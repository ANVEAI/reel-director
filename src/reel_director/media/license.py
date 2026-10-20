"""Licenses: normalize what each source says, allow commercial-safe only, write attribution and credits.

Policy (contract v4): CC0, PDM, public domain and CC BY are allowed; CC BY-SA is allowed but flagged share-alike
(the adapted insert inherits BY-SA) and only on the creator's opt-in (share_alike_ok: style / settings
media.allow_share_alike or RD_MEDIA_SHARE_ALIKE=1; founder: it would reach a commercial reel); NC and ND are rejected (a reel is commercial, and crop/grade/trim is an
adaptation). The stock sites' own licenses (Pixabay Content License, Unsplash License, Coverr License) allow free
commercial use with no required credit; the creator's own media ("own"), Claude-made clips ("original") and a
user-supplied web capture are allowed too. GFDL alone, "all rights reserved" and anything unparsed are rejected:
when in doubt, leave it out.

`normalize(raw, url)` reads every spelling we meet: Openverse ("by-sa" + version), Commons ("CC BY-SA 4.0",
"cc-by-sa-4.0", "Public domain", "GFDL|CC-BY-SA-3.0"), Archive (license URLs), YouTube ("CC-BY-3.0"), NASA ("pd").
A multi-license string keeps its most permissive allowed option. Credits: one TASL line per pick (Title, Author,
Source, License; "modified" for CC BY/BY-SA, which must say so) in the order the reel uses them, deterministic.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CC = "https://creativecommons.org"
# family -> (display name, allowed, share_alike, attribution_required, rank: lower is safer)
FAMILIES = {
    "cc0": ("CC0", True, False, False, 0),
    "pdm": ("Public Domain Mark", True, False, False, 0),
    "pd": ("Public domain", True, False, False, 1),
    "own": ("Own media", True, False, False, 0),
    "original": ("Original (made for this reel)", True, False, False, 0),
    "user-capture": ("User-supplied capture", True, False, False, 2),
    "pixabay": ("Pixabay Content License", True, False, False, 1),
    "unsplash": ("Unsplash License", True, False, False, 1),
    "coverr": ("Coverr License", True, False, False, 1),
    "cc-by": ("CC BY", True, False, True, 2),
    "cc-by-sa": ("CC BY-SA", True, True, True, 3),
    "cc-by-nc": ("CC BY-NC", False, False, True, 9), "cc-by-nd": ("CC BY-ND", False, False, True, 9),
    "cc-by-nc-sa": ("CC BY-NC-SA", False, True, True, 9), "cc-by-nc-nd": ("CC BY-NC-ND", False, False, True, 9),
    "gfdl": ("GNU FDL", False, True, True, 9), "arr": ("All rights reserved", False, False, True, 9),
    "unknown": ("Unknown license", False, False, True, 9),
}
UNVERSIONED = {"pd", "own", "original", "user-capture", "pixabay", "unsplash", "coverr", "unknown", "arr", "gfdl"}
URLS = {"cc0": f"{CC}/publicdomain/zero/1.0/", "pdm": f"{CC}/publicdomain/mark/1.0/",
        "pixabay": "https://pixabay.com/service/license-summary/", "unsplash": "https://unsplash.com/license",
        "coverr": "https://coverr.co/license"}
NOTES = {
    "cc-by-sa": "share-alike: the adapted insert is shared under the same CC BY-SA license; credit it",
    "cc-by": "credit required; say it was modified (cropped/graded)",
    "pd": "public domain; check for trademarks/insignia (NASA logo) and people's likeness",
    "user-capture": "you confirm you may show this page (your own site or permission)",
    "unsplash": "credit requested by the API guidelines (Photo by X on Unsplash)",
    "pixabay": "no credit required; never sell it unaltered or as a stock file",
    "coverr": "no credit required",
    "cc-by-nc": "non-commercial: a reel promoting a product is commercial",
    "cc-by-nd": "no-derivatives: crop/grade/trim is a derivative",
    "cc-by-nc-sa": "non-commercial", "cc-by-nc-nd": "non-commercial, no-derivatives",
    "gfdl": "GFDL needs the full license text shipped with the work", "unknown": "license not recognized",
    "arr": "all rights reserved",
}


@dataclass(frozen=True)
class License:
    id: str              # "cc-by-sa-4.0", "cc0-1.0", "pd", "pixabay", "unknown"
    family: str
    version: str
    name: str            # "CC BY-SA 4.0"
    url: str
    allowed: bool
    share_alike: bool
    attribution_required: bool
    rank: int
    note: str

    @property
    def modified_note(self) -> bool:
        return self.family in ("cc-by", "cc-by-sa")


def _make(family: str, version: str = "") -> License:
    name, ok, sa, attr, rank = FAMILIES[family]
    if family in ("cc0", "pdm"):
        version = version or "1.0"
    lid = f"{family}-{version}" if version and family not in UNVERSIONED else family
    url = URLS.get(family, "")
    if family.startswith("cc-by"):
        url = f"{CC}/licenses/{family[3:]}/{version or '4.0'}/"
        name = f"{name} {version}".strip()
    elif family == "cc0":
        name = f"CC0 {version}"
    return License(lid, family, version, name, url, ok, sa, attr, rank, NOTES.get(family, ""))


def _one(s: str, url: str = "") -> License:
    t = f"{s} {url}".lower().replace("_", "-")
    ver = m.group(1) if (m := re.search(r"(?<![\d.])([1-4]\.[05])(?![\d.])", t)) else ""
    if "publicdomain/zero" in t or re.search(r"\bcc-?0\b|cc zero|creative commons zero", t):
        return _make("cc0", "1.0")
    if "publicdomain/mark" in t or re.search(r"\bpdm\b|public domain mark", t):
        return _make("pdm", "1.0")
    for fam in ("own", "original", "user-capture", "pixabay", "unsplash", "coverr"):
        if re.fullmatch(rf"{fam}(?:[\s-]+(?:content[\s-]+)?licen[cs]e)?", t.strip()):
            return _make(fam)
    if "licenses/publicdomain" in t or re.search(r"(^|\s)(pd|public[ -]domain|pd-[\w-]+|no known copyright)\b", t):
        return _make("pd")
    if "all rights reserved" in t or re.search(r"\barr\b", t):
        return _make("arr")
    if "gfdl" in t or "gnu free documentation" in t:
        return _make("gfdl")
    cc = re.search(r"licenses/(by(?:-nc)?(?:-nd|-sa)?)/", t) or \
        re.search(r"(?:^|[\s(])(?:cc[\s-]+)?(by(?:[\s-]+nc)?(?:[\s-]+(?:nd|sa))?)(?=$|[\s\-,.)\d])", t)
    if cc:
        parts = re.split(r"[\s-]+", cc.group(1))
        fam = "cc-" + "-".join(parts)
        if fam in FAMILIES:
            return _make(fam, ver)
    if re.search(r"attribution[\s-]+sharealike|attribution[\s-]+share[\s-]+alike", t):
        return _make("cc-by-sa", ver)
    if re.search(r"\battribution\b", t) and not re.search(r"non-?commercial|noderiv", t):
        return _make("cc-by", ver)
    if re.search(r"non-?commercial", t):
        return _make("cc-by-nc", ver)
    return _make("unknown")


def normalize(raw: str | None = "", url: str | None = "", version: str | None = "") -> License:
    """Any license spelling (+ optional URL / version) -> License. A list keeps its safest allowed option."""
    raw, url = str(raw or "").strip(), str(url or "").strip()
    if version and raw and not re.search(r"\d\.\d", raw):
        raw = f"{raw} {version}"
    opts = [o for o in re.split(r"\s*(?:\||;|\bor\b|\bdual\b)\s*", raw, flags=re.I) if o] or [""]
    lic = [_one(o, url if len(opts) == 1 else "") for o in opts]
    if len(opts) > 1 and url:
        lic.append(_one("", url))
    lic.sort(key=lambda x: (not x.allowed, x.rank, x.id))
    return lic[0]


def info(license_id: str) -> License:
    """License for a normalized id stored on a Candidate ("cc-by-sa-4.0")."""
    return normalize(license_id)


def allowed(license_id: str) -> bool:
    return info(license_id).allowed


def share_alike_ok(settings=None) -> bool:
    """The creator opted in to CC BY-SA picks: RD_MEDIA_SHARE_ALIKE=1, or media.allow_share_alike in the settings /
    the script's style.media (a dict holding allow_share_alike directly works too)."""
    if os.environ.get("RD_MEDIA_SHARE_ALIKE", "").lower() in ("1", "true", "yes"):
        return True
    s = settings or {}
    m = s.get("media") if isinstance(s.get("media"), dict) else s
    return bool(m.get("allow_share_alike") or s.get("media.allow_share_alike"))


def attribution(title: str, creator: str, source_page: str, lic: License | str, source: str = "",
                modified: bool = True, kind: str = "video") -> str:
    """One TASL credit line: '"Title" by Creator, via Source (page), CC BY 4.0 (url), modified'."""
    lic = info(lic) if isinstance(lic, str) else lic
    title = (title or "Untitled").strip().strip('"')
    who = f" by {creator.strip()}" if creator and creator.strip() else ""
    via = f" via {source}" if source else ""
    page = f" ({source_page})" if source_page else ""
    if lic.family == "unsplash":
        return f'"{title}" — Photo{who} on Unsplash{page}'
    if lic.family == "pixabay":
        return f'"{title}"{who} from Pixabay{page}'
    if lic.family in ("own", "original"):
        return ""
    terms = f", {lic.name}" + (f" ({lic.url})" if lic.url else "")
    mod = (f", modified (cropped, {'trimmed, ' if kind == 'video' else ''}graded)" if modified and lic.modified_note
           else "")
    return f'"{title}"{who}{via}{page}{terms}{mod}'


def credits(cands: Iterable) -> list[str]:
    """Credit lines for the picks a reel uses, in order, one per source item; own/original media need none."""
    out, seen = [], set()
    for c in cands:
        if c.id in seen:
            continue
        seen.add(c.id)
        line = c.attribution or attribution(c.title, getattr(c, "creator", ""), c.source_page, c.license)
        if line:
            out.append(line)
    return out


def write_credits(path: Path, cands: Iterable, reel: str = "") -> Path:
    """renders/<reel>.credits.txt: what to paste under the post. Deterministic (no clock)."""
    cands = list(cands)
    lines = credits(cands)
    sa = sorted({info(c.license).name for c in cands if info(c.license).share_alike})
    head = [f"B-roll credits{f' — {reel}' if reel else ''}", ""]
    tail = ["", "Share-alike: this reel adapts " + ", ".join(sa) + " material; those inserts are shared under the "
            "same license."] if sa else []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(head + (lines or ["(no third-party media)"]) + tail) + "\n", encoding="utf-8")
    return path
