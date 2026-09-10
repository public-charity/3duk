"""Reject stale or incomplete evidence before resuming structure candidates."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diag.structure_inventory import read_osm_way_tags, structure_context, verify_inventory_sources
from diag.structure_workflow import reusable, candidate_conflicts
from phase1_qc import sha256


class StructureWorkflowTests(unittest.TestCase):
    def test_original_tunnel_semantics_remain_distinct(self):
        self.assertEqual(structure_context("tunnel", {"tunnel": "building_passage"}), "building_passage")
        self.assertEqual(structure_context("tunnel", {"tunnel": "covered"}), "covered_passage")
        self.assertEqual(structure_context("tunnel", {"railway": "rail", "service": "siding"}), "rail_siding_cover_review")
        self.assertEqual(structure_context("tunnel", {"location": "underground"}), "underground_tunnel")
        self.assertEqual(structure_context("tunnel", {"tunnel": "yes"}), "tunnel_context_review")

    def test_missing_osm_source_cannot_silently_drop_a_structure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"source.osm"
            path.write_text('<osm><way id="1"><tag k="tunnel" v="building_passage"/></way></osm>')
            self.assertEqual(read_osm_way_tags(path, {"1"})["1"]["tunnel"], "building_passage")
            with self.assertRaisesRegex(ValueError, "absent"):
                read_osm_way_tags(path, {"1", "2"})

    def test_changed_pixel_dependency_invalidates_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"pixels.r16"
            path.write_bytes(b"old")
            inventory = {"source": {"dependency_sha256": {str(path): sha256(path)}}}
            verify_inventory_sources(inventory)
            path.write_bytes(b"new")
            with self.assertRaisesRegex(ValueError, "dependency changed"):
                verify_inventory_sources(inventory)

    def test_resume_checks_actual_candidate_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log, doc, manifest = root/"run.log", root/"site.json", root/"manifest.json"
            log.write_text("finished")
            doc.write_text('{"splines":[{"id":"rail:1:0"}]}')
            manifest.write_text(json.dumps({"production_accepted": False, "candidate_documents": {doc.name: sha256(doc)},
                                           "measured": [{"id": "rail:1:0"}]}))
            job = dict(status="candidate", fingerprint="fresh", log=str(log), log_sha256=sha256(log),
                       manifest=str(manifest), manifest_sha256=sha256(manifest))
            self.assertTrue(reusable(job, "fresh"))
            self.assertFalse(reusable(job, "different"))
            self.assertEqual(candidate_conflicts({"a": job, "b": job}), {"rail:1:0": ["a", "b"]})
            doc.write_text("changed")
            self.assertFalse(reusable(job, "fresh"))


if __name__ == "__main__":
    unittest.main()
