"""Asset discovery and matching.

Walk a campaign's product folder, classify files against the registry, probe each file's
cloud-native status, emit one Product (= one future Item) per file,
resolve cloud-native twins, mark tile groups, associate sidecars,
and route anything unclassifiable through unknown_asset_policy.
"""

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from osgeo import gdal

from ..core.registry import STEM_PATTERNS, LABELS, SIDECAR_EXTENSIONS
log = logging.getLogger(__name__)

try:  # optional, (pip install gdal-utils on GDAL < 3.2)
    from osgeo_utils.samples.validate_cloud_optimized_geotiff import validate as _validate_cog
except ImportError:
    _validate_cog = None

gdal.UseExceptions()

COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"


@dataclass
class Asset:
    path: Path
    label: str
    category: str
    kind: str          # pcl | raster  (dispatches extract.py @reader)
    stac_roles: list
    media_type: str
    extensions: list   # which @populators run
    cloud_native: bool
    sidecars: list = field(default_factory=list)  # Paths matched by full basename
    file_meta: object = None  # extract.FileMeta, attached by manager's gate when it hashed

    def __str__(self) -> str:
        cn = "cloud-native" if self.cloud_native else "NOT cloud-native"
        sc = f" · {len(self.sidecars)} sidecar(s)" if self.sidecars else ""
        return (f"Asset {self.path.name!r}  [{self.label}, {self.category}/{self.kind}]"
                f" · {cn} · {self.media_type}{sc}")


@dataclass
class Product:
    id: str            # one future Item
    category: str
    kind: str
    assets: list[Asset]       # always length 1 today; kept a list for the Item builder
    group: str | None = None  # tile-group name -> subcollection; None -> flat in the campaign
    item: object = None       # pystac.Item, attached by manager (build or reuse); untyped so discover stays pystac-free

    def __str__(self) -> str:
        head = f"Product {self.id!r}  [{self.category}/{self.kind}]"
        if self.group:
            head += f"  group={self.group}"
        lines = [head]
        for i, a in enumerate(self.assets):
            branch = "└─" if i == len(self.assets) - 1 else "├─"
            lines.append(f"{branch} {a}")
        return "\n".join(lines)


# --- matching ---

def _match_ext(low_name: str, exts) -> str | None:
    """The longest of a pattern's extensions that low_name ends with, else None."""
    for e in sorted(exts, key=len, reverse=True):
        if low_name.endswith(e):
            return e
    return None


def _best_match(name: str, stem_patterns):
    """Most specific (pattern, matched_ext) for a filename, or None. Specificity = more require
    tokens, then longer extension (so dtm_masked > dtm, .copc.laz > .laz)."""
    low = name.lower()
    candidates = []
    for label, pat in stem_patterns.items():
        ext = _match_ext(low, pat["extensions"])
        if ext is None:
            continue
        tokens = set(name[: -len(ext)].lower().split("_"))
        if not set(pat["require"]) <= tokens:
            continue
        if set(pat["forbid"]) & tokens:
            continue
        candidates.append((label, pat, ext))
    if not candidates:
        return None
    return max(candidates, key=lambda c: (len(c[1]["require"]), len(c[2])))


def match(filename, stem_patterns=STEM_PATTERNS) -> str | None:
    """The most specific registry label for a filename, or None."""
    bm = _best_match(Path(filename).name, stem_patterns)
    return bm[0] if bm else None


# --- cloud-native probe ---

def _probe_cloud_native(path: Path, kind: str, ext: str) -> bool:
    """Pointclouds: ext == .copc.laz
    Rasters: GDAL reports LAYOUT=COG for COG-structured files regardless of filename
    files it detects also get the full COG validator,
    advisory only (structural errors warn but stay cloud-native).
    Unreadable rasters warn and count as non-cloud-native."""
    if kind == "pcl":
        return ext == ".copc.laz"
    if kind != "raster":
        return False
    try:
        ds = gdal.Open(str(path))
    except RuntimeError as e:
        log.warning(f"gdal open failed ({path.name}): {e}")
        return False
    if ds.GetMetadataItem("LAYOUT", "IMAGE_STRUCTURE") != "COG":
        return False
    if _validate_cog is not None:
        _, errors, _ = _validate_cog(str(path))
        if errors:
            log.warning(f"invalid COG ({path.name}): {'; '.join(errors)}")
    return True


# --- ids / twins / tile groups ---

def _item_id(name: str, ext: str) -> str:
    """Deterministic id: the filename's tokens minus the cog marker, original order/case,
    so an item keeps its id when a plain raster is later converted to COG."""
    tokens = name[: -len(ext)].split("_")
    return "_".join(t for t in tokens if t.lower() != "cog")


def _twin_key(m: "_Match"):
    """Two files are format twins when only the cog/copc marker differs
    (dtm.tif vs dtm_cog.tif; x.laz vs x.copc.laz -- .copc is part of the matched ext)."""
    tokens = frozenset(m.path.name[: -len(m.ext)].lower().split("_")) - {"cog"}
    return (m.path.parent, m.category, tokens)


def _cog_named(m: "_Match") -> bool:
    return "cog" in m.path.name[: -len(m.ext)].lower().split("_")


# format preference among twins; unlisted (raster) extensions rank equal
_EXT_RANK = {".copc.laz": 2, ".laz": 1, ".las": 0}


def _resolve_twins(matches: list["_Match"], policy: str) -> list["_Match"]:
    """Determines how twins are handled.
    Handles pcl and rasters at the same time. Precedent:
        1) has cloud_native attribute (pcl & raster)
        2) is "cog" named (raster)
        3) format rank (.copc.laz > .laz > .las) (pcl)
    One deterministic winner per twin bucket.
    non-cloud-native winner goes through the non_cloud_native policy:
    warn = catalog + warning | skip = drop | raise.

    Parameters:
        - matches; list of matches as produced in discover()
        - policy; 'warn' | 'skip' | 'raise'
    Returns: list of matches"""
    buckets: dict = {}
    for m in matches:
        buckets.setdefault(_twin_key(m), []).append(m)
    kept = []
    for members in buckets.values():
        non_copc = {m.ext for m in members} - {".copc.laz"}
        if len(non_copc) > 1:
            names = ", ".join(sorted(m.path.name for m in members))
            log.warning(f"extension mix in twins ({names}), keeping preferred format")
        winner = max(members, key=lambda m: (m.cloud_native, _cog_named(m), _EXT_RANK.get(m.ext, 0)))
        for m in members:
            if m is not winner:
                log.debug(f"superseded by twin {winner.path.name}: {m.path.name}")
        if winner.cloud_native:
            kept.append(winner)
            continue
        reason = "named cog, not a COG" if _cog_named(winner) else "non-cloud-native"
        if policy == "raise":
            raise ValueError(f"{reason}: {winner.path.name}")
        if policy == "warn":
            log.warning(f"{reason} ({winner.label}): {winner.path.name}")
            kept.append(winner)
        # skip: drop silently
    return kept


def _assign_tile_groups(products: list, root: Path) -> None:
    """Tiled = more than one product of a category sharing a subdir below the campaign
    root (tac_pcl writes all tiles of one cloud into one dir). The subdir names
    the subcollection; files at the root stay flat. Single place to change this policy."""
    buckets: dict = {}
    for p in products:
        parent = p.assets[0].path.parent
        if parent != root:
            buckets.setdefault((parent, p.category), []).append(p)
    for (parent, _), members in buckets.items():
        if len(members) > 1:
            name = "_".join(parent.relative_to(root).parts)
            for m in members:
                m.group = name


# --- discovery ---

@dataclass
class _Match:
    path: Path
    label: str
    category: str
    ext: str
    info: dict
    cloud_native: bool


def _walk(folder: Path) -> list:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def _sidecar_ext(name: str) -> str | None:
    low = name.lower()
    for e in sorted(SIDECAR_EXTENSIONS, key=len, reverse=True):
        if low.endswith(e):
            return e
    return None


def _handle_unknown(path: Path, reason: str, policy: str) -> None:
    if policy == "raise":
        raise ValueError(f"unknown asset {path.name}: {reason}")
    if policy == "warn":
        log.warning(f"skip ({reason}): {path.name}")
    # skip: silent


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def discover(folder: str | Path, policy_unknown: str = "warn", stem_patterns=None, labels=None,
             policy_non_cn: str = "warn", id_prefix: str | None = None) -> list:
    """Discover Products under a campaign folder. Walks a folder, applies policies,
    assigns .group (for pcl-tiles). Pass merge_overrides() output to apply per-campaign overrides.

    Arguments:
        - folder ; the folder to be walked
        - policy_unknown ; in ("warn","skip","raise") decides how to handle unknown assets
        - policy_non_cn ; in ("warn","skip","raise") decides how to handle non cloud-native assets
        - stem_patterns ; which stem-patterns to look for
        - labels ; the labels the stem-patterns point to
        - id_prefix ; fallback for files without ISO token, guarantees unique ID
    Returns:
        - List of Products
    """
    sp = stem_patterns if stem_patterns is not None else STEM_PATTERNS
    lb = labels if labels is not None else LABELS
    folder = Path(folder)
    files = _walk(folder)
    sidecars = [f for f in files if _sidecar_ext(f.name)]
    # campaign.yaml is the per-campaign sidecar, never an asset
    candidates = [f for f in files if not _sidecar_ext(f.name) and f.name.lower() != "campaign.yaml"]

    matches = []
    for f in candidates:
        bm = _best_match(f.name, sp)
        if bm is None:
            _handle_unknown(f, "no registry match", policy_unknown)
            continue
        label, pat, ext = bm
        if label not in lb:
            _handle_unknown(f, f"label {label!r} not in LABELS", policy_unknown)
            continue
        info = lb[label]
        if info["category"] == "ignore":
            log.debug(f"ignored ({label}): {f.name}")
            continue
        cn = _probe_cloud_native(f, info["kind"], ext)
        matches.append(_Match(f, label, info["category"], ext, info, cn))

    matches = _resolve_twins(matches, policy_non_cn)

    products = []
    seen_ids: dict = {}
    for m in sorted(matches, key=lambda m: m.path.name):
        item_id = _item_id(m.path.name, m.ext)
        if id_prefix and not _ISO_DATE.search(item_id):
            item_id = f"{id_prefix}_{item_id}"
        # if item_id[:1].isupper():
        #     log.warning(f"id starts with an uppercase letter (kept as-is): {item_id}")
        if item_id in seen_ids:
            raise ValueError(f"id collision: {item_id!r} from {seen_ids[item_id]} and {m.path.name}")
        seen_ids[item_id] = m.path.name

        is_cog = m.info["kind"] == "raster" and m.cloud_native
        asset = Asset(
            path=m.path,
            label=m.label,
            category=m.category,
            kind=m.info["kind"],
            stac_roles=list(m.info["stac_roles"]),
            media_type=COG_MEDIA_TYPE if is_cog else m.info["media_type"],
            extensions=list(m.info["extensions"]),
            cloud_native=m.cloud_native,
        )
        # same dir + stem form (x.prj) or full-name form (x.tif.aux.xml)
        base = m.path.name[: -len(m.ext)]
        asset.sidecars = [
            sc for sc in sidecars
            if sc.parent == m.path.parent
            and sc.name[: -len(_sidecar_ext(sc.name) or "")] in (base, m.path.name)
        ]
        products.append(Product(id=item_id, category=m.category, kind=m.info["kind"], assets=[asset]))

    _assign_tile_groups(products, folder)
    log.debug(f"{len(files)} files -> {len(products)} products in {folder}")
    return products


# --- self-check ---
def _report(products) -> None:
    lines = [f"products ({len(products)}):"]
    for p in products:
        grp = f"  group={p.group}" if p.group else ""
        lines.append(f"  {p.id}  [{p.category}/{p.kind}]{grp}")
        for a in p.assets:
            cn = "" if a.cloud_native else "  (non-cloud-native)"
            sc = f"\n\t\tsidecars={[s.name for s in a.sidecars]}" if a.sidecars else ""
            lines.append(f"      - {a.label}: {a.path.name}{cn}{sc}")
    log.info("\n".join(lines))


if __name__ == "__main__":
    from ..core.log import setup

    setup()

    args = sys.argv[1:]
    if args:
        _report(discover(Path(args[0])))
    else:
        log.info("usage: python -m stac.catalog.discover <folder>")
