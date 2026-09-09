#!/usr/bin/env python3
"""D3 -- road/terrain fusion audit.

The road surface is built at a SMOOTHED terrain height (BRIEF 1.1: "Do NOT follow raw
LiDAR point-for-point"); the landscape carries the RAW survey. Wherever the raw ground
rises above the smoothed curve the terrain erupts through the carriageway.

This measures it. For a sample of real Thanet splines, at every station, it evaluates the
modelled road SURFACE height across the full carriageway width (crown + camber + bank at
several lateral offsets) and the LANDSCAPE height at the same plan position, and reports
the signed clearance (road - terrain; negative = terrain above the road).

  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
  C:/Users/Shadow/code/3duk-env/env/python.exe Tools/diag/fusion_audit.py \
      --n 250 --windows 5,10,20,40 --out <dir>/fusion.json
"""
import argparse, glob, json, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "blender")))

from streetscape import schema as S            # noqa: E402
from streetscape import io_json                # noqa: E402
from streetscape.spline import (Spline, Frames, moving_average_arclength,  # noqa: E402
                                apply_pins, rate_limit)
from streetscape.terrain import Heightfield    # noqa: E402


# ---------------------------------------------------------------------------------------
def rebuild_with_window(sp: Spline, W: float, passes: int = None):
    """Recompute z_ref / bank / frames for a different smoothing window, in place.

    Stations, widths and camber do not depend on W, so this reproduces exactly what
    Spline.__init__ would have done with sampling.smoothing_window_m = W."""
    passes = int(sp.sampling.smoothing_passes if passes is None else passes)
    z_s = moving_average_arclength(sp.s, sp.z_fill, float(W), passes)
    sp.z_ref = apply_pins(z_s, sp.s, sp.pins, float(sp.sampling.pin_blend_m)) if sp.pins else z_s
    bmax = float(sp.sampling.bank_max_deg)
    beta_t = np.clip(moving_average_arclength(sp.s, sp.bank_raw, float(W), 1), -bmax, bmax)
    beta = (1.0 - sp.roll_mask) * beta_t + sp.roll_mask * sp.roll_pl
    sp.bank_deg = rate_limit(beta, sp.s, float(sp.sampling.bank_rate_max_deg_per_m))
    p3 = np.column_stack([sp.xy, sp.z_ref])
    t3 = np.column_stack([sp.t_h_xy, np.zeros(len(sp.s))])
    sp.frames = Frames.build(sp.s, p3, t3, sp.bank_deg)
    return sp


def surface_grid(sp: Spline, k: int):
    """(N, K) plan x, plan y, world z of the road surface across the carriageway.

    Lateral offsets run from -edge_offset(RIGHT) to +edge_offset(LEFT) -- the full surface
    width of Renderer A (DESIGN.md 4.1). Each point is frames.p + d*n + h*b with
    h = camber height (Spline.surface_h), exactly as the ribbon vertices are placed."""
    oL = sp.edge_offset(S.LEFT)
    oR = sp.edge_offset(S.RIGHT)
    f = np.linspace(0.0, 1.0, k)[None, :]
    d = (-oR)[:, None] + f * (oL + oR)[:, None]          # (N, K)
    h = sp.surface_h(d)                                   # (N, K)
    F = sp.frames
    P = F.p[:, None, :] + d[:, :, None] * F.n[:, None, :] + h[:, :, None] * F.b[:, None, :]
    return P[:, :, 0], P[:, :, 1], P[:, :, 2], d


def terrain_slope_deg(hf: Heightfield, x, y, step=1.0):
    zx1 = hf.sample(x + step, y); zx0 = hf.sample(x - step, y)
    zy1 = hf.sample(x, y + step); zy0 = hf.sample(x, y - step)
    gx = (zx1 - zx0) / (2 * step)
    gy = (zy1 - zy0) / (2 * step)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def pct(v, q):
    v = np.asarray(v, dtype=np.float64)
    return float(np.percentile(v, q)) if v.size else 0.0


def dist(v):
    v = np.asarray(v, dtype=np.float64)
    if v.size == 0:
        return {"n": 0}
    return {"n": int(v.size), "max": float(v.max()), "p99": pct(v, 99), "p95": pct(v, 95),
            "p50": pct(v, 50), "mean": float(v.mean())}


# ---------------------------------------------------------------------------------------
def measure(sp: Spline, hf: Heightfield, k: int, want_slope: bool):
    """Per-station clearance record for one spline."""
    X, Y, Z, D = surface_grid(sp, k)
    zt = hf.sample(X.ravel(), Y.ravel()).reshape(X.shape)
    clear = Z - zt                                  # + road above ground, - ground erupts
    valid = np.isfinite(clear)
    n_valid_rows = valid.any(axis=1)
    with np.errstate(invalid="ignore"):
        c = np.where(valid, clear, np.inf)
        min_clear = c.min(axis=1)                   # worst point across the width
    min_clear[~n_valid_rows] = np.nan
    # arc-length span each station owns (half to each neighbour)
    s = sp.s
    span = np.empty_like(s)
    if len(s) > 1:
        span[1:-1] = (s[2:] - s[:-2]) / 2.0
        span[0] = (s[1] - s[0]) / 2.0
        span[-1] = (s[-1] - s[-2]) / 2.0
    else:
        span[:] = 0.0
    slope = terrain_slope_deg(hf, sp.xy[:, 0], sp.xy[:, 1]) if want_slope else np.full(len(s), np.nan)
    return {"s": s, "min_clear": min_clear, "span": span, "slope": slope,
            "clear": clear, "valid": valid, "z_ref": sp.z_ref, "z_raw": sp.z_raw,
            "n_valid_stations": int(np.isfinite(min_clear).sum())}


def aggregate(records, label):
    """records: list of (cls, per-station arrays)."""
    mc = np.concatenate([r["min_clear"] for _, r in records]) if records else np.array([])
    sp_ = np.concatenate([r["span"] for _, r in records]) if records else np.array([])
    sl = np.concatenate([r["slope"] for _, r in records]) if records else np.array([])
    cls = np.concatenate([np.full(len(r["min_clear"]), c, dtype=object) for c, r in records]) if records else np.array([])
    ok = np.isfinite(mc)
    mc, sp_, sl, cls = mc[ok], sp_[ok], sl[ok], cls[ok]
    pen = np.maximum(0.0, -mc)
    hit = pen > 0.0
    out = {
        "label": label,
        "splines": len(records),
        "stations_with_terrain": int(mc.size),
        "stations_penetrated": int(hit.sum()),
        "fraction_stations_penetrated": float(hit.mean()) if mc.size else 0.0,
        "carriageway_km_total": float(sp_.sum()) / 1000.0,
        "carriageway_km_penetrated": float(sp_[hit].sum()) / 1000.0,
        "fraction_length_penetrated": float(sp_[hit].sum() / sp_.sum()) if sp_.sum() else 0.0,
        "penetration_m_over_penetrated_stations": dist(pen[hit]),
        "penetration_m_over_all_stations": dist(pen),
        "min_clearance_m_distribution": {"min": float(mc.min()) if mc.size else 0.0,
                                         "p01": pct(mc, 1), "p05": pct(mc, 5), "p50": pct(mc, 50),
                                         "p95": pct(mc, 95), "max": float(mc.max()) if mc.size else 0.0},
    }
    by_cls = {}
    for c in sorted(set(cls.tolist())):
        m = cls == c
        by_cls[c] = {"stations": int(m.sum()),
                     "fraction_penetrated": float(hit[m].mean()),
                     "km_total": float(sp_[m].sum()) / 1000.0,
                     "km_penetrated": float(sp_[m & hit].sum()) / 1000.0,
                     "pen_max_m": float(pen[m].max()) if m.any() else 0.0,
                     "pen_p95_m": pct(pen[m & hit], 95), "pen_p50_m": pct(pen[m & hit], 50)}
    out["by_class"] = by_cls
    buckets = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 90)]
    by_slope = {}
    for lo, hi in buckets:
        m = np.isfinite(sl) & (sl >= lo) & (sl < hi)
        by_slope["%d-%d deg" % (lo, hi)] = {
            "stations": int(m.sum()),
            "fraction_penetrated": float(hit[m].mean()) if m.any() else 0.0,
            "km_total": float(sp_[m].sum()) / 1000.0,
            "km_penetrated": float(sp_[m & hit].sum()) / 1000.0,
            "pen_max_m": float(pen[m].max()) if m.any() else 0.0,
            "pen_p95_m": pct(pen[m & hit], 95)}
    out["by_terrain_slope"] = by_slope
    return out


# ---------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--streetscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape")
    ap.add_argument("--extra-doc", action="append", default=[],
                    help="extra site document (e.g. the authored test stretch)")
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--all", action="store_true",
                    help="every road/rail spline in the directory (the acceptance gate), not a sample")
    ap.add_argument("--gate-m", type=float, default=None,
                    help="exit 1 if any station's clearance is below -gate_m (e.g. 0.005)")
    ap.add_argument("--k", type=int, default=9, help="lateral samples across the carriageway")
    ap.add_argument("--windows", default="20", help="comma-separated smoothing windows in metres")
    ap.add_argument("--layers", default="roads,rail")
    ap.add_argument("--seed", type=int, default=20260909)
    ap.add_argument("--out", required=True)
    ap.add_argument("--worst-out", default=None, help="write the worst station's cross/along profile here")
    args = ap.parse_args()

    print("loading heightfield ...", flush=True)
    hf = Heightfield.from_landscape_dir(args.landscape)
    print("  tiles %d" % len(hf.tiles), flush=True)

    files = sorted(glob.glob(os.path.join(args.streetscape, "site_x*_y*.json")))
    layers = set(args.layers.split(","))
    rng = random.Random(args.seed)
    # stratified: walk the tiles in a fixed order, take splines round-robin so the sample
    # is spread over the isle rather than clustered in the first tiles read.
    per_file = []
    for p in files:
        doc = json.load(open(p, encoding="utf-8"))
        idx = [i for i, s in enumerate(doc["splines"])
               if (s.get("source") or {}).get("layer") in layers and s["profile_ids"].get("road")]
        rng.shuffle(idx)
        if idx:
            per_file.append((p, idx))
    rng.shuffle(per_file)
    chosen = []
    if args.all:
        for p, idx in per_file:
            chosen.extend((p, i) for i in idx)
        args.n = len(chosen)
    r = 0
    while len(chosen) < args.n and any(r < len(idx) for _, idx in per_file):
        for p, idx in per_file:
            if r < len(idx):
                chosen.append((p, idx[r]))
                if len(chosen) >= args.n:
                    break
        r += 1
    extra = [(p, None) for p in args.extra_doc]
    print("selected %d splines from %d tiles (+%d extra docs)" % (len(chosen), len(per_file), len(extra)), flush=True)

    windows = [float(w) for w in args.windows.split(",")]
    results = {w: [] for w in windows}
    extra_results = {w: [] for w in windows}
    site_cache = {}
    built = 0
    skipped = []
    worst = None

    def sites(path):
        if path not in site_cache:
            site_cache[path] = io_json.load_site(path)
        return site_cache[path]

    def run(path, i, bucket):
        nonlocal built, worst
        site = sites(path)
        sdef = site.splines[i]
        cls = (sdef.source.cls if sdef.source is not None else None) or "?"
        try:
            sp = Spline(sdef, site, hf)
        except Exception as e:                                    # noqa: BLE001
            skipped.append([os.path.basename(path), i, repr(e)[:120]])
            return
        base_W = float(sp.sampling.smoothing_window_m)
        for W in windows:
            rebuild_with_window(sp, W)
            rec = measure(sp, hf, args.k, want_slope=True)
            bucket[W].append((cls, rec))
            if W == base_W and rec["n_valid_stations"]:
                pen = np.nanmax(np.where(np.isfinite(rec["min_clear"]), -rec["min_clear"], -np.inf))
                if worst is None or pen > worst[0]:
                    j = int(np.nanargmax(np.where(np.isfinite(rec["min_clear"]), -rec["min_clear"], -np.inf)))
                    worst = (float(pen), path, i, j, sdef.id, cls, float(sp.s[j]),
                             float(sp.xy[j, 0]), float(sp.xy[j, 1]))
        built += 1
        if built % 25 == 0:
            print("  built %d" % built, flush=True)

    for path, i in chosen:
        run(path, i, results)
    for path, _ in extra:
        site = sites(path)
        for i in range(len(site.splines)):
            if site.splines[i].profile_ids.road:
                run(path, i, extra_results)

    out = {"config": {"n_requested": args.n, "n_built": built, "k_lateral": args.k,
                      "windows_m": windows, "layers": sorted(layers), "seed": args.seed,
                      "landscape": args.landscape, "streetscape": args.streetscape,
                      "extra_docs": args.extra_doc},
           "skipped": skipped,
           "by_window": {str(w): aggregate(results[w], "sample W=%g" % w) for w in windows},
           "extra_by_window": {str(w): aggregate(extra_results[w], "extra W=%g" % w) for w in windows}
           if args.extra_doc else {},
           "worst_station": None if worst is None else
           {"penetration_m": worst[0], "file": os.path.basename(worst[1]), "spline_index": worst[2],
            "station_index": worst[3], "spline_id": worst[4], "cls": worst[5], "s_m": worst[6],
            "local_xy_m": [worst[7], worst[8]]}}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "skipped"}, indent=1)[:6000])

    if args.gate_m is not None:
        worst_pen = max((v["penetration_m_over_penetrated_stations"].get("max", 0.0)
                         for v in out["by_window"].values()), default=0.0)
        ok = worst_pen <= args.gate_m
        print("GATE %s: worst penetration %.6f m, allowed %.6f m"
              % ("PASS" if ok else "FAIL", worst_pen, args.gate_m))
        if not ok:
            sys.exit(1)

    if args.worst_out and worst is not None:
        json.dump({"worst": out["worst_station"], "note": "run worked_example.py for the profiles"},
                  open(args.worst_out, "w"), indent=1)


if __name__ == "__main__":
    main()
