"""Did the conform flatten the cliffs?  Independent slope statistics on both landscape products.

BRIEF 5 stage 1 requires slope_qa.max_deg >= 80 (cliffs intact).  Measured over kept cells only, the
steepest adjacent-post pair per tile (atan(|dz| / 1 m)), on the r16 the engine actually imported.
"""
import json, os, sys
import numpy as np

ROOT = "C:/Users/Shadow/code/3duk"
CFG = json.load(open(ROOT + "/sources/config/sites/thanet.json"))
NX, NY, RES = CFG["nx"], CFG["ny"], CFG["grid_res"]


def load(sub, i, j):
    p = "%s/data/thanet/out/unreal/%s/hm_x%d_y%d.r16" % (ROOT, sub, i, j)
    if not os.path.exists(p):
        return None, None
    a = ((np.fromfile(p, dtype="<u2").astype(np.float64) - 32768.0) / 128.0).reshape(RES, RES)
    c = "%s/data/thanet/out/unreal/%s/clip_x%d_y%d.r8" % (ROOT, sub, i, j)
    keep = np.fromfile(c, dtype=np.uint8).reshape(RES, RES) == 255 if os.path.exists(c) else np.ones((RES, RES), bool)
    return a, keep


def stats(sub):
    mx = 0.0
    at = None
    over45 = 0
    cells = 0
    for i in range(NX):
        for j in range(NY):
            a, keep = load(sub, i, j)
            if a is None:
                continue
            dx = np.abs(np.diff(a, axis=1))
            dy = np.abs(np.diff(a, axis=0))
            kx = keep[:, :-1] & keep[:, 1:]
            ky = keep[:-1, :] & keep[1:, :]
            s = max(float(dx[kx].max()) if kx.any() else 0.0, float(dy[ky].max()) if ky.any() else 0.0)
            d = np.degrees(np.arctan(s))
            if d > mx:
                mx = d
                at = [i, j]
            g0, g1 = np.gradient(a)
            slope = np.degrees(np.arctan(np.hypot(g1, g0)))
            over45 += int((slope[keep] > 45.0).sum())
            cells += int(keep.sum())
    return {"product": sub, "max_deg": round(mx, 3), "worst_tile": at,
            "cells_over_45deg": over45, "kept_cells": cells}


out = [stats("landscape"), stats("landscape_conformed")]
for r in out:
    print(json.dumps(r), flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
print("WROTE", sys.argv[1])
