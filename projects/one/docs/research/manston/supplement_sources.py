import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from collect_sources import get, save, NOW, OUT, CACHE

ns = {'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
index = ET.fromstring(get('https://www.manstonhistory.org.uk/sitemap.xml')[0])
maps = [x.text for x in index.findall('s:sitemap/s:loc',ns)]
urls = []
for url in maps:
    root = ET.fromstring(get(url)[0])
    urls.extend({'sitemap':url,'url':node.text} for node in root.findall('s:url/s:loc',ns))
api = json.loads((OUT/'website_inventory.json').read_text(encoding='utf-8'))
article_urls = {r['url'] for r in api['articles']}
unmatched = [r for r in urls if r['url'] not in article_urls and any(t in r['sitemap'] for t in ['post-sitemap','page-sitemap'])]
save('sitemap_inventory.json',{'retrieved_utc':NOW,'sitemaps':maps,'urls':urls,'article_urls_not_in_api':unmatched})
print('Sitemap:',len(urls),'URLs;',len(unmatched),'article URLs absent from REST article inventory',flush=True)

query = '[out:json][timeout:40];(way["aeroway"~"runway|taxiway|apron|aerodrome"](51.33,1.30,51.365,1.38);way["disused:aeroway"~"runway|taxiway|apron|aerodrome"](51.33,1.30,51.365,1.38););out geom;'
path = CACHE/'aeroways.json'
if not path.exists():
    for host in ['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter']:
        try:
            req=urllib.request.Request(host,data=urllib.parse.urlencode({'data':query}).encode(),headers={'User-Agent':'ManstonResearch/1.0'})
            with urllib.request.urlopen(req,timeout=55) as r:
                data=r.read()
            json.loads(data)
            path.write_bytes(data)
            break
        except Exception as e:
            print('Overpass attempt:',str(e),flush=True)
if path.exists():
    d=json.loads(path.read_text())
    print('Aeroways:',len(d.get('elements',[])),flush=True)
    print([(r['id'],r.get('tags')) for r in d.get('elements',[]) if 'runway' in str(r.get('tags'))],flush=True)
    save('aeroway_source.json',{'retrieved_utc':NOW,'source':'OpenStreetMap via Overpass','licence':'ODbL','query':query,'raw_timestamp':d.get('osm3s',{}).get('timestamp_osm_base'),'elements':d.get('elements',[])})
