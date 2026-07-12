import io
import logging

import pytest
from osgeo import gdal

from stac.catalog.discover import COG_MEDIA_TYPE, _ISO_DATE, discover

gdal.UseExceptions()


def _write_raster(path, cog: bool) -> None:
    mem = gdal.GetDriverByName("MEM").Create("", 2, 2, 1)
    out = gdal.GetDriverByName("COG" if cog else "GTiff").CreateCopy(str(path), mem)
    out = None


def _make_fixture(tmp) -> None:
    # rasters get real 2x2 px content so the probe runs for real: True = COG driver
    rasters = {
        "pielach_2023-02-08_DTM_etrs89_cog.tif": True,      # CN twin -> supersedes plain
        "pielach_2023-02-08_DTM_etrs89.tif": False,         # non-CN twin -> superseded
        "pielach_2023-02-08_DTM_masked_etrs89_cog.tif": True,  # variant -> own item
        "pielach_2023-02-08_DTM_filled_etrs89_cog.tif": True,  # both-CN twin pair:
        "pielach_2023-02-08_DTM_filled_etrs89.tif": True,      #   cog-named wins silently
        "pielach_2023-02-08_DSM_filled_etrs89.tif": True,   # plain-named real COG -> CN, no warning
        "pielach_2023-02-08_DSM_etrs89.tif": False,         # lone non-CN -> cataloged + warned
        "pielach_2023-02-08_transparent_mosaic_cog.tif": True,  # orthophoto, flat
        "dtm_dateless_etrs89.tif": False,                   # no date token -> id gets prefixed
    }
    touched = [
        "tiles/pielach_2023-02-08_526000_534050.copc.laz",  # tile group "tiles"
        "tiles/pielach_2023-02-08_526500_534050.copc.laz",
        "pielach_2023-02-08_ground.laz",                  # lone non-CN pointcloud, flat
        "pielach_2023-02-08_ground.las",                  # ext-mix twin -> laz preferred + warning
        "pielach_2023-02-08_DTM_shd.tif",                 # shade -> ignore category, silent
        "pielach_2023-02-08_DTM_etrs89_cog.tfw",          # sidecar
        "pielach_2023-02-08_DTM_etrs89_cog.prj",          # sidecar
        "pielach_2023-02-08_DTM_etrs89_cog.tif.aux.xml",  # GDAL PAM sidecar (full-name form)
        "tiles/pielach_2023-02-08_ground.prj",            # wrong dir -> never attaches
        "campaign.yaml",                                  # per-campaign sidecar, never an asset
        "opalsLog.xml",                                   # stray
    ]
    for n, cog in rasters.items():
        _write_raster(tmp / n, cog)
    for n in touched:
        p = tmp / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


@pytest.fixture(scope="module")
def discovered(tmp_path_factory):
    """Fixture tree discovered once: (tree root, products, captured warnings)."""
    tmp = tmp_path_factory.mktemp("discover_fix")
    _make_fixture(tmp)
    buf = io.StringIO()
    capture = logging.StreamHandler(buf)
    logging.getLogger().addHandler(capture)
    try:
        products = discover(tmp, policy_unknown="warn", id_prefix="pielach_2023-02-08")
    finally:
        logging.getLogger().removeHandler(capture)
    return tmp, products, buf.getvalue()


@pytest.fixture(scope="module")
def by_id(discovered):
    _, products, _ = discovered
    return {p.id: p for p in products}


def test_products_shape(discovered, by_id):
    _, products, _ = discovered
    assert len(products) == 10, sorted(by_id)
    assert all(len(p.assets) == 1 for p in products)
    assert all(_ISO_DATE.search(p.id) for p in products)


def test_cog_twin_supersedes_plain_variant_stays_separate(by_id):
    # variants ungrouped: DTM and DTM_masked are separate items
    assert "pielach_2023-02-08_DTM_masked_etrs89" in by_id

    # cog twin superseded the plain DTM: id keeps no cog token, asset is the COG
    dtm = by_id["pielach_2023-02-08_DTM_etrs89"].assets[0]
    assert dtm.path.name.endswith("_cog.tif") and dtm.cloud_native
    assert dtm.media_type == COG_MEDIA_TYPE
    assert len(dtm.sidecars) == 3  # tfw + prj + PAM aux.xml (full-name form)


def test_plain_named_real_cog_probed_cn_no_warning(discovered, by_id):
    _, _, err = discovered
    dsm_filled = by_id["pielach_2023-02-08_DSM_filled_etrs89"].assets[0]
    assert dsm_filled.cloud_native and dsm_filled.media_type == COG_MEDIA_TYPE
    assert "DSM_filled" not in err


def test_both_cn_twins_cog_named_wins_silently(discovered, by_id):
    _, _, err = discovered
    dtm_filled = by_id["pielach_2023-02-08_DTM_filled_etrs89"].assets[0]
    assert dtm_filled.path.name.endswith("_cog.tif") and dtm_filled.cloud_native
    assert "DTM_filled" not in err


def test_lone_non_cn_cataloged_with_warning_strays_warned(discovered, by_id):
    _, _, err = discovered
    dsm = by_id["pielach_2023-02-08_DSM_etrs89"].assets[0]
    assert not dsm.cloud_native and dsm.media_type != COG_MEDIA_TYPE
    assert "pielach_2023-02-08_DSM_etrs89.tif" in err and "ground.laz" in err
    assert "campaign.yaml" not in err and "opalsLog.xml" in err


def test_ext_mix_prefers_laz_cross_dir_prj_never_attaches(discovered, by_id):
    _, _, err = discovered
    ground = by_id["pielach_2023-02-08_ground"].assets[0]
    assert ground.path.name.endswith(".laz"), ground.path.name
    assert "extension mix" in err
    assert not ground.sidecars


def test_shade_ignore_category_no_product_no_warning(discovered):
    _, products, err = discovered
    assert not any("shd" in p.id.lower() for p in products)
    assert "shd" not in err.lower()


def test_dateless_file_gets_campaign_prefix(by_id):
    assert "pielach_2023-02-08_dtm_dateless_etrs89" in by_id


def test_tiles_share_group_rest_flat(discovered):
    _, products, _ = discovered
    tiled = [p for p in products if p.group]
    assert len(tiled) == 2 and {p.group for p in tiled} == {"tiles"}


def test_skip_policy_is_old_cloud_native_only_rule(discovered):
    tmp, _, _ = discovered
    skipped = discover(tmp, policy_unknown="skip", policy_non_cn="skip")
    assert len(skipped) == 7
    assert all(a.cloud_native for p in skipped for a in p.assets)
