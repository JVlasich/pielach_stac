from osgeo_utils.samples.validate_cloud_optimized_geotiff import validate
from glob import glob
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--input", type=str, required=True)
args = parser.parse_args()

paths = glob(os.path.join(args.input, "*.tif"))

for path in paths: 
    warnings, errors, details = validate(path)
    if errors:
        print("Not a valid COG:", errors)
    else:
        print("Valid COG!")