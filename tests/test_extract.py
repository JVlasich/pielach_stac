import json
import struct

import pytest
from osgeo import gdal, osr

from stac.catalog.extract import raster


def _interior_rings(geom: dict) -> int:
    """Total interior (hole) rings across a GeoJSON Polygon / MultiPolygon."""
    if geom["type"] == "Polygon":
        return len(geom["coordinates"]) - 1
    return sum(len(poly) - 1 for poly in geom["coordinates"])


def test_crs_fallback(tmp_path, write_tif, write_tif_no_crs):
    write_tif_no_crs(tmp_path / "bare.tif")

    # no CRS anywhere: raise
    with pytest.raises(ValueError, match="no CRS readable"):
        raster(tmp_path / "bare.tif")

    # sidecar fallback fills in
    meta = raster(tmp_path / "bare.tif", crs="EPSG:31256")
    assert meta.proj_epsg == 31256
    assert meta.bbox_wgs84 is not None

    # file CRS wins over fallback
    write_tif(tmp_path / "georef.tif", 10)
    meta = raster(tmp_path / "georef.tif", crs="EPSG:25833")
    assert meta.proj_epsg == 31256

    # garbage fallback: raise
    with pytest.raises(ValueError, match="invalid sidecar crs"):
        raster(tmp_path / "bare.tif", crs="EPSG:nonsense")


def test_mask_footprint_shrinks_geometry(tmp_path, write_tif, write_masked_tif):
    write_tif(tmp_path / "full.tif", 10, 64)
    write_masked_tif(tmp_path / "masked.tif")
    full = raster(tmp_path / "full.tif")
    masked = raster(tmp_path / "masked.tif")

    # same grid, same native extent
    assert masked.proj_bbox == full.proj_bbox

    # all-valid raster keeps the bbox rectangle
    assert full.geometry_wgs84["type"] == "Polygon"
    assert len(full.geometry_wgs84["coordinates"][0]) == 5

    # masked raster: footprint covers only the valid left half
    assert masked.geometry_wgs84["type"] in ("Polygon", "MultiPolygon")
    assert masked.bbox_wgs84[2] < full.bbox_wgs84[2], "lonmax should shrink"
    assert masked.bbox_wgs84[0] >= full.bbox_wgs84[0] - 1e-9
    assert masked.bbox_wgs84[1] >= full.bbox_wgs84[1] - 1e-9
    assert masked.bbox_wgs84[3] <= full.bbox_wgs84[3] + 1e-9


def test_nan_nodata_stays_json_safe(tmp_path):
    # float raster with nodata=NaN: bands must serialize as strict JSON
    # (raw NaN would leak as invalid JSON into the item files)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31256)
    ds = gdal.GetDriverByName("GTiff").Create(str(tmp_path / "nan.tif"), 4, 4, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((-53000, 25, 0, 340000, 0, -25))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float("nan"))
    band.Fill(5.0)
    band.WriteRaster(0, 0, 2, 4, struct.pack("<8f", *[float("nan")] * 8),
                     buf_type=gdal.GDT_Float32)
    ds = None

    meta = raster(tmp_path / "nan.tif")
    b = meta.raster_bands[0]
    assert b["nodata"] == "nan"
    s = b["statistics"]
    assert s["minimum"] == 5.0 and s["maximum"] == 5.0, "stats over valid pixels only"
    json.dumps(meta.raster_bands, allow_nan=False)  # raises on any leftover NaN/Inf


def test_footprint_drops_sliver_holes(tmp_path):
    # 32x32 all-valid grid poked with single-pixel nodata holes (625 m^2 each at 25 m/px,
    # under _MIN_HOLE_M2). The exterior stays a rectangle; every sliver hole is filtered out.
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31256)
    ds = gdal.GetDriverByName("GTiff").Create(str(tmp_path / "holed.tif"), 32, 32, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((-53000, 25, 0, 340000, 0, -25))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(0)
    band.Fill(255)
    for x, y in [(5, 5), (9, 7), (14, 20), (20, 8), (24, 24),
                 (6, 22), (23, 14), (17, 12), (11, 17), (22, 19)]:
        band.WriteRaster(x, y, 1, 1, bytes([0]))
    ds = None

    meta = raster(tmp_path / "holed.tif")
    assert _interior_rings(meta.geometry_wgs84) == 0, "sliver holes not filtered"


def _gapped_tif(path, n: int, px: float, gaps: list) -> None:
    """n x n all-valid Byte grid at px metres, poked with square nodata gaps.
    gaps = [(x, y, side_px), ...]."""
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31256)
    ds = gdal.GetDriverByName("GTiff").Create(str(path), n, n, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((-53000, px, 0, 340000, 0, -px))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(0)
    band.Fill(255)
    for x, y, side in gaps:
        band.WriteRaster(x, y, side, side, bytes([0]) * (side * side))
    ds = None


def test_gap_survives_regardless_of_ground_extent(tmp_path):
    # Same 2025 m^2 gap in two rasters of the same pixel count but very different ground
    # extent (1 km vs 6 km). The old pixel-derived threshold scaled with extent, so the gap
    # was published for the small raster and silently dropped for the large one.
    _gapped_tif(tmp_path / "small.tif", 1024, 1.0, [(400, 400, 45)])
    _gapped_tif(tmp_path / "large.tif", 1024, 6.0, [(400, 400, 8)])  # 48 m -> 2304 m^2

    for name in ("small.tif", "large.tif"):
        meta = raster(tmp_path / name)
        assert _interior_rings(meta.geometry_wgs84) == 1, f"gap not represented in {name}"


def test_gap_threshold_is_a_ground_area(tmp_path):
    # 1521 m^2 gap is above _MIN_HOLE_M2 and must show; 196 m^2 is below and must not.
    _gapped_tif(tmp_path / "two.tif", 512, 1.0, [(60, 60, 39), (300, 300, 14)])

    meta = raster(tmp_path / "two.tif")
    assert _interior_rings(meta.geometry_wgs84) == 1, "wrong number of gaps kept"


def test_shattered_mask_falls_back_to_bbox(tmp_path, caplog):
    # Valid data scattered into blobs that nearly all fall under _MIN_PART_M2: the surviving
    # footprint would claim ~5% of the actual data, so the bbox rectangle is published instead.
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31256)
    ds = gdal.GetDriverByName("GTiff").Create(str(tmp_path / "shattered.tif"), 1024, 1024, 1,
                                              gdal.GDT_Byte)
    ds.SetGeoTransform((-53000, 1.0, 0, 340000, 0, -1.0))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(0)
    band.Fill(0)
    for i in range(8):
        for j in range(8):
            side = 100 if (i, j) == (0, 0) else 55   # one part above _MIN_PART_M2, 63 below
            band.WriteRaster(10 + 128 * i, 10 + 128 * j, side, side, bytes([255]) * (side * side))
    ds = None

    with caplog.at_level("WARNING"):
        meta = raster(tmp_path / "shattered.tif")

    assert meta.geometry_wgs84["type"] == "Polygon"
    assert len(meta.geometry_wgs84["coordinates"][0]) == 5, "expected the bbox rectangle"
    assert any("keeping bbox rectangle" in r.message for r in caplog.records)
