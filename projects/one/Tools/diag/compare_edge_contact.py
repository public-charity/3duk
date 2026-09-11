"""Compare actual banked outer-face bases before/after a bounded document edit.

Uses emitted active edge segments (including bare skirts), sampled at <=25 cm.
Different geometry is measured against its own ground; maxima alone are a screen,
not proof that every support or triangle interior is covered.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS)); sys.path.insert(0,str(TOOLS/"blender"))
from phase1_qc import atomic_json,sha256,content_identity
from streetscape import io_json
from streetscape.spline import JunctionPlan,Spline
from streetscape.terrain import Heightfield
from diag.junction_contact_candidate import ribbon_bottom_points


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before-document",type=Path,required=True)
    ap.add_argument("--after-document",type=Path,required=True)
    ap.add_argument("--before-ground",type=Path,required=True)
    ap.add_argument("--after-ground",type=Path,required=True)
    ap.add_argument("--survey",type=Path,default=TOOLS.parents[2]/"data/thanet/out/unreal/landscape")
    ap.add_argument("--bounds",required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    b=np.array(list(map(float,args.bounds.split(","))))
    if b.shape!=(4,) or not np.isfinite(b).all() or np.any(b[2:]-b[:2]<=0) or np.any(b[2:]-b[:2]>256):
        raise ValueError("invalid bounded rectangle")
    bounds=(b[:2],b[2:])
    survey=Heightfield.from_landscape_dir(str(args.survey)); survey.sampling="landscape_triangulated"
    inputs=[args.before_document,args.after_document,Path(__file__),TOOLS/'phase1_qc.py',
            TOOLS/'diag/junction_contact_candidate.py',TOOLS/'diag/terrain_contact.py']
    inputs+=list((TOOLS/'blender/streetscape').glob('*.py'))
    for directory in (args.survey,args.before_ground,args.after_ground):
        inputs += [directory/'landscape_manifest.json']+list(directory.glob('hm_*.r16'))+list(directory.glob('clip_*.r8'))
    identity,hashes=content_identity(inputs,dict(bounds=b.tolist(),spacing_m=.25,regression_gate_m=.005))
    report=dict(status='running',fingerprint=identity,input_sha256=hashes,
                scope="bounded actual outer-face base screen",phase1_accepted=False,bounds_m=b.tolist(),
                before_document_sha256=sha256(args.before_document),after_document_sha256=sha256(args.after_document),results={})
    for tag,path,ground_path in (("before",args.before_document,args.before_ground),("after",args.after_document,args.after_ground)):
        ground=Heightfield.from_landscape_dir(str(ground_path)); ground.sampling="landscape_triangulated"
        site=io_json.load_site(str(path)); plan=JunctionPlan(site)
        if (site.origin.E,site.origin.N)!=(survey.origin_E,survey.origin_N) or (site.origin.E,site.origin.N)!=(ground.origin_E,ground.origin_N):
            raise ValueError("registration mismatch")
        rows={}
        for definition in site.splines:
            if definition.source.layer!="roads" or (definition.flags and (definition.flags.bridge or definition.flags.tunnel)): continue
            p=np.array([[p.x,p.y] for p in definition.points])
            if np.any(p.max(axis=0)+20 < b[:2]) or np.any(p.min(axis=0)-20 > b[2:]): continue
            sp=Spline(definition,site,survey,trim=plan.trim_for(definition.id))
            points=ribbon_bottom_points(sp,bounds)
            if not len(points): continue
            gap=points[:,2]-ground.sample(points[:,0],points[:,1])
            if not np.isfinite(gap).all(): raise ValueError("missing edge ground: "+definition.id)
            worst=int(np.argmax(gap))
            rows[definition.id]=dict(samples=len(points),max_gap_m=float(max(0,gap[worst])),
                samples_over_125mm=int(np.sum(gap>.125)),worst_xyz_m=points[worst].tolist())
        if not rows: raise ValueError("empty edge coverage")
        report["results"][tag]=rows
        report[tag+"_ground_manifest_sha256"]=sha256(ground_path/"landscape_manifest.json")
        atomic_json(args.out,report)
    a,c=report["results"]["before"],report["results"]["after"]
    report["added_or_lost_coverage"]=sorted(set(a)^set(c))
    report["max_gap_regressions"]=[dict(id=sid,increase_m=c[sid]["max_gap_m"]-a[sid]["max_gap_m"],before=a[sid],after=c[sid])
        for sid in sorted(set(a)&set(c)) if c[sid]["max_gap_m"]-a[sid]["max_gap_m"]>.005]
    report["screen_pass"]=not report["max_gap_regressions"] and not report["added_or_lost_coverage"]
    if content_identity(inputs,dict(bounds=b.tolist(),spacing_m=.25,regression_gate_m=.005))[0]!=identity:
        raise ValueError('edge comparison inputs changed during measurement')
    report['status']='complete'
    atomic_json(args.out,report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('results','input_sha256')},indent=2))


if __name__=="__main__": main()
