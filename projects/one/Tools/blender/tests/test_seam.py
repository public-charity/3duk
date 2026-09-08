"""DESIGN.md 5 rules 1-6 on the three synthetic roads, with and without the drop kerb and with a
mid-spline edge_uk_half_grass switch."""
import copy
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json, schema as S  # noqa: E402
from streetscape.build import build_spline  # noqa: E402
from streetscape.mesh import MeshBuffer, measure_lateral_overlap, coincident_xy_pairs, station_values  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))["straight_100"]
OV, SD, TD, TI = EXP["overlap_m"], EXP["skirt_drop_m"], EXP["tuck_depth_m"], EXP["tuck_in_m"]


def variants():
    for name in ("straight_100", "sine_5_50", "curve_R20_200"):
        base = syn.load_fixture(name)
        yield name + " (as is)", base
        d = copy.deepcopy(base)
        d["splines"][0]["drop_kerbs"] = [{"side": "both", "s_m": 30.0}]
        yield name + " (drop kerb both at 30)", d
        d = copy.deepcopy(base)
        d["splines"][0]["drop_kerbs"] = []
        yield name + " (no drop kerb)", d
        d = copy.deepcopy(base)
        d["profiles"]["edge"]["edge_uk_half_grass"] = syn.library_profile("edge_uk_half_grass")
        d["splines"][0]["segments"] = [{"id": "hg", "s0_m": 20.0, "s1_m": 60.0, "side": "both", "edge": {"profile_id": "edge_uk_half_grass"}}]
        yield name + " (half-grass switch 20-60)", d


class TestSeam(unittest.TestCase):
    def check(self, label, doc):
        site = io_json.site_from_dict(doc)
        res = build_spline(site, doc["splines"][0]["id"], syn.terrain_for(doc))
        sp = res.spline
        road = res.road
        # rule 2: identical stations (marking groups excluded)
        self.assertTrue(np.array_equal(station_values(road), sp.s), label)
        self.assertTrue(np.array_equal(station_values(res.edge[S.LEFT]), station_values(res.edge[S.RIGHT])), label)
        for side in (S.LEFT, S.RIGHT):
            e = res.edge[side]
            self.assertTrue(np.array_equal(station_values(e), sp.s), label)
            o0 = sp.edge_offset(side)
            h0 = sp.edge_height(side)
            spec = sp.side_spec[side]
            # rule 1: lateral overlap = 0.040 at every station
            m = measure_lateral_overlap(road, e, side, tuck_depth=TD)
            self.assertEqual(len(m["per_station"]), sp.n, label)
            self.assertTrue(np.all(np.isfinite(m["per_station"])), label)
            self.assertLess(float(np.abs(m["per_station"] - OV).max()), 1e-9, label)
            self.assertAlmostEqual(m["min_m"], OV, delta=1e-9)
            self.assertAlmostEqual(m["max_m"], OV, delta=1e-9)
            # rule 3: the skirt row sits strictly inside the kerb block at every station
            hk_min = float(spec.hk.min())
            self.assertTrue(0 < OV < 0.125 and -TD < -SD < hk_min, label)
            kv = e.vertices_of_groups(exact="kerb")
            o_k = side * e.vd[kv] - np.interp(e.vs[kv], sp.s, o0)
            self.assertLess(abs(float(o_k.min()) + TI), 1e-9, label)
            # rule 4: coincident distinct positions: 2 per station in [o0, o0 + ov], 0 in (o0 + 1e-6, o0 + ov]
            tot = 0
            strict = 0
            for i, s in enumerate(sp.s):
                sr = np.abs(road.vs - s) < 1e-9
                se = np.abs(e.vs - s) < 1e-9
                A = MeshBuffer(v=road.v[sr], vd=road.vd[sr])
                B = MeshBuffer(v=e.v[se], vd=e.vd[se])
                tot += coincident_xy_pairs(A, B, (o0[i], o0[i] + OV), side)
                strict += coincident_xy_pairs(A, B, (o0[i] + 1e-6, o0[i] + OV), side)
            self.assertEqual(tot, EXP["coincident_per_station"] * sp.n, label)
            self.assertEqual(strict, EXP["coincident_strict_band"], label)
            # rule 5: height coherence at the road-edge row and kerb row B
            rv = road.vertices_of_groups(exclude_prefix="marking:")
            edge_row = rv[np.abs(side * road.vd[rv] - np.interp(road.vs[rv], sp.s, o0)) < 1e-9]
            self.assertEqual(len(edge_row), sp.n, label)
            zr = np.interp(road.vs[edge_row], sp.s, sp.z_ref) + np.interp(road.vs[edge_row], sp.s, h0)
            self.assertLess(float(np.abs(road.v[edge_row][:, 2] - zr).max()), 1e-9, label)
            rowB = kv[(np.abs(o_k) < 1e-9) & (np.abs(e.vh[kv] - (np.interp(e.vs[kv], sp.s, h0) - TD)) < 1e-9)]
            self.assertGreaterEqual(len(rowB), sp.n, label)
            zb = np.interp(e.vs[rowB], sp.s, sp.z_ref) + np.interp(e.vs[rowB], sp.s, h0) - TD
            self.assertLess(float(np.abs(e.v[rowB][:, 2] - zb).max()), 1e-9, label)
            # rule 6: kerb face (x, y) equals road-edge (x, y) at every station (incl. the 6 -> 8 ramp)
            for i, s in enumerate(sp.s):
                r = edge_row[np.abs(road.vs[edge_row] - s) < 1e-9][0]
                b = rowB[np.abs(e.vs[rowB] - s) < 1e-9][0]
                self.assertLess(float(np.hypot(*(road.v[r][:2] - e.v[b][:2]))), 1e-9, label)
        self.assertEqual(res.stats["validate"]["road"], [], label)

    def test_all_variants(self):
        n = 0
        for label, doc in variants():
            with self.subTest(label=label):
                self.check(label, doc)
            n += 1
        self.assertEqual(n, 12)


if __name__ == "__main__":
    unittest.main()
