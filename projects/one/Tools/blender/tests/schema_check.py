#!/usr/bin/env python
"""Self-contained validator for the Project One streetscape schema artefacts.

No third-party dependency except numpy (for the geometry checks). Implements the subset of
JSON Schema draft 2020-12 that projects/one/schema/streetscape.schema.json uses:

  type (string or list), properties, required, additionalProperties (bool or schema),
  patternProperties, enum, const, items, prefixItems, minItems/maxItems, minLength/maxLength,
  minimum/maximum/exclusiveMinimum/exclusiveMaximum, multipleOf, pattern, $ref (#/... JSON
  pointer inside the root schema), allOf/anyOf/oneOf/not, if/then/else, boolean schemas.

Any other keyword met in the schema is reported as UNSUPPORTED (never silently skipped).

What it runs (see --help):
  1. structural validation of every profile file (wrapper against $defs/ProfileFile, inner
     profile against the matching $def) and every example against the root schema;
  2. the SCHEMA.md 8 structural/semantic rules (ids resolve, s0 < s1, material names, one road
     kind per spline, overlap/tuck rule, lane widths, overlay presence, junction consistency);
  3. numpy geometry sanity (finite points, site bbox, point spacing, s-ranges within the arc
     length of the centripetal Catmull-Rom of SCHEMA.md 3.1, width knots) and the
     SCHEMA.md 9.3 expectations for synthetic_straight.json;
  4. SCHEMA.md 4 <-> schema coverage (every $def and property documented, and vice versa).

Exit status 0 when there is no ERROR (warnings do not fail the run).

Usage:
  python schema_check.py <doc.json|profile.json>...                    (STAGES.md 0.9: VALID per file, exit 0 iff all valid)
  python schema_check.py --root <repo>/projects/one                    (full report; defaults to the repo)
  python schema_check.py --schema X.json --profiles DIR --examples DIR --md SCHEMA.md
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is present in the pipeline env
    np = None

# --------------------------------------------------------------------------------------------
# JSON Schema subset
# --------------------------------------------------------------------------------------------

IGNORED_KEYWORDS = {
    "$schema", "$id", "$defs", "$comment", "title", "description", "default", "examples",
    "deprecated", "readOnly", "writeOnly",
}
SUPPORTED_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "patternProperties", "enum",
    "const", "items", "prefixItems", "minItems", "maxItems", "minLength", "maxLength",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "pattern",
    "$ref", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "uniqueItems",
}


def json_equal(a, b):
    """JSON equality: bool is not a number, 1 == 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def type_ok(value, tname):
    if tname == "null":
        return value is None
    if tname == "boolean":
        return isinstance(value, bool)
    if tname == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and math.isfinite(value) and value.is_integer())
    if tname == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if tname == "string":
        return isinstance(value, str)
    if tname == "array":
        return isinstance(value, list)
    if tname == "object":
        return isinstance(value, dict)
    raise ValueError("unknown type name %r" % tname)


class SchemaValidator:
    def __init__(self, root_schema):
        self.root = root_schema
        self.unsupported = set()
        self.unresolved_refs = set()
        self._regex_cache = {}

    # -- helpers -----------------------------------------------------------------------------
    def regex(self, pat):
        r = self._regex_cache.get(pat)
        if r is None:
            r = self._regex_cache[pat] = re.compile(pat)
        return r

    def resolve_ref(self, ref):
        if not ref.startswith("#"):
            self.unresolved_refs.add(ref)
            return None
        node = self.root
        for part in ref[1:].split("/"):
            if part == "":
                continue
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                node = node[int(part)]
            elif isinstance(node, dict) and part in node:
                node = node[part]
            else:
                self.unresolved_refs.add(ref)
                return None
        return node

    # -- entry point -------------------------------------------------------------------------
    def validate(self, instance, schema, path="$"):
        """Return a list of (path, message) errors."""
        errors = []
        self._validate(instance, schema, path, errors)
        return errors

    def _validate(self, inst, schema, path, errors):
        if schema is True or schema == {}:
            return
        if schema is False:
            errors.append((path, "schema is false: no value allowed"))
            return
        if not isinstance(schema, dict):
            errors.append((path, "malformed schema node %r" % (schema,)))
            return

        for kw in schema:
            if kw not in SUPPORTED_KEYWORDS and kw not in IGNORED_KEYWORDS:
                self.unsupported.add(kw)

        if "$ref" in schema:
            target = self.resolve_ref(schema["$ref"])
            if target is None:
                errors.append((path, "unresolvable $ref %s" % schema["$ref"]))
            else:
                self._validate(inst, target, path, errors)

        if "type" in schema:
            types = schema["type"]
            if isinstance(types, str):
                types = [types]
            if not any(type_ok(inst, t) for t in types):
                errors.append((path, "expected type %s, got %s" % ("|".join(types), self._tn(inst))))
                # keep going only with keywords that tolerate the wrong type

        if "const" in schema and not json_equal(inst, schema["const"]):
            errors.append((path, "expected const %s, got %s" % (json.dumps(schema["const"]), self._short(inst))))
        if "enum" in schema and not any(json_equal(inst, e) for e in schema["enum"]):
            errors.append((path, "value %s not in enum %s" % (self._short(inst), json.dumps(schema["enum"]))))

        # numbers
        if isinstance(inst, (int, float)) and not isinstance(inst, bool):
            if "minimum" in schema and inst < schema["minimum"]:
                errors.append((path, "%r < minimum %r" % (inst, schema["minimum"])))
            if "maximum" in schema and inst > schema["maximum"]:
                errors.append((path, "%r > maximum %r" % (inst, schema["maximum"])))
            if "exclusiveMinimum" in schema and inst <= schema["exclusiveMinimum"]:
                errors.append((path, "%r <= exclusiveMinimum %r" % (inst, schema["exclusiveMinimum"])))
            if "exclusiveMaximum" in schema and inst >= schema["exclusiveMaximum"]:
                errors.append((path, "%r >= exclusiveMaximum %r" % (inst, schema["exclusiveMaximum"])))
            if "multipleOf" in schema:
                q = inst / schema["multipleOf"]
                if abs(q - round(q)) > 1e-9:
                    errors.append((path, "%r is not a multiple of %r" % (inst, schema["multipleOf"])))

        # strings
        if isinstance(inst, str):
            if "minLength" in schema and len(inst) < schema["minLength"]:
                errors.append((path, "string shorter than minLength %d" % schema["minLength"]))
            if "maxLength" in schema and len(inst) > schema["maxLength"]:
                errors.append((path, "string longer than maxLength %d" % schema["maxLength"]))
            if "pattern" in schema and not self.regex(schema["pattern"]).search(inst):
                errors.append((path, "%r does not match pattern %s" % (inst, schema["pattern"])))

        # arrays
        if isinstance(inst, list):
            if "minItems" in schema and len(inst) < schema["minItems"]:
                errors.append((path, "array has %d items < minItems %d" % (len(inst), schema["minItems"])))
            if "maxItems" in schema and len(inst) > schema["maxItems"]:
                errors.append((path, "array has %d items > maxItems %d" % (len(inst), schema["maxItems"])))
            if schema.get("uniqueItems"):
                for i in range(len(inst)):
                    for j in range(i):
                        if json_equal(inst[i], inst[j]):
                            errors.append((path, "items [%d] and [%d] are equal (uniqueItems)" % (j, i)))
            n_prefix = 0
            if "prefixItems" in schema:
                for i, sub in enumerate(schema["prefixItems"]):
                    if i < len(inst):
                        self._validate(inst[i], sub, "%s[%d]" % (path, i), errors)
                n_prefix = len(schema["prefixItems"])
            if "items" in schema:
                for i in range(n_prefix, len(inst)):
                    self._validate(inst[i], schema["items"], "%s[%d]" % (path, i), errors)

        # objects
        if isinstance(inst, dict):
            for req in schema.get("required", []):
                if req not in inst:
                    errors.append((path, "missing required property %r" % req))
            props = schema.get("properties", {})
            pprops = schema.get("patternProperties", {})
            for key, val in inst.items():
                kpath = "%s.%s" % (path, key)
                matched = False
                if key in props:
                    matched = True
                    self._validate(val, props[key], kpath, errors)
                for pat, sub in pprops.items():
                    if self.regex(pat).search(key):
                        matched = True
                        self._validate(val, sub, kpath, errors)
                if not matched and "additionalProperties" in schema:
                    ap = schema["additionalProperties"]
                    if ap is False:
                        errors.append((kpath, "additional property %r not allowed" % key))
                    else:
                        self._validate(val, ap, kpath, errors)

        # combinators
        if "allOf" in schema:
            for i, sub in enumerate(schema["allOf"]):
                self._validate(inst, sub, path, errors)
        if "anyOf" in schema:
            branch_errors = [self.validate(inst, sub, path) for sub in schema["anyOf"]]
            if not any(len(e) == 0 for e in branch_errors):
                best = min(branch_errors, key=len)
                errors.append((path, "matches no anyOf branch; closest branch: " + "; ".join(m for _, m in best[:3])))
        if "oneOf" in schema:
            branch_errors = [self.validate(inst, sub, path) for sub in schema["oneOf"]]
            ok = [i for i, e in enumerate(branch_errors) if len(e) == 0]
            if len(ok) == 0:
                best = min(branch_errors, key=len)
                errors.append((path, "matches no oneOf branch; closest branch: " + "; ".join(m for _, m in best[:3])))
            elif len(ok) > 1:
                errors.append((path, "matches more than one oneOf branch: %s" % ok))
        if "not" in schema:
            if len(self.validate(inst, schema["not"], path)) == 0:
                errors.append((path, "must not match 'not' schema"))
        if "if" in schema:
            cond = len(self.validate(inst, schema["if"], path)) == 0
            if cond and "then" in schema:
                self._validate(inst, schema["then"], path, errors)
            if not cond and "else" in schema:
                self._validate(inst, schema["else"], path, errors)

    @staticmethod
    def _tn(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, int):
            return "integer"
        if isinstance(v, float):
            return "number"
        if isinstance(v, str):
            return "string"
        if isinstance(v, list):
            return "array"
        if isinstance(v, dict):
            return "object"
        return type(v).__name__

    @staticmethod
    def _short(v):
        s = json.dumps(v)
        return s if len(s) <= 60 else s[:57] + "..."


# --------------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []
        self.lines = []

    def error(self, where, msg):
        self.errors.append("%s: %s" % (where, msg))

    def warn(self, where, msg):
        self.warnings.append("%s: %s" % (where, msg))

    def info(self, where, msg):
        self.infos.append("%s: %s" % (where, msg))

    def line(self, text=""):
        self.lines.append(text)


# --------------------------------------------------------------------------------------------
# Semantic checks (SCHEMA.md 8)
# --------------------------------------------------------------------------------------------

NORMATIVE_MATERIALS = {
    "tarmac", "white_paint", "yellow_paint", "concrete_kerb", "paving_slab", "grass", "gravel",
    "brick_red", "coping_concrete", "chain_link", "post_steel", "steel_painted_black",
    "wood_fence", "privet_leaf", "ballast", "sleeper_concrete", "rail_steel", "stone_flint",
    "concrete_wall", "massing_grey",
}

JUNCTION_SNAP_M = 0.3


def materials_of_road(p):
    out = set()
    out.add(p.get("surface_material"))
    for m in p.get("markings", []):
        out.add(m.get("material"))
    rail = p.get("rail")
    if rail:
        out.add(rail.get("rail", {}).get("material"))
        out.add(rail.get("sleeper", {}).get("material"))
        out.add(rail.get("ballast", {}).get("material"))
    out.discard(None)
    return out


def materials_of_barrier(b):
    out = set()
    if not b:
        return out
    for k in ("material", "coping_material", "post_material"):
        out.add(b.get(k))
    out.discard(None)
    return out


def materials_of_edge(p):
    out = set()
    mats = p.get("materials", {})
    out.add(mats.get("kerb"))
    out.add(mats.get("pavement"))
    sm = p.get("split_material") or {}
    if sm.get("enabled"):
        out.add(sm.get("inner"))
        out.add(sm.get("outer"))
    for b in p.get("barriers", []):
        out |= materials_of_barrier(b)
    for e in p.get("embankments", []):
        out.add(e.get("material"))
    out.discard(None)
    return out


def materials_of_hedge(p):
    out = {p.get("material"), (p.get("foliage") or {}).get("material")}
    out.discard(None)
    return out


def semantic_document_checks(doc, label, rep, library_ids):
    """SCHEMA.md 8 structural rules that the JSON Schema cannot express."""
    profiles = doc.get("profiles", {})
    proads = profiles.get("road", {}) or {}
    pedges = profiles.get("edge", {}) or {}
    phedges = profiles.get("hedge", {}) or {}
    doc_materials = set(k for k in (doc.get("materials") or {}) if not k.startswith("_"))
    used_materials = set()
    referenced = {"road": set(), "edge": set(), "hedge": set()}

    # profiles inline: self-consistency
    for pid, p in proads.items():
        if pid.startswith("_"):
            continue
        used_materials |= materials_of_road(p)
        lw = p.get("lane_widths_m") or []
        if lw and sum(lw) > p.get("width_m", 0) + 1e-9:
            rep.warn("%s profiles.road.%s" % (label, pid), "sum(lane_widths_m)=%.3f > width_m=%.3f" % (sum(lw), p["width_m"]))
        if p.get("overlap_m", 0.04) < 0.03:
            rep.error("%s profiles.road.%s" % (label, pid), "overlap_m %r < 0.03" % p.get("overlap_m"))
        for i, m in enumerate(p.get("markings", [])):
            if m.get("anchor", "centre") in ("edge_left", "edge_right") and m.get("offset_m", 0) < 0:
                rep.error("%s profiles.road.%s.markings[%d]" % (label, pid, i), "edge-anchored marking needs offset_m >= 0")
            if m.get("s1_m") is not None and m.get("s0_m", 0) >= m["s1_m"]:
                rep.error("%s profiles.road.%s.markings[%d]" % (label, pid, i), "s0_m >= s1_m")
    for pid, p in pedges.items():
        if pid.startswith("_"):
            continue
        used_materials |= materials_of_edge(p)
        for i, b in enumerate(p.get("barriers", [])):
            if b.get("s1_m") is not None and b.get("s0_m", 0) >= b["s1_m"]:
                rep.error("%s profiles.edge.%s.barriers[%d]" % (label, pid, i), "s0_m >= s1_m")
        for i, e in enumerate(p.get("embankments", [])):
            if e.get("s1_m") is not None and e.get("s0_m", 0) >= e["s1_m"]:
                rep.error("%s profiles.edge.%s.embankments[%d]" % (label, pid, i), "s0_m >= s1_m")
        sm = p.get("split_material") or {}
        if sm.get("enabled") and not (0 <= sm.get("boundary_frac", 0.5) <= 1):
            rep.error("%s profiles.edge.%s.split_material" % (label, pid), "boundary_frac outside [0, 1]")
    for pid, p in phedges.items():
        if pid.startswith("_"):
            continue
        used_materials |= materials_of_hedge(p)
        for i, hs in enumerate(p.get("segments", [])):
            if hs.get("s1_m") is not None and hs.get("s0_m", 0) >= hs["s1_m"]:
                rep.error("%s profiles.hedge.%s.segments[%d]" % (label, pid, i), "s0_m >= s1_m")

    # splines
    seen_ids = set()
    spline_end_points = {}
    for si, sp in enumerate(doc.get("splines", [])):
        where = "%s splines[%d] (%s)" % (label, si, sp.get("id"))
        sid = sp.get("id")
        if sid in seen_ids:
            rep.error(where, "duplicate spline id")
        seen_ids.add(sid)
        pids = sp.get("profile_ids", {})
        road_kind = None
        road_ids_on_spline = []
        edge_ids_on_spline = set()

        def resolve(slot, kind, table, pid):
            if pid is None:
                return None
            referenced[kind].add(pid)
            if pid in table:
                return table[pid]
            lib = " (exists in schema/profiles but is not inlined)" if pid in library_ids.get(kind, set()) else " (not in schema/profiles either)"
            rep.error(where, "%s '%s' does not resolve inside the document%s" % (slot, pid, lib))
            return None

        rp = resolve("profile_ids.road", "road", proads, pids.get("road"))
        if rp is not None:
            road_kind = rp.get("kind")
            road_ids_on_spline.append(pids.get("road"))
        for slot in ("edge_left", "edge_right"):
            ep = resolve("profile_ids." + slot, "edge", pedges, pids.get(slot))
            if ep is not None:
                edge_ids_on_spline.add(pids.get(slot))
        for slot in ("hedge_left", "hedge_right"):
            resolve("profile_ids." + slot, "hedge", phedges, pids.get(slot))

        for gi, seg in enumerate(sp.get("segments", [])):
            sw = "%s.segments[%d] (%s)" % (where, gi, seg.get("id"))
            s0, s1 = seg.get("s0_m", 0), seg.get("s1_m")
            if s1 is not None and s0 >= s1:
                rep.error(sw, "s0_m %r >= s1_m %r" % (s0, s1))
            side = seg.get("side")
            if side == "centre" and ("edge" in seg or "hedge" in seg):
                rep.warn(sw, "side 'centre' segment carries edge/hedge blocks that are never read")
            road = seg.get("road") or {}
            if "profile_id" in road:
                p = resolve("segments[%d].road.profile_id" % gi, "road", proads, road["profile_id"])
                if p is not None:
                    road_ids_on_spline.append(road["profile_id"])
                    if road_kind is not None and p.get("kind") != road_kind:
                        rep.error(sw, "road.profile_id kind %r differs from the spline's base road kind %r" % (p.get("kind"), road_kind))
            for lk in ("markings", "markings_add"):
                for mi, m in enumerate(road.get(lk, [])):
                    used_materials.add(m.get("material"))
                    if m.get("anchor", "centre") in ("edge_left", "edge_right") and m.get("offset_m", 0) < 0:
                        rep.error("%s.road.%s[%d]" % (sw, lk, mi), "edge-anchored marking needs offset_m >= 0")
            edge = seg.get("edge") or {}
            if "profile_id" in edge:
                p = resolve("segments[%d].edge.profile_id" % gi, "edge", pedges, edge["profile_id"])
                if p is not None:
                    edge_ids_on_spline.add(edge["profile_id"])
            if edge.get("barrier"):
                used_materials |= materials_of_barrier(edge["barrier"])
            if edge.get("embankment"):
                used_materials.add(edge["embankment"].get("material"))
            sm = edge.get("split_material")
            if sm and sm.get("enabled"):
                used_materials.add(sm.get("inner"))
                used_materials.add(sm.get("outer"))
            if side in ("left", "right", "both") and edge and pids.get("edge_" + side if side != "both" else "edge_left") is None and "profile_id" not in edge:
                rep.warn(sw, "edge overrides on side %r but profile_ids.edge_%s is null and no edge.profile_id is given" % (side, side))
            hedge = seg.get("hedge")
            if hedge is not None:
                if "profile_id" in hedge:
                    resolve("segments[%d].hedge.profile_id" % gi, "hedge", phedges, hedge["profile_id"])
                elif hedge.get("present"):
                    sides = ["left", "right"] if side == "both" else [side]
                    for sd in sides:
                        if sd in ("left", "right") and pids.get("hedge_" + sd) is None:
                            rep.warn(sw, "hedge.present true on side %s but profile_ids.hedge_%s is null and no hedge.profile_id given" % (sd, sd))

        # overlap / tuck rule across the profiles painted on this spline
        for rid in road_ids_on_spline:
            rp = proads.get(rid, {})
            for eid in edge_ids_on_spline:
                ep = pedges.get(eid, {})
                if not (ep.get("tuck_depth_m", 0.03) > rp.get("skirt_drop_m", 0.02)):
                    rep.error(where, "EdgeProfile '%s' tuck_depth_m %r must exceed RoadProfile '%s' skirt_drop_m %r" % (
                        eid, ep.get("tuck_depth_m", 0.03), rid, rp.get("skirt_drop_m", 0.02)))
        if road_kind == "rail" and (pids.get("edge_left") or pids.get("edge_right")):
            rep.info(where, "rail spline with edge profiles (allowed: ballast shoulder kerb line)")

        for di, dk in enumerate(sp.get("drop_kerbs", [])):
            sides = ["left", "right"] if dk.get("side") == "both" else [dk.get("side")]
            for sd in sides:
                if pids.get("edge_" + sd) is None:
                    rep.warn("%s.drop_kerbs[%d]" % (where, di), "drop kerb on side %s but profile_ids.edge_%s is null" % (sd, sd))

        src = sp.get("source", {})
        if src.get("layer") != "authored" and "overlay" not in sp:
            rep.warn(where, "overlay missing on a non-authored spline")
        pts = sp.get("points", [])
        if len(pts) >= 2:
            spline_end_points[sid] = ((pts[0]["x"], pts[0]["y"]), (pts[-1]["x"], pts[-1]["y"]))

    # junctions
    junction_ids = set()
    for ji, j in enumerate(doc.get("junctions", []) or []):
        jw = "%s junctions[%d] (%s)" % (label, ji, j.get("id"))
        if j.get("id") in junction_ids:
            rep.error(jw, "duplicate junction id")
        junction_ids.add(j.get("id"))
        for ei, e in enumerate(j.get("ends", [])):
            ends = spline_end_points.get(e.get("spline_id"))
            if ends is None:
                rep.error("%s.ends[%d]" % (jw, ei), "spline_id %r is not in this document" % e.get("spline_id"))
                continue
            p = ends[0] if e.get("end") == "start" else ends[1]
            d = math.hypot(p[0] - j["x"], p[1] - j["y"])
            if d > JUNCTION_SNAP_M:
                rep.error("%s.ends[%d]" % (jw, ei), "spline %s %s is %.3f m from the junction (> %.1f)" % (e.get("spline_id"), e.get("end"), d, JUNCTION_SNAP_M))
    for si, sp in enumerate(doc.get("splines", [])):
        for slot in ("junction_start", "junction_end"):
            v = sp.get(slot)
            if v is not None and v not in junction_ids:
                rep.warn("%s splines[%d].%s" % (label, si, slot), "junction id %r is not in junctions[]" % v)

    # materials
    used_materials.discard(None)
    unhinted = sorted(m for m in used_materials if m not in NORMATIVE_MATERIALS)
    for m in unhinted:
        rep.warn(label, "material %r is outside the SCHEMA.md 7 normative set (unhinted)" % m)
    missing_hint = sorted(m for m in used_materials if m not in doc_materials)
    if doc_materials and missing_hint:
        rep.info(label, "materials used but without a preview hint in this document: %s" % ", ".join(missing_hint))
    unused_hint = sorted(m for m in doc_materials if m not in used_materials)
    if unused_hint:
        rep.info(label, "preview hints never used by geometry: %s" % ", ".join(unused_hint))
    return {"materials_used": used_materials, "referenced": referenced}


# --------------------------------------------------------------------------------------------
# Geometry (numpy) — SCHEMA.md 3.1 curve, 3.2 stations
# --------------------------------------------------------------------------------------------

def catmull_rom_dense(P):
    """Centripetal Catmull-Rom (alpha 0.5, Barry-Goldman) through P (K x 2), SCHEMA.md 3.1.
    Returns (dense points, cumulative s, s at each knot)."""
    P = np.asarray(P, dtype=float)
    K = len(P)
    if K == 2:
        chord = float(np.linalg.norm(P[1] - P[0]))
        n = max(8, int(math.ceil(chord / 0.1))) + 1
        t = np.linspace(0.0, 1.0, n)[:, None]
        dense = P[0] + t * (P[1] - P[0])
        seg = np.linalg.norm(np.diff(dense, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        return dense, s, np.array([0.0, s[-1]])
    ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    pieces = []
    knot_s = [0.0]
    total = 0.0
    for i in range(K - 1):
        P0, P1, P2, P3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        chord = float(np.linalg.norm(P2 - P1))
        n = max(8, int(math.ceil(chord / 0.1))) + 1
        t0 = 0.0
        t1 = t0 + np.linalg.norm(P1 - P0) ** 0.5
        t2 = t1 + np.linalg.norm(P2 - P1) ** 0.5
        t3 = t2 + np.linalg.norm(P3 - P2) ** 0.5
        t = np.linspace(t1, t2, n)[:, None]
        A1 = (t1 - t) / (t1 - t0) * P0 + (t - t0) / (t1 - t0) * P1
        A2 = (t2 - t) / (t2 - t1) * P1 + (t - t1) / (t2 - t1) * P2
        A3 = (t3 - t) / (t3 - t2) * P2 + (t - t2) / (t3 - t2) * P3
        B1 = (t2 - t) / (t2 - t0) * A1 + (t - t0) / (t2 - t0) * A2
        B2 = (t3 - t) / (t3 - t1) * A2 + (t - t1) / (t3 - t1) * A3
        C = (t2 - t) / (t2 - t1) * B1 + (t - t1) / (t2 - t1) * B2
        seg = np.linalg.norm(np.diff(C, axis=0), axis=1)
        total += float(seg.sum())
        knot_s.append(total)
        pieces.append(C if i == 0 else C[1:])
    dense = np.vstack(pieces)
    seg = np.linalg.norm(np.diff(dense, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    return dense, s, np.array(knot_s)


def stations_for_straight(L, sampling, mandatory):
    """SCHEMA.md 3.2 march for kappa = 0 (straight) plus mandatory stations and the merge rule."""
    step = sampling.get("step_m", 2.0)
    min_step = sampling.get("min_step_m", 0.25)
    adaptive = [0.0]
    s = 0.0
    while s + step < L - min_step:
        s += step
        adaptive.append(s)
    adaptive.append(L)
    mand = sorted(set(m for m in mandatory if 0.0 < m < L))
    keep = [a for a in adaptive if all(abs(a - m) > min_step / 2 for m in mand)]
    st = sorted(set(keep) | set(mand))
    return np.array(st)


def spline_s_ranges(sp, doc):
    """Every (label, s0, s1) interval a spline references: segments, drop kerbs, markings and
    the profile-level lists of the profiles it uses. s1 None -> end."""
    out = []
    pids = sp.get("profile_ids", {})
    prof = doc.get("profiles", {})
    for gi, seg in enumerate(sp.get("segments", [])):
        out.append(("segments[%d] %s" % (gi, seg.get("id")), seg.get("s0_m", 0), seg.get("s1_m")))
        ramp = seg.get("ramp_m", (sp.get("sampling") or {}).get("width_ramp_m", 5.0))
        road = seg.get("road") or {}
        for lk in ("markings", "markings_add"):
            for mi, m in enumerate(road.get(lk, [])):
                if "s0_m" in m or "s1_m" in m:
                    out.append(("segments[%d].road.%s[%d]" % (gi, lk, mi), m.get("s0_m", 0), m.get("s1_m")))
    for di, dk in enumerate(sp.get("drop_kerbs", [])):
        s0 = dk["s_m"] - dk.get("ramp_m", 0.915)
        s1 = dk["s_m"] + dk.get("length_m", 1.83) + dk.get("ramp_m", 0.915)
        out.append(("drop_kerbs[%d] (%s) incl. ramps" % (di, dk.get("side")), s0, s1))
    rid = pids.get("road")
    if rid and rid in prof.get("road", {}):
        for mi, m in enumerate(prof["road"][rid].get("markings", [])):
            if "s0_m" in m or "s1_m" in m:
                out.append(("profile road %s markings[%d]" % (rid, mi), m.get("s0_m", 0), m.get("s1_m")))
    for slot in ("edge_left", "edge_right"):
        eid = pids.get(slot)
        if eid and eid in prof.get("edge", {}):
            ep = prof["edge"][eid]
            for bi, b in enumerate(ep.get("barriers", [])):
                out.append(("profile edge %s barriers[%d]" % (eid, bi), b.get("s0_m", 0), b.get("s1_m")))
            for ei, e in enumerate(ep.get("embankments", [])):
                out.append(("profile edge %s embankments[%d]" % (eid, ei), e.get("s0_m", 0), e.get("s1_m")))
            for di, dk in enumerate(ep.get("drop_kerbs", [])):
                out.append(("profile edge %s drop_kerbs[%d]" % (eid, di), dk["s_m"] - dk.get("ramp_m", 0.915),
                            dk["s_m"] + dk.get("length_m", 1.83) + dk.get("ramp_m", 0.915)))
    for slot in ("hedge_left", "hedge_right"):
        hid = pids.get(slot)
        if hid and hid in prof.get("hedge", {}):
            for hi, hs in enumerate(prof["hedge"][hid].get("segments", [])):
                out.append(("profile hedge %s segments[%d]" % (hid, hi), hs.get("s0_m", 0), hs.get("s1_m")))
    return out


def geometry_checks(doc, label, rep, site_bbox=None, spacing=(0.5, 20.0)):
    """Numpy sanity on every spline. site_bbox = (E0, E1, N0, N1) in CRS metres, optional."""
    results = {}
    origin = doc.get("origin", {})
    E0, N0 = origin.get("E", 0), origin.get("N", 0)
    for si, sp in enumerate(doc.get("splines", [])):
        where = "%s splines[%d] (%s)" % (label, si, sp.get("id"))
        pts = sp.get("points", [])
        xy = np.array([[p["x"], p["y"]] for p in pts], dtype=float)
        if not np.all(np.isfinite(xy)):
            rep.error(where, "non-finite point coordinates")
            continue
        for p in pts:
            for k in ("z", "roll_deg", "width_m"):
                v = p.get(k)
                if isinstance(v, float) and not math.isfinite(v):
                    rep.error(where, "non-finite %s" % k)
        # duplicates (SCHEMA.md 3.1 merges |dP| < 1e-6)
        d = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        n_dup = int(np.sum(d < 1e-6))
        if n_dup:
            rep.warn(where, "%d consecutive duplicate point(s) (< 1e-6 m) will be merged by the reader" % n_dup)
        keep = np.concatenate([[True], d >= 1e-6])
        xy = xy[keep]
        if len(xy) < 2:
            rep.error(where, "fewer than 2 distinct points")
            continue
        d = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        lo, hi = spacing
        for i, di in enumerate(d):
            if di < lo or di > hi:
                rep.warn(where, "point spacing %d->%d is %.2f m (outside %.1f..%.1f m band)" % (i, i + 1, di, lo, hi))
        # bbox in CRS
        if site_bbox is not None:
            E = xy[:, 0] + E0
            N = xy[:, 1] + N0
            e0, e1, n0, n1 = site_bbox
            inside = (E >= e0) & (E <= e1) & (N >= n0) & (N <= n1)
            if not inside.all():
                rep.error(where, "%d point(s) outside site bbox E %s..%s N %s..%s" % (int((~inside).sum()), e0, e1, n0, n1))
            ov = sp.get("overlay")
            if ov:
                oxy = np.array([[q[0], q[1]] for q in ov["pts"]], dtype=float)
                oin = (oxy[:, 0] + E0 >= e0) & (oxy[:, 0] + E0 <= e1) & (oxy[:, 1] + N0 >= n0) & (oxy[:, 1] + N0 <= n1)
                if not oin.all():
                    rep.error(where, "overlay has %d point(s) outside the site bbox" % int((~oin).sum()))
        # arc length
        L_chord = float(d.sum())
        dense, s_dense, knot_s = catmull_rom_dense(xy)
        L = float(s_dense[-1])
        if not np.all(np.diff(s_dense) >= 0):
            rep.error(where, "dense s not monotone")
        results[sp.get("id")] = {"L_chord": L_chord, "L_cr": L, "knot_s": knot_s.tolist()}
        rep.line("  %s: %d points, chord length %.3f m, Catmull-Rom length %.3f m" % (sp.get("id"), len(xy), L_chord, L))
        # width knots
        widths = [p.get("width_m") for p in pts]
        wk = [(round(float(knot_s[i]), 3), widths[i]) for i in range(len(pts)) if i < len(knot_s) and widths[i] is not None]
        distinct = sorted(set(w for _, w in wk))
        if wk:
            rep.line("    width knots (s, w): %s" % ", ".join("(%.2f, %s)" % (s_, w) for s_, w in wk if True))
            rep.line("    distinct widths: %s -> width change %s" % (distinct, "defined" if len(distinct) > 1 else "none"))
            if len(distinct) > 1:
                # linear interpolation consistency at interior knots that set a value strictly between neighbours
                for i in range(1, len(wk) - 1):
                    s0, w0 = wk[i - 1]
                    s1, w1 = wk[i]
                    s2, w2 = wk[i + 1]
                    if w0 != w2 and min(w0, w2) < w1 < max(w0, w2) and s2 > s0:
                        w_lin = w0 + (w2 - w0) * (s1 - s0) / (s2 - s0)
                        rep.line("    interior width knot at s=%.2f: w=%s, linear between neighbours would be %.4f (diff %.4f)" % (s1, w1, w_lin, w1 - w_lin))
        # s-ranges vs L
        for lbl, s0, s1 in spline_s_ranges(sp, doc):
            s1v = L if s1 is None else s1
            if s0 < 0 or s0 > L + 0.01:
                rep.error(where, "%s: s0 %.3f outside [0, L=%.3f]" % (lbl, s0, L))
            if s1v > L + 0.01:
                rep.error(where, "%s: s1 %.3f > L=%.3f (+0.01)" % (lbl, s1v, L))
            if s1v < s0:
                rep.error(where, "%s: s1 %.3f < s0 %.3f" % (lbl, s1v, s0))
        # overlay finite
        ov = sp.get("overlay")
        if ov:
            arr = np.array([[q[0], q[1]] for q in ov["pts"]], dtype=float)
            if not np.all(np.isfinite(arr)):
                rep.error(where, "overlay contains non-finite coordinates")
    return results


def synthetic_expectations(doc, label, rep, geom):
    """Reproduce the SCHEMA.md 9.3 numbers for examples/synthetic_straight.json from the file."""
    sp = doc["splines"][0]
    rp = doc["profiles"]["road"][sp["profile_ids"]["road"]]
    ep = doc["profiles"]["edge"][sp["profile_ids"]["edge_left"]]
    sampling = sp.get("sampling", {})
    L = geom[sp["id"]]["L_cr"]
    pts = sp["points"]
    xs = np.array([p["x"] for p in pts])
    ys = np.array([p["y"] for p in pts])
    knots = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(ys)))])
    wk = np.array([p.get("width_m", rp["width_m"]) for p in pts], dtype=float)

    def w(s):
        return float(np.interp(s, knots, wk))

    exp = {}
    checks = []

    def check(name, got, want, tol=1e-9):
        ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
        checks.append((name, got, want, ok))
        if not ok:
            rep.error("%s 9.3 %s" % (label, name), "got %r, SCHEMA.md 9.3 says %r" % (got, want))

    check("L", L, 100.0, 1e-9)
    mandatory = list(knots)
    for dk in sp.get("drop_kerbs", []):
        s_, ln, rm = dk["s_m"], dk.get("length_m", 1.83), dk.get("ramp_m", 0.915)
        mandatory += [s_ - rm, s_, s_ + ln, s_ + ln + rm]
    for m in rp.get("markings", []):
        if "s0_m" in m:
            mandatory.append(m["s0_m"])
        if m.get("s1_m") is not None:
            mandatory.append(m["s1_m"])
    mandatory += sampling.get("extra_stations_m", [])
    st = stations_for_straight(L, sampling, mandatory)
    gaps = np.diff(st)
    check("stations N", int(len(st)), 54)
    off_grid = [round(float(x), 3) for x in st if abs(x / 2.0 - round(x / 2.0)) > 1e-9]
    rep.line("    stations off the 2 m grid: %s" % off_grid)
    check("min gap", round(float(gaps.min()), 3), 0.17, 1e-6)
    check("max gap", round(float(gaps.max()), 3), 2.0, 1e-9)
    check("w(45)", w(45.0), 7.0)
    check("w(40)", w(40.0), 6.0)
    check("w(50)", w(50.0), 8.0)
    w_max = float(wk.max())
    check("w_max", w_max, 8.0)
    lss = rp.get("lateral_station_spacing_m", 1.0)
    n_int = max(7, 2 * int(math.ceil(w_max / (2 * lss))) + 1)
    check("n_int", n_int, 9)
    rows = n_int + 2
    check("ribbon rows", rows, 11)
    check("ribbon vertices", rows * len(st), 594)
    check("ribbon triangles", 2 * (rows - 1) * (len(st) - 1), 1060)
    check("overlap_m", rp.get("overlap_m", 0.04), 0.040)
    # drop kerb numbers
    dk = sp["drop_kerbs"][0]
    kh = ep["kerb_height_m"]
    tgt = dk.get("target_height_m", 0.006)
    ln, rm = dk.get("length_m", 1.83), dk.get("ramp_m", 0.915)
    s_flat_c = dk["s_m"] + ln / 2
    check("flat-run centre s", s_flat_c, 70.915, 1e-9)
    check("hk(flat centre)", tgt, 0.006, 1e-9)
    f_mid = 0.5 ** 2 * (3 - 2 * 0.5)
    hk_mid = kh * (1 - f_mid) + tgt * f_mid
    check("ramp midpoint s (down)", dk["s_m"] - rm / 2, 69.5425, 1e-9)
    check("ramp midpoint s (up)", dk["s_m"] + ln + rm / 2, 72.2875, 1e-9)
    check("hk(ramp midpoint)", hk_mid, 0.0655, 1e-9)
    pw = ep["pavement_width_m"]
    cf = ep.get("pavement_crossfall_pct", 2.5) / 100
    mcf = ep.get("pavement_max_crossfall_pct", 8.0) / 100
    hk_back = min(kh + pw * cf, tgt + pw * mcf)
    check("back edge F in flat run", round(hk_back, 6), 0.150, 1e-9)
    check("kerb row B", -ep.get("tuck_depth_m", 0.03), -0.03, 1e-9)
    check("kerb row A o", -ep.get("tuck_in_m", 0.02), -0.02, 1e-9)
    # markings
    cd = [m for m in rp["markings"] if m["id"] == "centre_1004"][0]
    period = cd["dash_m"] + cd["gap_m"]
    n_dash = 0
    k = 0
    dashes = []
    while cd.get("phase_m", 0) + k * period < L - 1e-9:
        a = cd.get("phase_m", 0) + k * period
        b = min(a + cd["dash_m"], L)
        dashes.append((a, b))
        k += 1
    check("centre dashes", len(dashes), 17)
    check("first dash", dashes[0], (0.0, 4.0))
    check("last dash", dashes[-1], (96.0, 100.0))
    check("dash strip half width", cd["width_m"] / 2, 0.05, 1e-12)
    dy = [m for m in rp["markings"] if m["id"] == "dyl_left_1018_1"][0]
    pair_c = dy["offset_m"]
    half = dy["width_m"] / 2 + dy["double_gap_m"] / 2
    check("dyl pair centre inward", pair_c, 0.25, 1e-12)
    check("dyl line centres inward", (round(pair_c + half, 6), round(pair_c - half, 6)), (0.35, 0.15))
    check("dyl edge shift 40->45", (w(45.0) - w(40.0)) / 2, 0.5, 1e-9)
    check("lift_m", dy.get("lift_m", 0.004), 0.004, 1e-12)
    # sampling tuple as written in 9.3
    order = ["step_m", "min_step_m", "curvature_gain", "smoothing_window_m", "smoothing_passes", "width_ramp_m",
             "bank_max_deg", "bank_probe_min_half_width_m", "pin_blend_m", "bank_rate_max_deg_per_m"]
    check("sampling tuple", [sampling.get(k) for k in order], [2.0, 0.25, 20.0, 20.0, 1, 5.0, 4.0, 1.5, 10.0, 0.25])
    ok_n = sum(1 for c in checks if c[3])
    rep.line("    SCHEMA.md 9.3 expectations reproduced from the file: %d/%d" % (ok_n, len(checks)))
    for name, got, want, ok in checks:
        rep.line("      %s %s: %s%s" % ("ok " if ok else "BAD", name, got, "" if ok else " (expected %s)" % (want,)))


# --------------------------------------------------------------------------------------------
# SCHEMA.md 4 <-> schema coverage
# --------------------------------------------------------------------------------------------

def docs_coverage(schema, md_text, rep):
    m = re.search(r"^## 4\..*?(?=^## 5\.)", md_text, re.S | re.M)
    sec4 = m.group(0) if m else md_text
    code_spans = re.findall(r"`([^`]*)`", sec4)
    tokens = set()
    for span in code_spans:
        for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", span):
            tokens.add(tok)
    # every $def documented?
    defs = schema.get("$defs", {})
    primitives = {"Id", "NonNeg", "Pos", "SideOrBoth", "SEnd", "MaterialName", "XYZ"}
    undocumented_defs = []
    for name in defs:
        if name in primitives:
            continue
        if not re.search(r"`%s`|\b%s\b" % (name, name), sec4):
            undocumented_defs.append(name)
    # every property documented?
    schema_props = {}

    def walk(node, owner):
        if isinstance(node, dict):
            for k, v in node.get("properties", {}).items():
                schema_props.setdefault(k, set()).add(owner)
                walk(v, owner + "." + k)
            for kw in ("items", "additionalProperties", "then", "else", "if", "not"):
                if kw in node and isinstance(node[kw], dict):
                    walk(node[kw], owner)
            for kw in ("allOf", "anyOf", "oneOf", "prefixItems"):
                for sub in node.get(kw, []) or []:
                    walk(sub, owner)
            for k, v in node.get("patternProperties", {}).items():
                walk(v, owner)
    walk(schema, "root")
    for name, d in defs.items():
        walk(d, name)
    undocumented_props = sorted((k, sorted(v)) for k, v in schema_props.items() if k not in tokens)
    # every documented snake_case field present in the schema?
    doc_fields = set(t for t in tokens if re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)+|[a-z]{2,}", t))
    known_non_fields = set("""
        m deg pct int m2 s0 s1 s w c d h o kw pw cf hk kh max_cf edge_offset edge_offset_L edge_offset_R
        n_int w_max z_ref z_edge z_back_edge dz terrain h0 hk_back o_b crossfall frac floor
        smoothstep centre edge_left edge_right road rail edge hedge left right both none disc start end
        seam way gap osm_way step06_smoothed other roads barriers authored parabolic planar solid dashed
        double radius chamfer batter retaining_wall auto downhill uphill flat rounded domed cards instances
        merged brick_wall stone_wall concrete_wall chain_link wood_fence railing guard_rail thanet margate
        null true false required and or of not the a to in at is per iff
        centre_1004 warning_1004_1 lane_1005 edge_left_1012_1 dyl_left_1018_1 syl_left_1017 white_paint
        yellow_paint edge_uk_kerb edge_uk_half_grass edge_wall_brick edge_chain_link edge_railing hedge_privet
        edge_barrier_only rail_standard road_trinity road_residential road_trunk road_primary road_secondary
        road_tertiary road_unclassified road_living_street road_service road_pedestrian path_footway
        path_cycleway path_track coping_concrete post_steel unreal py sources adapters profiles examples
        test_stretch json synthetic_straight sha hand authored fixture name lit
        ImportProfiles io_json load_profile_file straight_100 dtm_ma15_s_z interp s_knots w_knots
        apply_ramped_override H W R L N K p j n k x y z r hw_i lerp clip min max abs atan2 MA
        EdgeProfile RoadProfile HedgeProfile Marking Camber Sampling RailSpec RailSection Sleeper Ballast Lip
        SplitMaterial DropKerb SplineDropKerb BarrierSegment BarrierInline BarrierType Embankment
        EmbankmentInline HedgeSegment Foliage Spline Point Source Segment SegmentRoad SegmentEdge
        SegmentHedge Overlay Junction ProfileFile ProfileIds Continuation OverrunPoints Flags MaterialHint
        Id SEnd NonNeg Pos XYZ
        _tile _profile_ids_used _z_06 tile_m bounds_local x0 y0 x1 y1 SaveSite Plugins Streetscape
        UStreetMaterialTable UE step ramp pin blend len target width height offset inner outer
        ODN EPSG ma dp E0 N0 bpy sum Delta pts side kind mode
    """.split())
    fields_not_in_schema = sorted(t for t in doc_fields if t not in schema_props and t not in known_non_fields)
    return undocumented_defs, undocumented_props, fields_not_in_schema


# --------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------

def load_json(path, rep):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        rep.error(path, "invalid JSON: %s" % e)
        return None


def validate_files(paths, schema_path=None):
    """STAGES.md 0.9 mode: `schema_check.py <file>...` prints VALID / INVALID per file; exit 0 iff all valid.
    A file with top-level keys kind/id/profile is a library profile file (validated against
    $defs/ProfileFile + the inner profile def); anything else is a site document (root schema)."""
    here = os.path.abspath(os.path.dirname(__file__))
    if schema_path is None:
        cand = here
        for _ in range(6):
            sp = os.path.join(cand, "schema", "streetscape.schema.json")
            if os.path.isfile(sp):
                schema_path = sp
                break
            cand = os.path.dirname(cand)
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    V = SchemaValidator(schema)
    kind_def = {"road": "RoadProfile", "edge": "EdgeProfile", "hedge": "HedgeProfile"}
    n_bad = 0
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print("INVALID %s: %s" % (path, e))
            n_bad += 1
            continue
        if isinstance(data, dict) and {"kind", "id", "profile"} <= set(data):
            errs = V.validate(data, schema["$defs"]["ProfileFile"], "$")
            kind = data.get("kind")
            if kind in kind_def and isinstance(data.get("profile"), dict):
                errs += V.validate(data["profile"], schema["$defs"][kind_def[kind]], "$.profile")
            if data.get("id") != os.path.splitext(os.path.basename(path))[0]:
                errs.append(("$.id", "id %r != file name" % data.get("id")))
        else:
            errs = V.validate(data, schema, "$")
            if not errs:
                rep = Report()
                semantic_document_checks(data, os.path.basename(path), rep, {"road": set(), "edge": set(), "hedge": set()})
                errs += [(e.split(": ", 1)[0], e.split(": ", 1)[-1]) for e in rep.errors]
        if V.unsupported:
            errs.append(("$", "schema uses unsupported keywords %s" % sorted(V.unsupported)))
        if errs:
            n_bad += 1
            print("INVALID %s: %d error(s)" % (path, len(errs)))
            for p_, m in errs[:20]:
                print("    %s: %s" % (p_, m))
        else:
            print("VALID %s" % path)
    print("%d file(s), %d invalid" % (len(paths), n_bad))
    return 0 if n_bad == 0 else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-"):
        return validate_files(argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.abspath(os.path.dirname(__file__))
    ap.add_argument("--root", default=None, help="projects/one directory (default: derived from the repo)")
    ap.add_argument("--schema", default=None)
    ap.add_argument("--profiles", default=None)
    ap.add_argument("--examples", default=None)
    ap.add_argument("--md", default=None, help="SCHEMA.md for the coverage check ('' to skip)")
    ap.add_argument("--no-geometry", action="store_true")
    ap.add_argument("--no-docs", action="store_true")
    args = ap.parse_args(argv)

    root = args.root
    if root is None:
        # scratchpad or Tools/ copy: look for a projects/one ancestor, else the canonical repo path
        cand = here
        for _ in range(6):
            if os.path.isfile(os.path.join(cand, "schema", "streetscape.schema.json")):
                root = cand
                break
            cand = os.path.dirname(cand)
        if root is None:
            root = os.path.join("C:/Users/Shadow/code/3duk", "projects", "one")
    schema_path = args.schema or os.path.join(root, "schema", "streetscape.schema.json")
    profiles_dir = args.profiles or os.path.join(root, "schema", "profiles")
    examples_dir = args.examples or os.path.join(root, "schema", "examples")
    md_path = args.md if args.md is not None else os.path.join(root, "docs", "SCHEMA.md")

    rep = Report()
    rep.line("validate_streetscape.py")
    rep.line("  schema   : %s" % schema_path)
    rep.line("  profiles : %s" % profiles_dir)
    rep.line("  examples : %s" % examples_dir)
    rep.line("  numpy    : %s" % (np.__version__ if np is not None else "ABSENT"))

    schema = load_json(schema_path, rep)
    if schema is None:
        return finish(rep)
    V = SchemaValidator(schema)

    # -- 0. schema self-check: every $ref resolves, no unsupported keywords -------------------
    refs = set()

    def collect_refs(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str):
                    refs.add(v)
                else:
                    collect_refs(v)
        elif isinstance(node, list):
            for v in node:
                collect_refs(v)
    collect_refs(schema)
    for r in sorted(refs):
        if V.resolve_ref(r) is None:
            rep.error(schema_path, "$ref %s does not resolve" % r)
    rep.line("  schema: %d $defs, %d distinct $refs, all resolve: %s" % (len(schema.get("$defs", {})), len(refs), not V.unresolved_refs))
    # every $def referenced somewhere (or is the root)?
    used_defs = set(r.split("/")[-1] for r in refs if r.startswith("#/$defs/"))
    unused = sorted(d for d in schema.get("$defs", {}) if d not in used_defs)
    rep.line("  $defs never referenced by a $ref (entry points): %s" % unused)

    # -- 1. profiles ---------------------------------------------------------------------------
    rep.line("")
    rep.line("== 1. Profile files (wrapper vs $defs/ProfileFile; inner profile vs $defs/<Kind>Profile)")
    library_ids = {"road": set(), "edge": set(), "hedge": set()}
    library_profiles = {"road": {}, "edge": {}, "hedge": {}}
    kind_def = {"road": "RoadProfile", "edge": "EdgeProfile", "hedge": "HedgeProfile"}
    pfiles = sorted(f for f in os.listdir(profiles_dir) if f.endswith(".json"))
    for f in pfiles:
        path = os.path.join(profiles_dir, f)
        data = load_json(path, rep)
        if data is None:
            continue
        errs = V.validate(data, schema["$defs"]["ProfileFile"], "$")
        kind = data.get("kind")
        if kind in kind_def and isinstance(data.get("profile"), dict):
            errs += V.validate(data["profile"], schema["$defs"][kind_def[kind]], "$.profile")
        if data.get("id") != f[:-5]:
            errs.append(("$.id", "id %r != file name %r" % (data.get("id"), f[:-5])))
        for p, m in errs:
            rep.error("profiles/%s %s" % (f, p), m)
        if kind in library_ids:
            library_ids[kind].add(data.get("id"))
            library_profiles[kind][data.get("id")] = data.get("profile")
        rep.line("  %-28s kind=%-5s %s" % (f, kind, "OK" if not errs else "%d error(s)" % len(errs)))
    # semantic checks over the library as one pseudo-document
    pseudo = {"profiles": library_profiles, "splines": [], "junctions": [], "materials": {}}
    semantic_document_checks(pseudo, "profiles/*", rep, library_ids)
    # MaterialName description vs normative set
    desc = schema["$defs"]["MaterialName"].get("description", "")
    m = re.search(r"default set:\s*(.*?)\.\s*$", desc)
    if m:
        listed = set(x.strip() for x in m.group(1).split(","))
        if listed != NORMATIVE_MATERIALS:
            rep.error(schema_path + " $defs.MaterialName.description", "material list differs from SCHEMA.md 7: only-schema %s, only-md %s" % (
                sorted(listed - NORMATIVE_MATERIALS), sorted(NORMATIVE_MATERIALS - listed)))
        else:
            rep.line("  MaterialName.description default set == SCHEMA.md 7 normative set (%d names)" % len(listed))
    if md_path and os.path.isfile(md_path):
        md_text = open(md_path, "r", encoding="utf-8").read()
        m1 = re.search(r"The 20 library profiles:\s*`([^`]*)`", md_text)
        if m1:
            listed = set(x.strip() for x in m1.group(1).replace("\n", " ").split(","))
            all_ids = set().union(*library_ids.values())
            if listed != all_ids:
                rep.error(md_path + " section 1", "library profile list differs from schema/profiles: only-md %s, only-files %s" % (
                    sorted(listed - all_ids), sorted(all_ids - listed)))
            else:
                rep.line("  SCHEMA.md 1 library list == schema/profiles (%d ids)" % len(listed))

    # -- 2. examples ---------------------------------------------------------------------------
    rep.line("")
    rep.line("== 2. Examples (root schema + SCHEMA.md 8 rules + geometry)")
    efiles = sorted(f for f in os.listdir(examples_dir) if f.endswith(".json"))
    for f in efiles:
        path = os.path.join(examples_dir, f)
        doc = load_json(path, rep)
        if doc is None:
            continue
        errs = V.validate(doc, schema, "$")
        for p, m in errs:
            rep.error("examples/%s %s" % (f, p), m)
        rep.line("  %-28s schema: %s" % (f, "OK" if not errs else "%d error(s)" % len(errs)))
        label = "examples/%s" % f
        info = semantic_document_checks(doc, label, rep, library_ids)
        # referenced ids vs the library (task item 2)
        for kind, ids in info["referenced"].items():
            for pid in sorted(ids):
                inline = pid in (doc.get("profiles", {}).get(kind) or {})
                inlib = pid in library_ids[kind]
                same = None
                if inline and inlib:
                    same = json_equal(doc["profiles"][kind][pid], library_profiles[kind][pid])
                rep.line("    ref %-6s %-22s inline=%s library=%s%s" % (kind, pid, inline, inlib,
                         "" if same is None else (" identical-to-library" if same else " DIFFERS-from-library")))
                if not inline and not inlib:
                    rep.error(label, "profile %s/%s neither inline nor in schema/profiles" % (kind, pid))
        mats = sorted(info["materials_used"])
        rep.line("    materials used: %s" % ", ".join(mats))
        if not args.no_geometry and np is not None:
            bbox = None
            if doc.get("site") == "thanet":
                bbox = (632800, 639456, 168200, 171784)   # Margate grid, per task
            geom = geometry_checks(doc, label, rep, site_bbox=bbox)
            if f == "synthetic_straight.json":
                synthetic_expectations(doc, label, rep, geom)
            if f == "test_stretch.json":
                g = geom[doc["splines"][0]["id"]]
                rep.line("    SCHEMA.md 9.1 says L = 171.40 +- 0.05 (06 polyline 171.39, Catmull-Rom 171.41): CR here %.3f -> %s" % (
                    g["L_cr"], "consistent" if abs(g["L_cr"] - 171.40) <= 0.05 else "INCONSISTENT"))
                ks = g["knot_s"]
                rep.line("    knot s of points 10/11/12 (taper): %.2f / %.2f / %.2f (9.1 says 140.2 / 145.0 / 150.2)" % (ks[9], ks[10], ks[11]))
                if abs(ks[9] - 140.2) > 0.1 or abs(ks[10] - 145.0) > 0.1 or abs(ks[11] - 150.2) > 0.1:
                    rep.error(label, "taper knot s values differ from SCHEMA.md 9.1 by > 0.1 m")
                p0 = doc["splines"][0]["points"][0]
                ue = (round(100 * p0["x"]), round(-100 * p0["y"]), round(100 * p0.get("_z_06", 0)))
                rep.line("    UE start of points[0] (100x, -100y, 100z_06) = %s (9.1 says (809998, -817112, 2056))" % (ue,))
                if ue != (809998, -817112, 2056):
                    rep.error(label, "UE start differs from SCHEMA.md 9.1")

    # -- 3. docs coverage ----------------------------------------------------------------------
    if not args.no_docs and md_path and os.path.isfile(md_path):
        rep.line("")
        rep.line("== 3. SCHEMA.md 4 <-> schema coverage")
        md_text = open(md_path, "r", encoding="utf-8").read()
        und_defs, und_props, extra_fields = docs_coverage(schema, md_text, rep)
        rep.line("  $defs not mentioned in SCHEMA.md 4: %s" % (und_defs or "none"))
        rep.line("  schema properties not mentioned in SCHEMA.md 4: %s" % (["%s (%s)" % (k, ",".join(o)) for k, o in und_props] or "none"))
        rep.line("  snake_case fields in SCHEMA.md 4 that are not schema properties (after filtering known symbols): %s" % (extra_fields or "none"))
        for k, o in und_props:
            rep.warn("SCHEMA.md 4", "property %r of %s is not documented" % (k, ",".join(o)))
        for d in und_defs:
            rep.warn("SCHEMA.md 4", "$def %r is not documented" % d)

    if V.unsupported:
        for kw in sorted(V.unsupported):
            rep.error(schema_path, "schema uses keyword %r that this validator does not implement" % kw)
    return finish(rep)


def finish(rep):
    out = []
    out.extend(rep.lines)
    out.append("")
    out.append("== ERRORS (%d)" % len(rep.errors))
    out.extend("  " + e for e in rep.errors)
    out.append("== WARNINGS (%d)" % len(rep.warnings))
    out.extend("  " + w for w in rep.warnings)
    out.append("== INFO (%d)" % len(rep.infos))
    out.extend("  " + i for i in rep.infos)
    out.append("")
    out.append("RESULT: %s" % ("GREEN (no errors)" if not rep.errors else "RED (%d errors)" % len(rep.errors)))
    print("\n".join(out))
    return 0 if not rep.errors else 1


if __name__ == "__main__":
    sys.exit(main())
