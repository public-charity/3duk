#!/usr/bin/env python3.14
"""Emit per-tile semantic massing records (JSONL) for the Unity generator.

Deliberately semantic, not geometric: ~200 bytes per building, diffable and
version-controllable, and Unity can re-tune the art without re-running GDAL.
Geometry is emitted in LOCAL metres (x = E-E0, z = N-N0) ready for Unity.
"""
import json, os, pickle, hashlib
import numpy as np
from osgeo import ogr
ogr.UseExceptions()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG  = json.load(open(f"{ROOT}/sources/config/margate.json"))
LM   = json.load(open(f"{ROOT}/sources/config/landmarks.json"))
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
OUT = f"{ROOT}/data/out/massing"; os.makedirs(OUT, exist_ok=True)

feats = pickle.load(open(f"{ROOT}/data/interim/_feats.pkl","rb"))
keys  = np.load(f"{ROOT}/data/interim/_stats_keys.npy")
vals  = np.load(f"{ROOT}/data/interim/_stats_vals.npy")
S = {int(k): v for k, v in zip(keys, vals)}

# Margate's own vernacular, measured from its own LIDAR (fallback rung 6)
PRIOR = {"house":6.97,"residential":7.30,"yes":6.64,"semidetached_house":6.98,"retail":8.99,
         "terrace":8.13,"apartments":9.42,"garage":2.43,"detached":6.35,"shed":2.37,
         "garages":2.43,"commercial":7.02,"school":4.29,"industrial":5.75,"hospital":4.19,
         "bungalow":4.24,"roof":3.81}
FLAT = {"garage","garages","shed","roof","industrial","retail","commercial","supermarket"}

def tv(rec, key):
    ot = rec.get("other") or ""
    tok = f'"{key}"=>"'; i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i+len(tok)); return ot[i+len(tok):j]

def rings(geom):
    out = []
    for gi in range(geom.GetGeometryCount() if geom.GetGeometryName()=="MULTIPOLYGON" else 1):
        poly = geom.GetGeometryRef(gi) if geom.GetGeometryName()=="MULTIPOLYGON" else geom
        for ri in range(poly.GetGeometryCount()):
            r = poly.GetGeometryRef(ri)
            pts = [(round(r.GetX(n)-E0,3), round(r.GetY(n)-N0,3)) for n in range(r.GetPointCount())]
            if len(pts) >= 4: out.append({"hole": ri > 0, "pts": pts})
    return out

buckets, qa, nlm = {}, [], 0
for k, rec in enumerate(feats):
    if k not in S: continue
    p25, p50, p90, npx, d15, dmin = S[k]
    g = ogr.CreateGeometryFromWkb(rec["wkb"])
    x0,x1,y0,y1 = g.GetEnvelope(); cx, cy = (x0+x1)/2, (y0+y1)/2
    i, j = int((cx-E0)//T), int((cy-N0)//T)
    btype = rec.get("building") or "yes"
    name  = rec.get("name")
    lv    = tv(rec, "building:levels")
    try: levels = int(float(lv)) if lv else None
    except: levels = None

    # --- height fallback ladder; record which rung fired -------------------
    ht = tv(rec, "height")
    src, h = None, None
    if ht:
        try: h, src = float(str(ht).split()[0]), "osm_height"
        except: pass
    if h is None and npx >= 6:
        h, src = p50, "lidar_p50"
        if levels and abs(h - (3.16 + 1.84*levels)) > 4.0: src = "lidar_p50_disputed"
    elif h is None and npx >= 1:
        h, src = p50, "lidar_lowconf"
    if h is None and levels: h, src = 3.16 + 1.84*levels, "osm_levels"
    if h is None: h, src = PRIOR.get(btype, 6.6), "type_prior"

    roof = tv(rec, "roof:shape") or ("flat" if btype in FLAT else "gabled")
    if name in LM:                                   # hand override wins
        o = LM[name]; h = o.get("h_body", h); roof = o.get("roof", roof); src = "landmark_override"; nlm += 1
    if npx < 6 or (p90 - p50) > 8: qa.append({"osm_id": rec["osm_id"], "name": name,
                                              "px": int(npx), "p50": round(p50,1), "p90": round(p90,1)})

    buckets.setdefault((i,j), []).append({
        "id": rec["osm_id"], "name": name, "type": btype,
        "h": round(float(h),2), "ridge": round(float(max(p90,h)),2), "eaves": round(float(p25),2),
        "base_y": round(float(d15),2), "skirt": round(float(dmin-0.5),2),
        "levels": levels, "roof": roof, "src": src,
        "seed": int(hashlib.md5(str(rec["osm_id"]).encode()).hexdigest()[:8], 16),
        "rings": rings(g),
    })

n = 0
for (i,j), items in sorted(buckets.items()):
    with open(f"{OUT}/buildings_x{i}_y{j}.jsonl","w") as f:
        for b in items: f.write(json.dumps(b, separators=(",",":"))+"\n"); n += 1
json.dump(qa, open(f"{ROOT}/data/out/qa_height_outliers.json","w"), indent=1)
from collections import Counter
print(f"wrote {n} buildings across {len(buckets)} tiles -> {OUT}")
print(f"landmark overrides applied: {nlm}   QA flagged: {len(qa)}")
print("height source:", dict(Counter(b["src"] for v in buckets.values() for b in v)))
print("roof form   :", dict(Counter(b["roof"] for v in buckets.values() for b in v).most_common(6)))
