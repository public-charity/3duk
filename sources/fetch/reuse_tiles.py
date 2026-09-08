#!/usr/bin/env python3
"""Reuse one site's fetched LIDAR tiles for another site whose grid is a tile-aligned superset.

    PY sources/fetch/reuse_tiles.py --from margate --to thanet [--dry-run] [--link]

Thanet's grid was chosen so Margate's is a sub-grid (Margate tile (i, j) == Thanet tile (i+10, j+10)):
the rasters step 02 would fetch for those positions are bit-identical to the ones already on disk, so
they are copied under the new names instead of re-downloaded (182 files, ~730 MB). Nothing is trusted
by name alone -- each check prints both values and stops:
  1. crs, tile_m and grid_res equal;
  2. the wcs blocks equal (notes stripped): a different coverage is a different survey;
  3. the origin offset is a whole number of tiles (di, dj);
  4. the source directory's _grid.json equals lib.grid_stamp(source config);
  5. the target directory's _grid.json, if present, equals lib.grid_stamp(target config); if absent it is
     written AFTER the copies succeed so step 02 accepts the directory and fetches only the rest;
  6. every source file: grid_res x grid_res float32 by its TIFF header, and its own georeferencing tag
     (lib.tiff_info georef_origin: ModelTransformationTag 34264 on raw EA tiles, tiepoint 33922 on
     GDAL-written ones) lands exactly where the NEW name says; a target outside the target grid or wholly
     outside the target's clip is skipped and counted; a destination already present must hash equal to
     the source (a different tile under the same name is the one thing 02's cache can never detect);
  7. a summary {copied, present, outside_target_grid, outside_clip} and the mapping rule.

Run BEFORE step 02 for the target site. --dry-run does every check and copies nothing; --link makes NTFS
hard links instead of copies (same volume only).
"""
import argparse, hashlib, json, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def strip_notes(d):
    """Config blocks minus their prose (`note`, `*_note`, `_*` keys), so two sites that document the
    same coverage differently still compare equal."""
    if isinstance(d, dict):
        return {k: strip_notes(v) for k, v in d.items()
                if not (k == "note" or k.endswith("_note") or k.startswith("_"))}
    return d


def fatal(msg):
    sys.exit(f"reuse_tiles: FATAL -- {msg}")


def main():
    ap = argparse.ArgumentParser(description="copy one site's LIDAR tiles into another site's grid under their new indices")
    ap.add_argument("--from", dest="src", required=True, help="site whose data/<site>/raw/lidar tiles are reused")
    ap.add_argument("--to", dest="dst", required=True, help="site that receives them")
    ap.add_argument("--dry-run", action="store_true", help="run every check, copy nothing, write no stamp")
    ap.add_argument("--link", action="store_true", help="hard-link instead of copying (same volume only)")
    a = ap.parse_args()
    if a.src == a.dst:
        fatal("--from and --to name the same site")

    fc, tc = lib.load(a.src), lib.load(a.dst)
    fp, tp = lib.paths(fc), lib.paths(tc)
    T, RES = tc["tile_m"], tc["grid_res"]

    # 1. raster-defining scalars
    for k in ("crs", "tile_m", "grid_res"):
        if fc[k] != tc[k]:
            fatal(f"{k} differs: {a.src}={fc[k]!r} {a.dst}={tc[k]!r}")
    # 2. same coverages
    fw, tw = strip_notes(fc["wcs"]), strip_notes(tc["wcs"])
    if fw != tw:
        fatal(f"wcs blocks differ (a different coverage is a different survey):\n"
              f"  {a.src}: {json.dumps(fw, sort_keys=True)}\n  {a.dst}: {json.dumps(tw, sort_keys=True)}")
    # 3. whole-tile offset
    dE, dN = fc["origin"]["E"] - tc["origin"]["E"], fc["origin"]["N"] - tc["origin"]["N"]
    if dE % T or dN % T:
        fatal(f"origins are not {T} m aligned: dE={dE} dN={dN} ({a.src} {fc['origin']} vs {a.dst} {tc['origin']})")
    di, dj = dE // T, dN // T
    rule = f"{a.src} tile (i, j) == {a.dst} tile (i{di:+d}, j{dj:+d})"
    # 4. the source directory holds tiles for the source grid
    src_stamp_path = os.path.join(fp["lidar"], "_grid.json")
    if not os.path.exists(src_stamp_path):
        fatal(f"{src_stamp_path} missing: {a.src}'s tiles were not fetched by step 02 (or the directory moved)")
    src_stamp, expect_src = json.load(open(src_stamp_path)), lib.grid_stamp(fc)
    if src_stamp != expect_src:
        fatal(f"{src_stamp_path} does not match the {a.src} config:\n  stamp:  {src_stamp}\n  config: {expect_src}")
    # 5. the target stamp, if any, must already be the target grid
    dst_stamp_path = os.path.join(tp["lidar"], "_grid.json")
    expect_dst = lib.grid_stamp(tc)
    stamp_present = os.path.exists(dst_stamp_path)
    if stamp_present:
        dst_stamp = json.load(open(dst_stamp_path))
        if dst_stamp != expect_dst:
            fatal(f"{dst_stamp_path} holds a different grid:\n  stamp:  {dst_stamp}\n  config: {expect_dst}\n"
                  f"  Delete {tp['lidar']} to start over.")

    # 6. per file
    to_clip = lib.parse_clip(tc)
    E0, N0 = tc["origin"]["E"], tc["origin"]["N"]
    pat = re.compile(r"^(dtm|dsm)_x(\d+)_y(\d+)\.tif$")
    files = sorted(f for f in os.listdir(fp["lidar"]) if pat.match(f))
    if not files:
        fatal(f"no {{dtm,dsm}}_x*_y*.tif in {fp['lidar']}")
    counts = {"copied": 0, "present": 0, "outside_target_grid": 0, "outside_clip": 0}
    planned = []
    for name in files:
        kind, i, j = pat.match(name).groups()
        i, j = int(i), int(j)
        i2, j2 = i + di, j + dj
        if not (0 <= i2 < tc["nx"] and 0 <= j2 < tc["ny"]):
            counts["outside_target_grid"] += 1
            continue
        if lib.tile_state(to_clip, tc, i2, j2) == "outside":
            counts["outside_clip"] += 1
            continue
        src = os.path.join(fp["lidar"], name)
        info = lib.tiff_info(src)
        if not info or info["width"] != RES or info["height"] != RES or info["dtype"] != "float32":
            fatal(f"{src}: header says {info}, expected {RES}x{RES} float32")
        want = (E0 + i2 * T - 0.5, N0 + j2 * T + T + 0.5)
        got = info.get("georef_origin")
        if got is None or abs(got[0] - want[0]) > 1e-6 or abs(got[1] - want[1]) > 1e-6:
            fatal(f"{src}: georeferenced origin is {got} but {kind}_x{i2}_y{j2}.tif in {a.dst}'s grid must start at {want}")
        planned.append((src, os.path.join(tp["lidar"], f"{kind}_x{i2}_y{j2}.tif")))

    print(f"reuse_tiles: {rule}; {len(files)} source rasters, {len(planned)} land in {a.dst}'s grid"
          + (f" (clip: {to_clip.stamp()})" if to_clip is not None else ""))
    if not a.dry_run:
        lib.mkdirs(tp["lidar"])
    for src, dst in planned:
        if os.path.exists(dst):
            hs, hd = sha256(src), sha256(dst)
            if hs != hd:
                fatal(f"{dst} exists but differs from {src}\n  source: {hs}\n  target: {hd}\n"
                      f"  Not overwriting: decide which is right and delete the other.")
            counts["present"] += 1
            continue
        if a.dry_run:
            counts["copied"] += 1
            continue
        if a.link:
            os.link(src, dst)
        else:
            shutil.copyfile(src, dst)
        hs, hd = sha256(src), sha256(dst)
        if hs != hd:
            os.remove(dst)
            fatal(f"copy {src} -> {dst} does not hash equal ({hs} vs {hd}); removed")
        counts["copied"] += 1

    # 7. stamp and summary
    stamp_word = "present and matching" if stamp_present else ("would be written" if a.dry_run else "written")
    if a.dry_run:
        print(f"reuse_tiles: DRY RUN -- planned {len(planned)}, present {counts['present']}, "
              f"to copy {counts['copied']}, outside_target_grid {counts['outside_target_grid']}, "
              f"outside_clip {counts['outside_clip']}; _grid.json {stamp_word}")
        return
    if not stamp_present:
        json.dump(expect_dst, open(dst_stamp_path, "w"), indent=1)
    print(f"reuse_tiles: summary {json.dumps(counts)}; _grid.json {stamp_word} "
          f"({json.dumps(expect_dst)}); mapping {rule}")


if __name__ == "__main__":
    main()
