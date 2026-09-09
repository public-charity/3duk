"""Independent D3: does the landscape stand above the built road surface?

My own sample of splines, my own mosaic reader and my own samplers.  The ROAD is built with the
project's geometry core from the SURVEY landscape (../landscape), which is exactly what the plugin
does in the level (UStreetHeightfieldTerrain::ResolvedDir -> DataDir/landscape); the LANDSCAPE it is
measured against is the conformed product the level actually imported.

clearance(x, y) = z_landscape(x, y) - z_road_surface(x, y); positive = terrain erupts through the road.
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
    """(H, W) float32 of local-metre samples, NaN where the clip mask says nothing is there.
    Row 0 is the NORTH edge (local y = NY*T); column 0 is local x = 0."""
    m = np.full((H, W), np.nan, np.float32)
    n = 0
    for i in range(NX):
        for j in range(NY):
            p = "%s/data/thanet/out/unreal/%s/hm_x%d_y%d.r16" % (ROOT, sub, i, j)
            if not os.path.exists(p):
                continue
            a = (np.fromfile(p, dtype="<u2").astype(np.float32) - 32768.0) / 128.0
            a = a.reshape(RES, RES)
            c = "%s/data/thanet/out/unreal/%s/clip_x%d_y%d.r8" % (ROOT, sub, i, j)
            if os.path.exists(c):
                a = np.where(np.fromfile(c, dtype=np.uint8).reshape(RES, RES) == 0, np.nan, a)
            r0 = (NY - 1 - j) * T                       # mosaic row of this tile's NORTH edge
            m[r0:r0 + RES, i * T:i * T + RES] = a
            n += 1
    print("mosaic %s: %d tiles, %s" % (sub, n, m.shape), flush=True)
    return m


def sample(m, x, y, rule):
    """Bilinear or landscape-triangulated between posts at integer metres. NaN outside / on a NaN post."""
    col = np.asarray(x, float)
    row = (NY * T) - np.asarray(y, float)               # row grows south
    c0 = np.floor(col)
    r0 = np.floor(row)
    tx = col - c0
    ty = row - r0
    c0 = c0.astype(np.int64)
    r0 = r0.astype(np.int64)
    ok = (c0 >= 0) & (r0 >= 0) & (c0 <= W - 2) & (r0 <= H - 2)
    c0 = np.clip(c0, 0, W - 2)
    r0 = np.clip(r0, 0, H - 2)
    a = m[r0, c0]
    b = m[r0, c0 + 1]
    c = m[r0 + 1, c0]
    d = m[r0 + 1, c0 + 1]
    if rule == "tri":
        z = np.where(tx < ty, a * (1 - ty) + d * tx + c * (ty - tx), a * (1 - tx) + b * (tx - ty) + d * ty)
    else:
        z = (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
    return np.where(ok, z, np.nan)


CONF = mosaic("landscape_conformed")

SITE_DIR = ROOT + "/data/thanet/out/unreal/streetscape"
docs = sorted(glob.glob(SITE_DIR + "/site_*.json"))
terrain = Heightfield.from_landscape_dir(ROOT + "/data/thanet/out/unreal/landscape")

SEED = int(os.environ.get("VFY_SEED", "424242"))
N_WANT = int(os.environ.get("VFY_N", "250"))
rng = random.Random(SEED)
index = []
for p in docs:
    d = json.load(open(p))
    for k, sp in enumerate(d["splines"]):
        if sp["profile_ids"].get("road"):
            index.append((p, k, sp["id"], sp["source"]["layer"], sp["source"].get("cls")))
print("%d splines with a road profile in %d documents" % (len(index), len(docs)), flush=True)
pick = rng.sample(index, N_WANT)
by_doc = {}
for p, k, sid, layer, cls in pick:
    by_doc.setdefault(p, []).append((k, sid, layer, cls))

LAT = 0.25            # lateral sample step across the carriageway, metres
rows = []
built = 0
skipped = 0
for p in sorted(by_doc):
    site = io_json.load_site(p)
    defs = {sd.id: sd for sd in site.splines}
    for (k, sid, layer, cls) in by_doc[p]:
        sd = defs.get(sid)
        if sd is None:
            skipped += 1
            continue
        try:
            sp = Spline(sd, site, terrain)
        except Exception as e:
            skipped += 1
            print("  skip %s: %s" % (sid, e), flush=True)
            continue
        eL, eR = sp.edge_offset(S.LEFT), sp.edge_offset(S.RIGHT)
        wmax = float((eL + eR).max())
        K = max(5, int(np.ceil(wmax / LAT)) + 1)
        f = np.linspace(0.0, 1.0, K)
        D = -eR[:, None] + (eL + eR)[:, None] * f[None, :]        # (N, K) signed lateral
        Hh = sp.surface_h(D)                                       # camber height about z_ref
        F = sp.frames
        px = F.p[:, 0][:, None] + D * F.n[:, 0][:, None] + Hh * F.b[:, 0][:, None]
        py = F.p[:, 1][:, None] + D * F.n[:, 1][:, None] + Hh * F.b[:, 1][:, None]
        pz = F.p[:, 2][:, None] + D * F.n[:, 2][:, None] + Hh * F.b[:, 2][:, None]
        for rule in ("bi", "tri"):
            zl = sample(CONF, px.ravel(), py.ravel(), rule).reshape(px.shape)
            cl = zl - pz                                            # + = terrain above the road
            good = np.isfinite(cl)
            if not good.any():
                continue
            per_station_max = np.where(good, cl, -np.inf).max(axis=1)
            valid = np.isfinite(per_station_max)
            if not valid.any():
                continue
            rows.append(dict(id=sid, layer=layer, cls=cls, rule=rule, L=sp.length,
                             n_station=int(valid.sum()), pen=per_station_max[valid], s=sp.s[valid]))
        built += 1
print("built %d splines, skipped %d" % (built, skipped), flush=True)


def summarise(rule):
    R = [r for r in rows if r["rule"] == rule]
    pen = np.concatenate([r["pen"] for r in R])
    n = pen.size
    hit = pen > 0
    km = 0.0
    km_pen = 0.0
    for r in R:
        s = r["s"]
        if s.size < 2:
            continue
        wgt = np.gradient(s)
        km += wgt.sum() / 1000.0
        km_pen += wgt[r["pen"] > 0].sum() / 1000.0
    out = dict(rule=rule, splines=len(R), stations=int(n), km=km,
               stations_penetrated=int(hit.sum()), fraction=float(hit.mean()), km_penetrated=km_pen,
               max_m=float(pen.max()), p99_m=float(np.percentile(pen, 99)),
               p95_m=float(np.percentile(pen, 95)), p50_m=float(np.percentile(pen, 50)),
               min_clearance_m=float(-pen.max()), clearance_p50_m=float(np.percentile(-pen, 50)))
    if hit.any():
        pp = pen[hit]
        out["pen_p50_m"] = float(np.percentile(pp, 50))
        out["pen_p95_m"] = float(np.percentile(pp, 95))
        worst = max(R, key=lambda r: r["pen"].max())
        out["worst_spline"] = dict(id=worst["id"], layer=worst["layer"], cls=worst["cls"],
                                   max_m=float(worst["pen"].max()))
    print(json.dumps(out, indent=1), flush=True)
    return out


res = dict(seed=SEED, n_requested=N_WANT, built=built, skipped=skipped, lateral_step_m=LAT,
           by_rule=dict((r, summarise(r)) for r in ("bi", "tri")))
json.dump(res, open(sys.argv[1], "w"), indent=1)
print("WROTE", sys.argv[1])
