"""Scoped, restartable museum import in the existing Thanet World Partition map.

--inspect is read-only. --apply saves only Manston actor packages. --verify reopens
the saved map and tests the generated walk surfaces. Engine interfaces:
StreetscapeEditorLibrary.h: ImportStreetscapeJson, LoadRegion, ActorStatsJson;
Engine/Classes/Components/TextRenderComponent.h: SetText / SetWorldSize;
UnrealEd/Public/FileHelpers.h: UEditorLoadingAndSavingUtils::SavePackages.
"""
from pathlib import Path
import json
import sys
import unreal
import ue_common as uc

NAME='12_manston_museum'
PROJECT=Path(uc.project_dir())
RESEARCH=PROJECT/'docs/research/manston'
IMPL=RESEARCH/'implementation'
REPORTS=PROJECT/'Saved/Manston'
MAP='/Game/Thanet/Maps/Thanet'


def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def main():
    opts=uc.parse_args(sys.argv,flags=('inspect','apply','verify'))
    if sum(bool(v) for v in opts.values()) != 1:
        raise ValueError('Choose exactly one of --inspect, --apply, --verify')
    if not unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(MAP):
        raise RuntimeError('Could not load Thanet')
    hf=uc.heightfield()
    if hf is None:
        raise RuntimeError('No registered terrain')
    report={'map':MAP,'terrain':hf.describe_source(),'landscape_dir':str(hf.get_editor_property('landscape_dir')),
        'gateway_height_odn_m':hf.probe_m(633315-627680,166510-163080)}
    if opts['inspect']:
        if (IMPL/'walk_samples.json').exists():
            unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(560000,-310000,0),85000.)
            landscape=unreal.StreetscapeLandscapeImporter.find_landscape()
            checks=[]
            for route in json.loads((IMPL/'walk_samples.json').read_text())['routes']:
                points=route['local_xyz_m']
                for x,y,z in points[::max(1,len(points)//24)]:
                    actual=unreal.StreetscapeLandscapeImporter.probe_height_m(landscape,x,y,False)
                    checks.append({'x':x,'y':y,'landscape_z':actual,'survey_z':hf.probe_m(x,y),'planned_walk_z':z})
            report['terrain_checks']=checks
        save_json(REPORTS/'inspection.json',report)
        uc.report(NAME,report)
        return
    raise RuntimeError('Import not enabled until the generated route placement passes')


if __name__=='__main__':
    main()
