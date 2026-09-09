#!/usr/bin/env python3
"""How much of the isle a road corridor actually covers, once overlaps are counted once.

Rasterises every road/rail polyline from the Streetscape documents onto the 1 m site grid
with a per-class corridor half-width, and reports the union area (candidate (a)'s burned
area and candidate (c)'s hole area) plus how much of it is covered by more than one
corridor (junctions and parallel ways -- where a burn has to arbitrate).

  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
  C:/Users/Shadow/code/3duk-env/env/python.exe Tools/diag/corridor_mask.py --out <dir>/corridor.json
"""
import argparse, glob, json, os
import numpy as np

from network_extent import WIDTH, KERB_PAVE   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--streetscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape")
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--verge-m", type=float, default=2.0)
    ap.add_argument("--blend-m", type=float, default=3.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    man = json.load(open(os.path.join(args.landscape, "landscape_manifest.json"), encoding="utf-8"))
    res, nx, ny = int(man["res"]), int(man["nx"]), int(man["ny"])
    q = res - 1
    W, H = nx * q + 1, ny * q + 1
    core = np.zeros((H, W), dtype=np.uint8)     # count of corridors covering the cell (saturating)
    full = np.zeros((H, W), dtype=bool)
    # which cells exist at all (kept tiles, unclipped)
    kept = np.zeros((H, W), dtype=bool)
    for t in man["tiles"]:
        i, j = t["x"], t["y"]
        c = np.fromfile(os.path.join(args.landscape, t["files"]["clip"]), dtype=np.uint8).reshape(res, res)
        r0 = (ny - 1 - j) * q
        c0 = i * q
        kept[r0:r0 + res, c0:c0 + res] |= (c == 255)

    # per-spline stamping so overlaps are counted once per spline
    files = sorted(glob.glob(os.path.join(args.streetscape, "site_x*_y*.json")))
    n_sp = 0
    tmp = np.zeros((H, W), dtype=bool)
    for p in files:
        doc = json.load(open(p, encoding="utf-8"))
        for s in doc["splines"]:
            src = s.get("source") or {}
            if src.get("layer") not in ("roads", "rail"):
                continue
            cls = src.get("cls") or "?"
            hc = WIDTH.get(cls, 4.0) / 2.0 + KERB_PAVE.get(cls, 0.0)
            hf_ = hc + args.verge_m + args.blend_m
            pts = s["points"]
            touched_r, touched_c = [], []
            for a, b in zip(pts, pts[1:]):
                L = float(np.hypot(b["x"] - a["x"], b["y"] - a["y"]))
                if L < 1e-9:
                    continue
                n = max(2, int(L / 0.5) + 1)
                t = np.linspace(0.0, 1.0, n)
                cx = a["x"] + t * (b["x"] - a["x"])
                cy = a["y"] + t * (b["y"] - a["y"])
                ux, uy = -(b["y"] - a["y"]) / L, (b["x"] - a["x"]) / L
                lat = np.arange(-hf_, hf_ + 0.25, 0.5)
                PX = (cx[:, None] + lat[None, :] * ux).ravel()
                PY = (cy[:, None] + lat[None, :] * uy).ravel()
                LT = np.abs(np.broadcast_to(lat[None, :], (n, len(lat))).ravel())
                col = np.rint(PX).astype(np.int64)
                row = (H - 1) - np.rint(PY).astype(np.int64)
                ok = (col >= 0) & (col < W) & (row >= 0) & (row < H)
                col, row, LT = col[ok], row[ok], LT[ok]
                full[row, col] = True
                m = LT <= hc
                tmp[row[m], col[m]] = True
                touched_r.append(row[m]); touched_c.append(col[m])
            if touched_r:
                tr = np.concatenate(touched_r); tc = np.concatenate(touched_c)
                sel = tmp[tr, tc]
                tr, tc = tr[sel], tc[sel]
                uniq = np.unique(tr.astype(np.int64) * W + tc.astype(np.int64))
                ur, uc = (uniq // W).astype(np.int64), (uniq % W).astype(np.int64)
                core[ur, uc] = np.minimum(core[ur, uc].astype(np.int32) + 1, 255).astype(np.uint8)
                tmp[tr, tc] = False
            n_sp += 1
        print("  %s" % os.path.basename(p), end="\r", flush=True)

    core_any = core > 0
    out = {"splines": n_sp,
           "grid": [W, H],
           "kept_cells": int(kept.sum()),
           "kept_km2": kept.sum() / 1e6,
           "core_cells": int(core_any.sum()),
           "core_km2": core_any.sum() / 1e6,
           "core_pct_of_kept": 100.0 * (core_any & kept).sum() / max(kept.sum(), 1),
           "core_and_kept_km2": (core_any & kept).sum() / 1e6,
           "corridor_with_blend_cells": int(full.sum()),
           "corridor_with_blend_km2": full.sum() / 1e6,
           "corridor_with_blend_pct_of_kept": 100.0 * (full & kept).sum() / max(kept.sum(), 1),
           "core_cells_covered_by_2plus_corridors": int((core >= 2).sum()),
           "core_overlap_pct": 100.0 * (core >= 2).sum() / max(int(core_any.sum()), 1),
           "core_cells_covered_by_3plus": int((core >= 3).sum()),
           "verge_m": args.verge_m, "blend_m": args.blend_m,
           "core_note": "core = carriageway + kerb + pavement (the built surface held at the road plane); "
                        "corridor_with_blend adds the verge and the blend-out"}
    json.dump(out, open(args.out, "w"), indent=1)
    print()
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
