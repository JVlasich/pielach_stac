import os
from osgeo import gdal
from pathlib import Path

gdal.UseExceptions()

src_path = "Pielach_2024-10-09_transparent_mosaic_group1.tif"
out_dir = "./tiles"
tile_size = 16384  # pixels

os.makedirs(out_dir, exist_ok=True)
ds = gdal.Open(src_path)
width = ds.RasterXSize
height = ds.RasterYSize

# mask band of band 1 reflects alpha / nodata / internal mask transparently
mask_band = ds.GetRasterBand(1).GetMaskBand()

written, skipped = 0, 0

for i, xoff in enumerate(range(0, width, tile_size)):
    for j, yoff in enumerate(range(0, height, tile_size)):
        xsize = min(tile_size, width - xoff)
        ysize = min(tile_size, height - yoff)

        mask = mask_band.ReadAsArray(xoff, yoff, xsize, ysize)

        if mask is None or mask.max() == 0:
            skipped += 1
            continue  # entirely nodata / transparent → don't write

        out_path = os.path.join(out_dir, str(Path(src_path).name).strip(".tif") + f"_{xoff}_{yoff}.tif")
        gdal.Translate(
            out_path, ds,
            srcWin=[xoff, yoff, xsize, ysize],
            format="COG",
            creationOptions=[
                "COMPRESS=DEFLATE",
                "BLOCKSIZE=512",
                "OVERVIEWS=AUTO",
                "NUM_THREADS=ALL_CPUS",
                "BIGTIFF=IF_SAFER",
            ],
        )
        written += 1
        print(f"Wrote {out_path}")

ds = None
print(f"\nDone. {written} tiles written, {skipped} empty tiles skipped.")