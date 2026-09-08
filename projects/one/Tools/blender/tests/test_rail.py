"""Rail as a road-profile kind on rail_R300_600 (STAGES.md stage 7, DESIGN.md 6)."""
import math
import os
import re
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json  # noqa: E402
from streetscape.build import build_spline  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))["rail_R300_600"]


class TestRail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = syn.load_fixture("rail_R300_600")
        site = io_json.site_from_dict(doc)
        cls.res = build_spline(site, doc["splines"][0]["id"], syn.terrain_for(doc))
        cls.sp = cls.res.spline
        cls.rb = cls.res.road

    def test_gauge_and_rail_top(self):
        rb = self.rb
        left = rb.vertices_of_groups(exact="rail:left")
        right = rb.vertices_of_groups(exact="rail:right")
        top = 0.055 + 0.15875
        self.assertAlmostEqual(float(rb.vh[left].max()), EXP["rail_top_above_ballast"], delta=EXP["rail_top_tol"])
        self.assertAlmostEqual(top, EXP["rail_top_above_ballast"], delta=1e-9)
        lh = left[np.abs(rb.vh[left] - top) < 1e-9]
        rh = right[np.abs(rb.vh[right] - top) < 1e-9]
        inner = float(rb.vd[lh].min() - rb.vd[rh].max())
        self.assertAlmostEqual(inner, EXP["gauge_inner_faces"], delta=EXP["gauge_tol"])
        centres = float(np.mean(rb.vd[left]) - np.mean(rb.vd[right]))
        self.assertAlmostEqual(centres, EXP["rail_centres"], delta=EXP["rail_centres_tol"])
        self.assertTrue(rb.is_closed_manifold(grp_filter={"rail:left"}))
        self.assertTrue(rb.is_closed_manifold(grp_filter={"rail:right"}))
        self.assertEqual(self.res.stats["validate"]["road"], [])

    def test_sleepers(self):
        sl = [i for i in self.res.instances if i.kind == "sleeper"]
        n_want = math.floor(self.sp.length / 0.65) + 1
        self.assertEqual(len(sl), n_want)
        self.assertEqual(len(sl), EXP["sleepers"])
        # pitch measured along s (the transforms sit on frames.at(s_j))
        s_j = np.array([0.65 * j for j in range(len(sl))])
        pos = np.array([i.position for i in sl])
        fr = self.sp.frames.at(s_j)
        self.assertLess(float(np.linalg.norm(pos - (fr.p - 0.10 * fr.b), axis=1).max()), 1e-9)
        self.assertTrue(np.allclose(np.diff(s_j), EXP["sleeper_pitch"], atol=EXP["sleeper_pitch_tol"]))
        for i in sl[:5]:
            self.assertEqual(tuple(i.size), (0.25, 2.5, 0.15))
            self.assertEqual(i.material, "sleeper_concrete")

    def test_ballast(self):
        rb = self.rb
        bal = rb.vertices_of_groups(exact="ballast")
        top = bal[np.abs(rb.vh[bal]) < 1e-9]
        toe = bal[np.abs(rb.vh[bal] + 0.45) < 1e-9]
        self.assertAlmostEqual(float(rb.vd[top].max() - rb.vd[top].min()), EXP["ballast_top_width"], places=9)
        self.assertAlmostEqual(float(rb.vd[toe].max() - rb.vd[toe].min()), EXP["ballast_toe_width"], places=9)
        self.assertEqual(set(rb.material_names[m] for m in np.unique(rb.mat[rb.group_mask_tris(exact="ballast")])), {"ballast"})

    def test_tessellation_and_heights(self):
        sp = self.sp
        self.assertEqual(sp.z_raw_nan_count, EXP["z_raw_nan_count"])
        self.assertEqual(sp.kind, "rail")
        g = np.diff(sp.s)
        aa = ~(sp.mandatory[1:] | sp.mandatory[:-1])
        mid = (sp.s[1:] + sp.s[:-1]) / 2
        st1 = (mid > 20) & (mid < 180) & aa
        bend = (mid > 220) & (mid < 380) & aa
        self.assertAlmostEqual(float(g[st1].mean()), EXP["straight_spacing"], delta=EXP["straight_tol"])
        self.assertAlmostEqual(float(g[bend].mean()), EXP["bend_spacing"], delta=EXP["bend_tol"])
        # every station height is a terrain sample (flat 10 -> z_ref 10 everywhere, no lerp between waypoints)
        self.assertTrue(np.allclose(sp.z_raw, 10.0))
        self.assertLessEqual(float(g.max()), sp.sampling.step_m + sp.sampling.min_step_m)

    def test_no_rail_code_outside_rail_py(self):
        src = open(os.path.join(syn.TOOLS_BLENDER, "streetscape", "road.py"), encoding="utf-8").read()
        lines = [ln for ln in src.splitlines() if re.search(r"\brail\b", ln) and not ln.strip().startswith("#") and '"""' not in ln]
        code_lines = [ln for ln in lines if "import rail" in ln or "rail.build_rail" in ln or 'kind == "rail"' in ln]
        self.assertEqual(len(lines), len(code_lines), "rail-specific code outside the dispatch: %s" % lines)
        for mod in ("edge.py", "hedge.py", "sweep.py", "mesh.py"):
            s = open(os.path.join(syn.TOOLS_BLENDER, "streetscape", mod), encoding="utf-8").read()
            self.assertEqual(len(re.findall(r"build_rail|gauge_m|sleeper", s)), 0, mod)


if __name__ == "__main__":
    unittest.main()
