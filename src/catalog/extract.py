# type: ignore
"""Two decorator-registries: Reader and Populator

Readers return asset metadata
Extensions map metadata to Extension fields"""

from dataclasses import dataclass
from typing import Callable, Any

# kind → fn(path, needed_exts) -> AssetMeta (I/O once, gated)
_readers:    dict[str, Callable] = {}
# ext  → fn(target, meta) -> None (no I/O)
_extensions: dict[str, Callable] = {}

@dataclass
class AssetMeta:
    pass

@reader("raster") # GDAL
@reader("pointcloud") # OPALS

@extension("projection")
@extension("raster")
@extension("eo")    
@extension("pointcloud")
@extension("file")

# Baseline (always, not extension-gated): WGS84 `geometry` (polygon) + `bbox`
# plus the fields needed for id/datetime.