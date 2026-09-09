#!/usr/bin/env python3
"""Build a photo warchest for Thanet from open, re-fetchable sources.

    photos.py catalogue [--source S] [--town T]   ask every source what it holds; no image bytes
    photos.py download  [--source S] [--town T] [--limit N] [--size hd|sd] [--dry-run]
    photos.py assign                              re-file an existing catalogue after editing towns
    photos.py credits                             regenerate CREDITS.md from the manifests
    photos.py status                              what is on disk

Two passes on purpose. Cataloguing the whole isle is a few MB of JSON and takes minutes;
downloading it is tens of GB. `catalogue` tells you the count and the byte estimate per town
and per source, and `download` is the step you scope with --town/--source/--limit once you
have seen that number. Nothing is downloaded twice: a file already on disk whose size matches
the catalogue is left alone, so an interrupted run resumes.

SOURCES (all keyless unless noted; every one verified live on 2026-09-09)

  panoramax  api.panoramax.xyz -- open street-level photography, CC-BY-SA-4.0. The best
             source here for photogrammetry: contiguous driven/walked SEQUENCES, so the
             overlap RealityScan needs is already in the data, and the `hd` asset is the
             untouched original with its EXIF (GPS, focal length) intact.
  geograph   Geograph Britain and Ireland, CC-BY-SA-2.0. One-to-many photos per OS 1 km
             square by design, so coverage is even rather than clustered on landmarks.
             Enumerated square by square, which is exhaustive rather than a radius sample.
             `_original.jpg` is the photographer's upload (commonly 2-4 MB).
  commons    Wikimedia Commons geosearch, mixed CC/PD (per-file, recorded in the manifest).
             Landmark-heavy and often the highest resolution of the three.
  commons_cat Wikimedia Commons walked by CATEGORY instead of coordinate, from per-town seeds
             in thanet_towns.json. Geosearch only returns files that carry a geotag, and much
             of the best landmark photography on Commons has none -- this is the pass that
             finds it. The cost is that a file with no coordinate falls back to the town
             anchor, flagged coord_exact false.
  mapillary  Needs a free token in MAPILLARY_TOKEN (mapillary.com/dashboard/developers).
             Skipped with a note when unset. Street-level like Panoramax but far denser in
             the UK, so set the token if you want volume.
  flickr     Needs a key in FLICKR_API_KEY. Only CC-licensed, geotagged results are taken.

DEDUPLICATION. A large slice of Commons IS Geograph, re-uploaded with the Geograph id in the
filename ("... - geograph.org.uk - 1622222.jpg"). Those are dropped from the Commons
catalogue when the same id is already in the Geograph one, rather than downloading the same
photograph twice under two licences. The count of drops is reported.

LICENSING. Every source here is share-alike or public domain, and CC-BY-SA REQUIRES
attribution. Each town keeps a MANIFEST.jsonl carrying the author, licence and source page
of every file, and `photos.py credits` rolls those into CREDITS.md. Do not ship a render
built from this data without carrying that attribution -- see images/README.md.

POLITENESS. One request per second to Geograph, three to the others, single connection each,
descriptive User-Agent. These are small volunteer-run services; the rate limits here are
deliberately below what they would tolerate. Raise them and you are the reason the endpoint
starts refusing.
"""
import argparse, hashlib, json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOWNS_CFG = os.path.join(ROOT, "sources", "config", "thanet_towns.json")
IMAGES = os.path.join(ROOT, "images")
CATALOGUE = os.path.join(IMAGES, "_catalogue")

# Wikimedia's User-Agent policy asks for a contact address. This carries none: the repo is the
# contact. If you run this at volume, put your own address in UA_CONTACT.
UA_CONTACT = os.environ.get("WARCHEST_CONTACT", "")
UA = ("3duk-thanet-warchest/1.0 (open-data photogrammetry corpus for a 3D map of Thanet"
      + (f"; {UA_CONTACT}" if UA_CONTACT else "") + ")")

SOURCES = ["panoramax", "geograph", "commons", "commons_cat", "mapillary", "flickr"]


# ---------------------------------------------------------------- http

class Throttle:
    """One token bucket per host. Serialises nothing else -- threads still overlap across hosts."""
    def __init__(self):
        self.lock, self.next_at = threading.Lock(), {}

    def wait(self, host, min_interval):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_at.get(host, 0.0))
            self.next_at[host] = t + min_interval
        if t > now:
            time.sleep(t - now)


THROTTLE = Throttle()
# Seconds between requests, per host. commons.wikimedia.org is 1.0 because the API answers
# HTTP 429 well before its documented limits when several callers overlap -- measured here on
# 2026-09-09 with a catalogue run and a second script in flight at ~3/s combined.
RATE = {"www.geograph.org.uk": 1.0, "api.geograph.org.uk": 1.0, "s0.geograph.org.uk": 1.0,
        "s1.geograph.org.uk": 1.0, "s2.geograph.org.uk": 1.0, "s3.geograph.org.uk": 1.0,
        "commons.wikimedia.org": 1.0, "upload.wikimedia.org": 0.5}
# The baseline each host returns to as requests succeed, so one 429 during a long download does
# not pin the rest of the run at the ceiling.
RATE_BASE = dict(RATE)
OK_STREAK = {}
RATE_DEFAULT = 0.34
# Ceiling on the 429 backoff below. It doubles per 429 and each retry of one request can
# trigger it again, so an unbounded rule reaches minutes per request after a brief wobble;
# observed on Commons on 2026-09-09, which climbed 1 -> 2 -> 4 -> 8 -> 16 s in four steps.
RATE_MAX = 20.0


def recover(host):
    """Ease a backed-off host back toward its baseline after a run of successes.

    The backoff below doubles on every 429 and, without this, never comes down: one burst
    early in a long download pins the host at RATE_MAX for hours. Observed on
    upload.wikimedia.org, which went to 20 s a minute into a 2,700-file download and would
    have taken 15 hours at that rate. Recovery is deliberately slower than the backoff --
    25 clean requests to halve the interval, against an instant doubling on a single 429.
    """
    cur = RATE.get(host)
    base = RATE_BASE.get(host, RATE_DEFAULT)
    if cur is None or cur <= base:
        return
    n = OK_STREAK.get(host, 0) + 1
    if n >= 25:
        RATE[host], OK_STREAK[host] = max(cur / 2, base), 0
    else:
        OK_STREAK[host] = n


def http(url, timeout=60, max_bytes=None, retries=3):
    """GET with per-host throttling and backoff. Returns (status, headers, body)."""
    host = urllib.parse.urlparse(url).netloc
    interval = RATE.get(host, RATE_DEFAULT)
    last = None
    for attempt in range(retries):
        THROTTLE.wait(host, interval)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(max_bytes) if max_bytes else r.read()
            recover(host)
            return r.status, r.headers, body
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code in (400, 401, 403, 404):        # not going to get better by asking again
                return e.code, {}, e.read(2000)
            if e.code == 429:
                # Being told to slow down is data, not noise: honour Retry-After and then
                # permanently halve this host's rate for the rest of the run, so one 429 does
                # not become a run of them.
                try:
                    delay = float(e.headers.get("Retry-After", "") or 0)
                except ValueError:
                    delay = 0.0
                RATE[host] = min(max(RATE.get(host, RATE_DEFAULT) * 2, 1.0), RATE_MAX)
                OK_STREAK[host] = 0
                print(f"    429 from {host}; backing off to {RATE[host]:.1f}s between requests")
                time.sleep(max(delay, 5.0 * (attempt + 1)))
                continue
            time.sleep(2 ** attempt)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url[:120]} failed after {retries}: {last}")


def get_json(url, **kw):
    st, _, body = http(url, **kw)
    if st != 200:
        raise RuntimeError(f"GET {url[:120]} -> {st}: {body[:200]!r}")
    return json.loads(body)


# ---------------------------------------------------------------- towns

def load_towns():
    cfg = json.load(open(TOWNS_CFG, encoding="utf-8"))
    anchors = []
    for t in cfg["towns"]:
        for a in t["anchors"]:
            anchors.append((t["slug"], a["lat"], a["lon"]))
    return cfg, anchors


def haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(a))


def assign_town(lat, lon, anchors, max_km):
    best, best_d = "_unassigned", 1e9
    for slug, alat, alon in anchors:
        d = haversine_km(lat, lon, alat, alon)
        if d < best_d:
            best, best_d = slug, d
    return (best, best_d) if best_d <= max_km else ("_unassigned", best_d)


def in_bbox(lat, lon, bbox):
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e


# ---------------------------------------------------------------- panoramax

PANORAMAX_PAGE = 1000


def cat_panoramax(cfg, log):
    """Adaptive quadtree over /api/search.

    /api/search answers at most PANORAMAX_PAGE features and returns NO rel=next cursor, so a
    busy cell is silently truncated -- the first version of this function stopped at exactly
    1000 items for the whole isle and looked like a complete answer. A cell that comes back
    full is therefore assumed to be truncated and is split into four, recursively, until every
    leaf is under the cap. That makes the result self-verifying: no leaf is at the limit.

    Enumerating collections instead does not work here. Ten collections intersect the Thanet
    bbox and seven of them are worldwide mapcomplete batches -- 80k pictures, almost all of
    them nowhere near Kent -- so the per-collection route pages through two orders of
    magnitude more JSON than the area contains.
    """
    s, w, n, e = cfg["bbox_wgs84"]
    out, seen, cells, saturated = [], set(), 0, 0
    stack = [(s, w, n, e, 0)]
    while stack:
        cs, cw, cn, ce, depth = stack.pop()
        d = get_json(f"https://api.panoramax.xyz/api/search"
                     f"?bbox={cw},{cs},{ce},{cn}&limit={PANORAMAX_PAGE}", timeout=120)
        feats = d.get("features", [])
        cells += 1
        if len(feats) >= PANORAMAX_PAGE and depth < 12:
            mlat, mlon = (cs + cn) / 2, (cw + ce) / 2
            stack += [(cs, cw, mlat, mlon, depth + 1), (cs, mlon, mlat, ce, depth + 1),
                      (mlat, cw, cn, mlon, depth + 1), (mlat, mlon, cn, ce, depth + 1)]
            continue
        if len(feats) >= PANORAMAX_PAGE:
            saturated += 1
        for f in feats:
            fid = f.get("id")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            g = (f.get("geometry") or {}).get("coordinates") or [None, None]
            if g[0] is None:
                continue
            p = f.get("properties", {}) or {}
            assets = f.get("assets", {}) or {}
            lic = next((l.get("href") for l in f.get("links", []) if l.get("rel") == "license"),
                       "https://creativecommons.org/licenses/by-sa/4.0/")
            prov = ", ".join(x.get("name", "") for x in (f.get("providers") or []) if x.get("name"))
            # properties.collection is sometimes an object rather than the id string, so take
            # the id from the rel=collection link, which is always .../collections/<uuid>.
            chref = next((l.get("href", "") for l in f.get("links", [])
                          if l.get("rel") == "collection"), "")
            seq = chref.rstrip("/").split("/collections/")[-1].split("/")[0] if chref else ""
            out.append({
                "id": f"panoramax:{fid}", "source": "panoramax",
                "lat": g[1], "lon": g[0],
                "title": p.get("title") or "",
                "author": prov or p.get("providers") or "unknown",
                "date": (p.get("datetime") or "")[:10],
                "licence": "CC BY-SA 4.0", "licence_url": lic,
                "page": next((l["href"] for l in f.get("links", [])
                              if l.get("rel") == "self"), ""),
                "url_hd": (assets.get("hd") or {}).get("href", ""),
                "url_sd": (assets.get("sd") or {}).get("href", ""),
                "sequence": seq,
                "field_of_view": p.get("pers:interior_orientation", {}).get("field_of_view"),
                "make_model": " ".join(filter(None, [
                    str(p.get("pers:interior_orientation", {}).get("make") or ""),
                    str(p.get("pers:interior_orientation", {}).get("model") or "")])).strip(),
                "type": p.get("pers:imagery_type") or "flat",
                "ext": ".jpg",
            })
        if cells % 10 == 0 or not stack:
            log(f"  panoramax: {cells} cells searched, {len(stack)} queued, {len(out)} pictures")
    if saturated:
        log(f"  WARNING: {saturated} cells were still at the {PANORAMAX_PAGE} cap at max depth "
            f"-- those cells are truncated and hold more than is catalogued here.")
    return [r for r in out if r["url_hd"] or r["url_sd"]]


# ---------------------------------------------------------------- geograph

def osgb_squares(bbox_en):
    """1 km OS grid squares over an easting/northing rectangle, as TRxxyy refs.

    Thanet is entirely inside the TR 100 km square (origin E 600000, N 100000), so the
    two-letter prefix is constant and the four digits are just (E-600000)/1000 and
    (N-100000)/1000. No projection is done here: the rectangle is a superset of the isle and
    every returned photo carries its own lat/lon, which is what the assignment actually uses.
    """
    e0, n0, e1, n1 = bbox_en
    out = []
    for ee in range(int(e0) // 1000, int(e1) // 1000 + 1):
        for nn in range(int(n0) // 1000, int(n1) // 1000 + 1):
            out.append(f"TR{ee - 600:02d}{nn - 100:02d}")
    return out


GEOGRAPH_THUMB = re.compile(r"^(.*?)(_\d+x\d+)?\.jpg$", re.I)


def cat_geograph(cfg, log):
    """Enumerate every OS 1 km square over Thanet through the JSON syndicator.

    Three parameters matter and none of them are guessable:
      distance=1  means 'in this grid square', not 'within 1 km'. OMITTING it defaults to a
                  10 km radius, which returns the whole isle for every square and looks like
                  a working enumeration while being 200x redundant.
      perpage=100 is honoured; `limit`, `num`, `count`, `pagesize` and `max` are all silently
                  ignored and leave you on 15 results a page (~15k requests for Thanet).
      key=        may be empty. The feed serves anonymous callers.
    Paging then follows nextURL. Full resolution is the thumb URL with the _120x120 size
    suffix replaced by _original -- verified 2026-09-09: 120x120 is 4 KB, _original is 2.8 MB.

    The 247 MB gridimage_base.tsv.gz bulk dump is the other route and is authoritative, but it
    carries no image-URL hash, so every download would still need a per-photo lookup. The
    syndicator gives metadata and hash together.
    """
    squares = osgb_squares((626000, 160000, 642000, 173000))
    out, seen = [], set()
    for k, sq in enumerate(squares, 1):
        url = (f"https://api.geograph.org.uk/syndicator.php?key=&format=JSON"
               f"&location={sq}&distance=1&perpage=100")
        page, got = 0, 0
        while url and page < 40:
            try:
                d = get_json(url, timeout=90)
            except Exception as e:
                log(f"  geograph {sq} page {page}: {e}")
                break
            items = d.get("items") or []
            for it in items:
                gid = str(it.get("guid") or "")
                if not gid or gid in seen:
                    continue
                try:
                    lat, lon = float(it["lat"]), float(it["long"])
                except (KeyError, TypeError, ValueError):
                    continue
                seen.add(gid)
                thumb = it.get("thumb") or ""
                m = GEOGRAPH_THUMB.match(thumb)
                full = f"{m.group(1)}_original.jpg" if m else thumb
                out.append({
                    "id": f"geograph:{gid}", "source": "geograph",
                    "lat": lat, "lon": lon,
                    "title": it.get("title") or "",
                    "description": it.get("description") or "",
                    "author": it.get("author") or "unknown",
                    "author_url": it.get("source") or "",
                    "date": it.get("imageTaken") or "",
                    "licence": "CC BY-SA 2.0",
                    "licence_url": it.get("licence") or "http://creativecommons.org/licenses/by-sa/2.0/",
                    "page": it.get("link") or f"https://www.geograph.org.uk/photo/{gid}",
                    "url_hd": full, "url_sd": f"{m.group(1)}_1024x1024.jpg" if m else thumb,
                    "grid_square": sq,
                    "tags": (it.get("tags") or "").replace("?", "; "),
                    "ext": ".jpg",
                })
                got += 1
            page += 1
            url = d.get("nextURL")
            if not items:
                break
        if k % 20 == 0 or got:
            log(f"  geograph {sq} ({k}/{len(squares)}): +{got} (total {len(out)})")
    return out


# ---------------------------------------------------------------- commons

COMMONS_PAGE = 500


def cat_commons(cfg, log):
    """Adaptive quadtree over geosearch, in ggsbbox form.

    geosearch answers at most COMMONS_PAGE results and offers no continuation, so a full cell
    is a truncated cell. The first version tiled the area with fixed 1.2 km discs and 12 of
    them came back at the cap -- an unknown number of files in the densest parts of Margate,
    Broadstairs and Ramsgate were simply never listed. Splitting a full cell into four and
    re-asking makes the enumeration self-verifying: if nothing is at the cap, nothing is missed.

    ggsbbox is `top|left|bottom|right`, i.e. maxlat|minlon|minlat|maxlon, which is neither the
    Overpass order used elsewhere in this repo nor GeoJSON's.
    """
    s, w, n, e = cfg["bbox_wgs84"]
    out, seen, saturated, cells = [], set(), 0, 0
    stack = [(s, w, n, e, 0)]
    while stack:
        cs, cw, cn, ce, depth = stack.pop()
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
               f"&generator=geosearch&ggsbbox={cn:.6f}%7C{cw:.6f}%7C{cs:.6f}%7C{ce:.6f}"
               f"&ggslimit={COMMONS_PAGE}&ggsnamespace=6"
               "&prop=imageinfo&iiprop=url%7Csize%7Cmime%7Cextmetadata")
        try:
            d = get_json(url, timeout=90)
        except Exception as ex:
            log(f"  commons cell at depth {depth}: {ex}")
            continue
        cells += 1
        pages = (d.get("query") or {}).get("pages") or {}
        if len(pages) >= COMMONS_PAGE and depth < 12:
            mlat, mlon = (cs + cn) / 2, (cw + ce) / 2
            stack += [(cs, cw, mlat, mlon, depth + 1), (cs, mlon, mlat, ce, depth + 1),
                      (mlat, cw, cn, mlon, depth + 1), (mlat, mlon, cn, ce, depth + 1)]
            continue
        if len(pages) >= COMMONS_PAGE:
            saturated += 1
        clat, clon = (cs + cn) / 2, (cw + ce) / 2
        got = 0
        for pid, p in pages.items():
            if pid in seen:
                continue
            ii = (p.get("imageinfo") or [{}])[0]
            if not ii.get("url") or not str(ii.get("mime", "")).startswith("image/"):
                continue
            em = ii.get("extmetadata") or {}

            def meta(key):
                v = (em.get(key) or {}).get("value") or ""
                return re.sub(r"<[^>]+>", "", str(v)).strip()

            gps = (em.get("GPSLatitude") or {}).get("value"), (em.get("GPSLongitude") or {}).get("value")
            try:
                lat_i, lon_i = float(gps[0]), float(gps[1])
            except (TypeError, ValueError):
                # No EXIF GPS in the file's metadata even though geosearch matched it on the
                # page's own coordinate. Fall back to the cell centre and flag it: coord_exact
                # false means "somewhere in this cell", which town assignment tolerates and a
                # reconstruction must not trust.
                lat_i, lon_i = clat, clon
            seen.add(pid)
            out.append({
                "id": f"commons:{pid}", "source": "commons",
                "lat": lat_i, "lon": lon_i,
                "coord_exact": gps[0] is not None,
                "title": p.get("title", ""),
                "author": meta("Artist") or "unknown",
                "date": meta("DateTimeOriginal")[:10],
                "licence": meta("LicenseShortName") or "see page",
                "licence_url": (em.get("LicenseUrl") or {}).get("value") or "",
                "page": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(p.get('title',''))}",
                "url_hd": ii["url"].split("?")[0],
                "url_sd": ii["url"].split("?")[0],
                "width": ii.get("width"), "height": ii.get("height"),
                "bytes_hint": ii.get("size"),
                "ext": os.path.splitext(urllib.parse.unquote(ii["url"].split("?")[0]))[1] or ".jpg",
            })
            got += 1
        if cells % 10 == 0 or got:
            log(f"  commons: {cells} cells searched, {len(stack)} queued, +{got} "
                f"(total {len(out)})")
    if saturated:
        log(f"  WARNING: {saturated} cells were still at the {COMMONS_PAGE} cap at max depth "
            f"-- those cells are truncated and hold more than is catalogued here.")
    return out


# ---------------------------------------------------------------- commons categories

# Category branches that are not photographs OF the place. Two kinds, both learned by watching
# the walk go wrong: media that is not a photograph (maps, engravings, sheet music), and
# ORGANISATIONS AND PEOPLE. The second is the one that bites -- Category:Margate, Kent contains
# Category:Margate F.C., which at depth 3 reaches the squad, and the walk cheerfully collects
# several hundred portraits of footballers as "imagery of Margate". This list is a heuristic and
# will not be complete; `via_category` is recorded on every row so a bad branch can be filtered
# out afterwards without re-walking.
CAT_SKIP = re.compile(r"\b(maps?|coats? of arms|flags?|books?|sheet music|videos?|audio|"
                      r"logos?|timetables?|documents?|diagrams?|plaques of|postcards? of|"
                      r"engravings?|paintings?|drawings?|prints?|"
                      r"f\.?c\.?|football|players|footballers|managers|squads?|"
                      r"people|persons|men|women|births|deaths|portraits?|"
                      r"politicians|writers|artists|musicians|bands|albums|singles|"
                      r"films?|television|posters|stamps|coins|banknotes|"
                      r"mayors|councillors|residents|natives|alumni|"
                      # Date partitions: "Ramsgate by year" -> "1890s in Ramsgate" -> ... Those
                      # re-file photographs already collected under the parent, so they add no
                      # files while queueing hundreds of rate-limited requests. Observed: one
                      # such branch queued 224 categories for zero new files.
                      r"by year|by decade|by month|by date|\d{4}s?\ in)\b", re.I)
IMG_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")


def cat_commons_cat(cfg, log):
    """Walk Commons CATEGORIES per town, not coordinates.

    This exists because geosearch has a blind spot that matters: it only returns files
    carrying a coordinate. A large share of the best landmark photography on Commons is filed
    in `Category:Dreamland Margate` or `Category:Shell Grotto, Margate` with no geotag at all,
    and the geosearch pass cannot see any of it. Categories are the curated index Commons
    actually maintains, so this walks them from per-town seeds in thanet_towns.json.

    The trade is position quality. A file found this way may have no coordinate, so its
    lat/lon falls back to the town's first anchor and `coord_exact` is false. That is fine for
    filing it under a town and for finding subjects; it is NOT a position to reconstruct from.

    Seeds are verified category names, resolved 2026-09-09 -- `Category:Margate` is a
    disambiguation page holding zero files, and the real one is `Category:Margate, Kent`.
    Likewise Minster in Thanet, Westwood, Thanet and Acol, Kent. Guessing `Category:<town>`
    silently returns nothing for half the isle.
    """
    seeds = [(t["slug"], c) for t in cfg["towns"] for c in t.get("commons_categories", [])]
    if not seeds:
        log("  commons_cat: no commons_categories in thanet_towns.json -- nothing to walk")
        return []
    anchor = {t["slug"]: (t["anchors"][0]["lat"], t["anchors"][0]["lon"]) for t in cfg["towns"]}
    depth_max = 3
    files, seen_cat, skipped = {}, set(), 0

    # Every other town's seed is a WALL for this walk. Commons nests places the way
    # administration does, so Category:Cliftonville, Category:Garlinge and
    # Category:Westbrook, Kent all sit under Category:Margate, Kent -- and a plain BFS from
    # Margate swallows all three, files their photographs under margate, and leaves the
    # cliftonville walk reporting zero new files because everything was already claimed.
    # Stopping at another seed keeps each town's imagery in its own folder.
    seed_cats = {c for _, c in seeds}

    for slug, seed in seeds:
        queue = [(seed, 0)]
        while queue:
            cat, depth = queue.pop(0)
            if cat in seen_cat or (cat != seed and cat in seed_cats):
                continue
            seen_cat.add(cat)
            cont = None
            while True:
                url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
                       f"&list=categorymembers&cmtitle={urllib.parse.quote(cat)}"
                       "&cmlimit=500&cmtype=file%7Csubcat")
                if cont:
                    url += f"&cmcontinue={urllib.parse.quote(cont)}"
                try:
                    d = get_json(url, timeout=90)
                except Exception as ex:
                    log(f"  commons_cat {cat}: {ex}")
                    break
                for m in (d.get("query") or {}).get("categorymembers", []):
                    title = m.get("title", "")
                    if m.get("ns") == 14:
                        if depth + 1 <= depth_max and not CAT_SKIP.search(title):
                            queue.append((title, depth + 1))
                        elif CAT_SKIP.search(title):
                            skipped += 1
                    elif m.get("ns") == 6 and title.lower().endswith(IMG_EXT):
                        files.setdefault(title, (slug, cat))
                cont = (d.get("continue") or {}).get("cmcontinue")
                if not cont:
                    break
            # Per CATEGORY, not per seed. A seed like Category:Margate, Kent expands to tens of
            # subcategories, and Commons throttles anonymous callers hard enough that one seed
            # can take ten minutes -- logging only on completion looks indistinguishable from
            # a hang.
            log(f"    {'  ' * depth}{cat[9:][:52]:52s} files {len(files)}, "
                f"{len(queue)} categories queued")
        log(f"  commons_cat {slug:16s} {seed[:38]:38s} DONE, files so far {len(files)}")
    log(f"  commons_cat: {len(seen_cat)} categories walked, {skipped} non-photo branches "
        f"skipped, {len(files)} candidate files")

    # imageinfo in batches of 50 -- the API's limit for an unauthenticated titles= query.
    out, titles = [], sorted(files)
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
               "&prop=imageinfo&iiprop=url%7Csize%7Cmime%7Cextmetadata&titles="
               + urllib.parse.quote("|".join(batch)))
        try:
            d = get_json(url, timeout=120)
        except Exception as ex:
            log(f"  commons_cat imageinfo batch {i//50}: {ex}")
            continue
        for pid, p in ((d.get("query") or {}).get("pages") or {}).items():
            ii = (p.get("imageinfo") or [{}])[0]
            if not ii.get("url") or not str(ii.get("mime", "")).startswith("image/"):
                continue
            title = p.get("title", "")
            slug, via = files.get(title, ("_unassigned", ""))
            em = ii.get("extmetadata") or {}

            def meta(key):
                v = (em.get(key) or {}).get("value") or ""
                return re.sub(r"<[^>]+>", "", str(v)).strip()

            gps = (em.get("GPSLatitude") or {}).get("value"), (em.get("GPSLongitude") or {}).get("value")
            try:
                lat_i, lon_i, exact = float(gps[0]), float(gps[1]), True
            except (TypeError, ValueError):
                lat_i, lon_i = anchor.get(slug, (0.0, 0.0))
                exact = False
            out.append({
                "id": f"commons:{pid}", "source": "commons_cat",
                "lat": lat_i, "lon": lon_i, "coord_exact": exact,
                "seed_town": slug,
                "via_category": via,
                "title": title,
                "author": meta("Artist") or "unknown",
                "date": meta("DateTimeOriginal")[:10],
                "licence": meta("LicenseShortName") or "see page",
                "licence_url": (em.get("LicenseUrl") or {}).get("value") or "",
                "page": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title)}",
                "url_hd": ii["url"].split("?")[0], "url_sd": ii["url"].split("?")[0],
                "width": ii.get("width"), "height": ii.get("height"),
                "bytes_hint": ii.get("size"),
                "ext": os.path.splitext(urllib.parse.unquote(ii["url"].split("?")[0]))[1] or ".jpg",
            })
        if (i // 50) % 10 == 0:
            log(f"  commons_cat imageinfo {i + len(batch)}/{len(titles)}")
    return out


# ---------------------------------------------------------------- mapillary / flickr (keyed)

def cat_mapillary(cfg, log):
    tok = os.environ.get("MAPILLARY_TOKEN", "").strip()
    if not tok:
        log("  mapillary: MAPILLARY_TOKEN unset -- skipped. Get a free token at "
            "https://www.mapillary.com/dashboard/developers and re-run to add it.")
        return []
    s, w, n, e = cfg["bbox_wgs84"]
    out = []
    step = 0.02
    lat = s
    cells = []
    while lat < n:
        lon = w
        while lon < e:
            cells.append((lat, lon, min(lat + step, n), min(lon + step, e)))
            lon += step
        lat += step
    for k, (s2, w2, n2, e2) in enumerate(cells, 1):
        url = ("https://graph.mapillary.com/images?access_token=" + urllib.parse.quote(tok) +
               f"&bbox={w2},{s2},{e2},{n2}&limit=2000"
               "&fields=id,computed_geometry,geometry,captured_at,compass_angle,"
               "thumb_original_url,thumb_2048_url,creator,sequence,camera_type")
        try:
            d = get_json(url, timeout=120)
        except Exception as ex:
            log(f"  mapillary cell {k}/{len(cells)}: {ex}")
            continue
        for it in d.get("data", []):
            g = (it.get("computed_geometry") or it.get("geometry") or {}).get("coordinates")
            if not g:
                continue
            ts = it.get("captured_at")
            out.append({
                "id": f"mapillary:{it['id']}", "source": "mapillary",
                "lat": g[1], "lon": g[0],
                "title": "", "author": (it.get("creator") or {}).get("username", "unknown"),
                "date": time.strftime("%Y-%m-%d", time.gmtime(ts / 1000)) if ts else "",
                "licence": "CC BY-SA 4.0",
                "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                "page": f"https://www.mapillary.com/app/?focus=photo&pKey={it['id']}",
                "url_hd": it.get("thumb_original_url") or it.get("thumb_2048_url") or "",
                "url_sd": it.get("thumb_2048_url") or "",
                "sequence": it.get("sequence") or "",
                "compass_angle": it.get("compass_angle"),
                "type": it.get("camera_type") or "",
                "ext": ".jpg",
            })
        if k % 10 == 0:
            log(f"  mapillary cell {k}/{len(cells)}: total {len(out)}")
    return [r for r in out if r["url_hd"]]


def cat_flickr(cfg, log):
    key = os.environ.get("FLICKR_API_KEY", "").strip()
    if not key:
        log("  flickr: FLICKR_API_KEY unset -- skipped. Get one at "
            "https://www.flickr.com/services/apps/create/apply/ and re-run to add it.")
        return []
    s, w, n, e = cfg["bbox_wgs84"]
    # 1,2,3 = BY-SA / BY-NC-SA-ish set; 4,5,6,7,9,10 = BY, BY-SA, BY-ND, BY-NC-ND, PD, CC0.
    # Only the ones that permit derivative works are useful for a 3D reconstruction.
    lic = "4,5,7,9,10"
    out, page = [], 1
    while page <= 20:
        url = ("https://api.flickr.com/services/rest/?method=flickr.photos.search"
               f"&api_key={urllib.parse.quote(key)}&format=json&nojsoncallback=1"
               f"&bbox={w},{s},{e},{n}&license={lic}&has_geo=1&per_page=250&page={page}"
               "&extras=geo,license,owner_name,date_taken,url_o,url_k,url_h,o_dims")
        try:
            d = get_json(url, timeout=90)
        except Exception as ex:
            log(f"  flickr page {page}: {ex}")
            break
        ph = (d.get("photos") or {})
        for it in ph.get("photo", []):
            u = it.get("url_o") or it.get("url_k") or it.get("url_h")
            if not u:
                continue
            out.append({
                "id": f"flickr:{it['id']}", "source": "flickr",
                "lat": float(it.get("latitude", 0)), "lon": float(it.get("longitude", 0)),
                "title": it.get("title", ""), "author": it.get("ownername", "unknown"),
                "date": (it.get("datetaken") or "")[:10],
                "licence": f"Flickr licence id {it.get('license')}",
                "licence_url": "https://www.flickr.com/creativecommons/",
                "page": f"https://www.flickr.com/photos/{it.get('owner')}/{it['id']}",
                "url_hd": u, "url_sd": it.get("url_h") or u, "ext": ".jpg",
            })
        log(f"  flickr page {page}/{ph.get('pages', '?')}: total {len(out)}")
        if page >= int(ph.get("pages", 1) or 1):
            break
        page += 1
    return out


CATALOGUERS = {"panoramax": cat_panoramax, "geograph": cat_geograph, "commons": cat_commons,
               "commons_cat": cat_commons_cat,
               "mapillary": cat_mapillary, "flickr": cat_flickr}


# ---------------------------------------------------------------- catalogue / assign

COMMONS_GEOGRAPH = re.compile(r"geograph\.org\.uk\s*-\s*(\d+)", re.I)


def do_catalogue(args):
    cfg, anchors = load_towns()
    os.makedirs(CATALOGUE, exist_ok=True)
    todo = [args.source] if args.source else SOURCES
    for src in todo:
        print(f"[{src}] cataloguing ...")
        t0 = time.time()
        rows = CATALOGUERS[src](cfg, lambda m: print(m, flush=True))
        rows = [r for r in rows if in_bbox(r["lat"], r["lon"], cfg["bbox_wgs84"])]
        for r in rows:
            r["town"], d = assign_town(r["lat"], r["lon"], anchors, cfg["max_km"])
            r["anchor_km"] = round(d, 3)
        path = os.path.join(CATALOGUE, f"{src}.json")
        json.dump({"source": src, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "bbox_wgs84": cfg["bbox_wgs84"], "count": len(rows), "items": rows},
                  open(path, "w", encoding="utf-8"), indent=1)
        print(f"[{src}] {len(rows)} items in {time.time()-t0:.0f}s -> {os.path.relpath(path, ROOT)}")
    if getattr(args, "dedupe", False):
        dedupe_commons()
    else:
        print("[dedupe] skipped (pass --dedupe to drop Commons files that duplicate Geograph "
              "or another Commons pass)")
    summarise()


def dedupe_commons():
    """Drop Commons entries that duplicate something already catalogued.

    Two overlaps, both large:
      * a big share of Commons IS Geograph, re-uploaded with the Geograph id in the filename;
      * commons_cat (category walk) and commons (geosearch) find the same file whenever it is
        both geotagged and categorised, and they key on the same pageid.
    Dropping these here rather than at download time keeps the byte estimate honest.
    """
    gpath = os.path.join(CATALOGUE, "geograph.json")
    have_geo = set()
    if os.path.exists(gpath):
        have_geo = {r["id"].split(":", 1)[1]
                    for r in json.load(open(gpath, encoding="utf-8"))["items"]}

    seen_pageids = set()
    for name in ("commons", "commons_cat"):          # geosearch first: it has real coordinates
        path = os.path.join(CATALOGUE, f"{name}.json")
        if not os.path.exists(path):
            continue
        c = json.load(open(path, encoding="utf-8"))
        kept, drop_geo, drop_dup = [], 0, 0
        for r in c["items"]:
            m = COMMONS_GEOGRAPH.search(r.get("title", ""))
            if m and m.group(1) in have_geo:
                drop_geo += 1
                continue
            pid = r["id"].split(":", 1)[1]
            if pid in seen_pageids:
                drop_dup += 1
                continue
            seen_pageids.add(pid)
            kept.append(r)
        c["items"], c["count"] = kept, len(kept)
        c["deduped_against_geograph"], c["deduped_against_other_commons"] = drop_geo, drop_dup
        json.dump(c, open(path, "w", encoding="utf-8"), indent=1)
        print(f"[dedupe] {name}: dropped {drop_geo} Geograph re-uploads and {drop_dup} already "
              f"held by another Commons pass; {len(kept)} remain")


def do_assign(args):
    """Re-run town assignment over existing catalogues after editing thanet_towns.json."""
    cfg, anchors = load_towns()
    for src in SOURCES:
        p = os.path.join(CATALOGUE, f"{src}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        moved = 0
        for r in d["items"]:
            t, dist = assign_town(r["lat"], r["lon"], anchors, cfg["max_km"])
            if r.get("town") != t:
                moved += 1
            r["town"], r["anchor_km"] = t, round(dist, 3)
        json.dump(d, open(p, "w", encoding="utf-8"), indent=1)
        print(f"[{src}] reassigned; {moved} items changed town")
    summarise()


def load_catalogues(source=None, town=None):
    rows = []
    for src in ([source] if source else SOURCES):
        p = os.path.join(CATALOGUE, f"{src}.json")
        if os.path.exists(p):
            rows += json.load(open(p, encoding="utf-8"))["items"]
    if town:
        rows = [r for r in rows if r.get("town") == town]
    return rows


# per-source mean bytes of a full-resolution file, measured on sample downloads 2026-09-09
MEAN_BYTES = {"panoramax": 2_900_000, "geograph": 2_600_000, "commons": 1_900_000,
              "commons_cat": 1_900_000, "mapillary": 2_400_000, "flickr": 3_200_000}


def summarise():
    cfg, _ = load_towns()
    rows = load_catalogues()
    if not rows:
        print("no catalogue yet -- run: photos.py catalogue")
        return
    by = {}
    for r in rows:
        by.setdefault(r.get("town", "_unassigned"), {}).setdefault(r["source"], 0)
        by[r["town"]][r["source"]] += 1
    srcs = [s for s in SOURCES if any(s in v for v in by.values())]
    w = max(len(t) for t in by) + 2
    print("\n" + "town".ljust(w) + "".join(s[:9].rjust(11) for s in srcs) +
          "total".rjust(10) + "est. GB".rjust(10))
    print("-" * (w + 11 * len(srcs) + 20))
    order = [t["slug"] for t in cfg["towns"]] + ["_unassigned"]
    tot_n = tot_b = 0
    for t in order:
        if t not in by:
            continue
        n = sum(by[t].values())
        b = sum(by[t].get(s, 0) * MEAN_BYTES[s] for s in by[t])
        tot_n, tot_b = tot_n + n, tot_b + b
        print(t.ljust(w) + "".join(str(by[t].get(s, 0)).rjust(11) for s in srcs) +
              str(n).rjust(10) + f"{b/1e9:.1f}".rjust(10))
    print("-" * (w + 11 * len(srcs) + 20))
    print("TOTAL".ljust(w) + "".join(
        str(sum(by[t].get(s, 0) for t in by)).rjust(11) for s in srcs) +
        str(tot_n).rjust(10) + f"{tot_b/1e9:.1f}".rjust(10))
    print("\nest. GB is count x the mean full-resolution file size measured per source, not a "
          "sum of real Content-Lengths. Treat it as +/- 30%.")
    json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "by_town": by, "total": tot_n, "est_bytes": tot_b},
              open(os.path.join(CATALOGUE, "summary.json"), "w"), indent=1)


# ---------------------------------------------------------------- download

def target_path(r):
    ident = r["id"].split(":", 1)[1]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", ident)[:120]
    return os.path.join(IMAGES, r["town"], r["source"], safe + r.get("ext", ".jpg"))


JPEG_MAGIC = b"\xff\xd8\xff"
GEOGRAPH_SIZED = re.compile(r"(_(?:original|\d+x\d+))?\.jpg$", re.I)


def candidate_urls(r, size):
    """Ordered URLs to try for one record, largest acceptable first.

    Geograph needs a fallback chain and it is not optional: `_original.jpg` is the
    photographer's upload and is what you want, but it only exists for images uploaded above
    the old display size. For anything older the derivative was never made and every sized
    variant 404s -- only the plain `.jpg` exists.

    Measured over the completed Thanet download, not estimated: **34%** of 8,659 Geograph
    images (2,905 of them) had no `_original` and came from the plain rung. Those are ~100 KB
    median against 789 KB for `_original`, so a third of this corpus is roughly 640 px and is
    reference material rather than reconstruction input. Without the chain all 2,905 would
    simply have 404'd -- an early run, judged on its first thousand records, put the figure at
    5% and was wrong by a factor of seven.
    """
    first = r.get("url_hd") if size == "hd" else (r.get("url_sd") or r.get("url_hd"))
    urls = [first] if first else []
    if r.get("source") == "geograph" and first:
        base = GEOGRAPH_SIZED.sub("", first)
        for suf in ("_original.jpg", "_1024x1024.jpg", "_800x800.jpg", ".jpg"):
            if base + suf not in urls:
                urls.append(base + suf)
    for alt in (r.get("url_sd"), r.get("url_hd")):
        if alt and alt not in urls:
            urls.append(alt)
    return urls


def download_one(r, size):
    path = target_path(r)
    urls = candidate_urls(r, size)
    if not urls:
        return ("skip", r, 0, "no url")
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return ("cached", r, os.path.getsize(path), "")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body, url, st, why = None, None, 0, ""
    for cand in urls:
        try:
            st, _, b = http(cand, timeout=180)
        except Exception as e:
            why = str(e)[:120]
            continue
        if st == 200 and len(b) >= 1024:
            body, url = b, cand
            break
        why = f"HTTP {st}" if st != 200 else f"short body {len(b)}B"
    if body is None:
        return ("fail", r, 0, f"{why} (tried {len(urls)} url{'s' if len(urls) != 1 else ''})")
    if len(body) < 1024:
        return ("fail", r, 0, f"short body {len(body)}B")
    if r.get("ext", ".jpg").lower() in (".jpg", ".jpeg") and not body.startswith(JPEG_MAGIC):
        return ("fail", r, 0, f"not a JPEG (starts {body[:8]!r}) -- probably an error page")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path)
    r["file"] = os.path.relpath(path, IMAGES).replace("\\", "/")
    r["bytes"] = len(body)
    r["sha256"] = hashlib.sha256(body).hexdigest()
    r["fetched"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    r["url_used"] = url                    # which rung of the fallback chain actually served
    return ("ok", r, len(body), "")


def interleave_by_host(rows, size):
    """Round-robin the download order across image hosts.

    The throttle is per host, so throughput is (number of distinct hosts in flight) / interval.
    Geograph serves from s0-s3 and shards by the image id, which means id order is also, near
    enough, host order -- and the natural sort by (town, source, id) then parks every worker
    thread on the same host. Measured: 186 files in three minutes, about 1/s, against the 4/s
    the four hosts allow. Interleaving restores it without raising the per-host rate at all.
    """
    buckets = {}
    for r in rows:
        u = (r.get("url_hd") if size == "hd" else (r.get("url_sd") or r.get("url_hd"))) or ""
        buckets.setdefault(urllib.parse.urlparse(u).netloc, []).append(r)
    order, keys = [], sorted(buckets)
    for i in range(max((len(v) for v in buckets.values()), default=0)):
        for k in keys:
            if i < len(buckets[k]):
                order.append(buckets[k][i])
    return order


def do_download(args):
    rows = load_catalogues(args.source, args.town)
    rows = [r for r in rows if r.get("town") != "_unassigned" or args.include_unassigned]
    rows.sort(key=lambda r: (r.get("town", ""), r["source"], r["id"]))
    if args.limit:
        keep, per = [], {}
        for r in rows:
            k = (r["town"], r["source"])
            if per.get(k, 0) < args.limit:
                per[k] = per.get(k, 0) + 1
                keep.append(r)
        rows = keep
    if not rows:
        print("nothing to download -- run `photos.py catalogue` first, or widen --town/--source")
        return
    rows = interleave_by_host(rows, args.size)
    est = sum(MEAN_BYTES[r["source"]] for r in rows)
    print(f"{len(rows)} images, ~{est/1e9:.1f} GB at --size {args.size}")
    if args.dry_run:
        by = {}
        for r in rows:
            by[(r["town"], r["source"])] = by.get((r["town"], r["source"]), 0) + 1
        for (t, s), n in sorted(by.items()):
            print(f"  {t:18s} {s:11s} {n:6d}")
        return
    counts = {"ok": 0, "cached": 0, "fail": 0, "skip": 0}
    got = 0
    done_rows, t0 = [], time.time()
    with ThreadPoolExecutor(args.jobs) as ex:
        for i, (status, r, nb, msg) in enumerate(
                ex.map(lambda r: download_one(r, args.size), rows), 1):
            counts[status] += 1
            got += nb
            done_rows.append(r)
            if status == "fail":
                print(f"  FAIL {r['id']}: {msg}")
            if i % 100 == 0 or i == len(rows):
                rate = got / max(time.time() - t0, 1e-9) / 1e6
                print(f"  {i}/{len(rows)}  ok={counts['ok']} cached={counts['cached']} "
                      f"fail={counts['fail']}  {got/1e9:.2f} GB  {rate:.1f} MB/s", flush=True)
    write_manifests(done_rows)
    print(f"\ndownloaded {counts['ok']}, cached {counts['cached']}, failed {counts['fail']}, "
          f"{got/1e9:.2f} GB in {time.time()-t0:.0f}s")
    do_credits(args)


def write_manifests(rows):
    """One JSONL per town, merged with whatever is already recorded there.

    Read-modify-write with no lock. Two `download` runs covering the SAME town at the same
    time can therefore lose one side's records -- the image files are all still on disk, but
    the manifest, and so CREDITS.md, would under-report them. Running one download at a time
    per town avoids it; `photos.py credits` cannot repair it, because the licence and author
    live only in the catalogue and the manifest. Concurrent runs on DIFFERENT towns or
    different sources within a town are fine: each run writes only at the end.
    """
    by = {}
    for r in rows:
        if r.get("file"):
            by.setdefault(r["town"], {})[r["id"]] = r
    for town, recs in by.items():
        p = os.path.join(IMAGES, town, "MANIFEST.jsonl")
        existing = {}
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line:
                    try:
                        o = json.loads(line)
                        existing[o["id"]] = o
                    except json.JSONDecodeError:
                        pass
        existing.update(recs)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for k in sorted(existing):
                f.write(json.dumps(existing[k], ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- credits / status

def read_manifests():
    out = {}
    if not os.path.isdir(IMAGES):
        return out
    for town in sorted(os.listdir(IMAGES)):
        p = os.path.join(IMAGES, town, "MANIFEST.jsonl")
        if os.path.exists(p):
            rows = []
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            out[town] = rows
    return out


def do_credits(args=None):
    mans = read_manifests()
    if not mans:
        print("no manifests yet")
        return
    lines = ["# Credits",
             "",
             "Every image in this directory was published by someone else under a licence that "
             "**requires attribution**. This file is generated by `sources/fetch/photos.py credits` "
             "from the per-town `MANIFEST.jsonl`; it is the attribution of record.",
             "",
             "If you publish anything derived from these photos -- a mesh, a texture, a render, a "
             "game level -- the CC-BY-SA terms travel with it. See `images/README.md`.",
             ""]
    total = 0
    for town in sorted(mans):
        rows = mans[town]
        if not rows:
            continue
        total += len(rows)
        lines += [f"## {town} ({len(rows)} images)", ""]
        by_src = {}
        for r in rows:
            by_src.setdefault(r["source"], []).append(r)
        for src in sorted(by_src):
            rs = by_src[src]
            authors = {}
            for r in rs:
                a = (r.get("author") or "unknown").strip()
                authors.setdefault(a, []).append(r)
            lic = sorted({r.get("licence", "?") for r in rs})
            lines += [f"### {src} — {len(rs)} images — {', '.join(lic)}", ""]
            for a in sorted(authors, key=lambda x: (-len(authors[x]), x.lower())):
                n = len(authors[a])
                url = authors[a][0].get("author_url") or ""
                who = f"[{a}]({url})" if url else a
                lines.append(f"- {who} — {n} image{'s' if n != 1 else ''}")
            lines.append("")
    lines.insert(4, f"**{total} images** across {len(mans)} towns.\n")
    open(os.path.join(IMAGES, "CREDITS.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"credits: {total} images -> images/CREDITS.md")


# ---------------------------------------------------------------- clusters

TITLE_PREFIX = re.compile(r"^[A-Z]{1,2}\d{4}\s*:\s*")        # "TR3570 : " on every Geograph title
STOPWORDS = set("""the a an and or of in on at to from by for with near above over under
this that is was są se le la el il de du des les von der und od na tr thanet kent uk
england britain view looking towards along across down up out into off between old new
north south east west northern southern eastern western sea road street lane way path
footpath house building buildings church st saint bay cliff beach""".split())


def cluster_key_name(rows):
    """A human label for a cluster: the most common significant word run in its titles."""
    counts = {}
    for r in rows:
        t = TITLE_PREFIX.sub("", r.get("title") or "")
        t = re.sub(r"^File:", "", t)
        t = re.sub(r"\.(jpg|jpeg|png|tif|tiff)$", "", t, flags=re.I)
        toks = [w for w in re.findall(r"[A-Za-z][A-Za-z'&-]+", t)]
        for i in range(len(toks)):
            for span in (2, 1):
                if i + span <= len(toks):
                    ph = " ".join(toks[i:i + span])
                    if all(w.lower() in STOPWORDS for w in ph.split()):
                        continue
                    counts[ph] = counts.get(ph, 0) + (2 if span == 2 else 1)
    if not counts:
        return ""
    return max(counts, key=lambda k: (counts[k], len(k)))


def do_clusters(args):
    """Find places where enough photos look at one subject to reconstruct it.

    Panoramax and Mapillary do not need this -- their sequences already are the reconstruction
    unit, and they are reported separately below. This is for Geograph and Commons, which are
    scattered singles EXCEPT where a subject is famous enough that many people photographed it.
    Those clusters are the landmark targets.

    Connected components at a fixed radius, over a grid index. Single-link clustering will
    chain along a seafront rather than isolating one building; that is deliberate, because a
    seafront terrace IS one continuous subject, and --radius is the knob that decides how much
    chaining you want.
    """
    rows = [r for r in load_catalogues(args.source, args.town)
            if r.get("town") != "_unassigned"]
    if args.exclude_sequences:
        rows = [r for r in rows if not r.get("sequence")]
    if not rows:
        print("no catalogue -- run `photos.py catalogue` first")
        return
    R = args.radius / 1000.0                                  # km
    cell = R                                                  # one cell edge = the radius
    deg_lat = cell / 111.32
    grid = {}
    for i, r in enumerate(rows):
        deg_lon = cell / (111.32 * 0.623)
        grid.setdefault((int(r["lat"] / deg_lat), int(r["lon"] / deg_lon)), []).append(i)

    parent = list(range(len(rows)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for (gy, gx), idxs in grid.items():
        near = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                near += grid.get((gy + dy, gx + dx), [])
        for i in idxs:
            for j in near:
                if i < j and haversine_km(rows[i]["lat"], rows[i]["lon"],
                                          rows[j]["lat"], rows[j]["lon"]) <= R:
                    union(i, j)

    groups = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(rows[i])

    def span_m(ms):
        """Bounding-box diagonal. The number that separates a building from a whole town."""
        la = [m["lat"] for m in ms]
        lo = [m["lon"] for m in ms]
        return haversine_km(min(la), min(lo), max(la), max(lo)) * 1000.0

    # Single-link clustering CHAINS: in a town centre every photo is within radius of some
    # other photo, so the whole of Margate came back as one 2,110-photo component. A component
    # wider than max_span is not a subject, so it is re-clustered at a tighter radius until it
    # either fits or the radius stops helping. Reported spans are then meaningful.
    final = []
    queue = [(m, R) for m in groups.values()]
    while queue:
        members, r = queue.pop()
        if len(members) < args.min:
            continue
        if span_m(members) <= args.max_span or r < 0.004:
            final.append(members)
            continue
        r2 = r / 2
        sub = {}
        deg_lat2, deg_lon2 = r2 / 111.32, r2 / (111.32 * 0.623)
        idx = {}
        for m in members:
            idx.setdefault((int(m["lat"] / deg_lat2), int(m["lon"] / deg_lon2)), []).append(m)
        par = {id(m): id(m) for m in members}
        byid = {id(m): m for m in members}

        def f2(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x

        for (gy, gx), ms in idx.items():
            near = []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    near += idx.get((gy + dy, gx + dx), [])
            for a in ms:
                for b in near:
                    if id(a) < id(b) and haversine_km(a["lat"], a["lon"],
                                                      b["lat"], b["lon"]) <= r2:
                        ra, rb = f2(id(a)), f2(id(b))
                        if ra != rb:
                            par[rb] = ra
        for m in members:
            sub.setdefault(f2(id(m)), []).append(byid[id(m)])
        if len(sub) == 1:                      # splitting achieved nothing; keep it as is
            final.append(members)
        else:
            queue += [(v, r2) for v in sub.values()]

    out = []
    for members in final:
        if len(members) < args.min:
            continue
        srcs = {}
        for m in members:
            srcs[m["source"]] = srcs.get(m["source"], 0) + 1
        out.append({
            "name": cluster_key_name(members),
            "town": max({m["town"] for m in members},
                        key=lambda t: sum(1 for m in members if m["town"] == t)),
            "count": len(members),
            "sources": srcs,
            "span_m": round(span_m(members), 1),
            "lat": round(sum(m["lat"] for m in members) / len(members), 6),
            "lon": round(sum(m["lon"] for m in members) / len(members), 6),
            "photographers": len({(m.get("author") or "").strip() for m in members}),
            "years": sorted({(m.get("date") or "")[:4] for m in members if m.get("date")})[:1]
                     + sorted({(m.get("date") or "")[:4] for m in members if m.get("date")})[-1:],
            "ids": [m["id"] for m in members],
        })
    out.sort(key=lambda c: -c["count"])
    path = os.path.join(CATALOGUE, "clusters.json")
    json.dump({"radius_m": args.radius, "min": args.min, "count": len(out),
               "note": "Connected components of the photo positions at radius_m. Each is a "
                       "candidate reconstruction subject; `photographers` matters more than "
                       "`count` because one person's 40 frames of the same wall from one spot "
                       "will not reconstruct, and 12 people's will.",
               "clusters": out}, open(path, "w", encoding="utf-8"), indent=1)
    print(f"{len(out)} clusters of >={args.min} photos within {args.radius} m "
          f"-> {os.path.relpath(path, ROOT)}\n")
    print(f"{'n':>5} {'ppl':>4} {'span m':>7}  {'town':16s} {'sources':22s} name")
    print("-" * 92)
    for c in out[:args.show]:
        s = ", ".join(f"{k}:{v}" for k, v in sorted(c["sources"].items()))
        print(f"{c['count']:>5} {c['photographers']:>4} {c['span_m']:>7.0f}  {c['town']:16s} {s[:22]:22s} {c['name']}")

    seqs = {}
    for r in load_catalogues(args.source, args.town):
        if r.get("sequence"):
            seqs.setdefault((r["source"], str(r["sequence"]), r["town"]), 0)
            seqs[(r["source"], str(r["sequence"]), r["town"])] += 1
    big = sorted(((n, s) for s, n in seqs.items() if n >= args.min), reverse=True)
    if big:
        print(f"\nstreet-level SEQUENCES of >={args.min} frames -- these reconstruct directly, "
              f"no clustering needed:")
        print(f"{'n':>5}  {'town':16s} {'source':11s} sequence")
        print("-" * 92)
        for n, (src, seq, town) in big[:args.show]:
            print(f"{n:>5}  {town:16s} {src:11s} {seq}")


# ---------------------------------------------------------------- targets

GEO_LISTED = "geo/heritage/nhle_listed.geojson"
GRADE_RANK = {"I": 0, "II*": 1, "II": 2}


def do_targets(args):
    """Rank Historic England listed buildings by how much imagery already covers them.

    The join that makes the two halves of this warchest worth having: `geo.py` knows what is
    protected and where, `photos.py` knows what has been photographed and from how many
    distinct cameras. Together they answer the only question that matters before opening
    RealityScan -- which building can I reconstruct today, and which do I have to go and shoot.

    Ranked on PHOTOGRAPHERS, not photo count. Forty frames by one person walking one side of a
    street will not reconstruct; eight by eight people standing in different places will. The
    photo count is shown but is not the sort key.

    Positions from Commons category records are the town anchor when the file has no geotag
    (coord_exact false); those are excluded from the counts here, because a photo filed at the
    town centre says nothing about which building it shows.
    """
    path = os.path.join(ROOT, GEO_LISTED)
    if not os.path.exists(path):
        print(f"no {GEO_LISTED} -- run: python sources/fetch/geo.py fetch --layer nhle_listed")
        return
    listed = json.load(open(path, encoding="utf-8"))["features"]
    rows = [r for r in load_catalogues(None, args.town) if r.get("coord_exact", True)]
    if not rows:
        print("no catalogue -- run `photos.py catalogue` first")
        return

    R = args.radius / 1000.0
    deg_lat, deg_lon = R / 111.32, R / (111.32 * 0.623)
    grid = {}
    for r in rows:
        grid.setdefault((int(r["lat"] / deg_lat), int(r["lon"] / deg_lon)), []).append(r)

    out = []
    for f in listed:
        # NHLE serves every entry as a MultiPoint of one point, not a Point.
        g = f.get("geometry") or {}
        c = g.get("coordinates") or []
        if g.get("type") == "MultiPoint":
            c = c[0] if c else []
        elif g.get("type") != "Point":
            continue
        if len(c) < 2:
            continue
        lon, lat = c[0], c[1]
        near = []
        gy, gx = int(lat / deg_lat), int(lon / deg_lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for r in grid.get((gy + dy, gx + dx), []):
                    if haversine_km(lat, lon, r["lat"], r["lon"]) <= R:
                        near.append(r)
        p = f.get("properties") or {}
        srcs = {}
        for r in near:
            srcs[r["source"]] = srcs.get(r["source"], 0) + 1
        out.append({
            "name": p.get("Name") or p.get("ListEntry") or "?",
            "grade": p.get("Grade") or "?",
            "entry": p.get("ListEntry"),
            "lat": round(lat, 6), "lon": round(lon, 6),
            "town": near[0]["town"] if near else "",
            "photos": len(near),
            "photographers": len({(r.get("author") or "").strip() for r in near}),
            "sources": srcs,
        })

    covered = [t for t in out if t["photos"] >= args.min]
    covered.sort(key=lambda t: (-t["photographers"], GRADE_RANK.get(t["grade"], 3), -t["photos"]))
    gaps = [t for t in out if t["photos"] == 0 and GRADE_RANK.get(t["grade"], 3) <= 1]

    dest = os.path.join(CATALOGUE, "targets.json")
    json.dump({"radius_m": args.radius, "min_photos": args.min,
               "listed_total": len(out), "covered": len(covered), "grade_I_II*_gaps": len(gaps),
               "note": "Ranked by distinct photographers within radius_m, not by photo count: "
                       "parallax between cameras is what reconstructs a building. Records whose "
                       "position is a town-anchor fallback (coord_exact false) are excluded.",
               "targets": covered, "gaps": gaps},
              open(dest, "w", encoding="utf-8"), indent=1)

    print(f"{len(out)} listed buildings, {len(covered)} with >={args.min} photos within "
          f"{args.radius} m -> {os.path.relpath(dest, ROOT)}\n")
    print(f"{'ppl':>4} {'pics':>5}  {'gr':4s} {'town':16s} name")
    print("-" * 92)
    for t in covered[:args.show]:
        print(f"{t['photographers']:>4} {t['photos']:>5}  {t['grade']:4s} {t['town']:16s} "
              f"{t['name'][:52]}")
    if gaps:
        print(f"\n{len(gaps)} Grade I / II* buildings with NO catalogued photo within "
              f"{args.radius} m -- these are the ones to go and shoot:")
        for t in gaps[:args.show]:
            print(f"     {t['grade']:4s} {t['name'][:60]}")


def do_status(args=None):
    mans = read_manifests()
    print(f"{'town':18s}{'files':>8s}{'GB':>8s}   sources")
    print("-" * 60)
    tn = tb = 0
    for town in sorted(mans):
        rows = mans[town]
        b = sum(r.get("bytes", 0) for r in rows)
        srcs = sorted({r["source"] for r in rows})
        tn, tb = tn + len(rows), tb + b
        print(f"{town:18s}{len(rows):>8d}{b/1e9:>8.2f}   {', '.join(srcs)}")
    print("-" * 60)
    print(f"{'TOTAL':18s}{tn:>8d}{tb/1e9:>8.2f}")
    summarise()


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalogue", help="ask every source what it holds (no image bytes)")
    c.add_argument("--source", choices=SOURCES)
    c.add_argument("--town")
    c.set_defaults(fn=do_catalogue)

    d = sub.add_parser("download", help="fetch image files listed in the catalogue")
    d.add_argument("--source", choices=SOURCES)
    d.add_argument("--town")
    d.add_argument("--limit", type=int, help="max images per town per source")
    d.add_argument("--size", choices=["hd", "sd"], default="hd",
                   help="hd = original upload (default); sd = ~2048px, ~6x smaller")
    d.add_argument("--jobs", type=int, default=12,
                   help="worker threads. This does NOT set the request rate -- RATE does, per "
                        "host -- it only decides whether there are enough threads to reach it. "
                        "Geograph serves ~100 KB/s per connection, so 6 threads left the four "
                        "s0-s3 hosts running at ~1/s against a 4/s budget (default 12)")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--include-unassigned", action="store_true")
    d.set_defaults(fn=do_download)

    k = sub.add_parser("clusters", help="find groups of photos dense enough to reconstruct")
    k.add_argument("--radius", type=float, default=40.0, help="metres (default 40)")
    k.add_argument("--min", type=int, default=6, help="min photos in a cluster (default 6)")
    k.add_argument("--max-span", type=float, default=250.0,
                   help="metres; a component wider than this is re-clustered at half the "
                        "radius until it fits. Single-link clustering otherwise chains a whole "
                        "town centre into one component (default 250)")
    k.add_argument("--show", type=int, default=40)
    k.add_argument("--source", choices=SOURCES)
    k.add_argument("--town")
    k.add_argument("--exclude-sequences", action="store_true",
                   help="drop street-level sequence frames, leaving only the scattered sources")
    k.set_defaults(fn=do_clusters)

    g = sub.add_parser("targets", help="rank listed buildings by how well imagery covers them")
    g.add_argument("--radius", type=float, default=60.0, help="metres (default 60)")
    g.add_argument("--min", type=int, default=4, help="min photos to count as covered")
    g.add_argument("--show", type=int, default=30)
    g.add_argument("--town")
    g.set_defaults(fn=do_targets)

    a = sub.add_parser("assign", help="re-file the catalogue after editing thanet_towns.json")
    a.set_defaults(fn=do_assign)
    r = sub.add_parser("credits", help="regenerate images/CREDITS.md")
    r.set_defaults(fn=do_credits)
    s = sub.add_parser("status", help="what is on disk")
    s.set_defaults(fn=do_status)

    args = ap.parse_args()
    os.makedirs(IMAGES, exist_ok=True)
    args.fn(args)


if __name__ == "__main__":
    main()
