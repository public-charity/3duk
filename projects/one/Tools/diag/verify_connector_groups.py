"""Combine a frozen connector-screen snapshot, then verify whole documents.

Each invocation verifies at most two documents. Existing retained joins remain
protected. Failed combinations stay held for diagnosis; no per-pair green label
can promote a combined document without these complete mesh checks.
"""
import argparse,json,sys,time
from pathlib import Path
from collections import Counter
TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,sha256,content_identity,run_lock
from streetscape.terrain import Heightfield
from diag.restore_geometry_selection import apply_retained_connectors
from diag.connector_document_checks import check_complete_document


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--snapshot',type=Path,required=True)
    ap.add_argument('--manifest',type=Path,default=TOOLS.parent/'docs/checkpoints/phase1_36_geometry_selection.json')
    ap.add_argument('--max-docs',type=int,default=1);ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/connector_group_verification');args=ap.parse_args()
    if not 1<=args.max_docs<=2:raise ValueError('max-docs must be 1..2')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('outputs must stay under Saved/Phase1')
    snapshot=read(args.snapshot);screen=snapshot['screen'];individual=snapshot['individual_verification'];search=Path(snapshot['search_root']);manifest=read(args.manifest);parent=Path(manifest['source_candidate'])
    names={read(search/row['report'])['pair']['document'] for row in screen['completed'].values() if row['status']=='local_geometry_proposal'}
    docs={name:read(parent/name) for name in sorted(names)}
    for name in names:
        if sha256(parent/name)!=manifest['document_sha256'][name]:raise ValueError('retained source changed: '+name)
    ids={j['id'] for raw in docs.values() for j in raw['junctions']};groups={};held=[];already=[]
    inputs=[args.snapshot,args.manifest,Path(__file__),TOOLS/'phase1_qc.py']+[parent/n for n in sorted(names)]
    for key,row in screen['completed'].items():
        if row['status']!='local_geometry_proposal':continue
        path=search/row['report'];candidate=search/row['candidate']
        if sha256(path)!=row['report_sha256'] or sha256(candidate)!=row['candidate_sha256']:raise ValueError('frozen local proposal changed')
        proposal=read(path);name=proposal['pair']['document'];addition=proposal['addition'];inputs += [path,candidate]
        prior=individual['completed'].get(key)
        if addition['id'] in ids:already.append(key);continue
        if prior and prior['status'].startswith('held'):
            held.append(dict(index=key,status=prior['status'],document=name));continue
        groups.setdefault(name,[]).append(dict(index=key,addition=addition))
    inputs += list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs += [TOOLS/'diag'/n for n in ('connector_document_checks.py','restore_geometry_selection.py','road_body_quality.py','corner_quality_audit.py','polygon_boundary_quality.py')]
    terrain_dir=REPO/'data/thanet/out/unreal/landscape';inputs += [terrain_dir/'landscape_manifest.json']+list(terrain_dir.glob('hm_*.r16'))+list(terrain_dir.glob('clip_*.r8'))
    config=dict(scope='combined complete-document geometry verification',groups=groups,parent=str(parent.resolve()))
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        state_path=root/'state.json';state=read(state_path) if state_path.exists() else dict(status='pending',phase1_accepted=False,fingerprint=identity,input_sha256=hashes,config=config,
            total_documents=len(groups),total_proposals=sum(map(len,groups.values())),already_retained=already,held_individual=held,documents={})
        if state['fingerprint']!=identity or set(state['documents'])-set(groups):raise ValueError('group checkpoint identity or coverage differs')
        for name,row in state['documents'].items():
            if sha256(root/row['report'])!=row['report_sha256'] or sha256(root/row['candidate'])!=row['candidate_sha256']:raise ValueError('completed group output changed')
        terrain=Heightfield.from_landscape_dir(str(terrain_dir));terrain.sampling='landscape_triangulated';processed=0
        for name,selections in sorted(groups.items()):
            if name in state['documents']:continue
            started=time.perf_counter();folder=root/Path(name).stem;folder.mkdir(exist_ok=True)
            selected={name:docs[name]};apply_retained_connectors(selected,{name:[s['addition'] for s in selections]});candidate=selected[name]
            target=folder/name;atomic_json(target,candidate);report=dict(status='running',phase1_accepted=False,document=name,proposal_indices=[s['index'] for s in selections],additions=[s['addition'] for s in selections])
            path=folder/'report.json';atomic_json(path,report)
            try:report.update(check_complete_document(docs[name],candidate,terrain))
            except ValueError as exc:report.update(status='held_geometry',error=str(exc))
            except BaseException as exc:
                report.update(status='execution_failed',error=str(exc));atomic_json(path,report);raise
            report['seconds']=time.perf_counter()-started;atomic_json(path,report)
            state['documents'][name]=dict(status=report['status'],report=str(path.relative_to(root)),report_sha256=sha256(path),candidate=str(target.relative_to(root)),candidate_sha256=sha256(target),proposals=len(selections))
            atomic_json(state_path,state);processed+=1
            print(json.dumps(dict(document=name,status=report['status'],proposals=len(selections),seconds=round(report['seconds'],3),error=report.get('error'))),flush=True)
            if processed>=args.max_docs:break
        if content_identity(inputs,config)[0]!=identity:raise ValueError('group verification inputs changed during run')
        state.update(status='complete' if len(state['documents'])==len(groups) else 'pending',completed=len(state['documents']),totals=dict(Counter(r['status'] for r in state['documents'].values())))
        atomic_json(state_path,state);print(json.dumps(dict(root=str(root),completed=state['completed'],total=len(groups),totals=state['totals'])))


if __name__=='__main__':main()
