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


# labels: label → role definition
# (labels "pointcloud", "pointcloud_las") are deliberately absent
# the base variant carries thumbnail=True, derived ones (filled/masked) don't.
LABELS: dict[str, dict[str, object]] = {
    "pointcloud_copc": {
        "category":   "pointcloud",          # drives item-grouping + collection placement
        "kind":       "pcl",           # dispatches @reader  (pcl | raster)
        "stac_roles": ["data"],               # STAC asset.roles array
        "media_type": "application/vnd.laszip+copc",
        "extensions": ["pointcloud", "projection", "file"],  # drives reader gating + populators
        "thumbnail":  True,
    },

    # orthophoto: RGB orthomosaic COG, primary deliverable -> data + visual; eo for bands
    "orthophoto": {
        "category":   "orthophoto",
        "kind":       "raster",
        "stac_roles": ["data", "visual"],
        "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "extensions": ["eo", "raster", "projection", "file"],
        "thumbnail":  True,
    },

    # DTM (terrain) variants -> category "dtm"
    "dtm": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  True,
    },
    "dtm_filled": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
    },
    "dtm_masked": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
    },

    # DSM (surface) variants -> category "dsm"
    "dsm": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  True,
    },
    "dsm_filled": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  False,
    },
    "dsm_masked": {
        "category":   "dsm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
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
