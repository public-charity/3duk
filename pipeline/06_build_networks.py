#!/usr/bin/env python3.14
"""OSM highways -> per-tile road centrelines, draped on the LIDAR terrain.

Emits centreline + width rather than finished geometry, so Unity can rebuild the
ribbons at different widths without re-running GDAL.

Two things that matter for how it looks:
  * Chaikin smoothing -- OSM ways are angular, and raw vertices make every bend
    read as a facet. Two iterations kills it without moving the road.
  * A per-class height lift, so where a service road meets a trunk road the
    higher class wins the depth test instead of z-fighting. Much cheaper than
    boolean-merging road surfaces at junctions, and it reads fine.
"""
import json, os, math
from collections import Counter, defaultdict
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions(); ogr.UseExceptions()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG  = json.load(open(f"{ROOT}/pipeline/config/margate.json"))
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
OUT = f"{ROOT}/data/out/networks"; os.makedirs(OUT, exist_ok=True)

# carriageway width (m), pavement each side (m), draw-order lift (m)
SPEC = {
 "motorway":(14.0,0.0,0.24), "motorway_link":(7.0,0.0,0.24),
 "trunk":(12.0,2.0,0.24),    "trunk_link":(7.0,1.5,0.24),
 "primary":(10.0,2.0,0.22),  "primary_link":(6.5,1.5,0.22),
 "secondary":(8.5,2.0,0.20), "secondary_link":(6.0,1.5,0.20),
 "tertiary":(7.0,1.8,0.18),  "tertiary_link":(5.5,1.5,0.18),
 "residential":(6.0,1.5,0.16), "unclassified":(5.5,1.5,0.16),
 "living_street":(5.0,1.2,0.16), "service":(3.5,0.0,0.14),
 "pedestrian":(6.0,0.0,0.14),  "track":(3.0,0.0,0.12),
 "bridleway":(3.0,0.0,0.12),   "cycleway":(2.5,0.0,0.12),
 "footway":(2.0,0.0,0.10),     "path":(1.8,0.0,0.10),
 "steps":(2.0,0.0,0.10),
}
SKIP = {"construction","proposed","no","corridor","elevator","platform","raceway"}

dtm_ds = gdal.Open(f"{ROOT}/data/interim/dtm.vrt")
gt = dtm_ds.GetGeoTransform()
DTM = dtm_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
H, W = DTM.shape

def ground(e, n):
    """Bilinear sample of the DTM -- matches Unity's terrain interpolation."""
    fx = (e - gt[0]) / gt[1] - 0.5
    fy = (n - gt[3]) / gt[5] - 0.5
    x0, y0 = int(math.floor(fx)), int(math.floor(fy))
    tx, ty = fx - x0, fy - y0
    x0 = min(max(x0, 0), W - 2); y0 = min(max(y0, 0), H - 2)
    a = DTM[y0, x0]; b = DTM[y0, x0+1]; c = DTM[y0+1, x0]; d = DTM[y0+1, x0+1]
    v = (a*(1-tx) + b*tx)*(1-ty) + (c*(1-tx) + d*tx)*ty
    return float(v) if np.isfinite(v) and v > -1e30 else 0.0

def tagval(ot, key):
    if not ot: return None
    tok = f'"{key}"=>"'; i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i+len(tok)); return ot[i+len(tok):j]

def densify(pts, step=8.0):   # chaikin x2 refines this to ~2 m
    out = [pts[0]]
    for i in range(1, len(pts)):
        ax, ay = out[-1]; bx, by = pts[i]
        d = math.hypot(bx-ax, by-ay)
        if d > step:
            n = int(d // step)
            for k in range(1, n+1):
                t = k*step/d
                if t < 1.0: out.append((ax+(bx-ax)*t, ay+(by-ay)*t))
        out.append(pts[i])
    return out

def chaikin(pts, iters=2):
    """Corner-cutting. Keeps the endpoints pinned so junctions stay put."""
    for _ in range(iters):
        if len(pts) < 3: break
        new = [pts[0]]
        for i in range(len(pts)-1):
            ax, ay = pts[i]; bx, by = pts[i+1]
            new.append((ax*0.75+bx*0.25, ay*0.75+by*0.25))
            new.append((ax*0.25+bx*0.75, ay*0.25+by*0.75))
        new.append(pts[-1])
        pts = new
    return pts

# ---- pass 1: read ways, count endpoint usage to find junctions ----------
src = ogr.Open(f"{ROOT}/data/derived/margate.gpkg")
lyr = src.GetLayer("lines")
lyr.SetAttributeFilter("highway IS NOT NULL")
ways, endpoints = [], Counter()
for f in lyr:
    cls = f.GetField("highway")
    if cls in SKIP or cls not in SPEC: continue
    g = f.GetGeometryRef()
    if g is None or g.GetPointCount() < 2: continue
    pts = [(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())]
    ot = f.GetField("other_tags")
    w, pav, lift = SPEC[cls]
    lanes = tagval(ot, "lanes")
    if lanes:
        try: w = max(w, float(lanes)*3.0 + 1.0)
        except: pass
    w = round(w*2)/2.0                      # quantise to 0.5 m -- reads better, tiles cleanly
    ways.append({"id": f.GetField("osm_id"), "cls": cls, "w": w, "pav": pav, "lift": lift,
                 "name": f.GetField("name"), "pts": pts,
                 "bridge": bool(tagval(ot, "bridge")), "tunnel": bool(tagval(ot, "tunnel"))})
    for p in (pts[0], pts[-1]):
        endpoints[(round(p[0], 1), round(p[1], 1))] += 1

# junction discs where 3+ ways meet, sized by the widest incident road
junc = defaultdict(float)
for wy in ways:
    for p in (wy["pts"][0], wy["pts"][-1]):
        k = (round(p[0], 1), round(p[1], 1))
        if endpoints[k] >= 3: junc[k] = max(junc[k], wy["w"])

# ---- pass 2: smooth, drape, split per tile ------------------------------
buckets = defaultdict(list)
total_len = 0.0
for wy in ways:
    pts = chaikin(densify(wy["pts"]))
    run, cur = [], None
    for (e, n) in pts:
        z = ground(e, n) + wy["lift"]
        if wy["bridge"]: z += 3.0
        if wy["tunnel"]: z -= 4.0
        i, j = int((e-E0)//T), int((n-N0)//T)
        if cur is None: cur = (i, j)
        if (i, j) != cur:
            run.append([round(e-E0,2), round(z,2), round(n-N0,2)])   # duplicate at the seam
            if len(run) >= 2:
                buckets[cur].append({**{k: wy[k] for k in ("id","cls","w","pav","name")}, "pts": run})
            run = [run[-1]]; cur = (i, j)
        run.append([round(e-E0,2), round(z,2), round(n-N0,2)])
    if len(run) >= 2:
        buckets[cur].append({**{k: wy[k] for k in ("id","cls","w","pav","name")}, "pts": run})
    for a, b in zip(pts, pts[1:]): total_len += math.hypot(b[0]-a[0], b[1]-a[1])

for (e, n), w in junc.items():
    i, j = int((e-E0)//T), int((n-N0)//T)
    buckets[(i, j)].append({"cls": "_junction", "r": round(w/2.0 + 0.4, 2),
                            "pts": [[round(e-E0,2), round(ground(e,n)+0.085,2), round(n-N0,2)]]})

n = 0
for (i, j), items in sorted(buckets.items()):
    with open(f"{OUT}/roads_x{i}_y{j}.jsonl", "w") as fh:
        for it in items: fh.write(json.dumps(it, separators=(",",":"))+"\n"); n += 1
print(f"wrote {n} segments across {len(buckets)} tiles -> {OUT}")
print(f"road length: {total_len/1000:.1f} km   junction discs: {len(junc)}")
print("classes:", dict(Counter(w["cls"] for w in ways).most_common(8)))
