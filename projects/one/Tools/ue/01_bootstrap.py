"""01_bootstrap - create the Thanet project content that every later step assumes (UE_PLAN.md 5.3 row 1).

Phase 1: the content folders, the empty World Partition map /Game/Thanet/Maps/Thanet (UE_PLAN.md 1.4: "created empty
by the bootstrap"), sun / sky light / sky atmosphere / height fog / volumetric cloud, save.
Phase 2 (this file): M_Thanet_Landscape (Masked; LandscapeLayerBlend grass/sand/rock/water -> BaseColor,
LandscapeVisibilityMask -> OpacityMask), M_Street_Base (BaseColor / Roughness parameters, magenta by default) + one
MaterialInstanceConstant per SCHEMA.md 7 name (20), DT_StreetMaterials (UStreetMaterialTable keyed by those names,
fallback = the magenta base), and the 20 profile DataAssets from schema/profiles through
unreal.StreetscapeEditorLibrary.import_profiles.
Phase 3: the AStreetscapeSiteActor (site header, terrain source, profile library, material table).

Usage (through Tools/ue/run_ue_python.ps1):
    run_ue_python.ps1 -Script 01_bootstrap.py [-Args "--recreate | --template <asset path or none> | --skip-materials | --skip-profiles"]

Default: if the map exists it is loaded and checked (idempotent); --recreate deletes it (map + external actor
packages) and builds it again. --template none (default) makes an empty partitioned map with new_level(path, True);
--template /Engine/Maps/Templates/OpenWorld starts from the engine template instead - measured 2026-09-08: that
template brings a Landscape + 64 LandscapeStreamingProxy actors, 64 WorldPartitionHLOD packages that are never
loaded in the editor, a 741 KB WorldPartitionMiniMap, a StaticMeshActor and a PlayerStart; the landscape, minimap
and HLOD packages are removed here (the terrain comes from 02_import_landscape), the rest is left and listed.
Materials and profiles are re-applied on every run (existing assets are updated in place, never duplicated).
"""
import glob
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unreal  # noqa: E402

import ue_common as uc  # noqa: E402

NAME = "01_bootstrap"
MAP_PATH = "/Game/Thanet/Maps/Thanet"
MATERIALS_PATH = "/Game/Thanet/Materials"
PROFILES_PATH = "/Game/Thanet/Profiles"
DEFAULT_TEMPLATE = "none"  # or "/Engine/Maps/Templates/OpenWorld"; see the module docstring
# BRIEF 4.1: the thanet grid origin, which every Streetscape document of this site must carry.
SITE_ORIGIN_E = 627680.0
SITE_ORIGIN_N = 163080.0
FOLDERS = ["/Game/Thanet/Maps", MATERIALS_PATH, PROFILES_PATH, "/Game/Thanet/Landscape/Layers"]
# Classes whose actors the template may carry but this project must not: the landscape is imported later, and the
# template's minimap is a 741 KB texture of that landscape (rebuilt by WorldPartitionMiniMapBuilder when wanted).
TEMPLATE_ACTOR_CLASSES_TO_REMOVE = ("Landscape", "LandscapeStreamingProxy", "LandscapeGizmoActiveActor", "WorldPartitionMiniMap")
# External-actor packages that are never loaded in the editor (so destroy_actor cannot reach them) and only exist
# for the removed landscape: the OpenWorld template leaves 64 of them (~60 KB each). Pruned through the asset registry.
STALE_PACKAGE_CLASSES = ("WorldPartitionHLOD",)
EXTERNAL_ACTORS_PKG = "/Game/__ExternalActors__/Thanet/Maps/Thanet"
# (python class name, label, spawn location, spawn rotation)
ATMOSPHERE = [
    # unreal.Rotator takes (ROLL, PITCH, YAW). Written as (-42, 0, 28) this was roll -42 / pitch 0 / yaw 28:
    # a sun pointing along the horizon, which is why a lit capture of the test stretch came back at mean
    # luminance 2 out of 255 while its base colour came back at 71. The intent is a sun 42 degrees up.
    ("DirectionalLight", "Sun", unreal.Vector(0, 0, 500), unreal.Rotator(0.0, -42.0, 28.0)),
    ("SkyLight", "SkyLight", unreal.Vector(0, 0, 500), unreal.Rotator(0, 0, 0)),
    ("SkyAtmosphere", "SkyAtmosphere", unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)),
    ("ExponentialHeightFog", "HeightFog", unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)),
    ("VolumetricCloud", "VolumetricCloud", unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)),
]

# SCHEMA.md 7 material set in its normative order, with preview colours: the 12 hints of schema/examples/*.json
# (base_color / roughness / two_sided) plus plausible values for the 8 names the examples do not hint.
# (r, g, b, roughness, two_sided)
STREET_MATERIALS = [
    ("tarmac", (0.16, 0.16, 0.17), 0.9, False),
    ("white_paint", (0.92, 0.92, 0.9), 0.6, False),
    ("yellow_paint", (0.95, 0.8, 0.1), 0.6, False),
    ("concrete_kerb", (0.62, 0.61, 0.58), 0.8, False),
    ("paving_slab", (0.55, 0.54, 0.52), 0.85, False),
    ("grass", (0.25, 0.42, 0.14), 1.0, False),
    ("gravel", (0.52, 0.48, 0.42), 0.95, False),
    ("brick_red", (0.55, 0.27, 0.2), 0.85, False),
    ("coping_concrete", (0.66, 0.65, 0.62), 0.8, False),
    ("chain_link", (0.55, 0.57, 0.58), 0.5, True),
    ("post_steel", (0.35, 0.37, 0.38), 0.5, False),
    ("steel_painted_black", (0.05, 0.05, 0.06), 0.45, False),
    ("wood_fence", (0.45, 0.32, 0.18), 0.85, True),
    ("privet_leaf", (0.16, 0.33, 0.1), 0.9, False),
    ("ballast", (0.42, 0.40, 0.38), 0.95, False),
    ("sleeper_concrete", (0.58, 0.57, 0.55), 0.85, False),
    ("rail_steel", (0.50, 0.50, 0.52), 0.35, False),
    ("stone_flint", (0.48, 0.47, 0.44), 0.9, False),
    ("concrete_wall", (0.60, 0.60, 0.58), 0.85, False),
    ("massing_grey", (0.55, 0.55, 0.55), 0.9, False),
]
# landscape layers (step 09 ground cover fractions -> weightmaps; UE_PLAN.md 3.5) with preview colours
LANDSCAPE_LAYERS = [("grass", (0.25, 0.42, 0.14)), ("sand", (0.76, 0.70, 0.50)), ("rock", (0.45, 0.44, 0.42)), ("water", (0.10, 0.25, 0.35))]
FALLBACK_MAGENTA = (1.0, 0.0, 1.0)


def map_paths():
    """On-disk files that belong to the map: the .umap and the World Partition external packages."""
    c = uc.content_dir()
    return {
        "umap": c + "/Thanet/Maps/Thanet.umap",
        "external_actors": c + "/__ExternalActors__/Thanet/Maps/Thanet",
        "external_objects": c + "/__ExternalObjects__/Thanet/Maps/Thanet",
    }


def delete_existing_map():
    """Remove the map and its external packages from disk and from the asset registry (a stale registry entry for
    a deleted external actor would otherwise be picked up by the new partitioned world)."""
    paths = map_paths()
    files = []
    for key in ("external_actors", "external_objects"):
        d = paths[key]
        if os.path.isdir(d):
            for root, _dirs, names in os.walk(d):
                files.extend(os.path.join(root, n).replace("\\", "/") for n in names)
            shutil.rmtree(d)
    if os.path.isfile(paths["umap"]):
        files.append(paths["umap"])
        os.remove(paths["umap"])
    if files:
        unreal.AssetRegistryHelpers.get_asset_registry().scan_modified_asset_files(files)
    uc.log("deleted %d package files of the previous map" % len(files))
    return len(files)


def actor_classes(eas):
    counts = {}
    for a in eas.get_all_level_actors():
        cls = a.get_class().get_name()
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def actor_list(eas):
    """'Label (Class) @ x,y,z' for every loaded actor - small maps only; lets the log say what a template brought."""
    out = []
    for a in eas.get_all_level_actors():
        loc = a.get_actor_location()
        extra = ""
        if a.get_class().get_name() == "StaticMeshActor":
            mesh = a.get_editor_property("static_mesh_component").get_editor_property("static_mesh")
            extra = " mesh=%s" % (mesh.get_path_name() if mesh else None)
        out.append("%s (%s) @ %d,%d,%d%s" % (a.get_actor_label(), a.get_class().get_name(), loc.x, loc.y, loc.z, extra))
    return sorted(out)


def prune_stale_packages():
    """Delete external-actor packages of STALE_PACKAGE_CLASSES from disk and the registry; returns the count."""
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    files = []
    for asset in ar.get_assets_by_path(EXTERNAL_ACTORS_PKG, True, True):
        cls = str(asset.asset_class_path.asset_name)
        if cls in STALE_PACKAGE_CLASSES:
            pkg = str(asset.package_name)
            path = uc.content_dir() + pkg[len("/Game"):] + ".uasset"
            if os.path.isfile(path):
                os.remove(path)
                files.append(path)
    if files:
        ar.scan_modified_asset_files(files)
        uc.log("pruned %d stale %s package(s)" % (len(files), "/".join(STALE_PACKAGE_CLASSES)))
    return len(files)


def remove_template_landscape(eas, from_template):
    """Remove the OpenWorld template's own landscape - ONLY on the run that created the map from that template.

    This used to run on EVERY bootstrap, including the idempotent "map already exists, nothing to do" path, and
    the class list contains "Landscape". So a second `01_bootstrap.py` on a level that already held the imported
    Thanet landscape destroyed it: measured 2026-09-08,
        [thanet] removing template actor Landscape_thanet (Landscape)
    and the saved map came back with 140 LandscapeStreamingProxy actors and no ALandscape, which is what made
    every landscape probe fail on a level that looked complete. (The proxies survived only because a World
    Partition commandlet has not streamed them in, so get_all_level_actors never sees them - which would have made
    the damage worse, not better, on a run that had.) Nothing else in the bootstrap is destructive; --recreate is
    the switch that means "throw the map away".
    """
    if not from_template:
        skipped = [a.get_actor_label() for a in eas.get_all_level_actors()
                   if a.get_class().get_name() in TEMPLATE_ACTOR_CLASSES_TO_REMOVE]
        if skipped:
            uc.log("keeping %d existing %s actor(s) - this map was not created from a template on this run: %s"
                   % (len(skipped), "/".join(TEMPLATE_ACTOR_CLASSES_TO_REMOVE), skipped))
        return 0
    removed = 0
    for a in list(eas.get_all_level_actors()):
        if a.get_class().get_name() in TEMPLATE_ACTOR_CLASSES_TO_REMOVE:
            uc.log("removing template actor %s (%s)" % (a.get_actor_label(), a.get_class().get_name()))
            eas.destroy_actor(a)
            removed += 1
    return removed


def ensure_atmosphere(eas):
    present = actor_classes(eas)
    spawned = []
    fixed = []
    for cls_name, label, loc, rot in ATMOSPHERE:
        if present.get(cls_name, 0) > 0:
            # idempotent means "make it what it should be", not "leave whatever is there": a level built before
            # the sun's rotation was corrected keeps a sun on the horizon for ever otherwise
            for a in eas.get_all_level_actors():
                if a.get_class().get_name() != cls_name:
                    continue
                have = a.get_actor_rotation()
                if abs(have.pitch - rot.pitch) > 1e-3 or abs(have.yaw - rot.yaw) > 1e-3 or abs(have.roll - rot.roll) > 1e-3:
                    a.set_actor_rotation(rot, False)
                    a.modify()
                    fixed.append("%s %s -> pitch %g yaw %g roll %g" % (cls_name, label, rot.pitch, rot.yaw, rot.roll))
            continue
        cls = getattr(unreal, cls_name)
        actor = eas.spawn_actor_from_class(cls, loc, rot)
        if actor is None:
            uc.fail(NAME, "could not spawn %s" % cls_name)
        actor.set_actor_label(label)
        if cls_name == "SkyLight":
            actor.get_editor_property("light_component").set_editor_property("real_time_capture", True)
        if cls_name == "DirectionalLight":
            actor.get_editor_property("light_component").set_editor_property("atmosphere_sun_light", True)
        spawned.append(cls_name)
    if fixed:
        uc.log("corrected atmosphere transforms: %s" % fixed)
    return spawned


# -- materials (UE_PLAN.md 5.3 row 1, 2.5.3) ---------------------------------------------------------------------

def _asset_path(path, name):
    return "%s/%s.%s" % (path, name, name)


def ensure_asset(name, path, cls, factory):
    """Load the asset if it exists, else create it. Returns (asset, created)."""
    lib = unreal.EditorAssetLibrary
    full = _asset_path(path, name)
    if lib.does_asset_exist(full):
        asset = lib.load_asset(full)
        if asset is not None and asset.get_class().get_name() == cls.static_class().get_name():
            return asset, False
        uc.log("WARNING: %s exists with class %s - replacing" % (full, asset.get_class().get_name() if asset else None))
        lib.delete_asset(full)
    asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, path, cls, factory)
    if asset is None:
        uc.fail(NAME, "create_asset(%s) failed" % full)
    return asset, True


def make_street_base():
    """M_Street_Base: BaseColor (vector) and Roughness (scalar) parameters, magenta by default - the fallback
    UStreetMaterialTable.Resolve returns for names outside SCHEMA.md 7."""
    mel = unreal.MaterialEditingLibrary
    mat, created = ensure_asset("M_Street_Base", MATERIALS_PATH, unreal.Material, unreal.MaterialFactoryNew())
    if created:
        color = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -450, 0)
        color.set_editor_property("parameter_name", "BaseColor")
        color.set_editor_property("default_value", unreal.LinearColor(FALLBACK_MAGENTA[0], FALLBACK_MAGENTA[1], FALLBACK_MAGENTA[2], 1.0))
        mel.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
        rough = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -450, 250)
        rough.set_editor_property("parameter_name", "Roughness")
        rough.set_editor_property("default_value", 0.8)
        mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
        mel.recompile_material(mat)
    return mat, created


def make_street_instances(base):
    """One MaterialInstanceConstant per SCHEMA.md 7 name: MI_<name>. Returns {name: instance}, created count."""
    mel = unreal.MaterialEditingLibrary
    out = {}
    created = 0
    for name, rgb, rough, two_sided in STREET_MATERIALS:
        mi, was_created = ensure_asset("MI_" + name, MATERIALS_PATH, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        created += int(was_created)
        mel.set_material_instance_parent(mi, base)
        mel.set_material_instance_vector_parameter_value(mi, "BaseColor", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
        mel.set_material_instance_scalar_parameter_value(mi, "Roughness", float(rough))
        if two_sided:
            ovr = unreal.MaterialInstanceBasePropertyOverrides()
            ovr.set_editor_property("override_two_sided", True)
            ovr.set_editor_property("two_sided", True)
            mi.set_editor_property("base_property_overrides", ovr)
        mel.update_material_instance(mi)
        out[name] = mi
    return out, created


def make_landscape_material():
    """M_Thanet_Landscape (UE_PLAN.md 5.3): Masked; LandscapeLayerBlend grass/sand/rock/water -> BaseColor;
    LandscapeVisibilityMask -> OpacityMask (the clip line is a landscape hole, BRIEF 4.1)."""
    mel = unreal.MaterialEditingLibrary
    mat, created = ensure_asset("M_Thanet_Landscape", MATERIALS_PATH, unreal.Material, unreal.MaterialFactoryNew())
    if created:
        mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
        blend = mel.create_material_expression(mat, unreal.MaterialExpressionLandscapeLayerBlend, -500, 0)
        layers = []
        for i, (layer, rgb) in enumerate(LANDSCAPE_LAYERS):
            li = unreal.LayerBlendInput()
            li.set_editor_property("layer_name", layer)
            li.set_editor_property("blend_type", unreal.LandscapeLayerBlendType.LB_WEIGHT_BLEND)
            li.set_editor_property("const_layer_input", unreal.Vector(rgb[0], rgb[1], rgb[2]))
            li.set_editor_property("preview_weight", 1.0 if i == 0 else 0.0)
            layers.append(li)
        blend.set_editor_property("layers", layers)
        mel.connect_material_property(blend, "", unreal.MaterialProperty.MP_BASE_COLOR)
        vis = mel.create_material_expression(mat, unreal.MaterialExpressionLandscapeVisibilityMask, -500, 350)
        mel.connect_material_property(vis, "", unreal.MaterialProperty.MP_OPACITY_MASK)
        mel.recompile_material(mat)
    # Material.expressions is protected from Python; the layers are the ones this script set (recorded on creation)
    layer_names = [layer for layer, _rgb in LANDSCAPE_LAYERS]
    return mat, created, layer_names


def make_material_table(instances, fallback):
    table = unreal.StreetscapeEditorLibrary.create_material_table(MATERIALS_PATH, "DT_StreetMaterials", instances, fallback)
    if table is None:
        uc.fail(NAME, "create_material_table failed")
    missing = [str(n) for n in table.missing_normative_names()]
    if missing:
        uc.fail(NAME, "DT_StreetMaterials misses normative names: %s" % missing)
    return table


def count_assets(path, class_names):
    """Assets under a content path (non-recursive) whose class is one of class_names, by asset name."""
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    names = []
    for a in ar.get_assets_by_path(path, False, False):
        if str(a.asset_class_path.asset_name) in class_names:
            names.append(str(a.asset_name))
    return sorted(names)


def uasset_files(subdir):
    return sorted(os.path.basename(p) for p in glob.glob(uc.content_dir() + "/" + subdir + "/*.uasset"))


def main(argv):
    opts = uc.parse_args(argv, flags=("recreate", "skip_materials", "skip_profiles", "skip_site_actor"),
                         options={"template": DEFAULT_TEMPLATE, "origin_e": "", "origin_n": ""})
    template = opts["template"]
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    lib = unreal.EditorAssetLibrary

    made = []
    for f in FOLDERS:
        if not lib.does_directory_exist(f):
            if not lib.make_directory(f):
                uc.fail(NAME, "make_directory(%s) failed" % f)
            made.append(f)
    uc.log("folders present: %s (made now: %s)" % (FOLDERS, made))

    # -- materials + material table (before the map so the site actor of phase 3 can reference them)
    materials = {"count": 0, "created": 0, "instances": [], "table": None, "landscape_material": None, "landscape_layers": []}
    if not opts["skip_materials"]:
        base, base_created = make_street_base()
        instances, inst_created = make_street_instances(base)
        lm, lm_created, layer_names = make_landscape_material()
        table = make_material_table(instances, base)
        if not lib.save_directory(MATERIALS_PATH, False, True):
            uc.fail(NAME, "save_directory(%s) failed" % MATERIALS_PATH)
        names = count_assets(MATERIALS_PATH, ("Material", "MaterialInstanceConstant"))
        street = [n for n in names if n == "M_Street_Base" or n.startswith("MI_")]
        materials = {
            "count": len(street),
            "created": int(base_created) + inst_created + int(lm_created),
            "base": base.get_path_name(),
            "instances": sorted(instances.keys()),
            "table": table.get_path_name(),
            "table_entries": len(table.get_editor_property("materials")),
            "landscape_material": lm.get_path_name(),
            "landscape_layers": layer_names,
        }
        uc.log("materials: %d street (M_Street_Base + %d instances), landscape material %s with layers %s, table %d entries after %.1fs" % (
            materials["count"], len(instances), lm.get_name(), layer_names, materials["table_entries"], uc.elapsed_s()))

    # -- profile DataAssets (UE_PLAN.md 2.12 ImportProfiles)
    profiles = {"count": 0, "ids": [], "files": []}
    if not opts["skip_profiles"]:
        json_dir = uc.project_dir() + "/schema/profiles"
        n = unreal.StreetscapeEditorLibrary.import_profiles(json_dir, PROFILES_PATH)
        ids = [str(i) for i in unreal.StreetscapeEditorLibrary.profile_asset_ids(PROFILES_PATH)]
        files = uasset_files("Thanet/Profiles")
        profiles = {"count": int(n), "ids": ids, "files": files, "source": json_dir}
        uc.log("profiles: import_profiles -> %d, registry %d, .uasset files %d after %.1fs" % (n, len(ids), len(files), uc.elapsed_s()))
        if n != 20 or len(files) != 20:
            uc.fail(NAME, "expected 20 profile assets, got import %d / files %d" % (n, len(files)))

    # -- the map
    paths = map_paths()
    existed = os.path.isfile(paths["umap"])
    mode = "loaded"
    if existed and opts["recreate"]:
        delete_existing_map()
        existed = False
    if existed:
        if not les.load_level(MAP_PATH):
            uc.fail(NAME, "load_level(%s) failed" % MAP_PATH)
    else:
        mode = "created"
        if template.lower() == "none":
            template = "none"
            ok = les.new_level(MAP_PATH, True)
        else:
            ok = les.new_level_from_template(MAP_PATH, template)
        if not ok:
            uc.fail(NAME, "new level %s from %s failed" % (MAP_PATH, template))
    uc.log("map %s %s (template %s) after %.1fs" % (MAP_PATH, mode, template, uc.elapsed_s()))

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    before = actor_classes(eas)
    uc.log("actors before: %s" % before)
    removed = remove_template_landscape(eas, mode == "created" and template != "none")
    spawned = ensure_atmosphere(eas)

    # -- the StreetscapeSiteActor (UE_PLAN.md 2.10): site header, terrain source, profile library, material table
    site_actor = None
    if not opts["skip_site_actor"]:
        oe = float(opts["origin_e"]) if opts["origin_e"] else SITE_ORIGIN_E
        on = float(opts["origin_n"]) if opts["origin_n"] else SITE_ORIGIN_N
        sa = unreal.StreetscapeEditorLibrary.ensure_site_actor(uc.site_name(), oe, on)
        if sa is None:
            uc.fail(NAME, "ensure_site_actor failed")
        terrain = sa.get_editor_property("terrain_source")
        table = sa.get_editor_property("materials")
        site_actor = {
            "label": str(sa.get_actor_label()),
            "site": str(sa.get_editor_property("site_name")),
            "origin": [oe, on],
            "profiles": len(sa.get_editor_property("profiles")),
            "material_table": table.get_path_name() if table else None,
            "terrain": terrain.describe_source() if terrain else None,
            "terrain_tiles": terrain.num_tiles() if terrain else 0,
        }
        uc.log("site actor: %s" % json.dumps(site_actor, sort_keys=True))

    after = actor_classes(eas)
    listing = actor_list(eas)
    uc.log("actors after: %s" % after)
    for line in listing:
        uc.log("  actor: %s" % line)

    if not les.save_current_level():
        uc.fail(NAME, "save_current_level failed")
    uc.save_all()
    pruned = prune_stale_packages()

    ext = paths["external_actors"]
    ext_count = sum(len(n) for _r, _d, n in os.walk(ext)) if os.path.isdir(ext) else 0
    if not os.path.isfile(paths["umap"]):
        uc.fail(NAME, "%s not on disk after save" % paths["umap"])
    if ext_count == 0:
        uc.fail(NAME, "no external actor packages under %s - the map is not World Partition" % ext)
    n_actors = sum(after.values())
    if ext_count != n_actors:
        uc.log("WARNING: %d external actor packages on disk for %d loaded actors" % (ext_count, n_actors))

    uc.report(NAME, {
        "map": MAP_PATH,
        "mode": mode,
        "template": template,
        "world": world.get_name(),
        "folders": FOLDERS,
        "folders_made": made,
        "actors": after,
        "actor_list": listing,
        "template_actors_removed": removed,
        "stale_packages_pruned": pruned,
        "atmosphere_spawned": spawned,
        "umap": paths["umap"],
        "external_actor_packages": ext_count,
        "world_partition": ext_count > 0,
        # UE_PLAN.md 5.3: materials 21 = M_Street_Base + 20 instances; the landscape material is reported separately
        "materials": materials["count"],
        "materials_detail": materials,
        "profiles": profiles["count"],
        "profiles_detail": profiles,
        "profile_uassets": len(profiles["files"]),
        # phase 3: the StreetscapeSiteActor (UE_PLAN.md 2.10)
        "site_actor": site_actor,
    })


if __name__ == "__main__":
    main(sys.argv)
