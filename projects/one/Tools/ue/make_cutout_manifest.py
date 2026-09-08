"""make_cutout_manifest - a small landscape_manifest.json (plus its tile files) cut out of a big one.

STAGES.md 1 task 13: gate step (a) of D1 imports a 2x2-tile Margate window so the whole landscape path is proved on
something that takes seconds. The cutout is a *complete* adapter product in its own right: the window is re-indexed
to nx = ny = size, the site origin is moved to the window's south-west tile corner, every tile file is copied under
its new name, and the derived fields (range_m, slope_qa, clipped_cells_total, ue_import_unpadded) are recomputed
from the tiles that survive - so the importer cannot tell it from a real site.

stdlib only; run it with the pipeline python (STAGES.md command conventions):

    C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/make_cutout_manifest.py \
        --manifest <in>/landscape_manifest.json --tiles 15,15 --size 2 --out <out>/landscape_manifest.json
"""
import argparse
import json
import os
import shutil
import sys


def die(msg):
    sys.stderr.write("make_cutout_manifest: %s\n" % msg)
    raise SystemExit(2)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, help="source landscape_manifest.json")
    ap.add_argument("--tiles", required=True, help="south-west tile of the window as i,j (manifest indices)")
    ap.add_argument("--size", type=int, default=2, help="window size in tiles (size x size)")
    ap.add_argument("--out", required=True, help="destination landscape_manifest.json (its directory is created)")
    ap.add_argument("--no-copy", action="store_true", help="write the manifest only (the tile files must already be there)")
    a = ap.parse_args(argv[1:])

    x0, y0 = (int(v) for v in a.tiles.split(","))
    size = a.size
    src_dir = os.path.dirname(os.path.abspath(a.manifest))
    out_path = os.path.abspath(a.out)
    out_dir = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)

    with open(a.manifest) as fh:
        m = json.load(fh)
    tile_m = m["tile_m"]
    ny_old = m["ny"]

    keep = {}
    for t in m["tiles"]:
        if x0 <= t["x"] < x0 + size and y0 <= t["y"] < y0 + size:
            keep[(t["x"], t["y"])] = t
    if not keep:
        die("no tiles of %s in the window (%d, %d) size %d" % (a.manifest, x0, y0, size))

    def reindex_name(name, i, j):
        return name.replace("_x%d_y%d." % (i, j), "_x%d_y%d." % (i - x0, j - y0))

    new_tiles = []
    copied = 0
    for (i, j), t in sorted(keep.items()):
        nt = json.loads(json.dumps(t))
        nt["x"], nt["y"] = i - x0, j - y0
        files = nt.get("files") or {}
        for key in ("heightmap", "clip", "vis"):
            if files.get(key):
                new_name = reindex_name(files[key], i, j)
                if not a.no_copy:
                    shutil.copyfile(os.path.join(src_dir, files[key]), os.path.join(out_dir, new_name))
                    copied += 1
                files[key] = new_name
        w = files.get("weights")
        if w:
            for band, name in list(w.items()):
                if not name:
                    continue
                new_name = reindex_name(name, i, j)
                if not a.no_copy:
                    shutil.copyfile(os.path.join(src_dir, name), os.path.join(out_dir, new_name))
                    copied += 1
                w[band] = new_name
        # quad origin in the cutout frame: x = tile_m*i', y = tile_m*(ny'-1-j')
        nt["quad_origin"] = [tile_m * nt["x"], tile_m * (size - 1 - nt["y"])]
        new_tiles.append(nt)

    out = json.loads(json.dumps(m))
    out["tiles"] = new_tiles
    out["nx"] = size
    out["ny"] = size
    out["origin"] = {"E": m["origin"]["E"] + tile_m * x0, "N": m["origin"]["N"] + tile_m * y0}
    out["site"] = "%s_cutout_x%d_y%d_s%d" % (m.get("site", "site"), x0, y0, size)
    out["cutout_of"] = {
        "manifest": os.path.abspath(a.manifest),
        "site": m.get("site"),
        "tiles": [x0, y0],
        "size": size,
        "note": "tile indices are re-based to 0 and the origin moved by (tile_m*i0, tile_m*j0); heights are byte-identical copies",
    }
    for key in ("tiles_clipped", "tiles_missing"):
        vals = [[i - x0, j - y0] for i, j in (tuple(v) for v in m.get(key) or []) if x0 <= i < x0 + size and y0 <= j < y0 + size]
        out[key] = vals
    if m.get("water_tiles") is not None:
        out["water_tiles"] = [[i - x0, j - y0] for i, j in (tuple(v) for v in m["water_tiles"]) if x0 <= i < x0 + size and y0 <= j < y0 + size]
    if m.get("tiles_without_ground_raster") is not None:
        out["tiles_without_ground_raster"] = [[i - x0, j - y0] for i, j in (tuple(v) for v in m["tiles_without_ground_raster"])
                                              if x0 <= i < x0 + size and y0 <= j < y0 + size]
    out["clipped_cells_total"] = sum(int(t.get("clipped_cells") or 0) for t in new_tiles)
    mins = [t["min_m"] for t in new_tiles if t.get("min_m") is not None]
    maxs = [t["max_m"] for t in new_tiles if t.get("max_m") is not None]
    if mins and maxs:
        out["range_m"] = [min(mins), max(maxs)]
    slopes = [t["slope_max_deg"] for t in new_tiles if t.get("slope_max_deg") is not None]
    if slopes and isinstance(out.get("slope_qa"), dict):
        out["slope_qa"] = dict(out["slope_qa"])
        out["slope_qa"]["max_deg"] = max(slopes)
        out["slope_qa"]["note"] = "recomputed as the max of the cutout's tiles by make_cutout_manifest.py"
    verts = [size * tile_m + 1, size * tile_m + 1]
    if isinstance(out.get("ue_import_unpadded"), dict):
        out["ue_import_unpadded"] = dict(out["ue_import_unpadded"])
        out["ue_import_unpadded"]["verts"] = verts
        out["ue_import_unpadded"]["actor_location_cm"] = [0, -100 * (verts[1] - 1), 0]
    out.pop("weight_sum_histogram", None)

    with open(out_path, "w", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=False)
        fh.write("\n")
    print(json.dumps({
        "out": out_path.replace("\\", "/"),
        "tiles": len(new_tiles),
        "files_copied": copied,
        "nx": size, "ny": size,
        "verts": verts,
        "origin": out["origin"],
        "range_m": out.get("range_m"),
        "slope_max_deg": (out.get("slope_qa") or {}).get("max_deg"),
        "clipped_cells_total": out["clipped_cells_total"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
