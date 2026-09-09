"""Quality-check a rendered snapshot directory, independently of the renderer's own guards.

Every image must: exist, be >= 50 KB, decode as a PNG, be fully opaque, not be a single flat
colour, and not be more than 85 % one colour (which is what an all-sky or all-grass frame -- a
camera pointing at nothing, or a region that never streamed -- actually looks like).

Nothing here calls Unreal or trusts the renderer's report: the decoder is stdlib zlib + numpy.

usage:  python qc_renders.py <snapshot dir> [--json <out>]
"""
import json
import os
import struct
import sys
import zlib

import numpy as np

MIN_BYTES = 51200
MIN_VARIANCE = 25.0          # below this the frame is (near) a single flat colour
MIN_DISTINCT = 200           # distinct exact RGB triples
MAX_DOMINANT = 0.85          # > 85 % one colour fails
WARN_DOMINANT = 0.70


def decode(path):
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: %s" % path)
    i, idat, w, h, bd, ct = 8, [], 0, 0, 0, 0
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        data = d[i + 8:i + 8 + ln]
        i += 12 + ln
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT":
            idat.append(data)
        elif typ == b"IEND":
            break
    if bd != 8:
        raise ValueError("bit depth %d unsupported" % bd)
    nch = {0: 1, 2: 3, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(b"".join(idat))
    stride = w * nch
    if len(raw) != h * (stride + 1):
        raise ValueError("IDAT is %d bytes, expected %d" % (len(raw), h * (stride + 1)))
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    pos = 0
    for y in range(h):
        f = raw[pos]
        pos += 1
        line = np.frombuffer(raw[pos:pos + stride], dtype=np.uint8).copy()
        pos += stride
        if f == 0:
            pass
        elif f == 1:                                    # Sub: cumulative per channel
            for c in range(nch):
                line[c::nch] = np.cumsum(line[c::nch], dtype=np.uint32).astype(np.uint8)
        elif f == 2:                                    # Up
            line = (line.astype(np.uint16) + prev).astype(np.uint8)
        elif f == 3:                                    # Average
            b = bytearray(line.tobytes())
            for x in range(stride):
                a = b[x - nch] if x >= nch else 0
                b[x] = (b[x] + ((a + int(prev[x])) >> 1)) & 255
            line = np.frombuffer(bytes(b), dtype=np.uint8).copy()
        elif f == 4:                                    # Paeth
            b = bytearray(line.tobytes())
            pv = prev.tolist()
            for x in range(stride):
                a = b[x - nch] if x >= nch else 0
                bb = pv[x]
                c = pv[x - nch] if x >= nch else 0
                p = a + bb - c
                pa, pb, pc = abs(p - a), abs(p - bb), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (bb if pb <= pc else c)
                b[x] = (b[x] + pr) & 255
            line = np.frombuffer(bytes(b), dtype=np.uint8).copy()
        else:
            raise ValueError("filter type %d" % f)
        out[y] = line
        prev = line
    return out.reshape(h, w, nch), w, h, nch


def dominant_fraction(rgb, shift):
    q = (rgb >> shift).astype(np.uint32)
    lv = 256 >> shift
    key = q[:, :, 0] * lv * lv + q[:, :, 1] * lv + q[:, :, 2]
    counts = np.bincount(key.ravel())
    n = key.size
    top = np.argsort(counts)[::-1][:3]
    return float(counts.max()) / n, [(int(t), float(counts[t]) / n) for t in top if counts[t] > 0]


def check(path, rel):
    r = {"png": rel, "path": path}
    if not os.path.exists(path):
        r.update(ok=False, fail=["missing"])
        return r
    n = os.path.getsize(path)
    r["bytes"] = n
    fails, warns = [], []
    if n < MIN_BYTES:
        fails.append("bytes %d < %d" % (n, MIN_BYTES))
    try:
        img, w, h, nch = decode(path)
    except Exception as e:                              # noqa: BLE001 - reporting, not handling
        r.update(ok=False, fail=fails + ["decode: %s" % e])
        return r
    r.update(width=w, height=h, channels=nch)
    rgb = img[:, :, :3]
    f = rgb.astype(np.float64)
    lum = 0.2126 * f[:, :, 0] + 0.7152 * f[:, :, 1] + 0.0722 * f[:, :, 2]
    r["mean_luminance"] = round(float(lum.mean()), 2)
    r["variance"] = round(float(lum.var()), 2)
    r["thirds_variance"] = [round(float(lum[k * h // 3:(k + 1) * h // 3].var()), 1) for k in range(3)]
    flat = rgb.reshape(-1, 3)
    r["distinct_rgb"] = int(np.unique(flat, axis=0).shape[0])
    exact_dom = float(np.bincount(
        flat[:, 0].astype(np.uint32) * 65536 + flat[:, 1].astype(np.uint32) * 256
        + flat[:, 2].astype(np.uint32)).max()) / flat.shape[0]
    r["dominant_exact"] = round(exact_dom, 4)
    d16, top16 = dominant_fraction(rgb, 4)              # 16 levels/chan, bucket width 16
    d32, _ = dominant_fraction(rgb, 5)                  # 8 levels/chan, bucket width 32
    r["dominant_q16"] = round(d16, 4)
    r["dominant_q32"] = round(d32, 4)
    r["top3_q16"] = round(sum(t[1] for t in top16), 4)
    # detail: fraction of pixels whose horizontal neighbour differs by more than 8 in luminance
    r["edge_fraction"] = round(float((np.abs(np.diff(lum, axis=1)) > 8).mean()), 4)
    r["alpha_min"] = int(img[:, :, 3].min()) if nch == 4 else 255

    if r["variance"] < MIN_VARIANCE:
        fails.append("luminance variance %.2f < %.1f (flat frame)" % (r["variance"], MIN_VARIANCE))
    if r["distinct_rgb"] < MIN_DISTINCT:
        fails.append("only %d distinct RGB triples" % r["distinct_rgb"])
    if d16 > MAX_DOMINANT:
        fails.append("%.1f%% of pixels are one colour (q16) > %.0f%%" % (d16 * 100, MAX_DOMINANT * 100))
    if exact_dom > MAX_DOMINANT:
        fails.append("%.1f%% of pixels are one exact colour > %.0f%%" % (exact_dom * 100, MAX_DOMINANT * 100))
    if r["alpha_min"] != 255:
        fails.append("min alpha %d != 255 (PNG reads as transparent)" % r["alpha_min"])
    if not fails and d16 > WARN_DOMINANT:
        warns.append("%.1f%% one colour (q16)" % (d16 * 100))
    if not fails and r["edge_fraction"] < 0.02:
        warns.append("edge fraction %.3f - very little detail" % r["edge_fraction"])
    if not fails and min(r["thirds_variance"]) < 5.0:
        warns.append("a horizontal third of the frame is flat (variances %s)" % r["thirds_variance"])
    r["ok"] = not fails
    r["fail"] = fails
    r["warn"] = warns
    return r


def main():
    root = sys.argv[1].replace("\\", "/").rstrip("/")
    outjson = None
    if "--json" in sys.argv:
        outjson = sys.argv[sys.argv.index("--json") + 1]
    man = os.path.join(root, "manifest.json")
    rels = []
    if os.path.exists(man):
        m = json.load(open(man))
        rels = [i["png"] for i in m["images"]]
        print("manifest: %s images at commit %s (partial=%s)"
              % (len(rels), m["commit"], m["counts"]["partial"]))
    found = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if f.endswith(".png"):
                found.append(os.path.relpath(os.path.join(dp, f), root).replace("\\", "/"))
    for f in sorted(found):
        if f not in rels:
            rels.append(f)
            print("NOTE: %s is on disk but not in the manifest" % f)
    for f in rels:
        if not os.path.exists(os.path.join(root, f)):
            print("NOTE: %s is in the manifest but not on disk" % f)

    results = [check(os.path.join(root, f), f) for f in rels]
    print("%-64s %-5s %9s %8s %7s %7s %7s %6s" %
          ("image", "verd", "bytes", "var", "dom16", "domEx", "edge", "lum"))
    for r in results:
        print("%-64s %-5s %9s %8s %7s %7s %7s %6s" % (
            r["png"], "PASS" if r.get("ok") else "FAIL", r.get("bytes", "-"),
            r.get("variance", "-"), r.get("dominant_q16", "-"), r.get("dominant_exact", "-"),
            r.get("edge_fraction", "-"), r.get("mean_luminance", "-")))
        for x in r.get("fail", []):
            print("      FAIL: %s" % x)
        for x in r.get("warn", []):
            print("      warn: %s" % x)
    bad = [r for r in results if not r.get("ok")]
    warned = [r for r in results if r.get("ok") and r.get("warn")]
    print("\n%d images, %d failed, %d passed with warnings" % (len(results), len(bad), len(warned)))
    if outjson:
        json.dump(results, open(outjson, "w"), indent=1)
        print("wrote %s" % outjson)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
