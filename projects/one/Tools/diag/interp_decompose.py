#!/usr/bin/env python3
"""D2 -- the interpolation term, without the engine.

UStreetHeightfieldTerrain defaults to BILINEAR over the 1 m quad (the numpy contract,
DESIGN.md 8); an ALandscape is a triangle mesh and interpolates over the quad's two
triangles (EStreetHeightSampling::LandscapeTriangulated,
Plugins/Streetscape/Source/Streetscape/Private/StreetTerrainSource.cpp:169-177).

For a quad (A = z00, B = z10, C = z01, D = z11) with twist T = A + D - B - C:
    bilinear    = A + (B-A)tx + (C-A)ty + T*tx*ty
    triangulated(tx < ty) = A + (D-C)tx + (C-A)ty        -> bilinear - tri = -T*tx*(1-ty)
    triangulated(tx >= ty)= A + (B-A)tx + (D-B)ty        -> bilinear - tri = -T*ty*(1-tx)
so |bilinear - triangulated| <= |T|/4, attained at tx = ty = 1/2.

This computes the site-wide |T|/4 distribution from the r16 tiles and, for a point set,
both interpolations at the sampled positions.
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "blender")))
from streetscape.terrain import Heightfield   # noqa: E402


def both_interps(hf: Heightfield, x, y):
    """Bilinear and landscape-triangulated values at (x, y); NaN off coverage."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    bil = np.full(x.shape, np.nan)
    tri = np.full(x.shape, np.nan)
    twist = np.full(x.shape, np.nan)
    r1 = hf.res - 1
    ti = np.floor(x / hf.tile_m).astype(np.int64)
    tj = np.floor(y / hf.tile_m).astype(np.int64)
    keys = np.stack([ti, tj], axis=-1).reshape(-1, 2)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(x.shape)
    for u in range(len(uniq)):
        key = (int(uniq[u, 0]), int(uniq[u, 1]))
        T = hf.tiles.get(key)
        if T is None:
            continue
        sel = inv == u
        cx = np.clip((x[sel] - key[0] * hf.tile_m) / hf.px_m, 0.0, float(r1))
        ry = np.clip(((key[1] + 1) * hf.tile_m - y[sel]) / hf.px_m, 0.0, float(r1))
        x0 = np.minimum(np.floor(cx).astype(np.int64), r1 - 1)
        y0 = np.minimum(np.floor(ry).astype(np.int64), r1 - 1)
        tx = cx - x0
        ty = ry - y0
        A = T[y0, x0].astype(np.float64)          # (row y0, col x0)
        B = T[y0, x0 + 1].astype(np.float64)
        C = T[y0 + 1, x0].astype(np.float64)
        D = T[y0 + 1, x0 + 1].astype(np.float64)
        bil[sel] = (A * (1 - tx) + B * tx) * (1 - ty) + (C * (1 - tx) + D * tx) * ty
        tri[sel] = np.where(tx < ty,
                            A * (1 - ty) + D * tx + C * (ty - tx),
                            A * (1 - tx) + B * (tx - ty) + D * ty)
        twist[sel] = A + D - B - C
    return bil, tri, twist


def dist(v, name):
    v = np.asarray(v, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"name": name, "n": 0}
    a = np.abs(v)
    return {"name": name, "n": int(v.size), "max": float(a.max()),
            "p999": float(np.percentile(a, 99.9)), "p99": float(np.percentile(a, 99)),
            "p95": float(np.percentile(a, 95)), "p50": float(np.percentile(a, 50)),
            "rms": float(np.sqrt((v ** 2).mean()))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--npz", default="C:/Users/Shadow/code/3duk/projects/one/Saved/Diag/d2_points.npz")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hf = Heightfield.from_landscape_dir(args.landscape)
    rep = {"tiles": len(hf.tiles)}

    # site-wide bound: |twist|/4 over every 1 m quad of every tile
    allq = []
    worst = (0.0, None)
    per_tile = {}
    for key, T in hf.tiles.items():
        Z = T.astype(np.float64)
        W = Z[:-1, :-1] + Z[1:, 1:] - Z[:-1, 1:] - Z[1:, :-1]
        b = np.abs(W) / 4.0
        b = b[np.isfinite(b)]
        if b.size == 0:
            continue
        per_tile["%d,%d" % key] = float(b.max())
        if b.max() > worst[0]:
            worst = (float(b.max()), key)
        allq.append(b.astype(np.float32))
    allq = np.concatenate(allq)
    rep["quad_bound_m"] = {"quads": int(allq.size),
                           "max": float(allq.max()),
                           "p99999": float(np.percentile(allq, 99.999)),
                           "p9999": float(np.percentile(allq, 99.99)),
                           "p999": float(np.percentile(allq, 99.9)),
                           "p99": float(np.percentile(allq, 99)),
                           "p50": float(np.percentile(allq, 50)),
                           "quads_over_0_10m": int((allq > 0.10).sum()),
                           "quads_over_0_25m": int((allq > 0.25).sum()),
                           "quads_over_0_50m": int((allq > 0.50).sum()),
                           "worst_tile": list(worst[1]) if worst[1] else None}
    rep["quad_bound_note"] = ("|bilinear - landscape_triangulated| <= |twist|/4 on each 1 m quad; "
                              "the bound is attained at the quad centre.")

    if os.path.isfile(args.npz):
        z = np.load(args.npz, allow_pickle=False)
        xs, ys, slope, kind = z["x"], z["y"], z["slope"], z["kind"]
        bil, tri, tw = both_interps(hf, xs, ys)
        d = bil - tri
        rep["points"] = {"n": int(len(xs)),
                         "bilinear_minus_triangulated": dist(d, "all points"),
                         "steep_only": dist(d[kind == "steep"], "slope >= 20 deg"),
                         "scatter_only": dist(d[kind == "scatter"], "uniform scatter"),
                         "vertex_only": dist(d[kind == "vertex"], "integer-metre vertices")}
        rep["points"]["by_slope"] = {}
        for lo, hi in [(0, 2), (2, 5), (5, 10), (10, 20), (20, 45), (45, 90)]:
            m = np.isfinite(slope) & (slope >= lo) & (slope < hi)
            rep["points"]["by_slope"]["%d-%d deg" % (lo, hi)] = dist(d[m], "%d-%d" % (lo, hi))
        k = int(np.nanargmax(np.abs(np.where(np.isfinite(d), d, 0.0))))
        rep["points"]["worst"] = {"x": float(xs[k]), "y": float(ys[k]), "bilinear": float(bil[k]),
                                  "triangulated": float(tri[k]), "twist": float(tw[k]),
                                  "slope_deg": float(slope[k]), "kind": str(kind[k])}
    json.dump(rep, open(args.out, "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
