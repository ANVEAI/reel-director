"""Take intake: normalize any recording or import to the pipeline's house format.

Every take becomes constant-frame-rate H.264 High (crf 14) with mono 48 kHz AAC 256k, starting
at t=0 on both streams, so prep, QA, the studio player and HyperFrames all see the same
seekable, drift-free file. ffmpeg's autorotate applies iPhone rotation metadata while
re-encoding (and drops the matrix, so nothing rotates twice); HDR (HLG/PQ) sources are
converted to SDR BT.709 because the H.264 8-bit output can't carry them, and full-range or
BT.601-matrix SDR sources are converted to limited-range BT.709 (untagged ones are left as is).
"""
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

FPS_CHOICES = (24, 25, 30, 60)
DEFAULT_FPS = 30
MIN_REAL_FPS = 23          # below this the camera is struggling (low light), not a real rate: use 30
HDR_TRC = {"arib-std-b67", "smpte2084"}
BT601 = {"bt470bg", "smpte170m"}   # SD/webcam/MJPEG matrices: converted so every take is BT.709
MAX_EFFECTIVE_WIDTH = 1440  # 4/3 of a 1080-wide reel: a 1.33x zoom cue still has native pixels
VIDEO_ARGS = ["-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p"]
AUDIO_ARGS = ["-ac", "1", "-ar", "48000", "-c:a", "aac", "-b:a", "256k"]
DEAD_CHANNEL_DB = 20.0     # a channel this far below the loudest carries no mic (one-input USB interfaces)
SCALE_FLAGS = "lanczos+accurate_rnd+full_chroma_int"


class CaptureError(RuntimeError):
    pass


@dataclass
class SourceInfo:
    width: int          # display size: rotation already applied
    height: int
    fps: float          # the camera's nominal rate, from its normal frame intervals
    avg_fps: float      # frames / time; lower than fps when frames were dropped
    duration: float
    rotation: int
    vfr: bool
    dropped_frames: int
    hdr: bool
    has_audio: bool
    audio_channels: int
    sample_rate: int
    full_range: bool = False   # pc / yuvj (MJPEG webcams, some phones): brought to limited range
    matrix: str = ""           # YUV matrix tag ("" when untagged: left as is)

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = " / ".join(r.stderr.strip().splitlines()[-3:])
        raise CaptureError(f"{Path(cmd[0]).name} failed: {tail or 'no output'}")
    return r.stdout


def _frame_times(src: Path) -> np.ndarray:
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                "-of", "csv=p=0", str(src)])
    ts = [float(x) for x in out.split() if x.strip() not in {"", "N/A"}]
    return np.sort(np.array(ts, dtype=np.float64))


def frame_timing(times: np.ndarray) -> tuple[float, float, bool, int]:
    """(nominal fps, average fps, variable frame rate?, dropped frames) from presentation timestamps.

    A browser recording has a few ms of jitter on every frame; VFR here means frame gaps that
    really vary (dropped frames, low-light rate changes), measured as the p5..p95 spread of
    frame durations relative to the median.
    """
    d = np.diff(times)
    d = d[d > 0]
    if len(d) < 2:
        return 0.0, 0.0, False, 0
    med = float(np.median(d))
    avg = len(d) / float(times[-1] - times[0])
    spread = float(np.percentile(d, 95) - np.percentile(d, 5)) / med
    dropped = int(sum(round(x / med) - 1 for x in d if x > 1.5 * med))
    steady = d[np.abs(d - med) < 0.25 * med]   # mean of normal frames: robust to ms-rounded WebM stamps
    return round(1.0 / float(np.mean(steady)), 3), round(avg, 3), spread > 0.2 or dropped > 0, dropped


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            return int(round(float(sd["rotation"]))) % 360
    return int(stream.get("tags", {}).get("rotate", 0)) % 360


def probe(src: Path) -> SourceInfo:
    """What the take really is: display size, measured frame rate, HDR, audio."""
    data = json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(src)]))
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise CaptureError("no video track in the file")
    rot = _rotation(video)
    w, h = int(video["width"]), int(video["height"])
    if rot in (90, 270):
        w, h = h, w
    times = _frame_times(src)
    fps, avg, vfr, dropped = frame_timing(times)
    if not fps:
        num, _, den = (video.get("avg_frame_rate") or "0/1").partition("/")
        fps = avg = float(num) / float(den or 1) if float(den or 1) else 0.0
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)
    if not duration and len(times) > 1:   # MediaRecorder WebM has no duration in its header
        duration = float(times[-1] - times[0]) + (1.0 / fps if fps else 0.0)
    return SourceInfo(w, h, round(fps, 3), round(avg, 3), round(duration, 3), rot, vfr, dropped,
                      video.get("color_transfer") in HDR_TRC, audio is not None,
                      int(audio.get("channels", 0)) if audio else 0, int(audio.get("sample_rate", 0)) if audio else 0,
                      video.get("color_range") == "pc" or str(video.get("pix_fmt", "")).startswith("yuvj"),
                      str(video.get("color_space") or "").replace("unknown", ""))


def channel_levels(src: Path) -> list[float]:
    """RMS level (dBFS) of each channel of the first audio track."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-map", "0:a:0", "-af",
                        "astats=measure_overall=none:measure_perchannel=RMS_level", "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise CaptureError("ffmpeg failed reading the audio: " + " / ".join(r.stderr.strip().splitlines()[-2:]))
    return [float(x) for x in re.findall(r"RMS level dB: (-?inf|-?[\d.]+)", r.stderr)]


def downmix(levels: list[float]) -> str:
    """Mono filter that keeps the voice level: average the channels that carry signal.

    Browsers record a mono mic as two identical channels, and ffmpeg's `-ac 1` sums them at
    0.707 each (+3 dB, so a -1 dBFS take would clip); a dead channel would halve an average.
    """
    if len(levels) <= 1:
        return ""
    live = [i for i, db in enumerate(levels) if db >= max(levels) - DEAD_CHANNEL_DB]
    return "pan=mono|c0=" + "+".join(f"{1 / len(live):.6g}*c{i}" for i in live)


def target_fps(fps: float) -> int:
    """Nearest standard rate; a camera that fell below 23 fps is brought up to the default."""
    if not fps or fps < MIN_REAL_FPS:
        return DEFAULT_FPS
    return min(FPS_CHOICES, key=lambda c: (abs(c - fps), c != DEFAULT_FPS))


def effective_9x16(width: int, height: int) -> tuple[int, int]:
    """Largest 9:16 rectangle inside a frame: what survives the reel's crop."""
    if width * 16 > height * 9:
        return height * 9 // 16, height
    return width, width * 16 // 9


def output_size(width: int, height: int, max_eff_width: int = MAX_EFFECTIVE_WIDTH) -> tuple[int, int]:
    """Even frame size, downscaled only when its 9:16 crop is wider than max_eff_width."""
    eff_w, _ = effective_9x16(width, height)
    k = min(1.0, max_eff_width / eff_w) if eff_w else 1.0
    return max(2, int(width * k) // 2 * 2), max(2, int(height * k) // 2 * 2)


def video_filter(info: SourceInfo, fps: int, max_eff_width: int = MAX_EFFECTIVE_WIDTH) -> str:
    # start_time=0 repeats the first frame if video starts after audio, so both begin at 0.
    chain = [f"fps={fps}:start_time=0"]
    w, h = output_size(info.width, info.height, max_eff_width)
    scale = []
    if (w, h) != (info.width, info.height):
        scale += [f"w={w}", f"h={h}"]
    if info.hdr:
        # ffmpeg 8's colour-managed swscale; relative colorimetric maps HDR reference white to
        # SDR white (faces keep SDR-camera exposure) and clips only specular highlights.
        scale += ["out_transfer=bt709", "out_primaries=bt709", "out_color_matrix=bt709", "out_range=tv"]
    else:
        # House format is limited-range BT.709: a full-range or BT.601 take is converted (input
        # side read from the frame tags), so no range-unaware consumer crushes blacks/clips whites.
        if info.matrix in BT601:
            scale.append("out_color_matrix=bt709")
        if info.full_range:
            scale.append("out_range=tv")
    if scale:
        chain.append("scale=" + ":".join(scale + [f"flags={SCALE_FLAGS}"]))
    chain.append("format=yuv420p")
    return ",".join(chain)


def normalize(src: Path, dst: Path, max_eff_width: int = MAX_EFFECTIVE_WIDTH) -> dict:
    """Re-encode src into dst (written atomically). Returns what was done, for the QA report."""
    info = probe(src)
    if not info.has_audio:
        raise CaptureError("no audio track: the microphone wasn't recorded")
    fps = target_fps(info.fps)
    mix = downmix(channel_levels(src)) if info.audio_channels > 1 else ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(f".{dst.stem}.part{dst.suffix}")
    color = (["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"] if info.hdr else
             ["-colorspace", "bt709"] if info.matrix in BT601 else [])
    if info.hdr or info.full_range:
        color += ["-color_range", "tv"]
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0",
           "-map_metadata", "-1", "-vf", video_filter(info, fps, max_eff_width), "-fps_mode", "cfr",
           *VIDEO_ARGS, *color,
           # 2 s GOP: snappy scrubbing in the studio and cheap random access for frame extraction.
           "-g", str(2 * fps), "-af", ",".join(filter(None, [mix, "aresample=async=1:first_pts=0"])), *AUDIO_ARGS,
           "-movflags", "+faststart", str(part)]
    try:
        _run(cmd)
        os.replace(part, dst)
    finally:
        if part.exists():
            part.unlink()
    out = probe(dst)
    return {"source": info.to_dict(), "fps": fps, "width": out.width, "height": out.height,
            "duration": out.duration, "hdr_converted": info.hdr, "downmix": mix or None}
