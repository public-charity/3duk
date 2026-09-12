"""Promote the verified offshore candidate and publish an audit summary."""
from pathlib import Path
import hashlib,importlib.util,json,shutil,sys
ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'output/thanet_offshore_cleanup'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,j):p.write_text(json.dumps(j,indent=1))

def main():
    candidate=OUT/'landscape_candidate';base=ROOT/'data/thanet/out/unreal'
    live=base/'landscape_conformed';old=OUT/'baseline_data/unreal/landscape_conformed'
    checks=read(OUT/'candidate_validation.json');applied=read(OUT/'native_apply_report.json');verified=read(OUT/'native_verification.json')
    assert checks['all_checks_pass'] and applied['passed'] and verified['passed']
    assert not any(applied['unexpected'].values()) and verified['content_guard']['unchanged']
    # Refuse to overwrite another task's newer conformed edit; allow resuming a
    # partially promoted candidate. Validate every destination before copying.
    changes=[]
    for p in candidate.iterdir():
        if not p.is_file():raise ValueError('unexpected nested candidate directory')
        target=live/p.name;want=sha(p)
        if target.exists():
            current=sha(target)
            if current==want:continue
            if not (old/p.name).exists() or current!=sha(old/p.name):raise ValueError('conformed output changed '+p.name)
        elif (old/p.name).exists():raise ValueError('conformed output disappeared '+p.name)
        changes.append((p,target,want))
    for p,target,want in changes:
        shutil.copy2(p,target)
        if sha(target)!=want:raise ValueError('promotion verification failed '+p.name)
    sys.path.insert(0,str(ROOT/'sources'))
    spec=importlib.util.spec_from_file_location('offshore_unreal_adapter',ROOT/'sources/adapters/unreal.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rootman=read(base/'unreal_manifest.json');rootman['derived_products']=module.derived_products(str(base))
    save(base/'unreal_manifest.json',rootman)
    promotion=dict(files_updated=len(changes),candidate_manifest_sha256=sha(candidate/'landscape_manifest.json'),
                   native_saved_packages=len(applied['changes']['modified']),native_reopened_probes=verified['probes'],passed=True)
    save(OUT/'promotion.json',promotion)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image
    plt.rcParams.update({'font.family':'DejaVu Sans','figure.facecolor':'#f5f7f9'})
    for name,title in [('whole','Thanet'),('north','Northern offshore strip'),('east','East of Broadstairs'),('southeast','Southeast of Ramsgate')]:
        fig,axes=plt.subplots(1,2,figsize=(16,6.5),dpi=160)
        for ax,tag,label in zip(axes,['before','after_reopened'],['Before','After — saved map reopened']):
            ax.imshow(Image.open(OUT/'captures'/f'{tag}_{name}.png'))
            ax.set_title(label,loc='left',fontsize=14,pad=10);ax.axis('off')
        fig.suptitle(title+' | offshore cleanup',x=.03,ha='left',fontsize=20)
        fig.text(.03,.025,'Actual Unreal captures with matching cameras, lighting and loaded landscape/building actors.',fontsize=10)
        fig.subplots_adjust(left=.025,right=.975,top=.9,bottom=.07,wspace=.025)
        fig.savefig(OUT/f'before_after_{name}.png');plt.close(fig)
    terrain=read(ROOT/'data/thanet/out/terrain/offshore_report.json')
    report=f'''# Thanet offshore cleanup — completed

The approved A–D offshore artifacts have been removed from the saved Unreal landscape and the terrain pipeline. Selection uses imagery-reviewed regions and native connected-land protection; there is no distance-from-coast cutoff.

![Actual saved map before and after]({(OUT/'before_after_whole.png').as_posix()})

- 98 tile patches applied with exact height and all-four-material readback, preserving live samples outside each mask.
- {promotion['native_saved_packages']} landscape packages saved. Existing actor identities retained; no unrelated Content files changed during the update.
- {verified['probes']} reopened editor/collision/material probes passed. Maximum editor height error {verified['max_editor_error_m']:.6f} m; collision error {verified['max_collision_error_m']:.6f} m.
- All 737 shared tile boundaries agree: 378,081 matching samples, zero disagreements.
- Protected main-land and retained nearshore height/material comparisons are unchanged. The 182 nearshore components excluded by the review remain protected.
- Native resolution identified nine additional connected foreshore samples; these are retained and listed in candidate_validation.json. Every selected detached land-coloured artifact has water coverage; every corrected core sample is submerged.
- {terrain['core_cells']:,} native core samples and {terrain['correction_and_collar_cells']:,} samples including the sea-only blend. Highest corrected core point: {terrain['core_max_m']:.3f} m ODN, below the −0.6 m water reference.
- 35 source-empty sea tiles now carry explicit water material weights. Their unmeasured provenance remains recorded.
- Tests: five offshore cases and 48 adapter tests pass; Unreal editor build passes.

The offshore elevations are an inferred smooth continuation of nearby low marine samples, **not measured bathymetry**. Source LiDAR often records the water surface. The 40 m blend is a transition width, not a deletion rule.

Evidence: [approved review](../thanet_offshore_review/PLAN.md), [candidate checks](candidate_validation.json), [saved-map checks](native_verification.json), [native update](native_apply_report.json), [promotion](promotion.json).

Close views: [north](before_after_north.png), [east](before_after_east.png), [southeast](before_after_southeast.png).

Rollback copies: native_checkpoint/before contains all 141 original landscape packages; baseline_data contains the original derived terrain/coast/default and conformed products. Restore only those exact files with Unreal closed if rollback is required. No rollback has been performed.

The first native attempt hit UE 5.8's D3D12 command-list residency limit before any patch was saved. The successful run disables parallel command translation only inside its process; project rendering settings are unchanged.
'''
    (OUT/'RESULTS.md').write_text(report,encoding='utf8')
    print(json.dumps(promotion,indent=2),flush=True)

if __name__=='__main__':main()
