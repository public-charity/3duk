#!/bin/bash
# Rebuild a site's data layer from public sources.
#
#   ./sources/run.sh              run every step, 01 -> 10
#   ./sources/run.sh --from 04    resume from a step (steps are individually resumable)
#   ./sources/run.sh --only 06    run a single step
#   ./sources/run.sh --list       show the steps and exit
#
#   SITE=margate ./sources/run.sh        pick the site (required once there are two)
#
# Everything keys off sources/config/sites/<site>.json plus sources/config/tuning.json.
# Change either and every artefact downstream is invalid -- delete data/<site>/interim
# and data/<site>/out rather than trusting a partial rebuild.
#
# Steps are ordered, not parallel, and each is safe to re-run: 02 skips LIDAR tiles
# already on disk, 01 skips the Overpass fetch if the extract is present.
#
# Output is engine-neutral: GeoTIFF rasters and JSONL in the site CRS, elevation in
# real metres. To get Unity's conventions, run sources/adapters/unity.py afterwards.
#
# Output lands in data/<site>/, which is not tracked -- everything here is re-fetchable
# from the public endpoints, so none of it is committed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PY:-python3.14}"

STEPS=(
  "01:sources/fetch/01_fetch_osm.sh:OSM extract -> GeoPackage"
  "02:sources/fetch/02_fetch_lidar.py:1 m LIDAR DTM + DSM per tile (WCS)"
  "03:sources/derive/03_build_mosaics.sh:mosaic LIDAR tiles into VRTs"
  "04:sources/derive/04_derive_heights.py:building heights from nDSM (wall p50, ridge p90)"
  "05:sources/derive/05_export_terrain.py:cleaned per-tile terrain GeoTIFFs"
  "06:sources/derive/06_build_networks.py:OSM highways -> draped centrelines + widths"
  "07:sources/derive/07_massing.py:semantic per-building massing records"
  "09:sources/derive/09_coast.py:ground classification, coastline, sea extent"
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
command -v ogr2ogr >/dev/null || { echo "FATAL: GDAL CLI not found" >&2; exit 1; }

# Resolve the site once, up front, so an ambiguous SITE fails before any downloading.
eval "$("$PY" sources/lib.py env)"
echo "site: $SITE   crs: $CRS   grid: ${NX}x${NY}   -> data/$SITE/"

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
    *.sh) SITE="$SITE" bash "$PATHNAME" ;;
    *.py) SITE="$SITE" "$PY" "$PATHNAME" ;;
  esac
  echo "-- $NUM done in $(( $(date +%s) - T0 ))s"
done

echo ""
echo "data layer rebuilt in $(( $(date +%s) - START ))s -> data/$SITE/out/"
echo "for Unity conventions: SITE=$SITE $PY sources/adapters/unity.py"
