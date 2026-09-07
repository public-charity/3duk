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
import glob, json, os, sys
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
for old in glob.glob(os.path.join(OUT, "dtm_x*_y*.tif")):   # no stale tiles from a previous grid
    os.remove(old)

srs = osr.SpatialReference(); srs.ImportFromEPSG(lib.epsg(CFG))
wkt = srs.ExportToWkt()
drv = gdal.GetDriverByName("GTiff")

manifest, lo, hi, methods, missing = [], 1e9, -1e9, {}, []
slope_max, over45, cells = 0.0, 0, 0
for i in range(CFG["nx"]):
    for j in range(CFG["ny"]):
        src = os.path.join(P["lidar"], f"dtm_x{i}_y{j}.tif")
        if not os.path.exists(src):
            missing.append([i, j])       # step 02 got EMPTY here: beyond the source's coverage
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

        # Slope QA. Cliffs are where terrain fidelity dies quietly: a resample or a
        # smoothing pass downstream turns an 80 degree face into a 45 degree ramp with no
        # error anywhere. Recording the steepness that went IN lets a consumer prove the
        # faces came out. Measured on the EA DTM at Cliftonville: faces of 65-80 degrees.
        pw, ph = lib.pixel_size(d.GetGeoTransform())
        gy, gx = np.gradient(a.astype(np.float64))
        slope = np.degrees(np.arctan(np.hypot(gx / pw, gy / ph)))
        t_max, t_p99, t_over = float(slope.max()), float(np.percentile(slope, 99)), int((slope > 45).sum())
        slope_max, over45, cells = max(slope_max, t_max), over45 + t_over, cells + slope.size

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
                         "fill": m,
                         "slope_max_deg": round(t_max, 1),
                         "slope_p99_deg": round(t_p99, 1),
                         "cells_over_45deg": t_over})

json.dump({"site": CFG["site"], "crs": CFG["crs"],
           "origin": CFG["origin"], "tile_m": CFG["tile_m"], "res": RES,
           "vertical_datum": CFG.get("vertical_datum", "source datum (ODN for EA LIDAR)"),
           "elevation_units": "metres",
           "range_m": [round(lo, 2), round(hi, 2)],
           "slope_qa": {"max_deg": round(slope_max, 1),
                        "pct_cells_over_45deg": round(100.0 * over45 / max(cells, 1), 3),
                        "note": "Steepness that went into the product, at native resolution. If a consumer's "
                                "terrain shows nothing steeper than ~45 degrees where this says 70+, the "
                                "consumer resampled or decimated it -- the data did not."},
           "tiles": manifest,
           "tiles_missing": missing},
          open(os.path.join(OUT, "terrain_manifest.json"), "w"), indent=1)

print(f"wrote {len(manifest)} terrain tiles -> {OUT}" + (f"   ({len(missing)} grid positions have no source tile: {missing})" if missing else ""))
print(f"elevation range across site: {lo:.2f} .. {hi:.2f} m")
print(f"slope QA: steepest cell {slope_max:.1f} deg, {100.0 * over45 / max(cells, 1):.3f}% of cells over 45 deg")
print(f"nodata fill: {methods}")
if "median (degraded)" in methods:
    print("05: NOTE -- some tiles used the degraded median fill; install scipy for a true "
          "nearest-valid fill before treating this output as final.")
