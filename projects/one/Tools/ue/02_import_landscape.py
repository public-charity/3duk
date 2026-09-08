"""02_import_landscape - the adapter's landscape products into one World Partition ALandscape (UE_PLAN.md 5.3 row 2).

    run_ue_python.ps1 -Script 02_import_landscape.py -Render -Args "--manifest <DATA>/landscape/landscape_manifest.json
        [--wp-grid 4] [--qps 127] [--sections 2] [--max-components 0] [--map /Game/Thanet/Maps/Thanet]
        [--recreate-map] [--probes-only] [--no-grid] [--no-cliff] [--no-clip] [--grid-per-tile 5] [--report <path.json>]"

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
    """The 'heights match the heightfield' gate: a per_tile x per_tile lattice of integer-metre vertices inside
    every tile of the manifest, landscape (EHeightfieldSource::Editor) against the adapter's own r16 bytes.
    Points whose heightfield sample is NaN (clipped or off coverage) are counted, not compared."""
    imp = unreal.StreetscapeLandscapeImporter
    tile_m = man["tile_m"]
    ny = man["ny"]
    n = 0
    n_nan = 0
    n_land_none = 0
    max_dz = 0.0
    worst = None
    step = tile_m // (per_tile + 1)
    for t in man["tiles"]:
        x0 = tile_m * t["x"]
        y0 = tile_m * (ny - 1 - t["y"])
        # local y of heightmap row r is ny*tile_m - (y0 + r); use the tile's own local square instead
        ly0 = tile_m * t["y"]
        for a in range(1, per_tile + 1):
            for b in range(1, per_tile + 1):
                x = float(x0 + a * step)
                y = float(ly0 + b * step)
                zh = hf.probe_m(x, y)
                zl = imp.probe_height_m(land, x, y, False)
                n += 1
                if math.isnan(zh):
                    n_nan += 1
                    continue
                if zl is None or math.isnan(zl):
                    n_land_none += 1
                    continue
                dz = abs(zh - zl)
                if dz > max_dz:
                    max_dz = dz
                    worst = [x, y, _f(zh), _f(zl)]
    return {"points": n, "compared": n - n_nan - n_land_none, "heightfield_nan": n_nan,
            "landscape_none": n_land_none, "max_abs_dz_m": round(max_dz, 6),
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


def main(argv):
    opts = uc.parse_args(argv, flags=("probes_only", "recreate_map", "no_cliff", "no_clip", "no_grid"), options={
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
                                            opts["material"], opts["layer_path"], int(opts["max_components"]))
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

    if opts["probes_only"]:
        # A World Partition commandlet loads nothing (WorldPartition.cpp:880-886), so the landscape's components
        # live in unloaded streaming proxies and GetHeightAtLocation returns nothing. Pull in JUST the cells the
        # probes touch - loading all 140 proxies at once is the 15 GB the import itself needed.
        tile_m = man["tile_m"]
        ti, tj = int(CLIFF_XY[0] // tile_m), int(CLIFF_XY[1] // tile_m)
        cxm, cym = tile_m * (ti + 0.5), tile_m * (tj + 0.5)
        imp_lib = unreal.StreetscapeEditorLibrary
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
        uc.log("probes-only: loaded %d World Partition regions (cliff tile + clip line)" % loaded)
    report["landscape"] = json.loads(imp.landscape_state_json(land))
    uc.log("landscape: %s" % json.dumps(report["landscape"], sort_keys=True))

    # the reference heightfield must read the SAME directory the landscape came from (DESIGN.md 8)
    unreal.StreetscapeEditorLibrary.ensure_site_actor(str(man.get("site", uc.site_name())),
                                                      float(man["origin"]["E"]), float(man["origin"]["N"]))
    hf = uc.heightfield(os.path.dirname(manifest))
    if hf is None:
        uc.fail(NAME, "no site actor / terrain source to probe the heightfield with")
    report["terrain_source"] = {"describe": hf.describe_source(), "tiles": hf.num_tiles()}
    uc.log("heightfield: %s" % report["terrain_source"]["describe"])

    if not opts["no_grid"]:
        report["grid"] = probe_grid(land, man, hf, int(opts["grid_per_tile"]))
        uc.log("grid probe: %s" % json.dumps(report["grid"], sort_keys=True))
    if not opts["no_cliff"]:
        report["cliff"] = probe_cliff(land, man, plan_json, hf)
        uc.log("cliff probe: %s" % json.dumps({k: v for k, v in report["cliff"].items() if k != "rows_sample"}, sort_keys=True))
    if not opts["no_clip"]:
        clip = probe_clip(land, man, plan_json, hf)
        report["clip"] = clip
        uc.log("clip probe: %s" % json.dumps({k: v for k, v in clip.items() if k != "points"}, sort_keys=True))

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
    }
    uc.report(NAME, summary)


if __name__ == "__main__":
    main(sys.argv)
