"""Checkpointed actual-road/pavement ribbon comparison for data candidates.

Junction-only acceptance does not cover the street between its ends. Compare every
changed spline, including shared-plan trim effects, using the active A/B meshes.
This is a mapping-fold screen, not terrain, self-intersection or native acceptance.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
import numpy as np
TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,content_identity,sha256,run_lock
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan
from streetscape.road import build_road
from streetscape.edge import build_edge
from streetscape.terrain import Heightfield


def mapped_top_stats(mesh,group):
    if len(mesh.vs)!=len(mesh.v) or len(mesh.vd)!=len(mesh.v):
        raise ValueError('ribbon mapping audit requires station/offset attributes')
    faces=mesh.f[mesh.group_mask_tris(exact=group)];tri=mesh.v[faces]
    sd=np.column_stack([mesh.vs,mesh.vd])[faces]
    if not np.all(np.isfinite(tri)) or not np.all(np.isfinite(sd)):
        raise ValueError('non-finite ribbon coordinates')
    a,b=sd[:,1]-sd[:,0],sd[:,2]-sd[:,0]
    param=a[:,0]*b[:,1]-a[:,1]*b[:,0]
    normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    # Vertical kerb/pavement backs have zero parameter area. Top surfaces can
    # have negative reference height from camber/drop kerbs and must stay in QA.
    top=abs(param)>1e-12
    folded=top&(normal[:,2]*param<0)&(abs(normal[:,2])>1e-8)
    selected=sd[folded,:,0]
    return dict(surface_triangles=int(top.sum()),folded_triangles=int(folded.sum()),
        folded_area_m2=float(np.linalg.norm(normal[folded],axis=1).sum()*.5),
        folded_station_range_m=[float(selected.min()),float(selected.max())] if len(selected) else None)


def measure_spline(site,sid,survey,plan):
    try:
        spline=Spline(site.spline(sid),site,survey,trim=plan.trim_for(sid))
        if spline.kind=='rail':return dict(status='rail_needs_separate_surface_audit')
        road,_=build_road(spline);parts=dict(road=mapped_top_stats(road,'road'))
        for side in (-1,1):
            edge,_=build_edge(spline,side)
            parts['pavement_'+str(side)]=mapped_top_stats(edge,'pavement')
        return dict(status='fold_review' if any(p['folded_triangles'] for p in parts.values()) else 'passed',
            trim_m=list(plan.trim_for(sid)),length_m=spline.length,parts=parts)
    except ValueError as exc:
        return dict(status='needs_geometry',error=str(exc))


def referenced_strings(value):
    if isinstance(value,str):return {value}
    if isinstance(value,list):return set().union(*(referenced_strings(v) for v in value))
    if isinstance(value,dict):return set().union(*(referenced_strings(v) for v in value.values()))
    return set()


def spline_signature(raw,definition):
    refs=referenced_strings(definition)
    profiles={kind:{k:v for k,v in table.items() if k in refs} for kind,table in raw['profiles'].items()}
    return [definition,profiles,{k:v for k,v in raw.items() if k not in ('splines','profiles','junctions')}]


def interior_mask_signature(plan,sid):
    return sorted((j.id,tuple(sorted((e.end,e.station_m) for e in j.ends)))
                  for j in plan.site.junctions if j.kind=='bend' and any(e.spline_id==sid for e in j.ends))


def body_regressions(before,after):
    reasons=[]
    if before['status']=='passed' and after['status']!='passed':reasons.append('body pass lost')
    if before['status']!='needs_geometry' and after['status']=='needs_geometry':reasons.append('new body build failure')
    for part,a in before.get('parts',{}).items():
        b=after.get('parts',{}).get(part)
        if b is not None and b['folded_area_m2']>a['folded_area_m2']+1e-6:
            reasons.append(part+' folded area increased')
    return reasons


def compare_document(before_path,after_path,survey):
    raws=[json.loads(p.read_text()) for p in (before_path,after_path)]
    definitions=[{d['id']:d for d in raw['splines']} for raw in raws]
    if any(len(ds)!=len(raw['splines']) for ds,raw in zip(definitions,raws)) or set(definitions[0])!=set(definitions[1]):
        raise ValueError('spline coverage changed')
    sites=[io_json.site_from_dict(raw) for raw in raws];plans=[JunctionPlan(site) for site in sites]
    for site in sites:
        if (site.origin.E,site.origin.N)!=(survey.origin_E,survey.origin_N):raise ValueError('body audit registration mismatch')
    rows=[];unchanged=0;without_road=0
    for sid,d in definitions[0].items():
        other=definitions[1][sid]
        if not d['profile_ids'].get('road') and not other['profile_ids'].get('road'):
            without_road+=1;continue
        if (spline_signature(raws[0],d)==spline_signature(raws[1],other)
                and plans[0].trim_for(sid)==plans[1].trim_for(sid)
                and interior_mask_signature(plans[0],sid)==interior_mask_signature(plans[1],sid)):
            unchanged+=1;continue
        a,b=[measure_spline(site,sid,survey,plan) for site,plan in zip(sites,plans)]
        rows.append(dict(id=sid,before=a,after=b,reasons=body_regressions(a,b)))
    return dict(document=before_path.name,status='complete',phase1_accepted=False,results=rows,
        total_splines=len(definitions[0]),unchanged_road_splines=unchanged,without_road_profile=without_road,
        changed_splines=len(rows),regressions=sum(bool(r['reasons']) for r in rows),
        before=dict(Counter(r['before']['status'] for r in rows)),after=dict(Counter(r['after']['status'] for r in rows)))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before',type=Path,required=True);ap.add_argument('--after',type=Path,required=True)
    ap.add_argument('--document',action='append');ap.add_argument('--max-docs',type=int,default=8)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/road_body_quality')
    args=ap.parse_args()
    if not 1<=args.max_docs<=32:raise ValueError('max-docs must be 1..32')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must stay under Saved/Phase1')
    names=sorted(p.name for p in args.before.glob('site_x*_y*.json') if not p.name.endswith('.report.json'))
    after_names={p.name for p in args.after.glob('site_x*_y*.json') if not p.name.endswith('.report.json')}
    if set(names)!=after_names:raise ValueError('document coverage changed')
    if args.document:
        if set(args.document)-set(names):raise ValueError('requested document missing')
        names=[n for n in names if n in args.document]
    if not names:raise ValueError('no documents')
    terrain=REPO/'data/thanet/out/unreal/landscape'
    inputs=[p/n for p in (args.before,args.after) for n in names]+[Path(__file__),TOOLS/'phase1_qc.py']
    inputs+=list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs+=[terrain/'landscape_manifest.json']+list(terrain.glob('hm_*.r16'))+list(terrain.glob('clip_*.r8'))
    config=dict(before=str(args.before.resolve()),after=str(args.after.resolve()),documents=names,
        scope='changed active road/pavement mapping only',numpy=np.__version__)
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        path=root/'state.json'
        state=json.loads(path.read_text()) if path.exists() else dict(status='pending',fingerprint=identity,
            input_sha256=hashes,config=config,phase1_accepted=False,documents={})
        if state['fingerprint']!=identity or set(state['documents'])-set(names):raise ValueError('body checkpoint mismatch')
        for name,r in state['documents'].items():
            if sha256(root/(Path(name).stem+'.report.json'))!=r['report_sha256']:raise ValueError('body report missing/corrupt')
        pending=[name for name in names if name not in state['documents']]
        survey=Heightfield.from_landscape_dir(str(terrain));survey.sampling='landscape_triangulated'
        for name in pending[:args.max_docs]:
            start=time.perf_counter();report=compare_document(args.before/name,args.after/name,survey)
            report['seconds']=round(time.perf_counter()-start,3)
            target=root/(Path(name).stem+'.report.json');atomic_json(target,report)
            state['documents'][name]={k:v for k,v in report.items() if k!='results'}
            state['documents'][name]['report_sha256']=sha256(target);atomic_json(path,state)
            print(name,report['changed_splines'],'changed',report['regressions'],'regressions',report['seconds'],'seconds',flush=True)
        if content_identity(inputs,config)[0]!=identity:raise ValueError('body audit inputs changed')
        totals=Counter()
        for r in state['documents'].values():
            totals.update({k:r[k] for k in ('changed_splines','regressions','unchanged_road_splines','without_road_profile','total_splines')})
        state.update(status='complete' if len(state['documents'])==len(names) else 'pending',totals=dict(totals))
        atomic_json(path,state)
        print(json.dumps(dict(state=str(path),status=state['status'],completed=len(state['documents']),total=len(names),totals=state['totals'])))


if __name__=='__main__':main()
