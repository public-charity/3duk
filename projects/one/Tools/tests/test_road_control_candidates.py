import copy,json,sys,tempfile,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.road_control_candidates import (retained_indices,semantic_reasons,verify_document,
    directed_distance_bound,curve_bound,section_gaps,seam_regressions,load_completed)
from diag.road_surface_census import measure_surface
from phase1_qc import sha256
from streetscape import io_json
from streetscape.spline import JunctionPlan
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/tests'))
import synthetic


class RoadControlCandidatesTest(unittest.TestCase):
    def road(self):
        raw=synthetic.junction_crossroads();raw['junctions']=[];raw['splines']=raw['splines'][:1]
        d=raw['splines'][0];d.pop('junction_start',None);d.pop('junction_end',None)
        d['source']=dict(layer='roads',osm_id='test')
        d['points']=[dict(x=x,y=y,width_m=7.,_z_06=float(i)) for i,(x,y) in enumerate(((0,0),(20,0),(20.01,0),(20.02,0),(20.02,.01)))]
        return raw

    def test_actual_centimetre_corner_fails_then_bounded_pruning_passes(self):
        raw=self.road();terrain=synthetic.junction_terrain_for(raw);site=io_json.site_from_dict(raw);sid=site.splines[0].id
        before=measure_surface(site,sid,terrain,JunctionPlan(site));self.assertEqual(before['status'],'fold_review')
        candidate=copy.deepcopy(raw);d=candidate['splines'][0];keep=retained_indices(d['points'],.025)
        self.assertEqual(keep,[0,4]);d['points']=[d['points'][i] for i in keep]
        verify_document(raw,candidate,{sid:keep});site=io_json.site_from_dict(candidate)
        self.assertEqual(measure_surface(site,sid,terrain,JunctionPlan(site))['status'],'passed')
        self.assertLess(curve_bound(raw['splines'][0]['points'],d['points']),.05)

    def test_semantics_endpoints_and_all_unrelated_data_are_protected(self):
        raw=self.road();d=raw['splines'][0];keep=[0,4]
        self.assertEqual(semantic_reasons(d,keep),[]) # _z_06 is historical, never a height pin.
        self.assertTrue(semantic_reasons(d,[0,1]))
        for key,value in (('width_m',8.),('z',0.),('roll_deg',0.),('tags',['crossing']),('_unknown_note','keep')):
            bad=copy.deepcopy(d);bad['points'][1][key]=value;self.assertTrue(semantic_reasons(bad,keep),key)
        for flag in ('bridge','tunnel','steps','closed_loop'):
            bad=copy.deepcopy(d);bad['flags']={flag:True};self.assertTrue(semantic_reasons(bad,keep))
        self.assertTrue(semantic_reasons(d,keep,[d['id']]))
        candidate=copy.deepcopy(raw);candidate['splines'][0]['points']=copy.deepcopy([d['points'][i] for i in keep])
        candidate['splines'][0]['points'][0]['x']=.001
        with self.assertRaisesRegex(ValueError,'outside selected'):verify_document(raw,candidate,{d['id']:keep})

    def test_distance_bound_covers_segment_interiors_and_disparate_sampling(self):
        a=np.array([[0.,0.],[10.,0.]])
        b=np.array([[0.,.02],[.001,.02],[9.999,.02],[10.,.02]])
        bound=directed_distance_bound(a,b)
        self.assertGreaterEqual(bound,.02);self.assertLessEqual(bound,.02500000001)
        # Endpoints coincide, but the middle is far from the V: vertex-only
        # Hausdorff would report zero in the a->b direction.
        v=np.array([[0.,0.],[5.,5.],[10.,0.]])
        bound=directed_distance_bound(a,v)
        self.assertGreaterEqual(bound,5/np.sqrt(2));self.assertLess(bound,3.542)
        # More than eight segments, including a long nearest segment whose
        # midpoint lies far away: forces the certified KD fallback.
        b=np.array([[-100.,.02],[100.,.02]]+[[100.+i,100.] for i in range(10)])
        self.assertLess(directed_distance_bound(a,b),.026)

    def test_seam_gate_protects_each_actual_section_and_missing_geometry(self):
        before={'road_edge_0':.3,'pavement_0':.2,'kerb_0':.1,'centre':0.}
        after=dict(before,pavement_0=.200002)
        self.assertEqual(seam_regressions(before,after),['pavement_0 gap increased'])
        self.assertTrue(seam_regressions(before,dict(before,kerb_0='section_mismatch')))
        a={'road_edge_0':np.array([[0.,1.,0.]]),'road_edge_1':np.array([[0.,-1.,0.]])}
        b={'road_edge_0':a['road_edge_1'],'road_edge_1':a['road_edge_0']}
        self.assertEqual(section_gaps(a,b),{'road_edge_0':0.,'road_edge_1':0.})

    def test_corrupt_or_missing_checkpoint_cannot_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);report=root/'report.json';report.write_text('{}',encoding='utf-8')
            state=dict(attempts={'id':dict(report='report.json',report_sha256=sha256(report))},documents={})
            load_completed(root,state);report.write_text('{',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'missing/corrupt'):load_completed(root,state)


if __name__=='__main__':unittest.main()
