#!/usr/bin/env python3.14
"""Coastline, beach, water and sea extent -> a per-tile ground classification raster.

Three things the data forces on you:
  * The OSM coastline way runs far beyond the working area -- Overpass returns the
    WHOLE way for anything touching the bbox. It must be clipped.
  * You cannot separate sea from beach by elevation alone. Where a survey was flown at
    low tide the intertidal sand occupies the same elevation band as the water surface.
    The land/sea split has to come from the coastline vector, and the sand from the
    beach polygons plus a site-specific foreshore threshold.
  * The DTM carries the surveyed WATER SURFACE as a flat plane at water_level (measured
    at Whitby: -2.4 m ODN, razor sharp, 100% coverage even over open sea). That plane is
    not ground. A consumer that drapes a water surface at the same height z-fights it;
    one that paints it as sand puts a beach under the sea. So it is classified as water.

Emits a 4-band Byte GeoTIFF per tile (grass, sand, rock, water as 0-255 fractions that sum
to 255), north-up and georeferenced in the site CRS -- not a flipped PNG in some engine's
alphamap order. Consumers reorder for themselves; sources/adapters/unity.py shows it.

Tiles with no DTM at all (step 02 got EMPTY, or the mosaic is empty there) get no raster
and are listed in the manifest; the old code painted them grass. Whether they are sea is
a per-site fact (coast.missing_tiles_are_water), not something to assume.

The thresholds live in the site config because they are properties of one survey and
one coastline, not universal truths. Read the note in the config before reusing them.
"""
import glob, json, os, sys
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
WTOL = float(COAST.get("water_tolerance_m", 0.3))
SPLAT = CFG["tuning"]["coast"]["class_res"]
OUT = os.path.join(P["out"], "coast")
lib.mkdirs(OUT)
CLIP = lib.parse_clip(CFG)
# Clearing takes ~25 s and the previous run's manifest survives it; the marker is the one file that
# says "this directory is mid-rebuild". See lib.begin_product.
lib.begin_product(OUT, "09_coast")
for old in glob.glob(os.path.join(OUT, "ground_*.tif")):   # no stale tiles from a previous grid
    os.remove(old)

dtm = gdal.Open(os.path.join(P["interim"], "dtm.vrt"))
gt  = dtm.GetGeoTransform()
_band = dtm.GetRasterBand(1)
A   = _band.ReadAsArray().astype(np.float32)
# Nodata by the band's declared sentinel; the isfinite() tests below then catch it
# whatever the value is, instead of a -9999 reading as 9 km below the foreshore.
A[lib.nodata_mask(A, _band.GetNoDataValue())] = np.nan
Hh, Ww = A.shape

# Tile size in PIXELS, from the raster -- never assumed equal to tile_m.
TPX, TPY = lib.tile_px(CFG, gt)
if TPX % SPLAT or TPY % SPLAT:
    sys.exit(f"09: FATAL -- tile is {TPX}x{TPY} px, not divisible by class_res {SPLAT}")
FX, FY = TPX // SPLAT, TPY // SPLAT
pw, ph = lib.pixel_size(gt)
px_area = pw * ph

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
print(f"beach polygons: {n_beach}   sand cells: {sand.sum():,} ({sand.sum()*px_area/1e4:.1f} ha)")

# The OSM beach polygons stop at the surveyed sand, but where the survey was flown at
# low tide the LIDAR shows a much wider intertidal flat. Anything below this threshold
# is foreshore, not grass; leaving it green puts a lawn under the sea. Site-specific.
FORE = COAST["foreshore_max_odn"]
low = np.isfinite(A) & (A < FORE)
sand = sand | low
print(f"  + foreshore below {FORE} m -> sand now {sand.sum()*px_area/1e4:.1f} ha")

# ---- slope -> rock, so cliffs read as cliff -----------------------------
# np.gradient returns per-cell differences; divide by the cell size so the slope is a
# real angle rather than a number that changes meaning with the raster resolution.
gy, gx = np.gradient(np.where(np.isfinite(A), A, 0.0))
slope_deg = np.degrees(np.arctan(np.hypot(gx / pw, gy / ph)))
R0, R1 = COAST["rock_slope_deg"]
rock = np.clip((slope_deg - R0) / (R1 - R0), 0, 1)
print(f"slope: p50 {np.percentile(slope_deg,50):.1f} deg  p99 {np.percentile(slope_deg,99):.1f} deg"
      f"   rock coverage {100*(rock>0.5).mean():.2f}%  (ramp {R0}-{R1} deg)")

# ---- water: the DTM's flat surface at water_level is not ground ---------
# Flatness is judged by the CALMEST neighbour, not the central-difference slope: the last
# water cell before a sea wall has a huge central slope but a perfectly flat neighbour on
# the sea side, and must still read as water -- otherwise every quay and wall grows a
# one-cell sand fringe. fmin ignores NaN so a cell beside a nodata hole is judged on the
# neighbours it has.
Af = np.where(np.isfinite(A), A, np.nan)
dz = np.full(Af.shape, np.inf, np.float32)
dz[:, 1:]  = np.fmin(dz[:, 1:],  np.abs(Af[:, 1:] - Af[:, :-1]))
dz[:, :-1] = np.fmin(dz[:, :-1], np.abs(Af[:, :-1] - Af[:, 1:]))
dz[1:, :]  = np.fmin(dz[1:, :],  np.abs(Af[1:, :] - Af[:-1, :]))
dz[:-1, :] = np.fmin(dz[:-1, :], np.abs(Af[:-1, :] - Af[1:, :]))
WFLAT = float(COAST.get("water_flat_dz_per_m", 0.08)) * min(pw, ph)     # ~4.6 degrees at the calmest side
# Two rules, because the surveyed sea is not one plane. Flight strips flown at different
# tide states, plus swell, spread the surface over several decimetres (Whitby: one broad
# peak, -2.3 +/- 0.3 m). Anything BELOW the water level cannot be exposed ground, whatever
# its slope; anything within tolerance of it and locally flat is more of the same surface.
below = np.isfinite(A) & (A < WATER_Y - 0.1)
band  = np.isfinite(A) & (np.abs(A - WATER_Y) < WTOL) & (dz < WFLAT)
water = below | band
sand = sand & ~water
print(f"water surface (|z - {WATER_Y}| < {WTOL} m and flat): {water.sum()*px_area/1e4:.1f} ha")

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
water_tiles, missing, wrote = [], [], 0
clipped, n_clipped_cells = [], 0
for i in range(NX):
    for j in range(NY):
        # A position wholly outside the clip gets no raster and is tiles_clipped -- tested before
        # the mosaic bounds so it is never confused with a coverage gap (tiles_without_dtm).
        state = lib.tile_state(CLIP, CFG, i, j)
        if state == "outside":
            clipped.append([i, j]); continue
        e0, n0 = E0 + i * T, N0 + j * T
        col0 = int(round((e0 - gt[0]) / gt[1]))
        row1 = int(round((n0 - gt[3]) / gt[5]))          # north-up raster: +N = smaller row
        row0 = row1 - TPY
        if row0 < 0 or col0 < 0 or row1 > Hh or col0 + TPX > Ww:
            missing.append([i, j]); continue             # outside the mosaic: no tile from step 02
        sub_h = A[row0:row1, col0:col0+TPX]
        if np.isfinite(sub_h).mean() < 0.01:
            missing.append([i, j]); continue             # inside the mosaic but empty: same thing
        # Does this tile need a water surface? For a tile straddling the clip line, judge the KEPT
        # DTM cells only: the sea beyond the line is not part of the model.
        sub_w = sub_h
        if state == "straddle":
            kd = lib.cell_mask(CLIP, gt, TPY, TPX, row0=row0, col0=col0)
            sub_w = np.where(kd, sub_h, np.nan)
        if np.isfinite(sub_w).any() and np.nanmin(np.where(np.isfinite(sub_w), sub_w, 1e9)) < WATER_Y + COAST["water_margin_m"]:
            water_tiles.append([i, j])

        # Pixel centres sit on integer metres, so a 512 m tile spans 513 centres and a 2:1
        # downsample into 256 edge-aligned cells cannot be exact: each class cell is biased
        # by half a DTM pixel (about +0.5 m north, -0.5 m east). Known, sub-cell, accepted.
        def down(m):
            return m[row0:row1, col0:col0+TPX].reshape(SPLAT, FY, SPLAT, FX).mean(axis=(1, 3))
        s, k, w = down(sand), down(rock), down(water)
        k = np.clip(k * (1.0 - s - w), 0, 1)              # sand and water win over rock
        g = np.clip(1.0 - s - k - w, 0, 1)
        img = (np.dstack([g, s, k, w]) * 255).astype(np.uint8)
        # Class cells outside the clip are 0 in every band (sum 0), judged at the class-cell
        # centres with the raster's own geotransform; every kept cell keeps its 252..255 sum.
        if state == "straddle":
            km = lib.cell_mask(CLIP, (e0, cell, 0.0, n0 + T, 0.0, -cell), SPLAT, SPLAT)
            img[~km] = 0
            n_clipped_cells += int((~km).sum())

        # Row 0 is NORTH, matching the source raster and every GIS convention.
        d = drv.Create(os.path.join(OUT, f"ground_x{i}_y{j}.tif"), SPLAT, SPLAT, 4,
                       gdal.GDT_Byte, options=["COMPRESS=DEFLATE", "TILED=YES"])
        d.SetGeoTransform((e0, cell, 0.0, n0 + T, 0.0, -cell))
        d.SetProjection(wkt)
        for b in range(4):
            d.GetRasterBand(b + 1).WriteArray(img[..., b])
        d.FlushCache()
        wrote += 1

assume_sea = bool(COAST.get("missing_tiles_are_water", False))
if missing and assume_sea:
    water_tiles += [t for t in missing if t not in water_tiles]

json.dump({"site": CFG["site"], "crs": CFG["crs"],
           "water_level": WATER_Y, "water_tolerance_m": WTOL, "class_res": SPLAT, "tile_m": T,
           "origin": CFG["origin"],
           "row_order": "north-first (GeoTIFF convention)",
           "bands": ["grass", "sand", "rock", "water"],
           "thresholds": {"foreshore_max_odn": FORE, "rock_slope_deg": [R0, R1]},
           "water_tiles": water_tiles,
           "tiles_without_dtm": missing,
           "missing_tiles_are_water": assume_sea,
           "coastline_km_in_area": round(clipped_len / 1000, 2),
           **({} if CLIP is None else {
               "clip": lib.clip_manifest(CLIP, CFG),
               "tiles_clipped": clipped,
               "clipped_cells": n_clipped_cells,
               "bands_note": "grass+sand+rock+water sums to 252..255 for every cell inside the clip (each band "
                             "is truncated to uint8 separately); a cell outside the clip is 0 in all four bands, "
                             "and sum 0 occurs only outside."})},
          open(os.path.join(OUT, "coast_manifest.json"), "w"), indent=1)
lib.end_product(OUT)
print(f"wrote {wrote} ground rasters; {len(water_tiles)} tiles need a water surface"
      + (f"; {len(missing)} tiles have no DTM: {missing}" if missing else "")
      + (f"; {len(clipped)} positions outside the clip (no raster); {n_clipped_cells:,} class cells zeroed on straddling tiles" if CLIP is not None else ""))
print(f"water level: {WATER_Y} m")
