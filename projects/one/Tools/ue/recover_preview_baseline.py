"""Restore or verify only baseline IDs affected by the former destructive preview importer.

Explicit candidate manifests identify IDs; geometry comes exclusively from unchanged
production source JSON. Recovery saves only newly created actor packages. Never use
the ordinary replace-by-ID importer here.
"""
import json
import os
from pathlib import Path
import sys

import unreal
import ue_common as uc
from content_guard import snapshot, differences

NAME = "recover_preview_baseline"


def main(argv):
    opts = uc.parse_args(argv, flags=("restore",), options={"candidates": "", "out": "", "report": ""})
    if not opts["candidates"] or not opts["out"]:
        uc.fail(NAME, "--candidates and --out are required")
    root = Path(opts["out"])
    root.mkdir(parents=True, exist_ok=True)
    source = Path(uc.data_dir())/"streetscape"
    wanted = {}
    import hashlib
    for directory in opts["candidates"].split(","):
        directory = Path(directory)
        manifest = json.loads((directory/"candidate_manifest.json").read_text())
        for name, expected in manifest["source_documents"].items():
            if hashlib.sha256((source/name).read_bytes()).hexdigest() != expected:
                uc.fail(NAME, "baseline source changed: "+name)
            doc = json.loads((directory/name).read_text())
            wanted.setdefault(name, set()).update(s["id"] for s in doc["splines"])
    content = Path(__file__).resolve().parents[2]/"Content"
    before = snapshot(content)
    report = {"mode": "restore" if opts["restore"] else "verify", "status": "running", "documents": []}
    report_path = Path(opts["report"] or root/"recovery.json")

    def checkpoint():
        temp = report_path.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2))
        os.replace(str(temp), str(report_path))

    checkpoint()
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level("/Game/Thanet/Maps/Thanet"):
        uc.fail(NAME, "load failed")
    lib = unreal.StreetscapeEditorLibrary
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for name, ids in sorted(wanted.items()):
        doc = json.loads((source/name).read_text())
        doc["splines"] = [s for s in doc["splines"] if s["id"] in ids]
        doc["junctions"] = []
        if {s["id"] for s in doc["splines"]} != ids:
            uc.fail(NAME, "incomplete baseline selection: "+name)
        if any(s.get("elevation_profile") or s.get("junction_start") or s.get("junction_end") for s in doc["splines"]):
            uc.fail(NAME, "recovery requires original non-junction baseline")
        path = root/name
        path.write_text(json.dumps(doc, indent=2))
        points = [p for s in doc["splines"] for p in s["points"]]
        lo = [min(p[k] for p in points) for k in ("x", "y")]
        hi = [max(p[k] for p in points) for k in ("x", "y")]
        lib.load_region(unreal.Vector((lo[0]+hi[0])*50, -(lo[1]+hi[1])*50, 0),
                        max(hi[0]-lo[0], hi[1]-lo[1])*50+10000)
        created = lib.restore_missing_baseline_json(str(path)) if opts["restore"] else 0
        if created < 0:
            uc.fail(NAME, "targeted baseline restoration failed: "+name)
        actors = [a for a in eas.get_all_level_actors() if isinstance(a, unreal.StreetscapeActor)]
        seen = [str(a.get_editor_property("street_id")) for a in actors]
        counts = {sid: seen.count(sid) for sid in sorted(ids)}
        if any(n != 1 for n in counts.values()):
            uc.fail(NAME, "baseline identity mismatch: "+str(counts))
        stats = {sid: json.loads(lib.actor_stats_json(sid)) for sid in sorted(ids)}
        report["documents"].append({"source": str(source/name), "source_sha256": hashlib.sha256((source/name).read_bytes()).hexdigest(),
                                    "created": created, "counts": counts, "stats": stats})
        checkpoint()
    report["content_changes"] = differences(before, snapshot(content))
    if report["content_changes"]["deleted"] or report["content_changes"]["modified"]:
        checkpoint()
        uc.fail(NAME, "recovery changed pre-existing content")
    if not opts["restore"] and report["content_changes"]["added"]:
        uc.fail(NAME, "verification wrote content")
    report["status"] = "complete"
    checkpoint()
    uc.report(NAME, {"restored": sum(d["created"] for d in report["documents"]),
                     "verified_ids": sum(len(d["counts"]) for d in report["documents"]),
                     "report": str(report_path), "content_changes": report["content_changes"]})


if __name__ == "__main__":
    main(sys.argv)
