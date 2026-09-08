# Design: `sources/adapters/unreal.py`, its manifest and tests, and the first-deliverable test stretch

Design-phase document for Project One (`projects/one/docs/BRIEF.md` §4.1, §4.2, §4.4 are binding here).
Everything below was derived from files on disk on 2026-09-07; every repo fact carries a path and line,
every engine fact a header path and line under `C:/Program Files/Epic Games/UE_5.8/Engine/`. Nothing in
this document changes the pipeline: the adapter is a *consumer* of `data/<site>/out/` exactly like
`sources/adapters/unity.py`, and the pipeline stays engine-neutral (`sources/OUTPUT.md`, "Nothing here
knows about any engine").

Contents

- Part A — the adapter: §A1 module layout, §A2 output tree, §A3 landscape products, §A4 streetscape
  products, §A5 massing and furniture, §A6 `unreal.json`, §A7 frame functions and the worked example,
  §A8 tests, §A9 refusals, §A10 schema fields this design needs, §A11 contracts assumed from other
  subsystems.
- Part B — the test stretch: §B1 method and candidates, §B2 the chosen stretch, §B3 terrain along it,
  §B4 authoring plan, §B5 railway, §B6 the data block for `schema/examples/test_stretch.json`.

Sources read for this design (repo): `sources/OUTPUT.md`; `sources/adapters/unity.py` (193 lines) and
`unity.json`; `sources/lib.py`; `sources/derive/05_export_terrain.py`, `06_build_networks.py`,
`09_coast.py`, `10_furniture.py`; `sources/tests/dryrun.py` (415 lines) and
`sources/tests/fake_osgeo/osgeo/__init__.py`; `sources/config/tuning.json`, `sources/config/sites/margate.json`;
`data/margate/out/terrain/terrain_manifest.json`, `networks/networks_manifest.json`,
`coast/coast_manifest.json`, `roads_*.jsonl`, `buildings_*.jsonl`, `furniture_*.jsonl`,
`data/margate/derived/margate.gpkg` (read-only), `data/margate/interim/dtm.vrt` (read-only).

---

## Part A — the adapter

### A0. What the adapter is and is not

`sources/adapters/unreal.py` reads the neutral products under `data/<site>/out/` (plus the step-01
GeoPackage under `data/<site>/derived/` for the raw OSM polylines and tags) and writes
`data/<site>/out/unreal/`. It mirrors `unity.py` in shape (`need()`, one function per product, a
`_note`-carrying `unreal.json`, refusal instead of silent clipping — `unity.py:57-62`) and in
philosophy: **it converts, it never invents**. Two differences from `unity.py`, both deliberate:

1. **No engine frame is baked into the output.** `unity.py` emits Y-up, south-first rasters because
   Unity needs them. Here the output frame is the *Streetscape JSON frame* of BRIEF §4.2: local metres
   from the site origin, X east, Y north, Z up = ODN metres unchanged, right-handed. The ×(100, −100,
   100) to Unreal centimetres and the yaw sign flip happen **only** in the C++ JSON loader and the
   landscape importer (BRIEF §4.2 last row; Epic's own FlatPlanet convention,
   `Plugins/Runtime/GeoReferencing/Source/GeoReferencing/Private/GeoReferencingSystem.cpp:235`:
   `EngineCoordinates = UEWorldCoordinates * FVector(100.0, -100.0, 100.0)`). Rasters stay north-first
   because a north-first row 0 is already the smallest UE Y (§A3.6 proves it against the engine's
   indexing).
2. **Module level does no site I/O.** `unity.py` calls `lib.load()` at import (`unity.py:27`), which
   makes its pure helpers untestable without a site. `unreal.py` keeps every conversion function pure
   and does `lib.load()` inside `main()`, so `sources/tests/test_unreal_adapter.py` can import the
   module with `importlib` and unit-test the encoders and frame functions with numpy alone.

### A1. Module layout (`sources/adapters/unreal.py`)

```python
#!/usr/bin/env python3
"""Neutral pipeline output -> Unreal / Streetscape-JSON conventions.  (docstring: the six conversions,
the frame statement of BRIEF 4.2, and 'writes data/<site>/out/unreal/, never touches the neutral output')"""
import glob, json, math, os, sys
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions(); ogr.UseExceptions()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

ADP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unreal.json")
SCHEMA_VERSION = "1.0.0"          # must equal projects/one/schema/streetscape.schema.json $id version
FRAME = ("local metres from origin (E0,N0): x = E - E0 (east), y = N - N0 (north), z = ODN metres "
         "unchanged; right-handed, Z up. Unreal: X_ue = 100*x, Y_ue = -100*y, Z_ue = 100*z (cm, +Y south); "
         "yaw_ue = bearing - 90 = -heading_deg. Applied only by the Unreal loader/importer, never here.")

# ---- pure functions: no site, no files ----------------------------------------------------------
def encode_h16(z_m, per_unit=128, offset=32768):      # float array (m) -> np.ndarray dtype '<u2'
def decode_h16(h16, per_unit=128, offset=32768):      # -> float64 metres; decode(encode(z)) within 1/256 m
def check_range(range_m, limit_m):                    # sys.exit if range_m[0] < limit[0] or range_m[1] > limit[1]
def survey_to_local(E, N, z, E0, N0):                 # -> (E - E0, N - N0, z)
def local_to_ue_cm(x, y, z):                          # -> (100*x, -100*y, 100*z); DOCUMENTATION + TESTS ONLY
def bearing_to_heading_deg(bearing):                  # -> ((90 - bearing + 180) % 360) - 180   in (-180, 180]
def bearing_to_ue_yaw(bearing):                       # -> (bearing - 90) % 360; DOCUMENTATION + TESTS ONLY
def douglas_peucker(xy, tol_m, keep=()):              # -> sorted list of kept indices; 0 and n-1 always kept
def chain_segments(records):                          # tile-split records of ONE way -> ordered list (see A4.4)
def nearest_z(xy, chain_xyz):                         # z of the nearest chain vertex (overlay z, see A4.7)
def parse_height_m(text):                             # "1.2", "2", "2 m", "1.2m" -> float | None (fallback only; step 11 emits h)
def classify_barrier(cls, rec, adp):                  # -> ("brick_wall"|..., height_m, thickness_m, height_src) | None (skipped)
def profile_ids_for(layer, cls, tags, pav, adp):      # -> {"road": id|None, "edge": id|None, "hedge": id|None}
def load_profiles(profiles_dir):                      # -> {id: profile dict}; refuses duplicates
# ---- products -------------------------------------------------------------------------------------
def landscape(cfg, adp, src, out) ; def streetscape(cfg, adp, src, out)
def massing(cfg, adp, src, out)   ; def furniture(cfg, adp, src, out)
def write_root_manifest(cfg, adp, out, stats)
def main(argv=None):
    cfg = lib.load(); P = lib.paths(cfg); adp = json.load(open(ADP_PATH, encoding="utf-8"))
    out = os.path.join(P["out"], "unreal"); lib.mkdirs(out)
    print(f"unreal adapter: {cfg['site']}  ({cfg['crs']} -> local metres from E{E0} N{N0}; Y north; Z ODN)")
    stats = {}; stats["landscape"] = landscape(...); stats["streetscape"] = streetscape(...); ...
    write_root_manifest(...)
if __name__ == "__main__": main()
```

Run: `SITE=thanet C:/Users/Shadow/code/3duk-env/env/python.exe sources/adapters/unreal.py` (from the
repo root, GDAL env as in `run.sh`). `run.sh` prints the Unity hint at its end (`sources/run.sh`, last
line); the pipeline task should add the equivalent Unreal hint (see §A11).

### A2. Output tree

```
data/<site>/out/unreal/
  unreal_manifest.json                     root manifest: site, crs, origin, vertical_datum, frame (words),
                                           schema_version, adapter settings (copy of unreal.json), products[],
                                           and the key numbers of every source manifest it consumed
  landscape/
    landscape_manifest.json                §A3.5
    hm_x{i}_y{j}.r16                       uint16 LE, res x res (513x513), row 0 = north      §A3.1
    clip_x{i}_y{j}.r8                      uint8, res x res, 255 keep / 0 clipped-or-nodata    §A3.2
    weight_grass_x{i}_y{j}.r8              uint8, class_res x class_res (256x256), row 0 = north §A3.3
    weight_sand_x{i}_y{j}.r8   weight_rock_x{i}_y{j}.r8   weight_water_x{i}_y{j}.r8
  streetscape/
    profiles.json                          every profile referenced by any spline, by id       §A4.2
    site_x{i}_y{j}.json                    one Streetscape-JSON document per pipeline tile     §A4.1
    streetscape_manifest.json              counts, thinning stats, profile ids used, tags coverage
  massing/
    buildings_x{i}_y{j}.jsonl              rings in local metres, base_z kept as z             §A5.1
    massing_manifest.json
  furniture/
    furniture_x{i}_y{j}.jsonl              local x,y,z + bearing + heading_deg                 §A5.2
    furniture_manifest.json
```

Tile naming is the pipeline's (`x{i}_y{j}`, `i` east from `origin.E`, `j` north from `origin.N`,
`OUTPUT.md` "Tiles"). The overlay polylines are **inline** in each spline record (`overlay_points`,
§A4.7) — one file per tile carries everything a streaming cell needs; a separate `overlay/` directory
would be a second copy of the same geometry to keep in sync.

### A3. Landscape products

#### A3.1 Heightmap `hm_x{i}_y{j}.r16`

Per terrain tile in `terrain_manifest.tiles[]` (`05_export_terrain.py:68-76`), read
`terrain/dtm_x{i}_y{j}.tif` with GDAL, `a = band.ReadAsArray().astype(np.float64)`, refuse if
`a.shape != (res, res)` (`res` = `terrain_manifest.res`, 513 for Margate/Thanet). Nodata cells
(`lib.nodata_mask(a, band.GetNoDataValue())`, `lib.py:110-118`) are the clipped cells (§A3.2); for the
heightmap they are filled with `lib.fill_nodata` (nearest-valid; `lib.py:84-107`) so the last visible
quad at the hole edge continues real ground, and the method is recorded per tile as `clip_fill`.

Encoding, chosen so that **with landscape actor Z scale = 100 the engine height equals the ODN height
to the encoding quantum**:

```
h16 = round(z_m * 128) + 32768                 stored as uint16, little-endian, row-major
z_m = (h16 - 32768) / 128                      exact inverse; quantum 1/128 m = 0.78125 cm,
                                               max round-trip error 1/256 m = 0.39 cm
```

Why 128 and 32768: the engine decodes a landscape height texel as
`(Height - MidValue) * LANDSCAPE_ZSCALE` with `LANDSCAPE_ZSCALE (1.0f/128.0f)` and `MidValue = 32768.f`
(`Source/Runtime/Landscape/Public/LandscapeDataAccess.h:13-14, 26-27, 30-33`,
`LandscapeDataAccess::GetLocalHeight`). That local height is in the actor's local units, multiplied by
the actor's Z scale to reach world centimetres; with Z scale 100, world Z (cm) = 100 · (h16 − 32768)/128
= 100 · z_m — i.e. ODN metres become UE centimetres with no site-specific window and no normalisation.
Adjacent tiles trivially share the encoding (no per-tile min/max), so the shared 513th edge row is
bit-identical across the seam (step 05 guarantees identical borders, `OUTPUT.md` "terrain").

The engine's own encoder `GetTexHeight` **clamps silently** to 0..65535
(`LandscapeDataAccess.h:35-38`); a site whose ground exceeded the window would come out as a plateau
with no error anywhere — the exact failure `unity.py:57-62` refuses. So the adapter refuses too:
`check_range(terrain_manifest.range_m, unreal.json landscape.range_limit_m = [-255, 255])`. The
encodable window is −256.0..+255.99 m; the 1 m margin covers rounding and the fill values. Thanet is
−3..+60 m (BRIEF §4.4; Margate manifest `range_m [-2.91, 49.81]`), so this guard is a check, not a
constraint. The r16 is written with `h16.astype('<u2').tofile(path)`; the engine reads a `.r16` as a raw
`memcpy` of `Width*Height*2` bytes with no header and no byte-swap
(`Source/Editor/LandscapeEditor/Private/LandscapeFileFormatRaw.cpp:153-176`), and the target is
little-endian x64, so the file is exactly what `TArray<uint16>` wants. **No row flip** (§A3.6).

#### A3.2 Clip mask `clip_x{i}_y{j}.r8`

`uint8`, `res × res`, same row order as the heightmap: **255 = keep, 0 = clipped or nodata**. Derived
from the terrain tile *after* step 05: the pipeline design (BRIEF §4.1 "Crop semantics") makes step 05
write **nodata** for cells outside the clip half-plane while still filling genuine coverage gaps, so any
cell that is still nodata in `terrain/dtm_*.tif` is a deliberate absence. Consistency is enforced
against the manifest rather than assumed:

- If `terrain_manifest.clip` exists: for every tile `count(mask == 0)` must equal
  `tile.clipped_cells`; otherwise refuse ("terrain tile and manifest disagree on clipped cells — stale
  output, re-run step 05").
- If `terrain_manifest.clip` is absent (Margate, Whitby): `count(mask == 0)` must be 0 on every tile
  (05 filled everything, `05_export_terrain.py:45`); otherwise refuse.
- If the **site config** has a `clip` block and the terrain manifest has none, or the two `line`
  endpoints differ: refuse ("config has a clip the terrain manifest does not — stale output").

The mask is *keep* semantics because that is what the data says. The UE landscape **visibility layer**
paints *holes*: a vertex whose visibility weight exceeds `LANDSCAPE_VISIBILITY_THRESHOLD (2.0f/3.0f)`
(`LandscapeDataAccess.h:19`) is cut by marching squares
(`Source/Runtime/Landscape/Private/LandscapeEdit.cpp:4411`,
`UE::Landscape::GenerateMarchingSquaresGeometry(Visibilities, LANDSCAPE_VISIBILITY_THRESHOLD, ...)`).
The importer therefore feeds `visibility = 255 - clip` into the `FLandscapeImportLayerInfo` for
`ALandscapeProxy::VisibilityLayer` (`Source/Runtime/Landscape/Classes/LandscapeProxy.h:1002`,
`LandscapeProxy.h:193-218` for the struct, `LayerData` at `:208`). With a binary mask the iso-contour
at 2/3 falls inside the 1 m cell straddling the line, so the edge is the exact line to within one
cell; the manifest records this (`clip_mask.ue_visibility_weight`). Upgrade path if a staircase is
ever visible: a signed-distance weight `w = clamp(2/3 + d/1 m, 0, 1)` computed from the manifest's
`clip.line` (d = signed distance into the clipped half-plane) makes the 2/3 contour land exactly on the
line; not built now because the line crosses only farmland and the 1 m error is below the DTM's own
positional accuracy.

#### A3.3 Ground-cover weightmaps `weight_{grass,sand,rock,water}_x{i}_y{j}.r8`

From `coast/ground_x{i}_y{j}.tif`, four Byte bands in manifest order `["grass","sand","rock","water"]`
summing to 255 (`09_coast.py:168-179, 186-196`), `class_res × class_res` (256; `tuning.json:57`),
north-up (`09_coast.py:172-175`). On a clipped site the pipeline design writes **all four bands zero**
for cells outside the clip (`pipeline.md` §3.6: "the only way a cell can sum to 0"), so the sum is 255
inside and 0 under the hole — harmless for an Additive import and consistent with the clip mask; the
adapter checks `sum ∈ {0, 255}` per cell and refuses anything else. One `.r8` per band, `uint8`,
**no flip, no rescale, no re-blend**:
unlike `unity.py:145` (which hands the water remainder to grass because Unity alphamaps must sum to 1
over three layers) the Unreal side takes all four layers, and the bands already sum to 255 — exactly
`ELandscapeImportAlphamapType::Additive` ("All alpha maps for blended layers total to 1.0",
`LandscapeProxy.h:178-190`). Tiles listed in `coast_manifest.tiles_without_dtm` have no raster and get
`weights: null` in the landscape manifest. The engine reads `.r8` weightmaps as raw 8-bit
(`LandscapeFileFormatRaw.cpp:200-260`). Resolution note for the importer: landscape weightmaps are
per-vertex (`VertsX × VertsY` = 513 per tile), so the importer resamples 256 → 513 (nearest or
bilinear; `FLandscapeImportHelper::TransformWeightmapImportData(..., ELandscapeImportTransformType::
Resample)`, `Source/Editor/LandscapeEditor/Public/LandscapeImportHelper.h:137, 49-58`). The adapter
emits the native 256 rather than upsampling so the product stays lossless and the resampling choice
is the importer's, recorded there. `weight_res` is in the manifest.

#### A3.4 Padding and missing tiles

`terrain_manifest.tiles_missing` (no source tile at all, `05_export_terrain.py:40`) are copied into
the landscape manifest unchanged. The adapter writes **no** heightmap for them — inventing a tile
would blur "measured" and "filled" (`OUTPUT.md`: "do not assume they are sea"). The importer pads the
landscape there (BRIEF §6 Q1) and the manifest carries the agreed pad value so both sides use the same
number: `pad_value_h16 = encode_h16(water_level)` = 32691 for Margate/Thanet (`water_level −0.6`:
round(−76.8) + 32768), plus `pad_visibility: "hidden"`.

#### A3.5 `landscape_manifest.json`

```json
{
 "site": "thanet", "crs": "EPSG:27700", "origin": {"E": 627680, "N": 163080}, "vertical_datum": "ODN",
 "tile_m": 512, "res": 513, "nx": 26, "ny": 19, "weight_res": 256,
 "frame": "<FRAME string, A1>",
 "heightmap": {
   "file": "hm_x{i}_y{j}.r16", "dtype": "uint16 little-endian, row-major", "shape": [513, 513],
   "row0": "north", "col0": "west", "row_flip_for_ue": false,
   "z_encoding": {"formula": "h16 = round(z_m * 128) + 32768", "per_unit": 128, "offset": 32768,
                  "scale_z_cm": 100, "decode": "z_m = (h16 - 32768) / 128",
                  "quantum_m": 0.0078125, "max_roundtrip_error_m": 0.00390625,
                  "engine": "LandscapeDataAccess::GetLocalHeight, LANDSCAPE_ZSCALE = 1/128 (LandscapeDataAccess.h:13); actor scale Z 100 -> world cm = 100 * z_m"},
   "range_limit_m": [-255, 255]
 },
 "clip_mask": {"file": "clip_x{i}_y{j}.r8", "semantics": "255 keep, 0 clipped-or-nodata after step 05",
               "ue_visibility_weight": "255 - clip (visibility layer paints holes; cut threshold 2/3, LandscapeDataAccess.h:19)"},
 "weightmaps": {"files": "weight_{grass,sand,rock,water}_x{i}_y{j}.r8", "res": 256, "row0": "north",
                "bands": ["grass", "sand", "rock", "water"], "sum": 255, "alphamap_type": "Additive",
                "importer_note": "resample 256 -> 513 vertices; weights are per landscape vertex"},
 "range_m": [-2.91, 49.81], "elevation_units": "metres",
 "water_level": -0.6, "pad_value_h16": 32691, "pad_visibility": "hidden",
 "ue_import": {"actor_location_cm": [0, -972800, 0], "actor_scale": [100, 100, 100],
               "verts": [13313, 9729], "quads_per_tile": 512,
               "tile_quad_origin": "x0 = tile_m*i, y0 = tile_m*(ny-1-j); heightmap row r, col c -> landscape vertex (x0+c, y0+r)"},
 "clip": null, "tiles_clipped": [], "clipped_cells_total": 0, "source_nodata": null,
 "slope_qa": {"max_deg": 84.2, "pct_cells_over_45deg": 0.183, "note": "..."},
 "tiles_missing": [], "water_tiles": [[0,4], ...], "tiles_without_ground_raster": [],
 "tiles": [
   {"x": 15, "y": 15,
    "files": {"heightmap": "hm_x15_y15.r16", "clip": "clip_x15_y15.r8",
              "weights": {"grass": "weight_grass_x15_y15.r8", "sand": "...", "rock": "...", "water": "..."}},
    "min_m": 0.39, "max_m": 22.69, "h16_min": 32818, "h16_max": 35672,
    "clip_state": "inside", "clipped_cells": 0, "clip_fill": "none", "source_nodata_cells": 0, "source_fill": "none",
    "slope_max_deg": 78.5, "slope_p99_deg": 32.5, "cells_over_45deg": 708,
    "quad_origin": [7680, 1536]}
 ]
}
```

(The example tile row uses the real Margate `dtm_x5_y5.tif` numbers — the test-stretch tile — from
`terrain_manifest.json`: min 0.39, max 22.69 m → h16 32818..35672; `slope_max_deg 78.5` is the
Cliftonville cliff in that tile. `clip_state`, `tiles_clipped` and `nodata` appear only when the
terrain manifest has them, i.e. for a clipped site — the pipeline design adds them under
`if CLIP is not None`; `pipeline.md` §3.3.)

`clip`, `slope_qa`, per-tile `slope_*`, `cells_over_45deg`, `tiles_missing` are **copied verbatim** from
the terrain manifest so the importer can prove cliffs survived (`OUTPUT.md` "slope_qa": "This is how
you prove cliffs survived") without opening a second manifest. `water_tiles` and
`tiles_without_ground_raster` come from `coast_manifest.json` (`water_tiles`, `tiles_without_dtm`).
`ue_import.actor_location_cm[1] = -100 * tile_m * ny` (= −972 800 for ny 19); `verts = [nx*512+1,
ny*512+1]` = [13313, 9729] for nx 26, ny 19. (BRIEF §6 Q1 says "12801×9729"; 12801 = 25·512+1, which
does not match nx 26 — flagged for the importer designer.)

#### A3.6 Why row 0 = north needs no flip (and the tile → landscape mapping)

`ALandscapeProxy::Import` indexes the incoming height array as
`HeightData[Y * VertsX + X]` (`LandscapeEdit.cpp:3120`, the `HEIGHTDATA(X,Y)` macro used by the import
loop starting `:3123`; `VertsX = InMaxX - InMinX + 1`, `:3139`). Row index = landscape local Y, which
grows toward the actor's +Y = UE world +Y (identity rotation). BRIEF §4.2 maps `Y_ue = −100·y`, so UE
+Y is **south**: the smallest landscape Y is the northernmost row, i.e. GeoTIFF row 0. The heightmap
and the weightmaps are therefore written exactly as the pipeline's north-up rasters. Placement: the
landscape actor at `(0, −100·tile_m·ny, 0)` cm with scale (100, 100, 100) puts landscape vertex
(qx, qy) at local `x = qx` m, `y = tile_m·ny − qy` m; tile (i, j) occupies quads
`x ∈ [512i, 512i+512]`, `y_q ∈ [512(ny−1−j), 512(ny−1−j)+512]`; heightmap row r / column c of that tile
is landscape vertex `(512i + c, 512(ny−1−j) + r)`. Check: row 512 of tile j (its south edge, local
y = 512j) is row 0 of tile j−1 (north edge of tile j−1, also y = 512j). The test in §A8 asserts the
north-first order on a synthetic tile whose height increases northward.

### A4. Streetscape products

#### A4.1 Per-tile documents `site_x{i}_y{j}.json`

One Streetscape-JSON document per pipeline tile that has any network record — matching World
Partition streaming cells (BRIEF §4.4 "one World Partition ALandscape with streaming proxies", §6 Q8)
and the fact that step 06 already splits ways at tile seams with the seam vertex duplicated on both
sides (`06_build_networks.py:196-200`). A single `site.json` was rejected: for Thanet it would be a
~50–100 MB document that every load must parse whole, and the seam bookkeeping (§A4.4) would still be
needed for streaming. Each document:

```json
{
 "schema_version": "1.0.0",
 "site": "thanet", "crs": "EPSG:27700", "origin": {"E": 627680, "N": 163080}, "vertical_datum": "ODN",
 "frame": "<FRAME string>",
 "tile": {"x": 15, "y": 15, "tile_m": 512, "bounds_local": [7680.0, 7680.0, 8192.0, 8192.0]},
 "profiles_file": "profiles.json",
 "profile_ids_used": {"road": ["road_residential", "path_footway"], "edge": ["edge_uk_kerb"], "hedge": []},
 "splines": [ ... ],            // §A4.3
 "junctions": [ ... ]           // §A4.6
}
```

Header names follow the geometry designer's schema as given: `schema_version, site, crs, origin{E,N},
vertical_datum, frame`. `tile` and `profiles_file` / `profile_ids_used` are additions (§A10).

#### A4.2 `profiles.json`

The profile *definitions* live in `projects/one/schema/profiles/*.json` (BRIEF §4.3), one profile per
file with at least `{"id": "...", "kind": "road"|"edge"|"hedge", ...}`. The adapter loads that directory
(`unreal.json streetscape.profiles_dir`, repo-relative to `lib.ROOT`), refuses on a duplicate id or a
missing directory, verifies that **every id the class map can produce exists**, and writes
`streetscape/profiles.json` = `{"schema_version", "source_dir", "profiles": {"road": {id: def},
"edge": {id: def}, "hedge": {id: def}}}` containing only the ids actually referenced by this site's
splines. Consumers resolve `profile_ids.*` against this one file; the per-tile documents carry only
ids. The default UK profiles this design references (to be authored by the schema task): `road_trunk,
road_primary, road_secondary, road_tertiary, road_residential, road_unclassified, road_living_street,
road_service, road_pedestrian, path_footway, path_cycleway, path_track, rail_standard, edge_uk_kerb,
edge_uk_kerb_grass, edge_barrier_only, hedge_privet`.

#### A4.3 Spline record

```json
{
 "id": "road:30253079:0",
 "source": {"layer": "road", "osm_id": "30253079", "name": "Trinity Square", "cls": "residential",
            "segment_index": 0, "segment_count": 1, "tile": [15, 15],
            "tags": {"sidewalk": "both", "sidewalk:left": null, "sidewalk:right": null, "lanes": null,
                     "lanes:forward": null, "lanes:backward": null, "lane_markings": "no", "oneway": null,
                     "surface": "asphalt", "maxspeed": "30 mph", "lit": "yes",
                     "parking:lane:left": null, "parking:lane:right": null, "parking:lane:both": null}},
 "profile_ids": {"road": "road_residential", "edge": "edge_uk_kerb", "hedge": null},
 "profile_overrides": {"edge": {"pavement_width_m": 1.5, "sides": "both"},
                       "road": {"markings": []}},
 "points": [{"x": 8099.98, "y": 8171.12, "z": 20.56, "width_m": 6.0, "roll_deg": null, "tags": []}, ...],
 "sampling": {"height_source": "terrain",
              "z_note": "z = step 06 bilinear drape on the 1 m DTM after Chaikin smoothing; informative only, renderers re-sample and smooth from the heightfield",
              "terrain_hint": {"tile": [15, 15], "heightfield": "../landscape/hm_x15_y15.r16"}},
 "segments": {"drop_kerbs": [], "barriers": [], "hedge": [], "embankments": []},
 "flags": {"bridge": false, "tunnel": false, "z_gap": false},
 "continues_from": null, "continues_to": "road:879045149:0",
 "continuation_kind": {"from": null, "to": "way"},
 "overrun_points": {"before": null, "after": [7956.16, 8158.98, 18.51]},
 "overlay_points": [[8099.98, 8171.12, 20.56], [8076.93, 8165.98, 20.47], ...]
}
```

Field-by-field:

- `id` = `"{layer}:{osm_id}:{segment_index}"`, layer ∈ `road | rail | barrier`. Unique across the site
  because step 06/11 write each (way, tile-run) exactly once.
- `source.tags`: the OSM tags listed in `unreal.json streetscape.tags_passthrough`, read from the
  step-01 GeoPackage `lines` layer `other_tags` (hstore text, parsed with the same `tagval()` as
  `06_build_networks.py:72-78`). Step 06 emits only `w, pav, bridge, tunnel` (`06_build_networks.py:142`),
  not `sidewalk`/`lanes` (`OUTPUT.md` "networks/"), and the adapter already opens the GeoPackage for
  the overlay polyline, so the tags come at no extra cost. What the *pipeline* would ideally provide
  later: a `tags` object on each 06/11 record (contract change in `OUTPUT.md`, owned by the pipeline
  task), after which the adapter stops reading `other_tags` — flagged in §A11, not required now.
- `profile_ids`: from `unreal.json` (§A6) by layer, `cls`, tags and `pav`:
  - roads: `road_profile_by_class[cls]` (all 21 classes in `tuning.json:7-17` are mapped; an unmapped
    class is a refusal, because `tuning.json` and `unreal.json` would have drifted apart);
    `edge = edge_profile_default` (`edge_uk_kerb`) **iff** `pav > 0` and `tags.sidewalk != "no"` and
    `cls ∉ path_classes`; else `null`. Footway / path / steps / cycleway / bridleway / track /
    pedestrian are **Renderer-A flat ribbons** with `path_*` / `road_pedestrian` profiles (no
    markings, paving material) and **no edge renderer**: a footpath is a flush strip, not a
    kerbed pavement slab; the pavement-only-edge alternative was rejected because it would give every
    park path two kerbs. `steps` additionally gets `points[*].tags = ["steps"]` on the first point and
    `flags.steps = true` so a later stair renderer can find them.
  - `profile_overrides.edge.sides`: `"both"` for `sidewalk ∈ {both, yes, null}`, `"left"` /
    `"right"` for `sidewalk = left/right` (also from `sidewalk:left|right = yes`), no edge renderer for
    `sidewalk = no` or `separate` (mapped separately in OSM). Left/right are relative to the OSM way
    direction, which the adapter preserves (06 keeps vertex order, `06_build_networks.py:119, 161`).
    `pavement_width_m = pav` (metres, each side, `OUTPUT.md`). Margate has `sidewalk=both` on 471 of
    1064 residential/tertiary ways, `left` 70, `right` 40, `no` 42, `separate` 1 (measured 2026-09-07).
  - `profile_overrides.road.markings = []` when `tags.lane_markings == "no"` (387 Margate highways say
    so, 148 say yes). Otherwise no override: the profile's default marking list stands.
  - rail (step 11 record: `{"id","cls","gauge" (metres, 1.435),"gauge_src","tracks","electrified",
    "service","usage","bridge","tunnel","name","z_gap","pts"}`, `pipeline.md` §4.2): `road =
    rail_profile_by_gauge_m[f"{gauge:.3f}"]` (`"1.435"` → `rail_standard`); any other gauge →
    `rail_standard` plus `flags.gauge_unmapped = true` and a manifest count (never a silent drop).
    `cls` (`rail`, `disused`, `light_rail`, …), `gauge`, `gauge_src`, `tracks`, `electrified`,
    `service`, `usage` are copied into `source.tags`; `disused` additionally sets `flags.disused =
    true` so a consumer can filter. `edge = hedge = null`.
  - barriers (step 11 record: `{"id","cls","h" (metres, already defaulted by step 11 from
    `tuning.barriers.default_height_m`),"h_src","material","fence_type","wall","name","z_gap","pts"}`):
    `road = null`; `edge = "edge_barrier_only"` with `segments.barriers =
    [{"s0": 0.0, "s1": L, "type": T, "height_m": h, "thickness_m": t, "material": material}]` over
    the whole spline; `profile_overrides.edge = {"kerb_width_m": 0, "pavement_width_m": 0,
    "barrier_offset_m": 0}` because the spline *is* the barrier line. `T` from `classify_barrier`
    (§A6 rules, first match wins): `wall → brick_wall` (or `concrete_wall` / `stone_wall` by
    `material` / `wall`), `city_wall → stone_wall`, `fence → chain_link | railing | wood_fence` by
    `fence_type` / `material`, `guard_rail → guard_rail`, `handrail → railing`, `retaining_wall →
    retaining_wall` (the embankment/retaining kind of BRIEF §1.1 "LIDAR / HEIGHT MAPPING" edge case),
    `kerb → kerb_only` (edge profile `edge_uk_kerb` with pavement 0 and no barrier), `hedge →` the
    **hedge renderer**: `edge = null`, `hedge = "hedge_privet"`, `segments.hedge = [{"s0": 0.0,
    "s1": L, "height_m": h, "width_m": default_thickness_m.hedge}]`. Step 11 already drops `gate`,
    `bollard`, `yes`; the adapter still skips and counts any `cls` it has no rule for, rather than
    refusing, because the barrier class list is pipeline tuning. `height_m = h` (step 11's parsed or
    defaulted value; `h_src` goes into `source.tags`); only if a record lacks `h` does the adapter's
    own `default_height_m[T]` apply, and it says so in the manifest. Thickness is always the
    adapter's opinion (`default_thickness_m[T]`) — the pipeline design deliberately emits no width.
    Margate has 467 barrier ways: wall 175, fence 173, hedge 42, retaining_wall 30, kerb 19,
    bollard 13, gate 13, yes 2; only 15 carry `height`, 33 `material`, 42 `fence_type` (measured
    2026-09-07, agreeing with `pipeline.md` §0.2).
- `points[]`: local metres, `z` = 06's draped elevation, `width_m` = `w` on **every** kept point of a
  road spline (so no interpolation semantics are assumed of the schema; rail and barrier points carry
  no `width_m` and take the profile's), `roll_deg: null` (banking is computed from terrain by the
  renderers, BRIEF §1.1), `tags: []`. Thinning: §A4.5.
- `sampling.height_source = "terrain"`: the renderers re-sample and smooth heights from the heightfield
  (BRIEF §1.1 "Smooth sampled heights with a moving average"). The JSON `z` is informative (it lets
  Blender draw the raw polyline before any terrain is loaded, and it is the seam-consistent value 06
  chose). `terrain_hint` tells a heightfield-file sampler which tile to open (§6 Q3).
- `segments`: empty lists for roads/rail (authored later or by the test-stretch file); filled for
  barriers/hedges as above.
- `flags`: `bridge`, `tunnel`, `z_gap` passed through from 06/11 (`OUTPUT.md`). No deck offsets are
  applied — the Unreal profile decides what a bridge looks like; the neutral elevation is the ground
  under the structure and stays honest.
- `continues_from/to`, `continuation_kind`, `overrun_points`: §A4.4.
- `overlay_points`: §A4.7.

#### A4.4 Seams and way joins

Step 06 buckets a way into per-tile runs and duplicates the seam vertex in both runs
(`06_build_networks.py:196-200`, tested by `dryrun.py:218`). The adapter groups all records of one
`(layer, osm_id)` from all tile files, then `chain_segments()` orders them by matching an end vertex of
one run to the start vertex of the next (exact equality of the rounded `[E, N]`, which is what 06
wrote to both) — the way's vertex order is preserved, so `segment_index` counts along the OSM way
direction. For consecutive runs k and k+1: `continues_to(k) = id(k+1)`, `continues_from(k+1) = id(k)`,
`continuation_kind = "seam"`. If a chain cannot be closed (a run whose ends match nothing — possible
only if 06's output was edited) the adapter refuses.

Two further cases get the same treatment, because a renderer that extends its mesh a little past the
end of one spline into the next needs the same information for all three:

- `"way"`: a way end shared with exactly one other way of the same layer and no `_junction` record
  within `junction_snap_m` (0.3 m; 06 rounds junction keys to 0.1 m, `06_build_networks.py:132`). Step
  06 emits junction discs only where ≥ 3 ways meet (`tuning.json` `junction_min_ways 3`), so a 2-way
  node is a plain continuation (this is exactly the Trinity Square case, §B2: two ways, 6 m → 7 m).
- `null`: a dead end or a junction.

`overrun_points.before/after` carry the **one vertex beyond the join** taken from the neighbouring
spline (its second point, since the first is the shared vertex), in local metres. This lets the
Catmull-Rom end tangent at a seam match the neighbour's without loading the neighbour's tile file, so
the road-over-kerb overlap and the marking phase can be continued across the seam later (BRIEF §1.1
"Seam and overlap rules"). `overrun_points` is null at dead ends and at junctions.

#### A4.5 Waypoint thinning

06's `pts` are densified at 8 m and Chaikin-smoothed twice (`tuning.json:23-24`,
`06_build_networks.py:161`), leaving a vertex every ~2 m — on the 171 m test stretch, 115 vertices
for 11 OSM vertices. A Catmull-Rom (or any interpolating) resampler treats every waypoint as a knot:
115 knots two metres apart over-constrain it (any residual wobble in the Chaikin output becomes a
wobble in the tangent and therefore in the kerb offset) and bloat the tile documents by ~10×. The
adapter therefore thins in **XY only** with Douglas-Peucker at `thin_tolerance_m = 0.05` (5 cm),
always keeping the first and last vertex (which are the seam/junction vertices) — measured on the
test stretch: 115 → 13 points (20 at 2 cm, 11 at 10 cm, 8 at 25 cm). 5 cm is far below the DTM cell
(1 m), below OSM's positional accuracy (metres) and below what Chaikin itself moved the line by (up to
a quarter of the vertex spacing, `tuning.json chaikin_note`); the road-over-kerb overlap (≥ 3 cm,
BRIEF §5 stage 5) is unaffected because road and kerb share the spline. Heights are not a thinning
criterion: `height_source = "terrain"` means the resampler samples the heightfield at every
tessellated point and never lerps `z` between waypoints (BRIEF §1.1 "Train tracks"). A dead-straight
way collapses to its two end points, which is correct. `streetscape_manifest.json` records
`points_in`, `points_out` and `thin_tolerance_m`; set the tolerance to 0 in `unreal.json` to keep
06's vertices verbatim.

#### A4.6 Junctions

Each `_junction` record (`{"cls":"_junction","r":3.4,"pts":[[E,N,z]]}`, `OUTPUT.md`) becomes

```json
{"id": "junction:15_15:0", "x": 8100.0, "y": 8171.1, "z": 20.57, "r_m": 3.4,
 "incident": [{"spline": "road:30253079:0", "end": "start"}, {"spline": "road:462130116:0", "end": "end"}, ...]}
```

`incident` lists every spline in the same tile document whose first or last point lies within
`junction_snap_m` of the disc centre. This is the placeholder BRIEF §6 Q7 asks for ("junction nodes
referencing spline ends"); the renderers ignore it for the first deliverable. Known 06 limitation,
inherited: a T-junction onto the *interior* vertex of a through way is not a `_junction` (06 counts
endpoints only, `06_build_networks.py:131-139`) — the test stretch has four such side roads (§B2).

#### A4.7 Debug overlay

`overlay_points` = the **raw OSM way geometry** from the GeoPackage `lines` layer (the vertices before
06's densify/Chaikin/drape), in local metres, for the **whole way** on every one of its segments (the
raw vertices are sparse — 9 for the 145 m Trinity Square way — so clipping them per tile would lose
the seam crossing; duplicating a dozen numbers per extra tile is cheaper than a second file). `z` of
each overlay vertex = `z` of the nearest 06 vertex of the same way (`nearest_z`), recorded in the
manifest as `overlay_z: "nearest step-06 vertex; informative"` — it puts the debug line within a
couple of metres of the ground everywhere without the adapter re-reading the DTM mosaic (500 MB for
Thanet); the UE overlay component lifts it by a fixed 0.5 m and may re-drape on the landscape. This
is the "OSM visible as a debug / placeholder overlay" of BRIEF §1.1 stage 2.

### A5. Massing and furniture

#### A5.1 `massing/buildings_x{i}_y{j}.jsonl`

Every field of the step-07 record is kept (`OUTPUT.md` "massing/"); only `rings[*].pts` are converted
to local metres (`round(E − E0, 3), round(N − N0, 3)`, as `unity.py:121-123`). **`base_z` stays
`base_z`** and `skirt`, `h`, `ridge`, `eaves` are untouched — Z is up in this frame, so there is no
`base_y` rename (`unity.py:124` renames because Unity is Y-up). `massing_manifest.json` = the pipeline's
manifest plus `{"frame": FRAME, "coordinates": "rings in local metres, base_z/skirt ODN metres"}`.

#### A5.2 `furniture/furniture_x{i}_y{j}.jsonl`

```json
{"id":"8284208518","prop":"LitterBin","name":null,"x":7870.37,"y":6757.18,"z":null,
 "bearing":266.0,"heading_deg":-176.0,"src":"terrain","d":5.9,"cls":"footway","nudged":false}
```

`x, y` local metres; `z` = the pipeline's absolute elevation or `null` ("drape it yourself",
`OUTPUT.md`); `bearing` is kept unchanged — degrees clockwise from grid north is a compass heading and
means the same thing in all three frames; `heading_deg = bearing_to_heading_deg(bearing) = 90 −
bearing` wrapped to (−180, 180] is the same direction expressed as the Streetscape frame's own rotation
about +Z (counter-clockwise from +X = east, the right-handed convention Blender uses for `rotation_euler.z`).

Why not write `yaw = bearing − 90` into the record: that number is Unreal's yaw (clockwise from +X after
the Y flip; `bearing 131 → yaw 41`, BRIEF §4.2), and BRIEF §4.2 is binding that the Unreal conversion is
"applied only inside the Unreal plugin's JSON loader … never baked into the JSON". The relationship is
one sign: **`yaw_ue = −heading_deg = bearing − 90`** (mod 360) — the rotational counterpart of
`Y_ue = −100·y`. The adapter provides `bearing_to_ue_yaw()` for the manifest's worked example and the
unit test (§A7), the C++ loader implements the same line, and the furniture manifest states it in words:
`"ue_yaw": "yaw_ue = bearing - 90 = -heading_deg (applied by the loader)"`. `unity.py:179-183` had the
luxury that Unity's yaw about +Y *is* the bearing; here the two frames differ in handedness, so the
sign has to live in exactly one place, and BRIEF §4.2 says that place is the loader.

### A6. `unreal.json`

```json
{
  "_note": "Unreal / Streetscape-JSON consumer settings. Nothing in sources/derive/ reads this file. The adapter emits the Streetscape frame of projects/one/docs/BRIEF.md 4.2 (local metres from the site origin, X east, Y north, Z = ODN metres); the x100 / Y-flip / yaw sign to Unreal are applied ONLY by the Unreal plugin's loader and landscape importer and are quoted here for the record, not applied.",

  "frame": {
    "statement": "x = E - E0 (east), y = N - N0 (north), z = ODN metres. Unreal: X_ue = 100*x, Y_ue = -100*y, Z_ue = 100*z (cm). yaw_ue = bearing - 90 = -heading_deg.",
    "worked_example": {"survey": [635253.6, 171027.6, 17.2], "origin": [627680, 163080],
                       "local": [7573.6, 7947.6, 17.2], "ue_cm": [757360.0, -794760.0, 1720.0],
                       "bearing_deg": 131.0, "heading_deg": -41.0, "ue_yaw_deg": 41.0}
  },

  "landscape": {
    "heightmap_name": "hm_x{i}_y{j}.r16",
    "clip_name": "clip_x{i}_y{j}.r8",
    "weight_name": "weight_{band}_x{i}_y{j}.r8",
    "z_scale_cm": 100,
    "encoding": {"per_unit": 128, "offset": 32768, "formula": "h16 = round(z_m * per_unit) + offset"},
    "range_limit_m": [-255.0, 255.0],
    "clipped_fill": "nearest",
    "note": "per_unit 128 and offset 32768 are the engine's own (LANDSCAPE_ZSCALE = 1/128, MidValue 32768, Engine/Source/Runtime/Landscape/Public/LandscapeDataAccess.h:13,27); with the landscape actor's Z scale = z_scale_cm the engine height in cm is exactly 100 * z_m to 0.78 cm. The encodable window is -256..+256 m; range_limit_m keeps a 1 m margin and the adapter REFUSES a site outside it rather than clamping the way GetTexHeight (LandscapeDataAccess.h:35) silently would. clipped_fill is how nodata (= clipped) cells are filled in the heightmap under the hole; the clip mask carries the truth.",
    "cliffs_note": "The data holds cliff faces at 65-84 degrees (terrain_manifest.slope_qa). Import at 1 m (513 verts per 512 m tile), never resample, and compare the in-engine slope against slope_qa copied into landscape_manifest.json."
  },

  "streetscape": {
    "schema_version": "1.0.0",
    "profiles_dir": "projects/one/schema/profiles",
    "per_tile": true,
    "thin_tolerance_m": 0.05,
    "junction_snap_m": 0.3,
    "tags_passthrough": ["sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both", "lanes", "lanes:forward", "lanes:backward",
                         "lane_markings", "oneway", "surface", "maxspeed", "lit",
                         "parking:lane:left", "parking:lane:right", "parking:lane:both",
                         "gauge", "electrified", "service", "usage", "height", "material", "fence_type", "wall"],
    "road_profile_by_class": {
      "motorway": "road_trunk", "motorway_link": "road_trunk", "trunk": "road_trunk", "trunk_link": "road_trunk",
      "primary": "road_primary", "primary_link": "road_primary",
      "secondary": "road_secondary", "secondary_link": "road_secondary",
      "tertiary": "road_tertiary", "tertiary_link": "road_tertiary",
      "residential": "road_residential", "unclassified": "road_unclassified", "living_street": "road_living_street",
      "service": "road_service", "pedestrian": "road_pedestrian",
      "track": "path_track", "bridleway": "path_track", "cycleway": "path_cycleway",
      "footway": "path_footway", "path": "path_footway", "steps": "path_footway"
    },
    "path_classes": ["footway", "path", "steps", "cycleway", "bridleway", "track", "pedestrian"],
    "edge_profile_default": "edge_uk_kerb",
    "edge_rule": "edge renderer iff pav > 0 AND sidewalk tag != 'no'/'separate' AND cls not in path_classes; sides from sidewalk/sidewalk:left/right, default both",
    "markings_rule": "lane_markings=no -> profile_overrides.road.markings = []",
    "rail_profile_by_gauge_m": {"1.435": "rail_standard"},
    "rail_profile_fallback": "rail_standard",
    "barrier": {
      "edge_profile": "edge_barrier_only",
      "hedge_profile": "hedge_privet",
      "type_rules": [
        ["wall",           {"material": "brick"},     "brick_wall"],
        ["wall",           {"wall": "brick"},         "brick_wall"],
        ["wall",           {"material": "concrete"},  "concrete_wall"],
        ["wall",           {"wall": "concrete"},      "concrete_wall"],
        ["wall",           {"wall": "seawall"},       "concrete_wall"],
        ["wall",           {"material": "stone"},     "stone_wall"],
        ["wall",           {"wall": "stone_wall"},    "stone_wall"],
        ["wall",           {"wall": "dry_stone"},     "stone_wall"],
        ["wall",           {"wall": "flint"},         "stone_wall"],
        ["wall",           {},                        "brick_wall"],
        ["city_wall",      {},                        "stone_wall"],
        ["fence",          {"fence_type": "chain_link"}, "chain_link"],
        ["fence",          {"fence_type": "railing"}, "railing"],
        ["fence",          {"fence_type": "bars"},    "railing"],
        ["fence",          {"fence_type": "metal"},   "railing"],
        ["fence",          {"material": "metal"},     "railing"],
        ["fence",          {"fence_type": "wood"},    "wood_fence"],
        ["fence",          {"material": "wood"},      "wood_fence"],
        ["fence",          {},                        "wood_fence"],
        ["guard_rail",     {},                        "guard_rail"],
        ["handrail",       {},                        "railing"],
        ["retaining_wall", {},                        "retaining_wall"],
        ["kerb",           {},                        "kerb_only"],
        ["hedge",          {},                        "hedge"]
      ],
      "height_source": "step 11 record field h (metres, parsed or defaulted there, see h_src); default_height_m below applies only to a record without h",
      "default_height_m": {"brick_wall": 1.8, "concrete_wall": 1.8, "stone_wall": 1.5, "chain_link": 1.8, "guard_rail": 0.75,
                           "railing": 1.1, "wood_fence": 1.8, "retaining_wall": 1.5, "hedge": 1.5, "kerb_only": 0.125},
      "default_thickness_m": {"brick_wall": 0.23, "concrete_wall": 0.20, "stone_wall": 0.45, "chain_link": 0.05, "guard_rail": 0.10,
                              "railing": 0.05, "wood_fence": 0.05, "retaining_wall": 0.30, "hedge": 0.8},
      "note": "Opinions, not survey: only 15 of Margate's 467 barrier ways carry height=. First matching rule wins; the bare-class rules are the defaults. 'hedge' goes to the hedge renderer, everything else to the edge renderer as one barrier segment over the whole spline. A cls with no rule is skipped and counted (step 11 already drops gate/bollard/yes). Thickness is never in the pipeline output; it is this consumer's number."
    },
    "overlay_z": "nearest step-06 vertex of the same way; informative",
    "note": "footway/path/steps/cycleway/bridleway/track/pedestrian are Renderer-A flat ribbons with path_*/road_pedestrian profiles and NO edge renderer. All classes present in tuning.json roads.widths_m must appear in road_profile_by_class; the adapter refuses otherwise."
  },

  "massing": {"note": "rings to local metres; base_z/skirt unchanged (Z is up in this frame)."},
  "furniture": {"note": "x,y local; z kept (null = drape); bearing kept; heading_deg = 90 - bearing wrapped to (-180,180]. The loader's yaw_ue = bearing - 90 = -heading_deg is NOT written per record (BRIEF 4.2)."}
}
```

### A7. Frame conversion functions and the worked example (unit test)

```
survey_to_local(E, N, z, E0, N0)      = (E - E0, N - N0, z)
local_to_ue_cm(x, y, z)               = (100*x, -100*y, 100*z)          # loader-side; in the adapter for tests/docs only
bearing_to_heading_deg(b)             = ((90 - b + 180) % 360) - 180     # right-handed CCW from +X, (-180, 180]
bearing_to_ue_yaw(b)                  = (b - 90) % 360                   # loader-side; = (-heading) mod 360
```

Worked example (Thanet origin E0 = 627680, N0 = 163080):

| quantity | value |
|---|---|
| survey | E 635253.6, N 171027.6, z 17.2 (ODN m) |
| local (Streetscape JSON) | x = 635253.6 − 627680 = **7573.6**, y = 171027.6 − 163080 = **7947.6**, z = **17.2** |
| Unreal (cm) | X = 100·7573.6 = **757 360**, Y = −100·7947.6 = **−794 760**, Z = 100·17.2 = **1 720** |
| bearing 131.0° | heading_deg = 90 − 131 = **−41.0**; yaw_ue = 131 − 90 = **41.0** |
| test-stretch start (§B2) | survey (635779.98, 171251.12, 20.56) → local (8099.98, 8171.12, 20.56) → UE (809 998, −817 112, 2 056) |
| bearing 0° (north) | heading 90.0; yaw_ue 270.0 (= −90) |
| bearing 90° (east) | heading 0.0; yaw_ue 0.0 |

Consistency check of the two rotations: a unit vector at bearing b is (sin b, cos b) in (east, north) =
(x, y). In UE that point is (100 sin b, −100 cos b); UE yaw ψ measured from +X toward +Y gives
(cos ψ, sin ψ) ∝ (sin b, −cos b) ⇒ ψ = b − 90 ✓. In the right-handed frame the angle from +X toward +Y
is θ with (cos θ, sin θ) = (sin b, cos b) ⇒ θ = 90 − b ✓. All of these are asserted in
`test_unreal_adapter.py` (§A8) to 1e-9.

### A8. Tests — `sources/tests/test_unreal_adapter.py`

Standalone, numpy-only, run with `C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/test_unreal_adapter.py`;
exit code 1 on any failure; same `check(name, cond, detail)` reporter as `dryrun.py:43-46`. It inserts
`sources/tests/fake_osgeo` at the front of `sys.path` before importing anything from `sources/`
(`dryrun.py:31-34`), loads the adapter by path with
`importlib.util.spec_from_file_location("unreal_adapter", ".../adapters/unreal.py")` (the name `unreal`
is UE's own Python module name — never import the adapter as `unreal`), and then:

**Pure functions (no site):**
1. `encode_h16`/`decode_h16` on 10 000 random values in [−255, 255]: `max|decode(encode(z)) − z| ≤ 1/256`
   m (0.390625 cm), dtype `<u2`, and `encode(0.0) == 32768`, `encode(-0.6) == 32691`, `encode(255.0) == 65408`.
2. `check_range([-255.0, 255.0], ...)` passes; `[-256.1, 10]` and `[0, 255.5]` raise `SystemExit` whose
   message contains "does not fit".
3. Frames: the table in §A7, all rows, to 1e-9; `bearing_to_heading_deg(359.9) == 90.1 - 360 + ...` wraps
   into (−180, 180].
4. `douglas_peucker`: a 200-point straight line → `[0, 199]`; a 20 m sagitta arc sampled at 2 m with
   tol 0.05 keeps ≥ 6 and ≤ 40 points; every original point lies within tol of the thinned polyline;
   `keep=(57,)` forces index 57.
5. `chain_segments`: three shuffled runs of one way (seam vertices duplicated) come back in way order;
   an unclosable set raises `SystemExit`.
6. `parse_height_m`: "1.2" → 1.2, "2" → 2.0, "2 m" → 2.0, "1.2m" → 1.2, "tall" → None.
7. `classify_barrier` against the `unreal.json` rules: `("wall", {"h": None})` → brick_wall 1.8
   (adapter default, flagged); `("fence", {"fence_type": "chain_link", "h": 2.0})` → chain_link 2.0;
   `("hedge", {"h": 1.5})` → hedge; `("cattle_grid", {})` → None.

**Synthetic site `_ut_unreal` (fake GDAL, temp dir):** written by the test the way `dryrun.synth`
does (`dryrun.py:56-121`): site config `sources/config/sites/_ut_unreal.json` (removed in `finally`,
`dryrun.py:401-404`) with `origin {E: 500000, N: 150000}, tile_m 64, grid_res 65, nx 2, ny 1,
water_level -1.0`, and a `clip` block `{"type":"halfplane","line":[[500118,149000],[500118,151000]],"keep":"left"}`;
`lib.ROOT` pointed at a `tempfile.mkdtemp`. Fixtures written directly (no pipeline step runs):
- `out/terrain/dtm_x0_y0.tif`, `dtm_x1_y0.tif` via the fake GTiff driver: `z = 10 + 0.05·(N−N0) +
  0.01·(E−E0)` (north higher); tile (1,0) has its 10 easternmost columns set to nodata −9999 with the
  band's `SetNoDataValue(-9999)`; `terrain_manifest.json` hand-written with `clip`, per-tile
  `clipped_cells` (0 and 650), `range_m`, `slope_qa`, `tiles_missing: []`.
- `out/networks/roads_x0_y0.jsonl` + `roads_x1_y0.jsonl`: way `w1` (residential, w 6.0, pav 1.5,
  lanes → 7.0 would be 06's job; here w is given) crossing the seam at E0+64 with the seam vertex in
  both files; way `f1` footway; way `s1` service with `sidewalk=no`; one `_junction` at w1's start;
  `networks_manifest.json`. `rail_x0_y0.jsonl`: one record `{"cls":"rail","gauge":1.435,
  "gauge_src":"osm","tracks":2,"electrified":"rail",...}`. `barriers_x0_y0.jsonl`: one `wall` with
  `"h":1.5,"h_src":"osm","wall":"brick"`, one `hedge` with `"h":1.5,"h_src":"default"`, one record with
  the unknown `cls "cattle_grid"` (must be skipped and counted); plus `linear_manifest.json`.
- `out/coast/ground_x0_y0.tif` 32×32 four bands summing to 255 (grass 200 / sand 55 in the north
  half, water 255 in the south two rows) and `coast_manifest.json` with `class_res 32`.
- `out/massing/buildings_x0_y0.jsonl` one record; `out/furniture/furniture_x0_y0.jsonl` one record
  with `bearing 131.0`.
- `derived/_ut_unreal.gpkg` registered in `osgeo.VECTORS` with a `lines` layer whose fields are
  `["osm_id","highway","railway","barrier","name","other_tags"]` and whose raw geometries are the
  un-densified 3–4 vertex versions of the ways (filters `"highway IS NOT NULL"`, `"railway IS NOT
  NULL"`, `"barrier IS NOT NULL"` are all shapes `fake_osgeo._match` understands,
  `fake_osgeo/osgeo/__init__.py:180-192`).
- A temp `profiles_dir` with one minimal file per profile id named in §A4.2 (`{"id": ..., "kind": ...}`),
  and `adp["streetscape"]["profiles_dir"]` pointed at it (absolute paths are accepted).

Then `main()` runs and the test asserts:
8. `landscape/hm_x0_y0.r16` read back with `np.fromfile(..., "<u2").reshape(65, 65)`:
   `decode(raw)` equals the fake tile to ≤ 1/256 m everywhere; **row 0 decodes to the tile's northern
   (largest-z) row**; column 64 of tile (0,0) equals column 0 of tile (1,0) bit-for-bit.
9. `clip_x1_y0.r8`: 255 on the 55 western columns, 0 on the 10 eastern; `count(0) == 650 ==
   manifest.tiles[1].clipped_cells`; `clip_x0_y0.r8` all 255; heightmap values under the clipped
   columns are finite and equal the nearest kept column (nearest fill).
10. `weight_*_x0_y0.r8` exist for all four bands, shape 32×32, row 0 == coast raster row 0 (no flip),
    per-cell sum == 255.
11. `landscape_manifest.json` has every key listed in §A3.5 (`frame, heightmap.z_encoding.{formula,
    per_unit, offset, scale_z_cm}, clip_mask, weightmaps, range_m, water_level, pad_value_h16 ==
    encode(-1.0) == 32640, ue_import, clip, slope_qa, tiles_missing, tiles[*].{x,y,files,min_m,max_m,
    clipped_cells,quad_origin}`) and `clip` equals the terrain manifest's.
12. Streetscape: `site_x0_y0.json` + `site_x1_y0.json` exist; total spline count == number of
    non-junction road records (4: w1×2, f1, s1) + rail (1) + barrier records that are not skipped (2);
    the `cattle_grid` is counted in `streetscape_manifest.skipped_barriers`.
13. Local coords: the first point of `road:w1:0` == survey − origin to 0.01; `points[*].width_m == 6.0`
    on every point; `profile_ids == {road: road_residential, edge: edge_uk_kerb, hedge: null}`;
    `s1` (sidewalk=no) has `edge: null`; `f1` has `road: path_footway, edge: null`.
14. Seam: `road:w1:0.continues_to == "road:w1:1"`, `road:w1:1.continues_from == "road:w1:0"`,
    `continuation_kind.to == "seam"`, `overrun_points.after` of `w1:0` equals the second point of
    `w1:1`, and the last point of `w1:0` equals the first point of `w1:1` (seam vertex duplicated).
15. Every id in every `profile_ids` and `profile_ids_used` exists in `profiles.json`; barrier spline
    has `segments.barriers[0] == {s0: 0, s1: L±0.01, type: "brick_wall", height_m: 1.5, ...}`; hedge
    spline has `profile_ids.hedge == "hedge_privet"` and `segments.hedge[0].s1 == L`.
16. `overlay_points` of `road:w1:0` == the fake gpkg's raw vertices − origin, with z from the nearest
    06 vertex; `junctions[0].incident` names `road:w1:0` with `end: "start"`.
17. Thinning: `points_out < points_in` in the manifest for w1 (its 06 polyline is given 40 collinear
    points → 2 kept), and a curved fixture way keeps ≥ 4.
18. Massing: `rings[0].pts[0][0] == E − E0`, `base_z` present, `base_y` absent. Furniture:
    `x == e − E0`, `bearing == 131.0`, `heading_deg == -41.0`, no `yaw` key.
19. Refusals (each in `try/except SystemExit`, message checked): (a) `terrain_manifest.range_m =
    [-300, 10]` → "does not fit"; (b) a 64×65 tile → "expected (65, 65)"; (c)
    `road_profile_by_class.residential = "road_bogus"` → "profile id 'road_bogus' not found";
    (d) config has `clip`, terrain manifest lacks it → "stale"; (e) `tiles[1].clipped_cells = 1` (mask
    says 650) → "disagree".

**Hook into `dryrun.py` (requested from the pipeline task, which owns the file, BRIEF §7):** add
`"adapters/unreal.py"` to `STEPS` after `"adapters/unity.py"` (`dryrun.py:52-53`) so both synthetic
sites run through it (needs the lines layer to gain `railway`/`barrier` fields, `dryrun.py:96`, and
`profiles_dir` to resolve — the schema task's `projects/one/schema/profiles/` will exist by then), and a
check block after the Unity checks (`dryrun.py:282-311`): heightmap decodes to the neutral tile within
1/256 m and row 0 is north; clip mask all 255 for sites A/B (no clip) and the manifest's `clip` is
null; spline count == road segment count; `w1a`'s `continues_to` is `road:w1b:0`-style (`"way"` join at
`J`, since 3 ways meet there it is actually a junction — assert `null` and that `junctions[0].incident`
has 3 entries); the pipeline task's new **clip site C** asserts `clipped_cells` == mask zeros and that
the clip block is copied. The standalone test remains the authoritative unit test because it can run
before the pipeline changes land.

### A9. Refusals (all `sys.exit(message)`, message names the fix)

| condition | message (abridged) |
|---|---|
| a source manifest or directory is missing | `unreal adapter: <what> missing at <path>; run the pipeline first` (as `unity.py:37-40`) |
| `terrain_manifest.range_m` outside `landscape.range_limit_m` | `site elevation a..b m does not fit the r16 window -255..255 m at Z scale 100 -- encoding as-is would clamp real ground` |
| tile array shape ≠ `(res, res)` | `dtm_x{i}_y{j}.tif is (h, w), expected (res, res); grid_res and the tile disagree` |
| site config has `clip` and terrain manifest has none, or `clip.line` differs | `config has a clip block the terrain manifest does not (or a different line) -- stale output, re-run step 05` |
| nodata count ≠ `tile.clipped_cells` (or ≠ 0 with no clip) | `dtm_x{i}_y{j}: n nodata cells but the manifest says m clipped_cells -- tile and manifest disagree` |
| a profile id produced by the class/barrier map is absent from `profiles_dir` | `profile id '<id>' not found in <dir> (referenced by <rule>)` |
| a class in `tuning.json roads.widths_m` has no entry in `road_profile_by_class` | `class '<cls>' has no Unreal profile mapping -- add it to sources/adapters/unreal.json` |
| `profiles_dir` missing, or two files share an id | `profiles dir <path> missing` / `duplicate profile id` |
| coast raster shape ≠ `(class_res, class_res)`, or a cell's four bands sum to neither 0 nor 255 | `ground_x{i}_y{j}.tif is (h, w), expected class_res` / `bands sum to n at (r, c); expected 255 (or 0 under the clip)` |
| `rail_*`/`barriers_*` files exist but `networks/linear_manifest.json` does not | `linear manifest missing; step 11 output is partial` |
| a way's tile runs cannot be chained | `way <id>: n runs cannot be ordered into one chain -- networks output edited?` |
| GeoPackage missing | `<site>.gpkg missing (overlay + tags need step 01's output)` |

Warnings (printed, counted in the manifest, never fatal): rail/barrier files absent ("step 11 not
run"), unmapped rail gauge, skipped barrier classes, `fill` = `median (degraded)` on any tile
(propagated from the terrain manifest with the same wording as `05_export_terrain.py:96-98`).

### A10. Schema fields this design needs (for the geometry/schema designer)

Names already in the schema and used as given: `schema_version, site, crs, origin{E,N}, vertical_datum,
frame, profiles{road,edge,hedge}, splines[]{id, source{layer,osm_id,name,cls}, profile_ids{road,edge,hedge},
points[]{x,y,z,width_m,roll_deg,tags[]}, sampling{height_source}, segments{}, overlay_points[]}`.

Additions requested (all optional in the schema, all emitted by the adapter):

| field | why |
|---|---|
| header `tile{x,y,tile_m,bounds_local}`, `profiles_file`, `profile_ids_used` | per-tile documents (§A4.1) |
| `source.segment_index`, `source.segment_count`, `source.tile`, `source.tags{}` | seam bookkeeping; OSM tags for renderers/QA (§A4.3) |
| `profile_overrides{road{markings}, edge{pavement_width_m, sides, kerb_width_m, barrier_offset_m}}` | per-spline scalars that are not segment lists (pavement width from `pav`, sidewalk sides, barrier splines) |
| `flags{bridge,tunnel,z_gap,steps,gauge_unmapped}` | pipeline flags passed through |
| `continues_from`, `continues_to`, `continuation_kind{from,to}`, `overrun_points{before,after}` | seams and way joins (§A4.4) |
| `sampling.z_note`, `sampling.terrain_hint{tile,heightfield}` | which heightfield tile to open (§6 Q3) |
| `junctions[]{id,x,y,z,r_m,incident[]{spline,end}}` | §6 Q7 placeholder |
| `segments.barriers[].{type,height_m,thickness_m,material}` with `type ∈ {brick_wall, concrete_wall, stone_wall, chain_link, railing, guard_rail, wood_fence, retaining_wall, kerb_only}` and `segments.hedge[].{s0,s1,height_m,width_m}` | barrier/hedge layer (§A4.3) |
| `flags.disused`, `flags.tracks` (rail) | step 11 passes `cls=disused` and `tracks` through; the rail profile may want them |
| markings: `anchor ∈ {centre, edge_left, edge_right}` + `inset_m` | a yellow line must follow the *edge* across a width change (§B4) |
| drop kerb: `side`, `length_m` (flat lowered run) in addition to `s, ramp_m, target_height_m` | a driveway is a flat run with two ramps, not a V (§B4) |
| edge segments per side: `side ∈ {left,right,both}` on `kerb_segments[]` (kind: `uk_kerb | half_grass`) | half-grass on one side only (§B4) |

### A11. Contracts assumed from other subsystems

- **Pipeline task (05 clip)** — as designed in `projects/one/docs/design/pipeline.md` §3.3, which this
  adapter follows exactly: clipped cells are written as `-9999.0` **after** genuine gaps were filled,
  the band's `SetNoDataValue(-9999.0)` is called on every tile of a clipped site (and never on a
  clipless one, so Margate stays byte-identical), and `terrain_manifest.json` gains `nodata`, `clip`
  (`lib.clip_manifest`), `tiles_clipped` (positions wholly outside: no file), `clipped_cells_total`,
  and per tile `clip_state` (`inside`/`straddle`) + `clipped_cells`, all only when a clip exists;
  `min_m`/`max_m`/`range_m` and the slope QA are computed on kept cells. The adapter reads nodata
  through `lib.nodata_mask(a, band.GetNoDataValue())`, so the sentinel's value is irrelevant to it,
  and copies `tiles_clipped`/`clipped_cells_total`/`nodata` (as `source_nodata`) into
  `landscape_manifest.json`.
- **Pipeline task (step 11)** — record schemas of `pipeline.md` §4.2, taken as given:
  `networks/rail_x{i}_y{j}.jsonl` `{"id","cls","gauge" (m),"gauge_src","tracks","electrified","service",
  "usage","bridge","tunnel","name","z_gap","pts"}`; `networks/barriers_x{i}_y{j}.jsonl` `{"id","cls","h" (m),
  "h_src","material","fence_type","wall","name","z_gap","pts"}`; both split per tile with the seam vertex
  duplicated (`lib.drape_runs`), barriers with Chaikin 0; manifest `networks/linear_manifest.json`
  (the adapter `need()`s it whenever a `rail_*`/`barriers_*` file exists, and prints "step 11 not run"
  when neither exists). Barrier classes emitted there: `wall, fence, hedge, retaining_wall, kerb,
  guard_rail, handrail, city_wall` — all mapped in §A6.
- **Pipeline task (09 clip):** ground-raster cells outside the clip are all-zero (`pipeline.md` §3.6);
  the adapter accepts per-cell sums of 0 or 255 only.
- **Pipeline task (shared files):** `dryrun.py` hook (§A8); `run.sh` end-of-run hint; `OUTPUT.md`
  "Writing an adapter" gains one sentence naming `unreal.py` as the Streetscape-frame adapter.
- **Schema task:** `projects/one/schema/profiles/*.json` with the ids of §A4.2 and `kind`; the additions
  of §A10 in `streetscape.schema.json`; `schema_version "1.0.0"`.
- **Landscape importer (UE_PLAN):** consumes `landscape_manifest.json` as specified in §A3.5-3.6
  (actor location/scale, tile → quad mapping, `visibility = 255 − clip`, weight resample 256 → 513,
  padding at `pad_value_h16` hidden).
- **Blender prototype / UE loader:** apply `(100, −100, 100)` and `yaw = bearing − 90` themselves;
  treat `points[*].z` as informative and sample the heightfield.

---

## Part B — the test stretch

### B1. Method and candidates

Read-only survey of `data/margate/out/networks/roads_*.jsonl` (5 001 segments) joined per OSM way, with
tags and raw geometry from `data/margate/derived/margate.gpkg` (`lines` layer, `other_tags`) and heights
from `data/margate/interim/dtm.vrt`, using the env python with the GDAL environment. Filters, in order:
`cls ∈ {residential, tertiary}` (1 064 ways); not `bridge`/`tunnel`; no segment with `z_gap`; a
`sidewalk*` tag present (670 ways); northing of every vertex ≥ 170 300; then either a single way of
150–400 m with 1–5 m of elevation change and ≥ 3 m chord deviation (24 ways), or two ways sharing an
endpoint that no third way touches, with different `w` (a real width change: 06 widens `w` from `lanes`,
`06_build_networks.py:122-127`), total 150–450 m (13 pairs). Ranked on curvature.

| | A — **Trinity Square** (chosen) | B — Madeira Road | C — Athelstan Road + Clifton Gardens |
|---|---|---|---|
| OSM ways | 30253079 (w 6.0) + 879045149 (w 7.0, `lanes=2`) | 30278344 (w 6.0) + 879043328 (w 7.0, `lanes=2`) | 25501701 (w 7.0, `lanes=2`, `lane_markings=yes`) + 30299585 (w 6.0, `oneway`) |
| class | residential / residential | residential / residential | residential / residential |
| length | 145.2 + 26.2 = **171.4 m** | 246.9 + 10.5 = 257.4 m | 258.0 + 119.3 = 377.3 m |
| width change at s | **145.2 m** (26 m of 7.0 m remain) | 246.9 m (only 10.5 m remain) | 258.0 m |
| elevation | 20.56 → 18.09 m, **Δ 2.47 m, −1.44 %** | 28.74 → 21.81, Δ 6.9 m, −2.7 % | 18.05 → 21.46 (min 18.02, max 23.72), Δ 5.7 m |
| curve | bearing 257° → 285°, **chord deviation 8.5 m** | 223° → 300°, deviation 46.5 m | 182° → 197°, deviation 1.2 m (straight) |
| sidewalk | both / both | both / both | both / both |
| northing | 171 236–171 251 (≈ 200 m from the Fort Hill sea front) | 170 829–170 887 | 170 970–171 338 |
| tiles | Margate (5,5) = Thanet (15,15), one tile | Margate (6,5) | Margate (6,5) + (6,6): crosses a seam |
| bridge/tunnel/z_gap | none | none | none |
| verdict | meets every criterion | Δz > 5 m; width change too close to the end | dead straight (fails the curve criterion); Δz > 5 m; good **second** stretch later for the seam test and its real `lanes:forward/backward` centre line |

A fourth pair, Lonsdale Avenue 933912286 + 933912290 (293 m, 6 → 7 m at s 110, Δz 6.8 m), is dead
straight (deviation 0.0 m) and was dropped.

### B2. The chosen stretch: Trinity Square, Margate

- **Ways** (OSM direction east → west, which the adapter and the JSON keep):
  `30253079` "Trinity Square", `highway=residential`, `w 6.0, pav 1.5`; tags
  `lane_markings=no, lit=yes, maxspeed=30 mph, sidewalk=both, surface=asphalt`; 9 raw OSM vertices; 96
  draped vertices; 145.2 m. Then `879045149` "Trinity Square", `residential`, `w 7.0` (06: `lanes=2` →
  max(6.0, 2·3.0 + 1.0) = 7.0, `tuning.json lane_width_m 3.0, lane_margin_m 1.0`), `pav 1.5`; tags
  `lanes=2, lit=yes, maxspeed=30 mph, sidewalk=both, surface=asphalt`; 3 raw vertices; 20 draped
  vertices; 26.2 m. The two ways share the node at E 635636.65 N 171238.93 and nothing else touches
  it (no `_junction`), so the adapter emits `continues_to/from` with `continuation_kind "way"`.
- **Extent:** start E 635779.98 N 171251.12 z 20.56 (the east end, where footways 462130116 and
  488880069 meet; 06 places a `_junction` disc r 3.4 m at (635780.0, 171251.1, 20.57)); end
  E 635610.69 N 171242.25 z 18.09 (west). Total **171.39 m**, 115 draped vertices (join vertex once).
  Bearing 257.1° at the start, 284.7° at the end; raw OSM segment bearings 257.4, 252.7, 259.0, 266.8,
  265.1, 274.4, 274.6, 274.5, 276.4, 284.1° — a gentle right-hand (northward) curve concentrated in the
  first 100 m, chord deviation 8.5 m.
- **Local frame** (Thanet origin): start (8099.98, 8171.12, 20.56), join (7956.65, 8158.93, 18.52), end
  (7930.69, 8162.25, 18.09). Margate-origin local = these − 5120 in x and y. UE start
  (809 998, −817 112, 2 056) cm. Thanet tile **(15, 15)** = Margate tile (5, 5) (BRIEF §4.1: Margate
  (i, j) = Thanet (i+10, j+10)).
- **Sides** (left = south = the square, right = north): within 30 m the right side has 22 buildings —
  houses 5–11 m from the centreline, a 15.6 m `terrace` (1360057151) at s 5, garages 1360057148/9 at
  s 37.9/42.8 (8 m off: a driveway), a run of houses 1360057147…1360057134 from s 47 to 99, and OSM
  `barrier=wall` 1360057150 running N–S 5–19 m off the right side at s 27–30. The left side has 8, all
  set back: `retail` 280074642 at s 29 (15.6 m), `apartments` 280066408 at s 75 (17 m),
  `residential` 671150239/488883524/671150240 at s 107–117 (8.5–9.5 m), `hospital` 548976580 at
  s 156 (22 m). Side roads touching interior vertices (not `_junction`s, §A4.6): Trinity Square leg
  30253078 at s 23.6, footway 30253092 at s 40.3, Trinity Walk (service) 462130119 at s 95.9, service
  903253039 at s 134.0.
- **Half-grass plausibility:** the left/south side between the east junction and Trinity Walk faces
  the open square (nearest buildings 15–17 m), which is where a grass verge kerb reads naturally;
  200 m north is the cliff-top sea front at Fort Hill / Fort Crescent.

### B3. Terrain along the stretch

DTM sampled at 1 m of arc length along the 06 polyline with 06's exact bilinear convention
(`ground()`: `fx = (e − gt[0])/gt[1] − 0.5`, `06_build_networks.py:54-69`) from
`data/margate/interim/dtm.vrt` (geotransform origin 632799.5 / 171784.5, 1 m pixels): 172 samples, no
nodata. 15-sample (15 m) centred moving average:

| s (m) | z DTM (m) | z MA15 (m) | | s (m) | z DTM | z MA15 |
|---|---|---|---|---|---|---|
| 0 | 20.56 | — | | 90 | 19.59 | 19.57 |
| 10 | 20.46 | 20.47 | | 100 | 19.36 | 19.35 |
| 20 | 20.40 | 20.44 | | 110 | 19.17 | 19.17 |
| 30 | 20.48 | 20.48 | | 120 | 18.98 | 18.97 |
| 40 | 20.43 | 20.44 | | 130 | 18.81 | 18.79 |
| 50 | 20.36 | 20.35 | | 140 | 18.61 | 18.61 |
| 60 | 20.19 | 20.18 | | 150 | 18.40 | 18.43 |
| 70 | 19.98 | 19.97 | | 160 | 18.23 | 18.24 |
| 80 | 19.78 | 19.78 | | 171 | 18.08 | — |

Noise: residual after the 15 m moving average **RMS 1.5 cm, max 4.7 cm**; 1 m step-to-step
differences RMS 2.1 cm, max 6.6 cm. The profile is a flat 40 m crown (20.4–20.6 m) followed by a
steady −1.9 % fall — smoothing changes individual heights by ≤ 5 cm, which is visible in a close-up
of the kerb line and invisible from ten metres, exactly the regime the spec's "do not follow raw LIDAR
point-for-point" is about. Full 1 m table and the MA15 series are in the JSON block (§B6).

### B4. Authoring plan (arc-length s in metres from the east end; L = 171.4)

| feature | side | s-range / value | note |
|---|---|---|---|
| carriageway width | — | 6.0 m for s ∈ [0, 140.2]; linear taper **6.0 → 7.0** over **[140.2, 150.2]**; 7.0 m for [150.2, 171.4] | centred on the OSM join at 145.2; waypoints at 140.2 (6.0) and 150.2 (7.0) carry `width_m`; the kerb on both sides re-samples the edge offset 3.0 → 3.5 m; road overhang ≥ 3 cm over the kerb throughout |
| centre dashes | — | whole length [0, 171.4]; offset 0, width 0.10 m, dash 4.0 m, gap 2.0 m, white | authored despite `lane_markings=no` — the deliverable must show it; the adapter's own output for this way has `markings: []` |
| double yellows | **left** (south) | [0, 60] | anchored to `edge_left`, inset 0.25 m from the carriageway edge, two 0.075 m lines 0.075 m apart, yellow; covers the junction approach and the bend |
| drop kerb | **right** (north) | centre **s 40.3**, flat lowered run 3.0 m [38.8, 41.8], ramps 0.9 m each side ([37.9, 38.8] and [41.8, 42.7]), target height 0 | the garages at s 37.9–42.8; the pavement extrusion ramps with the kerb and both split materials carry down |
| half-grass / half-tarmac kerb | **left** | [0, 95.9] | grass outer face, tarmac inner, flush top (no step); standard UK kerb on the left for [95.9, 171.4] and on the right for the whole length; 95.9 is the Trinity Walk junction |
| barrier segments | **right**, at the back of the pavement (w/2 + pav = 4.5 m; 5.0 m after the taper) | **brick_wall** [0, 45] h 1.2 t 0.23; **chain_link** [45, 95] h 1.2 t 0.05; **railing** [95, 140] h 1.0 t 0.05; none beyond 140 | one segment list on the edge profile switching type at 45 and 95; nothing across the taper so the width change is unobstructed in the screenshot |
| hedge | **right**, 0.4 m behind the barrier line | [55, 90], height 1.5 m, width 0.8 m, privet | a privet behind the chain-link run; Renderer C reads the same segment list |
| heights | — | `height_source = terrain`, 15 m moving average, sampled at the tessellated points | banking from the local cross-slope, as the spec requires |
| overlay | — | the 11 raw OSM vertices (§B6 `raw_osm_local_xy`) lifted 0.5 m | debug lines |

The "far side" is the right/north side: the natural viewpoint for the first-deliverable screenshot is
from the square (south) looking north across the road at the terrace, so the drop kerb, the
brick → chain-link → railing switch and the hedge are all in view behind the centre dashes, with the
half-grass kerb and double yellows in the foreground.

### B5. Railway

The Margate extract contains **no railway ways**: `margate.gpkg` `lines` with `railway IS NOT NULL`
returns 0 features (the column exists and is empty), and the raw `data/margate/raw/margate.osm`
contains a single `k="railway"` tag and no `v="station"` — the Overpass query in `fetch_osm.sh` asks
for highways, buildings, barriers, natural and amenities but not `railway` (BRIEF §3). The Thanet
query must add `way["railway"]` (BRIEF §4.1) — recommended concretely:
`way["railway"~"^(rail|light_rail|narrow_gauge|disused|abandoned|platform)$"]` plus
`node["railway"="station"]` so the stations come too, and optionally `relation["route"="railway"]["name"~"Chatham Main Line"]`.

Nearest alignment to the test stretch and the route to fetch — **from memory of OSM, unverified
(no network fetch was permitted in this phase; positions ±200 m, way ids not quoted because they cannot
be verified offline):** the **Chatham Main Line** (Faversham–Ramsgate section) enters the Thanet grid
from the west near **Birchington-on-Sea** station (≈ E 629 670, N 169 415; Thanet tile (3, 12)), runs
east along the north coast through **Westgate-on-Sea** (≈ E 632 360, N 169 980; (9, 13)) and
**Margate** (≈ E 634 960, N 170 570; (14, 14) — about 1.06 km WSW of the test stretch, which makes it the
nearest railway alignment), then turns south-east inland to **Broadstairs** (≈ E 639 060, N 168 000;
(22, 9)), **Dumpton Park** (≈ E 638 360, N 166 480; (20, 6)) and **Ramsgate** (≈ E 637 330, N 165 640;
(18, 5)). From Ramsgate the line continues west toward Minster (the Kent Coast line via Sandwich) and
crosses the clip line near Cliffsend — the only railway crossing of the cut, where the clip-aware
step 11 will truncate it. The abandoned Margate–Ramsgate Harbour line (closed 1926, Ramsgate Tunnel)
is `railway=abandoned` in OSM if mapped and would be fetched by the pattern above; keep or drop by
`cls`. All six station positions convert to the kept side of the clip half-plane (checked with the
config's `(P−A)·(6071, 6984) ≥ 0` rule); they are to be replaced by the fetched OSM node positions in
`qa_*` of the first Thanet run.

### B6. Data block for `projects/one/schema/examples/test_stretch.json`

Everything below is in the Streetscape frame with the **Thanet** origin (E 627680, N 163080); the
synthesis agent authors the final example file from it. `polyline_06_*` are all 115 step-06 vertices
(survey E/N/z and local x/y/z); `waypoints_local_dp5cm_plus_taper` are the 13 Douglas-Peucker (5 cm)
waypoints plus the two inserted taper waypoints at s 140.2 and 150.2, each with `width_m` — this is
the `points[]` list the example file should use; `raw_osm_*` are the 11 raw OSM vertices (overlay);
`dtm_1m_s_z` are the 172 DTM samples, `dtm_ma15_s_z` the 15 m moving average where defined.

```json
{
 "_about": "Data for projects/one/schema/examples/test_stretch.json. Frame: Streetscape JSON (local metres from the THANET origin E 627680 N 163080; X east, Y north, Z = ODN metres). Margate-origin local = these minus 5120 in x and y. UE = (100x, -100y, 100z) cm.",
 "site": "thanet",
 "crs": "EPSG:27700",
 "origin": {
  "E": 627680,
  "N": 163080
 },
 "vertical_datum": "ODN",
 "tile": {
  "thanet": [15, 15],
  "margate": [5, 5]
 },
 "source": {
  "layer": "road",
  "osm_ids": ["30253079", "879045149"],
  "name": "Trinity Square",
  "cls": "residential",
  "w_m": {
   "30253079": 6.0,
   "879045149": 7.0
  },
  "pav_m": {
   "30253079": 1.5,
   "879045149": 1.5
  },
  "osm_tags": {
   "30253079": "\"lane_markings\"=>\"no\",\"lit\"=>\"yes\",\"maxspeed\"=>\"30 mph\",\"sidewalk\"=>\"both\",\"surface\"=>\"asphalt\"",
   "879045149": "\"lanes\"=>\"2\",\"lit\"=>\"yes\",\"maxspeed\"=>\"30 mph\",\"sidewalk\"=>\"both\",\"surface\"=>\"asphalt\""
  },
  "direction": "east -> west (OSM way direction of 30253079, then 879045149); left = south (square side), right = north (terrace side)"
 },
 "length_m": 171.39,
 "osm_join_s": 145.2,
 "z_start": 20.56,
 "z_end": 18.09,
 "grade_pct": -1.44,
 "bearing_start_deg": 257.1,
 "bearing_end_deg": 284.7,
 "polyline_06_survey_ENz": [
  [635779.98, 171251.12, 20.56],
  [635779.5, 171251.01, 20.56],
  [635778.52, 171250.8, 20.57],
  [635777.06, 171250.47, 20.55],
  [635775.1, 171250.03, 20.54],
  [635773.15, 171249.6, 20.48],
  [635771.2, 171249.16, 20.46],
  [635769.25, 171248.73, 20.46],
  [635767.3, 171248.29, 20.43],
  [635765.37, 171247.86, 20.4],
  [635763.46, 171247.44, 20.41],
  [635761.58, 171247.02, 20.4],
  [635759.72, 171246.6, 20.41],
  [635757.85, 171246.14, 20.45],
  [635755.97, 171245.64, 20.49],
  [635754.07, 171245.09, 20.48],
  [635752.16, 171244.5, 20.49],
  [635750.25, 171243.9, 20.48],
  [635748.34, 171243.31, 20.47],
  [635746.43, 171242.72, 20.49],
  [635744.52, 171242.12, 20.45],
  [635743.04, 171241.66, 20.45],
  [635742.0, 171241.34, 20.42],
  [635741.4, 171241.15, 20.43],
  [635741.22, 171241.1, 20.44],
  [635740.6, 171240.96, 20.44],
  [635739.54, 171240.74, 20.43],
  [635738.02, 171240.44, 20.41],
  [635736.06, 171240.06, 20.4],
  [635734.09, 171239.68, 20.38],
  [635732.13, 171239.3, 20.35],
  [635730.17, 171238.91, 20.35],
  [635728.21, 171238.53, 20.33],
  [635726.68, 171238.23, 20.28],
  [635725.58, 171238.02, 20.28],
  [635724.92, 171237.89, 20.27],
  [635724.69, 171237.84, 20.26],
  [635724.02, 171237.78, 20.24],
  [635722.9, 171237.71, 20.22],
  [635721.35, 171237.61, 20.19],
  [635719.35, 171237.5, 20.12],
  [635717.36, 171237.39, 20.07],
  [635715.36, 171237.28, 20.04],
  [635713.36, 171237.17, 20.0],
  [635711.36, 171237.06, 19.98],
  [635709.7, 171236.97, 19.95],
  [635708.37, 171236.89, 19.92],
  [635707.37, 171236.84, 19.9],
  [635706.7, 171236.8, 19.88],
  [635705.7, 171236.73, 19.85],
  [635704.37, 171236.63, 19.84],
  [635702.71, 171236.49, 19.81],
  [635700.72, 171236.32, 19.76],
  [635698.72, 171236.15, 19.73],
  [635696.73, 171235.98, 19.7],
  [635694.74, 171235.81, 19.65],
  [635692.75, 171235.64, 19.6],
  [635691.0, 171235.49, 19.56],
  [635689.51, 171235.37, 19.52],
  [635688.28, 171235.26, 19.49],
  [635687.29, 171235.18, 19.46],
  [635686.05, 171235.15, 19.41],
  [635684.56, 171235.18, 19.38],
  [635682.82, 171235.28, 19.37],
  [635680.82, 171235.43, 19.34],
  [635678.83, 171235.59, 19.3],
  [635676.83, 171235.74, 19.26],
  [635674.84, 171235.89, 19.22],
  [635672.85, 171236.05, 19.19],
  [635671.31, 171236.17, 19.17],
  [635670.23, 171236.25, 19.15],
  [635669.61, 171236.3, 19.14],
  [635669.44, 171236.31, 19.13],
  [635668.82, 171236.36, 19.12],
  [635667.74, 171236.45, 19.09],
  [635666.2, 171236.57, 19.06],
  [635664.21, 171236.73, 19.03],
  [635662.22, 171236.89, 18.98],
  [635660.22, 171237.05, 18.94],
  [635658.23, 171237.21, 18.9],
  [635656.23, 171237.37, 18.86],
  [635654.4, 171237.51, 18.84],
  [635652.73, 171237.65, 18.81],
  [635651.22, 171237.77, 18.81],
  [635649.87, 171237.88, 18.8],
  [635648.36, 171238.0, 18.76],
  [635646.68, 171238.13, 18.66],
  [635644.85, 171238.28, 18.65],
  [635642.86, 171238.44, 18.62],
  [635641.16, 171238.57, 18.6],
  [635639.76, 171238.68, 18.57],
  [635638.66, 171238.77, 18.55],
  [635637.86, 171238.83, 18.54],
  [635637.26, 171238.88, 18.53],
  [635636.86, 171238.91, 18.52],
  [635636.65, 171238.93, 18.52],
  [635636.16, 171238.98, 18.51],
  [635635.16, 171239.09, 18.49],
  [635633.67, 171239.26, 18.45],
  [635631.69, 171239.48, 18.4],
  [635629.7, 171239.7, 18.41],
  [635627.71, 171239.93, 18.36],
  [635625.72, 171240.15, 18.32],
  [635623.74, 171240.37, 18.27],
  [635621.8, 171240.59, 18.23],
  [635619.92, 171240.8, 18.2],
  [635618.1, 171241.0, 18.16],
  [635616.32, 171241.2, 18.11],
  [635614.81, 171241.4, 18.08],
  [635613.55, 171241.59, 18.07],
  [635612.55, 171241.78, 18.06],
  [635611.81, 171241.97, 18.07],
  [635611.25, 171242.11, 18.08],
  [635610.88, 171242.2, 18.09],
  [635610.69, 171242.25, 18.09]
 ],
 "polyline_06_local_xyz": [
  [8099.98, 8171.12, 20.56],
  [8099.5, 8171.01, 20.56],
  [8098.52, 8170.8, 20.57],
  [8097.06, 8170.47, 20.55],
  [8095.1, 8170.03, 20.54],
  [8093.15, 8169.6, 20.48],
  [8091.2, 8169.16, 20.46],
  [8089.25, 8168.73, 20.46],
  [8087.3, 8168.29, 20.43],
  [8085.37, 8167.86, 20.4],
  [8083.46, 8167.44, 20.41],
  [8081.58, 8167.02, 20.4],
  [8079.72, 8166.6, 20.41],
  [8077.85, 8166.14, 20.45],
  [8075.97, 8165.64, 20.49],
  [8074.07, 8165.09, 20.48],
  [8072.16, 8164.5, 20.49],
  [8070.25, 8163.9, 20.48],
  [8068.34, 8163.31, 20.47],
  [8066.43, 8162.72, 20.49],
  [8064.52, 8162.12, 20.45],
  [8063.04, 8161.66, 20.45],
  [8062.0, 8161.34, 20.42],
  [8061.4, 8161.15, 20.43],
  [8061.22, 8161.1, 20.44],
  [8060.6, 8160.96, 20.44],
  [8059.54, 8160.74, 20.43],
  [8058.02, 8160.44, 20.41],
  [8056.06, 8160.06, 20.4],
  [8054.09, 8159.68, 20.38],
  [8052.13, 8159.3, 20.35],
  [8050.17, 8158.91, 20.35],
  [8048.21, 8158.53, 20.33],
  [8046.68, 8158.23, 20.28],
  [8045.58, 8158.02, 20.28],
  [8044.92, 8157.89, 20.27],
  [8044.69, 8157.84, 20.26],
  [8044.02, 8157.78, 20.24],
  [8042.9, 8157.71, 20.22],
  [8041.35, 8157.61, 20.19],
  [8039.35, 8157.5, 20.12],
  [8037.36, 8157.39, 20.07],
  [8035.36, 8157.28, 20.04],
  [8033.36, 8157.17, 20.0],
  [8031.36, 8157.06, 19.98],
  [8029.7, 8156.97, 19.95],
  [8028.37, 8156.89, 19.92],
  [8027.37, 8156.84, 19.9],
  [8026.7, 8156.8, 19.88],
  [8025.7, 8156.73, 19.85],
  [8024.37, 8156.63, 19.84],
  [8022.71, 8156.49, 19.81],
  [8020.72, 8156.32, 19.76],
  [8018.72, 8156.15, 19.73],
  [8016.73, 8155.98, 19.7],
  [8014.74, 8155.81, 19.65],
  [8012.75, 8155.64, 19.6],
  [8011.0, 8155.49, 19.56],
  [8009.51, 8155.37, 19.52],
  [8008.28, 8155.26, 19.49],
  [8007.29, 8155.18, 19.46],
  [8006.05, 8155.15, 19.41],
  [8004.56, 8155.18, 19.38],
  [8002.82, 8155.28, 19.37],
  [8000.82, 8155.43, 19.34],
  [7998.83, 8155.59, 19.3],
  [7996.83, 8155.74, 19.26],
  [7994.84, 8155.89, 19.22],
  [7992.85, 8156.05, 19.19],
  [7991.31, 8156.17, 19.17],
  [7990.23, 8156.25, 19.15],
  [7989.61, 8156.3, 19.14],
  [7989.44, 8156.31, 19.13],
  [7988.82, 8156.36, 19.12],
  [7987.74, 8156.45, 19.09],
  [7986.2, 8156.57, 19.06],
  [7984.21, 8156.73, 19.03],
  [7982.22, 8156.89, 18.98],
  [7980.22, 8157.05, 18.94],
  [7978.23, 8157.21, 18.9],
  [7976.23, 8157.37, 18.86],
  [7974.4, 8157.51, 18.84],
  [7972.73, 8157.65, 18.81],
  [7971.22, 8157.77, 18.81],
  [7969.87, 8157.88, 18.8],
  [7968.36, 8158.0, 18.76],
  [7966.68, 8158.13, 18.66],
  [7964.85, 8158.28, 18.65],
  [7962.86, 8158.44, 18.62],
  [7961.16, 8158.57, 18.6],
  [7959.76, 8158.68, 18.57],
  [7958.66, 8158.77, 18.55],
  [7957.86, 8158.83, 18.54],
  [7957.26, 8158.88, 18.53],
  [7956.86, 8158.91, 18.52],
  [7956.65, 8158.93, 18.52],
  [7956.16, 8158.98, 18.51],
  [7955.16, 8159.09, 18.49],
  [7953.67, 8159.26, 18.45],
  [7951.69, 8159.48, 18.4],
  [7949.7, 8159.7, 18.41],
  [7947.71, 8159.93, 18.36],
  [7945.72, 8160.15, 18.32],
  [7943.74, 8160.37, 18.27],
  [7941.8, 8160.59, 18.23],
  [7939.92, 8160.8, 18.2],
  [7938.1, 8161.0, 18.16],
  [7936.32, 8161.2, 18.11],
  [7934.81, 8161.4, 18.08],
  [7933.55, 8161.59, 18.07],
  [7932.55, 8161.78, 18.06],
  [7931.81, 8161.97, 18.07],
  [7931.25, 8162.11, 18.08],
  [7930.88, 8162.2, 18.09],
  [7930.69, 8162.25, 18.09]
 ],
 "waypoints_local_dp5cm_plus_taper": [
  {
   "s": 0.0,
   "x": 8099.98,
   "y": 8171.12,
   "z": 20.56,
   "width_m": 6.0
  },
  {
   "s": 22.68,
   "x": 8077.85,
   "y": 8166.14,
   "z": 20.45,
   "width_m": 6.0
  },
  {
   "s": 26.61,
   "x": 8074.07,
   "y": 8165.09,
   "z": 20.48,
   "width_m": 6.0
  },
  {
   "s": 40.06,
   "x": 8061.22,
   "y": 8161.1,
   "z": 20.44,
   "width_m": 6.0
  },
  {
   "s": 56.91,
   "x": 8044.69,
   "y": 8157.84,
   "z": 20.26,
   "width_m": 6.0
  },
  {
   "s": 75.93,
   "x": 8025.7,
   "y": 8156.73,
   "z": 19.85,
   "width_m": 6.0
  },
  {
   "s": 94.41,
   "x": 8007.29,
   "y": 8155.18,
   "z": 19.46,
   "width_m": 6.0
  },
  {
   "s": 97.14,
   "x": 8004.56,
   "y": 8155.18,
   "z": 19.38,
   "width_m": 6.0
  },
  {
   "s": 98.88,
   "x": 8002.82,
   "y": 8155.28,
   "z": 19.37,
   "width_m": 6.0
  },
  {
   "s": 140.2,
   "x": 7961.63,
   "y": 8158.53,
   "z": 18.61,
   "width_m": 6.0
  },
  {
   "s": 144.99,
   "x": 7956.86,
   "y": 8158.91,
   "z": 18.52,
   "width_m": 6.479
  },
  {
   "s": 150.2,
   "x": 7951.68,
   "y": 8159.48,
   "z": 18.4,
   "width_m": 7.0
  },
  {
   "s": 165.65,
   "x": 7936.32,
   "y": 8161.2,
   "z": 18.11,
   "width_m": 7.0
  },
  {
   "s": 168.45,
   "x": 7933.55,
   "y": 8161.59,
   "z": 18.07,
   "width_m": 7.0
  },
  {
   "s": 171.39,
   "x": 7930.69,
   "y": 8162.25,
   "z": 18.09,
   "width_m": 7.0
  }
 ],
 "raw_osm_survey_EN": [
  [635779.98, 171251.12],
  [635756.93, 171245.98],
  [635740.97, 171241.02],
  [635724.34, 171237.78],
  [635705.7, 171236.75],
  [635685.81, 171235.05],
  [635669.19, 171236.33],
  [635647.84, 171238.04],
  [635636.65, 171238.93],
  [635613.67, 171241.5],
  [635610.69, 171242.25]
 ],
 "raw_osm_local_xy": [
  [8099.98, 8171.12],
  [8076.93, 8165.98],
  [8060.97, 8161.02],
  [8044.34, 8157.78],
  [8025.7, 8156.75],
  [8005.81, 8155.05],
  [7989.19, 8156.33],
  [7967.84, 8158.04],
  [7956.65, 8158.93],
  [7933.67, 8161.5],
  [7930.69, 8162.25]
 ],
 "raw_osm_s": [0.0, 23.6, 40.3, 57.3, 75.9, 95.9, 112.6, 134.0, 145.2, 168.3, 171.4],
 "dtm_1m_s_z": [
  [0.0, 20.56497573852539],
  [1.0, 20.560108184814453],
  [2.0, 20.571453094482422],
  [3.0, 20.55429458618164],
  [4.0, 20.54851531982422],
  [5.0, 20.539709091186523],
  [6.0, 20.524524688720703],
  [7.0, 20.483369827270508],
  [8.0, 20.478927612304688],
  [9.0, 20.46245765686035],
  [10.0, 20.457935333251953],
  [11.0, 20.457664489746094],
  [12.0, 20.43285369873047],
  [13.0, 20.42584800720215],
  [14.0, 20.415456771850586],
  [15.0, 20.403291702270508],
  [16.0, 20.422260284423828],
  [17.0, 20.411890029907227],
  [18.0, 20.39633560180664],
  [19.0, 20.394561767578125],
  [20.0, 20.40044403076172],
  [21.0, 20.416696548461914],
  [22.0, 20.43282699584961],
  [23.0, 20.45905113220215],
  [24.0, 20.481632232666016],
  [25.0, 20.493572235107422],
  [26.0, 20.49789810180664],
  [27.0, 20.477760314941406],
  [28.0, 20.479631423950195],
  [29.0, 20.491695404052734],
  [30.0, 20.476524353027344],
  [31.0, 20.48063087463379],
  [32.0, 20.47991943359375],
  [33.0, 20.468292236328125],
  [34.0, 20.49188232421875],
  [35.0, 20.494571685791016],
  [36.0, 20.466232299804688],
  [37.0, 20.44805335998535],
  [38.0, 20.44795799255371],
  [39.0, 20.42932891845703],
  [40.0, 20.433761596679688],
  [41.0, 20.437572479248047],
  [42.0, 20.432008743286133],
  [43.0, 20.416797637939453],
  [44.0, 20.402748107910156],
  [45.0, 20.396217346191406],
  [46.0, 20.387496948242188],
  [47.0, 20.382606506347656],
  [48.0, 20.37350845336914],
  [49.0, 20.357933044433594],
  [50.0, 20.355464935302734],
  [51.0, 20.35346221923828],
  [52.0, 20.338342666625977],
  [53.0, 20.329275131225586],
  [54.0, 20.307466506958008],
  [55.0, 20.28291893005371],
  [56.0, 20.281742095947266],
  [57.0, 20.261526107788086],
  [58.0, 20.231380462646484],
  [59.0, 20.211572647094727],
  [60.0, 20.191814422607422],
  [61.0, 20.164051055908203],
  [62.0, 20.128734588623047],
  [63.0, 20.106538772583008],
  [64.0, 20.075546264648438],
  [65.0, 20.054580688476562],
  [66.0, 20.049457550048828],
  [67.0, 20.02448272705078],
  [68.0, 20.000654220581055],
  [69.0, 19.990873336791992],
  [70.0, 19.983530044555664],
  [71.0, 19.964292526245117],
  [72.0, 19.951438903808594],
  [73.0, 19.93362045288086],
  [74.0, 19.902742385864258],
  [75.0, 19.87612533569336],
  [76.0, 19.850004196166992],
  [77.0, 19.836219787597656],
  [78.0, 19.830276489257812],
  [79.0, 19.811279296875],
  [80.0, 19.784929275512695],
  [81.0, 19.75887107849121],
  [82.0, 19.738021850585938],
  [83.0, 19.731876373291016],
  [84.0, 19.708494186401367],
  [85.0, 19.697114944458008],
  [86.0, 19.667865753173828],
  [87.0, 19.644289016723633],
  [88.0, 19.62418556213379],
  [89.0, 19.604015350341797],
  [90.0, 19.58557891845703],
  [91.0, 19.548458099365234],
  [92.0, 19.51936149597168],
  [93.0, 19.50177574157715],
  [94.0, 19.469261169433594],
  [95.0, 19.436141967773438],
  [96.0, 19.404970169067383],
  [97.0, 19.386045455932617],
  [98.0, 19.373592376708984],
  [99.0, 19.364763259887695],
  [100.0, 19.35654067993164],
  [101.0, 19.343154907226562],
  [102.0, 19.329299926757812],
  [103.0, 19.29400062561035],
  [104.0, 19.276012420654297],
  [105.0, 19.258840560913086],
  [106.0, 19.23894691467285],
  [107.0, 19.21440315246582],
  [108.0, 19.19664192199707],
  [109.0, 19.18939781188965],
  [110.0, 19.172245025634766],
  [111.0, 19.159299850463867],
  [112.0, 19.139921188354492],
  [113.0, 19.120689392089844],
  [114.0, 19.09261703491211],
  [115.0, 19.07189178466797],
  [116.0, 19.055599212646484],
  [117.0, 19.0408935546875],
  [118.0, 19.012548446655273],
  [119.0, 18.978439331054688],
  [120.0, 18.976459503173828],
  [121.0, 18.943641662597656],
  [122.0, 18.930591583251953],
  [123.0, 18.916908264160156],
  [124.0, 18.89158821105957],
  [125.0, 18.875221252441406],
  [126.0, 18.84513282775879],
  [127.0, 18.83725357055664],
  [128.0, 18.836429595947266],
  [129.0, 18.81153678894043],
  [130.0, 18.805307388305664],
  [131.0, 18.806713104248047],
  [132.0, 18.802196502685547],
  [133.0, 18.779285430908203],
  [134.0, 18.73116683959961],
  [135.0, 18.66514778137207],
  [136.0, 18.637662887573242],
  [137.0, 18.649682998657227],
  [138.0, 18.63160514831543],
  [139.0, 18.61855697631836],
  [140.0, 18.6090087890625],
  [141.0, 18.597942352294922],
  [142.0, 18.570209503173828],
  [143.0, 18.5584716796875],
  [144.0, 18.53913688659668],
  [145.0, 18.519969940185547],
  [146.0, 18.501848220825195],
  [147.0, 18.479833602905273],
  [148.0, 18.45505142211914],
  [149.0, 18.409435272216797],
  [150.0, 18.39593505859375],
  [151.0, 18.42779541015625],
  [152.0, 18.419631958007812],
  [153.0, 18.375246047973633],
  [154.0, 18.366147994995117],
  [155.0, 18.334707260131836],
  [156.0, 18.32782745361328],
  [157.0, 18.309078216552734],
  [158.0, 18.27573013305664],
  [159.0, 18.261608123779297],
  [160.0, 18.23242950439453],
  [161.0, 18.2336483001709],
  [162.0, 18.2039852142334],
  [163.0, 18.18878936767578],
  [164.0, 18.159730911254883],
  [165.0, 18.132753372192383],
  [166.0, 18.102014541625977],
  [167.0, 18.083789825439453],
  [168.0, 18.074024200439453],
  [169.0, 18.05846405029297],
  [170.0, 18.066028594970703],
  [171.0, 18.084739685058594]
 ],
 "dtm_ma15_s_z": [
  [7, 20.499],
  [8, 20.488],
  [9, 20.479],
  [10, 20.468],
  [11, 20.457],
  [12, 20.447],
  [13, 20.438],
  [14, 20.431],
  [15, 20.427],
  [16, 20.426],
  [17, 20.427],
  [18, 20.43],
  [19, 20.432],
  [20, 20.435],
  [21, 20.439],
  [22, 20.444],
  [23, 20.449],
  [24, 20.453],
  [25, 20.457],
  [26, 20.462],
  [27, 20.469],
  [28, 20.475],
  [29, 20.478],
  [30, 20.479],
  [31, 20.478],
  [32, 20.475],
  [33, 20.471],
  [34, 20.467],
  [35, 20.464],
  [36, 20.46],
  [37, 20.454],
  [38, 20.448],
  [39, 20.442],
  [40, 20.436],
  [41, 20.429],
  [42, 20.42],
  [43, 20.411],
  [44, 20.404],
  [45, 20.396],
  [46, 20.388],
  [47, 20.38],
  [48, 20.37],
  [49, 20.36],
  [50, 20.349],
  [51, 20.336],
  [52, 20.323],
  [53, 20.31],
  [54, 20.295],
  [55, 20.278],
  [56, 20.26],
  [57, 20.241],
  [58, 20.221],
  [59, 20.201],
  [60, 20.18],
  [61, 20.158],
  [62, 20.137],
  [63, 20.117],
  [64, 20.096],
  [65, 20.075],
  [66, 20.055],
  [67, 20.035],
  [68, 20.014],
  [69, 19.993],
  [70, 19.973],
  [71, 19.955],
  [72, 19.937],
  [73, 19.919],
  [74, 19.9],
  [75, 19.881],
  [76, 19.863],
  [77, 19.844],
  [78, 19.825],
  [79, 19.805],
  [80, 19.785],
  [81, 19.764],
  [82, 19.744],
  [83, 19.725],
  [84, 19.705],
  [85, 19.684],
  [86, 19.662],
  [87, 19.639],
  [88, 19.616],
  [89, 19.592],
  [90, 19.569],
  [91, 19.545],
  [92, 19.522],
  [93, 19.499],
  [94, 19.477],
  [95, 19.456],
  [96, 19.434],
  [97, 19.413],
  [98, 19.391],
  [99, 19.37],
  [100, 19.35],
  [101, 19.33],
  [102, 19.311],
  [103, 19.293],
  [104, 19.277],
  [105, 19.26],
  [106, 19.244],
  [107, 19.225],
  [108, 19.206],
  [109, 19.187],
  [110, 19.168],
  [111, 19.149],
  [112, 19.129],
  [113, 19.111],
  [114, 19.091],
  [115, 19.072],
  [116, 19.053],
  [117, 19.034],
  [118, 19.014],
  [119, 18.993],
  [120, 18.973],
  [121, 18.954],
  [122, 18.935],
  [123, 18.917],
  [124, 18.901],
  [125, 18.885],
  [126, 18.869],
  [127, 18.853],
  [128, 18.832],
  [129, 18.811],
  [130, 18.793],
  [131, 18.774],
  [132, 18.756],
  [133, 18.738],
  [134, 18.721],
  [135, 18.703],
  [136, 18.685],
  [137, 18.667],
  [138, 18.648],
  [139, 18.627],
  [140, 18.606],
  [141, 18.584],
  [142, 18.563],
  [143, 18.545],
  [144, 18.531],
  [145, 18.516],
  [146, 18.499],
  [147, 18.482],
  [148, 18.463],
  [149, 18.445],
  [150, 18.428],
  [151, 18.409],
  [152, 18.391],
  [153, 18.371],
  [154, 18.354],
  [155, 18.335],
  [156, 18.317],
  [157, 18.301],
  [158, 18.283],
  [159, 18.262],
  [160, 18.239],
  [161, 18.219],
  [162, 18.199],
  [163, 18.181],
  [164, 18.164]
 ],
 "dtm_noise": {
  "resid_rms_cm_after_ma15": 1.5,
  "resid_max_cm": 4.7,
  "step_1m_rms_cm": 2.1,
  "step_1m_max_cm": 6.6
 },
 "authoring_plan_s": {
  "width": {
   "s0_6m": 0.0,
   "taper_start": 140.2,
   "taper_end": 150.2,
   "s1_7m": 171.38760160496693,
   "from_m": 6.0,
   "to_m": 7.0
  },
  "centre_dashes": {
   "s": [0.0, 171.39],
   "offset_m": 0.0,
   "width_m": 0.1,
   "dash_m": 4.0,
   "gap_m": 2.0,
   "colour": "white"
  },
  "double_yellow": {
   "side": "left",
   "s": [0.0, 60.0],
   "anchor": "edge_left",
   "inset_m": 0.25,
   "line_width_m": 0.075,
   "line_gap_m": 0.075,
   "colour": "yellow",
   "note": "junction approach + bend, beside the half-grass kerb"
  },
  "drop_kerb": {
   "side": "right",
   "s_centre": 40.3,
   "flat_m": 3.0,
   "ramp_m": 0.9,
   "target_height_m": 0.0,
   "s_ramp_down": [37.9, 38.8],
   "s_flat": [38.8, 41.8],
   "s_ramp_up": [41.8, 42.7]
  },
  "half_grass_kerb": {
   "side": "left",
   "s": [0.0, 95.9],
   "note": "grass outer face, tarmac inner, flush top; standard UK kerb on the left [95.9, L] and on the right [0, L]"
  },
  "barriers_right_side": [
   {
    "s0": 0.0,
    "s1": 45.0,
    "type": "brick_wall",
    "height_m": 1.2,
    "thickness_m": 0.23
   },
   {
    "s0": 45.0,
    "s1": 95.0,
    "type": "chain_link",
    "height_m": 1.2,
    "thickness_m": 0.05
   },
   {
    "s0": 95.0,
    "s1": 140.0,
    "type": "railing",
    "height_m": 1.0,
    "thickness_m": 0.05
   }
  ],
  "barrier_lateral": "back of pavement: w/2 + pav = 3.0 + 1.5 = 4.5 m from centreline on the 6 m section",
  "hedge_right_side": {
   "s0": 55.0,
   "s1": 90.0,
   "height_m": 1.5,
   "width_m": 0.8,
   "lateral_extra_m": 0.4,
   "note": "privet behind the chain-link run"
  },
  "plan_points_local": {
   "double_yellow_start": {
    "s": 0.0,
    "x": 8099.98,
    "y": 8171.12,
    "z_06": 20.56
   },
   "double_yellow_end": {
    "s": 60.0,
    "x": 8041.61,
    "y": 8157.63,
    "z_06": 20.2
   },
   "drop_kerb_centre": {
    "s": 40.3,
    "x": 8060.99,
    "y": 8161.05,
    "z_06": 20.44
   },
   "barrier_brick_to_chainlink": {
    "s": 45.0,
    "x": 8056.38,
    "y": 8160.12,
    "z_06": 20.4
   },
   "barrier_chainlink_to_railing": {
    "s": 95.0,
    "x": 8006.7,
    "y": 8155.17,
    "z_06": 19.44
   },
   "barrier_end": {
    "s": 140.0,
    "x": 7961.83,
    "y": 8158.52,
    "z_06": 18.61
   },
   "hedge_start": {
    "s": 55.0,
    "x": 8046.57,
    "y": 8158.21,
    "z_06": 20.28
   },
   "hedge_end": {
    "s": 90.0,
    "x": 8011.68,
    "y": 8155.55,
    "z_06": 19.58
   },
   "taper_start": {
    "s": 140.2,
    "x": 7961.63,
    "y": 8158.53,
    "z_06": 18.61
   },
   "osm_join": {
    "s": 145.2,
    "x": 7956.65,
    "y": 8158.93,
    "z_06": 18.52
   },
   "taper_end": {
    "s": 150.2,
    "x": 7951.68,
    "y": 8159.48,
    "z_06": 18.4
   },
   "end": {
    "s": 171.4,
    "x": 7930.69,
    "y": 8162.25,
    "z_06": 18.09
   },
   "half_grass_end": {
    "s": 95.9,
    "x": 8005.8,
    "y": 8155.16,
    "z_06": 19.4
   }
  },
  "viewpoint": "from the square (south, left side) looking north: far side = right/north",
  "heights": {
   "height_source": "terrain",
   "smooth_window_m": 15.0,
   "note": "sample the heightfield at every tessellated point, then 15 m moving average; z in points[] is informative"
  },
  "overlay": {
   "points": "raw_osm_local_xy with z from the nearest 06 vertex",
   "lift_m": 0.5
  }
 }
}
```
