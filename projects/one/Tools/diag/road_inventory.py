#!/usr/bin/env python3
"""Inventory of the Streetscape site documents: how many splines, by layer and class."""
import argparse, collections, glob, json, os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    by_layer = collections.Counter()
    by_cls = collections.Counter()
    by_road_profile = collections.Counter()
    tiles = 0
    total = 0
    per_tile = {}
    for p in sorted(glob.glob(os.path.join(args.dir, "site_x*_y*.json"))):
        doc = json.load(open(p, encoding="utf-8"))
        tiles += 1
        n = 0
        for s in doc["splines"]:
            total += 1
            n += 1
            src = s.get("source") or {}
            by_layer[src.get("layer")] += 1
            by_cls[(src.get("layer"), src.get("cls"))] += 1
            by_road_profile[s["profile_ids"].get("road")] += 1
        per_tile[os.path.basename(p)] = n
    out = {"files": tiles, "splines": total,
           "by_layer": dict(by_layer),
           "by_layer_cls": {f"{k[0]}/{k[1]}": v for k, v in sorted(by_cls.items(), key=lambda kv: -kv[1])},
           "by_road_profile": dict(by_road_profile.most_common())}
    print(json.dumps(out, indent=1))
    if args.out:
        json.dump({**out, "per_tile": per_tile}, open(args.out, "w"), indent=1)


if __name__ == "__main__":
    main()
