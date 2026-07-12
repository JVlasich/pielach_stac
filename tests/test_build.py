from datetime import date, datetime, timedelta, timezone

import pytest

from stac.catalog.build import (_GPS_EPOCH, build_collection, build_item,
                                campaign_date, resolve_pc_datetime)
from stac.catalog.discover import discover

CAMP = date(2023, 2, 8)


def test_campaign_date_iso_token():
    assert campaign_date("pielach_2023-02-08_processed") == CAMP
    with pytest.raises(ValueError):
        campaign_date("no_date_here")


def test_pc_datetime_weekseconds():
    # 2023-02-08 is a Wednesday, GPS week starts Sunday 2023-02-05
    start, end = resolve_pc_datetime(100.0, 200.0, CAMP)
    assert start == datetime(2023, 2, 5, 0, 1, 40, tzinfo=timezone.utc), start
    assert (end - start).total_seconds() == 100


def test_pc_datetime_adjusted_standard_round_trip():
    known = datetime(2023, 2, 8, 12, tzinfo=timezone.utc)
    secs = (known - _GPS_EPOCH).total_seconds() - 1_000_000_000
    start, end = resolve_pc_datetime(secs, secs + 3600, CAMP)
    assert start == known, start
    assert end == known + timedelta(hours=1)


def test_pc_datetime_weekseconds_wrap_sat_to_sun():
    start, end = resolve_pc_datetime(604000.0, 100.0, CAMP)
    assert end > start and (end - start).total_seconds() == 900


def test_pc_datetime_degenerate_is_none():
    assert resolve_pc_datetime(None, None, CAMP) is None
    assert resolve_pc_datetime(5.0, 5.0, CAMP) is None
    assert resolve_pc_datetime(-1.0, 50.0, CAMP) is None


def test_build_item_and_collection(tmp_path, write_tif):
    write_tif(tmp_path / "pielach_2023-02-08_dtm_etrs89.tif", 10)
    write_tif(tmp_path / "pielach_2023-02-08_dsm_etrs89.tif", 20)
    products = discover(tmp_path)
    assert len(products) == 2

    items = [build_item(p, CAMP) for p in products]
    for p, item in zip(products, items):
        assert item.id == p.id
        assert item.bbox and item.geometry
        data_asset = item.assets[p.assets[0].label]
        assert data_asset.extra_fields["file:size"] > 0
        assert data_asset.extra_fields["file:checksum"].startswith("1220")
        props = item.properties
        assert props.get("proj:code") or props.get("proj:wkt2"), "no projection populated"
        assert data_asset.extra_fields["raster:bands"], "no raster bands"
        assert item.datetime == datetime.combine(CAMP, datetime.min.time(), tzinfo=timezone.utc)
        assert props["gsd"] == 25
        assert props["created"] and props["updated"]

    coll = build_collection("pielach_test", {"title": "t", "description": "d"}, items)
    assert coll.extent.spatial.bboxes and coll.extent.temporal.intervals
    assert [i.id for i in coll.get_items()] == [i.id for i in items]
    s = coll.to_dict()["summaries"]
    assert s["proj:code"] == ["EPSG:31256"]
    assert s["gsd"] == {"minimum": 25, "maximum": 25}
    assert "created" not in s and "updated" not in s

    with pytest.raises(ValueError):
        build_collection("empty", {}, [])


def test_build_item_provenance(tmp_path, write_tif):
    write_tif(tmp_path / "pielach_2023-02-08_dtm_etrs89.tif", 10)
    p = discover(tmp_path)[0]
    fixed = datetime(2020, 1, 1, tzinfo=timezone.utc)
    item = build_item(p, CAMP, created=fixed, properties={"platform": "riegl-test", "gsd": 99})
    assert item.common_metadata.created == fixed
    assert item.common_metadata.updated > fixed
    assert item.properties["platform"] == "riegl-test"
    assert item.properties["gsd"] == 99, "sidecar properties win over derived"
