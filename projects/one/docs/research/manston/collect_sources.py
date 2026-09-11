"""Refresh public Manston source metadata; raw research cache stays in tmp/manston.

No media binaries are mirrored. Published outputs contain links, metadata and facts,
not a redistribution of the history site's articles or photographs.
"""
import hashlib
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
CACHE = ROOT / 'tmp' / 'manston'
CACHE.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc).isoformat()
REFRESH = '--refresh' in sys.argv
BASE = 'https://www.manstonhistory.org.uk/'


def get(url):
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    path = CACHE / (key + '.json')
    if path.exists() and not REFRESH:
        obj = json.loads(path.read_text(encoding='utf-8'))
        return obj['body'], obj['headers']
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ManstonResearch/1.0 (public heritage study)'})
            with urllib.request.urlopen(req, timeout=45) as response:
                body = response.read().decode('utf-8', errors='replace')
                headers = dict(response.headers.items())
            path.write_text(json.dumps({'url': url, 'retrieved_utc': NOW, 'headers': headers, 'body': body}), encoding='utf-8')
            time.sleep(.25)
            return body, headers
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def plain(markup):
    return BeautifulSoup(markup or '', 'html.parser').get_text(' ', strip=True)


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def wp_inventory():
    counts, articles, media, terms, links = {}, [], [], [], []
    for kind in ['posts', 'pages', 'media', 'categories', 'tags']:
        page = 1
        count = 0
        while True:
            url = f'{BASE}wp-json/wp/v2/{kind}?per_page=100&page={page}'
            body, headers = get(url)
            rows = json.loads(body)
            total_pages = int(next((v for k,v in headers.items() if k.lower() == 'x-wp-totalpages'), 1))
            expected = int(next((v for k,v in headers.items() if k.lower() == 'x-wp-total'), len(rows)))
            for row in rows:
                if kind in ['posts', 'pages']:
                    html = row.get('content', {}).get('rendered', '')
                    text = plain(html)
                    article = {'id': row['id'], 'kind':kind, 'title': plain(row['title']['rendered']), 'url':row['link'], 'published':row['date'], 'modified':row['modified'], 'word_count':len(text.split()), 'content_sha256':hashlib.sha256(html.encode()).hexdigest(), 'categories':row.get('categories',[]), 'tags':row.get('tags',[]), 'layout_keywords':sorted(set(re.findall(r'\b(?:underground|semi-sunken|shelter|hangar|hangars|hanger|hangers|runway|railway|tunnel|tunnels|entrance|map|plan|FIDO|tower|barracks|fuel)\b', text, re.I)))}
                    articles.append(article)
                    soup = BeautifulSoup(html, 'html.parser')
                    for el in soup.find_all(['a','img','iframe']):
                        target = el.get('href') or el.get('src')
                        if target:
                            links.append({'parent_id':row['id'],'parent_url':row['link'],'kind':el.name,'url':urljoin(BASE,target),'label':(el.get('alt') or el.get_text(' ',strip=True))[:160]})
                elif kind == 'media':
                    media.append({'id':row['id'],'title':plain(row['title']['rendered']),'url':row.get('source_url'),'attachment_page':row['link'],'parent_post_id':row.get('post'),'mime_type':row.get('mime_type'),'date':row['date'],'width':row.get('media_details',{}).get('width'),'height':row.get('media_details',{}).get('height'),'rights_status':'not established; verify original owner before reuse'})
                else:
                    terms.append({k:row.get(k) for k in ['id','name','slug','count','link']} | {'kind':kind})
            count += len(rows)
            print(f'{kind}: {count}/{expected}', flush=True)
            if page >= total_pages:
                break
            page += 1
        counts[kind] = {'retrieved':count,'api_reported':expected,'pages':total_pages,'count_matches':count == expected}
    save('website_inventory.json', {'retrieved_utc':NOW,'source':BASE,'coverage':counts,'articles':articles,'taxonomies':terms})
    save('media_inventory.json', {'retrieved_utc':NOW,'media':media})
    save('linked_resources.json', {'retrieved_utc':NOW,'links':links})
    return counts


def kent_inventory():
    base = 'https://heritage.kent.gov.uk'
    url = base + '/Monument/MKE40120'
    body, _ = get(url)
    soup = BeautifulSoup(body, 'html.parser')
    candidates = {}
    for a in soup.find_all('a', href=True):
        if 'Parent of:' in a.get_text():
            full = urljoin(base,a['href'])
            candidates[full] = a.get_text(' ',strip=True)
    for extra in ['MKE90888','MKE97296','MKE125405','MKE98020','MKE98031','MKE125093','MKE125138','MKE125137','MKE125142']:
        candidates[base+'/Monument/'+extra] = extra

    def read(item):
        url,title = item
        try:
            body, _ = get(url)
            soup = BeautifulSoup(body, 'html.parser')
            text = soup.get_text(' ',strip=True)
            heading = soup.find('h1')
            match = re.search(r'Grid reference\s+(.+?)\s+Map sheet', text)
            grid = match.group(1) if match else None
            coord = re.search(r'TR\s+(\d{3,5})\s+(\d{3,5})', grid or '')
            en = [600000+int(coord[1].ljust(5,'0')),100000+int(coord[2].ljust(5,'0'))] if coord else None
            return {'id':url.rstrip('/').split('/')[-1].upper(),'title':heading.get_text(' ',strip=True) if heading else title,'url':url,'grid_reference':grid,'anchor_bng':en,'geometry_role':'HER representative point/extent centre, NOT a surveyed entrance or footprint','retrieved_utc':NOW,'source_sha256':hashlib.sha256(body.encode()).hexdigest(),'fetch_status':'ok'}
        except Exception as e:
            return {'url':url,'title':title,'fetch_status':'failed','error':str(e)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(read,candidates.items()))
    # Normalise and deduplicate case variations in public links.
    rows = list({r.get('id',r['url']):r for r in rows}.values())
    save('heritage_inventory.json',{'retrieved_utc':NOW,'parent_url':url,'records':rows,'note':'Public record metadata, not a licensed GIS polygon export. Main inventory follows all Manston parent-record children plus relevant independent records.'})
    print(f'Kent HER: {len(rows)} records, {sum(r["fetch_status"] != "ok" for r in rows)} failures',flush=True)
    return rows


if __name__ == '__main__':
    robots, _ = get(BASE+'robots.txt')
    counts = wp_inventory()
    rows = kent_inventory()
    save('acquisition_manifest.json',{'retrieved_utc':NOW,'website_coverage':counts,'heritage_records':len(rows),'heritage_failures':[r for r in rows if r['fetch_status']!='ok'],'method':'Public WordPress REST API, metadata links and content hashes; public Kent HER parent/child pages','excluded':'Login-only material, private archives, deleted content, comments, media binaries, external linked works; full source text remains in local scratch research cache only','status':'complete for listed API collections and discovered HER records; not a claim to every historical record or every website resource'})
