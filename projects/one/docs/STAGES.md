# Project One — stages, tasks, acceptance checks, status

BRIEF.md section 5 expanded into the implementation plan. Every stage lists its tasks (each names the
file(s) it produces), its owner per DESIGN.md 21, the acceptance checks as commands with the output or
number that counts as a pass, and its dependencies. The **Status column of the table in §0 is the only
status record** and belongs to the integration phase; nothing else in this file says "done".
Normative sources: DESIGN.md (why), SCHEMA.md (the interchange), UE_PLAN.md (Unreal, file by file),
PIPELINE_CHANGES.md (`sources/`, section by section). Where a number here disagrees with one of those,
that document wins and this file has a bug.

Written 2026-09-08 at the close of the design phase. Nothing below has been run **against the edited
steps**. BRIEF §8 records what ran before the tracks started: Thanet steps 01–04 with the *unmodified*
steps for all 494 positions, `sources/config/sites/thanet.json` written, the `way["railway"]` line already
in `fetch_osm.sh`, Margate's 182 rasters already copied to Thanet indices, the Margate baseline hash
`data/margate/regress/baseline_2026-09-08.sha256`, EEVEE-only headless Blender, the MAX_PATH limit. The
checks below are written for the disk state §8 describes and say where a clean run prints a different number.

---

## 0. Stage table (status lives here)

| # | Stage | Owner(s) | Depends on | Status |
|---|---|---|---|---|
| 0 | Repo and toolchain scaffolding | pipeline, adapter, geometry, unreal | — | not started |
| 1 | Cropped Thanet terrain | pipeline, adapter, unreal | 0 | not started |
| 2 | OSM reference layer | pipeline, adapter, unreal | 0, 1 | not started |
| 3 | Shared spline | geometry, unreal | 0 (real terrain: 1) | not started |
| 4 | Renderer A — road surface | geometry, unreal | 3 | not started |
| 5 | Renderer B — edge extrusion | geometry, unreal | 3, 4 | not started |
| FD | **First deliverable** — stages 3–5 on the test stretch in Blender and Unreal | geometry, unreal, integration | 1, 3, 4, 5 | not started |
| 6 | Renderer C — volumetric hedge | geometry, unreal | 5 | not started |
| 7 | Rail profile | geometry, unreal, pipeline | 2, 4 | not started |
| 8 | Explorer base | unreal, integration | 1, 2, FD | not started |

Status vocabulary for the integration phase: `not started` → `in progress` → `done (commit <sha>)`, or
`blocked: <reason>`. A stage is `done` only when every acceptance check below was run and its output
recorded in `projects/one/README.md` (BRIEF 4.5: unverified = not done).

BRIEF §8's pre-track facts change no status: raw Thanet data on disk from the *unmodified* steps proves
the sources and the network, not the stages, which are `done` only when their acceptance checks pass
against the edited steps.

---

## Command conventions used below

- Shell: Git Bash, from the repo root `cd /c/Users/Shadow/code/3duk` unless a command says otherwise.
  Forward slashes everywhere; `C:/...` for program and file arguments, `/c/...` inside `PATH`.
- Python is **only** `C:/Users/Shadow/code/3duk-env/env/python.exe`. Pipeline steps and the adapter
  additionally need the GDAL CLI: prefix `PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH`.
  `run.sh` takes `PY=` (PIPELINE_CHANGES.md 6); step 01 must go through `run.sh` so the OSTN15 guard
  applies (BRIEF 2).
- Unreal headless runner (UE_PLAN.md 5.2): `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
  C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script <name.py> [-Args "<args>"]
  [-Render]`. Pass = exit 0, the log line `Python script executed successfully`, and a final stdout line
  `THANET_OK <script> <json>`.
- Unreal Automation tests (UE_PLAN.md 2.13): `"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
  C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests <prefix>; Quit"
  -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log`. Pass = one
  `Test Completed. Result={Passed}` line per test named and no `Result={Failed}`.
- Blender headless (DESIGN.md 14, geometry.md 5.1): `"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"
  -b --python C:/Users/Shadow/code/3duk/projects/one/Tools/blender/streetscape/blender_main.py -- --site <json>
  --terrain <landscape dir> --out <dir> [--gltf] [--render]`. Pass = exit 0 and the files named. Paths handed
  to Blender must be short (BRIEF §8: the 270-character session scratchpad path fails on MAX_PATH) — keep
  inputs and outputs under `projects/one/` or `data/`; the render engine is `BLENDER_EEVEE` (Workbench is
  not selectable headless on this machine).
- numpy tests (no bpy, no GDAL): `C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s
  C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_*.py" -v` → last line `OK`.
- `<DATA>` = `C:/Users/Shadow/code/3duk/data/thanet/out/unreal` (UE_PLAN.md alias).
- Alex's running editor (`MCPGameProject`, port 55557) is never touched; every Unreal command here is a
  commandlet against `projects/one/Thanet.uproject` (BRIEF 4.5).

---

## Stage 0 — Repo and toolchain scaffolding

Everything the four tracks need before they can work in parallel: the site config, the clip API in
`lib.py` with its tests, the ignore rules, the `projects/one` skeleton, an Unreal project that compiles
with empty modules, a Blender package that imports, and the regression snapshot that every later
pipeline check compares against.

**Owner:** pipeline (0.1–0.6), adapter (0.7), geometry (0.8–0.10), unreal (0.11–0.15).

### Tasks

1. Write `sources/tests/regress_outputs.sh` (PIPELINE_CHANGES.md 9.1) and take `data/margate/regress/before.sha256` **before any edit to `sources/`**; BRIEF §8's `data/margate/regress/baseline_2026-09-08.sha256` (paths relative to `out/`) was taken earlier for the same purpose, so the two must be proved identical after normalising and `compare` must accept either as its reference. — pipeline
2. `sources/config/sites/thanet.json` already exists (BRIEF §8) with the PIPELINE_CHANGES.md 1 text; verify it against that section field by field (grid 26×19 at E 627680 N 163080, OSTN15 clip line, inherited calibration blocks with their notes, `wcs` equal to `margate.json`'s) and fix any drift in the same commit as the `lib.py` clip API. — pipeline
3. Add the clip API to `sources/lib.py` (`HalfPlaneClip`, `parse_clip`, `keep_points`, `tile_state`, `cell_mask`, `clip_wkt`, `clip_manifest`, `grid_stamp`, `signed_distance_out`) and the shared line geometry (`tagval`, `densify`, `chaikin`, `DtmSampler`, `tile_of`, `drape_runs`) plus the `lib.tiff_info` extension, verbatim from PIPELINE_CHANGES.md 2. — pipeline
4. Add `sources/config/tuning.json` blocks `rail` and `barriers` (PIPELINE_CHANGES.md 4.5). — pipeline
5. Extend `sources/tests/dryrun.py` with the `C-lib` checks of PIPELINE_CHANGES.md 8.3 and the site-C synthetic fixtures of 8.2 (steps 05–11 and the adapter hooks are added by stages 1–2; at stage 0 the harness must still pass with the two existing sites). — pipeline
6. Finish the root `.gitignore` (already modified in the working tree: `projects/*/{Binaries,Intermediate,Saved,DerivedDataCache,Build,.vs}`, `projects/*/Plugins/*/{Binaries,Intermediate}`, `projects/*/Tools/blender/out/`, `*.blend1`) and confirm `.gitattributes` routes `*.png` through LFS. — pipeline
7. Write `sources/adapters/unreal.json` (PIPELINE_CHANGES.md 13.11) and the module skeleton of `sources/adapters/unreal.py` with the pure functions and their unit tests in `sources/tests/test_unreal_adapter.py` (`encode_h16`/`decode_h16`, `check_range`, `survey_to_local`, `local_to_ue_cm`, `bearing_to_heading_deg`, `bearing_to_ue_yaw`, `visibility_weight`, `load_profiles`, `git_sha`). — adapter
8. Create the Blender package `projects/one/Tools/blender/streetscape/` with `__init__.py` (`__version__`, re-exports), `schema.py`, `io_json.py` (load/save/`validate_structure`) and an empty-but-importing stub for every other module of geometry.md 5.1 (`terrain, spline, sweep, mesh, noise, road, rail, edge, hedge, build, bpy_bridge, render, blender_main`). — geometry
9. Write `projects/one/Tools/blender/tests/schema_check.py` (JSON-Schema draft 2020-12 structural validator over `schema/streetscape.schema.json`, stdlib only — the adapter's tests import it) and `tests/test_io_json.py` (every `schema/profiles/*.json` loads, both `schema/examples/*.json` load and round-trip, unknown key rejected). — geometry
10. Write `projects/one/Tools/blender/tests/make_fixtures.py` and commit `tests/fixtures/expected.json` holding every number of SCHEMA.md 9.3 and DESIGN.md 3.7–3.8 (the fixture documents `straight_100`, `sine_5_50`, `curve_R20_200`, `rail_R300_600` are regenerated by the script into `tests/fixtures/*.json`). — geometry
11. Create `projects/one/Thanet.uproject`, `Source/Thanet.Target.cs`, `Source/ThanetEditor.Target.cs`, `Source/Thanet/{Thanet.Build.cs, Thanet.h, Thanet.cpp}` and `Config/{DefaultEngine.ini, DefaultGame.ini, DefaultInput.ini, DefaultEditor.ini}` as UE_PLAN.md 1. — unreal
12. Create `Plugins/Streetscape/Streetscape.uplugin`, both `*.Build.cs`, `Public/StreetscapeModule.h`, `Public/StreetscapeSettings.h` (`DataDir`, `SiteName`, `OverlayLiftM`), `Public/StreetscapeEditorModule.h` and their `.cpp` files (UE_PLAN.md 2.1–2.3), with the remaining headers of the file tree present as compiling stubs. — unreal
13. Copy the UnrealMCP plugin source-only into `Plugins/UnrealMCP/` and apply the `UUnrealMCPSettings` / commandlet-guard / `SetReuseAddr` edits of UE_PLAN.md 6. — unreal
14. Write `Tools/build.ps1`, `Tools/build.sh`, `Tools/ue/run_ue_python.ps1` and `Tools/ue/ue_common.py` (UE_PLAN.md 5.1–5.3 row 0). — unreal
15. Write `projects/one/README.md` with the layout of BRIEF 4.3, the build/run commands of this file, and a "state" section that points at the §0 table. — integration (initial text by unreal; integration owns it afterwards)

### Acceptance checks

```bash
# 0.1 snapshot exists and its first line is normalised (PIPELINE_CHANGES.md 9.1 self-check)
cd /c/Users/Shadow/code/3duk && ./sources/tests/regress_outputs.sh snapshot margate before
head -1 data/margate/regress/before.sha256 | grep -Eq '^[0-9a-f]{64}  [^*]' && echo NORMALISED
./sources/tests/regress_outputs.sh compare margate baseline_2026-09-08
```
Expected: `N files hashed -> .../data/margate/regress/before.sha256` with N = the number of files under `data/margate/out` today (terrain 92 + networks 83 + massing 71 + coast 92 + furniture 14 + 2 `qa_*.json` + `unity/**` = 1583), then `NORMALISED`, then `795 identical, 788 added (allowed), 0 problems` — every one of BRIEF §8's 795 baseline files still byte-identical, with only the `unity/**` products added since. Use the script's own `compare`, not a hand-written `diff`: it normalises both sides the same way (the baseline's paths carry a `./` prefix, so a `sed` that only strips `*` mismatches all 795 lines) and it applies the `ALLOW_NEW` list, so `unity/**` counts as an allowed addition rather than a difference.

```bash
# 0.2 / 0.3 the config parses through lib and the clip is the OSTN15 pair
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import sys; sys.path.insert(0,'sources'); import lib, json; cfg=json.load(open('sources/config/sites/thanet.json')); c=lib.parse_clip(cfg); print(cfg['nx']*cfg['ny'], cfg['clip']['line'], c.stamp() if hasattr(c,'stamp') else 'ok')"
```
Expected: `494 [[628512, 169680], [635496, 163609]] ...` — the Helmert pair `628514/169681` must not appear anywhere: `grep -rn "628514\|169681\|635498\|163610" sources/ projects/one/docs/*.md projects/one/schema` prints only the lines that forbid it.

```bash
# 0.3 / 0.5 dry run: the lib checks pass and nothing regresses
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/dryrun.py
```
Expected: last line `<n> passed, 0 failed` with n ≥ 86 + the `C-lib` checks; these names appear with `PASS`: `C-lib parse_clip: absent -> None; unknown type refuses`, `C-lib tile_state on the diagonal`, `C-lib keep_points: vectorised; on-line kept; keep=right mirrors`, `C-lib cell_mask at pixel centres: tile (1,0) clips 167466 of 263169; None -> all True`, `C-lib clip_wkt: 5-corner / rectangle / None`, `C-lib grid_stamp: four keys with or without a clip`, `C-lib drape_runs == 06 arithmetic`, `C-lib thanet.json clip.line == BRIEF 4.1 [[628512, 169680], [635496, 163609]]`, `C-lib tile_state / cell_mask on the Thanet grid: 360 inside, 31 straddle, 103 outside, 3861822 clipped cells`, `C-lib signed_distance_out: 0 on the line, + into the cut`.

```bash
# 0.6 ignore rules and LFS routing
git check-ignore -v projects/one/Binaries/x projects/one/Intermediate/x projects/one/Saved/x projects/one/Plugins/Streetscape/Binaries/x projects/one/Plugins/UnrealMCP/Intermediate/x projects/one/Tools/blender/out/x
git check-ignore -q projects/one/Tools/blender/renders/a.png; echo "renders ignored? exit=$?"
git check-attr filter projects/one/Tools/blender/renders/a.png
```
Expected: six matching lines from the first command; `renders ignored? exit=1`; `... filter: lfs`.

```bash
# 0.7 adapter pure functions
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/test_unreal_adapter.py
```
Expected: `OK`; the run includes `encode_h16(0) == 32768`, `encode_h16(-0.6) == 32691`, `encode_h16(255) == 65408`, `encode_h16(-1.0) == 32640`, the DESIGN.md 2 worked example `(635253.6, 171027.6, 17.2) -> (7573.6, 7947.6, 17.2) -> (757360, -794760, 1720)`, `bearing 131 -> heading -41 / yaw 41`, `bearing 270 -> heading -180`, `visibility_weight(0) == 170`, `(1) == 255`, `(-2) == 0`, and `load_profiles(projects/one/schema/profiles)` returning 20 ids.

```bash
# 0.8 / 0.9 / 0.10 the Blender package imports under both pythons, the validator accepts the examples, fixtures regenerate
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import sys; sys.path.insert(0,'projects/one/Tools/blender'); import streetscape; print(streetscape.__version__)"
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --python-expr "import sys; sys.path.insert(0, 'C:/Users/Shadow/code/3duk/projects/one/Tools/blender'); import streetscape, numpy; print('BLENDER_IMPORT_OK', streetscape.__version__, numpy.__version__)"
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/blender/tests/schema_check.py projects/one/schema/examples/test_stretch.json projects/one/schema/examples/synthetic_straight.json projects/one/schema/profiles/*.json
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/blender/tests/make_fixtures.py && ls projects/one/Tools/blender/tests/fixtures
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_io_json.py" -v
```
Expected: a version string; `BLENDER_IMPORT_OK <version> 2.3.x`; the validator prints `VALID` for 22 files (2 examples + 20 profiles) and exits 0; `fixtures/` lists `straight_100.json sine_5_50.json curve_R20_200.json rail_R300_600.json expected.json`; `OK`.

```bash
# 0.11–0.14 the Unreal project compiles with empty modules
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/build.ps1; echo "exit=$?"
ls projects/one/Binaries/Win64/UnrealEditor-Thanet.dll projects/one/Plugins/Streetscape/Binaries/Win64/UnrealEditor-Streetscape.dll projects/one/Plugins/Streetscape/Binaries/Win64/UnrealEditor-StreetscapeEditor.dll projects/one/Plugins/UnrealMCP/Binaries/Win64/UnrealEditor-UnrealMCP.dll
grep -c "C4459" projects/one/Saved/Logs/build.log
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script ue_common.py
```
Expected: `Result: Succeeded`, `exit=0`, the four DLLs listed, `0` C4459 hits, and `THANET_OK ue_common {"project_dir": "...", "data_dir": "..."}` proving the headless runner and `Intermediate/PythonStub/unreal.py` generation work (`bDeveloperMode=True`, UE_PLAN.md 1.4). The commandlet log must **not** contain `UnrealMCPBridge: Server started` (D10: no server in commandlets).

```bash
# 0.15 skeleton complete
ls projects/one projects/one/Source projects/one/Config projects/one/Plugins projects/one/Tools projects/one/Tools/blender projects/one/Tools/ue
git status --short projects/ | grep -v '^??' ; git status --short --ignored projects/one | grep '^!!'
```
Expected: the tree of BRIEF 4.3; the ignored list contains only `Binaries/`, `Intermediate/`, `Saved/`, `DerivedDataCache/`, `.vs/`, `Plugins/*/Binaries|Intermediate` and `Tools/blender/out/`.

**Depends on:** nothing. **Blocks:** every other stage.

---

## Stage 1 — Cropped Thanet terrain

BRIEF 5 row 1: `SITE=thanet run.sh` steps 01–05 complete; `terrain_manifest.json` shows 391 tiles, `clip`
recorded, `slope_qa.max_deg ≥ 80`; Margate tiles reused; the Unreal adapter writes landscape tiles + manifest;
the landscape is imported headless into `Thanet.uproject` at 1 m with the clip hole; a height probe proves the
cliffs are 65–80° in-engine.

**Owner:** pipeline (1.1–1.7), adapter (1.8–1.9), unreal (1.10–1.14).

### Tasks

1. `way["railway"]($BBOX);` is already in `sources/fetch/fetch_osm.sh` and Thanet's extract was fetched with it (BRIEF §8: 217 `rail` ways); add the query recording (`$OUT.query`, and in `sources/fetch/01_fetch_osm.sh` provenance `query_sha256`, `query_selectors`, `query_note`, `counts.railway`, `counts.barriers`, PIPELINE_CHANGES.md 5) and regenerate `sources/provenance/thanet.osm.json` by re-running 01, which skips the fetch on the matching bbox — so the `.query` file must be written from the script's own selectors even when the fetch is skipped, or the provenance honestly says `query_sha256: null` with the `query_note`. — pipeline
2. Replace the `PY` line of `sources/run.sh` with the usable-python probe, export `PY`, add step 11 to `STEPS`, and update the header and closing hint (PIPELINE_CHANGES.md 6). — pipeline
3. Write `sources/fetch/reuse_tiles.py` (checks 1–7 of PIPELINE_CHANGES.md 7) so Margate's 182 rasters land at `data/thanet/raw/lidar/{dtm,dsm}_x{i+10}_y{j+10}.tif` with a correct `_grid.json`; on this machine a one-off script already copied them (BRIEF §8), so the first run must report them `present` after re-checking each file's georeferencing — which for these EA tiles is the `ModelTransformationTag` (34264), not a tiepoint, so `lib.tiff_info`'s `georef_origin` reads 34264 first (PIPELINE_CHANGES.md 2.4). — pipeline
4. Edit `sources/fetch/02_fetch_lidar.py` to skip `outside` tile positions and write `data/thanet/raw/lidar/_fetch_clip.json` (PIPELINE_CHANGES.md 3.1). — pipeline
5. Edit `sources/derive/05_export_terrain.py` to write NoData −9999 outside the clip after the fill, declare NoData on every tile of a clipped site, and record `nodata, clip, tiles_clipped, clipped_cells_total, clip_note` and per-tile `clip_state, clipped_cells` in `data/thanet/out/terrain/terrain_manifest.json` (PIPELINE_CHANGES.md 3.3). — pipeline
6. Extend `sources/tests/dryrun.py` with the site-C checks for 02-equivalent skipping and step 05 (PIPELINE_CHANGES.md 8.3 "05" group) and add the `terrain/` and Clip rows to `sources/OUTPUT.md` (10.1). — pipeline
7. Run the real chain for Thanet: `reuse_tiles.py`, then `run.sh --only 01`, `--only 02`, `--only 03`, `--only 04`, `--only 05`, producing `data/thanet/derived/thanet.gpkg`, `data/thanet/raw/lidar/*.tif` (782 files from a clean run; 988 on this machine, BRIEF §8), `data/thanet/interim/{dtm,dsm}.vrt`, `data/thanet/out/terrain/*.tif` (391) and `terrain_manifest.json`. — pipeline
8. Implement the `landscape()` product of `sources/adapters/unreal.py` (`hm_*.r16`, `clip_*.r8`, `vis_*.r8`, `weight_*_*.r8`, `landscape/landscape_manifest.json`, `unreal_manifest.json`) and its refusals (PIPELINE_CHANGES.md 13.3, 13.10) with the synthetic-site checks in `sources/tests/test_unreal_adapter.py`. — adapter
9. Run the adapter for Thanet (weights will be absent until stage 2's step 09 has run: the adapter must write `weights: null` per tile and say so in `landscape_manifest.json`, then be re-run after stage 2) producing `data/thanet/out/unreal/landscape/**`. — adapter
10. Implement `Plugins/Streetscape/Source/Streetscape/Public/StreetTerrainSource.h` + `.cpp` (`IStreetTerrainSource`, `UStreetHeightfieldTerrain` reading `landscape_manifest.json` + `hm_*.r16` + `clip_*.r8` with the bilinear rule of DESIGN.md 8, `UStreetLandscapeTerrain`) and the Automation test `Private/Tests/StreetTerrainTests.cpp` (`Streetscape.Terrain.Bilinear`). — unreal
11. Implement `Plugins/Streetscape/Source/StreetscapeEditor/Public/StreetscapeLandscapeImporter.h` + `.cpp` (`ImportSite`, `ProbeHeightM`, `CountLandscapeComponents`, `CountStreamingProxies`; the manifest hard-fails, padding north/east, fill 32691, visibility from `vis_*.r8`, weightmaps by one mosaic resample, WP grid 4, the D1 gate and the region fallback of UE_PLAN.md 3.6–3.7) and the `M_Thanet_Landscape` creation in `Tools/ue/01_bootstrap.py`. — unreal
12. Write `Tools/ue/01_bootstrap.py` (folders, landscape material, `M_Street_Base` + 20 material instances, `DT_StreetMaterials`, `ImportProfiles` → 20 DataAssets, the empty World Partition map `/Game/Thanet/Maps/Thanet`, lights/sky/fog, `AStreetscapeSiteActor`) and `Tools/ue/02_import_landscape.py` (`--manifest --wp-grid --qps --sections --max-components`, plus `--probes-only` to re-run the probes on an already imported landscape; prints the report JSON and runs the cliff and clip probes). — unreal
13. Write `Tools/ue/make_cutout_manifest.py` (stdlib: copies a `landscape_manifest.json` restricted to a 2×2-tile window re-indexed to `nx 2, ny 2`, for the D1 gate step (a)) and `Tools/ue/04_probe.py` (`--points <csv> [--landscape]` → CSV of `x, y, z_heightfield, z_landscape, clipped`; `--actor <id> --trace-from-above` → one `line_trace_single` per station over the named streetscape actor's road, reporting blocked/unblocked). — unreal
14. Write `Tools/ue/05_screenshot.py` (`--x --y --z --yaw --pitch --out`, or `--camera cam1|cam2|cam3 --actor <id>` reproducing the three Blender camera definitions of geometry.md 5.12 in spline terms; `LoadRegion` + `SceneCapture2D` → PNG; `-game -ExecCmds="HighResShot"` fallback documented in the script header). — unreal

### Acceptance checks

```bash
# 1.3 tile reuse: dry run then copy
cd /c/Users/Shadow/code/3duk
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH C:/Users/Shadow/code/3duk-env/env/python.exe sources/fetch/reuse_tiles.py --from margate --to thanet --dry-run
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH C:/Users/Shadow/code/3duk-env/env/python.exe sources/fetch/reuse_tiles.py --from margate --to thanet
ls data/thanet/raw/lidar/*.tif | wc -l; cat data/thanet/raw/lidar/_grid.json
```
Expected on the current disk (BRIEF §8: the 182 copies and the full 494-position fetch already happened): dry run `planned 182, present 182, outside_target_grid 0, outside_clip 0`; real run `copied: 0, present: 182` with every file's georeferencing re-checked (a differing file is FATAL); `988` rasters on disk (494 positions × 2 — the 103 outside-clip positions are there too and are harmless); `_grid.json` has exactly the four keys of `lib.grid_stamp` for the Thanet config; `data/margate/` unchanged (`./sources/tests/regress_outputs.sh compare margate before` → `0 problems`). From a clean `data/thanet/raw/lidar/` the numbers are `copied: 182` (~728 MB) and `182` files.

```bash
# 1.1 / 1.7 steps 01–05 for Thanet (01 through run.sh so PROJ_NETWORK=ON applies)
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=thanet ./sources/run.sh --only 01
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE railway IS NOT NULL" data/thanet/derived/thanet.gpkg
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE barrier IS NOT NULL" data/thanet/derived/thanet.gpkg
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; p=json.load(open('sources/provenance/thanet.osm.json')); print(p['query_src'], p['query_sha256'] is not None, [s for s in p['query_selectors'] if 'railway' in s], p['counts']['railway'], p['counts']['barriers'])"
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=thanet ./sources/run.sh --only 02
ls data/thanet/raw/lidar/dtm_*.tif | wc -l
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=thanet ./sources/run.sh --only 03
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=thanet ./sources/run.sh --only 04
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=thanet ./sources/run.sh --only 05
ls data/thanet/out/terrain/dtm_*.tif | wc -l
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; m=json.load(open('data/thanet/out/terrain/terrain_manifest.json')); print(len(m['tiles']), len(m['tiles_clipped']), m['clipped_cells_total'], m['nodata'], m['slope_qa']['max_deg'], m['clip']['line'], m['clip']['keep'], sum(1 for t in m['tiles'] if t['clip_state']=='straddle'))"
```
Expected, in order (current disk state per BRIEF §8 — steps 01–04 already ran unmodified, so 01 skips the fetch and 02/03/04 are cache hits): step 01 passes the OSTN15 guard (`crs_max_transform_accuracy_m 1.0`; the log names the 1 m-class grid operation, not the Helmert one) on the existing 30 MB extract; railway count **`262`** (rail 217, abandoned 20, razed 16, platform 7, miniature 2); barrier count **≈ 2,260** (fence 1,155, wall 788, hedge 179, retaining_wall 43, gate 40, bollard 30, kerb 24, …); `reconstructed True ['way["railway"]'] 262 2272` — read `query_src` first, not the bare `query_sha256 is not None`: after a skipped fetch the selectors are rebuilt from `fetch_osm.sh` **as it is now**, so the hash is real but the query may never have been sent, and only `counts.railway` / `counts.barriers` prove the extract actually contains what the selector asks for (they do: 262 and 2272). `fetch`/`recorded` would mean the query is the extract's own; `absent` means none was recorded, with `query_note` saying so; step 02 summary **`cached: 782, ok: 0, skipped_clip: 206`** (all 391 kept positions are on disk; from a clean `raw/lidar` after `reuse_tiles.py` it is `cached: 182, skipped_clip: 206, ok: 600`, ≈ 4.6 min at 2.2 rasters/s); `494` raw DTM tiles on disk (the 103 outside positions were fetched by the unmodified 02 and stay — 05 and 09 skip them from the config; a clean run has `391`); 03/04 complete (04: DTM nodata 11.27 % of the mosaic = open sea; 23,400 of 23,459 footprints with ground and height); **`391` exported tiles**; **`391 103 3861822 -9999.0 <≥ 80> [[628512, 169680], [635496, 163609]] left 31`**. Offshore source gaps (the 11.27 %) are filled nearest and counted in `nodata_cells` — a coverage gap, distinct from `clipped_cells`; `tiles_missing` is empty (no position came back EMPTY).

```bash
# 1.5 / 1.6 dry run and Margate byte identity after the 02/05 edits
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/dryrun.py
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=margate ./sources/run.sh --only 05
./sources/tests/regress_outputs.sh compare margate before
```
Expected: `0 failed` with `PASS` on the 05 group (`straddle (1,0) NoData count 167466 == clipped_cells`, `outside tile no file + tiles_clipped`, `NoData declared on every tile`, `A clipless: no clip keys, no NoData tag`); the Margate compare prints `N identical, 0 added (allowed), 0 problems`.

```bash
# 1.8 / 1.9 adapter landscape products
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/test_unreal_adapter.py
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH SITE=thanet C:/Users/Shadow/code/3duk-env/env/python.exe sources/adapters/unreal.py
ls data/thanet/out/unreal/landscape/hm_*.r16 | wc -l; ls data/thanet/out/unreal/landscape/clip_*.r8 | wc -l; ls data/thanet/out/unreal/landscape/vis_*.r8 | wc -l
stat -c %s data/thanet/out/unreal/landscape/hm_x15_y15.r16 data/thanet/out/unreal/landscape/clip_x15_y15.r8
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; m=json.load(open('data/thanet/out/unreal/landscape/landscape_manifest.json')); print(m['res'], m['nx'], m['ny'], m['heightmap']['row0'], m['heightmap']['row_flip_for_ue'], m['heightmap']['z_encoding']['per_unit'], m['pad_value_h16'], m['clip']['line'], len(m['tiles_clipped']), m['clipped_cells_total'], m['slope_qa']['max_deg'], m['ue_import_unpadded']['verts'])"
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import numpy as np, json; m=json.load(open('data/thanet/out/unreal/landscape/landscape_manifest.json')); import glob; z=sum(int((np.fromfile(f, dtype=np.uint8)==0).sum()) for f in glob.glob('data/thanet/out/unreal/landscape/clip_*.r8')); print(z == m['clipped_cells_total'], z)"
```
Expected: `OK`; the adapter prints its product counts and exits 0 (weights `null` with a warning if step 09 has not run yet); `391 391 31`; `526338 263169`; `513 26 19 north False 128 32691 [[628512, 169680], [635496, 163609]] 103 3861822 <≥ 80> [13313, 9729]`; `True 3861822`.

```bash
# 1.10 heightfield sampler parity
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Terrain; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
```
Expected: `Test Completed. Result={Passed}` for `Streetscape.Terrain.Bilinear` (equals the numpy `Heightfield.sample` on 10 000 hashed points incl. tile borders and clip NaN).

```bash
# 1.12 bootstrap, then the gated landscape import (D1): (a) 2x2 cutout, (b) 256 components, (c) full
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 01_bootstrap.py
ls projects/one/Content/Thanet/Profiles/*.uasset | wc -l
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/make_cutout_manifest.py --manifest C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape/landscape_manifest.json --tiles 15,15 --size 2 --out C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape_cutout/landscape_manifest.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 02_import_landscape.py -Args "--manifest C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape_cutout/landscape_manifest.json" -Render
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 02_import_landscape.py -Args "--manifest C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape/landscape_manifest.json --max-components 256" -Render
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 02_import_landscape.py -Args "--manifest C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape/landscape_manifest.json" -Render
ls projects/one/Content/__ExternalActors__/Thanet/Maps/Thanet/ | wc -l
```
Expected: `THANET_OK 01_bootstrap {"materials": 21, "profiles": 20, "map": "/Game/Thanet/Maps/Thanet"}` and `20` profile assets; (a) report `components: 16`; (b) `components: 256` with `regions_used > 1` (the region path exercised); (c) **`components: 2067`, `proxies: 140`, `extent: [0, 0, 13462, 9906]`, `padding: {"east": 150, "north": 178}`, `fill_h16: 32691`, `helper_suggestion: {"qps": 255, "sections": 2, "components": [27, 20]}`**, `rss_mb` and `seconds` per step (peak ≤ 20 GB, ≤ 30 min, else the region fallback ran and `regions_used` says so); `≥ 140` external-actor packages. Each import run is against a fresh copy of the map (the importer refuses a map that already holds a landscape).

```bash
# 1.13 cliffs in-engine (UE_PLAN.md 8.5) and the clip edge (8.6)
mkdir -p C:/Users/Shadow/code/3duk/projects/one/Saved/probe   # ignored dir; short path (BRIEF §8: MAX_PATH)
printf 'x,y\n' > "C:/Users/Shadow/code/3duk/projects/one/Saved/probe/cliff.csv"; for x in 8800 8810 8820 8830 8840; do for y in $(seq 8570 8670); do printf '%s,%s\n' $x $y >> "C:/Users/Shadow/code/3duk/projects/one/Saved/probe/cliff.csv"; done; done
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 04_probe.py -Args "--points C:/Users/Shadow/code/3duk/projects/one/Saved/probe/cliff.csv --landscape" -Render > "C:/Users/Shadow/code/3duk/projects/one/Saved/probe/cliff_out.csv"
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import csv, math, json; r=[dict(l) for l in csv.DictReader(open(r'C:/Users/Shadow/code/3duk/projects/one/Saved/probe/cliff_out.csv')) if l.get('x')]; d=max(abs(float(a['z_heightfield'])-float(a['z_landscape'])) for a in r); s=max(math.degrees(math.atan(abs(float(b['z_heightfield'])-float(a['z_heightfield'])))) for a,b in zip(r,r[1:]) if a['x']==b['x']); m=json.load(open('data/thanet/out/unreal/landscape/landscape_manifest.json')); t=[t for t in m['tiles'] if t['x']==17 and t['y']==16][0]; print('max|dz|', d, 'slope_deg', s, 'tile slope_max_deg', t['slope_max_deg'])"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 02_import_landscape.py -Args "--manifest C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape/landscape_manifest.json --probes-only" -Render
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 05_screenshot.py -Args "--x 4324 --y 3564.5 --z 60 --yaw 0 --pitch -89 --out C:/Users/Shadow/code/3duk/projects/one/Tools/ue/shots/clip_edge.png" -Render
```
Expected: `max|dz| ≤ 0.01` (landscape and heightfield agree at vertices), `slope_deg ≥ 65` and within 2° of the tile's `slope_max_deg` (Cliftonville, tile (17, 16)); the probe report lists 20 points along `clip.line` (read from the manifest, never hard-coded) with `P+` returning a height and blocking a `line_trace_single`, `P−` returning none and passing through — the midpoint pair is local `(4325.31, 3566.01)` kept / `(4322.69, 3562.99)` cut; `clip_edge.png` written, showing a straight edge.

**Depends on:** 0. **Blocks:** 2, FD, 8.

---

## Stage 2 — OSM reference layer

BRIEF 5 row 2: steps 06, 07, 09, 10, **11** complete with clip counts; the adapter writes Streetscape JSON
splines for roads, rail and barriers plus overlay polylines; Unreal shows the overlay as debug lines over
the landscape.

**Owner:** pipeline (2.1–2.6), adapter (2.7–2.9), unreal (2.10–2.12).

### Tasks

1. Add clip support only to `sources/derive/06_build_networks.py` (drop and count `vertices_outside_clip` / `junctions_outside_clip`; an off-clip vertex closes a run like an off-grid one; manifest `clip`) per PIPELINE_CHANGES.md 3.4. — pipeline
2. Add the envelope-centre clip to `sources/derive/07_massing.py` (`outside_clip`), the straddle-tile zeroing and `tiles_clipped / clipped_cells / bands_note` to `sources/derive/09_coast.py`, and the node clip to `sources/derive/10_furniture.py` (PIPELINE_CHANGES.md 3.5–3.7). — pipeline
3. Write `sources/derive/11_linear_features.py` emitting `networks/rail_x{i}_y{j}.jsonl`, `networks/barriers_x{i}_y{j}.jsonl` and `networks/linear_manifest.json` through `lib.drape_runs` (record schemas and manifest of PIPELINE_CHANGES.md 4). — pipeline
4. Extend `sources/tests/dryrun.py` with the 06/07/09/10/11 site-C checks (PIPELINE_CHANGES.md 8.3), the `derive/11_linear_features.py` and `adapters/unreal.py` steps, and the adapter hook of 13.10; add the step-11 section, the `coast/` 252–255 contract and the "Writing an adapter" sentences to `sources/OUTPUT.md`, and the README deltas of 10.2. — pipeline
5. Run `run.sh --only 06 / 07 / 09 / 10 / 11` for Thanet producing `data/thanet/out/{networks,massing,coast,furniture}/**` and their manifests; then re-run 05–11 + `unity.py` for Margate and prove byte identity (PIPELINE_CHANGES.md 9.2). — pipeline
6. Inspect the first real step-11 output (Birchington–Margate–Broadstairs–Ramsgate continuous, `gauge_defaulted` small, barrier class histogram) and record it in `README.md`'s Thanet paragraph. — pipeline (record: integration)
7. Implement `streetscape()` in `sources/adapters/unreal.py` (`order_runs`, `thin_against_interpolant` at 0.10 m, `profile_ids_for`, `classify_barrier`, junction ends, `clip_polyline` overlays, per-tile `streetscape/site_x{i}_y{j}.json` documents with inlined profiles, `streetscape_manifest.json`) per PIPELINE_CHANGES.md 13.4–13.9 with the tests of 13.10. — adapter
8. Implement `massing()` and `furniture()` products (`massing/buildings_x*_y*.jsonl`, `furniture/furniture_x*_y*.jsonl` and manifests) and complete `write_root_manifest` (PIPELINE_CHANGES.md 13.10). — adapter
9. Re-run the adapter for Thanet (now with weights) and for Margate (`data/margate/out/unreal/**`, allowed by `ALLOW_NEW`), producing the complete `data/<site>/out/unreal/` trees. — adapter
10. Implement `Plugins/Streetscape/Source/Streetscape/Public/StreetTypes.h`, `StreetProfiles.h`, `StreetMaterialTable.h`, `StreetscapeJson.h` (+ `.cpp`: strict `FStreetscapeJson` loader/saver, `LoadSite(dir)`, `ToUE`, D13) and the tests `Streetscape.Json.SchemaFixtures`, `Streetscape.Json.RoundTrip` in `Private/Tests/StreetJsonTests.cpp`. — unreal
11. Implement `StreetOverlayComponent.h` + `.cpp` (persistent line batcher, `OverlayBatchId = FCrc::StrCrc32(*StreetId) || 1`, re-drape on the terrain source and lift `OverlayLiftM` 0.3, toggle) and the minimal `StreetscapeActor.h`/`StreetscapeSiteActor.h` needed to hold `Spline` (data only at this stage) + `Overlay`. — unreal
12. Write `Tools/ue/03_import_streetscape.py` (`--json <file-or-dir> [--player-start] [--stats-out <json>]` → `ImportStreetscapeJson`, with `--stats-out` writing `ActorStatsJson` per imported actor) and the `ImportStreetscapeJson` / `LoadRegion` / `SaveAll` / `ExportSiteJson` functions of `StreetscapeEditorLibrary.h` (UE_PLAN.md 2.12; renderers still absent, so an actor carries only its spline data and overlay). — unreal

### Acceptance checks

```bash
# 2.1–2.4 dry run with site C, steps 06–11 and the adapter
cd /c/Users/Shadow/code/3duk
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/dryrun.py
```
Expected: `<n> passed, 0 failed`, n ≥ 86 + ≈ 40; `PASS` on: `06: rd1 cut at its last kept vertex`, `outside way dropped`, `off-clip vertices are not DTM gaps`, `outside junction dropped`; `07: outside_clip 1`; `09: (sum >= 252) | (sum == 0) everywhere; sum == 0 count == clipped_cells`, `straddle (1,0) zero-sum cells 41665`; `10: outside node dropped, cn1 placed on rd1`; `11: rl1 per-tile pts/z_gap identical to rd1's` (the C11 drift guard), `rail fields (1.435 osm, tracks 2, ...)`, `wall h 0.5 osm / fence h 1.5 default`, `"15 cm" -> 0.15`, `hedge cut; gate counted`, `A11/B11 zero counts`; `adapter: unreal_manifest round-trips origin/tile_m/nx/ny/res`, `site C clipped_cells == clip-mask zeros`, `vis present for straddle tiles`.

```bash
# 2.5 the real Thanet run, 06–11
for s in 06 07 09 10 11; do PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=thanet ./sources/run.sh --only $s || break; done
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; n=json.load(open('data/thanet/out/networks/networks_manifest.json')); l=json.load(open('data/thanet/out/networks/linear_manifest.json')); m=json.load(open('data/thanet/out/massing/massing_manifest.json')); c=json.load(open('data/thanet/out/coast/coast_manifest.json')); f=json.load(open('data/thanet/out/qa_furniture.json')); print('06', n['clip']['keep'], n['vertices_outside_clip'], n['junctions_outside_clip'], n.get('segments'), n.get('junctions')); print('11 rail', l['layers']['rail']['segments'], l['layers']['rail']['tiles'], l['layers']['rail']['length_km'], l['layers']['rail']['by_class'], 'gauge_defaulted', l['layers']['rail']['gauge_defaulted'], 'outside_clip', l['layers']['rail']['vertices_outside_clip']); print('11 barriers', l['layers']['barriers']['segments'], l['layers']['barriers']['by_class'], l['ways_skipped_by_class']); print('07', m['outside_clip'], m.get('height_calib'), m.get('height_calib_fit')); print('09', len(c['tiles_clipped']), c['clipped_cells'], c['bands_note'][:40]); print('10', f['outside_clip'])"
ls data/thanet/out/networks/rail_x*_y*.jsonl | wc -l; ls data/thanet/out/networks/barriers_x*_y*.jsonl | wc -l; ls data/thanet/out/coast/ground_x*_y*.tif | wc -l
```
Expected: every step exits 0; every manifest carries `clip` with `keep left` and the clipped-site keys of PIPELINE_CHANGES.md 9.3; **rail `segments > 0`** with `by_class` = `rail` (≤ 217 ways, BRIEF §8) plus `miniature` (≤ 2), `ways_skipped_by_class.railway` = `{abandoned: 20, razed: 16, platform: 7}` (minus any outside the grid), `gauge_defaulted` small (the named lines carry `gauge=1435`), covering the Birchington–Margate–Broadstairs–Ramsgate line (tiles from the west edge to the Ramsgate area, `length_km` of the order of 30); barriers `by_class` with `fence` ≤ 1,155, `wall` ≤ 788, `hedge` ≤ 179, `retaining_wall` ≤ 43, `kerb` ≤ 24 (the raw way counts of BRIEF §8, reduced by the grid and clip drops the manifest counts); `ways_skipped_by_class.barrier` = `{gate: 40, bollard: 30, …}`; massing `height_calib.source == fitted` (mode auto with ~4× Margate's buildings) — `1.385 + 2.646×levels`, `{n: 2948, rejected: 176, rmse_m: 1.21, excluded_off_clip: 78}`: the fit population is the population the model emits, so the 78 mainland footprints the clip drops are held out and counted (`qa_furniture.json` lives at `out/`, not `out/furniture/`); `09` `tiles_clipped == 103`; ground rasters `nx*ny − tiles_clipped − len(tiles_without_dtm)` = 494 − 103 − 35 = **356**, not 391: step 09 deliberately writes no raster for a position with no DTM and lists it in `tiles_without_dtm` (`OUTPUT.md`, `coast/`), so `391` would mean 35 tiles were painted from nothing; the rail/barrier tile counts equal `linear_manifest.layers.*.tiles`.

```bash
# 2.5 Margate byte identity after all pipeline edits (PIPELINE_CHANGES.md 9.2)
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH PY=C:/Users/Shadow/code/3duk-env/env/python.exe SITE=margate ./sources/run.sh --from 05
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH SITE=margate C:/Users/Shadow/code/3duk-env/env/python.exe sources/adapters/unity.py
./sources/tests/regress_outputs.sh compare margate before
```
Expected: `N identical, K added (allowed), 0 problems` — added files are only `networks/linear_manifest.json` and `networks/barriers_x*_y*.jsonl` (no `rail_*`: Margate's extract has 0 railway ways and is not re-fetched); step 11 on Margate prints the `NOTE -- no railway ways in the extract` line. **0 CHANGED, 0 REMOVED** is the stage gate.

```bash
# 2.7–2.9 adapter streetscape documents
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/test_unreal_adapter.py
PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH SITE=thanet C:/Users/Shadow/code/3duk-env/env/python.exe sources/adapters/unreal.py
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/blender/tests/schema_check.py data/thanet/out/unreal/streetscape/site_x*_y*.json | tail -1
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; m=json.load(open('data/thanet/out/unreal/streetscape/streetscape_manifest.json')); print(m['documents'], m['splines_by_layer'], 'thin', m['thin_tolerance_m'], m['thin_max_dev_m'], 'points', m['points_in'], '->', m['points_out'], 'ways', m['ways'], m['ways_multi_run'], m['ways_with_gaps'], 'junctions', m['junctions'], 'overlay clipped', m['overlay_ways_clipped'], 'profiles', m['profile_ids_used'], 'warnings', m['warnings'])"
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; d=json.load(open('data/thanet/out/unreal/streetscape/site_x15_y15.json')); s=[s for s in d['splines'] if s['id']=='roads:30253079:0'][0]; print(s['source']['name'], s['profile_ids'], len(s['points']), 'z' in s['points'][0], s['overlay']['kind'], len(s['overlay']['pts']), s['continues_to'])"
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json, glob; m=json.load(open('data/thanet/out/unreal/landscape/landscape_manifest.json')); print(m['weight_sum_histogram'], sum(1 for t in m['tiles'] if t['files']['weights'] is None)); print(len(glob.glob('data/thanet/out/unreal/landscape/weight_grass_*.r8')))"
```
Expected: `OK`; the adapter exits 0 with `warnings` empty (step 11 has run); the validator's last line reports every document `VALID`; `splines_by_layer` has `roads`, `rail > 0`, `barriers > 0`; `thin_max_dev_m ≤ 0.10`; `profile_ids_used.road` ⊆ the 20 library ids and includes `rail_standard`, `.edge` includes `edge_uk_kerb`, `edge_barrier_only`, `.hedge` includes `hedge_privet`; the Trinity Square spline shows `Trinity Square {'road': 'road_residential', 'edge_left': 'edge_uk_kerb', 'edge_right': 'edge_uk_kerb', 'hedge_left': None, 'hedge_right': None} <≈ 15 points> False osm_way 11 roads:879045149:0` (no `z` on points; the raw way's 11 vertices as overlay); the weight histogram has counts only at keys `255, 254, 253, 252, 0`, `weights: null` only for `tiles_without_ground_raster`, and `391` grass weight files (minus those).

```bash
# 2.10 JSON loader parity with the schema fixtures
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Json; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
```
Expected: `Result={Passed}` for `Streetscape.Json.SchemaFixtures` (`examples/test_stretch.json` and `synthetic_straight.json` load unchanged; unknown key rejected in strict mode; enums lower snake) and `Streetscape.Json.RoundTrip` (save is byte-equal after canonical ordering).

```bash
# 2.11 / 2.12 overlay over the landscape, headless
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 03_import_streetscape.py -Args "--json C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 05_screenshot.py -Args "--x 8030 --y 8165 --z 45 --yaw 0 --pitch -60 --out C:/Users/Shadow/code/3duk/projects/one/Tools/ue/shots/overlay_trinity.png" -Render
```
Expected: `THANET_OK 03_import_streetscape {"actors": N, ...}` with N equal to `streetscape_manifest.splines_by_layer` summed (≈ 24k, DESIGN.md 10); the log reports `LoadSite` document count = `documents`; the screenshot shows magenta overlay lines 0.3 m above the terrain along Trinity Square with the landscape beneath. Save then reopen in a second commandlet: the actor count is unchanged and overlays re-drape (`OnRegister`).

**Depends on:** 0, 1. **Blocks:** 7, 8.

---

## Stage 3 — Shared spline

BRIEF 5 row 3, with DESIGN.md 3 and SCHEMA.md 3 as the algorithm. Waypoints carry position, optional
roll, optional width override and tags; BRIEF 1.1's "profile id per waypoint" is expressed as an
s-ranged `segments[]` entry (a waypoint profile id is a segment from that knot to the next with no
ramp — DESIGN.md 19), so no `points[].profile_ids` field exists. Curvature-adaptive resampling with
mandatory stations, arc-length `s`, terrain sampling at every station, moving-average smoothing with
end pinning, banking with the clamp and the 0.25°/m rate limit, frames.

**Owner:** geometry (3.1–3.6), unreal (3.7–3.10).

### Tasks

1. Implement `Tools/blender/streetscape/terrain.py` (`Heightfield.from_landscape_dir`, `from_step05_dir`, `from_function`, `sample` with the bilinear rule of DESIGN.md 8, `origin {E, N}` carried so a document authored in another origin can be shifted: the Thanet-frame stretch on Margate's step-05 tiles is `+5120, +5120`). — geometry
2. Implement `Tools/blender/streetscape/noise.py` (`lowbias32`, `unit_noise`, `lattice`, `value_noise3`, `fbm3`, DESIGN.md 3.8) and `tests/test_noise.py`. — geometry
3. Implement `Tools/blender/streetscape/spline.py` (`Spline`: duplicate merge, centripetal Catmull-Rom, adaptive stations with mandatory stations, `s`, `width(s)`/`roll(s)` with ramped segment overrides, heights + gap fill + centred moving average with end pinning + `z` pins, bank probes/clamp/mask/rate limit, `Frames`, `edge_offset(side)`/`edge_height(side)`) per SCHEMA.md 3. — geometry
4. Implement `schema.py` resolution functions (`resolve_sampling`, `resolve_road`, `resolve_side`, `paint_intervals`, `apply_ramped_override`) and `tests/synthetic.py` (the three synthetic roads, `rail_R300_600`, the `from_function` terrains). — geometry
5. Write `tests/test_terrain.py` and `tests/test_spline.py` (`test_stations`, `test_width`, `test_smoothing`, `test_bank`, `test_frames`) against `fixtures/expected.json`. — geometry
6. Implement `build.py` up to `build_spline` producing the spline stats keys `length_m, n_samples, step_min/max/mean, z_raw_nan_count, bank_min/max` in `stats.json` (renderers attach in stages 4–6). — geometry
7. Implement `Public/StreetSplineMath.h` + `.cpp` (`FStreetSplineMath`, `FStreetFrames`: the verbatim port of `spline.py`, D8) and `Public/StreetSpline.h` + `.cpp` (`UStreetSplineMetadata`, `UStreetSplineComponent` wrapping `USplineComponent` for gizmos, `Build()`/`Resample()`, `FStreetSamples`). — unreal
8. Implement `Public/StreetTimelines.h` + `.cpp` (`FStreetRoadTimeline`, `FStreetSideTimeline`, `FStreetSideSpec`, the mirror of the numpy resolution functions). — unreal
9. Implement `Public/StreetGeometry.h` + `.cpp` `FStreetNoise` and the tests `Private/Tests/StreetSplineTests.cpp` (`Streetscape.Spline.Stations`, `.Smoothing`, `.Bank`, `.Frames`) and `StreetNoiseTests.cpp` (`Streetscape.Noise.KnownAnswer`) reading `Tools/blender/tests/fixtures/`. — unreal
10. Make `AStreetscapeActor` build its spline on `OnRegister` from the loaded JSON through `UStreetHeightfieldTerrain` and expose `ActorStatsJson` with the spline keys. — unreal

### Acceptance checks

```bash
cd /c/Users/Shadow/code/3duk
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_terrain.py" -v
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_noise.py" -v
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_spline.py" -v
```
Expected: `OK` three times. The numbers asserted (SCHEMA.md 9.3, DESIGN.md 3.7–3.8): `straight_100` **N = 54** stations (51 adaptive + 3 drop-kerb stations at 69.085 / 71.83 / 72.745), gaps min 0.17 / max 2.0, every adaptive–adaptive gap 2.0, `s` monotone with `s[0] = 0`; `w(40) = 6, w(45) = 7.0 ± 1e-9, w(50) = 8`; `sine_5_50` L = 109.2 ± 0.1, N = 101 ± 3, crest spacing ≤ 0.85, inflection ≥ 1.5, ratio ≥ 1.8; `curve_R20_200` N = 117 ± 2, arc 1.00 ± 0.03, straights 1.99 ± 0.02; smoothing on the 2 % grade with `0.1·√3·unit_noise(i, 7)`, W = 20: interior RMS factor **≥ 2.5** (2.837), max err ≤ 0.08, ends pinned, grade 0.0196 ± 0.002, W = 10 factor ≥ 1.7, two passes ≥ 3.0, 8 m ripple RMS 0.0700 → ≤ 0.010; bank 5.71° → 4.00° clamp, roll mask blend, rate limit 0.25°/m; frames `t_h·n = 0`, `b·Z = cos β`, `n·Z = sin β` to 1e-12; `Heightfield.sample` equals the `ground()` transcription on 10 000 hashed points (max abs diff 0, NaN count exact); `lowbias32(1) = 0x688990c0`, `lowbias32(2) = 0xd1132181`, `lowbias32(0xdeadbeef) = 0xe628c683`, `unit_noise(0..4, 7) = −0.33847302, 0.94551079, −0.62749659, 0.96820159, 0.64059920`.

```bash
# the edge contract: nothing outside spline.py computes width/2
grep -rn "width_m *\/ *2\|w *\/ *2\|/ *2\.0" projects/one/Tools/blender/streetscape/road.py projects/one/Tools/blender/streetscape/edge.py projects/one/Tools/blender/streetscape/hedge.py; echo "grep exit=$?"
```
Expected: no output, `grep exit=1` (`test_examples.py` repeats this check).

```bash
# spline stats on the real stretch (terrain from stage 1; before stage 1 finishes, from_step05_dir on data/margate/out with the +5120 shift is a convenience, not the reference)
PYTHONPATH=C:/Users/Shadow/code/3duk/projects/one/Tools/blender C:/Users/Shadow/code/3duk-env/env/python.exe -m streetscape.build --site C:/Users/Shadow/code/3duk/projects/one/schema/examples/test_stretch.json --terrain C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape --out C:/Users/Shadow/code/3duk/projects/one/Tools/blender/out/test_stretch
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; s=json.load(open('projects/one/Tools/blender/out/test_stretch/authored:trinity_square/stats.json')); print(s['length_m'], s['n_samples'], s['step_min'], s['step_max'], s['z_raw_nan_count'], s['bank_min'], s['bank_max'])"
```
Expected: `length_m = 171.40 ± 0.05`, `z_raw_nan_count = 0`, `step_min ≥ 0.25`, `step_max ≤ 2.0`, `|bank| ≤ 4.0`; the smoothed profile matches the `dtm_ma15_s_z` table of `docs/design/adapter_and_test_stretch.md` B6: `z_ref(10) = 20.47`, `z_ref(100) = 19.35`, `z_ref(160) = 18.24`, each ± 0.02 m.

```bash
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Spline; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Noise; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
```
Expected: `Result={Passed}` for `Streetscape.Spline.Stations`, `Streetscape.Spline.Smoothing`, `Streetscape.Spline.Bank`, `Streetscape.Spline.Frames` (the left kerb of `synthetic_straight` has JSON `y > 0` and UE `Y < 0`) and `Streetscape.Noise.KnownAnswer` — the same `fixtures/expected.json` numbers as the numpy suite.

**Depends on:** 0 (the real-stretch check additionally needs 1). **Blocks:** 4, 5, 6, 7.

---

## Stage 4 — Renderer A: road surface

BRIEF 5 row 4: road ribbon with camber/bank, per-segment width, markings as material-ID sub-meshes in the
same build pass; double yellow, single yellow and centre dashes expressible purely as profile data.
Marking offsets and widths are measured from the mesh. Lifted strips at `lift_m 0.004` (DESIGN.md 4.1).

**Owner:** geometry (4.1–4.4), unreal (4.5–4.7).

### Tasks

1. Implement `Tools/blender/streetscape/sweep.py` (`Section`, `SectionPoint`, `sweep()` — the one cross-section sweep, geometric winding, caps, UV `u = s`) and `mesh.py` (`MeshBuffer`, `triangulate_polygon_2d`, `stats()`, `validate()`, `is_closed_manifold`, `measure_lateral_overlap`, `coincident_xy_pairs`) with `tests/test_sweep_mesh.py`. — geometry
2. Implement `Tools/blender/streetscape/road.py` (`build_road`: ribbon rows at `±edge_offset`, skirts at `±(edge_offset + overlap_m)` dropped `skirt_drop_m`, parabolic/planar/none camber, per-station width from `edge_offset`, markings swept over the shared frames plus interpolated dash-end frames as `marking:*` groups; dispatch to `rail.build_rail` reserved for stage 7). — geometry
3. Write `tests/test_road_markings.py` (`test_markings`, `test_camber`, `test_edge_anchor_follows_ramp`). — geometry
4. Extend `build.py` so `BuildResult.road` and the `road`/`skirt_*`/`marking:*` buffer stats land in `stats.json` (per-buffer `verts`, `tris`, `per_material`, marking strip count). — geometry
5. Implement `Public/StreetGeometry.h` + `.cpp` `FStreetMeshBuilder`, `FStreetSection`, `FStreetSweep::Sweep`, `FStreetGeometry::ToDynamicMesh` (winding flip `(a, c, b)`, normals mirrored, material IDs via the attribute set) and tests `Private/Tests/StreetSweepTests.cpp` (`Streetscape.Sweep.Manifold`), `StreetGeometryTests.cpp` (`Streetscape.Geometry.ToDynamicMesh`). — unreal
6. Implement `Public/StreetRenderers.h` + `.cpp` `UStreetRendererBase` (subclass of `UDynamicMeshComponent`, D6; `PreSave` stash / `PostSaveRoot` restore, complex-as-simple collision) and `UStreetRoadRenderer` mirroring `road.py`, with `Private/Tests/StreetRoadTests.cpp` (`Streetscape.Road.Markings`). — unreal
7. Wire `AStreetscapeActor::RebuildAll` for the `Road` component and extend `ActorStatsJson` with the road buffer keys. — unreal

### Acceptance checks

```bash
cd /c/Users/Shadow/code/3duk
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_sweep_mesh.py" -v
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_road_markings.py" -v
```
Expected: `OK` twice. Numbers (SCHEMA.md 9.3): `straight_100` ribbon **11 rows → 594 vertices / 1060 triangles** (groups `road`, `skirt_*` only); closed square swept along `straight_100` is a closed manifold with outward normals and `2·4·(N−1) + 2·2` triangles; `triangulate_polygon_2d` on the 11-point kerb polygon → 9 triangles with area equal to the polygon's (diff < 1e-12); `validate()` empty; **centre dashes (TSRGD 1004, 4 m / 2 m): 17 dashes `[0,4] [6,10] … [96,100]`** with ends within 1e-9 and strip `vd ∈ {−0.05, +0.05}`; **double yellow (1018.1) on the left: pair centre `o0 − 0.25`, line centres `o0 − 0.35` and `o0 − 0.15`**, each 0.10 wide, and at `s = 45` (`w = 7`) every yellow vertex is exactly 0.5 m further out than at `s = 40` (the edge anchor follows the 6 → 8 m ramp); **every marking vertex is `0.004 ± 1e-9` above the road surface** at the same `(s, d)`; single yellow is the same profile row with `pattern solid` and `double_gap_m` absent — no code path is specific to any marking; camber `surface_h(0) = 0`, `surface_h(±3) = −0.0375` for w 6 at 2.5 %, planar `−0.075`.

```bash
# the marking set is data: the three UK cases exist as profile rows, not as code
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; p=json.load(open('projects/one/schema/profiles/road_residential.json'))['profile']; t=json.load(open('projects/one/schema/examples/test_stretch.json')); r=t['profiles']['road']['road_trinity']; print([ (m['id'], m['pattern'], m.get('anchor'), m.get('double_gap_m')) for m in r['markings']])"
grep -c "double_yellow\|DoubleYellow\|centre_dash\|CentreDash" projects/one/Tools/blender/streetscape/road.py projects/one/Plugins/Streetscape/Source/Streetscape/Private/StreetRenderers.cpp
```
Expected: `[('centre_1004', 'dashed', 'centre', None), ('dyl_left_1018_1', 'double', 'edge_left', 0.1)]` (the stretch's marking set); `0` and `0` — no marking-specific identifiers in renderer code.

```bash
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Sweep; Automation RunTests Streetscape.Geometry; Automation RunTests Streetscape.Road; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
```
Expected: `Result={Passed}` for `Streetscape.Sweep.Manifold`, `Streetscape.Geometry.ToDynamicMesh` (vertex count == input, winding flipped) and `Streetscape.Road.Markings` (strip centres/widths/dash ends/lift 0.004/double gap/edge anchor on the 6→8 ramp), all against `fixtures/expected.json`.

**Depends on:** 3. **Blocks:** 5, 7, FD.

---

## Stage 5 — Renderer B: edge extrusion

BRIEF 5 row 5: kerb with lip + pavement + drop kerbs + split materials + barrier segments (brick wall /
chain-link / railing) + embankment/retaining entries; **road-over-kerb overlap ≥ 3 cm everywhere including
across a width change** (the design value is 0.040 m, schema floor 0.03). Tests: no zero-width seam,
overlap measured. Half-grass / half-tarmac is `split` on the profile with a flush top at
`boundary_frac`; drop kerbs carry both materials down (DESIGN.md 4.2).

**Owner:** geometry (5.1–5.4), unreal (5.5–5.7).

### Tasks

1. Implement `Tools/blender/streetscape/edge.py` (`build_edge`: the A–G section of DESIGN.md 4.2 per station from the resolved `SideSpec`, drop-kerb factor with smoothstep ramps and the pavement back-edge rule, split materials on one flush row set, barrier sections and post/rail instance lists per type, embankment batter / retaining wall gating, caps at mask-run ends). — geometry
2. Write `tests/test_edge.py` (kerb rows, drop kerb, split, barriers, embankments on the step terrain). — geometry
3. Write `tests/test_seam.py` (rules 1–6 of DESIGN.md 5 on all three synthetic roads, with and without the drop kerb and with a mid-spline `edge_uk_half_grass` switch). — geometry
4. Extend `build.py` so `BuildResult.edge[side]`, `instances` and the per-side `overlap_min/max` reach `stats.json`; write `tests/test_examples.py` (end-to-end build of `synthetic_straight.json` on flat terrain, the import-graph rule, the `width/2` grep, the Chaikin-vs-OSM overlay Hausdorff check). — geometry
5. Implement `UStreetEdgeRenderer` in `StreetRenderers.h` + `.cpp` mirroring `edge.py` (timelines from `StreetTimelines.h`, instances as `UInstancedStaticMeshComponent` children for posts/rails), and the tests `Private/Tests/StreetEdgeTests.cpp` (`Streetscape.Edge.Overlap`, `Streetscape.Edge.DropKerb`, `Streetscape.Edge.Barriers`) and `StreetSeamTests.cpp`. — unreal
6. Wire `EdgeLeft` / `EdgeRight` into `AStreetscapeActor::RebuildAll` and `ActorStatsJson` (`overlap_min/max` per side, kerb/pavement buffer counts, instance counts). — unreal
7. Assert at build time that the edge renderer's stations equal the road renderer's (`np.array_equal` rule 2; C++ `check`) and log `Streetscape.Perf.Tile` timings (`Private/Tests/StreetPerfTests.cpp`). — unreal

### Acceptance checks

```bash
cd /c/Users/Shadow/code/3duk
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_edge.py" -v
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_seam.py" -v
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_examples.py" -v
```
Expected: `OK` three times. Numbers: kerb rows D, S, E flush (`max|Δz| < 1e-12`), B at `−0.03`, A at `o = −0.02`; **left drop kerb on `straight_100`: `hk(70.915) = 0.006 ± 1e-6`, `hk(69.5425) = hk(72.2875) = 0.0655 ± 1e-6`, back edge F at 0.150 in the flat run**, both split materials present on the ramp triangles; wall over `[0, 45]` closed manifold with coping; **chain-link over `[45, 100]` at pitch 3 → 19 posts**; railing → 3 rails at `rails_m`; batter only where `dz > 0.35`, retaining wall where `dz < −0.35`; **`measure_lateral_overlap` min = max = 0.040 at all 54 stations, both sides, including inside the 6 → 8 m ramp**; identical station sets between road and edge buffers (marking groups excluded); **coincident distinct positions exactly 2 per station in `[o0, o0 + 0.04]` and 0 in `(o0 + 1e-6, o0 + 0.04]`** — no zero-width seam; `|road_edge_row.z − (z_ref + h0)| < 1e-9`, kerb row B exactly `td` below; kerb-face `(x, y)` equals road-edge `(x, y)` to 1e-9 across the ramp; `test_examples`: three builders exported, `road/edge/hedge` never import each other, Hausdorff spline↔raw ≤ 1.5 m on the right-angle way.

```bash
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Edge; Automation RunTests Streetscape.Perf; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
```
Expected: `Result={Passed}` for `Streetscape.Edge.Overlap` (0.040 at every station both sides; coincident positions 2·N; height coherence 1e-9; flush split top), `Streetscape.Edge.DropKerb` (0.006 / 0.0655 / 0.150; both materials on the ramp), `Streetscape.Edge.Barriers` (wall manifold; 19 posts; 3 rails); `Streetscape.Perf.Tile` logs ms per actor (informational).

**Depends on:** 3, 4. **Blocks:** FD, 6.

---

## FIRST DELIVERABLE — stages 3–5 on the test stretch in Blender and Unreal

BRIEF 5 row "First deliverable" and BRIEF 1.1: the shared spline + Renderer A + Renderer B on
`schema/examples/test_stretch.json` (Trinity Square, Margate, Thanet frame, SCHEMA.md 9.1), built by the
Blender prototype (renders committed as PNG via LFS) **and** by the Unreal plugin (level saved, screenshot),
both checked against the same numbers.

**Owner:** geometry (FD.1–FD.3), unreal (FD.4–FD.6), integration (FD.7).

### Checklist — every BRIEF 1.1 first-deliverable item and where it is proved

| BRIEF 1.1 item | in `test_stretch.json` | numpy check | Unreal check |
|---|---|---|---|
| varying road width | `width_m` 6.0 on the eastern points, 6.479 / 7.0 at the taper knots (`s` 140.2 / 145.0 / 150.2) | `stats.json` `w_max = 7.0`; `edge_offset` 3.0 → 3.5 across the taper | `ActorStatsJson` same values |
| double yellows + centre dashes | profile `road_trinity` = `road_residential` + `centre_1004` (whole length) + `dyl_left_1018_1` (`s0_m 0, s1_m 60`) | marking strip count and centres per stage 4 rules measured on the real build | `Streetscape.Road.Markings`; screenshot cam1 |
| a drop kerb | `drop_kerbs`: right, `s_m 38.8, length 3.0, ramp 0.9, target 0.0` (vehicle) and left, `s_m 75.0, length 1.83, ramp 0.915, target 0.006` (pedestrian) | `hk` in the flat runs 0.0 / 0.006; ramps 37.9–38.8, 41.8–42.7 and around 75 | screenshot cam3 (first drop kerb) |
| a half-grass / half-tarmac kerb | segment `half_grass_left` `edge_uk_half_grass` for `s` 0–95.9, `boundary_frac 0.5` | flush top, `grass` outer / `kerb_concrete` inner; the pedestrian drop at 75 carries both materials down | material IDs on the left edge component |
| a width change with correct road-over-kerb overlap | the 6 → 7 m taper | `overlap_min = overlap_max = 0.040` both sides at every station incl. the taper | `ActorStatsJson.overlap_min/max` 0.040 |
| LiDAR-sampled, smoothed heights | `sampling.smoothing_window_m 15.0`, one pass; heights from Thanet tile (15, 15) = Margate tile (5, 5) | `z_ref(10) = 20.47`, `z_ref(100) = 19.35`, `z_ref(160) = 18.24` ± 0.02; `z_raw_nan_count 0` | same via `UStreetHeightfieldTerrain` (bit-identical bytes) |
| a debug overlay of the source OSM polyline | `overlay.kind osm_way`, `osm_id 30253079`, 11 raw vertices | `overlay.json` written, densified at 2 m, lifted 0.3 m | `Overlay` component visible 0.3 m over the road (screenshot cam2) |

Also on the stretch, as the base for stages 6–7: brick wall → chain-link → railing on the right at
45 / 95 / 140 (stage 5), privet hedge 0.4 m behind the fence for 55–90 (stage 6 — the hedge component is
allowed to be absent at the first-deliverable gate and must be present at the stage 6 gate).

### Tasks

1. Implement `Tools/blender/streetscape/bpy_bridge.py` (`to_object`, materials by name, per-loop UVs, instances as linked duplicates, overlay as an emissive edge mesh, glTF export) and `render.py` (**`BLENDER_EEVEE`** — BRIEF §8: Workbench is not selectable under `-b` on this machine, superseding DESIGN.md 14's Workbench choice; the three fixed cameras of geometry.md 5.12, 1920×1080 PNG), and `blender_main.py` (args after `--`, `build_all` → bridge → optional glTF/renders; non-zero exit on any `validate()` message). — geometry
2. Build the stretch headless and commit `Tools/blender/renders/trinity_square_cam{1,2,3}.png` (LFS) plus `Tools/blender/renders/trinity_square.stats.json` (a copy of the build's `stats.json`, the numeric reference the Unreal side is diffed against). — geometry
3. Confirm `schema/examples/test_stretch.json` needs no edit; if a number in it must change, update SCHEMA.md 9.1 in the same commit. — geometry
4. Complete `AStreetscapeActor` (`Spline` root, `Road`, `EdgeLeft`, `EdgeRight`, `Overlay`; `bRebuildOnLoad`; `PreSave`/`PostSaveRoot`; `bIsSpatiallyLoaded`), `AStreetscapeSiteActor::PostLoad` material resolution, and the `--player-start` option of `03_import_streetscape.py` (a `PlayerStart` 2 m above the first waypoint, yaw = bearing − 90). — unreal
5. Save the level with the stretch imported (`Content/Thanet/Maps/Thanet.umap` and its OFPA actors are regenerated by the scripts; commit the map only if small, BRIEF 4.3) and produce `Tools/ue/shots/trinity_square_cam{1,2,3}.png` from the same three camera definitions. — unreal
6. Write `Tools/ue/compare_stats.py` (stdlib: diff `ActorStatsJson` against the Blender `stats.json` on the parity keys of DESIGN.md 14 with the tolerances below; exit non-zero on a mismatch). — unreal
7. Record both builds' numbers side by side in `projects/one/README.md` and update the §0 status table. — integration

### Acceptance checks

```bash
# FD.1 / FD.2 Blender build: numeric core, then bpy + glTF + renders
cd /c/Users/Shadow/code/3duk
PYTHONPATH=C:/Users/Shadow/code/3duk/projects/one/Tools/blender C:/Users/Shadow/code/3duk-env/env/python.exe -m streetscape.build --site C:/Users/Shadow/code/3duk/projects/one/schema/examples/test_stretch.json --terrain C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape --out C:/Users/Shadow/code/3duk/projects/one/Tools/blender/out/test_stretch
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --python C:/Users/Shadow/code/3duk/projects/one/Tools/blender/streetscape/blender_main.py -- --site C:/Users/Shadow/code/3duk/projects/one/schema/examples/test_stretch.json --terrain C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape --out C:/Users/Shadow/code/3duk/projects/one/Tools/blender/out/test_stretch --gltf --render; echo "blender exit=$?"
ls projects/one/Tools/blender/out/test_stretch/authored:trinity_square/ projects/one/Tools/blender/out/test_stretch/renders/ projects/one/Tools/blender/out/test_stretch/*.glb
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; s=json.load(open('projects/one/Tools/blender/out/test_stretch/authored:trinity_square/stats.json')); print(s['length_m'], s['n_samples'], s['overlap_min'], s['overlap_max'], s['marking_strips'], {k: (v['verts'], v['tris']) for k, v in s['buffers'].items()}, s['instances'])"
```
Expected: `blender exit=0`; `road.npz edge_left.npz edge_right.npz instances.json overlay.json stats.json`, `renders/authored:trinity_square_cam1.png … cam3.png`, one `.glb`; **`length_m 171.40 ± 0.05`**, `overlap_min == overlap_max == 0.040` (both sides), `marking_strips` = 17-per-100-m centre dashes over 171.4 m + 2 double-yellow lines (the exact count is frozen into `renders/trinity_square.stats.json` when first measured and quoted in README), instances `post_round` 18 (chain-link `[45, 95]` at 3.0 m → `floor(50/3) + 1 + [frac(16.67) > 0.5]` = 16 + 1 + 1 = 18, posts at 45, 48, …, 93 and the last at 95; SCHEMA.md 4.10 rule) + `post_square` 23 (railing `[95, 140]` at 2.0 → 23); cam1 shows the double yellows and centre dashes from the left pavement, cam2 the taper from the air, cam3 the vehicle drop kerb at `s` 38.8 with the tarmac inner face and grass outer face of the half-grass kerb beyond.

```bash
# FD.2 renders committed via LFS
cp projects/one/Tools/blender/out/test_stretch/renders/authored:trinity_square_cam1.png projects/one/Tools/blender/renders/trinity_square_cam1.png   # and cam2, cam3, stats.json
git add projects/one/Tools/blender/renders/ && git lfs ls-files | grep trinity_square
```
Expected: three `trinity_square_cam*.png` lines from `git lfs ls-files`.

```bash
# FD.4 / FD.5 Unreal build of the same document, saved, reopened, screenshots
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 03_import_streetscape.py -Args "--json C:/Users/Shadow/code/3duk/projects/one/schema/examples/test_stretch.json --player-start --stats-out C:/Users/Shadow/code/3duk/projects/one/Tools/ue/shots/trinity_square.ue_stats.json"
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/compare_stats.py --blender projects/one/Tools/blender/renders/trinity_square.stats.json --unreal projects/one/Tools/ue/shots/trinity_square.ue_stats.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 04_probe.py -Args "--actor authored:trinity_square --trace-from-above" -Render
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 05_screenshot.py -Args "--camera cam1 --actor authored:trinity_square --out C:/Users/Shadow/code/3duk/projects/one/Tools/ue/shots/trinity_square_cam1.png" -Render   # and cam2, cam3
```
Expected: `THANET_OK 03_import_streetscape {"actors": 1, "player_start": true, ...}` with one `AStreetscapeActor` labelled `authored:trinity_square` carrying `Road, EdgeLeft, EdgeRight, HedgeRight (stage 6), Overlay`; `compare_stats.py` prints `PARITY OK`: `length_m` ± 0.05, `n_samples` equal, `overlap_min/max` 0.040 both, per-buffer vertex/triangle counts of the `road`, `kerb` and `pavement` groups equal, marking strip count equal, instance counts equal (DESIGN.md 14 parity definition); the probe reports a `line_trace_single` from above the road **blocking after the save** (mesh restored by `PostSaveRoot`); a second commandlet reopening the map reports identical counts (`bRebuildOnLoad`); three PNGs written showing what the Blender cameras show, the overlay visible 0.3 m over the road.

```bash
# FD gate: the whole numpy suite and the whole Automation suite
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_*.py" -v 2>&1 | tail -3
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
grep -c "Result={Passed}" projects/one/Saved/Logs/tests.log; grep -c "Result={Failed}" projects/one/Saved/Logs/tests.log
```
Expected: `OK` (every `test_*.py` of stages 0–5); every `Streetscape.*` test implemented so far `Passed`, `0` failed.

**Depends on:** 1, 3, 4, 5. **Blocks:** 6 (its stretch numbers), 8.

---

## Stage 6 — Renderer C: volumetric hedge

BRIEF 5 row 6: a volumetric privet hedge along the shared spline reading the same segment list as
Renderer B, so it stacks cleanly beside walls and fences. Swept closed rounded-rectangle volume with
`fbm3` displacement and leaf-card instances (DESIGN.md 4.3); never a thin wall with a leaf texture.

**Owner:** geometry (6.1–6.3), unreal (6.4–6.5).

### Tasks

1. Implement `Tools/blender/streetscape/hedge.py` (`build_hedge`: inner face at `edge_offset + kw + pw + [barrier.offset_m + thickness] + hedge.offset_m` from the one `SideTimeline`, base `h0 + hk_back − base_sink_m`, rounded section with `corner_points`, `top_profile`, per-vertex `noise_amplitude_m · fbm3(V/noise_scale_m, seed)` displacement with the base row undisplaced, leaf cards `floor(area·density + frac)` per surface triangle from the same hash sequence). — geometry
2. Write `tests/test_hedge.py`. — geometry
3. Extend `build.py`/`bpy_bridge.py` for `BuildResult.hedge[side]` and `leaf_card` instances; rebuild the stretch so `hedge_right.npz` exists and the renders/stats in `Tools/blender/renders/` are refreshed. — geometry
4. Implement `UStreetHedgeRenderer` in `StreetRenderers.h` + `.cpp` mirroring `hedge.py` (cards as an `UInstancedStaticMeshComponent`, `mode instances` reserved), `Private/Tests/StreetHedgeTests.cpp` (`Streetscape.Hedge.Volume`), and wire `HedgeLeft`/`HedgeRight` into `AStreetscapeActor` and `ActorStatsJson`. — unreal
5. Re-import the stretch and refresh `Tools/ue/shots/trinity_square_cam2.png` and the parity comparison. — unreal

### Acceptance checks

```bash
cd /c/Users/Shadow/code/3duk
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_hedge.py" -v
```
Expected: `OK`. The volume is a closed manifold before and after noise (`is_closed_manifold` True); bottom row undisplaced; `max|δ| ≤ 0.06 + 1e-9`; **inner-face offset = wall outer face + `hedge.offset_m` where a wall is in force and = pavement back edge + `hedge.offset_m` where none is** (to 1e-9) — the "stacks beside walls/fences" rule; leaf-card count within ±5 % of `12·area`; a re-run gives bit-identical vertices (seeded hash, no actor-id seeds).

```bash
PYTHONPATH=C:/Users/Shadow/code/3duk/projects/one/Tools/blender C:/Users/Shadow/code/3duk-env/env/python.exe -m streetscape.build --site C:/Users/Shadow/code/3duk/projects/one/schema/examples/test_stretch.json --terrain C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape --out C:/Users/Shadow/code/3duk/projects/one/Tools/blender/out/test_stretch
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json, numpy as np; s=json.load(open('projects/one/Tools/blender/out/test_stretch/authored:trinity_square/stats.json')); print(s['buffers']['hedge_right'], s['instances'].get('leaf_card')); e=np.load('projects/one/Tools/blender/out/test_stretch/authored:trinity_square/hedge_right.npz'); print(e['vs'].min(), e['vs'].max())"
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Hedge; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 03_import_streetscape.py -Args "--json C:/Users/Shadow/code/3duk/projects/one/schema/examples/test_stretch.json --stats-out C:/Users/Shadow/code/3duk/projects/one/Tools/ue/shots/trinity_square.ue_stats.json"
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/compare_stats.py --blender projects/one/Tools/blender/renders/trinity_square.stats.json --unreal projects/one/Tools/ue/shots/trinity_square.ue_stats.json
```
Expected: the stretch has a `hedge_right` buffer spanning `s` 55–90 (`vs.min() == 55.0`, `vs.max() == 90.0`, stations shared with the edge buffer) with an inner face 0.4 m behind the chain-link fence (fence outer face at `4.625 + 0.05` on the 6 m section → hedge inner face at 5.075), leaf-card instances present; `Streetscape.Hedge.Volume` `Passed`; the actor now lists `HedgeRight`; `PARITY OK` including the hedge buffer counts and the card count.

**Depends on:** 5 (and FD's stretch numbers). **Blocks:** 8 (stretch complete).

---

## Stage 7 — Rail profile

BRIEF 5 row 7: standard-gauge track on the Birchington–Margate–Broadstairs–Ramsgate line hugging LIDAR in
cuttings; tessellation visibly tighter on curves. Rail is `RoadProfile.kind = "rail"` on Renderer A
(DESIGN.md 6): ballast ribbon, sleepers as instances, two BS113A rails swept at `±(gauge/2 + head/2)`,
sampling defaults 1.0 / 0.25 / 60 / 40 / 2 / 6°, heights sampled at every station.

**Owner:** geometry (7.1–7.3), unreal (7.4–7.5), pipeline (7.6, already delivered by stage 2 — listed for the check).

### Tasks

1. Implement `Tools/blender/streetscape/rail.py` (`build_rail`, called only from `road.build_road` when `kind == "rail"`: ballast section `(−(w/2 + 0.45·1.5), −0.45) → (−w/2, 0) → (w/2, 0) → (w/2 + 0.675, −0.45)`, sleepers `2.5 × 0.25 × 0.15` at `phase + j·0.65`, rails as the closed 12-point section at `lateral ±0.75243`, `height 0.055`). — geometry
2. Write `tests/test_rail.py`. — geometry
3. Add `--only-layer <roads|rail|barriers>` to the `build.py` CLI and `blender_main.py` (filters splines by `source.layer`), then build the rail worked example (`SCHEMA.md 9.2`, generated by `make_fixtures.py` as `rail_R300_600.json`) and one real tile of the Thanet rail (`data/thanet/out/unreal/streetscape/site_x*_y*.json` containing a `rail:` spline in a cutting near Broadstairs/Dumpton) headless in Blender, committing `Tools/blender/renders/rail_cutting_cam2.png`. — geometry
4. Add the rail branch to `UStreetRoadRenderer` (`Kind == Rail`: same sections, sleepers as instances) and `Private/Tests/StreetRailTests.cpp` (`Streetscape.Rail.Gauge`). — unreal
5. Import the Thanet rail splines (already part of the stage 2 site import) with the renderer active and screenshot a cutting: `Tools/ue/shots/rail_cutting.png`. — unreal
6. Verify the real step-11 rail coverage and gauge fields (stage 2 task 2.6) — the data side of this stage. — pipeline

### Acceptance checks

```bash
cd /c/Users/Shadow/code/3duk
C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s C:/Users/Shadow/code/3duk/projects/one/Tools/blender/tests -p "test_rail.py" -v
```
Expected: `OK`. On `rail_R300_600`: **inner faces of the rail heads 1.435 ± 0.001 m apart**, rail centres 1.5049 ± 0.001, rail top `0.21375 ± 1e-6` above the ballast top; sleepers `floor(L/0.65) + 1` with consecutive pitch `0.65 ± 1e-6` along `s`; ballast toe width `4.75`; **station spacing 1.00 ± 0.02 on the straight and 0.83 ± 0.03 in the R = 300 m bend** (`1/(1 + 60/300)`); every station's height is a terrain sample (`z_raw_nan_count 0`, no lerp between waypoints); no rail-specific code outside `rail.py` and the one dispatch line in `road.py` (`grep -n "rail" projects/one/Tools/blender/streetscape/road.py` shows only the dispatch).

```bash
"C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject -ExecCmds="Automation RunTests Streetscape.Rail; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log
```
Expected: `Streetscape.Rail.Gauge` `Passed` (1.435 ± 0.001 inner faces, 1.5049 centres, rail top 0.21375, sleeper count/pitch, toe 4.75, bend spacing 0.83).

```bash
# the real line: continuous, standard gauge, tighter in the cuttings
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json, glob; n=0; ids=set(); gauges=set(); tiles=[]
for f in sorted(glob.glob('data/thanet/out/unreal/streetscape/site_x*_y*.json')):
    d=json.load(open(f))
    for s in d['splines']:
        if s['source']['layer']=='rail': n+=1; ids.add(s['source']['osm_id']); gauges.add(s['source']['tags'].get('gauge')); tiles.append(tuple(s['source']['tile']))
print('rail splines', n, 'ways', len(ids), 'gauges', gauges, 'tiles x-range', min(t[0] for t in tiles), max(t[0] for t in tiles))"
PYTHONPATH=C:/Users/Shadow/code/3duk/projects/one/Tools/blender C:/Users/Shadow/code/3duk-env/env/python.exe -m streetscape.build --site C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape/site_x<i>_y<j>.json --terrain C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape --out C:/Users/Shadow/code/3duk/projects/one/Tools/blender/out/rail_tile --only-layer rail
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json, glob; [print(f, json.load(open(f))['step_min'], json.load(open(f))['step_max'], json.load(open(f))['step_mean']) for f in glob.glob('projects/one/Tools/blender/out/rail_tile/rail:*/stats.json')]"
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --python C:/Users/Shadow/code/3duk/projects/one/Tools/blender/streetscape/blender_main.py -- --site C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape/site_x<i>_y<j>.json --terrain C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape --out C:/Users/Shadow/code/3duk/projects/one/Tools/blender/out/rail_tile --only-layer rail --render
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 05_screenshot.py -Args "--actor rail:<osm_id>:<k> --camera cam2 --out C:/Users/Shadow/code/3duk/projects/one/Tools/ue/shots/rail_cutting.png" -Render
```
Expected: rail splines across the x-range of the isle (Birchington in the west to Ramsgate in the south-east), `gauges == {'1435'}` (or `None` for untagged ways — `flags.gauge_unmapped` count reported by the adapter manifest is small); per rail spline `step_max ≤ 1.0` and `step_min ≥ 0.25` with `step_mean < 1.0` on curved runs; `<i>_<j>` is chosen as a tile with a curved run in a cutting (record which in README); the Blender render and the Unreal screenshot both show sleepers, two rails and ballast following the cutting floor, and the station density visibly tighter on the curve. `<osm_id>:<k>` is the spline id from the tile document.

**Depends on:** 2 (real rail data), 4 (Renderer A). **Blocks:** 8 (rail visible in the explorer is a stage 8 nicety, not a gate).

---

## Stage 8 — Explorer base

BRIEF 5 row 8: `Thanet.uproject` opens to a World Partition map with the landscape, overlay, test-stretch
streetscape and an Enhanced-Input pawn that walks and flies; massing from step 07 shown as grey boxes
(placeholder only). Plus the MCP port behaviour of DESIGN.md 12.

**Owner:** unreal (8.1–8.6), integration (8.7–8.8).

### Tasks

1. Implement `Source/Thanet/ThanetExplorerPawn.h/.cpp`, `ThanetExplorerInput.h/.cpp` (`ACharacter`, capsule 34/88, camera at 64 cm with pawn control rotation, walk 300 / sprint ×2.5, fly 1500 / sprint 6000, step height 45, jump 420, `F` fly toggle via `SetMovementMode(MOVE_Flying)`, `O` overlay toggle; Enhanced Input objects built in C++ in `SetupPlayerInputComponent`: WASD, Mouse2D, Space, LeftControl, LeftShift, F, O) and `ThanetGameMode.h/.cpp` (`DefaultPawnClass`). — unreal
2. Implement `Public/StreetscapeMassingActor.h` + `.cpp` and `UStreetscapeEditorLibrary::ImportMassing` (one actor per `massing/buildings_x{i}_y{j}.jsonl`, rings extruded `base_z − skirt → base_z + h`, ear-clipped caps, material `massing_grey`, `bIsSpatiallyLoaded`) and `Tools/ue/06_import_massing.py`. — unreal
3. Add the `Streetscape` section to `Tools > ` in `StreetscapeEditorModule.cpp` (*Import landscape site…*, *Import streetscape JSON…*, *Import massing…*, *Rebuild all streetscape actors*, *Toggle OSM overlay*) and the details-panel *Rebuild* button on `AStreetscapeActor`. — unreal
4. Verify the UnrealMCP settings copy: `Config/DefaultEngine.ini` `Port=55558`, `bStartInCommandlets=False`, `SetReuseAddr` removed (stage 0 task 0.13) — the GUI check below is the proof. — unreal
5. Produce the final map state: landscape (stage 1), site streetscape actors (stage 2 import with all three renderers now active — verify actor count and `Streetscape.Perf.Tile` timing), test stretch with `PlayerStart`, massing; `EditorStartupMap` and `GameDefaultMap` point at `/Game/Thanet/Maps/Thanet`. — unreal
6. Screenshot set `Tools/ue/shots/explorer_{spawn,cliftonville_cliff,ramsgate_massing,clip_edge}.png` via `05_screenshot.py`. — unreal
7. Update `projects/one/README.md` "how to run" (build → bootstrap → import landscape → import streetscape → import massing → open in the editor → Play) and the §0 status column with commit shas. — integration
8. Commit at the end of the phase with the message stating what was verified and how (BRIEF 4.5). — integration

### Acceptance checks

```bash
cd /c/Users/Shadow/code/3duk
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/build.ps1 | tail -3
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 06_import_massing.py -Args "--dir C:/Users/Shadow/code/3duk/data/thanet/out/unreal/massing"
C:/Users/Shadow/code/3duk-env/env/python.exe -c "import json; print(json.load(open('data/thanet/out/unreal/massing/massing_manifest.json'))['files'])"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Shadow/code/3duk/projects/one/Tools/ue/run_ue_python.ps1 -Script 05_screenshot.py -Args "--x 7573.6 --y 7947.6 --z 80 --yaw 41 --pitch -30 --out C:/Users/Shadow/code/3duk/projects/one/Tools/ue/shots/explorer_ramsgate_massing.png" -Render
grep -n "GameDefaultMap\|EditorStartupMap\|GlobalDefaultGameMode\|Port=" projects/one/Config/DefaultEngine.ini
```
Expected: `Result: Succeeded`; `THANET_OK 06_import_massing {"actors": N}` with **N equal to `massing_manifest.files`** (tiles with buildings); grey boxes over the landscape in the screenshot; `GameDefaultMap=/Game/Thanet/Maps/Thanet.Thanet`, `EditorStartupMap=...Thanet.Thanet`, `GlobalDefaultGameMode=/Script/Thanet.ThanetGameMode`, `Port=55558`.

```text
GUI checks (the only non-headless items in this file; each is recorded in README with a screenshot and the Output Log lines quoted):
1. "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject
   opens on /Game/Thanet/Maps/Thanet with the landscape streaming in (World Partition, 140 proxies), the overlay lines, the test stretch and massing.
   Output Log contains `UnrealMCPBridge: Server started on 127.0.0.1:55558`; meanwhile
   C:/Users/Shadow/code/3duk-env/env/python.exe C:/UnrealProjects/test_bridge.py still answers on 55557 from Alex's editor (UE_PLAN.md 8.9).
2. Play In Editor: the pawn spawns at the PlayerStart 2 m above Trinity Square's first waypoint facing along the road (yaw = bearing − 90);
   WASD walks on the road surface (complex collision on the DynamicMesh), the 12.5 cm kerb is climbed (step height 45 cm), the pavement is walkable,
   `F` switches to flying and back, `Space`/`LeftControl` ascend/descend while flying, `LeftShift` sprints, `O` hides and shows the OSM overlay,
   flying to the Cliftonville cliff (local 8820, 8620) shows the 65–80° face, and flying across the Wantsum line shows the hard straight edge with nothing beyond.
3. Tools > Streetscape menu lists the five entries; the *Rebuild* button on the test-stretch actor rebuilds it in place.
```

```bash
# the round's final state of the repo
git status --short | grep -v '^??' | grep -v 'projects/one/' ; echo "outside projects/one modified above (expect only sources/, README.md, .gitignore, .gitattributes)"
git ls-files projects/one | grep -E 'Binaries/|Intermediate/|Saved/|DerivedDataCache/|\.sln$|__ExternalActors__' ; echo "build products tracked? (expect none) exit=$?"
git lfs ls-files | grep -c "projects/one/Tools/blender/renders/"
```
Expected: no build products tracked (`exit=1`); the committed renders (≥ 4: three stretch cameras + the rail cutting) are LFS objects.

**Depends on:** 1, 2, FD (6 and 7 for the full picture). **Blocks:** nothing — closes the round.

---

## Order of work for the implementation phase

Four tracks. The first three run in parallel from the moment stage 0 lands (stage 0 itself is split by
owner and its parts are independent except that 0.9's `schema_check.py` must exist before the adapter's
tests are run and 0.10's `expected.json` before any spline test). File ownership is DESIGN.md 21;
nobody edits another track's files, and the shared touch points (`lib.py`, `run.sh`, `OUTPUT.md`,
`dryrun.py`, root `.gitignore`) belong to the pipeline track — the adapter track *requests* its
`dryrun.py` hook and `OUTPUT.md` sentence from it (PIPELINE_CHANGES.md 0).

**Track 1 — pipeline + adapter** (stage 0 tasks 0.1–0.7, stage 1 tasks 1.1–1.9, stage 2 tasks 2.1–2.9,
stage 7 task 7.6). Must finish before integration starts: `data/margate/regress/before.sha256` taken
before the first edit and `regress_outputs.sh compare margate before` reporting **0 problems** after
the last; `dryrun.py` at `0 failed` with the site-C checks; the real Thanet chain 01–11 complete with
`terrain_manifest.json` at 391 / 103 / 3,861,822 and `slope_qa.max_deg ≥ 80`; `sources/adapters/unreal.py`
run on Thanet producing the complete `data/thanet/out/unreal/` tree (391 heightmaps, 31 `vis` files,
weights, per-tile streetscape documents that pass `schema_check.py`, massing, furniture, manifests) and
`test_unreal_adapter.py` `OK`. The `way["railway"]` line already landed and the Thanet extract already
contains the rail ways (BRIEF §8), so the only step-01 work on the critical path is the provenance
rewrite; the raw 01–04 products on disk are reused, not re-fetched.

**Track 2 — geometry / Blender** (stage 0 tasks 0.8–0.10, stages 3–7 geometry tasks, FD.1–FD.3). Works
against synthetic terrains until track 1 delivers `data/thanet/out/unreal/landscape`; the only artefacts
that wait for real data are the stretch build (FD) and the rail tile (7.3). Must finish before
integration starts: the whole `Tools/blender/tests` suite `OK` under the env python; `fixtures/expected.json`
frozen with every number of SCHEMA.md 9.3 and DESIGN.md 3.7–3.8 (the C++ tests read it, so freezing it
late blocks track 3); `blender.exe -b` build of `test_stretch.json` exiting 0 with `stats.json`, GLB and
the three renders committed under `Tools/blender/renders/` via LFS.

**Track 3 — Unreal** (stage 0 tasks 0.11–0.15, stages 1–8 unreal tasks, FD.4–FD.6). Compiles empty on
day one, then implements in the mirror order of UE_PLAN.md 2.14 against `fixtures/expected.json`
(terrain → JSON → spline/noise → sweep/geometry → road → edge → hedge → rail), with the landscape
importer and the scripts developed against Thanet's landscape products as soon as track 1 has stage 1.
Must finish before integration starts: `build.ps1` `Result: Succeeded` with no C4459; every
`Streetscape.*` Automation test `Passed` under `-nullrhi`; scripts `01_bootstrap.py` through
`06_import_massing.py` each ending in `THANET_OK` headless; the gated landscape import (D1) resolved one
way or the other with the report JSON kept; the test stretch imported, saved, reopened and screenshotted;
`compare_stats.py` `PARITY OK` against track 2's `stats.json`.

**Track 4 — integration** (stage 0 task 0.15 thereafter, FD.7, stage 8 tasks 8.7–8.8, the §0 status
column). Starts when the three tracks above have met their "must finish" lines, then: re-runs the whole
chain from a clean `data/thanet/` (`reuse_tiles.py` → `run.sh` 01–11 → `unreal.py` → `build.ps1` →
scripts 01–06) recording every output in `projects/one/README.md`; runs the GUI checks of stage 8;
fills the §0 table with `done (commit <sha>)` per stage, or `blocked: <reason>` with the failing
command's output; commits once per phase in the repo's style; refreshes the renders and screenshots
if any number changed. Integration owns `projects/one/README.md` and this file's status column only —
a failing check goes back to the owning track, never gets "fixed" in integration.

---

## Definition of done for this round

The round is done when the §0 table shows stages 0–5 and FD as `done (commit <sha>)`, stages 6, 7 and 8
as `done` or as `blocked: <reason>` with the failing command quoted, and the first deliverable exists
exactly as BRIEF 1.1 words it:

> **FIRST DELIVERABLE**
> Implement the shared spline + Renderer A + Renderer B on a short test stretch that includes: varying road width; double yellows + centre dashes; a drop kerb; a half-grass / half-tarmac kerb; a width change with correct road-over-kerb overlap; LiDAR-sampled, smoothed heights; a debug overlay of the source OSM polyline.
> Then add Renderer C and a rail profile. Keep the system data-driven so Thanet-scale variation is authored as profiles and segment lists, not new C++ classes.

— proved on `schema/examples/test_stretch.json` in **both** Blender (`Tools/blender/renders/trinity_square_cam{1,2,3}.png`
and `trinity_square.stats.json` committed via LFS) **and** Unreal (map saved, `Tools/ue/shots/trinity_square_cam{1,2,3}.png`,
`compare_stats.py` `PARITY OK` on length, station count, overlap 0.040, buffer counts, marking strips and instances), with
the cropped Thanet landscape (391 tiles, the hard Wantsum edge, cliffs ≥ 65° in-engine), the OSM overlay over it, Margate
byte-identical, and every "works" in `projects/one/README.md` backed by a command that was run and its output. "Amazing base
to build on" (BRIEF 1) means exactly that list and nothing that is not on it: buildings beyond grey massing, seafront hero
assets, junction geometry, packaged builds and Nanite/HLOD baking are out of this round by design (DESIGN.md 7, 10, 15).
