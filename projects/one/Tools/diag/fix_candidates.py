#!/usr/bin/env python3
"""D3 -- decomposition of the fusion, and the three candidate fixes measured.

Decomposition (exact, per station):
    min_clear = (z_ref - z_raw_centre)            <- T1 longitudinal smoothing residual
              + min_k [ z_raw_centre + d_k sin(beta) + camber_k cos(beta) - z_terrain_k ]
    T2_flat   = z_raw_centre - max_k z_terrain_k  <- cross-section roughness (flat ribbon, no bank)
    T3        = T2 - T2_flat                      <- what bank + camber add

Candidates:
  (a) conform the landscape to the road over a corridor, blending out over a verge
  (b) raise the road to clear the local maximum ground plus a clearance
  (c) cut the landscape away under the corridor (visibility holes)

  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
  C:/Users/Shadow/code/3duk-env/env/python.exe Tools/diag/fix_candidates.py --n 250 --out <dir>/fixes.json
"""
import argparse, glob, json, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "blender")))
sys.path.insert(0, HERE)
from streetscape import schema as S            # noqa: E402
from streetscape import io_json                # noqa: E402
from streetscape.spline import Spline, moving_average_arclength   # noqa: E402
from streetscape.terrain import Heightfield    # noqa: E402
from fusion_audit import rebuild_with_window, surface_grid, dist, pct   # noqa: E402

VERGE_M = 2.0
BLEND_M = 3.0


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def per_spline(sp: Spline, hf: Heightfield, k: int, clearance: float,
               verge: float, blend: float, cell: float):
    N = len(sp.s)
    X, Y, Z, D = surface_grid(sp, k)
    zt = hf.sample(X.ravel(), Y.ravel()).reshape(X.shape)
    ok = np.isfinite(zt) & np.isfinite(Z)
    clear = np.where(ok, Z - zt, np.inf)
    min_clear = clear.min(axis=1)
    good = np.isfinite(sp.z_raw) & ok.any(axis=1)
    min_clear = np.where(good, min_clear, np.nan)

    # --- decomposition
    zr = sp.z_raw
    T1 = sp.z_ref - zr                                     # longitudinal
    tmax = np.where(ok, zt, -np.inf).max(axis=1)
    T2_flat = zr - tmax
    T2 = min_clear - T1
    T3 = T2 - T2_flat

    # arc span per station
    span = np.empty(N)
    if N > 1:
        span[1:-1] = (sp.s[2:] - sp.s[:-2]) / 2.0
        span[0] = (sp.s[1] - sp.s[0]) / 2.0
        span[-1] = (sp.s[-1] - sp.s[-2]) / 2.0
    else:
        span[:] = 0.0

    # --- (b) raise the road
    need = np.where(good, np.maximum(0.0, -min_clear) + clearance, np.nan)
    # a per-station lift is exactly the "follow the raw LIDAR" the brief forbids, so also
    # measure the honest version: running max over the smoothing window, then re-smoothed
    W = float(sp.sampling.smoothing_window_m)
    need_f = np.where(np.isfinite(need), need, 0.0)
    run = np.array([need_f[(sp.s >= s0 - W / 2) & (sp.s <= s0 + W / 2)].max() for s0 in sp.s])
    lift_sm = moving_average_arclength(sp.s, run, W, 1)
    lift_sm = np.maximum(lift_sm, need_f)                  # never below what is needed
    # after lifting, how far does the road float above the ground on its low side?
    top = np.where(ok, Z - zt, -np.inf).max(axis=1)
    top = np.where(np.isfinite(top), top, np.nan)
    gap_raw = np.where(good, top + need, np.nan)
    gap_sm = np.where(good, top + lift_sm, np.nan)

    # --- (a) conform the landscape: rasterise the corridor onto the 1 m grid
    oL, oR = sp.edge_offset(S.LEFT), sp.edge_offset(S.RIGHT)
    sl = sp.side_spec[S.LEFT]
    sr = sp.side_spec[S.RIGHT]
    # the CORE is the built surface: carriageway + kerb + pavement. It is genuinely flat in
    # reality, so holding the road plane across it is honest. Everything beyond it (verge +
    # blend) is a blend back to the raw survey.
    coreL = oL + sl.back_offset
    coreR = oR + sr.back_offset
    F = sp.frames
    cells = {}
    lat = np.arange(0.0, 1.0, 1.0)  # placeholder replaced below
    for i in range(N):
        if not good[i]:
            continue
        hi = float(coreL[i] + verge + blend)
        lo = -float(coreR[i] + verge + blend)
        lat = np.arange(lo, hi + cell * 0.5, cell)
        px = F.p[i, 0] + lat * F.n_flat[i, 0]
        py = F.p[i, 1] + lat * F.n_flat[i, 1]
        # target height: the road surface inside the carriageway, held at the edge level
        # across kerb+pavement+verge, then blended to the raw ground over `blend`
        dclamp = np.clip(lat, -float(oR[i]), float(oL[i]))
        z_road = (sp.z_ref[i] + dclamp * np.sin(np.radians(sp.bank_deg[i]))
                  + sp.surface_h(np.atleast_1d(dclamp))[0] * np.cos(np.radians(sp.bank_deg[i]))
                  if False else
                  sp.z_ref[i] + dclamp * np.sin(np.radians(sp.bank_deg[i]))
                  + np.asarray(sp.surface_h(dclamp[None, :]))[0] * np.cos(np.radians(sp.bank_deg[i])))
        edge_core = np.where(lat >= 0, float(coreL[i]), -float(coreR[i]))
        t_blend = (np.abs(lat) - np.abs(edge_core)) / (verge + blend)
        w = smoothstep(t_blend)
        zg = hf.sample(px, py)
        target = np.where(np.abs(lat) <= np.abs(edge_core), z_road,
                          z_road * (1 - w) + np.where(np.isfinite(zg), zg, z_road) * w)
        in_core = np.abs(lat) <= np.abs(edge_core)
        for a, b, t, g, c_ in zip(px, py, target, zg, in_core):
            if not np.isfinite(g):
                continue
            key = (int(round(a)), int(round(b)))
            prev = cells.get(key)
            if prev is None or abs(t - g) > abs(prev[0] - prev[1]):
                cells[key] = (t, g, bool(c_))
    deltas = np.array([t - g for t, g, _ in cells.values()]) if cells else np.array([])
    core_mask = np.array([c for _, _, c in cells.values()], dtype=bool) if cells else np.zeros(0, bool)

    return {"good": good, "span": span, "min_clear": min_clear,
            "T1": T1, "T2": T2, "T2_flat": T2_flat, "T3": T3,
            "lift_need": need, "lift_smoothed": lift_sm,
            "gap_after_lift_raw": gap_raw, "gap_after_lift_smoothed": gap_sm,
            "conform_cells": len(cells), "conform_delta": deltas, "conform_core": core_mask,
            "kerb_h": np.asarray(sl.kerb_height), "length_m": sp.length}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--streetscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape")
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--k", type=int, default=9)
    ap.add_argument("--clearance-m", type=float, default=0.05)
    ap.add_argument("--verge-m", type=float, default=VERGE_M)
    ap.add_argument("--blend-m", type=float, default=BLEND_M)
    ap.add_argument("--cell-m", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=20260909)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hf = Heightfield.from_landscape_dir(args.landscape)
    files = sorted(glob.glob(os.path.join(args.streetscape, "site_x*_y*.json")))
    rng = random.Random(args.seed)
    per_file = []
    for p in files:
        doc = json.load(open(p, encoding="utf-8"))
        idx = [i for i, s in enumerate(doc["splines"])
               if (s.get("source") or {}).get("layer") in ("roads", "rail") and s["profile_ids"].get("road")]
        rng.shuffle(idx)
        if idx:
            per_file.append((p, idx))
    rng.shuffle(per_file)
    chosen, r = [], 0
    while len(chosen) < args.n and any(r < len(i) for _, i in per_file):
        for p, i in per_file:
            if r < len(i):
                chosen.append((p, i[r]))
                if len(chosen) >= args.n:
                    break
        r += 1

    acc = {k: [] for k in ("min_clear", "T1", "T2", "T2_flat", "T3", "lift_need", "lift_smoothed",
                           "gap_after_lift_raw", "gap_after_lift_smoothed", "span", "conform_delta",
                           "conform_core")}
    cls_all = []
    n_cells = 0
    total_len = 0.0
    cache = {}
    built = 0
    for p, i in chosen:
        if p not in cache:
            cache[p] = io_json.load_site(p)
        site = cache[p]
        sd = site.splines[i]
        try:
            sp = Spline(sd, site, hf)
        except Exception:
            continue
        rebuild_with_window(sp, float(sp.sampling.smoothing_window_m))
        r_ = per_spline(sp, hf, args.k, args.clearance_m, args.verge_m, args.blend_m, args.cell_m)
        g = r_["good"]
        for kk in ("min_clear", "T1", "T2", "T2_flat", "T3", "lift_need", "lift_smoothed",
                   "gap_after_lift_raw", "gap_after_lift_smoothed", "span"):
            acc[kk].append(np.asarray(r_[kk])[g])
        acc["conform_delta"].append(r_["conform_delta"])
        acc["conform_core"].append(r_["conform_core"])
        cls_all.append(np.full(int(g.sum()), (sd.source.cls if sd.source else "?"), dtype=object))
        n_cells += r_["conform_cells"]
        total_len += r_["length_m"]
        built += 1
        if built % 25 == 0:
            print("  %d" % built, flush=True)

    cat = {k: (np.concatenate(v) if v else np.array([])) for k, v in acc.items()}
    cls = np.concatenate(cls_all) if cls_all else np.array([])
    span = cat["span"]
    kerb = 0.125
    out = {
        "config": vars(args), "splines_built": built, "network_km_sampled": total_len / 1000.0,
        "decomposition": {
            "note": "min_clear = T1 + T2 ; T2 = T2_flat + T3. Negative T means the ground wins.",
            "T1_longitudinal_smoothing_m": dist(cat["T1"]),
            "T1_signed": {"p05": pct(cat["T1"], 5), "p50": pct(cat["T1"], 50), "p95": pct(cat["T1"], 95),
                          "min": float(cat["T1"].min()), "max": float(cat["T1"].max()),
                          "mean": float(cat["T1"].mean())},
            "T2_flat_cross_roughness_m": {"p05": pct(cat["T2_flat"], 5), "p50": pct(cat["T2_flat"], 50),
                                          "p95": pct(cat["T2_flat"], 95), "min": float(cat["T2_flat"].min()),
                                          "mean": float(cat["T2_flat"].mean())},
            "T3_bank_and_camber_m": {"p05": pct(cat["T3"], 5), "p50": pct(cat["T3"], 50),
                                     "p95": pct(cat["T3"], 95), "min": float(cat["T3"].min()),
                                     "mean": float(cat["T3"].mean())},
            "share_of_penetration": {
                "stations_penetrated": int((cat["min_clear"] < 0).sum()),
                "penetration_explained_by_T1_only": int(((cat["min_clear"] < 0) & (cat["T1"] < 0) & (cat["T2"] >= 0)).sum()),
                "penetration_explained_by_T2_only": int(((cat["min_clear"] < 0) & (cat["T2"] < 0) & (cat["T1"] >= 0)).sum()),
                "both_negative": int(((cat["min_clear"] < 0) & (cat["T1"] < 0) & (cat["T2"] < 0)).sum()),
                "T2_negative_fraction": float((cat["T2"] < 0).mean()),
                "T1_negative_fraction": float((cat["T1"] < 0).mean())},
        },
        "candidate_a_conform": {
            "cells_touched_sample": n_cells,
            "delta_m_target_minus_raw": {
                "n": int(cat["conform_delta"].size),
                "max_fill": float(cat["conform_delta"].max()) if cat["conform_delta"].size else 0.0,
                "max_cut": float(cat["conform_delta"].min()) if cat["conform_delta"].size else 0.0,
                "p99_abs": pct(np.abs(cat["conform_delta"]), 99),
                "p95_abs": pct(np.abs(cat["conform_delta"]), 95),
                "p50_abs": pct(np.abs(cat["conform_delta"]), 50),
                "mean_signed": float(cat["conform_delta"].mean()) if cat["conform_delta"].size else 0.0,
                "frac_over_0_25m": float((np.abs(cat["conform_delta"]) > 0.25).mean()) if cat["conform_delta"].size else 0.0,
                "frac_over_1m": float((np.abs(cat["conform_delta"]) > 1.0).mean()) if cat["conform_delta"].size else 0.0,
                "frac_over_2m": float((np.abs(cat["conform_delta"]) > 2.0).mean()) if cat["conform_delta"].size else 0.0,
                "cells_over_2m": int((np.abs(cat["conform_delta"]) > 2.0).sum())},
            "delta_core_only": {
                "n": int(cat["conform_core"].sum()),
                "max_fill": float(cat["conform_delta"][cat["conform_core"]].max()),
                "max_cut": float(cat["conform_delta"][cat["conform_core"]].min()),
                "p99_abs": pct(np.abs(cat["conform_delta"][cat["conform_core"]]), 99),
                "p95_abs": pct(np.abs(cat["conform_delta"][cat["conform_core"]]), 95),
                "p50_abs": pct(np.abs(cat["conform_delta"][cat["conform_core"]]), 50),
                "frac_over_2m": float((np.abs(cat["conform_delta"][cat["conform_core"]]) > 2.0).mean())},
            "delta_blend_only": {
                "n": int((~cat["conform_core"]).sum()),
                "max_fill": float(cat["conform_delta"][~cat["conform_core"]].max()),
                "max_cut": float(cat["conform_delta"][~cat["conform_core"]].min()),
                "p99_abs": pct(np.abs(cat["conform_delta"][~cat["conform_core"]]), 99),
                "p50_abs": pct(np.abs(cat["conform_delta"][~cat["conform_core"]]), 50)},
            "corridor_note": "half-width = edge_offset + kerb + pavement + %g m verge, blended out over %g m"
                             % (args.verge_m, args.blend_m)},
        "candidate_b_raise": {
            "lift_per_station_m": dist(cat["lift_need"]),
            "lift_smoothed_m": dist(cat["lift_smoothed"]),
            "float_gap_after_raw_lift_m": dist(cat["gap_after_lift_raw"]),
            "float_gap_after_smoothed_lift_m": dist(cat["gap_after_lift_smoothed"]),
            "km_where_gap_exceeds_kerb_%.3fm" % kerb: float(span[cat["gap_after_lift_smoothed"] > kerb].sum()) / 1000.0,
            "km_total": float(span.sum()) / 1000.0,
            "frac_stations_gap_over_kerb": float((cat["gap_after_lift_smoothed"] > kerb).mean()),
            "frac_stations_gap_over_0_5m": float((cat["gap_after_lift_smoothed"] > 0.5).mean())},
        "by_class_T": {},
    }
    for c in sorted(set(cls.tolist())):
        m = cls == c
        out["by_class_T"][c] = {
            "stations": int(m.sum()),
            "T1_p05": pct(cat["T1"][m], 5), "T1_p95": pct(cat["T1"][m], 95),
            "T2_flat_p05": pct(cat["T2_flat"][m], 5), "T2_flat_p50": pct(cat["T2_flat"][m], 50),
            "T3_p05": pct(cat["T3"][m], 5), "T3_min": float(cat["T3"][m].min()),
            "lift_p95": pct(cat["lift_need"][m], 95), "lift_max": float(cat["lift_need"][m].max())}
    json.dump(out, open(args.out, "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "by_class_T"}, indent=1)[:7000])


if __name__ == "__main__":
    main()
