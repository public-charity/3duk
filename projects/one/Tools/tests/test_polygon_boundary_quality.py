import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.polygon_boundary_quality import boundary_quality,cross


class PolygonBoundaryQualityTests(unittest.TestCase):
    def test_star_can_have_zero_fan_excess_but_overlap(self):
        theta=np.arange(5)*2*np.pi/5;ring=np.c_[np.cos(theta),np.sin(theta)][[0,2,4,1,3]]
        signed=cross(ring,np.roll(ring,-1,axis=0))*.5
        self.assertAlmostEqual(abs(signed).sum()-abs(signed.sum()),0.)
        report=boundary_quality(ring)
        self.assertFalse(report['simple']);self.assertEqual(report['proper_crossings'],5)

    def test_simple_concave_and_reversed_registered_ring_pass(self):
        ring=np.array([[0,0],[4,0],[4,4],[2,2],[0,4]],dtype=float)
        for points in (ring,ring[::-1],ring+[12159.44,5368.59]):self.assertTrue(boundary_quality(points)['simple'])

    def test_nonadjacent_touch_and_adjacent_backtracking_fail(self):
        ring=[[0,0],[4,0],[4,4],[2,0],[0,4]]
        self.assertGreater(boundary_quality(ring)['nonadjacent_touches'],0)
        ring=[[0,0],[4,0],[2,0],[2,3],[0,3]]
        self.assertGreater(boundary_quality(ring)['collinear_overlaps'],0)

    def test_consecutive_vertical_edges_collapse_without_hiding_other_repeats(self):
        report=boundary_quality([[0,0],[0,0],[1,0],[1,1],[0,1],[0,0]])
        self.assertTrue(report['simple']);self.assertEqual(report['collapsed_consecutive_xy_vertices'],2)
        self.assertFalse(boundary_quality([[0,0],[1,0],[1,1],[0,0],[0,1]])['simple'])

    def test_invalid_and_zero_area_boundaries_fail(self):
        self.assertFalse(boundary_quality([[0,0],[1,0],[2,0]])['simple'])
        with self.assertRaises(ValueError):boundary_quality([[0,0],[1,0],[0,float('nan')]])


if __name__=='__main__':unittest.main()
