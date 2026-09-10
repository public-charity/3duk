"""Atomic sparse checkpoints for terrain conformance; no partial product is accepted."""
import os
from pathlib import Path
import sys
import uuid

import numpy as np

from phase1_qc import atomic_json, content_identity, read_json, sha256
sys.path.insert(0, str(Path(__file__).resolve().parent/"blender"))
from streetscape.conform import KEY_NONE


class ConformCheckpoint:
    def __init__(self, directory, inputs, config):
        self.inputs, self.config = inputs, config
        self.fingerprint, hashes = content_identity(inputs, config)
        self.root = Path(directory).resolve()/self.fingerprint[:20]
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root/"state.json"
        atomic_json(self.root/"inputs.json", {"fingerprint": self.fingerprint, "config": config, "sha256": hashes})
        self.previous = None

    def verify_inputs(self):
        if content_identity(self.inputs, self.config)[0] != self.fingerprint:
            raise ValueError("conform inputs changed during processing; checkpoint/product refused")

    def load(self, acc):
        if not self.path.exists():
            return None
        state = read_json(self.path)
        path = (self.root/state["arrays"]).resolve()
        if path.parent != self.root or not path.name.startswith("stamps_"):
            raise ValueError("checkpoint arrays must be inside the checkpoint directory")
        if state["fingerprint"] != self.fingerprint or sha256(path) != state["arrays_sha256"]:
            raise ValueError("stale or altered conform checkpoint")
        with np.load(path, allow_pickle=False) as data:
            idx, key, z, earth = (data[name] for name in ("index", "key", "z", "earth"))
        if (idx.dtype != np.int64 or key.dtype != np.uint16 or z.dtype != np.float32 or
                idx.ndim != 1 or key.shape != idx.shape or z.shape != idx.shape or
                np.any(idx < 0) or np.any(idx >= acc.key.size) or
                np.any(np.diff(idx) <= 0) or not np.isfinite(z).all()):
            raise ValueError("invalid conform checkpoint arrays")
        acc.key.reshape(-1)[idx] = key
        acc.z.reshape(-1)[idx] = z
        acc.stats = state["accumulator_stats"]
        self.previous = path
        result = state["progress"]
        result["earth_all"] = [earth] if earth.size else []
        return result

    def save(self, acc, progress, earth_all):
        self.verify_inputs()
        flat_key, flat_z = acc.key.reshape(-1), acc.z.reshape(-1)
        idx = np.flatnonzero(flat_key != KEY_NONE).astype(np.int64)
        if not np.isfinite(flat_z[idx]).all():
            raise ValueError("nonfinite terrain targets cannot be checkpointed")
        path = self.root/("stamps_"+uuid.uuid4().hex+".npz")
        with path.open("wb") as stream:
            np.savez(stream, index=idx, key=flat_key[idx], z=flat_z[idx],
                     earth=np.concatenate(earth_all) if earth_all else np.empty(0, dtype=np.float32))
            stream.flush()
            os.fsync(stream.fileno())
        state = {"fingerprint": self.fingerprint, "arrays": path.name, "arrays_sha256": sha256(path),
                 "accumulator_stats": acc.stats, "progress": progress, "phase1_accepted": False}
        atomic_json(self.path, state)
        # Retire only our previous complete checkpoint AFTER the new pointer is durable.
        if self.previous is not None:
            try:
                self.previous.unlink(missing_ok=True)
            except OSError:
                pass  # the new checkpoint is durable; delayed cleanup must not lose it
        self.previous = path
        return str(self.path)


def checkpoint_inputs(args, documents, tools):
    source = Path(args.landscape)
    paths = [p for p in source.iterdir() if p.is_file()]
    paths += [Path(p) for p in documents]
    paths += list((Path(tools)/"blender/streetscape").glob("*.py"))
    paths += [Path(tools)/name for name in ("conform_landscape.py", "conform_checkpoint.py", "phase1_qc.py")]
    config = {k: v for k, v in vars(args).items() if k not in ("max_docs", "checkpoint_every", "checkpoint_dir", "report")}
    config.update(documents=[str(Path(p).resolve()) for p in documents], python=sys.version, numpy=np.__version__)
    return paths, config
