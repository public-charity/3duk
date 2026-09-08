# Project One — Isle of Thanet explorer: the brief

This file is the anchor for everything under `projects/one/`. It records what was asked, what
the environment actually is, what has already been decided, and what is still open. Every
design and implementation agent reads it first. Sections 4 and 7 are binding; section 6 is
for the design phase to close.

Date of writing: 2026-09-07. Author: Claude, from Alex's request and a survey of the machine.

---

## 1. What is being built

Alex wants a **high-fidelity, explorable 3D model of the Isle of Thanet** (Margate,
Broadstairs, Ramsgate, Birchington, Westgate, Cliftonville, Manston) in **Unreal Engine 5**,
built from the public data the `3duk` pipeline already turns into terrain, roads, buildings and
ground cover. The Isle is cut from the mainland by a **hard straight line between Minnis Bay and
Pegwell Bay** (the line of the old Wantsum Channel): everything north-east of that line exists,
everything south-west of it does not. **All LIDAR is cropped to that region.** On top of the
terrain, a **reusable, data-driven procedural streetscape system** generates roads, kerbs,
pavements, markings, walls, fences, railings, train tracks and volumetric hedges from shared
splines snapped to OSM polylines — so Thanet-scale variety is authored as profiles and segment
lists, not hand-placed geometry or new C++ classes.

The deliverable of this round is **"an amazing base to build on"**: the pipeline extension, the
Unreal project, the streetscape plugin with its first deliverable working on a real test stretch,
and the interactive explorer (walk / fly) over the cropped Thanet terrain. Buildings and seafront
hero assets are explicitly *last* and are not part of this round beyond the massing the pipeline
already emits.

### 1.1 The original specification, verbatim

> You are implementing a scalable procedural streetscape system for a large 3D reconstruction of the Isle of Thanet in Unreal Engine 5.
>
> **CONTEXT AND STACK**
> - Target engine: Unreal Engine 5 (not Unity).
> - Authoring / tooling also available: Blender (headless via Claude Code), RealityScan, LiDAR processing software.
> - Hardware: Windows Shadow.tech VM with a high-end NVIDIA GPU (H400-class, lots of CUDA cores). Do not worry about GPU limits; design for quality and correctness first.
> - Source data:
>   - LiDAR / DEM for ground topology (already proven in a Unity prototype).
>   - OpenStreetMap as a reference / placeholder layer only: import road and rail as polylines / simple polygons. OSM is NOT the final mesh. The procedural spline tools build the real geometry on top of those paths.
> - Goal: a reusable, data-driven spline system that can generate roads, kerbs, pavements, markings, walls, fences, railings, train tracks, and volumetric hedges at Thanet scale without hand-placing thousands of points.
>
> **CORE DESIGN PRINCIPLE**
> One shared spline (or set of snapped OSM-derived splines) is the source of truth. Multiple specialised mesh renderers read that same spline. Do not spawn a new renderer class for every visual variant. Variants are profiles + per-segment overrides.
>
> **DECIDE AUTHORING LOCATION EARLY**
> - Preferred path: prototype the mesh builders as Python in Blender first (easier to validate geometry, UVs, seams). Then port the same logic to Unreal as C++ components with Blueprint-exposed profile assets.
> - Runtime Unreal authoring is acceptable later for iteration, but do not build two incompatible spline formats. Define a single spline + profile data schema that both Blender and Unreal can read/write (JSON or a simple Unreal DataAsset + exported JSON).
>
> **STAGE ORDER (DO NOT SKIP)**
> 1. Import and tile the LiDAR terrain. Terrain must exist before anything snaps to it.
> 2. Import OSM road / rail polylines as a reference layer. Snap spline control points to those polylines. Keep OSM visible as a debug / placeholder overlay.
> 3. Build the shared spline component (waypoints: position, optional width, bank, profile id, segment tags).
> 4. Build Renderer A: road surface.
> 5. Build Renderer B: edge extrusion (kerb + pavement + walls / fences / railings as profile types).
> 6. Build Renderer C: volumetric hedges / bushes.
> 7. Train tracks reuse the same spline + profile pattern as roads, with tighter tessellation on high curvature and per-sample LiDAR height (not lerp between endpoints).
> 8. Buildings and seafront hero assets last. Low-quality LiDAR along seafronts is expected; do not try to sculpt walls from that LiDAR. Use procedural profiles instead.
>
> **THREE RENDERERS ONLY**
>
> *Renderer A — Road surface (flat)*
> - Extrudes a flat (or slightly cambered / banked) carriageway along the spline.
> - Profile fields: lane count, per-lane widths, total width (can vary per segment), surface material, optional camber.
> - Markings are NOT a second renderer. They are a list on the road profile: offset from centreline; width; dash pattern (solid, dashed, double, none); material / colour.
> - UK marking examples that must be expressible as data, not new code: double yellow; single yellow; centre dashes; combinations of the above.
> - Generate markings in the same mesh pass as the road (sub-meshes or UV / material slots). Do not stack extra spline renderers for paint — resampling the same spline twice causes alignment drift.
>
> *Renderer B — Edge extrusion (kerb + pavement + linear barriers)*
> - Different topology from the road: vertical extrusion with a top lip, not a flat ribbon.
> - Shares the same spline as the road. Samples the road's current edge offset at each point so the kerb always hugs the carriageway even when road width changes mid-spline.
> - Per-segment parameters: kerb width (NOT fixed); kerb height; pavement width; drop-kerb list: distance along spline, ramp length, target height (usually 0).
> - Drop kerbs punch a gap in the lip and ramp height down over a short run. This logic lives here, not in the road renderer.
> - Pavement belongs in this renderer, not the road renderer. It is a wider, lower extrusion that shares seam and drop-kerb handling with the kerb.
> - Walls, fences, railings are profile types on this same renderer, not new renderer classes: type (brick wall, chain-link, railing, etc.); height, thickness, material; segment list with start/end distances along the spline so you can switch brick → chain-link → railing without stacking tools.
> - Half-grass / half-tarmac kerbs are a profile flag / split material: grass on the outer face, tarmac on the inner face; boundary along the top edge; keep both faces flush at the top (typical UK kerb). Do not introduce a visible step unless explicitly requested. Drop-kerb ramps carry both materials down.
>
> *Renderer C — Volumetric hedge / bush*
> - A trimmed privet (or similar) is not an extrusion. It is a volume with foliage.
> - Separate renderer, but it MUST read the same spline and the same segment list as Renderer B so it stacks cleanly beside walls/fences.
> - Follows the path and generates a canopy / volume. Do not fake this as a thin wall with a leaf texture if the brief is a real trimmed hedge.
>
> **SEAM AND OVERLAP RULES (CRITICAL)**
> - Never leave a 0-width mathematical join between road and kerb. Sampling error will show as a crack or z-fight.
> - Rule: the surface that is visually on top owns the seam.
> - Road sits on top of kerb, so: road mesh extends a few centimetres past the kerb start line; kerb base tucks under that overhang; any width-change error disappears under the lip.
> - Prefer a small overlap or shared seam vertices so the two meshes tessellate cleanly.
> - When road width changes mid-spline, both renderers must re-sample the same edge offset for that segment.
>
> **LIDAR / HEIGHT MAPPING**
> - Sample LiDAR height at each spline sample point. Do NOT follow raw LiDAR point-for-point — it is noisy and will make the road ripple.
> - Smooth sampled heights with a moving average or low-pass filter. The road and kerb sit on the smoothed curve. The terrain mesh underneath stays untouched.
> - Both road and kerb inherit the same smoothed heights because they share the spline.
> - For cross-section: tilt / bank each segment to match local terrain slope so a road on a banked corner leans with the ground instead of hovering flat.
> - High-curvature paths (especially rail in cuttings): increase tessellation where curvature is high. Sample LiDAR height at each tessellated point; do not lerp height only between sparse waypoints.
> - Edge case: road cutting through a steep bank. Smoothed height will sit above or below real ground. Handle with an extra profile entry on Renderer B: short embankment or retaining wall on the downhill / uphill side. Same spline, extra extrusion.
>
> **TRAIN TRACKS**
> - Same spline + profile architecture as roads.
> - Placeholder OSM / imported rail polyline first, then procedural track profile over it.
> - Must hug LiDAR in deep curves. Treat this as a sampling / tessellation problem, not a new tool.
>
> **DATA MODEL TO IMPLEMENT**
> Define something equivalent to:
> ```
> Spline
>   points[]: position, optional roll, optional width override
>   samples: resampled at adaptive interval (tighter on curvature)
> RoadProfile
>   lanes, widths, camber, surface material
>   markings[]: offset, width, pattern, material
> EdgeProfile
>   kerbWidth, kerbHeight, pavementWidth
>   splitMaterial? (inner/outer)
>   dropKerbs[]: s, rampLength, targetHeight
>   barrierSegments[]: s0, s1, type, height, thickness, material
> HedgeProfile
>   width, height, density / mesh set
>   segments[]: s0, s1
> ```
> All distances s are arc-length along the shared spline.
>
> **WHAT NOT TO DO**
> - Do not make one renderer per marking type, per fence type, or per kerb width.
> - Do not stack independent road-paint splines on top of the carriageway spline.
> - Do not put pavement in the road renderer.
> - Do not put volumetric hedges in the edge-extrusion renderer.
> - Do not author final road meshes from OSM polygons; OSM is a snap target and placeholder only.
> - Do not wait for buildings / seafront assets before the three renderers work on tiled LiDAR.
>
> **FIRST DELIVERABLE**
> Implement the shared spline + Renderer A + Renderer B on a short test stretch that includes: varying road width; double yellows + centre dashes; a drop kerb; a half-grass / half-tarmac kerb; a width change with correct road-over-kerb overlap; LiDAR-sampled, smoothed heights; a debug overlay of the source OSM polyline.
> Then add Renderer C and a rail profile. Keep the system data-driven so Thanet-scale variation is authored as profiles and segment lists, not new C++ classes.

Alex's framing around it: *"use the data sources existing in the repo and previous calibration
work to create the isle of thanet with a hard straight line cut-off between minnis bay and
pegwell, crop all lidar data to this region and build the interactive town explorer base so I can
eventually make it a high fidelity 3d model to explore ... I really want an amazing base to build
on."*

---

## 2. The machine, as surveyed (not as the spec assumed)

| | |
|---|---|
| OS | Windows 11 Home, Shadow.tech VM. Git Bash is the shell for scripts. |
| GPU / RAM / CPU | **NVIDIA RTX A4500, 20 GB** (not an H400). 28 GB RAM. 4 physical / 8 logical cores. UBT builds run 4-wide. |
| Disk | 294 GB free on C:. |
| Unreal | **UE 5.8.2** at `C:\Program Files\Epic Games\UE_5.8` (binary install; full engine *source headers* are present under `Engine/Source` and `Engine/Plugins` and must be read to verify any API). `UnrealEditor.exe`, `UnrealEditor-Cmd.exe`. Bundled dotnet: `Engine/Binaries/ThirdParty/DotNet/10.0/win-x64/dotnet.exe`; UBT: `Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll`; `Engine/Build/BatchFiles/Build.bat`. |
| Compiler | Visual Studio 2022 **Build Tools** 17.14, MSVC 14.44, Windows SDK 10.0.22621. Proven: the UnrealMCP plugin project compiled with it on 2026-09-07 (see `C:\UnrealProjects\build6.log`). |
| Engine plugins verified present | PythonScriptPlugin (Experimental), GeoReferencing, ProceduralMeshComponent, GeometryScripting, GeometryProcessing, PCG, Water (Experimental), Landmass, ModelingToolsEditorMode, EditorScriptingUtilities, EnhancedInput, Interchange, GLTFExporter, LandscapePatch, MeshLODToolset, WorldPartitionHLODUtilities, Niagara. Core (non-plugin) modules: Landscape, LandscapeEditor, GeometryCore, GeometryFramework. |
| UE Python | PythonScriptPlugin bundles Python 3.11 (`Engine/Binaries/ThirdParty/Python3/Win64`). Headless: `UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=<file>` (class `UPythonScriptCommandlet`). |
| Unreal MCP | `chongdashu/unreal-mcp` at `C:\UnrealProjects\unreal-mcp`, ported to 5.8 (see memory notes). Plugin source: `C:\UnrealProjects\unreal-mcp\MCPGameProject\Plugins\UnrealMCP` (81 MB incl. binaries). The editor is **currently running `MCPGameProject`** with the TCP bridge live on `127.0.0.1:55557`. The MCP tools only manipulate actors/blueprints in whichever project is open — they cannot import landscapes. Do not close Alex's editor. |
| Blender | **5.2.1 LTS** at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`, Python **3.13.13**, numpy 2.3.4. Headless works: `blender.exe -b --python <script>`. |
| Pipeline Python | **`C:\Users\Shadow\code\3duk-env\env\python.exe`** — conda-forge Python 3.13.15 with **GDAL 3.13.3**, numpy 2.5.3, scipy 1.18. GDAL CLI in `C:\Users\Shadow\code\3duk-env\env\Library\bin`. `python3`/`python` on PATH are the **broken Microsoft Store stubs — never use them**. |
| PROJ / datum | The OSTN15 grid is **not installed**; step 01 sets `PROJ_NETWORK=ON` and PROJ fetches it from cdn.proj.org (cache at `%LOCALAPPDATA%\proj\cache.db`). Without it OSM lands ~1.8 m off the LIDAR. Always run step 01 through `run.sh` so the guard applies. |
| Network | EA WCS reachable (GetCapabilities 0.2 s). Measured throughput 2026-09-07: 182 tiles in 83 s with 8 workers. Only `https://overpass-api.de` answered; the two mirror endpoints in `fetch_osm.sh` were unreachable today. Nominatim reachable. |
| Git | `origin = https://github.com/public-charity/3duk.git`. Working branch **`thanet-explorer`**, cut from `fix/datum-guard-regression` (one commit ahead of `main`: the datum guard, which Thanet needs). git-lfs 3.7 installed; `.gitattributes` routes `*.png *.fbx *.blend *.exr *.tga *.wav *.psd` through LFS and forces LF on text. |

---

## 3. The 3duk repo: what exists and the rules

Read `README.md` and `sources/OUTPUT.md` (the output contract) before touching `sources/`.
Summary of what matters here:

- **Engine-neutral pipeline**, steps 01–10 driven by `sources/run.sh`, config in
  `sources/config/sites/<site>.json` + `sources/config/tuning.json`, shared code in
  `sources/lib.py`. Output is GeoTIFF + JSONL in **EPSG:27700 metres, elevation ODN metres,
  north-up, no local origin**. Consumers convert in `sources/adapters/<consumer>.py`;
  `unity.py` is the reference adapter (Y-up, local metres, 16-bit RAW, class lifts, bridge/tunnel
  offsets). **Nothing in `sources/derive/` may learn about an engine.**
- **Margate is already built** (`data/margate/`, untracked): origin E 632800 N 168200, 13×7 tiles
  of 512 m, 513×513 samples per tile (shared edge row), 7,669 buildings, 5,001 road segments /
  317 km, 584 junctions, elevation −2.91..49.81 m, cliffs to 84°. Raw LIDAR: 182 GeoTIFFs
  (`data/margate/raw/lidar/{dtm,dsm}_x{i}_y{j}.tif`, 4 MB each, uncompressed). OSM extract
  `data/margate/raw/margate.osm` (8.6 MB) → `data/margate/derived/margate.gpkg`.
- **Calibration lessons live in the configs and README** and must be reused, not rediscovered:
  Margate's `water_level -0.6`, `coast.foreshore_max_odn 1.2` (low-tide survey),
  `rock_slope_deg [22,40]` (Cliftonville chalk), `height_calib` fitted 1.337 + 2.807×levels
  (n=1457, rmse 1.4 m), landmark overrides for Arlington House and the Jubilee Clock Tower,
  `crs_max_transform_accuracy_m 1.0` (OSTN15 guard). Thanet is the same chalk coast and the same
  EA composite, so it inherits Margate's numbers — with a note saying so and that the fitted line
  will be re-regressed from Thanet's own buildings (`mode: auto`).
- **The site rule**: "Add `sources/config/sites/<name>.json` and set `SITE=<name>`. No step should
  need editing. If one does, that is a bug in the step, not a missing feature." A **clip region is
  a genuinely new feature**, so extending the steps to honour an *optional* `clip` block in the
  site config is legitimate — but it must be opt-in, backward compatible (Margate and Whitby
  configs unchanged → byte-identical output), implemented once in `lib.py`, and recorded in every
  manifest it affects.
- **Testing**: `sources/tests/dryrun.py` runs steps 05–10 and the Unity adapter against two
  synthetic sites through a fake in-memory GDAL (`sources/tests/fake_osgeo`) with numpy only.
  Every pipeline change must extend it (a synthetic site with a clip line; the new step; the new
  adapter) and it must pass with the env python. The README's regression standard is "reproduces
  the previous model to the centimetre" — keep Margate byte-identical.
- **Data facts found in the Margate GeoPackage** that shape this project: the Overpass query
  fetches **no `railway` ways** (0 in Margate; `railway` exists as a column but is empty) — the
  Thanet query must add `way["railway"]`. **467 `barrier` ways** exist: wall 175, fence 173, hedge
  42, retaining_wall 30, kerb 19, gate 13, bollard 13 — a real reference layer for Renderer B/C
  segment lists. Highways carry `sidewalk`, `sidewalk:left/right`, `lanes`, `lanes:forward/backward`,
  `lane_markings`, `surface`, `maxspeed`, `lit` in `other_tags`.
- **Repo hygiene**: `data/` is untracked (re-fetchable). Text files are LF. Binary art only through
  LFS. No Unreal build products (`Binaries/`, `Intermediate/`, `Saved/`, `DerivedDataCache/`,
  `.vs/`, `*.sln`) may be committed — `.gitignore` covers them for `projects/`.

---

## 4. Decisions already made (binding)

### 4.1 The `thanet` site

| | |
|---|---|
| Site name | `thanet` → `sources/config/sites/thanet.json`, output `data/thanet/`. |
| CRS / datum | EPSG:27700, ODN, exactly as Margate. `crs_max_transform_accuracy_m 1.0`. |
| Grid | **origin E 627680, N 163080; tile_m 512; nx 26, ny 19; grid_res 513** → 494 tile positions, extent E 627680..640992, N 163080..172808 (13.3 km × 9.7 km). Chosen so Margate's grid is a sub-grid: **Margate tile (i, j) = Thanet tile (i+10, j+10)**, so the 182 downloaded Margate rasters are bit-identical to what step 02 would fetch and can be copied into `data/thanet/raw/lidar/` under the new names (with a correct `_grid.json` stamp) instead of re-downloading. |
| Overpass bbox | `bbox_wgs84: [51.305, 1.275, 51.405, 1.465]` (S, W, N, E) — generous; the grid is the model. Expect ~45 MB (Margate's 8.6 MB scaled by area). |
| **Clip line** | From **Minnis Bay** `A = (E 628512, N 169680)` (OSM `natural=bay` node, lat 51.38015 lon 1.28241) to **Pegwell Bay** `B = (E 635496, N 163609)` (OSM `place=locality` node, lat 51.32281 lon 1.37858). Both reprojected through the **OSTN15 grid** (`PROJ_NETWORK=ON cs2cs EPSG:4326 EPSG:27700`), the same operation step 01 uses for all OSM data; the Helmert fallback puts them ~2 m away (628514, 169681 / 635498, 163610) and must not be used. Length 9,254 m, bearing 131° A→B. **Keep the half-plane on the LEFT of A→B** (north-east): keep P iff `cross(B−A, P−A) ≥ 0`, i.e. `(P−A)·(6071, 6984) ≥ 0`. Verified: Margate, Birchington station, Manston airport, Ramsgate harbour, North Foreland are kept; Minster and Cliffsend village are excluded. The endpoints are provisional in the sense that they are **config, not code**: `clip: {"type": "halfplane", "line": [[628512, 169680], [635496, 163609]], "keep": "left", ...notes}`; moving them rebuilds the model. |
| Tile budget | Against the line: 360 tiles fully kept, 31 straddle it, 103 fully excluded → **391 tiles to fetch (782 rasters)**, ~6 minutes at the measured rate, minus 91 tiles reused from Margate. |
| Crop semantics | Step 02 **does not fetch** tiles whose 512 m square lies wholly outside the clip. Step 05 writes **nodata (not filled)** for cells outside the clip and records `clip` + per-tile `clipped_cells` in the terrain manifest — a clipped cell is a deliberate absence, distinct from a coverage gap, and the manifest must let a consumer tell them apart. Steps 06/07/09/10 (and the new linear-features step) drop features/vertices outside the clip and count them in their manifests, the same way they already count `outside_grid`. The Unreal side renders the cut as **a hard edge**: landscape visibility (hole) mask along the exact line, not a staircase of missing components. |
| Calibration | Inherit Margate's `water_level`, `coast`, `height_calib` (mode auto, Margate's fitted line as `fallback`), `landmarks`, `wcs`. Each inherited block carries a note saying it was measured at Margate on this same survey and is expected to hold across the isle; `qa_height_outliers.json` from the first Thanet run decides whether more landmarks are needed (Ramsgate's Royal Harbour, Broadstairs' Bleak House are candidates — do not pre-add). |

### 4.2 Coordinate conventions (three frames, one conversion point each)

| Frame | Axes / units | Where it applies |
|---|---|---|
| **Survey** | EPSG:27700 easting/northing metres, Z = ODN metres, north-up rasters. `bearing` = degrees clockwise from grid north. | Everything under `sources/derive/` and `data/<site>/out/` — unchanged. |
| **Streetscape JSON** (the shared spline + profile schema) | **Local metres from the site origin (E0, N0)**, **right-handed, Z-up: X = east, Y = north, Z = up (ODN metres, not re-based)**. File header carries `crs`, `origin`, `vertical_datum`, `site`, `schema_version`. Doubles. This is Blender's native frame, so the Blender prototype reads it with no transform. Float32 cannot hold raw eastings (ULP at 6.3e5 is 6 cm) — hence local. | `projects/one/schema/streetscape.schema.json`; written by `sources/adapters/unreal.py`; read by Blender and by the Unreal plugin. |
| **Unreal** | Left-handed, Z-up, **centimetres**: `X_ue = 100·x`, **`Y_ue = −100·y`** (so +Y points south), `Z_ue = 100·z`. This is exactly what Epic's GeoReferencing plugin does in FlatPlanet mode (`GeoReferencingSystem.cpp:232`: `(Projected − Origin) * FVector(100, −100, 100)`). **Yaw = bearing − 90°** (yaw 0 = +X = east; positive yaw turns east→south = clockwise on a north-up map). A north-up heightmap's row 0 is the smallest UE Y (north) — **no row flip** for landscape import. | Applied **only** inside the Unreal plugin's JSON loader and inside the landscape importer. Never baked into the JSON. |

`sources/adapters/unreal.py` emits Streetscape-JSON-frame data (local metres, Y north) plus
landscape heightmaps; the C++ loader does the ×(100, −100, 100). The adapter's own manifest
states this in words. A unit test covers a known point in all three frames.

### 4.3 Layout of `projects/one/`

```
projects/one/
  README.md                      how to build, run, and what state each stage is in
  docs/
    BRIEF.md                     this file
    DESIGN.md                    architecture decisions and their reasons (design phase output)
    SCHEMA.md                    the shared spline + profile schema, field by field (normative prose)
    STAGES.md                    stage order with acceptance criteria and status
    UE_PLAN.md                   file-by-file plan of the Unreal project + plugin, APIs cited to engine headers
    PIPELINE_CHANGES.md          exact changes to sources/ (clip, linear features step, adapter, tests)
    design/                      raw per-subsystem designs and critiques from the design phase
  schema/
    streetscape.schema.json      JSON Schema (draft 2020-12) for the interchange format
    profiles/*.json              UK default profiles: residential / primary roads, UK kerb, half-grass kerb,
                                 brick wall, chain-link, railing, privet hedge, standard-gauge rail
  Thanet.uproject                UE 5.8 C++ project ("Thanet")
  Source/Thanet/                 game module: explorer pawn (walk + fly), game mode, minimal
  Source/Thanet.Target.cs, Source/ThanetEditor.Target.cs
  Plugins/Streetscape/           THE reusable plugin (runtime module Streetscape, editor module StreetscapeEditor)
  Plugins/UnrealMCP/             copy of the 5.8-ported UnrealMCP plugin SOURCE (no Binaries/Intermediate) so the
                                 MCP bridge works when this project is the one open in the editor
  Config/                        DefaultEngine.ini (World Partition, DX12/SM6, Lumen/VSM as the blank template),
                                 DefaultGame.ini, DefaultInput.ini (Enhanced Input), DefaultEditor.ini
  Content/                       ONLY assets generated by scripts or tiny hand-made ones; large binaries via LFS
  Tools/
    blender/streetscape/         Blender/numpy prototype of the geometry core + Renderers A/B/C + rail
    blender/tests/               pure-numpy tests (no bpy) runnable with the pipeline python
    ue/                          editor Python: bootstrap (materials, profile DataAssets), import_landscape,
                                 import_streetscape, screenshot; PowerShell wrappers for headless runs
    build.ps1 / build.sh         UBT build of ThanetEditor Win64 Development
```

Everything under `projects/one/` is text except what LFS carries. Generated Unreal assets
(`.uasset/.umap`) produced by the bootstrap scripts are committed only if small and only after the
scripts that regenerate them exist — the scripts are the source of truth.

### 4.4 Engine and implementation choices

- **UE 5.8.2, C++.** Streetscape is a **plugin** (`Plugins/Streetscape`) with a Runtime module
  (`Streetscape`: spline component, profile DataAsset classes, three renderer components, JSON
  loader, terrain sampler interface, debug overlay) and an Editor module (`StreetscapeEditor`:
  details-panel "Rebuild" buttons, a "Streetscape → Import site" menu, the **landscape importer**
  UFUNCTIONs callable from Python). The game module `Thanet` holds only the explorer.
- **Meshes: `UDynamicMeshComponent`** (GeometryFramework + GeometryCore, both core engine
  modules — no plugin dependency at runtime). One component per renderer per spline, **material
  IDs via the mesh attribute set** (`EnableMaterialID`) so markings, kerb inner/outer faces,
  pavement, barriers are sub-meshes of one build, exactly as the spec demands. Complex-as-simple
  collision so the explorer can walk on roads and pavements. `UProceduralMeshComponent` is the
  fallback only if DynamicMesh proves unworkable in a specific case, and that must be recorded.
- **Profiles are `UDataAsset` subclasses** (`URoadProfile`, `UEdgeProfile`, `UHedgeProfile`; rail is
  a `URoadProfile` with `Kind = Rail`) with USTRUCT rows for markings, drop kerbs, barrier
  segments, hedge segments, embankments. **JSON is the interchange**: every profile and spline
  can be round-tripped (`ToJson`/`FromJson`) to the same schema the Blender prototype reads; a
  Python bootstrap creates the default DataAssets from `schema/profiles/*.json`.
- **Rail = a profile of Renderer A, not a fourth renderer**: ballast bed as the cambered ribbon
  (shoulders via the same camber/bank machinery), rails and sleepers as **sub-meshes of the same
  build pass** (rails: a small closed cross-section swept at ±gauge/2 using the same
  cross-section sweep routine Renderer B uses for kerbs; sleepers: instanced along `s` at a pitch
  or swept boxes — decide in design). Rail profiles force tighter curvature-adaptive tessellation.
- **Terrain in UE = one World Partition `ALandscape`** with streaming proxies, imported by our own
  C++ from the adapter's 16-bit tiles via `ALandscapeProxy::Import(...)`
  (`Engine/Source/Runtime/Landscape/Classes/LandscapeProxy.h:1418`) then
  `FLandscapeConfigHelper::PartitionLandscape` / `ChangeGridSize`
  (`Engine/Source/Runtime/Landscape/Public/LandscapeConfigHelper.h:71-72`) — the same calls the
  editor's Landscape mode makes. `FLandscapeImportHelper::ChooseBestComponentSizeForImport`
  (`LandscapeImportHelper.h:140`) and `TransformHeightmapImportData` (`:138`) exist for
  padding to a valid component grid. Height encoding: `LANDSCAPE_ZSCALE = 1/128`
  (`LandscapeDataAccess.h:13`): local height = (h16 − 32768)/128 × actor Z scale. With Z scale
  100 the window is ±256 m at 0.78 cm — Thanet is −3..+60 m. **1 m samples, no resampling**;
  prove cliffs survive by comparing against `terrain_manifest.slope_qa` after import. The clip
  line is cut with the **landscape visibility layer** (`ALandscapeProxy::VisibilityLayer`,
  `LandscapeProxy.h:1002`) so the edge is the exact line. Ground cover (grass/sand/rock/water
  fractions from step 09) becomes landscape weightmap layers.
- **Headless first**: every editor-side step (bootstrap, landscape import, streetscape import,
  screenshot) must run via `UnrealEditor-Cmd.exe Thanet.uproject -run=pythonscript -script=…`
  (or a commandlet) so it is reproducible and does not depend on the GUI. Interactive use of the
  MCP bridge is a convenience on top, never the only path.
- **Blender prototype first, sharing the schema**: the geometry core (resampling, arc-length,
  curvature, height smoothing, banking, cross-section sweep, seam/overlap, markings, drop kerbs,
  split materials, barrier segments, hedge volume, rail) is written as **pure numpy** under
  `Tools/blender/streetscape/` with a thin `bpy` layer for mesh creation/render, so the same code
  is unit-tested with the pipeline python (no Blender needed) and rendered in Blender headless.
  The C++ port mirrors the module structure and the tests' numeric expectations (vertex counts,
  overlap widths, marking offsets, smoothed heights on a known synthetic profile).
- **OSM reference layer**: roads from step 06 (`networks/roads_*.jsonl`), plus a **new step 11
  `sources/derive/11_linear_features.py`** emitting `networks/rail_x*_y*.jsonl` (railway ways:
  rail/tram/… with gauge, electrified, service, bridge/tunnel) and `networks/barriers_x*_y*.jsonl`
  (barrier ways: wall, fence, hedge, retaining_wall, kerb, with height/material tags) — draped on
  the DTM with the same densify/drape/tile-split code as 06 (factor it into `lib.py` or a shared
  module rather than copy it). Step 06 itself stays untouched except for clip support, to keep
  its centimetre regression intact. The Unreal adapter turns roads/rail/barriers into
  **Streetscape JSON splines** with a `source: {"osm_id", "layer"}` block and a default profile
  id from `cls`, and keeps the raw OSM polyline alongside as the **debug overlay** geometry.
- **First deliverable test stretch**: chosen from the Margate data (already on disk, so work
  starts before the Thanet fetch finishes): a residential/tertiary road with a width change or
  two joined ways of different widths, near the seafront so the half-grass kerb is plausible.
  Authored as a Streetscape JSON file in `projects/one/schema/examples/test_stretch.json` with:
  a width override mid-spline, double-yellow + centre-dash marking set, one drop kerb, a
  half-grass/half-tarmac edge segment, the OSM polyline as overlay, heights sampled from the
  Margate DTM and smoothed. It is built by the Blender prototype (→ glTF + PNG renders) and by
  the Unreal plugin (→ actor in a level), and both outputs are checked against the same numbers.

### 4.5 Process rules

- Work happens on branch `thanet-explorer`. Commit at the end of each phase with a message that
  states what was verified and how (the repo's existing commit style).
- **Do not close or drive Alex's running editor** (`MCPGameProject`). Headless commandlets against
  `projects/one/Thanet.uproject` are fine and can run alongside it (the UnrealMCP plugin in the
  new project must tolerate port 55557 being taken — check it logs and continues rather than
  asserting; if it asserts, make the port configurable).
- Never modify `data/margate/` or `data/whitby/`; read them freely. Copying Margate raw tiles
  into `data/thanet/raw/lidar/` is expected.
- Run every Python through `C:\Users\Shadow\code\3duk-env\env\python.exe` (pipeline, tests,
  adapters) or Blender's bundled Python (`blender.exe -b --python …`) or UE's bundled Python
  (`-run=pythonscript`). Blender's numpy is 2.3; the env's is 2.5; UE's Python 3.11 has **no
  numpy** — the UE-side Python must be pure stdlib + `unreal`.
- Scratch/temporary files go in the session scratchpad, not in the repo.
- Every claim of "works" must be backed by a command that was actually run and its output; the
  README and STAGES.md record the state honestly, including what is not done.

---

## 5. Stage order and acceptance criteria

| # | Stage | Done when |
|---|---|---|
| 1 | Cropped Thanet terrain | `SITE=thanet run.sh` steps 01–05 complete; `terrain_manifest.json` shows 391 tiles, `clip` recorded, `slope_qa.max_deg` ≥ 80 (cliffs intact); Margate tiles reused; Unreal adapter writes landscape tiles + manifest; **landscape imported headless into `Thanet.uproject`** at 1 m with the clip hole; a screenshot or height probe proves cliffs are 65–80° in-engine. |
| 2 | OSM reference layer | Steps 06, 07, 09, 10, **11** complete with clip counts; adapter writes Streetscape JSON splines for roads, rail and barriers plus overlay polylines; Unreal shows the overlay as debug lines over the landscape. |
| 3 | Shared spline | `UStreetSplineComponent` + numpy `spline.py`: waypoints (position, roll, width override, profile id, tags), curvature-adaptive resampling, arc-length `s`, terrain sampling, moving-average smoothing, banking. Tests: synthetic sine road → sample spacing tighter on bends, smoothed heights within tolerance, `s` monotone. |
| 4 | Renderer A | Road ribbon with camber/bank, per-segment width, markings as material-ID sub-meshes: double yellow, single yellow, centre dashes expressible purely as profile data. Tests: marking offsets/widths measured from the mesh. |
| 5 | Renderer B | Kerb with lip + pavement + drop kerbs + split materials + barrier segments (brick / chain-link / railing) + embankment/retaining entries; road-over-kerb overlap ≥ 3 cm everywhere including across a width change. Tests: no zero-width seam, overlap measured. |
| **First deliverable** | Stages 3–5 on the test stretch in **both** Blender (renders committed as PNG via LFS) and Unreal (level saved, screenshot). |
| 6 | Renderer C | Volumetric privet hedge along the shared spline reading the same segment list as B. |
| 7 | Rail profile | Standard-gauge track on the Margate/Thanet railway (Birchington–Margate–Broadstairs–Ramsgate line) hugging LIDAR in cuttings; tessellation density visibly tighter on curves. |
| 8 | Explorer base | `Thanet.uproject` opens to a World Partition map with the landscape, overlay, test-stretch streetscape and an Enhanced-Input pawn that walks and flies; massing from step 07 shown as grey boxes (placeholder only). |

---

## 6. Open questions for the design phase (close them in DESIGN.md)

1. Landscape import granularity: import the whole 12801×9729 heightfield in one `Import` call and
   partition, or per-region imports? What component size (`ChooseBestComponentSizeForImport`) and
   World Partition grid size? Where does padding go and what value fills it (recommend: water
   level, marked visible=false)?
2. How exactly to write the visibility (hole) layer and the four ground-cover weightmaps in the
   same import call (`FLandscapeImportLayerInfo` + layer info objects created by script).
3. Terrain sampling for the spline in-editor: `ALandscapeProxy::GetHeightAtLocation`
   (`LandscapeProxy.h:1101`) vs reading the adapter's heightfield directly (deterministic, works
   before the landscape exists, identical to Blender). Recommend: the plugin samples an
   `IStreetTerrainSource`; two implementations (heightfield file, landscape).
4. Cross-section sweep: one generic "sweep closed/open polyline profile along spline at lateral
   offset with per-sample height/bank" routine shared by kerb, wall, railing posts, rail heads —
   define its API once for numpy and C++.
5. Markings: sub-mesh strips lifted by ~3 mm, or same-plane with material ID (z-fight risk)?
   Dash pattern parameterisation (`dash_m`, `gap_m`, `phase_m`, `double_gap_m`).
6. Hedge volume: swept rounded box with noise-displaced surface + instanced leaf cards, or
   Niagara/PCG foliage? Must be a real volume; decide density knobs.
7. Junctions: step 06 emits `_junction` discs. Out of scope for the first deliverable, but the
   schema must leave room (`junction` nodes referencing spline ends).
8. Streaming: one actor per OSM way vs one per tile with many spline components; HLOD/Nanite
   settings for DynamicMesh at Thanet scale.
9. Explorer pawn: first-person walk with fly toggle; spawn at the test stretch; minimap later.
10. Where the UnrealMCP plugin copy comes from (source-only copy of
    `C:\UnrealProjects\unreal-mcp\MCPGameProject\Plugins\UnrealMCP`) and how its port conflict
    with the running editor is handled.

---

## 7. Rules for agents working in this repo

- Read this file, then only what your task needs. Cite engine APIs by **header path and line
  number** in the installed engine; do not rely on memory of other UE versions (5.8 removed
  `ANY_PACKAGE`, requires `EngineIncludeOrderVersion.Unreal5_8`/`BuildSettingsVersion.V7` — see
  memory notes on the UnrealMCP port).
- Python: `C:\Users\Shadow\code\3duk-env\env\python.exe` only (see §2). Bash scripts: LF endings.
- File ownership during parallel implementation is stated in each task; do not edit files owned
  by another task. Shared touch points (`lib.py`, `run.sh`, `OUTPUT.md`, `dryrun.py`, root
  `.gitignore`) belong to the pipeline task unless stated otherwise.
- Verify by running. Report exactly what ran and what it printed. Unverified = not done.

---

## Design phase closed 2026-09-07

- Normative output: `DESIGN.md` (architecture, every decision with its reason; §6's open questions closed there), `SCHEMA.md` + `../schema/` (the interchange, field by field), `UE_PLAN.md` (Unreal project and plugin file by file, APIs cited to the installed 5.8 headers), `PIPELINE_CHANGES.md` (every change to `sources/`), `STAGES.md` (§5 expanded into tasks, owners, acceptance commands and the one status column).
- Section 4 of this file remains binding on the implementation phase and overrides the normative documents where they disagree.
- `DESIGN.md` §19 lists the critique that was rejected, with reasons, so it is not re-raised; `DESIGN.md` §21 is the file ownership for the parallel tracks.
- `docs/design/` keeps the raw per-subsystem designs and critiques for reference only.
- Nothing designed here had been run at the close; §8 below records what ran before the tracks started, and `STAGES.md`'s status column is the only place that says what is done.

---

## 8. Implementation-phase facts (2026-09-08, before the tracks started)

Things done or discovered after the design closed. Implementers treat these as current state.

- **Raw Thanet data is already on disk** (steps 01–04 ran through `run.sh` on 2026-09-08 with the
  *unmodified* steps; logs in the session scratchpad `logs/thanet_0{1,2,3,4}.log`):
  - `sources/config/sites/thanet.json` exists with exactly the PIPELINE_CHANGES.md §1 text (OSTN15
    endpoints). `sources/fetch/fetch_osm.sh` already has `way["railway"]($BBOX);` after the highway
    line (§5's other items — `.query` file, provenance `query_*` keys and railway/barrier counts — are
    still to do; **Thanet's provenance was written without them and must be regenerated by re-running
    01, which skips the fetch on a matching bbox**).
  - 01: 30 MB extract, first Overpass attempt, datum operation **1 m class (OSTN15)**; 23,459
    buildings, 12,036 highways; in the GeoPackage: `railway` rail 217, abandoned 20, razed 16,
    platform 7, miniature 2 (named lines: Kent Coast Line, Chatham Main Line (Ramsgate Branch),
    Ashford to Ramsgate Line, tagged gauge 1435, electrified rail, passenger_lines 2, usage main);
    `barrier` fence 1,155, wall 788, hedge 179, retaining_wall 43, gate 40, bollard 30, kerb 24.
  - 02: Margate's 182 rasters were copied to Thanet indices `(i+10, j+10)` by a one-off script after
    checking each file's `ModelTransformationTag` origin (the tiles use tag 34264, **not** a tiepoint —
    `reuse_tiles.py`'s `georef_origin` check must read 34264 first); `_grid.json` holds the four keys.
    Then the unmodified 02 fetched **all 494 positions** (806 ok + 182 cached, 311 s, 3.9 GB): the 103
    outside-clip positions are on disk too. That is harmless (05 and 09 skip them from the config, and
    a later 02 with the clip edit sees them as cached), but `skipped_clip` will report 0 for them
    unless 02 also counts on-disk outside tiles — say which in the manifest. No position came back
    EMPTY: the composite covers the whole grid including open sea.
  - 03: `dtm.vrt`/`dsm.vrt` over 494 tiles, 13313 × 9729. 04: DTM nodata **11.27 %** of the mosaic,
    DSM 17.47 % (open sea / far offshore, unlike Margate's 0 %); 23,400 of 23,459 footprints have
    DTM ground and DSM height, 0 ground-only. Step 05's nearest fill will therefore fill sea cells —
    the coast step's water rule decides what they are; record the fill counts.
- **Margate byte-identity baseline**: `data/margate/regress/baseline_2026-09-08.sha256` — sha256 of
  every file under `data/margate/out/`, paths relative to `out/`, taken before any `sources/` edit.
  `regress_outputs.sh` must be able to compare against it (or re-snapshot before the first edit and
  prove the two snapshots are identical).
- **numpy LAPACK works** in the env python — but only with `C:/Users/Shadow/code/3duk-env/env/Library/bin`
  on PATH; without it `np.polyfit`/`svd`/`lstsq` exit silently with no output (OpenBLAS DLL not found).
  DESIGN.md §14's "no LAPACK" rule came from that. Keeping the geometry core pure-numpy is still
  right (portability to C++), but tests must not treat LAPACK calls as forbidden in the pipeline.
- **Blender 5.2 headless**: `bpy.types.RenderSettings.engine` enumerates only `BLENDER_EEVEE` in
  `-b` mode on this machine (Workbench is not selectable; use EEVEE — 480×270 renders in ~20 s
  including startup). glTF (`export_scene.gltf`, GLB) works. **Script paths must be short**: the
  session scratchpad path is 270 characters and Blender fails to open files there (MAX_PATH);
  `projects/one/Tools/blender/...` is fine.
- Overpass: only `overpass-api.de` answers; keep the mirror list but expect the other two to fail.
- The design docs were verified after synthesis; where a doc and BRIEF §4 disagree, §4 wins.
