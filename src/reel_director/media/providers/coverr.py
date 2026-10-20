"""Coverr: free stock video under the Coverr License (needs a free API key).

Built, inactive until COVERR_API_KEY (or settings media.coverr_key) is set; request a key at
https://api.coverr.co/docs/ (Coverr for developers).
API (docs, 2026-10-20): GET https://api.coverr.co/videos?query&page_size&urls=true with
`Authorization: Bearer <key>` -> {page, pages, total, hits: [{id, title, description, tags, poster, thumbnail,
duration, max_width, max_height, aspect_ratio, is_vertical, urls: {mp4, mp4_preview, mp4_download}}]}.
The urls are signed for our key. Coverr requires that downloads go through `mp4_download` (that request is
their download count); after it we also PATCH /videos/<id>/stats/downloads (204), best effort.
Orientation is filtered client-side from is_vertical / aspect_ratio.
"""
from __future__ import annotations

import logging

from .. import license as L
from ..base import Candidate, Provider, ProviderError

log = logging.getLogger(__name__)
API = "https://api.coverr.co/videos"


class Coverr(Provider):
    name = "coverr"
    label = "Coverr"
    kinds = ("video",)
    key_name = "coverr_key"
    key_env = ("COVERR_API_KEY", "REEL_DIRECTOR_COVERR_KEY")
    signup = "free key: https://api.coverr.co/docs/"

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}

    def search(self, query, kind="video", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        if not self.available or kind != "video" or not query.strip():
            return []
        params = {"query": query.strip()[:200], "page_size": max(1, min(int(limit), 100)), "urls": "true"}
        data = self.api(API, params, self.headers()) or {}
        out = [c for hit in data.get("hits", []) if (c := self.candidate(hit, duration))]
        if orientation == "portrait":
            out.sort(key=lambda c: not c.extra.get("is_vertical"))        # stable: vertical first, API order kept
        return out

    def candidate(self, hit: dict, duration) -> Candidate | None:
        urls = hit.get("urls") or {}
        url = urls.get("mp4_download") or urls.get("mp4")
        dur = float(hit.get("duration") or 0)
        if not url or (dur and dur < duration[0]):
            return None
        title = (hit.get("title") or "Coverr clip").strip()
        lic = L.normalize("coverr")
        page = hit.get("url") or (f"https://coverr.co/videos/{hit['slug']}" if hit.get("slug") else "https://coverr.co")
        tags = tuple(t if isinstance(t, str) else t.get("name", "") for t in hit.get("tags") or [])
        return Candidate(
            id=f"coverr:{hit['id']}", provider=self.name, kind="video", title=title, url=url,
            thumb=hit.get("thumbnail") or hit.get("poster") or "", w=int(hit.get("max_width") or 0),
            h=int(hit.get("max_height") or 0), duration=dur, license=lic.id,
            attribution=L.attribution(title, "", page, lic, self.label), source_page=page,
            tags=tuple(t for t in tags if t),
            extra={"description": (hit.get("description") or "")[:400], "is_vertical": bool(hit.get("is_vertical")),
                   "aspect_ratio": hit.get("aspect_ratio"), "preview": urls.get("mp4_preview", ""),
                   "video_id": hit["id"], "license_note": lic.note})

    windowed = False        # downloads must go through mp4_download (whole file; Coverr clips are short)

    def cache_key(self, c: Candidate) -> str:
        return f"coverr:{c.extra.get('video_id') or c.id}"

    def downloaded(self, c: Candidate) -> None:
        try:
            self.http.ping(f"{API}/{c.extra.get('video_id')}/stats/downloads", method="PATCH", headers=self.headers())
        except ProviderError as e:
            log.warning("coverr download stats ping failed for %s: %s", c.id, e)


def provider(settings=None, **kw) -> Coverr:
    return Coverr.from_settings(settings, **kw)
