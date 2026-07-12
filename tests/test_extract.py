from stac.catalog.extract import raster


def test_mask_footprint_shrinks_geometry(tmp_path, write_tif, write_masked_tif):
    write_tif(tmp_path / "full.tif", 10, 16)
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
