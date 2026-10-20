"""Subject matte (matte.py): alpha WebM, grey matte, baked background treatment."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from reel_director import matte
from reel_director.face import FaceUnavailable, frames

REAL = Path(__file__).resolve().parents[1] / "work" / "real-1" / "raw" / "hook-1.mp4"
W, H = 216, 384


class LeftHalf:
    """The 'person' is the left half of the frame; the mask comes at half resolution, as Vision's does."""
    name = "fake-seg"

    def mask(self, rgbx):
        h, w = rgbx.shape[0] // 2, rgbx.shape[1] // 2
        m = np.zeros((h, w), np.uint8)
        m[:, : w // 2] = 255
        return m


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """1 s of a busy test pattern at 30 fps, with audio."""
    d = tmp_path_factory.mktemp("matte")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=s={W}x{H}:r=30:d=1", "-f", "lavfi", "-i", "sine=f=330:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-qp", "0", "-c:a", "aac", "-shortest", str(d / "hook-1.mp4")], check=True)
    return d / "hook-1.mp4"


def decode(path: Path, fmt: str, codec: list[str] | None = None) -> np.ndarray:
    ch = {"rgba": 4, "gray": 1, "rgb24": 3}[fmt]
    r = subprocess.run(["ffmpeg", "-v", "error", *(codec or []), "-i", str(path), "-f", "rawvideo", "-pix_fmt", fmt,
                        "pipe:1"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, H, W, ch)


def test_alpha_webm_carries_the_person_as_alpha(clip, tmp_path):
    out = tmp_path / "hook-1.matte.webm"
    r = matte.matte(clip, out, seg=LeftHalf())
    assert (r["kind"], r["frames"], r["mask_size"], r["backend"]) == ("alpha", 30, [W // 2, H // 2], "fake-seg")
    assert r["bytes"] == out.stat().st_size > 0 and r["person_share"] == 0.5
    v = decode(out, "rgba", ["-c:v", "libvpx-vp9"])            # the native vp9 decoder drops alpha
    assert len(v) == 30
    a = v[..., 3]
    assert a[:, :, : W // 2 - 8].min() > 240 and a[:, :, W // 2 + 8:].max() < 15
    src = decode(clip, "rgba")
    assert np.abs(v[:, :, : W // 2 - 8, :3].astype(int) - src[:, :, : W // 2 - 8, :3]).mean() < 6   # the take's pixels


def test_grey_matte(clip, tmp_path):
    out = tmp_path / "hook-1.matte.mp4"
    r = matte.matte(clip, out, kind="mask", seg=LeftHalf())
    g = decode(out, "gray")[..., 0]
    assert r["kind"] == "mask" and len(g) == 30
    assert g[:, :, : W // 2 - 8].min() > 235 and g[:, :, W // 2 + 8:].max() < 20


def test_treat_background_blurs_and_dims_only_the_background(clip, tmp_path):
    out = tmp_path / "hook-1.bg.mp4"
    r = matte.treat_background(clip, out, seg=LeftHalf())
    assert r["kind"] == "treated" and r["frames"] == 30 and (r["blur"], r["dim"]) == (matte.BLUR, matte.DIM)
    t, s = decode(out, "rgb24").astype(float), decode(clip, "rgb24").astype(float)
    keep = (slice(None), slice(None), slice(0, W // 2 - 12))
    assert np.abs(t[keep] - s[keep]).mean() < 4                # the subject is untouched
    bg = (slice(None), slice(None), slice(W // 2 + 24, None))

    def edges(x):   # the strongest horizontal steps: hard edges in the pattern, soft after the blur
        return np.percentile(np.abs(np.diff(x.mean(-1), axis=2)), 99.5)
    assert edges(t[bg]) < edges(s[bg]) / 4
    assert t[bg].mean() == pytest.approx(s[bg].mean() * (1 - matte.DIM), rel=0.12)
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                              str(out)], capture_output=True, text=True, check=True).stdout.split()
    assert streams == ["video", "audio"]


def test_outputs_are_deterministic(clip, tmp_path):
    for name, run in (("x.webm", lambda o: matte.matte(clip, o, seg=LeftHalf())),
                      ("x.mp4", lambda o: matte.treat_background(clip, o, seg=LeftHalf()))):
        a, b = tmp_path / f"a-{name}", tmp_path / f"b-{name}"
        run(a)
        run(b)
        assert a.read_bytes() == b.read_bytes(), name


def test_bad_kind_and_no_backend(clip, tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        matte.matte(clip, tmp_path / "x.webm", kind="png", seg=LeftHalf())
    monkeypatch.setattr(matte.sys, "platform", "linux")
    with pytest.raises(FaceUnavailable):
        matte.get_segmenter()


@pytest.mark.skipif(not REAL.exists() or sys.platform != "darwin", reason="needs macOS Vision and work/real-1")
def test_vision_person_mask_on_the_founders_take():
    try:
        seg = matte.get_segmenter()
    except FaceUnavailable:
        pytest.skip("pyobjc Vision not installed")
    _, img = next(frames(REAL, 1))
    m = seg.mask(img)
    assert m.shape == (2016, 1512)                              # the "accurate" level's mask
    assert 0.3 < np.mean(m >= 128) < 0.5                        # measured 0.396: head and torso
    ys, xs = int(0.53 * m.shape[0]), int(0.53 * m.shape[1])     # between the eyes (face track)
    assert m[ys, xs] > 200 and m[int(0.1 * m.shape[0]), int(0.1 * m.shape[1])] < 30   # face in, wall poster out
