"""item + collection builders, id/datetime/geometry, extension wiring, thumbnails"""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

import pystac
from pystac import Collection, Extent, Provider, Summaries
from pystac.extensions.eo import EOExtension
from pystac.extensions.file import FileExtension
from pystac.extensions.pointcloud import PointcloudExtension, Schema, SchemaType, Statistic
from pystac.extensions.projection import ProjectionExtension
from pystac.extensions.raster import RasterExtension

from ..core.registry import SIDECAR_EXTENSIONS
from .extract import _readers

import logging
log = logging.getLogger(__name__)

# TODO thumbnails

_GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
_WEEK = 604800  # seconds


def campaign_date(name: str) -> date:
    """ISO date token (YYYY-MM-DD) from a campaign folder name (firm data-keeping demand)."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(name))
    if not m:
        raise ValueError(f"no ISO date token in {name!r}")
    return date.fromisoformat(m.group())


def resolve_pc_datetime(gps_min, gps_max, campaign: date) -> tuple[datetime, datetime] | None:
    """Raw GPSTime min/max -> (start, end) UTC. Values above one week are adjusted
    standard GPS time (seconds since GPS epoch minus 1e9, absolute); otherwise
    weekseconds resolved against the GPS week of the campaign date.
    Returns:
        - None for absent or degenerate GPSTime, caller falls back to campaign date.
    Note: leap seconds ignored, ~18 s error irrelevant for catalog datetimes."""
    if gps_min is None or gps_max is None or gps_min == gps_max or gps_min < 0:
        return None
    if gps_max > _WEEK:  # adjusted standard
        start = _GPS_EPOCH + timedelta(seconds=gps_min + 1e9)
        end = _GPS_EPOCH + timedelta(seconds=gps_max + 1e9)
    else:  # weekseconds
        if gps_max < gps_min:
            log.warning(f"gps weekseconds wrap Sat->Sun ({gps_min} > {gps_max}), extending into next week")
            gps_max += _WEEK
        week_start = (datetime.combine(campaign, datetime.min.time(), tzinfo=timezone.utc)
                      - timedelta(days=(campaign.weekday() + 1) % 7))
        start = week_start + timedelta(seconds=gps_min)
        end = week_start + timedelta(seconds=gps_max)
    # a stray min OR max poisons the extent; warn on either
    for edge, dt in (("start", start), ("end", end)):
        if abs((dt.date() - campaign).days) > 7:
            log.warning(f"gps {edge} {dt.date()} deviates >7d from campaign date {campaign}")
    return start, end

# maps the random int to the opals type and in turn to the stac type
_STAC_SCHEMA_TYPE = {
    0: SchemaType.SIGNED,   2: SchemaType.SIGNED,   4: SchemaType.SIGNED,   9: SchemaType.SIGNED,   # int32/8/16/64
    1: SchemaType.UNSIGNED, 3: SchemaType.UNSIGNED, 5: SchemaType.UNSIGNED,                          # uint32/8/16
    6: SchemaType.FLOATING, 7: SchemaType.FLOATING,    # float32 / double
    11: SchemaType.UNSIGNED # bool is technically an uint
}

# eo common_name values GDAL color interps can map to (alpha etc. get name only)
_EO_COMMON = {"red", "green", "blue", "nir"}


# ext  → fn(item, pystac_asset, meta, fm) -> None (no I/O)
_extensions: dict[str, Callable] = {}


def extension(name: str):
    """Registers a populator under a registry extension key."""
    def deco(fn):
        _extensions[name] = fn
        return fn
    return deco


@extension("projection")
def _populate_projection(item, pa, meta, fm) -> None:
    proj = ProjectionExtension.ext(item, add_if_missing=True)
    if meta.proj_epsg:
        proj.code = f"EPSG:{meta.proj_epsg}"
    proj.wkt2 = meta.proj_wkt
    if meta.proj_shape:
        proj.shape = meta.proj_shape
    if meta.proj_transform:
        proj.transform = meta.proj_transform
    if meta.proj_bbox:
        proj.bbox = meta.proj_bbox


@extension("pointcloud")
def _populate_pointcloud(item, pa, meta, fm) -> None:
    schemas = []
    for s in meta.pc_schemas:
        t = _STAC_SCHEMA_TYPE.get(s["type"])
        if t is None:
            log.warning(f"unmapped opals column type {s['type']} for {s['name']}, dim dropped from pc:schemas")
            continue
        schemas.append(Schema({"name": s["name"], "size": s["size"], "type": t.value}))
    pc = PointcloudExtension.ext(item, add_if_missing=True)
    pc.apply(
        count=meta.pc_count,
        type=meta.pc_type,
        encoding=_pc_encoding(pa.href),
        schemas=schemas,
        density=meta.pc_density,
        statistics=[Statistic(dict(s)) for s in meta.pc_statistics] or None,
    )


def _pc_encoding(href: str) -> str:
    low = href.lower()
    if low.endswith(".copc.laz"):
        return "copc"
    return low.rsplit(".", 1)[-1]  # laz | las


# raster v1.1 statistics schema is closed, extract's extra "count" key must not leak in
_RASTER_STAT_KEYS = ("minimum", "maximum", "mean", "stddev", "valid_percent")


@extension("raster")
def _populate_raster(item, pa, meta, fm) -> None:
    """raster:bands on the asset (v1.1 per-band fields incl. sampling/resolution)."""
    bands = []
    for b in meta.raster_bands:
        stats = {k: b["statistics"][k] for k in _RASTER_STAT_KEYS if b["statistics"].get(k) is not None}
        rb = {
            "data_type": b["data_type"],
            "nodata": b["nodata"],
            "unit": b["unit"],
            "scale": b["scale"],
            "offset": b["offset"],
            "bits_per_sample": b["bits_per_sample"],
            "sampling": meta.raster_sampling,
            "spatial_resolution": meta.raster_spatial_resolution,
            "statistics": stats or None,
        }
        bands.append({k: v for k, v in rb.items() if v is not None})
    pa.extra_fields["raster:bands"] = bands
    _add_schema(item, RasterExtension.get_schema_uri())


@extension("eo")
def _populate_eo(item, pa, meta, fm) -> None:
    """eo:bands names from color interpretation (RGB orthos)."""
    bands = []
    for b in meta.raster_bands:
        eb = {"name": b["description"] or b["color_interp"] or f"band{b['index']}"}
        if b["color_interp"] in _EO_COMMON:
            eb["common_name"] = b["color_interp"]
        bands.append(eb)
    pa.extra_fields["eo:bands"] = bands
    _add_schema(item, EOExtension.get_schema_uri())


@extension("file")
def _populate_file(item, pa, meta, fm) -> None:
    f = FileExtension.ext(pa, add_if_missing=True)
    # multihash: 0x12 = sha2-256, 0x20 = 32 byte digest
    f.apply(checksum="1220" + fm.sha256, size=fm.size)


def _add_schema(item, uri: str) -> None:
    if uri not in item.stac_extensions:
        item.stac_extensions.append(uri)


_SIDECAR_MEDIA = {".prj": "text/plain", ".tfw": "text/plain", ".aux.xml": "application/xml"}


def build_item(product, campaign: date, *, created: datetime | None = None,
               properties: dict | None = None, crs: str | None = None) -> pystac.Item:
    """Produces and populates a Stac item from a discover::Product
    Steps:
        1) Run readers -> Assetmeta
        2) Resolve datetime
        3) Call populators to add extensions
        4) Apply created (idempotency) and properties (sidecar)
        5) Return pystac.Item
    """
    extracted = []
    for a in product.assets:
        meta = _readers[a.kind](a.path, crs=crs)
        fm = a.file_meta or _readers["file_meta"](a.path)
        extracted.append((a, meta, fm))

    # baseline from the first asset (single-asset products today)
    _, m0, _ = extracted[0]
    span = resolve_pc_datetime(m0.pc_gps_time_min, m0.pc_gps_time_max, campaign)
    start = span[0] if span else datetime.combine(campaign, datetime.min.time(), tzinfo=timezone.utc)

    item = pystac.Item(
        id=product.id,
        geometry=m0.geometry_wgs84,
        bbox=m0.bbox_wgs84,
        datetime=start,
        properties={},
    )
    if span:
        item.common_metadata.start_datetime = span[0]
        item.common_metadata.end_datetime = span[1]

    for a, meta, fm in extracted:
        pa = pystac.Asset(
            href=a.path.resolve().as_posix(),
            media_type=a.media_type,
            roles=list(a.stac_roles),
        )
        item.add_asset(a.label, pa)
        for ext in a.extensions:
            fn = _extensions.get(ext)
            if fn is None:
                log.warning(f"no populator for extension {ext!r} ({a.label})")
                continue
            fn(item, pa, meta, fm)
        for sc in a.sidecars:
            # key = matched sidecar type (prj | tfw | aux.xml), covers foo.tif.aux.xml too
            low = sc.name.lower()
            ext = next(e for e in sorted(SIDECAR_EXTENSIONS, key=len, reverse=True) if low.endswith(e))
            item.add_asset(ext.lstrip("."), pystac.Asset(href=sc.resolve().as_posix(),
                                                         media_type=_SIDECAR_MEDIA.get(ext),
                                                         roles=["metadata"]))

    if m0.raster_spatial_resolution is not None:
        item.common_metadata.gsd = m0.raster_spatial_resolution
    now = datetime.now(timezone.utc)
    item.common_metadata.created = created or now
    item.common_metadata.updated = now
    if properties:
        item.properties.update(properties)

    log.debug(f"built item {item.id} ({len(extracted)} asset(s))")
    return item


# curated collection summaries: sets for categorical, ranges for numeric.
# created/updated (run noise), wkt2 (bloat) and datetime (extent) stay out.
_SUMMARY_SETS = ("proj:code", "platform", "instruments", "pc:encoding")
_SUMMARY_RANGES = ("gsd", "pc:count", "pc:density")


def _summarize(items) -> Summaries | None:
    out = {}
    for f in _SUMMARY_SETS:
        vals = set()
        for i in items:
            v = i.properties.get(f)
            if isinstance(v, list):
                vals.update(v)
            elif v is not None:
                vals.add(v)
        if vals:
            out[f] = sorted(vals)
    for f in _SUMMARY_RANGES:
        nums = [i.properties[f] for i in items if isinstance(i.properties.get(f), (int, float))]
        if nums:
            out[f] = {"minimum": min(nums), "maximum": max(nums)}
    return Summaries(out) if out else None


# id consumed upstream in manager.process_campaign
_COLLECTION_META_KEYS = {"id", "title", "description", "license", "license_link", "providers", "keywords"}


def build_collection(cid: str, meta: dict, items: list, children: Sequence = ()) -> Collection:
    """Generic collection factory for campaign collections and tile subcollections.
    Extent + curated summaries derived from items + children's items. meta keys
    consumed: title, description, license, providers, keywords. providers accepts
    the STAC list form or a name-keyed mapping."""
    all_items = list(items) + [i for c in children for i in c.get_items(recursive=True)]
    if not all_items:
        raise ValueError(f"collection {cid!r} would be empty")

    unknown = set(meta) - _COLLECTION_META_KEYS
    if unknown:
        log.warning(f"collection {cid}: ignored unknown sidecar keys: {sorted(unknown)}")

    providers = meta.get("providers") or []
    if isinstance(providers, dict):  # name-as-key convenience form
        providers = [{"name": name, **(spec or {})} for name, spec in providers.items()]

    coll = Collection(
        id=cid,
        title=meta.get("title"),
        description=meta.get("description") or meta.get("title") or cid,
        extent=Extent.from_items(all_items),
        license=meta.get("license") or "other",
        providers=[Provider.from_dict(p) for p in providers] or None,
        keywords=meta.get("keywords"),
        summaries=_summarize(all_items),
    )
    lic_link = meta.get("license_link")
    if lic_link:
        coll.add_link(pystac.Link(rel="license", target=lic_link, title=meta.get("license")))
    elif meta.get("license") == "other":
        log.warning(f"collection {cid}: license 'other' without a license_link (spec recommends one)")
    for c in children:
        coll.add_child(c)
    for i in items:
        coll.add_item(i)
    return coll


# --- self-check ---

if __name__ == "__main__":
    import sys

    from ..core.log import setup
    from .discover import discover

    setup()

    # build items from real files (raster default, pass a dir for others)
    args = sys.argv[1:]
    folder = Path(args[0]) if args else Path("data/sample_tif")
    products = discover(folder)
    for p in products:
        try:
            camp = campaign_date(str(p.assets[0].path))
        except ValueError:
            camp = date(2023, 2, 8)  # sample files without a date token
        item = build_item(p, camp)
        log.info(f"item {item.id}: dt={item.datetime} ext={len(item.stac_extensions)} assets={list(item.assets)}")
