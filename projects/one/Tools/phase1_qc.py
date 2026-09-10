#!/usr/bin/env python3
"""Bounded, resumable road QC. Never equates a numerical pass with Phase 1 acceptance.

Run through Tools/python.ps1. Default: fixed risk sample, at most two chunks per call.
Repeat the same command to resume. --scope full --max-jobs 0 runs every chunk.
State and reports live under Saved/Phase1/<scope>/<content fingerprint>/.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parents[2]
SAMPLE_CAMERAS = (
    "birchington/railway_bridge_over_minnis_road",
    "broadstairs/st_peters_high_street",
    "broadstairs/north_foreland_lighthouse",
    "westwood/haine_road_past_westwood_cross",
    "birchington/station_road_to_the_square",
    "acol/margate_hill_at_the_isle_edge",
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Windows readers/virus scanners can briefly open without FILE_SHARE_DELETE.
    # Keep the old complete state while retrying the atomic rename; never fall
    # back to truncating the live state file.
    for attempt in range(21):
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(0.1)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def content_identity(paths, config):
    entries = {str(p.resolve()): sha256(p) for p in sorted(set(map(Path, paths)))}
    digest = hashlib.sha256(json.dumps({"files": entries, "config": config},
                                      sort_keys=True).encode()).hexdigest()
    return digest, entries


def measurements(jobs, lods):
    """Sum counts/lengths, never average per-chunk percentages."""
    totals = {}
    for lod in lods:
        rows = [read_json(j["report"])["by_lod"][f"lod{lod}"] for j in jobs
                if j["status"] in ("passed", "failed") and "report_sha256" in j]
        if not rows:
            continue
        out = {key: sum(r.get(key, 0) for r in rows) for key in
               ("splines", "stations_with_terrain", "stations_penetrated", "stations_floating",
                "carriageway_km_total", "carriageway_km_penetrated", "float_km")}
        out["fraction_length_penetrated"] = (out["carriageway_km_penetrated"] /
                                             out["carriageway_km_total"] if out["carriageway_km_total"] else None)
        out["fraction_stations_floating"] = (out["stations_floating"] /
                                             out["stations_with_terrain"] if out["stations_with_terrain"] else None)
        for label in ("penetration", "float"):
            out[label + "_max_m"] = max(r.get(label + "_m_over_all_stations", {}).get("max", 0) for r in rows)
        totals[f"lod{lod}"] = out
    return totals


def inventory(streetscape):
    paths = sorted(Path(streetscape).glob("site_x*_y*.json"))
    if not paths:
        raise ValueError("no site documents: empty coverage cannot pass")
    counts, classes, documents, structures = Counter(), Counter(), [], []
    seen = set()
    for path in paths:
        doc = read_json(path)
        rows = []
        for sp in doc["splines"]:
            if sp["id"] in seen:
                raise ValueError("duplicate spline id: " + sp["id"])
            seen.add(sp["id"])
            counts["all_splines"] += 1
            source = sp.get("source") or {}
            if source.get("layer") not in ("roads", "rail") or not sp["profile_ids"].get("road"):
                continue
            flags = sp.get("flags") or {}
            kind = "bridge" if flags.get("bridge") else "tunnel" if flags.get("tunnel") else "ground"
            counts[kind] += 1
            classes[source.get("cls") or "unknown"] += 1
            if kind != "ground":
                structures.append({"doc": path.name, "spline_id": sp["id"], "kind": kind})
            rows.append(sp)
        counts["junctions"] += len(doc.get("junctions", []))
        documents.append({"name": path.name, "eligible": len(rows),
                          "ground": sum(not (s.get("flags") or {}).get("bridge") and
                                        not (s.get("flags") or {}).get("tunnel") for s in rows)})
    if not counts["ground"]:
        raise ValueError("no ground roads/rail to audit")
    return {"counts": dict(counts), "classes": dict(classes), "documents": documents,
            "structures_pending_acceptance": structures}, paths


def sample_documents(paths, spec_path):
    spec = read_json(spec_path)
    locations = {t["slug"] + "/" + loc["slug"]: loc
                 for t in spec["towns"] for loc in t["locations"]}
    missing = set(SAMPLE_CAMERAS) - locations.keys()
    if missing:
        raise ValueError("sample cameras missing: " + str(sorted(missing)))
    # Data documents are indexed by their source tile; select the camera/subject
    # tiles plus a one-tile halo so roads crossing the sample boundary stay present.
    origin = spec["origin"]
    tiles = set()
    for name in SAMPLE_CAMERAS:
        for point in (locations[name]["camera_en"], locations[name]["subject_en"]):
            x = math.floor((point[0] - origin["E"]) / 512)
            y = math.floor((point[1] - origin["N"]) / 512)
            tiles.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    selected = [p for p in paths if any(p.name == f"site_x{x}_y{y}.json" for x, y in tiles)]
    if not selected:
        raise ValueError("fixed risk sample selected no documents")
    return selected


def report_problems(report, expected, lods):
    problems = []
    if report.get("config", {}).get("n") != expected:
        problems.append("selected spline count does not match inventory")
    summary = report.get("summary", {})
    if summary.get("stations_with_terrain", 0) <= 0:
        problems.append("no measured stations")
    measured = summary.get("splines", 0)
    skipped = report.get("skipped_count", 0)
    structures = report.get("structures_not_gated_count", 0)
    if measured + skipped + structures != expected:
        problems.append("measured/excluded/failed coverage does not reconcile")
    for lod in lods:
        row = report.get("by_lod", {}).get(f"lod{lod}", {})
        value = row.get("penetration_m_over_all_stations", {}).get("max")
        if row.get("stations_with_terrain", 0) <= 0 or value is None or not math.isfinite(value):
            problems.append(f"LOD {lod}: missing/nonfinite measurement")
        elif lod == 0 and value > 0.005:
            problems.append(f"LOD 0 penetration {value:.6f} m exceeds 0.005 m")
    # The historic 18 cm clip-boundary stub remains named in the report. Any
    # exception in constructing a spline is a failed check, never an exclusion.
    for row in report.get("skipped", []):
        if row[2] != "no terrain under any station":
            problems.append("spline build failed: " + str(row))
    return problems


def reusable(job, fingerprint, expected, lods):
    if job.get("status") not in ("passed", "failed") or job.get("fingerprint") != fingerprint:
        return False
    try:
        report = Path(job["report"])
        if sha256(report) != job["report_sha256"]:
            return False
        problems = report_problems(read_json(report), expected, lods)
        return problems == job["problems"] and job.get("exit_code") == (0 if not problems else 1)
    except (OSError, ValueError, KeyError, TypeError):
        return False


@contextmanager
def run_lock(path):
    # OS-held lock is released even on interpreter/VM failure; no stale PID lock.
    with Path(path).open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", choices=("sample", "full"), default="sample")
    ap.add_argument("--landscape", type=Path, default=REPO / "data/thanet/out/unreal/landscape_conformed")
    ap.add_argument("--survey", type=Path, default=REPO / "data/thanet/out/unreal/landscape")
    ap.add_argument("--streetscape", type=Path, default=REPO / "data/thanet/out/unreal/streetscape")
    ap.add_argument("--out", type=Path, default=TOOLS.parent / "Saved/Phase1")
    ap.add_argument("--chunk-size", type=int, default=4)
    ap.add_argument("--max-jobs", type=int, default=2, help="0 runs all remaining chunks")
    ap.add_argument("--timeout-s", type=int, default=300)
    ap.add_argument("--lods", default="0,1,2,3")
    args = ap.parse_args()
    if args.chunk_size <= 0 or args.max_jobs < 0 or args.timeout_s <= 0:
        ap.error("chunk-size/timeout must be positive; max-jobs must be nonnegative")
    lods = sorted(set(int(k) for k in args.lods.split(",")))
    if 0 not in lods or any(k < 0 or k > 3 for k in lods):
        ap.error("LODs must include 0 and be in 0..3")
    census, paths = inventory(args.streetscape)
    spec = TOOLS / "ue/render_set.json"
    selected = paths if args.scope == "full" else sample_documents(paths, spec)
    eligible = {r["name"]: r["eligible"] for r in census["documents"]}
    selected = [p for p in selected if eligible[p.name]]
    chunks = [selected[i:i + args.chunk_size] for i in range(0, len(selected), args.chunk_size)]
    import numpy as np
    config = {"scope": args.scope, "chunk_size": args.chunk_size, "lods": lods,
              "documents": [p.name for p in selected], "python": sys.version,
              "numpy": np.__version__, "penetration_gate_m": 0.005,
              "survey": str(args.survey.resolve()), "landscape": str(args.landscape.resolve()),
              "streetscape": str(args.streetscape.resolve())}
    inputs = paths + [spec, Path(__file__), TOOLS / "road_fusion_audit.py"]
    inputs += list((TOOLS / "blender/streetscape").glob("*.py"))
    for directory in (args.landscape, args.survey):
        inputs += [directory / "landscape_manifest.json"]
        inputs += list(directory.glob("hm_*.r16")) + list(directory.glob("clip_*.r8"))
    fingerprint, hashes = content_identity(inputs, config)
    root = args.out.resolve() / args.scope / fingerprint[:20]
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.json"
    with run_lock(root / "run.lock"):
        atomic_json(root / "inputs.json", {"fingerprint": fingerprint, "config": config, "sha256": hashes})
        atomic_json(root / "inventory.json", census)
        state = read_json(state_path) if state_path.exists() else {"jobs": {}}
        state.update({"fingerprint": fingerprint, "scope": args.scope,
                      "phase1_accepted": False, "total_chunks": len(chunks), "config": config})
        ran = 0
        for index, chunk in enumerate(chunks):
            key = f"chunk_{index:03d}"
            expected = sum(eligible[p.name] for p in chunk)
            job = state["jobs"].get(key, {})
            if reusable(job, fingerprint, expected, lods):
                continue
            if args.max_jobs and ran >= args.max_jobs:
                # Invalidated cached outputs must not stay labelled passed.
                state["jobs"][key] = {"status": "pending"}
                continue
            attempt = root / (key + "_" + uuid.uuid4().hex[:8])
            report, log = attempt.with_suffix(".json"), attempt.with_suffix(".log")
            cmd = [sys.executable, str(TOOLS / "road_fusion_audit.py"),
                   "--landscape", str(args.landscape.resolve()), "--survey", str(args.survey.resolve()),
                   "--streetscape", str(args.streetscape.resolve()), "--n", "0",
                   "--lods", ",".join(map(str, lods)), "--gate-m", "0.005", "--out", str(report)]
            for path in chunk:
                cmd += ["--only-doc", path.name]
            job = {"status": "running", "fingerprint": fingerprint, "command": cmd,
                   "documents": [p.name for p in chunk], "expected_splines": expected,
                   "report": str(report), "log": str(log), "started_utc": time.time()}
            state["jobs"][key] = job
            atomic_json(state_path, state)
            print(f"{key}: {len(chunk)} documents, {expected} splines -> {log}", flush=True)
            try:
                with log.open("w", encoding="utf-8") as stream:
                    result = subprocess.run(cmd, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT,
                                            timeout=args.timeout_s, check=False)
                job["exit_code"] = result.returncode
                payload = read_json(report)
                problems = report_problems(payload, expected, lods)
                if result.returncode and not problems:
                    problems.append(f"process exited {result.returncode}")
                job["report_sha256"] = sha256(report)
                job["problems"] = problems
                job["status"] = "failed" if problems else "passed"
                job["structures_excluded"] = payload["structures_not_gated_count"]
                job["skipped"] = payload["skipped"]
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                job.update(status="interrupted", problems=[str(exc)])
            job["elapsed_s"] = round(time.time() - job["started_utc"], 2)
            atomic_json(state_path, state)
            print(f"{key}: {job['status']} in {job['elapsed_s']} s; {job['problems']}", flush=True)
            ran += 1
        # A concurrent source/product update invalidates this entire run. A job
        # cannot certify bytes that changed after its starting fingerprint.
        final_fingerprint, _ = content_identity(inputs, config)
        if final_fingerprint != fingerprint:
            for job in state["jobs"].values():
                job.update(status="interrupted", problems=["inputs changed during QC; rerun"])
        totals = Counter(j["status"] for j in state["jobs"].values())
        state["status"] = ("failed" if totals["failed"] or totals["interrupted"] else
                           "numerical_checks_complete" if totals["passed"] == len(chunks) else "pending")
        state["totals"] = dict(totals)
        state["measurements"] = measurements(state["jobs"].values(), lods)
        state["updated_utc"] = time.time()
        state["remaining_acceptance"] = ["structure heights/clearance", "floating edge treatment",
                                         "junction/crossing continuity", "engine parity and import identity",
                                         "visual inspection at shipped settings"]
        atomic_json(state_path, state)
        atomic_json(args.out / "latest.json", {"state": str(state_path), "status": state["status"]})
        print(json.dumps({"state": str(state_path), "status": state["status"], "totals": dict(totals),
                          "phase1_accepted": False}), flush=True)
        return 1 if state["status"] == "failed" else 0 if state["status"] == "numerical_checks_complete" else 2


if __name__ == "__main__":
    sys.exit(main())
