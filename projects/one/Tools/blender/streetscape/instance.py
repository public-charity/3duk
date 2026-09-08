"""Instance records (posts, sleepers, leaf cards): transform lists, never merged into a MeshBuffer
(DESIGN.md 4; geometry.md 5.12).  The transform is a (4, 4) matrix in document-local metres whose
columns are (t_h, n, b, p): local X along the path, local Y along the banked left normal, local Z up
the banked b, origin p.  ``size`` = (extent along t_h, extent along n, extent along b); boxes span
[-sx/2, sx/2] x [-sy/2, sy/2] x [0, sz] in that local frame (origin at the bottom centre).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Instance:
    kind: str
    transform: np.ndarray
    size: tuple
    material: str
    spline_id: str
    side: int

    def to_json(self) -> dict:
        return {"kind": self.kind, "transform": [[float(x) for x in row] for row in self.transform],
                "size": [float(x) for x in self.size], "material": self.material,
                "spline_id": self.spline_id, "side": int(self.side)}

    @property
    def position(self) -> np.ndarray:
        return self.transform[:3, 3]


def make_transform(t_h, n, b, p) -> np.ndarray:
    M = np.eye(4)
    M[:3, 0] = t_h
    M[:3, 1] = n
    M[:3, 2] = b
    M[:3, 3] = p
    return M


def box_mesh(M: np.ndarray, size):
    """(8, 3) corners and (12, 3) triangles (outward) of an instance box, for merged mode / bridges."""
    sx, sy, sz = size
    c = np.array([[-sx / 2, -sy / 2, 0.0], [sx / 2, -sy / 2, 0.0], [sx / 2, sy / 2, 0.0], [-sx / 2, sy / 2, 0.0],
                  [-sx / 2, -sy / 2, sz], [sx / 2, -sy / 2, sz], [sx / 2, sy / 2, sz], [-sx / 2, sy / 2, sz]])
    P = (M[:3, :3] @ c.T).T + M[:3, 3]
    F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], dtype=np.int64)
    return P, F
