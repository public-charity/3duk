# Tools/ue - building and driving the Unreal project headlessly

Everything here runs against `projects/one/Thanet.uproject` (UE 5.8.2, `C:/Program Files/Epic Games/UE_5.8`)
without opening the editor GUI. Alex's running editor (`MCPGameProject`, MCP port 55557) is never touched:
this project's MCP bridge is configured for port 55558 and does not start inside commandlets at all.

Commands are Git Bash from the repo root (`cd /c/Users/Shadow/code/3duk`).

## Editing and exporting a junction document

Load the actors covering the complete source document with `load_region` first.
After editing spline gizmos, call each edited spline component's
`sync_def_from_component()` to copy its points into the shared schema definition.
For edits made directly to `def`, use `sync_component_from_def()` instead.
Then call `unreal.StreetscapeEditorLibrary.refresh_document_junctions(source_path)`.
It validates every source actor is loaded exactly once, resolves the whole document,
preflights all splines/junctions, and updates trims and owner arm copies together.
Existing actor identities remain stable. A failed preflight changes nothing; a failed
actor rebuild restores the prior junction/profile state. This operation does not save.

`export_document_json(source_path, separate_output_path)` exports the current spline
definitions and referenced profiles while preserving all source junction definitions,
including disabled/unbuilt junctions, materials and document metadata. Missing actors,
duplicate IDs, changed registration, conflicting shared profiles and loss of a previously
buildable junction are errors. Source overwrite is refused. Source junction membership
and junction coordinates remain authoritative; this workflow edits existing spline IDs.
The old `export_site_json` refuses junction-bearing actors because a partial loaded actor
set cannot reconstruct every original junction. Keep the exported file for review/QC,
then use the normal editor save operation when the complete edit is accepted.

Headless regression: `diag_document_roundtrip.py --source site_x1_y12.json --out <dir>`.
It exports a complete real document, changes a non-owner arm by 15 cm, verifies the owner
patch responds, restores the original points, and proves the original document and
junction statistics return exactly. It checks actor paths and saved Content hashes too.

## Build

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/build.ps1
# or: projects/one/Tools/build.sh      (same thing; -Config DebugGame, -ProjectFiles to regenerate the .sln)
```

Runs the engine's bundled dotnet + UnrealBuildTool for `ThanetEditor Win64 Development` (UE_PLAN.md 5.1), log in
`projects/one/Saved/Logs/build.log`. Success is `Result: Succeeded` and these four DLLs:

```
projects/one/Binaries/Win64/UnrealEditor-Thanet.dll
projects/one/Plugins/Streetscape/Binaries/Win64/UnrealEditor-Streetscape.dll
projects/one/Plugins/Streetscape/Binaries/Win64/UnrealEditor-StreetscapeEditor.dll
projects/one/Plugins/UnrealMCP/Binaries/Win64/UnrealEditor-UnrealMCP.dll
```

Rules that bite on this install: `BuildSettingsVersion.V7` + `EngineIncludeOrderVersion.Unreal5_8` in both
targets, C4459 (a local shadowing a file-scope name) is an error, `ANY_PACKAGE` no longer exists. A full build
from nothing takes minutes (see the timings table below); incremental rebuilds of one module take well under one.

## Run an editor-Python script headlessly

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 01_bootstrap.py [-Args "--recreate"] [-Render] [-Log name.log]
```

This is `UnrealEditor-Cmd.exe Thanet.uproject -run=pythonscript -script="<Tools/ue/script> <args>" -unattended
-nopause -nosplash -stdout -FullStdOutLogOutput -NoLiveCoding -log=<script>.log` (UE_PLAN.md 5.2). Pass = exit 0,
`Python script executed successfully` in the log, and the script's last line `THANET_OK <script> <json>`;
a failure prints `THANET_FAIL ...` or a Python traceback and the commandlet exits non-zero. Logs land in
`projects/one/Saved/Logs/<script>.log` (stdout carries the same lines). `-Render` adds
`-AllowCommandletRendering` for steps that need an RHI (landscape import, probes, screenshots).

Scripts are stdlib + `unreal` only (UE's Python is 3.11 without numpy). `Tools/ue` reaches `sys.path` through
`UE_PYTHONPATH`, which the runner sets. `projects/one/Intermediate/PythonStub/unreal.py` - the authority for Python
names of engine and plugin classes - is written by `gen_python_stub.ps1` (see the facts below for why not by the
first run); regenerate it after every build that adds or renames reflected types.

| script | does | prints |
|---|---|---|
| `ue_common.py` | helpers (`project_dir`, `data_dir` from `StreetscapeSettings`, `parse_args`, `save_all`, `report`); run directly it proves the runner | `THANET_OK ue_common {...}` |
| `01_bootstrap.py` | `M_Street_Base` (BaseColor / Roughness parameters, magenta) + one `MI_<name>` `MaterialInstanceConstant` per SCHEMA.md 7 name (20), `M_Thanet_Landscape` (Masked; `LandscapeLayerBlend` grass/sand/rock/water -> BaseColor, `LandscapeVisibilityMask` -> OpacityMask), `DT_StreetMaterials` (`UStreetMaterialTable`, 20 entries, fallback = the magenta base), the 20 profile DataAssets under `/Game/Thanet/Profiles` (`StreetscapeEditorLibrary.import_profiles` from `schema/profiles`), then the folders under `/Game/Thanet`, the empty World Partition map `/Game/Thanet/Maps/Thanet` (`new_level(path, True)`), sun / sky light / sky atmosphere / height fog / volumetric cloud, save. Idempotent (assets are updated in place, the map is loaded and checked); `--recreate` deletes and rebuilds the map; `--skip-materials` / `--skip-profiles`; `--template /Engine/Maps/Templates/OpenWorld` starts from the engine template instead, removing its landscape, stale minimap and the 64 never-loaded HLOD packages it leaves behind | `THANET_OK 01_bootstrap {"materials": 21, "profiles": 20, "profile_uassets": 20, ...}` |
| `gen_python_stub.ps1` | writes `Intermediate/PythonStub/unreal.py` (see below) | `THANET_OK gen_python_stub {...}` |
| `run_ue_tests.ps1` | the Automation tests headlessly (below) | one `Success`/`Fail` line per test |
| `numpy_parity_dump.py` | (pipeline python, not UE) writes the numpy prototype's spline arrays for `Streetscape.Spline.NumpyParity` | `wrote ... numpy_parity.json` |
| `03_import_streetscape.py` | `--json <file-or-dir>` → one `AStreetscapeActor` per spline (label = spline id) with the components its `profile_ids` ask for, built from ONE `FStreetSamples`; `--player-start` drops an `APlayerStart` 2 m above the first point (yaw = bearing − 90); `--stats-out <file>` writes the first spline's `ActorStatsJson` (the parity file); `--save` saves and then re-reads every buffer to prove the PreSave/PostSaveRoot round trip; `--verify` re-opens a saved map, streams a `--region-radius-m` (default 20 km, the whole isle) and reports the rebuilt counts — **it fails on zero actors**, because in a World Partition commandlet "nothing streamed in" and "nothing there" are the same report; `--expect-actors N` compares the count against the manifest; `--slice i/n` imports one nth of a directory's documents (site scale needs several commandlets or the whole isle stays resident); `--no-preload` skips the 20 km pre-stream, correct only on a level known to hold no streetscape actor for these ids; `--stats-limit N` caps the per-actor stats work; **`--sample-mode bilinear\|triangulated`** pins which surface the street is draped from - `UStreetHeightfieldTerrain` defaults to the landscape's own **triangulated** rule (the ground the pawn collides with and the camera sees), while the numpy `Heightfield` still defaults to bilinear, so a run whose numbers go to `compare_stats.py` must pass `--sample-mode bilinear`; either way the rule is printed and carried in the report's `terrain` string | `THANET_OK 03_import_streetscape {"actors": 1, "per_actor": {...}, ...}` |
| `05_screenshot.py` | `--camera cam1\|cam2\|cam3\|all --actor <spline id> --out <dir or .png>` (or the free camera `--x --y --z --yaw --pitch`): the eye / target / FOV come from `StreetscapeEditorLibrary.actor_camera_json`, the C++ mirror of `Tools/blender/streetscape/render.py camera_defs`, so Unreal and Blender frame the same thing. Transient `SceneCapture2D` → `TextureRenderTarget2D` → `RenderingLibrary.export_render_target`, then the PNG is rewritten opaque. Between the first and the real capture it calls `StreetscapeEditorLibrary.finish_shader_compilation()`, which BLOCKS on `FShaderCompilingManager::FinishAllCompilation` — sleeping never worked because the compiler's results are applied on the game thread the script is holding. **Guards**: every capture reports `distinct_rgb` and `mean_luminance` and the run FAILS below `--min-distinct` (64) / `--min-lum` (6) or above `--max-lum` (250), and the report carries a material audit of the level. `--source final_ldr\|scene_hdr\|base_color`, `--ev <bias>`. **Needs `-Render`** | `THANET_OK 05_screenshot {"cameras": {"cam1": {"bytes": ..., "distinct_rgb": ..., "mean_luminance": ...}}, "materials": {...}}` |
| `compare_stats.py` | (any python, stdlib only) `--ue <ActorStatsJson> --numpy <Tools/blender/.../stats.json>`: length ±0.05 m, `n_samples`, overlap min/max, per-buffer AND per-material AND per-group verts/tris, marking strips, instance counts, `stations_identical` | one line per row then `PARITY OK` (exit 0) or `PARITY FAIL` (exit 1) |

| script | does | prints |
|---|---|---|
| `02_import_landscape.py` | reads `landscape_manifest.json` and drives `StreetscapeLandscapeImporter.ImportSite`: one World Partition `ALandscape` (2067 components / 140 streaming proxies for Thanet), the four ground-cover weightmaps and the `__LANDSCAPE_VISIBILITY__` mask that cuts the clip line, then the **shared-edge check** and the three gate probes (`grid`, `cliff`, `clip`). **Every gate can fail the script**: `grid.within_0_01_m`, `cliff.agree`, `cliff.slope_ok`, `clip.pass` and `shared_edge.ok` are branched on, and a failure prints `THANET_FAIL` with the list. `--max-shared-edge-h16 <n>` is the tolerance for the row/column two neighbouring tiles both write (0 = identical, which sound data gives; negative waives the gate and records `"waived": true`). `--probes-only` re-runs the probes on a saved map and streams the WHOLE world first so the grid probe sees every tile (`--no-load-all` for the cheap cliff+clip path, which then reports the grid probe as `skipped` instead of a false verdict); `--recreate-map`; `--no-grid` / `--no-cliff` / `--no-clip`; `--report <json>`. **Needs `-Render`** | `THANET_OK 02_import_landscape {"import": {...}, "grid": {...}, "cliff": {...}, "clip": {...}}` or `THANET_FAIL ... gate(s) failed: ...` |
| `04_probe.py` | six read-only modes on a saved map. `--points <csv> --landscape` → CSV `x,y,z_heightfield,z_landscape,z_landscape_collision,clipped,z_trace,blocked` (`--sample-mode bilinear\|triangulated` switches the terrain source's interpolation, which is how the 0.52 m disagreement with the landscape was measured); `--actor <id> --trace-from-above`; `--explorer`; `--landscape-info [--load-all] [--weights-at "x,y;..."]`; `--massing [--massing-at ...] [--refresh-collision]` — **fails when it finds zero massing actors** while `massing_manifest.files` is non-zero; `--materials [--load-all]` finishes shader compilation and reports the material every component would draw with and how many slots fell back to the engine default. `--load-radius-m` streams a box around each point; `--load-all` pulls the whole world in (~5 GB). **Needs `-Render`** | `THANET_OK 04_probe {"mode": ..., ...}` |
| `06_import_massing.py` | one `AStreetscapeMassingActor` per `massing/buildings_x{i}_y{j}.jsonl`, each extruding that tile's footprints from `skirt` to `base_z + h` into one `UDynamicMeshComponent`, material `MI_massing_grey` (created here, not in `01`, so the SCHEMA.md 7 material count stays 21). Checks the actor and building counts against `massing_manifest.json`. `--dir`, `--material`, `--no-save` | `THANET_OK 06_import_massing {"actors": 216, "buildings": 20121, "matches_manifest": true, ...}` |
| `make_cutout_manifest.py` | (pipeline python) writes a reduced `landscape_manifest.json` over a rectangle of tiles, for a fast partial import while debugging | `wrote ... n tiles` |
| `00_build_level.ps1` | **rebuilds the whole level with one command** and then asserts it: bootstrap → landscape → test stretch → massing → the site streetscape in `-StreetscapeSlices` commandlets → two assertion passes. `-Recreate` builds from nothing, `-AllowSeamH16 <n>` is passed to the landscape gate, `-Skip*` drops a step, `-AssertOnly` runs only the assertion | one `=== <step>` line per step, then `00_build_level: level rebuilt and asserted in N s` |
| `07_assert_level.py` | opens the saved map and compares what is in it against the adapter's manifests: streetscape actors vs `streetscape_manifest.splines_by_layer`, massing actors and buildings vs `massing_manifest`, landscape components / proxies vs the importer's own plan, plus a PlayerStart and a game mode with a default pawn. Counts come from the World Partition **external-actor packages via the asset registry** (nothing loaded), which is the only way to count 15,422 actors; `--census-only` reports without failing, `--no-load-all` skips the streaming pass | `THANET_OK 07_assert_level {"expect": {...}, "got": {...}, "problems": []}` |

`Tools/ue/shots/` holds the committed PNG captures; `*.png` is routed through LFS by the root `.gitattributes`
(`git check-attr filter -- projects/one/Tools/ue/shots/x.png` → `filter: lfs`).

## Run the Automation tests headlessly

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_tests.ps1 [-Filter Streetscape] [-Log tests.log] [-ParityJson <numpy_parity.json>]
```

This is exactly the UE_PLAN.md 2.13 command, `UnrealEditor-Cmd.exe Thanet.uproject -ExecCmds="Automation RunTests
<Filter>; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=<Log>` (the quoting of `-ExecCmds`
is why it is a PowerShell wrapper), followed by a summary read from `Saved/Logs/<Log>`: exit 0 when at least one
test completed and none failed, 2 on a failure, 3 when the filter matched nothing. UE 5.8 prints
`Test Completed. Result={Success}` / `Result={Fail}` (not the `{Passed}` / `{Failed}` wording of STAGES.md; the
wrapper accepts both). Unlike commandlets, a passing Automation run exits 0 on this machine.

Phase 2 tests (Plugins/Streetscape/Source/Streetscape/Private/Tests, all reading `schema/` and
`Tools/blender/tests/fixtures/expected.json`): `Streetscape.Spline.{Stations, Smoothing, Bank, Frames, TestStretch,
NumpyParity}`, `Streetscape.Noise.KnownAnswer`, `Streetscape.Json.{SchemaFixtures, RoundTrip}`,
`Streetscape.Sweep.Manifold`, `Streetscape.Geometry.ToDynamicMesh`, `Streetscape.Terrain.Bilinear` - 12 tests.
`TestStretch` builds `schema/examples/test_stretch.json` on the
adapter heightfield `data/thanet/out/unreal/landscape` and skips with an info line when that output is absent.

Phase 3 adds 11 renderer tests, all against the same `expected.json`: `Streetscape.Road.{Markings, DashPhase,
NullProfile}` (11 ribbon rows / 594 verts / 1060 tris, 17 centre dashes at 6 k .. 6 k + 4, the double yellow's line
centres 0.35 / 0.15 inward of the LEFT kerb line across the 6 → 8 m ramp, lift 0.004 measured on the road mesh),
`Streetscape.Edge.{Overlap, DropKerb, SplitMaterials, Barriers}` (row A at −0.02, row B at −0.03, three lip points
on the r = 0.02 arc, the D/S/E top flush to < 1e-12, hk 0.006 / 0.0655 and back edge 0.150, 19 / 18 / 23 / 21 posts,
three railing rails = six levels), `Streetscape.Seam.Rules` (DESIGN.md 5 rules 1-6 on straight_100, sine_5_50,
curve_R20_200, the half-grass switch and the no-drop-kerb variant), `Streetscape.Hedge.Volume` (closed manifold
before and after the noise, base row undisplaced, inner face stepping out by the wall/fence thickness, cards within
5 % of 12 per m²), `Streetscape.Rail.Gauge` (1.435 inner faces, 1.50485 centres, rail top 0.21375, 924 sleepers at
0.65, ballast 3.4 / 4.75) and `Streetscape.Perf.Tile` (informational ms per actor). **23 tests, 22 s wall clock including the 13 s editor start (measured 2026-09-08: `23 passed, 0 failed`).**
`NumpyParity` compares the C++ spline arrays with a numpy dump bit for bit when `-ParityJson` (env
`STREETSCAPE_PARITY_JSON`) points at one:

```bash
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH C:/Users/Shadow/code/3duk-env/env/python.exe C:/Users/Shadow/code/3duk/projects/one/Tools/ue/numpy_parity_dump.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_tests.ps1 -Filter Streetscape.Spline.NumpyParity -ParityJson C:/Users/Shadow/code/3duk/projects/one/Saved/Tests/numpy_parity.json
```

Measured 2026-09-08: `straight_100` s / width / z_ref / bank / edge_left, `sine_5_50` s, `curve_R20_200` s and the
cross-slope bank - every value bit-identical to numpy (the port reproduces np.interp, np.gradient, np.linspace,
np.sum's pairwise summation and float32 heightfield tiles on purpose; see StreetSplineMath.h).

## Measured on this machine (2026-09-08, RTX A4500, 4 cores)

| step | wall clock |
|---|---|
| `build.ps1` from a clean tree (61 actions: game module + Streetscape + StreetscapeEditor + UnrealMCP; the shared UnrealEd PCH dominates) | 3 min 06 s (UBA executor 133 s) |
| `build.ps1` again with nothing changed | 9 s |
| `01_bootstrap.py` first commandlet start ever (cold DDC; map created from the OpenWorld template, 65 landscape actors removed) | 57 s (script part 6.5 s) |
| `01_bootstrap.py` second run (map loaded, nothing to do) | 13 s (script part 0.2 s) |
| `01_bootstrap.py --recreate --template none` (delete 79 packages, empty WP map, 5 atmosphere actors) | 12 s |
| `gen_python_stub.ps1` (`-run=PythonOnlineDocs`, 627,730-line stub; includes a one-off 34 s Sphinx pip install) | 65 s |
| `build.ps1` incremental after editing one plugin .cpp (phase 2, 2026-09-08 10:xx) | 12-38 s |
| `run_ue_tests.ps1 -Filter Streetscape` (12 tests incl. editor start; NullRHI) | 21-22 s |
| `01_bootstrap.py` with materials + profiles (first creation of 23 material assets + 20 profile assets: 0.3 s + 0.5 s script time) | 12 s |
| `01_bootstrap.py` again (assets updated in place, map loaded) | 12 s |
| `01_bootstrap.py` with the site actor (391 heightfield tiles loaded, 20 profiles, DT_StreetMaterials attached) | 16 s (script part 4.6 s) |
| `run_ue_tests.ps1 -Filter Streetscape` after phase 3 (23 tests incl. editor start; NullRHI) | 22 s |
| `03_import_streetscape.py` on `schema/examples/test_stretch.json` (`--player-start --save`, one actor, 6362 verts / 9246 tris, 1691 instances) | 17 s (script part 3.0 s) |
| `03_import_streetscape.py --verify` (fresh commandlet, `load_region`, rebuild-on-load of the saved actor) | 14 s (script part 0.9 s) |
| `Streetscape.Perf.Tile` (build one actor from JSON: spline + all three renderers, mean of 5) | straight_100 0.75 ms (2320 v / 3500 t), curve_R20_200 1.32 ms (5439 / 7972), rail_R300_600 5.54 ms (35262 / 35248) |
| `02_import_landscape.py` on the whole of Thanet (391 tiles → 2067 components / 140 proxies, 12 region blocks, then the three gate probes) | 337 s script time, peak RSS 14.4 GB (regions 279 s, save 14 s) |
| `06_import_massing.py` on `data/thanet/out/unreal/massing` (216 actors, 20,121 buildings, 222,440 verts / 364,007 tris) | 21 s (`ImportMassing` itself 2.8-3.2 s), + the save of 216 external-actor packages |
| `04_probe.py --points` on 45 points with 29 400 m regions loaded | 10 s script time |
| `04_probe.py --landscape-info --load-all` (whole world streamed in to count components) | 12.5 s script time, RSS 5.1 GB |
| `04_probe.py --explorer` (spawn the pawn, build the input objects, read the bindings) | 3 s script time |
| `00_build_level.ps1 -Recreate` end to end (bootstrap, landscape, test stretch, massing, 12 streetscape slices, 2 assertion passes) | ~17 min |
| `02_import_landscape.py` full site through the region path (`--max-components 256`, 12 blocks) | 366 s, peak RSS ~19 GB |
| `02_import_landscape.py --probes-only` on a level holding only the landscape (whole world streamed, 14,347 grid points) | 15 s |
| `03_import_streetscape.py --slice i/12 --no-preload --save` (about 20 documents, 400-1800 actors) | 30-90 s each, ~14 min for the whole site |
| the whole site imported: 15,423 `AStreetscapeActor` external-actor packages | 15,787 packages in the level |
| `07_assert_level.py --no-load-all` (counts from the asset registry, nothing streamed) | 1 s |
| `07_assert_level.py` streaming the WHOLE isle (15,423 streetscape + 216 massing + 140 proxies, every mesh rebuilt on load) | **384 s, RSS 19.5 GB** |
| `03_import_streetscape.py --verify --census --expect-actors 15423` on the finished level (fresh commandlet, 20 km `load_region`, every mesh rebuilt from its saved definition) | **307.8 s**, 15,423 actors, 0 without samples, 0 with no buffer, peak RSS **21.77 GB** |
| `04_probe.py --actor-sample 16 --step-m 2.0` (16 of 12,815 road actors, 881 stations, a downward trace and an `ALandscape` height query at each) | 220 s |
| **D5, 2026-09-09: the whole network in one commandlet** — `03_import_streetscape.py --purge --json <DATA>/streetscape --first site_x16_y15.json --census --save --expect-actors 15422 --player-start --allow-no-terrain 1` | first run **606.8 s** (map 0.1 s, purge of an empty level 6.5 s, 246 documents -> 15,422 actors **236.1 s**, census 4.0 s, save **366.6 s**); the final run, which purged a full level first, **914.9 s** (purge of 15,423 actors **275.8 s**, import **261.0 s**, census 4.1 s, save **374.0 s**) |
| the same import, measured first on 1 document and then on 10 (819 actors) before committing to it | 10 documents: 4.3 s build + 21.5 s save (38 packages/s); the whole site extrapolated to 81 s + 400 s and came in at 236 s + 367 s |
| RSS during that import | 1.65 GB after `load_level`, **18.54 GB peak** at 15,422 actors on the first run (0.95 MB per actor, linear from 518 actors / 4.45 GB), 19.71 GB after the save; the final run peaked at **21.39 GB** because the purge held the previous 15,423 actors before it built the new ones |
| what those 15,422 actors are | 12,815 roads + 2,325 barriers + 282 rail, **1,072.4 km**, 745,642 stations, 30,624 renderer components + 15,422 overlays + 1,697 ISM components, **19,705,600 verts / 29,006,476 tris**, 575,381 instances (464,753 leaf cards, 76,715 sleepers, 30,164 round posts, 3,749 square posts), 20,700 marking strips |
| on disk | 15,788 external-actor packages in the level (15,423 streetscape + 216 massing + 140 landscape proxies + 9), `Content/` **2.1 GB**; a streetscape package is 65 KB median |
| `06_import_massing.py --no-preload` on a level that already holds the whole network | `ImportMassing` itself 2.4 s (216 actors, 20,121 buildings, 222,440 verts / 364,007 tris); 281.7 s total, of which the Python-side `load_region` that `--no-preload` was meant to skip cost ~180 s and 21 GB before it was removed |

Commandlets run with the null RHI (no `-AllowCommandletRendering`), so no shader compilation happened; expect the
first `-Render` run of the landscape phase to be the slow one.

Facts found on this machine that the scripts account for:

- Every editor start logs `Visual C++ redistributable version 14.44.35211.0 is outdated` at **Error** severity
  (`Engine/Source/Runtime/ApplicationCore/Private/Windows/WindowsPlatformApplicationMisc.cpp:121`, unconditional under
  `WITH_EDITOR`, no switch), so the commandlet framework prints `Failure - 1 error(s)` and exits 1 even when the script
  succeeded. `run_ue_python.ps1` therefore reads the log after the run: exit 0 only if `Python script executed
  successfully` is present and that advisory is the only counted error; any other error or a Python failure keeps the
  engine's non-zero code. Updating the redistributable needs admin and is Alex's call.
- `bDeveloperMode=True` does not write `Intermediate/PythonStub/unreal.py` in a commandlet
  (`PythonScriptPlugin.cpp:1604`, `!IsRunningCommandlet()`); `gen_python_stub.ps1` gets it through the
  `PythonOnlineDocs` commandlet, which also pip-installs Sphinx into the engine's Python and writes Sphinx sources
  under `Engine/Plugins/Experimental/PythonScriptPlugin/SphinxDocs/` (one-off side effects, harmless).
- `PythonScriptPluginSettings.AdditionalPaths` resolves against `Engine/Binaries/Win64`, not the project
  (`PythonScriptPlugin.cpp:1277` -> `Paths.cpp:1584`), so the runner sets `UE_PYTHONPATH` instead.
- A non-commandlet editor session (the Automation test run) DOES write `Intermediate/PythonStub/unreal.py` under
  `bDeveloperMode=True`, so after `run_ue_tests.ps1` the stub is current without `gen_python_stub.ps1`.
- `Material.expressions` is protected from Python (`get_editor_property` raises); the bootstrap records the landscape
  layers it created instead of reading them back.
- Phase 3 facts:
  - a plain `virtual FString Describe() const` is invisible to `unreal.py`; only `UFUNCTION`s are, hence
    `UStreetTerrainSourceBase::DescribeSource()`.
  - in a World Partition commandlet nothing is loaded until `StreetscapeEditorLibrary.load_region(...)` runs, so
    `streetscape_actor_ids()` returns `[]` right after `load_level` - `03 --verify` and `05_screenshot.py` both
    load the site first (radius 20 km around the origin) and only then look the actor up.
  - `FObjectPreSaveContext` has no `IsSaving()` in 5.8 (`ObjectSaveContext.h:243`); the renderer's `PreSave` gates
    on `!IsCooking() && !IsProceduralSave()` instead.
  - `SceneCapture2D`'s Python properties are `capture_component2d`, then `capture_every_frame` /
    `capture_on_movement` (no `b_` prefix). `UTextureRenderTarget2D::UpdateResource` is not exposed either, so the
    target comes from `RenderingLibrary.create_render_target2d`. The first `-Render` commandlet on this machine
    spends ~3.5 min compiling SM6 shaders before the script runs; later ones reuse the DDC (~55 s startup).
  - every scene-capture source writes **alpha 0**, so the exported PNG is fully transparent and looks blank in a
    viewer; `05_screenshot.py` rewrites it opaque with stdlib `zlib` and reports `distinct_rgb` so a capture that
    really rendered nothing fails instead of shipping a blank file.
  - the level has **no landscape yet** (`02_import_landscape.py` is stage 1's), so a lit capture is mostly empty
    space around the streetscape meshes; `--source base_color` shows albedo without depending on lighting, and is
    what `shots/` holds.
  - **open**: in a `-AllowCommandletRendering` commandlet the `UDynamicMeshComponent`s render with the engine
    default grid material even though the site actor has `DT_StreetMaterials`, `Resolve()` logs no fallback
    warning and `Commit` logs no missing-table warning. Not shader compilation - a 45 s `--warm-s` between
    captures produces byte-identical PNGs (58369 / 35355 / 173004 bytes either way). The geometry itself is
    correct in the captures (road ribbon, kerb line, wall, and the overlay drawn as a magenta line at
    `(255, 64, 229)` = the component's linear `(1.0, 0.25, 0.9)`). Next step is to look at the same map in the GUI,
    where `ConfigureMaterialSet`'s effect on the component is directly visible.
  - two save/reload bugs the round trip found, both fixed: setting a `UPROPERTY` from C++ does not dirty the
    package, so the site actor's material table was not saved and every renderer slot came back as
    `WorldGridMaterial` (`EnsureSiteActor` now calls `Modify()` + `MarkPackageDirty()`, and `Commit` warns when the
    table is missing); and the instanced `UStreetHeightfieldTerrain` serialises but its `FStreetHeightfield::Tiles`
    is plain C++ and does not, so a re-opened map returned "heightfield (not loaded)" with 0 tiles and every
    rebuild-on-load would have sampled no ground and flattened the street to z = 0 (`ResolveTerrainSource` now
    re-`Load()`s it).
  - `FStreetGeometry::MeasureLateralOverlap` had a real parity bug found by `Streetscape.Seam.Rules`: it filtered
    the visible kerb rows against a fixed `-tuck_depth` where `mesh.measure_lateral_overlap` uses the per-station
    `h0 - tuck_depth` (`h0` = the camber height at the kerb line). On an 8 m carriageway at 2.5 % camber `h0` is
    −0.05, so a 6 mm drop-kerb top fell below the fixed threshold and the overlap came back NaN at those stations.
    Fixed to the numpy rule; `min`/`max` had hidden it because they skip NaN.
- Phase 4 facts:
  - **`UDynamicMeshComponent`'s constructor sets `UCollisionProfile::NoCollision_ProfileName`**
    (`GeometryFramework/Private/Components/DynamicMeshComponent.cpp:92`). `SetComplexAsSimpleCollisionEnabled(true,
    true)` only chooses *which* geometry the body uses, so on its own it cooks a triangle mesh that no trace and no
    capsule can ever reach: a downward line trace over a finished road or a 57 m tower block hit the landscape
    underneath. `UStreetRendererBase::ApplyCollision` and `AStreetscapeMassingActor::RefreshCollision` now also set
    `BlockAll` + `QueryAndPhysics`. The profile is serialised, so actors saved before the fix stay uncollidable
    until they are re-imported.
  - **`ALandscapeProxy::GetHeightAtLocation(..., EHeightfieldSource::Complex)` still returns a height inside a
    visibility hole.** The collision heightfield keeps the sample and only marks its material as a hole, so
    `ProbeHeightM(..., bUseCollision=true)` is *not* a hole test. The honest test is a line trace: over the cut
    side of the clip line it passes straight through (measured: 37 of 37 kept points block, 0 of 8 cut points do).
  - **Two ways a re-import silently doubles a World Partition level, both fixed.** (a) `TActorIterator` in a
    commandlet sees only what is streamed in, so "replace the actor with this id" replaced nothing and left the old
    one behind - `ImportStreetscapeJson` and `ImportMassing` now `LoadRegion(origin, 20 km)` before they look.
    (b) `UWorld::EditorDestroyActor` removes the actor from the world but leaves its external-actor `.uasset` on
    disk, so it is back the next time the map opens: `UStreetscapeEditorLibrary::DeleteActorsAndPackages` collects
    `AActor::GetExternalPackage()` and calls `ObjectTools::CleanupAfterSuccessfulDelete` (`ObjectTools.h:313`).
    Measured before the fix: three `AStreetscapeActor`s for one `authored:trinity_square`
    (`--explorer` reported `overlay_components_toggled: 3`), 50 massing actors over 25 tiles, and 624
    `__ExternalActors__` packages. `ImportMassing` now also re-uses one actor per tile instead of respawning.
  - **`ULandscapeInfo::XYtoComponentMap` only holds components of proxies that are streamed in.** A fresh
    commandlet that loads a few 400 m regions reports 536 components / 34 proxies for the same landscape that
    reports 2067 / 140 after `load_region(origin, 20 km)` (~5 GB RSS). Always say which you measured.
  - **Slope is an operator, not a number.** `sources/derive/05_*.py:79-80` computes `np.gradient` (interior central
    differences, `(a[k+1] - a[k-1]) / 2`) so a one-cell cliff face is averaged over 2 m; walking adjacent post
    pairs measures the same face over 1 m and reads steeper. On tile (17, 16) the pipeline's own float32 DTM gives
    81.722° central / 84.654° pairwise, and the imported `.r16` gives 81.722° / 84.655° - the landscape is not
    losing the cliff, the two numbers are two different derivatives. `02_import_landscape.py` reports both and
    compares like with like.
  - `unreal.SoftClassPath` has no exported fields, so `str()` on `GameMapsSettings.global_default_game_mode` prints
    `<Struct 'SoftClassPath' ... {}>`. Resolve it with `unreal.SystemLibrary.get_class_from_soft_path(scp)`.
    `03_import_streetscape.py --set-game-mode /Script/Thanet.ThanetGameMode` writes the class onto the map's
    `WorldSettings.default_game_mode` so the map does not depend on the project default.
  - `UCameraComponent` exposes `relative_location` but not `use_pawn_control_rotation` to Python; and
    `USceneComponent.get_relative_location()` is not a Python method - use `get_editor_property("relative_location")`.
  - PIE cannot be driven from a commandlet. `04_probe.py --explorer` spawns an `AThanetExplorerPawn`, calls the
    now-`UFUNCTION` `BuildInputObjects()` and reads `DescribeBindings()` back, which proves the mapping context,
    the actions and their keys exist - it does not prove the pawn walks.
- Phase 2 engine facts the plugin relies on: `FJsonObject::Values` keys are `UE::TSharedString<TCHAR>` in 5.8
  (`Dom/JsonObject.h:237`, case-insensitive; `FString(*Key)` to read); `FJsonSerializer::Deserialize` only accepts a
  top-level object or array (scalar notes are parsed as `[value]`); GeometryCore's front-face normal is
  `cross(v2 - v0, v1 - v0)` (`VectorUtil.h:80-87`, "Unreal has Left-Hand Coordinate System"), so `ToDynamicMesh`
  keeps the JSON winding after the (100, -100, 100) mirror - the two handedness flips cancel (UE_PLAN.md 2.7 said
  "reversed"; measured: reversing gives UE face normals pointing away from the carriageway); UE's `PI` is a float
  literal (`3.1415926535897932f`) - tests use `UE_DOUBLE_PI`.

## Parity with the Blender/numpy prototype (phase 3 gate)

```bash
# 1. bootstrap (materials, profiles, map, site actor)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 -Script 01_bootstrap.py
# 2. import the test stretch and write its ActorStatsJson
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 -Script 03_import_streetscape.py \
  -Args "--json C:/Users/Shadow/code/3duk/projects/one/schema/examples/test_stretch.json --player-start --save \
         --stats-out C:/Users/Shadow/code/3duk/projects/one/Saved/Tests/ue_trinity_square.stats.json"
# 3. compare it with the numpy stats.json, field by field
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/compare_stats.py \
  --ue projects/one/Saved/Tests/ue_trinity_square.stats.json \
  --numpy projects/one/Tools/blender/renders/trinity_square.stats.json
```

Measured 2026-09-08: **81 rows compared, 0 mismatches, `PARITY OK`** - `length_m` 171.405484, `n_samples` 116,
overlap min = max = 0.04 on both sides, `road` 1794 v / 2756 t (tarmac 1276/2300, white_paint 266/208,
yellow_paint 252/248), `edge_left` 1508/2318, `edge_right` 2696/3448 (six materials), `hedge_right` 364/724,
31 marking strips, 18 `post_round` + 23 `post_square` + 1650 `leaf_card`, `stations_identical` true for every
buffer. The same comparison passes against the stats taken after saving and re-opening the map in a fresh
commandlet (`--verify`), which is the PreSave/PostSaveRoot + rebuild-on-load round trip: on re-open the buffers
only exist because `OnRegister` found an empty `UDynamicMesh` and `PostRegisterAllComponents` rebuilt it.

**Pin the sampling rule on both sides of that comparison.** Since the junction round, the terrain SOURCE
(`UStreetHeightfieldTerrain`) defaults to the landscape's own TRIANGULATED interpolation - the ground the pawn collides
with and the camera sees - while the numpy `Heightfield` dataclass still defaults to bilinear. So the import above needs
`--sample-mode bilinear` to be comparing one surface with itself; the rule it used is printed in the log and carried in
the report's `terrain` string, so no parity run is ambiguous about which ground it stood on.

The test stretch's own `junctions[]` entry has ONE arm, and a junction needs three, so the plan skips it and the trim is
`(0, 0)`. The FD row is therefore the same measurement it was before junctions existed - which is exactly what makes it
a regression check on the port rather than a new number.

Tolerances in `compare_stats.py` are not knobs. Counts are compared exactly; only `length_m` has a tolerance
(±0.05 m, the figure UE_PLAN.md 8.7 names). A mismatch means one of the two implementations is wrong.

**Heights differ by 2.6 mm against the committed `trinity_square.stats.json`, and that is the terrain source, not
the code.** That file was built on `data/margate/out/terrain` (GDAL float32 DTM) shifted +5120; the Unreal run
uses `data/thanet/out/unreal/landscape`, whose r16 tiles quantise height to 1/128 m. Measured: max |Δz_ref|
0.0025 m, max |Δz_raw| 0.0026 m, `bank_min` −2.83098 vs −2.839497. Rebuilding the numpy side on the *same*
landscape directory makes every number identical to the last digit:

```bash
PYTHONPATH=projects/one/Tools/blender C:/Users/Shadow/code/3duk-env/env/python.exe -m streetscape.build \
  --site projects/one/schema/examples/test_stretch.json --terrain data/thanet/out/unreal/landscape --out <scratch>
# -> z_ref_probe, z_raw_probe, bank_min/max, step_min/max, mandatory_stations all identical; PARITY OK
```

## What was eating the level

The audit before this pass recorded that the saved map lost its test-stretch actor "during a sequence of
read-only-looking gate commands" and that the mechanism was unidentified. It is `01_bootstrap.py`.

`remove_template_landscape()` exists because `--template /Engine/Maps/Templates/OpenWorld` brings its own
landscape, minimap and 64 HLOD packages, none of which this project wants. It ran on **every** bootstrap,
including the idempotent "the map already exists, load it and check it" path, and its class list contains
`Landscape`. So the second time anyone ran `01_bootstrap.py` on a level that already held the imported Thanet
landscape, the log said

```
[thanet] removing template actor Landscape_thanet (Landscape)
```

and the parent `ALandscape` was destroyed. What was left on disk was 140 `LandscapeStreamingProxy` packages and
no landscape actor - a level that looks complete to a file count and fails every landscape probe. The proxies
survived only because a World Partition commandlet has not streamed them in, so `get_all_level_actors()` never
saw them; a run that HAD streamed them would have deleted those too.

It now removes template actors only on the run that actually created the map from a template, and otherwise says
what it is keeping. `--recreate` remains the switch that means "throw the map away".

## Two more the gates found

**The landscape's closed upper edge had no height.** `ALandscapeProxy::GetHeightAtLocation` finds the component
with `FMath::FloorToInt32(ActorSpaceLocation / ComponentSizeQuads)` (`LandscapeCollision.cpp:2709`), so a point
exactly on the last component's far boundary floors to an index one past the end and comes back unset. Thanet's
padding goes north and east, which makes the site's whole southern edge (local y = 0) that boundary: the grid gate
found 57 lattice points where the landscape reported no height and the heightfield reported -1.7 .. -2.6 m.
`ProbeHeightM` now retries 5e-4 quads inside the extent - four orders of magnitude below the 1/128 m height
quantum - and only when the point is genuinely inside. `landscape_none` went 57 -> 0.

**`03_import_streetscape.py --json <dir>` fed `streetscape_manifest.json` to the strict document loader**, which
is a hard failure at the very end of a site import (the manifest sorts last). Directory imports now skip
`*_manifest.json`.

## Two defects the new gates found in the level itself

**The region path was losing the parent `ALandscape`.** `ImportSite` bounds its peak memory with
`CollectGarbage(RF_NoFlags, bPerformFullPurge=true)` after every 16x16-component block. A freshly spawned World
Partition actor that no loader adapter pins is collectable, and the parent `ALandscape` is exactly that: the
saved Thanet map came back with **140 `LandscapeStreamingProxy` actors and no `ALandscape` at all**, so
`FindLandscape()` returned null and `02_import_landscape.py --probes-only`, `04_probe.py --landscape-info` and
`--points --landscape` all failed on a level that looked complete. The same import through the single-Import path
(a 2x2 cutout, `GateClean`) kept its parent - `{"Landscape": 1, "LandscapeStreamingProxy": 4}` on disk - which is
what pinned the cause to the region loop. `ImportSite` now roots the actor for the duration, saves its package
with each block's proxies, marks it dirty before the final save, and reports `landscape_actor_package` and
`landscape_actor_package_dirty_after_save` so the read-back proof is in the import report.

**One street on the isle has no ground under any station.** `roads:132194822:0` in `site_x7_y7.json` is a 5-point
fragment that lies **entirely between 0.01 m and 0.19 m inside the clip line**. `FStreetHeightfield::Sample` needs
all four corners of its 1 m cell to be unclipped, so within about a metre of the cut it returns nothing: every
station sampled NaN, `FillNanAlong` had nothing to hold, and the street would have been built flat at z = 0 at the
very edge of the world. The import now names it and refuses unless `--allow-no-terrain N` says how many such
splines are being accepted. The lasting fix is upstream/coordinated: `Sample` should fall back to the nearest
valid corner near the clip line (the landscape itself renders and collides right up to the line - measured 6 mm),
and the numpy `Heightfield.sample` has to change with it.

## Gates that can fail (the integrity pass, 2026-09-08)

Everything in this section was added because a check existed but could not report a failure. The rule now is that
a verification mode which finds nothing FAILS, and a probe whose verdict is False FAILS the script.

| was | is |
|---|---|
| `02_import_landscape.py` printed `THANET_OK` and exited 0 with `grid.within_0_01_m: false` - the four verdicts were data, nothing branched on them | the script branches on `grid.within_0_01_m`, `cliff.agree`, `cliff.slope_ok`, `clip.pass` and the importer's `shared_edge.ok`, and prints `THANET_FAIL ... gate(s) failed: ...` |
| `--probes-only` streamed only the cliff tile and the clip line, so `probe_grid` (which walks every tile) left 8217 of 9775 points unstreamed and could never pass | `--probes-only` streams the whole world by default; `--no-load-all` keeps the cheap path and reports the grid probe as `"skipped": "..."` instead of a verdict |
| `probe_grid`'s lattice was `tile_m // (per_tile + 1)` with a, b in 1..5, i.e. offsets 85..425 of a 512 m tile - it could never land on a tile edge | offsets `0, 85, 170, 255, 340, 425, 512`, so tile-boundary rows and columns are in the gate |
| the importer measured the shared-edge disagreement, wrote `shared_edge_max_h16_delta: 2267` into the report and neither warned nor failed; and it only saw the pairs whose neighbour happened to be read first (190,831 of 378,081 samples) | `CheckSharedEdges` compares every neighbouring pair from the tile edges it already holds - complete and order-independent - and `ImportSite` returns an error above `MaxSharedEdgeH16Delta` (default 0) |
| `03_import_streetscape.py --verify` printed `THANET_OK ... "actors": 0` after streaming a 1 km radius around UE (0, 0), which is the site's south-west corner - 11.5 km from the test stretch | 20 km radius, and zero actors is a `THANET_FAIL`; `--expect-actors N` checks the count against the manifest |
| `04_probe.py --massing` printed success with 216 actors' worth of zeros when nothing was streamed in | zero actors against a non-empty `massing_manifest.files` is a `THANET_FAIL` that names the missing loading mode |
| `05_screenshot.py` reported `THANET_OK` for a frame that was black apart from an overlay line, because the only guard was `distinct_rgb < 4` | `distinct_rgb`, `mean_luminance` and configurable thresholds, plus a material audit of the level in the report |
| an unreadable heightmap tile was `continue`d in `FStreetHeightfield::LoadLandscapeDir`, so every street over it sampled NaN, was forward-filled along s and built flat | it returns false with the filename, as the wrong-size case already did |
| an unreadable weight or visibility file was `continue`d in the landscape importer, leaving that tile's ground cover at zero | both are hard failures, like the wrong-size case two lines below them |
| a street whose stations all sampled NaN was built flat at z = 0 and the import still returned success | `ImportStreetscapeJson` collects the `no terrain under any station` warnings and returns -1, naming the splines |
| STAGES 5.7's "C++ check that the edge renderer's stations equal the road renderer's" existed only as a report field computed when someone asked for `ActorStatsJson` | `RebuildAllChecked` compares every renderer buffer's station set against `FStreetSamples::S` on every build of every spline, and fails the build |
| the massing reader dropped an unparsable JSONL line and defaulted a missing `skirt` silently | `FStreetMassingStats::SkippedLines` / `SkirtDefaulted` / `SkippedBuildings`, warned about per tile and summed in the import report |
| no `AStreetscapeActor` component was ever attached to its root: the root spline was left Movable while every child is Static, so `AttachToComponent` refused all ~16 per street | `AStreetscapeActor` sets the root spline to `EComponentMobility::Static` |
| the `PlayerStart` stood 1.5 m above the first waypoint while BRIEF/STAGES FD.4 and this file all said 2 m | 2 m, as documented |

## Gates that were proved to fail (D4, 2026-09-09)

The 2026-09-08 pass above made the verdicts branch. It did not make any of them *fail on purpose*, and a gate
nobody has watched fail is a line of code that has always been true. This round finished the job in two halves:
the gates that were still missing, and a driver that breaks one thing at a time and requires the failure.

### What was still soft

| was | is |
|---|---|
| `02_import_landscape.py` reported `components`, `proxies` and `extent` and compared none of them: an import that built 1,700 of 2,067 components printed `THANET_OK` with the shortfall inside the JSON | a `counts` probe compares components / proxies / extent / `tiles_read` against the plan the same manifest produced, and `counts.ok` is a gate |
| a probe that could not run reported `{"skipped": ...}` and `check()` logged one line and returned - `--no-load-all` and a clip-less manifest both silently removed a gate | a skipped gate is a **failure** unless `--allow-skipped-gates` is passed, and the summary carries `gates_skipped` |
| `06_import_massing.py` computed `matches_manifest` and `buildings_match_manifest`, printed them, and exited 0 whatever they said - including on 0 actors | actors <= 0, `ImportMassing.failed > 0`, and either mismatch are `THANET_FAIL`; `--allow-mismatch` accepts them loudly and records `accepted_problems` |
| `04_probe.py --explorer` printed the wiring of a level with no game mode, no pawn and no `PlayerStart` as a success | all three are failures |
| `04_probe.py --points` reported success on a CSV that produced 0 rows, and on points the landscape has no height for | both are failures |
| `04_probe.py --materials` counted `slots_using_engine_default` and `slots_null` and passed anyway - the checkerboard in a capture | any such slot fails unless `--allow-default-materials` |
| `04_probe.py --landscape-info` reported `ground_layers_missing` and `has_visibility_layer: false` as data | both are failures |
| a `tiles[]` entry that was not a JSON object was `continue`d in `ReadManifest`: the manifest declared 391 tiles, the importer read 390, and only `tiles_read` (which nothing compared) knew | `OutProblem`, and the import stops |
| `FindOrAddLandscapeProxy` returning null was `continue`d in `AddComponentsForBlock`: the region came out with fewer components and the import still said `ok` | the block fails and names the component coordinate |
| a landscape material that did not load was a `Warning` and the whole isle drew with the engine default | it fails; pass an empty `--material` to mean "the engine default, on purpose" |
| `ImportMassing` streamed the whole world unconditionally - at site scale that is 15,422 streetscape actors and every one of their meshes rebuilt (19 GB) just to replace 216 boxes | `bPreloadWorld` (default true, `06 --no-preload` to switch it off) with the same loud warning the streetscape path has, recorded as `report.preloaded` |

### Each gate, broken on purpose

`Tools/ue/gate_proofs.py` (pipeline python, not editor python) builds a 2 x 2-tile cutout of the Margate window
with `make_cutout_manifest.py`, then for each gate breaks exactly one thing, runs the real command against a
scratch map `/Game/Thanet/Maps/GateProof`, and requires a **non-zero exit AND a `THANET_FAIL` naming that gate**.
The clean cases run the same commands on the same un-broken cutout and require `THANET_OK`, so a case that
"fails" because the whole path is broken does not count as proof. Run 2026-09-09:
`C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/gate_proofs.py`
-> **12 of 12 proved, 3 of 3 clean runs pass** (`Saved/Tests/gate_proofs.json`, per-case logs
`Saved/Logs/gate_<id>.log`).

| case | gate | script | verdict | the failure it printed |
|---|---|---|---|---|
| `corrupt_r16` | importer: a heightmap tile that is the wrong size | `02_import_landscape.py` | exit -1 | 02_import_landscape import_site failed: assembly: hm_x0_y0.r16: 526330 bytes, expected 526338 |
| `missing_tile_file` | importer: a manifest tile whose file is not on disk | `02_import_landscape.py` | exit -1 | 02_import_landscape import_site failed: assembly: cannot read hm_x1_y1.r16 |
| `malformed_tile_entry` | importer: a tiles[] entry that is not an object | `02_import_landscape.py` | exit -1 | 02_import_landscape manifest rejected: tiles[4] is not a JSON object |
| `missing_material` | importer: the landscape material does not load | `02_import_landscape.py` | exit -1 | 02_import_landscape import_site failed: landscape material /Game/Thanet/Materials/M_Does_Not_Exist.M_Does_Not_Exist did not load (pass an empty --material to accept the engine default on purpose) |
| `grid_probe_mismatch` | 02 gate grid.within_0_01_m | `02_import_landscape.py` | exit -1073741819 | 02_import_landscape gate(s) failed: grid.within_0_01_m is False |
| `component_count` | 02 gate counts.ok (components / proxies / extent / tiles_read vs the plan) | `02_import_landscape.py` | exit -1073741819 | 02_import_landscape gate(s) failed: counts.ok is False |
| `skipped_gate` | 02: a gate that did not run is not a gate that passed | `02_import_landscape.py` | exit -1 | 02_import_landscape gate(s) failed: grid.within_0_01_m did not run: --no-load-all streams only the cliff tile and the clip line; probe_grid walks every tile (pass --allow-skipped-gates to accept that on purpose); counts.ok did not |
| `verify_zero_actors` | 03 --verify on a level with no streetscape actor | `03_import_streetscape.py` | exit -1073741819 | 03_import_streetscape verify found 0 AStreetscapeActor in /Game/Thanet/Maps/GateProof after streaming a 20000 m radius - 'nothing streamed in' and 'nothing there' look identical, so this is a failure, not a pass |
| `census_zero_actors` | 04 --census on a level with no streetscape actor | `04_probe.py` | exit -1 | 04_probe the level holds 0 AStreetscapeActor (streamed: True) |
| `explorer_no_player_start` | 04 --explorer with no PlayerStart | `04_probe.py` | exit -1073741819 | 04_probe explorer wiring: the level has no PlayerStart, so Play would spawn at the world origin |
| `materials_no_components` | 04 --materials with nothing to audit | `04_probe.py` | exit -1073741819 | 04_probe no streetscape or massing components in the level (use --load-all to stream them in) |
| `massing_count` | 06 actors != massing_manifest.files | `06_import_massing.py` | exit -1073741819 | 06_import_massing massing import gate(s) failed: actors 3 != massing_manifest.files 10; buildings 233 != massing_manifest.buildings 20121 |
| `clean_import` / `clean_import_final` | the same import of the same un-broken cutout | `02_import_landscape.py` | exit 0 | `THANET_OK` - 25 of 25 components, `counts.ok` true |
| `clean_probes` | the same probes against the landscape that was just imported | `02_import_landscape.py --probes-only` | exit 0 | `THANET_OK` - `grid.within_0_01_m` true over 1,058 lattice points |

Two notes on the exit codes. `-1` is the Python failure the runner refuses to override; `-1073741819` is an
access violation while the editor tears down a level holding the whole isle, which the runner also refuses to
override because there is no clean `Warning/Error Summary` to read. Both are non-zero, which is the contract.
And the ordering matters: the four cases that recreate the map and then fail leave it with no landscape, so the
driver re-imports the clean cutout before the `--probes-only` cases - without that they failed with "no
ALandscape", which is a failure for the wrong reason and the driver scored them NOT PROVED (run 1,
`Saved/Tests/gate_proofs_run1.json`).

## The whole network in the level (D5, 2026-09-09)

Alex's report was that the roads fuse with the landscape; the round before this one fixed that in the data. The
other half of "the isle is not in the level" was simpler and worse: **only the authored test stretch was in it.**
The site import had been run once (the row above records its 15,423 packages), and the terrain round's
`02_import_landscape.py --recreate-map` deleted the map to re-import the conformed landscape, taking every
streetscape and massing actor with it. Nothing noticed, because nothing compared the level against the manifests
until `07_assert_level.py` was run by hand.

### Granularity: measured, then chosen

DESIGN.md 10 says one `AStreetscapeActor` per spline. That is 15,422 actors, so it was measured before it was
believed - one document, then ten (819 actors), then the whole site:

| | 10 documents / 819 actors | 246 documents / 15,422 actors |
|---|---|---|
| build (spline + every renderer) | 4.3 s | 236.1 s (65 actors/s) |
| save (one external-actor package each) | 21.5 s (38 packages/s) | 366.6 s (42 packages/s) |
| RSS | +0.11 GB over a 4.45 GB base | **18.54 GB peak**, 0.95 MB per actor, linear |
| on disk | 53 MB | 1.9 GB (65 KB median per package) |

So the per-spline choice costs about **1 MB of editor memory and 65 KB of disk per street**, and both scale
linearly. 18.5 GB fits in 28 GB with the landscape and the massing already resident, which is why the whole site
imports in **one** commandlet (606.8 s end to end) rather than the twelve slices `00_build_level.ps1` still uses
by default. The slices remain the supported route because they bound the peak at about 6 GB; the single run is
faster and was used here so that one census covers the whole network at once.

The alternative - one actor per 512 m tile, 246 actors - was not taken. It gives the same component and vertex
count with a 512 m streaming cell instead of a per-street one, and it makes "replace the street with this OSM id"
a rebuild of the whole tile. Nothing measured here argues for it.

**Meshes are not serialised and there is no HLOD.** Each renderer's `PreSave` stashes and empties its
`UDynamicMesh` and the actor's `PostSaveRoot` puts it back, so a package holds the spline and its profiles, not
its triangles - that is what keeps a 19.7-million-vertex network inside 1.9 GB and why a re-open rebuilds every
mesh (measured: 384 s to stream and rebuild the whole isle). It is also why `AStreetscapeActor` sets
`bEnableAutoLODGeneration = false` (`StreetscapeActor.cpp:42`): an HLOD build runs over what is in the package,
and at save time that is an empty mesh. HLOD for the streets needs a static-mesh bake first, which is a later
round.

### One spline in 15,422 has no ground

`roads:132194822:0` in `site_x7_y7.json` is five waypoints spanning 0.2 m at local (3908.6, 3925.6), which is
**1.2 cm inside the clip line** - every terrain cell around it is NoData, so it sampled no ground at any station
and would have been built flat at z = 0. The import refused it (`--allow-no-terrain 0`, the honest default) and
named it; this level was then built with `--allow-no-terrain 1`, which logs it as `ACCEPTED` and counts it. The
fix belongs upstream in `sources/adapters/unreal.py` - a run of 5 points spanning 0.2 m is degenerate whether or
not it has terrain.
### The defect that only shows up at site scale: roads that do not stream

The first full import produced a level whose counts were all correct - 15,423 actors on disk, 15,423 streamed and
rebuilt on re-open, 19.7 M vertices - and whose **street-level captures had no streets in them.** The massing
boxes were there, the landscape was there, the ground was bare green where a road should be. The material audit
in the same capture reported 1,793 loaded components resolving to `MI_tarmac`, `MI_concrete_kerb`,
`MI_white_paint` and the rest, so the geometry was not un-materialled; it was not *there*.

`04_probe.py --census --census-at 8352,7861 --load-radius-m 700` (added for this) named it in one line: a
1,400 m box over the densest terraced streets in Cliftonville streamed in **124 actors - 113 barriers, 10 rail,
1 authored test stretch from 5.8 km away - and zero roads**, out of 12,815 roads in the level.

The cause is the interaction of two decisions that are each right on their own:

- **meshes are not serialised** (DESIGN.md 10): `PreSave` stashes and empties every renderer's `UDynamicMesh`;
- **World Partition places a spatially-loaded actor from `AActor::GetStreamingBounds`**, which returns
  "a valid origin and an empty extent if this actor doesn't have primitive components"
  (`UE/Runtime/Engine/Classes/GameFramework/Actor.h:2538-2546`).

At save time a road actor's only geometry is an empty mesh, so its streaming bounds were a degenerate box at the
actor transform - the identity, i.e. UE (0, 0, 0) - and every road in Thanet was filed in the one World Partition
cell at the site's south-west corner. Barriers, hedges and rail escaped because they also carry
`UInstancedStaticMeshComponent`s whose instance transforms *are* serialised, so those actors had real bounds.
The isle looked right only when the whole isle was streamed, which is exactly the condition every check so far had
been run under.

The fix is `AStreetscapeActor::StreamingBoundsUE`: a serialised `FBox`, recomputed at the end of every
`RebuildAllChecked` from `CalcBounds` over the actor's primitive components (plus 1 m of XY and 10 m of Z slack),
returned from a `GetStreamingBounds` override. `UpdateStreamingBounds()` is public so a resave pass can refresh
it. After a re-import with the fix, the same 700 m census at Cliftonville streams **1,264 actors of which 1,100 are roads**, 69.5 km of network, 1,227 marking strips (`Saved/Tests/d5_census_cliftonville.json`).

### Still open: the landscape draws through the carriageway at close range

With the whole network in the level, a capture straight down over Margate
(`Saved/Diag/d5_top_margate_street.png`, 130 m, 300 m across) shows the streets as tarmac ribbons with kerbs and
pavements - **and green wedges of landscape punching through them**, metres across. At eye height those wedges
dominate and the carriageway disappears into green
(`Tools/ue/shots/isle_street_margate.png`, kept as the record of it).

What it is not:

- not the data: `Tools/road_fusion_audit.py` reports zero of 666,314 stations with terrain above the built
  surface, and 0.0025 m worst penetration even when the landscape is sampled as triangles;
- not the collision: `04_probe.py --actor-sample 16` traces down at 881 stations, all 881 land on the street, and
  the `ALandscape` height query is between 0.0269 m and 0.196 m below it at every one of them;
- not the material: the same capture's material audit resolves every slot (`MI_tarmac`, `MI_concrete_kerb`,
  `MI_white_paint`, ...), none to the engine default;
- not streaming: 1,264 actors including 1,100 roads are loaded in that frame.

It is the **render** margin. The carriageway sits `corridor_sink_m = 0.03` above the conformed ground
(docs/TERRAIN_ROADS.md 8) and the landscape's drawn mesh is not its own `GetHeightAtLocation` surface. Two things
were tried and neither closed it: pinning `LOD0ScreenSize` on the landscape **after** the World Partition stream
rather than before (a real bug - before the fix the pin was applied to 1 actor and reached none of the 140
streaming proxies; after it, 5 of 5 in frame) changed the frame not at all, and raising the pin from 8 to 100
made it worse (`Saved/Diag/d5_top_margate_lod100.png`). The next thing to try is the sink itself: 3 cm of
clearance is thinner than the landscape's own vertical quantum times its LOD morph, and the corridor pass that
owns it (`Tools/blender/streetscape/conform.py`, road-corridor track) is where a bigger figure belongs.

### The four captures of the finished world (D5, 2026-09-09)

All taken headless with `05_screenshot.py`'s free camera against `/Game/Thanet/Maps/Thanet` as it now stands
(15,423 streetscape actors, 216 massing actors, the conformed 2,067-component landscape). Camera choices come
from `Tools/ue/pick_captures.py`, which picks each site by a measured criterion rather than by eye
(`Saved/Diag/d5_capture_sites.json`).

| file | what it shows | camera (document metres / UE degrees) |
|---|---|---|
| `shots/isle_from_the_south_west.png` | the whole isle: the road network as a web across it, Margate / Broadstairs / Ramsgate as dense coastal clusters, and the **straight south-west edge where the Minnis Bay - Pegwell Bay clip cuts the land** | (-554.62, 1764.75, 3400) yaw -20.25 pitch -19.59 fov 60, 30 km region |
| `shots/isle_seafront_westgate.png` | the Westgate promenade: tarmac, both kerbs, pavement, dashed centre line, the beach and the sea; picked as the road above 3 m ODN with all 7 lateral probes below 0 m ODN | (3148.36, 6819.68, 13.11) yaw -42.31 pitch -0.28 fov 80 |
| `shots/isle_rail_cutting_ramsgate.png` | the Kent Coast line in its cutting through Ramsgate - the deepest on the isle, 10.1 m below ground on both sides at 25 m lateral - with the town's roads and massing around it | (11401.43, 3877.77, 76.71) yaw -81.96 pitch -15.64 fov 60 |
| `shots/isle_street_cliftonville.png` | the Cliftonville terraces: roads, kerbs and pavements threading between 52-footprints-within-40 m of massing, the densest built street on the isle | (8380, 7833, 44) yaw -147.2 pitch -22 fov 70 |
| `shots/isle_street_margate.png` | kept deliberately: eye height on a Margate tertiary road, where the landscape draws through the carriageway (see the section above) | (8301.76, 7730.00, 10.09) yaw -165.41 pitch -3.12 fov 75 |

Every capture is guarded (`distinct_rgb`, mean luminance, and a material audit of the level in the report), and
one attempt was rejected by that guard rather than committed: a camera placed 7 m off the centreline landed
inside a terraced house and came back with 2 distinct colours, which `05_screenshot.py` failed instead of saving.


## Rebuilding the level (and why there is one command for it)

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/00_build_level.ps1 -Recreate
```

`projects/one/Content/` is git-ignored: the level is not an artefact anyone can review, it is something the scripts
produce. Until this script existed it was produced by hand, in an order nobody had written down, with nothing that
would notice if it came out short - and it did. Measured 2026-09-08 before this pass:

- the saved map held **140 `LandscapeStreamingProxy` actors and no `ALandscape` at all**, so
  `02_import_landscape.py --probes-only` could not find a landscape to probe and `04_probe.py --landscape-info`
  would have failed the same way. The landscape had been in it earlier the same day.
- it held **one** `AStreetscapeActor` (the authored test stretch) and none of the isle's 15,422 streets, because
  STAGES 2.12 had never been run.

`00_build_level.ps1` runs bootstrap -> landscape -> test stretch -> massing -> the site streetscape (in
`-StreetscapeSlices` separate commandlets, because every actor a run imports stays resident until it exits) and
finishes with `07_assert_level.py`, which compares what is in the level against the adapter's own manifests and
fails if it is short. `-AllowSeamH16 -1` waives the landscape importer's shared-edge gate for a deliberate import
of the known-bad tile seams described below.

## The tile-seam defect in the terrain data (upstream, unfixed)

Neighbouring 512 m tiles write the row / column they share **twice** - tile (i, j) column 512 is tile (i+1, j)
column 0 - and both writes come from the same source raster, so they must be identical. On Thanet they are not,
and the landscape carries the difference as a false cliff at a tile boundary. Measured three ways, all agreeing:

| measurement | number |
|---|---|
| shared samples across all 391 tiles (numpy over the `hm_*.r16` files) | 378,081 |
| samples where the two writes disagree | 35,951 (max 1402 h16 = **10.95 m**) |
| ... restricted to samples the landscape renders (neither side a visibility hole) | 28,725 of 370,797 (max 683 h16 = **5.34 m**) |
| ... of those, more than 1 m / more than 5 m apart | 14,507 / 113 |
| tiles with at least one disagreeing edge | 77 of 391 |
| the importer's own check on a 2x2 cutout at tiles (23,17)-(24,17) | `864 of 2052`, worst `683 h16 = 5.336 m` at local (512, 512), −2.188 m vs 3.148 m |
| in-engine probe of those six points (`04_probe.py --points seam.csv --landscape`) | `max_abs_dz_m 4e-05` — landscape and heightfield agree with each other, so **both carry the artefact** |

**Root cause, established here and handed to the pipeline track:** every one of the 28,725 disagreeing visible
samples sits on a cell where the source DTM has **no data**. Checked exhaustively against the nodata mask of
`data/thanet/interim/dtm.vrt` (11.273 % of the mosaic, open sea): `at_source_nodata 28725, at_source_data 0`, and
`max_delta_h16_where_source_has_data = 0`. Step 05 fills NoData **per tile**, so a sea cell filled from inside
tile A gets a different nearest neighbour than the same cell filled from inside tile B. The surveyed ground is
bit-identical across every seam; only the fill disagrees. The fix belongs upstream (fill the mosaic, or fill the
shared edge once).

What the Unreal side does about it: `ImportSite` compares every shared edge (order-independently, from the tile
edges it already has in hand) and **refuses the import** when the two writes disagree by more than
`MaxSharedEdgeH16Delta` (default 0). Proven both ways on 2 x 2 cutouts:

```
tiles (23,17)  -> THANET_FAIL 02_import_landscape import_site failed: shared tile edges disagree: 864 of 2052 ...
tiles (15,15)  -> LogStreetscapeEditor: ImportSite: shared tile edges agree exactly over 2052 visible samples
```

`probe_grid` in `02_import_landscape.py` now samples the tile boundary rows and columns as well as the interior
(offsets 0 and `tile_m`, not just 85..425 of a 512 m tile), so the one place the assembly can go wrong is no
longer the one place the gate cannot look.

## Two ground surfaces, two interpolation rules

The plugin's terrain source (`UStreetHeightfieldTerrain`, what every spline, road, kerb, hedge and rail is draped
on) interpolates the 1 m grid **bilinearly**, because that is what the numpy prototype does and what every frozen
parity number was computed with. The `ALandscape` the pawn collides with is a **triangle mesh**: Chaos splits each
cell on its (0,0)-(1,1) diagonal (`Chaos::FHeightField::GetHeightAt` -> `GetHeightNormalAt`,
`Engine/Source/Runtime/Experimental/Chaos/Private/Chaos/HeightField.cpp:921-968`, reached from
`ALandscapeProxy::GetHeightAtLocation`, `LandscapeCollision.cpp:2703` -> `:2548`). On steep ground the two differ
by up to **0.52 m** - four times the 0.125 m kerb Renderer B exists to model.

`EStreetHeightSampling::LandscapeTriangulated` implements the engine's rule exactly and
`Streetscape.Terrain.Triangulated` proves it: on the measured Ramsgate harbour-wall cell (corners SW −2.182,
SE −0.435, NW −1.781, NE 2.240) bilinear gives −0.40959 and the triangulated rule gives −0.92735, the height the
engine itself returned there; on a planar patch the two agree to 0 over 2000 points, and at grid posts they are
identical. `04_probe.py --points --sample-mode triangulated` measures it against the live landscape.

**The default is still Bilinear.** Switching it moves every number in
`Tools/blender/tests/fixtures/expected.json` and `renders/trinity_square.stats.json`, which the geometry track
owns: the numpy `Heightfield.sample` has to adopt the same rule in the same change.

## Opening the project in the GUI later

`"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject`
after a successful `build.ps1`. Its Output Log should show `UnrealMCPBridge: Server started on 127.0.0.1:55558`
while Alex's editor keeps 55557 (`C:/UnrealProjects/test_bridge.py` still answers there). The Python MCP server
registered as `unrealMCP` targets 55557; driving this project interactively needs a second server instance pointed
at 55558 (out of scope for now). `UNREAL_MCP_PORT=<n>` in the environment overrides the configured port.
`EditorStartupMap` is `/Game/Thanet/Maps/Thanet`, so run `01_bootstrap.py` once before the first GUI start.
The GUI start on this machine shows the VC++ redistributable dialog first (advisory - dismiss it).
