"""Independent D1 audit: do neighbouring tiles agree on the samples they share?

Written from scratch for the verification pass. Three products are checked:
  terrain/dtm_*.tif                (step 05, the survey)
  unreal/landscape/hm_*.r16        (the adapter's unconformed landscape)
  unreal/landscape_conformed/hm_*.r16
Geometry: grid_res = tile_m/px + 1, north-up, row 0 = north, col 0 = west.
  tile (i,j) east column  (col -1) IS tile (i+1,j) west column (col 0)
  tile (i,j) north row    (row  0) IS tile (i,j+1) south row  (row -1)
"""
import json, os, sys
import numpy as np

ROOT = "C:/Users/Shadow/code/3duk"
CFG = json.load(open(f"{ROOT}/sources/config/sites/thanet.json"))
NX, NY, RES = CFG["nx"], CFG["ny"], CFG["grid_res"]


def load_tif(i, j):
    from osgeo import gdal
    p = f"{ROOT}/data/thanet/out/terrain/dtm_x{i}_y{j}.tif"
    if not os.path.exists(p):
        return None, None
    d = gdal.Open(p); b = d.GetRasterBand(1)
    a = b.ReadAsArray().astype(np.float64)
    nd = b.GetNoDataValue()
    bad = np.zeros(a.shape, bool)
    if nd is not None:
        bad |= np.isclose(a, nd)
    bad |= ~np.isfinite(a) | (a < -1e30)
    return a, bad


def load_r16(sub, i, j):
    p = f"{ROOT}/data/thanet/out/unreal/{sub}/hm_x{i}_y{j}.r16"
    if not os.path.exists(p):
        return None, None
    a = np.fromfile(p, dtype="<u2").astype(np.int64).reshape(RES, RES)
    c = f"{ROOT}/data/thanet/out/unreal/{sub}/clip_x{i}_y{j}.r8"
    m = np.fromfile(c, dtype=np.uint8).reshape(RES, RES) if os.path.exists(c) else np.full((RES, RES), 255, np.uint8)
    return a, (m == 0)          # bad == clipped/nodata


def audit(loader, scale, label):
    tiles, bads = {}, {}
    for i in range(NX):
        for j in range(NY):
            a, b = loader(i, j)
            if a is not None:
                tiles[(i, j)] = a; bads[(i, j)] = b
    pairs = pairs_bad = 0
    n_cmp = n_cmp_vis = n_bad = n_bad_vis = 0
    worst = 0.0; worst_at = None; worst_vis = 0.0; worst_vis_at = None
    tiles_bad = set()
    for (i, j) in sorted(tiles):
        for (di, dj) in ((1, 0), (0, 1)):
            n = (i + di, j + dj)
            if n not in tiles:
                continue
            pairs += 1
            if di:
                x, y = tiles[(i, j)][:, -1], tiles[n][:, 0]
                bx, by = bads[(i, j)][:, -1], bads[n][:, 0]
            else:
                x, y = tiles[(i, j)][0, :], tiles[n][-1, :]
                bx, by = bads[(i, j)][0, :], bads[n][-1, :]
            ok = ~(bx | by)                       # comparable: both sides carry a value
            d = np.abs(x - y) * scale
            n_cmp += x.size
            n_cmp_vis += int(ok.sum())
            k = d > 0
            n_bad += int(k.sum())
            kv = k & ok
            n_bad_vis += int(kv.sum())
            if k.any():
                pairs_bad += 1
                tiles_bad.add((i, j)); tiles_bad.add(n)
                if d[k].max() > worst:
                    worst = float(d[k].max()); worst_at = [[i, j], list(n), int(np.argmax(d))]
            if kv.any() and d[kv].max() > worst_vis:
                worst_vis = float(d[kv].max()); worst_vis_at = [[i, j], list(n), int(np.argmax(np.where(kv, d, -1)))]
    r = dict(product=label, tiles=len(tiles), pairs=pairs, pairs_disagreeing=pairs_bad,
             tiles_touching_disagreement=len(tiles_bad),
             samples_compared_all=n_cmp, samples_disagreeing_all=n_bad, max_m_all=worst, max_at_all=worst_at,
             samples_compared_visible=n_cmp_vis, samples_disagreeing_visible=n_bad_vis,
             max_m_visible=worst_vis, max_at_visible=worst_vis_at)
    print(json.dumps(r, indent=1), flush=True)
    return r


out = {}
out["terrain_geotiff"] = audit(load_tif, 1.0, "terrain/dtm_*.tif")
out["landscape_r16"] = audit(lambda i, j: load_r16("landscape", i, j), 1.0 / 128.0, "unreal/landscape/hm_*.r16")
out["conformed_r16"] = audit(lambda i, j: load_r16("landscape_conformed", i, j), 1.0 / 128.0, "unreal/landscape_conformed/hm_*.r16")
json.dump(out, open(sys.argv[1], "w"), indent=1)
print("WROTE", sys.argv[1])
