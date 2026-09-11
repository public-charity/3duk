"""Bounded, resumable per-end trim proposals with real neighbour and body gates.

Complete documents stay below Saved/Phase1. Every retained target must pass a
fresh full-document audit and changed-body comparison. Partial improvements are
diagnostic only. Terrain, continuation seams and native world acceptance remain
separate; no geometry core is patched by this tool.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time
from collections import Counter
import numpy as np
import scipy
from scipy.optimize import differential_evolution

TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,content_identity,sha256,run_lock
from streetscape import io_json
from streetscape.terrain import Heightfield
from diag.junction_trim_candidates import CachedPlan,Evaluator,metrics,regressions
from diag.corner_quality_audit import audit_document
from diag.road_body_quality import measure_spline,body_regressions,compare_document


class RequestedPlan(CachedPlan):
    """Observe the final requests before minimum-remaining trim reconciliation."""
    def __init__(self,site,curves):
        self.requested={}
        super().__init__(site,curves)

    def _arm_at(self,jid,sid,end,cx,cy,radius):
        self.requested.setdefault(jid,{})[(sid,end)]=float(radius)
        return super()._arm_at(jid,sid,end,cx,cy,radius)


def verify_document(source,candidate):
    normal=copy.deepcopy(candidate)
    a=source.get('junctions',[]);b=normal.get('junctions',[])
    if [j['id'] for j in a]!=[j['id'] for j in b]:raise ValueError('junction coverage/order changed')
    for old,new in zip(a,b):
        if [(e['spline_id'],e['end']) for e in old['ends']]!=[(e['spline_id'],e['end']) for e in new['ends']]:
            raise ValueError('junction end bindings/order changed')
        for oe,ne in zip(old['ends'],new['ends']):
            if oe.get('trim_radius_m')!=ne.get('trim_radius_m'):
                value=ne.get('trim_radius_m')
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not 0<value<=32:
                    raise ValueError('arm trim outside (0,32]')
            if 'trim_radius_m' in oe:ne['trim_radius_m']=oe['trim_radius_m']
            else:ne.pop('trim_radius_m',None)
    if source!=normal:raise ValueError('candidate changed non-arm-trim source data')


def within_length_limits(before,after):
    """Check every changed end, including the opposite end of a short shared link."""
    for sid in set(before.trims)|set(after.trims):
        old=before.trim_for(sid);new=after.trim_for(sid)
        if old==new:continue
        length=after._curve(sid)[7];fraction=float(before.cfg['max_trim_frac_of_length'])
        if any(b>max(a,fraction*length)+1e-8 for a,b in zip(old,new)):return False
    return True


class BudgetExpired(Exception):pass


def search(evaluator,plan,current,jid,seconds=20.,seed=17):
    start=time.perf_counter();hard_deadline=start+seconds;deadline=start+.8*seconds
    initial=current[jid];j=plan.junction(jid)
    observation=RequestedPlan(evaluator.site,evaluator.curves)
    keys=sorted(observation.requested[jid]);lookup={(e.spline_id,e.end):e for e in j.ends}
    original_values={key:lookup[key].trim_radius_m for key in keys}
    radii=np.array([observation.requested[jid][key] for key in keys])
    bounds=[(.5,min(32.,max(float(r),.5*plan._curve(k[0])[7]))) for k,r in zip(keys,radii)]
    if any(not lo<=r<=hi for r,(lo,hi) in zip(radii,bounds)):
        return dict(status='needs_radius_context',before=initial,seconds=time.perf_counter()-start),None,None
    def assign(values):
        for key,value in zip(keys,values):lookup[key].trim_radius_m=float(value)
    attempts=0;rejections=Counter();kept=[];bodies={};best=initial;best_all=current;best_values=radii.copy()
    best_score=float('inf');timed_out=False
    try:
        assign(radii)
        reconstructed=evaluator.plan()
        if plan.trims!=reconstructed.trims or evaluator.measure(reconstructed,jid)!=initial:
            raise ValueError('captured arm requests do not reproduce baseline')
        def objective(values):
            nonlocal attempts,best,best_all,best_values,best_score
            if time.perf_counter()>deadline:raise BudgetExpired()
            attempts+=1
            if attempts%32==0:evaluator.splines.clear()
            assign(values);trial=evaluator.plan()
            if not within_length_limits(plan,trial):rejections['length']+=1;return 1e6
            target=evaluator.measure(trial,jid)
            if regressions({jid:initial},{jid:target}):rejections['target_regression']+=1;return 1e5
            if target['status'] in ('needs_geometry','not_planned'):rejections['unbuildable']+=1;return 1e5
            score=float(sum(values))*1e-5 if target['status']=='passed' else 1.+sum(
                (target[k] or 0)/max(initial[k] or 0,1e-6) for k in ('overlap','folded','inverted'))
            if score>=best_score:return score
            after=dict(current)
            for other in evaluator.affected(plan,trial)|{jid}:after[other]=evaluator.measure(trial,other)
            if regressions(current,after):rejections['neighbour_regression']+=1;return 1e4
            for sid in sorted(set(plan.trims)|set(trial.trims)):
                if plan.trim_for(sid)==trial.trim_for(sid):continue
                if sid not in bodies:bodies[sid]=measure_spline(evaluator.site,sid,evaluator.survey,plan)
                new=measure_spline(evaluator.site,sid,evaluator.survey,trial)
                if new['status'] not in ('passed','fold_review') or body_regressions(bodies[sid],new):
                    rejections['body_regression_or_unmeasured']+=1;return 1e3
            best=target;best_all=after;best_values=np.array(values,dtype=float);best_score=score
            kept.append(dict(evaluation=attempts,score=score,target=target,radii_m=best_values.tolist()))
            return score
        try:
            objective(radii)
            for _ in range(2):
                changed=False
                for index in range(len(keys)):
                    radius=best_values[index]
                    for value in sorted(set(np.clip(radius+d,*bounds[index]) for d in (-8,-4,-2,-1,-.5,.5,1,2,4,8))):
                        previous=best_score;proposal=best_values.copy();proposal[index]=value;objective(proposal)
                        changed=changed or best_score<previous
                        if best['status']=='passed' or time.perf_counter()>start+.4*seconds:break
                    if best['status']=='passed' or time.perf_counter()>start+.4*seconds:break
                if not changed or best['status']=='passed' or time.perf_counter()>start+.4*seconds:break
            if best['status']!='passed':
                differential_evolution(objective,bounds,popsize=5,maxiter=40,seed=seed,polish=False,tol=0,atol=0,
                    x0=best_values,callback=lambda *args:best['status']=='passed')
        except BudgetExpired:timed_out=True
        # Reserve time to shrink the first feasible random proposal under the same gates.
        deadline=hard_deadline
        if best['status']=='passed':
            try:
                for _ in range(2):
                    for index in range(len(keys)):
                        radius=best_values[index]
                        for value in sorted(set(max(bounds[index][0],radius-d) for d in (.25,.5,1,2,4,8,12))):
                            proposal=best_values.copy();proposal[index]=value;objective(proposal)
            except BudgetExpired:timed_out=True
        row=dict(status='geometry_proposal' if best['status']=='passed' else 'needs_geometry',before=initial,
            best=best,evaluations=attempts,rejections=dict(rejections),improvements=kept,timed_out=timed_out,
            seconds=round(time.perf_counter()-start,3))
        if best['status']!='passed':return row,None,None
        row['requests']=[dict(spline_id=k[0],end=k[1],trim_radius_m=float(v)) for k,v in zip(keys,best_values)]
        return row,row['requests'],best_all
    finally:
        for key,value in original_values.items():lookup[key].trim_radius_m=value


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--document',type=Path,required=True);ap.add_argument('--junction',action='append')
    ap.add_argument('--max-junctions',type=int,default=1);ap.add_argument('--seconds',type=float,default=20.)
    ap.add_argument('--seed',type=int,default=17)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/junction_arm_trim_candidates')
    args=ap.parse_args()
    if not 1<=args.max_junctions<=2 or not 1<=args.seconds<=20:raise ValueError('max-junctions 1..2; seconds 1..20')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must stay under Saved/Phase1')
    source=json.loads(args.document.read_text());terrain=REPO/'data/thanet/out/unreal/landscape'
    inputs=[args.document,Path(__file__),TOOLS/'phase1_qc.py']
    inputs += [TOOLS/'diag'/p for p in ('junction_trim_candidates.py','corner_quality_audit.py','road_body_quality.py')]
    inputs += list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs += [terrain/'landscape_manifest.json']+list(terrain.glob('hm_*.r16'))+list(terrain.glob('clip_*.r8'))
    config=dict(scope='bounded per-end geometry only',seconds=args.seconds,seed=args.seed,
        selected=sorted(set(args.junction)) if args.junction else None,numpy=np.__version__,scipy=scipy.__version__)
    identity,hashes=content_identity(inputs,config);root=args.out/args.document.stem/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        path=root/'state.json';survey=Heightfield.from_landscape_dir(str(terrain));survey.sampling='landscape_triangulated'
        if path.exists():
            state=json.loads(path.read_text())
            if state['fingerprint']!=identity:raise ValueError('arm checkpoint identity changed')
            for key in ('document','report','source_report'):
                if sha256(root/state[key])!=state[key+'_sha256']:raise ValueError('arm checkpoint missing/corrupt')
            data=json.loads((root/state['document']).read_text());report=json.loads((root/state['report']).read_text())
        else:
            data=copy.deepcopy(source);report=audit_document(args.document,survey)
            state=dict(status='pending',fingerprint=identity,input_sha256=hashes,config=config,phase1_accepted=False,
                attempts={},baseline_totals=report['totals'])
        verify_document(source,data)
        current={r['id']:metrics(r) for r in report['results']}
        selected=set(args.junction) if args.junction else {jid for jid,r in current.items() if r['status']!='passed'}
        if selected-set(current):raise ValueError('unknown junction selection')
        pending=sorted(selected-set(state['attempts']))
        def checkpoint():
            step=root/('step_%04d'%len(state['attempts']));doc_path=step/args.document.name;report_path=step/'report.json'
            atomic_json(doc_path,data);atomic_json(report_path,report)
            state.update(document=str(doc_path.relative_to(root)),document_sha256=sha256(doc_path),
                report=str(report_path.relative_to(root)),report_sha256=sha256(report_path),totals=report['totals'])
            if not state['attempts']:
                state.update(source_report=state['report'],source_report_sha256=state['report_sha256'])
            atomic_json(path,state)
        if not path.exists():checkpoint()
        source_metrics={r['id']:metrics(r) for r in json.loads((root/state['source_report']).read_text())['results']}
        for jid in pending[:args.max_junctions]:
            start=time.perf_counter();site=io_json.site_from_dict(data);ev=Evaluator(site,survey);plan=ev.plan()
            arms=plan.arms.get(jid,[])
            context=not arms or any(getattr(site.spline(a.spline_id).flags,k,False) for a in arms for k in ('bridge','tunnel','steps'))
            requests=None
            if current[jid]['status']=='passed':row=dict(status='already_passed')
            elif context:row=dict(status='needs_structure_or_connected_context')
            else:row,requests,after=search(ev,plan,current,jid,args.seconds,args.seed)
            if requests:
                proposal=copy.deepcopy(data);junction=next(j for j in proposal['junctions'] if j['id']==jid)
                values={(e['spline_id'],e['end']):e['trim_radius_m'] for e in requests}
                for end in junction['ends']:
                    key=(end['spline_id'],end['end'])
                    if key in values:end['trim_radius_m']=values[key]
                verify_document(source,proposal);trial_path=root/'trial.json';atomic_json(trial_path,proposal)
                checked=audit_document(trial_path,survey);full={r['id']:metrics(r) for r in checked['results']}
                if full!=after or regressions(current,full):raise ValueError('incremental/full arm geometry audit mismatch')
                # Compare every accumulated edit to the input, preventing small changes
                # from adding up across individually sub-tolerance proposals.
                body=compare_document(args.document,trial_path,survey)
                source_regressions=regressions(source_metrics,full)
                if source_regressions:row.update(status='rejected_input_junction_regression',regressions=source_regressions)
                elif body['regressions']:row.update(status='rejected_independent_body_regression',body=body)
                else:
                    body_path=root/('step_%04d'%(len(state['attempts'])+1))/'body_report.json';atomic_json(body_path,body)
                    row.update(status='geometry_candidate',body_report=str(body_path.relative_to(root)),body_report_sha256=sha256(body_path))
                    data=proposal;report=checked;current=full
            row['total_seconds']=round(time.perf_counter()-start,3);state['attempts'][jid]=row;checkpoint()
            print(jid,row['status'],row.get('evaluations',0),'evaluations',row['total_seconds'],'seconds',flush=True)
        if content_identity(inputs,config)[0]!=identity:raise ValueError('arm search inputs changed during run')
        remaining=selected-set(state['attempts']);state.update(status='pending' if remaining else 'complete',remaining=len(remaining))
        atomic_json(path,state)
        print(json.dumps(dict(state=str(path),status=state['status'],remaining=len(remaining),totals=state['totals'])))


if __name__=='__main__':main()
