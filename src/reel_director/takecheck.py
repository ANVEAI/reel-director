"""Take QA: is a fresh take technically usable, and did the creator read the script?

Runs in a subprocess right after a take lands in the studio. It transcribes with mlx-whisper
(through the `transcribe` helper) and never imports torch: mlx must be the first of the two
in a process, and word timestamps are enough for a QA verdict (prep does the VAD snapping).

Thresholds come from the studio spec; the evidence behind each is noted where it isn't obvious.
"""
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

import numpy as np

from . import face as facetrack
from .capture import SourceInfo, effective_9x16, probe
from .cleanup import keep_segments, score_take, snap_to_speech
from .schema import ScriptError, Shot, load_script
from .timing import Alignment, align, estimate

MIN_COVERAGE = 0.85    # matches compile's "re-record?" warning
CLIP_DBFS = -0.3       # a sample this close to full scale counts as clipped...
CLIP_SAMPLES = 10      # ...and more than this many is audible clipping, not one hot transient
SILENT_LUFS = -40.0    # a real mic at speaking distance reads about -30..-16 LUFS
SNR_FAIL = 15.0
SNR_WARN = 25.0
LUMA_DARK = 60         # full-range luma of the 9:16 crop
LUMA_BRIGHT = 200
# blurdetect mean at <= 1080 px wide. Measured on synthetic charts: ~4-5 sharp, ~7 at gaussian
# sigma 2, ~8.4 at sigma 3. Retune on real takes; it only ever warns.
BLUR_WARN = 8.0
SUBJECT = (0.25, 0.12, 0.75, 0.62)   # x0, y0, x1, y1 of the 9:16 crop: a talking head (exposure)
FOCUS = (0.30, 0.22, 0.70, 0.55)     # tighter, so a defocused background doesn't read as a soft lens
BLOWN_OUT = 0.25       # share of the crop at 250+ luma: blown highlights whatever the subject reads
MIN_FPS = 24
LONG_TAKE = 3.0        # x the estimated read
DROPPED_WARN = 3       # dropped camera frames before stutter is worth mentioning
SR = 48000
WINDOW = 0.05          # audio analysis window, seconds
SAMPLE_FPS = 2         # video frames analysed per second
SPEECH_FRAME = 0.02    # speech detection for word snapping: frame size,
SPEECH_ABOVE = 0.35    # threshold as a share of the SNR above the floor (clamped to 6-15 dB),
SPEECH_GAP = 0.15      # shorter silences merge, spans are padded, and blips (clicks) are dropped
SPEECH_PAD = 0.03
SPEECH_MIN = 0.08

# Framing, from the face track (face.py). The auto-reframe zooms up to face.REFRAME_MAX to put the
# eye line at 0.40 H; only what it can't reach gets a coaching note. Face height is the face box
# over the frame height: the founder's MacBook takes measure 0.19-0.20, which leaves room for
# captions under the chin once the eye line is at 0.40.
FACE_PRESENT = 0.8     # face found in at least this share of the take
FACE_SMALL = 0.12
FACE_LARGE = 0.30
FACE_TARGET = 0.20
OFF_CENTRE = 0.08      # face centre this far (share of the width) from the middle

VIRTUAL_MIC = re.compile(r"BlackHole|Zoom|Teams|Loom|Aggregate|Multi-Output|Virtual|Soundflower", re.I)
BLUETOOTH_MIC = re.compile(r"AirPods|Bluetooth|Beats|Buds|Headset|Hands-?Free|Jabra|Bose", re.I)


def _ff(args: list[str]) -> subprocess.CompletedProcess:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True)
    if r.returncode != 0:
        tail = r.stderr.decode(errors="replace").strip().splitlines()[-3:]
        raise RuntimeError("ffmpeg failed: " + " / ".join(tail))
    return r


# --- measurements ---------------------------------------------------------------------------

def video_stats(media: Path, width: int, height: int) -> dict:
    """Exposure and sharpness of the part of the frame that survives the 9:16 crop.

    Judged on the subject window (centre-upper part of the crop, where a talking head sits):
    a white wall or a defocused background around a well-lit, sharp face is not a problem.
    The whole crop's mean is still reported, and its highlights catch blown-out frames.
    """
    ew, eh = effective_9x16(width, height)
    cw, ch = max(2, ew // 2 * 2), max(2, eh // 2 * 2)
    k = min(1.0, 1080 / cw)
    x0, y0, x1, y1 = FOCUS
    sw, sh = max(2, int(cw * (x1 - x0)) // 2 * 2), max(2, int(ch * (y1 - y0)) // 2 * 2)
    bw, bh = max(2, int(sw * k) // 2 * 2), max(2, int(sh * k) // 2 * 2)
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "blur.txt"
        graph = (f"[0:v]fps={SAMPLE_FPS},crop={cw}:{ch},split[a][b];"
                 f"[a]scale=108:192:flags=area,format=gray[l];"
                 f"[b]crop={sw}:{sh}:{int(cw * x0)}:{int(ch * y0)},scale={bw}:{bh}:flags=area,"
                 f"blurdetect=block_width=32:block_height=32,metadata=print:key=lavfi.blur:file='{log}'[s]")
        r = _ff(["-v", "error", "-i", str(media), "-filter_complex", graph, "-map", "[l]", "-f", "rawvideo", "pipe:1",
                 "-map", "[s]", "-f", "null", "-"])
        found = re.findall(r"lavfi\.blur=(\S+)", log.read_text()) if log.exists() else []
    blur = [b for b in map(float, found) if np.isfinite(b)]   # nan: a frame with no edges at all
    luma = np.frombuffer(r.stdout, dtype=np.uint8)
    if not luma.size:
        raise RuntimeError("no video frames decoded")
    frames = luma[: luma.size // (108 * 192) * 108 * 192].reshape(-1, 192, 108)
    x0, y0, x1, y1 = SUBJECT
    subject = frames[:, int(192 * y0):int(192 * y1), int(108 * x0):int(108 * x1)]
    return {"effective_9x16": [ew, eh], "luma_mean": round(float(luma.mean()), 1),
            "luma_p5": round(float(np.percentile(luma, 5)), 1), "luma_p95": round(float(np.percentile(luma, 95)), 1),
            "subject_luma": round(float(subject.mean()), 1) if subject.size else None,
            "blown_out": round(float(np.mean(luma >= 250)), 3), "decode_errors": len(_decode_errors(r)),
            "blur": round(float(np.mean(blur)), 2) if blur else None}


def decode_audio(media: Path, mono: bool = True, errors: list[str] | None = None) -> np.ndarray:
    """Float samples. mono=False keeps every channel at the native rate, for honest peaks.
    `errors` collects the decoder's error lines (a damaged stream still decodes, with gaps)."""
    args = ["-v", "error", "-i", str(media), "-vn"] + (["-ac", "1", "-ar", str(SR)] if mono else []) + ["-f", "f32le", "pipe:1"]
    r = _ff(args)
    if errors is not None:
        errors += _decode_errors(r)
    return np.frombuffer(r.stdout, dtype="<f4")


def _decode_errors(r: subprocess.CompletedProcess) -> list[str]:
    """Error lines from an `-v error` decode: a cleanly converted take has none, while one written
    by two converters at once (a studio restart mid-normalize) has hundreds."""
    return [ln for ln in r.stderr.decode(errors="replace").splitlines() if ln.strip()]


def integrated_lufs(media: Path) -> float:
    r = _ff(["-i", str(media), "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    found = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", r.stderr.decode(errors="replace"))
    return float(found[-1]) if found and found[-1] != "-inf" else -70.0


def peak_stats(samples: np.ndarray) -> dict:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    clipped = int(np.count_nonzero(np.abs(samples) >= 10 ** (CLIP_DBFS / 20))) if samples.size else 0
    return {"peak_dbfs": round(20 * np.log10(max(peak, 1e-6)), 2), "clipped_samples": clipped}


def frame_db(mono: np.ndarray, window: float = WINDOW) -> np.ndarray:
    """RMS level (dBFS) of consecutive `window`-second frames."""
    n = int(window * SR)
    frames = mono[: len(mono) // n * n].reshape(-1, n) if len(mono) >= n else np.zeros((1, n), "<f4")
    return np.maximum(10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12), -120.0)


def noise_stats(mono: np.ndarray, words: list[dict]) -> dict:
    """Noise floor from the gaps around the words; speech level from inside them."""
    db = frame_db(mono)
    centers = (np.arange(len(db)) + 0.5) * WINDOW
    speech = np.zeros(len(db), bool)
    near = np.zeros(len(db), bool)
    for w in words:
        speech |= (centers >= w["s"]) & (centers <= w["e"])
        near |= (centers >= w["s"] - 0.1) & (centers <= w["e"] + 0.1)
    quiet = db[~near]
    # 20th percentile of the gaps: robust to a breath or a word edge Whisper placed loosely.
    noise = float(np.percentile(quiet, 20)) if len(quiet) >= 10 else float(np.percentile(db, 10))
    level = (float(10 * np.log10(np.mean(10 ** (db[speech] / 10)))) if speech.any()
             else float(np.percentile(db, 95)))
    return {"noise_floor_db": round(noise, 1), "snr_db": round(level - noise, 1)}


def speech_spans(mono: np.ndarray, noise_db: float, snr_db: float) -> list[tuple[float, float]]:
    """Where the voice is, from 20 ms frame levels: prep snaps Whisper's words to Silero VAD,
    but Silero imports torch, which this mlx process must never load.

    Speech is anything clearly above the room (6-15 dB, scaled with the SNR); gaps under
    SPEECH_GAP merge and spans get SPEECH_PAD each side, as in audio.speech_spans.
    """
    db = frame_db(mono, SPEECH_FRAME)
    on = np.concatenate([[False], db > noise_db + float(np.clip(SPEECH_ABOVE * snr_db, 6.0, 15.0)), [False]])
    edges = np.flatnonzero(np.diff(on.astype(np.int8)))
    spans: list[list[float]] = []
    for a, b in zip(edges[::2] * SPEECH_FRAME, edges[1::2] * SPEECH_FRAME, strict=True):
        if spans and a - spans[-1][1] < SPEECH_GAP:
            spans[-1][1] = float(b)
        else:
            spans.append([float(a), float(b)])
    return [(max(0.0, a - SPEECH_PAD), b + SPEECH_PAD) for a, b in spans if b - a >= SPEECH_MIN]


# --- script check ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return text.strip(".,!?;:\"'“”‘’()[]—-")


def script_diff(shot: Shot, asr: list[dict], al: Alignment | None = None) -> tuple[list[dict], list[str]]:
    """Misread words (expected vs heard) and script words not heard at all.

    Read off timing.align's own word map, so its misreads are exactly the ones score_take counts.
    """
    al = al or align(shot, asr)
    misread = [{"expected": _clean(shot.words[i].text), "heard": " ".join(_clean(asr[j]["w"]) for j in al.hits[i])}
               for i in sorted(al.misread_words)]
    missing = [_clean(w.text) for i, w in enumerate(shot.words) if i not in al.hits]
    return misread, missing


def _phrase(words: list[str], a: int, b: int) -> str:
    """words[a..b] (inclusive, clamped), with an ellipsis wherever the line goes on."""
    a, b = max(a, 0), min(b, len(words) - 1)
    return ("…" if a > 0 else "") + " ".join(words[a:b + 1]) + ("…" if b < len(words) - 1 else "")


def misread_context(shot: Shot, asr: list[dict], al: Alignment) -> list[dict]:
    """Each run of misread script words as what was heard vs what is written, with one word of
    context either side: 'pass the' for 'pressed' alone is a riddle, '…even pass the record' vs
    '…even pressed record' shows the slip (an extra 'the') at a glance."""
    keep = [j for j in range(len(asr)) if j not in al.ignored - al.used_asr]
    heard = [_clean(asr[j]["w"]) for j in keep]
    pos = {j: k for k, j in enumerate(keep)}
    script = [_clean(w.text) for w in shot.words]
    runs: list[list[int]] = []
    for i in sorted(al.misread_words):
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    out = []
    for run in runs:
        ks = [pos[j] for i in run for j in al.hits.get(i, ()) if j in pos]
        if ks:
            out.append({"said": _phrase(heard, min(ks) - 1, max(ks) + 1), "script": _phrase(script, run[0] - 1, run[-1] + 1)})
    return out


def script_check(shot: Shot, words: list[dict], duration: float) -> dict:
    al = align(shot, words)
    segs = keep_segments(al, words, duration)
    sc = score_take(al, words, segs)
    misread, missing = script_diff(shot, words, al)
    return {"coverage": round(al.coverage, 3), "misread": misread, "misread_ctx": misread_context(shot, words, al),
            "missing": missing,
            "junk": [w["w"].strip() for j, w in enumerate(words) if j not in al.used_asr | al.ignored],
            "kept_seconds": sc.kept, "cuts": sc.cuts, "score": sc.score,
            "heard": " ".join(w["w"].strip() for j, w in enumerate(words) if j not in al.ignored - al.used_asr)}


# --- verdict --------------------------------------------------------------------------------

def mic_label(capture: dict | None) -> str:
    """Mic name from the studio's X-Capture-Info ({"audio": {"label": ...}} or flat variants)."""
    c = capture.get("client") or capture if isinstance(capture, dict) else None
    if not isinstance(c, dict):
        return ""
    for v in (c.get("audio"), c.get("mic"), c.get("audioLabel"), c.get("micLabel")):
        if isinstance(v, dict) and isinstance(v.get("label"), str):
            return v["label"]
        if isinstance(v, str):
            return v
    return ""


def _check(id_: str, level: str, message: str) -> dict:
    return {"id": id_, "level": level, "message": message}


def _script_checks(s: dict, n_words: int) -> list[dict]:
    out = []
    if s["misread"]:
        if s.get("misread_ctx"):
            said = "; ".join(f"you said “{m['said']}” — script: “{m['script']}”" for m in s["misread_ctx"])
        else:
            said = "; ".join(f"heard “{m['heard']}” for “{m['expected']}”" for m in s["misread"])
        out.append(_check("misread", "fail", f"Misread: {said}. Read it exactly as written."))
    if s["coverage"] < MIN_COVERAGE and (s["missing"] or not s["misread"]):   # misreads alone: named above
        miss = " ".join(s["missing"]) or "most of the line"
        out.append(_check("coverage", "fail",
                          f"Only {s['coverage']:.0%} of the line was heard (missing: {miss}). Read the whole line."))
    if not out and s["missing"]:
        # A skipped word still shows in the captions, so it can never be a "great" take.
        out.append(_check("skipped", "warn", f"Skipped: {' '.join(s['missing'])}. The caption still shows it: "
                          "record again if it matters."))
    if not any(c["level"] == "fail" for c in out):
        trim = f"; {len(s['junk'])} extra word(s) and {s['cuts']} cut(s) get trimmed" if s["junk"] or s["cuts"] else ""
        out.append(_check("script", "ok", f"Script read: {n_words - len(s['missing'])}/{n_words} words{trim}."))
    return out


def _audio_checks(a: dict, mic: str) -> list[dict]:
    out = []
    if a["peak_dbfs"] >= CLIP_DBFS and a["clipped_samples"] > CLIP_SAMPLES:
        out.append(_check("clipping", "fail", f"Audio clipped ({a['clipped_samples']} samples at full scale): "
                          "lower the mic input level or move back a little."))
    if a["lufs"] < SILENT_LUFS:
        out.append(_check("silent", "fail", f"No voice recorded ({a['lufs']:.0f} LUFS): check the right microphone "
                          "is selected and not muted (the level meter should move when you speak), then read the line."))
    elif a["snr_db"] < SNR_FAIL:
        out.append(_check("noise", "fail", f"Too noisy (voice only {a['snr_db']:.0f} dB above the room): "
                          "find a quieter spot or get the mic closer."))
    elif a["snr_db"] < SNR_WARN:
        out.append(_check("noise", "warn", f"Background noise is noticeable (SNR {a['snr_db']:.0f} dB): "
                          "turn off fans/AC or get the mic closer."))
    if mic and VIRTUAL_MIC.search(mic):
        out.append(_check("mic", "warn", f"“{mic}” is a virtual audio device, not a microphone: "
                          "pick the MacBook or iPhone mic."))
    elif mic and BLUETOOTH_MIC.search(mic):
        out.append(_check("mic", "warn", f"“{mic}” is a Bluetooth mic (low-quality call mode while recording): "
                          "use the MacBook or iPhone mic."))
    if not out:
        out.append(_check("audio", "ok", f"Audio clean: {a['lufs']:.0f} LUFS, SNR {a['snr_db']:.0f} dB."))
    return out


def _video_checks(v: dict, target_width: int) -> list[dict]:
    out = []
    if v.get("decode_errors"):
        out.append(_check("corrupt", "fail", f"The converted take is damaged ({v['decode_errors']} decode errors): "
                          "Discard it and record or import it again (the original upload is kept in raw/orig/)."))
    luma = v["subject_luma"] if v.get("subject_luma") is not None else v["luma_mean"]
    if luma < LUMA_DARK:
        out.append(_check("exposure", "warn", f"Too dark (brightness {luma:.0f}/255): add light in front of you."))
    elif luma > LUMA_BRIGHT or v.get("blown_out", 0) > BLOWN_OUT:
        out.append(_check("exposure", "warn", f"Too bright (brightness {luma:.0f}/255): dim the light or move "
                          "away from the window."))
    ew, eh = v["effective_9x16"]
    if ew < target_width:
        out.append(_check("resolution", "warn", f"Only {ew}x{eh} survives the 9:16 crop, so the reel is upscaled: "
                          "use a portrait camera mode or the iPhone."))
    if v["blur"] is None:
        out.append(_check("focus", "warn", "No fine detail in the picture: is the lens covered or completely "
                          "out of focus?"))
    elif v["blur"] > BLUR_WARN:
        # Founder's real takes: same FaceTime mode, same framing, same brightness reading, blur 6 at midday vs
        # 10 in the evening. Webcams hide low light behind auto-gain + noise reduction, which smears detail
        # while the luma meter still reads normal, so light is the likeliest cause; the lens comes second.
        out.append(_check("focus", "warn", f"Picture looks soft (blur {v['blur']:.1f}): usually not enough light. "
                          "Add a lamp in front of you or face a window, then check the lens is clean."))
    if v["fps"] < MIN_FPS - 0.5:          # 23.976 is film rate, not a struggling camera
        out.append(_check("fps", "warn", f"Camera ran at {v['fps']:.0f} fps (usually low light): add light so it can "
                          "hold 30 fps."))
    if v.get("dropped_frames", 0) > DROPPED_WARN:
        out.append(_check("stutter", "warn", f"Camera dropped {v['dropped_frames']} frames (stutter): close other "
                          "camera apps and heavy tabs."))
    if not out:
        out.append(_check("picture", "ok", f"Picture good: {ew}x{eh} for 9:16, brightness {luma:.0f}/255."))
    return out


def _cm(px: float, per_cm: float | None) -> str:
    return f" ~{max(1, round(px / per_cm))} cm" if per_cm else ""


def _framing_checks(f: dict | None) -> list[dict]:
    """Coaching from the face track summary (plus the take's "w"/"h"). No face at all is not
    flagged: a take can be a screen or product shot; a face that comes and goes is."""
    if not f or f.get("eye_y_med") is None:
        return []
    out = []
    if f["present"] < FACE_PRESENT:
        out.append(_check("face", "warn", f"Your face was out of frame or turned away for {1 - f['present']:.0%} "
                          "of the take: stay in frame, facing the camera."))
    per_cm, eye, fh = facetrack.px_per_cm(f), f["eye_y_med"], f["face_h_med"]
    target = facetrack.TARGET_EYE_Y
    _, reach = facetrack.reframe_eye(eye)
    if abs(reach - target) > facetrack.EYE_TOL:
        n = _cm(abs(eye - target) * f["h"], per_cm)
        if eye > target:   # eyes low in frame: the subject must rise relative to the lens
            msg = (f"Your eyes sit {eye:.0%} of the way down the frame (best: {target:.0%}), so captions land on "
                   f"your face: sit{n} higher or lower the camera{n} (on a laptop, tilt the screen slightly toward you).")
        else:
            msg = (f"Your eyes sit only {eye:.0%} of the way down the frame (best: {target:.0%}): raise the "
                   f"camera{n} or sit{n} lower.")
        out.append(_check("framing", "warn", msg))
    if fh < FACE_SMALL:
        out.append(_check("size", "warn", f"Your face is small in the frame ({fh:.0%} of the height): move about "
                          f"{round((1 - fh / FACE_TARGET) * 20) * 5}% closer to the camera."))
    elif fh > FACE_LARGE:
        out.append(_check("size", "warn", f"You're very close to the camera (face {fh:.0%} of the height): sit "
                          f"about {round((fh / FACE_TARGET - 1) * 20) * 5}% farther back so captions fit."))
    off = f["center_x_med"] - 0.5
    if abs(off) > OFF_CENTRE:   # takes are not mirrored: the face right of centre is the creator's left
        out.append(_check("centre", "warn", f"You're off-centre ({f['center_x_med']:.0%} across the frame): move"
                          f"{_cm(abs(off) * f['w'], per_cm)} to your {'right' if off > 0 else 'left'}."))
    if not out:
        fixed = " after the auto-reframe" if abs(eye - target) > facetrack.EYE_TOL else ""
        out.append(_check("framing", "ok", f"Framing good: eye line at {reach:.0%} of the height{fixed}, "
                          f"face {fh:.0%} of the frame."))
    return out


def assess(video: dict, audio: dict, script: dict, n_words: int, estimate_s: float,
           target_width: int = 1080, mic: str = "", face: dict | None = None) -> list[dict]:
    """Human-readable, actionable checks; the verdict comes from their levels.

    Audio root causes come first (the studio shows the first fail): a muted mic also fails the
    script check, but "check the mic" is what the creator needs to hear, not "read the whole line".
    """
    checks = (_audio_checks(audio, mic) + _script_checks(script, n_words) + _video_checks(video, target_width)
              + _framing_checks(face))
    if estimate_s and video["duration"] > LONG_TAKE * estimate_s:
        checks.append(_check("length", "warn", f"Take is {video['duration']:.1f}s for a ~{estimate_s:.1f}s line: "
                             "start reading sooner and stop right after (dead air is cut, but check the read)."))
    return checks


def verdict(checks: list[dict]) -> str:
    levels = {c["level"] for c in checks}
    return "retake" if "fail" in levels else "ok" if "warn" in levels else "great"


# --- entry point ----------------------------------------------------------------------------

def _default_transcribe(media: Path) -> list[dict]:
    from .__main__ import transcribe
    return transcribe(media)


def _default_face(media: Path, out: Path) -> dict | None:
    """Face track summary (writes <take>.face.json next to the report); None without a backend."""
    try:
        return facetrack.face_track(media, out)["summary"]
    except facetrack.FaceUnavailable:
        return None


def check_take(media: Path, script_path: Path, shot_id: str, out: Path, source: Path | None = None,
               capture: dict | None = None, transcribe_fn: Callable[[Path], list[dict]] | None = None,
               face_fn: Callable[[Path, Path], dict | None] | None = None) -> dict:
    """Measure a normalized take, write its report to `out` (and words and face track next to it), return it."""
    script = load_script(script_path)
    shot = next((s for s in script.shots if s.id == shot_id), None)
    if shot is None:
        raise ScriptError(f"shot {shot_id!r} is not in {script_path}")
    info = probe(media)
    src: SourceInfo = probe(source) if source else info
    words = (transcribe_fn or _default_transcribe)(media)
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / f"{media.stem}.words.json").write_text(json.dumps(words, indent=1))

    video = {"width": info.width, "height": info.height, "fps": round(src.fps, 2), "duration": info.duration,
             **video_stats(media, info.width, info.height), "vfr_source": src.vfr,
             "dropped_frames": src.dropped_frames, "source_size": [src.width, src.height]}
    audio_errors: list[str] = []
    mono = decode_audio(media, errors=audio_errors)
    video["decode_errors"] = video.get("decode_errors", 0) + len(audio_errors)
    peaks = peak_stats(decode_audio(source, mono=False) if source else mono)
    audio = {"sample_rate": src.sample_rate or SR, **peaks, "lufs": integrated_lufs(media), **noise_stats(mono, words)}
    # Whisper stretches words over pauses ("and" spanning a 2 s pause), which would hide the cuts
    # the build makes; snap to the voice first, as prep does.
    snapped = snap_to_speech(words, speech_spans(mono, audio["noise_floor_db"], audio["snr_db"]))
    sc = script_check(shot, snapped, info.duration)
    est = round(estimate(shot)[-1].end, 2)
    fs = (face_fn or _default_face)(media, out.parent / f"{media.stem}.face.json")
    face = {**fs, "w": info.width, "h": info.height} if fs else None
    checks = assess(video, audio, sc, len(shot.words), est, script.width, mic_label(capture), face)
    report = {"take": media.stem, "shot": shot.id, "created": int(time.time()), "video": video, "audio": audio,
              "script": sc, "face": fs, "checks": checks, "verdict": verdict(checks), "estimate_s": est}
    tmp = out.with_name(f".{out.name}.part")
    tmp.write_text(json.dumps(report, indent=1))
    tmp.replace(out)
    return report
