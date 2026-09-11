# Manston implementation checkpoints

Read the newest checkpoint at the end of this file for the current resume action; earlier entries record the history.

User direction, 11 September 2026: start the approved phases and save progress frequently. Restore selected historic buildings within today's landscape.

## Checkpoint 00 — research preserved; implementation started

- The research chest and museum approval report are complete. This file records implementation separately from the explorer's other ongoing road and vehicle work.
- Phase 0 is active: place evidence anchors in the existing British National Grid frame, sample terrain, check proposed routes against mapped buildings and prepare a reproducible Unreal overlay.
- Phase 1 is next: a connected, collision-bearing museum circuit, arrival and interpretation stops in the explorer. Historical shells require supported footprints; approximate anchors cannot become fabricated surveyed buildings.
- Phases 2–3 retain their evidence gates: unknown tunnel portals, depths and connectivity stay unknown. Labelled interpretation can proceed independently.
- No Unreal packages have been modified for Manston yet.

## Resume

Read this file, `MANSTON_MUSEUM_PLAN.md`, and the latest implementation manifest/report before continuing. Keep checkpoints in this directory and generated assets under a dedicated Manston package path. Stage only Manston-owned files; preserve unrelated working-tree changes. Save before and after each engine mutation.

Next: inspect terrain and engine import interfaces, produce the terrain/obstacle-checked blockout, then import and validate a scoped museum overlay.

## Checkpoint 01 — placement generator saved

- `Tools/manston/build_museum.py` uses the existing terrain sampler and Streetscape schema. It routes R1/R2 around mapped buildings, keeps both loops connected, and places 32 evidence records without filling unknown historical floor/portal values.
- The initial route candidate passes schema and geometry generation: R1 880 m / R2 3,610 m, minimum sampled centre-to-building clearance above 5.2 m. The conservative terrain routing lengthens the concept walks. Short grades still exceed the desired gentle-access target; this is a blockout, not an accessibility sign-off.
- `Tools/ue/12_manston_museum.py --inspect` successfully loaded the real map. The site's runtime spline source is the original survey while the project also has a conformed terrain product. Checking the actual landscape before import.
- Files are saved; no Manston geometry has yet been saved into the map. Next: verify rendered terrain registration, add the two routes and scoped wayfinding, then reopen and collision-check.

## Checkpoint 02 — first museum blockout saved in the explorer

- Imported into `/Game/Thanet/Maps/Thanet`: 2 museum walk actors, 8 interpretation boards, 25 benches, and 32 editor-only evidence labels (169 actor packages in total). The labels retain approximate-point status and stay hidden in the visitor view.
- Saved only museum actor packages and three dedicated museum materials. Existing museum/airport massing remains the current mapped exterior baseline.
- Both paths have explicit designed elevations, independent of the shared road terrain source. Maximum sampled longitudinal grades are 6.02% / 6.21%; maximum centre lifts above terrain are 0.236 m / 0.292 m. Edge/support and crossing detail are still required.
- Engine import completed and wrote `Saved/Manston/import_report.json`. Recovery packages: `Saved/Manston/checkpoints/20260911T210607Z/after/`.
- The runner returned a failure because loading the wider existing map also logged two unrelated road-junction rebuild errors (`roads:101767724:0`, `roads:1154393739:0`). Do not describe this as a clean whole-project pass. The museum import itself reported success; saved-world checks are running next.

Current next step: finish the reopened collision/obstacle checks and inspect the rendered arrival view. Preserve any failures in the report and fix the museum routes before calling the circuit walkable.

## Checkpoint 03 — preserved identities and clear fence crossings

- Revised R1: 768.7 m; R2: 2,694.3 m. Rounded bends keep the full walk width clear. Both retain the same gateway and close back on themselves. There are now 19 active rest stops and 8 information boards; unused older benches remain hidden, non-colliding editor-only recovery objects.
- Seven existing fence actors have 13 explicitly authored museum openings. Their original definitions are preserved in `implementation/barriers.saved_baseline.streetscape.json`; only added `manston_gate_` segment overrides alter them.
- An attempted update exposed the legacy importer's replacement/deletion behaviour. Restored all nine affected packages from the pre-update copy, then implemented `StreetDocumentPatchLibrary` to update existing independent splines in place. Its build succeeded. The missing-target negative test preserved every existing definition; positive updates preserved actor identities.
- Current saved asset checkpoint: `Saved/Manston/checkpoints/20260911T212133Z/after/`. The import's Content guard found **no changes outside the declared museum/fence package scope**.
- Reopened world: 3,837 centre/edge floor probes found no missing or buried path surface; the continuous body sweeps found no obstacles. The stricter reference-height comparison has a maximum 3.8 cm discrepancy still under investigation. The arrival sign's lettering is not yet visible in the capture, so visual acceptance is still open.
- `Tools/manston/check_checkpoint.py` passed both schemas, both closed/connected loops, all seven preserved baseline fence definitions, all 32 unknown underground geometry fields, and the complete-generation hashes. Interrupted builds are refused by the importer.

Current next step: inspect the sign/collision detail diagnostics, finish the visual check, and save the final validation report. Do not mark the museum phase complete: historical shells, detailed entrances/interiors, path supports/crossings and a full in-game walking session remain.
