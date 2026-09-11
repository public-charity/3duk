import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.connected_width_candidates import width_components


class ConnectedWidthTest(unittest.TestCase):
    def test_whole_continuation_evidence_is_required_without_mutating_sources(self):
        definitions=[dict(id='a',source={'osm_id':'1'},profile_ids={'road':'primary'},junction_start='j0',continues_to='b',
            points=[dict(x=0,y=0,width_m=10.),dict(x=10,y=0,width_m=10.)]),
            dict(id='b',source={'osm_id':'2'},profile_ids={'road':'primary'},continues_from='a',junction_end='j1',
            points=[dict(x=10,y=0,width_m=10.),dict(x=20,y=0,width_m=10.)])]
        tuning=dict(lane_width_m=3.,lane_margin_m=1.,width_quantum_m=.5)
        tags={i:dict(lanes='1',oneway='yes') for i in ('1','2')}
        for case in ('valid','missing_evidence','unequal_width','structure','broken_link','widening'):
            with self.subTest(case=case):
                ds=copy.deepcopy(definitions);evidence=copy.deepcopy(tags)
                if case=='missing_evidence':evidence['2'].pop('lanes')
                if case=='unequal_width':evidence['2']['lanes']='2'
                if case=='structure':ds[1]['flags']={'bridge':True}
                if case=='broken_link':ds[1].pop('continues_from')
                if case=='widening':
                    for p in ds[1]['points']:p['width_m']=3.
                before=copy.deepcopy(ds);result=width_components(ds,evidence,tuning)
                self.assertEqual(ds,before)
                self.assertEqual(len(result),1)
                self.assertEqual(result[0]['ids'],['a','b'])
                self.assertEqual(result[0]['status'],'candidate' if case=='valid' else 'needs_context')


if __name__=='__main__':unittest.main()
