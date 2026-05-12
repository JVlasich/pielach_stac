```yaml
# project.yaml — opalsstac configuration
# All paths are relative to this file's location
# unless they start with /


# ── COLLECTION METADATA ───────────────────
# Describes the dataset as a whole.
# These fields populate the STAC Collection object

collection:
  id: "sample-name"            # machine-readable, no spaces
  title: "Sample Name Long"
  description: >
    Sample Description, this can be longer

  # roles producer | licensor | processor | host
  provider:
    name: "Provider Name"
    roles:
		- "producer"
        - "licensor"
    url: "https://provider.name.com"

  # Sensor / acquisition parameters, stored as collection-level properties
  # and inherited by items (can be overridden per-item if needed)
  instrument:
    platform: "aircraft"
    sensor: "..."
    scan_angle_deg: 30
    pulse_repetition_rate_khz: 800

  # Temporal coverage of the whole campaign
  # Items get their own datetime from GPSTime — this is the collection envelope (optional)
  temporal_extent:
    start: "2024-04-10"
    end: "2024-04-18"

  # License
  license: "proprietary" # or "CC-BY-4.0" or a URL

  # Keywords for STAC catalog discovery
  keywords:
    - "lidar"
    - "ALS"
    - "point cloud"
    - "..."


# ── PROCESSING CONFIGURATION ──────────────

processing:
  # Convert GPSTime to UTC (only las version <= 1.1)
  # Options:
  #   "gps_week" — requires gps_week field below; most accurate
  #   "file_mtime" — uses file modification time as fallback; coarse
  #   "config_date" — uses temporal_extent.start above; coarse
  gpstime_strategy: "gps_week"
  gps_week: 2312                  # only needed if strategy is "gps_week"
  
  # What to do with files that don't match any registry pattern
  # skip | warn | register_as_unknown
  unknown_asset_policy: "warn"

  # Whether to generate PNG thumbnail overviews for raster assets
  # marked with thumbnail: true in the registry
  generate_thumbnails: true


# ── PATHS ─────────────────────────────────

paths:
  # Directory containing the files to be indexed
  # Can be a list if data is in multiple locations
  input: "./strips"
  # input:
  #   - "./strips/flight_A"
  #   - "./strips/flight_B"

  # Where the STAC catalog JSON files will be written
  catalog_root: "./stac_catalog"


# ── ASSET REGISTRY OVERRIDES ──────────────
# Only needed if your project uses non-standard output names.
# These are merged with (and take precedence over) the built-in registry
# (which is based on opals naming conventions)

asset_overrides:
  # Example: project names terrain models differently
  - suffix: "_ground"
    extension: ".tif"
    label: "dtm_candidate"        # reuses an existing role definition

  # Example: project has a custom density raster output
  - suffix: "_density"
    extension: ".tif"
    label: "point_density"        # needs a matching entry in role_overrides below

# If you use a custom label above, define its role here
role_overrides:
  point_density:
    stac_roles: ["overview", "metadata"]
    media_type: "image/tiff; application=geotiff"
    title: "Point density raster"
    extensions: ["raster", "projection"]
    thumbnail: true


# ── HIERARCHY (OPTIONAL, MANUAL MODE) ──────
# If present, switches catalog from auto-inferred hierarchy to manually defined.
# If absent, the dynamic auto-hierarchy is built from discovered asset categories.
# Asset discovery + metadata extraction run in BOTH modes.

hierarchy:
  # Top-level node — typically a catalog. Can also be a single collection if flat.
  type: catalog            # catalog | collection
  id: campaign-2024        # required, machine-readable
  title: "Campaign 2024"   # optional, default = Title-Case of id
  description: >           # optional
    ALS acquisition spring 2024.
  children:                # required for catalog nodes

    # ── EXPLICIT-STYLE COLLECTION ──
    # Every item enumerated. Use for hero items with hand-picked IDs.
    # Each href MUST exist on disk — missing href is a hard error.
    - type: collection
      id: hero-strips
      title: "Hero Strips"
      items:
        - id: strip_001
          # Optional overrides — if omitted, auto-extracted via opalsImport/opalsBounds:
          # title: "Strip 001"
          # datetime: "2024-04-12T10:30:00Z"
          assets:
            - href: "strips/strip_001.laz"
              # category: pointcloud   # optional — auto-classified via stem
        - id: strip_002
          assets:
            - href: "strips/strip_002.laz"

    # ── MATCH-STYLE COLLECTION ──
    # Items auto-discovered and assigned via match rules.
    # Use for bulk content where naming conventions are consistent.
    - type: collection
      id: bulk-tiles
      title: "Bulk COPC Tiles"
      match:
        categories: [pointcloud]              # semantic categories from registry
        path_glob: "tiles/*.copc.laz"      # str or list, relative to paths.input
        # stem_regex: "^tile_[a-z][0-9]+$"    # optional regex on filename stem
        not_match:                            # optional — exclude rules
          stem_regex: "^test_"
```

