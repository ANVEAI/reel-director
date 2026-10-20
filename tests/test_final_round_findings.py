"""Regressions for the capture findings of the 20 Oct review (final round).

Experiments and before/after numbers: work/final-round/findings/.
"""
import json
import subprocess
from pathlib import Path

import numpy as np

from reel_director import capture
from reel_director import takecheck as tc


def _info(**kw) -> capture.SourceInfo:
    base = dict(width=1080, height=1920, fps=30.0, avg_fps=30.0, duration=1.0, rotation=0, vfr=False,
                dropped_frames=0, hdr=False, has_audio=True, audio_channels=1, sample_rate=48000)
    return capture.SourceInfo(**{**base, **kw})


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _stream(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,pix_fmt,color_range,color_space", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"][0]


def _y_plane(path: Path, w: int, h: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "yuv420p", "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(raw[: w * h], np.uint8).reshape(h, w)


# --- full-range / BT.601 inputs end up limited-range BT.709 ----------------------------------

def test_filter_converts_full_range_and_bt601_only_when_needed():
    assert "scale=" not in capture.video_filter(_info(), 30)                        # limited, untagged: as before
    assert "scale=" not in capture.video_filter(_info(matrix="bt709"), 30)
    vf = capture.video_filter(_info(full_range=True, matrix="bt470bg"), 30)
    assert "out_range=tv" in vf and "out_color_matrix=bt709" in vf
    vf = capture.video_filter(_info(width=2160, height=3840, full_range=True, matrix="bt709"), 30)
    assert "w=1440" in vf and "out_range=tv" in vf and "out_color_matrix" not in vf
    hdr = capture.video_filter(_info(hdr=True, full_range=True), 30)
    assert hdr.count("out_range=tv") == 1


def test_full_range_bt601_take_is_normalized_to_limited_bt709(tmp_path):
    src = tmp_path / "webcam_full.mp4"     # an MJPEG-style webcam: full range, BT.601 matrix
    _ffmpeg("-f", "lavfi", "-i", "color=black:s=160x240:d=0.5:r=30[a];color=white:s=160x240:d=0.5:r=30[b];[a][b]hstack",
            "-f", "lavfi", "-i", "sine=f=440:d=0.5", "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0",
            "-pix_fmt", "yuvj420p", "-color_range", "pc", "-colorspace", "bt470bg", "-c:a", "aac", "-shortest", str(src))
    info = capture.probe(src)
    assert info.full_range and info.matrix == "bt470bg"
    dst = tmp_path / "take.mp4"
    capture.normalize(src, dst)
    s = _stream(dst)
    assert (s["pix_fmt"], s.get("color_range"), s.get("color_space")) == ("yuv420p", "tv", "bt709")
    y = _y_plane(dst, 320, 240)
    black, white = float(y[:, 20:140].mean()), float(y[:, 180:300].mean())
    assert abs(black - 16) <= 1 and abs(white - 235) <= 1        # was 0 / 255 (full range kept)
    assert not capture.probe(dst).full_range


def test_limited_untagged_take_is_untouched(tmp_path):
    src = tmp_path / "limited.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=gray:s=160x240:d=0.4:r=30", "-f", "lavfi", "-i", "sine=d=0.4",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
    info = capture.probe(src)
    assert not info.full_range and info.matrix == ""
    dst = tmp_path / "take.mp4"
    capture.normalize(src, dst)
    assert _stream(dst)["pix_fmt"] == "yuv420p"
    assert abs(float(_y_plane(dst, 160, 240).mean()) - float(_y_plane(src, 160, 240).mean())) < 1.0


# --- QA video checks: no false warnings for common, correct setups ----------------------------

def _checks(**v) -> list[str]:
    base = {"effective_9x16": [1080, 1920], "luma_mean": 128.0, "subject_luma": 128.0, "blown_out": 0.0,
            "blur": 4.0, "fps": 30.0, "dropped_frames": 0, "decode_errors": 0}
    return [c["id"] for c in tc._video_checks({**base, **v}, 1080) if c["level"] != "ok"]


def test_white_wall_or_dark_room_around_a_lit_face_is_not_an_exposure_warning():
    # measured on synthetic frames: frame mean 221.8 / 59.8, face window 174.4 / 160.7
    assert _checks(luma_mean=221.8, subject_luma=174.4) == []
    assert _checks(luma_mean=59.8, subject_luma=160.7) == []
    assert _checks(luma_mean=230.0, subject_luma=230.0) == ["exposure"]      # a blown-out face still warns


def test_film_rate_is_not_a_low_light_warning():
    assert _checks(fps=23.976) == [] and _checks(fps=23.98) == []
    assert _checks(fps=20.0) == ["fps"]


def test_sharp_subject_on_defocused_background_is_not_soft(tmp_path):
    bokeh, soft = tmp_path / "bokeh.mp4", tmp_path / "soft.mp4"
    _ffmpeg("-filter_complex", "testsrc2=s=1080x1920:d=0.5:r=30,gblur=sigma=8[b];testsrc2=s=600x900:d=0.5:r=30[f];"
            "[b][f]overlay=240:230", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p", str(bokeh))
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=0.5:r=30,gblur=sigma=3", "-c:v", "libx264",
            "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p", str(soft))
    assert tc.video_stats(bokeh, 1080, 1920)["blur"] <= tc.BLUR_WARN          # whole-crop mean was 8.58
    assert tc.video_stats(soft, 1080, 1920)["blur"] > tc.BLUR_WARN           # a soft lens still warns


# --- HDR (HLG) to SDR: legal codes, reference white at 100% --------------------------------------

def test_hlg_ramp_lands_in_legal_range_with_reference_white_at_100_percent(tmp_path):
    """The review's 'Y up to 254' came from a gray readback that expanded tv to pc range; the Y
    plane itself tops out at 235-236. Pin it: mid-grey and reference white where BT.2408 puts them."""
    w, h = 512, 64
    y = np.tile(np.round(64 + 876 * np.arange(w) / (w - 1)).astype("<u2"), (h, 1))
    frame = y.tobytes() + np.full(w * h // 2, 512, "<u2").tobytes()
    src = tmp_path / "hlg.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-s", f"{w}x{h}",
                    "-r", "30", "-color_range", "tv", "-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
                    "-colorspace", "bt2020nc", "-i", "pipe:0", "-f", "lavfi", "-i", "sine=d=0.4", "-c:v", "ffv1",
                    "-c:a", "pcm_s16le", "-shortest", str(src)], input=frame * 12, check=True)
    assert capture.probe(src).hdr
    dst = tmp_path / "take.mp4"
    capture.normalize(src, dst)
    row = _y_plane(dst, w, h)[h // 2].astype(int)
    at = lambda s: int(row[round(s * (w - 1))])                      # noqa: E731
    assert row.max() <= 236 and row.min() >= 15                     # no super-white / sub-black codes
    assert abs(at(0.5) - 139) <= 3 and abs(at(0.75) - 234) <= 3     # mid-tones and reference white kept
    assert np.all(np.diff(row) >= -1)                                # monotonic ramp
