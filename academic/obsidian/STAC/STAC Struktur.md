## Best Candidates
- Catalog
	- pielach-dsm
		- item
	- pielach-dtm
		- item
	- pielach-pointcloud
		- item (tile)
			- Asset (cocp tile, ext: pointcloud, projection pc:type=lidar, pc:count)
	- pielach-orthophoto
		- item (date)
			- Asset (mosaic .tif ext: eo, projection)

- Catalog
	- Collection (All Data)
		- Collection (Datum)
			- Item (Tile 001)
				- Asset (Punktwolke)
				- Asset (DGM)
				- Asset (DOM)
		- Collection (Datum 2)
			- Item (Tile 002)
				- ...
				- ...
Oder:
- Catalog
	- pielach-elevation
		- item (date)
			- Assets (DSM, DTM, DSM_shd, DTM_shd ext: projection, file)
	- pielach-pointcloud
		- item (tile)
			- Asset (cocp tile, ext: pointcloud, projection pc:type=lidar, pc:count)
	- pielach-orthophoto
		- item (date)
			- Asset (mosaic .tif ext: eo, projection)



shading nicht nötig zu katalogisieren
## File Structure

/pielach/
│
├── catalog.json                           ← root Catalog
│
├── pielach-elevation/
│   ├── collection.json
│   └── items/
│       ├── pielach-elevation-2014-02-21.json
│       ├── pielach-elevation-2015-03-20.json
│       ├── pielach-elevation-2016-11-04.json
│       ├── pielach-elevation-2021-03-09.json
│       ├── pielach-elevation-2023-02-08.json
│       └── pielach-elevation-2024-10-09.json
│
├── pielach-pointcloud/
│   ├── collection.json
│   └── items/
│       ├── 2014-02-21/
│       │   ├── pielach-pc-2014-02-21-e480-n5333.json
│       │   ├── pielach-pc-2014-02-21-e480-n5334.json
│       │   └── ...
│       ├── 2015-03-20/
│       │   └── ...
│       └── 2024-10-09/
│           └── ...
│
└── pielach-orthophoto/
    ├── collection.json
    └── items/
        ├── pielach-ortho-2014-02-21.json
        ├── pielach-ortho-2016-11-04.json
        └── pielach-ortho-2024-10-09.json
## How to handle tiles
- Catalog
	- Collection (Datum)
		- Item (Tile_01) \[Property: type=pointcloud] -> Asset (LAZ)
		- Item (Tile_02) \[Property: type=pointcloud] -> Asset (LAZ)
		- Item (DGM_Full) \[Property: type=model] -> Asset (DGM)
		- Item (DOM_Full) \[Property: type=model] -> Asset (DOM)

- Catalog
	- Collection (Vienna LiDAR Point Clouds)
		- Item (2026_Tile_01) -> Asset (LAZ)
		- Item (2026_Tile_02) -> Asset (LAZ)
		- Item (2026_Tile_03) -> Asset (LAZ)
	- Collection (Vienna Elevation Models)
		- Item (2026_DGM_Full) -> Asset (DGM Whole Area)
		- Item (2026_DOM_Full) -> Asset (DOM Whole Area)

## Andere Optionen
- Catalog
	- Collection (All Data)
		- Item (Datum)
			- Asset (Punktwolke)
			- Asset (DGM)
			- Asset (DOM)
		- Item (Datum 2)
			- ...
			- ...

- Catalog
	- Collection (All Data)
		- Collection (Specific time)
			- Item (Punktwolke)
				- Asset
			- Item (DGM)
				- Asset
		- Collection (Specific time 2)
			- ...
				- ...

- Catalog
	- Collection (All Data)
		- Collection (Specific time)
			- Collection (Tile area)
				- Item (Punktwolke)
					- Asset
				- Item (DGM)
					- Asset
		- Collection (Specific time 2)
			- ...
				- ...