#!/bin/bash
# Prove a pipeline edit did not change a site's products.
#   regress_outputs.sh snapshot <site> <label>   hash every file under data/<site>/out -> data/<site>/regress/<label>.sha256
#   regress_outputs.sh compare  <site> <label>   re-hash and diff against the snapshot
# Line format of the hash files is normalised to "<64 hex><two spaces><path>" with the path relative to
# out/ and no "./" prefix: on Windows GNU sha256sum marks binary mode with '*' glued to the name, which
# would break the ADDED-file allow list below. compare normalises the reference the same way, so a
# snapshot taken by hand (data/margate/regress/baseline_2026-09-08.sha256, BRIEF 8, "./" paths) is
# accepted as a label too.
# Exit 0 = nothing changed or removed and every added file is in ALLOW_NEW; exit 1 otherwise.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:-}"; SITE="${2:-}"; LABEL="${3:-before}"
[ -n "$MODE" ] && [ -n "$SITE" ] || { echo "usage: $0 snapshot|compare <site> [label]" >&2; exit 2; }
OUT="$ROOT/data/$SITE/out"; REG="$ROOT/data/$SITE/regress"; mkdir -p "$REG"
[ -d "$OUT" ] || { echo "FATAL: $OUT does not exist" >&2; exit 1; }
# Products a later commit is allowed to ADD without invalidating the snapshot (step 11, the Unreal
# adapter). Anything else that appears, disappears or changes is a problem.
# (doubled backslashes: awk -v processes escape sequences once, so "\\." reaches the regex as "\.")
ALLOW_NEW='^(networks/(rail|barriers)_x[0-9]+_y[0-9]+\\.jsonl|networks/linear_manifest\\.json|unreal/.*)$'
norm() { sed -E 's/^([0-9a-f]{64}) [ *]?(\.\/)?/\1  /'; }
hash_tree() { (cd "$OUT" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs -d '\n' sha256sum | norm); }
case "$MODE" in
  snapshot) hash_tree > "$REG/$LABEL.sha256"; echo "$(wc -l < "$REG/$LABEL.sha256") files hashed -> $REG/$LABEL.sha256" ;;
  compare)
    [ -s "$REG/$LABEL.sha256" ] || { echo "FATAL: no snapshot $REG/$LABEL.sha256 (run: $0 snapshot $SITE $LABEL)" >&2; exit 1; }
    hash_tree > "$REG/$LABEL.now.sha256"
    join -j 2 -a 1 -a 2 -e MISSING -o '0,1.1,2.1' \
      <(norm < "$REG/$LABEL.sha256" | LC_ALL=C sort -k2) <(LC_ALL=C sort -k2 "$REG/$LABEL.now.sha256") \
      | awk -v allow="$ALLOW_NEW" '
        $2=="MISSING" { if ($1 ~ allow) {added++} else {bad++; print "ADDED (unexpected) " $1}; next }
        $3=="MISSING" { bad++; print "REMOVED " $1; next }
        $2!=$3        { bad++; print "CHANGED " $1; next }
        { same++ }
        END { printf "%d identical, %d added (allowed), %d problems\n", same, added, bad; exit bad>0 }' ;;
  *) echo "usage: $0 snapshot|compare <site> [label]" >&2; exit 2 ;;
esac
