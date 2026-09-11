"""Junctions: the shared trim, Renderer A's patch and Renderer B's corner (SCHEMA.md 4.18).

Six synthetic shapes (``synthetic.JUNCTION_BUILDERS``) plus the real Isle of Thanet documents when
they are on disk.  Every assertion here is a MEASUREMENT of the finished buffers, in world metres,
not a restatement of how they were built:

  * no gap between the patch and any ribbon it meets, and none between a corner and any kerb it
    continues -- read back out of the meshes with ``build.junction_audit``;
  * no carriageway crossing the junction boundary -- every road vertex of an arm is at or beyond the
    trim, along the arm's own outward direction;
  * kerb corners continuous, one per adjacent pair;
  * the 40 mm road-over-kerb overlap preserved ALONG the corner, not just along the straights;
  * the stations Renderer A emits are exactly the stations Renderer B emits;
  * determinism: two builds of the same document are byte-identical.

``fixtures/expected.json:junction`` freezes the counts the C++ port has to reproduce.
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import synthetic as syn  # noqa: E402

from streetscape import io_json, schema as S  # noqa: E402
from streetscape.build import build_all, junction_audit  # noqa: E402
from streetscape.mesh import NON_STATION_PREFIXES, station_values  # noqa: E402
from streetscape.road import junction_boundary, junction_surface, junction_target_z  # noqa: E402
from streetscape.spline import JunctionPlan, Spline, arm_station_index  # noqa: E402

EXPECTED = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))
GAP_TOL_M = 1e-9          # the tolerance the no-crack claim is made at
OVERLAP_TOL_M = 1e-9

_CACHE = {}


def built(name: str):
    """(plan, results) for one synthetic junction fixture, built once for the whole module."""
    if name not in _CACHE:
        doc = syn.JUNCTION_BUILDERS[name]()
        site = io_json.site_from_dict(doc)
        plan = JunctionPlan(site)
        _CACHE[name] = (plan, build_all(site, syn.junction_terrain_for(doc), plan=plan))
    return _CACHE[name]


class TestPlan(unittest.TestCase):
    def test_every_arm_is_trimmed(self):
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            self.assertEqual(plan.stats["junctions_built"], 1, name)
            self.assertEqual(plan.stats["arms"], len(plan.arms["j0"]), name)
            for a in plan.arms["j0"]:
                sp = res[a.spline_id].spline
                self.assertTrue(sp.trimmed, "%s: %s not trimmed" % (name, a.spline_id))
                self.assertAlmostEqual(sp.s_trim[0], a.s_trim, places=9)

    def test_trim_radius_is_frozen(self):
        for name, want in EXPECTED["junction"]["fixtures"].items():
            plan, _res = built(name)
            self.assertAlmostEqual(plan.trim_radius["j0"], want["trim_radius_m"], places=6, msg=name)

    def test_wide_arm_is_pushed_back_further_than_a_narrow_one(self):
        """The whole point of "the trim must account for the width": the 12 m trunk fixture ends up
        with a bigger junction than the 6 m crossroads at the same angles and the same radius_m."""
        wide, _ = built("junction_widths")
        narrow, _ = built("junction_crossroads")
        self.assertGreater(wide.trim_radius["j0"], narrow.trim_radius["j0"] + 1.0)

    def test_arc_length_is_not_rebased(self):
        """The trim is a mask: L, the station array and every s in it are the document's own."""
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            for a in plan.arms["j0"]:
                sp = res[a.spline_id].spline
                self.assertAlmostEqual(sp.length, sp.s[-1], places=9)
                self.assertEqual(sp.s[0], 0.0)
                self.assertTrue(np.all(np.diff(sp.s) > 0))
                self.assertIn(sp.s_trim[0], list(sp.s))         # the trim is a station, exactly


class TestPatch(unittest.TestCase):
    def test_no_gap_between_patch_and_ribbon(self):
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            rep = junction_audit(plan, res)
            self.assertEqual(rep["patches"], 1, name)
            self.assertLessEqual(rep["worst_patch_gap_m"], GAP_TOL_M,
                                 "%s: patch/ribbon gap %g m at %s" % (name, rep["worst_patch_gap_m"],
                                                                     rep["worst_patch_gap_at"]))

    def test_patch_does_not_overlap_itself(self):
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            rep = junction_audit(plan, res)
            self.assertEqual(rep["non_monotone"], 0, name)
            self.assertLess(rep["patch_overlap_area_m2"], 1e-6, name)

    def test_no_carriageway_crosses_the_junction_boundary(self):
        """Along each arm's own outward direction, every road / skirt vertex of that arm is at or
        beyond the trim.  The arms are straight in these fixtures, so the trim distance along the
        spline IS the trim radius and the bound is exact."""
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            node = np.array([plan.junction("j0").x, plan.junction("j0").y])
            for a in plan.arms["j0"]:
                r = res[a.spline_id]
                vi = r.road.vertices_of_groups(exclude_prefix=NON_STATION_PREFIXES)
                proj = (r.road.v[vi][:, :2] - node) @ a.u
                self.assertGreaterEqual(float(proj.min()), a.s_trim - 1e-6,
                                        "%s: %s reaches %.4f m from the node, trim is %.4f"
                                        % (name, a.spline_id, float(proj.min()), a.s_trim))

    def test_patch_is_a_surface_on_a_slope(self):
        """On the graded fixture the patch's boundary heights span the grade rather than sitting at
        one z, and its apex is at or above every arm's crown."""
        plan, res = built("junction_slope")
        loop, _slices, _corners = junction_boundary(plan, "j0", {k: v.spline for k, v in res.items()})
        span = float(loop[:, 2].max() - loop[:, 2].min())
        self.assertGreater(span, 0.4, "boundary z span %.4f m: the patch is flat" % span)
        info = [r.junctions["j0"] for r in res.values() if "j0" in r.junctions][0]
        for a in plan.arms["j0"]:
            sp = res[a.spline_id].spline
            i = arm_station_index(sp, a.end)
            self.assertGreaterEqual(info["z_apex"] + 1e-9, float(sp.frames.p[i][2]))

    def test_patch_is_in_the_road_buffer_with_the_road_material(self):
        """BRIEF 1.1 THREE RENDERERS ONLY: no fourth buffer, no fourth material."""
        for name in syn.JUNCTION_BUILDERS:
            _plan, res = built(name)
            owner = [r for r in res.values() if r.junctions][0]
            self.assertIn("junction:j0", owner.road.group_names)
            gid = owner.road.group_names.index("junction:j0")
            mats = set(owner.road.material_names[m] for m in np.unique(owner.road.mat[owner.road.grp == gid]))
            self.assertEqual(mats, {"tarmac"}, name)
            self.assertEqual(set(res.keys()) & {"junction"}, set())


class TestCorner(unittest.TestCase):
    def test_one_corner_per_adjacent_pair_and_no_gap(self):
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            rep = junction_audit(plan, res)
            self.assertEqual(rep["corners"], len(plan.arms["j0"]), name)
            self.assertLessEqual(rep["worst_corner_gap_m"], GAP_TOL_M,
                                 "%s: kerb/corner gap %g m at %s" % (name, rep["worst_corner_gap_m"],
                                                                    rep["worst_corner_gap_at"]))

    def test_overlap_along_the_corner(self):
        """The road-over-kerb rule, measured round the corner: the patch boundary between two arms is
        the corner kerb line pushed outward by exactly the profile's ``overlap_m`` and dropped by its
        ``skirt_drop_m`` -- the same 40 mm / 20 mm the ribbon carries along a straight."""
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            splines = {k: v.spline for k, v in res.items()}
            _loop, _slices, corners = junction_boundary(plan, "j0", splines)
            for af, nx, P, T, fr, ov, sd in corners:
                for q in range(len(P)):
                    pt = fr.p[q] - ov[q] * fr.n[q] - sd[q] * fr.b[q]
                    lateral = float(np.dot(pt - fr.p[q], -fr.n[q]))
                    drop = float(np.dot(pt - fr.p[q], fr.b[q]))
                    self.assertAlmostEqual(lateral, ov[q], delta=OVERLAP_TOL_M, msg=name)
                    self.assertAlmostEqual(drop, -sd[q], delta=OVERLAP_TOL_M, msg=name)
                self.assertAlmostEqual(float(ov[0]), 0.04, places=9, msg=name)
                self.assertAlmostEqual(float(sd[0]), 0.02, places=9, msg=name)

    def test_corner_is_tangent_to_both_kerbs(self):
        """G1 at both ends: the fillet leaves along the arm's own kerb line and arrives along the
        next arm's, so there is no kink where the kerb starts to turn."""
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            splines = {k: v.spline for k, v in res.items()}
            _loop, _slices, corners = junction_boundary(plan, "j0", splines)
            for af, nx, P, T, fr, ov, sd in corners:
                self.assertLess(float(np.linalg.norm(T[0] - (-af.u))), 1e-9, name)
                self.assertLess(float(np.linalg.norm(T[-1] - nx.u)), 1e-9, name)
                self.assertLess(float(np.linalg.norm(P[0] - af.p_hi)), 1e-12, name)
                self.assertLess(float(np.linalg.norm(P[-1] - nx.p_lo)), 1e-12, name)

    def test_corner_matches_a_circular_arc_where_one_exists(self):
        """The symmetric crossroads: the two kerb ends are equidistant from the node, so a circular
        arc tangent to both kerb lines does exist and the cubic must be it."""
        plan, res = built("junction_crossroads")
        splines = {k: v.spline for k, v in res.items()}
        _loop, _slices, corners = junction_boundary(plan, "j0", splines)
        for af, nx, P, T, fr, ov, sd in corners:
            # the arc centre is the intersection of the two end normals
            n0 = np.array([-(-af.u)[1], (-af.u)[0]])
            n1 = np.array([-nx.u[1], nx.u[0]])
            A = np.column_stack([n0, -n1])
            t = np.linalg.solve(A, P[-1][:2] - P[0][:2])
            centre = P[0][:2] + t[0] * n0
            r = float(np.linalg.norm(P[0][:2] - centre))
            err = np.abs(np.linalg.norm(P[:, :2] - centre, axis=1) - r).max()
            # 2.7e-4 r is the known worst-case error of the (4/3) tan(tau/4) cubic approximation of a
            # quarter circle: 0.27 mm on this 1 m corner.  A tighter bound would need a real arc
            # primitive in the sweep, and 0.27 mm is two orders below the 40 mm overlap it sits inside.
            self.assertLess(float(err), 3.0e-4 * r,
                            "corner deviates %.3g m from the %.3f m arc" % (float(err), r))


class TestConformHook(unittest.TestCase):
    """``junction_surface`` / ``junction_target_z``: the patch as a polygon plus a height sampler, so
    the corridor conform can burn the ground under a junction from the SAME surface the mesh is."""

    def test_sampler_reproduces_the_mesh(self):
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            loop, apex = junction_surface(plan, "j0", {k: v.spline for k, v in res.items()})
            z = junction_target_z(loop, apex, loop[:, 0], loop[:, 1])
            self.assertLess(float(np.nanmax(np.abs(z - loop[:, 2]))), 1e-9, name)
            self.assertAlmostEqual(float(junction_target_z(loop, apex, [apex[0]], [apex[1]])[0]),
                                   float(apex[2]), places=9, msg=name)
            far = junction_target_z(loop, apex, [apex[0] + 1000.0], [apex[1]])
            self.assertTrue(np.isnan(far[0]), name)


class TestStationsAndDeterminism(unittest.TestCase):
    def test_stations_identical_across_renderers(self):
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            for a in plan.arms["j0"]:
                r = res[a.spline_id]
                sp = r.spline
                want = sp.s[sp.active]
                self.assertTrue(np.array_equal(station_values(r.road), want), "%s road" % name)
                for side in (S.LEFT, S.RIGHT):
                    b = r.edge.get(side)
                    if b is None:
                        continue
                    st = station_values(b)
                    self.assertTrue(np.all(np.isin(st, want)),
                                    "%s edge %s carries a station outside the trim" % (name, side))
                self.assertTrue(r.stats["stations_identical"]["road"])

    def test_nothing_is_emitted_outside_the_trim(self):
        for name in syn.JUNCTION_BUILDERS:
            plan, res = built(name)
            for a in plan.arms["j0"]:
                sp = res[a.spline_id].spline
                for bname, b in res[a.spline_id].buffers().items():
                    vi = b.vertices_of_groups(exclude_prefix=NON_STATION_PREFIXES)
                    if not len(vi):
                        continue
                    self.assertGreaterEqual(float(b.vs[vi].min()), sp.s_trim[0] - 1e-9,
                                            "%s %s %s" % (name, a.spline_id, bname))

    def test_determinism(self):
        for name in syn.JUNCTION_BUILDERS:
            doc = syn.JUNCTION_BUILDERS[name]()
            site = io_json.site_from_dict(doc)
            ter = syn.junction_terrain_for(doc)
            a = build_all(site, ter)
            b = build_all(io_json.site_from_dict(syn.JUNCTION_BUILDERS[name]()), ter)
            for sid in a:
                for bn, ba in a[sid].buffers().items():
                    bb = b[sid].buffers()[bn]
                    self.assertEqual(ba.v.tobytes(), bb.v.tobytes(), "%s %s %s v" % (name, sid, bn))
                    self.assertEqual(ba.f.tobytes(), bb.f.tobytes(), "%s %s %s f" % (name, sid, bn))
                    self.assertEqual(ba.group_names, bb.group_names)


class TestFrozenCounts(unittest.TestCase):
    """The numbers the C++ port must reproduce exactly (SCHEMA.md 9.3)."""

    def test_counts(self):
        for name, want in EXPECTED["junction"]["fixtures"].items():
            plan, res = built(name)
            rep = junction_audit(plan, res)
            got = {
                "trim_radius_m": round(plan.trim_radius["j0"], 6),
                "arms": len(plan.arms["j0"]),
                "patch_verts": rep["patch_verts"],
                "patch_tris": rep["patch_tris"],
                "patch_boundary": [r.junctions["j0"]["boundary"] for r in res.values() if r.junctions][0],
                "patch_area_m2": round(rep["patch_area_m2"], 4),
                "corners": rep["corners"],
                "corner_tris": rep["corner_tris"],
                "total_verts": sum(b.stats()["verts"] for r in res.values() for b in r.buffers().values()),
                "total_tris": sum(b.stats()["tris"] for r in res.values() for b in r.buffers().values()),
            }
            for k, v in want.items():
                if isinstance(v, float):
                    self.assertAlmostEqual(got[k], v, places=4, msg="%s.%s" % (name, k))
                else:
                    self.assertEqual(got[k], v, "%s.%s: got %r want %r" % (name, k, got[k], v))


class TestAuditCLI(unittest.TestCase):
    """``python -m streetscape.build --junction-audit DIR --out JSON`` is the acceptance command of
    SCHEMA.md 9.3 -- the isle-wide measurement is quoted from its output, so it has to run.

    It did not: the ``if __name__ == "__main__"`` guard sat in the middle of build.py, above the audit
    section, so ``main`` dispatched to a ``_audit_main`` that had not been defined yet and every
    invocation died with ``NameError``.  Nothing in the suite called the module as a script, so nothing
    noticed.  This runs it as a script, on a one-document directory, in a subprocess."""

    def test_module_runs_as_a_script(self):
        import json
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            docs = os.path.join(tmp, "docs")
            os.makedirs(docs)
            with open(os.path.join(docs, "site_x0_y0.json"), "w", encoding="utf-8") as fh:
                json.dump(syn.junction_crossroads(), fh)
            out = os.path.join(tmp, "audit.json")
            env = dict(os.environ, PYTHONPATH=syn.TOOLS_BLENDER)
            p = subprocess.run([sys.executable, "-m", "streetscape.build",
                                "--junction-audit", docs, "--out", out],
                               cwd=syn.TOOLS_BLENDER, env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("JUNCTION_AUDIT", p.stdout, p.stdout + p.stderr)
            rep = syn.load_json(out)
            self.assertEqual(rep["totals"]["documents"], 1)
            self.assertEqual(rep["totals"]["junctions"], 1)
            self.assertEqual(rep["totals"]["patches"], 1)
            self.assertEqual(rep["totals"]["arms"], 4)
            self.assertEqual(rep["worst"]["patch_gap_m"], 0.0)
            self.assertEqual(rep["worst"]["corner_gap_m"], 0.0)


class TestDegenerate(unittest.TestCase):
    """A spline too short to survive trimming at both ends must degrade, not vanish or invert."""

    def _doc(self, length):
        doc = syn.junction_doc("junction_short", [0.0, 90.0, 180.0], length=length, radius_m=4.0)
        # arm0 becomes a stub between two junctions: give it a junction at BOTH ends
        j2 = {"id": "j1", "x": doc["splines"][0]["points"][-1]["x"],
              "y": doc["splines"][0]["points"][-1]["y"], "z": None, "radius_m": 4.0, "kind": "disc",
              "ends": [{"spline_id": "authored:arm0", "end": "end"}]}
        for bd, sid in ((90.0, "authored:arm3"), (270.0, "authored:arm4")):
            import copy
            import math
            s = copy.deepcopy(doc["splines"][1])
            s["id"] = sid
            th = math.radians(bd)
            s["points"] = [{"x": round(j2["x"] + math.cos(th) * t, 6),
                            "y": round(j2["y"] + math.sin(th) * t, 6), "width_m": 6.0}
                           for t in (0.0, 30.0, 60.0)]
            s["junction_start"] = "j1"
            s["overlay"] = {"kind": "other", "pts": [[p["x"], p["y"]] for p in s["points"]], "osm_id": None}
            doc["splines"].append(s)
            j2["ends"].append({"spline_id": sid, "end": "start"})
        doc["splines"][0]["junction_end"] = "j1"
        doc["junctions"].append(j2)
        return doc

    def test_short_spline_degrades(self):
        for length in (12.0, 8.0, 6.0, 4.0, 2.0, 1.5, 0.8):
            doc = self._doc(length)
            site = io_json.site_from_dict(doc)
            plan = JunctionPlan(site)
            # This checks the shared trim, independently of whether two overlapping
            # junction discs can form a valid fillet around the remaining stub.
            sp = Spline(site.spline("authored:arm0"),site,syn.junction_terrain_for(doc),
                        trim=plan.trim_for("authored:arm0"))
            t0, t1 = sp.s_trim
            self.assertLess(t0, t1, "L=%g: the trim inverted" % length)
            self.assertGreaterEqual(int(sp.active.sum()), 2, "L=%g: the spline vanished" % length)
            self.assertAlmostEqual(sp.length, length, delta=1e-6)
            if length > S.JUNCTION_DEFAULTS["min_remaining_m"]:
                self.assertGreaterEqual(t1 - t0, S.JUNCTION_DEFAULTS["min_remaining_m"] - 1e-6,
                                        "L=%g kept only %.4f m" % (length, t1 - t0))

    def test_gaps_survive_degeneracy(self):
        doc = self._doc(6.0)
        site = io_json.site_from_dict(doc)
        plan = JunctionPlan(site)
        res = build_all(site, syn.junction_terrain_for(doc), plan=plan)
        rep = junction_audit(plan, res)
        self.assertLessEqual(rep["worst_patch_gap_m"], GAP_TOL_M, str(rep["worst_patch_gap_at"]))
        self.assertLessEqual(rep["worst_corner_gap_m"], GAP_TOL_M, str(rep["worst_corner_gap_at"]))

    def test_folded_corner_between_overlapping_junctions_is_rejected(self):
        # The 2 m stub produced a near reversal inside a sub-millimetre radius.
        # Sampling it coarsely concealed that invalid pavement geometry.
        doc=self._doc(2.)
        site=io_json.site_from_dict(doc)
        with self.assertRaisesRegex(ValueError,'cannot meet quality limits'):
            build_all(site,syn.junction_terrain_for(doc),plan=JunctionPlan(site))


class TestValidation(unittest.TestCase):
    """io_json now reads junctions, so a junction that points at nothing is a structural error rather
    than an unread placeholder: it would silently shrink the node by one arm and change the trim radius
    of every other arm there."""

    def doc(self):
        return syn.junction_crossroads()

    def test_end_pointing_at_a_missing_spline(self):
        d = self.doc()
        d["junctions"][0]["ends"][1]["spline_id"] = "authored:nope"
        errs = io_json.validate_structure(d)
        self.assertTrue(any("is not in this document" in e for e in errs), errs)

    def test_unknown_junction_id_on_a_spline(self):
        d = self.doc()
        d["splines"][0]["junction_start"] = "j_nowhere"
        errs = io_json.validate_structure(d)
        self.assertTrue(any("is not in junctions[]" in e for e in errs), errs)

    def test_duplicate_junction_id(self):
        d = self.doc()
        d["junctions"].append(dict(d["junctions"][0]))
        self.assertTrue(any("duplicate junction id" in e for e in io_json.validate_structure(d)))

    def test_disc_with_too_few_arms_warns(self):
        d = self.doc()
        d["junctions"][0]["ends"] = d["junctions"][0]["ends"][:2]
        w = io_json.validate_warnings(d)
        self.assertTrue(any("nothing is trimmed or filled below 3" in x for x in w), w)

    def test_end_further_than_snap_warns(self):
        d = self.doc()
        d["junctions"][0]["x"] += 1.0
        w = io_json.validate_warnings(d)
        self.assertTrue(any("from the node" in x for x in w), w)

    def test_the_real_documents_are_clean(self):
        doc = syn.thanet_site("x13_y3")
        if doc is None:
            self.skipTest("Thanet streetscape products not on disk")
        self.assertEqual(io_json.validate_structure(doc), [])
        self.assertEqual([x for x in io_json.validate_warnings(doc) if "junction" in x], [])


@unittest.skipIf(syn.thanet_site("x10_y12") is None, "Thanet streetscape products not on disk")
class TestThanet(unittest.TestCase):
    """The real isle, on the three tiles that carry the awkward cases."""

    def test_real_documents_have_no_cracks(self):
        ter = syn.thanet_landscape()
        if ter is None:
            self.skipTest("landscape not on disk")
        for tile in ("x10_y12", "x13_y3", "x16_y2"):
            doc = syn.thanet_site(tile)
            site = io_json.site_from_dict(doc)
            plan = JunctionPlan(site)
            res = build_all(site, ter, plan=plan)
            rep = junction_audit(plan, res)
            self.assertGreater(rep["patches"], 0, tile)
            self.assertLessEqual(rep["worst_patch_gap_m"], GAP_TOL_M,
                                 "%s: %g m at %s" % (tile, rep["worst_patch_gap_m"], rep["worst_patch_gap_at"]))
            self.assertLessEqual(rep["worst_corner_gap_m"], GAP_TOL_M,
                                 "%s: %g m at %s" % (tile, rep["worst_corner_gap_m"], rep["worst_corner_gap_at"]))

    def test_untrimmed_build_is_still_available(self):
        """conform.py burns the corridor from the UNTRIMMED arms, so ``junctions=False`` must give the
        pre-junction geometry unchanged."""
        ter = syn.thanet_landscape()
        if ter is None:
            self.skipTest("landscape not on disk")
        site = io_json.site_from_dict(syn.thanet_site("x10_y12"))
        res = build_all(site, ter, junctions=False)
        for r in res.values():
            self.assertFalse(r.spline.trimmed)
            self.assertTrue(bool(r.spline.active.all()))
            self.assertEqual(r.junctions, {})


if __name__ == "__main__":
    unittest.main()
