"""LEARN: creator profile (framing / light / voice / speech -> coaching tips) and the style reference."""
import json
import subprocess

import numpy as np
import pytest

from reel_director import learn, styleref
from reel_director.presets import resolve_style

FOUNDER = {"box": [0.35, 0.466, 0.36, 0.20], "eyes": [[0.462, 0.524], [0.606, 0.522]], "mouth": [0.534, 0.6],
           "chin_y": 0.672, "conf": 1.0}     # Apple Vision on work/real-1 hook-1 (rounded)


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def face(dy=0.0, dx=0.0):
    f = json.loads(json.dumps(FOUNDER))
    f["box"][0] += dx
    f["box"][1] += dy
    f["eyes"] = [[x + dx, y + dy] for x, y in f["eyes"]]
    f["mouth"] = [f["mouth"][0] + dx, f["mouth"][1] + dy]
    f["chin_y"] += dy
    return f


# --- framing --------------------------------------------------------------------------------------------------
def test_reframe_cannot_reach_founder_eye_line():
    r = learn.reframe_reach(0.526, 0.39)
    assert r == {"scale": 1.1, "eye_y_after": 0.479, "fixable": False}   # 1.1 * 0.526 - 0.1


def test_reframe_fixes_small_offsets_and_never_moves_down():
    assert learn.reframe_reach(0.44, 0.3)["fixable"]
    up = learn.reframe_reach(0.37, 0.2)                 # scaling about the top pushes the eyes down a little
    assert up["fixable"] and up["scale"] <= learn.REFRAME_MAX
    assert learn.reframe_reach(0.30, 0.15) == {"scale": 1.1, "eye_y_after": 0.33, "fixable": False}


def test_reframe_keeps_headroom():
    r = learn.reframe_reach(0.45, 0.05)                 # hair near the top: lifting would crop the head
    assert r["eye_y_after"] >= 0.44 and not r["fixable"]


def test_caption_lines_below_chin_and_limits_agree():
    assert learn.caption_lines_below_chin(0.142, 0.0805) == 1    # the founder: 1040 px chin + 54 px beard clearance
    assert learn.caption_lines_below_chin(0.10, 0.057) == 2
    assert learn.caption_lines_below_chin(0.20, 0.113) == 0
    for n in (1, 2):
        e2c = learn.max_eye_to_chin(n) - 1e-4
        assert learn.caption_lines_below_chin(e2c, learn.IPD_PER_E2C * e2c) == n
        assert learn.caption_lines_below_chin(e2c + 2e-3, learn.IPD_PER_E2C * (e2c + 2e-3)) == n - 1


def test_framing_summary_from_faces():
    fr = learn.framing([face(), face(0.01), None, face(-0.01)], 1080, 1920)
    assert fr["eye_y"] == 0.523 and fr["present"] == 0.75 and fr["samples"] == 4
    assert fr["eye_to_chin"] == pytest.approx(0.149, abs=1e-3)
    assert fr["chin_k"] == pytest.approx(0.149 / 0.077, abs=0.01)
    assert fr["px_per_cm"] == pytest.approx(0.144 * 1080 / 6.3, abs=0.05)
    assert learn.framing([None, None], 1080, 1920) is None


def test_read_face_json_normalises_vision_track(tmp_path):
    p = tmp_path / "hook-1.face.json"
    p.write_text(json.dumps({"version": 1, "take": "hook-1", "w": 1080, "h": 1920, "fps": 30, "step": 3,
                             "frames": [{"t": 0.0, "box": [378, 895, 389, 384], "eyes": [[654, 1002], [499, 1006]],
                                         "mouth": [577, 1152], "chin_y": 1290, "conf": 0.98}, None]}))
    a, b = learn.read_face_json(p)
    assert b is None and a["eyes"][0][0] < a["eyes"][1][0]          # sorted image-left first
    assert a["box"][1] == pytest.approx(895 / 1920) and a["chin_y"] == pytest.approx(1290 / 1920)


# --- light ----------------------------------------------------------------------------------------------------
def test_cct_and_lab():
    assert learn.cct_k([255, 255, 255]) == pytest.approx(6504, abs=10)
    assert learn.cct_k([255, 214, 170]) < learn.CCT_WARM
    assert learn.cct_k([200, 220, 255]) > learn.CCT_COOL
    assert learn.lab([255, 255, 255]) == pytest.approx([100.0, 0.0, 0.0], abs=0.2)


def test_light_stats_on_a_synthetic_frame():
    rgb = np.full((960, 540, 3), 200, np.uint8)            # neutral wall
    rgb[400:960, 150:400] = (150, 110, 90)                   # person (face + body)
    rgb[520:560, 200:270] = (170, 125, 105)                  # brighter image-left cheek
    rgb[150:280, 60:480:6] = 0                               # stripes = a busy poster in the title band
    st = learn.light_stats(rgb, face())
    assert st["face_lr"] > 1 and st["title_edges"] > learn.BUSY_EDGES
    li = learn.summarize_light([st, st])
    assert li["busy_background"] and li["white_point_k"] == pytest.approx(6500, abs=50)


# --- tips -----------------------------------------------------------------------------------------------------
def profile(fr=None, light=None, voice=None, wpm=150.0):
    return {"framing": fr, "light": light, "voice": voice, "speech": {"wpm": wpm} if wpm else None}


def test_founder_tips_lower_or_tilt_the_camera_not_raise():
    fr = learn.framing([face()] * 4, 1080, 1920)
    v = {"lufs": -28.0, "snr_db": 31.6, "noise_floor_db": -60, "peak_dbfs": -10}
    tips = learn.coaching_tips(profile(fr, voice=v))
    first = tips[0]
    assert first["id"] == "eye_line" and first["level"] == "fix"
    assert "Tilt the camera down" in first["text"] and "lower it about" in first["text"]
    cm = int(first["text"].split("lower it about ")[1].split(" cm")[0])
    assert 8 <= cm <= 11                                     # (0.523 - 0.40) * 1920 px / (155 px / 6.3 cm)
    ids = [t["id"] for t in tips]
    assert "face_size" in ids and ids.index("noise") < ids.index("pace")
    assert [t["level"] for t in tips] == sorted((t["level"] for t in tips), key=["fix", "nudge", "keep"].index)


def test_tips_raise_camera_centre_and_light_sides():
    fr = learn.framing([face(-0.19, -0.12)] * 3, 1080, 1920)     # eyes at 0.33, face image-left
    li = {"face_luma": 80.0, "bg_to_face": 1.1, "face_lr": 0.6, "white_point_k": 3600.0, "busy_background": False,
          "title_band_edges": 0.01}
    tips = {t["id"]: t for t in learn.coaching_tips(profile(fr, li))}
    assert "raise it" in tips["eye_line"]["text"] and "Tilt the camera up" in tips["eye_line"]["text"]
    assert "to your left" in tips["centre"]["text"]          # image-left = the creator's right: move left
    assert "on your right" in tips["side_light"]["text"]     # image-left cheek darker = their right cheek
    assert tips["exposure"]["level"] == "fix" and "warm" in tips["colour"]["text"]


def test_voice_and_pace_tips():
    v = {"lufs": -34.0, "snr_db": 20.0, "noise_floor_db": -50, "peak_dbfs": -20}
    tips = {t["id"]: t for t in learn.coaching_tips(profile(voice=v, wpm=120))}
    assert tips["voice_level"]["level"] == tips["noise"]["level"] == "fix"
    assert tips["pace"]["level"] == "nudge" and tips["face"]["level"] == "fix"
    clean = {t["id"]: t for t in learn.coaching_tips(profile(voice={**v, "lufs": -22.0, "snr_db": 40.0}))}
    assert clean["noise"]["level"] == "keep" and "voice_level" not in clean


def test_speech_rate():
    words = [{"w": "a", "s": 0.0, "e": 0.3}, {"w": "b", "s": 0.3, "e": 0.6}, {"w": "c", "s": 1.6, "e": 2.0}]
    r = learn.speech_rate(words)
    assert r["wpm"] == 90.0 and r["articulation_wpm"] == 180.0 and r["pauses"] == 1
    assert learn.speech_rate(words[:2]) is None


# --- reference ------------------------------------------------------------------------------------------------
def test_visual_changes_find_hard_cuts_not_dissolves():
    rng = np.random.default_rng(1)
    g = np.clip(rng.normal(100, 2, (120, 32, 18)), 0, 255)
    g[30:] += 60                                            # hard cut at frame 30
    g[75:] -= 40                                            # and 75
    g[90:105] += np.linspace(0, 60, 15)[:, None, None]      # a 15-frame dissolve that stays
    g[105:] += 60
    assert styleref.visual_changes(g.astype(np.uint8), 30.0) == [1.0, 2.5]


def test_caption_band_ignores_static_poster_and_smooth_motion():
    rng = np.random.default_rng(2)
    n, H, W = 24, 240, 135
    g = np.full((n, H, W), 120, np.uint8)
    poster = (rng.random((30, 110)) > 0.5) * 255             # dense, static
    for k in range(n):
        g[k, 35:65, 12:122] = poster
        g[k, 132:146, 20:115] = (rng.random((14, 95)) > 0.5) * 255 if k % 2 else 120   # text that swaps
        y = 170 + (k % 6) * 3
        g[k, y:y + 20, 40:80] = 140                          # a smooth moving hand
    band = styleref.caption_band(g)
    assert 0.53 <= band["center_y"] <= 0.62 and band["y0"] >= 0.5
    assert styleref.caption_band(np.full((n, H, W), 120, np.uint8)) is None


def test_caption_zone_mapping():
    fr = learn.framing([face()] * 2, 1080, 1920)            # eyes 0.523, mouth 0.6, chin 0.672
    assert styleref.caption_zone({"y0": 0.54, "y1": 0.6}, fr) == "over-face"   # the real-1 reel (P1)
    assert styleref.caption_zone({"y0": 0.69, "y1": 0.75}, fr) == "below-chin"
    assert styleref.caption_zone({"y0": 0.80, "y1": 0.86}, fr) == "lower-band"
    assert styleref.caption_zone({"y0": 0.30, "y1": 0.42}, fr) == "above-head"
    assert styleref.caption_zone(None, fr) is None


def test_broll_share_counts_faceless_shots_not_lone_misses():
    faces = [FOUNDER] * 4 + [None] + [FOUNDER] * 3 + [None] * 8 + [FOUNDER] * 8    # 4 fps, 6 s
    assert styleref.broll_share(faces, 4, [2.0, 4.0], 6.0) == pytest.approx(1 / 3)
    assert styleref.broll_share([], 4, [], 6.0) == 0.0


def test_nearest_pace():
    assert [styleref.nearest_pace(g) for g in (1.42, 2.6, 4.5, None)] == ["punchy", "standard", "calm", "calm"]


@pytest.fixture(scope="module")
def cut_video(tmp_path_factory):
    """3 s: two hard cuts (1.0 s, 2.0 s) between flat colours, a tone underneath."""
    d = tmp_path_factory.mktemp("ref")
    out = d / "ref.mp4"
    ff("-f", "lavfi", "-i", "color=c=0x303030:s=180x320:r=30:d=1", "-f", "lavfi", "-i",
       "color=c=0xC0C0C0:s=180x320:r=30:d=1", "-f", "lavfi", "-i", "color=c=0x606060:s=180x320:r=30:d=1",
       "-f", "lavfi", "-i", "sine=f=300:d=3", "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
       "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out))
    return out


def test_style_reference_end_to_end(cut_video):
    calls = []
    backend = lambda rgb: calls.append(rgb.shape) or (FOUNDER if rgb.mean() > 150 else None)   # noqa: E731
    ref = styleref.style_reference([cut_video], backend=backend)
    r = ref["references"][0]
    assert r["visual_changes"] == [1.0, 2.0] and r["caption_band"] is None and r["speech"] is None
    assert r["broll_share"] == pytest.approx(2 / 3, abs=0.02) and calls[0] == (960, 540, 3)
    o = ref["preset_overrides"]
    assert o["pace"] == "punchy" and o["broll_share"] == 0.35 and o["caption_zone"] == "below-chin"
    assert any("capped at 35%" in n for n in ref["notes"]) and any("metronomic" in n for n in ref["notes"])
    assert resolve_style({"preset": "clean-pro", **o})["pace"] == "punchy"
    assert styleref.style_reference([cut_video], backend=backend) == ref       # deterministic


# --- creator end to end ---------------------------------------------------------------------------------------
@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "raw").mkdir(parents=True)
    (root / "qa").mkdir()
    ff("-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(root / "raw" / "hook-1.mp4"))
    (root / "takes.json").write_text(json.dumps({"hook": [{"src": "raw/hook-1.mp4", "pin": False}]}))
    (root / "qa" / "hook-1.json").write_text(json.dumps({"audio": {"lufs": -27.0, "snr_db": 40.0,
                                                                   "noise_floor_db": -61.0, "peak_dbfs": -9.0}}))
    words = [{"w": w, "s": 0.2 + 0.3 * i, "e": 0.45 + 0.3 * i} for i, w in enumerate("one two three four".split())]
    (root / "qa" / "hook-1.words.json").write_text(json.dumps(words))
    return root


def test_creator_profile_with_backend_and_cli(project):
    prof = learn.creator_profile(project, backend=lambda rgb: face())
    assert prof["takes"] == ["hook-1"] and prof["face_source"] == ["apple-vision"]
    assert prof["framing"]["samples"] == 2 and prof["voice"]["snr_db"] == 40.0
    assert prof["speech"]["wpm"] == pytest.approx(4 / 1.15 * 60, abs=0.2)
    assert prof["coach"]["eye_target"] == 0.40 and prof["coach"]["tip"].startswith("Your eyes sit at")
    assert learn.creator_profile(project, backend=lambda rgb: face()) == prof
    assert learn.main(["creator", str(project)]) == 0                # real backend (or none): a test pattern
    assert json.loads((project / "qa" / "creator.json").read_text())["version"] == 1


def test_creator_prefers_vision_face_track(project):
    track = {"version": 1, "take": "hook-1", "w": 180, "h": 320, "fps": 30, "step": 3,
             "frames": [{"t": 0.0, "box": [63, 100, 65, 64], "eyes": [[83, 128], [109, 128]], "mouth": [96, 150],
                         "chin_y": 166, "conf": 0.99}, {"t": 1.0, "box": [63, 100, 65, 64], "eyes": [[83, 128],
                         [109, 128]], "mouth": [96, 150], "chin_y": 166, "conf": 0.99}]}
    (project / "qa" / "hook-1.face.json").write_text(json.dumps(track))

    def boom(rgb):
        raise AssertionError("backend must not run when VISION's track exists")
    prof = learn.creator_profile(project, backend=boom)
    assert prof["face_source"] == ["face.json"] and prof["framing"]["eye_y"] == 0.4
    assert prof["tips"][0]["id"] != "eye_line" or prof["tips"][0]["level"] != "fix"


def test_reference_cli_refuses_non_files(tmp_path, capsys):
    assert learn.main(["reference", "https://example.com/v.mp4", "--out", str(tmp_path / "s.json")]) == 2
    assert "not a local file" in capsys.readouterr().err


@pytest.mark.skipif(learn.face_backend() is None, reason="Apple Vision unavailable")
def test_apple_vision_runs_and_finds_no_face_in_a_test_pattern(project):
    rgb = learn.frames(project / "raw" / "hook-1.mp4", 180, 320, fps=1, limit=1)[0]
    assert learn.face_backend()(rgb) is None
