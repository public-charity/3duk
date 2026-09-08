#!/bin/bash
# Rebuild a site's data layer from public sources.
#
#   ./sources/run.sh              run every step, 01 -> 11
#   ./sources/run.sh --from 04    resume from a step (steps are individually resumable)
#   ./sources/run.sh --only 06    run a single step
#   ./sources/run.sh --list       show the steps and exit
#
#   SITE=margate ./sources/run.sh        pick the site (required once there are two)
#   PY=/path/to/python ./sources/run.sh  the python with numpy + GDAL bindings (probed on PATH if unset);
#                                        the GDAL CLI (ogr2ogr, ogrinfo, gdalbuildvrt) must be on PATH
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
  "11:sources/derive/11_linear_features.py:OSM railway + barrier ways -> draped polylines (rail_*, barriers_*)"
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

# The python must import numpy AND the GDAL bindings: a bare `python3` on PATH is often a stub (the
# Microsoft Store alias on Windows) or an interpreter without osgeo, and the failure would otherwise
# surface as an ImportError three steps in. Probe, or trust an explicit PY= after checking it.
# (After the argument loop so --list needs no python at all.)
usable() { command -v "$1" >/dev/null 2>&1 && "$1" -c 'import numpy; from osgeo import gdal' >/dev/null 2>&1; }
if [ -z "${PY:-}" ]; then
  for cand in python3.14 python3.13 python3 python; do if usable "$cand"; then PY="$cand"; break; fi; done
  if [ -z "${PY:-}" ]; then
    echo "FATAL: no python with numpy + GDAL bindings found on PATH." >&2
    echo "       Set PY to one, e.g.  PY=/c/path/to/conda-env/python.exe SITE=thanet $0" >&2
    echo "       (the GDAL CLI must be on PATH too: PATH=/c/path/to/conda-env/Library/bin:\$PATH)" >&2
    exit 1
  fi
  echo "PY unset -> $PY"
elif ! usable "$PY"; then
  echo "FATAL: PY=$PY cannot import numpy and osgeo.gdal" >&2; exit 1
fi
export PY          # 01_fetch_osm.sh and 03_build_mosaics.sh read $PY

command -v ogr2ogr >/dev/null || { echo "FATAL: GDAL CLI not found" >&2; exit 1; }

# GDAL needs its data directory for the OSM driver (osmconf.ini) and PROJ needs proj.db.
# Packaged GDALs (conda, OSGeo4W) set these on activation; a bare PATH does not, and the
# failure is a wall of driver names that hides "cannot find osmconf.ini". Find them next
# to the binary and say so, rather than letting step 01 die confusingly.
GDAL_BIN="$(dirname "$(command -v ogr2ogr)")"
if [ -z "${GDAL_DATA:-}" ]; then
  for G in "$GDAL_BIN/../share/gdal" "$GDAL_BIN/../../share/gdal"; do
    if [ -f "$G/osmconf.ini" ]; then export GDAL_DATA="$(cd "$G" && pwd)"; echo "GDAL_DATA unset -> $GDAL_DATA"; break; fi
  done
fi
if [ -z "${PROJ_DATA:-}" ] && [ -z "${PROJ_LIB:-}" ]; then
  for G in "$GDAL_BIN/../share/proj" "$GDAL_BIN/../../share/proj"; do
    if [ -f "$G/proj.db" ]; then export PROJ_DATA="$(cd "$G" && pwd)"; echo "PROJ_DATA unset -> $PROJ_DATA"; break; fi
  done
fi
ogrinfo --formats 2>/dev/null | grep -q "OSM" || { echo "FATAL: this GDAL has no OSM driver (or cannot find osmconf.ini -- set GDAL_DATA)" >&2; exit 1; }

# Resolve the site once, up front, so an ambiguous SITE fails before any downloading.
eval "$("$PY" sources/lib.py env)"
echo "site: $SITE   crs: $CRS   grid: ${NX}x${NY}   -> data/$SITE/"

START=$(date +%s)
for s in "${STEPS[@]}"; do
  IFS=: read -r NUM PATHNAME DESC <<< "$s"
  [ -n "$ONLY" ] && [ "$NUM" != "$ONLY" ] && continue
  [ -z "$ONLY" ] && [ "$NUM" \< "$FROM" ] && continue
  [ -f "$PATHNAME" ] || { echo "FATAL: step $NUM is registered but $PATHNAME does not exist" >&2; exit 1; }

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
echo "for Unreal / Streetscape: SITE=$SITE $PY sources/adapters/unreal.py"
