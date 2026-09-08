# Pipeline changes for Thanet — normative (clip, step 11, tile reuse, tests, the Unreal adapter)

Supersedes `docs/design/pipeline.md` and Part A of `docs/design/adapter_and_test_stretch.md` with the
critique fixes folded in (§0). Repo facts are cited as `path:line` against branch `thanet-explorer` at
commit `0d31c0c` (working tree 2026-09-08). Python is always
`C:/Users/Shadow/code/3duk-env/env/python.exe` (`PY` below). Nothing here has been run; the
implementation phase runs everything in §9 and §13.10 and records the output in STAGES.md.

Ownership (BRIEF 7): sections 1–10 belong to the **pipeline task**, section 13 to the **adapter task**;
the shared touch points (`lib.py`, `run.sh`, `OUTPUT.md`, `dryrun.py`, root `.gitignore`) are the
pipeline task's, and the adapter task requests its `dryrun.py` hook (§8.3) and `OUTPUT.md` sentence
(§10.1) from it.

---

## 0. What changed from the two designs

pipeline.md: the clip line is the **OSTN15** pair `[[628512, 169680], [635496, 163609]]` everywhere
(the Helmert pair the design used is forbidden by BRIEF 4.1); the straddle-tile NoData count is
**3,861,822** of 8,158,239 (recomputed); `grid_stamp` keeps its four keys and 02 writes
`_fetch_clip.json` instead (§3.1); `regress_outputs.sh` normalises `sha256sum`'s `*` binary marker (§9.1)
and the expected file counts are corrected; step 09's contract is "bands sum to 252–255 inside, 0
outside" (§3.6); `clip_manifest.semantics` says "footprint envelope centre (07)"; `budget_note` is
reworded and pinned by a dry-run check (§8.3); the 02 banner is corrected (§3.1); 06 stays duplicated
(DESIGN.md 19) with the C11 equivalence check as the drift guard; no `road_tags.jsonl` (DESIGN.md 19).
adapter design: weights accepted at 252–255 with a histogram (§13.3); Streetscape documents follow the
schema verbatim (§13.5); no `z`/`roll_deg` on points; `chain_segments` ordered along the raw way with
gaps and loops (§13.6); overlays clipped (§13.9); thinning measured against the Catmull-Rom at 0.10 m
(§13.7); `vis_*.r8` visibility product (§13.3); manifest skeletons (§13.11); `heading ∈ [−180, 180)`;
h16 example 32817/35673 from the array; `ue_import_unpadded`; service roads keep a kerb; barrier
splines centred; `edge_uk_kerb_grass` → `edge_uk_half_grass`; `kerb_only` removed; `lib.tagval`
imported, not copied; B1 counts 1,067 / 43, chord deviation 11.1 m.

---

## 1. `sources/config/sites/thanet.json` — full text

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
    "line": [[628512, 169680], [635496, 163609]],
    "keep": "left",
    "note": "The Isle of Thanet is cut from the mainland by a hard straight line along the old Wantsum Channel. A point P is KEPT iff cross(B-A, P-A) >= 0, i.e. (P-A) . (6071, 6984) >= 0 -- the half-plane on the LEFT of A->B, which is north-east. Points exactly on the line are kept. Step 02 does not fetch tiles wholly outside; step 05 writes nodata (not filled) for cells outside; steps 06/07/09/10/11 drop and count. Endpoints are config, not code: move them and rebuild.",
    "endpoints_note": "A = Minnis Bay (OSM natural=bay node, 51.38015 N 1.28241 E). B = Pegwell Bay (OSM place=locality node, 51.32281 N 1.37858 E). Both reprojected through the OSTN15 grid (PROJ_NETWORK=ON cs2cs EPSG:4326 EPSG:27700), the same operation step 01 uses. The Helmert fallback gives 628514/169681 and 635498/163610, about 2 m away, and MUST NOT be used (dryrun.py check 'C-lib thanet.json clip.line == BRIEF 4.1'). 9,254 m, bearing 131 deg A->B. Verified kept: Margate, Birchington station, Manston, Ramsgate harbour, North Foreland. Verified excluded: Minster, Cliffsend.",
    "budget_note": "Against this 26x19 grid, by tile corners: 360 tiles inside, 31 straddle, 103 outside -> 391 tiles fetched (782 rasters); 3,861,822 of the 8,158,239 cell centres of the straddle tiles lie outside and are written as NoData by step 05. Recomputed by dryrun.py check 'C-lib tile_state / cell_mask on the Thanet grid' against this file."
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
    "note": "mode auto: step 07 regresses height = intercept + m_per_level * building:levels from THANET's own buildings that carry both a levels tag and a trustworthy LIDAR p50, records the fit in massing_manifest.json, and uses it. The fallback is Margate's FITTED line (n=1457, 83 rejected, rmse 1.4 m, measured 2026-09-07 on this same survey). With ~4x Margate's building stock the fit will engage; the manifest says source=fitted if it did."
  },

  "coast": {
    "foreshore_max_odn": 1.2,
    "rock_slope_deg": [22.0, 40.0],
    "water_margin_m": 0.75,
    "water_tolerance_m": 0.3,
    "missing_tiles_are_water": false,
    "note": "INHERITED FROM MARGATE. foreshore_max_odn is a property of the survey's tide state: the EA flew this stretch at low tide, so the intertidal flat reads as land and anything below 1.2 m ODN is sand. rock_slope_deg is the ramp tuned to the Cliftonville chalk cliffs; Thanet is the same chalk from Birchington round North Foreland to Ramsgate. missing_tiles_are_water false: the composite carried 100% coverage over the sea at Margate and Whitby; if the first run lists missing tiles in the open sea set this true rather than assuming. Clipped tiles (outside the Wantsum line) are NOT missing tiles -- they are listed separately as tiles_clipped."
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

  "lidar_reuse_note": "Before step 02: PY sources/fetch/reuse_tiles.py --from margate --to thanet. It proves both grids are 512-aligned with identical tile_m, grid_res, crs and WCS coverages, copies data/margate/raw/lidar/{dtm,dsm}_x{i}_y{j}.tif to data/thanet/raw/lidar/{dtm,dsm}_x{i+10}_y{j+10}.tif after checking each file's own georeferencing tag lands where the new name says, and writes the four-key _grid.json stamp so step 02 accepts the directory and fetches only the remaining 300 tile positions.",

  "landmarks": {
    "_note": "INHERITED FROM MARGATE (both are on the isle). Hand-authored overrides for buildings the LIDAR p50 estimator gets wrong, keyed by OSM name; step 07 reports how many applied. Do NOT pre-add Ramsgate or Broadstairs landmarks: qa_height_outliers.json from the first Thanet run decides whether the Royal Harbour buildings, Bleak House or the Granville need one.",
    "Arlington House": { "h_body": 57.0, "roof": "flat", "tier": "hero", "why": "18-storey tower on a large podium; p50 samples the podium (7.0m from 22px). Real height ~57m." },
    "Jubilee Clock Tower": { "h_body": 24.0, "roof": "tower", "tier": "hero", "why": "Tiny footprint (7px) undersamples the tower. Real height ~24m." }
  }
}
```

The WCS `url`/`coverage` values are copied from `sources/config/sites/margate.json` at implementation
time (the values above are the design's transcription; `reuse_tiles.py` check 2 catches any drift).

---

## 2. `lib.py` — the clip API and the shared line geometry

### 2.1 Placement and principles

New section `# ---- clip region ----` after `nodata_mask` (`sources/lib.py:110-118`) and before the
TIFF-header section (`:121`); `# ---- line geometry ----` after it. Rules: steps call only the
module-level functions; every function accepts `clip=None` and answers "kept" (`keep_points` → all
True, `tile_state` → `'inside'`, `cell_mask` → all True, `clip_wkt` → the bbox rectangle,
`clip_manifest` → `None`, `grid_stamp` → the four keys); **no step writes a different byte when the
clip is None** (clip keys under `if CLIP is not None`, NoData tag only with a clip); float64 half-plane
test on raw eastings; ties kept; north-up geotransforms only.

### 2.2 Code (verbatim into `lib.py`)

```python
# ---- clip region ------------------------------------------------------------
# An optional `clip` block in the site config restricts the model to a region inside the tile grid
# (Thanet: the half-plane north-east of the Minnis Bay -> Pegwell Bay line). Steps ask three questions
# -- is this point kept, what is this tile's state, which cells of this raster are kept -- through the
# module-level functions below and never look inside the clip object. With no clip block every
# function answers "kept", and no step writes a different byte.

class HalfPlaneClip:
    """Keep one side of the infinite line through A and B. keep 'left': keep P iff cross(B-A, P-A) >= 0.
    'right' negates the test. Points exactly on the line are kept."""
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
        return {"type": self.type, "line": [list(self.a), list(self.b)], "keep": self.keep}

    def keep_points(self, E, N):
        import numpy as np
        E = np.asarray(E, dtype=np.float64); N = np.asarray(N, dtype=np.float64)
        return (E - self.a[0]) * self.n[0] + (N - self.a[1]) * self.n[1] >= 0.0

    def signed_distance_out(self, E, N):
        """Metres INTO the clipped half-plane (positive = cut, negative = kept); used by the Unreal
        adapter for the landscape visibility weight."""
        import numpy as np, math
        E = np.asarray(E, dtype=np.float64); N = np.asarray(N, dtype=np.float64)
        return -((E - self.a[0]) * self.n[0] + (N - self.a[1]) * self.n[1]) / math.hypot(*self.n)

    def rect_state(self, e0, n0, e1, n1):
        k = self.keep_points([e0, e1, e0, e1], [n0, n0, n1, n1])
        return "inside" if k.all() else ("outside" if not k.any() else "straddle")

    def rect_polygon(self, e0, n0, e1, n1):
        poly = [(e0, n0), (e1, n0), (e1, n1), (e0, n1)]
        f = lambda p: (p[0] - self.a[0]) * self.n[0] + (p[1] - self.a[1]) * self.n[1]
        out = []
        for i in range(4):
            p, q = poly[i], poly[(i + 1) % 4]
            fp, fq = f(p), f(q)
            if fp >= 0.0: out.append(p)
            if (fp >= 0.0) != (fq >= 0.0):
                t = fp / (fp - fq)
                out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        return out + [out[0]] if len(out) >= 3 else []


_CLIP_TYPES = {"halfplane": HalfPlaneClip}


def parse_clip(cfg):
    blk = cfg.get("clip")
    if not blk: return None
    t = blk.get("type")
    if t not in _CLIP_TYPES:
        sys.exit(f"clip.type {t!r} not supported (known: {', '.join(sorted(_CLIP_TYPES))})")
    return _CLIP_TYPES[t](blk)


def keep_points(clip, E, N):
    import numpy as np
    if clip is None:
        return np.ones(np.broadcast(np.asarray(E), np.asarray(N)).shape, dtype=bool)
    return clip.keep_points(E, N)


def tile_state(clip, cfg, i, j):
    if clip is None: return "inside"
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    return clip.rect_state(E0 + i * T, N0 + j * T, E0 + (i + 1) * T, N0 + (j + 1) * T)


def cell_mask(clip, gt, height, width, row0=0, col0=0):
    """(height, width) bool of KEPT cells for a north-up raster, evaluated at pixel CENTRES:
    E = gt[0] + (col + 0.5) * gt[1], N = gt[3] + (row + 0.5) * gt[5]."""
    import numpy as np
    if clip is None: return np.ones((height, width), dtype=bool)
    if gt[2] != 0.0 or gt[4] != 0.0:
        sys.exit("cell_mask: rotated geotransforms are not supported; rasters here are north-up")
    E = gt[0] + (col0 + np.arange(width) + 0.5) * gt[1]
    N = gt[3] + (row0 + np.arange(height) + 0.5) * gt[5]
    return clip.keep_points(E[None, :], N[:, None])


def clip_wkt(clip, bbox):
    e0, n0, e1, n1 = bbox
    ring = ([(e0, n0), (e1, n0), (e1, n1), (e0, n1), (e0, n0)] if clip is None
            else clip.rect_polygon(e0, n0, e1, n1))
    if not ring: return None
    return "POLYGON((" + ",".join(f"{x:.3f} {y:.3f}" for x, y in ring) + "))"


def clip_manifest(clip):
    if clip is None: return None
    return {**clip.stamp(),
            "semantics": "keep P iff cross(B-A, P-A) >= 0 for keep 'left' (<= 0 for 'right'); line = [A, B] in CRS "
                         "metres; points on the line are kept. Raster cells are tested at their centres; features at "
                         "their vertices (06, 11), footprint envelope centre (07) or node (10)."}


def grid_stamp(cfg, clip=None):
    """The _grid.json stamp step 02 and reuse_tiles.py agree on: the four raster-defining keys. The clip
    does not change a tile's bytes, so it is NOT part of the stamp (02 records it in _fetch_clip.json)."""
    return {"crs": cfg["crs"], "origin": cfg["origin"], "tile_m": cfg["tile_m"], "grid_res": cfg["grid_res"]}
```

`keep_points` on scalars returns a 0-d bool array (`if not lib.keep_points(...)` works). A later
`PolygonClip` implements `stamp / keep_points / signed_distance_out / rect_state / rect_polygon` and is
registered as `"polygon"`; nothing else moves.

### 2.3 Shared line geometry (copies of 06's arithmetic; 06 not refactored this round)

```python
# ---- line geometry -------------------------------------------------------------
# Densify + Chaikin + bilinear drape + per-tile split, exactly as step 06 does it. Step 06 keeps its own
# copies (BRIEF 4.4 "06 stays untouched"); the dry run proves equivalence (check C11 'rail on a road's
# polyline gives identical pts'); the follow-up commit "refactor-06-onto-lib.drape_runs" is gated by
# sources/tests/regress_outputs.sh compare margate before == 0 changed.

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
    """06_build_networks.py:54-69 as an object: bilinear sample of a north-up array whose gaps are NaN."""
    def __init__(self, arr, gt):
        self.a, self.gt = arr, gt
        self.H, self.W = arr.shape

    def __call__(self, e, n):
        import math, numpy as np
        gt, W, H, DTM = self.gt, self.W, self.H, self.a
        fx = (e - gt[0]) / gt[1] - 0.5
        fy = (n - gt[3]) / gt[5] - 0.5
        if not (0.0 <= fx <= W - 1 and 0.0 <= fy <= H - 1): return (0.0, False)
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
    """06_build_networks.py:163-201 as a function. Returns [(tile, [[E, N, z], ...], z_gap)] per tile run,
    seam vertex duplicated on both sides. An off-grid vertex and an off-clip vertex both close the run.
    counters: 'outside_grid', 'outside_clip', 'without_dtm' (kept vertices only)."""
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

### 2.4 `lib.tiff_info` extension (for `reuse_tiles.py`)

In the tag loop (`lib.py:155-162`) add `ModelTransformationTag` (34264, 16 doubles → `georef_origin
= (m[3], m[7])`) and `ModelTiepointTag` (33922, ≥ 6 doubles with raster tiepoint (0, 0) → `(tp[3],
tp[4])`); return `"georef_origin": vals.get("georef_origin")` (`:164-165`). Raw EA tiles carry 34264,
GDAL-written tiles 33922 + 33550.

---

## 3. Per-step edits

### 3.0 Common pattern

Right after `P = lib.paths(CFG)`: `CLIP = lib.parse_clip(CFG)`. Manifests add clip keys only under
`extra = {} if CLIP is None else {...}`; consumers use `manifest.get("clip")`.

### 3.1 Step 02 `sources/fetch/02_fetch_lidar.py`

| location | change |
|---|---|
| after `:28` | `CLIP = lib.parse_clip(CFG)` |
| `:32` | `GRID = lib.grid_stamp(CFG)` — the same four keys; `:34-38` unchanged (a clip edit never invalidates fetched tiles) |
| after `:39` | `if CLIP is not None: json.dump({"clip": lib.clip_manifest(CLIP), "skipped_positions": skipped}, open(os.path.join(P["lidar"], "_fetch_clip.json"), "w"), indent=1)` — written after the job list, overwritten each run, never compared |
| `:78` | `positions = [(i, j) for i in range(CFG["nx"]) for j in range(CFG["ny"])]`; `skipped = [(i, j) for (i, j) in positions if lib.tile_state(CLIP, CFG, i, j) == "outside"]`; `jobs = [(k, i, j) for k in ("dtm", "dsm") for (i, j) in positions if (i, j) not in set(skipped)]` |
| `:79` | `print(f"fetching {len(jobs)} rasters for {CFG['site']} ({len(positions)-len(skipped)} of {CFG['nx']*CFG['ny']} tile positions x2, {RES}x{RES} each)...", flush=True)` and, when `skipped`: `print(f"clip: skipping {len(skipped)} tile positions ({2*len(skipped)} rasters) wholly outside the clip line", flush=True)` |
| `:88` | `stats["skipped_clip"] = 2 * len(skipped)` before `print("summary:", stats)` — Thanet prints `skipped_clip: 206` |

A tile on disk at an `outside` position is left alone; 05 and 09 skip it from the config.

### 3.2 Steps 03 and 04 — no change

03 mosaics whatever exists (`03_build_mosaics.sh:22`, informational count at `:28`); 04's calibration
inputs include mainland buildings deliberately (more samples, and 07 applies the clip at emission).

### 3.3 Step 05 `sources/derive/05_export_terrain.py`

| location | change |
|---|---|
| after `:23` | `CLIP = lib.parse_clip(CFG)`; `ND = -9999.0` |
| `:34` | add `clipped = []`, `n_clipped_total = 0` |
| `:36-41` | before the `os.path.exists(src)` test: `state = lib.tile_state(CLIP, CFG, i, j)`; `if state == "outside": clipped.append([i, j]); (print if the file exists); continue` — `tiles_missing` keeps meaning "coverage gap" |
| after `:45` and after `:57-60` | `keep = lib.cell_mask(CLIP, d.GetGeoTransform(), RES, RES)`; `n_clip = int((~keep).sum())`; `if n_clip == RES*RES: clipped.append([i, j]); continue` (defensive; cannot happen with EA geometry); `kept_a = a[keep]`; `kept_slope = slope[keep]` |
| `:50` | range from `kept_a` |
| `:59-60` | slope stats from `kept_slope`; `cells += int(keep.sum())`; the gradient itself stays on the filled, unclipped array (real ground beyond the line gives the true edge gradient) |
| before `:62` | `if CLIP is not None: a[~keep] = ND; n_clipped_total += n_clip` |
| `:62-67` | after `dst.SetProjection(wkt)`: `if CLIP is not None: dst.GetRasterBand(1).SetNoDataValue(ND)` — on **every** tile of a clipped site, never on a clipless one |
| `:68-76` | `min_m/max_m` from `kept_a`; add (clipped sites only) `"clip_state": state`, `"clipped_cells": n_clip` |
| `:78-90` | add (clipped sites only) `"nodata": ND`, `"clip": lib.clip_manifest(CLIP)`, `"tiles_clipped": clipped`, `"clipped_cells_total": n_clipped_total`, `"clip_note": "Cells outside the clip are written as the declared NoData AFTER source gaps were filled: a NoData cell is a deliberate absence (the model ends here), never a coverage gap. Coverage gaps were filled and are counted in nodata_cells; grid positions with no source tile are tiles_missing; positions wholly outside the clip are tiles_clipped and have no file."` |
| `:92` | append `({len(clipped)} positions outside the clip: not exported)` when non-empty |

Thanet expectation: 391 tiles written, `tiles_clipped` = 103 positions, `clipped_cells_total` = 3,861,822.

### 3.4 Step 06 `sources/derive/06_build_networks.py` (clip support only)

| location | change |
|---|---|
| after `:39` | `CLIP = lib.parse_clip(CFG)` |
| `:144` | add `n_outside_clip, n_junc_clip = 0, 0` |
| after `:161` | `keep = lib.keep_points(CLIP, [p[0] for p in pts], [p[1] for p in pts]) if CLIP is not None else None` (tested on the smoothed vertices) |
| `:165-172` | `for k, (e, n) in enumerate(pts):` and after the `tile is None` branch: `if keep is not None and not keep[k]: n_outside_clip += 1; samp.append((e, n, None, None)); continue` — the fill loops (`:175-182`) skip it and the run loop (`:189-192`) closes the run; the test precedes `ground()`, so an off-clip vertex is not a DTM gap |
| `:204-207` | after `if tile is None: continue`: `if CLIP is not None and not lib.keep_points(CLIP, e, n): n_junc_clip += 1; continue` |
| `:221-231` | add (clipped only) `"clip"`, `"vertices_outside_clip"`, `"junctions_outside_clip"` |
| `:233-238` | print the two counts when a clip exists |

A way crossing the line ends at its last kept smoothed vertex (≤ 12 m short at the default
smoothing); nothing extends it (DESIGN.md 16). `length_km` (`:202`) keeps counting whole ways.

### 3.5 Step 07 `sources/derive/07_massing.py`

After `:31` `CLIP = ...`; `:119` add `outside_clip = 0`; after the grid test at `:124-126`:
`if CLIP is not None and not lib.keep_points(CLIP, cx, cy): outside_clip += 1; continue` (the same
**envelope centre** `(cx, cy)` from `:122`); manifest `:191-199` adds (clipped only) `"clip"`,
`"outside_clip"`; print `:203-204` appends `off-clip: {outside_clip}`.

### 3.6 Step 09 `sources/derive/09_coast.py`

Contract: **bands sum to 252–255 for every cell inside the clip** (each band is truncated to uint8
independently at `:170`; Margate today: 5,873,301 cells at 255, 89,722 at 254, 751 at 253, 2 at 252)
**and to 0 for every cell outside; no inside cell sums below 252 and sum 0 occurs only outside.**

| location | change |
|---|---|
| after `:44` | `CLIP = lib.parse_clip(CFG)` |
| `:147` | add `clipped, n_clipped_cells = [], 0` |
| `:149` loop head | first statement: `state = lib.tile_state(CLIP, CFG, i, j)`; `if state == "outside": clipped.append([i, j]); continue` (before the mosaic-bounds test at `:155/:158`) |
| water-tile test (`:159-160` region) | for straddle tiles judge kept DTM cells only: `kd = lib.cell_mask(CLIP, gt, TPY, TPX, row0=row0, col0=col0)`; `sub_k = np.where(kd, sub_h, np.nan)`; skip the test when nothing is finite |
| after `:170` | `if state == "straddle": km = lib.cell_mask(CLIP, (e0, cell, 0.0, n0 + T, 0.0, -cell), SPLAT, SPLAT); img[~km] = 0; n_clipped_cells += int((~km).sum())` — class-cell centres, the geotransform of `:175` |
| `:186-196` | add (clipped only) `"clip"`, `"tiles_clipped": clipped`, `"clipped_cells": n_clipped_cells`, `"bands_note": "grass+sand+rock+water sums to 252..255 for every cell inside the clip (each band is truncated to uint8 separately); a cell outside the clip is 0 in all four bands, and sum 0 occurs only outside."` |
| `:197` | append the clipped counts |

Coastline length stays clipped to the grid rectangle. The Unity adapter paints grass under the cut
(`unity.py:145`); noted, not fixed (Unity is not a Thanet target).

### 3.7 Step 10 `sources/derive/10_furniture.py`

After `:35` `CLIP = ...`; `:128` add `outside_clip = 0`; after the grid test `:139-141`:
`if CLIP is not None and not lib.keep_points(CLIP, e, n): outside_clip += 1; continue` (OSM position,
before any nudge); manifest `:158-166` adds (clipped only) `"clip"`, `"outside_clip"`; print `:168`
appends `outside clip: {outside_clip}`.

---

## 4. Step 11 `sources/derive/11_linear_features.py`

### 4.1 Scope

Two layers from the GeoPackage `lines` layer, each densified, smoothed, draped and tiled exactly like
roads via `lib.drape_runs`.

**Railway** — `railway IS NOT NULL`, emit `tuning.rail.classes` = `rail, light_rail, tram,
narrow_gauge, miniature, disused` (`disused` = track still in place; `abandoned/razed/dismantled`,
`construction/proposed`, `platform/station/…` are skipped and counted in `ways_skipped_by_class.railway`).

**Barriers** — `barrier IS NOT NULL`, emit `tuning.barriers.classes` = `wall, fence, hedge,
retaining_wall, kerb, guard_rail, handrail, city_wall`; `gate`, `bollard`, `yes` and anything else are
skipped and counted; the barrier features in `multipolygons` are counted as `barrier_areas_skipped`
(Margate: 2) and not read.

### 4.2 Record schemas

`networks/rail_x{i}_y{j}.jsonl`, one record per tile run:

```json
{"id":"w123","cls":"rail","gauge":1.435,"gauge_src":"osm","tracks":2,"electrified":"rail","service":null,"usage":"main",
 "bridge":false,"tunnel":false,"name":"Chatham Main Line","z_gap":false,"pts":[[E,N,z],...]}
```

| field | type | meaning |
|---|---|---|
| `id` | string | OSM way id |
| `cls` | string | the OSM `railway` value verbatim |
| `gauge` | number, m | OSM `gauge` mm → m (`"1435"` → 1.435; `"1435;1000"` → first; `"standard"` → 1.435); absent/unparseable → `tuning.rail.default_gauge_m` |
| `gauge_src` | `osm` \| `default` | |
| `tracks` | int or null | OSM `tracks`, not defaulted |
| `electrified`, `service`, `usage` | string or null | raw OSM values |
| `bridge`, `tunnel` | bool | tag presence, elevation not adjusted |
| `name` | string or null | |
| `z_gap` | bool | as roads (`sources/OUTPUT.md:58`) |
| `pts` | `[[E, N, z], …]` | densified (`tuning.rail.densify_step_m` 8) + Chaikin (`chaikin_iters` 2), draped, tiled, cut at grid and clip |

`networks/barriers_x{i}_y{j}.jsonl`:

```json
{"id":"w456","cls":"wall","h":0.5,"h_src":"osm","material":null,"fence_type":null,"wall":"brick","name":null,"z_gap":false,"pts":[[E,N,z],...]}
```

| field | type | meaning |
|---|---|---|
| `cls` | string | OSM `barrier` value verbatim |
| `h` | number, m | OSM `height`: first token, unit suffix `m` (default) / `cm` (÷100) / `mm` (÷1000) / `ft` or `'` (×0.3048); absent/unparseable → `tuning.barriers.default_height_m[cls]` |
| `h_src` | `osm` \| `default` | |
| `material`, `fence_type`, `wall`, `name` | string or null | raw OSM |
| `z_gap` | bool | |
| `pts` | `[[E, N, z], …]` | densified 8 m, **Chaikin 0** (walls turn corners), draped, tiled |

No width is emitted for either layer.

### 4.3 Structure

```python
#!/usr/bin/env python3
"""OSM railway and barrier ways -> per-tile draped polylines, beside the roads of step 06."""
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
dtm_ds = gdal.Open(os.path.join(P["interim"], "dtm.vrt")); band = dtm_ds.GetRasterBand(1)
DTM = band.ReadAsArray().astype(np.float32); DTM[lib.nodata_mask(DTM, band.GetNoDataValue())] = np.nan
sample = lib.DtmSampler(DTM, dtm_ds.GetGeoTransform())

def parse_gauge(s): ...        # -> (metres, "osm") | (RAIL["default_gauge_m"], "default")
def parse_height(s, cls): ...  # -> (metres, "osm") | (BAR["default_height_m"][cls], "default")
def as_int(s): ...

LAYERS = {"rail": dict(column="railway", classes=set(RAIL["classes"]), tun=RAIL, prefix="rail"),
          "barriers": dict(column="barrier", classes=set(BAR["classes"]), tun=BAR, prefix="barriers")}
src = ogr.Open(P["gpkg"]); lyr = src.GetLayer("lines"); summary = {}
for name, L in LAYERS.items():
    lyr.SetAttributeFilter(f"{L['column']} IS NOT NULL")
    buckets, skipped, counters, length, n_default = defaultdict(list), Counter(), {}, 0.0, 0
    for f in lyr:
        cls = f.GetField(L["column"])
        if cls not in L["classes"]: skipped[cls] += 1; continue
        g = f.GetGeometryRef()
        if g is None or g.GetPointCount() < 2: continue
        raw = [(g.GetX(k), g.GetY(k)) for k in range(g.GetPointCount())]
        rec = build_record(name, f, cls, f.GetField("other_tags"))     # §4.2 minus z_gap/pts; bumps n_default
        pts = lib.chaikin(lib.densify(raw, L["tun"]["densify_step_m"]), L["tun"]["chaikin_iters"])
        for tile, run, gap in lib.drape_runs(pts, CFG, sample, CLIP, counters):
            buckets[tile].append({**rec, "z_gap": gap, "pts": run})
        for a, b in zip(pts, pts[1:]): length += math.hypot(b[0]-a[0], b[1]-a[1])
    for old in glob.glob(os.path.join(OUT, f"{L['prefix']}_x*_y*.jsonl")): os.remove(old)   # own files only
    n = 0
    for (i, j), items in sorted(buckets.items()):
        with open(os.path.join(OUT, f"{L['prefix']}_x{i}_y{j}.jsonl"), "w") as fh:
            for it in items: fh.write(json.dumps(it, separators=(",", ":")) + "\n"); n += 1
    summary[name] = {...}
```

Zero matching ways is not an error; with an empty `railway` column and no `query_sha256` in provenance
the step prints `11: NOTE -- no railway ways in the extract; the Overpass query must include
way["railway"] (fetch_osm.sh) and the extract must be re-fetched` (the Margate case). Ways tagged both
`highway` and `railway` appear in both layers.

### 4.4 Manifest `networks/linear_manifest.json`

```json
{"site": "thanet", "crs": "EPSG:27700", "coordinates": "[easting, northing, elevation] in CRS metres",
 "origin": {"E": 627680, "N": 163080}, "tile_m": 512,
 "source_layer": "lines (GeoPackage from step 01); barrier areas in multipolygons are not read",
 "layers": {
  "rail": {"files": "rail_x{i}_y{j}.jsonl", "column": "railway", "classes_emitted": ["rail", "light_rail", "tram", "narrow_gauge", "miniature", "disused"],
           "segments": 0, "tiles": 0, "length_km": 0.0, "by_class": {}, "smoothing": {"densify_step_m": 8.0, "chaikin_iters": 2},
           "default_gauge_m": 1.435, "gauge_defaulted": 0, "vertices_without_dtm": 0, "vertices_outside_grid": 0},
  "barriers": {"files": "barriers_x{i}_y{j}.jsonl", "column": "barrier", "classes_emitted": ["wall", "fence", "hedge", "retaining_wall", "kerb", "guard_rail", "handrail", "city_wall"],
               "segments": 0, "tiles": 0, "length_km": 0.0, "by_class": {}, "smoothing": {"densify_step_m": 8.0, "chaikin_iters": 0},
               "default_height_m": {"wall": 1.8, "fence": 1.5, "hedge": 1.5, "retaining_wall": 1.5, "kerb": 0.12, "guard_rail": 0.75, "handrail": 1.0, "city_wall": 6.0},
               "height_defaulted": 0, "vertices_without_dtm": 0, "vertices_outside_grid": 0}},
 "ways_skipped_by_class": {"railway": {}, "barrier": {"gate": 13, "bollard": 13, "yes": 2}},
 "barrier_areas_skipped": 2}
```

Plus, clipped sites only: top-level `"clip"` and per layer `"vertices_outside_clip"`.

### 4.5 `sources/config/tuning.json` additions (after the `roads` block)

```json
  "rail": {
    "classes": ["rail", "light_rail", "tram", "narrow_gauge", "miniature", "disused"],
    "classes_note": "OSM railway values emitted by step 11 as cls. disused = track still in place; abandoned/razed/dismantled have no track and are skipped, as are platform/station/signal and other non-track ways. Skipped values are counted in linear_manifest.ways_skipped_by_class.",
    "default_gauge_m": 1.435,
    "default_gauge_note": "Standard gauge (1435 mm), the whole Kent network. OSM gauge is in millimetres and is converted; a way without the tag gets this and gauge_src=default.",
    "densify_step_m": 8.0,
    "chaikin_iters": 2,
    "chaikin_note": "Same presentation choice as roads. The Streetscape rail profile resamples with curvature-adaptive spacing anyway. Set 0 for OSM-faithful vertices."
  },
  "barriers": {
    "classes": ["wall", "fence", "hedge", "retaining_wall", "kerb", "guard_rail", "handrail", "city_wall"],
    "classes_note": "OSM barrier values emitted by step 11 as cls -- the linear ones. gate and bollard ways (two-node, point-like) and barrier=yes are skipped and counted; barrier nodes live in the points layer.",
    "default_height_m": {"wall": 1.8, "fence": 1.5, "hedge": 1.5, "retaining_wall": 1.5, "kerb": 0.12, "guard_rail": 0.75, "handrail": 1.0, "city_wall": 6.0},
    "default_height_note": "OPINIONS, used only when OSM has no height tag (Margate: 15 of 467 barrier ways carry one) and tagged h_src=default. wall 1.8 (below the 2 m permitted-development limit); fence 1.5 (garden panel); hedge 1.5 (trimmed privet); retaining_wall 1.5 (the DTM step is the truth); kerb 0.12 (= furniture.kerb_m); guard_rail 0.75 (beam height); handrail 1.0 (Approved Document K); city_wall 6.0 (placeholder).",
    "densify_step_m": 8.0,
    "chaikin_iters": 0,
    "chaikin_note": "Zero on purpose: walls and fences are angular; Chaikin would move every corner a quarter-span inward. Densification still adds drape points every 8 m."
  },
```

---

## 5. `sources/fetch/fetch_osm.sh` and provenance

- Insert `  way["railway"]($BBOX);` after `fetch_osm.sh:26` (`way["highway"]`); `way["barrier"]` is
  already at `:32`. No relations, no node selectors (DESIGN.md 19).
- After the heredoc (`:40`): `printf '%s' "$Q" > "$OUT.query"`.
- `01_fetch_osm.sh` provenance (`:127-151`): pass `"$OSM.query"`; add `query_sha256` (null if the
  query file is absent), `query_selectors` (sorted unique `(node|way|relation)\[[^]]*\]` with
  `($BBOX)` stripped), `query_note` when null (`"null query_* means the extract predates query
  recording; it was fetched by fetch_osm.sh as of commit 0d31c0c, which had no way[\"railway\"]"`), and
  `counts.railway` / `counts.barriers` via two more `ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE
  railway IS NOT NULL"` / `barrier IS NOT NULL` beside `:124-125`.

Margate's extract is not re-fetched (01 skips on a matching bbox, `01:24-30`); it keeps 0 railway ways
and byte-identical outputs; the README says so (§10.2).

---

## 6. `sources/run.sh`

- `:38`: append `"11:sources/derive/11_linear_features.py:OSM railway + barrier ways -> draped polylines (rail_*, barriers_*)"`
  (the `\<` string compare at `:81` orders `11` after `10`). Header `:4` → `01 -> 11`. Closing hint `:97`
  additionally prints `for Unreal / Streetscape: SITE=$SITE $PY sources/adapters/unreal.py`.
- Replace `:27` `PY="${PY:-python3.14}"` with the probe below and delete `:53`:

```bash
usable() { command -v "$1" >/dev/null 2>&1 && "$1" -c 'import numpy; from osgeo import gdal' >/dev/null 2>&1; }
if [ -z "${PY:-}" ]; then
  for cand in python3.14 python3.13 python3 python; do if usable "$cand"; then PY="$cand"; break; fi; done
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
export PY          # 01_fetch_osm.sh:14 and 03_build_mosaics.sh:11 read $PY
```

Invocation on this machine:
`PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=/c/Users/Shadow/code/3duk-env/env/python.exe SITE=thanet ./sources/run.sh`.

---

## 7. `sources/fetch/reuse_tiles.py`

CLI `PY sources/fetch/reuse_tiles.py --from margate --to thanet [--dry-run] [--link]`. Checks, each a
`sys.exit` with both values printed:

1. `crs`, `tile_m`, `grid_res` equal.
2. `wcs` blocks equal (notes stripped).
3. `dE = from.origin.E − to.origin.E`, `dN` likewise, both multiples of `tile_m`; `di, dj = dE // tile_m,
   dN // tile_m` (Margate → Thanet: 10, 10).
4. Source stamp `data/<from>/raw/lidar/_grid.json` equals `lib.grid_stamp(from_cfg)`.
5. Target stamp: `expected = lib.grid_stamp(to_cfg)`; existing must equal it, else it is written **after**
   the copies succeed.
6. Per source `{dtm,dsm}_x{i}_y{j}.tif`: target `(i + di, j + dj)`; outside the target grid → `outside_target_grid`;
   `lib.tile_state(to_clip, to_cfg, i2, j2) == "outside"` → `outside_clip` (Margate → Thanet: 0);
   `lib.tiff_info`: `width == height == grid_res`, `dtype == "float32"`, `georef_origin == (E0_to + i2·T − 0.5,
   N0_to + j2·T + T + 0.5)` to 1e-6 (Margate `x0_y0` → `(632799.5, 168712.5)`); destination present with equal
   sha256 → `present`; present and different → FATAL; else copy (or `os.link` with `--link`) and re-hash.
7. Summary `{copied, present, outside_target_grid, outside_clip}` and the mapping rule.

Expected: `--dry-run` 182 planned; real run 182 copied (~728 MB); then `SITE=thanet run.sh --only 02`
reports `cached: 182`, `skipped_clip: 206`, `ok: 600`, about 4.6 min at 2.2 rasters/s.

---

## 8. `sources/tests/dryrun.py`

### 8.1 Harness

`STEPS` (`dryrun.py:52-53`) gains `"derive/11_linear_features.py"` after 10 and `"adapters/unreal.py"`
after `unity.py`, run for all three sites. `lines` fields (`:96`) become `["osm_id", "highway",
"railway", "barrier", "name", "other_tags"]`; new `synth` parameters `rails=()`, `barriers=()` (tuples
`(id, value, pts, name, other_tags)`), `skip_tiles=()` (no raw `dtm` tile, VRT region = ND); decoys
gain `networks/rail_x9_y9.jsonl`, `networks/barriers_x9_y9.jsonl`; cleanup removes `_dryrun_c.json`.
The adapter's `profiles_dir` resolves to the real `projects/one/schema/profiles/`.

### 8.2 Site C: 1 m, 3 × 2 tiles, diagonal clip

`E0c, N0c = 700000, 300000`, `CLIP_C = {"type": "halfplane", "line": [[E0c, N0c + 1100], [E0c + 1100, N0c]],
"keep": "left"}` (kept iff local `x + y ≥ 1100`); plane `z = 20 + 0.01(E − E0c) + 0.02(N − N0c)`;
`skip_tiles=((0, 0),)`. Tile states: `(0,0)` outside; `(0,1) (1,0) (1,1) (2,0)` straddle; `(2,1)` inside.
Clipped 1 m cells: `(1,0)`, `(0,1)` 167,466 of 263,169; `(1,1)`, `(2,0)` 2,926; `(2,1)` 0. Clipped 2 m
class cells: `(1,0)` 41,665, `(1,1)` 703. Features (local offsets): ways `rd1` residential
`(700,100)→(700,900)` (crosses the line at y = 400 and the seam at 512), `rd2` residential
`(100,100)→(300,100)` outside, `rd3` footway, `rd4` service at the outside junction `(100,100)`, `rd5`/`rd6`
tertiary + `rd7` footway at the inside junction `(1300,800)`; rail `rl1` rail = `rd1`'s polyline with
`"gauge"=>"1435","electrified"=>"rail","usage"=>"main","tracks"=>"2"`, `rl2` disused `(1200,600)→(1400,700)`,
`rl3` platform, `rl4` rail outside; barriers `bw1` wall `(1100,600)→(1100,700)` `"height"=>"0.5","wall"=>"brick"`,
`bf1` fence `(1200,900)→(1300,900)` chain_link/metal, `bk1` kerb `"height"=>"15 cm"`, `bh1` hedge
`(400,400)→(800,800)` crossing the line, `bg1` gate; buildings `cb1` kept, `cb2` centroid outside; nodes
`cn1` inside on `rd1`, `cn2` outside. Config extra: `origin, clip, water_level −50, height_calib fixed,
coast {foreshore −50, rock [25,45], margin 0.75}, landmarks {}`.

### 8.3 `check()` names (≈ 40 new; today 86)

lib: `C-lib parse_clip: absent -> None; unknown type refuses` · `C-lib tile_state on the diagonal` ·
`C-lib keep_points: vectorised; on-line kept; keep=right mirrors` · `C-lib cell_mask at pixel centres:
tile (1,0) clips 167466 of 263169; None -> all True` · `C-lib clip_wkt: 5-corner / rectangle / None` ·
`C-lib grid_stamp: four keys with or without a clip` · `C-lib drape_runs == 06 arithmetic` ·
**`C-lib thanet.json clip.line == BRIEF 4.1 [[628512, 169680], [635496, 163609]]`** ·
**`C-lib tile_state / cell_mask on the Thanet grid: 360 inside, 31 straddle, 103 outside, 3861822 clipped
cells`** (reads the real `sources/config/sites/thanet.json`) · `C-lib signed_distance_out: 0 on the line,
+ into the cut`.
05: outside tile no file + `tiles_clipped` · straddle `(1,0)` NoData count 167466 == `clipped_cells` ·
SW NoData / NE real / kept cells untouched · inside tile `clip_state inside` · NoData declared on every
tile · `range_m`/`slope_qa` from kept cells · manifest `clip` block.
06: `rd1` cut at its last kept vertex (`x + y ≥ 1100`, first vertex `y ∈ [400, 412)`) · outside way
dropped, counts · off-clip vertices are not DTM gaps · seam split kept · outside junction dropped ·
manifest `clip`.
07: `outside_clip 1`, one building kept.
09: outside tile no raster · straddle `(1,0)` zero-sum cells 41665; **`(sum >= 252) | (sum == 0)`
everywhere; `sum == 0` count == `clipped_cells`** · totals · manifest `clip`, `bands_note`.
10: outside node dropped, `cn1` placed on `rd1`.
11: `rl1` per-tile `pts`/`z_gap` identical to `rd1`'s · rail fields (1.435 osm, tracks 2, electrified,
usage, bridge/tunnel False) · disused default gauge; platform skipped · outside rail dropped ·
wall h 0.5 osm / fence h 1.5 default · Chaikin 0 (`bw1` E exact) · `"15 cm"` → 0.15 · hedge cut; gate
counted · manifest shape · decoys cleared · `A11`/`B11` zero counts · `A` clipless: no clip keys, no
NoData tag.
adapter: §13.10 hook.
Real-tile check (when `data/margate` exists): `lib.tiff_info(dtm_x0_y0.tif)["georef_origin"] ==
(632799.5, 168712.5)`.

---

## 9. Margate byte-identity procedure

### 9.1 `sources/tests/regress_outputs.sh`

```bash
#!/bin/bash
# Prove a pipeline edit did not change a site's products.
#   regress_outputs.sh snapshot <site> <label>   hash every file under data/<site>/out -> data/<site>/regress/<label>.sha256
#   regress_outputs.sh compare  <site> <label>   re-hash and diff against the snapshot
# Line format of the hash files is normalised to "<64 hex><two spaces><path>": on Windows GNU sha256sum
# marks binary mode with '*' glued to the name, which would break the ADDED-file allow list below.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="$1"; SITE="$2"; LABEL="${3:-before}"
OUT="$ROOT/data/$SITE/out"; REG="$ROOT/data/$SITE/regress"; mkdir -p "$REG"
ALLOW_NEW='^(networks/(rail|barriers)_x[0-9]+_y[0-9]+\.jsonl|networks/linear_manifest\.json|unreal/.*)$'
hash_tree() { (cd "$OUT" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs -d '\n' sha256sum | sed -E 's/^([0-9a-f]{64}) \*?/\1  /'); }
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

Self-check at first run: `head -1 data/margate/regress/before.sha256` must match `^[0-9a-f]{64}  [^*]`.

### 9.2 Procedure

1. Before any edit: `./sources/tests/regress_outputs.sh snapshot margate before` — hashes every file
   under `data/margate/out` (today: terrain 92, networks 83, massing 71, coast 92, furniture 14, two
   `qa_*.json`, plus `unity/**`; the snapshot's line count is the reference number).
2. Make the edits of §2–§6.
3. `PATH=… PY=… SITE=margate ./sources/run.sh --from 05` (05, 06, 07, 09, 10, 11), then
   `SITE=margate $PY sources/adapters/unity.py`.
4. `./sources/tests/regress_outputs.sh compare margate before` → **0 CHANGED, 0 REMOVED**; added and
   allowed: `networks/linear_manifest.json`, `networks/barriers_x*_y*.jsonl` (no `rail_*`: 0 railway
   ways). If the Unreal adapter is also run, `unreal/**` is allowed.

### 9.3 Manifests that gain keys (clipped sites only)

`terrain_manifest.json`: `nodata, clip, tiles_clipped, clipped_cells_total, clip_note`, per tile
`clip_state, clipped_cells` · `networks_manifest.json`: `clip, vertices_outside_clip, junctions_outside_clip` ·
`massing_manifest.json`: `clip, outside_clip` · `coast_manifest.json`: `clip, tiles_clipped, clipped_cells,
bands_note` · `qa_furniture.json`: `clip, outside_clip` · `linear_manifest.json` (new, all sites): `clip`
and per-layer `vertices_outside_clip` for clipped sites · `raw/lidar/_fetch_clip.json` (new, clipped
sites). `_grid.json` never changes. Whitby is not re-run this round (same commands apply).

---

## 10. `sources/OUTPUT.md` and `README.md` deltas

### 10.1 `OUTPUT.md`

- Conventions table (`:8-18`): row **Clip** — "A site config may carry an optional `clip` block
  (Thanet: the half-plane north-east of the Minnis Bay → Pegwell Bay line). Every manifest of a clipped
  site records it under `clip` (`type`, `line`, `keep`, `semantics`); no `clip` key = unclipped site.
  Rasters are clipped at cell centres; vertices, footprint envelope centres and nodes at their
  positions; points exactly on the line are kept."
- `terrain/` (`:25-27`): "**Except** cells outside the site's clip: written as the band's declared
  NoData (`terrain_manifest.nodata`, −9999) **after** the fill — a deliberate absence, never a coverage
  gap. `clipped_cells` per tile counts them; `clip_state` is `inside` or `straddle`. Positions wholly
  outside have no file and are `tiles_clipped`, distinct from `tiles_missing`. Render NoData as a hole."
  `slope_qa` (`:29-30` region): "For a clipped site `range_m` and `slope_qa` describe kept cells only."
- `networks/` after `:64-66`: "Likewise a way that crosses the clip line ends at its last kept smoothed
  vertex (within ~12 m of the line at the default smoothing); `vertices_outside_clip` and
  `junctions_outside_clip` are counted; off-clip vertices are not DTM gaps."
- New subsection **`networks/` — step 11** with the two record tables of §4.2 verbatim, then:
  "`linear_manifest.json` is step 11's manifest (`networks_manifest.json` stays step 06's).
  `default_gauge_m` and `default_height_m` are opinions from `tuning.json`; records that used them say so
  in `gauge_src` / `h_src`. `ways_skipped_by_class` lists every `railway`/`barrier` value seen but not
  emitted; `barrier_areas_skipped` counts closed barrier outlines in `multipolygons`, which are not read."
- `massing/`: "`outside_clip` counts footprints whose envelope centre lies outside the clip; not emitted."
- `coast/` (`:104-105`): replace "as fractions 0–255 that sum to 255" with "as fractions 0–255 that
  **sum to 252–255 (each band is truncated to a byte separately) for every cell inside the site's clip;
  a cell outside the clip is 0 in all four bands (sum 0), and sum 0 occurs only outside**". Manifest
  paragraph: "`tiles_clipped` lists positions wholly outside (no raster; distinct from
  `tiles_without_dtm`), `clipped_cells` counts zeroed cells."
- `furniture/`: "`qa_furniture.json` counts `outside_clip` nodes; not placed."
- "Writing an adapter" (`:152-157`): add "Honour `clip`: treat terrain NoData as absence, not
  elevation; expect ground-cover cells that sum to 0; expect rail and barrier layers beside roads.
  `sources/adapters/unreal.py` is the Streetscape-frame adapter (local metres, Y north, Z ODN) for
  Unreal and Blender; it additionally reads `derived/<site>.gpkg` for the raw OSM way geometry and tags,
  the one product not in `out/`."

### 10.2 `README.md`

Tree: `derive/` "03-11 … railway + barrier polylines"; `fetch/` gains `reuse_tiles.py`; `tests/` line
"`dryrun.py` fake-GDAL run of 05–11 + adapters on three synthetic sites; `regress_outputs.sh`
byte-identity of a site's products; `test_unreal_adapter.py`". Rebuilding: the §6 invocation and the
`PY` probe rule. Sites: **thanet** paragraph (26×19 tiles, the Wantsum cut, inherited calibration
re-fitted by 07, Margate sub-grid `(i, j) → (i+10, j+10)` via `reuse_tiles.py`). Adding a site: "A clip
is the one feature that is legitimately a step-wide change — opt-in via the site config, implemented
once in `lib.py`, recorded in every manifest it touches, byte-identical output without it (proved by
`regress_outputs.sh`)." Output table: row 11. Sources and licensing: the query-in-provenance rule and
"Margate's and Whitby's extracts were fetched before `way["railway"]` was in the query (`query_sha256:
null`)". Checking without GDAL: "three synthetic sites … the third has a clip line crossing the grid
diagonally and rail/barrier ways, and runs step 11 and the Unreal adapter". Regression: the §9
procedure. Environment note: numpy's LAPACK calls (`polyfit/lstsq/svd`) exit silently in the env python
unless `3duk-env/env/Library/bin` is on `PATH` (BRIEF §8; DESIGN.md 14).

---

## 11. Risks (pipeline)

1. Byte identity is easy to lose (an unconditional `SetNoDataValue`, a `"clip": None` key, key-order
   changes, an opportunistic 06 refactor) — §3.0 guard, snapshot **before** the first edit, 06 refactor
   as its own gated commit.
2. Rail is absent until Thanet is fetched — the synthetic site exercises the arithmetic; the first real
   run is inspected (Birchington–Ramsgate continuous, `gauge_defaulted` small).
3. A ~45 MB Overpass extract may time out — retries exist (`fetch_osm.sh:42-62`); raise `[timeout:600]`
   to 900 in the same edit if needed.
4. The clip edge and the landscape hole must agree — 05 clips at 1 m cell centres with `≥ 0`; the adapter
   derives `vis_*.r8` from the same line with the same `≥ 0`/`keep left` semantics (§13.3) and
   cross-checks `clip_*.r8` against `clipped_cells`.
5. `length_km` and calibration include beyond-line geometry — deliberate; noted in the manifests.
6. Step 09 memory for Thanet ≈ 3.5 GB — run alone.
7. Provenance rewrite on every step-01 run dirties `sources/provenance/margate.osm.json` with
   `query_sha256: null` — commit it or do not run 01 for Margate.

---

## 12. Contracts with the other subsystems (as the pipeline sees them)

The adapter (§13) reads terrain NoData via `lib.nodata_mask(a, band.GetNoDataValue())`, tolerates
`clip` absent, accepts ground cells summing to 252–255 or 0, reads `rail_*`/`barriers_*` with the §4.2
fields, and writes `data/<site>/out/unreal/unreal_manifest.json` with `origin{E,N}`, `tile_m`, `nx`,
`ny`, `res`, `crs`, `vertical_datum`, `frame`; the dry run asserts those round-trip. The Unreal importer
cuts the hole from the adapter's `vis_*.r8` (derived from `terrain_manifest.clip.line`).

---

## 13. The Unreal adapter — `sources/adapters/unreal.py` (adapter task)

### 13.0 Principles

Reads `data/<site>/out/` (terrain, networks incl. step 11, coast, massing, furniture, their manifests)
plus `data/<site>/derived/<site>.gpkg` (raw OSM geometry and `other_tags`); writes
`data/<site>/out/unreal/`. Mirrors `unity.py` in shape (`need()`, one function per product, a
`_note`-carrying `unreal.json`, refusal over silent clipping) but **bakes no engine frame**: output is
the Streetscape frame (DESIGN.md 2). Module level does no site I/O (`lib.load()` inside `main()`), so
`test_unreal_adapter.py` unit-tests the pure functions. Runs under the fake GDAL with numpy only (no
scipy/PIL). Uses `lib.tagval` (not a third copy) and `lib.HalfPlaneClip.signed_distance_out`.

### 13.1 Module layout

```python
#!/usr/bin/env python3
"""Neutral pipeline output -> Streetscape-frame products for Unreal and Blender."""
import glob, json, math, os, subprocess, sys
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions(); ogr.UseExceptions()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

ADP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unreal.json")
SCHEMA_VERSION = "1.0.0"
FRAME = "local-metres, X east, Y north, Z up"        # the schema const, verbatim
FRAME_NOTE = ("x = E - E0 (east), y = N - N0 (north), z = ODN metres unchanged; right-handed, Z up. Unreal: X_ue = 100*x, "
              "Y_ue = -100*y, Z_ue = 100*z (cm, +Y south); yaw_ue = bearing - 90 = -heading_deg. Applied only by the Unreal loader/importer.")

# ---- pure functions --------------------------------------------------------------------------
def encode_h16(z_m, per_unit=128, offset=32768) -> np.ndarray   # '<u2'; round(z*128)+32768
def decode_h16(h16, per_unit=128, offset=32768) -> np.ndarray   # float64 m; |decode(encode(z)) - z| <= 1/256
def check_range(range_m, limit_m)                                # sys.exit "does not fit" outside limit
def survey_to_local(E, N, z, E0, N0)                             # (E-E0, N-N0, z)
def local_to_ue_cm(x, y, z)                                      # (100x, -100y, 100z)  -- docs/tests only
def bearing_to_heading_deg(b)                                    # ((90 - b + 180) % 360) - 180  in [-180, 180)
def bearing_to_ue_yaw(b)                                         # (b - 90) % 360           -- docs/tests only
def visibility_weight(d_m, px_m=1.0) -> np.ndarray               # uint8 round(clamp(2/3 + d/(3 px), 0, 1) * 255)
def catmull_rom_dense(P, alpha=0.5, n=32) -> np.ndarray          # the schema interpolant (SCHEMA.md 3.1), for thinning
def thin_against_interpolant(xy, tol_m, keep=()) -> (indices, max_dev_m)   # 13.7
def order_runs(raw_xy, runs) -> list                             # 13.6
def nearest_z(xy, chain_xyz) -> float
def clip_polyline(xy_list, cfg, clip) -> (pieces, n_dropped)     # 13.9
def parse_height_m(text) -> float | None                         # fallback only; step 11 emits h
def classify_barrier(cls, rec, adp) -> (type, height_m, thickness_m, material, height_src) | None
def profile_ids_for(layer, cls, tags, pav, adp) -> dict          # the five ProfileIds keys
def load_profiles(profiles_dir) -> dict                          # {kind: {id: profile}}; refuses duplicates / bad shape
def git_sha() -> str                                             # subprocess git rev-parse --short HEAD, "unknown" on failure
# ---- products ----------------------------------------------------------------------------------
def landscape(cfg, adp, src, out, clip) ; def streetscape(cfg, adp, src, out, clip, profiles)
def massing(cfg, adp, src, out)   ; def furniture(cfg, adp, src, out)
def write_root_manifest(cfg, adp, out, stats)
def main(argv=None): ...
if __name__ == "__main__": main()
```

Run: `SITE=thanet PY sources/adapters/unreal.py` from the repo root with the GDAL environment.

### 13.2 Output tree

```
data/<site>/out/unreal/
  unreal_manifest.json
  landscape/  landscape_manifest.json  hm_x{i}_y{j}.r16  clip_x{i}_y{j}.r8  vis_x{i}_y{j}.r8 (straddle tiles)  weight_{grass,sand,rock,water}_x{i}_y{j}.r8
  streetscape/  site_x{i}_y{j}.json  streetscape_manifest.json
  massing/  buildings_x{i}_y{j}.jsonl  massing_manifest.json
  furniture/  furniture_x{i}_y{j}.jsonl  furniture_manifest.json
```

### 13.3 Landscape products

**`hm_x{i}_y{j}.r16`** — per `terrain_manifest.tiles[]`: read `terrain/dtm_x{i}_y{j}.tif`, refuse if
shape ≠ `(res, res)`; `bad = lib.nodata_mask(a, band.GetNoDataValue())` = the clipped cells; fill them
with `lib.fill_nodata` (nearest; recorded as `clip_fill`); `check_range(range_m, [-255, 255])`;
`encode_h16(a).astype('<u2').tofile(path)` — 526,338 bytes, north row first, no flip. Engine facts:
`LANDSCAPE_ZSCALE 1/128`, `MidValue 32768`, `GetTexHeight` clamps silently (`LandscapeDataAccess.h:13, :27, :35-38`)
— hence the refusal. `h16_min/h16_max` per tile are computed from the encoded array (Margate
`dtm_x5_y5`: 32817 / 35673).

**`clip_x{i}_y{j}.r8`** — `255 keep / 0 clipped-or-nodata` from `bad`. Consistency: with
`terrain_manifest.clip`, `count(0) == tile.clipped_cells` else refuse; without, `count(0) == 0` else
refuse; config clip present but manifest clip absent or a different `line` → refuse ("stale").

**`vis_x{i}_y{j}.r8`** — straddle tiles only (`tile.clip_state == "straddle"`): for every vertex
position (pixel centre, integer metres) `d = clip.signed_distance_out(E, N)`,
`w = round(clamp(2/3 + d/(3·px_m), 0, 1)·255)` with `px_m = 1.0`; `w = 170` on the line (2/3·255 rounded),
255 from 1 m into the cut, 0 from 2 m into the kept side. Inside tiles: no file (importer uses 0);
excluded tiles: no file (importer uses 255). This is the "exact line" of BRIEF 4.1: the render edge is
where the bilinearly interpolated weight crosses 2/3, i.e. `d = 0`.

**`weight_{band}_x{i}_y{j}.r8`** — from `coast/ground_x{i}_y{j}.tif`, four Byte bands in manifest order,
`class_res × class_res` (256), north-up, no flip, no rescale. Accept per-cell sums in `{0} ∪ [252, 255]`;
refuse `1..251` or `> 255` ("bands sum to n at (r, c)"). Record `weight_sum_histogram {252: n, 253: n,
254: n, 255: n, 0: n}` in the manifest. Tiles in `coast_manifest.tiles_without_dtm` get `weights: null`.

**Padding / missing**: `tiles_missing` copied; no heightmap invented; `pad_value_h16 = encode_h16(water_level)`
(32691), `pad_visibility: "hidden"`; padding placement is the importer's (north and east, UE_PLAN.md 3.3).

**`landscape_manifest.json`** (every key; the importer reads exactly these names):

```json
{"site": "thanet", "crs": "EPSG:27700", "origin": {"E": 627680, "N": 163080}, "vertical_datum": "ODN",
 "tile_m": 512, "res": 513, "nx": 26, "ny": 19, "weight_res": 256, "px_m": 1.0,
 "frame": "local-metres, X east, Y north, Z up", "frame_note": "<FRAME_NOTE>",
 "heightmap": {"file": "hm_x{i}_y{j}.r16", "dtype": "uint16 little-endian, row-major", "shape": [513, 513], "row0": "north", "col0": "west", "row_flip_for_ue": false,
               "z_encoding": {"formula": "h16 = round(z_m * 128) + 32768", "per_unit": 128, "offset": 32768, "scale_z_cm": 100, "decode": "z_m = (h16 - 32768) / 128", "quantum_m": 0.0078125, "max_roundtrip_error_m": 0.00390625},
               "range_limit_m": [-255, 255], "window_m": [-256.0, 255.99]},
 "clip_mask": {"file": "clip_x{i}_y{j}.r8", "semantics": "255 keep, 0 clipped-or-nodata after step 05; verification only"},
 "visibility": {"file": "vis_x{i}_y{j}.r8", "present_for": "straddle tiles", "semantics": "landscape visibility weight: 255 = hole, 0 = visible; absent file = 0 for kept tiles and 255 for tiles_clipped/tiles_missing/padding",
                "formula": "w = round(clamp(2/3 + d / (3 * px_m), 0, 1) * 255), d = signed metres into the clipped half-plane from clip.line (keep semantics of clip); the 2/3 iso-line is the clip line"},
 "weightmaps": {"files": "weight_{grass,sand,rock,water}_x{i}_y{j}.r8", "res": 256, "row0": "north", "bands": ["grass", "sand", "rock", "water"], "sum": "252..255 inside the clip, 0 outside", "alphamap_type": "Additive",
                "importer_note": "assemble the site mosaic (nx*256 x ny*256, cell centres at odd metres) and resample once, cell-centre-aware bilinear, to the padded vertex grid; renormalise to 255"},
 "weight_sum_histogram": {"255": 0, "254": 0, "253": 0, "252": 0, "0": 0},
 "range_m": [-2.91, 49.81], "elevation_units": "metres", "water_level": -0.6, "pad_value_h16": 32691, "pad_visibility": "hidden",
 "ue_import_unpadded": {"actor_location_cm": [0, -972800, 0], "actor_scale": [100, 100, 100], "verts": [13313, 9729], "quads_per_tile": 512,
                        "tile_quad_origin": "x0 = tile_m*i, y0 = tile_m*(ny-1-j); heightmap row r, col c -> landscape vertex (x0+c, y0+r)",
                        "padding_rule": "the importer pads to a valid component grid on the EAST and NORTH only and moves the actor by -100*pad_north in Y; these numbers are for the unpadded grid"},
 "clip": null, "tiles_clipped": [], "clipped_cells_total": 0, "source_nodata": null,
 "slope_qa": {"max_deg": 84.2, "pct_cells_over_45deg": 0.183, "note": "..."},
 "tiles_missing": [], "water_tiles": [], "tiles_without_ground_raster": [],
 "tiles": [{"x": 15, "y": 15, "files": {"heightmap": "hm_x15_y15.r16", "clip": "clip_x15_y15.r8", "vis": null, "weights": {"grass": "weight_grass_x15_y15.r8", "sand": "...", "rock": "...", "water": "..."}},
            "min_m": 0.39, "max_m": 22.69, "h16_min": 32817, "h16_max": 35673, "clip_state": "inside", "clipped_cells": 0, "clip_fill": "none",
            "source_nodata_cells": 0, "source_fill": "none", "slope_max_deg": 78.5, "slope_p99_deg": 32.5, "cells_over_45deg": 708, "quad_origin": [7680, 1536]}]}
```

`clip`, `tiles_clipped`, `clipped_cells_total`, `source_nodata`, per-tile `clip_state`/`clipped_cells`
come from the terrain manifest (null/empty on clipless sites); `slope_qa`, per-tile slope numbers,
`tiles_missing` copied verbatim; `water_tiles`, `tiles_without_ground_raster` from the coast manifest.
File names are bare, relative to `landscape/`.

### 13.4 Per-tile Streetscape documents

One `streetscape/site_x{i}_y{j}.json` per pipeline tile with any network record, schema 1.0.0, header
`{schema_version, site, crs, origin, vertical_datum, frame: FRAME, generator: "sources/adapters/unreal.py@<sha>",
materials (from unreal.json materials_hints), profiles: {road, edge, hedge} (only the ids referenced by
this document, copied from schema/profiles/*.json .profile), splines, junctions, _tile: {x, y, tile_m,
bounds_local}, _profile_ids_used}`. `load_profiles` reads `unreal.json streetscape.profiles_dir`
(`projects/one/schema/profiles`, repo-relative or absolute), validates the `{kind, id, profile}` shape,
refuses duplicates, and refuses at start-up if any id in `road_profile_by_class`, `rail_profile_by_gauge_m`,
`rail_profile_fallback`, `edge_profile_default`, `barrier.edge_profile`, `barrier.hedge_profile` is absent.

### 13.5 Spline record (verbatim schema; example: Trinity Square east run)

```json
{"id": "roads:30253079:0",
 "source": {"layer": "roads", "osm_id": "30253079", "name": "Trinity Square", "cls": "residential", "tile": [15, 15], "segment_index": 0, "segment_count": 1,
            "tags": {"sidewalk": "both", "lane_markings": "no", "surface": "asphalt", "maxspeed": "30 mph", "lit": "yes"}},
 "profile_ids": {"road": "road_residential", "edge_left": "edge_uk_kerb", "edge_right": "edge_uk_kerb", "hedge_left": null, "hedge_right": null},
 "points": [{"x": 8099.98, "y": 8171.12, "width_m": 6.0, "_z_06": 20.56}, ...],
 "segments": [{"id": "adapter", "s0_m": 0.0, "s1_m": null, "side": "both", "edge": {"pavement_width_m": 1.5}, "road": {"markings": []}}],
 "drop_kerbs": [],
 "overlay": {"kind": "osm_way", "osm_id": "30253079", "pts": [[8099.98, 8171.12, 20.56], ...]},
 "junction_start": "junction:15_15:0", "junction_end": null,
 "continues_from": null, "continues_to": "roads:879045149:0", "continuation_kind": {"from": null, "to": "way"},
 "overrun_points": {"before": null, "after": [7956.16, 8158.98, 18.51]},
 "flags": {"bridge": false, "tunnel": false, "z_gap": false, "steps": false, "disused": false, "gauge_unmapped": false, "closed_loop": false, "tracks": null}}
```

Rules:
- `id = "<layer>:<osm_id>:<segment_index>"`, `layer ∈ roads|rail|barriers`.
- `source.tags`: the tags in `unreal.json streetscape.tags_passthrough`, read from `other_tags` with
  `lib.tagval`, **strings only, absent omitted**; rail fields (`gauge`, `gauge_src`, `tracks`,
  `electrified`, `service`, `usage`) and barrier fields (`h_src`, `material`, `fence_type`, `wall`) are
  stringified into `tags` too.
- `points`: `{x, y, width_m (roads: w on every point), _z_06}` — **no `z`, no `roll_deg`, no `tags`**
  except `["steps"]` on the first point of `highway=steps`.
- Roads: `road = road_profile_by_class[cls]` (unmapped class → refusal); edges per the sidewalk rule:
  `sidewalk ∈ {both, yes, absent}` → both sides `edge_uk_kerb`; `left`/`right` (or `sidewalk:left|right =
  yes`) → that side only; `sidewalk = no` or `separate`, or `cls ∈ path_classes` → both null. Service /
  unclassified / living_street keep kerbs with `pavement_width_m = pav` (0 allowed: kerb without
  pavement). One whole-spline segment `{s0_m 0, s1_m null, side both, edge {pavement_width_m: pav}}` when
  `pav ≠ 1.8`; add `road {markings: []}` to it when `lane_markings = no`; omit the segment entirely when
  neither applies.
- Rail: `road = rail_profile_by_gauge_m[f"{gauge:.3f}"]` else `rail_profile_fallback` + `flags.gauge_unmapped`
  and a manifest count; `flags.disused` for `cls = disused`; `flags.tracks = tracks`; edges/hedges null.
- Barriers: `edge_left = barrier.edge_profile` (`edge_barrier_only`), one segment
  `{s0_m 0, s1_m null, side left, edge {barrier {type, height_m: h, thickness_m: default_thickness_m[type],
  material: material_by_type[type], post_pitch_m: default_post_pitch_m[type] (fences), offset_m: −thickness_m/2}}}`;
  `hedge` class → `hedge_left = barrier.hedge_profile`, segment `{side left, hedge {present true,
  height_m: h, width_m: default_thickness_m.hedge, offset_m: −width_m/2}}`; `kerb` class → `edge_left =
  edge_uk_kerb` with segment `{edge {pavement_width_m: 0}}` and no barrier; unknown class → skipped and
  counted (`skipped_barriers {cls: n}`). `height_m = h` from step 11 (`h_src` into tags); the adapter's
  `default_height_m` applies only when `h` is missing, and says so in the manifest.
- `flags.bridge/tunnel/z_gap` from the records. No deck offsets.
- `junction_start/junction_end` from 13.8; `continues_*` etc. from 13.6.

### 13.6 Seams and way joins — `order_runs`

All records of one `(layer, osm_id)` are grouped across tile files and ordered **along the raw OSM
way**: for each run, project its first vertex onto the raw polyline (from the GeoPackage) and take
`(segment index, t)` as its key; sort; `segment_index` counts along the way; for a closed loop
(`raw[0] == raw[-1]`, `flags.closed_loop`) segment 0 is the run containing raw vertex 0. Consecutive runs
that share their seam vertex (exact equality of the rounded `[E, N]`) get `continuation_kind "seam"`;
consecutive runs separated by an off-grid / off-clip excursion get `"gap"` (counted `ways_with_gaps`).
A way end shared with exactly one other way of the same layer and no `_junction` within
`junction_snap_m` (0.3) → `"way"`; otherwise null. `overrun_points.before/after` = the neighbour's second
point (local metres), null at dead ends and junctions. Refuse only when a run's first vertex is farther
than 1.0 m from the raw way (edited output). Margate facts this handles: 632 multi-run ways, 3 loop ways
crossing a seam, 41 single-run loops, 3,577 off-grid vertices.

### 13.7 Waypoint thinning — `thin_against_interpolant`

06's ~2 m vertices over-constrain the Catmull-Rom. Thinning keeps the first and last vertex (seam /
junction nodes) and every vertex within 0.3 m of a junction disc or way join, starts from Douglas-Peucker
at `thin_tolerance_m`, then iterates: evaluate the centripetal Catmull-Rom through the kept points
(`catmull_rom_dense`, 32 samples per segment), find the original vertex farthest from that curve, add it
while the distance exceeds `thin_tolerance_m` (**0.10 m**, `unreal.json`). Measured on the test stretch:
115 → 15 points, max deviation 0.093 m (DP alone at 5 cm keeps 13 points but deviates 0.247 m under the
interpolant). `thin_tolerance_m 0` keeps 06's vertices verbatim (with duplicates merged by the reader).
Manifest: `points_in`, `points_out`, `thin_tolerance_m`, `thin_max_dev_m` (against the interpolant).

### 13.8 Junctions

Each `_junction` record → `{"id": "junction:<i>_<j>:<k>", "x", "y", "z": z06, "radius_m": r, "kind": "disc",
"ends": [{"spline_id", "end"}]}` for every spline in the same document whose first/last point lies
within `junction_snap_m`; those splines get `junction_start`/`junction_end` set.

### 13.9 Debug overlay — `clip_polyline`

`overlay.pts` = the raw OSM way vertices for the **whole way**, clipped to the grid rectangle and to the
clip half-plane with `lib.keep_points`, the exact crossing point inserted on the line / grid edge
(Sutherland–Hodgman against the four grid edges then the clip line); `z` = nearest step-06 vertex of the
same way (`nearest_z`), the crossing point takes the last kept vertex's `z`. Counts
`overlay_vertices_dropped`, `overlay_ways_clipped`. A raw way split into several pieces by the clip
yields the piece containing this run's vertices. Both engines lift the overlay by 0.3 m (DESIGN.md 5.5).

### 13.10 Massing, furniture, root manifest, tests, refusals

**Massing**: every step-07 field kept; `rings[*].pts` → local metres (3 dp); `base_z`, `skirt`, `h`,
`ridge`, `eaves` untouched. `massing_manifest.json` = the pipeline manifest + `{"frame": FRAME,
"frame_note", "coordinates": "rings in local metres, base_z/skirt ODN metres", "files": n}`.

**Furniture**: `{id, prop, name, x, y, z (or null), bearing, heading_deg, src, d, cls, nudged}` with
`heading_deg = bearing_to_heading_deg(bearing)`; `furniture_manifest.json` = pipeline `qa_furniture.json`
keys + `frame`, `frame_note`, `ue_yaw: "yaw_ue = bearing - 90 = -heading_deg (applied by the loader)"`.

**`streetscape_manifest.json`**:
```json
{"site", "crs", "origin", "tile_m", "nx", "ny", "frame", "schema_version", "generator", "profiles_dir", "per_tile": true, "documents": n,
 "splines_by_layer": {"roads": n, "rail": n, "barriers": n}, "points_in": n, "points_out": n, "thin_tolerance_m": 0.10, "thin_max_dev_m": x,
 "ways": n, "ways_multi_run": n, "ways_with_gaps": n, "closed_loops": n, "junctions": n, "seam_joins": n, "way_joins": n,
 "skipped_barriers": {"cls": n}, "barriers_by_type": {"brick_wall": n, ...}, "barrier_height_defaulted_by_adapter": n, "gauge_unmapped": n,
 "overlay_vertices_dropped": n, "overlay_ways_clipped": n, "tags_coverage": {"sidewalk": n, ...}, "profile_ids_used": {"road": [], "edge": [], "hedge": []}, "warnings": []}
```

**`unreal_manifest.json`**:
```json
{"site", "crs", "origin": {"E", "N"}, "tile_m", "nx", "ny", "res", "vertical_datum", "frame", "frame_note", "schema_version", "generator",
 "adapter_settings": <copy of unreal.json>, "products": {"landscape": {"dir", "manifest", "files"}, "streetscape": {...}, "massing": {...}, "furniture": {...}},
 "sources": {"terrain": {"manifest", "tiles", "range_m", "slope_qa", "tiles_clipped"}, "networks": {"manifest", "segments", "junctions"}, "linear": {"manifest", "rail_segments", "barrier_segments"} | null,
             "coast": {"manifest", "tiles", "water_tiles"}, "massing": {"manifest", "buildings"}, "furniture": {"manifest", "placed"}}}
```

**`sources/tests/test_unreal_adapter.py`** (numpy + fake GDAL, standalone; `importlib` load by path,
never `import unreal`): pure functions — `encode/decode_h16` round trip ≤ 1/256 m and known values
(`encode(0) = 32768`, `encode(−0.6) = 32691`, `encode(255) = 65408`, `encode(−1.0) = 32640`);
`check_range` refusals; the frame table of DESIGN.md 2 incl. `bearing 270 → heading −180`;
`visibility_weight(0) = 170`, `(1) = 255`, `(−2) = 0`; `thin_against_interpolant` on a straight line
→ 2 points and on an arc keeps ≥ 6; `order_runs` on shuffled runs incl. a loop and a gap; `parse_height_m`;
`classify_barrier`; `clip_polyline` inserts the crossing point. Synthetic site `_ut_unreal` (2 × 1 tiles of
64 m, clip line at E0 + 118, fixtures written directly incl. a 32×32 ground raster with a **sum-254 cell
(fractions 0.3/0.7)** and step-11 rail/barrier files): r16 decodes within 1/256 m with row 0 north and
the shared column bit-identical; clip mask 650 zeros == `clipped_cells`; `vis` file present for the
straddle tile with `w = 170` on the line; weights unflipped with the 254 cell accepted; manifest keys
of 13.3 present; both site documents validate against `schema/streetscape.schema.json` via the
validator in `projects/one/Tools/blender/tests/schema_check.py`; ids, `profile_ids`, segments, seam
`continues_*`, overlay clipped, junction ends, thinning counts, massing/furniture conversions; refusals
(range, shape, unknown profile id, stale clip, clipped-cells disagreement, bands summing to 100).

**`dryrun.py` hook** (pipeline task adds it): run the adapter on A, B, C; assert `unreal_manifest`
round-trips `origin`/`tile_m`/`nx`/`ny`/`res`; site C `clipped_cells == clip-mask zeros`, `vis` present
for straddle tiles, `clip` block copied; A/B: no clip, all-255 masks, no `vis` files.

**Refusals** (`sys.exit`): missing source manifest/dir; `range_m` outside `[-255, 255]`; tile shape;
config clip vs terrain manifest clip (absent or different line); clipped-cells disagreement; profile id
absent from `profiles_dir` or bad file shape; class without a profile mapping; duplicate profile ids;
ground raster shape or a cell summing to `1..251` or `> 255`; `rail_*`/`barriers_*` present without
`linear_manifest.json`; a run that cannot be located on its raw way; GeoPackage missing. Warnings
(counted, never fatal): step 11 not run; unmapped gauge; skipped barrier classes; `median (degraded)`
fill.

### 13.11 `sources/adapters/unreal.json`

```json
{
  "_note": "Unreal / Streetscape-JSON consumer settings. Nothing in sources/derive/ reads this file. The adapter emits the Streetscape frame of projects/one/docs/BRIEF.md 4.2; the x100 / Y-flip / yaw sign to Unreal are applied ONLY by the Unreal plugin and are quoted here for the record.",
  "frame": {"statement": "x = E - E0 (east), y = N - N0 (north), z = ODN metres. Unreal: X_ue = 100*x, Y_ue = -100*y, Z_ue = 100*z (cm). yaw_ue = bearing - 90 = -heading_deg.",
            "worked_example": {"survey": [635253.6, 171027.6, 17.2], "origin": [627680, 163080], "local": [7573.6, 7947.6, 17.2], "ue_cm": [757360.0, -794760.0, 1720.0], "bearing_deg": 131.0, "heading_deg": -41.0, "ue_yaw_deg": 41.0}},
  "landscape": {"heightmap_name": "hm_x{i}_y{j}.r16", "clip_name": "clip_x{i}_y{j}.r8", "vis_name": "vis_x{i}_y{j}.r8", "weight_name": "weight_{band}_x{i}_y{j}.r8",
                "z_scale_cm": 100, "encoding": {"per_unit": 128, "offset": 32768, "formula": "h16 = round(z_m * per_unit) + offset"}, "range_limit_m": [-255.0, 255.0],
                "clipped_fill": "nearest", "visibility_ramp_px": 3, "weight_sum_accept": [252, 255],
                "note": "per_unit 128 and offset 32768 are the engine's own (LANDSCAPE_ZSCALE = 1/128, MidValue 32768, Engine/Source/Runtime/Landscape/Public/LandscapeDataAccess.h:13,27); with the landscape actor's Z scale = z_scale_cm the engine height in cm is exactly 100 * z_m to 0.78 cm. The encodable window is -256.0..+255.99 m; range_limit_m keeps a 1 m margin and the adapter REFUSES a site outside it rather than clamping the way GetTexHeight (LandscapeDataAccess.h:35) silently would. visibility_ramp_px: the visibility weight ramps from 2/3 on the clip line to 1 over ramp/3 px into the cut so the 2/3 iso-line is the line itself.",
                "cliffs_note": "The data holds cliff faces at 65-84 degrees (terrain_manifest.slope_qa). Import at 1 m (513 verts per 512 m tile), never resample, and compare the in-engine slope against slope_qa copied into landscape_manifest.json."},
  "streetscape": {
    "schema_version": "1.0.0", "profiles_dir": "projects/one/schema/profiles", "per_tile": true,
    "thin_tolerance_m": 0.10, "thin_note": "max distance of any step-06 vertex from the centripetal Catmull-Rom through the kept points (the schema's interpolant); 0 keeps every vertex.",
    "junction_snap_m": 0.3, "run_locate_tolerance_m": 1.0, "overlay_lift_note": "renderers re-drape overlay.pts and lift 0.3 m; z in the file is the nearest step-06 vertex, informative",
    "tags_passthrough": ["sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both", "lanes", "lanes:forward", "lanes:backward", "lane_markings", "oneway", "surface", "maxspeed", "lit",
                         "parking:lane:left", "parking:lane:right", "parking:lane:both", "gauge", "electrified", "service", "usage", "height", "material", "fence_type", "wall"],
    "road_profile_by_class": {"motorway": "road_trunk", "motorway_link": "road_trunk", "trunk": "road_trunk", "trunk_link": "road_trunk", "primary": "road_primary", "primary_link": "road_primary",
                              "secondary": "road_secondary", "secondary_link": "road_secondary", "tertiary": "road_tertiary", "tertiary_link": "road_tertiary", "residential": "road_residential",
                              "unclassified": "road_unclassified", "living_street": "road_living_street", "service": "road_service", "pedestrian": "road_pedestrian",
                              "track": "path_track", "bridleway": "path_track", "cycleway": "path_cycleway", "footway": "path_footway", "path": "path_footway", "steps": "path_footway"},
    "path_classes": ["footway", "path", "steps", "cycleway", "bridleway", "track", "pedestrian"],
    "edge_profile_default": "edge_uk_kerb",
    "edge_rule": "edge_left/edge_right = edge_uk_kerb unless sidewalk is 'no'/'separate' or cls is a path class; sides from sidewalk / sidewalk:left / sidewalk:right, default both; pavement_width_m = pav via a whole-spline segment when pav != 1.8 (0 allowed: kerb without pavement)",
    "markings_rule": "lane_markings=no -> segment road.markings = []",
    "rail_profile_by_gauge_m": {"1.435": "rail_standard"}, "rail_profile_fallback": "rail_standard",
    "barrier": {"edge_profile": "edge_barrier_only", "hedge_profile": "hedge_privet",
      "type_rules": [["wall", {"material": "brick"}, "brick_wall"], ["wall", {"wall": "brick"}, "brick_wall"], ["wall", {"material": "concrete"}, "concrete_wall"], ["wall", {"wall": "concrete"}, "concrete_wall"], ["wall", {"wall": "seawall"}, "concrete_wall"],
                     ["wall", {"material": "stone"}, "stone_wall"], ["wall", {"wall": "stone_wall"}, "stone_wall"], ["wall", {"wall": "dry_stone"}, "stone_wall"], ["wall", {"wall": "flint"}, "stone_wall"], ["wall", {}, "brick_wall"],
                     ["city_wall", {}, "stone_wall"], ["fence", {"fence_type": "chain_link"}, "chain_link"], ["fence", {"fence_type": "railing"}, "railing"], ["fence", {"fence_type": "bars"}, "railing"], ["fence", {"fence_type": "metal"}, "railing"],
                     ["fence", {"material": "metal"}, "railing"], ["fence", {"fence_type": "wood"}, "wood_fence"], ["fence", {"material": "wood"}, "wood_fence"], ["fence", {}, "wood_fence"],
                     ["guard_rail", {}, "guard_rail"], ["handrail", {}, "railing"], ["retaining_wall", {}, "retaining_wall"], ["kerb", {}, "kerb"], ["hedge", {}, "hedge"]],
      "height_source": "step 11 record field h (metres, parsed or defaulted there, see h_src); default_height_m below applies only to a record without h and is counted",
      "default_height_m": {"brick_wall": 1.8, "concrete_wall": 1.8, "stone_wall": 1.5, "chain_link": 1.8, "guard_rail": 0.75, "railing": 1.1, "wood_fence": 1.8, "retaining_wall": 1.5, "hedge": 1.5},
      "default_thickness_m": {"brick_wall": 0.215, "concrete_wall": 0.20, "stone_wall": 0.45, "chain_link": 0.05, "guard_rail": 0.10, "railing": 0.05, "wood_fence": 0.05, "retaining_wall": 0.30, "hedge": 0.8},
      "default_post_pitch_m": {"chain_link": 3.0, "wood_fence": 1.8, "railing": 2.0, "guard_rail": 4.0},
      "material_by_type": {"brick_wall": "brick_red", "concrete_wall": "concrete_wall", "stone_wall": "stone_flint", "retaining_wall": "concrete_wall", "chain_link": "chain_link", "wood_fence": "wood_fence", "railing": "steel_painted_black", "guard_rail": "steel_painted_black"},
      "offset_rule": "offset_m = -thickness_m/2 (hedge: -width_m/2) so the geometry is centred on the OSM way; 'kerb' -> edge_uk_kerb with pavement_width_m 0 and no barrier; 'hedge' -> the hedge renderer",
      "note": "Opinions, not survey. First matching rule wins; the bare-class rules are the defaults. A cls with no rule is skipped and counted."},
    "materials_hints": "copied into every document's materials block from projects/one/schema/examples/test_stretch.json materials",
    "note": "footway/path/steps/cycleway/bridleway/track/pedestrian are Renderer-A flat ribbons with path_*/road_pedestrian profiles and NO edge renderer. All classes present in tuning.json roads.widths_m must appear in road_profile_by_class; the adapter refuses otherwise."
  },
  "massing": {"note": "rings to local metres; base_z/skirt unchanged (Z is up in this frame)."},
  "furniture": {"note": "x,y local; z kept (null = drape); bearing kept; heading_deg = ((90 - bearing + 180) mod 360) - 180 in [-180, 180). The loader's yaw_ue = bearing - 90 is NOT written per record (BRIEF 4.2)."}
}
```

### 13.12 cls → profile map (summary)

| OSM | profile ids |
|---|---|
| `highway` motorway/trunk (+links) | road `road_trunk`; edges per sidewalk rule |
| primary / secondary / tertiary (+links) | `road_primary` / `road_secondary` / `road_tertiary` |
| residential / unclassified / living_street / service | `road_residential` / `road_unclassified` / `road_living_street` / `road_service`; edges `edge_uk_kerb` with `pavement_width_m = pav` |
| pedestrian | `road_pedestrian`, edges null |
| footway / path / steps | `path_footway`, edges null (`flags.steps`) |
| cycleway | `path_cycleway`; track / bridleway | `path_track` |
| `railway` any emitted class, gauge 1.435 | `rail_standard` (other gauges: `rail_standard` + `flags.gauge_unmapped`) |
| `barrier` wall / city_wall / fence / guard_rail / handrail / retaining_wall | `edge_barrier_only` + one barrier segment of the mapped type |
| `barrier` kerb | `edge_uk_kerb` + `pavement_width_m 0` |
| `barrier` hedge | `hedge_privet` + one hedge segment |

### 13.13 Contracts assumed

Pipeline 05/09/11 as in §3 and §4 (taken as given); `dryrun.py` hook and `OUTPUT.md` sentence from
the pipeline task; `schema/profiles/*.json` with the 20 ids and the `{kind, id, profile}` shape;
UE importer reads `landscape_manifest.json` as written (UE_PLAN.md 4.1); the geometry core reads
`hm_*.r16 + clip_*.r8` through `Heightfield.from_landscape_dir` (DESIGN.md 8).
