"""Dataclasses for every object of the Streetscape interchange schema 1.0.0 and the resolution
rules that turn profiles + segments into per-side timelines (SCHEMA.md 4, 5; geometry.md 5.2).

Every class carries a SPEC table (field -> (type spec, required, default)) that ``from_dict`` uses
to convert AND validate: unknown non-underscore keys, wrong types, enum values and ranges raise
``SchemaError`` with the JSON path, so ``io_json.validate_structure`` is this file's SPEC tables
applied to a document (no third-party JSON-schema package; SCHEMA.md 8).

Nothing here samples terrain or builds geometry.  ``resolve_road`` / ``resolve_side`` need the arc
length L (known once the dense curve exists) and return timelines; ``SideTimeline.evaluate(s)`` gives
the per-station ``SideSpec`` that BOTH Renderer B and Renderer C read.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields as dc_fields
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

FRAME_CONST = "local-metres, X east, Y north, Z up"
MATERIAL_NAMES = (
    "tarmac", "white_paint", "yellow_paint", "concrete_kerb", "paving_slab", "grass", "gravel",
    "brick_red", "coping_concrete", "chain_link", "post_steel", "steel_painted_black", "wood_fence",
    "privet_leaf", "ballast", "sleeper_concrete", "rail_steel", "stone_flint", "concrete_wall",
    "massing_grey",
)
BARRIER_TYPES = ("brick_wall", "stone_wall", "concrete_wall", "retaining_wall", "chain_link",
                 "wood_fence", "railing", "guard_rail", "none")
WALL_TYPES = ("brick_wall", "stone_wall", "concrete_wall", "retaining_wall")
FENCE_TYPES = ("chain_link", "wood_fence")
RAILING_TYPES = ("railing", "guard_rail")

LEFT, RIGHT = 1, -1
SIDE_NAME = {LEFT: "left", RIGHT: "right"}


class SchemaError(ValueError):
    """Raised with the list of every structural problem found (path: message)."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


# --------------------------------------------------------------------------------------------
# generic conversion
# --------------------------------------------------------------------------------------------

_ID_RE = None
_MAT_RE = None


def _id_ok(s: str) -> bool:
    global _ID_RE
    if _ID_RE is None:
        import re
        _ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
    return bool(_ID_RE.match(s))


def _mat_ok(s: str) -> bool:
    global _MAT_RE
    if _MAT_RE is None:
        import re
        _MAT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
    return bool(_MAT_RE.match(s))


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _convert(spec, v, path, errs):
    """Convert/validate v against spec; append problems to errs; return the converted value."""
    kind = spec[0]
    if kind == "opt":
        if v is None:
            return None
        return _convert(spec[1], v, path, errs)
    if v is None:
        errs.append("%s: null is not allowed" % path)
        return None
    if kind == "num":
        if not _is_num(v):
            errs.append("%s: expected number, got %r" % (path, v))
            return v
        lo, hi, excl = (spec[1:] + (None, None, False))[:3]
        if lo is not None and (v < lo or (excl and v <= lo)):
            errs.append("%s: %r %s minimum %r" % (path, v, "<=" if excl else "<", lo))
        if hi is not None and v > hi:
            errs.append("%s: %r > maximum %r" % (path, v, hi))
        return float(v)
    if kind == "int":
        if not ((isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer())):
            errs.append("%s: expected integer, got %r" % (path, v))
            return v
        lo, hi = (spec[1:] + (None, None))[:2]
        if lo is not None and v < lo:
            errs.append("%s: %r < minimum %r" % (path, v, lo))
        if hi is not None and v > hi:
            errs.append("%s: %r > maximum %r" % (path, v, hi))
        return int(v)
    if kind == "bool":
        if not isinstance(v, bool):
            errs.append("%s: expected boolean, got %r" % (path, v))
        return v
    if kind == "str":
        if not isinstance(v, str):
            errs.append("%s: expected string, got %r" % (path, v))
        elif len(spec) > 1 and spec[1] and len(v) < 1:
            errs.append("%s: empty string" % path)
        return v
    if kind == "id":
        if not isinstance(v, str) or not _id_ok(v):
            errs.append("%s: %r is not an Id (^[A-Za-z0-9_.:-]+$)" % (path, v))
        return v
    if kind == "mat":
        if not isinstance(v, str) or not _mat_ok(v):
            errs.append("%s: %r is not a material name (^[a-z][a-z0-9_]*$)" % (path, v))
        return v
    if kind == "enum":
        if v not in spec[1]:
            errs.append("%s: %r not in enum %s" % (path, v, list(spec[1])))
        return v
    if kind == "const":
        if v != spec[1]:
            errs.append("%s: expected const %r, got %r" % (path, spec[1], v))
        return v
    if kind == "obj":
        if not isinstance(v, dict):
            errs.append("%s: expected object, got %r" % (path, type(v).__name__))
            return v
        return spec[1]._from(v, path, errs)
    if kind == "list":
        if not isinstance(v, list):
            errs.append("%s: expected array, got %r" % (path, type(v).__name__))
            return v
        lo = spec[2] if len(spec) > 2 else 0
        if len(v) < lo:
            errs.append("%s: %d items < minItems %d" % (path, len(v), lo))
        return [_convert(spec[1], x, "%s[%d]" % (path, i), errs) for i, x in enumerate(v)]
    if kind == "map":
        if not isinstance(v, dict):
            errs.append("%s: expected object, got %r" % (path, type(v).__name__))
            return v
        out = {}
        for k, x in v.items():
            if k.startswith("_"):
                continue
            out[k] = _convert(spec[1], x, "%s.%s" % (path, k), errs)
        return out
    if kind == "xy":
        if not isinstance(v, list) or len(v) not in (2, 3) or not all(_is_num(x) for x in v):
            errs.append("%s: expected [x, y] or [x, y, z] numbers" % path)
            return v
        return [float(x) for x in v]
    if kind == "xyz":
        if not isinstance(v, list) or len(v) != 3 or not all(_is_num(x) for x in v):
            errs.append("%s: expected [x, y, z] numbers" % path)
            return v
        return [float(x) for x in v]
    if kind == "any":
        return v
    raise ValueError("bad spec %r" % (spec,))


def _emit(v):
    if isinstance(v, SchemaObject):
        return v.to_dict()
    if isinstance(v, list):
        return [_emit(x) for x in v]
    if isinstance(v, dict):
        return {k: _emit(x) for k, x in v.items()}
    return v


class SchemaObject:
    SPEC: Dict[str, tuple] = {}
    _KEEP_NOTES = ("_z_06",)

    @classmethod
    def _from(cls, d: dict, path: str, errs: list):
        kw = {}
        for k in d:
            if k.startswith("_"):
                continue
            if k not in cls.SPEC:
                errs.append("%s: unknown key %r" % (path, k))
        for name, (spec, required, default) in cls.SPEC.items():
            if name in d:
                kw[name] = _convert(spec, d[name], "%s.%s" % (path, name), errs)
            elif required:
                errs.append("%s: missing required key %r" % (path, name))
                kw[name] = default() if callable(default) else default
            else:
                kw[name] = default() if callable(default) else default
        try:
            obj = cls(**kw)
        except TypeError as e:  # pragma: no cover - SPEC/dataclass mismatch is a programming error
            raise RuntimeError("%s: %s" % (cls.__name__, e))
        obj._post(d, path, errs)
        return obj

    def _post(self, d, path, errs):
        """Per-class conditional requirements (if/then of the JSON schema)."""

    @classmethod
    def from_dict(cls, d: dict, path: str = "$"):
        errs: List[str] = []
        obj = cls._from(d, path, errs)
        if errs:
            raise SchemaError(errs)
        return obj

    def to_dict(self) -> dict:
        out = {}
        for f in dc_fields(self):
            if f.name.startswith("_") or f.name not in self.SPEC:
                continue
            v = getattr(self, f.name)
            if v is None and not self.SPEC[f.name][1]:
                continue
            out[f.name] = _emit(v)
        return out


def _S(kind, *args):
    return (kind,) + args


NUM = _S("num")
POS = _S("num", 0.0, None, True)
NONNEG = _S("num", 0.0)
STR = _S("str", True)
ID = _S("id")
MAT = _S("mat")
BOOL = _S("bool")
OPT_ID = _S("opt", ID)
SEND = _S("opt", NONNEG)


# --------------------------------------------------------------------------------------------
# profiles
# --------------------------------------------------------------------------------------------

@dataclass
class MaterialHint(SchemaObject):
    SPEC = {
        "base_color": (_S("list", _S("num", 0.0, 1.0)), False, None),
        "roughness": (_S("num", 0.0, 1.0), False, None),
        "two_sided": (BOOL, False, False),
        "texture_repeat_m": (POS, False, None),
    }
    base_color: Optional[list] = None
    roughness: Optional[float] = None
    two_sided: bool = False
    texture_repeat_m: Optional[float] = None


@dataclass
class Sampling(SchemaObject):
    SPEC = {
        "step_m": (POS, False, None),
        "min_step_m": (POS, False, None),
        "curvature_gain": (NONNEG, False, None),
        "smoothing_window_m": (NONNEG, False, None),
        "smoothing_passes": (_S("int", 0, 4), False, None),
        "width_ramp_m": (POS, False, None),
        "bank_max_deg": (_S("num", 0.0, 30.0), False, None),
        "bank_probe_min_half_width_m": (POS, False, None),
        "bank_rate_max_deg_per_m": (NONNEG, False, None),
        "pin_blend_m": (POS, False, None),
        "extra_stations_m": (_S("list", NONNEG), False, None),
    }
    step_m: Optional[float] = None
    min_step_m: Optional[float] = None
    curvature_gain: Optional[float] = None
    smoothing_window_m: Optional[float] = None
    smoothing_passes: Optional[int] = None
    width_ramp_m: Optional[float] = None
    bank_max_deg: Optional[float] = None
    bank_probe_min_half_width_m: Optional[float] = None
    bank_rate_max_deg_per_m: Optional[float] = None
    pin_blend_m: Optional[float] = None
    extra_stations_m: Optional[list] = None


ROAD_SAMPLING_DEFAULTS = dict(step_m=2.0, min_step_m=0.25, curvature_gain=20.0, smoothing_window_m=20.0,
                              smoothing_passes=1, width_ramp_m=5.0, bank_max_deg=4.0,
                              bank_probe_min_half_width_m=1.5, bank_rate_max_deg_per_m=0.25,
                              pin_blend_m=10.0, extra_stations_m=[])
RAIL_SAMPLING_DEFAULTS = dict(ROAD_SAMPLING_DEFAULTS, step_m=1.0, curvature_gain=60.0,
                              smoothing_window_m=40.0, smoothing_passes=2, bank_max_deg=6.0)


@dataclass
class Camber(SchemaObject):
    SPEC = {
        "kind": (_S("enum", ("parabolic", "planar", "none")), True, "none"),
        "crossfall_pct": (_S("num", 0.0, 10.0), False, None),
        "camber_m": (NONNEG, False, None),
    }
    kind: str = "none"
    crossfall_pct: Optional[float] = None
    camber_m: Optional[float] = None


@dataclass
class Marking(SchemaObject):
    SPEC = {
        "id": (ID, False, None),
        "anchor": (_S("enum", ("centre", "edge_left", "edge_right")), False, "centre"),
        "offset_m": (NUM, True, 0.0),
        "width_m": (POS, True, 0.1),
        "pattern": (_S("enum", ("solid", "dashed", "double", "none")), True, "none"),
        "dash_m": (POS, False, None),
        "gap_m": (POS, False, None),
        "phase_m": (NUM, False, 0.0),
        "double_gap_m": (POS, False, None),
        "material": (MAT, True, "white_paint"),
        "lift_m": (_S("num", 0.0, 0.02), False, 0.004),
        "s0_m": (NONNEG, False, None),
        "s1_m": (SEND, False, None),
    }
    id: Optional[str] = None
    anchor: str = "centre"
    offset_m: float = 0.0
    width_m: float = 0.1
    pattern: str = "none"
    dash_m: Optional[float] = None
    gap_m: Optional[float] = None
    phase_m: float = 0.0
    double_gap_m: Optional[float] = None
    material: str = "white_paint"
    lift_m: float = 0.004
    s0_m: Optional[float] = None
    s1_m: Optional[float] = None

    def _post(self, d, path, errs):
        if self.pattern == "dashed" and (self.dash_m is None or self.gap_m is None):
            errs.append("%s: dashed marking needs dash_m and gap_m" % path)
        if self.pattern == "double" and self.double_gap_m is None:
            errs.append("%s: double marking needs double_gap_m" % path)


@dataclass
class RailSection(SchemaObject):
    SPEC = {
        "profile_id": (_S("str"), False, None),
        "height_m": (POS, True, 0.15875),
        "head_width_m": (POS, True, 0.06985),
        "foot_width_m": (POS, True, 0.1397),
        "web_thickness_m": (POS, True, 0.020),
        "head_depth_m": (POS, True, 0.045),
        "foot_thickness_m": (POS, True, 0.011),
        "material": (MAT, True, "rail_steel"),
    }
    profile_id: Optional[str] = None
    height_m: float = 0.15875
    head_width_m: float = 0.06985
    foot_width_m: float = 0.1397
    web_thickness_m: float = 0.020
    head_depth_m: float = 0.045
    foot_thickness_m: float = 0.011
    material: str = "rail_steel"


@dataclass
class Sleeper(SchemaObject):
    SPEC = {
        "length_m": (POS, True, 2.5),
        "width_m": (POS, True, 0.25),
        "height_m": (POS, True, 0.15),
        "pitch_m": (POS, True, 0.65),
        "phase_m": (NUM, False, 0.0),
        "embed_m": (NONNEG, False, 0.10),
        "mode": (_S("enum", ("instances", "merged")), False, "instances"),
        "material": (MAT, True, "sleeper_concrete"),
    }
    length_m: float = 2.5
    width_m: float = 0.25
    height_m: float = 0.15
    pitch_m: float = 0.65
    phase_m: float = 0.0
    embed_m: float = 0.10
    mode: str = "instances"
    material: str = "sleeper_concrete"


@dataclass
class Ballast(SchemaObject):
    SPEC = {
        "shoulder_slope": (POS, True, 1.5),
        "depth_m": (POS, True, 0.45),
        "material": (MAT, True, "ballast"),
    }
    shoulder_slope: float = 1.5
    depth_m: float = 0.45
    material: str = "ballast"


@dataclass
class RailSpec(SchemaObject):
    SPEC = {
        "gauge_m": (POS, True, 1.435),
        "pad_m": (NONNEG, False, 0.005),
        "rail": (_S("obj", RailSection), True, RailSection),
        "sleeper": (_S("obj", Sleeper), True, Sleeper),
        "ballast": (_S("obj", Ballast), True, Ballast),
    }
    gauge_m: float = 1.435
    pad_m: float = 0.005
    rail: RailSection = field(default_factory=RailSection)
    sleeper: Sleeper = field(default_factory=Sleeper)
    ballast: Ballast = field(default_factory=Ballast)


@dataclass
class RoadProfile(SchemaObject):
    SPEC = {
        "kind": (_S("enum", ("road", "rail")), True, "road"),
        "lanes": (_S("int", 0), False, None),
        "lane_widths_m": (_S("list", POS), False, None),
        "width_m": (NONNEG, True, 0.0),
        "surface_material": (MAT, True, "tarmac"),
        "camber": (_S("obj", Camber), True, Camber),
        "overlap_m": (_S("num", 0.03, 0.10), False, 0.04),
        "skirt_drop_m": (_S("num", 0.0, 0.03), False, 0.02),
        "lateral_station_spacing_m": (POS, False, 1.0),
        "markings": (_S("list", _S("obj", Marking)), True, list),
        "rail": (_S("obj", RailSpec), False, None),
        "sampling_defaults": (_S("obj", Sampling), False, None),
    }
    kind: str = "road"
    lanes: Optional[int] = None
    lane_widths_m: Optional[list] = None
    width_m: float = 0.0
    surface_material: str = "tarmac"
    camber: Camber = field(default_factory=Camber)
    overlap_m: float = 0.04
    skirt_drop_m: float = 0.02
    lateral_station_spacing_m: float = 1.0
    markings: List[Marking] = field(default_factory=list)
    rail: Optional[RailSpec] = None
    sampling_defaults: Optional[Sampling] = None

    def _post(self, d, path, errs):
        if self.kind == "rail" and self.rail is None:
            errs.append("%s: kind rail requires 'rail'" % path)


@dataclass
class Lip(SchemaObject):
    SPEC = {
        "kind": (_S("enum", ("radius", "chamfer", "none")), True, "radius"),
        "size_m": (NONNEG, False, 0.02),
        "arc_points": (_S("int", 1, 8), False, 3),
    }
    kind: str = "radius"
    size_m: float = 0.02
    arc_points: int = 3


@dataclass
class SplitMaterial(SchemaObject):
    SPEC = {
        "enabled": (BOOL, True, False),
        "inner": (MAT, False, None),
        "outer": (MAT, False, None),
        "boundary_frac": (_S("num", 0.0, 1.0), False, 0.5),
    }
    enabled: bool = False
    inner: Optional[str] = None
    outer: Optional[str] = None
    boundary_frac: float = 0.5

    def _post(self, d, path, errs):
        if self.enabled and (self.inner is None or self.outer is None):
            errs.append("%s: enabled split needs inner and outer" % path)


@dataclass
class DropKerb(SchemaObject):
    SPEC = {
        "s_m": (NONNEG, True, 0.0),
        "length_m": (NONNEG, False, 1.83),
        "ramp_m": (POS, False, 0.915),
        "target_height_m": (_S("num", 0.0, 0.2), False, 0.006),
    }
    s_m: float = 0.0
    length_m: float = 1.83
    ramp_m: float = 0.915
    target_height_m: float = 0.006


@dataclass
class SplineDropKerb(SchemaObject):
    SPEC = {
        "side": (_S("enum", ("left", "right", "both")), True, "both"),
        "s_m": (NONNEG, True, 0.0),
        "length_m": (NONNEG, False, 1.83),
        "ramp_m": (POS, False, 0.915),
        "target_height_m": (_S("num", 0.0, 0.2), False, 0.006),
    }
    side: str = "both"
    s_m: float = 0.0
    length_m: float = 1.83
    ramp_m: float = 0.915
    target_height_m: float = 0.006

    def as_drop_kerb(self) -> DropKerb:
        return DropKerb(s_m=self.s_m, length_m=self.length_m, ramp_m=self.ramp_m,
                        target_height_m=self.target_height_m)


_BARRIER_FIELDS = {
    "type": (_S("enum", BARRIER_TYPES), True, "none"),
    "height_m": (POS, False, None),
    "thickness_m": (POS, False, None),
    "material": (MAT, False, None),
    "coping_material": (MAT, False, "coping_concrete"),
    "coping_overhang_m": (NONNEG, False, 0.025),
    "coping_height_m": (NONNEG, False, 0.05),
    "post_pitch_m": (POS, False, None),
    "post_size_m": (POS, False, 0.06),
    "post_material": (MAT, False, "post_steel"),
    "rails_m": (_S("list", NONNEG), False, None),
    "rail_size_m": (POS, False, 0.04),
    "offset_m": (NUM, False, 0.0),
    "skirt_m": (NONNEG, False, 0.30),
}


def _barrier_post(self, d, path, errs):
    if self.type != "none":
        for k in ("height_m", "thickness_m", "material"):
            if getattr(self, k) is None:
                errs.append("%s: barrier type %s requires %s" % (path, self.type, k))
        if self.type in FENCE_TYPES + RAILING_TYPES and self.post_pitch_m is None:
            errs.append("%s: barrier type %s requires post_pitch_m" % (path, self.type))


@dataclass
class Barrier(SchemaObject):
    """BarrierInline (no s-range); BarrierSegment adds s0_m/s1_m."""
    SPEC = dict(_BARRIER_FIELDS)
    type: str = "none"
    height_m: Optional[float] = None
    thickness_m: Optional[float] = None
    material: Optional[str] = None
    coping_material: str = "coping_concrete"
    coping_overhang_m: float = 0.025
    coping_height_m: float = 0.05
    post_pitch_m: Optional[float] = None
    post_size_m: float = 0.06
    post_material: str = "post_steel"
    rails_m: Optional[list] = None
    rail_size_m: float = 0.04
    offset_m: float = 0.0
    skirt_m: float = 0.30

    _post = _barrier_post

    def effective_rails(self) -> list:
        if self.rails_m is not None:
            return list(self.rails_m)
        if self.type == "guard_rail":
            return [0.75, 0.55]
        H = self.height_m or 0.0
        return [H - 0.02, 0.5 * H, 0.10]


@dataclass
class BarrierSegment(Barrier):
    SPEC = dict({"s0_m": (NONNEG, True, 0.0), "s1_m": (SEND, True, None)}, **_BARRIER_FIELDS)
    s0_m: float = 0.0
    s1_m: Optional[float] = None

    def inline(self) -> Barrier:
        return Barrier(**{f.name: getattr(self, f.name) for f in dc_fields(Barrier)})


_EMB_FIELDS = {
    "side": (_S("enum", ("left", "right", "both", "downhill", "uphill", "auto")), True, "auto"),
    "kind": (_S("enum", ("batter", "retaining_wall", "auto")), True, "auto"),
    "slope_ratio": (POS, False, 1.5),
    "wall_thickness_m": (POS, False, 0.30),
    "wall_coping_m": (NONNEG, False, 0.10),
    "threshold_m": (NONNEG, False, 0.35),
    "toe_extra_m": (NONNEG, False, 0.30),
    "material": (MAT, True, "grass"),
}


@dataclass
class Embankment(SchemaObject):
    SPEC = dict(_EMB_FIELDS)
    side: str = "auto"
    kind: str = "auto"
    slope_ratio: float = 1.5
    wall_thickness_m: float = 0.30
    wall_coping_m: float = 0.10
    threshold_m: float = 0.35
    toe_extra_m: float = 0.30
    material: str = "grass"


@dataclass
class EmbankmentSegment(Embankment):
    SPEC = dict({"s0_m": (NONNEG, True, 0.0), "s1_m": (SEND, True, None)}, **_EMB_FIELDS)
    s0_m: float = 0.0
    s1_m: Optional[float] = None

    def inline(self) -> Embankment:
        return Embankment(**{f.name: getattr(self, f.name) for f in dc_fields(Embankment)})


@dataclass
class EdgeMaterials(SchemaObject):
    SPEC = {"kerb": (MAT, True, "concrete_kerb"), "pavement": (MAT, True, "paving_slab")}
    kerb: str = "concrete_kerb"
    pavement: str = "paving_slab"


@dataclass
class EdgeProfile(SchemaObject):
    SPEC = {
        "kerb_width_m": (NONNEG, True, 0.0),
        "kerb_height_m": (NONNEG, True, 0.0),
        "lip": (_S("obj", Lip), False, Lip),
        "pavement_width_m": (NONNEG, True, 0.0),
        "pavement_crossfall_pct": (_S("num", 0.0, 10.0), False, 2.5),
        "pavement_max_crossfall_pct": (_S("num", 0.0, 20.0), False, 8.0),
        "tuck_depth_m": (NONNEG, False, 0.03),
        "tuck_in_m": (NONNEG, False, 0.02),
        "skirt_m": (NONNEG, False, 0.30),
        "materials": (_S("obj", EdgeMaterials), True, EdgeMaterials),
        "split_material": (_S("obj", SplitMaterial), False, SplitMaterial),
        "drop_kerbs": (_S("list", _S("obj", DropKerb)), False, list),
        "barriers": (_S("list", _S("obj", BarrierSegment)), False, list),
        "embankments": (_S("list", _S("obj", EmbankmentSegment)), False, list),
    }
    kerb_width_m: float = 0.0
    kerb_height_m: float = 0.0
    lip: Lip = field(default_factory=Lip)
    pavement_width_m: float = 0.0
    pavement_crossfall_pct: float = 2.5
    pavement_max_crossfall_pct: float = 8.0
    tuck_depth_m: float = 0.03
    tuck_in_m: float = 0.02
    skirt_m: float = 0.30
    materials: EdgeMaterials = field(default_factory=EdgeMaterials)
    split_material: SplitMaterial = field(default_factory=SplitMaterial)
    drop_kerbs: List[DropKerb] = field(default_factory=list)
    barriers: List[BarrierSegment] = field(default_factory=list)
    embankments: List[EmbankmentSegment] = field(default_factory=list)


@dataclass
class Foliage(SchemaObject):
    SPEC = {
        "mode": (_S("enum", ("none", "cards", "instances")), True, "none"),
        "density_per_m2": (NONNEG, False, 12.0),
        "card_size_m": (POS, False, 0.25),
        "material": (MAT, False, None),
        "mesh_id": (_S("str"), False, None),
        "seed": (_S("int", 0), False, 1),
    }
    mode: str = "none"
    density_per_m2: float = 12.0
    card_size_m: float = 0.25
    material: Optional[str] = None
    mesh_id: Optional[str] = None
    seed: int = 1


@dataclass
class HedgeSegment(SchemaObject):
    SPEC = {
        "s0_m": (NONNEG, True, 0.0),
        "s1_m": (SEND, True, None),
        "offset_m": (NUM, False, 0.1),
        "height_override_m": (POS, False, None),
        "width_override_m": (POS, False, None),
    }
    s0_m: float = 0.0
    s1_m: Optional[float] = None
    offset_m: float = 0.1
    height_override_m: Optional[float] = None
    width_override_m: Optional[float] = None


@dataclass
class HedgeProfile(SchemaObject):
    SPEC = {
        "width_m": (POS, True, 0.8),
        "height_m": (POS, True, 1.5),
        "top_profile": (_S("enum", ("flat", "rounded", "domed")), True, "flat"),
        "corner_radius_m": (NONNEG, False, 0.15),
        "corner_points": (_S("int", 1, 8), False, 4),
        "noise_amplitude_m": (NONNEG, False, 0.06),
        "noise_scale_m": (POS, False, 0.6),
        "noise_seed": (_S("int", 0), False, 1),
        "base_sink_m": (NONNEG, False, 0.10),
        "material": (MAT, True, "privet_leaf"),
        "foliage": (_S("obj", Foliage), True, Foliage),
        "segments": (_S("list", _S("obj", HedgeSegment)), True, list),
    }
    width_m: float = 0.8
    height_m: float = 1.5
    top_profile: str = "flat"
    corner_radius_m: float = 0.15
    corner_points: int = 4
    noise_amplitude_m: float = 0.06
    noise_scale_m: float = 0.6
    noise_seed: int = 1
    base_sink_m: float = 0.10
    material: str = "privet_leaf"
    foliage: Foliage = field(default_factory=Foliage)
    segments: List[HedgeSegment] = field(default_factory=list)


# --------------------------------------------------------------------------------------------
# spline
# --------------------------------------------------------------------------------------------

@dataclass
class Point(SchemaObject):
    SPEC = {
        "x": (NUM, True, 0.0),
        "y": (NUM, True, 0.0),
        "z": (_S("opt", NUM), False, None),
        "roll_deg": (_S("opt", _S("num", -30.0, 30.0)), False, None),
        "width_m": (NONNEG, False, None),
        "tags": (_S("list", _S("str")), False, list),
    }
    x: float = 0.0
    y: float = 0.0
    z: Optional[float] = None
    roll_deg: Optional[float] = None
    width_m: Optional[float] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class SegmentRoad(SchemaObject):
    SPEC = {
        "width_m": (NONNEG, False, None),
        "profile_id": (ID, False, None),
        "edge_extra_left_m": (NUM, False, None),
        "edge_extra_right_m": (NUM, False, None),
        "markings": (_S("list", _S("obj", Marking)), False, None),
        "markings_add": (_S("list", _S("obj", Marking)), False, None),
    }
    width_m: Optional[float] = None
    profile_id: Optional[str] = None
    edge_extra_left_m: Optional[float] = None
    edge_extra_right_m: Optional[float] = None
    markings: Optional[List[Marking]] = None
    markings_add: Optional[List[Marking]] = None


_MISSING = object()


@dataclass
class SegmentEdge(SchemaObject):
    SPEC = {
        "profile_id": (ID, False, None),
        "kerb_width_m": (NONNEG, False, None),
        "kerb_height_m": (NONNEG, False, None),
        "pavement_width_m": (NONNEG, False, None),
        "pavement_crossfall_pct": (_S("num", 0.0, 10.0), False, None),
        "split_material": (_S("obj", SplitMaterial), False, None),
        "barrier": (_S("opt", _S("obj", Barrier)), False, None),
        "embankment": (_S("opt", _S("obj", Embankment)), False, None),
    }
    profile_id: Optional[str] = None
    kerb_width_m: Optional[float] = None
    kerb_height_m: Optional[float] = None
    pavement_width_m: Optional[float] = None
    pavement_crossfall_pct: Optional[float] = None
    split_material: Optional[SplitMaterial] = None
    barrier: Optional[Barrier] = None
    embankment: Optional[Embankment] = None
    barrier_set: bool = False          # the key was present (null paints "none")
    embankment_set: bool = False

    def _post(self, d, path, errs):
        self.barrier_set = "barrier" in d
        self.embankment_set = "embankment" in d

    def to_dict(self):
        out = super().to_dict()
        if self.barrier_set and self.barrier is None:
            out["barrier"] = None
        if self.embankment_set and self.embankment is None:
            out["embankment"] = None
        return out


@dataclass
class SegmentHedge(SchemaObject):
    SPEC = {
        "present": (BOOL, True, False),
        "profile_id": (ID, False, None),
        "offset_m": (NUM, False, None),
        "height_m": (POS, False, None),
        "width_m": (POS, False, None),
    }
    present: bool = False
    profile_id: Optional[str] = None
    offset_m: Optional[float] = None
    height_m: Optional[float] = None
    width_m: Optional[float] = None


@dataclass
class Segment(SchemaObject):
    SPEC = {
        "id": (ID, False, None),
        "s0_m": (NONNEG, True, 0.0),
        "s1_m": (SEND, True, None),
        "side": (_S("enum", ("left", "right", "both", "centre")), True, "both"),
        "ramp_m": (NONNEG, False, None),
        "road": (_S("obj", SegmentRoad), False, None),
        "edge": (_S("obj", SegmentEdge), False, None),
        "hedge": (_S("obj", SegmentHedge), False, None),
    }
    id: Optional[str] = None
    s0_m: float = 0.0
    s1_m: Optional[float] = None
    side: str = "both"
    ramp_m: Optional[float] = None
    road: Optional[SegmentRoad] = None
    edge: Optional[SegmentEdge] = None
    hedge: Optional[SegmentHedge] = None

    def applies_to(self, side: int) -> bool:
        return self.side == "both" or self.side == SIDE_NAME[side]


@dataclass
class Source(SchemaObject):
    SPEC = {
        "layer": (_S("enum", ("roads", "rail", "barriers", "authored")), True, "authored"),
        "osm_id": (_S("opt", _S("str")), False, None),
        "osm_ids": (_S("list", _S("str")), False, None),
        "name": (_S("opt", _S("str")), False, None),
        "cls": (_S("opt", _S("str")), False, None),
        "tags": (_S("map", _S("str")), False, None),
        "tile": (_S("list", _S("int")), False, None),
        "segment_index": (_S("int", 0), False, None),
        "segment_count": (_S("int", 1), False, None),
    }
    layer: str = "authored"
    osm_id: Optional[str] = None
    osm_ids: Optional[list] = None
    name: Optional[str] = None
    cls: Optional[str] = None
    tags: Optional[dict] = None
    tile: Optional[list] = None
    segment_index: Optional[int] = None
    segment_count: Optional[int] = None


@dataclass
class Overlay(SchemaObject):
    SPEC = {
        "kind": (_S("enum", ("osm_way", "step06_smoothed", "other")), True, "other"),
        "pts": (_S("list", _S("xy"), 2), True, list),
        "osm_id": (_S("opt", _S("str")), False, None),
    }
    kind: str = "other"
    pts: list = field(default_factory=list)
    osm_id: Optional[str] = None


@dataclass
class ProfileIds(SchemaObject):
    SPEC = {
        "road": (OPT_ID, True, None),
        "edge_left": (OPT_ID, True, None),
        "edge_right": (OPT_ID, True, None),
        "hedge_left": (OPT_ID, True, None),
        "hedge_right": (OPT_ID, True, None),
    }
    road: Optional[str] = None
    edge_left: Optional[str] = None
    edge_right: Optional[str] = None
    hedge_left: Optional[str] = None
    hedge_right: Optional[str] = None

    def edge(self, side: int) -> Optional[str]:
        return self.edge_left if side == LEFT else self.edge_right

    def hedge(self, side: int) -> Optional[str]:
        return self.hedge_left if side == LEFT else self.hedge_right


@dataclass
class Continuation(SchemaObject):
    SPEC = {
        "from": (_S("opt", _S("enum", ("seam", "way", "gap"))), True, None),
        "to": (_S("opt", _S("enum", ("seam", "way", "gap"))), True, None),
    }
    from_: Optional[str] = None
    to: Optional[str] = None

    @classmethod
    def _from(cls, d, path, errs):
        d2 = dict(d)
        if "from" in d2:
            d2["from_"] = d2.pop("from")
        obj = super()._from(d2, path, errs)
        return obj

    def to_dict(self):
        return {"from": self.from_, "to": self.to}


Continuation.SPEC = {"from_": Continuation.SPEC["from"], "to": Continuation.SPEC["to"]}


@dataclass
class OverrunPoints(SchemaObject):
    SPEC = {"before": (_S("opt", _S("xyz")), True, None), "after": (_S("opt", _S("xyz")), True, None)}
    before: Optional[list] = None
    after: Optional[list] = None


@dataclass
class Flags(SchemaObject):
    SPEC = {
        "bridge": (BOOL, False, False), "tunnel": (BOOL, False, False), "z_gap": (BOOL, False, False),
        "steps": (BOOL, False, False), "disused": (BOOL, False, False), "gauge_unmapped": (BOOL, False, False),
        "closed_loop": (BOOL, False, False), "tracks": (_S("opt", _S("int", 1)), False, None),
    }
    bridge: bool = False
    tunnel: bool = False
    z_gap: bool = False
    steps: bool = False
    disused: bool = False
    gauge_unmapped: bool = False
    closed_loop: bool = False
    tracks: Optional[int] = None


@dataclass
class SplineDef(SchemaObject):
    SPEC = {
        "id": (ID, True, "spline"),
        "source": (_S("obj", Source), True, Source),
        "profile_ids": (_S("obj", ProfileIds), True, ProfileIds),
        "points": (_S("list", _S("obj", Point), 2), True, list),
        "sampling": (_S("obj", Sampling), False, None),
        "segments": (_S("list", _S("obj", Segment)), False, list),
        "drop_kerbs": (_S("list", _S("obj", SplineDropKerb)), False, list),
        "overlay": (_S("obj", Overlay), False, None),
        "junction_start": (OPT_ID, False, None),
        "junction_end": (OPT_ID, False, None),
        "continues_from": (OPT_ID, False, None),
        "continues_to": (OPT_ID, False, None),
        "continuation_kind": (_S("obj", Continuation), False, None),
        "overrun_points": (_S("obj", OverrunPoints), False, None),
        "flags": (_S("obj", Flags), False, None),
    }
    id: str = "spline"
    source: Source = field(default_factory=Source)
    profile_ids: ProfileIds = field(default_factory=ProfileIds)
    points: List[Point] = field(default_factory=list)
    sampling: Optional[Sampling] = None
    segments: List[Segment] = field(default_factory=list)
    drop_kerbs: List[SplineDropKerb] = field(default_factory=list)
    overlay: Optional[Overlay] = None
    junction_start: Optional[str] = None
    junction_end: Optional[str] = None
    continues_from: Optional[str] = None
    continues_to: Optional[str] = None
    continuation_kind: Optional[Continuation] = None
    overrun_points: Optional[OverrunPoints] = None
    flags: Optional[Flags] = None


@dataclass
class JunctionEnd(SchemaObject):
    SPEC = {"spline_id": (ID, True, ""), "end": (_S("enum", ("start", "end")), True, "start")}
    spline_id: str = ""
    end: str = "start"


@dataclass
class Junction(SchemaObject):
    SPEC = {
        "id": (ID, True, ""),
        "x": (NUM, True, 0.0),
        "y": (NUM, True, 0.0),
        "z": (_S("opt", NUM), False, None),
        "radius_m": (NONNEG, False, None),
        "kind": (_S("enum", ("disc", "none")), False, "disc"),
        "ends": (_S("list", _S("obj", JunctionEnd)), True, list),
    }
    id: str = ""
    x: float = 0.0
    y: float = 0.0
    z: Optional[float] = None
    radius_m: Optional[float] = None
    kind: str = "disc"
    ends: List[JunctionEnd] = field(default_factory=list)


@dataclass
class Origin(SchemaObject):
    SPEC = {"E": (NUM, True, 0.0), "N": (NUM, True, 0.0)}
    E: float = 0.0
    N: float = 0.0


@dataclass
class Profiles(SchemaObject):
    SPEC = {
        "road": (_S("map", _S("obj", RoadProfile)), True, dict),
        "edge": (_S("map", _S("obj", EdgeProfile)), True, dict),
        "hedge": (_S("map", _S("obj", HedgeProfile)), True, dict),
    }
    road: Dict[str, RoadProfile] = field(default_factory=dict)
    edge: Dict[str, EdgeProfile] = field(default_factory=dict)
    hedge: Dict[str, HedgeProfile] = field(default_factory=dict)


@dataclass
class Site(SchemaObject):
    SPEC = {
        "schema_version": (STR, True, "1.0.0"),
        "site": (STR, True, ""),
        "crs": (STR, True, "EPSG:27700"),
        "origin": (_S("obj", Origin), True, Origin),
        "vertical_datum": (STR, True, "ODN"),
        "frame": (_S("const", FRAME_CONST), True, FRAME_CONST),
        "generator": (STR, True, ""),
        "materials": (_S("map", _S("obj", MaterialHint)), False, dict),
        "profiles": (_S("obj", Profiles), True, Profiles),
        "splines": (_S("list", _S("obj", SplineDef)), True, list),
        "junctions": (_S("list", _S("obj", Junction)), False, list),
    }
    schema_version: str = "1.0.0"
    site: str = ""
    crs: str = "EPSG:27700"
    origin: Origin = field(default_factory=Origin)
    vertical_datum: str = "ODN"
    frame: str = FRAME_CONST
    generator: str = ""
    materials: Dict[str, MaterialHint] = field(default_factory=dict)
    profiles: Profiles = field(default_factory=Profiles)
    splines: List[SplineDef] = field(default_factory=list)
    junctions: List[Junction] = field(default_factory=list)
    notes: dict = field(default_factory=dict)          # underscore keys of the root, kept for provenance

    def _post(self, d, path, errs):
        import re
        if not re.match(r"^1\.[0-9]+\.[0-9]+$", self.schema_version or ""):
            errs.append("%s.schema_version: %r is not 1.x.y" % (path, self.schema_version))
        if not re.match(r"^EPSG:[0-9]+$", self.crs or ""):
            errs.append("%s.crs: %r is not EPSG:<n>" % (path, self.crs))
        self.notes = {k: v for k, v in d.items() if k.startswith("_")}

    def spline(self, spline_id: str) -> SplineDef:
        for sp in self.splines:
            if sp.id == spline_id:
                return sp
        raise KeyError(spline_id)


@dataclass
class ProfileFile(SchemaObject):
    SPEC = {
        "kind": (_S("enum", ("road", "edge", "hedge")), True, "road"),
        "id": (ID, True, ""),
        "profile": (_S("any"), True, None),
    }
    kind: str = "road"
    id: str = ""
    profile: Any = None

    def _post(self, d, path, errs):
        cls = {"road": RoadProfile, "edge": EdgeProfile, "hedge": HedgeProfile}[self.kind] if self.kind in ("road", "edge", "hedge") else None
        if cls is not None and isinstance(self.profile, dict):
            self.profile = cls._from(self.profile, path + ".profile", errs)
        elif cls is not None:
            errs.append("%s.profile: expected object" % path)


# --------------------------------------------------------------------------------------------
# resolution (SCHEMA.md 5)
# --------------------------------------------------------------------------------------------

def resolve_sampling(spline: SplineDef, road: Optional[RoadProfile]) -> Sampling:
    """spline.sampling > RoadProfile.sampling_defaults > built-in (road or rail column)."""
    base = dict(RAIL_SAMPLING_DEFAULTS if (road is not None and road.kind == "rail") else ROAD_SAMPLING_DEFAULTS)
    for src in ((road.sampling_defaults if road is not None else None), spline.sampling):
        if src is None:
            continue
        for f in dc_fields(Sampling):
            v = getattr(src, f.name)
            if v is not None:
                base[f.name] = v
    base["extra_stations_m"] = list(base.get("extra_stations_m") or [])
    return Sampling(**base)


def apply_ramped_override(s: np.ndarray, base: np.ndarray, s0: float, s1: float, ramp: float, value: float) -> np.ndarray:
    """[s0-ramp, s0]: lerp base -> value; [s0, s1]: value; [s1, s1+ramp]: lerp value -> base."""
    s = np.asarray(s, dtype=np.float64)
    out = np.array(base, dtype=np.float64, copy=True)
    if s1 < s0:
        return out
    inside = (s >= s0) & (s <= s1)
    out[inside] = value
    if ramp > 0:
        pre = (s >= s0 - ramp) & (s < s0)
        t = (s[pre] - (s0 - ramp)) / ramp
        out[pre] = base[pre] + (value - base[pre]) * t
        post = (s > s1) & (s <= s1 + ramp)
        t = (s[post] - s1) / ramp
        out[post] = value + (base[post] - value) * t
    return out


def paint_intervals(L: float, layers: list) -> list:
    """layers: [(s0, s1|None, value)] in priority order (later wins).  Returns [(a, b, value|None)]
    over [0, L] with adjacent equal values merged; s1 None = L; ranges clamped to [0, L]."""
    eps = 1e-9
    norm = []
    for s0, s1, v in layers:
        a = max(0.0, float(s0))
        b = L if s1 is None else min(L, float(s1))
        if b <= a + eps:
            continue
        norm.append((a, b, v))
    bps = {0.0, float(L)}
    for a, b, _ in norm:
        bps.add(a)
        bps.add(b)
    bps = sorted(bps)
    out = []
    for a, b in zip(bps[:-1], bps[1:]):
        if b - a <= eps:
            continue
        val = None
        for a0, b0, v in norm:
            if a0 <= a + eps and b <= b0 + eps:
                val = v
        if out and out[-1][2] is val and abs(out[-1][1] - a) <= eps:
            out[-1] = (out[-1][0], b, val)
        else:
            out.append((a, b, val))
    return out


def _clamp_open(vals, L: float) -> list:
    return [float(v) for v in vals if 0.0 < v < L]


@dataclass
class ScalarOverride:
    s0: float
    s1: float
    ramp: float
    value: float


def _ramped(s: np.ndarray, base_value: float, overrides: list) -> np.ndarray:
    out = np.full(s.shape, float(base_value), dtype=np.float64)
    for o in overrides:
        out = apply_ramped_override(s, out, o.s0, o.s1, o.ramp, o.value)
    return out


@dataclass
class RoadTimeline:
    kind: Optional[str]                              # 'road' | 'rail' | None (no carriageway)
    base: Optional[RoadProfile]
    L: float
    width_knots: List[Optional[float]]               # per (merged) point: width_m or None -> base width
    width_overrides: List[ScalarOverride]
    extra_overrides: Dict[int, List[ScalarOverride]]
    profile_intervals: list                          # [(a, b, RoadProfile|None)]
    marking_intervals: list                          # [(a, b, [Marking])]
    crossfall_overrides: List[ScalarOverride]
    camber_m_overrides: List[ScalarOverride]
    _mandatory: list

    def mandatory_stations(self) -> list:
        return sorted(set(self._mandatory))

    def profile_at(self, s: np.ndarray) -> list:
        """Road profile in force per station (interval [a, b); the last interval includes L)."""
        return _values_at(self.profile_intervals, s, self.base)


def _values_at(intervals, s, default=None):
    s = np.asarray(s, dtype=np.float64)
    out = [default] * len(s)
    if not intervals:
        return out
    starts = np.array([a for a, _, _ in intervals])
    idx = np.searchsorted(starts, s + 1e-9, side="right") - 1
    for i, k in enumerate(idx):
        if k >= 0:
            v = intervals[k][2]
            out[i] = default if v is None else v
    return out


def resolve_road(spline: SplineDef, site: Site, L: float, n_points: Optional[int] = None,
                 ramp_default: Optional[float] = None) -> RoadTimeline:
    pid = spline.profile_ids.road
    base = site.profiles.road[pid] if pid is not None else None
    ramp_d = float(ramp_default if ramp_default is not None else ROAD_SAMPLING_DEFAULTS["width_ramp_m"])
    mand: List[float] = []
    width_over: List[ScalarOverride] = []
    extra_over = {LEFT: [], RIGHT: []}
    cf_over: List[ScalarOverride] = []
    cm_over: List[ScalarOverride] = []
    prof_layers = [(0.0, None, base)]
    mark_layers = [(0.0, None, list(base.markings) if base else [], "replace")]
    for seg in spline.segments:
        r = seg.road
        if r is None:
            continue
        s0 = float(seg.s0_m)
        s1 = L if seg.s1_m is None else float(seg.s1_m)
        ramp = ramp_d if seg.ramp_m is None else float(seg.ramp_m)
        if r.width_m is not None:
            width_over.append(ScalarOverride(s0, s1, ramp, float(r.width_m)))
            mand += [s0, s1, s0 - ramp, s1 + ramp]
        if r.edge_extra_left_m is not None:
            extra_over[LEFT].append(ScalarOverride(s0, s1, ramp, float(r.edge_extra_left_m)))
            mand += [s0, s1, s0 - ramp, s1 + ramp]
        if r.edge_extra_right_m is not None:
            extra_over[RIGHT].append(ScalarOverride(s0, s1, ramp, float(r.edge_extra_right_m)))
            mand += [s0, s1, s0 - ramp, s1 + ramp]
        if r.profile_id is not None:
            p = site.profiles.road[r.profile_id]
            prof_layers.append((s0, s1, p))
            mark_layers.append((s0, s1, list(p.markings), "replace"))
            mand += [s0, s1, s0 - ramp, s1 + ramp]
            if p.camber.crossfall_pct is not None:
                cf_over.append(ScalarOverride(s0, s1, ramp, float(p.camber.crossfall_pct)))
            if p.camber.camber_m is not None:
                cm_over.append(ScalarOverride(s0, s1, ramp, float(p.camber.camber_m)))
        if r.markings is not None:
            mark_layers.append((s0, s1, list(r.markings), "replace"))
            mand += [s0, s1]
        if r.markings_add is not None:
            mark_layers.append((s0, s1, list(r.markings_add), "add"))
            mand += [s0, s1]
    prof_int = paint_intervals(L, prof_layers)
    # markings: painted with replace/add semantics
    bps = {0.0, L}
    for a, b, _, _ in mark_layers:
        bps.add(max(0.0, a))
        bps.add(L if b is None else min(L, b))
    for a, b, mlist, _ in mark_layers:
        for m in mlist:
            if m.s0_m is not None:
                mand.append(float(m.s0_m))
            if m.s1_m is not None:
                mand.append(float(m.s1_m))
    bps = sorted(bps)
    mark_int = []
    for a, b in zip(bps[:-1], bps[1:]):
        if b - a <= 1e-9:
            continue
        cur: List[Marking] = []
        for a0, b0, mlist, mode in mark_layers:
            b0v = L if b0 is None else b0
            if a0 <= a + 1e-9 and b <= b0v + 1e-9:
                cur = list(mlist) if mode == "replace" else cur + list(mlist)
        mark_int.append((a, b, cur))
    for a, b, _ in prof_int:
        mand += [a, b]
    widths = [p.width_m for p in spline.points]
    return RoadTimeline(kind=(base.kind if base else None), base=base, L=L, width_knots=widths,
                        width_overrides=width_over, extra_overrides=extra_over, profile_intervals=prof_int,
                        marking_intervals=mark_int, crossfall_overrides=cf_over, camber_m_overrides=cm_over,
                        _mandatory=_clamp_open(mand, L))


@dataclass
class HedgeSpec:
    profile: HedgeProfile
    offset_m: float
    height_m: float
    width_m: float


@dataclass
class SideSpec:
    """Per-station arrays over the N stations for one side (read by Renderer B AND Renderer C)."""
    side: int
    present: np.ndarray            # (N,) bool: an edge profile exists on this side
    kerb_width: np.ndarray
    kerb_height: np.ndarray
    pavement_width: np.ndarray
    crossfall: np.ndarray          # fraction (pct / 100)
    max_crossfall: np.ndarray      # fraction
    lip_size: np.ndarray
    lip_kind: list                 # per station str
    arc_points: int
    tuck_depth: np.ndarray
    tuck_in: np.ndarray
    skirt: np.ndarray
    mat_kerb: np.ndarray           # object arrays
    mat_pavement: np.ndarray
    mat_inner: np.ndarray
    mat_outer: np.ndarray
    split: np.ndarray              # bool
    split_frac: np.ndarray
    drop_factor: np.ndarray
    drop_target: np.ndarray
    hk: np.ndarray                 # kerb upstand after the drop factor
    lip_r: np.ndarray              # lip size after the drop factor
    hk_back: np.ndarray            # pavement back-edge height above the road edge
    back_offset: np.ndarray        # kw + pw (outward from the kerb line)
    barrier_timeline: list         # [(a, b, Barrier|None)]
    embankment_timeline: list      # [(a, b, Embankment|None)]
    hedge_timeline: list           # [(a, b, HedgeSpec|None)]
    has_kerb_or_pavement: bool

    def barrier_at(self, s: np.ndarray) -> list:
        return _values_at(self.barrier_timeline, s, None)


@dataclass
class SideTimeline:
    side: int
    base: Optional[EdgeProfile]
    hedge_base: Optional[HedgeProfile]
    L: float
    scalar_overrides: Dict[str, List[ScalarOverride]]
    profile_intervals: list           # [(a, b, EdgeProfile)]
    split_intervals: list             # [(a, b, SplitMaterial|None)]  (None -> profile's own)
    barrier_intervals: list
    embankment_intervals: list
    hedge_intervals: list
    drop_kerbs: List[DropKerb]
    _mandatory: list

    def mandatory_stations(self) -> list:
        return sorted(set(self._mandatory))

    def evaluate(self, s: np.ndarray) -> SideSpec:
        s = np.asarray(s, dtype=np.float64)
        N = len(s)
        base = self.base
        present = np.full(N, base is not None, dtype=bool)
        if base is None:
            z = np.zeros(N)
            obj = np.array([None] * N, dtype=object)
            return SideSpec(self.side, present, z, z, z, z, z, z, ["none"] * N, 1, z, z, z, obj, obj, obj, obj,
                            np.zeros(N, dtype=bool), z, z, z, z, z, z, z, [], [], self.hedge_intervals, False)
        kw = _ramped(s, base.kerb_width_m, self.scalar_overrides["kerb_width_m"])
        kh = _ramped(s, base.kerb_height_m, self.scalar_overrides["kerb_height_m"])
        pw = _ramped(s, base.pavement_width_m, self.scalar_overrides["pavement_width_m"])
        cfp = _ramped(s, base.pavement_crossfall_pct, self.scalar_overrides["pavement_crossfall_pct"])
        profs = _values_at(self.profile_intervals, s, base)
        splits = _values_at(self.split_intervals, s, None)
        lip_size = np.array([p.lip.size_m if p.lip.kind != "none" else 0.0 for p in profs])
        lip_kind = [p.lip.kind for p in profs]
        arc_points = int(base.lip.arc_points)
        tuck_depth = np.array([p.tuck_depth_m for p in profs])
        tuck_in = np.array([p.tuck_in_m for p in profs])
        skirt = np.array([p.skirt_m for p in profs])
        max_cf = np.array([p.pavement_max_crossfall_pct for p in profs]) / 100.0
        mat_kerb = np.array([p.materials.kerb for p in profs], dtype=object)
        mat_pav = np.array([p.materials.pavement for p in profs], dtype=object)
        split = np.zeros(N, dtype=bool)
        split_frac = np.full(N, 0.5)
        mat_inner = mat_kerb.copy()
        mat_outer = mat_pav.copy()
        for i, (p, so) in enumerate(zip(profs, splits)):
            sm = so if so is not None else p.split_material
            if sm is not None and sm.enabled:
                split[i] = True
                split_frac[i] = sm.boundary_frac
                mat_inner[i] = sm.inner
                mat_outer[i] = sm.outer
        # drop kerbs
        f = np.zeros(N)
        target = np.zeros(N)
        for dk in self.drop_kerbs:
            fk = drop_factor(s, dk.s_m, dk.length_m, dk.ramp_m)
            better = fk > f
            target[better] = dk.target_height_m
            f = np.maximum(f, fk)
        hk = kh * (1.0 - f) + target * f
        with np.errstate(divide="ignore", invalid="ignore"):
            lip_r = np.where(kh > 0, lip_size * hk / np.where(kh > 0, kh, 1.0), 0.0)
        cf = cfp / 100.0
        hk_back = np.minimum(kh + pw * cf, hk + pw * max_cf)
        hk_back = np.where(pw > 0, hk_back, hk)
        has_kp = bool((kw > 0).any() or (pw > 0).any())
        return SideSpec(side=self.side, present=present, kerb_width=kw, kerb_height=kh, pavement_width=pw,
                        crossfall=cf, max_crossfall=max_cf, lip_size=lip_size, lip_kind=lip_kind,
                        arc_points=arc_points, tuck_depth=tuck_depth, tuck_in=tuck_in, skirt=skirt,
                        mat_kerb=mat_kerb, mat_pavement=mat_pav, mat_inner=mat_inner, mat_outer=mat_outer,
                        split=split, split_frac=split_frac, drop_factor=f, drop_target=target, hk=hk,
                        lip_r=lip_r, hk_back=hk_back, back_offset=kw + pw,
                        barrier_timeline=self.barrier_intervals, embankment_timeline=self.embankment_intervals,
                        hedge_timeline=self.hedge_intervals, has_kerb_or_pavement=has_kp)


def smoothstep(t):
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def drop_factor(s: np.ndarray, s_d: float, length: float, ramp: float) -> np.ndarray:
    """f_k(s) of SCHEMA.md 4.9: smoothstep down-ramp, 1 on the flat run, smoothstep up-ramp."""
    s = np.asarray(s, dtype=np.float64)
    f = np.zeros(s.shape)
    down = (s >= s_d - ramp) & (s < s_d)
    f[down] = smoothstep((s[down] - (s_d - ramp)) / ramp)
    flat = (s >= s_d) & (s <= s_d + length)
    f[flat] = 1.0
    up = (s > s_d + length) & (s <= s_d + length + ramp)
    f[up] = 1.0 - smoothstep((s[up] - (s_d + length)) / ramp)
    return f


_EDGE_SCALARS = ("kerb_width_m", "kerb_height_m", "pavement_width_m", "pavement_crossfall_pct")


def resolve_side(spline: SplineDef, side: int, site: Site, L: float, ramp_default: Optional[float] = None) -> SideTimeline:
    eid = spline.profile_ids.edge(side)
    base = site.profiles.edge[eid] if eid is not None else None
    hid = spline.profile_ids.hedge(side)
    hedge_base = site.profiles.hedge[hid] if hid is not None else None
    ramp_d = float(ramp_default if ramp_default is not None else ROAD_SAMPLING_DEFAULTS["width_ramp_m"])
    mand: List[float] = []
    scal = {k: [] for k in _EDGE_SCALARS}
    prof_layers = [(0.0, None, base)]
    split_layers = [(0.0, None, None)]
    bar_layers = []
    emb_layers = []
    hedge_layers = []
    drops: List[DropKerb] = []
    if base is not None:
        for b in base.barriers:
            bar_layers.append((b.s0_m, b.s1_m, b.inline() if b.type != "none" else None))
        for e in base.embankments:
            emb_layers.append((e.s0_m, e.s1_m, e.inline()))
        drops += list(base.drop_kerbs)
    if hedge_base is not None:
        for hs in hedge_base.segments:
            h = HedgeSpec(hedge_base, hs.offset_m,
                          hs.height_override_m if hs.height_override_m is not None else hedge_base.height_m,
                          hs.width_override_m if hs.width_override_m is not None else hedge_base.width_m)
            hedge_layers.append((hs.s0_m, hs.s1_m, h))
    # profile switches replace the PROFILE-LEVEL lists inside their range; those layers sit below every
    # spline-segment layer (SCHEMA.md 5.4: profile list layers first, then spline segments in file order)
    for seg in spline.segments:
        if not seg.applies_to(side) or seg.edge is None or base is None or seg.edge.profile_id is None:
            continue
        s0 = float(seg.s0_m)
        s1 = L if seg.s1_m is None else float(seg.s1_m)
        p = site.profiles.edge[seg.edge.profile_id]
        bar_layers.append((s0, s1, None))
        emb_layers.append((s0, s1, None))
        for b in p.barriers:
            a0 = max(s0, b.s0_m)
            b1 = s1 if b.s1_m is None else min(s1, b.s1_m)
            bar_layers.append((a0, b1, b.inline() if b.type != "none" else None))
        for em in p.embankments:
            a0 = max(s0, em.s0_m)
            b1 = s1 if em.s1_m is None else min(s1, em.s1_m)
            emb_layers.append((a0, b1, em.inline()))
        drops += list(p.drop_kerbs)
    for seg in spline.segments:
        if not seg.applies_to(side):
            continue
        s0 = float(seg.s0_m)
        s1 = L if seg.s1_m is None else float(seg.s1_m)
        ramp = ramp_d if seg.ramp_m is None else float(seg.ramp_m)
        e = seg.edge
        if e is not None and base is not None:
            if e.profile_id is not None:
                p = site.profiles.edge[e.profile_id]
                prof_layers.append((s0, s1, p))
                mand += [s0, s1, s0 - ramp, s1 + ramp]
                for k in _EDGE_SCALARS:
                    scal[k].append(ScalarOverride(s0, s1, ramp, float(getattr(p, k))))
            for k in _EDGE_SCALARS:
                v = getattr(e, k)
                if v is not None:
                    scal[k].append(ScalarOverride(s0, s1, ramp, float(v)))
                    mand += [s0, s1, s0 - ramp, s1 + ramp]
            if e.split_material is not None:
                split_layers.append((s0, s1, e.split_material))
                mand += [s0, s1]
            if e.barrier_set:
                bar_layers.append((s0, s1, e.barrier if (e.barrier is not None and e.barrier.type != "none") else None))
                mand += [s0, s1]
            if e.embankment_set:
                emb_layers.append((s0, s1, e.embankment))
                mand += [s0, s1]
        h = seg.hedge
        if h is not None:
            hp = site.profiles.hedge[h.profile_id] if h.profile_id is not None else hedge_base
            if h.present and hp is not None:
                spec = HedgeSpec(hp, h.offset_m if h.offset_m is not None else 0.1,
                                 h.height_m if h.height_m is not None else hp.height_m,
                                 h.width_m if h.width_m is not None else hp.width_m)
                hedge_layers.append((s0, s1, spec))
            else:
                hedge_layers.append((s0, s1, None))
            mand += [s0, s1]
    for dk in spline.drop_kerbs:
        if dk.side == "both" or dk.side == SIDE_NAME[side]:
            drops.append(dk.as_drop_kerb())
    for dk in drops:
        mand += [dk.s_m - dk.ramp_m, dk.s_m, dk.s_m + dk.length_m, dk.s_m + dk.length_m + dk.ramp_m]
    for lay in (bar_layers, emb_layers, hedge_layers):
        for a, b, _ in lay:
            mand.append(float(a))
            if b is not None:
                mand.append(float(b))
    prof_int = paint_intervals(L, prof_layers)
    for a, b, _ in prof_int:
        mand += [a, b]
    return SideTimeline(side=side, base=base, hedge_base=hedge_base, L=L, scalar_overrides=scal,
                        profile_intervals=prof_int, split_intervals=paint_intervals(L, split_layers),
                        barrier_intervals=paint_intervals(L, bar_layers),
                        embankment_intervals=paint_intervals(L, emb_layers),
                        hedge_intervals=paint_intervals(L, hedge_layers), drop_kerbs=drops,
                        _mandatory=_clamp_open(mand, L))


def road_kinds_consistent(spline: SplineDef, site: Site) -> Optional[str]:
    """Validation: every road profile painted on one spline has the same kind. Returns the problem or None."""
    kinds = set()
    pid = spline.profile_ids.road
    if pid is not None and pid in site.profiles.road:
        kinds.add(site.profiles.road[pid].kind)
    for seg in spline.segments:
        if seg.road is not None and seg.road.profile_id in site.profiles.road:
            kinds.add(site.profiles.road[seg.road.profile_id].kind)
    if len(kinds) > 1:
        return "spline %s mixes road kinds %s" % (spline.id, sorted(kinds))
    return None
