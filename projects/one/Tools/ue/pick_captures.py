"""pick_captures - choose the four D5 capture sites from the data, not by eye (host-side, pipeline python).

    export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
    C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/pick_captures.py \
        --streetscape data/thanet/out/unreal/streetscape --massing data/thanet/out/unreal/massing \
        --landscape data/thanet/out/unreal/landscape --out projects/one/Saved/Diag/d5_capture_sites.json

Four sites, each chosen by a measured criterion so the picture is of something that is actually there:

  street     a marked carriageway with the most massing footprints within 40 m -> the densest built street
  seafront   a road whose ground is above 3 m ODN with sea (ground < 0 m ODN) within 150 m, longest such run
  cutting    a rail station whose ground rises by the most on BOTH sides at 25 m lateral -> a real cutting
  isle       a high camera over the centroid of the network looking along the clip line

Prints, and writes, a {tag: {x, y, z, yaw, pitch, fov, radius_m, why}} document in DOCUMENT metres / UE degrees,
which is exactly what 05_screenshot.py's free camera takes.
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
from streetscape.terrain import Heightfield  # noqa: E402


def load_splines(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, "site_x*_y*.json"))):
        doc = json.load(open(f))
        for s in doc["splines"]:
            pts = np.asarray([[p["x"], p["y"]] for p in s["points"]], dtype=float)
            if len(pts) < 2:
                continue
            out.append({"id": s["id"], "file": os.path.basename(f), "pts": pts,
                        "road": (s.get("profile_ids") or {}).get("road"),
                        "tags": s.get("tags") or {}, "layer": s["id"].split(":")[0]})
    return out


def load_building_centres(d):
    xs, ys, hs = [], [], []
    for f in sorted(glob.glob(os.path.join(d, "buildings_x*_y*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                b = json.loads(line)
                for r in b.get("rings") or []:
                    if r.get("hole"):
                        continue
                    p = np.asarray(r["pts"], dtype=float)
                    xs.append(p[:, 0].mean())
                    ys.append(p[:, 1].mean())
                    hs.append(float(b.get("base_z") or 0.0) + float(b.get("h") or 0.0))
                    break
    return np.asarray(xs), np.asarray(ys), np.asarray(hs)


def stations(pts, step=10.0):
    """Resample a polyline every `step` m (straight segments: this is for choosing a viewpoint, not geometry)."""
    seg = np.hypot(*(pts[1:] - pts[:-1]).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] < step:
        return pts[:1], np.zeros(1)
    q = np.arange(0.0, s[-1], step)
    x = np.interp(q, s, pts[:, 0])
    y = np.interp(q, s, pts[:, 1])
    return np.stack([x, y], axis=1), q


def look(hf, ex, ey, ez, tx, ty, tz, fov, radius, why, extra=None):
    dx, dy, dz = tx - ex, ty - ey, tz - ez
    yaw = math.degrees(math.atan2(-dy, dx))          # UE: +Y is south, so a north-going look is negative yaw
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    out = {"x": round(ex, 2), "y": round(ey, 2), "z": round(ez, 2),
           "yaw": round(yaw, 2), "pitch": round(pitch, 2), "fov": fov,
           "radius_m": radius, "target": [round(tx, 2), round(ty, 2), round(tz, 2)], "why": why}
    if extra:
        out.update(extra)
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--streetscape", required=True)
    ap.add_argument("--massing", required=True)
    ap.add_argument("--landscape", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv[1:])

    hf = Heightfield.from_landscape_dir(a.landscape)
    splines = load_splines(a.streetscape)
    bx, by, bh = load_building_centres(a.massing)
    sys.stderr.write("splines %d, building rings %d\n" % (len(splines), len(bx)))

    sites = {}

    # ---- 1. the densest built street: a marked carriageway with the most footprints within 40 m
    MARKED = {"road_primary", "road_secondary", "road_tertiary", "road_residential", "road_unclassified",
              "road_trunk", "road_living_street"}
    best = None
    cell = 64.0
    keys = {}
    for i in range(len(bx)):
        keys.setdefault((int(bx[i] // cell), int(by[i] // cell)), []).append(i)
    for sp in splines:
        if sp["layer"] != "roads" or sp["road"] not in MARKED:
            continue
        st, _q = stations(sp["pts"], 15.0)
        for k in range(len(st)):
            x, y = st[k]
            near = 0
            hsum = 0.0
            cx, cy = int(x // cell), int(y // cell)
            for ix in (cx - 1, cx, cx + 1):
                for iy in (cy - 1, cy, cy + 1):
                    for j in keys.get((ix, iy), ()):
                        d = math.hypot(bx[j] - x, by[j] - y)
                        if d <= 40.0:
                            near += 1
                            hsum += bh[j]
            if near and (best is None or near > best[0]):
                best = (near, sp, k, st, hsum / near)
    if best:
        near, sp, k, st, meanh = best
        x, y = st[k]
        nx, ny = st[min(k + 1, len(st) - 1)]
        if (nx, ny) == (x, y):
            nx, ny = st[max(k - 1, 0)]
            nx, ny = 2 * x - nx, 2 * y - ny
        z = float(hf.sample(np.asarray([x]), np.asarray([y]))[0])
        d = math.hypot(nx - x, ny - y) or 1.0
        ux, uy = (nx - x) / d, (ny - y) / d
        # Stand ON the carriageway. The first version stood 2.5 m off the centreline "on the pavement" and 8 m
        # back, and the ground there was a metre above the road: the capture was a wall of green with the road
        # nowhere in it. The road is built on the SMOOTHED terrain, and at the centreline the raw terrain is
        # within a few centimetres of it (measured: 540 of 881 probe stations within 2 cm), so terrain + 1.6 m at
        # a station IS eye height over the carriageway.
        ex, ey = x - 14.0 * ux, y - 14.0 * uy
        ez = float(hf.sample(np.asarray([ex]), np.asarray([ey]))[0])
        if not np.isfinite(ez):
            ez = z
        sites["street"] = look(hf, ex, ey, ez + 1.60, x + 26.0 * ux, y + 26.0 * uy, z + 0.30, 75, 700,
                               "eye height on %s (%s), %d massing footprints within 40 m, mean roof %.1f m ODN"
                               % (sp["id"], sp["road"], near, meanh),
                               {"spline": sp["id"], "file": sp["file"], "buildings_within_40m": near})

    # ---- 2. the seafront: ground above 3 m with sea within 150 m to one side
    best = None
    for sp in splines:
        if sp["layer"] != "roads":
            continue
        st, _q = stations(sp["pts"], 20.0)
        if len(st) < 4:
            continue
        z = hf.sample(st[:, 0], st[:, 1])
        for k in range(1, len(st) - 1):
            if not np.isfinite(z[k]) or z[k] < 3.0:
                continue
            tx, ty = st[k + 1] - st[k - 1]
            d = math.hypot(tx, ty) or 1.0
            nx_, ny_ = -ty / d, tx / d
            probes = np.arange(20.0, 160.0, 20.0)
            for sgn in (1.0, -1.0):
                px = st[k, 0] + sgn * nx_ * probes
                py = st[k, 1] + sgn * ny_ * probes
                pz = hf.sample(px, py)
                sea = np.nansum(np.where(np.isfinite(pz), pz < 0.0, 0.0))
                if sea >= 4 and (best is None or (sea, z[k]) > (best[0], best[1])):
                    best = (sea, float(z[k]), st, k, sgn, nx_, ny_, sp)
    if best:
        sea, zk, st, k, sgn, nx_, ny_, sp = best
        x, y = st[k]
        tx, ty = st[k + 1] - st[k - 1]
        d = math.hypot(tx, ty) or 1.0
        ux, uy = tx / d, ty / d
        ex, ey = x - 40.0 * ux, y - 40.0 * uy          # on the promenade line, looking along it (see "street")
        ez = float(hf.sample(np.asarray([ex]), np.asarray([ey]))[0])
        if not np.isfinite(ez):
            ez = zk
        sites["seafront"] = look(hf, ex, ey, ez + 1.70, x + 110.0 * ux, y + 110.0 * uy, zk + 0.30, 80, 900,
                                 "promenade on %s at %.1f m ODN with %d of 7 lateral probes below 0 m ODN (sea)"
                                 % (sp["id"], zk, int(sea)),
                                 {"spline": sp["id"], "file": sp["file"]})

    # ---- 3. a rail cutting: ground higher on BOTH sides at 25 m
    best = None
    for sp in splines:
        if sp["layer"] != "rail":
            continue
        st, _q = stations(sp["pts"], 20.0)
        if len(st) < 4:
            continue
        z = hf.sample(st[:, 0], st[:, 1])
        for k in range(1, len(st) - 1):
            if not np.isfinite(z[k]):
                continue
            tx, ty = st[k + 1] - st[k - 1]
            d = math.hypot(tx, ty) or 1.0
            nx_, ny_ = -ty / d, tx / d
            zl = hf.sample(np.asarray([st[k, 0] + 25 * nx_]), np.asarray([st[k, 1] + 25 * ny_]))[0]
            zr = hf.sample(np.asarray([st[k, 0] - 25 * nx_]), np.asarray([st[k, 1] - 25 * ny_]))[0]
            if not (np.isfinite(zl) and np.isfinite(zr)):
                continue
            depth = min(zl - z[k], zr - z[k])
            if depth > 0 and (best is None or depth > best[0]):
                best = (float(depth), st, k, sp, float(zl), float(zr), float(z[k]))
    if best:
        depth, st, k, sp, zl, zr, zk = best
        x, y = st[k]
        tx, ty = st[k + 1] - st[k - 1]
        d = math.hypot(tx, ty) or 1.0
        ux, uy = tx / d, ty / d
        ex, ey = x - 45.0 * ux, y - 45.0 * uy
        ez = float(hf.sample(np.asarray([ex]), np.asarray([ey]))[0])
        if not np.isfinite(ez):
            ez = zk
        sites["cutting"] = look(hf, ex, ey, ez + 2.20, x + 150.0 * ux, y + 150.0 * uy, zk + 0.40, 70, 900,
                                "rail %s in a cutting %.1f m deep (ground +%.1f m left / +%.1f m right at 25 m)"
                                % (sp["id"], depth, zl - zk, zr - zk),
                                {"spline": sp["id"], "file": sp["file"], "cutting_depth_m": round(depth, 2)})

    # ---- 4. the isle from above, looking along the clip line so the cut is in frame
    man = json.load(open(os.path.join(a.landscape, "landscape_manifest.json")))
    clip = man.get("clip") or {}
    e0, n0 = man["origin"]["E"], man["origin"]["N"]
    line = clip.get("line") or [[e0, n0], [e0 + 1, n0]]
    ax, ay = line[0][0] - e0, line[0][1] - n0
    bx2, by2 = line[1][0] - e0, line[1][1] - n0
    allpts = np.concatenate([sp["pts"] for sp in splines])
    cx, cy = float(allpts[:, 0].mean()), float(allpts[:, 1].mean())
    # stand south-west of the clip line's midpoint, high, looking north-east across the isle: the cut is the near
    # edge of the land and the whole road network is beyond it
    mx, my = (ax + bx2) / 2.0, (ay + by2) / 2.0
    vx, vy = cx - mx, cy - my
    vn = math.hypot(vx, vy) or 1.0
    vx, vy = vx / vn, vy / vn
    ex, ey = mx - 5200.0 * vx, my - 5200.0 * vy
    sites["isle"] = look(hf, ex, ey, 3400.0, cx, cy, 20.0, 60, 30000,
                         "5.2 km south-west of the Minnis Bay - Pegwell Bay clip line at 3.4 km, looking "
                         "north-east over the network centroid (%.0f, %.0f): the cut is the near shoreline"
                         % (cx, cy),
                         {"clip_line_local_m": [[round(ax, 1), round(ay, 1)], [round(bx2, 1), round(by2, 1)]]})

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="\n") as fh:
        json.dump(sites, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps(sites, indent=1, sort_keys=True))
    print("written: %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
