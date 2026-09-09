"""02_import_landscape - the adapter's landscape products into one World Partition ALandscape (UE_PLAN.md 5.3 row 2).

    run_ue_python.ps1 -Script 02_import_landscape.py -Render -Args "--manifest <DATA>/landscape/landscape_manifest.json
        [--wp-grid 4] [--qps 127] [--sections 2] [--max-components 0] [--map /Game/Thanet/Maps/Thanet]
        [--recreate-map] [--probes-only] [--no-load-all] [--no-grid] [--no-cliff] [--no-clip] [--grid-per-tile 5]
        [--max-shared-edge-h16 0] [--report <path.json>]"

THE SCRIPT FAILS WHEN A GATE FAILS. grid.within_0_01_m, cliff.agree, cliff.slope_ok, clip.pass and the
importer's shared_edge.ok all have to hold, or the last line is THANET_FAIL and the exit code is non-zero.
--max-shared-edge-h16 is the tolerance for the row/column two neighbouring tiles both write (0 = they must be
identical, which is what sound data gives; a negative value waives the gate and says so in the report).

-Render is mandatory for a real import: the edit-layer merge needs FApp::CanEverRender()
(LandscapeEditLayers.cpp:7051, DESIGN.md 13).

What it does, in order:
  1. loads (or creates, with --recreate-map / --map) the World Partition map;
  2. prints the PLAN the importer computes from the manifest alone - component size, count, padding, extent, the
     engine helper's own suggestion - so the numbers are visible even if the import then fails;
  3. calls StreetscapeLandscapeImporter.import_site, which does the single Import or the 16x16-component region
     fallback of UE_PLAN.md 3.7 when --max-components is exceeded, and records rss_mb / seconds per step;
  4. runs the two verification probes of UE_PLAN.md 8.5 (the Cliftonville cliff) and 8.6 (the clip edge), both
     driven by numbers READ FROM THE MANIFEST (the clip line, the tile slope_max_deg) - never hard-coded;
  5. saves, and prints THANET_OK 02_import_landscape <report>.

--probes-only skips 3 and re-runs the probes against an already-imported landscape.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unreal  # noqa: E402

import ue_common as uc  # noqa: E402

NAME = "02_import_landscape"
DEFAULT_MAP = "/Game/Thanet/Maps/Thanet"
DEFAULT_MATERIAL = "/Game/Thanet/Materials/M_Thanet_Landscape.M_Thanet_Landscape"
DEFAULT_LAYER_PATH = "/Game/Thanet/Landscape/Layers"
# UE_PLAN.md 8.5: the Cliftonville cliff, local metres from the thanet origin.
CLIFF_XY = (8820.0, 8620.0)
CLIFF_SPAN = 50          # +/- metres along y
CLIFF_LINES = (-20, -10, 0, 10, 20)   # x offsets
CLIP_OFFSET_M = 2.0      # UE_PLAN.md 8.6: P+ / P- are 2 m either side of the line
CLIP_SAMPLES = 20


def _f(v):
    return None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), 4)


def delete_map(map_path, umap):
    """--recreate-map: remove the .umap and its external actor/object packages from disk AND from the asset
    registry (a stale registry entry for a deleted external actor is picked up by the new partitioned world).
    Same routine as 01_bootstrap.delete_existing_map."""
    import shutil
    rel = map_path[len("/Game"):]
    files = []
    for d in (uc.content_dir() + "/__ExternalActors__" + rel, uc.content_dir() + "/__ExternalObjects__" + rel):
        if os.path.isdir(d):
            for root, _dirs, names in os.walk(d):
                files.extend(os.path.join(root, n).replace("\\", "/") for n in names)
            shutil.rmtree(d)
    if os.path.isfile(umap):
        files.append(umap)
        os.remove(umap)
    if files:
        unreal.AssetRegistryHelpers.get_asset_registry().scan_modified_asset_files(files)
    uc.log("deleted %d package files of the previous %s" % (len(files), map_path))


def plan(opts):
    imp = unreal.StreetscapeLandscapeImporter
    return json.loads(imp.plan_site_json(opts["manifest"], int(opts["qps"]), int(opts["sections"]), int(opts["wp_grid"])))


def manifest_tiles(path):
    with open(path) as fh:
        return json.load(fh)


def probe_grid(land, man, hf, per_tile=5):
    """The 'heights match the heightfield' gate: a lattice of integer-metre vertices over every tile of the
    manifest, landscape (EHeightfieldSource::Editor) against the adapter's own r16 bytes.

    The lattice includes the tile's OWN BOUNDARY rows and columns (local offsets 0 and tile_m) as well as the
    interior. The original `step = tile_m // (per_tile + 1)` with a, b in 1..per_tile could only produce offsets
    85..425 of a 512 m tile, so the one place the assembly can go wrong - the row/column two tiles both write -
    was the one place the gate could never look. Points whose heightfield sample is NaN (clipped or off coverage)
    are counted, not compared; a point the landscape has no height for fails the gate."""
    imp = unreal.StreetscapeLandscapeImporter
    tile_m = man["tile_m"]
    n_nan = 0
    n_land_none = 0
    max_dz = 0.0
    worst = None
    step = tile_m // (per_tile + 1)
    offsets = [0] + [a * step for a in range(1, per_tile + 1)] + [tile_m]
    pts = set()
    for t in man["tiles"]:
        x0 = tile_m * t["x"]
        y0 = tile_m * t["y"]
        for a in offsets:
            for b in offsets:
                pts.add((float(x0 + a), float(y0 + b)))
    n_edge = sum(1 for x, y in pts if x % tile_m == 0 or y % tile_m == 0)
    none_pts = []
    x_max = man["nx"] * tile_m
    y_max = man["ny"] * tile_m
    for x, y in sorted(pts):
        zh = hf.probe_m(x, y)
        zl = imp.probe_height_m(land, x, y, False)
        if math.isnan(zh):
            n_nan += 1
            continue
        if zl is None or math.isnan(zl):
            n_land_none += 1
            if len(none_pts) < 20:
                none_pts.append([x, y, _f(zh), "site_edge" if (x in (0.0, x_max) or y in (0.0, y_max)) else "interior"])
            continue
        dz = abs(zh - zl)
        if dz > max_dz:
            max_dz = dz
            worst = [x, y, _f(zh), _f(zl)]
    n = len(pts)
    return {"points": n, "compared": n - n_nan - n_land_none, "heightfield_nan": n_nan,
            "landscape_none": n_land_none, "max_abs_dz_m": round(max_dz, 6),
            "tile_boundary_points": n_edge, "lattice_offsets_m": offsets,
            "landscape_none_sample": none_pts,
            "worst": worst, "within_0_01_m": max_dz <= 0.01 and n_land_none == 0}


def probe_cliff(land, man, plan_json, hf):
    """UE_PLAN.md 8.5: landscape vs heightfield within 0.01 m, and a measured slope >= 65 deg."""
    imp = unreal.StreetscapeLandscapeImporter
    tile_m = man["tile_m"]
    ny = man["ny"]
    cx, cy = CLIFF_XY
    ti = int(cx // tile_m)
    tj = int(cy // tile_m)
    tile = next((t for t in man["tiles"] if t["x"] == ti and t["y"] == tj), None)
    out = {"local_xy": [cx, cy], "tile": [ti, tj], "tile_slope_max_deg": (tile or {}).get("slope_max_deg"),
           "points": 0, "max_abs_dz_m": None, "slope_max_deg": None, "agree": None, "n_landscape_none": 0}
    if cx < 0 or cy < 0 or cx > man["nx"] * tile_m or cy > ny * tile_m:
        out["skipped"] = "outside this manifest's coverage"
        return out
    max_dz = 0.0
    max_slope = 0.0
    n = 0
    none_land = 0
    rows = []
    for dx in CLIFF_LINES:
        x = cx + dx
        prev = None
        for y in range(int(cy - CLIFF_SPAN), int(cy + CLIFF_SPAN) + 1):
            zh = hf.probe_m(x, float(y))
            zl = imp.probe_height_m(land, x, float(y), False)
            n += 1
            if zl is None or math.isnan(zl):
                none_land += 1
            elif not math.isnan(zh):
                max_dz = max(max_dz, abs(zh - zl))
            if prev is not None and not math.isnan(zh) and not math.isnan(prev):
                max_slope = max(max_slope, math.degrees(math.atan(abs(zh - prev))))
            prev = zh
            rows.append((x, float(y), zh, zl))
    out["points"] = n
    out["max_abs_dz_m"] = round(max_dz, 5)
    out["transect_slope_max_deg"] = round(max_slope, 2)
    out["n_landscape_none"] = none_land
    out["agree"] = max_dz <= 0.01 and none_land == 0
    out["rows_sample"] = [[round(r[0], 1), round(r[1], 1), _f(r[2]), _f(r[3])] for r in rows[:4]]

    # The 5 x 101 m transect above is the nominal one of UE_PLAN.md 8.5, but the cliff face is not guaranteed to
    # fall inside it (measured: it does not - the transect tops out at ~17 deg while the tile's slope_max_deg is
    # 81.7). So also scan the WHOLE tile at its native 1 m spacing, exactly as the pipeline computed
    # tiles[].slope_max_deg, and report the steepest adjacent pair - then check the landscape against the
    # heightfield AT THAT PAIR, which is the point of the exercise.
    tx0, ty0 = tile_m * ti, tile_m * tj
    rowsz = []
    for r in range(tile_m + 1):
        y = float(ty0 + r)
        rowsz.append([hf.probe_m(float(tx0 + c), y) for c in range(tile_m + 1)])
    best = (0.0, None)
    for r in range(tile_m + 1):
        zr = rowsz[r]
        for c in range(tile_m + 1):
            z = zr[c]
            if math.isnan(z):
                continue
            if c + 1 <= tile_m and not math.isnan(zr[c + 1]):
                d = abs(zr[c + 1] - z)
                if d > best[0]:
                    best = (d, (tx0 + c, ty0 + r, tx0 + c + 1, ty0 + r))
            if r + 1 <= tile_m and not math.isnan(rowsz[r + 1][c]):
                d = abs(rowsz[r + 1][c] - z)
                if d > best[0]:
                    best = (d, (tx0 + c, ty0 + r, tx0 + c, ty0 + r + 1))
    scan_slope = math.degrees(math.atan(best[0]))

    # ... and the CENTRAL-difference slope over the same grid, which is what the manifest's
    # tiles[].slope_max_deg actually is: sources/derive/05_*.py:79-80 does
    #     gy, gx = np.gradient(a); slope = degrees(atan(hypot(gx/pw, gy/ph)))
    # and np.gradient's interior term is (a[k+1] - a[k-1]) / 2 (one-sided at the edges, edge_order=1).
    # A step between two adjacent posts is therefore spread over 2 m and reads shallower by construction:
    # comparing the adjacent-pair maximum above against the manifest compares two different operators, so
    # the "does the landscape keep the cliffs" test is central-vs-central, and the pair maximum is reported
    # beside it as the steepest single-cell face.
    def _d(lo, hi, span):
        if lo is None or hi is None or math.isnan(lo) or math.isnan(hi):
            return None
        return (hi - lo) / span

    central_max = 0.0
    for r in range(tile_m + 1):
        for c in range(tile_m + 1):
            if math.isnan(rowsz[r][c]):
                continue
            if c == 0:
                gx = _d(rowsz[r][0], rowsz[r][1], 1.0)
            elif c == tile_m:
                gx = _d(rowsz[r][tile_m - 1], rowsz[r][tile_m], 1.0)
            else:
                gx = _d(rowsz[r][c - 1], rowsz[r][c + 1], 2.0)
            if r == 0:
                gy = _d(rowsz[0][c], rowsz[1][c], 1.0)
            elif r == tile_m:
                gy = _d(rowsz[tile_m - 1][c], rowsz[tile_m][c], 1.0)
            else:
                gy = _d(rowsz[r - 1][c], rowsz[r + 1][c], 2.0)
            if gx is None or gy is None:
                continue
            central_max = max(central_max, math.hypot(gx, gy))
    central_slope = math.degrees(math.atan(central_max))

    out["tile_scan"] = {
        "tile_local_origin": [tx0, ty0],
        "samples": (tile_m + 1) ** 2,
        "slope_max_deg": round(scan_slope, 2),
        "central_diff_max_deg": round(central_slope, 2),
        "steepest_pair": list(best[1]) if best[1] else None,
    }
    if best[1]:
        ax, ay, bx, by = best[1]
        za_h, zb_h = hf.probe_m(float(ax), float(ay)), hf.probe_m(float(bx), float(by))
        za_l = imp.probe_height_m(land, float(ax), float(ay), False)
        zb_l = imp.probe_height_m(land, float(bx), float(by), False)
        out["tile_scan"]["z_heightfield_m"] = [_f(za_h), _f(zb_h)]
        out["tile_scan"]["z_landscape_m"] = [_f(za_l), _f(zb_l)]
        out["tile_scan"]["max_abs_dz_m"] = round(max(abs(za_h - za_l), abs(zb_h - zb_l)), 6)
        out["tile_scan"]["agree"] = out["tile_scan"]["max_abs_dz_m"] <= 0.01
    out["slope_max_deg"] = round(scan_slope, 2)
    out["slope_central_diff_max_deg"] = round(central_slope, 2)
    out["slope_operators"] = ("slope_max_deg = steepest adjacent post pair (atan(|dz| / 1 m)); "
                              "slope_central_diff_max_deg = np.gradient central differences, the operator "
                              "sources/derive/05 used for tiles[].slope_max_deg. Compare like with like.")
    out["slope_ok"] = scan_slope >= 65.0
    if tile and tile.get("slope_max_deg") is not None:
        out["slope_vs_tile_deg"] = round(central_slope - float(tile["slope_max_deg"]), 2)
        out["slope_within_2deg_of_tile"] = abs(central_slope - float(tile["slope_max_deg"])) <= 2.0
        out["pair_slope_vs_tile_deg"] = round(scan_slope - float(tile["slope_max_deg"]), 2)
    return out


def probe_clip(land, man, plan_json, hf):
    """UE_PLAN.md 8.6: at 20 points along clip.line, P+ (kept) has ground and blocks a trace, P- (cut) has neither."""
    imp = unreal.StreetscapeLandscapeImporter
    clip = (plan_json or {}).get("clip")
    if not clip:
        return {"skipped": "no clip in the manifest"}
    (ax, ay), (bx, by) = clip["line_local_m"]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    # keep 'left' of A->B: cross(B-A, P-A) >= 0, so the inward unit normal is perp(u) = (-uy, ux)
    nx, ny_ = (-uy, ux) if clip.get("keep", "left") == "left" else (uy, -ux)
    zmax = float(man["range_m"][1]) + 200.0
    zmin = float(man["range_m"][0]) - 200.0
    pts = []
    ok_plus = ok_minus = 0
    for k in range(CLIP_SAMPLES):
        s = (k + 0.5) / CLIP_SAMPLES
        mx, my = ax + dx * s, ay + dy * s
        if not (0 <= mx <= man["nx"] * man["tile_m"] and 0 <= my <= man["ny"] * man["tile_m"]):
            continue
        row = {"s": round(s, 4), "mid": [round(mx, 2), round(my, 2)]}
        for sign, tag in ((+1.0, "plus"), (-1.0, "minus")):
            px = mx + sign * CLIP_OFFSET_M * nx
            py = my + sign * CLIP_OFFSET_M * ny_
            zh = hf.probe_m(px, py)
            zc = imp.probe_height_m(land, px, py, True)
            zt = imp.trace_down_zm(px, py, zmax, zmin)
            row[tag] = {
                "xy": [round(px, 2), round(py, 2)],
                "z_heightfield_m": _f(zh),
                "z_landscape_collision_m": _f(zc),
                "trace_z_m": _f(zt),
                "blocked": not (zt is None or math.isnan(zt)),
            }
        if row["plus"]["blocked"] and row["plus"]["z_heightfield_m"] is not None:
            ok_plus += 1
        if not row["minus"]["blocked"] and row["minus"]["z_heightfield_m"] is None:
            ok_minus += 1
        pts.append(row)
    if not pts:
        # every sample of the clip line fell outside this manifest's coverage (a cutout, say). "pass: false" for
        # that is a lie about the cut; say the probe did not run and let --allow-skipped-gates decide.
        return {"skipped": "the clip line does not cross this manifest's coverage (0 of %d samples inside)" % CLIP_SAMPLES,
                "line_local_m": [[round(ax, 2), round(ay, 2)], [round(bx, 2), round(by, 2)]],
                "keep": clip.get("keep"), "samples": 0}
    mid = (ax + dx * 0.5, ay + dy * 0.5)
    return {
        "line_local_m": [[round(ax, 2), round(ay, 2)], [round(bx, 2), round(by, 2)]],
        "keep": clip.get("keep"),
        "length_m": round(length, 2),
        "midpoint": [round(mid[0], 2), round(mid[1], 2)],
        "midpoint_plus": [round(mid[0] + CLIP_OFFSET_M * nx, 2), round(mid[1] + CLIP_OFFSET_M * ny_, 2)],
        "midpoint_minus": [round(mid[0] - CLIP_OFFSET_M * nx, 2), round(mid[1] - CLIP_OFFSET_M * ny_, 2)],
        "samples": len(pts),
        "kept_side_ok": ok_plus,
        "cut_side_ok": ok_minus,
        "pass": len(pts) > 0 and ok_plus == len(pts) and ok_minus == len(pts),
        "points": pts,
    }


def probe_counts(report, plan_json, man, whole_world_loaded):
    """The gate nobody was running: does the LEVEL hold what the PLAN said it would?

    components / proxies / extent came back in the report as data and nothing branched on them, so an import that
    built 1,700 of 2,067 components printed THANET_OK with the shortfall inside the JSON. Also checks that every
    tile the manifest lists was actually read (tiles_read), which is the counted version of "a heightmap tile that
    could not be read". In --probes-only --no-load-all only the streamed proxies are in ULandscapeInfo, so the
    component/proxy comparison is meaningless there and says so instead of passing.
    """
    land = report.get("landscape") or {}
    imp = report.get("import") or {}
    out = {
        "components_in_level": land.get("components"),
        "components_planned": plan_json.get("components_planned"),
        "proxies_in_level": land.get("proxies"),
        "proxies_expected": plan_json.get("proxies_expected"),
        "extent_in_level": land.get("extent"),
        "extent_planned": plan_json.get("extent"),
        "tiles_read": imp.get("tiles_read"),
        "tiles_in_manifest": plan_json.get("tiles_in_manifest"),
        "whole_world_loaded": bool(whole_world_loaded),
    }
    if not whole_world_loaded:
        out["skipped"] = ("only the streamed proxies are in ULandscapeInfo::XYtoComponentMap, so a component or "
                          "proxy count taken here is a count of what happens to be loaded, not of the landscape")
        return out
    bad = []
    if out["components_in_level"] != out["components_planned"]:
        bad.append("components %s != planned %s" % (out["components_in_level"], out["components_planned"]))
    if out["proxies_in_level"] != out["proxies_expected"]:
        bad.append("proxies %s != expected %s" % (out["proxies_in_level"], out["proxies_expected"]))
    if out["extent_in_level"] != out["extent_planned"]:
        bad.append("extent %s != planned %s" % (out["extent_in_level"], out["extent_planned"]))
    if out["tiles_read"] is not None and out["tiles_read"] != out["tiles_in_manifest"]:
        bad.append("tiles_read %s != tiles_in_manifest %s" % (out["tiles_read"], out["tiles_in_manifest"]))
    out["problems"] = bad
    out["ok"] = not bad
    return out


def main(argv):
    opts = uc.parse_args(argv, flags=("probes_only", "recreate_map", "no_cliff", "no_clip", "no_grid", "no_load_all",
                                      "allow_skipped_gates", "no_counts"), options={
        "manifest": "",
        "qps": "127",
        "sections": "2",
        "wp_grid": "4",
        "max_components": "0",
        "map": DEFAULT_MAP,
        "material": DEFAULT_MATERIAL,
        "layer_path": DEFAULT_LAYER_PATH,
        "report": "",
        "grid_per_tile": "5",
        "max_shared_edge_h16": "0",
    })
    if not opts["manifest"]:
        uc.fail(NAME, "--manifest is required")
    manifest = opts["manifest"].replace("\\", "/")
    if not os.path.isfile(manifest):
        uc.fail(NAME, "no such manifest: %s" % manifest)
    man = manifest_tiles(manifest)

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    map_path = opts["map"]
    content_umap = uc.content_dir() + map_path[len("/Game"):] + ".umap"
    if opts["recreate_map"] and os.path.isfile(content_umap):
        delete_map(map_path, content_umap)
    if opts["recreate_map"] or not os.path.isfile(content_umap):
        if not les.new_level(map_path, True):
            uc.fail(NAME, "new_level(%s, partitioned) failed" % map_path)
        # a landscape needs a saved package before it can create external actors
        if not les.save_current_level():
            uc.fail(NAME, "save_current_level failed for the new map")
        uc.log("map %s created (World Partition)" % map_path)
    else:
        if not les.load_level(map_path):
            uc.fail(NAME, "load_level(%s) failed" % map_path)
        uc.log("map %s loaded" % map_path)

    imp = unreal.StreetscapeLandscapeImporter
    plan_json = plan(opts)
    uc.log("plan: %s" % json.dumps(plan_json, sort_keys=True))
    if plan_json.get("error"):
        uc.fail(NAME, "manifest rejected: %s" % plan_json["error"])

    report = {"plan": plan_json, "manifest": manifest, "map": map_path, "probes_only": bool(opts["probes_only"])}

    if not opts["probes_only"]:
        rss0 = imp.rss_mb()
        land, import_json = imp.import_site(manifest, int(opts["qps"]), int(opts["sections"]), int(opts["wp_grid"]),
                                            opts["material"], opts["layer_path"], int(opts["max_components"]),
                                            int(opts["max_shared_edge_h16"]))
        result = json.loads(import_json)
        report["import"] = result
        report["rss_mb_before_call"] = round(rss0, 1)
        uc.log("import_site -> ok=%s components=%s proxies=%s regions=%s" %
               (result.get("ok"), result.get("components"), result.get("proxies"), result.get("regions_used")))
        if not result.get("ok"):
            uc.fail(NAME, "import_site failed: %s" % result.get("error"))
    else:
        report["import"] = None

    land = imp.find_landscape()
    if land is None:
        uc.fail(NAME, "no ALandscape in the level after the import")

    grid_skipped = None
    if opts["probes_only"]:
        # A World Partition commandlet loads nothing (WorldPartition.cpp:880-886), so the landscape's components
        # live in unloaded streaming proxies and GetHeightAtLocation returns nothing.
        imp_lib = unreal.StreetscapeEditorLibrary
        tile_m = man["tile_m"]
        if opts["no_load_all"]:
            # the cheap path: JUST the cells the cliff and clip probes touch. probe_grid walks EVERY tile of the
            # manifest, so most of its points would be unstreamed and it would report a verdict about nothing:
            # say so instead of emitting one.
            ti, tj = int(CLIFF_XY[0] // tile_m), int(CLIFF_XY[1] // tile_m)
            cxm, cym = tile_m * (ti + 0.5), tile_m * (tj + 0.5)
            imp_lib.load_region(unreal.Vector(100.0 * cxm, -100.0 * cym, 0.0), 100.0 * tile_m)
            clip = (plan_json or {}).get("clip")
            loaded = 1
            if clip:
                (ax, ay), (bx, by) = clip["line_local_m"]
                for k in range(CLIP_SAMPLES):
                    t = (k + 0.5) / CLIP_SAMPLES
                    px, py = ax + (bx - ax) * t, ay + (by - ay) * t
                    if 0 <= px <= man["nx"] * tile_m and 0 <= py <= man["ny"] * tile_m:
                        imp_lib.load_region(unreal.Vector(100.0 * px, -100.0 * py, 0.0), 30000.0)
                        loaded += 1
            uc.log("probes-only --no-load-all: loaded %d World Partition regions (cliff tile + clip line only)" % loaded)
            grid_skipped = "--no-load-all streams only the cliff tile and the clip line; probe_grid walks every tile"
        else:
            # the honest path: stream the whole world so the grid gate probes the landscape it claims to probe
            # (~5 GB RSS, measured 12.5 s in 04_probe --landscape-info --load-all)
            imp_lib.load_region(unreal.Vector(0.0, 0.0, 0.0), 2000000.0)
            uc.log("probes-only: streamed the whole world (rss %.1f MB) so the grid probe sees every tile" % imp.rss_mb())
    report["landscape"] = json.loads(imp.landscape_state_json(land))
    uc.log("landscape: %s" % json.dumps(report["landscape"], sort_keys=True))

    # the reference heightfield must read the SAME directory the landscape came from (DESIGN.md 8)
    site_actor = unreal.StreetscapeEditorLibrary.ensure_site_actor(str(man.get("site", uc.site_name())),
                                                                   float(man["origin"]["E"]), float(man["origin"]["N"]))
    prev_dir = ""
    if site_actor is not None:
        t = site_actor.get_editor_property("terrain_source")
        if t is not None:
            prev_dir = str(t.get_editor_property("landscape_dir") or "")
    hf = uc.heightfield(os.path.dirname(manifest))
    if hf is None:
        uc.fail(NAME, "no site actor / terrain source to probe the heightfield with")
    report["terrain_source"] = {"describe": hf.describe_source(), "tiles": hf.num_tiles()}
    uc.log("heightfield: %s" % report["terrain_source"]["describe"])

    if not opts["no_grid"]:
        if grid_skipped:
            report["grid"] = {"skipped": grid_skipped}
        else:
            report["grid"] = probe_grid(land, man, hf, int(opts["grid_per_tile"]))
        uc.log("grid probe: %s" % json.dumps(report["grid"], sort_keys=True))
    if not opts["no_cliff"]:
        report["cliff"] = probe_cliff(land, man, plan_json, hf)
        uc.log("cliff probe: %s" % json.dumps({k: v for k, v in report["cliff"].items() if k != "rows_sample"}, sort_keys=True))
    if not opts["no_clip"]:
        clip = probe_clip(land, man, plan_json, hf)
        report["clip"] = clip
        uc.log("clip probe: %s" % json.dumps({k: v for k, v in clip.items() if k != "points"}, sort_keys=True))

    if not opts["no_counts"]:
        report["counts"] = probe_counts(report, plan_json, man,
                                        whole_world_loaded=not (opts["probes_only"] and opts["no_load_all"]))
        uc.log("counts gate: %s" % json.dumps(report["counts"], sort_keys=True))

    uc.save_all()
    report["rss_mb_end"] = round(imp.rss_mb(), 1)

    out_path = opts["report"] or (uc.project_dir() + "/Saved/Tests/landscape_import_%s.json" % os.path.basename(os.path.dirname(manifest)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="\n") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
        fh.write("\n")

    summary = {
        "map": map_path,
        "report": out_path.replace("\\", "/"),
        "components": report["landscape"].get("components"),
        "proxies": report["landscape"].get("proxies"),
        "extent": report["landscape"].get("extent"),
        "padding": plan_json.get("padding"),
        "fill_h16": plan_json.get("fill_h16"),
        "components_planned": plan_json.get("components_planned"),
        "helper_suggestion": plan_json.get("helper_suggestion"),
        "region_path": (report.get("import") or {}).get("region_path"),
        "regions_used": (report.get("import") or {}).get("regions_used"),
        "rss_mb": (report.get("import") or {}).get("rss_mb"),
        "seconds": (report.get("import") or {}).get("seconds"),
        "grid": {k: report.get("grid", {}).get(k) for k in ("points", "compared", "heightfield_nan", "landscape_none", "max_abs_dz_m", "within_0_01_m")} if "grid" in report else None,
        "cliff": {k: report.get("cliff", {}).get(k) for k in ("max_abs_dz_m", "transect_slope_max_deg", "slope_max_deg", "tile_slope_max_deg", "slope_vs_tile_deg", "slope_within_2deg_of_tile", "agree", "slope_ok", "tile_scan", "skipped")} if "cliff" in report else None,
        "clip": {k: report.get("clip", {}).get(k) for k in ("samples", "kept_side_ok", "cut_side_ok", "pass")} if "clip" in report else None,
        "shared_edge": (report.get("import") or {}).get("shared_edge"),
        "counts": report.get("counts"),
    }

    # ---- the verdict. Before this the script printed THANET_OK whatever the probes concluded: grid.within_0_01_m,
    # cliff.agree, cliff.slope_ok and clip.pass were carried as data and nothing branched on them (STAGES 1.13).
    failures = []
    skipped = []

    def check(section, key, want=True):
        sec = report.get(section)
        if sec is None:
            return                       # the probe was switched off with --no-<section>
        if "skipped" in sec:
            # a gate that did not run is not a gate that passed. --no-load-all and a clip-less manifest both land
            # here, and both used to print one log line and let the run report success.
            if opts["allow_skipped_gates"]:
                uc.log("gate %s.%s: SKIPPED and ALLOWED by --allow-skipped-gates (%s)" % (section, key, sec["skipped"]))
                skipped.append("%s.%s (%s)" % (section, key, sec["skipped"]))
                return
            failures.append("%s.%s did not run: %s (pass --allow-skipped-gates to accept that on purpose)"
                            % (section, key, sec["skipped"]))
            return
        got = sec.get(key)
        if got is None:
            failures.append("%s.%s was not computed" % (section, key))
        elif bool(got) != want:
            failures.append("%s.%s is %s" % (section, key, got))

    check("grid", "within_0_01_m")
    check("cliff", "agree")
    check("cliff", "slope_ok")
    check("clip", "pass")
    check("counts", "ok")
    se = (report.get("import") or {}).get("shared_edge")
    if se is not None and not se.get("ok", True):
        failures.append("shared_edge.ok is False (max %s h16 over %s visible samples)"
                        % (se.get("visible_max_h16_delta"), se.get("visible_samples_checked")))
    if se is not None and se.get("waived"):
        uc.log("WARNING: the shared-edge gate was WAIVED (--max-shared-edge-h16 %s); worst %s h16 = %s m at %s"
               % (opts["max_shared_edge_h16"], se.get("visible_max_h16_delta"), se.get("visible_max_m"), se.get("worst_local_m")))
    # ...but the LEVEL must not keep it.  The gates above probe the landscape against the directory it
    # was imported from, which since docs/TERRAIN_ROADS.md 8 is `landscape_conformed`; the streets are
    # a different question and BRIEF 1.1 answers it -- a road drapes on the SURVEY.  Leaving the probe's
    # directory on the saved site actor makes the next 03_import_streetscape build its roads on the
    # ground that was burned from roads, a feedback loop whose first symptom is terrain standing back
    # up through the carriageway. Restore whatever the level had.
    if site_actor is not None:
        t = site_actor.get_editor_property("terrain_source")
        probe_dir = os.path.normpath(os.path.dirname(manifest)).lower()
        keep = prev_dir if (prev_dir and os.path.normpath(prev_dir).lower() != probe_dir) else ""
        if t is not None and str(t.get_editor_property("landscape_dir") or "") != keep:
            t.set_editor_property("landscape_dir", keep)
            t.load()
            uc.log("terrain source set to %r for the level (the probe's %s is temporary)"
                   % (keep or "<settings default: the survey>", os.path.dirname(manifest)))
            uc.save_all()
    summary["gates_failed"] = failures
    summary["gates_skipped"] = skipped
    if failures:
        uc.log("report written to %s" % out_path.replace("\\", "/"))
        uc.fail(NAME, "gate(s) failed: %s | summary %s" % ("; ".join(failures), json.dumps(summary, sort_keys=True)))
    uc.report(NAME, summary)


if __name__ == "__main__":
    main(sys.argv)
