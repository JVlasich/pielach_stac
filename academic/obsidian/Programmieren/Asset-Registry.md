# Prinzip 
Default-Mapping nach OPALS-Konventionen/default werten. Sucht nacht stems mit suffix und file extensions -> assigned ein label -> label definiert in einem role dict welche daten extrahiert werden und wo das item/asset eingeordnet wird.

Projektspezifische Konventionen werden via `asset_overrides` und `role_overrides` in `project.yml` gemerged

```yaml
stem_patterns:
  - { suffix: "",         extension: ".laz",      label: "pointcloud" }
  - { suffix: "",         extension: ".copc.laz", label: "pointcloud_copc" }
  - { suffix: "_dtm",     extension: ".tif",      label: "dtm" }
    
roles:
  dtm:
    category: "elevation_dtm"
    stac_roles: ["data"]
    media_type: "image/tiff; application=geotiff"
    extensions: ["raster", "projection", "file"]
    thumbnail: true
  pointcloud:
    category: "pointcloud"
    stac_roles: ["data"]
    media_type: "application/vnd.laszip"
    extensions: ["pointcloud", "projection", "file"]
    thumbnail: false
```

# Parsing:
FUNCTIONS CAN BE INSIDE DICTIONARIES