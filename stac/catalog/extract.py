# type: ignore
"""Two decorator-registries: Reader and Populator

Readers return asset metadata
Extensions map metadata to Extension fields"""

import hashlib
import mmap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import opals
from opals import Info


@dataclass
class AssetMeta:
    """Dataclass that holds all possible asset metadata.
    extractors will build their extension from these
    
    To be expanded for the other extensions"""
    pc_count:      int                 | None = None
    pc_type:       str                 | None = None
    pc_density:    float               | None = None
    pc_schemas:    list[dict[str:Any]] = field(default_factory=list)
    pc_statistics: list[dict[str:Any]] = field(default_factory=list)
    proj_wkt:      str                 | None = None


@dataclass
class FileMeta:
    size: int
    mtime: float
    sha256: str


def raster():
    pass


def pointcloud(path: str) -> AssetMeta:
    """Extracts relevant pointcloud metadata using opalsInfo.
    Attributes are only extracted if they have more than one possible value.
    returns: AssetMeta object"""
    logLevel = opals.Types.LogLevel.none
    inf = Info.Info()
    inf.inFile = str(path)
    inf.exactComputation = 1
    inf.commons.screenLogLevel = logLevel
    inf.commons.fileLogLevel = logLevel
    inf.run()

    stats = inf.statistic[0]
    attributes = stats.getAttributes()

    statistics = [
        {
            "name":    a.getName(),
            "count":   a.getCount(),
            "minimum": a.getMin(),
            "maximum": a.getMax(),
            "average": a.getMean(),
            "stddev":  a.getStd(),
        } for a in attributes if a.getMin() != a.getMax()
    ]

    schemas = [
        {
            "name":a.getName(),
            "size":a.getStorageSize(),
            "type":a.getType() # DM::ColumnType int mapped in build.py
        } for a in attributes if a.getMin() != a.getMax()
    ]

    return AssetMeta(
        pc_count=stats.getPointCount(),
        pc_density=stats.getPointDensity(),
        pc_type="lidar", # hmmmmmm hardcoding
        pc_schemas=schemas,
        pc_statistics=statistics,
        proj_wkt=stats.getCoordRefSys()
    )


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
        with open(p, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                hash_object.update(mm)
        hash = hash_object.hexdigest()
    except ValueError as e:
        print(f"Error while computing hash for file: {p}, assets cannot be empty")
        raise e

    return FileMeta(size=size, mtime=mtime, sha256=hash)


# kind → fn(path, needed_exts) -> AssetMeta (I/O once, gated)
_readers: dict[str, Callable] = {
    "raster": raster,
    "pointcloud": pointcloud,
    "file_meta":file_meta
}


# Baseline (always, not extension-gated): WGS84 `geometry` (polygon) + `bbox`
# plus the fields needed for id/datetime.
