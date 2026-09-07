#!/usr/bin/env python3.14
"""Coastline, beach and sea extent -> a per-tile ground classification raster.

Two things the data forces on you:
  * The OSM coastline way runs far beyond the working area -- Overpass returns the
    WHOLE way for anything touching the bbox. It must be clipped.
  * You cannot separate sea from beach by elevation alone. Where a survey was flown at
    low tide the intertidal sand occupies the same elevation band as the water surface.
    The land/sea split has to come from the coastline vector, and the sand from the
    beach polygons plus a site-specific foreshore threshold.

Emits a 3-band Byte GeoTIFF per tile (grass, sand, rock as 0-255 fractions), north-up
and georeferenced in the site CRS -- not a flipped PNG in some engine's alphamap order.
Consumers reorder for themselves; sources/adapters/unity.py shows it.

The thresholds live in the site config because they are properties of one survey and
one coastline, not universal truths. Read the note in the config before reusing them.
"""
import json, os, sys
import numpy as np
from osgeo import gdal, ogr, osr
gdal.UseExceptions(); ogr.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
P   = lib.paths(CFG)
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
NX, NY = CFG["nx"], CFG["ny"]
COAST = CFG["coast"]
WATER_Y = CFG["water_level"]
SPLAT = CFG["tuning"]["coast"]["class_res"]
OUT = os.path.join(P["out"], "coast")
lib.mkdirs(OUT)

dtm = gdal.Open(os.path.join(P["interim"], "dtm.vrt"))
gt  = dtm.GetGeoTransform()
A   = dtm.GetRasterBand(1).ReadAsArray().astype(np.float32)
Hh, Ww = A.shape

# Tile size in PIXELS, from the raster -- never assumed equal to tile_m.
TPX, TPY = lib.tile_px(CFG, gt)
if TPX % SPLAT or TPY % SPLAT:
    sys.exit(f"09: FATAL -- tile is {TPX}x{TPY} px, not divisible by class_res {SPLAT}")
FX, FY = TPX // SPLAT, TPY // SPLAT

# ---- rasterise beach polygons onto the DTM grid -------------------------
src = ogr.Open(P["gpkg"])
mp  = src.GetLayer("multipolygons")
mem = ogr.GetDriverByName("MEM").CreateDataSource("m")
srs = osr.SpatialReference(); srs.ImportFromEPSG(lib.epsg(CFG))


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
px_area = abs(gt[1] * gt[5])
print(f"beach polygons: {n_beach}   sand cells: {sand.sum():,} "
      f"({sand.sum()*px_area/1e4:.1f} ha)")

# The OSM beach polygons stop at the surveyed sand, but where the survey was flown at
# low tide the LIDAR shows a much wider intertidal flat. Anything below this threshold
# is foreshore, not grass; leaving it green puts a lawn under the sea. Site-specific.
FORE = COAST["foreshore_max_odn"]
low = np.isfinite(A) & (A > -1e30) & (A < FORE)
sand = sand | low
print(f"  + foreshore below {FORE} m -> sand now {sand.sum()*px_area/1e4:.1f} ha")

# ---- slope -> rock, so cliffs read as cliff -----------------------------
# np.gradient returns per-cell differences; divide by the cell size so the slope is a
# real angle rather than a number that changes meaning with the raster resolution.
pw, ph = lib.pixel_size(gt)
gy, gx = np.gradient(np.where(np.isfinite(A) & (A > -1e30), A, 0.0))
slope_deg = np.degrees(np.arctan(np.hypot(gx / pw, gy / ph)))
R0, R1 = COAST["rock_slope_deg"]
rock = np.clip((slope_deg - R0) / (R1 - R0), 0, 1)
print(f"slope: p50 {np.percentile(slope_deg,50):.1f} deg  p99 {np.percentile(slope_deg,99):.1f} deg"
      f"   rock coverage {100*(rock>0.5).mean():.2f}%  (ramp {R0}-{R1} deg)")

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
print(f"coastline: {raw_len/1000:.1f} km raw -> {clipped_len/1000:.1f} km after clipping")

# ---- per-tile classification rasters + water tile list -------------------
drv = gdal.GetDriverByName("GTiff")
wkt = srs.ExportToWkt()
cell = T / SPLAT
water_tiles, wrote = [], 0
for i in range(NX):
    for j in range(NY):
        e0, n0 = E0 + i * T, N0 + j * T
        col0 = int(round((e0 - gt[0]) / gt[1]))
        row1 = int(round((n0 - gt[3]) / gt[5]))          # north-up raster: +N = smaller row
        row0 = row1 - TPY
        if row0 < 0 or col0 < 0 or row1 > Hh or col0 + TPX > Ww: continue
        sub_h = A[row0:row1, col0:col0+TPX]
        if sub_h.size == 0: continue
        if np.nanmin(np.where(np.isfinite(sub_h), sub_h, 1e9)) < WATER_Y + COAST["water_margin_m"]:
            water_tiles.append([i, j])

        s = sand[row0:row1, col0:col0+TPX]
        k = rock[row0:row1, col0:col0+TPX]
        s = s.reshape(SPLAT, FY, SPLAT, FX).mean(axis=(1, 3))
        k = k.reshape(SPLAT, FY, SPLAT, FX).mean(axis=(1, 3))
        k = np.clip(k * (1.0 - s), 0, 1)                  # sand wins on the beach
        g = np.clip(1.0 - s - k, 0, 1)
        img = (np.dstack([g, s, k]) * 255).astype(np.uint8)

        # Row 0 is NORTH, matching the source raster and every GIS convention.
        d = drv.Create(os.path.join(OUT, f"ground_x{i}_y{j}.tif"), SPLAT, SPLAT, 3,
                       gdal.GDT_Byte, options=["COMPRESS=DEFLATE", "TILED=YES"])
        d.SetGeoTransform((e0, cell, 0.0, n0 + T, 0.0, -cell))
        d.SetProjection(wkt)
        for b in range(3):
            d.GetRasterBand(b + 1).WriteArray(img[..., b])
        d.FlushCache()
        wrote += 1

json.dump({"site": CFG["site"], "crs": CFG["crs"],
           "water_level": WATER_Y, "class_res": SPLAT, "tile_m": T,
           "origin": CFG["origin"],
           "row_order": "north-first (GeoTIFF convention)",
           "bands": ["grass", "sand", "rock"],
           "thresholds": {"foreshore_max_odn": FORE, "rock_slope_deg": [R0, R1]},
           "water_tiles": water_tiles,
           "coastline_km_in_area": round(clipped_len / 1000, 2)},
          open(os.path.join(OUT, "coast_manifest.json"), "w"), indent=1)
print(f"wrote {wrote} ground rasters; {len(water_tiles)} tiles need a water surface")
print(f"water level: {WATER_Y} m")
