"""Default registry.

Per-campaign overrides ('campaign.yaml'): a 'patterns' entry replaces a whole
STEM_PATTERNS entry (omitted require/forbid/extensions default to []). A 'labels'
entry replaces a whole LABELS entry and must carry every key (see _validate TODO).
New patterns/labels can be defined entirely in overrides.

Also here: override merge, validation."""

import logging
from typing import Any

log = logging.getLogger(__name__)

# stem_patterns: label -> match rule. stem split("_") -> set -> matched against require/forbid
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
    "log": {
        "require": [],
        "forbid": [],
        "extensions": [".log"],
    },

}


# labels: label -> role definition
LABELS: dict[str, dict[str, Any]] = {
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
        "thumbnail":  False,
    },
    "pointcloud_las": {
        "category":   "pointcloud",
        "kind":       "pcl",
        "stac_roles": ["data"],
        "media_type": "application/vnd.las",
        "extensions": ["pointcloud", "projection", "file"],
        "thumbnail":  False,
    },

    # orthophoto: RGB orthomosaic, primary deliverable -> data + visual; eo comes off color interp
    "orthophoto": {
        "category":   "orthophoto",
        "kind":       "raster",
        "stac_roles": ["data", "visual"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["bands", "projection", "file"],
        "thumbnail":  True,
    },

    # DTM (terrain) variants -> category "dtm"
    "dtm": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["bands", "projection", "file"],
        "thumbnail":  True,
    },
    "dtm_filled": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["bands", "projection", "file"],
        "thumbnail":  True,
    },
    "dtm_masked": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["bands", "projection", "file"],
        "thumbnail":  True,
    },

    # DSM (surface) variants -> category "dsm"
    "dsm": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["bands", "projection", "file"],
        "thumbnail":  True,
    },
    "dsm_filled": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["bands", "projection", "file"],
        "thumbnail":  True,
    },
    "dsm_masked": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["bands", "projection", "file"],
        "thumbnail":  True,
    },

    # category "ignore" = discover matches then drops silently (derived viz, not a product)
    "shade": {
        "category":   "ignore",
        "kind":       "raster",
        "stac_roles": [],
        "media_type": "image/tiff; application=geotiff",
        "extensions": [],
        "thumbnail":  False,
    },
    "log": {
        "category":   "ignore",
        "kind":       "",
        "stac_roles": [],
        "media_type": "",
        "extensions": [],
        "thumbnail":  False,
    },
}

SIDECAR_EXTENSIONS = {".prj", ".tfw", ".aux.xml"}  # recognized, never an asset, never "unknown"


# --- override merge ---

_PATTERN_KEYS = ("require", "forbid", "extensions")
_LABEL_KEYS = ("category", "kind", "stac_roles", "media_type", "extensions", "thumbnail")


def merge_overrides(patterns, labels):
    """Per-campaign overrides onto the defaults. Returns merged (stem_patterns,
    labels) copies; module globals stay unmutated."""
    sp = {k: dict(v) for k, v in STEM_PATTERNS.items()}
    sp.update(patterns or {})

    lb = {k: dict(v) for k, v in LABELS.items()}
    lb.update(labels or {})

    _validate(sp, lb)
    return sp, lb


def _validate(stem_patterns, labels) -> None:
    for key, value in stem_patterns.items():
        if not isinstance(value, dict) or not value:
            raise ValueError(f"pattern {key!r}: set at least one key")
        for k in _PATTERN_KEYS:
            if isinstance(value.get(k), str):  # a bare scalar would iterate character-wise
                log.warning(f"pattern {key!r}: {k} is the string {value[k]!r}, read as a one-element list")
                value[k] = [value[k]]
            value[k] = [str(t).lower() for t in value.get(k, [])]  # omitted -> []; matching is lowercased
    for key, value in labels.items():
        missing = [k for k in _LABEL_KEYS if k not in value]
        if missing:
            # labels require all keys for now.
            # TODO: infer missing label keys at runtime instead of erroring.
            raise ValueError(f"label {key!r}: missing keys {missing}")
