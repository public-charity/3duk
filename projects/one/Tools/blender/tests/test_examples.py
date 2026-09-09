"""End-to-end: synthetic_straight.json builds; package structure rules (three builders, import graph,
no width/2 outside spline.py); Chaikin-vs-OSM overlay distance; determinism of the written products;
the real test stretch when the Margate tiles (or the Thanet landscape) are on disk."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
import streetscape  # noqa: E402
from streetscape import io_json, schema as S, spline as SP  # noqa: E402
from streetscape.build import build_spline, build_all, write_result, load_terrain, safe_dir_name  # noqa: E402
from streetscape.terrain import Heightfield  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))
REPO = os.path.dirname(os.path.dirname(syn.PROJECT_ONE))
PKG = os.path.join(syn.TOOLS_BLENDER, "streetscape")


class TestPackageRules(unittest.TestCase):
    def test_exports_and_version(self):
        self.assertTrue(re.match(r"^\d+\.\d+\.\d+$", streetscape.__version__))
        from streetscape import road, edge, hedge
        self.assertTrue(callable(road.build_road) and callable(edge.build_edge) and callable(hedge.build_hedge))
        builders = [n for n in dir(streetscape) if n.startswith("build_")]
        self.assertEqual(sorted(builders), ["build_all", "build_spline"])

    def test_import_graph(self):
        for mod in ("road", "edge", "hedge"):
            src = open(os.path.join(PKG, mod + ".py"), encoding="utf-8").read()
            for other in ("road", "edge", "hedge"):
                if other == mod:
                    continue
                self.assertIsNone(re.search(r"^\s*from\s+\.\s*import\s+.*\b%s\b|^\s*from\s+\.%s\s+import|^\s*import\s+streetscape\.%s" % (other, other, other), src, re.M),
                                  "%s imports %s" % (mod, other))
        rail = open(os.path.join(PKG, "rail.py"), encoding="utf-8").read()
        self.assertIsNone(re.search(r"from \.(road|edge|hedge) import", rail))

    def test_no_width_over_two_outside_spline(self):
        pat = re.compile(r"width_m *\/ *2|w *\/ *2|\/ *2\.0|width *\/ *2")
        for mod in ("road.py", "edge.py", "hedge.py", "rail.py"):
            src = open(os.path.join(PKG, mod), encoding="utf-8").read()
            hits = [ln for ln in src.splitlines() if pat.search(ln)]
            self.assertEqual(hits, [], "%s computes width/2: %s" % (mod, hits))
        # the same grep the acceptance check runs
        try:
            out = subprocess.run(["grep", "-rn", r"width_m *\/ *2\|w *\/ *2\|/ *2\.0", os.path.join(PKG, "road.py"), os.path.join(PKG, "edge.py"), os.path.join(PKG, "hedge.py")],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 1, out.stdout)
        except FileNotFoundError:
            pass


class TestSyntheticStraightBuild(unittest.TestCase):
    def test_build_and_write(self):
        path = os.path.join(syn.EXAMPLES_DIR, "synthetic_straight.json")
        site = io_json.load_site(path)
        terrain = syn.terrain_for(syn.load_json(path))
        results = build_all(site, terrain)
        self.assertEqual(list(results), ["authored:straight_100"])
        res = results["authored:straight_100"]
        st = res.stats
        for k in ("length_m", "n_samples", "step_min", "step_max", "step_mean", "z_raw_nan_count", "bank_min", "bank_max",
                  "buffers", "overlap_min", "overlap_max", "marking_strips", "instances"):
            self.assertIn(k, st)
        self.assertEqual(set(st["buffers"]), {"road", "edge_left", "edge_right"})
        self.assertEqual(st["n_samples"], EXP["straight_100"]["N"])
        self.assertEqual(st["overlap_min"], 0.04)
        self.assertEqual(st["overlap_max"], 0.04)
        self.assertEqual(st["marking_strips"], EXP["straight_100"]["marking_strips"])
        self.assertTrue(all(v is True for v in st["stations_identical"].values()))
        d = tempfile.mkdtemp()
        try:
            out = write_result(res, d)
            self.assertEqual(os.path.basename(out), "authored~straight_100")
            for f in ("road.npz", "edge_left.npz", "edge_right.npz", "instances.json", "overlay.json", "stats.json", "spline.npz"):
                self.assertTrue(os.path.isfile(os.path.join(out, f)), f)
            first = {f: open(os.path.join(out, f), "rb").read() for f in os.listdir(out)}
            res2 = build_spline(site, "authored:straight_100", terrain)
            out2 = write_result(res2, d)
            for f, data in first.items():
                self.assertEqual(open(os.path.join(out2, f), "rb").read(), data, "%s differs between two runs" % f)
            with open(os.path.join(out, "overlay.json"), encoding="utf-8") as fh:
                ov = json.load(fh)
            self.assertEqual(ov["lift_m"], 0.3)
            self.assertTrue(all(abs(p[2] - 10.3) < 1e-9 for p in ov["pts"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_cli(self):
        d = tempfile.mkdtemp()
        try:
            env = dict(os.environ)
            env["PYTHONPATH"] = syn.TOOLS_BLENDER
            hf = syn.flat_terrain(10.0)
            hf.save_npz(os.path.join(d, "flat.npz"))
            out = subprocess.run([sys.executable, "-m", "streetscape.build", "--site", os.path.join(syn.EXAMPLES_DIR, "synthetic_straight.json"),
                                  "--terrain", os.path.join(d, "flat.npz"), "--out", os.path.join(d, "o")], capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "o", "authored~straight_100", "stats.json")))
            self.assertIn("overlap=0.04/0.04", out.stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)


def densify(pts, step):
    out = [pts[0]]
    for i in range(1, len(pts)):
        ax, ay = out[-1]
        bx, by = pts[i]
        d = np.hypot(bx - ax, by - ay)
        if d > step:
            n = int(d // step)
            for k in range(1, n + 1):
                t = k * step / d
                if t < 1.0:
                    out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        out.append(pts[i])
    return out


def chaikin(pts, iters):
    for _ in range(iters):
        if len(pts) < 3:
            break
        new = [pts[0]]
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            new.append((ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25))
            new.append((ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75))
        new.append(pts[-1])
        pts = new
    return pts


def dist_to_polyline(P, poly):
    """Distance of every point of P (K, 2) to the polyline poly (M, 2) (exact point-to-segment)."""
    P = np.asarray(P, dtype=float)
    poly = np.asarray(poly, dtype=float)
    best = np.full(len(P), np.inf)
    for a, b in zip(poly[:-1], poly[1:]):
        ab = b - a
        L2 = float(ab @ ab)
        t = np.clip(((P - a) @ ab) / L2, 0.0, 1.0) if L2 > 0 else np.zeros(len(P))
        q = a + t[:, None] * ab
        best = np.minimum(best, np.hypot(P[:, 0] - q[:, 0], P[:, 1] - q[:, 1]))
    return best


def hausdorff(A, B):
    """Symmetric Hausdorff distance between two polylines (dense vertices vs exact segments)."""
    return max(float(dist_to_polyline(A, B).max()), float(dist_to_polyline(B, A).max()))


def polyline_dense(pts, step=0.05):
    return np.asarray(pts, dtype=float)


class TestOverlayRibbon(unittest.TestCase):
    """BRIEF 1.1 first deliverable: "a debug overlay of the source OSM polyline".  It has to be VISIBLE:
    an edge-only bpy mesh has no primitives, so EEVEE draws nothing and the glTF exporter omits it."""

    def test_ribbon_has_primitives_and_the_right_cross_section(self):
        from streetscape.bpy_bridge import overlay_ribbon, OVERLAY_RIBBON_W_M
        pts = np.array([[0.0, 0.0, 10.0], [10.0, 0.0, 10.0], [10.0, 10.0, 11.0], [20.0, 10.0, 11.0]])
        verts, faces = overlay_ribbon(pts)
        self.assertEqual(len(verts), 4 * len(pts))
        self.assertEqual(len(faces), 2 * (len(pts) - 1), "an overlay with no faces renders as nothing")
        self.assertTrue(all(len(f) == 4 for f in faces))
        self.assertEqual(len(set(i for f in faces for i in f)), 4 * len(pts))   # every vertex used
        V = np.array(verts)
        for i, p in enumerate(pts):
            a, b, c, d = V[4 * i], V[4 * i + 1], V[4 * i + 2], V[4 * i + 3]
            self.assertAlmostEqual(float(np.linalg.norm(a - b)), OVERLAY_RIBBON_W_M, places=9)
            self.assertAlmostEqual(float(np.linalg.norm(c - d)), OVERLAY_RIBBON_W_M, places=9)
            self.assertTrue(np.allclose(0.5 * (a + b), p, atol=1e-12))          # centred on the polyline
            self.assertTrue(np.allclose(0.5 * (c + d), p, atol=1e-12))
            self.assertAlmostEqual(float(a[2] - b[2]), 0.0, places=12)          # one ribbon horizontal
            self.assertAlmostEqual(float(c[2] - d[2]), OVERLAY_RIBBON_W_M, places=9)   # the other vertical
        # degenerate inputs do not raise
        self.assertEqual(overlay_ribbon(np.zeros((1, 3))), ([], []))

    def test_the_committed_stretch_overlay_builds_a_ribbon(self):
        doc = syn.load_json(os.path.join(syn.EXAMPLES_DIR, "test_stretch.json"))
        pts = np.array([[p[0], p[1], 0.0] for p in doc["splines"][0]["overlay"]["pts"]])
        from streetscape.bpy_bridge import overlay_ribbon
        verts, faces = overlay_ribbon(pts)
        self.assertEqual(len(faces), 2 * (len(pts) - 1))
        self.assertGreater(len(faces), 0)


class TestOverlayDistance(unittest.TestCase):
    def spline_of(self, raw):
        pts = [tuple(np.round(p, 2)) for p in chaikin(densify(raw, 8.0), 2)]
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["points"] = [{"x": float(x), "y": float(y)} for x, y in pts]
        doc["splines"][0]["drop_kerbs"] = []
        doc["splines"][0]["overlay"] = {"kind": "osm_way", "pts": [[float(x), float(y)] for x, y in raw], "osm_id": "1"}
        site = io_json.site_from_dict(doc)
        sp = SP.Spline(site.splines[0], site, syn.flat_terrain(10.0, (512.0, 512.0)))
        return sp

    def test_right_angle_and_kink(self):
        raw = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0)]
        sp = self.spline_of(raw)
        d = hausdorff(sp.xy_dense, polyline_dense(raw))
        self.assertLessEqual(d, 1.5)
        self.assertGreater(d, 0.5)
        raw = [(0.0, 0.0), (40.0, 0.0), (40.0 + 40.0 * np.cos(np.radians(30)), 40.0 * np.sin(np.radians(30)))]
        sp = self.spline_of(raw)
        self.assertLessEqual(hausdorff(sp.xy_dense, polyline_dense(raw)), 0.6)
        raw = [(0.0, 0.0), (40.0, 0.0), (80.0, 0.0)]
        sp = self.spline_of(raw)
        self.assertLess(hausdorff(sp.xy_dense, polyline_dense(raw)), 0.011)


def stretch_terrain():
    """Thanet landscape if present, else the Margate step-05 tiles (GDAL or the npz cache)."""
    hf = syn.thanet_landscape()
    if hf is not None:
        return hf, "thanet landscape"
    cache = os.path.join(syn.TOOLS_BLENDER, "out", "terrain_margate_step05_thanetframe.npz")
    if os.path.isfile(cache):
        return Heightfield.from_npz(cache), "margate step05 npz cache"
    terr = os.path.join(REPO, "data", "margate", "out", "terrain")
    if os.path.isfile(os.path.join(terr, "terrain_manifest.json")):
        try:
            from osgeo import gdal  # noqa: F401
            return Heightfield.from_step05_dir(terr, tiles=[(i, j) for i in (4, 5, 6) for j in (4, 5, 6)]), "margate step05 gdal"
        except Exception:
            return None, None
    return None, None


class TestStretch(unittest.TestCase):
    def test_trinity_square(self):
        terrain, src = stretch_terrain()
        if terrain is None:
            self.skipTest("no terrain for the test stretch on disk")
        E = EXP["test_stretch"]
        site = io_json.load_site(os.path.join(syn.EXAMPLES_DIR, "test_stretch.json"))
        res = build_spline(site, "authored:trinity_square", terrain)
        st = res.stats
        self.assertAlmostEqual(st["length_m"], E["L"], delta=E["L_tol"])
        self.assertEqual(st["n_samples"], E["n_samples"])
        self.assertEqual(st["z_raw_nan_count"], E["z_raw_nan_count"])
        self.assertGreaterEqual(st["step_min"], E["step_min_floor"])
        self.assertLessEqual(st["step_max"], E["step_max"] + 1e-6)
        self.assertLessEqual(max(abs(st["bank_min"]), abs(st["bank_max"])), E["bank_abs_max"])
        sp = res.spline
        for k, v in E["z_ref"].items():
            self.assertAlmostEqual(float(np.interp(float(k), sp.s, sp.z_ref)), v, delta=E["z_ref_tol"], msg="z_ref(%s) [%s]" % (k, src))
        self.assertEqual(st["overlap_min"], E["overlap"])
        self.assertEqual(st["overlap_max"], E["overlap"])
        self.assertEqual(st["w_max"], E["w_max"])
        self.assertEqual(st["instances"], E["instances"])
        self.assertEqual(st["marking_strips"], E["marking_strips"])
        self.assertEqual({k: [v["verts"], v["tris"]] for k, v in st["buffers"].items()}, E["buffers"])
        h = res.hedge[S.RIGHT]
        self.assertEqual([float(h.vs.min()), float(h.vs.max())], E["hedge_s_range"])
        spec = sp.side_spec[S.RIGHT]
        i = int(np.argmin(np.abs(sp.s - 60.0)))
        o_inner = float((-h.vd[np.abs(h.vs - sp.s[i]) < 1e-9]).min())
        self.assertAlmostEqual(o_inner, E["hedge_inner_face_on_6m_section"], places=9)
        # the 4 mm marking lift measured in WORLD z on the real banked, cambered, curved stretch
        from test_road_markings import vertical_clearance_over_road
        W = EXP["marking_lift_world"]
        M = W["measured"]["test_stretch_thanet_landscape"]
        mv, gap = vertical_clearance_over_road(res.road)
        self.assertEqual(len(mv), M["verts"])
        self.assertFalse(np.isnan(gap).any(), "a marking vertex sits over no road triangle")
        self.assertGreater(float(gap.min()), W["min_clearance_m"])
        if src == "thanet landscape":
            self.assertAlmostEqual(float(gap.min()), M["min"], delta=W["tol"])
            self.assertAlmostEqual(float(gap.max()), M["max"], delta=W["tol"])
        self.assertEqual(st["overlay_points"], E["overlay_points"])
        self.assertTrue(all(v == [] for v in st["validate"].values()))
        self.assertEqual(safe_dir_name("authored:trinity_square"), "authored~trinity_square")


if __name__ == "__main__":
    unittest.main()
