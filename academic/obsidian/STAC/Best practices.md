# Naming

- Item IDs should exactly match the filename (without `.json`): `pielach-elevation-2024-10-09`
- Collection IDs: `pielach-elevation`, `pielach-pointcloud`, `pielach-orthophoto`
- Root catalog ID: `pielach`

For the COPC tiles, a good tile naming convention encodes the tile's grid position so that the ID is both unique and meaningful: `pielach-pc-2024-10-09-e480500-n5333000` (using the tile's lower-left corner in ETRS89 / UTM easting/northing in meters)

# Relative vs. absolute links
The best practice for a static catalog is to use relative paths for the catalog/collection/item link graph (the `parent`, `root`, `child`, `item`, `collection`, `items` rels), and absolute paths for asset `href`s. This makes the JSON link graph portable (you can rename the bucket/domain and only need to update the `self` links) while keeping assets independently accessible.

# Point-cloud-only dates
The date `2017-11-15` only has a `.laz` file and no derived raster products. still create an elevation Item but with a clear description noting only the source point cloud was processed. Use `description` or custom property like `"dtm_variant": "void-filled"` to distinguisch DTM variants. 

# Sidecar-files
`.tfw` and `.prj` dont need seperate assets

# Misc
pointcloud collection needs a `summaries` entry listing acquisition dates, so catalog browsers can display an intelligible temporal overview without crawling all tile items. Add `"summaries": { "datetime": ["2014-02-21", "2015-03-20", ...] }` to the pointcloud collection.json.