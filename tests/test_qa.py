"""QA gates (contract v2 editing director): geometry, the v1 layout estimate, frame-exact grabs, the bitmap sheet,
each gate on synthetic inputs, scoring, and one end-to-end run on a tiny synthetic build (face detector stubbed)."""
import json
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pytest

from reel_director import qa
from reel_director.before_after import (frame_index, grab, legacy_layout, media_at, moments, text, wrap,
                                        write_png)
from reel_director.face import protected_box
from reel_director.qa_face import face_core, face_record, inter, reframed

FACE = {"box": [380, 900, 320, 380], "eyes": [[470, 1030], [610, 1030]], "mouth": [540, 1170], "chin_y": 1280,
        "conf": 1.0}


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def html(caps=(("cap-1", ["Hello", "world"]),), title=None, family="bold", videos=(("hook", 0, 2.0, 0.5),)):
    v = "".join(f'<div class="txl" id="L-{s}-0"><div class="fr"><video id="take-{s}-0" class="clip take" '
                f'src="assets/{s}-1.mp4" muted playsinline data-start="{a}" data-duration="{d}" data-track-index="0" '
                f'data-media-start="{m}"></video></div></div>' for s, a, d, m in videos)
    c = "".join(f'<div id="{i}" class="clip cap"><div id="{i}-in" class="cap-in fit">'
                + " ".join(f'<span id="{i}-w{k}" class="word">{w}</span>' for k, w in enumerate(ws)) + "</div></div>"
                for i, ws in caps)
    t = ('<div id="title-9" class="clip title"><div id="title-9-in" class="g-in title-inner"><div class="title-text fit">'
         + " ".join(f'<span class="tw">{w}</span>' for w in title) + "</div></div></div>") if title else ""
    return f'<body class="cap-{family}">{v}{t}<div id="caps">{c}</div>'


def build(layout, style=None, cards=(), plan=None, shots=None) -> dict:
    tl = {"duration": 4.0, "shots": shots or [{"id": "hook", "start": 0.0, "duration": 4.0, "take": 0, "words": [],
                                               "clips": [{"start": 0.0, "media_in": 1.0, "media_out": 5.0}]}]}
    layout = {"captions": [], "title": None, "cards": list(cards), **layout}
    return {"layout": layout, "style": style or {"pace": "standard"}, "tl": tl, "directed": {"shots": []},
            "plan": plan or {"D": 4.0, "fps": 30, "segs": [], "items": []}, "videos": []}


# ------------------------------------------------------------------------------------------------ geometry
def test_face_core_is_visions_protected_box():
    core = face_core(FACE)
    assert core == protected_box(FACE)
    x, y, w, h = core
    assert y < 1030 - 0.06 * 380 and y + h > 1170 + 0.06 * 380 and x < 470 and x + w > 610   # eyes..mouth + pad
    assert inter([0, 0, 10, 10], [5, 5, 10, 10]) == 25 and inter([0, 0, 10, 10], [10, 0, 5, 5]) == 0


def test_reframe_reaches_only_what_the_zoom_cap_allows():
    r = reframed(FACE, 1920)                               # eyes at 0.536 H
    assert r["scale"] == 1.1 and r["eye_y"] == pytest.approx(0.49, abs=0.005)
    assert r["map"](1030) / 1920 == pytest.approx(r["eye_y"], abs=1e-3)


def test_face_record_scales_to_reel_pixels_and_keeps_the_largest_face():
    lm = {"leftEye": [[100, 200], [110, 200]], "rightEye": [[160, 200], [170, 200]], "nose": [[135, 230]],
          "outerLips": [[120, 260], [150, 270]], "faceContour": [[90, 220], [135, 300], [180, 220]]}
    rec = face_record({"faces": [{"box": [10, 10, 20, 20], "conf": 0.5, "landmarks": {}},
                                 {"box": [80, 150, 110, 160], "conf": 0.99, "landmarks": lm}]}, 2.0)
    assert rec["box"] == [160, 300, 220, 320] and rec["eyes"] == [[210, 400], [330, 400]]
    assert rec["mouth"] == [270, 530] and rec["chin_y"] == 600
    assert face_record({"faces": []}, 2.0) is None


# ------------------------------------------------------------------------------------------------ v1 layout
def test_v1_caption_estimate_matches_the_measured_wrap():
    assert [len(x) for x in wrap(["MOST", "CREATORS"], 76, 696)] == [1, 1]     # measured: two lines on real-1
    assert [len(x) for x in wrap(["WAS", "FINISHED"], 76, 696)] == [2]
    plan = {"caps": [{"id": "cap-1", "s": 0.2, "e": 0.8}], "items": [
        {"id": "title-9", "kind": "title", "s": 0.0, "e": 2.5}, {"id": "broll-3", "kind": "broll", "s": 1, "e": 2}]}
    L = legacy_layout(plan, html(caps=(("cap-1", ["Most", "creators"]),), title=["3", "HOURS", "PER", "REEL?"]))
    x, y, w, h = L["captions"][0]["box"]
    assert (x + w / 2, y + h / 2) == pytest.approx((520, 1110), abs=0.2) and L["captions"][0]["text"] == "MOST CREATORS"
    assert h > 140 and L["title"]["box"][1] == 300 and L["title"]["box"][3] == 2 * 102 + 40
    assert L["cards"][0]["box"] == [0, 0, 1080, 1920] and L["source"] == "legacy-v1-estimate"


# ------------------------------------------------------------------------------------------------ frames / sheet
@pytest.fixture(scope="module")
def ramp(tmp_path_factory) -> Path:
    """30 lossless frames at 30 fps whose grey level is 8 x the frame index."""
    d = tmp_path_factory.mktemp("ramp")
    raw = np.concatenate([np.full((1, 32, 18, 3), 8 * k, np.uint8) for k in range(30)]).tobytes()
    (d / "r.rgb").write_bytes(raw)
    ff("-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "18x32", "-r", "30", "-i", str(d / "r.rgb"),
       "-c:v", "ffv1", str(d / "r.mkv"))
    return d / "r.mkv"


def test_grab_returns_the_exact_frames_in_request_order(ramp):
    fr = grab(ramp, [0.5, 0.0, 0.9, 0.5, 5.0], (18, 32), fps=30)
    assert [int(round(f.mean() / 8)) for f in fr] == [15, 0, 27, 15, 29]       # past the end -> last frame
    assert frame_index(0.49) == 15 and frame_index(0.4833) == 14 and frame_index(1 / 60) == 1


def test_png_writer_is_valid_and_deterministic(tmp_path):
    img = np.zeros((20, 30, 3), np.uint8)
    text(img, 1, 1, "ab?", 1, (255, 0, 0))
    assert img[..., 0].any() and not img[..., 1].any()
    a, b = write_png(tmp_path / "a.png", img).read_bytes(), write_png(tmp_path / "b.png", img).read_bytes()
    assert a == b and a.startswith(b"\x89PNG\r\n\x1a\n")
    idat = a[a.index(b"IDAT") + 4:a.index(b"IEND") - 8]
    assert len(zlib.decompress(idat)) == 20 * (1 + 30 * 3)


def test_moments_map_reel_time_to_media_time():
    tl = {"duration": 4.0, "shots": [{"id": "a", "clips": [{"start": 0, "media_in": 2.0, "media_out": 4.0}]},
                                     {"id": "b", "clips": [{"start": 2.0, "media_in": 1.0, "media_out": 3.0}]}]}
    ms = moments(tl, 4)
    assert [m["shot"] for m in ms] == ["a", "a", "b", "b"]
    assert ms[0] == {"t": 0.5, "shot": "a", "media_t": 2.5} and ms[2]["media_t"] == pytest.approx(1.5)
    assert media_at(tl, 9.0)[0] == "b" and media_at(tl, 9.0)[1] == pytest.approx(4.0 - 1 / 30, abs=1e-3)


# ------------------------------------------------------------------------------------------------ gates
CAP = {"chunk_id": "cap-1", "t0": 0.0, "t1": 2.0, "box": [300, 1040, 480, 150], "text": "HELLO WORLD"}


def test_text_over_face_fails_on_overlap_and_exempts_full_cards():
    b = build({"captions": [CAP]}, cards=[{"id": "c", "t0": 1.0, "t1": 2.0, "layout": "full", "box": [0, 0, 1080, 1920]}])
    ts = [0.0, 0.5, 1.2, 1.5]
    g = qa.gate_text_over_face(b, ts, [FACE] * 4)
    assert g["level"] == "fail" and g["value"]["frames_checked"] == 2 and g["value"]["frames_overlapping"] == 2
    assert g["fix"]["op"] == "move_caption" and g["value"]["worst"]["face_covered_pct"] > 30
    high = {**FACE, "box": [380, 300, 320, 380], "eyes": [[470, 430], [610, 430]], "mouth": [540, 570], "chin_y": 680}
    assert qa.gate_text_over_face(b, ts, [high] * 4)["level"] == "ok"
    assert qa.gate_text_over_face(b, ts, [None] * 4)["level"] == "warn"


def test_caption_zone_fix_follows_the_contract_order_after_the_reachable_reframe():
    b = build({"captions": [CAP]})
    up = {"box": [380, 600, 320, 380], "eyes": [[470, 730], [610, 730]], "mouth": [540, 870], "chin_y": 980, "conf": 1}
    assert qa.caption_fix(b, [0], [up], ["hook"])["args"]["zone"] == "below-chin"
    # eyes at 0.536 H: the 1.10 cap only lifts them to 0.49 H, the bearded chin line stays too low for a caption
    assert qa.caption_fix(b, [0], [FACE], ["hook"])["args"]["zone"] == "above-head"
    titled = build({"captions": [CAP], "title": {"t0": 0.0, "t1": 2.5, "box": [154, 300, 700, 244]}})
    assert qa.caption_fix(titled, [0], [FACE], ["hook"])["args"]["zone"] == "lower-band"   # title owns the top
    assert qa.caption_fix(b, [0], [None], ["hook"])["args"]["zone"] == "lower-band"
    two = build({"captions": [CAP]}, shots=[{"id": "a", "start": 0, "duration": 1, "clips": []},
                                            {"id": "b", "start": 1, "duration": 3, "clips": []}])
    assert qa.caption_fix(two, [0.5, 2.0], [up, FACE], ["a", "b"])["args"] == {"zones": {"a": "below-chin",
                                                                                         "b": "above-head"}}


def test_borrowed_face_fills_a_missed_detection_but_not_across_shots_or_cards():
    shots = [{"id": "a", "start": 0, "duration": 1.0, "clips": []}, {"id": "b", "start": 1.0, "duration": 3.0, "clips": []}]
    b = build({}, shots=shots, cards=[{"id": "c", "t0": 3.0, "t1": 4.0, "layout": "full"}])
    out = qa.fill_faces(b, [0.8, 1.0, 1.2, 3.2, 3.4], [FACE, None, FACE, None, FACE])
    assert out[1]["borrowed"] and out[3] is None and out[0] is FACE


def test_caption_contrast_measures_the_ring_not_the_text():
    b = build({"captions": [CAP]}, style={"caption": "bold", "text": "#FFFFFF"})
    fr = np.zeros((960, 540, 3), np.uint8)
    fr[520:595, 150:390] = 255                             # white text inside the box, black around it
    g = qa.gate_caption_contrast(b, [0.5], [fr])
    assert g["level"] == "ok" and g["value"]["halo_min"] == 21.0
    bright = np.full((960, 540, 3), 235, np.uint8)
    g = qa.gate_caption_contrast(b, [0.5], [bright])
    assert g["level"] == "warn" and g["value"]["effective"] == 21.0 and g["value"]["halo_min"] < 1.3
    g = qa.gate_caption_contrast(build({"captions": [CAP]}, style={"text": "#FFFFFF"}) | {
        "layout": {"captions": [CAP], "caption_family": "minimal", "cards": []}}, [0.5], [bright])
    assert g["level"] == "fail"


def test_title_over_a_busy_background_needs_a_solid_backdrop():
    ti = {"id": "t", "t0": 0.0, "t1": 2.5, "box": [154, 300, 700, 244], "text": "3 HOURS"}
    b = build({"title": ti}, style={"text": "#FFFFFF", "accent": "#FFE14D"})
    rng = np.random.default_rng(0)
    busy = (rng.random((960, 540)) > 0.5)[..., None].repeat(3, 2).astype(np.uint8) * 200
    see = (busy * 0.38 + 5).astype(np.uint8)              # semi-transparent dark plate over the busy wall
    g = qa.gate_title(b, [1.0], [see], {1.0: busy})
    assert g["level"] == "fail" and g["value"]["busy"] and g["fix"]["args"] == {"param": "title_backdrop", "value": "solid"}
    solid = np.full((960, 540, 3), 12, np.uint8)
    assert qa.gate_title(b, [1.0], [solid], {1.0: busy})["level"] == "ok"
    assert qa.gate_title(b, [2.45], [see], {1.0: busy})["message"] == "title not sampled"   # exit frames skipped


def test_safe_zone():
    assert qa.gate_safe(build({"captions": [CAP]}))["level"] == "ok"
    low = {**CAP, "box": [300, 1200, 480, 150]}
    assert qa.gate_safe(build({"captions": [low]}))["level"] == "fail"


def test_pace_from_plan_hides_changes_under_cards_and_proposes_a_drop():
    plan = {"D": 8.0, "fps": 30, "items": [], "segs": [
        {"layer": "L-hook-0", "punches": [[0, 1.08], [30, 1.0], [60, 1.06], [90, 1.0]]},
        {"layer": "L-turn-0", "punches": [[0, 1.0], [165, 1.07]]}]}
    words = [{"w": w, "s": s, "e": s + 0.3} for w, s in (("one", 1.0), ("two", 2.0), ("three", 3.0))]
    shots = [{"id": "hook", "start": 0, "duration": 4.0, "clips": [], "words": words},
             {"id": "turn", "start": 4.0, "duration": 4.0, "clips": [], "words": []}]
    b = build({}, style={"pace": "punchy"}, plan=plan, shots=shots,
              cards=[{"id": "c", "t0": 5.0, "t1": 6.0, "layout": "full"}])
    b["videos"] = [{"id": "take-hook-0", "start": 0.0, "duration": 4.0}, {"id": "take-turn-0", "start": 4.0, "duration": 4.0},
                   {"id": "take-turn-1", "start": 5.5, "duration": 2.5}]
    b["directed"] = {"shots": [{"id": "hook", "cues": [{"type": "punch", "at": w, "auto": True} for w in
                                                       ("one", "two", "three")]}, {"id": "turn", "cues": []}]}
    assert [k for _, k in qa.plan_changes(b)] == ["punch", "punch", "punch", "cut", "card", "card-out"]
    g = qa.gate_pace(b)
    assert g["level"] == "fail" and g["value"]["cv"] < 0.25 and g["value"]["max_static"] == 2.0
    assert g["fix"]["op"] == "drop_cue" and g["fix"]["args"]["shot"] == "hook"


def test_audio_av_black_frozen_and_scoring():
    good = {"lufs": -14.1, "true_peak": -2.0, "short_term_max": -11.0, "av_offset_ms": 0.0, "av_duration_diff_ms": -13.3}
    assert [g["level"] for g in qa.gate_audio(good)] == ["ok", "ok"]
    bad = {**good, "lufs": -16.0, "av_offset_ms": 50.0}
    assert [g["level"] for g in qa.gate_audio(bad)] == ["fail", "fail"]
    b = build({}, cards=[{"id": "c", "t0": 1.0, "t1": 3.0, "layout": "full"}])
    assert qa.gate_black_frozen(b, {"black": [], "frozen": [(1.2, 2.9)]})["level"] == "warn"
    assert qa.gate_black_frozen(b, {"black": [(3.5, 3.9)], "frozen": []})["level"] == "fail"
    ok, fixable = qa._gate("a", "ok", 1, 1, ""), qa._gate("b", "fail", 1, 1, "", {"op": "reframe", "args": {}})
    assert qa.score([ok]) == (100, 100, "ship")
    assert qa.score([ok, fixable]) == (80, 80, "fix")
    assert qa.score([qa._gate("c", "fail", 1, 1, "")]) == (80, 80, "block")
    d = {"status": "ok", "score": 60, "issues": [{"severity": "high"}]}
    assert qa.score([ok], d) == (100, 80, "fix")


def test_framing_and_face_presence():
    b = build({})
    ts = [k * 0.2 for k in range(20)]
    g1, g2 = qa.gate_broll_face(b, ts, [FACE] * 20)
    # eye line 0.536 H: the 1.10 reframe reaches only 0.49 H, so the edit cannot fix it: a warn for the coach, no fix
    assert g1["level"] == "ok" and g2["level"] == "warn" and g2["value"]["hook"]["eye_y"] == pytest.approx(0.536, abs=1e-3)
    assert g2["fix"] is None
    assert g2["value"]["hook"]["reachable_eye_y"] == pytest.approx(0.49, abs=0.005) and "camera" in g2["message"]
    near = {**FACE, "eyes": [[470, 860], [610, 860]]}          # 0.448 H: reachable inside 0.40 +- 0.03 -> the edit's job
    g = qa.gate_broll_face(b, ts, [near] * 20)[1]
    assert g["level"] == "fail" and g["fix"]["op"] == "reframe" and g["fix"]["args"]["shots"] == ["hook"]
    up = {**FACE, "eyes": [[470, 770], [610, 770]]}
    assert qa.gate_broll_face(b, ts, [up] * 20)[1]["level"] == "ok"
    assert qa.gate_broll_face(b, ts, [None] * 20)[0]["level"] == "fail"


# ------------------------------------------------------------------------------------------------ end to end
@pytest.fixture(scope="module")
def synth(tmp_path_factory) -> Path:
    """A 2 s v1-shaped build: one take, two captions on the face line, a title, a master with audio."""
    d = tmp_path_factory.mktemp("build")
    (d / "reel" / "assets").mkdir(parents=True)
    (d / "renders").mkdir()
    (d / "raw").mkdir()
    src = ["-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3", "-f", "lavfi", "-i", "sine=f=220:d=3",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
    ff(*src, str(d / "raw" / "hook-1.mp4"))
    ff("-i", str(d / "raw" / "hook-1.mp4"), "-c", "copy", str(d / "reel" / "assets" / "hook-1.mp4"))
    ff("-ss", "0.5", "-i", str(d / "raw" / "hook-1.mp4"), "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
       "-c:a", "aac", str(d / "renders" / "reel-master.mp4"))
    plan = {"W": 1080, "H": 1920, "fps": 30, "D": 2.0, "segs": [{"layer": "L-hook-0", "punches": [[0, 1.0], [24, 1.06]]}],
            "caps": [{"id": "cap-1", "s": 0.1, "e": 1.0}, {"id": "cap-2", "s": 1.0, "e": 1.9}],
            "items": [{"id": "title-9", "kind": "title", "s": 0.0, "e": 1.5}]}
    page = html(caps=(("cap-1", ["Hello", "world"]), ("cap-2", ["again"])), title=["Big", "title"])
    (d / "reel" / "index.html").write_text(page + f'<script type="application/json" id="rd-plan">{json.dumps(plan)}</script>')
    (d / "reel" / "timeline.json").write_text(json.dumps({"duration": 2.0, "shots": [
        {"id": "hook", "start": 0.0, "duration": 2.0, "take": 0, "words": [{"w": "Hello", "s": 0.1, "e": 0.5}],
         "clips": [{"start": 0.0, "media_in": 0.5, "media_out": 2.5}]}]}))
    (d / "build-takes.json").write_text(json.dumps({"hook": [{"src": "raw/hook-1.mp4"}]}))
    (d / "directed.json").write_text(json.dumps({"style": {"pace": "standard", "text": "#FFFFFF"}, "shots": [
        {"id": "hook", "cues": [{"type": "punch", "at": "Hello", "auto": True}]}]}))
    return d


def test_run_qa_end_to_end_is_deterministic(synth, tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "detect_faces", lambda frames: ([FACE] * len(frames), "stub"))
    a, b = tmp_path / "a", tmp_path / "b"
    rep = qa.run_qa(synth, a)
    qa.run_qa(synth, b)
    ids = {g["id"]: g for g in rep["gates"]}
    assert ids["text_over_face"]["level"] == "fail" and rep["verdict"] in ("fix", "block")
    assert rep["layout_source"] == "legacy-v1-estimate" and rep["face_backend"] == "stub"
    for f in ("qa/report.json", "qa/overlay.png", "renders/before-after.png", "renders/before-after.json",
              "qa/layout.estimated.json"):
        assert (a / f).read_bytes().replace(str(a).encode(), b"") == (b / f).read_bytes().replace(str(b).encode(), b""), f
    ba = json.loads((a / "renders" / "before-after.json").read_text())
    assert ba["pairs"][0]["raw_src"] == "raw/hook-1.mp4" and ba["audio"]["takes"][0]["shot"] == "hook"
    assert not (synth / "qa").exists()                     # the build itself is never written to
