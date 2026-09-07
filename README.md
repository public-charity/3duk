# 3duk

Two things survive here: a scanned street-furniture asset, and the pipeline that turns
public UK geodata into a tiled model of Margate. The game project that consumed them
has been removed.

```
assets/LitterBin/   Glasdon Jubilee 110 bin -- FBX + albedo, the Blender script that
                    builds it, and the provenance record of the scan it came from
sources/
  fetch/            01 Overpass extract, 02 EA 1m LIDAR DTM/DSM over WCS
  derive/           03-10 mosaics, building heights, terrain, roads, massing, coast,
                    street furniture
  config/           margate.json (BNG origin, 13x7 512 m tiles, WCS coverage ids),
                    landmarks.json (hand-authored height overrides), _tiles.json
  provenance/       osm.json -- bbox, sha256 and feature counts of the extract used
  run.sh            the driver
```

## Rebuilding the data

```bash
./sources/run.sh --list     # the steps
./sources/run.sh            # 01 -> 10, each step resumable
./sources/run.sh --from 04  # resume
```

Needs `python3.14` (override with `PY=`) and the GDAL CLI. Output lands in `data/`,
which is not tracked.

## Sources and licensing

| | |
|---|---|
| Buildings, highways, amenities | OpenStreetMap via Overpass API — **ODbL** |
| Terrain and surface heights | Environment Agency LIDAR Composite 1 m DTM + first-return DSM — **OGL v3** |

OSM is live data: re-running `01` later will not reproduce the earlier model, because
footprints get added, retagged and split. `sources/provenance/osm.json` records the bbox,
byte count and sha256 of the extract actually used, so a later build can tell whether it
is comparing like with like.

## The bin

`assets/LitterBin/` — photogrammetry scan of a real Thanet District Council bin, rebuilt
as parametric geometry and snapped to the manufacturer's published 1158 × 598 × 553 mm.
Three LODs, one 1024×512 albedo. `.fbx` and `.png` are tracked with git-lfs. The README
in that folder has the full method and the caveats worth reading before scanning another.
