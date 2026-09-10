"""Exercise one real document's unsaved edit/export/junction-refresh path.

Requires all source actors, preserves their identities, restores the edited definition,
and hashes all saved Content on both success and failure. Never imports or saves actors.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import unreal
import ue_common as uc
from content_guard import snapshot, require_unchanged

NAME = "diag_document_roundtrip"


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return round(value, 6) if isinstance(value, float) else value


def main(argv):
    opts = uc.parse_args(argv, options={"source": "site_x1_y12.json", "out": ""})
    if not opts["out"]:
        uc.fail(NAME, "--out required")
    root = Path(opts["out"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = (Path(uc.data_dir()) / "streetscape" / opts["source"]).resolve()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    doc = json.loads(source.read_text())
    ids = {s["id"] for s in doc["splines"]}
    content = Path(__file__).resolve().parents[2] / "Content"
    before = snapshot(content)
    report = {"status": "running", "source": str(source), "source_sha256": source_hash, "steps": []}

    def checkpoint():
        temp = root / "report.tmp"
        temp.write_text(json.dumps(report, indent=2))
        os.replace(str(temp), str(root / "report.json"))

    lib = unreal.StreetscapeEditorLibrary
    edited = None
    restore_point = None

    def restore():
        if restore_point is None:
            return
        index, x = restore_point
        definition = edited.get_editor_property("def")
        points = list(definition.get_editor_property("points"))
        points[index].set_editor_property("x", x)
        definition.set_editor_property("points", points)
        edited.set_editor_property("def", definition)
        edited.sync_component_from_def()
        if lib.refresh_document_junctions(str(source)) != len(ids):
            raise ValueError("restoration refresh failed")
    checkpoint()
    try:
        if not unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level("/Game/Thanet/Maps/Thanet"):
            raise ValueError("load failed")
        points = [p for s in doc["splines"] for p in s["points"]]
        lo = [min(p[k] for p in points) for k in ("x", "y")]
        hi = [max(p[k] for p in points) for k in ("x", "y")]
        lib.load_region(unreal.Vector((lo[0]+hi[0])*50, -(lo[1]+hi[1])*50, 0),
                        max(hi[0]-lo[0], hi[1]-lo[1])*50+20000)
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors = [a for a in eas.get_all_level_actors() if isinstance(a, unreal.StreetscapeActor)
                  and str(a.get_editor_property("street_id")) in ids]
        by_id = {str(a.get_editor_property("street_id")): a for a in actors}
        if len(actors) != len(ids) or set(by_id) != ids:
            raise ValueError("source IDs not loaded exactly once")
        paths_before = {sid: a.get_path_name() for sid, a in by_id.items()}
        baseline_path = root / "baseline.json"
        if not lib.export_document_json(str(source), str(baseline_path)):
            raise ValueError("baseline export failed")
        baseline = json.loads(baseline_path.read_text())
        if canonical(baseline) != canonical(doc):
            raise ValueError("loaded baseline differs from complete source document")
        report["steps"].append("baseline complete source roundtrip")
        report["actors"] = len(actors)
        report["junctions"] = len(doc["junctions"])
        checkpoint()
        def junction_stats():
            return {sid: {k: a.get_editor_property("junction_stats").get_editor_property(k)
                          for k in ("owned", "built", "skipped", "patch_area_m2", "patch_verts", "patch_tris")}
                    for sid, a in by_id.items()}

        stats_before = junction_stats()
        owners = [sid for sid, stats in stats_before.items() if stats["owned"]]
        if not owners:
            raise ValueError("no built junction owner")
        owner_id = owners[0]
        junction = next(j for j in doc["junctions"] if any(e["spline_id"] == owner_id for e in j["ends"]))
        arm = next(e for e in junction["ends"] if e["spline_id"] != owner_id)
        arm_id = arm["spline_id"]
        edited = by_id[arm_id].get_editor_property("spline")
        changed = edited.get_editor_property("def")
        changed_points = list(changed.get_editor_property("points"))
        index = min(1, len(changed_points)-1) if arm["end"] == "start" else max(0, len(changed_points)-2)
        old_x = changed_points[index].get_editor_property("x")
        restore_point = (index, old_x)
        changed_points[index].set_editor_property("x", old_x+0.15)
        changed.set_editor_property("points", changed_points)
        edited.set_editor_property("def", changed)
        edited.sync_component_from_def()
        if lib.refresh_document_junctions(str(source)) != len(ids):
            raise ValueError("edited document refresh failed")
        stats_after = junction_stats()
        if any(stats["built"] != stats["owned"] or stats["skipped"] for stats in stats_after.values()):
            raise ValueError("junction build incomplete after edit")
        area_delta = stats_after[owner_id]["patch_area_m2"]-stats_before[owner_id]["patch_area_m2"]
        if abs(area_delta) < 1e-8:
            raise ValueError("owner patch did not respond to edited non-owner arm")
        edited_path = root / "edited.json"
        if not lib.export_document_json(str(source), str(edited_path)):
            raise ValueError("edited export failed")
        exported = json.loads(edited_path.read_text())
        if canonical(exported["junctions"]) != canonical(doc["junctions"]):
            raise ValueError("edited export lost source junctions")
        report["edit"] = {"spline": arm_id, "point": index, "delta_x_m": 0.15,
                          "owner": owner_id, "patch_area_change_m2": area_delta}
        report["junction_stats"] = {"before": stats_before, "edited": stats_after}
        report["steps"].append("edited arm reached owner and exported with all junctions")
        checkpoint()
        restore()
        restore_point = None
        restored_path = root / "restored.json"
        if not lib.export_document_json(str(source), str(restored_path)):
            raise ValueError("restored export failed")
        if canonical(json.loads(restored_path.read_text())) != canonical(baseline):
            raise ValueError("restored document differs from baseline")
        if junction_stats() != stats_before:
            raise ValueError("restored junction geometry differs from baseline")
        if paths_before != {sid: a.get_path_name() for sid, a in by_id.items()}:
            raise ValueError("actor identity changed")
        report["steps"].append("restored exact baseline and retained actor paths")
        report["status"] = "complete"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        try:
            restore()
        finally:
            report["content_integrity"] = require_unchanged(before, snapshot(content))
            if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
                raise ValueError("source changed during diagnostic")
            checkpoint()
    uc.report(NAME, {"report": str(root / "report.json"), "status": report["status"],
                     "content_integrity": report["content_integrity"]})


if __name__ == "__main__":
    main(sys.argv)
