"""Load / save / validate Streetscape documents (stdlib json only; SCHEMA.md 8).

``validate_structure(doc)`` returns the list of structural problems (empty = valid): the SPEC tables
of schema.py applied to the document (unknown keys, types, enums, ranges, conditional requirements,
``frame`` const, ``schema_version`` 1.x) plus the cross-references (every ``profile_ids.*`` and
``Segment.*.profile_id`` resolves inside the document, ``s0_m < s1_m``, one road kind per spline).
``validate_warnings(doc)`` returns the non-fatal notes (unhinted material names, missing overlay on a
non-authored spline, lane widths over width_m).
"""
from __future__ import annotations

import json
import os
from typing import List, Tuple

from . import schema as S


def _iter_materials(site: S.Site):
    for pid, p in site.profiles.road.items():
        yield "profiles.road.%s.surface_material" % pid, p.surface_material
        for i, m in enumerate(p.markings):
            yield "profiles.road.%s.markings[%d].material" % (pid, i), m.material
        if p.rail is not None:
            yield "profiles.road.%s.rail.rail.material" % pid, p.rail.rail.material
            yield "profiles.road.%s.rail.sleeper.material" % pid, p.rail.sleeper.material
            yield "profiles.road.%s.rail.ballast.material" % pid, p.rail.ballast.material
    for pid, p in site.profiles.edge.items():
        yield "profiles.edge.%s.materials.kerb" % pid, p.materials.kerb
        yield "profiles.edge.%s.materials.pavement" % pid, p.materials.pavement
        if p.split_material.enabled:
            yield "profiles.edge.%s.split_material.inner" % pid, p.split_material.inner
            yield "profiles.edge.%s.split_material.outer" % pid, p.split_material.outer
        for i, b in enumerate(p.barriers):
            for k in ("material", "coping_material", "post_material"):
                v = getattr(b, k)
                if v is not None:
                    yield "profiles.edge.%s.barriers[%d].%s" % (pid, i, k), v
        for i, e in enumerate(p.embankments):
            yield "profiles.edge.%s.embankments[%d].material" % (pid, i), e.material
    for pid, p in site.profiles.hedge.items():
        yield "profiles.hedge.%s.material" % pid, p.material
        if p.foliage.material is not None:
            yield "profiles.hedge.%s.foliage.material" % pid, p.foliage.material
    for si, sp in enumerate(site.splines):
        for gi, seg in enumerate(sp.segments):
            if seg.edge is not None and seg.edge.barrier is not None:
                for k in ("material", "coping_material", "post_material"):
                    v = getattr(seg.edge.barrier, k)
                    if v is not None:
                        yield "splines[%d].segments[%d].edge.barrier.%s" % (si, gi, k), v
            if seg.edge is not None and seg.edge.embankment is not None:
                yield "splines[%d].segments[%d].edge.embankment.material" % (si, gi), seg.edge.embankment.material
            if seg.road is not None:
                for lk in ("markings", "markings_add"):
                    for mi, m in enumerate(getattr(seg.road, lk) or []):
                        yield "splines[%d].segments[%d].road.%s[%d].material" % (si, gi, lk, mi), m.material


def _cross_checks(site: S.Site) -> List[str]:
    errs: List[str] = []
    for si, sp in enumerate(site.splines):
        where = "$.splines[%d] (%s)" % (si, sp.id)
        ids = sp.profile_ids
        for slot, table in (("road", site.profiles.road), ("edge_left", site.profiles.edge),
                            ("edge_right", site.profiles.edge), ("hedge_left", site.profiles.hedge),
                            ("hedge_right", site.profiles.hedge)):
            v = getattr(ids, slot)
            if v is not None and v not in table:
                errs.append("%s.profile_ids.%s: %r not in profiles.%s" % (where, slot, v, slot.split("_")[0]))
        for gi, seg in enumerate(sp.segments):
            sw = "%s.segments[%d]" % (where, gi)
            if seg.s1_m is not None and not seg.s1_m > seg.s0_m:
                errs.append("%s: s1_m %r must be > s0_m %r" % (sw, seg.s1_m, seg.s0_m))
            if seg.road is not None and seg.road.profile_id is not None and seg.road.profile_id not in site.profiles.road:
                errs.append("%s.road.profile_id: %r not in profiles.road" % (sw, seg.road.profile_id))
            if seg.edge is not None and seg.edge.profile_id is not None and seg.edge.profile_id not in site.profiles.edge:
                errs.append("%s.edge.profile_id: %r not in profiles.edge" % (sw, seg.edge.profile_id))
            if seg.hedge is not None and seg.hedge.profile_id is not None and seg.hedge.profile_id not in site.profiles.hedge:
                errs.append("%s.hedge.profile_id: %r not in profiles.hedge" % (sw, seg.hedge.profile_id))
            if seg.side == "centre" and (seg.edge is not None or seg.hedge is not None):
                errs.append("%s: side centre reads only the road block" % sw)
        p = road_kind_problem = S.road_kinds_consistent(sp, site)
        if road_kind_problem:
            errs.append("%s: %s" % (where, p))
        # semantic errors that are cheap to check structurally
        rid = ids.road
        if rid in site.profiles.road:
            rp = site.profiles.road[rid]
            for slot in ("edge_left", "edge_right"):
                eid = getattr(ids, slot)
                if eid in site.profiles.edge and not site.profiles.edge[eid].tuck_depth_m > rp.skirt_drop_m:
                    errs.append("%s: edge %s tuck_depth_m %r must exceed road skirt_drop_m %r" % (
                        where, eid, site.profiles.edge[eid].tuck_depth_m, rp.skirt_drop_m))
    for pid, p in site.profiles.road.items():
        for i, m in enumerate(p.markings):
            if m.s1_m is not None and m.s0_m is not None and not m.s1_m > m.s0_m:
                errs.append("$.profiles.road.%s.markings[%d]: s1_m must be > s0_m" % (pid, i))
    for pid, p in site.profiles.edge.items():
        for name, lst in (("barriers", p.barriers), ("embankments", p.embankments)):
            for i, b in enumerate(lst):
                if b.s1_m is not None and not b.s1_m > b.s0_m:
                    errs.append("$.profiles.edge.%s.%s[%d]: s1_m must be > s0_m" % (pid, name, i))
    for pid, p in site.profiles.hedge.items():
        for i, h in enumerate(p.segments):
            if h.s1_m is not None and not h.s1_m > h.s0_m:
                errs.append("$.profiles.hedge.%s.segments[%d]: s1_m must be > s0_m" % (pid, i))
    seen = set()
    for si, sp in enumerate(site.splines):
        if sp.id in seen:
            errs.append("$.splines[%d]: duplicate spline id %r" % (si, sp.id))
        seen.add(sp.id)
    return errs


def validate_structure(doc: dict) -> List[str]:
    """Every structural problem of a site document as 'path: message' (empty list = valid)."""
    if not isinstance(doc, dict):
        return ["$: document is not an object"]
    errs: List[str] = []
    site = S.Site._from(doc, "$", errs)
    if errs:
        return errs
    return _cross_checks(site)


def validate_warnings(doc: dict) -> List[str]:
    errs: List[str] = []
    site = S.Site._from(doc, "$", errs)
    if errs:
        return []
    warns: List[str] = []
    for path, name in _iter_materials(site):
        if name not in S.MATERIAL_NAMES:
            warns.append("$.%s: material %r is unhinted (not in SCHEMA.md 7)" % (path, name))
    for si, sp in enumerate(site.splines):
        if sp.source.layer != "authored" and sp.overlay is None:
            warns.append("$.splines[%d]: overlay missing on a %s spline" % (si, sp.source.layer))
    for pid, p in site.profiles.road.items():
        if p.lane_widths_m and sum(p.lane_widths_m) > p.width_m + 1e-9:
            warns.append("$.profiles.road.%s: sum(lane_widths_m) %r > width_m %r" % (pid, sum(p.lane_widths_m), p.width_m))
    return warns


def site_from_dict(doc: dict) -> S.Site:
    errs = validate_structure(doc)
    if errs:
        raise S.SchemaError(errs)
    return S.Site.from_dict(doc)


def load_site(path: str) -> S.Site:
    """json.load -> validate_structure -> Site; raises SchemaError listing every problem."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    try:
        site = site_from_dict(doc)
    except S.SchemaError as e:
        raise S.SchemaError(["%s: %s" % (os.path.basename(path), p) for p in e.problems])
    return site


def site_to_dict(site: S.Site) -> dict:
    d = site.to_dict()
    for k, v in site.notes.items():
        d[k] = v
    return d


def save_site(site: S.Site, path: str) -> None:
    """Canonical text: indent 1, dataclass field order, LF line endings, shortest-repr floats."""
    text = json.dumps(site_to_dict(site), indent=1, ensure_ascii=False, allow_nan=False)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")


def load_profile_file(path: str) -> Tuple[str, str, object]:
    """schema/profiles/<id>.json -> (kind, id, profile dataclass)."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    pf = S.ProfileFile.from_dict(doc)
    expect = os.path.splitext(os.path.basename(path))[0]
    if pf.id != expect:
        raise S.SchemaError(["%s: id %r != file name %r" % (path, pf.id, expect)])
    return pf.kind, pf.id, pf.profile


def load_profile_library(dir_path: str) -> dict:
    """{kind: {id: profile}} over every *.json of a profiles directory."""
    out = {"road": {}, "edge": {}, "hedge": {}}
    for name in sorted(os.listdir(dir_path)):
        if name.endswith(".json"):
            kind, pid, prof = load_profile_file(os.path.join(dir_path, name))
            out[kind][pid] = prof
    return out
