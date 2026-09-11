"""numpy_parity_dump - write the numpy prototype's spline arrays for Streetscape.Spline.NumpyParity (UE_PLAN.md 2.14).

Runs with the PIPELINE python (not UE's):
    PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH C:/Users/Shadow/code/3duk-env/env/python.exe \
        projects/one/Tools/ue/numpy_parity_dump.py [--out projects/one/Saved/Tests/numpy_parity.json]
then
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_tests.ps1 -Filter Streetscape.Spline.NumpyParity \
        -ParityJson projects/one/Saved/Tests/numpy_parity.json

The C++ test builds the same fixtures (Tools/blender/tests/fixtures/*.json, flat terrain z = 10 with xy0 (0, -256);
'bank_cross' = straight_100 on the 0.1 cross-slope terrain) and reports, per array, how many values are bit-identical
and the max |diff| (asserted < 1e-9). Measured 2026-09-08: 8 arrays, every value bit-identical.
"""
import argparse
import json
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ONE = os.path.dirname(os.path.dirname(HERE))
TOOLS_BLENDER = os.path.join(PROJECT_ONE, "Tools", "blender")
sys.path.insert(0, TOOLS_BLENDER)
sys.path.insert(0, os.path.join(TOOLS_BLENDER, "tests"))

import synthetic as SY  # noqa: E402
from streetscape import io_json as IO  # noqa: E402
from streetscape import schema as S  # noqa: E402
from streetscape import spline as SP  # noqa: E402
from streetscape.terrain import Heightfield
from streetscape.edge import build_edge
from streetscape.build import build_all


def build(name, terrain=None):
    doc = SY.load_fixture(name)
    site = IO.site_from_dict(doc)
    t = terrain if terrain is not None else SY.terrain_for(doc)
    return SP.Spline(site.splines[0], site, t)


def arrays(sp):
    return {
        "s": [float(v) for v in sp.s],
        "width": [float(v) for v in sp.width],
        "z_ref": [float(v) for v in sp.z_ref],
        "bank": [float(v) for v in sp.bank_deg],
        "edge_left": [float(v) for v in sp.edge_offset(S.LEFT)],
    }


def support_meshes(kind):
    doc = SY.load_fixture("straight_100")
    definition = doc["splines"][0]
    definition["elevation_profile"] = [dict(s_m=0,z_m=11.5,bank_deg=12),dict(s_m=100,z_m=11.5,bank_deg=12)]
    definition["segments"] = [dict(id="support",s0_m=0,s1_m=None,side="both",
        edge=dict(embankment=dict(kind=kind,side="both",material="grass",threshold_m=.01)))]
    site = IO.site_from_dict(doc)
    field = Heightfield.from_function(lambda x,y:10-.2*y if kind=="batter" else 10+0*x,
                                      extent_m=(512,512),xy0=(0,-256))
    sp = SP.Spline(site.splines[0],site,field)
    result = {}
    for side,name in ((1,"left"),(-1,"right")):
        mesh,_ = build_edge(sp,side,field)
        result[name] = {key:getattr(mesh,key).ravel().tolist() for key in ("v","f","vs","vd","vh")}
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PROJECT_ONE, "Saved", "Tests", "numpy_parity.json"))
    args = ap.parse_args()
    out = {name: arrays(build(name)) for name in ("straight_100", "sine_5_50", "curve_R20_200", "rail_R300_600", "elevation_profile_100")}
    out["bank_cross"] = arrays(build("straight_100", SY.cross_slope_terrain(0.1)))
    for rule in ("bilinear", "landscape_triangulated"):
        field = Heightfield.from_function(lambda x, y: 10.0 + x * y / 32.0,
                                           extent_m=(512, 512), px_m=1.0, tile_m=512.0, xy0=(0.0, -256.0))
        field.sampling = rule
        out["twist_" + rule] = arrays(build("sine_5_50", field))
    for kind in ("batter","retaining_wall"):
        out["support_"+kind] = support_meshes(kind)
    for fixture in ('junction_arm_trims','junction_collapsed_pavement','junction_connector_bend','junction_connector_reverse'):
        arm_doc=SY.load_json(os.path.join(SY.FIXTURES_DIR,fixture+'.json'))
        arm_site=IO.site_from_dict(arm_doc);arm_plan=SP.JunctionPlan(arm_site)
        arm_builds=build_all(arm_site,SY.junction_terrain_for(arm_doc),plan=arm_plan)
        out[fixture]={}
        for sid,result in arm_builds.items():
            row=dict(s=result.spline.s.tolist(),trim=list(result.spline.s_trim))
            for name,mesh in (('road',result.road),('left',result.edge[1]),('right',result.edge[-1])):
                row[name]={key:getattr(mesh,key).ravel().tolist() for key in ('v','f','vs','vd','vh')}
            out[fixture][sid]=row
    out['corner_curves']={}
    for name,a,b,d0,d1,node in (
        ('long_shallow',[0,0,51.7],[.13,25.22,51.3],[-.063,.998],[-.311,.950],[-3.9,16.5]),
        ('parallel_s',[0,0,10],[30,10,11],[1,0],[1,0],[15,5]),
        ('translated_s',[8370,4480,10],[8400,4490,11],[1,0],[1,0],[8385,4485])):
        p,t=SP.corner_curve(a,b,d0,d1,node,10.,.75)
        n0=np.cos(.05)*np.array([-t[0,1],t[0,0],0])+np.array([0,0,np.sin(.05)])
        n1=np.cos(-.08)*np.array([-t[-1,1],t[-1,0],0])+np.array([0,0,np.sin(-.08)])
        fr=SP.corner_frames(p,t,n0,n1)
        out['corner_curves'][name]=dict(points=p.ravel().tolist(),tangents=t.ravel().tolist(),
                                       normals=fr.n.ravel().tolist(),up=fr.b.ravel().tolist())
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)
    print("wrote %s: %s" % (args.out, {k:len(v["s"]) if "s" in v else "geometry arrays" for k,v in out.items()}))


if __name__ == "__main__":
    main()
