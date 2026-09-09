#!/usr/bin/env python3
"""Fetch open geospatial data for Thanet into geo/.

    geo.py fetch [--layer L ...]    fetch every layer, or just the named ones
    geo.py list                     what layers exist and what is on disk

Companion to photos.py. Where that collects pictures to reconstruct FROM, this collects the
frames to hang them on: what the buildings are, which ones are protected, where the aerial
surveys flew, and which national datasets cover the isle.

Everything here is Open Government Licence v3 or ODbL, and everything is re-fetchable -- geo/
is disposable, like data/. Nothing in it feeds the terrain pipeline; sources/run.sh remains
the only thing that writes data/<site>/.

LAYERS

  osm_places      OSM place nodes (town/suburb/village/hamlet) over the district. The source
                  the anchors in sources/config/thanet_towns.json were read from -- re-fetch
                  to check they have not moved or been renamed.
  osm_buildings   Building footprints with name, height and levels tags, as GeoJSON. The
                  pipeline already derives massing from its own extract; this is the
                  human-readable version for deciding what is worth photographing.
  osm_admin       Administrative and civil-parish boundaries over the district.
  osm_heritage    OSM's own heritage tagging (historic=*, heritage=*, tourism=attraction).
  nhle_listed     Historic England's National Heritage List: every listed building, with its
                  grade and list entry number. Grade I and II* are the buildings worth the
                  most photogrammetry effort, and Thanet has a lot of them.
  nhle_areas      Conservation areas as named points (HE's polygon layer is redacted).
  he_harbours     HE harbour heritage assets -- piers, quays, lighthouses, with descriptions.
  ea_oblique      Environment Agency OBLIQUE aerial photography index. Each record is one
                  low-angle air photo with the camera's easting, northing, heading and view
                  angle. Obliques see building FACADES and roofs together, which vertical
                  imagery cannot, so this is the highest-value aerial index here.
  ea_vertical     EA vertical (ortho) aerial photography index, 10-25 cm.
  ea_lidar_pc     EA LIDAR point cloud (LAZ) index -- classified returns, median 0.85 m spacing.
  ea_lidar_nlp    National LIDAR Programme index.
  os_products     Ordnance Survey OpenData product catalogue with live download URLs.

The three ea_* photo/lidar layers are INDEXES, not the imagery. They tell you exactly which
files exist over Thanet and where they were flown; the files themselves come from the Defra
portal at https://environment.data.gov.uk/DefraDataDownload/?Mode=survey, which is an
interactive map with no documented headless API. geo/ea/README.md is written with the shortlist.
"""
import argparse, json, os, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOWNS_CFG = os.path.join(ROOT, "sources", "config", "thanet_towns.json")
GEO = os.path.join(ROOT, "geo")
UA = "3duk-thanet-warchest/1.0 (open geodata for a 3D map of Thanet)"

OVERPASS = ["https://overpass.kumi.systems/api/interpreter",
            "https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]

HE = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services"
EA_WFS = "https://environment.data.gov.uk/spatialdata/survey-index-files/wfs"
EA_NS = "dataset-9f0fa3fc-a860-4729-adc9-47fe53f658d0"


def get(url, data=None, timeout=180, retries=3):
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code in (400, 401, 403, 404):
                raise RuntimeError(f"{last}: {e.read(300)!r}")
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 ** a)
    raise RuntimeError(f"GET {url[:110]} failed after {retries}: {last}")


def write(rel, obj, note=None):
    path = os.path.join(GEO, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if note and isinstance(obj, dict):
        obj = dict(obj)
        obj["_provenance"] = note
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    n = len(obj.get("features", [])) if isinstance(obj, dict) else len(obj)
    print(f"  -> geo/{rel}  ({n} features, {os.path.getsize(path)/1e6:.1f} MB)")
    return path


def bbox():
    cfg = json.load(open(TOWNS_CFG, encoding="utf-8"))
    return cfg["bbox_wgs84"], cfg


# ---------------------------------------------------------------- overpass

def overpass(query, timeout=180):
    """One request per mirror, no per-mirror retry.

    Retrying a slow Overpass query against the same mirror just queues behind the query that
    was already slow: the first version here used 3 retries x 3 mirrors x a 300 s timeout and
    sat on one heritage query for 25 minutes without ever reporting why. Failing over quickly
    to the next mirror is both faster and politer.
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for host in OVERPASS:
        try:
            return json.loads(get(host, data=body, timeout=timeout, retries=1))
        except Exception as e:
            last = e
            print(f"    {host.split('/')[2]}: {str(e)[:120]}")
    raise RuntimeError(f"every Overpass mirror failed: {last}")


def osm_to_geojson(d, kinds=("node", "way", "relation")):
    """Overpass 'out center' -> GeoJSON points. Ways and relations become their centroid.

    Centres, not footprints, on purpose: these layers are for deciding WHERE to point a
    camera and for cross-referencing against the photo manifests. The pipeline's own extract
    (data/thanet/raw/thanet.osm) is the one that carries real geometry, and osm_buildings
    below keeps full polygons because footprints are what you match a facade to.
    """
    feats = []
    for e in d.get("elements", []):
        if e["type"] not in kinds:
            continue
        if e["type"] == "node":
            lat, lon = e.get("lat"), e.get("lon")
        else:
            c = e.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None:
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": dict(e.get("tags", {}),
                                         **{"@id": f"{e['type']}/{e['id']}"})})
    return {"type": "FeatureCollection", "features": feats}


def layer_osm_places(bb, cfg):
    s, w, n, e = bb
    d = overpass(f"""[out:json][timeout:180];
      node["place"~"^(city|town|suburb|village|hamlet|neighbourhood|locality)$"]({s},{w},{n},{e});
      out body;""")
    return write("osm/places.geojson", osm_to_geojson(d),
                 {"source": "OpenStreetMap via Overpass", "licence": "ODbL 1.0",
                  "attribution": "(c) OpenStreetMap contributors",
                  "note": "The anchors in sources/config/thanet_towns.json were read from this "
                          "layer. If a name or position here disagrees with that config, the "
                          "config is stale -- re-run `photos.py assign` after fixing it."})


def layer_osm_buildings(bb, cfg):
    s, w, n, e = bb
    d = overpass(f"""[out:json][timeout:600];
      (way["building"]["name"]({s},{w},{n},{e});
       relation["building"]["name"]({s},{w},{n},{e});
       way["building"]["height"]({s},{w},{n},{e});
       way["building"]["building:levels"]({s},{w},{n},{e}););
      out center tags;""")
    return write("osm/buildings_named.geojson", osm_to_geojson(d),
                 {"source": "OpenStreetMap via Overpass", "licence": "ODbL 1.0",
                  "attribution": "(c) OpenStreetMap contributors",
                  "note": "Named buildings, plus any building carrying height or "
                          "building:levels. Not every building -- that is what the pipeline's "
                          "own extract is for. These are the ones with enough identity to be "
                          "worth a reconstruction target."})


def layer_osm_admin(bb, cfg):
    s, w, n, e = bb
    d = overpass(f"""[out:json][timeout:300];
      relation["boundary"="administrative"]["admin_level"~"^(6|8|10)$"]({s},{w},{n},{e});
      out center tags;""")
    return write("osm/admin.geojson", osm_to_geojson(d),
                 {"source": "OpenStreetMap via Overpass", "licence": "ODbL 1.0",
                  "attribution": "(c) OpenStreetMap contributors",
                  "note": "admin_level 6 = county, 8 = district (Thanet), 10 = civil parish. "
                          "Centroids only."})


def layer_osm_heritage(bb, cfg):
    """One small query per tag rather than one five-clause union.

    The union form is what a single Overpass request is *for*, but it is all-or-nothing: when
    it is slow you get nothing and learn nothing about which clause was expensive. Five cheap
    queries merged here cost a few more round trips and degrade one tag at a time.
    """
    s, w, n, e = bb
    selectors = ['nwr["historic"]', 'nwr["heritage"]', 'nwr["tourism"="attraction"]',
                 'nwr["man_made"="lighthouse"]', 'nwr["amenity"="place_of_worship"]']
    merged, failed = {}, []
    for sel in selectors:
        try:
            d = overpass(f'[out:json][timeout:120];{sel}({s},{w},{n},{e});out center tags;')
        except Exception as ex:
            failed.append(f"{sel}: {str(ex)[:100]}")
            print(f"    SKIPPED {sel}")
            continue
        for f in osm_to_geojson(d)["features"]:
            merged[f["properties"]["@id"]] = f
        print(f"    {sel:36s} {len(d.get('elements', []))} elements "
              f"(merged total {len(merged)})")
    fc = {"type": "FeatureCollection", "features": list(merged.values())}
    note = {"source": "OpenStreetMap via Overpass", "licence": "ODbL 1.0",
            "attribution": "(c) OpenStreetMap contributors",
            "selectors": selectors}
    if failed:
        note["INCOMPLETE"] = failed
    return write("osm/heritage.geojson", fc, note)


# ---------------------------------------------------------------- arcgis (historic england)

ARCGIS_PAGE = 1000


def arcgis(service, bb, where="1=1", layer=0):
    """Paged ArcGIS FeatureServer query.

    Pages until a short page arrives. The obvious `exceededTransferLimit` flag is NOT usable
    here: with f=geojson the server omits it, so trusting it stops after one page and returns
    exactly ARCGIS_PAGE features looking like a complete answer -- which is what the first
    version of this did to the listed-buildings layer (1000 of 1268).
    """
    s, w, n, e = bb
    out, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": where, "outFields": "*", "f": "geojson",
            "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
            "resultOffset": offset, "resultRecordCount": ARCGIS_PAGE, "returnGeometry": "true"})
        d = json.loads(get(f"{HE}/{service}/FeatureServer/{layer}/query?{q}", timeout=180))
        if "error" in d:
            raise RuntimeError(f"{service}: {d['error']}")
        fs = d.get("features", [])
        out += fs
        if len(fs) < ARCGIS_PAGE:
            break
        offset += len(fs)
    return {"type": "FeatureCollection", "features": out}


def layer_nhle_listed(bb, cfg):
    fc = arcgis("National_Heritage_List_for_England_NHLE_v02_VIEW", bb)
    grades = {}
    for f in fc["features"]:
        g = (f.get("properties") or {}).get("Grade") or "?"
        grades[g] = grades.get(g, 0) + 1
    print(f"     grades: {grades}")
    return write("heritage/nhle_listed.geojson", fc,
                 {"source": "Historic England, National Heritage List for England",
                  "licence": "Open Government Licence v3.0",
                  "attribution": "Contains Historic England data (c) Historic England",
                  "grades": grades,
                  "note": "Grade I and II* are the buildings worth the most photogrammetry "
                          "effort. Join to the photo manifests on position to find which "
                          "listed buildings already have imagery."})


def layer_nhle_areas(bb, cfg):
    """Conservation areas, as named POINTS.

    Historic England's `Conservation_Areas` polygon service is redacted: over Thanet it
    answers two features, each an LPA-sized blob (112 and 321 sq km) whose every attribute
    reads "No data available for publication by HE". It is not a boundary dataset and using
    it would be worse than having nothing. `ConservationAreaLocators` is the usable layer --
    one named point per conservation area, sourced by HE from the local authority. For real
    boundaries, Thanet District Council is the publisher of record.
    """
    fc = arcgis("ConservationAreaLocators", bb)
    names = sorted({(f.get("properties") or {}).get("NAME_CONCA", "") for f in fc["features"]})
    print(f"     areas: {', '.join(n for n in names if n)}")
    return write("heritage/conservation_areas.geojson", fc,
                 {"source": "Historic England, ConservationAreaLocators",
                  "licence": "Open Government Licence v3.0",
                  "attribution": "Contains Historic England data (c) Historic England",
                  "geometry": "points, not boundaries",
                  "names": [n for n in names if n],
                  "note": "One named point per conservation area. HE's Conservation_Areas "
                          "POLYGON service is redacted over Thanet -- two LPA-sized blobs with "
                          "every attribute set to 'No data available for publication by HE' -- "
                          "so it is deliberately not used. Thanet District Council publishes "
                          "the real boundaries."})


def layer_he_harbours(bb, cfg):
    """Historic England's harbour heritage-asset inventory.

    Richer than the NHLE entry for the same structures: it carries a monument type and a prose
    summary per asset, which is what tells you whether a quay wall is worth reconstructing.
    Ramsgate Royal Harbour is the dense part over Thanet.
    """
    fc = arcgis("Heritage_Assets_Inventory1", bb)
    return write("heritage/harbour_assets.geojson", fc,
                 {"source": "Historic England, Heritage Assets Inventory",
                  "licence": "Open Government Licence v3.0",
                  "attribution": "Contains Historic England data (c) Historic England",
                  "note": "Harbour structures -- piers, quays, slips, lighthouses, dry docks -- "
                          "with monument type and summary. Ramsgate's Royal Harbour is the only "
                          "Royal Harbour in the UK and is the bulk of these records."})


# ---------------------------------------------------------------- environment agency

def ea_index(layer, bb):
    s, w, n, e = bb
    q = urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": f"{EA_NS}:{layer}", "outputFormat": "application/json",
        "srsName": "EPSG:4326", "count": 10000,
        "bbox": f"{s},{w},{n},{e},urn:ogc:def:crs:EPSG::4326"})
    return json.loads(get(f"{EA_WFS}?{q}", timeout=240))


EA_LICENCE = {"source": "Environment Agency survey index, via environment.data.gov.uk WFS",
              "licence": "Open Government Licence v3.0",
              "attribution": "(c) Environment Agency copyright and/or database right 2026. "
                             "All rights reserved.",
              "portal": "https://environment.data.gov.uk/DefraDataDownload/?Mode=survey"}


def layer_ea_oblique(bb, cfg):
    fc = ea_index("Oblique_photography_index_catalogue", bb)
    by = {}
    for f in fc["features"]:
        by[f["properties"].get("sortie")] = by.get(f["properties"].get("sortie"), 0) + 1
    print(f"     sorties: {by}")
    return write("ea/oblique_photography_index.geojson", fc,
                 dict(EA_LICENCE, sorties=by,
                      note="One record per oblique air photo, with the camera's easting, "
                           "northing, heading (deg) and iva (image view angle). This is pose "
                           "metadata: an oblique run along a seafront is effectively an "
                           "aerial photogrammetry strip. The JPEGs themselves are not served "
                           "over HTTP -- filepath is a path inside the Defra archive, and the "
                           "portal above is the only documented way to order them."))


def layer_ea_vertical(bb, cfg):
    fc = ea_index("Vertical_photography_index_catalogue", bb)
    return write("ea/vertical_photography_index.geojson", fc,
                 dict(EA_LICENCE,
                      note="Orthorectified vertical imagery, 10-25 cm. Good for ground and "
                           "roof texture and as a basemap; it cannot see facades."))


def layer_ea_lidar_pc(bb, cfg):
    fc = ea_index("LIDAR_Point_Cloud_Index_Catalogue", bb)
    return write("ea/lidar_pointcloud_index.geojson", fc,
                 dict(EA_LICENCE,
                      note="Classified LAZ point cloud. Spacing is median 0.85 m over Thanet, "
                           "NOT the ~0.2 m an earlier version of this note claimed: only the "
                           "2006 (0.21 m) and 2017 (0.35 m) surveys beat the 1 m composite the "
                           "pipeline already uses. The advantage is that these are raw "
                           "classified returns, not a resampled surface -- and that RealityScan "
                           "can import a point cloud as control, which is the cheapest way to "
                           "get a photogrammetric mesh into real OSGB36/ODN coordinates."))


def layer_ea_lidar_nlp(bb, cfg):
    fc = ea_index("National_LIDAR_Programme_Index_Catalogue", bb)
    return write("ea/lidar_nlp_index.geojson", fc, dict(EA_LICENCE))


# ---------------------------------------------------------------- ordnance survey

def layer_os_products(bb, cfg):
    """OS OpenData catalogue with live per-format download URLs.

    Keyless: api.os.uk/downloads/v1 serves the OpenData tier without an API key. The products
    are national, so nothing here is Thanet-shaped -- the useful ones are listed in the note
    and the download URLs are resolved so a fetch is one curl away.
    """
    prods = json.loads(get("https://api.os.uk/downloads/v1/products", timeout=120))
    want = {"OpenMapLocal", "OpenNames", "OpenRoads", "OpenUPRN", "OpenUSRN",
            "Terrain50", "OpenZoomstack", "BoundaryLine", "BuiltUpAreas", "VectorMapDistrict"}
    out = []
    for p in prods:
        if p["id"] not in want:
            continue
        entry = {k: p.get(k) for k in ("id", "name", "version", "url", "documentationUrl")}
        try:
            entry["downloads"] = [
                {k: d.get(k) for k in ("format", "subformat", "area", "fileName", "size", "url")}
                for d in json.loads(get(f"https://api.os.uk/downloads/v1/products/"
                                        f"{p['id']}/downloads", timeout=120))]
        except Exception as ex:
            entry["downloads_error"] = str(ex)[:200]
        out.append(entry)
        print(f"     {p['id']}: {len(entry.get('downloads', []))} downloads")
    return write("os/opendata_products.json",
                 {"products": out,
                  "_provenance": {
                      "source": "Ordnance Survey OS OpenData, api.os.uk/downloads/v1 (no key)",
                      "licence": "Open Government Licence v3.0",
                      "attribution": "Contains OS data (c) Crown copyright and database right 2026",
                      "note": "National products, not clipped to Thanet. The ones that matter "
                              "here: BuiltUpAreas (settlement polygons -- a better town "
                              "boundary than the anchor discs in thanet_towns.json), OpenNames "
                              "(gazetteer, for naming what a photo shows), OpenRoads, "
                              "OpenUPRN (a point per addressable property), Terrain50 "
                              "(50 m DTM, coarse next to the 1 m LIDAR but national), and "
                              "OpenZoomstack (a whole-GB vector basemap in one GeoPackage)."}})


LAYERS = {
    "osm_places": layer_osm_places, "osm_buildings": layer_osm_buildings,
    "osm_admin": layer_osm_admin, "osm_heritage": layer_osm_heritage,
    "nhle_listed": layer_nhle_listed, "nhle_areas": layer_nhle_areas,
    "he_harbours": layer_he_harbours,
    "ea_oblique": layer_ea_oblique, "ea_vertical": layer_ea_vertical,
    "ea_lidar_pc": layer_ea_lidar_pc, "ea_lidar_nlp": layer_ea_lidar_nlp,
    "os_products": layer_os_products,
}


def write_ea_readme():
    """Turn the three EA indexes into an ordering guide.

    The indexes say what exists; this says how to get it, and which of it is worth getting.
    Regenerated from whatever indexes are on disk, so the counts are never stale relative to
    the GeoJSON beside it.
    """
    import collections
    d = os.path.join(GEO, "ea")
    if not os.path.isdir(d):
        return

    def load(name):
        p = os.path.join(d, name)
        return json.load(open(p, encoding="utf-8"))["features"] if os.path.exists(p) else []

    obl = load("oblique_photography_index.geojson")
    ver = load("vertical_photography_index.geojson")
    laz = load("lidar_pointcloud_index.geojson")

    L = ["# Environment Agency survey data over Thanet",
         "",
         "Generated by `sources/fetch/geo.py` from the GeoJSON indexes in this directory.",
         "",
         "All of it is **Open Government Licence v3.0**: © Environment Agency copyright and/or",
         "database right 2026. All rights reserved.",
         "",
         "## How to actually get the files",
         "",
         "These GeoJSONs are **indexes, not imagery**. Each record's `filepath` is a path inside",
         "the Defra archive (`.\\Oblique_Photography_Archive\\...`), not a URL — the files are not",
         "served over plain HTTP and there is no documented headless API. Order them from:",
         "",
         "    https://environment.data.gov.uk/DefraDataDownload/?Mode=survey",
         "",
         "Draw your area of interest on the map, pick the product and year, and it builds a zip.",
         "Use the tables below to know what to ask for before you go there.",
         ""]

    if obl:
        by = collections.Counter((f["properties"].get("sortie"), f["properties"].get("year"))
                                 for f in obl)
        L += ["## Oblique aerial photography — the high-value set", "",
              f"{len(obl)} frames over the Thanet bbox. Obliques are shot at a low angle, so a",
              "single frame sees **roofs and facades together** — the one thing neither",
              "street-level photography nor vertical orthophotos can give you. Each record",
              "carries the camera's `easting`, `northing`, `heading` (degrees) and `iva` (image",
              "view angle), which is pose metadata: a sortie flown along a seafront is",
              "effectively a ready-made aerial photogrammetry strip.", "",
              "| Sortie | Year | Frames |", "|---|---|---|"]
        for (sortie, year), n in sorted(by.items(), key=lambda kv: (-kv[1], kv[0][0] or "")):
            L.append(f"| `{sortie}` | {year} | {n} |")
        L += ["",
              "Ask for these by sortie. The 2017 sorties are the most recent and the largest.",
              ""]

    if ver:
        by = collections.Counter((f["properties"].get("year"), f["properties"].get("resolution"),
                                  f["properties"].get("type")) for f in ver)
        L += ["## Vertical (ortho) aerial photography", "",
              f"{len(ver)} tiles. Orthorectified and looking straight down: good for ground and",
              "roof texture and as a basemap, useless for facades.", "",
              "| Year | Resolution | Bands | Tiles |", "|---|---|---|---|"]
        for (year, res, typ), n in sorted(by.items()):
            L.append(f"| {year} | {res if res is not None else '?'} m | {typ or '?'} | {n} |")
        L += ["",
              "The 2006 pass is 10 cm — the sharpest here, though nearly twenty years old and",
              "flown before much of the recent seafront work.", ""]

    if laz:
        import statistics
        pts = sum(f["properties"].get("pt_count") or 0 for f in laz)
        per_year = collections.defaultdict(list)
        tiles = collections.Counter()
        for f in laz:
            p = f["properties"]
            tiles[p.get("year")] += 1
            if p.get("pt_spacing"):
                per_year[p.get("year")].append(p["pt_spacing"])
        allsp = sorted(s for v in per_year.values() for s in v)
        L += ["## LIDAR point cloud (LAZ)", "",
              f"{len(laz)} tiles across {len(tiles)} survey years, {pts/1e6:.0f} million points."]
        if allsp:
            L += ["",
                  f"Point spacing is **median {statistics.median(allsp):.2f} m** "
                  f"(p10 {allsp[len(allsp)//10]:.2f}, p90 {allsp[9*len(allsp)//10]:.2f}). Do not",
                  "quote the mean: one tile reports 253 m and drags it to 2.25 m.",
                  "",
                  "Only two surveys here are substantially denser than the 1 m composite the",
                  "terrain pipeline already uses — **2006 at 0.21 m** and **2017 at 0.35 m**. The",
                  "rest sit near 0.85 m, which is comparable. Pick by year, not by assuming the",
                  "point cloud is finer.", ""]
        L += ["The real advantage over the composite is not always density: this is the raw",
              "**classified** return (every tile here is classified), so you get ground / building",
              "/ vegetation classes and multiple returns rather than one resampled surface.", "",
              "It is also the **georeferencing shortcut**. RealityScan accepts a point cloud as",
              "control, and importing this is the cheapest way to land a photogrammetric mesh in",
              "real OSGB36 / ODN coordinates — the frame everything else in this repo uses",
              "(`EPSG:27700`, elevations in metres above Ordnance Datum Newlyn). A mesh built",
              "from photographs alone is in an arbitrary frame and will not sit on the terrain",
              "the pipeline builds.", "",
              "| Year | Tiles | Median spacing |", "|---|---|---|"]
        for y in sorted(tiles):
            m = (f"{statistics.median(per_year[y]):.2f} m" if per_year.get(y) else "—")
            L.append(f"| {y} | {tiles[y]} | {m} |")
        L.append("")

    path = os.path.join(d, "README.md")
    open(path, "w", encoding="utf-8").write("\n".join(L))
    print(f"  -> geo/ea/README.md")


def do_fetch(args):
    bb, cfg = bbox()
    todo = args.layer or list(LAYERS)
    ok, bad = [], []
    for name in todo:
        print(f"[{name}]")
        t0 = time.time()
        try:
            LAYERS[name](bb, cfg)
            ok.append(name)
            print(f"     {time.time()-t0:.0f}s")
        except Exception as e:
            bad.append((name, str(e)[:300]))
            print(f"     FAILED: {str(e)[:300]}")
    write_ea_readme()
    print(f"\n{len(ok)} layers written, {len(bad)} failed")
    for n, e in bad:
        print(f"  {n}: {e}")


def do_list(args):
    print(f"{'layer':16s}{'on disk':>12s}   description")
    print("-" * 78)
    for name in LAYERS:
        hits = []
        for root, _, files in os.walk(GEO):
            for f in files:
                p = os.path.join(root, f)
                if name.split("_", 1)[-1] in f or name in f:
                    hits.append(p)
        sz = sum(os.path.getsize(p) for p in hits)
        doc = (LAYERS[name].__doc__ or "").strip().split("\n")[0]
        print(f"{name:16s}{(f'{sz/1e6:.1f} MB' if hits else '-'):>12s}   {doc[:44]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--layer", action="append", choices=list(LAYERS))
    f.set_defaults(fn=do_fetch)
    l = sub.add_parser("list")
    l.set_defaults(fn=do_list)
    args = ap.parse_args()
    os.makedirs(GEO, exist_ok=True)
    args.fn(args)


if __name__ == "__main__":
    main()
