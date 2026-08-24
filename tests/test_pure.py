"""Pure-logic unit tests: no real data files, no GDAL/OPALS calls at runtime.

Covers the internals the file-driven tests only reach indirectly (matcher, twin
resolution, id derivation, config precedence). discover imports gdal, so it is imported
lazily inside the tests that need it and guarded with importorskip, so a missing geo
stack skips those cases instead of collapsing collection.
Run: env\\Scripts\\python -m pytest tests/ -q
"""

import argparse

import pytest


# --- registry: global isolation (Fix 2 regression) ---

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
