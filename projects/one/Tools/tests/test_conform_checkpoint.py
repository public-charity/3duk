"""Interrupted terrain stamping must resume to identical raster targets."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conform_checkpoint import ConformCheckpoint
from streetscape.conform import ConformAccumulator, MosaicGrid


class ConformCheckpointTests(unittest.TestCase):
    def stamp(self, acc, height=13, rank=1):
        acc.add(np.array([1, 2, 2]), np.array([2, 3, 3]), np.array([height, height, height-.1]),
                np.array([rank, rank, rank]), np.array([0, .5, .5]))

    def test_resume_preserves_arbitration_and_float_bits(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/"input"
            source.write_bytes(b"source")
            grid = MosaicGrid(nx=1, ny=1, res=9)
            whole = ConformAccumulator(grid)
            self.stamp(whole)
            self.stamp(whole, 15, 0)  # higher but stronger target replaces the lower blend
            self.stamp(whole, 14, 0)
            partial = ConformAccumulator(grid)
            self.stamp(partial)
            cp = ConformCheckpoint(Path(temp)/"state", [source], {"sampling": "triangulated"})
            cp.save(partial, {"n_docs": 1}, [np.array([1.25, -.5], dtype=np.float32)])
            resumed = ConformAccumulator(grid)
            loaded = ConformCheckpoint(Path(temp)/"state", [source], {"sampling": "triangulated"}).load(resumed)
            self.assertEqual(loaded["n_docs"], 1)
            np.testing.assert_array_equal(loaded["earth_all"][0], [1.25, -.5])
            self.stamp(resumed, 15, 0)
            self.stamp(resumed, 14, 0)
            np.testing.assert_array_equal(whole.key, resumed.key)
            np.testing.assert_array_equal(whole.z.view(np.uint32), resumed.z.view(np.uint32))
            self.assertEqual(whole.stats, resumed.stats)

    def test_source_change_refuses_checkpoint_and_uses_new_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/"input"
            source.write_bytes(b"source")
            cp = ConformCheckpoint(Path(temp)/"state", [source], {})
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                cp.save(ConformAccumulator(MosaicGrid(nx=1, ny=1, res=9)), {}, [])
            self.assertNotEqual(cp.fingerprint, ConformCheckpoint(Path(temp)/"state", [source], {}).fingerprint)

    def test_corrupt_arrays_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/"input"
            source.write_bytes(b"source")
            cp = ConformCheckpoint(Path(temp)/"state", [source], {})
            acc = ConformAccumulator(MosaicGrid(nx=1, ny=1, res=9))
            self.stamp(acc)
            cp.save(acc, {}, [])
            cp.previous.write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "altered"):
                cp.load(ConformAccumulator(MosaicGrid(nx=1, ny=1, res=9)))


if __name__ == "__main__":
    unittest.main()
