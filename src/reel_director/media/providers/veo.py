"""Google Veo on Vertex AI: paid text-to-video and image-to-video B-roll (v4 media contract).

Project: REEL_DIRECTOR_VEO_PROJECT or settings media.veo.project, else the gcloud CLI's configured project; region
us-central1 (the only region with Veo quota buckets, and the only one the Veo 3.1 model pages list). Auth is your
gcloud login: `gcloud auth print-access-token` + `x-goog-user-project` (user credentials need a quota project;
nothing here changes cloud config). Verified 2026-10-20 with FREE reads only
(`probe`): aiplatform API enabled, billing enabled, caller holds aiplatform.endpoints.predict; the publisher catalog
lists veo-3.1-fast-generate-001 + veo-3.1-generate-001 (GA) and veo-3.1-lite-generate-001 (preview); veo-3.0-* and
veo-2.0 return 404 (RETIRED) although their quota buckets remain. Output is 24 fps (select.py normalizes to CFR 30).

Money: search() only QUOTES (ledger event, zero network). fetch() goes through budget.run_paid: it refuses unless
the creator approved that exact quote within the caps, submits ONE predictLongRunning request, records the job id,
polls fetchPredictOperation, takes the video inline (base64, default) or from GCS (when storage_uri is set), puts it
in the shared MediaCache under the key "veo:<request_id>" and settles the ledger. Prices: per generated second,
PRICE_BASIS below. License "original" (made for this reel) + extra.ai_generated, so credits and the AI-disclosure
step know it is synthetic (Veo output carries a SynthID watermark).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..base import Candidate
from ..budget import Budget, BudgetError, GenerationFailed, GenerationTimeout, SubmitRejected, run_paid
from ..cache import MediaCache

PROVIDER = "veo"
PROJECT = None          # REEL_DIRECTOR_VEO_PROJECT / settings media.veo.project, else gcloud's configured project
LOCATION = "us-central1"
DEFAULT_MODEL = "veo-3.1-fast-generate-001"
LICENSE = "original"    # made for this reel (license.py: allowed, no credit line); extra.ai_generated flags it as AI
PRICE_BASIS = "Cloud Billing Catalog, Vertex AI service C7E2-9256-1C43, USD per generated second, effective 2026-10-20"
ASPECTS = ("9:16", "16:9")
DIMS = {"720p": (720, 1280), "1080p": (1080, 1920), "4k": (2160, 3840)}
DEFAULT_NEGATIVE = "text, captions, subtitles, watermark, logo, distorted hands, distorted faces"
MAX_DOWNLOAD = 512 * 1024 * 1024
Http = Callable[..., "tuple[int, Any]"]


@dataclass(frozen=True)
class VeoModel:
    durations: tuple[int, ...]
    resolutions: tuple[str, ...]
    rates: Mapping[tuple[str, bool], float]     # (resolution, generate_audio) -> USD per second
    skus: str


_FAST = {("720p", False): 0.08, ("720p", True): 0.10, ("1080p", False): 0.10, ("1080p", True): 0.12,
         ("4k", False): 0.25, ("4k", True): 0.30}
_STD = {("720p", False): 0.20, ("720p", True): 0.40, ("1080p", False): 0.20, ("1080p", True): 0.40,
        ("4k", False): 0.40, ("4k", True): 0.60}
_FAST_SKU = "Veo 3 Fast: 7DE3-56E5-CE6C 720p, D679-F281-7C1A 1080p (+audio A9F8-76D1-003D / A0A5-329E-CDBE)"
_STD_SKU = "Veo 3: 4D50-275D-FC3F video, F64B-2A78-7BAE audio, EBB6-730E-171A 4k, A88E-25E5-8E63 4k audio"
MODELS: dict[str, VeoModel] = {      # durations / resolutions: Vertex AI "Veo 3.1" model page, 2026-10-20
    "veo-3.1-fast-generate-001": VeoModel((4, 6, 8), ("720p", "1080p"), _FAST, _FAST_SKU),
    "veo-3.1-generate-001": VeoModel((4, 6, 8), ("720p", "1080p", "4k"), _STD, _STD_SKU),
}
UNPRICED = {"veo-3.1-lite-generate-001": "public preview with no Vertex AI billing SKU yet, so it cannot be quoted"}
RETIRED = {m: "not in the Vertex AI publisher-model catalog (GET 404 on 2026-10-20); use veo-3.1-*" for m in (
    "veo-3.0-fast-generate-001", "veo-3.0-generate-001", "veo-2.0-generate-001")}

SETUP = f"""Veo needs the founder's gcloud login (already present on this Mac) and nothing else for a first clip:
  gcloud auth login            # only if `gcloud auth print-access-token` fails
  python -m reel_director.media.providers.veo probe     # free: models, quota region, permission check
Paid generation happens only after approving a quote (Studio, or the CLI):
  python -m reel_director.media.providers.veo quote "<prompt>" --reel <reel> --clip <slot>   # free, prints the id
  python -m reel_director.media.budget approve <request_id>
  python -m reel_director.media.providers.veo generate <request_id>                       # PAID, once
Optional GCS output (default is inline bytes, no bucket needed) also needs storage.objects.get on that bucket."""


class VeoError(RuntimeError):
    pass


# ---- shared plumbing (higgsfield.py reuses these) ----------------------------------------------------------------
def http_json(method: str, url: str, headers: Mapping[str, str] | None = None, body: Any = None,
              timeout: float = 120) -> tuple[int, Any]:
    """(status, parsed JSON | {'raw': text}). HTTP errors are returned, transport errors raise."""
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if body is not None and not isinstance(body, bytes):
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    try:
        return code, json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return code, {"raw": raw[:2000].decode("utf-8", "replace")}


def http_bytes(url: str, headers: Mapping[str, str] | None = None, timeout: float = 300,
               limit: int = MAX_DOWNLOAD) -> bytes:
    req = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise VeoError(f"download from {url[:80]} exceeds {limit} bytes")
    return data


def cache_bytes(cache: MediaCache, data: bytes, ext: str, key: str, meta: Mapping[str, Any]) -> Path:
    """Generated bytes -> the shared content-addressed cache (files/<aa>/<sha><ext> + sidecar), indexed by `key`."""
    if not data:
        raise VeoError("empty output")
    tmp_dir = cache.root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=tmp_dir, suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return cache.put(Path(name), key=key, meta={**meta, "ai_generated": True}, ext=ext)


def candidate_request_id(candidate: Any) -> str:
    cid = candidate if isinstance(candidate, str) else getattr(candidate, "id", None) or candidate["id"]
    return cid.split(":", 1)[1] if ":" in cid else cid


def frame_for(w: int, h: int, resolution: str | None = None) -> tuple[str, str, int, int]:
    """Reel slot (w x h) -> (aspectRatio, resolution, out_w, out_h). Square pip slots get 9:16 and are cropped."""
    portrait = h >= w
    res = resolution or ("720p" if min(w, h) <= 720 else "1080p")
    if res not in DIMS:
        raise VeoError(f"resolution {res!r} not in {sorted(DIMS)}")
    short, long_ = DIMS[res]
    return ("9:16" if portrait else "16:9", res, *((short, long_) if portrait else (long_, short)))


def snap_seconds(model: str, want: float) -> int:
    allowed = MODELS[model].durations
    return next((d for d in allowed if d >= want - 1e-9), allowed[-1])


def estimate(model: str, seconds: float, resolution: str = "1080p", audio: bool = False) -> dict:
    if model in UNPRICED or model in RETIRED:
        raise VeoError(f"{model}: {UNPRICED.get(model) or RETIRED[model]}")
    m = MODELS.get(model)
    if m is None:
        raise VeoError(f"unknown Veo model {model!r}; known: {sorted(MODELS)}")
    if resolution not in m.resolutions:
        raise VeoError(f"{model} does not offer {resolution} (has {m.resolutions})")
    if (resolution, audio) not in m.rates:
        raise VeoError(f"{model} cannot generate audio")
    if int(seconds) not in m.durations:
        raise VeoError(f"{model} makes {m.durations} second clips, not {seconds}")
    rate = m.rates[(resolution, audio)]
    return {"model": model, "seconds": int(seconds), "resolution": resolution, "audio": audio, "samples": 1,
            "usd_per_second": rate, "usd": round(rate * int(seconds), 4), "sku": m.skus, "basis": PRICE_BASIS}


def make_spec(prompt: str, *, model: str = DEFAULT_MODEL, seconds: float = 4, w: int = 1080, h: int = 1920,
              resolution: str | None = None, audio: bool = False, image: Path | str | None = None,
              negative_prompt: str = DEFAULT_NEGATIVE, person_generation: str = "dont_allow",
              seed: int | None = None, storage_uri: str | None = None, attempt: int = 0) -> dict:
    """Everything that defines (and prices) one generation; stored verbatim in the ledger quote."""
    if not prompt.strip():
        raise VeoError("empty prompt")
    aspect, res, out_w, out_h = frame_for(w, h, resolution)
    secs = snap_seconds(model, seconds) if model in MODELS else int(seconds)
    spec = {"prompt": prompt.strip(), "model": model, "seconds": secs, "aspect": aspect, "resolution": res,
            "w": out_w, "h": out_h, "audio": bool(audio), "negative_prompt": negative_prompt,
            "person_generation": person_generation, "attempt": int(attempt),
            "seed": int(seed) if seed is not None else int(hashlib.sha256(f"{model}|{prompt}".encode())
                                                              .hexdigest()[:8], 16)}
    if image:
        p = Path(image).expanduser()
        spec.update(image=str(p), image_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                    image_mime=mimetypes.guess_type(p.name)[0] or "image/png")
    if storage_uri:
        if not storage_uri.startswith("gs://"):
            raise VeoError("storage_uri must be gs://bucket/prefix/")
        spec["storage_uri"] = storage_uri
    return spec


def build_request(spec: Mapping[str, Any]) -> dict:
    """The exact predictLongRunning body (Vertex AI Veo API). sampleCount is pinned to 1: cost = 1 clip."""
    inst: dict[str, Any] = {"prompt": spec["prompt"]}
    if spec.get("image"):
        raw = Path(spec["image"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["image_sha256"]:
            raise VeoError(f"{spec['image']} changed since it was quoted/approved; quote it again")
        inst["image"] = {"bytesBase64Encoded": base64.b64encode(raw).decode(), "mimeType": spec["image_mime"]}
    params: dict[str, Any] = {"aspectRatio": spec["aspect"], "durationSeconds": int(spec["seconds"]),
                              "sampleCount": 1, "personGeneration": spec["person_generation"],
                              "seed": int(spec["seed"]), "resolution": spec["resolution"],
                              "generateAudio": bool(spec["audio"])}
    if spec.get("negative_prompt"):
        params["negativePrompt"] = spec["negative_prompt"]
    if spec.get("storage_uri"):
        params["storageUri"] = spec["storage_uri"]
    return {"instances": [inst], "parameters": params}


def gcloud_project(run: Callable[..., Any] = subprocess.run) -> str | None:
    """The gcloud CLI's configured project (`gcloud config get-value project`), or None."""
    try:
        r = run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    p = (r.stdout or "").strip()
    return p if r.returncode == 0 and p and p != "(unset)" else None


class VeoProvider:
    name = PROVIDER
    paid = True

    def __init__(self, *, project: str | None = PROJECT, location: str = LOCATION, model: str = DEFAULT_MODEL,
                 budget: Budget | None = None, cache: MediaCache | None = None, http: Http | None = None,
                 fetch_bytes: Callable[..., bytes] | None = None, run: Callable[..., Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 poll_timeout: float = 600.0):
        self.run = run or subprocess.run
        self.project = project or (gcloud_project(self.run) if shutil.which("gcloud") else None) or ""
        self.location, self.model = location, model
        self.budget = budget or Budget()
        self._cache = cache
        self.http, self.fetch_bytes = http or http_json, fetch_bytes or http_bytes
        self.sleep, self.clock, self.poll_timeout = sleep, clock, float(poll_timeout)
        self._token: tuple[float, str] | None = None

    @classmethod
    def from_settings(cls, settings: Mapping | None = None, env: Mapping[str, str] | None = None, **kw):
        """settings['media']['veo'] = {project, location, model}; env REEL_DIRECTOR_VEO_* wins."""
        env = os.environ if env is None else env
        v = dict(((settings or {}).get("media") or {}).get("veo") or {})
        kw.setdefault("budget", Budget.from_settings(settings, env))
        return cls(project=env.get("REEL_DIRECTOR_VEO_PROJECT") or v.get("project") or kw.pop("project", PROJECT),
                   location=env.get("REEL_DIRECTOR_VEO_LOCATION") or v.get("location") or LOCATION,
                   model=env.get("REEL_DIRECTOR_VEO_MODEL") or v.get("model") or DEFAULT_MODEL, **kw)

    # ---- auth / endpoints ----------------------------------------------------------------------------------
    @property
    def cache(self) -> MediaCache:
        if self._cache is None:
            self._cache = MediaCache()
        return self._cache

    @property
    def available(self) -> bool:
        return shutil.which("gcloud") is not None and bool(self.project)

    def status(self) -> dict:
        rates = MODELS[self.model].rates if self.model in MODELS else {}
        return {"provider": PROVIDER, "paid": True, "available": self.available, "kinds": ["video"],
                "project": self.project, "location": self.location, "model": self.model, "price_basis": PRICE_BASIS,
                "usd_per_second": {f"{r}{'+audio' if a else ''}": v for (r, a), v in rates.items()},
                "budget": budget_summary(self.budget), "setup": SETUP}

    def _headers(self) -> dict:
        now = time.time()
        if not self._token or now - self._token[0] > 1800:
            out = self.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, timeout=60)
            tok = (out.stdout or "").strip()
            if out.returncode or not tok:
                raise VeoError("gcloud has no usable login (`gcloud auth login`).\n" + SETUP)
            self._token = (now, tok)
        return {"Authorization": f"Bearer {self._token[1]}", "x-goog-user-project": self.project}

    def _model_url(self, model: str, method: str) -> str:
        return (f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}/locations/"
                f"{self.location}/publishers/google/models/{model}:{method}")

    # ---- free checks ---------------------------------------------------------------------------------------
    def probe(self) -> dict:
        """FREE reads only: publisher-model catalog, model metadata, IAM permission test. Never generates."""
        h, out = self._headers(), {"project": self.project, "location": self.location}
        base = f"https://{self.location}-aiplatform.googleapis.com"
        ids, token = [], ""
        for _ in range(20):
            q = urllib.parse.urlencode({"pageSize": 200, "listAllVersions": "true",
                                        **({"pageToken": token} if token else {})})
            code, body = self.http("GET", f"{base}/v1beta1/publishers/google/models?{q}", h)
            if code != 200:
                raise VeoError(f"model list HTTP {code}: {json.dumps(body)[:300]}")
            ids += [m["name"].rsplit("/", 1)[-1] for m in body.get("publisherModels", []) if "/veo-" in m["name"]]
            token = body.get("nextPageToken") or ""
            if not token:
                break
        out["veo_models"] = sorted(set(ids))
        out["models"] = {}
        for mid in sorted({self.model, *MODELS, *UNPRICED, *RETIRED}):
            code, body = self.http("GET", f"{base}/v1/publishers/google/models/{mid}", h)
            out["models"][mid] = {"http": code, "launch_stage": body.get("launchStage") if code == 200 else None,
                                  "quotable": mid in MODELS}
        out["model"] = {"id": self.model, **out["models"][self.model]}
        out["quota"] = self._veo_quota(h)
        perms = ["aiplatform.endpoints.predict"]
        code, body = self.http("POST", f"https://cloudresourcemanager.googleapis.com/v1/projects/{self.project}"
                                       ":testIamPermissions", h, {"permissions": perms})
        out["permissions"] = {p: p in (body.get("permissions") or []) for p in perms}
        in_region = "error" in out["quota"] or self.location in out["quota"].get(self.model, {})
        out["ready"] = bool(self.model in out["veo_models"] and out["model"]["http"] == 200 and in_region
                            and all(out["permissions"].values()))
        return out

    def _veo_quota(self, h: Mapping[str, str]) -> dict:
        """{veo model: {region: requests/min}} from the project's Service Usage quota buckets (a free read)."""
        url = (f"https://serviceusage.googleapis.com/v1beta1/projects/{self.project}/services/"
               "aiplatform.googleapis.com/consumerQuotaMetrics?view=FULL&pageSize=500")
        found: dict[str, dict[str, Any]] = {}
        token = ""
        for _ in range(10):
            code, body = self.http("GET", url + (f"&pageToken={urllib.parse.quote(token)}" if token else ""), h)
            if code != 200:
                return {"error": f"quota read HTTP {code}"}
            for m in body.get("metrics") or []:
                for lim in m.get("consumerQuotaLimits") or []:
                    for b in lim.get("quotaBuckets") or []:
                        d = b.get("dimensions") or {}
                        if str(d.get("base_model", "")).startswith("veo-"):
                            found.setdefault(d["base_model"], {})[d.get("region", "global")] = b.get("effectiveLimit")
            token = body.get("nextPageToken") or ""
            if not token:
                break
        return {k: found[k] for k in sorted(found)}

    # ---- quote (free) --------------------------------------------------------------------------------------
    def quote(self, prompt: str, *, reel: str, clip: str, **spec_kw):
        spec = make_spec(prompt, model=spec_kw.pop("model", self.model), **spec_kw)
        est = estimate(spec["model"], spec["seconds"], spec["resolution"], spec["audio"])
        return self.budget.quote(PROVIDER, spec["model"], spec, usd=est["usd"], seconds=spec["seconds"],
                                 reel=reel, clip=clip, basis=f"{est['usd_per_second']}/s; {est['sku']}; {PRICE_BASIS}")

    def search(self, query: str, kind: str = "video", min_short_side: int = 1080,
               duration: tuple[float, float] = (2, 10), orientation: str | None = None, limit: int = 20, *,
               reel: str = "", clip: str = "", image: Path | str | None = None, **spec_kw) -> list[Candidate]:
        """One proposed clip with its price. Writes a quote; spends nothing; touches no network."""
        if kind != "video":
            return []
        w, h = (1920, 1080) if orientation == "landscape" else (1080, 1920)
        res = "720p" if min_short_side <= 720 else "1080p"
        q = self.quote(query, reel=reel, clip=clip or query, seconds=max(duration[0], 1), w=w, h=h,
                       resolution=spec_kw.pop("resolution", res), image=image, **spec_kw)
        return [self.candidate(q)]

    def resolve(self, c: Candidate) -> Candidate:
        return c                                               # a quote is already complete

    @staticmethod
    def candidate(q) -> Candidate:
        return paid_candidate(q, f"AI-generated with Google Veo ({q.model})")

    # ---- paid path (approval-gated) ------------------------------------------------------------------------
    def fetch(self, candidate: Any, segment: tuple[float, float] | None = None, approved: bool = False) -> Path:
        """The whole generated clip (segment picking is select.py's job). approved=True records the caller's
        (Studio's) approval of a still-open quote, within the caps; otherwise the ledger must already hold one."""
        rid = candidate_request_id(candidate)
        hit = self.cache.lookup(f"{PROVIDER}:{rid}")
        if hit:
            return hit
        q = self.budget.get(rid)
        spec = q.spec

        def submit() -> str:
            body = build_request(spec)
            code, resp = self.http("POST", self._model_url(spec["model"], "predictLongRunning"), self._headers(), body)
            if 400 <= code < 500:
                raise SubmitRejected(f"Veo refused the request (HTTP {code}): {json.dumps(resp)[:400]}")
            if code != 200 or not resp.get("name"):
                raise VeoError(f"Veo submit HTTP {code} without an operation: {json.dumps(resp)[:300]}")
            return resp["name"]

        def finish(resp: dict) -> Path:
            video = resp["videos"][0]
            if video.get("bytesBase64Encoded"):
                data = base64.b64decode(video["bytesBase64Encoded"])
            elif video.get("gcsUri", "").startswith("gs://"):
                bucket, _, obj = video["gcsUri"][5:].partition("/")
                url = (f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/"
                       f"{urllib.parse.quote(obj, safe='')}?alt=media")
                data = self.fetch_bytes(url, self._headers())
            else:
                raise VeoError(f"Veo returned no video bytes or gcsUri: {json.dumps(video)[:200]}")
            side = {**self.candidate(q).to_dict(), "request_id": rid, "prompt": spec["prompt"],
                    "spec": {k: v for k, v in spec.items() if k != "prompt"}, "gcs_uri": video.get("gcsUri")}
            return cache_bytes(self.cache, data, ".mp4", f"{PROVIDER}:{rid}", side)

        return run_paid(self.budget, rid, submit=submit, wait=self._wait, finish=finish,
                        approved_by="studio (approved=True)" if approved else None)

    def _wait(self, operation: str) -> dict:
        model = operation.split("/models/", 1)[1].split("/", 1)[0] if "/models/" in operation else self.model
        deadline, delay = self.clock() + self.poll_timeout, 5.0
        while True:
            code, op = self.http("POST", self._model_url(model, "fetchPredictOperation"), self._headers(),
                                 {"operationName": operation})
            if code == 200 and op.get("done"):
                if op.get("error"):
                    err = op["error"]
                    raise GenerationFailed(f"Veo job failed: {err.get('code')} {err.get('message', '')}",
                                           outcome="failed", charged=None)
                resp = op.get("response") or {}
                if not resp.get("videos"):
                    why = "; ".join(resp.get("raiMediaFilteredReasons") or []) or "no video returned"
                    raise GenerationFailed(f"Veo filtered the clip ({resp.get('raiMediaFilteredCount', 0)}): {why}",
                                           outcome="filtered", charged=None)
                return resp
            if code not in (200, 429) and code < 500:
                raise VeoError(f"Veo poll HTTP {code}: {json.dumps(op)[:300]}")
            if self.clock() + delay > deadline:
                raise GenerationTimeout(f"Veo job {operation} still running after {self.poll_timeout:.0f}s; "
                                        "fetch again later to resume (already paid, not resubmitted)")
            self.sleep(delay)
            delay = min(delay * 1.5, 20.0)


def budget_summary(budget: Budget) -> dict:
    try:
        return budget.summary()
    except Exception as e:          # noqa: BLE001 - a broken ledger must show in Studio, not crash the status page
        return {"error": str(e)}


def paid_candidate(q, attribution: str) -> Candidate:
    """A quoted (not yet generated) clip: price in cost_usd, the quote in extra; fetch() needs approval."""
    s = q.spec          # url: a non-network marker (like claude_clip's) so select.pick keeps it; fetch() ignores it
    return Candidate(id=f"{q.provider}:{q.request_id}", provider=q.provider, kind="video", title=s["prompt"][:120],
                     url=f"{q.provider}://quote/{q.request_id}", thumb="", w=s["w"], h=s["h"],
                     duration=float(s["seconds"]), license=LICENSE,
                     attribution=attribution, source_page="", cost_usd=float(q.usd or 0.0),
                     extra={"ai_generated": True, "paid": True, "request_id": q.request_id, "model": q.model,
                            "price_known": q.usd is not None, "price_basis": q.basis, "reel": q.reel,
                            "clip": q.clip, "approve": f"python -m reel_director.media.budget approve {q.request_id}"})


def provider(settings: Mapping | None = None, **kw) -> VeoProvider:
    return VeoProvider.from_settings(settings, **kw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reel_director.media.providers.veo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="free: model catalog, quota regions, IAM permission check")
    for name in ("estimate", "quote"):
        e = sub.add_parser(name, help="price of one clip (offline)" if name == "estimate" else
                           "free: write a quote to the ledger and print its request_id + approve command")
        e.add_argument("--model", default=DEFAULT_MODEL)
        e.add_argument("--seconds", type=float, default=4)
        e.add_argument("--size", default="1080x1920")
        e.add_argument("--audio", action="store_true")
        if name == "quote":
            e.add_argument("prompt")
            e.add_argument("--reel", required=True)
            e.add_argument("--clip", required=True)
            e.add_argument("--image", help="image-to-video: the first frame")
    g = sub.add_parser("generate", help="PAID: run one APPROVED quote (refused unless approved within the caps)")
    g.add_argument("request_id")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "probe":
            print(json.dumps(VeoProvider.from_settings(None).probe(), indent=2))
            return 0
        if a.cmd == "generate":
            print(VeoProvider.from_settings(None).fetch(a.request_id))
            return 0
        w, h = (int(x) for x in a.size.lower().split("x"))
        if a.cmd == "quote":
            q = VeoProvider.from_settings(None).quote(a.prompt, reel=a.reel, clip=a.clip, model=a.model,
                                                      seconds=a.seconds, w=w, h=h, audio=a.audio, image=a.image)
            print(json.dumps({"request_id": q.request_id, "usd": q.usd, "model": q.model, "seconds": q.seconds,
                              "basis": q.basis, "approve": f"python -m reel_director.media.budget approve "
                              f"{q.request_id}", "then": f"python -m reel_director.media.providers.veo generate "
                              f"{q.request_id}"}, indent=2))
            return 0
        _, res, _, _ = frame_for(w, h)
        secs = snap_seconds(a.model, a.seconds) if a.model in MODELS else a.seconds
        print(json.dumps(estimate(a.model, secs, res, a.audio), indent=2))
    except (VeoError, BudgetError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
