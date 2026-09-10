"""World-space contact geometry for Renderer B's existing support profiles.

These are cross-section coordinates for the shared sweep, not another renderer.
Batter search is bounded to 64 m horizontal run at 25 cm probes, then 28 bisections.
Unsupported/no-data toes fail instead of emitting an apparently complete floating face.
"""
import numpy as np


def world_section(frames, side, run, dz):
    """World horizontal-outward run and world-Z offset -> banked section (o,h)."""
    c = frames.b[:,2]
    s = frames.n[:,2]
    return c*run+side*s*dz, -side*s*run+c*dz


def batter_toes(start, outward_xy, terrain, mask, ratio, extra):
    run = np.zeros(len(start))
    bottom = np.zeros(len(start))
    active = np.flatnonzero(mask)
    if not len(active):
        return run,bottom
    p = start[active]
    u = outward_xy[active]
    lo = np.zeros(len(active))
    hi = np.zeros(len(active))
    pending = np.ones(len(active),dtype=bool)
    for step in range(1,257):
        ids = np.flatnonzero(pending)
        if not len(ids):
            break
        distance = step*.25
        xy = p[ids,:2]+distance*u[ids]
        ground = terrain.sample(xy[:,0],xy[:,1])
        if not np.isfinite(ground).all():
            raise ValueError("batter toe crosses missing terrain")
        hit = p[ids,2]-distance/ratio <= ground
        hi[ids[hit]] = distance
        pending[ids[hit]] = False
        lo[ids[~hit]] = distance
    if pending.any():
        raise ValueError("batter toe does not meet terrain within 64 m; needs another support model")
    for _ in range(28):
        mid = (lo+hi)*.5
        xy = p[:,:2]+mid[:,None]*u
        ground = terrain.sample(xy[:,0],xy[:,1])
        if not np.isfinite(ground).all():
            raise ValueError("batter toe has missing terrain in contact interval")
        above = p[:,2]-mid/ratio > ground
        lo = np.where(above,mid,lo)
        hi = np.where(above,hi,mid)
    xy = p[:,:2]+hi[:,None]*u
    ground = terrain.sample(xy[:,0],xy[:,1])
    run[active] = hi
    bottom[active] = ground-extra-p[:,2]
    return run,bottom
