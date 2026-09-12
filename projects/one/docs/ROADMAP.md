# Thanet building foundation roadmap

Recorded 2026-09-12 after the user's stated intention to fund another 200 hours.
The objective is a dependable map foundation for detailed buildings. The phase
sequence and hour allocations below are planning recommendations, not guaranteed
durations, completed milestones, or authorization to run an unattended schedule.

## Proposed allocation of the additional 200 hours

| Phase | Deliverable | Hours |
|---|---|---:|
| 1. Physical ground and transport | Road/rail geometry, junctions, terrain contact, cuttings, embankments, necessary crossing structures, and verified engine integration | 70 |
| 2. Land use and ground surfaces | Fields, grassland, woodland areas, parks, beaches, exposed chalk, yards, car parks, materials and transitions | 30 |
| 3. Building placement foundation | Footprints, ground references, local terrain adjustments, entrances, driveways, pavement connections and replaceable placeholders | 35 |
| 4. Vegetation and boundaries | Trees, hedgerows, shrubs and grass that respect transport, building footprints and access | 25 |
| 5. Whole-map integration | Streaming, collision, performance, consistent appearance, walk/drive inspections and a verified saved baseline | 20 |
| Contingency | Difficult geometry, missing evidence and integration problems | 20 |
| Total | Additional budget | 200 |

Phase 1 remains open. Start with RESUME.md and PHASE1_QC.md for current evidence;
this roadmap does not promote any geometry or terrain candidate. The latest
completed checkpoint when this plan was discussed was 42: 11,186 passing bodies,
1,911 folded bodies, 230 connectors and one retained interior bend. Original
junction failures and whole-network physical acceptance remained open. Ongoing
checkpoint 43 work must not be confused with a completed checkpoint.

The earlier broad estimate was 40-100 additional hours for reliable transport and
terrain integration, with 100+ possible for every strict exception. These were
low-confidence estimates from observed progress, not measured future workloads.
If Phase 1 needs more than its allocation, reduce vegetation detail before
compromising building placement and ground connections.

## Delivery and acceptance

Plan 10-20-hour milestones around saved, inspectable improvements. Track accepted
repairs, unresolved defects, physical coverage and visible results separately
from unit-test counts, candidate proposals and documentation checkpoints. Use
reusable batch tools for repeated checks and searches, and model reasoning for
new failure types and algorithm design. Preserve measured versus inferred data.

Before decorating the island, prove the building workflow on a terraced street,
a sloping plot, a detached house, a farm and a large commercial building:

- Replace a placeholder with a detailed asset at the intended position/elevation.
- Connect entrances to surrounding paths without buried doors or floating steps.
- Adjust local ground without disturbing neighbouring roads or buildings.
- Regenerate terrain/vegetation without overwriting authored building changes.
- Save, reopen and stream each area with its relationships intact.

Farmland includes field boundaries, margins, tracks and appropriate surfaces.
Crop type, planting direction and individual vegetation placement require evidence
or explicit modelling labels. Ground contact precision does not establish real
world survey accuracy. Detailed facades, interiors and landmark reconstruction
follow the foundation rather than determining its acceptance.

## References

- [Current recovery and progress record](RESUME.md)
- [Phase 1 quality and acceptance](PHASE1_QC.md)
- [Original brief](BRIEF.md)
- [Strategic handover](HANDOVER.md)
- [Epic landscape materials](https://dev.epicgames.com/documentation/unreal-engine/landscape-materials-in-unreal-engine)
- [Epic procedural generation](https://dev.epicgames.com/documentation/unreal-engine/procedural-content-generation-overview?lang=en-US)
