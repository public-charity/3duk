"""Author airfield surfaces from spline references and EA LiDAR; bake scoped mesh caches.

The interchange splines remain the runway/taxiway source. Renderer A generates paint;
its footprints are joined and tessellated once, removing intersecting-ribbon z-fighting.
Aprons are area features snapped to reference outlines. Native landscape is unchanged.
"""
from pathlib import Path
import json,sys,hashlib,math
from collections import Counter
import numpy as np
from scipy.ndimage import map_coordinates, maximum_filter
from osgeo import gdal
import shapely
from shapely.geometry import Polygon,LineString,box
from shapely.ops import unary_union
from PIL import Image,ImageDraw
P=Path(__file__).resolve().parents[2];R=P.parents[1]
sys.path.insert(0,str(P/'Tools/blender'))
from streetscape.terrain import Heightfield
from streetscape.io_json import validate_structure,load_site
from streetscape.build import build_spline
OUT=P/'docs/research/manston/airfield';CACHE=P/'Saved/ManstonAirfield/generated'
ORIGIN=np.array([627680.,163080.]);B=[631400,165050,634850,167250]
FRAME='local-metres, X east, Y north, Z up'

def save(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp')
 t.write_text(json.dumps(d,separators=(',',':'),allow_nan=False),encoding='utf8');t.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

class Ground:
 def __init__(self):
  gdal.UseExceptions();ds=gdal.Open(str(R/'data/thanet/interim/dtm.vrt'));gt=ds.GetGeoTransform()
  self.raw=ds.ReadAsArray(int(B[0]-(gt[0]+.5)),int(gt[3]-.5-B[3]),B[2]-B[0]+1,B[3]-B[1]+1).astype(float)
  if np.any(self.raw<-1000):raise ValueError('Missing raw airfield LiDAR')
  np.save(R/'tmp/manston/airfield_raw_dtm.npy',self.raw)
  self.hf=Heightfield.from_landscape_dir(str(R/'data/thanet/out/unreal/landscape_conformed'));self.hf.sampling='landscape_triangulated'
  self.hybrid=self.raw.copy()
  # Bounded row strips keep the native source sampling's temporary arrays small.
  for row in range(0,len(self.raw),100):
   yy,xx=np.mgrid[row:min(row+100,len(self.raw)),0:self.raw.shape[1]]
   h=self.hf.sample((xx+B[0]-ORIGIN[0]).ravel(),(B[3]-yy-ORIGIN[1]).ravel()).reshape(xx.shape)
   self.hybrid[row:row+len(xx)]=np.where(np.isfinite(h),h,self.raw[row:row+len(xx)])
  self.paved=maximum_filter(self.hybrid,size=5,mode='nearest')+.065
 def sample(self,x,y):return self.at(np.c_[np.atleast_1d(x)+ORIGIN[0],np.atleast_1d(y)+ORIGIN[1]])
 def at(self,xy,paved=False):
  q=np.asarray(xy);ix=q[:,0]-B[0];iy=B[3]-q[:,1]
  if np.any((ix<0)|(iy<0)|(ix>self.raw.shape[1]-1)|(iy>self.raw.shape[0]-1)):raise ValueError('Geometry outside LiDAR crop')
  return map_coordinates(self.paved if paved else self.hybrid,[iy,ix],order=1,mode='nearest')
 def rebased(self,*args):return self
 def describe(self):return {'source':'EA raw DTM with existing conformed landscape retained','origin_E':627680,'origin_N':163080,'sampling':'bilinear 1m hybrid'}

MATS={'asphalt':'/Game/Thanet/Manston/Airfield/M_Asphalt','concrete':'/Game/Thanet/Manston/Airfield/M_Concrete',
 'apron':'/Game/Thanet/Manston/Airfield/M_Apron','grass':'/Game/Thanet/Manston/Airfield/M_Grass',
 'white_paint':'/Game/Thanet/Manston/Airfield/M_White','yellow_paint':'/Game/Thanet/Manston/Airfield/M_Yellow'}

def mark(id,offset,width,a=None,b=None,pattern='solid',material='white_paint'):
 m=dict(id=id,anchor='centre',offset_m=offset,width_m=width,pattern=pattern,material=material,lift_m=.006)
 if a is not None:m.update(s0_m=a,s1_m=b)
 if pattern=='dashed':m.update(dash_m=30.,gap_m=20.,phase_m=100.)
 return m

def runway_marks(L):
 m=[mark('centre',0,.9,110,L-110,'dashed'),mark('left_edge',29.5,.45),mark('right_edge',-29.5,.45)]
 for end in (0,1):
  def add(id,d,w,s0,s1):m.append(mark(str(end)+'_'+id,d if not end else -d,w,s0 if not end else L-s1,s1 if not end else L-s0))
  add('threshold',0,60,2,3.8)
  for k in range(12):add('stripe_'+str(k),(k-5.5)*4.,1.8,10,40)
  for d in (-11,11):add('aim_'+str(d),d,6.,300,345)
  glyphs={'1':['00100','01100','00100','00100','00100','00100','01110'],
          '0':['01110','11011','11011','11011','11011','11011','01110'],
          '2':['01110','11011','00011','00110','01100','11000','11111'],
          '8':['01110','11011','11011','01110','11011','11011','01110']}
  for digit,ch in enumerate('10' if end==0 else '28'):
   for row,line in enumerate(glyphs[ch]):
    for col,c in enumerate(line):
     if c=='1':add('number_%d_%d_%d'%(digit,row,col),-(digit*9+col*1.4-7.3),1.42,65+(6-row)*2.6,65+(7-row)*2.6)
 return m

def triangulate(poly,step):
 """Uniform interior grid, exact clipped boundary cells; no unfilled polygon interiors."""
 if poly.is_empty:return np.empty((0,2)),np.empty((0,3),int)
 lo=np.floor(np.array(poly.bounds[:2])/step)*step;hi=np.ceil(np.array(poly.bounds[2:])/step)*step
 x=np.arange(lo[0],hi[0],step);y=np.arange(lo[1],hi[1],step);xx,yy=np.meshgrid(x,y)
 cells=shapely.box(xx.ravel(),yy.ravel(),xx.ravel()+step,yy.ravel()+step)
 full=shapely.covers(poly,cells);touch=shapely.intersects(poly,cells)&~full
 verts=[];faces=[];lookup={}
 def vertex(p):
  k=(round(float(p[0]),5),round(float(p[1]),5))
  if k not in lookup:lookup[k]=len(verts);verts.append(k)
  return lookup[k]
 def face(points):
  a=np.array(points)
  area=float((a[1,0]-a[0,0])*(a[2,1]-a[0,1])-(a[1,1]-a[0,1])*(a[2,0]-a[0,0]))
  if abs(area)<1e-7:return
  q=[vertex(p) for p in points];faces.append(q if area>0 else q[::-1])
 for X,Y in zip(xx.ravel()[full],yy.ravel()[full]):
  face([(X,Y),(X+step,Y),(X+step,Y+step)]);face([(X,Y),(X+step,Y+step),(X,Y+step)])
 for cell in cells[touch]:
  cut=shapely.intersection(poly,cell)
  for t in shapely.get_parts(shapely.constrained_delaunay_triangles(cut)):
   face(list(t.exterior.coords)[:3])
 v=np.array(verts);f=np.array(faces,dtype=int)
 a=v[f[:,1]]-v[f[:,0]];b=v[f[:,2]]-v[f[:,0]]
 measured=abs(a[:,0]*b[:,1]-a[:,1]*b[:,0]).sum()/2
 if abs(measured-poly.area)>max(.02,poly.area*1e-6):raise ValueError('Triangulation area differs from footprint')
 return v,f

def main():
 save(OUT/'build_state.json',{'state':'building'});CACHE.mkdir(parents=True,exist_ok=True)
 ground=Ground();base=json.loads((OUT.parent/'basemap.bng.json').read_text());aeros=base['aeroways']
 runway=next(a for a in aeros if a['tags'].get('aeroway')=='runway')
 pts=np.array(runway['pts']);W=pts[-1];E=pts[0];u=(E-W)/np.linalg.norm(E-W);n=np.array([-u[1],u[0]]);mid=(W+E)/2
 L=2750.;W=mid-u*L/2;E=mid+u*L/2
 doc=dict(schema_version='1.0.0',site='thanet',crs='EPSG:27700',origin=dict(E=627680,N=163080),vertical_datum='ODN',frame=FRAME,
  generator='manston-airfield-completion',profiles={'road':{},'edge':{},'hedge':{}},splines=[],junctions=[])
 features=[]
 def spline(id,name,points,width,mat,marks,source):
  doc['profiles']['road'][id]=dict(kind='road',lanes=1,lane_widths_m=[width],width_m=width,surface_material=mat,
   camber={'kind':'none','crossfall_pct':0.},overlap_m=.04,skirt_drop_m=.02,lateral_station_spacing_m=3.,markings=marks)
  doc['splines'].append(dict(id=id,source={'layer':'authored','name':name},profile_ids={'road':id,'edge_left':None,'edge_right':None,'hedge_left':None,'hedge_right':None},
   points=[{'x':float(p[0]-ORIGIN[0]),'y':float(p[1]-ORIGIN[1])} for p in points],sampling={'step_m':3.,'min_step_m':.5,'curvature_gain':12.,'smoothing_window_m':5.,'bank_max_deg':0.},segments=[],drop_kerbs=[]))
  features.append(dict(id=id,name=name,width_m=width,source=source,classification='runway' if id=='runway' else 'taxiway'))
 spline('runway','Runway 10/28', [W,E],61.,'tarmac',runway_marks(L),'OSM 35310906 alignment; 2750 x 61 m authored physical envelope; historical civil dimensions')
 spline('historic_platform','Broad historic runway pavement',[W+25*n,E+25*n],230.,'concrete',[],
  'LiDAR and aerial edge interpretation; approx 230 m breadth including redundant pavement, not an additional operational runway')
 for a in aeros:
  if a['tags'].get('aeroway')!='taxiway':continue
  ref=a['tags'].get('ref','');w=23. if ref.startswith('A') else 18.
  if not ref:w=12.
  spline('taxi_'+a['id'],'Taxiway '+(ref or 'link'),a['pts'],w,'tarmac',[mark('centre',0,.18,material='yellow_paint')],
   'OSM '+a['id']+' reference alignment; width estimated from aerial, not surveyed')
 save(OUT/'airfield.streetscape.json',doc)
 errors=validate_structure(doc)
 if errors:raise ValueError(errors)
 site=load_site(str(OUT/'airfield.streetscape.json'))
 shapes={};paints=[]
 for d in doc['splines']:
  result=build_spline(site,d['id'],ground);xy=result.spline.xy+ORIGIN
  width=doc['profiles']['road'][d['id']]['width_m'];shapes[d['id']]=LineString(xy).buffer(width/2,cap_style='flat',join_style='round')
  mesh=result.road
  for k,name in enumerate(mesh.material_names):
   if name not in ('white_paint','yellow_paint'):continue
   faces=mesh.f[mesh.mat==k];used,inv=np.unique(faces,return_inverse=True)
   paints.append((name,mesh.v[used,:2]+ORIGIN,inv.reshape(-1,3)))
 aprons=[]
 for a in aeros:
  if a['tags'].get('aeroway')!='apron':continue
  q=Polygon(a['pts']).buffer(0)
  aprons.append(q)
  features.append(dict(id='apron_'+a['id'],name=a['tags'].get('name','Apron / dispersal pad'),classification='apron',source='OSM '+a['id']+' outline, corroborated by LiDAR/aerial',area_m2=round(q.area,1)))
 # The large apron is visibly paved in aerial imagery but absent from the OSM apron inventory.
 missing_apron=Polygon([(633330,165790),(633690,165735),(633644,165985),(633425,166025)])
 aprons.append(missing_apron);features.append(dict(id='central_apron',name='Central apron infill',classification='apron',source='Manually interpreted Esri aerial; approximate edges, image date unknown',area_m2=round(missing_apron.area,1)))
 asphalt=unary_union([p for k,p in shapes.items() if k!='historic_platform'])
 apron=unary_union(aprons).difference(asphalt)
 concrete=shapes['historic_platform'].difference(asphalt.union(apron))
 paved=asphalt.union(apron).union(concrete)
 # Preserve all existing landscape; restore only airport land on the discarded side of its crop.
 boundary=Polygon(next(a['pts'] for a in aeros if a['tags'].get('aeroway')=='aerodrome')).buffer(15).union(paved.buffer(20))
 # Exact source clip polygon is read from the terrain manifest (same data already used by UE).
 man=ground.hf.manifest
 save(OUT/'terrain_clip_reference.json',man.get('clip',{}))
 # Missing terrain uses a 4 m grid mask; a 4 m overlap under retained ground avoids an open seam.
 extension=[]
 for X in np.arange(631400,634850,128.):
  for Y in np.arange(165050,167250,128.):
   tile=box(X,Y,min(X+128,634850),min(Y+128,167250));p=boundary.intersection(tile)
   if p.is_empty:continue
   tx,ty=np.meshgrid(np.arange(X,min(X+128,634850),4),np.arange(Y,min(Y+128,167250),4))
   q=np.c_[tx.ravel()+2,ty.ravel()+2]
   z=ground.hf.sample(q[:,0]-ORIGIN[0],q[:,1]-ORIGIN[1]);missing=~np.isfinite(z)
   if missing.any():extension.append(unary_union(shapely.box(q[missing,0]-4,q[missing,1]-4,q[missing,0]+4,q[missing,1]+4)).intersection(p))
 extension=unary_union(extension).difference(paved)
 caches=[];probes=[];floor_triangles=[];paint_checks=[]
 def cache(id,xy,f,mat,paved_surface=True,paint=False,supplied_z=None):
  if not len(f):return
  z=ground.at(xy,paved_surface) if supplied_z is None else supplied_z
  origin=np.r_[np.mean(xy,axis=0)-ORIGIN,0.]
  v=np.round(np.c_[xy-ORIGIN,z]-origin,5)
  a=v[f[:,1],:2]-v[f[:,0],:2];b=v[f[:,2],:2]-v[f[:,0],:2]
  signed=a[:,0]*b[:,1]-a[:,1]*b[:,0]
  if np.any(signed< -1e-8):raise ValueError('Inverted cache triangle '+id)
  # Marking interval boundaries can emit microscopic slivers that collapse at 10-micron storage precision.
  removed=int((signed<=1e-8).sum());f=f[signed>1e-8]
  data=dict(frame=FRAME,vertices=v.tolist(),triangles=np.c_[f,np.zeros(len(f),int)].tolist(),materials=[MATS[mat]])
  path=CACHE/(id+'.json');save(path,data)
  caches.append(dict(id='manston_airfield:'+id,file=path.name,sha256=sha(path),origin_local_m=origin.tolist(),material=mat,vertices=len(v),triangles=len(f),paint=paint,collapsed_precision_slivers_removed=removed))
  if paved_surface and not paint:floor_triangles.append((v+origin)[f])
  if not paint:
   # Triangle centroid height is independently known from exported vertices.
   indices=np.unique(np.linspace(0,len(f)-1,min(len(f),75)).astype(int));tri=f[indices]
   for p,h in zip(xy[tri].mean(axis=1),z[tri].mean(axis=1)):
    probes.append(dict(actor='manston_airfield:'+id,xy_local_m=(p-ORIGIN).tolist(),z_m=float(h),kind=mat,
     native_landscape_present=bool(np.isfinite(ground.hf.sample(p[0]-ORIGIN[0],p[1]-ORIGIN[1])))))
 for mat,poly,step in [('grass',extension,4.),('concrete',concrete,2.),('apron',apron,2.),('asphalt',asphalt,2.)]:
  for X in range(631400,634850,256):
   for Y in range(165050,167250,256):
    cut=poly.intersection(box(X,Y,min(X+256,634850),min(Y+256,167250)))
    if cut.area<.001:continue
    xy,f=triangulate(cut,step);cache('%s_%s_%s'%(mat,X,Y),xy,f,mat,mat!='grass')
  print(mat,'complete',flush=True)
 # Paint uses Renderer A's footprint, intersected with the actual exported floor triangles.
 # Each paint face is parallel to its supporting floor face, preventing the holes caused by
 # independently interpolating a raster across a differently tessellated surface.
 floors=np.concatenate(floor_triangles);floor_polys=shapely.polygons(floors[:,:,:2]);tree=shapely.STRtree(floor_polys)
 for i,(mat,xy,f) in enumerate(paints):
  footprint=shapely.union_all(shapely.polygons((xy-ORIGIN)[f]))
  if mat=='yellow_paint':footprint=footprint.difference(shapely.transform(shapes['runway'].buffer(12),lambda p:p-ORIGIN))
  vertices=[];faces=[];covered_area=0.
  for index in tree.query(footprint,predicate='intersects'):
   cut=footprint.intersection(floor_polys[index])
   if cut.area<1e-9:continue
   a,b,c=floors[index];ab=b[:2]-a[:2];ac=c[:2]-a[:2];det=ab[0]*ac[1]-ab[1]*ac[0]
   for t in shapely.get_parts(shapely.constrained_delaunay_triangles(cut)):
    q=np.array(t.exterior.coords)[:3];delta=q-a[:2]
    bu=(delta[:,0]*ac[1]-delta[:,1]*ac[0])/det;bv=(ab[0]*delta[:,1]-ab[1]*delta[:,0])/det
    z=a[2]+bu*(b[2]-a[2])+bv*(c[2]-a[2])+.009
    ab2=q[1]-q[0];ac2=q[2]-q[0];signed=ab2[0]*ac2[1]-ab2[1]*ac2[0]
    if abs(signed)<1e-8:continue
    face=list(range(len(vertices),len(vertices)+3));faces.append(face if signed>0 else face[::-1])
    vertices.extend(np.c_[q+ORIGIN,z]);covered_area+=abs(signed)/2
  if not vertices:continue
  v=np.array(vertices);cache('paint_'+str(i),v[:,:2],np.array(faces),mat,True,True,v[:,2])
  paint_checks.append(dict(id='paint_'+str(i),footprint_area_m2=footprint.area,covered_area_m2=covered_area,offset_m=.009))
  if abs(footprint.area-covered_area)>max(.1,footprint.area*1e-4):raise ValueError('Paint footprint is not supported by pavement')
 print('paint conformed to exported floor triangles',flush=True)
 # Full width and threshold coverage checks, including the section formerly beyond the terrain clip.
 checks=[]
 for s in np.linspace(0,L,140):
  for d in np.linspace(-30.5,30.5,9):checks.append(W+u*s+n*d)
 # One micrometre accommodates round-off at the exact threshold boundary in BNG coordinates.
 q=np.array(checks);covered=shapely.covers(paved.buffer(1e-6),shapely.points(q))
 if not covered.all():raise ValueError('Runway coverage incomplete')
 source_counts=dict(Counter(a['tags'].get('aeroway') for a in aeros))
 report=dict(frame=FRAME,source_counts=source_counts,features=features,runway_length_m=L,runway_width_m=61,
  historic_pavement_width_m=230,areas_m2={k:round(v.area,1) for k,v in [('paved',paved),('terrain_extension',extension),('asphalt',asphalt),('apron',apron),('historic_concrete',concrete)]},
  caches=caches,probes=probes,paint_contact_checks=paint_checks,runway_coverage_points=len(q),runway_coverage_pass=True,
  source_sha256={str(p.relative_to(R)).replace('\\','/'):sha(p) for p in [OUT/'airfield.streetscape.json',OUT.parent/'basemap.bng.json',R/'data/thanet/interim/dtm.vrt']},
  terrain_note='Paved surfaces drape onto local upper envelope of existing conformed ground with raw EA DTM fallback outside the original crop; no global landscape edits.',
  limitations=['Runway/taxiway widths and apron infill edges are reconstruction estimates, not a measured airport survey.',
   'No operational aviation lights, navigational equipment or current airport-use claim. Museum interpretation preserves historic pavement.',
   'LiDAR impressions alone do not establish underground rooms or portals.'])
 save(OUT/'airfield_manifest.json',report)
 save(OUT/'build_state.json',dict(state='ready',manifest_sha256=sha(OUT/'airfield_manifest.json'),cache_dir=str(CACHE),caches=len(caches)))
 # Original diagnostic plan, not third-party aerial imagery.
 img=Image.new('RGB',(1726,1101),'#b4c89b');draw=ImageDraw.Draw(img)
 def coords(ring):return [((p[0]-B[0])/2,(B[3]-p[1])/2) for p in ring]
 for poly,color in [(concrete,'#b0aaa0'),(apron,'#92998f'),(asphalt,'#3b4043')]:
  mask=Image.new('L',img.size,0);md=ImageDraw.Draw(mask)
  for p in shapely.get_parts(poly):
   if p.geom_type!='Polygon':continue
   md.polygon(coords(p.exterior.coords),fill=255)
   for hole in p.interiors:md.polygon(coords(hole.coords),fill=0)
  img.paste(color,(0,0),mask)
 draw=ImageDraw.Draw(img)
 for a in base['buildings']:draw.polygon(coords(a['rings'][0]['pts']),fill='#77786f')
 draw.text((30,30),'MANSTON: complete airfield surface plan / north up / 2 m per pixel',fill='black')
 draw.text((30,50),'EA LiDAR (OGL); OSM contributors (ODbL); authored reconstruction estimates',fill='black')
 img.save(OUT/'surface_plan.png')
 print(json.dumps({k:report[k] for k in ['source_counts','runway_length_m','areas_m2','runway_coverage_points']}))
 print('caches',len(caches),'triangles',sum(c['triangles'] for c in caches),'probes',len(probes))

if __name__=='__main__':main()
