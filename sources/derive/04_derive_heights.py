#!/usr/bin/env python3.14
"""Derive a real height for every building footprint from LIDAR.

nDSM = DSM(first return) - DTM, sampled inside each OSM footprint.
Uses p50 as the wall/body height and p90 as the ridge: p99/max chase chimneys
and aerials, mean is dragged down by roof pitch. One ID-raster + sorted
groupby does all buildings at once instead of per-polygon rasterisation.
"""
import json, os, sys, math, hashlib
import numpy as np
from osgeo import gdal, ogr, osr
gdal.UseExceptions(); ogr.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
TUN = CFG["tuning"]["buildings"]
P   = lib.paths(CFG)
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]

dtm_ds = gdal.Open(os.path.join(P["interim"], "dtm.vrt"))
dsm_ds = gdal.Open(os.path.join(P["interim"], "dsm.vrt"))
gt = dtm_ds.GetGeoTransform(); W, H = dtm_ds.RasterXSize, dtm_ds.RasterYSize
dtm = dtm_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
dsm = dsm_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
bad = ~np.isfinite(dtm) | ~np.isfinite(dsm) | (dtm < -1e30) | (dsm < -1e30)
ndsm = np.where(bad, np.nan, dsm - dtm)
print(f"grid {W}x{H}  nodata {100*bad.mean():.2f}%", flush=True)

# ---- collect footprints -------------------------------------------------
src = ogr.Open(P["gpkg"])
lyr = src.GetLayer("multipolygons")
lyr.SetAttributeFilter("building IS NOT NULL AND building != 'no'")
feats = []
for f in lyr:
    g = f.GetGeometryRef()
    if g is None or g.IsEmpty(): continue
    feats.append({
        "osm_id": f.GetField("osm_way_id") or f.GetField("osm_id"),
        "building": f.GetField("building"), "name": f.GetField("name"),
        "levels": f.GetField("building:levels") if "building:levels" in [f.GetFieldDefnRef(i).GetName() for i in range(f.GetFieldCount())] else None,
        "other": f.GetField("other_tags"),
        "wkb": g.ExportToWkb(),
    })
print(f"footprints: {len(feats)}", flush=True)

def tagval(rec, key):
    if rec.get("levels") and key == "building:levels": return rec["levels"]
    ot = rec.get("other") or ""
    tok = f'"{key}"=>"'
    i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i+len(tok))
    return ot[i+len(tok):j]

# Erode by half a pixel so a footprint does not sample its neighbours across a shared
# wall. Derived from the raster, never assumed: at 2 m or 50 cm this must change with it.
PX_W, PX_H = lib.pixel_size(gt)
EROSION = min(PX_W, PX_H) / 2.0

# ---- rasterise all footprints into one ID raster ------------------------
mem = ogr.GetDriverByName("Memory").CreateDataSource("m")
srs = osr.SpatialReference(); srs.ImportFromEPSG(lib.epsg(CFG))
ml = mem.CreateLayer("b", srs, ogr.wkbMultiPolygon)
ml.CreateField(ogr.FieldDefn("idx", ogr.OFTInteger))
for k, rec in enumerate(feats):
    g = ogr.CreateGeometryFromWkb(rec["wkb"])
    e = g.Buffer(-EROSION)                   # half a pixel, whatever the pixel is
    if e is None or e.IsEmpty(): e = g       # slivers/garages collapse -> keep original
    ft = ogr.Feature(ml.GetLayerDefn()); ft.SetGeometry(e); ft.SetField("idx", k+1)
    ml.CreateFeature(ft)

drv = gdal.GetDriverByName("MEM")
idr = drv.Create("", W, H, 1, gdal.GDT_Int32)
idr.SetGeoTransform(gt); idr.SetProjection(dtm_ds.GetProjection())
gdal.RasterizeLayer(idr, [1], ml, options=["ATTRIBUTE=idx"])
ids = idr.GetRasterBand(1).ReadAsArray()
# tiny footprints that caught no pixel -> retry with ALL_TOUCHED
got = np.zeros(len(feats)+1, bool); got[np.unique(ids)] = True
missing = [k for k in range(len(feats)) if not got[k+1]]
if missing:
    ml2 = mem.CreateLayer("b2", srs, ogr.wkbMultiPolygon)
    ml2.CreateField(ogr.FieldDefn("idx", ogr.OFTInteger))
    for k in missing:
        ft = ogr.Feature(ml2.GetLayerDefn()); ft.SetGeometry(ogr.CreateGeometryFromWkb(feats[k]["wkb"])); ft.SetField("idx", k+1)
        ml2.CreateFeature(ft)
    idr2 = drv.Create("", W, H, 1, gdal.GDT_Int32)
    idr2.SetGeoTransform(gt); idr2.SetProjection(dtm_ds.GetProjection())
    gdal.RasterizeLayer(idr2, [1], ml2, options=["ATTRIBUTE=idx", "ALL_TOUCHED=TRUE"])
    a2 = idr2.GetRasterBand(1).ReadAsArray()
    ids = np.where((ids == 0) & (a2 > 0), a2, ids)
    print(f"  ALL_TOUCHED retry recovered {len(missing)} tiny footprints", flush=True)

# ---- sorted groupby -----------------------------------------------------
flat = ids.ravel(); sel = flat > 0
order = np.argsort(flat[sel], kind="stable")
sid   = flat[sel][order]
nd_v  = ndsm.ravel()[sel][order]
dt_v  = dtm.ravel()[sel][order]
edges = np.searchsorted(sid, np.arange(1, len(feats)+2))
print(f"sampled pixels: {sel.sum():,}", flush=True)

stats = {}
for k in range(len(feats)):
    a, b = edges[k], edges[k+1]
    if b <= a: continue
    nv = nd_v[a:b]; dv = dt_v[a:b]
    nv = nv[np.isfinite(nv)]; dv = dv[np.isfinite(dv)]
    if nv.size == 0 or dv.size == 0: continue
    stats[k] = (float(np.percentile(nv, TUN["eaves_percentile"])), float(np.percentile(nv, TUN["wall_percentile"])),
                float(np.percentile(nv, TUN["ridge_percentile"])), int(nv.size),
                float(np.percentile(dv, TUN["ground_percentile"])), float(dv.min()))
print(f"buildings with LIDAR: {len(stats)} / {len(feats)} ({100*len(stats)/len(feats):.1f}%)", flush=True)
json.dump({"n_feats": len(feats)}, open(os.path.join(P["interim"], "_h_meta.json"),"w"))
np.save(os.path.join(P["interim"], "_stats_keys.npy"), np.array(sorted(stats.keys())))
np.save(os.path.join(P["interim"], "_stats_vals.npy"), np.array([stats[k] for k in sorted(stats)]))
import pickle; pickle.dump(feats, open(os.path.join(P["interim"], "_feats.pkl"),"wb"))  # wkb-safe
