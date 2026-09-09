"""io_json: every library profile loads, both examples load and round-trip, unknown keys are rejected,
broken documents raise with the path, and the hand-written validator agrees with the JSON-Schema subset
validator of schema_check.py on the examples."""
import copy
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import io_json, schema as S  # noqa: E402
import schema_check  # noqa: E402


class TestIoJson(unittest.TestCase):
    def test_every_profile_loads(self):
        files = sorted(glob.glob(os.path.join(syn.PROFILES_DIR, "*.json")))
        self.assertEqual(len(files), 20)
        kinds = {}
        for f in files:
            kind, pid, prof = io_json.load_profile_file(f)
            kinds[kind] = kinds.get(kind, 0) + 1
            self.assertEqual(pid, os.path.splitext(os.path.basename(f))[0])
            self.assertIsInstance(prof, {"road": S.RoadProfile, "edge": S.EdgeProfile, "hedge": S.HedgeProfile}[kind])
        self.assertEqual(kinds, {"road": 13, "edge": 6, "hedge": 1})
        lib = io_json.load_profile_library(syn.PROFILES_DIR)
        self.assertEqual(lib["road"]["rail_standard"].kind, "rail")
        self.assertAlmostEqual(lib["road"]["rail_standard"].rail.gauge_m, 1.435)

    def test_examples_load_and_roundtrip(self):
        for name in ("test_stretch.json", "synthetic_straight.json"):
            path = os.path.join(syn.EXAMPLES_DIR, name)
            site = io_json.load_site(path)
            d = tempfile.mkdtemp()
            try:
                out = os.path.join(d, name)
                io_json.save_site(site, out)
                site2 = io_json.load_site(out)
                self.assertEqual(io_json.site_to_dict(site), io_json.site_to_dict(site2))
                self.assertEqual(site.to_dict(), site2.to_dict())
                with open(out, "rb") as fh:
                    self.assertNotIn(b"\r\n", fh.read())
            finally:
                shutil.rmtree(d, ignore_errors=True)
            self.assertEqual(io_json.validate_structure(syn.load_json(path)), [])

    def test_unknown_key_rejected(self):
        doc = syn.straight_100()
        doc["splines"][0]["points"][0]["widht_m"] = 6.0
        errs = io_json.validate_structure(doc)
        self.assertTrue(any("unknown key 'widht_m'" in e and "points[0]" in e for e in errs), errs)
        doc = syn.straight_100()
        doc["_note"] = {"anything": 1}
        doc["splines"][0]["_dbg"] = 3
        self.assertEqual(io_json.validate_structure(doc), [])

    def test_broken_documents_name_the_path(self):
        base = syn.straight_100()
        cases = [
            ("frame", lambda d: d.__setitem__("frame", "unreal cm"), "$.frame"),
            ("version", lambda d: d.__setitem__("schema_version", "2.0.0"), "schema_version"),
            ("missing origin N", lambda d: d["origin"].pop("N"), "$.origin"),
            ("points < 2", lambda d: d["splines"][0].__setitem__("points", d["splines"][0]["points"][:1]), "points"),
            ("dashed without dash_m", lambda d: d["profiles"]["road"]["road_test_marked"]["markings"][0].pop("dash_m"), "markings[0]"),
            ("double without gap", lambda d: d["profiles"]["road"]["road_test_marked"]["markings"][1].pop("double_gap_m"), "markings[1]"),
            ("rail without rail block", lambda d: d["profiles"]["road"]["road_test_marked"].__setitem__("kind", "rail"), "road_test_marked"),
            ("overlap below floor", lambda d: d["profiles"]["road"]["road_test_marked"].__setitem__("overlap_m", 0.02), "overlap_m"),
            ("profile id unresolved", lambda d: d["splines"][0]["profile_ids"].__setitem__("edge_left", "edge_x"), "profile_ids.edge_left"),
            ("s1 <= s0", lambda d: d["splines"][0].__setitem__("segments", [{"s0_m": 10.0, "s1_m": 5.0, "side": "both"}]), "segments[0]"),
            ("roll out of range", lambda d: d["splines"][0]["points"][0].__setitem__("roll_deg", 45), "roll_deg"),
            ("bad enum", lambda d: d["profiles"]["road"]["road_test_marked"]["camber"].__setitem__("kind", "crown"), "camber.kind"),
            ("tuck rule", lambda d: d["profiles"]["edge"]["edge_uk_kerb"].__setitem__("tuck_depth_m", 0.01), "tuck_depth_m"),
        ]
        for name, mutate, path_part in cases:
            d = copy.deepcopy(base)
            mutate(d)
            errs = io_json.validate_structure(d)
            self.assertTrue(errs, "%s: no error" % name)
            self.assertTrue(any(path_part in e for e in errs), "%s: %s" % (name, errs))
            with self.assertRaises(S.SchemaError):
                io_json.site_from_dict(d)

    def test_agrees_with_schema_check_on_examples_and_fixtures(self):
        schema = syn.load_json(os.path.join(syn.SCHEMA_DIR, "streetscape.schema.json"))
        V = schema_check.SchemaValidator(schema)
        docs = [syn.load_json(os.path.join(syn.EXAMPLES_DIR, n)) for n in ("test_stretch.json", "synthetic_straight.json")]
        docs += [b() for b in syn.FIXTURE_BUILDERS.values()]
        for doc in docs:
            self.assertEqual(V.validate(doc, schema, "$"), [])
            self.assertEqual(io_json.validate_structure(doc), [])
        # and both reject the same broken document
        d = copy.deepcopy(docs[0])
        d["splines"][0]["segments"][0]["pavement_width_m"] = 1.5
        self.assertTrue(V.validate(d, schema, "$"))
        self.assertTrue(io_json.validate_structure(d))

    def test_warnings(self):
        d = syn.straight_100()
        d["profiles"]["road"]["road_test_marked"]["surface_material"] = "cobbles"
        w = io_json.validate_warnings(d)
        self.assertTrue(any("cobbles" in x for x in w), w)
        self.assertEqual(io_json.validate_structure(d), [])

    def test_warnings_on_an_invalid_document_are_not_silence(self):
        """An empty warning list from a document that cannot even be parsed reads as "clean"; return the
        structural errors instead, prefixed, so a caller checking only warnings cannot be fooled."""
        d = syn.straight_100()
        del d["splines"][0]["points"]
        errs = io_json.validate_structure(d)
        self.assertTrue(errs)
        w = io_json.validate_warnings(d)
        self.assertTrue(w)
        self.assertTrue(all(x.startswith("invalid: ") for x in w), w)
        self.assertEqual([x[len("invalid: "):] for x in w], errs)


if __name__ == "__main__":
    unittest.main()
