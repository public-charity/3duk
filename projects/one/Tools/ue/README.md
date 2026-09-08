# Tools/ue - building and driving the Unreal project headlessly

Everything here runs against `projects/one/Thanet.uproject` (UE 5.8.2, `C:/Program Files/Epic Games/UE_5.8`)
without opening the editor GUI. Alex's running editor (`MCPGameProject`, MCP port 55557) is never touched:
this project's MCP bridge is configured for port 55558 and does not start inside commandlets at all.

Commands are Git Bash from the repo root (`cd /c/Users/Shadow/code/3duk`).

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
| `03_import_streetscape.py` | `--json <file-or-dir>` → one `AStreetscapeActor` per spline (label = spline id) with the components its `profile_ids` ask for, built from ONE `FStreetSamples`; `--player-start` drops an `APlayerStart` at the first point (yaw = bearing − 90); `--stats-out <file>` writes the first spline's `ActorStatsJson` (the parity file); `--save` saves and then re-reads every buffer to prove the PreSave/PostSaveRoot round trip; `--verify` skips the import and instead re-opens a saved map, `load_region`s the actors in and reports the rebuilt counts | `THANET_OK 03_import_streetscape {"actors": 1, "per_actor": {...}, ...}` |
| `05_screenshot.py` | `--camera cam1\|cam2\|cam3\|all --actor <spline id> --out <dir or .png>`: the eye / target / FOV come from `StreetscapeEditorLibrary.actor_camera_json`, the C++ mirror of `Tools/blender/streetscape/render.py camera_defs`, so Unreal and Blender frame the same thing. Transient `SceneCapture2D` → `TextureRenderTarget2D` → `RenderingLibrary.export_render_target`, then the PNG is rewritten opaque. `--source final_ldr\|scene_hdr\|base_color`, `--ev <bias>` (manual exposure), `--warm-s <s>` (wait between captures for the project material shaders). **Needs `-Render`** | `THANET_OK 05_screenshot {"cameras": {"cam1": {"bytes": ..., "distinct_rgb": ...}}}` |
| `compare_stats.py` | (any python, stdlib only) `--ue <ActorStatsJson> --numpy <Tools/blender/.../stats.json>`: length ±0.05 m, `n_samples`, overlap min/max, per-buffer AND per-material AND per-group verts/tris, marking strips, instance counts, `stations_identical` | one line per row then `PARITY OK` (exit 0) or `PARITY FAIL` (exit 1) |

Later phases add `02_import_landscape.py`, `04_probe.py` and `06_import_massing.py` (UE_PLAN.md 5.3).

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

## Opening the project in the GUI later

`"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject`
after a successful `build.ps1`. Its Output Log should show `UnrealMCPBridge: Server started on 127.0.0.1:55558`
while Alex's editor keeps 55557 (`C:/UnrealProjects/test_bridge.py` still answers there). The Python MCP server
registered as `unrealMCP` targets 55557; driving this project interactively needs a second server instance pointed
at 55558 (out of scope for now). `UNREAL_MCP_PORT=<n>` in the environment overrides the configured port.
`EditorStartupMap` is `/Game/Thanet/Maps/Thanet`, so run `01_bootstrap.py` once before the first GUI start.
The GUI start on this machine shows the VC++ redistributable dialog first (advisory - dismiss it).
