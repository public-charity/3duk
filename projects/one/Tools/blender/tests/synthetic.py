"""Synthetic fixtures shared by the tests and make_fixtures.py (geometry.md 6, DESIGN.md 3.7, 3.10).

Documents are built as plain dicts (schema 1.0.0) from the library profiles under schema/profiles so
the fixtures and the C++ Automation tests read exactly the same profile numbers.  Terrains are
``Heightfield.from_function`` fields.
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_BLENDER = os.path.dirname(HERE)
PROJECT_ONE = os.path.dirname(os.path.dirname(TOOLS_BLENDER))
SCHEMA_DIR = os.path.join(PROJECT_ONE, "schema")
PROFILES_DIR = os.path.join(SCHEMA_DIR, "profiles")
EXAMPLES_DIR = os.path.join(SCHEMA_DIR, "examples")
FIXTURES_DIR = os.path.join(HERE, "fixtures")
if TOOLS_BLENDER not in sys.path:
    sys.path.insert(0, TOOLS_BLENDER)

from streetscape.terrain import Heightfield  # noqa: E402
from streetscape import noise  # noqa: E402

FRAME = "local-metres, X east, Y north, Z up"


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def library_profile(pid: str) -> dict:
    return copy.deepcopy(load_json(os.path.join(PROFILES_DIR, pid + ".json"))["profile"])


def straight_100() -> dict:
    """examples/synthetic_straight.json verbatim (SCHEMA.md 9.3)."""
    return load_json(os.path.join(EXAMPLES_DIR, "synthetic_straight.json"))


def _road_test_marked() -> dict:
    return copy.deepcopy(straight_100()["profiles"]["road"]["road_test_marked"])


def _doc(site, spline_id, points, road_profiles, edge_profiles, hedge_profiles, profile_ids, sampling=None,
         segments=None, drop_kerbs=None, overlay=None, source=None, terrain_note=None):
    d = {
        "schema_version": "1.0.0",
        "site": site,
        "crs": "EPSG:27700",
        "origin": {"E": 0, "N": 0},
        "vertical_datum": "ODN",
        "frame": FRAME,
        "generator": "hand-authored (Tools/blender/tests/synthetic.py)",
        "materials": copy.deepcopy(straight_100()["materials"]),
        "profiles": {"road": road_profiles, "edge": edge_profiles, "hedge": hedge_profiles},
        "splines": [{
            "id": spline_id,
            "source": source or {"layer": "authored", "osm_id": None, "name": spline_id, "cls": None},
            "profile_ids": profile_ids,
            "points": points,
            "segments": segments or [],
            "drop_kerbs": drop_kerbs or [],
            "junction_start": None,
            "junction_end": None,
        }],
        "junctions": [],
    }
    if sampling is not None:
        d["splines"][0]["sampling"] = sampling
    if overlay is not None:
        d["splines"][0]["overlay"] = overlay
    if terrain_note is not None:
        d["_terrain"] = terrain_note
    return d


ROAD_SAMPLING = {"step_m": 2.0, "min_step_m": 0.25, "curvature_gain": 20.0, "smoothing_window_m": 20.0,
                 "smoothing_passes": 1, "width_ramp_m": 5.0, "bank_max_deg": 4.0,
                 "bank_probe_min_half_width_m": 1.5, "pin_blend_m": 10.0, "bank_rate_max_deg_per_m": 0.25}


def sine_5_50() -> dict:
    """Points every 5 m on y = 5 sin(2 pi x / 50), x in [0, 100]; w 6; edge_uk_kerb both sides."""
    pts = [{"x": float(x), "y": round(5.0 * math.sin(2 * math.pi * x / 50.0), 6), "width_m": 6.0} for x in range(0, 101, 5)]
    return _doc("synthetic_sine", "authored:sine_5_50", pts, {"road_test_marked": _road_test_marked()},
                {"edge_uk_kerb": library_profile("edge_uk_kerb")}, {},
                {"road": "road_test_marked", "edge_left": "edge_uk_kerb", "edge_right": "edge_uk_kerb",
                 "hedge_left": None, "hedge_right": None}, sampling=dict(ROAD_SAMPLING),
                overlay={"kind": "other", "pts": [[p["x"], p["y"]] for p in pts], "osm_id": None},
                terrain_note={"kind": "flat", "z_m": 10.0, "px_m": 1.0, "tile_m": 512.0, "extent_m": [512.0, 512.0]})


def curve_R20_200() -> dict:
    """Straight (0,0)->(60,0), 90 deg left arc R = 20 (8 waypoints), straight to L = 200; w 6."""
    pts = [{"x": 0.0, "y": 0.0, "width_m": 6.0}, {"x": 60.0, "y": 0.0, "width_m": 6.0}]
    R = 20.0
    for k in range(1, 9):
        th = math.radians(90.0 * k / 8)
        pts.append({"x": round(60.0 + R * math.sin(th), 6), "y": round(R - R * math.cos(th), 6), "width_m": 6.0})
    arc = math.pi / 2 * R
    pts.append({"x": 80.0, "y": round(20.0 + (200.0 - 60.0 - arc), 6), "width_m": 6.0})
    return _doc("synthetic_curve", "authored:curve_R20_200", pts, {"road_test_marked": _road_test_marked()},
                {"edge_uk_kerb": library_profile("edge_uk_kerb")}, {},
                {"road": "road_test_marked", "edge_left": "edge_uk_kerb", "edge_right": "edge_uk_kerb",
                 "hedge_left": None, "hedge_right": None}, sampling=dict(ROAD_SAMPLING),
                overlay={"kind": "other", "pts": [[p["x"], p["y"]] for p in pts], "osm_id": None},
                terrain_note={"kind": "flat", "z_m": 10.0, "px_m": 1.0, "tile_m": 512.0, "extent_m": [512.0, 512.0]})


def rail_R300_600() -> dict:
    """600 m of standard-gauge track: 200 m straight, an R = 300 m left bend of 200 m, 200 m straight
    (SCHEMA.md 9.2 shape, rail_standard profile).  Origin-local coordinates start at (100, 100)."""
    pts = []
    x0, y0 = 100.0, 100.0
    for x in (0.0, 50.0, 100.0, 150.0, 200.0):
        pts.append({"x": x0 + x, "y": y0})
    R = 300.0
    arc_len = 200.0
    n_arc = 10
    for k in range(1, n_arc + 1):
        th = (arc_len / R) * k / n_arc
        pts.append({"x": round(x0 + 200.0 + R * math.sin(th), 6), "y": round(y0 + R - R * math.cos(th), 6)})
    th_end = arc_len / R
    ex, ey = x0 + 200.0 + R * math.sin(th_end), y0 + R - R * math.cos(th_end)
    tx, ty = math.cos(th_end), math.sin(th_end)
    for d in (50.0, 100.0, 150.0, 200.0):
        pts.append({"x": round(ex + tx * d, 6), "y": round(ey + ty * d, 6)})
    return _doc("synthetic_rail", "authored:rail_R300_600", pts, {"rail_standard": library_profile("rail_standard")}, {}, {},
                {"road": "rail_standard", "edge_left": None, "edge_right": None, "hedge_left": None, "hedge_right": None},
                source={"layer": "rail", "osm_id": "0", "name": "rail_R300_600", "cls": "rail",
                        "tags": {"gauge": "1435", "electrified": "rail"}},
                overlay={"kind": "other", "pts": [[p["x"], p["y"]] for p in pts], "osm_id": "0"},
                terrain_note={"kind": "flat", "z_m": 10.0, "px_m": 1.0, "tile_m": 512.0, "extent_m": [1024.0, 1024.0]})


# -- terrains ------------------------------------------------------------------------------------

def flat_terrain(z: float = 10.0, extent=(512.0, 512.0)) -> Heightfield:
    """Flat z; tiles cover x in [0, extent_x) and y in [-256, extent_y - 256) so probes beside a road
    on y = 0 stay on coverage."""
    return Heightfield.from_function(lambda x, y: np.full_like(x, z, dtype=np.float64), extent, xy0=(0.0, -256.0))


def cross_slope_terrain(slope: float = 0.1, extent=(512.0, 512.0)) -> Heightfield:
    """z = slope * y: a hillside rising to the left of a road that runs along +x (covers y in [-256, 256))."""
    return Heightfield.from_function(lambda x, y: slope * y, extent, xy0=(0.0, -256.0))


def grade_noise_terrain(extent=(512.0, 512.0)) -> Heightfield:
    """2 % grade along x with hash noise of sigma 0.1 on the integer lattice."""
    def fn(x, y):
        i = np.round(x).astype(np.int64) * 7919 + np.round(y).astype(np.int64)
        return 0.02 * x + 0.1 * np.sqrt(3.0) * noise.unit_noise(i, 7)
    return Heightfield.from_function(fn, extent, xy0=(0.0, -256.0))


def step_terrain(step_at_y: float = 6.0, drop: float = 1.5, extent=(512.0, 512.0)) -> Heightfield:
    """z = 10 for y < step_at_y (under the road), 10 - drop beyond it (a 1.5 m bank the pavement overhangs)."""
    return Heightfield.from_function(lambda x, y: np.where(y < step_at_y, 10.0, 10.0 - drop), extent, xy0=(0.0, -256.0))


def terrain_for(doc: dict) -> Heightfield:
    t = doc.get("_terrain") or {}
    ext = tuple(t.get("extent_m", [512.0, 512.0]))
    return flat_terrain(float(t.get("z_m", 10.0)), ext)


FIXTURE_BUILDERS = {
    "straight_100": straight_100,
    "sine_5_50": sine_5_50,
    "curve_R20_200": curve_R20_200,
    "rail_R300_600": rail_R300_600,
}


def load_fixture(name: str) -> dict:
    path = os.path.join(FIXTURES_DIR, name + ".json")
    if os.path.isfile(path):
        return load_json(path)
    return FIXTURE_BUILDERS[name]()
