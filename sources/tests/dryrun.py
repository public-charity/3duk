#!/usr/bin/env python3
"""Dry-run steps 05-10 and the Unity adapter against TWO synthetic sites.

    python3 sources/tests/dryrun.py            # needs numpy only -- no GDAL, no network
    python3 sources/tests/dryrun.py --keep     # leave the output directories for inspection

A fake in-memory GDAL/OGR (sources/tests/fake_osgeo) stands in for the real one, so this
runs on any machine with numpy. It proves the steps import, resolve config through lib,
agree with each other on file and field names, emit the schemas OUTPUT.md promises, and
that the fidelity fixes behave. Running two sites with different origins, pixel sizes,
grid sizes, coastlines and calibration modes is the proof that nothing about one site
leaked into the code.

  site A  coastal, 1 m pixels, 512 m tiles, 513 res, sea + cliff + beach, DTM hole,
          auto-fitted height calibration, landmark overrides, roads and buildings that
          stray off the grid, stale files from a "previous run" that must be cleared
  site B  inland, 2 m pixels, 512 m tiles, 257 res, different origin, no water anywhere,
          fixed height calibration, no landmarks, and a DTM that covers only 2 of the 3
          tile columns (the third is "beyond coverage")

It does NOT prove anything about GDAL itself -- rasterisation here is envelope-fill and
line clipping is vertex-keep -- and does not cover steps 01-04. lib.tiff_info is checked
against a real EA tile when one is present under data/.
"""
import glob, json, os, pickle, runpy, shutil, sys, tempfile, traceback
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
REPO = os.path.dirname(SRC)
sys.path.insert(0, os.path.join(HERE, "fake_osgeo"))
sys.path.insert(0, SRC)
import osgeo
from osgeo import gdal, ogr
import lib

KEEP = "--keep" in sys.argv
ROOT = tempfile.mkdtemp(prefix="3duk-dryrun-")
lib.ROOT = ROOT
SITES_DIR = os.path.join(SRC, "config", "sites")

results = []
def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok or not detail else f"   <- {detail}"))

def jl(pattern):
    return [json.loads(l) for p in sorted(glob.glob(pattern)) for l in open(p)]

EA_WCS = {"dtm": {"url": "x", "coverage": "x"}, "dsm": {"url": "x", "coverage": "x"}}
STEPS = ["derive/05_export_terrain.py", "derive/06_build_networks.py", "derive/07_massing.py",
         "derive/09_coast.py", "derive/10_furniture.py", "adapters/unity.py"]


def synth(site, cfg_extra, px, RES, NX, NY, zfun, nodata_patch=None, ways=(), beach=None,
          buildings=(), nodes=(), vrt_nx=None, decoys=False):
    """Write a site config, build the DTM/VRT/tiles/GeoPackage/interim in the fake GDAL,
    run the steps, and return what the checks need. vrt_nx limits how many tile columns
    the DTM covers (the rest are 'beyond coverage'); decoys plants stale output files."""
    E0, N0, T = cfg_extra["origin"]["E"], cfg_extra["origin"]["N"], 512
    ND = -9999.0
    vrt_nx = NX if vrt_nx is None else vrt_nx
    os.environ["SITE"] = site
    json.dump({"crs": "EPSG:27700", "tile_m": T, "nx": NX, "ny": NY, "grid_res": RES,
               "bbox_wgs84": [51.0, 1.0, 51.1, 1.1], "vertical_datum": "TEST", "wcs": EA_WCS,
               **cfg_extra}, open(os.path.join(SITES_DIR, f"{site}.json"), "w"), indent=1)
    cfg = lib.load(); P = lib.paths(cfg)
    lib.mkdirs(*[P[k] for k in ("raw", "interim", "derived", "out", "lidar")])
    if decoys:
        for sub, name in (("terrain", "dtm_x9_y9.tif"), ("networks", "roads_x9_y9.jsonl"),
                          ("massing", "buildings_x9_y9.jsonl"), ("coast", "ground_x9_y9.tif")):
            lib.mkdirs(os.path.join(P["out"], sub))
            open(os.path.join(P["out"], sub, name), "w").write("stale\n")

    tpx = T // px
    W, H = vrt_nx * tpx + 1, NY * tpx + 1
    gt = (E0 - px / 2, px, 0.0, N0 + NY * T + px / 2, 0.0, -px)
    EE, NN = np.meshgrid(E0 + px * np.arange(W), N0 + NY * T - px * np.arange(H))
    Z = zfun(EE, NN).astype(np.float32)
    if nodata_patch:
        e0, e1, n0, n1 = nodata_patch
        Z[(EE >= e0) & (EE < e1) & (NN >= n0) & (NN < n1)] = ND
    vrt = gdal.GetDriverByName("MEM").Create(os.path.join(P["interim"], "dtm.vrt"), W, H, 1, gdal.GDT_Float32)
    vrt.SetGeoTransform(gt); vrt.SetProjection("FAKE"); vrt.GetRasterBand(1).SetNoDataValue(ND)
    vrt.GetRasterBand(1).WriteArray(Z)
    for i in range(vrt_nx):
        for j in range(NY):
            c0, r0 = i * tpx, (NY - 1 - j) * tpx
            t = gdal.GetDriverByName("GTiff").Create(os.path.join(P["lidar"], f"dtm_x{i}_y{j}.tif"), RES, RES, 1, gdal.GDT_Float32)
            t.SetGeoTransform((E0 + i * T - px / 2, px, 0, N0 + (j + 1) * T + px / 2, 0, -px))
            t.GetRasterBand(1).SetNoDataValue(ND)
            t.GetRasterBand(1).WriteArray(Z[r0:r0 + RES, c0:c0 + RES])

    G = ogr.Geometry
    lines = ogr.Layer("lines", ["osm_id", "highway", "name", "other_tags"])
    for (id, cls, pts, name, ot) in ways:
        lines.CreateFeature(ogr.Feature(lines.defn, {"osm_id": id, "highway": cls, "name": name, "other_tags": ot}, G("LINESTRING", pts)))
    mp = ogr.Layer("multipolygons", ["osm_id", "building", "name", "natural", "other_tags"])
    if beach:
        mp.CreateFeature(ogr.Feature(mp.defn, {"osm_id": "beach", "natural": "beach"}, G("POLYGON", [beach])))
    feats, keys, vals = [], [], []
    for k, (id, f, ring, st) in enumerate(buildings):
        g = G("POLYGON", [ring])
        mp.CreateFeature(ogr.Feature(mp.defn, {"osm_id": id, **f}, g))
        feats.append({"osm_id": id, "building": f.get("building"), "name": f.get("name"),
                      "levels": None, "other": f.get("other_tags"), "wkb": g.ExportToWkb()})
        if st: keys.append(k); vals.append(st)
    pickle.dump(feats, open(os.path.join(P["interim"], "_feats.pkl"), "wb"))
    np.save(os.path.join(P["interim"], "_stats_keys.npy"), np.array(keys))
    np.save(os.path.join(P["interim"], "_stats_vals.npy"), np.array(vals))
    pts = ogr.Layer("points", ["osm_id", "name", "other_tags"])           # no 'amenity' column -> other_tags path
    for (id, x, y, ot) in nodes:
        pts.CreateFeature(ogr.Feature(pts.defn, {"osm_id": id, "other_tags": ot}, G("POINT", (x, y))))
    ds = ogr.DataSource(); ds.layers = {"lines": lines, "multipolygons": mp, "points": pts}
    osgeo.VECTORS[osgeo._norm(P["gpkg"])] = ds

    for rel in STEPS:
        print(f"\n=== [{site}] {rel}")
        runpy.run_path(os.path.join(SRC, rel), run_name="__main__")
    return dict(P=P, out=P["out"], Z=Z, E0=E0, N0=N0, T=T, NX=NX, NY=NY, RES=RES, px=px)


rect = lambda x, y, w, h: [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]

try:
    # ================================================================ site A: coastal, 1 m
    E0, N0, T, NX, NY, RES = 500000, 150000, 512, 2, 1, 513
    SLOPE, CLIFF_N, CLIFF_H, SEA_N, SEA_Z = 0.02, 306, 20.0, 60, -1.0
    def zA(EE, NN):
        Z = 5.0 + SLOPE * (EE - E0)
        Z = np.where(NN >= N0 + CLIFF_N, Z + CLIFF_H, Z)
        return np.where(NN < N0 + SEA_N, SEA_Z, Z)
    def z_at(e, n):
        z = 5.0 + SLOPE * (e - E0)
        if n >= N0 + CLIFF_N: z += CLIFF_H
        if n < N0 + SEA_N: z = SEA_Z
        return z
    J = (E0 + 600, N0 + 200)
    waysA = [
        ("w1a", "residential", [(E0 + 100, N0 + 200), J], "High Street", '"lanes"=>"2"'),   # crosses the seam
        ("w1b", "residential", [J, (E0 + 900, N0 + 250)], "High Street", None),
        ("w2", "footway", [J, (E0 + 600, N0 + 100)], None, None),                                 # third way at J
        ("w4", "primary", [(E0 + 720, N0 + 380), (E0 + 720, N0 + 460)], None, '"bridge"=>"yes"'),   # through the DTM hole
        ("w5", "tertiary", [(E0 + 50, N0 + 450), (E0 + 300, N0 + 450)], None, '"tunnel"=>"yes"'),
        ("w6", "construction", [(E0 + 10, N0 + 10), (E0 + 20, N0 + 20)], None, None),             # skipped class
        ("w7", "bus_guideway", [(E0 + 10, N0 + 30), (E0 + 20, N0 + 40)], None, None),            # not in widths
        ("w8", "residential", [(E0 - 200, N0 + 100), (E0 - 100, N0 + 100)], None, None),         # entirely off-grid
        ("w9", "footway", [(E0 - 50, N0 + 150), (E0 + 50, N0 + 150)], None, None),               # crosses the grid edge
        ("c1", None, [(E0 - 5000, N0 + SEA_N), (E0 + 200, N0 + SEA_N), (E0 + 3000, N0 + SEA_N)], None, '"natural"=>"coastline"'),
    ]
    #        id     fields                                                                  footprint                        (p25,p50,p90,npx,d15,dmin) or None
    bldA = [("b1", {"building": "house", "other_tags": '"building:levels"=>"2"'},           rect(E0 + 150, N0 + 220, 10, 8),  (5.0, 6.8, 9.5, 60, 9.4, 9.2)),
            ("b2", {"building": "apartments", "name": "Test Tower", "other_tags": '"building:levels"=>"10"'}, rect(E0 + 700, N0 + 150, 20, 20), (20.0, 21.0, 23.0, 300, 26.0, 25.5)),
            ("b3", {"building": "retail", "other_tags": '"building:levels"=>"3"'},          rect(E0 + 300, N0 + 230, 15, 15), (3.0, 3.2, 4.0, 100, 12.0, 11.8)),   # outlier
            ("b4", {"building": "shed"},                                                     rect(E0 + 50, N0 + 240, 3, 3),    (2.0, 2.4, 2.6, 3, 6.5, 6.4)),
            ("b5", {"building": "house", "other_tags": '"height"=>"8.5 m"'},                rect(E0 + 200, N0 + 260, 8, 8),   (1.0, 2.0, 3.0, 20, 11.0, 10.9)),
            ("b6", {"building": "terrace", "other_tags": '"building:levels"=>"3"'},         rect(E0 + 900, N0 + 480, 8, 8),   None),
            ("b7", {"building": "garage"},                                                   rect(E0 + 950, N0 + 480, 5, 5),   None),
            ("b8", {"building": "yes", "other_tags": '"roof:shape"=>"hipped"'},              rect(E0 + 400, N0 + 270, 9, 9),   (4.0, 5.0, 7.0, 40, 13.0, 12.9)),
            # clean calibration points: h = 3 + 2*levels
            ("b9",  {"building": "house", "other_tags": '"building:levels"=>"1"'},          rect(E0 + 100, N0 + 300, 8, 8),   (4.0, 5.0, 6.0, 50, 11.0, 10.9)),
            ("b10", {"building": "house", "other_tags": '"building:levels"=>"2"'},          rect(E0 + 120, N0 + 300, 8, 8),   (6.0, 7.0, 8.0, 50, 11.0, 10.9)),
            ("b11", {"building": "house", "other_tags": '"building:levels"=>"3"'},          rect(E0 + 140, N0 + 300, 8, 8),   (8.0, 9.0, 10.0, 50, 11.0, 10.9)),
            ("b12", {"building": "house", "other_tags": '"building:levels"=>"4"'},          rect(E0 + 160, N0 + 300, 8, 8),   (10.0, 11.0, 12.0, 50, 11.0, 10.9)),
            ("b13", {"building": "house"},                                                   rect(E0 - 100, N0 + 100, 8, 8),   (4.0, 5.0, 6.0, 50, 3.0, 2.9))]   # off-grid
    nodesA = [("n1", E0 + 300, N0 + 201, '"amenity"=>"waste_basket"'),   # 1 m off a 7 m road: in carriageway
              ("n2", E0 + 300, N0 + 205, '"amenity"=>"waste_basket"'),   # on the pavement
              ("n3", E0 + 300, N0 + 240, '"amenity"=>"waste_basket"'),   # 40 m away: beyond snap
              ("n4", E0 - 50, N0 + 100, '"amenity"=>"waste_basket"'),    # outside the grid
              ("n5", E0 + 310, N0 + 205, '"amenity"=>"bench"')]          # not a mapped prop
    A = synth("_dryrun_a", {
        "origin": {"E": E0, "N": N0}, "water_level": SEA_Z,
        "height_calib": {"mode": "auto", "min_buildings": 3, "fallback": {"intercept": 9.9, "m_per_level": 9.9}, "dispute_m": 4.0},
        "coast": {"foreshore_max_odn": 1.2, "rock_slope_deg": [22.0, 40.0], "water_margin_m": 0.75, "water_tolerance_m": 0.3},
        "landmarks": {"_note": "test", "Test Tower": {"h_body": 57.0, "roof": "flat"}, "Never Matches": {"h_body": 1.0}},
    }, px=1, RES=RES, NX=NX, NY=NY, zfun=zA, nodata_patch=(E0 + 700, E0 + 740, N0 + 400, N0 + 440),
       ways=waysA, beach=rect(E0, N0 + SEA_N, 400, 60), buildings=bldA, nodes=nodesA, decoys=True)
    out, Z = A["out"], A["Z"]
    print("\n=== checks: site A")

    # ---- stale outputs
    check("A   stale files from a previous run are cleared by every step",
          not any(glob.glob(os.path.join(out, sub, "*x9_y9*")) for sub in ("terrain", "networks", "massing", "coast")))

    # ---- 05 terrain
    tm = json.load(open(os.path.join(out, "terrain", "terrain_manifest.json")))
    check("A05 manifest: crs, origin, true range, datum, no missing tiles", tm["crs"] == "EPSG:27700" and tm["origin"]["E"] == E0
          and tm["range_m"][0] == SEA_Z and abs(tm["range_m"][1] - z_at(E0 + 1024, N0 + 511)) < 0.01 and tm["vertical_datum"] == "TEST"
          and tm["tiles_missing"] == [], str(tm["range_m"]))
    check("A05 nodata cells counted on the patched tile only", [t["nodata_cells"] > 0 for t in tm["tiles"]] == [False, True])
    tiles = {(t["x"], t["y"]): gdal.Open(os.path.join(out, "terrain", t["file"])).GetRasterBand(1).ReadAsArray() for t in tm["tiles"]}
    check("A05 -9999 never reaches the output", all(a.min() > -100 for a in tiles.values()))
    check("A05 filled patch is plausible ground, not a hole", 20 < tiles[(1, 0)][80:110, 195:225].min() and tiles[(1, 0)][80:110, 195:225].max() < 50)
    check("A05 output stays north-up (row 0 == north edge of the VRT)", np.array_equal(tiles[(0, 0)][0], Z[0, :RES]))
    check("A05 shared seam column identical across tiles", np.array_equal(tiles[(0, 0)][:, -1], tiles[(1, 0)][:, 0]))
    check("A05 fill method reported per tile", all(t["fill"] in ("median (degraded)", "nearest", "none") for t in tm["tiles"]))
    check("A05 slope QA: the 20 m/1 m cliff survives as ~87 deg", tm["slope_qa"]["max_deg"] > 85 and all("slope_max_deg" in t for t in tm["tiles"]), str(tm["slope_qa"]))

    # ---- 06 roads
    roads = jl(os.path.join(out, "networks", "roads_*.jsonl"))
    segs = [r for r in roads if r["cls"] != "_junction"]
    by_id = {}
    for s in segs: by_id.setdefault(s["id"], []).append(s)
    check("A06 vertices are [E, N, z] in CRS metres", all(len(v) == 3 and E0 <= v[0] <= E0 + NX * T for s in segs for v in s["pts"]))
    check("A06 skipped 'construction' and unknown classes", "w6" not in by_id and "w7" not in by_id and "c1" not in by_id)
    check("A06 off-grid way dropped; edge-crossing way clipped to the grid", "w8" not in by_id and "w9" in by_id and all(v[0] >= E0 for v in by_id["w9"][0]["pts"]))
    check("A06 no tile files with negative indices", not glob.glob(os.path.join(out, "networks", "roads_x-*.jsonl")))
    check("A06 lanes tag widened w1a to 7.0 m", by_id["w1a"][0]["w"] == 7.0)
    check("A06 bridge/tunnel flags emitted", by_id["w4"][0]["bridge"] is True and by_id["w5"][0]["tunnel"] is True and by_id["w1a"][0]["bridge"] is False)
    w4z0 = by_id["w4"][0]["pts"][0][2]
    check("A06 bridge z is honest ground, no +3 m", abs(w4z0 - z_at(E0 + 720, N0 + 380)) < 0.05, f"{w4z0} vs {z_at(E0+720, N0+380)}")
    check("A06 DTM hole: z filled from neighbours, segment tagged z_gap", by_id["w4"][0]["z_gap"] is True and all(abs(v[2] - w4z0) < 0.05 for v in by_id["w4"][0]["pts"]))
    check("A06 clean way has z_gap False", by_id["w1a"][0]["z_gap"] is False)
    w1a = sorted(by_id["w1a"], key=lambda s: s["pts"][0][0])
    check("A06 seam: w1a split into 2 tiles with the seam vertex duplicated", len(w1a) == 2 and w1a[0]["pts"][-1] == w1a[1]["pts"][0])
    check("A06 draped z follows the slope (no lift)", abs(w1a[0]["pts"][0][2] - z_at(E0 + 100, N0 + 200)) < 0.05)
    junc = [r for r in roads if r["cls"] == "_junction"]
    check("A06 one junction disc where 3 ways meet", len(junc) == 1 and abs(junc[0]["pts"][0][0] - J[0]) < 0.2)
    nm = json.load(open(os.path.join(out, "networks", "networks_manifest.json")))
    check("A06 manifest records smoothing, widths, nodata + off-grid counts", nm["smoothing"]["chaikin_iters"] == 2 and "residential" in nm["widths_m"]
          and nm["vertices_without_dtm"] > 0 and nm["vertices_outside_grid"] > 0)

    # ---- 07 massing
    bl = jl(os.path.join(out, "massing", "buildings_*.jsonl")); bb = {b["id"]: b for b in bl}
    mm = json.load(open(os.path.join(out, "massing", "massing_manifest.json")))
    cal = mm["height_calib"]
    check("A07 12 buildings emitted (off-grid b13 dropped), incl. the 2 without LIDAR", len(bl) == 12 and "b13" not in bb and mm["outside_grid"] == 1
          and bb["b6"]["base_z"] is None and bb["b6"]["lidar_px"] == 0)
    check("A07 calibration FITTED from the site's own buildings, outlier rejected", cal["source"] == "fitted" and mm["height_calib_fit"]["n"] == 6
          and mm["height_calib_fit"]["rejected"] == 1 and 1.6 < cal["m_per_level"] < 2.0 and 2.5 < cal["intercept"] < 4.5, str(cal) + str(mm["height_calib_fit"]))
    check("A07 osm_levels rung uses the fitted line, not the fallback", bb["b6"]["src"] == "osm_levels"
          and abs(bb["b6"]["h"] - (cal["intercept"] + 3 * cal["m_per_level"])) < 0.01 and abs(bb["b6"]["h"] - (9.9 + 3 * 9.9)) > 1)
    check("A07 lidar_p50 when p50 agrees with levels", bb["b1"]["src"] == "lidar_p50" and bb["b1"]["h"] == 6.8)
    check("A07 disputed when p50 is far from the fitted line", bb["b3"]["src"] == "lidar_p50_disputed")
    check("A07 lowconf under min_pixels", bb["b4"]["src"] == "lidar_lowconf")
    check("A07 OSM height tag wins over LIDAR", bb["b5"]["src"] == "osm_height" and bb["b5"]["h"] == 8.5)
    check("A07 type_prior only with no evidence at all", bb["b7"]["src"] == "type_prior" and bb["b7"]["h"] == 2.43)
    check("A07 landmark override by name (h + roof)", bb["b2"]["src"] == "landmark_override" and bb["b2"]["h"] == 57.0 and bb["b2"]["roof"] == "flat")
    check("A07 roof: tag > flat-type > default", bb["b8"]["roof"] == "hipped" and bb["b4"]["roof"] == "flat" and bb["b1"]["roof"] == "gabled")
    check("A07 rings are CRS metres, not local", bb["b1"]["rings"][0]["pts"][0][0] == E0 + 150)
    check("A07 skirt from tuning (dmin - 0.5)", bb["b1"]["skirt"] == 8.7 and bb["b1"]["eaves"] == 5.0 and bb["b1"]["ridge"] == 9.5)
    check("A07 manifest: no-LIDAR count, source histogram", mm["buildings_without_lidar"] == 2 and mm["by_height_source"]["type_prior"] == 1)

    # ---- 09 ground cover
    cm = json.load(open(os.path.join(out, "coast", "coast_manifest.json")))
    check("A09 both tiles need water (sea strip); none without DTM", sorted(map(tuple, cm["water_tiles"])) == [(0, 0), (1, 0)] and cm["tiles_without_dtm"] == [])
    g0 = gdal.Open(os.path.join(out, "coast", "ground_x0_y0.tif"))
    check("A09 four bands: grass, sand, rock, water", g0.RasterCount == 4 and cm["bands"] == ["grass", "sand", "rock", "water"])
    grass, sand, rock, water = (g0.GetRasterBand(i).ReadAsArray().astype(int) for i in (1, 2, 3, 4))
    sea_rows, beach_rows = SEA_N // 2, (SEA_N + 60) // 2
    # The sea/land boundary at N0+60 falls inside the northernmost sea cell (2 m cells over
    # integer-centred 1 m samples), so that one row is legitimately half water, half land.
    check("A09 north-up: the DTM's flat sea is WATER in the bottom rows, not sand; boundary cell is mixed",
          water[-(sea_rows - 1):].min() == 255 and sand[-(sea_rows - 1):].max() == 0
          and 100 <= water[-sea_rows].max() <= 160 and water[:-sea_rows].max() == 0)
    check("A09 OSM beach polygon is sand, just above the water", sand[-beach_rows:-sea_rows, :200].min() == 255 and sand[:10].max() == 0)
    cliff_row = (T - CLIFF_N) // 2
    check("A09 rock at the cliff row, nowhere else", rock[cliff_row].max() > 200 and rock[:cliff_row - 2].max() == 0)
    check("A09 bands sum to ~255 everywhere", int((grass + sand + rock + water).min()) >= 252)
    ggt = g0.GetGeoTransform()
    check("A09 raster is georeferenced (origin, 2 m cells, north-up)", ggt[0] == E0 and ggt[3] == N0 + T and ggt[1] == 2.0 and ggt[5] == -2.0)
    check("A09 manifest records thresholds, tolerance and row order", cm["thresholds"]["foreshore_max_odn"] == 1.2 and cm["water_tolerance_m"] == 0.3 and "north" in cm["row_order"])

    # ---- 10 furniture
    fl = jl(os.path.join(out, "furniture", "furniture_*.jsonl")); ff = {r["id"]: r for r in fl}
    check("A10 placed 3: outside-grid dropped, bench ignored", sorted(ff) == ["n1", "n2", "n3"])
    check("A10 carriageway node nudged onto the kerb", ff["n1"]["nudged"] is True and ff["n1"]["src"] == "kerb" and abs(ff["n1"]["n"] - (N0 + 200 + 4.25)) < 0.01)
    check("A10 pavement node: kerb, not nudged", ff["n2"]["src"] == "kerb" and ff["n2"]["nudged"] is False)
    check("A10 far node: terrain, z null", ff["n3"]["src"] == "terrain" and ff["n3"]["z"] is None)
    check("A10 bearing is compass: E-W road -> 90", all(0 <= r["bearing"] < 360 for r in fl) and abs(ff["n1"]["bearing"] - 90.0) < 0.5)
    check("A10 kerb z = draped road z + kerb_m", abs(ff["n2"]["z"] - (z_at(E0 + 300, N0 + 200) + 0.12)) < 0.05)
    check("A10 coordinates are CRS E/N", ff["n2"]["e"] == E0 + 300)
    qf = json.load(open(os.path.join(out, "qa_furniture.json")))
    check("A10 qa: outside_grid 1, amenity kinds seen", qf["outside_grid"] == 1 and qf["amenity_kinds_seen"]["bench"] == 1)

    # ---- adapter
    U = os.path.join(out, "unity")
    um_t = json.load(open(os.path.join(U, "terrain", "terrain_manifest.json")))
    yb, ys = um_t["y_base"], um_t["y_size"]
    check("adapter auto window: floor(min-5) .. ceil(max+5), shared by all tiles", yb == -6.0 and ys == 57.0, f"{yb} {ys}")
    raw = np.fromfile(os.path.join(U, "terrain", "hm_x0_y0.raw"), "<u2").reshape(RES, RES)
    expect = (np.flipud(np.clip((tiles[(0, 0)].astype(np.float64) - yb) / ys, 0, 1)) * 65535).round()
    check("adapter heightmap == flipud(normalised neutral tile)", np.abs(raw.astype(float) - expect).max() <= 1)
    ur = jl(os.path.join(U, "networks", "roads_*.jsonl")); u4 = [r for r in ur if r.get("id") == "w4"][0]
    check("adapter road z = neutral z + class lift + bridge offset", abs(u4["pts"][0][1] - (w4z0 + 0.22 + 3.0)) < 0.01, str(u4["pts"][0]))
    check("adapter road coords are local Y-up [x, y, z]", u4["pts"][0][0] == 720.0 and u4["pts"][0][2] == 380.0)
    check("adapter strips bridge/tunnel flags from Unity records", "bridge" not in u4)
    um = jl(os.path.join(U, "massing", "buildings_*.jsonl")); ub = {b["id"]: b for b in um}
    check("adapter massing: local rings, base_y", ub["b1"]["rings"][0]["pts"][0][0] == 150.0 and ub["b1"]["base_y"] == 9.4 and "base_z" not in ub["b1"])
    sp = gdal.Open(os.path.join(U, "coast", "splat_x0_y0.png"))
    spg, sps, spk = (sp.GetRasterBand(i).ReadAsArray().astype(int) for i in (1, 2, 3))
    check("adapter splat: 3 bands summing to 255, sand == flipud(neutral sand), grass fills under water", sp.RasterCount == 3
          and np.array_equal(sps, np.flipud(g0.GetRasterBand(2).ReadAsArray()).astype(int))
          and (spg + sps + spk).min() >= 253 and spg[:sea_rows - 2].min() == 255)
    wm = gdal.Open(os.path.join(U, "coast", "water_x0_y0.png"))
    check("adapter water mask PNG == flipud(neutral water band)", np.array_equal(wm.GetRasterBand(1).ReadAsArray(), np.flipud(g0.GetRasterBand(4).ReadAsArray())))
    uf = {r["id"]: r for r in jl(os.path.join(U, "furniture", "furniture_*.jsonl"))}
    check("adapter furniture: x/z local, y=z, yaw==bearing", uf["n2"]["x"] == 300.0 and uf["n2"]["y"] == ff["n2"]["z"] and uf["n2"]["yaw"] == ff["n2"]["bearing"])
    ns = runpy.run_path(os.path.join(SRC, "adapters", "unity.py"), run_name="not_main")
    ns["ADP"]["terrain"]["y_base"] = -5.0; ns["ADP"]["terrain"]["y_size"] = 10.0
    try:
        ns["terrain"](); refused = False
    except SystemExit as e:
        refused = "does not fit" in str(e)
    check("adapter REFUSES a pinned window that would clip terrain", refused)

    # ================================================================ site B: inland, 2 m, DTM covers 2 of 3 columns
    E0b, N0b, NXb, NYb, RESb = 300000, 700000, 3, 2, 257
    def zB(EE, NN):
        return 100.0 + 0.05 * (EE - E0b) + 0.01 * (NN - N0b)
    def zb_at(e, n): return 100.0 + 0.05 * (e - E0b) + 0.01 * (n - N0b)
    waysB = [("r1", "primary", [(E0b + 100, N0b + 300), (E0b + 1400, N0b + 300)], "Long Road", '"lanes"=>"4"'),   # runs into the uncovered column
             ("r2", "footway", [(E0b + 500, N0b + 300), (E0b + 500, N0b + 900)], None, None)]
    bldB = [("k1", {"building": "house", "other_tags": '"building:levels"=>"2"'}, rect(E0b + 200, N0b + 320, 10, 10), (4.0, 6.0, 8.0, 40, 105.0, 104.8)),
            ("k2", {"building": "house", "other_tags": '"building:levels"=>"2"'}, rect(E0b + 900, N0b + 700, 10, 10), None)]   # no LIDAR -> fixed calib
    nodesB = [("m1", E0b + 300, N0b + 305, '"amenity"=>"waste_basket"'), ("m2", E0b + 300, N0b + 400, '"amenity"=>"bench"')]
    B = synth("_dryrun_b", {
        "origin": {"E": E0b, "N": N0b}, "water_level": -50.0,
        "height_calib": {"mode": "fixed", "intercept": 2.5, "m_per_level": 3.0, "dispute_m": 4.0},
        "coast": {"foreshore_max_odn": -50.0, "rock_slope_deg": [25.0, 45.0], "water_margin_m": 0.75},
        "landmarks": {},
    }, px=2, RES=RESb, NX=NXb, NY=NYb, zfun=zB, ways=waysB, buildings=bldB, nodes=nodesB, vrt_nx=2)
    outb, Zb = B["out"], B["Z"]
    print("\n=== checks: site B")
    tmb = json.load(open(os.path.join(outb, "terrain", "terrain_manifest.json")))
    check("B05 4 tiles at 257x257 from 2 m pixels; the uncovered column is listed as missing", len(tmb["tiles"]) == 4 and tmb["res"] == 257
          and tmb["tiles_missing"] == [[2, 0], [2, 1]] and abs(tmb["range_m"][0] - 100.0) < 0.01, str(tmb["tiles_missing"]))
    tb = gdal.Open(os.path.join(outb, "terrain", "dtm_x0_y1.tif")).GetRasterBand(1).ReadAsArray()
    check("B05 tile content matches the VRT at 2 m (north tile, north-west corner)", tb.shape == (257, 257) and np.array_equal(tb[0], Zb[0, :257]))
    check("B05 slope QA reflects a gentle site (max ~3 deg), not site A's cliff", tmb["slope_qa"]["max_deg"] < 5 and tmb["slope_qa"]["pct_cells_over_45deg"] == 0)
    rb = jl(os.path.join(outb, "networks", "roads_*.jsonl")); segb = [r for r in rb if r["cls"] != "_junction"]
    r1 = sorted([s for s in segb if s["id"] == "r1"], key=lambda s: s["pts"][0][0])
    check("B06 road split across 3 tiles at a different origin, lanes=4 -> 13 m", len(r1) == 3 and r1[0]["w"] == 13.0 and all(E0b <= v[0] <= E0b + 1536 for s in r1 for v in s["pts"]))
    check("B06 draped on the 2 m DTM (z follows the plane)", abs(r1[0]["pts"][0][2] - zb_at(E0b + 100, N0b + 300)) < 0.06)
    edge_z = zb_at(E0b + 1024, N0b + 300)
    check("B06 beyond the DTM: NOT clamped to the edge pixel -- z carried from the last covered vertex, z_gap set",
          r1[2]["z_gap"] is True and all(abs(v[2] - edge_z) < 0.5 for v in r1[2]["pts"]) and r1[0]["z_gap"] is False, str(r1[2]["pts"][-1]))
    nmb = json.load(open(os.path.join(outb, "networks", "networks_manifest.json")))
    check("B06 manifest counts the uncovered vertices as DTM gaps, none off-grid", nmb["vertices_without_dtm"] > 0 and nmb["vertices_outside_grid"] == 0)
    kb = {b["id"]: b for b in jl(os.path.join(outb, "massing", "buildings_*.jsonl"))}
    mmb = json.load(open(os.path.join(outb, "massing", "massing_manifest.json")))
    check("B07 FIXED calibration from config, recorded as such", mmb["height_calib"]["source"] == "config" and mmb["height_calib"]["intercept"] == 2.5)
    check("B07 no-LIDAR building gets 2.5 + 3.0*2 = 8.5 via osm_levels", kb["k2"]["src"] == "osm_levels" and kb["k2"]["h"] == 8.5 and kb["k2"]["base_z"] is None)
    check("B07 rings in this site's CRS range, not site A's", 300000 <= kb["k1"]["rings"][0]["pts"][0][0] < 302000)
    cmb = json.load(open(os.path.join(outb, "coast", "coast_manifest.json")))
    gb = gdal.Open(os.path.join(outb, "coast", "ground_x1_y0.tif"))
    check("B09 inland: no water tiles, no sand, no rock, no water -- all grass", cmb["water_tiles"] == [] and gb.GetRasterBand(2).ReadAsArray().max() == 0
          and gb.GetRasterBand(3).ReadAsArray().max() == 0 and gb.GetRasterBand(4).ReadAsArray().max() == 0 and gb.GetRasterBand(1).ReadAsArray().min() == 255)
    check("B09 uncovered column: no raster, listed as tiles_without_dtm, NOT assumed to be sea",
          cmb["tiles_without_dtm"] == [[2, 0], [2, 1]] and not glob.glob(os.path.join(outb, "coast", "ground_x2_*.tif")) and cmb["missing_tiles_are_water"] is False)
    check("B09 georeferenced at the 2 m site: 256 cells of 2 m per tile", gb.GetGeoTransform()[0] == E0b + 512 and gb.GetGeoTransform()[1] == 2.0 and gb.RasterXSize == 256)
    fb = {r["id"]: r for r in jl(os.path.join(outb, "furniture", "furniture_*.jsonl"))}
    check("B10 one bin placed on the kerb of the 13 m road, bench ignored", list(fb) == ["m1"] and fb["m1"]["src"] == "kerb" and fb["m1"]["cls"] == "primary")
    umb = json.load(open(os.path.join(outb, "unity", "terrain", "terrain_manifest.json")))
    ybb, ysb = umb["y_base"], umb["y_size"]
    # only the covered columns exist, so the range tops out at E0b+1024: 161.4 m -> ceil(166.4) = 167
    check("B-adapter auto window follows THIS site's covered range (95 .. 167); 4 heightmaps", ybb == 95.0 and ysb == 72.0
          and len(glob.glob(os.path.join(outb, "unity", "terrain", "hm_*.raw"))) == 4, f"{ybb} {ysb}")
    rawb = np.fromfile(os.path.join(outb, "unity", "terrain", "hm_x0_y1.raw"), "<u2").reshape(257, 257)
    expb = (np.flipud(np.clip((tb.astype(np.float64) - ybb) / ysb, 0, 1)) * 65535).round()
    check("B-adapter heightmap correct at 257 res", np.abs(rawb.astype(float) - expb).max() <= 1)

    # ---- lib with real numpy
    a = np.array([[1, 2, 3], [4, -9999.0, 6], [7, 8, 9]], float)
    bad = lib.nodata_mask(a, -9999.0)
    check("lib.nodata_mask hits the declared sentinel only", bad.sum() == 1 and bad[1, 1])
    check("lib.nodata_mask: nan and -3.4e38 also caught", lib.nodata_mask(np.array([np.nan, -3.4e38, 1.0]), None).tolist() == [True, True, False])
    m = lib.fill_nodata(a, bad)
    check("lib.fill_nodata fills and names its method", a[1, 1] != -9999.0 and np.isfinite(a).all() and m in ("median (degraded)", "nearest"))
    check("lib.pixel_size / tile_px at 2 m", lib.pixel_size((0, 2, 0, 0, 0, -2)) == (2, 2) and lib.tile_px({"tile_m": 512}, (0, 2, 0, 0, 0, -2)) == (256, 256))
    try:
        lib.tile_px({"tile_m": 500}, (0, 3, 0, 0, 0, -3)); ok = False
    except SystemExit:
        ok = True
    check("lib.tile_px refuses a non-integer pixel fit", ok)
    os.environ.pop("SITE", None)
    try:
        lib.site_name(); ambiguous = False
    except SystemExit:
        ambiguous = True
    check("lib.site_name refuses to guess when several sites are configured", ambiguous)
    check("lib.tiff_info: not-a-TIFF and empty file -> None",
          lib.tiff_info(os.path.abspath(__file__)) is None and lib.tiff_info(os.path.join(SRC, "config", "tuning.json")) is None)
    real = sorted(glob.glob(os.path.join(REPO, "data", "*", "raw", "lidar", "dtm_x0_y0.tif")))
    if real:
        info = lib.tiff_info(real[0])
        check(f"lib.tiff_info on a REAL EA tile ({os.path.relpath(real[0], REPO)}): 513x513 float32, nodata -3.4e38",
              info == {"width": 513, "height": 513, "dtype": "float32", "nodata": info["nodata"]} and info["nodata"] is not None and info["nodata"] < -1e30, str(info))
    else:
        print("  SKIP  lib.tiff_info on a real EA tile (none under data/)")

except Exception:
    traceback.print_exc()
    results.append(("HARNESS CRASHED", False))
finally:
    for s in ("_dryrun_a", "_dryrun_b"):
        p = os.path.join(SITES_DIR, f"{s}.json")
        if os.path.exists(p): os.remove(p)
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
