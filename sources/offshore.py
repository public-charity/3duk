"""Opt-in, imagery-reviewed offshore correction in survey coordinates.

No distance-to-coast deletion threshold. Geometry chooses the reviewed sea;
connected land and the documented coast protect real terrain. Inferred heights
are explicitly modelled from low marine samples, not claimed as bathymetry.
"""
import hashlib
import json
from pathlib import Path
import numpy as np


def rules(cfg):
    spec = cfg.get('offshore_normalisation')
    if not spec or not spec.get('enabled', False):
        return None
    path = Path(__file__).parent / spec['review_file']
    review = json.loads(path.read_text(encoding='utf8'))
    if review['crs'] != cfg['crs']:
        raise ValueError('offshore review CRS differs from site')
    return dict(spec, review=review, review_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def burn(polygons, gt, shape):
    from osgeo import gdal, ogr
    ds = gdal.GetDriverByName('MEM').Create('', shape[1], shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    vector = ogr.GetDriverByName('Memory').CreateDataSource('offshore')
    layer = vector.CreateLayer('mask', geom_type=ogr.wkbUnknown)
    for geom in polygons:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(ogr.CreateGeometryFromJson(json.dumps(geom)))
        layer.CreateFeature(feature)
    gdal.RasterizeLayer(ds, [1], layer, burn_values=[1], options=['ALL_TOUCHED=TRUE'])
    return ds.ReadAsArray().astype(bool)


def masks(cfg, gt, heights):
    """Shared native-grid decision; invalid values may be NaN or filled."""
    from scipy import ndimage as ndi
    spec = rules(cfg)
    if spec is None:
        return None
    review = spec['review']
    sea = burn(review['regions'], gt, heights.shape)
    protected = burn(review['protected_land'], gt, heights.shape)
    # A real connected foreshore is protected even outside the coastline vector.
    # Match the classifier's water band. A blanket elevation threshold would
    # join submerged water to the island and accidentally protect false rises.
    dz = np.full(heights.shape, np.inf, np.float32)
    for axis in (0, 1):
        a = [slice(None),slice(None)]; b = a.copy(); a[axis]=slice(1,None); b[axis]=slice(None,-1)
        a,b=tuple(a),tuple(b); diff=np.abs(heights[a]-heights[b])
        dz[a]=np.fmin(dz[a],diff); dz[b]=np.fmin(dz[b],diff)
    coast=cfg.get('coast',{})
    band=(np.abs(heights-cfg['water_level'])<coast.get('water_tolerance_m',.3)) & (dz<coast.get('water_flat_dz_per_m',.08)*min(abs(gt[1]),abs(gt[5])))
    dry = np.isfinite(heights) & (heights >= cfg['water_level']-.1) & ~band
    del dz,band
    labels, _ = ndi.label(dry, structure=np.ones((3, 3)))
    counts = np.bincount(labels[protected & dry].ravel())
    if len(counts) > 1:
        counts[0] = 0
        protected |= labels == int(counts.argmax())
    sea &= ~protected
    return sea, protected, spec


def normalise(heights, missing, sea, protected, water_level, clearance_m=.3,
              blend_m=40., smooth_m=80., pixel_m=1., reference_step=4):
    """Modify ONLY the approved core and a sea-only blend; return masks/report.

    Evaluate the core at native resolution. Fit the smooth marine reference on
    a coarser grid, then interpolate it; this bounds memory and does not resample
    the original land. NoData is supplied separately from its filled heights.
    """
    from scipy import ndimage as ndi
    if heights.shape != missing.shape or sea.shape != heights.shape or protected.shape != heights.shape:
        raise ValueError('offshore array shape mismatch')
    if not np.isfinite(heights).all() or clearance_m <= 0 or blend_m <= 0 or smooth_m <= 0:
        raise ValueError('finite filled heights and positive fit parameters required')
    threshold = water_level-clearance_m
    core = sea & ~protected & (missing | (heights >= threshold))
    if not core.any():
        return core, np.zeros(heights.shape, np.float32), dict(core_cells=0, changed_cells=0)
    step = max(1, int(reference_step))
    small = heights[::step, ::step]
    trust = ~missing[::step, ::step] & ~protected[::step, ::step] & (small < threshold)
    if not trust.any():
        raise ValueError('no valid low marine reference samples; refusing invented constant')
    idx = ndi.distance_transform_edt(~trust, return_distances=False, return_indices=True)
    smooth = ndi.gaussian_filter(small[tuple(idx)], sigma=smooth_m/(pixel_m*step))
    del idx
    dist = ndi.distance_transform_edt(~core, sampling=pixel_m).astype(np.float32)
    alpha = np.clip(1-dist/blend_m, 0, 1)
    alpha *= alpha*(3-2*alpha)
    alpha[protected] = 0
    # The collar joins already-submerged sea, never unrelated dry/rock features.
    alpha[~sea & (heights >= threshold)] = 0
    del dist
    changed = 0; max_change = 0.; core_max = -float('inf')
    for r in range(0, heights.shape[0], 128):
        s = slice(r, min(r+128, heights.shape[0]))
        rr, cc = np.nonzero(alpha[s] > 0)
        if not len(rr):
            continue
        rr += r
        target = ndi.map_coordinates(smooth, [rr/step, cc/step], order=1, mode='nearest')
        old = heights[rr, cc].copy(); a = alpha[rr, cc]
        new = old*(1-a)+target*a
        heights[rr, cc] = new
        changed += int(np.count_nonzero(old != new))
        max_change = max(max_change, float(np.max(np.abs(new-old))))
        keep = core[rr, cc]
        if keep.any(): core_max = max(core_max, float(new[keep].max()))
    if core_max >= threshold:
        raise ValueError('offshore fit was not fully submerged')
    return core, alpha, dict(core_cells=int(core.sum()), correction_and_collar_cells=int((alpha>0).sum()),
        changed_cells=changed, maximum_change_m=max_change, core_max_m=core_max,
        method='native core; smooth nearest low marine reference; sea-only smoothstep collar',
        inferred_not_surveyed_bathymetry=True, reference_step=step, blend_m=blend_m, smooth_m=smooth_m)


def apply(cfg, gt, heights, missing, out):
    selection = masks(cfg, gt, heights)
    if selection is None: return {}
    from osgeo import gdal, osr
    sea, protected, spec = selection
    core, alpha, report = normalise(heights, missing, sea, protected, cfg['water_level'],
        clearance_m=spec['clearance_m'], blend_m=spec['blend_m'], smooth_m=spec['smooth_m'],
        pixel_m=abs(gt[1]), reference_step=spec['reference_step'])
    # A native-grid provenance raster lets the downstream delta updater preserve
    # every conformed road/land height outside the actual correction.
    path = Path(out)/'offshore_masks.tif'
    ds = gdal.GetDriverByName('GTiff').Create(str(path), heights.shape[1], heights.shape[0], 3,
        gdal.GDT_Byte, options=['TILED=YES','COMPRESS=DEFLATE'])
    sr = osr.SpatialReference(); sr.ImportFromEPSG(int(cfg['crs'].split(':')[1]))
    ds.SetGeoTransform(gt); ds.SetProjection(sr.ExportToWkt())
    for i, a in enumerate([core, alpha>0, sea], 1): ds.GetRasterBand(i).WriteArray(a.astype('u1')*255)
    ds.FlushCache(); ds = None
    report.update(review_sha256=spec['review_sha256'], mask_file=path.name,
        mask_bands=['core','height_correction_and_collar','reviewed_water'], pixel_m=abs(gt[1]),
        rule='imagery-reviewed sea regions; preserve coast and connected land; no coast-distance cutoff')
    (Path(out)/'offshore_report.json').write_text(json.dumps(report, indent=2))
    return {'offshore_normalisation': report}
