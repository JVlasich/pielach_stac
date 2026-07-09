# type: ignore
"""Two decorator-registries: Reader and Populator

Readers return asset metadata
Extensions map metadata to Extension fields (build.py)"""

import hashlib
import logging
import mmap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import opals
from opals import Info
from osgeo import gdal, osr

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")  # no .aux.xml droppings next to assets
log = logging.getLogger(__name__)


@dataclass
class AssetMeta:
    """Dataclass that holds all possible asset metadata.
    extractors will build their extension from these

    To be expanded for the other extensions"""
    # Pointcloud
    pc_count:      int                 | None = None
    pc_type:       str                 | None = None
    pc_density:    float               | None = None
    pc_schemas:    list[dict[str:Any]] = field(default_factory=list)
    pc_statistics: list[dict[str:Any]] = field(default_factory=list)
    pc_gps_time_min:  float            | None = None  # raw, weekseconds or adjusted standard
    pc_gps_time_max:  float            | None = None  # resolved to UTC in build (campaign date)

    # Projection metadata
    proj_wkt:       str      | None = None
    proj_epsg:      int      | None = None
    proj_shape:     list     | None = None  # [height, width] (proj:shape order)
    proj_transform: list     | None = None  # STAC proj:transform order
    proj_bbox:      list     | None = None  # native CRS [minx, miny, maxx, maxy]

    # raster (STAC 1.1 unified bands feed both raster + eo populators)
    raster_bands:   list[dict[str:Any]] = field(default_factory=list)
    raster_sampling: str     | None = None  # "area" | "point" (raster:sampling)
    raster_spatial_resolution: float | None = None  # abs(gt[1]), square pixels assumed
    dt_processing:  datetime     | None = None  # TIFFTAG_DATETIME, when the file was written

    # General
    geometry_wgs84: dict         | None = None  # GeoJSON Polygon
    bbox_wgs84:     list         | None = None


@dataclass
class FileMeta:
    size: int
    mtime: float
    sha256: str


def _dtype_name(gdal_type: int) -> str:
    """GDAL data type name to raster extension string (Byte -> uint8, Float32 -> float32)."""
    name = gdal.GetDataTypeName(gdal_type)
    return "uint8" if name == "Byte" else name.lower()


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


def raster(path: str) -> AssetMeta:
    """Extracts relevant raster metadata using GDAL.
    Item datetime is campaign-driven and not read here; TIFFTAG_DATETIME is kept
    only as the processing timestamp. Band statistics are exact (full scan).
    returns: AssetMeta object"""
    ds = gdal.Open(str(path))

    srs = ds.GetSpatialRef()
    if srs is None:
        log.error(f"no CRS readable: {path}")
        raise ValueError(f"{path}: no CRS readable (check PROJ_LIB/GDAL_DATA)")

    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize

    bands = []
    for i in range(1, ds.RasterCount + 1):
        b = ds.GetRasterBand(i)
        minimum, maximum, mean, stddev = b.ComputeStatistics(False)
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
            "nodata":       b.GetNoDataValue(),
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
        proj_wkt=srs.ExportToWkt(["FORMAT=WKT2_2019"]),
        proj_shape=[h, w],
        proj_transform=[gt[1], gt[2], gt[0], gt[4], gt[5], gt[3]],
        proj_bbox=proj_bbox,
        geometry_wgs84=geometry,
        bbox_wgs84=bbox_wgs84,
        dt_processing=dt,
    )


def pointcloud(path: str) -> AssetMeta:
    """Extracts relevant pointcloud metadata using opalsInfo.
    Attributes are only extracted if they have more than one possible value.
    returns: AssetMeta object"""
    logLevel = opals.Types.LogLevel.none
    inf = Info.Info()
    inf.inFile = str(path)
    inf.exactComputation = 1
    inf.commons.screenLogLevel = logLevel
    inf.commons.fileLogLevel = logLevel
    inf.run()

    stats = inf.statistic[0]
    attributes = stats.getAttributes()

    statistics = [
        {
            "name":    a.getName(),#.split()[0], # Names are doubled?
            "count":   a.getCount(),
            "minimum": a.getMin(),
            "maximum": a.getMax(),
            "average": a.getMean(),
            "stddev":  a.getStd(),
        } for a in attributes if a.getMin() != a.getMax()
    ]

    schemas = [
        {
            "name":a.getName(),
            "size":a.getStorageSize(),
            "type":a.getType() # DM::ColumnType int mapped in build.py
        } for a in attributes if a.getMin() != a.getMax()
    ]

    # raw GPSTime, resolved to UTC in build; constant GPSTime is filtered out
    gps = next((s for s in statistics if s["name"].startswith("GPSTime")), None)

    wkt = stats.getCoordRefSys()
    if not wkt:
        log.error(f"no CRS readable: {path}")
        raise ValueError(f"{path}: no CRS readable (check PROJ_LIB/GDAL_DATA)")
    srs = osr.SpatialReference()
    if srs.ImportFromWkt(wkt) != 0:
        raise ValueError(f"{path}: invalid CRS WKT")

    bb = stats.getBoundingBox()  # xmin, ymin, zmin, xmax, ymax, zmax
    proj_bbox = [bb[0], bb[1], bb[3], bb[4]]
    geometry, bbox_wgs84 = _wgs84_footprint(srs, proj_bbox)

    return AssetMeta(
        pc_count=stats.getPointCount(),
        pc_density=stats.getPointDensity(),
        pc_type="lidar", # hmmmmmm hardcoding
        pc_schemas=schemas,
        pc_statistics=statistics,
        pc_gps_time_min=gps["minimum"] if gps else None,
        pc_gps_time_max=gps["maximum"] if gps else None,
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
    if isinstance(p, str):
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
        print(f"Error while computing hash for file: {p}, assets cannot be empty")
        raise e

    return FileMeta(size=size, mtime=mtime, sha256=hash)


# kind → fn(path, needed_exts) -> AssetMeta (I/O once, gated)
_readers: dict[str, Callable] = {
    "raster": raster,
    "pointcloud": pointcloud,
    "file_meta":file_meta
}


# Baseline (always, not extension-gated): WGS84 `geometry` (polygon) + `bbox`
# plus the fields needed for id/datetime.


# --- self-check ---

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    target = Path(args[0]) if args else next(Path("data/sample_tif").rglob("*.tif"))

    if target.name.lower().endswith((".laz", ".las")):
        meta = pointcloud(target)
        assert meta.pc_count, "no points"
        lonmin, latmin, lonmax, latmax = meta.bbox_wgs84
        assert -180 <= lonmin <= lonmax <= 180 and -90 <= latmin <= latmax <= 90, meta.bbox_wgs84
        print(f"{target.name}: count={meta.pc_count} density={meta.pc_density:.2f}")
        print(f"  bbox_wgs84={[round(v, 6) for v in meta.bbox_wgs84]}")
        print(f"  gps_time min={meta.pc_gps_time_min} max={meta.pc_gps_time_max}")
        print(f"  {meta.pc_statistics=}")
        print("pointcloud self-check ok")
        sys.exit(0)

    meta = raster(target)

    assert meta.raster_bands, "no bands extracted"
    assert meta.proj_epsg or meta.proj_wkt, "no CRS info"
    lonmin, latmin, lonmax, latmax = meta.bbox_wgs84
    assert -180 <= lonmin <= lonmax <= 180 and -90 <= latmin <= latmax <= 90, meta.bbox_wgs84

    print(f"{target.name}: epsg={meta.proj_epsg} shape={meta.proj_shape} dt={meta.dt_processing}")
    print(f"  sampling={meta.raster_sampling} resolution={meta.raster_spatial_resolution}")
    print(f"  bbox_wgs84={[round(v, 6) for v in meta.bbox_wgs84]}")
    for b in meta.raster_bands:
        s = b["statistics"]
        assert 0 <= s["valid_percent"] <= 100, s
        print(f"  band {b['index']} {b['data_type']} {b['color_interp']} nodata={b['nodata']} "
              f"unit={b['unit']} scale={b['scale']} offset={b['offset']} nbits={b['bits_per_sample']} "
              f"min={s['minimum']:.3f} max={s['maximum']:.3f} mean={s['mean']:.3f} std={s['stddev']:.3f} "
              f"valid={s['valid_percent']:.1f}% count={s['count']}\n\n")
        print("#"*100+"\n", meta)
    print("raster self-check ok")
