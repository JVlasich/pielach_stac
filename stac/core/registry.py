"""Default Registry

Override merge ('config.yaml'): 'asset_overrides' (dict) merge per-label onto 'STEM_PATTERNS'
order-irrelevant matches per set.
'role_overrides' (dict) deep-merge per-label onto 'LABELS'.
New labels may be defined entirely in 'role_overrides'.

override merge, validation"""

# stem_patterns: label -> match rule. split.("_") -> set -> match agaisnt required
# {label: {"require": [], "forbid": [], "extensions": ""}}
STEM_PATTERNS: dict[str, dict[str, object]] = {
    # Pointcloud variants
    "pointcloud_copc": {
        "require": [],
        "forbid": [],
        "extensions": [".copc.laz"],
    },
    "pointcloud": {
        "require": [],
        "forbid": [],
        "extensions": [".laz"],
    },
    "pointcloud_las": {
        "require": [],
        "forbid": [],
        "extensions": [".las"],
    },

    # Ortho
    "orthophoto": {
        "require": ["transparent", "mosaic"],
        "forbid": [],
        "extensions": [".tif", ".tiff"],
    },

    # DTM variants
    "dtm": {
        "require": ["dtm"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
    },
    "dtm_filled": {
        "require": ["dtm", "filled"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
    },
    "dtm_masked": {
        "require": ["dtm", "masked"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
    },

    # DSM variants
    "dsm": {
        "require": ["dsm"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
    },
    "dsm_filled": {
        "require": ["dsm", "filled"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
    },
    "dsm_masked": {
        "require": ["dsm", "masked"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
    },

    # shd for filtering
    "shade": {
        "require": ["shd"],
        "forbid": [],
        "extensions": [".tif", ".tiff"],
    },
}


# labels: label -> role definition
LABELS: dict[str, dict[str, object]] = {
    "pointcloud_copc": {
        "category":   "pointcloud",          # drives item-grouping + collection placement
        "kind":       "pcl",           # dispatches @reader  (pcl | raster)
        "stac_roles": ["data"],               # STAC asset.roles array
        "media_type": "application/vnd.laszip+copc",
        "extensions": ["pointcloud", "projection", "file"],  # drives reader gating + populators
        "thumbnail":  True,
    },
    "pointcloud": {
        "category":   "pointcloud",
        "kind":       "pcl",
        "stac_roles": ["data"],
        "media_type": "application/vnd.laszip",
        "extensions": ["pointcloud", "projection", "file"],
        "thumbnail":  True,
    },
    "pointcloud_las": {
        "category":   "pointcloud",
        "kind":       "pcl",
        "stac_roles": ["data"],
        "media_type": "application/vnd.las",
        "extensions": ["pointcloud", "projection", "file"],
        "thumbnail":  True,
    },

    # orthophoto: RGB orthomosaic, primary deliverable -> data + visual; eo for bands
    "orthophoto": {
        "category":   "orthophoto",
        "kind":       "raster",
        "stac_roles": ["data", "visual"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["eo", "raster", "projection", "file"],
        "thumbnail":  True,
    },

    # DTM (terrain) variants -> category "dtm"
    "dtm": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  True,
    },
    "dtm_filled": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
    },
    "dtm_masked": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
    },

    # DSM (surface) variants -> category "dsm"
    "dsm": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  True,
    },
    "dsm_filled": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
    },
    "dsm_masked": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
    },

    # shades ignored?
    # "shade":  { # unsure about this
    #     "category":   "ignore",
    #     "kind":       "raster",
    #     "stac_roles": ["visual"],
    #     "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
    #     "extensions": ["raster", "projection", "file"],
    #     "thumbnail":  False,
    # },
}

SIDECAR_EXTENSIONS = {".prj", ".tfw", ".aux.xml"}  # recognized, never an asset, never "unknown"


# --- override merge ---

_PATTERN_KEYS = ("require", "forbid", "extensions")
_LABEL_KEYS = ("category", "kind", "stac_roles", "media_type", "extensions", "thumbnail")


def merge_overrides(patterns, labels):
    """Per-campaign overrides onto the defaults.
    Returns merged (stem_patterns, labels) copies
    the module globals are not mutated."""
    sp = dict(STEM_PATTERNS); sp.update(patterns or {})
    lb = dict(LABELS);        lb.update(labels or {})
    _validate(sp, lb)
    return sp, lb


def _validate(stem_patterns, labels) -> None:
    for key, value in stem_patterns.items():
        if not isinstance(value, dict) or not value:
            raise ValueError(f"pattern {key!r}: set at least one key")
        for k in _PATTERN_KEYS:
            value.setdefault(k, [])  # omitted require/forbid/extensions -> []
    for key, value in labels.items():
        missing = [k for k in _LABEL_KEYS if k not in value]
        if missing:
            # labels require all keys for now.
            # TODO: infer missing label keys at runtime instead of erroring.
            raise ValueError(f"label {key!r}: missing keys {missing}")


# --- self-check ---

if __name__ == "__main__":
    import logging

    from .log import setup

    setup()
    log = logging.getLogger(__name__)

    # pattern override replaces the entry, defaults the omitted keys, leaves siblings alone
    sp, lb = merge_overrides({"pointcloud": {"extensions": [".laz", ".las"]}}, {})
    assert sp["pointcloud"]["extensions"] == [".laz", ".las"]
    assert sp["pointcloud"]["require"] == [] and sp["pointcloud"]["forbid"] == []
    assert sp["dtm"] == STEM_PATTERNS["dtm"] and sp["dsm"] == STEM_PATTERNS["dsm"]

    # new label needs all keys; missing key or empty pattern raises
    full = {"category": "pointcloud", "kind": "pcl", "stac_roles": ["data"],
            "media_type": "application/vnd.laszip+copc",
            "extensions": ["pointcloud", "projection", "file"], "thumbnail": True}
    _, lb = merge_overrides({}, {"pointcloud": full})
    assert lb["pointcloud"] == full
    incomplete = {k: v for k, v in full.items() if k != "extensions"}

    for i in range(2):
        try:
            dummy = merge_overrides({}, {"x": incomplete}) if i == 0 else merge_overrides({"x": {}}, {})
        except ValueError as e:
            log.info(f"expected this error: {e}, this is good")

    # no overrides -> copies equal to the originals
    sp, lb = merge_overrides(None, None)
    assert sp == STEM_PATTERNS and lb == LABELS

    log.info("registry self-check ok")
