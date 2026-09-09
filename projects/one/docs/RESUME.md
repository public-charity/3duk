# Resume here

The VM this is built on drops without warning, and it has already taken the session down five
times. This file is the handover: read it first after any disconnect, and it should be enough to
pick the work up cold. Keep it current — it is the only file that claims to describe *now*.

Last updated: 2026-09-09, during the "finish the base" round.

---

## 1. One paragraph of context

`projects/one` is an Isle of Thanet digital-twin base in Unreal Engine 5.8, built from the `3duk`
pipeline's public-data products (EA 1 m LIDAR + OpenStreetMap, EPSG:27700, ODN metres). The isle is
cut from the mainland by a straight line along the old Wantsum Channel. On top of the terrain sits a
data-driven streetscape system: one shared spline read by three renderers (road, edge extrusion,
hedge), with every variant expressed as profile JSON and arc-length segment lists rather than code.
`docs/BRIEF.md` is the binding brief; section 4 wins over every other document.

## 2. Where the work stands

| | |
|---|---|
| Branch | `thanet-explorer` (not merged to `main`) |
| Last commit | `3e26561` — integrity-pass fixes from the pipeline, geometry and adapter audits |
| Before that | `4bfee9d` massing + explorer pawn, `bc08e22` renderers + landscape import, `98db6f1` pipeline + adapter + geometry + UE core, `8c099f2` design |
| Green as of `3e26561` | `build.ps1` Result: Succeeded · 23/23 Unreal automation tests · 100 numpy tests · dryrun 143+ checks, 0 failed · Margate byte-identical (795 files) |

**Data on disk (all git-ignored, hours to rebuild — do not delete):**

- `data/thanet/raw/` 3.9 GB — 988 LIDAR rasters and the 30 MB OSM extract. Re-fetching costs ~6 min
  for LIDAR and one Overpass call, but the OSM extract will differ from the one everything was built
  against (`sources/provenance/thanet.osm.json` records its sha256).
- `data/thanet/out/` — the survey products: 391 terrain tiles, roads, massing, coast, furniture, rail
  and barriers.
- `data/thanet/out/unreal/` — the engine products: 391 `hm_*.r16`, 391 `clip_*.r8`, 31 `vis_*.r8`,
  weightmaps, 246 streetscape documents (~15,422 splines), massing, furniture.
- `projects/one/Content/` 2.1 GB — the generated level: landscape (2,067 components, 140 proxies),
  216 massing actors, one test-stretch streetscape actor. **Regenerable** by the `Tools/ue` scripts,
  which is why it is ignored; regenerating the landscape costs ~6 minutes plus editor startup.

## 3. What is running right now

A workflow, `thanet-finish-real`, run id **`wf_c1860991-626`**, script at
`~/.claude/projects/C--Users-Shadow-code-3duk/<session>/workflows/scripts/thanet-finish-real-wf_c1860991-626.js`.

Resume it with `Workflow({scriptPath: "<that path>", resumeFromRunId: "wf_c1860991-626"})`. Completed
agents replay from cache; only the interrupted one and its successors re-run. **Do not edit the
shared prompt preamble in that script** — it invalidates every cached agent and throws the finished
work away. Editing one agent's own prompt is safe.

Its five phases run in order because each depends on the last:

1. **Diagnose** — done. Wrote `docs/TERRAIN_ROADS.md` and the tools in `Tools/diag/`.
2. **Terrain fidelity** — fix the tile-boundary seams (D1) and pin down the sampler disagreement (D2).
3. **Road corridor** — stop roads fusing with the ground (D3). The headline.
4. **Full import** — honest gates (D4) and the whole network into the level (D5).
5. **Prove** — an independent verifier re-measures everything, then the README and STAGES status.

If the workflow cannot be resumed, the phases are independent enough to re-launch individually from
the descriptions in section 4 plus `docs/TERRAIN_ROADS.md`.

## 4. The five defects, as measured

`docs/TERRAIN_ROADS.md` is the full analysis with every command and number. In short:

**D1 — tile-boundary seams.** 85 of 737 adjacent tile pairs disagree on the row of samples they
share; worst 5.34 m in visible ground, 10.95 m including ground hidden behind the cut. Cause proven:
every one of the 29,188 disagreeing cells is a cell the survey never measured, and step 05 fills each
tile's NoData from that tile's own neighbourhood, so two tiles invent different heights for the same
edge. The raw rasters agree exactly (0 of 330,946 cells differ). No disagreeing cell is on surveyed
ground, so D1 does not touch any road corridor — it is independent of D3.

**D2 — "two terrain truths" was a misdiagnosis.** The plugin's heightfield and the imported landscape
are the *same data*, agreeing at every grid post to 0.53 mm. They differ only in how they interpolate
*between* posts: bilinear versus the landscape's triangle pairs. The 0.52 m figure is the
interpolation bound of a single 1 m quad with a 2.08 m twist; 0.026 % of quads exceed 0.5 m. Worth
recording and bounding, not "fixing".

**D3 — the fusion Alex saw.** 89.7 % of road stations have terrain above the road surface somewhere
across the carriageway: 24.0 of the 26.7 km sampled, median penetration 6.1 cm, p99 63 cm, max 4.1 m.
The authored test stretch penetrates at 100 % of its stations. **The driver is not the longitudinal
smoothing** — at a 5 m window it is worse (93.5 %). It is the cross-section: a flat or cambered
ribbon meeting a rough, cross-sloping 1 m DTM, negative at 94.4 % of stations against 47.3 % for the
longitudinal term. Recommended fix: conform the landscape to the road over a corridor, as a
deterministic pass writing a *new* product directory, leaving the survey untouched. Core corridor is
7.01 km², 7.1 % of the kept land; median change 4.1 cm, p95 0.34 m.

**D4 — dishonest gates.** `02_import_landscape.py` prints `THANET_OK` and exits 0 whatever its own
probes concluded; `--verify` modes report success on zero actors; some I/O failures are skipped in
silence.

**D5 — the network is not in the level.** Only the hand-authored test stretch was ever imported. The
246 adapter documents (~15,422 splines) have never been built as geometry in the engine.

## 5. Rules that cost previous sessions hours

- **PATH must use the `/c/` form**: `export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"`.
  A `C:/...` entry is invisible to bash — GDAL disappears and numpy's LAPACK dies silently with no
  output at all.
- **Python is only** `C:/Users/Shadow/code/3duk-env/env/python.exe`. The `python`/`python3` on PATH
  are broken Microsoft Store stubs.
- **Every `UnrealEditor-Cmd` run exits 1** because of a VC++ redistributable advisory logged at Error
  severity. `Tools/ue/run_ue_python.ps1` derives the real verdict from the log; anything else that
  trusts the raw exit code will read every success as a failure.
- **UE 5.8 prints `Test Completed. Result={Success}`**, not `{Passed}`.
- **Close the GUI editor before headless work.** Both processes fight over asset locks in `Content/`.
- **Never launch the GUI from an agent**; it blocks on a modal dialog with no one to click it.
- **Blender headless renders with EEVEE only** in `-b` mode on this machine, and its scripts must sit
  on a short path — the session scratchpad path is 270 characters and Blender cannot open files there.
- **Long jobs must run in the background with a log.** The Bash tool caps at 600 s; a landscape import
  is ~6 min, a full build ~2 min, the first editor start several minutes.

## 6. If you are starting completely cold

```bash
cd /c/Users/Shadow/code/3duk && git log --oneline -6 && git status --short
```

Then read, in order: this file, `docs/BRIEF.md` sections 4, 7 and 8, `docs/TERRAIN_ROADS.md` section 1,
and `docs/STAGES.md` for what each stage's acceptance command is. Confirm the tree is still green
before changing anything:

```bash
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/dryrun.py | tail -3
./sources/tests/regress_outputs.sh compare margate before
powershell -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_tests.ps1
```

To look at the world rather than rebuild it, open the editor on the saved level — but only when no
headless job is running:

```bash
"/c/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" "C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject"
```

## 7. Uncommitted work

Agents write into the working tree and the orchestrator commits between phases, so after a crash
there will usually be uncommitted changes from the agent that was mid-flight. They are not
necessarily broken — check them, build, run the tests, and commit what passes rather than discarding
it. `git status --short` and `git diff --stat` are the first two commands after any disconnect.
