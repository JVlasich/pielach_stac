"""Default Registry

Override merge ('config.yaml'): 'asset_overrides' (list) extend 'STEM_PATTERNS'
order-irrelevant matches per set.
'role_overrides' (dict) deep-merge per-label onto 'LABELS'.
New labels may be defined entirely in 'role_overrides'.

matcher, override merge, validation"""

# stem_patterns: split.("_") -> set -> match agaisnt required
# {"require": [], "forbid": [], "extensions": "", "label": ""}
STEM_PATTERNS: list[dict[str, object]] = [
    # Pointcloud variants
    {
        "require": [],
        "forbid": [],
        "extensions": [".copc.laz"],
        "label": "pointcloud_copc"
    },
    {
        "require": [],
        "forbid": [],
        "extensions": [".laz"],
        "label": "pointcloud"
    },
    {
        "require": [],
        "forbid": [],
        "extensions": [".las"],
        "label": "pointcloud_las"
    },

    # Ortho
    {
        "require": ["transparent", "mosaic"],
        "forbid": [],
        "extensions": [".tif", ".tiff"],
        "label": "orthophoto"
    },

    # DTM variants
    {
        "require": ["dtm"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
        "label": "dtm"
    },
    {
        "require": ["dtm", "filled"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
        "label": "dtm_filled"
    },
    {
        "require": ["dtm", "masked"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
        "label": "dtm_masked"
    },

    # DSM variants
    {
        "require": ["dsm"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
        "label": "dsm"
    },
    {
        "require": ["dsm", "filled"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
        "label": "dsm_filled"
    },
    {
        "require": ["dsm", "masked"],
        "forbid": ["shd"],
        "extensions": [".tif", ".tiff"],
        "label": "dsm_masked"
    },
]


# labels: label → role definition
LABELS: dict[str, dict[str, object]] = {
    "pointcloud_copc": {
        "category":   "pointcloud",          # drives item-grouping + collection placement
        "kind":       "pcl",           # dispatches @reader  (pcl | raster)
        "stac_roles": ["data"],               # STAC asset.roles array
        "media_type": "application/vnd.laszip+copc",
        "extensions": ["pointcloud", "projection", "file"],  # drives reader gating + populators
        "thumbnail":  True,
    },
    "dtm": {
        "category":   "dtm",
        "kind":       "raster",
        "stac_roles": ["data"],
        "media_type": "image/tiff; application=geotiff",
        "extensions": ["raster", "projection", "file"],
        "thumbnail":  True,
    }

}

SIDECAR_EXTENSIONS = {".prj", ".tfw", ".aux.xml"}  # recognized, never an asset, never "unknown"
