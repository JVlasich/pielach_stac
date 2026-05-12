[stat-spec](https://stacspec.org/en/about/stac-spec/)
# Catalog
[Catalog](https://github.com/radiantearth/stac-spec/blob/master/catalog-spec/catalog-spec.md): Groups other catalogs and collections. flexible JSON file of links to organize and browse STAC Items
# Collection
[Collection](https://github.com/radiantearth/stac-spec/blob/master/collection-spec/collection-spec.md): Extension of STAC Catalog (extends to extent, license, keywords, providers, etc) used to describe items that fall within it.
# Item
[Item](https://github.com/radiantearth/stac-spec/blob/master/item-spec/item-spec.md): Atomic unit, representing single spatiotemporal asset as GeoJSON feature plus datetime and links
additional fields: 
- the time the asset represents
- a thumbnail for quick browsing
- asset links, links to the described data
- relationship links, allowing users to traverse other related STAC Items
Can also contain additional fields and JSON structures, siehe [[Ideen#JSON-Structures]]
# API
[API](https://github.com/radiantearth/stac-api-spec): RESTful endpoint that enables search of STAC Items,
That's for later
# Extensions
- Projection (proj) STAC braucht WGS84 (EPSG:4326) -> tatsächliches CRS angeben
- Point Cloud (pointcloud)
- Raster (raster): Bänder und Datentypen
# Dynamic vs Static
A static catalog is one that is implemented as a set of flat files on a web server or an object store like S3 or Google Cloud Storage. A dynamic catalog is one that generates its responses dynamically, generally backed by some sort of server. The core Item, Catalog and Collection specs can be fully implemented by either, and the spec is designed to be agnostic to how it is implemented

Wichtige Notiz: Ein statischer Katalog kann als Grundlage dienen einen dynamischen zu machen. Also zuerst statisch.