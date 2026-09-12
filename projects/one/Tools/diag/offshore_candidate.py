"""Rebase approved offshore changes onto current conformed landscape, preserving all other bytes.

The native patches carry exact masks and baseline heights. This script writes only
the chosen candidate/checkpoint directory; it does not promote or import it.
"""
import argparse, copy, hashlib, json, shutil, sys
from pathlib import Path
import numpy as np
from osgeo import gdal
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'sources'))
import lib

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,j):p.write_text(json.dumps(j,indent=1))
def read(p):return json.loads(p.read_text())

def weight_mosaic(root,man):
    a=np.zeros((man['ny']*256,man['nx']*256,4),np.uint8)
    for t in man['tiles']:
        if t['files']['weights']:
            r=(man['ny']-1-t['y'])*256;c=t['x']*256
            for b,key in enumerate(['grass','sand','rock','water']):
                a[r:r+256,c:c+256,b]=np.fromfile(root/t['files']['weights'][key],dtype='u1').reshape(256,256)
    return a

def vertex_weights(a,i,j):
    # Same cell-centre bilinear + round/renormalise as the native importer.
    rr=np.clip(((18-j)*512+np.arange(513))/2-.5,0,a.shape[0]-1)
    cc=np.clip((i*512+np.arange(513))/2-.5,0,a.shape[1]-1)
    r0=np.minimum(np.floor(rr).astype(int),a.shape[0]-2);c0=np.minimum(np.floor(cc).astype(int),a.shape[1]-2)
    ty=(rr-r0)[:,None,None];tx=(cc-c0)[None,:,None]
    v=(a[r0[:,None],c0[None,:]].astype(float)*(1-tx)+a[r0[:,None],c0[None,:]+1]*tx)*(1-ty)
    v+=(a[r0[:,None]+1,c0[None,:]].astype(float)*(1-tx)+a[r0[:,None]+1,c0[None,:]+1]*tx)*ty
    v=np.floor(v+.5).astype(np.int32);s=v.sum(2);best=v.argmax(2)
    new=np.floor(v*255/np.maximum(s[:,:,None],1)+.5).astype(np.int32)
    r,c=np.indices(s.shape);new[r,c,best]+=np.where(s>0,255-new.sum(2),0)
    return np.clip(new,0,255).astype('u1')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--validate',action='store_true');args=ap.parse_args()
    out=Path(args.out).resolve();out.mkdir(exist_ok=True,parents=True)
    cp=out/'baseline_data';old=cp/'unreal/landscape_conformed';new=ROOT/'data/thanet/out/unreal/landscape'
    baseline=read(old/'landscape_manifest.json');fresh=read(new/'landscape_manifest.json');current=ROOT/'data/thanet/out/unreal/landscape_conformed'
    for p in old.iterdir():
        if p.is_file() and sha(p)!=sha(current/p.name):raise ValueError('conformed baseline changed '+p.name)
    candidate=out/'landscape_candidate'
    if args.validate:
        validate(out,candidate,old,read(candidate/'landscape_manifest.json'),read(out/'patch_manifest.json')['patches'])
        return
    if candidate.exists():raise ValueError('candidate already exists; preserve previous attempt')
    shutil.copytree(old,candidate);patches=out/'patches';patches.mkdir()
    manifest=copy.deepcopy(baseline);by={(t['x'],t['y']):t for t in fresh['tiles']}
    maskds=gdal.Open(str(ROOT/'data/thanet/out/terrain/offshore_masks.tif'))
    edges={};changes=[];native=[];maxoutside=0
    beforeweights=weight_mosaic(old,baseline)
    finalweights=beforeweights.copy()
    for t in manifest['tiles']:
        i,j=t['x'],t['y'];r=(18-j)*512;c=i*512;f=t['files'];nf=by[i,j]['files']
        hm=maskds.GetRasterBand(2).ReadAsArray(c,r,513,513)>0
        a=np.fromfile(old/f['heightmap'],dtype='<u2').reshape(513,513)
        b=np.fromfile(new/nf['heightmap'],dtype='<u2').reshape(513,513)
        desired=np.where(hm,b,a).astype('<u2');desired.tofile(candidate/f['heightmap'])
        changed=desired!=a
        assert not changed[~hm].any()
        clip=np.fromfile(old/f['clip'],dtype='u1').reshape(513,513)>0
        assert not changed[~clip].any()
        t['h16_min']=int(desired.min());t['h16_max']=int(desired.max())
        t['min_m']=float(((desired.astype(float)-32768)/128)[clip].min())
        t['max_m']=float(((desired.astype(float)-32768)/128)[clip].max())
        edges[i,j]=dict(n=desired[0],s=desired[-1],w=desired[:,0],e=desired[:,-1])
        # Old coast weights in the conformed product are preserved outside the source delta.
        base_default=cp/'unreal/landscape';base_t=next(v for v in read(base_default/'landscape_manifest.json')['tiles'] if (v['x'],v['y'])==(i,j))
        oldfiles=base_t['files']['weights'];newfiles=nf['weights'];outfiles={}
        for band,key in enumerate(['grass','sand','rock','water']):
            a0=np.fromfile(base_default/oldfiles[key],dtype='u1').reshape(256,256) if oldfiles else np.zeros((256,256),np.uint8)
            b0=np.fromfile(new/newfiles[key],dtype='u1').reshape(256,256)
            orig=beforeweights[(18-j)*256:(19-j)*256,i*256:(i+1)*256,band]
            dst=np.where(a0!=b0,b0,orig).astype('u1')
            name=f'weight_{key}_x{i}_y{j}.r8';dst.tofile(candidate/name);outfiles[key]=name
            finalweights[(18-j)*256:(19-j)*256,i*256:(i+1)*256,band]=dst
        f['weights']=outfiles
        changes.append(dict(x=i,y=j,height_samples=int(changed.sum())))
    se=lib.shared_edge_audit(edges);assert se['samples_disagreeing']==0
    manifest['offshore_normalisation']=fresh['offshore_normalisation']
    manifest['tiles_without_ground_raster']=[];manifest['weights_note']='All sea tiles carry explicit water weights after approved offshore cleanup.'
    manifest['offshore_baseline_sha256']=sha(old/'landscape_manifest.json')
    manifest['offshore_shared_edges']=se
    manifest['range_m']=[min(t['min_m'] for t in manifest['tiles']),max(t['max_m'] for t in manifest['tiles'])]
    save(candidate/'landscape_manifest.json',manifest)
    for t in manifest['tiles']:
        i,j=t['x'],t['y'];f=t['files'];a=np.fromfile(old/f['heightmap'],dtype='<u2').reshape(513,513);b=np.fromfile(candidate/f['heightmap'],dtype='<u2').reshape(513,513)
        hm=a!=b;wa=vertex_weights(beforeweights,i,j);wb=vertex_weights(finalweights,i,j);wm=np.any(wa!=wb,axis=2)
        if not (hm.any() or wm.any()):continue
        prefix=f'x{i}_y{j}';record=dict(crs='EPSG:27700',vertical_datum='ODN',size=513,x_m=i*512,north_y_m=(j+1)*512,
            before=prefix+'_before.r16',after=prefix+'_after.r16',height_mask=prefix+'_height.r8',water_mask=prefix+'_water.r8',weights=prefix+'_weights.r8')
        for key,array in [('before',a),('after',b),('height_mask',hm.astype('u1')),('water_mask',wm.astype('u1')),('weights',wb)]:array.tofile(patches/record[key])
        record['sha256']={k:sha(patches/record[k]) for k in ['before','after','height_mask','water_mask','weights']}
        name=prefix+'.json';save(patches/name,record)
        # Spatial probes include both corrected and unchanged posts inside every patch.
        probes=[]
        for which,mask in [('height',hm),('water',wm)]:
            rr,cc=np.where(mask)
            if len(rr):
                for k in np.unique(np.linspace(0,len(rr)-1,7).astype(int)):
                    y,x=int(rr[k]),int(cc[k]);probes.append(dict(kind=which,x=i*512+x,y=(j+1)*512-y,z_m=(int(b[y,x])-32768)/128,water=float(wb[y,x,3])/255))
        native.append(dict(file=name,sha256=sha(patches/name),tile=[i,j],height_samples=int(hm.sum()),weight_samples=int(wm.sum()),probes=probes))
    save(out/'patch_manifest.json',dict(candidate=str(candidate),patches=native,baseline_manifest_sha256=sha(old/'landscape_manifest.json'),shared_edges=se,protected_height_changes=0))
    validate(out,candidate,old,manifest,native)

def validate(out,candidate,old,manifest,native):
    # The approved screening was 4m; preserve foreshore connected to the island
    # at native 1m resolution, as required by the plan. Report this refinement.
    se=manifest['offshore_shared_edges']
    finalweights=weight_mosaic(candidate,manifest)
    beforeweights=weight_mosaic(old,read(old/'landscape_manifest.json'))
    review=np.load(ROOT/'output/thanet_offshore_review/analysis_arrays.npz');approved=np.load(ROOT/'output/thanet_offshore_review/proposal_preview.npz')
    h4=np.full((2432,3328),np.nan,np.float32)
    for t in manifest['tiles']:
        i,j=t['x'],t['y'];f=t['files'];a=np.fromfile(candidate/f['heightmap'],dtype='<u2').reshape(513,513)
        h4[(18-j)*128:(19-j)*128,i*128:(i+1)*128]=(a[2:512:4,2:512:4].astype(float)-32768)/128
    water4=finalweights[:,:,3].reshape(2432,2,3328,2).mean((1,3))/255
    protected=review['land']&np.isfinite(review['z']);held=review['detached']&~approved['mask']
    assert np.array_equal(h4[protected],review['z'][protected])
    assert np.array_equal(h4[held],review['z'][held])
    maskds=gdal.Open(str(ROOT/'data/thanet/out/terrain/offshore_masks.tif'))
    native_sea=maskds.GetRasterBand(3).ReadAsArray()[2:9728:4,2:13312:4]>0
    refined=approved['terrain_mask']&~native_sea
    assert np.array_equal(h4[refined],review['z'][refined])
    old4=beforeweights.reshape(2432,2,3328,2,4).mean((1,3))
    new4=finalweights.reshape(2432,2,3328,2,4).mean((1,3))
    assert np.array_equal(old4[protected|held],new4[protected|held])
    badpaint=int((water4[approved['mask']]<.99).sum());above=int((h4[approved['terrain_mask']&native_sea]>=-.6).sum())
    rr,cc=np.where(refined&(h4>=-.6))
    report=dict(patch_tiles=len(native),shared_edges=se,protected_main_land_changes=0,retained_nearshore_height_changes=0,
        approved_artifact_samples_not_water=badpaint,approved_terrain_samples_above_water=above,
        retained_native_connected_foreshore_samples=int(refined.sum()),
        retained_native_connected_foreshore_above_water=[dict(E=int(627680+c*4+2),N=int(172808-r*4-2),z_m=float(h4[r,c])) for r,c in zip(rr,cc)],
        protected_and_retained_material_changes=0,
        encoded_height_samples_changed=sum(t['height_samples'] for t in native),all_checks_pass=badpaint==0 and above==0)
    save(out/'candidate_validation.json',report);print(json.dumps(report,indent=2),flush=True)
    if not report['all_checks_pass']:raise ValueError('approved artifact coverage incomplete')

if __name__=='__main__':main()
