"""Evidence placement and native Streetscape blockout; run with the project Python.

No source terrain, OSM products or historical geometry are edited. The generated
walks are museum design, not present public access or surveyed historical paths.
"""
from pathlib import Path
import argparse
import hashlib
import heapq
import json
import math
import sys
import numpy as np
from scipy.ndimage import distance_transform_edt, label

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT.parents[1]
RESEARCH = PROJECT / 'docs/research/manston'
OUT = RESEARCH / 'implementation'
sys.path.insert(0, str(PROJECT / 'Tools/blender'))
from streetscape.terrain import Heightfield
from streetscape.io_json import validate_structure, load_site
from streetscape.build import build_spline

ORIGIN = np.array([627680., 163080.])
STEP = 2.
BOUNDS = np.array([632650., 165700., 633750., 166780.])


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def inside(points, ring):
    """Ray crossing for survey polygons; ring may repeat its first vertex."""
    p = np.asarray(points)
    hit = np.zeros(len(p), dtype=bool)
    for a, b in zip(ring, np.roll(ring, -1, axis=0)):
        if a[1] == b[1]:
            continue
        hit ^= ((a[1] > p[:, 1]) != (b[1] > p[:, 1])) & (p[:, 0] <
            (b[0]-a[0]) * (p[:, 1]-a[1]) / (b[1]-a[1]) + a[0])
    return hit


def distance_to_buildings(points, buildings):
    p = np.asarray(points)
    result = np.full(len(p), np.inf)
    for building in buildings:
        # Conservative: courtyards are obstacles until their entrances are mapped.
        ring = np.array(building['rings'][0]['pts'])
        lo, hi = ring.min(axis=0)-15, ring.max(axis=0)+15
        select = np.flatnonzero(np.all((p >= lo) & (p <= hi), axis=1))
        if not len(select):
            continue
        q = p[select]
        d = np.full(len(q), np.inf)
        for a, b in zip(ring, np.roll(ring, -1, axis=0)):
            v = b-a
            if np.dot(v,v) < 1e-12:
                continue
            t = np.clip((q-a) @ v / np.dot(v,v), 0, 1)
            d = np.minimum(d, np.linalg.norm(q-a-t[:,None]*v, axis=1))
        d[inside(q, ring)] = 0
        result[select] = np.minimum(result[select], d)
    return result


class Router:
    def __init__(self, hf, buildings):
        self.hf = hf
        self.x = np.arange(BOUNDS[0], BOUNDS[2]+STEP, STEP)
        self.y = np.arange(BOUNDS[1], BOUNDS[3]+STEP, STEP)
        xx, yy = np.meshgrid(self.x,self.y)
        self.shape = xx.shape
        self.points = np.c_[xx.ravel(),yy.ravel()]
        self.z = hf.sample(xx.ravel()-ORIGIN[0],yy.ravel()-ORIGIN[1]).reshape(xx.shape)
        self.clearance = distance_to_buildings(self.points, buildings).reshape(xx.shape)
        self.free = (self.clearance >= 5.) & np.isfinite(self.z)
        # Avoid steep terrain; this is a blockout routing criterion, not accessibility certification.
        gy,gx = np.gradient(self.z, STEP)
        self.slope = np.hypot(gx,gy)
        self.free &= self.slope < .12
        self.free[[0,-1],:] = False
        self.free[:,[0,-1]] = False
        regions,_=label(self.free)
        counts=np.bincount(regions.ravel());counts[0]=0
        self.free &= regions == counts.argmax()
        self.nearest = distance_transform_edt(~self.free, return_distances=False, return_indices=True)

    def cell(self,p):
        x,y = np.round((np.array(p)-BOUNDS[:2])/STEP).astype(int)
        if not (0 <= y < self.shape[0] and 0 <= x < self.shape[1]):
            raise ValueError('Waypoint outside routing bounds')
        return tuple(self.nearest[:,y,x])

    def xy(self,c):
        return [float(self.x[c[1]]),float(self.y[c[0]])]

    def astar(self,start,end):
        start,end = self.cell(start),self.cell(end)
        heap = [(0.,start)]
        best = {start:0.}
        parent = {}
        done = set()
        while heap:
            _,p = heapq.heappop(heap)
            if p in done:
                continue
            if p == end:
                path=[p]
                while p != start:
                    p=parent[p];path.append(p)
                return [self.xy(c) for c in reversed(path)]
            done.add(p)
            for dy,dx in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                q = p[0]+dy,p[1]+dx
                if not self.free[q] or not self.free[p[0]+dy,p[1]] or not self.free[p[0],p[1]+dx]:
                    continue
                length=STEP*math.hypot(dx,dy)
                grade=abs(float(self.z[q]-self.z[p]))/length
                if grade > .12:
                    continue
                cost=best[p]+length*(1+12*grade+4*float(self.slope[q]))
                if cost < best.get(q,math.inf):
                    best[q]=cost;parent[q]=p
                    heapq.heappush(heap,(cost+STEP*math.hypot(q[0]-end[0],q[1]-end[1]),q))
        raise ValueError('No connected museum path between %r and %r' % (start,end))

    def simplify(self,points):
        # Preserve bends while removing staircase noise. Every shortcut is sampled.
        p=np.asarray(points);out=[p[0]];i=0
        while i < len(p)-1:
            chosen=i+1
            for j in range(min(i+24,len(p)-1),i+1,-1):
                v=p[j]-p[i];length=np.linalg.norm(v)
                if length < 1e-8:
                    continue
                # Preserve the route's original shape to within 2 m.
                t=np.clip((p[i:j+1]-p[i])@v/(length*length),0,1)
                if np.linalg.norm(p[i:j+1]-p[i]-t[:,None]*v,axis=1).max()>2:
                    continue
                samples=p[i]+np.linspace(0,1,max(2,int(length)+1))[:,None]*v
                indices=np.round((samples-BOUNDS[:2])/STEP).astype(int)
                heights=self.hf.sample(samples[:,0]-ORIGIN[0],samples[:,1]-ORIGIN[1])
                grade=np.abs(np.diff(heights))/np.maximum(np.linalg.norm(np.diff(samples,axis=0),axis=1),1e-9)
                if np.all(self.free[indices[:,1],indices[:,0]]) and np.isfinite(heights).all() and grade.max() <= .12:
                    chosen=j;break
            out.append(p[chosen]);i=chosen
        return np.array(out)


def build(landscape_dir):
    save(OUT/'build_state.json',{'state':'building','resume':'Re-run build_museum.py; importing an incomplete generation is refused.'})
    basemap=json.loads((RESEARCH/'basemap.bng.json').read_text())
    proposal=json.loads((RESEARCH/'museum_proposal.bng.json').read_text())
    evidence=json.loads((RESEARCH/'features.bng.json').read_text())
    hf=Heightfield.from_landscape_dir(str(landscape_dir))
    hf.sampling='landscape_triangulated'
    router=Router(hf,basemap['buildings'])
    doc=dict(schema_version='1.0.0',site='thanet',crs='EPSG:27700',origin=dict(E=627680,N=163080),
        vertical_datum='ODN',frame='local-metres, X east, Y north, Z up',generator='manston-museum-phase1',
        materials={'gravel':{'base_color':[.52,.48,.42],'roughness':.95}},
        profiles={'road':{'manston_walk':{'kind':'road','lanes':1,'lane_widths_m':[3.],
            'width_m':3.,'surface_material':'gravel','camber':{'kind':'none','crossfall_pct':0.},
            'overlap_m':.04,'skirt_drop_m':.03,'lateral_station_spacing_m':.5,'markings':[]}},'edge':{},'hedge':{}},
        splines=[],junctions=[])
    designed=[]
    for route in proposal['routes'][:2]:
        points=[]
        for a,b in zip(route['points'][:-1],route['points'][1:]):
            leg=router.astar(a,b)
            points.extend(leg if not points else leg[1:])
        simple=router.simplify(points)
        # Rounded corners keep a 3 m ribbon from folding at A* grid turns.
        for _ in range(2):
            p,q=simple[:-1],simple[1:]
            rounded=np.stack([.75*p+.25*q,.25*p+.75*q],axis=1).reshape(-1,2)
            simple=np.vstack([simple[0],rounded,simple[-1]])
        if not np.array_equal(simple[0],simple[-1]):
            raise ValueError('Loop lost its closure')
        local=simple-ORIGIN
        sp=dict(id='manston:'+route['id'],source=dict(layer='authored',name=route['name']),
            profile_ids={'road':'manston_walk','edge_left':None,'edge_right':None,'hedge_left':None,'hedge_right':None},
            points=[dict(x=float(p[0]),y=float(p[1])) for p in local],
            sampling=dict(step_m=1.,min_step_m=.25,curvature_gain=20.,smoothing_window_m=4.,smoothing_passes=1,
                width_ramp_m=3.,bank_max_deg=8.,bank_probe_min_half_width_m=1.5,pin_blend_m=3.,bank_rate_max_deg_per_m=2.),
            segments=[],drop_kerbs=[],flags={'closed_loop':True})
        doc['splines'].append(sp)
        designed.append({'id':route['id'],'name':route['name'],'points_bng':simple.tolist(),
            'adjusted_waypoints_bng':[router.xy(router.cell(p)) for p in route['points']]})
    errors=validate_structure(doc)
    if errors:
        raise ValueError(errors)
    save(OUT/'museum_walks.streetscape.json',doc)
    site=load_site(str(OUT/'museum_walks.streetscape.json'))
    metrics=[]
    path_samples=[]
    for route,definition in zip(designed,doc['splines']):
        result=build_spline(site,definition['id'],hf)
        # A museum promenade needs its own authored elevation. This does not move
        # the survey or the site's other roads. Lift across the full path width,
        # then form the lowest closed grade-limited profile above those samples.
        ground=hf.sample(result.road.v[:,0],result.road.v[:,1])
        required=np.zeros(len(result.spline.s))
        station=np.searchsorted(result.spline.s,result.road.vs)
        np.maximum.at(required,station,ground-result.road.v[:,2]+.08)
        elevation=result.spline.z_ref+required
        ds=np.diff(result.spline.s)
        for _ in range(4):
            elevation[0]=elevation[-1]=max(elevation[0],elevation[-1])
            for i in range(1,len(elevation)):
                elevation[i]=max(elevation[i],elevation[i-1]-.06*ds[i-1])
            for i in range(len(elevation)-2,-1,-1):
                elevation[i]=max(elevation[i],elevation[i+1]-.06*ds[i])
        definition['elevation_profile']=[{'s_m':float(s),'z_m':float(z),'bank_deg':float(b)}
            for s,z,b in zip(result.spline.s,elevation,result.spline.bank_deg)]
        save(OUT/'museum_walks.streetscape.json',doc)
        site=load_site(str(OUT/'museum_walks.streetscape.json'))
        result=build_spline(site,definition['id'],hf)
        samples=np.c_[result.spline.xy,result.spline.z_ref]
        xy=samples[:,:2]+ORIGIN
        clearance=distance_to_buildings(xy,basemap['buildings'])
        ds=np.linalg.norm(np.diff(samples[:,:2],axis=0),axis=1)
        grade=np.abs(np.diff(samples[:,2]))/np.maximum(ds,1e-9)
        if not np.isfinite(samples).all() or clearance.min()<2.5:
            raise ValueError('Native spline samples lose building clearance or terrain coverage')
        stat={'id':route['id'],'length_m':round(float(result.spline.s[-1]),1),
            'samples':len(samples),'minimum_centre_to_building_m':round(float(clearance.min()),2),
            'max_longitudinal_grade_pct':round(float(grade.max()*100),2),
            'p95_longitudinal_grade_pct':round(float(np.percentile(grade,95)*100),2),
            'maximum_centre_lift_above_terrain_m':round(float((samples[:,2]-result.spline.z_raw).max()),3),
            'walk_minutes_at_3kmh':round(float(result.spline.s[-1])/50,1),
            'closed_loop':True,'road_triangles':len(result.road.f)}
        metrics.append(stat)
        path_samples.append({'id':route['id'],'local_xyz_m':np.round(samples,4).tolist()})
    # These heights place signs ON the surface; they do not fill unknown historical floor depths.
    anchors=[]
    for f in evidence['features']:
        xy=np.array(f['anchor_bng'])-ORIGIN
        z=float(hf.sample(np.array([xy[0]]),np.array([xy[1]]))[0])
        anchors.append(dict(id=f['id'],name=f['name'],layer=f['layer'],anchor_bng=f['anchor_bng'],
            placement_surface_z_odn_m=round(z,4) if math.isfinite(z) else None,
            source_url=f['source_url'],survival=f['survival_as_recorded'],
            historical_floor_z_odn_m=None,historical_portals_bng=None,
            geometry_status='Representative evidence point; not a surveyed entrance or footprint'))
    gateway=designed[0]['points_bng'][0]
    furniture=[]
    all_samples=np.vstack([np.array(r['local_xyz_m']) for r in path_samples])
    def place_near(index, samples):
        p=samples[index,:2]+ORIGIN
        tangent=samples[min(index+4,len(samples)-1),:2]-samples[max(0,index-4),:2]
        if np.linalg.norm(tangent)<.001:
            return None
        tangent/=np.linalg.norm(tangent)
        normal=np.array([-tangent[1],tangent[0]])
        candidates=np.array([p+4.5*normal,p-4.5*normal])
        distances=distance_to_buildings(candidates,basemap['buildings'])
        order=np.argsort(-distances)
        for choice in order:
            xy=candidates[choice]
            local=xy-ORIGIN
            z=float(hf.sample(local[0:1],local[1:2])[0])
            if distances[choice]>=3 and math.isfinite(z):
                # Face toward the walk. Yaw converted only at the Unreal boundary.
                facing=p-xy
                return {'bng':xy.tolist(),'surface_z_odn_m':z,
                    'heading_deg':math.degrees(math.atan2(facing[1],facing[0]))}
        return None
    core_ids=('MKE98025','MKE98027','MKE98021','MKE98020','MKE98024','MKE125515','MKE125655')
    for f in anchors:
        if f['id'] not in core_ids:
            continue
        index=int(np.argmin(np.linalg.norm(all_samples[:,:2]+ORIGIN-np.array(f['anchor_bng']),axis=1)))
        p=place_near(index,all_samples)
        if p:
            furniture.append(dict(id='sign_'+f['id'],kind='sign',name=f['name'],
                text=f['name']+'\nHistorical location nearby\nRestoration planned',source_id=f['id'],**p))
    for r in path_samples:
        samples=np.array(r['local_xyz_m'])
        distances=np.r_[0,np.cumsum(np.linalg.norm(np.diff(samples[:,:2],axis=0),axis=1))]
        for k,station in enumerate(np.arange(120,distances[-1],180)):
            p=place_near(int(np.searchsorted(distances,station)),samples)
            if p:
                furniture.append(dict(id='rest_'+r['id']+'_'+str(k),kind='bench',name='Rest stop',**p))
    first=np.array(path_samples[0]['local_xyz_m'])
    p=place_near(0,first)
    if p:
        furniture.append(dict(id='welcome',kind='sign',name='Manston Museum',
            text='MANSTON\nRAF HERITAGE MUSEUM\nMuseum walk  R1\nAirfield walk  R2\nRestoration work in progress',**p))
    manifest={'schema':'manston-implementation-0.1','phase':'Phase 0 placed; Phase 1 blockout candidate',
        'origin':doc['origin'],'crs':'EPSG:27700','vertical_datum':'ODN',
        'terrain_dir':str(landscape_dir.relative_to(ROOT)).replace('\\','/'),
        'terrain_manifest_sha256':hashlib.sha256((landscape_dir/'landscape_manifest.json').read_bytes()).hexdigest(),
        'input_sha256':{p:hashlib.sha256((RESEARCH/p).read_bytes()).hexdigest() for p in
            ('features.bng.json','museum_proposal.bng.json','basemap.bng.json')},
        'gateway_bng':gateway,'routes':designed,'metrics':metrics,'anchors':anchors,'furniture':furniture,
        'limitations':['Proposed museum reuse in the explorer; not current public access.',
            'Explicit promenade elevation is new museum design. Raised portions need edge/support detailing.',
            'Walks avoid mapped building footprints; fences and entrances still need detailed survey.',
            'Real gameplay and saved-world collision checks pending.',
            'Unknown historical footprints, underground portals, floor depths and links remain unmodelled.']}
    save(OUT/'walk_samples.json',{'routes':path_samples})
    save(OUT/'museum_manifest.json',manifest)
    save(OUT/'build_state.json',{'state':'ready','sha256':{name:hashlib.sha256((OUT/name).read_bytes()).hexdigest()
        for name in ('museum_walks.streetscape.json','walk_samples.json','museum_manifest.json')}})
    print(json.dumps({'output':str(OUT),'routes':metrics,'anchors':len(anchors)}))
    return manifest


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--landscape-dir',default=str(ROOT/'data/thanet/out/unreal/landscape_conformed'))
    args=ap.parse_args()
    build(Path(args.landscape_dir).resolve())
