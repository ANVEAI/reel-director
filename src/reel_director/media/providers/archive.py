"""Internet Archive: public-domain / CC film and video (Prelinger, government films...) (no key).

Search: GET https://archive.org/advancedsearch.php with a Lucene query over title/subject/description,
mediatype:movies, the curated collections (TRUSTED, below) and an explicit list of allowed license URLs (wildcards
on licenseurl make the backend fail, seen
2026-10-20). resolve() reads https://archive.org/metadata/<id> and picks the best derivative (h.264 MP4 first) with
its size and length. Most items are minutes long and SD, so select.py ranks them below modern stock and fetch()
takes a window (ffmpeg over HTTP ranges) rather than the whole film.
"""
from __future__ import annotations

import re
import urllib.parse

from .. import license as L
from ..base import Candidate, Provider, pick_rendition, setting

API = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
LICENSES = ["http://creativecommons.org/licenses/publicdomain/", "http://creativecommons.org/publicdomain/mark/1.0/",
            "http://creativecommons.org/publicdomain/zero/1.0/", "https://creativecommons.org/publicdomain/zero/1.0/",
            "https://creativecommons.org/publicdomain/mark/1.0/"] + \
    [f"{s}://creativecommons.org/licenses/{f}/{v}/" for s in ("http", "https") for f in ("by", "by-sa")
     for v in ("1.0", "2.0", "2.5", "3.0", "4.0")]
FORMATS = ("h.264 HD", "h.264", "MPEG4", "h.264 IA", "HiRes MPEG4", "512Kb MPEG4", "Ogg Video", "MPEG2")
# Broadcast masters are labelled "MPEG2" too (smoke test: a 3.6 GB / 38 GB .mxf original was picked as the only
# 1080p file); a window fetch out of those is slow and fragile, so they never count as renditions.
SKIP_EXT = (".mxf",)
LUCENE = re.compile(r'[+\-&|!(){}\[\]^"~*?:\\/]')
# Archive licenses are declared by the uploader, and many are false: the 2026-10-20 smoke tests surfaced a "Pingu /
# Blue's Clues / Nickelodeon" rip marked PDM (top hit for "clock"), a "Looney Tunes" short marked CC0, "Taxi Driver
# 1976" and Shaw Bros films marked CC BY 4.0 inside feature_films, LeapFrog episodes marked PDM. So by default only
# collections whose uploader IS the rights holder or a public-domain curator are searched (Prelinger Archives,
# FedFlix = US government films, NASA's own collection): `AND collection:(...)` at the source, re-checked per item.
# settings media.archive_any_uploader / REEL_DIRECTOR_ARCHIVE_ANY_UPLOADER=1 opens every upload, ranked lower
# (license_trust "uploader-declared") and flagged in Studio.
TRUSTED = ("prelinger", "fedflix", "nasa")
UNTRUSTED_NOTE = "uploader-declared license on Internet Archive: verify the rights holder before publishing"


def terms(query: str) -> str:
    words = [w for w in LUCENE.sub(" ", query).split() if w.upper() not in ("AND", "OR", "NOT")]
    return " ".join(words[:8])


class Archive(Provider):
    name = "archive"
    label = "Internet Archive"
    kinds = ("video",)

    @property
    def any_uploader(self) -> bool:
        v = setting(self.settings, "archive_any_uploader", ("REEL_DIRECTOR_ARCHIVE_ANY_UPLOADER",))
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    def search(self, query, kind="video", min_short_side=1080, duration=(2.0, 10.0), orientation=None, limit=20):
        t = terms(query)
        if kind != "video" or not t:
            return []
        lic = " OR ".join(f'"{u}"' for u in LICENSES)
        q = f"(title:({t}) OR subject:({t}) OR description:({t})) AND mediatype:movies AND licenseurl:({lic})"
        if not self.any_uploader:
            q += f" AND collection:({' OR '.join(TRUSTED)})"
        params = {"q": q, "fl[]": ["identifier", "title", "licenseurl", "creator", "subject", "description",
                                   "collection"],
                  "rows": max(1, min(int(limit), 50)), "output": "json"}
        data = self.api(API, params) or {}
        return [c for d in (data.get("response") or {}).get("docs", []) if (c := self.candidate(d))]

    def candidate(self, d: dict) -> Candidate | None:
        lic = L.normalize("", d.get("licenseurl"))
        ident = d.get("identifier")
        if not lic.allowed or not ident:
            return None
        title = _one(d.get("title")) or ident
        creator = _one(d.get("creator"))
        subj = d.get("subject") or []
        tags = tuple(s.strip() for s in (subj if isinstance(subj, list) else re.split(r"[;,]", subj)) if s.strip())
        page = f"https://archive.org/details/{ident}"
        cols = d.get("collection") or []
        cols = set(cols if isinstance(cols, list) else [cols])
        trust = "curated" if cols & set(TRUSTED) else "uploader-declared"
        if trust != "curated" and not self.any_uploader:
            return None
        return Candidate(
            id=f"archive:{ident}", provider=self.name, kind="video", title=title, url="",
            thumb=f"https://archive.org/services/img/{ident}", license=lic.id,
            attribution=L.attribution(title, creator, page, lic, self.label), source_page=page, creator=creator,
            tags=tags[:30], extra={"description": re.sub(r"<[^>]+>", " ", _one(d.get("description")))[:400],
                                   "identifier": ident, "collections": sorted(cols), "license_trust": trust,
                                   "license_note": lic.note if trust == "curated" else UNTRUSTED_NOTE})

    def resolve(self, c: Candidate, min_short_side: int = 1080) -> Candidate:
        if c.url or not c.extra.get("identifier"):
            return c
        ident = c.extra["identifier"]
        meta = self.api(META + urllib.parse.quote(ident)) or {}
        lic = L.normalize("", (meta.get("metadata") or {}).get("licenseurl"))
        if not lic.allowed:                     # the item's own record wins over the search index
            c.extra["rejected"] = f"license {lic.id}"
            return c
        rends = [{"url": f"https://archive.org/download/{urllib.parse.quote(ident)}/{urllib.parse.quote(f['name'])}",
                  "w": int(float(f.get("width") or 0)), "h": int(float(f.get("height") or 0)),
                  "size": int(f.get("size") or 0), "length": _len(f.get("length")), "format": f.get("format")}
                 for f in meta.get("files") or [] if f.get("format") in FORMATS
                 and not str(f.get("name", "")).lower().endswith(SKIP_EXT)]
        r = pick_rendition(rends, min_short_side)
        if r:
            c.url, c.w, c.h, c.duration = r["url"], r["w"], r["h"], r["length"]
            c.extra.update(size=r["size"], format=r["format"], resolved=True)
        thumbs = sorted(f["name"] for f in meta.get("files") or [] if f.get("format") == "Thumbnail")
        if thumbs:                              # a frame from the middle reads better than the item tile
            c.extra["frames"] = [f"https://archive.org/download/{urllib.parse.quote(ident)}/{urllib.parse.quote(n)}"
                                 for n in thumbs[:: max(1, len(thumbs) // 6)][:6]]
        return c


def _one(v) -> str:
    return str(v[0] if isinstance(v, list) and v else v or "").strip()


def _len(v) -> float:
    s = str(v or "0")
    if ":" in s:
        parts = [float(x) for x in s.split(":")]
        return sum(x * 60 ** i for i, x in enumerate(reversed(parts)))
    try:
        return float(s)
    except ValueError:
        return 0.0


def provider(settings=None, **kw) -> Archive:
    return Archive.from_settings(settings, **kw)
