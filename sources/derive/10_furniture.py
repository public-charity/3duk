#!/usr/bin/env python3.14
"""OSM amenity nodes -> per-tile street-furniture placements (JSONL) for the Unity generator.

Semantic, not geometric: one record per node saying which prop, where (local metres),
which way to face and how high. Height comes from the nearest draped road centreline plus
the kerb when the node sits on a pavement -- which is where mappers put bins -- otherwise
it is left null and Unity drops the prop onto the terrain. No DTM is read here, so this
step needs only the GeoPackage and data/out/networks, and runs in seconds.

Two things that matter for how it looks:
  * Props are squared to the nearest road, not left at OSM's default rotation. A bin at
    a random yaw beside a straight kerb reads as wrong from twenty metres away.
  * Nodes mapped inside the carriageway are pushed onto the pavement. Mappers place a
    bin from an aerial photo to within a couple of metres; that is enough to put it in
    the road, and a bin in the road is the first thing a walker notices.
"""
import glob, hashlib, json, math, os, sys
from collections import Counter, defaultdict
from osgeo import ogr
ogr.UseExceptions()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG  = json.load(open(f"{ROOT}/sources/config/margate.json"))
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
NX, NY = CFG["nx"], CFG["ny"]
NET = f"{ROOT}/data/out/networks"
OUT = f"{ROOT}/data/out/furniture"

PROPS = {"waste_basket": "LitterBin"}   # OSM amenity value -> prefab key in MargateFurnitureGenerator
KERB  = 0.12                            # MargateRoadGenerator.KerbH: pavement top sits this far above the centreline
SNAP  = 25.0                            # further than this from any road, the road tells us nothing; use the terrain

def tagval(ot, key):
    if not ot: return None
    tok = f'"{key}"=>"'; i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i + len(tok)); return ot[i + len(tok):j]

def load_roads():
    """Every draped centreline segment, bucketed by tile so a lookup only touches 3x3 tiles."""
    segs = defaultdict(list)
    for path in sorted(glob.glob(f"{NET}/roads_*.jsonl")):
        for line in open(path):
            r = json.loads(line)
            if r.get("cls") == "_junction": continue
            p = r["pts"]
            for a, b in zip(p, p[1:]):
                if a[0] == b[0] and a[2] == b[2]: continue          # 06 repeats the first vertex
                cx, cz = (a[0] + b[0]) / 2, (a[2] + b[2]) / 2
                segs[(int(cx // T), int(cz // T))].append((a[0], a[1], a[2], b[0], b[1], b[2], r["w"], r["pav"], r["cls"]))
    return segs

def nearest_road(x, z, segs):
    """Closest segment in the 3x3 tile neighbourhood -> (dist, y on line, (dx,dz), w, pav, cls, side, foot)."""
    i, j = int(x // T), int(z // T); best = None
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for (ax, ay, az, bx, by, bz, w, pav, cls) in segs.get((i + di, j + dj), ()):
                dx, dz = bx - ax, bz - az; L2 = dx * dx + dz * dz
                t = max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / L2)) if L2 > 0 else 0.0
                px, pz = ax + dx * t, az + dz * t
                d = math.hypot(x - px, z - pz)
                if best is None or d < best[0]:
                    side = 1.0 if ((x - px) * -dz + (z - pz) * dx) > 0 else -1.0    # which side of the line the node is on
                    best = (d, ay + (by - ay) * t, (dx, dz), w, pav, cls, side, (px, pz))
    return best

def place(osm_id, x, z, segs):
    """One placement record. yaw is Unity's rotation about Y in degrees, +Z turning toward +X."""
    nr = nearest_road(x, z, segs)
    if nr is None or nr[0] > SNAP:
        seed = int(hashlib.md5(str(osm_id).encode()).hexdigest()[:8], 16)
        return {"x": round(x, 2), "y": None, "z": round(z, 2), "yaw": float(seed % 360), "src": "terrain",
                "d": None, "cls": None, "nudged": False}
    d, y_line, (dx, dz), w, pav, cls, side, (px, pz) = nr
    yaw = round(math.degrees(math.atan2(dx, dz)) % 360.0, 1)
    half = w / 2.0; nudged = False
    if d < half:                                                    # mapped in the carriageway
        target = half + (pav / 2.0 if pav > 0 else 0.6)
        L = math.hypot(dx, dz); nx, nz = -dz / L * side, dx / L * side
        x, z = px + nx * target, pz + nz * target; d = target; nudged = True
    if d <= half + pav + 1.0:
        y, src = y_line + (KERB if pav > 0 else 0.0), ("kerb" if pav > 0 else "road")
    else:
        y, src = None, "terrain"                                    # verge, forecourt, park edge: let the terrain say
    return {"x": round(x, 2), "y": None if y is None else round(y, 2), "z": round(z, 2), "yaw": yaw,
            "src": src, "d": round(d, 1), "cls": cls, "nudged": nudged}

def main():
    segs = load_roads()
    nseg = sum(len(v) for v in segs.values())
    if nseg == 0: sys.exit(f"10: FATAL -- no road segments in {NET}; run step 06 first")
    os.makedirs(OUT, exist_ok=True)
    for old in glob.glob(f"{OUT}/furniture_*.jsonl"): os.remove(old)

    src = ogr.Open(f"{ROOT}/data/derived/margate.gpkg")
    lyr = src.GetLayer("points")
    has_field = lyr.GetLayerDefn().GetFieldIndex("amenity") >= 0     # default osmconf keeps amenity inside other_tags
    buckets, n_amenity, outside, kinds = defaultdict(list), 0, 0, Counter()
    for f in lyr:
        ot = f.GetField("other_tags")
        am = f.GetField("amenity") if has_field else tagval(ot, "amenity")
        if not am: continue
        n_amenity += 1; kinds[am] += 1
        if am not in PROPS: continue
        g = f.GetGeometryRef()
        if g is None: continue
        x, z = g.GetX() - E0, g.GetY() - N0
        if not (0 <= x < NX * T and 0 <= z < NY * T): outside += 1; continue
        rec = {"id": f.GetField("osm_id"), "prop": PROPS[am], "name": f.GetField("name") or None}
        rec.update(place(rec["id"], x, z, segs))
        buckets[(int(rec["x"] // T), int(rec["z"] // T))].append(rec)

    # Distrust quiet success: an empty points layer means step 01 did not convert it, not that Margate has no bins.
    if n_amenity == 0: sys.exit("10: FATAL -- no amenity nodes in the points layer; check step 01 converted 'points'")

    n = 0
    for (i, j), items in sorted(buckets.items()):
        with open(f"{OUT}/furniture_x{i}_y{j}.jsonl", "w") as fh:
            for r in items: fh.write(json.dumps(r, separators=(",", ":")) + "\n"); n += 1
    srcs = Counter(r["src"] for v in buckets.values() for r in v)
    json.dump({"placed": n, "tiles": len(buckets), "outside_grid": outside, "by_height_source": dict(srcs),
               "nudged_out_of_carriageway": sum(r["nudged"] for v in buckets.values() for r in v),
               "amenity_kinds_seen": dict(kinds.most_common(12)), "props": PROPS},
              open(f"{ROOT}/data/out/qa_furniture.json", "w"), indent=1)
    print(f"wrote {n} placements across {len(buckets)} tiles -> {OUT}   ({nseg} road segments consulted)")
    print(f"height from: {dict(srcs)}   outside grid: {outside}   amenity nodes total: {n_amenity}")
    if n == 0: print("10: WARNING -- amenity nodes exist but none are waste_basket; nothing to place")

if __name__ == "__main__":
    main()
