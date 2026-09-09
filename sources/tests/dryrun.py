#!/usr/bin/env python3
"""Dry-run steps 05-11 and the adapters against THREE synthetic sites.

    python3 sources/tests/dryrun.py            # needs numpy only -- no GDAL, no network
    python3 sources/tests/dryrun.py --keep     # leave the output directories for inspection

A fake in-memory GDAL/OGR (sources/tests/fake_osgeo) stands in for the real one, so this
runs on any machine with numpy. It proves the steps import, resolve config through lib,
agree with each other on file and field names, emit the schemas OUTPUT.md promises, and
that the fidelity fixes behave. Running three sites with different origins, pixel sizes,
grid sizes, coastlines, calibration modes and one clip line is the proof that nothing
about one site leaked into the code.

  site A  coastal, 1 m pixels, 512 m tiles, 513 res, sea + cliff + beach, DTM hole,
          auto-fitted height calibration, landmark overrides, roads and buildings that
          stray off the grid, stale files from a "previous run" that must be cleared,
          no railway or barrier ways (step 11 must say so and write empty counts)
  site B  inland, 2 m pixels, 512 m tiles, 257 res, different origin, no water anywhere,
          fixed height calibration, no landmarks, and a DTM that covers only 2 of the 3
          tile columns (the third is "beyond coverage")
  site C  1 m, 3 x 2 tiles, a diagonal clip line (kept iff local x + y >= 1100,
          PIPELINE_CHANGES.md 8.2): one tile wholly outside (and without a raw tile), four
          straddling it, one inside; roads, a rail drawn along a road, barriers, a building
          and a node on each side of the line. The clip API is also exercised at lib level
          ("C-lib" checks) against site A's step-06 output (drape_runs equivalence) and the
          real sources/config/sites/thanet.json.

The Unreal adapter (sources/adapters/unreal.py) is run on all three sites when the file
exists; when it does not, its checks are SKIPPED loudly and counted as skipped, never as
passed. It does NOT prove anything about GDAL itself -- rasterisation here is envelope-fill
and line clipping is vertex-keep -- and does not cover steps 01-04 (02's clip skipping is
checked at lib level). lib.tiff_info is checked against real EA and GDAL-written tiles when
they are present under data/.
"""
import glob, json, math, os, pickle, re, runpy, shutil, sys, tempfile, traceback
from collections import Counter
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

results, skipped = [], []
def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok or not detail else f"   <- {detail}"))

def skip(name, why):
    """A check that could not run. Counted as skipped -- never as passed."""
    skipped.append(name)
    print(f"  SKIP  {name}   <- {why}")

def jl(pattern):
    return [json.loads(l) for p in sorted(glob.glob(pattern)) for l in open(p)]

def jl_tiles(pattern):
    """{(i, j): [records]} keyed by the tile in the file name."""
    out = {}
    for p in sorted(glob.glob(pattern)):
        mt = re.search(r"_x(\d+)_y(\d+)\.jsonl$", p)
        out[(int(mt.group(1)), int(mt.group(2)))] = [json.loads(l) for l in open(p)]
    return out

EA_WCS = {"dtm": {"url": "x", "coverage": "x"}, "dsm": {"url": "x", "coverage": "x"}}
ADAPTER = "adapters/unreal.py"          # the adapter task's file; run when present, SKIPPED loudly when not
STEPS = ["derive/05_export_terrain.py", "derive/06_build_networks.py", "derive/07_massing.py",
         "derive/09_coast.py", "derive/10_furniture.py", "derive/11_linear_features.py",
         "adapters/unity.py", ADAPTER]
adapter_ran = {}                        # site -> True (ran), False (crashed), None (file absent)


def synth(site, cfg_extra, px, RES, NX, NY, zfun, nodata_patch=None, ways=(), beach=None,
          buildings=(), nodes=(), vrt_nx=None, decoys=False, rails=(), barriers=(), skip_tiles=()):
    """Write a site config, build the DTM/VRT/tiles/GeoPackage/interim in the fake GDAL,
    run the steps, and return what the checks need. vrt_nx limits how many tile columns
    the DTM covers (the rest are 'beyond coverage'); skip_tiles are positions with no raw
    tile whose VRT region is nodata; decoys plants stale output files; rails / barriers are
    (id, value, pts, name, other_tags) ways with railway / barrier set instead of highway."""
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
                          ("networks", "rail_x9_y9.jsonl"), ("networks", "barriers_x9_y9.jsonl"),
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
    for (si, sj) in skip_tiles:         # the shared edge row/column belongs to the neighbours
        Z[(EE >= E0 + si * T) & (EE < E0 + (si + 1) * T) & (NN >= N0 + sj * T) & (NN < N0 + (sj + 1) * T)] = ND
    vrt = gdal.GetDriverByName("MEM").Create(os.path.join(P["interim"], "dtm.vrt"), W, H, 1, gdal.GDT_Float32)
    vrt.SetGeoTransform(gt); vrt.SetProjection("FAKE"); vrt.GetRasterBand(1).SetNoDataValue(ND)
    vrt.GetRasterBand(1).WriteArray(Z)
    for i in range(vrt_nx):
        for j in range(NY):
            if (i, j) in skip_tiles: continue
            c0, r0 = i * tpx, (NY - 1 - j) * tpx
            t = gdal.GetDriverByName("GTiff").Create(os.path.join(P["lidar"], f"dtm_x{i}_y{j}.tif"), RES, RES, 1, gdal.GDT_Float32)
            t.SetGeoTransform((E0 + i * T - px / 2, px, 0, N0 + (j + 1) * T + px / 2, 0, -px))
            t.GetRasterBand(1).SetNoDataValue(ND)
            t.GetRasterBand(1).WriteArray(Z[r0:r0 + RES, c0:c0 + RES])

    G = ogr.Geometry
    lines = ogr.Layer("lines", ["osm_id", "highway", "railway", "barrier", "name", "other_tags"])
    for (id, cls, pts, name, ot) in ways:
        lines.CreateFeature(ogr.Feature(lines.defn, {"osm_id": id, "highway": cls, "name": name, "other_tags": ot}, G("LINESTRING", pts)))
    for (id, cls, pts, name, ot) in rails:
        lines.CreateFeature(ogr.Feature(lines.defn, {"osm_id": id, "railway": cls, "name": name, "other_tags": ot}, G("LINESTRING", pts)))
    for (id, cls, pts, name, ot) in barriers:
        lines.CreateFeature(ogr.Feature(lines.defn, {"osm_id": id, "barrier": cls, "name": name, "other_tags": ot}, G("LINESTRING", pts)))
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
    open(P["gpkg"], "ab").close()        # zero-byte placeholder: a consumer may test os.path.exists before ogr.Open

    for rel in STEPS:
        print(f"\n=== [{site}] {rel}")
        path = os.path.join(SRC, rel)
        if rel == ADAPTER:
            # PIPELINE_CHANGES.md 13.10 hook: the adapter is another task's file. Absent -> its
            # checks are skipped and say so; a crash -> one FAIL, and the pipeline checks go on.
            if not os.path.exists(path):
                print(f"  SKIPPED  {rel} does not exist -- the Unreal adapter checks for [{site}] are counted as skipped")
                adapter_ran[site] = None
                continue
            try:
                runpy.run_path(path, run_name="__main__")
                adapter_ran[site] = True
            except SystemExit as ex:                           # sys.exit(0) is a normal end; anything else a refusal
                if ex.code in (0, None):
                    adapter_ran[site] = True
                else:
                    adapter_ran[site] = False
                    check(f"adapter ran on [{site}] without refusing or crashing", False, f"refused: {ex.code}")
            except Exception as ex:
                traceback.print_exc()
                adapter_ran[site] = False
                check(f"adapter ran on [{site}] without refusing or crashing", False, f"{type(ex).__name__}: {ex}")
            continue
        runpy.run_path(path, run_name="__main__")
    return dict(P=P, out=P["out"], Z=Z, E0=E0, N0=N0, T=T, NX=NX, NY=NY, RES=RES, px=px)


def no_clip_keys(site_out, label):
    """A clipless site's manifests carry none of PIPELINE_CHANGES.md 9.3's keys and its terrain
    tiles declare no NoData: the byte-identity guarantee, seen from the schema side."""
    tm = json.load(open(os.path.join(site_out, "terrain", "terrain_manifest.json")))
    nm = json.load(open(os.path.join(site_out, "networks", "networks_manifest.json")))
    mm = json.load(open(os.path.join(site_out, "massing", "massing_manifest.json")))
    cm = json.load(open(os.path.join(site_out, "coast", "coast_manifest.json")))
    qf = json.load(open(os.path.join(site_out, "qa_furniture.json")))
    lm = json.load(open(os.path.join(site_out, "networks", "linear_manifest.json")))
    bad = [k for k in ("nodata", "clip", "tiles_clipped", "clipped_cells_total", "clip_note") if k in tm]
    bad += [f"tile:{k}" for t in tm["tiles"] for k in ("clip_state", "clipped_cells") if k in t]
    bad += [f"06:{k}" for k in ("clip", "vertices_outside_clip", "junctions_outside_clip") if k in nm]
    bad += [f"07:{k}" for k in ("clip", "outside_clip") if k in mm]
    bad += [f"09:{k}" for k in ("clip", "tiles_clipped", "clipped_cells", "bands_note") if k in cm]
    bad += [f"10:{k}" for k in ("clip", "outside_clip") if k in qf]
    bad += [f"11:{k}" for k in ("clip",) if k in lm]
    bad += [f"11:{L}:vertices_outside_clip" for L in lm["layers"] if "vertices_outside_clip" in lm["layers"][L]]
    nd = [gdal.Open(os.path.join(site_out, "terrain", t["file"])).GetRasterBand(1).GetNoDataValue() for t in tm["tiles"]]
    check(f"{label} clipless: no clip keys in any manifest, no NoData tag on any terrain tile",
          not bad and all(v is None for v in nd), f"{bad} nodata={nd}")


def adapter_checks(site, label, S, clip_block=None, tm=None):
    """PIPELINE_CHANGES.md 13.10's dryrun hook, per site. Skipped (not passed) when the adapter is absent."""
    names = [f"{label}-unreal manifest round-trips origin/tile_m/nx/ny/res",
             (f"{label}-unreal clipped_cells == clip-mask zeros per tile and in total; vis present for straddle tiles only; clip block copied"
              if clip_block else f"{label}-unreal no clip, all-255 clip masks, no vis files")]
    if adapter_ran.get(site) is None:
        for nm_ in names: skip(nm_, f"{ADAPTER} absent")
        return
    if adapter_ran.get(site) is False:
        for nm_ in names: check(nm_, False, "adapter did not complete")
        return
    U = os.path.join(S["out"], "unreal")
    done = set()
    try:
        um = json.load(open(os.path.join(U, "unreal_manifest.json")))
        check(names[0], um["origin"] == {"E": S["E0"], "N": S["N0"]} and um["tile_m"] == S["T"] and um["nx"] == S["NX"]
              and um["ny"] == S["NY"] and um["res"] == S["RES"], str({k: um.get(k) for k in ("origin", "tile_m", "nx", "ny", "res")}))
        done.add(names[0])
        lmf = json.load(open(os.path.join(U, "landscape", "landscape_manifest.json")))
        zeros = {}
        for t in lmf["tiles"]:
            m = np.fromfile(os.path.join(U, "landscape", f"clip_x{t['x']}_y{t['y']}.r8"), dtype=np.uint8)
            zeros[(t["x"], t["y"])] = (int((m == 0).sum()), m.size, os.path.exists(os.path.join(U, "landscape", f"vis_x{t['x']}_y{t['y']}.r8")))
        if clip_block:
            per_tile = {(t["x"], t["y"]): t for t in tm["tiles"]}
            ok = (all(zeros[k][0] == per_tile[k]["clipped_cells"] and zeros[k][1] == S["RES"] ** 2 for k in zeros)
                  and sum(z[0] for z in zeros.values()) == lmf["clipped_cells_total"] == tm["clipped_cells_total"]
                  and all(zeros[k][2] == (per_tile[k]["clip_state"] == "straddle") for k in zeros)
                  and lmf["clip"]["line"] == clip_block["line"] and lmf["clip"]["keep"] == clip_block["keep"]
                  and sorted(map(tuple, lmf["tiles_clipped"])) == sorted(map(tuple, tm["tiles_clipped"])))
            check(names[1], ok, f"{zeros} total {lmf.get('clipped_cells_total')} vs {tm.get('clipped_cells_total')}")
        else:
            ok = (lmf.get("clip") is None and all(z[0] == 0 and z[1] == S["RES"] ** 2 and not z[2] for z in zeros.values())
                  and not glob.glob(os.path.join(U, "landscape", "vis_*.r8")) and lmf.get("clipped_cells_total", 0) == 0)
            check(names[1], ok, str(zeros))
        done.add(names[1])
    except Exception as ex:
        traceback.print_exc()
        for nm_ in names:
            if nm_ not in done: check(nm_, False, f"{type(ex).__name__}: {ex}")


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
            ("b13", {"building": "house"},                                                   rect(E0 - 100, N0 + 100, 8, 8),   (4.0, 5.0, 6.0, 50, 3.0, 2.9)),   # off-grid
            # off-grid AND carrying levels + a trustworthy p50: the exact shape that used to poison
            # the height_calib fit. It is not emitted, so it must not steer the line either.
            ("b15", {"building": "house", "other_tags": '"building:levels"=>"2"'},          rect(E0 - 200, N0 + 140, 8, 8),   (30.0, 40.0, 45.0, 50, 3.0, 2.9)),
            # in a DSM coverage gap: 04 found ground (DTM) but no first-return cells -> height must come down the ladder, ground must stay real
            ("b14", {"building": "house", "other_tags": '"building:levels"=>"2"'},          rect(E0 + 180, N0 + 300, 8, 8),   (np.nan, np.nan, np.nan, 0, 11.0, 10.9))]
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
    check("A07 13 buildings emitted (off-grid b13, b15 dropped), incl. the 2 without LIDAR", len(bl) == 13
          and "b13" not in bb and "b15" not in bb and mm["outside_grid"] == 2
          and bb["b6"]["base_z"] is None and bb["b6"]["lidar_px"] == 0)
    check("A07 DSM-gap building keeps its real ground; only the height goes down the ladder",
          bb["b14"]["base_z"] == 11.0 and bb["b14"]["skirt"] == 10.4 and bb["b14"]["lidar_px"] == 0 and bb["b14"]["eaves"] is None
          and bb["b14"]["src"] == "osm_levels" and mm["buildings_without_dsm"] == 1 and mm["buildings_without_lidar"] == 2, str(bb["b14"]))
    check("A07 calibration FITTED from the site's own buildings, outlier rejected, off-grid b15 excluded from the fit",
          cal["source"] == "fitted" and mm["height_calib_fit"]["n"] == 6 and mm["height_calib_fit"]["rejected"] == 1
          and mm["height_calib_fit"]["excluded_off_grid"] == 1 and "excluded_off_clip" not in mm["height_calib_fit"]
          and 1.6 < cal["m_per_level"] < 2.0 and 2.5 < cal["intercept"] < 4.5, str(cal) + str(mm["height_calib_fit"]))
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

    # ---- 11 linear features on a site with no railway/barrier ways, and the clipless guarantee
    lmA = json.load(open(os.path.join(out, "networks", "linear_manifest.json")))
    check("A11 zero counts: rail and barriers 0 segments / 0 tiles, no files, empty skip histograms, 0 barrier areas",
          lmA["layers"]["rail"]["segments"] == 0 and lmA["layers"]["barriers"]["segments"] == 0
          and lmA["layers"]["rail"]["tiles"] == 0 and lmA["layers"]["barriers"]["tiles"] == 0
          and not glob.glob(os.path.join(out, "networks", "rail_x*_y*.jsonl")) and not glob.glob(os.path.join(out, "networks", "barriers_x*_y*.jsonl"))
          and lmA["ways_skipped_by_class"] == {"railway": {}, "barrier": {}} and lmA["barrier_areas_skipped"] == 0
          and lmA["layers"]["rail"]["gauge_defaulted"] == 0 and lmA["layers"]["barriers"]["height_defaulted"] == 0
          and lmA["origin"] == {"E": E0, "N": N0} and lmA["tile_m"] == T, str(lmA["layers"]))
    check("A11 decoys rail_x9_y9 / barriers_x9_y9 cleared by step 11; roads_x9_y9 by 06",
          not glob.glob(os.path.join(out, "networks", "*x9_y9*")))
    no_clip_keys(out, "A")
    adapter_checks("_dryrun_a", "A", A)

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
    lmB = json.load(open(os.path.join(outb, "networks", "linear_manifest.json")))
    check("B11 zero counts at the 2 m site: no rail/barrier ways, no files, no clip key",
          lmB["layers"]["rail"]["segments"] == 0 and lmB["layers"]["barriers"]["segments"] == 0 and "clip" not in lmB
          and not glob.glob(os.path.join(outb, "networks", "rail_x*_y*.jsonl")) and not glob.glob(os.path.join(outb, "networks", "barriers_x*_y*.jsonl")))
    adapter_checks("_dryrun_b", "B", B)

    # ================================================================ site C: 1 m, 3 x 2 tiles, diagonal clip
    # PIPELINE_CHANGES.md 8.2: a half-plane clip kept iff local x + y >= 1100. Tile (0, 0) is wholly
    # outside and has no raw tile (its VRT region is nodata); (0,1) (1,0) (1,1) (2,0) straddle the
    # line; (2,1) is inside. The plane z = 20 + 0.01 x + 0.02 y carries a 30 m single-cell spike at
    # local (600, 100) -- OUTSIDE the clip, inside straddle tile (1,0) -- so that range_m and slope_qa
    # are provably taken from kept cells only (the spike would give ~86 deg and z 58).
    E0c, N0c = 700000, 300000
    CLIP_C = {"type": "halfplane", "line": [[E0c, N0c + 1100], [E0c + 1100, N0c]], "keep": "left"}
    cfgC = {"crs": "EPSG:27700", "origin": {"E": E0c, "N": N0c}, "tile_m": 512, "nx": 3, "ny": 2, "grid_res": 513, "clip": CLIP_C}
    def zC(EE, NN):
        Z = 20.0 + 0.01 * (EE - E0c) + 0.02 * (NN - N0c)
        return np.where((EE == E0c + 600) & (NN == N0c + 100), Z + 30.0, Z)
    def zc_at(e, n): return 20.0 + 0.01 * (e - E0c) + 0.02 * (n - N0c)
    L = lambda x, y: (E0c + x, N0c + y)
    rd1 = [L(700, 100), L(700, 900)]                       # crosses the line at y = 400 and the seam at y = 512
    waysC = [("rd1", "residential", rd1, "Cut Road", None),
             ("rd2", "residential", [L(100, 100), L(300, 100)], None, None),       # wholly outside
             ("rd3", "footway", [L(100, 100), L(100, 300)], None, None),           # outside; third way at the outside junction
             ("rd4", "service", [L(100, 100), L(300, 300)], None, None),           # outside junction (100, 100)
             ("rd5", "tertiary", [L(1300, 800), L(1500, 800)], None, None),
             ("rd6", "tertiary", [L(1100, 800), L(1300, 800)], None, None),
             ("rd7", "footway", [L(1300, 800), L(1300, 1000)], None, None)]        # inside junction (1300, 800)
    railsC = [("rl1", "rail", rd1, "Test Line", '"gauge"=>"1435","electrified"=>"rail","usage"=>"main","tracks"=>"2"'),
              ("rl2", "disused", [L(1200, 600), L(1400, 700)], None, None),        # no gauge tag -> default
              ("rl3", "platform", [L(1250, 650), L(1350, 650)], None, None),       # not a track: skipped
              ("rl4", "rail", [L(100, 200), L(300, 200)], None, '"gauge"=>"1435"')]  # wholly outside the clip
    barriersC = [("bw1", "wall", [L(1100, 600), L(1100, 700)], None, '"height"=>"0.5","wall"=>"brick"'),
                 ("bf1", "fence", [L(1200, 900), L(1300, 900)], None, '"fence_type"=>"chain_link","material"=>"metal"'),
                 ("bk1", "kerb", [L(1200, 700), L(1250, 700)], None, '"height"=>"15 cm"'),
                 ("bh1", "hedge", [L(400, 400), L(800, 800)], None, None),         # crosses the line at (550, 550)
                 ("bg1", "gate", [L(1200, 750), L(1202, 750)], None, None)]        # point-like: skipped, counted
    # cb1 and cb3-cb5 are inside the clip and sit exactly on h = 3 + 2*levels, so the auto fit below has
    # one arithmetic answer. cb2 is OUTSIDE the clip and off the line: it is not emitted, so it must not
    # enter the calibration either -- with it the fit is no longer 3.0 + 2.0*levels.
    bldC = [("cb1", {"building": "house", "other_tags": '"building:levels"=>"2"'}, rect(E0c + 1200, N0c + 600, 10, 10), (4.0, 7.0, 8.0, 40, 44.0, 43.8)),
            ("cb2", {"building": "house", "other_tags": '"building:levels"=>"2"'}, rect(E0c + 200, N0c + 200, 10, 10), (4.0, 6.0, 8.0, 40, 26.0, 25.8)),   # centre outside
            ("cb3", {"building": "house", "other_tags": '"building:levels"=>"1"'}, rect(E0c + 1300, N0c + 500, 10, 10), (4.0, 5.0, 6.0, 40, 43.0, 42.8)),
            ("cb4", {"building": "house", "other_tags": '"building:levels"=>"2"'}, rect(E0c + 1330, N0c + 500, 10, 10), (4.0, 7.0, 8.0, 40, 43.0, 42.8)),
            ("cb5", {"building": "house", "other_tags": '"building:levels"=>"3"'}, rect(E0c + 1360, N0c + 500, 10, 10), (4.0, 9.0, 10.0, 40, 43.0, 42.8)),
            # a seamark: `height` is the LIGHT's elevation above MHWS, seamark:landmark:height the tower
            ("cb6", {"building": "yes", "name": "Test Light",
                     "other_tags": '"height"=>"57","seamark:type"=>"light_major","seamark:landmark:height"=>"26"'},
             rect(E0c + 1400, N0c + 700, 10, 10), (10.0, 18.0, 24.0, 40, 43.0, 42.8)),
            # a seamark with only the ambiguous tag: still used, but reported
            ("cb7", {"building": "yes", "other_tags": '"height"=>"18","seamark:type"=>"light_minor"'},
             rect(E0c + 1440, N0c + 700, 10, 10), (2.0, 4.5, 12.7, 8, 43.0, 42.8))]
    nodesC = [("cn1", E0c + 702, N0c + 700, '"amenity"=>"waste_basket"'),          # 2 m off rd1, inside
              ("cn2", E0c + 100, N0c + 150, '"amenity"=>"waste_basket"')]          # outside
    C = synth("_dryrun_c", {
        "origin": {"E": E0c, "N": N0c}, "clip": CLIP_C, "water_level": -50.0,
        "height_calib": {"mode": "auto", "min_buildings": 3, "fallback": {"intercept": 9.9, "m_per_level": 9.9}, "dispute_m": 4.0},
        "coast": {"foreshore_max_odn": -50.0, "rock_slope_deg": [25.0, 45.0], "water_margin_m": 0.75},
        "landmarks": {},
    }, px=1, RES=513, NX=3, NY=2, zfun=zC, ways=waysC, buildings=bldC, nodes=nodesC,
       rails=railsC, barriers=barriersC, skip_tiles=((0, 0),))
    outc = C["out"]
    print("\n=== checks: site C")
    clipC = lib.parse_clip(cfgC)
    onC = lambda e, n: (e - E0c) + (n - N0c) >= 1100 - 1e-6          # kept?
    near = lambda e, n: (e - E0c) + (n - N0c) < 1100 + 12             # within 12 m of the line (8 m densify + Chaikin)

    # ---- 02-equivalent: the positions step 02 would not request
    sk = [(i, j) for i in range(3) for j in range(2) if lib.tile_state(clipC, cfgC, i, j) == "outside"]
    check("C02-equivalent: only (0,0) is wholly outside -> skipped_clip 2, 5 positions x2 requested", sk == [(0, 0)] and 2 * len(sk) == 2 and (6 - len(sk)) * 2 == 10)

    # ---- 05 terrain with the clip
    tmc = json.load(open(os.path.join(outc, "terrain", "terrain_manifest.json")))
    tc = {(t["x"], t["y"]): t for t in tmc["tiles"]}
    check("C05 outside tile (0,0): no file, listed in tiles_clipped, NOT in tiles_missing; 5 tiles written",
          not os.path.exists(os.path.join(outc, "terrain", "dtm_x0_y0.tif")) and tmc["tiles_clipped"] == [[0, 0]]
          and tmc["tiles_missing"] == [] and sorted(tc) == [(0, 1), (1, 0), (1, 1), (2, 0), (2, 1)], f"{tmc['tiles_clipped']} {tmc['tiles_missing']} {sorted(tc)}")
    a10 = gdal.Open(os.path.join(outc, "terrain", "dtm_x1_y0.tif")).GetRasterBand(1).ReadAsArray()
    m10 = lib.cell_mask(clipC, (E0c + 512 - 0.5, 1.0, 0.0, N0c + 512 + 0.5, 0.0, -1.0), 513, 513)
    raw10 = C["Z"][512:1025, 512:1025]
    check("C05 straddle (1,0): NoData count 167466 == clipped_cells == manifest", int((a10 == -9999.0).sum()) == 167466 == tc[(1, 0)]["clipped_cells"]
          and tc[(1, 0)]["clip_state"] == "straddle", f"{int((a10 == -9999.0).sum())} {tc[(1, 0)]}")
    check("C05 straddle (1,0): SW corner NoData, NE corner real, kept cells untouched, nothing else NoData",
          a10[512, 0] == -9999.0 and abs(a10[0, 512] - zc_at(E0c + 1024, N0c + 512)) < 0.01
          and np.array_equal(a10[m10], raw10[m10]) and (a10[~m10] == -9999.0).all() and (a10[m10] != -9999.0).all())
    check("C05 inside tile (2,1): clip_state inside, 0 clipped cells, no NoData in the array",
          tc[(2, 1)]["clip_state"] == "inside" and tc[(2, 1)]["clipped_cells"] == 0
          and (gdal.Open(os.path.join(outc, "terrain", "dtm_x2_y1.tif")).GetRasterBand(1).ReadAsArray() != -9999.0).all())
    check("C05 NoData -9999 declared on EVERY tile of the clipped site (inside ones too)",
          all(gdal.Open(os.path.join(outc, "terrain", t["file"])).GetRasterBand(1).GetNoDataValue() == -9999.0 for t in tmc["tiles"]) and tmc["nodata"] == -9999.0)
    check("C05 range_m and slope_qa from KEPT cells only: [31.0, 55.84], no spike (86 deg / z 58 lies outside the line)",
          tmc["range_m"] == [31.0, 55.84] and tmc["slope_qa"]["max_deg"] < 5 and tmc["slope_qa"]["pct_cells_over_45deg"] == 0
          and tc[(1, 0)]["min_m"] > 30 and tc[(1, 0)]["max_m"] < 56 and tc[(1, 0)]["slope_max_deg"] < 5, f"{tmc['range_m']} {tmc['slope_qa']} {tc[(1, 0)]}")
    check("C05 manifest clip block, clipped_cells_total = 2 x 167466 + 2 x 2926, clip_note, nodata_cells 0 (no coverage gap was filled)",
          tmc["clip"]["line"] == CLIP_C["line"] and tmc["clip"]["keep"] == "left" and "semantics" in tmc["clip"]
          and tmc["clipped_cells_total"] == 2 * 167466 + 2 * 2926 == sum(t["clipped_cells"] for t in tmc["tiles"])
          and tc[(1, 1)]["clipped_cells"] == 2926 and tc[(0, 1)]["clipped_cells"] == 167466 and tc[(2, 0)]["clipped_cells"] == 2926
          and "deliberate absence" in tmc["clip_note"] and all(t["nodata_cells"] == 0 for t in tmc["tiles"]),
          f"{tmc.get('clipped_cells_total')} {[t['clipped_cells'] for t in tmc['tiles']]}")

    # ---- 06 roads with the clip
    rc = jl_tiles(os.path.join(outc, "networks", "roads_x*_y*.jsonl"))
    segc = [(t, r) for t, rs in rc.items() for r in rs if r["cls"] != "_junction"]
    byc = {}
    for t, r in segc: byc.setdefault(r["id"], []).append((t, r))
    rd1_runs = sorted(byc.get("rd1", []), key=lambda tr: tr[1]["pts"][0][1])
    check("C06 rd1 cut at its last kept smoothed vertex: first vertex y in [400, 412), every vertex x + y >= 1100",
          rd1_runs and 400 <= rd1_runs[0][1]["pts"][0][1] - N0c < 412 and all(onC(v[0], v[1]) for _, r in rd1_runs for v in r["pts"])
          and abs(rd1_runs[-1][1]["pts"][-1][1] - (N0c + 900)) < 1e-6, str([r["pts"][0] for _, r in rd1_runs]))
    nmc = json.load(open(os.path.join(outc, "networks", "networks_manifest.json")))
    check("C06 wholly outside ways dropped (rd2, rd3, rd4), counted as vertices_outside_clip; rd5-7 kept",
          all(w not in byc for w in ("rd2", "rd3", "rd4")) and all(w in byc for w in ("rd5", "rd6", "rd7")) and nmc["vertices_outside_clip"] > 0)
    check("C06 off-clip vertices are NOT DTM gaps: vertices_without_dtm 0, every kept segment z_gap False, z on the plane",
          nmc["vertices_without_dtm"] == 0 and all(r["z_gap"] is False for _, r in segc)
          and all(abs(v[2] - zc_at(v[0], v[1])) < 0.05 for _, r in segc for v in r["pts"]))
    check("C06 seam split kept: rd1 in tiles (1,0) and (1,1) with the seam vertex duplicated",
          [t for t, _ in rd1_runs] == [(1, 0), (1, 1)] and rd1_runs[0][1]["pts"][-1] == rd1_runs[1][1]["pts"][0])
    juncc = [(t, r) for t, rs in rc.items() for r in rs if r["cls"] == "_junction"]
    check("C06 outside junction (100,100) dropped and counted; inside junction (1300,800) kept",
          len(juncc) == 1 and abs(juncc[0][1]["pts"][0][0] - (E0c + 1300)) < 0.2 and nmc["junctions_outside_clip"] == 1 and nmc["junctions"] == 2, str(juncc))
    check("C06 manifest clip block", nmc["clip"]["keep"] == "left" and nmc["clip"]["line"] == CLIP_C["line"])

    # ---- 07 massing with the clip
    blc = jl(os.path.join(outc, "massing", "buildings_*.jsonl"))
    mmc = json.load(open(os.path.join(outc, "massing", "massing_manifest.json")))
    bc = {b["id"]: b for b in blc}
    check("C07 outside_clip 1 (cb2's envelope centre), 6 buildings kept, manifest clip block",
          mmc["outside_clip"] == 1 and sorted(bc) == ["cb1", "cb3", "cb4", "cb5", "cb6", "cb7"] and mmc["buildings"] == 6
          and mmc["outside_grid"] == 0 and mmc["clip"]["line"] == CLIP_C["line"],
          f"{mmc.get('outside_clip')} {sorted(bc)}")
    # The fit population must BE the model population. cb1/cb3/cb4/cb5 lie exactly on h = 3 + 2*levels;
    # off-clip cb2 (levels 2, p50 6.0) does not, so if it leaked in the answer would not be 3.0/2.0.
    check("C07 height_calib fitted from IN-CLIP buildings only: exactly 3.0 + 2.0*levels, off-clip cb2 excluded",
          mmc["height_calib"] == {"intercept": 3.0, "m_per_level": 2.0, "source": "fitted", "dispute_m": 4.0}
          and mmc["height_calib_fit"] == {"n": 4, "rejected": 0, "rmse_m": 0.0, "excluded_off_clip": 1},
          f"{mmc['height_calib']} {mmc['height_calib_fit']}")
    check("C07 seamark: seamark:landmark:height beats the ambiguous `height` tag (26, not 57); "
          "a seamark with only `height` still uses it and is reported",
          bc["cb6"]["src"] == "seamark_height" and bc["cb6"]["h"] == 26.0
          and bc["cb7"]["src"] == "osm_height" and bc["cb7"]["h"] == 18.0
          and mmc["by_height_source"]["seamark_height"] == 1, f"{bc['cb6']} {bc['cb7']}")

    # ---- 09 ground cover with the clip
    cmc = json.load(open(os.path.join(outc, "coast", "coast_manifest.json")))
    check("C09 outside tile (0,0): no raster, tiles_clipped [[0,0]], NOT tiles_without_dtm; 5 rasters",
          not os.path.exists(os.path.join(outc, "coast", "ground_x0_y0.tif")) and cmc["tiles_clipped"] == [[0, 0]] and cmc["tiles_without_dtm"] == []
          and len(glob.glob(os.path.join(outc, "coast", "ground_x*_y*.tif"))) == 5, f"{cmc.get('tiles_clipped')} {cmc['tiles_without_dtm']}")
    sums, zero_total = {}, 0
    for pth in sorted(glob.glob(os.path.join(outc, "coast", "ground_x*_y*.tif"))):
        gd = gdal.Open(pth)
        s = sum(gd.GetRasterBand(b).ReadAsArray().astype(int) for b in (1, 2, 3, 4))
        mt = re.search(r"ground_x(\d+)_y(\d+)", pth); sums[(int(mt.group(1)), int(mt.group(2)))] = s
        zero_total += int((s == 0).sum())
    check("C09 straddle (1,0): zero-sum class cells 41665; (1,1): 703; inside (2,1): none",
          int((sums[(1, 0)] == 0).sum()) == 41665 and int((sums[(1, 1)] == 0).sum()) == 703 and int((sums[(2, 1)] == 0).sum()) == 0,
          str({k: int((v == 0).sum()) for k, v in sums.items()}))
    check("C09 (sum >= 252) | (sum == 0) everywhere; sum == 0 count == clipped_cells; zero cells are 0 in ALL bands",
          all(((v >= 252) | (v == 0)).all() for v in sums.values()) and zero_total == cmc["clipped_cells"] == 2 * 41665 + 2 * 703
          and all((gdal.Open(os.path.join(outc, "coast", "ground_x1_y0.tif")).GetRasterBand(b).ReadAsArray()[sums[(1, 0)] == 0] == 0).all() for b in (1, 2, 3, 4)),
          f"{zero_total} vs {cmc.get('clipped_cells')}")
    g10 = gdal.Open(os.path.join(outc, "coast", "ground_x1_y0.tif"))
    km10 = lib.cell_mask(clipC, g10.GetGeoTransform(), 256, 256)
    check("C09 zeroed cells are exactly the class cells whose centres lie outside the line; kept cells are all grass 255",
          np.array_equal(sums[(1, 0)] == 0, ~km10) and (g10.GetRasterBand(1).ReadAsArray()[km10] == 255).all())
    check("C09 manifest clip, tiles_clipped, clipped_cells, bands_note; no water tiles at -50",
          cmc["clip"]["line"] == CLIP_C["line"] and "252..255" in cmc["bands_note"] and "only outside" in cmc["bands_note"] and cmc["water_tiles"] == [])

    # ---- 10 furniture with the clip
    fc = {r["id"]: r for r in jl(os.path.join(outc, "furniture", "furniture_*.jsonl"))}
    qfc = json.load(open(os.path.join(outc, "qa_furniture.json")))
    check("C10 outside node cn2 dropped and counted; cn1 placed on rd1 (residential, kerb)",
          list(fc) == ["cn1"] and fc["cn1"]["cls"] == "residential" and fc["cn1"]["src"] == "kerb" and qfc["outside_clip"] == 1
          and qfc["outside_grid"] == 0 and qfc["clip"]["line"] == CLIP_C["line"], f"{list(fc)} {qfc.get('outside_clip')}")

    # ---- 11 linear features with the clip
    railc = jl_tiles(os.path.join(outc, "networks", "rail_x*_y*.jsonl"))
    barc = jl_tiles(os.path.join(outc, "networks", "barriers_x*_y*.jsonl"))
    lmc = json.load(open(os.path.join(outc, "networks", "linear_manifest.json")))
    rl1 = {t: [(r["pts"], r["z_gap"]) for r in rs if r["id"] == "rl1"] for t, rs in railc.items()}
    rd1_by_tile = {t: [(r["pts"], r["z_gap"]) for r in rs if r.get("id") == "rd1"] for t, rs in rc.items()}
    check("C11 rl1 (rail on rd1's polyline): per-tile pts and z_gap IDENTICAL to rd1's -- lib.drape_runs == 06",
          {t: v for t, v in rl1.items() if v} == {t: v for t, v in rd1_by_tile.items() if v} and len([1 for v in rl1.values() if v]) == 2,
          f"rail tiles {sorted(t for t, v in rl1.items() if v)} vs road tiles {sorted(t for t, v in rd1_by_tile.items() if v)}")
    rr = {r["id"]: r for rs in railc.values() for r in rs}
    check("C11 rail fields: gauge 1.435 osm, tracks 2, electrified rail, usage main, service null, bridge/tunnel False, name, cls rail",
          rr["rl1"]["gauge"] == 1.435 and rr["rl1"]["gauge_src"] == "osm" and rr["rl1"]["tracks"] == 2 and rr["rl1"]["electrified"] == "rail"
          and rr["rl1"]["usage"] == "main" and rr["rl1"]["service"] is None and rr["rl1"]["bridge"] is False and rr["rl1"]["tunnel"] is False
          and rr["rl1"]["name"] == "Test Line" and rr["rl1"]["cls"] == "rail", str({k: v for k, v in rr["rl1"].items() if k != "pts"}))
    check("C11 disused rl2 gets the default gauge (1.435, gauge_src default); platform rl3 skipped and counted",
          rr["rl2"]["gauge"] == 1.435 and rr["rl2"]["gauge_src"] == "default" and rr["rl2"]["tracks"] is None and "rl3" not in rr
          and lmc["ways_skipped_by_class"]["railway"] == {"platform": 1} and lmc["layers"]["rail"]["gauge_defaulted"] == 1, str(lmc["ways_skipped_by_class"]))
    check("C11 outside rail rl4 dropped: not emitted, its vertices in vertices_outside_clip; by_class {rail 1, disused 1}",
          "rl4" not in rr and lmc["layers"]["rail"]["vertices_outside_clip"] > 0 and lmc["layers"]["rail"]["by_class"] == {"rail": 1, "disused": 1}
          and lmc["layers"]["rail"]["ways_dropped"] == 1, str(lmc["layers"]["rail"]))
    br = {r["id"]: r for rs in barc.values() for r in rs}
    check("C11 wall bw1 h 0.5 (osm, wall brick); fence bf1 h 1.5 (default, chain_link / metal)",
          br["bw1"]["h"] == 0.5 and br["bw1"]["h_src"] == "osm" and br["bw1"]["wall"] == "brick" and br["bw1"]["cls"] == "wall"
          and br["bf1"]["h"] == 1.5 and br["bf1"]["h_src"] == "default" and br["bf1"]["fence_type"] == "chain_link" and br["bf1"]["material"] == "metal"
          and lmc["layers"]["barriers"]["height_defaulted"] == 2, f"{ {k: v for k, v in br['bw1'].items() if k != 'pts'} } {lmc['layers']['barriers'].get('height_defaulted')}")
    check("C11 Chaikin 0 on barriers: bw1's E exact on every vertex, endpoints pinned, 14 densified vertices",
          all(v[0] == E0c + 1100 for v in br["bw1"]["pts"]) and br["bw1"]["pts"][0][1] == N0c + 600 and br["bw1"]["pts"][-1][1] == N0c + 700
          and len(br["bw1"]["pts"]) == 14 and lmc["layers"]["barriers"]["smoothing"]["chaikin_iters"] == 0 and lmc["layers"]["rail"]["smoothing"]["chaikin_iters"] == 2,
          str(br["bw1"]["pts"][:3]))
    check("C11 kerb height \"15 cm\" -> 0.15 m (osm)", br["bk1"]["h"] == 0.15 and br["bk1"]["h_src"] == "osm")
    bh1_runs = [(t, r) for t, rs in barc.items() for r in rs if r["id"] == "bh1"]
    check("C11 hedge bh1 cut at the line (first vertex within 12 m, all vertices kept); gate bg1 skipped and counted",
          len(bh1_runs) == 1 and bh1_runs[0][0] == (1, 1) and near(*bh1_runs[0][1]["pts"][0][:2])
          and all(onC(v[0], v[1]) for _, r in bh1_runs for v in r["pts"]) and "bg1" not in br
          and lmc["ways_skipped_by_class"]["barrier"] == {"gate": 1} and lmc["layers"]["barriers"]["vertices_outside_clip"] > 0,
          f"{[(t, r['pts'][0]) for t, r in bh1_runs]} {lmc['ways_skipped_by_class']}")
    check("C11 manifest shape: PIPELINE_CHANGES.md 4.4 keys, tile counts == files, clip block",
          set(lmc) >= {"site", "crs", "coordinates", "origin", "tile_m", "source_layer", "layers", "ways_skipped_by_class", "barrier_areas_skipped", "clip"}
          and set(lmc["layers"]["rail"]) >= {"files", "column", "classes_emitted", "segments", "tiles", "length_km", "by_class", "smoothing", "default_gauge_m",
                                            "gauge_defaulted", "vertices_without_dtm", "vertices_outside_grid", "vertices_outside_clip"}
          and set(lmc["layers"]["barriers"]) >= {"files", "column", "classes_emitted", "segments", "tiles", "length_km", "by_class", "smoothing", "default_height_m",
                                                "height_defaulted", "vertices_without_dtm", "vertices_outside_grid", "vertices_outside_clip"}
          and lmc["layers"]["rail"]["tiles"] == len(railc) and lmc["layers"]["barriers"]["tiles"] == len(barc)
          and lmc["layers"]["rail"]["segments"] == sum(len(v) for v in railc.values()) and lmc["layers"]["barriers"]["segments"] == sum(len(v) for v in barc.values())
          and lmc["layers"]["rail"]["column"] == "railway" and lmc["layers"]["barriers"]["column"] == "barrier"
          and lmc["layers"]["barriers"]["default_height_m"]["wall"] == 1.8 and lmc["layers"]["rail"]["default_gauge_m"] == 1.435
          and lmc["layers"]["barriers"]["by_class"] == {"wall": 1, "fence": 1, "kerb": 1, "hedge": 1}
          and lmc["clip"]["line"] == CLIP_C["line"] and lmc["origin"] == {"E": E0c, "N": N0c} and lmc["barrier_areas_skipped"] == 0
          and lmc["layers"]["rail"]["vertices_without_dtm"] == 0 and lmc["layers"]["barriers"]["vertices_without_dtm"] == 0,
          str({k: (v if k != "layers" else {kk: {x: y for x, y in vv.items() if x not in ("default_height_m", "classes_emitted")} for kk, vv in v.items()}) for k, v in lmc.items()}))
    adapter_checks("_dryrun_c", "C", C, clip_block=CLIP_C, tm=tmc)

    # ---- C-lib: the clip API and the shared line geometry (PIPELINE_CHANGES.md 2, 8.3)
    print("\n=== checks: lib clip API (site C numbers, site A's 06 output, the real thanet.json)")
    refused = 0
    for bad in ({"clip": {"type": "circle", "line": [[0, 0], [1, 1]]}},
                {"clip": {"type": "halfplane", "line": [[0, 0], [1, 1]], "keep": "up"}},
                {"clip": {"type": "halfplane", "line": [[5, 5], [5, 5]]}}):
        try:
            lib.parse_clip(bad)
        except SystemExit:
            refused += 1
    check("C-lib parse_clip: absent -> None; unknown type refuses", lib.parse_clip({}) is None and lib.parse_clip({"clip": None}) is None
          and isinstance(clipC, lib.HalfPlaneClip) and refused == 3
          and clipC.stamp() == {"type": "halfplane", "line": [[E0c, N0c + 1100], [E0c + 1100, N0c]], "keep": "left"}, f"refused {refused}")
    states = {(i, j): lib.tile_state(clipC, cfgC, i, j) for i in range(3) for j in range(2)}
    check("C-lib tile_state on the diagonal", states == {(0, 0): "outside", (0, 1): "straddle", (1, 0): "straddle", (1, 1): "straddle",
          (2, 0): "straddle", (2, 1): "inside"} and lib.tile_state(None, cfgC, 0, 0) == "inside", str(states))
    Ek = E0c + np.array([0, 1100, 600, 550, 2000]); Nk = N0c + np.array([0, 0, 500, 550, 2000])
    kp = lib.keep_points(clipC, Ek, Nk)
    kr = lib.keep_points(lib.parse_clip({"clip": {**CLIP_C, "keep": "right"}}), Ek, Nk)
    k0 = lib.keep_points(clipC, E0c, N0c)
    check("C-lib keep_points: vectorised; on-line kept; keep=right mirrors", kp.tolist() == [False, True, True, True, True]
          and kr.tolist() == [True, True, True, True, False] and k0.shape == () and not k0
          and lib.keep_points(None, Ek, Nk).tolist() == [True] * 5 and lib.keep_points(None, Ek[None, :], Nk[:, None]).shape == (5, 5),
          f"{kp.tolist()} {kr.tolist()}")
    gt10 = (E0c + 512 - 0.5, 1.0, 0.0, N0c + 512 + 0.5, 0.0, -1.0)
    m10 = lib.cell_mask(clipC, gt10, 513, 513)
    check("C-lib cell_mask at pixel centres: tile (1,0) clips 167466 of 263169; None -> all True",
          m10.shape == (513, 513) and int((~m10).sum()) == 167466 and not m10[512, 0] and m10[0, 512]
          and lib.cell_mask(None, gt10, 513, 513).shape == (513, 513) and lib.cell_mask(None, gt10, 513, 513).all(), str(int((~m10).sum())))
    bb11, bb21, bb00 = (E0c + 512, N0c + 512, E0c + 1024, N0c + 1024), (E0c + 1024, N0c + 512, E0c + 1536, N0c + 1024), (E0c, N0c, E0c + 512, N0c + 512)
    w11, wN, w21 = lib.clip_wkt(clipC, bb11), lib.clip_wkt(None, bb11), lib.clip_wkt(clipC, bb21)
    rectN = (f"POLYGON(({E0c + 512}.000 {N0c + 512}.000,{E0c + 1024}.000 {N0c + 512}.000,{E0c + 1024}.000 {N0c + 1024}.000,"
             f"{E0c + 512}.000 {N0c + 1024}.000,{E0c + 512}.000 {N0c + 512}.000))")
    check("C-lib clip_wkt: 5-corner / rectangle / None", w11.startswith("POLYGON((") and w11.count(",") == 5
          and f"{E0c + 588}.000 {N0c + 512}.000" in w11 and f"{E0c + 512}.000 {N0c + 588}.000" in w11
          and wN == rectN and w21.count(",") == 4 and lib.clip_wkt(clipC, bb00) is None, f"{w11} | {wN}")
    check("C-lib grid_stamp: four keys with or without a clip", lib.grid_stamp(cfgC) == lib.grid_stamp(cfgC, clipC)
          == {"crs": "EPSG:27700", "origin": {"E": E0c, "N": N0c}, "tile_m": 512, "grid_res": 513})
    cmC = lib.clip_manifest(clipC)
    check("C-lib clip_manifest: None -> None; stamp keys + semantics", lib.clip_manifest(None) is None
          and set(cmC) == {"type", "line", "keep", "semantics"} and cmC["line"] == CLIP_C["line"] and "centres" in cmC["semantics"])
    cmW = lib.clip_manifest(clipC, cfgC)
    check("C-lib clip_manifest(clip, cfg) carries the kept region as WKT over the whole grid",
          set(cmW) == {"type", "line", "keep", "semantics", "wkt", "wkt_note"}
          and lib.site_bbox(cfgC) == (E0c, N0c, E0c + 3 * 512, N0c + 2 * 512)
          and cmW["wkt"] == lib.clip_wkt(clipC, lib.site_bbox(cfgC)) and cmW["wkt"].count(",") == 4
          and lib.clip_manifest(None, cfgC) is None, str(cmW.get("wkt")))
    sd = clipC.signed_distance_out(E0c + np.array([0, 0, 1100, 1100]), N0c + np.array([1100, 0, 0, 1100]))
    check("C-lib signed_distance_out: 0 on the line, + into the cut", abs(sd[0]) < 1e-9 and abs(sd[2]) < 1e-9
          and abs(sd[1] - 1100 / math.sqrt(2)) < 1e-6 and abs(sd[3] + 1100 / math.sqrt(2)) < 1e-6, str(sd))
    check("C-lib tagval / densify / chaikin are 06's copies", lib.tagval('"lanes"=>"2","bridge"=>"yes"', "bridge") == "yes"
          and lib.tagval(None, "x") is None and lib.tagval('"a"=>"b"', "x") is None
          and lib.densify([(0.0, 0.0), (20.0, 0.0)], 8.0) == [(0.0, 0.0), (8.0, 0.0), (16.0, 0.0), (20.0, 0.0)]
          and lib.chaikin([(0, 0), (10, 0), (10, 10)], 1) == [(0, 0), (2.5, 0.0), (7.5, 0.0), (10.0, 2.5), (10.0, 7.5), (10, 10)]
          and lib.chaikin([(0, 0), (10, 0)], 3) == [(0, 0), (10, 0)])
    # drape_runs must reproduce step 06's per-tile runs, z values and z_gap flags for site A exactly
    # (the guard for the later refactor of 06 onto lib): same densify/Chaikin/bilinear/seam arithmetic.
    cfgA = {"origin": {"E": A["E0"], "N": A["N0"]}, "tile_m": A["T"], "nx": A["NX"], "ny": A["NY"]}
    six = {}
    for pth in sorted(glob.glob(os.path.join(A["out"], "networks", "roads_x*_y*.jsonl"))):
        mt = re.search(r"roads_x(\d+)_y(\d+)\.jsonl$", pth)
        for l in open(pth):
            r = json.loads(l)
            if r["cls"] != "_junction":
                six.setdefault(r["id"], []).append(((int(mt.group(1)), int(mt.group(2))), json.dumps(r["pts"]), r["z_gap"]))
    TR = json.load(open(os.path.join(SRC, "config", "tuning.json"), encoding="utf-8"))["roads"]
    SPECr, SKIPr = {k for k in TR["widths_m"] if not k.startswith("_")}, set(TR["skip"])
    Zn = A["Z"].astype(np.float32); Zn[lib.nodata_mask(Zn, -9999.0)] = np.nan
    sampA = lib.DtmSampler(Zn, (A["E0"] - 0.5, 1.0, 0.0, A["N0"] + A["NY"] * A["T"] + 0.5, 0.0, -1.0))
    mine, ctr = {}, {}
    for (wid, wcls, wpts, _, _) in waysA:
        if wcls in SKIPr or wcls not in SPECr or len(wpts) < 2: continue
        for tile, run, gap in lib.drape_runs(lib.chaikin(lib.densify(wpts, TR["densify_step_m"]), TR["chaikin_iters"]), cfgA, sampA, None, ctr):
            mine.setdefault(wid, []).append((tile, json.dumps(run), gap))
    check("C-lib drape_runs == 06 arithmetic", len(six) >= 6 and {k: sorted(v) for k, v in mine.items()} == {k: sorted(v) for k, v in six.items()}
          and ctr.get("without_dtm") == nm["vertices_without_dtm"] and ctr.get("outside_grid") == nm["vertices_outside_grid"]
          and "outside_clip" not in ctr and lib.tile_of(cfgA, A["E0"] - 1, A["N0"]) is None and lib.tile_of(cfgA, A["E0"] + 600, A["N0"] + 200) == (1, 0),
          f"lib {sorted(mine)} vs 06 {sorted(six)}; counters {ctr} vs {nm['vertices_without_dtm']}/{nm['vertices_outside_grid']}")
    # the real Thanet config: the OSTN15 endpoints of BRIEF 4.1 and the tile budget its notes quote
    tcfg = json.load(open(os.path.join(SITES_DIR, "thanet.json"), encoding="utf-8"))
    check("C-lib thanet.json clip.line == BRIEF 4.1 [[628512, 169680], [635496, 163609]]",
          tcfg["clip"]["type"] == "halfplane" and tcfg["clip"]["line"] == [[628512, 169680], [635496, 163609]] and tcfg["clip"]["keep"] == "left",
          str(tcfg["clip"].get("line")))
    tclip = lib.parse_clip(tcfg)
    Tt, E0t, N0t, RESt = tcfg["tile_m"], tcfg["origin"]["E"], tcfg["origin"]["N"], tcfg["grid_res"]
    st, clipped = Counter(), 0
    for i in range(tcfg["nx"]):
        for j in range(tcfg["ny"]):
            s = lib.tile_state(tclip, tcfg, i, j); st[s] += 1
            if s == "straddle":
                clipped += int((~lib.cell_mask(tclip, (E0t + i * Tt - 0.5, 1.0, 0.0, N0t + (j + 1) * Tt + 0.5, 0.0, -1.0), RESt, RESt)).sum())
    check("C-lib tile_state / cell_mask on the Thanet grid: 360 inside, 31 straddle, 103 outside, 3861822 clipped cells",
          dict(st) == {"inside": 360, "straddle": 31, "outside": 103} and clipped == 3861822, f"{dict(st)} {clipped}")
    bn = tcfg["clip"].get("budget_note", "")
    check("C-lib thanet.json budget_note quotes the recomputed budget (360/31/103, 3,861,822 of 8,158,239)",
          "360 tiles inside, 31 straddle, 103 outside" in bn and "3,861,822" in bn and "8,158,239" in bn and 31 * RESt * RESt == 8158239)
    mcfg = json.load(open(os.path.join(SITES_DIR, "margate.json"), encoding="utf-8"))
    check("C-lib margate.json has no clip: every answer is 'kept'", "clip" not in mcfg and lib.parse_clip(mcfg) is None
          and lib.tile_state(None, mcfg, 0, 0) == "inside" and lib.clip_manifest(None) is None)

    # ---- lib with real numpy
    a = np.array([[1, 2, 3], [4, -9999.0, 6], [7, 8, 9]], float)
    bad = lib.nodata_mask(a, -9999.0)
    check("lib.nodata_mask hits the declared sentinel only", bad.sum() == 1 and bad[1, 1])
    check("lib.nodata_mask: nan and -3.4e38 also caught", lib.nodata_mask(np.array([np.nan, -3.4e38, 1.0]), None).tolist() == [True, True, False])
    m = lib.fill_nodata(a, bad)
    check("lib.fill_nodata fills and names its method", a[1, 1] != -9999.0 and np.isfinite(a).all() and m in ("median (degraded)", "nearest"))
    e0v = np.full((3, 3), -9999.0); eb = lib.nodata_mask(e0v, -9999.0)
    m0 = lib.fill_nodata(e0v, eb)
    e1v = np.full((3, 3), -9999.0); m1 = lib.fill_nodata(e1v, lib.nodata_mask(e1v, -9999.0), empty_fill=-0.6)
    check("lib.fill_nodata all-nodata: default 0 unchanged, empty_fill used and named",
          m0 == "all-nodata -> 0" and (e0v == 0.0).all() and m1 == "all-nodata -> -0.6" and (e1v == -0.6).all(), f"{m0} {m1}")
    pd_ = os.path.join(tempfile.gettempdir(), "_dryrun_product")
    shutil.rmtree(pd_, ignore_errors=True)
    lib.begin_product(pd_, "test_step")
    mark = os.path.join(pd_, lib.INCOMPLETE)
    present = os.path.exists(mark) and json.load(open(mark))["step"] == "test_step"
    lib.end_product(pd_); lib.end_product(pd_)          # idempotent: a second call must not raise
    check("lib.begin_product / end_product: the marker exists only while the product is being rebuilt",
          present and not os.path.exists(mark) and lib.INCOMPLETE == "_incomplete.json")
    shutil.rmtree(pd_, ignore_errors=True)
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
        check(f"lib.tiff_info on a REAL EA tile ({os.path.relpath(real[0], REPO)}): 513x513 float32, nodata -3.4e38, georef_origin read",
              info is not None and set(info) == {"width", "height", "dtype", "nodata", "georef_origin"}
              and info["width"] == 513 and info["height"] == 513 and info["dtype"] == "float32"
              and info["nodata"] is not None and info["nodata"] < -1e30 and info["georef_origin"] is not None, str(info))
    else:
        print("  SKIP  lib.tiff_info on a real EA tile (none under data/)")
    # georef_origin: the raw EA tiles carry ModelTransformationTag 34264, GDAL-written tiles the tiepoint
    # 33922 -- both must give the corner of pixel (0, 0); and Margate's x0_y0 reused as Thanet's x10_y10
    # must sit exactly where the Thanet grid says (627680 + 10*512 - 0.5, 163080 + 11*512 + 0.5).
    for label, rel, want in (("ModelTransformationTag 34264 on raw EA margate dtm_x0_y0", ("margate", "raw", "lidar", "dtm_x0_y0.tif"), (632799.5, 168712.5)),
                             ("ModelTiepointTag 33922 on GDAL-written margate out/terrain/dtm_x0_y0", ("margate", "out", "terrain", "dtm_x0_y0.tif"), (632799.5, 168712.5)),
                             ("thanet dtm_x10_y10 (Margate's x0_y0 reused) == Thanet grid (10, 10)", ("thanet", "raw", "lidar", "dtm_x10_y10.tif"), (627680 + 10 * 512 - 0.5, 163080 + 11 * 512 + 0.5))):
        pth = os.path.join(REPO, "data", *rel)
        if os.path.exists(pth):
            got = lib.tiff_info(pth)["georef_origin"]
            check(f"lib.tiff_info georef_origin: {label} == {want}", got == want, str(got))
        else:
            print(f"  SKIP  lib.tiff_info georef_origin: {label} ({os.path.relpath(pth, REPO)} absent)")

    # ---- every product directory must declare itself complete when the run succeeded
    left = sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "**", lib.INCOMPLETE), recursive=True))
    check("no _incomplete.json survives a successful run of any site (05 and 09 remove theirs)", left == [], str(left))

except Exception:
    traceback.print_exc()
    results.append(("HARNESS CRASHED", False))
finally:
    for s in ("_dryrun_a", "_dryrun_b", "_dryrun_c"):
        p = os.path.join(SITES_DIR, f"{s}.json")
        if os.path.exists(p): os.remove(p)
    for d in glob.glob(os.path.join(SRC, "**", "__pycache__"), recursive=True):
        shutil.rmtree(d, ignore_errors=True)
    if KEEP:
        print(f"\noutput kept at {ROOT}")
    else:
        shutil.rmtree(ROOT, ignore_errors=True)

fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed" + (f", {len(skipped)} SKIPPED (not passed)" if skipped else ""))
for n in fails: print("  FAILED:", n)
for n in skipped: print("  SKIPPED:", n)
sys.exit(1 if fails else 0)
