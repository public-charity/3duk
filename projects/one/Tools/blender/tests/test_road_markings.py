"""Renderer A on straight_100: ribbon counts, dashes, double yellow, lift, edge-anchored ramp, camber
(STAGES.md stage 4, SCHEMA.md 9.3)."""
import os
import re
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json, schema as S  # noqa: E402
from streetscape.build import build_spline  # noqa: E402
from streetscape.mesh import surface_height_at  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))["straight_100"]


def dash_runs(buf, group):
    tri = buf.f[buf.group_mask_tris(exact=group)]
    spans = sorted(set((round(float(buf.vs[t].min()), 9), round(float(buf.vs[t].max()), 9)) for t in tri))
    runs = []
    for a, b in spans:
        if runs and abs(a - runs[-1][1]) < 1e-9:
            runs[-1] = (runs[-1][0], b)
        else:
            runs.append((a, b))
    return runs


class TestRoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = syn.load_fixture("straight_100")
        cls.site = io_json.site_from_dict(doc)
        cls.res = build_spline(cls.site, doc["splines"][0]["id"], syn.terrain_for(doc))
        cls.sp = cls.res.spline
        cls.road = cls.res.road

    def test_ribbon_counts(self):
        road = self.road
        ribbon_v = road.vertices_of_groups(exclude_prefix="marking:")
        ribbon_t = int(np.sum(~road.group_mask_tris("marking:")))
        self.assertEqual(len(ribbon_v), EXP["ribbon_verts"])
        self.assertEqual(ribbon_t, EXP["ribbon_tris"])
        rows = len(np.unique(np.round(road.vd[ribbon_v][np.abs(road.vs[ribbon_v]) < 1e-9], 9)))
        self.assertEqual(rows, EXP["ribbon_rows"])
        self.assertEqual(set(g for g in road.group_names if not g.startswith("marking:")), {"road", "skirt_left", "skirt_right"})
        self.assertEqual(self.res.stats["validate"]["road"], [])
        self.assertTrue(np.array_equal(np.unique(road.vs[ribbon_v]), self.sp.s))

    def test_markings(self):
        road = self.road
        E = EXP["centre_dashes"]
        vi = road.vertices_of_groups(exact="marking:centre_1004")
        self.assertEqual(sorted(np.unique(np.round(road.vd[vi], 9))), E["vd"])
        runs = dash_runs(road, "marking:centre_1004")
        self.assertEqual(len(runs), E["count"])
        self.assertAlmostEqual(runs[0][0], E["first"][0], delta=E["tol"])
        self.assertAlmostEqual(runs[0][1], E["first"][1], delta=E["tol"])
        self.assertAlmostEqual(runs[-1][0], E["last"][0], delta=E["tol"])
        self.assertAlmostEqual(runs[-1][1], E["last"][1], delta=E["tol"])
        for k, (a, b) in enumerate(runs):
            self.assertAlmostEqual(a, 6.0 * k, delta=E["tol"])
            self.assertAlmostEqual(b, 6.0 * k + 4.0, delta=E["tol"])
        self.assertEqual(self.res.stats["marking_strips"], EXP["marking_strips"])
        # double yellow on the left follows the edge: line centres at o0 - 0.35 and o0 - 0.15
        D = EXP["double_yellow"]
        vi = road.vertices_of_groups(exact="marking:dyl_left_1018_1")
        o0 = self.sp.edge_offset(S.LEFT)
        for i, s in enumerate(self.sp.s):
            sel = np.abs(road.vs[vi] - s) < 1e-9
            vd = np.sort(road.vd[vi][sel])
            self.assertEqual(len(vd), 4, "double yellow at s=%g" % s)
            centres = [(vd[0] + vd[1]) / 2, (vd[2] + vd[3]) / 2]
            self.assertAlmostEqual(centres[0], o0[i] - D["line_centres_inward"][0], delta=1e-9)
            self.assertAlmostEqual(centres[1], o0[i] - D["line_centres_inward"][1], delta=1e-9)
            self.assertAlmostEqual(vd[1] - vd[0], D["line_width"], delta=1e-9)
            self.assertAlmostEqual((centres[0] + centres[1]) / 2, o0[i] - D["pair_centre_inward"], delta=1e-9)
        i40 = int(np.argmin(np.abs(self.sp.s - 40.0)))
        vd40 = np.sort(road.vd[vi][np.abs(road.vs[vi] - 40.0) < 1e-9])
        for k, shift in D["shift_per_station"].items():
            vds = np.sort(road.vd[vi][np.abs(road.vs[vi] - float(k)) < 1e-9])
            self.assertTrue(np.allclose(vds - vd40, shift, atol=1e-9), "shift at s=%s" % k)
        # s = 45 lies between the stations 44 and 46: the strip edges are straight, so the shift is exactly 0.5
        vd44 = np.sort(road.vd[vi][np.abs(road.vs[vi] - 44.0) < 1e-9])
        vd46 = np.sort(road.vd[vi][np.abs(road.vs[vi] - 46.0) < 1e-9])
        self.assertTrue(np.allclose((vd44 + vd46) / 2 - vd40, D["shift_40_to_45"], atol=1e-9))

    def test_lift_above_the_road_mesh(self):
        road = self.road
        vi = road.vertices_of_groups(prefix="marking:")
        self.assertGreater(len(vi), 100)
        for k in vi:
            h_road = surface_height_at(road, float(road.vs[k]), float(road.vd[k]))
            self.assertFalse(np.isnan(h_road))
            self.assertAlmostEqual(float(road.vh[k] - h_road), EXP["lift_m"], delta=EXP["lift_tol"])
        # and in WORLD space: at a shared station the road mesh between two rows is the straight segment between
        # the row vertices, so the marking vertex must sit exactly lift * b above the interpolated road point
        ribbon = road.vertices_of_groups(exclude_prefix="marking:")
        sp = self.sp
        checked = 0
        for k in vi[::3]:
            same = ribbon[np.abs(road.vs[ribbon] - road.vs[k]) < 1e-9]
            if len(same) == 0:
                continue
            i = int(np.argmin(np.abs(sp.s - road.vs[k])))
            order = np.argsort(road.vd[same])
            dd = road.vd[same][order]
            d = float(road.vd[k])
            j = int(np.clip(np.searchsorted(dd, d) - 1, 0, len(dd) - 2))
            t = (d - dd[j]) / (dd[j + 1] - dd[j])
            p_road = (1 - t) * road.v[same[order[j]]] + t * road.v[same[order[j + 1]]]
            diff = road.v[k] - p_road - EXP["lift_m"] * sp.frames.b[i]
            self.assertLess(float(np.linalg.norm(diff)), 1e-9)
            checked += 1
        self.assertGreater(checked, 50)

    def test_camber(self):
        C = EXP["camber"]
        sp = self.sp
        i = int(np.argmin(np.abs(sp.s - 20.0)))
        self.assertAlmostEqual(float(sp.surface_h(np.zeros(sp.n))[i]), C["h0"], places=12)
        self.assertAlmostEqual(float(sp.surface_h(np.full(sp.n, 3.0))[i]), C["h_pm3_parabolic"], places=12)
        self.assertAlmostEqual(float(sp.surface_h(np.full(sp.n, -3.0))[i]), C["h_pm3_parabolic"], places=12)
        doc = syn.load_fixture("straight_100")
        doc["profiles"]["road"]["road_test_marked"]["camber"] = {"kind": "planar", "crossfall_pct": 2.5}
        site = io_json.site_from_dict(doc)
        from streetscape.spline import Spline
        sp2 = Spline(site.splines[0], site, syn.terrain_for(doc))
        self.assertAlmostEqual(float(sp2.surface_h(np.full(sp2.n, 3.0))[i]), C["h_pm3_planar"], places=12)
        doc["profiles"]["road"]["road_test_marked"]["camber"] = {"kind": "none"}
        site = io_json.site_from_dict(doc)
        sp3 = Spline(site.splines[0], site, syn.terrain_for(doc))
        self.assertEqual(float(np.abs(sp3.surface_h(np.full(sp3.n, 3.0))).max()), 0.0)

    def test_single_yellow_is_the_same_code_path(self):
        doc = syn.load_fixture("straight_100")
        doc["profiles"]["road"]["road_test_marked"]["markings"] = [
            {"id": "syl_left_1017", "anchor": "edge_left", "offset_m": 0.25, "width_m": 0.1, "pattern": "solid", "material": "yellow_paint"}]
        site = io_json.site_from_dict(doc)
        res = build_spline(site, doc["splines"][0]["id"], syn.terrain_for(doc))
        road = res.road
        vi = road.vertices_of_groups(exact="marking:syl_left_1017")
        o0 = res.spline.edge_offset(S.LEFT)
        for i, s in enumerate(res.spline.s):
            vd = np.sort(road.vd[vi][np.abs(road.vs[vi] - s) < 1e-9])
            self.assertEqual(len(vd), 2)
            self.assertAlmostEqual(float((vd[0] + vd[1]) / 2), o0[i] - 0.25, delta=1e-9)
        self.assertEqual(res.stats["marking_strips"], 1)
        # dash phase is global: a dash pattern with phase 1 starts at 1, 7, 13 ...
        doc["profiles"]["road"]["road_test_marked"]["markings"] = [
            {"id": "d", "anchor": "centre", "offset_m": 0.0, "width_m": 0.1, "pattern": "dashed", "dash_m": 4.0, "gap_m": 2.0, "phase_m": 1.0, "material": "white_paint"}]
        site = io_json.site_from_dict(doc)
        res = build_spline(site, doc["splines"][0]["id"], syn.terrain_for(doc))
        runs = dash_runs(res.road, "marking:d")
        self.assertAlmostEqual(runs[0][0], 1.0, delta=1e-9)
        self.assertAlmostEqual(runs[1][0], 7.0, delta=1e-9)

    def test_no_marking_specific_code(self):
        src = open(os.path.join(syn.TOOLS_BLENDER, "streetscape", "road.py"), encoding="utf-8").read()
        self.assertEqual(len(re.findall(r"double_yellow|DoubleYellow|centre_dash|CentreDash|dyl_left|1018", src)), 0)

    def test_no_road_when_profile_null(self):
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["profile_ids"]["road"] = None
        site = io_json.site_from_dict(doc)
        res = build_spline(site, doc["splines"][0]["id"], syn.terrain_for(doc))
        self.assertIsNone(res.road)
        self.assertTrue(np.all(res.spline.width == 0.0))
        self.assertTrue(np.all(res.spline.edge_offset(S.LEFT) == 0.0))


if __name__ == "__main__":
    unittest.main()
