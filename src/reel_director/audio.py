"""Audio with ffmpeg: clean and level each take, master or deliver the final reel.

Video streams are copied untouched; only audio is re-encoded. Gain is always a measured
linear gain plus a peak limiter: ffmpeg's loudnorm is never used to apply gain, because when
its linear mode cannot reach the target it silently falls back to dynamic mode, which pumps
and writes an AAC timestamp gap (seeks into the take then land 21-78 ms off).
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

SR = 48000
TAKE_LUFS = -16.0     # dialogue level per take, leaves headroom for music and SFX
MASTER_LUFS = -14.0   # common short-form delivery target (convention, not a platform spec)
MASTER_TP = -1.5      # true-peak ceiling of the delivered AAC (platforms re-encode again)
TAKE_TP = -1.5        # ceiling of the take limiter
AAC = ["-c:a", "aac", "-b:a", "256k", "-ar", str(SR)]

# afftdn delays its output by exactly 1200 samples at 48 kHz (25 ms, its frame); pad the end and
# trim the head so a prepped take stays sample-aligned with its stream-copied picture.
AFFTDN_DELAY = 1200
DENOISE_SKIP_SNR = 35.0    # cleaner than this: highpass only (afftdn would only dull the voice)


def _ff(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-y", *args], check=True, capture_output=True)


def _err(p: subprocess.CompletedProcess) -> str:
    return p.stderr.decode(errors="replace")


def loudness(src: Path, pre: str = "") -> dict:
    """EBU R128 integrated loudness and true peak (ffmpeg ebur128, oversampled peak)."""
    chain = f"{pre}," if pre else ""
    err = _err(_ff("-i", str(src), "-vn", "-af", f"{chain}ebur128=peak=true:framelog=quiet", "-f", "null", "-"))
    i = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err)
    tp = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    return {"I": float(i[-1]) if i and i[-1] != "-inf" else -70.0,
            "tp": float(tp[-1]) if tp and tp[-1] != "-inf" else -120.0}


def measure(src: Path, pre: str = "", target: float = TAKE_LUFS, tp: float = MASTER_TP) -> dict:
    """Back-compat keys (input_i / input_tp) from an ebur128 measurement. Measures only."""
    m = loudness(src, pre)
    return {"input_i": m["I"], "input_tp": m["tp"]}


def snr_db(src: Path) -> float:
    """Take SNR without a transcript, on takecheck's scale: power mean of the speech frames (>= 10 dB over
    the floor) minus the floor (10th percentile of 20 ms frames). Gaps at digital silence (a gated or
    synthetic take) mean there is no noise to remove: 99."""
    x = np.frombuffer(_ff("-i", str(src), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1").stdout,
                      "<f4").astype(np.float64)
    n = int(0.02 * SR)
    if len(x) < 10 * n:
        return 0.0
    db = 10 * np.log10(np.mean(x[: len(x) // n * n].reshape(-1, n) ** 2, axis=1) + 1e-14)
    if np.mean(db < -90) >= 0.02:
        return 99.0
    floor = float(np.percentile(db, 10))
    speech = db[db >= floor + 10]
    level = 10 * np.log10(np.mean(10 ** (speech / 10))) if len(speech) else floor
    return round(float(level - floor), 1)


def denoise_chain(snr: float | None) -> tuple[str, dict]:
    """highpass always; afftdn only for a noisy take, its strength from the SNR and its delay removed."""
    chain = f"aresample={SR},highpass=f=80"
    if snr is None or snr >= DENOISE_SKIP_SNR:
        return chain, {"denoise": False, "snr_db": snr}
    nr = float(np.clip(40.0 - snr, 6.0, 12.0))
    chain += (f",apad=pad_len={AFFTDN_DELAY},afftdn=nr={nr:g}:nf=-25:tn=1,"
              f"atrim=start_sample={AFFTDN_DELAY},asetpts=N/SR/TB")
    return chain, {"denoise": True, "snr_db": snr, "nr_db": nr}


def _limit(ceiling_db: float) -> str:
    """alimiter at 48 kHz with fixed level (no auto-gain) and its look-ahead delay compensated.
    (Not oversampled: aresample=192000 around it puts 1-sample jitter into the AAC pts.)"""
    return f"alimiter=limit={10 ** (ceiling_db / 20):.5f}:attack=1:release=60:level=0:latency=1"


def clean_take(src: Path, dst: Path, denoise: bool = True) -> dict:
    """Denoise (adaptive, optional) and level a take to TAKE_LUFS with a measured linear gain + limiter."""
    snr = snr_db(src) if denoise else None
    pre, info = denoise_chain(snr)
    before, filt = loudness(src), loudness(src, pre)
    gain = TAKE_LUFS - filt["I"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ff("-i", str(src), "-map", "0:v:0?", "-map", "0:a:0", "-c:v", "copy",
        "-af", f"{pre},volume={gain:.2f}dB,{_limit(TAKE_TP)},asetpts=N/SR/TB",
        "-ar", str(SR), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst))
    after = loudness(dst)
    return {"before_lufs": before["I"], "after_lufs": after["I"], "true_peak": after["tp"],
            "gain_db": round(gain, 2), **info}


def decode(path: Path, channels: int = 2) -> np.ndarray:
    """Audio as float64 (n, channels) at 48 kHz."""
    raw = _ff("-i", str(path), "-vn", "-ac", str(channels), "-ar", str(SR), "-f", "f32le", "pipe:1").stdout
    return np.frombuffer(raw, "<f4").astype(np.float64).reshape(-1, channels)


def _mux(video: Path, wav: Path, dst: Path, duration: float | None = None) -> None:
    """Picture stream-copied from `video` (if it has one), audio = `wav` encoded to AAC as delivered."""
    _ff("-i", str(video), "-i", str(wav), "-map", "0:v:0?", "-map", "1:a:0", "-c:v", "copy", *AAC,
        *(["-t", f"{duration:.3f}"] if duration else []), "-movflags", "+faststart", str(dst))


def _relevel(x: np.ndarray, target: float, ceiling: float, tmp: Path) -> Path:
    """Linear gain to `target` LUFS through the true-peak limiter (numpy: no ffmpeg pts side effects)."""
    import soundfile as sf

    from .levels import master as level
    y, _, _ = level(x, target, ceiling)
    sf.write(str(tmp), y, SR, subtype="FLOAT")
    return tmp


def master(src: Path, dst: Path, target: float = MASTER_LUFS, tp: float = MASTER_TP) -> dict:
    """Loudness pass on a rendered reel (mode B fallback): measured gain, 4x true-peak limiter, AAC, then
    re-measure the ENCODED file and lower the ceiling / correct the gain until it meets the spec."""
    import tempfile
    before, x = loudness(src), decode(src)
    ceil, tgt, after = tp - 0.5, target, before
    with tempfile.TemporaryDirectory() as td:
        for _ in range(6):
            _mux(src, _relevel(x, tgt, ceil, Path(td) / "a.wav"), dst)
            after = loudness(dst)
            ok_tp, ok_i = after["tp"] <= tp, abs(after["I"] - target) <= 0.3
            if ok_tp and ok_i:
                break
            ceil -= 0.0 if ok_tp else after["tp"] - tp + 0.2
            tgt += 0.0 if ok_i else target - after["I"]
    return {"before_lufs": before["I"], "after_lufs": after["I"], "true_peak": after["tp"]}


def streams(path: Path) -> dict:
    """{codec_type: {start, duration}} from ffprobe."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time,duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: {"start": float(s.get("start_time") or 0), "duration": float(s.get("duration") or 0)}
            for s in json.loads(out)["streams"]}


def deliver(render_mp4: Path, mix_wav: Path, out: Path, target: float = MASTER_LUFS, tp: float = MASTER_TP) -> dict:
    """Mux the rendered picture (stream copy) with the baked, mastered mix (mode A). Pass 1 is a plain
    AAC encode of mix.wav; if the ENCODED file misses -14 +-0.5 LUFS or the true-peak ceiling, the mix is
    re-leveled through the limiter with a corrected target/ceiling and re-encoded (up to 3 more passes)."""
    import tempfile
    render_mp4, mix_wav, out = Path(render_mp4), Path(mix_wav), Path(out)
    vdur = streams(render_mp4)["video"]["duration"]
    out.parent.mkdir(parents=True, exist_ok=True)
    src, tgt, ceil, m, passes = mix_wav, target, tp - 0.5, {}, 0
    with tempfile.TemporaryDirectory() as td:
        for passes in range(1, 5):
            _mux(render_mp4, src, out, vdur)
            m = loudness(out)
            ok_tp, ok_i = m["tp"] <= tp, abs(m["I"] - target) <= 0.5
            if ok_tp and ok_i:
                break
            ceil -= 0.0 if ok_tp else m["tp"] - tp + 0.2
            tgt += 0.0 if ok_i else target - m["I"]
            src = _relevel(decode(mix_wav), tgt, ceil, Path(td) / f"p{passes}.wav")
    st = streams(out)
    a, v = st.get("audio", {}), st.get("video", {})
    return {"lufs": m.get("I"), "true_peak": m.get("tp"), "passes": passes, "releveled": passes > 1,
            "audio_start": a.get("start"), "video_start": v.get("start"),
            "av_start_offset_ms": round(1000 * (a.get("start", 0.0) - v.get("start", 0.0)), 2),
            "audio_duration": a.get("duration"), "video_duration": v.get("duration"),
            "ok": bool(m.get("tp", 0.0) <= tp and abs(m.get("I", 0.0) - target) <= 0.5)}


def speech_spans(src: Path) -> list[tuple[float, float]]:
    """Silero VAD speech regions in seconds. Imports torch: call after all mlx-whisper work."""
    import tempfile

    import soundfile as sf
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "vad.wav"
        _ff("-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav))
        audio, _ = sf.read(wav, dtype="float32")
    spans = get_speech_timestamps(torch.from_numpy(audio), load_silero_vad(), return_seconds=True,
                                  min_silence_duration_ms=150, speech_pad_ms=30)
    return [(float(s["start"]), float(s["end"])) for s in spans]
