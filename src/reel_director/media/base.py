"""Media B-roll: the provider interface every source implements (contract v4).

A provider turns a text query into Candidates and a chosen Candidate into a local file:

    search(query, kind="image"|"video", min_short_side=1080, duration=(2, 10), orientation=None, limit=20)
        -> [Candidate{id, provider, kind, title, url, thumb, w, h, duration, license, attribution, source_page,
                      cost_usd}]
    resolve(candidate) -> Candidate     the expensive per-item details (manifests, sizes), only for the shortlist
    fetch(candidate, segment=None) -> Path   a file in the content-addressed media cache (cache.py)

Each provider module exposes `provider(settings=None, **kw)`, the factory the registry (providers/__init__.py)
calls. Keys come from the environment first, then settings["media"]["<name>_key"]; a keyed provider without a key
is built but not `available` and returns no candidates. Paid providers return estimates in `cost_usd` and must
call `guard()` before spending: it raises ApprovalRequired unless the caller passed approved=True.

`Http` is the one network seam (stdlib urllib, no new dependency): tests swap in a fake that serves recorded
fixtures, so unit tests never touch the network. API keys never reach a log, a sidecar or an error message
(`redact`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

KINDS = ("image", "video")
ORIENTATIONS = ("portrait", "landscape", "square")
UA = os.environ.get("REEL_DIRECTOR_UA", "ReelDirector/0.1 (local B-roll search; python-urllib)")
SECRET_PARAMS = {"key", "api_key", "client_id", "access_token", "token", "apikey"}
CHUNK = 1 << 16


class ProviderError(RuntimeError):
    """A source failed (network, quota, bad response). The resolver notes it and tries the next source."""


class ProviderTimeout(ProviderError):
    """A source did not answer in time. Not retried (smoke test 2026-10-20: Openverse search hung 30-60 s per call
    while its other endpoints answered in 0.05 s); Provider.api then skips that source for the rest of the run."""


class ApprovalRequired(RuntimeError):
    """A paid fetch was asked for without the creator's approval of its cost."""


@dataclass
class Candidate:
    id: str                       # "<provider>:<provider id>", stable across searches
    provider: str
    kind: str                     # image | video
    title: str
    url: str                      # the rendition fetch() downloads (best fit for min_short_side)
    thumb: str = ""
    w: int = 0                    # pixels of `url` (0 = unknown until resolve())
    h: int = 0
    duration: float = 0.0         # seconds (0 for images / unknown)
    license: str = ""             # normalized id (license.normalize(...).id), e.g. "cc-by-4.0", "cc0-1.0", "pdm-1.0"
    attribution: str = ""         # ready-to-print credit line (license.attribution)
    source_page: str = ""
    cost_usd: float = 0.0
    creator: str = ""
    tags: tuple = ()
    extra: dict = field(default_factory=dict)   # provider details: description, sizes, flags, original dims

    @property
    def short_side(self) -> int:
        return min(self.w, self.h) if self.w and self.h else 0

    @property
    def aspect(self) -> float:
        return self.w / self.h if self.w and self.h else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, d: Mapping) -> "Candidate":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in d.items() if k in names}
        kw["tags"] = tuple(kw.get("tags") or ())
        kw["extra"] = dict(kw.get("extra") or {})
        return cls(**kw)


def redact(url: str) -> str:
    """The URL with secret query params (key, api_key, client_id...) masked: safe for logs and sidecars."""
    p = urllib.parse.urlsplit(url)
    if not p.query:
        return url
    q = [(k, "***" if k.lower() in SECRET_PARAMS else v) for k, v in urllib.parse.parse_qsl(p.query, True)]
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(q, safe="*,:/")))


def target_aspect(orientation: str | None) -> float | None:
    return {"portrait": 9 / 16, "landscape": 16 / 9, "square": 1.0}.get(orientation or "")


def setting(settings: Mapping | None, name: str, env_names: tuple[str, ...] = (),
            env: Mapping[str, str] | None = None) -> Any:
    """env wins, then settings["media"][name], then a flat settings["media.<name>"]."""
    env = os.environ if env is None else env
    for e in env_names:
        if env.get(e):
            return env[e]
    s = settings or {}
    m = s.get("media") if isinstance(s.get("media"), Mapping) else {}
    return m.get(name) if m.get(name) not in (None, "") else s.get(f"media.{name}")


class Http:
    """GET JSON / download with a UA, retries on 429/5xx and a byte cap. One instance per resolver run."""

    def __init__(self, ua: str = UA, timeout: float = 30.0, retries: int = 2, backoff: float = 1.5):
        self.ua, self.timeout, self.retries, self.backoff = ua, timeout, retries, backoff

    def _open(self, url: str, headers: Mapping[str, str] | None = None, method: str = "GET"):
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, **(headers or {})}, method=method)
        for attempt in range(self.retries + 1):
            try:
                return urllib.request.urlopen(req, timeout=self.timeout)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                body = e.read(300).decode("utf-8", "replace") if e.fp else ""
                raise ProviderError(f"HTTP {e.code} for {redact(url)}: {body.strip()[:200]}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
                    raise ProviderTimeout(f"timed out after {self.timeout:g} s: {redact(url)}") from None
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                raise ProviderError(f"network error for {redact(url)}: {e}") from None
        raise ProviderError(f"unreachable: {redact(url)}")   # pragma: no cover

    def get_json(self, url: str, params: Mapping | None = None, headers: Mapping[str, str] | None = None) -> Any:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        with self._open(url, {"Accept": "application/json", **(headers or {})}) as r:
            raw = _body(r, url)
        try:
            return json.loads(raw)
        except ValueError:
            raise ProviderError(f"not JSON from {redact(url)}: {raw[:120]!r}") from None

    def download(self, url: str, dest: Path, headers: Mapping[str, str] | None = None,
                 max_bytes: int = 400 << 20) -> str:
        """Stream `url` to `dest` (bytes capped); returns the response Content-Type."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with self._open(url, headers) as r, open(dest, "wb") as f:
            ctype = r.headers.get("Content-Type", "")
            while chunk := _body(r, url, CHUNK):
                n += len(chunk)
                if n > max_bytes:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise ProviderError(f"{redact(url)} is over the {max_bytes >> 20} MB cap")
                f.write(chunk)
        return ctype

    def ping(self, url: str, method: str = "GET", headers: Mapping[str, str] | None = None) -> int:
        """Fire-and-check a tracking endpoint (Unsplash download_location, Coverr download stats)."""
        with self._open(url, headers, method) as r:
            r.read(1024)
            return r.status


def _body(r, url: str, n: int | None = None) -> bytes:
    """r.read() / r.read(n) with a stalled body raised as ProviderTimeout / ProviderError (never a bare OSError).
    Never r.read(-1): http.client then reads a chunked body raw, framing included (seen live: corrupt JSON)."""
    try:
        return r.read() if n is None else r.read(n)
    except TimeoutError:
        raise ProviderTimeout(f"body read timed out: {redact(url)}") from None
    except OSError as e:
        raise ProviderError(f"network error reading {redact(url)}: {e}") from None


class Provider:
    """Base for the free/keyed stock sources. Subclasses set the class fields and implement search()."""
    name = "base"
    label = ""                    # how credits name the source ("Wikimedia Commons")
    kinds: tuple[str, ...] = ("image",)
    paid = False
    key_name: str | None = None   # settings["media"][key_name]
    key_env: tuple[str, ...] = ()
    signup = ""                   # where the founder gets a key

    def __init__(self, *, key: str | None = None, http: Http | None = None, cache=None,
                 settings: Mapping | None = None):
        self.key = key or None
        self.http = http or Http()
        self._cache = cache
        self.settings = dict(settings or {})
        self._down_until = 0.0

    down_s = 600.0                # after a timeout, skip this source's API for 10 min (cached answers still serve)

    @classmethod
    def from_settings(cls, settings: Mapping | None = None, env: Mapping[str, str] | None = None, **kw):
        key = setting(settings, cls.key_name, cls.key_env, env) if cls.key_name else None
        return cls(key=kw.pop("key", None) or key, settings=settings, **kw)

    @property
    def cache(self):
        if self._cache is None:
            from .cache import MediaCache
            self._cache = MediaCache()
        return self._cache

    @property
    def available(self) -> bool:
        return self.key_name is None or bool(self.key)

    def status(self) -> dict:
        why = None
        if not self.available and self.key_name:
            why = f"set {self.key_env[0] if self.key_env else ''} (or settings media.{self.key_name}); {self.signup}"
        return {"provider": self.name, "available": self.available, "kinds": list(self.kinds), "paid": self.paid,
                "cost_usd": 0.0, "setup": why}

    def search(self, query: str, kind: str = "image", min_short_side: int = 1080,
               duration: tuple[float, float] = (2.0, 10.0), orientation: str | None = None,
               limit: int = 20) -> list[Candidate]:
        raise NotImplementedError

    def resolve(self, c: Candidate) -> Candidate:
        return c

    def api(self, url: str, params: Mapping | None = None, headers: Mapping[str, str] | None = None,
            ttl: float = 86400) -> Any:
        """GET JSON through the response cache when this provider was given one (24 h: Pixabay's rule, and
        the anonymous Openverse/Commons quotas). The cache key is the redacted URL, so keys never hit disk."""
        full = url + (("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True) if params else "")
        if self._cache is not None and ttl:
            if (hit := self._cache.json_get(f"api:{redact(full)}", ttl)) is not None:
                return hit
        if time.monotonic() < self._down_until:
            raise ProviderTimeout(f"{self.name}: skipped, it timed out earlier in this run")
        try:
            data = self.http.get_json(full, None, headers)
        except ProviderTimeout:
            self._down_until = time.monotonic() + self.down_s   # circuit breaker: one hang per run, not per cue
            raise
        if self._cache is not None and ttl and not (isinstance(data, dict) and data.get("error")):
            self._cache.json_put(f"api:{redact(full)}", data)
        return data

    def guard(self, c: Candidate, approved: bool = False) -> None:
        if (self.paid or c.cost_usd > 0) and not approved:
            raise ApprovalRequired(f"{c.id}: ~${c.cost_usd:.2f} needs the creator's approval")

    windowed = True               # a video `segment` is fetched as a window (False: the source needs whole files)

    def fetch(self, c: Candidate, segment: tuple[float, float] | None = None, approved: bool = False) -> Path:
        """Download `c.url` (or the [start, end) window of a long remote clip) into the cache; idempotent:
        a second call is a cache hit with no network and no tracking ping."""
        self.guard(c, approved)
        if not c.url:
            raise ProviderError(f"{c.id}: no media URL (resolve() it first)")
        if c.kind == "video" and segment and self.windowed:
            return self.cache.fetch_window(c.url, segment, meta=self.sidecar(c), ua=self.http.ua)
        key = self.cache_key(c)
        if key and (hit := self.cache.lookup(key)):
            return hit
        path = self.cache.fetch_url(c.url, self.http, key=key, meta=self.sidecar(c), headers=self.fetch_headers(c))
        self.downloaded(c)
        return path

    def cache_key(self, c: Candidate) -> str | None:
        """Index key for a whole-file fetch; None = the (redacted) URL. Override when URLs expire or are signed."""
        return None

    def fetch_headers(self, c: Candidate) -> dict | None:
        return None

    def downloaded(self, c: Candidate) -> None:
        """Hook after a real download (not a cache hit): the stock sites' download-tracking pings."""

    def sidecar(self, c: Candidate) -> dict:
        d = c.to_dict()
        for k in ("url", "thumb"):
            d[k] = redact(d[k])
        return d


def which(tool: str) -> str:
    return shutil.which(tool) or tool


REEL_FRAME = {"portrait": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}


def pick_rendition(rends: list[dict], min_short_side: int, orientation: str | None = None) -> dict | None:
    """Smallest rendition {w, h, ...} that is big enough, else the largest one. Big enough = covers the reel frame
    for `orientation` without upscaling (a 1920x1312 still is NOT enough for a 1080x1920 crop); with no
    orientation, a short side >= min_short_side."""
    rends = [r for r in rends if r.get("w") and r.get("h")]
    if not rends:
        return None
    if orientation in REEL_FRAME:
        tw, th = REEL_FRAME[orientation]
        k = min_short_side / 1080
        ok = [r for r in rends if r["w"] >= tw * k and r["h"] >= th * k]     # cover-fit scale <= 1
    else:
        ok = [r for r in rends if min(r["w"], r["h"]) >= min_short_side]
    if ok:
        return min(ok, key=lambda r: (r["w"] * r["h"], r.get("size") or 0))
    return max(rends, key=lambda r: (r["w"] * r["h"], -(r.get("size") or 0)))


def strip_utm(url: str) -> str:
    """Drop utm_* tracking params (Commons adds them), so one file has one URL and one cache key."""
    p = urllib.parse.urlsplit(url)
    if "utm_" not in p.query:
        return url
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, True) if not k.startswith("utm_")]
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(q)))


def clean_text(s: Any, limit: int = 300) -> str:
    """HTML (Commons Artist/Description fields) -> one line of plain text. Hidden blocks go first: Commons hides
    Wikidata QuickStatements ('label QS:Len,"..."') in display:none divs (smoke test: they leaked into a credit)."""
    import html
    t = re.sub(r"<(\w+)[^>]*display:\s*none[^>]*>.*?</\1>", " ", str(s or ""), flags=re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\blabel QS:\w+,\s*\".*?\"(?=\s|$)", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:limit]
