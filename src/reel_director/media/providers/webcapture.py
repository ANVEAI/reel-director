"""Web capture: screenshots of a user-supplied URL via `hyperframes capture` (no key, no cost).

Only answers queries that are a public http(s) URL (the creator's product page, a tweet, a dashboard), as images:
the viewport screenshots down the page (screenshots/scroll-000.png ... scroll-100.png) and the full-page plate
(screenshots/full-page.png). They are desktop-width, so treatments put them in a browser/laptop mockup or pan the
plate. Captures are cached per URL under <cache>/captures/<sha256(url)[:16]>/ and reused (deterministic) until
search(..., refresh=True). License "user-capture": the creator confirms they may show the page (Studio says so).
Runs headless Chrome with --skip-vision (no AI captioning) and --skip-assets (no asset downloads).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path

from .. import license as L
from ..base import Candidate, Provider, ProviderError
from ..cache import sha256_text
from .library import ffprobe

URL = re.compile(r"^https?://[^\s/?#]+\.[^\s/?#]+[^\s]*$")


class WebCapture(Provider):
    name = "webcapture"
    label = "Web capture"
    kinds = ("image",)

    def __init__(self, *, run=subprocess.run, probe=ffprobe, max_shots: int = 8, timeout_ms: int = 60000, **kw):
        super().__init__(**kw)
        self.run, self.probe, self.max_shots, self.timeout_ms = run, probe, max_shots, timeout_ms
        self.exe = shutil.which("hyperframes")

    @property
    def available(self) -> bool:
        return bool(self.exe)

    def status(self) -> dict:
        return {**super().status(), "setup": None if self.exe else "install the HyperFrames CLI (hyperframes)"}

    @staticmethod
    def shots(out: Path) -> list[Path]:
        d = out / "screenshots"
        if not d.is_dir():
            return []
        scroll = sorted(d.glob("scroll-*.png"))
        return scroll + [p for p in (d / "full-page.png",) if p.is_file()]

    def capture(self, url: str, refresh: bool = False) -> Path:
        out = self.cache.root / "captures" / sha256_text(url)[:16]
        if self.shots(out) and not refresh:
            return out
        tmp = out.with_name(f"{out.name}.tmp-{os.getpid()}")
        cmd = [self.exe or "hyperframes", "capture", url, "-o", str(tmp), "--json", "--skip-vision", "--skip-assets",
               "--max-screenshots", str(self.max_shots), "--timeout", str(self.timeout_ms),
               "--capture-budget", str(self.timeout_ms)]
        r = self.run(cmd, capture_output=True, text=True, timeout=self.timeout_ms / 1000 * 3 + 60)
        try:
            res = json.loads((r.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            res = {"ok": r.returncode == 0}
        if r.returncode or not res.get("ok", True) or not self.shots(tmp):
            raise ProviderError(f"hyperframes capture failed for {url}: {res.get('error') or (r.stderr or '')[-200:]}")
        if out.exists():                        # refresh: keep the old capture beside the new one
            out.rename(out.with_name(f"{out.name}.old-{os.getpid()}"))
        tmp.rename(out)
        return out

    def search(self, query, kind="image", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20,
               refresh: bool = False):
        url = query.strip()
        if kind != "image" or not URL.match(url) or not self.available:
            return []
        out = self.capture(url, refresh)
        host = urllib.parse.urlsplit(url).hostname or url
        lic = L.normalize("user-capture")
        cands = []
        for p in self.shots(out)[: max(1, int(limit))]:
            w, h, _ = self.probe(p)
            where = "full page" if p.stem == "full-page" else f"{int(p.stem.split('-')[1])}% down"
            title = f"{host} ({where})"
            cands.append(Candidate(
                id=f"webcapture:{sha256_text(url)[:12]}:{p.stem}", provider=self.name, kind="image", title=title,
                url=p.as_uri(), thumb=p.as_uri(), w=w, h=h, license=lic.id,
                attribution=L.attribution(title, "", url, lic, self.label), source_page=url,
                tags=tuple(t for t in re.split(r"[^a-z0-9]+", host.lower()) if t and t not in ("www", "com")),
                extra={"capture_dir": str(out), "plate": p.stem == "full-page", "license_note": lic.note}))
        return cands


def provider(settings=None, **kw) -> WebCapture:
    return WebCapture.from_settings(settings, **kw)
