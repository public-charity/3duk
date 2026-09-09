"""Did conforming the landscape to the roads bury or strand the massing?

Every building's footprint vertices are sampled on both landscape products.  A building's base sits at
`skirt` (its lowest point) and its solid starts there, so ground ABOVE `base_z` at a footprint vertex
is the box being swallowed, and ground far BELOW `skirt` is the box on stilts.
"""
import glob, json, os, sys
import numpy as np

ROOT = "C:/Users/Shadow/code/3duk"
CFG = json.load(open(ROOT + "/sources/config/sites/thanet.json"))
NX, NY, T, RES = CFG["nx"], CFG["ny"], CFG["tile_m"], CFG["grid_res"]
W, H = NX * T + 1, NY * T + 1


def mosaic(sub):
    m = np.full((H, W), np.nan, np.float32)
    for i in range(NX):
        for j in range(NY):
            p = "%s/data/thanet/out/unreal/%s/hm_x%d_y%d.r16" % (ROOT, sub, i, j)
            if not os.path.exists(p):
                continue
            a = ((np.fromfile(p, dtype="<u2").astype(np.float32) - 32768.0) / 128.0).reshape(RES, RES)
            c = "%s/data/thanet/out/unreal/%s/clip_x%d_y%d.r8" % (ROOT, sub, i, j)
            if os.path.exists(c):
                a = np.where(np.fromfile(c, dtype=np.uint8).reshape(RES, RES) == 0, np.nan, a)
            m[(NY - 1 - j) * T:(NY - 1 - j) * T + RES, i * T:i * T + RES] = a
    return m


def sample_tri(m, x, y):
    col = np.asarray(x, float)
    row = (NY * T) - np.asarray(y, float)
    c0 = np.clip(np.floor(col).astype(np.int64), 0, W - 2)
    r0 = np.clip(np.floor(row).astype(np.int64), 0, H - 2)
    tx = col - np.floor(col)
    ty = row - np.floor(row)
    a = m[r0, c0]
    b = m[r0, c0 + 1]
    c = m[r0 + 1, c0]
    d = m[r0 + 1, c0 + 1]
    return np.where(tx < ty, a * (1 - ty) + d * tx + c * (ty - tx), a * (1 - tx) + b * (tx - ty) + d * ty)


SUR = mosaic("landscape")
CON = mosaic("landscape_conformed")

xs, ys, base, skirt = [], [], [], []
for p in sorted(glob.glob(ROOT + "/data/thanet/out/unreal/massing/buildings_*.jsonl")):
    with open(p) as fh:
        for line in fh:
            b = json.loads(line)
            for ring in b["rings"]:
                if ring.get("hole"):
                    continue
                for (x, y) in ring["pts"][:-1]:
                    xs.append(x)
                    ys.append(y)
                    base.append(b["base_z"])
                    skirt.append(b["skirt"])
x = np.array(xs)
y = np.array(ys)
base = np.array(base)
skirt = np.array(skirt)
zs = sample_tri(SUR, x, y)
zc = sample_tri(CON, x, y)
ok = np.isfinite(zs) & np.isfinite(zc)
print("%d footprint vertices, %d with ground on both products" % (x.size, ok.sum()), flush=True)
moved = np.abs(zc - zs) > 1e-9
print("vertices whose ground the conform moved: %d (%.3f%%), max |move| %.3f m"
      % (moved.sum(), 100.0 * moved.mean(), float(np.abs(zc - zs)[ok].max())), flush=True)


def report(z, label):
    bury = (z - base) > 0.5
    stilt = (skirt - z) > 0.5
    print("  %-10s ground above base_z by >0.5 m: %d vertices (%.3f%%), worst %.2f m | "
          "ground below skirt by >0.5 m: %d (%.3f%%), worst %.2f m"
          % (label, (bury & ok).sum(), 100.0 * (bury & ok).mean(), float((z - base)[ok].max()),
             (stilt & ok).sum(), 100.0 * (stilt & ok).mean(), float((skirt - z)[ok].max())), flush=True)


report(zs, "survey")
report(zc, "conformed")
json.dump({"vertices": int(x.size), "with_ground": int(ok.sum()), "moved": int(moved.sum()),
           "max_move_m": float(np.abs(zc - zs)[ok].max()),
           "buried_survey": int((((zs - base) > 0.5) & ok).sum()),
           "buried_conformed": int((((zc - base) > 0.5) & ok).sum()),
           "stilts_survey": int((((skirt - zs) > 0.5) & ok).sum()),
           "stilts_conformed": int((((skirt - zc) > 0.5) & ok).sum())},
          open(sys.argv[1], "w"), indent=1)
print("WROTE", sys.argv[1])
