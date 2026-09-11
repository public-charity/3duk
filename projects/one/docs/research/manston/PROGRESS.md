# Manston implementation checkpoints

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
