"""Pipeline orchestration: sidecar load, idempotency gate, campaign loop, catalog write."""

import fnmatch
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pystac
import yaml

from ..core import config
from ..core.registry import merge_overrides
from .build import build_collection, build_item, campaign_date
from .discover import discover
from .extract import file_meta
from .hierarchy import resolve_hierarchy

log = logging.getLogger(__name__)

CATALOG_DEFAULTS = {
    "id": "pielach",
    "title": "Pielach River Topo-Bathymetric LiDAR Time Series",
    "description": "Automated STAC catalog of the processed Pielach campaign datasets.",
    # resolved in cli.py
    "root": None,
    "out": None,             # default: <root>/catalog
    "stale": "warn",         # warn | remove | raise (items and collections)
    "dryRun": False,
    "force": False,          # skip checks, rebuild every item
    "validate": False,       # STAC-validate after save (needs pystac[validation])
    "unknownAssets": "warn", # warn | skip | raise for unclassifiable files
    "nonCloudNative": "warn",# warn | skip | raise for files without a CN twin
    "only": None,            # glob over campaign dir names; skips the stale-collection sweep
    "nbThreads": None,       # opals thread count, None = opals default (all CPUs)
    "exactComputation": True,# exact point statistics (full scan) vs header-only (fast, no stats)
}
config.register_defaults("catalog", CATALOG_DEFAULTS)


def load_sidecar(path) -> dict:
    """Read a per-campaign sidecar YAML into a dict
    (collection / patterns / labels / hierarchy / properties blocks / crs fallback)."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


# --- idempotency gate ---

def _stored_file_fields(item, label: str):
    """Returns: (file:size, sha256-hex) stored on the item's data asset, or None."""
    a = item.assets.get(label)
    if a is None:
        return None
    size = a.extra_fields.get("file:size")
    mh = a.extra_fields.get("file:checksum") or ""
    if size is None or not mh.startswith("1220"):
        return None
    return size, mh[4:]


def _needs_rebuild(product, existing_item) -> bool:
    """Size shortcut, then sha256 confirm. A computed hash rides on the asset so
    build_item never hashes twice.
    Note: gates the first asset only, products are single-asset today."""
    a = product.assets[0]
    stored = _stored_file_fields(existing_item, a.label)
    if stored is None:
        return True
    if a.path.stat().st_size != stored[0]:
        return True
    fm = file_meta(a.path)
    a.file_meta = fm
    return fm.sha256 != stored[1]


# --- per-campaign pipeline ---

def process_campaign(
    folder, root, *, # positional
    dry_run: bool = False,
    force:   bool = False,
    policy_unknown: str = "warn",
    policy_non_cn:  str = "warn",
    policy_stale:   str = "warn",
    seen_camp_ids: set | None = None,
    seen_item_ids: set | None = None
) -> dict:

    """Build or refresh one campaign collection on the root catalog.

    Item build failures (unreadable CRS, reader errors) drop only that item;
    the rest of the campaign still builds. A previously cataloged version of a
    failed item follows the stale policy.

    Arguments:
        - folder ; path to the campaign folder
        - dry_run ; early returns, no writes except last_run.json. Readers not called except file_meta
        - force ; skip idempotency, build all items
        - policy_unknown ; in ("warn","skip","raise") decides how to handle unknown assets
        - policy_non_cn ; in ("warn","skip","raise") decides how to handle non cloud-native assets
        - policy_stale ; in ("warn","raise", "remove") decides how to handle existing items that were removed from disk
        - seen_camp_ids ; passed in update_catalog() and mutated inplace
        - seen_item_ids ; passed in update_catalog() and mutated inplace
    Returns:
        {"rebuilt": n, "reused": n, "stale": n, "failed": n}
    Exceptions:
        - missing campaign.yaml
        - camp/item id collisions with earlier campaigns of the same run
    """
    folder = Path(folder)
    sc = load_sidecar(folder / "campaign.yaml")
    sp, lb = merge_overrides(sc.get("patterns"), sc.get("labels"))

    camp = campaign_date(folder.name)
    camp_id = (sc.get("collection") or {}).get("id") or f"pielach_{camp.isoformat()}"
    if seen_camp_ids is not None:
        if camp_id in seen_camp_ids:
            raise ValueError(f"campaign id {camp_id!r} already used by another folder this run")
        seen_camp_ids.add(camp_id)

    products = discover(folder, policy_unknown=policy_unknown, stem_patterns=sp, labels=lb,
                        policy_non_cn=policy_non_cn, id_prefix=camp_id)

    if not products:
        log.warning(f"no products in {folder.name}, campaign {camp_id} untouched")
        return {"rebuilt": 0, "reused": 0, "stale": 0, "failed": 0}

    if seen_item_ids is not None:
        dupes = {p.id for p in products} & seen_item_ids
        if dupes:
            raise ValueError(f"item ids already used by another campaign: {sorted(dupes)}")
        seen_item_ids.update(p.id for p in products)

    old = root.get_child(camp_id)
    existing, parent_of = {}, {}
    if old:
        for i in old.get_items(recursive=True):
            existing[i.id] = i
            coll = i.get_collection()
            parent_of[i.id] = coll.id if coll else camp_id

    props = sc.get("properties") or {}
    rebuilt = reused = 0
    failed_items = []
    for p in products:
        prev = existing.get(p.id)
        if not force and prev is not None and not _needs_rebuild(p, prev):
            p.item = prev.clone()
            reused += 1
            continue
        if not dry_run:
            # created survives rebuilds, updated stamps in build_item
            created = prev.common_metadata.created if prev else None
            try:
                p.item = build_item(p, camp, created=created, properties=props,
                                    crs=sc.get("crs"))
            except Exception:
                log.exception(f"item failed, dropped from this run: {p.id}")
                failed_items.append(p)
                continue
        rebuilt += 1

    if failed_items:
        products = [p for p in products if p not in failed_items]
        if not products:
            log.warning(f"all items failed in {folder.name}, campaign {camp_id} untouched")
            return {"rebuilt": 0, "reused": reused, "stale": 0, "failed": len(failed_items)}

    stale_ids = sorted(set(existing) - {p.id for p in products})
    for sid in stale_ids:
        if policy_stale == "raise":
            raise ValueError(f"stale item {sid}: file gone from {folder.name}")
        if policy_stale == "warn":
            log.warning(f"stale item kept, asset href dangles: {sid}")
        else:
            log.info(f"removed stale item: {sid}")

    counts = {"rebuilt": rebuilt, "reused": reused, "stale": len(stale_ids),
              "failed": len(failed_items)}
    log.info(f"{camp_id}: {rebuilt} rebuilt, {reused} reused, {len(stale_ids)} stale, "
             f"{len(failed_items)} failed")
    if dry_run:
        return counts

    # kept-stale items stay exactly where they were: bucket clones by old parent id
    stale_clones: dict = {}
    if policy_stale == "warn":
        for sid in stale_ids:
            stale_clones.setdefault(parent_of[sid], []).append(existing[sid].clone())

    nodes = resolve_hierarchy(products, sc.get("hierarchy"))
    children = []
    for node in nodes[1:]:
        if not node.products:
            continue
        sub_id = f"{camp_id}_{node.name}"
        meta = {"title": node.title, "description": node.description}
        items = [p.item for p in node.products] + stale_clones.pop(sub_id, [])
        children.append(build_collection(sub_id, meta, items))

    flat_items = [p.item for p in nodes[0].products] + stale_clones.pop(camp_id, [])

    # subcollections that only stale items still reference: recreate from old metadata
    for sub_id, clones in sorted(stale_clones.items()):
        old_sub = old.get_child(sub_id) if old else None
        meta = {"title": old_sub.title if old_sub else None,
                "description": old_sub.description if old_sub else None}
        children.append(build_collection(sub_id, meta, clones))

    camp_coll = build_collection(camp_id, sc.get("collection") or {}, flat_items, children)
    if old is not None:
        root.remove_child(camp_id)
    root.add_child(camp_coll)
    return counts


# --- catalog loop ---

def _load_or_create_root(out_dir: Path) -> pystac.Catalog:
    cat_json = out_dir / "catalog.json"
    cfg = config.section("catalog")
    if cat_json.exists():
        root = pystac.Catalog.from_file(str(cat_json))
        root.make_all_asset_hrefs_absolute()  # asset hrefs survive re-normalization
        # title/description follow the config on every run; id stays (id change = new catalog)
        root.title, root.description = cfg["title"], cfg["description"]
        log.debug(f"loaded existing catalog: {cat_json}")
        return root
    log.info(f"creating new catalog {cfg['id']!r} in {out_dir}")
    return pystac.Catalog(id=cfg["id"], title=cfg["title"], description=cfg["description"])


def update_catalog(
    root, out_dir, *, # positional
    dry_run:    bool = False,
    force:      bool = False,
    validate:   bool = False,
    only: str | None = None,
    policy_stale:   str = "warn",
    policy_unknown: str = "warn",
    policy_non_cn:  str = "warn",
) -> dict:
    """Re-run the whole catalog over a processed-datasets root (idempotent).
    Campaign dirs = direct subdirs with an ISO date token; failures are isolated.

    Collections without a campaign
    dir on disk follow the stale policy (removal is skipped while any campaign
    failed, since a failed campaign's id is unknown).

    Arguments:
        - root ; Path to be scanned for subfolders
        - out_dir ; Path to write the finished catalog to
        - dry_run ; no writes
        - force ; skip checks, rebuild all
        - validate ; calls pystac.validate at the end (requires dependency)
        - only ; look at a single campaign
        - policy_unknown ; in ("warn","skip","raise") decides how to handle unknown assets
        - policy_non_cn ; in ("warn","skip","raise") decides how to handle non cloud-native assets
        - policy_stale ; in ("warn","raise", "remove") decides how to handle stale collections

    Returns:
        {"ok": {campaign: counts}, "failed": {campaign: error},
        "stale_collections": [ids], "validation": None | "ok" | error};

        and written to <out>/last_run.json."""
    root, out_dir = Path(root), Path(out_dir)
    cat = _load_or_create_root(out_dir)

    ok, failed = {}, {}
    seen_camp_ids, seen_item_ids = set(), set()
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.resolve() == out_dir.resolve():
            continue
        if only and not fnmatch.fnmatch(d.name, only):
            log.debug(f"only={only!r} skips {d.name}")
            continue
        try:
            campaign_date(d.name)
        except ValueError:
            log.info(f"not a campaign (no ISO date token): {d.name}")
            continue
        log.info(f"\033[96m=== {d.name} ===\033[00m")
        try:
            ok[d.name] = process_campaign(
                d, cat, policy_stale=policy_stale, dry_run=dry_run, force=force,
                policy_unknown=policy_unknown, policy_non_cn=policy_non_cn,
                seen_camp_ids=seen_camp_ids, seen_item_ids=seen_item_ids)
        except Exception as e:
            log.exception(f"FAILED: {d.name}")
            failed[d.name] = str(e)

    if only:
        stale_colls = []
        log.info("only-filtered run: stale-collection sweep skipped")
    else:
        stale_colls = sorted(c.id for c in cat.get_children() if c.id not in seen_camp_ids)
    for cid in stale_colls:
        if policy_stale == "raise":
            raise ValueError(f"stale collection {cid}: no campaign dir in {root}")
        if policy_stale == "remove" and not failed and not dry_run:
            cat.remove_child(cid)
            log.info(f"removed stale collection: {cid}")
        else:
            log.warning(f"collection kept, campaign dir gone: {cid}")

    validation = None
    if not dry_run:
        cat.normalize_hrefs(str(out_dir))
        cat.make_all_asset_hrefs_relative()
        cat.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
        log.info(f"catalog saved: {out_dir}")
        if validate:
            validation = _validate_catalog(cat)
    res = {"ok": ok, "failed": failed,
           "stale_collections": stale_colls, "validation": validation}
    _write_report(out_dir, res, dry_run=dry_run, force=force, only=only, stale=policy_stale)
    return res


def _write_report(out_dir: Path, res: dict, **knobs) -> None:
    """Machine-readable run report, overwritten each run (dry runs included)."""
    report = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), **knobs, **res}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last_run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.debug(f"run report written: {out_dir / 'last_run.json'}")


def _validate_catalog(root) -> str:
    """root.validate_all() guarded for the optional pystac[validation] extra.
    Returns "ok" or the error string (logged either way)."""
    try:
        import pystac.validation  # noqa: F401 jsonschema presence check
        root.validate_all()
    except ImportError:
        msg = "--validate needs the validation extra: pip install pystac[validation]"
        log.error(msg)
        return msg
    except Exception as e:
        log.error(f"STAC validation failed: {e}")
        return str(e)
    log.info("catalog validates against STAC schemas")
    return "ok"
