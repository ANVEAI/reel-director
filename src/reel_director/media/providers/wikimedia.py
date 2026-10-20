"""Wikimedia Commons: CC/PD photos and video (no key).

One request per search: generator=search over the File: namespace (`<q> filetype:bitmap` or `filetype:video`)
with imageinfo/videoinfo props (size, mime, url, a 480 px thumb, extmetadata license/artist fields; for video the
transcode `derivatives`, so the pick can be the 1080p VP9 transcode instead of a 200 MB original; for images the
smallest standard-width thumbnail that covers the reel frame, see scaled()). Search-time
size filters (filew:/fileh:) make CirrusSearch answer "too busy", so size is ranked client-side instead.
`Restrictions` (personality rights, trademarks) are kept in extra and down-ranked by select.py. Commons sometimes
answers 200 with {"error": cirrussearch-too-busy | maxlag}: we retry once, then raise ProviderError.
"""
from __future__ import annotations

import re
import time

from .. import license as L
from ..base import REEL_FRAME, Candidate, Provider, ProviderError, clean_text, pick_rendition, strip_utm

API = "https://commons.wikimedia.org/w/api.php"
FIELDS = "LicenseShortName|License|LicenseUrl|Artist|Credit|ObjectName|ImageDescription|AttributionRequired|" \
         "UsageTerms|Restrictions|Categories"
BUSY = ("cirrussearch-too-busy-error", "maxlag", "ratelimited")
# Commons serves thumbnails at standard widths only (1700px answered HTTP 400, 1280/1920/3840 200: 2026-10-20).
BUCKETS = (960, 1280, 1920, 3840)
HEADROOM = 1.2                  # room for a Ken Burns push without upscaling
THUMB_W = re.compile(r"/((?:lossy-)?(?:page\d+-)?)\d+px-(?=[^/]*$)")


def scaled(thumb: str, w: int, h: int, min_short_side: int, orientation: str | None = None):
    """(url, w, h) of the smallest standard-width thumbnail that still covers the reel frame x HEADROOM, or None
    when only the original is big enough. Smoke test: a 3378x4622 original was 8.3 MB; the 1920 px rendition that
    covers a 1080x1920 crop is 1.2 MB."""
    if not (thumb and w and h and THUMB_W.search(thumb)):
        return None
    k = min_short_side / 1080 * HEADROOM
    if orientation in REEL_FRAME:
        tw, th = REEL_FRAME[orientation]
        need = w * max(tw / w, th / h) * k
    else:
        need = min_short_side * HEADROOM * w / min(w, h)
    bw = next((b for b in BUCKETS if b >= need), None)
    if not bw or bw >= w:
        return None
    return THUMB_W.sub(lambda m: f"/{m.group(1)}{bw}px-", thumb, count=1), bw, round(h * bw / w)


class Wikimedia(Provider):
    name = "wikimedia"
    label = "Wikimedia Commons"
    kinds = ("image", "video")
    retry_wait = 2.0

    def search(self, query, kind="image", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        if kind not in self.kinds or not query.strip():
            return []
        vid = kind == "video"
        p = "vi" if vid else "ii"
        params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
                  "gsrsearch": f"{query.strip()[:200]} filetype:{'video' if vid else 'bitmap'}", "gsrnamespace": "6",
                  "gsrlimit": max(1, min(int(limit), 50)), "prop": "videoinfo" if vid else "imageinfo",
                  f"{p}prop": "url|size|mime|mediatype|extmetadata" + ("|derivatives" if vid else ""),
                  f"{p}urlwidth": "480", f"{p}extmetadatafilter": FIELDS, "maxlag": "5"}
        for attempt in (0, 1):
            data = self.api(API, params) or {}
            err = data.get("error")
            if not err:
                break
            if err.get("code") in BUSY and attempt == 0:
                time.sleep(self.retry_wait)
                continue
            raise ProviderError(f"Commons: {err.get('code')}: {err.get('info', '')[:120]}")
        pages = sorted((data.get("query") or {}).get("pages", []), key=lambda pg: pg.get("index", 0))
        return [c for pg in pages if (c := self.candidate(pg, kind, min_short_side, duration, orientation))]

    def candidate(self, pg: dict, kind: str, min_short_side: int, duration, orientation=None) -> Candidate | None:
        info = (pg.get("videoinfo") or pg.get("imageinfo") or [None])[0]
        if not info or not info.get("url"):
            return None
        mt = info.get("mediatype", "")
        if (kind == "video") != (mt in ("VIDEO", "AUDIO")) or mt == "AUDIO":
            return None
        meta = {k: (v or {}).get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
        lic = L.normalize(meta.get("LicenseShortName") or meta.get("License"), meta.get("LicenseUrl"))
        if not lic.allowed:
            return None
        dur = float(info.get("duration") or 0)
        if kind == "video" and dur and dur < duration[0]:
            return None
        url, w, h = strip_utm(info["url"]), int(info.get("width") or 0), int(info.get("height") or 0)
        size = int(info.get("size") or 0)
        if kind == "video":
            rends = [{"url": strip_utm(d["src"]), "w": d.get("width", 0), "h": d.get("height", 0),
                      "size": int(d.get("bandwidth", 0) * dur / 8), "type": d.get("type", "")}
                     for d in info.get("derivatives") or [] if "audio/" not in d.get("type", "")
                     and "mpeg4.mov" not in d.get("src", "")]
            if r := pick_rendition(rends, min_short_side, orientation):
                url, w, h, size = r["url"], int(r["w"]), int(r["h"]), r["size"]
        elif "svg" not in str(info.get("mime")) and (r := scaled(strip_utm(info.get("thumburl") or ""), w, h,
                                                                  min_short_side, orientation)):
            url, w, h, size = r[0], r[1], r[2], 0          # size unknown until downloaded
        page_title = pg.get("title", "")
        title = clean_text(meta.get("ObjectName")) or re.sub(r"^File:|\.\w+$", "", page_title)
        creator = re.sub(r"\s*\(\s*(talk|contribs?|discussion|page)\s*(\|\s*\w+\s*)?\)", "",
                         clean_text(meta.get("Artist"), 160)).strip()[:120]
        page = info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{page_title.replace(' ', '_')}"
        cats = [c.strip() for c in clean_text(meta.get("Categories"), 2000).split("|") if c.strip()]
        restr = clean_text(meta.get("Restrictions"), 200)
        return Candidate(
            id=f"wikimedia:{pg.get('pageid')}", provider=self.name, kind=kind, title=title, url=url,
            thumb=strip_utm(info.get("thumburl") or ""), w=w, h=h, duration=dur, license=lic.id,
            attribution=L.attribution(title, creator, page, lic, self.label, kind=kind), source_page=page, creator=creator,
            tags=tuple(cats[:20]),
            extra={"description": clean_text(meta.get("ImageDescription")), "mime": info.get("mime"),
                   "size": size, "orig_w": int(info.get("width") or 0), "orig_h": int(info.get("height") or 0),
                   "original_url": strip_utm(info["url"]), "restrictions": restr, "license_note": lic.note})


def provider(settings=None, **kw) -> Wikimedia:
    return Wikimedia.from_settings(settings, **kw)
