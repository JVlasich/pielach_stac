"""Extends core.config with the catalog's nested sections.

config.py ignores these sections.
nested catalog config is parsed into dataclasses, independently of config.py.

TODO: hierarchy, registry overrides (asset/role)
"""

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

required_fields = ("title", "description", "sensor", "site", "status", "productPaths")
valid_status = {"processed", "pending"}


@dataclass
class Campaign:
    date: date
    title: str
    description: str
    sensor: object  # str or list[str]
    site: str
    status: str
    product_paths: list  # folders relative to CatalogConfig.root_dir


@dataclass
class CollectionMeta:
    id: str
    title: str
    description: str
    license: object = None
    providers: list = field(default_factory=list)
    keywords: list = field(default_factory=list)


@dataclass
class CatalogConfig:
    root_dir: str
    campaigns: dict  # key (ISO date string) -> Campaign
    collection: CollectionMeta


def _require(d: dict, keys, ctx: str) -> None:
    missing = [k for k in keys if d.get(k) is None]
    if missing:
        raise ValueError(f"{ctx}: missing required field(s): {', '.join(missing)}")


def _parse_campaign(key, raw) -> Campaign:
    if not isinstance(raw, dict):
        raise ValueError(f"campaign {key!r}: entry must be a mapping")
    if isinstance(key, date):  # YAML parses unquoted YYYY-MM-DD into a date
        d = key
    else:
        try:
            d = date.fromisoformat(str(key))
        except ValueError:
            raise ValueError(f"campaign {key!r}: key is not an ISO date (YYYY-MM-DD)")

    ctx = f"campaign {d.isoformat()!r}"
    _require(raw, required_fields, ctx)

    status = raw["status"]
    if status not in valid_status:
        raise ValueError(f"{ctx}: status {status!r} not in {sorted(valid_status)}")

    paths = raw["productPaths"]
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise ValueError(f"{ctx}: productPaths must be a non-empty list")

    return Campaign(
        date=d,
        title=raw["title"],
        description=raw["description"],
        sensor=raw["sensor"],
        site=raw["site"],
        status=status,
        product_paths=[str(p) for p in paths],
    )


def _parse_collection(raw) -> CollectionMeta:
    if not isinstance(raw, dict):
        raise ValueError("config: 'collection' section missing or not a mapping")
    _require(raw, ("id", "title", "description"), "collection")
    return CollectionMeta(
        id=raw["id"],
        title=raw["title"],
        description=raw["description"],
        license=raw.get("license"),
        providers=raw.get("providers") or [],
        keywords=raw.get("keywords") or [],
    )


def load_catalog_config(path) -> CatalogConfig:
    """Parse the main catalog config + its referenced campaigns file into a CatalogConfig.

    Structural validation only (required fields, status enum, ISO-date keys). Does not check that
    product paths exist on disk - that is discover.py's job once the archive is reachable.
    """
    path = Path(path)
    main = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(main, dict):
        raise ValueError(f"{path}: must be a YAML mapping")

    campaigns_file = main.get("campaigns_file")
    if not campaigns_file:
        raise ValueError(f"{path}: missing 'campaigns_file' pointer")
    camp_path = path.parent / campaigns_file
    camp_raw = yaml.safe_load(camp_path.read_text(encoding="utf-8")) or {}
    if not isinstance(camp_raw, dict):
        raise ValueError(f"{camp_path}: must be a YAML mapping")

    root_dir = camp_raw.get("root_dir")
    if not root_dir:
        raise ValueError(f"{camp_path}: missing 'root_dir'")
    raw_campaigns = camp_raw.get("campaigns")
    if not isinstance(raw_campaigns, dict) or not raw_campaigns:
        raise ValueError(f"{camp_path}: 'campaigns' must be a non-empty mapping")

    campaigns = {}
    for key, raw in raw_campaigns.items():
        c = _parse_campaign(key, raw)
        campaigns[c.date.isoformat()] = c  # canonical ISO-string key
    collection = _parse_collection(main.get("collection"))
    return CatalogConfig(
        root_dir=str(root_dir), campaigns=campaigns, collection=collection
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "usage: python -m src.core.config_ext [catalog-config.yaml]",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = load_catalog_config(sys.argv[1])
    print(f"root_dir:   {cfg.root_dir}")
    print(f"collection: {cfg.collection.id} - {cfg.collection.title}")
    print(f"campaigns ({len(cfg.campaigns)}):")
    for key, c in cfg.campaigns.items():
        print(f"  {key}  {c.status:<10} {c.sensor!s:<24} paths={c.product_paths}")
