#!/usr/bin/env python3.14
"""Neutral pipeline output -> Unity conventions.

Run after the pipeline:  python3.14 sources/adapters/unity.py

Everything Unity-shaped lives here and nowhere else. This is the reference for writing
an adapter for any other consumer -- the conversions it performs are exactly the
assumptions the data layer used to carry:

  coordinates   CRS eastings/northings  ->  local metres from the grid origin
  axes          [E, N, elevation]       ->  [x, y, z] with y up  (x = E-E0, z = N-N0)
  terrain       Float32 GeoTIFF, north-up -> 16-bit RAW, south-first, normalised
  ground cover  3-band GeoTIFF, north-up  -> RGB PNG, south-first (alphamap order)
  orientation   bearing (cw from north)   -> yaw about Y  (numerically identical)
  roads         honest draped elevation   -> plus class lift, bridge and tunnel offsets

Writes into data/<site>/out/unity/ and never touches the neutral output.
"""
import glob, json, math, os, sys
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
P = lib.paths(CFG)
ADP = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "unity.json"),
                     encoding="utf-8"))
E0, N0 = CFG["origin"]["E"], CFG["origin"]["N"]
SRC = P["out"]
OUT = os.path.join(P["out"], "unity")
lib.mkdirs(OUT)


def need(path, what):
    if not os.path.exists(path):
        sys.exit(f"unity adapter: {what} missing at {path}; run the pipeline first")
    return path


# ---- terrain: GeoTIFF -> 16-bit RAW -------------------------------------
def terrain():
    d = os.path.join(SRC, "terrain")
    man = json.load(open(need(os.path.join(d, "terrain_manifest.json"), "terrain manifest")))
    lo, hi = man["range_m"]
    tc = ADP["terrain"]
    if tc["y_base"] == "auto" or tc["y_size"] == "auto":
        # One window for the whole site, derived from the measured range: every tile
        # shares it (Unity needs that for seamless neighbours) and nothing can fall outside.
        m = float(tc.get("auto_margin_m", 5.0))
        yb = float(math.floor(lo - m))
        ys = float(math.ceil(hi + m) - yb)
    else:
        yb, ys = float(tc["y_base"]), float(tc["y_size"])
    # The old pipeline clipped to a fixed window in silence. A site with ground outside it
    # came out as a plateau with no error anywhere. Refuse instead.
    if lo < yb or hi > yb + ys:
        sys.exit(f"unity adapter: site elevation {lo}..{hi} m does not fit the encoding window "
                 f"{yb}..{yb+ys} m. Widen terrain.y_base / y_size in sources/adapters/unity.json "
                 f"-- encoding as-is would flatten real ground.")
    o = os.path.join(OUT, "terrain"); lib.mkdirs(o)
    n = 0
    for t in man["tiles"]:
        a = gdal.Open(os.path.join(d, t["file"])).GetRasterBand(1).ReadAsArray().astype(np.float64)
        h = np.clip((a - yb) / ys, 0.0, 1.0)
        h = np.flipud(h)                       # GeoTIFF north-first -> Unity south-first
        (h * 65535.0).round().astype("<u2").tofile(
            os.path.join(o, f"hm_x{t['x']}_y{t['y']}.raw"))
        n += 1
    json.dump({"origin": man["origin"], "tile_m": man["tile_m"], "res": man["res"],
               "y_base": yb, "y_size": ys, "range_m": man["range_m"],
               "tiles": [{"x": t["x"], "y": t["y"]} for t in man["tiles"]]},
              open(os.path.join(o, "terrain_manifest.json"), "w"), indent=1)
    print(f"terrain : {n} RAW heightmaps (window {yb}..{yb+ys} m, site {lo}..{hi} m)")


# ---- roads: CRS -> local Y-up, plus the rendering fudges ----------------
def roads():
    d = os.path.join(SRC, "networks")
    need(os.path.join(d, "networks_manifest.json"), "networks manifest")
    R = ADP["roads"]
    lift, dflt = R["class_lift_m"], R["default_lift_m"]
    o = os.path.join(OUT, "networks"); lib.mkdirs(o)
    n = 0
    for path in sorted(glob.glob(os.path.join(d, "roads_*.jsonl"))):
        out = []
        for line in open(path):
            r = json.loads(line)
            if r.get("cls") == "_junction":
                e, nn, z = r["pts"][0]
                out.append({"cls": "_junction", "r": r["r"],
                            "pts": [[round(e - E0, 2), round(z + R["junction_lift_m"], 2),
                                     round(nn - N0, 2)]]})
                continue
            dz = lift.get(r["cls"], dflt)
            if r.get("bridge"): dz += R["bridge_offset_m"]
            if r.get("tunnel"): dz += R["tunnel_offset_m"]
            rec = {k: r[k] for k in ("id", "cls", "w", "pav", "name") if k in r}
            rec["pts"] = [[round(e - E0, 2), round(z + dz, 2), round(nn - N0, 2)]
                          for e, nn, z in r["pts"]]
            out.append(rec)
        with open(os.path.join(o, os.path.basename(path)), "w") as fh:
            for rec in out:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n"); n += 1
    print(f"roads   : {n} segments -> local Y-up, class lift and bridge/tunnel offsets applied")


# ---- massing: rings CRS -> local ---------------------------------------
def massing():
    d = os.path.join(SRC, "massing")
    need(os.path.join(d, "massing_manifest.json"), "massing manifest")
    o = os.path.join(OUT, "massing"); lib.mkdirs(o)
    n = 0
    for path in sorted(glob.glob(os.path.join(d, "buildings_*.jsonl"))):
        with open(os.path.join(o, os.path.basename(path)), "w") as fh:
            for line in open(path):
                b = json.loads(line)
                b["rings"] = [{"hole": r["hole"],
                               "pts": [(round(e - E0, 3), round(nn - N0, 3)) for e, nn in r["pts"]]}
                              for r in b["rings"]]
                b["base_y"] = b.pop("base_z")
                fh.write(json.dumps(b, separators=(",", ":")) + "\n"); n += 1
    print(f"massing : {n} buildings -> local metres")


# ---- ground cover: GeoTIFF -> flipped RGB PNG ---------------------------
def ground():
    d = os.path.join(SRC, "coast")
    man = json.load(open(need(os.path.join(d, "coast_manifest.json"), "coast manifest")))
    o = os.path.join(OUT, "coast"); lib.mkdirs(o)
    png = gdal.GetDriverByName("PNG")
    mem = gdal.GetDriverByName("MEM")
    n, nw = 0, 0
    for path in sorted(glob.glob(os.path.join(d, "ground_*.tif"))):
        ds = gdal.Open(path)
        w, h = ds.RasterXSize, ds.RasterYSize
        bands = [ds.GetRasterBand(b + 1).ReadAsArray().astype(np.float64) for b in range(min(ds.RasterCount, 4))]
        g, s, k = bands[0], bands[1], bands[2]
        # Unity alphamaps must sum to 1 per cell. Where the neutral raster says "water" the
        # three ground layers sum to less; give the remainder to grass so the terrain under
        # the water plane is still painted, and hand the water mask over separately.
        g = np.clip(g + np.clip(255.0 - (g + s + k), 0, 255), 0, 255)
        tmp = mem.Create("", w, h, 3, gdal.GDT_Byte)
        for b, arr in enumerate((g, s, k)):    # north-first -> south-first alphamap order
            tmp.GetRasterBand(b + 1).WriteArray(np.flipud(arr).astype(np.uint8))
        name = os.path.basename(path).replace("ground_", "splat_").replace(".tif", ".png")
        png.CreateCopy(os.path.join(o, name), tmp)
        n += 1
        if len(bands) >= 4:
            wm = mem.Create("", w, h, 1, gdal.GDT_Byte)
            wm.GetRasterBand(1).WriteArray(np.flipud(bands[3]).astype(np.uint8))
            png.CreateCopy(os.path.join(o, name.replace("splat_", "water_")), wm)
            nw += 1
    wt = man["water_tiles"]
    json.dump({"water_level": man["water_level"], "splat_res": man["class_res"],
               "tile_m": man["tile_m"], "layers": man["bands"][:3],
               "water_mask": "water_x{i}_y{j}.png -- 255 where the DTM carries the flat water "
                             "surface; sink or cut the terrain there so it does not z-fight the water plane",
               "water_tiles_flat": [v for t in wt for v in t],
               "tiles_without_dtm_flat": [v for t in man.get("tiles_without_dtm", []) for v in t]},
              open(os.path.join(o, "coast_manifest.json"), "w"), indent=1)
    print(f"ground  : {n} splat PNGs, {nw} water masks, {len(wt)} water tiles")


# ---- furniture: CRS + bearing -> local + yaw ----------------------------
def furniture():
    d = os.path.join(SRC, "furniture")
    if not os.path.isdir(d):
        print("furniture: none (step 10 not run)"); return
    o = os.path.join(OUT, "furniture"); lib.mkdirs(o)
    n = 0
    for path in sorted(glob.glob(os.path.join(d, "furniture_*.jsonl"))):
        with open(os.path.join(o, os.path.basename(path)), "w") as fh:
            for line in open(path):
                r = json.loads(line)
                # bearing (cw from grid north) and Unity yaw about +Y are the same number:
                # both are atan2(east, north) in degrees.
                rec = {"id": r["id"], "prop": r["prop"], "name": r["name"],
                       "x": round(r["e"] - E0, 2), "z": round(r["n"] - N0, 2),
                       "y": r["z"], "yaw": r["bearing"],
                       "src": r["src"], "d": r["d"], "cls": r["cls"], "nudged": r["nudged"]}
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n"); n += 1
    print(f"furniture: {n} placements -> local metres, yaw")


if __name__ == "__main__":
    print(f"unity adapter: {CFG['site']}  ({CFG['crs']} -> local metres from "
          f"E{E0} N{N0})")
    terrain(); roads(); massing(); ground(); furniture()
    print(f"-> {OUT}")
