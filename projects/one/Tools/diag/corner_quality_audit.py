"""Resumable geometry-only census of real shared junction curves and pavement folds.

Each completed document is checkpointed and hashed. A passing curve census is not
terrain/structure acceptance. Inverted pavement tops stay in coverage instead of
disappearing from a positive-normal surface filter.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
import numpy as np
TOOLS=Path(__file__).resolve().parents[1]; REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,content_identity,sha256,run_lock
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan
from streetscape.road import junction_boundary
from streetscape.edge import build_junction_corners
from streetscape.mesh import MeshBuffer
from streetscape.terrain import Heightfield


def pavement_top_stats(mesh):
    mask=mesh.group_mask_tris(prefix='corner_pavement:')
    mask &= np.min(mesh.vh[mesh.f],axis=1)>=-1e-8
    triangles=mesh.v[mesh.f[mask]]
    normal=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    inverted=normal[:,2]<-1e-8
    return dict(top_triangles=len(triangles),inverted_top_triangles=int(inverted.sum()),
        inverted_area_m2=float(np.linalg.norm(normal[inverted],axis=1).sum()*.5))


def pending_documents(documents,root,records):
    """Lost or corrupted completed reports must reduce completion coverage."""
    pending=[]
    wanted={p.name for p in documents}
    for name in list(records):
        if name not in wanted:raise ValueError('unexpected document in corner checkpoint')
    for path in documents:
        old=records.get(path.name);report_path=root/(path.stem+'.report.json')
        if not old or not report_path.exists() or sha256(report_path)!=old['report_sha256']:
            records.pop(path.name,None);pending.append(path)
    return pending


def audit_document(path,survey):
    site=io_json.load_site(str(path));plan=JunctionPlan(site)
    if (site.origin.E,site.origin.N)!=(survey.origin_E,survey.origin_N):raise ValueError('corner census registration mismatch')
    splines={};errors={}
    for sid in sorted({a.spline_id for arms in plan.arms.values() for a in arms}):
        try:splines[sid]=Spline(site.spline(sid),site,survey,trim=plan.trim_for(sid))
        except ValueError as exc:errors[sid]=str(exc)
    rows=[]
    for j in site.junctions:
        row=dict(id=j.id,xy_m=[j.x,j.y],curves=[])
        rows.append(row)
        if j.id not in plan.arms:row.update(status='not_planned');continue
        row['arms']=[a.spline_id for a in plan.arms[j.id]]
        row['structure_arms']=[sid for sid in row['arms'] if site.spline(sid).flags and
                               (site.spline(sid).flags.bridge or site.spline(sid).flags.tunnel)]
        try:
            missing={sid:errors[sid] for sid in row['arms'] if sid in errors}
            if missing:raise ValueError('arm build failed: '+str(missing))
            boundary=junction_boundary(plan,j.id,splines)
            if boundary is None:raise ValueError('planned junction has no boundary')
            q=boundary[0][:,:2]-np.array([j.x,j.y]);r=np.roll(q,-1,axis=0)
            signed=(q[:,0]*r[:,1]-q[:,1]*r[:,0])*.5
            row['patch_overlap_area_m2']=float(max(0,np.sum(abs(signed))-abs(np.sum(signed))))
            for k,(a,b,p,t,fr,_,_) in enumerate(boundary[2]):
                length=np.linalg.norm(np.diff(p,axis=0),axis=1)
                turns=np.degrees(np.arccos(np.clip(np.sum(t[:-1]*t[1:],axis=1),-1,1)))
                row['curves'].append(dict(corner=k,arms=[a.spline.id,b.spline.id],rings=len(p),
                    length_m=float(length.sum()),max_segment_m=float(length.max()),max_turn_deg=float(turns.max()),
                    min_up_z=float(fr.b[:,2].min())))
            mesh=MeshBuffer();build_junction_corners(plan,j.id,splines,mesh)
            row['pavement']=pavement_top_stats(mesh)
            folded=row['pavement']['inverted_top_triangles']>0 or any(c['min_up_z']<=0 for c in row['curves'])
            row['status']='fold_review' if folded else 'overlap_review' if row['patch_overlap_area_m2']>1e-4 else 'passed'
        except ValueError as exc:
            row.update(status='needs_geometry',error=str(exc))
    return dict(status='complete',document=path.name,junctions=len(rows),results=rows,
        totals=dict(Counter(r['status'] for r in rows)))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--streetscape',type=Path,default=REPO/'data/thanet/out/unreal/streetscape')
    ap.add_argument('--document',action='append')
    ap.add_argument('--max-docs',type=int,default=4)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/corner_quality')
    args=ap.parse_args()
    if not 1<=args.max_docs<=16:raise ValueError('max-docs must be 1..16')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('corner audit output must be under Saved/Phase1')
    documents=sorted(args.streetscape.glob('site_x*_y*.json'))
    if args.document:
        selected=set(args.document);documents=[p for p in documents if p.name in selected]
        if {p.name for p in documents}!=selected:raise ValueError('requested corner document missing')
    if not documents:raise ValueError('no corner documents')
    directory=REPO/'data/thanet/out/unreal/landscape'
    inputs=documents+[Path(__file__),TOOLS/'phase1_qc.py']+list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs += [directory/'landscape_manifest.json']+list(directory.glob('hm_*.r16'))+list(directory.glob('clip_*.r8'))
    config=dict(scope='curve/mesh quality only',numpy=np.__version__,documents=[p.name for p in documents])
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        state_path=root/'state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else dict(status='running',fingerprint=identity,
            input_sha256=hashes,config=config,phase1_accepted=False,documents={})
        if state['fingerprint']!=identity:raise ValueError('corner checkpoint identity mismatch')
        todo=pending_documents(documents,root,state['documents'])
        state['status']='running' if todo else 'complete'
        atomic_json(state_path,state)
        survey=Heightfield.from_landscape_dir(str(directory));survey.sampling='landscape_triangulated'
        for path in todo[:args.max_docs]:
            start=time.time();report=audit_document(path,survey);report['seconds']=round(time.time()-start,3)
            report_path=root/(path.stem+'.report.json');atomic_json(report_path,report)
            state['documents'][path.name]=dict(report_sha256=sha256(report_path),totals=report['totals'],seconds=report['seconds'])
            atomic_json(state_path,state)
            print(path.name,report['totals'],report['seconds'],'seconds',flush=True)
        if content_identity(inputs,config)[0]!=identity:raise ValueError('corner census inputs changed during run')
        counts=Counter()
        for row in state['documents'].values():counts.update(row['totals'])
        state.update(status='complete' if len(state['documents'])==len(documents) else 'pending',totals=dict(counts))
        atomic_json(state_path,state)
        print(json.dumps(dict(state=str(state_path),status=state['status'],completed=len(state['documents']),total=len(documents),totals=state['totals'])))


if __name__=='__main__':main()
