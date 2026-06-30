from osgeo_utils.samples.validate_cloud_optimized_geotiff import validate
from glob import glob
import argparse
import os


def validate_cog_tiles(input_dir):
    paths = glob(os.path.join(input_dir, "*.tif"))

    for path in paths:
        _, errors, _ = validate(path) # warning, errors, details
        if errors:
            print("Not a valid COG:", errors)
        else:
            print("Valid COG!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str, required=True)
    args = parser.parse_args()

    validate_cog_tiles(args.input)
