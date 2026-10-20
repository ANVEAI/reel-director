"""Pure geometry helpers of the face-aware layout (split out of layout.py; layout re-exports every name):
title window, resolution cap, face-track loading, background busyness, face boxes and box utilities, and the
VISUALS hook attributes. Deterministic; no state."""
import html
import json
import math
import subprocess
from pathlib import Path

import numpy as np

DUR_SLACK = 0.25                          # face track vs take length (s)
TITLE_DUR, TITLE_SNAP = 2.5, 0.3          # council 6: title 0-2.5 s; its out snaps onto a word start within 0.3 s


def title_window(tl, si: int, c, D: float) -> tuple[float, float]:
    """A title's [in, out): frame 0 for the first shot (else its word), held TITLE_DUR, out snapped onto the nearest
    word start within TITLE_SNAP that does not leave a one-word sentence tail (captions resume on a fresh chunk)."""
    p = tl.shots[si]
    s = 0.0 if si == 0 else p.words[c.start_word].start
    e = min(D, s + float(c.params.get("dur", TITLE_DUR)))
    ws = [(w.text, t.start) for q in tl.shots for w, t in zip(q.shot.words, q.words)]
    for _, k in sorted((abs(t - e), k) for k, (_, t) in enumerate(ws) if s + 1.0 < t and abs(t - e) <= TITLE_SNAP + 1e-6):
        if not (ws[k][0][-1:] in ".!?" and k and ws[k - 1][0][-1:] not in ".!?"):
            return s, ws[k][1]
    return s, e


def res_cap(crop_w: int) -> float:
    """Council Z3 resolution guard: total magnification <= 1.10 x cropW / 1080 (1.10 when unknown)."""
    return 1.10 * crop_w / 1080 if crop_w else 1.10


def load_face(src, duration: float | None = None) -> tuple[dict | None, str | None]:
    """The take's face track, or (None, why). A track whose length disagrees with the take is someone
    else's (a renamed prep) and is ignored."""
    src = Path(src)
    for p in (src.with_name(src.stem + ".face.json"), src.parent.parent / "qa" / f"{src.stem}.face.json"):
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            return None, f"{p.name}: unreadable"
        if d.get("version") != 1 or not d.get("frames") or not d.get("w") or not d.get("h"):
            return None, f"{p.name}: not a v1 face track"
        dt = d.get("step", 1) / d.get("fps", 30)
        if duration and abs(len(d["frames"]) * dt - duration) > DUR_SLACK + dt:
            return None, f"{p.name}: {len(d['frames']) * dt:.2f}s track for a {duration:.2f}s take"
        return d, None
    return None, "no face track"


def busyness(src, t: float, box, size: tuple[int, int]) -> float | None:
    """0..1 busyness of the take behind `box` ([x0, y0, x1, y1], take px) at media time t: share of strong
    luma edges (/ 0.12) and luma spread (/ 0.20), 60/40. Real takes: word-cloud poster 0.93, bare wall 0.04."""
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    w, h = (min(size[0], int(box[2])) - x0) // 4 * 4, (min(size[1], int(box[3])) - y0) // 4 * 4
    if w < 16 or h < 16:
        return None
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1", "-vf",
                              f"crop={w}:{h}:{x0}:{y0},scale={w // 2}:{h // 2},format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if len(raw) != (w // 2) * (h // 2):
        return None
    a = np.frombuffer(raw, np.uint8).reshape(h // 2, w // 2).astype(float) / 255
    g = np.hypot(np.abs(np.diff(a, axis=1))[:-1], np.abs(np.diff(a, axis=0))[:, :-1])
    return round(min(1.0, 0.6 * min(1.0, float((g > 0.08).mean()) / 0.12) + 0.4 * min(1.0, float(a.std()) / 0.20)), 3)


def _feat(fr: dict) -> list[float]:
    """Eyes + nose + mouth (take px, unpadded), a superset of VISION's and QA's cores: inner 76 % of the face
    width or pupils +- 0.40 x pupil distance, eye line - max(8 % face h, 0.12 ipd) to the mouth + max(11 % face h,
    0.30 ipd). Measured on the real takes: Vision's eye/nose/lip landmark box sits inside it."""
    x, y, w, h = fr["box"]
    (lx, ly), (rx, ry) = sorted(fr["eyes"])
    ipd = max(math.hypot(rx - lx, ry - ly), 1.0)
    return [min(x + 0.12 * w, lx - 0.40 * ipd), min(ly, ry) - max(0.08 * h, 0.12 * ipd),
            max(x + 0.88 * w, rx + 0.40 * ipd), fr["mouth"][1] + max(0.11 * h, 0.30 * ipd)]


def _head(fr: dict) -> list[float]:
    """Forehead (box top) to chin, full face width (take px); a beard hangs 0.35 ipd below the jaw (VISION)."""
    x, y, w, h = fr["box"]
    ipd = math.hypot(fr["eyes"][1][0] - fr["eyes"][0][0], fr["eyes"][1][1] - fr["eyes"][0][1])
    return [x, y, x + w, max(float(fr.get("chin_y") or 0.0) + 0.35 * ipd, y + h)]


def _map(b, A, B, pad=(0.0, 0.0, 0.0, 0.0)):
    return [A * b[0] + B[0] - pad[0], A * b[1] + B[1] - pad[1], A * b[2] + B[0] + pad[2], A * b[3] + B[1] + pad[3]]


def _union(bs):
    bs = list(bs)
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)] if bs else None


def _hit(a, b) -> float:
    """Intersection area of two [x0, y0, x1, y1] boxes."""
    if not a or not b:
        return 0.0
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def xywh(b) -> list[int]:
    x0, y0 = round(b[0]), round(b[1])
    return [x0, y0, round(b[2]) - x0, round(b[3]) - y0]


def _box(x, y, w, h):
    return [x, y, x + w, y + h]


def css_vars(b, prefix="") -> str:
    x, y, w, h = xywh(b)
    return f"--{prefix}x:{x}px;--{prefix}y:{y}px;--{prefix}w:{w}px;--{prefix}h:{h}px"


def data_attrs(kind: str, params: dict | None, b, extra_css: str = "") -> str:
    """The VISUALS hook on a cue element: data-kind, data-params (JSON, 'why' dropped) and the box vars."""
    prm = {k: v for k, v in (params or {}).items() if k != "why"}
    js = html.escape(json.dumps(prm, ensure_ascii=False, sort_keys=True), quote=True)
    return f' data-kind="{html.escape(kind)}" data-params="{js}" style="{css_vars(b)}{extra_css}"'
