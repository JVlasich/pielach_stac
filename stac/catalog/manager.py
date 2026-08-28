"""Pipeline orchestration: sidecar load, idempotency gate, campaign loop, catalog write."""

import fnmatch
import hashlib
import json
import logging
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from time import perf_counter

import pystac
import yaml

from ..core import config
from ..core.capabilities import laspy_available
from ..core.registry import merge_overrides
from .build import build_collection, build_item, campaign_date
from .discover import discover, qualify_id
from .extract import file_meta, pcl_point_count
from .hierarchy import resolve_hierarchy
from .policy import RunPolicy
from .thumbnail import render_collection_thumbnail, render_thumbnail

log = logging.getLogger(__name__)

CATALOG_DEFAULTS = {
    "id": "catalog",
    "title": "STAC Catalog",
    "description": "Static STAC catalog.",
    # resolved in cli.py
    "root": None,
    "out": None,             # default: <root>/catalog
    # policy defaults live on RunPolicy (policy.py)
    **RunPolicy.config_defaults(),
    "nbThreads": None,       # opals thread count, None = opals default (all CPUs)
    "exactComputation": True,# exact point statistics (full scan) vs header-only (fast, no stats)
    # root metadata: with both license and providers set, the root is promoted to a Collection
    "license": None,         # root license (SPDX id or "other")
    "providers": None,       # root providers (STAC list or name-keyed mapping)
    "licenseLink": None,     # root rel=license link
}
config.register_defaults("catalog", CATALOG_DEFAULTS)


def load_sidecar(path) -> dict:
    """Per-campaign sidecar YAML -> dict
    (collection / patterns / labels / hierarchy / properties blocks / crs fallback)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{path}: campaign sidecar must be a YAML mapping, not {type(data).__name__}")
    return data


def _register_id(seen: dict | None, new_id: str, kind: str, source: str, policy: str) -> None:
    """One id namespace per run (root/collections/subcollections/items).
    Collision: warn keeps the first owner, raise fails the campaign. Collection ids
    always raise: the second campaign replaces the first one's collection in the root,
    so warn cannot keep the first owner - it merges two campaigns into one collection."""
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
    """(file:size, sha256-hex) stored on the item's data asset, else None."""
    a = item.assets.get(label)
    if a is None:
        return None
    size = a.extra_fields.get("file:size")
    mh = a.extra_fields.get("file:checksum") or ""
    if size is None or not mh.startswith("1220"):
        return None
    return size, mh[4:]


_GATE_KEYS = ("patterns", "labels", "properties", "crs")


def _sidecar_digest(sc: dict) -> str:
    """sha256 over the sidecar keys that change item content. Raw values, before
    merge_overrides normalizes its copies in place: the digest tracks the file, not code
    behaviour. collection is collection-only; exclude and hierarchy already propagate,
    since collections are rebuilt from scratch every run."""
    payload = {k: sc.get(k) for k in _GATE_KEYS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _needs_rebuild(product, existing_item) -> bool:
    """Size shortcut, then sha256 confirm. A computed hash rides on the asset so
    build_item never hashes twice.
    Gates the first asset only (products are single-asset today), and only the data
    asset: a hand-deleted co-located thumbnail or sidecar leaves a dangling href until
    the next --force run."""
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

def _queue_coll_thumb(sub, node, rebuilt_ids: set, parent_of: dict, jobs: list) -> None:
    """Queue one aggregate thumbnail for a tiled point-cloud subcollection.

    Only point-cloud members carrying the registry thumbnail flag render, so plain LAS/LAZ
    stays opt-in (a full read); partial cover warns. The job carries a changed flag - any
    member rebuilt, or the member set moved - because collections are rebuilt every run
    unconditionally and would otherwise re-render every campaign every time. The
    PNG-exists half of the gate waits for the drain: hrefs are undefined until normalize."""
    pcl = [p for p in node.products if p.assets[0].kind == "pcl"]
    flagged = [p for p in pcl if p.assets[0].thumbnail]
    if not flagged:
        return
    if len(flagged) < len(pcl):
        skipped = sorted(p.id for p in pcl if p not in flagged)
        log.warning(f"{sub.id} thumbnail covers {len(flagged)}/{len(pcl)} tiles, "
                    f"no registry thumbnail flag on: {skipped}")
    # stale clones count as members: they sit in the collection, and comparing without
    # them would report a change every run for as long as one is kept
    ids = {i.id for i in sub.get_items()}
    was = {i for i, par in parent_of.items() if par == sub.id}
    changed = bool(rebuilt_ids & ids) or ids != was
    jobs.append((sub, [p.assets[0].path for p in flagged], changed))


def process_campaign(
    folder, root, policy: RunPolicy, *, # positional
    seen_ids: dict | None = None,
    thumb_jobs: list | None = None,
    coll_thumb_jobs: list | None = None
) -> dict:

    """Build or refresh one campaign collection on the root catalog.

    An item build failure (unreadable CRS, reader error) drops only that item, the rest
    of the campaign still builds. A previously cataloged version of a failed item
    follows the stale policy.

    folder ; path to the campaign folder
    policy ; RunPolicy for this run
    seen_ids ; {id: (kind, source)} from update_catalog(), mutated in place
    Returns: {"rebuilt": n, "reused": n, "stale": n, "failed": n, "seconds": {...}}
    Raises: missing campaign.yaml; item/subcollection id collision when
    policy.id_collisions == "raise", collection id collision always
    """
    folder = Path(folder)
    t_start = perf_counter()
    secs = {"discover": 0.0, "hash": 0.0, "build": 0.0}

    def _counts(rebuilt=0, reused=0, stale=0, failed=0) -> dict:
        return {"rebuilt": rebuilt, "reused": reused, "stale": stale, "failed": failed,
                "seconds": {**{k: round(v, 2) for k, v in secs.items()},
                            "total": round(perf_counter() - t_start, 2)}}

    try:
        sc = load_sidecar(folder / "campaign.yaml")
    except FileNotFoundError:
        sc = load_sidecar(folder / "campaign.yml")

    digest = _sidecar_digest(sc)
    sp, lb = merge_overrides(sc.get("patterns"), sc.get("labels"))

    camp = campaign_date(folder.name)
    camp_id = (sc.get("collection") or {}).get("id") or f"{root.id}_{camp.isoformat()}"
    _register_id(seen_ids, camp_id, "collection", folder.name, policy.id_collisions)

    t = perf_counter()
    products = discover(folder, policy, stem_patterns=sp, labels=lb,
                        id_prefix=camp_id, exclude=sc.get("exclude"))
    secs["discover"] = perf_counter() - t

    if not products:
        log.warning(f"no products in {folder.name}, campaign {camp_id} untouched")
        return _counts()

    for p in products:
        _register_id(seen_ids, p.id, "item", folder.name, policy.id_collisions)

    old = root.get_child(camp_id)
    # sidecar edits reach no data file, so the file gate alone would carry stale items over
    stored_digest = (old.extra_fields or {}).get("sidecar:checksum") if old is not None else None
    sidecar_changed = old is not None and stored_digest != digest
    if sidecar_changed:
        if stored_digest is None:  # catalog predates the gate: one full rebuild, then quiet
            log.warning(f"no sidecar gate stored, rebuilding every item in {camp_id}")
        else:
            log.info(f"sidecar changed, rebuilding every item in {camp_id}")
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

    # drop pcl tiles with VERY few points (configurable), laspy header read.
    # a previously cataloged one is removed, not kept stale
    if policy.min_points:
        kept = []
        for p in products:
            if p.kind == "pcl":
                try:
                    n = pcl_point_count(p.assets[0].path)
                except Exception as e:
                    log.warning(f"point-count read failed, tile kept: {p.id} ({e})")
                    kept.append(p)
                    continue
                if n < policy.min_points:
                    log.warning(f"tiny tile dropped ({n} pts < {policy.min_points}): {p.id}")
                    existing.pop(p.id, None)
                    continue
            kept.append(p)
        products = kept
        if not products:
            log.warning(f"all products below minPoints in {folder.name}, campaign {camp_id} untouched")
            return _counts()

    rebuilt = reused = 0
    rebuilt_ids: set[str] = set()   # feeds the subcollection thumbnail gate below
    failed_items = []
    for p in products:
        prev = existing.get(p.id)
        t = perf_counter()
        reuse = (not policy.force and not sidecar_changed and prev is not None
                 and not _needs_rebuild(p, prev))
        secs["hash"] += perf_counter() - t
        if reuse:
            p.item = prev.clone()
            reused += 1
            continue
        if not policy.dry_run:
            # created survives rebuilds, updated stamps in build_item
            created = prev.common_metadata.created if prev else None
            t = perf_counter()
            try:
                p.item = build_item(p, camp, created=created, properties=props,
                                    crs=sc.get("crs"))
            except Exception:
                log.exception(f"item failed, dropped from this run: {p.id}")
                failed_items.append(p)
                continue
            finally:
                secs["build"] += perf_counter() - t
            a0 = p.assets[0]
            if policy.thumbnails and thumb_jobs is not None and a0.thumbnail:
                if a0.kind == "raster":
                    kind = "rgb" if a0.category == "orthophoto" else "hillshade"
                    thumb_jobs.append((p.item, a0.path, kind))
                elif a0.kind == "pcl":
                    thumb_jobs.append((p.item, a0.path, "pointcloud"))
        rebuilt += 1
        rebuilt_ids.add(p.id)

    if failed_items:
        products = [p for p in products if p not in failed_items]
        if not products:
            log.warning(f"all items failed in {folder.name}, campaign {camp_id} untouched")
            return _counts(reused=reused, failed=len(failed_items))

    stale_ids = sorted(set(existing) - {p.id for p in products})
    for sid in stale_ids:
        if policy.stale == "raise":
            raise ValueError(f"stale item {sid}: file gone from {folder.name}")
        if policy.stale == "warn":
            log.warning(f"stale item kept, asset href dangles: {sid}")
        else:
            log.info(f"removed stale item: {sid}")

    counts = (rebuilt, reused, len(stale_ids), len(failed_items))
    log.info(f"{camp_id}: {rebuilt} rebuilt, {reused} reused, {len(stale_ids)} stale, "
             f"{len(failed_items)} failed")
    if policy.dry_run:
        return _counts(*counts)

    # kept-stale items stay exactly where they were: bucket clones by old parent id
    stale_clones: dict = {}
    if policy.stale == "warn":
        for sid in stale_ids:
            stale_clones.setdefault(parent_of[sid], []).append(existing[sid].clone())

    nodes = resolve_hierarchy(products, sc.get("hierarchy"))
    children = []
    for node in nodes[1:]:
        if not node.products:
            continue
        # usually the subdir already carries the campaign (pre-tool writes <stem>_tiles);
        # qualify the ones that do not, same rule as item ids
        sub_id = qualify_id(node.name, camp_id)
        _register_id(seen_ids, sub_id, "subcollection", folder.name, policy.id_collisions)
        cat = node.products[0].category
        camp_meta = sc.get("collection") or {}  # tiles inherit the campaign's attribution
        meta = {"title": node.title or f"{cat} tiles",
                "description": node.description or f"Tiled {cat} for campaign {camp_id}.",
                "providers": camp_meta.get("providers"),
                "keywords": camp_meta.get("keywords")}
        items = [p.item for p in node.products] + stale_clones.pop(sub_id, [])
        sub = build_collection(sub_id, meta, items)
        children.append(sub)
        if policy.thumbnails and coll_thumb_jobs is not None:
            _queue_coll_thumb(sub, node, rebuilt_ids, parent_of, coll_thumb_jobs)

    flat_items = [p.item for p in nodes[0].products] + stale_clones.pop(camp_id, [])

    # subcollections that only stale items still reference: recreate from old metadata
    for sub_id, clones in sorted(stale_clones.items()):
        old_sub = old.get_child(sub_id) if old else None
        meta = {"title": old_sub.title if old_sub else None,
                "description": old_sub.description if old_sub else None}
        children.append(build_collection(sub_id, meta, clones))

    camp_coll = build_collection(camp_id, sc.get("collection") or {}, flat_items, children)
    camp_coll.extra_fields["sidecar:checksum"] = digest  # next run's sidecar half of the gate
    if old is not None:
        root.remove_child(camp_id)
    root.add_child(camp_coll)
    return _counts(*counts)


# --- catalog loop ---

def _root_providers(cfg) -> list:
    provs = cfg["providers"] or []
    if isinstance(provs, dict):  # name-as-key convenience form (mirrors build_collection)
        provs = [{"name": name, **(spec or {})} for name, spec in provs.items()]
    return [pystac.Provider.from_dict(p) for p in provs]


def _union_extent(children) -> pystac.Extent:
    """Spatial bbox + temporal interval aggregated over the child collections."""
    bboxes = [c.extent.spatial.bboxes[0] for c in children if c.extent.spatial.bboxes]
    if bboxes:
        sp = pystac.SpatialExtent([[min(b[0] for b in bboxes), min(b[1] for b in bboxes),
                                    max(b[2] for b in bboxes), max(b[3] for b in bboxes)]])
    else:
        sp = pystac.SpatialExtent([[-180, -90, 180, 90]])
    intervals = [c.extent.temporal.intervals[0] for c in children if c.extent.temporal.intervals]
    starts = [i[0] for i in intervals if i and i[0]]
    ends = [i[1] for i in intervals if i and i[1]]
    tp = pystac.TemporalExtent([[min(starts) if starts else None, max(ends) if ends else None]])
    return pystac.Extent(sp, tp)


def _load_or_create_root(out_dir: Path) -> pystac.Catalog:
    """Load or create the root. With license and providers both configured the root is a
    Collection (union extent set after the campaign loop), else a bare Catalog. A root
    type change across runs migrates the existing children over."""
    cat_json = out_dir / "catalog.json"
    cfg = config.section("catalog")
    promote = bool(cfg["license"] and cfg["providers"])

    existing = None
    if cat_json.exists():
        existing = pystac.read_file(str(cat_json))
        existing.make_all_asset_hrefs_absolute()  # asset hrefs survive re-normalization

    # Collection is a Catalog subclass, so match on the promote flag directly
    reuse = existing is not None and (promote == isinstance(existing, pystac.Collection))
    if reuse:
        root = existing
    else:
        if promote:
            placeholder = pystac.Extent(pystac.SpatialExtent([[-180, -90, 180, 90]]),
                                        pystac.TemporalExtent([[None, None]]))
            root = pystac.Collection(id=cfg["id"], title=cfg["title"], description=cfg["description"],
                                     extent=placeholder, license=cfg["license"] or "other")
        else:
            root = pystac.Catalog(id=cfg["id"], title=cfg["title"], description=cfg["description"])
        if existing is not None:
            log.info(f"root type -> {'Collection' if promote else 'Catalog'}, migrating children")
            for c in list(existing.get_children()):
                root.add_child(c)
        else:
            log.info(f"creating new {'collection' if promote else 'catalog'} {cfg['id']!r} in {out_dir}")

    # title/description follow the config on every run; id stays (id change = new catalog)
    root.title, root.description = cfg["title"], cfg["description"]
    if promote:
        root.license = cfg["license"]
        root.providers = _root_providers(cfg)
        root.remove_links("license")  # rebuild the license link idempotently
        if cfg["licenseLink"]:
            root.add_link(pystac.Link(rel="license", target=cfg["licenseLink"], title=cfg["license"]))
    return root


class _WarnCollector(logging.Handler):
    """Collects warning records during a run so they land in last_run.json."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs: list[str] = []
        self.setFormatter(logging.Formatter("%(name)s | %(message)s"))

    def emit(self, record):
        self.msgs.append(self.format(record))


def update_catalog(root, out_dir, policy: RunPolicy) -> dict:
    """Re-run the whole catalog over a processed-datasets root (idempotent).
    Campaign dirs = direct subdirs with an ISO date token; failures are isolated.

    Collections with no campaign dir on disk follow the stale policy. The sweep acts
    only on clean runs: while any campaign failed its collection id is unknown, so
    flagged collections are kept with a warning regardless of policy.

    root ; Path scanned for campaign subfolders
    out_dir ; Path the finished catalog is written to
    policy ; RunPolicy for this run, passed unchanged to every campaign

    Returns: {"ok": {campaign: counts}, "failed": {campaign: error},
    "stale_collections": [ids], "validation": None | "ok" | error, "seconds": {...}};
    also written to <out_dir>/last_run.json."""
    root, out_dir = Path(root), Path(out_dir)
    t_start = perf_counter()
    cat = _load_or_create_root(out_dir)

    ok, failed, stale_colls, validation, fatal = {}, {}, [], None, None
    secs = {"thumbnails": 0.0, "save": 0.0}
    warns = _WarnCollector()
    root_logger = logging.getLogger()
    root_logger.addHandler(warns)
    try:
        seen_ids: dict = {cat.id: ("catalog", "root")}
        # (item, src_path, kind) for rebuilt raster items, rendered after normalize
        thumb_jobs: list = []
        # (collection, [tile paths], changed) for tiled point-cloud subcollections
        coll_thumb_jobs: list = []
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.resolve() == out_dir.resolve():
                continue
            if policy.only and not fnmatch.fnmatch(d.name, policy.only):
                log.debug(f"only={policy.only!r} skips {d.name}")
                continue
            try:
                campaign_date(d.name)
            except ValueError:
                log.info(f"not a campaign (no ISO date token): {d.name}")
                continue
            log.info(f"\033[96m=== {d.name} ===\033[00m")
            try:
                ok[d.name] = process_campaign(
                    d, cat, policy, seen_ids=seen_ids, thumb_jobs=thumb_jobs,
                    coll_thumb_jobs=coll_thumb_jobs)
            except Exception as e:
                log.exception(f"FAILED: {d.name}")
                failed[d.name] = str(e)

        if policy.only:
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
            if policy.stale == "raise":
                raise ValueError(f"stale collection {cid}: no campaign dir in {root}")
            if policy.stale == "remove" and not policy.dry_run:
                cat.remove_child(cid)
                log.info(f"removed stale collection: {cid}")
            else:
                log.warning(f"collection kept, campaign dir gone: {cid}")

        if isinstance(cat, pystac.Collection):  # promoted root: aggregate extent over campaigns
            cat.extent = _union_extent(list(cat.get_children()))

        if not policy.dry_run:
            cat.normalize_hrefs(str(out_dir))
            if isinstance(cat, pystac.Collection):
                cat.set_self_href(str(out_dir / "catalog.json"))  # stable root entry point (not collection.json)
            if policy.thumbnails:
                t = perf_counter()
                # pcl thumbnails need laspy
                pcl_ok = laspy_available()
                if not pcl_ok and (coll_thumb_jobs
                                   or any(k == "pointcloud" for *_, k in thumb_jobs)):
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
                for coll, srcs, changed in (coll_thumb_jobs if pcl_ok else []):
                    png = Path(coll.get_self_href()).parent / f"{coll.id}_thumbnail.png"
                    try:
                        if changed or policy.force or not png.exists():
                            render_collection_thumbnail(coll, srcs)
                        # unlike items, collections are rebuilt from scratch every run and
                        # carry no assets forward: attach on the skip path too
                        coll.add_asset("thumbnail", pystac.Asset(
                            href=png.resolve().as_posix(), media_type="image/png",
                            roles=["thumbnail"]))
                    except Exception as e:
                        log.warning(f"thumbnail failed for {coll.id}: {e}")
                secs["thumbnails"] = perf_counter() - t
            if policy.asset_hrefs == "relative":
                cat.make_all_asset_hrefs_relative()
            # thumbnails live inside the catalog tree: always relative, both href modes
            for obj in chain(cat.get_items(recursive=True), cat.get_all_collections()):
                for asset in obj.assets.values():
                    if "thumbnail" in (asset.roles or []):
                        asset.href = pystac.utils.make_relative_href(
                            asset.get_absolute_href(), obj.get_self_href())
            t = perf_counter()
            cat.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
            secs["save"] = perf_counter() - t
            log.info(f"catalog saved: {out_dir}")
            if policy.validate:
                validation = _validate_catalog(cat)
    except Exception as e:
        fatal = f"{type(e).__name__}: {e}"
        raise
    finally:
        root_logger.removeHandler(warns)
        secs = {k: round(v, 2) for k, v in secs.items()}
        secs["total"] = round(perf_counter() - t_start, 2)
        res = {"ok": ok, "failed": failed, "stale_collections": stale_colls,
               "validation": validation, "seconds": secs, "warnings": warns.msgs}
        if fatal:
            res["fatal"] = fatal
        _write_report(res, out_dir, dry_run=policy.dry_run, force=policy.force,
                      only=policy.only, stale=policy.stale)
    return res


def _write_report(res: dict, out_dir: Path, **knobs) -> None:
    """Machine-readable run report next to the catalog, overwritten each run (dry runs
    included). Not a STAC object, but it belongs to the catalog it describes; written to
    the working directory it forked into one copy per directory a run was started in."""
    report = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), **knobs, **res}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "last_run.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.debug(f"run report written: {path}")


def _validate_catalog(root) -> str:
    """root.validate_all(), guarded for the optional pystac[validation] extra.
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
