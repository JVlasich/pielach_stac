"""Project-wide logging.

Entrypoints call setup() once; every module gets its own logger via
logging.getLogger(__name__) and just logs — no handlers, no levels.
"""

import logging
import sys

_ORANGE = "\033[38;5;208m"
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    """Colors warning lines orange, everything else untouched."""

    def format(self, record):
        s = super().format(record)
        if record.levelno == logging.WARNING:
            return f"{_ORANGE}{s}{_RESET}"
        return s


def setup(verbose: bool = False) -> None:
    """Configure the root logger for console output (stderr)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_ColorFormatter(
        "%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=[handler],
    )


if __name__ == "__main__":
    setup(verbose="-v" in sys.argv)
    log = logging.getLogger("stac.core.log")
    log.debug("debug message (only with -v)")
    log.info("info message")
    log.warning("warning message")
    log.error("error message")
    print("log self-check ok")
