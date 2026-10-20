"""YouTube Creative-Commons B-roll provider (v4 media contract, docs/research/v4-media-broll-contract.md).

Discovery: YouTube Data API v3 `search.list` with `videoLicense=creativeCommon` (100 quota units of the default
10,000/day), then `videos.list` (1 unit) for duration, definition and the authoritative `status.license`. YouTube's
only Creative-Commons option is CC BY 3.0, so every hit is CC-BY (credit required, commercial use allowed).

Credentials (nothing here creates or changes cloud config):
  * an API key: env YOUTUBE_API_KEY / REEL_DIRECTOR_YOUTUBE_API_KEY, or settings media.youtube_cc_key; or
  * `media.youtube_auth: "adc"` (env REEL_DIRECTOR_YOUTUBE_AUTH=adc): a bearer token from
    `gcloud auth application-default print-access-token`, which must carry the youtube.readonly scope.
  Without either the provider is built but not `available` and returns no candidates; status()["setup"] carries
  FOUNDER_SETUP, the exact commands the founder runs.

Download: YouTube's Terms of Service forbid downloading except through YouTube's own features, even for CC videos.
resolve()/fetch() therefore only touch youtube.com when `media.youtube_download: true` (default false; env
REEL_DIRECTOR_YOUTUBE_DOWNLOAD=1). fetch() is CC-BY only (re-verified from yt-dlp's metadata before any media byte
is fetched), shows TOS_WARNING, records the attribution in the cache sidecar and logs every attempt (ok or failed)
as one JSON line in <cache>/logs/youtube_downloads.jsonl.
"""
from __future__ import annotations

import html
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import license as lic
from ..base import Candidate, Provider, ProviderError, setting, which
from ..cache import MediaCache

log = logging.getLogger(__name__)

PROVIDER = "youtube_cc"
API = "https://www.googleapis.com/youtube/v3"
LICENSE = lic.normalize("CC-BY-3.0")      # YouTube's "Creative Commons Attribution license (reuse allowed)"
DEFAULT_QUOTA_PROJECT = None   # adc mode: media.youtube_quota_project / REEL_DIRECTOR_YOUTUBE_QUOTA_PROJECT
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
_VID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ISO = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")
_TRUE = {"1", "true", "yes", "on"}

TOS_WARNING = (
    "YouTube's Terms of Service forbid downloading videos except through YouTube's own features, even when a video "
    "is Creative-Commons licensed. Reel Director only downloads YouTube CC-BY videos because you turned on "
    "media.youtube_download; you accept that risk. Each clip is credited (CC BY 3.0) in the reel's credits file.")

FOUNDER_SETUP = f"""YouTube CC discovery needs a credential the YouTube Data API v3 accepts: enable the API in a Google
Cloud project of yours (gcloud tokens carry only the cloud-platform scope, so the API answers 403
ACCESS_TOKEN_SCOPE_INSUFFICIENT without one of the options below). Option A (recommended), an API key restricted to
the YouTube Data API:
  gcloud services enable youtube.googleapis.com apikeys.googleapis.com --project PROJECT_ID
  gcloud services api-keys create --project PROJECT_ID \\
      --display-name="reel-director youtube-cc search" --api-target=service=youtube.googleapis.com
  gcloud services api-keys get-key-string KEY_ID --project PROJECT_ID   # KEY_ID from the create output
  export YOUTUBE_API_KEY=...   # e.g. in ~/.zshrc; never commit it
Option B, re-login application-default credentials with the YouTube read-only scope (keeps cloud-platform for Veo):
  gcloud auth application-default login \\
      --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/cloud-platform,{YOUTUBE_SCOPE}
  export REEL_DIRECTOR_YOUTUBE_AUTH=adc REEL_DIRECTOR_YOUTUBE_QUOTA_PROJECT=PROJECT_ID
  (if Google answers "This app is blocked" for the gcloud client, add --client-id-file=<a Desktop OAuth client JSON
  from the project's Credentials page>; Option A avoids that.)"""

Runner = Callable[..., subprocess.CompletedProcess]


class YouTubeError(ProviderError):
    """Base error of this provider (a ProviderError: the resolver notes it and tries the next source)."""


class YouTubeAuthError(YouTubeError):
    """The API rejected the credential (bad key, missing scope, API disabled)."""


class YouTubeQuotaError(YouTubeError):
    """Daily quota exhausted (search.list costs 100 of 10,000 units)."""


class YouTubeDownloadDisabled(YouTubeError):
    """fetch() called while media.youtube_download is off (the default)."""


class YouTubeLicenseError(YouTubeError):
    """The video is not CC-BY according to yt-dlp's metadata: never downloaded."""


def iso8601_seconds(text: str) -> float:
    """'PT1M5S' -> 65.0; 'P0D' (live/upcoming) -> 0.0; raises ValueError on anything else."""
    m = _ISO.match(text or "")
    if not m or text in ("P", "PT"):
        raise ValueError(f"not an ISO-8601 duration: {text!r}")
    d, h, mi, s = (float(g) if g else 0.0 for g in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def is_cc_by(license_text: str | None) -> bool:
    """True only for plain Creative Commons Attribution (license.normalize family 'cc-by': no NC / ND / SA)."""
    return bool(license_text) and lic.normalize(license_text).family == "cc-by"


def video_id(candidate_or_id: Any) -> str:
    """Video id from a Candidate (id 'youtube_cc:<vid>' or a watch URL) or a bare id; validated (11 safe chars)."""
    is_str = isinstance(candidate_or_id, str)
    raw = candidate_or_id if is_str else (getattr(candidate_or_id, "id", "") or "")
    raw = raw.split(":", 1)[1] if raw.startswith(PROVIDER + ":") else raw
    if not _VID.match(raw):
        url = raw if is_str else (getattr(candidate_or_id, "url", "") or "")
        raw = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("v", [""])[0]
    if not _VID.match(raw):
        raise YouTubeError(f"invalid YouTube video id: {raw!r}")
    return raw


def watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def attribution(title: str, channel: str, vid: str) -> str:
    return lic.attribution(title, channel, watch_url(vid), LICENSE, source="YouTube")


def _flag(v: Any) -> bool:
    return v is True or str(v).strip().lower() in _TRUE


class YouTubeCC(Provider):
    """search() -> [Candidate] (free, quota-metered); resolve()/fetch() opt-in (ToS), fetch is CC-BY only."""

    name = PROVIDER
    label = "YouTube (Creative Commons)"
    kinds = ("video",)
    paid = False
    key_name = "youtube_cc_key"
    key_env = ("YOUTUBE_API_KEY", "REEL_DIRECTOR_YOUTUBE_API_KEY")
    signup = "see FOUNDER_SETUP (gcloud services api-keys create ... in your Google Cloud project)"

    def __init__(self, *, key: str | None = None, http=None, cache=None, settings: Mapping | None = None,
                 auth: str | None = None, quota_project: str | None = DEFAULT_QUOTA_PROJECT, download: bool = False,
                 cache_dir: Path | str | None = None, run: Runner | None = None, ytdlp: str | None = None,
                 ffmpeg: str | None = None, max_source_seconds: float = 1200):
        super().__init__(key=key, http=http, cache=cache or (MediaCache(cache_dir) if cache_dir else None),
                         settings=settings)
        self.auth = (str(auth or "")).lower() or None
        self.quota_project = quota_project or DEFAULT_QUOTA_PROJECT or None
        self.download = bool(download)
        self.run = run or subprocess.run
        self.ytdlp = ytdlp or which("yt-dlp")
        self.ffmpeg = ffmpeg or which("ffmpeg")
        self.max_source_seconds = float(max_source_seconds)
        self.quota_used = 0

    @classmethod
    def from_settings(cls, settings: Mapping | None = None, env: Mapping[str, str] | None = None, **kw):
        """env wins over settings["media"]: youtube_cc_key (alias youtube_api_key), youtube_auth, youtube_download
        (default false), youtube_quota_project."""
        key = kw.pop("key", None) or setting(settings, cls.key_name, cls.key_env, env) \
            or setting(settings, "youtube_api_key", (), env)
        kw.setdefault("auth", setting(settings, "youtube_auth", ("REEL_DIRECTOR_YOUTUBE_AUTH",), env))
        kw.setdefault("download", _flag(setting(settings, "youtube_download", ("REEL_DIRECTOR_YOUTUBE_DOWNLOAD",),
                                                env)))
        kw.setdefault("quota_project", setting(settings, "youtube_quota_project",
                                               ("REEL_DIRECTOR_YOUTUBE_QUOTA_PROJECT",), env))
        return cls(key=key, settings=settings, **kw)

    # ---- status ---------------------------------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(self.key) or self.auth == "adc"

    def status(self) -> dict:
        """Studio/CLI summary: is discovery active, is downloading on (+ the ToS warning), what to set up."""
        return {**super().status(), "auth": "api_key" if self.key else self.auth, "download": self.download,
                "license": LICENSE.id, "quota_used": self.quota_used,
                "tos_warning": TOS_WARNING if self.download else None,
                "setup": None if self.available else FOUNDER_SETUP}

    # ---- discovery ------------------------------------------------------------------------------------------
    def _headers(self) -> dict:
        if self.key:
            return {}
        out = self.run(["gcloud", "auth", "application-default", "print-access-token"],
                       capture_output=True, text=True, timeout=30)
        token = (out.stdout or "").strip()
        if out.returncode or not token:
            raise YouTubeAuthError("gcloud application-default token unavailable.\n" + FOUNDER_SETUP)
        return {"Authorization": f"Bearer {token}",
                **({"x-goog-user-project": self.quota_project} if self.quota_project else {})}

    def _api(self, method: str, params: dict, cost: int) -> dict:
        q = dict(params, key=self.key) if self.key else dict(params)
        try:
            body = self.http.get_json(f"{API}/{method}", q, self._headers())
        except YouTubeError:
            raise
        except ProviderError as e:                   # base.Http: "HTTP 403 for <redacted url>: <body[:200]>"
            msg = str(e)
            if re.search(r"quota|rateLimitExceeded|dailyLimitExceeded", msg):
                raise YouTubeQuotaError(msg) from None
            if re.match(r"HTTP (400|401|403)\b", msg):
                raise YouTubeAuthError(msg + "\n" + FOUNDER_SETUP) from None
            raise
        if isinstance(body, dict) and body.get("error"):
            raise YouTubeError(f"YouTube API {method}: {str(body['error'])[:300]}")
        self.quota_used += cost
        return body

    def search(self, query: str, kind: str = "video", min_short_side: int = 1080,
               duration: tuple[float, float] = (2.0, 10.0), orientation: str | None = None,
               limit: int = 20, video_durations: Sequence[str] = ("short", "medium")) -> list[Candidate]:
        """CC-licensed YouTube videos for `query`, in API relevance order (stable for a recorded response).

        `duration` is the B-roll insert length: sources shorter than its minimum are dropped (select.py cuts the
        best segment from longer ones). w/h are the lower bound YouTube guarantees for the definition (hd >= 720p);
        resolve() reads the real size. `orientation` cannot be filtered by the API (select.py crops)."""
        if kind not in self.kinds or not (query or "").strip() or not self.available:
            return []
        out: list[Candidate] = []
        seen: set[str] = set()
        for vd in video_durations:
            params = {"part": "snippet", "q": query.strip(), "type": "video", "videoLicense": "creativeCommon",
                      "order": "relevance", "safeSearch": "strict", "videoDuration": vd,
                      "maxResults": max(1, min(50, limit * 2))}
            if min_short_side >= 720:
                params["videoDefinition"] = "high"
            ids = [it["id"]["videoId"] for it in self._api("search", params, 100).get("items", [])
                   if isinstance(it.get("id"), dict) and _VID.match(it["id"].get("videoId", ""))]
            ids = [i for i in ids if i not in seen]
            seen.update(ids)
            if ids:
                out += self._details(ids, duration)
            if len(out) >= limit:
                break
        return out[:limit]

    def _details(self, ids: list[str], duration: tuple[float, float]) -> list[Candidate]:
        body = self._api("videos", {"part": "snippet,contentDetails,status", "id": ",".join(ids),
                                    "maxResults": len(ids)}, 1)
        by_id = {it.get("id"): it for it in body.get("items", [])}
        out = []
        for vid in ids:                              # keep search (relevance) order
            it = by_id.get(vid)
            if not it:
                continue
            sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("status", {})
            if st.get("license") != "creativeCommon" or sn.get("liveBroadcastContent", "none") != "none":
                continue
            if cd.get("projection", "rectangular") != "rectangular":
                continue
            try:
                secs = iso8601_seconds(cd.get("duration", ""))
            except ValueError:
                continue
            if secs < float(duration[0]):
                continue
            hd = cd.get("definition") == "hd"
            thumbs = sn.get("thumbnails", {})
            thumb = next((thumbs[k]["url"] for k in ("maxres", "standard", "high", "medium", "default")
                          if k in thumbs), "")
            title = html.unescape(sn.get("title") or vid)
            channel = html.unescape(sn.get("channelTitle") or "unknown channel")
            out.append(Candidate(
                id=f"{PROVIDER}:{vid}", provider=PROVIDER, kind="video", title=title, url=watch_url(vid),
                thumb=thumb, w=1280 if hd else 640, h=720 if hd else 360, duration=secs, license=LICENSE.id,
                attribution=attribution(title, channel, vid), source_page=watch_url(vid), cost_usd=0.0,
                creator=channel, tags=tuple(sn.get("tags") or ())[:12],
                extra={"video_id": vid, "definition": cd.get("definition", ""), "channel_id": sn.get("channelId", ""),
                       "published_at": sn.get("publishedAt", ""), "size_verified": False,
                       "description": html.unescape(sn.get("description") or "")[:300]}))
        return out

    # ---- yt-dlp (opt-in, ToS) -------------------------------------------------------------------------------
    def _ytdlp(self, args: list[str], timeout: int) -> subprocess.CompletedProcess:
        return self.run([self.ytdlp, "--ignore-config", "--no-playlist", "--no-update", "--no-progress", *args],
                        capture_output=True, text=True, timeout=timeout)

    def probe(self, candidate: Any) -> dict:
        """yt-dlp metadata (no media bytes): license text, channel, title, best width/height, duration."""
        vid = video_id(candidate)
        out = self._ytdlp(["-J", "--skip-download", "--", watch_url(vid)], 120)
        if out.returncode:
            raise YouTubeError(f"yt-dlp metadata failed for {vid}: {(out.stderr or '').strip()[-400:]}")
        meta = json.loads(out.stdout)
        return {"id": vid, "title": meta.get("title") or "", "channel": meta.get("channel") or meta.get("uploader"),
                "license_text": meta.get("license"), "duration": meta.get("duration"),
                "w": meta.get("width") or 0, "h": meta.get("height") or 0}

    def resolve(self, c: Candidate, max_height: int = 1080) -> Candidate:
        """Real size + verified license for a shortlisted candidate. Only with downloads on (it scrapes the watch
        page); with downloads off no network is touched and the candidate comes back marked `rejected` (select.pick
        drops it from the shortlist: it could never be fetched). Not CC BY per yt-dlp -> rejected too. The size is
        what fetch(max_height) will deliver."""
        if not self.download:
            why = "YouTube downloads are off (media.youtube_download: false)"
            return Candidate(**{**c.to_dict(), "tags": c.tags, "extra": {**c.extra, "rejected": why}})
        m = self.probe(c)
        w, h = int(m["w"]), int(m["h"])
        if w and h and min(w, h) > max_height:
            k = max_height / min(w, h)
            w, h = int(round(w * k / 2) * 2), int(round(h * k / 2) * 2)
        ok = is_cc_by(m["license_text"])
        extra = {**c.extra, "license_text": m["license_text"], "license_verified": ok, "size_verified": bool(w),
                 "source_w": m["w"], "source_h": m["h"]}
        if not ok:
            extra["rejected"] = f"not CC BY according to YouTube ({m['license_text']!r})"
        return Candidate(**{**c.to_dict(), "w": w or c.w, "h": h or c.h, "license": LICENSE.id if ok else "unknown",
                            "duration": float(m["duration"] or c.duration), "tags": c.tags, "extra": extra})

    @staticmethod
    def _log(root: Path, record: dict) -> None:
        """One JSON line per download attempt (ok or failed): the audit trail the contract asks for."""
        logf = root / "logs" / "youtube_downloads.jsonl"
        logf.parent.mkdir(parents=True, exist_ok=True)
        with logf.open("a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "provider": PROVIDER,
                                "tos_acknowledged": True, **record}) + "\n")

    def _trim(self, src: Path, segment: tuple[float, float], dst: Path, with_audio: bool) -> Path:
        """Frame-accurate cut [a, b) re-encoded to H.264 with bit-exact flags (same input -> same bytes)."""
        a, b = (float(x) for x in segment)
        audio = ["-c:a", "aac", "-b:a", "128k"] if with_audio else ["-an"]
        cmd = [self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-i", str(src),
               "-t", f"{b - a:.3f}", "-map", "0:v:0", *(["-map", "0:a:0?"] if with_audio else []),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", *audio,
               "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
               "-movflags", "+faststart", str(dst)]
        res = self.run(cmd, capture_output=True, text=True, timeout=600)
        if res.returncode or not dst.is_file():
            raise YouTubeError(f"ffmpeg trim failed: {(res.stderr or '').strip()[-400:]}")
        return dst

    def fetch(self, c: Any, segment: tuple[float, float] | None = None, approved: bool = False, *,
              max_height: int = 1080, with_audio: bool = False) -> Path:
        """Download (a segment of) a CC-BY video into the content-addressed cache and return the local file.
        Refuses unless media.youtube_download is on and yt-dlp's metadata says CC BY. Free: `approved` unused."""
        if not self.download:
            raise YouTubeDownloadDisabled(
                "YouTube downloads are off (media.youtube_download: false). " + TOS_WARNING +
                " To opt in, set media.youtube_download: true or REEL_DIRECTOR_YOUTUBE_DOWNLOAD=1.")
        vid = video_id(c)
        if segment is not None and not 0 <= float(segment[0]) < float(segment[1]):
            raise YouTubeError(f"invalid segment {segment!r}")
        seg = [round(float(x), 3) for x in segment] if segment else None
        key = f"{PROVIDER}:{vid}#{seg[0]:.3f}-{seg[1]:.3f}" if seg else f"{PROVIDER}:{vid}#full"
        key += f"@{int(max_height)}" + ("+audio" if with_audio else "")
        if hit := self.cache.lookup(key):                # same request -> same file, no network
            return hit
        root = self.cache.root
        log.warning("%s", TOS_WARNING)
        print(f"WARNING (youtube_cc): {TOS_WARNING}", file=sys.stderr)
        meta = self.probe(vid)
        if not is_cc_by(meta["license_text"]):
            raise YouTubeLicenseError(f"{vid}: license {meta['license_text']!r} is not CC BY; not downloading")
        if (meta["duration"] or 0) > self.max_source_seconds:
            raise YouTubeError(f"{vid}: source is {meta['duration']} s (> {self.max_source_seconds:g} s); "
                               "pick a shorter source for B-roll")
        h = int(max_height)
        v = f"bv*[height<={h}][vcodec^=avc1][ext=mp4]/bv*[height<={h}][ext=mp4]/bv*[height<={h}]"
        fmt = f"{v.replace('/', '+ba/')}+ba/b[height<={h}]" if with_audio else f"{v}/b[height<={h}]"
        (root / "tmp").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / "tmp", prefix="yt-") as tmp:
            # Native download of the whole stream at <= max_height, then a local frame-accurate trim: yt-dlp's
            # --download-sections streams through ffmpeg, which YouTube answered with 403 (2026-10-20).
            dl = Path(tmp) / "dl"
            dl.mkdir()
            res = self._ytdlp(["-f", fmt, "--merge-output-format", "mp4", "-o", str(dl / f"{vid}.%(ext)s"),
                               "--", watch_url(vid)], 1800)
            files = sorted(p for p in dl.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl")))
            if res.returncode or not files:
                err = (res.stderr or "").strip()[-400:]
                hint = (" YouTube refused the stream (HTTP 403): update yt-dlp (`brew upgrade yt-dlp`) and retry."
                        if "403" in err else "")
                self._log(root, {"status": "failed", "video_id": vid, "license_text": meta["license_text"],
                                 "segment": seg, "error": err})
                raise YouTubeError(f"yt-dlp download failed for {vid}: {err}{hint}")
            src = self._trim(files[0], segment, Path(tmp) / f"{vid}.mp4", with_audio) if segment else files[0]
            title, channel = meta["title"] or vid, meta["channel"] or "unknown channel"
            cand = c if isinstance(c, Candidate) else Candidate(
                id=f"{PROVIDER}:{vid}", provider=PROVIDER, kind="video", title=title, url=watch_url(vid))
            sidecar = {**self.sidecar(cand), "id": f"{PROVIDER}:{vid}", "video_id": vid, "title": title,
                       "creator": channel, "license": LICENSE.id, "license_text": meta["license_text"],
                       "attribution": attribution(title, channel, vid), "source_page": watch_url(vid),
                       "segment": seg, "max_height": h, "with_audio": bool(with_audio), "cost_usd": 0.0,
                       "tos_warning": TOS_WARNING}
            dest = self.cache.put(src, key, sidecar, ext=src.suffix.lower() or ".mp4")   # webm stays webm
        self._log(root, {"status": "ok", **{k: sidecar[k] for k in ("video_id", "license_text", "segment",
                                                                   "attribution")},
                         "sha256": dest.stem, "bytes": dest.stat().st_size, "path": str(dest)})
        log.info("youtube_cc: downloaded %s (%s) -> %s", vid, meta["license_text"], dest)
        return dest


YouTubeCCProvider = YouTubeCC          # name used in the contract notes


def provider(settings: Mapping | None = None, **kw) -> YouTubeCC:
    """Factory the registry (providers/__init__.py) calls."""
    return YouTubeCC.from_settings(settings, **kw)
