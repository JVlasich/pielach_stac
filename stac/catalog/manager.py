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
from .thumbnail import pcl_thumbnails_available, render_thumbnail

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
    "idCollisions": "warn",  # warn | raise for duplicate item/subcollection ids across campaigns
    "assetHrefs": "absolute",# relative (self-contained) | absolute (keep build-time paths)
    "nbThreads": None,       # opals thread count, None = opals default (all CPUs)
    "exactComputation": True,# exact point statistics (full scan) vs header-only (fast, no stats)
    "thumbnails": True,      # render PNG thumbnails for raster items (ortho/DSM/DTM)
}
config.register_defaults("catalog", CATALOG_DEFAULTS)


def load_sidecar(path) -> dict:
    """Read a per-campaign sidecar YAML into a dict
    (collection / patterns / labels / hierarchy / properties blocks / crs fallback)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{path}: campaign sidecar must be a YAML mapping, not {type(data).__name__}")
    return data


def _register_id(seen: dict | None, new_id: str, kind: str, source: str, policy: str) -> None:
    """One id namespace per run (root/collections/subcollections/items).
    Collision: warn keeps the first owner, raise fails the campaign. Collection ids
    always raise: the second campaign replaces the first one's collection in the root,
    so warn cannot keep the first owner, it merges two campaigns into one collection."""
    if seen is None:
        return
    if new_id in seen:
        k2, s2 = seen[new_id]
        msg = f"id collision: {new_id!r} ({kind}, {source}) already used by {k2} ({s2})"
        if policy == "raise" or kind == "collection":
            raise ValueError(msg)
        log.warning(msg)
        return
    seen[new_id] = (kind, source)


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
    Note: gates the first asset only, products are single-asset today. The gate hashes
    only the data asset, so a hand-deleted co-located thumbnail or sidecar leaves a
    dangling href until the next --force run."""
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
    policy_ids:     str = "warn",
    seen_ids: dict | None = None,
    thumbnails: bool = True,
    thumb_jobs: list | None = None
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
        - policy_ids ; in ("warn","raise") decides how to handle id collisions in the run namespace
          (collection ids always raise, see _register_id)
        - seen_ids ; {id: (kind, source)} passed in update_catalog() and mutated inplace
    Returns:
        {"rebuilt": n, "reused": n, "stale": n, "failed": n}
    Exceptions:
        - missing campaign.yaml
        - item/subcollection id collisions when policy_ids == "raise", collection ids always
    """
    folder = Path(folder)
    sc = load_sidecar(folder / "campaign.yaml")
    sp, lb = merge_overrides(sc.get("patterns"), sc.get("labels"))

    camp = campaign_date(folder.name)
    camp_id = (sc.get("collection") or {}).get("id") or f"pielach_{camp.isoformat()}"
    _register_id(seen_ids, camp_id, "collection", folder.name, policy_ids)

    products = discover(folder, policy_unknown=policy_unknown, stem_patterns=sp, labels=lb,
                        policy_non_cn=policy_non_cn, id_prefix=camp_id)

    if not products:
        log.warning(f"no products in {folder.name}, campaign {camp_id} untouched")
        return {"rebuilt": 0, "reused": 0, "stale": 0, "failed": 0}

    for p in products:
        _register_id(seen_ids, p.id, "item", folder.name, policy_ids)

    old = root.get_child(camp_id)
    existing, parent_of = {}, {}
    if old:
        for i in old.get_items(recursive=True):
            existing[i.id] = i
            coll = i.get_collection()
            parent_of[i.id] = coll.id if coll else camp_id

    props = sc.get("properties") or {}
    # typo guard: override keys must hit something in this campaign
    labels = {a.label for p in products for a in p.assets}
    for lbl in (props.get("byLabel") or {}):
        if lbl not in labels:
            log.warning(f"properties.byLabel matches no product label: {lbl}")
    item_ids = {p.id for p in products}
    for iid in (props.get("byId") or {}):
        if iid not in item_ids:
            log.warning(f"properties.byId matches no item id: {iid}")

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
            a0 = p.assets[0]
            if thumbnails and thumb_jobs is not None and a0.thumbnail:
                if a0.kind == "raster":
                    kind = "rgb" if a0.category == "orthophoto" else "hillshade"
                    thumb_jobs.append((p.item, a0.path, kind))
                elif a0.kind == "pcl":
                    thumb_jobs.append((p.item, a0.path, "pointcloud"))
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
        # the subdir already carries the campaign (pre-tool writes <stem>_tiles), take it as-is
        sub_id = node.name
        _register_id(seen_ids, sub_id, "subcollection", folder.name, policy_ids)
        cat = node.products[0].category
        meta = {"title": node.title or f"{cat} tiles",
                "description": node.description or f"Tiled {cat} for campaign {camp_id}."}
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


class _WarnCollector(logging.Handler):
    """Captures warnings records during a run so they land in last_run.json."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs: list[str] = []
        self.setFormatter(logging.Formatter("%(name)s | %(message)s"))

    def emit(self, record):
        self.msgs.append(self.format(record))


def update_catalog(
    root, out_dir, *, # positional
    dry_run:    bool = False,
    force:      bool = False,
    validate:   bool = False,
    only: str | None = None,
    asset_hrefs: str = "absolute",
    policy_stale:   str = "warn",
    policy_unknown: str = "warn",
    policy_non_cn:  str = "warn",
    policy_ids:     str = "warn",
    thumbnails:     bool = True,
) -> dict:
    """Re-run the whole catalog over a processed-datasets root (idempotent).
    Campaign dirs = direct subdirs with an ISO date token; failures are isolated.

    Collections without a campaign
    dir on disk follow the stale policy. The sweep acts only on clean runs:
    while any campaign failed its collection id is unknown, so flagged
    collections are kept with a warning regardless of policy.

    Arguments:
        - root ; Path to be scanned for subfolders
        - out_dir ; Path to write the finished catalog to
        - dry_run ; no writes
        - force ; skip checks, rebuild all
        - validate ; calls pystac.validate at the end (requires dependency)
        - only ; look at a single campaign
        - asset_hrefs ; "absolute" (keep build-time paths, default) or "relative"
          (self-contained); thumbnail assets are always written relative
        - policy_unknown ; in ("warn","skip","raise") decides how to handle unknown assets
        - policy_non_cn ; in ("warn","skip","raise") decides how to handle non cloud-native assets
        - policy_stale ; in ("warn","raise", "remove") decides how to handle stale collections
        - policy_ids ; in ("warn","raise") decides how to handle id collisions
          (one namespace: root + collections + subcollections + items;
          collection ids always raise, they cannot be resolved by keeping the first owner)

    Returns:
        {"ok": {campaign: counts}, "failed": {campaign: error},
        "stale_collections": [ids], "validation": None | "ok" | error};

        and written to <out>/last_run.json."""
    root, out_dir = Path(root), Path(out_dir)
    cat = _load_or_create_root(out_dir)

    ok, failed, stale_colls, validation, fatal = {}, {}, [], None, None
    warns = _WarnCollector()
    root_logger = logging.getLogger()
    root_logger.addHandler(warns)
    try:
        seen_ids: dict = {cat.id: ("catalog", "root")}
        # (item, src_path, kind) for rebuilt raster items, rendered after normalize
        thumb_jobs: list = []
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
                    policy_ids=policy_ids, seen_ids=seen_ids,
                    thumbnails=thumbnails, thumb_jobs=thumb_jobs)
            except Exception as e:
                log.exception(f"FAILED: {d.name}")
                failed[d.name] = str(e)

        if only:
            stale_colls = []
            log.info("only-filtered run: stale-collection sweep skipped")
        else:
            camp_ids = {i for i, (kind, _) in seen_ids.items() if kind == "collection"}
            stale_colls = sorted(c.id for c in cat.get_children() if c.id not in camp_ids)
        for cid in stale_colls:
            # a failed campaign never registers its id, so its collection would be
            # misread as stale; act (raise/remove) only on clean runs
            if failed:
                log.warning(f"collection kept, no surviving campaign this run "
                            f"(dir gone or campaign failed): {cid}")
                continue
            if policy_stale == "raise":
                raise ValueError(f"stale collection {cid}: no campaign dir in {root}")
            if policy_stale == "remove" and not dry_run:
                cat.remove_child(cid)
                log.info(f"removed stale collection: {cid}")
            else:
                log.warning(f"collection kept, campaign dir gone: {cid}")

        if not dry_run:
            cat.normalize_hrefs(str(out_dir))
            if thumbnails:
                # thumb creation for pcl -> make sure laspy can load
                pcl_ok = pcl_thumbnails_available()
                if not pcl_ok and any(k == "pointcloud" for *_, k in thumb_jobs):
                    log.warning("laspy/lazrs unavailable; skipping point-cloud thumbnails")
                for item, src, kind in thumb_jobs:
                    if kind == "pointcloud" and not pcl_ok:
                        continue
                    try:
                        href = render_thumbnail(item, src, kind)
                        item.add_asset("thumbnail", pystac.Asset(
                            href=href, media_type="image/png", roles=["thumbnail"]))
                    except Exception as e:
                        log.warning(f"thumbnail failed for {item.id}: {e}")
            if asset_hrefs == "relative":
                cat.make_all_asset_hrefs_relative()
            # thumbnails live inside the catalog tree: always relative, both href modes
            for item in cat.get_items(recursive=True):
                for asset in item.assets.values():
                    if "thumbnail" in (asset.roles or []):
                        asset.href = pystac.utils.make_relative_href(
                            asset.get_absolute_href(), item.get_self_href())
            cat.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
            log.info(f"catalog saved: {out_dir}")
            if validate:
                validation = _validate_catalog(cat)
    except Exception as e:
        fatal = f"{type(e).__name__}: {e}"
        raise
    finally:
        root_logger.removeHandler(warns)
        res = {"ok": ok, "failed": failed, "stale_collections": stale_colls,
               "validation": validation, "warnings": warns.msgs}
        if fatal:
            res["fatal"] = fatal
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
