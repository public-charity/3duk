"""Byte-level guard for render-only operations on saved project content."""
import hashlib
from pathlib import Path


def snapshot(root):
    return {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def differences(before, after):
    return {"deleted": sorted(before.keys()-after.keys()), "added": sorted(after.keys()-before.keys()),
            "modified": sorted(p for p in before.keys() & after.keys() if before[p] != after[p])}


def require_unchanged(before, after):
    changed = differences(before, after)
    if any(changed.values()):
        raise ValueError("render modified saved Content files: " + str(changed))
    digest = hashlib.sha256(str(sorted(after.items())).encode()).hexdigest()
    return {"unchanged": True, "files": len(after), "sha256": digest}
