#!/usr/bin/env python3
"""Bounded, resumable structure candidate screening. No production changes or acceptance.

Every structure is accounted for, including unresolved deck fits and passages.
Default four rail candidates per invocation; repeat to resume, or --max-jobs 0.
Each subprocess has a deadline and its own immutable attempt directory.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from phase1_qc import atomic_json, content_identity, read_json, run_lock, sha256

REPO = TOOLS.parents[2]


def reusable(job, fingerprint):
    if job.get("fingerprint") != fingerprint or job.get("status") not in ("candidate", "needs_approach_review"):
        return False
    try:
        if sha256(job["log"]) != job["log_sha256"]:
            return False
        if job["status"] == "candidate":
            path = Path(job["manifest"])
            if sha256(path) != job["manifest_sha256"]:
                return False
            doc = read_json(path)
            if not doc.get("candidate_documents") or doc.get("production_accepted") is not False:
                return False
            return all(sha256(path.parent/n) == digest for n, digest in doc["candidate_documents"].items())
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def candidate_conflicts(jobs):
    """Separate candidates are not automatically safe to combine."""
    owners = defaultdict(list)
    for gid, job in jobs.items():
        if job["status"] == "candidate":
            for row in read_json(job["manifest"])["measured"]:
                owners[row["id"]].append(gid)
    return {sid: ids for sid, ids in owners.items() if len(ids) > 1}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inventory", type=Path, default=TOOLS.parent/"Saved/Phase1/structures_baseline.json")
    ap.add_argument("--fits", type=Path, default=TOOLS.parent/"Saved/Phase1/deck_candidates.json")
    ap.add_argument("--out", type=Path, default=TOOLS.parent/"Saved/Phase1/structures")
    ap.add_argument("--max-jobs", type=int, default=4)
    ap.add_argument("--timeout-s", type=int, default=60)
    ap.add_argument("--connected", action="store_true", help="screen bridge networks across short links and tile stubs")
    args = ap.parse_args()
    if args.max_jobs < 0 or args.timeout_s <= 0:
        ap.error("max-jobs must be nonnegative and timeout positive")
    inv, fits = read_json(args.inventory), read_json(args.fits)
    if fits["source_sha256"] != sha256(args.inventory):
        raise ValueError("fits do not match inventory")
    source = Path(inv["source"]["streetscape"])
    dependencies = inv["source"].get("dependency_sha256")
    if not dependencies:
        raise ValueError("regenerate inventory with pixel hashes")
    paths = [Path(p) for p in dependencies]
    paths += [source/n for n in inv["source"]["document_sha256"]]
    paths += [args.inventory, args.fits, Path(__file__), TOOLS/"phase1_qc.py",
              TOOLS/"diag/bridge_profile_candidate.py", TOOLS/"diag/structure_inventory.py",
              TOOLS/"diag/bridge_alignment.py"]
    import numpy as np
    config = {"python": sys.version, "numpy": np.__version__, "kind": "rail", "timeout_s": args.timeout_s,
              "connected": args.connected}
    fingerprint, hashes = content_identity(paths, config)
    for path, digest in dependencies.items():
        if hashes[str(Path(path).resolve())] != digest:
            raise ValueError("inventory dependency changed: " + path)
    for name, digest in inv["source"]["document_sha256"].items():
        if hashes[str((source/name).resolve())] != digest:
            raise ValueError("inventory streetscape changed: " + name)
    groups = {g["id"]: g for g in inv["groups"]}
    fitted = {g["id"]: g for g in fits["groups"]}
    if not groups or groups.keys() != fitted.keys():
        raise ValueError("empty or incomplete structure coverage")
    root = args.out.resolve()/fingerprint[:20]
    root.mkdir(parents=True, exist_ok=True)
    state_path = root/"state.json"
    with run_lock(root/"run.lock"):
        atomic_json(root/"inputs.json", {"fingerprint": fingerprint, "config": config, "sha256": hashes})
        state = read_json(state_path) if state_path.exists() else {"jobs": {}}
        state.update(fingerprint=fingerprint, phase1_accepted=False, total_groups=len(groups))
        ran = 0
        for gid, group in groups.items():
            fit = fitted[gid]
            if fit["status"] != "deck_candidate_requires_approaches" or not gid.startswith("rail:"):
                state["jobs"][gid] = {"status": "needs_road_approach_model" if fit["status"] == "deck_candidate_requires_approaches" else fit["status"],
                                      "contexts": group["contexts"], "problems": fit.get("problems", [])}
                if group["kind"] == "tunnel":
                    state["jobs"][gid].update(status="needs_context_model", problems=["model floor/cover according to original OSM context; do not fit first return"])
                continue
            job = state["jobs"].get(gid, {})
            if reusable(job, fingerprint):
                continue
            if args.max_jobs and ran >= args.max_jobs:
                state["jobs"][gid] = {"status": "pending"}
                continue
            attempt = root/(gid.replace(":", "_")+"_"+uuid.uuid4().hex[:8])
            attempt.mkdir()
            log = attempt/"run.log"
            cmd = [sys.executable, str(TOOLS/"diag/bridge_profile_candidate.py"), "--inventory", str(args.inventory.resolve()),
                   "--fits", str(args.fits.resolve()), "--group", gid, "--out", str(attempt)]
            if args.connected:
                cmd.append("--connected")
            job = {"status": "running", "fingerprint": fingerprint, "log": str(log), "started_utc": time.time(), "command": cmd}
            state["jobs"][gid] = job
            atomic_json(state_path, state)
            try:
                with log.open("w", encoding="utf-8") as stream:
                    proc = subprocess.run(cmd, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT, timeout=args.timeout_s)
                job["exit_code"] = proc.returncode
                if proc.returncode:
                    last = log.read_text(encoding="utf-8").strip().splitlines()[-1]
                    job.update(status="needs_approach_review" if last.startswith("ValueError:") else "failed", problems=[last])
                else:
                    path = attempt/"candidate_manifest.json"
                    manifest = read_json(path)
                    covered = [r["group"] for r in manifest["groups"]]
                    if gid not in covered or any(k not in groups for k in covered) or not manifest["measured"]:
                        raise ValueError("candidate returned incomplete group")
                    job.update(status="candidate", manifest=str(path), manifest_sha256=sha256(path), covered_groups=covered, problems=[])
                job["log_sha256"] = sha256(log)
            except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as exc:
                job.update(status="interrupted", problems=[str(exc)])
            job["elapsed_s"] = round(time.time()-job["started_utc"], 2)
            atomic_json(state_path, state)
            print(gid, job["status"], job["elapsed_s"], job["problems"], flush=True)
            ran += 1
        if content_identity(paths, config)[0] != fingerprint:
            for job in state["jobs"].values():
                job.update(status="interrupted", problems=["inputs changed during screening"])
        state["totals"] = dict(Counter(j["status"] for j in state["jobs"].values()))
        state["candidate_conflicts"] = candidate_conflicts(state["jobs"])
        state["updated_utc"] = time.time()
        atomic_json(state_path, state)
        atomic_json(args.out/"latest.json", {"state": str(state_path), "phase1_accepted": False})
        print(json.dumps({"state": str(state_path), "totals": state["totals"], "candidate_conflicts": state["candidate_conflicts"]}, indent=2))
        return 1 if any(s in state["totals"] for s in ("failed", "interrupted")) else 2 if "pending" in state["totals"] else 0


if __name__ == "__main__":
    sys.exit(main())
