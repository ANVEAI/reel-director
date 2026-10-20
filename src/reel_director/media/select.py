"""Pick the B-roll: rank candidates, (optionally) let Claude look at thumbnails, choose the clip segment, normalize.

Ranking (deterministic, no network): score = 0.5 relevance + 0.3 quality + 0.2 license, where
  relevance  query words (stemmed, stop words out) found in the title (1.0), tags (0.8) or description (0.5),
             averaged over the query, +0.15 when the whole query is in the title; 0 relevance quarters the score.
             A candidate that describes its own context (a gallery Claude clip) also scores the share of that
             context the line actually says; the better of the two counts. A reused gallery clip under REUSE_MIN
             relevance is dropped (v4 panel: a 2-word match is not a pick)
  quality    resolution after a cover-fit into the reel frame (1.0 = no upscale) x crop keep (0.7 + 0.3 x share
             of the source kept), x 0.8 for Commons restrictions (personality/trademark), x 0.7 for watermark/
             text/logo/diagram hints or a burned-in text_overlay, 0 when a clip is shorter than the insert
  license    1.0 CC0/PDM/own, 0.95 PD/stock licenses, 0.85 CC BY, 0.7 CC BY-SA; NC/ND/unknown never get here, and
             CC BY-SA only on the creator's opt-in (license.share_alike_ok)
Ties break by the provider order, then id. `pick()` searches the sources in order, ranks, resolves the shortlist
(manifests/sizes), re-ranks, and optionally reranks the top thumbnails with `claude -p` (cached by query +
thumbnail hashes, so the same media.json replays without calling Claude again).

Clips: best_segment() splits the source at scene cuts (ffmpeg scene score) and picks a window inside one shot,
away from cuts and the file's first/last half second, preferring long steady shots and windows whose middle frame
has no sizeable faces of other people and no text (Apple Vision when available). normalize_clip()/normalize_image()
cover-crop (or blur-pad) to the reel size at CFR 30 and apply grade_filter(): a gentle eq/colorbalance that moves
the source's luma, contrast and saturation toward the founder's take and the preset tone, clamped small.
"""
from __future__ import annotations

import inspect
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from . import license as L
from .base import Candidate, target_aspect

WEIGHTS = (0.5, 0.3, 0.2)
LICENSE_SCORE = {0: 1.0, 1: 0.95, 2: 0.85, 3: 0.7}
STOP = set("a an and are as at be by for from in into is it of on or the to with this that your my our you "
           "we i me how what why when shot photo image video clip footage stock b roll broll".split())
NOISY = re.compile(r"\b(watermark|logo|text|subtitles?|caption|screenshot|diagram|chart|map|infographic|"
                   r"poster|meme|banner|labels|slate)\b", re.I)
# Museum scans read as "old document", not B-roll (smoke test 2026-10-20: a CC0 al-Jazari folio outranked a CC0
# clock photo for "clock"): x 0.75 unless the query itself asks for art.
ARTWORK = re.compile(r"\b(folio|manuscript|illustration|drawing|engraving|painting|lithograph|etching|woodcut|"
                     r"sketch|watercolou?r|fresco|miniature|plate \d+)\b", re.I)
# Long-form programs are rarely B-roll (smoke test: "Around The Clock" = a 25-min local news show full of people
# and lower thirds matched "clock"): x 0.7 for these words, x 0.8 for sources over 10 min (x 0.65 over 30 min).
PROGRAM = re.compile(r"\b(news|episode|show|podcast|interview|lecture|webinar|credits|trailer|commentary|briefing|"
                     r"conference|parade|meeting|sermon|broadcast)\b", re.I)
REEL = {"portrait": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}
# A generated clip always matches its own brief at full resolution; real footage that fits wins (contract: real
# inserts count), a generated one beats weak stock.
GENERATED = {"claude_clip": 0.85, "veo": 0.85, "higgsfield": 0.85}
REUSE_MIN = 0.5                   # a reused gallery clip must fit the line at least this well
LONG_S, WINDOW_S = 60.0, 15.0     # fetch(): a source longer than this downloads a window, not the whole film


def stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(("sses", "xes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    return w


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if w not in STOP and len(w) > 1]


@dataclass
class Scored:
    cand: Candidate
    score: float
    parts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {**self.cand.to_dict(), "score": round(self.score, 4), "score_parts": self.parts}


def relevance(c: Candidate, query: str, context: str = "") -> float:
    q = list(dict.fromkeys(tokens(query)))
    if not q:
        return 0.0
    title, tags = set(tokens(c.title)), set(tokens(" ".join(c.tags)))
    desc = set(tokens(f"{c.extra.get('description', '')} {c.extra.get('alt', '')}"))
    s = sum(1.0 if t in title else 0.8 if t in tags else 0.5 if t in desc else 0.0 for t in q) / len(q)
    if len(q) > 1 and " ".join(q) in " ".join(tokens(c.title)):
        s += 0.15
    own = list(dict.fromkeys(tokens(c.extra.get("context") or "")))     # what a gallery clip was made to say
    if own and context:
        said = set(tokens(context))
        s = max(s, sum(t in said for t in own) / len(own))
    return min(1.0, s)


def quality(c: Candidate, min_short_side: int = 1080, orientation: str | None = "portrait",
            duration: tuple[float, float] = (2.0, 10.0)) -> float:
    if c.w and c.h:
        tw, th = REEL.get(orientation or "", (min_short_side, min_short_side))
        scale = max(tw / c.w, th / c.h)
        res = min(1.0, 1.0 / scale) if orientation in REEL else min(1.0, c.short_side / max(1, min_short_side))
        keep = (tw * th) / (c.w * scale * c.h * scale) if orientation in REEL else 1.0
        q = res * (0.7 + 0.3 * keep)
    else:
        q = 0.5                                 # unknown until resolve(); the shortlist is re-ranked after it
    if c.kind == "video" and c.duration and c.duration < duration[0]:
        return 0.0
    if c.kind == "video":
        q *= 0.65 if c.duration > 1800 else 0.8 if c.duration > 600 else 1.0
        q *= 0.7 if PROGRAM.search(c.title) else 1.0
    if c.extra.get("restrictions"):
        q *= 0.8
    if NOISY.search(f"{c.title} {' '.join(c.tags)}") or c.extra.get("text_overlay"):
        q *= 0.7
    if c.extra.get("mature"):
        return 0.0
    return q


def score(c: Candidate, query: str, min_short_side: int = 1080, orientation: str | None = "portrait",
          duration: tuple[float, float] = (2.0, 10.0), context: str = "") -> Scored:
    rel, qual = relevance(c, query, context), quality(c, min_short_side, orientation, duration)
    if ARTWORK.search(f"{c.title} {' '.join(c.tags[:10])}") and not ARTWORK.search(query):
        qual *= 0.75
    lic = LICENSE_SCORE.get(L.info(c.license).rank, 0.0)
    total = WEIGHTS[0] * rel + WEIGHTS[1] * qual + WEIGHTS[2] * lic
    if rel == 0:
        total *= 0.25
    total *= GENERATED.get(c.provider, 1.0) * (0.8 if c.extra.get("license_trust") == "uploader-declared" else 1.0)
    return Scored(c, total, {"relevance": round(rel, 3), "quality": round(qual, 3), "license": lic})


def rank(cands: list[Candidate], query: str, order: tuple | list = (), share_alike: bool = True,
         notes: list | None = None, **spec) -> list[Scored]:
    """Allowed, de-duplicated candidates, best first. Deterministic for the same input. share_alike=False drops
    CC BY-SA; a reused gallery clip under REUSE_MIN relevance drops (both noted)."""
    seen, out = set(), []
    for c in cands:
        if c.id in seen or (c.url and c.url in seen) or not L.allowed(c.license):
            continue
        seen.update({c.id, c.url} - {""})
        if not share_alike and L.info(c.license).share_alike:
            notes is not None and notes.append(f"skipped {c.id}: {L.info(c.license).name} needs the share-alike opt-in")
            continue
        sc = score(c, query, **spec)
        if c.extra.get("reused") and sc.parts["relevance"] < REUSE_MIN:
            notes is not None and notes.append(f"skipped {c.id}: reused clip fits the line at {sc.parts['relevance']:.2f}"
                                               f" < {REUSE_MIN}")
            continue
        out.append(sc)
    pos = {n: i for i, n in enumerate(order)}
    return sorted(out, key=lambda s: (-round(s.score, 6), pos.get(s.cand.provider, len(pos)), s.cand.id))


@dataclass
class Pick:
    query: str
    kind: str
    best: Scored | None
    alternates: list[Scored]
    notes: list[str]

    def to_dict(self) -> dict:
        """The media.json entry for one cue: chosen + alternates + credit lines + why."""
        chosen = [self.best.cand] if self.best else []
        return {"query": self.query, "kind": self.kind, "chosen": self.best.to_dict() if self.best else None,
                "alternates": [a.to_dict() for a in self.alternates], "credits": L.credits(chosen),
                "notes": self.notes}


def _search(p, query: str, kind: str, named: Mapping | None = None, **kw) -> list[Candidate]:
    """p.search with only the keyword args its signature takes (other teams' sources differ on `limit`); `named`
    (reel / clip for paid quotes, context = the spoken words for Claude clips) only where search names them."""
    try:
        params = inspect.signature(p.search).parameters
    except (TypeError, ValueError):
        params = {}
    if params and not any(v.kind is inspect.Parameter.VAR_KEYWORD for v in params.values()):
        kw = {k: v for k, v in kw.items() if k in params}
    return p.search(query, kind, **kw, **{k: v for k, v in (named or {}).items() if k in params and v})


def gather(providers: Mapping, names: list[str], query: str, kind: str, named: Mapping | None = None,
           **spec) -> tuple[list[Candidate], list[str]]:
    cands, notes = [], []
    for n in names:
        try:
            got = _search(providers[n], query, kind, named, **spec)
        except Exception as e:      # noqa: BLE001 - one dead source never sinks the cue
            notes.append(f"{n}: {type(e).__name__}: {str(e)[:160]}")
            continue
        notes.append(f"{n}: {len(got)} candidate(s)")
        cands.extend(got)
    return cands, notes


def pick(query: str | Mapping, kind: str = "image", providers: Mapping | None = None, prefer: list[str] | None = None,
         settings: Mapping | None = None, min_short_side: int = 1080, duration: tuple[float, float] = (2.0, 10.0),
         orientation: str | None = "portrait", limit: int = 20, shortlist: int = 6, alternates: int = 4,
         vision: Callable | None = None, named: Mapping | None = None) -> Pick | dict:
    """Search -> rank -> resolve the shortlist -> re-rank -> (vision rerank) -> best + alternates.
    Called with mediaplan's brief dict {query, kind, providers, duration, orientation ("any" = None),
    min_short_side, paid_ok} it returns the media.json dict (Pick.to_dict()); the preferred non-stock sources in
    `providers` are built too (paid ones only with paid_ok/allow_paid; their search is a free estimate)."""
    from . import providers as registry
    if isinstance(query, Mapping):
        b = query
        prefer = list(b.get("providers") or prefer or [])
        paid = bool(b.get("paid_ok") or b.get("allow_paid"))
        if providers is None:
            extra = [n for n in prefer if n in registry.OTHER and (paid or n not in registry.PAID)]
            providers = registry.build(list(registry.FREE + registry.KEYED) + extra, settings=settings)
        o = b.get("orientation", orientation)
        return pick(str(b.get("query", "")), b.get("kind") or b.get("media") or kind, providers, prefer, settings,
                    int(b.get("min_short_side") or min_short_side), tuple(b.get("duration") or duration),
                    None if o in ("any", None, "") else o, limit, shortlist, alternates, vision,
                    {"reel": b.get("reel"), "clip": b.get("clip"), "context": b.get("at")}).to_dict()
    providers = providers if providers is not None else registry.build(settings=settings)
    names = registry.order(kind, providers, prefer)
    spec = {"min_short_side": min_short_side, "duration": duration, "orientation": orientation}
    cands, notes = gather(providers, names, query, kind, named, limit=limit, **spec)
    spec.update(context=str((named or {}).get("context") or ""), share_alike=L.share_alike_ok(settings))
    ranked = rank(cands, query, names, notes=notes, **spec)
    top = []
    for s in ranked[:shortlist]:
        c = s.cand
        try:
            c = providers[c.provider].resolve(c)
        except Exception as e:      # noqa: BLE001
            notes.append(f"resolve {c.id}: {e}")
            continue
        if c.url and not c.extra.get("rejected"):
            top.append(c)
        else:
            notes.append(f"dropped {c.id}: {c.extra.get('rejected') or 'no downloadable rendition'}")
    final = rank(top, query, names, **spec) + ranked[shortlist:]
    if vision and final:
        try:
            final = vision(final, query)
        except Exception as e:      # noqa: BLE001 - no vision = metadata order, said out loud
            notes.append(f"vision rerank skipped: {str(e)[:200]}")
    best = final[0] if final else None
    if best is None:
        notes.append(f"no allowed {kind} for {query!r}")
    return Pick(query, kind, best, final[1:1 + alternates], notes)


# --- clip segment ----------------------------------------------------------------------------------------------

def scenes(path: Path, threshold: float = 0.3, run=subprocess.run) -> list[float]:
    """Scene-cut times (s) from ffmpeg's scene score."""
    r = run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-map", "0:v:0", "-vf",
             f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600)
    return sorted({round(float(t), 3) for t in re.findall(r"pts_time:([\d.]+)", r.stderr or "")})


def best_segment(length: float, need: float, cuts: list[float] = (), flags: Callable | None = None,
                 margin: float = 0.25, edge: float = 0.5, step: float = 0.5, probe_top: int = 5) -> tuple[float, float]:
    """[start, end) of `need` seconds inside one shot of a `length`-second clip. flags(t) -> {"faces": n,
    "text": n} for the frame at t (None = no check). Deterministic for the same inputs."""
    need = min(need, length)
    if length <= need + 2 * edge:
        s = max(0.0, (length - need) / 2)
        return round(s, 3), round(s + need, 3)
    bounds = [0.0] + [c for c in sorted(cuts) if 0 < c < length] + [length]
    wins = []
    for a, b in zip(bounds, bounds[1:]):
        lo, hi = max(a + (margin if a > 0 else 0), edge), min(b - (margin if b < length else 0), length - edge)
        if hi - lo < need:
            continue
        mid, n = (lo + hi) / 2, int((hi - lo - need) / step) + 1
        for s in sorted({round(mid - need / 2, 3), *(round(lo + k * step, 3) for k in range(n))}):
            wins.append((min(1.0, (b - a) / 6.0) - 0.05 * abs(s + need / 2 - mid), s))
    if not wins:                                # no shot is long enough: the longest shot's start
        a, b = max(zip(bounds, bounds[1:]), key=lambda ab: (ab[1] - ab[0], -ab[0]))
        s = min(max(a, 0.0), length - need)
        return round(s, 3), round(s + need, 3)
    wins.sort(key=lambda w: (-round(w[0], 6), w[1]))
    if flags:
        rescored = []
        for base, s in wins[:probe_top]:
            f = flags(s + need / 2) or {}
            rescored.append((base - 0.4 * min(int(f.get("faces", 0)), 2) - 0.3 * bool(f.get("text")), s))
        wins = sorted(rescored, key=lambda w: (-round(w[0], 6), w[1]))
    return wins[0][1], round(wins[0][1] + need, 3)


def apple_flags(path: Path) -> Callable | None:
    """flags(t) for best_segment via Apple Vision: sizeable faces (>8% of height) and confident text lines."""
    try:
        import Vision
        from ..face import FaceUnavailable, VisionBackend, frames_at
        vb = VisionBackend()
    except Exception:               # noqa: BLE001 - not macOS / no pyobjc: segment pick still works
        return None

    def flags(t: float) -> dict:
        try:
            img = frames_at(path, [t])[0]
        except Exception:           # noqa: BLE001
            return {}
        fr, tr = Vision.VNDetectFaceRectanglesRequest.alloc().init(), Vision.VNRecognizeTextRequest.alloc().init()
        tr.setRecognitionLevel_(1)  # fast
        h = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(vb.cgimage(img), None)
        ok, _ = h.performRequests_error_([fr, tr], None)
        if not ok:
            return {}
        faces = [o for o in fr.results() or [] if o.boundingBox().size.height > 0.08]
        return {"faces": len(faces), "text": len([o for o in tr.results() or [] if o.confidence() > 0.5])}
    _ = FaceUnavailable
    return flags


# --- normalize to the reel -----------------------------------------------------------------------------------

def frame_stats(path: Path, t: float = 0.0, frames: int = 5, run=subprocess.run) -> dict:
    """Mean luma (YAVG), the 10-90 % luma range and mean saturation over a few frames (ffmpeg signalstats)."""
    r = run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", str(frames),
             "-vf", "signalstats,metadata=print:file=-", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120)
    vals: dict[str, list[float]] = {}
    for k, v in re.findall(r"lavfi\.signalstats\.(YAVG|YLOW|YHIGH|SATAVG)=([\d.]+)", r.stdout or ""):
        vals.setdefault(k, []).append(float(v))
    m = {k: sum(v) / len(v) for k, v in vals.items()}
    return {"y": m.get("YAVG", 0.0), "range": m.get("YHIGH", 0.0) - m.get("YLOW", 0.0), "sat": m.get("SATAVG", 0.0)}


def grade_filter(src: Mapping | None = None, ref: Mapping | None = None, tone: Mapping | None = None) -> str:
    """eq (+ colorbalance for the preset temp) moving `src` stats toward `ref`; every step clamped small."""
    def clamp(x, lo, hi):
        return max(lo, min(hi, x))
    b, c, s = 0.0, 1.0, float((tone or {}).get("sat", 1.0))
    if src and ref and src.get("y"):
        b = clamp((ref["y"] - src["y"]) / 255 * 0.6, -0.08, 0.08)
        if src.get("range") and ref.get("range"):
            c = clamp(ref["range"] / src["range"], 0.9, 1.12)
        if src.get("sat") and ref.get("sat"):
            s *= clamp(ref["sat"] / src["sat"], 0.8, 1.2)
    c *= 1.0 + float((tone or {}).get("contrast", 0.0)) * 0.5
    out = f"eq=brightness={b:.3f}:contrast={clamp(c, 0.85, 1.2):.3f}:saturation={clamp(s, 0.7, 1.3):.3f}"
    if temp := float((tone or {}).get("temp", 0.0)):
        k = clamp(temp, -0.1, 0.1)
        out += f",colorbalance=rm={k * 0.5:.3f}:bm={-k * 0.5:.3f}:rh={k * 0.3:.3f}:bh={-k * 0.3:.3f}"
    return out


def _fit_graph(w: int, h: int, fit: str, grade: str, tail: str) -> list[str]:
    g = f",{grade}" if grade else ""
    if fit == "contain":                        # blurred cover behind the whole picture: nothing cropped
        return ["-filter_complex", f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},gblur=sigma=40,eq=brightness=-0.08[bg];[b]scale={w}:{h}:"
                f"force_original_aspect_ratio=decrease:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2{g}{tail}"]
    return ["-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}{g}{tail}"]


ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "4",
       "-movflags", "+faststart", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1"]


def normalize_clip(src: Path, dst: Path, segment: tuple[float, float], w: int = 1080, h: int = 1920, fps: int = 30,
                   fit: str = "cover", grade: str = "", run=subprocess.run) -> Path:
    """The insert as the reel wants it: trimmed, cover-cropped (or blur-padded), CFR fps, graded, silent, H.264."""
    s, e = segment
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{s:.3f}", "-i", str(src), "-t", f"{e - s:.3f}", "-an",
           *_fit_graph(w, h, fit, grade, f",fps={fps},setsar=1,format=yuv420p"), "-r", str(fps), "-fps_mode", "cfr",
           *ENC, str(dst)]
    r = run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise RuntimeError(f"normalize_clip failed: {(r.stderr or '')[-300:]}")
    return dst


def normalize_image(src: Path, dst: Path, w: int = 1080, h: int = 1920, fit: str = "cover", grade: str = "",
                    headroom: float = 1.0, run=subprocess.run) -> Path:
    """A still at the reel size x headroom (room for Ken Burns), cover-cropped or blur-padded, graded."""
    W, H = int(round(w * headroom / 2)) * 2, int(round(h * headroom / 2)) * 2
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), *_fit_graph(W, H, fit, grade, ",setsar=1"),
           "-frames:v", "1", "-fflags", "+bitexact", "-map_metadata", "-1", str(dst)]
    r = run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(f"normalize_image failed: {(r.stderr or '')[-300:]}")
    return dst


# --- fetch + segment for the resolver (mediaplan.default_fetch looks for select.fetch) ---------------------------

def fetch(c, approved: bool = False, segment: tuple[float, float] | None = None, settings: Mapping | None = None,
          providers: Mapping | None = None) -> Path:
    """Local file for a Candidate (or its media.json dict) through its provider. A video longer than LONG_S
    without a segment downloads a WINDOW_S window from 25 % in (scene/segment picking then runs inside it), never
    the whole film. Paid candidates raise ApprovalRequired unless approved=True."""
    from . import providers as registry
    d = c if isinstance(c, Mapping) else c.to_dict()
    if d.get("path") and Path(d["path"]).is_file():
        return Path(d["path"])
    cand = Candidate.from_dict(d)
    p = (providers or {}).get(cand.provider) or registry.make(cand.provider, settings)
    if p is None:
        raise RuntimeError(f"media provider {cand.provider!r} is not available")
    if cand.kind == "video" and not cand.url and hasattr(p, "resolve"):
        cand = p.resolve(cand)
    seg = segment or (tuple(d["segment_window"]) if d.get("segment_window") else None)
    if cand.kind == "video" and not seg and cand.duration > LONG_S:
        s = round(cand.duration * 0.25, 3)
        seg = (s, round(min(cand.duration, s + WINDOW_S), 3))
    kw = {"segment": seg, "approved": approved}
    try:
        params = inspect.signature(p.fetch).parameters
        kw = {k: v for k, v in kw.items() if k in params and v}
    except (TypeError, ValueError):
        kw = {}
    if cand.cost_usd > 0 and not approved:
        from .base import ApprovalRequired
        raise ApprovalRequired(f"{cand.id}: ~${cand.cost_usd:.2f} needs the creator's approval")
    out = p.fetch(cand, **kw)
    return Path(getattr(out, "path", out))


def clip_segment(path: Path, need: float, flags: bool = True) -> tuple[float, float]:
    """[start, end) of `need` seconds in a local clip: scene cuts + (Apple Vision) faces/text check."""
    from . import media_duration
    path = Path(path)
    return best_segment(media_duration(path), need, scenes(path), apple_flags(path) if flags else None)


from .vision import STRIP_ENV, STRIP_ENV_PREFIX, VISION_PROMPT, claude_env, parse_scores, vision_rerank  # noqa: E402,F401
