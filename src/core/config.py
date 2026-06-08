import re
import sys
import yaml
from pathlib import Path

COMMONS = "commons"

_defaults = {}  # namespace: dict
_file = {}      # namespace: dict
_cli = {}       # namespace: dict

_defaults[COMMONS] = {
    "nbThreads": 1,
    "distribute": 1,
    "tmp_path": "./tmp",
    "fileLogLevel": "error",    # error | info | warning
    "screenLogLevel": "error",
    "keeptmp": False,
}


def register_defaults(namespace: str, defaults: dict) -> None:
    _defaults[namespace] = dict(defaults)


def load_config(path: Path) -> None:
    """Load namespaced YAML config into the file layer. Warns on unknown sections/keys."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"Config {path} must be a YAML mapping, not {type(data).__name__}")

    for ns, values in data.items():
        if ns not in _defaults:
            continue  # sibling tool's section in a shared config, ignore quietly
        if values is None:
            continue  # section present but empty (all keys commented) = no overrides
        if not isinstance(values, dict):
            raise TypeError(f"Section '{ns}' in {path} must be a mapping, not {type(values).__name__}")
        for key in values:
            if key not in _defaults[ns]:
                print(f"Warning: unknown key '{ns}.{key}' in {path}", file=sys.stderr)
        _file.setdefault(ns, {}).update(values)


def merge_cli(namespace: str, cli_args) -> None:
    """Route non-None CLI args into the cli layer. Commons keys go to the commons namespace."""
    if namespace not in _defaults:
        raise KeyError(f"unregistered namespace {namespace!r}")
    commons_keys = set(_defaults[COMMONS])
    for key, value in vars(cli_args).items():
        if key in ("config", "init") or value is None:
            continue
        target = COMMONS if key in commons_keys else namespace
        _cli.setdefault(target, {})[key] = value


def section(namespace: str) -> dict:
    """Resolve a namespace: defaults < file < cli."""
    if namespace not in _defaults:
        raise KeyError(f"unregistered namespace {namespace!r}")
    merged = {}
    merged.update(_defaults.get(namespace, {}))
    merged.update(_file.get(namespace, {}))
    merged.update(_cli.get(namespace, {}))
    return merged


_HEADER_RE = re.compile(r"^[A-Za-z_]\w*:\s*$")  # a top-level "section:" line


def _section_body(ns: str) -> list:
    """The commented key lines for one section (no header, no trailing blank)."""
    return [f"  # {key}: {_repr_yaml(value)}" for key, value in _defaults[ns].items()]


def _rstrip_blanks(lines: list) -> list:
    while lines and lines[-1].strip() == "":
        lines.pop()
    return lines


def _parse_template(text: str) -> tuple:
    """Split a template into (preamble, sections). sections is an ordered name->body dict,
    body being the lines under a 'name:' header. Indented/comment lines never start a section."""
    preamble = []
    sections = {}
    current = None
    for line in text.splitlines():
        if _HEADER_RE.match(line):
            current = line.split(":", 1)[0]
            sections[current] = []
        elif current is None:
            preamble.append(line)
        else:
            sections[current].append(line)
    return preamble, sections


def generate_template_config(namespace: str, path: Path) -> None:
    """Append/refresh a commented YAML template. Refreshes commons + the given namespace,
    preserves any sibling sections, so one file can be built up across modules."""
    if namespace not in _defaults:
        raise KeyError(f"Namespace '{namespace}' not registered")

    path = Path(path)
    if path.exists():
        preamble, sections = _parse_template(path.read_text(encoding="utf-8"))
    else:
        preamble = [
            "# Configuration template. All values shown are defaults.",
            "# Uncomment and modify as needed. CLI args override values set here.",
        ]
        sections = {}

    for ns in (COMMONS, namespace):
        sections[ns] = _section_body(ns)  # refresh existing or append new

    out = _rstrip_blanks(list(preamble))
    if out:
        out.append("")
    for name, body in sections.items():
        out.append(f"{name}:")
        out.extend(_rstrip_blanks(list(body)))
        out.append("")

    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Template config written to: {path}")


def _repr_yaml(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
