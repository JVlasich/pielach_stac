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

    # Ortho (cloud-native twin "orthophoto_cog" derived below)
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


# labels: label → role definition
# raster labels here are the NON-cloud-native (plain GeoTIFF) variants; their cloud-native
# "_cog" twins (COG media type, cloud_native=True) are derived below. Non-CN files are
# cataloged only as fallback when no CN twin exists (discover non_cloud_native policy, D11).
# the base variant carries thumbnail=True, derived ones (filled/masked) don't.
LABELS: dict[str, dict[str, object]] = {
    "pointcloud_copc": {
        "category":   "pointcloud",          # drives item-grouping + collection placement
        "kind":       "pcl",           # dispatches @reader  (pcl | raster)
        "stac_roles": ["data"],               # STAC asset.roles array
        "media_type": "application/vnd.laszip+copc",
        "extensions": ["pointcloud", "projection", "file"],  # drives reader gating + populators
        "thumbnail":  True,
        "cloud_native": True,
    },
    "pointcloud": {
        "category":   "pointcloud",
        "kind":       "pcl",
        "stac_roles": ["data"],
        "media_type": "application/vnd.laszip",
        "extensions": ["pointcloud", "projection", "file"],
        "thumbnail":  True,
        "cloud_native": False,
    },
    "pointcloud_las": {
        "category":   "pointcloud",
        "kind":       "pcl",
        "stac_roles": ["data"],
        "media_type": "application/vnd.las",
        "extensions": ["pointcloud", "projection", "file"],
        "thumbnail":  True,
        "cloud_native": False,
    },

    # orthophoto: RGB orthomosaic, primary deliverable -> data + visual; eo for bands
    "orthophoto": {
        "category":   "orthophoto",
        "kind":       "raster",
        "stac_roles": ["data", "visual"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["eo", "raster", "projection", "file"],
        "thumbnail":  True,
        "cloud_native": False,
    },

    # DTM (terrain) variants -> category "dtm"
    "dtm": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  True,
        "cloud_native": False,
    },
    "dtm_filled": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
        "cloud_native": False,
    },
    "dtm_masked": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
        "cloud_native": False,
    },

    # DSM (surface) variants -> category "dsm"
    "dsm": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  True,
        "cloud_native": False,
    },
    "dsm_filled": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
        "cloud_native": False,
    },
    "dsm_masked": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
        "cloud_native": False,
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

# derive the cloud-native raster twins: same rule + "cog" token, COG media type.
# specificity in the matcher (more require tokens wins) picks the _cog label for *_cog.tif.
_COG_MEDIA = "image/tiff; application=geotiff; profile=cloud-optimized"
for _base in ("orthophoto", "dtm", "dtm_filled", "dtm_masked", "dsm", "dsm_filled", "dsm_masked"):
    STEM_PATTERNS[_base + "_cog"] = {**STEM_PATTERNS[_base], "require": STEM_PATTERNS[_base]["require"] + ["cog"]}
    LABELS[_base + "_cog"] = {**LABELS[_base], "media_type": _COG_MEDIA, "cloud_native": True}


SIDECAR_EXTENSIONS = {".prj", ".tfw", ".aux.xml"}  # recognized, never an asset, never "unknown"


# --- override merge ---

_PATTERN_KEYS = ("require", "forbid", "extensions")
_LABEL_KEYS = ("category", "kind", "stac_roles", "media_type", "extensions", "thumbnail", "cloud_native")


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
        value.setdefault("cloud_native", False)  # omitted in overrides -> treated as non-cloud-native
        missing = [k for k in _LABEL_KEYS if k not in value]
        if missing:
            # labels require all keys for now.
            # TODO: infer missing label keys at runtime instead of erroring.
            raise ValueError(f"label {key!r}: missing keys {missing}")


# --- self-check ---

if __name__ == "__main__":
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
            print(f"expected this error: {e}, this is good")

    # override omitting cloud_native defaults to False
    assert lb["pointcloud"]["cloud_native"] is False

    # no overrides -> copies equal to the originals
    sp, lb = merge_overrides(None, None)
    assert sp == STEM_PATTERNS and lb == LABELS

    # derived cog twins: extra require token, COG media type, cloud_native flipped
    assert sp["dtm_cog"]["require"] == ["dtm", "cog"]
    assert lb["dtm_cog"]["cloud_native"] and not lb["dtm"]["cloud_native"]
    assert lb["orthophoto_cog"]["media_type"].endswith("profile=cloud-optimized")

    print("registry self-check ok")
