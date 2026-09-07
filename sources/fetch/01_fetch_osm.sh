#!/bin/bash
# Step 01 -- Overpass extract -> GeoPackage, plus a provenance record.
#
# OSM is live data: re-running this years later will NOT reproduce the same model.
# Footprints get added, retagged and split. The provenance file records exactly what
# was fetched so a later build can tell whether it is comparing like with like --
# and the raw extract is worth archiving somewhere durable if the model matters.
#
# Overpass bbox order is S,W,N,E, which is not the order anything else here uses.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${PY:-python3.14}"
eval "$("$PY" sources/lib.py env)"          # SITE CRS EPSG BBOX DIR_* OSM GPKG
PROV="sources/provenance/${SITE}.osm.json"

mkdir -p "$DIR_RAW" "$DIR_DERIVED" sources/provenance

# Reuse an extract only if it really is one and was fetched for THIS bbox. The provenance
# file records the bbox, so a changed config refetches instead of quietly modelling the
# old area. An extract with no provenance (one archived by hand) is used, with a warning.
NEED_FETCH=1
if [ -s "$OSM" ] && head -c 200 "$OSM" | grep -q "<?xml"; then
  if [ -s "$PROV" ]; then
    OLD_BBOX=$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("bbox_wgs84_swne",""))' "$PROV")
    if [ "$OLD_BBOX" = "$BBOX" ]; then
      echo "01: $OSM present ($(du -h "$OSM" | cut -f1)), bbox matches provenance -- skipping fetch (rm it to force)"
      NEED_FETCH=0
    else
      echo "01: $OSM was fetched for bbox $OLD_BBOX but the config now says $BBOX -- refetching"
      rm -f "$OSM"
    fi
  else
    echo "01: $OSM present with no provenance -- using it, but its bbox cannot be verified"
    NEED_FETCH=0
  fi
elif [ -e "$OSM" ]; then
  echo "01: $OSM is not an XML extract (a failed download?) -- refetching"
  rm -f "$OSM"
fi
if [ "$NEED_FETCH" = 1 ]; then
  echo "01: fetching OSM for $SITE, bbox $BBOX ..."
  BBOX="$BBOX" OUT="$OSM" ./sources/fetch/fetch_osm.sh
fi

# -t_srs IS LOAD-BEARING. Overpass returns WGS84 degrees; every downstream step
# rasterises these footprints against the projected LIDAR grid. Omit it and steps
# 04/07/09 run to completion, report zero errors, and silently sample nothing --
# "buildings with LIDAR: 0 / 7669". There is no crash to lead you to the cause.
#
# Only the three layers the pipeline consumes. Naming them explicitly keeps the empty
# relation layers GDAL would otherwise emit out of the file, and documents the contract:
# 04/07/09 read multipolygons, 06 reads lines, 10 reads points.
echo "01: converting to GeoPackage (reprojecting to $CRS) ..."
rm -f "$GPKG"
ogr2ogr -f GPKG -t_srs "$CRS" "$GPKG" "$OSM" points lines multipolygons

# Guard the reprojection without assuming a particular grid's magnitudes: compare the
# extent against the bbox reprojected through the same CRS. If -t_srs silently did not
# apply, the extent is still in degrees and will not land anywhere near it.
"$PY" - "$GPKG" "$BBOX" "$CRS" <<'PYEOF'
import sys
from osgeo import ogr, osr
ogr.UseExceptions(); osr.UseExceptions()
gpkg, bbox, crs = sys.argv[1:4]
s, w, n, e = (float(v) for v in bbox.split(","))
src = osr.SpatialReference(); src.ImportFromEPSG(4326)
src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
dst = osr.SpatialReference(); dst.SetFromUserInput(crs)
dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
tr = osr.CoordinateTransformation(src, dst)
xs, ys = zip(*[tr.TransformPoint(x, y)[:2] for x, y in ((w, s), (e, s), (w, n), (e, n))])
ds = ogr.Open(gpkg); lyr = ds.GetLayer("multipolygons")
x0, x1, y0, y1 = lyr.GetExtent()
pad = max(x1 - x0, y1 - y0, 1.0)
if not (min(xs) - pad <= x0 <= max(xs) + pad and min(ys) - pad <= y0 <= max(ys) + pad):
    sys.exit(f"01: FATAL -- {gpkg} extent ({x0:.1f},{y0:.1f}) is not inside the requested "
             f"bbox reprojected to {crs} ({min(xs):.1f},{min(ys):.1f})..({max(xs):.1f},{max(ys):.1f}); check -t_srs")
print(f"01: extent check OK -- {x0:.0f},{y0:.0f} .. {x1:.0f},{y1:.0f} in {crs}")
PYEOF

# Layers the downstream steps actually rely on. Fail loudly here rather than with a
# confusing GDAL error three steps later.
for L in multipolygons lines points; do
  ogrinfo -so "$GPKG" "$L" >/dev/null 2>&1 || { echo "01: FATAL -- layer '$L' missing from $GPKG" >&2; exit 1; }
done

BUILDINGS=$(ogrinfo -q -sql "SELECT COUNT(*) FROM multipolygons WHERE building IS NOT NULL AND building != 'no'" "$GPKG" | grep -oE '[0-9]+' | tail -1)
HIGHWAYS=$(ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE highway IS NOT NULL" "$GPKG" | grep -oE '[0-9]+' | tail -1)

"$PY" - "$OSM" "$BBOX" "${BUILDINGS:-0}" "${HIGHWAYS:-0}" "$PROV" "$SITE" "$CRS" <<'PYEOF'
import hashlib, json, os, sys, datetime
osm, bbox, buildings, highways, prov, site, crs = sys.argv[1:8]
h = hashlib.sha256()
with open(osm, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
# mtime of the extract, NOT "now" -- this script skips the fetch when the extract is
# already on disk, so a wall-clock stamp here would claim a download that never happened.
mtime = datetime.datetime.fromtimestamp(os.path.getmtime(osm), datetime.UTC)
json.dump({
    "site": site,
    "source": "OpenStreetMap via Overpass API",
    "licence": "ODbL",
    "crs": crs,
    "extract_mtime_utc": mtime.isoformat(timespec="seconds"),
    "recorded_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    "bbox_wgs84_swne": bbox,
    "bytes": os.path.getsize(osm),
    "sha256": h.hexdigest(),
    "counts": {"buildings": int(buildings), "highways": int(highways)},
    "note": f"Re-fetching later will differ; archive {osm} to reproduce.",
}, open(prov, "w"), indent=2)
print(f"01: {buildings} buildings, {highways} highways -> {prov}")
PYEOF
