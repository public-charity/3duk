"""Probe points for the in-engine verification.

Two sets, one CSV:
  kind=vertex   integer-metre landscape posts spread over the isle -> D2: engine height vs the r16 post
  kind=road     road-centreline stations from my own random spline sample -> D3 in the engine
Columns: x,y,kind,z_expect,z_road  (z_expect = my conformed sampler; z_road = built road surface, NaN for vertex)
"""
import glob, json, os, random, sys
import numpy as np

ROOT = "C:/Users/Shadow/code/3duk"
sys.path.insert(0, ROOT + "/projects/one/Tools/blender")
from streetscape import io_json, schema as S            # noqa: E402
from streetscape.spline import Spline                    # noqa: E402
from streetscape.terrain import Heightfield              # noqa: E402

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
    c0 = np.floor(col).astype(np.int64)
    r0 = np.floor(row).astype(np.int64)
    tx = col - c0
    ty = row - r0
    c0 = np.clip(c0, 0, W - 2)
    r0 = np.clip(r0, 0, H - 2)
    a = m[r0, c0]
    b = m[r0, c0 + 1]
    c = m[r0 + 1, c0]
    d = m[r0 + 1, c0 + 1]
    return np.where(tx < ty, a * (1 - ty) + d * tx + c * (ty - tx), a * (1 - tx) + b * (tx - ty) + d * ty)


CONF = mosaic("landscape_conformed")
rng = random.Random(90909)
out = []

# ---- vertex set: integer-metre posts with a value, spread over the whole grid ----------------
tries = 0
while len([r for r in out if r[2] == "vertex"]) < 300 and tries < 200000:
    tries += 1
    x = rng.randrange(0, W - 1)
    y = rng.randrange(0, H - 1)
    z = CONF[(NY * T) - y, x]
    if np.isfinite(z):
        out.append((float(x), float(y), "vertex", float(z), float("nan")))

# ---- road set: centreline stations from my own random spline sample --------------------------
docs = sorted(glob.glob(ROOT + "/data/thanet/out/unreal/streetscape/site_*.json"))
terrain = Heightfield.from_landscape_dir(ROOT + "/data/thanet/out/unreal/landscape")
index = []
for p in docs:
    d = json.load(open(p))
    for sp in d["splines"]:
        if sp["profile_ids"].get("road") and sp["source"]["layer"] == "roads":
            index.append((p, sp["id"]))
pick = rng.sample(index, 60)
by_doc = {}
for p, sid in pick:
    by_doc.setdefault(p, []).append(sid)
n_road = 0
for p in sorted(by_doc):
    site = io_json.load_site(p)
    defs = {sd.id: sd for sd in site.splines}
    for sid in by_doc[p]:
        try:
            sp = Spline(defs[sid], site, terrain)
        except Exception:
            continue
        step = max(1, sp.n // 12)
        for i in range(0, sp.n, step):
            x = float(sp.frames.p[i, 0])
            y = float(sp.frames.p[i, 1])
            zr = float(sp.frames.p[i, 2])           # centreline surface (camber 0 at d = 0)
            ze = float(sample_tri(CONF, np.array([x]), np.array([y]))[0])
            if np.isfinite(ze):
                out.append((x, y, "road", ze, zr))
                n_road += 1

with open(sys.argv[1], "w") as fh:
    fh.write("x,y,kind,z_expect,z_road\n")
    for r in out:
        fh.write("%.4f,%.4f,%s,%.6f,%.6f\n" % r)
print("wrote %d points (%d vertex, %d road) -> %s" % (len(out), len(out) - n_road, n_road, sys.argv[1]))
