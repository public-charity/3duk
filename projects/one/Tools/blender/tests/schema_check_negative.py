"""Negative tests: mutate valid documents and assert the validator reports an error at the right path."""
import copy, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_streetscape import SchemaValidator, Report, semantic_document_checks

ROOT = "C:/Users/Shadow/code/3duk/projects/one"
schema = json.load(open(os.path.join(ROOT, "schema/streetscape.schema.json"), encoding="utf-8"))
doc = json.load(open(os.path.join(ROOT, "schema/examples/test_stretch.json"), encoding="utf-8"))
pf = json.load(open(os.path.join(ROOT, "schema/profiles/rail_standard.json"), encoding="utf-8"))
V = SchemaValidator(schema)

cases = []

def case(name, mutate, expect_substr, target="doc"):
    cases.append((name, mutate, expect_substr, target))

def m(fn):
    return fn

case("unknown root key", lambda d: d.__setitem__("foo", 1), "additional property 'foo'")
case("underscore root key allowed", lambda d: d.__setitem__("_foo", {"a": 1}), None)
case("wrong frame", lambda d: d.__setitem__("frame", "unreal cm"), "expected const")
case("schema_version 2.0.0", lambda d: d.__setitem__("schema_version", "2.0.0"), "does not match pattern")
case("crs pattern", lambda d: d.__setitem__("crs", "27700"), "does not match pattern")
case("origin missing N", lambda d: d["origin"].pop("N"), "missing required property 'N'")
case("profiles missing hedge map", lambda d: d["profiles"].pop("hedge"), "missing required property 'hedge'")
case("dashed without dash_m", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][0].pop("dash_m"), "missing required property 'dash_m'")
case("double without double_gap_m", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][1].pop("double_gap_m"), "missing required property 'double_gap_m'")
case("marking pattern enum", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][0].__setitem__("pattern", "dotted"), "not in enum")
case("marking lift_m too big", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][0].__setitem__("lift_m", 0.05), "> maximum")
case("marking width_m zero (Pos)", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][0].__setitem__("width_m", 0), "exclusiveMinimum")
case("marking s1_m null ok", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][1].__setitem__("s1_m", None), None)
case("marking s1_m string", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][1].__setitem__("s1_m", "60"), "oneOf")
case("road kind rail without rail", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("kind", "rail"), "missing required property 'rail'")
case("overlap_m below floor", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("overlap_m", 0.02), "< minimum")
case("skirt_drop_m above cap", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("skirt_drop_m", 0.05), "> maximum")
case("lanes non-integer", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("lanes", 2.5), "expected type integer")
case("lanes 2.0 is integer", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("lanes", 2.0), None)
case("width_m boolean", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("width_m", True), "expected type number")
case("camber kind enum", lambda d: d["profiles"]["road"]["road_trinity"]["camber"].__setitem__("kind", "crown"), "not in enum")
case("material name uppercase", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("surface_material", "Tarmac"), "does not match pattern")
case("split enabled without inner", lambda d: d["profiles"]["edge"]["edge_uk_half_grass"]["split_material"].pop("inner"), "missing required property 'inner'")
case("boundary_frac > 1", lambda d: d["profiles"]["edge"]["edge_uk_half_grass"]["split_material"].__setitem__("boundary_frac", 1.5), "> maximum")
case("lip arc_points 0", lambda d: d["profiles"]["edge"]["edge_uk_kerb"]["lip"].__setitem__("arc_points", 0), "< minimum")
case("edge materials missing pavement", lambda d: d["profiles"]["edge"]["edge_uk_kerb"]["materials"].pop("pavement"), "missing required property 'pavement'")
case("hedge top_profile enum", lambda d: d["profiles"]["hedge"]["hedge_privet"].__setitem__("top_profile", "spiky"), "not in enum")
case("foliage mode missing", lambda d: d["profiles"]["hedge"]["hedge_privet"]["foliage"].pop("mode"), "missing required property 'mode'")
case("profile_ids missing hedge_left", lambda d: d["splines"][0]["profile_ids"].pop("hedge_left"), "missing required property 'hedge_left'")
case("profile_ids road bad id chars", lambda d: d["splines"][0]["profile_ids"].__setitem__("road", "road trinity"), "oneOf")
case("point z string", lambda d: d["splines"][0]["points"][0].__setitem__("z", "abc"), "oneOf")
case("point z null ok", lambda d: d["splines"][0]["points"][0].__setitem__("z", None), None)
case("point roll_deg 45", lambda d: d["splines"][0]["points"][0].__setitem__("roll_deg", 45), "oneOf")
case("point roll_deg -10 ok", lambda d: d["splines"][0]["points"][0].__setitem__("roll_deg", -10), None)
case("point width negative", lambda d: d["splines"][0]["points"][0].__setitem__("width_m", -1), "< minimum")
case("points fewer than 2", lambda d: d["splines"][0].__setitem__("points", d["splines"][0]["points"][:1]), "< minItems 2")
case("segment side enum", lambda d: d["splines"][0]["segments"][0].__setitem__("side", "middle"), "not in enum")
case("segment missing side", lambda d: d["splines"][0]["segments"][0].pop("side"), "missing required property 'side'")
case("segment unknown key", lambda d: d["splines"][0]["segments"][0].__setitem__("pavement_width_m", 1.5), "additional property 'pavement_width_m'")
case("barrier brick_wall without height", lambda d: d["splines"][0]["segments"][2]["edge"]["barrier"].pop("height_m"), "missing required property 'height_m'")
case("barrier chain_link without post_pitch", lambda d: d["splines"][0]["segments"][3]["edge"]["barrier"].pop("post_pitch_m"), "missing required property 'post_pitch_m'")
case("barrier type none needs nothing", lambda d: d["splines"][0]["segments"][2]["edge"].__setitem__("barrier", {"type": "none"}), None)
case("barrier null ok", lambda d: d["splines"][0]["segments"][2]["edge"].__setitem__("barrier", None), None)
case("barrier inline with s0_m", lambda d: d["splines"][0]["segments"][2]["edge"]["barrier"].__setitem__("s0_m", 0), "additional property 's0_m'")
case("barrier type enum", lambda d: d["splines"][0]["segments"][2]["edge"]["barrier"].__setitem__("type", "hedge"), "not in enum")
case("rails_m negative", lambda d: d["splines"][0]["segments"][5]["edge"]["barrier"].__setitem__("rails_m", [1.0, -0.1]), "< minimum")
case("hedge segment missing present", lambda d: d["splines"][0]["segments"][4]["hedge"].pop("present"), "missing required property 'present'")
case("drop kerb missing side", lambda d: d["splines"][0]["drop_kerbs"][0].pop("side"), "missing required property 'side'")
case("drop kerb target 0.5", lambda d: d["splines"][0]["drop_kerbs"][0].__setitem__("target_height_m", 0.5), "> maximum")
case("drop kerb ramp 0", lambda d: d["splines"][0]["drop_kerbs"][0].__setitem__("ramp_m", 0), "exclusiveMinimum")
case("overlay pts 1 item", lambda d: d["splines"][0]["overlay"].__setitem__("pts", [[0, 0]]), "< minItems 2")
case("overlay pt 4 coords", lambda d: d["splines"][0]["overlay"]["pts"].__setitem__(0, [1, 2, 3, 4]), "> maxItems 3")
case("overlay kind enum", lambda d: d["splines"][0]["overlay"].__setitem__("kind", "raw"), "not in enum")
case("source layer enum", lambda d: d["splines"][0]["source"].__setitem__("layer", "footways"), "not in enum")
case("source tags non-string", lambda d: d["splines"][0]["source"]["tags"].__setitem__("lanes", 2), "expected type string")
case("source tile 3 items", lambda d: d["splines"][0]["source"].__setitem__("tile", [1, 2, 3]), "> maxItems 2")
case("continuation_kind bad", lambda d: d["splines"][0]["continuation_kind"].__setitem__("from", "seem"), "oneOf")
case("overrun_points XYZ 2 items", lambda d: d["splines"][0].__setitem__("overrun_points", {"before": [1, 2], "after": None}), "< minItems 3")
case("overrun_points ok", lambda d: d["splines"][0].__setitem__("overrun_points", {"before": [1, 2, 3], "after": None}), None)
case("flags unknown", lambda d: d["splines"][0]["flags"].__setitem__("oneway", True), "additional property 'oneway'")
case("flags tracks 0", lambda d: d["splines"][0]["flags"].__setitem__("tracks", 0), "oneOf")
case("junction end enum", lambda d: d["junctions"][0]["ends"][0].__setitem__("end", "middle"), "not in enum")
case("junction missing ends", lambda d: d["junctions"][0].pop("ends"), "missing required property 'ends'")
case("sampling passes 5", lambda d: d["splines"][0]["sampling"].__setitem__("smoothing_passes", 5), "> maximum")
case("sampling bank_max 40", lambda d: d["splines"][0]["sampling"].__setitem__("bank_max_deg", 40), "> maximum")
case("sampling unknown", lambda d: d["splines"][0]["sampling"].__setitem__("step", 2), "additional property 'step'")
case("materials hint base_color 1.5", lambda d: d["materials"]["tarmac"].__setitem__("base_color", [1.5, 0, 0]), "> maximum")
case("materials hint unknown key", lambda d: d["materials"]["tarmac"].__setitem__("metallic", 0.1), "additional property 'metallic'")
case("materials name uppercase key allowed? (schema keys unconstrained)", lambda d: d["materials"].__setitem__("Tarmac", {}), None)
# profile files
case("pf kind enum", lambda d: d.__setitem__("kind", "rail"), "not in enum", "pf")
case("pf id bad", lambda d: d.__setitem__("id", "rail standard"), "does not match pattern", "pf")
case("pf rail without rail block via wrapper", lambda d: d["profile"].pop("rail"), "missing required property 'rail'", "pf")
case("pf gauge missing", lambda d: d["profile"]["rail"].pop("gauge_m"), "missing required property 'gauge_m'", "pf")
case("pf sleeper mode enum", lambda d: d["profile"]["rail"]["sleeper"].__setitem__("mode", "hism"), "not in enum", "pf")
case("pf ballast top_width_m (removed field)", lambda d: d["profile"]["rail"]["ballast"].__setitem__("top_width_m", 3.4), "additional property 'top_width_m'", "pf")
case("pf profile unknown key", lambda d: d["profile"].__setitem__("gauge", 1.435), "additional property 'gauge'", "pf")
case("pf sampling_defaults min_step 0", lambda d: d["profile"]["sampling_defaults"].__setitem__("min_step_m", 0), "exclusiveMinimum", "pf")

fails = 0
for name, mutate, expect, target in cases:
    d = copy.deepcopy(doc if target == "doc" else pf)
    mutate(d)
    if target == "doc":
        errs = V.validate(d, schema, "$")
    else:
        errs = V.validate(d, schema["$defs"]["ProfileFile"], "$")
    msgs = ["%s: %s" % e for e in errs]
    if expect is None:
        ok = len(errs) == 0
    else:
        ok = any(expect in m for m in msgs)
    if not ok:
        fails += 1
    print("%s %-55s -> %s" % ("ok " if ok else "BAD", name, ("valid" if not errs else "; ".join(msgs[:2]))[:150]))

# semantic negative tests
def sem(name, mutate, expect):
    global fails
    d = copy.deepcopy(doc)
    mutate(d)
    rep = Report()
    semantic_document_checks(d, "t", rep, {"road": {"road_residential"}, "edge": {"edge_uk_kerb"}, "hedge": set()})
    allm = rep.errors + rep.warnings
    ok = any(expect in m for m in allm)
    if not ok:
        fails += 1
    print("%s %-55s -> %s" % ("ok " if ok else "BAD", name, "; ".join(allm[:2])[:150]))

sem("profile id not inline (in library)", lambda d: d["splines"][0]["profile_ids"].__setitem__("road", "road_residential"), "exists in schema/profiles but is not inlined")
sem("profile id nowhere", lambda d: d["splines"][0]["segments"][1]["edge"].__setitem__("profile_id", "edge_x"), "not in schema/profiles either")
sem("segment s0 >= s1", lambda d: d["splines"][0]["segments"][2].__setitem__("s1_m", 0.0), "s0_m 0.0 >= s1_m 0.0")
sem("tuck rule", lambda d: d["profiles"]["edge"]["edge_uk_kerb"].__setitem__("tuck_depth_m", 0.01), "tuck_depth_m 0.01 must exceed")
sem("lane widths sum", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("lane_widths_m", [4, 4]), "sum(lane_widths_m)")
sem("unhinted material", lambda d: d["profiles"]["road"]["road_trinity"].__setitem__("surface_material", "cobbles"), "outside the SCHEMA.md 7 normative set")
sem("junction end too far", lambda d: d["junctions"][0].__setitem__("x", 8110.0), "from the junction")
sem("junction_start unknown", lambda d: d["splines"][0].__setitem__("junction_start", "j_nowhere"), "is not in junctions[]")
sem("duplicate spline id", lambda d: d["splines"].append(copy.deepcopy(d["splines"][0])), "duplicate spline id")
sem("road kind mismatch on switch", lambda d: (d["profiles"]["road"].__setitem__("r2", dict(d["profiles"]["road"]["road_trinity"], kind="rail", rail=pf["profile"]["rail"])),
                                                 d["splines"][0]["segments"][0].__setitem__("road", {"profile_id": "r2"})), "differs from the spline's base road kind")
sem("overlay missing on non-authored", lambda d: (d["splines"][0]["source"].__setitem__("layer", "roads"), d["splines"][0].pop("overlay")), "overlay missing")
sem("edge-anchored negative offset", lambda d: d["profiles"]["road"]["road_trinity"]["markings"][1].__setitem__("offset_m", -0.25), "needs offset_m >= 0")

print("NEGATIVE TESTS: %d case(s), %d failure(s)" % (len(cases) + 12, fails))
sys.exit(1 if fails else 0)
