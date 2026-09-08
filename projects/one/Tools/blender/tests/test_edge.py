"""Renderer B: kerb rows, drop kerb, split materials, barriers, embankments (STAGES.md stage 5)."""
import copy
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json, schema as S  # noqa: E402
from streetscape.build import build_spline  # noqa: E402
from streetscape.edge import post_stations  # noqa: E402
from streetscape.terrain import Heightfield  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))
E1 = EXP["straight_100"]


def doc_with(segments=None, drop_kerbs=None, profiles_edge=None):
    doc = syn.load_fixture("straight_100")
    if profiles_edge:
        for pid in profiles_edge:
            doc["profiles"]["edge"][pid] = syn.library_profile(pid)
    if segments is not None:
        doc["splines"][0]["segments"] = segments
    if drop_kerbs is not None:
        doc["splines"][0]["drop_kerbs"] = drop_kerbs
    return doc


def build(doc, terrain=None):
    site = io_json.site_from_dict(doc)
    return build_spline(site, doc["splines"][0]["id"], terrain if terrain is not None else syn.terrain_for(doc))


def rows_at(buf, sp, side, s, group="kerb"):
    vi = buf.vertices_of_groups(exact=group)
    sel = vi[np.abs(buf.vs[vi] - s) < 1e-9]
    i = int(np.argmin(np.abs(sp.s - s)))
    o = side * buf.vd[sel] - sp.edge_offset(side)[i]
    h = buf.vh[sel] - sp.edge_height(side)[i]
    return o, h, sel


class TestKerb(unittest.TestCase):
    def test_rows(self):
        res = build(syn.load_fixture("straight_100"))
        sp = res.spline
        K = E1["kerb"]
        for side in (S.LEFT, S.RIGHT):
            e = res.edge[side]
            o, h, sel = rows_at(e, sp, side, 20.0)
            self.assertLess(abs(float(np.min(o)) - K["row_A_o"]), 1e-12)
            self.assertLess(abs(float(np.min(h)) - K["row_B_h"]), 1e-12)
            top = h[np.abs(h - 0.125) < 1e-12]
            self.assertGreaterEqual(len(top), 3)                      # D, S, E share one height: flush
            self.assertLess(float(np.ptp(e.v[sel][np.abs(h - 0.125) < 1e-12][:, 2])), K["flush_tol"])
            # lip arc points lie on the radius-0.02 arc centred (0.02, 0.105)
            lip = (o > 0) & (o < 0.02) & (h > 0.105) & (h < 0.125)
            self.assertEqual(int(lip.sum()), 3)
            r = np.hypot(o[lip] - 0.02, h[lip] - 0.105)
            self.assertTrue(np.allclose(r, 0.02, atol=1e-12))
            # pavement back edge F at kw + pw = 1.925, height 0.17; G at -0.30
            op, hp, _ = rows_at(e, sp, side, 20.0, "pavement")
            self.assertAlmostEqual(float(op.max()), 0.125 + 1.8, places=12)
            self.assertAlmostEqual(float(hp.max()), E1["drop_kerb"]["hk_back_nominal"], places=12)
            self.assertAlmostEqual(float(hp.min()), -0.30, places=12)
            self.assertEqual(res.stats["validate"]["edge_left" if side == S.LEFT else "edge_right"], [])

    def test_drop_kerb(self):
        res = build(syn.load_fixture("straight_100"))
        sp = res.spline
        D = E1["drop_kerb"]
        tl = sp.side_tl[S.LEFT]
        q = np.array([D["flat_centre_s"], D["ramp_mid_down_s"], D["ramp_mid_up_s"], 20.0])
        spec = tl.evaluate(q)
        self.assertAlmostEqual(float(spec.hk[0]), D["hk_flat"], delta=D["tol"])
        self.assertAlmostEqual(float(spec.hk[1]), D["hk_ramp_mid"], delta=D["tol"])
        self.assertAlmostEqual(float(spec.hk[2]), D["hk_ramp_mid"], delta=D["tol"])
        self.assertAlmostEqual(float(spec.hk[3]), 0.125, delta=D["tol"])
        self.assertAlmostEqual(float(spec.hk_back[0]), D["hk_back_flat"], delta=D["tol"])
        self.assertAlmostEqual(float(spec.hk_back[3]), D["hk_back_nominal"], delta=D["tol"])
        # the mesh at the flat-run station 70.915 is not a station; at 70.0 (flat) the face is 6 mm and F is at 0.150
        e = res.edge[S.LEFT]
        o, h, _ = rows_at(e, sp, S.LEFT, 70.0)
        self.assertAlmostEqual(float(h.max()), D["hk_flat"], delta=D["tol"])
        op, hp, _ = rows_at(e, sp, S.LEFT, 70.0, "pavement")
        self.assertAlmostEqual(float(hp.max()), D["hk_back_flat"], delta=D["tol"])
        # the right side (no drop kerb) keeps 0.125 everywhere
        self.assertTrue(np.allclose(sp.side_spec[S.RIGHT].hk, 0.125))
        # drop kerb stations are exact floats in s
        for m in (70.0 - 0.915, 70.0, 71.83, 72.745):
            self.assertTrue(np.any(sp.s == m))

    def test_split_materials_flush_and_ramp_down(self):
        doc = doc_with(segments=[{"id": "hg", "s0_m": 30.0, "s1_m": 80.0, "side": "left", "edge": {"profile_id": "edge_uk_half_grass"}}],
                       profiles_edge=["edge_uk_half_grass"])
        res = build(doc)
        sp = res.spline
        e = res.edge[S.LEFT]
        spec = sp.side_spec[S.LEFT]
        o0 = sp.edge_offset(S.LEFT)
        h0 = sp.edge_height(S.LEFT)
        tarmac = e.material_names.index("tarmac")
        grass = e.material_names.index("grass")
        kerb_c = e.material_names.index("concrete_kerb")
        counts = {"inner": 0, "outer": 0, "kerb_outside_range": 0, "bad": 0}
        for t in np.where(e.group_mask_tris(exact="kerb"))[0]:
            f = e.f[t]
            s_m = float(e.vs[f].mean())
            o = float((e.vd[f] - np.interp(e.vs[f], sp.s, o0)).mean())
            h = float((e.vh[f] - np.interp(e.vs[f], sp.s, h0)).mean())
            i = int(np.argmin(np.abs(sp.s - s_m)))
            if h < spec.hk[i] - 1e-6:
                continue                                                    # not the top
            if 30.0 < s_m < 80.0:
                if o < 0.0625 - 1e-9:
                    counts["inner" if e.mat[t] == tarmac else "bad"] += 1
                elif o > 0.0625 + 1e-9:
                    counts["outer" if e.mat[t] == grass else "bad"] += 1
            else:
                counts["kerb_outside_range" if e.mat[t] == kerb_c else "bad"] += 1
        self.assertEqual(counts["bad"], 0, counts)
        self.assertGreater(counts["inner"], 0)
        self.assertGreater(counts["outer"], 0)
        self.assertGreater(counts["kerb_outside_range"], 0)
        # flush: every top-row vertex at a station has the same z
        kv = e.vertices_of_groups(exact="kerb")
        top = kv[np.abs(e.vh[kv] - np.interp(e.vs[kv], sp.s, h0 + spec.hk)) < 1e-12]
        for s in sp.s:
            sel = top[np.abs(e.vs[top] - s) < 1e-9]
            self.assertGreaterEqual(len(sel), 3)
            self.assertLess(float(np.ptp(e.v[sel][:, 2])), 1e-12)
        # the drop kerb at 70 lies inside the split run: both materials ride the same rows down
        i70 = int(np.argmin(np.abs(sp.s - 70.0)))
        self.assertAlmostEqual(float(spec.hk[i70]), 0.006, places=9)
        self.assertTrue(spec.split[i70])
        # switch stations exact, profile switch adds the ramp stations too
        for m in (25.0, 30.0, 80.0, 85.0):
            self.assertTrue(np.any(sp.s == m))

    def test_edge_null_side(self):
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["profile_ids"]["edge_right"] = None
        res = build(doc)
        self.assertIsNone(res.edge[S.RIGHT])
        self.assertIsNotNone(res.edge[S.LEFT])
        self.assertEqual(sorted(res.stats["overlap"]), ["left"])


class TestBarriers(unittest.TestCase):
    def test_post_rule(self):
        P = E1["posts"]
        self.assertEqual(len(post_stations(45.0, 100.0, 3.0)), P["chain_link_45_100_pitch3"])
        self.assertEqual(post_stations(45.0, 100.0, 3.0)[:3], [45.0, 48.0, 51.0])
        self.assertEqual(post_stations(45.0, 100.0, 3.0)[-2:], [96.0, 100.0])
        self.assertEqual(len(post_stations(45.0, 95.0, 3.0)), P["chain_link_45_95_pitch3"])
        self.assertEqual(post_stations(45.0, 95.0, 3.0)[-2:], [93.0, 95.0])
        self.assertEqual(len(post_stations(95.0, 140.0, 2.0)), P["railing_95_140_pitch2"])
        self.assertEqual(len(post_stations(20.0, 60.0, 2.0)), P["railing_20_60_pitch2"])

    def test_wall_fence_railing(self):
        doc = doc_with(segments=[
            {"id": "wall", "s0_m": 0.0, "s1_m": 45.0, "side": "right", "edge": {"barrier": {"type": "brick_wall", "height_m": 1.2, "thickness_m": 0.215, "material": "brick_red"}}},
            {"id": "fence", "s0_m": 45.0, "s1_m": None, "side": "right", "edge": {"barrier": {"type": "chain_link", "height_m": 1.2, "thickness_m": 0.05, "material": "chain_link", "post_pitch_m": 3.0}}},
            {"id": "railing", "s0_m": 20.0, "s1_m": 60.0, "side": "left", "edge": {"barrier": {"type": "railing", "height_m": 1.0, "thickness_m": 0.05, "material": "steel_painted_black", "post_pitch_m": 2.0, "rails_m": [0.98, 0.5, 0.1]}}},
        ])
        res = build(doc)
        sp = res.spline
        eR, eL = res.edge[S.RIGHT], res.edge[S.LEFT]
        wall = [g for g in eR.group_names if g.startswith("barrier:brick_wall")][0]
        self.assertTrue(eR.is_closed_manifold(grp_filter={wall}))
        wall_tris = eR.group_mask_tris(exact=wall)
        self.assertIn("coping_concrete", [eR.material_names[m] for m in np.unique(eR.mat[wall_tris])])
        self.assertIn("brick_red", [eR.material_names[m] for m in np.unique(eR.mat[wall_tris])])
        wv = np.unique(eR.f[wall_tris])
        self.assertEqual(float(eR.vs[wv].min()), 0.0)
        self.assertEqual(float(eR.vs[wv].max()), 45.0)
        # wall inner face at the pavement back edge, top at 1.2 above it, coping 0.05 higher and 0.025 proud each side
        spec = sp.side_spec[S.RIGHT]
        o = -eR.vd[wv] - np.interp(eR.vs[wv], sp.s, sp.edge_offset(S.RIGHT) + spec.back_offset)
        h = eR.vh[wv] - np.interp(eR.vs[wv], sp.s, sp.edge_height(S.RIGHT) + spec.hk_back)
        self.assertAlmostEqual(float(o.min()), -0.025, places=9)
        self.assertAlmostEqual(float(o.max()), 0.215 + 0.025, places=9)
        self.assertAlmostEqual(float(h.max()), 1.25, places=9)
        self.assertAlmostEqual(float(h.min()), -0.30, places=9)
        posts_r = [i for i in res.instances if i.kind == "post_round"]
        self.assertEqual(len(posts_r), E1["posts"]["chain_link_45_100_pitch3"])
        ps = sorted(float(np.interp(i.position[0], sp.xy[:, 0], sp.s)) for i in posts_r)
        self.assertTrue(np.allclose(ps[:-1], 45.0 + 3.0 * np.arange(18), atol=1e-6))
        self.assertAlmostEqual(ps[-1], 100.0, places=6)
        fence = [g for g in eR.group_names if g.startswith("barrier:chain_link")][0]
        self.assertIn("chain_link", eR.two_sided)
        fv = np.unique(eR.f[eR.group_mask_tris(exact=fence)])
        self.assertAlmostEqual(float(eR.vs[fv].min()), 45.0)
        self.assertAlmostEqual(float(eR.vs[fv].max()), 100.0)
        posts_s = [i for i in res.instances if i.kind == "post_square"]
        self.assertEqual(len(posts_s), E1["posts"]["railing_20_60_pitch2"])
        rail_grp = [g for g in eL.group_names if g.startswith("barrier:railing")][0]
        rv = np.unique(eL.f[eL.group_mask_tris(exact=rail_grp)])
        specL = sp.side_spec[S.LEFT]
        hr = eL.vh[rv] - np.interp(eL.vs[rv], sp.s, sp.edge_height(S.LEFT) + specL.hk_back)
        levels = np.unique(np.round(hr, 6))
        self.assertEqual(len(levels), 2 * EXP["straight_100"]["railing_rails"])
        self.assertTrue(np.allclose(sorted(levels), sorted([0.08, 0.12, 0.48, 0.52, 0.96, 1.0]), atol=1e-9))
        self.assertTrue(eL.is_closed_manifold(grp_filter={rail_grp}))
        self.assertEqual(res.stats["validate"]["edge_right"], [])
        self.assertEqual(res.stats["validate"]["edge_left"], [])
        # a barrier never changes the road/kerb seam
        self.assertEqual(res.stats["overlap"], {"left": {"min": 0.04, "max": 0.04}, "right": {"min": 0.04, "max": 0.04}})

    def test_barrier_only_profile(self):
        doc = doc_with(profiles_edge=["edge_barrier_only"])
        doc["splines"][0]["profile_ids"]["edge_left"] = "edge_barrier_only"
        doc["splines"][0]["segments"] = [{"id": "w", "s0_m": 0.0, "s1_m": None, "side": "left",
                                          "edge": {"barrier": {"type": "wood_fence", "height_m": 1.8, "thickness_m": 0.05, "material": "wood_fence", "post_pitch_m": 3.0, "offset_m": -0.025}}}]
        res = build(doc)
        e = res.edge[S.LEFT]
        self.assertNotIn("kerb", e.group_names)
        self.assertNotIn("pavement", e.group_names)
        self.assertTrue(any(g.startswith("barrier:wood_fence") for g in e.group_names))
        # centred on the kerb line: panel plane at offset + t/2 = 0
        o = e.vd - np.interp(e.vs, res.spline.s, res.spline.edge_offset(S.LEFT))
        self.assertTrue(np.allclose(o, 0.0, atol=1e-9))
        self.assertEqual(len([i for i in res.instances if i.kind == "post_round"]), len(post_stations(0.0, 100.0, 3.0)))

    def test_profile_level_barrier_list(self):
        doc = doc_with(profiles_edge=["edge_wall_brick"])
        doc["splines"][0]["profile_ids"]["edge_right"] = "edge_wall_brick"
        res = build(doc)
        e = res.edge[S.RIGHT]
        self.assertTrue(any(g.startswith("barrier:brick_wall") for g in e.group_names))
        wv = np.unique(e.f[e.group_mask_tris(prefix="barrier:brick_wall")])
        self.assertEqual(float(e.vs[wv].min()), 0.0)
        self.assertEqual(float(e.vs[wv].max()), 100.0)
        # a segment painting barrier: null removes it inside its range
        doc["splines"][0]["segments"] = [{"id": "gap", "s0_m": 40.0, "s1_m": 60.0, "side": "right", "edge": {"barrier": None}}]
        res2 = build(doc)
        e2 = res2.edge[S.RIGHT]
        st = np.unique(e2.vs[np.unique(e2.f[e2.group_mask_tris(prefix="barrier:brick_wall")])])
        self.assertTrue(np.all((st <= 40.0) | (st >= 60.0)))


class TestEmbankments(unittest.TestCase):
    def _doc(self, side="auto", kind="auto"):
        return doc_with(segments=[{"id": "emb", "s0_m": 0.0, "s1_m": None, "side": "both",
                                   "edge": {"embankment": {"side": side, "kind": kind, "material": "grass"}}}])

    def test_batter_only_where_dz_exceeds_threshold(self):
        # ground falls away on the left beyond y = 3: back edge (y = 4.925 .. 5.925) is 0.96+ m above it
        terrain = Heightfield.from_function(lambda x, y: 10.0 - 0.5 * np.maximum(0.0, y - 3.0), (512.0, 512.0), xy0=(0.0, -256.0))
        res = build(self._doc(), terrain)
        gl = [g for g in res.edge[S.LEFT].group_names if g.startswith("embankment")]
        gr = [g for g in res.edge[S.RIGHT].group_names if g.startswith("embankment")]
        self.assertEqual(gl, ["embankment:batter:0"])
        self.assertEqual(gr, [])
        e = res.edge[S.LEFT]
        bv = np.unique(e.f[e.group_mask_tris(prefix="embankment:batter")])
        # batter starts at the back edge and runs down at 1:1.5 to toe_extra below the ground
        sp = res.spline
        spec = sp.side_spec[S.LEFT]
        o = e.vd[bv] - np.interp(e.vs[bv], sp.s, sp.edge_offset(S.LEFT) + spec.back_offset)
        h = e.vh[bv] - np.interp(e.vs[bv], sp.s, sp.edge_height(S.LEFT) + spec.hk_back)
        top = np.abs(h) < 1e-9
        self.assertTrue(top.any())
        self.assertTrue(np.allclose(o[top], 0.0, atol=1e-9))
        low = ~top
        self.assertTrue(np.allclose(o[low] / (-h[low]), 1.5, atol=1e-9))
        self.assertEqual(res.stats["validate"]["edge_left"], [])

    def test_retaining_wall_only_where_ground_is_above(self):
        terrain = Heightfield.from_function(lambda x, y: 10.0 + 0.5 * np.maximum(0.0, y - 3.0), (512.0, 512.0), xy0=(0.0, -256.0))
        res = build(self._doc(), terrain)
        gl = [g for g in res.edge[S.LEFT].group_names if g.startswith("embankment")]
        gr = [g for g in res.edge[S.RIGHT].group_names if g.startswith("embankment")]
        self.assertEqual(gl, ["embankment:retaining_wall:0"])
        self.assertEqual(gr, [])
        e = res.edge[S.LEFT]
        self.assertTrue(e.is_closed_manifold(grp_filter={"embankment:retaining_wall:0"}))
        # below the threshold (0.35 m) nothing is emitted
        terrain2 = Heightfield.from_function(lambda x, y: 10.0 + 0.2 * (y > 3.0), (512.0, 512.0), xy0=(0.0, -256.0))
        res2 = build(self._doc(), terrain2)
        self.assertEqual([g for g in res2.edge[S.LEFT].group_names if g.startswith("embankment")], [])

    def test_side_and_kind_gating(self):
        terrain = Heightfield.from_function(lambda x, y: 10.0 - 0.5 * np.maximum(0.0, y - 3.0), (512.0, 512.0), xy0=(0.0, -256.0))
        res = build(self._doc(side="uphill", kind="auto"), terrain)
        self.assertEqual([g for g in res.edge[S.LEFT].group_names if g.startswith("embankment")], [])
        res = build(self._doc(side="right", kind="batter"), terrain)
        self.assertEqual([g for g in res.edge[S.LEFT].group_names if g.startswith("embankment")], [])
        res = build(self._doc(side="left", kind="retaining_wall"), terrain)
        self.assertEqual([g for g in res.edge[S.LEFT].group_names if g.startswith("embankment")], [])
        res = build(self._doc(side="downhill", kind="batter"), terrain)
        self.assertEqual([g for g in res.edge[S.LEFT].group_names if g.startswith("embankment")], ["embankment:batter:0"])


if __name__ == "__main__":
    unittest.main()
