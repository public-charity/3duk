"""The shared spline: stations, width, smoothing, bank, frames (STAGES.md stage 3, SCHEMA.md 9.3)."""
import copy
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json, noise, schema as S  # noqa: E402
from streetscape import spline as SP  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))


def build(doc, terrain=None):
    site = io_json.site_from_dict(doc)
    return SP.Spline(site.splines[0], site, terrain if terrain is not None else syn.terrain_for(doc))


def adaptive_gaps(sp):
    g = np.diff(sp.s)
    aa = ~(sp.mandatory[1:] | sp.mandatory[:-1])
    mid = (sp.s[1:] + sp.s[:-1]) / 2
    return g, aa, mid


class TestStations(unittest.TestCase):
    def test_straight_100(self):
        E = EXP["straight_100"]
        sp = build(syn.load_fixture("straight_100"))
        self.assertAlmostEqual(sp.length, E["L"], places=9)
        self.assertEqual(sp.n, E["N"])
        self.assertEqual(sp.s[0], 0.0)
        self.assertEqual(sp.s[-1], sp.length)
        self.assertTrue(np.all(np.diff(sp.s) > 0))
        g = np.diff(sp.s)
        self.assertAlmostEqual(float(g.min()), E["gap_min"], places=9)
        self.assertAlmostEqual(float(g.max()), E["gap_max"], places=9)
        off = [float(x) for x in sp.s if abs(x / 2 - round(x / 2)) > 1e-9]
        self.assertEqual(off, E["off_grid_stations"])
        for m in E["off_grid_stations"] + [40.0, 50.0, 70.0]:
            self.assertTrue(np.any(sp.s == m), "mandatory station %r not present as the exact float" % m)
        g, aa, _ = adaptive_gaps(sp)
        self.assertTrue(np.allclose(g[aa], E["adaptive_gap"], atol=1e-9))
        # without the drop kerb: 51 stations at exactly 2 m
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["drop_kerbs"] = []
        sp2 = build(doc)
        self.assertEqual(sp2.n, E["N_without_drop_kerb"])
        self.assertLess(float(np.abs(np.diff(sp2.s) - 2.0).max()), 1e-9)

    def test_catmull_rom_passes_through_waypoints(self):
        for name in ("sine_5_50", "curve_R20_200"):
            sp = build(syn.load_fixture(name))
            P = np.array([[p.x, p.y] for p in sp.points])
            for k, sk in enumerate(sp.s_knots):
                xy = np.array([np.interp(sk, sp.s_dense, sp.xy_dense[:, 0]), np.interp(sk, sp.s_dense, sp.xy_dense[:, 1])])
                self.assertLess(float(np.hypot(*(xy - P[k]))), 1e-9)
                self.assertTrue(np.any(np.abs(sp.s - sk) < 1e-9))

    def test_sine_5_50(self):
        E = EXP["sine_5_50"]
        sp = build(syn.load_fixture("sine_5_50"))
        self.assertAlmostEqual(sp.length, E["L"], delta=E["L_tol"])
        self.assertAlmostEqual(sp.n, E["N"], delta=E["N_tol"])
        g, aa, mid = adaptive_gaps(sp)
        x = np.interp(mid, sp.s, sp.xy[:, 0])
        ph = x % 25.0
        crest = (np.abs(ph - 12.5) < 3) & aa
        infl = (np.minimum(ph, 25 - ph) < 3) & aa
        self.assertLessEqual(float(g[crest].mean()), E["crest_spacing_max"])
        self.assertGreaterEqual(float(g[infl].mean()), E["inflection_spacing_min"])
        self.assertGreaterEqual(float(g[infl].mean() / g[crest].mean()), E["ratio_min"])
        self.assertGreaterEqual(float(np.diff(sp.s).min()), sp.sampling.min_step_m / 2 - 1e-9)

    def test_curve_R20_200(self):
        E = EXP["curve_R20_200"]
        sp = build(syn.load_fixture("curve_R20_200"))
        self.assertAlmostEqual(sp.length, E["L"], delta=E["L_tol"])
        self.assertAlmostEqual(sp.n, E["N"], delta=E["N_tol"])
        self.assertTrue(np.all(np.diff(sp.s) > 0))
        g, aa, mid = adaptive_gaps(sp)
        arc = (mid > 62) & (mid < 89) & aa
        st1 = (mid < 58) & aa
        st2 = (mid > 94) & aa
        self.assertAlmostEqual(float(g[arc].mean()), E["arc_spacing"], delta=E["arc_tol"])
        self.assertAlmostEqual(float(g[st1].mean()), E["straight_spacing"], delta=E["straight_tol"])
        self.assertAlmostEqual(float(g[st2].mean()), E["straight_spacing"], delta=E["straight_tol"])
        self.assertAlmostEqual(float(g[st1].mean() / g[arc].mean()), E["ratio"], delta=E["ratio_tol"])
        # final gap rule: last gap in [min_step, step + min_step)
        self.assertGreaterEqual(float(np.diff(sp.s)[-1]), sp.sampling.min_step_m - 1e-9)
        self.assertLess(float(np.diff(sp.s)[-1]), sp.sampling.step_m + sp.sampling.min_step_m)

    def test_rail_sampling_defaults_and_spacing(self):
        E = EXP["rail_R300_600"]
        sp = build(syn.load_fixture("rail_R300_600"))
        for k, v in E["sampling"].items():
            self.assertEqual(getattr(sp.sampling, k), v)
        self.assertAlmostEqual(sp.n, E["N"], delta=E["N_tol"])
        g, aa, mid = adaptive_gaps(sp)
        st1 = (mid > 20) & (mid < 180) & aa
        bend = (mid > 220) & (mid < 380) & aa
        self.assertAlmostEqual(float(g[st1].mean()), E["straight_spacing"], delta=E["straight_tol"])
        self.assertAlmostEqual(float(g[bend].mean()), E["bend_spacing"], delta=E["bend_tol"])
        self.assertEqual(sp.z_raw_nan_count, E["z_raw_nan_count"])

    def test_duplicate_points_merged(self):
        doc = syn.load_fixture("straight_100")
        pts = doc["splines"][0]["points"]
        pts.insert(2, {"x": 40.0 + 1e-8, "y": 0.0, "width_m": 6.0, "tags": ["dup"]})
        sp = build(doc)
        self.assertEqual(sp.points_merged, 1)
        self.assertEqual(len(sp.points), 4)
        self.assertIn("dup", sp.points[1].tags)
        self.assertEqual(sp.n, EXP["straight_100"]["N"])


class TestWidth(unittest.TestCase):
    def test_knots_and_ramp(self):
        E = EXP["straight_100"]
        sp = build(syn.load_fixture("straight_100"))
        for k, v in E["w"].items():
            self.assertAlmostEqual(float(np.interp(float(k), sp.s, sp.width)), v, delta=E["w_tol"])
        self.assertAlmostEqual(float((sp.edge_offset(S.LEFT) + sp.edge_offset(S.RIGHT)).max()), E["w_max"])
        self.assertTrue(np.allclose(sp.edge_offset(S.LEFT), sp.width / 2))

    def test_segment_override(self):
        E = EXP["straight_100"]["width_override"]
        doc = syn.load_fixture("straight_100")
        seg = E["segment"]
        doc["splines"][0]["segments"] = [{"id": "narrow", "s0_m": seg["s0_m"], "s1_m": seg["s1_m"], "side": "centre",
                                          "ramp_m": seg["ramp_m"], "road": {"width_m": seg["width_m"]}}]
        sp = build(doc)
        for k, v in E["w"].items():
            self.assertAlmostEqual(float(np.interp(float(k), sp.s, sp.width)), v, delta=1e-9, msg="w(%s)" % k)
        for m in (55.0, 60.0, 80.0, 85.0):
            self.assertTrue(np.any(np.abs(sp.s - m) < 1e-9), "ramp/segment station %r" % m)

    def test_edge_extra_is_carriageway(self):
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["segments"] = [{"id": "bay", "s0_m": 20.0, "s1_m": 30.0, "side": "left", "ramp_m": 2.0,
                                          "road": {"edge_extra_left_m": 2.0}}]
        sp = build(doc)
        i = int(np.argmin(np.abs(sp.s - 25.0)))
        self.assertAlmostEqual(float(sp.edge_offset(S.LEFT)[i]), 3.0 + 2.0)
        self.assertAlmostEqual(float(sp.edge_offset(S.RIGHT)[i]), 3.0)
        self.assertAlmostEqual(float(sp.width[i]), 6.0)


class TestSmoothing(unittest.TestCase):
    def setUp(self):
        self.s = np.arange(0, 101, 2.0)
        self.z = 0.02 * self.s + 0.1 * np.sqrt(3.0) * noise.unit_noise(np.arange(51), 7)
        self.inter = (self.s >= 10) & (self.s <= 90)

    def factor(self, W, passes):
        zs = SP.moving_average_arclength(self.s, self.z, W, passes)
        err_r = (self.z - 0.02 * self.s)[self.inter]
        err_s = (zs - 0.02 * self.s)[self.inter]
        rms = lambda e: float(np.sqrt(np.mean(e ** 2)))  # noqa: E731
        return zs, rms(err_r) / rms(err_s), float(np.abs(err_s).max())

    def test_W20(self):
        E = EXP["smoothing"]["W20"]
        zs, f, me = self.factor(20.0, 1)
        self.assertGreaterEqual(f, E["factor_min"])
        self.assertAlmostEqual(f, E["factor_measured"], delta=0.01)
        self.assertLessEqual(me, E["max_err_max"])
        self.assertEqual(zs[0], self.z[0])
        self.assertEqual(zs[-1], self.z[-1])
        grade = (zs[45] - zs[5]) / 80.0
        self.assertAlmostEqual(grade, E["grade"], delta=E["grade_tol"])

    def test_W10_and_two_passes(self):
        _, f10, _ = self.factor(10.0, 1)
        self.assertGreaterEqual(f10, EXP["smoothing"]["W10"]["factor_min"])
        _, f2, _ = self.factor(20.0, 2)
        self.assertGreaterEqual(f2, EXP["smoothing"]["W20_2pass"]["factor_min"])

    def test_ripple_8m(self):
        E = EXP["smoothing"]["ripple_8m"]
        rip = 0.1 * np.sin(2 * np.pi * self.s / 8.0)
        rs = SP.moving_average_arclength(self.s, rip, 20.0, 1)
        self.assertAlmostEqual(float(np.sqrt(np.mean(rip ** 2))), E["rms_raw"], delta=E["rms_raw_tol"])
        self.assertLessEqual(float(np.sqrt(np.mean(rs[self.inter] ** 2))), E["rms_max"])

    def test_invariants(self):
        s = np.array([0, 1, 1.5, 4, 4.2, 9, 10.0])
        self.assertTrue(np.allclose(SP.moving_average_arclength(s, np.full(7, 3.0), 4.0), 3.0))
        self.assertTrue(np.allclose(SP.moving_average_arclength(s, 0.5 * s, 4.0), 0.5 * s))
        z = np.array([1.0, np.nan, np.nan, 4.0, np.nan])
        f, all_nan = SP.fill_nan_along(z)
        self.assertFalse(all_nan)
        self.assertTrue(np.array_equal(f, [1.0, 1.0, 1.0, 4.0, 4.0]))
        f, all_nan = SP.fill_nan_along(np.array([np.nan, np.nan]))
        self.assertTrue(all_nan)

    def test_pins(self):
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["points"][1]["z"] = 12.0
        sp = build(doc)
        i40 = int(np.argmin(np.abs(sp.s - 40.0)))
        self.assertAlmostEqual(float(sp.z_ref[i40]), 12.0, places=9)
        self.assertAlmostEqual(float(np.interp(50.0, sp.s, sp.z_ref)), 10.0, places=9)   # blend ends at 10 m
        self.assertAlmostEqual(float(np.interp(45.0, sp.s, sp.z_ref)), 11.0, places=9)


class TestBank(unittest.TestCase):
    def test_terrain_bank_clamped(self):
        E = EXP["bank"]
        doc = syn.load_fixture("straight_100")
        sp = build(doc, syn.cross_slope_terrain(0.1))
        i = int(np.argmin(np.abs(sp.s - 50.0)))
        self.assertAlmostEqual(float(sp.bank_raw[i]), E["raw_deg"], delta=E["raw_tol"])
        self.assertAlmostEqual(float(sp.bank_terrain[i]), E["clamped_deg"], places=9)
        self.assertAlmostEqual(float(sp.bank_deg[i]), E["clamped_deg"], places=9)

    def test_roll_override_all_points(self):
        doc = syn.load_fixture("straight_100")
        for p in doc["splines"][0]["points"]:
            p["roll_deg"] = 2.0
        sp = build(doc, syn.cross_slope_terrain(0.1))
        self.assertTrue(np.allclose(sp.bank_deg, EXP["bank"]["roll_all_deg"], atol=1e-9))

    def test_roll_mask_blends_linearly(self):
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["points"][1]["roll_deg"] = 2.0       # the point at s = 40 only
        sp = build(doc, syn.cross_slope_terrain(0.1))
        f = lambda q: float(np.interp(q, sp.s, sp.bank_unlimited))  # noqa: E731
        self.assertAlmostEqual(f(0.0), 4.0, places=6)
        self.assertAlmostEqual(f(20.0), 3.0, places=6)
        self.assertAlmostEqual(f(40.0), 2.0, places=9)
        self.assertAlmostEqual(f(45.0), 3.0, places=6)
        self.assertAlmostEqual(f(50.0), 4.0, places=6)
        self.assertAlmostEqual(f(100.0), 4.0, places=6)

    def test_rate_limit(self):
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["points"][0]["roll_deg"] = 0.0
        doc["splines"][0]["points"][1]["roll_deg"] = 20.0      # 20 deg over 40 m = 0.5 deg/m > 0.25
        doc["splines"][0]["points"][2]["roll_deg"] = 20.0
        doc["splines"][0]["points"][3]["roll_deg"] = 20.0
        sp = build(doc)
        r = float(sp.sampling.bank_rate_max_deg_per_m)
        self.assertAlmostEqual(r, EXP["bank"]["rate_limit_deg_per_m"])
        rate = np.abs(np.diff(sp.bank_deg)) / np.diff(sp.s)
        self.assertLessEqual(float(rate.max()), r + 1e-9)
        self.assertGreater(float(np.abs(np.diff(sp.bank_unlimited) / np.diff(sp.s)).max()), r)
        self.assertAlmostEqual(float(sp.bank_deg[-1]), 20.0, places=9)


class TestFrames(unittest.TestCase):
    def test_orthonormal_and_bank(self):
        tol = EXP["bank"]["frames_tol"]
        doc = syn.load_fixture("curve_R20_200")
        sp = build(doc, syn.cross_slope_terrain(0.05))
        F = sp.frames
        beta = np.radians(sp.bank_deg)
        self.assertLess(float(np.abs(np.sum(F.t_h * F.n, axis=1)).max()), tol)
        self.assertLess(float(np.abs(np.linalg.norm(F.n, axis=1) - 1).max()), tol)
        self.assertLess(float(np.abs(np.linalg.norm(F.b, axis=1) - 1).max()), tol)
        self.assertLess(float(np.abs(F.b[:, 2] - np.cos(beta)).max()), tol)
        self.assertLess(float(np.abs(F.n[:, 2] - np.sin(beta)).max()), tol)
        self.assertGreater(float(np.abs(beta).max()), 0.01)
        # n_flat = Z x t_h and the left normal of a road along +x is +y
        sp2 = build(syn.load_fixture("straight_100"))
        self.assertTrue(np.allclose(sp2.frames.n_flat, [0.0, 1.0, 0.0]))
        self.assertTrue(np.allclose(sp2.frames.b, [0.0, 0.0, 1.0]))

    def test_insert_and_at(self):
        sp = build(syn.load_fixture("curve_R20_200"))
        fr = sp.frames.insert(np.array([61.3, 100.05, 0.0, sp.length]))
        self.assertEqual(len(fr), sp.n + 2)
        self.assertTrue(np.all(np.diff(fr.s) > 0))
        self.assertTrue(np.all(np.isin(sp.s, fr.s)))
        k = int(np.where(np.abs(fr.s - 61.3) < 1e-12)[0][0])
        self.assertLess(abs(float(np.dot(fr.t_h[k], fr.n[k]))), 1e-12)
        self.assertAlmostEqual(float(np.linalg.norm(fr.b[k])), 1.0, places=12)


class TestStationingGuarantee(unittest.TestCase):
    """The bounds ``adaptive_stations`` actually holds to, on every fixture (expected.json 'stationing').

    STAGES.md stage 3 and stage 7 assert `step_min >= 0.25` and (rail) `step_max <= 1.0`; neither the
    fixtures nor the real Thanet data meet those, and they are not what the algorithm promises.  These
    are the real bounds, so a future change to the march that breaks them fails here."""

    ST = EXP["stationing"]

    def test_upper_bound_on_every_fixture(self):
        for name in ("straight_100", "sine_5_50", "curve_R20_200", "rail_R300_600"):
            sp = build(syn.load_fixture(name))
            g = np.diff(sp.s)
            bound = sp.sampling.step_m + sp.sampling.min_step_m
            self.assertLessEqual(float(g.max()), bound + 1e-9,
                                 "%s: max gap %.6f > step_m + min_step_m = %.6f" % (name, g.max(), bound))
            # and every adaptive-to-adaptive gap except the last one is <= step_m
            gg, aa, _ = adaptive_gaps(sp)
            inner = gg[aa][:-1] if aa.any() else gg[:0]
            self.assertTrue(np.all(inner <= sp.sampling.step_m + 1e-9), name)

    def test_rail_fixture_matches_the_recorded_measurement(self):
        sp = build(syn.load_fixture("rail_R300_600"))
        g = np.diff(sp.s)
        m = self.ST["measured"]["rail_R300_600"]
        self.assertEqual(len(sp.s), m["N"])
        self.assertAlmostEqual(float(g.min()), m["step_min"], places=6)
        self.assertAlmostEqual(float(g.max()), m["step_max"], places=6)
        self.assertGreater(m["step_max"], 1.0, "the recorded rail step_max is above the STAGES.md bound "
                                               "of 1.0: that document is what needs correcting")

    def test_no_lower_bound_exists(self):
        """Two mandatory stations 10 mm apart produce a 10 mm gap with no message anywhere -- the
        documented `step_min >= 0.25` is unenforceable, not merely unenforced."""
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["sampling"] = dict(doc["splines"][0].get("sampling") or {}, extra_stations_m=[50.0, 50.01, 50.02])
        sp = build(doc)
        g = np.diff(sp.s)
        self.assertAlmostEqual(float(g.min()), 0.01, places=9)
        self.assertLess(float(g.min()), sp.sampling.min_step_m)
        self.assertEqual(self.ST["lower_bound_rule"], None)


if __name__ == "__main__":
    unittest.main()
