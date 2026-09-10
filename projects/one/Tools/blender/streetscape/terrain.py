"""Tiled north-up heightfield sampled with the step-06 ``ground()`` rule (DESIGN.md 8, geometry.md 5.3).

Pixel centres sit on integer metres: tile (i, j) covers local x in [i*tile_m, (i+1)*tile_m],
y in [j*tile_m, (j+1)*tile_m]; row 0 is the NORTH edge, column 0 the WEST edge; adjacent tiles share
their edge row/column (513 samples per 512 m).  ``sample`` is bilinear between pixel centres with the
inward clamp at the last row/column and NaN where any of the four samples is NaN or the point is off
coverage -- a literal transcription of ``sources/derive/06_build_networks.py:54-69`` per tile.

Sources:
  Heightfield.from_landscape_dir(path)   adapter product: landscape_manifest.json + hm_*.r16 + clip_*.r8
                                         (z = (h16 - 32768) / 128, NaN where clip == 0).  An inconsistent
                                         directory raises: a tile the manifest lists whose heightmap is
                                         absent, and a tile that declares a clip mask whose raster is
                                         absent, are both errors -- the clip raster is what makes a
                                         clipped cell a deliberate absence (BRIEF 4.1), so defaulting it
                                         to "no clipping" would build road across the Wantsum cut.
  Heightfield.from_step05_dir(path)      GDAL convenience (env python): terrain/dtm_x*_y*.tif of step 05
  Heightfield.from_function(fn, ...)     synthetic fields for the tests

Frames: a heightfield carries the survey origin (E, N) of its tile (0, 0) corner.  A document authored in
another origin is sampled through ``rebased(E_doc, N_doc)``: the Thanet-frame test stretch on Margate's
step-05 tiles is the +5120 m shift (Margate origin 632800/168200 -> Thanet 627680/163080).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np


def _interp(a, b, c, d, tx, ty, rule: str):
    """One quad, two rules (docs/TERRAIN_ROADS.md 3.3).

    ``a`` is the NW sample, ``b`` NE, ``c`` SW, ``d`` SE; ``tx`` grows east and ``ty`` south, which is
    the landscape's own +Y.  ``bilinear`` is the numpy/plugin contract (DESIGN.md 8) and the default;
    ``landscape_triangulated`` is what ALandscape's Chaos heightfield returns between the posts, so a
    measurement made with it is a measurement of the surface the pawn walks on and the camera sees.
    Bit-for-bit the same expression as FStreetHeightfield::Sample
    (Plugins/Streetscape/Source/Streetscape/Private/StreetTerrainSource.cpp:169-173).

    THE DIAGONAL, DETERMINED RATHER THAN ASSUMED.  Both branches share ``a`` and ``d``, so the quad
    is split on the **NW-SE diagonal**: ``tx < ty`` is the south-west triangle (a, c, d) and
    ``tx >= ty`` the north-east one (a, b, d).  A quad can be split either way and the two choices
    differ by the full ``|twist|/4`` at the quad centre -- up to 6.12 m at the Thanet maximum -- so
    getting it backwards would be worse than using bilinear.  It was settled by measurement against
    the running engine, not by reading a header: predicting ``z_heightfield - z_landscape`` at 6,958
    probe points with nothing but this expression minus the bilinear one leaves a residual of
    **0.000587 m maximum, 0.0000983 m rms, over the 6,866 points further than 1 m from a tile
    boundary** (docs/TERRAIN_ROADS.md 3.4, ``Saved/Diag/d2_interp_vs_engine.json``; the 92 excluded
    points are the D1 seam, where the numpy field holds two copies of a shared row and the landscape
    one).  Flipping the comparison to ``tx > 1 - ty`` would have to leave a residual of the same size
    as the term itself, and does not.  The engine side of that comparison is
    ``ALandscapeProxy::GetHeightAtLocation`` -> ``FHeightField::GetHeightAt``
    (Chaos/Private/Chaos/HeightField.cpp:937-969)."""
    if rule == "landscape_triangulated":
        return np.where(tx < ty, a * (1.0 - ty) + d * tx + c * (ty - tx),
                        a * (1.0 - tx) + b * (tx - ty) + d * ty)
    if rule != "bilinear":
        raise ValueError("unknown sampling rule %r" % rule)
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty


@dataclass
class Heightfield:
    tile_m: float
    res: int
    px_m: float
    tiles: dict = field(default_factory=dict)       # (i, j) -> (res, res) float32, row 0 = north
    origin_E: float = 0.0                           # survey E of the local x = 0 line of THIS heightfield
    origin_N: float = 0.0
    shift_xy: tuple = (0.0, 0.0)                    # added to query (x, y) before lookup (document -> heightfield frame)
    xy0: tuple = (0.0, 0.0)                         # heightfield-frame coordinates of tile (0, 0)'s SW corner
    source: str = ""                                # human-readable provenance for stats.json
    manifest: dict = field(default_factory=dict)
    sampling: str = "bilinear"                      # "bilinear" | "landscape_triangulated" (see sample())

    # -- construction --------------------------------------------------------------------------
    @classmethod
    def from_function(cls, fn, extent_m=(512.0, 512.0), px_m: float = 1.0, tile_m: float = 512.0,
                      origin=(0.0, 0.0), xy0=(0.0, 0.0)) -> "Heightfield":
        """Synthetic field: fn(x, y) vectorised over arrays of local metres.  Tiles cover
        [xy0, xy0 + extent) of the local frame (xy0 defaults to the origin)."""
        res = int(round(tile_m / px_m)) + 1
        nx = int(np.ceil(extent_m[0] / tile_m))
        ny = int(np.ceil(extent_m[1] / tile_m))
        hf = cls(tile_m=float(tile_m), res=res, px_m=float(px_m), origin_E=float(origin[0]),
                 origin_N=float(origin[1]), source="from_function", xy0=(float(xy0[0]), float(xy0[1])))
        c = np.arange(res, dtype=np.float64) * px_m
        for i in range(nx):
            for j in range(ny):
                xs = xy0[0] + i * tile_m + c
                ys = xy0[1] + (j + 1) * tile_m - c            # row 0 = north
                X, Y = np.meshgrid(xs, ys)
                hf.tiles[(i, j)] = np.asarray(fn(X, Y), dtype=np.float64).astype(np.float32)
        return hf

    @classmethod
    def from_landscape_dir(cls, path: str) -> "Heightfield":
        """Adapter product (PIPELINE_CHANGES.md 13.3): hm_x{i}_y{j}.r16 + clip_x{i}_y{j}.r8."""
        mpath = os.path.join(path, "landscape_manifest.json")
        with open(mpath, "r", encoding="utf-8") as fh:
            man = json.load(fh)
        res = int(man["res"])
        tile_m = float(man["tile_m"])
        px_m = float(man.get("px_m", tile_m / (res - 1)))
        enc = man.get("heightmap", {}).get("z_encoding", {})
        per_unit = float(enc.get("per_unit", 128))
        offset = float(enc.get("offset", 32768))
        hf = cls(tile_m=tile_m, res=res, px_m=px_m, origin_E=float(man["origin"]["E"]),
                 origin_N=float(man["origin"]["N"]), source="landscape:" + os.path.abspath(path), manifest=man)
        missing = set(tuple(t) for t in man.get("tiles_missing", []))
        clipped_whole = set(tuple(t) for t in man.get("tiles_clipped", []))
        for t in man.get("tiles", []):
            key = (int(t["x"]), int(t["y"]))
            if key in missing or key in clipped_whole:
                continue
            files = t.get("files", {})
            hm_name = files.get("heightmap") or "hm_x%d_y%d.r16" % key
            clip_name = files.get("clip") or "clip_x%d_y%d.r8" % key
            hm_path = os.path.join(path, hm_name)
            if not os.path.isfile(hm_path):
                # A tile the manifest lists but whose heightmap is absent is an inconsistent directory,
                # not "no terrain here": silently skipping it turns real ground into a NaN hole and the
                # splines over it get filled heights with only a generic warning.
                raise FileNotFoundError(
                    "%s: landscape_manifest.json lists tile (%d, %d) but its heightmap %s is missing"
                    % (path, key[0], key[1], hm_name))
            h16 = np.fromfile(hm_path, dtype="<u2")
            if h16.size != res * res:
                raise ValueError("%s: %d values, expected %d" % (hm_path, h16.size, res * res))
            z = (h16.astype(np.float64) - offset) / per_unit
            z = z.reshape(res, res)
            cpath = os.path.join(path, clip_name)
            if os.path.isfile(cpath):
                clip = np.fromfile(cpath, dtype=np.uint8).reshape(res, res)
                z[clip == 0] = np.nan
            elif files.get("clip") is not None or str(t.get("clip_state", "")) == "straddle" or int(t.get("clipped_cells", 0) or 0) > 0:
                # The clip raster is what makes a clipped cell a DELIBERATE ABSENCE (BRIEF 4.1 crop
                # semantics).  Loading a straddle tile without it turns the Wantsum cut into ordinary
                # ground and roads/kerbs would be built across water.  Refuse rather than default.
                raise FileNotFoundError(
                    "%s: tile (%d, %d) declares clip mask %s (clip_state=%r, clipped_cells=%s) but the file is missing"
                    % (path, key[0], key[1], clip_name, t.get("clip_state"), t.get("clipped_cells")))
            hf.tiles[key] = z.astype(np.float32)
        return hf

    @classmethod
    def from_step05_dir(cls, path: str, tiles=None) -> "Heightfield":
        """Convenience for the env python: reads terrain_manifest.json + dtm_x*_y*.tif with GDAL.

        ``tiles``: optional iterable of (i, j) to restrict the read (the whole site is 92+ tiles)."""
        from osgeo import gdal  # noqa: local import: only the env python has GDAL
        gdal.UseExceptions()
        mpath = os.path.join(path, "terrain_manifest.json")
        with open(mpath, "r", encoding="utf-8") as fh:
            man = json.load(fh)
        res = int(man["res"])
        tile_m = float(man["tile_m"])
        px_m = tile_m / (res - 1)
        hf = cls(tile_m=tile_m, res=res, px_m=px_m, origin_E=float(man["origin"]["E"]),
                 origin_N=float(man["origin"]["N"]), source="step05:" + os.path.abspath(path), manifest=man)
        want = None if tiles is None else set(tuple(t) for t in tiles)
        for t in man["tiles"]:
            key = (int(t["x"]), int(t["y"]))
            if want is not None and key not in want:
                continue
            fpath = os.path.join(path, t["file"])
            ds = gdal.Open(fpath)
            band = ds.GetRasterBand(1)
            a = band.ReadAsArray().astype(np.float32)
            if a.shape != (res, res):
                raise ValueError("%s: shape %s, expected (%d, %d)" % (fpath, a.shape, res, res))
            nd = band.GetNoDataValue()
            if nd is not None:
                a[np.isclose(a, nd) | (a <= -1e30)] = np.nan
            gt = ds.GetGeoTransform()
            # sanity: pixel centres on integer metres at the expected corner (DESIGN.md 8)
            exp_x = hf.origin_E + key[0] * tile_m - 0.5 * px_m
            exp_y = hf.origin_N + (key[1] + 1) * tile_m + 0.5 * px_m
            if abs(gt[0] - exp_x) > 1e-6 or abs(gt[3] - exp_y) > 1e-6:
                raise ValueError("%s: geotransform origin (%r, %r) != expected (%r, %r)" % (fpath, gt[0], gt[3], exp_x, exp_y))
            hf.tiles[key] = a
            ds = None
        return hf

    # -- cache (Blender's python has no GDAL: the env python exports, Blender loads) ------------
    def save_npz(self, path: str) -> None:
        from .mesh import save_npz_dict
        keys = sorted(self.tiles)
        arrays = {"meta": np.array([self.tile_m, self.res, self.px_m, self.origin_E, self.origin_N, self.xy0[0], self.xy0[1]], dtype=np.float64),
                  "keys": np.array(keys, dtype=np.int64).reshape(-1, 2),
                  "source": np.array([self.source], dtype="U256")}
        for k in keys:
            arrays["t_%d_%d" % k] = self.tiles[k]
        save_npz_dict(path, arrays)

    @classmethod
    def from_npz(cls, path: str) -> "Heightfield":
        d = np.load(path, allow_pickle=False)
        m = d["meta"]
        hf = cls(tile_m=float(m[0]), res=int(m[1]), px_m=float(m[2]), origin_E=float(m[3]), origin_N=float(m[4]),
                 xy0=(float(m[5]), float(m[6])), source=str(d["source"][0]) + " (npz cache)")
        for k in d["keys"]:
            key = (int(k[0]), int(k[1]))
            hf.tiles[key] = d["t_%d_%d" % key]
        return hf

    # -- the coarser surfaces the landscape can DRAW ---------------------------------------------
    def lod_skeleton(self, k: int) -> "Heightfield":
        """A 2^k decimation of this field, anchored on the tile grid, dropped posts replaced by the
        straight line between the kept ones.

        **THIS IS NOT THE LANDSCAPE'S LOD MESH.**  It was written on 2026-09-09 in the belief that it
        was, and every LOD figure taken with it (0.03 % at LOD 1, 1.9 % at LOD 2, 8.6 % at LOD 3) is
        an underestimate -- the same corridors measured against the engine's real rule give 0.76 %,
        8.18 % and 22.26 %.  Two things are wrong with it and both matter:

        * the engine's stride is ``SubsectionSizeQuads / ((SubsectionSizeVerts >> k) - 1)``, which is
          127/63, 127/31, 127/15 = **2.016, 4.097, 8.467 m**, not 2, 4, 8;
        * the anchor is the **subsection lattice** -- every 127th landscape vertex, offset by the
          importer's north padding -- which shares no alignment with the 512 m tile grid.

        Use ``LandscapeLodSurface``, which is a transcription of
        ``ULandscapeComponent::GenerateHeightmapMips`` and ``LandscapeVertexFactory.ush``.  Nothing
        in the conform, the audit or the reports calls this any more; it survives only because
        ``tests/test_conform.py`` still pins its behaviour, and that test belongs to the geometry
        track to retire."""
        import copy as _copy
        k = int(k)
        if k <= 0:
            return self
        s = 1 << k
        r1 = self.res - 1
        idx = np.arange(self.res)
        lo = np.minimum((idx // s) * s, r1)
        hi = np.minimum(lo + s, r1)
        t = (idx - lo) / np.where(hi > lo, hi - lo, 1)
        out = _copy.copy(self)
        out.tiles = {}
        for key, T in self.tiles.items():
            A = T.astype(np.float64)
            B = A[lo, :] * (1.0 - t)[:, None] + A[hi, :] * t[:, None]
            out.tiles[key] = (B[:, lo] * (1.0 - t)[None, :] + B[:, hi] * t[None, :]).astype(np.float32)
        out.source = (self.source or "") + " +lod%d(NOT the engine rule)" % k
        return out

    def lod_surface(self, k: int, path: str = None):
        """The surface the landscape DRAWS at level of detail ``k`` -- see ``LandscapeLodSurface``."""
        return LandscapeLodSurface.from_landscape_dir(path or self.source.split("landscape:", 1)[-1],
                                                     k, sampling=self.sampling)

    # -- frames --------------------------------------------------------------------------------
    def rebased(self, doc_E: float, doc_N: float) -> "Heightfield":
        """View of this heightfield for a document whose origin is (doc_E, doc_N): x_hf = x_doc + (doc_E - E_hf)."""
        return Heightfield(tile_m=self.tile_m, res=self.res, px_m=self.px_m, tiles=self.tiles,
                           origin_E=self.origin_E, origin_N=self.origin_N,
                           shift_xy=(float(doc_E) - self.origin_E, float(doc_N) - self.origin_N),
                           xy0=self.xy0, source=self.source, manifest=self.manifest,
                           sampling=self.sampling)

    # -- sampling ------------------------------------------------------------------------------
    def sample(self, x, y) -> np.ndarray:
        """Bilinear sample at local metres (x, y) of the document frame; NaN off coverage / on nodata."""
        x = np.asarray(x, dtype=np.float64) + (self.shift_xy[0] - self.xy0[0])
        y = np.asarray(y, dtype=np.float64) + (self.shift_xy[1] - self.xy0[1])
        scalar = x.ndim == 0
        x = np.atleast_1d(x)
        y = np.atleast_1d(y)
        out = np.full(x.shape, np.nan, dtype=np.float64)
        finite = np.isfinite(x) & np.isfinite(y)
        if not finite.any():
            return float(out[0]) if scalar else out
        ti = np.full(x.shape, -1, dtype=np.int64)
        tj = np.full(x.shape, -1, dtype=np.int64)
        ti[finite] = np.floor(x[finite] / self.tile_m).astype(np.int64)
        tj[finite] = np.floor(y[finite] / self.tile_m).astype(np.int64)
        keys = np.stack([ti, tj], axis=-1).reshape(-1, 2)
        uniq, inv = np.unique(keys, axis=0, return_inverse=True)
        inv = inv.reshape(x.shape)
        r1 = self.res - 1
        for u_idx in range(len(uniq)):
            key = (int(uniq[u_idx, 0]), int(uniq[u_idx, 1]))
            sel = (inv == u_idx) & finite
            if not sel.any():
                continue
            T = self.tiles.get(key)
            if T is None:
                continue
            cx = (x[sel] - key[0] * self.tile_m) / self.px_m
            ry = ((key[1] + 1) * self.tile_m - y[sel]) / self.px_m
            # inside [0, res-1] by construction of the tile index; guard rounding at the far edge
            cx = np.clip(cx, 0.0, float(r1))
            ry = np.clip(ry, 0.0, float(r1))
            x0 = np.minimum(np.floor(cx).astype(np.int64), r1 - 1)
            y0 = np.minimum(np.floor(ry).astype(np.int64), r1 - 1)
            tx = cx - x0
            ty = ry - y0
            a = T[y0, x0].astype(np.float64)
            b = T[y0, x0 + 1].astype(np.float64)
            c = T[y0 + 1, x0].astype(np.float64)
            d = T[y0 + 1, x0 + 1].astype(np.float64)
            out[sel] = _interp(a, b, c, d, tx, ty, self.sampling)
        # ground() treats the mosaic as [0, W-1] x [0, H-1] INCLUSIVE: a point exactly on the far edge of the
        # coverage belongs to the last tile (its last column / top row) when the next tile does not exist
        miss = finite & ~np.isfinite(out)
        if miss.any():
            on_x = miss & (np.abs(x - ti * self.tile_m) < 1e-9)
            on_y = miss & (np.abs(y - tj * self.tile_m) < 1e-9)
            for sel_x, sel_y in ((on_x, np.zeros_like(on_x)), (np.zeros_like(on_y), on_y), (on_x & on_y, on_x & on_y)):
                sel = sel_x | sel_y
                if not sel.any():
                    continue
                for idx in np.where(sel)[0]:
                    key = (int(ti[idx]) - (1 if sel_x[idx] else 0), int(tj[idx]) - (1 if sel_y[idx] else 0))
                    T = self.tiles.get(key)
                    if T is None:
                        continue
                    cx = (x[idx] - key[0] * self.tile_m) / self.px_m
                    ry = ((key[1] + 1) * self.tile_m - y[idx]) / self.px_m
                    if not (-1e-9 <= cx <= r1 + 1e-9 and -1e-9 <= ry <= r1 + 1e-9):
                        continue
                    cx = float(np.clip(cx, 0.0, r1))
                    ry = float(np.clip(ry, 0.0, r1))
                    x0 = min(int(np.floor(cx)), r1 - 1)
                    y0 = min(int(np.floor(ry)), r1 - 1)
                    tx, ty = cx - x0, ry - y0
                    a, b, c, d = (float(T[y0, x0]), float(T[y0, x0 + 1]), float(T[y0 + 1, x0]), float(T[y0 + 1, x0 + 1]))
                    out[idx] = float(_interp(np.float64(a), np.float64(b), np.float64(c), np.float64(d),
                                             np.float64(tx), np.float64(ty), self.sampling))
        out[~np.isfinite(out)] = np.nan
        return float(out[0]) if scalar else out

    def bounds(self):
        """Local-frame (document) bounds of the tiled coverage as (x0, y0, x1, y1)."""
        if not self.tiles:
            return None
        ii = [k[0] for k in self.tiles]
        jj = [k[1] for k in self.tiles]
        sx, sy = self.shift_xy[0] - self.xy0[0], self.shift_xy[1] - self.xy0[1]
        return (min(ii) * self.tile_m - sx, min(jj) * self.tile_m - sy,
                (max(ii) + 1) * self.tile_m - sx, (max(jj) + 1) * self.tile_m - sy)

    def describe(self) -> dict:
        return {"source": self.source, "tile_m": self.tile_m, "res": self.res, "px_m": self.px_m,
                "n_tiles": len(self.tiles), "origin": {"E": self.origin_E, "N": self.origin_N},
                "shift_xy": [float(self.shift_xy[0]), float(self.shift_xy[1])], "xy0": [float(self.xy0[0]), float(self.xy0[1])]}


# ---------------------------------------------------------------------------------------------
# The surface the landscape DRAWS, which is not the surface its height query returns
# ---------------------------------------------------------------------------------------------
class LandscapeLodSurface:
    """The mesh an ``ALandscape`` rasterises at integer level of detail ``k``.

    ``Heightfield.sample`` answers what ``ALandscapeProxy::GetHeightAtLocation`` answers: the LOD-0
    triangulation, which is also what the pawn collides with.  It is NOT what the camera sees.  Past
    a distance set by ``LOD0ScreenSize`` the renderer draws a coarser mesh, and the corridor a
    conform sank 3 cm at the 1 m posts can be drawn straight over by a triangle that never saw them.

    THE RULE, TRANSCRIBED RATHER THAN GUESSED.  Two pieces of shipped engine source, read at
    UE 5.8.2 on this machine:

    * ``Runtime/Landscape/Private/LandscapeEdit.cpp:2272``
      ``ULandscapeComponent::GenerateHeightmapMips`` builds mip ``m`` of the component's heightmap
      texture from mip ``m-1``.  It is NOT a box filter.  Each subsection of
      ``SubsectionSizeQuads`` quads is resampled onto
      ``MipSubsectionSizeQuads = ((SubsectionSizeQuads + 1) >> m) - 1`` quads, and the value at mip
      vertex ``i`` is read from the previous mip at the FRACTIONAL position
      ``PrevMipSubsectionSizeQuads * i / MipSubsectionSizeQuads`` by bilinear interpolation
      (``FMath::Lerp`` of the four neighbours), then re-quantised to uint16.
    * ``Engine/Shaders/Private/LandscapeVertexFactory.ush:660-680`` places the vertex at
      ``ActualLODCoordsInt / CoordTranslate.x`` -- the same evenly spread subsection positions -- and
      reads its height from ``Texture2DSampleLevel(HeightmapTexture, ..., LodValue - LodBias)``, i.e.
      exactly that mip texel.  Between two integer LODs it lerps position AND height towards the
      next LOD (``MorphAlpha``), so an integer-LOD surface is the extreme of a continuum, not a step.

    Two consequences that the previous model got wrong, and that decide where a road survives:

    1. **The stride is not 2^k.**  With this site's ``SubsectionSizeQuads = 127`` it is
       ``127 / ((128 >> k) - 1)`` = **2.0159 m at LOD 1, 4.0968 m at LOD 2, 8.4667 m at LOD 3**.
    2. **The anchor is the subsection grid, every 127 landscape vertices**, not the 512 m tile grid
       and not the world origin.  Subsection edges keep their LOD-0 height EXACTLY at every mip (the
       resample lands on them with zero fraction), which is what keeps neighbouring components crack
       free -- and it means the error is zero on a lattice of lines 127 m apart and largest between.

    So the drawn surface at LOD k is: per subsection, an ``(M_k+1)^2`` lattice of vertices at those
    strides, each carrying the chained bilinear resample of the LOD-0 heights, triangulated with the
    landscape's own NW-SE diagonal (the same ``_interp`` rule as LOD 0, in subsection index space).

    NOT modelled, and each one bounded: the uint16 re-quantisation at every mip (half-quantum
    0.0039 m per level, unbiased, <= 0.0117 m at LOD 3); ``MorphAlpha`` (between levels, and bounded
    by the two levels it interpolates); ``LodBias`` from heightmap texture streaming (0 with the
    texture resident, which is what a commandlet capture has).

    WHERE EACH LOD IS DRAWN.  ``FLandscapeComponentSceneProxy::ComputeLODForView``
    (``LandscapeRender.cpp:4508``) takes ``ComputeBoundsScreenRadiusSquared`` of the COMPONENT bounds
    -- 254 m square here, sphere radius about 180 m -- and compares it against the ratios built at
    ``LandscapeRender.cpp:1549-1567``: ``LOD0ScreenSize``, divided by ``LOD0DistributionSetting``
    once and by ``LODDistributionSetting`` per level after that.  With this level's saved values
    (0.5, 1.25, 3.0) and the render set's 80 deg / 16:9 camera that is LOD 0 inside about 380 m,
    LOD 1 by 480 m, LOD 2 by 1.4 km and LOD 3 only past 4.3 km.  ``distances_m`` computes it.
    """

    def __init__(self, mosaic, k, subsection_quads=127, y_top_m=0.0, px_m=1.0,
                 sampling="landscape_triangulated", source="", meta=None):
        self.meta = dict(meta or {})
        self.k = int(k)
        self.sq = int(subsection_quads)
        self.y_top_m = float(y_top_m)
        self.px_m = float(px_m)
        self.sampling = sampling
        self.source = source
        self.shift_xy = (0.0, 0.0)
        self.mk = ((self.sq + 1) >> self.k) - 1
        if self.mk < 1:
            raise ValueError("LOD %d leaves %d quads per subsection" % (self.k, self.mk))
        self.stride_m = self.px_m * self.sq / float(self.mk)
        self.weights = self.resample_weights(self.sq, self.k)
        self.grid = self._build(mosaic)

    # -- the engine's own resample chain, as a matrix ------------------------------------------
    @staticmethod
    def resample_weights(subsection_quads: int, k: int) -> np.ndarray:
        """``(M_k+1, subsection_quads+1)``: row ``i`` is how mip-k vertex ``i`` of a subsection is
        made out of that subsection's LOD-0 vertices.

        One level of ``GenerateHeightmapMips`` per step, composed: the value at mip ``m`` vertex
        ``i`` is the linear interpolation of mip ``m-1`` at ``M_{m-1} * i / M_m``.  Because every
        level is linear in the level below it, the whole chain is one matrix -- which is also the
        proof that the drawn height is a weighted AVERAGE of nearby survey heights with non-negative
        weights summing to one, so lowering ground can never raise the drawn surface."""
        n = int(subsection_quads) + 1
        W = np.eye(n, dtype=np.float64)
        prev_q = int(subsection_quads)
        for m in range(1, int(k) + 1):
            q = ((int(subsection_quads) + 1) >> m) - 1
            if q < 1:
                raise ValueError("mip %d leaves %d quads" % (m, q))
            p = prev_q * np.arange(q + 1, dtype=np.float64) / float(q)
            i0 = np.minimum(np.floor(p).astype(np.int64), prev_q)
            i1 = np.minimum(i0 + 1, prev_q)
            f = p - i0
            W = (1.0 - f)[:, None] * W[i0] + f[:, None] * W[i1]
            prev_q = q
        return W

    # -- construction ---------------------------------------------------------------------------
    @classmethod
    def from_landscape_dir(cls, path: str, k: int, subsection_quads: int = 127,
                           sampling: str = "landscape_triangulated") -> "LandscapeLodSurface":
        """Read ``hm_*.r16`` into one landscape-vertex mosaic and build the LOD-k lattice.

        The clip mask is deliberately NOT applied.  ``clip == 0`` marks ground outside the model, but
        the h16 still holds a filled height there and the engine's mip chain averages it like any
        other texel; masking it to NaN here would poison every mip vertex within 2^k cells of the
        coast and delete the answer exactly where the coastal roads are."""
        with open(os.path.join(path, "landscape_manifest.json"), "r", encoding="utf-8") as fh:
            man = json.load(fh)
        res = int(man["res"])
        tile_m = float(man["tile_m"])
        px_m = float(man.get("px_m", tile_m / (res - 1)))
        enc = man.get("heightmap", {}).get("z_encoding", {})
        per_unit = float(enc.get("per_unit", 128))
        offset = float(enc.get("offset", 32768))
        nx, ny = int(man["nx"]), int(man["ny"])
        sq = int(subsection_quads)
        # THE ANCHOR.  Landscape vertex (0, 0) is NOT the survey's north-west sample: the importer
        # pads to a whole component grid on the EAST and the NORTH and moves the actor with it
        # (StreetscapeLandscapeImporter.h:8, .cpp:255 and :506 -- "data row r -> padded row
        # r + pad_north, columns unchanged, actor at (0, -100*(H-1 + pad_north), 0)").  At Thanet
        # that is pad_north = 178, and 178 mod 127 = 51, so getting this wrong slides the whole
        # subsection lattice 51 m north of where the engine puts it.
        sections = int(round(float((man.get("ue_import", {}) or {}).get("sections", 2)) or 2))
        qpc = sq * sections
        w0, h0 = nx * (res - 1) + 1, ny * (res - 1) + 1
        wp = -(-(w0 - 1) // qpc) * qpc + 1
        hp = -(-(h0 - 1) // qpc) * qpc + 1
        pad_north = hp - h0
        pad_h16 = float(man.get("pad_value_h16", offset))
        nsx, nsy = (wp - 1) // sq, (hp - 1) // sq
        mosaic = np.full((hp, wp), np.float32((pad_h16 - offset) / per_unit), dtype=np.float32)
        missing = set(tuple(t) for t in man.get("tiles_missing", []))
        clipped_whole = set(tuple(t) for t in man.get("tiles_clipped", []))
        for t in man.get("tiles", []):
            key = (int(t["x"]), int(t["y"]))
            if key in missing or key in clipped_whole:
                continue
            name = (t.get("files", {}) or {}).get("heightmap") or "hm_x%d_y%d.r16" % key
            h16 = np.fromfile(os.path.join(path, name), dtype="<u2")
            if h16.size != res * res:
                raise ValueError("%s: %d values, expected %d" % (name, h16.size, res * res))
            z = ((h16.astype(np.float64) - offset) / per_unit).reshape(res, res).astype(np.float32)
            r0 = (ny - 1 - key[1]) * (res - 1) + pad_north
            c0 = key[0] * (res - 1)
            mosaic[r0:r0 + res, c0:c0 + res] = z
        return cls(mosaic, k, subsection_quads=sq, y_top_m=px_m * (h0 - 1 + pad_north), px_m=px_m,
                   sampling=sampling, source="landscape:%s +lod%d" % (os.path.abspath(path), k),
                   meta={"pad_north": pad_north, "pad_east": wp - w0, "verts_padded": [wp, hp],
                         "subsections": [nsx, nsy], "quads_per_component": qpc})

    def _build(self, mosaic) -> np.ndarray:
        """``(nsy, M+1, nsx, M+1)`` mip-k heights, one subsection row of blocks at a time."""
        sq, W = self.sq, self.weights
        n = sq + 1
        nsy = (mosaic.shape[0] - 1) // sq
        nsx = (mosaic.shape[1] - 1) // sq
        out = np.empty((nsy, self.mk + 1, nsx, self.mk + 1), dtype=np.float32)
        from numpy.lib.stride_tricks import as_strided
        for sy in range(nsy):
            rows = np.ascontiguousarray(mosaic[sy * sq:sy * sq + n, :], dtype=np.float64)
            blk = as_strided(rows, shape=(n, nsx, n),
                             strides=(rows.strides[0], sq * rows.strides[1], rows.strides[1]))
            r1 = np.tensordot(W, blk, axes=([1], [0]))          # (M+1, nsx, n)   rows -> mip rows
            out[sy] = np.tensordot(r1, W, axes=([2], [1]))      # (M+1, nsx, M+1) cols -> mip cols
        return out

    # -- sampling, with Heightfield's signature so it drops into the same call sites -------------
    def sample(self, x, y) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64) + self.shift_xy[0]
        y = np.asarray(y, dtype=np.float64) + self.shift_xy[1]
        scalar = x.ndim == 0
        x = np.atleast_1d(x)
        y = np.atleast_1d(y)
        out = np.full(x.shape, np.nan, dtype=np.float64)
        nsy, _, nsx, _ = self.grid.shape
        vx = x / self.px_m
        vy = (self.y_top_m - y) / self.px_m
        ok = np.isfinite(vx) & np.isfinite(vy) & (vx >= 0) & (vy >= 0) \
            & (vx <= nsx * self.sq) & (vy <= nsy * self.sq)
        if not ok.any():
            return float(out[0]) if scalar else out
        sq, mk = self.sq, self.mk
        sx = np.clip((vx[ok] / sq).astype(np.int64), 0, nsx - 1)
        sy = np.clip((vy[ok] / sq).astype(np.int64), 0, nsy - 1)
        # mip index space inside the subsection: u in [0, sq] -> a in [0, mk]
        a = (vx[ok] - sx * sq) * mk / float(sq)
        b = (vy[ok] - sy * sq) * mk / float(sq)
        i0 = np.clip(np.floor(a).astype(np.int64), 0, mk - 1)
        j0 = np.clip(np.floor(b).astype(np.int64), 0, mk - 1)
        tx = np.clip(a - i0, 0.0, 1.0)
        ty = np.clip(b - j0, 0.0, 1.0)
        G = self.grid
        nw = G[sy, j0, sx, i0].astype(np.float64)
        ne = G[sy, j0, sx, i0 + 1].astype(np.float64)
        sw = G[sy, j0 + 1, sx, i0].astype(np.float64)
        se = G[sy, j0 + 1, sx, i0 + 1].astype(np.float64)
        out[ok] = _interp(nw, ne, sw, se, tx, ty, self.sampling)
        out[~np.isfinite(out)] = np.nan
        return float(out[0]) if scalar else out

    def rebased(self, doc_E: float, doc_N: float) -> "LandscapeLodSurface":
        raise NotImplementedError("the LOD surface is only defined in the landscape's own frame")

    def describe(self) -> dict:
        d = {"source": self.source, "lod": self.k, "subsection_quads": self.sq,
             "mip_quads": self.mk, "stride_m": self.stride_m, "px_m": self.px_m,
             "y_top_m": self.y_top_m, "grid": [int(v) for v in self.grid.shape],
             "sampling": self.sampling}
        d.update(self.meta)
        return d

    # -- where the engine draws this level -------------------------------------------------------
    @staticmethod
    def distances_m(lod0_screen_size=0.5, lod0_distribution=1.25, lod_distribution=3.0,
                    fov_deg=80.0, aspect=16.0 / 9.0, component_quads=254, px_m=1.0,
                    height_extent_m=20.0, max_lod=5):
        """Distance in metres at which each LOD becomes the one drawn, from the engine's own formula.

        ``ComputeBoundsScreenRadiusSquared`` (``SceneManagement.cpp:933``) is
        ``(0.5 * max(M00, M11) * R / D)^2``; ``FLandscapeRenderSystem::ComputeLODFromScreenSize``
        compares it against the ratio chain of ``LandscapeRender.cpp:1549-1567``.  ``R`` is the
        landscape COMPONENT's bounds sphere radius, not the subsection's."""
        m00 = 1.0 / np.tan(np.radians(fov_deg) / 2.0)
        screen_mult = max(0.5 * m00, 0.5 * m00 * aspect)
        half = 0.5 * component_quads * px_m
        r = float(np.sqrt(2.0 * half * half + (0.5 * height_extent_m) ** 2))
        ratios, cur = [], float(lod0_screen_size)
        ratios.append(cur)
        cur /= max(lod0_distribution, 1.01)
        ratios.append(cur)
        for _ in range(2, max_lod + 1):
            cur /= max(lod_distribution, 1.01)
            ratios.append(cur)
        d = [round(screen_mult * r / q, 1) for q in ratios]
        return {"component_bounds_radius_m": r, "screen_multiple": screen_mult,
                "lod_screen_ratio": ratios,
                "lod_begins_m": d,
                "lod_begins_m_note": (
                    "entry k is the distance at which the component's screen radius falls to the "
                    "ratio for LOD k.  Entry 0 is therefore where LOD 0 ENDS -- inside it the "
                    "landscape is exactly LOD 0 -- and entry k >= 1 is where LOD k is fully "
                    "reached; between two entries the vertex factory morphs between the two levels "
                    "(MorphAlpha), so an integer-LOD surface is the far end of a continuum."),
                "stride_m": [round(127.0 / (((128 >> k) - 1) or 1), 4) for k in range(len(ratios))]}
