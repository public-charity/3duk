import copy,json,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.local_connector_candidates import proposed_document,screen_pair,active_end_sections
from streetscape import io_json
from streetscape.spline import Spline


class LocalConnectorCandidateTests(unittest.TestCase):
    def source(self):
        path=Path(__file__).resolve().parents[1]/'blender/tests/fixtures/junction_connector_bend.json'
        raw=json.loads(path.read_text(encoding='utf-8'));j=raw['junctions'][0]
        pair=dict(document=path.name,ids=[e['spline_id'] for e in j['ends']],ends=[0 if e['end']=='start' else 1 for e in j['ends']])
        raw['junctions']=[]
        for d in raw['splines']:d['junction_start']=None;d['junction_end']=None
        return raw,pair

    def test_finished_local_geometry_pass_preserves_complete_source_payload(self):
        raw,pair=self.source();original=copy.deepcopy(raw)
        candidate,report=screen_pair(raw,pair,None)
        self.assertEqual(report['status'],'local_geometry_proposal');self.assertEqual(raw,original)
        restored=copy.deepcopy(candidate);restored['junctions'].pop()
        for d,slot in zip((next(d for d in restored['splines'] if d['id']==sid) for sid in pair['ids']),pair['ends']):
            d['junction_start' if slot==0 else 'junction_end']=None
        self.assertEqual(restored,raw)
        self.assertLessEqual(report['trials'][-1]['local_mesh_seams']['worst_corner_gap_m'],1e-9)
        self.assertTrue(report['trials'][-1]['boundary']['simple'])

    def test_existing_binding_and_nonreciprocal_end_rejected_without_mutation(self):
        for mode in ('binding','continuation'):
            raw,pair=self.source();d=next(d for d in raw['splines'] if d['id']==pair['ids'][0]);slot=pair['ends'][0]
            if mode=='binding':d['junction_start' if slot==0 else 'junction_end']='existing'
            else:d['continues_from' if slot==0 else 'continues_to']='other'
            original=copy.deepcopy(raw)
            with self.assertRaises(ValueError):proposed_document(raw,pair,6.,1.)
            self.assertEqual(raw,original)

    def test_opposite_end_uses_active_trim_plane(self):
        raw,pair=self.source();d=raw['splines'][0]
        d['points']=[dict(d['points'][0],x=0.,y=0.),dict(d['points'][0],x=20.,y=0.)]
        d['continues_from']=None;d['continues_to']=None
        site=io_json.site_from_dict(raw);sp=Spline(site.splines[0],site,None,trim=(2.,3.))
        np.testing.assert_allclose(active_end_sections(sp,0)['centre'][0,:2],[2.,0.],atol=1e-9)
        np.testing.assert_allclose(active_end_sections(sp,1)['centre'][0,:2],[17.,0.],atol=1e-9)


if __name__=='__main__':unittest.main()
