"""Asset discovery and matching.

Walk a campaign's product folder, classify files against the registry, emit one Product
(= one future Item) per file, resolve cloud-native twins (D11), mark tile groups (D10),
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
    cloud_native: bool # False -> fallback catalog entry (D11); build flags pielach:cloud_native
    sidecars: list = field(default_factory=list)  # Paths matched by full basename


@dataclass
class Product:
    id: str            # one future Item
    category: str
    kind: str
    assets: list[Asset]       # always length 1 today; kept a list for the Item builder
    group: str | None = None  # tile-group name -> subcollection; None -> flat in the campaign


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


def _resolve_twins(matches: list, policy: str) -> list:
    """Cloud-native twin supersedes its non-cloud-native sibling silently; lone
    non-cloud-native files go through the non_cloud_native policy (D11):
    warn = catalog + stderr warning | skip = drop (old cloud-native-only rule) | raise."""
    buckets: dict = {}
    for m in matches:
        buckets.setdefault(_twin_key(m), []).append(m)
    kept = []
    for members in buckets.values():
        cn = [m for m in members if m.info["cloud_native"]]
        if cn:
            kept.extend(cn)
            continue
        for m in members:
            if policy == "raise":
                raise ValueError(f"non-cloud-native asset: {m.path.name}")
            if policy == "warn":
                print(f"WARN non-cloud-native ({m.label}): {m.path.name}", file=sys.stderr)
                kept.append(m)
            # skip: drop silently
    return kept


def _assign_tile_groups(products: list, root: Path) -> None:
    """Tiled = more than one product of a category sharing a subdir below the campaign
    root (tac_pcl writes all tiles of one cloud into one dir, D9/D10). The subdir names
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


def discover(folder, policy: str = "warn", stem_patterns=None, labels=None,
             non_cloud_native: str = "warn") -> list:
    """Discover Products under a campaign folder. One file = one Product (one future Item);
    tile groups share a .group -> subcollection, everything else is flat in the campaign (D10).
    policy = skip | warn | raise for unclassifiable files;
    non_cloud_native = warn | skip | raise for files without a cloud-native twin (D11).
    stem_patterns/labels default to the module registry; pass merge_overrides() output to apply
    per-campaign overrides."""
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
            _handle_unknown(f, "no registry match", policy)
            continue
        label, pat, ext = bm
        if label not in lb:
            _handle_unknown(f, f"label {label!r} not in LABELS", policy)
            continue
        info = lb[label]
        matches.append(_Match(f, label, info["category"], ext, info))

    matches = _resolve_twins(matches, non_cloud_native)

    products = []
    seen_ids: dict = {}
    for m in sorted(matches, key=lambda m: m.path.name):
        item_id = _item_id(m.path.name, m.ext)
        if item_id in seen_ids:
            raise ValueError(f"id collision: {item_id!r} from {seen_ids[item_id]} and {m.path.name}")
        seen_ids[item_id] = m.path.name

        asset = Asset(
            path=m.path,
            label=m.label,
            category=m.category,
            kind=m.info["kind"],
            stac_roles=list(m.info["stac_roles"]),
            media_type=m.info["media_type"],
            extensions=list(m.info["extensions"]),
            cloud_native=m.info["cloud_native"],
        )
        base = m.path.name[: -len(m.ext)]
        asset.sidecars = [
            sc for sc in sidecars if sc.name[: -len(_sidecar_ext(sc.name))] == base
        ]
        products.append(Product(id=item_id, category=m.category, kind=m.info["kind"], assets=[asset]))

    _assign_tile_groups(products, folder)
    return products


def _print(products) -> None:
    print(f"\nproducts ({len(products)}):")
    for p in products:
        grp = f"  group={p.group}" if p.group else ""
        print(f"  {p.id}  [{p.category}/{p.kind}]{grp}")
        for a in p.assets:
            cn = "" if a.cloud_native else "  (non-cloud-native)"
            sc = f"\n\t\tsidecars={[s.name for s in a.sidecars]}" if a.sidecars else ""
            print(f"      - {a.label}: {a.path.name}{cn}{sc}")


def _make_fixture(tmp: Path) -> None:
    names = [
        "tiles/pielach_2023-02-08_526000_534050.copc.laz",  # tile group "tiles"
        "tiles/pielach_2023-02-08_526500_534050.copc.laz",
        "pielach_2023-02-08_DTM_etrs89_cog.tif",          # label dtm_cog
        "pielach_2023-02-08_DTM_etrs89.tif",              # non-CN twin -> superseded
        "pielach_2023-02-08_DTM_masked_etrs89_cog.tif",   # variant -> own item
        "pielach_2023-02-08_DSM_etrs89.tif",              # lone non-CN -> cataloged + warned
        "pielach_2023-02-08_ground.laz",                  # lone non-CN pointcloud, flat
        "pielach_2023-02-08_transparent_mosaic_cog.tif",  # label orthophoto_cog, flat
        "pielach_2023-02-08_DTM_etrs89_cog.tfw",          # sidecar
        "pielach_2023-02-08_DTM_etrs89_cog.prj",          # sidecar
        "campaign.yaml",                                  # per-campaign sidecar, never an asset
        "opalsLog.xml",                                   # stray
    ]
    for n in names:
        p = tmp / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


# --- self-check ---
if __name__ == "__main__":


    args = sys.argv[1:]
    if args:
        _print(discover(Path(args[0])))
    else:
        import contextlib
        import io
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="discover_fix_"))
        try:
            _make_fixture(tmp)
            print(f"fixture: {tmp}")
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                products = discover(tmp, policy="warn")
            err = buf.getvalue()
            print(err, file=sys.stderr, end="")
            _print(products)

            by_id = {p.id: p for p in products}
            assert len(products) == 7, sorted(by_id)
            assert all(len(p.assets) == 1 for p in products)

            # variants ungrouped: DTM and DTM_masked are separate items
            assert "pielach_2023-02-08_DTM_etrs89" in by_id
            assert "pielach_2023-02-08_DTM_masked_etrs89" in by_id

            # cog twin superseded the plain DTM: id keeps no cog token, asset is the COG
            dtm = by_id["pielach_2023-02-08_DTM_etrs89"].assets[0]
            assert dtm.path.name.endswith("_cog.tif") and dtm.cloud_native
            assert len(dtm.sidecars) == 2

            # lone non-CN cataloged with warning; sidecar yaml never warned, strays still are
            assert not by_id["pielach_2023-02-08_DSM_etrs89"].assets[0].cloud_native
            assert "pielach_2023-02-08_DSM_etrs89.tif" in err and "ground.laz" in err
            assert "campaign.yaml" not in err and "opalsLog.xml" in err

            # tiles share a group, everything else is flat
            tiled = [p for p in products if p.group]
            assert len(tiled) == 2 and {p.group for p in tiled} == {"tiles"}

            # skip policy = old cloud-native-only rule
            skipped = discover(tmp, policy="skip", non_cloud_native="skip")
            assert len(skipped) == 5
            assert all(a.cloud_native for p in skipped for a in p.assets)

            print("\ndiscover self-check ok")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
