"""Compare two render-set snapshots frame by frame, on the ground half of each frame.

    python compare_snapshots.py renders/b1cd3e5 renders/<new> [--json <out>]

The question a snapshot pair has to answer is "did the carriageway come back?", and the honest way to
answer it is to look at the pictures.  This adds a MEASUREMENT beside the looking, so that the reading
in an INDEX.md is checkable rather than impressionistic, using the same stdlib PNG decoder the QC pass
uses (`qc_renders.decode`) over the LOWER HALF of the frame -- the half a street camera fills with the
ground it is standing on.

Four proxies, none of them a definition, and every threshold CALIBRATED by sampling the real frames
rather than guessed (the first version used a 20-level neutral-grey window and missed the carriageway
entirely, because this renderer's tarmac is a warm grey with a channel spread of about 25):

  grass   the landscape's grass material, measured at (109, 145, 46): G > R + 20 and G > B + 35.
  tarmac  the road material, measured at (104, 94, 80): warm (R >= B), channel spread <= 34, and
          40 <= luminance <= 150 -- which excludes the paving slab at (188, 179, 162), luminance 180,
          and the unlit black facades at (0, 0, 0).
  paving  the kerb/footway band: the same warm, low-spread rule at 150 < luminance <= 235.
  magenta the OSM debug overlay: R > G + 40 and B > G + 40.

A frame whose carriageway is missing shows grass where tarmac should be, so the pair (grass down,
tarmac up) is the signature to look for.  It cannot tell a recovered road from a re-textured verge on
its own; that is what opening the image is for.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qc_renders import decode                                          # noqa: E402


def metrics(path):
    a, w, h, _nch = decode(path)
    half = a[h // 2:, :, :3].astype(np.int16)
    r, g, b = half[:, :, 0], half[:, :, 1], half[:, :, 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    spread = half.max(axis=2) - half.min(axis=2)
    warm = (spread <= 34) & (r >= b)
    return {
        "grass": round(float(((g > r + 20) & (g > b + 35)).mean()), 4),
        "tarmac": round(float((warm & (lum >= 40) & (lum <= 150)).mean()), 4),
        "paving": round(float((warm & (lum > 150) & (lum <= 235)).mean()), 4),
        "magenta": round(float(((r > g + 40) & (b > g + 40)).mean()), 4),
        "lum_lower": round(float(lum.mean()), 2),
    }


def main():
    a_dir, b_dir = sys.argv[1].rstrip("/\\"), sys.argv[2].rstrip("/\\")
    outjson = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    man = json.load(open(os.path.join(b_dir, "manifest.json")))
    rows = []
    print("%-58s %-8s %17s %17s %17s" % ("id", "kind", "grass  A->B", "tarmac A->B", "magenta A->B"))
    for im in man["images"]:
        pa, pb = os.path.join(a_dir, im["png"]), os.path.join(b_dir, im["png"])
        if not (os.path.isfile(pa) and os.path.isfile(pb)):
            print("%-58s MISSING" % im["id"])
            continue
        ma, mb = metrics(pa), metrics(pb)
        row = {"id": im["id"], "kind": im["kind"], "a": ma, "b": mb,
               "d_grass": round(mb["grass"] - ma["grass"], 4),
               "d_tarmac": round(mb["tarmac"] - ma["tarmac"], 4)}
        rows.append(row)
        print("%-58s %-8s  %.4f -> %.4f  %.4f -> %.4f  %.4f -> %.4f"
              % (im["id"], im["kind"], ma["grass"], mb["grass"], ma["tarmac"], mb["tarmac"],
                 ma["magenta"], mb["magenta"]))
    for kinds, label in ((("street", "landmark"), "street+landmark"), (("aerial",), "aerial"),
                         (("seafront",), "seafront")):
        sel = [r for r in rows if r["kind"] in kinds]
        if sel:
            print("\n%-16s n=%d  mean grass %.4f -> %.4f   mean tarmac %.4f -> %.4f"
                  % (label, len(sel),
                     sum(r["a"]["grass"] for r in sel) / len(sel),
                     sum(r["b"]["grass"] for r in sel) / len(sel),
                     sum(r["a"]["tarmac"] for r in sel) / len(sel),
                     sum(r["b"]["tarmac"] for r in sel) / len(sel)))
    if outjson:
        json.dump(rows, open(outjson, "w", encoding="utf-8", newline="\n"), indent=1)
        print("wrote %s" % outjson)


if __name__ == "__main__":
    main()
