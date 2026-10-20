"""v4 final round (panel review of the founder's reel): the clip's payoff lands on the line, the salient content stays
whole and in view, split inserts bridge instead of flashing the face, QA counts split B-roll and catches text on a
media object, CC BY-SA is opt-in, a reused gallery clip must fit the line, honest credits, the one-accent tint."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from reel_director import broll_flow, media_fit as mf, policy, qa, qa_media, treatments
from reel_director.media import license as L, select as S
from reel_director.media.base import Candidate
from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline

ROOT = Path(__file__).resolve().parents[1]


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


@pytest.fixture(scope="module")
def event_clip(tmp_path_factory) -> Path:
    """3 s, black; a white square appears at 1.5 s (the 'checkmark'), top-left quarter of the frame."""
    p = tmp_path_factory.mktemp("fit") / "event.mp4"
    ff("-f", "lavfi", "-i", "color=c=black:s=540x960:d=3:r=30", "-vf",
       "drawbox=x=60:y=120:w=200:h=200:color=white:t=fill:enable='gte(t,1.5)'", "-pix_fmt", "yuv420p", str(p))
    return p


# ---- media_fit ---------------------------------------------------------------------------------------------------
def test_payoff_is_the_onset_of_the_strongest_change_and_where_it_happens(event_clip):
    assert mf.payoff(event_clip, 3.0) == pytest.approx(1.5, abs=1 / 30 + 1e-6)
    x, y = mf.payoff_xy(event_clip, 3.0, 1.5)
    assert x == pytest.approx(160 / 540, abs=0.03) and y == pytest.approx(220 / 960, abs=0.03)


def test_a_steady_clip_has_no_payoff(tmp_path):
    p = tmp_path / "flat.mp4"
    ff("-f", "lavfi", "-i", "color=c=red:s=540x960:d=2:r=30", "-pix_fmt", "yuv420p", str(p))
    assert mf.payoff(p, 2.0) is None


def test_hit_prefers_a_result_word_then_the_longest_early_content_word():
    ws = [("edit", 3.98), ("was", 4.3), ("finished", 4.68), ("before", 5.1), ("pressed", 5.96), ("record?", 6.42)]
    assert mf.hit(ws, 3.85, 7.16) == 4.68                                   # "finished": a result word
    ws2 = [("edit", 3.98), ("was", 4.3), ("changing", 4.68), ("before", 5.1), ("tomorrow", 6.6)]
    assert mf.hit(ws2, 3.85, 7.16) == 4.68                                  # longest content word in the first 60 %
    assert mf.hit([("edit", 3.98)], 3.85, 7.16) is None
    assert mf.align(1.667, 4.68, 3.8467, 3.0) == pytest.approx(0.834, abs=1e-3)
    assert mf.align(0.2, 5.0, 3.0, 3.0) == 0.0 and mf.align(2.9, 3.1, 3.0, 3.0) == 1.8   # clamped in the clip


def test_offset_keeps_a_content_block_whole_over_a_stray_label():
    sal = np.zeros(192)
    sal[50:105] = 10.0          # the panel (550 px of a 1920 px clip)
    sal[122:126] = 60.0         # a bright label 170 px below it
    y = mf.offset(sal, 1920, 833, (0, 593), soft=120)
    top = (833 - 1920) * y / 100 + 500
    assert 0 <= top and top + 550 <= 593 + 10                                  # the panel stays whole above the band end
    assert mf.offset(np.ones(192), 1920, 1920) == 50.0                         # nothing overflows: centred


def test_held_clip_holds_the_last_frame_with_bt709_tags(tmp_path, event_clip):
    out = mf.held(event_clip, 1.0, 1.0, 0.8, tmp_path / "h.mp4")
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=color_space,color_primaries:"
                                    "format=duration", "-of", "json", str(out)], capture_output=True, text=True).stdout)
    assert pr["streams"][0]["color_space"] == "bt709" and float(pr["format"]["duration"]) == pytest.approx(1.8, abs=0.05)
    f = mf.frames(out)
    assert np.abs(f[-1] - f[int(1.05 * 30)]).mean() < 1.0                       # the tail is the last frame, held
    assert mf.held(event_clip, 1.0, 1.0, 0.8, tmp_path / "h.mp4") == out       # cached by name


# ---- split flow (council pass) -------------------------------------------------------------------------------
def _pass(media_until="pressed", pace="standard"):
    data = {"title": "Flow", "style": {"preset": "clean-pro", "pace": pace}, "shots": [
        {"id": "turn", "line": "What if the edit was finished before you even pressed record?", "cues": [
            {"type": "broll", "at": "edit", "until": media_until, "kind": "media", "layout": "split", "auto": True,
             "query": "editing timeline", "slot": "turn.3"}]},
        {"id": "cta", "line": "Read the script, hit record, and the reel builds itself.", "cues": [
            {"type": "broll", "at": "Read", "until": "reel", "kind": "list", "layout": "split", "auto": True,
             "items": ["READ THE SCRIPT", "HIT RECORD"]}]}]}
    s = parse_script(policy.prepare(data, "clean-pro"))
    takes = {}
    for sh in s.shots:
        w = [{"w": x.text, "s": round(0.5 + 0.38 * i, 3), "e": round(0.5 + 0.38 * i + 0.34, 3)} for i, x in enumerate(sh.words)]
        takes[sh.id] = [Take(Path(f"/tmp/{sh.id}.mp4"), w, w[-1]["e"] + 0.6)]
    return policy._Pass(s, build_timeline(s, takes), [])


def test_a_split_insert_close_to_the_next_split_card_runs_on_to_the_cut():
    P = _pass()
    broll_flow.split_flow(P)
    c = next(c for c in P.s.shots[0].cues if c.params.get("kind") == "media")
    cut = P.tl.shots[1].out_start
    assert c.params.get("bridge") and c.params.get("to_cut") and P.span(0, c)[1] == pytest.approx(cut, abs=1e-3)
    assert any("runs on to the next split" in n for n in P.notes)
    broll_flow.split_flow(P)                                                     # idempotent
    assert P.span(0, c)[1] == pytest.approx(cut, abs=1e-3)


def test_a_long_bridged_run_gets_a_beat_word_and_policy_counts_it():
    P = _pass(pace="punchy")                                                      # max static 3.0 s
    broll_flow.split_flow(P)
    c = next(c for c in P.s.shots[0].cues if c.params.get("kind") == "media")
    a, b = P.span(0, c)
    assert b - a > 3.0 and c.params.get("beat") is not None
    t = P.t(0, c.params["beat"])
    assert a + 1.0 <= t <= b - 0.6 and any(abs(x - t) < 1e-6 for x in P.changes())


def test_grow_runs_a_split_insert_to_the_contract_max_but_never_onto_the_payoff():
    P = _pass(media_until="was")
    c = next(c for c in P.s.shots[0].cues if c.params.get("kind") == "media")
    broll_flow.grow(P, 0, c, payoff_t=99.0)
    a, b = P.span(0, c)
    assert c.end_word > 4 and b - a <= 3.0 + 1e-6
    c.end_word = 4
    broll_flow.grow(P, 0, c, payoff_t=P.t(0, 6))
    assert P.span(0, c)[1] <= P.t(0, 6) + 1e-6


# ---- QA -------------------------------------------------------------------------------------------------------
def _b(cards=(), caps=(), items=(), D=10.0):
    return {"layout": {"captions": list(caps), "title": None, "cards": list(cards), "reframe": []},
            "style": {"pace": "standard"}, "plan": {"D": D, "fps": 30, "segs": [], "items": list(items)},
            "tl": {"duration": D, "shots": [{"id": "a", "start": 0.0, "duration": D}]}, "directed": {}, "videos": []}


def test_broll_face_counts_split_inserts_and_keeps_the_face_off_cap():
    b = _b(cards=[{"id": "broll-1", "kind": "broll", "t0": 2.0, "t1": 5.0, "layout": "split", "box": [0, 0, 1, 1]}])
    g = qa.gate_broll_face(b, [k * 0.5 for k in range(20)], [None] * 20)[0]
    assert g["value"]["broll_share"] == pytest.approx(0.3) and g["value"]["faceoff_share"] == 0.0
    assert "B-roll 30% of the reel (face-off 0%" in g["message"]


def test_media_share_wants_25_to_40_percent_of_real_media():
    item = lambda s, e: {"id": "x", "kind": "broll", "s": s, "e": e, "layout": "split", "media": {"t": "fullbleed"}}  # noqa: E731
    assert qa.gate_media_share(_b())["level"] == "ok"                                      # no real media: fine
    assert qa.gate_media_share(_b(items=[item(2.0, 3.2)]))["level"] == "warn"              # 12 %
    g = qa.gate_media_share(_b(items=[item(2.0, 5.0)]))
    assert g["level"] == "ok" and g["value"]["media_share"] == pytest.approx(0.3)


def test_media_text_fails_when_a_caption_touches_a_media_object():
    dev = {"id": "broll-9", "kind": "broll", "t0": 3.8, "t1": 6.3, "layout": "full", "box": [0, 0, 1080, 1920],
           "media": "device", "obj": [54, 300, 972, 648]}
    clear = {"chunk_id": "cap-2", "t0": 3.9, "t1": 4.3, "box": [172, 972, 696, 276], "text": "What if"}
    on = {**clear, "box": [172, 900, 696, 192]}
    assert qa.gate_media_text(_b(cards=[dev], caps=[clear]))["level"] == "ok"
    g = qa.gate_media_text(_b(cards=[dev], caps=[on]))
    assert g["level"] == "fail" and g["value"]["overlaps"][0]["text"] == "cap-2"
    fill = {**dev, "media": "fullbleed", "obj": None}                         # a picture under captions is by design
    assert qa.gate_media_text(_b(cards=[fill], caps=[on]))["level"] == "ok"
    late = {**on, "t0": 6.3, "t1": 7.0}
    assert qa.gate_media_text(_b(cards=[dev], caps=[late]))["level"] == "ok"   # not on screen together


def test_plan_changes_count_a_media_beat():
    b = _b(items=[{"id": "x", "kind": "broll", "s": 3.0, "e": 7.0, "layout": "split", "media": {"t": "fullbleed",
                                                                                                "beat": 1.5}}])
    assert (4.5, "broll-beat") in qa.plan_changes(b)


# ---- selection: share-alike opt-in, reused clips must fit the line -------------------------------------------
def _cand(cid, lic, title="Kdenlive timeline", provider="wikimedia", **extra):
    return Candidate(id=cid, provider=provider, kind="image", title=title, url=f"https://x/{cid}", w=1920, h=1080,
                     license=lic, extra=extra)


def test_share_alike_is_opt_in(monkeypatch):
    monkeypatch.delenv("RD_MEDIA_SHARE_ALIKE", raising=False)
    cands = [_cand("a", "cc-by-sa-4.0"), _cand("b", "cc0-1.0")]
    notes = []
    assert [s.cand.id for s in S.rank(cands, "kdenlive timeline", share_alike=False, notes=notes)] == ["b"]
    assert "share-alike opt-in" in notes[0]
    assert {s.cand.id for s in S.rank(cands, "kdenlive timeline")} == {"a", "b"}
    assert not L.share_alike_ok() and L.share_alike_ok({"media": {"allow_share_alike": True}})
    monkeypatch.setenv("RD_MEDIA_SHARE_ALIKE", "1")
    assert L.share_alike_ok()


def test_a_reused_clip_scores_its_context_against_the_line_and_needs_half_of_it():
    clip = _cand("claude_clip:k", "original", title="timeline auto-assembling with a checkmark", provider="claude_clip",
                 reused=True, context="edit finished before you hit record",
                 description="edit finished before you hit record")
    q = "video editing timeline on a laptop screen"
    assert S.relevance(clip, q) == pytest.approx(0.375, abs=1e-3)               # the panel's 0.375
    assert S.relevance(clip, q, "edit was finished before you even pressed") >= 0.5
    notes = []
    kept = S.rank([clip], q, notes=notes, context="edit was finished before you even pressed")
    assert [s.cand.id for s in kept] == ["claude_clip:k"]
    assert S.rank([clip], q, notes=notes, context="most creators waste hours") == [] and "reused clip" in notes[-1]


# ---- credits and the tint -------------------------------------------------------------------------------------
def test_credits_say_reused_and_a_still_is_not_trimmed():
    b = type("B", (), {})()
    b._media_src = {"turn.3": {"provider": "claude_clip", "title": "timeline", "path": "/x/a.mp4", "video": True,
                               "extra": {"reused": True}},
                    "cta.1": {"provider": "wikimedia", "path": "/x/b.png", "video": False, "license": "cc-by-4.0",
                              "attribution": '"K" by A, CC BY 4.0, modified (cropped, trimmed, graded)'}}
    out = treatments.credits_of(b)
    assert out[0].endswith("modified (cropped, graded)")
    assert out[1] == "timeline: AI-generated insert (Claude motion graphic), reused from the Reel Director clip gallery"
    assert L.attribution("T", "A", "", "cc-by-4.0", kind="image").endswith("modified (cropped, graded)")
    assert L.attribution("T", "A", "", "cc-by-4.0").endswith("modified (cropped, trimmed, graded)")


def test_accent_tint_keeps_black_and_pulls_white_toward_the_accent():
    svg = treatments._tint_svg("#FFD400", 0.45)
    vals = [float(x) for x in svg.split('values="')[1].split('"')[0].split()]
    m = np.array(vals).reshape(4, 5)[:3, :3]
    assert np.allclose(m @ [0, 0, 0], 0)                                       # blacks stay black
    white = m @ [1, 1, 1]
    assert white[2] == pytest.approx(0.55, abs=1e-3) and white[0] >= 0.99 and white[1] > white[2]   # warm, yellow


def test_new_files_stay_under_500_lines():
    src = ROOT / "src" / "reel_director"
    for f in ("media_fit.py", "broll_flow.py", "qa_media.py", "qa.py", "treatments.py", "media/select.py",
              "media/vision.py", "media/license.py", "broll_media.py", "policy.py", "pace.py", "web/broll.mjs"):
        assert len((src / f).read_text().splitlines()) < 500, f
    assert qa_media.MEDIA_SHARE == (0.25, 0.40)
