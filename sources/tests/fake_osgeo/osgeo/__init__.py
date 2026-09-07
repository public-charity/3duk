"""Minimal in-memory stand-in for GDAL/OGR -- just enough API surface to dry-run the
3duk pipeline steps 05-10 and the Unity adapter against synthetic data.

Rasters are numpy arrays in a path-keyed registry (a zero-byte placeholder is touched on
disk so glob() finds them). Vectors are plain Python. Rasterisation is envelope-fill.
Attribute filters cover only the handful of SQL shapes the pipeline uses.

This verifies the pipeline's wiring, schemas and arithmetic. It does not verify GDAL.
"""
import math, os, pickle, re, sys, types
import numpy as np

FILES = {}      # normalised path -> _Dataset
VECTORS = {}    # normalised path -> DataSource


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


# ============================================================ gdal
GDT_Byte, GDT_Int32, GDT_Float32 = 1, 5, 6
_DT = {GDT_Byte: np.uint8, GDT_Int32: np.int32, GDT_Float32: np.float32, None: np.float32}


class _Band:
    def __init__(self, ds, i): self.ds, self.i = ds, i
    def ReadAsArray(self): return self.ds.bands[self.i].copy()
    def WriteArray(self, a):
        self.ds.bands[self.i][...] = np.asarray(a).astype(self.ds.bands[self.i].dtype)
        return 0
    def GetNoDataValue(self): return self.ds.nodata
    def SetNoDataValue(self, v): self.ds.nodata = v; return 0


class _Dataset:
    def __init__(self, w, h, nb, dtype, path=""):
        self.bands = [np.zeros((h, w), dtype) for _ in range(nb)]
        self.gt, self.proj, self.nodata, self.path = (0, 1, 0, 0, 0, -1), "", None, path
        self.RasterXSize, self.RasterYSize, self.RasterCount = w, h, nb
    def GetGeoTransform(self): return self.gt
    def SetGeoTransform(self, gt): self.gt = tuple(float(v) for v in gt); return 0
    def GetProjection(self): return self.proj
    def SetProjection(self, p): self.proj = p; return 0
    def GetRasterBand(self, i): return _Band(self, i - 1)
    def FlushCache(self): pass


def _register(path, ds):
    if path:
        FILES[_norm(path)] = ds
        open(path, "ab").close()          # so glob() sees it


class _Driver:
    def __init__(self, name): self.name = name
    def Create(self, path, w, h, nb=1, etype=None, options=None):
        ds = _Dataset(w, h, nb, _DT.get(etype, np.float32), path)
        _register(path, ds)
        return ds
    def CreateCopy(self, path, src, strict=0, options=None):
        ds = _Dataset(src.RasterXSize, src.RasterYSize, src.RasterCount, src.bands[0].dtype, path)
        for i, b in enumerate(src.bands): ds.bands[i][...] = b
        ds.gt, ds.proj, ds.nodata = src.gt, src.proj, src.nodata
        _register(path, ds)
        return ds


def _gdal_open(path, *a):
    k = _norm(path)
    if k not in FILES:
        raise RuntimeError(f"fake gdal: no registered raster at {path}")
    return FILES[k]


def _rasterize(ds, bands, layer, burn_values=None, options=None):
    attr = None
    for o in (options or []):
        if o.upper().startswith("ATTRIBUTE="): attr = o.split("=", 1)[1]
    gt = ds.gt
    for f in layer:
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty(): continue
        x0, x1, y0, y1 = g.GetEnvelope()
        c0 = max(int(math.floor((x0 - gt[0]) / gt[1])), 0)
        c1 = min(int(math.ceil((x1 - gt[0]) / gt[1])), ds.RasterXSize)
        r0 = max(int(math.floor((y1 - gt[3]) / gt[5])), 0)
        r1 = min(int(math.ceil((y0 - gt[3]) / gt[5])), ds.RasterYSize)
        if c1 <= c0 or r1 <= r0: continue
        val = f.GetField(attr) if attr else (burn_values[0] if burn_values else 1)
        for b in bands: ds.bands[b - 1][r0:r1, c0:c1] = val
    return 0


gdal = types.ModuleType("osgeo.gdal")
gdal.GDT_Byte, gdal.GDT_Int32, gdal.GDT_Float32 = GDT_Byte, GDT_Int32, GDT_Float32
gdal.UseExceptions = lambda: None
gdal.Open = _gdal_open
gdal.GetDriverByName = lambda n: _Driver(n)
gdal.RasterizeLayer = _rasterize
sys.modules["osgeo.gdal"] = gdal


# ============================================================ ogr
class Geometry:
    """POINT: (x,y). LINESTRING/LINEARRING: [(x,y)]. POLYGON: [ring,...] where ring is
    [(x,y)]. MULTIPOLYGON: [polygon,...] where polygon is [ring,...]. All plain lists."""
    def __init__(self, kind, data): self.kind, self.data = kind, data
    def GetGeometryName(self): return self.kind
    def GetGeometryCount(self):
        return len(self.data) if self.kind in ("POLYGON", "MULTIPOLYGON") else 0
    def GetGeometryRef(self, i):
        if self.kind == "POLYGON": return Geometry("LINEARRING", self.data[i])
        if self.kind == "MULTIPOLYGON": return Geometry("POLYGON", self.data[i])
        raise IndexError(self.kind)
    def GetPointCount(self):
        if self.kind == "POINT": return 1
        return len(self.data) if self.kind in ("LINESTRING", "LINEARRING") else 0
    def GetX(self, i=0): return self.data[0] if self.kind == "POINT" else self.data[i][0]
    def GetY(self, i=0): return self.data[1] if self.kind == "POINT" else self.data[i][1]
    def _pts(self):
        if self.kind == "POINT": return [self.data]
        if self.kind in ("LINESTRING", "LINEARRING"): return list(self.data)
        if self.kind == "POLYGON": return [p for r in self.data for p in r]
        return [p for poly in self.data for r in poly for p in r]
    def GetEnvelope(self):
        pts = self._pts()
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), max(xs), min(ys), max(ys))
    def IsEmpty(self): return len(self._pts()) == 0
    def Clone(self): return Geometry(self.kind, pickle.loads(pickle.dumps(self.data)))
    def ExportToWkb(self): return pickle.dumps((self.kind, self.data))
    def Length(self):
        p = self._pts()
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(p, p[1:]))
    def Intersection(self, other):
        x0, x1, y0, y1 = other.GetEnvelope()
        if self.kind in ("LINESTRING", "LINEARRING"):
            keep = [p for p in self.data if x0 <= p[0] <= x1 and y0 <= p[1] <= y1]
            return Geometry("LINESTRING", keep if len(keep) >= 2 else [])
        raise NotImplementedError("fake ogr: Intersection only for lines")
    def Buffer(self, d): return self.Clone()


def _from_wkb(b):
    kind, data = pickle.loads(b)
    return Geometry(kind, data)


def _from_wkt(s):
    m = re.match(r"\s*POLYGON\s*\(\((.*)\)\)\s*$", s)
    if not m: raise NotImplementedError("fake ogr: only POLYGON((...)) WKT")
    pts = [tuple(float(v) for v in pair.split()) for pair in m.group(1).split(",")]
    return Geometry("POLYGON", [pts])


class FieldDefn:
    def __init__(self, name, t=0): self.name = name
    def GetName(self): return self.name


class _LayerDefn:
    def __init__(self, names): self.names = list(names)
    def GetFieldIndex(self, n): return self.names.index(n) if n in self.names else -1
    def GetFieldCount(self): return len(self.names)
    def GetFieldDefn(self, i): return FieldDefn(self.names[i])


class Feature:
    def __init__(self, defn=None, fields=None, geom=None):
        self.defn, self.fields, self.geom = defn, dict(fields or {}), geom
    def GetField(self, n): return self.fields.get(n)
    def SetField(self, n, v): self.fields[n] = v
    def GetGeometryRef(self): return self.geom
    def SetGeometry(self, g): self.geom = g
    def GetFieldCount(self): return self.defn.GetFieldCount() if self.defn else len(self.fields)
    def GetFieldDefnRef(self, i): return self.defn.GetFieldDefn(i)


def _match(f, expr):
    if not expr: return True
    m = re.fullmatch(r'\s*"?(\w+)"?\s+IS NOT NULL\s+AND\s+"?(\w+)"?\s*!=\s*\'([^\']*)\'\s*', expr, re.I)
    if m: return f.GetField(m.group(1)) is not None and f.GetField(m.group(2)) != m.group(3)
    m = re.fullmatch(r'\s*"?(\w+)"?\s+IS NOT NULL\s*', expr, re.I)
    if m: return f.GetField(m.group(1)) is not None
    m = re.fullmatch(r'\s*"?(\w+)"?\s+IN\s*\((.*)\)\s*', expr, re.I)
    if m:
        vals = [v.strip().strip("'") for v in m.group(2).split(",")]
        return f.GetField(m.group(1)) in vals
    m = re.fullmatch(r"\s*\"?(\w+)\"?\s+LIKE\s+'%(.*)%'\s*", expr, re.I)
    if m: return m.group(2) in (f.GetField(m.group(1)) or "")
    raise NotImplementedError(f"fake ogr: attribute filter not understood: {expr!r}")


class Layer:
    def __init__(self, name, fieldnames=(), features=()):
        self.name, self.defn, self.features, self.filter = name, _LayerDefn(fieldnames), list(features), None
    def GetLayerDefn(self): return self.defn
    def SetAttributeFilter(self, expr): self.filter = expr; return 0
    def CreateField(self, fd): self.defn.names.append(fd.name); return 0
    def CreateFeature(self, f): self.features.append(f); return 0
    def __iter__(self): return (f for f in self.features if _match(f, self.filter))
    def GetFeatureCount(self): return sum(1 for _ in self)
    def GetExtent(self):
        pts = [p for f in self for p in f.geom._pts()]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), max(xs), min(ys), max(ys))


class DataSource:
    def __init__(self): self.layers = {}
    def GetLayer(self, name=0):
        if isinstance(name, str):
            if name not in self.layers: raise RuntimeError(f"fake ogr: no layer {name}")
            return self.layers[name]
        return list(self.layers.values())[name]
    def CreateLayer(self, name, srs=None, geom_type=None):
        L = Layer(name); self.layers[name] = L; return L


class _OgrDriver:
    def CreateDataSource(self, name): return DataSource()


def _ogr_open(path, update=0):
    k = _norm(path)
    if k not in VECTORS:
        raise RuntimeError(f"fake ogr: no registered datasource at {path}")
    return VECTORS[k]


ogr = types.ModuleType("osgeo.ogr")
ogr.wkbPoint, ogr.wkbLineString, ogr.wkbPolygon, ogr.wkbMultiPolygon = 1, 2, 3, 6
ogr.OFTInteger, ogr.OFTReal, ogr.OFTString = 0, 2, 4
ogr.UseExceptions = lambda: None
ogr.Open = _ogr_open
ogr.GetDriverByName = lambda n: _OgrDriver()
ogr.Geometry, ogr.Feature, ogr.Layer, ogr.DataSource, ogr.FieldDefn = Geometry, Feature, Layer, DataSource, FieldDefn
ogr.CreateGeometryFromWkb, ogr.CreateGeometryFromWkt = _from_wkb, _from_wkt
sys.modules["osgeo.ogr"] = ogr


# ============================================================ osr
class SpatialReference:
    def __init__(self): self.epsg = None
    def ImportFromEPSG(self, c): self.epsg = int(c); return 0
    def SetFromUserInput(self, s): self.epsg = int(str(s).split(":")[1]); return 0
    def ExportToWkt(self): return f"FAKE_WKT[EPSG:{self.epsg}]"
    def SetAxisMappingStrategy(self, s): pass


class CoordinateTransformation:
    def __init__(self, a, b): pass
    def TransformPoint(self, x, y, z=0.0): return (x, y, z)


osr = types.ModuleType("osgeo.osr")
osr.OAMS_TRADITIONAL_GIS_ORDER = 1
osr.SpatialReference, osr.CoordinateTransformation = SpatialReference, CoordinateTransformation
sys.modules["osgeo.osr"] = osr
