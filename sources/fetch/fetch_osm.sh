#!/bin/bash
# Fetch all Margate OSM layers needed for the massing pipeline.
# bbox order for Overpass is S,W,N,E
set -euo pipefail
BBOX="${BBOX:-51.365,1.345,51.402,1.432}"
OUT="${OUT:-data/raw/margate.osm}"
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
