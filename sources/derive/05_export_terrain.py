#!/usr/bin/env python3.14
"""DTM GeoTIFF -> Unity 16-bit RAW heightmaps (one per 512m tile).

Unity TerrainData indexes heights[z, x] with z increasing NORTH; GeoTIFF row 0
is NORTH, so we flip vertically. Values are unsigned 16-bit little-endian,
normalised over [y_base, y_base + y_size] in metres ODN.
"""
import json, os, glob
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG  = json.load(open(f"{ROOT}/sources/config/margate.json"))
OUT  = f"{ROOT}/data/out/terrain"; os.makedirs(OUT, exist_ok=True)
YB, YS, RES = CFG["terrain_y_base"], CFG["terrain_y_size"], CFG["heightmap_res"]

manifest, lo, hi = [], 1e9, -1e9
for i in range(CFG["nx"]):
    for j in range(CFG["ny"]):
        src = f"{ROOT}/data/raw/lidar/dtm_x{i}_y{j}.tif"
        if not os.path.exists(src): continue
        d = gdal.Open(src); b = d.GetRasterBand(1)
        a = b.ReadAsArray().astype(np.float64)
        nd = b.GetNoDataValue()
        if nd is not None:
            bad = ~np.isfinite(a) | (a <= nd/2)
            if bad.any():                      # nearest-valid fill
                from scipy import ndimage      # optional; fall back to median
                a[bad] = np.median(a[~bad]) if (~bad).any() else 0.0
        assert a.shape == (RES, RES), f"{src} is {a.shape}, expected {(RES,RES)}"
        lo, hi = min(lo, a.min()), max(hi, a.max())
        h = np.clip((a - YB) / YS, 0.0, 1.0)
        h = np.flipud(h)                        # GeoTIFF north-first -> Unity south-first
        (h * 65535.0).round().astype("<u2").tofile(f"{OUT}/hm_x{i}_y{j}.raw")
        manifest.append({"x": i, "y": j,
                         "min_odn": round(float(a.min()), 2),
                         "max_odn": round(float(a.max()), 2)})
json.dump({"origin": CFG["origin"], "tile_m": CFG["tile_m"], "res": RES,
           "y_base": YB, "y_size": YS, "tiles": manifest},
          open(f"{OUT}/terrain_manifest.json", "w"), indent=1)
print(f"wrote {len(manifest)} heightmaps -> {OUT}")
print(f"ODN range across town: {lo:.2f} .. {hi:.2f} m  (encoded over {YB}..{YB+YS})")
