# Resume here

## Current checkpoint — 2026-09-10, Phase 1 completion

### Second milestone after source checkpoint `6ef72f0`

- **The earlier green sample used bilinear road construction. The saved Unreal
  site uses triangulated construction** (`Saved/Logs/render_set_all.log`, line
  reporting the loaded `landscape` terrain source, not the capture's private
  `landscape_conformed` probe). `road_fusion_audit.py` and `conform_landscape.py`
  now have explicit `--survey-sampling`, defaulting to `landscape_triangulated`;
  the generic geometry fixture default remains bilinear. QC records the choice.
- Corrected sample state: `Saved/Phase1/sample/714a0b1d99df9fdd3309/state.json`:
  **10 batches pass, 2 fail**, worst ground penetration 13.644 mm and 23.116 mm.
  This mismatch is a real QC
  defect; it has not yet been proved to explain the visible Minnis cutting patches.
- `Tools/diag/structure_inventory.py` measures all 151 flagged segments in 133
  connected groups (83 bridges, 50 tunnels), including five groups across documents.
  It uses mutual nearest endpoints so a 7 cm split stub does not create a branch.
  Latest report: `Saved/Phase1/structures_baseline.json`, now triangulated survey.
- **Useful new evidence at Minnis Road:** raw first-return DSM is almost flat around
  13 m ODN across both rail spans while DTM falls to ~7.5 m under them. Even bridge
  DTM endpoints are too low. Do not use a chord of the DTM endpoints as the deck.
- `Tools/diag/fit_structure_decks.py` fits robust candidate lines to DSM lateral
  20th-percentile samples and rejects coverage, abutment, residual, lateral-spread
  and grade failures. Initial result: 49 bridge candidates, 34 requiring review,
  50 tunnels requiring a different model. **No candidate is production accepted.**
  Minnis fits match first return to max 4.5 cm, at ~0.9% grade. Approaches still need
  up to ~2.8 m correction, so changing the deck alone would leave endpoint steps.
- Five deck-fit failure tests plus 14 QC tests pass (19 total). Inventory and deck-fit
  reports have both been regenerated against triangulated construction.
- Another dishonest green was found: `Streetscape.Spline.NumpyParity` returned success
  when no reference JSON existed, and skipped missing cases/arrays. It now fails
  for those conditions; `run_ue_tests.ps1` generates a fresh reference by default.
  The reference now includes rail and non-planar terrain under both sampling rules.
  Build and fresh-reference automation passed **34/34**, including bit-identical
  non-planar triangulated arrays. `Saved/phase1_tests_sampling.runner.log`.
  Deliberate empty reference `{}` fails with seven missing-case errors and exit 2:
  `Saved/phase1_parity_negative.runner.log`.
- One-document triangulated conform completed in **14.9 seconds** under
  `Saved/Phase1/minnis_conform_triangulated`. It is explicitly a **subset**, despite
  having the full raster directory layout: never import it over the full site.
  Production terrain is unchanged. Its audit has zero LOD-0 station penetration,
  but 7.959% floating stations and 4.480 m maximum float. Partial conform now refuses
  the default production destination; a failure test proves that guard.
- Same Minnis camera with `landscape_lod0_screen_size=0.01` still shows foreground
  grass through the road: `Saved/Phase1/minnis_lod_diagnostic/manifest.json`.
  One frame took 93 s, with the recorded post-success teardown crash. The original
  45 camera definitions remain untouched; `render_set.ps1 -Spec` accepts a candidate
  capture specification. The LOD knob is **not** a proven fix for this cutting.
- Next: audit interiors of actual emitted road triangles, not only sampled analytic
  station cross-sections. Check runtime mesh/probe agreement at the breakthrough.
  Then implement explicit deck profiles plus supported approach transitions.

### Completed first milestone (historical numerical baseline uses bilinear)

This section supersedes the historical September 9 handover below. Read
`PHASE1_QC.md` for the active strategy and acceptance ledger.

- Start: clean tree at `e67b876`, branch `thanet-explorer`. No Unreal editor process
  was running when inspected. Survey and generated products are present.
- User objective: finish a base for high-quality building overlays, with roads and
  streets in a sane state; use fast iterations and durable restart checkpoints.
- Completed: resumable, fail-closed numerical QC; debug overlay off by default in
  Unreal and Blender presentation. O-key now controls the actual world line batch,
  including newly streamed cells. No survey, road geometry or level asset changes.
- Verified: numpy baseline 147 tests; pipeline 167 checks; adapter 47 tests;
  QC failure/resume tests 13; Unreal build succeeded; Unreal automation **34/34**,
  including `Streetscape.Overlay.Lifecycle`. Logs: `Saved/phase1_*.log` and
  `Saved/Logs/phase1_tests.log`. The handover's 32-test count was stale.
- QC sample: 48 documents, 2,868 selected splines = 2,843 measured + 24 structures
  explicitly excluded + one named no-terrain stub. Twelve chunks took 111.34 seconds
  of audit time, about 7–13 seconds each. A second invocation reused all twelve in
  ~5 seconds. State: `Saved/Phase1/sample/70b1f1ab251bc2f0c187/state.json`.
- Numerical baseline: 133,265 stations / 192.737 km; LOD 0 has zero penetration above
  5 mm, but **11.638%** of stations float over 125 mm (max 4.475 m). Penetrated length:
  LOD 1 0.366%, LOD 2 2.657%, LOD 3 7.626%. These are recorded defects, not acceptance.
- Two fixed renders inspected: `Saved/Phase1/overlay_smoke/manifest.json`; overlay
  absent in both. `birchington/station_road_to_the_square.png` has continuous road
  and junction corner. `birchington/railway_bridge_over_minnis_road.png` still has
  conspicuous terrain breakthrough and a sagging railway span. Both PNG guards pass
  with low-detail warnings. Engine had the known **post-success teardown access
  violation**; runner recorded raw -1073741819 after the images/report/log closed.
- Findings: junction conform is already wired; overlay uses SDPG_World already;
  `road_fusion_audit.py --all` in HANDOVER.md is invalid (use `--n 0`).
- Next: investigate Minnis Road using its fixed camera and neighbouring documents;
  separate missing structure elevation from ground/LOD conflict. Inventory connected
  bridge segments and approach endpoint heights before choosing a deck model. Keep
  modelled structure heights in a separate derived product with explicit provenance.
- Useful implementation warning: `Spline.apply_pins` applies sequential local
  triangular corrections, so pinning only a bridge's endpoints does **not** create
  a straight deck. Do not mistake existing Z-pin support for a structure profile.
- Commands (PowerShell, repository root):
  `& projects/one/Tools/python.ps1 projects/one/Tools/phase1_qc.py --max-jobs 2`
  resumes up to two sample chunks (exit 2 = pending, 1 = failed, 0 = numerical
  checks complete). `--scope full --max-jobs 0` measures the full census, still with
  per-chunk checkpoints. Run commands to validate freshness; do not trust an old
  `latest.json` alone after changing source/data.
- Engine build/tests/render require writable AppData engine caches. Sandbox launches
  failed before work; rerunning with approved cache access succeeded. Do not work
  around permissions with another engine invocation.
- No full-site Phase 1 acceptance has been earned. Bridges, cuttings/bare edges,
  crossing paths and junction editing/roundtrip remain open.

---

## Historical checkpoint (superseded; retained for diagnostic context)

The VM this is built on drops without warning, and it has already taken the session down five
times. This file is the handover: read it first after any disconnect, and it should be enough to
pick the work up cold. Keep it current — it is the only file that claims to describe *now*.

Last updated: 2026-09-09, at the end of the "roads above ground, joined properly" round, by the
integrity agent. Sections 3 and 8 are the ones that go stale first.

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
| Last commit | `44f36bd` — a fixed set of 45 viewpoints rendered at every commit, and the road defect finally explained |
| Before that | `b1cd3e5` conform + seams + honest gates + the whole isle in the level, `b1a7c52` this file + `TERRAIN_ROADS.md`, `3e26561` integrity fixes, `4bfee9d` massing + explorer pawn, `bc08e22` renderers + landscape import |
| Re-measured 2026-09-09 by the integrity pass (at `44f36bd` + working tree) | `dryrun.py` **167 passed, 0 failed** · `test_unreal_adapter.py` **Ran 47 … OK** · numpy suite **Ran 116 … OK** · `build.ps1` **Result: Succeeded** · `run_ue_tests.ps1` **26 `Result={Success}`, 0 failures** (`Saved/Logs/tests.log`) · Margate gate **green** (below) |

**The Margate regression gate passes again**, and it can still fail:

```bash
export PY=C:/Users/Shadow/code/3duk-env/env/python.exe
./sources/tests/regress_outputs.sh compare  margate terrain_fix_before   # 1582 identical, 1 extended, 0 problems
./sources/tests/regress_outputs.sh compare  margate baseline_2026-09-08  # 794 identical, 1 extended, 788 added, 0 problems
./sources/tests/regress_outputs.sh selftest margate                      # 12 cases, 0 failed
```

`before` and `fixer_before` are **superseded snapshots and are still red on purpose** — see
`docs/STAGES.md` note (a). Use `terrain_fix_before` or `baseline_2026-09-08`.

**Data on disk (all git-ignored, hours to rebuild — do not delete):**

- `data/thanet/raw/` 3.9 GB — 988 LIDAR rasters and the 30 MB OSM extract. Re-fetching costs ~6 min
  for LIDAR and one Overpass call, but the OSM extract will differ from the one everything was built
  against (`sources/provenance/thanet.osm.json` records its sha256).
- `data/thanet/out/` — the survey products: 391 terrain tiles, roads, massing, coast, furniture, rail
  and barriers.
- `data/thanet/out/unreal/` — the engine products: `landscape/` (391 `hm_*.r16`, 391 `clip_*.r8`,
  31 `vis_*.r8`, weightmaps), 246 streetscape documents (~15,422 splines), massing, furniture, **and
  `landscape_conformed/`** — see §4. `landscape_clean/` and `landscape_seam/` are 25-file 2×2 cutouts
  left behind by `Tools/ue/gate_proofs.py`; they are scratch, not products.
- `projects/one/Content/` 2.1 GB — the generated level: landscape (2,067 components, 140 proxies),
  216 massing actors, 15,423 streetscape actors. **Regenerable** by the `Tools/ue` scripts, which is
  why it is ignored; regenerating the landscape costs ~6 minutes plus editor startup.
- `renders/<commit>/` — the fixed 45-viewpoint render set, committed via LFS with a `manifest.json`
  holding each camera transform and each image's sha256. `renders/b1cd3e5/INDEX.md` is the
  defect-by-defect reading of what the model looks like.

## 3. What this round did, agent by agent

Three agents worked in parallel on Alex's request — *"fix the roads so they are all above ground as
necessary and make sure they join together properly … make this a solid foundation"*. The binding
architectural call was:

> A junction is road **surface**, so filling it is **Renderer A**. There is no fourth renderer.
> The **trimming** of a spline end back to a junction belongs one level lower, in the **shared spline
> layer**, so Renderer A and Renderer B read one trimmed extent and cannot drift. Renderer B stops the
> kerb and pavement at the trim and turns the corner with a radius. Junctions are **data** — 1,642
> `_junction` records already in `data/thanet/out/networks/roads_*.jsonl`, already carried into every
> site document as `junctions[]` — use them, do not invent a parallel mechanism.

- **Geometry / spline** — `Tools/blender/streetscape/{spline,schema,road,edge,hedge,mesh,build,
  terrain,conform}.py`, `tests/synthetic.py`, `tests/test_conform.py`, `Tools/conform_landscape.py`,
  `Tools/road_fusion_audit.py`, `schema/streetscape.schema.json`. A `JunctionPlan` resolves the trim
  once per site; `Spline` takes `trim=(t_start, t_end)` as a **mask on `s`**, not a re-basing (so every
  segment list and every `s`-ranged override keeps its meaning), and both trim stations are added to
  the mandatory station set so they exist exactly in every renderer's list. `resolve_widths` became
  the one definition of half-width that `Spline` and `JunctionPlan` both call.
- **Clearance / adapter** — `sources/adapters/unreal.py` gained `derived_products()`, so
  `unreal_manifest.json` finally indexes `landscape_conformed`: what wrote it, when, at which commit,
  how many cells it changed, and that its heights inside the corridor are the road and not the survey.
  An absent directory yields `present: false` rather than no entry, so "not built yet" and "not known
  about" cannot be confused.
- **Integrity** (this file's author) — `sources/tests/regress_outputs.sh`, `sources/OUTPUT.md`,
  `README.md`, `Tools/ue/run_ue_python.ps1`, `docs/STAGES.md`, `docs/RESUME.md`. See §5 and §6.

**Both of the other two were still mid-flight when this was written.** `git status --short` and
`git diff --stat` first, then run the suites in §2 before believing any of it.

## 4. The defects, and where each one stands

`docs/TERRAIN_ROADS.md` is the measured analysis; `renders/b1cd3e5/INDEX.md` is what it looks like.

**D1 — tile-boundary seams. FIXED** (`b1cd3e5`). Step 05 no longer nearest-fills open sea and no
longer fills per tile; the fill is decided once over the site mosaic, and `terrain_manifest.json`
gained a `shared_edges` block that step 05 exits non-zero on. Thanet: 737 pairs, **0 of 378,081**
shared samples disagreeing, worst 0.0 m (was 29,188 cells and 5.34 m). Margate: 162 pairs, 0 of
83,106.

**D2 — "two terrain truths" was a misdiagnosis.** The heightfield and the ALandscape are the same
data, agreeing at every grid post to 0.53 mm; they differ only between posts, bilinear versus the
landscape's triangle pairs, bounded by `|twist|/4` (max 6.12 m over the site, 0.026 % of quads over
0.5 m). `Streetscape.Terrain.Triangulated` exists and passes. **The §3.5 recommendation was NOT
carried out** and this is easy to assume otherwise: `StreetTerrainSource.h:53` and `:138` still
default to `EStreetHeightSampling::Bilinear`, and `Tools/blender/streetscape/terrain.py`'s
`Heightfield.sample` is still bilinear only — so the conform was burned against the bilinear rule
while the ground the player sees and collides with is triangulated. Checked 2026-09-09; it is a
coordinated change (`DESIGN.md` §8 specifies bilinear and the frozen fixtures move with it).

**D3 — roads fusing with the ground. FIXED in the data** (`b1cd3e5`). The corridor conform burns the
road's own built surface into a copy of the landscape. Whole isle, 13,097 splines, 666,314 stations:
stations with ground above the built surface **565,545 → 0**, carriageway penetrated **826.7 km →
0.000 km**, worst penetration **13.826 m → 0.000000 m**.

**D3b — and yet the road is not in the picture. OPEN, and it is now the headline.** Measured over the
45-frame set at `b1cd3e5`: of the 31 frames that stand on or look along a road, **the carriageway is
drawn in 15 and missing in 16**. It is not the geometry — a downward trace at those same cameras hits
the street 2.7–6.0 cm above the landscape, and hiding the `LandscapeProxy` actors brings the whole
street back (`Tools/ue/diag_road_visibility.py`, `Saved/RoadVisibility/`). **The surface the landscape
rasterises is not the surface its own height query returns**, and the drawn ground wins wherever a
1 m quad holds more than the conform's 3 cm sink. Pinning LOD 0 removes it in a capture
(`05_screenshot.py --landscape-lod0-screen-size`) but not at runtime. Deepening the sink is not free:
the kerb tuck is 0.03 m, so a deeper sink shows daylight under the kerb.

**D4 — dishonest gates. FIXED** (`b1cd3e5` for the import gates, this round for the two below).

**D5 — the network is in the level.** 15,423 streetscape actors, 216 massing actors, 140 proxies,
`PlayerStart`, game mode and pawn set, `problems: []` (`Saved/Tests/d5_assert_final.json`).

## 5. The two integrity defects closed this round

**The Margate gate could not pass under any snapshot on disk.** A gate that compares one hash per
file dies the first time a manifest gains a key or `generator` records a new commit sha, and it had.
`regress_outputs.sh` now compares rasters and record files **byte for byte with no allowance of any
kind**, and JSON products **structurally**: `PROVENANCE` when only the `generator` string differs,
`EXTENDED` when the only difference is a key named in the script's `ALLOW_ADDED` table, `CHANGED`
otherwise. Both allowances are proved by re-serialising the reduced file and hashing it against the
snapshot, so one changed digit still fails. What actually changed is in `docs/STAGES.md` note (a),
with the byte counts. `selftest` breaks twelve things on purpose and requires the exact verdict for
each.

**The headless runner was reporting crashes as successes — read this before trusting any THANET_OK.**
`Tools/ue/run_ue_python.ps1` used to attribute *every* non-zero exit to this machine's VC++
redistributable advisory. There are two causes, not one, and they were measured on 2026-09-09:

| what the run did | raw exit | why |
|---|---|---|
| `ue_common.py`, with and without `-Render` | **1** | the VC++ advisory, counted as an error by the commandlet framework |
| `04_probe.py --points … ` (no `--landscape`, `regions_loaded 0`) | **1** | the same |
| `04_probe.py --points … --landscape` (`regions_loaded 1`) | **0xC0000005** | access violation at teardown |
| `07_assert_level.py --census-only` (streams the whole world) | **0xC0000005** | the same |
| all nine `render_set.ps1` batches at `b1cd3e5` | **0xC0000005** | the same (`renders/b1cd3e5/manifest.json`) |

**It fires when, and only when, the run streamed in a World Partition region, and it fires after
everything is finished.** In every measured case the Python script printed `THANET_OK`, the output
files were written (`Saved/probe/census.json`, all 45 images and their reports), and the log ran all
the way through the Warning/Error Summary to `LogExit: Exiting.` and `Log file closed` with no crash
marker anywhere. **No output is lost.** There is also **no callstack**: UE writes no
`Saved/Crashes/` entry and Windows writes no dump, because the fault is after the crash handler has
been torn down. Getting a stack would mean attaching a debugger (procdump/windbg, neither installed)
to the commandlet — that is the next step if it ever starts costing work rather than exit codes.

The runner now names the NTSTATUS, waives the teardown crash **only** against positive proof that the
work finished (Python succeeded, ≥1 `THANET_OK`, no `THANET_FAIL`, no crash marker, clean shutdown),
prints a banner when it does, writes a `VERDICT` line and a row in
`Saved/Logs/run_ue_python_verdicts.tsv`, refuses the waiver under `-StrictExit`, and fails loudly with
a 40-line log excerpt for anything else. Verified on four cases: advisory → 0, teardown crash → 0 with
the banner, teardown crash `-StrictExit` → non-zero, deliberate Python failure → non-zero.

## 6. Rules that cost previous sessions hours

- **PATH must use the `/c/` form**: `export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"`.
  A `C:/...` entry is invisible to bash — GDAL disappears and numpy's LAPACK dies silently with no
  output at all.
- **Python is only** `C:/Users/Shadow/code/3duk-env/env/python.exe`. The `python`/`python3` on PATH
  are broken Microsoft Store stubs. `regress_outputs.sh` needs one too — `export PY=` it.
- **`run_ue_python.ps1` exit 0 is not proof.** Read the `VERDICT` line it prints and confirm the
  output files exist. §5 says why.
- **UE 5.8 prints `Test Completed. Result={Success}`**, not `{Passed}`.
- **Close the GUI editor before headless work.** Both processes fight over asset locks in `Content/`.
- **Never launch the GUI from an agent**; it blocks on a modal dialog with no one to click it.
- **`--max-components 256` on the landscape import.** With `0` the importer tries all 2,067 components
  in one `Import` call and the D3D12 device dies with `E_OUTOFMEMORY` after ~12 minutes.
- **Blender headless renders with EEVEE only** in `-b` mode on this machine, and its scripts must sit
  on a short path — the session scratchpad path is 270 characters and Blender cannot open files there.
- **Long jobs must run in the background with a log.** The Bash tool caps at 600 s; a landscape import
  is ~6 min, the conform ~13.5 min, the 45-frame render set ~19 min, the first editor start several
  minutes.
- **Never `git commit/stash/checkout/reset` from an agent** — the orchestrator commits between phases.

## 7. If you are starting completely cold

```bash
cd /c/Users/Shadow/code/3duk && git log --oneline -6 && git status --short && git diff --stat
```

Then read, in order: this file, `docs/BRIEF.md` sections 1.1, 4 and 7, `docs/TERRAIN_ROADS.md`
sections 1 and 8, `renders/b1cd3e5/INDEX.md`, and `docs/STAGES.md` §0 for what each stage's acceptance
command is and what was last seen to pass. Confirm the tree is still green before changing anything:

```bash
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
export PY=C:/Users/Shadow/code/3duk-env/env/python.exe
$PY sources/tests/dryrun.py | tail -1                               # 167 passed, 0 failed
$PY sources/tests/test_unreal_adapter.py 2>&1 | tail -1             # OK
$PY -m unittest discover -s projects/one/Tools/blender/tests -p "test_*.py" 2>&1 | tail -1
./sources/tests/regress_outputs.sh compare margate terrain_fix_before | tail -1
./sources/tests/regress_outputs.sh selftest margate | tail -1
powershell -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/build.ps1 | tail -3
powershell -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_tests.ps1 | tail -5
```

To look at the world rather than rebuild it, open the editor on the saved level — but only when no
headless job is running:

```bash
"/c/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" "C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject"
```

## 8. Uncommitted work

Agents write into the working tree and the orchestrator commits between phases, so after a crash
there will usually be uncommitted changes from the agents that were mid-flight. They are not
necessarily broken — check them, build, run the tests, and commit what passes rather than discarding
it. `git status --short` and `git diff --stat` are the first two commands after any disconnect.

At the moment this file was written the tree held, uncommitted: the geometry track's junction trim
(`Tools/blender/streetscape/**`, `schema/streetscape.schema.json`, `Tools/conform_landscape.py`,
`Tools/road_fusion_audit.py`), the adapter's `derived_products` block
(`sources/adapters/unreal.py`), this round's integrity work (`sources/tests/regress_outputs.sh`,
`sources/OUTPUT.md`, `README.md`, `projects/one/Tools/ue/run_ue_python.ps1`, `docs/STAGES.md`, this
file), an unrelated edit to `sources/fetch/photos.py`, and `sources/config/thanet_towns.json`
untracked. The trim work changes the geometry the conform is burned from, so
**`Tools/conform_landscape.py` and `Tools/road_fusion_audit.py` have to be re-run and the landscape
re-imported before the level matches the splines again** — a `conform_v2` run was in progress.
