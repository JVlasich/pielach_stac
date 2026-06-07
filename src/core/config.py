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
            print(f"Warning: unknown config section '{ns}' in {path}", file=sys.stderr)
            continue
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


def generate_template_config(namespace: str, path: Path) -> None:
    """Write a commented YAML template for the commons + given namespace."""
    if namespace not in _defaults:
        raise KeyError(f"Namespace '{namespace}' not registered")

    lines = [
        "# Configuration template. All values shown are defaults.",
        "# Uncomment and modify as needed. CLI args override values set here.",
        "",
    ]
    for ns in (COMMONS, namespace):
        lines.append(f"{ns}:")
        for key, value in _defaults[ns].items():
            lines.append(f"  # {key}: {_repr_yaml(value)}")
        lines.append("")

    Path(path).write_text("\n".join(lines), encoding="utf-8")
    print(f"Template config written to: {path}")


def _repr_yaml(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
