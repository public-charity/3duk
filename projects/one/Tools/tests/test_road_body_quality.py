import copy,json,sys,tempfile,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.road_body_quality import mapped_top_stats,compare_document,body_regressions
from streetscape.mesh import MeshBuffer
from streetscape.spline import corner_frames
from streetscape.sweep import open_section,sweep
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/tests'))
import synthetic


class RoadBodyQualityTest(unittest.TestCase):
    def test_interior_mask_add_change_and_removal_cannot_hit_unchanged_cache(self):
        fixture=Path(__file__).resolve().parents[1]/'blender/tests/fixtures/junction_interior_bend_garrard.json'
        bent=json.loads(fixture.read_text(encoding='utf-8'));original=copy.deepcopy(bent);original['junctions']=[]
        terrain=synthetic.junction_terrain_for(bent)
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a.json';b=Path(temp)/'b.json';c=Path(temp)/'c.json'
            a.write_text(json.dumps(original));b.write_text(json.dumps(bent))
            added=compare_document(a,b,terrain)
            self.assertEqual(added['changed_splines'],1)
            self.assertEqual(added['before'],{'fold_review':1})
            self.assertEqual(added['after'],{'passed':1})
            removed=compare_document(b,a,terrain)
            self.assertEqual(removed['changed_splines'],1)
            self.assertEqual(removed['regressions'],1)
            changed=copy.deepcopy(bent);changed['junctions'][0]['ends'][0]['station_m']-=.5
            c.write_text(json.dumps(changed))
            self.assertEqual(compare_document(b,c,terrain)['changed_splines'],1)
            self.assertEqual(compare_document(b,b,terrain)['unchanged_road_splines'],1)

    def test_actual_fold_below_reference_height_survives_winding_correction(self):
        theta=np.linspace(0,-np.pi/2,41)
        pos=np.column_stack([np.cos(theta),np.sin(theta),np.zeros(len(theta))])
        tangent=np.column_stack([np.sin(theta),-np.cos(theta),np.zeros(len(theta))])
        frames=corner_frames(pos,tangent,[1,0,0],[0,-1,0])
        for width in (.4,2.):
            mesh=MeshBuffer()
            section=open_section([(.1,-.05,'paving'),(width,-.05,'paving'),(width,-.3,'paving')])
            sweep(mesh,section,frames,side=-1,cap_start=False,cap_end=False,group='pavement')
            stats=mapped_top_stats(mesh,'pavement')
            self.assertEqual(stats['surface_triangles'],80)
            self.assertEqual(stats['folded_triangles']>0,width>1.)
            mesh.f=mesh.f[:,[0,2,1]]
            self.assertEqual(mapped_top_stats(mesh,'pavement'),stats)

    def test_changed_plan_trims_rebuild_all_affected_actual_road_bodies(self):
        raw=synthetic.junction_crossroads();candidate=copy.deepcopy(raw)
        candidate['junctions'][0]['trim_radius_m']=8.
        terrain=synthetic.junction_terrain_for(raw)
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a.json';b=Path(temp)/'b.json'
            a.write_text(json.dumps(raw));b.write_text(json.dumps(candidate))
            report=compare_document(a,b,terrain)
            self.assertEqual(report['changed_splines'],4)
            self.assertEqual(report['regressions'],0)
            self.assertEqual(report['after'],{'passed':4})
            unchanged=compare_document(a,a,terrain)
            self.assertEqual(unchanged['changed_splines'],0)
            self.assertEqual(unchanged['unchanged_road_splines'],4)
            candidate['splines'].pop();b.write_text(json.dumps(candidate))
            with self.assertRaisesRegex(ValueError,'coverage'):compare_document(a,b,terrain)

    def test_a_small_fold_regression_cannot_hide_in_better_network_totals(self):
        a=dict(status='passed',parts={'road':dict(folded_area_m2=0.)})
        b=dict(status='fold_review',parts={'road':dict(folded_area_m2=.001)})
        self.assertEqual(body_regressions(a,b),['body pass lost','road folded area increased'])

    def test_missing_mapping_coordinates_are_not_a_pass(self):
        mesh=MeshBuffer();mesh.v=np.zeros((3,3))
        with self.assertRaisesRegex(ValueError,'station/offset'):mapped_top_stats(mesh,'road')


if __name__=='__main__':unittest.main()
