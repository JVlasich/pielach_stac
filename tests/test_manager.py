import json
import shutil
from pathlib import Path

import pystac

from stac.catalog.manager import update_catalog


def _raw_href(out: Path, item_id: str, role: str) -> str:
    """The on-disk (un-resolved) href of an item's first asset with the given role."""
    item_json = next(out.rglob(f"{item_id}.json"))
    d = json.loads(item_json.read_text(encoding="utf-8"))
    a = next(a for a in d["assets"].values() if role in (a.get("roles") or []))
    return a["href"]


def test_failed_item_isolated(tmp_path, write_tif, write_tif_no_crs):
    out = tmp_path / "catalog"
    camp = tmp_path / "2020-01-01"
    camp.mkdir()
    write_tif(camp / "pielach_2020-01-01_dtm_etrs89.tif", 10)
    write_tif_no_crs(camp / "pielach_2020-01-01_dsm_etrs89.tif")
    (camp / "campaign.yaml").write_text("", encoding="utf-8")

    # no-CRS item fails alone, campaign still builds
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2020-01-01"] == {"rebuilt": 1, "reused": 0, "stale": 0, "failed": 1}, res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    assert {i.id for i in cat.get_items(recursive=True)} == {"pielach_2020-01-01_dtm_etrs89"}

    # sidecar crs fallback rescues it
    (camp / "campaign.yaml").write_text('crs: "EPSG:31256"\n', encoding="utf-8")
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2020-01-01"] == {"rebuilt": 1, "reused": 1, "stale": 0, "failed": 0}, res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    item = next(i for i in cat.get_items(recursive=True) if i.id.endswith("dsm_etrs89"))
    assert item.properties["proj:code"] == "EPSG:31256"

    # every item failing: campaign untouched, no collection created
    camp2 = tmp_path / "2021-02-02"
    camp2.mkdir()
    write_tif_no_crs(camp2 / "pielach_2021-02-02_dtm_etrs89.tif")
    (camp2 / "campaign.yaml").write_text("", encoding="utf-8")
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2021-02-02"] == {"rebuilt": 0, "reused": 0, "stale": 0, "failed": 1}, res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    assert cat.get_child("pielach_2021-02-02") is None


def test_subcollection_id_not_doubled_and_asset_href_modes(tmp_path, write_tif):
    out = tmp_path / "catalog"
    camp = tmp_path / "2024-10-09"
    tiles = camp / "pielach_2024-10-09_tiles"
    tiles.mkdir(parents=True)
    write_tif(camp / "pielach_2024-10-09_dsm_etrs89.tif", 10)
    write_tif(tiles / "pielach_2024-10-09_dtm_526000_534000.tif", 20)
    write_tif(tiles / "pielach_2024-10-09_dtm_527000_534000.tif", 30)
    (camp / "campaign.yaml").write_text("", encoding="utf-8")

    # default: subcollection id takes the subdir name as-is, no camp_id doubling
    update_catalog(tmp_path, out)
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    coll = cat.get_child("pielach_2024-10-09")
    assert coll.get_child("pielach_2024-10-09_tiles") is not None
    assert coll.get_child("pielach_2024-10-09_pielach_2024-10-09_tiles") is None
    # absolute (default) data href keeps the build-time path; thumbnail stays relative
    assert Path(_raw_href(out, "pielach_2024-10-09_dsm_etrs89", "data")).is_absolute()
    assert (_raw_href(out, "pielach_2024-10-09_dsm_etrs89", "thumbnail")
            == "./pielach_2024-10-09_dsm_etrs89_thumbnail.png")

    # relative mode: data href climbs out of catalog/, thumbnail unchanged
    update_catalog(tmp_path, out, force=True, asset_hrefs="relative")
    assert _raw_href(out, "pielach_2024-10-09_dsm_etrs89", "data").startswith("..")
    assert (_raw_href(out, "pielach_2024-10-09_dsm_etrs89", "thumbnail")
            == "./pielach_2024-10-09_dsm_etrs89_thumbnail.png")


def test_tiny_pcl_tiles_dropped(tmp_path, monkeypatch):
    # pcl reads need opals/laspy; mock discover/build_item/pcl_point_count to exercise the filter
    from datetime import datetime, timezone

    import stac.catalog.manager as mgr
    from stac.catalog.discover import Asset, Product

    camp = tmp_path / "2024-10-09"
    (camp / "tiles").mkdir(parents=True)
    (camp / "campaign.yaml").write_text(
        "collection:\n"
        "  providers:\n"
        "    - name: TU Wien\n"
        "      roles: [processor]\n"
        "  keywords: [LiDAR, Pielach]\n", encoding="utf-8")

    def _prod(pid):
        a = Asset(path=camp / "tiles" / f"{pid}.copc.laz", label="pointcloud_copc",
                  category="pointcloud", kind="pcl", stac_roles=["data"],
                  media_type="application/vnd.laszip+copc", extensions=[], cloud_native=True)
        return Product(id=pid, category="pointcloud", kind="pcl", assets=[a], group="tiles")

    monkeypatch.setattr(mgr, "discover",
                        lambda folder, **kw: [_prod("pielach_2024-10-09_big"),
                                              _prod("pielach_2024-10-09_tiny")])
    # header point count drives the drop, read before build (tile files aren't real here)
    monkeypatch.setattr(mgr, "pcl_point_count",
                        lambda path: 5_000_000 if "big" in str(path) else 3)

    def _fake_item(product, campaign, **kw):
        return pystac.Item(id=product.id, geometry={"type": "Point", "coordinates": [15.4, 48.2]},
                           bbox=[15.4, 48.2, 15.4, 48.2],
                           datetime=datetime(2024, 10, 9, tzinfo=timezone.utc), properties={})

    monkeypatch.setattr(mgr, "build_item", _fake_item)

    root = pystac.Catalog(id="pielach", description="d")
    mgr.process_campaign(camp, root, min_points=1000)
    camp_coll = root.get_child("pielach_2024-10-09")
    ids = {i.id for i in camp_coll.get_items(recursive=True)}
    assert ids == {"pielach_2024-10-09_big"}, ids  # 3-point tile dropped, real tile kept

    # P2-1: the tiles subcollection inherits the campaign's providers/keywords
    sub = camp_coll.get_child("tiles")
    assert sub.providers and sub.providers[0].name == "TU Wien"
    assert "LiDAR" in (sub.keywords or [])


def test_root_promoted_to_collection(tmp_path, write_tif, monkeypatch):
    from stac.core import config
    orig = config.section
    base = orig("catalog")
    monkeypatch.setattr(config, "section", lambda ns: (
        {**base, "license": "CC-BY-4.0", "providers": [{"name": "TU Wien"}]}
        if ns == "catalog" else orig(ns)))
    out = tmp_path / "catalog"
    camp = tmp_path / "2024-10-09"
    camp.mkdir()
    write_tif(camp / "pielach_2024-10-09_dsm_etrs89.tif", 10)
    (camp / "campaign.yaml").write_text("", encoding="utf-8")

    update_catalog(tmp_path, out)
    root = pystac.read_file(str(out / "catalog.json"))
    assert isinstance(root, pystac.Collection)
    assert root.license == "CC-BY-4.0" and root.providers
    assert root.extent.spatial.bboxes[0] and root.extent.temporal.intervals[0]


def test_update_catalog_staged_idempotency(tmp_path, write_tif):
    """One sequential story: build -> reuse -> content change -> stale ->
    dry-run -> force -> subcollection stale -> duplicate id -> vanished campaign."""
    out = tmp_path / "catalog"
    camp_dir = tmp_path / "2023-02-08_test"
    (camp_dir / "pielach_2023-02-08_tiles").mkdir(parents=True)
    write_tif(camp_dir / "pielach_2023-02-08_dtm_etrs89.tif", 10)
    write_tif(camp_dir / "pielach_2023-02-08_dsm_etrs89.tif", 20)
    write_tif(camp_dir / "pielach_2023-02-08_tiles" / "pielach_2023-02-08_dtm_1_1.tif", 30)
    write_tif(camp_dir / "pielach_2023-02-08_tiles" / "pielach_2023-02-08_dtm_1_2.tif", 40)
    write_tif(camp_dir / "pielach_2023-02-08_tiles" / "pielach_2023-02-08_dtm_1_3.tif", 45)
    (camp_dir / "campaign.yaml").write_text(
        "collection:\n"
        "  title: Test campaign\n"
        "  description: fixture campaign\n"
        "  license: CC-BY-4.0\n"
        "properties:\n"
        "  platform: riegl-test\n"
        "hierarchy:\n"
        "  groups:\n"
        "    pielach_2023-02-08_tiles:\n"
        "      title: DTM tiles\n",
        encoding="utf-8",
    )
    (tmp_path / "2023-05-05_broken").mkdir()          # campaign without campaign.yaml
    (tmp_path / "notes").mkdir()                      # not a campaign, ignored

    # run 1: full build, broken campaign isolated
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2023-02-08_test"] == {"rebuilt": 5, "reused": 0, "stale": 0, "failed": 0}, res
    assert "2023-05-05_broken" in res["failed"]

    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    camp = cat.get_child("pielach_2023-02-08")
    assert camp is not None and camp.title == "Test campaign"
    sub = camp.get_child("pielach_2023-02-08_tiles")
    assert sub is not None and sub.title == "DTM tiles"
    assert len(list(sub.get_items())) == 3
    assert len(list(camp.get_items(recursive=True))) == 5

    # sidecar properties passthrough + provenance timestamps + curated summaries
    item = next(i for i in camp.get_items() if i.id == "pielach_2023-02-08_dtm_etrs89")
    assert item.properties["platform"] == "riegl-test"
    created0, updated0 = item.properties["created"], item.properties["updated"]
    s = camp.to_dict()["summaries"]
    assert s["proj:code"] == ["EPSG:31256"] and s["platform"] == ["riegl-test"]
    assert s["gsd"] == {"minimum": 25, "maximum": 25}

    # run report persisted
    report = json.loads((Path.cwd() / "last_run.json").read_text(encoding="utf-8"))
    assert report["ok"]["2023-02-08_test"]["rebuilt"] == 5 and report["failed"]

    # run 2: no-op, everything reused, timestamps untouched
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2023-02-08_test"] == {"rebuilt": 0, "reused": 5, "stale": 0, "failed": 0}, res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    item = next(i for i in cat.get_items(recursive=True) if i.id == "pielach_2023-02-08_dtm_etrs89")
    assert (item.properties["created"], item.properties["updated"]) == (created0, updated0)

    # only-filter: broken campaign skipped, stale-collection sweep off
    res = update_catalog(tmp_path, out, only="2023-02-08*")
    assert res["ok"]["2023-02-08_test"]["reused"] == 5
    assert not res["failed"] and res["stale_collections"] == []

    # content change at constant size -> hash path rebuilds exactly that item
    write_tif(camp_dir / "pielach_2023-02-08_dtm_etrs89.tif", 99)
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2023-02-08_test"] == {"rebuilt": 1, "reused": 4, "stale": 0, "failed": 0}, res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    item = next(i for i in cat.get_items(recursive=True) if i.id == "pielach_2023-02-08_dtm_etrs89")
    assert item.properties["created"] == created0, "created survives rebuilds"
    assert item.properties["updated"] > updated0, "updated bumps on rebuild"

    # deleted file: default warn keeps the item, remove drops it
    (camp_dir / "pielach_2023-02-08_dsm_etrs89.tif").unlink()
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2023-02-08_test"] == {"rebuilt": 0, "reused": 4, "stale": 1, "failed": 0}, res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    assert len(list(cat.get_items(recursive=True))) == 5

    res = update_catalog(tmp_path, out, policy_stale="remove")
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    assert len(list(cat.get_items(recursive=True))) == 4

    # dry run: reports, writes nothing but the run report
    write_tif(camp_dir / "pielach_2023-02-08_dtm_etrs89.tif", 50)
    before = (out / "catalog.json").stat().st_mtime
    res = update_catalog(tmp_path, out, dry_run=True)
    assert res["ok"]["2023-02-08_test"]["rebuilt"] == 1
    assert (out / "catalog.json").stat().st_mtime == before
    report = json.loads((Path.cwd() / "last_run.json").read_text(encoding="utf-8"))
    assert report["dry_run"] is True

    # force skips the gate, everything rebuilds
    res = update_catalog(tmp_path, out, force=True)
    assert res["ok"]["2023-02-08_test"] == {"rebuilt": 4, "reused": 0, "stale": 0, "failed": 0}, res

    # kept-stale tile stays inside its subcollection (no flat drift)
    (camp_dir / "pielach_2023-02-08_tiles" / "pielach_2023-02-08_dtm_1_3.tif").unlink()
    res = update_catalog(tmp_path, out)
    assert res["ok"]["2023-02-08_test"] == {"rebuilt": 0, "reused": 3, "stale": 1, "failed": 0}, res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    camp = cat.get_child("pielach_2023-02-08")
    assert {i.id for i in camp.get_items()} == {"pielach_2023-02-08_dtm_etrs89"}
    sub = camp.get_child("pielach_2023-02-08_tiles")
    assert len(list(sub.get_items())) == 3  # 2 live + 1 stale clone kept in place

    # duplicate campaign id fails isolated, first campaign untouched
    dup = tmp_path / "2023-06-06_dup"
    dup.mkdir()
    (dup / "campaign.yaml").write_text("collection:\n  id: pielach_2023-02-08\n",
                                       encoding="utf-8")
    res = update_catalog(tmp_path, out)
    assert "already used" in res["failed"]["2023-06-06_dup"], res
    assert "2023-02-08_test" in res["ok"]
    shutil.rmtree(dup)

    # vanished campaign dir: removal blocked while another campaign fails...
    shutil.rmtree(camp_dir)
    res = update_catalog(tmp_path, out, policy_stale="remove")
    assert res["stale_collections"] == ["pielach_2023-02-08"] and res["failed"], res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    assert cat.get_child("pielach_2023-02-08") is not None

    # ...then removed once the run is clean
    shutil.rmtree(tmp_path / "2023-05-05_broken")
    res = update_catalog(tmp_path, out, policy_stale="remove")
    assert not res["failed"] and res["stale_collections"] == ["pielach_2023-02-08"], res
    cat = pystac.Catalog.from_file(str(out / "catalog.json"))
    assert cat.get_child("pielach_2023-02-08") is None
