# type: ignore
"""Two decorator-registries: Reader and Populator

Readers return asset metadata
Extensions map metadata to Extension fields (build.py)"""

import hashlib
import json
import logging
import math
import mmap
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from opals import Info
from osgeo import gdal, ogr, osr

from ..core.log import opals_log

osr.UseExceptions()
gdal.UseExceptions()
gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")  # no .aux.xml next to assets
log = logging.getLogger(__name__)

# set by cli after config merge; nbThreads None = opals default (all CPUs)
OPALS_INFO = {"nbThreads": None, "exactComputation": True}

# footprint tuning. All in ground units, so every item is filtered the same way
# regardless of its pixel count (a pixel-derived threshold makes a gap survive in one
# campaign and vanish in the next, purely because the grids differ in size).
_FOOTPRINT_GRID = 2048    # px, longest edge of the working grid
_MIN_PART_M2    = 4000.0  # footprint parts below this are mask noise
_MIN_HOLE_M2    = 1000.0  # interior gaps below this are not represented
_SIMPLIFY_M     = 6.0     # vertex tolerance; above a gap's radius the ring collapses
_MIN_AREA_RATIO = 0.5     # footprint below this share of the valid area -> bbox rectangle


@dataclass
class AssetMeta:
    """Dataclass that holds all possible asset metadata.
    extractors will build their extension from these

    To be expanded for the other extensions"""
    # Pointcloud
    pc_count:      int                 | None = None
    pc_type:       str                 | None = None
    pc_density:    float               | None = None
    pc_schemas:    list[dict[str, Any]] = field(default_factory=list)
    pc_statistics: list[dict[str, Any]] = field(default_factory=list)
    pc_gps_time_min:  float            | None = None  # raw, weekseconds or adjusted standard
    pc_gps_time_max:  float            | None = None  # resolved to UTC in build (campaign date)

    # raster (STAC 1.1 unified bands feed both raster + eo populators)
    raster_bands:   list[dict[str, Any]] = field(default_factory=list)
    raster_sampling: str                | None = None  # "area" | "point" (raster:sampling)
    raster_spatial_resolution: float    | None = None  # abs(gt[1]), square pixels assumed
    dt_processing:  datetime            | None = None  # TIFFTAG_DATETIME, when the file was written

    # Projection metadata
    proj_wkt:       str      | None = None
    proj_epsg:      int      | None = None
    proj_shape:     list     | None = None  # [height, width] (proj:shape order)
    proj_transform: list     | None = None  # STAC proj:transform order
    proj_bbox:      list     | None = None  # native CRS [minx, miny, maxx, maxy]

    # General
    geometry_wgs84: dict     | None = None  # GeoJSON Polygon
    bbox_wgs84:     list     | None = None

    def __str__(self) -> str:
        def num(v):
            return "?" if v is None else (f"{v:,}" if isinstance(v, int) else f"{v:,.2f}")

        rows = []
        if self.pc_count is not None:
            parts = [f"{num(self.pc_count)} pts"]
            if self.pc_density is not None:
                parts.append(f"{self.pc_density:.2f} pts/m²")
            if self.pc_type:
                parts.append(self.pc_type)
            rows.append(("pointcloud", " · ".join(parts)))
        if self.pc_schemas:
            names = [d.get("name", "?") for d in self.pc_schemas]
            shown = ", ".join(names[:3]) + (f", +{len(names) - 3} more" if len(names) > 3 else "")
            rows.append(("schema", f"{len(names)} dims: {shown}"))
        if self.pc_statistics:
            rows.append(("statistics", f"{len(self.pc_statistics)} dims"))
        if self.pc_gps_time_min is not None:
            rows.append(("gps_time", f"{num(self.pc_gps_time_min)} → {num(self.pc_gps_time_max)}"))
        if self.proj_epsg or self.proj_wkt:
            crs = f"EPSG:{self.proj_epsg}" if self.proj_epsg else f"wkt: {self.proj_wkt[:50]}…"
            parts = [crs]
            if self.proj_shape:
                parts.append(f"shape {self.proj_shape[1]}×{self.proj_shape[0]}")
            if self.proj_bbox:
                parts.append("bbox [" + ", ".join(f"{v:.2f}" for v in self.proj_bbox) + "]")
            rows.append(("proj", " · ".join(parts)))
        if self.raster_bands:
            parts = [f"{len(self.raster_bands)} band(s)"]
            if self.raster_spatial_resolution is not None:
                parts.append(f"{self.raster_spatial_resolution:g} m/px")
            if self.raster_sampling:
                parts.append(f"sampling={self.raster_sampling}")
            rows.append(("raster", " · ".join(parts)))
        if self.dt_processing:
            rows.append(("processed", self.dt_processing.isoformat(sep=" ")))
        if self.bbox_wgs84:
            rows.append(("wgs84", "[" + ", ".join(f"{v:.5f}" for v in self.bbox_wgs84) + "]"))
        if not rows:
            return "AssetMeta(empty)"
        width = max(len(k) for k, _ in rows)
        lines = ["AssetMeta"]
        for i, (k, v) in enumerate(rows):
            branch = "└─" if i == len(rows) - 1 else "├─"
            lines.append(f"{branch} {k.ljust(width)}  {v}")
        return "\n".join(lines)


@dataclass
class FileMeta:
    size: int
    mtime: float
    sha256: str


def _dtype_name(gdal_type: int) -> str:
    """GDAL data type name to raster extension string (Byte -> uint8, Float32 -> float32)."""
    name = gdal.GetDataTypeName(gdal_type)
    return "uint8" if name == "Byte" else name.lower()


def _finite(v):
    """Non-finite floats to None, item JSON must stay parseable (NaN is invalid JSON)."""
    return None if isinstance(v, float) and not math.isfinite(v) else v


def _json_nodata(v):
    """Non-finite nodata to the raster extension's string forms ("nan", "inf", "-inf")."""
    if isinstance(v, float) and math.isnan(v):
        return "nan"
    if isinstance(v, float) and math.isinf(v):
        return "inf" if v > 0 else "-inf"
    return v


def _wgs84_footprint(srs, proj_bbox: list) -> tuple[dict, list]:
    """Native CRS bbox -> WGS84 (GeoJSON polygon, bbox) via densified edge transform,
    bundled GDAL 3.1 has no TransformBounds (3.4+)."""
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)  # lon,lat order
    ct = osr.CoordinateTransformation(srs, wgs84)
    n = 21
    ex = [proj_bbox[0] + (proj_bbox[2] - proj_bbox[0]) * i / n for i in range(n + 1)]
    ey = [proj_bbox[1] + (proj_bbox[3] - proj_bbox[1]) * i / n for i in range(n + 1)]
    ring = ([(x, proj_bbox[1]) for x in ex] + [(x, proj_bbox[3]) for x in ex]
            + [(proj_bbox[0], y) for y in ey] + [(proj_bbox[2], y) for y in ey])
    pts = ct.TransformPoints(ring)
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    lonmin, latmin, lonmax, latmax = min(lons), min(lats), max(lons), max(lats)
    geometry = {"type": "Polygon", "coordinates": [[
        [lonmin, latmin], [lonmax, latmin], [lonmax, latmax], [lonmin, latmax], [lonmin, latmin],
    ]]}
    return geometry, [lonmin, latmin, lonmax, latmax]


def _drop_small_holes(poly, min_hole: float):
    """Rebuild a polygon keeping its exterior ring and only interior rings >= min_hole.
    The surviving rings are the real data gaps, the point of publishing a footprint
    at all; sliver holes below the threshold are mask noise that blows up the ring
    count. Held apart from the part threshold: gaps are admitted much smaller than
    the outline pieces, so showing more gaps never fragments the outline."""
    out = ogr.Geometry(ogr.wkbPolygon)
    out.AddGeometry(poly.GetGeometryRef(0).Clone())  # exterior ring
    for i in range(1, poly.GetGeometryCount()):
        ring = poly.GetGeometryRef(i)
        tmp = ogr.Geometry(ogr.wkbPolygon)
        tmp.AddGeometry(ring.Clone())
        if tmp.GetArea() >= min_hole:
            out.AddGeometry(ring.Clone())
    return out


def _decimated_mask(band, w: int, h: int, k: int):
    """Band 1's mask reduced by k in both axes: a cell is valid when >= 50% of its
    source pixels are. Read at full resolution in row strips (k * w bytes at a time)
    rather than with buf_xsize, because a buffered read is served from the COG
    overviews, whose resampling marks a cell valid if *any* source pixel is and
    dilates the footprint by up to 3x. Trailing pixels are zero-padded, so the last
    row and column of cells need a full half-cell of data -- an edge effect well below
    the simplify tolerance. None when the mask cannot be read."""
    import numpy as np
    mask = band.GetMaskBand()
    bw, bh = -(-w // k), -(-h // k)
    out = np.zeros((bh, bw), dtype=bool)
    buf = np.zeros((k, bw * k), dtype=bool)
    for row in range(bh):
        y0 = row * k
        strip = mask.ReadAsArray(0, y0, w, min(k, h - y0))
        if strip is None:
            return None
        buf[:] = False
        buf[:strip.shape[0], :w] = strip > 0
        out[row] = buf.reshape(k, bw, k).mean(axis=(0, 2)) >= 0.5
    return out


def _mask_footprint(ds, gt, srs, w: int, h: int, valid_frac: float) -> tuple[dict, list] | None:
    """True data footprint from band 1's mask (nodata/alpha/internal): decimated
    read, polygonize, filter, simplify, reproject to WGS84. The interior rings are
    the real data gaps, and are what makes this worth publishing over the bbox.
    Returns (geometry, bbox) or None when the raster is fully valid, the mask gives
    nothing usable, or the result covers less than _MIN_AREA_RATIO of the actual
    valid area — caller keeps the bbox rectangle."""
    band = ds.GetRasterBand(1)
    if band.GetMaskFlags() == gdal.GMF_ALL_VALID:
        return None
    k = max(1, -(-max(w, h) // _FOOTPRINT_GRID))
    valid = _decimated_mask(band, w, h, k)
    if valid is None or valid.all() or not valid.any():
        return None  # rectangle is the truth / mask degenerate
    bh, bw = valid.shape

    mem = gdal.GetDriverByName("MEM").Create("", bw, bh, 1, gdal.GDT_Byte)
    mem.SetGeoTransform((gt[0], gt[1] * k, gt[2] * k, gt[3], gt[4] * k, gt[5] * k))
    mem.GetRasterBand(1).WriteArray(valid.astype("uint8") * 255)
    # drop speckle before polygonizing, where it is cheap: a noisy mask otherwise
    # yields thousands of sliver polygons that every later step has to carry
    cell_m2 = abs(gt[1] * gt[5]) * k * k
    gdal.SieveFilter(mem.GetRasterBand(1), None, mem.GetRasterBand(1),
                     max(1, int(min(_MIN_PART_M2, _MIN_HOLE_M2) / cell_m2)), 4)

    vds = ogr.GetDriverByName("Memory").CreateDataSource("")
    lyr = vds.CreateLayer("footprint", srs=srs)
    # mask arg = the band itself, so only valid regions become polygons. Polygonize
    # already emits one polygon per connected region with its gaps as interior rings,
    # so the parts need no union afterwards.
    gdal.Polygonize(mem.GetRasterBand(1), mem.GetRasterBand(1), lyr, -1)
    geom = ogr.Geometry(ogr.wkbMultiPolygon)
    for feat in lyr:
        g = feat.GetGeometryRef()
        if g is not None and g.GetArea() >= _MIN_PART_M2:
            geom.AddGeometry(_drop_small_holes(g, _MIN_HOLE_M2))
    if geom.IsEmpty():
        return None
    geom = geom.SimplifyPreserveTopology(_SIMPLIFY_M)
    if geom is None or geom.IsEmpty():
        return None

    # a footprint that lost most of the data is worse than no footprint: a sparse
    # mask shatters into parts that all fall under _MIN_PART_M2, and the remnant
    # would be published as the whole truth
    exact_m2 = valid_frac * w * h * abs(gt[1] * gt[5])
    if exact_m2 and geom.GetArea() < _MIN_AREA_RATIO * exact_m2:
        log.warning(f"footprint covers {geom.GetArea() / exact_m2:.0%} of the valid data, "
                    f"keeping bbox rectangle: {ds.GetDescription()}")
        return None

    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    geom.Transform(osr.CoordinateTransformation(srs, wgs84))
    minx, maxx, miny, maxy = geom.GetEnvelope()
    return json.loads(geom.ExportToJson()), [minx, miny, maxx, maxy]


def _fallback_srs(crs: str, path) -> "osr.SpatialReference":
    """Sidecar crs string (EPSG:xxxx or WKT) -> SpatialReference. Used only
    when the file itself carries no CRS."""
    log.warning(f"no CRS in file, using sidecar crs {crs!r}: {path}")
    srs = osr.SpatialReference()
    try:
        srs.SetFromUserInput(str(crs))
    except RuntimeError as e:
        raise ValueError(f"{path}: invalid sidecar crs {crs!r}: {e}\n expected: (EPSG:xxxx or WKT)") from e
    return srs


def raster(path: str, crs: str | None = None) -> AssetMeta:
    """Extracts relevant raster metadata using GDAL.
    Item datetime is campaign-driven and not read here; TIFFTAG_DATETIME is kept
    only as the processing timestamp. Band statistics are exact (full scan).
    geometry = mask-derived footprint, bbox rectangle fallback.
    crs = sidecar fallback, only consulted when the file has none.
    returns: AssetMeta object"""
    log.debug(f"extracting raster metadata: {path}")
    ds = gdal.Open(str(path))

    srs = ds.GetSpatialRef()
    if srs is None and crs:
        srs = _fallback_srs(crs, path)
    if srs is None:
        log.error(f"no CRS readable: {path}")
        raise ValueError(f"{path}: no CRS readable (check PROJ_LIB/GDAL_DATA, "
                         f"or set 'crs' in campaign.yaml)")

    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize

    bands = []
    for i in range(1, ds.RasterCount + 1):
        b = ds.GetRasterBand(i)
        minimum, maximum, mean, stddev = (_finite(v) for v in b.ComputeStatistics(False))
        if b.GetMaskFlags() == gdal.GMF_ALL_VALID:
            valid_percent, count = 100.0, w * h
        else:
            # mask mean / 255 assumes binary mask, partial alpha skews valid_percent
            frac = b.GetMaskBand().ComputeStatistics(False)[2] / 255.0
            valid_percent, count = frac * 100, round(frac * w * h)
        nbits = b.GetMetadataItem("NBITS", "IMAGE_STRUCTURE")
        bands.append({
            "index":        i,
            "data_type":    _dtype_name(b.DataType),
            "nodata":       _json_nodata(b.GetNoDataValue()),
            "color_interp": gdal.GetColorInterpretationName(b.GetColorInterpretation()).lower(),
            "description":  b.GetDescription() or None,
            "unit":         b.GetUnitType() or None,
            "scale":        b.GetScale(),
            "offset":       b.GetOffset(),
            "bits_per_sample": int(nbits) if nbits else None,
            "statistics":   {"minimum": minimum, "maximum": maximum, "mean": mean, "stddev": stddev,
                             "valid_percent": valid_percent, "count": count},
        })

    # native bbox from geotransform corners (handles rotated rasters)
    xs = [gt[0], gt[0] + w * gt[1], gt[0] + h * gt[2], gt[0] + w * gt[1] + h * gt[2]]
    ys = [gt[3], gt[3] + w * gt[4], gt[3] + h * gt[5], gt[3] + w * gt[4] + h * gt[5]]
    proj_bbox = [min(xs), min(ys), max(xs), max(ys)]

    geometry, bbox_wgs84 = _wgs84_footprint(srs, proj_bbox)
    try:
        fp = _mask_footprint(ds, gt, srs, w, h,
                             bands[0]["statistics"]["valid_percent"] / 100)
    except Exception as e:
        log.warning(f"footprint failed, keeping bbox rectangle ({path}): {e}")
        fp = None
    if fp:
        geometry, bbox_wgs84 = fp

    code = srs.GetAuthorityCode(None)

    dt = None
    raw = ds.GetMetadataItem("TIFFTAG_DATETIME")
    if raw:
        try:
            dt = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            log.debug(f"unparseable TIFFTAG_DATETIME {raw!r} in {path}")

    return AssetMeta(
        raster_bands=bands,
        raster_sampling=(ds.GetMetadataItem("AREA_OR_POINT") or "").lower() or None,
        raster_spatial_resolution=abs(gt[1]),
        proj_epsg=int(code) if code else None,
        proj_wkt=srs.ExportToWkt(["FORMAT=WKT2_2018"]),
        proj_shape=[h, w],
        proj_transform=[gt[1], gt[2], gt[0], gt[4], gt[5], gt[3]],
        proj_bbox=proj_bbox,
        geometry_wgs84=geometry,
        bbox_wgs84=bbox_wgs84,
        dt_processing=dt,
    )


def _attr_name(a) -> str:
    """getName() returns "Shortname (Longname)"; the longname disambiguates dims
    that share a shortname (e.g. two Amplitudes). Whole string when no parens."""
    full = a.getName()
    m = re.search(r"\((.*)\)\s*$", full)
    return m.group(1) if m else full


def pointcloud(path: str, crs: str | None = None) -> AssetMeta:
    """Extracts relevant pointcloud metadata using opalsInfo.
    Attributes are only extracted if they have more than one possible value.
    crs = sidecar fallback, only consulted when the file has none.
    returns: AssetMeta object"""
    log.debug(f"extracting pointcloud metadata: {path}")
    inf = Info.Info()
    inf.inFile = str(path)
    inf.exactComputation = int(OPALS_INFO["exactComputation"])
    if OPALS_INFO["nbThreads"]:
        inf.commons.nbThreads = OPALS_INFO["nbThreads"]
    opals_log(inf)
    inf.run()

    stats = inf.statistic[0]
    attributes = stats.getAttributes()

    statistics = [
        {
            "name":    _attr_name(a),
            "count":   a.getCount(),
            "minimum": _finite(a.getMin()),
            "maximum": _finite(a.getMax()),
            "average": _finite(a.getMean()),
            "stddev":  _finite(a.getStd()),
        } for a in attributes if a.getMin() != a.getMax()  # constant dims carry no signal
    ]
    statistics = [{k: v for k, v in s.items() if v is not None} for s in statistics]

    # schemas list every dimension the file has, unfiltered (pc:schemas = truth)
    schemas = [
        {
            "name": _attr_name(a),
            "size": a.getStorageSize(),
            "type": a.getType()  # DM::ColumnType int mapped in build.py
        } for a in attributes # constant dimns are still extracted
    ]

    # raw GPSTime, resolved to UTC in build; found by shortname so the display
    # name stays free; constant GPSTime is filtered out
    gps_attr = next((a for a in attributes
                     if a.getName().split()[0] == "GPSTime" and a.getMin() != a.getMax()
                     and math.isfinite(a.getMin()) and math.isfinite(a.getMax())), None)
    gps = {"minimum": gps_attr.getMin(), "maximum": gps_attr.getMax()} if gps_attr else None

    wkt = stats.getCoordRefSys()
    if wkt:
        srs = osr.SpatialReference()
        if srs.ImportFromWkt(wkt) != 0:
            raise ValueError(f"{path}: invalid CRS WKT")
    elif crs:
        srs = _fallback_srs(crs, path)
        wkt = srs.ExportToWkt(["FORMAT=WKT2_2018"])
    else:
        log.error(f"no CRS readable: {path}")
        raise ValueError(f"{path}: no CRS readable (check PROJ_LIB/GDAL_DATA, "
                         f"or set 'crs' in campaign.yaml)")

    # EPSG attempt so pointcloud items get proj:code like rasters do
    code = srs.GetAuthorityCode(None)
    if code is None:
        try:
            if srs.AutoIdentifyEPSG() == 0:
                code = srs.GetAuthorityCode(None)
        except RuntimeError:
            pass  # exotic/compound CRS without a match, wkt2 still carries it

    bb = stats.getBoundingBox()  # xmin, ymin, zmin, xmax, ymax, zmax
    proj_bbox = [bb[0], bb[1], bb[3], bb[4]]
    geometry, bbox_wgs84 = _wgs84_footprint(srs, proj_bbox)

    density = stats.getPointDensity()
    return AssetMeta(
        pc_count=stats.getPointCount(),
        pc_density=None if math.isnan(density) else density,  # nan when exactComputation off
        pc_type="lidar", # hmmmmmm hardcoding
        pc_schemas=schemas,
        pc_statistics=statistics, # gpstime duplicate here
        pc_gps_time_min=gps["minimum"] if gps else None,
        pc_gps_time_max=gps["maximum"] if gps else None,
        proj_epsg=int(code) if code else None,
        proj_wkt=wkt,
        proj_bbox=proj_bbox,
        geometry_wgs84=geometry,
        bbox_wgs84=bbox_wgs84,
    )


def file_meta(p: Path | str) -> FileMeta:
    """Reads File Metadata to compare against existing assets.
    Used in idempotency pipeline to reduce runtime
    by only calling other readers if changes are detected"""
    # checks
    p = Path(p)
    if not (p.exists() and p.is_file()):
        raise ValueError("Path doesnt exist or is not a file")

    # stats
    stat = p.stat()
    mtime, size = stat.st_mtime, stat.st_size

    # hash, mmap faster but fails on 0 size files, why would they exist tho?
    hash_object = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                hash_object.update(mm)
        hash = hash_object.hexdigest()
    except ValueError as e:
        log.exception(f"Error while computing hash for file: {p}, assets cannot be empty",
                      stack_info=True)
        raise e

    return FileMeta(size=size, mtime=mtime, sha256=hash)


def pcl_point_count(p: Path | str) -> int:
    """Point count from the LAS public header, uncompressed in .las/.laz/.copc.laz
    alike (no point decompression, ~7 ms). Lets the minPoints filter drop degenerate
    tiles before the expensive opals build."""
    import laspy
    with laspy.open(str(p)) as r:
        return r.header.point_count


# kind → fn(path, needed_exts) -> AssetMeta (I/O once, gated)
_readers: dict[str, Callable] = {
    "raster": raster,
    "pcl": pointcloud,
    "file_meta":file_meta
}


# Baseline (always, not extension-gated): WGS84 `geometry` (polygon) + `bbox`
# plus the fields needed for id/datetime.


# --- self-check ---

if __name__ == "__main__":
    import sys

    from ..core.log import setup

    setup()

    args = sys.argv[1:]
    target = Path(args[0]) if args else next(Path("data/sample_tif").rglob("*.tif"))

    if target.name.lower().endswith((".laz", ".las")):
        meta = pointcloud(target)
        assert meta.pc_count, "no points"
        # schemas = every dim (unfiltered), stats subset, longnames verbatim and unique
        schema_names = {s["name"] for s in meta.pc_schemas}
        assert {s["name"] for s in meta.pc_statistics} <= schema_names
        assert len(schema_names) == len(meta.pc_schemas), schema_names
        lonmin, latmin, lonmax, latmax = meta.bbox_wgs84
        assert -180 <= lonmin <= lonmax <= 180 and -90 <= latmin <= latmax <= 90, meta.bbox_wgs84
        log.info(f"{target.name}: count={meta.pc_count} density={meta.pc_density:.2f} epsg={meta.proj_epsg}")
        log.info(f"  bbox_wgs84={[round(v, 6) for v in meta.bbox_wgs84]}")
        log.info(f"  gps_time min={meta.pc_gps_time_min} max={meta.pc_gps_time_max}")
        log.debug(f"  {meta.pc_statistics=}")
        log.info("pointcloud self-check ok")
        sys.exit(0)

    meta = raster(target)

    assert meta.raster_bands, "no bands extracted"
    assert meta.proj_epsg or meta.proj_wkt, "no CRS info"
    lonmin, latmin, lonmax, latmax = meta.bbox_wgs84
    assert -180 <= lonmin <= lonmax <= 180 and -90 <= latmin <= latmax <= 90, meta.bbox_wgs84

    log.info(f"{target.name}: epsg={meta.proj_epsg} shape={meta.proj_shape} dt={meta.dt_processing}")
    log.info(f"  sampling={meta.raster_sampling} resolution={meta.raster_spatial_resolution}")
    log.info(f"  bbox_wgs84={[round(v, 6) for v in meta.bbox_wgs84]}")
    for b in meta.raster_bands:
        s = b["statistics"]
        assert 0 <= s["valid_percent"] <= 100, s
        log.info(f"  band {b['index']} {b['data_type']} {b['color_interp']} nodata={b['nodata']} "
                 f"unit={b['unit']} scale={b['scale']} offset={b['offset']} nbits={b['bits_per_sample']} "
                 f"min={s['minimum']:.3f} max={s['maximum']:.3f} mean={s['mean']:.3f} std={s['stddev']:.3f} "
                 f"valid={s['valid_percent']:.1f}% count={s['count']}")
        log.debug(f"\n{meta}")
    log.info("raster self-check ok")
