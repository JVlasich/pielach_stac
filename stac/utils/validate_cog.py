from osgeo_utils.samples.validate_cloud_optimized_geotiff import validate
from glob import glob
import argparse
import logging
import os

log = logging.getLogger(__name__)


def validate_cog_tiles(input_dir):
    paths = glob(os.path.join(input_dir, "*.tif"))
    log.debug(f"validating {len(paths)} tif(s) in {input_dir}")

    for path in paths:
        _, errors, _ = validate(path) # warning, errors, details
        if errors:
            log.error(f"Not a valid COG ({os.path.basename(path)}): {errors}")
        else:
            log.info(f"Valid COG: {os.path.basename(path)}")


if __name__ == "__main__":
    from ..core.log import setup

    setup()

    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str, required=True)
    args = parser.parse_args()

    validate_cog_tiles(args.input)
