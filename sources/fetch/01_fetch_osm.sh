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
QUERY="$OSM.query"
if [ "$NEED_FETCH" = 1 ]; then
  echo "01: fetching OSM for $SITE, bbox $BBOX ..."
  BBOX="$BBOX" OUT="$OSM" ./sources/fetch/fetch_osm.sh          # writes $QUERY just before the download
  QUERY_SRC="fetch"
elif [ -s "$QUERY" ] && [ ! "$QUERY" -nt "$OSM" ]; then
  QUERY_SRC="recorded"                                          # older than the extract: written at fetch time
else
  # Skipped fetch and no query recorded with the extract (extracts from before query recording, or a
  # query file newer than the extract, i.e. an earlier reconstruction). Write the query fetch_osm.sh
  # would send TODAY so the provenance can list its selectors, and flag it as a reconstruction: the
  # extract may have been fetched with different selectors (Margate's predates way["railway"]).
  echo "01: no query recorded with $OSM -- reconstructing $QUERY from fetch_osm.sh's current selectors"
  QUERY_ONLY=1 BBOX="$BBOX" OUT="$OSM" ./sources/fetch/fetch_osm.sh
  QUERY_SRC="reconstructed"
fi

# ---- datum transformation guard ------------------------------------------------------
# OSM is WGS84; the LIDAR is natively in the site CRS. For British National Grid the
# accurate WGS84 -> OSGB36 transformation is the OSTN15 grid (1 m class, ~10 cm in
# practice). Without the grid file PROJ silently falls back to a 7-parameter Helmert
# (2 m class) and the whole model lands ~1.8 m off the LIDAR: footprints on the street,
# eaves 0.6 m low, roof coverage under footprints down from 92% to 87% -- and nothing
# anywhere says so. Found by regressing against the original Margate model. PROJ can fetch
# grids from cdn.proj.org when PROJ_NETWORK=ON; try that, and otherwise refuse to build.
MAX_ACC=$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("crs_max_transform_accuracy_m", 1.0))' "sources/config/sites/${SITE}.json")
best_op() {
  projinfo -s EPSG:4326 -t "$CRS" --bbox "$BW,$BS,$BE,$BN" --spatial-test intersects -o PROJ 2>/dev/null \
    | grep -m1 -E "^(unknown id|[A-Za-z_]+:[0-9]+), "
}
acc_of() { echo "$1" | grep -oE ", [0-9.]+ m, " | grep -oE "[0-9.]+" | head -1; }
if command -v projinfo >/dev/null; then
  IFS=, read -r BS BW BN BE <<< "$BBOX"                  # our bbox is S,W,N,E; projinfo wants W,S,E,N
  OP=$(best_op); ACC=$(acc_of "$OP")
  if [ -z "$ACC" ] || awk "BEGIN{exit !($ACC > $MAX_ACC)}"; then
    echo "01: best available WGS84 -> $CRS transformation is ${ACC:-unknown} m class; need <= $MAX_ACC m"
    echo "01: enabling PROJ_NETWORK=ON so PROJ can fetch the transformation grid from cdn.proj.org ..."
    export PROJ_NETWORK=ON
    OP=$(best_op); ACC=$(acc_of "$OP")
    if [ -z "$ACC" ] || awk "BEGIN{exit !($ACC > $MAX_ACC)}"; then
      echo "01: FATAL -- still ${ACC:-unknown} m class: $OP" >&2
      echo "    The model would sit metres off the LIDAR. Install the grid (conda: proj-data; or download the" >&2
      echo "    grid projinfo names from https://cdn.proj.org into \$PROJ_DATA), or allow network access." >&2
      exit 1
    fi
  fi
  echo "01: datum transformation (${ACC} m class): $(echo "$OP" | cut -c1-110)"
else
  OP="unverified: projinfo not available"
  echo "01: WARNING -- projinfo not found; cannot verify the WGS84 -> $CRS transformation. The model may be metres off the LIDAR."
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
# Build into a sibling and rename at the end. The old code removed $GPKG first, which
# (a) destroyed the good product before knowing the new one converts and passes the guards
# below, and (b) aborted the whole step whenever anything held the file open -- normal on
# Windows while another step, an adapter or a GIS tool is reading it.
GPKG_TMP="${GPKG%.gpkg}.new.gpkg"      # keep the .gpkg extension: GDAL warns about any other
rm -f "$GPKG_TMP"
ogr2ogr -f GPKG -t_srs "$CRS" "$GPKG_TMP" "$OSM" points lines multipolygons

# Guard the reprojection without assuming a particular grid's magnitudes: compare the
# extent against the bbox reprojected through the same CRS. If -t_srs silently did not
# apply, the extent is still in degrees and will not land anywhere near it.
"$PY" - "$GPKG_TMP" "$BBOX" "$CRS" <<'PYEOF'
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
  ogrinfo -so "$GPKG_TMP" "$L" >/dev/null 2>&1 || { echo "01: FATAL -- layer '$L' missing from $GPKG_TMP" >&2; exit 1; }
done

# Only now replace the product, so a reader never sees a half-written GeoPackage and a failed
# conversion never destroys the good one. On Windows the rename still fails while another
# process holds the old file open, so say exactly that instead of a bare "Device or resource
# busy" -- and leave the verified .tmp in place, so a re-run costs nothing.
for attempt in 1 2 3 4 5; do
  if mv -f "$GPKG_TMP" "$GPKG" 2>/dev/null; then break; fi
  if [ "$attempt" = 5 ]; then
    echo "01: FATAL -- cannot replace $GPKG: another process has it open (a pipeline step, an adapter" >&2
    echo "    or a GIS tool reading it). The new GeoPackage is built and verified at $GPKG_TMP;" >&2
    echo "    close the reader and re-run 01, or rename it into place by hand." >&2
    exit 1
  fi
  echo "01: $GPKG is held open by another process; retrying the rename ($attempt/5) ..." >&2
  sleep 2
done

BUILDINGS=$(ogrinfo -q -sql "SELECT COUNT(*) FROM multipolygons WHERE building IS NOT NULL AND building != 'no'" "$GPKG" | grep -oE '[0-9]+' | tail -1)
HIGHWAYS=$(ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE highway IS NOT NULL" "$GPKG" | grep -oE '[0-9]+' | tail -1)
RAILWAY=$(ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE railway IS NOT NULL" "$GPKG" | grep -oE '[0-9]+' | tail -1)
BARRIERS=$(ogrinfo -q -sql "SELECT COUNT(*) FROM lines WHERE barrier IS NOT NULL" "$GPKG" | grep -oE '[0-9]+' | tail -1)

"$PY" - "$OSM" "$BBOX" "${BUILDINGS:-0}" "${HIGHWAYS:-0}" "$PROV" "$SITE" "$CRS" "$OP" \
        "${RAILWAY:-0}" "${BARRIERS:-0}" "$QUERY" "$QUERY_SRC" <<'PYEOF'
import hashlib, json, os, re, sys, datetime
osm, bbox, buildings, highways, prov, site, crs, op, railway, barriers, query, query_src = sys.argv[1:13]
h = hashlib.sha256()
with open(osm, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
# mtime of the extract, NOT "now" -- this script skips the fetch when the extract is
# already on disk, so a wall-clock stamp here would claim a download that never happened.
mtime = datetime.datetime.fromtimestamp(os.path.getmtime(osm), datetime.UTC)
# The Overpass query: its sha256 and the sorted unique selectors (node/way/relation[...] with the
# bbox stripped), so a later build can tell whether two extracts asked for the same things. A query
# reconstructed after a skipped fetch is flagged, because the extract may predate a selector change.
qsha, qsel, qnote = None, [], None
if os.path.isfile(query) and os.path.getsize(query) > 0:
    qbytes = open(query, "rb").read()
    qsha = hashlib.sha256(qbytes).hexdigest()
    qsel = sorted(set(re.findall(r"(?:node|way|relation)\[[^\]]*\]", qbytes.decode("utf-8", "replace"))))
    if query_src == "reconstructed":
        qnote = (f"query_* describe {os.path.basename(query)} as RECONSTRUCTED from fetch_osm.sh's selectors at "
                 f"record time, because the fetch was skipped (extract already on disk) and no query had been "
                 f"recorded with it; the extract may have been fetched with different selectors -- judge by "
                 f"counts.railway / counts.barriers, not by the selector list.")
else:
    qnote = ('null query_* means the extract predates query recording; it was fetched by fetch_osm.sh as of '
             'commit 0d31c0c, which had no way["railway"]')
json.dump({
    "site": site,
    "source": "OpenStreetMap via Overpass API",
    "licence": "ODbL",
    "crs": crs,
    "datum_transformation": op,
    "extract_mtime_utc": mtime.isoformat(timespec="seconds"),
    "recorded_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    "bbox_wgs84_swne": bbox,
    "bytes": os.path.getsize(osm),
    "sha256": h.hexdigest(),
    "query_sha256": qsha,
    "query_src": (query_src if qsha else "absent"),
    "query_src_note": "'fetch' -- the query this run sent to Overpass. 'recorded' -- the query file saved "
                      "beside the extract by the run that fetched it. 'reconstructed' -- the fetch was skipped "
                      "and the selectors were rebuilt from fetch_osm.sh AS IT IS NOW, so they describe this "
                      "script, not necessarily the extract on disk. 'absent' -- no query at all. A consumer "
                      "must test query_src, not just query_sha256 != null: a reconstructed sha256 is a real "
                      "hash of a query that may never have been sent.",
    "query_selectors": qsel,
    "query_note": qnote,
    "counts": {"buildings": int(buildings), "highways": int(highways),
               "railway": int(railway), "barriers": int(barriers)},
    "note": f"Re-fetching later will differ; archive {osm} to reproduce.",
}, open(prov, "w", newline="\n"), indent=2)      # LF on every platform: the repo is LF-only
print(f"01: {buildings} buildings, {highways} highways, {railway} railway ways, {barriers} barrier ways -> {prov}")
print(f"01: query {'sha256 ' + qsha[:12] + '...' if qsha else 'not recorded'} ({query_src}), {len(qsel)} selectors")
PYEOF
