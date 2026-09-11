import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.terrain_edge_contact import grid_crossings,compare_segments,constraint_points


class Field:
    sampling='landscape_triangulated';shift_xy=(0.,0.);xy0=(0.,0.);px_m=1.;origin_E=0.;origin_N=0.
    def __init__(self,fn):self.fn=fn
    def sample(self,x,y):return self.fn(np.asarray(x),np.asarray(y))


class ExactEdgeContactTests(unittest.TestCase):
    def test_diagonal_extremum_between_quarter_metre_samples(self):
        # y=.13 crosses the NW-SE diagonal at x=.87, missed by 25 cm samples.
        edge=np.array([[[.7,.13,1.],[.95,.13,1.]]])
        ground=Field(lambda x,y:abs(x+y-1.))
        stats=compare_segments(edge,ground,ground)
        self.assertAlmostEqual(stats['after_max_gap_m'],1.)
        self.assertLess(max(1-ground.sample(np.array([.7,.95]),.13)),1.)

    def test_grid_crossings_reverse_and_negative_coordinates(self):
        edge=np.array([[-1.2,-.13,2.],[1.1,.43,3.]])
        a=grid_crossings(edge,1.);b=grid_crossings(edge[::-1],1.)
        np.testing.assert_allclose(a,b[::-1],atol=1e-14)
        for p,q in zip(a,b[::-1]):self.assertLess(np.linalg.norm(p-q),1e-13)
        for p,q in zip(a[:-1],a[1:]):
            mid=(p+q)*.5
            for dim in (0,1):self.assertEqual(np.floor((p[dim]+mid[dim])*.5),np.floor((q[dim]+mid[dim])*.5))
            self.assertEqual(np.floor(sum((p[:2]+mid[:2])*.5)),np.floor(sum((q[:2]+mid[:2])*.5)))

    def test_positive_gap_clamp_root_can_be_worst_increase(self):
        edge=np.array([[[.1,.1,0.],[.4,.1,0.]]])
        old=Field(lambda x,y:.25-x)
        # Choose slopes so new-old reaches its maximum exactly where old gap opens.
        new=Field(lambda x,y:-.1-.5*(x-.25))
        stats=compare_segments(edge,old,new)
        self.assertAlmostEqual(stats['max_gap_increase_m'],.1)
        self.assertAlmostEqual(stats['worst_increase_edge_point_m'][0],.25)
        self.assertEqual(stats['exact_breakpoints'],3)

    def test_registration_and_missing_ground_rejected(self):
        edge=[[[0.,0.,0.],[1.,0.,0.]]];a=Field(lambda x,y:x*0);b=Field(lambda x,y:x*np.nan)
        with self.assertRaisesRegex(ValueError,'missing terrain'):compare_segments(edge,a,b)
        b.origin_E=1.
        with self.assertRaisesRegex(ValueError,'registration'):compare_segments(edge,a,b)

    def test_constraints_include_region_and_protected_gap_roots(self):
        edge=np.array([[[.1,.1,0.],[.4,.1,0.]]]);ground=Field(lambda x,y:.25-x)
        points=constraint_points(edge,ground,[.15,0.,.35,.5],gap_roots=(.005,))
        np.testing.assert_allclose(sorted(points[:,0]),[.1,.15,.255,.35,.4])


if __name__=='__main__':unittest.main()
