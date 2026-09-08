"""Integer-hash noise shared by the hedge renderer and the tests (DESIGN.md 3.8).

Everything here is uint32 arithmetic so the C++ port reproduces it bit for bit:

  lowbias32(x): x ^= x >> 16; x *= 0x7feb352d; x ^= x >> 15; x *= 0x846ca68b; x ^= x >> 16
  unit_noise(i, seed) = lowbias32(uint32(i) * 0x9E3779B1 ^ lowbias32(uint32(seed))) / 2^32 * 2 - 1   in [-1, 1)
  lattice(ix, iy, iz, seed) = lowbias32(ix * 0x9E3779B1 ^ lowbias32(iy * 0x85EBCA77 ^ lowbias32(iz * 0xC2B2AE3D ^ seed))) / 2^32 * 2 - 1
  value_noise3 = trilinear smoothstep interpolation of lattice values
  fbm3(q) = (v(q) + 0.5 * v(2q + 17.3)) / 1.5   in [-1, 1]

Known answers (SCHEMA.md 9.3): lowbias32(0) = 0, lowbias32(1) = 0x688990c0, lowbias32(2) = 0xd1132181,
lowbias32(0xdeadbeef) = 0xe628c683; unit_noise(0..4, 7) = -0.33847302, 0.94551079, -0.62749659,
0.96820159, 0.64059920.
"""
from __future__ import annotations

import numpy as np

_U32 = np.uint32
_GOLD = _U32(0x9E3779B1)
_K2 = _U32(0x85EBCA77)
_K3 = _U32(0xC2B2AE3D)
_M1 = _U32(0x7FEB352D)
_M2 = _U32(0x846CA68B)
_TWO32 = 4294967296.0


def _u32(x) -> np.ndarray:
    """Any integer array/scalar -> uint32 array (two's complement wrap, like a C cast)."""
    a = np.asarray(x)
    if a.dtype.kind == "f":
        a = np.floor(a).astype(np.int64)
    return a.astype(np.int64).astype(_U32, copy=False) if a.dtype != _U32 else a


def lowbias32(x) -> np.ndarray:
    """The lowbias32 integer hash (Chris Wellons), vectorised over uint32."""
    with np.errstate(over="ignore"):
        x = _u32(x)
        x = x ^ (x >> _U32(16))
        x = x * _M1
        x = x ^ (x >> _U32(15))
        x = x * _M2
        x = x ^ (x >> _U32(16))
    return x


def _to_unit(h: np.ndarray) -> np.ndarray:
    return h.astype(np.float64) / _TWO32 * 2.0 - 1.0


def unit_noise(i, seed: int) -> np.ndarray:
    """Hash of an integer index sequence -> float64 in [-1, 1)."""
    with np.errstate(over="ignore"):
        h = lowbias32(_u32(i) * _GOLD ^ lowbias32(_u32(seed)))
    return _to_unit(h)


def unit_noise01(i, seed: int) -> np.ndarray:
    """[0, 1) variant: (unit_noise + 1) / 2."""
    return (unit_noise(i, seed) + 1.0) * 0.5


def lattice(ix, iy, iz, seed: int) -> np.ndarray:
    """Lattice value in [-1, 1) at integer lattice coordinates."""
    with np.errstate(over="ignore"):
        s = _u32(seed)
        h = lowbias32(_u32(ix) * _GOLD ^ lowbias32(_u32(iy) * _K2 ^ lowbias32(_u32(iz) * _K3 ^ s)))
    return _to_unit(h)


def _smoothstep(t: np.ndarray) -> np.ndarray:
    return t * t * (3.0 - 2.0 * t)


def value_noise3(p, seed: int) -> np.ndarray:
    """Trilinear smoothstep interpolation of lattice values; p is (N, 3) float."""
    p = np.asarray(p, dtype=np.float64)
    if p.ndim == 1:
        p = p[None, :]
    p0 = np.floor(p)
    f = _smoothstep(p - p0)
    i0 = p0.astype(np.int64)
    ix, iy, iz = i0[:, 0], i0[:, 1], i0[:, 2]
    fx, fy, fz = f[:, 0], f[:, 1], f[:, 2]
    c000 = lattice(ix, iy, iz, seed)
    c100 = lattice(ix + 1, iy, iz, seed)
    c010 = lattice(ix, iy + 1, iz, seed)
    c110 = lattice(ix + 1, iy + 1, iz, seed)
    c001 = lattice(ix, iy, iz + 1, seed)
    c101 = lattice(ix + 1, iy, iz + 1, seed)
    c011 = lattice(ix, iy + 1, iz + 1, seed)
    c111 = lattice(ix + 1, iy + 1, iz + 1, seed)
    x00 = c000 + (c100 - c000) * fx
    x10 = c010 + (c110 - c010) * fx
    x01 = c001 + (c101 - c001) * fx
    x11 = c011 + (c111 - c011) * fx
    y0 = x00 + (x10 - x00) * fy
    y1 = x01 + (x11 - x01) * fy
    return y0 + (y1 - y0) * fz


def fbm3(p, seed: int) -> np.ndarray:
    """Two-octave normalised value noise in [-1, 1]."""
    p = np.asarray(p, dtype=np.float64)
    if p.ndim == 1:
        p = p[None, :]
    return (value_noise3(p, seed) + 0.5 * value_noise3(2.0 * p + 17.3, seed)) / 1.5
