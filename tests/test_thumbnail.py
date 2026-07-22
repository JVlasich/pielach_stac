"""render_thumbnail: PNG output, longest edge capped at 512, no upscale."""

from osgeo import gdal

from stac.catalog.thumbnail import render_thumbnail, MAX_EDGE

gdal.UseExceptions()


class _Item:
    """Minimal stand-in: render_thumbnail reads .id, .get_self_href() and .properties."""
    def __init__(self, href, id, properties=None):
        self._href = str(href)
        self.id = id
        self.properties = properties or {}

    def get_self_href(self):
        return self._href


def _tif(path, w, h, bands, dtype=gdal.GDT_Byte):
    ds = gdal.GetDriverByName("GTiff").Create(str(path), w, h, bands, dtype)
    ds.SetGeoTransform((0, 1, 0, 0, 0, -1))
    for b in range(1, bands + 1):
        ds.GetRasterBand(b).Fill(40 * b)
    ds = None


def _open(href):
    ds = gdal.Open(href)
    drv, w, h = ds.GetDriver().ShortName, ds.RasterXSize, ds.RasterYSize
    ds = None
    return drv, w, h


def test_rgb_downscaled(tmp_path):
    _tif(tmp_path / "src.tif", 600, 400, 3)
    item = _Item(tmp_path / "item" / "item.json", "ortho")
    href = render_thumbnail(item, tmp_path / "src.tif", "rgb")

    assert href.endswith("ortho_thumbnail.png")
    drv, w, h = _open(href)
    assert drv == "PNG"
    assert max(w, h) == MAX_EDGE          # capped
    assert (w, h) == (512, 341)           # aspect preserved (600:400)


def test_hillshade_downscaled(tmp_path):
    _tif(tmp_path / "dtm.tif", 400, 600, 1, gdal.GDT_Float32)
    item = _Item(tmp_path / "item" / "item.json", "dtm")
    href = render_thumbnail(item, tmp_path / "dtm.tif", "hillshade")

    drv, w, h = _open(href)
    assert drv == "PNG"
    assert max(w, h) == MAX_EDGE
    assert (w, h) == (341, 512)


def test_no_upscale(tmp_path):
    _tif(tmp_path / "small.tif", 8, 8, 3)
    item = _Item(tmp_path / "item" / "item.json", "small")
    href = render_thumbnail(item, tmp_path / "small.tif", "rgb")

    _, w, h = _open(href)
    assert (w, h) == (8, 8)               # already under MAX_EDGE, kept native


def _masked_tif(path, w, h, vx0, vx1, vy0, vy1):
    """Float32 raster: nodata everywhere except the valid window [vx0:vx1, vy0:vy1)."""
    import numpy as np
    nd = -9999.0
    ds = gdal.GetDriverByName("GTiff").Create(str(path), w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((0, 1, 0, 0, 0, -1))
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nd)
    arr = np.full((h, w), nd, dtype="float32")
    arr[vy0:vy1, vx0:vx1] = 42.0
    b.WriteArray(arr)
    ds = None


def test_hillshade_cropped_to_data(tmp_path):
    # valid data fills a 400-wide, full-height window in an 800x800 grid (nodata margins)
    _masked_tif(tmp_path / "dtm.tif", 800, 800, 200, 600, 0, 800)
    item = _Item(tmp_path / "item" / "item.json", "dtm")
    href = render_thumbnail(item, tmp_path / "dtm.tif", "hillshade")

    _, w, h = _open(href)
    assert max(w, h) == MAX_EDGE
    # cropped to the 400x800 data window (aspect ~0.5), not the 800x800 grid (aspect 1.0)
    assert abs(w / h - 0.5) < 0.03


def test_hillshade_warped_to_4326(tmp_path):
    # legacy rasters carry no CRS, so the item's proj metadata drives the warp to 4326
    from osgeo import osr
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31256)
    p = tmp_path / "dtm.tif"
    ds = gdal.GetDriverByName("GTiff").Create(str(p), 400, 600, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((-53000, 25, 0, 340000, 0, -25))  # no SetProjection: CRS comes from the item
    ds.GetRasterBand(1).Fill(300.0)
    ds = None
    item = _Item(tmp_path / "item" / "item.json", "dtm",
                 properties={"proj:wkt2": srs.ExportToWkt()})
    href = render_thumbnail(item, p, "hillshade")

    out = gdal.Open(href)
    assert out.GetDriver().ShortName == "PNG"
    assert max(out.RasterXSize, out.RasterYSize) <= MAX_EDGE
    assert out.RasterCount == 2                    # gray + alpha => the warp ran (1-band = skipped)


def _las(path, n=800):
    import laspy
    import numpy as np
    rng = np.random.default_rng(0)
    x = np.concatenate([rng.uniform(0, 100, n), [0.0, 100.0, 0.0, 100.0]])  # corners pin the extent
    y = np.concatenate([rng.uniform(0, 50, n), [0.0, 0.0, 50.0, 50.0]])
    z = np.concatenate([rng.uniform(0, 10, n), [0.0, 0.0, 0.0, 0.0]])
    las = laspy.LasData(laspy.LasHeader(point_format=3))
    las.x, las.y, las.z = x, y, z
    las.write(str(path))


def test_pointcloud(tmp_path):
    _las(tmp_path / "pc.las")
    item = _Item(tmp_path / "item" / "item.json", "pc")
    href = render_thumbnail(item, tmp_path / "pc.las", "pointcloud")

    assert href.endswith("pc_thumbnail.png")
    drv, w, h = _open(href)
    assert drv == "PNG"
    assert max(w, h) == MAX_EDGE          # capped
    assert (w, h) == (512, 256)           # extent 100x50 -> x longer
