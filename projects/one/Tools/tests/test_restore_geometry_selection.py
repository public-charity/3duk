import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.restore_geometry_selection import pending_documents,apply_retained_trims,apply_retained_controls,apply_retained_connectors,apply_retained_bends
from phase1_qc import sha256


class SelectionRecoveryTest(unittest.TestCase):
    def bend_source(self):
        path=Path(__file__).resolve().parents[1]/'blender/tests/fixtures/junction_interior_bend_garrard.json'
        joined=json.loads(path.read_text(encoding='utf-8'));source=copy.deepcopy(joined);source['junctions']=[]
        return source,joined

    def test_bend_recovery_preserves_entire_original_spline_and_timeline(self):
        source,joined=self.bend_source();docs={'doc':source}
        apply_retained_bends(docs,{'doc':joined['junctions']})
        self.assertEqual(docs['doc'],joined)
        self.assertEqual(docs['doc']['splines'],source['splines'])

    def test_invalid_later_bend_does_not_partially_restore_an_earlier_document(self):
        source,joined=self.bend_source();original={'a':source,'b':copy.deepcopy(source)}
        for case in ('station','range','node','duplicate','same_role','kind','trim','overlap'):
            first=copy.deepcopy(joined['junctions'][0]);second=copy.deepcopy(first);second['id']='second'
            if case=='station':second['ends'][0]['station_m']=float('nan')
            elif case=='range':second['ends'][1]['station_m']=10000
            elif case=='node':second['x']+=.01
            elif case=='duplicate':second['id']=first['id']
            elif case=='same_role':second['ends'][0]['end']=second['ends'][1]['end']
            elif case=='kind':second['kind']='connector'
            elif case=='trim':second['trim_radius_m']=2
            selections={'a':[first],'b':[second]}
            if case=='overlap':selections={'a':[first,second]}
            docs=copy.deepcopy(original)
            with self.assertRaises(ValueError,msg=case):apply_retained_bends(docs,selections)
            self.assertEqual(docs,original)

    def connector_source(self):
        path=Path(__file__).resolve().parents[1]/'blender/tests/fixtures/junction_connector_reverse.json'
        joined=json.loads(path.read_text(encoding='utf-8'));source=copy.deepcopy(joined);source['junctions']=[]
        for d in source['splines']:d['junction_start']=None;d['junction_end']=None
        return source,joined

    def test_connector_recovery_preserves_complete_source_payload(self):
        source,joined=self.connector_source();docs={'doc':source}
        apply_retained_connectors(docs,{'doc':joined['junctions']})
        self.assertEqual(docs['doc'],joined)

    def test_connector_recovery_validates_all_documents_before_mutation(self):
        source,joined=self.connector_source();original={'a':source,'b':copy.deepcopy(source)}
        for case in ('trim','node','duplicate','binding','handle'):
            first=copy.deepcopy(joined['junctions'][0]);second=copy.deepcopy(first);second['id']='j1'
            if case=='trim':second['trim_radius_m']=float('nan')
            elif case=='node':second['x']+=.01
            elif case=='duplicate':second['ends'][1]=copy.deepcopy(second['ends'][0])
            elif case=='binding':second['ends'][0]['end']='start'
            else:second['corner_handle_frac']=1.1
            docs=copy.deepcopy(original)
            with self.assertRaises(ValueError,msg=case):apply_retained_connectors(docs,{'a':[first],'b':[second]})
            self.assertEqual(docs,original)

    def test_control_recovery_preserves_endpoints_and_rejects_all_invalid_edits_before_mutation(self):
        d=dict(id='roads:1:0',source=dict(layer='roads'),profile_ids=dict(road='road'),
            points=[dict(x=x,y=0.,width_m=7.) for x in (0.,10.,10.01)],flags={})
        source={'doc':dict(junctions=[],splines=[d,dict(copy.deepcopy(d),id='roads:2:0')])}
        for keep in ([0,1],[0,0,2],[0,1.5,2],[False,2],[0,3,2],[0,-1,2],[],[0,1,2,3]):
            docs=copy.deepcopy(source)
            with self.assertRaises(ValueError):apply_retained_controls(docs,{'roads:1:0':[0,2],'roads:2:0':keep})
            self.assertEqual(docs,source)
        docs=copy.deepcopy(source);apply_retained_controls(docs,{'roads:1:0':[0,2]})
        self.assertEqual(docs['doc']['splines'][0]['points'],[d['points'][0],d['points'][-1]])
        self.assertEqual(docs['doc']['splines'][1],source['doc']['splines'][1])

    def test_interruption_between_document_and_state_write_recovers_completed_document(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=root/'site_x1_y1.json';a.write_text('{"valid":true}')
            expected={a.name:sha256(a)};records={}
            self.assertEqual(pending_documents(root,expected,records),[])
            self.assertEqual(records,{a.name:dict(sha256=expected[a.name])})
            a.write_text('corrupted')
            self.assertEqual(pending_documents(root,expected,records),[a.name])
            self.assertEqual(records,{})

    def test_empty_or_extra_coverage_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for expected,records in (({},{}),({'a.json':'hash'},{'unexpected.json':{}})):
                with self.assertRaisesRegex(ValueError,'coverage'):pending_documents(root,expected,records)

    def test_restoration_rejects_invalid_or_ambiguous_end_selection_before_mutation(self):
        source={'doc':{'junctions':[{'id':'j','ends':[{'spline_id':'s','end':'start','note':'preserve'}]}]}}
        request=dict(spline_id='s',end='start',trim_radius_m=7.5)
        invalid=[dict(request,trim_radius_m=v) for v in (True,0,-1,33,float('nan'),float('inf'))]
        invalid += [dict(request,end='end'),dict(request,note='change')]
        for rows in [[r] for r in invalid]+[[request,request]]:
            docs=copy.deepcopy(source)
            with self.assertRaises(ValueError):apply_retained_trims(docs,{'j':10},{'j':rows})
            self.assertEqual(docs,source)
        docs=copy.deepcopy(source);apply_retained_trims(docs,{'j':10},{'j':[request]})
        self.assertEqual(docs['doc']['junctions'][0],dict(id='j',trim_radius_m=10,
            ends=[dict(spline_id='s',end='start',note='preserve',trim_radius_m=7.5)]))


if __name__=='__main__':unittest.main()
