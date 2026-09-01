"""Optional-dependency probes, cached per run."""

import functools


@functools.lru_cache(maxsize=1)  # probed once per run
def laspy_available() -> bool:
    """True when laspy + lazrs import here (both vendored in libs/: linux cp310 .so and
    win_amd64 .pyd). Gates every laspy-backed step, COPC footprints and thumbnails alike."""
    try:
        import laspy  # noqa: F401
        import lazrs  # noqa: F401
        return True
    except Exception:
        return False
