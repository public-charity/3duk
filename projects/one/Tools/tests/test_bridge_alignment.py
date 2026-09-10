"""Prove short links and reversed tile fragments retain a continuous shared profile."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diag.bridge_alignment import chain_samples, split_profile, merge_profile, network_profiles
from diag.bridge_profile_candidate import approach_profile, hermite


def spline(sid, length, z=13, bank=1):
    s = np.linspace(0, length, int(np.ceil(length))+1)
    return SimpleNamespace(id=sid, s=s, length=length, z_ref=np.full(len(s), float(z)),
                           bank_deg=np.full(len(s), float(bank)),
                           sampling=SimpleNamespace(bank_rate_max_deg_per_m=.25))


class ConnectedAlignmentTests(unittest.TestCase):
    def test_reversed_bank_and_arc_roundtrip(self):
        splines = {"a": spline("a", 12, 13, 2), "b": spline("b", 3, 13, -2)}
        chain = [("a", False), ("b", True)]
        sp, offsets = chain_samples(chain, splines.__getitem__)
        np.testing.assert_allclose(sp.bank_deg, 2)
        updates = split_profile(chain, splines.__getitem__, offsets, sp.s, sp.z_ref, sp.bank_deg, sp.length)
        for sid, row in updates.items():
            q, z, bank = merge_profile(splines[sid], [row])
            np.testing.assert_allclose(z, splines[sid].z_ref)
            np.testing.assert_allclose(bank, splines[sid].bank_deg)
            self.assertEqual(q[0], 0)
            self.assertEqual(q[-1], splines[sid].length)

    def test_overlapping_incompatible_profiles_fail(self):
        sp = spline("a", 100)
        a = (np.array([0, 60]), np.array([13, 13]), np.array([0, 0]))
        b = (np.array([40, 100]), np.array([14, 14]), np.array([0, 0]))
        with self.assertRaisesRegex(ValueError, "incompatible overlapping"):
            merge_profile(sp, [a, b])

    def fixture(self):
        segments = {"rail:a:0": (0, 20, True), "rail:link:0": (32, 20, False),
                    "rail:b:0": (32, 52, True), "rail:left:0": (-200, 0, False),
                    "rail:stub:0": (54, 52, False), "rail:right:0": (54, 254, False)}
        definitions, built, groups, fits = {}, {}, {}, {}
        for sid, (a, b, bridge) in segments.items():
            definitions[sid] = ("site.json", {"source": {"layer": "rail"}, "points": [{"x": a, "y": 0}, {"x": b, "y": 0}],
                                               "flags": {"bridge": bridge}})
            built[sid] = spline(sid, abs(b-a), 10 if sid == "rail:link:0" else 13)
            if bridge:
                groups[sid] = {"splines": [sid], "ends": [{"spline_id": sid, "end": e} for e in ("start", "end")]}
                fits[sid] = {"status": "deck_candidate_requires_approaches",
                             "profile_by_spline": [{"spline_id": sid, "s_m": [0, abs(b-a)], "z_m": [13, 13]}]}
        return definitions, built, groups, fits

    def test_paired_bridges_and_reversed_two_metre_stub(self):
        definitions, built, groups, fits = self.fixture()
        decks, profiles, records, selected = network_profiles(["rail:a:0"], groups, fits, definitions,
                                                              built.__getitem__, approach_profile, hermite)
        self.assertEqual(selected, ["rail:a:0", "rail:b:0"])
        self.assertEqual(len(decks), 2)
        self.assertEqual(len(profiles), 4)
        np.testing.assert_allclose(profiles["rail:link:0"][1], 13)
        np.testing.assert_allclose(profiles["rail:link:0"][2], 0)
        np.testing.assert_allclose(profiles["rail:stub:0"][1], 13)
        self.assertEqual(sum(r["method"] == "between_decks" for r in records), 1)
        for sid, (q, z, bank, owners) in profiles.items():
            self.assertEqual(q[-1], built[sid].length)
        right = profiles["rail:right:0"]
        self.assertEqual(right[2][-1], 1)  # remote geometry preserved

    def test_unsupported_neighbouring_deck_is_not_invented(self):
        definitions, built, groups, fits = self.fixture()
        fits["rail:b:0"]["status"] = "needs_deck_review"
        with self.assertRaisesRegex(ValueError, "unsupported deck"):
            network_profiles(["rail:a:0"], groups, fits, definitions, built.__getitem__, approach_profile, hermite)


if __name__ == "__main__":
    unittest.main()
