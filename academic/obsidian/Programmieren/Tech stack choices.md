# Pre-Processing
## Tiling:
- opals
- pdal (no, slow, mucho memory)
- lastools (no, paid)
# Conversion:
- COPC:
	- lascopcindex (fixed version)
	- untwine (qgis)
- COG:
	- ?
	- GDAL?
# STAC creation
- pystac
- datetime (std)
- pyproj
- shapely
# Metadata extraction
## Simple:
- Pointcouds
	- pymeepcl (copclib)
	- laspy (for headers, since copclib sucks)
- Raster
	- ?
	- rasterio
## In-depth
- Pointclouds
	- opals (pyDM)
		- Info (pc:stats)
		- ?
- Raster
	- ?