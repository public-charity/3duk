"""sweep.py / mesh.py: closed and open sections, winding, caps, triangulation, validation, UVs."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json, schema as S  # noqa: E402
from streetscape import spline as SP  # noqa: E402
from streetscape.mesh import MeshBuffer, triangulate_polygon_2d, polygon_area_2d  # noqa: E402
from streetscape.sweep import Section, SectionPoint, sweep, closed_section, open_section  # noqa: E402


def straight():
    doc = syn.load_fixture("straight_100")
    site = io_json.site_from_dict(doc)
    return SP.Spline(site.splines[0], site, syn.terrain_for(doc))


class TestSweep(unittest.TestCase):
    def test_closed_square_is_manifold_with_outward_normals(self):
        sp = straight()
        N = sp.n
        a = 0.25
        sec = closed_section([(-a, 1.0, "m"), (-a, 1.0 + 2 * a, "m"), (a, 1.0 + 2 * a, "m"), (a, 1.0, "m")])
        buf = MeshBuffer()
        res = sweep(buf, sec, sp.frames, side=+1, lateral=0.0, height=0.0, group="box")
        self.assertEqual(len(buf.f), 2 * 4 * (N - 1) + 2 * 2)
        self.assertEqual(res.n_quads, 4 * (N - 1))
        self.assertTrue(buf.is_closed_manifold())
        self.assertEqual(buf.validate(), [])
        fn = buf.face_normals()
        cen = (buf.v[buf.f[:, 0]] + buf.v[buf.f[:, 1]] + buf.v[buf.f[:, 2]]) / 3.0
        centre = np.array([50.0, 0.0, 10.0 + 1.0 + a])          # the box centre: every outward normal points away from it
        self.assertTrue(np.all(np.sum(fn * (cen - centre), axis=1) > 0))
        self.assertTrue(np.allclose(buf.uv[:, 0], buf.vs))

    def test_open_kerb_face_points_toward_the_road(self):
        sp = straight()
        for side in (S.LEFT, S.RIGHT):
            sec = open_section([(-0.02, -0.03, "k"), (0.0, -0.03, "k"), (0.0, 0.125, "k"), (0.125, 0.125, "p"), (1.925, 0.17, "p"), (1.925, -0.3, "p")],
                               smooth=[False, False, False, False, False, False])
            buf = MeshBuffer()
            sweep(buf, sec, sp.frames, side=side, lateral=sp.edge_offset(side), height=sp.edge_height(side),
                  cap_start=True, cap_end=True, group=["kerb", "kerb", "kerb", "pavement", "pavement"])
            self.assertEqual(buf.validate(), [])
            # the face quads (section edge 1: (0,-0.03) -> (0,0.125)) face -side * n (toward the carriageway)
            fn = buf.face_normals()[(buf.grp == buf.group_id("kerb"))]
            nrm = np.linalg.norm(fn, axis=1)
            face = np.abs(fn[:, 1]) > 0.9 * nrm              # the kerb face quads (the caps point along +-x)
            self.assertTrue(face.any())
            self.assertTrue(np.all(fn[face, 1] * (-side) > 0))
            # pavement top faces up, back face outward
            pav = buf.face_normals()[(buf.grp == buf.group_id("pavement"))]
            up = pav[:, 2] > 1e-9
            self.assertTrue(up.any())
            outward = np.abs(pav[:, 1]) > 0.9 * np.linalg.norm(pav, axis=1)
            self.assertTrue(outward.any())
            self.assertTrue(np.all(pav[outward, 1] * side > 0))
            # caps: 2 (one polygon per end), normals along -t_h and +t_h
            # counted through the triangle range beyond the quads
            self.assertGreater(len(buf.f), 2 * 5 * (sp.n - 1))

    def test_caps_at_mask_run_ends(self):
        sp = straight()
        sec = closed_section([(0.0, -0.3, "w"), (0.0, 1.0, "w"), (0.2, 1.0, "w"), (0.2, -0.3, "w")])
        mask = (sp.s <= 30.0) | (sp.s >= 60.0)
        buf = MeshBuffer()
        res = sweep(buf, sec, sp.frames, side=+1, lateral=3.0, height=0.0, mask=mask, group="wall")
        self.assertEqual(len(res.runs), 2)
        self.assertTrue(buf.is_closed_manifold())
        n_quads = res.n_quads
        self.assertEqual(len(buf.f), 2 * n_quads + 4 * 2)
        # every station in the runs is present, none of the gap stations
        st = np.unique(buf.vs)
        self.assertTrue(np.all((st <= 30.0) | (st >= 60.0)))

    def test_quad_mask_separates_dashes(self):
        sp = straight()
        sec = open_section([(-0.05, 0.004, "m"), (0.05, 0.004, "m")], smooth=True)
        qm = (sp.s[:-1] >= 6.0 - 1e-9) & (sp.s[1:] <= 10.0 + 1e-9)
        buf = MeshBuffer()
        res = sweep(buf, sec, sp.frames, side=+1, quad_mask=qm, cap_start=False, cap_end=False, group="d")
        self.assertEqual(len(res.runs), 1)
        self.assertEqual(float(buf.vs.min()), 6.0)
        self.assertEqual(float(buf.vs.max()), 10.0)

    def test_hard_points_duplicate_rows(self):
        sp = straight()
        sec = open_section([(0.0, 0.0, "a"), (1.0, 0.0, "a"), (1.0, 1.0, "a")], smooth=[False, False, False])
        buf = MeshBuffer()
        res = sweep(buf, sec, sp.frames, side=+1, cap_start=False, cap_end=False)
        self.assertEqual(res.vidx.shape[1], 4)        # 3 points + 1 hard interior
        self.assertEqual(len(buf.v), 4 * sp.n)
        sec2 = open_section([(0.0, 0.0, "a"), (1.0, 0.0, "a"), (1.0, 1.0, "a")], smooth=True)
        buf2 = MeshBuffer()
        res2 = sweep(buf2, sec2, sp.frames, side=+1, cap_start=False, cap_end=False)
        self.assertEqual(res2.vidx.shape[1], 3)

    def test_degenerate_quads_skipped(self):
        sp = straight()
        N = sp.n
        O = np.zeros((N, 2))
        O[:, 1] = np.where(sp.s < 50, 0.5, 0.0)          # collapses to a point beyond s = 50
        sec = open_section([(0.0, 0.0, "a"), (0.5, 0.0, "a")], smooth=True)
        buf = MeshBuffer()
        sweep(buf, sec, sp.frames, side=+1, point_o=O, cap_start=False, cap_end=False)
        self.assertEqual(buf.validate(), [])


class TestMesh(unittest.TestCase):
    def test_triangulate_kerb_polygon(self):
        pts = np.array([(-0.02, -0.03), (0.0, -0.03), (0.0, 0.105), (0.0015, 0.1127), (0.0059, 0.1191), (0.0123, 0.1235),
                        (0.02, 0.125), (0.0625, 0.125), (0.125, 0.125), (1.925, 0.17), (1.925, -0.3)])
        tris = triangulate_polygon_2d(pts)
        self.assertEqual(len(tris), 9)
        area = sum(abs(polygon_area_2d(pts[list(t)])) for t in tris)
        self.assertLess(abs(area - abs(polygon_area_2d(pts))), 1e-12)
        # reversed orientation gives the same triangles count and area
        tris2 = triangulate_polygon_2d(pts[::-1])
        self.assertEqual(len(tris2), 9)

    def test_validate_and_manifold(self):
        buf = MeshBuffer()
        v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0.5, 0.5, 1.0]], dtype=float)
        buf.append_vertices(v, np.zeros((5, 2)), np.zeros(5), np.zeros(5), np.zeros(5))
        m = buf.material_id("x")
        g = buf.group_id("g")
        # a pyramid over the square base: closed manifold
        buf.append_triangles([[0, 2, 1], [1, 2, 3], [0, 1, 4], [1, 3, 4], [3, 2, 4], [2, 0, 4]], m, g)
        self.assertTrue(buf.is_closed_manifold())
        self.assertEqual(buf.validate(), [])
        buf.append_triangles([[0, 1, 4]], m, g)        # duplicate
        self.assertTrue(any("duplicate" in x for x in buf.validate()))
        buf2 = MeshBuffer()
        buf2.append_vertices(v[:3], np.zeros((3, 2)), np.zeros(3), np.zeros(3), np.zeros(3))
        buf2.append_triangles([[0, 1, 2]], buf2.material_id("x"), buf2.group_id("g"))
        self.assertFalse(buf2.is_closed_manifold())
        st = buf.stats()
        self.assertEqual(st["verts"], 5)
        self.assertEqual(st["per_material"]["x"]["tris"], 7)

    def test_npz_roundtrip_is_deterministic(self):
        import tempfile
        import shutil
        sp = straight()
        sec = closed_section([(0, 0, "a"), (0, 1, "a"), (1, 1, "b"), (1, 0, "b")])
        buf = MeshBuffer()
        sweep(buf, sec, sp.frames, side=+1, group="box")
        buf.compute_normals()
        d = tempfile.mkdtemp()
        try:
            p1 = os.path.join(d, "a.npz")
            p2 = os.path.join(d, "b.npz")
            buf.save_npz(p1)
            buf.save_npz(p2)
            with open(p1, "rb") as f1, open(p2, "rb") as f2:
                self.assertEqual(f1.read(), f2.read())
            b2 = MeshBuffer.load_npz(p1)
            self.assertTrue(np.array_equal(b2.v, buf.v))
            self.assertEqual(b2.material_names, buf.material_names)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
