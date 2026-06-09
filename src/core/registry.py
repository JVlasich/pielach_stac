"""Default Registry

Override merge ('config.yaml'): 'asset_overrides' (list) extend 'STEM_PATTERNS'
order-irrelevant because the matcher sorts by length.
'role_overrides' (dict) deep-merge per-label onto 'LABELS'.
New labels may be defined entirely in 'role_overrides'.

matcher, override merge, validation"""

# stem_patterns: ordered list, matched longest-(suffix+extension)-first
# sample entry: {"prefix": "", "suffix": "", "extension": ".copc.laz", "label": "pointcloud"}
STEM_PATTERNS: list[dict[str, str]]


# labels: label → role definition
LABELS: dict[str, dict[str, object]]
# SAMPLE LABEL:
# "pointcloud": {
#         "category":   "pointcloud",          # drives item-grouping + collection placement
#         "kind":       "pointcloud",           # dispatches @reader  (pointcloud | raster)
#         "stac_roles": ["data"],               # STAC asset.roles array
#         "media_type": "application/vnd.laszip+copc",
#         "extensions": ["pointcloud", "projection", "file"],  # drives reader gating + populators
#         "thumbnail":  False,
#     },

SIDECAR_EXTENSIONS = {".prj", ".tfw", ".aux.xml"}  # recognized, never an asset, never "unknown"
