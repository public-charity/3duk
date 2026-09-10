"""Validate and apply a small model candidate to the current headless world, without saving."""
import hashlib
import json
from pathlib import Path


def read_candidate(directory):
    directory = Path(directory).resolve()
    path = directory / "candidate_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("scope") != "delta" or not manifest.get("candidate_documents"):
        raise ValueError("preview requires a nonempty delta candidate manifest")
    files, ids = [], []
    for name, expected_hash in manifest["candidate_documents"].items():
        doc_path = (directory / name).resolve()
        if doc_path.parent != directory or doc_path.suffix != ".json":
            raise ValueError("candidate document must be directly inside candidate directory")
        if hashlib.sha256(doc_path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("candidate document changed: " + name)
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        ids.extend(s["id"] for s in doc["splines"])
        if doc.get("junctions") or any(s.get("junction_start") or s.get("junction_end") for s in doc["splines"]):
            raise ValueError("delta preview currently requires splines without junction ownership")
        files.append((str(doc_path), len(doc["splines"])))
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("empty or duplicate candidate IDs")
    return {"manifest": str(path), "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "documents": manifest["candidate_documents"], "ids": sorted(ids), "saved": False}, files


def apply_candidate(directory):
    import unreal
    record, files = read_candidate(directory)
    lib = unreal.StreetscapeEditorLibrary
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    def loaded_ids():
        return [str(a.get_editor_property("street_id")) for a in eas.get_all_level_actors()
                if isinstance(a, unreal.StreetscapeActor)]

    def loaded_paths():
        return sorted((str(a.get_editor_property("street_id")), str(a.get_path_name()))
                      for a in eas.get_all_level_actors() if isinstance(a, unreal.StreetscapeActor))

    before = loaded_ids()
    before_paths = loaded_paths()
    for sid in record["ids"]:
        if before.count(sid) != 1:
            raise ValueError("preview requires one loaded actor: %s has %d" % (sid, before.count(sid)))
    for path, expected in files:
        count = lib.preview_elevation_json(path)
        if count != expected:
            raise ValueError("candidate import count mismatch: " + path)
    after = loaded_ids()
    if sorted(before) != sorted(after):
        raise ValueError("candidate changed actor census")
    if loaded_paths() != before_paths:
        raise ValueError("candidate replaced an actor instead of updating it in memory")
    record["actor_paths_unchanged"] = True
    record["actor_stats"] = {sid: json.loads(lib.actor_stats_json(sid)) for sid in record["ids"]}
    return record
