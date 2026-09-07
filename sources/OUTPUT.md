# Output contract

What the pipeline writes into `data/<site>/out/`, and what a consumer may rely on.
Verified by `sources/tests/dryrun.py`. Change this document and the test together.

## Conventions that hold everywhere

| | |
|---|---|
| **CRS** | The site config's `crs` (Margate: EPSG:27700, British National Grid). Every coordinate below is an easting/northing in this CRS, in **metres**. No local origin is subtracted. |
| **Elevation** | Metres above the site's `vertical_datum` (Margate: ODN). Always the **third** component of a vertex, or a field named `z`/`base_z`. Never Y-up. |
| **Orientation** | `bearing`: degrees clockwise from grid north, `[0, 360)`. |
| **Rasters** | GeoTIFF, **north-up** (row 0 is the northern edge), georeferenced, CRS-tagged. |
| **Tiles** | `x{i}_y{j}`: `i` counts east from `origin.E`, `j` counts north from `origin.N`, each `tile_m` metres. A feature belongs to the tile containing its centroid (buildings, furniture) or is split at tile boundaries with the seam vertex duplicated on both sides (roads). |
| **Manifests** | Every product directory has one `*_manifest.json` recording `site`, `crs`, `origin`, `tile_m` and every parameter the step ran under. Read it before the data. |
| **null** | Means *unknown*, never zero. A `null` elevation is "we have no measurement here" — drape it yourself. |
| **`src`** | Where a value came from. Filter on it. Nothing is invented without saying so. |

Nothing here knows about any engine. `sources/adapters/unity.py` is what a consumer
that wants local Y-up coordinates and 16-bit heightmaps looks like — copy it.

## `terrain/` — step 05

`dtm_x{i}_y{j}.tif` — Float32, one band, `grid_res × grid_res` (513: 512 m + a shared
edge row, so adjacent tiles have identical borders). Nodata has been **filled**; the
manifest says how many cells and by which method per tile.

`terrain_manifest.json` — `range_m` is the true site-wide elevation range. A consumer
encoding into a fixed window must compare against it; the pipeline will not clip for you.
`fill` per tile is `none`, `nearest` (scipy present) or `median (degraded)` — treat the
last as provisional. `tiles_missing` lists grid positions that have **no tile at all**
(the source returned nothing there — beyond its coverage); do not assume they are sea.

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
counts `vertices_outside_grid` and `vertices_without_dtm`.

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
| `lidar_px` | How many LIDAR cells fell inside the footprint. Your confidence measure. |
| `roof` | OSM `roof:shape` if tagged, else `flat` for the types in tuning, else the tuning default. |
| `src` | Which rung produced `h`, in order of trust: `osm_height`, `lidar_p50`, `lidar_p50_disputed` (LIDAR disagrees with `building:levels` by more than `height_calib.dispute_m`), `lidar_lowconf` (fewer than `min_pixels` samples), `osm_levels` (`height_calib` regression, **site-specific**), `type_prior` (**no evidence at all** — a per-type guess measured at another site; see `tuning.json`), `landmark_override` (hand-authored in the site config). |
| `seed` | Stable per-building hash for deterministic variation. |
| `rings` | Exterior first, then holes. `[E, N]` pairs, closed. |

`massing_manifest.json` — `by_height_source` is the histogram of `src`;
`buildings_without_lidar` and `outside_grid` are counted. `height_calib` is the line the
`osm_levels` rung actually used, with `source` = `fitted` (regressed from this site's own
buildings that carry both `building:levels` and a trustworthy LIDAR p50 — the default),
`config` (pinned in the site config) or `fallback` (too few buildings to fit; another
site's line was used — treat `osm_levels` heights as provisional). `height_calib_fit`
gives `n`, `rejected` and `rmse_m` for a fit. If `type_prior` is a large share, the model
is describing this town with another town's building stock.

## `coast/` — step 09

`ground_x{i}_y{j}.tif` — Byte, four bands **grass, sand, rock, water** as fractions 0–255
that sum to 255, at `class_res × class_res` (256) per tile, georeferenced. Sand includes
OSM beach polygons **plus everything below `coast.foreshore_max_odn`** — a property of the
survey's tide state, recorded in the manifest. Rock is a slope ramp between
`coast.rock_slope_deg`.

**Water is the DTM's own flat surface.** The EA composite carries the surveyed water level
as a plane (measured at Whitby: −2.4 m ODN, razor-flat, 100% coverage even over open sea).
Cells within `water_tolerance_m` of `water_level` whose calmest neighbour is flat are
`water`, and are excluded from sand. That plane is not ground: a consumer that drapes a water
surface at `water_level` will z-fight it, so sink or cut the terrain under the water band.

Tiles with no DTM at all get no raster and are listed as `tiles_without_dtm`. They are added
to `water_tiles` only if the site config says `coast.missing_tiles_are_water` — whether a
no-data tile is open sea or just beyond coverage is a per-site fact, not an assumption.

`coast_manifest.json` — `water_tiles` lists `[i, j]` pairs whose lowest ground is within
`water_margin_m` of `water_level`, i.e. tiles that need a water surface; `bands`,
`thresholds`, `water_tolerance_m` and `tiles_without_dtm` are recorded.

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

## `qa_*.json`

`qa_height_outliers.json` — buildings with too few LIDAR samples or a ridge far above the
walls. `qa_furniture.json` — placement counts and every amenity kind seen, so you can find
out what else is mappable.

## Writing an adapter

Read the manifests, not the config. Subtract `origin` if you want local coordinates; swap
axes if you want Y-up; `np.flipud` a raster if your engine's row 0 is south; convert
`bearing` to your rotation convention; add your own draw-order lifts and bridge decks.
Put all of it in one file under `sources/adapters/` and none of it anywhere else.
