"""Renderer C: closed volume before/after noise, base row fixed, displacement bound, stacking beside
walls/fences, leaf-card count, determinism (STAGES.md stage 6)."""
import copy
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json, schema as S  # noqa: E402
from streetscape.build import build_spline  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))["hedge"]


def hedge_doc(noise_amp=None, top="flat", with_wall=True):
    doc = syn.load_fixture("straight_100")
    doc["profiles"]["hedge"]["hedge_privet"] = syn.library_profile("hedge_privet")
    doc["profiles"]["hedge"]["hedge_privet"]["top_profile"] = top
    if noise_amp is not None:
        doc["profiles"]["hedge"]["hedge_privet"]["noise_amplitude_m"] = noise_amp
    sp = doc["splines"][0]
    sp["profile_ids"]["hedge_right"] = "hedge_privet"
    sp["segments"] = []
    if with_wall:
        sp["segments"] += [
            {"id": "wall", "s0_m": 0.0, "s1_m": 45.0, "side": "right", "edge": {"barrier": {"type": "brick_wall", "height_m": 1.2, "thickness_m": 0.215, "material": "brick_red"}}},
            {"id": "fence", "s0_m": 45.0, "s1_m": 70.0, "side": "right", "edge": {"barrier": {"type": "chain_link", "height_m": 1.2, "thickness_m": 0.05, "material": "chain_link", "post_pitch_m": 3.0}}},
        ]
    sp["segments"].append({"id": "hedge", "s0_m": 30.0, "s1_m": 90.0, "side": "right", "hedge": {"present": True, "offset_m": EXP["offset_m"]}})
    return doc


def build(doc):
    site = io_json.site_from_dict(doc)
    return build_spline(site, doc["splines"][0]["id"], syn.terrain_for(doc))


class TestHedge(unittest.TestCase):
    def test_volume_manifold_and_noise(self):
        res = build(hedge_doc())
        res0 = build(hedge_doc(noise_amp=0.0))
        h, h0 = res.hedge[S.RIGHT], res0.hedge[S.RIGHT]
        self.assertTrue(h0.is_closed_manifold())
        self.assertTrue(h.is_closed_manifold())
        self.assertEqual(res.stats["validate"]["hedge_right"], [])
        self.assertEqual(len(h.v), len(h0.v))
        d = np.linalg.norm(h.v - h0.v, axis=1)
        self.assertLessEqual(float(d.max()), EXP["noise_amplitude_m"] + EXP["noise_tol"])
        self.assertGreater(float(d.max()), 0.01)
        sp = res.spline
        spec = sp.side_spec[S.RIGHT]
        base = np.interp(h.vs, sp.s, sp.edge_height(S.RIGHT) + spec.hk_back - 0.1)
        bottom = np.abs(h.vh - base) < 1e-9
        self.assertTrue(bottom.any())
        self.assertEqual(float(d[bottom].max()), 0.0)
        # spans s 30..90 with stations shared with the edge buffer
        self.assertEqual(float(h.vs.min()), 30.0)
        self.assertEqual(float(h.vs.max()), 90.0)
        self.assertTrue(np.all(np.isin(np.unique(h.vs), sp.s)))
        self.assertEqual(res.stats["buffers"]["hedge_right"]["tris"], len(h.f))

    def test_stacks_beside_wall_and_fence(self):
        res = build(hedge_doc(noise_amp=0.0))
        sp = res.spline
        h = res.hedge[S.RIGHT]
        spec = sp.side_spec[S.RIGHT]
        o = -h.vd - np.interp(h.vs, sp.s, sp.edge_offset(S.RIGHT) + spec.back_offset)
        for s, step in ((32.0, 0.215), (44.0, 0.215), (46.0, 0.05), (68.0, 0.05), (72.0, 0.0), (88.0, 0.0)):
            sel = np.abs(h.vs - s) < 1e-9
            self.assertTrue(sel.any(), s)
            inner = float(o[sel].min())
            self.assertLess(abs(inner - (step + EXP["offset_m"])), EXP["offset_tol"], "inner face at s=%g" % s)
            outer = float(o[sel].max())
            self.assertLess(abs(outer - (step + EXP["offset_m"] + 0.8)), EXP["offset_tol"])
        # height: 1.5 above the pavement back edge, sunk 0.1 below it
        hb = h.vh - np.interp(h.vs, sp.s, sp.edge_height(S.RIGHT) + spec.hk_back)
        self.assertAlmostEqual(float(hb.max()), 1.5, places=9)
        self.assertAlmostEqual(float(hb.min()), -0.1, places=9)

    def test_leaf_cards(self):
        res = build(hedge_doc())
        h = res.hedge[S.RIGHT]
        sp = res.spline
        spec = sp.side_spec[S.RIGHT]
        cards = [i for i in res.instances if i.kind == "leaf_card"]
        self.assertEqual(res.stats["instances"]["leaf_card"], len(cards))
        base = np.interp(h.vs, sp.s, sp.edge_height(S.RIGHT) + spec.hk_back - 0.1)
        hrel = (h.vh - base)
        tri_h = hrel[h.f].mean(axis=1)
        area = h.face_areas()[tri_h > 0.05].sum()
        self.assertAlmostEqual(len(cards) / (EXP["card_density_per_m2"] * area), 1.0, delta=EXP["card_tol_frac"])
        for c in cards[:50]:
            self.assertEqual(tuple(c.size), (0.25, 0.25, 0.0))
            self.assertEqual(c.material, "privet_leaf")
            M = c.transform
            self.assertAlmostEqual(float(np.linalg.norm(M[:3, 2])), 1.0, places=9)
        # no cards without foliage
        doc = hedge_doc()
        doc["profiles"]["hedge"]["hedge_privet"]["foliage"] = {"mode": "none"}
        self.assertNotIn("leaf_card", build(doc).stats["instances"])

    def test_deterministic(self):
        a = build(hedge_doc())
        b = build(hedge_doc())
        self.assertTrue(np.array_equal(a.hedge[S.RIGHT].v, b.hedge[S.RIGHT].v))
        self.assertTrue(np.array_equal(a.hedge[S.RIGHT].f, b.hedge[S.RIGHT].f))
        ia = [i for i in a.instances if i.kind == "leaf_card"]
        ib = [i for i in b.instances if i.kind == "leaf_card"]
        self.assertEqual(len(ia), len(ib))
        self.assertTrue(all(np.array_equal(x.transform, y.transform) for x, y in zip(ia, ib)))

    def test_top_profiles(self):
        for top in ("flat", "rounded", "domed"):
            res = build(hedge_doc(top=top, noise_amp=0.0))
            h = res.hedge[S.RIGHT]
            self.assertTrue(h.is_closed_manifold(), top)
            self.assertEqual(res.stats["validate"]["hedge_right"], [], top)

    def test_present_false_removes(self):
        doc = hedge_doc()
        doc["splines"][0]["segments"].append({"id": "gap", "s0_m": 50.0, "s1_m": 60.0, "side": "right", "hedge": {"present": False}})
        res = build(doc)
        h = res.hedge[S.RIGHT]
        st = np.unique(h.vs)
        self.assertTrue(np.all((st <= 50.0) | (st >= 60.0)))
        self.assertEqual(len([g for g in h.group_names if g.startswith("hedge:")]), 2)


if __name__ == "__main__":
    unittest.main()
