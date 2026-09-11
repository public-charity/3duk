"""Validate a restartable museum build and unchanged source barrier definitions."""
from pathlib import Path
import hashlib
import json
import sys

PROJECT=Path(__file__).resolve().parents[2]
IMPL=PROJECT/'docs/research/manston/implementation'
sys.path.insert(0,str(PROJECT/'Tools/blender'))
from streetscape.io_json import validate_structure


def main():
    state=json.loads((IMPL/'build_state.json').read_text())
    assert state['state']=='ready','Interrupted generation'
    for name,digest in state['sha256'].items():
        assert hashlib.sha256((IMPL/name).read_bytes()).hexdigest()==digest,name
    walks=json.loads((IMPL/'museum_walks.streetscape.json').read_text())
    gates=json.loads((IMPL/'museum_gates.streetscape.json').read_text())
    for doc in (walks,gates):
        assert not validate_structure(doc),validate_structure(doc)
    assert walks['origin']=={'E':627680,'N':163080}
    assert len(walks['splines'])==2
    assert walks['splines'][0]['points'][0]==walks['splines'][1]['points'][0],'Loops have no common gateway'
    for s in walks['splines']:
        assert s['points'][0]==s['points'][-1],s['id']
        assert abs(s['elevation_profile'][0]['z_m']-s['elevation_profile'][-1]['z_m'])<1e-8
    baseline={s['id']:s for s in json.loads((IMPL/'barriers.saved_baseline.streetscape.json').read_text())['splines']}
    for s in gates['splines']:
        restored=dict(s)
        restored['segments']=[seg for seg in s['segments'] if not seg['id'].startswith('manston_gate_')]
        assert restored==baseline[s['id']],'Source fence changed outside new openings: '+s['id']
    schedule=json.loads((IMPL/'gate_schedule.json').read_text())
    assert schedule['walk_samples_sha256']==state['sha256']['walk_samples.json']
    assert schedule['gate_document_sha256']==hashlib.sha256((IMPL/'museum_gates.streetscape.json').read_bytes()).hexdigest()
    manifest=json.loads((IMPL/'museum_manifest.json').read_text())
    assert len(manifest['anchors'])==32
    for f in manifest['anchors']:
        assert f['historical_floor_z_odn_m'] is None and f['historical_portals_bng'] is None,f['id']
    print(json.dumps({'pass':True,'schemas':2,'closed_connected_loops':2,'baseline_barriers_preserved':len(gates['splines']),
        'unknown_subsurface_geometry_preserved':32,'restart_hashes':'verified'}))


if __name__=='__main__':
    main()
