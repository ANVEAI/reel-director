"""Style reference (LEARN): measure videos the user supplies -> style-ref.json that can seed a preset override.

Visual changes are single-frame difference spikes (cuts, punches, card in/out); the caption band is where strong
edges keep changing in the lower frame; faces come from the same backend as the creator profile (Apple Vision on
macOS), giving the B-roll share (shots where the face is gone) and whether captions sit over the face. Speech rate
and the voice-over-bed level need a transcript (mlx-whisper, optional). Local files only: nothing is downloaded.
Run it through `python -m reel_director.learn reference <video> ... --out style-ref.json`.
"""
import math
import statistics
from pathlib import Path

import numpy as np

from .learn import FACE_PAD, _med, _r, face_backend, frames, framing, speech_rate
from .pace import CV_FAIL
from .presets import PACE

# A cut: a single-frame mean-difference spike >= 12/255, >= 6x its +-0.5 s neighbourhood, >= 2x either neighbour.
CUT_MIN, CUT_K, CUT_ISO = 12.0, 6.0, 2.0
CAPTION_SCAN = (0.40, 0.95)               # the lower frame, where captions live
CAPTION_MIN = 0.001                       # band score (edge change x edge density) below this: no captions
BROLL_CAP = {"calm": 0.15, "standard": 0.25, "punchy": 0.35}   # council: never padded to reach it
ZONES = ("below-chin", "above-head", "lower-band")
FACE_FPS = 4                              # face samples per second (B-roll share, caption-vs-face)


def visual_changes(gray: np.ndarray, fps: float) -> list[float]:
    """Instant picture changes (cuts, punches, card in/out): single-frame mean-difference spikes. A dissolve spreads
    its change over many frames and is not counted (council 5 keeps >= 90 % hard cuts)."""
    d = np.abs(np.diff(gray.astype(np.float32), axis=0)).mean(axis=(1, 2))
    win, out = max(1, int(round(fps / 2))), []
    for i, v in enumerate(d):
        near = np.concatenate([d[max(0, i - win):i], d[i + 1:i + 1 + win]])
        side = max(d[i - 1] if i else 0.0, d[i + 1] if i + 1 < len(d) else 0.0)
        if v >= CUT_MIN and v >= CUT_K * max(float(np.median(near)) if near.size else 0.0, 0.5) and v >= CUT_ISO * side:
            t = (i + 1) / fps
            if not out or t - out[-1] > 0.2:
                out.append(round(t, 3))
    return out


def caption_band(gray: np.ndarray, scan=CAPTION_SCAN) -> dict | None:
    """Where captions sit: rows whose strong edges keep changing (text swaps every chunk) AND are dense (text),
    in the lower frame; a busy static poster (dense, still) and gestures (moving, smooth) both score low."""
    g = gray.astype(np.float32)
    if len(g) < 3:
        return None
    E = np.maximum(np.abs(np.diff(g, axis=2))[:, :-1, :], np.abs(np.diff(g, axis=1))[:, :, :-1]) > 60
    calm = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2)) < 8          # drop frame pairs across a cut
    if calm.sum() < 2:
        return None
    H, W = E.shape[1], E.shape[2]
    x0, x1 = int(0.1 * W), int(0.9 * W)
    chg = (E[1:] ^ E[:-1])[calm][:, :, x0:x1].mean(axis=(0, 2))
    den = E[:, :, x0:x1].mean(axis=(0, 2))
    score = np.convolve(chg * den, np.ones(5) / 5, mode="same")
    lo, hi = int(scan[0] * H), int(scan[1] * H)
    k = lo + int(np.argmax(score[lo:hi]))
    if score[k] < CAPTION_MIN:
        return None
    a = b = k
    while a > lo and score[a - 1] >= 0.3 * score[k]:
        a -= 1
    while b < hi - 1 and score[b + 1] >= 0.3 * score[k]:
        b += 1
    return {"y0": _r(a / H), "y1": _r((b + 1) / H), "center_y": _r((a + b + 1) / 2 / H), "score": _r(score[k], 4)}


def caption_zone(band: dict | None, fr: dict | None) -> str | None:
    """Map the reference's caption band onto our zones: 'over-face' when it covers eyes-to-mouth (+6 % pad),
    'below-chin' when it hugs the face from below (top within 8 % H of the padded chin), else 'lower-band'."""
    if band is None:
        return None
    if fr is None:
        return "lower-band" if band["y0"] >= 0.66 else "below-chin"
    pad = FACE_PAD * fr["face_h"]
    core_top, core_bot = fr["eye_y"] - 0.05 * fr["face_h"] - pad, fr["mouth_y"] + 0.05 * fr["face_h"] + pad
    if band["y1"] <= core_top:
        return "above-head"
    if band["y0"] >= core_bot:
        return "below-chin" if band["y0"] <= max(fr["chin_y"] + pad, core_bot) + 0.08 else "lower-band"
    return "over-face"


def nearest_pace(median_gap: float | None) -> str:
    if not median_gap:
        return "calm"
    return min(PACE, key=lambda p: abs(math.log(median_gap / PACE[p]["S"])))


def bed_levels(media: Path, words: list[dict]) -> dict | None:
    """Voice vs music-bed loudness: 400 ms blocks inside words vs blocks >= 150 ms clear of any word. Whisper
    stretches words over short pauses, so the bed is reported only with >= 0.5 s of clear blocks."""
    from .levels import block_loudness
    from .takecheck import decode_audio
    if not words:
        return None
    bl = block_loudness(decode_audio(media))
    c = np.arange(len(bl)) * 0.1 + 0.2
    dist = np.min([np.maximum(0, np.maximum(w["s"] - c, c - w["e"])) for w in words], axis=0)

    def pw(m):
        m = m & (bl > -70)
        return float(-0.691 + 10 * np.log10(np.mean(10 ** ((bl[m] + 0.691) / 10)))) if m.sum() >= 5 else None
    voice, bed = pw(dist == 0), pw(dist >= 0.15)
    return {"voice_lufs": _r(voice, 1), "bed_lufs": _r(bed, 1), "speech_share": _r(np.mean(dist == 0), 2),
            "voice_over_bed_lu": _r(voice - bed, 1) if voice is not None and bed is not None else None}


def broll_share(faces: list, fps: float, changes: list[float], duration: float) -> float:
    """Share of the runtime in shots (spans between visual changes) where >= 80 % of the face samples find no face.
    Per shot, not per sample: captions or a hand over the face make Vision miss single frames inside a face shot
    (30 % of the samples on the real-1 reel), which is occlusion, not a cutaway."""
    if not faces or duration <= 0:
        return 0.0
    edges, total = [0.0, *[t for t in changes if 0 < t < duration], duration], 0.0
    for a, b in zip(edges, edges[1:]):
        got = [f for k, f in enumerate(faces) if a <= k / fps < b]
        if b - a >= 0.5 and got and sum(1 for f in got if not f) >= 0.8 * len(got):
            total += b - a
    return total / duration


def analyze_reference(path: Path, backend=None, asr=None, max_s: float = 180.0) -> dict:
    """One reference video -> measured style. `asr(path) -> words` (None: no speech numbers)."""
    from .audio import loudness
    from .capture import probe
    from .pace import gaps_between, pace_cv
    info = probe(path)
    fps, hw, dur = info.fps or 30.0, info.height / info.width, min(info.duration, max_s)
    ch = visual_changes(frames(path, 72, max(2, int(round(36 * hw)) * 2), gray=True, limit=int(max_s * fps)), fps)
    gaps = gaps_between(ch)
    band = caption_band(frames(path, 270, int(round(135 * hw)) * 2, fps=6, gray=True, limit=int(max_s * 6)))
    backend = backend if backend is not None else face_backend()
    faces = [backend(fr) for fr in frames(path, 540, int(round(270 * hw)) * 2, fps=FACE_FPS, limit=int(max_s * 4))
             ] if backend else []
    fr = framing(faces, info.width, info.height) if faces else None
    speech, bed = None, None
    if asr is not None and info.has_audio:
        try:
            words = asr(path)
            speech, bed = speech_rate(words), bed_levels(path, words)
        except Exception as e:   # noqa: BLE001 - ASR is best-effort: the reference still has its picture numbers
            speech = {"error": str(e)[:200]}
    loud = loudness(path) if info.has_audio else None
    return {"file": path.name, "duration": _r(dur, 2), "size": [info.width, info.height], "fps": _r(fps, 2),
            "visual_changes": ch, "changes_per_min": _r(len(ch) / dur * 60, 1) if dur else None,
            "median_gap_s": _r(statistics.median(gaps), 2) if gaps else None, "cv": _r(pace_cv(ch), 2),
            "first_change_s": ch[0] if ch else None, "caption_band": band, "caption_zone": caption_zone(band, fr),
            "face_present": fr["present"] if fr else (0.0 if backend else None),
            "broll_share": _r(broll_share(faces, FACE_FPS, ch, dur), 3) if backend else None,
            "face": {k: fr[k] for k in ("eye_y", "face_h", "chin_y", "center_x")} if fr else None,
            "speech": speech, "levels": bed,
            "loudness": {"lufs": loud["I"], "true_peak": loud["tp"]} if loud else None}


def style_reference(paths: list[Path], backend=None, asr=None) -> dict:
    refs = [analyze_reference(Path(p), backend, asr) for p in paths]
    gaps = _med(r["median_gap_s"] for r in refs)
    pace = nearest_pace(gaps)
    share = _med(r["broll_share"] for r in refs)
    zones = [r["caption_zone"] for r in refs if r["caption_zone"]]
    zone = max(sorted(set(zones)), key=zones.count) if zones else None
    notes = []
    if zone == "over-face":
        notes.append("reference captions cover the face: not copied (faces are sacred); using below-chin")
    cv = _med(r["cv"] for r in refs)
    if cv is not None and cv < CV_FAIL:
        notes.append(f"reference rhythm is metronomic (CV {cv:.2f} < {CV_FAIL}): its pace is used, not its rhythm")
    broll = round(min(share, BROLL_CAP[pace]), 2) if share is not None else None
    if share is not None and share > BROLL_CAP[pace]:
        notes.append(f"reference cuts away from the face {share:.0%} of the time; capped at {BROLL_CAP[pace]:.0%} "
                     f"({pace}, never padded)")
    return {"version": 1, "references": refs,
            "measured": {"median_gap_s": _r(gaps, 2), "cv": _r(cv, 2),
                         "changes_per_min": _r(_med(r["changes_per_min"] for r in refs), 1),
                         "broll_share": _r(share, 3), "caption_zone": zone,
                         "wpm": _r(_med((r["speech"] or {}).get("wpm") for r in refs), 1)},
            "preset_overrides": {"pace": pace, "caption_zone": zone if zone in ZONES else "below-chin",
                                 **({"broll_share": broll} if broll is not None else {})},
            "notes": notes}


