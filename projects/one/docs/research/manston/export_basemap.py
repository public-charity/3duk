"""Uses the repository's GDAL/OSTN15 environment; preserves surveyed BNG metres."""
import hashlib
import json
import os
from pathlib import Path
from osgeo import osr

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
BBOX=[631250,164650,635000,167800]
def inside(p):
    return BBOX[0]<=p[0]<=BBOX[2] and BBOX[1]<=p[1]<=BBOX[3]
out={'crs':'EPSG:27700','bbox':BBOX,'buildings':[],'roads':[],'aeroways':[],'provenance':{'buildings_roads':'Existing Thanet OSM/LiDAR-derived survey products; see sources/provenance/thanet.osm.json','licences':'OpenStreetMap ODbL; Environment Agency lidar Open Government Licence'}}
for f in (ROOT/'data/thanet/out/massing').glob('*.jsonl'):
    for line in f.open():
        r=json.loads(line)
        if any(inside(p) for p in r['rings'][0]['pts']):
            out['buildings'].append({k:r.get(k) for k in ['id','name','base_z','h','src','rings']})
for f in (ROOT/'data/thanet/out/networks').glob('roads_*.jsonl'):
    for line in f.open():
        r=json.loads(line)
        if any(inside(p) for p in r['pts']):
            out['roads'].append({k:r.get(k) for k in ['id','name','cls','pts','w']})
src=HERE/'aeroway_source.json'
if src.exists():
    # Same grid-shift operation as the established geodata pipeline.
    os.environ['PROJ_NETWORK']='ON'
    wgs=osr.SpatialReference(); wgs.ImportFromEPSG(4326); wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    bng=osr.SpatialReference(); bng.ImportFromEPSG(27700); bng.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    opts=osr.CoordinateTransformationOptions(); opts.SetDesiredAccuracy(1.0); opts.SetBallparkAllowed(False)
    ct=osr.CreateCoordinateTransformation(wgs,bng,opts)
    if ct is None: raise RuntimeError('No non-ballpark <=1m BNG transformation')
    for e in json.loads(src.read_text())['elements']:
        pts=[list(ct.TransformPoint(p['lon'],p['lat'])[:2]) for p in e.get('geometry',[])]
        if not all(abs(p[0])<1e7 and abs(p[1])<1e7 for p in pts): raise RuntimeError('Coordinate transformation failed')
        out['aeroways'].append({'id':str(e['id']),'tags':e.get('tags',{}),'pts':pts})
    out['provenance']['aeroways']='Fresh OSM supplement; <=1m non-ballpark PROJ operation required; mapping itself is not survey accuracy'
(HERE/'basemap.bng.json').write_text(json.dumps(out,separators=(',',':')),encoding='utf-8')
print({k:len(out[k]) for k in ['buildings','roads','aeroways']})
