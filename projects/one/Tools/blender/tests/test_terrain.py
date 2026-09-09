"""Heightfield.sample == a literal transcription of step 06's ground() (06_build_networks.py:54-69)."""
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402
from streetscape import noise  # noqa: E402
from streetscape.terrain import Heightfield  # noqa: E402

RES, TILE = 513, 512.0


def field_fn(x, y):
    return 10.0 + 3.0 * np.sin(x / 37.0) + 2.0 * np.cos(y / 23.0) + 0.01 * x


def mosaic_of(hf: Heightfield, nx: int, ny: int) -> np.ndarray:
    """Assemble the tiles into one north-up array with the shared edge rows collapsed (like the VRT)."""
    W = nx * (RES - 1) + 1
    H = ny * (RES - 1) + 1
    M = np.full((H, W), np.nan, dtype=np.float32)
    for (i, j), T in hf.tiles.items():
        r0 = (ny - 1 - j) * (RES - 1)
        c0 = i * (RES - 1)
        M[r0:r0 + RES, c0:c0 + RES] = T
    return M


def ground_transcription(DTM, gt, e, n):
    """Verbatim port of sources/derive/06_build_networks.py ground()."""
    H, W = DTM.shape
    fx = (e - gt[0]) / gt[1] - 0.5
    fy = (n - gt[3]) / gt[5] - 0.5
    if not (0.0 <= fx <= W - 1 and 0.0 <= fy <= H - 1):
        return (0.0, False)
    x0, y0 = int(math.floor(fx)), int(math.floor(fy))
    x0 = min(x0, W - 2)
    y0 = min(y0, H - 2)
    tx, ty = fx - x0, fy - y0
    a = DTM[y0, x0]
    b = DTM[y0, x0 + 1]
    c = DTM[y0 + 1, x0]
    d = DTM[y0 + 1, x0 + 1]
    v = (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
    return (float(v), True) if np.isfinite(v) else (0.0, False)


class TestHeightfield(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hf = Heightfield.from_function(field_fn, (2 * TILE, 2 * TILE))
        cls.hf.tiles[(1, 1)][100:104, 200:203] = np.nan          # a NaN hole
        cls.M = mosaic_of(cls.hf, 2, 2)
        # geotransform of the mosaic in local metres: pixel centres on integers, row 0 = north edge y = 1024
        cls.gt = (-0.5, 1.0, 0.0, 2 * TILE + 0.5, 0.0, -1.0)

    def test_matches_ground_on_hashed_points(self):
        n = 10000
        x = (noise.unit_noise01(np.arange(n), 11) * 1100.0 - 40.0)        # some off coverage
        y = (noise.unit_noise01(np.arange(n) + 50000, 12) * 1100.0 - 40.0)
        got = self.hf.sample(x, y)
        want = np.full(n, np.nan)
        for k in range(n):
            v, ok = ground_transcription(self.M, self.gt, x[k], y[k])
            if ok:
                want[k] = v
        nan_got = ~np.isfinite(got)
        nan_want = ~np.isfinite(want)
        self.assertTrue(np.array_equal(nan_got, nan_want), "NaN pattern differs: %d vs %d" % (nan_got.sum(), nan_want.sum()))
        self.assertGreater(int(nan_want.sum()), 0)
        diff = np.abs(got[~nan_got] - want[~nan_want]).max()
        self.assertLessEqual(diff, 1e-9)

    def test_nan_hole_and_off_coverage(self):
        self.assertTrue(np.isnan(self.hf.sample(712.5, 1024 - 101.5)))        # inside the hole (tile (1,1) row 101)
        self.assertTrue(np.isnan(self.hf.sample(-1.0, 10.0)))
        self.assertTrue(np.isnan(self.hf.sample(10.0, 2 * TILE + 0.5)))
        self.assertFalse(np.isnan(self.hf.sample(10.0, 10.0)))

    def test_tile_boundary_identical_from_either_tile(self):
        # the shared column x = 512 belongs to tile 0 (last column) and tile 1 (first column)
        for y in (3.3, 250.0, 511.9, 512.0, 700.25):
            v = self.hf.sample(512.0, y)
            v_left = self.hf.sample(512.0 - 1e-9, y)
            v_right = self.hf.sample(512.0 + 1e-9, y)
            self.assertAlmostEqual(v, v_left, places=6)
            self.assertAlmostEqual(v, v_right, places=6)

    def test_last_row_col_inward_clamp(self):
        # x exactly at the last column (1024) uses the inward pair (1023, 1024)
        v = self.hf.sample(1024.0, 300.0)
        self.assertTrue(np.isfinite(v))
        self.assertAlmostEqual(v, float(self.M[int(1024 - 300), 1024]), places=5)

    def test_rebased_shift(self):
        hf2 = Heightfield.from_function(field_fn, (TILE, TILE), origin=(1000.0, 2000.0))
        view = hf2.rebased(900.0, 1900.0)      # a document whose origin is 100 m SW of the field's
        self.assertAlmostEqual(view.sample(150.0, 160.0), hf2.sample(50.0, 60.0), places=9)
        self.assertEqual(view.shift_xy, (-100.0, -100.0))

    def test_npz_cache_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "hf.npz")
            self.hf.save_npz(p)
            hf2 = Heightfield.from_npz(p)
            self.assertEqual(sorted(hf2.tiles), sorted(self.hf.tiles))
            for k in self.hf.tiles:
                self.assertTrue(np.array_equal(self.hf.tiles[k], hf2.tiles[k], equal_nan=True))
            x = np.linspace(0, 1000, 500)
            self.assertTrue(np.array_equal(self.hf.sample(x, x[::-1]), hf2.sample(x, x[::-1]), equal_nan=True))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_from_landscape_dir_decodes_r16_and_clip(self):
        d = tempfile.mkdtemp()
        try:
            z = np.round(field_fn(*np.meshgrid(np.arange(RES, dtype=float), TILE - np.arange(RES, dtype=float))) * 128) / 128
            h16 = (np.round(z * 128) + 32768).astype("<u2")
            h16.tofile(os.path.join(d, "hm_x3_y2.r16"))
            clip = np.full((RES, RES), 255, dtype=np.uint8)
            clip[10:20, 30:40] = 0
            clip.tofile(os.path.join(d, "clip_x3_y2.r8"))
            man = {"site": "t", "origin": {"E": 627680, "N": 163080}, "tile_m": 512, "res": 513, "px_m": 1.0,
                   "heightmap": {"z_encoding": {"per_unit": 128, "offset": 32768}},
                   "tiles": [{"x": 3, "y": 2, "files": {"heightmap": "hm_x3_y2.r16", "clip": "clip_x3_y2.r8"}}],
                   "tiles_missing": [], "tiles_clipped": []}
            with open(os.path.join(d, "landscape_manifest.json"), "w", encoding="utf-8") as fh:
                json.dump(man, fh)
            hf = Heightfield.from_landscape_dir(d)
            self.assertEqual(sorted(hf.tiles), [(3, 2)])
            T = hf.tiles[(3, 2)]
            self.assertTrue(np.isnan(T[15, 35]))
            self.assertAlmostEqual(float(T[0, 0]), float(z[0, 0]), places=9)      # bit-identical decode of the quantised value
            self.assertAlmostEqual(hf.sample(3 * TILE + 100.0, 2 * TILE + 512.0 - 200.0), float(z[200, 100]), places=9)
            self.assertEqual(hf.origin_E, 627680.0)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _landscape_dir(self, d, *, write_hm=True, write_clip=True, clip_state="straddle"):
        """A one-tile adapter landscape directory, optionally missing one of its two rasters."""
        z = np.round(field_fn(*np.meshgrid(np.arange(RES, dtype=float), TILE - np.arange(RES, dtype=float))) * 128) / 128
        if write_hm:
            ((np.round(z * 128) + 32768).astype("<u2")).tofile(os.path.join(d, "hm_x3_y2.r16"))
        clip = np.full((RES, RES), 255, dtype=np.uint8)
        clip[10:20, 30:40] = 0
        if write_clip:
            clip.tofile(os.path.join(d, "clip_x3_y2.r8"))
        man = {"site": "t", "origin": {"E": 627680, "N": 163080}, "tile_m": 512, "res": 513, "px_m": 1.0,
               "heightmap": {"z_encoding": {"per_unit": 128, "offset": 32768}},
               "tiles": [{"x": 3, "y": 2, "clip_state": clip_state, "clipped_cells": int((clip == 0).sum()),
                          "files": {"heightmap": "hm_x3_y2.r16", "clip": "clip_x3_y2.r8"}}],
               "tiles_missing": [], "tiles_clipped": []}
        with open(os.path.join(d, "landscape_manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(man, fh)
        return int((clip == 0).sum())

    def test_missing_heightmap_raises(self):
        """A tile the manifest lists whose hm_*.r16 is absent used to be skipped with `continue`."""
        d = tempfile.mkdtemp()
        try:
            self._landscape_dir(d, write_hm=False)
            with self.assertRaises(FileNotFoundError) as cm:
                Heightfield.from_landscape_dir(d)
            self.assertIn("hm_x3_y2.r16", str(cm.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_missing_clip_mask_raises(self):
        """A declared clip raster that is absent used to load as 'no clipping' -- the one way this code
        could silently build road across the Wantsum cut."""
        d = tempfile.mkdtemp()
        try:
            n_clipped = self._landscape_dir(d, write_clip=True)
            self.assertEqual(int(np.isnan(Heightfield.from_landscape_dir(d).tiles[(3, 2)]).sum()), n_clipped)
            os.remove(os.path.join(d, "clip_x3_y2.r8"))
            with self.assertRaises(FileNotFoundError) as cm:
                Heightfield.from_landscape_dir(d)
            self.assertIn("clip_x3_y2.r8", str(cm.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_from_step05_dir_margate_tile(self):
        terrain_dir = os.path.join(os.path.dirname(os.path.dirname(syn.PROJECT_ONE)), "data", "margate", "out", "terrain")
        if not os.path.isfile(os.path.join(terrain_dir, "terrain_manifest.json")):
            self.skipTest("data/margate/out/terrain not on disk")
        try:
            from osgeo import gdal  # noqa: F401
        except Exception:
            self.skipTest("GDAL not importable in this python")
        hf = Heightfield.from_step05_dir(terrain_dir, tiles=[(5, 5)])
        self.assertEqual(sorted(hf.tiles), [(5, 5)])
        self.assertEqual(hf.origin_E, 632800.0)
        T = hf.tiles[(5, 5)]
        self.assertEqual(T.shape, (RES, RES))
        # pixel (row r, col c) sits at local x = 5*512 + c, y = 6*512 - r
        self.assertAlmostEqual(hf.sample(5 * TILE + 100.0, 6 * TILE - 40.0), float(T[40, 100]), places=5)
        # Thanet-frame view: Margate (5, 5) = Thanet (15, 15)
        view = hf.rebased(627680.0, 163080.0)
        self.assertAlmostEqual(view.sample(15 * TILE + 100.0, 16 * TILE - 40.0), float(T[40, 100]), places=5)


if __name__ == "__main__":
    unittest.main()
