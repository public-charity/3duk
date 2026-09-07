#!/usr/bin/env python3.14
"""Coastline, beach and sea extent.

Two things the data forces on you:
  * The OSM coastline way is 34 km long and runs to Herne Bay -- Overpass returns
    the WHOLE way for anything touching the bbox. It must be clipped.
  * You cannot separate sea from beach by elevation. 17% of the DTM sits below
    0.5 m ODN and Margate's tidal sands occupy the same band as the water surface,
    because the survey was flown at low tide. The land/sea split has to come from
    the coastline vector, and the sand from the beach polygons.

Emits: a splat map per tile (R grass, G sand, B rock-by-slope) and the list of
tiles that need a water surface.
"""
import json, os, math
import numpy as np
from osgeo import gdal, ogr, osr
gdal.UseExceptions(); ogr.UseExceptions()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG  = json.load(open(f"{ROOT}/sources/config/margate.json"))
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
NX, NY = CFG["nx"], CFG["ny"]
WATER_Y = CFG.get("water_level", -0.6)
SPLAT   = 256
OUT = f"{ROOT}/data/out/coast"; os.makedirs(OUT, exist_ok=True)

dtm = gdal.Open(f"{ROOT}/data/interim/dtm.vrt")
gt  = dtm.GetGeoTransform()
A   = dtm.GetRasterBand(1).ReadAsArray().astype(np.float32)
Hh, Ww = A.shape

# ---- rasterise beach polygons onto the DTM grid -------------------------
src = ogr.Open(f"{ROOT}/data/derived/margate.gpkg")
mp  = src.GetLayer("multipolygons")
mem = ogr.GetDriverByName("MEM").CreateDataSource("m")
srs = osr.SpatialReference(); srs.ImportFromEPSG(27700)

def burn(where, name):
    mp.SetAttributeFilter(where)
    lay = mem.CreateLayer(name, srs, ogr.wkbMultiPolygon)
    n = 0
    for f in mp:
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty(): continue
        ft = ogr.Feature(lay.GetLayerDefn()); ft.SetGeometry(g.Clone()); lay.CreateFeature(ft); n += 1
    r = gdal.GetDriverByName("MEM").Create("", Ww, Hh, 1, gdal.GDT_Byte)
    r.SetGeoTransform(gt); r.SetProjection(dtm.GetProjection())
    gdal.RasterizeLayer(r, [1], lay, burn_values=[255])
    return np.asarray(r.GetRasterBand(1).ReadAsArray()) > 0, n

sand, n_beach = burn("\"natural\" IN ('beach','sand','shingle')", "beach")
print(f"beach polygons: {n_beach}   sand pixels: {sand.sum():,} ({sand.sum()/1e4:.1f} ha)")

# The OSM beach polygons stop at the surveyed sand, but the LIDAR shows a much
# wider intertidal flat -- it was flown at low tide. Anything low-lying seaward of
# the town is foreshore, not grass; leaving it green puts a lawn under the sea.
low = np.isfinite(A) & (A > -1e30) & (A < 1.2)
sand = sand | low
print(f"  + foreshore below 1.2 m ODN -> sand now {sand.sum()/1e4:.1f} ha")

# ---- slope -> rock, so the Cliftonville cliffs read as cliff ------------
gy, gx = np.gradient(np.where(np.isfinite(A) & (A > -1e30), A, 0.0))
slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
rock = np.clip((slope_deg - 22.0) / 18.0, 0, 1)          # 22 deg -> 40 deg ramp
print(f"slope: p50 {np.percentile(slope_deg,50):.1f} deg  p99 {np.percentile(slope_deg,99):.1f} deg"
      f"   rock coverage {100*(rock>0.5).mean():.2f}%")

# ---- clip the coastline, purely to record what it is --------------------
ln = src.GetLayer("lines")
ln.SetAttributeFilter("other_tags LIKE '%\"natural\"=>\"coastline\"%'")
rect = ogr.CreateGeometryFromWkt(
    f"POLYGON(({E0} {N0},{E0+NX*T} {N0},{E0+NX*T} {N0+NY*T},{E0} {N0+NY*T},{E0} {N0}))")
clipped_len = 0.0; raw_len = 0.0
for f in ln:
    g = f.GetGeometryRef()
    raw_len += g.Length()
    c = g.Intersection(rect)
    if c and not c.IsEmpty(): clipped_len += c.Length()
print(f"coastline: {raw_len/1000:.1f} km raw -> {clipped_len/1000:.1f} km after clipping to the working rect")

# ---- per-tile splat maps + water tile list -------------------------------
water_tiles, wrote = [], 0
for i in range(NX):
    for j in range(NY):
        e0, n0 = E0 + i*T, N0 + j*T
        col0 = int(round((e0 - gt[0]) / gt[1]))
        row1 = int(round((n0 - gt[3]) / gt[5]))          # north-up raster: +N = smaller row
        row0 = row1 - T
        if row0 < 0 or col0 < 0 or row1 > Hh or col0 + T > Ww: continue
        sub_h = A[row0:row1, col0:col0+T]
        if sub_h.size == 0: continue
        if np.nanmin(np.where(np.isfinite(sub_h), sub_h, 1e9)) < WATER_Y + 0.75:
            water_tiles.append([i, j])

        s = sand[row0:row1, col0:col0+T]
        k = rock[row0:row1, col0:col0+T]
        # downsample to SPLAT x SPLAT, then flip so row 0 is SOUTH (Unity alphamap order)
        f = T // SPLAT
        s = s.reshape(SPLAT, f, SPLAT, f).mean(axis=(1,3))
        k = k.reshape(SPLAT, f, SPLAT, f).mean(axis=(1,3))
        s = np.flipud(s); k = np.flipud(k)
        k = np.clip(k * (1.0 - s), 0, 1)                  # sand wins on the beach
        g = np.clip(1.0 - s - k, 0, 1)
        img = (np.dstack([g, s, k]) * 255).astype(np.uint8)
        d = gdal.GetDriverByName("MEM").Create("", SPLAT, SPLAT, 3, gdal.GDT_Byte)
        for b in range(3): d.GetRasterBand(b+1).WriteArray(img[..., b])
        gdal.GetDriverByName("PNG").CreateCopy(f"{OUT}/splat_x{i}_y{j}.png", d)
        wrote += 1

json.dump({"water_level": WATER_Y, "splat_res": SPLAT, "tile_m": T,
           "water_tiles_flat": [v for t in water_tiles for v in t],
           "layers": ["grass", "sand", "rock"]},
          open(f"{OUT}/coast_manifest.json", "w"), indent=1)
print(f"wrote {wrote} splat maps; {len(water_tiles)} tiles need water surface")
print(f"water level: {WATER_Y} m ODN")
