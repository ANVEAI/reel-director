"""Face track (face.py) and the face-driven take QA it feeds (takecheck framing + misread context)."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from reel_director import face
from reel_director.face import Face, FaceUnavailable, smooth
from reel_director.schema import parse_script
from reel_director.takecheck import _framing_checks, check_take, misread_context, script_check
from reel_director.timing import align

REAL = Path(__file__).resolve().parents[1] / "work" / "real-1" / "raw" / "hook-1.mp4"


def mk(x=400.0, y=900.0, eye_y=1018.0, conf=0.95) -> Face:
    """A face like the founder's: 394 px box, pupils 158 px apart, mouth 153 px under the eyes."""
    return Face((x, y, 394.0, 394.0), ((x + 120, eye_y), (x + 278, eye_y)), (x + 199, eye_y + 153), y + 394, conf)


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


class FakeBackend:
    """Face position follows the frame's brightness (a lavfi colour ramp), with seeded jitter;
    frames darker than `absent_below` have no face."""
    name = "fake"

    def __init__(self, absent_below=-1.0, jitter=3.0):
        self.absent_below, self.rng, self.jitter = absent_below, np.random.default_rng(7), jitter

    def detect(self, rgbx):
        lum = float(rgbx[..., :3].mean())
        if lum < self.absent_below:
            return None
        h = rgbx.shape[0]
        return mk(x=20.0, y=0.3 * h, eye_y=0.5 * h + lum / 10 + self.rng.normal(0, self.jitter))


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """1 s, 30 fps, 108x192, brightness ramping from black to white."""
    d = tmp_path_factory.mktemp("clip")
    ff("-f", "lavfi", "-i", "color=c=black:s=108x192:r=30:d=1", "-vf", "geq=lum='255*N/29':cb=128:cr=128",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-qp", "0", str(d / "take-1.mp4"))
    return d / "take-1.mp4"


# --- smoothing ------------------------------------------------------------------------------

def test_smooth_fills_short_gaps_and_keeps_long_ones():
    raw = [mk()] * 3 + [None] * 2 + [mk()] * 3 + [None] * 3 + [mk()] * 3
    out = smooth(raw)
    assert all(out[i] is not None for i in range(8))           # a 2-sample blink is interpolated
    assert [out[i] for i in range(8, 11)] == [None] * 3        # a 3-sample gap is a real absence
    assert out[3].eyes[0][1] == pytest.approx(1018.0)


def test_smooth_kills_jitter_and_spikes_but_follows_motion():
    rng = np.random.default_rng(1)
    ys = 1000 + 2.0 * np.arange(60)                            # a steady lean down the frame
    raw = [mk(eye_y=y + rng.normal(0, 4)) for y in ys]
    raw[30] = mk(eye_y=ys[30] + 80)                            # one detector glitch
    sm = np.array([f.eyes[0][1] for f in smooth(raw)])
    noisy = np.array([f.eyes[0][1] for f in raw])
    assert np.std(np.diff(sm, 2)) < np.std(np.diff(noisy, 2)) / 4
    assert abs(sm[30] - ys[30]) < 6                            # the spike is gone
    assert np.max(np.abs(sm[5:-5] - ys[5:-5])) < 5             # zero phase: no lag on the ramp


# --- summary --------------------------------------------------------------------------------

def test_summary_ratios_and_stability():
    frames = [face._frame_dict(i / 10, mk()) for i in range(20)] + [None]
    s = face.summary(frames, 1080, 1920, detected=20)
    assert s["eye_y_med"] == pytest.approx(1018 / 1920, abs=1e-4)
    assert s["face_h_med"] == pytest.approx(394 / 1920, abs=1e-4)
    assert s["center_x_med"] == pytest.approx(597 / 1080, abs=1e-4)
    assert s["present"] == pytest.approx(20 / 21, abs=1e-3) and s["stable"] is True
    assert s["ipd_px_med"] == 158.0 and s["chin_y_med"] == pytest.approx(1294 / 1920, abs=1e-4)
    moving = [face._frame_dict(i / 10, mk(x=100.0 + 40 * i)) for i in range(20)]
    assert face.summary(moving, 1080, 1920)["stable"] is False


def test_summary_without_face():
    s = face.summary([None, None], 1080, 1920)
    assert s == {"eye_y_med": None, "face_h_med": None, "center_x_med": None, "present": 0.0, "stable": False}


# --- track ----------------------------------------------------------------------------------

def test_face_track_writes_the_contract(clip, tmp_path):
    out = tmp_path / "qa" / "take-1.face.json"
    tr = face.face_track(clip, out, backend=FakeBackend(absent_below=40))
    assert json.loads(out.read_text()) == tr
    assert {k: tr[k] for k in ("version", "take", "w", "h", "fps", "step", "backend")} == {
        "version": 1, "take": "take-1", "w": 108, "h": 192, "fps": 30.0, "step": 3, "backend": "fake"}
    fr = tr["frames"]
    assert len(fr) == 10 and fr[0] is None and fr[-1] is not None
    assert [f["t"] for f in fr if f] == [round(k * 0.1, 3) for k in range(10) if fr[k]]
    f = fr[-1]
    assert set(f) == {"t", "box", "eyes", "mouth", "chin_y", "conf"} and f["eyes"][0][0] < f["eyes"][1][0]
    assert 0 < tr["summary"]["present"] < 1
    again = tmp_path / "again.json"
    face.face_track(clip, again, backend=FakeBackend(absent_below=40))
    assert again.read_bytes() == out.read_bytes()             # deterministic


def test_face_at_interpolates_and_respects_gaps():
    tr = {"step": 3, "fps": 30.0, "frames": [face._frame_dict(0.0, mk(eye_y=1000)),
                                             face._frame_dict(0.1, mk(eye_y=1010)), None, None]}
    assert face.face_at(tr, 0.05)["eyes"][0][1] == pytest.approx(1005.0)
    assert face.face_at(tr, 0.1)["eyes"][0][1] == 1010.0
    assert face.face_at(tr, 0.3) is None and face.face_at(tr, 9.0) is None
    assert face.face_at(tr, -1.0)["eyes"][0][1] == 1000.0


def test_protected_box_and_chin_clearance():
    f = face._frame_dict(0.0, mk())
    x, y, w, h = face.protected_box(f)
    (lx, ly), (rx, _) = f["eyes"]
    mx, my = f["mouth"]
    assert x < lx - 0.2 * 158 and x + w > rx + 0.2 * 158        # eye corners
    assert y < ly - 0.06 * 158 and y + h > my + 0.24 * 158      # lids, lower lip
    assert y > f["box"][1] and y + h < f["chin_y"]              # forehead and chin stay free
    assert face.overlaps([x, y, w, h], [0, my, 1080, 10]) and not face.overlaps([x, y, w, h], [0, 1400, 1080, 100])
    assert face.chin_clear_y(f) == pytest.approx(f["chin_y"] + 0.35 * 158, abs=0.1)


@pytest.mark.parametrize("eye, scale, after", [(0.40, 1.0, 0.40), (0.45, None, 0.40), (0.53, 1.10, 0.483),
                                               (0.30, 1.10, 0.33)])
def test_reframe_eye_reach(eye, scale, after):
    s, out = face.reframe_eye(eye)
    assert out == pytest.approx(after, abs=1e-3)
    assert 1.0 <= s <= face.REFRAME_MAX and (scale is None or s == pytest.approx(scale))


def test_no_backend_degrades(monkeypatch, tmp_path):
    def broken():
        raise FaceUnavailable("no Vision here")
    monkeypatch.setattr(face, "BACKENDS", {"vision": broken})
    notes = []
    assert face.prep_faces([tmp_path / "x.mp4"], tmp_path, log=notes.append) == {}
    assert notes == ["  face track skipped: no Vision here"]
    with pytest.raises(FaceUnavailable):
        face.get_backend("mediapipe")


def test_face_never_imports_torch():
    code = "import sys, reel_director.face, reel_director.matte; print('torch' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip() == "False"


@pytest.mark.skipif(not REAL.exists() or sys.platform != "darwin", reason="needs macOS Vision and work/real-1")
def test_vision_on_the_founders_take(tmp_path):
    try:
        backend = face.get_backend()
    except FaceUnavailable:
        pytest.skip("pyobjc Vision not installed")
    s = face.face_track(REAL, tmp_path / "hook-1.face.json", backend=backend)["summary"]
    # Measured and checked by eye on drawn frames: pupils at ~1018 px of 1920, box ~0.20 H.
    assert 0.50 < s["eye_y_med"] < 0.56 and 0.17 < s["face_h_med"] < 0.23 and s["present"] >= 0.95


# --- takecheck: framing guidance and misread context ----------------------------------------

def summ(**kw):
    return {"eye_y_med": 0.40, "face_h_med": 0.20, "center_x_med": 0.50, "present": 1.0, "stable": True,
            "ipd_px_med": 158.0, "w": 1080, "h": 1920, **kw}


def ids(checks):
    return {c["id"]: c["level"] for c in checks}


def test_framing_eyes_too_low_says_how_far():
    (c,) = _framing_checks(summ(eye_y_med=0.53))
    assert (c["id"], c["level"]) == ("framing", "warn")
    assert "53%" in c["message"] and "sit ~10 cm higher" in c["message"] and "lower the camera ~10 cm" in c["message"]


def test_framing_reframe_absorbs_small_offsets():
    (c,) = _framing_checks(summ(eye_y_med=0.45))
    assert c["level"] == "ok" and "after the auto-reframe" in c["message"]
    assert ids(_framing_checks(summ())) == {"framing": "ok"}


@pytest.mark.parametrize("kw, want, words", [
    ({"eye_y_med": 0.28}, "framing", "raise the camera"),
    ({"face_h_med": 0.09}, "size", "closer"),
    ({"face_h_med": 0.36}, "size", "farther back"),
    ({"center_x_med": 0.62}, "centre", "to your right"),     # takes aren't mirrored: image right = your left
    ({"center_x_med": 0.38}, "centre", "to your left"),
    ({"present": 0.5}, "face", "out of frame"),
])
def test_framing_warnings(kw, want, words):
    checks = _framing_checks(summ(**kw))
    assert ids(checks) == {want: "warn"}
    assert words in checks[0]["message"]


def test_no_face_no_framing_check():
    assert _framing_checks(None) == [] and _framing_checks(summ(eye_y_med=None)) == []


def test_misread_shows_the_phrase_in_context():
    """turn-1 of the founder's test: Whisper heard 'pass the record' for 'pressed record'."""
    sh = parse_script({"shots": [{"id": "turn", "line": "What if the edit was finished before you even pressed record?"}]}).shots[0]
    said = "What if the edit was finished before you even pass the record?".split()
    asr = [{"w": w, "s": 0.3 * i, "e": 0.3 * i + 0.25} for i, w in enumerate(said)]
    assert misread_context(sh, asr, align(sh, asr)) == [{"said": "…even pass the record", "script": "…even pressed record"}]
    assert script_check(sh, asr, 5.0)["misread"] == [{"expected": "pressed", "heard": "pass the"}]   # unchanged


def test_check_take_reports_face_and_framing(tmp_path):
    ff("-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=2", "-f", "lavfi", "-i", "sine=f=220:d=2",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp_path / "hook-1.mp4"))
    line = "Most creators waste three hours editing one reel."
    (tmp_path / "script.json").write_text(json.dumps({"width": 360, "height": 640, "shots": [{"id": "hook", "line": line}]}))
    words = [{"w": w, "s": 0.2 + 0.2 * i, "e": 0.38 + 0.2 * i} for i, w in enumerate(line.split())]
    seen = []

    def fake_face(media, out):
        seen.append(out)
        return summ(eye_y_med=0.53, ipd_px_med=52.7)
    r = check_take(tmp_path / "hook-1.mp4", tmp_path / "script.json", "hook", tmp_path / "qa" / "hook-1.json",
                   transcribe_fn=lambda m: words, face_fn=fake_face)
    assert seen == [tmp_path / "qa" / "hook-1.face.json"]
    assert r["face"]["eye_y_med"] == 0.53 and ids(r["checks"])["framing"] == "warn"
    assert "~10 cm" in next(c["message"] for c in r["checks"] if c["id"] == "framing")   # 0.13 x 640 px / (52.7/6.3)
