"""Streetscape geometry core: pure numpy prototype of the shared spline and Renderers A/B/C (+ rail).

Project One (projects/one). Normative documents: docs/DESIGN.md 3-8, docs/SCHEMA.md. This package
has no bpy dependency; bpy_bridge.py, render.py and blender_main.py import bpy lazily.
"""
__version__ = "0.1.0"

from .io_json import load_site, save_site, validate_structure, load_profile_file  # noqa: F401
from .mesh import MeshBuffer  # noqa: F401
from .terrain import Heightfield  # noqa: F401
from .build import build_spline, build_all, BuildResult, Instance  # noqa: F401
