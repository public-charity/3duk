"""MeshBuffer and the measurement helpers the seam/marking tests use (geometry.md 5.6).

Vertex attributes ``vs`` (station s), ``vd`` (signed lateral offset from the centreline, + left) and
``vh`` (section height above z_ref at that d) are what make the seam and marking tests measurements
rather than guesses; the bpy bridge and the glTF export drop them.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import numpy as np


@dataclass
class MeshBuffer:
    v: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    f: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.int64))
    uv: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    vn: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    mat: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int32))
    grp: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int32))
    vs: np.ndarray = field(default_factory=lambda: np.zeros(0))
    vd: np.ndarray = field(default_factory=lambda: np.zeros(0))
    vh: np.ndarray = field(default_factory=lambda: np.zeros(0))
    material_names: List[str] = field(default_factory=list)
    group_names: List[str] = field(default_factory=list)
    two_sided: Set[str] = field(default_factory=set)
    _v_chunks: list = field(default_factory=list, repr=False)
    _f_chunks: list = field(default_factory=list, repr=False)

    # -- ids -----------------------------------------------------------------------------------
    def material_id(self, name: str) -> int:
        if name not in self.material_names:
            self.material_names.append(name)
        return self.material_names.index(name)

    def group_id(self, name: str) -> int:
        if name not in self.group_names:
            self.group_names.append(name)
        return self.group_names.index(name)

    # -- append --------------------------------------------------------------------------------
    def append_vertices(self, P, uv, s, d, h) -> int:
        """Append vertices; returns the index of the first one."""
        P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
        n0 = len(self.v)
        self.v = np.vstack([self.v, P]) if n0 else P.copy()
        self.uv = np.vstack([self.uv, np.asarray(uv, dtype=np.float64).reshape(-1, 2)]) if n0 else np.asarray(uv, dtype=np.float64).reshape(-1, 2).copy()
        self.vs = np.concatenate([self.vs, np.asarray(s, dtype=np.float64).ravel()])
        self.vd = np.concatenate([self.vd, np.asarray(d, dtype=np.float64).ravel()])
        self.vh = np.concatenate([self.vh, np.asarray(h, dtype=np.float64).ravel()])
        return n0

    def append_triangles(self, T, mat_id, grp_id) -> None:
        T = np.asarray(T, dtype=np.int64).reshape(-1, 3)
        if len(T) == 0:
            return
        mat_id = np.broadcast_to(np.asarray(mat_id, dtype=np.int32), (len(T),))
        grp_id = np.broadcast_to(np.asarray(grp_id, dtype=np.int32), (len(T),))
        self.f = np.vstack([self.f, T]) if len(self.f) else T.copy()
        self.mat = np.concatenate([self.mat, mat_id])
        self.grp = np.concatenate([self.grp, grp_id])

    def append_polygon(self, ring_idx, mat_id: int, grp_id: int, normal_hint) -> int:
        """Ear-clip the ring (vertex indices) in its best plane (Newell normal) and append; returns tri count."""
        ring_idx = np.asarray(ring_idx, dtype=np.int64)
        if len(ring_idx) < 3:
            return 0
        P = self.v[ring_idx]
        nrm = newell_normal(P)
        if np.linalg.norm(nrm) < 1e-18:
            return 0
        u, w = plane_basis(nrm)
        pts2 = np.stack([P @ u, P @ w], axis=1)
        tris = triangulate_polygon_2d(pts2)
        if len(tris) == 0:
            return 0
        T = ring_idx[tris]
        # orient toward the hint
        a, b, c = self.v[T[:, 0]], self.v[T[:, 1]], self.v[T[:, 2]]
        fn = np.cross(b - a, c - a)
        flip = (fn @ np.asarray(normal_hint, dtype=np.float64)) < 0
        T[flip] = T[flip][:, [0, 2, 1]]
        area = 0.5 * np.linalg.norm(fn, axis=1)
        keep = area >= 1e-10
        self.append_triangles(T[keep], mat_id, grp_id)
        return int(keep.sum())

    def merge(self, other: "MeshBuffer") -> None:
        if len(other.v) == 0:
            return
        n0 = len(self.v)
        mat_map = np.array([self.material_id(n) for n in other.material_names], dtype=np.int32) if other.material_names else np.zeros(0, dtype=np.int32)
        grp_map = np.array([self.group_id(n) for n in other.group_names], dtype=np.int32) if other.group_names else np.zeros(0, dtype=np.int32)
        self.append_vertices(other.v, other.uv, other.vs, other.vd, other.vh)
        if len(other.f):
            self.append_triangles(other.f + n0, mat_map[other.mat], grp_map[other.grp])
        self.two_sided |= set(other.two_sided)

    # -- derived -------------------------------------------------------------------------------
    def face_normals(self) -> np.ndarray:
        a, b, c = self.v[self.f[:, 0]], self.v[self.f[:, 1]], self.v[self.f[:, 2]]
        return np.cross(b - a, c - a)

    def face_areas(self) -> np.ndarray:
        return 0.5 * np.linalg.norm(self.face_normals(), axis=1)

    def compute_normals(self) -> None:
        vn = np.zeros((len(self.v), 3))
        if len(self.f):
            fn = self.face_normals()          # area weighted
            for k in range(3):
                np.add.at(vn, self.f[:, k], fn)
        n = np.linalg.norm(vn, axis=1, keepdims=True)
        n[n == 0] = 1.0
        self.vn = vn / n

    def validate(self) -> List[str]:
        msgs = []
        if len(self.v) and not np.all(np.isfinite(self.v)):
            msgs.append("non-finite vertex coordinates: %d" % int(np.sum(~np.isfinite(self.v).all(axis=1))))
        if len(self.f):
            if self.f.min() < 0 or self.f.max() >= len(self.v):
                msgs.append("triangle index out of range")
            else:
                areas = self.face_areas()
                deg = int(np.sum(areas < 1e-10))
                if deg:
                    msgs.append("%d degenerate triangle(s) (< 1e-10 m^2)" % deg)
                srt = np.sort(self.f, axis=1)
                _, cnt = np.unique(srt, axis=0, return_counts=True)
                dup = int(np.sum(cnt > 1))
                if dup:
                    msgs.append("%d duplicate triangle(s)" % dup)
        if len(self.mat) != len(self.f) or len(self.grp) != len(self.f):
            msgs.append("material/group arrays do not match the triangle count")
        return msgs

    def is_closed_manifold(self, mat_filter: Optional[Set[str]] = None, grp_filter: Optional[Set[str]] = None,
                           tol: float = 1e-9) -> bool:
        """Every edge in exactly two triangles with opposite orientation, after welding coincident vertices."""
        sel = np.ones(len(self.f), dtype=bool)
        if mat_filter is not None:
            ids = [self.material_names.index(m) for m in mat_filter if m in self.material_names]
            sel &= np.isin(self.mat, ids)
        if grp_filter is not None:
            ids = [self.group_names.index(g) for g in grp_filter if g in self.group_names]
            sel &= np.isin(self.grp, ids)
        F = self.f[sel]
        if len(F) == 0:
            return False
        weld = weld_indices(self.v, tol)
        F = weld[F]
        F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 2] != F[:, 0])]
        edges = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
        key_dir = edges[:, 0] * (len(weld) + 1) + edges[:, 1]
        key_und = np.minimum(edges[:, 0], edges[:, 1]) * (len(weld) + 1) + np.maximum(edges[:, 0], edges[:, 1])
        _, cnt = np.unique(key_und, return_counts=True)
        if not np.all(cnt == 2):
            return False
        _, cntd = np.unique(key_dir, return_counts=True)
        return bool(np.all(cntd == 1))

    def stats(self) -> dict:
        per_mat: Dict[str, dict] = {}
        for i, name in enumerate(self.material_names):
            sel = self.mat == i
            if not sel.any():
                continue
            per_mat[name] = {"tris": int(sel.sum()), "verts": int(len(np.unique(self.f[sel])))}
        per_grp: Dict[str, dict] = {}
        for i, name in enumerate(self.group_names):
            sel = self.grp == i
            if not sel.any():
                continue
            per_grp[name] = {"tris": int(sel.sum()), "verts": int(len(np.unique(self.f[sel])))}
        bbox = [[float(x) for x in self.v.min(axis=0)], [float(x) for x in self.v.max(axis=0)]] if len(self.v) else None
        return {"verts": int(len(self.v)), "tris": int(len(self.f)), "bbox": bbox,
                "per_material": per_mat, "per_group": per_grp}

    # -- io ------------------------------------------------------------------------------------
    def save_npz(self, path: str) -> None:
        """Deterministic .npz (fixed zip timestamps, stored, arrays in a fixed order)."""
        save_npz_dict(path, {
            "v": self.v, "f": self.f, "uv": self.uv, "vn": self.vn, "mat": self.mat, "grp": self.grp,
            "vs": self.vs, "vd": self.vd, "vh": self.vh,
            "material_names": np.array(self.material_names, dtype="U64"),
            "group_names": np.array(self.group_names, dtype="U64"),
            "two_sided": np.array(sorted(self.two_sided), dtype="U64"),
        })

    @classmethod
    def load_npz(cls, path: str) -> "MeshBuffer":
        d = np.load(path, allow_pickle=False)
        return cls(v=d["v"], f=d["f"], uv=d["uv"], vn=d["vn"], mat=d["mat"], grp=d["grp"], vs=d["vs"], vd=d["vd"],
                   vh=d["vh"], material_names=[str(x) for x in d["material_names"]],
                   group_names=[str(x) for x in d["group_names"]], two_sided=set(str(x) for x in d["two_sided"]))

    # -- selections ----------------------------------------------------------------------------
    def group_mask_tris(self, prefix: str = "", exact: Optional[str] = None) -> np.ndarray:
        if exact is not None:
            ids = [i for i, n in enumerate(self.group_names) if n == exact]
        else:
            ids = [i for i, n in enumerate(self.group_names) if n.startswith(prefix)]
        return np.isin(self.grp, ids)

    def vertices_of_groups(self, prefix: str = "", exact: Optional[str] = None, exclude_prefix=None) -> np.ndarray:
        """Indices of vertices used by triangles of the named group(s).  ``exclude_prefix`` is one
        prefix or a tuple of them."""
        if exclude_prefix is not None:
            pre = (exclude_prefix,) if isinstance(exclude_prefix, str) else tuple(exclude_prefix)
            ids = [i for i, n in enumerate(self.group_names) if not n.startswith(pre)]
            sel = np.isin(self.grp, ids)
        else:
            sel = self.group_mask_tris(prefix, exact)
        return np.unique(self.f[sel])


def save_npz_dict(path: str, arrays: dict) -> None:
    """np.savez replacement with fixed zip timestamps so two runs give byte-identical files."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, arr in arrays.items():
            bio = io.BytesIO()
            np.lib.format.write_array(bio, np.ascontiguousarray(np.asarray(arr)), allow_pickle=False)
            zi = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            zf.writestr(zi, bio.getvalue())


# --------------------------------------------------------------------------------------------
# geometry helpers (no LAPACK anywhere)
# --------------------------------------------------------------------------------------------

def newell_normal(P: np.ndarray) -> np.ndarray:
    P = np.asarray(P, dtype=np.float64)
    Q = np.roll(P, -1, axis=0)
    n = np.array([
        np.sum((P[:, 1] - Q[:, 1]) * (P[:, 2] + Q[:, 2])),
        np.sum((P[:, 2] - Q[:, 2]) * (P[:, 0] + Q[:, 0])),
        np.sum((P[:, 0] - Q[:, 0]) * (P[:, 1] + Q[:, 1])),
    ])
    return n


def plane_basis(n: np.ndarray):
    n = np.asarray(n, dtype=np.float64)
    n = n / np.linalg.norm(n)
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    w = np.cross(n, u)
    return u, w


def polygon_area_2d(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def triangulate_polygon_2d(pts) -> np.ndarray:
    """Ear clipping of a simple polygon (K, 2) of either orientation -> (K-2, 3) index triples."""
    pts = np.asarray(pts, dtype=np.float64)
    K = len(pts)
    if K < 3:
        return np.zeros((0, 3), dtype=np.int64)
    area = polygon_area_2d(pts)
    sign = 1.0 if area >= 0 else -1.0
    idx = list(range(K))
    tris = []

    def cross(o, a, b):
        return (pts[a, 0] - pts[o, 0]) * (pts[b, 1] - pts[o, 1]) - (pts[a, 1] - pts[o, 1]) * (pts[b, 0] - pts[o, 0])

    def inside(p, a, b, c):
        d1 = cross(a, b, p) * sign
        d2 = cross(b, c, p) * sign
        d3 = cross(c, a, p) * sign
        return d1 >= -1e-14 and d2 >= -1e-14 and d3 >= -1e-14

    guard = 0
    while len(idx) > 3 and guard < 10 * K * K:
        guard += 1
        found = False
        n = len(idx)
        for i in range(n):
            a, b, c = idx[(i - 1) % n], idx[i], idx[(i + 1) % n]
            if cross(a, b, c) * sign <= 1e-14:
                continue
            ok = True
            for j in idx:
                if j in (a, b, c):
                    continue
                if inside(j, a, b, c):
                    ok = False
                    break
            if ok:
                tris.append((a, b, c))
                idx.pop(i)
                found = True
                break
        if not found:
            # degenerate polygon (collinear tail): clip the first vertex anyway
            a, b, c = idx[0], idx[1], idx[2]
            tris.append((a, b, c))
            idx.pop(1)
    if len(idx) == 3:
        tris.append(tuple(idx))
    return np.array(tris, dtype=np.int64).reshape(-1, 3)


def weld_indices(V: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    """Map every vertex to the index of the first vertex within tol (coordinate quantisation)."""
    if len(V) == 0:
        return np.zeros(0, dtype=np.int64)
    q = np.round(V / tol).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    return first[inv.ravel()]


def distinct_positions(V: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    return np.unique(np.round(V / tol).astype(np.int64), axis=0).astype(np.float64) * tol


# --------------------------------------------------------------------------------------------
# measurements for the seam tests (DESIGN.md 5)
# --------------------------------------------------------------------------------------------

# Groups whose vertices are NOT stations of the spline, so every (s, d, h) measurement steps over
# them: painted strips carry interpolated dash ends, and junction patches and kerb corners are not
# swept along the spline at all (SCHEMA.md 4.18).  The overlap and station rules are stated in terms
# of the swept ribbon, and this is what "the swept ribbon" means in code.
NON_STATION_PREFIXES = ("marking:", "junction:", "corner_")


def station_values(buf: MeshBuffer, exclude_prefix=NON_STATION_PREFIXES) -> np.ndarray:
    vi = buf.vertices_of_groups(exclude_prefix=exclude_prefix)
    return np.unique(buf.vs[vi])


def measure_lateral_overlap(road: MeshBuffer, edge: MeshBuffer, side: int, tuck_depth: float = 0.03) -> dict:
    """Per station: road_extent = max(side*vd of road verts at s, marking groups excluded);
    kerb_face = min(side*vd of the edge 'kerb'-group verts at s above the tuck rows (the lowest kerb row
    at that station is the A/B underside at -tuck_depth; everything above it is the visible block).
    Returns {'min_m', 'max_m', 'per_station', 'stations'}."""
    rv = road.vertices_of_groups(exclude_prefix=NON_STATION_PREFIXES)
    stations = np.unique(road.vs[rv])
    kv = edge.vertices_of_groups(exact="kerb")
    per = np.full(len(stations), np.nan)
    for i, s in enumerate(stations):
        r_sel = rv[np.abs(road.vs[rv] - s) <= 1e-9]
        k_sel = kv[np.abs(edge.vs[kv] - s) <= 1e-9]
        if len(r_sel) == 0 or len(k_sel) == 0:
            continue
        d_road = side * road.vd[r_sel]
        road_extent = float(np.max(d_road))                       # the skirt row
        levels = np.unique(np.round(d_road, 9))
        edge_d = levels[-2] if len(levels) >= 2 else levels[-1]   # the road-edge row (h = h0)
        h0 = float(np.min(road.vh[r_sel][np.abs(d_road - edge_d) <= 1e-9]))
        vis = k_sel[edge.vh[k_sel] > h0 - tuck_depth + 1e-9]      # the kerb block above its tuck rows
        if len(vis) == 0:
            continue
        kerb_face = float(np.min(side * edge.vd[vis]))
        per[i] = road_extent - kerb_face
    ok = np.isfinite(per)
    return {"min_m": float(np.min(per[ok])) if ok.any() else float("nan"),
            "max_m": float(np.max(per[ok])) if ok.any() else float("nan"),
            "per_station": per, "stations": stations}


def coincident_xy_pairs(a: MeshBuffer, b: MeshBuffer, d_band, side: int, tol_xy: float = 1e-6, tol_z: float = 1e-6,
                        dedup: float = 1e-9) -> int:
    """Number of (position of a, position of b) pairs with |dxy| <= tol_xy and |dz| > tol_z, both with
    side*vd inside d_band (inclusive), positions deduplicated at `dedup` first."""
    lo, hi = d_band

    def positions(buf):
        sel = (side * buf.vd >= lo - 1e-12) & (side * buf.vd <= hi + 1e-12)
        return distinct_positions(buf.v[sel], dedup)

    A = positions(a)
    B = positions(b)
    if len(A) == 0 or len(B) == 0:
        return 0
    count = 0
    # bucket B by rounded xy
    key = np.round(B[:, :2] / tol_xy).astype(np.int64)
    buckets: Dict[tuple, list] = {}
    for i, k in enumerate(map(tuple, key)):
        buckets.setdefault(k, []).append(i)
    ka = np.round(A[:, :2] / tol_xy).astype(np.int64)
    for i in range(len(A)):
        kx, ky = int(ka[i, 0]), int(ka[i, 1])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in buckets.get((kx + dx, ky + dy), []):
                    if np.hypot(A[i, 0] - B[j, 0], A[i, 1] - B[j, 1]) <= tol_xy and abs(A[i, 2] - B[j, 2]) > tol_z:
                        count += 1
    return count


def surface_height_at(buf: MeshBuffer, s: float, d: float, group_prefix_exclude=NON_STATION_PREFIXES) -> float:
    """Height vh of the (non-marking) mesh at parameter (s, d): barycentric on the triangle whose
    (vs, vd) footprint contains the point.  NaN when none does."""
    pre = (group_prefix_exclude,) if isinstance(group_prefix_exclude, str) else tuple(group_prefix_exclude)
    ids = [i for i, n in enumerate(buf.group_names) if not n.startswith(pre)]
    sel = np.isin(buf.grp, ids)
    F = buf.f[sel]
    S0 = buf.vs[F]
    D0 = buf.vd[F]
    near = (S0.min(axis=1) <= s + 1e-9) & (S0.max(axis=1) >= s - 1e-9) & (D0.min(axis=1) <= d + 1e-9) & (D0.max(axis=1) >= d - 1e-9)
    for tri, ss, dd in zip(F[near], S0[near], D0[near]):
        x1, y1, x2, y2, x3, y3 = ss[0], dd[0], ss[1], dd[1], ss[2], dd[2]
        det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(det) < 1e-18:
            continue
        l1 = ((y2 - y3) * (s - x3) + (x3 - x2) * (d - y3)) / det
        l2 = ((y3 - y1) * (s - x3) + (x1 - x3) * (d - y3)) / det
        l3 = 1.0 - l1 - l2
        if min(l1, l2, l3) >= -1e-9:
            return float(l1 * buf.vh[tri[0]] + l2 * buf.vh[tri[1]] + l3 * buf.vh[tri[2]])
    return float("nan")
