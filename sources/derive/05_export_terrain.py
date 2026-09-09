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

The fill is decided ONCE over the whole site mosaic, never per tile. Neighbouring tiles share
a row of samples (grid_res = tile_m/px + 1) and a per-tile fill made each of them invent that
row out of its own cells: on the Thanet product, 28,725 of 370,797 shared samples disagreed and
the worst by 5.34 m, which the landscape importer then had to resolve by picking a side -- a
512 m false cliff on every seam the sea touches (projects/one/docs/TERRAIN_ROADS.md 2). Filling
the mosaic makes a shared sample one cell with one answer, so the tiles cannot disagree; the
manifest's `shared_edges` block measures every one of them on the product just written and this
step exits non-zero if a single sample differs.
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
# Used only when the site has NO valid source cell ANYWHERE -- there is then nothing to interpolate
# from and every cell of the product is invention. Fill it at the site's declared water surface
# rather than 0 m ODN: on this coast such a site would be open sea beyond the composite, and a 0 m
# plate stands proud of the water plane a consumer draws at water_level. Sites without a water_level
# keep the old 0.0, so nothing inland moves. NOTE this used to fire per TILE, which is why 28 Thanet
# positions were flat -0.6 m plates standing ~2 m above the surveyed sea their neighbours carry
# (thanet.json coast.missing_tiles_are_water_note). Filling the mosaic instead gives those positions
# the nearest surveyed value and the ledge goes with it; they are still listed as tiles_fabricated
# because nothing in them was measured.
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

# ---- pass 1: assemble the site mosaic and fill it ONCE ---------------------------------
# Every raw tile on disk goes in, including positions wholly outside the clip: the clip is applied
# per tile below, AFTER the fill, so a gap near the line is filled from the real ground on both
# sides of it rather than from whichever side happens to be exported.
GT = {}                               # (i, j) -> the raw tile's geotransform, reused for the write
H_MOS, W_MOS, GT_MOS, PX = lib.mosaic_geom(CFG)
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]


def read_tile(i, j):
    src = os.path.join(P["lidar"], f"dtm_x{i}_y{j}.tif")
    if not os.path.exists(src):
        return None
    d = gdal.Open(src); b = d.GetRasterBand(1)
    a = b.ReadAsArray().astype(np.float32)
    gt = d.GetGeoTransform()
    # A tile is now placed by its grid INDEX, so it had better be where that index says it is:
    # one mis-filed tile would otherwise be silently laid over its neighbour.
    want = (E0 + i * T - PX / 2, PX, 0.0, N0 + (j + 1) * T + PX / 2, 0.0, -PX)
    if max(abs(g - w) for g, w in zip(gt, want)) > 1e-6:
        sys.exit(f"05: FATAL -- {src} is georeferenced at {gt}, but grid position ({i}, {j}) is {want}; "
                 f"the tile does not belong at the name it carries")
    GT[(i, j)] = gt
    return np.where(lib.nodata_mask(a, b.GetNoDataValue()), np.nan, a)


print(f"mosaic: {W_MOS} x {H_MOS} samples at {PX:g} m", flush=True)
MOS, MINFO = lib.assemble_mosaic(CFG, read_tile, label="05 site mosaic")
BAD = ~np.isfinite(MOS)
# A grid position with no raw tile at all is not a gap in a survey, it is somewhere the survey was
# never asked about (site B of the dry run, and step 02's EMPTY responses). Those cells are filled
# with everything else so the arithmetic stays uniform, but they are never exported and they are not
# counted as invention: only NoData INSIDE a tile that exists is.
COVERED = np.zeros(MOS.shape, bool)
for _p in GT:
    COVERED[lib.mosaic_window(CFG, *_p)] = True
N_BAD = int((BAD & COVERED).sum())
REACH = np.zeros(MOS.shape, np.float32) if BAD.any() else None
METHOD = lib.fill_nodata(MOS, BAD, label="site mosaic", empty_fill=EMPTY_FILL, px_m=PX, reach=REACH)
print(f"mosaic: {MINFO['tiles']} raw tiles of {CFG['nx'] * CFG['ny']} grid positions, {N_BAD:,} nodata cells "
      f"inside them ({100.0 * N_BAD / (W_MOS * H_MOS):.2f}% of the mosaic), fill '{METHOD}' decided once "
      f"over the whole site", flush=True)
if MINFO["overlap_conflicts"]:
    sys.exit(f"05: FATAL -- {MINFO['overlap_conflicts']:,} cells on a shared tile edge disagree between the two "
             f"raw tiles that carry them (worst {MINFO['overlap_conflict_max']:g} m). Two tiles cut from one "
             f"composite cannot disagree about a shared sample: the raw directory holds tiles from more than "
             f"one fetch. Re-fetch, do not paper over it.")

# ---- pass 2: cut the tiles back out, clip, write ----------------------------------------
manifest, lo, hi, methods, missing = [], 1e9, -1e9, {}, []
fabricated = []                       # positions with no surveyed cell at all: the whole tile is invention
slope_max, over45, cells = 0.0, 0, 0
clipped, n_clipped_total = [], 0
edges = {}                            # (i, j) -> the four border lines of what was WRITTEN, for shared_edges
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
        if (i, j) not in GT:
            missing.append([i, j])       # step 02 got EMPTY here: beyond the source's coverage
            continue
        win = lib.mosaic_window(CFG, i, j)
        a = MOS[win].copy()              # copy: the clip writes NoData into it below
        bad = BAD[win]
        n_nodata = int(bad.sum())
        surveyed = RES * RES - n_nodata
        if n_nodata == 0:
            m = "none"
        elif METHOD.startswith("all-nodata"):
            m = METHOD                   # nothing was surveyed anywhere in the site
        else:
            m = ("all-nodata -> " if surveyed == 0 else "") + "mosaic " + METHOD
        methods[m] = methods.get(m, 0) + 1
        if m.startswith("all-nodata"):
            fabricated.append([i, j])
        # Cells outside the clip, judged at their centres. Statistics below describe KEPT cells
        # only; on a clipless site every cell is kept and nothing here changes a number.
        keep = lib.cell_mask(CLIP, GT[(i, j)], RES, RES)
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
        pw, ph = lib.pixel_size(GT[(i, j)])
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
        dst.SetGeoTransform(GT[(i, j)])
        dst.SetProjection(wkt)
        if CLIP is not None:             # every tile of a clipped site declares it; a clipless one never
            dst.GetRasterBand(1).SetNoDataValue(ND)
        dst.GetRasterBand(1).WriteArray(a)
        dst.FlushCache()
        manifest.append({"x": i, "y": j,
                         "file": f"dtm_x{i}_y{j}.tif",
                         "min_m": round(float(kept_a.min()), 2),
                         "max_m": round(float(kept_a.max()), 2),
                         "nodata_cells": n_nodata,
                         "fill": m,
                         # How far this tile's invention had to travel to find a surveyed cell. Only
                         # present when there was any, so a fully surveyed site's manifest is unchanged.
                         **({} if not n_nodata or REACH is None else {
                             "fill_reach_max_m": round(float(REACH[win][bad].max()), 2),
                             "fill_reach_p50_m": round(float(np.percentile(REACH[win][bad], 50)), 2)}),
                         "slope_max_deg": round(t_max, 1),
                         "slope_p99_deg": round(t_p99, 1),
                         "cells_over_45deg": t_over,
                         **({} if CLIP is None else {"clip_state": state, "clipped_cells": n_clip})})
        edges[(i, j)] = {"n": a[0].copy(), "s": a[-1].copy(), "w": a[:, 0].copy(), "e": a[:, -1].copy()}

# ---- the shared-edge audit, on the tiles just written ----------------------------------
SE = lib.shared_edge_audit(edges)
SE["note"] = ("Every sample two neighbouring tiles SHARE (grid_res = tile_m/px + 1, so tile (i, j)'s east "
              "column IS tile (i+1, j)'s west column), compared on the files just written. One landscape "
              "vertex, so any difference is a step the consumer has to resolve by picking a side. The "
              "nodata fill is decided once over the site mosaic (lib.assemble_mosaic + lib.fill_nodata), so "
              "this must be 0 and step 05 exits non-zero if it is not. It was 28,725 samples and 5.34 m "
              "on the Thanet product built by the per-tile fill this replaced.")

# Only present when it happened, so a site with full coverage keeps the manifest it always had.
fab = {} if not fabricated else {
    "tiles_fabricated": fabricated,
    "empty_fill_m": EMPTY_FILL,
    "tiles_fabricated_note": "Grid positions where the source had no valid cell of their own. Nothing here was "
                             "surveyed: every cell was filled from the site mosaic, from a surveyed cell that "
                             "may be far away -- read the tile's fill_reach_max_m before treating any of it as "
                             "ground. empty_fill_m is used only if the WHOLE SITE had no valid cell. Distinct "
                             "from tiles_missing (no source tile) and tiles_clipped (deliberately outside the model)."}
RB = REACH[BAD & COVERED] if (N_BAD and REACH is not None) else None   # the reach of every filled cell, once
fill_block = {} if not N_BAD else {
    "fill": {
        "method": METHOD,
        "decided_over": "the whole site mosaic, once",
        "mosaic": {"shape": [H_MOS, W_MOS], "px_m": PX, "raw_tiles": MINFO["tiles"],
                   "shared_cells_written_twice": MINFO["overlap_cells"],
                   "shared_cell_conflicts": MINFO["overlap_conflicts"],
                   "shared_cell_conflict_max_m": round(MINFO["overlap_conflict_max"], 4)},
        "nodata_cells": N_BAD,
        "nodata_pct_of_mosaic": round(100.0 * N_BAD / (W_MOS * H_MOS), 3),
        **({} if RB is None else {
            "reach_m": {k: round(float(v), 2) for k, v in
                        zip(("max", "p99", "p95", "p50", "mean"),
                            (RB.max(), *np.percentile(RB, [99, 95, 50]), RB.mean()))},
            "cells_by_reach_m": {b: int(((RB > lo_) & (RB <= hi_)).sum())
                                 for b, lo_, hi_ in (("<=1.5", 0.0, 1.5), ("1.5-5", 1.5, 5.0), ("5-20", 5.0, 20.0),
                                                     ("20-100", 20.0, 100.0), ("100-500", 100.0, 500.0),
                                                     (">500", 500.0, float("inf")))}}),
        "note": "Cells the source never measured, filled nearest-valid from the site mosaic so that two tiles "
                "sharing an edge cannot invent different heights for it (shared_edges proves they do not). "
                "reach_m is the distance each filled cell had to travel to reach a surveyed one: a few metres "
                "is a gap in a survey, hundreds of metres is ground beyond it. The values are in the product "
                "and carry no marker of their own -- this block and the per-tile fill_reach_max_m are the record."}}
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
           "shared_edges": SE,
           "tiles": manifest,
           "tiles_missing": missing,
           **fill_block,
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
if RB is not None:
    print(f"nodata reach: max {RB.max():.1f} m  p99 {np.percentile(RB, 99):.1f}  p50 {np.percentile(RB, 50):.1f}"
          f"   ({int((RB <= 5).sum()):,} of {N_BAD:,} filled cells are within 5 m of surveyed ground)")
print(f"shared edges: {SE['pairs']} tile pairs, {SE['samples_compared']:,} shared samples, "
      f"{SE['samples_disagreeing']:,} disagree (max {SE['max_disagreement_m']:g} m)")
if fabricated:
    print(f"05: WARNING -- {len(fabricated)} tile position(s) had NO surveyed cell of their own "
          f"({len(fabricated) * RES * RES:,} fabricated cells). Nothing there was measured; every cell came from "
          f"the nearest surveyed cell in the site mosaic, which may be far away (per-tile fill_reach_max_m). "
          f"They are listed as tiles_fabricated in the manifest. Positions: {fabricated}", flush=True)
if "median (degraded)" in METHOD:
    print("05: NOTE -- the degraded median fill was used; install scipy for a true "
          "nearest-valid fill before treating this output as final.")
if SE["samples_disagreeing"]:
    sys.exit(f"05: FATAL -- {SE['samples_disagreeing']:,} of {SE['samples_compared']:,} shared-edge samples differ "
             f"between neighbouring tiles (worst {SE['max_disagreement_m']:g} m at {SE['max_at']}). Two tiles cut "
             f"from one filled mosaic cannot disagree about a sample they share; something writes tiles from more "
             f"than one array. The product on disk carries the numbers (terrain_manifest.shared_edges) -- do not "
             f"ship it.")
