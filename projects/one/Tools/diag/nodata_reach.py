#!/usr/bin/env python3
"""D1 -- how far a NoData cell has to reach for a valid neighbour.

Step 05 fills each tile's NoData from that tile's own valid cells (lib.fill_nodata ->
scipy.ndimage.distance_transform_edt on a 513x513 array). Two tiles therefore invent
different values for the row they share. The fix is a fill that sees across the tile
boundary; this measures how wide a halo that needs, by running ONE distance transform over
the whole site mosaic of the RAW rasters and reporting the reach.

  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
  C:/Users/Shadow/code/3duk-env/env/python.exe Tools/diag/nodata_reach.py --out <dir>/reach.json
"""
import argparse, json, os
import numpy as np
from osgeo import gdal
gdal.UseExceptions()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="C:/Users/Shadow/code/3duk")
    ap.add_argument("--site", default="thanet")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    prod = os.path.join(args.repo, "data", args.site, "out", "terrain")
    raw = os.path.join(args.repo, "data", args.site, "raw", "lidar")
    man = json.load(open(os.path.join(prod, "terrain_manifest.json"), encoding="utf-8"))
    res = int(man["res"])
    nx = max(t["x"] for t in man["tiles"]) + 1
    ny = max(t["y"] for t in man["tiles"]) + 1
    q = res - 1
    W, H = nx * q + 1, ny * q + 1
    print("mosaic %d x %d" % (W, H), flush=True)
    valid = np.zeros((H, W), dtype=bool)
    present = np.zeros((H, W), dtype=bool)
    for t in man["tiles"]:
        i, j = t["x"], t["y"]
        p = os.path.join(raw, "dtm_x%d_y%d.tif" % (i, j))
        if not os.path.isfile(p):
            continue
        d = gdal.Open(p)
        b = d.GetRasterBand(1)
        a = b.ReadAsArray().astype(np.float32)
        nd = b.GetNoDataValue()
        bad = ~np.isfinite(a)
        if nd is not None:
            bad |= np.isclose(a, nd)
        # mosaic row 0 = north = tile j = ny-1 row 0
        r0 = (ny - 1 - j) * q
        c0 = i * q
        valid[r0:r0 + res, c0:c0 + res] |= ~bad
        present[r0:r0 + res, c0:c0 + res] = True
    from scipy import ndimage
    print("distance transform ...", flush=True)
    dt = ndimage.distance_transform_edt(~valid).astype(np.float32)
    gap = present & ~valid
    reach = dt[gap]
    # the shared rows/columns between kept tiles
    edge = np.zeros((H, W), dtype=bool)
    for t in man["tiles"]:
        i, j = t["x"], t["y"]
        r0 = (ny - 1 - j) * q
        c0 = i * q
        edge[r0, c0:c0 + res] = True
        edge[r0 + q, c0:c0 + res] = True
        edge[r0:r0 + res, c0] = True
        edge[r0:r0 + res, c0 + q] = True
    edge &= present
    eg = edge & ~valid
    bins = [0, 1.5, 3, 5, 10, 20, 50, 100, 200, 500, 1000, 1e9]
    hist = [int(((reach > bins[k]) & (reach <= bins[k + 1])).sum()) for k in range(len(bins) - 1)]
    ehist = [int(((dt[eg] > bins[k]) & (dt[eg] <= bins[k + 1])).sum()) for k in range(len(bins) - 1)] if eg.any() else []
    out = {"mosaic": [W, H], "tiles": len(man["tiles"]),
           "reach_histogram_bins_m": bins[:-1] + ["inf"],
           "reach_histogram_all_nodata": hist,
           "reach_histogram_shared_edge_nodata": ehist,
           "cells_in_kept_tiles": int(present.sum()),
           "cells_nodata_raw": int(gap.sum()),
           "pct_nodata_raw": 100.0 * gap.sum() / max(present.sum(), 1),
           "reach_m": {"max": float(reach.max()) if reach.size else 0.0,
                       "p99": float(np.percentile(reach, 99)) if reach.size else 0.0,
                       "p95": float(np.percentile(reach, 95)) if reach.size else 0.0,
                       "p50": float(np.percentile(reach, 50)) if reach.size else 0.0,
                       "mean": float(reach.mean()) if reach.size else 0.0},
           "shared_edge_cells": int(edge.sum()),
           "shared_edge_nodata_cells": int(eg.sum()),
           "shared_edge_reach_m": {"max": float(dt[eg].max()) if eg.any() else 0.0,
                                   "p99": float(np.percentile(dt[eg], 99)) if eg.any() else 0.0,
                                   "p95": float(np.percentile(dt[eg], 95)) if eg.any() else 0.0,
                                   "p50": float(np.percentile(dt[eg], 50)) if eg.any() else 0.0},
           "halo_needed_px": {
               "for_all_nodata": int(np.ceil(float(reach.max()))) if reach.size else 0,
               "for_shared_edges_only": int(np.ceil(float(dt[eg].max()))) if eg.any() else 0,
               "p999_shared_edges": float(np.percentile(dt[eg], 99.9)) if eg.any() else 0.0},
           "note": "reach = Euclidean distance in 1 m cells from a NoData cell to the nearest "
                   "surveyed cell, computed once over the whole site mosaic; a per-tile fill with "
                   "a halo of that many pixels reproduces the mosaic answer exactly."}
    json.dump(out, open(args.out, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
