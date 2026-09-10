"""The corridor conform (D3): the ground under the built street is the street, and stays that way.

The defect this guards against is the one Alex reported from the editor -- "the real road geometry is
still fusing with the landscape".  Measured over the whole isle before the fix: 89.06 % of 666,314
stations had terrain above the carriageway, 866.06 km of 968.84 km, worst 13.698 m
(``projects/one/Saved/Diag/fusion_before_all.json``).  These tests are the permanent version of that
measurement, small enough to run in the suite:

  * a deliberately rough synthetic hill, a road that crosses a tile boundary, both edges kerbed --
    the burn must leave zero penetration and no float bigger than the kerb, and must not touch a cell
    outside the corridor;
  * the same on real Thanet splines and the real adapter landscape when the data is on disk;
  * and, when the product has been generated, the shipped ``landscape_conformed`` directory is
    checked for the things a consumer relies on: the manifest says the heights are not the survey,
    the delta rasters reconstruct the survey exactly, and the tile seams still agree.
"""
import json
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import conform as C, fusion as F, io_json, noise, schema as S  # noqa: E402
from streetscape.spline import Spline  # noqa: E402
from streetscape.terrain import Heightfield  # noqa: E402

CONFORMED_DIR = os.path.join(os.path.dirname(syn.THANET_LANDSCAPE), "landscape_conformed")


def rough(x, y):
    """A hill with 1 m-scale roughness: smooth enough to be ground, rough enough that a 6 m plank on
    its smoothed centreline is buried somewhere across its width at nearly every station."""
    i = (np.rint(x).astype(np.int64) * 7919 + np.rint(y).astype(np.int64) * 104729).astype(np.int64)
    n = noise.unit_noise(np.abs(i) % (1 << 30), 11)
    return (12.0 + 0.035 * x - 0.02 * y + 2.5 * np.sin(x / 23.0) + 1.5 * np.cos(y / 17.0)
            + 0.35 * np.sin(x / 3.1 + y / 2.7) + 0.18 * n)


def rough_field():
    return Heightfield.from_function(rough, extent_m=(1024.0, 1024.0), px_m=1.0, tile_m=512.0)


def shifted_straight(dx=470.0, dy=300.0):
    """schema/examples/synthetic_straight.json moved so the 100 m road crosses the x = 512 tile seam."""
    doc = syn.straight_100()
    for p in doc["splines"][0]["points"]:
        p["x"] = float(p["x"]) + dx
        p["y"] = float(p["y"]) + dy
    return doc


def burn(splines, hf, params=None):
    """Stamp every spline and return (conformed heightfield, accumulator, grid)."""
    params = params or C.CorridorParams()
    grid = C.MosaicGrid(nx=2, ny=2, res=513)
    acc = C.ConformAccumulator(grid)

    def z_raw_at(x, y):
        return hf.sample(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))

    for sp in splines:
        for cx, cy, z, rank, u in C.spline_targets(sp, params, z_raw_at):
            col = cx.astype(np.int64)
            row = (grid.H - 1) - cy.astype(np.int64)
            ok = (col >= 0) & (col < grid.W) & (row >= 0) & (row < grid.H)
            acc.add(col[ok], row[ok], z[ok], rank[ok], u[ok])
    acc.finish()
    return C.burn_heightfield(hf, grid, acc), acc, grid


class TestSyntheticCorridor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hf = rough_field()
        doc = shifted_straight()
        site = io_json.site_from_dict(doc)
        cls.sp = Spline(site.splines[0], site, cls.hf)
        cls.hf2, cls.acc, cls.grid = burn([cls.sp], cls.hf)

    def test_the_unconformed_ground_really_does_fuse(self):
        """Guard the guard: if the synthetic terrain were smooth the test below would prove nothing."""
        rec = F.audit_spline(self.sp, self.hf)
        pen = rec["penetration"][rec["valid"]]
        self.assertGreater(float((pen > 0.005).mean()), 0.5,
                           "the synthetic terrain is too smooth to exercise the burn")
        self.assertGreater(float(pen.max()), 0.05)

    def test_zero_penetration_after_the_burn(self):
        rec = F.audit_spline(self.sp, self.hf2)
        v = rec["valid"]
        self.assertTrue(v.any())
        self.assertLessEqual(float(rec["penetration"][v].max()), 0.005,
                             "terrain still above the built surface after the conform")

    def test_zero_penetration_with_the_landscape_triangulation(self):
        """The engine interpolates a quad as two triangles; the burn has to survive that rule too."""
        hf3 = C.burn_heightfield(self.hf, self.grid, self.acc)
        hf3.sampling = "landscape_triangulated"
        rec = F.audit_spline(self.sp, hf3)
        self.assertLessEqual(float(rec["penetration"][rec["valid"]].max()), 0.005)

    def test_no_visible_float(self):
        rec = F.audit_spline(self.sp, self.hf2)
        self.assertLessEqual(float(rec["float"][rec["valid"]].max()), 0.125,
                             "daylight under the kerb/pavement after the conform")

    def test_the_sink_is_hidden_by_the_block(self):
        """The sink never exceeds what the built block can cover -- that is what makes it data and
        not taste (conform.sink_profile).  A side with a kerb and pavement covers `skirt` (0.30 m in
        every shipped edge profile) and the sink may take at most `sink_cover_frac` of it; a bare
        ribbon covers only `skirt_drop_m` and keeps the floor, whose 1 cm of overhang is an order
        inside the 0.125 m float gate."""
        params = C.CorridorParams()
        sink = C.sink_profile(self.sp, params)
        self.assertLessEqual(float(sink.max()), params.sink_max_m + 1e-12)
        self.assertGreaterEqual(float(sink.min()), params.sink_m - 1e-12)
        for side in (S.LEFT, S.RIGHT):
            spec = self.sp.side_spec[side]
            has = np.asarray(spec.present, dtype=bool) & (np.asarray(spec.back_offset) > 0.0)
            if has.any():
                self.assertLessEqual(float(sink[has].max()),
                                     float(np.min(np.asarray(spec.skirt)[has])) * params.sink_cover_frac + 1e-12,
                                     "the sink takes more than its share of the pavement skirt")
            if (~has).any():
                bare = float(sink[~has].max()) - float(np.min(np.asarray(self.sp.skirt_drop_m)[~has]))
                self.assertLessEqual(bare, 0.03,
                                     "a ribbon with no kerb is sunk further than it can hide")

    def test_rule_delta_measures_both_interpolation_rules_and_restores_the_sampling(self):
        """``fusion.rule_delta`` is the committed form of the task-1 measurement: the same landscape,
        the same corridor points, read bilinear and read as the landscape's own triangle pair.

        Two things have to hold or the number means nothing.  First the two rules must AGREE at the
        grid posts and differ only between them (docs/TERRAIN_ROADS.md 3.3), which is what bounds the
        disagreement by |twist|/4 rather than leaving it open.  Second the call must not leave the
        heightfield on a different rule than it found it, because the audit that calls it samples with
        one rule on purpose and a leaked mutation would silently re-measure everything else."""
        hf = C.burn_heightfield(self.hf, self.grid, self.acc)
        hf.sampling = "landscape_triangulated"
        d, cb, ct = F.rule_delta(self.sp, hf, k_road=9)
        self.assertEqual(hf.sampling, "landscape_triangulated", "rule_delta leaked its sampling rule")
        self.assertGreater(d.size, 0)
        self.assertEqual(d.size, cb.size)
        # the two clearances differ by exactly the rule delta, by construction
        np.testing.assert_allclose(np.asarray(ct, dtype=np.float64) - np.asarray(cb, dtype=np.float64),
                                   np.asarray(d, dtype=np.float64), atol=1e-5)
        # at the posts themselves the rules are the same surface
        x0, y0 = 0.5 * (self.hf.bounds()[0] + self.hf.bounds()[2]), 0.5 * (self.hf.bounds()[1] + self.hf.bounds()[3])
        gx = np.floor(np.linspace(x0 - 40, x0 + 40, 41))
        gy = np.floor(np.linspace(y0 - 40, y0 + 40, 41))
        X, Y = np.meshgrid(gx, gy)
        hf.sampling = "bilinear"
        zb = hf.sample(X.ravel(), Y.ravel())
        hf.sampling = "landscape_triangulated"
        zt = hf.sample(X.ravel(), Y.ravel())
        np.testing.assert_allclose(zb, zt, atol=1e-9)
        s = F.rule_summary([d], [cb], [ct])
        self.assertEqual(s["points"], int(d.size))
        self.assertGreaterEqual(s["abs_bilinear_minus_triangulated_m"]["min"], 0.0)

    def test_lod_skeleton_is_the_surface_the_landscape_draws(self):
        """``Heightfield.lod_skeleton(k)`` must keep every 2^k-th post exactly and put the straight
        line between them everywhere else -- that is what the landscape's coarser meshes draw, and it
        is the difference between a road that is above the ground in the data and one that is visible
        (road_fusion_audit.py's header records the measurement)."""
        for k in (1, 2, 3):
            lod = self.hf2.lod_skeleton(k)
            s = 1 << k
            for key, T in self.hf2.tiles.items():
                A, B = np.asarray(T, dtype=np.float64), np.asarray(lod.tiles[key], dtype=np.float64)
                np.testing.assert_allclose(B[::s, ::s], A[::s, ::s], atol=1e-4,
                                           err_msg="LOD %d moved a post it is supposed to keep" % k)
                mid = B[s // 2::s, ::s]
                lo, hi = A[0::s, ::s][:-1], A[s::s, ::s]
                np.testing.assert_allclose(mid, 0.5 * (lo + hi), atol=1e-3,
                                           err_msg="LOD %d is not linear between the posts it keeps" % k)
                break
            self.assertEqual(set(lod.tiles), set(self.hf2.tiles))

    def test_outside_the_corridor_is_untouched(self):
        far = 0
        for key in self.hf.tiles:
            a, b = self.hf.tiles[key], self.hf2.tiles[key]
            same = a == b
            r0, c0 = self.grid.tile_origin(*key)
            untouched = self.acc.key[r0:r0 + 513, c0:c0 + 513] == C.KEY_NONE
            self.assertTrue(bool(same[untouched].all()),
                            "a cell no corridor claimed was rewritten")
            far += int(untouched.sum())
        self.assertGreater(far, 1000000)

    def test_the_burn_reaches_both_sides_of_the_tile_seam(self):
        """The corridor crosses x = 512, so the two tiles hold copies of the same column: a per-tile
        burn would disagree there (that is D1's mechanism).  The mosaic burn cannot."""
        for j in (0, 1):
            west = self.hf2.tiles[(0, j)][:, 512]
            east = self.hf2.tiles[(1, j)][:, 0]
            np.testing.assert_array_equal(west, east)
        touched = (self.acc.key[:, 512] != C.KEY_NONE).sum()
        self.assertGreater(int(touched), 5, "the fixture no longer crosses the seam")

    def test_deterministic(self):
        hf_b, _, _ = burn([self.sp], self.hf)
        for key in self.hf.tiles:
            np.testing.assert_array_equal(self.hf2.tiles[key], hf_b.tiles[key])

    def test_the_corridor_is_the_profile_width(self):
        """Corridor half width = edge_offset + kerb + pavement (+ verge + blend), from the profile
        data -- not a constant in the burn."""
        halves = C.corridor_half_widths(self.sp)
        o, back = halves[S.LEFT]
        spec = self.sp.side_spec[S.LEFT]
        np.testing.assert_allclose(o, self.sp.width / 2.0 + self.sp.extra[S.LEFT])
        np.testing.assert_allclose(back, spec.kerb_width + spec.pavement_width)
        self.assertGreater(float(o.max()), float(o.min()), "the fixture's width change is gone")

    def test_lower_target_wins_where_two_corridors_cross(self):
        """A second way crossing the first: the ground follows the LOWER surface, so neither road can
        be penetrated by the ground the other one asked for."""
        doc = shifted_straight()
        sp_a = self.sp
        cross = {
            "id": "cross", "points": [{"x": 520.0, "y": 250.0}, {"x": 520.0, "y": 350.0}],
            "profile_ids": doc["splines"][0]["profile_ids"],
            "source": {"osm_id": "1", "layer": "roads", "cls": "residential"},
        }
        doc2 = json.loads(json.dumps(doc))
        doc2["splines"] = [cross]
        site2 = io_json.site_from_dict(doc2)
        sp_b = Spline(site2.splines[0], site2, self.hf)
        hf2, acc, grid = burn([sp_a, sp_b], self.hf)
        for sp in (sp_a, sp_b):
            rec = F.audit_spline(sp, hf2)
            self.assertLessEqual(float(rec["penetration"][rec["valid"]].max()), 0.005, sp.id)
        self.assertGreater(acc.stats["contributions"], 0)


class TestRealThanetSample(unittest.TestCase):
    """The same assertion on real splines and the real survey, when the data is on disk."""

    @classmethod
    def setUpClass(cls):
        cls.hf = syn.thanet_landscape()
        cls.doc = syn.thanet_site("x16_y2")
        if cls.hf is None or cls.doc is None:
            raise unittest.SkipTest("data/thanet/out/unreal is not on disk")

    def test_a_real_tile_of_roads(self):
        site = io_json.site_from_dict(self.doc)
        man = self.hf.manifest
        grid = C.MosaicGrid.from_manifest(man)
        params = C.CorridorParams()
        acc = C.ConformAccumulator(grid)

        def z_raw_at(x, y):
            return self.hf.sample(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))

        splines = []
        for sdef in site.splines[:60]:
            if sdef.profile_ids.road is None:
                continue
            sp = Spline(sdef, site, self.hf)
            if any("no terrain under any station" in w for w in sp.warnings):
                continue
            splines.append(sp)
            for cx, cy, z, rank, u in C.spline_targets(sp, params, z_raw_at):
                col = cx.astype(np.int64)
                row = (grid.H - 1) - cy.astype(np.int64)
                ok = (col >= 0) & (col < grid.W) & (row >= 0) & (row < grid.H)
                acc.add(col[ok], row[ok], z[ok], rank[ok], u[ok])
        acc.finish()
        self.assertGreater(len(splines), 5)
        before = max(float(F.audit_spline(sp, self.hf)["penetration"].max()) for sp in splines)
        hf2 = C.burn_heightfield(self.hf, grid, acc)
        after = max(float(F.audit_spline(sp, hf2)["penetration"].max()) for sp in splines)
        self.assertGreater(before, 0.05, "the sample was already clean: it proves nothing")
        self.assertLessEqual(after, 0.005, "real roads still fuse after the conform")


class TestJunctionDiscs(unittest.TestCase):
    """The ground under Renderer A's junction patch is the patch.

    A corridor is a band along ONE spline, so between two arms, close to the node, there are wedges
    that no band covers as built surface -- only as the feathered blend, which is allowed to rise
    back to the survey.  The patch lays tarmac across exactly those wedges, and before
    ``conform.junction_targets`` existed 814 of 87,969 patch vertices over the isle sat below the
    conformed ground, worst 2.890 m (``Saved/Diag/junction_isle.json``) -- terrain standing up
    through the middle of a crossroads.  This is that measurement, on one real Thanet site, with the
    landscape read the way it draws.
    """

    @classmethod
    def setUpClass(cls):
        cls.hf = syn.thanet_landscape()
        # x21_y3 on purpose: it holds `roads:4591162:0`, the worst patch-below-ground vertex on the
        # isle before the disc burn existed (-2.890 m, Saved/Diag/junction_isle.json:worst).
        cls.doc = syn.thanet_site("x21_y3")
        if cls.hf is None or cls.doc is None:
            raise unittest.SkipTest("data/thanet/out/unreal is not on disk")

    def _stamp(self, site, plan, untrimmed, trimmed, params, grid, junctions: bool):
        acc = C.ConformAccumulator(grid)

        def z_raw_at(x, y):
            return self.hf.sample(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))

        def put(cx, cy, z, rank, u):
            col = cx.astype(np.int64)
            row = (grid.H - 1) - cy.astype(np.int64)
            ok = (col >= 0) & (col < grid.W) & (row >= 0) & (row < grid.H)
            acc.add(col[ok], row[ok], z[ok], rank[ok], u[ok])

        for sp in untrimmed.values():
            for batch in C.spline_targets(sp, params, z_raw_at, acc.stats):
                put(*batch)
        if junctions:
            for jid in sorted(plan.arms):
                if any(a.spline_id not in trimmed for a in plan.arms[jid]):
                    continue
                out = C.junction_targets(plan, jid, trimmed, params)
                if out is not None:
                    put(*out)
        acc.finish()
        return C.burn_heightfield(self.hf, grid, acc)

    def test_the_ground_under_a_junction_patch_is_the_patch(self):
        from streetscape.road import junction_surface, junction_target_z
        from streetscape.spline import JunctionPlan
        site = io_json.site_from_dict(self.doc)
        plan = JunctionPlan(site)
        if not plan.arms:
            self.skipTest("no junctions in this site document")
        params = C.CorridorParams()
        grid = C.MosaicGrid.from_manifest(self.hf.manifest)
        untrimmed, trimmed = {}, {}
        arm_ids = {a.spline_id for arms in plan.arms.values() for a in arms}
        for sdef in site.splines:
            if sdef.profile_ids.road is None or sdef.source is None:
                continue
            if sdef.source.layer not in ("roads", "rail"):
                continue
            if sdef.flags is not None and (sdef.flags.bridge or sdef.flags.tunnel):
                continue
            sp = Spline(sdef, site, self.hf)
            if any("no terrain under any station" in w for w in sp.warnings):
                continue
            untrimmed[sdef.id] = sp
            if sdef.id in arm_ids:
                trimmed[sdef.id] = Spline(sdef, site, self.hf, trim=plan.trim_for(sdef.id))
        self.assertGreater(len(trimmed), 5)

        def worst(hfb):
            """Deepest ground-above-patch over a 0.25 m scatter inside every patch, read with the
            landscape's own triangulation -- the surface the camera sees."""
            hfb.sampling = "landscape_triangulated"
            deepest = 0.0
            n = 0
            for jid in sorted(plan.arms):
                if any(a.spline_id not in trimmed for a in plan.arms[jid]):
                    continue
                res = junction_surface(plan, jid, trimmed)
                if res is None:
                    continue
                loop, apex = res
                gx = np.arange(loop[:, 0].min(), loop[:, 0].max() + 0.25, 0.25)
                gy = np.arange(loop[:, 1].min(), loop[:, 1].max() + 0.25, 0.25)
                X, Y = np.meshgrid(gx, gy)
                X, Y = X.ravel(), Y.ravel()
                pz = junction_target_z(loop, apex, X, Y)
                m = np.isfinite(pz)
                if not m.any():
                    continue
                gz = hfb.sample(X[m], Y[m])
                d = gz - pz[m]
                d = d[np.isfinite(d)]
                n += int(d.size)
                if d.size:
                    deepest = max(deepest, float(d.max()))
            return deepest, n

        bands_only = self._stamp(site, plan, untrimmed, trimmed, params, grid, junctions=False)
        with_discs = self._stamp(site, plan, untrimmed, trimmed, params, grid, junctions=True)
        before, n = worst(bands_only)
        after, _ = worst(with_discs)
        self.assertGreater(n, 5000, "the scatter is too small to prove anything")
        self.assertGreater(before, 0.05,
                           "the corridor bands alone already covered every patch here: the test "
                           "proves nothing and needs a site with real junction wedges")
        self.assertLessEqual(after, 0.0, "ground still stands through a junction patch after the burn")


class TestConformedProduct(unittest.TestCase):
    """What a consumer of ``landscape_conformed`` is entitled to assume."""

    @classmethod
    def setUpClass(cls):
        p = os.path.join(CONFORMED_DIR, "landscape_manifest.json")
        if not os.path.isfile(p):
            raise unittest.SkipTest("landscape_conformed has not been generated")
        with open(p, "r", encoding="utf-8") as fh:
            cls.man = json.load(fh)

    def test_the_manifest_says_it_is_not_the_survey(self):
        self.assertIn("conform", self.man)
        self.assertIn("NOT THE RAW SURVEY", self.man["heightmap"]["semantics"].upper())
        c = self.man["conform"]
        for k in ("corridor", "cells_changed", "max_fill_m", "max_cut_m", "source", "generator"):
            self.assertIn(k, c)
        self.assertGreater(int(c["cells_changed"]), 0)

    def test_the_delta_rasters_reconstruct_the_survey(self):
        res = int(self.man["res"])
        n = 0
        for t in self.man["conform_tiles"]:
            if not t.get("delta_file"):
                continue
            i, j = t["x"], t["y"]
            new = np.fromfile(os.path.join(CONFORMED_DIR, "hm_x%d_y%d.r16" % (i, j)), dtype="<u2")
            old = np.fromfile(os.path.join(syn.THANET_LANDSCAPE, "hm_x%d_y%d.r16" % (i, j)), dtype="<u2")
            d = np.fromfile(os.path.join(CONFORMED_DIR, t["delta_file"]), dtype="<i2")
            np.testing.assert_array_equal(new.astype(np.int64) - d.astype(np.int64), old.astype(np.int64))
            self.assertEqual(int((d != 0).sum()), int(t["cells_changed"]))
            n += 1
            if n >= 6:
                break
        self.assertGreater(n, 0)

    def test_the_tile_seams_still_agree(self):
        """The burn is done once over the site mosaic, so a sample two tiles share is one cell.  This
        is the D1 invariant and the conform must not reintroduce a seam."""
        res = int(self.man["res"])
        have = {(t["x"], t["y"]) for t in self.man["tiles"]
                if os.path.isfile(os.path.join(CONFORMED_DIR, "hm_x%d_y%d.r16" % (t["x"], t["y"])))}
        checked = 0
        for (i, j) in sorted(have):
            a = np.fromfile(os.path.join(CONFORMED_DIR, "hm_x%d_y%d.r16" % (i, j)), dtype="<u2").reshape(res, res)
            if (i + 1, j) in have:
                b = np.fromfile(os.path.join(CONFORMED_DIR, "hm_x%d_y%d.r16" % (i + 1, j)), dtype="<u2").reshape(res, res)
                np.testing.assert_array_equal(a[:, res - 1], b[:, 0])
                checked += 1
            if (i, j + 1) in have:
                b = np.fromfile(os.path.join(CONFORMED_DIR, "hm_x%d_y%d.r16" % (i, j + 1)), dtype="<u2").reshape(res, res)
                np.testing.assert_array_equal(a[0, :], b[res - 1, :])
                checked += 1
            if checked >= 60:
                break
        self.assertGreater(checked, 0)

    def test_the_clip_and_visibility_rasters_were_copied_untouched(self):
        for name in sorted(os.listdir(syn.THANET_LANDSCAPE))[:40]:
            if not (name.startswith("clip_") or name.startswith("vis_") or name.startswith("weight_")):
                continue
            with open(os.path.join(syn.THANET_LANDSCAPE, name), "rb") as fh:
                a = fh.read()
            with open(os.path.join(CONFORMED_DIR, name), "rb") as fh:
                b = fh.read()
            self.assertEqual(a, b, name)


if __name__ == "__main__":
    unittest.main()
