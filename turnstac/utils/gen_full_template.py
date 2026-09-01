"""One template config YAML holding every tool namespace.

Usage:
    python -m stac.utils.gen_full_template [out.yaml]

Needs the full env (opals + gdal + pystac): tool modules import at top level.
"""

import sys
from pathlib import Path

import yaml

from ..catalog.manager import CATALOG_DEFAULTS as CAT_DEFAULTS
from ..pre.tac_pcl import DEFAULTS as PCL_DEFAULTS
from ..pre.tac_raster import DEFAULTS as RASTER_DEFAULTS

# namespace strings are locals in each tool's main(), duplicated here on purpose
SECTIONS = {
    "catalog": CAT_DEFAULTS,
    "tile_and_convert_pcl": PCL_DEFAULTS,
    "tac_raster": RASTER_DEFAULTS,
}


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.yaml")

    lines = [
        "# Configuration template. All values shown are defaults.",
        "# Uncomment and modify as needed. CLI args override values set here.",
        "",
    ]
    for ns, defaults in SECTIONS.items():
        lines.append(f"{ns}:")
        body = yaml.safe_dump(defaults, sort_keys=False).splitlines()
        lines += [f"  # {line}" for line in body]
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Template config written to: {path}")


if __name__ == "__main__":
    main()
