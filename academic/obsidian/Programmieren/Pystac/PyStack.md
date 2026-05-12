[Documentation](https://pystac.readthedocs.io/en/stable/api.html)

## Catalog

To overview use:
```python
catalog.describe
```

Create a Catalog and add items
```python
catalog = pystac.Catalog(id='tutorial-catalog', description='This catalog is a basic description')

item = pystac.Item(id='local-image',
		geometry=footprint,
		bbox=bbox,
		datetime=datetime_utc,
		properties={})

catalog.add_item(item)

print(list(catalog.get_children()))
print(list(catalog.get_items()))

# Add collection to catalog
catalog.add_child(collection)
```

## Asset 

```python
item.add_asset(
	key='image',
	asset=pystac.Asset(
		href=img_path,
		media_type=pystac.MediaType.GEOTIFF)
	)

# Asset Href is absolute. Can make relative like:
catalog.make_all_asset_hrefs_relative()
```

## Save

```python
catalog.normalize_hrefs(os.path.join(tmp_dir.name, "stac"))
catalog.save(catalog_type=pystac.CatalogType.[type])
```

## Extensions

They're weird. Beispiel mit eo, nicht wichtig für mich
```python
# enable eo extension for each item and then apply fields
eo = EOExtension.ext(item, add_if_missing=True)
eo.apply(bands=wv3_bands)
# Can also apply to assets instead (in addition?) to items
```

There's also common Metadata (No Extension needed):
```python
item.common_metadata.platform = "Maxar"
item.common_metadata.instruments = ["WorldView3"]
item.common_metadata.gsd = 0.3
```

## Collection

Ich blick noch nicht ganz durch

```python
# Vereinigung für die spatial extents
from shapely.geometry import shape

unioned_footprint = shape(footprint).union(shape(footprint2))
collection_bbox = list(unioned_footprint.bounds)
spatial_extent = pystac.SpatialExtent(bboxes=[collection_bbox])

# Sortierung für temporal extents
collection_interval = sorted([collection_item.datetime, collection_item2.datetime])

temporal_extent = pystac.TemporalExtent(intervals=[collection_interval])
```

Erstellen braucht die extents und eine license
```python
collection_extent = pystac.Extent(spatial=spatial_extent, temporal=temporal_extent)

collection = pystac.Collection(
	id='wv3-images',
	description='Spacenet 5 images over Moscow',
	extent=collection_extent,
	license='CC-BY-SA-4.0'
	)
	
collection.add_items(List[Item])
```