"""
Tile and Convert Pointcloud:
Tiles a LAZ file using OPALS and converts tiles to COPC format.

Usage:
    python tile_and_convert.py --infile file.laz [--config config.yaml] [--outdir dir]
    python tile_and_convert.py --init [config.yaml]

Requires: opals
"""

import argparse
import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from ..core.log import setup
from ..utils import io

import opals
from opals import Import, Types, pyDM
from opals.workflows import preTiling, preCutting # concidering _import

log = logging.getLogger(__name__)

_BIN = Path(__file__).resolve().parents[1] / "bin"   # src/pre/<mod> -> src/bin
_COPCINDEX = "lascopcindex64" + (".exe" if os.name == "nt" else "") # linux inclusive :) not tested tho

DEFAULTS = {
    "infile": None,
    "outdir": None,
    "nbThreads": 1,
    "distribute": 1,
    "tileSize_odm": 22.0,
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
        log.debug(f"ODM exists, skipping import: {odm_path.name}")
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
    # shift by half LAS resolution so quantized coords never sit exactly on tile edges (dupes)
    pret.pointOrigin = pointOrigin if pointOrigin else f"{box.xmin - 0.0005};{box.ymin - 0.0005}"
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
        log.info("All tiles already have COPC. Skipping conversion.")
        return

    log.info(f"Converting {len(laz_files)} tile(s) to COPC...")

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
        # Check true sometimes raises because of CRS issues with some files
        # Copcfile still written, lascopcindex exits with 2
        check=True
    )

    lof_path.unlink(missing_ok=True)


def resolve_inputs(raw) -> list:
    """Expand a path or list of paths/dirs into a deduped list of .laz files."""
    entries = [raw] if isinstance(raw, str) else list(raw)
    resolved = []
    seen = set()
    for entry in entries:
        p = Path(entry).resolve()
        if p.is_dir():
            laz = [f for f in sorted(p.glob("*.laz")) if not f.name.endswith(".copc.laz")]
        elif p.exists():
            laz = [p]
        else:
            raise FileNotFoundError(f"Input path not found: {p}")
        for f in laz:
            if f not in seen:
                seen.add(f)
                resolved.append(f)

    if not resolved:
        raise Exception(f"No .laz inputs resolved from --infile {entries}")
    return resolved


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

    tac.add_argument("--infile", type=str, nargs="+", default=None,
                        help="Input LAZ file(s) and/or directories")
    tac.add_argument("--outdir", type=str, default=None,
                        help="Output directory for COPC tiles. Single input: exact dir. "
                             "Multiple inputs: parent root, each input goes to <outdir>/<stem>_tiles. "
                             "(default: <infile_stem>_tiles beside each input)")

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


def process_one(infile: Path | str, cfg: dict, outdir: Path | str, tmp_root: Path | str) -> Path:
    """Run the full tile+convert pipeline for one input. Returns the produced ODM path."""
    infile, outdir, tmp_root = Path(infile), Path(outdir), Path(tmp_root)
    work = tmp_root / infile.stem          # per-input work dir isolates odm, grid and tiles
    tile_tmp = work / "tiles"
    outdir.mkdir(parents=True, exist_ok=True)
    tile_tmp.mkdir(parents=True, exist_ok=True)

    if not infile.is_file():
        raise FileNotFoundError(f"Input file not found: {infile}")

    # OPALS Logger always writes XML logs to CWD — redirect to work dir
    original_cwd = Path.cwd()
    os.chdir(str(work))
    try:
        # Import to ODM
        log.info(f"Importing {infile.name} to ODM...")
        import_laz_file(infile, work, cfg["nbThreads"], cfg["tileSize_odm"])
        odm_path = work / infile.with_suffix(".odm").name
        header = pyDM.Datamanager.getHeaderODM(str(odm_path))

        # Create tile grid
        log.info("Creating tile grid...")
        pretile(header, work, cfg["nbThreads"], cfg["pointOrigin"], cfg["tileSize"])

        # Cut tiles — LAZ goes to tile_tmp, not outdir
        log.info("Cutting tiles...")
        precut(infile, cfg["buffer"], tile_tmp, cfg["nbThreads"], cfg["distribute"], work)
    finally:
        os.chdir(str(original_cwd))

    # COPC conversion — skip files already in outdir
    laz_to_convert = find_laz_needing_conversion(tile_tmp, outdir)
    convert_to_copc(laz_to_convert, tile_tmp, outdir)
    return odm_path


def main():
    setup()
    namespace = "tile_and_convert_pcl"
    from ..core import config
    config.register_defaults(namespace, DEFAULTS)

    parser = build_parser()
    cli_args = parser.parse_args()

    # --init: generate template and exit
    if cli_args.init is not None:
        config.generate_template_config(namespace, Path(cli_args.init))
        sys.exit(0)

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

    inputs = resolve_inputs(cfg["infile"])
    tmp_path = Path(cfg["tmp_path"]).resolve()
    tmp_path.mkdir(parents=True, exist_ok=True)

    explicit_outdir = Path(cfg["outdir"]).resolve() if cfg["outdir"] else None

    def outdir_for(infile: Path) -> Path:
        if explicit_outdir is None:                 # default: beside each input
            return Path(str(infile.with_suffix("")) + "_tiles")
        if len(inputs) == 1:                        # single input: exact dir (back-compat)
            return explicit_outdir
        return explicit_outdir / (infile.stem + "_tiles")  # multi: parent root

    results = []          # (name, "ok" | error message)
    produced_odms = []

    for idx, infile in enumerate(inputs, 1):
        log.info(f"\033[96m=== {infile.name} ({idx}/{len(inputs)}) ===\033[00m")
        try:
            odm_path = process_one(infile, cfg, outdir_for(infile), tmp_path)
            produced_odms.append(odm_path)
            results.append((infile.name, "ok"))
        except Exception as e:
            log.exception(f"FAILED: {infile.name}", stack_info=True)
            results.append((infile.name, str(e)))

    # Cleanup once at batch end
    if cfg.get("keeptmp"):
        log.info("Keeping all temporary files.")
    elif cfg.get("keepodm"):
        log.info("Cleaning temporary files but keeping ODM.")
        for odm in produced_odms:
            io.clean_dir(str(odm.parent), [odm.name])
    else:
        log.info("Cleaning all temporary files.")
        io.clean_dir(str(tmp_path), [])

    if os.name == "nt":  # Windows beep on completion
        import winsound
        winsound.MessageBeep()

    # Summary
    failed = [(n, m) for n, m in results if m != "ok"]
    log.info(f"Done. {len(results) - len(failed)} ok, {len(failed)} failed.")
    for name, msg in failed:
        log.error(f"  {name}: {msg}")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
