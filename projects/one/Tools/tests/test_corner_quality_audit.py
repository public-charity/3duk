import sys
from pathlib import Path
import unittest
import tempfile
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.corner_quality_audit import pavement_top_stats,pending_documents
from phase1_qc import sha256
from streetscape.mesh import MeshBuffer


class CornerCoverageTest(unittest.TestCase):
    def test_inverted_pavement_stays_in_coverage_and_buried_outer_face_does_not(self):
        m=MeshBuffer();m.v=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,-.3]],dtype=float)
        m.vh=m.v[:,2].copy();m.f=np.array([[0,1,2],[0,2,1],[0,1,3]])
        m.grp=np.zeros(3,dtype=int);m.group_names=['corner_pavement:j:0']
        r=pavement_top_stats(m)
        self.assertEqual(r['top_triangles'],2)
        self.assertEqual(r['inverted_top_triangles'],1)
        self.assertAlmostEqual(r['inverted_area_m2'],.5)

    def test_corrupted_report_cannot_remain_counted_as_completed_after_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=root/'site_x1_y1.json';b=root/'site_x2_y2.json'
            ar=root/'site_x1_y1.report.json';br=root/'site_x2_y2.report.json'
            ar.write_text('{}');br.write_text('{}')
            records={a.name:dict(report_sha256=sha256(ar)),b.name:dict(report_sha256=sha256(br))}
            br.write_text('{')
            self.assertEqual(pending_documents([a,b],root,records),[b])
            self.assertEqual(set(records),{a.name})


if __name__=='__main__':unittest.main()
