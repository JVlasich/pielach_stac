"""
Tile and Convert Pointcloud:
Tiles a LAZ file using OPALS and converts tiles to COPC format.

Usage:
    python tile_and_convert.py --infile file.laz [--config config.yaml] [--outdir dir]
    python tile_and_convert.py --init [config.yaml]

Requires: pyyaml, opals
"""

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from ..utils import io

import opals
from opals import Import, Types, pyDM
from opals.workflows import preTiling, preCutting # concidering _import

_BIN = Path(__file__).resolve().parents[1] / "bin"   # src/pre/<mod> -> src/bin
_COPCINDEX = "lascopcindex64" + (".exe" if os.name == "nt" else "") # linux inclusive :) not tested tho

DEFAULTS = {
    "infile": None,
    "outdir": None,
    "nbThreads": 1,
    "distribute": 1,
    "tileSize_odm": 24.0,
    "tmp_path": "./tmp",
    "pointOrigin": None,#"529000;5340000",
    "tileSize": 500,
    "keepodm": True,
    "buffer": 0,
    "keeptmp": None,
}


def import_laz_file(infile: Path, tmp_path: Path, nbThreads: int, tileSize_odm: float):
    odm_path = tmp_path / infile.with_suffix(".odm").name
    if odm_path.exists():
        return None

    imp = Import.Import()
    imp.inFile = str(infile)
    imp.commons.nbThreads = nbThreads
    imp.outFile = str(odm_path)
    imp.tileSize = tileSize_odm
    imp.run()
    return imp


def pretile(header, tmp_path: Path, nbThreads: int, pointOrigin: str | None, tileSize: int):
    pret = preTiling.preTiling()
    box = header.getLimit()
    pret.bbox = [box.xmin, box.ymin, box.xmax, box.ymax]
    pret.skipIfExists = True
    pret.tileSize = tileSize
    # infer pointorigin from bbox if not provided
    pret.pointOrigin = pointOrigin if pointOrigin else f"{box.xmin};{box.ymin}"
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


def convert_to_copc(laz_files: list, tile_tmp: Path, odir: Path):
    if not laz_files:
        print("All tiles already have COPC. Skipping conversion.")
        return

    print(f"Converting {len(laz_files)} tile(s) to COPC...")

    lof_path = tile_tmp / "_convert_list.txt"
    lof_path.write_text(
        "\n".join(str(f) for f in laz_files),
        encoding="utf-8"
    )

    subprocess.run([
        str(_BIN / _COPCINDEX),
        "-lof", str(lof_path),
        "-odir", str(odir),
        "-progress",
    ],
        check=True
    )

    lof_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tile a LAZ file and convert tiles to COPC format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Config precedence: CLI args > YAML config > built-in defaults.
            Use --init to generate a template config file.
        """)
    )

    commons_cli = parser.add_argument_group("Common options")

    commons_cli.add_argument("--nbThreads", type=int, default=None,
                        help=f"Number of threads (default: {DEFAULTS['nbThreads']})")
    commons_cli.add_argument("--distribute", type=int, default=None,
                        help=f"Distribution factor (default: {DEFAULTS['distribute']})")
    commons_cli.add_argument("--tmp_path", type=str, default=None,
                        help=f"Temporary directory path (default: {DEFAULTS['tmp_path']})")
    commons_cli.add_argument("--keeptmp", action=argparse.BooleanOptionalAction, default=None,
                        help=f"Keep temporary files (default: False)")

    tac = parser.add_argument_group("Tile and Convert options")


    tac.add_argument("--config", type=str, default=None,
                        help="Path to YAML configuration file")
    tac.add_argument("--init", type=str, nargs="?", const="config.yaml", default=None, # "?" means 0 or 1 args
                        metavar="FILENAME",
                        help="Generate template config YAML and exit (default: config.yaml)")

    tac.add_argument("--infile", type=str, default=None,
                        help="Input LAZ file path")
    tac.add_argument("--outdir", type=str, default=None,
                        help="Output directory for COPC tiles (default: <infile_stem>_tiles)")
    
    tac.add_argument("--pointOrigin", type=str, default=None,
                        help=f"Tile origin coordinates (default: {DEFAULTS['pointOrigin']})")
    tac.add_argument("--tileSize", type=float, default=None,
                        help=f"Tile size in map units (default: {DEFAULTS['tileSize']})")
    tac.add_argument("--buffer", type=float, default=None,
                        help=f"Buffer around tiles in map units (default: {DEFAULTS['buffer']})")
    tac.add_argument("--tileSize_odm", type=float, default=None,
                        help=f"Tile size for opalsImport (default: {DEFAULTS['tileSize_odm']})")
    tac.add_argument("--keepodm", action=argparse.BooleanOptionalAction, default=None, # note to self: NO store_true
                        help=f"Keep intermediate ODM files (default: {DEFAULTS['keepodm']})")
    

    return parser


def main():
    namespace = "tile_and_convert_pcl"
    from ..core import config
    config.register_defaults(namespace, DEFAULTS)

    parser = build_parser()
    cli_args = parser.parse_args()

    # --init: generate template and exit
    if cli_args.init is not None:
        config.generate_template_config(namespace, Path(cli_args.init))
        sys.exit(0)

##################### New config handling #################################
# import config.py as config
# config.register_defaults("namespace", DEFAULTS)
#
# if cli_args.init is not None:
#     config.generate_template_config("namespace", Path(cli_args.init))
#     sys.exit(0)
#
# if cli_args.config is not None:
#     config.load_config(cli_args.config) -> None
#
# config.merge_cli("namespace", cli_args: argparse.Namespace)
# cfg = config.section("namespace") 

    # Load config file
    if cli_args.config is not None:
        config_path = Path(cli_args.config)
        if not config_path.is_file():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        config.load_config(config_path)

    # Merge: CLI > config > defaults
    config.merge_cli(namespace, cli_args)
    cfg = config.section(namespace)
    com = config.section("commons")
    cfg.update(com)  # make commons keys accessible via cfg for convenience

    if cfg["infile"] is None:
        raise Exception("--infile is required (via CLI or config file)")

    infile = Path(cfg["infile"]).resolve()
    tmp_path = Path(cfg["tmp_path"]).resolve()
    # copcindex_path = Path(cfg["copcindex_path"]).resolve()

    if cfg["outdir"] is None:
        outdir = Path(str(infile.with_suffix("")) + "_tiles")
    else:
        outdir = Path(cfg["outdir"]).resolve()

    tile_tmp = tmp_path / "tiles"

    outdir.mkdir(parents=True, exist_ok=True)
    tmp_path.mkdir(parents=True, exist_ok=True)
    tile_tmp.mkdir(parents=True, exist_ok=True)

    if not infile.is_file():
        raise FileNotFoundError(f"Input file not found: {infile}")

    # OPALS Logger always writes XML logs to CWD — redirect to tmp
    original_cwd = Path.cwd()
    os.chdir(str(tmp_path))

    try:
        # Import to ODM
        print(f"Importing {infile.name} to ODM...")
        import_laz_file(infile, tmp_path, cfg["nbThreads"], cfg["tileSize_odm"])
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

    # COPC conversion — skip files already in outdir
    laz_to_convert = find_laz_needing_conversion(tile_tmp, outdir)
    convert_to_copc(laz_to_convert, tile_tmp, outdir)

    # Cleanup
    if cfg.get("keeptmp") or cfg.get("keepodm"):
        if cfg.get("keeptmp"):  # implies keepodm
            print("Keeping all temporary files.")
        elif cfg.get("keepodm"):
            print("Cleaning temporary files but keeping ODM.")
            io.clean_dir(str(tmp_path), [odm_path.name])
    else:
        print("Cleaning all temporary files.")
        io.clean_dir(str(tmp_path), [])

    if os.name == "nt":  # Windows beep on completion
        import winsound
        winsound.MessageBeep()
    print("Done.")

if __name__ == "__main__":
    main()
