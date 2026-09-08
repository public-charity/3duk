# Pipeline design: the `thanet` site, the clip, step 11, tile reuse, and the regression plan

Design-phase output for Project One (see `projects/one/docs/BRIEF.md` §3, §4.1, §4.4). This
document specifies every change to `sources/` needed for the Isle of Thanet build, precisely
enough to implement without further questions. Nothing here has been run yet except the
verification arithmetic in §0.2; the implementation phase runs everything listed in §9.

Repo facts are cited as `path:line` against the working tree of branch `thanet-explorer` at
commit `0d31c0c` (plus the untracked `projects/`). Engine facts are cited against
`C:/Program Files/Epic Games/UE_5.8/Engine/Source`.

---

## 0. What exists, and what was verified

### 0.1 The pipeline as it stands

| | Where | What matters for this design |
|---|---|---|
| Site resolution, config merge, paths | `sources/lib.py:13-57` | `lib.load()` merges `config/sites/<site>.json` and `config/tuning.json`; `lib.paths()` gives `raw/interim/derived/out/lidar/gpkg/osm`. |
| Raster helpers | `sources/lib.py:69-118` | `pixel_size`, `tile_px`, `fill_nodata` (scipy nearest / median fallback), `nodata_mask` (declared sentinel + non-finite + `< -1e30`). |
| TIFF header reader (no GDAL) | `sources/lib.py:126-166` | Reads width/height/dtype/nodata from the first IFD. Does **not** read georeferencing tags; §7 extends it. |
| Shell bridge | `sources/lib.py:174-194` | `eval "$(PY sources/lib.py env)"` gives `.sh` steps `SITE CRS EPSG BBOX NX NY DIR_* OSM GPKG`. |
| Driver | `sources/run.sh:27` (`PY="${PY:-python3.14}"`), `:29-39` (STEPS), `:53` (PY check), `:74` (site resolution), `:78-93` (loop) | `PY` is a plain shell variable, **not exported**; sub-scripts `01_fetch_osm.sh:14` and `03_build_mosaics.sh:11` each default to `python3.14` on their own. |
| Overpass query | `sources/fetch/fetch_osm.sh:21-40` | 13 selectors; **no `way["railway"]`**. Confirmed: `margate.gpkg` layer `lines` has a `railway` column and `SELECT COUNT(*) FROM lines WHERE railway IS NOT NULL` = **0** (also 0 in `other_tags`). |
| LIDAR fetch | `sources/fetch/02_fetch_lidar.py:32-40` (grid stamp), `:50-75` (fetch), `:78` (job list), `:88-95` (summary + hard-fail) | Stamp `_grid.json` = `{crs, origin, tile_m, grid_res}`; a mismatch is FATAL. |
| Mosaics | `sources/derive/03_build_mosaics.sh:16-24` | `gdalbuildvrt` over whatever tiles exist. |
| Heights | `sources/derive/04_derive_heights.py:41-55, 71-131` | Samples every footprint in the GeoPackage; emits nothing itself (interim pickles). |
| Terrain export | `sources/derive/05_export_terrain.py:36-76` (tile loop), `:78-90` (manifest) | Fills nodata, computes slope QA on the filled array, writes DEFLATE/PREDICTOR=3 Float32 with **no NoData tag** (verified with gdalinfo on `data/margate/out/terrain/dtm_x0_y0.tif`). |
| Roads | `sources/derive/06_build_networks.py:54-69` (`ground`), `:72-78` (`tagval`), `:81-92` (`densify`), `:95-106` (`chaikin`), `:152-157` (`tile_of`), `:160-202` (pass 2), `:204-209` (junctions), `:213-219` (write), `:221-231` (manifest) | Off-grid vertex closes the run (`:189-192`); `vertices_outside_grid` counted (`:168`). |
| Massing | `sources/derive/07_massing.py:120-126` (centroid grid test), `:191-199` (manifest) | `outside_grid` counted at `:125`. |
| Ground cover | `sources/derive/09_coast.py:148-180` (tile loop), `:186-196` (manifest) | Bands grass/sand/rock/water, Byte, sum to 255 (`:168-170`). |
| Furniture | `sources/derive/10_furniture.py:139-141` (grid test), `:158-166` (manifest = `qa_furniture.json`) | `outside_grid` counted. |
| Dry run | `sources/tests/dryrun.py:56-121` (`synth`), `:126-396` (sites A, B, lib checks) | 86 `check()` calls today; fake GDAL in `sources/tests/fake_osgeo/osgeo/__init__.py`. |
| Reference adapter | `sources/adapters/unity.py:44-77` (terrain), `:81-108` (roads), `:130-165` (ground), `:189-193` (`__main__`) | Pattern the Unreal adapter follows (runpy-importable, functions callable with `run_name="not_main"`, see `dryrun.py:305`). |

### 0.2 Verified numbers (computed 2026-09-07 with the env python, numpy 2.5.3)

* Clip line `A = (628514, 169681)`, `B = (635498, 163610)`: `B−A = (6984, −6071)`, length **9253.8 m**, bearing **131.0°**. For `keep: left`, `cross(B−A, P−A) = (P−A)·(6071, 6984)`, exactly as BRIEF §4.1.
* Thanet grid (origin 627680/163080, 512 m, 26×19) against the line by tile corners: **360 inside, 31 straddle, 103 outside** → 391 tiles fetched, 782 rasters. Straddle tiles: `(0,13) (0,14) (1,12) (1,13) (2,11) (2,12) (3,10) (3,11) (4,9) (4,10) (5,9) (6,8) (6,9) (7,7) (7,8) (8,6) (8,7) (9,5) (9,6) (10,4) (10,5) (11,3) (11,4) (12,3) (13,2) (13,3) (14,1) (14,2) (15,0) (15,1) (16,0)`.
* Cells outside the clip inside straddle tiles (513×513 centres on integer metres): **3,884,985** of 8,158,239 — what step 05 will write as nodata.
* Margate's 13×7 grid maps to Thanet tiles `(i+10, j+10)` (offsets `5120/512 = 10` both axes) and **all 91 are `inside`** — none straddle, so every reused tile is exported whole.
* Margate station, Birchington station, Manston, Ramsgate harbour, North Foreland kept; Minster, Cliffsend excluded.
* Raw EA tile `data/margate/raw/lidar/dtm_x0_y0.tif`: 513×513 Float32, `ModelTransformationTag` (34264) = `(1,0,0,632799.5, 0,−1,0,168712.5, …)`, `GDAL_NODATA` (42113) = `-3.4028234663852886E+38`, `GeoKeyDirectory` ProjectedCSTypeGeoKey 27700, tiled 512×512. Pixel centres are on integer metres from `632800..633312`.
* Step 05 output tile: `ModelTiepointTag` (33922) + `ModelPixelScaleTag` (33550), same origin, no NoData tag, DEFLATE, PREDICTOR 3, tiled 256×256. All 91 Margate terrain tiles have `nodata_cells 0`, `fill none`.
* Margate barrier ways in `lines`: wall 175, fence 173, hedge 42, retaining_wall 30, kerb 19, gate 13, bollard 13, yes 2 (467 total). Tags present in `other_tags`: `height` on 15 ways, `material` 33, `fence_type` 42, `wall` 14 (values seen: `brick`, `seawall`). Two barrier features sit in `multipolygons` (closed ways/relations); 388 barrier **nodes** in `points`.
* Environment: `C:/Users/Shadow/code/3duk-env/env/python.exe` is Python 3.13.15, numpy 2.5.3, scipy 1.18.0, GDAL 3.13.3. `python3`/`python` on PATH resolve to `…/WindowsApps/` Store stubs; `python3.14`/`python3.13` do not exist on PATH. `sha256sum` (coreutils 8.32) is available in Git Bash.

---

## 1. `sources/config/sites/thanet.json` — full content

Every inherited block carries a note saying where it was measured. Keys ending in `note`
are ignored by code (as they are today in `margate.json`).

```json
{
  "crs": "EPSG:27700",
  "crs_note": "British National Grid, exactly as Margate. Every raster and vector in the pipeline is held in this CRS; OSM arrives in WGS84 degrees and is reprojected by step 01.",
  "crs_max_transform_accuracy_m": 1.0,
  "crs_max_transform_accuracy_note": "Inherited from Margate. Step 01 refuses to reproject OSM unless PROJ's best WGS84 -> OSGB36 operation is at least this accurate: the OSTN15 grid (1 m class), not the 2 m Helmert fallback that put the Margate model 1.8 m off the LIDAR. The grid is not installed on this machine; step 01 sets PROJ_NETWORK=ON and PROJ fetches it from cdn.proj.org.",

  "origin": { "E": 627680, "N": 163080 },
  "origin_note": "South-west corner of the tile grid, in CRS metres. Chosen so that Margate's grid (origin 632800/168200) is a sub-grid: Margate tile (i, j) == Thanet tile (i+10, j+10). Margate's 91 downloaded tile positions (182 rasters) are therefore bit-identical to what step 02 would fetch here and are copied in by sources/fetch/reuse_tiles.py instead of re-downloaded.",

  "tile_m": 512,
  "nx": 26,
  "ny": 19,
  "grid_res": 513,
  "grid_res_note": "Samples per tile edge. 513 = 512 + 1 so adjacent tiles share an identical edge row and there is no seam. Extent: E 627680..640992, N 163080..172808 (13.3 x 9.7 km, 494 tile positions).",

  "bbox_wgs84": [51.305, 1.275, 51.405, 1.465],
  "bbox_note": "S,W,N,E -- Overpass order. Generous on purpose: the grid and the clip are the model; features outside them are counted and dropped by steps 06/07/10/11. Expect a ~45 MB extract (Margate's 8.6 MB scaled by area).",

  "clip": {
    "type": "halfplane",
    "line": [[628514, 169681], [635498, 163610]],
    "keep": "left",
    "note": "The Isle of Thanet is cut from the mainland by a hard straight line along the old Wantsum Channel. A point P is KEPT iff cross(B-A, P-A) >= 0, i.e. (P-A) . (6071, 6984) >= 0 -- the half-plane on the LEFT of A->B, which is north-east. Points exactly on the line are kept. Step 02 does not fetch tiles wholly outside; step 05 writes nodata (not filled) for cells outside; steps 06/07/09/10/11 drop and count. Endpoints are config, not code: move them and rebuild.",
    "endpoints_note": "A = Minnis Bay (OSM natural=bay node, 51.38015 N 1.28241 E). B = Pegwell Bay (OSM place=locality node, 51.32281 N 1.37858 E). 9,254 m, bearing 131 deg A->B. Verified kept: Margate, Birchington station, Manston, Ramsgate harbour, North Foreland. Verified excluded: Minster, Cliffsend.",
    "budget_note": "Against this 26x19 grid, by tile corners: 360 tiles inside, 31 straddle, 103 outside -> 391 tiles fetched (782 rasters), 3,884,985 cells written as nodata in the straddle tiles. Computed 2026-09-07 with lib.tile_state / lib.cell_mask."
  },

  "vertical_datum": "ODN",
  "vertical_datum_note": "Ordnance Datum Newlyn -- the datum of the EA LIDAR. Every elevation the pipeline emits, including water_level, is metres above this.",

  "water_level": -0.6,
  "water_level_note": "INHERITED FROM MARGATE (same EA composite, same survey flights, same chalk coast; measured there as the DTM's flat sea surface). Expected to hold across the isle. Check coast_manifest.water_tiles and the sea-tile minima from the first Thanet run of 05 before trusting it for Pegwell Bay's mudflats.",

  "height_calib": {
    "mode": "auto",
    "min_buildings": 30,
    "fallback": { "intercept": 1.337, "m_per_level": 2.807 },
    "dispute_m": 4.0,
    "note": "mode auto: step 07 regresses height = intercept + m_per_level * building:levels from THANET's own buildings that carry both a levels tag and a trustworthy LIDAR p50, records the fit in massing_manifest.json, and uses it. The fallback is Margate's FITTED line (n=1457, 83 rejected, rmse 1.4 m, measured 2026-09-07 on this same survey), not the old hardcoded 3.16/1.84 of uncertain provenance. With ~4x Margate's building stock the fit will engage; the manifest says source=fitted if it did."
  },

  "coast": {
    "foreshore_max_odn": 1.2,
    "rock_slope_deg": [22.0, 40.0],
    "water_margin_m": 0.75,
    "water_tolerance_m": 0.3,
    "missing_tiles_are_water": false,
    "note": "INHERITED FROM MARGATE. foreshore_max_odn is a property of the survey's tide state: the EA flew this stretch at low tide, so the intertidal flat reads as land and anything below 1.2 m ODN is sand. rock_slope_deg is the ramp tuned to the Cliftonville chalk cliffs; Thanet is the same chalk from Birchington round North Foreland to Ramsgate. water_tolerance_m 0.3 is what Margate ran with (its default). missing_tiles_are_water false: the composite carried 100% coverage over the sea at Margate and Whitby, so tiles_missing is expected to be empty; if the first run lists missing tiles in the north-east (open sea) set this true rather than assuming. Clipped tiles (outside the Wantsum line) are NOT missing tiles -- they are listed separately as tiles_clipped."
  },

  "wcs": {
    "dtm": {
      "url": "https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wcs",
      "coverage": "13787b9a-26a4-4775-8523-806d13af58fc__Lidar_Composite_Elevation_DTM_1m"
    },
    "dsm": {
      "url": "https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-first-return-dsm-1m/wcs",
      "coverage": "df4e3ec3-315e-48aa-aaaf-b5ae74d7b2bb__Lidar_Composite_Elevation_FZ_DSM_1m"
    },
    "note": "Identical to Margate's -- a precondition for reusing its tiles (reuse_tiles.py refuses if either coverage differs)."
  },

  "lidar_reuse_note": "Before step 02: PY sources/fetch/reuse_tiles.py --from margate --to thanet. It proves both grids are 512-aligned with identical tile_m, grid_res, crs and WCS coverages, copies data/margate/raw/lidar/{dtm,dsm}_x{i}_y{j}.tif to data/thanet/raw/lidar/{dtm,dsm}_x{i+10}_y{j+10}.tif after checking each file's own georeferencing tag lands where the new name says, and writes the _grid.json stamp (with the clip) so step 02 accepts the directory and fetches only the remaining 300 tiles.",

  "landmarks": {
    "_note": "INHERITED FROM MARGATE (both are on the isle). Hand-authored overrides for buildings the LIDAR p50 estimator gets wrong, keyed by OSM name; step 07 reports how many applied. Do NOT pre-add Ramsgate or Broadstairs landmarks: qa_height_outliers.json from the first Thanet run decides whether the Royal Harbour buildings, Bleak House or the Granville need one.",
    "Arlington House": {
      "h_body": 57.0, "roof": "flat", "tier": "hero",
      "why": "18-storey tower on a large podium; p50 samples the podium (7.0m from 22px). Real height ~57m."
    },
    "Jubilee Clock Tower": {
      "h_body": 24.0, "roof": "tower", "tier": "hero",
      "why": "Tiny footprint (7px) undersamples the tower. Real height ~24m."
    }
  }
}
```

`lib.load()` needs no change to read this: `clip` is just another key, and `lib.parse_clip(cfg)`
(§2) is what the steps call.

---

## 2. The clip feature in `lib.py`

### 2.1 Placement and principles

A new section `# ---- clip region ----` goes after the raster-geometry section (after
`nodata_mask`, `lib.py:118`) and before the TIFF header section (`lib.py:121`). Rules:

* Steps call **only** the five module-level functions (`parse_clip`, `keep_points`,
  `tile_state`, `cell_mask`, `clip_wkt`) plus `clip_manifest` and `grid_stamp`. They never
  look inside the clip object, so a `polygon` type is one new class registered in
  `_CLIP_TYPES` and zero step edits.
* Every function accepts `clip=None` and answers "everything is kept": `keep_points` → all
  `True`, `tile_state` → `'inside'`, `cell_mask` → all `True`, `clip_wkt` → the bbox
  rectangle, `clip_manifest` → `None`, `grid_stamp` → today's four keys. **No step's code
  path writes anything different when the clip is `None`** — the clip-only manifest keys
  are added under `if CLIP is not None` guards (§3.0), the NoData tag is only set when a clip
  exists, and the `_grid.json` stamp only gains a `clip` key when one exists. That is how a
  missing clip block yields byte-identical behaviour to today, manifests included.
* Vectorised: `keep_points` works on numpy arrays with broadcasting (scalars are fine).
  Half-plane test in float64 on raw eastings/northings: the products are ~1e4 × 1e4 = 1e8,
  well inside double precision; ties (`== 0`) are kept, per BRIEF.
* Only north-up geotransforms are supported (`gt[2] == gt[4] == 0`); anything else is a
  `sys.exit`, matching the pipeline's north-up contract.

### 2.2 Code

```python
# ---- clip region ------------------------------------------------------------
# An optional `clip` block in the site config restricts the model to a region inside the
# tile grid (Thanet: the half-plane north-east of the Minnis Bay -> Pegwell Bay line).
# The steps ask three questions -- is this point kept, what is this tile's state, which
# cells of this raster are kept -- through the module-level functions below and never look
# inside the clip object, so another clip type is one more class in _CLIP_TYPES. With no
# clip block every function answers "kept", and no step writes a different byte.

class HalfPlaneClip:
    """Keep one side of the infinite line through A and B.

    keep 'left': keep P iff cross(B-A, P-A) >= 0 -- P on, or to the left of, A->B when
    looking from A towards B. 'right' negates the test. Points exactly on the line are
    kept, so a cell centre or a vertex lying on it belongs to the model.
    """
    type = "halfplane"

    def __init__(self, block):
        (ax, ay), (bx, by) = block["line"]
        self.a, self.b = (float(ax), float(ay)), (float(bx), float(by))
        self.keep = block.get("keep", "left")
        if self.keep not in ("left", "right"):
            sys.exit(f"clip.keep must be 'left' or 'right', got {self.keep!r}")
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        if dx == 0.0 and dy == 0.0:
            sys.exit("clip.line: the two endpoints coincide")
        s = 1.0 if self.keep == "left" else -1.0
        self.n = (-dy * s, dx * s)          # cross(B-A, P-A) == (P-A) . (-dy, dx)

    def stamp(self):
        """The normalised block, without notes -- what goes into manifests and _grid.json."""
        return {"type": self.type, "line": [list(self.a), list(self.b)], "keep": self.keep}

    def keep_points(self, E, N):
        import numpy as np
        E = np.asarray(E, dtype=np.float64); N = np.asarray(N, dtype=np.float64)
        return (E - self.a[0]) * self.n[0] + (N - self.a[1]) * self.n[1] >= 0.0

    def rect_state(self, e0, n0, e1, n1):
        """'inside' if all four corners are kept, 'outside' if none, else 'straddle'.
        A half-plane is convex, so a rectangle with all corners kept has every interior
        point kept, and one with no corner kept has none."""
        k = self.keep_points([e0, e1, e0, e1], [n0, n0, n1, n1])
        return "inside" if k.all() else ("outside" if not k.any() else "straddle")

    def rect_polygon(self, e0, n0, e1, n1):
        """Kept part of the rectangle as a closed list of (E, N); [] if nothing is kept.
        Sutherland-Hodgman against the one clip edge."""
        poly = [(e0, n0), (e1, n0), (e1, n1), (e0, n1)]
        f = lambda p: (p[0] - self.a[0]) * self.n[0] + (p[1] - self.a[1]) * self.n[1]
        out = []
        for i in range(4):
            p, q = poly[i], poly[(i + 1) % 4]
            fp, fq = f(p), f(q)
            if fp >= 0.0:
                out.append(p)
            if (fp >= 0.0) != (fq >= 0.0):
                t = fp / (fp - fq)
                out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        return out + [out[0]] if len(out) >= 3 else []


_CLIP_TYPES = {"halfplane": HalfPlaneClip}


def parse_clip(cfg):
    """The site's clip object, or None when the config has no `clip` block."""
    blk = cfg.get("clip")
    if not blk:
        return None
    t = blk.get("type")
    if t not in _CLIP_TYPES:
        sys.exit(f"clip.type {t!r} not supported (known: {', '.join(sorted(_CLIP_TYPES))})")
    return _CLIP_TYPES[t](blk)


def keep_points(clip, E, N):
    """Boolean array, True where (E, N) is kept. Broadcasts; scalars give a 0-d array."""
    import numpy as np
    if clip is None:
        return np.ones(np.broadcast(np.asarray(E), np.asarray(N)).shape, dtype=bool)
    return clip.keep_points(E, N)


def tile_state(clip, cfg, i, j):
    """'inside' | 'straddle' | 'outside' for tile (i, j) of the config's grid."""
    if clip is None:
        return "inside"
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    return clip.rect_state(E0 + i * T, N0 + j * T, E0 + (i + 1) * T, N0 + (j + 1) * T)


def cell_mask(clip, gt, height, width, row0=0, col0=0):
    """(height, width) bool array of KEPT cells for a north-up raster with geotransform gt,
    evaluated at pixel CENTRES: E = gt[0] + (col + 0.5) * gt[1], N = gt[3] + (row + 0.5) * gt[5].
    row0/col0 address a sub-window of a larger raster (step 09 reads tiles out of the mosaic)."""
    import numpy as np
    if clip is None:
        return np.ones((height, width), dtype=bool)
    if gt[2] != 0.0 or gt[4] != 0.0:
        sys.exit("cell_mask: rotated geotransforms are not supported; rasters here are north-up")
    E = gt[0] + (col0 + np.arange(width) + 0.5) * gt[1]
    N = gt[3] + (row0 + np.arange(height) + 0.5) * gt[5]
    return clip.keep_points(E[None, :], N[:, None])


def clip_wkt(clip, bbox):
    """WKT POLYGON of the kept part of bbox = (E_min, N_min, E_max, N_max), for OGR
    Intersection tests and for consumers that want the cut as a polygon. None if the
    bbox lies wholly outside the clip. With no clip: the bbox rectangle."""
    e0, n0, e1, n1 = bbox
    ring = ([(e0, n0), (e1, n0), (e1, n1), (e0, n1), (e0, n0)] if clip is None
            else clip.rect_polygon(e0, n0, e1, n1))
    if not ring:
        return None
    return "POLYGON((" + ",".join(f"{x:.3f} {y:.3f}" for x, y in ring) + "))"


def clip_manifest(clip):
    """What every affected manifest records under "clip": the normalised block plus the
    rule in words, so a consumer can re-derive the mask without reading this code."""
    if clip is None:
        return None
    return {**clip.stamp(),
            "semantics": "keep P iff cross(B-A, P-A) >= 0 for keep 'left' (<= 0 for 'right'); "
                         "line = [A, B] in CRS metres; points on the line are kept. Raster cells "
                         "are tested at their centres; features at their vertices (06, 11), "
                         "footprint centroid (07) or node (10)."}


def grid_stamp(cfg, clip):
    """The _grid.json stamp step 02 and reuse_tiles.py agree on. Gains a 'clip' key only
    when the site has one, so an existing clipless stamp still matches its config."""
    s = {"crs": cfg["crs"], "origin": cfg["origin"], "tile_m": cfg["tile_m"], "grid_res": cfg["grid_res"]}
    if clip is not None:
        s["clip"] = clip.stamp()
    return s
```

`keep_points(clip, cx, cy)` on scalars returns a 0-d array; `if not lib.keep_points(...)`
works because numpy 0-d bool arrays are truthy/falsy.

A later `PolygonClip` would implement the same four methods (`stamp`, `keep_points`
via an even-odd/winding test, `rect_state` via corner test + edge/rectangle intersection,
`rect_polygon` via a general polygon clip) and be registered as `"polygon"`. Nothing else
moves.

### 2.3 Shared line geometry for step 11 (also in `lib.py`)

Section `# ---- line geometry ----`, after the clip section. These are **verbatim copies**
of step 06's functions, plus the per-way drape/split loop turned into a function. Step 06
is **not** refactored to import them in this round (§4.3 gives the reasoning); the dry run
proves the copies reproduce 06 by draping a rail way and a road along the same polyline and
demanding identical output (§8).

```python
# ---- line geometry -------------------------------------------------------------
# Densify + Chaikin + bilinear drape + per-tile split, exactly as step 06 does it. Step 06
# keeps its own copies until the byte-identity harness (sources/tests/regress_outputs.sh)
# gates a refactor; step 11 uses these. Changing one without the other breaks the dry
# run's "rail on a road's polyline gives identical pts" check.

def tagval(ot, key):                        # == 06_build_networks.py:72-78
    if not ot: return None
    tok = '"' + key + '"=>"'
    i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i + len(tok))
    return ot[i + len(tok):j]


def densify(pts, step):                     # == 06_build_networks.py:81-92
    import math
    out = [pts[0]]
    for i in range(1, len(pts)):
        ax, ay = out[-1]; bx, by = pts[i]
        d = math.hypot(bx - ax, by - ay)
        if d > step:
            n = int(d // step)
            for k in range(1, n + 1):
                t = k * step / d
                if t < 1.0: out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        out.append(pts[i])
    return out


def chaikin(pts, iters):                    # == 06_build_networks.py:95-106
    for _ in range(iters):
        if len(pts) < 3: break
        new = [pts[0]]
        for i in range(len(pts) - 1):
            ax, ay = pts[i]; bx, by = pts[i + 1]
            new.append((ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25))
            new.append((ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75))
        new.append(pts[-1])
        pts = new
    return pts


class DtmSampler:
    """06_build_networks.py:54-69 as an object: bilinear sample of a north-up array whose
    gaps are NaN. __call__(e, n) -> (elevation, ok)."""
    def __init__(self, arr, gt):
        self.a, self.gt = arr, gt
        self.H, self.W = arr.shape

    def __call__(self, e, n):
        import math, numpy as np
        gt, W, H, DTM = self.gt, self.W, self.H, self.a
        fx = (e - gt[0]) / gt[1] - 0.5
        fy = (n - gt[3]) / gt[5] - 0.5
        if not (0.0 <= fx <= W - 1 and 0.0 <= fy <= H - 1):
            return (0.0, False)
        x0, y0 = int(math.floor(fx)), int(math.floor(fy))
        x0 = min(x0, W - 2); y0 = min(y0, H - 2)
        tx, ty = fx - x0, fy - y0
        a = DTM[y0, x0]; b = DTM[y0, x0+1]; c = DTM[y0+1, x0]; d = DTM[y0+1, x0+1]
        v = (a*(1-tx) + b*tx)*(1-ty) + (c*(1-tx) + d*tx)*ty
        return (float(v), True) if np.isfinite(v) else (0.0, False)


def tile_of(cfg, e, n):                     # == 06_build_networks.py:152-157, cfg passed in
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    i, j = int((e - E0) // T), int((n - N0) // T)
    return (i, j) if 0 <= i < cfg["nx"] and 0 <= j < cfg["ny"] else None


def drape_runs(pts, cfg, sample, clip, counters):
    """06_build_networks.py:163-201 as a function. pts: already densified/smoothed (E, N).
    sample: DtmSampler. Returns [(tile, [[E, N, z], ...], z_gap)], one per tile run, with
    the seam vertex duplicated on both sides. An off-grid vertex and an off-clip vertex both
    close the current run. counters (dict) is incremented: 'outside_grid', 'outside_clip',
    'without_dtm' (only for kept vertices -- an off-clip vertex is not a DTM gap)."""
    keep = keep_points(clip, [p[0] for p in pts], [p[1] for p in pts]) if clip is not None else None
    samp = []
    for k, (e, n) in enumerate(pts):
        tile = tile_of(cfg, e, n)
        if tile is None:
            counters["outside_grid"] = counters.get("outside_grid", 0) + 1
            samp.append((e, n, None, None)); continue
        if keep is not None and not keep[k]:
            counters["outside_clip"] = counters.get("outside_clip", 0) + 1
            samp.append((e, n, None, None)); continue
        z, ok = sample(e, n)
        samp.append((e, n, z if ok else None, tile))
    zs = [s[2] for s in samp]
    counters["without_dtm"] = counters.get("without_dtm", 0) + sum(1 for (_, _, z, t) in samp if z is None and t is not None)
    last = None
    for idx in range(len(zs)):
        if zs[idx] is not None: last = zs[idx]
        elif last is not None and samp[idx][3] is not None: zs[idx] = last
    nxt = None
    for idx in range(len(zs) - 1, -1, -1):
        if zs[idx] is not None: nxt = zs[idx]
        elif nxt is not None and samp[idx][3] is not None: zs[idx] = nxt
    runs, run, cur, run_gap = [], [], None, False
    def flush():
        if cur is not None and len(run) >= 2: runs.append((cur, run, run_gap))
    for (e, n, z_raw, tile), z in zip(samp, zs):
        filled = z_raw is None
        if tile is None:
            flush(); run, cur, run_gap = [], None, False
            continue
        if z is None: z = 0.0
        if cur is None: cur = tile
        v = [round(e, 2), round(n, 2), round(z, 2)]
        if tile != cur:
            run.append(v); run_gap |= filled
            flush()
            run = [run[-1]]; cur = tile; run_gap = filled
        run.append(v); run_gap |= filled
    flush()
    return runs
```

(`flush` mutates `run`/`cur`/`run_gap` from the enclosing scope only by reading them; the
reassignments happen in the loop body, so no `nonlocal` is needed — same structure as
06's module-level `flush`.)

---

## 3. Per-step changes

### 3.0 Common pattern

Each affected step adds, right after `P = lib.paths(CFG)`:

```python
CLIP = lib.parse_clip(CFG)
```

and, in its manifest `json.dump({...})`, adds the clip keys **only when a clip exists**, e.g.

```python
extra = {} if CLIP is None else {"clip": lib.clip_manifest(CLIP), "tiles_clipped": clipped, ...}
json.dump({..., **extra}, ...)
```

This is the guarantee that Margate's and Whitby's manifests do not change by a byte (§9).
Consumers therefore use `manifest.get("clip")`; `None`/absent means no clip.

### 3.1 Step 02 `sources/fetch/02_fetch_lidar.py`

| Location | Change |
|---|---|
| after `:28` | `CLIP = lib.parse_clip(CFG)` |
| `:32` `GRID = {...}` | `GRID = lib.grid_stamp(CFG, CLIP)` — same four keys as today plus `clip` when present, so Margate's existing `_grid.json` still compares equal (`:34-38` unchanged). |
| `:78` job list | `positions = [(i, j) for i in range(CFG["nx"]) for j in range(CFG["ny"])]`<br>`skipped = [(i, j) for (i, j) in positions if lib.tile_state(CLIP, CFG, i, j) == "outside"]`<br>`jobs = [(k, i, j) for k in ("dtm", "dsm") for (i, j) in positions if (i, j) not in set(skipped)]` |
| `:79` print | add: `if skipped: print(f"clip: skipping {len(skipped)} tile positions ({2*len(skipped)} rasters) wholly outside the clip line", flush=True)` |
| `:88` summary | `stats["skipped_clip"] = 2 * len(skipped)` before `print("summary:", stats)` — Thanet prints `skipped_clip: 206`. |

A tile already on disk for an `outside` position (fetched before the clip was added) is left
alone here — 05 and 09 skip it deterministically from the config (§3.3, §3.6), so it is
inert. Step 02 has no manifest; the `_grid.json` stamp and the printed summary are its
record, and 05's `tiles_clipped` is the durable one.

### 3.2 Steps 03 and 04 — no change

* **03** mosaics whatever tiles exist (`03_build_mosaics.sh:22`). With 391 of 494 positions
  present the VRT simply has nodata where the 103 skipped tiles would be; every consumer of
  the VRT (`04:22-31`, `06:44-50`, `09:48-54`) already treats VRT nodata as a gap. Its
  "expected nx*ny" message (`:28`) becomes informational for a clipped site; the design
  leaves it (the number is still the grid size).
* **04** samples footprints and writes interim pickles; it emits no product. Footprints
  outside the clip get statistics that 07 never emits (07 applies the clip at the centroid
  test, §3.5). Its `height_calib` inputs (`07:66-86`) therefore include mainland buildings —
  deliberately: the regression is a property of the survey's building stock, more samples
  are better, and today it already includes off-grid buildings (no grid test in
  `fit_calibration`). Recorded here as a decision, not an accident.

### 3.3 Step 05 `sources/derive/05_export_terrain.py`

Semantics (BRIEF §4.1): cells outside the clip are written as **nodata by choice, after the
source-gap fill**, so a consumer can distinguish "the survey had no data here" (filled, counted
in `nodata_cells`) from "the model ends here" (declared NoData, counted in `clipped_cells`).

| Location | Change |
|---|---|
| after `:23` | `CLIP = lib.parse_clip(CFG)`; `ND = -9999.0  # output NoData for clipped cells; only declared when a clip exists` |
| `:34` | add `clipped = []` (tile positions with state `outside`, or straddle with zero kept cells) and `n_clipped_total = 0` |
| `:36-41` loop head | insert **before** the `os.path.exists(src)` test:<br>`state = lib.tile_state(CLIP, CFG, i, j)`<br>`if state == "outside":`<br>`    clipped.append([i, j])`<br>`    if os.path.exists(src): print(f"  dtm_x{i}_y{j}: on disk but wholly outside the clip; not exported")`<br>`    continue`<br>The existing missing-file branch (`:39-41`) then applies only to `inside`/`straddle` positions, so `tiles_missing` keeps its meaning (coverage gap). |
| after `:45` (fill) and after `:57-60` (slope on the filled array) | `keep = lib.cell_mask(CLIP, d.GetGeoTransform(), RES, RES)`<br>`n_clip = int((~keep).sum())`<br>`if n_clip == RES * RES:  # straddle by corners, but no cell centre kept (cannot happen with EA geometry: the corners are cell centres)`<br>`    clipped.append([i, j]); print(...); continue`<br>`kept_a = a[keep]`; `kept_slope = slope[keep]` |
| `:50` range | `lo, hi = min(lo, float(kept_a.min())), max(hi, float(kept_a.max()))` |
| `:59-60` slope stats | compute `t_max, t_p99, t_over` from `kept_slope`; `cells += int(keep.sum())`. The slope itself is still computed on the **filled, unclipped** array (`:57-58`) — the ground beyond the line is real terrain and gives the true gradient at the edge; taking the gradient across a nodata step would report a fake 89.99° cliff. |
| after slope, before `:62` write | `if CLIP is not None: a[~keep] = ND` |
| `:62-67` write | after `dst.SetProjection(wkt)`: `if CLIP is not None: dst.GetRasterBand(1).SetNoDataValue(ND)` — set on **every** tile of a clipped site (inside tiles too) so the declaration is uniform per site; never on a clipless site, so today's tiles are byte-identical. |
| `:68-76` per-tile manifest | `min_m`/`max_m` from `kept_a`; add, only when `CLIP is not None`: `"clip_state": state` (`inside`/`straddle`), `"clipped_cells": n_clip`. |
| `:78-90` manifest | add, only when `CLIP is not None`: `"nodata": ND`, `"clip": lib.clip_manifest(CLIP)`, `"tiles_clipped": clipped`, `"clipped_cells_total": n_clipped_total`, and `"clip_note": "Cells outside the clip are written as the declared NoData AFTER source gaps were filled: a NoData cell is a deliberate absence (the model ends here), never a coverage gap. Coverage gaps were filled and are counted in nodata_cells; grid positions with no source tile are tiles_missing; positions wholly outside the clip are tiles_clipped and have no file."` |
| `:92` print | append `f"   ({len(clipped)} positions outside the clip: not exported)"` when non-empty. |

Decision — straddle tile with zero kept cells: **not written**, listed in `tiles_clipped`. It
cannot occur for EA geometry (the 513 centres include the four tile corners, and a straddle
tile has at least one kept corner), so the branch is defensive; it exists because a 2 m or
offset raster could produce it and an all-NoData GeoTIFF would be a tile that claims to
exist and holds nothing.

`range_m` is over kept cells only, because that is what a consumer's encoding window must
hold; `slope_qa` likewise, so the cliff proof (`max_deg ≥ 80`) refers to modelled ground.

### 3.4 Step 06 `sources/derive/06_build_networks.py`

Clip support only — no refactor (BRIEF §4.4: "Step 06 itself stays untouched except for clip
support").

| Location | Change |
|---|---|
| after `:39` | `CLIP = lib.parse_clip(CFG)` |
| `:144` | `total_len, n_nodata, n_outside = 0.0, 0, 0` → add `n_outside_clip, n_junc_clip = 0, 0` |
| `:161` after `pts = chaikin(...)` | `keep = lib.keep_points(CLIP, [p[0] for p in pts], [p[1] for p in pts]) if CLIP is not None else None` — tested on the **smoothed** vertices, the ones that are emitted. |
| `:165-172` sampling loop | `for k, (e, n) in enumerate(pts):` and, after the `tile is None` branch (`:167-170`):<br>`if keep is not None and not keep[k]:`<br>`    n_outside_clip += 1`<br>`    samp.append((e, n, None, None))`<br>`    continue`<br>A `(e, n, None, None)` entry is exactly what an off-grid vertex produces, so the fill loops (`:176-182`) skip it and the run loop (`:189-192`) closes the run at it — "an off-clip vertex closes the run exactly like an off-grid vertex". The clip test precedes `ground()`, so an off-clip vertex is not counted in `vertices_without_dtm`. |
| `:204-207` junctions | after `if tile is None: continue`: `if CLIP is not None and not lib.keep_points(CLIP, e, n): n_junc_clip += 1; continue` |
| `:221-231` manifest | add only when `CLIP is not None`: `"clip": lib.clip_manifest(CLIP)`, `"vertices_outside_clip": n_outside_clip`, `"junctions_outside_clip": n_junc_clip`. |
| `:233-238` prints | add `f"   off-clip vertices: {n_outside_clip}, junctions: {n_junc_clip}"` when a clip exists. |

Known limitation, stated in OUTPUT.md (§10): a way ends at its **last kept smoothed vertex**,
not at the exact intersection with the line — the same rule the grid edge uses today
(`OUTPUT.md:64`). With `densify_step_m 8` and two Chaikin passes the emitted vertex spacing is
about 2 m, so the gap between the last vertex and the line is under 12 m in the worst case
(the last densified 8 m step, diagonal). The Unreal side extends the spline's last segment
to the visibility edge if it wants a flush end; the survey data does not invent a vertex.

`length_km` (`:202`) keeps counting the whole way, off-grid and off-clip parts included, as it
does today for off-grid parts — unchanged so Margate's number does not move.

### 3.5 Step 07 `sources/derive/07_massing.py`

| Location | Change |
|---|---|
| after `:31` | `CLIP = lib.parse_clip(CFG)` |
| `:119` | `outside_clip = 0` |
| `:122-126` | after the grid test: `if CLIP is not None and not lib.keep_points(CLIP, cx, cy): outside_clip += 1; continue` — the same envelope-centre `(cx, cy)` the tile assignment uses, so "the tile that owns the building" and "is the building kept" agree. |
| `:191-199` manifest | add only when `CLIP is not None`: `"clip": lib.clip_manifest(CLIP)`, `"outside_clip": outside_clip`. |
| `:203-204` print | append `off-clip: {outside_clip}`. |

A footprint straddling the line is kept whole or dropped whole by its centroid; rings are not
cut (the landscape hole under half a building is an Unreal-side matter and the count of such
buildings is small: the line runs through farmland and the Stour marshes).

### 3.6 Step 09 `sources/derive/09_coast.py`

Decision for the ground raster: cells outside the clip get **all four bands zero**. The
contract "bands sum to 255" becomes "sum to 255 for every modelled cell; a cell that sums to
0 is outside the clip, and that is the only way a cell can sum to 0". Justification:

* Skipping straddle tiles would leave Ramsgate's and Birchington's edges unpainted.
* Painting clipped cells as classified would put ground cover under the landscape hole
  (harmless in Unreal, since the hole hides it, but it contradicts "everything south-west
  of the line does not exist" and would make the raster disagree with the terrain's NoData).
* A fifth band would change the raster shape for every consumer, including Unity's
  (`unity.py:139-145` reads `min(RasterCount, 4)` bands).
* Zero is self-describing and cheap to test (`sum == 0`), and the adapter can cross-check it
  against the terrain NoData mask at 2 m resolution.

| Location | Change |
|---|---|
| after `:44` | `CLIP = lib.parse_clip(CFG)` |
| `:147` | `water_tiles, missing, wrote = [], [], 0` → add `clipped, n_clipped_cells = [], 0` |
| `:148-155` loop head | first statement in the `for j` body: `state = lib.tile_state(CLIP, CFG, i, j)`; `if state == "outside": clipped.append([i, j]); continue` — before the mosaic-bounds test, so a skipped tile is never listed in `tiles_without_dtm`. |
| `:159` water-tile test | for straddle tiles judge only kept DTM cells: `kd = lib.cell_mask(CLIP, gt, TPY, TPX, row0=row0, col0=col0)`; `sub_k = np.where(kd, sub_h, np.nan)`; use `sub_k` in the `nanmin` test (and skip the test if `not np.isfinite(sub_k).any()`). For `inside` tiles `kd` is all True and the arithmetic is identical. |
| after `:170` (`img = ...`) | `if state == "straddle":`<br>`    km = lib.cell_mask(CLIP, (e0, cell, 0.0, n0 + T, 0.0, -cell), SPLAT, SPLAT)`<br>`    img[~km] = 0`<br>`    n_clipped_cells += int((~km).sum())` — mask evaluated at the **class-cell centres** `e0 + (c + 0.5)·cell`, which is the geotransform the tile is written with (`:175`). |
| `:186-196` manifest | add only when `CLIP is not None`: `"clip": lib.clip_manifest(CLIP)`, `"tiles_clipped": clipped`, `"clipped_cells": n_clipped_cells`, `"bands_note": "grass+sand+rock+water == 255 for every cell inside the clip; cells outside the clip are 0 in all four bands, the only way a cell sums to 0."` |
| `:197` print | append clipped counts. |

Coastline length (`:130-141`) is left as it is (clipped to the grid rectangle, not the clip);
the `clip_wkt` helper exists if a later round wants `coastline_km_in_clip`.

Consequence to record: the Unity adapter's `ground()` (`unity.py:145`) hands the remainder to
grass, so a Unity build of a clipped site paints grass under the cut. Unity is not a target
for Thanet; noted, not fixed.

### 3.7 Step 10 `sources/derive/10_furniture.py`

| Location | Change |
|---|---|
| after `:35` | `CLIP = lib.parse_clip(CFG)` |
| `:128` | `buckets, n_amenity, outside, kinds = ...` → add `outside_clip = 0` |
| `:139-141` | after the grid test: `if CLIP is not None and not lib.keep_points(CLIP, e, n): outside_clip += 1; continue` — tested on the **OSM position**, before any kerb nudge (a node just inside the line that is nudged across it is a sub-metre effect and stays). |
| `:158-166` manifest | add only when `CLIP is not None`: `"clip": lib.clip_manifest(CLIP)`, `"outside_clip": outside_clip`. |
| `:168` print | append `outside clip: {outside_clip}`. |

Step 10 reads roads from 06, which are already clipped, so a kept node near the line snaps
only to kept road segments.

---

## 4. Step 11 `sources/derive/11_linear_features.py`

### 4.1 Scope and class lists

Two layers from the GeoPackage `lines` layer, each draped and tiled exactly like roads:

**Railway** — filter `railway IS NOT NULL`; emit ways whose `railway` value is in
`tuning.rail.classes`:

| value | emitted | why |
|---|---|---|
| `rail` | yes | The Chatham Main Line (Birchington–Margate–Broadstairs–Ramsgate) and its Minster/Ashford branch as far as the clip; the reference for the rail profile. |
| `light_rail`, `tram`, `narrow_gauge`, `miniature` | yes | Real track in the ground; none expected in Thanet today, but the class list is config. |
| `disused` | **yes** | OSM's `railway=disused` means track still in place (Ramsgate Harbour branch stubs, sidings). The LIDAR shows the formation; the consumer can render or filter on `cls`. |
| `abandoned`, `razed`, `dismantled` | no | Track removed; the alignment is a footpath or nothing. No geometry to build. |
| `construction`, `proposed` | no | Nothing on the ground. |
| `platform`, `station`, `halt`, `level_crossing`, `signal`, `switch`, `buffer_stop`, `crossing`, `subway_entrance`, … | no | Not track. Counted in `ways_skipped_by_class.railway` so the manifest shows what was seen. |

**Barriers** — filter `barrier IS NOT NULL`; emit ways whose `barrier` value is in
`tuning.barriers.classes`: `wall`, `fence`, `hedge`, `retaining_wall`, `kerb`, `guard_rail`,
`handrail`, `city_wall`. Skipped and counted: `gate`, `bollard` (13 + 13 two-node ways in
Margate; point-like, and their 388 node twins live in `points`), `yes`, `cycle_barrier`, and
anything else. The two barrier features in `multipolygons` are not read; their count is
recorded as `barrier_areas_skipped` (one `SELECT`-free pass: `mp.SetAttributeFilter("barrier IS
NOT NULL")` and count) so the omission is visible.

### 4.2 Record schemas

`networks/rail_x{i}_y{j}.jsonl`, one record per tile run:

```json
{"id":"w123","cls":"rail","gauge":1.435,"gauge_src":"osm","tracks":2,"electrified":"rail",
 "service":null,"usage":"main","bridge":false,"tunnel":false,"name":"Chatham Main Line",
 "z_gap":false,"pts":[[E,N,z],...]}
```

| field | type | meaning |
|---|---|---|
| `id` | string | OSM way id (`osm_id` column). |
| `cls` | string | The OSM `railway` value, verbatim. |
| `gauge` | number, m | OSM `gauge` is millimetres: `"1435"` → `1.435`. `"1435;1000"` (dual gauge) → first value. `"standard"` → 1.435. Unparseable or absent → `tuning.rail.default_gauge_m`. |
| `gauge_src` | `"osm"` \| `"default"` | Which of the above happened. |
| `tracks` | int or null | OSM `tracks` tag (parallel tracks on this way); null if absent. Not defaulted — 1 is the consumer's assumption to make. |
| `electrified` | string or null | Raw OSM value (`no`, `rail` = third rail, `contact_line`, `yes`). Thanet is third-rail 750 V DC; the value is passed, not interpreted. |
| `service` | string or null | Raw (`siding`, `yard`, `spur`, `crossover`). |
| `usage` | string or null | Raw (`main`, `branch`, `industrial`, `tourism`). |
| `bridge`, `tunnel` | bool | Presence of the tag, as roads (`06:130`). Elevation is **not** adjusted. |
| `name` | string or null | `name` column. |
| `z_gap` | bool | As roads (`OUTPUT.md:58`): a vertex of this run fell on a DTM gap and carried its neighbour's elevation. |
| `pts` | `[[E, N, z], ...]` | Draped on the DTM after densify + Chaikin (`tuning.rail`), split per tile with the seam vertex duplicated, cut at the grid edge and the clip. |

`networks/barriers_x{i}_y{j}.jsonl`:

```json
{"id":"w456","cls":"wall","h":0.5,"h_src":"osm","material":null,"fence_type":null,
 "wall":"brick","name":null,"z_gap":false,"pts":[[E,N,z],...]}
```

| field | type | meaning |
|---|---|---|
| `cls` | string | The OSM `barrier` value, verbatim. |
| `h` | number, m | Height above local ground. OSM `height` parsed: first token; unit suffix `m` (default), `cm` (÷100), `mm` (÷1000), `ft`/`'` (×0.3048); `"1.8 m"`, `"15 cm"`, `"2"` all parse. Unparseable or absent → `tuning.barriers.default_height_m[cls]`. |
| `h_src` | `"osm"` \| `"default"` | Which. |
| `material` | string or null | Raw OSM `material` (`brick`, `concrete`, `metal`, `wood`). |
| `fence_type` | string or null | Raw (`railing`, `chain_link`, `wood`, `metal`, `bars`, `hedge`). |
| `wall` | string or null | Raw OSM `wall` (`brick`, `seawall`, `dry_stone`, `flint`). |
| `name` | string or null | |
| `z_gap` | bool | As above. |
| `pts` | `[[E, N, z], ...]` | Draped with `tuning.barriers` (Chaikin **0**: vertices stay on the OSM segments). |

No width is emitted for either layer: ballast/formation width and wall thickness are profile
opinions the Streetscape schema owns, not survey.

### 4.3 Sharing 06's code: decision

Options weighed:

| | shared module, 06 untouched | refactor 06 onto the shared code, gated by byte identity |
|---|---|---|
| Risk to the centimetre regression | none — 06's arithmetic is not edited beyond the clip guard | low but real: any drift in `round`, seam duplication or gap fill shows only in a full Margate re-run |
| Code duplication | `tagval/densify/chaikin/ground/tile_of` and the pass-2 loop exist twice (~70 lines) | none |
| Dry-run proof of equivalence | needed and cheap: rail on a road's polyline must give identical `pts` (§8) | the regress script is the proof |
| Fits BRIEF §4.4 ("06 stays untouched except for clip support") | yes | no |

**Chosen: shared functions in `lib.py` (§2.3), step 06 not refactored in this round.** The
duplication is bounded and covered by the equivalence check; the regression is protected. The
refactor of 06 onto `lib.drape_runs` is a follow-up commit whose acceptance test is
`regress_outputs.sh compare margate` reporting zero differences (§9). `lib.py` rather than a
new `sources/derive/_lines.py` because every step already does `sys.path.insert(0, SOURCES);
import lib` and the module docstring (`lib.py:1-6`) names it as the shared home; a second
import root for one module buys nothing.

### 4.4 Structure of the step

```python
#!/usr/bin/env python3
"""OSM railway and barrier ways -> per-tile draped polylines, beside the roads of step 06.
(docstring: what, why two layers, why Chaikin 0 for barriers, coordinates contract)"""
import glob, json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions(); ogr.UseExceptions()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load(); P = lib.paths(CFG); CLIP = lib.parse_clip(CFG)
OUT = os.path.join(P["out"], "networks"); lib.mkdirs(OUT)
RAIL, BAR = CFG["tuning"]["rail"], CFG["tuning"]["barriers"]

dtm_ds = gdal.Open(os.path.join(P["interim"], "dtm.vrt"))       # same source as 06:44-50
band = dtm_ds.GetRasterBand(1)
DTM = band.ReadAsArray().astype(np.float32)
DTM[lib.nodata_mask(DTM, band.GetNoDataValue())] = np.nan
sample = lib.DtmSampler(DTM, dtm_ds.GetGeoTransform())

def parse_gauge(s): ...        # -> (metres, "osm") or (RAIL["default_gauge_m"], "default")
def parse_height(s, cls): ...  # -> (metres, "osm") or (BAR["default_height_m"][cls], "default")
def as_int(s): ...             # tracks

LAYERS = {
  "rail":     dict(column="railway", classes=set(RAIL["classes"]), tun=RAIL, prefix="rail"),
  "barriers": dict(column="barrier", classes=set(BAR["classes"]), tun=BAR, prefix="barriers"),
}

src = ogr.Open(P["gpkg"]); lyr = src.GetLayer("lines")
summary = {}
for name, L in LAYERS.items():
    lyr.SetAttributeFilter(f"{L['column']} IS NOT NULL")
    buckets, skipped, counters, length, n_default = defaultdict(list), Counter(), {}, 0.0, 0
    for f in lyr:
        cls = f.GetField(L["column"])
        if cls not in L["classes"]: skipped[cls] += 1; continue
        g = f.GetGeometryRef()
        if g is None or g.GetPointCount() < 2: continue
        raw = [(g.GetX(k), g.GetY(k)) for k in range(g.GetPointCount())]
        ot = f.GetField("other_tags")
        rec = build_record(name, f, cls, ot)           # the schema of §4.2 minus z_gap/pts; bumps n_default
        pts = lib.chaikin(lib.densify(raw, L["tun"]["densify_step_m"]), L["tun"]["chaikin_iters"])
        for tile, run, gap in lib.drape_runs(pts, CFG, sample, CLIP, counters):
            buckets[tile].append({**rec, "z_gap": gap, "pts": run})
        for a, b in zip(pts, pts[1:]): length += math.hypot(b[0]-a[0], b[1]-a[1])
    for old in glob.glob(os.path.join(OUT, f"{L['prefix']}_x*_y*.jsonl")): os.remove(old)   # own files only
    n = 0
    for (i, j), items in sorted(buckets.items()):
        with open(os.path.join(OUT, f"{L['prefix']}_x{i}_y{j}.jsonl"), "w") as fh:
            for it in items: fh.write(json.dumps(it, separators=(",", ":")) + "\n"); n += 1
    summary[name] = {...}   # see manifest below
```

Per-layer `build_record`:
* rail: `{"id", "cls", "gauge", "gauge_src", "tracks", "electrified", "service", "usage", "bridge", "tunnel", "name"}` via `lib.tagval(ot, ...)`.
* barriers: `{"id", "cls", "h", "h_src", "material", "fence_type", "wall", "name"}`.

Ways tagged both `highway` and `railway` (street-running tram) appear in roads and rail —
intended.

Zero matching ways (Margate: 0 railway; both synthetic sites A and B: 0 of each) is **not an
error**: the layer writes no tile files, the manifest carries zero counts, and the step prints
`11: NOTE -- no railway ways in the extract; the Overpass query must include way["railway"]
(fetch_osm.sh) and the extract must be re-fetched` when `railway` is empty **and** the
provenance file lacks a `query_sha256` (§5) — the Margate situation.

### 4.5 Manifest `networks/linear_manifest.json`

Separate from `networks_manifest.json` because 06 writes that file wholesale and stays untouched.

```json
{
 "site": "thanet", "crs": "EPSG:27700",
 "coordinates": "[easting, northing, elevation] in CRS metres",
 "origin": {"E": 627680, "N": 163080}, "tile_m": 512,
 "source_layer": "lines (GeoPackage from step 01); barrier areas in multipolygons are not read",
 "layers": {
  "rail": {
   "files": "rail_x{i}_y{j}.jsonl", "column": "railway",
   "classes_emitted": ["rail", "light_rail", "tram", "narrow_gauge", "miniature", "disused"],
   "segments": 0, "tiles": 0, "length_km": 0.0,
   "by_class": {"rail": 0, "disused": 0},
   "smoothing": {"densify_step_m": 8.0, "chaikin_iters": 2},
   "default_gauge_m": 1.435, "gauge_defaulted": 0,
   "vertices_without_dtm": 0, "vertices_outside_grid": 0
  },
  "barriers": {
   "files": "barriers_x{i}_y{j}.jsonl", "column": "barrier",
   "classes_emitted": ["wall", "fence", "hedge", "retaining_wall", "kerb", "guard_rail", "handrail", "city_wall"],
   "segments": 0, "tiles": 0, "length_km": 0.0,
   "by_class": {"wall": 0, "fence": 0},
   "smoothing": {"densify_step_m": 8.0, "chaikin_iters": 0},
   "default_height_m": {"wall": 1.8, "fence": 1.5, "hedge": 1.5, "retaining_wall": 1.5, "kerb": 0.12, "guard_rail": 0.75, "handrail": 1.0, "city_wall": 6.0},
   "height_defaulted": 0,
   "vertices_without_dtm": 0, "vertices_outside_grid": 0
  }
 },
 "ways_skipped_by_class": {"railway": {"platform": 0}, "barrier": {"gate": 13, "bollard": 13, "yes": 2}},
 "barrier_areas_skipped": 2
}
```

Plus, only when a clip exists: top-level `"clip": lib.clip_manifest(CLIP)` and per layer
`"vertices_outside_clip"`. `length_km` is the smoothed polyline length of the emitted classes
(whole ways, as 06 does).

### 4.6 Tuning entries (`sources/config/tuning.json`)

Insert after the `roads` block:

```json
  "rail": {
    "classes": ["rail", "light_rail", "tram", "narrow_gauge", "miniature", "disused"],
    "classes_note": "OSM railway values emitted by step 11 as cls. disused = track still in place (rendered or filtered by the consumer); abandoned/razed/dismantled have no track and are skipped, as are platform/station/signal and other non-track ways. Skipped values are counted in linear_manifest.ways_skipped_by_class.",
    "default_gauge_m": 1.435,
    "default_gauge_note": "Standard gauge (1435 mm), the whole Kent network. OSM gauge is in millimetres and is converted; a way without the tag gets this and gauge_src=default.",
    "densify_step_m": 8.0,
    "chaikin_iters": 2,
    "chaikin_note": "Same presentation choice as roads: OSM rail vertices are sparse on straights and angular on curves; two corner-cutting passes keep the drape from reading as facets. The Streetscape rail profile resamples with curvature-adaptive spacing anyway. Set 0 for OSM-faithful vertices."
  },

  "barriers": {
    "classes": ["wall", "fence", "hedge", "retaining_wall", "kerb", "guard_rail", "handrail", "city_wall"],
    "classes_note": "OSM barrier values emitted by step 11 as cls -- the linear ones. gate and bollard ways (two-node, point-like) and barrier=yes are skipped and counted; barrier nodes live in the points layer and are not step 11's business.",
    "default_height_m": {
      "wall": 1.8, "fence": 1.5, "hedge": 1.5, "retaining_wall": 1.5,
      "kerb": 0.12, "guard_rail": 0.75, "handrail": 1.0, "city_wall": 6.0
    },
    "default_height_note": "OPINIONS, used only when OSM has no height tag (Margate: 15 of 467 barrier ways carry one) and tagged h_src=default. wall 1.8: a UK boundary wall below the 2 m permitted-development limit. fence 1.5: garden fence panel (1.8 is also common; the LIDAR nDSM will say). hedge 1.5: trimmed privet at shoulder height. retaining_wall 1.5: unknowable from tags -- the DTM step across the way is the truth and the consumer should measure it. kerb 0.12: matches furniture.kerb_m, the same physical upstand (BS 7533 kerbs show 100-150 mm). guard_rail 0.75: UK vehicle safety barrier beam height ~0.6-0.8 m. handrail 1.0: Building Regs Approved Document K, 900-1000 mm. city_wall 6.0: placeholder; none in Thanet.",
    "densify_step_m": 8.0,
    "chaikin_iters": 0,
    "chaikin_note": "Zero on purpose: walls and fences are angular by nature -- a garden wall turns a 90 degree corner, it does not round it. Chaikin would move every corner a quarter-span inward and put the wall through the house. Vertices stay exactly on the OSM segments; densification still adds drape points every 8 m."
  },
```

---

## 5. `sources/fetch/fetch_osm.sh` and provenance

### 5.1 Query

Insert after `fetch_osm.sh:26` (`way["highway"]($BBOX);`):

```
  way["railway"]($BBOX);
```

Nothing else is needed for step 11: `way["barrier"]` is already there (`:32`). Relations are
not added (rail routes are relations of ways; the ways carry the geometry and tags).

### 5.2 Record what was asked

The extract's identity is the bbox **and** the query. Today only the bbox is recorded
(`01_fetch_osm.sh:145`), which is why Margate's extract can have zero railway ways with
nothing in provenance saying the query never asked. Changes:

* `fetch_osm.sh`, after the heredoc (`:40`): `printf '%s' "$Q" > "$OUT.query"` — the exact
  query text sent, beside the extract in `data/<site>/raw/` (untracked, like the extract).
* `01_fetch_osm.sh` provenance writer (`:127-151`): pass `"$OSM.query"` in; add fields
  * `"query_sha256"`: sha256 of `$OSM.query` if it exists, else `null`;
  * `"query_selectors"`: sorted unique `grep -oE '(node|way|relation)\[[^]]*\]' "$OSM.query"`
    with `($BBOX)` stripped, if it exists, else `null`;
  * `"query_note"`: `"null query_* means the extract predates query recording; it was fetched by fetch_osm.sh as of commit 0d31c0c, which had no way[\"railway\"]"` when null;
  * `counts` gains `"railway"` and `"barriers"` via two more `ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE railway IS NOT NULL"` / `barrier IS NOT NULL` at `:124-125`.

Implication, stated plainly in the README (§10): **Margate's extract was fetched without
`way["railway"]` and is not re-fetched in this round** — step 01 skips the fetch because the
bbox matches (`01:24-30`), so Margate keeps 0 railway ways and its outputs stay byte-identical.
A future `rm data/margate/raw/margate.osm` + step 01 produces a different extract (Margate
station's line exists) and a new sha256; `query_sha256` will then differ from null, which is
the honest record. Whitby is in the same position.

---

## 6. `sources/run.sh`

### 6.1 Register step 11

`run.sh:38` — append to `STEPS`:

```
  "11:sources/derive/11_linear_features.py:OSM railway + barrier ways -> draped polylines (rail_*, barriers_*)"
```

The string comparison `[ "$NUM" \< "$FROM" ]` (`:81`) orders `"11"` after `"10"` correctly.
Update the header comment `:4` to `01 -> 11` and the closing hint (`:97`) to also print
`for Unreal: SITE=$SITE $PY sources/adapters/unreal.py` (adapter designed separately).

### 6.2 Friendlier `PY` resolution

Replace `run.sh:27` (`PY="${PY:-python3.14}"`) with a probe that rejects interpreters that
exist on PATH but cannot run the pipeline — on this machine `python3` and `python` are the
Microsoft Store stubs, so `command -v` alone (`:53`) would pass and every step would die:

```bash
# PY: an interpreter with numpy and the GDAL bindings. Set PY=<path> to choose one; otherwise
# probe the usual names and REJECT any that cannot import both -- the Microsoft Store
# python/python3 stubs are on PATH on Windows and pass `command -v` while running nothing.
usable() { command -v "$1" >/dev/null 2>&1 && "$1" -c 'import numpy; from osgeo import gdal' >/dev/null 2>&1; }
if [ -z "${PY:-}" ]; then
  for cand in python3.14 python3.13 python3 python; do
    if usable "$cand"; then PY="$cand"; break; fi
  done
  if [ -z "${PY:-}" ]; then
    echo "FATAL: no python with numpy + GDAL bindings found on PATH." >&2
    echo "       Set PY to one, e.g.  PY=/c/path/to/conda-env/python.exe SITE=thanet $0" >&2
    echo "       (the GDAL CLI must be on PATH too: PATH=/c/path/to/conda-env/Library/bin:\$PATH)" >&2
    exit 1
  fi
  echo "PY unset -> $PY"
elif ! usable "$PY"; then
  echo "FATAL: PY=$PY cannot import numpy and osgeo.gdal" >&2; exit 1
fi
export PY          # 01_fetch_osm.sh and 03_build_mosaics.sh read $PY; without export they fall back to python3.14
```

and delete the now-redundant `:53`. `export PY` fixes a latent bug: when `run.sh` resolves
`PY` itself, the `.sh` steps (`01:14`, `03:11`) never saw it. No environment path is
hardcoded; the README documents the invocation for this machine:

```bash
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH \
PY=/c/Users/Shadow/code/3duk-env/env/python.exe \
SITE=thanet ./sources/run.sh
```

`run.sh:60-70` then finds `GDAL_DATA`/`PROJ_DATA` beside `ogr2ogr` as it does today.

---

## 7. Tile reuse: `sources/fetch/reuse_tiles.py`

### 7.1 CLI

```
PY sources/fetch/reuse_tiles.py --from margate --to thanet [--dry-run] [--link]
```

* `--from`, `--to`: site names; both configs are loaded with `lib.load(name)` (not `SITE`).
* `--dry-run`: perform every check and print the plan (`copy 182, skip-outside 0, present 0`), write nothing.
* `--link`: `os.link` instead of `shutil.copyfile` (NTFS hardlinks; saves 728 MB). Default is copy: `data/margate/` must never be modified (BRIEF §4.5) and although the pipeline never writes a raw tile in place (02 deletes and rewrites, `02:56,71`), a copy makes that guarantee independent of future code.

Exit status 0 only if every check passed and every planned file is present and verified.

### 7.2 Checks, in order (each failure is `sys.exit` with the two values printed)

1. `from.crs == to.crs`, `from.tile_m == to.tile_m`, `from.grid_res == to.grid_res`.
2. `from.wcs == to.wcs` as JSON objects (both `dtm` and `dsm`: `url` and `coverage`). Notes keys are stripped before comparing. Different coverage → different pixels → refuse.
3. Alignment: `dE = from.origin.E − to.origin.E`, `dN = from.origin.N − to.origin.N`; require `dE % tile_m == 0` and `dN % tile_m == 0`. `di, dj = dE // tile_m, dN // tile_m` (may be negative). Margate→Thanet: `di = dj = 10`.
4. Source stamp: `data/<from>/raw/lidar/_grid.json` must exist and equal `lib.grid_stamp(from_cfg, lib.parse_clip(from_cfg))` (Margate's has no clip → the four keys, matching the file on disk today).
5. Target stamp: `expected = lib.grid_stamp(to_cfg, lib.parse_clip(to_cfg))`. If `data/<to>/raw/lidar/_grid.json` exists it must equal `expected`; otherwise it is written (after the copies succeed, not before, so an aborted run leaves no stamp claiming a grid). This is byte-for-byte what `02` will compute at `02:32`, so `02` accepts the directory.
6. Per source tile `{dtm,dsm}_x{i}_y{j}.tif` (glob, parse `i, j` from the name):
   * target index `(i2, j2) = (i + di, j + dj)`; if outside `0..to.nx−1 × 0..to.ny−1` → counted `outside_target_grid`, skipped.
   * if `lib.tile_state(to_clip, to_cfg, i2, j2) == "outside"` → counted `outside_clip`, skipped (02 would not fetch it). Margate→Thanet: 0.
   * `info = lib.tiff_info(src)`; require `width == height == grid_res`, `dtype == "float32"`, and **`info["georef_origin"] == (E0_to + i2·T − px/2, N0_to + j2·T + T + px/2)`** with `px = T/(grid_res−1)` (1.0 m) to 1e-6 — the file's own georeferencing must land where the new name says. Margate `x0_y0` → Thanet `x10_y10`: `(627680 + 5120 − 0.5, 163080 + 5120 + 512 + 0.5) = (632799.5, 168712.5)`, which is exactly the tag read from the file (§0.2).
   * destination `data/<to>/raw/lidar/{kind}_x{i2}_y{j2}.tif`: if present and `sha256(dst) == sha256(src)` → `present`; if present and different → FATAL (never silently overwrite a fetched tile); else copy/link, then re-hash the destination and require equality → `copied`.
7. Print the summary `{copied, present, outside_target_grid, outside_clip}` and the mapping rule `(i, j) -> (i+10, j+10)`.

### 7.3 `lib.tiff_info` extension (needed by check 6)

Add to the tag loop (`lib.py:155-162`):

```python
                elif tag == 34264 and typ == 12 and cnt == 16:        # ModelTransformationTag
                    m = struct.unpack(bo + "16d", data)
                    vals["georef_origin"] = (m[3], m[7])
                elif tag == 33922 and typ == 12 and cnt >= 6:          # ModelTiepointTag
                    tp = struct.unpack(bo + f"{cnt}d", data)
                    if tp[0] == 0.0 and tp[1] == 0.0:                 # tiepoint at raster (0, 0)
                        vals["georef_origin"] = (tp[3], tp[4])
```

and `"georef_origin": vals.get("georef_origin")` in the returned dict (`lib.py:164-165`).
Raw EA tiles carry 34264; GDAL-written tiles carry 33922 + 33550 (§0.2) — both handled. The
returned value is the outer corner of pixel (0, 0), i.e. `gt[0], gt[3]`. The dry run's
real-tile check (`dryrun.py:390-394`) gains `info["georef_origin"] == (632799.5, 168712.5)`
when the Margate tile is present.

### 7.4 Expected run for Thanet

`--dry-run`: 182 planned copies, 0 outside grid, 0 outside clip. Real run: 182 copied
(~728 MB, seconds), `_grid.json` written with the clip stamp. Then `SITE=thanet run.sh --only
02` reports `cached: 182`, `skipped_clip: 206`, `ok: 600` (391 positions × 2 − 182), about
4.6 min at the measured 2.2 rasters/s.

---

## 8. `sources/tests/dryrun.py` extension

### 8.1 Harness changes (`synth`, `dryrun.py:56-121`)

* `STEPS` (`:52-53`) gains `"derive/11_linear_features.py"` after `10_furniture.py` and
  `"adapters/unreal.py"` after `unity.py`. Both run for **all three** sites: A and B prove
  the no-railway/no-barrier/no-clip paths, C proves the features.
* `lines` layer field names (`:96`) become `["osm_id", "highway", "railway", "barrier", "name", "other_tags"]`; existing `ways` tuples get `railway=None, barrier=None`.
* New parameters: `rails=()` and `barriers=()` — tuples `(id, value, pts, name, other_tags)` inserted into the same `lines` layer with `highway=None` and `railway`/`barrier` set; `skip_tiles=()` — tile positions for which **no raw `dtm_x{i}_y{j}.tif` is created and the VRT region is set to `ND`**, simulating step 02 having skipped them.
* Decoys (`:70-74`) gain `("networks", "rail_x9_y9.jsonl")` and `("networks", "barriers_x9_y9.jsonl")`.
* `synth` returns unchanged; site configs are written with any extra keys from `cfg_extra` (a `clip` block passes straight through, `:65-67`).
* Cleanup (`:402-404`) removes `_dryrun_c.json` too.

### 8.2 Site C: coastal-free, 1 m, diagonal clip

```python
E0c, N0c, NXc, NYc, RESc = 700000, 300000, 3, 2, 513
CLIP_C = {"type": "halfplane", "line": [[E0c, N0c + 1100], [E0c + 1100, N0c]], "keep": "left"}
# kept iff (x - 0)*1100 + (y - 1100)*1100 >= 0  <=>  x + y >= 1100 in local metres: north-east of the diagonal
def zC(EE, NN): return 20.0 + 0.01 * (EE - E0c) + 0.02 * (NN - N0c)          # a plane, 20 .. 55.84 m
def zc_at(e, n): return 20.0 + 0.01 * (e - E0c) + 0.02 * (n - N0c)
```

Tile states (verified §0.2): `(0,0)` **outside**; `(0,1) (1,0) (1,1) (2,0)` **straddle**;
`(2,1)` **inside**. Clipped 1 m cells: `(1,0)` and `(0,1)` **167,466** of 263,169; `(1,1)` and
`(2,0)` **2,926**; `(2,1)` 0. Clipped 2 m class cells: `(1,0)` **41,665**, `(1,1)` **703**.

Features (local offsets from `E0c, N0c`):

| kind | id | value | geometry | tags | purpose |
|---|---|---|---|---|---|
| way | `rd1` | `residential` | `(700,100) → (700,900)` | — | crosses the clip line at y=400 and the seam at y=512 |
| way | `rd2` | `residential` | `(100,100) → (300,100)` | — | wholly outside |
| way | `rd3` | `footway` | `(100,100) → (100,300)` | — | third way at outside junction `(100,100)` |
| way | `rd4` | `service` | `(100,100) → (300,300)` | — | idem |
| way | `rd5` | `tertiary` | `(1100,800) → (1300,800)` | — | inside junction `(1300,800)` |
| way | `rd6` | `tertiary` | `(1300,800) → (1500,800)` | — | idem |
| way | `rd7` | `footway` | `(1300,800) → (1300,1000)` | — | idem |
| rail | `rl1` | `rail` | same as `rd1` | `"gauge"=>"1435","electrified"=>"rail","usage"=>"main","tracks"=>"2"` | equivalence with 06 |
| rail | `rl2` | `disused` | `(1200,600) → (1400,700)` | — | default gauge |
| rail | `rl3` | `platform` | `(1210,610) → (1220,610)` | — | skipped class |
| rail | `rl4` | `rail` | `(50,50) → (150,50)` | — | wholly outside |
| barrier | `bw1` | `wall` | `(1100,600) → (1100,700)` | `"height"=>"0.5","wall"=>"brick"` | OSM height, Chaikin 0 |
| barrier | `bf1` | `fence` | `(1200,900) → (1300,900)` | `"fence_type"=>"chain_link","material"=>"metal"` | default height |
| barrier | `bk1` | `kerb` | `(1400,900) → (1450,900)` | `"height"=>"15 cm"` | unit parsing |
| barrier | `bh1` | `hedge` | `(400,400) → (800,800)` | — | crosses the line (800 → 1600) |
| barrier | `bg1` | `gate` | `(1200,950) → (1202,950)` | — | skipped class |
| building | `cb1` | house | `rect(1200,700,10,8)`, stats `(4,6,8,40,46.1,45.9)` (ground = plane at the centroid) | `"building:levels"=>"2"` | kept |
| building | `cb2` | house | `rect(100,200,10,8)`, stats `(4,6,8,40,25.1,24.9)` | — | centroid outside |
| node | `cn1` | waste_basket | `(705, 800)` | | inside, on `rd1`'s pavement |
| node | `cn2` | waste_basket | `(150, 105)` | | outside |

Config extra: `origin`, `clip: CLIP_C`, `water_level: -50.0`, `height_calib` fixed
`{intercept 2.5, m_per_level 3.0}`, `coast {foreshore_max_odn -50, rock_slope_deg [25,45],
water_margin_m 0.75}`, `landmarks {}`; `px=1, RES=513, NX=3, NY=2, skip_tiles=((0,0),),
decoys=True`.

### 8.3 New `check()` names

lib (pure functions, run before the site):

* `C-lib parse_clip: absent block -> None; unknown type refuses`
* `C-lib tile_state on the diagonal: (0,0) outside, (2,1) inside, the other four straddle`
* `C-lib keep_points: vectorised; on-line points kept; keep=right is the mirror`
* `C-lib cell_mask at pixel centres: tile (1,0) clips 167466 of 263169; clip None -> all True`
* `C-lib clip_wkt: straddle tile gives a 5-corner polygon, inside tile the rectangle, outside tile None`
* `C-lib grid_stamp: four keys without a clip, five with`
* `C-lib drape_runs == 06 arithmetic: seam duplicated, off-grid closes run, off-clip closes run`

step 05:

* `C05 outside tile (0,0): no file, listed in tiles_clipped, NOT in tiles_missing`
* `C05 straddle tile (1,0): clipped cells are the declared NoData and number 167466 == clipped_cells`
* `C05 straddle cells: SW corner NoData, NE corner real ground, kept cells untouched vs the plane`
* `C05 inside tile (2,1): clipped_cells 0, no NoData cell, clip_state inside`
* `C05 NoData declared on every tile of the clipped site; nodata recorded in the manifest`
* `C05 range_m and slope_qa from kept cells only`
* `C05 manifest clip block: type halfplane, line, keep left`

step 06:

* `C06 way crossing the line is cut at its last kept vertex: all pts satisfy x+y >= 1100, first pt within 12 m of the line`
* `C06 wholly outside way dropped; vertices_outside_clip > 0, vertices_outside_grid == 0`
* `C06 off-clip vertices are not counted as DTM gaps (vertices_without_dtm == 0)`
* `C06 kept part of rd1 still splits at the seam into tiles (1,0) and (1,1)`
* `C06 junction outside the clip dropped and counted; inside junction kept`
* `C06 manifest records clip`

step 07:

* `C07 building with centroid outside dropped, outside_clip 1; inside building kept`

step 09:

* `C09 outside tile: no raster, listed in tiles_clipped, not in tiles_without_dtm`
* `C09 straddle tile (1,0): all four bands zero on exactly 41665 cells; bands sum to 255 everywhere else`
* `C09 clipped_cells total == sum of zero-sum cells across tiles; inside tile has none`
* `C09 manifest records clip and bands_note`

step 10:

* `C10 furniture node outside dropped and counted outside_clip; inside node placed on rd1`

step 11:

* `C11 rail on a road's polyline gives IDENTICAL pts and z_gap per tile (shared densify/chaikin/drape/split/clip)`
* `C11 rail fields: gauge 1.435 from "1435" (osm), tracks 2, electrified rail, usage main, bridge/tunnel False`
* `C11 disused rail: default gauge 1.435, gauge_src default; platform skipped and counted`
* `C11 wholly outside rail dropped; rail layer counts vertices_outside_clip`
* `C11 wall: h 0.5 (osm), wall brick, material null; fence: h 1.5 (default), fence_type chain_link`
* `C11 barrier Chaikin 0: every vertex of bw1 has E exactly E0c+1100`
* `C11 kerb height "15 cm" -> 0.15`
* `C11 hedge crossing the line is cut; gate way skipped and counted`
* `C11 manifest: two layers with counts, smoothing, defaults, skipped classes, clip`
* `C11 stale rail/barrier decoys cleared; roads files untouched by 11`
* `A11 no railway or barrier ways: no files, zero counts, no crash` and `B11 …`
* `A   clipless site: no clip keys in any manifest, no NoData tag on terrain tiles` (backward compatibility)

adapter (contract assumed, see §12):

* `C-unreal adapter runs on the clipped site; unreal_manifest round-trips origin and tile_m`
* `A-unreal adapter runs on a clipless site`

Real-tile checks (only when `data/margate` exists): extend `dryrun.py:390-394` with
`info["georef_origin"] == (632799.5, 168712.5)`.

Expected total: 86 today + ~40 new.

### 8.4 Expected values worth pinning

* `tm["tiles_clipped"] == [[0, 0]]`, `tm["tiles_missing"] == []`.
* Tile `(1,0)`: `lib.nodata_mask(a, band.GetNoDataValue()).sum() == 167466`; `a[512, 0]` is NoData (local `(512, 0)`, `x+y = 512`); `a[0, 512]` equals `zc_at(E0c+1024, N0c+512)` (local `(1024, 512)`, kept).
* `rd1`: kept vertices have local `y ≥ 400` (`x = 700`); the first emitted vertex's `y` is in `[400, 412)`.
* `nm["junctions"] == 1`, `nm["junctions_outside_clip"] == 1`.
* `mm["outside_clip"] == 1`, `len(buildings) == 1`.
* `cm["tiles_clipped"] == [[0, 0]]`, zero-sum cells on `ground_x1_y0.tif` == 41665.
* `qf["outside_clip"] == 1`, placed `["cn1"]`.
* rail `rl1` per-tile records `== ` road `rd1` per-tile records on `pts` and `z_gap` (compare after sorting by first vertex).

---

## 9. Margate byte-identity procedure

### 9.1 `sources/tests/regress_outputs.sh`

```bash
#!/bin/bash
# Prove a pipeline edit did not change a site's products.
#   regress_outputs.sh snapshot <site> <label>   hash every file under data/<site>/out -> data/<site>/regress/<label>.sha256
#   regress_outputs.sh compare  <site> <label>   re-hash and diff against the snapshot
# compare exits 1 on any CHANGED or REMOVED file; ADDED files are listed and allowed only if
# they match the patterns in ALLOW_NEW (new products of a new step are expected; a changed
# old product is a regression). Manifests are included: none of them carries a timestamp.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="$1"; SITE="$2"; LABEL="${3:-before}"
OUT="$ROOT/data/$SITE/out"; REG="$ROOT/data/$SITE/regress"; mkdir -p "$REG"
ALLOW_NEW='^(networks/(rail|barriers)_x[0-9]+_y[0-9]+\.jsonl|networks/linear_manifest\.json|unreal/.*)$'
hash_tree() { (cd "$OUT" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs -d '\n' sha256sum); }
case "$MODE" in
  snapshot) hash_tree > "$REG/$LABEL.sha256"; echo "$(wc -l < "$REG/$LABEL.sha256") files hashed -> $REG/$LABEL.sha256" ;;
  compare)
    hash_tree > "$REG/$LABEL.now.sha256"
    join -j 2 -a 1 -a 2 -e MISSING -o '0,1.1,2.1' \
      <(LC_ALL=C sort -k2 "$REG/$LABEL.sha256") <(LC_ALL=C sort -k2 "$REG/$LABEL.now.sha256") \
      | awk -v allow="$ALLOW_NEW" '
        $2=="MISSING" { if ($1 ~ allow) {added++} else {bad++; print "ADDED (unexpected) " $1}; next }
        $3=="MISSING" { bad++; print "REMOVED " $1; next }
        $2!=$3        { bad++; print "CHANGED " $1; next }
        { same++ }
        END { printf "%d identical, %d added (allowed), %d problems\n", same, added, bad; exit bad>0 }' ;;
  *) echo "usage: $0 snapshot|compare <site> [label]" >&2; exit 2 ;;
esac
```

`data/<site>/regress/` is under the untracked `data/`, so snapshots never enter git.

### 9.2 Procedure

1. **Before any edit** (first thing in the implementation phase):
   `./sources/tests/regress_outputs.sh snapshot margate before` → 92 terrain + 82 networks + 70 massing + coast + furniture + qa + unity files.
2. Make all edits of §2–§6.
3. Re-run the derived steps on Margate — configs untouched, interim untouched:
   `PATH=… PY=… SITE=margate ./sources/run.sh --from 05` (05, 06, 07, 09, 10, **11**), then
   `SITE=margate $PY sources/adapters/unity.py`.
4. `./sources/tests/regress_outputs.sh compare margate before`.

Expected result: **0 CHANGED, 0 REMOVED**. Added and allowed: `networks/linear_manifest.json`
and `networks/barriers_x*_y*.jsonl` (Margate has 467 barrier ways in the emitted classes minus
gate/bollard/yes — expect files in most inhabited tiles); **no** `rail_*` files (0 railway
ways). If the Unreal adapter is also run, `unreal/**` is allowed too.

### 9.3 Which manifests legitimately change

Under the §3.0 rule **none of Margate's existing files change**, manifests included, because
every clip key is emitted only when a clip exists and the NoData tag is set only when a clip
exists. The manifests that **would** gain keys for a clipped site (Thanet), and therefore must
be read with `.get()`:

| manifest | new keys (clipped sites only) |
|---|---|
| `terrain/terrain_manifest.json` | `nodata`, `clip`, `tiles_clipped`, `clipped_cells_total`, `clip_note`; per tile `clip_state`, `clipped_cells` |
| `networks/networks_manifest.json` | `clip`, `vertices_outside_clip`, `junctions_outside_clip` |
| `massing/massing_manifest.json` | `clip`, `outside_clip` |
| `coast/coast_manifest.json` | `clip`, `tiles_clipped`, `clipped_cells`, `bands_note` |
| `qa_furniture.json` | `clip`, `outside_clip` |
| `networks/linear_manifest.json` | new file (all sites); `clip` and per-layer `vertices_outside_clip` for clipped sites |
| `raw/lidar/_grid.json` | `clip` (clipped sites only; Margate's stamp unchanged) |

If an implementer prefers always-present keys (`"clip": null`), that is a schema decision to
take **after** the byte-identity run, in its own commit, with the compare re-run and the
changed manifests listed there — not folded into this change.

### 9.4 Whitby

Not re-run in this round (no `data/whitby/out` regression baseline is needed for Thanet), but
the same two commands apply verbatim with `whitby`.

---

## 10. `sources/OUTPUT.md` and `README.md` deltas

### 10.1 `OUTPUT.md`

* In the conventions table (`OUTPUT.md:8-18`), add a row **`Clip`**: "A site config may carry an
  optional `clip` block (Thanet: the half-plane north-east of the Minnis Bay → Pegwell Bay
  line). Every manifest of a clipped site records it under `clip` (`type`, `line`, `keep`,
  `semantics`); a manifest without a `clip` key is an unclipped site and nothing below about
  clipping applies. Rasters are clipped at cell centres; vertices, footprint centroids and
  nodes at their positions; points exactly on the line are kept."
* `terrain/` section, after "Nodata has been **filled**…" (`:25-27`): "**Except** cells outside the
  site's clip: they are written as the band's declared NoData (`terrain_manifest.nodata`,
  −9999) **after** the fill, so a NoData cell is a deliberate absence — the model ends here —
  and never a coverage gap. `clipped_cells` per tile counts them; `clip_state` says whether
  the tile is `inside` or `straddle`. Grid positions wholly outside the clip have no file and
  are listed as `tiles_clipped`, distinct from `tiles_missing` (no source data). A consumer
  renders NoData as a hole (Unreal: the landscape visibility layer), not as ground."
* `terrain/` `slope_qa` paragraph (`:35-41`): add "For a clipped site `range_m` and `slope_qa`
  describe kept cells only."
* `networks/` section, after the grid-clipping sentence (`:64-66`): "Likewise a way that crosses
  the clip line ends at its last kept smoothed vertex (within ~12 m of the line at the
  default smoothing); `vertices_outside_clip` and `junctions_outside_clip` are counted, and off-clip
  vertices are not DTM gaps."
* New subsection **`networks/` — step 11** after the roads subsection: the two record schemas
  and field tables of §4.2 verbatim, plus: "`linear_manifest.json` is step 11's manifest
  (`networks_manifest.json` stays step 06's). `default_gauge_m` and `default_height_m` are
  opinions from `tuning.json`; records that used them say so in `gauge_src` / `h_src`.
  `ways_skipped_by_class` lists every `railway` / `barrier` value seen but not emitted;
  `barrier_areas_skipped` counts closed barrier outlines in `multipolygons`, which are not read."
* `massing/` manifest paragraph (`:92-100`): add "`outside_clip` counts footprints whose centroid
  lies outside the clip; they are not emitted."
* `coast/` first paragraph (`:104-108`): replace "as fractions 0–255 that sum to 255" with "as
  fractions 0–255 that sum to 255 **for every cell inside the site's clip; a cell outside the
  clip is 0 in all four bands (sum 0), and that is the only way a cell sums to 0**". Add to
  the manifest paragraph (`:123-125`): "`tiles_clipped` lists grid positions wholly outside the
  clip (no raster; distinct from `tiles_without_dtm`), `clipped_cells` counts zeroed cells."
* `furniture/` (`:127-145`): add "`qa_furniture.json` counts `outside_clip` nodes; they are not
  placed."
* "Writing an adapter" (`:152-157`): add "Honour `clip`: treat terrain NoData as absence, not
  elevation; expect ground-cover cells that sum to 0; expect rail and barrier layers beside
  roads."

### 10.2 `README.md`

* Tree (`README.md:12-23`): `derive/` line becomes "03-11 mosaics, heights, terrain, roads,
  massing, ground cover, street furniture, **railway + barrier polylines**"; `fetch/` line
  gains "`reuse_tiles.py` copies another site's LIDAR tiles into an aligned grid";
  `tests/` (add a line) "`dryrun.py` fake-GDAL run of 05–11 + adapters on three synthetic sites;
  `regress_outputs.sh` byte-identity of a site's products".
* Rebuilding (`:26-36`): after the code block, add the invocation for a conda GDAL environment
  on Windows (the §6.2 three-line command) and: "`PY` is probed if unset (`python3.14`,
  `python3.13`, `python3`, `python`, first one that imports numpy and `osgeo.gdal`); the
  Microsoft Store `python` stubs are rejected."
* Sites (`:41-46`): add **thanet**: "the whole Isle of Thanet, 26×19 tiles, cut by a hard line
  from Minnis Bay to Pegwell Bay (`clip` in its config): tiles wholly south-west of the line
  are not fetched, cells beyond it are NoData, features beyond it are dropped and counted.
  Its calibration is Margate's, inherited with notes, re-fitted from its own buildings by
  step 07. Margate's grid is a sub-grid (`(i, j) → (i+10, j+10)`), so its 182 rasters are
  copied in by `sources/fetch/reuse_tiles.py --from margate --to thanet` instead of re-fetched."
* Adding a site (`:48-54`): add a paragraph "**A clip is the one feature that is legitimately a
  step-wide change** — it is opt-in through the site config, implemented once in `lib.py`
  (`parse_clip`, `keep_points`, `tile_state`, `cell_mask`), recorded in every manifest it
  touches, and a config without it produces byte-identical output (proved by
  `sources/tests/regress_outputs.sh`)."
* Output table (`:129-135`): add row "| 11 | `networks/rail_x*_y*.jsonl`, `networks/barriers_x*_y*.jsonl` — railway and barrier ways draped on the DTM: gauge/electrified/service/usage, or height/material/fence_type/wall |".
* Sources and licensing (`:122-125`): add "The Overpass query is part of the extract's
  identity: `fetch_osm.sh` writes the query it sent beside the extract and step 01 records its
  sha256 and selectors in provenance. **Margate's and Whitby's extracts were fetched before
  `way["railway"]` was in the query** (their provenance says `query_sha256: null`); they hold
  no railway ways until re-fetched, which would also change every OSM-derived product."
* Checking without GDAL (`:141-154`): "three synthetic sites … the third has a clip line
  crossing the grid diagonally and rail/barrier ways, and runs step 11 and the Unreal adapter".
* Regression (`:84-100`): add "`sources/tests/regress_outputs.sh snapshot|compare <site>
  <label>` is the standing procedure: snapshot before an edit, re-run `--from 05`, compare —
  zero changed files or the edit is not done."

---

## 11. Risks, ordered

1. **Byte-identity of 05/06/09 is easy to lose in small ways.** Any unconditional `SetNoDataValue`,
   an unconditional `"clip": None` key, a changed `json.dump` key order, or a refactor of 06 onto
   `lib.drape_runs` "while we are there" breaks §9. Mitigation: the §3.0 guard pattern, the
   regress snapshot taken **before** the first edit, and the rule that the 06 refactor is a
   separate commit.
2. **Rail is absent until Thanet is fetched.** No site on disk has railway ways, so step 11's rail
   path is exercised only by the synthetic site until step 01 runs for Thanet. The dry-run's
   equivalence check covers the arithmetic; the first real run must be inspected (Birchington–
   Ramsgate line continuous, `gauge_defaulted` small, `by_class.rail` plausible).
3. **A ~45 MB Overpass extract may time out or 504.** `fetch_osm.sh` retries three times per
   endpoint with growing pauses (`:42-62`), but only `overpass-api.de` answered on 2026-09-07. If
   it fails, split is not an option (one extract per site is the contract); wait and retry, or
   raise `[timeout:600]` (`:22`) to 900 in the same edit.
4. **Straddle-tile edge and the Unreal hole mask must agree.** 05 clips at 1 m cell centres with
   `≥ 0`; the Unreal importer cuts the visibility layer along the same line from the manifest's
   `clip` block (BRIEF §4.4, `Runtime/Landscape/Classes/LandscapeProxy.h:1002`
   `VisibilityLayer`). If the importer derives its mask from the NoData cells instead, the edge is
   a 1 m staircase; if from the line, it is exact but must use identical semantics (`≥ 0`,
   `keep left`). The adapter should emit both (mask from NoData for verification, the line for the
   cut) and the design for `unreal.py` must say which the importer uses.
5. **`length_km` and calibration include beyond-line geometry.** Deliberate (§3.4, §3.2), but a
   reader of `networks_manifest.length_km` for Thanet will over-read the road length by the
   mainland portion inside the bbox; the manifest note should say so if it matters.
6. **Memory in 09 for Thanet.** The mosaic is 12801×9729 float32 (498 MB) plus `Af`, `dz`, `sand`,
   `rock`, `water` and the gradient pair — roughly 3.5 GB peak, as today's design already
   implies at this size; the per-tile clip masks add nothing material. 28 GB RAM suffices, but
   09 should be run alone, not alongside an Unreal build.
7. **Hardlink option.** `--link` shares inodes with `data/margate/raw/lidar`; safe against the
   pipeline's own operations (02 only deletes/rewrites) but not against a hand edit. Default is
   copy; the flag is documented as "only if disk is short".
8. **Fake-GDAL blind spots.** The dry run's `Intersection` is envelope-based and rasterisation is
   envelope-fill (`fake_osgeo:76-92, 136-141`); `clip_wkt` is therefore only unit-tested on its
   own output, not through OGR. Acceptable: no step depends on `clip_wkt`.
9. **Provenance rewrite on every step-01 run.** `01:127-151` rewrites `sources/provenance/<site>.osm.json`
   (tracked) with a fresh `recorded_utc` even when the fetch is skipped; adding `query_*` fields
   means the next Margate run of 01 dirties that file with `query_sha256: null`. Harmless and
   honest; commit it or don't run 01 for Margate.
10. **`disused` inclusion is a judgement.** If Thanet's `railway=disused` ways turn out to be mapped
    alignments without visible formation, drop the value from `tuning.rail.classes` — config, not
    code.

---

## 12. Contracts assumed from the other subsystems

* **Unreal adapter** (`sources/adapters/unreal.py`, designed separately) writes into
  `data/<site>/out/unreal/` and a manifest **`data/<site>/out/unreal/unreal_manifest.json`**
  carrying at least `origin` (`{E, N}`), `tile_m`, `crs`, `vertical_datum`, and the frame
  statement of BRIEF §4.2. The dry run runs it via `runpy.run_path(..., run_name="__main__")`
  on all three synthetic sites under the fake GDAL with numpy only — so it must not import
  scipy/PIL, must tolerate `clip` absent, must read terrain NoData via the band's declared
  value (`lib.nodata_mask(a, band.GetNoDataValue())`), must treat ground-cover cells summing to
  0 as outside, and must read `networks/rail_*.jsonl` / `networks/barriers_*.jsonl` with the
  §4.2 fields (`cls`, `gauge`, `h`, …) for Streetscape JSON splines with `source: {"osm_id": id,
  "layer": "roads"|"rail"|"barriers"}`.
* **Unreal landscape importer** cuts the hole along `terrain_manifest.clip.line` with
  `terrain_manifest.clip.keep` semantics (`ALandscapeProxy::VisibilityLayer`,
  `Runtime/Landscape/Classes/LandscapeProxy.h:1002`), and may verify against the NoData cells;
  height encoding per `Runtime/Landscape/Public/LandscapeDataAccess.h:13` (`LANDSCAPE_ZSCALE
  1/128`) is the adapter's concern, not the pipeline's.
* **Streetscape schema** consumes `gauge` (m), `tracks`, `electrified`, `h` (m), `cls` as profile
  selectors; the pipeline promises those names and units and nothing about widths.
