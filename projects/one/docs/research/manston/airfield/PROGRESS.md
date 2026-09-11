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
