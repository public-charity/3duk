"""Select supplied semantic surfaces for vertical terrain contact, at every slope.

Callers select road/pavement/skirt groups first. A road stays in coverage when
steep or inverted; orientation and folds are separate geometry gates. Vertical
faces cannot be height graphs and are counted explicitly, never called checked.
"""
import numpy as np


def projected_surface_mask(triangles):
    tri=np.asarray(triangles,dtype=float)
    if tri.ndim!=3 or tri.shape[1:]!=(3,3) or not np.isfinite(tri).all():
        raise ValueError('finite (N,3,3) semantic surface triangles required')
    normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    length=np.linalg.norm(normal,axis=1)
    keep=np.abs(normal[:,2])>=1e-10
    return keep,dict(supplied_triangles=len(tri),height_graph_triangles=int(keep.sum()),
        vertical_or_degenerate_xy_triangles=int((~keep).sum()),
        steep_height_graph_triangles=int((keep&(np.abs(normal[:,2])<=.5*length)).sum()),
        downward_height_graph_triangles=int((keep&(normal[:,2]<0)).sum()))
