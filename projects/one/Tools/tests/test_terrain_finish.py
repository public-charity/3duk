import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender'))
from diag.terrain_finish import minimum_adjustment,apply_adjustments,TerrainFinishInfeasible
from diag.terrain_contact import exact_penetration
from streetscape.terrain import Heightfield
from diag.terrain_finish_candidate import contact_targets,required_contact_coverage
from diag.terrain_edge_contact import constraint_points,compare_segments


class TerrainFinishTest(unittest.TestCase):
    def field(self):
        f=Heightfield.from_function(lambda x,y: np.where(x<8,1.125,.875),extent_m=(16,8),tile_m=8)
        f.sampling='landscape_triangulated'
        return f

    def test_joint_finish_fills_and_cuts_without_surface_penetration(self):
        f=self.field()
        top=np.array([[[6,2,1],[10,2,1],[10,5,1]],[[6,2,1],[10,5,1],[6,5,1]]],dtype=float)
        points=np.array([[x,y,.97] for x in np.arange(6,10.1,.5) for y in (2,5)])
        changes,stats=minimum_adjustment(top,f,(6,2,10,5),points)
        after=apply_adjustments(f,changes)
        self.assertGreater(stats['raised_posts'],0)
        self.assertGreater(stats['lowered_posts'],0)
        self.assertGreaterEqual(exact_penetration(top,after)['minimum_clearance_m'],.01-1e-8)
        self.assertLessEqual(float(np.max(points[:,2]-after.sample(*points[:,:2].T))),.005+1e-8)
        np.testing.assert_array_equal(f.tiles[(0,0)],self.field().tiles[(0,0)])

    def test_incompatible_surface_and_outer_edge_fail(self):
        f=self.field()
        top=np.array([[[6,2,1],[10,2,1],[6,5,1]]],dtype=float)
        with self.assertRaisesRegex(ValueError,'cannot satisfy'):
            minimum_adjustment(top,f,(6,2,10,5),np.array([[7,3,1.2]]))

    def test_shared_post_fill_updates_both_copies_and_rejects_inconsistent_seam(self):
        f=self.field()
        after=apply_adjustments(f,{(8,3):1.})
        self.assertEqual(after.tiles[(0,0)][5,8],1.)
        self.assertEqual(after.tiles[(1,0)][5,0],1.)
        self.assertEqual(f.tiles[(0,0)][5,8],.875)
        f.tiles[(0,0)][5,8]=.8
        with self.assertRaisesRegex(ValueError,'inconsistent seam'):
            apply_adjustments(f,{(8,3):1.})

    def test_failed_contact_reports_irreducible_gap_without_returning_a_candidate(self):
        f=self.field()
        top=np.array([[[6,2,1],[10,2,1],[6,5,1]]],dtype=float)
        with self.assertRaises(TerrainFinishInfeasible) as caught:
            minimum_adjustment(top,f,(6,2,10,5),np.array([[7,3,1.2]]),diagnose_failure=True)
        diagnostic=caught.exception.diagnostic
        self.assertEqual(diagnostic['status'],'complete')
        self.assertGreaterEqual(diagnostic['achievable_max_contact_gap_m'],.21-1e-8)

    def test_new_floating_corner_requires_fill_while_inherited_gap_is_preserved(self):
        f=Heightfield.from_function(lambda x,y: np.zeros_like(x),extent_m=(8,8),tile_m=8)
        f.sampling='landscape_triangulated'
        # This diagonal crosses terrain triangles between integer posts. Checking
        # only mesh vertices would miss constraints when neighbouring posts move.
        segments=np.array([[[2.2,2.1,.25],[5.8,5.7,.25]]])
        points=constraint_points(segments,f,(1,1,7,7),gap_roots=(1/128-.005,))
        top=np.array([[[1,1,.3],[7,1,.3],[7,7,.3]],[[1,1,.3],[7,7,.3],[1,7,.3]]])
        protected=contact_targets(points,f.sample(*points[:,:2].T),1/128,False)
        old_changes,_=minimum_adjustment(top,f,(1,1,7,7),protected,edge_gap_m=1/128)
        old=apply_adjustments(f,old_changes)
        self.assertEqual(old_changes,{})
        self.assertEqual(compare_segments(segments,f,old)['after_max_gap_m'],.25)
        required=contact_targets(points,f.sample(*points[:,:2].T),1/128,True)
        changes,stats=minimum_adjustment(top,f,(1,1,7,7),required,edge_gap_m=1/128)
        after=apply_adjustments(f,changes)
        self.assertGreater(stats['raised_posts'],0)
        self.assertLessEqual(compare_segments(segments,f,after)['after_max_gap_m'],1/128+1e-8)
        self.assertLessEqual(exact_penetration(top,after)['max_penetration_m'],1e-8)

    def test_new_corner_contact_cannot_be_substituted_by_a_same_named_road(self):
        with self.assertRaisesRegex(ValueError,'named junction.*join'):
            required_contact_coverage(['join'],['join'],{'join'},set())
        with self.assertRaisesRegex(ValueError,'named road.*road'):
            required_contact_coverage(['road'],[],set(),{'road'})
        self.assertEqual(required_contact_coverage(['road'],['join'],{'road'},{'join'}),
                         {'roads':['road'],'junctions':['join']})


if __name__=='__main__':unittest.main()
