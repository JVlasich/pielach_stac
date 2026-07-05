"""item + collection builders, id/datetime/geometry, extension wiring, thumbnails"""
from typing import Callable
import pystac
from pystac.extensions.pointcloud import PointcloudExtension, Schema, SchemaType, Statistic


# maps the random int to the opals type and in turn to the stac type
_STAC_SCHEMA_TYPE = {
    0: SchemaType.SIGNED,   2: SchemaType.SIGNED,   4: SchemaType.SIGNED,   9: SchemaType.SIGNED,   # int32/8/16/64
    1: SchemaType.UNSIGNED, 3: SchemaType.UNSIGNED, 5: SchemaType.UNSIGNED,                          # uint32/8/16
    6: SchemaType.FLOATING, 7: SchemaType.FLOATING,    # float32 / double
    11: SchemaType.UNSIGNED # bool is technically an uint
}

# ext  → fn(target, meta) -> None (no I/O)
_extensions: dict[str, Callable] = {}  # will be populated by decorators

# @extension("projection") # vertical datum?
# @extension("raster")
# @extension("eo")
# @extension("pointcloud")
# @extension("file")
# @extension("processing")
