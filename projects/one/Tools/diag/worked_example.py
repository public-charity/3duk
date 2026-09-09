#!/usr/bin/env python3
"""D3 -- one place, in full: the raw DTM along and across a road, the smoothed curve the
road surface is built on, and where they cross.

  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
  C:/Users/Shadow/code/3duk-env/env/python.exe Tools/diag/worked_example.py \
      --doc <site_xN_yM.json> --spline-id roads:...:0 --out <dir>/worked.json
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "blender")))
from streetscape import schema as S           # noqa: E402
from streetscape import io_json               # noqa: E402
from streetscape.spline import Spline         # noqa: E402
from streetscape.terrain import Heightfield   # noqa: E402
sys.path.insert(0, HERE)
from fusion_audit import rebuild_with_window, surface_grid   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--doc", required=True)
    ap.add_argument("--spline-id", default=None)
    ap.add_argument("--spline-index", type=int, default=None)
    ap.add_argument("--k", type=int, default=25)
    ap.add_argument("--windows", default="5,10,20,40")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hf = Heightfield.from_landscape_dir(args.landscape)
    site = io_json.load_site(args.doc)
    idx = args.spline_index
    if idx is None:
        idx = next(i for i, s in enumerate(site.splines) if s.id == args.spline_id)
    sdef = site.splines[idx]
    sp = Spline(sdef, site, hf)
    out = {"doc": os.path.basename(args.doc), "spline_id": sdef.id, "index": idx,
           "cls": (sdef.source.cls if sdef.source else None),
           "profile_road": sdef.profile_ids.road,
           "length_m": sp.length, "stations": int(sp.n),
           "width_m": float(np.median(sp.width)),
           "smoothing_window_default_m": float(sp.sampling.smoothing_window_m)}

    windows = [float(w) for w in args.windows.split(",")]
    prof = {}
    worst_by_w = {}
    for W in windows:
        rebuild_with_window(sp, W)
        X, Y, Z, D = surface_grid(sp, args.k)
        zt = hf.sample(X.ravel(), Y.ravel()).reshape(X.shape)
        clear = Z - zt
        c = np.where(np.isfinite(clear), clear, np.inf)
        minc = c.min(axis=1)
        minc[~np.isfinite(clear).any(axis=1)] = np.nan
        prof[str(W)] = {"z_ref": sp.z_ref.tolist(), "min_clear": minc.tolist()}
        j = int(np.nanargmin(np.where(np.isfinite(minc), minc, np.inf)))
        worst_by_w[str(W)] = {"station": j, "s_m": float(sp.s[j]),
                              "min_clear_m": float(minc[j]),
                              "xy": [float(sp.xy[j, 0]), float(sp.xy[j, 1])]}
    out["worst_by_window"] = worst_by_w

    # the along-road table at the default window
    Wd = float(sp.sampling.smoothing_window_m)
    rebuild_with_window(sp, Wd)
    X, Y, Z, D = surface_grid(sp, args.k)
    zt = hf.sample(X.ravel(), Y.ravel()).reshape(X.shape)
    clear = Z - zt
    c = np.where(np.isfinite(clear), clear, np.inf)
    minc = c.min(axis=1)
    corridor_max_terrain = np.nanmax(np.where(np.isfinite(zt), zt, -np.inf), axis=1)
    out["along"] = {
        "note": "s, raw DTM at the centreline, smoothed z_ref, max raw terrain across the carriageway, "
                "min clearance across the carriageway",
        "columns": ["s_m", "z_raw_centre_m", "z_ref_m", "terrain_max_across_m", "min_clear_m"],
        "rows": [[round(float(a), 3), round(float(b), 4), round(float(cc), 4),
                  round(float(dd), 4), round(float(ee), 4)]
                 for a, b, cc, dd, ee in zip(sp.s, sp.z_raw, sp.z_ref, corridor_max_terrain, minc)],
    }
    j = int(np.nanargmin(np.where(np.isfinite(minc), minc, np.inf)))
    out["worst_station"] = {
        "station": j, "s_m": float(sp.s[j]), "xy": [float(sp.xy[j, 0]), float(sp.xy[j, 1])],
        "z_raw_centre_m": float(sp.z_raw[j]), "z_ref_m": float(sp.z_ref[j]),
        "bank_deg": float(sp.bank_deg[j]), "width_m": float(sp.width[j]),
        "min_clear_m": float(minc[j]),
        "cross_section": {
            "columns": ["lateral_d_m", "plan_x_m", "plan_y_m", "z_road_m", "z_terrain_m", "clearance_m"],
            "rows": [[round(float(D[j, k]), 3), round(float(X[j, k]), 3), round(float(Y[j, k]), 3),
                      round(float(Z[j, k]), 4), round(float(zt[j, k]), 4), round(float(clear[j, k]), 4)]
                     for k in range(X.shape[1])]},
    }
    # raw DTM cross-section on a 1 m ladder, wider than the carriageway
    F = sp.frames
    dd = np.arange(-12.0, 12.01, 0.5)
    px = F.p[j, 0] + dd * F.n_flat[j, 0]
    py = F.p[j, 1] + dd * F.n_flat[j, 1]
    out["worst_station"]["raw_cross_ladder"] = {
        "columns": ["d_m", "z_terrain_m"],
        "rows": [[round(float(a), 2), round(float(b), 4)] for a, b in zip(dd, hf.sample(px, py))]}
    # smoothing arithmetic at the worst station
    lo, hi = sp.s[j] - Wd / 2.0, sp.s[j] + Wd / 2.0
    m = (sp.s >= lo) & (sp.s <= hi)
    out["worst_station"]["window"] = {
        "W_m": Wd, "s_range": [float(lo), float(hi)], "stations_in_window": int(m.sum()),
        "z_raw_in_window": {"min": float(np.nanmin(sp.z_raw[m])), "max": float(np.nanmax(sp.z_raw[m])),
                            "mean": float(np.nanmean(sp.z_raw[m]))},
        "z_ref_here": float(sp.z_ref[j]), "z_raw_here": float(sp.z_raw[j])}
    json.dump(out, open(args.out, "w"), indent=1)
    printable = {k: v for k, v in out.items() if k != "along"}
    printable["along_rows"] = len(out["along"]["rows"])
    print(json.dumps(printable, indent=1)[:6000])


if __name__ == "__main__":
    main()
