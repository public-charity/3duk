"""Render source LiDAR relief with mapped airfield references for manual review."""
from pathlib import Path
import json, sys
import numpy as np
from scipy.ndimage import gaussian_filter
from PIL import Image, ImageDraw, ImageFont
P=Path(__file__).resolve().parents[2]
R=P.parents[1]
sys.path.insert(0,str(P/'Tools/blender'))
from streetscape.terrain import Heightfield
OUT=P/'docs/research/manston/airfield'
OUT.mkdir(parents=True,exist_ok=True)
B=[631400,165050,634850,167250]
x=np.arange(B[0],B[2]+1,2.)
y=np.arange(B[3],B[1]-1,-2.)
xx,yy=np.meshgrid(x,y)
hf=Heightfield.from_landscape_dir(str(R/'data/thanet/out/unreal/landscape'))
z=np.load(R/'tmp/manston/airfield_raw_dtm.npy')[::2,::2]
gy,gx=np.gradient(z,2.)
relief=z-gaussian_filter(z,12)
b=json.loads((P/'docs/research/manston/basemap.bng.json').read_text())
for mode in ['relief','references']:
 grey=(np.clip((np.nan_to_num(relief)+.35)/.7,0,1)*255).astype('uint8')
 img=Image.fromarray(grey).convert('RGB');d=ImageDraw.Draw(img)
 def xy(p):return tuple(((np.asarray(p)-[B[0],B[3]])/[2,-2]).tolist())
 if mode=='references':
  for a in b['aeroways']:
   p=np.array(a['pts']);k=a['tags'].get('aeroway')
   if k=='aerodrome':continue
   d.line([xy(q) for q in p],fill={'runway':'#ff5050','taxiway':'#ffd34e','apron':'#48dada'}[k],width=2)
   if k!='apron':d.text(xy(p[len(p)//2]),a['tags'].get('ref','?')+' / '+a['id'][-4:],fill='red')
 for a in b['buildings']:
  p=np.array(a['rings'][0]['pts']);d.line([xy(q) for q in p],fill='#277298',width=1)
 for e in range(631500,635000,250):
  d.text(xy([e,B[3]-25]),str(e),fill='#ee0000')
 for n in range(165250,167250,250):d.text(xy([B[0]+5,n]),str(n),fill='#ee0000')
 d.text((200,30),'Manston: EA LiDAR local relief, 2m pixels. EPSG:27700; north up. OGL / OSM ODbL.',fill='#ee0000')
 img.save(OUT/('lidar_'+mode+'.png'))
print(str(OUT))
