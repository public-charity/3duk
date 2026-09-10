"""Connected rail alignments across short inter-bridge links and tile-boundary stubs.

Uses the shared profile schema. Ambiguous connections, unsupported neighbouring
decks and incompatible overlapping changes fail; the caller also checks DSM support.
"""
from collections import defaultdict
import math
from types import SimpleNamespace

import numpy as np


def chain_samples(chain, built):
    stations, heights, banks, offsets = [], [], [], []
    offset, rate = 0.0, math.inf
    for sid, reverse in chain:
        sp = built(sid)
        s, z, bank = sp.s, sp.z_ref, sp.bank_deg
        if reverse:
            s, z, bank = sp.length-s[::-1], z[::-1], -bank[::-1]
        offsets.append(offset)
        first = 1 if stations else 0
        stations.extend(offset+s[first:])
        heights.extend(z[first:])
        banks.extend(bank[first:])
        offset += sp.length
        rate = min(rate, sp.sampling.bank_rate_max_deg_per_m)
    if not stations or offset <= 0:
        raise ValueError("empty approach chain")
    return SimpleNamespace(id=" + ".join(sid for sid, _ in chain), s=np.asarray(stations),
                           z_ref=np.asarray(heights), bank_deg=np.asarray(banks), length=offset,
                           sampling=SimpleNamespace(bank_rate_max_deg_per_m=rate)), offsets


def split_profile(chain, built, offsets, q, z, bank, changed_length):
    """Preserve each original arc and flip signed bank on reversed parts."""
    updates = {}
    for (sid, reverse), offset in zip(chain, offsets):
        sp = built(sid)
        stop = min(sp.length, changed_length-offset)
        if stop <= 1e-8:
            break
        local = np.unique(np.r_[0, stop, q[(q > offset) & (q < offset+stop)]-offset])
        zz, bb = np.interp(local+offset, q, z), np.interp(local+offset, q, bank)
        if reverse:
            local, zz, bb = sp.length-local[::-1], zz[::-1], -bb[::-1]
        updates[sid] = (local, zz, bb)
    return updates


def merge_profile(sp, updates):
    q = np.unique(np.r_[sp.s, *[u[0] for u in updates]])
    z, bank = np.interp(q, sp.s, sp.z_ref), np.interp(q, sp.s, sp.bank_deg)
    used = np.zeros(len(q), dtype=bool)
    for s, zz, bb in updates:
        active = (q >= s[0]-1e-8) & (q <= s[-1]+1e-8)
        both = used & active
        new_z, new_bank = np.interp(q, s, zz), np.interp(q, s, bb)
        if both.any() and (np.max(np.abs(z[both]-new_z[both])) > 1e-5 or
                           np.max(np.abs(bank[both]-new_bank[both])) > 1e-5):
            raise ValueError(sp.id + ": incompatible overlapping approach changes")
        z[active], bank[active] = new_z[active], new_bank[active]
        used |= active
    return q, z, bank


def network_profiles(selected, groups, fits, definitions, built, approach_fn, hermite_fn, snap=.35):
    ends, bins = {}, defaultdict(list)
    for sid, (_, row) in definitions.items():
        if (row.get("source") or {}).get("layer") != "rail":
            continue
        for end, point in (("start", row["points"][0]), ("end", row["points"][-1])):
            xy = (point["x"], point["y"])
            ends[(sid, end)] = xy
            bins[(math.floor(xy[0]/snap), math.floor(xy[1]/snap))].append((sid, end))

    def neighbours(key):
        xy = ends[key]
        bx, by = math.floor(xy[0]/snap), math.floor(xy[1]/snap)
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in bins[(bx+dx, by+dy)]:
                    if other[0] != key[0]:
                        distance = math.dist(xy, ends[other])
                        if distance <= snap:
                            near.append((distance, other))
        nearest = min((d for d, _ in near), default=math.inf)
        return [other for distance, other in near if distance <= nearest+1e-5]

    sid_group = {sid: gid for gid, g in groups.items() for sid in g["splines"]}
    selected = set(selected)
    walks = {}

    def walk(key):
        if key in walks:
            return walks[key]
        chain, length, current, seen = [], 0.0, key, {key[0]}
        target = None
        while length < 130:
            near = neighbours(current)
            if len(near) != 1:
                # A supported anchor can still lie before this branch/dead end.
                break
            sid, end = near[0]
            if sid in seen:
                raise ValueError("cyclic approach chain at " + sid)
            flags = definitions[sid][1].get("flags") or {}
            if flags.get("bridge") or flags.get("tunnel"):
                target = (sid, end)
                break
            chain.append((sid, end == "end"))
            length += built(sid).length
            seen.add(sid)
            current = (sid, "end" if end == "start" else "start")
        if not chain:
            raise ValueError(key[0] + ": no unambiguous connected ground approach")
        walks[key] = (chain, length, target)
        return walks[key]

    # Include the other deck where the short connector cannot contain a separate
    # approach transition. Only passing first-return fits may be added.
    while True:
        added = set()
        for gid in sorted(selected):
            if fits[gid]["status"] != "deck_candidate_requires_approaches" or not gid.startswith("rail:"):
                raise ValueError("network requires passing rail deck fit: " + gid)
            for end in groups[gid]["ends"]:
                _, length, target = walk((end["spline_id"], end["end"]))
                if target and length < 50:
                    next_group = sid_group[target[0]]
                    if fits[next_group]["status"] != "deck_candidate_requires_approaches":
                        raise ValueError(gid + ": short link reaches unsupported deck " + next_group)
                    added.add(next_group)
        if added <= selected:
            break
        selected |= added

    constraints, decks = {}, {}
    for gid in sorted(selected):
        by_id = {p["spline_id"]: p for p in fits[gid]["profile_by_spline"]}
        for sid, p in by_id.items():
            decks[sid] = (np.asarray(p["s_m"]), np.asarray(p["z_m"]), np.zeros(2), gid)
        for end in groups[gid]["ends"]:
            p = by_id[end["spline_id"]]
            is_start = end["end"] == "start"
            slope = (p["z_m"][1]-p["z_m"][0])/p["s_m"][1]
            constraints[(end["spline_id"], end["end"])] = (p["z_m"][0 if is_start else 1],
                                                          slope*(-1 if is_start else 1), gid)
    updates, owners, records, completed = defaultdict(list), defaultdict(set), [], set()
    for key, (z0, g0, gid) in sorted(constraints.items()):
        if key in completed:
            continue
        chain, length, target = walk(key)
        sp, offsets = chain_samples(chain, built)
        if target in constraints:
            z1, end_grade, next_gid = constraints[target]
            q = np.unique(np.r_[sp.s, np.arange(0, sp.length, 1.0), sp.length])
            z = hermite_fn(q, sp.length, z0, z1, g0, -end_grade)
            bank = np.zeros(len(q))
            grade = float(np.max(np.abs(np.diff(z)/np.diff(q))))
            if grade > .05:
                raise ValueError(sp.id + ": connected bridge approach exceeds 5% grade")
            changed = sp.length
            info = {"method": "between_decks", "groups": [gid, next_gid], "chain": chain,
                    "blend_length_m": changed, "blend_max_grade_pct": 100*grade}
            completed.add(target)
        else:
            q, z, bank, info = approach_fn(sp, "start", z0, g0)
            changed = info["blend_length_m"]
            info.update(method="supported_ground_anchor", groups=[gid], chain=chain)
        for sid, update in split_profile(chain, built, offsets, q, z, bank, changed).items():
            updates[sid].append(update)
            owners[sid].update(info["groups"])
        records.append(info)
        completed.add(key)
    profiles = {sid: (*merge_profile(built(sid), rows), sorted(owners[sid])) for sid, rows in updates.items()}
    return decks, profiles, records, sorted(selected)
