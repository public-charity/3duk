#!/bin/bash
# Overpass fetch. Called by step 01, which supplies BBOX and OUT from the site config.
# bbox order for Overpass is S,W,N,E.
#
# No default bbox: a hardcoded fallback here means an unset BBOX silently downloads
# somewhere else entirely, and the first sign of it is a model of the wrong town.
#
# Public Overpass instances are shared and often busy. 429 (rate limited) and 504 (queue
# timeout) are normal weather, not faults in the query, so each endpoint gets ATTEMPTS
# tries with a growing pause before the next endpoint is tried. Two more things that look
# like success and are not:
#   * on any HTTP failure curl still writes the error page to OUT -- it is removed, so a
#     later run cannot mistake an HTML 504 for an extract;
#   * Overpass reports "runtime error" INSIDE a well-formed XML body with HTTP 200, so the
#     body is checked for real data before it is accepted.
set -euo pipefail
: "${BBOX:?set BBOX=S,W,N,E (step 01 passes this from the site config)}"
: "${OUT:?set OUT=<path for the .osm extract>}"
ATTEMPTS="${ATTEMPTS:-3}"
mkdir -p "$(dirname "$OUT")"
read -r -d '' Q <<QUERY || true
[out:xml][timeout:600][maxsize:536870912];
(
  way["building"]($BBOX);
  relation["building"]($BBOX);
  way["highway"]($BBOX);
  way["railway"]($BBOX);
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
  for ((a = 1; a <= ATTEMPTS; a++)); do
    echo "trying $EP (attempt $a/$ATTEMPTS) ..."
    CODE=$(curl -sS -m 900 -X POST -d "$Q" "$EP" -o "$OUT" -w '%{http_code}' 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ] && [ -s "$OUT" ] && head -c 200 "$OUT" | grep -q "<?xml"; then
      if grep -q -m1 "runtime error" "$OUT"; then
        echo "  Overpass runtime error inside the XML:"; grep -o -m1 "<remark>[^<]*" "$OUT" | head -c 300; echo
        rm -f "$OUT"
        [ "$a" -lt "$ATTEMPTS" ] && sleep $((20 * a)); continue
      fi
      if ! grep -q -m1 "<node " "$OUT"; then
        echo "  payload is XML but holds no nodes -- empty area or wrong bbox; not retrying this endpoint"
        rm -f "$OUT"; break
      fi
      echo "OK -> $OUT ($(du -h "$OUT" | cut -f1))"; exit 0
    fi
    echo "  HTTP $CODE"
    rm -f "$OUT"
    [ "$a" -lt "$ATTEMPTS" ] && sleep $((20 * a))
  done
done
echo "all endpoints failed" >&2; exit 1
