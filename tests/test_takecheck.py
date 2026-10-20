import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from reel_director import capture
from reel_director.schema import parse_script
from reel_director.cleanup import snap_to_speech
from reel_director.takecheck import (assess, check_take, mic_label, noise_stats, peak_stats, script_check,
                                     script_diff, speech_spans, verdict)
from reel_director.timing import align

LINE = "Most creators waste three hours editing one reel."
SAID = [("most", 0.5, 0.68), ("creators", 0.68, 0.9), ("waste", 0.9, 1.1), ("three", 1.1, 1.3),
        ("hours", 1.3, 1.5), ("editing", 1.5, 1.7), ("one", 1.7, 1.85), ("reel.", 1.85, 2.0)]


def words(replace=None):
    out = [{"w": w, "s": s, "e": e} for w, s, e in SAID]
    for i, w in (replace or {}).items():
        out[i]["w"] = w
    return out


def shot():
    return parse_script({"shots": [{"id": "hook", "line": LINE}]}).shots[0]


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def take(tmp_path_factory):
    """A tiny 9:16 take: a 0.3-amplitude tone where the (mocked) words are, -62 dB around them."""
    d = tmp_path_factory.mktemp("take")
    ff("-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=3", "-f", "lavfi",
       "-i", "sine=f=220:d=3,volume='if(between(t,0.5,2.0),2.4,0.008)':eval=frame",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "upload.mp4"))
    (d / "script.json").write_text(json.dumps({"width": 360, "height": 640, "shots": [{"id": "hook", "line": LINE}]}))
    capture.normalize(d / "upload.mp4", d / "hook-1.mp4")
    return d


# --- script check ------------------------------------------------------------------------

def test_misread_is_named_and_counted_like_align():
    asr = words({4: "days"})
    misread, missing = script_diff(shot(), asr)
    assert misread == [{"expected": "hours", "heard": "days"}] and missing == []
    assert len(misread) == align(shot(), asr).misread


def test_missing_words_and_junk_are_reported():
    asr = [{"w": "um", "s": 0.1, "e": 0.3}] + [w for i, w in enumerate(words()) if i not in (3, 4)]
    sc = script_check(shot(), asr, 3.0)
    assert sc["missing"] == ["three", "hours"] and sc["junk"] == ["um"]
    assert sc["coverage"] == pytest.approx(6 / 8)


# --- thresholds --------------------------------------------------------------------------

VIDEO = {"duration": 3.0, "effective_9x16": [1080, 1920], "luma_mean": 120, "blur": 4.5, "fps": 30, "dropped_frames": 0}
AUDIO = {"peak_dbfs": -6.0, "clipped_samples": 0, "lufs": -20.0, "snr_db": 40.0}
SCRIPT = {"coverage": 1.0, "misread": [], "missing": [], "junk": [], "cuts": 0}


def run(video=None, audio=None, script=None, mic=""):
    checks = assess({**VIDEO, **(video or {})}, {**AUDIO, **(audio or {})}, {**SCRIPT, **(script or {})}, 8, 2.9,
                    1080, mic)
    return verdict(checks), {c["id"]: c["level"] for c in checks if c["level"] != "ok"}


def test_clean_take_is_great():
    assert run() == ("great", {})


@pytest.mark.parametrize("change, failed", [
    ({"script": {"misread": [{"expected": "hours", "heard": "days"}], "coverage": 0.875}}, "misread"),
    ({"script": {"coverage": 0.8, "missing": ["one", "reel"]}}, "coverage"),
    ({"audio": {"peak_dbfs": -0.1, "clipped_samples": 50}}, "clipping"),
    ({"audio": {"lufs": -55.0}}, "silent"),
    ({"audio": {"snr_db": 12.0}}, "noise"),
])
def test_fails_mean_retake(change, failed):
    v, issues = run(**change)
    assert v == "retake" and issues[failed] == "fail"


@pytest.mark.parametrize("change, warned", [
    ({"audio": {"snr_db": 20.0}}, "noise"),
    ({"video": {"luma_mean": 40}}, "exposure"),
    ({"video": {"luma_mean": 230}}, "exposure"),
    ({"video": {"effective_9x16": [607, 1080]}}, "resolution"),
    ({"video": {"blur": 11.0}}, "focus"),
    ({"video": {"blur": None}}, "focus"),
    ({"video": {"fps": 15}}, "fps"),
    ({"video": {"duration": 12.0}}, "length"),
    ({"mic": "BlackHole 2ch"}, "mic"),
    ({"mic": "AirPods Pro"}, "mic"),
])
def test_warnings_mean_ok(change, warned):
    v, issues = run(**change)
    assert v == "ok" and issues == {warned: "warn"}


def test_mic_label_tolerates_any_capture_info():
    label = "Alex\u2019s iPhone Microphone"
    for info in ({"client": {"audio": {"label": label}}}, {"audio": {"label": label}}, {"mic": label},
                 {"client": {"audioLabel": label}}):
        assert mic_label(info) == label
    for info in (None, {}, {"client": None}, {"client": "garbled"}, {"client": {"audio": None}}, ["x"]):
        assert mic_label(info) == ""


def test_a_few_clipped_samples_or_a_hot_peak_alone_are_fine():
    assert run(audio={"peak_dbfs": -0.1, "clipped_samples": 4})[0] == "great"
    assert run(audio={"peak_dbfs": -1.0, "clipped_samples": 50})[0] == "great"


def test_peak_and_noise_measurements():
    t = np.arange(48000 * 2) / 48000
    sig = np.where((t > 0.5) & (t < 1.5), 0.3 * np.sin(2 * np.pi * 220 * t), 0.001 * np.sin(2 * np.pi * 50 * t))
    ns = noise_stats(sig.astype("<f4"), [{"w": "x", "s": 0.5, "e": 1.5}])
    assert ns["noise_floor_db"] == pytest.approx(-63, abs=1.5) and ns["snr_db"] == pytest.approx(49.5, abs=1.5)
    clipped = np.clip(sig * 5, -1, 1).astype("<f4")
    assert peak_stats(clipped)["clipped_samples"] > 1000 and peak_stats(clipped)["peak_dbfs"] == 0.0


def test_a_pause_whisper_stretched_a_word_over_is_still_cut():
    """'record, [2 s] and the reel': Whisper gives 'and' the whole pause; snapping to the voice
    (as prep does with Silero) makes QA count the cut the build will make."""
    t = np.arange(48000 * 5) / 48000
    voice = ((t > 0.5) & (t < 1.6)) | ((t > 3.6) & (t < 4.4))
    sig = np.where(voice, 0.3 * np.sin(2 * np.pi * 220 * t), 0.001 * np.sin(2 * np.pi * 50 * t)).astype("<f4")
    spans = speech_spans(sig, -63.0, 49.0)
    assert len(spans) == 2
    assert spans[0][0] == pytest.approx(0.47, abs=0.03) and spans[1][1] == pytest.approx(4.43, abs=0.03)
    sh = parse_script({"shots": [{"id": "cta", "line": "Hit record, and the reel builds."}]}).shots[0]
    said = [("Hit", 0.5, 0.9), ("record,", 0.9, 1.6), ("and", 1.7, 3.8), ("the", 3.8, 3.95), ("reel", 3.95, 4.15),
            ("builds.", 4.15, 4.4)]
    ws = [{"w": w, "s": s, "e": e} for w, s, e in said]
    raw = script_check(sh, ws, 5.0)
    snapped = script_check(sh, snap_to_speech(ws, spans), 5.0)
    assert raw["cuts"] == 0 and snapped["cuts"] == 1
    assert snapped["kept_seconds"] == pytest.approx(raw["kept_seconds"] - 1.8, abs=0.1)   # the 2 s pause, less pads


# --- end to end on real media (transcription mocked) -------------------------------------

def test_check_take_writes_report_and_words(take):
    out = take / "qa" / "hook-1.json"
    r = check_take(take / "hook-1.mp4", take / "script.json", "hook", out, source=take / "upload.mp4",
                   transcribe_fn=lambda p: words())
    assert json.loads(out.read_text()) == r
    assert json.loads((take / "qa" / "hook-1.words.json").read_text())[0]["w"] == "most"
    assert r["take"] == "hook-1" and r["shot"] == "hook" and r["verdict"] == "great", r["checks"]
    v, a, s = r["video"], r["audio"], r["script"]
    assert (v["width"], v["height"], v["fps"], v["effective_9x16"]) == (360, 640, 30.0, [360, 640])
    assert 60 < v["luma_mean"] < 200 and v["luma_p5"] <= v["luma_mean"] <= v["luma_p95"] and v["blur"] < 8
    assert v["vfr_source"] is False
    assert a["sample_rate"] == 44100 and a["clipped_samples"] == 0   # source rate (lavfi sine)
    assert -25 < a["lufs"] < -5 and a["snr_db"] > 35
    assert s["coverage"] == 1.0 and s["misread"] == [] and s["cuts"] == 0 and s["score"] > 90


def test_check_take_misread_is_a_retake(take):
    r = check_take(take / "hook-1.mp4", take / "script.json", "hook", take / "qa2" / "hook-1.json",
                   transcribe_fn=lambda p: words({4: "days"}))
    assert r["verdict"] == "retake"
    assert r["script"]["misread"] == [{"expected": "hours", "heard": "days"}]
    assert any(c["id"] == "misread" and "days" in c["message"] for c in r["checks"])


def test_takecheck_never_imports_torch():
    code = "import sys, reel_director.takecheck, reel_director.__main__; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"


# --- normalization -----------------------------------------------------------------------

def test_normalize_applies_rotation_and_makes_cfr_av_from_zero(tmp_path):
    land, vfr, rot = tmp_path / "land.mp4", tmp_path / "vfr.mp4", tmp_path / "rot.mp4"
    # 30 fps camera with a 0.3 s hiccup (dropped frames), stereo audio starting 0.2 s late
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2",
       "-vf", "setpts='if(gt(N,30),PTS+0.3/TB,PTS)'", "-fps_mode", "vfr", "-af", "adelay=200|200",
       "-ac", "2", "-c:v", "libx264", "-c:a", "aac", str(vfr))
    ff("-display_rotation", "90", "-i", str(vfr), "-c", "copy", str(rot))
    src = capture.probe(rot)
    assert (src.width, src.height, src.rotation, src.vfr) == (180, 320, 90, True) and src.dropped_frames >= 8
    info = capture.normalize(rot, land)
    out = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(land)],
                                    capture_output=True, text=True, check=True).stdout)["streams"]
    v = next(s for s in out if s["codec_type"] == "video")
    a = next(s for s in out if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["profile"], v["pix_fmt"]) == (180, 320, "High", "yuv420p")
    assert v["r_frame_rate"] == v["avg_frame_rate"] == "30/1" and not v.get("side_data_list")
    assert (a["codec_name"], a["channels"], a["sample_rate"]) == ("aac", 1, "48000")
    assert float(v["start_time"]) == 0 and float(a["start_time"]) == 0
    assert info["fps"] == 30 and info["source"]["vfr"] is True and capture.probe(land).vfr is False


def _peak_db(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                          "astats=measure_overall=Peak_level:measure_perchannel=none", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(err.rsplit("Peak level dB: ", 1)[1].split()[0])


@pytest.mark.parametrize("pan, kept", [("stereo|c0=c0|c1=c0", "0.5*c0+0.5*c1"),   # browser: mono mic twice
                                       ("stereo|c0=c0|c1=0.001*c0", "1*c0")])   # USB interface, input 2 empty
def test_normalize_downmix_keeps_the_voice_level(tmp_path, pan, kept):
    src, out = tmp_path / "st.mov", tmp_path / "mono.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=1", "-f", "lavfi", "-i", "sine=f=440:d=1",
       "-af", f"volume=0.5,pan={pan}", "-c:v", "libx264", "-c:a", "pcm_s16le", str(src))
    info = capture.normalize(src, out)
    assert info["downmix"] == f"pan=mono|c0={kept}"
    assert abs(_peak_db(out) - _peak_db(src)) < 0.5      # -ac 1 alone adds +3 dB to the duplicated mic


def test_normalize_rejects_a_take_without_audio(tmp_path):
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1", "-c:v", "libx264", str(tmp_path / "mute.mp4"))
    with pytest.raises(capture.CaptureError, match="no audio"):
        capture.normalize(tmp_path / "mute.mp4", tmp_path / "out.mp4")
    assert not list(tmp_path.glob("*out*"))


def test_frame_rate_and_size_choices():
    assert [capture.target_fps(x) for x in (0, 15, 20, 23.976, 25, 29.97, 59.94)] == [30, 30, 30, 24, 25, 30, 60]
    assert capture.effective_9x16(1920, 1080) == (607, 1080) and capture.effective_9x16(1080, 1920) == (1080, 1920)
    assert capture.output_size(2160, 3840) == (1440, 2560)     # 4K portrait: lean, still > 1080 for zooms
    assert capture.output_size(3840, 2160) == (3840, 2160)     # landscape 4K: its 9:16 crop is only 1215 wide
    assert capture.output_size(1920, 1080) == (1920, 1080)
    assert Path(capture.__file__).name == "capture.py"
