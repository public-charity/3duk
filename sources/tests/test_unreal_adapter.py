#!/usr/bin/env python3
"""Unit tests for sources/adapters/unreal.py (PIPELINE_CHANGES.md 13.10).

    C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/test_unreal_adapter.py      -> last line OK

Standalone: numpy plus the fake in-memory GDAL/OGR of sources/tests/fake_osgeo (no real GDAL, no
network, no site data). The adapter is loaded by path with importlib -- never `import unreal`, which is
the name of Unreal's own Python module -- so its module level must do no site I/O.

Part 1 exercises the pure functions against the numbers of DESIGN.md 2 and PIPELINE_CHANGES.md 13.
Part 2 synthesises the site `_ut_unreal` (2 x 1 tiles of 64 m at 1 m, a vertical clip line at
E0 + 118 keeping the west, so tile (1, 0) straddles it with 650 clipped cells) with fixtures written
DIRECTLY in the shapes steps 05 / 06 / 07 / 09 / 10 / 11 emit (the network runs come from lib.drape_runs,
so seams and clip cuts are step 06's own), runs the adapter's main() on it and checks every product,
validates both site documents with projects/one/Tools/blender/tests/schema_check.py's validator, and
proves the refusals (range, tile shape, unknown profile id, stale clip, clipped-cells disagreement,
bands summing to 100).
"""
import importlib.util, json, math, os, shutil, sys, tempfile, unittest
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
REPO = os.path.dirname(SRC)
sys.path.insert(0, os.path.join(HERE, "fake_osgeo"))
sys.path.insert(0, SRC)
import osgeo
from osgeo import gdal, ogr
import lib


def load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def jdump(obj, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1)


def jload(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


U = load_by_path("unreal_adapter", os.path.join(SRC, "adapters", "unreal.py"))
SC = load_by_path("schema_check", os.path.join(REPO, "projects", "one", "Tools", "blender", "tests", "schema_check.py"))
SCHEMA_PATH = os.path.join(REPO, "projects", "one", "schema", "streetscape.schema.json")
PROFILES_DIR = os.path.join(REPO, "projects", "one", "schema", "profiles")
ADP = jload(U.ADP_PATH)
SITE = "_ut_unreal"
SITES_DIR = os.path.join(SRC, "config", "sites")


# =============================================================================================
# Part 1: pure functions
# =============================================================================================

class PureFunctions(unittest.TestCase):

    def test_h16_known_values_and_roundtrip(self):
        enc = U.encode_h16
        self.assertEqual(int(enc(0.0)), 32768)
        self.assertEqual(int(enc(-0.6)), 32691)
        self.assertEqual(int(enc(255.0)), 65408)
        self.assertEqual(int(enc(-1.0)), 32640)
        self.assertEqual(enc(np.zeros(3)).dtype, np.dtype("<u2"))
        z = np.random.RandomState(1).uniform(-250, 250, size=(50, 50))
        self.assertLessEqual(np.abs(U.decode_h16(enc(z)) - z).max(), 1 / 256 + 1e-12)
        self.assertEqual(float(U.decode_h16(32768)), 0.0)
        with self.assertRaises(SystemExit):
            enc(300.0)                                     # outside the window: refuse, never wrap

    def test_check_range_refusals(self):
        U.check_range([-2.91, 49.81], [-255, 255])
        for bad in ([-300.0, 10.0], [0.0, 260.0]):
            with self.assertRaises(SystemExit) as cm:
                U.check_range(bad, [-255, 255])
            self.assertIn("does not fit", str(cm.exception))

    def test_frame_table(self):
        x, y, z = U.survey_to_local(635253.6, 171027.6, 17.2, 627680, 163080)
        self.assertAlmostEqual(x, 7573.6, 6); self.assertAlmostEqual(y, 7947.6, 6); self.assertEqual(z, 17.2)
        X, Y, Z = U.local_to_ue_cm(x, y, z)
        self.assertAlmostEqual(X, 757360.0, 3); self.assertAlmostEqual(Y, -794760.0, 3); self.assertAlmostEqual(Z, 1720.0, 6)
        self.assertEqual(U.bearing_to_heading_deg(270), -180.0)
        self.assertEqual(U.bearing_to_heading_deg(131), -41.0)
        self.assertEqual(U.bearing_to_ue_yaw(131), 41.0)
        self.assertEqual(U.bearing_to_heading_deg(90), 0.0)
        self.assertEqual(U.bearing_to_ue_yaw(90), 0.0)
        for b in (0, 45, 90, 131, 180, 270, 359.5):
            self.assertAlmostEqual((U.bearing_to_ue_yaw(b) + U.bearing_to_heading_deg(b)) % 360.0, 0.0, 9)
            self.assertTrue(-180.0 <= U.bearing_to_heading_deg(b) < 180.0)
        self.assertEqual(U.FRAME, "local-metres, X east, Y north, Z up")

    def test_visibility_weight(self):
        w = U.visibility_weight(np.array([0.0, 1.0, -2.0, -1.0, 0.4]))
        self.assertEqual(w.dtype, np.uint8)
        self.assertEqual(w.tolist(), [170, 255, 0, 85, 204])
        self.assertEqual(int(U.visibility_weight(0.0)), 170)
        self.assertEqual(int(U.visibility_weight(1.0)), 255)
        self.assertEqual(int(U.visibility_weight(-2.0)), 0)
        self.assertEqual(int(U.visibility_weight(2.0, px_m=2.0)), 255)   # px-scaled ramp

    def test_catmull_rom_passes_through_knots(self):
        P = np.array([[0, 0], [10, 2], [20, -1], [30, 0]], dtype=float)
        dense = U.catmull_rom_dense(P)
        self.assertEqual(dense.shape, (32 + 31 + 31, 2))
        for p in P:
            self.assertLess(np.hypot(dense[:, 0] - p[0], dense[:, 1] - p[1]).min(), 1e-9)
        straight = U.catmull_rom_dense(np.array([[0, 0], [5, 0]], dtype=float))
        self.assertEqual(len(straight), 32); self.assertTrue(np.allclose(straight[:, 1], 0))

    def test_thin_straight_and_arc(self):
        xs = np.arange(0, 100.1, 2.0)
        idx, dev = U.thin_against_interpolant(np.c_[xs, np.zeros_like(xs)], 0.10)
        self.assertEqual(idx, [0, len(xs) - 1]); self.assertLessEqual(dev, 1e-9)
        a = np.linspace(0, math.pi / 2, 80)
        arc = np.c_[50 * np.cos(a), 50 * np.sin(a)]
        idx, dev = U.thin_against_interpolant(arc, 0.10)
        self.assertGreaterEqual(len(idx), 6); self.assertLessEqual(dev, 0.10)
        self.assertEqual(idx[0], 0); self.assertEqual(idx[-1], len(arc) - 1)
        idx2, _ = U.thin_against_interpolant(arc, 0.10, keep=(7, 40))
        self.assertTrue({7, 40} <= set(idx2))
        idx0, dev0 = U.thin_against_interpolant(arc, 0.0)
        self.assertEqual(idx0, list(range(len(arc)))); self.assertEqual(dev0, 0.0)

    def test_thin_deviation_is_measured_on_a_converged_sampling(self):
        """The deviation is measured against the interpolant SAMPLED as a polyline, and a coarse
        sampling reads the deviation of the curve a consumer reconstructs low (its chords cut inside
        the curve). The reported number must be the converged one: it is a claim about the shipped
        file, not about our sampling of it. Thanet's worst spline reads 0.099985 m at 32 samples per
        segment and 0.100277 m converged -- under the old single-density measure the 0.10 m
        acceptance passed on the sampling rather than on the geometry."""
        rs = np.random.RandomState(0)                      # irregular vertex spacing, like an OSM way
        step = rs.uniform(0.5, 12.0, 60); th = np.cumsum(rs.normal(0, 0.12, 60))
        xy = np.c_[np.cumsum(step * np.cos(th)), np.cumsum(step * np.sin(th))]
        idx, dev = U.thin_against_interpolant(xy, 0.10)
        coarse = U._dist_to_polyline(xy, U.catmull_rom_dense(xy[idx], n=32)).max()
        dense = U._dist_to_polyline(xy, U.catmull_rom_dense(xy[idx], n=512)).max()
        self.assertGreater(dense - coarse, 1e-5)           # the two measures really do differ here
        self.assertAlmostEqual(dev, dense, delta=2e-5)     # ... and the reported one is the converged one
        self.assertLessEqual(dev, 0.10)

    def test_relink_runs_after_a_degenerate_drop(self):
        raw = [(0.0, 0.0), (40.0, 0.0)]
        A = {"id": "W", "pts": [[0.0, 0.0, 1.0], [10.0, 0.0, 1.0]]}
        B = {"id": "W", "pts": [[10.0, 0.0, 1.0], [20.0, 0.0, 1.0]]}
        tail = {"id": "W", "pts": [[20.0, 0.0, 1.0]]}                  # degenerate: dropped by streetscape()
        ordered = U.order_runs(raw, [A, B, tail])
        self.assertEqual([(o["from"], o["to"]) for o in ordered], [(None, "seam"), ("seam", "seam"), ("seam", None)])
        kept = U.relink_runs([(ordered[0], A["pts"]), (ordered[1], B["pts"])])
        self.assertEqual([o["segment_index"] for o, _ in kept], [0, 1])
        # B's "seam" pointed at the dropped run: its end is a way end again, and it is not a seam join
        self.assertEqual([(o["from"], o["to"]) for o, _ in kept], [(None, "seam"), ("seam", None)])
        mid = {"id": "W", "pts": [[15.0, 0.0, 1.0]]}                   # a dropped run between two survivors
        C = {"id": "W", "pts": [[30.0, 0.0, 1.0], [40.0, 0.0, 1.0]]}
        ordered = U.order_runs(raw, [A, mid, C])
        kept = U.relink_runs([(ordered[0], A["pts"]), (ordered[2], C["pts"])])
        self.assertEqual([o["segment_index"] for o, _ in kept], [0, 1])
        self.assertEqual([(o["from"], o["to"]) for o, _ in kept], [(None, "gap"), ("gap", None)])

    def test_order_runs_shuffled_loop_and_gap(self):
        raw = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]       # closed loop
        A = {"id": "L", "pts": [[0.0, 0.0, 1.0], [25.0, 0.0, 1.0], [50.0, 0.0, 1.0]]}
        B = {"id": "L", "pts": [[50.0, 0.0, 1.0], [100.0, 0.0, 1.0], [100.0, 50.0, 1.0]]}
        C = {"id": "L", "pts": [[100.0, 50.0, 1.0], [100.0, 100.0, 1.0], [0.0, 100.0, 1.0], [0.0, 60.0, 1.0]]}
        D = {"id": "L", "pts": [[0.0, 30.0, 1.0], [0.0, 0.0, 1.0]]}                    # after an excursion: gap
        out = U.order_runs(raw, [C, A, D, B])
        self.assertEqual([o["rec"] is r for o, r in zip(out, (A, B, C, D))], [True] * 4)
        self.assertEqual([o["segment_index"] for o in out], [0, 1, 2, 3])
        self.assertEqual([(o["from"], o["to"]) for o in out], [(None, "seam"), ("seam", "seam"), ("seam", "gap"), ("gap", None)])
        self.assertEqual(out[0]["u"], 0.0)                                              # raw vertex 0 keys to segment 0
        self.assertTrue(all(o["dist_m"] < 1e-9 for o in out))

    def test_nearest_z(self):
        chain = np.array([[0, 0, 10.0], [10, 0, 11.0], [20, 0, 12.0]])
        self.assertEqual(U.nearest_z((11.0, 0.5), chain), 11.0)
        self.assertEqual(U.nearest_z((100.0, 0.0), chain), 12.0)

    def test_clip_polyline_inserts_crossing(self):
        cfg = {"origin": {"E": 1000.0, "N": 2000.0}, "tile_m": 64, "nx": 2, "ny": 1}
        clip = lib.parse_clip({"clip": {"type": "halfplane", "line": [[1118.0, 2000.0], [1118.0, 2064.0]], "keep": "left"}})
        pieces, dropped = U.clip_polyline([(1090.0, 2055.0), (1126.0, 2055.0)], cfg, clip)
        self.assertEqual(len(pieces), 1); self.assertEqual(dropped, 1)
        self.assertEqual([(p[0], p[1], p[3]) for p in pieces[0]], [(1090.0, 2055.0, False), (1118.0, 2055.0, True)])
        self.assertAlmostEqual(pieces[0][-1][2], 28.0, 9)                                # u of the crossing
        # grid clip: a way leaving the grid to the north and coming back gives two pieces with crossings
        pieces, dropped = U.clip_polyline([(1020.0, 2050.0), (1040.0, 2070.0), (1060.0, 2050.0)], cfg, None)
        self.assertEqual(len(pieces), 2); self.assertEqual(dropped, 1)
        self.assertAlmostEqual(pieces[0][-1][1], 2064.0, 9); self.assertAlmostEqual(pieces[1][0][1], 2064.0, 9)
        # wholly outside the clip -> nothing
        pieces, dropped = U.clip_polyline([(1120.0, 2010.0), (1125.0, 2020.0)], cfg, clip)
        self.assertEqual(pieces, []); self.assertEqual(dropped, 2)

    def test_parse_height_m(self):
        self.assertEqual(U.parse_height_m("0.5"), 0.5)
        self.assertEqual(U.parse_height_m("15 cm"), 0.15)
        self.assertEqual(U.parse_height_m("2 m"), 2.0)
        self.assertAlmostEqual(U.parse_height_m("6'"), 1.8288, 6)
        self.assertAlmostEqual(U.parse_height_m("3 ft"), 0.9144, 6)
        self.assertEqual(U.parse_height_m("1200mm"), 1.2)
        self.assertIsNone(U.parse_height_m("tall")); self.assertIsNone(U.parse_height_m(None))

    def test_classify_barrier(self):
        S = ADP["streetscape"]
        self.assertEqual(U.classify_barrier("wall", {"h": 0.5, "h_src": "osm", "wall": "brick"}, S), ("brick_wall", 0.5, 0.215, "brick_red", "osm"))
        self.assertEqual(U.classify_barrier("wall", {"h": 1.8, "h_src": "default", "material": "stone"}, S)[0], "stone_wall")
        self.assertEqual(U.classify_barrier("wall", {"h": 1.8, "h_src": "default"}, S)[0], "brick_wall")
        t = U.classify_barrier("fence", {"fence_type": "chain_link"}, S)
        self.assertEqual(t, ("chain_link", 1.8, 0.05, "chain_link", "adapter_default"))
        self.assertEqual(U.classify_barrier("fence", {"height": "1.2 m"}, S)[1:], (1.2, 0.05, "wood_fence", "adapter_parsed"))
        self.assertEqual(U.classify_barrier("retaining_wall", {"h": 1.5, "h_src": "default"}, S)[3], "concrete_wall")
        self.assertEqual(U.classify_barrier("hedge", {"h": 1.2, "h_src": "osm"}, S), ("hedge", 1.2, 0.8, None, "osm"))
        self.assertEqual(U.classify_barrier("kerb", {"h": 0.12, "h_src": "default"}, S)[0], "kerb")
        self.assertIsNone(U.classify_barrier("cattle_grid", {}, S))

    def test_profile_ids_for_sidewalk_rule(self):
        S = ADP["streetscape"]
        f = lambda cls, tags: U.profile_ids_for("roads", cls, tags, S)
        self.assertEqual(f("residential", {"sidewalk": "both"}), {"road": "road_residential", "edge_left": "edge_uk_kerb", "edge_right": "edge_uk_kerb", "hedge_left": None, "hedge_right": None})
        self.assertEqual(f("residential", {})["edge_right"], "edge_uk_kerb")
        self.assertEqual((f("residential", {"sidewalk": "left"})["edge_left"], f("residential", {"sidewalk": "left"})["edge_right"]), ("edge_uk_kerb", None))
        self.assertEqual((f("residential", {"sidewalk:right": "yes"})["edge_left"], f("residential", {"sidewalk:right": "yes"})["edge_right"]), (None, "edge_uk_kerb"))
        self.assertEqual((f("primary", {"sidewalk": "no"})["edge_left"], f("primary", {"sidewalk": "separate"})["edge_right"]), (None, None))
        self.assertEqual(f("footway", {"sidewalk": "both"}), {"road": "path_footway", "edge_left": None, "edge_right": None, "hedge_left": None, "hedge_right": None})
        self.assertEqual(f("service", {})["road"], "road_service")
        with self.assertRaises(SystemExit):
            f("bus_guideway", {})
        # rail: profile_ids_for leaves the road id to the caller (one gauge path -- rail_profile_for)
        self.assertEqual(U.profile_ids_for("rail", "rail", {"gauge": "1.435"}, S),
                         {"road": None, "edge_left": None, "edge_right": None, "hedge_left": None, "hedge_right": None})
        self.assertEqual(U.rail_profile_for(0.381, S), ("rail_standard", True))
        self.assertEqual(U.rail_profile_for(1.435, S), ("rail_standard", False))
        self.assertEqual(U.profile_ids_for("barriers", "hedge", {}, S)["hedge_left"], "hedge_privet")
        self.assertEqual(U.profile_ids_for("barriers", "kerb", {}, S)["edge_left"], "edge_uk_kerb")
        self.assertEqual(U.profile_ids_for("barriers", "wall", {}, S)["edge_left"], "edge_barrier_only")

    def test_load_profiles_and_settings(self):
        prof = U.load_profiles(PROFILES_DIR)
        ids = set(prof["road"]) | set(prof["edge"]) | set(prof["hedge"])
        self.assertEqual(len(ids), 20)
        self.assertIn("rail_standard", prof["road"]); self.assertIn("edge_barrier_only", prof["edge"]); self.assertIn("hedge_privet", prof["hedge"])
        tuning = jload(os.path.join(SRC, "config", "tuning.json"))
        U.check_adapter_settings(ADP, tuning, prof)
        bad = json.loads(json.dumps(ADP)); bad["streetscape"]["road_profile_by_class"]["residential"] = "road_nope"
        with self.assertRaises(SystemExit) as cm:
            U.check_adapter_settings(bad, tuning, prof)
        self.assertIn("road_nope", str(cm.exception))
        tmp = tempfile.mkdtemp(prefix="ut-prof-")
        try:
            jdump({"kind": "edge", "id": "a", "profile": {}}, os.path.join(tmp, "a.json"))
            jdump({"kind": "road", "id": "a", "profile": {}}, os.path.join(tmp, "b.json"))   # id != file name
            with self.assertRaises(SystemExit):
                U.load_profiles(tmp)
            os.remove(os.path.join(tmp, "b.json"))
            jdump({"kind": "road", "id": "b"}, os.path.join(tmp, "b.json"))                  # bad shape
            with self.assertRaises(SystemExit):
                U.load_profiles(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_git_sha_is_a_string_and_marks_uncommitted_source(self):
        sha = U.git_sha()
        self.assertIsInstance(sha, str); self.assertTrue(sha)
        import subprocess
        d = subprocess.run(["git", "status", "--porcelain", "--", "sources/adapters/unreal.py", "sources/adapters/unreal.json"],
                           cwd=REPO, capture_output=True, text=True)
        if d.returncode == 0 and sha != "unknown":     # a product from uncommitted code must say so
            self.assertEqual(sha.endswith("-dirty"), bool(d.stdout.strip()), sha)


# =============================================================================================
# Part 2: the synthetic site _ut_unreal
# =============================================================================================

E0, N0, T, NX, NY, RES = 400000.0, 100000.0, 64, 2, 1, 65
ND = -9999.0
CLIP = {"type": "halfplane", "line": [[E0 + 118, N0], [E0 + 118, N0 + 64]], "keep": "left"}     # keep the west
WKT = "FAKE_WKT[EPSG:27700]"            # what osr.SpatialReference.ExportToWkt() gives steps 05/09 here


def zfun(E, N):
    return 2.0 + 0.05 * (np.asarray(E) - E0) + 0.02 * (np.asarray(N) - N0)


def jsonl(path, recs):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")


class SyntheticSite(unittest.TestCase):
    """Fixtures written directly in the pipeline's shapes, then the adapter's main() once for the class."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="3duk-ut-unreal-")
        lib.ROOT = cls.root
        os.environ["SITE"] = SITE
        cls.cfg_path = os.path.join(SITES_DIR, f"{SITE}.json")
        jdump({"crs": "EPSG:27700", "origin": {"E": E0, "N": N0}, "tile_m": T, "nx": NX, "ny": NY, "grid_res": RES,
                   "bbox_wgs84": [51.0, 1.0, 51.1, 1.1], "vertical_datum": "ODN", "water_level": -50.0, "clip": CLIP,
                   "wcs": {"dtm": {"url": "x", "coverage": "x"}, "dsm": {"url": "x", "coverage": "x"}}},
                  cls.cfg_path)
        cls.cfg = lib.load(); cls.P = lib.paths(cls.cfg); cls.clip = lib.parse_clip(cls.cfg)
        lib.mkdirs(*[cls.P[k] for k in ("raw", "interim", "derived", "out")])
        cls.src = cls.P["out"]
        cls.build_terrain(); cls.build_coast(); cls.build_networks(); cls.build_massing_furniture()
        cls.out = os.path.join(cls.src, "unreal")
        cls.rc = U.main([])
        cls.L = os.path.join(cls.out, "landscape"); cls.S = os.path.join(cls.out, "streetscape")
        cls.lm = jload(os.path.join(cls.L, "landscape_manifest.json"))
        cls.sm = jload(os.path.join(cls.S, "streetscape_manifest.json"))
        cls.docs = {(i, j): jload(os.path.join(cls.S, f"site_x{i}_y{j}.json")) for (i, j) in ((0, 0), (1, 0))}
        cls.sp = {s["id"]: s for d in cls.docs.values() for s in d["splines"]}
        cls.um = jload(os.path.join(cls.out, "unreal_manifest.json"))

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.cfg_path): os.remove(cls.cfg_path)
        shutil.rmtree(cls.root, ignore_errors=True)
        for d in (os.path.join(SRC, "adapters", "__pycache__"), os.path.join(HERE, "__pycache__")):
            shutil.rmtree(d, ignore_errors=True)

    # ---- fixtures -------------------------------------------------------------------------------
    @classmethod
    def tile_arrays(cls):
        out = {}
        for i in range(NX):
            c = np.arange(RES); r = np.arange(RES)
            EE, NN = np.meshgrid(E0 + i * T + c, N0 + T - r)         # row 0 = north
            a = zfun(EE, NN).astype(np.float32)
            keep = lib.cell_mask(cls.clip, (E0 + i * T - 0.5, 1.0, 0.0, N0 + T + 0.5, 0.0, -1.0), RES, RES)
            out[i] = (a, keep)
        return out

    @classmethod
    def build_terrain(cls):
        d = os.path.join(cls.src, "terrain"); lib.mkdirs(d)
        tiles, total, rng = [], 0, [1e9, -1e9]
        for i, (a, keep) in cls.tile_arrays().items():
            arr = a.copy(); arr[~keep] = ND
            ds = gdal.GetDriverByName("GTiff").Create(os.path.join(d, f"dtm_x{i}_y0.tif"), RES, RES, 1, gdal.GDT_Float32)
            ds.SetGeoTransform((E0 + i * T - 0.5, 1.0, 0.0, N0 + T + 0.5, 0.0, -1.0)); ds.SetProjection(WKT)
            ds.GetRasterBand(1).SetNoDataValue(ND); ds.GetRasterBand(1).WriteArray(arr)
            n_clip = int((~keep).sum()); total += n_clip
            kept = a[keep]; rng = [min(rng[0], float(kept.min())), max(rng[1], float(kept.max()))]
            tiles.append({"x": i, "y": 0, "file": f"dtm_x{i}_y0.tif", "min_m": round(float(kept.min()), 2), "max_m": round(float(kept.max()), 2),
                          "nodata_cells": 0, "fill": "none", "slope_max_deg": 3.1, "slope_p99_deg": 3.1, "cells_over_45deg": 0,
                          "clip_state": lib.tile_state(cls.clip, cls.cfg, i, 0), "clipped_cells": n_clip})
        cls.terrain_manifest = {"site": SITE, "crs": "EPSG:27700", "origin": {"E": E0, "N": N0}, "tile_m": T, "res": RES, "vertical_datum": "ODN",
                                "elevation_units": "metres", "range_m": [round(rng[0], 2), round(rng[1], 2)],
                                "slope_qa": {"max_deg": 3.1, "pct_cells_over_45deg": 0.0, "note": "test"},
                                "nodata": ND, "clip": lib.clip_manifest(cls.clip), "tiles_clipped": [], "clipped_cells_total": total,
                                "clip_note": "test", "tiles_missing": [], "tiles": tiles}
        cls.tm_path = os.path.join(d, "terrain_manifest.json")
        jdump(cls.terrain_manifest, cls.tm_path)

    @classmethod
    def build_coast(cls):
        d = os.path.join(cls.src, "coast"); lib.mkdirs(d)
        CR = 32; cell = T / CR
        cls.ground = {}
        for i in range(NX):
            r = np.arange(CR)[:, None] * np.ones((1, CR), dtype=int)
            grass = (255 - 7 * r).astype(np.uint8); sand = (7 * r).astype(np.uint8)
            rock = np.zeros((CR, CR), np.uint8); water = np.zeros((CR, CR), np.uint8)
            if i == 1:
                grass[3, 4], sand[3, 4] = 76, 178                                     # fractions 0.3 / 0.7 -> sum 254
                km = lib.cell_mask(cls.clip, (E0 + i * T, cell, 0.0, N0 + T, 0.0, -cell), CR, CR)
                for b in (grass, sand, rock, water): b[~km] = 0
            ds = gdal.GetDriverByName("GTiff").Create(os.path.join(d, f"ground_x{i}_y0.tif"), CR, CR, 4, gdal.GDT_Byte)
            ds.SetGeoTransform((E0 + i * T, cell, 0.0, N0 + T, 0.0, -cell)); ds.SetProjection(WKT)
            for b, arr in enumerate((grass, sand, rock, water)):
                ds.GetRasterBand(b + 1).WriteArray(arr)
            cls.ground[i] = ds
        jdump({"site": SITE, "crs": "EPSG:27700", "water_level": -50.0, "water_tolerance_m": 0.3, "class_res": CR, "tile_m": T,
                   "origin": {"E": E0, "N": N0}, "row_order": "north-first (GeoTIFF convention)", "bands": ["grass", "sand", "rock", "water"],
                   "thresholds": {"foreshore_max_odn": -50.0, "rock_slope_deg": [25.0, 45.0]}, "water_tiles": [], "tiles_without_dtm": [],
                   "missing_tiles_are_water": False, "coastline_km_in_area": 0.0, "clip": lib.clip_manifest(cls.clip), "tiles_clipped": [],
                   "clipped_cells": 5 * CR, "bands_note": "test"},
                  os.path.join(d, "coast_manifest.json"))

    @classmethod
    def build_networks(cls):
        d = os.path.join(cls.src, "networks"); lib.mkdirs(d)
        L = lambda *pts: [(E0 + x, N0 + y) for x, y in pts]
        sample = lambda e, n: (float(zfun(e, n)), True)
        cfg = cls.cfg
        roads = [  # id, cls, raw, name, other_tags, w, pav
            ("rd1", "residential", L((10, 30), (100, 30)), "Test Road", '"sidewalk"=>"both","lane_markings"=>"no","lit"=>"yes"', 6.0, 1.5),
            ("rd2", "service", L((100, 30), (100, 50)), None, '"service"=>"driveway"', 3.5, 0.0),
            ("rd3", "footway", L((100, 30), (110, 20)), None, None, 2.0, 0.0),
            ("rd4", "residential", L((10, 10), (10, 30)), "Join Road", None, 6.0, 1.5),
            ("rd5", "tertiary", L((20, 50), (40, 70), (60, 50)), "Gap Road", None, 7.0, 1.8),
            ("rd6", "service", L((30, 10), (40, 10), (40, 20), (30, 20), (30, 10)), "Loop", None, 3.5, 0.0),
            ("rd7", "residential", L((90, 55), (126, 55)), "Cut Road", '"sidewalk"=>"right"', 6.0, 1.5),
            ("rd8", "steps", L((50, 40), (50, 46)), None, None, 2.0, 0.0),
        ]
        rails = [  # id, cls, raw, name, other_tags, extra record fields
            ("rl1", "rail", L((5, 58), (110, 58)), "Test Line", '"gauge"=>"1435","electrified"=>"rail","usage"=>"main","tracks"=>"2"',
             {"gauge": 1.435, "gauge_src": "osm", "tracks": 2, "electrified": "rail", "service": None, "usage": "main", "bridge": False, "tunnel": False}),
            ("rl2", "miniature", L((70, 5), (90, 5)), None, '"gauge"=>"381"',
             {"gauge": 0.381, "gauge_src": "osm", "tracks": None, "electrified": None, "service": None, "usage": None, "bridge": False, "tunnel": False}),
            ("rl3", "disused", L((20, 45), (30, 45)), None, None,
             {"gauge": 1.435, "gauge_src": "default", "tracks": None, "electrified": None, "service": None, "usage": None, "bridge": False, "tunnel": False}),
        ]
        barriers = [  # id, cls, raw, name, other_tags, extra record fields (h omitted on bf2 on purpose)
            ("bw1", "wall", L((70, 40), (70, 50)), None, '"height"=>"0.5","wall"=>"brick"', {"h": 0.5, "h_src": "osm", "material": None, "fence_type": None, "wall": "brick"}),
            ("bf1", "fence", L((80, 40), (90, 40)), None, '"fence_type"=>"chain_link"', {"h": 1.5, "h_src": "default", "material": None, "fence_type": "chain_link", "wall": None}),
            ("bh1", "hedge", L((20, 20), (25, 25)), None, '"height"=>"1.2"', {"h": 1.2, "h_src": "osm", "material": None, "fence_type": None, "wall": None}),
            ("bk1", "kerb", L((5, 5), (15, 5)), None, '"height"=>"15 cm"', {"h": 0.15, "h_src": "osm", "material": None, "fence_type": None, "wall": None}),
            ("bx1", "cattle_grid", L((75, 10), (76, 10)), None, None, {"h": 0.3, "h_src": "default", "material": None, "fence_type": None, "wall": None}),
            ("bf2", "fence", L((80, 45), (90, 45)), None, None, {"material": None, "fence_type": None, "wall": None}),
        ]
        cls.raw = {}
        buckets = {"roads": {}, "rail": {}, "barriers": {}}
        counters = {}
        n_out_clip = 0
        for (wid, c, raw, name, ot, w, pav) in roads:
            cls.raw[wid] = (raw, "highway", c, name, ot)
            pts = lib.densify(raw, 2.0)
            before = counters.get("outside_clip", 0)
            for tile, run, gap in lib.drape_runs(pts, cfg, sample, cls.clip, counters):
                buckets["roads"].setdefault(tile, []).append({"id": wid, "cls": c, "w": w, "pav": pav, "name": name, "bridge": False, "tunnel": False, "z_gap": gap, "pts": run})
        for (wid, c, raw, name, ot, extra) in rails:
            cls.raw[wid] = (raw, "railway", c, name, ot)
            for tile, run, gap in lib.drape_runs(lib.densify(raw, 2.0), cfg, sample, cls.clip, counters):
                buckets["rail"].setdefault(tile, []).append({"id": wid, "cls": c, **extra, "name": name, "z_gap": gap, "pts": run})
        for (wid, c, raw, name, ot, extra) in barriers:
            cls.raw[wid] = (raw, "barrier", c, name, ot)
            for tile, run, gap in lib.drape_runs(lib.densify(raw, 2.0), cfg, sample, cls.clip, counters):
                buckets["barriers"].setdefault(tile, []).append({"id": wid, "cls": c, **extra, "name": name, "z_gap": gap, "pts": run})
        # the junction disc where rd1, rd2 and rd3 meet
        J = (E0 + 100, N0 + 30)
        buckets["roads"].setdefault((1, 0), []).append({"cls": "_junction", "r": 3.4, "pts": [[J[0], J[1], round(float(zfun(*J)), 2)]]})
        for layer, prefix in (("roads", "roads"), ("rail", "rail"), ("barriers", "barriers")):
            for (i, j), recs in buckets[layer].items():
                jsonl(os.path.join(d, f"{prefix}_x{i}_y{j}.jsonl"), recs)
        cls.counters = counters
        n_roads = sum(len(v) for v in buckets["roads"].values())
        jdump({"site": SITE, "crs": "EPSG:27700", "coordinates": "[easting, northing, elevation] in CRS metres", "origin": {"E": E0, "N": N0},
                   "tile_m": T, "segments": n_roads, "tiles": len(buckets["roads"]), "length_km": 0.4, "junctions": 1,
                   "smoothing": {"densify_step_m": 8.0, "chaikin_iters": 2}, "widths_m": {"residential": [6.0, 1.5]},
                   "vertices_without_dtm": 0, "vertices_outside_grid": counters.get("outside_grid", 0),
                   "clip": lib.clip_manifest(cls.clip), "vertices_outside_clip": counters.get("outside_clip", 0), "junctions_outside_clip": 0},
                  os.path.join(d, "networks_manifest.json"))
        jdump({"site": SITE, "crs": "EPSG:27700", "origin": {"E": E0, "N": N0}, "tile_m": T,
                   "layers": {"rail": {"segments": sum(len(v) for v in buckets["rail"].values()), "tiles": len(buckets["rail"])},
                              "barriers": {"segments": sum(len(v) for v in buckets["barriers"].values()), "tiles": len(buckets["barriers"])}},
                   "clip": lib.clip_manifest(cls.clip)}, os.path.join(d, "linear_manifest.json"))
        # the GeoPackage: raw geometry + other_tags, in the fake OGR registry (and a placeholder file for need())
        lines = ogr.Layer("lines", ["osm_id", "highway", "railway", "barrier", "name", "other_tags"])
        for wid, (raw, col, c, name, ot) in cls.raw.items():
            lines.CreateFeature(ogr.Feature(lines.defn, {"osm_id": wid, col: c, "name": name, "other_tags": ot}, ogr.Geometry("LINESTRING", raw)))
        ds = ogr.DataSource(); ds.layers = {"lines": lines}
        osgeo.VECTORS[osgeo._norm(cls.P["gpkg"])] = ds
        open(cls.P["gpkg"], "ab").close()

    @classmethod
    def build_massing_furniture(cls):
        d = os.path.join(cls.src, "massing"); lib.mkdirs(d)
        jsonl(os.path.join(d, "buildings_x0_y0.jsonl"),
              [{"id": "cb1", "name": None, "type": "house", "h": 6.8, "ridge": 9.5, "eaves": 5.0, "base_z": 4.4, "skirt": 3.9, "lidar_px": 60,
                "levels": 2, "roof": "gabled", "src": "lidar_p50", "seed": 1,
                "rings": [{"hole": False, "pts": [[E0 + 20, N0 + 40], [E0 + 30, N0 + 40], [E0 + 30, N0 + 48], [E0 + 20, N0 + 48], [E0 + 20, N0 + 40]]}]}])
        jdump({"site": SITE, "crs": "EPSG:27700", "coordinates": "CRS eastings/northings, metres", "origin": {"E": E0, "N": N0}, "tile_m": T,
                   "height_calib": {"intercept": 2.5, "m_per_level": 3.0, "source": "config", "dispute_m": 4.0}, "buildings": 1, "tiles": 1,
                   "outside_grid": 0, "by_height_source": {"lidar_p50": 1}, "buildings_without_lidar": 0, "buildings_without_dsm": 0,
                   "clip": lib.clip_manifest(cls.clip), "outside_clip": 0}, os.path.join(d, "massing_manifest.json"))
        d = os.path.join(cls.src, "furniture"); lib.mkdirs(d)
        jsonl(os.path.join(d, "furniture_x0_y0.jsonl"),
              [{"id": "cn1", "prop": "LitterBin", "name": None, "e": E0 + 30, "n": N0 + 34.25, "z": 5.0, "bearing": 270.0, "src": "kerb", "d": 4.25,
                "cls": "residential", "nudged": False}])
        jdump({"site": SITE, "crs": "EPSG:27700", "origin": {"E": E0, "N": N0}, "tile_m": T, "placed": 1, "tiles": 1, "outside_grid": 0,
                   "outside_clip": 0, "by_height_source": {"kerb": 1}, "kerb_m": 0.12, "snap_m": 25.0},
                  os.path.join(cls.src, "qa_furniture.json"))

    # ---- landscape ------------------------------------------------------------------------------
    def test_00_ran(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual(self.um["warnings"], [])

    def test_heightmaps_decode_north_first_and_share_the_seam_column(self):
        arrs = self.tile_arrays()
        hm = {}
        for i in range(NX):
            h = np.fromfile(os.path.join(self.L, f"hm_x{i}_y0.r16"), dtype="<u2")
            self.assertEqual(h.size, RES * RES); self.assertEqual(os.path.getsize(os.path.join(self.L, f"hm_x{i}_y0.r16")), RES * RES * 2)
            hm[i] = h.reshape(RES, RES)
            z = U.decode_h16(hm[i])
            a, keep = arrs[i]
            self.assertLessEqual(np.abs(z - a)[keep].max(), 1 / 256)                       # kept cells: within the quantum
            self.assertTrue(np.all(np.isfinite(z)))                                          # clipped cells were filled, never left at -9999
            self.assertLessEqual(np.abs(z[0] - zfun(E0 + i * T + np.arange(RES), N0 + T))[keep[0]].max(), 1 / 256)   # row 0 = north
            self.assertGreater(float(np.abs(z[-1] - zfun(E0 + i * T + np.arange(RES), N0 + T))[keep[0]].max()), 1.0)  # not the south row
        self.assertTrue(np.array_equal(hm[0][:, -1], hm[1][:, 0]))                           # shared column bit-identical
        t1 = [t for t in self.lm["tiles"] if t["x"] == 1][0]
        self.assertEqual((t1["h16_min"], t1["h16_max"]), (int(hm[1].min()), int(hm[1].max())))
        self.assertEqual(t1["clip_fill"], "nearest")

    def test_clip_mask_zero_count_equals_clipped_cells(self):
        m0 = np.fromfile(os.path.join(self.L, "clip_x0_y0.r8"), dtype=np.uint8).reshape(RES, RES)
        m1 = np.fromfile(os.path.join(self.L, "clip_x1_y0.r8"), dtype=np.uint8).reshape(RES, RES)
        self.assertTrue((m0 == 255).all())
        self.assertEqual(int((m1 == 0).sum()), 650)
        t1 = [t for t in self.lm["tiles"] if t["x"] == 1][0]
        self.assertEqual(t1["clipped_cells"], 650); self.assertEqual(self.lm["clipped_cells_total"], 650)
        self.assertTrue((m1[:, 55:] == 0).all() and (m1[:, :55] == 255).all())              # E > E0 + 118 is the cut
        self.assertEqual(t1["clip_state"], "straddle"); self.assertEqual([t for t in self.lm["tiles"] if t["x"] == 0][0]["clip_state"], "inside")

    def test_visibility_mask_for_the_straddle_tile_only(self):
        self.assertFalse(os.path.exists(os.path.join(self.L, "vis_x0_y0.r8")))
        v = np.fromfile(os.path.join(self.L, "vis_x1_y0.r8"), dtype=np.uint8).reshape(RES, RES)
        self.assertTrue((v[:, 54] == 170).all())                                              # on the line (E0 + 118)
        self.assertTrue((v[:, 55:] == 255).all())                                             # 1 m into the cut
        self.assertTrue((v[:, 53] == 85).all())                                               # 1 m into the kept side
        self.assertTrue((v[:, :53] == 0).all())                                               # 2 m and more into the kept side
        self.assertEqual([t["files"]["vis"] for t in self.lm["tiles"]], [None, "vis_x1_y0.r8"])

    def test_weights_unflipped_and_the_254_cell_accepted(self):
        g0 = np.fromfile(os.path.join(self.L, "weight_grass_x0_y0.r8"), dtype=np.uint8).reshape(32, 32)
        s0 = np.fromfile(os.path.join(self.L, "weight_sand_x0_y0.r8"), dtype=np.uint8).reshape(32, 32)
        self.assertEqual(int(g0[0, 0]), 255); self.assertEqual(int(g0[31, 0]), 255 - 7 * 31)           # row 0 north, no flip
        self.assertTrue(np.array_equal(g0, self.ground[0].GetRasterBand(1).ReadAsArray()))
        self.assertTrue(np.array_equal(s0, self.ground[0].GetRasterBand(2).ReadAsArray()))
        g1 = np.fromfile(os.path.join(self.L, "weight_grass_x1_y0.r8"), dtype=np.uint8).reshape(32, 32)
        s1 = np.fromfile(os.path.join(self.L, "weight_sand_x1_y0.r8"), dtype=np.uint8).reshape(32, 32)
        self.assertEqual((int(g1[3, 4]), int(s1[3, 4])), (76, 178))
        self.assertTrue((g1[:, 27:] == 0).all())
        self.assertEqual(self.lm["weight_sum_histogram"], {"255": 1024 + 863, "254": 1, "253": 0, "252": 0, "0": 160})
        self.assertEqual(self.lm["weight_res"], 32)
        self.assertEqual(self.lm["tiles"][0]["files"]["weights"], {b: f"weight_{b}_x0_y0.r8" for b in ("grass", "sand", "rock", "water")})
        self.assertEqual(len([f for f in os.listdir(self.L) if f.startswith("weight_")]), 8)

    def test_landscape_manifest_keys(self):
        m = self.lm
        for k in ("site", "crs", "origin", "vertical_datum", "tile_m", "res", "nx", "ny", "weight_res", "px_m", "frame", "frame_note", "heightmap",
                  "clip_mask", "visibility", "weightmaps", "weight_sum_histogram", "range_m", "elevation_units", "water_level", "pad_value_h16",
                  "pad_visibility", "ue_import_unpadded", "clip", "tiles_clipped", "clipped_cells_total", "source_nodata", "slope_qa",
                  "tiles_missing", "water_tiles", "tiles_without_ground_raster", "tiles"):
            self.assertIn(k, m)
        for k in ("file", "dtype", "shape", "row0", "col0", "row_flip_for_ue", "z_encoding", "range_limit_m", "window_m"):
            self.assertIn(k, m["heightmap"])
        for k in ("formula", "per_unit", "offset", "scale_z_cm", "decode", "quantum_m", "max_roundtrip_error_m"):
            self.assertIn(k, m["heightmap"]["z_encoding"])
        for k in ("files", "res", "row0", "bands", "sum", "alphamap_type", "importer_note"):
            self.assertIn(k, m["weightmaps"])
        for k in ("x", "y", "files", "min_m", "max_m", "h16_min", "h16_max", "clip_state", "clipped_cells", "clip_fill", "source_nodata_cells",
                  "source_fill", "slope_max_deg", "slope_p99_deg", "cells_over_45deg", "quad_origin"):
            self.assertIn(k, m["tiles"][0])
        self.assertEqual((m["res"], m["nx"], m["ny"], m["tile_m"], m["px_m"]), (RES, NX, NY, T, 1.0))
        self.assertEqual(m["heightmap"]["row0"], "north"); self.assertIs(m["heightmap"]["row_flip_for_ue"], False)
        self.assertEqual(m["heightmap"]["z_encoding"]["per_unit"], 128); self.assertEqual(m["heightmap"]["z_encoding"]["offset"], 32768)
        self.assertEqual(m["pad_value_h16"], int(U.encode_h16(-50.0))); self.assertEqual(m["pad_visibility"], "hidden")
        self.assertEqual(m["clip"], lib.clip_manifest(self.clip)); self.assertEqual(m["source_nodata"], ND)
        self.assertEqual(m["ue_import_unpadded"]["verts"], [NX * (RES - 1) + 1, NY * (RES - 1) + 1])
        self.assertEqual(m["ue_import_unpadded"]["actor_location_cm"], [0, -100 * T * NY, 0])
        self.assertEqual([t["quad_origin"] for t in m["tiles"]], [[0, 0], [T, 0]])
        self.assertEqual(m["frame"], U.FRAME)

    # ---- streetscape ----------------------------------------------------------------------------
    def test_documents_validate_against_the_schema(self):
        schema = jload(SCHEMA_PATH)
        V = SC.SchemaValidator(schema)
        prof = U.load_profiles(PROFILES_DIR)
        library_ids = {k: set(v) for k, v in prof.items()}
        self.assertEqual(sorted(self.docs), [(0, 0), (1, 0)]); self.assertEqual(self.sm["documents"], 2)
        for tile, doc in self.docs.items():
            errs = V.validate(doc, schema, "$")
            self.assertEqual(errs, [], f"site_x{tile[0]}_y{tile[1]}.json: {errs[:5]}")
            rep = SC.Report()
            SC.semantic_document_checks(doc, f"site_x{tile[0]}_y{tile[1]}.json", rep, library_ids)
            self.assertEqual(rep.errors, [])
            self.assertEqual(doc["frame"], U.FRAME); self.assertEqual(doc["schema_version"], "1.0.0")
            self.assertTrue(doc["generator"].startswith("sources/adapters/unreal.py@"))
            self.assertEqual(doc["_tile"]["x"], tile[0]); self.assertEqual(doc["_tile"]["bounds_local"], [tile[0] * T, 0, (tile[0] + 1) * T, T])
            for kind in ("road", "edge", "hedge"):
                self.assertEqual(sorted(doc["profiles"][kind]), doc["_profile_ids_used"][kind])
                for pid, p in doc["profiles"][kind].items():
                    self.assertEqual(p, prof[kind][pid])                                  # inlined verbatim from the library
            self.assertIn("materials", doc)
        self.assertFalse(V.unsupported)

    def test_ids_profiles_segments_and_points(self):
        a, b = self.sp["roads:rd1:0"], self.sp["roads:rd1:1"]
        self.assertEqual((a["source"]["tile"], b["source"]["tile"]), ([0, 0], [1, 0]))
        self.assertEqual((a["source"]["segment_index"], a["source"]["segment_count"], b["source"]["segment_index"]), (0, 2, 1))
        self.assertEqual(a["source"]["name"], "Test Road"); self.assertEqual(a["source"]["cls"], "residential"); self.assertEqual(a["source"]["osm_id"], "rd1")
        self.assertEqual(a["source"]["tags"], {"sidewalk": "both", "lane_markings": "no", "lit": "yes"})
        self.assertEqual(a["profile_ids"], {"road": "road_residential", "edge_left": "edge_uk_kerb", "edge_right": "edge_uk_kerb", "hedge_left": None, "hedge_right": None})
        self.assertEqual(a["segments"], [{"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "both", "edge": {"pavement_width_m": 1.5}, "road": {"markings": []}}])
        for p in a["points"]:
            self.assertEqual(sorted(p), ["_z_06", "width_m", "x", "y"]); self.assertEqual(p["width_m"], 6.0)
        self.assertEqual((a["points"][0]["x"], a["points"][0]["y"]), (10.0, 30.0)); self.assertEqual((a["points"][-1]["x"], a["points"][-1]["y"]), (64.0, 30.0))
        self.assertEqual((b["points"][0]["x"], b["points"][-1]["x"]), (64.0, 100.0))
        self.assertAlmostEqual(a["points"][0]["_z_06"], float(zfun(E0 + 10, N0 + 30)), 2)
        self.assertEqual(len(a["points"]), 2)                                                 # a straight run thins to its ends
        self.assertEqual(a["drop_kerbs"], [])
        # service with pav 0 keeps the kerb with a 0 m pavement; footway has no edges and no segment
        self.assertEqual(self.sp["roads:rd2:0"]["segments"], [{"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "both", "edge": {"pavement_width_m": 0.0}}])
        self.assertEqual(self.sp["roads:rd3:0"]["profile_ids"], {"road": "path_footway", "edge_left": None, "edge_right": None, "hedge_left": None, "hedge_right": None})
        self.assertEqual(self.sp["roads:rd3:0"]["segments"], [])
        # sidewalk=right: the kerb and its pavement override on the right only
        r7 = self.sp["roads:rd7:0"]
        self.assertEqual((r7["profile_ids"]["edge_left"], r7["profile_ids"]["edge_right"]), (None, "edge_uk_kerb"))
        self.assertEqual(r7["segments"][0]["side"], "right")
        # steps
        r8 = self.sp["roads:rd8:0"]
        self.assertTrue(r8["flags"]["steps"]); self.assertEqual(r8["points"][0]["tags"], ["steps"]); self.assertNotIn("tags", r8["points"][-1])
        self.assertEqual(r8["profile_ids"]["road"], "path_footway")

    def test_seam_way_gap_and_loop_continuations(self):
        a, b = self.sp["roads:rd1:0"], self.sp["roads:rd1:1"]
        self.assertEqual((a["continues_to"], b["continues_from"]), ("roads:rd1:1", "roads:rd1:0"))
        self.assertEqual((a["continuation_kind"]["to"], b["continuation_kind"]["from"]), ("seam", "seam"))
        self.assertEqual(a["overrun_points"]["after"], [b["points"][1]["x"], b["points"][1]["y"], b["points"][1]["_z_06"]])
        self.assertEqual(b["overrun_points"]["before"], [a["points"][-2]["x"], a["points"][-2]["y"], a["points"][-2]["_z_06"]])
        # way join: rd4 ends where rd1 starts, no junction there
        j = self.sp["roads:rd4:0"]
        self.assertEqual((j["continues_to"], j["continuation_kind"]["to"]), ("roads:rd1:0", "way"))
        self.assertEqual((a["continues_from"], a["continuation_kind"]["from"]), ("roads:rd4:0", "way"))
        self.assertEqual(j["overrun_points"]["after"], [a["points"][1]["x"], a["points"][1]["y"], a["points"][1]["_z_06"]])
        self.assertIsNone(j["continues_from"]); self.assertIsNone(j["overrun_points"]["before"])
        # gap: rd5 leaves the grid to the north and comes back
        g0, g1 = self.sp["roads:rd5:0"], self.sp["roads:rd5:1"]
        self.assertEqual((g0["continuation_kind"]["to"], g1["continuation_kind"]["from"]), ("gap", "gap"))
        self.assertEqual(g0["continues_to"], "roads:rd5:1"); self.assertEqual(g0["source"]["segment_count"], 2)
        self.assertLess(g0["points"][-1]["y"], 64.0); self.assertGreater(g0["points"][-1]["y"], 50.0)
        # loop
        lp = self.sp["roads:rd6:0"]
        self.assertTrue(lp["flags"]["closed_loop"]); self.assertIsNone(lp["continues_to"]); self.assertIsNone(lp["continues_from"])
        self.assertEqual(lp["points"][0]["x"], lp["points"][-1]["x"])
        m = self.sm
        self.assertEqual((m["ways_with_gaps"], m["closed_loops"], m["seam_joins"], m["way_joins"]), (1, 1, 2, 1))
        self.assertEqual(m["ways_multi_run"], 3)                                             # rd1, rd5, rl1

    def test_overlay_is_the_raw_way_clipped_to_grid_and_clip(self):
        r7 = self.sp["roads:rd7:0"]
        self.assertEqual(r7["overlay"]["kind"], "osm_way"); self.assertEqual(r7["overlay"]["osm_id"], "rd7")
        self.assertEqual([p[:2] for p in r7["overlay"]["pts"]], [[90.0, 55.0], [118.0, 55.0]])          # crossing inserted on the line
        self.assertEqual(r7["overlay"]["pts"][1][2], r7["overlay"]["pts"][0][2])                        # crossing takes the last kept vertex's z
        self.assertLessEqual(r7["points"][-1]["x"], 118.0)                                             # 06 cut the run at its last kept vertex
        self.assertEqual((self.sm["overlay_ways_clipped"], self.sm["overlay_vertices_dropped"]), (2, 2))  # rd7 by the clip, rd5 by the grid
        a = self.sp["roads:rd1:0"]
        self.assertEqual([p[:2] for p in a["overlay"]["pts"]], [[10.0, 30.0], [100.0, 30.0]])          # the whole way, not the run
        self.assertEqual(a["overlay"]["pts"][0][2], a["points"][0]["_z_06"])
        g0 = self.sp["roads:rd5:0"]
        self.assertEqual(g0["overlay"]["pts"][0][:2], [20.0, 50.0]); self.assertAlmostEqual(g0["overlay"]["pts"][-1][1], 64.0, 6)
        self.assertEqual(self.sp["roads:rd5:1"]["overlay"]["pts"][-1][:2], [60.0, 50.0])

    def test_junction_ends(self):
        doc = self.docs[(1, 0)]
        self.assertEqual(len(doc["junctions"]), 1)
        j = doc["junctions"][0]
        self.assertEqual((j["id"], j["x"], j["y"], j["radius_m"], j["kind"]), ("junction:1_0:0", 100.0, 30.0, 3.4, "disc"))
        ends = sorted((e["spline_id"], e["end"]) for e in j["ends"])
        self.assertEqual(ends, [("roads:rd1:1", "end"), ("roads:rd2:0", "start"), ("roads:rd3:0", "start")])
        self.assertEqual(self.sp["roads:rd1:1"]["junction_end"], "junction:1_0:0")
        self.assertEqual(self.sp["roads:rd2:0"]["junction_start"], "junction:1_0:0")
        self.assertIsNone(self.sp["roads:rd1:1"]["continues_to"])                                       # a junction end is not a way join
        self.assertEqual(self.docs[(0, 0)]["junctions"], []); self.assertEqual(self.sm["junctions"], 1)

    def test_rail(self):
        r = self.sp["rail:rl1:0"]
        self.assertEqual(r["profile_ids"], {"road": "rail_standard", "edge_left": None, "edge_right": None, "hedge_left": None, "hedge_right": None})
        self.assertEqual(r["source"]["layer"], "rail"); self.assertEqual(r["source"]["segment_count"], 2)
        self.assertEqual(r["source"]["tags"], {"gauge": "1.435", "electrified": "rail", "usage": "main", "gauge_src": "osm", "tracks": "2"})
        self.assertEqual(r["flags"]["tracks"], 2); self.assertFalse(r["flags"]["gauge_unmapped"]); self.assertFalse(r["flags"]["disused"])
        self.assertEqual(sorted(r["points"][0]), ["_z_06", "x", "y"]); self.assertEqual(r["segments"], [])
        self.assertEqual(r["continues_to"], "rail:rl1:1")
        self.assertTrue(self.sp["rail:rl2:0"]["flags"]["gauge_unmapped"]); self.assertEqual(self.sp["rail:rl2:0"]["profile_ids"]["road"], "rail_standard")
        self.assertTrue(self.sp["rail:rl3:0"]["flags"]["disused"]); self.assertEqual(self.sp["rail:rl3:0"]["source"]["tags"]["gauge_src"], "default")
        self.assertEqual(self.sm["gauge_unmapped"], 1); self.assertEqual(self.sm["splines_by_layer"]["rail"], 4)

    def test_barriers(self):
        w = self.sp["barriers:bw1:0"]
        self.assertEqual(w["profile_ids"], {"road": None, "edge_left": "edge_barrier_only", "edge_right": None, "hedge_left": None, "hedge_right": None})
        self.assertEqual(w["segments"], [{"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "left",
                                          "edge": {"barrier": {"type": "brick_wall", "height_m": 0.5, "thickness_m": 0.215, "material": "brick_red", "offset_m": -0.1075}}}])
        self.assertEqual(w["source"]["tags"], {"height": "0.5", "wall": "brick", "h_src": "osm"})
        self.assertEqual(sorted(w["points"][0]), ["_z_06", "x", "y"])
        f = self.sp["barriers:bf1:0"]["segments"][0]["edge"]["barrier"]
        self.assertEqual(f, {"type": "chain_link", "height_m": 1.5, "thickness_m": 0.05, "material": "chain_link", "offset_m": -0.025, "post_pitch_m": 3.0})
        h = self.sp["barriers:bh1:0"]
        self.assertEqual(h["profile_ids"]["hedge_left"], "hedge_privet"); self.assertIsNone(h["profile_ids"]["edge_left"])
        self.assertEqual(h["segments"], [{"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "left", "hedge": {"present": True, "width_m": 0.8, "offset_m": -0.4, "height_m": 1.2}}])
        k = self.sp["barriers:bk1:0"]
        self.assertEqual(k["profile_ids"]["edge_left"], "edge_uk_kerb")
        self.assertEqual(k["segments"], [{"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "left", "edge": {"pavement_width_m": 0.0}}])
        self.assertNotIn("barriers:bx1:0", self.sp); self.assertEqual(self.sm["skipped_barriers"], {"cattle_grid": 1})
        f2 = self.sp["barriers:bf2:0"]
        self.assertEqual(f2["segments"][0]["edge"]["barrier"]["type"], "wood_fence"); self.assertEqual(f2["segments"][0]["edge"]["barrier"]["height_m"], 1.8)
        self.assertEqual(f2["source"]["tags"]["h_src"], "adapter_default")
        self.assertEqual(self.sm["barrier_height_defaulted_by_adapter"], 1)
        self.assertEqual(self.sm["barriers_by_type"], {"brick_wall": 1, "chain_link": 1, "hedge": 1, "kerb": 1, "wood_fence": 1})
        self.assertEqual(self.sm["splines_by_layer"]["barriers"], 5)

    def test_thinning_counts_and_manifest(self):
        m = self.sm
        self.assertGreater(m["points_in"], m["points_out"]); self.assertLessEqual(m["thin_max_dev_m"], 0.10); self.assertEqual(m["thin_tolerance_m"], 0.10)
        self.assertEqual(m["points_in"], sum(len(r["pts"]) for p in os.listdir(os.path.join(self.src, "networks")) if p.endswith(".jsonl")
                                             for r in read_jsonl(os.path.join(self.src, "networks", p)) if r.get("cls") != "_junction"))
        self.assertEqual(m["points_out"], sum(len(s["points"]) for s in self.sp.values()))
        self.assertEqual(m["splines_by_layer"], {"roads": 10, "rail": 4, "barriers": 5})
        self.assertEqual(m["ways"], 8 + 3 + 5); self.assertEqual(m["runs_degenerate"], 0)
        self.assertEqual(m["profile_ids_used"], {"road": ["path_footway", "rail_standard", "road_residential", "road_service", "road_tertiary"],
                                                 "edge": ["edge_barrier_only", "edge_uk_kerb"], "hedge": ["hedge_privet"]})
        self.assertLessEqual(m["run_locate_max_m"], 1e-6); self.assertEqual(m["warnings"], [])
        self.assertEqual(m["tags_coverage"]["sidewalk"], 2)
        for k in ("site", "crs", "origin", "tile_m", "nx", "ny", "frame", "schema_version", "generator", "profiles_dir", "per_tile", "documents",
                  "splines_by_layer", "points_in", "points_out", "thin_tolerance_m", "thin_max_dev_m", "ways", "ways_multi_run", "ways_with_gaps",
                  "closed_loops", "junctions", "seam_joins", "way_joins", "skipped_barriers", "barriers_by_type", "barrier_height_defaulted_by_adapter",
                  "gauge_unmapped", "overlay_vertices_dropped", "overlay_ways_clipped", "tags_coverage", "profile_ids_used", "warnings"):
            self.assertIn(k, m)

    # ---- massing, furniture, root ----------------------------------------------------------------
    def test_massing_and_furniture_conversions(self):
        b = read_jsonl(os.path.join(self.out, "massing", "buildings_x0_y0.jsonl"))[0]
        self.assertEqual(b["rings"][0]["pts"], [[20.0, 40.0], [30.0, 40.0], [30.0, 48.0], [20.0, 48.0], [20.0, 40.0]])
        self.assertEqual((b["base_z"], b["skirt"], b["h"], b["src"], b["seed"]), (4.4, 3.9, 6.8, "lidar_p50", 1))
        mm = jload(os.path.join(self.out, "massing", "massing_manifest.json"))
        self.assertEqual((mm["frame"], mm["files"], mm["buildings"], mm["coordinates"]), (U.FRAME, 1, 1, "rings in local metres, base_z/skirt ODN metres"))
        f = read_jsonl(os.path.join(self.out, "furniture", "furniture_x0_y0.jsonl"))[0]
        self.assertEqual(f, {"id": "cn1", "prop": "LitterBin", "name": None, "x": 30.0, "y": 34.25, "z": 5.0, "bearing": 270.0, "heading_deg": -180.0,
                             "src": "kerb", "d": 4.25, "cls": "residential", "nudged": False})
        fm = jload(os.path.join(self.out, "furniture", "furniture_manifest.json"))
        self.assertEqual((fm["placed"], fm["records"], fm["frame"]), (1, 1, U.FRAME)); self.assertIn("yaw_ue = bearing - 90", fm["ue_yaw"])

    def test_root_manifest_round_trips_the_grid(self):
        m = self.um
        self.assertEqual((m["origin"], m["tile_m"], m["nx"], m["ny"], m["res"]), ({"E": E0, "N": N0}, T, NX, NY, RES))
        self.assertEqual(m["clip"], lib.clip_manifest(self.clip)); self.assertEqual(m["frame"], U.FRAME)
        self.assertEqual(m["adapter_settings"], ADP)
        self.assertEqual(m["products"]["landscape"]["heightmaps"], 2); self.assertEqual(m["products"]["streetscape"]["documents"], 2)
        self.assertEqual(m["products"]["massing"]["buildings"], 1); self.assertEqual(m["products"]["furniture"]["placed"], 1)
        self.assertEqual(m["sources"]["linear"], {"manifest": "networks/linear_manifest.json", "rail_segments": 4, "barrier_segments": 6})
        self.assertEqual(m["sources"]["terrain"]["tiles"], 2)

    # ---- refusals --------------------------------------------------------------------------------
    def _landscape(self, adp=None, clip="same"):
        out2 = os.path.join(self.root, "refusal"); lib.mkdirs(out2)
        return U.landscape(self.cfg, adp or ADP, self.src, out2, self.clip if clip == "same" else clip, [])

    def _with_manifest(self, mutate):
        tm = json.loads(json.dumps(self.terrain_manifest)); mutate(tm)
        jdump(tm, self.tm_path)
        try:
            with self.assertRaises(SystemExit) as cm:
                self._landscape()
        finally:
            jdump(self.terrain_manifest, self.tm_path)
        return str(cm.exception)

    def test_refuse_range(self):
        self.assertIn("does not fit", self._with_manifest(lambda tm: tm.update(range_m=[-300.0, 10.0])))

    def test_refuse_tile_shape(self):
        path = os.path.join(self.src, "terrain", "dtm_x9_y9.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 64, 64, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((E0 + 9 * T - 0.5, 1.0, 0.0, N0 + 10 * T + 0.5, 0.0, -1.0)); ds.SetProjection(WKT)
        gpath = os.path.join(self.src, "coast", "ground_x9_y9.tif")     # ... so the torn-coast check is not what fires
        gd = gdal.GetDriverByName("GTiff").Create(gpath, 32, 32, 4, gdal.GDT_Byte)
        gd.SetGeoTransform((E0 + 9 * T, T / 32.0, 0.0, N0 + 10 * T, 0.0, -T / 32.0)); gd.SetProjection(WKT)
        def mutate(tm):
            tm["tiles"].append({**tm["tiles"][0], "x": 9, "y": 9, "file": "dtm_x9_y9.tif", "clipped_cells": 0, "clip_state": "inside"})
        try:
            self.assertIn("manifest res is 65", self._with_manifest(mutate))
        finally:
            os.remove(path); os.remove(gpath)

    def test_refuse_stale_clip(self):
        msg = self._with_manifest(lambda tm: tm["clip"].update(line=[[E0 + 100, N0], [E0 + 100, N0 + 64]]))
        self.assertIn("stale", msg)
        self.assertIn("stale", self._with_manifest(lambda tm: tm.pop("clip")))
        with self.assertRaises(SystemExit) as cm:                       # config clipless, manifest clipped
            self._landscape(clip=None)
        self.assertIn("stale", str(cm.exception))

    def test_refuse_clipped_cells_disagreement(self):
        def mutate(tm):
            tm["tiles"][1]["clipped_cells"] = 600
        self.assertIn("disagree", self._with_manifest(mutate))

    def test_refuse_unknown_profile_id(self):
        bad = json.loads(json.dumps(ADP)); bad["streetscape"]["barrier"]["hedge_profile"] = "hedge_nope"
        with self.assertRaises(SystemExit) as cm:
            U.check_adapter_settings(bad, self.cfg["tuning"], U.load_profiles(PROFILES_DIR))
        self.assertIn("hedge_nope", str(cm.exception))

    def test_refuse_bands_summing_to_100(self):
        band = self.ground[0].GetRasterBand(1)
        orig = band.ReadAsArray()
        try:
            arr = orig.copy(); arr[0, 0] = 100
            band.WriteArray(arr)                                         # grass 100, sand 0 at (0, 0): sum 100
            with self.assertRaises(SystemExit) as cm:
                self._landscape()
            self.assertIn("bands sum to 100 at (0, 0)", str(cm.exception))
        finally:
            band.WriteArray(orig)

    def test_refuse_terrain_tile_with_a_neighbours_georeference(self):
        """Shape alone cannot catch a tile carrying another tile's data: the product would be
        self-consistent and silently misplaced."""
        path = os.path.join(self.src, "terrain", "dtm_x0_y0.tif")
        ds = gdal.Open(path); good = ds.GetGeoTransform()
        try:
            ds.SetGeoTransform((E0 + T - 0.5, 1.0, 0.0, N0 + T + 0.5, 0.0, -1.0))       # tile (1, 0)'s window
            with self.assertRaises(SystemExit) as cm:
                self._landscape()
            self.assertIn("georeferenced at", str(cm.exception))
            self.assertIn("dtm_x0_y0.tif", str(cm.exception))
            ds.SetGeoTransform(good); ds.SetProjection("FAKE_WKT[EPSG:3857]")           # right place, wrong CRS
            with self.assertRaises(SystemExit) as cm:
                self._landscape()
            self.assertIn("EPSG:27700", str(cm.exception))
        finally:
            ds.SetGeoTransform(good); ds.SetProjection(WKT)

    def test_refuse_ground_raster_mis_georeferenced(self):
        g = self.ground[0]; good = g.GetGeoTransform()
        try:
            g.SetGeoTransform((E0 + T, T / 32.0, 0.0, N0 + T, 0.0, -T / 32.0))          # tile (1, 0)'s window
            with self.assertRaises(SystemExit) as cm:
                self._landscape()
            self.assertIn("ground_x0_y0.tif", str(cm.exception))
        finally:
            g.SetGeoTransform(good)

    def test_refuse_torn_coast_product(self):
        """A tile the coast manifest does NOT list in tiles_without_dtm but whose ground raster is
        absent means coast/ is incomplete or is being rewritten -- refuse, never ship a landscape
        missing its ground cover with exit 0 (PIPELINE_CHANGES.md 13.10 refusals)."""
        path = os.path.join(self.src, "coast", "ground_x0_y0.tif")
        os.remove(path)
        try:
            with self.assertRaises(SystemExit) as cm:
                self._landscape()
            msg = str(cm.exception)
            self.assertIn("tiles_without_dtm", msg); self.assertIn("[[0, 0]]", msg); self.assertIn("step 09", msg)
            self.assertIn("Nothing was written", msg)                  # refused before _clear touched the product
        finally:
            open(path, "ab").close()                       # the fake keeps the raster; only the file was gone

    def test_tiles_fabricated_are_counted_and_warned(self):
        """Every cell NoData in the source: step 05 exports a flat plate (terrain_manifest
        tiles_fabricated). Fabricated ground, and nothing in the adapter's manifest counted it."""
        out2 = os.path.join(self.root, "invented"); lib.mkdirs(out2)
        tm = json.loads(json.dumps(self.terrain_manifest))
        tm["tiles"][0]["fill"] = "all-nodata -> -0.6"
        tm["tiles_fabricated"] = [[0, 0]]; tm["empty_fill_m"] = -0.6
        jdump(tm, self.tm_path)
        warns = []
        try:
            st = U.landscape(self.cfg, ADP, self.src, out2, self.clip, warns)
        finally:
            jdump(self.terrain_manifest, self.tm_path)
        man = jload(os.path.join(out2, "landscape", "landscape_manifest.json"))
        self.assertEqual(man["tiles_fabricated"], [[0, 0]]); self.assertEqual(st["tiles_fabricated"], 1)
        self.assertEqual(man["empty_fill_m"], -0.6)
        self.assertTrue(any("NO surveyed cell at all" in w for w in warns), warns)
        self.assertEqual(self.lm["tiles_fabricated"], [])              # the site itself has none
        tm["tiles_fabricated"] = [[1, 0]]                              # manifest list vs per-tile fill disagree
        jdump(tm, self.tm_path)
        try:
            with self.assertRaises(SystemExit) as cm:
                U.landscape(self.cfg, ADP, self.src, out2, self.clip, [])
            self.assertIn("tiles_fabricated", str(cm.exception))
        finally:
            jdump(self.terrain_manifest, self.tm_path)

    def test_strict_refuses_a_missing_source_directory(self):
        cd = os.path.join(self.src, "coast")
        os.rename(cd, cd + ".away")
        try:
            with self.assertRaises(SystemExit) as cm:
                U.main(["--strict"])
            self.assertIn("--strict", str(cm.exception)); self.assertIn("step 09", str(cm.exception))
        finally:
            os.rename(cd + ".away", cd)
        self.assertTrue(os.path.exists(os.path.join(self.L, "weight_grass_x0_y0.r8")))   # nothing was cleared

    def test_only_carries_the_other_products_over(self):
        """--only rebuilds a subset; the products it did not touch are still on disk and still
        current, so the site-level index must not null them."""
        try:
            self.assertEqual(U.main(["--only", "streetscape"]), 0)
            m = jload(os.path.join(self.out, "unreal_manifest.json"))
            self.assertEqual([k for k, v in m["products"].items() if v is None], [])
            self.assertEqual(m["products"]["landscape"]["heightmaps"], 2)
            self.assertEqual(m["products"]["massing"]["buildings"], 1)
            self.assertEqual(m["partial_run"]["rebuilt"], ["streetscape"])
            self.assertEqual(m["partial_run"]["carried_over_from_previous_manifest"], ["furniture", "landscape", "massing"])
            with self.assertRaises(SystemExit) as cm:
                U.main(["--only", "landscpae"])
            self.assertIn("no such product", str(cm.exception))
        finally:
            U.main([])                                     # leave the tree as setUpClass built it
        m = jload(os.path.join(self.out, "unreal_manifest.json"))
        self.assertNotIn("partial_run", m); self.assertEqual(m["products"]["landscape"]["heightmaps"], 2)

    def test_seam_qa_measures_the_shared_edge(self):
        """The two synthetic tiles share a column of 65 samples; both are fully covered, so every
        sample must agree, and a difference on a fill-free edge must be called out."""
        q = self.lm["seam_qa"]
        self.assertEqual((q["edges_compared"], q["samples_disagreeing"], q["samples_disagreeing_on_fill_free_edges"]),
                         (1, 0, 0))
        self.assertGreater(q["samples_compared"], 0)      # the clipped part of tile (1, 0) is not counted
        self.assertEqual(q["max_disagreement_m"], 0.0)
        h0 = np.fromfile(os.path.join(self.L, "hm_x0_y0.r16"), dtype="<u2").reshape(RES, RES)
        h1 = np.fromfile(os.path.join(self.L, "hm_x1_y0.r16"), dtype="<u2").reshape(RES, RES)
        k = np.fromfile(os.path.join(self.L, "clip_x1_y0.r8"), dtype=np.uint8).reshape(RES, RES)[:, 0] == 255
        self.assertEqual(int(q["samples_compared"]), int(k.sum()))
        self.assertTrue((h0[:, -1][k] == h1[:, 0][k]).all())
        # a tile that carries a neighbour's data on its shared edge is exactly what this catches
        ds = gdal.Open(os.path.join(self.src, "terrain", "dtm_x0_y0.tif"))
        a = ds.GetRasterBand(1).ReadAsArray(); orig = a.copy()
        try:
            a[:, -1] = a[:, -1] + 3.0
            ds.GetRasterBand(1).WriteArray(a)
            warns = []
            out2 = os.path.join(self.root, "seam"); lib.mkdirs(out2)
            U.landscape(self.cfg, ADP, self.src, out2, self.clip, warns)
            man = jload(os.path.join(out2, "landscape", "landscape_manifest.json"))
            self.assertEqual(man["seam_qa"]["samples_disagreeing_on_fill_free_edges"], int(k.sum()))
            self.assertAlmostEqual(man["seam_qa"]["max_disagreement_m"], 3.0, places=3)
            self.assertTrue(any("written by more than one run" in w for w in warns), warns)
        finally:
            ds.GetRasterBand(1).WriteArray(orig)

    def test_manifest_records_how_the_thinning_was_measured(self):
        m = self.sm
        self.assertEqual(m["thin_interpolant_samples_per_segment"], U.THIN_VERIFY_SAMPLES)
        self.assertEqual(m["point_quantum_m"], 0.01)
        self.assertLessEqual(m["point_quantum_max_shift_m"], 0.005 + 1e-9)      # half a quantum, by construction
        for d in self.docs.values():                                            # ... and it is what shipped
            for sp in d["splines"]:
                for pt in sp["points"]:
                    self.assertEqual(pt["x"], round(pt["x"], 2)); self.assertEqual(pt["y"], round(pt["y"], 2))

    def test_refuse_partial_step11(self):
        lm = os.path.join(self.src, "networks", "linear_manifest.json")
        os.rename(lm, lm + ".bak")
        try:
            with self.assertRaises(SystemExit) as cm:
                U.streetscape(self.cfg, ADP, self.src, os.path.join(self.root, "refusal"), self.clip, U.load_profiles(PROFILES_DIR), [])
            self.assertIn("linear_manifest.json", str(cm.exception))
        finally:
            os.rename(lm + ".bak", lm)


if __name__ == "__main__":
    unittest.main(verbosity=1)
