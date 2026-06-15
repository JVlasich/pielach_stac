"""
Efficiently crawls a directory tree and produces a summarized overview.

Designed for very large directory hierarchies (millions of files) where a
full listing is impractical. Directories exceeding a configurable file-count
threshold are summarized by extension distribution instead of listing every
file individually.

Size collection, file counting and extension mapping are each optional. With
all three disabled (--plain) the tool acts as a faster, JSON-capable drop-in
for Windows' "tree /f /a": every file listed, no stats, no stat() calls.

Usage:
    python tree_crawler.py P:\\DATA\\PIELACH
    python tree_crawler.py ./data --format json --output tree.json
    python tree_crawler.py ./data --threshold 50 --max-depth 3 -v
    python tree_crawler.py ./data --plain          # tree /f /a equivalent

As a library:
    from tree_crawler import crawl_directory, render_text, to_json
    tree = crawl_directory(Path("P:/data"), threshold=100)
    print(render_text(tree))
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

DEFAULTS = {
    "threshold": 1e9,
    "max_depth": None,
    "format": "text",
    "no_size": False,
    "no_count": False,
    "no_ext": False,
    "plain": False,
    "verbose": False,
    "max_listed": 20,
}


@dataclass
class DirNode:
    """One directory in the crawl tree.

    total_size, file_count and ext_distribution are None when their
    collection was disabled.
    """
    name: str
    path: str
    children: list[DirNode] = field(default_factory=list)
    total_size: int | None = None
    file_count: int | None = None
    ext_distribution: dict[str, int] | None = None
    summarized: bool = False
    files: list[str] | None = None


def crawl_directory(
    root: Path,
    *,
    threshold: int = DEFAULTS["threshold"],
    max_depth: int | None = DEFAULTS["max_depth"],
    collect_size: bool = True,
    count_files: bool = True,
    map_ext: bool = True,
    verbose: bool = False,
) -> DirNode:
    """Crawl root and return a DirNode tree.

    Directories with >= threshold files are summarized (extension
    distribution only, no individual filenames). Summarization requires
    count_files; with counting disabled every file is listed.
    """
    root = root.resolve()
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    return _crawl_one(
        root,
        threshold=threshold,
        max_depth=max_depth,
        current_depth=0,
        collect_size=collect_size,
        count_files=count_files,
        map_ext=map_ext,
        verbose=verbose,
    )


def _crawl_one(
    dir_path: Path,
    *,
    threshold: int,
    max_depth: int | None,
    current_depth: int,
    collect_size: bool,
    count_files: bool,
    map_ext: bool,
    verbose: bool,
) -> DirNode:
    if verbose:
        print(f"  scanning: {dir_path}", file=sys.stderr)

    file_count = 0
    total_size = 0
    ext_dist: dict[str, int] = {}
    filenames: list[str] = []
    subdirs: list[Path] = []

    try:
        with os.scandir(dir_path) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        file_count += 1
                        if collect_size:
                            try:
                                total_size += entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                pass
                        if map_ext:
                            suffix = Path(entry.name).suffix.lower() or "(no ext)"
                            ext_dist[suffix] = ext_dist.get(suffix, 0) + 1
                        filenames.append(entry.name)
                except OSError:
                    pass
    except PermissionError:
        return DirNode(
            name=dir_path.name + " [ACCESS DENIED]",
            path=str(dir_path),
        )
    except OSError as e:
        return DirNode(
            name=dir_path.name + f" [ERROR: {e.strerror}]",
            path=str(dir_path),
        )

    summarized = count_files and file_count >= threshold
    if summarized:
        filenames = None
    else:
        filenames.sort(key=str.lower)

    children = []
    if max_depth is None or current_depth < max_depth:
        subdirs.sort(key=lambda p: p.name.lower())
        for sd in subdirs:
            children.append(_crawl_one(
                sd,
                threshold=threshold,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                collect_size=collect_size,
                count_files=count_files,
                map_ext=map_ext,
                verbose=verbose,
            ))

    return DirNode(
        name=dir_path.name,
        path=str(dir_path),
        children=children,
        total_size=total_size if collect_size else None,
        file_count=file_count if count_files else None,
        ext_distribution=ext_dist if map_ext else None,
        summarized=summarized,
        files=filenames,
    )


# ---- Output: Text ----

def render_text(node: DirNode, *, max_listed: int = DEFAULTS["max_listed"]) -> str:
    lines: list[str] = []
    lines.append(f"{node.name}\\{_size_suffix(node)}")
    _render_children(node, lines, prefix="", max_listed=max_listed)
    return "\n".join(lines)


def _render_children(
    node: DirNode,
    lines: list[str],
    prefix: str,
    max_listed: int,
) -> None:
    # items: ("filegroup", node), ("file", name) or ("dir", node). With a
    # header the files nest under it; without one (plain mode) each file is a
    # sibling of the subdirs so connectors stay correct.
    items: list[tuple[str, object]] = []

    if _has_files(node):
        header = _files_header(node)
        if header is not None:
            items.append(("filegroup", node))
        else:
            for name in _listed_files(node, max_listed):
                items.append(("file", name))

    for child in node.children:
        items.append(("dir", child))

    for i, (kind, obj) in enumerate(items):
        is_last = (i == len(items) - 1)
        connector = "\\-- " if is_last else "+-- "
        extension = "    " if is_last else "|   "

        if kind == "dir":
            child_node: DirNode = obj
            lines.append(f"{prefix}{connector}{child_node.name}\\{_size_suffix(child_node)}")
            _render_children(child_node, lines, prefix + extension, max_listed)
        elif kind == "filegroup":
            file_node: DirNode = obj
            lines.append(f"{prefix}{connector}{_files_header(file_node)}")
            if not file_node.summarized:
                _render_file_list(file_node, lines, prefix + extension, max_listed)
        elif kind == "file":
            lines.append(f"{prefix}{connector}{obj}")


def _listed_files(node: DirNode, max_listed: int) -> list[str]:
    files = node.files or []
    listed = files if max_listed <= 0 else files[:max_listed]
    remaining = len(files) - len(listed)
    if remaining > 0:
        return listed + [f"... ({remaining} more)"]
    return listed


def _render_file_list(
    node: DirNode,
    lines: list[str],
    prefix: str,
    max_listed: int,
) -> None:
    listed = _listed_files(node, max_listed)
    for fi, fname in enumerate(listed):
        fc = "\\-- " if fi == len(listed) - 1 else "+-- "
        lines.append(f"{prefix}{fc}{fname}")


def _has_files(node: DirNode) -> bool:
    return bool(node.files) or (node.file_count or 0) > 0


def _size_suffix(node: DirNode) -> str:
    if node.total_size is None:
        return ""
    return f" ({_human_size(node.total_size)})"


def _files_header(node: DirNode) -> str | None:
    """Bracketed summary line for a directory's files, or None when neither
    count nor extension mapping is collected (plain listing)."""
    count = node.file_count
    dist = _format_ext_dist(node.ext_distribution) if node.ext_distribution else ""
    if count is not None and dist:
        return f"[{count} files: {dist}]"
    if count is not None:
        return f"[{count} files]"
    if dist:
        return f"[{dist}]"
    return None


def _human_size(nbytes: int) -> str:
    if nbytes == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            if unit == "B":
                return f"{nbytes} B"
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def _format_ext_dist(ext_dist: dict[str, int]) -> str:
    total = sum(ext_dist.values())
    if total == 0:
        return ""
    sorted_exts = sorted(ext_dist.items(), key=lambda x: x[1], reverse=True)
    parts = []
    for ext, count in sorted_exts:
        pct = count * 100 / total
        if pct >= 1:
            parts.append(f"*{ext} {pct:.0f}%")
        else:
            parts.append(f"*{ext} <1%")
    return ", ".join(parts)


# ---- Output: JSON ----

def to_dict(node: DirNode) -> dict:
    d: dict = {
        "name": node.name,
        "path": node.path,
    }
    if node.total_size is not None:
        d["total_size"] = node.total_size
    if node.file_count is not None:
        d["file_count"] = node.file_count
        d["summarized"] = node.summarized
    if node.ext_distribution is not None:
        d["ext_distribution"] = node.ext_distribution
    if node.files is not None:
        d["files"] = node.files
    if node.children:
        d["children"] = [to_dict(c) for c in node.children]
    return d


def to_json(node: DirNode, **kwargs) -> str:
    kwargs.setdefault("indent", 2)
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(to_dict(node), **kwargs)


# ---- CLI ----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl a directory tree and produce a summarized overview.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Directories with many files are summarized by extension distribution.
            --plain disables size, count and extension mapping for a fast
            tree /f /a style full listing. Output is read-only.
        """)
    )

    parser.add_argument("directory", type=Path,
                        help="Root directory to crawl")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output file path (default: stdout)")
    parser.add_argument("-f", "--format", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    parser.add_argument("-t", "--threshold", type=int, default=DEFAULTS["threshold"],
                        help=f"Summarize dirs with >= N files (default: {DEFAULTS['threshold']})")
    parser.add_argument("-d", "--max-depth", type=int, default=None,
                        help="Maximum recursion depth (default: unlimited)")
    parser.add_argument("-m", "--max-listed", type=int, default=DEFAULTS["max_listed"],
                        help=f"Max files listed per dir, 0 = unlimited (default: {DEFAULTS['max_listed']})")
    parser.add_argument("--no-size", action="store_true",
                        help="Skip file size collection (faster, no stat calls)")
    parser.add_argument("--no-count", action="store_true",
                        help="Skip file counting and threshold summarization")
    parser.add_argument("--no-ext", action="store_true",
                        help="Skip extension distribution mapping")
    parser.add_argument("--plain", action="store_true",
                        help="tree /f /a drop-in: implies --no-size --no-count --no-ext, lists all files")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print progress to stderr")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    no_size = args.no_size or args.plain
    no_count = args.no_count or args.plain
    no_ext = args.no_ext or args.plain
    max_listed = 0 if args.plain else args.max_listed

    tree = crawl_directory(
        args.directory,
        threshold=args.threshold,
        max_depth=args.max_depth,
        collect_size=not no_size,
        count_files=not no_count,
        map_ext=not no_ext,
        verbose=args.verbose,
    )

    if args.format == "json":
        output = to_json(tree)
    else:
        output = render_text(tree, max_listed=max_listed)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Output written to: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
