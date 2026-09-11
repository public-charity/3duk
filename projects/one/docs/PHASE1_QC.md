# Phase 1 completion and quality control

Started 2026-09-10 from `e67b876` on `thanet-explorer` for Alex's request to finish a
Thanet base suitable for high-quality building overlays. Survey registration, terrain,
roads, rail, junctions and their transitions belong to Phase 1. Hero buildings and
decorative presentation remain later work.

## Exact terrain-edge constraints — 2026-09-11

A sampled terrain candidate passed its 25 cm edge checks but failed an independent
exact check: 8.225 mm gap versus a 7.8125 mm limit. Keep that candidate rejected.
Split every actual emitted edge at terrain grid/diagonal crossings and region
boundaries; include roots where protected or positive gap limits change slope.
This gives complete extrema for straight edges over LOD-0 piecewise planar ground.
Regression tests cover a missed diagonal extremum, reversed/negative coordinates,
clamped-gap extrema, protected roots, missing ground and registration rejection.
The revised Wings Close solve uses 16 posts, clears 101 mm penetration, and passes
an independent exact edge check with max required gap 6.91 mm. 106 workflow tests
pass. Native visual/terrain/rollback proof is the next separate gate.

## Explicit connector pilot and complete native runs — 2026-09-11

Four local joins reproduce private full-document geometry through a shared explicit
connector kind, with native parity on 170 arrays. Every untouched body, old junction
and remote-end section is exact; local meshes were visually inspected. Native
preview additions are restricted to existing unused reciprocal continuation ends.
170 NumPy, 99 tool and 48 native tests pass. Checkpoint 33 then proves a complete
58-actor loaded-world preview/export/restore with all 15,938 Content files exact.
The actual images fail the visual gate: terrain breaks through the new outer
road bend. Transaction success and full texture residency cannot certify road/
terrain contact. Quantify that local defect before expanding the pilot.

An interrupted native test exposed a launcher false success. Require agreement
between discovered, started and completed test counts, reject fatal logs and
unexpected engine exits. Replaying the actual gate on complete, crashed and silently
truncated logs proves all three outcomes. A passing subset is never full coverage.

A private shifted-fan diagnosis exposes another weak metric: self-crossing boundaries
can have zero signed-area excess. Future filling experiments must prove boundary
simplicity and actual triangle overlap as well as local winding and seams.

## Complete control cleanup and exact reuse — 2026-09-11

All 988 eligible ordinary roads tested; 538 repairs retained across 168 documents.
Full coverage proves 11,164 passing bodies, 1,933 folds and 2,325 non-road definitions;
all 1,642 junction metrics unchanged. Zero body regressions and no increased actual
road-edge/kerb/pavement gap across 308 affected continuation pairs. Conservative
centreline deviation <=49.879 mm; length change <=9.752 mm. Every original endpoint
and retained point dictionary preserved. All 246 candidate files reconstruct
byte-exact from checkpoint 30's committed selection manifest.

Reuse geometry only when its complete inputs are exact: shared profiles, terrain,
core, definitions, junction bindings and bound-arm geometry. Eight independently
rebuilt documents compare exactly with full builds; 88 already completed full
builds were retained and the remaining 72 edited documents rebuilt every changed
body. Hash every reused report and freeze the prior state. Report fresh and reused
coverage separately. This avoids minutes rebuilding untouched streets.

Reject speculative approaches on an early adversarial sample: refreshed global
continuation curves regress all first five pairs and are stopped. Four private
two-arm local joins pass finished mesh seams, but full-document, topology, terrain
and native proofs remain necessary. Neither result implies Phase 1 acceptance.

## Bounded road-control repairs — 2026-09-11

A complete candidate repairs 38 folded road bodies by removing redundant interior
controls within0.1m. Endpoints, retained point dictionaries and all other document
data remain exact. Every retained road now passes, with a conservative centreline
deviation bound <=50mm and length change <=50mm. Actual road-edge, kerb and pavement
continuation sections cannot worsen. Junction arms, structures, steps, loops,
height/roll pins and distinct point semantics are protected.

Independent full-document checks verify all38 repairs: 10,664 passing bodies,
2,433 folds, 2,325 non-road definitions; all1,642 junction metrics unchanged,
zero body/continuation regressions. Thirty-three unique continuation pairs checked.
Largest curve bound47.272mm, length change9.752mm. The three largest mesh repairs
were visually inspected. All246 documents reconstruct byte-exact from the committed
checkpoint29 selection; 99 tool tests pass. Whole-network search continues in
16-road calls, checkpointed per attempt; the first optimized batch took13.140s.
Terrain, structures, other overlaps, existing continuation gaps and native world
acceptance remain open. This is a geometry milestone, not Phase1 acceptance.

## Opening-section winding and full body coverage — 2026-09-11

The shared sweep now uses the nonzero end section to orient a triangle when the
starting section has zero width. Regression tests prove the old code fails; new
opening/closing, side and bank cases pass. Build, 166 NumPy, 93 tool and 46 native
tests pass. 102 actual mesh/station arrays agree; all face indices exact, max
coordinate difference 5.68434e-14 m. Fresh censuses add 28 junction passes to both
original and candidate, preserving exact curve, mapping-fold and patch-overlap
metrics for all 3,284 paired records. No regressions. Candidate: 1,182 pass,
327 fold, 130 overlap, three build failures. Data-only improvement remains 509.

The changed-body gate does not cover inherited defects in untouched roads. A new
full census measures all road/pavement and ballast/rail ribbons and explicitly
counts non-road definitions. The completed 246-document census records 10,626
passes, 2,471 folded bodies and 2,325 non-road definitions, with no missing IDs
or body build failures. All 1,487 earlier changed-body measurements reproduce
exactly; all 1,052 partition dependencies and report hashes verify. Of the folds,
254 affect pavement alone, 790 both road and pavement, and 1,427 road or rail.
Median area is 0.19177 m2; 1,082 lie near active ends. These inherited defects
remain explicit work. Separate centimetre-scale source-control noise from genuine
sharp bends; every candidate must pass body, junction, continuation and geometric
deviation checks together. No terrain or whole-site acceptance can follow from
the earlier changed-body comparison alone. Checkpoint28 preserves this baseline.

## Ordinary-road overlap checkpoint — 2026-09-11

The bounded 80-junction search retains 38 proposals, bringing the complete candidate
to 1,154 passing junctions (509 more than original). Every proposal survives the
combined original comparison: zero junction/body regressions, all 1,487 changed
bodies checked. 23 fresh documents +223 hash-verified report reuses take 32.754 s.
All 423 actual junction patches in the changed documents have zero patch gaps and
corner seam error below 7e-12 m. The three largest combined trim requests were
visually inspected. The committed checkpoint-26 selection reconstructs all 246
documents byte for byte in eight bounded batches. This remains a geometry candidate.

Remaining geometry needs a different fix: a private prototype corrects triangle
winding where pavement opens from zero width, fixing seven junctions across four
complete documents without moving vertices or changing mapping-fold/overlap areas.
The starting section has no normal hint; use the nonzero end section. Port to both
cores with an opening/closing regression fixture and parity before accepting it.
The 488 unresolved junctions and unmeasured unchanged road bodies remain explicit,
along with continuation seams, terrain, structures and world acceptance.

## Per-arm trim checkpoint — 2026-09-11

The serialized search pilot retains 3/8 proposals: three of four overlap cases,
zero of four fold-status cases. This directs the next bounded search toward the
80 unsearched ordinary-road overlap cases. The retained candidate reaches 1,116
passes (471 more than original), with zero junction or body regressions across
1,411 changed bodies. Three freshly audited documents and 243 exact report reuses
take 10.054 s. All 62 junction meshes in those three documents have zero patch
gaps and corner seam error below 6e-12 m; the actual mesh diagram was inspected.
90 tool tests pass, including a planted body regression that blocks a junction
improvement. A completed real search resumes without repeating its evaluations.
Checkpoint 25 exactly reconstructs all 246 documents from raw data in eight batches.

Six optional end trim requests resolve two more junctions while preserving shared
A/B/C stations. The fresh whole-site result is 1,113 passing junctions, 468 more
than original, with no local junction or road-body regressions. All 1,404 changed
bodies are checked. The 529 unresolved junctions, continuation seams, terrain and
structures remain explicit failures or open work; this is not Phase 1 acceptance.

164 NumPy, 87 tool and 46 native tests pass; native build succeeds and raw engine
exit is zero. 51 actual native/Python mesh and station arrays match to floating-point
precision. All 17 junction meshes in the two edited documents have zero patch gaps
and corner seam error below 4e-12 m. Complete-document preservation and half-arm
bounds are independently verified. The committed checkpoint-24 manifest exactly
reconstructs all 246 candidate documents from raw sources in bounded batches.

Next searches operate serialized per-end fields with a 10–20 s junction budget.
Only full target passes may be retained, subject to affected-neighbour and actual
road-body checks plus an independent full-document audit. Shrink feasible radii
under the same gates. Record each attempt atomically; partial improvements remain
diagnostic, and final composition must also pass the original-base comparison.

## Pavement mapping diagnosis — 2026-09-11

**Verified retained selection:** 168 complete width groups (213 splines) and 420
trims preserve all 246 documents and improve original junction passes from 645 to
1,111. All 466 new passes survive comparison with the original base, with no lost
passes or increased junction/body defects. Every one of 1,399 changed road bodies
is checked. The final five-document correction takes 12.413 s; 241 unchanged
documents reuse reports only after exact input/document/report hash checks.

The committed selection manifest and `restore_geometry_selection.py` reproduce
all 246 candidate files byte for byte from raw input in 32-document batches.
Corruption and interruption recovery are tested; all 86 tool tests pass. This is
a recoverable geometry candidate, not a production rollout. 361 folds, 167 overlaps
and three unbuildable corners remain, along with terrain/seam/structure acceptance.
See `docs/checkpoints/phase1_23_geometry_selection.json` and current RESUME.

**Whole-site search and body check:** 437 bounded trims across 132 documents
produce 1,140 passing junctions, with zero junction regressions against the width
input. The original-base comparison still finds 21 inherited width regressions.
Independent preservation accounts for all 246 documents, 15,422 definitions,
1,642 junctions and 1,054 source/dependency hashes. No production rollout.

The new actual-body screen checks every changed road and pavement ribbon, including
shared-plan trim effects. Winding-independent signed mapping includes tops below
reference height and excludes vertical backs. All 84 tool tests pass. Full comparison
finds 14 body regressions among 1,226 trim-affected splines, and 16 among 1,507
combined changes relative to original. Two newly folded bodies came from trims;
even the small existing-fold increases remain failures. Filter the affected trims
and whole width groups, then recheck neighbours and original geometry. A junction
pass is insufficient to accept the adjoining street.

A continuation-control prototype closes large endpoint gaps, with all 43 equal-width
sample joins within 5 mm after a private bank projection. However, it increases
folding on 47/96 tested road bodies. Reject blanket adoption. Seam, body, junction,
terrain and structure gates must agree before porting or promoting a geometry change.

**Bounded trim search:** actual A/B meshes drive <=30 trials per junction, with
unchanged plan curves/arm geometry cached. Every affected neighbouring junction
is checked; a retained proposal must exactly match a fresh full-document audit.
Short arms retain the existing half-length bound. Immutable step files and atomic
state checkpoint each junction. 80 tool tests pass. The 44-junction pilot improves
from 13 width-only passes to 26 combined passes using 13 trims, with no regression
against its input; one inherited width regression versus original geometry remains
at J15_14:22. Exact source preservation and all 807 input hashes verify. Actual-mesh
plan diagrams confirm the removed folds. Phase 1/native/terrain acceptance remains open.

**Gate implemented and verified:** 76 tool tests pass, including an actual folded
sweep and a crossroads proving folded pavement cannot reach expensive contact
sampling despite zero patch overlap and upward normals. Full baseline now records
645 passes, 757 folds, 236 overlaps and four curve failures across all 1,642
junctions. The retained width candidate records 703 passes, 764 folds, 172 overlaps
and three curve failures: 59 new passes but 27 regressions. These supersede the
older normal-only census. Evaluate widths and bounded trims jointly before rollout.

The sweep builder corrects each triangle's winding toward the exposed surface.
An upward-facing mesh can therefore still fold back over itself. A new independent
diagnosis compares signed world XY area with signed (station, offset) area; this
detects reversed mapping despite the winding correction. Four documents contain
42 affected junctions, including previous geometry passes. A pavement-aware trim
prototype reduces these to 23; no renderer change has been accepted. Next prove
this stronger gate on an actual folded sweep and add it to geometry/contact QC.
Earlier normal-only census pass counts are insufficient for acceptance.

The retained width selection is now 210 groups / 261 splines, with 16 whole groups
held after two full comparisons. All 246 candidate documents preserve the complete
source apart from intended width fields. Regenerate both baseline and candidate
censuses under the stronger gate before promotion. See current RESUME checkpoint.

## Whole-network width candidate — 2026-09-11

A checkpointed full-document candidate applies 226 connected lane-width groups
(278 splines across 49 documents); 63 groups need more context. Independent
verification accounts for all 246 documents and 15,422 source spline definitions,
preserving IDs, centrelines, junctions, continuations and every non-width field.
73 tool tests pass. Geometry census retains all 1,642 junctions: 1,289 pass,
106 fold reviews, 243 overlap reviews and four curve failures.

The candidate earns 75 new geometry passes but causes 11 regressions, including
one new unbuildable curve and one indirect junction effect. This unfiltered
candidate must not be promoted. Hold affected connected groups and recheck the
whole network; totals alone cannot excuse local regression. Detailed comparison
and preservation evidence are in `connected_width_candidates/144f23ef8518eb1e0350`.

## Geometry-first contact gate — 2026-09-11

Check surface geometry before spending time on terrain. Junction overlaps,
inverted pavement, missing arms, incompatible sections and unresolved curves
now remain explicit `needs_geometry` results. They cannot gain a terrain pass
or disappear from coverage. On the 51-junction pilot, contact work fell from
112.763 s elapsed to 17.852 s; all 40 measured reports remained exactly equal.
The result is 39 terrain passes, one failure and 11 geometry failures, rather
than giving misleading terrain-only passes to bad meshes. 72 tool tests pass.
A spatial-index experiment was rejected after it proved slower on this case.

The four unbuildable curves all involve short fragments: a 2.399 m connector
between roundabout junctions, a 2.999 m road ending at a tile boundary, a 2.035 m
stair fragment, and a 0.747 m path. Three have explicit longer continuations.
Plan connected paths before imposing per-document trim limits; use a connected
junction model for the tiny roundabout connector and a landing/structure model
for the stairs. Preserve the existing curve quality limits and registration.

## Connected road-width checkpoint — 2026-09-11

Explicit one-lane roundabout pieces were 10 m wide from road-class defaults.
A complete-document candidate infers 4/7 m widths from existing lane tuning,
preserves centrelines, and changes reciprocal continuation pieces together.
One bounded 8 m trim removes an automatic-solver overlap. All eight local
junction boundaries are clean; whole-document geometry improves 35->40 passes,
16->11 overlap reviews, with no regression. All 19 local driving screens pass.
Terrain contact improves 49->50 passing junctions out of 51; a 55.720 mm pavement
burial and four larger road-edge gaps remain. A fast terrain repair rejects a
67.630 mm conflict with a lower overlapping service road instead of burying it.

70 tool and 45 native tests pass. The reversible native preview restores all
239 actors, 51 junctions (including the trim override) and 8,343 terrain posts
exactly; all 15,913 Content files unchanged. Both images were inspected. The
overall engine run nevertheless fails because world loading reaches two known
unbuildable junctions outside this candidate. Keep transaction proof separate
from engine/world acceptance. Candidate, images, failed solver and precise restart
state are in the seventeenth checkpoint of `RESUME.md`; Phase 1 remains open.

## Shared corner quality checkpoint — 2026-09-11

Long shallow junction corners previously had only three rings over 25–35 m.
Both geometry cores now enforce <=1 m segments, <=10 mm cubic chord error and
actual tangent turn <= the profile limit, within 4,096 segments. Signed bank
transport preserves exact end seams and removes internal downward frame flips.
An actor rebuild rejects any missing owned junction before replacing its buffers.
Verification: 160 Python geometry, 45 native and 69 tool tests pass; native
point/tangent/normal/up parity <=1e-9, worst point difference 1.819e-12 m.

The new geometry-only census includes inverted pavement tops in its coverage.
All 246 documents / 1,642 junctions completed with atomic per-document reports:
1,215 passes, 106 pavement fold reviews, 317 patch overlap reviews, four curves
unable to satisfy the bounded quality gate. This supersedes the earlier geometry
census, whose positive-normal filter could hide inverted tops. Report identity:
`Saved/Phase1/corner_quality/60fe03b94c711092b03a/state.json`.
Passing geometry alone never grants terrain/structure or Phase 1 acceptance.

The pilot has no downward frames, but 13 of its 16 overlapping patch boundaries
have proper self-intersections, including crossing road end rows. Fix the trim,
width or connected junction model before attempting triangulation. Previous local
terrain/crossing candidate fingerprints are historical after this shared-core edit;
regenerate them before native previews. Saved production geometry remains unchanged.

## Structure rollout checkpoint — 2026-09-10

**Preview correction:** the first preview implementation reused the production
replace-by-ID importer. That importer deletes saved external actor packages immediately;
not calling SaveAll did NOT make it transient. Twelve original rail actors were affected
(six Minnis, six Margate). Targeted recovery from unchanged source JSON restored twelve
new actor packages and changed/deleted no pre-existing Content file:
`Saved/Phase1/preview_recovery/restore.json`. Fresh-process verification passed:
`preview_recovery/verify_reload.json`, all 12 IDs exactly once, zero file changes.
The replacement native `PreviewElevationJson` updates only loaded elevation profiles
and never calls spawn/delete/save. Python checks actor paths as well as the ID census.
Every capture now hashes saved Content before/after, including failed captures.
Do not use the old preview helper from commits 68e32c0 or 5dc05d9.
The safe four-span Margate preview passed (115 s): actor paths retained and all
15,913 Content files byte-identical. `margate_four_bridge_preview_safe/manifest.json`.
Four selected spans and their approaches are visibly continuous; other nearby
tracks, supports and the raw cutting sides remain unresolved.

Connected approach modelling doubled the passing rail candidates from eight to sixteen
without relaxing the DSM gate. It follows tile fragments, joins short bridge connectors
with matching endpoint heights/tangents, preserves signed bank under reversal and rejects
conflicting overlapping edits. A union generation produces 50 spline definitions in 6.7 s.
The two Broadley Road crossings still have only 1.78–1.97 m nominal clearance above the
current road mesh; these remain unresolved despite positive, non-intersecting envelopes.

`Tools/diag/structure_workflow.py` screens at most four rail candidates per invocation
with per-group atomic state, bounded subprocess deadlines and immutable attempt folders.
The whole 133-group inventory remains visible; unsupported models are not dropped from
coverage. Resume results require matching source and artifact hashes. DSM VRT dependencies,
survey pixels/masks, original OSM semantics and geometry modules are now hashed too.

Current ledger `Saved/Phase1/structures/c6e5169baf705bcf9ea1/state.json`:
8 rail candidates, 16 rail approach reviews, 34 deck-fit reviews, 25 road-approach models,
50 passage/tunnel context models. The 24 rail jobs took roughly five seconds each.
Repeat invocation reuses all results in 7.4 s; 36 tool tests pass. All remain candidates.
Original tunnel tags distinguish 14 building passages, two covered passages, and nine
rail sidings requiring cover review. Do not model these all as underground tunnels.
Several bridge pairs have 9–13 m ground connectors, and tile stubs can be under a metre:
use connected alignments across those segments before claiming continuity.

## Working strategy

**2026-09-11 support/preview integration:** Renderer B can now sample a separately
configured ground source, leaving the survey-derived road vertices unchanged.
The transient-world integration test and full 42-test native suite pass. A bounded
commandlet-only landscape preview was exercised over 4,225 real posts: 497 changed,
max 109.375 mm; composed/collision queries agree within 0.059 mm, then restore
identically. Native encoded heights remain exact. All 15,913 Content files remain
byte-identical. Evidence: `terrain_preview_camera/report.json` and its two images.
Those images also reveal road/pavement overlap at New Haine Road's roundabout
approach. This is a geometry failure despite passing terrain contact. Inspect the
actual obstructing mesh and default widths, not just terrain statistics. The hedge
appearance changes between first and second capture; stabilize all rendered resources
before using pixel differences as terrain-only evidence. See RESUME.md for next steps.

**Renderer B support correction, 2026-09-11:** actual banked world edge positions
now drive support selection. Batter toes solve their intersection with terrain;
retaining walls stay vertical and explicitly support downhill road edges. Missing
or unreachable required toes fail the actor rebuild. 155 NumPy tests, 58 tool tests
and 41 native tests pass; all 20 support mesh arrays are bit-identical across the
two engines. Before rollout, supports must sample the conformed ground separately
from the survey that establishes the road spline. No support edits have been saved
to the production level. See RESUME.md for current checkpoint and integration work.

**2026-09-11 contact repair:** exact mesh/landscape triangle intersections and a
bounded integer height solver repaired three ordinary corners with eight grid-post
changes. The complete derived `Saved/Phase1/ground_contact_candidate` verifies
2,486 output files and all 246 survey-relative delta round trips. The 75 junctions
in its touched documents now have 73 passes and two existing failures. Other cuts
were rejected because they opened pavement/road edges even with protected-edge
constraints; those require geometry/support corrections. Source rasters and the
saved Unreal level are unchanged. This is a numerical candidate, awaiting a safe
terrain preview and visual acceptance. See RESUME.md for every report and restart path.

**Latest measurements supersede the older float numbers below.** Per-side coverage
now measures bare edges independently: **8.38545% / 65.961 km** floating at LOD 0,
with all 62 envelope chunks still within the penetration gate. Every floating run
is recorded for prioritized repair. Largest outliers are coastal stairs and landings.

A second gate now measures emitted junction patch/corner triangle interiors from
trimmed arms. It distinguishes actual visible penetration from lower pavement hidden
under a higher road patch; deep overlaps remain review items. The 430-junction sample
has **401 passes, 18 overlap reviews, 10 visible-geometry failures and one structure
case**. Full census complete: **1,513 passes, 85 overlap reviews, 36 failures,
8 structure cases (1,642 total)**, state `junction_mesh_qc/a087591d8ce94eb1833f/state.json`.
This closes a scope gap in the ribbon-envelope gate;
it does not turn its earlier numerical pass into whole-scene acceptance.
152 core tests and 52 tool tests pass. See RESUME.md for current state paths.

Full corrected ground census passed **62/62** chunks: 12,945 measured splines,
660,835 stations, 961.532 km, max LOD-0 penetration 0.8005 mm. 151 structures and
one named no-terrain stub remain explicitly excluded. Floating measures 8.0557%
of stations / 63.245 km, worst 12.292 m. A code review found that the float audit
can miss a bare side when the opposite side has a kerb; correct that before using
this percentage as a complete acceptance measure.

Broadley road inference now corrects the DTM's false rise onto the rail deck using
nearby road-height anchors, with longer bank blends. All tested visible approach
points agree with DTM; the occluded floor is named as inferred. Nominal rail-base
clearance improves to 3.410/3.557 m. Candidate full document and 49-test evidence
are recorded in RESUME.md. Terrain import, actual soffits, support geometry, widths
and visual checks remain open; positive envelope clearance alone is insufficient.

Corrected triangulated terrain candidate completed all 246 documents / 391 tiles.
Its 48-document sample now passes all 12 chunks with zero LOD-0 penetration across
133,265 stations (old baseline: two failed chunks, max 23.116 mm). Floating remains
11.6287%, max 4.480 m, and coarser terrain LODs still intersect roads; these remain
open acceptance items. Full resumable census is in
`ground_candidate_qc/full/23e0541a1dd5b0a8a66e/state.json`.

Junction editing/export now has an explicit whole-document path: preserve the full
source junction list, replace definitions with complete current loaded actor state,
preflight the shared solve, then refresh trims and owner copies together. Missing actors,
duplicate IDs, profile conflicts and disappearing previously buildable junctions fail.
Two new native tests pass; a real six-actor document edit/export/restore also passed,
with original JSON/patch statistics restored and all 15,913 Content files unchanged.
Evidence: `document_roundtrip/report.json`; workflow in `Tools/ue/README.md`.

Terrain conform now supports sparse atomic checkpoints and bounded document runs:
`conform_landscape.py --checkpoint-dir <dir> --max-docs 4`. Interrupted work loses
at most the current small chunk. Cache identity covers source pixels, documents,
parameters and geometry code. Pending runs do not emit products. A two-document
resume proof matches all 398 heightmap/delta rasters byte-for-byte against an
uninterrupted run; 46 tool tests pass. The corrected full candidate is being written
separately under `Saved/Phase1/ground_conformed_triangulated/`.

1. Inspect current source and saved evidence before accepting historical status.
2. Inventory **every** road/rail way, junction and bridge/tunnel. Keep measured,
   excluded, unsupported and failed counts separate. An empty selection is failure.
3. Iterate on fixed difficult locations: Minnis Road cutting/rail bridge, St Peter's
   crossing, North Foreland road edges, Haine Road, a normal urban junction, rural
   bare roads and the clip boundary. Include neighbouring documents where geometry
   crosses the sample boundary. A subset pass is never whole-site acceptance.
4. Run fast numerical checks first, with input/content fingerprints and small-batch
   results written atomically. Resume only results with matching inputs and intact
   outputs. Record a running job before launch; interrupted jobs are rerun.
5. Prove new gates reject deliberate defects: empty coverage, missing results,
   stale/tampered output and threshold failures. Passing unit tests alone cannot
   establish that an imported scene is correct.
6. Inspect fixed street-level and elevated renders at shipped landscape settings.
   Preserve the original 45 cameras; append junction cameras. Review foreground
   clearance, bare edges, junction continuity, structures and building-ground seams.
7. After a candidate passes the sample, run the full inventory in bounded chunks,
   verify parity and survey/regression contracts, then import and inspect. Keep the
   last usable generated product until the candidate is verified. Record exactly
   which data revision the level contains.

## Acceptance ledger

The subsequent bounded terrain finish raises 19 encoded posts by <=102 mm,
reducing the corrected approach's max outer-base gap to 15.5 mm. Exact upper-surface
clearance, preserved neighbour contact, whole-window max-gap comparison, independent
391-map survey reconstruction, and the guarded native document/terrain restoration
all pass. Two existing pavement corners remain buried and visibly malformed. Their
25 m and 35 m curves have only three sample rings: improve shared curve quality
before treating a terrain-only repair as sufficient. Restart details: milestone 15
at the top of `RESUME.md`. No candidate has replaced the saved production level.

Latest bounded pilot (2026-09-11): exact triangle crossing fit removes a 76 mm
footway obstruction and corrects two explicitly lane-tagged approach widths using
existing tuning. Full document + terrain preview restores exactly; all 15,913 saved
Content files unchanged, 43 native / 62 tool tests passed. **Candidate rejected for
acceptance:** a neighbouring bare road edge gap increases 48 -> 164 mm, and two
existing pavement corners remain buried. Complete contact/visual evidence and
restart paths are in the fourteenth milestone at the top of `RESUME.md`.

| Area | Current status | Evidence required to close |
|---|---|---|
| Survey/registration | Historical pass; preserve | Untouched survey hashes, shared tile edges, existing engine probes |
| Overlay | Default/toggle fixed | World-batcher lifecycle passes in engine; two default-off frames inspected; explicit visual occlusion with debug enabled still to check |
| Ground roads/cuttings | Open | No unexpected penetration at LOD 0; rendered LOD and bare-edge cases reviewed; floating runs resolved or explicitly classified |
| Bridges/tunnels | Open | Full census, continuous endpoints, plausible grades and crossing clearance; modelled heights labelled |
| Junctions | Partly implemented | Patch conform already wired; verify remaining structure-arm cases, crossing paths, live edits and JSON round trip |
| Building overlay readiness | Open | Retained survey frame/ground references; stable massing-to-ground relationship and replaceable placeholders |
| Imported level | Historical pass | Fresh artifact identity, actor census, numerical probes and fixed renders after accepted changes |
| Restart safety | QC implemented | Atomic state, input/output hashes, actual resumption and 13 failure tests pass; terrain conform/import still need bounded restart support |

Existing floating/LOD fractions are **regression ceilings**, not a definition of a
finished road network. Bridge exclusions cannot contribute to a completion pass.

## Corrections to historical handover

- `conform_landscape.py` already calls `C.junction_targets`; its default includes
  junctions. `--no-junctions` exists for A/B diagnosis. Do not implement it twice.
- `StreetOverlayComponent.cpp` already uses `SDPG_World`; inspect thick-line behaviour
  and toggle lifecycle rather than assuming it uses foreground depth priority.
- `road_fusion_audit.py` has `--n 0` for all splines, not the handover's `--all`.
- `RESUME.md`'s previous contents describe September 9 and predate several fixes.
- Millimetre engine-registration residuals do not imply millimetre accuracy of the
  underlying 1 m LIDAR or OSM. Preserve both facts in downstream provenance.

## Durable evidence

Source and operational decisions: this file and `RESUME.md` (tracked).
Machine-readable run state, individual reports and logs: `Saved/Phase1/` (local,
git-ignored, persistent across a process/VM restart when the workspace disk survives).
Commit verified source milestones; do not claim a commit backs up ignored generated
assets or protects against losing the VM disk itself.

## First measured checkpoint

`Tools/phase1_qc.py` defaults to four documents per chunk and two chunks per
invocation; the risk sample includes a one-tile halo around six fixed camera/subject
pairs. Each chunk has a unique log/report attempt, reconciled spline counts, a
300-second timeout and an atomically replaced state. Successful cached reports are
reused only with matching input roles, content hashes and report hashes. The final
input fingerprint is checked again to catch changes during the run. Windows reader
sharing conflicts retry atomic replacement without truncating the old checkpoint.

Historical **bilinear construction** baseline, 2026-09-10: 12 chunks, 48 documents, 2,868 selected splines; 2,843 measured,
24 structures excluded, one no-terrain stub. 111.34 seconds of audit time; reuse-only
run about 5 seconds. 192.737 km / 133,265 stations. No LOD-0 penetration above 5 mm;
11.638% floating stations over 125 mm; penetrated length 0.366% / 2.657% / 7.626%
at LOD 1 / 2 / 3. This remains **numerical_checks_complete**, never Phase 1 accepted.

Two new images and their manifest are at `Saved/Phase1/overlay_smoke/`. They confirm
the overlay is off and expose the still-broken Minnis Road railway bridge/cutting.
The model's geometry is unchanged in this checkpoint. C++ build and 34 automation
tests passed; numpy baseline 147, pipeline 167, adapter 47, QC 13 passed.

For a resumed session, run
`& projects/one/Tools/python.ps1 projects/one/Tools/phase1_qc.py` from the repository
root. A source change creates a new run
fingerprint; do not copy old passes into it. Full-site numerical measurement and
engine import/visual acceptance are subsequent distinct steps.

## Production sampling and structures checkpoint

The saved engine site constructs roads with triangulated survey sampling. The old
bilinear audit was not measuring that construction. Construction and measurement
sampling are now separate, explicit inputs; the corrected sample has two failed
chunks (worst penetration 13.644 and 23.116 mm). Source and generated terrain have
not been altered to hide these failures. A one-document candidate conform takes
14.9 seconds, allowing cheap experiments before any full product replacement.
Subset outputs carry scope/document hashes and refuse the default production path.

The all-site structure inventory contains 151 segments in 133 connected groups,
including five crossing documents. DSM first returns provide a stronger bridge
deck reference than DTM endpoint chords: at Minnis both the deck interior and some
endpoints were lost in the DTM. Robust first-return fits yield 49 bridge candidates,
34 bridge reviews and 50 tunnels needing another model. Candidates remain unaccepted
until approach continuity, bank, crossing clearance and fixed-camera inspection pass.

The engine parity test now fails for absent references, cases or arrays instead of
silently skipping them. Fresh seven-case data includes non-planar terrain under
both sampling rules; all 34 engine tests pass, and an empty reference deliberately
fails. Nineteen tool tests pass. This is stronger evidence than a historical test
count that included a skipped parity case.

Minnis foreground breakthrough persisted even with forced component LOD 0. Actual
triangle sampling and engine probes agreed. A landscape-hidden comparison isolated
the covering mesh; requesting full heightmap residency then removed the patches.
The capture was using incomplete asynchronous texture resources. Shader readiness
and component LOD settings alone were insufficient evidence of terrain readiness.

All standard captures now complete heightmap compilation and residency, validate
resident mip counts, and retain that evidence per image. Diagnostic before/after
frames are in `Saved/Phase1/minnis_residency/`; normal corrected frames are in
`Saved/Phase1/capture_ready/`. This fixes misleading capture geometry, not the
remaining bridge/approach, terrain-wall or floating-edge defects. Twenty-six tool
tests pass, including triangle-interior and texture-readiness failure proofs.

## First structural geometry candidate

Two Minnis railway spans and four 40 m approaches now use an explicit shared
elevation/bank profile. The same profile is read, built and written by NumPy and
Unreal; all new parity arrays are bit-identical. Geometry regression is 151 NumPy
tests and 35 Unreal tests. Candidate generation takes 2.1 seconds. The p95 DSM
residual on adjusted approaches is 3.5–7.2 cm, with maximum approach grade 1.381%.

The fixed-camera preview has continuous rail above the road. Sampled nominal
ballast-base clearance is at least 4.633 m. The saved level is unchanged: delta
previews verify document hashes and actor census, record engine stats, and do not
save. Support geometry, other structures and full-site acceptance remain open.
