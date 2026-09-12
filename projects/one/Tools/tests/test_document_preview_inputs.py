import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ue'))
from document_preview_inputs import preview_source_path


class DocumentPreviewInputsTests(unittest.TestCase):
    def test_default_source_remains_the_production_document(self):
        self.assertEqual(preview_source_path({},'original.json'),Path('original.json').resolve())

    def test_unhashed_authored_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'included in candidate provenance'):
            preview_source_path({'source_document':'authored.json','input_sha256':{}},'original.json')

    def test_explicit_hashed_source_is_used_without_changing_default_file(self):
        source=Path('authored.json').resolve()
        self.assertEqual(preview_source_path({'source_document':str(source),'input_sha256':{str(source):'verified-by-caller'}},'original.json'),source)


if __name__=='__main__':unittest.main()
