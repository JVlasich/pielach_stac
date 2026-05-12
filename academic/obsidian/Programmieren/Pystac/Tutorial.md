Wichtige takeaways von den Notebooks:
## Imports

```python
import os
import json
import rasterio
import pystac
from datetime import datetime, timezone
from shapely.geometry import Polygon, mapping

# Beispiel extensions außer projection wsl nicht wichtig
from pystac.extensions.eo import Band, EOExtension
from pystac.extensions.view import ViewExtension
from pystac.extensions.projection import ProjectionExtension
```

Mach Katalog mit [[PyStack]]

## JSON Check

```python
json.dumps(catalog.to_dict(), indent=4)
```

# Geometry and BBox function

```python
def get_bbox_and_footprint(raster):
	with rasterio.open(raster) as r:
	bounds = r.bounds
	bbox = [bounds.left, bounds.bottom, bounds.right, bounds.top]
	footprint = Polygon([
		[bounds.left, bounds.bottom],
		[bounds.left, bounds.top],
		[bounds.right, bounds.top],
		[bounds.right, bounds.bottom]
		])
return (bbox, mapping(footprint))
```

## Datetime

```python
datetime_utc = datetime.now(tz=timezone.utc)
```

