# Terrain and roads — the diagnosis behind D1, D2 and D3

Written 2026-09-09 by the diagnostic agent. **No production code was changed by this round.**
Everything here is measured, not asserted; every number is followed by the command that produced it
and the JSON it was read out of. The measuring tools are new and reusable, under
`projects/one/Tools/diag/`; their raw output is under `projects/one/Saved/Diag/` (git-ignored).

Alex's report — *"the real road geometry is still fusing with the landscape"* — is D3. It is real,
it is pervasive, and it is **not** primarily a smoothing-window problem. D1 and D2 are separate,
smaller, and both turn out to be one-line-of-cause defects.

Read `BRIEF.md` §1.1 ("LIDAR / HEIGHT MAPPING", "SEAM AND OVERLAP RULES") and `DESIGN.md` §3, §5,
§8, §9 first; this document assumes them.

---

## 0. Environment for every command below

```sh
cd /c/Users/Shadow/code/3duk
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"     # the /c/ form; GDAL + LAPACK
PY=C:/Users/Shadow/code/3duk-env/env/python.exe
```

Products read: `data/thanet/out/terrain/` (391 GeoTIFF tiles + manifest),
`data/thanet/raw/lidar/` (782 raw EA rasters), `data/thanet/out/unreal/landscape/`
(391 `hm_*.r16` + `clip_*.r8` + 31 `vis_*.r8` + weights + manifest),
`data/thanet/out/unreal/streetscape/` (246 `site_x*_y*.json`, 15,422 splines),
and the saved level `/Game/Thanet/Maps/Thanet` (2,067 components, 140 proxies).

---

## 1. Headline findings

| | finding | number |
|---|---|---|
| **D1** | Adjacent tiles disagree on the row/column they share. | 85 of 737 adjacent tile pairs; 28,725 of 370,797 visible shared samples (7.75 %); worst **5.336 m** where a player can see it, **10.953 m** including ground hidden behind the Wantsum cut. |
| **D1 cause** | Proven: **every** disagreeing cell is a cell the survey never measured. | 29,188 of 29,188 disagreeing cells had raw NoData on at least one side. The raw rasters agree at those edges **exactly**: 0 of 330,946 comparable raw edge cells disagree, max 0.000 m. |
| **D1 scope** | 77 of 391 tiles touch a disagreeing edge. No disagreeing cell is on surveyed ground, so **no road corridor is affected** — D1 and D3 are independent. |
| **D2** | The heightfield and the ALandscape are **the same data**. They agree at every grid post to **0.53 mm**. They differ only in how they interpolate *between* posts: bilinear vs the landscape's triangles. | Off-vertex max 1.909 m on steep ground, 0.134 m on a uniform scatter; the numpy prediction explains the engine's answer to a residual of **0.59 mm** over 6,866 points. |
| **D2 "0.52 m"** | It is the interpolation bound `|twist|/4` of one 1 m quad with twist 2.08 m. 25,937 of 98,643,766 quads (0.026 %) exceed 0.50 m; the site maximum bound is 6.121 m. | Survives fixing D1 — it is unrelated to the seams except at the 1.3 % of points that sit within 1 m of a tile boundary. |
| **D3** | **89.7 %** of road stations have terrain above the road surface somewhere across the carriageway: **24.008 km of the 26.726 km sampled**. | median penetration 6.1 cm, p95 27.5 cm, p99 63.1 cm, max 4.145 m. |
| **D3 driver** | **Not** the 20 m smoothing window. At W = 5 m the fraction is *higher* (93.5 %). The dominant term is the flat/cambered ribbon meeting a rough, cross-sloping 1 m DTM. | T2 (cross-section) is negative at **94.4 %** of stations; T1 (longitudinal smoothing) at only **47.3 %**. |
| **Recommendation** | **(a) conform the landscape to the road over a corridor**, implemented as a new deterministic pass that writes a *new* product directory and leaves the survey untouched. | Core corridor 7.014 km² = 7.11 % of the 98.667 km² kept land; median change 4.1 cm, p95 0.34 m, p99 1.10 m. |

---

## 2. D1 — the tile-boundary seams

### 2.1 Geometry of a shared edge

`grid_res 513 = 512 + 1`, so neighbours **share a row of samples**. Verified from the GeoTransforms:

```sh
$PY -c "from osgeo import gdal; gdal.UseExceptions()
for f in ['dtm_x10_y10.tif','dtm_x11_y10.tif','dtm_x10_y11.tif']:
    d=gdal.Open('data/thanet/out/terrain/'+f); print(f, d.RasterXSize, d.RasterYSize, d.GetGeoTransform())"
```
```
dtm_x10_y10.tif 513 513 (632799.5, 1.0, 0.0, 168712.5, 0.0, -1.0)
dtm_x11_y10.tif 513 513 (633311.5, 1.0, 0.0, 168712.5, 0.0, -1.0)
dtm_x10_y11.tif 513 513 (632799.5, 1.0, 0.0, 169224.5, 0.0, -1.0)
```

Tile `x10` column 512 has its centre at E 633312.0; tile `x11` column 0 has its centre at E 633312.0.
Tile `y10` row 0 is N 168712.0; tile `y11` row 512 is N 168712.0. So:

* **east neighbour**: `(i, j)` column 512 ≡ `(i+1, j)` column 0
* **north neighbour**: `(i, j)` row 0 ≡ `(i, j+1)` row 512

Both writes come from the same source raster and must be bit-identical.

### 2.2 What the survey product does

```sh
$PY projects/one/Tools/diag/seam_audit.py --site thanet \
    --out projects/one/Saved/Diag/seam_audit.json
```
`projects/one/Saved/Diag/seam_audit.json` → `summary`:

```
tiles_present                        391
pairs                                737   (372 horizontal, 365 vertical)
pairs_disagreeing                     85
tiles_touching_a_disagreeing_edge     77
cells_compared                   370,797
cells_disagreeing                 29,188   (7.87 %)
edge_max_m       max 5.339467525482178   p99 3.5968377065658554   p50 0.0
```

Worst edges (product, GeoTIFF, metres):

| kind | tiles | max | cells | fill A | fill B |
|---|---|---|---|---|---|
| h | (23,17)\|(24,17) | 5.3395 | 54 | nearest | nearest |
| v | (24,17)\|(24,18) | 5.2900 | 297 | nearest | nearest |
| v | (23,1)\|(23,2) | 4.9899 | 108 | nearest | nearest |
| v | (23,2)\|(23,3) | 4.7835 | 106 | nearest | nearest |
| h | (23,2)\|(24,2) | 4.0600 | 513 | nearest | all-nodata → −0.6 |
| h | (24,0)\|(25,0) | 3.8000 | 513 | nearest | all-nodata → −0.6 |
| h | (11,17)\|(12,17) | 3.6344 | 330 | nearest | nearest |

### 2.3 The raw source agrees exactly — proof of cause

The same tool reads `data/thanet/raw/lidar/dtm_x*_y*.tif` at the identical edges:

```
raw_totals: pairs_with_raw 737,  raw_cells_compared 330,946,
            raw_cells_disagreeing 0,  raw_max_m 0.0
hypothesis_per_tile_fill:
  product_disagreeing_cells_where_raw_had_nodata_on_a_side   29,188
  product_disagreeing_cells_where_raw_was_valid_on_both_sides      0
  of_those_max_raw_disagreement_m                                0.0
```

**The raw EA rasters are bit-identical on every shared edge. Every single disagreeing cell in the
product is a cell whose raw value was NoData on at least one side.** The hypothesis is confirmed
with no exceptions: the cause is entirely `sources/derive/05_export_terrain.py` calling
`lib.fill_nodata(a, bad, …)` on **one 513×513 tile at a time** (`sources/lib.py:84-116`,
`scipy.ndimage.distance_transform_edt` on that tile's array), so the two tiles sharing a NoData
edge cell each copy the nearest valid value **from inside themselves** and land on different
answers. Nothing downstream introduces the disagreement; the adapter and the importer faithfully
carry it through (the importer already says so —
`Plugins/Streetscape/Source/StreetscapeEditor/Private/StreetscapeLandscapeImporter.cpp:1049-1057`).

### 2.4 The product the landscape is actually built from

`hm_*.r16` has no NoData (clipped cells are filled nearest-valid and the masks carry the truth), so
a shared edge there can disagree for two different reasons and they must be separated:

```sh
$PY projects/one/Tools/diag/seam_audit_r16.py --out projects/one/Saved/Diag/seam_r16.json
```
```
pairs                                737
pairs_disagreeing_any                115
pairs_disagreeing_visible             85
tiles_touching_a_visible_seam         77
samples_disagree_any              35,951
samples_visible                  370,797
samples_disagree_visible          28,725      (7.75 %)
max_h16_any        1402  ->  10.953125 m      <- includes ground hidden behind the clip
max_h16_visible     683  ->   5.3359375 m     <- what a player can see
per_edge_visible_max_m: max 5.3359375  p99 3.59625  p50 0.0
```

This reconciles the two figures in circulation: **10.95 m** is the worst shared-edge step anywhere
in the adapter product (mostly invented ground behind the Wantsum cut, never rendered); **5.336 m**
is the worst step on ground the visibility layer leaves visible. The importer's
`shared_edge_max_h16_delta 2267` (`projects/one/Saved/Tests/gate_c.json`) is larger again because it
runs over the *assembled, padded* landscape, which also butts real tiles against the padding fill.

Worst visible seams, located in site-local metres (x east, y north from origin E 627680 N 163080):

| tiles | max | cells | where |
|---|---|---|---|
| (23,17)\|(24,17) | 5.336 | 54 | x = 12288, y ∈ [8704, 9216] |
| (24,17)\|(24,18) | 5.289 | 297 | y = 9216, x ∈ [12288, 12800] |
| (23,1)\|(23,2) | 4.984 | 108 | y = 1024, x ∈ [11776, 12288] |
| (23,2)\|(23,3) | 4.781 | 89 | y = 1536, x ∈ [11776, 12288] |
| (23,2)\|(24,2) | 4.063 | 513 | x = 12288, y ∈ [1024, 1536] |
| (11,17)\|(12,17) | 3.633 | 330 | x = 6144, y ∈ [8704, 9216] |

All of the worst are at the north-east and south-east margins — foreshore and open sea.

### 2.5 How much of the isle, and is any of it on real ground

* 77 of 391 tiles (19.7 %) touch a disagreeing edge.
* 28,725 visible shared samples of 370,797 (7.75 %) disagree — 28.7 km of seam line out of 371 km.
* **No disagreeing cell is on surveyed ground.** Every one had raw NoData on a side (§2.3).

### 2.6 What the fix has to cope with — the reach measurement

The obvious cheap fix ("fill each tile with a halo of its neighbours") does not work here, and the
reason is worth knowing before anyone tries it:

```sh
$PY projects/one/Tools/diag/nodata_reach.py --out projects/one/Saved/Diag/nodata_reach.json
```
```
mosaic                       13313 x 9729
cells_in_kept_tiles            102,521,345
cells_nodata_raw                14,601,593    (14.24 % of the kept grid)
reach_m   max 1378.82   p99 1220.84   p95 995.92   p50 319.78   mean 386.04
shared_edge_nodata_cells            69,297
shared_edge_reach_m  max 1378.82  p99 1336.11  p95 1078.03  p50 350.49
halo_needed_px  for_all_nodata 1379   for_shared_edges_only 1379
```

`reach` = Euclidean distance, in 1 m cells, from a NoData cell to the nearest *surveyed* cell,
computed once over the whole site mosaic. Distribution of reach for the 69,297 NoData cells that sit
on a shared edge (bins in metres):

| ≤1.5 | ≤3 | ≤5 | ≤10 | ≤20 | ≤50 | ≤100 | ≤200 | ≤500 | ≤1000 | >1000 |
|---|---|---|---|---|---|---|---|---|---|---|
| 806 | 964 | 1040 | 1520 | 2075 | 4410 | 5119 | 7581 | 19914 | 20497 | 5371 |

Only 2,810 of 69,297 (4.1 %) are within 5 m of surveyed ground — those are genuine inland gaps.
**95.9 % are open sea**, hundreds of metres from anything measured, and step 05 is currently
"nearest-valid"-filling them by copying coastal land heights up to 1.379 km out to sea. That is
where the 5 m steps come from: two tiles copy different bits of coast into the same water.

**Two things the D1 fix must do**, in this order of importance:

1. **Do not nearest-fill open sea.** A NoData cell whose reach exceeds a small threshold has no
   nearest valid neighbour worth the name; it is not a gap, it is beyond the survey. It belongs at
   the site `water_level` (−0.6 m for Thanet, already the `EMPTY_FILL` step 05 uses for wholly
   NoData tiles) and must be recorded as fabricated, exactly as `tiles_fabricated` already is. This
   alone removes 95.9 % of the disagreeing edge cells *and* removes a large honesty problem that has
   nothing to do with seams.
2. **Fill the remaining real gaps once, over the mosaic, not per tile.** Step 03 already builds
   `dtm.vrt` over the whole grid; one `distance_transform_edt` over 13313 × 9729 completed inside
   this diagnostic run on this machine (`nodata_reach.py`, well under the Bash tool's limit), so it
   is affordable. A per-tile fill with a halo is only equivalent if the halo exceeds the reach; the
   number above (1,379 px) says a halo is the wrong shape of fix.

Owner: **pipeline track** (`sources/derive/05_export_terrain.py`, `sources/lib.py`). The manifest
must gain a per-tile `fill_reach_max_m` and a site-level `sea_fill_cells` so the change is recorded,
and `sources/tests/dryrun.py` needs a synthetic site whose NoData straddles a tile boundary with the
assertion that the two shared edges are bit-identical. Margate has 0 % NoData
(`BRIEF.md` §2 / §8), so **byte identity for Margate is unaffected by construction** — but that must
be re-proved with `sources/tests/regress_outputs.sh compare margate before`, not assumed.

---

## 3. D2 — "two terrain truths"

### 3.1 Method

7,000 points: 5,000 uniform scatter over the site, 1,000 restricted to ground ≥ 20° (the claim is
"on steep ground"), 1,000 snapped to integer metres (exactly on landscape vertices, to isolate the
interpolation term). Each sampled three ways:

```sh
# (a) numpy Heightfield over the r16 bytes the plugin reads, and (b) the source GeoTIFF via GDAL
$PY projects/one/Tools/diag/terrain_truths.py --mode emit --out projects/one/Saved/Diag/d2_ab.json

# (c) the imported ALandscape, headless
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 \
   -Script 04_probe.py -Render -Log diag_d2_probe.log \
   -Args "--points .../Saved/Diag/d2_points.csv --landscape"
# -> THANET_OK 04_probe {"blocked": 7000, "clipped": 0, "elapsed_s": 193.8, "landscape": true,
#     "landscape_none": 0, "max_abs_dz_m": 3.18759, "points": 7000, "regions_loaded": 314,
#     "sample_mode": "bilinear", "unclipped": 7000}

$PY projects/one/Tools/diag/terrain_truths.py --mode join --out projects/one/Saved/Diag/d2_join.json
$PY projects/one/Tools/diag/interp_decompose.py --out projects/one/Saved/Diag/d2_interp.json
```

### 3.2 Term by term

**A — r16 quantisation only.** `z_heightfield − z_geotiff` over all 7,000 points
(`d2_ab.json`, `d2_join.json:A_heightfield_vs_geotiff`):

```
max 0.0038928985595703125   p99 0.0037462985515594   p50 0.0013628253132230   rms 0.0016918459044848
```

The maximum is `0.00390625 = 1/256` m — **exactly half the 1/128 m quantum**, which is the manifest's
own `max_roundtrip_error_m`. Nothing else differs: the adapter's heightmap *is* the step-05 DTM to
within the encoding. No fill, clip or padding effect appears (`hf_nan 0`, `tif_nan 0`).

**B — heightfield vs the ALandscape** (`d2_join.json`):

| subset | n | max | p99 | p95 | p50 | rms |
|---|---|---|---|---|---|---|
| all | 6,958 | **3.18755** | 0.10133 | 0.01622 | 0.00049 | 0.07537 |
| **at integer-metre vertices** | 1,000 | **0.000525** | 0.00036 | 0.00021 | 0.000038 | 0.000095 |
| between vertices | 5,958 | 3.18755 | 0.11926 | 0.01901 | 0.00083 | 0.08145 |
| steep (≥ 20°) | 996 | 3.18755 | 0.74807 | 0.14170 | 0.00550 | 0.17300 |
| within 1 m of a tile boundary | 92 | 3.18755 | 3.10068 | 0.90779 | 0.00015 | 0.55239 |

By terrain slope (`slope_buckets_B`, |Δ| m):

| slope | n | max | p99 | p95 | p50 |
|---|---|---|---|---|---|
| 0–2° | 3,506 | 0.0264 | 0.0099 | 0.0049 | 0.00014 |
| 2–5° | 1,807 | 0.0790 | 0.0161 | 0.0083 | 0.00055 |
| 5–10° | 459 | 0.0519 | 0.0276 | 0.0109 | 0.00082 |
| 10–20° | 128 | 0.0805 | 0.0489 | 0.0244 | 0.00098 |
| 20–45° | 841 | 0.9297 | 0.2310 | 0.0673 | 0.0042 |
| 45–90° | 215 | **3.1876** | 1.8968 | 0.4626 | 0.0178 |

**C — GeoTIFF vs ALandscape** is B plus A and is numerically B: max 3.18630, p99 0.10164.

**There is only one terrain truth at the grid posts.** At integer metres the three products agree to
0.53 mm — that is `float` storage plus the probe's four-decimal print, and it satisfies
`DESIGN.md` §8's stated "tolerance of 1 cm at vertices" by a factor of 19. What is called "two
truths" is **two interpolation rules between the posts**.

### 3.3 The interpolation rule, exactly

`UStreetHeightfieldTerrain` defaults to bilinear (`EStreetHeightSampling::Bilinear`,
`Plugins/Streetscape/Source/Streetscape/Private/StreetTerrainSource.cpp:174-177`); the ALandscape is
a triangle mesh and Chaos interpolates over the quad's two triangles
(`Engine/Source/Runtime/Experimental/Chaos/Private/Chaos/HeightField.cpp:937-969`, reached from
`ALandscapeProxy::GetHeightAtLocation` → `ULandscapeHeightfieldCollisionComponent::GetHeight` →
`FHeightField::GetHeightAt`, `Engine/Source/Runtime/Landscape/Private/LandscapeCollision.cpp:2703,
2517-2552`). The plugin already implements exactly that rule as
`EStreetHeightSampling::LandscapeTriangulated` (`StreetTerrainSource.cpp:169-173`).

For a 1 m quad `A=z00, B=z10, C=z01, D=z11` with **twist `T = A + D − B − C`**:

```
bilinear                 = A + (B−A)tx + (C−A)ty + T·tx·ty
triangulated (tx <  ty)  = A + (D−C)tx + (C−A)ty        →  bilinear − tri = −T·tx·(1−ty)
triangulated (tx >= ty)  = A + (B−A)tx + (D−B)ty        →  bilinear − tri = −T·ty·(1−tx)
```
so **|bilinear − triangulated| ≤ |T|/4**, attained at the quad centre `tx = ty = ½`.

Site-wide, over all 98,643,766 one-metre quads of the 391 tiles (`d2_interp.json:quad_bound_m`):

```
max 6.12109375   p99.999 1.54296875   p99.99 0.962890625   p99.9 0.185546875   p99 0.041015625   p50 0.00390625
quads_over_0_10m  228,582   quads_over_0_25m  64,474   quads_over_0_50m  25,937
worst tile (23, 15)
```

**Where "0.52 m" comes from.** It is the interpolation bound of a single 1 m quad whose twist is
2.08 m. 25,937 quads (0.026 % of the site) have a bound above 0.50 m; the site maximum is 6.121 m.
On the uniform scatter the largest actual disagreement is 0.134 m; on the steep scatter it is
1.909 m. So 0.52 m was a sample maximum from a point set that included some steep ground — it is
neither a floor nor a ceiling, and the honest statement is the table in §3.2 plus this bound.

### 3.4 The decomposition is exact

```sh
$PY projects/one/Saved/Diag/check_interp_vs_engine.py     # -> Saved/Diag/d2_interp_vs_engine.json
```

Predicting the engine's `z_heightfield − z_landscape` with nothing but the numpy
bilinear-minus-triangulated formula:

| | n | max | p99 | p95 | rms |
|---|---|---|---|---|---|
| engine B | 6,958 | 3.18755 | 0.08600 | 0.01584 | 0.07537 |
| numpy prediction | 6,958 | 1.90868 | 0.08613 | 0.01584 | 0.04065 |
| **residual, > 1 m from a tile boundary** | **6,866** | **0.000587** | 0.000315 | 0.000212 | **0.0000983** |
| residual, ≤ 1 m from a tile boundary | 92 | 3.18755 | 3.10068 | 0.90445 | 0.55178 |

Away from tile boundaries the prediction is exact to **0.59 mm** — i.e. **the whole of D2 is the
interpolation rule and nothing else**: not quantisation, not the half-pixel convention, not the
padding, not the import.

The 92 near-boundary points are **D1 leaking into D2**: the numpy `Heightfield` picks a tile by
`floor(x/512)` and reads that tile's copy of the shared row, while the landscape holds one value for
the shared vertex. At the worst point (local x 12287.821, y 1442.164, 0.179 m from the boundary,
slope 62.7°) bilinear and triangulated both give 3.28125 m from tile A while the landscape says
0.0937 m — a 3.188 m disagreement that is purely the seam.

**Does D2 survive fixing D1?** Yes. Fixing D1 removes only the ≤ 1 m-from-boundary column
(1.3 % of points). The interpolation term is untouched: 1.909 m max on steep ground, bound 6.121 m
site-wide.

### 3.5 Which is authoritative

**The ALandscape's triangulation is authoritative** for anything that must sit on, or be seen
against, the ground:

* it is what is rendered and what the pawn collides with. A downward line trace agrees with
  `GetHeightAtLocation` exactly — `z_trace − z_landscape` over 6,958 points has p50 = p95 = 0.0
  (`d2_join.json:trace_vs_landscape`); the p99 of 7.02 m and max of 37.66 m are traces that hit a
  massing actor's roof, not the ground, and are not a terrain error.
* `Simple` and `Complex` collision heightfields are identical here:
  `z_landscape_collision − z_landscape` is 0.0 at every one of the 6,958 points.
* it cannot be changed. Bilinear can.

The heightfield is authoritative for the **survey value at a grid post** (§3.2 row 2), and remains
the right thing for Blender/Unreal parity — provided both use the same rule.

**Recommended D2 fix (small, and independent of D3):** make `LandscapeTriangulated` the default.
Two places:

* `Plugins/Streetscape/Source/Streetscape/Public/StreetTerrainSource.h:53` and `:138` — flip the
  default `EStreetHeightSampling` from `Bilinear` to `LandscapeTriangulated`. The implementation at
  `StreetTerrainSource.cpp:169-173` is already verified correct against the running engine (§3.4).
* `projects/one/Tools/blender/streetscape/terrain.py:186 Heightfield.sample` — add the same rule and
  make it the default, keeping bilinear reachable for the frozen fixtures.

This is a **coordinated change**: `DESIGN.md` §8 currently *specifies* bilinear ("the identical
bilinear rule"), and the frozen expectations in `SCHEMA.md` §9.3 / `Tools/blender/tests/fixtures/`
sample synthetic terrain and will move. That is the cost; it is small and it is the only way the two
toolchains and the engine can agree everywhere rather than only at grid posts. **See
`needs_from_others`.**

---

## 4. D3 — the roads fuse with the landscape

### 4.1 What was measured

For a sample of **250 real Thanet road/rail splines** drawn round-robin from all 246 site documents
(so the sample is spread over the isle, not clustered), plus the authored test stretch, at **every
station**, the modelled road **surface** was evaluated at 9 lateral offsets spanning the full
carriageway — `frames.p + d·n + camber(d)·b`, exactly how Renderer A places its ribbon rows
(`DESIGN.md` §4.1) — and the **landscape** height was sampled at the same plan position. Clearance is
`z_road − z_terrain`; negative means the ground erupts through the carriageway.

```sh
$PY projects/one/Tools/diag/fusion_audit.py --n 250 --windows 5,10,20,40 \
    --extra-doc projects/one/schema/examples/test_stretch.json \
    --out projects/one/Saved/Diag/fusion_full.json
# 251 splines built, 0 skipped, 16,212 stations with terrain, 26.726 km of carriageway
```

### 4.2 The headline

At the shipped window **W = 20 m** (`fusion_full.json:by_window["20.0"]`):

```
stations_with_terrain              16,212
stations_penetrated                14,543      fraction 0.89705
carriageway_km_total               26.7256
carriageway_km_penetrated          24.0077     fraction of length 0.89830
penetration over penetrated stations:  max 4.1453  p99 0.6312  p95 0.2752  p50 0.0605  mean 0.0943
min clearance distribution: min -4.1453  p01 -0.5962  p05 -0.2628  p50 -0.0531  p95 +0.0124  max +1.1923
```

Read the median: **the middle of the road network has the ground 5.3 cm above the tarmac somewhere
across its width**. That is the "fusing" Alex saw — not a few bad places, the default state.

The authored test stretch is no better: **100 % of its 116 stations penetrate**, max 0.278 m,
p95 0.173 m, p50 0.059 m (`fusion_full.json:extra_by_window["20.0"]`).

### 4.3 By road class (W = 20)

| class | stations | frac penetrated | km | km penetrated | pen max | p95 | p50 |
|---|---|---|---|---|---|---|---|
| residential | 3,946 | 0.949 | 6.410 | 6.080 | 1.387 | 0.192 | 0.070 |
| service | 2,458 | 0.967 | 3.582 | 3.475 | 0.840 | 0.146 | 0.060 |
| unclassified | 1,876 | 0.934 | 3.360 | 3.139 | 0.725 | 0.299 | 0.061 |
| footway | 1,613 | 0.738 | 2.506 | 1.849 | 4.145 | 0.258 | 0.026 |
| bridleway | 1,375 | 0.813 | 2.500 | 2.016 | 0.427 | 0.201 | 0.045 |
| secondary | 1,146 | 0.965 | 2.115 | 2.048 | 1.977 | 0.587 | 0.093 |
| tertiary | 1,110 | 0.931 | 1.983 | 1.849 | 0.593 | 0.244 | 0.064 |
| track | 701 | 0.775 | 1.149 | 0.906 | 0.435 | 0.090 | 0.021 |
| cycleway | 650 | 0.842 | 1.100 | 0.925 | 0.499 | 0.261 | 0.062 |
| **trunk** | 396 | **1.000** | 0.722 | 0.722 | 0.686 | 0.397 | **0.267** |
| path | 288 | 0.712 | 0.471 | 0.335 | 0.244 | 0.079 | 0.023 |
| pedestrian | 208 | 0.678 | 0.337 | 0.225 | 0.771 | 0.592 | 0.172 |
| rail | 313 | 0.834 | 0.303 | 0.254 | 0.489 | 0.125 | 0.036 |
| **primary** | 91 | **1.000** | 0.150 | 0.150 | 0.672 | 0.223 | 0.165 |
| steps | 41 | 0.951 | 0.038 | 0.034 | 2.064 | 1.907 | 0.777 |

**The wider the road, the worse it is.** Trunk (12 m) and primary (10 m) penetrate at *every*
station, with median penetrations of 26.7 cm and 16.5 cm. That is the signature of a width-driven
cause, not a smoothing-driven one.

### 4.4 By terrain slope (W = 20)

| slope | stations | frac penetrated | km | km penetrated | pen max | p95 |
|---|---|---|---|---|---|---|
| 0–2° | 8,766 | 0.916 | 14.435 | 13.250 | 0.711 | 0.187 |
| 2–5° | 5,920 | 0.879 | 9.841 | 8.652 | 1.513 | 0.289 |
| 5–10° | 994 | 0.863 | 1.649 | 1.431 | 1.641 | 0.497 |
| 10–20° | 321 | 0.910 | 0.500 | 0.459 | 1.537 | 0.828 |
| 20–90° | 201 | 0.741 | 0.292 | 0.207 | **4.145** | 1.882 |

Frequency is flat with slope (**91.6 % even on ground flatter than 2°**); depth is not. Slope
controls how bad it looks, not whether it happens.

### 4.5 The smoothing window is not the driver — measured, not argued

Same 250 splines, four windows (`fusion_full.json:by_window`):

| W (m) | stations penetrated / 16,212 | fraction | km penetrated | pen max | p99 | p95 | p50 |
|---|---|---|---|---|---|---|---|
| 5 | 15,162 | **0.9352** | 24.946 | 3.1495 | 0.5968 | 0.2552 | 0.0523 |
| 10 | 14,871 | 0.9173 | 24.490 | 3.4904 | 0.6093 | 0.2627 | 0.0557 |
| **20** (shipped) | 14,543 | 0.8971 | 24.008 | 4.1453 | 0.6312 | 0.2752 | 0.0605 |
| 40 | 14,007 | 0.8640 | 23.108 | 4.6163 | 0.7005 | 0.3029 | 0.0666 |

**Refuted.** Shortening the window makes the fusion *more* frequent (93.5 % at W = 5) and only
slightly shallower; lengthening it makes it less frequent but deeper (max 4.62 m at W = 40). Across
an 8× range of window the fraction moves by 7 percentage points and never approaches zero. **No
value of W fixes this**, and W = 0 (following the raw DTM point-for-point) is what BRIEF §1.1
explicitly forbids and would in any case still leave the cross-section term below.

### 4.6 Why — the exact decomposition

Because the longitudinal residual is constant across the width, the clearance splits **exactly**:

```
min_clear = T1 + T2                       T1 = z_ref − z_raw(centreline)          longitudinal smoothing
T2        = T2_flat + T3                  T2_flat = z_raw(centre) − max_k z_terrain_k   cross-section
                                          T3 = what bank + camber add
```

```sh
$PY projects/one/Tools/diag/fix_candidates.py --n 250 --out projects/one/Saved/Diag/fixes_full.json
# 250 splines, 26.726 km, 16,207 stations
```
`fixes_full.json:decomposition`:

| term | p05 | p50 | p95 | min | mean |
|---|---|---|---|---|---|
| **T1** longitudinal smoothing | −0.0470 | **0.0000** | +0.0448 | −1.3671 | −0.00012 |
| **T2_flat** cross-section roughness | −0.2983 | **−0.0515** | 0.0000 | −3.0369 | −0.0922 |
| **T3** bank + camber | −0.0506 | +0.0013 | +0.1031 | −0.3495 | +0.0106 |

```
stations_penetrated                        14,537
  ...explained by T1 alone (T2 >= 0)          573    (3.9 %)
  ...explained by T2 alone (T1 >= 0)        6,875   (47.3 %)
  ...both negative                          7,089   (48.8 %)
T2 negative fraction                        0.9438
T1 negative fraction                        0.4728
```

**T1 is a zero-median, symmetric residual** — the moving average is doing exactly what BRIEF §1.1
asks, and by itself it puts the road below the raw crown only half the time. **T2 is negative at
94.4 % of stations**, with a median of −5.2 cm. That is the mechanism:

> A flat (or gently cambered) ribbon 6–12 m wide is laid on a **1 m DTM whose surface across the
> carriageway is not planar**. The centreline height is one sample of a rough field; the maximum of
> ~9 samples across the width is systematically above it. The bank is clamped to ±4°
> (`ROAD_SAMPLING_DEFAULTS.bank_max_deg`, `schema.py:290`) and rate-limited to 0.25°/m, so wherever
> the real cross slope exceeds 4° the ribbon's uphill edge dives into the hill. Camber then lowers
> both edges by a further `crossfall/100 · w/4` (6 m at 2.5 % → 3.75 cm; 12 m → 7.5 cm).

Per class, `T2_flat` p05 tracks width almost perfectly (`fixes_full.json:by_class_T`): trunk −0.600,
secondary −0.685, unclassified −0.337, residential −0.250, service −0.132, path −0.083. `T1` p05 is
−0.012 for trunk and −0.081 for footway — an order of magnitude smaller and in the *opposite*
ordering.

### 4.7 A worked example — the A-road at Manston

```sh
$PY projects/one/Tools/diag/worked_example.py \
    --doc data/thanet/out/unreal/streetscape/site_x16_y2.json --spline-index 45 \
    --out projects/one/Saved/Diag/worked_trunk.json
```

`roads:32352025:0`, class **trunk**, profile `road_trunk`, width 12.0 m, length 212.490 m,
127 stations, `smoothing_window_default_m 20.0`. Penetration at **every** station.

**Along the road** (`worked_trunk.json:along`, every 6th station; metres):

| s | z_raw(centre) | z_ref (smoothed) | max terrain across | min clearance |
|---|---|---|---|---|
| 0.000 | 12.2262 | 12.2262 | 15.9646 | **−3.4176** |
| 12.000 | 19.0095 | 19.0995 | 19.7132 | −0.3559 |
| 23.999 | 22.4754 | 21.8293 | 22.5681 | −0.8585 |
| 35.999 | 21.9090 | 21.9232 | 22.0032 | −0.1170 |
| 47.998 | 21.3701 | 21.3184 | 21.3899 | −0.0784 |
| 68.999 | 20.0943 | 20.0776 | 20.2768 | −0.1385 |
| 127.185 | 16.5691 | 16.5155 | 16.7408 | −0.1989 |
| 212.490 | 16.7994 | 16.7994 | 16.8482 | −0.0762 |

Three regimes are visible in one table:

* **s = 24.0** — the smoothing residual bites: `z_ref` is 0.646 m *below* the raw crown as the road
  comes over a rise. Clearance −0.859 m. This is T1, and it is the only place where the window
  matters.
* **s = 36.0 and s = 48.0** — the smoothing is essentially exact (`|z_raw − z_ref|` = 1.4 cm and
  5.2 cm) yet the clearance is still −0.117 m and −0.078 m, because the raw ground **across** the
  12 m carriageway peaks 9.4 cm and 2.0 cm above the centreline sample. This is T2_flat, and no
  window can touch it.
* **s = 0** — the window shrinks to zero at the ends (`DESIGN.md` §3 rule 3), so `z_ref` **equals**
  `z_raw` exactly (12.2262 m both). The clearance is nevertheless **−3.418 m**. This is T3 + T2_flat
  at their worst: the road crosses a bank.

**Across the road at s = 0** (`worked_trunk.json:worst_station.cross_section`, bank −4.000° = the
clamp, width 12.0 m):

| lateral d | z road | z terrain | clearance |
|---|---|---|---|
| −6.0 | 12.5700 | 15.9323 | **−3.3624** |
| −4.5 | 12.4981 | 15.8264 | −3.3284 |
| −3.0 | 12.4168 | 15.0333 | −2.6165 |
| −1.5 | 12.3262 | 13.3540 | −1.0278 |
| **0.0** | **12.2262** | **12.2262** | **0.0000** |
| +1.5 | 12.1169 | 11.6317 | +0.4852 |
| +3.0 | 11.9983 | 11.2151 | +0.7832 |
| +4.5 | 11.8702 | 11.7359 | +0.1343 |
| +6.0 | 11.7329 | 12.6739 | −0.9410 |

The raw ground rises 3.706 m over the 6 m to the left of the centreline — a true cross slope of
`atan(3.706/6) = 31.7°`. The bank is clamped at 4.0°, i.e. the ribbon can only lean
`6 · tan(4°) = 0.42 m` over that half-width. The remaining 3.29 m is buried. **The road is a
12 m plank laid across a cutting the survey resolved at 1 m.**

This is precisely the case BRIEF §1.1 anticipated — *"Edge case: road cutting through a steep bank.
Smoothed height will sit above or below real ground. Handle with an extra profile entry on Renderer
B: short embankment or retaining wall"* — and the schema already has `Embankment` /
`EmbankmentSegment` for it. But an embankment is *extra geometry beside the road*; it does not stop
the **landscape mesh itself** from passing through the carriageway. On a 1 m heightfield with a
6–12 m ribbon, the terrain is not underneath the road: it is through it.

---

## 5. The candidate fixes, measured

Corridor definition used throughout, per class:

```
half_core  = edge_offset(side) + kerb_width + pavement_width      (the BUILT surface)
           = w/2 + 0.125 + 1.8   for road classes with a UK kerb
           = w/2                 for paths, cycleways, tracks, rail
verge      = 2.0 m   (held at the road-edge level)
blend      = 3.0 m   (smoothstep back to the raw survey)
```

Areas, rasterised onto the 1 m grid with overlaps counted once
(`projects/one/Tools/diag/corridor_mask.py` → `Saved/Diag/corridor_mask.json`, 13,097 splines):

```
kept land                                    98,666,807 cells = 98.667 km2
core (carriageway + kerb + pavement)          7,014,540 cells =  7.014 km2  =  7.11 % of kept land
corridor incl. verge + blend                 14,548,457 cells = 14.548 km2  = 14.74 % of kept land
core cells covered by 2+ corridors              574,015 cells =  8.18 % of the core
core cells covered by 3+ corridors               31,750 cells
```

(The naive length × width estimate in `Saved/Diag/network_extent.json` — 968.669 km of network,
10.920 km² core, 16.732 km² with blend — double-counts junctions; the rasterised union above is the
number to use.)

### 5.1 (a) Conform the landscape to the road — **RECOMMENDED**

Burn the road's own smoothed profile into the landscape heightmap over the corridor and blend out.
Measured over the 250-spline sample, 293,011 distinct 1 m cells
(`fixes_full.json:candidate_a_conform`):

| | n | max fill | max cut | p99 \|Δ\| | p95 \|Δ\| | p50 \|Δ\| | \|Δ\|>0.25 | \|Δ\|>1 | \|Δ\|>2 |
|---|---|---|---|---|---|---|---|---|---|
| whole corridor | 293,011 | +12.193 | −6.127 | 1.101 | 0.337 | **0.041** | 7.55 % | 1.13 % | 0.45 % |
| core only | 117,559 | +12.193 | −4.152 | 0.782 | 0.261 | 0.041 | — | — | 0.40 % |
| blend only | 175,452 | +11.867 | −6.128 | 1.299 | — | 0.040 | — | — | — |

**The typical change to the landscape is 4.1 cm.** 92.4 % of corridor cells move less than 25 cm.
The extremes (12.2 m fill, 6.1 m cut, 1,321 cells of 293,011) are exactly the cliff-edge and
cutting cases of §4.7, and they must be **capped**, not allowed to bulldoze a chalk cliff.

**Against the honesty rules.** BRIEF §1.1 says *"The terrain mesh underneath stays untouched."* That
sentence is written about the LIDAR-sampling rule for the spline, and it is satisfied — the
recommendation below does not touch `data/thanet/out/terrain/` at all. What it changes is a
**derived, engine-side product**, and it records every changed cell. The repo's actual binding rules
are: `sources/derive/` may not learn about an engine (`README.md`, `sources/OUTPUT.md`); the survey
product is `data/<site>/out/`; a change must be recorded in a manifest (`BRIEF.md` §3, §4.1). A
corridor conform obeys all three when it is a **new product beside the old one**.

**Where it belongs.**

| option | verdict |
|---|---|
| a new step in `sources/derive/` | **No.** It needs the *smoothed spline height*, which is defined by the geometry core (`Tools/blender/streetscape/spline.py`). Re-implementing Catmull-Rom + adaptive stations + the arc-length moving average inside the pipeline duplicates the normative definition and guarantees drift. |
| inside `sources/adapters/unreal.py` | **No.** Same problem, plus it would silently redefine `hm_*.r16` (`DESIGN.md` §8 says it is "h16 of step 05's filled DTM") and break the adapter's own verification that `clip_*.r8` counts match `clipped_cells`. |
| an Unreal-side importer pass | **No.** The burn would exist only inside the `.umap`, so Blender's terrain and the numpy tests would disagree with the engine — reintroducing the parity problem D2 is about, and making the change unreproducible outside UE. |
| **a new deterministic pass in `projects/one/`, run after the adapter, writing a new product** | **Yes.** It runs the *same* numpy geometry core that defines the road height, so the burned surface is the road surface by construction; it is pure numpy so it is testable with the env python; both Blender and Unreal read the same bytes; the survey and the raw landscape product stay on disk untouched for comparison. |

**Concrete specification.**

* **New module** `projects/one/Tools/blender/streetscape/conform.py` (geometry track owns
  `Tools/blender/**`) + driver `projects/one/Tools/conform_landscape.py`.
* **Input** `data/thanet/out/unreal/landscape/` + `data/thanet/out/unreal/streetscape/site_*.json`.
* **Output** `data/thanet/out/unreal/landscape_conformed/` — the *same* file layout (`hm_*.r16`,
  `clip_*.r8`, `vis_*.r8`, `weight_*_*.r8` copied byte-for-byte; only `hm_*.r16` differs) plus:
  * `landscape_manifest.json` copied with an added block
    `conform: {source: "../landscape", generator, commit, corridor: {...}, cells_changed, max_fill_m,
    max_cut_m, p99_abs_m, clamp_m, tiles: [{x, y, cells_changed, max_abs_m}]}` and
    `heightmap.semantics` changed from "h16 of step 05's filled DTM" to
    **"h16 of step 05's filled DTM, conformed to the road corridor — NOT the raw survey"**.
  * `conform_delta_x{i}_y{j}.r16` — the signed change per cell, so any consumer can recover the
    survey exactly and a diff is auditable. This is how "a consumer knows the landscape is no longer
    the raw survey": the manifest says so in words, the delta raster proves it cell by cell, and
    the directory has a different name.
* **Target surface**, per 1 m cell at signed lateral offset `t` from the nearest station:
  * `|t| ≤ edge_offset` — the road surface: `z_ref + t·sin β + camber(t)·cos β`, minus
    **`sink = 0.03 m`**.
  * `edge_offset < |t| ≤ half_core` — held flat at the road-edge level minus `sink`. (The kerb and
    pavement are a solid block from `−tuck_depth = −0.03 m` to `hk_back`, `DESIGN.md` §4.2, and the
    pavement back face drops `skirt_m = 0.3` — so ground 3 cm under the road-edge plane is inside
    the block everywhere and never pokes out.)
  * `half_core < |t| ≤ half_core + verge + blend` — `smoothstep((|t| − half_core)/(verge + blend))`
    from that shelf level back to the raw survey value at that cell.
* **Clamp** `|Δ| ≤ 2.00 m` per cell. 99.55 % of corridor cells are inside it already; the 0.45 %
  that are not are cuttings and cliff edges, where flattening the ground is the wrong answer and
  the right answer is BRIEF §1.1's own: an **embankment / retaining-wall segment on Renderer B**.
  The pass must **emit the list of clamped runs** (`conform_clamped.json`: spline id, `s0`, `s1`,
  side, residual metres) so the geometry track can add those `EmbankmentSegment`s from data rather
  than by eye.
* **Where two corridors cross** (574,015 cells, 8.18 % of the core): resolve per cell by class
  priority `trunk > primary > secondary > tertiary > unclassified > residential > living_street >
  service > pedestrian > cycleway > track > bridleway > footway > path > steps`, rail above all
  roads; ties break to the **higher** target (so a junction never leaves a lip that a lower road
  pokes through); then one 3×3 box smoothing pass restricted to cells that had 2+ contributors, to
  kill the ridge along the arbitration line. Record `cells_arbitrated` in the manifest.
* **The cliff and the coast.** The clamp is the primary protection. In addition the pass must
  **refuse to write** a cell whose `clip_*.r8` is 0 (outside the model) and must leave the
  `vis_*.r8` and weight rasters untouched, so the Wantsum cut and the ground-cover classification
  are unchanged by construction; `slope_qa` is recomputed for the conformed product and reported
  beside the original so any loss of cliff steepness is visible rather than silent. On the sample,
  only 0.292 km of 26.726 km of carriageway (1.1 %) sits on ground steeper than 20°, so the burn
  touches very little of the chalk coast at all.
* **Consumers**: `UStreetscapeSettings::GetResolvedDataDir()/landscape` →
  `.../landscape_conformed`; `02_import_landscape.py --manifest` and the Blender driver's
  `--terrain` both point at the new directory. `data/thanet/out/terrain/` and
  `data/thanet/out/unreal/landscape/` are never written.
* **Ordering**: run **after** the D1 fix, so the corridor is burned onto seam-free ground; otherwise
  a road crossing a repaired seam would have to be re-burned.

**The test that proves it fixed** (this is the acceptance gate; it must be added to `STAGES.md`):

1. The gate is already implemented:
   ```sh
   $PY projects/one/Tools/diag/fusion_audit.py --all --windows 20 --gate-m 0.005 \
       --landscape data/thanet/out/unreal/landscape_conformed \
       --out projects/one/Saved/Diag/fusion_conformed.json
   ```
   over the **whole** network (13,097 road/rail splines, not a sample). It must print
   `GATE PASS` and exit 0, and the JSON must show `carriageway_km_penetrated` ≈ 0.000.
   Today the same command on the unconformed landscape prints
   `GATE FAIL: worst penetration 4.145316 m, allowed 0.005000 m` and exits 1.
   (Tolerance rationale: r16 half-quantum 0.0039 m + ~0.001 m of cross-section sagitta over a 1 m
   quad + ~0.001 m of bank-twist interpolation ≈ 0.006 m, comfortably inside the 0.03 m sink.)
2. `Tools/diag/seam_audit_r16.py --landscape .../landscape_conformed` must report
   `samples_disagree_visible == 0` (the conform must not reintroduce a seam: corridors crossing a
   tile boundary must be burned from the same station set on both sides).
3. `sources/tests/regress_outputs.sh compare margate before` → 0 changed, and
   `sha256sum data/thanet/out/terrain/*` unchanged from before the pass.
4. An Unreal automation test that walks the pawn along the test stretch and asserts the downward
   trace hits the road mesh, not the landscape, at every station
   (`04_probe.py --actor <id> --trace-from-above` already does the trace).
5. A screenshot from the same camera before and after, committed via LFS.

### 5.2 (b) Raise the road to clear the terrain — **REJECTED**

Lift each station to at least the local maximum ground over the corridor plus a clearance
(0.05 m), and let the skirts hide the gap. Measured (`fixes_full.json:candidate_b_raise`,
16,207 stations, 26.722 km):

| | max | p99 | p95 | p50 | mean |
|---|---|---|---|---|---|
| lift needed, per station | 4.1953 | 0.6463 | 0.3128 | 0.1032 | 0.1347 |
| lift after the honest re-smoothing¹ | 4.1953 | 0.8900 | 0.4475 | 0.1552 | 0.2017 |
| **float gap on the low side, per-station lift** | 8.8377 | 5.4613 | 0.4010 | 0.1305 | 0.2529 |
| **float gap on the low side, re-smoothed lift** | 8.9766 | 5.8574 | 0.5579 | **0.1820** | 0.3199 |

¹ a per-station lift *is* "follow the raw LIDAR point-for-point", which BRIEF §1.1 forbids; the
honest version takes a running maximum over the smoothing window and re-smooths, which raises more.

```
km_total                                        26.722
km where the gap exceeds the 0.125 m kerb       22.003     (82.4 % of stations)
fraction of stations with a gap over 0.5 m       0.0587
```

**Rejected on the numbers.** The road-over-kerb machinery hides 2 cm (`skirt_drop_m 0.02`) and the
kerb block itself is 0.125 m tall. A median gap of **0.182 m** means the road, kerb and pavement
would float with daylight underneath along **22.0 of 26.7 km** — 82 % of the network — and at the
p99 it floats 5.86 m. It also makes every junction wrong: two ways meeting at a node are lifted by
different amounts, so the shared node no longer agrees (`DESIGN.md` §3 rule 3 exists precisely to
keep meeting splines bit-identical). And it defeats the purpose: the model would stop being the
survey where it matters most, at eye level.

### 5.3 (c) Cut the landscape away under the roads — **REJECTED**

Mark the corridor as landscape visibility holes and let the road mesh be the ground.

* **Hole area**: the core alone is **7.014 km², 7.11 % of the isle's 98.667 km² of kept land**;
  with the verge and blend it is 14.548 km² (14.74 %). Punching 7 % of a landscape into holes is
  not a fix, it is a different model.
* **The holes are 1 m staircases.** Collision removes a *whole quad* whose dominant layer is the
  visibility layer (`Engine/Source/Runtime/Landscape/Private/LandscapeCollision.cpp:1276-1279`,
  triangle skip at `:644-654`), and the render edge falls where the bilinearly sampled weight
  crosses 2/3 (`LandscapeDataAccess.h:19`). A 6 m carriageway at 30° to the grid would therefore
  get a ragged 1 m-quantised edge along both kerbs — visibly worse than the fusion it replaces.
  The one place a hole edge *is* acceptable is the Wantsum cut, because that line is straight and
  is deliberately drawn with a 1-cell feathered `vis_*.r8` (`DESIGN.md` §16); a road network is
  neither straight nor sparse.
* **Collision**: the pawn would fall through the 2 m of verge between the pavement back edge and
  the hole boundary wherever the streetscape mesh does not reach — and the streetscape does not
  reach: `edge_uk_kerb` ends at `kerb + pavement = 1.925 m` from the kerb line.
* **The coast and ground cover**: the visibility layer is already the mechanism carrying the clip.
  Overloading it with 7 km² of road holes destroys the invariant the importer checks (`clip.pass`,
  `kept_side_ok/cut_side_ok` in `Saved/Tests/gate_c.json`) and makes the four ground-cover
  weightmaps meaningless under the corridor (they are renormalised against a layer that is now
  dominant in 7 % of the site).

### 5.4 (d) The hybrid that is actually recommended

The recommendation is (a) **plus** two things that come from BRIEF §1.1 itself and cost almost
nothing once the corridor pass exists:

* **the clamped runs become embankments.** Where `|Δ| > 2 m` the pass does not flatten the ground;
  it emits the run and the geometry track adds an `EmbankmentSegment` (batter or retaining wall,
  already in the schema, `DESIGN.md` §4.2) on that side. This is 1,321 of 293,011 corridor cells on
  the sample (0.45 %; 0.40 % of core cells) — a small, enumerable list, not a general case.
* **the D2 sampling change (§3.5)**, so the burned surface, the road mesh and the rendered landscape
  are the same surface everywhere, not only at grid posts.

---

## 6. Order of work, and who owns what

| # | change | owner (`DESIGN.md` §21) | proved by |
|---|---|---|---|
| 1 | **D1**: step 05 stops nearest-filling open sea (reach threshold → `water_level`, recorded) and fills the remaining real gaps once over the mosaic | pipeline (`sources/derive/05_export_terrain.py`, `sources/lib.py`, `sources/tests/dryrun.py`) | `seam_audit.py` cells_disagreeing → 0; `seam_audit_r16.py` samples_disagree_visible → 0; Margate byte-identical |
| 2 | re-run the adapter and re-import the landscape | adapter, unreal | importer `shared_edge.ok` true with `MaxSharedEdgeH16Delta 0` (no waiver) |
| 3 | **D2**: `LandscapeTriangulated` becomes the default in the plugin and in numpy `Heightfield.sample`; `DESIGN.md` §8 and the frozen fixtures updated | unreal + geometry, coordinated | a probe run where `max_abs_dz_m` over 7,000 points is ≤ 0.001 m instead of 3.18759 |
| 4 | **D3**: the corridor conform pass, its manifest, its delta rasters and its clamped-run list | geometry (new `Tools/blender/streetscape/conform.py`), consumers repointed by unreal | §5.1's five acceptance checks |
| 5 | embankments from the clamped runs | geometry | the clamped-run list is empty of unhandled entries |

---

## 7. Tools written by this round

All under `projects/one/Tools/diag/` (owned by the diagnostic role; nothing else was touched).
Every one takes `--out <json>` and prints its summary.

| tool | what it measures |
|---|---|
| `seam_audit.py` | shared edges of the step-05 GeoTIFFs vs the raw EA rasters; tests the per-tile-fill hypothesis cell by cell |
| `seam_audit_r16.py` | the same edges on the adapter's `hm_*.r16`, split visible / hidden by `clip_*.r8` + `vis_*.r8` |
| `nodata_reach.py` | one distance transform over the 13313 × 9729 mosaic: how far a NoData cell is from surveyed ground |
| `terrain_truths.py` | `--mode emit` builds the point set and samples the heightfield + GeoTIFF; `--mode join` folds in `04_probe.py`'s landscape column |
| `interp_decompose.py` | bilinear vs landscape-triangulated, at points and as the site-wide `\|twist\|/4` bound |
| `road_inventory.py` | spline counts by layer and class |
| `network_extent.py` | network length by class and the naive corridor area |
| `corridor_mask.py` | the rasterised corridor union and its self-overlap |
| `fusion_audit.py` | the D3 clearance measurement, any set of smoothing windows; `--all` runs the whole network and `--gate-m <m>` turns it into a pass/fail gate (exit 1 on failure) |
| `fix_candidates.py` | the T1/T2/T3 decomposition and candidates (a) and (b) measured |
| `worked_example.py` | one spline in full: along-road table, cross-section, raw ladder, window arithmetic |

Raw outputs (git-ignored): `projects/one/Saved/Diag/{seam_audit,seam_r16,nodata_reach,d2_ab,d2_join,
d2_interp,d2_interp_vs_engine,road_inventory,network_extent,corridor_mask,fusion_full,fixes_full,
worked_trunk}.json`, plus `d2_points.csv`, `d2_points.npz`, `d2_probe.csv`.

---

# 8. D3 as built — the corridor conform (2026-09-09, road corridor agent)

Section 5.1's recommendation was implemented, with four deviations that are stated and measured
below. **Penetration over the whole isle is zero.** Everything here was produced by the commands
quoted; the JSON each number came from is named.

## 8.1 The result, before and after

Whole network, 13,097 road/rail splines from all 246 site documents, 666,314 stations, 968.840 km of
carriageway, measured across the **built surface** (carriageway + kerb + pavement), the road built on
the survey and compared against the landscape the engine imports:

```sh
cd /c/Users/Shadow/code/3duk
PY=C:/Users/Shadow/code/3duk-env/env/python.exe
# before: the adapter's landscape
$PY projects/one/Tools/road_fusion_audit.py --landscape data/thanet/out/unreal/landscape \
    --gate-m 0.005 --slope --out projects/one/Saved/Diag/fusion_before_all_v2.json
# after: the conformed landscape (the acceptance gate)
$PY projects/one/Tools/road_fusion_audit.py --landscape data/thanet/out/unreal/landscape_conformed \
    --gate-m 0.005 --float-gate-m 0.125 --float-max-frac 0.06 --slope \
    --out projects/one/Saved/Diag/fusion_after_all.json
```

| | before | after |
|---|---|---|
| stations with terrain above the built surface (> 5 mm) | **565,545 of 666,314 (84.88 %)** | **0** |
| carriageway penetrated | **826.693 km of 968.840** | **0.000 km** |
| worst penetration | **13.826 m** | **0.000000 m** |
| p99 / p95 / p50 penetration over all stations | 0.897 / 0.275 / 0.047 m | 0 / 0 / 0 |
| worst penetration, carriageway only | 13.698 m | 0.000000 m |
| worst penetration, kerb + pavement | 13.826 m | 0.000000 m |
| minimum clearance, p50 | **−0.047 m** (ground 4.7 cm through the tarmac) | **+0.031 m** (the 0.03 m sink plus the sag) |
| minimum clearance, minimum | −13.698 m | **+0.009 m** |
| stations floating (gap > 0.125 m under the outer face) | 3.72 % / 34.281 km | 5.43 % / 42.713 km |
| worst float | 11.745 m | 13.076 m |

The diagnostic's own carriageway-only measurement (`fusion_audit.py --all`) moved from
**89.06 % / 866.056 km / 13.698 m** to zero on the same product.

With the landscape's **own triangulated rule** rather than the bilinear contract — what the pawn
walks on and the camera sees (`--sampling landscape_triangulated`,
`Saved/Diag/fusion_after_all_tri.json`): worst penetration **0.0025 m** at one rail station, zero
elsewhere. (Before it was excluded, that run reported 32.06 m at `roads:132194822:0` — the one spline
in the isle with **no survey ground under any station**, which the burn refuses to touch and the
audit now names and skips instead of blaming the conform for it.)

## 8.2 What was built

| file | role |
|---|---|
| `Tools/blender/streetscape/conform.py` | the pass, pure numpy: corridor zones, the sag correction, the mosaic arbitration |
| `Tools/conform_landscape.py` | the driver: reads the landscape + every site document, writes `landscape_conformed` |
| `Tools/blender/streetscape/fusion.py` | the measurement: penetration and float over the built surface |
| `Tools/road_fusion_audit.py` | the whole-isle gate (exit 1 on failure) |
| `Tools/blender/tests/test_conform.py` | 15 permanent tests (synthetic + real Thanet + the shipped product) |
| `Plugins/.../Tests/StreetConformTests.cpp` | `Streetscape.Conform.Manifest` and `Streetscape.Conform.NoFusion` — the same measurement in the engine's own C++ |
| `data/thanet/out/unreal/landscape_conformed/` | the product: `hm_*.r16`, `conform_delta_*.r16`, everything else copied byte for byte |

The burn is the road surface by construction, not a second transcription of it: `spline.camber_h` is
now the single definition of the cross-section, and both `Spline.surface_h` (the renderers) and
`conform.built_surface` (the burn) call it.

## 8.3 The corridor, per side and per station, from the profile data

```
|d| <= edge_offset(side)                    the road surface   z_ref + d sinB + camber(d) cosB
   .. + kerb_width + pavement_width         the shelf, held at the road-edge level
   .. + apron 1.5 m                         still arbitrated as built surface (see 8.4)
   .. + verge 2.0 m                         the shelf, clamped to +-2 m of the survey
   .. + blend                               smoothstep back to the survey value of that cell
sink 0.03 m under everything but the blend tail
blend = clamp(|shelf - survey| / tan(34 deg), 3 m, 12 m)   per station and side
```

`edge_offset` is the edge contract (DESIGN.md 3.6) and `kerb_width + pavement_width` is
`SideSpec.back_offset` — so a width change, a parking-bay `edge_extra`, a drop kerb and a profile
switch all move the corridor with the road, and nothing in the burn computes `width / 2`.

The blend length is **not** the recommendation's fixed 3 m: a fixed blend turns a 4 m cut into a 53°
wall. At 34° (1:1.5, the usual earthwork batter) the fill and cut faces read as embankments and
cuttings. Cost: the corridor is 12.70 km² of the 98.667 km² of kept land (12.9 %).

## 8.4 Four deviations from §5.1, each with its reason

1. **The clamp is on the verge and the blend, not on the built surface.** §5.1 asked for
   `|Δ| ≤ 2 m` everywhere; that cannot coexist with its own acceptance gate, because the places
   needing more than 2 m are exactly the places where the ground stands in the carriageway. So the
   built surface is exact and the ground **outside** it moves by at most 2.00 m: 1,321,998 cells were
   clamped. Without it a cliff-top way whose verge edge hangs 17 m over the beach builds a 17 m earth
   shelf out of the chalk (measured: `roads:28875046:0` +17.472 m) and a promenade under a cliff cuts
   a 14 m notch into it (`roads:179363634:0` −14.624 m). The step the clamp leaves at the apron edge
   **is** the retaining wall, and its run is written to `conform_clamped.json` (1,554 runs; 204 over
   5 m, 27 over 10 m) for Renderer B's `EmbankmentSegment` — BRIEF 1.1's own answer.
2. **Arbitration is the minimum, not class priority.** §5.1 proposed priority by road class with ties
   to the higher target. The minimum is what makes the gate provable: no way can be penetrated by
   ground another way asked for. It is also right at a grade separation — the ground follows the
   lower way and the bridge, or the upper flight of steps, flies over it. 9,248,160 cells were
   arbitrated, the deepest drop 13.30 m. No 3×3 smoothing pass was added: the minimum leaves a
   *crease*, not a ridge, and it is under the road.
3. **A sag correction was added** (`conform.sag_correction`). The landscape interpolates linearly
   between its 1 m posts; the road surface does not have to be linear between them, and where it is
   convex the straight line between two burned posts lies **above** the surface it was burned from.
   That is real fusion, of exactly the kind being fixed: 0.264 m on the A299 slip road at Manston
   (`roads:32352025:0` station 0, a 145 % grade off the junction) and 0.472 m on the cliff footway
   `roads:1387728616:0` (z_ref climbs 9.3 → 19.6 m in 2.5 m). The burn subtracts the second
   difference of the built surface, measured at three spans up to 1.5 m and taken at its largest,
   times a 1.5 safety factor. A straight grade, however steep, has a zero second difference and is
   untouched — which is why this is a correction and not a minimum over a stencil (that would sink a
   10 % grade by a tenth of the span and make the road float).
4. **Coverage had to be proved, not assumed.** Three separate holes in the stamping each left ground
   standing in a carriageway, and each is now a named test: the road's own end quad (9.3 mm — fixed
   by a 1.5 m overhang past both ends, which also closes the gap where a side road stops short of the
   way it joins); the wedge on the outside of a sharp turn (19 mm — fixed by curvature-adaptive ray
   spacing with the tangent re-interpolated, never lerped, and by making **every station** a ray);
   and the 0.5 m reach of rounding to the nearest cell (96 mm — fixed by claiming all four cells of
   the unit square a ladder point falls in). 264,885,057 contributions were arbitrated into
   13,358,939 cells.

## 8.5 The product, and how a consumer knows it is not the survey

`data/thanet/out/unreal/landscape_conformed/` — same layout, `clip_*.r8`, `vis_*.r8` and the four
weightmaps copied **byte for byte** (asserted by `test_conform.py`), only `hm_*.r16` different, plus:

* `landscape_manifest.json` with `heightmap.semantics` = *"h16 of step 05's filled DTM, CONFORMED TO
  THE ROAD CORRIDOR — not the raw survey"* and a `conform` block holding the corridor parameters, the
  generator, the commit, and every headline number;
* `conform_delta_x{i}_y{j}.r16` — int16, `h16_conformed − h16_survey`, so the survey is recoverable
  cell by cell (`test_conform.py` reconstructs it and compares byte for byte);
* `conform_clamped.json` — the runs for the geometry track.

`data/thanet/out/terrain/` and `data/thanet/out/unreal/landscape/` are **not written**: the driver
refuses when the source and destination are the same path, and refuses to run on a manifest that
already carries a `conform` block, so the burn cannot be applied twice.

Recorded in the manifest, measured on the run (`Saved/Diag/conform_report.json`):

```
splines_burned 13096   splines_skipped 1 (no survey ground under any station)
cells_changed  12,697,333 = 12.70 km2      cells_touched 13,358,939
|delta| p50 0.078 m   p95 0.430 m   p99 1.328 m   max fill +17.383 m   max cut -14.656 m
cells_clamped  1,321,998    arbitrations 9,248,160 (deepest 13.301 m)
slope_qa over the 246 changed tiles: max 86.278 deg survey -> 86.278 deg conformed (unchanged),
   cells over 45 deg 173,616 -> 193,032, worst per-tile flattening 8.03 deg at tile (17, 6)
```

**No cliff was flattened**: the site's steepest slope is identical before and after, and the burn
*adds* steep cells (the clamp's own faces) rather than removing them.

## 8.6 The float, and why the gate is a fraction

Conforming cannot remove float, because float is what two overlapping modelled surfaces at different
heights leave behind. After the burn 5.43 % of stations (42.713 km) have a gap deeper than 0.125 m
under the outer face of the built block, concentrated in **steps 57 %, cycleway 24 %, rail 18 %,
footway 11 %** and almost absent from carriageways (residential 0.39 %, service 0.27 %,
tertiary 0.72 %, secondary 0.68 %, trunk 4.3 %).

Attribution, measured rather than argued (`Saved/Diag/float_attribution.json`): of 60 floating
splines re-burned **on their own**, 36 stop floating entirely — their ground had been taken by a
neighbouring corridor. The rest are cliff stairs zigzagging over themselves and paths above
promenades, where the lower flight wins the cell and the upper one needs a wall. Both have the same
answer: `conform_clamped.json` → `EmbankmentSegment` on Renderer B.

So the gate is `--gate-m 0.005` (a hard zero on penetration) plus `--float-max-frac 0.06` — today's
5.43 % with a little headroom, a number that may only ever go **down** as those structures are built.

## 8.7 Running it

```sh
$PY projects/one/Tools/conform_landscape.py --report projects/one/Saved/Diag/conform_report.json
#   ~13.5 min, 1.3 GB RSS, 264.9 M contributions -> CONFORM_OK
$PY projects/one/Tools/road_fusion_audit.py --landscape data/thanet/out/unreal/landscape_conformed \
    --gate-m 0.005 --float-gate-m 0.125 --float-max-frac 0.06 --out <json>      # ~2 min -> GATE PASS
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 \
    -Script 02_import_landscape.py -Render -Log thanet_import_conformed.log \
    -Args "--manifest <DATA>/landscape_conformed/landscape_manifest.json --recreate-map --report <json>"
```

**The landscape import must read `landscape_conformed`.** Everything else keeps reading `landscape`:
the road drapes on the **survey** (BRIEF 1.1), so `UStreetscapeSettings::DataDir` / `landscape`,
`ue_common.heightfield()`, the Blender driver's `--terrain` and both test suites are unchanged —
which is also why the conform can never feed back into the road it was burned from.

## 8.8 In the engine, not only in numpy

The landscape was re-imported from the conformed product and the level rebuilt:

```sh
run_ue_python.ps1 -Script 02_import_landscape.py -Render -Log thanet_import_conformed.log \
  -Args "--manifest <DATA>/landscape_conformed/landscape_manifest.json --recreate-map \
         --max-components 256 --max-shared-edge-h16 0 --report <...>/landscape_import_conformed.json"
# THANET_OK: components 2067, proxies 140, regions_used 12, elapsed_s 359.5, gates_failed []
#   grid  max_abs_dz_m 0.000645  within_0_01_m true     (the landscape IS the conformed file)
#   cliff agree true, slope_max_deg 84.65, slope_ok true, slope_within_2deg_of_tile true
#   clip  pass, 20/20
```

`--max-components 256` matters: with `0` the importer attempts the whole 2067-component landscape in
one `Import` call and the D3D12 device dies with `E_OUTOFMEMORY` after ~12 minutes (twice, log
`Saved/Logs/import_conformed_stdout.log`). The 12-region path that `00_build_level.ps1` already uses
completes in 6 minutes.

**The road drapes on the survey, and now the level says so.** `02_import_landscape.py` pointed the
site actor's terrain source at the directory it probed and left it there; the saved level therefore
told the next `03_import_streetscape.py` to build its roads on the *conformed* ground — a feedback
loop whose first symptom is terrain standing back up through the carriageway. 02 now restores the
level's terrain source after its gates (`terrain source set to '<settings default: the survey>'`).

Measured in the engine, on three real roads (flat Margate, a 24° slope at Ramsgate, the cliff top at
Cliftonville), 1,141 points across the carriageway, `04_probe.py --points ... --landscape`:

| | before (survey heightfield) | after (the imported ALandscape) |
|---|---|---|
| road − ground, minimum | **−2.1809 m** | **+0.0274 m** |
| road − ground, p50 | −0.0375 m | +0.0388 m |
| points with ground above the road | **807 of 1141** | **0 of 1141** |

and the downward line trace at those points hits the road mesh itself at 944 of 1,141 (8 reach the
landscape, the rest hit the kerb, pavement or a marking), so the surface being measured is the one
that is actually there.

`Streetscape.Conform.NoFusion` says the same thing inside the automation suite: *8 splines, 507
stations: worst penetration 0.000000 m (was 2.187067 m on the survey), 0 stations penetrated (459
fused before)*. Suite: **26 of 26 pass** (`Saved/Logs/ue_tests_conform.log`), and the numpy suite is
**115 of 115** (100 before, 15 new in `test_conform.py`).

## 8.9 The captures, and the landscape LOD that hides a 3 cm sink

`projects/one/Tools/ue/shots/`, eye level (1.65 m above the carriageway), 1600 × 900, materials
audited (`slots_using_engine_default` 0; tarmac, concrete kerb, paving slab, brick, ballast, privet):

| file | where | what it shows |
|---|---|---|
| `conform_flat_margate.png` | `roads:33732297:3`, unclassified, local (5314.8, 5060.3), flat | carriageway, both kerbs and pavements, the OSM overlay; before the conform this stretch had ground up to 1.44 m through it |
| `conform_slope_ramsgate.png` | `roads:28077736:0`, residential, (11554.6, 3656.4), 24° ground | the road holding its line across a slope with massing and steps behind |
| `conform_cliff_cliftonville.png` | `roads:151099555:0`, service, (9105.3, 8261.7), cliff top | the road running out to the cliff edge, sea beyond |

Two diagnostic frames are kept beside them: `diag_top_margate.png` (the same road from above with the
landscape at its default LOD) and `diag_top_lod0.png` (identical camera, LOD 0 pinned).

**What they cost to get right.** The first captures showed green wedges through the carriageway that
look exactly like the defect. They are not it, and the difference matters:

* the landscape's **render** mesh at LOD > 0 is not the surface its own `GetHeightAtLocation`
  returns — the LOD chain drops vertices and morphs between levels, so the drawn ground moves by
  decimetres while the data does not. Against a 0.03 m sink it draws straight through the road.
* proved by exclusion and by construction: the queried clearance at those exact places is +0.027 m
  or more (§8.8); 944 of 1,141 downward traces hit the road mesh, so the mesh is not full of holes;
  `r.SetNearClipPlane=100` changes nothing, so it is not depth precision; `r.Nanite=0` changes
  nothing; `r.Fog=0` **does** change the frame, so the console plumbing works. Setting the landscape
  actor's `lod0_screen_size` to 8 removes every wedge (`diag_top_lod0.png`) — and
  `landscape.OverrideLOD` does not, because it never reaches a SceneCapture's view.

`05_screenshot.py` therefore gained `--landscape-lod0-screen-size` (and `--cvars`, which the
diagnosis needed). It is a **capture** setting: at runtime the same 3 cm can be swallowed by the LOD
at distance, and the answer there is the landscape's own LOD distribution, not a deeper sink — a
deeper sink would show daylight under the 0.03 m kerb tuck. That is recorded as the one open problem
this round leaves in the engine.

The green sliver still visible along the centre of `conform_slope_ramsgate.png` survives LOD 0: two
OSM ways run parallel there and the sliver is the ground **between** two road ribbons, which no
carriageway covers. It is a network-modelling question (D5), not a fusion one — the probe over that
spline reports a minimum clearance of +0.0278 m over 371 points.
