"""Library: the creator's own media folder, searched first (own footage beats stock).

Folder: $REEL_DIRECTOR_MEDIA_LIBRARY > settings media.library > /Volumes/Seagate Basic/reel-director/library (when
it exists). Not available until one of them names an existing folder. Matching is by words in the file's path
(folder names act as tags: library/office/laptop-typing.mp4) plus an optional sidecar next to the file:
  <file>.json  {"title", "tags": [...], "license", "creator", "source_page"}   (license defaults to "own")
  <file>.txt   free words / tags
Only matching files are probed (ffprobe: size, duration). fetch() copies the file (or the window of a long
video) into the content-addressed cache, so a media.json pins exact bytes even if the folder changes later.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import license as L
from ..base import Candidate, Provider, setting
from ..cache import DRIVE

DEFAULT = DRIVE / "reel-director" / "library"
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff", ".gif"}
VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def ffprobe(path: Path) -> tuple[int, int, float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        return int(s.get("width") or 0), int(s.get("height") or 0), float((d.get("format") or {}).get("duration") or 0)
    except (ValueError, TypeError):
        return 0, 0, 0.0


class Library(Provider):
    name = "library"
    label = "Your library"
    kinds = ("image", "video")

    def __init__(self, *, root: Path | str | None = None, probe=ffprobe, **kw):
        super().__init__(**kw)
        self.root = Path(root).expanduser() if root else None
        self.probe = probe

    @classmethod
    def from_settings(cls, settings=None, env=None, **kw):
        root = kw.pop("root", None) or setting(settings, "library", ("REEL_DIRECTOR_MEDIA_LIBRARY",), env)
        if not root and DEFAULT.is_dir():
            root = DEFAULT
        return cls(root=root, settings=settings, **kw)

    @property
    def available(self) -> bool:
        return bool(self.root and self.root.is_dir())

    def status(self) -> dict:
        return {**super().status(), "root": str(self.root) if self.root else None,
                "setup": None if self.available else f"create {DEFAULT} or set media.library / "
                                                      "REEL_DIRECTOR_MEDIA_LIBRARY to your media folder"}

    def files(self, kind: str) -> list[Path]:
        exts = VIDEO if kind == "video" else IMAGE
        return sorted(p for p in self.root.rglob("*") if p.suffix.lower() in exts and p.is_file()
                      and not any(part.startswith(".") for part in p.relative_to(self.root).parts))

    @staticmethod
    def sidecar_of(p: Path) -> dict:
        for side in (p.with_name(p.name + ".json"), p.with_suffix(".json")):
            if side.is_file():
                try:
                    return json.loads(side.read_text())
                except ValueError:
                    return {}
        txt = p.with_suffix(".txt")
        return {"tags": txt.read_text(errors="replace").split()} if txt.is_file() else {}

    def search(self, query, kind="image", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        from ..select import tokens
        if not self.available or kind not in self.kinds:
            return []
        q = set(tokens(query))
        hits = []
        for p in self.files(kind):
            side = self.sidecar_of(p)
            rel = p.relative_to(self.root)
            words = set(tokens(" ".join([*rel.parts[:-1], p.stem, side.get("title", ""), *side.get("tags", [])])))
            if n := len(q & words):
                hits.append((-n, str(rel), p, side))
        out = []
        for _, rel, p, side in sorted(hits)[: max(1, int(limit))]:
            w, h, dur = self.probe(p)
            if kind == "video" and dur and dur < duration[0]:
                continue
            lic = L.normalize(side.get("license") or "own")
            if not lic.allowed:
                continue
            title = side.get("title") or p.stem.replace("-", " ").replace("_", " ")
            creator, page = side.get("creator", ""), side.get("source_page", "")
            out.append(Candidate(
                id=f"library:{rel}", provider=self.name, kind=kind, title=title, url=p.as_uri(),
                thumb=p.as_uri() if kind == "image" else "", w=w, h=h, duration=dur if kind == "video" else 0.0,
                license=lic.id, attribution=L.attribution(title, creator, page, lic), source_page=page,
                creator=creator, tags=tuple(side.get("tags", [])), extra={"path": str(p)}))
        return out


def provider(settings=None, **kw) -> Library:
    return Library.from_settings(settings, **kw)
