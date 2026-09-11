import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.restore_geometry_selection import pending_documents
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


if __name__=='__main__':unittest.main()
