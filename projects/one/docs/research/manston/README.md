# Manston research and approval pack

Start with [the museum plan](MANSTON_MUSEUM_PLAN.md) and [the source chest](SOURCE_CHEST.md).
The typeset approval report is at `output/pdf/manston_museum_approval_plan.pdf` from the repository root.
Research date: 11 September 2026. The user approved starting implementation. **Phases 0–1 are underway**; see [the saved checkpoints](PROGRESS.md) for the current state and resume action. The original approval report remains a dated research/concept record.

Use [the implementation guide](IMPLEMENTATION_GUIDE.md) to visit the saved museum blockout, reproduce it, or recover from the packaged checkpoint.

The subsequent runway and airfield completion work is recorded in [the airfield guide](airfield/README.md), [LiDAR findings](airfield/LIDAR_FINDINGS.md) and [saved checkpoints](airfield/PROGRESS.md), including the local terrain extension needed to recover the runway beyond the original map crop. The latest airfield checkpoint also includes four museum furniture clearance corrections.

The recommendation is selected restoration within today's mapped landscape, with a museum gateway, a short command loop, an aircraft/engineering circuit and optional archaeology/runway trails.
The underground records support separate features. Unknown coordinates, depths and connectivity are not fabricated.

## Coverage

- 110 history-site posts and 43 pages, reconciled against all post/page sitemap URLs.
- 491 public media records returned; endpoint total 503. The 12-object discrepancy remains explicit.
- 305 Kent HER record anchors; 32 curated feature notes, with source and survival statements.
- 624 background building records, 517 tiled road segments and 49 aeroway records.
- Five proposed route alignments, four proposed gateway roles, three analytical figures.

`acquisition_manifest.json` describes exclusions. This is not a complete archive of every document, photograph, comment, deleted article or private historical record. The retrieved article/page collections contain utility and old pages as well as historical content.

## Files and evidence

The two `.bng.json` research/proposal files use EPSG:27700 metres with the Thanet origin E627680 N163080. They are **not** Streetscape-schema documents. All unknown floor heights and portal positions stay null. The HER representative point may be the centre of a multi-feature extent and is not an entrance or surveyed building corner.

`museum_masterplan.png`, `subsurface_evidence.png` and `interior_concepts.png` are original analytical figures. SVG versions are included. Existing roads/buildings and new aeroway data derive from OpenStreetMap contributors (ODbL) and the project's existing EA LiDAR-based data (Open Government Licence); preserve that attribution. Kent HER metadata is attributed to Kent County Council. This pack does not grant a licence to source photographs or maps.

The source-text cache and the three historical map images used for visual research remain in ignored `tmp/manston/`. They are working research material and are not part of the distributable pack. Reuse of third-party photographs, scans or source-map tiles must be checked with the actual rights holder.

## Reproduction

Run from the repository root. Use a Python with BeautifulSoup, matplotlib, Pillow, ReportLab and pypdf for collection/figures/report. Use the repository's GDAL environment for the basemap export (with its Library/bin on PATH so the existing PROJ/OSTN15 setup is available).

1. `collect_sources.py` inventories the public REST collections and Kent HER. Pass `--refresh` to request fresh public responses instead of using the existing scratch cache. Cached runs reuse the recorded source snapshot; output-generation timestamps alone do not establish a new source retrieval.
2. `supplement_sources.py` reconciles sitemap URLs and retrieves aeroways if the local aeroway cache is absent. Its saved `raw_timestamp` identifies the OSM snapshot; a cached rerun is not a fresh OSM extract.
3. `export_basemap.py` reads existing Thanet products and transforms the aeroway supplement. It requires a non-ballpark coordinate transformation with requested accuracy no worse than 1 m; this is a transformation requirement, not a claim of OSM survey accuracy.
4. `curate_pack.py` produces the reviewed features, proposals and human-readable index. Editorial notes and route geometry live in this script and should be reviewed before changes.
5. `draw_maps.py` draws the three figures. `build_pdf.py` typesets the Markdown report with landscape A3 figure pages.

Before creating/editing the PDF, follow the available PDF skill's artifact-operation marker requirement. After changing text or figures, render the PDF and inspect its pages. Keep the report's published counts consistent with refreshed inventory totals.

## Validation completed

For the research pack: checked unique IDs and inventory counts, coordinate round-trips, null unknown geometries, route-length calculations, footnote definitions and image links. Rendered and visually reviewed all 15 PDF pages, including full-size inspection of dense tables and sources. Implementation checks and changes to the explorer are recorded separately in `PROGRESS.md` and `implementation/`.
