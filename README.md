# 3duk

Two things live here: a scanned street-furniture asset, and a pipeline that turns public
UK geodata into a tiled model of a place.

The pipeline output is **engine-neutral** — GeoTIFF rasters and JSONL in the site's own
CRS, elevation in real metres, north-up. Consumers convert; the survey stays honest.

```
assets/LitterBin/   Glasdon Jubilee 110 bin -- FBX + albedo, the Blender script that
                    builds it, and the provenance of the scan it came from
sources/
  lib.py            site resolution, config, raster geometry -- shared by every step
  config/
    sites/<site>.json   one file per place: CRS, tile grid, bbox, source coverages,
                        water level, height calibration, landmark overrides
    tuning.json         cross-site opinions: road widths, building priors, percentiles
  fetch/            01 Overpass extract, 02 1 m LIDAR DTM/DSM over WCS
  derive/           03-10 mosaics, heights, terrain, roads, massing, ground cover,
                    street furniture
  adapters/         consumer-specific conversion; unity.py is the reference
  provenance/       what was actually fetched -- bbox, sha256, feature counts
  run.sh            the driver
```

## Rebuilding

```bash
./sources/run.sh --list           # the steps
SITE=margate ./sources/run.sh     # 01 -> 10, each step resumable
./sources/run.sh --from 04        # resume
```

Needs `python3.14` (override with `PY=`) and the GDAL CLI. `scipy` is optional but
wanted: without it, terrain nodata is filled with a median instead of a true
nearest-valid fill, and step 05 says so loudly rather than quietly degrading.

Output lands in `data/<site>/`, which is not tracked. `SITE` is required once more than
one site is configured — with exactly one, it resolves on its own.

## Adding a site

Add `sources/config/sites/<name>.json` and set `SITE=<name>`. No step should need
editing. If one does, that is a bug in the step, not a missing feature — the constant it
wants belongs in the site config or in `tuning.json`.

Read the notes in the config before reusing another site's numbers. `height_calib`,
`coast.foreshore_max_odn` and `coast.rock_slope_deg` are measurements of one town and one
survey flight, not universal constants, and `tuning.json`'s `type_priors_m` records which
site it was measured at. Step 07 warns when more than 5% of buildings fall back to those
priors, because that means the model is being described by another place's vernacular.

## Sources and licensing

| | |
|---|---|
| Buildings, highways, amenities | OpenStreetMap via Overpass API — **ODbL** |
| Terrain and surface heights | Environment Agency LIDAR Composite 1 m DTM + first-return DSM — **OGL v3** |

OSM is live data: re-running `01` later will not reproduce the earlier model, because
footprints get added, retagged and split. `sources/provenance/<site>.osm.json` records the
bbox, byte count and sha256 of the extract actually used, so a later build can tell whether
it is comparing like with like.

## Output

| Step | Product |
|---|---|
| 05 | `terrain/dtm_x*_y*.tif` — Float32 GeoTIFF, real metres, north-up, CRS-tagged |
| 06 | `networks/roads_x*_y*.jsonl` — centrelines as `[easting, northing, elevation]`, width, class, bridge/tunnel flags |
| 07 | `massing/buildings_x*_y*.jsonl` — per-building height, ridge, eaves, roof form, rings in CRS metres, and `src` naming which evidence produced the height |
| 09 | `coast/ground_x*_y*.tif` — 3-band grass/sand/rock fractions, north-up, plus water tile list |
| 10 | `furniture/furniture_x*_y*.jsonl` — prop key, position, `bearing` degrees clockwise from grid north |

Every step writes a manifest beside its output recording the CRS, the origin and the
parameters it ran under. **[sources/OUTPUT.md](sources/OUTPUT.md) is the contract** — every
field, its units, what `null` means, and which values are measurements versus opinions.

## Checking it without GDAL

```bash
python3 sources/tests/dryrun.py
```

Runs steps 05–10 and the Unity adapter against a synthetic two-tile site through a fake
in-memory GDAL. Needs numpy only. It proves the wiring, the schemas in `OUTPUT.md`, and the
fidelity guarantees (nodata by declared sentinel, honest bridge elevation, buildings without
LIDAR emitted rather than dropped, calibration from config, north-up rasters, adapter refusing
to clip terrain). It does not exercise GDAL itself or steps 01–04.

### Consumers

`sources/adapters/unity.py` converts all of it to Unity's conventions — local metres from
the grid origin, Y-up, 16-bit RAW heightmaps, south-first alphamaps, yaw — and holds the
things that are properly Unity's and not the survey's: road draw-order lift, and the
invented bridge and tunnel offsets. It refuses to encode terrain that does not fit its
height window rather than silently flattening it.

Write a sibling adapter for any other consumer. Nothing in `sources/derive/` should ever
learn about one.

## The bin

`assets/LitterBin/` — photogrammetry scan of a real Thanet District Council bin, rebuilt
as parametric geometry and snapped to the manufacturer's published 1158 × 598 × 553 mm.
Three LODs, one 1024×512 albedo. `.fbx` and `.png` are tracked with git-lfs. The README in
that folder has the full method and the caveats worth reading before scanning another.
