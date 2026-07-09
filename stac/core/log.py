"""Project-wide logging.

Entrypoints call setup() once; every module gets its own logger via
logging.getLogger(__name__) and just logs — no handlers, no levels.
"""

import logging
import sys


def setup(verbose: bool = False) -> None:
    """Configure the root logger for console output (stderr)."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


if __name__ == "__main__":
    setup(verbose="-v" in sys.argv)
    log = logging.getLogger("stac.core.log")
    log.debug("debug message (only with -v)")
    log.info("info message")
    log.warning("warning message")
    log.error("error message")
    print("log self-check ok")
