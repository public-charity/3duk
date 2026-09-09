"""Independent D2 + survey-honesty audit.

(a) terrain/dtm_*.tif vs raw/lidar/dtm_*.tif on every cell the RAW tile marks valid
    -> proves data/thanet/out/terrain still carries the survey, unconformed.
(b) unreal/landscape/hm_*.r16 vs terrain/dtm_*.tif on every kept cell
    -> the encoding distance only.
(c) unreal/landscape_conformed/hm_*.r16 vs unreal/landscape/hm_*.r16
    -> how much the conform moved the ground, and that the survey product did not move.
(d) conform_delta rasters reconstruct the survey exactly.
"""
import json, os, random, sys
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

ROOT = "C:/Users/Shadow/code/3duk"
CFG = json.load(open(f"{ROOT}/sources/config/sites/thanet.json"))
NX, NY, RES = CFG["nx"], CFG["ny"], CFG["grid_res"]
LS = f"{ROOT}/data/thanet/out/unreal/landscape"
LC = f"{ROOT}/data/thanet/out/unreal/landscape_conformed"
TER = f"{ROOT}/data/thanet/out/terrain"
RAW = f"{ROOT}/data/thanet/raw/lidar"

pos = [(i, j) for i in range(NX) for j in range(NY) if os.path.exists(f"{TER}/dtm_x{i}_y{j}.tif")]
print(f"{len(pos)} exported tiles", flush=True)


def rd_tif(p):
    d = gdal.Open(p); b = d.GetRasterBand(1)
    return b.ReadAsArray().astype(np.float64), b.GetNoDataValue()


def r16(path):
    return np.fromfile(path, dtype="<u2").astype(np.int64).reshape(RES, RES)


def r8(path):
    return np.fromfile(path, dtype=np.uint8).reshape(RES, RES)


# ---- (a) survey honesty: out/terrain vs raw, on raw-valid cells -------------------------
random.seed(20260909)
sample = random.sample(pos, 40)
a_n = a_diff = 0; a_max = 0.0; a_worst = None
for (i, j) in sample:
    rp = f"{RAW}/dtm_x{i}_y{j}.tif"
    if not os.path.exists(rp):
        continue
    r, rnd = rd_tif(rp)
    t, tnd = rd_tif(f"{TER}/dtm_x{i}_y{j}.tif")
    good = np.isfinite(r) & (r > -1e30)
    if rnd is not None:
        good &= ~np.isclose(r, rnd)
    if tnd is not None:
        good &= ~np.isclose(t, tnd)          # exclude cells 05 clipped away
    d = np.abs(r[good] - t[good])
    a_n += int(good.sum()); a_diff += int((d > 0).sum())
    if d.size and d.max() > a_max:
        a_max = float(d.max()); a_worst = [i, j]
print(f"(a) terrain vs raw on {len(sample)} tiles: {a_n:,} raw-valid unclipped cells, "
      f"{a_diff:,} differ, max {a_max} m, worst tile {a_worst}", flush=True)

# ---- (b) r16 vs GeoTIFF, all tiles, kept cells ------------------------------------------
b_n = 0; b_max = 0.0; b_worst = None; b_sq = 0.0
for (i, j) in pos:
    t, tnd = rd_tif(f"{TER}/dtm_x{i}_y{j}.tif")
    h = (r16(f"{LS}/hm_x{i}_y{j}.r16") - 32768) / 128.0
    keep = r8(f"{LS}/clip_x{i}_y{j}.r8") == 255
    if tnd is not None:
        keep &= ~np.isclose(t, tnd)
    d = np.abs(h[keep] - t[keep])
    b_n += int(keep.sum()); b_sq += float((d * d).sum())
    if d.size and d.max() > b_max:
        b_max = float(d.max()); b_worst = [i, j]
print(f"(b) landscape r16 vs terrain GeoTIFF: {b_n:,} kept cells, max {b_max} m "
      f"(half-quantum {1/256:.9f}), rms {(b_sq / b_n) ** 0.5:.10f}, worst tile {b_worst}", flush=True)

# ---- (c) conformed vs survey landscape ---------------------------------------------------
c_ch = 0; c_tot = 0; c_max = 0.0; c_min = 0.0; c_tiles = 0; deltas = []
d_bad = 0
for (i, j) in pos:
    hs = r16(f"{LS}/hm_x{i}_y{j}.r16")
    hc = r16(f"{LC}/hm_x{i}_y{j}.r16")
    d = (hc - hs) / 128.0
    c_tot += d.size
    n = int((d != 0).sum()); c_ch += n
    if n:
        c_tiles += 1
        c_max = max(c_max, float(d.max())); c_min = min(c_min, float(d.min()))
        deltas.append(np.abs(d[d != 0]).astype(np.float32))
    dp = f"{LC}/conform_delta_x{i}_y{j}.r16"
    if os.path.exists(dp):
        dl = np.fromfile(dp, dtype="<i2").astype(np.int64).reshape(RES, RES)
        if not np.array_equal(hc - dl, hs):
            d_bad += 1
    elif n:
        d_bad += 1                              # changed but no delta raster
dd = np.concatenate(deltas) if deltas else np.zeros(1, np.float32)
print(f"(c) conformed vs landscape: {c_ch:,} of {c_tot:,} cells changed ({100.0*c_ch/c_tot:.3f}%), "
      f"{c_tiles} tiles touched, fill max {c_max} m, cut min {c_min} m; "
      f"|delta| p50 {np.percentile(dd,50):.6f} p95 {np.percentile(dd,95):.6f} p99 {np.percentile(dd,99):.6f}", flush=True)
print(f"(d) tiles where conform_delta does NOT reconstruct the survey: {d_bad}", flush=True)
json.dump(dict(terrain_vs_raw_cells=a_n, terrain_vs_raw_differing=a_diff, terrain_vs_raw_max_m=a_max,
               r16_vs_geotiff_cells=b_n, r16_vs_geotiff_max_m=b_max, r16_vs_geotiff_rms_m=(b_sq / b_n) ** 0.5,
               r16_vs_geotiff_worst_tile=b_worst,
               conform_cells_changed=c_ch, conform_cells_total=c_tot, conform_tiles=c_tiles,
               conform_max_fill_m=c_max, conform_max_cut_m=c_min,
               conform_abs_p50=float(np.percentile(dd, 50)), conform_abs_p95=float(np.percentile(dd, 95)),
               conform_abs_p99=float(np.percentile(dd, 99)),
               delta_reconstruction_failures=d_bad),
          open(sys.argv[1], "w"), indent=1)
print("WROTE", sys.argv[1])
