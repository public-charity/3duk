"""Bounded interior-bend proposals on unchanged source spline timelines.

Historical fold areas rank work only. Every road is measured on the current
selection. At most two child processes per call, 20 s search plus 15 s startup
allowance each; atomic per-trial/per-road evidence survives an interruption.
Local proposals still require combined full-document, terrain and visual gates.
"""
import argparse,copy,json,subprocess,sys,time
from pathlib import Path
import numpy as np
TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,sha256,content_identity,run_lock
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan
from streetscape.terrain import Heightfield
from streetscape.road import build_road,junction_boundary
from streetscape.edge import build_edge,build_junction_corners
from streetscape.mesh import MeshBuffer
from streetscape.build import build_all,junction_audit
from diag.local_connector_candidates import body_stats,active_end_sections
from diag.road_body_quality import body_regressions
from diag.corner_quality_audit import pavement_top_stats
from diag.polygon_boundary_quality import boundary_quality,cross


def folded_intervals(mesh,group):
    faces=mesh.f[mesh.group_mask_tris(exact=group)];tri=mesh.v[faces]
    sd=np.column_stack([mesh.vs,mesh.vd])[faces]
    a,b=sd[:,1]-sd[:,0],sd[:,2]-sd[:,0];param=cross(a,b)
    normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    folded=(abs(param)>1e-12)&(normal[:,2]*param<0)&(abs(normal[:,2])>1e-8)
    return [(float(v[:,0].min()),float(v[:,0].max()),float(np.linalg.norm(n)*.5))
            for v,n in zip(sd[folded],normal[folded])]


def fold_clusters(sp):
    road,_=build_road(sp);intervals=folded_intervals(road,'road')
    for side in (-1,1):
        edge,_=build_edge(sp,side);intervals+=folded_intervals(edge,'pavement')
    groups=[]
    for lo,hi,area in sorted(intervals):
        if groups and lo<=groups[-1]['hi']+1.:
            groups[-1]['hi']=max(groups[-1]['hi'],hi);groups[-1]['area_m2']+=area
        else:groups.append(dict(lo=lo,hi=hi,area_m2=area))
    return sorted(groups,key=lambda row:-row['area_m2'])


def basic_hold(raw,definition):
    flags=definition.get('flags') or {};profile=raw['profiles']['road'].get(definition['profile_ids'].get('road'))
    if any(flags.get(k) for k in ('bridge','tunnel','steps','closed_loop')) or definition['source'].get('cls')=='steps':return 'structure_steps_or_closed_loop'
    if not profile or profile.get('kind','road')!='road':return 'not_ordinary_road'
    if len(definition['points'])<3:return 'no_interior_control'
    return None


def unsupported_continuity(sp):
    return any(value for tl in sp.side_tl.values()
               for intervals in (tl.barrier_intervals,tl.embankment_intervals,tl.hedge_intervals)
               for _,_,value in intervals)


def total_fold(metrics):return sum(part['folded_area_m2'] for part in metrics['parts'].values())


def evaluate(current,sid,terrain,before,original_sp,addition):
    candidate=copy.deepcopy(current);candidate['junctions'].append(addition)
    site=io_json.site_from_dict(candidate);plan=JunctionPlan(site);jid=addition['id']
    sp=Spline(site.spline(sid),site,terrain,trim=plan.trim_for(sid));bodies=body_stats(sp)
    regressions=body_regressions(before,bodies)
    metrics=dict(after_body=bodies,original_station_array_exact=np.array_equal(original_sp.s,sp.s),
                 original_length_difference_m=float(abs(original_sp.length-sp.length)))
    if regressions or total_fold(bodies)>=total_fold(before)-1e-6:
        return None,dict(metrics,reason='no_fold_reduction_or_regression',regressions=regressions)
    if metrics['original_length_difference_m']>1e-9:raise ValueError('original timeline length changed')
    boundary=junction_boundary(plan,jid,{sid:sp})
    if boundary is None:raise ValueError('new bend has no boundary')
    simple=boundary_quality(boundary[0][:,:2]);q=boundary[0][:,:2]-[addition['x'],addition['y']]
    signed=cross(q,np.roll(q,-1,axis=0))*.5;overlap=float(max(0.,abs(signed).sum()-abs(signed.sum())))
    metrics.update(boundary=simple,patch_overlap_m2=overlap)
    if not simple['simple'] or overlap>1e-4:return None,dict(metrics,reason='patch_boundary_or_overlap')
    edge=MeshBuffer();corners=build_junction_corners(plan,jid,{sid:sp},edge);pavement=pavement_top_stats(edge)
    metrics['corner']=dict(corners,pavement=pavement)
    if corners['skipped_incompatible'] or pavement['folded_top_triangles'] or pavement['inverted_top_triangles'] or any(np.min(c[4].b[:,2])<=0 for c in boundary[2]):
        return None,dict(metrics,reason='corner_geometry')
    movement=0.
    for slot in (0,1):
        a,b=active_end_sections(original_sp,slot),active_end_sections(sp,slot)
        for key,v in a.items():
            if v.shape!=b[key].shape:raise ValueError('active endpoint coverage changed')
            movement=max(movement,float(np.linalg.norm(v-b[key],axis=1).max(initial=0)))
    metrics['endpoint_movement_m']=movement
    if movement>1e-9:return None,dict(metrics,reason='active_endpoint_moved')
    built=build_all(site,terrain,only_ids=[sid],plan=plan)
    selected=copy.copy(plan);selected.arms={jid:plan.arms[jid]};seams=junction_audit(selected,built)
    metrics['finished_mesh_seams']=seams
    if seams['patches']!=1 or seams['worst_patch_gap_m']>1e-9 or seams['worst_corner_gap_m']>1e-9 or seams['corners_skipped_incompatible']:
        return None,dict(metrics,reason='finished_mesh_seam')
    return candidate,dict(metrics,reason='local_geometry_proposal')


def screen_road(raw,sid,terrain,budget_s=20.,checkpoint=None):
    started=time.perf_counter();definition=next(d for d in raw['splines'] if d['id']==sid)
    record=dict(status='running',spline=sid,name=definition['source'].get('name'),trials=[],additions=[])
    hold=basic_hold(raw,definition)
    if hold:return None,dict(record,status='held',reason=hold)
    site=io_json.site_from_dict(raw);plan=JunctionPlan(site)
    original_sp=Spline(site.spline(sid),site,terrain,trim=plan.trim_for(sid))
    before=body_stats(original_sp);record['before_body']=before
    if before['status']=='passed':return None,dict(record,status='current_body_passed')
    if unsupported_continuity(original_sp):return None,dict(record,status='held',reason='barrier_hedge_or_support_continuity_unproved')
    current=copy.deepcopy(raw);sp=original_sp;baseline=before
    pts,_,_,knots,*_=plan._curve(sid)
    used={j['id'] for j in raw['junctions']};stop='maximum_three_bends'
    for _ in range(3):
        clusters=fold_clusters(sp)
        if not clusters:stop='all_body_folds_removed';break
        choices=[]
        for cluster in clusters:
            near=[i for i in range(1,len(knots)-1) if cluster['lo']-2<=knots[i]<=cluster['hi']+2]
            if not near:continue
            i=min(near,key=lambda i:abs(knots[i]-(cluster['lo']+cluster['hi'])*.5))
            raw_index=next(k for k,p in enumerate(definition['points']) if p['x']==pts[i].x and p['y']==pts[i].y)
            jid='bend:'+sid.removeprefix('roads:')+':'+str(raw_index)
            if jid not in used:choices.append((cluster,i,raw_index,jid))
        if not choices:stop='no_unmasked_interior_control_near_fold';break
        cluster,i,raw_index,jid=choices[0];station=float(knots[i]);found=False
        extent=max(float(np.interp(station,sp.s,sp.edge_offset(side)+sp.side_spec[side].kerb_width+sp.side_spec[side].pavement_width)) for side in (-1,1))
        radii=sorted(set(round(max(1.,min(16.,v)),3) for v in (extent*.8,extent+1.,extent*1.5,extent*2.)))
        for radius in radii:
            lower=np.flatnonzero(original_sp.s<=min(station-radius,cluster['lo']-.25))
            upper=np.flatnonzero(original_sp.s>=max(station+radius,cluster['hi']+.25))
            if not len(lower) or not len(upper):continue
            lo,hi=map(float,(original_sp.s[lower[-1]],original_sp.s[upper[0]]))
            for cap in (.65,.45,1.):
                if time.perf_counter()-started>budget_s:stop='search_budget_exhausted';break
                addition=dict(id=jid,kind='bend',x=pts[i].x,y=pts[i].y,corner_handle_frac=cap,
                    ends=[dict(spline_id=sid,end='end',station_m=lo),dict(spline_id=sid,end='start',station_m=hi)])
                try:proposal,metrics=evaluate(current,sid,terrain,baseline,original_sp,addition)
                except ValueError as exc:proposal=None;metrics=dict(reason='geometry_error',error=str(exc))
                record['trials'].append(dict(control=raw_index,radius_m=radius,corner_handle_frac=cap,stations_m=[lo,hi],**metrics))
                record['seconds']=round(time.perf_counter()-started,3)
                if proposal is not None:
                    current=proposal;record['additions'].append(addition);used.add(jid);baseline=metrics['after_body']
                    newsite=io_json.site_from_dict(current);newplan=JunctionPlan(newsite)
                    sp=Spline(newsite.spline(sid),newsite,terrain,trim=newplan.trim_for(sid));found=True
                if checkpoint:checkpoint(record)
                if found:break
            if found or stop=='search_budget_exhausted':break
        if not found:
            if stop!='search_budget_exhausted':stop='trial_set_exhausted'
            break
    record.update(status='local_geometry_proposal' if record['additions'] else 'needs_geometry',stop_reason=stop,
        after_body=baseline,seconds=round(time.perf_counter()-started,3),
        remaining_gates=['combined complete document','required new-corner ground contact','actual mesh visual and native risk sample'])
    return (current if record['additions'] else None),record


def worker(request_path):
    request=json.loads(request_path.read_text(encoding='utf-8'));folder=request_path.parent
    terrain=Heightfield.from_landscape_dir(request['terrain']);terrain.sampling='landscape_triangulated'
    raw=json.loads(Path(request['source']).read_text(encoding='utf-8'))
    candidate,report=screen_road(raw,request['spline'],terrain,request['budget_s'],lambda r:atomic_json(folder/'progress.json',r))
    if candidate is not None:
        target=folder/Path(request['source']).name;atomic_json(target,candidate)
        report.update(candidate=target.name,candidate_sha256=sha256(target))
    atomic_json(folder/'report.json',report)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--worker',type=Path)
    ap.add_argument('--manifest',type=Path,default=TOOLS.parent/'docs/checkpoints/phase1_42_geometry_selection.json')
    ap.add_argument('--inventory',type=Path,default=TOOLS.parent/'Saved/Phase1/road_surface_fold_inventory.json')
    ap.add_argument('--max-roads',type=int,default=2);ap.add_argument('--road-budget-s',type=float,default=20.)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/internal_bend_candidates');args=ap.parse_args()
    if args.worker:worker(args.worker);return
    if not 1<=args.max_roads<=2 or not 1<=args.road_budget_s<=20:raise ValueError('require 1..2 roads and 1..20 search seconds')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must remain under Saved/Phase1')
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'));source=Path(manifest['source_candidate'])
    docs={};queue=[];held=[]
    for row in sorted(json.loads(args.inventory.read_text(encoding='utf-8'))['results'],key=lambda r:(-r['folded_area_m2'],r['id'])):
        name=row['document']
        if name not in docs:
            if sha256(source/name)!=manifest['document_sha256'][name]:raise ValueError('selected source changed: '+name)
            docs[name]=json.loads((source/name).read_text(encoding='utf-8'))
        definition=next(d for d in docs[name]['splines'] if d['id']==row['id'])
        reason=basic_hold(docs[name],definition)
        record=dict(document=name,id=row['id'],historical_fold_area_m2=row['folded_area_m2'])
        if reason:held.append(dict(record,reason=reason))
        else:queue.append(record)
    terrain=REPO/'data/thanet/out/unreal/landscape'
    inputs=[Path(__file__),args.manifest,args.inventory,TOOLS/'phase1_qc.py']+[source/name for name in docs]
    inputs+=list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs += [TOOLS/'diag'/name for name in ('local_connector_candidates.py','road_body_quality.py','road_control_candidates.py',
        'corner_quality_audit.py','polygon_boundary_quality.py','restore_geometry_selection.py')]
    inputs += [terrain/'landscape_manifest.json']+list(terrain.glob('hm_*.r16'))+list(terrain.glob('clip_*.r8'))
    config=dict(scope='bounded independent interior bend proposals',road_budget_s=args.road_budget_s,process_timeout_s=args.road_budget_s+15,numpy=np.__version__,queue=queue)
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        state_path=root/'state.json'
        state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else dict(status='pending',phase1_accepted=False,
            fingerprint=identity,input_sha256=hashes,config=config,total=len(queue),held=held,completed={})
        if state['fingerprint']!=identity:raise ValueError('search fingerprint mismatch')
        for row in state['completed'].values():
            if sha256(root/row['report'])!=row['report_sha256']:raise ValueError('stored road report changed')
            if row.get('candidate') and sha256(root/row['candidate'])!=row['candidate_sha256']:raise ValueError('stored candidate changed')
        atomic_json(state_path,state);processed=0
        for index,row in enumerate(queue):
            if str(index) in state['completed']:continue
            road_root=root/f'road_{index:05d}';road_root.mkdir(exist_ok=True)
            folder=road_root/f'attempt_{len(list(road_root.glob("attempt_*")))+1:03d}';folder.mkdir()
            request=folder/'request.json';atomic_json(request,dict(source=str(source/row['document']),spline=row['id'],terrain=str(terrain),budget_s=args.road_budget_s))
            with (folder/'worker.log').open('w',encoding='utf-8') as log:
                try:
                    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(request.resolve())],stdout=log,stderr=subprocess.STDOUT,
                        timeout=config['process_timeout_s'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if result.returncode:raise ValueError('worker failed with exit '+str(result.returncode))
                    report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
                except (subprocess.TimeoutExpired,ValueError) as exc:
                    report=dict(status='worker_timeout' if isinstance(exc,subprocess.TimeoutExpired) else 'worker_failed',error=str(exc),spline=row['id'])
                    atomic_json(folder/'report.json',report)
            record=dict(status=report['status'],report=str((folder/'report.json').relative_to(root)),report_sha256=sha256(folder/'report.json'))
            if report.get('candidate'):
                record.update(candidate=str((folder/report['candidate']).relative_to(root)),candidate_sha256=report['candidate_sha256'])
            state['completed'][str(index)]=record;atomic_json(state_path,state);processed+=1
            print(json.dumps(dict(index=index,spline=row['id'],status=report['status'],additions=len(report.get('additions',[])),seconds=report.get('seconds'))),flush=True)
            if processed>=args.max_roads:break
        if content_identity(inputs,config)[0]!=identity:raise ValueError('inputs changed during search')
        state['status']='complete' if len(state['completed'])==len(queue) else 'pending';atomic_json(state_path,state)
        print(json.dumps(dict(root=str(root),completed=len(state['completed']),total=len(queue))))


if __name__=='__main__':main()
