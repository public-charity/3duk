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
CLIP = lib.parse_clip(CFG)
ND = -9999.0          # declared NoData on a CLIPPED site only; a clipless site's tiles carry no NoData tag
OUT = os.path.join(P["out"], "terrain")
lib.mkdirs(OUT)
RES = CFG["grid_res"]
# A tile position with no valid source cell at all is fabricated wholesale (lib.fill_nodata). Fill it
# at the site's declared water surface rather than 0 m ODN: on this coast those positions are open sea
# beyond the composite, and a 0 m plate stands proud of the water plane a consumer draws at water_level.
# Sites without a water_level keep the old 0.0, so nothing inland moves.
EMPTY_FILL = float(CFG.get("water_level", 0.0))
# Clearing the product takes ~20 s and the manifest describing the OLD run stays on disk while it
# happens: a crash in between leaves a half-empty directory beside a manifest still claiming every
# tile. The marker is written FIRST and removed only after the manifest is, so exactly one file
# answers "is this product complete?" -- and regress_outputs.sh reports it as an unexpected ADD.
lib.begin_product(OUT, "05_export_terrain")
for old in glob.glob(os.path.join(OUT, "dtm_x*_y*.tif")):   # no stale tiles from a previous grid
    os.remove(old)

srs = osr.SpatialReference(); srs.ImportFromEPSG(lib.epsg(CFG))
wkt = srs.ExportToWkt()
drv = gdal.GetDriverByName("GTiff")

manifest, lo, hi, methods, missing = [], 1e9, -1e9, {}, []
fabricated = []                       # positions with no surveyed cell at all: the whole tile is invention
slope_max, over45, cells = 0.0, 0, 0
clipped, n_clipped_total = [], 0
for i in range(CFG["nx"]):
    for j in range(CFG["ny"]):
        src = os.path.join(P["lidar"], f"dtm_x{i}_y{j}.tif")
        # A position wholly outside the clip is not exported, whether or not a raw tile exists
        # (step 02 may have fetched it before the clip was configured). It goes to tiles_clipped,
        # so tiles_missing keeps meaning exactly "coverage gap".
        state = lib.tile_state(CLIP, CFG, i, j)
        if state == "outside":
            clipped.append([i, j])
            if os.path.exists(src):
                print(f"  dtm_x{i}_y{j}: wholly outside the clip; raw tile on disk, not exported", flush=True)
            continue
        if not os.path.exists(src):
            missing.append([i, j])       # step 02 got EMPTY here: beyond the source's coverage
            continue
        d = gdal.Open(src); b = d.GetRasterBand(1)
        a = b.ReadAsArray().astype(np.float32)
        bad = lib.nodata_mask(a, b.GetNoDataValue())
        m = lib.fill_nodata(a, bad, label=f"dtm_x{i}_y{j}", empty_fill=EMPTY_FILL)
        methods[m] = methods.get(m, 0) + 1
        if m.startswith("all-nodata"):
            fabricated.append([i, j])
        if a.shape != (RES, RES):
            sys.exit(f"05: FATAL -- {src} is {a.shape}, expected {(RES, RES)}; "
                     f"grid_res and the WCS request window disagree")
        # Cells outside the clip, judged at their centres. Statistics below describe KEPT cells
        # only; on a clipless site every cell is kept and nothing here changes a number.
        keep = lib.cell_mask(CLIP, d.GetGeoTransform(), RES, RES)
        n_clip = int((~keep).sum())
        if n_clip == RES * RES:          # defensive: cannot happen with EA tile geometry
            clipped.append([i, j])
            continue
        kept_a = a[keep]
        lo, hi = min(lo, float(kept_a.min())), max(hi, float(kept_a.max()))

        # Slope QA. Cliffs are where terrain fidelity dies quietly: a resample or a
        # smoothing pass downstream turns an 80 degree face into a 45 degree ramp with no
        # error anywhere. Recording the steepness that went IN lets a consumer prove the
        # faces came out. Measured on the EA DTM at Cliftonville: faces of 65-80 degrees.
        # The gradient is taken on the filled, unclipped array: real ground beyond the line
        # gives the true edge gradient; only the statistics are restricted to kept cells.
        pw, ph = lib.pixel_size(d.GetGeoTransform())
        gy, gx = np.gradient(a.astype(np.float64))
        slope = np.degrees(np.arctan(np.hypot(gx / pw, gy / ph)))
        kept_slope = slope[keep]
        t_max, t_p99, t_over = float(kept_slope.max()), float(np.percentile(kept_slope, 99)), int((kept_slope > 45).sum())
        slope_max, over45, cells = max(slope_max, t_max), over45 + t_over, cells + int(keep.sum())

        # The clip is applied AFTER the fill: a NoData cell in the output is a deliberate
        # absence (the model ends here), never a coverage gap -- those were filled above.
        if CLIP is not None:
            a[~keep] = ND
            n_clipped_total += n_clip

        dst = drv.Create(os.path.join(OUT, f"dtm_x{i}_y{j}.tif"), RES, RES, 1,
                         gdal.GDT_Float32, options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"])
        dst.SetGeoTransform(d.GetGeoTransform())
        dst.SetProjection(wkt)
        if CLIP is not None:             # every tile of a clipped site declares it; a clipless one never
            dst.GetRasterBand(1).SetNoDataValue(ND)
        dst.GetRasterBand(1).WriteArray(a)
        dst.FlushCache()
        manifest.append({"x": i, "y": j,
                         "file": f"dtm_x{i}_y{j}.tif",
                         "min_m": round(float(kept_a.min()), 2),
                         "max_m": round(float(kept_a.max()), 2),
                         "nodata_cells": int(bad.sum()),
                         "fill": m,
                         "slope_max_deg": round(t_max, 1),
                         "slope_p99_deg": round(t_p99, 1),
                         "cells_over_45deg": t_over,
                         **({} if CLIP is None else {"clip_state": state, "clipped_cells": n_clip})})

# Only present when it happened, so a site with full coverage keeps the manifest it always had.
fab = {} if not fabricated else {
    "tiles_fabricated": fabricated,
    "empty_fill_m": EMPTY_FILL,
    "tiles_fabricated_note": "Grid positions where the source had no valid cell at all. Nothing here was "
                             "surveyed: the whole tile is a flat plate at empty_fill_m (the site's water_level "
                             "where it has one, else 0). Their per-tile `fill` says the same. Distinct from "
                             "tiles_missing (no source tile) and tiles_clipped (deliberately outside the model)."}
extra = {} if CLIP is None else {
    "nodata": ND,
    "clip": lib.clip_manifest(CLIP, CFG),
    "tiles_clipped": clipped,
    "clipped_cells_total": n_clipped_total,
    "clip_note": "Cells outside the clip are written as the declared NoData AFTER source gaps were filled: "
                 "a NoData cell is a deliberate absence (the model ends here), never a coverage gap. Coverage "
                 "gaps were filled and are counted in nodata_cells; grid positions with no source tile are "
                 "tiles_missing; positions wholly outside the clip are tiles_clipped and have no file."}
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
           "tiles_missing": missing,
           **fab,
           **extra},
          open(os.path.join(OUT, "terrain_manifest.json"), "w"), indent=1)
lib.end_product(OUT)

print(f"wrote {len(manifest)} terrain tiles -> {OUT}" + (f"   ({len(missing)} grid positions have no source tile: {missing})" if missing else "")
      + (f"   ({len(clipped)} positions outside the clip: not exported)" if clipped else ""))
if CLIP is not None:
    print(f"clip: {n_clipped_total:,} cells outside the clip written as NoData {ND} across "
          f"{sum(1 for t in manifest if t['clip_state'] == 'straddle')} straddling tiles")
print(f"elevation range across site: {lo:.2f} .. {hi:.2f} m")
print(f"slope QA: steepest cell {slope_max:.1f} deg, {100.0 * over45 / max(cells, 1):.3f}% of cells over 45 deg")
print(f"nodata fill: {methods}")
if fabricated:
    print(f"05: WARNING -- {len(fabricated)} tile position(s) had NO surveyed cell at all and are exported as a "
          f"flat plate at {EMPTY_FILL:g} m ODN ({len(fabricated) * RES * RES:,} fabricated cells). Nothing there "
          f"was measured. They are listed as tiles_fabricated in the manifest and carry fill "
          f"'all-nodata -> {EMPTY_FILL:g}'. Positions: {fabricated}", flush=True)
if "median (degraded)" in methods:
    print("05: NOTE -- some tiles used the degraded median fill; install scipy for a true "
          "nearest-valid fill before treating this output as final.")
