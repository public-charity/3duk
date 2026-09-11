"""Bounded, resumable trim candidates using actual A/B meshes and neighbour QC.

Only existing junction trim_radius_m fields change in complete Saved documents.
Geometry acceptance remains separate from terrain, driving, structures and native
preview. Every trial checks all junctions whose shared arm trims have changed.
"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import time
import numpy as np

TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,content_identity,sha256,run_lock
from streetscape import io_json
from streetscape.spline import JunctionPlan,Spline
from streetscape.terrain import Heightfield
from streetscape.road import junction_boundary
from streetscape.edge import build_junction_corners
from streetscape.mesh import MeshBuffer
from diag.corner_quality_audit import audit_document,pavement_top_stats

RADII=[.5,1.,1.5,2.,2.5,3.,3.5,4.,4.5,5.,5.5,6.,6.5,7.,7.5,8.,9.,10.,11.,12.,14.,16.,18.,20.,22.,24.,26.,28.,30.,32.]


def metrics(row):
    p=row.get('pavement',{})
    return dict(status=row['status'],overlap=row.get('patch_overlap_area_m2'),
        inverted=p.get('inverted_area_m2'),folded=p.get('folded_top_area_m2'))


def regressions(before,after):
    if set(before)!=set(after):raise ValueError('junction coverage changed')
    out=[]
    for jid,a in before.items():
        b=after[jid];reasons=[]
        if a['status']=='passed' and b['status']!='passed':reasons.append('pass lost')
        if a['status']!='needs_geometry' and b['status']=='needs_geometry':reasons.append('new geometry failure')
        for key,tol in (('overlap',1e-4),('inverted',1e-6),('folded',1e-6)):
            if a[key] is not None and b[key] is not None and b[key]>a[key]+tol:reasons.append(key+' increased')
        if reasons:out.append(dict(id=jid,reasons=reasons))
    return out


class CachedPlan(JunctionPlan):
    """Plan curves depend only on unchanged splines/profiles, never junction trims."""
    def __init__(self,site,curves):
        self.shared_curves=curves
        super().__init__(site)

    def _curve(self,sid):
        if sid not in self.shared_curves:self.shared_curves[sid]=super()._curve(sid)
        return self.shared_curves[sid]


class Evaluator:
    def __init__(self,site,survey):
        self.site=site;self.survey=survey;self.curves={};self.splines={}

    def plan(self):return CachedPlan(self.site,self.curves)

    def spline(self,sid,plan):
        key=(sid,plan.trim_for(sid))
        if key not in self.splines:
            self.splines[key]=Spline(self.site.spline(sid),self.site,self.survey,trim=key[1])
        return self.splines[key]

    def measure(self,plan,jid):
        row=dict(status='needs_geometry',overlap=None,inverted=None,folded=None)
        try:
            if jid not in plan.arms:return dict(row,status='not_planned')
            ss={a.spline_id:self.spline(a.spline_id,plan) for a in plan.arms[jid]}
            boundary=junction_boundary(plan,jid,ss)
            if boundary is None:raise ValueError('missing boundary')
            j=plan.junction(jid);q=boundary[0][:,:2]-[j.x,j.y];r=np.roll(q,-1,axis=0)
            signed=.5*(q[:,0]*r[:,1]-q[:,1]*r[:,0])
            row['overlap']=float(max(0,np.sum(abs(signed))-abs(np.sum(signed))))
            mesh=MeshBuffer();corner=build_junction_corners(plan,jid,ss,mesh)
            if corner['skipped_incompatible']:raise ValueError('incompatible corner sections')
            p=pavement_top_stats(mesh);row.update(inverted=p['inverted_area_m2'],folded=p['folded_top_area_m2'])
            folded=p['inverted_top_triangles'] or p['folded_top_triangles'] or any(np.min(c[4].b[:,2])<=0 for c in boundary[2])
            row['status']='fold_review' if folded else 'overlap_review' if row['overlap']>1e-4 else 'passed'
        except ValueError:
            pass
        return row

    def affected(self,old,new):
        changed={sid for sid in set(old.trims)|set(new.trims) if old.trim_for(sid)!=new.trim_for(sid)}
        return {jid for jid,arms in new.arms.items() if any(a.spline_id in changed for a in arms)}


def try_radius(evaluator,plan,current,jid,radius):
    """Temporarily evaluate one existing trim; always restore the schema object."""
    j=plan.junction(jid);previous=j.trim_radius_m
    try:
        j.trim_radius_m=radius;trial=evaluator.plan()
        # Respect the shared planner's half-length rule. Do not consume a short
        # fragment to manufacture a passing corner; that needs connected context.
        for a in trial.arms[jid]:
            old=next(x for x in plan.arms[jid] if x.spline_id==a.spline_id and x.end==a.end)
            limit=max(old.trim_m,float(plan.cfg['max_trim_frac_of_length'])*trial._curve(a.spline_id)[7])
            if a.trim_m>limit+1e-8:return dict(radius_m=radius,status='length_limit'),None,None
        changed=evaluator.affected(plan,trial)|{jid}
        after=dict(current)
        for other in sorted(changed):after[other]=evaluator.measure(trial,other)
        bad=regressions(current,after)
        accepted=after[jid]['status']=='passed' and not bad
        result=dict(radius_m=radius,status='geometry_candidate' if accepted else 'rejected',
            target=after[jid],affected=sorted(changed),regressions=bad)
        return result,trial if accepted else None,after if accepted else None
    finally:
        j.trim_radius_m=previous


def verify_document(source,candidate):
    """Exact complete-document preservation except bounded existing trim fields."""
    normal=copy.deepcopy(candidate)
    if [j['id'] for j in source.get('junctions',[])]!=[j['id'] for j in normal.get('junctions',[])]:
        raise ValueError('junction coverage/order changed')
    for a,b in zip(source.get('junctions',[]),normal.get('junctions',[])):
        if a.get('trim_radius_m')!=b.get('trim_radius_m'):
            value=b.get('trim_radius_m')
            if not isinstance(value,(int,float)) or not np.isfinite(value) or not 0<value<=32:
                raise ValueError('candidate trim outside (0,32]')
        if 'trim_radius_m' in a:b['trim_radius_m']=a['trim_radius_m']
        else:b.pop('trim_radius_m',None)
    if source!=normal:raise ValueError('candidate changed non-trim source data')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--document',type=Path,required=True)
    ap.add_argument('--junction',action='append')
    ap.add_argument('--max-junctions',type=int,default=2)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/junction_trim_candidates')
    args=ap.parse_args()
    if not 1<=args.max_junctions<=8:raise ValueError('max-junctions must be 1..8')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must stay under Saved/Phase1')
    source=json.loads(args.document.read_text());survey_dir=REPO/'data/thanet/out/unreal/landscape'
    inputs=[args.document,Path(__file__),TOOLS/'phase1_qc.py',TOOLS/'diag/corner_quality_audit.py']
    inputs+=list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs+=[survey_dir/'landscape_manifest.json']+list(survey_dir.glob('hm_*.r16'))+list(survey_dir.glob('clip_*.r8'))
    config=dict(scope='trim-only geometry candidates; terrain/driving/native unaccepted',radii_m=RADII,
        selected=sorted(set(args.junction)) if args.junction else None,numpy=np.__version__)
    identity,hashes=content_identity(inputs,config);root=args.out/args.document.stem/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        state_path=root/'state.json';survey=Heightfield.from_landscape_dir(str(survey_dir));survey.sampling='landscape_triangulated'
        if state_path.exists():
            state=json.loads(state_path.read_text())
            if state['fingerprint']!=identity:raise ValueError('checkpoint identity changed')
            doc_path=root/state['document'];report_path=root/state['report']
            if sha256(doc_path)!=state['document_sha256'] or sha256(report_path)!=state['report_sha256']:
                raise ValueError('checkpoint document/report missing or corrupt; do not reuse completion')
            data=json.loads(doc_path.read_text());report=json.loads(report_path.read_text())
        else:
            data=copy.deepcopy(source);report=audit_document(args.document,survey)
            atomic_json(root/'source_report.json',report)
            state=dict(status='pending',fingerprint=identity,input_sha256=hashes,config=config,phase1_accepted=False,
                attempts={},baseline_totals=report['totals'])
        verify_document(source,data)
        site=io_json.site_from_dict(data);evaluator=Evaluator(site,survey);plan=evaluator.plan()
        current={r['id']:metrics(r) for r in report['results']}
        selected=set(args.junction) if args.junction else {jid for jid,r in current.items() if r['status']!='passed'}
        if selected-set(current):raise ValueError('unknown junction selection')
        pending=[jid for jid in sorted(selected) if jid not in state['attempts']]
        for jid in pending[:args.max_junctions]:
            start=time.perf_counter();trials=[];accepted=None
            arms=plan.arms.get(jid,[])
            context=not arms or any(getattr(site.spline(a.spline_id).flags,k,False) for a in arms for k in ('bridge','tunnel','steps'))
            if current[jid]['status']=='passed':status='already_passed'
            elif context:status='needs_structure_or_connected_context'
            else:
                status='needs_geometry'
                for radius in RADII:
                    if radius<float(plan.junction(jid).radius_m or 0):continue
                    trial,new_plan,after=try_radius(evaluator,plan,current,jid,radius);trials.append(trial)
                    if new_plan is not None:
                        # Independent full-document audit is the authority; cached
                        # local evaluation is only a fast proposal mechanism.
                        proposal=copy.deepcopy(data)
                        next(j for j in proposal['junctions'] if j['id']==jid)['trim_radius_m']=radius
                        verify_document(source,proposal)
                        trial_path=root/'trial.json';atomic_json(trial_path,proposal)
                        checked=audit_document(trial_path,survey)
                        full={r['id']:metrics(r) for r in checked['results']}
                        if full!=after or regressions(current,full):raise ValueError('incremental/full geometry audit mismatch')
                        data=proposal;report=checked;current=full;plan.junction(jid).trim_radius_m=radius
                        plan=evaluator.plan();accepted=radius;status='geometry_candidate';break
            state['attempts'][jid]=dict(status=status,accepted_radius_m=accepted,trials=trials,seconds=round(time.perf_counter()-start,3))
            # Immutable step files + one atomic state pointer survive interruption
            # between writing a document, report, and completion record.
            step='step_%04d'%len(state['attempts']);doc_path=root/step/args.document.name;report_path=root/step/'report.json'
            atomic_json(doc_path,data);atomic_json(report_path,report)
            state.update(document=str(doc_path.relative_to(root)),document_sha256=sha256(doc_path),
                report=str(report_path.relative_to(root)),report_sha256=sha256(report_path),totals=report['totals'])
            atomic_json(state_path,state)
            evaluator.splines.clear()
            print(jid,status,accepted,state['attempts'][jid]['seconds'],'seconds',flush=True)
        if not state['attempts']:
            doc_path=root/'unchanged'/args.document.name;report_path=root/'unchanged/report.json'
            atomic_json(doc_path,data);atomic_json(report_path,report)
            state.update(document=str(doc_path.relative_to(root)),document_sha256=sha256(doc_path),
                report=str(report_path.relative_to(root)),report_sha256=sha256(report_path),totals=report['totals'])
        if content_identity(inputs,config)[0]!=identity:raise ValueError('trim inputs changed during run')
        remaining=selected-set(state['attempts'])
        state.update(status='pending' if remaining else 'complete',remaining=len(remaining),attempted=len(state['attempts']))
        atomic_json(state_path,state)
        print(json.dumps(dict(state=str(state_path),status=state['status'],remaining=len(remaining),totals=state['totals'])))


if __name__=='__main__':main()
