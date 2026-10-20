"""Higgsfield: paid text-to-video and image-to-video B-roll (Seedance 2.0, Kling 3.0) through the Higgsfield API.

How Higgsfield is reachable on this Mac (inspected read-only 2026-10-20):
  * ~/.claude.json lists only "claude.ai Higgsfield" under claudeAiMcpEverConnected: an OAuth connector managed by
    claude.ai (official server https://mcp.higgsfield.ai/mcp). Its token never lands on disk, `claude mcp list` does
    not show it, so a headless Python client cannot use it.
  * the higgsfield-image-auto / seedance-auto-generate skills drive the higgsfield.ai web UI with Playwright and the
    subscription's credits (models soul-v2, seedance_2_0; 9:16; 720p/1080p; 5/8/10 s; confirm before Generate).
    `image-to-video` is a RunComfy router, not Higgsfield.
  * the developer API (docs.higgsfield.ai, SDK higgsfield-ai/higgsfield-client) is what this client speaks:
    POST https://api.higgsfield.ai/<model path> -> {request_id, status_url, cancel_url, status}
    GET  /requests/<id>/status -> status queued|in_progress|completed|failed|nsfw|canceled, video.url
    POST /estimate/<model path> (same body) -> {credits, usd}   free price check
    POST /files/generate-upload-url {content_type} -> {public_url, upload_url, upload_headers}; PUT the bytes
    auth: `Authorization: Key <key_id>:<key_secret>` (see credential()). API billing is a prepaid USD balance,
    separate from the web subscription. failed / nsfw / canceled requests are not charged. Re-checked 2026-10-20
    against docs.higgsfield.ai/llms-full.txt; api.higgsfield.ai answers 401 "Invalid credentials" without a key.
Money: identical gate to Veo (budget.run_paid). search() quotes using the free estimate endpoint; fetch() refuses
without an approved quote, submits once with `Idempotency-Key: rd-<request_id>` (a retried submit can't charge
twice), polls, downloads the video WITHOUT sending the API key to the CDN, caches it (MediaCache key
"higgsfield:<request_id>") and settles the ledger. Without a key the provider is not `available` and search()
returns nothing (a clip with no price can't be approved).
"""
from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import os
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..base import Candidate
from ..budget import Budget, GenerationFailed, GenerationTimeout, SubmitRejected, run_paid
from ..cache import MediaCache
from .veo import (DIMS, LICENSE, budget_summary, cache_bytes, candidate_request_id, http_bytes, http_json,
                  paid_candidate)

PROVIDER = "higgsfield"
API = "https://api.higgsfield.ai"
DONE = {"completed", "failed", "nsfw", "canceled"}
SETUP = """Higgsfield generation from Reel Director needs a Higgsfield API key (the claude.ai connector and the web
subscription can't be used headlessly). Founder steps:
  1. https://cloud.higgsfield.ai -> API keys -> create a key; add prepaid USD balance (API billing is separate).
  2. export HF_KEY="<key_id>:<key_secret>"     # or HF_API_KEY_ID + HF_API_KEY_SECRET; never commit it
  3. python -m reel_director.media.providers.higgsfield estimate   # free price check, proves the key
Paid generation still needs: python -m reel_director.media.budget approve <request_id>"""


class HiggsfieldError(RuntimeError):
    pass


@dataclass(frozen=True)
class HFModel:
    image: bool                         # image-to-video (needs image_url)
    seconds: tuple[int, int]            # inclusive range
    resolutions: tuple[str, ...]        # empty: the model has no resolution field
    aspects: tuple[str, ...]            # empty: output follows the input image
    audio_key: str
    audio_values: tuple[Any, Any]       # (off, on)


_SEED_RES, _SEED_AR = ("480p", "720p", "1080p", "4k"), ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9")
MODELS: dict[str, HFModel] = {
    "bytedance/seedance-2.0/text-to-video": HFModel(False, (4, 15), _SEED_RES, _SEED_AR, "generate_audio", (False, True)),
    "bytedance/seedance-2.0/image-to-video": HFModel(True, (4, 15), _SEED_RES, (), "generate_audio", (False, True)),
    "kling-video/v3.0/std/text-to-video": HFModel(False, (3, 15), (), ("16:9", "9:16", "1:1"), "sound", ("off", "on")),
    "kling-video/v3.0/std/image-to-video": HFModel(True, (3, 15), (), (), "sound", ("off", "on")),
}
DEFAULT_T2V = "bytedance/seedance-2.0/text-to-video"
DEFAULT_I2V = "bytedance/seedance-2.0/image-to-video"


def credential(settings: Mapping | None = None, env: Mapping[str, str] | None = None) -> str | None:
    """"<key_id>:<key_secret>" from the env names docs.higgsfield.ai uses (Python SDK HF_KEY, JS SDK HF_CREDENTIALS,
    curl HF_API_KEY_ID + HF_API_KEY_SECRET; HF_API_KEY + HF_API_SECRET too), then settings media.higgsfield_key."""
    env = os.environ if env is None else env
    for one in ("HF_KEY", "HF_CREDENTIALS"):
        if env.get(one):
            return env[one]
    for kid, sec in (("HF_API_KEY_ID", "HF_API_KEY_SECRET"), ("HF_API_KEY", "HF_API_SECRET")):
        if env.get(kid) and env.get(sec):
            return f"{env[kid]}:{env[sec]}"
    return ((settings or {}).get("media") or {}).get("higgsfield_key") or None


def make_spec(prompt: str, *, model: str | None = None, seconds: float = 4, w: int = 1080, h: int = 1920,
              resolution: str | None = None, audio: bool = False, image: Path | str | None = None,
              attempt: int = 0) -> dict:
    model = model or (DEFAULT_I2V if image else DEFAULT_T2V)
    m = MODELS.get(model)
    if m is None:
        raise HiggsfieldError(f"unknown Higgsfield model {model!r}; known: {sorted(MODELS)}")
    if not prompt.strip():
        raise HiggsfieldError("empty prompt")
    if m.image != bool(image):
        raise HiggsfieldError(f"{model} {'needs' if m.image else 'does not take'} an input image")
    portrait = h >= w
    spec: dict[str, Any] = {"prompt": prompt.strip(), "model": model, "attempt": int(attempt), "audio": bool(audio),
                            "seconds": int(min(max(math.ceil(seconds - 1e-9), m.seconds[0]), m.seconds[1]))}
    if m.resolutions:
        spec["resolution"] = resolution or ("720p" if min(w, h) <= 720 else "1080p")
        if spec["resolution"] not in m.resolutions:
            raise HiggsfieldError(f"{model} offers {m.resolutions}, not {spec['resolution']}")
    if m.aspects:
        spec["aspect"] = "9:16" if portrait else "16:9"
    short, long_ = DIMS.get(spec.get("resolution", "720p"), DIMS["720p"])
    spec["w"], spec["h"] = (short, long_) if portrait else (long_, short)
    if image:
        p = Path(image).expanduser()
        spec.update(image=str(p), image_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                    image_mime=mimetypes.guess_type(p.name)[0] or "image/png")
    return spec


def build_args(spec: Mapping[str, Any], image_url: str | None = None) -> dict:
    """The model's JSON body (docs.higgsfield.ai model pages). One clip per request."""
    m = MODELS[spec["model"]]
    args: dict[str, Any] = {"prompt": spec["prompt"], "duration": int(spec["seconds"]),
                            m.audio_key: m.audio_values[1 if spec["audio"] else 0]}
    if m.resolutions:
        args["resolution"] = spec["resolution"]
    if m.aspects:
        args["aspect_ratio"] = spec["aspect"]
    if m.image:
        if not image_url:
            raise HiggsfieldError("image-to-video needs the uploaded image URL")
        args["image_url"] = image_url
    return args


class HiggsfieldProvider:
    name = PROVIDER
    paid = True

    def __init__(self, *, key: str | None = None, budget: Budget | None = None, cache: MediaCache | None = None,
                 http: Callable[..., Any] | None = None, fetch_bytes: Callable[..., bytes] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 poll_timeout: float = 900.0, api: str = API):
        self.key, self.api = key, api.rstrip("/")
        self.budget = budget or Budget()
        self._cache = cache
        self.http, self.fetch_bytes = http or http_json, fetch_bytes or http_bytes
        self.sleep, self.clock, self.poll_timeout = sleep, clock, float(poll_timeout)
        self._uploads: dict[str, str] = {}

    @classmethod
    def from_settings(cls, settings: Mapping | None = None, env: Mapping[str, str] | None = None, **kw):
        kw.setdefault("budget", Budget.from_settings(settings, env))
        return cls(key=credential(settings, env), **kw)

    @property
    def cache(self) -> MediaCache:
        if self._cache is None:
            self._cache = MediaCache()
        return self._cache

    @property
    def available(self) -> bool:
        return bool(self.key)

    def status(self) -> dict:
        return {"provider": PROVIDER, "paid": True, "available": self.available, "kinds": ["video"], "api": self.api,
                "models": sorted(MODELS), "price_basis": "POST /estimate/<model> (per request, USD)",
                "budget": budget_summary(self.budget), "setup": None if self.available else SETUP}

    def _headers(self) -> dict:
        if not self.key:
            raise HiggsfieldError(SETUP)
        return {"Authorization": f"Key {self.key}", "Accept": "application/json"}

    def _call(self, method: str, path: str, body: Any = None, extra: Mapping[str, str] | None = None):
        return self.http(method, f"{self.api}/{path.lstrip('/')}", {**self._headers(), **(extra or {})}, body)

    def _upload(self, spec: Mapping[str, Any]) -> str:
        """Free storage upload of the input image (only for image-to-video); re-checked against the quoted hash."""
        raw = Path(spec["image"]).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != spec["image_sha256"]:
            raise HiggsfieldError(f"{spec['image']} changed since it was quoted/approved; quote it again")
        if sha in self._uploads:
            return self._uploads[sha]
        code, r = self._call("POST", "/files/generate-upload-url", {"content_type": spec["image_mime"]})
        if code >= 300 or not str(r.get("upload_url", "")).startswith("https://"):
            raise HiggsfieldError(f"upload URL request HTTP {code}: {json.dumps(r)[:300]}")
        code, _ = self.http("PUT", r["upload_url"], r.get("upload_headers") or {"Content-Type": spec["image_mime"]}, raw)
        if code >= 300:
            raise HiggsfieldError(f"image upload HTTP {code}")
        self._uploads[sha] = r["public_url"]
        return r["public_url"]

    # ---- quote (free) --------------------------------------------------------------------------------------
    def estimate(self, spec: Mapping[str, Any]) -> dict | None:
        """Free price check. None without a key (the quote then can't be approved). Image-to-video uploads the
        input image first (free storage, needed because image_url is a required field of the priced body)."""
        if not self.available:
            return None
        args = build_args(spec, self._upload(spec) if spec.get("image") else None)
        code, r = self._call("POST", f"/estimate/{spec['model']}", args)
        if code != 200 or "usd" not in r:
            raise HiggsfieldError(f"estimate HTTP {code}: {json.dumps(r)[:300]}")
        return {"usd": float(r["usd"]), "credits": r.get("credits")}

    def quote(self, prompt: str, *, reel: str, clip: str, **spec_kw):
        spec = make_spec(prompt, **spec_kw)
        est = self.estimate(spec)
        basis = (f"Higgsfield /estimate: {est['credits']} credits = ${est['usd']}" if est
                 else "no Higgsfield API key: price unknown")
        return self.budget.quote(PROVIDER, spec["model"], spec, usd=est["usd"] if est else None,
                                 seconds=spec["seconds"], reel=reel, clip=clip, basis=basis)

    def search(self, query: str, kind: str = "video", min_short_side: int = 1080,
               duration: tuple[float, float] = (2, 10), orientation: str | None = None, limit: int = 20, *,
               reel: str = "", clip: str = "", image: Path | str | None = None, **spec_kw) -> list[Candidate]:
        if kind != "video" or not self.available:
            return []
        w, h = (1920, 1080) if orientation == "landscape" else (1080, 1920)
        spec_kw.setdefault("resolution", "720p" if min_short_side <= 720 else "1080p")
        if not MODELS[spec_kw.get("model") or (DEFAULT_I2V if image else DEFAULT_T2V)].resolutions:
            spec_kw["resolution"] = None
        q = self.quote(query, reel=reel, clip=clip or query, seconds=max(duration[0], 1), w=w, h=h, image=image,
                       **spec_kw)
        return [self.candidate(q)]

    def resolve(self, c: Candidate) -> Candidate:
        return c                                               # a quote is already complete

    @staticmethod
    def candidate(q) -> Candidate:
        return paid_candidate(q, f"AI-generated with Higgsfield ({q.model})")

    # ---- paid path (approval-gated) ------------------------------------------------------------------------
    def fetch(self, candidate: Any, segment: tuple[float, float] | None = None, approved: bool = False) -> Path:
        """Same contract as VeoProvider.fetch: whole clip, ledger approval (or approved=True within the caps)."""
        rid = candidate_request_id(candidate)
        hit = self.cache.lookup(f"{PROVIDER}:{rid}")
        if hit:
            return hit
        q = self.budget.get(rid)
        spec = q.spec

        def submit() -> str:
            args = build_args(spec, self._upload(spec) if spec.get("image") else None)
            code, r = self._call("POST", f"/{spec['model']}", args, {"Idempotency-Key": f"rd-{rid}"})
            if 400 <= code < 500:
                raise SubmitRejected(f"Higgsfield refused the request (HTTP {code}): {json.dumps(r)[:400]}")
            if code >= 300 or not r.get("request_id"):
                raise HiggsfieldError(f"Higgsfield submit HTTP {code} without a request_id: {json.dumps(r)[:300]}")
            return str(r["request_id"])

        def finish(r: dict) -> Path:
            url = ((r.get("video") or {}).get("url")) or ""
            if urllib.parse.urlsplit(url).scheme != "https":
                raise HiggsfieldError(f"completed without an https video URL: {json.dumps(r)[:200]}")
            data = self.fetch_bytes(url, {})                   # CDN download: never send the API key here
            side = {**self.candidate(q).to_dict(), "request_id": rid, "prompt": spec["prompt"],
                    "spec": {k: v for k, v in spec.items() if k != "prompt"}, "hf_request_id": r.get("request_id")}
            ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
            return cache_bytes(self.cache, data, ext if ext in (".mp4", ".mov", ".webm") else ".mp4",
                               f"{PROVIDER}:{rid}", side)

        return run_paid(self.budget, rid, submit=submit, wait=self._wait, finish=finish,
                        approved_by="studio (approved=True)" if approved else None)

    def _wait(self, request_id: str) -> dict:
        deadline, delay = self.clock() + self.poll_timeout, 2.0
        path = f"/requests/{urllib.parse.quote(request_id, safe='')}/status"
        while True:
            code, r = self._call("GET", path)
            st = r.get("status") if code == 200 else None
            if st == "completed":
                return r
            if st in DONE:                                     # failed / nsfw / canceled: refunded per the docs
                raise GenerationFailed(f"Higgsfield request {request_id} ended {st}: {r.get('error') or ''}".strip(),
                                       outcome="filtered" if st == "nsfw" else st, charged=False)
            if code != 200 and code != 429 and code < 500:
                raise HiggsfieldError(f"status HTTP {code}: {json.dumps(r)[:300]}")
            if self.clock() + delay > deadline:
                raise GenerationTimeout(f"Higgsfield request {request_id} not done after {self.poll_timeout:.0f}s; "
                                        "fetch again later to resume (not resubmitted)")
            self.sleep(delay)
            delay = min(delay * 1.5, 10.0)


def provider(settings: Mapping | None = None, **kw) -> HiggsfieldProvider:
    return HiggsfieldProvider.from_settings(settings, **kw)


if __name__ == "__main__":
    import sys
    p = HiggsfieldProvider.from_settings(None)
    if not p.available:
        print(SETUP, file=sys.stderr)
        sys.exit(2)
    words = [a for a in sys.argv[1:] if a != "estimate"]
    spec = make_spec(" ".join(words) or "slow push-in on a city skyline at dusk, no people, no text")
    print(json.dumps({"spec": spec, "estimate": p.estimate(spec)}, indent=2))
