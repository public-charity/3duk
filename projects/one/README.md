# Project One — the Isle of Thanet, as a base to build on

This is a walkable, flyable model of the Isle of Thanet in **Unreal Engine 5.8**, built entirely from public
data (Environment Agency 1 m LIDAR and OpenStreetMap) by a deterministic pipeline: every mesh in it is
generated from data, none of it modelled by hand. The isle is cut from the mainland along a straight line between Minnis Bay and Pegwell Bay,
and on top of the terrain a reusable **Streetscape** plugin grows roads, kerbs, pavements, markings, walls,
fences, railings, hedges and railway track from one shared spline plus **profile JSON** — so a new road type
or a new kerb is a data file, not a C++ class. Everything here is reproducible from the raw data by the
commands in [Rebuilding it from nothing](#2-rebuilding-it-from-nothing), and every number below was read out of
a manifest or printed by a command that is quoted next to it.

**Read this too.** `docs/BRIEF.md` is what was asked and what is binding (section 4); its section 9 is the
state at the end of this build, including the open defects. `docs/STAGES.md` §0 is the only status record.
`docs/DESIGN.md` says why each thing is the way it is; `docs/SCHEMA.md` + `schema/` is the interchange format;
`docs/TERRAIN_ROADS.md` is the terrain/road-fusion diagnosis and the fix that came out of it.

---

## 1. What exists today

Numbers are quoted from the file or command named beside them. Paths are relative to the repo root
`C:/Users/Shadow/code/3duk`. `<DATA>` = `data/thanet/out/unreal`.

### 1.1 Terrain — the survey

| | | source |
|---|---|---|
| Tiles exported | **391** of 494 grid positions, 512 m each, 513 × 513 samples at 1 m (neighbours share an edge row) | `data/thanet/out/terrain/terrain_manifest.json` |
| Grid | origin E 627680 N 163080, 26 × 19 tiles → 13313 × 9729 samples (13.3 km × 9.7 km) | same |
| Elevation | **−3.08 .. 59.62 m ODN**; steepest cell **86.3°**, 0.209 % of cells over 45° | same (`range_m`, `slope_qa`) |
| Never surveyed | **14,601,593 cells (11.273 %)** of the mosaic had no LIDAR — open sea and offshore. Filled nearest-valid **once over the whole site mosaic**; reach p50 319.8 m, max 1378.8 m | same (`fill`) |
| Wholly invented tiles | **28** tile positions had no surveyed cell at all — **7,368,732 cells, 7.3 km²** — listed as `tiles_fabricated` | `terrain_manifest.json`, step-05 WARNING in `Saved/Logs/thanet_05.log` |
| Tile seams | **737** neighbouring pairs, **378,081** shared samples, **0 disagree, max 0.0 m** | `terrain_manifest.json` `shared_edges` |

The seam number is the round's first repair. Before it, the same audit found **28,725 shared samples
differing by up to 5.34 m** (and 10.95 m counting ground behind the cut), because each tile filled its own
NoData from its own neighbourhood. Step 05 now assembles the site once and fills once, and refuses to exit 0
if any shared sample disagrees.

### 1.2 The cut

Half-plane from **Minnis Bay (E 628512, N 169680)** to **Pegwell Bay (E 635496, N 163609)**, keeping the
north-east side; **9,253.83 m** long (`Saved/Tests/landscape_import_conformed.json` → `clip.length_m`). Both
endpoints were reprojected through the OSTN15 grid, not the Helmert fallback (which lands ~2 m away).

* **103** grid positions lie wholly outside and have no file; **3,861,822** cells inside kept tiles are
  outside the cut and are written as NoData −9999 (`terrain_manifest.json`).
* **31** straddle tiles carry a visibility ramp (`<DATA>/landscape/vis_x*_y*.r8`), so in the engine the edge
  is the exact line, not a staircase of missing components.
* In-engine check: 20 probe points just inside the line all return a height, 20 just outside all return none —
  `clip.pass true`, `kept_side_ok 20`, `cut_side_ok 20` (`Saved/Tests/landscape_import_conformed.json`).

### 1.3 Buildings (massing — grey boxes, by design)

**20,121** buildings in **216** per-tile actors; 3,278 footprints outside the cut were dropped
(`data/thanet/out/massing/massing_manifest.json`). Heights: LIDAR p50 for 19,710 of them, with a height
calibration re-fitted on Thanet's own buildings — **1.385 + 2.646 × levels**, n 2948, 176 rejected,
rmse **1.21 m** — and 2 landmark overrides. In the level: 222,440 verts / 364,007 tris
(`Saved/Logs/full_import3.log` census).

### 1.4 Roads, rail and barriers — the data

| layer | count | length | source |
|---|---|---|---|
| roads (step 06) | 14,468 tile segments, 1,841 junctions, 246 tiles | **1,173.19 km** | `data/thanet/out/networks/networks_manifest.json` |
| rail (step 11) | 282 segments over 45 tiles; classes `rail` 171, `miniature` 2; gauge defaulted on 7 | **80.68 km** | `data/thanet/out/networks/linear_manifest.json` |
| barriers (step 11) | 2,354 segments over 145 tiles: fence 1,089, wall 773, hedge 162, retaining_wall 43, kerb 24, guard_rail 2 | **134.37 km** | same |

Rail did not exist in the original Margate extract; the Overpass query gained `way["railway"]` for Thanet and
the extract carries 262 railway ways and 2,272 barrier ways (`sources/provenance/thanet.osm.json` `counts`).

### 1.5 The streetscape documents (the interchange)

**246** per-tile documents under `<DATA>/streetscape/`, holding **15,422 splines** — roads 12,815, rail 282,
barriers 2,325 — thinned from 640,661 OSM vertices to 114,008 control points with a **maximum deviation of
0.10 m** from the interpolant, plus 1,642 junctions
(`<DATA>/streetscape/streetscape_manifest.json`). Each document inlines the profiles its splines name, so one
document is a complete, self-contained build.

### 1.6 The landscape in Unreal

Imported from the **conformed** heightmaps (see 1.8): **2,067 components** (53 × 39 at 127 quads × 2
sections), **140** World Partition streaming proxies (grid size 4), padded to 13463 × 9907 (150 columns east,
178 rows north) with fill h16 32691 = −0.6016 m, actor at (0, −990600, 0) cm, scale (100, 100, 100). Import
took **342.2 s** over 12 regions, peaking at 16.7 GB RSS.
(`Saved/Tests/landscape_import_conformed.json`.)

Two probes in the same run:

* **13,452** lattice points compared between the imported `ALandscape` and the heightfield the splines
  sample: **max |dz| 0.000645 m**.
* Cliftonville cliff, tile (17, 16): **81.56°** by central difference in-engine against the pipeline's
  recorded 81.7° for that tile — the cliffs survived the import.

### 1.7 The streetscape network in the level

The saved level `/Game/Thanet/Maps/Thanet` holds (`Saved/Tests/d5_assert_final.json`, an assertion pass that
re-opens the map in a fresh commandlet and counts what streams in):

| | |
|---|---|
| `AStreetscapeActor` | **15,423** (15,422 from the 246 documents + 1 authored test stretch) |
| `AStreetscapeMassingActor` | **216**, 20,121 buildings |
| Landscape | 1 actor + **140** `LandscapeStreamingProxy` |
| External-actor packages on disk | **15,789**; `Content/` is **2.2 GB** |
| Network built | **1,072.4 km**, 745,642 stations, 19,705,600 verts, 29,006,476 tris, 20,700 marking strips, 575,381 instances (464,753 leaf cards, 76,715 sleepers, 30,164 round posts, 3,749 square posts) — `Saved/Logs/full_import3.log` census, which excludes the authored stretch |

Streaming works: a 1,400 m box over Cliftonville streams **1,264 actors** — 1,100 roads, 153 barriers, 10
rail, 1 authored — 69.5 km of network in 11.5 s (`Saved/Tests/d5_census_cliftonville.json`). Before an
actor-bounds fix landed in this round the same box pulled **`"actors": 124, "actors_by_layer": {"authored":
1, "barriers": 113, "rail": 10}`** — **not one road** (`Saved/Logs/d5_census_local.log`): our meshes are
deliberately not serialised, so World Partition filed every road actor under an empty bounding box, and only
the barriers and rail escaped because their instanced-mesh components keep real bounds.

### 1.8 Roads against terrain — the headline repair, and what is still wrong

The road surface sits on a **smoothed** terrain curve (BRIEF 1.1 forbids following raw LIDAR point for point)
while the landscape carried the **raw** survey, so the ground erupted through the carriageway. Measured over
every road and rail spline of the isle, both before and after:

| whole-isle measure, 13,096 splines / 666,314 stations / 968.8 km | before | after |
|---|---|---|
| stations with terrain above the built surface | **565,545 (84.88 %)** | **0** |
| carriageway penetrated | **826.693 km** | **0.000 km** |
| worst penetration | **13.826 m** | **0.000 m** |
| worst against the landscape's own triangulation | — | 0.002537 m |
| median clearance under the surface | −0.047 m | +0.031 m |

Command, re-run for this README today:

```bash
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/road_fusion_audit.py \
  --landscape C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape_conformed \
  --gate-m 0.005 --float-gate-m 0.125 --out <json>
# GATE PASS: worst penetration 0.000000 m (allowed 0.005000); float over 0.125 m at 5.4311% of stations,
# worst float 13.075507 m
```

The fix is a new deterministic pass (`Tools/conform_landscape.py`) that writes a **separate** product,
`<DATA>/landscape_conformed/`, in which the ground under the road corridor is the road: 13,096 splines
burned, 12,697,333 cells changed (12.70 km²), |Δ| p50 0.078 m / p95 0.430 m / p99 1.328 m, worst fill
+17.38 m and worst cut −14.66 m, 1,554 clamped runs, 811.6 s
(`data/thanet/out/unreal/landscape_conformed/landscape_manifest.json` → `conform`,
`Saved/Diag/conform_report.json`). The survey products are never written; per-cell `conform_delta_*.r16`
rasters make the change fully reversible.

**Two things are still wrong, and they are the reason this README does not claim the job is finished:**

1. **The landscape still draws through the carriageway at ordinary viewing distances.** The data is right
   (zero penetration above), but the corridor is sunk only 0.03 m, which is thinner than the landscape's
   *rendered* surface at range, so green wedges cut across the road. See `Saved/Diag/d5_top_margate_street.png`
   and `Tools/ue/shots/isle_street_margate.png`, where the street is barely visible at eye level. The one
   clean frame (`Tools/ue/shots/conform_flat_margate.png`) was captured with the landscape's LOD pinned,
   which is not how the level runs. This is exactly the defect Alex reported, and it is not closed.
2. **Roads float.** Corridor arbitration takes the *minimum* of two crossing surfaces, so where corridors
   overlap the cell goes to the lower one and the higher road is left standing above the ground: **5.43 % of
   stations (42.7 km)** are more than 0.125 m clear, worst 13.08 m, concentrated in steps (57 % of their
   stations), cycleways (24 %) and rail (18 %). You can see it as black voids under the near kerb in
   `Tools/ue/shots/isle_seafront_westgate.png`. The 1,554 clamped runs are recorded in
   `landscape_conformed/conform_clamped.json` for Renderer B to build as embankments and retaining walls;
   until they are built, the gate's `--float-max-frac 0.06` is a regression detector calibrated to today's defect, not an
   acceptance criterion.

### 1.9 Parity: the same document, two engines, the same numbers

The Blender/numpy geometry core and the C++ renderers are held to the same output. On the authored test
stretch (`schema/examples/test_stretch.json`, Trinity Square, Margate) `Tools/ue/compare_stats.py` compares
**81 rows** and finds **0 mismatches**, both on the freshly imported actor and after the level was saved and
re-opened (`Saved/Tests/parity_trinity_square.json`, `..._reopened.json`): length **171.405484 m**, 116
stations, road-over-kerb overlap **0.040 m** min and max on both sides, road buffer 1,794 verts / 2,756 tris,
**31** marking strips, 18 round + 23 square posts, 1,650 leaf cards.

Rebuilt today from the committed reference with the pipeline python, against the conformed landscape:

```
authored:trinity_square: L=171.405 N=116 overlap=0.04/0.04 strips=31
  buffers={'road': (1794, 2756), 'edge_left': (1508, 2318), 'edge_right': (2696, 3448), 'hedge_right': (364, 724)}
  instances={'post_round': 18, 'post_square': 23, 'leaf_card': 1650}
```

— identical to `Tools/blender/renders/trinity_square.stats.json`, the frozen reference.

### 1.10 Geo-registration

* **Datum**: PROJ resolves OSGB36 ↔ WGS 84 through the **OSTN15 grid, 1 m accuracy class** —
  `"Inverse of OSGB36 to WGS 84 (9) + British National Grid, 1 m"`
  (`sources/provenance/thanet.osm.json` → `datum_transformation`). The Helmert fallback would put OSM about
  1.8 m off the LIDAR; step 01 refuses it (`crs_max_transform_accuracy_m 1.0`).
* **Three frames, one conversion point each** (BRIEF 4.2): survey (EPSG:27700 / ODN) → Streetscape JSON
  (local metres, X east, Y north, Z up) → Unreal (cm, X east, **Y south**, Z up). Worked example asserted by
  the adapter tests: `(635253.6, 171027.6, 17.2) → (7573.6, 7947.6, 17.2) → (757360, −794760, 1720) cm`,
  bearing 131° → yaw 41°.
* **Height encoding**: `h16 = round(z·128) + 32768`. Measured over **99,037,257 surveyed cells**, the worst
  disagreement between the 16-bit landscape tiles and the source GeoTIFF is **0.00390625 m** — exactly half
  the 1/128 m quantum, i.e. the encoding floor (`<DATA>/landscape/landscape_manifest.json` →
  `heightmap.roundtrip_measured`).
* **Regression against the previous model**: of the 795 Margate output files snapshotted before the first
  edit to `sources/`, **794 are byte-identical**; all **91 terrain rasters** are byte-identical (re-hashed for
  this README). The single difference is `terrain/terrain_manifest.json`, which gained one key,
  `shared_edges`. See the caveat in [Known limitations](#6-known-limitations-and-what-is-deliberately-not-done).

### 1.11 The test estate, run for this README

| check | command | result |
|---|---|---|
| pipeline dry run | `python sources/tests/dryrun.py` | **167 passed, 0 failed** |
| adapter | `python sources/tests/test_unreal_adapter.py` | **47 tests, OK** |
| geometry core (numpy) | `python -m unittest discover -s projects/one/Tools/blender/tests -p "test_*.py"` | **115 tests, OK** |
| C++ build | `Tools/build.ps1` | **Result: Succeeded** |
| Unreal automation | `Tools/ue/run_ue_tests.ps1 -Filter Streetscape` | **26 completed, 26 passed, 0 failed, 33 s** |
| road/terrain fusion | `Tools/road_fusion_audit.py` | **GATE PASS**, worst penetration 0.000000 m |

---

## 2. Rebuilding it from nothing

Shell is Git Bash from the repo root. Two absolute rules, each of which has cost hours:

```bash
cd /c/Users/Shadow/code/3duk
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"   # the /c/ form; a C:/ entry is invisible to bash
PY=C:/Users/Shadow/code/3duk-env/env/python.exe                     # the ONLY python for pipeline/adapter/numpy
```

`python` and `python3` on PATH are broken Microsoft Store stubs. Without the `Library/bin` entry, GDAL
disappears and numpy's LAPACK dies **silently**.

| # | step | command | time |
|---|---|---|---|
| 1 | reuse Margate's 182 LIDAR rasters | `$PY sources/fetch/reuse_tiles.py --from margate --to thanet` | seconds |
| 2 | OSM extract (Overpass) | `PY=$PY SITE=thanet ./sources/run.sh --only 01` | minutes; skipped when the extract is on disk |
| 3 | LIDAR fetch, 782 rasters / 3.9 GB | `PY=$PY SITE=thanet ./sources/run.sh --only 02` | ~5 min (494 positions measured at 311 s) |
| 4 | VRT mosaic + coverage QA | `... --only 03`, `... --only 04` | minutes |
| 5 | **terrain export, the clip and the seam fix** | `... --only 05` | minutes — it assembles the 13313 × 9729 site once, fills the nodata with **one** distance transform, then cuts out 391 tiles |
| 6 | networks, massing, coast, furniture, linear features | `... --only 06`, `07`, `09`, `10`, `11` | minutes each |
| 7 | Unreal adapter (heightmaps, masks, weights, 246 documents, massing, furniture) | `SITE=thanet $PY sources/adapters/unreal.py` | minutes |
| 8 | **conform the landscape to the roads** | `$PY projects/one/Tools/conform_landscape.py --landscape <DATA>/landscape --streetscape <DATA>/streetscape --out <DATA>/landscape_conformed` | **811.6 s (13.5 min)** |
| 9 | compile the C++ | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/build.ps1` | minutes (incremental: seconds) |
| 10 | **build the whole level, one command** | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/00_build_level.ps1 -Recreate` | **the long one — allow an hour** |

Step 10 is six commandlets in the only order that works, and it ends by re-opening the saved map in a fresh
process and counting what is actually in it against the adapter's own manifests. Measured pieces:
bootstrap (materials, 20 profile DataAssets, the World Partition map); **landscape import 342.2 s**;
the authored test stretch + `PlayerStart`; **massing 281.7 s** for 216 actors; **the site streetscape import
914.9 s** as a single commandlet (purge of the previous 15,423 actors 275.8 s, build 261.0 s, save 374.0 s,
peak 21.9 GB of 28 GB RAM — `Saved/Logs/full_import3.log` → `timing`) —
the script's default splits it over 12 slices to keep memory bounded, which its own header estimates at ~1 h.

Two things that will bite you:

* Every `UnrealEditor-Cmd` run on this machine exits non-zero. `Tools/ue/run_ue_python.ps1` and
  `run_ue_tests.ps1` derive the real verdict from the log (`THANET_OK` / `Test Completed. Result={Success}`)
  and are the only supported way to run these scripts. See the caveat in section 6 — the override is
  currently hiding a real crash on shutdown.
* Nothing under `projects/one/Content/` is committed. It is regenerated by step 10 and it is 2.2 GB.

Smaller loops, for when you are working on one thing:

```bash
# just the geometry, no engine, no Blender: builds every spline of one document to .npz + stats.json
PYTHONPATH=projects/one/Tools/blender $PY -m streetscape.build \
  --site  projects/one/schema/examples/test_stretch.json \
  --terrain data/thanet/out/unreal/landscape_conformed \
  --out   projects/one/Tools/blender/out/test_stretch

# the same document through Blender, with glTF and the three fixed cameras
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b \
  --python projects/one/Tools/blender/streetscape/blender_main.py -- \
  --site <doc> --terrain <landscape dir> --out <dir> --gltf --render
```

---

## 3. Opening it and walking around

```bash
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" \
  C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject
```

It opens on `/Game/Thanet/Maps/Thanet` (set as both `EditorStartupMap` and `GameDefaultMap`) with the
landscape streaming in through World Partition. Press **Play**: the game mode is
`/Script/Thanet.ThanetGameMode` and the pawn `/Script/Thanet.ThanetExplorerPawn`, spawning at the
`PlayerStart` on the test stretch (all three verified in the level by
`Saved/Tests/d5_assert_final.json`).

| key | |
|---|---|
| **W A S D**, mouse | walk / look — 300 cm/s, capsule 34 × 88, step height 45 cm so the 12.5 cm kerb is climbable |
| **Shift** | sprint (walk × 2.5; flying 6000 cm/s) |
| **F** | toggle flying (1500 cm/s) |
| **Space / Left Ctrl** | up / down while flying |
| **O** | show / hide the magenta OSM debug overlay |

*(Bindings read from `Source/Thanet/ThanetExplorerPawn.cpp`; Enhanced Input objects are built in C++, there is
no input asset to hunt for.)*

**What was and was not verified.** Walkability was proved headlessly, not by a human at the keyboard: 881 of
881 downward traces over a sample of 16 road actors were blocked by the street mesh, and the landscape was
strictly below it at every one of them (closest approach **0.0269 m**,
`Saved/Logs/d5_clearance3.log`). Play-In-Editor itself was **not** exercised in this round — see section 6. If you want to look without the editor, the headless screenshot tool takes any camera:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 \
  -Script 05_screenshot.py -Args "--x 7573.6 --y 7947.6 --z 80 --yaw 41 --pitch -30 --out <png>" -Render
```

Existing captures are in `Tools/ue/shots/` (isle, seafront, rail cutting, streets, the clip edge) and
`Saved/Diag/`. Read section 1.8 before you trust the street-level ones.

---

## 4. The point of the system: a new road type, kerb, fence or hedge **without writing code**

One spline is the source of truth; three renderers read it (A road surface, B kerb/pavement/barriers,
C volumetric hedge). What varies between a residential street, a trunk road, a promenade and a railway is
**profile data and s-ranged segments**, never a new class. There are 20 profiles in `schema/profiles/`
today — 13 road-kind, 6 edge-kind, 1 hedge — and the adapter maps every OSM class onto one of them in
`sources/adapters/unreal.json` → `road_profile_by_class`.

There are two places to put a change, and they do different jobs:

* **In one document** (`<DATA>/streetscape/site_x*_y*.json`, or an authored file like
  `schema/examples/test_stretch.json`): add the profile under `profiles.<kind>.<id>` and point a spline's
  `profile_ids` at it. Rebuild that document. Nothing else in the isle changes.
* **In the library** (`schema/profiles/<id>.json`) plus one line of
  `sources/adapters/unreal.json`: every OSM way of that class picks it up at the next adapter run, and
  `Tools/ue/01_bootstrap.py` turns it into a `UDataAsset` for the editor.

### 4.1 Worked example — run end to end for this README

Take the Trinity Square test stretch and, **by editing JSON only**, give it a new road type, a new kerb, a
railing and a hedge. Copy the document somewhere writable (`projects/one/Saved/` is git-ignored):

```bash
mkdir -p projects/one/Saved/DocExample
cp projects/one/schema/examples/test_stretch.json projects/one/Saved/DocExample/boulevard.json
```

Then, in that file:

**(a) a new road type.** Add to `profiles.road` — the fields are the whole spec of a carriageway: width,
camber, and the marking list. Markings are *rows on the road profile*, not a second renderer:

```json
"road_boulevard": {
  "kind": "road", "lanes": 2, "lane_widths_m": [4.5, 4.5], "width_m": 9.0,
  "surface_material": "tarmac",
  "camber": { "kind": "parabolic", "crossfall_pct": 2.0 },
  "overlap_m": 0.04, "skirt_drop_m": 0.02, "lateral_station_spacing_m": 1.0,
  "markings": [
    { "id": "centre_solid", "anchor": "centre",     "offset_m": 0.0,  "width_m": 0.1,
      "pattern": "solid",  "material": "white_paint",  "lift_m": 0.004 },
    { "id": "dyl_right",    "anchor": "edge_right", "offset_m": 0.25, "width_m": 0.1,
      "pattern": "double", "double_gap_m": 0.1, "material": "yellow_paint", "lift_m": 0.004 }
  ]
}
```

**(b) a new kerb variant.** Add to `profiles.edge` — start from `schema/profiles/edge_uk_kerb.json` and
change three numbers: a 250 mm kerb with a 180 mm upstand and a 3 m footway.

**(c) a fence and (d) a hedge** — both are `segments[]` entries on the same spline, in arc-length metres, so
they stack against each other instead of stacking tools:

```json
{ "id": "railing_left",  "s0_m": 100.0, "s1_m": 160.0, "side": "left",
  "edge":  { "profile_id": "edge_railing" } },
{ "id": "hedge_left_run","s0_m": 100.0, "s1_m": 160.0, "side": "left",
  "hedge": { "present": true } }
```

Finally point the spline at the new profiles:

```json
"profile_ids": { "road": "road_boulevard", "edge_left": "edge_uk_kerb",
                 "edge_right": "edge_uk_kerb_high", "hedge_left": "hedge_privet",
                 "hedge_right": "hedge_privet" }
```

Validate, then rebuild:

```bash
$PY projects/one/Tools/blender/tests/schema_check.py projects/one/Saved/DocExample/boulevard.json
# VALID projects/one/Saved/DocExample/boulevard.json

PYTHONPATH=projects/one/Tools/blender $PY -m streetscape.build \
  --site   C:/Users/Shadow/code/3duk/projects/one/Saved/DocExample/boulevard.json \
  --terrain C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape_conformed \
  --out    C:/Users/Shadow/code/3duk/projects/one/Saved/DocExample/out
```

What changed, measured from the two builds' `stats.json` and `.npz` (left column is the unedited stretch
built the same way, right column after the JSON edit — **no code was touched**):

| | before | after |
|---|---|---|
| carriageway width | 6.0 m (`w_max` 7.0 at the taper) | **9.0 m**; road ribbon reaches ±4.54 m from the centreline (±3.54 before) |
| marking strips | 31 (TSRGD 1004 centre dashes over 171 m, plus the two double-yellow lines for s 0-60) | **3** (one solid centre line + one double yellow) |
| right-hand edge lateral reach | 5.125 m | **7.990 m** (wider kerb + wider footway + wider road) |
| railing on the left | — | **+31 square posts** (23 → 54): exactly 60 m ÷ the profile's 2.0 m post pitch, + 1 |
| hedge on the left | — | a **new `hedge_left` buffer**, 518 verts / 1,032 tris; leaf cards 1,650 → 4,486 |
| **road-over-kerb overlap** | 0.040 m min = max | **0.040 m min = max** — the seam rule survives all of it |

Two things worth noticing. The schema validator rejected the first attempt with
`edge-anchored marking needs offset_m >= 0` before anything was built — the format is checked, not trusted.
And a per-point `width_m` on the spline **overrides** the profile's width, which is why the example clears
them: point overrides win over profile defaults, everywhere.

The same file drives Blender and Unreal with no conversion, and both were run for this README:

```bash
# renders (three fixed cameras, EEVEE)
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b \
  --python projects/one/Tools/blender/streetscape/blender_main.py -- \
  --site <boulevard.json> --terrain <landscape_conformed> --out <dir> --render
# STREETSCAPE_OK version=0.1.0 splines=1 problems=0   (3 camera PNGs written)

# into the engine (no --save, so the saved level is untouched)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 \
  -Script 03_import_streetscape.py -Args "--json <boulevard.json> --stats-out <ue_stats.json>"
# THANET_OK 03_import_streetscape {"actors": 1, ... "elapsed_s": 313.8}

$PY projects/one/Tools/ue/compare_stats.py --ue <ue_stats.json> --numpy <out>/…/stats.json
# 90 rows compared, 1 mismatch(es) -> PARITY FAIL
```

That last line is the honest result and it is worth reading carefully. Of 90 compared rows, **89 match
exactly** — length, 118 stations, both overlaps at 0.040, every buffer's vertex, triangle, per-material and
per-group count including the brand-new `hedge_left`, the marking strips, the round and square post counts,
and station identity across all five buffers. The one difference is **leaf-card instances: 4,483 in Unreal
against 4,486 in numpy, 0.07 %** — the seeded per-triangle card scatter on a hedge configuration the frozen
fixtures do not cover (the committed test stretch has a hedge only on the right, and scores 81 rows with 0
mismatches). It is recorded as an open defect in `docs/BRIEF.md` §9; it was found by writing this section,
which is the point of running your documentation rather than typing it.

### 4.2 The same trick, for the whole isle

To make `road_boulevard` the profile for, say, every `secondary` road on Thanet, put the file in
`schema/profiles/road_boulevard.json` in the shape `{"kind": "road", "id": "road_boulevard", "profile": {…}}`,
change one line in `sources/adapters/unreal.json`:

```json
"road_profile_by_class": { … "secondary": "road_boulevard", … }
```

and re-run steps 7 and 10 of section 2. The adapter inlines the new profile into all 246 documents and the
level import rebuilds every affected actor. *(This paragraph describes the mechanism the adapter already
implements and uses for the current 20 profiles; the section 4.1 example is the one that was run end to end
for this README.)*

**What you may not do** (BRIEF 1.1, and the tests enforce it): a renderer per marking type, per fence type or
per kerb width; a second spline stacked on the carriageway for paint; pavement inside the road renderer;
hedges inside the edge renderer. `grep -c "double_yellow\|centre_dash" Tools/blender/streetscape/road.py`
returns 0 and is meant to stay 0.

---

## 5. How the pieces fit

```
   EA LIDAR (WCS)   OpenStreetMap (Overpass)
          |                   |
          v                   v
   sources/derive/01..11  ── engine-neutral: EPSG:27700, ODN metres, north-up.
          |                   Knows nothing about any engine. Margate stays byte-identical.
          v
   data/thanet/out/{terrain,networks,massing,coast,furniture}
          |
          v
   sources/adapters/unreal.py ── the ONE place that knows about Unreal-adjacent products:
          |                       16-bit heightmaps + masks + weightmaps, and the
          |                       Streetscape JSON documents (local metres, X east, Y north, Z up)
          v
   data/thanet/out/unreal/{landscape, streetscape, massing, furniture}
          |                        |
          |                        +--> Tools/conform_landscape.py --> …/landscape_conformed
          |                             (the ground under the roads; the survey is left alone)
          v                        v
   Tools/blender/streetscape   Plugins/Streetscape (C++)
   pure numpy geometry core     the same algorithms, ported line for line
   + a thin bpy layer           spline -> Renderer A / B / C -> UDynamicMeshComponent
          |                        |
          +----- compare_stats ----+   81 rows, 0 mismatches
                                   |
                                   v
                          /Game/Thanet/Maps/Thanet
                          landscape + 15,423 street actors + 216 massing + the explorer pawn
```

The rules that keep it honest, all of them enforced by tests rather than by convention: nothing in
`sources/derive/` may learn about an engine; the ×100 / Y-flip to Unreal happens only inside the plugin's
loader and the landscape importer; the numpy core and the C++ port are diffed against the same frozen
fixture file (`Tools/blender/tests/fixtures/expected.json`); and Margate — the model this pipeline was
originally calibrated on — must stay byte-identical after every change.

---

## 6. Known limitations, and what is deliberately not done

**Open defects** (severity as recorded in `docs/BRIEF.md` §9):

1. **[blocker] The landscape draws through the roads at ordinary viewing distance.** Section 1.8. The data
   is right and the picture is wrong; this is the defect Alex reported and it is still visible in this
   round's own captures.
2. **[major] Roads float where corridors cross.** Section 1.8: 5.43 % of stations more than 0.125 m clear,
   worst 13.08 m, black voids under kerbs. That is the audit's own measure (worst point of the section per
   station); a separate verification pass that asked instead whether the ground is more than a kerb-height
   below *anywhere* across the section put it at 16.4 % of stations, max 2.46 m. The embankments and
   retaining walls that would close the gap are recorded in `conform_clamped.json` and not built.
3. **[major] The conformed landscape is invisible in the pipeline's own index.** `<DATA>/unreal_manifest.json`
   lists landscape / streetscape / massing / furniture and **not** `landscape_conformed`, and `sources/OUTPUT.md`
   does not mention it (`grep -c landscape_conformed sources/OUTPUT.md` → 0). The product the engine actually
   imports is announced only by its own manifest.
4. **[major] That manifest carries a stale `heightmap.roundtrip_measured` block** copied from the survey
   product, whose note invites a consumer to assert the ground matches the survey — which is false by up to
   17.38 m in the corridor, and contradicts the honest `heightmap.semantics` line three keys later.
5. **[major] The Margate byte-identity gate cannot return a clean pass.**
   `./sources/tests/regress_outputs.sh compare margate baseline_2026-09-08` prints
   `794 identical, 788 added (allowed), 1 problems`, the one problem being `terrain/terrain_manifest.json`'s
   new `shared_edges` key; against the later `before` snapshot it prints `1497 identical, 86 problems`,
   which are the four manifests plus 83 adapter documents whose `generator` string embeds the current commit.
   All **91 terrain rasters are byte-identical** (re-hashed for this README) — the *products* are intact, but
   the gate as written now reports a difference every run, so it can no longer catch a real one.
6. **[major] The headless runner hides a crash.** `Tools/ue/run_ue_python.ps1` overrides a non-zero engine
   exit when the script succeeded and the only counted error is a VC++ redistributable advisory. Counting the
   logs: **43 runs were overridden from exit −1073741819 (0xC0000005, access violation)** and only 12 from
   exit 1, the advisory's own code. The scripts' work completed (`THANET_OK`, and the saved level asserts
   correct), but something is faulting on shutdown and the message says otherwise.
7. **[minor] Blender/Unreal parity has a 0.07 % hole in leaf-card scatter.** Section 4.1: a hedge on the
   left of a spline produced 4,486 cards in numpy and 4,483 in C++. Every other row of that comparison, and
   all 81 rows of the committed test-stretch comparison, match exactly.
8. **[minor] Play-In-Editor was never exercised in this round.** Walkability rests on the headless evidence
   in section 3. The GUI checks of `STAGES.md` stage 8 — Play, the Tools > Streetscape menu, the MCP port —
   have not been run, which is why stage 8 reads `in progress` and not `done`.

**Deliberately not done** (BRIEF 5 / DESIGN 7, 10, 15 — these are scope, not defects):

* **Buildings are grey extruded footprints.** No facades, no roofs beyond a flat top, no seafront hero
  assets. The brief puts them last, and low-quality seafront LIDAR means they must be procedural, not
  sculpted.
* **No junction geometry.** Step 06's junction discs are carried through the schema as `junctions[]` and
  referenced by spline ends, but no renderer reads them: two roads meeting is two ribbons overlapping.
* **No Nanite, no HLOD bake, no packaged build.** The level is an editor artefact.
* **28 tile positions (7.3 km²) are invented ground**, not survey — offshore, filled from the nearest
  surveyed cell, which can be over a kilometre away. They are listed as `tiles_fabricated` in the manifest;
  a consumer that cares must mask or water-fill them.
* **Furniture is a token**: 52 objects placed (`data/thanet/out/qa_furniture.json`).
* **The overlay is a debug layer.** OSM is a snap target and a reference, never the final mesh (BRIEF 1.1).

---

## 7. Layout

```
projects/one/
  Thanet.uproject                UE 5.8 C++ project "Thanet"
  Source/Thanet/                 explorer pawn + game mode (that is all the game module does)
  Plugins/Streetscape/           the reusable plugin: Streetscape (runtime) + StreetscapeEditor
  Plugins/UnrealMCP/             source-only copy of the 5.8-ported MCP bridge (port 55558; off in commandlets)
  Config/                        DefaultEngine/Game/Input/Editor .ini
  Content/                       GENERATED by Tools/ue (2.2 GB, git-ignored); the scripts are the source of truth
  schema/                        streetscape.schema.json, profiles/*.json (20), examples/*.json
  Tools/blender/streetscape/     the numpy geometry core + the bpy layer and renderers
  Tools/blender/tests/           115 numpy tests and the frozen fixtures the C++ tests also read
  Tools/conform_landscape.py     the road-corridor conform pass
  Tools/road_fusion_audit.py     the whole-isle penetration/float gate
  Tools/ue/                      headless editor Python + the PowerShell runners (see Tools/ue/README.md)
  Tools/build.ps1                UBT build of ThanetEditor Win64 Development
  docs/                          BRIEF, DESIGN, SCHEMA, UE_PLAN, PIPELINE_CHANGES, STAGES, TERRAIN_ROADS
```

Outside `projects/one/`: the pipeline is `sources/` (steps, `lib.py`, adapters, tests, `OUTPUT.md` — the
output contract), and the data is `data/thanet/` (raw 3.9 GB, out 1.2 GB), untracked and re-fetchable.

## 8. State

`docs/STAGES.md` §0 is the only status record; `docs/BRIEF.md` §9 records what is true at the end of this
build, the open defects above with their severity, and the three things to do next. Nothing is called done
in either place without the command that proved it.
