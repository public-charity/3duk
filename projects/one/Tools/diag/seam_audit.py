#!/usr/bin/env python3
"""D1 -- tile-boundary seam audit.

Adjacent 513x513 tiles SHARE a row/column of samples (grid_res 512 + 1). This tool reads
data/<site>/out/terrain/dtm_x*_y*.tif directly with GDAL and compares every shared edge
between horizontally and vertically adjacent tiles.

Geometry (verified from the GeoTransforms):
  tile (i, j) column 512 centre == tile (i+1, j) column 0 centre   (east neighbour)
  tile (i, j) row    0   centre == tile (i, j+1) row 512 centre    (north neighbour)

It also reads the RAW source rasters (data/<site>/raw/lidar/dtm_x*_y*.tif) at the same
edges so the fill hypothesis can be tested: if raw agrees where the product disagrees, the
per-tile NoData fill in step 05 is the whole cause.

Usage:
  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
  C:/Users/Shadow/code/3duk-env/env/python.exe Tools/diag/seam_audit.py \
      --site thanet --out <dir>/seam_audit.json
"""
import argparse, json, os, sys
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

ND = -9999.0


def edge_arrays(path, which):
    """Return (values, nodata_mask) for one edge of a tile raster."""
    d = gdal.Open(path)
    b = d.GetRasterBand(1)
    nd = b.GetNoDataValue()
    if which == "east":
        a = b.ReadAsArray(d.RasterXSize - 1, 0, 1, d.RasterYSize).astype(np.float64).ravel()
    elif which == "west":
        a = b.ReadAsArray(0, 0, 1, d.RasterYSize).astype(np.float64).ravel()
    elif which == "north":
        a = b.ReadAsArray(0, 0, d.RasterXSize, 1).astype(np.float64).ravel()
    elif which == "south":
        a = b.ReadAsArray(0, d.RasterYSize - 1, d.RasterXSize, 1).astype(np.float64).ravel()
    else:
        raise ValueError(which)
    bad = ~np.isfinite(a)
    if nd is not None:
        bad |= np.isclose(a, nd)
    gt = d.GetGeoTransform()
    return a, bad, gt


def stats(v):
    v = np.asarray(v, dtype=np.float64)
    if v.size == 0:
        return {"n": 0}
    return {"n": int(v.size), "max": float(v.max()), "p99": float(np.percentile(v, 99)),
            "p95": float(np.percentile(v, 95)), "p50": float(np.percentile(v, 50)),
            "mean": float(v.mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="thanet")
    ap.add_argument("--repo", default="C:/Users/Shadow/code/3duk")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tol", type=float, default=1e-6, help="metres; below this an edge agrees")
    args = ap.parse_args()

    prod = os.path.join(args.repo, "data", args.site, "out", "terrain")
    raw = os.path.join(args.repo, "data", args.site, "raw", "lidar")
    man = json.load(open(os.path.join(prod, "terrain_manifest.json")))
    present = {(t["x"], t["y"]) for t in man["tiles"]}
    fill_of = {(t["x"], t["y"]): t.get("fill", "?") for t in man["tiles"]}
    ndc_of = {(t["x"], t["y"]): t.get("nodata_cells", 0) for t in man["tiles"]}

    pairs = []
    for (i, j) in sorted(present):
        for (ni, nj, a_edge, b_edge, kind) in ((i + 1, j, "east", "west", "h"),
                                               (i, j + 1, "north", "south", "v")):
            if (ni, nj) not in present:
                continue
            pa = os.path.join(prod, f"dtm_x{i}_y{j}.tif")
            pb = os.path.join(prod, f"dtm_x{ni}_y{nj}.tif")
            va, ba, _ = edge_arrays(pa, a_edge)
            vb, bb, _ = edge_arrays(pb, b_edge)
            both = ~(ba | bb)
            d = np.abs(va - vb)
            d[~both] = 0.0
            n_dis = int((d > args.tol).sum())
            rec = {"kind": kind, "a": [i, j], "b": [ni, nj],
                   "n_comparable": int(both.sum()),
                   "n_nodata_either": int((ba | bb).sum()),
                   "n_disagree": n_dis,
                   "max_m": float(d.max()) if d.size else 0.0,
                   "p99_m": float(np.percentile(d[both], 99)) if both.any() else 0.0,
                   "p50_m": float(np.percentile(d[both], 50)) if both.any() else 0.0,
                   "sum_abs_m": float(d.sum()),
                   "fill_a": fill_of[(i, j)], "fill_b": fill_of[(ni, nj)],
                   "nodata_cells_a": ndc_of[(i, j)], "nodata_cells_b": ndc_of[(ni, nj)]}
            # raw edges: were the SOURCE samples equal there?
            ra = os.path.join(raw, f"dtm_x{i}_y{j}.tif")
            rb = os.path.join(raw, f"dtm_x{ni}_y{nj}.tif")
            if os.path.exists(ra) and os.path.exists(rb):
                wa, ma, _ = edge_arrays(ra, a_edge)
                wb, mb, _ = edge_arrays(rb, b_edge)
                rboth = ~(ma | mb)
                rd = np.abs(wa - wb)
                rd[~rboth] = 0.0
                rec["raw"] = {"n_comparable": int(rboth.sum()),
                              "n_disagree": int((rd > args.tol).sum()),
                              "max_m": float(rd.max()) if rd.size else 0.0,
                              "n_nodata_a": int(ma.sum()), "n_nodata_b": int(mb.sum()),
                              "n_nodata_either": int((ma | mb).sum())}
                # the fill hypothesis: at cells where the PRODUCT disagrees, was the RAW
                # data NoData on at least one side?
                dis = d > args.tol
                if dis.any():
                    rec["hyp"] = {
                        "disagree_and_raw_nodata_either": int((dis & (ma | mb)).sum()),
                        "disagree_and_raw_both_valid": int((dis & rboth).sum()),
                        "disagree_and_raw_both_valid_max_m":
                            float(rd[dis & rboth].max()) if (dis & rboth).any() else 0.0,
                        "raw_nodata_either_and_agree": int((~dis & (ma | mb)).sum()),
                    }
            pairs.append(rec)
        print(f"  {i},{j} done", end="\r", flush=True)

    dis_pairs = [p for p in pairs if p["n_disagree"] > 0]
    all_d = np.concatenate([np.full(p["n_disagree"], 0.0) for p in pairs]) if pairs else np.array([])
    # per-edge maxima distribution
    maxes = np.array([p["max_m"] for p in pairs])
    tiles_with_bad_edge = set()
    for p in dis_pairs:
        tiles_with_bad_edge.add(tuple(p["a"]))
        tiles_with_bad_edge.add(tuple(p["b"]))

    hyp_nodata = sum(p.get("hyp", {}).get("disagree_and_raw_nodata_either", 0) for p in pairs)
    hyp_valid = sum(p.get("hyp", {}).get("disagree_and_raw_both_valid", 0) for p in pairs)
    hyp_valid_max = max([p.get("hyp", {}).get("disagree_and_raw_both_valid_max_m", 0.0)
                         for p in pairs] or [0.0])

    summary = {
        "site": args.site, "tol_m": args.tol,
        "tiles_present": len(present),
        "pairs": len(pairs),
        "pairs_horizontal": sum(1 for p in pairs if p["kind"] == "h"),
        "pairs_vertical": sum(1 for p in pairs if p["kind"] == "v"),
        "pairs_disagreeing": len(dis_pairs),
        "tiles_touching_a_disagreeing_edge": len(tiles_with_bad_edge),
        "cells_compared": sum(p["n_comparable"] for p in pairs),
        "cells_disagreeing": sum(p["n_disagree"] for p in pairs),
        "edge_max_m": {"max": float(maxes.max()), "p99": float(np.percentile(maxes, 99)),
                       "p50": float(np.percentile(maxes, 50))} if maxes.size else {},
        "worst_pairs": sorted(dis_pairs, key=lambda p: -p["max_m"])[:15],
        "raw_totals": {
            "pairs_with_raw": sum(1 for p in pairs if "raw" in p),
            "raw_cells_compared": sum(p["raw"]["n_comparable"] for p in pairs if "raw" in p),
            "raw_cells_disagreeing": sum(p["raw"]["n_disagree"] for p in pairs if "raw" in p),
            "raw_max_m": max([p["raw"]["max_m"] for p in pairs if "raw" in p] or [0.0]),
        },
        "hypothesis_per_tile_fill": {
            "product_disagreeing_cells_where_raw_had_nodata_on_a_side": hyp_nodata,
            "product_disagreeing_cells_where_raw_was_valid_on_both_sides": hyp_valid,
            "of_those_max_raw_disagreement_m": hyp_valid_max,
        },
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({"summary": summary, "pairs": pairs}, open(args.out, "w"), indent=1)
    print()
    print(json.dumps(summary, indent=1)[:4000])


if __name__ == "__main__":
    main()
