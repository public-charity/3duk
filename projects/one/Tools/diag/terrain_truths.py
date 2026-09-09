#!/usr/bin/env python3
"""D2 -- two terrain truths.

Samples the same scattered points with
  (a) the numpy Heightfield over data/<site>/out/unreal/landscape  (the bytes the plugin reads)
  (b) the source GeoTIFF via GDAL (data/<site>/out/terrain)
and writes the point list as a CSV for Tools/ue/04_probe.py --points --landscape, which adds
  (c) the imported ALandscape (ALandscapeProxy::GetHeightAtLocation).

Two phases:
  --emit    build the point set, sample (a) and (b), write points.csv + truths_ab.json
  --join    read the probe CSV back and decompose (a) vs (b) vs (c)
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "blender")))
from streetscape.terrain import Heightfield   # noqa: E402


def dist(v, name):
    v = np.asarray(v, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"name": name, "n": 0}
    return {"name": name, "n": int(v.size), "max": float(np.abs(v).max()),
            "p99": float(np.percentile(np.abs(v), 99)), "p95": float(np.percentile(np.abs(v), 95)),
            "p50": float(np.percentile(np.abs(v), 50)), "rms": float(np.sqrt((v ** 2).mean())),
            "mean_signed": float(v.mean())}


def emit(args):
    hfl = Heightfield.from_landscape_dir(args.landscape)
    print("landscape tiles %d" % len(hfl.tiles), flush=True)
    man = hfl.manifest
    nx, ny, tile_m = int(man["nx"]), int(man["ny"]), float(man["tile_m"])
    rng = np.random.default_rng(args.seed)
    W, H = nx * tile_m, ny * tile_m

    # a plain scatter, then a steep-ground scatter (D2's claim is "on steep ground")
    def scatter(n, steep_min=None, batch=200000):
        got_x, got_y = [], []
        while sum(len(a) for a in got_x) < n:
            x = rng.uniform(0, W, batch)
            y = rng.uniform(0, H, batch)
            z = hfl.sample(x, y)
            ok = np.isfinite(z)
            if steep_min is not None:
                g = np.hypot((hfl.sample(x + 1, y) - hfl.sample(x - 1, y)) / 2.0,
                             (hfl.sample(x, y + 1) - hfl.sample(x, y - 1)) / 2.0)
                sl = np.degrees(np.arctan(g))
                ok &= np.isfinite(sl) & (sl >= steep_min)
            got_x.append(x[ok]); got_y.append(y[ok])
        return np.concatenate(got_x)[:n], np.concatenate(got_y)[:n]

    xs, ys = scatter(args.n)
    kind = np.array(["scatter"] * args.n, dtype=object)
    if args.n_steep:
        sx, sy = scatter(args.n_steep, steep_min=args.steep_min_deg)
        xs = np.concatenate([xs, sx]); ys = np.concatenate([ys, sy])
        kind = np.concatenate([kind, np.array(["steep"] * args.n_steep, dtype=object)])
    # vertex-exact points (integer metres) so the interpolation term can be isolated
    if args.n_vertex:
        vx, vy = scatter(args.n_vertex)
        vx = np.round(vx); vy = np.round(vy)
        keep = np.isfinite(hfl.sample(vx, vy))
        vx, vy = vx[keep], vy[keep]
        xs = np.concatenate([xs, vx]); ys = np.concatenate([ys, vy])
        kind = np.concatenate([kind, np.array(["vertex"] * len(vx), dtype=object)])

    z_hf = hfl.sample(xs, ys)
    slope = np.degrees(np.arctan(np.hypot(
        (hfl.sample(xs + 1, ys) - hfl.sample(xs - 1, ys)) / 2.0,
        (hfl.sample(xs, ys + 1) - hfl.sample(xs, ys - 1)) / 2.0)))
    # distance to the nearest tile boundary (the D1 seams live there)
    dbx = np.minimum(xs % tile_m, tile_m - (xs % tile_m))
    dby = np.minimum(ys % tile_m, tile_m - (ys % tile_m))
    dbound = np.minimum(dbx, dby)

    del hfl
    print("sampling the GeoTIFFs ...", flush=True)
    hfg = Heightfield.from_step05_dir(args.terrain)
    z_tif = hfg.sample(xs, ys)
    del hfg

    os.makedirs(os.path.dirname(args.points_csv), exist_ok=True)
    with open(args.points_csv, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("x,y\n")
        for x, y in zip(xs, ys):
            fh.write("%.6f,%.6f\n" % (x, y))
    np.savez(args.npz, x=xs, y=ys, z_hf=z_hf, z_tif=z_tif, slope=slope,
             dbound=dbound, kind=np.array([str(k) for k in kind]))

    d = z_hf - z_tif
    rep = {"points": int(len(xs)), "csv": args.points_csv,
           "hf_vs_geotiff": dist(d, "z_heightfield - z_geotiff"),
           "hf_vs_geotiff_steep": dist(d[kind == "steep"], "steep only"),
           "hf_vs_geotiff_vertex": dist(d[kind == "vertex"], "integer-metre vertices only"),
           "quantum_m": 1.0 / 128.0,
           "both_finite": int(np.isfinite(d).sum()),
           "hf_nan": int((~np.isfinite(z_hf)).sum()), "tif_nan": int((~np.isfinite(z_tif)).sum())}
    json.dump(rep, open(args.out, "w"), indent=1)
    print(json.dumps(rep, indent=1))


def join(args):
    z = np.load(args.npz, allow_pickle=False)
    xs, ys, z_hf, z_tif = z["x"], z["y"], z["z_hf"], z["z_tif"]
    slope, dbound, kind = z["slope"], z["dbound"], z["kind"]
    idx = {(round(float(a), 4), round(float(b), 4)): i for i, (a, b) in enumerate(zip(xs, ys))}
    z_ls = np.full(len(xs), np.nan)
    z_col = np.full(len(xs), np.nan)
    z_tr = np.full(len(xs), np.nan)
    clipped = np.zeros(len(xs), dtype=bool)
    n_rows = 0
    with open(args.probe_csv, encoding="utf-8") as fh:
        head = fh.readline().strip().split(",")
        ci = {name: k for k, name in enumerate(head)}
        for line in fh:
            p = line.rstrip("\n").split(",")
            if len(p) < 3:
                continue
            key = (round(float(p[ci["x"]]), 4), round(float(p[ci["y"]]), 4))
            i = idx.get(key)
            if i is None:
                continue
            n_rows += 1
            v = p[ci["z_landscape"]] if "z_landscape" in ci else ""
            if v != "":
                z_ls[i] = float(v)
            if "z_landscape_collision" in ci and p[ci["z_landscape_collision"]] != "":
                z_col[i] = float(p[ci["z_landscape_collision"]])
            if "z_trace" in ci and p[ci["z_trace"]] != "":
                z_tr[i] = float(p[ci["z_trace"]])
            if "clipped" in ci and p[ci["clipped"]] not in ("", "0"):
                clipped[i] = True

    d_hf_ls = z_hf - z_ls
    d_tif_ls = z_tif - z_ls
    d_hf_tif = z_hf - z_tif
    near_seam = dbound <= 1.0
    rep = {
        "rows_matched": n_rows, "points": int(len(xs)),
        "landscape_none": int((~np.isfinite(z_ls)).sum()),
        "A_heightfield_vs_geotiff": dist(d_hf_tif, "z_hf - z_tif  (r16 quantisation + fill/clip)"),
        "B_heightfield_vs_landscape": dist(d_hf_ls, "z_hf - z_landscape (import + interpolation)"),
        "C_geotiff_vs_landscape": dist(d_tif_ls, "z_tif - z_landscape (total, survey vs engine)"),
        "B_at_integer_vertices": dist(d_hf_ls[kind == "vertex"], "z_hf - z_landscape at vertices"),
        "B_off_vertex": dist(d_hf_ls[kind != "vertex"], "z_hf - z_landscape between vertices"),
        "B_steep": dist(d_hf_ls[kind == "steep"], "z_hf - z_landscape on steep ground"),
        "C_steep": dist(d_tif_ls[kind == "steep"], "z_tif - z_landscape on steep ground"),
        "near_tile_boundary_1m": {
            "n": int(near_seam.sum()),
            "A": dist(d_hf_tif[near_seam], "z_hf - z_tif within 1 m of a tile boundary"),
            "B": dist(d_hf_ls[near_seam], "z_hf - z_landscape within 1 m of a tile boundary")},
        "collision_vs_render": dist(z_col - z_ls, "z_landscape_collision - z_landscape"),
        "D_heightfield_vs_line_trace": dist(z_hf - z_tr, "z_hf - z_trace (what the pawn stands on)"),
        "D_trace_steep": dist((z_hf - z_tr)[kind == "steep"], "z_hf - z_trace on steep ground"),
        "trace_vs_landscape": dist(z_tr - z_ls, "z_trace - z_landscape"),
        "slope_buckets_B": {},
    }
    for lo, hi in [(0, 2), (2, 5), (5, 10), (10, 20), (20, 45), (45, 90)]:
        m = np.isfinite(slope) & (slope >= lo) & (slope < hi)
        rep["slope_buckets_B"]["%d-%d deg" % (lo, hi)] = dist(d_hf_ls[m], "%d-%d" % (lo, hi))
    k = np.nanargmax(np.abs(np.where(np.isfinite(d_hf_ls), d_hf_ls, 0.0)))
    rep["worst_B"] = {"x": float(xs[k]), "y": float(ys[k]), "z_hf": float(z_hf[k]),
                      "z_tif": float(z_tif[k]), "z_landscape": float(z_ls[k]),
                      "slope_deg": float(slope[k]), "dist_to_tile_boundary_m": float(dbound[k]),
                      "kind": str(kind[k])}
    json.dump(rep, open(args.out, "w"), indent=1)
    print(json.dumps(rep, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["emit", "join"], required=True)
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--terrain", default="C:/Users/Shadow/code/3duk/data/thanet/out/terrain")
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--n-steep", type=int, default=1000)
    ap.add_argument("--n-vertex", type=int, default=1000)
    ap.add_argument("--steep-min-deg", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=20260909)
    ap.add_argument("--points-csv", default="C:/Users/Shadow/code/3duk/projects/one/Saved/Diag/d2_points.csv")
    ap.add_argument("--npz", default="C:/Users/Shadow/code/3duk/projects/one/Saved/Diag/d2_points.npz")
    ap.add_argument("--probe-csv", default="C:/Users/Shadow/code/3duk/projects/one/Saved/Diag/d2_probe.csv")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    (emit if args.mode == "emit" else join)(args)


if __name__ == "__main__":
    main()
