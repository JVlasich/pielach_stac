"""Asset discovery and matching.

Walk a campaign's product folder, classify files against the registry, group them into future Items,
associate sidecars, and route anything unclassifiable through unknown_asset_policy.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..core.registry import STEM_PATTERNS, LABELS, SIDECAR_EXTENSIONS


@dataclass
class Asset:
    path: Path
    label: str
    category: str
    kind: str          # pcl | raster  (dispatches extract.py @reader)
    stac_roles: list
    media_type: str
    extensions: list   # which @populators run
    sidecars: list = field(default_factory=list)  # Paths matched by full basename


@dataclass
class Product:
    id: str            # one future Item
    category: str
    kind: str
    assets: list[Asset]       # 1 for a PC tile; N variants for a raster category


# --- matching ---

def _match_ext(low_name: str, exts) -> str | None:
    """The longest of a pattern's extensions that low_name ends with, else None."""
    for e in sorted(exts, key=len, reverse=True):
        if low_name.endswith(e):
            return e
    return None


def _best_match(name: str):
    """Most specific (pattern, matched_ext) for a filename, or None. Specificity = more require
    tokens, then longer extension (so dtm_masked > dtm, .copc.laz > .laz)."""
    low = name.lower()
    candidates = []
    for label, pat in STEM_PATTERNS.items():
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


def match(filename) -> str | None:
    """The most specific registry label for a filename, or None."""
    bm = _best_match(Path(filename).name)
    return bm[0] if bm else None


# --- grouping / ids ---

def _group_key(tokens, require, category) -> frozenset:
    """Order-independent grouping key: drop only the variant tokens, keep the category token."""
    return frozenset(tokens) - (set(require) - {category})


def _item_id(members) -> str:
    """Deterministic id from the lexicographically-smallest member: its tokens minus that file's
    variant tokens, in original order."""
    rep = min(members, key=lambda m: m.path.name)
    strip = set(rep.require) - {rep.category}
    tokens = rep.path.name[: -len(rep.ext)].split("_")
    return "_".join(t for t in tokens if t.lower() not in strip)


# --- discovery ---

@dataclass
class _Match:
    path: Path
    label: str
    category: str
    require: list
    ext: str
    info: dict


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
        print(f"WARN skip ({reason}): {path.name}", file=sys.stderr)
    # skip: silent


def discover(folder, policy: str = "warn") -> list:
    """Discover Products under a campaign folder. policy = skip | warn | raise for unclassifiable files."""
    folder = Path(folder)
    files = _walk(folder)
    sidecars = [f for f in files if _sidecar_ext(f.name)]
    candidates = [f for f in files if not _sidecar_ext(f.name)]

    groups: dict = {}
    for f in candidates:
        bm = _best_match(f.name)
        if bm is None:
            _handle_unknown(f, "no registry match", policy)
            continue
        label, pat, ext = bm
        if label not in LABELS:
            _handle_unknown(f, f"label {label!r} not in LABELS", policy)
            continue
        info = LABELS[label]
        category = info["category"]
        tokens = f.name[: -len(ext)].lower().split("_")
        key = (category, _group_key(tokens, pat["require"], category))
        groups.setdefault(key, []).append(
            _Match(f, label, category, list(pat["require"]), ext, info)
        )

    products = []
    seen_ids: dict = {}
    for (category, _), members in groups.items():
        item_id = _item_id(members)
        if item_id in seen_ids:
            raise ValueError(f"id collision: {item_id!r} from {seen_ids[item_id]} and {category}")
        seen_ids[item_id] = category

        assets = []
        for m in members:
            asset = Asset(
                path=m.path,
                label=m.label,
                category=m.category,
                kind=m.info["kind"],
                stac_roles=list(m.info["stac_roles"]),
                media_type=m.info["media_type"],
                extensions=list(m.info["extensions"]),
            )
            base = m.path.name[: -len(m.ext)]
            asset.sidecars = [
                sc for sc in sidecars if sc.name[: -len(_sidecar_ext(sc.name))] == base
            ]
            assets.append(asset)

        products.append(Product(id=item_id, category=category, kind=members[0].info["kind"], assets=assets))

    return products


# --- self-check ---

def _make_fixture(tmp: Path) -> None:
    names = [
        "tiles/pielach_2023-02-08_526000_534050.copc.laz",
        "tiles/pielach_2023-02-08_526500_534050.copc.laz",
        "pielach_2023-02-08_DTM_etrs89_cog.tif",
        "pielach_2023-02-08_DTM_masked_etrs89_cog.tif",   # label dtm_masked
        "pielach_2023-02-08_DSM_etrs89_cog.tif",          # label dsm
        "pielach_2023-02-08_transparent_mosaic_cog.tif",  # label orthophoto
        "pielach_2023-02-08_DTM_etrs89_cog.tfw",          # sidecar
        "pielach_2023-02-08_DTM_etrs89_cog.prj",          # sidecar
        "opalsLog.xml",                                   # stray
        "qc_plot.svg",                                    # stray
    ]
    for n in names:
        p = tmp / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def _print(products) -> None:
    print(f"\nproducts ({len(products)}):")
    for p in products:
        print(f"  {p.id}  [{p.category}/{p.kind}]")
        for a in p.assets:
            sc = f"\n\t\tsidecars={[s.name for s in a.sidecars]}" if a.sidecars else ""
            print(f"      - {a.label}: {a.path.name}{sc}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        _print(discover(Path(args[0])))
    else:
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="discover_fix_"))
        try:
            _make_fixture(tmp)
            print(f"fixture: {tmp}")
            _print(discover(tmp, policy="warn"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
