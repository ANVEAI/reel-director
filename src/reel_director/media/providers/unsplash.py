"""Unsplash: high-quality photos under the Unsplash License (needs a free Access Key).

Built, inactive until UNSPLASH_ACCESS_KEY (or settings media.unsplash_key) is set; create a (demo) app at
https://unsplash.com/oauth/applications (50 requests/hour until approved for production).
API (docs, 2026-10-20): GET https://api.unsplash.com/search/photos?query&per_page<=30&orientation=landscape|
portrait|squarish&content_filter=high with `Authorization: Client-ID <key>` and `Accept-Version: v1`.
Guidelines we follow: images come from the returned urls.raw (imgix: w/fm/q params, ixid kept); every use
triggers the photo's `download_location` (tracking only, never used as the image); credit "Photo by <name> on
Unsplash" linking both with utm_source=reel_director&utm_medium=referral.
"""
from __future__ import annotations

import logging
import urllib.parse

from .. import license as L
from ..base import Candidate, Provider, ProviderError

log = logging.getLogger(__name__)
API = "https://api.unsplash.com/search/photos"
UTM = "utm_source=reel_director&utm_medium=referral"
ORIENT = {"portrait": "portrait", "landscape": "landscape", "square": "squarish"}
HEADROOM = 1.5          # fetch 1.5x the reel's short side: room for Ken Burns / crop without upscaling


def _utm(url: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}{UTM}" if url else ""


class Unsplash(Provider):
    name = "unsplash"
    label = "Unsplash"
    kinds = ("image",)
    key_name = "unsplash_key"
    key_env = ("UNSPLASH_ACCESS_KEY", "REEL_DIRECTOR_UNSPLASH_KEY")
    signup = "free key: https://unsplash.com/oauth/applications"

    def headers(self) -> dict:
        return {"Authorization": f"Client-ID {self.key}", "Accept-Version": "v1"}

    def search(self, query, kind="image", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        if not self.available or kind != "image" or not query.strip():
            return []
        params = {"query": query.strip()[:200], "per_page": max(1, min(int(limit), 30)), "content_filter": "high"}
        if orientation in ORIENT:
            params["orientation"] = ORIENT[orientation]
        data = self.api(API, params, self.headers()) or {}
        return [c for r in data.get("results", []) if (c := self.candidate(r, min_short_side))]

    def candidate(self, r: dict, min_short_side: int) -> Candidate | None:
        raw, ow, oh = (r.get("urls") or {}).get("raw"), int(r.get("width") or 0), int(r.get("height") or 0)
        if not raw or not ow or not oh:
            return None
        short = min(ow, oh, int(min_short_side * HEADROOM))
        w, h = (short, round(short * oh / ow)) if ow <= oh else (round(short * ow / oh), short)
        url = f"{raw}{'&' if '?' in raw else '?'}{urllib.parse.urlencode({'w': w, 'fm': 'jpg', 'q': 85})}"
        user = r.get("user") or {}
        name = (user.get("name") or user.get("username") or "").strip()
        title = (r.get("description") or r.get("alt_description") or "Unsplash photo").strip()
        lic = L.normalize("unsplash")
        page = _utm((r.get("links") or {}).get("html", ""))
        tags = tuple(t.get("title", "") for t in r.get("tags") or [] if t.get("title"))
        return Candidate(
            id=f"unsplash:{r['id']}", provider=self.name, kind="image", title=title, url=url,
            thumb=(r.get("urls") or {}).get("small", ""), w=w, h=h, license=lic.id,
            attribution=L.attribution(title, name, page, lic), source_page=page, creator=name, tags=tags,
            extra={"orig_w": ow, "orig_h": oh, "alt": r.get("alt_description") or "",
                   "download_location": (r.get("links") or {}).get("download_location", ""),
                   "photographer_url": _utm((user.get("links") or {}).get("html", "")), "license_note": lic.note})

    def cache_key(self, c: Candidate) -> str:
        return f"{c.id}:{c.w}x{c.h}"

    def downloaded(self, c: Candidate) -> None:
        """Report the download to Unsplash (API guideline); best effort, never blocks the pick."""
        if c.extra.get("download_location") and self.available:
            try:
                self.http.ping(c.extra["download_location"], headers=self.headers())
            except ProviderError as e:
                log.warning("unsplash download tracking failed for %s: %s", c.id, e)


def provider(settings=None, **kw) -> Unsplash:
    return Unsplash.from_settings(settings, **kw)
