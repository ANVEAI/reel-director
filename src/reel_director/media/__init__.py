"""Media: file probing plus the v4 B-roll engine (free stock, Claude clips, paid generators).

This package replaces the old `media.py` module (which only held media_duration); `from .media import
media_duration` keeps working from here. Submodules:
  base.py      Candidate + Provider interface + Http seam
  license.py   license normalization, commercial-safe policy, attribution and the per-reel credits file
  cache.py     content-addressed media cache on the external drive (LRU size cap, sidecar JSON)
  select.py    ranking (text match + quality + license, optional Claude vision rerank), clip segment pick,
               normalization to the reel (crop/pad, CFR 30, grade match)
  providers/   one module per source; providers.build(settings) makes them
Nothing here imports the network or ffmpeg at package import time.
"""
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def media_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())
