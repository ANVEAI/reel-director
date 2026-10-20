"""Pixabay: free photos and stock video under the Pixabay Content License (needs a free API key).

Built, inactive until PIXABAY_API_KEY (or settings media.pixabay_key) is set; get a key at
https://pixabay.com/api/docs/ (log in, the key is shown on the docs page).
API (docs, 2026-10-20): GET https://pixabay.com/api/?key&q(<=100 chars)&image_type=photo&orientation=
horizontal|vertical&safesearch=true&per_page=3..200 and GET https://pixabay.com/api/videos/?key&q&video_type=film.
Rules we follow: cache responses 24 h (Provider.api), no hotlinking (fetch() downloads to the cache), show where
results come from (provider label in Studio + the credit line). Without "full API access" images top out at
largeImageURL (1280 px long side): candidates report that rendition's size, so select.py ranks them honestly.
Video renditions: large (~4K, may be empty), medium (~1080p), small, tiny: the smallest that reaches
min_short_side wins.
"""
from __future__ import annotations

from .. import license as L
from ..base import Candidate, Provider, pick_rendition

API = "https://pixabay.com/api/"
ORIENT = {"portrait": "vertical", "landscape": "horizontal"}


class Pixabay(Provider):
    name = "pixabay"
    label = "Pixabay"
    kinds = ("image", "video")
    key_name = "pixabay_key"
    key_env = ("PIXABAY_API_KEY", "REEL_DIRECTOR_PIXABAY_KEY")
    signup = "free key: https://pixabay.com/api/docs/"

    def search(self, query, kind="image", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        if not self.available or kind not in self.kinds or not query.strip():
            return []
        params = {"key": self.key, "q": query.strip()[:100], "safesearch": "true",
                  "per_page": max(3, min(int(limit), 200))}
        if kind == "image":
            params.update(image_type="photo", **({"orientation": ORIENT[orientation]} if orientation in ORIENT else {}))
        else:
            params["video_type"] = "film"
        data = self.api(API + ("videos/" if kind == "video" else ""), params) or {}
        make = self.video if kind == "video" else self.image
        return [c for hit in data.get("hits", []) if (c := make(hit, min_short_side, duration, orientation))]

    def cache_key(self, c: Candidate) -> str:
        return f"{c.id}:{c.w}x{c.h}"        # pixabay.com/get/ URLs expire after 24 h; the item + size does not

    def _base(self, hit: dict, kind: str) -> dict:
        tags = tuple(t.strip() for t in str(hit.get("tags", "")).split(",") if t.strip())
        title = ", ".join(tags[:3]) or f"Pixabay {kind} {hit.get('id')}"
        lic = L.normalize("pixabay")
        page = hit.get("pageURL", "")
        user = str(hit.get("user") or "")
        return dict(id=f"pixabay:{kind}:{hit['id']}", provider=self.name, kind=kind, title=title, license=lic.id,
                    attribution=L.attribution(title, user, page, lic), source_page=page, creator=user, tags=tags)

    def image(self, hit: dict, min_short_side: int, duration, orientation=None) -> Candidate | None:
        ow, oh = int(hit.get("imageWidth") or 0), int(hit.get("imageHeight") or 0)
        if hit.get("imageURL"):                 # approved full-access accounts get the original
            url, w, h = hit["imageURL"], ow, oh
        elif hit.get("largeImageURL") and ow and oh:
            s = min(1.0, 1280 / max(ow, oh))
            url, w, h = hit["largeImageURL"], round(ow * s), round(oh * s)
        else:
            return None
        return Candidate(url=url, thumb=hit.get("webformatURL") or hit.get("previewURL", ""), w=w, h=h,
                         extra={"orig_w": ow, "orig_h": oh, "size": hit.get("imageSize")}, **self._base(hit, "image"))

    def video(self, hit: dict, min_short_side: int, duration, orientation=None) -> Candidate | None:
        dur = float(hit.get("duration") or 0)
        if dur and dur < duration[0]:
            return None
        rends = [{"url": v["url"], "w": v.get("width", 0), "h": v.get("height", 0), "size": v.get("size", 0),
                  "thumb": v.get("thumbnail", ""), "name": n}
                 for n, v in (hit.get("videos") or {}).items() if v and v.get("url")]
        r = pick_rendition(rends, min_short_side, orientation)
        if not r:
            return None
        return Candidate(url=r["url"], thumb=r["thumb"], w=int(r["w"]), h=int(r["h"]), duration=dur,
                         extra={"rendition": r["name"], "size": r["size"]}, **self._base(hit, "video"))


def provider(settings=None, **kw) -> Pixabay:
    return Pixabay.from_settings(settings, **kw)
