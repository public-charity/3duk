#!/bin/bash
# Prove a pipeline edit did not change a site's products.
#   regress_outputs.sh snapshot <site> <label>   hash every file under data/<site>/out -> data/<site>/regress/<label>.sha256
#   regress_outputs.sh compare  <site> <label>   re-hash and classify every difference
#   regress_outputs.sh selftest <site>           break twelve things on purpose and require the right verdict
#
# Needs a python for the JSON comparison (stdlib only). It probes $PY then python3.14/3.13/3/python; without
# one it falls back to byte-for-byte on JSON too, which is STRICTER, and says so on stderr.
#
# WHAT COUNTS AS A DIFFERENCE, AND WHY THIS IS NOT ONE HASH COMPARISON
# --------------------------------------------------------------------
# Rasters and record files are compared BYTE FOR BYTE and there is no allowance of any kind: a GeoTIFF, an
# .r16/.r8, a .jsonl, a .png that changes by one byte is a problem, full stop. That is the gate and it is not
# negotiable.
#
# The manifests are different in kind. They carry provenance (`generator` embeds the git sha of the code that
# wrote the file, so it changes on every commit by construction) and they legitimately GAIN keys as the
# pipeline learns to record more about itself. Under a pure hash comparison both of those read as "the product
# changed", which is how this gate came to fail under every snapshot on disk and stopped being able to catch
# anything at all. So a *.json file whose bytes differ is compared STRUCTURALLY instead:
#
#   * `generator` may hold a different value        -> reported as PROVENANCE, allowed
#   * a key listed in ALLOW_ADDED below may be new  -> reported as EXTENDED, allowed, with the key named
#   * anything else                                 -> CHANGED, a problem
#
# The structural comparison is not a loosening: it is verified by hash. The current file is parsed, the
# declared new keys are deleted, the provenance string is set back to a candidate old value, and the result is
# re-serialised in the file's own writer style and hashed against the snapshot line. If the result does not
# reproduce the snapshot byte for byte, the file is CHANGED. One recorded number moving by one digit fails.
# The ONLY things that can be forgiven are the ones named, per file, in the table below.
#
# Adding a row to ALLOW_ADDED is a deliberate act: it says "this key did not exist when the snapshot was taken,
# it does now, and nothing else in the file moved" - and the hash proves the second half. Do not add a row to
# make a red gate green; work out what changed first.
#
# Line format of the hash files is normalised to "<64 hex><two spaces><path>" with the path relative to
# out/ and no "./" prefix: on Windows GNU sha256sum marks binary mode with '*' glued to the name, which
# would break the ADDED-file allow list below. compare normalises the reference the same way, so a
# snapshot taken by hand (data/margate/regress/baseline_2026-09-08.sha256, BRIEF 8, "./" paths) is
# accepted as a label too.
# Exit 0 = nothing changed or removed, every added file is in ALLOW_NEW and every JSON difference reduced to
# provenance or a declared added key. Exit 1 otherwise.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:-}"; SITE="${2:-}"; LABEL="${3:-before}"
[ -n "$MODE" ] && [ -n "$SITE" ] || { echo "usage: $0 snapshot|compare|selftest <site> [label]" >&2; exit 2; }
OUT="$ROOT/data/$SITE/out"; REG="$ROOT/data/$SITE/regress"; mkdir -p "$REG"
[ -d "$OUT" ] || { echo "FATAL: $OUT does not exist" >&2; exit 1; }
# Products a later commit is allowed to ADD without invalidating the snapshot (step 11, the Unreal
# adapter). Anything else that appears, disappears or changes is a problem.
# (doubled backslashes: awk -v processes escape sequences once, so "\\." reaches the regex as "\.")
ALLOW_NEW='^(networks/(rail|barriers)_x[0-9]+_y[0-9]+\\.jsonl|networks/linear_manifest\\.json|unreal/.*)$'

# Keys a later commit is allowed to have ADDED to a JSON product, per path, with the commit that added them.
# "a.b.c" is a nested key. A key NOT listed here appearing in a file is CHANGED, not EXTENDED.
ALLOW_ADDED_TABLE=$(cat <<'EOT'
terrain/terrain_manifest.json	shared_edges	step 05's seam check (the per-tile NoData fill became one mosaic fill); it only records, it changes no raster
unreal/landscape/landscape_manifest.json	seam_qa tiles_fabricated tiles_fabricated_note empty_fill_m	3e26561, the adapter recording invented ground and the shared-edge check it now runs
unreal/unreal_manifest.json	products.landscape.tiles_fabricated partial_run derived_products	3e26561, the same count carried into the root manifest and the --only run marker; derived_products is the index entry for landscape_conformed, a product that lives beside the adapter's output and is not written by it
unreal/streetscape/streetscape_manifest.json	thin_interpolant_samples_per_segment point_quantum_m point_quantum_max_shift_m	3e26561, the adapter recording how it thins and quantises
EOT
)
# Provenance keys whose VALUE may differ between a snapshot and today. Nothing else about the file may.
PROVENANCE_KEYS='generator'

norm() { sed -E 's/^([0-9a-f]{64}) [ *]?(\.\/)?/\1  /'; }
hash_tree() { (cd "$OUT" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs -d '\n' sha256sum | norm); }

# A python that can parse JSON. Only stdlib is needed. Without one the JSON files are compared byte for byte
# (stricter, not looser) and the script says so.
find_py() {
  local c
  for c in ${PY:-} python3.14 python3.13 python3 python C:/Users/Shadow/code/3duk-env/env/python.exe; do
    [ -n "$c" ] || continue
    if "$c" -c 'import json,hashlib,sys' >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  return 1
}

case "$MODE" in
  snapshot) hash_tree > "$REG/$LABEL.sha256"; echo "$(wc -l < "$REG/$LABEL.sha256") files hashed -> $REG/$LABEL.sha256" ;;
  compare)
    [ -s "$REG/$LABEL.sha256" ] || { echo "FATAL: no snapshot $REG/$LABEL.sha256 (run: $0 snapshot $SITE $LABEL)" >&2; exit 1; }
    hash_tree > "$REG/$LABEL.now.sha256"
    WORK="$REG/.$LABEL.compare"; rm -rf "$WORK"; mkdir -p "$WORK"
    # Pass 1: the three plain verdicts, plus a list of JSON files to look at structurally.
    join -j 2 -a 1 -a 2 -e MISSING -o '0,1.1,2.1' \
      <(norm < "$REG/$LABEL.sha256" | LC_ALL=C sort -k2) <(LC_ALL=C sort -k2 "$REG/$LABEL.now.sha256") \
      | awk -v allow="$ALLOW_NEW" -v work="$WORK" '
        $2=="MISSING" { if ($1 ~ allow) {print "ADDED-ALLOWED " $1 > (work "/verdicts")} else {print "ADDED-UNEXPECTED " $1 > (work "/verdicts")}; next }
        $3=="MISSING" { print "REMOVED " $1 > (work "/verdicts"); next }
        $2!=$3        { if ($1 ~ /\.json$/) { print $1 "\t" $2 > (work "/json_todo") } else { print "CHANGED " $1 > (work "/verdicts") } ; next }
                      { print "IDENTICAL " $1 > (work "/verdicts") }'
    touch "$WORK/verdicts" "$WORK/json_todo"
    # Pass 2: the JSON files, structurally.
    if [ -s "$WORK/json_todo" ]; then
      if PYBIN="$(find_py)"; then
        printf '%s\n' "$ALLOW_ADDED_TABLE" > "$WORK/allow_added.tsv"
        cat > "$WORK/reduce.py" <<'PYEOF'
"""Can today's JSON file be reduced to the snapshot's bytes by (a) putting a provenance string back and
(b) deleting keys this repo has DECLARED were added? Proof is the sha256 of the re-serialised result."""
import hashlib, json, os, subprocess, sys

out_dir, todo, allow_path, prov_keys = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4].split(",")

allow = {}
if os.path.exists(allow_path):
    for line in open(allow_path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[0].strip():
            allow[parts[0].strip()] = [k for k in parts[1].split() if k]

STYLES = [(1, None, "\n", True), (1, None, "\r\n", False), (1, None, "\n", False), (1, None, "\r\n", True),
          (None, (",", ":"), "\n", True), (None, (",", ":"), "\n", False),
          (2, None, "\n", True), (2, None, "\n", False), (4, None, "\n", True), (4, None, "\n", False)]

def serialise(obj, style):
    indent, sep, nl, trail = style
    s = json.dumps(obj, indent=indent, separators=sep)
    if trail:
        s += "\n"
    return s.replace("\n", nl).encode("utf-8")

def detect(raw, obj):
    for st in STYLES:
        try:
            if serialise(obj, st) == raw:
                return st
        except Exception:
            pass
    return None

def collect_provenance(obj, keys, found, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str):
                found.append((path + (k,), v))
            collect_provenance(v, keys, found, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            collect_provenance(v, keys, found, path + (i,))

def drop(obj, dotted):
    parts = dotted.split(".")
    cur = obj
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]
        return True
    return False

def candidate_values(current):
    """Old values a provenance string could have held: today's, without -dirty, and the same stem at any of
    the last 60 commits (with and without -dirty)."""
    out = [current]
    if current.endswith("-dirty"):
        out.append(current[:-6])
    stem = current.split("@")[0] if "@" in current else None
    if stem:
        try:
            shas = subprocess.run(["git", "log", "--format=%h", "-60"], capture_output=True, text=True,
                                  cwd=os.path.dirname(os.path.abspath(__file__))).stdout.split()
        except Exception:
            shas = []
        for s in shas:
            out.append("%s@%s" % (stem, s))
            out.append("%s@%s-dirty" % (stem, s))
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq

for line in open(todo, encoding="utf-8"):
    rel, want = line.rstrip("\n").split("\t")
    path = os.path.join(out_dir, rel)
    raw = open(path, "rb").read()
    try:
        obj = json.loads(raw)
    except Exception as exc:
        print("CHANGED %s (json: will not parse - %s)" % (rel, exc))
        continue
    style = detect(raw, obj)
    if style is None:
        print("CHANGED %s (json: cannot be re-serialised byte for byte, so it cannot be compared "
              "structurally; treat as changed)" % rel)
        continue
    added = allow.get(rel, [])
    dropped = [k for k in added if drop(obj, k)]
    prov = []
    collect_provenance(obj, prov_keys, prov)
    base = serialise(obj, style)
    if hashlib.sha256(base).hexdigest() == want:
        print("EXTENDED %s (+%s)" % (rel, ",".join(dropped) if dropped else "nothing"))
        continue
    # Put a provenance string back. There is at most one such key in this repo's products; if a file ever
    # carries several, only the first is searched and the file falls through to CHANGED, which is safe.
    hit = None
    if prov:
        ppath, current = prov[0]
        for cand in candidate_values(current):
            if cand == current:
                continue
            cur = obj
            for p in ppath[:-1]:
                cur = cur[p]
            cur[ppath[-1]] = cand
            if hashlib.sha256(serialise(obj, style)).hexdigest() == want:
                hit = (".".join(str(x) for x in ppath), current, cand)
                break
        if hit is None:
            cur = obj
            for p in ppath[:-1]:
                cur = cur[p]
            cur[ppath[-1]] = current
    if hit is not None:
        kind = "EXTENDED" if dropped else "PROVENANCE"
        extra = (" +%s" % ",".join(dropped)) if dropped else ""
        print("%s %s (%s %s -> %s)%s" % (kind, rel, hit[0], hit[2], hit[1], extra))
    else:
        why = "provenance and the declared added keys (%s)" % (",".join(added) if added else "none declared")
        print("CHANGED %s (json: %s do not account for it - a recorded value differs)" % (rel, why))
PYEOF
        "$PYBIN" "$WORK/reduce.py" "$OUT" "$WORK/json_todo" "$WORK/allow_added.tsv" "$PROVENANCE_KEYS" >> "$WORK/verdicts"
      else
        echo "NOTE: no python found (set PY=), so JSON files are compared byte for byte only" >&2
        awk -F'\t' '{print "CHANGED " $1 " (json: no python to compare it structurally)"}' "$WORK/json_todo" >> "$WORK/verdicts"
      fi
    fi
    # Pass 3: report.
    grep -v -e '^IDENTICAL ' -e '^ADDED-ALLOWED ' "$WORK/verdicts" | LC_ALL=C sort || true
    awk '
      /^IDENTICAL /        { same++;  next }
      /^ADDED-ALLOWED /    { added++; next }
      /^PROVENANCE /       { prov++;  next }
      /^EXTENDED /         { ext++;   next }
                           { bad++ }
      END {
        printf "%d identical, %d provenance-only (allowed), %d extended (allowed), %d added (allowed), %d problems\n",
               same, prov, ext, added, bad
        exit bad > 0
      }' "$WORK/verdicts" ;;
  selftest)
    # A gate nobody has seen fail is not a gate. Build a scratch site out of four real products of <site>,
    # snapshot it, then break exactly one thing at a time and require the exact verdict.
    #   regress_outputs.sh selftest margate
    PYBIN="$(find_py)" || { echo "FATAL: selftest needs a python (set PY=)" >&2; exit 2; }
    set +e   # every case below runs a command that is SUPPOSED to exit 1
    S="$ROOT/data/_gatecheck"; rm -rf "$S"; mkdir -p "$S/out/terrain" "$S/out/unreal/streetscape" "$S/out/networks"
    cp "$OUT/terrain/$(cd "$OUT/terrain" && ls dtm_*.tif | head -1)"                     "$S/out/terrain/one.tif"
    cp "$OUT/terrain/terrain_manifest.json"                                              "$S/out/terrain/"
    cp "$OUT/unreal/streetscape/$(cd "$OUT/unreal/streetscape" && ls site_*.json | head -1)" "$S/out/unreal/streetscape/one.json"
    cp "$OUT/networks/$(cd "$OUT/networks" && ls roads_*.jsonl | head -1)"                "$S/out/networks/one.jsonl"
    cp -r "$S/out" "$S/pristine"
    # the scratch site's manifest sits at the same relative path, so the ALLOW_ADDED row for it applies
    fails=0
    _restore() { rm -rf "$S/out"; cp -r "$S/pristine" "$S/out"; }
    _case() { # name want_exit want_pattern [label]
      local name="$1" want="$2" pat="$3" lab="${4:-t0}" outp rc last
      outp="$("$0" compare _gatecheck "$lab" 2>&1)"; rc=$?
      last="$(printf '%s\n' "$outp" | tail -1)"
      if [ "$rc" = "$want" ] && printf '%s\n' "$outp" | grep -qE "$pat"; then
        echo "PASS  $name   ($last)"
      else
        echo "FAIL  $name   (exit $rc, wanted $want; wanted a line matching /$pat/)"
        printf '%s\n' "$outp" | grep -vE '^(IDENTICAL|ADDED-ALLOWED)' | head -5
        fails=$((fails + 1))
      fi
      _restore
    }
    "$0" snapshot _gatecheck t0 >/dev/null
    _case "untouched products compare clean" 0 '^4 identical, .* 0 problems$'
    "$PYBIN" -c "
import sys; p=sys.argv[1]
b=bytearray(open(p,'rb').read()); b[len(b)//2] ^= 1; open(p,'wb').write(bytes(b))" "$S/out/terrain/one.tif"
    _case "a flipped bit in a GeoTIFF is CHANGED" 1 '^CHANGED terrain/one\.tif$'
    "$PYBIN" -c "
import sys; p=sys.argv[1]
open(p,'wb').write(open(p,'rb').read().replace(b'\"cls\"', b'\"CLS\"', 1))" "$S/out/networks/one.jsonl"
    _case "an edited .jsonl record is CHANGED" 1 '^CHANGED networks/one\.jsonl$'
    "$PYBIN" -c "
import json, sys; p=sys.argv[1]
d=json.load(open(p)); d['slope_qa']['max_deg']=d['slope_qa']['max_deg']+0.1
open(p,'w',newline='').write(json.dumps(d,indent=1).replace(chr(10),chr(13)+chr(10)))" "$S/out/terrain/terrain_manifest.json"
    _case "a changed manifest NUMBER is CHANGED" 1 '^CHANGED terrain/terrain_manifest\.json'
    "$PYBIN" -c "
import json, sys; p=sys.argv[1]
d=json.load(open(p)); d['something_new']={'n':1}
open(p,'w',newline='').write(json.dumps(d,indent=1).replace(chr(10),chr(13)+chr(10)))" "$S/out/terrain/terrain_manifest.json"
    _case "an UNDECLARED added key is CHANGED" 1 '^CHANGED terrain/terrain_manifest\.json'
    "$PYBIN" -c "
import json, sys; p=sys.argv[1]
d=json.load(open(p)); d.pop('shared_edges',None)
open(p,'w',newline='').write(json.dumps(d,indent=1).replace(chr(10),chr(13)+chr(10)))" "$S/out/terrain/terrain_manifest.json"
    "$0" snapshot _gatecheck t5 >/dev/null; _restore
    _case "a DECLARED added key is EXTENDED, not a problem" 0 '^EXTENDED terrain/terrain_manifest\.json \(\+shared_edges\)' t5
    "$PYBIN" -c "
import json, sys; p=sys.argv[1]
d=json.load(open(p)); d.pop('shared_edges',None)
open(p,'w',newline='').write(json.dumps(d,indent=1).replace(chr(10),chr(13)+chr(10)))" "$S/out/terrain/terrain_manifest.json"
    _case "REMOVING a key the snapshot had is CHANGED" 1 '^CHANGED terrain/terrain_manifest\.json'
    "$PYBIN" -c "
import re, sys; p=sys.argv[1]
b=open(p,'rb').read()
open(p,'wb').write(re.sub(rb'(\"generator\":\")[^\"]*', rb'\g<1>somewhere/else.py@0000000', b, count=1))" "$S/out/unreal/streetscape/one.json"
    _case "a generator that is not a known commit is CHANGED" 1 '^CHANGED unreal/streetscape/one\.json'
    "$PYBIN" -c "
import json, subprocess, sys; p=sys.argv[1]
sha=subprocess.run(['git','log','--format=%h','-1'],capture_output=True,text=True).stdout.strip()
b=open(p,'rb').read(); d=json.loads(b); stem=d['generator'].split('@')[0]
open(p,'wb').write(b.replace(d['generator'].encode(), ('%s@%s' % (stem, sha)).encode(), 1))" "$S/out/unreal/streetscape/one.json"
    _case "a changed generator alone is PROVENANCE, not a problem" 0 '^PROVENANCE unreal/streetscape/one\.json'
    "$PYBIN" -c "
import json, sys; p=sys.argv[1]
d=json.load(open(p)); pt=d['splines'][0]['points'][0]; pt['x']=round(pt['x']+0.01, 2)
open(p,'w',newline=chr(10)).write(json.dumps(d,separators=(',',':'))+chr(10))" "$S/out/unreal/streetscape/one.json"
    _case "a 1 cm move of one spline point is CHANGED" 1 '^CHANGED unreal/streetscape/one\.json'
    rm "$S/out/terrain/one.tif"
    _case "a removed product is REMOVED" 1 '^REMOVED terrain/one\.tif$'
    echo hello > "$S/out/terrain/dtm_x9_y9.tif"
    _case "an unexpected new file is ADDED-UNEXPECTED" 1 '^ADDED-UNEXPECTED terrain/dtm_x9_y9\.tif$'
    rm -rf "$S"
    if [ "$fails" -eq 0 ]; then echo "regress_outputs selftest: 12 cases, 0 failed"; else echo "regress_outputs selftest: $fails FAILED"; exit 1; fi ;;
  *) echo "usage: $0 snapshot|compare|selftest <site> [label]" >&2; exit 2 ;;
esac
