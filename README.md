# Virtual Margate

A walkable, real-world-accurate model of Margate, Kent, built from open data: Environment
Agency 1 m LIDAR for ground, OpenStreetMap for buildings/roads/coast, rendered in Unity 6.

The current build is a **grey-box**: correct ground, correct footprints, correct road
network, no photoreal surfacing. Part B of this document is the plan for the photoreal
layer (Gaussian splatting), which has not been built yet.

This README exists so the project can be regenerated from scratch. Read the **Caveats**
under each step before re-running anything — most of them cost hours to discover.

---

## Extent and coordinate contract

Everything keys off `pipeline/config/margate.json`. Treat it as the single source of truth;
if you change it, every downstream artefact is invalid.

| | |
|---|---|
| CRS | British National Grid, **EPSG:27700** |
| Origin | E 632800, N 168200 |
| Tiles | 13 × 7 tiles of 512 m → **6.66 × 3.58 km** (~24 km²) |
| Heightmap | 513 × 513 per tile (1 m LIDAR posts, shared edge row) |
| Unity axes | `x = E - E0`, `z = N - N0`, `y = metres ODN` |
| Terrain Y | base −5.0 m, range 60.0 m |
| Water level | −0.6 m ODN |
| WGS84 bbox | 51.365, 1.345, 51.402, 1.432 |

**The 513 rule.** Unity heightmaps must be 2ⁿ+1. 512 m tiles at 1 m LIDAR spacing give 513
samples *only if* you request a half-pixel-expanded window so pixel centres land on integer
BNG metres. Get this wrong and adjacent tiles have a seam you cannot fix in Unity.

---

# Part A — Regenerating the base world

## Quick rebuild

```bash
./run.sh              # every data step, 01 -> 09
./run.sh --from 04    # resume from a step
./run.sh --only 06    # single step
./run.sh --unity      # then drive Unity headlessly (MargateBootstrap.BuildAll)
./run.sh --list       # show the steps
```

Every step is individually resumable: 01 skips the Overpass fetch if the extract is on
disk, 02 skips LIDAR tiles already downloaded. Override the interpreter or editor path
with `PY=` / `UNITY=`.

**Verified reproducible.** Running 01→09 from the raw OSM extract and LIDAR tiles
regenerates all 267 tracked files in `data/out/` **byte-identically**. If you get diffs
there, something upstream changed — most likely a fresh Overpass pull rather than a bug.

Numbered scripts live in `pipeline/`. You can also run them individually, in order, and
check the output at each stage.

> **Caveat: there is no step 08.** It was abandoned. The numbering is preserved so log
> output and filenames agree. Steps 01 and 03 were originally undocumented manual shell
> commands; they are now scripts, which is how the `-t_srs` bug below came to light.

### 01 — Fetch OSM → GeoPackage

```bash
./run.sh --only 01                        # or: bash pipeline/01_fetch_osm.sh
```

Pulls buildings, highways, natural, landuse, leisure, waterway, man_made, barrier, plus
tree/amenity/shop/tourism nodes via `tools/fetch_osm.sh` (which falls back across three
Overpass endpoints), then converts to `data/derived/margate.gpkg` and writes a provenance
record to `data/provenance/osm.json`.

**Caveats**
- **`-t_srs EPSG:27700` is load-bearing.** Overpass returns WGS84 degrees; every downstream
  step rasterises these footprints against the BNG LIDAR grid. Omit it and steps 04/07/09
  run to completion, exit 0, print no errors — and silently sample nothing
  (`buildings with LIDAR: 0 / 7669`). There is no crash to lead you to the cause. The script
  now asserts the extent is in projected metres rather than trusting the flag.
- Overpass bbox order is **S,W,N,E** — not the order anything else in this project uses.
- The main endpoint rate-limits and times out at this size. The fallback loop is not
  optional; keep it.
- Only `points`, `lines`, `multipolygons` are emitted — the layers the pipeline consumes.
- OSM is live data. A rebuild years later will **not** reproduce the same model — footprints
  get added, retagged and split. `data/provenance/osm.json` records the SHA-256, byte count
  and feature counts of the extract used, so a later build can tell whether it is comparing
  like with like. **Archive `data/raw/margate.osm` alongside the build**, or pin a dated
  Geofabrik extract, if the exact model matters.

### 02 — Fetch LIDAR

```bash
python3 pipeline/02_fetch_lidar.py        # → data/raw/lidar/{dtm,dsm}_x{i}_y{j}.tif
```

182 rasters (91 tiles × DTM + first-return DSM) over WCS 2.0.1, threaded, resumable — it
skips any file already on disk over 100 KB.

**Caveats**
- Axis labels **must** be `E`/`N`. Using `x`/`y` returns HTTP 500 with no useful message.
- The subset window is expanded by half a pixel each side (`e-0.5` → `e+T+0.5`) — this is
  what produces exactly 513×513 with centres on integer metres. Do not "tidy" it.
- The service returns HTTP 200 with a non-TIFF body for tiles outside coverage. The script
  sniffs the TIFF magic bytes (`II*\0` / `MM\0*`) rather than trusting the status code.

### 03 — Build mosaics

```bash
./run.sh --only 03                        # or: bash pipeline/03_build_mosaics.sh
```

Mosaics the per-tile GeoTIFFs into `data/interim/{dtm,dsm}.vrt`. Steps 04, 06 and 09 all
read these VRTs, never the individual tiles.

**Caveats**
- A VRT is just XML pointing at the tiles, so this is instant — but it also breaks silently
  if `data/raw/lidar/` moves. Rebuild it rather than relocating it.
- The script reports tiles found against the expected `nx*ny`. Fewer is legal — the sea has
  no DTM — but you want to know before wondering why a tile is flat. Margate currently
  resolves 91/91 for both DTM and DSM.

### 04 — Derive building heights

```bash
python3 pipeline/04_derive_heights.py     # → data/interim/_feats.pkl, _stats_*.npy
```

nDSM = DSM − DTM, sampled inside each OSM footprint. Uses **p50 as wall height, p90 as
ridge**.

**Caveats**
- p99/max chase chimneys, aerials and gulls. Mean is dragged down by roof pitch. p50/p90 was
  arrived at by looking at results, not theory — re-derive it if you move to another town.
- Rasterises **one ID-raster and does a sorted groupby** for all buildings at once. Do not
  go back to per-polygon rasterisation; it is orders of magnitude slower.
- Buildings with no LIDAR return fall back to `building:levels × 2.58 m + 1.83 m`
  (`height_calib` in config), then to a per-type prior measured from Margate's own LIDAR
  (see `PRIOR` in step 07). Three fallback rungs, deliberately.
- Outliers land in `data/out/qa_height_outliers.json`. **Actually read this file** — it is
  where you find footprints tagged as buildings that are car parks, and 40 m "houses".

### 05 — Export terrain heightmaps

```bash
python3 pipeline/05_export_terrain.py     # → data/out/terrain/hm_x{i}_y{j}.raw + manifest
```

Unsigned 16-bit little-endian RAW, normalised over `[y_base, y_base + y_size]`.

**Caveats**
- Unity indexes `heights[z, x]` with **z increasing north**; GeoTIFF row 0 is **north**. The
  `np.flipud` is mandatory. Symptom of getting it wrong: the town is mirrored and the
  coastline is on the wrong side, which is surprisingly easy to not notice.
- Values are clipped to the 60 m band. If Margate's terrain ever exceeds it you silently
  flat-top the cliffs rather than get an error — the manifest records per-tile min/max ODN
  so you can check.

### 06 — Road network

```bash
python3 pipeline/06_build_networks.py     # → data/out/networks/
```

Emits **centreline + width**, not finished geometry, so Unity can rebuild ribbons at
different widths without re-running GDAL. Widths per highway class are in `SPEC`.

**Caveats**
- **Two iterations of Chaikin smoothing.** OSM ways are angular and raw vertices make every
  bend read as a facet. Two is enough; more starts moving the road off its true line.
- Junctions are not boolean-merged. Instead each class gets a small **height lift** (0.10 m
  footway → 0.24 m motorway) so the higher class wins the depth test. Vastly cheaper than
  real junction geometry and it reads fine at walking speed. This is the single best
  cost/quality trade in the project.
- `SKIP` drops construction/proposed/platform/elevator etc. Without it you get roads through
  buildings.

### 07 — Building massing

```bash
python3 pipeline/07_massing.py            # → data/out/massing/*.jsonl
```

Per-tile JSONL, ~200 bytes per building, **semantic not geometric** — Unity does the
extrusion.

**Caveats**
- Deliberately diffable and version-controllable. You can re-art the whole town without
  touching GDAL. Keep this property; it is why iteration on the Unity side is fast.
- Geometry is already in **local metres** (`x = E-E0, z = N-N0`), ready for Unity. No
  transform happens on the C# side.
- `PRIOR` heights are measured from Margate's own LIDAR, so they encode local vernacular
  (terraces 8.13 m, bungalows 4.24 m). Another town needs its own priors.
- Landmarks are overridden by hand in `pipeline/config/landmarks.json`. Statistics will never
  get the Dreamland scenic railway or Turner Contemporary right.

### 09 — Coast, beach and sea

```bash
python3 pipeline/09_coast.py              # → data/out/coast/ (splat maps + water tile list)
```

Emits a per-tile splat map (R grass, G sand, B rock-by-slope) and the list of tiles needing
a water surface.

**Caveats — this step is where the data fights back**
- The OSM coastline way is **34 km long and runs to Herne Bay**. Overpass returns the whole
  way for anything touching the bbox. It must be clipped or you get sea across the map.
- **You cannot separate sea from beach by elevation.** 17% of the DTM sits below 0.5 m ODN,
  and Margate's tidal sands occupy the same band as the water surface *because the LIDAR was
  flown at low tide*. Land/sea has to come from the coastline vector and sand from the beach
  polygons. Expect the same trap in any tidal town.

### Unity assembly

Open `unity/VirtualMargate` (Unity **6000.3.23f1**) and run the menu in order:

```
Margate/1 - Import Terrain
Margate/2 - Generate Buildings
Margate/3 - Setup Scene and Player
Margate/4 - Terrain Material
Margate/5 - Generate Roads
Margate/6 - Generate Sea and Beach
```

Generators are in `Assets/_Project/Code/Editor/`, runtime in `Code/Runtime/`
(`MargateWorld`, `MargateWalker`). `MargateDiag`, `MargateShaderCheck` and `MargateWaterDebug`
are diagnostics — use them before assuming a generator is broken.

**Caveat:** generated `Terrain_x*_y*.asset` files are committed. They are large binary
assets and every re-import shows as a diff across all 91. Check `.gitattributes` before
adding more generated binaries.

---

# Part B — The photoreal layer (Gaussian splatting)

**Status: planned, not built.** This is the roadmap for turning the grey-box into something
that looks like Margate.

## The governing constraint

The map is 24 km². **Nobody splats 24 km² at street fidelity.** Rendering budget is roughly
1 M splats ≈ 180–220 MB VRAM and 3–8 ms/frame on an RTX 3070; ~6 M splats runs ~147 fps on a
3080 Ti. So the model is:

> **Grey-box stays the world substrate. Splats are hero pockets streamed per-tile inside it.**

Candidate hero sites: Dreamland, Turner Contemporary, the Old Town lanes, the Harbour Arm,
and the Shell Grotto as the interior test case.

Do not plan for continuous photoreal coverage. Plan for ~1 hero location per streamed tile
and good transitions between grey-box and splat.

## Platform

Training requires **NVIDIA CUDA on Windows**. AMD ROCm exists in forks but is unreliable;
Apple Silicon cannot run CUDA training at all. Brush is the only serious cross-platform
escape hatch, chosen for portability rather than quality.

The intended split is **Mac = repo, pipeline, Unity authoring; Windows = training rig**.
Captures in, `.ply`/`.sog` out, synced across. Do not migrate the GDAL pipeline to Windows —
the geospatial Python stack is materially more painful there, and `tools/*.sh` would need
WSL or Git Bash.

What actually matters in the training box, in order:

1. **VRAM.** Densification is what OOMs you, and it scales with scene extent — which is our
   problem exactly, since these are streets not objects. 24 GB = never think about it. 16 GB
   = cap splat counts and downscale inputs. 12 GB = fighting it on anything bigger than a room.
2. **System RAM.** COLMAP/GLOMAP feature matching on thousands of drone frames is the
   RAM-hungry, largely CPU-bound step. 64 GB comfortable, 128 GB for big aerial sets.
3. **NVMe capacity.** Images + COLMAP databases + checkpoints run to hundreds of GB *per
   site*. Multi-TB.
4. **Sustained thermals.** Training runs for hours at full load; a cool case beats a faster
   card that throttles.

## Phase 0 — Before any capture

- [ ] Pick hero sites and mark their tile indices.
- [ ] **Permissions.** Dreamland and Turner Contemporary are private property; interiors need
      written access. Seafront drone flying needs CAA compliance and crowd/coastal rules
      observed. **This gates Phases 2–3 far harder than any software choice.**
- [ ] Decide the georeferencing method now, not after capture — see caveats below.
- [ ] Establish ground control: pick features identifiable in both the LIDAR DTM and the
      photos.

## Phase 1 — Free pipeline (£0)

Prove the round-trip on 3–4 hero sites before spending anything.

```
phone / drone video
  → RealityScan  (or COLMAP / GLOMAP)     # alignment / SfM
  → LichtFeld Studio                       # training
  → SuperSplat or LichtFeld editor         # cleanup, crop, floater removal
  → .ply / .sog
  → aras-p/UnityGaussianSplatting          # Unity 6+, MIT
```

**Tool notes**
- **LichtFeld Studio** — best free quality currently; full editing suite (brush/lasso/polygon
  select, crop, align, compose) plus Python plugins and MCP endpoints for automation. The
  automation hooks matter if this becomes 20 sites rather than 4.
- **Brush** — cross-platform, runs on AMD and Mac. The fallback if the Windows box is busy.
- **gsplat / Nerfstudio** — research baseline, most configurable, most fiddly.
- **Postshot** — was the default desktop trainer; moved to subscription **with no free `.ply`
  export**. That change is why the OSS tools took over. Don't build a pipeline on it.
- **AirVis Studio** — free, local, Windows/macOS, no account. Takes video / 360 video / image
  folders / COLMAP output, exports RAD, PLY, SPLAT, SPZ, KSPLAT, SOG, SSOG, does people
  masking, and — uniquely useful here — **generates voxel or mesh collision plus automatic
  LOD on export**. Keep it as a scout/recon tool and for its collision exporter. Not the
  backbone: cloud tier caps at 1,000 images @ 2048 px or 15 min video, no georeferencing, no
  RTK, no aerial-ground fusion.

**Caveats**
- **More splats is not better.** Higher splat counts produce markedly more floaters and
  noisier results. Tune for the scene, don't max the slider.
- **Capture on overcast days with locked exposure.** Splats bake lighting. Mixed sun/cloud
  across a capture gives you a scene that cannot be lit consistently, and matching Unity's
  sun to a baked scene is far easier when that scene is flat-lit.
- **Splats do not collide and do not relight.** You need proxy colliders (AirVis's collision
  export, or mesh extraction from LichtFeld) and you must accept baked lighting.
- **Georeference by fitting to the existing DTM.** The `origin` block already defines the
  transform; use LIDAR-derived control points. Doing this per-site by eye will drift and you
  will not notice until two adjacent splats disagree about ground level.
- Watch the water plane at −0.6 m. **gsplat-unity** is the alternative Unity renderer worth
  knowing because it blends Gaussians correctly against transparent meshes via bounding
  boxes — relevant exactly there.

**Unity integration gotchas**
- `aras-p/UnityGaussianSplatting` requires **Vulkan or D3D12** in Project Settings. **D3D11
  will not work.**
- For URP you must add `GaussianSplatURPFeature` to the renderer asset. Nothing renders
  without it and there is no warning.

## Phase 2 — Aerial (low four figures)

Add a DJI drone with RTK for exteriors. Either **Luma AI** (best-looking outdoors — handles
vegetation and sky better than most) or **DJI Terra** (georeferenced aerial GS at building/
site scale). This is what makes the seafront and roofscape convincing.

**Caveat:** the RTK fix is not a nice-to-have. It is what lets Phase 3's aerial-ground fusion
work later, and what stops you re-flying everything.

## Phase 3 — Pro unified indoor/outdoor (~£14k)

Only if seamless interiors are a core deliverable rather than a nice-to-have.

**XGRIDS LixelKity K1/K2 + Lixel CyberColor.** CyberColor's *Aerial-Ground Map Fusion* merges
DJI drone imagery with handheld SLAM-LiDAR scans into a **single unified splat**, both
captured with RTK fix. Premium adds HD Enhancement, AI dynamic object removal (deletes the
tourists), ~90% compression vs raw, Revit/BIM export.

Indicative cost: K1 ≈ £10,918 (£12,467 with RTK), CyberColor ≈ $2,500. A K2 + LixelStudio 4.0
generation now exists. Adjacent options: NavVis VLX and Leica BLK2GO/BLK2FLY for interiors;
Matterport if you want dollhouse tours rather than fidelity.

## Research worth tracking at this scale

- **Hierarchical 3DGS** — proper LOD hierarchy with smooth level transitions for very large
  scenes. The most directly relevant to a streamed town.
- **HUG** — block-based urban aerial reconstruction.
- **BlitzGS** — distributed city-scale training.
- **PrismGS** — anti-aliasing at large scale. Matters a lot when a camera moves through a town.
- **MetroGS** — geometrically accurate large-scale reconstruction.

---

# If you build this again

Ordered by how much time it would save.

1. **Write every step down as a script on day one, even the one-liners.** Steps 01 and 03
   were "obvious" two-line shell commands and stayed undocumented for that reason. When they
   were finally reconstructed, the `ogr2ogr` line turned out to need `-t_srs EPSG:27700` —
   knowledge that existed only in shell history and would have been lost entirely with the
   terminal session. An undocumented one-liner is not simple, it is just unrecorded.
2. **Distrust steps that succeed quietly.** The missing `-t_srs` produced no error, exit code
   0, and a plausible-looking run — the only symptom was `buildings with LIDAR: 0 / 7669`
   buried in stdout. Every stage that can silently sample nothing should assert on its own
   output. Steps 01 and 03 now do; the others should learn the same trick.
3. **Prove reproducibility, don't assume it.** Regenerating `data/out/` and diffing against
   the committed copies is what turned "the pipeline probably works" into a verified 267/267
   byte-identical result. Do this before trusting any rebuild.
4. **Capture is the bottleneck, not compute.** Permissions, drone access and RTK gate this
   project far more than GPU hours. Start the permission conversations in week one; they run
   in parallel with everything else for free.
5. **Keep the semantic-not-geometric rule.** Emitting centrelines and massing records rather
   than meshes is why the Unity side can be re-arted in minutes. Every time you are tempted
   to bake geometry earlier, don't.
6. **Cheap tricks beat correct geometry.** The per-class road height lift instead of boolean
   junction merging is the best decision in the codebase. Look for more of these before
   reaching for the correct-but-expensive solution.
7. **Check the QA outputs.** `qa_height_outliers.json` and the terrain manifest exist to be
   read. Both encode failures that are invisible in-engine.
8. **Tidal data lies.** The low-tide LIDAR flight makes elevation useless for land/sea
   separation. Assume any coastal dataset has a comparable trap and look for it early.
9. **Prove the whole splat round-trip on one small site** — capture → train → georeference →
   Unity → collide → walk — before capturing anything else. Every step above has a gotcha
   that is cheap to hit once and expensive to hit across twelve sites.
10. **Don't commit generated binaries** without a considered `.gitattributes` policy. 91
   terrain assets churn on every re-import.

---

## Repo layout

```
run.sh               orchestrator: ./run.sh [--from N|--only N|--unity|--list]
pipeline/            numbered build scripts + config/margate.json (source of truth)
  01_fetch_osm.sh    Overpass -> GeoPackage (EPSG:27700) + provenance
  02_fetch_lidar.py  EA 1m DTM/DSM per tile over WCS
  03_build_mosaics.sh  gdalbuildvrt -> data/interim/{dtm,dsm}.vrt
  04..09             heights, terrain, networks, massing, coast  (no 08)
  config/            margate.json, landmarks.json, _tiles.json
  lib/
tools/               fetch_osm.sh, build_when_free.sh, AssetRipper, render_2013.py
data/
  raw/               OSM extract + LIDAR GeoTIFFs (fetched, not committed)
  interim/           VRT mosaics, pickled features, stats arrays  (not committed)
  derived/           margate.gpkg  (not committed)
  provenance/        osm.json -- what was fetched, when, and its SHA-256  (committed)
  out/               terrain/ networks/ massing/ coast/ + QA json  -> consumed by Unity
unity/VirtualMargate Unity 6000.3.23f1 project
salvage/             3dexplore/  earlier experiments
```
