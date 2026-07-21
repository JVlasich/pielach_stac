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
    # 32x32 all-valid grid poked with single-pixel nodata holes (each far below (3px)^2).
    # The exterior stays a rectangle; every sliver hole must be filtered out.
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
