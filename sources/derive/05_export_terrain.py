#!/usr/bin/env python3.14
"""Per-tile terrain: cleaned Float32 GeoTIFF in the site CRS, elevation in real metres.

This is deliberately NOT an engine heightmap. It stays north-up, georeferenced and
unnormalised, so it is readable by anything that reads a GeoTIFF and carries no
consumer's row order or encoding window. sources/adapters/unity.py turns these into
16-bit RAW heightmaps; write a sibling adapter for any other consumer.

Two things this step exists to do beyond copying pixels:
  * fill nodata honestly (nearest-valid where scipy is available, and say so when not)
  * report the true elevation range, so a consumer encoding into a fixed window can
    be told when its window would clip real ground rather than discovering a plateau
"""
import json, os, sys
import numpy as np
from osgeo import gdal, osr
gdal.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
P = lib.paths(CFG)
OUT = os.path.join(P["out"], "terrain")
lib.mkdirs(OUT)
RES = CFG["grid_res"]

srs = osr.SpatialReference(); srs.ImportFromEPSG(lib.epsg(CFG))
wkt = srs.ExportToWkt()
drv = gdal.GetDriverByName("GTiff")

manifest, lo, hi, methods = [], 1e9, -1e9, {}
for i in range(CFG["nx"]):
    for j in range(CFG["ny"]):
        src = os.path.join(P["lidar"], f"dtm_x{i}_y{j}.tif")
        if not os.path.exists(src):
            continue
        d = gdal.Open(src); b = d.GetRasterBand(1)
        a = b.ReadAsArray().astype(np.float32)
        bad = lib.nodata_mask(a, b.GetNoDataValue())
        m = lib.fill_nodata(a, bad, label=f"dtm_x{i}_y{j}")
        methods[m] = methods.get(m, 0) + 1
        if a.shape != (RES, RES):
            sys.exit(f"05: FATAL -- {src} is {a.shape}, expected {(RES, RES)}; "
                     f"grid_res and the WCS request window disagree")
        lo, hi = min(lo, float(a.min())), max(hi, float(a.max()))

        dst = drv.Create(os.path.join(OUT, f"dtm_x{i}_y{j}.tif"), RES, RES, 1,
                         gdal.GDT_Float32, options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"])
        dst.SetGeoTransform(d.GetGeoTransform())
        dst.SetProjection(wkt)
        dst.GetRasterBand(1).WriteArray(a)
        dst.FlushCache()
        manifest.append({"x": i, "y": j,
                         "file": f"dtm_x{i}_y{j}.tif",
                         "min_m": round(float(a.min()), 2),
                         "max_m": round(float(a.max()), 2),
                         "nodata_cells": int(bad.sum()),
                         "fill": m})

json.dump({"site": CFG["site"], "crs": CFG["crs"],
           "origin": CFG["origin"], "tile_m": CFG["tile_m"], "res": RES,
           "vertical_datum": CFG.get("vertical_datum", "source datum (ODN for EA LIDAR)"),
           "elevation_units": "metres",
           "range_m": [round(lo, 2), round(hi, 2)],
           "tiles": manifest},
          open(os.path.join(OUT, "terrain_manifest.json"), "w"), indent=1)

print(f"wrote {len(manifest)} terrain tiles -> {OUT}")
print(f"elevation range across site: {lo:.2f} .. {hi:.2f} m")
print(f"nodata fill: {methods}")
if "median (degraded)" in methods:
    print("05: NOTE -- some tiles used the degraded median fill; install scipy for a true "
          "nearest-valid fill before treating this output as final.")
