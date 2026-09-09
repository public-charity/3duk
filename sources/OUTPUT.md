# Output contract

What the pipeline writes into `data/<site>/out/`, and what a consumer may rely on.
Verified by `sources/tests/dryrun.py`. Change this document and the test together.

## Conventions that hold everywhere

| | |
|---|---|
| **CRS** | The site config's `crs` (Margate: EPSG:27700, British National Grid). Every coordinate below is an easting/northing in this CRS, in **metres**. No local origin is subtracted. |
| **Georeferencing accuracy** | OSM arrives in WGS84 and is reprojected once, in step 01, with PROJ's best available operation — step 01 **refuses to run** if that operation is worse than the site's `crs_max_transform_accuracy_m` (for OSGB36: the OSTN15 grid, not the 2 m Helmert fallback). The operation used is recorded in `sources/provenance/<site>.osm.json` as `datum_transformation`. LIDAR is native to the CRS. With the grid, footprints and roads reproduce a reference run to the centimetre; without it, everything OSM-derived sits ~1.8 m off the LIDAR. |
| **Elevation** | Metres above the site's `vertical_datum` (Margate: ODN). Always the **third** component of a vertex, or a field named `z`/`base_z`. Never Y-up. |
| **Orientation** | `bearing`: degrees clockwise from grid north, `[0, 360)`. |
| **Rasters** | GeoTIFF, **north-up** (row 0 is the northern edge), georeferenced, CRS-tagged. |
| **Tiles** | `x{i}_y{j}`: `i` counts east from `origin.E`, `j` counts north from `origin.N`, each `tile_m` metres. A feature belongs to the tile containing its centroid (buildings, furniture) or is split at tile boundaries with the seam vertex duplicated on both sides (roads). |
| **Manifests** | Every product directory has one `*_manifest.json` recording `site`, `crs`, `origin`, `tile_m` and every parameter the step ran under. Read it before the data. |
| **null** | Means *unknown*, never zero. A `null` elevation is "we have no measurement here" — drape it yourself. |
| **`src`** | Where a value came from. Filter on it. Nothing is invented without saying so. |
| **Clip** | A site config may carry an optional `clip` block (Thanet: the half-plane north-east of the Minnis Bay → Pegwell Bay line). Every manifest of a clipped site records it under `clip` (`type`, `line`, `keep`, `semantics`, and — in every manifest written by `sources/derive/*` — `wkt`, the kept region as a polygon in CRS metres, so you never have to re-derive the cut outline yourself); no `clip` key = unclipped site, and an unclipped site's products are byte-identical to what they were before clips existed. Rasters are clipped at cell centres; vertices, footprint envelope centres and nodes at their positions; points exactly on the line are kept. |
| **`_incomplete.json`** | Its presence in a product directory means the step that owns it is mid-rebuild or died mid-rebuild: **the directory is incomplete and its manifest describes an earlier run**. Steps 05 and 09 clear their whole directory before computing, so they write this marker before the first delete and remove it only after the manifest is written. Test for it before trusting a product. A successful run never leaves one. |

Nothing here knows about any engine. `sources/adapters/unity.py` is what a consumer
that wants local Y-up coordinates and 16-bit heightmaps looks like — copy it.

## `terrain/` — step 05

`dtm_x{i}_y{j}.tif` — Float32, one band, `grid_res × grid_res` (513: 512 m + a shared
edge row, so adjacent tiles have identical borders). Nodata has been **filled**; the
manifest says how many cells and by which method per tile. **Except** cells outside the
site's clip: written as the band's declared NoData (`terrain_manifest.nodata`, −9999)
**after** the fill — a deliberate absence, never a coverage gap. `clipped_cells` per tile
counts them; `clip_state` is `inside` or `straddle`. Positions wholly outside have no file
and are `tiles_clipped`, distinct from `tiles_missing`. Render NoData as a hole. On a
clipless site no tile declares a NoData value and none of these keys exist.

`terrain_manifest.json` — `range_m` is the true site-wide elevation range. A consumer
encoding into a fixed window must compare against it; the pipeline will not clip for you.
`fill` per tile is `none`, `mosaic nearest` (scipy present), `mosaic median (degraded)` —
treat that as provisional — or `all-nodata -> mosaic nearest`, which means the source had
**no valid cell anywhere in that tile**: every one of its 513×513 cells came from the
nearest surveyed cell elsewhere in the site. Those positions are listed as
`tiles_fabricated` (key present only when it happened) and the step prints a WARNING naming
them. Nothing in such a tile was surveyed — a consumer that cares about real ground should
treat them like `tiles_missing`. `empty_fill_m` is the value used if the **whole site** had
no valid cell at all (the site's `water_level` where it has one, else 0 m).
`tiles_missing` lists grid positions that have **no tile at all** (the source returned
nothing there — beyond its coverage); do not assume they are sea.
For a clipped site `range_m` and `slope_qa` describe kept cells only (the gradient itself
is taken on the filled, unclipped array, so the edge cells carry their true slope).

`shared_edges` — **the seam guarantee, measured on the files just written.** Neighbours
share a row of samples, so `grid_res − 1` metres of tile plus one shared line; that line is
one vertex in any consumer that assembles the tiles. `pairs`, `samples_compared`,
`samples_disagreeing`, `max_disagreement_m`, `max_at`. It is **0**, and step 05 exits
non-zero if it is not. It is 0 because the NoData fill is decided **once over the whole
site mosaic** and the tiles are cut out of the result — filling per tile made each of two
neighbours invent that line from its own cells and they disagreed (Thanet, 2026-09-09:
28,725 of 370,797 shared samples, worst 5.34 m, carried into the engine as a 512 m false
cliff). A consumer may rely on `hm[i][:, -1] == hm[i+1][:, 0]` to the bit.

`fill` (site level, present only when the source had NoData) — how much of the product is
invention and how far it had to reach for it: `method`, `nodata_cells`, the `mosaic` it was
decided over and its `shared_cell_conflicts` (raw tiles that disagree where they overlap;
must be 0), `reach_m` percentiles and `cells_by_reach_m`. Per tile, `fill_reach_max_m` and
`fill_reach_p50_m`. **Reach is the honesty number**: a few metres is a gap in a survey; on
Thanet the median is 320 m and the maximum 1,379 m, which is open sea being filled from the
coast. The filled values carry no marker of their own — this is the record.

`slope_qa` — `max_deg` and `pct_cells_over_45deg` site-wide, plus `slope_max_deg`,
`slope_p99_deg` and `cells_over_45deg` per tile, all at native resolution. **This is how you
prove cliffs survived.** The EA DTM holds cliff faces at 65–80° (measured at Cliftonville:
5 m wide for a 10 m drop; 8.6 m in a single cell at the steepest). If your engine shows
nothing steeper than ~45° where this says 70+, your import resampled or your terrain LOD
decimated it — the data did not. Keep heightmap resolution equal to `grid_res` and turn
pixel-error/LOD decimation down.

## `networks/` — step 06

`roads_x{i}_y{j}.jsonl`, one record per line.

```json
{"id":"w123","cls":"residential","w":6.0,"pav":1.5,"name":"High Street",
 "bridge":false,"tunnel":false,"z_gap":false,
 "pts":[[632912.4,168377.1,11.02], ...]}
```

| field | meaning |
|---|---|
| `cls` | OSM `highway` value. Only classes listed in `tuning.json → roads.widths_m` are emitted. |
| `w`, `pav` | Carriageway width and pavement width **each side**, metres — from tuning, widened by OSM `lanes`. Opinions, not survey; recorded in the manifest. |
| `bridge`, `tunnel` | OSM flags, passed through. The elevation is **not** adjusted for them — it is the ground under the structure. Raise the deck yourself. |
| `z_gap` | `true` if any vertex **of this segment** fell on a DTM gap — nodata, or beyond the mosaic's extent; its elevation was carried from the nearest sampled vertex along the way (both directions). Segments of the same way that were fully sampled stay `false`. |
| `pts` | `[E, N, z]`. Draped on the DTM by bilinear sample, after Chaikin smoothing (`manifest.smoothing.chaikin_iters`; 0 = faithful to OSM vertices). |

Records with `"cls":"_junction"` are different: `{"cls":"_junction","r":3.4,"pts":[[E,N,z]]}`
— one point and a radius, where three or more ways meet.

Ways are clipped to the tile grid: a way that leaves the grid ends at its last inside
vertex, and nothing is written for tiles with negative indices. `networks_manifest.json`
counts `vertices_outside_grid` and `vertices_without_dtm`. Likewise a way that crosses the
clip line ends at its last kept smoothed vertex (within ~12 m of the line at the default
smoothing); `vertices_outside_clip` and `junctions_outside_clip` are counted; off-clip
vertices are not DTM gaps. `length_km` counts whole ways, beyond the grid and the clip.

## `networks/` — step 11

Railway and barrier ways from the same GeoPackage, densified, draped and tiled exactly as
roads are (through `lib.drape_runs`; a rail drawn along a road's polyline gets the road's
vertices to the centimetre). No width is emitted for either layer.

`rail_x{i}_y{j}.jsonl`, one record per tile run:

```json
{"id":"w123","cls":"rail","gauge":1.435,"gauge_src":"osm","tracks":2,"electrified":"rail","service":null,"usage":"main",
 "bridge":false,"tunnel":false,"name":"Chatham Main Line","z_gap":false,"pts":[[E,N,z],...]}
```

| field | type | meaning |
|---|---|---|
| `id` | string | OSM way id |
| `cls` | string | the OSM `railway` value verbatim (`tuning.json → rail.classes`: `rail`, `light_rail`, `tram`, `narrow_gauge`, `miniature`, `disused` — track still in place) |
| `gauge` | number, m | OSM `gauge` mm → m (`"1435"` → 1.435; `"1435;1000"` → first; `"standard"` → 1.435); absent/unparseable → `tuning.rail.default_gauge_m` |
| `gauge_src` | `osm` \| `default` | |
| `tracks` | int or null | OSM `tracks`, not defaulted |
| `electrified`, `service`, `usage` | string or null | raw OSM values |
| `bridge`, `tunnel` | bool | tag presence, elevation not adjusted |
| `name` | string or null | |
| `z_gap` | bool | as roads |
| `pts` | `[[E, N, z], …]` | densified (`tuning.rail.densify_step_m` 8) + Chaikin (`chaikin_iters` 2), draped, tiled, cut at grid and clip |

`barriers_x{i}_y{j}.jsonl`:

```json
{"id":"w456","cls":"wall","h":0.5,"h_src":"osm","material":null,"fence_type":null,"wall":"brick","name":null,"z_gap":false,"pts":[[E,N,z],...]}
```

| field | type | meaning |
|---|---|---|
| `cls` | string | OSM `barrier` value verbatim (`tuning.json → barriers.classes`: `wall`, `fence`, `hedge`, `retaining_wall`, `kerb`, `guard_rail`, `handrail`, `city_wall`) |
| `h` | number, m | OSM `height`: first token, unit suffix `m` (default) / `cm` (÷100) / `mm` (÷1000) / `ft` or `'` (×0.3048); absent/unparseable → `tuning.barriers.default_height_m[cls]` |
| `h_src` | `osm` \| `default` | |
| `material`, `fence_type`, `wall`, `name` | string or null | raw OSM |
| `z_gap` | bool | |
| `pts` | `[[E, N, z], …]` | densified 8 m, **Chaikin 0** (walls turn corners), draped, tiled |

`linear_manifest.json` is step 11's manifest (`networks_manifest.json` stays step 06's).
`default_gauge_m` and `default_height_m` are opinions from `tuning.json`; records that used
them say so in `gauge_src` / `h_src`, and `gauge_defaulted` / `height_defaulted` count them.
`by_class` counts ways that produced at least one tile run; `ways_dropped` had no kept
vertex on the grid. `ways_skipped_by_class` lists every `railway`/`barrier` value seen but
not emitted (`abandoned`, `razed`, `platform`; `gate`, `bollard`, `yes`, …);
`barrier_areas_skipped` counts closed barrier outlines in `multipolygons`, which are not
read. A way tagged both `highway` and `railway` appears in both layers. Zero railway ways is
not an error, but the step says whether the extract was fetched with `way["railway"]` in the
query (`sources/provenance/<site>.osm.json → query_sha256`).

## `massing/` — step 07

`buildings_x{i}_y{j}.jsonl`, one record per OSM building footprint — **including
footprints with no LIDAR coverage** (they carry `lidar_px: 0` and null ground).

```json
{"id":"w456","name":null,"type":"house","h":6.8,"ridge":9.5,"eaves":5.0,
 "base_z":9.4,"skirt":8.9,"lidar_px":60,"levels":2,"roof":"gabled",
 "src":"lidar_p50","seed":2891404412,
 "rings":[{"hole":false,"pts":[[E,N],[E,N],...]}]}
```

| field | meaning |
|---|---|
| `h` | Body/wall height **above ground**, metres. Never null. |
| `ridge`, `eaves` | Also above ground: nDSM p90 and p25 inside the footprint. `eaves` is null without LIDAR. |
| `base_z` | Absolute ground elevation at the footprint (DTM p15). **null without LIDAR** — drape it. |
| `skirt` | Absolute elevation to extend walls down to, so a building on a slope does not float. null without LIDAR. |
| `lidar_px` | How many first-return (DSM) cells fell inside the footprint — the evidence behind a LIDAR height. `0` with a real `base_z` means **the DSM has a gap here but the DTM does not**: the EA first-return composite has flight-strip holes over land (Whitby: 187 ha, 630 buildings). Ground is measured; height came down the ladder. `0` with `base_z: null` means no LIDAR at all. |
| `roof` | OSM `roof:shape` if tagged, else `flat` for the types in tuning, else the tuning default. |
| `src` | Which rung produced `h`, in order of trust: `seamark_height` (a charted landmark's `seamark:landmark:height` — see below), `osm_height`, `lidar_p50`, `lidar_p50_disputed` (LIDAR disagrees with `building:levels` by more than `height_calib.dispute_m`), `lidar_lowconf` (fewer than `min_pixels` samples), `osm_levels` (`height_calib` regression, **site-specific**), `type_prior` (**no evidence at all** — a per-type guess measured at another site; see `tuning.json`), `landmark_override` (hand-authored in the site config). |
| `seed` | Stable per-building hash for deterministic variation. |
| `rings` | Exterior first, then holes. `[E, N]` pairs, closed. |

`massing_manifest.json` — `by_height_source` is the histogram of `src`;
`buildings_without_lidar` (no ground, no height), `buildings_without_dsm` (ground yes,
height no — a DSM coverage gap) and `outside_grid` are counted. `outside_clip` counts
footprints whose envelope centre lies outside the clip; not emitted. `height_calib` is the line the
`osm_levels` rung actually used, with `source` = `fitted` (regressed from this site's own
buildings that carry both `building:levels` and a trustworthy LIDAR p50 — the default),
`config` (pinned in the site config) or `fallback` (too few buildings to fit; another
site's line was used — treat `osm_levels` heights as provisional). `height_calib_fit`
gives `n`, `rejected` and `rmse_m` for a fit, plus `excluded_off_grid` / `excluded_off_clip`
when footprints were held out. **The fit population is the model population**: only
footprints this site actually emits can steer the line, so the same config over the same
OSM extract gives the same line whether or not the raw LIDAR happens to cover ground the
grid or the clip excludes. If `type_prior` is a large share, the model is describing this
town with another town's building stock.

**Seamarks.** On a lighthouse or beacon the plain OSM `height` tag is, by the seamark
tagging scheme, the elevation of the *light* above MHWS — not the height of the structure.
Step 07 therefore prefers `seamark:landmark:height` on any footprint carrying `seamark:*`
tags or `man_made=lighthouse` and records `src: "seamark_height"`. (North Foreland, OSM way
562020647: `height=57`, `seamark:landmark:height=26`; the LIDAR says 25.75 m — DSM max 63.64
minus DTM p50 37.89 over 101 cells. The old ladder modelled it 31 m too tall.) Where a
seamark carries **only** the ambiguous tag it is still used — there is nothing better — but
step 07 prints a WARNING naming the way, its height and the LIDAR p90 beside it, so the
mismatch is visible rather than silent.

## `coast/` — step 09

`ground_x{i}_y{j}.tif` — Byte, four bands **grass, sand, rock, water** as fractions 0–255
that **sum to 252–255 (each band is truncated to a byte separately) for every cell inside
the site's clip; a cell outside the clip is 0 in all four bands (sum 0), and sum 0 occurs
only outside**, at `class_res × class_res` (256) per tile, georeferenced. Sand includes
OSM beach polygons **plus everything below `coast.foreshore_max_odn`** — a property of the
survey's tide state, recorded in the manifest. Rock is a slope ramp between
`coast.rock_slope_deg`.

**Water is the DTM's own surveyed surface.** The EA composite carries the water surface
over sea and harbour with 100% coverage (Whitby: one broad peak at −2.3 ± 0.3 m ODN —
flight strips at different tide states, plus swell — not a single plane). A cell is `water`
if it is **below `water_level`** (it cannot be exposed ground) or **within
`water_tolerance_m` of it with a flat calmest neighbour**; water is excluded from sand. That
surface is not ground: a consumer that drapes a water plane at `water_level` will z-fight
it, so sink or cut the terrain under the water band. Surface noise above the tolerance reads
as foreshore sand — on Whitby's pure-sea tiles that residue is 2–6%.

Tiles with no DTM at all get no raster and are listed as `tiles_without_dtm`. They are added
to `water_tiles` only if the site config says `coast.missing_tiles_are_water` — whether a
no-data tile is open sea or just beyond coverage is a per-site fact, not an assumption.

`coast_manifest.json` — `water_tiles` lists `[i, j]` pairs whose lowest ground is within
`water_margin_m` of `water_level`, i.e. tiles that need a water surface (judged on kept
cells only where a tile straddles the clip); `bands`, `thresholds`, `water_tolerance_m` and
`tiles_without_dtm` are recorded. `tiles_clipped` lists positions wholly outside (no raster;
distinct from `tiles_without_dtm`), `clipped_cells` counts zeroed cells, and `bands_note`
restates the sum rule.

## `furniture/` — step 10

`furniture_x{i}_y{j}.jsonl`, one record per OSM amenity node mapped in
`tuning.json → furniture.props`.

```json
{"id":"n789","prop":"LitterBin","name":null,"e":632945.0,"n":168402.3,"z":11.12,
 "bearing":90.0,"src":"kerb","d":4.3,"cls":"residential","nudged":true}
```

| field | meaning |
|---|---|
| `prop` | Abstract key. Mapping it to a mesh is yours. |
| `z` | Absolute elevation from the nearest draped road, plus `kerb_m` when on a pavement. **null** when the node is more than `snap_m` from any road or sits on a verge — drape it. |
| `bearing` | Squared to the nearest road. Random (seeded) when `src` is `terrain`. |
| `src` | `kerb`, `road` or `terrain`. |
| `d`, `cls` | Distance to, and class of, the road used. |
| `nudged` | `true` if the node was mapped inside the carriageway and moved to the pavement edge. The original OSM position is not kept; the move is at most half a carriageway. |

`qa_furniture.json` counts `outside_clip` nodes (judged at the OSM position, before any
nudge); not placed.

## `qa_*.json`

`qa_height_outliers.json` — buildings with too few LIDAR samples or a ridge far above the
walls. `qa_furniture.json` — placement counts and every amenity kind seen, so you can find
out what else is mappable.

## `unreal/` — the adapter's own tree, and the one product that is **not** the survey

*Everything above this heading is checked by `sources/tests/dryrun.py` on synthetic sites. This section
is not: `dryrun.py` exercises the adapter's own refusals, but `landscape_conformed/` is built by
`projects/one/`, outside `sources/`, and its own tests are
`projects/one/Tools/blender/tests/test_conform.py` (16 cases as of 2026-09-09, including a byte-for-byte reconstruction
of the survey from the delta rasters) and `projects/one/Tools/road_fusion_audit.py` (the whole-isle
acceptance gate). It is described here because a consumer reading `data/<site>/out/` will find it and
must not mistake it for the survey.*

Everything above is written by `sources/derive/` and is the survey. `data/<site>/out/unreal/`
is different in kind: it is written by `sources/adapters/unreal.py`, which converts the
survey into the Streetscape frame (local metres from `origin`, X east, Y north, Z ODN) for
Unreal and Blender. It is derived, it is regenerable from the survey in one command, and
`unreal_manifest.json` at its root is the index of what it holds. It changes nothing above
it: the adapter never writes into `terrain/`, `networks/`, `massing/`, `coast/` or
`furniture/`.

| directory | what it is |
|---|---|
| `unreal/landscape/` | The survey as an engine heightmap: `hm_x{i}_y{j}.r16` (h16 of step 05's filled DTM), `clip_*.r8`, `vis_*.r8`, `weight_{band}_*.r8`, `landscape_manifest.json`. **This is still the survey**, re-encoded. |
| `unreal/streetscape/` | `site_x{i}_y{j}.json` — the road, rail and barrier centrelines as splines with inlined profiles, plus `junctions[]`, and `streetscape_manifest.json`. |
| `unreal/massing/`, `unreal/furniture/` | The step 07 / step 10 products in the same frame. |
| **`unreal/landscape_conformed/`** | **Not the survey.** See below. |

### `landscape_conformed/` — the ground with the roads burned into it

`projects/one/Tools/conform_landscape.py` (geometry core
`projects/one/Tools/blender/streetscape/conform.py`) reads `unreal/landscape/` and every
`unreal/streetscape/site_*.json` and writes a **second, complete landscape product** beside
the first. It exists because a 6–12 m road ribbon laid on a 1 m DTM has the ground standing
through the carriageway at most stations — 84.9 % of the isle's 666,314 road stations before
this pass, zero after (`projects/one/docs/TERRAIN_ROADS.md` §4, §8).

**Its semantics, in one sentence: under the road corridor the ground IS the road surface,
not the measurement.** The manifest says so in words — `heightmap.semantics` reads
*"h16 of step 05's filled DTM, CONFORMED TO THE ROAD CORRIDOR — not the raw survey"* — and
a consumer that wants the survey must read `unreal/landscape/` or `terrain/` instead.

* Same file layout as `landscape/`. `clip_*.r8`, `vis_*.r8` and every `weight_*.r8` are
  copied **byte for byte**; only `hm_*.r16` differs, and only inside the corridor.
* `landscape_manifest.json` carries an extra `conform` block: the corridor parameters
  (sink 0.03 m, verge 2 m, blend 3–12 m at a 34° batter, clamp 2 m outside the built
  surface), the generator, the commit, and every headline number — on Thanet
  `cells_changed` 12,697,333 (12.70 km², 12.9 % of the kept land), `|Δ|` p50 0.078 m,
  p95 0.430 m, max fill +17.38 m, max cut −14.66 m, `cells_clamped` 1,321,998,
  `arbitrations` 9,248,160 — plus a `slope_qa` measured over the changed tiles beside the
  survey's, so a flattened cliff would be visible rather than silent (it is not: the site
  maximum is 86.278° before and after).
* **`conform_delta_x{i}_y{j}.r16`** — int16, little-endian, row-major, `res × res`, one per
  changed tile (246 of 391 on Thanet; an absent file means that tile is byte-identical to
  `landscape/`). It is `h16_conformed − h16_survey`, so **the survey is recoverable cell by
  cell**: `z_survey_m = (h16_conformed − delta) / 128 − 32768 / 128`. That is what the delta
  rasters are for — they are the audit trail that makes a modified ground honest: the
  directory name says the product is different, the manifest says how and why, and the
  deltas prove exactly which cells moved and by how much. `Tools/blender/tests/test_conform.py`
  reconstructs the survey from them and compares it byte for byte.
* `conform_clamped.json` — the runs where the ground wanted to move more than the clamp
  (1,554 on Thanet; 204 over 5 m). These are cuttings, cliff edges and promenades under
  cliffs, where flattening the ground is the wrong answer; the list is the input to
  Renderer B's embankment / retaining-wall segments.
* The pass refuses to run when source and destination are the same path, and refuses a
  manifest that already carries a `conform` block, so it can never be applied twice.
* **Who reads which.** The Unreal landscape import reads `landscape_conformed`. Everything
  that samples ground height for the road itself — the splines, the Blender driver's
  `--terrain`, both test suites — reads `landscape`, because the road drapes on the survey
  (`projects/one/docs/BRIEF.md` §1.1). That is what stops the burn feeding back into the
  road it was burned from.

## Writing an adapter

Read the manifests, not the config. Subtract `origin` if you want local coordinates; swap
axes if you want Y-up; `np.flipud` a raster if your engine's row 0 is south; convert
`bearing` to your rotation convention; add your own draw-order lifts and bridge decks.
Put all of it in one file under `sources/adapters/` and none of it anywhere else.
Honour `clip`: treat terrain NoData as absence, not elevation; expect ground-cover cells
that sum to 0; expect rail and barrier layers beside roads. `sources/adapters/unreal.py` is
the Streetscape-frame adapter (local metres, Y north, Z ODN) for Unreal and Blender; it
additionally reads `derived/<site>.gpkg` for the raw OSM way geometry and tags, the one
product not in `out/`.
