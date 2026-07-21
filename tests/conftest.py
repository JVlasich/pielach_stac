import pytest
from osgeo import gdal, osr

gdal.UseExceptions()


def _write_tif(path, value: int, size: int = 4) -> None:
    """Small georeferenced GTiff (uncompressed = content change keeps the size)."""
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31256)
    ds = gdal.GetDriverByName("GTiff").Create(str(path), size, size, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((-53000, 25, 0, 340000, 0, -25))
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).Fill(value)
    ds = None


def _write_masked_tif(path, value: int = 100) -> None:
    """64x64 on the _write_tif grid, nodata=0, only the left half holds data. Large enough that
    the valid half survives the footprint min-part filter ((10 px)^2 at 25 m/px = 62500 m^2)."""
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31256)
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 64, 64, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((-53000, 25, 0, 340000, 0, -25))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(0)
    band.Fill(0)
    band.WriteRaster(0, 0, 32, 64, bytes([value]) * (32 * 64))
    ds = None


def _write_tif_no_crs(path, size: int = 4) -> None:
    """Georeferenced grid but no CRS declared (legacy-file case)."""
    ds = gdal.GetDriverByName("GTiff").Create(str(path), size, size, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((-53000, 25, 0, 340000, 0, -25))
    ds.GetRasterBand(1).Fill(10)
    ds = None


@pytest.fixture
def write_tif():
    return _write_tif


@pytest.fixture
def write_tif_no_crs():
    return _write_tif_no_crs


@pytest.fixture
def write_masked_tif():
    return _write_masked_tif
