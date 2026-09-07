#!/bin/bash
# Rebuild the Margate data layer from public sources.
#
#   ./sources/run.sh              run every step, 01 -> 10
#   ./sources/run.sh --from 04    resume from a step (steps are individually resumable)
#   ./sources/run.sh --only 06    run a single step
#   ./sources/run.sh --list       show the steps and exit
#
# Everything keys off sources/config/margate.json. Change that and every artefact
# downstream is invalid -- delete data/interim and data/out rather than trusting a
# partial rebuild.
#
# Steps are ordered, not parallel, and each is safe to re-run: 02 skips LIDAR tiles
# already on disk, 01 skips the Overpass fetch if the extract is present.
#
# Output lands in data/ at the repo root, which is not tracked -- everything here is
# re-fetchable from OpenStreetMap and the Environment Agency, so nothing is committed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PY:-python3.14}"

STEPS=(
  "01:sources/fetch/01_fetch_osm.sh:OSM extract -> GeoPackage"
  "02:sources/fetch/02_fetch_lidar.py:EA 1m LIDAR DTM + DSM per tile (WCS)"
  "03:sources/derive/03_build_mosaics.sh:mosaic LIDAR tiles into VRTs"
  "04:sources/derive/04_derive_heights.py:building heights from nDSM (p50 wall, p90 ridge)"
  "05:sources/derive/05_export_terrain.py:DTM -> 16-bit RAW heightmaps"
  "06:sources/derive/06_build_networks.py:OSM highways -> draped centrelines + widths"
  "07:sources/derive/07_massing.py:semantic per-building massing records"
  "09:sources/derive/09_coast.py:coastline, beach splat maps, sea extent"
  "10:sources/derive/10_furniture.py:street furniture placements from OSM amenity nodes"
)
# There is no 08. It was abandoned; the numbering is kept so log output and this
# script agree with the filenames on disk.

FROM="00"; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from)  FROM="$2"; shift 2 ;;
    --only)  ONLY="$2"; shift 2 ;;
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
