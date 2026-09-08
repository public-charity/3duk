"""06_import_massing - grey building placeholders from the adapter's massing product (UE_PLAN.md 5.3 row 6).

    run_ue_python.ps1 -Script 06_import_massing.py -Args "[--dir <DATA>/massing] [--map /Game/Thanet/Maps/Thanet]
        [--material /Game/Thanet/Materials/MI_massing_grey] [--no-save]"

One AStreetscapeMassingActor per buildings_x{i}_y{j}.jsonl (DESIGN.md 15), each holding that tile's footprints
extruded from `skirt` to `base_z + h` in one UDynamicMeshComponent. The actor count must equal
massing_manifest.json's `files` (the tiles that have buildings).

The grey material instance is created here rather than in 01_bootstrap.py on purpose: 01's contract is the
SCHEMA.md 7 street material set (M_Street_Base + 20 instances = the 21 of UE_PLAN.md 8.3) and adding a 22nd would
change a number another check asserts. MI_massing_grey is a plain instance of M_Street_Base.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unreal  # noqa: E402

import ue_common as uc  # noqa: E402

NAME = "06_import_massing"
DEFAULT_MAP = "/Game/Thanet/Maps/Thanet"
MATERIALS_PATH = "/Game/Thanet/Materials"
MASSING_MI = "MI_massing_grey"
GREY = (0.34, 0.33, 0.31)


def ensure_grey_material():
    """MI_massing_grey: a MaterialInstanceConstant of M_Street_Base with a concrete-grey BaseColor."""
    lib = unreal.EditorAssetLibrary
    base_path = "%s/M_Street_Base.M_Street_Base" % MATERIALS_PATH
    base = lib.load_asset(base_path)
    if base is None:
        uc.fail(NAME, "M_Street_Base is missing - run 01_bootstrap.py first")
    full = "%s/%s.%s" % (MATERIALS_PATH, MASSING_MI, MASSING_MI)
    created = False
    mi = lib.load_asset(full) if lib.does_asset_exist(full) else None
    if mi is None:
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            MASSING_MI, MATERIALS_PATH, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        created = True
    mel = unreal.MaterialEditingLibrary
    mel.set_material_instance_parent(mi, base)
    mel.set_material_instance_vector_parameter_value(mi, "BaseColor", unreal.LinearColor(GREY[0], GREY[1], GREY[2], 1.0))
    mel.set_material_instance_scalar_parameter_value(mi, "Roughness", 0.85)
    mel.update_material_instance(mi)
    lib.save_asset(full, only_if_is_dirty=False)
    return full, created


def main(argv):
    opts = uc.parse_args(argv, flags=("no_save",), options={
        "dir": "", "map": DEFAULT_MAP, "material": "",
    })
    massing_dir = (opts["dir"] or (uc.data_dir() + "/massing")).replace("\\", "/")
    if not os.path.isdir(massing_dir):
        uc.fail(NAME, "no such directory: %s" % massing_dir)

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(opts["map"]):
        uc.fail(NAME, "load_level(%s) failed" % opts["map"])
    # World Partition: nothing is loaded in a commandlet until a region is (Tools/ue/README.md), and the massing
    # actors of a previous run must be visible for ImportMassing to replace them.
    unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0, 0, 0), 2000000.0)

    material, created = (opts["material"], False) if opts["material"] else ensure_grey_material()
    uc.log("massing material %s (created=%s)" % (material, created))

    n, report_json = unreal.StreetscapeEditorLibrary.import_massing(massing_dir, material)
    report = json.loads(report_json)
    if n < 0:
        uc.fail(NAME, "import_massing failed: %s" % report.get("error"))

    expected = None
    man_path = os.path.join(massing_dir, "massing_manifest.json")
    if os.path.isfile(man_path):
        with open(man_path) as fh:
            man = json.load(fh)
        expected = man.get("files")
        report["manifest_files"] = expected
        report["manifest_buildings"] = man.get("buildings")
        report["matches_manifest"] = (n == expected)
        report["buildings_match_manifest"] = (report.get("buildings") == man.get("buildings"))

    if not opts["no_save"]:
        uc.save_all()

    uc.report(NAME, {
        "actors": n,
        "dir": massing_dir,
        "material": material,
        "material_created": created,
        "expected_actors": expected,
        "matches_manifest": report.get("matches_manifest"),
        "buildings": report.get("buildings"),
        "manifest_buildings": report.get("manifest_buildings"),
        "buildings_match_manifest": report.get("buildings_match_manifest"),
        "verts": report.get("verts"),
        "tris": report.get("tris"),
        "hole_rings": report.get("hole_rings"),
        "clamped_heights": report.get("clamped_heights"),
        "z_min_m": report.get("z_min_m"),
        "z_max_m": report.get("z_max_m"),
        "seconds": report.get("seconds"),
    })


if __name__ == "__main__":
    main(sys.argv)
