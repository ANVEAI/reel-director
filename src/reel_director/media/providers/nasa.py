"""NASA Image and Video Library: public-domain space/science photos and video (no key).

Search: GET https://images-api.nasa.gov/search?q=..&media_type=image|video. Image hits carry their renditions
(~small/~medium/~large/~orig with sizes) in `links`, so the pick is the smallest one that is big enough. Video
hits carry only posters: resolve() reads the item's asset manifest (collection.json) and metadata.json for the
size and duration, then points at ~orig.mp4 (fetched as a window, so a 200 MB master costs a few MB).

License: NASA media is generally not copyrighted (normalized "pd") with two caveats kept in license_note: NASA
insignia/logos are restricted and NASA must not appear to endorse anything. Items that name a third-party
rights holder (copyright, (c), Getty, AP, Reuters, ESA) are dropped: they are not NASA works.
"""
from __future__ import annotations

import re
import urllib.parse

from .. import license as L
from ..base import Candidate, Provider, pick_rendition

API = "https://images-api.nasa.gov/search"
THIRD_PARTY = re.compile(r"©|\(c\)|copyright|getty|\bap photo|reuters|\besa\b|courtesy of", re.I)
VIDEO_PREF = ("~orig.mp4", "~large.mp4", "~medium.mp4", "~small.mp4", "~mobile.mp4")
NOTE = "NASA media is not copyrighted in the US; no NASA logos/insignia, no implied endorsement"
# Crew photos from the ISS / Shuttle (ids like iss002e5478, s135e012345, sts114-...) carry a burned-in white strip
# with the frame id and date along the bottom (smoke test 2026-10-20, "laptop"): flagged so select.py ranks them
# below clean frames and a treatment can crop the strip.
FRAME_STRIP = re.compile(r"^(iss\d+e\d+|s\d{2,3}e\d+|sts\d+)", re.I)


def _q(url: str) -> str:
    """NASA hrefs contain raw spaces; quote the path, keep the scheme/host."""
    p = urllib.parse.urlsplit(url.replace("http://", "https://", 1))
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(urllib.parse.unquote(p.path))))


def _seconds(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    if m := re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", s):
        return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.match(r"([\d.]+)\s*s", s)
    return float(m[1]) if m else 0.0


class Nasa(Provider):
    name = "nasa"
    label = "NASA Image and Video Library"
    kinds = ("image", "video")

    def search(self, query, kind="image", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        if kind not in self.kinds or not query.strip():
            return []
        data = self.api(API, {"q": query.strip()[:200], "media_type": kind, "page_size": max(1, min(int(limit), 100))})
        items = ((data or {}).get("collection") or {}).get("items", [])
        return [c for it in items if (c := self.candidate(it, kind, min_short_side, orientation))]

    def candidate(self, it: dict, kind: str, min_short_side: int, orientation=None) -> Candidate | None:
        d = (it.get("data") or [{}])[0]
        nid = d.get("nasa_id")
        if not nid or d.get("media_type") != kind:
            return None
        text = " ".join(str(d.get(k) or "") for k in ("description", "photographer", "secondary_creator", "title"))
        if THIRD_PARTY.search(text):
            return None
        links = it.get("links") or []
        thumb = next((_q(x["href"]) for x in links if x.get("rel") == "preview"), "")
        who = str(d.get("photographer") or d.get("secondary_creator") or "").strip()
        creator = who if who.upper().startswith("NASA") else "/".join(x for x in ("NASA", d.get("center"), who) if x)
        lic = L.normalize("pd")
        page = f"https://images.nasa.gov/details/{urllib.parse.quote(nid)}"
        title = (d.get("title") or nid).strip()
        kw = {"files": it.get("href", "")}
        url, w, h = "", 0, 0
        if kind == "image":
            rends = [{"url": _q(x["href"]), "w": x.get("width", 0), "h": x.get("height", 0), "size": x.get("size", 0)}
                     for x in links if x.get("rel") in ("canonical", "alternate") and x.get("render") == "image"]
            r = pick_rendition(rends, min_short_side, orientation)
            if not r:
                return None
            url, w, h = r["url"], int(r["w"]), int(r["h"])
            orig = max(rends, key=lambda r: r["w"] * r["h"])
            kw.update(orig_w=orig["w"], orig_h=orig["h"], size=r.get("size"))
            if FRAME_STRIP.match(nid):
                kw["text_overlay"] = "bottom strip: frame id + date"
        kws = d.get("keywords") or []
        tags = tuple(t.strip() for k in kws for t in str(k).split(",") if t.strip())[:30]
        return Candidate(
            id=f"nasa:{nid}", provider=self.name, kind=kind, title=title, url=url, thumb=thumb, w=w, h=h,
            duration=0.0, license=lic.id, attribution=L.attribution(title, creator, page, lic, self.label, kind=kind),
            source_page=page, creator=creator, tags=tags,
            extra={"description": (d.get("description_508") or d.get("description") or "")[:400],
                   "center": d.get("center"),
                   "date": d.get("date_created"), "license_note": NOTE, **kw})

    def resolve(self, c: Candidate) -> Candidate:
        """Video: the asset manifest -> best mp4 URL; metadata.json -> width, height, duration."""
        if c.kind != "video" or c.url or not c.extra.get("files"):
            return c
        files = [_q(u) for u in self.api(_q(c.extra["files"])) or []]
        mp4 = next((u for pref in VIDEO_PREF for u in files if u.endswith(urllib.parse.quote(pref))), "")
        meta_url = next((u for u in files if u.endswith("/metadata.json")), "")
        meta = (self.api(meta_url) if meta_url else None) or {}
        w = int(meta.get("QuickTime:ImageWidth") or meta.get("Composite:ImageSize", "0x0").split("x")[0] or 0)
        h = int(meta.get("QuickTime:ImageHeight") or meta.get("Composite:ImageSize", "0x0").split("x")[-1] or 0)
        dur = _seconds(meta.get("QuickTime:Duration") or meta.get("QuickTime:MediaDuration"))
        c.url, c.w, c.h, c.duration = mp4, w, h, dur
        c.extra.update(size=meta.get("File:FileSize"), bitrate=meta.get("Composite:AvgBitrate"),
                       fps=meta.get("QuickTime:VideoFrameRate"), resolved=True)
        return c


def provider(settings=None, **kw) -> Nasa:
    return Nasa.from_settings(settings, **kw)
