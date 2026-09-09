# Thanet photo warchest

Open-licensed photography of the Isle of Thanet, filed by town, for photogrammetric
reconstruction in RealityScan and headless Blender, feeding the Unreal map in `projects/one`.

Everything here is fetched by [`sources/fetch/photos.py`](../sources/fetch/photos.py) from
public endpoints. Nothing in this directory is committed — it is disposable and re-fetchable,
exactly like `data/`. The source of truth is the fetcher plus
[`sources/config/thanet_towns.json`](../sources/config/thanet_towns.json).

```bash
# what exists, per town per source -- a few MB of JSON, no image bytes
python sources/fetch/photos.py catalogue

# then scope the actual download
python sources/fetch/photos.py download --town margate --source panoramax
python sources/fetch/photos.py download --limit 200 --size sd     # a taste of everything

# and work out what to point RealityScan at
python sources/fetch/photos.py clusters --min 8                   # subjects with many angles
python sources/fetch/photos.py targets                            # listed buildings, by coverage
```

## Layout

```
images/
  _catalogue/<source>.json    everything the source holds over Thanet; the download list
  _catalogue/summary.json     counts and byte estimate per town
  <town>/<source>/*.jpg       the image files
  <town>/MANIFEST.jsonl       one record per downloaded file: author, licence, page, position, sha256
  CREDITS.md                  attribution roll-up, generated from the manifests
```

Towns come from `thanet_towns.json`, which assigns each photo to the town owning the nearest
OSM place anchor. Anything more than 2.5 km from every anchor lands in `_unassigned/`. Edit
that config and run `photos.py assign` to re-file the catalogue without re-downloading.

## Sources

| Source | Licence | Coverage | Worth for reconstruction |
|---|---|---|---|
| **panoramax** | CC BY-SA 4.0 | street-level | **High.** Contiguous sequences, so overlap is inherent. `hd` is the untouched original with GPS EXIF. |
| **mapillary** | CC BY-SA 4.0 | street-level | **High**, and far denser than Panoramax in the UK — but needs `MAPILLARY_TOKEN`. |
| **geograph** | CC BY-SA 2.0 | ~1 per OS 1 km square | Medium. Even coverage by design, so good for context and for landmarks several people have shot; rarely overlapping enough on its own. |
| **commons** | mixed CC / PD | landmark-heavy | Medium. Often the highest resolution, and clusters on exactly the buildings worth modelling. |
| **flickr** | CC (derivative-permitting only) | variable | Medium; needs `FLICKR_API_KEY`. |

**A third of the Geograph corpus is low resolution and there is nothing to be done about it.**
`_original.jpg` — the photographer's upload — only exists for images uploaded above the old
site display size. Measured over the completed Thanet download: 2,905 of 8,659 Geograph images
(34%) have no `_original` and no `_1024x1024` either, so the fetcher falls back to the plain
`.jpg` at roughly 640 px. Those are ~100 KB against 789 KB median for the rest. Treat them as
reference and context, not as reconstruction input; `url_used` in the manifest records which
rung each file came from, so you can filter on it:

```bash
grep '"source": "geograph"' images/margate/MANIFEST.jsonl | grep '_original'   # the usable ones
```

**Commons overlaps Geograph heavily, and that overlap is kept by default.** About three
quarters of the Commons files over Thanet are Geograph photographs re-uploaded under a filename
carrying the Geograph id. `photos.py catalogue --dedupe` drops them, but it is off by default:
the re-upload is a separate file with its own resolution and licence, and given that a third of
the Geograph corpus is capped at ~640 px, the Commons copy is sometimes the higher-resolution
one. Turn it on only if disk matters more than coverage.

Set the two keys and re-run `catalogue` to fold them in:

```bash
export MAPILLARY_TOKEN=MLY|...      # mapillary.com/dashboard/developers
export FLICKR_API_KEY=...           # flickr.com/services/apps/create/apply
```

## Using this with RealityScan

**Reconstruct from sequences, not from folders.** A town folder is an archive, not an input
set — it mixes 20 years of cameras, seasons and subjects, and feeding all of it to RealityScan
produces a slow, incoherent alignment. The unit that reconstructs is a *sequence*: a run of
consecutive street-level frames along one street. Panoramax and Mapillary records carry a
`sequence` id in `MANIFEST.jsonl`; group by it.

```bash
# every panoramax sequence in Margate, largest first
python - <<'PY'
import json, collections
rows=[json.loads(l) for l in open("images/margate/MANIFEST.jsonl",encoding="utf-8")]
c=collections.Counter(r.get("sequence") for r in rows if r["source"]=="panoramax")
for seq,n in c.most_common(): print(n, seq)
PY
```

**`photos.py clusters`** does the equivalent for the scattered sources: it reports groups of
photos within a few tens of metres of each other, which is where Geograph and Commons actually
have enough angles on one subject to reconstruct it. Those are your landmark candidates. It
reports a `span_m` per cluster — single-link clustering chains along a seafront, so use the
span to tell one building (tens of metres) from half a town, and `--max-span` to control it.

**`photos.py targets`** joins that coverage to Historic England's listed buildings from
`geo/heritage/nhle_listed.geojson`, and is the most direct answer to "what can I build today":

```
 ppl  pics  gr   town             name
  44   156  II   margate          DROIT HOUSE
  36    99  II   broadstairs      LITTLEWOLD
  31    61  II*  ramsgate         THE CLOCK HOUSE
```

It ranks on **distinct photographers**, not photo count, because parallax between cameras is
what reconstructs a building — forty frames by one person walking one side of a street will
not. It also lists the Grade I and II\* buildings with *no* imagery at all, which is the
shoot-list if you go to Thanet with a camera.

**Keep the EXIF.** `--size hd` fetches the original upload with its metadata intact, which is
what lets RealityScan seed alignment and georeference the result. Spot-checked on Panoramax
downloads: GPS present on every file, camera make and focal length on most but **not all** —
so treat focal length as a bonus rather than something to rely on. `--size sd` is ~6x smaller
and re-encoded — fine for a look, weak for reconstruction.

**Georeference against the LIDAR.** `geo/ea/lidar_pointcloud_index.geojson` lists the EA's
classified LAZ point cloud over Thanet (median 0.85 m spacing; the 2006 and 2017 surveys are
finer, at 0.21 m and 0.35 m). Importing that as control is the cheapest way to land a
photogrammetric mesh in real OSGB36 / ODN coordinates — the same frame the rest of the pipeline
works in (`sources/config/sites/thanet.json`, `crs: EPSG:27700`, elevations in metres above
Ordnance Datum Newlyn). A mesh built from photos alone is in an arbitrary frame and will not
sit on the terrain.

**Street-level imagery sees facades, not roofs.** For roofs you want the EA oblique aerial
photography indexed in `geo/ea/oblique_photography_index.geojson` — 336 frames over the isle,
each with camera easting, northing, heading and view angle. The imagery itself is ordered
through the Defra portal rather than fetched over HTTP; see `geo/ea/README.md`.

## Licensing — read this before you publish anything

Every image here is **share-alike or public domain**, and the share-alike ones **require
attribution**. CC BY-SA is viral: a mesh, texture, render or game level derived from a
CC BY-SA photo carries the same terms.

- `CREDITS.md` is generated from the manifests and is the attribution of record. Regenerate it
  with `photos.py credits` after any download.
- `MANIFEST.jsonl` holds per-file author, licence, licence URL and source page. Do not
  discard it — it is the only link between a file on disk and the person owed credit.
- Commons files are **mixed**: some are CC BY-SA, some CC0, some public domain, a few are
  more restrictive. The per-file `licence` field is authoritative; the table above is not.
- Mixing sources into one reconstruction mixes their licences into the output. If you intend
  to ship the result under a single set of terms, reconstruct from one licence class at a time
  — the manifest lets you filter before you build.

None of this is legal advice; the licence text at the recorded `licence_url` governs.

## Being a good citizen of these APIs

The fetcher is rate-limited to one request per second to Geograph and three per second to the
others, single connection, with a descriptive User-Agent. These are volunteer-run and
public-sector services and the limits are deliberately well under what they would tolerate.
Geograph in particular asks that its images not be hotlinked from its servers — download and
serve your own copies, which is what this does.

If you run this at any volume, set a contact address so the operators can reach you:

```bash
export WARCHEST_CONTACT="you@example.com"
```
