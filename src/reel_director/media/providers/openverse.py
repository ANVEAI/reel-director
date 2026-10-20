"""Openverse: CC and public-domain images aggregated from Flickr, Wikimedia, museums... (no key).

API: GET https://api.openverse.org/v1/images/?q=..&license=by,by-sa,cc0,pdm&aspect_ratio=tall|wide|square
&size=large&page_size<=20 (anonymous limit). The license filter is the policy (no NC/ND) applied at the source;
license.normalize re-checks every hit anyway. `filter_dead=false` skips Openverse's slow dead-link probe (we
download the pick and fail over if it is gone). Images only: Openverse has no video.
"""
from __future__ import annotations

from .. import license as L
from ..base import Candidate, Provider

API = "https://api.openverse.org/v1/images/"
ASPECT = {"portrait": "tall", "landscape": "wide", "square": "square"}


class Openverse(Provider):
    name = "openverse"
    label = "Openverse"
    kinds = ("image",)

    def search(self, query, kind="image", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        if kind != "image" or not query.strip():
            return []
        params = {"q": query.strip()[:200], "license": "by,by-sa,cc0,pdm", "page_size": max(1, min(int(limit), 20)),
                  "mature": "false", "filter_dead": "false"}
        if orientation in ASPECT:
            params["aspect_ratio"] = ASPECT[orientation]
        if min_short_side >= 720:
            params["size"] = "large"
        data = self.api(API, params)
        return [c for r in (data or {}).get("results", []) if (c := self.candidate(r))]

    def candidate(self, r: dict) -> Candidate | None:
        lic = L.normalize(r.get("license"), r.get("license_url"), r.get("license_version"))
        if not lic.allowed or not r.get("url"):
            return None
        title = (r.get("title") or "Untitled").strip()
        creator = (r.get("creator") or "").strip()
        src = r.get("source") or r.get("provider") or ""
        via = f"{src.replace('_', ' ').title()} via Openverse" if src else "Openverse"
        page = r.get("foreign_landing_url") or r.get("detail_url") or ""
        return Candidate(
            id=f"openverse:{r['id']}", provider=self.name, kind="image", title=title, url=r["url"],
            thumb=r.get("thumbnail") or "", w=int(r.get("width") or 0), h=int(r.get("height") or 0), duration=0.0,
            license=lic.id, attribution=L.attribution(title, creator, page, lic, via, kind="image"), source_page=page,
            creator=creator, tags=tuple(t["name"] for t in r.get("tags") or [] if t.get("name")),
            extra={"source": src, "filetype": r.get("filetype"), "filesize": r.get("filesize"),
                   "license_note": lic.note, "mature": bool(r.get("mature"))})


def provider(settings=None, **kw) -> Openverse:
    return Openverse.from_settings(settings, **kw)
