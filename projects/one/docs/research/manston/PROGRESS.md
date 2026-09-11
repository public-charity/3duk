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

## Checkpoint 04 — validated first blockout; restart package ready

- The saved core now has two closed museum walks (768.7 m and 2,694.3 m), 19 active rest stops, 8 readable information boards and 13 proposed fence openings. All 32 evidence anchors retain unknown underground floors/portals; no historical tunnel network or measured interiors have been fabricated.
- The arrival sign renders correctly. Captured lettering uses an explicit checked emissive connection; its material graph is reused on later updates.
- Investigated the 3.8 cm reference-height discrepancy: it is the upper face where path ribbons overlap, not a native coordinate error. Independent triangle calculations reproduce the native collision surface. The current verifier checks the actual ribbon mesh, including overlaps, rather than treating a lower centreline as the top surface.
- The reopened museum checks pass: **3,837 floor probes**, no missing/buried path samples, no capsule-sweep obstacles, and maximum independent mesh/native collision residual under **0.025 mm**. This tiny residual describes computational agreement, not historical survey accuracy. The full CharacterMovement/Play-in-Editor walk and accessibility assessment remain unperformed.
- Latest asset checkpoint: **`Saved/Manston/checkpoints/20260911T213333Z/`**. Its `Content/` holds pre-update copies and `after/` holds resulting assets. Native updates preserved identities; the negative missing-target test preserved all existing definitions. No files outside the declared museum/fence scope changed. Verification left all 16,111 Content files unchanged.
- Current guide: `IMPLEMENTATION_GUIDE.md`. Distributable restart archive: repository-root `output/manston_phase1_checkpoint.zip`. The archive includes source recipes, native updater, reviewed renders, reports, hashes, and before/after package copies. It requires this existing Thanet world/data.
- The two unrelated pre-existing road-junction load errors remain. The final wrapper verdict also records `0xC0000005` at process teardown after the completed report and clean log shutdown, consistent with the existing World Partition teardown issue documented by the runner. The museum's positive report is not a clean whole-project engine verdict.

### Resume from here

1. Run `Tools/manston/check_checkpoint.py`; inspect the matching import and verification reports in `implementation/`.
2. Open the explorer and perform the full on-foot R1/R2 traversal, using the guide's gateway command. Detail crossings, directional signs, promenade supports and the few overlapping path joins.
3. Continue Phase 0 plan registration and Phase 1 historically supported restoration models: two existing museums, old RAF tower, T2 hangar and fighter pen. This checkpoint provides circulation and interpretation, not completed heritage architecture.
4. Advance Phases 2–3 only with the evidence gates in `MANSTON_MUSEUM_PLAN.md`: separate sunken hangars, railway/War Flight/FIDO layers, and individually evidenced underground features. Keep unknown portal/depth/connectivity fields unknown.

Source and implementation checkpoints are in Git on `thanet-explorer`; stage only Manston-owned files and preserve the other active road/vehicle work.

## Checkpoint 05 — full airfield surfaces saved

The user's next direction was to fill all runway surfaces and recover airfield features visible in LiDAR, cross-checking aerial imagery. The work is saved in the existing explorer as a separate, scoped overlay. See `airfield/PROGRESS.md` for the newest validation state and recovery point. It includes the full runway, broad historic pavement, taxiways, aprons, dispersal pads and a local raw-LiDAR terrain extension. Museum architecture and unknown underground geometry remain at checkpoint 04's state.

## Checkpoint 06 — complete airfield validated with museum circulation

The full 2,750 m runway, broad historic pavement, all retrieved taxiway/apron references, interpreted central apron and LiDAR-visible dispersal pads are saved. Read `airfield/README.md` and `airfield/LIDAR_FINDINGS.md` for evidence, uncertainty and previews. Combined validation passed 7,279 airfield surface probes, 999 additional runway probes and 3,837 museum floor probes with no raised-body sweep obstructions. Three boards and one bench were moved clear of the paths, with 19 existing component actors preserved and saved separately. The latest combined recovery archive is `output/manston_airfield_checkpoint.zip`; earlier phase archives remain dated checkpoints. Manual gameplay traversal and detailed museum architecture remain outstanding.
