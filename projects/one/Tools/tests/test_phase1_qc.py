"""Failure proofs for the QC state contract; stdlib only, no engine/data dependencies."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("phase1_qc", TOOLS / "phase1_qc.py")
qc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qc)


def report():
    return {"config": {"n": 4}, "summary": {"splines": 3, "stations_with_terrain": 100},
            "structures_not_gated_count": 1, "skipped_count": 0, "skipped": [],
            "by_lod": {f"lod{k}": {"stations_with_terrain": 100,
                                   "penetration_m_over_all_stations": {"max": 0.003}}
                       for k in (0, 1, 2, 3)}}


class CoverageGates(unittest.TestCase):
    def test_control(self):
        self.assertEqual(qc.report_problems(report(), 4, [0, 1, 2, 3]), [])

    def test_empty_inventory_fails(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "empty coverage"):
                qc.inventory(d)

    def test_zero_stations_cannot_pass(self):
        value = report()
        value["summary"]["stations_with_terrain"] = 0
        self.assertIn("no measured stations", qc.report_problems(value, 4, [0]))

    def test_unaccounted_spline_fails(self):
        value = report()
        value["summary"]["splines"] -= 1
        self.assertTrue(qc.report_problems(value, 4, [0]))

    def test_missing_lod_and_nan_fail(self):
        for defect in (None, float("nan")):
            value = report()
            value["by_lod"]["lod2"]["penetration_m_over_all_stations"]["max"] = defect
            self.assertTrue(qc.report_problems(value, 4, [0, 2]))

    def test_real_penetration_fails(self):
        value = report()
        value["by_lod"]["lod0"]["penetration_m_over_all_stations"]["max"] = 0.006
        self.assertTrue(qc.report_problems(value, 4, [0]))

    def test_exception_is_not_an_exclusion(self):
        value = report()
        value["summary"]["splines"] -= 1
        value["skipped_count"] = 1
        value["skipped"] = [["site.json", "road:1", "ValueError: broken"]]
        self.assertTrue(qc.report_problems(value, 4, [0]))

    def test_production_cli_rejects_partial_selector(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "site_x0_y0.json").write_text("{}")
            result = subprocess.run([sys.executable, str(TOOLS / "road_fusion_audit.py"),
                                     "--streetscape", d, "--only-doc", "site_x0_y0.json",
                                     "--only-doc", "missing", "--out", str(Path(d, "out.json"))],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("matched no documents: missing", result.stderr)
            self.assertFalse(Path(d, "out.json").exists())

    def test_subset_conform_cannot_replace_full_product(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "site_x0_y0.json").write_text("{}")
            result = subprocess.run([sys.executable, str(TOOLS / "conform_landscape.py"),
                                     "--streetscape", d, "--only-doc", "site_x0_y0.json"], cwd=qc.REPO,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("subset conform requires a separate --out", result.stderr)


class ResumeGates(unittest.TestCase):
    def test_content_change_and_new_file_change_identity(self):
        with tempfile.TemporaryDirectory() as d:
            first, second = Path(d, "a"), Path(d, "b")
            first.write_text("original")
            baseline, _ = qc.content_identity([first], {})
            first.write_text("modified")
            self.assertNotEqual(baseline, qc.content_identity([first], {})[0])
            first.write_text("original")
            second.write_text("additional")
            self.assertNotEqual(baseline, qc.content_identity([first, second], {})[0])
            self.assertNotEqual(qc.content_identity([first, second], {"survey": "a", "landscape": "b"})[0],
                                qc.content_identity([first, second], {"survey": "b", "landscape": "a"})[0])

    def test_measured_fractions_are_weighted_by_length(self):
        with tempfile.TemporaryDirectory() as d:
            jobs = []
            for i, (length, hit) in enumerate(((1, 1), (99, 0))):
                value = report()
                value["by_lod"]["lod0"].update(carriageway_km_total=length,
                                               carriageway_km_penetrated=hit)
                path = Path(d, f"{i}.json")
                qc.atomic_json(path, value)
                jobs.append({"status": "passed", "report": str(path), "report_sha256": qc.sha256(path)})
            self.assertEqual(qc.measurements(jobs, [0])["lod0"]["fraction_length_penetrated"], 0.01)

    def test_resume_requires_intact_report_and_current_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "report.json")
            qc.atomic_json(path, report())
            job = {"status": "passed", "fingerprint": "current", "report": str(path),
                   "report_sha256": qc.sha256(path), "problems": [], "exit_code": 0}
            self.assertTrue(qc.reusable(job, "current", 4, [0]))
            self.assertFalse(qc.reusable(job, "changed", 4, [0]))
            self.assertFalse(qc.reusable(dict(job, status="running"), "current", 4, [0]))
            poisoned = copy.deepcopy(report())
            poisoned["by_lod"]["lod0"]["penetration_m_over_all_stations"]["max"] = 1
            qc.atomic_json(path, poisoned)
            self.assertFalse(qc.reusable(job, "current", 4, [0]))
            path.unlink()
            self.assertFalse(qc.reusable(job, "current", 4, [0]))

    def test_atomic_replacement_preserves_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "state.json")
            qc.atomic_json(path, {"status": "running"})
            qc.atomic_json(path, {"status": "passed"})
            self.assertEqual(qc.read_json(path), {"status": "passed"})
            self.assertEqual(list(Path(d).glob("*.tmp")), [])

    def test_windows_reader_lock_retries_without_truncating_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "state.json")
            qc.atomic_json(path, {"status": "previous"})
            replace = qc.os.replace
            def busy_once(src, dst):
                self.assertEqual(qc.read_json(path), {"status": "previous"})
                qc.os.replace.side_effect = replace
                raise PermissionError("reader has no delete sharing")
            with mock.patch.object(qc.os, "replace", side_effect=busy_once), mock.patch.object(qc.time, "sleep"):
                qc.atomic_json(path, {"status": "next"})
            self.assertEqual(qc.read_json(path), {"status": "next"})


if __name__ == "__main__":
    unittest.main()
