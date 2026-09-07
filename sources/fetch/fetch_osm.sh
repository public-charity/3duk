#!/bin/bash
# Overpass fetch. Called by step 01, which supplies BBOX and OUT from the site config.
# bbox order for Overpass is S,W,N,E.
#
# No default bbox: a hardcoded fallback here means an unset BBOX silently downloads
# somewhere else entirely, and the first sign of it is a model of the wrong town.
set -euo pipefail
: "${BBOX:?set BBOX=S,W,N,E (step 01 passes this from the site config)}"
: "${OUT:?set OUT=<path for the .osm extract>}"
mkdir -p "$(dirname "$OUT")"
read -r -d '' Q <<QUERY || true
[out:xml][timeout:900][maxsize:1073741824];
(
  way["building"]($BBOX);
  relation["building"]($BBOX);
  way["highway"]($BBOX);
  way["natural"]($BBOX);
  way["landuse"]($BBOX);
  way["leisure"]($BBOX);
  way["waterway"]($BBOX);
  way["man_made"]($BBOX);
  way["barrier"]($BBOX);
  node["natural"="tree"]($BBOX);
  node["amenity"]($BBOX);
  node["shop"]($BBOX);
  node["tourism"]($BBOX);
);
(._;>;);
out body;
QUERY
echo "bbox: $BBOX"
for EP in https://overpass-api.de/api/interpreter https://overpass.private.coffee/api/interpreter https://overpass.kumi.systems/api/interpreter; do
  echo "trying $EP ..."
  if curl -sS --fail -m 900 -X POST -d "$Q" "$EP" -o "$OUT"; then
    if [ -s "$OUT" ] && head -c 200 "$OUT" | grep -q "<?xml"; then
      echo "OK -> $OUT ($(du -h "$OUT" | cut -f1))"; exit 0
    fi
    echo "  bad payload, trying next"
  fi
done
echo "all endpoints failed" >&2; exit 1
