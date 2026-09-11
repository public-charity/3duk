import copy,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.restore_geometry_selection import pending_documents,apply_retained_trims
from phase1_qc import sha256


class SelectionRecoveryTest(unittest.TestCase):
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
