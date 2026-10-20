"""Final-fixer round on the real-1 review (CD / HQ / founder, 20 Oct): one text block at a time, cards that own their
words, the CTA flash, dead air at seams, the payoff beat, punches that never read as wobble, the head-clearance gate
and the enforced pace gate."""
import json
import subprocess

import numpy as np
import pytest

from reel_director import capplan, cleanup, compiler, policy, qa, qa_face, stage, stagger
from reel_director.compiler import compile_project
from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline
from test_layout import A, B, asr, build, face_doc

pytestmark = pytest.mark.skipif(not (stage.pack_root() / "transitions" / "aliases.json").exists(),
                                reason="motion-pack not installed")


def test_no_caption_under_the_hook_title_and_the_title_ends_on_a_word(tmp_path):
    tl, _, plan, lay = build(tmp_path, cues_a=[{"type": "title", "at": "Most", "until": "hours", "text": "3 HOURS PER REEL?"}])
    t0, t1 = lay["title"]["t0"], lay["title"]["t1"]
    starts = [round(w.start, 4) for p in tl.shots for w in p.words]
    # 'reel.' at 2.25 s would leave a one-word sentence tail and no other word starts within 0.3 s: the title holds 2.5 s
    assert t0 == 0.0 and t1 == pytest.approx(2.5)
    assert all(c["t0"] >= t1 - 1e-6 for c in lay["captions"])                        # one text block at a time
    first = min(lay["captions"], key=lambda c: c["t0"])
    assert t1 - 1e-6 <= first["t0"] <= min(x for x in starts if x >= t1)            # resumes on the title's out
    from reel_director.layout import title_window
    from types import SimpleNamespace as N
    ws = [N(text=t, start=s, end=s + 0.28) for t, s in (("Most", 0.15), ("waste", 1.8), ("one", 2.23), ("reel.", 2.53))]
    tl2 = N(shots=[N(shot=N(words=ws), words=ws)])
    assert title_window(tl2, 0, N(params={}), 9.0) == (0.0, 2.23)                    # snapped onto 'one', not 'reel.'


def test_full_card_owns_its_words_and_chunks_never_straddle_its_edges(tmp_path):
    _, html, plan, lay = build(tmp_path, cues_b=[{"type": "broll", "at": "edit was finished", "kind": "text", "text": "DONE"}])
    card = next(c for c in lay["cards"] if c["kind"] == "broll")
    assert card["layout"] == "full"
    assert not [c for c in lay["captions"] if c["t0"] < card["t1"] - 1e-6 and card["t0"] < c["t1"] - 1e-6]
    assert all(c["zone"] != "card" for c in lay["captions"])
    assert 'class="clip card broll full b-text solo"' in html                           # the bigger, caption-free headline


def test_split_checklist_hides_its_item_words_and_ticks_on_them(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "probe_size", lambda path: (1080, 1920))
    data = {"title": "t", "shots": [{"id": "a", "line": A}, {"id": "b", "line": "Read the script, hit record, and the reel builds itself.",
                                     "cues": [{"type": "broll", "at": "Read", "until": "reel", "kind": "list",
                                               "items": ["READ THE SCRIPT", "HIT RECORD"], "layout": "split"}]}]}
    s = parse_script(data, base_dir=tmp_path)
    (tmp_path / "prepped").mkdir()
    takes = {}
    for sh in s.shots:
        src = tmp_path / "prepped" / f"{sh.id}.mp4"
        src.write_bytes(b"")
        w = asr(sh.line)
        takes[sh.id] = [Take(src, w, round(w[-1]["e"] + 1.0, 3))]
        (tmp_path / "prepped" / f"{sh.id}.face.json").write_text(json.dumps(face_doc(sh.id, takes[sh.id][0].duration)))
    tl = build_timeline(s, takes)
    html = compile_project(tl, tmp_path / "out").read_text()
    lay = json.loads((tmp_path / "out" / "layout.json").read_text())
    card = next(c for c in lay["cards"] if c["layout"] == "split")
    p, cue = tl.shots[1], s.shots[1].cues[0]
    assert capplan.item_words(p, cue, ["READ THE SCRIPT", "HIT RECORD"]) == {0, 1, 2, 3, 4}
    over = [c for c in lay["captions"] if c["t0"] < card["t1"] - 1e-6 and card["t0"] < c["t1"] - 1e-6]
    assert over and all(c["zone"] == "card" and "script" not in c["text"].lower() for c in over)   # 'and the reel' only
    at = capplan.list_ticks(p, cue, ["READ THE SCRIPT", "HIT RECORD"])
    assert at == [round(p.words[0].start, 4), round(p.words[3].start, 4)] and '&quot;at&quot;: [' in html
    assert card["dy"] > 0 and 720 <= card["split_h"] <= 1056 and "--split-h:" in html


def test_a_card_within_6_frames_of_its_cut_starts_on_the_cut():
    assert stagger.card_in(7.5, 7.65, 30, 4) == 7.5                  # 7.5167 would flash the take for one frame
    assert stagger.card_in(7.5, 8.0, 30, 4) == pytest.approx(8.0 - 4 / 30)
    assert stagger.card_in(7.5, 7.52, 30, 4) == 7.5


def test_seams_trim_dead_air_to_the_voice(tmp_path):
    take = tmp_path / "t.mp4"           # 1.0 s silence, 1.0 s tone (the read), 1.5 s silence
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=1:sample_rate=48000", "-af",
                    "adelay=1000,apad=pad_dur=1.5", "-t", "3.5", "-c:a", "aac", str(take)], check=True)
    seg = cleanup.Segment(0.85, 2.35)                        # PRE_ROLL 0.15 / POST_ROLL 0.35 around the read
    out = cleanup.seam(take, seg, 1.0, 2.0, True, True)
    assert 0.9 <= out.media_in <= 0.97 and 2.03 <= out.media_out <= 2.12
    assert cleanup.seam(tmp_path / "none.mp4", seg, 1.0, 2.0, True, True) == seg          # no audio: unchanged


def test_payoff_punch_lands_on_the_last_phrase_and_ends_on_frame_0_level():
    data = {"title": "t", "shots": [{"id": "hook", "line": A}, {"id": "cta", "line": "Read the script, hit record, and the reel builds itself."}]}
    s = parse_script(policy.prepare(data), base_dir=None)
    tl = build_timeline(s)
    from reel_director import pipeline
    d = pipeline.direct(s, {}, notes=[])
    tl = build_timeline(d)
    cta = d.shots[-1]
    pay = [c for c in cta.cues if c.type == "punch" and c.params.get("payoff")]
    assert pay and cta.words[pay[0].start_word].text == "builds" and pay[0].params["level"] == "M"
    emph = [c for c in cta.cues if c.type == "emphasis"]
    assert [cta.words[c.start_word].text for c in emph] == ["itself."]
    P = policy._Pass(d, tl, [])
    last = max((P.pt(si, c), c.params["level"]) for si, sh in enumerate(d.shots) for c in sh.cues if c.type == "punch")
    assert last[1] == "M"


def test_punches_never_read_as_wobble():
    b = compiler._Builder.__new__(compiler._Builder)
    from types import SimpleNamespace
    b.s = SimpleNamespace(title="Reel Director demo")
    got = {b.punch_scale(1.17, 1.10, f) for f in range(0, 300, 3)}
    assert min(got) >= compiler.PUNCH_MIN_CAP and max(got) <= 1.10 and len(got) > 10
    assert b.punch_scale(1.17, 1.07, 30) == 1.0                    # a punch under 8 % is no punch


def test_head_gate_fails_text_on_the_hair_and_passes_clear_text(monkeypatch):
    import reel_director.matte as matte
    monkeypatch.setattr(matte, "get_segmenter", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no vision")))
    face = {"box": [340, 860, 400, 400], "eyes": [[460, 990], [620, 990]], "mouth": [540, 1150], "chin_y": 1260}
    frames = np.zeros((2, 960, 540, 3), np.uint8)
    on_hair = lambda t: [{"id": "cap-1", "kind": "caption", "box": [172, 584, 696, 192], "text": "x"}]   # noqa: E731
    clear = lambda t: [{"id": "cap-1", "kind": "caption", "box": [172, 440, 696, 192], "text": "x"}]     # noqa: E731
    g = qa_face.head_gate([0.0, 0.2], frames, [face, face], on_hair, lambda t: False)
    assert g["level"] == "fail" and g["value"]["head_top_from"] == "estimate" and g["fix"]["op"] == "move_caption"
    assert qa_face.head_gate([0.0, 0.2], frames, [face, face], clear, lambda t: False)["level"] == "ok"   # 668 px top


def test_qa_pace_median_out_of_range_fails():
    plan = {"D": 8.0, "fps": 30, "items": [], "segs": [{"layer": "L-a-0", "punches": [[0, 1.09], [24, 1.0], [48, 1.09],
                                                                                     [72, 1.0], [96, 1.09], [120, 1.0]]}]}
    words = [{"w": w, "s": s, "e": s + 0.3} for w, s in (("one", 0.8), ("two", 1.6), ("three", 2.4))]
    b = {"plan": plan, "layout": {"cards": []}, "videos": [{"id": "take-a-0", "start": 0.0, "duration": 8.0}],
         "style": {"pace": "standard"}, "tl": {"shots": [{"id": "a", "start": 0, "duration": 8.0, "clips": [], "words": words}]},
         "directed": {"shots": [{"id": "a", "cues": []}]}}
    g = qa.gate_pace(b)
    assert g["level"] == "fail" and "median gap" in g["message"]
