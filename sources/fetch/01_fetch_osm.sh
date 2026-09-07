#!/bin/bash
# Step 01 -- Overpass extract -> GeoPackage, plus a provenance record.
#
# OSM is live data: re-running this years later will NOT reproduce the same model.
# Footprints get added, retagged and split. The provenance file records exactly what
# was fetched so a later build can tell whether it is comparing like with like --
# and data/raw/margate.osm is worth archiving somewhere durable if the model matters.
#
# Overpass bbox order is S,W,N,E, which is not the order anything else here uses.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

OSM="data/raw/margate.osm"
GPKG="data/derived/margate.gpkg"
PROV="sources/provenance/osm.json"
PY="${PY:-python3.14}"

mkdir -p data/raw data/derived sources/provenance

BBOX=$("$PY" -c 'import json;print(",".join(str(v) for v in json.load(open("sources/config/margate.json"))["bbox_wgs84"]))')

if [ -s "$OSM" ]; then
  echo "01: $OSM present ($(du -h "$OSM" | cut -f1)) -- skipping fetch (rm it to force)"
else
  echo "01: fetching OSM for bbox $BBOX ..."
  BBOX="$BBOX" OUT="$OSM" ./sources/fetch/fetch_osm.sh
fi

# -t_srs EPSG:27700 IS LOAD-BEARING. Overpass returns WGS84 degrees; every downstream
# step rasterises these footprints against the BNG LIDAR grid. Omit it and steps 04/07/09
# run to completion, report zero errors, and silently sample nothing -- "buildings with
# LIDAR: 0 / 7669". There is no crash to lead you to the cause.
#
# Only the three layers the pipeline consumes. Naming them explicitly keeps the empty
# relation layers GDAL would otherwise emit out of the file, and documents the contract:
# 04/07/09 read multipolygons, 06 reads lines, points is for later use.
echo "01: converting to GeoPackage (reprojecting to EPSG:27700) ..."
rm -f "$GPKG"
ogr2ogr -f GPKG -t_srs EPSG:27700 "$GPKG" "$OSM" points lines multipolygons

# Guard the reprojection: BNG eastings around Margate are ~630-640k. If this reads as
# degrees, -t_srs silently did not apply and everything downstream will sample nothing.
EXT_OK=$(ogrinfo -so "$GPKG" multipolygons | awk -F'[(,]' '/^Extent:/ {print ($2 > 100000) ? "yes" : "no"}')
[ "$EXT_OK" = "yes" ] || { echo "01: FATAL -- $GPKG is not in projected metres; check -t_srs" >&2; exit 1; }

# Layers the downstream steps actually rely on. Fail loudly here rather than with a
# confusing GDAL error three steps later.
for L in multipolygons lines; do
  ogrinfo -so "$GPKG" "$L" >/dev/null 2>&1 || { echo "01: FATAL -- layer '$L' missing from $GPKG" >&2; exit 1; }
done

BUILDINGS=$(ogrinfo -q -sql "SELECT COUNT(*) FROM multipolygons WHERE building IS NOT NULL AND building != 'no'" "$GPKG" | grep -oE '[0-9]+' | tail -1)
HIGHWAYS=$(ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE highway IS NOT NULL" "$GPKG" | grep -oE '[0-9]+' | tail -1)

"$PY" - "$OSM" "$BBOX" "${BUILDINGS:-0}" "${HIGHWAYS:-0}" "$PROV" <<'PYEOF'
import hashlib, json, os, sys, datetime
osm, bbox, buildings, highways, prov = sys.argv[1:6]
h = hashlib.sha256()
with open(osm, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
# mtime of the extract, NOT "now" -- this script skips the fetch when the extract is
# already on disk, so a wall-clock stamp here would claim a download that never happened.
mtime = datetime.datetime.fromtimestamp(os.path.getmtime(osm), datetime.UTC)
json.dump({
    "source": "OpenStreetMap via Overpass API",
    "extract_mtime_utc": mtime.isoformat(timespec="seconds"),
    "recorded_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    "bbox_wgs84_swne": bbox,
    "bytes": os.path.getsize(osm),
    "sha256": h.hexdigest(),
    "counts": {"buildings": int(buildings), "highways": int(highways)},
    "note": "ODbL. Re-fetching later will differ; archive data/raw/margate.osm to reproduce.",
}, open(prov, "w"), indent=2)
print(f"01: {buildings} buildings, {highways} highways -> {prov}")
PYEOF
