#!/bin/bash
# Rebuild Virtual Margate's data layer from scratch.
#
#   ./run.sh              run every data step, 01 -> 10
#   ./run.sh --from 04    resume from a step (steps are individually resumable)
#   ./run.sh --only 06    run a single step
#   ./run.sh --unity      after the data steps, drive Unity headlessly to rebuild the scene
#   ./run.sh --list       show the steps and exit
#
# Everything keys off pipeline/config/margate.json. Change that and every artefact
# downstream is invalid -- delete data/interim, data/out and the Unity Generated/
# folder rather than trusting a partial rebuild.
#
# Steps are ordered, not parallel, and each is safe to re-run: 02 skips LIDAR tiles
# already on disk, 01 skips the Overpass fetch if the extract is present.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PY:-python3.14}"
UNITY="${UNITY:-/Applications/Unity/Hub/Editor/6000.3.23f1/Unity.app/Contents/MacOS/Unity}"

STEPS=(
  "01:pipeline/01_fetch_osm.sh:OSM extract -> GeoPackage"
  "02:pipeline/02_fetch_lidar.py:EA 1m LIDAR DTM + DSM per tile (WCS)"
  "03:pipeline/03_build_mosaics.sh:mosaic LIDAR tiles into VRTs"
  "04:pipeline/04_derive_heights.py:building heights from nDSM (p50 wall, p90 ridge)"
  "05:pipeline/05_export_terrain.py:DTM -> Unity 16-bit RAW heightmaps"
  "06:pipeline/06_build_networks.py:OSM highways -> draped centrelines + widths"
  "07:pipeline/07_massing.py:semantic per-building massing records"
  "09:pipeline/09_coast.py:coastline, beach splat maps, sea extent"
  "10:pipeline/10_furniture.py:street furniture placements from OSM amenity nodes"
)
# There is no 08. It was abandoned; the numbering is kept so log output and this
# script agree with the filenames on disk.

FROM="00"; ONLY=""; DO_UNITY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from)  FROM="$2"; shift 2 ;;
    --only)  ONLY="$2"; shift 2 ;;
    --unity) DO_UNITY=1; shift ;;
    --list)  for s in "${STEPS[@]}"; do IFS=: read -r n p d <<< "$s"; printf "  %s  %s\n" "$n" "$d"; done; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

command -v "$PY" >/dev/null || { echo "FATAL: $PY not found (override with PY=...)" >&2; exit 1; }
command -v ogr2ogr >/dev/null || { echo "FATAL: GDAL CLI not found (brew install gdal)" >&2; exit 1; }

START=$(date +%s)
for s in "${STEPS[@]}"; do
  IFS=: read -r NUM PATHNAME DESC <<< "$s"
  [ -n "$ONLY" ] && [ "$NUM" != "$ONLY" ] && continue
  [ -z "$ONLY" ] && [ "$NUM" \< "$FROM" ] && continue

  echo ""
  echo "=============================================================="
  echo " $NUM  $DESC"
  echo "=============================================================="
  T0=$(date +%s)
  case "$PATHNAME" in
    *.sh) bash "$PATHNAME" ;;
    *.py) "$PY" "$PATHNAME" ;;
  esac
  echo "-- $NUM done in $(( $(date +%s) - T0 ))s"
done

echo ""
echo "data layer rebuilt in $(( $(date +%s) - START ))s -> data/out/"

if [ "$DO_UNITY" -eq 1 ]; then
  [ -x "$UNITY" ] || { echo "FATAL: Unity not at $UNITY (override with UNITY=...)" >&2; exit 1; }
  if pgrep -f "Unity.app/Contents/MacOS/Unity -projectPath" >/dev/null; then
    echo "FATAL: the Unity GUI holds the project lock. Close it, or use tools/build_when_free.sh." >&2
    exit 1
  fi
  echo "driving Unity headlessly (MargateBootstrap.BuildAll) ..."
  "$UNITY" -projectPath "$ROOT/unity/VirtualMargate" -batchmode -quit \
           -executeMethod MargateBootstrap.BuildAll -logFile "$ROOT/tools/.rebuild.log"
  grep -E "\[Margate\]|error CS" tools/.rebuild.log | head -20 || true
  echo "unity build done -> tools/.rebuild.log"
fi
