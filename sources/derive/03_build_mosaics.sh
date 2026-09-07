#!/bin/bash
# Step 03 -- mosaic the per-tile LIDAR GeoTIFFs into two VRTs.
#
# Steps 04, 06 and 09 all read the VRTs, never the individual tiles. A VRT is just XML
# pointing at the tiles, so this is instant -- but it also means the VRT breaks silently
# if the tile directory moves. Rebuild it rather than relocating it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${PY:-python3.14}"
eval "$("$PY" sources/lib.py env)"          # SITE NX NY DIR_* ...

mkdir -p "$DIR_INTERIM"

for KIND in dtm dsm; do
  N=$(ls "$DIR_LIDAR"/${KIND}_x*_y*.tif 2>/dev/null | wc -l | tr -d ' ')
  if [ "$N" -eq 0 ]; then
    echo "03: FATAL -- no ${KIND} tiles in $DIR_LIDAR. Run 02_fetch_lidar.py first." >&2
    exit 1
  fi
  gdalbuildvrt -q "$DIR_INTERIM/${KIND}.vrt" "$DIR_LIDAR"/${KIND}_x*_y*.tif
  echo "03: ${KIND}.vrt <- ${N} tiles"
done

# Expected count is nx*ny. Fewer means tiles fell outside the source's coverage, which is
# legal (the sea has no DTM) but you want to know about it before wondering why a tile is flat.
echo "03: expected $(( NX * NY )) tiles per kind for $SITE"
