# Phase 1 completion and quality control

Started 2026-09-10 from `e67b876` on `thanet-explorer` for Alex's request to finish a
Thanet base suitable for high-quality building overlays. Survey registration, terrain,
roads, rail, junctions and their transitions belong to Phase 1. Hero buildings and
decorative presentation remain later work.

## Working strategy

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

Minnis foreground breakthrough persists with finer terrain LOD settings. Inspect
actual triangle interiors and engine probes next; passing station samples cannot
establish clearance across the whole rendered surface.
