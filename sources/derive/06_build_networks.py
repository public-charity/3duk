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
import glob, json, math, os, sys
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
NX, NY = CFG["nx"], CFG["ny"]
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
    if not (0.0 <= fx <= W - 1 and 0.0 <= fy <= H - 1):
        # Outside the DTM's extent. The old code clamped to the edge pixel here, which
        # gave every vertex beyond the mosaic a confident, wrong elevation. It is a gap.
        return (0.0, False)
    x0, y0 = int(math.floor(fx)), int(math.floor(fy))
    x0 = min(x0, W - 2); y0 = min(y0, H - 2)          # last row/col still interpolates inward
    tx, ty = fx - x0, fy - y0
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
total_len, n_nodata, n_outside = 0.0, 0, 0


def flush(cur, run, wy, gap):
    if cur is not None and len(run) >= 2:
        buckets[cur].append({**{k: wy[k] for k in KEEP}, "z_gap": gap, "pts": run})


def tile_of(e, n):
    """Tile index, or None when the vertex is off the grid. The Overpass bbox is
    deliberately generous; the grid is the model, and nothing is written for tiles
    with negative indices."""
    i, j = int((e - E0) // T), int((n - N0) // T)
    return (i, j) if 0 <= i < NX and 0 <= j < NY else None


for wy in ways:
    pts = chaikin(densify(wy["pts"], TUN["densify_step_m"]), TUN["chaikin_iters"])
    # Sample first, then fill DTM gaps from BOTH directions along the way, so a way that
    # starts inside a gap borrows its first real elevation instead of dropping to zero.
    samp = []
    for (e, n) in pts:
        tile = tile_of(e, n)
        if tile is None:
            n_outside += 1
            samp.append((e, n, None, None))
            continue
        z, ok = ground(e, n)
        samp.append((e, n, z if ok else None, tile))
    zs = [s[2] for s in samp]
    n_nodata += sum(1 for (_, _, z, t) in samp if z is None and t is not None)
    last = None
    for idx in range(len(zs)):
        if zs[idx] is not None: last = zs[idx]
        elif last is not None and samp[idx][3] is not None: zs[idx] = last
    nxt = None
    for idx in range(len(zs) - 1, -1, -1):
        if zs[idx] is not None: nxt = zs[idx]
        elif nxt is not None and samp[idx][3] is not None: zs[idx] = nxt

    # z_gap is per SEGMENT: only the tile runs that actually contain a filled vertex carry
    # it, so a consumer can trust the segments that were fully sampled.
    run, cur, run_gap = [], None, False
    for (e, n, z_raw, tile), z in zip(samp, zs):
        filled = z_raw is None
        if tile is None:                                 # off the grid: close the run here
            flush(cur, run, wy, run_gap)
            run, cur, run_gap = [], None, False
            continue
        if z is None: z = 0.0                            # the whole way sits in a DTM hole
        if cur is None: cur = tile
        v = [round(e, 2), round(n, 2), round(z, 2)]
        if tile != cur:
            run.append(v); run_gap |= filled             # the seam vertex belongs to both runs
            flush(cur, run, wy, run_gap)
            run = [run[-1]]; cur = tile; run_gap = filled
        run.append(v); run_gap |= filled
    flush(cur, run, wy, run_gap)
    for a, b in zip(pts, pts[1:]): total_len += math.hypot(b[0] - a[0], b[1] - a[1])

for (e, n), w in junc.items():
    tile = tile_of(e, n)
    if tile is None: continue
    z, _ = ground(e, n)
    buckets[tile].append({"cls": "_junction", "r": round(w / 2.0 + TUN["junction_margin_m"], 2),
                          "pts": [[round(e, 2), round(n, 2), round(z, 2)]]})

# Clear the previous run's tiles first: after a grid or bbox change the old files would
# otherwise sit beside the new ones and step 10 would read both.
for old in glob.glob(os.path.join(OUT, "roads_*.jsonl")):
    os.remove(old)
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
           "vertices_without_dtm": n_nodata,
           "vertices_outside_grid": n_outside},
          open(os.path.join(OUT, "networks_manifest.json"), "w"), indent=1)

print(f"wrote {n} segments across {len(buckets)} tiles -> {OUT}")
print(f"road length: {total_len/1000:.1f} km   junction discs: {len(junc)}")
print("classes:", dict(Counter(w["cls"] for w in ways).most_common(8)))
if n_nodata:
    print(f"06: WARNING -- {n_nodata:,} vertices had no DTM value; elevation carried from the "
          f"nearest valid neighbour and the segment tagged z_gap. Check LIDAR coverage.")
