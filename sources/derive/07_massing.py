#!/usr/bin/env python3.14
"""Per-tile semantic massing records (JSONL), one per building footprint.

Deliberately semantic, not geometric: ~200 bytes per building, diffable and
version-controllable, so a consumer can re-tune its art without re-running GDAL.

Coordinates are CRS eastings/northings in metres -- no local origin offset and no
engine axis convention. A consumer that wants local coordinates subtracts the origin
from the manifest; sources/adapters/unity.py shows the conversion.

Every height carries `src` saying which rung of the fallback ladder produced it:
  osm_height          the building's own OSM height tag
  lidar_p50           LIDAR, enough samples to trust
  lidar_p50_disputed  LIDAR, but it disagrees with building:levels by more than dispute_m
  lidar_lowconf       LIDAR, too few samples to trust
  osm_levels          building:levels through the site's height_calib regression
  type_prior          no evidence at all -- a per-type guess, see tuning.json
  landmark_override   hand-authored in the site config
"""
import glob, json, os, sys, pickle, hashlib
import numpy as np
from osgeo import ogr
ogr.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
TUN = CFG["tuning"]["buildings"]
P   = lib.paths(CFG)
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
OUT = os.path.join(P["out"], "massing")
lib.mkdirs(OUT)

CAL_CFG = CFG["height_calib"]
LM      = CFG.get("landmarks", {})
PRIOR   = {k: v for k, v in TUN["type_priors_m"].items() if not k.startswith("_")}
PRIOR_D = TUN["type_prior_default_m"]
FLAT    = set(TUN["flat_roof_types"])
MINPX   = TUN["min_pixels"]
NX, NY  = CFG["nx"], CFG["ny"]

feats = pickle.load(open(os.path.join(P["interim"], "_feats.pkl"), "rb"))
keys  = np.load(os.path.join(P["interim"], "_stats_keys.npy"))
vals  = np.load(os.path.join(P["interim"], "_stats_vals.npy"))
S = {int(k): v for k, v in zip(keys, vals)}

def tv(rec, key):
    ot = rec.get("other") or ""
    tok = f'"{key}"=>"'; i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i+len(tok)); return ot[i+len(tok):j]

def levels_of(rec):
    lv = rec.get("levels") or tv(rec, "building:levels")
    try: return int(float(lv)) if lv else None
    except (TypeError, ValueError): return None

# ---- levels -> height calibration -----------------------------------------
# Storey height is a property of a town's building stock, not a constant. In "auto" mode
# the line is regressed here from this site's own buildings that carry both an OSM
# building:levels tag and a trustworthy LIDAR p50; the fitted line is what the ladder
# uses and what the manifest records. "fixed" mode uses the config's numbers. Either way
# the values in force are written out, so the config can never again claim one regression
# while the code applies another -- which is how the previous pipeline was found.
def fit_calibration():
    pairs = []
    for k, rec in enumerate(feats):
        if k not in S: continue
        p25, p50, p90, npx, d15, dmin = S[k]
        lv = levels_of(rec)
        if lv and 1 <= lv <= 30 and npx >= MINPX and tv(rec, "height") is None:
            pairs.append((lv, float(p50)))
    n_min = int(CAL_CFG.get("min_buildings", 30))
    if len(pairs) < n_min:
        return None, {"n": len(pairs), "reason": f"fewer than {n_min} buildings with both levels and LIDAR"}
    L = np.array([p[0] for p in pairs], float); Hv = np.array([p[1] for p in pairs], float)
    b, a = np.polyfit(L, Hv, 1)
    resid = Hv - (a + b * L)
    keep = np.abs(resid) <= max(2.0 * float(resid.std()), 2.0)     # one pass of outlier rejection
    if keep.sum() >= max(3, n_min // 2):
        b, a = np.polyfit(L[keep], Hv[keep], 1)
        resid = Hv[keep] - (a + b * L[keep])
    return ({"intercept": round(float(a), 3), "m_per_level": round(float(b), 3)},
            {"n": int(keep.sum()), "rejected": int((~keep).sum()),
             "rmse_m": round(float(np.sqrt((resid ** 2).mean())), 2)})

mode = CAL_CFG.get("mode", "fixed" if "intercept" in CAL_CFG else "auto")
fit, fit_info = fit_calibration() if mode == "auto" else (None, {"n": 0, "reason": "mode fixed"})
if fit:
    CAL = {**fit, "source": "fitted"}
elif "intercept" in CAL_CFG:
    CAL = {"intercept": CAL_CFG["intercept"], "m_per_level": CAL_CFG["m_per_level"], "source": "config"}
else:
    CAL = {**CAL_CFG["fallback"], "source": "fallback"}
    print(f"07: WARNING -- height_calib auto-fit not possible ({fit_info.get('reason')}); using the "
          f"fallback {CAL['intercept']} + {CAL['m_per_level']}*levels, which was NOT measured at "
          f"{CFG['site']}.", flush=True)
CAL["dispute_m"] = float(CAL_CFG.get("dispute_m", 4.0))
print(f"height calibration ({CAL['source']}): h = {CAL['intercept']} + {CAL['m_per_level']} * levels   {fit_info}")

def h_from_levels(levels):
    return CAL["intercept"] + CAL["m_per_level"] * levels

def rings(geom):
    """Exterior + hole rings as CRS coordinates, metres."""
    out = []
    for gi in range(geom.GetGeometryCount() if geom.GetGeometryName()=="MULTIPOLYGON" else 1):
        poly = geom.GetGeometryRef(gi) if geom.GetGeometryName()=="MULTIPOLYGON" else geom
        for ri in range(poly.GetGeometryCount()):
            r = poly.GetGeometryRef(ri)
            pts = [(round(r.GetX(n), 3), round(r.GetY(n), 3)) for n in range(r.GetPointCount())]
            if len(pts) >= 4: out.append({"hole": ri > 0, "pts": pts})
    return out

def r2(v):
    return None if v is None else round(float(v), 2)

buckets, qa, nlm, no_lidar, outside = {}, [], 0, 0, 0
for k, rec in enumerate(feats):
    g = ogr.CreateGeometryFromWkb(rec["wkb"])
    x0,x1,y0,y1 = g.GetEnvelope(); cx, cy = (x0+x1)/2, (y0+y1)/2
    i, j = int((cx-E0)//T), int((cy-N0)//T)
    if not (0 <= i < NX and 0 <= j < NY):
        outside += 1                  # the Overpass bbox is generous; the grid is the model
        continue
    if k in S:
        p25, p50, p90, npx, d15, dmin = S[k]
    else:
        # No LIDAR sample inside the footprint at all -- outside coverage, or a sliver.
        # The old code dropped these buildings from the model without a word, which on
        # a site with partial LIDAR silently deletes whole streets. Emit them with the
        # ground unknown and let `src` say how the height was reached.
        p25 = p50 = p90 = d15 = dmin = None
        npx = 0
        no_lidar += 1
    btype  = rec.get("building") or "yes"
    name   = rec.get("name")
    levels = levels_of(rec)

    # --- height fallback ladder; record which rung fired -------------------
    ht = tv(rec, "height")
    src, h = None, None
    if ht:
        try: h, src = float(str(ht).split()[0]), "osm_height"
        except: pass
    if h is None and npx >= MINPX:
        h, src = p50, "lidar_p50"
        if levels and abs(h - h_from_levels(levels)) > CAL["dispute_m"]: src = "lidar_p50_disputed"
    elif h is None and npx >= 1:
        h, src = p50, "lidar_lowconf"
    if h is None and levels: h, src = h_from_levels(levels), "osm_levels"
    if h is None: h, src = PRIOR.get(btype, PRIOR_D), "type_prior"

    roof = tv(rec, "roof:shape") or ("flat" if btype in FLAT else TUN["default_roof"])
    if name in LM:                                   # hand override wins
        o = LM[name]; h = o.get("h_body", h); roof = o.get("roof", roof); src = "landmark_override"; nlm += 1
    if npx < MINPX or (p90 is not None and (p90 - p50) > TUN["qa_ridge_spread_m"]):
        qa.append({"osm_id": rec["osm_id"], "name": name, "px": int(npx),
                   "p50": None if p50 is None else round(p50, 1),
                   "p90": None if p90 is None else round(p90, 1)})

    buckets.setdefault((i,j), []).append({
        "id": rec["osm_id"], "name": name, "type": btype,
        "h": r2(h),
        "ridge": r2(max(p90, h)) if p90 is not None else r2(h),
        "eaves": r2(p25),
        "base_z": r2(d15),
        "skirt": r2(dmin - TUN["skirt_below_min_m"]) if dmin is not None else None,
        "lidar_px": int(npx),
        "levels": levels, "roof": roof, "src": src,
        "seed": int(hashlib.md5(str(rec["osm_id"]).encode()).hexdigest()[:8], 16),
        "rings": rings(g),
    })

for old in glob.glob(os.path.join(OUT, "buildings_*.jsonl")):   # no stale tiles from a previous grid
    os.remove(old)
n = 0
for (i,j), items in sorted(buckets.items()):
    with open(os.path.join(OUT, f"buildings_x{i}_y{j}.jsonl"), "w") as f:
        for b in items: f.write(json.dumps(b, separators=(",",":"))+"\n"); n += 1

from collections import Counter
by_src = Counter(b["src"] for v in buckets.values() for b in v)
json.dump({"site": CFG["site"], "crs": CFG["crs"], "coordinates": "CRS eastings/northings, metres",
           "origin": CFG["origin"], "tile_m": CFG["tile_m"],
           "height_calib": CAL, "height_calib_fit": fit_info,
           "buildings": n, "tiles": len(buckets), "outside_grid": outside,
           "by_height_source": dict(by_src), "landmark_overrides": nlm,
           "buildings_without_lidar": no_lidar,
           "qa_flagged": len(qa)},
          open(os.path.join(OUT, "massing_manifest.json"), "w"), indent=1)
json.dump(qa, open(os.path.join(P["out"], "qa_height_outliers.json"), "w"), indent=1)

print(f"wrote {n} buildings across {len(buckets)} tiles -> {OUT}")
print(f"landmark overrides applied: {nlm}   QA flagged: {len(qa)}")
print("height source:", dict(by_src))
print("roof form   :", dict(Counter(b["roof"] for v in buckets.values() for b in v).most_common(6)))

# type_prior means "no evidence at all". A few is normal; a lot means this site is being
# described by another site's vernacular, which is exactly the failure worth shouting about.
if n and by_src.get("type_prior", 0) / n > 0.05:
    pct = 100 * by_src["type_prior"] / n
    print(f"07: WARNING -- {pct:.1f}% of buildings fell back to type_priors_m, which were "
          f"measured at '{CFG['tuning']['buildings']['type_priors_m'].get('_measured_at','?')}'. "
          f"Re-measure them for {CFG['site']} before trusting this massing.")
if nlm < sum(1 for k in LM if not k.startswith("_")):
    print(f"07: NOTE -- {sum(1 for k in LM if not k.startswith('_')) - nlm} landmark override(s) "
          f"did not match any building name; an OSM rename silently drops them.")
