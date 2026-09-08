#!/usr/bin/env python3.14
"""OSM amenity nodes -> per-tile street-furniture placements (JSONL).

Semantic, not geometric: one record per node saying which prop, where, which way it
faces and how high. Elevation comes from the nearest draped road centreline plus the
kerb when the node sits on a pavement -- which is where mappers put bins -- otherwise
it is left null and the consumer drops the prop onto the terrain. No DTM is read here,
so this step needs only the GeoPackage and step 06's output, and runs in seconds.

Coordinates are CRS eastings/northings in metres. Orientation is `bearing`: degrees
clockwise from grid north, the compass convention -- not any engine's rotation axis.

Two things that matter for how it reads:
  * Props are squared to the nearest road, not left at an arbitrary rotation. A bin at
    a random angle beside a straight kerb reads as wrong from twenty metres away.
  * Nodes mapped inside the carriageway are pushed onto the pavement. Mappers place a
    bin from an aerial photo to within a couple of metres; that is enough to put it in
    the road, and a bin in the road is the first thing a walker notices. Every nudged
    record says so, so the guess is auditable rather than invisible.
"""
import glob, hashlib, json, math, os, sys
from collections import Counter, defaultdict
from osgeo import ogr
ogr.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
TUN = CFG["tuning"]["furniture"]
P   = lib.paths(CFG)
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
NX, NY = CFG["nx"], CFG["ny"]
NET = os.path.join(P["out"], "networks")
OUT = os.path.join(P["out"], "furniture")
CLIP = lib.parse_clip(CFG)

PROPS = {k: v for k, v in TUN["props"].items() if not k.startswith("_")}
KERB  = TUN["kerb_m"]
SNAP  = TUN["snap_m"]


def tagval(ot, key):
    if not ot: return None
    tok = '"' + key + '"=>"'
    i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i + len(tok))
    return ot[i + len(tok):j]


def load_roads():
    """Every draped centreline segment, bucketed by tile so a lookup touches 3x3 tiles.

    Step 06 emits [easting, northing, elevation]; index 2 is the elevation.
    """
    segs = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(NET, "roads_*.jsonl"))):
        for line in open(path):
            r = json.loads(line)
            if r.get("cls") == "_junction": continue
            p = r["pts"]
            for a, b in zip(p, p[1:]):
                if a[0] == b[0] and a[1] == b[1]: continue      # 06 repeats the seam vertex
                ce, cn = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                segs[(int((ce - E0) // T), int((cn - N0) // T))].append(
                    (a[0], a[1], a[2], b[0], b[1], b[2], r["w"], r["pav"], r["cls"]))
    return segs


def nearest_road(e, n, segs):
    """Closest segment in the 3x3 tile neighbourhood.
    -> (dist, elevation on the line, (de,dn), w, pav, cls, side, foot)"""
    i, j = int((e - E0) // T), int((n - N0) // T)
    best = None
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for (ae, an, az, be, bn, bz, w, pav, cls) in segs.get((i + di, j + dj), ()):
                de, dn = be - ae, bn - an
                L2 = de * de + dn * dn
                t = max(0.0, min(1.0, ((e - ae) * de + (n - an) * dn) / L2)) if L2 > 0 else 0.0
                pe, pn = ae + de * t, an + dn * t
                d = math.hypot(e - pe, n - pn)
                if best is None or d < best[0]:
                    side = 1.0 if ((e - pe) * -dn + (n - pn) * de) > 0 else -1.0
                    best = (d, az + (bz - az) * t, (de, dn), w, pav, cls, side, (pe, pn))
    return best


def place(osm_id, e, n, segs):
    """One placement record. bearing is degrees clockwise from grid north."""
    nr = nearest_road(e, n, segs)
    if nr is None or nr[0] > SNAP:
        seed = int(hashlib.md5(str(osm_id).encode()).hexdigest()[:8], 16)
        return {"e": round(e, 2), "n": round(n, 2), "z": None,
                "bearing": float(seed % 360), "src": "terrain",
                "d": None, "cls": None, "nudged": False}
    d, z_line, (de, dn), w, pav, cls, side, (pe, pn) = nr
    bearing = round(math.degrees(math.atan2(de, dn)) % 360.0, 1)
    half = w / 2.0
    nudged = False
    if d < half:                                                    # mapped in the carriageway
        target = half + (pav / 2.0 if pav > 0 else TUN["carriageway_nudge_m"])
        L = math.hypot(de, dn)
        ne, nn = -dn / L * side, de / L * side
        e, n = pe + ne * target, pn + nn * target
        d = target
        nudged = True
    if d <= half + pav + TUN["verge_margin_m"]:
        z, srcname = z_line + (KERB if pav > 0 else 0.0), ("kerb" if pav > 0 else "road")
    else:
        z, srcname = None, "terrain"          # verge, forecourt, park edge: let the terrain say
    return {"e": round(e, 2), "n": round(n, 2), "z": None if z is None else round(z, 2),
            "bearing": bearing, "src": srcname, "d": round(d, 1), "cls": cls, "nudged": nudged}


def main():
    segs = load_roads()
    nseg = sum(len(v) for v in segs.values())
    if nseg == 0:
        sys.exit(f"10: FATAL -- no road segments in {NET}; run step 06 first")
    lib.mkdirs(OUT)
    for old in glob.glob(os.path.join(OUT, "furniture_*.jsonl")):
        os.remove(old)

    src = ogr.Open(P["gpkg"])
    lyr = src.GetLayer("points")
    has_field = lyr.GetLayerDefn().GetFieldIndex("amenity") >= 0   # default osmconf hides it in other_tags
    buckets, n_amenity, outside, kinds = defaultdict(list), 0, 0, Counter()
    outside_clip = 0
    for f in lyr:
        ot = f.GetField("other_tags")
        am = f.GetField("amenity") if has_field else tagval(ot, "amenity")
        if not am: continue
        n_amenity += 1
        kinds[am] += 1
        if am not in PROPS: continue
        g = f.GetGeometryRef()
        if g is None: continue
        e, n = g.GetX(), g.GetY()
        if not (E0 <= e < E0 + NX * T and N0 <= n < N0 + NY * T):
            outside += 1
            continue
        if CLIP is not None and not lib.keep_points(CLIP, e, n):
            outside_clip += 1             # judged at the OSM position, before any nudge
            continue
        rec = {"id": f.GetField("osm_id"), "prop": PROPS[am], "name": f.GetField("name") or None}
        rec.update(place(rec["id"], e, n, segs))
        buckets[(int((rec["e"] - E0) // T), int((rec["n"] - N0) // T))].append(rec)

    # Distrust quiet success: an empty points layer means step 01 did not convert it,
    # not that the site has no bins.
    if n_amenity == 0:
        sys.exit("10: FATAL -- no amenity nodes in the points layer; check step 01 converted 'points'")

    n = 0
    for (i, j), items in sorted(buckets.items()):
        with open(os.path.join(OUT, f"furniture_x{i}_y{j}.jsonl"), "w") as fh:
            for r in items:
                fh.write(json.dumps(r, separators=(",", ":")) + "\n"); n += 1

    srcs = Counter(r["src"] for v in buckets.values() for r in v)
    json.dump({"site": CFG["site"], "crs": CFG["crs"],
               "coordinates": "CRS eastings/northings, metres; bearing is degrees clockwise from grid north",
               "origin": CFG["origin"], "tile_m": CFG["tile_m"],
               "placed": n, "tiles": len(buckets), "outside_grid": outside,
               "by_height_source": dict(srcs),
               "nudged_out_of_carriageway": sum(r["nudged"] for v in buckets.values() for r in v),
               "amenity_kinds_seen": dict(kinds.most_common(12)), "props": PROPS,
               "kerb_m": KERB, "snap_m": SNAP,
               **({} if CLIP is None else {"clip": lib.clip_manifest(CLIP), "outside_clip": outside_clip})},
              open(os.path.join(P["out"], "qa_furniture.json"), "w"), indent=1)
    print(f"wrote {n} placements across {len(buckets)} tiles -> {OUT}   ({nseg} segments consulted)")
    print(f"elevation from: {dict(srcs)}   outside grid: {outside}   amenity nodes total: {n_amenity}"
          + (f"   outside clip: {outside_clip}" if CLIP is not None else ""))
    if n == 0:
        print(f"10: WARNING -- amenity nodes exist but none matched {sorted(PROPS)}; nothing to place")


if __name__ == "__main__":
    main()
