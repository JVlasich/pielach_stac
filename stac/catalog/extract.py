# type: ignore
"""Two decorator-registries: Reader and Populator

Readers return asset metadata
Extensions map metadata to Extension fields"""

from dataclasses import dataclass
from typing import Callable, Any
from pathlib import Path
import hashlib
import mmap


@dataclass
class AssetMeta:
    pass


@dataclass
class FileMeta:
    size: int
    mtime: float
    sha256: str

def raster():
    pass


def pointcloud():
    pass


def file_meta(p: Path | str) -> FileMeta:
    """Reads File Metadata to compare against existing assets.
    Used in idempotency pipeline to reduce runtime
    by only calling other readers if changes are detected"""
    # checks
    if isinstance(p, str):
        p = Path(p)
    if not (p.exists() and p.is_file()):
        raise ValueError("Path doesnt exist or is not a file")

    # stats
    stat = p.stat()
    mtime, size = stat.st_mtime, stat.st_size

    # hash, mmap faster but fails on 0 size files, why would they exist tho?
    hash_object = hashlib.sha256()
    try:
        with open(p, 'rb') as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                hash_object.update(mm)
        hash = hash_object.hexdigest()
    except ValueError as e:
        print(f"Error while computing hash for file: {p}, assets cannot be empty")
        raise e

    return FileMeta(
        size = size,
        mtime = mtime,
        sha256 = hash
    )



# kind → fn(path, needed_exts) -> AssetMeta (I/O once, gated)
_readers:    dict[str, Callable] = {raster, pointcloud, file_meta}
# ext  → fn(target, meta) -> None (no I/O)
_extensions: dict[str, Callable] = {} # will be populated by decorators

# @extension("projection") # vertical datum?
# @extension("raster")
# @extension("eo")
# @extension("pointcloud")
# @extension("file")
# @extension("processing")

# Baseline (always, not extension-gated): WGS84 `geometry` (polygon) + `bbox`
# plus the fields needed for id/datetime.
