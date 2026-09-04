#!/bin/bash
# Step 03 -- mosaic the per-tile LIDAR GeoTIFFs into two VRTs.
#
# Steps 04, 06 and 09 all read data/interim/{dtm,dsm}.vrt, never the individual tiles.
# A VRT is just XML pointing at the tiles, so this is instant -- but it also means the
# VRT breaks silently if data/raw/lidar/ moves. Rebuild it rather than relocating it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p data/interim

for KIND in dtm dsm; do
  N=$(ls data/raw/lidar/${KIND}_x*_y*.tif 2>/dev/null | wc -l | tr -d ' ')
  if [ "$N" -eq 0 ]; then
    echo "03: FATAL -- no ${KIND} tiles in data/raw/lidar/. Run 02_fetch_lidar.py first." >&2
    exit 1
  fi
  gdalbuildvrt -q "data/interim/${KIND}.vrt" data/raw/lidar/${KIND}_x*_y*.tif
  echo "03: ${KIND}.vrt <- ${N} tiles"
done

# Expected count is nx*ny. Fewer means tiles fell outside EA coverage, which is legal
# (the sea has no DTM) but you want to know about it before wondering why a tile is flat.
EXPECT=$(python3.14 -c 'import json;c=json.load(open("pipeline/config/margate.json"));print(c["nx"]*c["ny"])')
echo "03: expected ${EXPECT} tiles per kind"
