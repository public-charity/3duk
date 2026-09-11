"""Bounded source-control cleanup, preserving endpoints and measured neighbours.

Only redundant interior controls within 0.1 m may be removed. Road/junction IDs,
all retained point dictionaries and all other document data are preserved. The
ignored historical _z_06 note stays recoverable in the hashed original source.
No junction arms, structures, steps, loops or explicit height/roll pins are edited.
Every retained body must pass, with <=50 mm curve/length change and no increased
continuation kerb/pavement gap. Full composition verification is still required.
"""
import argparse,copy,json,re,sys,time
from pathlib import Path
from collections import Counter
import numpy as np
from scipy.spatial import cKDTree
TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,content_identity,sha256,run_lock
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan,catmull_rom_dense
from streetscape.terrain import Heightfield
from streetscape.edge import build_edge
from diag.road_surface_census import measure_surface
from diag.road_body_quality import body_regressions


def retained_indices(points,tolerance):
    if not 0<tolerance<=.1:raise ValueError('control tolerance must be within (0,0.1] m')
    p=np.array([[q['x'],q['y']] for q in points]);keep=[0]
    if len(p)<2 or not np.all(np.isfinite(p)):raise ValueError('invalid controls')
    for i in range(1,len(p)-1):
        if np.linalg.norm(p[i]-p[keep[-1]])>=tolerance:keep.append(i)
    while len(keep)>1 and np.linalg.norm(p[-1]-p[keep[-1]])<tolerance:keep.pop()
    return keep+[len(p)-1]


def semantic_reasons(definition,keep,bound_ids=()):
    d=definition;reasons=[];flags=d.get('flags') or {};points=d['points']
    if any(type(i) is not int for i in keep) or len(keep)<2 or keep!=sorted(set(keep)) or keep[0]!=0 or keep[-1]!=len(points)-1:
        return ['selection must preserve ordered original endpoints']
    if d['id'] in bound_ids or d.get('junction_start') or d.get('junction_end'):reasons.append('junction arm')
    if not d['profile_ids'].get('road') or (d.get('source') or {}).get('layer')!='roads':reasons.append('not ordinary road')
    if any(flags.get(k) for k in ('bridge','tunnel','steps','closed_loop')):reasons.append('structure/steps/loop')
    if any(p.get(k) is not None for p in points for k in ('z','roll_deg')):reasons.append('explicit height/roll')
    attrs=[{k:v for k,v in p.items() if k not in ('x','y','_z_06')} for p in points]
    for a,b in zip(keep,keep[1:]):
        if b>a+1 and any(attrs[i]!=attrs[a] or attrs[i]!=attrs[b] for i in range(a+1,b)):
            reasons.append('distinct point semantics');break
    return reasons


def verify_document(source,candidate,selections):
    """Exact source preservation, except explicitly selected original controls."""
    if set(source)!=set(candidate) or any(source[k]!=candidate[k] for k in source if k!='splines'):
        raise ValueError('candidate changed source outside selected controls')
    if len(source['splines'])!=len(candidate['splines']):raise ValueError('candidate changed spline coverage')
    found=set();bound={e['spline_id'] for j in source['junctions'] for e in j['ends']}
    for d,other in zip(source['splines'],candidate['splines']):
        expected=d
        if d['id'] in selections:
            keep=selections[d['id']];found.add(d['id']);reasons=semantic_reasons(d,keep,bound)
            if reasons:raise ValueError('invalid retained controls: '+str(reasons))
            if not any(retained_indices(d['points'],tol)==keep for tol in (.025,.05,.1)):
                raise ValueError('selection is not a bounded redundant-control removal')
            expected=dict(d,points=[d['points'][i] for i in keep])
        if expected!=other:raise ValueError('candidate changed source outside selected controls')
    if found!=set(selections):raise ValueError('candidate changed source outside selected controls')


def directed_distance_bound(a,b,step=.01):
    """Certified polyline distance upper bound, using exact nearest segments.

    Distance-to-set is 1-Lipschitz, so a half-sample-spacing term bounds the
    unsampled intervals. KD-tree candidates are expanded whenever the distance
    to an omitted segment cannot be proved larger than the current best.
    """
    if step<=0:raise ValueError('positive sampling step required')
    a,b=[np.asarray(p,dtype=float) for p in (a,b)]
    if any(p.ndim!=2 or p.shape[1]!=2 or len(p)<2 or not np.all(np.isfinite(p)) for p in (a,b)):
        raise ValueError('finite planar polylines required')
    delta=np.diff(a,axis=0);length=np.linalg.norm(delta,axis=1);count=np.maximum(1,np.ceil(length/step).astype(int))
    points=np.vstack([x+np.arange(n)[:,None]/n*d for x,d,n in zip(a[:-1],delta,count)]+[a[-1:]])
    starts=b[:-1];vec=np.diff(b,axis=0);square=np.einsum('ij,ij->i',vec,vec)
    if np.any(square<=0):raise ValueError('duplicate dense-polyline vertex')
    mid=(b[:-1]+b[1:])*.5;tree=cKDTree(mid);half=float(np.sqrt(square).max()*.5)
    k=min(8,len(mid));distance,index=tree.query(points,k=k)
    if k==1:distance=distance[:,None];index=index[:,None]
    rel=points[:,None,:]-starts[index]
    t=np.clip(np.einsum('nki,nki->nk',rel,vec[index])/square[index],0,1)
    best=np.linalg.norm(rel-t[:,:,None]*vec[index],axis=2).min(axis=1)
    uncertain=np.flatnonzero(distance[:,-1]-half<=best+1e-12) if k<len(mid) else []
    for i in uncertain:
        ix=np.array(tree.query_ball_point(points[i],float(best[i]+half+1e-12)))
        rel=points[i]-starts[ix];t=np.clip(np.einsum('ij,ij->i',rel,vec[ix])/square[ix],0,1)
        best[i]=np.linalg.norm(rel-t[:,None]*vec[ix],axis=1).min()
    return float(best.max()+np.max(length/count)*.5)


def curve_bound(a,b):
    curves=[catmull_rom_dense(np.array([[p['x'],p['y']] for p in points]))[1] for points in (a,b)]
    return max(directed_distance_bound(*curves),directed_distance_bound(*curves[::-1]))


def endpoint_sections(sp,slot):
    """Actual B kerb/pavement endpoint vertices, plus the shared road kerb line."""
    i=0 if slot==0 else -1;left=1 if slot==0 else -1;parts={}
    for k,side in enumerate((left,-left)):
        parts['road_edge_'+str(k)]=(sp.frames.p[i]+side*sp.edge_offset(side)[i]*sp.frames.n[i]+sp.edge_height(side)[i]*sp.frames.b[i])[None,:]
        edge,_=build_edge(sp,side)
        for group in ('kerb','pavement'):
            indices=np.unique(edge.f[edge.group_mask_tris(exact=group)])
            indices=indices[np.abs(edge.vs[indices]-sp.s[i])<=1e-8]
            parts[group+'_'+str(k)]=edge.v[indices]
    parts['centre']=np.array([[sp.xy[i,0],sp.xy[i,1],sp.z_ref[i]]])
    return parts


def section_gaps(a,b):
    results={}
    for key,points in a.items():
        other_key=key[:-1]+str(1-int(key[-1])) if key[-1] in '01' else key
        other=b[other_key]
        if not len(points) or not len(other):
            results[key]=None if len(points)==len(other) else 'section_mismatch';continue
        distance=np.linalg.norm(points[:,None,:]-other[None,:,:],axis=2)
        results[key]=float(max(distance.min(axis=0).max(),distance.min(axis=1).max()))
    return results


def seam_regressions(before,after):
    if set(before)!=set(after):return ['continuation coverage changed']
    reasons=[]
    for key,a in before.items():
        b=after[key]
        if isinstance(a,(float,int)) and isinstance(b,(float,int)):
            if b>a+1e-6:reasons.append(key+' gap increased')
        elif a!=b:reasons.append(key+' section changed')
    return reasons


def load_completed(root,state):
    for row in state['attempts'].values():
        path=root/row['report']
        if not path.exists() or sha256(path)!=row['report_sha256']:raise ValueError('candidate checkpoint report missing/corrupt')
    for row in state['documents'].values():
        path=root/row['path']
        if not path.exists() or sha256(path)!=row['sha256']:raise ValueError('candidate checkpoint document missing/corrupt')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--streetscape',type=Path,required=True)
    ap.add_argument('--census',type=Path,required=True);ap.add_argument('--max-splines',type=int,default=8)
    ap.add_argument('--spline',action='append');ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/road_control_candidates')
    args=ap.parse_args()
    if not 1<=args.max_splines<=16:raise ValueError('max-splines must be 1..16')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must stay under Saved/Phase1')
    paths=sorted(p for p in args.streetscape.glob('site_x*_y*.json') if re.fullmatch(r'site_x-?\d+_y-?\d+\.json',p.name))
    census=json.loads((args.census/'state.json').read_text(encoding='utf-8'))
    if census['status']!='complete' or set(census['documents'])!={p.name for p in paths}:raise ValueError('complete baseline census required')
    inputs=paths+[Path(__file__),args.census/'state.json',TOOLS/'phase1_qc.py',TOOLS/'diag/road_body_quality.py',TOOLS/'diag/road_surface_census.py']
    inputs+=list((TOOLS/'blender/streetscape').glob('*.py'))
    terrain=REPO/'data/thanet/out/unreal/landscape'
    inputs+=[terrain/'landscape_manifest.json']+list(terrain.glob('hm_*.r16'))+list(terrain.glob('clip_*.r8'))
    config=dict(scope='unbound ordinary roads; redundant controls; complete bodies and continuation sections',splines=sorted(args.spline or []),numpy=np.__version__)
    identity,hashes=content_identity(inputs,config)
    expected={Path(k).resolve():v for k,v in census['input_sha256'].items()}
    for p,digest in hashes.items():
        key=Path(p).resolve()
        if key in expected and expected[key]!=digest:raise ValueError('census source/core/terrain is stale: '+p)
    docs={p.name:json.loads(p.read_text(encoding='utf-8')) for p in paths}
    locations={};definitions={};bound={e['spline_id'] for raw in docs.values() for j in raw['junctions'] for e in j['ends']}
    for name,raw in docs.items():
        for d in raw['splines']:
            if d['id'] in definitions:raise ValueError('duplicate source spline ID')
            locations[d['id']]=name;definitions[d['id']]=d
    baselines={};selected={}
    for name,row in census['documents'].items():
        path=args.census/(Path(name).stem+'.report.json')
        if sha256(path)!=row['report_sha256']:raise ValueError('baseline report missing/corrupt')
        report=json.loads(path.read_text(encoding='utf-8'))
        if {r['id'] for r in report['results']}!={d['id'] for d in docs[name]['splines']}:raise ValueError('baseline coverage differs')
        for result in report['results']:
            sid=result['id'];baselines[sid]=result
            if result['status']!='fold_review' or result['kind']!='road':continue
            if args.spline and sid not in args.spline:continue
            trials=[];seen=set()
            for tol in (.025,.05,.1):
                keep=retained_indices(definitions[sid]['points'],tol)
                if len(keep)==len(definitions[sid]['points']) or tuple(keep) in seen:continue
                seen.add(tuple(keep))
                if not semantic_reasons(definitions[sid],keep,bound):trials.append(dict(tolerance_m=tol,retained_indices=keep))
            if trials:selected[sid]=trials
    if args.spline and set(args.spline)-set(selected):raise ValueError('requested spline is not eligible')
    selected=dict(sorted(selected.items(),key=lambda r:(-sum(p['folded_area_m2'] for p in baselines[r[0]]['parts'].values()),r[0])))
    root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        state_path=root/'state.json'
        state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else dict(status='pending',phase1_accepted=False,
            fingerprint=identity,input_sha256=hashes,config=config,source=str(args.streetscape),attempts={},documents={},selections={})
        if state['fingerprint']!=identity or set(state['attempts'])-set(selected):raise ValueError('candidate checkpoint identity changed')
        load_completed(root,state);current_docs=dict(docs)
        for name,row in state['documents'].items():current_docs[name]=json.loads((root/row['path']).read_text(encoding='utf-8'))
        for name in state['documents']:
            verify_document(docs[name],current_docs[name],{sid:k for sid,k in state['selections'].items() if locations[sid]==name})
        survey=Heightfield.from_landscape_dir(str(terrain));survey.sampling='landscape_triangulated'
        cache={};contexts={}
        def spline(sid,original=False):
            name=locations[sid];raw=docs[name] if original else current_docs[name];digest=sha256_json(raw);key=(sid,digest)
            if key not in cache:
                if digest not in contexts:
                    site=io_json.site_from_dict(raw);contexts[digest]=(site,JunctionPlan(site))
                site,plan=contexts[digest]
                cache[key]=Spline(site.spline(sid),site,survey,trim=plan.trim_for(sid))
            return cache[key]
        for sid,trials in [(sid,t) for sid,t in selected.items() if sid not in state['attempts']][:args.max_splines]:
            started=time.perf_counter();name=locations[sid];old=spline(sid);initial=spline(sid,True);results=[];retained=None
            for request in trials:
                proposal=dict(current_docs[name]);proposal['splines']=list(proposal['splines'])
                index=next(i for i,d in enumerate(proposal['splines']) if d['id']==sid)
                d=dict(proposal['splines'][index]);proposal['splines'][index]=d
                keep=request['retained_indices'];d['points']=[definitions[sid]['points'][i] for i in keep]
                choices=dict(state['selections'],**{sid:keep});verify_document(docs[name],proposal,{s:k for s,k in choices.items() if locations[s]==name})
                site=io_json.site_from_dict(proposal);plan=JunctionPlan(site);after=measure_surface(site,sid,survey,plan)
                reasons=body_regressions(baselines[sid],after)
                if after['status']!='passed':reasons.append('target remains folded')
                trial=dict(request=request,after=after,hold_reasons=reasons)
                if not reasons:
                    sp=Spline(site.spline(sid),site,survey,trim=plan.trim_for(sid))
                    trial['dense_polyline_hausdorff_upper_bound_m']=curve_bound(definitions[sid]['points'],d['points'])
                    trial['length_change_m']=sp.length-initial.length
                    if trial['dense_polyline_hausdorff_upper_bound_m']>.05:reasons.append('curve deviation over 50 mm')
                    if abs(trial['length_change_m'])>.05:reasons.append('length change over 50 mm')
                    joins=[]
                    for slot,key in enumerate(('continues_from','continues_to')):
                        other=definitions[sid].get(key)
                        if not other:continue
                        matches=[i for i,k in enumerate(('continues_from','continues_to')) if definitions.get(other,{}).get(k)==sid]
                        if len(matches)!=1:reasons.append('missing/nonreciprocal continuation');continue
                        nslot=matches[0];neighbour=spline(other);original_neighbour=spline(other,True)
                        neighbour_section=endpoint_sections(neighbour,nslot)
                        values=[section_gaps(endpoint_sections(x,slot),y) for x,y in (
                            (initial,endpoint_sections(original_neighbour,nslot)),(old,neighbour_section),(sp,neighbour_section))]
                        join=dict(other=other,end=slot,other_end=nslot,source=values[0],before=values[1],after=values[2]);joins.append(join)
                        reasons.extend(seam_regressions(values[0],values[2])+seam_regressions(values[1],values[2]))
                    trial['continuations']=joins
                    if not reasons:retained=proposal
                results.append(trial)
                if retained is not None:break
            step=root/('step_%05d'%len(state['attempts']));report_path=step/'report.json'
            result=dict(id=sid,document=name,source_body=baselines[sid],trials=results,status='geometry_candidate' if retained is not None else 'held',seconds=round(time.perf_counter()-started,3))
            atomic_json(report_path,result)
            if retained is not None:
                path=step/name;atomic_json(path,retained);current_docs[name]=retained
                state['documents'][name]=dict(path=str(path.relative_to(root)),sha256=sha256(path))
                state['selections'][sid]=results[-1]['request']['retained_indices']
            state['attempts'][sid]=dict(status=result['status'],report=str(report_path.relative_to(root)),report_sha256=sha256(report_path))
            atomic_json(state_path,state)
            print(sid,result['status'],result['seconds'],'seconds',flush=True)
        if content_identity(inputs,config)[0]!=identity:raise ValueError('candidate inputs changed during work')
        state.update(status='complete' if len(state['attempts'])==len(selected) else 'pending',completed=len(state['attempts']),total=len(selected),retained=len(state['selections']))
        atomic_json(state_path,state)
        print(json.dumps(dict(state=str(state_path),**{k:state[k] for k in ('status','completed','total','retained')})))


def sha256_json(raw):
    import hashlib
    return hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()


if __name__=='__main__':main()
