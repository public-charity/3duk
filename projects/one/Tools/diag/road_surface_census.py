"""Bounded full census of actual road, pavement, ballast and rail mapping folds.

Unlike a changed-body comparison, every definition stays in coverage. Non-road
definitions are explicitly counted. This does not accept terrain, intersections
between separate roads, continuation joins, structures or native rendering.
"""
import argparse,json,re,sys,time
from collections import Counter
from pathlib import Path
import numpy as np
TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,sha256,content_identity,run_lock
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan
from streetscape.terrain import Heightfield
from streetscape.road import build_road
from streetscape.edge import build_edge
from diag.road_body_quality import mapped_top_stats


def measure_surface(site,sid,survey,plan):
    definition=site.spline(sid)
    if definition.profile_ids.road is None:return dict(status='without_road_profile',kind=None)
    try:
        spline=Spline(definition,site,survey,trim=plan.trim_for(sid));mesh,_=build_road(spline)
        groups=('ballast','rail:left','rail:right') if spline.kind=='rail' else ('road',)
        parts={group:mapped_top_stats(mesh,group) for group in groups}
        if any(not parts[group]['surface_triangles'] for group in groups):
            raise ValueError('required active road/rail surface is empty')
        for side in (-1,1):
            edge,_=build_edge(spline,side)
            parts['pavement_'+str(side)]=mapped_top_stats(edge,'pavement')
        return dict(status='fold_review' if any(r['folded_triangles'] for r in parts.values()) else 'passed',kind=spline.kind,
            length_m=spline.length,trim_m=list(plan.trim_for(sid)),parts=parts)
    except ValueError as exc:return dict(status='needs_geometry',kind=None,error=str(exc))


def audit_document(path,survey):
    site=io_json.load_site(str(path));plan=JunctionPlan(site)
    if (site.origin.E,site.origin.N)!=(survey.origin_E,survey.origin_N):raise ValueError('surface census registration mismatch')
    ids=[d.id for d in site.splines]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate spline coverage')
    rows=[dict(id=sid,**measure_surface(site,sid,survey,plan)) for sid in ids]
    return dict(status='complete',phase1_accepted=False,document=path.name,definitions=len(ids),
        totals=dict(Counter(r['status'] for r in rows)),kinds=dict(Counter(r['kind'] or 'not_measured_as_road' for r in rows)),results=rows)


def pending_documents(paths,root,records):
    names={p.name for p in paths}
    if not names or set(records)-names:raise ValueError('surface checkpoint coverage mismatch')
    pending=[]
    for path in paths:
        record=records.get(path.name);report=root/(path.stem+'.report.json')
        if not record or not report.exists() or sha256(report)!=record['report_sha256']:
            records.pop(path.name,None);pending.append(path)
    return pending


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--streetscape',type=Path,required=True)
    ap.add_argument('--document',action='append');ap.add_argument('--max-docs',type=int,default=4)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/road_surface_census');args=ap.parse_args()
    if not 1<=args.max_docs<=8:raise ValueError('max-docs must be 1..8')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must stay under Saved/Phase1')
    paths=sorted(p for p in args.streetscape.glob('site_x*_y*.json') if re.fullmatch(r'site_x-?\d+_y-?\d+\.json',p.name))
    if args.document:
        paths=[p for p in paths if p.name in args.document]
        if {p.name for p in paths}!=set(args.document):raise ValueError('requested surface document missing')
    if not paths:raise ValueError('no surface documents')
    terrain=REPO/'data/thanet/out/unreal/landscape'
    inputs=paths+[Path(__file__),TOOLS/'phase1_qc.py',TOOLS/'diag/road_body_quality.py']
    inputs+=list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs+=[terrain/'landscape_manifest.json']+list(terrain.glob('hm_*.r16'))+list(terrain.glob('clip_*.r8'))
    config=dict(scope='all active road/rail/pavement mapping surfaces',documents=[p.name for p in paths],numpy=np.__version__)
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        path=root/'state.json';state=json.loads(path.read_text()) if path.exists() else dict(status='pending',phase1_accepted=False,
            fingerprint=identity,input_sha256=hashes,config=config,documents={})
        if state['fingerprint']!=identity:raise ValueError('surface checkpoint identity changed')
        pending=pending_documents(paths,root,state['documents'])
        survey=Heightfield.from_landscape_dir(str(terrain));survey.sampling='landscape_triangulated'
        for document in pending[:args.max_docs]:
            start=time.perf_counter();report=audit_document(document,survey);report['seconds']=round(time.perf_counter()-start,3)
            target=root/(document.stem+'.report.json');atomic_json(target,report)
            state['documents'][document.name]={k:v for k,v in report.items() if k!='results'}
            state['documents'][document.name]['report_sha256']=sha256(target);atomic_json(path,state)
            print(document.name,report['totals'],report['seconds'],'seconds',flush=True)
        if content_identity(inputs,config)[0]!=identity:raise ValueError('surface census inputs changed')
        totals=Counter();kinds=Counter()
        for row in state['documents'].values():totals.update(row['totals']);kinds.update(row['kinds'])
        state.update(status='complete' if len(state['documents'])==len(paths) else 'pending',totals=dict(totals),kinds=dict(kinds),
            definitions=sum(r['definitions'] for r in state['documents'].values()),completed=len(state['documents']),total=len(paths))
        if sum(totals.values())!=state['definitions']:raise ValueError('surface census lost definitions')
        atomic_json(path,state)
        print(json.dumps(dict(state=str(path),**{k:state[k] for k in ('status','completed','total','definitions','totals','kinds')})))


if __name__=='__main__':main()
