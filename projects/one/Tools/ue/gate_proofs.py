"""gate_proofs - deliberately break something, prove the gate fails, restore it, prove it passes (D4).

Run with the PIPELINE python from anywhere (like make_cutout_manifest.py it is a host-side tool, NOT an
editor-Python script):

    C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/gate_proofs.py [--only <id>,<id>] [--out <json>]

A gate that has never been seen to fail is not a gate; it is a line of code that has always been true. Every case
below names one gate, breaks exactly one thing, runs the real command, and requires a non-zero exit AND a
THANET_FAIL line whose text mentions the gate. The clean cases at the end run the same commands on the same
un-broken inputs and require THANET_OK, so a case that "fails" because the whole path is broken is caught.

The landscape cases work on a 2x2-tile cutout (make_cutout_manifest.py) imported into its own scratch map, so a
proof costs about a minute and never touches /Game/Thanet/Maps/Thanet.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
PROJ = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(os.path.dirname(PROJ))
DATA = REPO + "/data/thanet/out/unreal"
SCRATCH = PROJ + "/Saved/GateProof"
GOOD = SCRATCH + "/good"
MAP = "/Game/Thanet/Maps/GateProof"
RUNNER = HERE + "/run_ue_python.ps1"


def sh(script, args, log, render=True):
    """One headless editor run. Returns (exit_code, stdout_text)."""
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", RUNNER,
           "-Script", script, "-Args", args, "-Log", log]
    if render:
        cmd.append("-Render")
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or ""), round(time.time() - t0, 1)


def verdict_lines(text):
    ok = [l.strip() for l in text.splitlines() if "THANET_OK " in l]
    bad = [l.strip() for l in text.splitlines() if "THANET_FAIL " in l]
    return ok, bad


def reset_dir(name):
    """A fresh copy of the clean cutout under Saved/GateProof/<name>."""
    dst = SCRATCH + "/" + name
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(GOOD, dst)
    return dst


def manifest(path):
    with open(path) as fh:
        return json.load(fh)


def write_manifest(path, man):
    with open(path, "w", newline="\n") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
        fh.write("\n")


# ---------------------------------------------------------------------------------------------------------------
# the cases. break() prepares the input and returns the (script, args) to run; `expect` is a fragment the
# THANET_FAIL line (or the log) must contain, so a run that fails for an unrelated reason is not counted as proof.
# ---------------------------------------------------------------------------------------------------------------

def case_corrupt_r16():
    d = reset_dir("corrupt_r16")
    p = d + "/hm_x0_y0.r16"
    with open(p, "r+b") as fh:                      # 8 bytes short: the file is there and is not the tile
        fh.truncate(os.path.getsize(p) - 8)
    return ("02_import_landscape.py",
            "--manifest %s/landscape_manifest.json --map %s --recreate-map --report %s/report.json" % (d, MAP, d),
            "bytes, expected")


def case_missing_tile_file():
    d = reset_dir("missing_tile")
    os.remove(d + "/hm_x1_y1.r16")                  # the manifest still lists it
    return ("02_import_landscape.py",
            "--manifest %s/landscape_manifest.json --map %s --recreate-map --report %s/report.json" % (d, MAP, d),
            "cannot read")


def case_malformed_tile_entry():
    d = reset_dir("malformed_tile")
    mp = d + "/landscape_manifest.json"
    man = manifest(mp)
    man["tiles"].append("this is not a tile object")
    write_manifest(mp, man)
    return ("02_import_landscape.py",
            "--manifest %s/landscape_manifest.json --map %s --recreate-map --report %s/report.json" % (d, MAP, d),
            "is not a JSON object")


def case_missing_material():
    d = reset_dir("no_material")
    return ("02_import_landscape.py",
            "--manifest %s/landscape_manifest.json --map %s --recreate-map --material /Game/Thanet/Materials/M_Does_Not_Exist.M_Does_Not_Exist --report %s/report.json" % (d, MAP, d),
            "did not load")


def case_grid_probe_mismatch():
    """--probes-only against a directory whose heights are NOT the ones that were imported."""
    d = reset_dir("shifted_heights")
    for name in os.listdir(d):
        if not name.endswith(".r16"):
            continue
        p = d + "/" + name
        with open(p, "r+b") as fh:
            b = bytearray(fh.read())
            for i in range(0, len(b), 2):           # +1280 h16 = +10 m everywhere
                v = min(65535, b[i] | (b[i + 1] << 8)) + 1280
                v = min(65535, v)
                b[i] = v & 0xFF
                b[i + 1] = (v >> 8) & 0xFF
            fh.seek(0)
            fh.write(bytes(b))
    return ("02_import_landscape.py",
            "--manifest %s/landscape_manifest.json --map %s --probes-only --no-cliff --allow-skipped-gates --report %s/report.json" % (d, MAP, d),
            "grid.within_0_01_m")


def case_component_count():
    """A manifest that declares a tile the level was never imported with: the plan grows, the level does not."""
    d = reset_dir("extra_tile")
    mp = d + "/landscape_manifest.json"
    man = manifest(mp)
    man["nx"] = 3
    extra = json.loads(json.dumps(man["tiles"][0]))
    extra["x"] = 2
    man["tiles"].append(extra)
    write_manifest(mp, man)
    return ("02_import_landscape.py",
            "--manifest %s/landscape_manifest.json --map %s --probes-only --no-grid --no-cliff --no-clip --report %s/report.json" % (d, MAP, d),
            "counts.ok is False")


def case_skipped_gate():
    """--no-load-all makes the grid gate unable to run; it used to be one log line and a pass."""
    d = SCRATCH + "/good"
    return ("02_import_landscape.py",
            "--manifest %s/landscape_manifest.json --map %s --probes-only --no-load-all --no-cliff --no-clip --report %s/skipped_report.json" % (d, MAP, SCRATCH),
            "within_0_01_m did not run")


def case_verify_zero_actors():
    return ("03_import_streetscape.py", "--verify --map %s" % MAP, "verify found 0 AStreetscapeActor")


def case_census_zero_actors():
    return ("04_probe.py", "--census --map %s" % MAP, "holds 0 AStreetscapeActor")


def case_explorer_no_player_start():
    return ("04_probe.py", "--explorer --map %s" % MAP, "no PlayerStart")


def case_materials_no_components():
    return ("04_probe.py", "--materials --load-all --map %s" % MAP, "no streetscape or massing components")


def case_massing_count():
    """A massing manifest whose file count does not match what the import produced."""
    d = SCRATCH + "/massing"
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    src = DATA + "/massing"
    names = sorted(n for n in os.listdir(src) if n.startswith("buildings_x") and n.endswith(".jsonl"))[:3]
    for n in names:
        shutil.copyfile(src + "/" + n, d + "/" + n)
    man = manifest(src + "/massing_manifest.json")
    man["files"] = len(names) + 7                   # the manifest claims seven tiles that are not there
    write_manifest(d + "/massing_manifest.json", man)
    return ("06_import_massing.py", "--dir %s --map %s --no-save" % (d, MAP), "massing_manifest.files")


CASES = [
    ("corrupt_r16", "importer: a heightmap tile that is the wrong size", case_corrupt_r16),
    ("missing_tile_file", "importer: a manifest tile whose file is not on disk", case_missing_tile_file),
    ("malformed_tile_entry", "importer: a tiles[] entry that is not an object", case_malformed_tile_entry),
    ("missing_material", "importer: the landscape material does not load", case_missing_material),
    ("grid_probe_mismatch", "02 gate grid.within_0_01_m", case_grid_probe_mismatch),
    ("component_count", "02 gate counts.ok (components / proxies / extent / tiles_read vs the plan)", case_component_count),
    ("skipped_gate", "02: a gate that did not run is not a gate that passed", case_skipped_gate),
    ("verify_zero_actors", "03 --verify on a level with no streetscape actor", case_verify_zero_actors),
    ("census_zero_actors", "04 --census on a level with no streetscape actor", case_census_zero_actors),
    ("explorer_no_player_start", "04 --explorer with no PlayerStart", case_explorer_no_player_start),
    ("materials_no_components", "04 --materials with nothing to audit", case_materials_no_components),
    ("massing_count", "06 actors != massing_manifest.files", case_massing_count),
]

# the case after which the clean cutout must be imported again, because everything before it left the map empty
CLEAN_BEFORE = "grid_probe_mismatch"

# after the breakage: the same commands on the same clean inputs must pass again
CLEAN = [
    ("clean_import", "02_import_landscape.py",
     "--manifest %s/landscape_manifest.json --map %s --recreate-map --no-cliff --allow-skipped-gates --report %s/clean_report.json" % (GOOD, MAP, SCRATCH)),
    ("clean_probes", "02_import_landscape.py",
     "--manifest %s/landscape_manifest.json --map %s --probes-only --no-cliff --allow-skipped-gates --report %s/clean_probes.json" % (GOOD, MAP, SCRATCH)),
]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=PROJ + "/Saved/Tests/gate_proofs.json")
    ap.add_argument("--skip-clean", action="store_true")
    a = ap.parse_args(argv[1:])
    only = set(x for x in a.only.split(",") if x)
    if not os.path.isdir(GOOD):
        raise SystemExit("no clean cutout at %s - make_cutout_manifest.py first" % GOOD)

    results = []
    clean = []

    def run_clean(cid, script, args):
        code, text, secs = sh(script, args, "gate_%s.log" % cid)
        ok_lines, fail_lines = verdict_lines(text)
        passed = code == 0 and bool(ok_lines) and not fail_lines
        clean.append({"id": cid, "script": script, "args": args, "exit_code": code,
                      "seconds": secs, "passed": passed,
                      "thanet_ok": (ok_lines[-1][:400] if ok_lines else None),
                      "thanet_fail": (fail_lines[-1][:400] if fail_lines else None)})
        print("%-26s %s exit=%d" % (cid, "PASS   " if passed else "FAIL   ", code))
        sys.stdout.flush()

    for cid, what, fn in CASES:
        if only and cid not in only:
            continue
        # every case up to and including missing_material recreates the map and then fails, so the map is left
        # with no landscape. The probes-only cases that follow need one: import the clean cutout first, and
        # require THAT to pass, or a "gate failed" verdict below would only be saying the level is empty.
        if cid == CLEAN_BEFORE and not only:
            run_clean(*CLEAN[0])
        script, args, expect = fn()
        code, text, secs = sh(script, args, "gate_%s.log" % cid)
        ok_lines, fail_lines = verdict_lines(text)
        blob = "\n".join(fail_lines) if fail_lines else text
        proved = code != 0 and bool(fail_lines) and expect in blob
        results.append({
            "id": cid, "gate": what, "script": script, "args": args,
            "expect_in_failure": expect, "exit_code": code, "seconds": secs,
            "thanet_fail": (fail_lines[-1][:400] if fail_lines else None),
            "thanet_ok_lines": len(ok_lines),
            "proved": proved,
        })
        print("%-26s %s exit=%d %s" % (cid, "PROVED " if proved else "NOT PROVED", code,
                                       (fail_lines[-1][:160] if fail_lines else "(no THANET_FAIL)")))
        sys.stdout.flush()

    if not a.skip_clean and not only:
        for cid, script, args in CLEAN:
            run_clean(cid + "_final" if any(c["id"] == cid for c in clean) else cid, script, args)

    out = {"cases": results, "clean": clean,
           "proved": sum(1 for r in results if r["proved"]), "cases_run": len(results),
           "clean_passed": sum(1 for c in clean if c["passed"]), "clean_run": len(clean),
           "cutout": GOOD, "map": MAP}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("cases", "clean")}, sort_keys=True))
    print("report: %s" % a.out)
    bad = [r["id"] for r in results if not r["proved"]] + [c["id"] for c in clean if not c["passed"]]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
