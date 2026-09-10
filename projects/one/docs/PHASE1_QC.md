# Phase 1 completion and quality control

Started 2026-09-10 from `e67b876` on `thanet-explorer` for Alex's request to finish a
Thanet base suitable for high-quality building overlays. Survey registration, terrain,
roads, rail, junctions and their transitions belong to Phase 1. Hero buildings and
decorative presentation remain later work.

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
