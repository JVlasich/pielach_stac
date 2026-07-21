"""Pure-logic unit tests: no real data files, no GDAL/OPALS calls at runtime.

Heavy modules (discover->gdal, build/tac_pcl->opals) are imported lazily inside the
tests that need them and guarded with importorskip, so a missing geo stack skips
those cases instead of collapsing collection. Run: env\\Scripts\\python -m pytest tests/ -q
"""

import argparse
from datetime import date, datetime, timezone

import pytest


# --- registry: override merge + global isolation (Fix 2 regression) ---

def test_merge_overrides_fills_missing_pattern_keys_on_result():
    from stac.core import registry
    sp, _ = registry.merge_overrides({"newpat": {"extensions": [".xyz"]}}, None)
    assert sp["newpat"] == {"extensions": [".xyz"], "require": [], "forbid": []}


def test_merge_overrides_rejects_incomplete_label():
    from stac.core import registry
    with pytest.raises(ValueError):
        registry.merge_overrides(None, {"bad": {"category": "x"}})  # missing label keys


def test_merge_overrides_does_not_mutate_globals(monkeypatch):
    """Injects a key-incomplete built-in so the shallow-copy aliasing actually bites:
    RED on `dict(STEM_PATTERNS)`, GREEN after the per-entry copy."""
    from stac.core import registry
    monkeypatch.setitem(registry.STEM_PATTERNS, "tmp", {"require": ["x"]})
    registry.merge_overrides(None, None)
    assert "extensions" not in registry.STEM_PATTERNS["tmp"]


# --- discover: matching, twin resolution, id derivation ---

def _discover():
    pytest.importorskip("osgeo.gdal")
    from stac.catalog import discover
    return discover


def test_match_specificity_and_forbid():
    d = _discover()
    assert d.match("a_dtm.tif") == "dtm"
    assert d.match("a_dtm_filled.tif") == "dtm_filled"      # more require tokens wins
    assert d.match("a_dtm_shd.tif") == "shade"              # dtm forbids shd -> routes to shade
    assert d.match("x_transparent_mosaic.tif") == "orthophoto"
    assert d.match("x_mosaic.tif") is None                  # missing 'transparent'
    assert d.match("foo.txt") is None


def test_match_extension_specificity():
    d = _discover()
    from stac.core.registry import STEM_PATTERNS
    assert d.match("cloud.copc.laz") == "pointcloud_copc"   # .copc.laz beats .laz
    assert d.match("cloud.laz") == "pointcloud"
    label, _pat, ext = d._best_match("cloud.copc.laz", STEM_PATTERNS)
    assert (label, ext) == ("pointcloud_copc", ".copc.laz")


def test_resolve_twins_cn_beats_plain():
    d = _discover()
    from pathlib import Path
    plain = d._Match(Path("camp/dtm.tif"), "dtm", "dtm", ".tif", {}, False)
    cog = d._Match(Path("camp/dtm_cog.tif"), "dtm", "dtm", ".tif", {}, True)
    kept = d._resolve_twins([plain, cog], "warn")
    assert [m.path.name for m in kept] == ["dtm_cog.tif"]


def test_resolve_twins_lone_non_cn_policy():
    d = _discover()
    from pathlib import Path
    m = d._Match(Path("c/x.laz"), "pointcloud", "pointcloud", ".laz", {}, False)
    assert d._resolve_twins([m], "skip") == []
    assert d._resolve_twins([m], "warn") == [m]
    with pytest.raises(ValueError):
        d._resolve_twins([m], "raise")


def test_item_id_strips_cog_marker():
    d = _discover()
    assert d._item_id("2023-02-08_dtm_cog.tif", ".tif") == "2023-02-08_dtm"
    assert d._item_id("x_COG.laz", ".laz") == "x"            # case-insensitive strip
    assert d._item_id("dtm.tif", ".tif") == "dtm"


# --- build: GPS time -> UTC extent ---

def _build():
    pytest.importorskip("opals")
    from stac.catalog import build
    return build


def test_resolve_pc_datetime_guards():
    b = _build()
    camp = date(2023, 2, 8)
    assert b.resolve_pc_datetime(None, 5.0, camp) is None
    assert b.resolve_pc_datetime(100.0, 100.0, camp) is None   # degenerate (min==max)
    assert b.resolve_pc_datetime(-1.0, 5.0, camp) is None      # negative


def test_resolve_pc_datetime_weekseconds_lands_on_campaign_day():
    b = _build()
    camp = date(2023, 2, 8)                 # Wednesday; GPS week starts prior Sunday 2023-02-05
    wednesday_secs = 3 * 86400              # Sun=0 -> Wed = 3 days into the GPS week
    start, end = b.resolve_pc_datetime(wednesday_secs, wednesday_secs + 3600, camp)
    assert start == datetime(2023, 2, 8, 0, 0, tzinfo=timezone.utc)
    assert (end - start).total_seconds() == 3600


def test_resolve_pc_datetime_adjusted_standard():
    b = _build()
    camp = date(2023, 2, 8)
    midnight = datetime(2023, 2, 8, tzinfo=timezone.utc)
    standard = (midnight - datetime(1980, 1, 6, tzinfo=timezone.utc)).total_seconds()
    adj = standard - 1e9                    # adjusted standard GPS time
    start, end = b.resolve_pc_datetime(adj, adj + 3600, camp)
    assert start == midnight
    assert (end - start).total_seconds() == 3600


def test_resolve_pc_datetime_week_wrap():
    b = _build()
    camp = date(2023, 2, 8)
    saturday, sunday_next = 6 * 86400, 0    # max < min -> wraps into the next week
    start, end = b.resolve_pc_datetime(saturday, sunday_next, camp)
    assert end > start
    assert (end - start).total_seconds() == 86400


# --- config: defaults < file < cli precedence ---

def test_config_precedence(tmp_path):
    from stac.core import config
    config.register_defaults("t_prec", {"a": 1, "b": 2, "c": 3})
    assert config.section("t_prec") == {"a": 1, "b": 2, "c": 3}

    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("t_prec:\n  b: 20\n  c: 30\n", encoding="utf-8")
    config.load_config(cfg_file)
    assert config.section("t_prec") == {"a": 1, "b": 20, "c": 30}

    ns = argparse.Namespace(c=300, a=None, config=None, init=None, loglevel=None)
    config.merge_cli("t_prec", ns)          # cli wins; None (a) does not override
    assert config.section("t_prec") == {"a": 1, "b": 20, "c": 300}


# --- hierarchy: flat/group placement ---

def _ns(id, group=None):
    from types import SimpleNamespace
    return SimpleNamespace(id=id, group=group)


def test_resolve_hierarchy_auto_groups():
    from stac.catalog.hierarchy import resolve_hierarchy
    nodes = resolve_hierarchy([_ns("a"), _ns("b", group="g")], None)
    assert nodes[0].name is None and [p.id for p in nodes[0].products] == ["a"]
    assert nodes[1].name == "g" and [p.id for p in nodes[1].products] == ["b"]


def test_resolve_hierarchy_placement_overrides():
    from stac.catalog.hierarchy import resolve_hierarchy
    hier = {"placement": {"a": "g", "b": None},                 # pin a into g, force b flat
            "groups": {"g": {"title": "T", "description": "D"}}}
    nodes = resolve_hierarchy([_ns("a"), _ns("b", group="g")], hier)
    flat = nodes[0]
    grp = next(n for n in nodes if n.name == "g")
    assert [p.id for p in flat.products] == ["b"]
    assert [p.id for p in grp.products] == ["a"]
    assert (grp.title, grp.description) == ("T", "D")


# --- tac_pcl: runt-tile merge determinism ---

def _group_tiles():
    pytest.importorskip("opals")
    from stac.pre.tac_pcl import group_tiles
    return group_tiles


def test_group_tiles_no_merge_above_threshold():
    group_tiles = _group_tiles()
    tiles = [("a", 100, (0, 0)), ("b", 100, (1, 0))]
    assert group_tiles(tiles, 50) == [["a"], ["b"]]


def test_group_tiles_runt_merges_into_adjacent():
    group_tiles = _group_tiles()
    tiles = [("a", 100, (0, 0)), ("b", 10, (1, 0))]            # b is a runt, adjacent to a
    assert group_tiles(tiles, 50) == [["a", "b"]]             # largest member first, names it


def test_group_tiles_isolated_runt_kept():
    group_tiles = _group_tiles()
    tiles = [("a", 100, (0, 0)), ("b", 10, (5, 5))]            # runt, no adjacent neighbor
    assert group_tiles(tiles, 50) == [["a"], ["b"]]
