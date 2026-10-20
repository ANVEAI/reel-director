"""Fit a real B-roll clip to the spoken line and to its pane (v4 final round: the panel's timing + scale must-fixes).

payoff(path): the onset (media seconds) of the clip's strongest visual event after its opening - the checkmark that
  pops, the counter that lands. Mean |frame difference| per frame on a 108x192 grey proxy; the peak of a 3-frame mean
  after the opening (max(OPEN_S, 20 % of the clip)), walked back to where the change first reaches half the peak.
  None when nothing stands out (a steady shot keeps its scene-cut segment).
hit(words, trigger): the reel time that payoff lands on: a result word ("finished", "done", "ready" ...) spoken
  inside the insert, else the longest content word after the noun that triggered it, in the first 60 % of the insert.
align(peak, hit_t, s, dur): the media start that puts the payoff on the hit, clamped inside the clip.
payoff_xy(path, duration, t): where in the picture that event happens (x, y fractions): the beat zooms about it.
rows(path) / cols(path): salience per row / column (mean gradient energy over a few frames, floor removed).
offset(sal, scaled, pane, band, soft): the cover offset (object-position %) that keeps the most salience inside
  [band) of the pane - above the captions in a split pane, inside a device screen - without cutting a block of
  content in two (a UI panel stays whole rather than trading its top row for a stray label below), and away from
  the band's first `soft` px (the platform header) when the content can sit lower.
held(path, seg0, play, hold, dst): the clip's used window with its last frame held `hold` s (a bridged insert runs
  to the cut), re-encoded with the source's BT.709 tags so the browser shows the same colours throughout (a PNG
  still of the last frame decoded with another matrix and visibly jumped).
Deterministic: ffmpeg decodes, numpy measures, results are cached per (path, mtime).
"""
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import lexicon as lx

W8, H8 = 108, 192                   # grey proxy (1/10 of the reel)
OPEN_S, HALF, MIN_RISE = 0.6, 0.5, 1.6
HIT_SPAN = 0.6                      # the hit word sits in the first 60 % of the insert
RESULT = frozenset("""done finished ready built complete completed fixed solved sorted saved live launched shipped
published posted doubled tripled grew won works working gone booked sold""".split())


@lru_cache(maxsize=48)
def _grey(path: str, mtime: float) -> np.ndarray:
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vf",
                              f"scale={W8}:{H8}:flags=area,format=gray", "-f", "rawvideo", "pipe:1"],
                             capture_output=True, timeout=180).stdout
    except (OSError, subprocess.SubprocessError):
        return np.zeros((0, H8, W8), np.float32)
    n = len(raw) // (W8 * H8)
    return np.frombuffer(raw[: n * W8 * H8], np.uint8).reshape(n, H8, W8).astype(np.float32)


def frames(path) -> np.ndarray:
    p = Path(path)
    try:
        return _grey(str(p), p.stat().st_mtime)
    except OSError:
        return np.zeros((0, H8, W8), np.float32)


def payoff(path, duration: float) -> float | None:
    """Onset (s) of the strongest change after the opening, or None (see the module doc)."""
    f = frames(path)
    if len(f) < 8 or duration <= 0:
        return None
    fps = len(f) / duration
    e = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))          # e[i]: the change that shows on frame i + 1
    sm = np.convolve(e, np.ones(3) / 3, mode="same")
    lo = int(round(max(OPEN_S, 0.2 * duration) * fps))
    if lo >= len(e) - 2:
        return None
    i = lo + int(np.argmax(sm[lo:]))
    j = max(range(max(lo, i - 1), min(len(e), i + 2)), key=lambda k: (e[k], -k))
    if sm[i] < MIN_RISE * max(float(np.median(e)), 0.05):
        return None
    k = j
    while k - 1 >= lo and e[k - 1] >= HALF * e[j]:
        k -= 1
    return round((k + 1) / fps, 3)


def payoff_xy(path, duration: float, t: float) -> tuple[float, float] | None:
    """Centroid (x, y fractions) of the change over the 0.25 s after the payoff onset t, or None."""
    f = frames(path)
    if len(f) < 3 or duration <= 0:
        return None
    fps = len(f) / duration
    i0 = max(1, min(len(f) - 1, int(round(t * fps))))
    d = np.abs(np.diff(f[i0 - 1:min(len(f), i0 + int(round(0.25 * fps)) + 1)], axis=0)).sum(axis=0)
    if float(d.sum()) <= 0:
        return None
    ys, xs = np.mgrid[:H8, :W8]
    return round(float((d * xs).sum() / d.sum() + 0.5) / W8, 4), round(float((d * ys).sum() / d.sum() + 0.5) / H8, 4)


def hit(words: list[tuple[str, float]], s: float, e: float) -> float | None:
    """words = [(text, reel start)] spoken in [s, e), the trigger noun first. The payoff's word time, or None."""
    after = [(t, w) for t, w in words[1:] if s <= w < e]
    res = [w for t, w in after if lx.bare(t) in RESULT]
    if res:
        return res[0]
    early = [(len(lx.bare(t)), -w, w) for t, w in after if lx.is_content(t) and w <= s + HIT_SPAN * (e - s)]
    return max(early)[2] if early else None


def align(peak: float, hit_t: float, s: float, dur: float, keep: float = 1.2) -> float:
    """Media start that shows the payoff at hit_t; never before the clip, never so late that < keep s remain."""
    return round(min(max(0.0, peak - (hit_t - s)), max(0.0, dur - keep)), 3)


def _sal(path, axis: int) -> np.ndarray:
    f = frames(path)
    if not len(f):
        return np.zeros(H8 if axis == 1 else W8)
    pick = f[np.linspace(0, len(f) - 1, min(len(f), 8)).round().astype(int)]
    g = np.abs(np.diff(pick, axis=1, append=pick[:, -1:, :])) + np.abs(np.diff(pick, axis=2, append=pick[:, :, -1:]))
    v = g.mean(axis=(0, axis + 1))
    return np.clip(v - np.percentile(v, 20), 0, None)


def rows(path) -> np.ndarray:
    return _sal(path, 1)


def cols(path) -> np.ndarray:
    return _sal(path, 0)


def blocks(sal: np.ndarray, frac: float = 0.12, gap: int = 4) -> np.ndarray:
    """Block id per row (-1 = background): runs of salient rows, gaps of <= `gap` rows closed."""
    on = sal > frac * float(sal.max()) if len(sal) and sal.max() > 0 else np.zeros(len(sal), bool)
    idx = np.flatnonzero(on)
    out, cur = np.full(len(sal), -1), -1
    for k, i in enumerate(idx):
        cur += 1 if k == 0 or i - idx[k - 1] > gap + 1 else 0
        lo = idx[k - 1] + 1 if k and i - idx[k - 1] <= gap + 1 else i
        out[lo:i + 1] = cur
    return out


def offset(sal: np.ndarray, scaled: float, pane: float, band: tuple[float, float] | None = None,
           soft: float = 0.0) -> float:
    """object-position % on one axis: the cover offset o in [pane - scaled, 0] that puts the most salience inside
    [band) of the pane (default: the whole pane), a block cut by the band's edge paying twice its outside part,
    the band's first `soft` px counting 60 %; ties keep the centred offset. 50 when nothing overflows."""
    slack = pane - scaled
    if slack > -1 or not len(sal) or float(sal.sum()) <= 0:
        return 50.0
    b0, b1 = band or (0.0, pane)
    pos, blk = (np.arange(len(sal)) + 0.5) / len(sal) * scaled, blocks(sal)
    best = None
    for o in np.arange(slack, 0.01, 4.0):
        y = o + pos
        inside = (y >= b0) & (y < b1)
        cut = np.isin(blk, np.unique(blk[inside & (blk >= 0)])) & ~inside & (blk >= 0)
        score = float((sal * np.where(y < b0 + soft, 0.6, 1.0))[inside].sum()) - 2.0 * float(sal[cut].sum())
        key = (-round(score, 3), abs(o - slack / 2))
        if best is None or key < best[0]:
            best = (key, o)
    return round(float(best[1] / slack * 100), 2)


def held(path, seg0: float, play: float, hold: float, dst: Path) -> Path | None:
    """[seg0, seg0 + play) of the clip + its last frame held `hold` s, H.264 CRF 16 BT.709, deterministic; or None."""
    dst = Path(dst)
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.stem}.part.mp4")
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{seg0:.3f}", "-t", f"{play:.3f}",
                        "-i", str(path), "-an", "-vf", f"tpad=stop_mode=clone:stop_duration={hold:.3f},setsar=1",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-threads", "1",
                        "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                        "-movflags", "+faststart", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1",
                        str(tmp)], capture_output=True, timeout=300)
    if r.returncode or not tmp.exists():
        return None
    tmp.replace(dst)
    return dst
