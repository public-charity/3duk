import sys
from pathlib import Path
import unittest
import tempfile
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.corner_quality_audit import pavement_top_stats,pending_documents
from phase1_qc import sha256
from streetscape.mesh import MeshBuffer
from streetscape.spline import corner_frames
from streetscape.sweep import open_section,sweep


class CornerCoverageTest(unittest.TestCase):
    def test_inverted_pavement_stays_in_coverage_and_buried_outer_face_does_not(self):
        m=MeshBuffer();m.v=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,-.3]],dtype=float)
        m.vh=m.v[:,2].copy();m.f=np.array([[0,1,2],[0,2,1],[0,1,3]])
        m.vs=m.v[:,0].copy();m.vd=m.v[:,1].copy()
        m.grp=np.zeros(3,dtype=int);m.group_names=['corner_pavement:j:0']
        r=pavement_top_stats(m)
        self.assertEqual(r['top_triangles'],2)
        self.assertEqual(r['inverted_top_triangles'],1)
        self.assertAlmostEqual(r['inverted_area_m2'],.5)

    def test_winding_correction_cannot_hide_a_folded_pavement_sweep(self):
        theta=np.linspace(0,-np.pi/2,41)
        positions=np.column_stack([np.cos(theta),np.sin(theta),np.zeros(len(theta))])
        tangent=np.column_stack([np.sin(theta),-np.cos(theta),np.zeros(len(theta))])
        frames=corner_frames(positions,tangent,[1,0,0],[0,-1,0])
        for width in (.4,2.):
            with self.subTest(width=width):
                m=MeshBuffer()
                section=open_section([(.1,.15,'paving'),(width,.15,'paving')])
                sweep(m,section,frames,side=-1,cap_start=False,cap_end=False,group='corner_pavement:j:0')
                # Offset 2 m crosses the centre of a 1 m radius circle, but the
                # renderer reorients all emitted triangles to face upward.
                r=pavement_top_stats(m)
                self.assertEqual(r['inverted_top_triangles'],0)
                self.assertEqual(r['folded_top_triangles']>0,width>1.)
                self.assertEqual(r['folded_top_area_m2']>0,width>1.)
                m.f=m.f[:,[0,2,1]]
                reversed_result=pavement_top_stats(m)
                self.assertEqual(reversed_result['folded_top_triangles'],r['folded_top_triangles'])
                self.assertAlmostEqual(reversed_result['folded_top_area_m2'],r['folded_top_area_m2'])

    def test_missing_sweep_attributes_cannot_pass_mapping_quality(self):
        m=MeshBuffer();m.v=np.zeros((3,3));m.vh=np.zeros(3)
        m.f=np.array([[0,1,2]]);m.grp=np.zeros(1,dtype=int);m.group_names=['corner_pavement:j:0']
        with self.assertRaisesRegex(ValueError,'station/offset'):
            pavement_top_stats(m)

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
