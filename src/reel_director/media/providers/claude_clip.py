"""Claude-created B-roll clips (v4 media contract, docs/research/v4-media-broll-contract.md): free, subscription.

generate(spec): a cache hit by brief hash returns at once. Otherwise stage a sandbox in work/media-claude/<key>/
(renderable scaffold, motion-pack modules COPIED from the pack, Reel Director fonts, owned icons, a three.js shim,
up to two accepted clips as examples), run headless `claude -p` there (tools Read/Write/Bash, Bash limited to
`hyperframes lint|snapshot`, --restricted --safe-mode, no MCP, no session, a timeout, a JSON-schema answer), then
validate: static checks (contract, no clocks/randomness/network, kit untouched) -> `hyperframes lint` -> render ->
frame check (pictures, frame 0 one, motion to the end) -> seek check (out-of-order frames match the render). A
rejected attempt is retried at most `retries` (<= 2) times with the errors fed back. The accepted MP4 and poster go
into the shared media cache (cache.py) under `claude_clip:<key>`; the composition joins work/media-claude/_gallery.

Never paid: ANTHROPIC_API_KEY is removed from the child's environment, so `claude -p` runs on the subscription login
or not at all (FOUNDER_SETUP says how to log the CLI in). GEMINI_API_KEY is removed too and every snapshot passes
`--describe false`: `hyperframes snapshot` otherwise uploads frames to Gemini vision whenever that key is set.
search() offers a clip only when it can be made or is cached.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

import numpy as np

from .. import clip_prompts as P
from ..clip_prompts import contact_sheet, frame_check, gray_frames, parse_lint, static_check  # noqa: F401
from ...stage import FONTS, StageError, import_closure, pack_root
from ..base import Candidate, ProviderError, setting
from ..cache import MediaCache

PROVIDER = "claude_clip"
LICENSE = "original"            # license.py: made for this reel (motion-pack is the founder's own, fonts are OFL)
REPO = Path(__file__).resolve().parents[4]
ICONS = Path(__file__).resolve().parents[2] / "icons" / "lucide"
MP_ENTRIES = ("type/gfx/index.js", "type/ease.js", "type/icons.js", "layers/overlay.js", "layers/ease.js",
              "objects/index.js", "physics/table-player.js")
PACK_FONTS = (("Manrope", "objects/kit/fonts/Manrope-Variable.ttf", 0),
              ("IBM Plex Mono", "objects/kit/fonts/IBMPlexMono-Medium.ttf", 500),
              ("IBM Plex Mono", "objects/kit/fonts/IBMPlexMono-SemiBold.ttf", 600))
CAPTURE = ("--no-browser-gpu",)  # SwiftShader capture: two renders are bit-identical (GPU capture drifts ~46 dB run to run)
RENDER_CRF = 18                 # near-transparent; the reel re-encodes anyway (CRF 16 + grain is ~25 MB per 3 s)
SEEK_TOL, SEEK_FRAC = 3.5, 0.006  # seeked snapshot vs rendered frame (108x192 luma): mean |diff|, share of pixels off by
                                 # > 24; same frame measures ~2.0 / <0.1 %, a frame off measures 3-7 / 1.6-4.7 %
EXAMPLES = 2
GALLERY_HEAD = re.compile(r"<!-- accepted clip(?: (\S+))?; brief: (.*?) -->")   # line 1 of every _gallery/<key>.html
STRIP_ENV = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "ANTHROPIC_API_KEY",    # an API key = paid: never for clips
             "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY")  # `hyperframes snapshot` calls Gemini
STRIP_ENV_PREFIX = ("CLAUDE_CODE_SESSION", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_HOST", "CLAUDE_CODE_MESSAGING",
                    "CLAUDE_CODE_SDK", "CLAUDE_CODE_CHILD", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_EXECPATH", "CLAUDE_AGENT_SDK")
FOUNDER_SETUP = ("The Claude Code CLI is not logged in for headless use, so `claude -p` cannot author clips. In a "
                 "terminal run ONE of:\n  claude auth login      (subscription login in the browser)\n"
                 "  claude setup-token     (long-lived token; then export CLAUDE_CODE_OAUTH_TOKEN=<token>)\n"
                 "then check: claude auth status   (expects \"loggedIn\": true). An API key is never used for clips.")


class ClipError(ProviderError):
    """No acceptable clip after every attempt (the message says why; the sandbox keeps attempts.json)."""


class ClipAuthError(ClipError):
    """The CLI is not logged in: a founder step, never retried."""


@dataclass
class ClipSpec:
    brief: str
    width: int = 1080
    height: int = 1920
    duration: float = 3.0
    fps: int = 30
    context: str = ""
    style: dict = field(default_factory=dict)

    def key(self) -> str:
        blob = json.dumps({"v": P.PROMPT_VERSION, "brief": _norm(self.brief), "context": _norm(self.context),
                           "size": [self.width, self.height], "dur": round(float(self.duration), 3), "fps": self.fps,
                           "style": self.style}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {"brief": self.brief, "width": self.width, "height": self.height, "duration": self.duration,
                "fps": self.fps, "context": self.context, "style": self.style}


@dataclass
class ClipResult:
    key: str
    path: Path
    poster: Path | None
    meta: dict
    cached: bool = False


def size_for(orientation: str | None) -> tuple[int, int]:
    return {"square": (1080, 1080), "pip": (1080, 1080), "landscape": (1920, 1080)}.get(orientation or "", (1080, 1920))


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV and not k.startswith(STRIP_ENV_PREFIX)}
    env["NO_COLOR"] = "1"
    return env


class ClaudeClipProvider:
    name = PROVIDER
    label = "Claude clip"
    kinds = ("video",)
    paid = False
    serves_cache = True             # registry.order keeps it while logged out: cached / gallery clips still serve

    def __init__(self, work_root: Path | None = None, cache: MediaCache | None = None, *, pack: Path | None = None,
                 claude_bin: str | None = None, hyperframes_bin: str | None = None, ffmpeg_bin: str | None = None,
                 model: str | None = None, retries: int = 2, timeout: float = 900.0, render_timeout: float = 600.0,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run, log: Callable[[str], None] = print):
        self.work_root = Path(work_root or os.environ.get("RD_CLIP_WORK") or REPO / "work" / "media-claude")
        self._cache = cache
        self.pack = Path(pack or pack_root())
        self.claude = claude_bin or shutil.which("claude") or "claude"
        self.hf = hyperframes_bin or shutil.which("hyperframes") or "hyperframes"
        self.ffmpeg = ffmpeg_bin or shutil.which("ffmpeg") or "ffmpeg"
        self.model = model or os.environ.get("RD_CLIP_MODEL") or None
        self.retries, self.timeout, self.render_timeout = max(0, min(2, int(retries))), timeout, render_timeout
        self.run, self.log = run, log
        self._auth: bool | None = None

    @classmethod
    def from_settings(cls, settings: Mapping | None = None, **kw):
        return cls(model=kw.pop("model", None) or setting(settings, "claude_clip_model", ("RD_CLIP_MODEL",)), **kw)

    @property
    def cache(self) -> MediaCache:
        if self._cache is None:
            self._cache = MediaCache()
        return self._cache

    @property
    def available(self) -> bool:
        """Logged in (checked once per instance); cached clips are offered either way (see search)."""
        if self._auth is None:
            try:
                self.check_auth()
                self._auth = True
            except ClipAuthError:
                self._auth = False
        return self._auth

    def status(self) -> dict:
        ok = self.available
        return {"provider": PROVIDER, "available": ok, "kinds": list(self.kinds), "paid": False, "cost_usd": 0.0,
                "setup": None if ok else FOUNDER_SETUP}

    # ---- the common provider interface (base.py) ----
    def search(self, query: str, kind: str = "video", min_short_side: int = 1080, duration=(2.0, 10.0),
               orientation: str | None = "portrait", limit: int = 1, context: str = "",
               style: dict | None = None) -> list[Candidate]:
        """One would-be clip for the brief (fetch() makes it), plus accepted gallery clips of briefs sharing >= 2
        words with it (reused as they are: free, no `claude -p`, offered even when logged out). Cost is always 0."""
        if kind != "video" or not str(query).strip() or limit < 1:
            return []
        w, h = size_for(orientation)
        if min(w, h) < min_short_side:
            return []
        dur = float(min(max(3.0, duration[0]), duration[1], 4.0))
        spec = ClipSpec(str(query).strip(), w, h, dur, 30, context or "", dict(style or {}))
        key, hit = spec.key(), self.cached(spec)
        out = [] if hit else [self._cand(g, self.cached(g), True) for g in self.gallery(spec)]
        if hit is None and not self.available:
            return out[:limit]
        (self.work_root / key).mkdir(parents=True, exist_ok=True)
        (self.work_root / key / "spec.json").write_text(json.dumps(spec.as_dict(), indent=1, sort_keys=True) + "\n")
        return ([self._cand(spec, hit)] + out)[:limit]

    def _cand(self, spec: ClipSpec, hit: ClipResult | None, reused: bool = False) -> Candidate:
        key = spec.key()
        return Candidate(id=f"{PROVIDER}:{key}", provider=PROVIDER, kind="video", title=spec.brief, w=spec.width,
                         url=str(hit.path) if hit else f"claude-clip://{key}", h=spec.height, duration=spec.duration,
                         thumb=str(hit.poster) if hit and hit.poster else "", license=LICENSE, creator="Claude",
                         tags=("claude", "motion-graphics"), extra={"brief_key": key, "context": spec.context,
                                                                    "description": spec.context, "reused": reused})

    def gallery(self, spec: ClipSpec, limit: int = 2) -> list[ClipSpec]:
        """Cached clips (current prompt version, same size) of OTHER briefs, most shared brief + context words first."""
        from ..select import tokens
        want, hits = set(tokens(f"{spec.brief} {spec.context}")), []
        for f in sorted(self.work_root.glob("*/spec.json")):
            try:
                g = ClipSpec(**json.loads(f.read_text()))
            except (OSError, ValueError, TypeError):
                continue
            n = len(want & set(tokens(f"{g.brief} {g.context}")))
            if n >= 2 and g.key() == f.parent.name != spec.key() and (g.width, g.height) == (spec.width, spec.height):
                hits += [(-n, g.key(), g)] if self.cached(g) else []
        return [g for *_, g in sorted(hits)[:limit]]

    def resolve(self, c: Candidate) -> Candidate:
        return c

    def fetch(self, c, segment=None, approved: bool = False) -> Path:
        cid = c.get("id") if isinstance(c, Mapping) else c.id
        key = str(cid).split(":", 1)[-1]
        spec_file = self.work_root / key / "spec.json"
        if spec_file.exists():
            spec = ClipSpec(**json.loads(spec_file.read_text()))
        else:
            get = (lambda k, d=None: c.get(k, d)) if isinstance(c, Mapping) else (lambda k, d=None: getattr(c, k, d))
            spec = ClipSpec(get("title"), int(get("w") or 1080), int(get("h") or 1920), float(get("duration") or 3.0))
        return self.generate(spec).path

    # ---- generation ----
    def cached(self, spec: ClipSpec) -> ClipResult | None:
        key = spec.key()
        mp4 = self.cache.lookup(f"{PROVIDER}:{key}")
        if mp4 is None:
            return None
        return ClipResult(key, mp4, self.cache.lookup(f"{PROVIDER}:{key}:poster"),
                          self.cache.meta(mp4).get(PROVIDER, {}), cached=True)

    def generate(self, spec: ClipSpec) -> ClipResult:
        hit = self.cached(spec)
        if hit:
            return hit
        self.check_auth()
        sb = self.prepare(spec)
        prev = json.loads((sb / "attempts.json").read_text()) if (sb / "attempts.json").exists() else []
        errors = prev[-1]["errors"] if prev and prev[-1].get("errors") else None
        attempts: list[dict] = []
        for n in range(self.retries + 1):
            t0 = time.monotonic()
            answer = self.author(sb, spec, errors)
            out = sb / "out" / f"attempt-{len(prev) + n}.mp4"
            errors, stats = self.validate(sb, spec, out)
            attempts.append({"n": len(prev) + n, "ok": not errors, "errors": errors, "claude": answer,
                             "stats": stats, "seconds": round(time.monotonic() - t0, 1)})
            (sb / "attempts.json").write_text(json.dumps(prev + attempts, indent=1) + "\n")
            self.log(f"  claude_clip {spec.key()} attempt {n}: {'ok' if not errors else '; '.join(errors)[:300]}")
            if not errors:
                return self.store(sb, spec, out, attempts)
        raise ClipError(f"no acceptable clip for {spec.brief!r} after {len(attempts)} attempt(s): "
                        f"{'; '.join(attempts[-1]['errors'])[:600]} (sandbox {sb})")

    def finish(self, spec: ClipSpec, note: str = "authored in the sandbox by hand") -> ClipResult:
        """Validate + render + cache whatever index.html the sandbox holds, without `claude -p` (the manual path)."""
        sb = self.work_root / spec.key()
        errors, stats = self.validate(sb, spec, sb / "out" / "manual.mp4")
        if errors:
            raise ClipError("; ".join(errors))
        return self.store(sb, spec, sb / "out" / "manual.mp4",
                          [{"n": 0, "ok": True, "errors": [], "claude": {"summary": note}, "stats": stats}])

    def check_auth(self) -> None:
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return
        try:
            r = self.run([self.claude, "auth", "status"], capture_output=True, text=True, env=child_env(), timeout=60)
            ok = bool(json.loads(r.stdout or "{}").get("loggedIn"))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            ok = False
        if not ok:
            raise ClipAuthError(FOUNDER_SETUP)

    def prepare(self, spec: ClipSpec) -> Path:
        """Stage the sandbox. Everything is a COPY (never a link), so nothing written in the sandbox can reach the
        pack or the repo; a manifest pins kit/ and mp/ for the integrity check."""
        sb = self.work_root / spec.key()
        (sb / "out").mkdir(parents=True, exist_ok=True)
        (sb / "spec.json").write_text(json.dumps(spec.as_dict(), indent=1, sort_keys=True) + "\n")
        try:
            mods = import_closure(self.pack, MP_ENTRIES)
        except StageError as e:
            raise ClipError(f"motion-pack not usable: {e}") from None
        for rel in mods:
            _copy(self.pack / rel, sb / "mp" / rel)
        fonts = []
        for f in sorted(FONTS.rglob("*.woff2")):
            _copy(f, sb / "kit" / "fonts" / f.name)
            fonts.append(_font_entry(f.parent.name, f.name))
        for fam, rel, weight in PACK_FONTS:
            if (self.pack / rel).exists():
                _copy(self.pack / rel, sb / "kit" / "fonts" / Path(rel).name)
                fonts.append((fam, f"kit/fonts/{Path(rel).name}", weight, "normal"))
        faces = P.font_faces(fonts)
        (sb / "kit" / "fonts.css").write_text(faces + "\n")
        icons = sorted(p.stem for p in ICONS.glob("*.svg"))
        for name in icons:
            _copy(ICONS / f"{name}.svg", sb / "kit" / "icons" / f"{name}.svg")
        (sb / "kit" / "objects3d.js").write_text(P.OBJECTS_SHIM)
        for ex in self.examples(spec):
            _copy(ex, sb / "kit" / "examples" / ex.name)
        idx = sb / "index.html"
        if not idx.exists():
            idx.write_text(P.scaffold_html(width=spec.width, height=spec.height, duration=spec.duration,
                                           fps=spec.fps, faces=faces, style=spec.style, brief=spec.brief))
        manifest = {p.relative_to(sb).as_posix(): P.file_sha(p) for d in ("mp", "kit") for p in sorted((sb / d).rglob("*"))
                    if p.is_file()}
        (sb / "out" / "kit-manifest.json").write_text(json.dumps(manifest, indent=0, sort_keys=True))
        (sb / "out" / "icons.json").write_text(json.dumps(icons))
        return sb

    def examples(self, spec: ClipSpec) -> list[Path]:
        """Up to EXAMPLES accepted clips of OTHER briefs (never this brief's older take), current prompt version first."""
        mine, ranked = _norm(P._clean(spec.brief)), []
        for g in sorted((self.work_root / "_gallery").glob("*.html")):
            ver, brief = gallery_info(g)
            if g.stem != spec.key() and _norm(brief) != mine:
                ranked.append((ver != P.PROMPT_VERSION, g.name, g))
        return [g for *_, g in sorted(ranked)[:EXAMPLES]]

    def prompt(self, sb: Path, spec: ClipSpec, errors: list[str] | None = None) -> str:
        icons = json.loads((sb / "out" / "icons.json").read_text()) if (sb / "out" / "icons.json").exists() else []
        return P.build_prompt(spec.brief, width=spec.width, height=spec.height, duration=spec.duration, fps=spec.fps,
                              context=spec.context, style=spec.style, icons=icons, errors=errors)

    def claude_cmd(self) -> list[str]:
        cmd = [self.claude, "-p", "--output-format", "json", "--json-schema", json.dumps(P.RESULT_SCHEMA),
               "--tools", "Read,Write,Bash", "--permission-mode", "dontAsk", "--restricted", "--safe-mode",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence",
               "--disable-slash-commands",
               "--allowedTools", "Read,Write,Bash(hyperframes lint:*),Bash(hyperframes snapshot:*)"]
        return cmd + (["--model", self.model] if self.model else [])

    def author(self, sb: Path, spec: ClipSpec, errors: list[str] | None) -> dict:
        """One headless `claude -p` run in the sandbox (prompt on stdin); returns its JSON answer."""
        prompt = self.prompt(sb, spec, errors)
        (sb / "out" / "prompt.txt").write_text(prompt)
        try:
            r = self.run(self.claude_cmd(), input=prompt, cwd=str(sb), capture_output=True, text=True,
                         env=child_env(), timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return {"status": "error", "summary": f"claude -p timed out after {self.timeout:.0f}s"}
        try:
            data = json.loads(r.stdout or "{}")
        except ValueError:
            data = {"is_error": True, "result": ((r.stdout or "") + (r.stderr or ""))[-400:]}
        msg = str(data.get("result") or "")
        if data.get("is_error") and re.search(r"authenticat|log ?in|OAuth", msg, re.I):
            raise ClipAuthError(f"{msg}\n{FOUNDER_SETUP}")
        out = data.get("structured_output")
        if not isinstance(out, dict):
            try:
                out = json.loads(msg)
            except ValueError:
                out = {"status": "error" if data.get("is_error") else "ok", "summary": msg[-400:]}
        out["cost_usd_reported"] = data.get("total_cost_usd")     # subscription run: informational only
        return out

    # ---- validation ----
    def validate(self, sb: Path, spec: ClipSpec, out_mp4: Path) -> tuple[list[str], dict]:
        errors, stats = static_check(sb, spec), {}
        if errors:
            return errors, stats
        r = self._run([self.hf, "lint", "--json", str(sb)], 180)
        lint_err, lint_warn = parse_lint((r.stdout or "") + (r.stderr or ""))
        stats["lint_warnings"] = lint_warn[:12]
        if lint_err:
            return [f"hyperframes lint: {e}" for e in lint_err[:10]], stats
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        r = self._run([self.hf, "render", str(sb), "-o", str(out_mp4), "--crf", str(RENDER_CRF), "--fps", str(spec.fps),
                       *CAPTURE], self.render_timeout)
        stats["render_s"] = round(time.monotonic() - t0, 1)
        if r.returncode != 0 or not out_mp4.exists():
            tail = " | ".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-4:])
            return [f"render failed: {tail[-500:]}"], stats
        errors, fstats = frame_check(out_mp4, spec, self.ffmpeg, self.run)
        stats.update(fstats)
        if not errors:
            errors, sstats = self.seek_check(sb, spec, out_mp4)
            stats.update(sstats)
        return errors, stats

    def seek_check(self, sb: Path, spec: ClipSpec, mp4: Path) -> tuple[list[str], dict]:
        """Snapshot a late frame, then seek BACK to an early one; both must match the render (state between frames
        or async drawing shows up here). A snapshot tool failure skips the check rather than failing the clip."""
        fr = spec.fps
        times = [round(spec.duration * f * fr) / fr for f in (0.8, 0.25)]
        out = sb / "out" / "seek"
        r = self._run([self.hf, "snapshot", str(sb), "--at", ",".join(f"{t:.4f}" for t in times), "--no-end",
                       "--describe", "false", *CAPTURE, "-o", str(out)], 240)
        pngs = sorted(out.glob("frame-*.png"))
        if r.returncode != 0 or len(pngs) != len(times):
            return [], {"seek_check": "skipped (snapshot failed)"}
        vid = gray_frames(mp4, times, self.ffmpeg, self.run)
        snap = [gray_frames(p, [0.0], self.ffmpeg, self.run)[0] for p in pngs]
        if any(f is None for f in vid + snap):
            return [], {"seek_check": "skipped (decode failed)"}
        d = [np.abs(a - b) for a, b in zip(vid, snap)]
        diffs = [(round(float(x.mean()), 2), round(float((x > 24).mean()), 4)) for x in d]
        errs = [f"not seek-safe: the frame at {t:.2f}s changes after an out-of-order seek (mean diff {m}, {f:.1%} of "
                f"pixels off); draw(t) must set every animated property from t alone"
                for t, (m, f) in zip(times, diffs) if m > SEEK_TOL or f > SEEK_FRAC]
        return errs, {"seek_diff": diffs}

    def _run(self, cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
        try:
            return self.run(cmd, capture_output=True, text=True, env=child_env(), timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout:.0f}s")

    def store(self, sb: Path, spec: ClipSpec, mp4: Path, attempts: list[dict]) -> ClipResult:
        key = spec.key()
        poster = sb / "out" / "poster.jpg"
        self.run([self.ffmpeg, "-v", "error", "-y", "-ss", f"{spec.duration * 0.65:.3f}", "-i", str(mp4),
                  "-frames:v", "1", "-q:v", "3", str(poster)], capture_output=True, text=True, timeout=120)
        gallery = self.work_root / "_gallery" / f"{key}.html"
        gallery.parent.mkdir(parents=True, exist_ok=True)
        html = (sb / "index.html").read_text(errors="replace")
        gallery.write_text(f"<!-- accepted clip {P.PROMPT_VERSION}; brief: {P._clean(spec.brief)} -->\n" + html)
        for old in gallery.parent.glob("*.html"):          # this brief's takes from older prompts leave the example pool
            ver, brief = gallery_info(old)
            if old != gallery and ver != P.PROMPT_VERSION and _norm(brief) == _norm(P._clean(spec.brief)):
                (gallery.parent / "superseded").mkdir(exist_ok=True)
                old.replace(gallery.parent / "superseded" / old.name)
        meta = {"key": key, "prompt_version": P.PROMPT_VERSION, "spec": spec.as_dict(), "sandbox": str(sb),
                "composition": str(gallery), "attempts": attempts}
        side = {"provider": PROVIDER, "id": f"{PROVIDER}:{key}", "title": spec.brief, "license": LICENSE,
                "attribution": "", "cost_usd": 0.0, PROVIDER: meta}
        path = self.cache.put(mp4, key=f"{PROVIDER}:{key}", meta=side, ext=".mp4", move=False)
        pst = self.cache.put(poster, key=f"{PROVIDER}:{key}:poster", meta={"provider": PROVIDER}, ext=".jpg",
                             move=False) if poster.exists() else None
        (sb / "out" / "result.json").write_text(json.dumps({**meta, "file": str(path)}, indent=1) + "\n")
        return ClipResult(key, path, pst, meta)


def provider(settings: Mapping | None = None, **kw) -> ClaudeClipProvider:
    """The registry factory (providers/__init__.py)."""
    return ClaudeClipProvider.from_settings(settings, **kw)


def gallery_info(path: Path) -> tuple[str, str]:
    """(prompt version, brief) from line 1 of an accepted composition; the version is '' before cc-v5."""
    with open(path, errors="replace") as f:
        m = GALLERY_HEAD.match(f.readline().strip())
    return (m.group(1) or "", m.group(2)) if m else ("", "")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()
    shutil.copyfile(src, dest)


def _font_entry(folder: str, name: str) -> tuple[str, str, int, str]:
    """inter-latin-700-normal.woff2 -> ("Inter", "kit/fonts/...", 700, "normal") (family from the folder name)."""
    fam = " ".join(w.capitalize() for w in folder.split("-"))
    m = re.search(r"-(\d{3})-(normal|italic)\.woff2$", name)
    return fam, f"kit/fonts/{name}", int(m.group(1)) if m else 400, m.group(2) if m else "normal"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m reel_director.media.providers.claude_clip",
                                 description="Author a B-roll clip with headless Claude + HyperFrames (free).")
    ap.add_argument("brief")
    ap.add_argument("--context", default="")
    ap.add_argument("--duration", type=float, default=3.0)
    ap.add_argument("--orientation", default="portrait", choices=["portrait", "square", "pip", "landscape"])
    ap.add_argument("--prepare", action="store_true", help="only stage the sandbox and write out/prompt.txt")
    ap.add_argument("--finish", action="store_true", help="validate + render + cache the sandbox's index.html as is")
    ap.add_argument("--note", default="authored in the sandbox by hand", help="--finish: who authored index.html")
    a = ap.parse_args(argv)
    w, h = size_for(a.orientation)
    prov, spec = ClaudeClipProvider(), ClipSpec(a.brief, w, h, a.duration, 30, a.context)
    try:
        if a.prepare:
            sb = prov.prepare(spec)
            (sb / "out" / "prompt.txt").write_text(prov.prompt(sb, spec))
            print(sb)
            return 0
        res = prov.finish(spec, a.note) if a.finish else prov.generate(spec)
    except ClipAuthError as e:
        print(e, file=sys.stderr)
        return 3
    except ClipError as e:
        print(f"claude_clip: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"key": res.key, "file": str(res.path), "poster": str(res.poster), "cached": res.cached}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
