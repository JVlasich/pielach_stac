## Quick-Reference Summary - Pointclouds

| Extension    | Fields Added                                                                                                             | Use When                                                | Used |
| ------------ | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- | ---- |
| `pointcloud` | `pc:count`, `pc:type`, `pc:encoding`, `pc:schemas`, `pc:statistics`, `pc:density`                                        | Always — core point cloud metadata                      | ✓    |
| `projection` | `proj:epsg`, `proj:wkt2`, `proj:projjson`, `proj:bbox`, `proj:geometry`, `proj:centroid`, `proj:shape`, `proj:transform` | Always — CRS and spatial footprint                      | ✓    |
| `file`       | `file:size`, `file:checksum`, `file:header_size`, `file:byte_order`                                                      | When consumers need to validate downloads               | ✓    |
| `timestamps` | `published`, `expires`, `unpublished`                                                                                    | When tiles have lifecycle or are published in batches   | X    |
| `version`    | `version`, `experimental` + version links                                                                                | When tiles are reprocessed and versioned over time      | X    |
| `processing` | `processing:lineage`, `processing:level`, `processing:software`, `processing:facility`                                   | When documenting the processing pipeline matters        | X    |
| `storage`    | `storage:platform`, `storage:region`, `storage:requester_pays`, `storage:tier`                                           | For cloud-hosted catalogs with access cost implications | X    |

---
These four extensions should be declared in `stac_extensions` at the Item level:

# Types of extensions
###  **Projection**
[Github](https://stac-extensions.github.io/projection/v1.1.0/schema.json) — use on all raster and point cloud items. Key fields: `proj:epsg` (e.g. `25833` for ETRS89/UTM 33N), `proj:shape` (pixel dimensions), `proj:bbox` (native CRS bounding box). This is essential for any spatial tool to correctly interpret your data.

### **Point Cloud**
[Github](https://stac-extensions.github.io/pointcloud/v1.0.0/schema.json) — use only on point cloud items. Required: `pc:count`, `pc:type`, `pc:encoding`. Highly recommended: `pc:density`, `pc:schemas`.

### **File**
[Github](https://stac-extensions.github.io/file/v2.1.0/schema.json) — use on all items. Key field: `file:size` (in bytes) on each asset. Optionally `file:checksum` (a multihash value, e.g. SHA-256) for integrity verification. This is inexpensive to add and very useful for data management.

### **EO**
[Github](https://stac-extensions.github.io/eo/v1.1.0/schema.json) — use only on the orthophoto collection items. Key field: `eo:bands` describing the image channels, and `eo:cloud_cover` if you have that metadata.

# Usage

## Pointclouds

### 1. `pointcloud` Extension

> Schema: `https://stac-extensions.github.io/pointcloud/v1.0.0/schema.json`

| Field           | Type             | Required | Description                                                 |
| --------------- | ---------------- | :------: | ----------------------------------------------------------- |
| `pc:count`      | integer          |    ✓     | Total number of points in the asset                         |
| `pc:type`       | string           |    ✓     | Functional type: `lidar`, `eopc`, `radar`, `sonar`, `other` |
| `pc:encoding`   | string           |    ✓     | Data format / compression: `LASzip`, `LAZ`, `EPT`, etc.     |
| `pc:schemas`    | array of objects |    ✓     | Dimension definitions (see sub-table below)                 |
| `pc:statistics` | array of objects |    X     | Per-dimension statistics (see sub-table below)              |
| `pc:density`    | number           |    X     | Average point density in points per m²                      |

#### `pc:schemas` — Dimension Object Fields

| Field  | Type    | Required | Description                                                     |
| ------ | ------- | :------: | --------------------------------------------------------------- |
| `name` | string  |    ✓     | Dimension name, e.g. `X`, `Y`, `Z`, `Intensity`, `ReturnNumber` |
| `size` | integer |    ✓     | Size in bytes                                                   |
| `type` | string  |    ✓     | Data type: `floating`, `unsigned`, `signed`, `unknown`          |
#### `pc:statistics` — Statistics Object Fields

| Field      | Type    | Required | Description                             |
| ---------- | ------- | :------: | --------------------------------------- |
| `name`     | string  |    ✓     | Dimension name this statistic refers to |
| `position` | integer |    X     | Index of the dimension in `pc:schemas`  |
| `average`  | number  |    X     | Mean value                              |
| `count`    | integer |    X     | Number of non-null values               |
| `maximum`  | number  |    X     | Maximum value                           |
| `minimum`  | number  |    X     | Minimum value                           |
| `stddev`   | number  |    X     | Standard deviation                      |
| `variance` | number  |    X     | Variance                                |
### 2. `projection` Extension

> Schema: `https://stac-extensions.github.io/projection/v1.1.0/schema.json`

| Field            | Type              | Required | Description                                              |
| ---------------- | ----------------- | :------: | -------------------------------------------------------- |
| `proj:epsg`      | integer           |    X     | EPSG code of the CRS, e.g. `25832`. `null` if non-EPSG   |
| `proj:wkt2`      | string            |    X     | Full CRS definition as a WKT2 string                     |
| `proj:projjson`  | object            |    X     | CRS definition as a PROJJSON object                      |
| `proj:bbox`      | array of numbers  |    X     | Bounding box in native CRS: `[minx, miny, maxx, maxy]`   |
| `proj:geometry`  | GeoJSON geometry  |    X     | Precise footprint polygon in native CRS                  |
| `proj:centroid`  | object            |    X     | `{ "lat": ..., "lon": ... }` in WGS84                    |
| `proj:shape`     | array of integers |    X     | Pixel/cell dimensions `[height, width]` for gridded data |
| `proj:transform` | array of numbers  |    X     | Affine transform coefficients (6-element or 9-element)   |
### 3. `file` Extension

> Schema: `https://stac-extensions.github.io/file/v2.1.0/schema.json`

| Field              | Type    | Required | Description                                 |
| ------------------ | ------- | :------: | ------------------------------------------- |
| `file:size`        | integer |    X     | File size in bytes                          |
| `file:checksum`    | string  |    X     | Multihash checksum string (e.g. SHA-256)    |
| `file:header_size` | integer |    X     | Byte offset of the data body (header size)  |
| `file:byte_order`  | string  |    X     | Byte order: `big-endian` or `little-endian` |
### 5. `version` Extension

> Schema: `https://stac-extensions.github.io/version/v1.2.0/schema.json`
#### Item Properties

| Field          | Type    | Required | Description                                    |
| -------------- | ------- | :------: | ---------------------------------------------- |
| `version`      | string  |    ✓     | Version identifier for this item, e.g. `"2.1"` |
| `experimental` | boolean |    X     | Marks the item as a draft or unstable version  |

#### Item Links

| `rel` value           | Description                                       |
| --------------------- | ------------------------------------------------- |
| `derived_from`        | Points to source items this item was derived from |
| `predecessor-version` | Links to the previous version of this item        |
| `successor-version`   | Links to the next version of this item            |
| `latest-version`      | Links to the most current version                 |
### 6. `processing` Extension

> Schema: `https://stac-extensions.github.io/processing/v1.2.0/schema.json`

| Field                   | Type   | Required | Description                                                  |
| ----------------------- | ------ | :------: | ------------------------------------------------------------ |
| `processing:expression` | object |    X     | Algorithm or formula applied, with `format` and `expression` |
| `processing:lineage`    | string |    X     | Human-readable description of the processing chain           |
| `processing:level`      | string |    X     | Processing level label, e.g. `L1`, `L2`, `L3`                |
| `processing:facility`   | string |    X     | Name of the processing facility                              |
| `processing:software`   | object |    X     | Map of software name → version, e.g. `{"PDAL": "2.6.0"}`     |

---

### 7. `storage` Extension

> Schema: `https://stac-extensions.github.io/storage/v1.0.0/schema.json`

| Field                    | Type    | Required | Description                                                         |
| ------------------------ | ------- | :------: | ------------------------------------------------------------------- |
| `storage:platform`       | string  |    X     | Cloud platform: `aws`, `gcp`, `azure`, `alibaba`, `huawei`, `other` |
| `storage:region`         | string  |    X     | Cloud region the data is stored in, e.g. `eu-central-1`             |
| `storage:requester_pays` | boolean |    X     | Whether egress costs are charged to the requester                   |
| `storage:tier`           | string  |    X     | Storage class/tier: `online`, `nearline`, `coldline`, `archive`     |

---
