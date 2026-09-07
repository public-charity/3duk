#!/usr/bin/env python3.14
"""OSM highways -> per-tile road centrelines, draped on the LIDAR terrain.

Emits centreline + width rather than finished geometry, so a consumer can rebuild the
ribbons at different widths without re-running GDAL.

Coordinates are [easting, northing, elevation] in CRS metres. Elevation is the third
component, not the second: this is survey data, not a scene graph. A consumer wanting
Y-up local coordinates converts (see sources/adapters/unity.py).

What this step does NOT do, deliberately:
  * no draw-order lift. Stacking coincident surfaces so they do not z-fight is a
    rendering concern; baking a fake 0.2 m into the elevation corrupts the survey.
    Consumers get `cls` and can rank it themselves.
  * no bridge/tunnel offset. The previous version added +3 m to bridges and -4 m to
    tunnels -- invented numbers that then overwrote the real draped elevation, and the
    flags themselves were dropped from the output. Now the flags are emitted and the
    elevation stays honest; a consumer that wants a deck raises it with its own number.

Chaikin smoothing IS still applied, because OSM's angular vertices otherwise read as
facets -- but it moves the centreline, so the iteration count is configurable and
recorded in the manifest. Set chaikin_iters to 0 for geometry faithful to OSM.
"""
import json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions(); ogr.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
TUN = CFG["tuning"]["roads"]
P   = lib.paths(CFG)
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
OUT = os.path.join(P["out"], "networks")
lib.mkdirs(OUT)

SPEC = {k: tuple(v) for k, v in TUN["widths_m"].items() if not k.startswith("_")}
SKIP = set(TUN["skip"])

dtm_ds = gdal.Open(os.path.join(P["interim"], "dtm.vrt"))
gt = dtm_ds.GetGeoTransform()
_band = dtm_ds.GetRasterBand(1)
DTM = _band.ReadAsArray().astype(np.float32)
# Mark nodata by the band's declared sentinel so ground() sees it as a gap whatever
# the value is -- a -9999 would otherwise drape roads 10 km underground.
DTM[lib.nodata_mask(DTM, _band.GetNoDataValue())] = np.nan
H, W = DTM.shape


def ground(e, n):
    """Bilinear sample of the DTM. Returns (elevation, ok); ok is False where the DTM
    has no measurement, so the caller can carry a real neighbouring value forward
    instead of silently dropping the road to zero."""
    fx = (e - gt[0]) / gt[1] - 0.5
    fy = (n - gt[3]) / gt[5] - 0.5
    x0, y0 = int(math.floor(fx)), int(math.floor(fy))
    tx, ty = fx - x0, fy - y0
    x0 = min(max(x0, 0), W - 2); y0 = min(max(y0, 0), H - 2)
    a = DTM[y0, x0]; b = DTM[y0, x0+1]; c = DTM[y0+1, x0]; d = DTM[y0+1, x0+1]
    v = (a*(1-tx) + b*tx)*(1-ty) + (c*(1-tx) + d*tx)*ty
    return (float(v), True) if np.isfinite(v) else (0.0, False)


def tagval(ot, key):
    if not ot: return None
    tok = '"' + key + '"=>"'
    i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i + len(tok))
    return ot[i + len(tok):j]


def densify(pts, step):
    out = [pts[0]]
    for i in range(1, len(pts)):
        ax, ay = out[-1]; bx, by = pts[i]
        d = math.hypot(bx - ax, by - ay)
        if d > step:
            n = int(d // step)
            for k in range(1, n + 1):
                t = k * step / d
                if t < 1.0: out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        out.append(pts[i])
    return out


def chaikin(pts, iters):
    """Corner-cutting. Keeps the endpoints pinned so junctions stay put."""
    for _ in range(iters):
        if len(pts) < 3: break
        new = [pts[0]]
        for i in range(len(pts) - 1):
            ax, ay = pts[i]; bx, by = pts[i + 1]
            new.append((ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25))
            new.append((ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75))
        new.append(pts[-1])
        pts = new
    return pts


# ---- pass 1: read ways, count endpoint usage to find junctions ----------
src = ogr.Open(P["gpkg"])
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
    w, pav = SPEC[cls]
    lanes = tagval(ot, "lanes")
    if lanes:
        try: w = max(w, float(lanes) * TUN["lane_width_m"] + TUN["lane_margin_m"])
        except: pass
    q = TUN["width_quantum_m"]
    w = round(w / q) * q
    ways.append({"id": f.GetField("osm_id"), "cls": cls, "w": w, "pav": pav,
                 "name": f.GetField("name"), "pts": pts,
                 "bridge": bool(tagval(ot, "bridge")), "tunnel": bool(tagval(ot, "tunnel"))})
    for p in (pts[0], pts[-1]):
        endpoints[(round(p[0], 1), round(p[1], 1))] += 1

# junction discs where N+ ways meet, sized by the widest incident road
junc = defaultdict(float)
for wy in ways:
    for p in (wy["pts"][0], wy["pts"][-1]):
        k = (round(p[0], 1), round(p[1], 1))
        if endpoints[k] >= TUN["junction_min_ways"]: junc[k] = max(junc[k], wy["w"])

# ---- pass 2: smooth, drape, split per tile ------------------------------
KEEP = ("id", "cls", "w", "pav", "name", "bridge", "tunnel")
buckets = defaultdict(list)
total_len, n_nodata = 0.0, 0
for wy in ways:
    pts = chaikin(densify(wy["pts"], TUN["densify_step_m"]), TUN["chaikin_iters"])
    run, cur, last_z, way_gap = [], None, None, False
    for (e, n) in pts:
        z, ok = ground(e, n)
        if not ok:
            n_nodata += 1
            way_gap = True
            z = last_z if last_z is not None else 0.0    # carry the last real value
        else:
            last_z = z
        i, j = int((e - E0) // T), int((n - N0) // T)
        if cur is None: cur = (i, j)
        v = [round(e, 2), round(n, 2), round(z, 2)]
        if (i, j) != cur:
            run.append(v)                                # duplicate at the seam
            if len(run) >= 2:
                buckets[cur].append({**{k: wy[k] for k in KEEP}, "z_gap": way_gap, "pts": run})
            run = [run[-1]]; cur = (i, j)
        run.append(v)
    if len(run) >= 2:
        buckets[cur].append({**{k: wy[k] for k in KEEP}, "z_gap": way_gap, "pts": run})
    for a, b in zip(pts, pts[1:]): total_len += math.hypot(b[0] - a[0], b[1] - a[1])

for (e, n), w in junc.items():
    i, j = int((e - E0) // T), int((n - N0) // T)
    z, _ = ground(e, n)
    buckets[(i, j)].append({"cls": "_junction", "r": round(w / 2.0 + TUN["junction_margin_m"], 2),
                            "pts": [[round(e, 2), round(n, 2), round(z, 2)]]})

n = 0
for (i, j), items in sorted(buckets.items()):
    with open(os.path.join(OUT, f"roads_x{i}_y{j}.jsonl"), "w") as fh:
        for it in items:
            fh.write(json.dumps(it, separators=(",", ":")) + "\n"); n += 1

json.dump({"site": CFG["site"], "crs": CFG["crs"],
           "coordinates": "[easting, northing, elevation] in CRS metres",
           "origin": CFG["origin"], "tile_m": CFG["tile_m"],
           "segments": n, "tiles": len(buckets),
           "length_km": round(total_len / 1000, 2), "junctions": len(junc),
           "smoothing": {"densify_step_m": TUN["densify_step_m"],
                         "chaikin_iters": TUN["chaikin_iters"]},
           "widths_m": {k: list(v) for k, v in SPEC.items()},
           "vertices_without_dtm": n_nodata},
          open(os.path.join(OUT, "networks_manifest.json"), "w"), indent=1)

print(f"wrote {n} segments across {len(buckets)} tiles -> {OUT}")
print(f"road length: {total_len/1000:.1f} km   junction discs: {len(junc)}")
print("classes:", dict(Counter(w["cls"] for w in ways).most_common(8)))
if n_nodata:
    print(f"06: WARNING -- {n_nodata:,} vertices had no DTM value; elevation carried from the "
          f"nearest valid neighbour and the segment tagged z_gap. Check LIDAR coverage.")
