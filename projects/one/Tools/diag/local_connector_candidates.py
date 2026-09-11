"""Bounded independent same-document continuation proposals; no network acceptance.

Checkpoint every pair, rank historical gaps only as hints, and measure current
emitted sections. A proposal must have a simple patch boundary, no fan overlap or
corner folds, no body regression, fixed opposite active end sections, and finished
A/B mesh seams. Full-document combination, terrain and native proof remain gates.
"""
import argparse,copy,json,sys,time
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
from diag.road_body_quality import mapped_top_stats,body_regressions
from diag.road_control_candidates import section_gaps
from diag.corner_quality_audit import pavement_top_stats
from diag.polygon_boundary_quality import boundary_quality,cross
from diag.restore_geometry_selection import apply_retained_connectors


def active_end_sections(sp,slot):
    active=np.flatnonzero(sp.active)
    if not len(active):raise ValueError('empty active road')
    i=active[0 if slot==0 else -1];left=1 if slot==0 else -1;parts={}
    for k,side in enumerate((left,-left)):
        parts['road_edge_'+str(k)]=(sp.frames.p[i]+side*sp.edge_offset(side)[i]*sp.frames.n[i]+sp.edge_height(side)[i]*sp.frames.b[i])[None,:]
        edge,_=build_edge(sp,side)
        for group in ('kerb','pavement'):
            indices=np.unique(edge.f[edge.group_mask_tris(exact=group)])
            indices=indices[np.abs(edge.vs[indices]-sp.s[i])<=1e-8];parts[group+'_'+str(k)]=edge.v[indices]
    parts['centre']=sp.frames.p[i:i+1]
    return parts


def body_stats(sp):
    road,_=build_road(sp);parts=dict(road=mapped_top_stats(road,'road'))
    if not parts['road']['surface_triangles']:raise ValueError('empty active road surface')
    for side in (-1,1):
        edge,_=build_edge(sp,side);parts['pavement_'+str(side)]=mapped_top_stats(edge,'pavement')
    return dict(status='fold_review' if any(v['folded_triangles'] for v in parts.values()) else 'passed',parts=parts)


def proposed_document(raw,pair,trim,cap):
    definitions={d['id']:d for d in raw['splines']};first=definitions[pair['ids'][0]];point=first['points'][0 if pair['ends'][0]==0 else -1]
    jid='connector:'+':'.join(sid.replace('roads:','') for sid in pair['ids'])
    addition=dict(id=jid,x=point['x'],y=point['y'],kind='connector',radius_m=.5,trim_radius_m=trim,corner_handle_frac=cap,
        ends=[dict(spline_id=sid,end='start' if slot==0 else 'end') for sid,slot in zip(pair['ids'],pair['ends'])])
    docs={pair['document']:raw};apply_retained_connectors(docs,{pair['document']:[addition]})
    return docs[pair['document']],addition


def evaluate(raw,pair,terrain,baseline,far_sections,trim,cap):
    candidate,addition=proposed_document(raw,pair,trim,cap);site=io_json.site_from_dict(candidate);plan=JunctionPlan(site);jid=addition['id']
    splines={sid:Spline(site.spline(sid),site,terrain,trim=plan.trim_for(sid)) for sid in pair['ids']}
    boundary=junction_boundary(plan,jid,splines)
    if boundary is None:raise ValueError('new connector has no boundary')
    simple=boundary_quality(boundary[0][:,:2]);q=boundary[0][:,:2]-np.array([addition['x'],addition['y']]);area=cross(q,np.roll(q,-1,axis=0))*.5
    overlap=float(max(0.,abs(area).sum()-abs(area.sum())))
    metrics=dict(boundary=simple,patch_overlap_area_m2=overlap)
    if not simple['simple'] or overlap>1e-4:return None,dict(metrics,reason='patch boundary or overlap')
    edge=MeshBuffer();info=build_junction_corners(plan,jid,splines,edge);pavement=pavement_top_stats(edge);metrics['corner']=dict(info,pavement=pavement)
    if info['skipped_incompatible'] or pavement['folded_top_triangles'] or pavement['inverted_top_triangles'] or any(np.min(c[4].b[:,2])<=0 for c in boundary[2]):
        return None,dict(metrics,reason='corner geometry')
    bodies={sid:body_stats(sp) for sid,sp in splines.items()};metrics['bodies']=bodies
    regressions={sid:body_regressions(baseline[sid],bodies[sid]) for sid in pair['ids']}
    if any(regressions.values()):return None,dict(metrics,reason='body regression',regressions=regressions)
    maximum=0.
    for sid,slot in zip(pair['ids'],pair['ends']):
        new=active_end_sections(splines[sid],1-slot);old=far_sections[sid]
        for part,points in old.items():
            if points.shape!=new[part].shape:return None,dict(metrics,reason='opposite active section coverage changed')
            if len(points):maximum=max(maximum,float(np.linalg.norm(points-new[part],axis=1).max()))
    metrics['opposite_active_section_movement_m']=maximum
    if maximum>1e-9:return None,dict(metrics,reason='opposite active section moved')
    # Rebuild finished owner buffers independently; filtered build explicitly
    # leaves other junctions for the complete-document integration gate.
    built=build_all(site,terrain,only_ids=pair['ids'],plan=plan);seams=junction_audit(plan,built);metrics['local_mesh_seams']=seams
    if seams['patches']!=1 or seams['worst_patch_gap_m']>1e-9 or seams['worst_corner_gap_m']>1e-9 or seams['corners_skipped_incompatible']:
        return None,dict(metrics,reason='finished mesh seam')
    return (candidate,addition),dict(metrics,reason='local_geometry_proposal')


def screen_pair(raw,pair,terrain,budget_s=15.):
    started=time.perf_counter();site=io_json.site_from_dict(raw);plan=JunctionPlan(site)
    splines={sid:Spline(site.spline(sid),site,terrain,trim=plan.trim_for(sid)) for sid in pair['ids']}
    baseline={sid:body_stats(sp) for sid,sp in splines.items()}
    far={sid:active_end_sections(splines[sid],1-slot) for sid,slot in zip(pair['ids'],pair['ends'])}
    sections=[active_end_sections(splines[sid],slot) for sid,slot in zip(pair['ids'],pair['ends'])]
    gaps=section_gaps(*sections)
    record=dict(pair=pair,before_bodies=baseline,actual_before_section_gaps_m=gaps,trials=[])
    if all(value is None or (isinstance(value,(float,int)) and value<=.05) for value in gaps.values()):
        return None,dict(record,status='current_gap_below_50mm',seconds=time.perf_counter()-started)
    for trim in (4.,6.,8.,10.,12.,2.,1.,.5,3.,5.,7.):
        for cap in (.45,.65,1.):
            if time.perf_counter()-started>budget_s:
                return None,dict(record,status='search_budget_exhausted',seconds=time.perf_counter()-started)
            try:
                proposal,metrics=evaluate(raw,pair,terrain,baseline,far,trim,cap)
            except ValueError as exc:proposal=None;metrics=dict(reason='geometry_error',error=str(exc))
            record['trials'].append(dict(trim_radius_m=trim,corner_handle_frac=cap,**metrics))
            if proposal is not None:
                candidate,addition=proposal
                record.update(status='local_geometry_proposal',addition=addition,seconds=time.perf_counter()-started,
                    remaining_gates=['complete-document and accumulated proposals','terrain contact','native rendering and transaction'])
                return candidate,record
    return None,dict(record,status='needs_geometry',seconds=time.perf_counter()-started)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--max-pairs',type=int,default=2);ap.add_argument('--pair-budget-s',type=float,default=15.)
    ap.add_argument('--source',type=Path,default=TOOLS.parent/'Saved/Phase1/connector_compositions/3b827be0962f2fbf0ae9')
    ap.add_argument('--inventory',type=Path,default=TOOLS.parent/'Saved/Phase1/local_connector_inventory.json')
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/local_connector_candidates');args=ap.parse_args()
    if not 1<=args.max_pairs<=4 or not 1<=args.pair_budget_s<=20:raise ValueError('bounded calls require 1..4 pairs and 1..20 seconds per pair')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('candidate output must stay under Saved/Phase1')
    inventory=json.loads(args.inventory.read_text(encoding='utf-8'));names=sorted({r['document'] for r in inventory['results']})
    docs={name:json.loads((args.source/name).read_text(encoding='utf-8')) for name in names};queue=[];held=[]
    for pair in inventory['results']:
        raw=docs[pair['document']];definitions={d['id']:d for d in raw['splines']};reason=[]
        bound={(e['spline_id'],e['end']) for j in raw['junctions'] for e in j['ends']}
        for sid,slot,other in zip(pair['ids'],pair['ends'],pair['ids'][::-1]):
            d=definitions[sid];end='start' if slot==0 else 'end';flags=d.get('flags') or {};profile=raw['profiles']['road'].get(d['profile_ids'].get('road'))
            if (sid,end) in bound or d.get('junction_'+end) is not None:reason.append('end_already_bound')
            if d.get('continues_from' if slot==0 else 'continues_to')!=other:reason.append('not_reciprocal')
            if flags.get('bridge') or flags.get('tunnel') or d.get('source',{}).get('cls')=='steps':reason.append('structure_or_steps')
            if not profile or profile.get('kind','road')!='road':reason.append('not_ordinary_road')
        if reason:held.append(dict(pair=pair,reasons=sorted(set(reason))))
        else:queue.append(pair)
    terrain_dir=REPO/'data/thanet/out/unreal/landscape'
    inputs=[Path(__file__),args.inventory,TOOLS/'phase1_qc.py']+[args.source/n for n in names]+list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs += [TOOLS/'diag'/n for n in ('road_body_quality.py','road_control_candidates.py','corner_quality_audit.py','polygon_boundary_quality.py','restore_geometry_selection.py')]
    inputs += [terrain_dir/'landscape_manifest.json']+list(terrain_dir.glob('hm_*.r16'))+list(terrain_dir.glob('clip_*.r8'))
    config=dict(scope='independent local connector screen; combination/terrain/native pending',pair_budget_s=args.pair_budget_s,numpy=np.__version__)
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        state_path=root/'state.json';state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else dict(status='pending',phase1_accepted=False,fingerprint=identity,input_sha256=hashes,config=config,total=len(queue),held=held,completed={})
        assert state['fingerprint']==identity
        for index,row in state['completed'].items():
            if sha256(root/row['report'])!=row['report_sha256']:raise ValueError('completed connector report changed')
            if row.get('candidate') and sha256(root/row['candidate'])!=row['candidate_sha256']:raise ValueError('completed connector document changed')
        terrain=Heightfield.from_landscape_dir(str(terrain_dir));terrain.sampling='landscape_triangulated';processed=0
        for index,pair in enumerate(queue):
            if str(index) in state['completed']:continue
            candidate,report=screen_pair(docs[pair['document']],pair,terrain,args.pair_budget_s)
            folder=root/f'pair_{index:05d}';folder.mkdir(parents=True,exist_ok=True);path=folder/'report.json';atomic_json(path,report)
            row=dict(report=str(path.relative_to(root)),report_sha256=sha256(path),status=report['status'])
            if candidate is not None:
                target=folder/pair['document'];atomic_json(target,candidate);row.update(candidate=str(target.relative_to(root)),candidate_sha256=sha256(target))
            state['completed'][str(index)]=row;atomic_json(state_path,state);processed+=1
            print(json.dumps(dict(index=index,ids=pair['ids'],status=report['status'],trials=len(report['trials']),seconds=round(report['seconds'],3))),flush=True)
            if processed>=args.max_pairs:break
        assert content_identity(inputs,config)[0]==identity
        state['status']='complete' if len(state['completed'])==len(queue) else 'pending';atomic_json(state_path,state)
        print(json.dumps(dict(root=str(root),completed=len(state['completed']),total=len(queue),proposals=sum(r['status']=='local_geometry_proposal' for r in state['completed'].values()))))


if __name__=='__main__':main()
