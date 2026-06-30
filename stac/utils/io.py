from pathlib import Path
import shutil
from typing import List

def clean_dir(directory: str, keep: List[str]):
    """Delete everything in [directory] except items whose names are in [keep]."""
    keep = set(keep) # type: ignore
    for item in Path(directory).iterdir():
        if item.name in keep:
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()