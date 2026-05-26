"""
Tile and Convert Pointcloud:
Tiles a LAZ file using OPALS and converts tiles to COPC format.

Usage:
    python tile_and_convert.py --infile file.laz [--config config.yaml] [--outdir dir]
    python tile_and_convert.py --init [config.yaml]

Requires: pyyaml
"""

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
import winsound
from pathlib import Path

import yaml

import opals
from opals import Import, Types, pyDM
from opals.workflows import preTiling, preCutting

DEFAULTS = {
    "infile": None,
    "outdir": None,
    "nbThreads": 1,
    "distribute": 1,
    "tmp_path": "./tmp",
    "copcindex_path": "./bin/lascopcindex64.exe",
    "pointOrigin": "529000;5340000",
    "tileSize": 500,
    "keepodm": False,
    "buffer": 0,
}


def import_laz_file(infile: Path, tmp_path: Path, nbThreads: int):
    odm_path = tmp_path / infile.with_suffix(".odm").name
    if odm_path.exists():
        return None

    imp = Import.Import()
    imp.inFile = str(infile)
    imp.commons.nbThreads = nbThreads
    imp.outFile = str(odm_path)
    imp.run()
    return imp


def pretile(header, tmp_path: Path, nbThreads: int, pointOrigin: str, tileSize: int):
    pret = preTiling.preTiling()
    box = header.getLimit()
    pret.bbox = [box.xmin, box.ymin, box.xmax, box.ymax]
    pret.skipIfExists = True
    pret.tileSize = tileSize
    pret.pointOrigin = pointOrigin
    pret.nbThreads = nbThreads
    pret.fileLogLevel = Types.LogLevel.error
    pret.screenLogLevel = Types.LogLevel.error
    pret.export = str(tmp_path)
    pret.run() # type: ignore
    return pret


def precut(infile: Path, buffer: int, export_dir: Path, nbThreads: int,
           distribute: int, tmp_path: Path):
    prec = preCutting.preCutting()
    prec.shapefile = str(tmp_path / "Tiles.shp")
    prec.vector = str(tmp_path / infile.with_suffix(".odm").name)
    prec.buffer = buffer
    prec.export = str(export_dir / infile.name)
    prec.skipIfExists = True
    prec.oformat = "<l v='4' p='6'/>"
    prec.nbThreads = nbThreads
    prec.distribute = distribute
    prec.fileLogLevel = Types.LogLevel.error
    prec.screenLogLevel = Types.LogLevel.error
    prec.run() # type: ignore
    return prec


def load_config(config_path: Path) -> dict:
    """Loads the yaml config and warns about keys in the config that are not mapped"""
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError(f"Error: config file {config_path} must contain a YAML mapping, not {type(data).__name__}")
    valid_keys = set(DEFAULTS.keys())
    for key in data:
        if key not in valid_keys:
            print(f"Warning: unknown config key '{key}' in {config_path}", file=sys.stderr)
    return data


def generate_template_config(output_path: Path):
    template = textwrap.dedent("""\
        # tile_and_convert.py configuration
        # All values shown are defaults. Uncomment and modify as needed.
        # CLI arguments override values set here.

        # infile:                               # Required: input LAZ file
        # outdir:                               # Output directory (default: <infile_stem>_tiles)
        # nbThreads: 1                          # Number of processing threads
        # distribute: 1                         # OPALS distribution factor
        # tmp_path: ./tmp                       # Temporary working directory
        # copcindex_path: ./lascopcindex64.exe  # Path to lascopcindex executable
        # pointOrigin: "x;y"                    # Tile grid origin coordinates
        # tileSize: 500                         # Tile size in map units
        # keepodm: true                         # Keep intermediate ODM files
        # buffer: 0                             # Buffer around tiles (map units)
    """)
    output_path.write_text(template, encoding="utf-8")
    print(f"Template config written to: {output_path}")


def merge_config(cli_args: argparse.Namespace, config: dict) -> dict:
    merged = dict(DEFAULTS)

    for key, value in config.items():
        if key in merged:
            merged[key] = value

    for key, value in vars(cli_args).items():
        if key in ("config", "init"):
            continue
        if value is not None:
            merged[key] = value

    return merged


def find_laz_needing_conversion(tile_tmp: Path, outdir: Path) -> list:
    existing_copc = {p.name for p in outdir.glob("*.copc.laz")}
    need_conversion = []

    for laz in tile_tmp.glob("*.laz"):
        if laz.name.endswith(".copc.laz"):
            continue
        expected_copc_name = laz.stem + ".copc.laz"
        if expected_copc_name not in existing_copc:
            need_conversion.append(laz)

    return need_conversion


def convert_to_copc(laz_files: list, copcindex_path: Path, tile_tmp: Path):
    if not laz_files:
        print("All tiles already have COPC. Skipping conversion.")
        return

    print(f"Converting {len(laz_files)} tile(s) to COPC...")

    lof_path = tile_tmp / "_convert_list.txt"
    lof_path.write_text(
        "\n".join(str(f) for f in laz_files),
        encoding="utf-8"
    )

    subprocess.run(
        [str(copcindex_path), "-lof", str(lof_path), "-progress"],
        check=True
    )

    lof_path.unlink(missing_ok=True)


def move_copc_to_outdir(tile_tmp: Path, outdir: Path):
    copc_files = list(tile_tmp.glob("*.copc.laz"))
    if not copc_files:
        print("Warning: no .copc.laz files found in tmp after conversion.", file=sys.stderr)
        return

    for src in copc_files:
        dst = outdir / src.name
        shutil.move(str(src), str(dst))

    print(f"Moved {len(copc_files)} COPC file(s) to {outdir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tile a LAZ file and convert tiles to COPC format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Config precedence: CLI args > YAML config > built-in defaults.
            Use --init to generate a template config file.
        """)
    )

    parser.add_argument("--config", type=str, default=None,
                        help="Path to YAML configuration file")
    parser.add_argument("--init", type=str, nargs="?", const="config.yaml", default=None, # "?" means 0 or 1 args
                        metavar="FILENAME",
                        help="Generate template config YAML and exit (default: config.yaml)")

    parser.add_argument("--infile", type=str, default=None,
                        help="Input LAZ file path")
    parser.add_argument("--outdir", type=str, default=None,
                        help="Output directory for COPC tiles (default: <infile_stem>_tiles)")
    parser.add_argument("--nbThreads", type=int, default=None,
                        help=f"Number of threads (default: {DEFAULTS['nbThreads']})")
    parser.add_argument("--distribute", type=int, default=None,
                        help=f"Distribution factor (default: {DEFAULTS['distribute']})")
    parser.add_argument("--tmp_path", type=str, default=None,
                        help=f"Temporary directory path (default: {DEFAULTS['tmp_path']})")
    parser.add_argument("--copcindex_path", type=str, default=None,
                        help=f"Path to lascopcindex executable (default: {DEFAULTS['copcindex_path']})")
    parser.add_argument("--pointOrigin", type=str, default=None,
                        help=f"Tile origin coordinates (default: {DEFAULTS['pointOrigin']})")
    parser.add_argument("--tileSize", type=int, default=None,
                        help=f"Tile size in map units (default: {DEFAULTS['tileSize']})")
    parser.add_argument("--keepodm", action='store_true',
                        help=f"Keep intermediate ODM files (default: {DEFAULTS['keepodm']})")
    parser.add_argument("--buffer", type=int, default=None,
                        help=f"Buffer around tiles in map units (default: {DEFAULTS['buffer']})")

    return parser


if __name__ == "__main__":
    parser = build_parser()
    cli_args = parser.parse_args()

    # --init: generate template and exit
    if cli_args.init is not None:
        generate_template_config(Path(cli_args.init))
        sys.exit(0)

    # Load config file
    config = {}
    if cli_args.config is not None:
        config_path = Path(cli_args.config)
        if not config_path.is_file():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        config = load_config(config_path)

    # Merge: CLI > config > defaults
    cfg = merge_config(cli_args, config)

    if cfg["infile"] is None:
        raise Exception("--infile is required (via CLI or config file)")

    infile = Path(cfg["infile"])
    tmp_path = Path(cfg["tmp_path"])
    copcindex_path = Path(cfg["copcindex_path"])

    if cfg["outdir"] is None:
        outdir = Path(infile.stem + "_tiles")
    else:
        outdir = Path(cfg["outdir"])

    tile_tmp = tmp_path / "tiles"

    outdir.mkdir(parents=True, exist_ok=True)
    tmp_path.mkdir(parents=True, exist_ok=True)
    tile_tmp.mkdir(parents=True, exist_ok=True)

    if not infile.is_file():
        raise FileNotFoundError(f"Input file not found: {infile}")
    if not copcindex_path.is_file():
        raise FileNotFoundError(f"Error: lascopcindex not found: {copcindex_path}")

    # OPALS Logger always writes XML logs to CWD — redirect to tmp
    original_cwd = Path.cwd()
    os.chdir(str(tmp_path))

    try:
        # Import to ODM
        print(f"Importing {infile.name} to ODM...")
        import_laz_file(infile, tmp_path, cfg["nbThreads"])
        odm_path = tmp_path / infile.with_suffix(".odm").name
        header = pyDM.Datamanager.getHeaderODM(str(odm_path))

        # Create tile grid
        print("Creating tile grid...")
        pretile(header, tmp_path, cfg["nbThreads"], cfg["pointOrigin"], cfg["tileSize"])

        # Cut tiles — LAZ goes to tile_tmp, not outdir
        print("Cutting tiles...")
        precut(infile, cfg["buffer"], tile_tmp, cfg["nbThreads"], cfg["distribute"], tmp_path)
    finally:
        os.chdir(str(original_cwd))

    if not cfg["keepodm"]:
        odm_path.unlink(missing_ok=True)

    # COPC conversion — skip files already in outdir
    laz_to_convert = find_laz_needing_conversion(tile_tmp, outdir)
    convert_to_copc(laz_to_convert, copcindex_path, tile_tmp)

    # Move .copc.laz to outdir
    move_copc_to_outdir(tile_tmp, outdir)

    winsound.MessageBeep()
    print("Done.")
