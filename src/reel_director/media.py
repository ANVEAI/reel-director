"""Media file probing."""
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def media_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())
