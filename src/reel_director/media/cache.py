"""Content-addressed media cache (contract v4) on the external drive, shared by every provider.

Root: $REEL_DIRECTOR_MEDIA_CACHE (or $RD_MEDIA_CACHE) > /Volumes/Seagate Basic/reel-director/media-cache when the
drive is mounted > ~/.cache/reel-director/media. Layout (the same one youtube_cc writes):

  files/<aa>/<sha256><ext>     the bytes, named by their SHA-256 (two sources of one file share one copy)
  files/<aa>/<sha256>.json     sidecar: candidate metadata (redacted URLs), keys that point here, bytes
  index/<sha256(key)>.json     {"path": "files/..", "sha256"}: key = redacted URL, URL#window, brief hash...
  json/<aa>/<sha256(key)>.json cached API responses {"t", "data"} (Pixabay asks for 24 h caching)
  tmp/                         partial downloads (same filesystem, so the final move is atomic)

LRU: a hit touches the file's mtime; after each put the cache evicts least-recently-used files until it is under
the cap (50 GB on the drive, 5 GB in the fallback), never a file in `keep` (the picks of an open media.json) or
one used in the last hour. Eviction deletes single files only (file + sidecar); an index entry left behind is a
miss next time.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from .base import UA, Http, ProviderError, redact

DRIVE = Path("/Volumes/Seagate Basic")
EXTERNAL = DRIVE / "reel-director" / "media-cache"
FALLBACK = Path.home() / ".cache" / "reel-director" / "media"
CAP = {"external": 50 << 30, "fallback": 5 << 30}
RECENT_S = 3600
EXT_OK = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".heic", ".mp4", ".m4v", ".mov", ".webm",
          ".ogv", ".ogg", ".mkv", ".avi", ".mpg", ".mpeg"}
CTYPE_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
             "image/tiff": ".tif", "video/mp4": ".mp4", "video/webm": ".webm", "video/ogg": ".ogv",
             "application/ogg": ".ogv", "video/quicktime": ".mov", "video/x-matroska": ".mkv"}


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def default_root(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    for k in ("REEL_DIRECTOR_MEDIA_CACHE", "RD_MEDIA_CACHE"):
        if env.get(k):
            return Path(env[k]).expanduser()
    if os.path.ismount(DRIVE) and os.access(DRIVE, os.W_OK):
        return EXTERNAL
    return FALLBACK


def ext_for(url: str, ctype: str = "") -> str:
    """A safe file extension from the URL path or the Content-Type ('.bin' if neither is a known media type)."""
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if ext in EXT_OK:
        return ".jpg" if ext == ".jpeg" else ext
    return CTYPE_EXT.get(ctype.split(";")[0].strip().lower(), ".bin")


class MediaCache:
    def __init__(self, root: Path | str | None = None, cap_bytes: int | None = None):
        self.root = Path(root) if root else default_root()
        self.cap = cap_bytes or CAP["external" if self.root == EXTERNAL else "fallback"]

    # --- paths -------------------------------------------------------------------------------------------
    def _index(self, key: str) -> Path:
        return self.root / "index" / f"{sha256_text(key)}.json"

    def _tmp(self, suffix: str = "") -> Path:
        d = self.root / "tmp"
        d.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=d, suffix=suffix)
        os.close(fd)
        return Path(name)

    # --- objects -------------------------------------------------------------------------------------------
    def lookup(self, key: str) -> Path | None:
        """The cached file for `key`, touched for LRU; None on a miss (or if it was evicted)."""
        ix = self._index(key)
        try:
            rel = json.loads(ix.read_text())["path"]
        except (OSError, ValueError, KeyError):
            return None
        p = self.root / rel
        if not p.is_file():
            return None
        os.utime(p, None)
        return p

    def put(self, src: Path, key: str | None = None, meta: dict | None = None, ext: str | None = None,
            move: bool = True) -> Path:
        """Store `src` under its SHA-256 (moved, or copied when move=False); index it under `key`."""
        src = Path(src)
        sha = sha256_file(src)
        ext = (ext or src.suffix or ".bin").lower()
        rel = Path("files") / sha[:2] / f"{sha}{ext}"
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            if move:
                os.replace(src, dest) if src.parent.stat().st_dev == dest.parent.stat().st_dev else \
                    _copy(src, dest, unlink=True)
            else:
                _copy(src, dest)
        elif move and src.exists():
            src.unlink()
        os.utime(dest, None)
        side = dest.with_suffix(".json")
        old = _read_json(side) or {}
        keys = sorted(set(old.get("keys", [])) | ({key} if key else set()))
        side.write_text(json.dumps({**old, **(meta or {}), "sha256": sha, "bytes": dest.stat().st_size,
                                    "keys": keys}, indent=1, sort_keys=True) + "\n")
        if key:
            ix = self._index(key)
            ix.parent.mkdir(parents=True, exist_ok=True)
            ix.write_text(json.dumps({"path": str(rel), "sha256": sha}, sort_keys=True) + "\n")
        self.evict()
        return dest

    def meta(self, path: Path) -> dict:
        return _read_json(Path(path).with_suffix(".json")) or {}

    def fetch_url(self, url: str, http: Http | None = None, key: str | None = None, meta: dict | None = None,
                  headers: dict | None = None, max_bytes: int = 400 << 20) -> Path:
        """Download once; later calls with the same URL (or key) are cache hits with no network."""
        if url.startswith("file://") or url.startswith("/"):
            local = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path) if url.startswith("file://") else url)
            key = key or f"file:{local}:{local.stat().st_size}:{int(local.stat().st_mtime)}"
            return self.lookup(key) or self.put(local, key, meta, move=False)
        key = key or redact(url)
        if hit := self.lookup(key):
            return hit
        tmp = self._tmp()
        try:
            ctype = (http or Http()).download(url, tmp, headers=headers, max_bytes=max_bytes)
            return self.put(tmp, key, {**(meta or {}), "source_url": redact(url), "content_type": ctype},
                            ext=ext_for(url, ctype))
        finally:
            tmp.unlink(missing_ok=True)

    def fetch_window(self, url: str, segment: tuple[float, float], meta: dict | None = None, ua: str = UA,
                     run=subprocess.run, timeout: float = 600) -> Path:
        """Only the [start, end) seconds of a long (remote or local) video, stream-copied by ffmpeg over HTTP
        range requests, so a 3 s insert from a 15-minute film downloads a few MB, not the whole film."""
        s, e = (round(float(x), 3) for x in segment)
        if not 0 <= s < e:
            raise ProviderError(f"bad segment {segment!r}")
        key = f"window:{redact(url)}#{s:.3f}-{e:.3f}"
        if hit := self.lookup(key):
            return hit
        tmp = self._tmp(".mkv")
        src = urllib.parse.unquote(url[7:]) if url.startswith("file://") else url
        net = ["-user_agent", ua] if src.startswith("http") else []
        base = ["ffmpeg", "-nostdin", "-v", "error", "-y", *net, "-ss", f"{s:.3f}", "-i", src, "-t", f"{e - s:.3f}",
                "-map", "0:v:0", "-an", "-fflags", "+bitexact", "-map_metadata", "-1"]
        try:
            r = run([*base, "-c", "copy", "-f", "matroska", str(tmp)], capture_output=True, text=True, timeout=timeout)
            if r.returncode or tmp.stat().st_size < 1024:
                r = run([*base, "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                         "-f", "matroska", str(tmp)], capture_output=True, text=True, timeout=timeout)
            if r.returncode or tmp.stat().st_size < 1024:
                raise ProviderError(f"ffmpeg window fetch failed for {redact(url)}: {(r.stderr or '')[-300:]}")
            return self.put(tmp, key, {**(meta or {}), "source_url": redact(url), "segment": [s, e]}, ext=".mkv")
        finally:
            tmp.unlink(missing_ok=True)

    # --- API response cache --------------------------------------------------------------------------------
    def json_get(self, key: str, ttl: float = 86400) -> Any:
        h = sha256_text(key)
        d = _read_json(self.root / "json" / h[:2] / f"{h}.json")
        if d is None or (ttl and time.time() - float(d.get("t", 0)) > ttl):
            return None
        return d.get("data")

    def json_put(self, key: str, data: Any) -> None:
        h = sha256_text(key)
        p = self.root / "json" / h[:2] / f"{h}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"t": time.time(), "key": redact(key), "data": data}, sort_keys=True))
        os.replace(tmp, p)

    # --- LRU -----------------------------------------------------------------------------------------------
    def _files(self) -> list[Path]:
        d = self.root / "files"
        return [p for p in d.glob("*/*") if p.is_file() and p.suffix != ".json"] if d.is_dir() else []

    def usage(self) -> int:
        return sum(p.stat().st_size for p in self._files())

    def evict(self, cap: int | None = None, keep: Iterable[str] = ()) -> list[str]:
        """Delete least-recently-used files until usage <= cap. `keep`: SHA-256s that must stay."""
        cap = self.cap if cap is None else cap
        files = [(p.stat().st_mtime, p.stat().st_size, p) for p in self._files()]
        total = sum(s for _, s, _ in files)
        if total <= cap:
            return []
        keep, now, gone = set(keep), time.time(), []
        for mtime, size, p in sorted(files, key=lambda x: (x[0], x[2].name)):
            if total <= cap:
                break
            if p.stem in keep or now - mtime < RECENT_S:
                continue
            p.unlink(missing_ok=True)
            p.with_suffix(".json").unlink(missing_ok=True)
            total -= size
            gone.append(p.stem)
        return gone


def _copy(src: Path, dest: Path, unlink: bool = False) -> None:
    import shutil
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    if unlink:
        src.unlink(missing_ok=True)


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None
