#!/usr/bin/env python3
"""Dry-run steps 05-10 and the Unity adapter against a synthetic two-tile site.

    python3 sources/tests/dryrun.py            # needs numpy only -- no GDAL, no network
    python3 sources/tests/dryrun.py --keep     # leave the output directory for inspection

A fake in-memory GDAL/OGR (sources/tests/fake_osgeo) stands in for the real one, so this
runs on any machine with numpy. It proves the steps import, resolve config through lib,
agree with each other on file and field names, emit the schemas OUTPUT.md promises, and
that the specific fidelity fixes behave: nodata by declared sentinel, honest bridge
elevation, buildings without LIDAR emitted rather than dropped, calibration from config,
north-up rasters, and an adapter that refuses to clip terrain.

It does NOT prove anything about GDAL itself -- rasterisation here is envelope-fill and
line clipping is vertex-keep. Run the real pipeline on a GDAL machine for that.

Steps 01-04 are not covered: they are network fetches and one GDAL rasterisation whose
outputs this harness hand-builds instead.
"""
import glob, json, os, pickle, runpy, shutil, sys, tempfile, traceback
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "fake_osgeo"))
sys.path.insert(0, SRC)
import osgeo                      # the fake, by virtue of sys.path order
from osgeo import gdal, ogr
import lib

KEEP = "--keep" in sys.argv
ROOT = tempfile.mkdtemp(prefix="3duk-dryrun-")
lib.ROOT = ROOT
SITE = "_dryrun"
os.environ["SITE"] = SITE
SITE_JSON = os.path.join(SRC, "config", "sites", f"{SITE}.json")

E0, N0, T, NX, NY, RES = 500000, 150000, 512, 2, 1, 513
ND = -9999.0
SLOPE, CLIFF_N, CLIFF_H, SEA_N = 0.02, 306, 20.0, 60

json.dump({
    "crs": "EPSG:27700", "origin": {"E": E0, "N": N0}, "tile_m": T, "nx": NX, "ny": NY,
    "grid_res": RES, "bbox_wgs84": [51.0, 1.0, 51.1, 1.1], "vertical_datum": "TEST",
    "water_level": -0.6,
    "height_calib": {"intercept": 3.16, "m_per_level": 1.84, "dispute_m": 4.0},
    "coast": {"foreshore_max_odn": 1.2, "rock_slope_deg": [22.0, 40.0], "water_margin_m": 0.75},
    "wcs": {"dtm": {"url": "x", "coverage": "x"}, "dsm": {"url": "x", "coverage": "x"}},
    "landmarks": {"_note": "test", "Test Tower": {"h_body": 57.0, "roof": "flat"},
                  "Never Matches": {"h_body": 1.0}},
}, open(SITE_JSON, "w"), indent=1)

results = []
def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok or not detail else f"   <- {detail}"))

def z_at(e, n):
    z = 5.0 + SLOPE * (e - E0)
    if n >= N0 + CLIFF_N: z += CLIFF_H
    if n < N0 + SEA_N: z = -1.0
    return z

def jl(pattern):
    return [json.loads(l) for p in sorted(glob.glob(pattern)) for l in open(p)]

try:
    cfg = lib.load(); P = lib.paths(cfg)
    lib.mkdirs(*[P[k] for k in ("raw", "interim", "derived", "out", "lidar")])

    # ------------------------------------------------------------ synthetic DTM
    W, H = NX * T + 1, NY * T + 1
    gt = (E0 - 0.5, 1.0, 0.0, N0 + NY * T + 0.5, 0.0, -1.0)
    EE, NN = np.meshgrid(E0 + np.arange(W), N0 + NY * T - np.arange(H))   # both (H, W), pixel centres
    Z = (5.0 + SLOPE * (EE - E0)).astype(np.float32)
    Z[NN >= N0 + CLIFF_N] += CLIFF_H
    Z[NN < N0 + SEA_N] = -1.0
    patch = (EE >= E0 + 700) & (EE < E0 + 740) & (NN >= N0 + 400) & (NN < N0 + 440)
    Z[patch] = ND
    vrt = gdal.GetDriverByName("MEM").Create(os.path.join(P["interim"], "dtm.vrt"), W, H, 1, gdal.GDT_Float32)
    vrt.SetGeoTransform(gt); vrt.SetProjection("FAKE"); vrt.GetRasterBand(1).SetNoDataValue(ND)
    vrt.GetRasterBand(1).WriteArray(Z)
    for i in range(NX):
        for j in range(NY):
            c0, r0 = i * T, (NY - 1 - j) * T
            t = gdal.GetDriverByName("GTiff").Create(os.path.join(P["lidar"], f"dtm_x{i}_y{j}.tif"), RES, RES, 1, gdal.GDT_Float32)
            t.SetGeoTransform((E0 + i * T - 0.5, 1, 0, N0 + (j + 1) * T + 0.5, 0, -1))
            t.GetRasterBand(1).SetNoDataValue(ND)
            t.GetRasterBand(1).WriteArray(Z[r0:r0 + RES, c0:c0 + RES])

    # ------------------------------------------------------------ synthetic vectors
    G = ogr.Geometry
    lines = ogr.Layer("lines", ["osm_id", "highway", "name", "other_tags"])
    def way(id, cls, pts, name=None, ot=None):
        lines.CreateFeature(ogr.Feature(lines.defn, {"osm_id": id, "highway": cls, "name": name, "other_tags": ot}, G("LINESTRING", pts)))
    J = (E0 + 600, N0 + 200)
    way("w1a", "residential", [(E0 + 100, N0 + 200), J], "High Street", '"lanes"=>"2"')   # crosses the tile seam at E0+512
    way("w1b", "residential", [J, (E0 + 900, N0 + 250)], "High Street")
    way("w2", "footway", [J, (E0 + 600, N0 + 100)])                                       # third way at J -> junction
    way("w4", "primary", [(E0 + 720, N0 + 380), (E0 + 720, N0 + 460)], ot='"bridge"=>"yes"')  # crosses the nodata patch
    way("w5", "tertiary", [(E0 + 50, N0 + 450), (E0 + 300, N0 + 450)], ot='"tunnel"=>"yes"')
    way("w6", "construction", [(E0 + 10, N0 + 10), (E0 + 20, N0 + 20)])                   # skipped class
    way("w7", "bus_guideway", [(E0 + 10, N0 + 30), (E0 + 20, N0 + 40)])                   # not in widths -> skipped
    way("c1", None, [(E0 - 5000, N0 + SEA_N), (E0 + 200, N0 + SEA_N), (E0 + 3000, N0 + SEA_N)], ot='"natural"=>"coastline"')

    mp = ogr.Layer("multipolygons", ["osm_id", "building", "name", "natural", "other_tags"])
    rect = lambda x, y, w, h: [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    mp.CreateFeature(ogr.Feature(mp.defn, {"osm_id": "beach", "natural": "beach"},
                                 G("POLYGON", [rect(E0, N0 + SEA_N, 400, 60)])))
    #      id    fields                                                              footprint                    04 stats (p25,p50,p90,npx,d15,dmin) or None
    B = [("b1", {"building": "house", "other_tags": '"building:levels"=>"2"'},       rect(E0 + 150, N0 + 220, 10, 8),  (5.0, 6.8, 9.5, 60, 9.4, 9.2)),
         ("b2", {"building": "apartments", "name": "Test Tower", "other_tags": '"building:levels"=>"10"'}, rect(E0 + 700, N0 + 150, 20, 20), (20.0, 21.0, 23.0, 300, 26.0, 25.5)),
         ("b3", {"building": "retail", "other_tags": '"building:levels"=>"3"'},      rect(E0 + 300, N0 + 230, 15, 15), (3.0, 3.2, 4.0, 100, 12.0, 11.8)),
         ("b4", {"building": "shed"},                                                 rect(E0 + 50, N0 + 240, 3, 3),    (2.0, 2.4, 2.6, 3, 6.5, 6.4)),
         ("b5", {"building": "house", "other_tags": '"height"=>"8.5 m"'},            rect(E0 + 200, N0 + 260, 8, 8),   (1.0, 2.0, 3.0, 20, 11.0, 10.9)),
         ("b6", {"building": "terrace", "other_tags": '"building:levels"=>"3"'},     rect(E0 + 900, N0 + 480, 8, 8),   None),
         ("b7", {"building": "garage"},                                               rect(E0 + 950, N0 + 480, 5, 5),   None),
         ("b8", {"building": "yes", "other_tags": '"roof:shape"=>"hipped"'},          rect(E0 + 400, N0 + 270, 9, 9),   (4.0, 5.0, 7.0, 40, 13.0, 12.9))]
    feats, keys, vals = [], [], []
    for k, (id, f, ring, st) in enumerate(B):
        g = G("POLYGON", [ring])
        mp.CreateFeature(ogr.Feature(mp.defn, {"osm_id": id, **f}, g))
        feats.append({"osm_id": id, "building": f.get("building"), "name": f.get("name"),
                      "levels": None, "other": f.get("other_tags"), "wkb": g.ExportToWkb()})
        if st: keys.append(k); vals.append(st)
    pickle.dump(feats, open(os.path.join(P["interim"], "_feats.pkl"), "wb"))
    np.save(os.path.join(P["interim"], "_stats_keys.npy"), np.array(keys))
    np.save(os.path.join(P["interim"], "_stats_vals.npy"), np.array(vals))

    pts = ogr.Layer("points", ["osm_id", "name", "other_tags"])          # no 'amenity' column -> other_tags path
    def node(id, x, y, ot):
        pts.CreateFeature(ogr.Feature(pts.defn, {"osm_id": id, "other_tags": ot}, G("POINT", (x, y))))
    node("n1", E0 + 300, N0 + 201, '"amenity"=>"waste_basket"')   # 1 m off a 7 m road: in carriageway
    node("n2", E0 + 300, N0 + 205, '"amenity"=>"waste_basket"')   # on the pavement
    node("n3", E0 + 300, N0 + 240, '"amenity"=>"waste_basket"')   # 40 m away: beyond snap
    node("n4", E0 - 50, N0 + 100, '"amenity"=>"waste_basket"')    # outside the grid
    node("n5", E0 + 310, N0 + 205, '"amenity"=>"bench"')          # not a mapped prop

    ds = ogr.DataSource(); ds.layers = {"lines": lines, "multipolygons": mp, "points": pts}
    osgeo.VECTORS[osgeo._norm(P["gpkg"])] = ds

    # ------------------------------------------------------------ run the steps
    for rel in ["derive/05_export_terrain.py", "derive/06_build_networks.py", "derive/07_massing.py",
                "derive/09_coast.py", "derive/10_furniture.py", "adapters/unity.py"]:
        print(f"\n=== {rel}")
        runpy.run_path(os.path.join(SRC, rel), run_name="__main__")

    out = P["out"]
    print("\n=== checks")

    # ---- 05 terrain
    tm = json.load(open(os.path.join(out, "terrain", "terrain_manifest.json")))
    check("05 manifest: crs, origin, true range, datum", tm["crs"] == "EPSG:27700" and tm["origin"]["E"] == E0
          and tm["range_m"][0] == -1.0 and abs(tm["range_m"][1] - z_at(E0 + 1024, N0 + 511)) < 0.01 and tm["vertical_datum"] == "TEST", str(tm["range_m"]))
    check("05 nodata cells counted on the patched tile only", [t["nodata_cells"] > 0 for t in tm["tiles"]] == [False, True])
    tiles = {(t["x"], t["y"]): gdal.Open(os.path.join(out, "terrain", t["file"])).GetRasterBand(1).ReadAsArray() for t in tm["tiles"]}
    check("05 -9999 never reaches the output", all(a.min() > -100 for a in tiles.values()))
    check("05 filled patch is plausible ground, not a hole", 20 < tiles[(1, 0)][80:110, 195:225].min() and tiles[(1, 0)][80:110, 195:225].max() < 50)
    check("05 output stays north-up (row 0 == north edge of the VRT)", np.array_equal(tiles[(0, 0)][0], Z[0, :RES]))
    check("05 shared seam column identical across tiles", np.array_equal(tiles[(0, 0)][:, -1], tiles[(1, 0)][:, 0]))
    check("05 fill method reported per tile", all(t["fill"] in ("median (degraded)", "nearest", "none") for t in tm["tiles"]))

    # ---- 06 roads
    roads = jl(os.path.join(out, "networks", "roads_*.jsonl"))
    segs = [r for r in roads if r["cls"] != "_junction"]
    by_id = {}
    for s in segs: by_id.setdefault(s["id"], []).append(s)
    check("06 vertices are [E, N, z] in CRS metres", all(len(v) == 3 and E0 <= v[0] <= E0 + NX * T for s in segs for v in s["pts"]))
    check("06 skipped 'construction' and unknown classes", "w6" not in by_id and "w7" not in by_id and "c1" not in by_id)
    check("06 lanes tag widened w1a to 7.0 m", by_id["w1a"][0]["w"] == 7.0)
    check("06 bridge/tunnel flags emitted", by_id["w4"][0]["bridge"] is True and by_id["w5"][0]["tunnel"] is True and by_id["w1a"][0]["bridge"] is False)
    w4z0 = by_id["w4"][0]["pts"][0][2]
    check("06 bridge z is honest ground, no +3 m", abs(w4z0 - z_at(E0 + 720, N0 + 380)) < 0.05, f"{w4z0} vs {z_at(E0+720, N0+380)}")
    check("06 -9999 patch: z carried forward, segment tagged z_gap", by_id["w4"][0]["z_gap"] is True and all(abs(v[2] - w4z0) < 0.05 for v in by_id["w4"][0]["pts"]))
    check("06 clean way has z_gap False", by_id["w1a"][0]["z_gap"] is False)
    w1a = sorted(by_id["w1a"], key=lambda s: s["pts"][0][0])
    check("06 seam: w1a split into 2 tiles with the seam vertex duplicated", len(w1a) == 2 and w1a[0]["pts"][-1] == w1a[1]["pts"][0])
    check("06 draped z follows the slope (no lift)", abs(w1a[0]["pts"][0][2] - z_at(E0 + 100, N0 + 200)) < 0.05)
    junc = [r for r in roads if r["cls"] == "_junction"]
    check("06 one junction disc where 3 ways meet", len(junc) == 1 and abs(junc[0]["pts"][0][0] - J[0]) < 0.2)
    nm = json.load(open(os.path.join(out, "networks", "networks_manifest.json")))
    check("06 manifest records smoothing, widths, nodata count", nm["smoothing"]["chaikin_iters"] == 2 and "residential" in nm["widths_m"] and nm["vertices_without_dtm"] > 0)

    # ---- 07 massing
    bl = jl(os.path.join(out, "massing", "buildings_*.jsonl")); bb = {b["id"]: b for b in bl}
    check("07 all 8 buildings emitted, incl. the 2 without LIDAR", len(bl) == 8 and bb["b6"]["base_z"] is None and bb["b6"]["lidar_px"] == 0)
    check("07 calibration comes from config: 3 levels -> 3.16+1.84*3", bb["b6"]["src"] == "osm_levels" and abs(bb["b6"]["h"] - 8.68) < 0.005, str(bb["b6"]["h"]))
    check("07 lidar_p50 when p50 agrees with levels", bb["b1"]["src"] == "lidar_p50" and bb["b1"]["h"] == 6.8)
    check("07 disputed when p50 is far from levels", bb["b3"]["src"] == "lidar_p50_disputed")
    check("07 lowconf under min_pixels", bb["b4"]["src"] == "lidar_lowconf")
    check("07 OSM height tag wins over LIDAR", bb["b5"]["src"] == "osm_height" and bb["b5"]["h"] == 8.5)
    check("07 type_prior only with no evidence at all", bb["b7"]["src"] == "type_prior" and bb["b7"]["h"] == 2.43)
    check("07 landmark override by name (h + roof)", bb["b2"]["src"] == "landmark_override" and bb["b2"]["h"] == 57.0 and bb["b2"]["roof"] == "flat")
    check("07 roof: tag > flat-type > default", bb["b8"]["roof"] == "hipped" and bb["b4"]["roof"] == "flat" and bb["b1"]["roof"] == "gabled")
    check("07 rings are CRS metres, not local", bb["b1"]["rings"][0]["pts"][0][0] == E0 + 150)
    check("07 skirt from tuning (dmin - 0.5)", bb["b1"]["skirt"] == 8.7 and bb["b1"]["eaves"] == 5.0 and bb["b1"]["ridge"] == 9.5)
    mm = json.load(open(os.path.join(out, "massing", "massing_manifest.json")))
    check("07 manifest: calib, no-LIDAR count, source histogram", mm["height_calib"]["m_per_level"] == 1.84 and mm["buildings_without_lidar"] == 2 and mm["by_height_source"]["type_prior"] == 1)

    # ---- 09 ground cover
    cm = json.load(open(os.path.join(out, "coast", "coast_manifest.json")))
    check("09 both tiles need water (sea strip)", sorted(map(tuple, cm["water_tiles"])) == [(0, 0), (1, 0)])
    g0 = gdal.Open(os.path.join(out, "coast", "ground_x0_y0.tif"))
    grass, sand, rock = (g0.GetRasterBand(i).ReadAsArray().astype(int) for i in (1, 2, 3))
    check("09 raster is north-up: sand (sea+beach) in the BOTTOM rows", sand[-10:].mean() > 240 and sand[:10].mean() < 10)
    cliff_row = (T - CLIFF_N) // 2
    check("09 rock at the cliff row, nowhere else", rock[cliff_row].max() > 200 and rock[:cliff_row - 2].max() == 0)
    check("09 bands sum to ~255 everywhere", int((grass + sand + rock).min()) >= 252)
    ggt = g0.GetGeoTransform()
    check("09 raster is georeferenced (origin, 2 m cells, north-up)", ggt[0] == E0 and ggt[3] == N0 + T and ggt[1] == 2.0 and ggt[5] == -2.0)
    check("09 manifest records thresholds and row order", cm["thresholds"]["foreshore_max_odn"] == 1.2 and "north" in cm["row_order"])

    # ---- 10 furniture
    fl = jl(os.path.join(out, "furniture", "furniture_*.jsonl")); ff = {r["id"]: r for r in fl}
    check("10 placed 3: outside-grid dropped, bench ignored", sorted(ff) == ["n1", "n2", "n3"])
    check("10 carriageway node nudged onto the kerb", ff["n1"]["nudged"] is True and ff["n1"]["src"] == "kerb" and abs(ff["n1"]["n"] - (N0 + 200 + 4.25)) < 0.01)
    check("10 pavement node: kerb, not nudged", ff["n2"]["src"] == "kerb" and ff["n2"]["nudged"] is False)
    check("10 far node: terrain, z null", ff["n3"]["src"] == "terrain" and ff["n3"]["z"] is None)
    check("10 bearing is compass: E-W road -> 90", all(0 <= r["bearing"] < 360 for r in fl) and abs(ff["n1"]["bearing"] - 90.0) < 0.5)
    check("10 kerb z = draped road z + kerb_m", abs(ff["n2"]["z"] - (z_at(E0 + 300, N0 + 200) + 0.12)) < 0.05)
    check("10 coordinates are CRS E/N", ff["n2"]["e"] == E0 + 300)
    qf = json.load(open(os.path.join(out, "qa_furniture.json")))
    check("10 qa: outside_grid 1, amenity kinds seen", qf["outside_grid"] == 1 and qf["amenity_kinds_seen"]["bench"] == 1)

    # ---- adapter
    U = os.path.join(out, "unity")
    raw = np.fromfile(os.path.join(U, "terrain", "hm_x0_y0.raw"), "<u2").reshape(RES, RES)
    expect = (np.flipud(np.clip((tiles[(0, 0)].astype(np.float64) + 5.0) / 60.0, 0, 1)) * 65535).round()
    check("adapter heightmap == flipud(normalised neutral tile)", np.abs(raw.astype(float) - expect).max() <= 1)
    ur = jl(os.path.join(U, "networks", "roads_*.jsonl")); u4 = [r for r in ur if r.get("id") == "w4"][0]
    check("adapter road z = neutral z + class lift + bridge offset", abs(u4["pts"][0][1] - (w4z0 + 0.22 + 3.0)) < 0.01, str(u4["pts"][0]))
    check("adapter road coords are local Y-up [x, y, z]", u4["pts"][0][0] == 720.0 and u4["pts"][0][2] == 380.0)
    check("adapter strips bridge/tunnel flags from Unity records", "bridge" not in u4)
    um = jl(os.path.join(U, "massing", "buildings_*.jsonl")); ub = {b["id"]: b for b in um}
    check("adapter massing: local rings, base_y", ub["b1"]["rings"][0]["pts"][0][0] == 150.0 and ub["b1"]["base_y"] == 9.4 and "base_z" not in ub["b1"])
    sp = gdal.Open(os.path.join(U, "coast", "splat_x0_y0.png"))
    check("adapter splat PNG == flipud(ground GeoTIFF)", np.array_equal(sp.GetRasterBand(2).ReadAsArray(), np.flipud(g0.GetRasterBand(2).ReadAsArray())))
    uf = {r["id"]: r for r in jl(os.path.join(U, "furniture", "furniture_*.jsonl"))}
    check("adapter furniture: x/z local, y=z, yaw==bearing", uf["n2"]["x"] == 300.0 and uf["n2"]["y"] == ff["n2"]["z"] and uf["n2"]["yaw"] == ff["n2"]["bearing"])
    ns = runpy.run_path(os.path.join(SRC, "adapters", "unity.py"), run_name="not_main")
    ns["ADP"]["terrain"]["y_size"] = 10.0
    try:
        ns["terrain"](); refused = False
    except SystemExit as e:
        refused = "does not fit" in str(e)
    check("adapter REFUSES a window that would clip terrain", refused)

    # ---- lib with real numpy
    a = np.array([[1, 2, 3], [4, ND, 6], [7, 8, 9]], float)
    bad = lib.nodata_mask(a, ND)
    check("lib.nodata_mask hits the declared sentinel only", bad.sum() == 1 and bad[1, 1])
    check("lib.nodata_mask: nan and -3.4e38 also caught", lib.nodata_mask(np.array([np.nan, -3.4e38, 1.0]), None).tolist() == [True, True, False])
    m = lib.fill_nodata(a, bad)
    check("lib.fill_nodata fills and names its method", a[1, 1] != ND and np.isfinite(a).all() and m in ("median (degraded)", "nearest"))
    check("lib.pixel_size / tile_px at 2 m", lib.pixel_size((0, 2, 0, 0, 0, -2)) == (2, 2) and lib.tile_px({"tile_m": 512}, (0, 2, 0, 0, 0, -2)) == (256, 256))
    try:
        lib.tile_px({"tile_m": 500}, (0, 3, 0, 0, 0, -3)); ok = False
    except SystemExit:
        ok = True
    check("lib.tile_px refuses a non-integer pixel fit", ok)

except Exception:
    traceback.print_exc()
    results.append(("HARNESS CRASHED", False))
finally:
    if os.path.exists(SITE_JSON): os.remove(SITE_JSON)
    for d in glob.glob(os.path.join(SRC, "**", "__pycache__"), recursive=True):
        shutil.rmtree(d, ignore_errors=True)
    if KEEP:
        print(f"\noutput kept at {ROOT}")
    else:
        shutil.rmtree(ROOT, ignore_errors=True)

fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
for n in fails: print("  FAILED:", n)
sys.exit(1 if fails else 0)
