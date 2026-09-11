"""Checkpointed Thanet width candidates from explicit lane evidence and joined ends.

This prepares complete documents under Saved/Phase1. It does not accept geometry,
change survey data, or write production documents. Every continuation component
is kept together; missing evidence, width transitions and structures need review.
"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import time

TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path.insert(0,str(TOOLS))
from phase1_qc import atomic_json,content_identity,sha256,run_lock
from diag.path_crossing_candidate import lane_width_candidate
from diag.structure_inventory import read_osm_way_tags


def width_components(definitions,tags,tuning):
    """Partition direct continuations; identify evidence-backed reductions only."""
    by_id={d['id']:d for d in definitions}
    if len(by_id)!=len(definitions):raise ValueError('duplicate source width ID')
    links={sid:set() for sid in by_id}
    for sid,d in by_id.items():
        for key in ('continues_from','continues_to'):
            neighbour=d.get(key)
            if neighbour in links:links[sid].add(neighbour);links[neighbour].add(sid)
    def inferred(d):
        t=tags.get(d['source']['osm_id'],{})
        count=t.get('lanes','')
        if t.get('oneway')!='yes' or count not in ('1','2','3','4') or 'width' in t:return None
        q=float(tuning['width_quantum_m'])
        return round((int(count)*float(tuning['lane_width_m'])+float(tuning['lane_margin_m']))/q)*q
    seen=set();rows=[]
    for sid in sorted(by_id):
        if sid in seen:continue
        todo=[sid];group=[];seen.add(sid)
        while todo:
            here=todo.pop();group.append(here)
            for other in sorted(links[here]):
                if other not in seen:seen.add(other);todo.append(other)
        group.sort();widths={i:inferred(by_id[i]) for i in group}
        reductions=[i for i in group if widths[i] is not None and widths[i]<min(p['width_m'] for p in by_id[i]['points'])-1e-6]
        if not reductions:continue
        reasons=[]
        for i in group:
            d=by_id[i]
            if widths[i] is None:reasons.append(i+': missing compatible explicit lane evidence')
            elif widths[i]>min(p['width_m'] for p in d['points'])+1e-6:reasons.append(i+': would widen another fragment')
            if any((d.get('flags') or {}).get(k) for k in ('bridge','tunnel','steps')):reasons.append(i+': structure or steps')
        if not reasons:
            # Reuse the actual candidate preflight on a private minimal copy.
            profiles={d['profile_ids']['road']:{'markings':[]} for d in (by_id[i] for i in group)}
            temporary={'splines':copy.deepcopy([by_id[i] for i in group]),'profiles':{'road':profiles}}
            try:lane_width_candidate(temporary,group,tags,tuning)
            except ValueError as exc:reasons.append(str(exc))
        rows.append(dict(id=group[0],ids=group,reductions=reductions,
            status='needs_context' if reasons else 'candidate',reasons=reasons,inferred_widths_m=widths))
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--max-docs',type=int,default=8)
    ap.add_argument('--hold-groups',type=Path,help='JSON decision file with a groups list; keeps complete components at source widths')
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/connected_width_candidates')
    args=ap.parse_args()
    if not 1<=args.max_docs<=32:raise ValueError('max-docs must be 1..32')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('candidate output must stay under Saved/Phase1')
    source=REPO/'data/thanet/out/unreal/streetscape';paths=sorted(source.glob('site_x*_y*.json'))
    if not paths:raise ValueError('no source documents; empty coverage is not a candidate')
    osm=REPO/'data/thanet/raw/thanet.osm';tuning_path=REPO/'sources/config/tuning.json'
    inputs=paths+[osm,tuning_path,Path(__file__),TOOLS/'phase1_qc.py',TOOLS/'diag/path_crossing_candidate.py',TOOLS/'diag/structure_inventory.py']
    config=dict(site='thanet',scope='complete-document data candidates; geometry not accepted',model='explicit one-way lanes with complete reciprocal continuations')
    held=[]
    if args.hold_groups:
        decision=json.loads(args.hold_groups.read_text());held=decision.get('groups')
        if not isinstance(held,list) or any(not isinstance(i,str) for i in held) or len(set(held))!=len(held):
            raise ValueError('hold decision must contain unique string group IDs')
        held=sorted(held);inputs.append(args.hold_groups);config['held_groups']=held
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        started=time.time();state_path=root/'state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else dict(status='running',fingerprint=identity,
            input_sha256=hashes,config=config,phase1_accepted=False,documents={})
        if state['fingerprint']!=identity:raise ValueError('width candidate identity changed')
        pending=[]
        for path in paths:
            record=state['documents'].get(path.name);candidate=root/path.name
            if not record or not candidate.exists() or sha256(candidate)!=record['sha256']:
                state['documents'].pop(path.name,None);pending.append(path)
        state['status']='running';atomic_json(state_path,state)
        catalogue_path=root/'catalogue.json'
        catalogue_ok=catalogue_path.exists() and sha256(catalogue_path)==state.get('catalogue_sha256')
        if pending or not catalogue_ok:
            docs={p.name:json.loads(p.read_text()) for p in paths}
            definitions=[d for raw in docs.values() for d in raw['splines'] if d['source']['layer']=='roads' and d['profile_ids'].get('road')]
            tags=read_osm_way_tags(osm,{d['source']['osm_id'] for d in definitions})
            tuning=json.loads(tuning_path.read_text())['roads'];groups=width_components(definitions,tags,tuning)
            eligible={g['id'] for g in groups if g['status']=='candidate'}
            if set(held)-eligible:raise ValueError('hold decision contains unknown or ineligible width groups')
            for group in groups:
                if group['id'] in held:
                    group['status']='held_for_geometry';group['reasons'].append('held by geometry comparison: '+str(args.hold_groups))
            selected=sorted(i for g in groups if g['status']=='candidate' for i in g['ids'])
            road_profiles={}
            for raw in docs.values():
                for key,profile in raw['profiles']['road'].items():
                    if key in road_profiles and road_profiles[key]!=profile:raise ValueError('conflicting source road profile: '+key)
                    road_profiles[key]=profile
            models=lane_width_candidate({'splines':definitions,'profiles':{'road':road_profiles}},selected,tags,tuning)
            selected=set(selected)
            catalogue=dict(status='candidate',phase1_accepted=False,groups=groups,
                totals=dict(Counter(g['status'] for g in groups)),selected_splines=len(selected),models=models)
            atomic_json(root/'catalogue.json',catalogue)
            for path in pending[:args.max_docs]:
                raw=docs[path.name];changed=[d['id'] for d in raw['splines'] if d['id'] in selected]
                for d in raw['splines']:
                    if d['id'] in selected:
                        pid=d['profile_ids']['road'];raw['profiles']['road'][pid]=road_profiles[pid]
                if changed:atomic_json(root/path.name,raw)
                else:(root/path.name).write_bytes(path.read_bytes())
                state['documents'][path.name]=dict(sha256=sha256(root/path.name),changed_ids=changed)
                atomic_json(state_path,state)
                print(path.name,len(changed),'modelled widths',flush=True)
            state['catalogue_sha256']=sha256(root/'catalogue.json')
            state['width_groups']=catalogue['totals'];state['selected_splines']=len(selected)
        if content_identity(inputs,config)[0]!=identity:raise ValueError('width candidate source changed during run')
        state.update(status='complete' if len(state['documents'])==len(paths) else 'pending',completed=len(state['documents']),total=len(paths))
        atomic_json(state_path,state)
        print(json.dumps(dict(state=str(state_path),status=state['status'],completed=state['completed'],total=state['total'],
            groups=state.get('width_groups'),selected_splines=state.get('selected_splines'),seconds=round(time.time()-started,3))))


if __name__=='__main__':main()
