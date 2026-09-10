"""Small, exact LOD-0 terrain cuts under a supplied mesh; never edits the survey.

Intersect mesh triangles with the landscape's NW-SE triangles. Height differences
are affine on each intersection polygon, so its vertices are sufficient contact
constraints. Minimize the sum of lowered grid posts, with a hard cut budget. This
avoids sinking every post in a triangle's bounding box to its lowest mesh vertex.
The caller must reject inappropriate/occluded surfaces and check adjacent edges.
"""
import copy
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix


def cross2(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


def clip_triangle(polygon, triangle):
    """Convex XY polygon clipped to a triangle, preserving intersection vertices."""
    polygon = np.asarray(polygon, dtype=float)
    triangle = np.asarray(triangle, dtype=float)
    sign = np.sign(cross2(triangle[1]-triangle[0], triangle[2]-triangle[0]))
    if not sign:
        return np.empty((0, 2))
    for a, b in zip(triangle, np.roll(triangle, -1, axis=0)):
        if not len(polygon):
            break
        distances = sign*cross2(b-a, polygon-a)
        result = []
        for i, p in enumerate(polygon):
            q, dp, dq = polygon[i-1], distances[i], distances[i-1]
            if (dp >= 0) != (dq >= 0):
                result.append(q+(p-q)*dq/(dq-dp))
            if dp >= 0:
                result.append(p)
        polygon = np.asarray(result).reshape(-1, 2)
    return polygon


def barycentric(triangle, points):
    a, b, c = np.asarray(triangle)
    det = cross2(b-a, c-a)
    if abs(det) < 1e-12:
        raise ValueError("degenerate XY triangle")
    v = cross2(points-a, c-a)/det
    w = cross2(b-a, points-a)/det
    return np.column_stack((1-v-w, v, w))


def contacts(triangles, terrain):
    """Yield (three integer XY post keys, barycentric weights, mesh Z).

    Keys are shared between adjacent tiles. Only an unshifted, integral-grid field
    is supported; registration mismatches must fail instead of silently moving a cut.
    """
    if terrain.sampling != "landscape_triangulated" or terrain.shift_xy != (0., 0.) or terrain.xy0 != (0., 0.):
        raise ValueError("contact repair requires unshifted landscape triangles")
    px = terrain.px_m
    for tri in triangles:
        if not np.isfinite(tri).all():
            raise ValueError("nonfinite contact mesh")
        if abs(cross2(tri[1, :2]-tri[0, :2], tri[2, :2]-tri[0, :2])) < 1e-10:
            continue
        lo = np.floor(tri[:, :2].min(axis=0)/px).astype(int)
        hi = np.floor(tri[:, :2].max(axis=0)/px).astype(int)
        if np.prod(hi-lo+1) > 10000:
            raise ValueError("contact triangle exceeds bounded raster budget")
        for x in range(lo[0], hi[0]+1):
            for y in range(lo[1], hi[1]+1):
                # NW(a)-SE(d) diagonal, in local east/north coordinates.
                for keys in (((x,y+1),(x,y),(x+1,y)), ((x,y+1),(x+1,y),(x+1,y+1))):
                    xy = np.asarray(keys, dtype=float)*px
                    polygon = clip_triangle(tri[:, :2], xy)
                    if len(polygon) < 3:
                        continue
                    area = abs(np.sum(cross2(polygon-polygon[0], np.roll(polygon,-1,axis=0)-polygon[0])))*.5
                    if area < 1e-10:
                        continue
                    weights = barycentric(xy, polygon)
                    # Numerical clipping noise must never invert a monotone cut.
                    if weights.min() < -1e-8:
                        raise ValueError("invalid terrain contact weights")
                    weights = np.maximum(weights, 0)
                    weights /= weights.sum(axis=1)[:, None]
                    mesh_z = barycentric(tri[:, :2], polygon)@tri[:, 2]
                    yield keys, weights, mesh_z


def exact_penetration(triangles, terrain):
    worst = -np.inf
    count = 0
    for keys, weights, z in contacts(triangles, terrain):
        xy = np.asarray(keys)*terrain.px_m
        ground = terrain.sample(xy[:, 0], xy[:, 1])
        if not np.isfinite(ground).all():
            raise ValueError("missing terrain under contact triangle")
        worst = max(worst, float(np.max(weights@ground-z)))
        count += len(z)
    if not count:
        raise ValueError("empty terrain contact measurement")
    return {"contact_vertices": count, "max_penetration_m": max(0., worst),
            "minimum_clearance_m": -worst}


def point_weights(point, px):
    """Integer post keys/weights for local XY on the NW-SE landscape split."""
    x, y = np.asarray(point)/px
    i, j = int(np.floor(x)), int(np.floor(y))
    u, v = x-i, y-j
    if u+v <= 1:
        return ((i,j+1),(i,j),(i+1,j)), np.array([v,1-u-v,u])
    return ((i,j+1),(i+1,j),(i+1,j+1)), np.array([1-u,1-v,u+v-1])


def minimum_cut(triangles, terrain, clearance_m=.01, max_cut_m=.5, protected_points=None):
    if not (np.isfinite(clearance_m) and np.isfinite(max_cut_m) and 0 < clearance_m < max_cut_m):
        raise ValueError("invalid contact cut limits")
    enc = terrain.manifest.get("heightmap", {}).get("z_encoding", {})
    unit = float(enc.get("per_unit", 128.))
    offset = float(enc.get("offset", 32768.))
    if not (unit > 0 and np.isfinite(unit) and np.isfinite(offset)):
        raise ValueError("invalid height encoding")
    constraints, post_ids, original = [], {}, {}
    count = 0
    for keys, weights, z in contacts(triangles, terrain):
        xy = np.asarray(keys)*terrain.px_m
        ground = terrain.sample(xy[:, 0], xy[:, 1])
        if not np.isfinite(ground).all():
            raise ValueError("missing terrain under contact triangle")
        rhs = weights@ground-z+clearance_m
        count += len(rhs)
        for w, value in zip(weights, rhs):
            if value <= 1e-9:
                continue
            row = {}
            for key, coefficient, old in zip(keys, w, ground):
                if coefficient <= 1e-12:
                    continue
                if key not in post_ids:
                    post_ids[key] = len(post_ids)
                    original[key] = float(old)
                row[post_ids[key]] = float(coefficient)
            constraints.append((row, float(value)))
    if not count:
        raise ValueError("empty terrain contact mesh")
    if not constraints:
        return {}, {"contact_vertices": count, "constraints": 0, "changed_posts": 0, "max_cut_m": 0.}
    # Each protected XYZ is an outer-face base. Retain contact where it exists,
    # and allow at most 5 mm extra daylight where there is already a gap.
    lower = [value for _, value in constraints]
    upper = [np.inf]*len(constraints)
    protected_count = 0
    if protected_points is not None:
        for point in protected_points:
            keys, weights = point_weights(point[:2], terrain.px_m)
            row = {post_ids[k]:float(w) for k,w in zip(keys,weights) if k in post_ids and w>1e-12}
            if not row:
                continue
            ground = terrain.sample(point[0],point[1])
            if not np.isfinite(ground):
                raise ValueError("missing terrain under protected edge")
            constraints.append((row,0.))
            lower.append(-np.inf)
            upper.append(max(0.,float(ground-point[2]))+.005)
            protected_count += 1
    row_indices, col_indices, values = [], [], []
    for i, (row, _) in enumerate(constraints):
        for j, value in row.items():
            row_indices.append(i)
            col_indices.append(j)
            values.append(value/unit)
    matrix = coo_matrix((values, (row_indices, col_indices)), shape=(len(constraints), len(post_ids))).tocsr()
    # Optimize integer encoding steps directly. Rounding a continuous optimum can
    # break an adjacent edge's upper cut limit even while contact remains clear.
    result = milp(np.ones(len(post_ids)), integrality=np.ones(len(post_ids)),
                  bounds=Bounds(0,np.floor(max_cut_m*unit)),
                  constraints=LinearConstraint(matrix,lower,upper), options={"time_limit":20.})
    if not result.success:
        raise ValueError("contact cut cannot meet its budget: "+result.message)
    changes = {}
    for key, j in post_ids.items():
        if result.x[j] <= 1e-9:
            continue
        if abs(original[key]*unit+offset-round(original[key]*unit+offset))>1e-5:
            raise ValueError("source terrain is not quantized to its declared encoding")
        encoded = round(original[key]*unit+offset)-round(result.x[j])
        if not 0 <= encoded <= 65535:
            raise ValueError("contact height exceeds encoding range")
        target = float((encoded-offset)/unit)
        if original[key]-target > max_cut_m+1e-9:
            raise ValueError("quantized contact cut exceeds budget")
        changes[key] = target
    return changes, {"contact_vertices": count, "constraints": len(constraints),
                     "protected_points":protected_count,"changed_posts": len(changes),
                     "max_cut_m": max(original[k]-z for k, z in changes.items()),
                     "summed_post_cut_m": sum(original[k]-z for k, z in changes.items())}


def apply_posts(terrain, changes):
    """Copy only touched tiles, updating EVERY copy of each seam post."""
    result = copy.copy(terrain)
    result.tiles = dict(terrain.tiles)
    q = terrain.res-1
    written = set()
    for key, tile in terrain.tiles.items():
        i, j = key
        selected = [(x-i*q, (j+1)*q-y, z, (x,y)) for (x,y),z in changes.items()
                    if i*q <= x <= (i+1)*q and j*q <= y <= (j+1)*q]
        if not selected:
            continue
        updated = tile.copy()
        for col, row, z, post in selected:
            if not np.isfinite(tile[row, col]) or z > tile[row, col]+1e-8:
                raise ValueError("contact cut has missing/inconsistent seam terrain")
            updated[row, col] = z
            written.add(post)
        result.tiles[key] = updated
    if written != set(changes):
        raise ValueError("contact post outside terrain coverage")
    return result
