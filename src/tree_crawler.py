"""
Efficiently crawls a directory tree and produces a summarized overview.

Designed for very large directory hierarchies (millions of files) where a
full listing is impractical. Directories exceeding a configurable file-count
threshold are summarized by extension distribution instead of listing every
file individually.

Usage:
    python tree_crawler.py P:\\DATA\\PIELACH
    python tree_crawler.py ./data --format json --output tree.json
    python tree_crawler.py ./data --threshold 50 --max-depth 3 -v

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
    "threshold": 100,
    "max_depth": None,
    "format": "text",
    "no_size": False,
    "verbose": False,
    "max_listed": 20,
}


@dataclass
class DirNode:
    """One directory in the crawl tree."""
    name: str
    path: str
    total_size: int
    file_count: int
    ext_distribution: dict[str, int]
    children: list[DirNode] = field(default_factory=list)
    summarized: bool = False
    files: list[str] | None = None


def crawl_directory(
    root: Path,
    *,
    threshold: int = DEFAULTS["threshold"],
    max_depth: int | None = DEFAULTS["max_depth"],
    collect_size: bool = True,
    verbose: bool = False,
) -> DirNode:
    """Crawl root and return a DirNode tree.

    Directories with >= threshold files are summarized (extension
    distribution only, no individual filenames).
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
        verbose=verbose,
    )


def _crawl_one(
    dir_path: Path,
    *,
    threshold: int,
    max_depth: int | None,
    current_depth: int,
    collect_size: bool,
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
                        suffix = Path(entry.name).suffix.lower() or "(no ext)"
                        ext_dist[suffix] = ext_dist.get(suffix, 0) + 1
                        if file_count <= threshold:
                            filenames.append(entry.name)
                except OSError:
                    pass
    except PermissionError:
        return DirNode(
            name=dir_path.name + " [ACCESS DENIED]",
            path=str(dir_path),
            total_size=0,
            file_count=0,
            ext_distribution={},
        )
    except OSError as e:
        return DirNode(
            name=dir_path.name + f" [ERROR: {e.strerror}]",
            path=str(dir_path),
            total_size=0,
            file_count=0,
            ext_distribution={},
        )

    summarized = file_count >= threshold
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
                verbose=verbose,
            ))

    return DirNode(
        name=dir_path.name,
        path=str(dir_path),
        total_size=total_size,
        file_count=file_count,
        ext_distribution=ext_dist,
        children=children,
        summarized=summarized,
        files=filenames,
    )


# ---- Output: Text ----

def render_text(node: DirNode, *, show_size: bool = True, max_listed: int = DEFAULTS["max_listed"]) -> str:
    lines: list[str] = []
    size_str = f" ({_human_size(node.total_size)})" if show_size else ""
    lines.append(f"{node.name}\\{size_str}")
    _render_children(node, lines, prefix="", show_size=show_size, max_listed=max_listed)
    return "\n".join(lines)


def _render_children(
    node: DirNode,
    lines: list[str],
    prefix: str,
    show_size: bool,
    max_listed: int,
) -> None:
    items: list[tuple[str, object]] = []

    if node.file_count > 0:
        items.append(("files", node))

    for child in node.children:
        items.append(("dir", child))

    for i, (kind, obj) in enumerate(items):
        is_last = (i == len(items) - 1)
        connector = "\\-- " if is_last else "+-- "
        extension = "    " if is_last else "|   "

        if kind == "dir":
            child_node: DirNode = obj
            size_str = f" ({_human_size(child_node.total_size)})" if show_size else ""
            lines.append(f"{prefix}{connector}{child_node.name}\\{size_str}")
            _render_children(child_node, lines, prefix + extension, show_size, max_listed)
        elif kind == "files":
            file_node: DirNode = obj
            dist_str = _format_ext_dist(file_node.ext_distribution, file_node.file_count)
            if file_node.summarized:
                lines.append(f"{prefix}{connector}[{file_node.file_count} files: {dist_str}]")
            else:
                lines.append(f"{prefix}{connector}[{file_node.file_count} files: {dist_str}]")
                file_prefix = prefix + extension
                listed = file_node.files[:max_listed] if file_node.files else []
                for fi, fname in enumerate(listed):
                    is_last_file = (fi == len(listed) - 1) and (len(file_node.files) <= max_listed)
                    fc = "\\-- " if is_last_file else "+-- "
                    lines.append(f"{file_prefix}{fc}{fname}")
                remaining = file_node.file_count - len(listed)
                if remaining > 0:
                    lines.append(f"{file_prefix}\\-- ... ({remaining} more)")


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


def _format_ext_dist(ext_dist: dict[str, int], total: int) -> str:
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
    d = {
        "name": node.name,
        "path": node.path,
        "total_size": node.total_size,
        "file_count": node.file_count,
        "ext_distribution": node.ext_distribution,
        "summarized": node.summarized,
    }
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
            Output is read-only — the input directory is never modified.
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
    parser.add_argument("--no-size", action="store_true",
                        help="Skip file size collection (faster)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print progress to stderr")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    tree = crawl_directory(
        args.directory,
        threshold=args.threshold,
        max_depth=args.max_depth,
        collect_size=not args.no_size,
        verbose=args.verbose,
    )

    if args.format == "json":
        output = to_json(tree)
    else:
        output = render_text(tree, show_size=not args.no_size)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Output written to: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
