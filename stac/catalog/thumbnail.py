"""Render a downscaled PNG thumbnail for a raster item (ortho RGB / DSM-DTM hillshade)."""

import logging
from pathlib import Path

from osgeo import gdal

gdal.UseExceptions()
log = logging.getLogger(__name__)

MAX_EDGE = 512  # longest thumbnail edge in px


def render_thumbnail(item, src_path, kind: str) -> str:
    """Write <item_dir>/<item_id>_thumbnail.png next to the item JSON, return its abs href.

    kind: "rgb" (ortho band downscale) | "hillshade" (DSM/DTM height render)"""
    src = str(src_path)
    out = Path(item.get_self_href()).parent / f"{item.id}_thumbnail.png"
    out.parent.mkdir(parents=True, exist_ok=True)  # save() has not created the item dir yet

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
