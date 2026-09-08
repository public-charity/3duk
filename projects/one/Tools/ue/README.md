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

Later phases add `02_import_landscape.py`, `03_import_streetscape.py`, `04_probe.py`, `05_screenshot.py`,
`06_import_massing.py` (UE_PLAN.md 5.3) and the `StreetscapeSiteActor` to `01_bootstrap.py`.

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
`Streetscape.Sweep.Manifold`, `Streetscape.Geometry.ToDynamicMesh`, `Streetscape.Terrain.Bilinear` - 12 tests,
about 22 s wall clock including the editor start. `TestStretch` builds `schema/examples/test_stretch.json` on the
adapter heightfield `data/thanet/out/unreal/landscape` and skips with an info line when that output is absent.
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
- Phase 2 engine facts the plugin relies on: `FJsonObject::Values` keys are `UE::TSharedString<TCHAR>` in 5.8
  (`Dom/JsonObject.h:237`, case-insensitive; `FString(*Key)` to read); `FJsonSerializer::Deserialize` only accepts a
  top-level object or array (scalar notes are parsed as `[value]`); GeometryCore's front-face normal is
  `cross(v2 - v0, v1 - v0)` (`VectorUtil.h:80-87`, "Unreal has Left-Hand Coordinate System"), so `ToDynamicMesh`
  keeps the JSON winding after the (100, -100, 100) mirror - the two handedness flips cancel (UE_PLAN.md 2.7 said
  "reversed"; measured: reversing gives UE face normals pointing away from the carriageway); UE's `PI` is a float
  literal (`3.1415926535897932f`) - tests use `UE_DOUBLE_PI`.

## Opening the project in the GUI later

`"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject`
after a successful `build.ps1`. Its Output Log should show `UnrealMCPBridge: Server started on 127.0.0.1:55558`
while Alex's editor keeps 55557 (`C:/UnrealProjects/test_bridge.py` still answers there). The Python MCP server
registered as `unrealMCP` targets 55557; driving this project interactively needs a second server instance pointed
at 55558 (out of scope for now). `UNREAL_MCP_PORT=<n>` in the environment overrides the configured port.
`EditorStartupMap` is `/Game/Thanet/Maps/Thanet`, so run `01_bootstrap.py` once before the first GUI start.
The GUI start on this machine shows the VC++ redistributable dialog first (advisory - dismiss it).
