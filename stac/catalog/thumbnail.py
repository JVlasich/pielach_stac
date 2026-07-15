"""Render a downscaled PNG thumbnail for a raster item (ortho RGB / DSM-DTM hillshade)."""

import functools
import logging
from pathlib import Path

from osgeo import gdal

gdal.UseExceptions()
log = logging.getLogger(__name__)

MAX_EDGE = 512  # longest thumbnail edge in px


@functools.lru_cache(maxsize=1) # runs function only first time its called
def pcl_thumbnails_available() -> bool:
    """True if laspy + lazrs (vendored in libs\\, win_amd64 cp310) import here."""
    try:
        import laspy  # noqa: F401
        import lazrs  # noqa: F401
        return True
    except Exception:
        return False


def render_thumbnail(item, src_path, kind: str) -> str:
    """Write <item_dir>/<item_id>_thumbnail.png next to the item JSON, return its abs href.

    kind: "rgb" (ortho band downscale) | "hillshade" (DSM/DTM height render)
          | "pointcloud" (COPC/LAZ top-down elevation colormap)"""
    src = str(src_path)
    out = Path(item.get_self_href()).parent / f"{item.id}_thumbnail.png"
    out.parent.mkdir(parents=True, exist_ok=True)  # save() has not created the item dir yet

    if kind == "pointcloud":
        return _render_pcl(src, out)  # GDAL cannot open point clouds, own path below

    ds = gdal.Open(src)
    sw, sh, nbands = ds.RasterXSize, ds.RasterYSize, ds.RasterCount
    ds = None
    if max(sw, sh) <= MAX_EDGE:
        w, h = sw, sh
    else:
        scale = MAX_EDGE / max(sw, sh)
        w, h = max(1, round(sw * scale)), max(1, round(sh * scale))

    if kind == "hillshade":
        small = gdal.Translate("", src, format="MEM", width=w, height=h)
        # zFactor=1 default, bump if gentle river relief looks flat
        hs = gdal.DEMProcessing("", small, "hillshade", format="MEM")
        gdal.Translate(str(out), hs, format="PNG")  # PNG driver is CreateCopy-only
    else:
        # RGB bands 1-3, drops a real alpha (nodata edges show dark, is okay)
        bands = [1, 2, 3] if nbands >= 3 else [1]
        gdal.Translate(str(out), src, format="PNG", width=w, height=h,
                       bandList=bands, resampleAlg="average")

    return out.resolve().as_posix()


COARSE_N = int(4e5)  # decimation target for plain (non-COPC) laz/las


def _coarse_xyz(src: str):
    """(x, y, z) arrays, coarsely sampled. COPC reads shallow octree levels; plain laz/las strides."""
    import laspy
    import numpy as np
    if src.endswith(".copc.laz"):
        with laspy.CopcReader.open(src) as r:
            h = r.header
            span = max(h.maxs[0] - h.mins[0], h.maxs[1] - h.mins[1])
            pts = r.query(resolution=span / MAX_EDGE)  # ~one octree node per thumbnail pixel
        return np.asarray(pts.x), np.asarray(pts.y), np.asarray(pts.z)
    # plain LAZ/LAS has no spatial index (COPC is the fast norm); stride chunks, bounded memory
    with laspy.open(src) as f:
        step = max(1, f.header.point_count // COARSE_N)
        xs, ys, zs = [], [], []
        for pts in f.chunk_iterator(3_000_000):
            xs.append(np.asarray(pts.x)[::step])
            ys.append(np.asarray(pts.y)[::step])
            zs.append(np.asarray(pts.z)[::step])
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)


def _render_pcl(src: str, out: Path) -> str:
    """Top-down elevation colormap, max-Z per cell, longest edge MAX_EDGE, empty cells transparent."""
    import matplotlib.image as mpimg
    import numpy as np
    from scipy import ndimage
    from scipy.stats import binned_statistic_2d

    x, y, z = _coarse_xyz(src)
    ex, ey = np.ptp(x), np.ptp(y)
    if ex >= ey:
        w, h = MAX_EDGE, (max(1, round(MAX_EDGE * ey / ex)) if ex else 1)
    else:
        w, h = (max(1, round(MAX_EDGE * ex / ey)) if ey else 1), MAX_EDGE
    grid, *_ = binned_statistic_2d(x, y, z, statistic="max", bins=[w, h])  # nan = empty cell
    # nearest-fill small holes, keep real voids transparent
    nan = np.isnan(grid)
    dist, (ix, iy) = ndimage.distance_transform_edt(nan, return_indices=True)
    small = nan & (dist <= 2)  # fills gaps up to ~4 px wide; bump if speckle persists
    grid[small] = grid[ix[small], iy[small]]
    vmin, vmax = np.nanpercentile(grid, [10, 90])  # guard implausible high/low returns
    # grid is [x, y]; transpose to rows=y, origin lower keeps north up
    mpimg.imsave(str(out), grid.T, cmap="cividis", vmin=vmin, vmax=vmax, origin="lower")
    return out.resolve().as_posix()


if __name__ == "__main__":
    # self-check: python -m stac.catalog.thumbnail <src> [<dest dir>]
    import sys
    from types import SimpleNamespace
    import time

    src = Path(sys.argv[1]).resolve()
    dst = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path.cwd()
    if src.name.endswith((".las", ".laz")):
        kind = "pointcloud"
    else:
        ds = gdal.Open(str(src))
        kind = "rgb" if ds.RasterCount >= 3 else "hillshade"
        ds = None
    item = SimpleNamespace(id=src.stem.removesuffix(".copc"),
                           get_self_href=lambda: str(dst / "item.json"))
    start = time.time()
    print(render_thumbnail(item, src, kind), f" ({round(time.time()-start,1)}s)")
