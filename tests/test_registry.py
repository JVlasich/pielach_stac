import pytest

from stac.core.registry import LABELS, STEM_PATTERNS, merge_overrides

FULL_LABEL = {"category": "pointcloud", "kind": "pcl", "stac_roles": ["data"],
              "media_type": "application/vnd.laszip+copc",
              "extensions": ["pointcloud", "projection", "file"], "thumbnail": True}


def test_pattern_override_defaults_omitted_keys_leaves_siblings():
    sp, _ = merge_overrides({"pointcloud": {"extensions": [".laz", ".las"]}}, {})
    assert sp["pointcloud"]["extensions"] == [".laz", ".las"]
    assert sp["pointcloud"]["require"] == [] and sp["pointcloud"]["forbid"] == []
    assert sp["dtm"] == STEM_PATTERNS["dtm"] and sp["dsm"] == STEM_PATTERNS["dsm"]


def test_new_label_needs_all_keys():
    _, lb = merge_overrides({}, {"pointcloud": FULL_LABEL})
    assert lb["pointcloud"] == FULL_LABEL

    incomplete = {k: v for k, v in FULL_LABEL.items() if k != "extensions"}
    with pytest.raises(ValueError):
        merge_overrides({}, {"x": incomplete})


def test_empty_pattern_raises():
    with pytest.raises(ValueError):
        merge_overrides({"x": {}}, {})


def test_override_tokens_and_extensions_are_lowercased():
    sp, _ = merge_overrides({"dtm": {"require": ["DTM", "Masked"], "forbid": ["SHD"],
                                     "extensions": [".TIF"]}}, {})
    assert sp["dtm"] == {"require": ["dtm", "masked"], "forbid": ["shd"], "extensions": [".tif"]}


@pytest.mark.parametrize("key", ["require", "forbid", "extensions"])
def test_scalar_pattern_key_wrapped_with_warning(key, caplog):
    sp, _ = merge_overrides({"dtm": {key: "DTM"}}, {})
    assert sp["dtm"][key] == ["dtm"]
    assert "one-element list" in caplog.text


def test_no_overrides_copies_equal_originals():
    sp, lb = merge_overrides(None, None)
    assert sp == STEM_PATTERNS and lb == LABELS
