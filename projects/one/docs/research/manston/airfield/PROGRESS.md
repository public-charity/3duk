# Airfield completion checkpoints

User direction: complete all visible runway/airfield surfaces and investigate LiDAR artifacts. Preserve frequent saves.

## 00 — evidence and coverage diagnosis

- Existing source supplement has 1 runway centreline, 23 taxiway records, 24 apron records and an aerodrome boundary (49 total; verified by generator).
- The explorer's diagonal Wantsum clip passes through the main runway. Full airfield completion therefore needs a narrowly scoped extension over the missing airport ground. The raw EA DTM has complete coverage of the inspected E631400–634850 / N165050–167250 extent.
- Reviewed Esri World Imagery in the browser, in EPSG:27700 at that extent. The imagery shows the broad surviving paved runway strip, parallel taxiways, northern dispersal pads, aprons and a separate northeastern paved strip. That strip's precise historical function and the imagery capture date are not established. Do not treat cloud shadows or grass discoloration as measured archaeological structures.
- Source: https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox=631400,165050,634850,167250&bboxSR=27700&imageSR=27700&size=1800,1150&format=png&f=image
- Historical corroboration: https://www.manstonhistory.org.uk/manston-layout-history/ and existing/redundant pavement on https://rsp.co.uk/wp-content/uploads/2018/01/04-Masterplan-2018.pdf (proposed new buildings excluded).
- No engine assets changed at this checkpoint. Next: author complete surface coverage and local terrain restoration from raw DTM, validate, save scoped actors, reopen and inspect.

## 01 — complete geometry candidate validated

- Authored 2,750 m x 61 m runway 10/28 with threshold bars, threshold stripes, numbers, centre dashes, edge lines and aiming marks. Broad surviving pavement is reconstructed at approximately 230 m overall width. These dimensions describe the model, not new survey measurements.
- All 23 source taxiway records and 24 source apron records are represented, plus one approximate central apron infill from aerial interpretation. The Y/T-shaped dispersal pads and separate northeastern strip are included.
- Total pavement: 836,289 m²; local missing-ground extension: 461,309 m². Existing landscape and road assets are retained. Surface unions avoid stacked intersecting pavement meshes; the shared road renderer produces the markings.
- 124 caches / 526,551 triangles pass geometry/hash checks; 1,260 checks cover the entire runway footprint. Paint interval slivers collapsing at 10-micron cache precision were removed before import. An early commandlet launch was stopped during startup, before any airfield checkpoint or Content change.
- The generic native cache uploader compiled successfully; parsing/material/topology checks happen before it changes its supplied actor. Imports save every eight actors and retain before/after bytes. Source recipes are checkpointed in Git.
- Next: finish native import, reopen the saved map, test full-width runway collision and surface contact, and inspect the before/after renders.

## 02 — airfield saved in the explorer

- Native checkpoint `Saved/ManstonAirfield/checkpoints/20260911T220935Z/` contains the initial import. All 124 mesh actors and six dedicated materials are saved; the journal reached `saved`.
- Content guard: 130 added files, no deleted files and no modified existing files. The museum, roads and global landscape assets remain byte-identical.
- The before overview confirms the original runway area had no pavement mesh and its western half was beyond the diagonal terrain cut. Read-only saved-map collision and after-render checks are now the next gate; do not call this verified until their report is complete.

## 03 — native facing correction

- The first reopened verification failed every floor probe and showed no new surface from above. The initial symptom looked like a persistence problem. Inspection of the existing `FStreetGeometry::ToDynamicMesh` identified the actual conversion mistake: GeometryCore uses a left-handed face normal, so the source triangle indices must be kept when reflecting Y. The new uploader had reversed them a second time.
- Corrected triangle order to match the existing converter and supplied complete UV/normal overlays. Added a top-face collision check for every ground/pavement cache before its next save, and a saved-triangle-count check on reopening.
- The failed report is retained as `Saved/ManstonAirfield/verification_before_winding_fix.json`. All original map Content remained unchanged by that read-only check. The corrected import/reopen cycle is the next acceptance gate.

## 04 — corrected surfaces saved

- Latest native checkpoint: `Saved/ManstonAirfield/checkpoints/20260911T222019Z/`. All non-paint caches passed top-face collision checks before being saved. Existing airfield actor identities were preserved; no Content outside the declared airfield scope changed.
- This checkpoint's `after/` is the corrected output. Its `before/` is the preceding, unverified reversed-face attempt and should not be used as a visually accepted airfield restoration. The initial import's `before.json` records the original map baseline.
- Reopened full-width runway checks, saved triangle counts and render review are in progress. Museum path collision regression is next because some new paved surfaces cross the museum circulation.

## 05 — surface contact diagnosis and marking correction

- Reopened all 526,551 saved triangles; all 7,279 component floor traces and 999 independent full-runway traces hit their intended surfaces. The overview and close views show the restored airfield.
- The apparent 157 buried samples are all outside the original landscape visibility clip: independent Heightfield sampling returns NaN for every one. Unreal's editor height query still reports filled, invisible heightmap texels there. The contact check now explicitly uses the source visibility mask and reports the excluded count; visible terrain retains the same 2 cm failure threshold.
- Paint sampled directly from the raster crossed the differently tessellated floor, producing small holes in white markings. Revised baking intersects Renderer A's marking footprints with the exact exported pavement triangles and offsets each resulting face 9 mm above its supporting face. Footprint area coverage is checked during generation.
- Revised geometry generation is running. Reimport/reopen and museum-walk regression remain required; this is not the final accepted checkpoint.

## 06 — complete surface bake saved for final reopen

- Revised bake: 124 caches / 565,258 triangles, 1,260 whole-runway coverage checks and all 49 source aeroway records accounted for. Marking footprints are fully supported by the pavement; white-paint area is 6,728.576 m². Manifest `f01d3002ac86740465e14e3be56fc608f76373a4b3825f9aa2b4ed319da0a64f`.
- Saved checkpoint `Saved/ManstonAirfield/checkpoints/20260911T223349Z/`. The importer updated the same 124 actor identities and six dedicated materials, saving in batches of eight. No added/deleted Content files and no modification outside those 130 owned files.
- Import Python completed, with the two inherited road-junction errors and known process-teardown `0xC0000005` still reported by the wrapper. This is not a clean global engine result.
- The final reopen now runs both airfield surface validation and the established R1/R2 museum floor/body-capsule checks in the same loaded world. Packaging refuses a stale or failed museum regression. Final report and visual review pending.

## 07 — museum circulation correction

- The final airfield surface check passed all 7,279 floor probes and 999 full-runway probes, with no missing/buried visible pavement. The reviewed west-end render shows continuous threshold stripes, numbers, edges and aiming marks. The overview and northern dispersal close-up confirm the recovered surfaces.
- The broader loaded and rendered world exposed six raised-body sweep hits against four existing museum furniture groups: signs MKE98027/MKE98021/MKE98024 and bench R1_1. No new airfield surface obstructed those body sweeps. All 3,837 existing museum floor probes still passed.
- Moved those four complete furniture groups by 2.5–5.5 m, checking their full footprints against both routes and buildings. Minimum footprint-to-route-centre distance is now over 2 m. Canonical museum furniture positions and restart hashes were updated; future museum generation preserves these explicit corrections or rejects them if the underlying route placement changes.
- Nineteen existing component actors saved in `Saved/ManstonAirfield/furniture_checkpoints/20260911T224215Z/`; no other Content files changed. Both before/after copies and a batch-save journal are retained. The earlier failed circulation report remains `Saved/ManstonAirfield/museum_before_clearance.json`.
- Reopen both airfield and museum collision checks before packaging. Full manual CharacterMovement traversal remains a separate unperformed check.

## 08 — combined saved-world validation passed

- Accepted airfield checkpoint: `20260911T223349Z`, plus furniture checkpoint `20260911T224215Z`. Final surface and museum reports both pass for the current manifests.
- Saved 565,258 surface triangles reopened correctly. All 7,279 component floor probes and 999 independent full-runway probes hit. No visible-terrain burial; minimum sampled pavement clearance 0.065 m. All 3,837 museum floor probes passed and both routes have zero raised-body capsule obstructions. Verification left all 16,241 Content files unchanged.
- Reviewed the final overview, western threshold and northern dispersal renders, plus the museum overview. White markings are continuous; the full runway, northern pads and connected aprons remain visible. Surface materials and historic widths are still reconstruction/blockout treatments, not detailed archaeological fabric.
- The final Python script reported success. The two inherited road-junction errors remain; the runner's full exit classification is kept in `Saved/ManstonAirfield/verify_runner4.log`. Do not describe this as a clean whole-project engine run.
- Package command: `Tools/manston/package_airfield.py`. It refuses mismatched reports, source hashes, airfield/furniture asset hashes, or a failed museum regression, and verifies the ZIP CRC after writing. Current guide and recovery archive are `airfield/README.md` and repository-root `output/manston_airfield_checkpoint.zip`.
- Next museum work: manual full character traversal and crossing/support detail, followed by the historically evidenced building restorations already in the phased plan. No new subsurface connectivity, floor levels or portals were invented for this surface completion.

Final runner verdict: `unknown_exit`, raw `-1073741819` / `0xC0000005`, Python success true, two inherited road errors, no crash markers, clean log shutdown true, 150.7 s. The task-specific validation passed; the known World Partition teardown fault remains outside this change.
