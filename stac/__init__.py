import sys
from pathlib import Path

# Vendored deps (libs\ at repo root) take precedence over any installed
# copies so the shipped versions run everywhere. To upgrade a dep, refresh libs\.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "libs"))
