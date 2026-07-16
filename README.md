# Pielach STAC

Automated, idempotent pipeline that turns the processed topo-bathymetric LiDAR
time series of the Pielach river into a standards-compliant static
[STAC 1.1](https://stacspec.org) catalog. Bachelor thesis project, TU Wien,
Department of Geodesy and Geoinformation.

## Deployment layout

The repo folder is meant to live inside the processed-datasets root
(`12_PROCESSED_DATASETS`). Each campaign is one ISO-dated folder next to it,
holding the products plus a per-campaign `campaign.yaml` sidecar
(template: `sample_configs/sample_campaign.yaml`):

```
12_PROCESSED_DATASETS/
├── 2023-02-08/              # campaign: <date>-named folder
│   ├── campaign.yaml        # per-campaign metadata + overrides
│   ├── *_dtm_*.tif ...      # products (COG / COPC preferred)
│   └── <name>_tiles/        # tiled products -> subcollection
├── 2024-10-09/
├── catalog/                 # generated STAC catalog (output)
└── <this repo>/
```

## Prerequisites

- Windows with an [OPALS](https://opals.geo.tuwien.ac.at/) installation
  (default path `C:\opals_nightly_2.6.0`, override with the `OPALS_ROOT`
  environment variable). GDAL, numpy, scipy and matplotlib ride in OPALS'
  bundled Python.
- Pure-Python dependencies (pystac, pyyaml, laspy, lazrs) are vendored in
  `libs\`, no pip install needed.
- Running outside `opalsShell`: set `PROJ_LIB=<opals>\addons\crs` and
  `GDAL_DATA=<opals>\addons\gdal`, otherwise CRS information drops silently.
  The `.bat` launchers handle this.

## Quick start

- **`update_catalog.bat`** — double-click to build/refresh the catalog into
  `<data root>\catalog`. Re-running is safe and cheap: an item is rebuilt only
  when its file changed (size shortcut, then sha256).
- **`view_catalog.bat`** — serves data root + bundled STAC Browser and opens
  `http://localhost:8111/browser/`.

## CLI

```
python -m stac <root> [--config config.yaml] [options]
python -m stac --init <path>     # write a commented config template
```

Key options (CLI > YAML config > defaults):

| Option | Effect |
| --- | --- |
| `--force` | skip the idempotency gate, rebuild everything (use after registry/code changes) |
| `--dryRun` | discover + gate only, write nothing |
| `--only <glob>` | process only matching campaign dirs |
| `--stale warn\|remove\|raise` | items/collections whose files vanished from disk |
| `--unknownAssets warn\|skip\|raise` | files matching no registry pattern |
| `--nonCloudNative warn\|skip\|raise` | files without a cloud-native twin |
| `--idCollisions warn\|raise` | duplicate ids across campaigns |
| `--assetHrefs relative\|absolute` | asset href style (thumbnails always relative) |
| `--thumbnails / --no-thumbnails` | PNG thumbnails for raster + COPC items |
| `--validate` | STAC-validate after saving (needs `pystac[validation]`) |

Each run writes a machine-readable report to `<out>/last_run.json`.

## Pre-processing tools

| Tool | Purpose |
| --- | --- |
| `python -m stac.pre.tac_pcl` | tile a LAZ with OPALS and convert tiles to COPC |
| `python -m stac.pre.tac_raster` | convert GeoTIFF to COG, tiling above a size threshold |
| `python -m stac.pre.c_copc` | convert LAZ to COPC without tiling |

All share the `--config` / `--init` pattern; `python -m stac.utils.gen_full_template`
writes one template covering every namespace (see `sample_configs/sample_config.yaml`).

## Tests

```
env\Scripts\python -m pytest tests
```
requires `pytest`
