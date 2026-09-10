"""Quality checks must reject canopy/coverage errors before a deck is generated."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "diag"))
from fit_structure_decks import robust_line


class DeckFitTests(unittest.TestCase):
    def test_known_grade_with_vehicle_outliers(self):
        s = np.linspace(0, 100, 101)
        z = 13 + 0.01 * s
        z[40:50] += 2
        fit = robust_line(s, z)
        self.assertTrue(fit["pass"])
        self.assertAlmostEqual(fit["intercept_m"], 13, places=10)
        self.assertAlmostEqual(fit["slope"], 0.01, places=10)

    def test_missing_returns_fail(self):
        fit = robust_line(np.arange(10), [13, 13] + [np.nan] * 8)
        self.assertFalse(fit["pass"])

    def test_contaminated_abutment_fails(self):
        s = np.linspace(0, 100, 101)
        z = np.full(101, 13.0)
        z[:15] += 5
        self.assertFalse(robust_line(s, z)["pass"])

    def test_curved_or_irregular_surface_does_not_become_a_line(self):
        s = np.linspace(0, 100, 101)
        z = 13 + 2 * np.sin(np.pi * s / 100)
        self.assertFalse(robust_line(s, z)["pass"])

    def test_tiny_degenerate_span_fails(self):
        self.assertFalse(robust_line(np.linspace(0, 0.1, 10), np.full(10, 13))["pass"])


if __name__ == "__main__":
    unittest.main()
