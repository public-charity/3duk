# Handover — taking this project to the finishing line

**Active Phase 1 work, 2026-09-10:** start with [RESUME.md](RESUME.md) for the latest
verified checkpoint and [PHASE1_QC.md](PHASE1_QC.md) for the replacement QC strategy.
Several diagnoses below are historical: junction conform was already wired, the
production road sampler is triangulated, and incomplete heightmap residency caused
false foreground breakthrough in headless captures. A tested shared elevation
profile and a continuous Minnis bridge/approach candidate now exist. The pilot is
not whole-site acceptance; the saved production level is still unchanged.

Written 2026-09-10 for an incoming assistant with **no prior context**, at Alex's request. If you
are that assistant: read this file end to end before running anything. It is long because the
expensive failures in this project have all been failures of context, not of capability.

`docs/RESUME.md` is the short operational handover, kept current after every disconnect. This file
is the strategic one: what the project is, why it is built the way it is, what is actually done,
what remains, and the traps that have each cost a working session.

---

## 1. What this is, in one page

**The deliverable.** An explorable digital-twin base of the Isle of Thanet in Kent — Margate,
Cliftonville, Broadstairs, Ramsgate, Birchington, Westgate, Westwood, Manston, Acol — built in
Unreal Engine 5.8 from public data, at real-world scale and real-world position, accurate to
millimetres. It is a *base*: the ground, the road network, building masses and the tooling to grow
them, not a finished game level.

**The data.** Environment Agency 1 m LIDAR (a terrain model and a first-return surface model) plus
OpenStreetMap, both fetched from public endpoints. Everything is held in EPSG:27700 (British
National Grid) with elevations in metres above Ordnance Datum Newlyn. Nothing is invented; where
something *is* invented (filled gaps, modelled deck heights) it is recorded as such in a manifest.

**The cut.** The isle is separated from the mainland by a hard straight line along the old Wantsum
Channel, from Minnis Bay to Pegwell Bay. Everything north-east of it exists; everything south-west
does not. This is a config value, not code: `sources/config/sites/thanet.json → clip`.

**The streetscape system.** The heart of the project, and the part with the strongest opinions
behind it. One shared spline per way is the source of truth. Three renderers read it:

- **Renderer A** — the road surface: carriageway, camber, lane markings, and (as a *profile kind*,
  not a fourth renderer) railway track. Junction surfaces are also Renderer A, because a junction
  is tarmac.
- **Renderer B** — edge extrusion: kerb, pavement, drop kerbs, walls, fences, railings, embankments.
- **Renderer C** — volumetric hedge.

Every variant — a marking pattern, a fence type, a kerb width, a half-grass kerb — is **profile
JSON and arc-length segment lists**, never a new class. That constraint came from the original
brief and it has held; there are exactly three renderer classes and twenty data profiles.

**Two implementations, one schema.** The geometry core exists in pure numpy
(`projects/one/Tools/blender/streetscape/`, ~7,600 lines) and again in C++
(`projects/one/Plugins/Streetscape/`, ~13,700 lines). They read the same JSON schema and are held
to **bit-exact parity** by frozen fixtures: `Tools/blender/tests/fixtures/expected.json` is the
contract, and `Tools/ue/compare_stats.py` diffs a real build on both sides. The numpy side is the
reference; when they disagree, the C++ side is wrong until proven otherwise.

---

## 2. Where the work actually stands

**Branch** `thanet-explorer`, not merged to `main`. Roughly 12 commits of Project One work on top of
an existing pipeline repo.

### Verified working

| | |
|---|---|
| Terrain | 391 tiles of 512 m at 1 m resolution, imported as 2,067 landscape components in 140 World Partition proxies |
| The cut | Applied as a landscape visibility hole on the exact line; no terrain survives past it |
| Buildings | 20,121 massing extrusions in 216 actors, heights from LIDAR with a per-site storey regression |
| Streets | 15,423 actors, 1,072 km of road, rail and barriers |
| Junctions | 1,642 built in the level, 0 skipped |
| Geo-registration | 880 probes over 11 km: 0.15 mm horizontal bias, 0.71 ppm scale error |
| Blender/Unreal parity | 81 compared quantities, 0 mismatches |
| Test estate | dryrun 167, numpy 147, adapter 47, Unreal automation 32, all green |
| Regression gate | Margate byte-identical, and proven to catch a planted single-bit change |

### The visual record

`renders/<commit>/<town>/<location>.png` — 45 fixed viewpoints, five in each of nine towns, cameras
frozen in a committed spec so the same shot returns every time. Three snapshots exist: `b1cd3e5`
(roads invisible), `7c8b4a6` (roads appear), `b6d3274` (junctions appear). Each has an `INDEX.md`
reading the model defect by defect and a `manifest.json` with every camera transform.

**This is the single most useful instrument in the project.** It is how the buried-road bug was
diagnosed, and how each fix was proved. Re-render after any change that could affect appearance:
`projects/one/Tools/render_set.ps1`, about 19 minutes for the set.

---

## 3. The traps — read this section twice

Every one of these cost at least one working session.

**The PATH must use the `/c/` form.** `export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"`
before *every* Python invocation. A `C:/...` entry is invisible to bash: GDAL silently disappears and
numpy's linear algebra dies with **no output at all** — an agent once concluded the environment had
no LAPACK and designed around it.

**Python is only** `C:/Users/Shadow/code/3duk-env/env/python.exe`. The `python` and `python3` on PATH
are broken Microsoft Store stubs.

**Every headless Unreal run exits 1** because of a Visual C++ redistributable advisory logged at
Error severity. `Tools/ue/run_ue_python.ps1` derives the true verdict from the log. This override was
*also* masking genuine access violations for most of the project's history; it now distinguishes
them, and `-StrictExit` refuses the waiver. **Never trust the runner's exit code alone — confirm the
work happened and the output files exist.**

**UE 5.8 prints `Test Completed. Result={Success}`**, not `{Passed}`. Anything grepping for the
latter counts zero tests and reports success.

**Close the GUI editor before headless work**, and never launch the GUI from an agent — it blocks on
a modal dialog with nobody to click it.

**Blender renders with EEVEE only** in batch mode here, and cannot open scripts on very long paths.

**The Bash tool caps at 600 s.** A landscape import is 6 minutes, a conform pass 14, a render 19.
Run them in the background with a log and poll.

**The VM drops without warning**, roughly every one to two hours, and has taken the session down six
times. Commit on every reconnect; check `git status` first. Nothing has been lost so far, but only
because of that discipline.

---

## 4. The architecture, and why

Understanding *why* matters more than the code, because these decisions are load-bearing and
reversing one by accident will break things far away.

**Survey data is sacred.** `data/<site>/out/terrain` is the raw measurement and is never written by
a consumer. Where roads need the ground reshaped, that happens in a **separate product**
(`data/thanet/out/unreal/landscape_conformed/`) with per-cell delta rasters, so the change is exactly
reversible and a manifest states in words that it is not the survey.

**The pipeline knows nothing about engines.** `sources/derive/*` emits GeoTIFF and JSONL in national
grid metres. All engine-shaped conversion lives in one adapter, `sources/adapters/unreal.py`. This is
why a Unity adapter also exists and why a second engine would be cheap.

**Three coordinate frames, converted at exactly one place each.**

| frame | definition |
|---|---|
| Survey | EPSG:27700 easting/northing, elevation ODN metres, bearings clockwise from grid north |
| Interchange JSON | local metres from the site origin: X east, Y north, Z up |
| Unreal | centimetres, left-handed: `X=100x`, `Y=−100y`, `Z=100z`, `yaw = bearing − 90` |

The site origin is E 627680, N 163080. The Unreal conversion happens only in the JSON loader and the
landscape importer. Never bake it into data.

**One spline, one trim, every renderer.** When a road meets a junction its spline end is trimmed, and
that trim is a **mask on arc length, not a re-basing**, so every segment range, marking interval,
drop kerb and barrier run keeps its meaning. Both trim stations join the mandatory station set, so
Renderer A and Renderer B see an identical extent *by construction* and cannot drift apart. This is
the single most important invariant in the geometry core.

**The road owns the seam.** The carriageway overhangs the kerb by 40 mm and the kerb tucks under, so
sampling error hides beneath the lip instead of showing as a crack. Measured at exactly 0.040 m at
every station.

**Gates must fail.** Several scripts once printed success regardless of their own findings, which is
how "junctions are done" survived a round with zero junctions in the level. Twelve gates were
hardened and each was proved by deliberately breaking something and requiring a non-zero exit. **If
you add a check, prove it can fail.**

---

## 5. What remains — the actual work, in priority order

Ordered by what I would do next. Each item states the evidence, because several plausible-sounding
"fixes" here are wrong for reasons already measured.

### P1. The debug overlay is drawn over everything

The magenta OSM reference polyline draws through buildings, through terrain and across the sky, in
all 45 frames. It was always meant to be a toggleable debug layer. It is the single biggest thing
standing between the current renders and something presentable.

*Where*: `StreetOverlayComponent` in the plugin, and the overlay build in the numpy core.
*Do*: make it depth-tested and off by default, with a console variable or an editor toggle.
*Effort*: small. *Payoff*: every image improves immediately.

### P2. Roads in cuttings and on embankments

The clearance work fixed roads on ordinary ground; it did not fix roads whose ground is very
different on the two sides. The worst standing case is
`birchington/railway_bridge_over_minnis_road` — a road in a cutting with steep sides, where no
single sink depth works. Separately, 7.7 % of stations float more than 125 mm above the ground, worst
about 13 m, concentrated at bridges, and the float gate is currently red by 0.06 points
(0.0806 against a 0.08 limit).

*Read first*: `docs/TERRAIN_ROADS.md` — the measured analysis, including why the obvious fixes were
rejected. Raising roads to clear the terrain was measured and rejected: it leaves a median 0.18 m
gap over 22 km. Cutting holes in the landscape was measured and rejected: the corridor is 7 km².
*Also note*: 36 % of built length is bare on **both** sides — footways, cycleways, tracks, service
roads, rail — where no per-side rule can help, because there is no kerb or pavement to hide a sink.
Those need a different treatment, probably a thin shoulder.

### P3. Bridges and tunnels

The pipeline's own contract says bridge elevations are *the ground under the structure*, unadjusted.
So bridges currently follow the terrain instead of spanning it, and the railway leaves the ground and
arcs into the air where OSM flags a bridge. Both flags are in the data, so this is a data-driven rule,
not a special case. Whatever deck height you choose is a **modelling choice, not survey**, and must be
recorded in the manifest as such.

### P4. Junction robustness

Junctions work, with caveats the wiring agent recorded honestly:

- The owning actor holds a **copy** of each arm taken at import, so editing an arm's spline in the
  editor rebuilds the arm but not the junction. Junctions are import-time, not live.
- About 3,500 arm definitions are duplicated onto owners, roughly 5 MB, and an owner rebuilds its
  non-owned arms a second time on every rebuild.
- `ExportSiteJson` does not write `junctions[]` back, so a level→document round trip loses them.
- The 1,642 records are **road-to-road only**. A footway crossing a carriageway with no junction
  record is still drawn straight across it — visible in `broadstairs/st_peters_high_street`.
- Ground still breaks through the middle of some junction patches: the conform burns bands along
  splines, and the wedges between arms near a node are only feathered. `road.junction_surface` and
  `junction_target_z` are the hooks that close this and `conform.py` does not call them yet.

### P5. The fixed viewpoint set has no junction camera

All 45 locations were chosen before junctions existed, so the biggest change in the model reads as a
subtle one. Add two or three cameras that look directly into crossings of different arm counts. Note
that adding a camera changes the spec hash — record why, and keep every existing camera untouched, or
the comparison across snapshots is destroyed.

### P6. Two operational sharp edges

- `02_import_landscape.py` cannot re-import over an existing landscape: it unconditionally spawns a
  new one and nothing deletes the old, so "the conform changed, re-import" costs a full rebuild.
- `00_build_level.ps1` defaults to `-AllowNoTerrain 0`, but the isle needs `1` because of a single
  18 cm road stub sitting just inside the clip line over holed-out ground.

### P7. Presentation, once the above is done

No textures anywhere; buildings are grey prisms and ground is flat colour. Shaded faces render solid
black for want of ambient light. The model ends in a hard vertical cut with no sea. Manston's runway
is field. Car park surfaces are missing. These are listed with locations in
`renders/b6d3274/INDEX.md`.

---

## 6. How to verify anything

The estate, all of which must stay green:

```bash
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
export PY=C:/Users/Shadow/code/3duk-env/env/python.exe

$PY sources/tests/dryrun.py                                   # 167 checks, pipeline, no GDAL needed
./sources/tests/regress_outputs.sh compare margate terrain_fix_before
./sources/tests/regress_outputs.sh selftest margate           # proves the gate can fail
$PY -m unittest discover -s projects/one/Tools/blender/tests -p "test_*.py"
$PY sources/tests/test_unreal_adapter.py
powershell -File projects/one/Tools/build.ps1                 # Result: Succeeded
powershell -File projects/one/Tools/ue/run_ue_tests.ps1       # 32/32
```

Road quality, measured rather than eyeballed:

```bash
$PY projects/one/Tools/road_fusion_audit.py --all --gate-m 0.005
```

And the pictures: `projects/one/Tools/render_set.ps1`, then
`$PY projects/one/Tools/compare_snapshots.py` to diff two snapshots.

**Rebuild timings**, so you can plan a session: conform 14 min, landscape import 6 min, streetscape
import 5 min, render 19 min. A full cycle is about an hour.

---

## 7. How to work on this well

**Measure before you fix.** Every serious error in this project came from acting on a plausible
story instead of a measurement. The roads were "above ground by every number the engine will give"
while being invisible on screen, because the numbers came from the landscape's *height query* and the
picture came from its *rasterised triangles* — surfaces that differ by up to half a metre inside a
single one-metre quad. `docs/TERRAIN_ROADS.md` exists because that took two rounds to find.

**Distrust green.** Three separate defects survived because something reported success it had not
earned: a gate that printed OK regardless of its probes, a runner that swallowed access violations,
and a junction layer that was complete, tested, ported — and called from nothing.

**Write down what you did not do.** The most valuable content in this repo's history is the honest
open-problems lists. One agent even recorded running a git command it had been told not to.

**Keep `RESUME.md` true.** It is the only file that claims to describe the present, and after six
disconnects it is what makes the next session cheap.

**Adversarial review pays here.** Independent auditors caught a lighthouse modelled 31 m too tall
because an OSM `height` tag on a seamark is the light's elevation and not the tower, a hand-written
override putting Margate's clock tower 9 m too high, a storey-height regression fitted over buildings
outside the model, and a false provenance claim in my own documentation.

---

## 8. What "finished" means

Alex's original brief is in `docs/BRIEF.md §1.1`, verbatim, and an auditor found 66 of roughly 72
requirements met with measured evidence and none violated. The remainder is P1 to P7 above.

For this base to be handed to a team building a real digital twin, I would want: the overlay off,
roads correct in cuttings and on bridges, junctions robust to editing, a Thanet regression gate to
match Margate's, and the documents true. Presentation — textures, lighting, sea — is a separate phase
and should not be mixed into this one.

The foundations under all of that are sound: the isle is in the right place to sub-millimetre
accuracy, the survey is intact and every derived change reversible, two independent implementations
agree exactly, and there is a fixed visual record to prove whether the next change helped.
