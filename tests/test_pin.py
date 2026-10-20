import json

import pytest

from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline, pick_take

LINE = "Most creators waste three hours editing one reel."
CLEAN = [{"w": w, "s": s, "e": e} for w, s, e in (
    ("most", 0.5, 0.8), ("creators", 0.8, 1.3), ("waste", 1.3, 1.7), ("three", 1.7, 2.0),
    ("hours", 2.0, 2.4), ("editing", 2.4, 2.9), ("one", 2.9, 3.1), ("reel", 3.1, 3.5))]


def shot():
    return parse_script({"shots": [{"id": "hook", "line": LINE}]}).shots[0]


def misread():
    words = [dict(w) for w in CLEAN]
    words[4]["w"] = "days"
    return words


def test_pinned_take_beats_a_better_score_but_all_are_scored(tmp_path):
    takes = [Take(tmp_path / "a.mp4", CLEAN, 4.5), Take(tmp_path / "b.mp4", misread(), 4.5, pin=True)]
    (idx, al, segs, sc), scored = pick_take(shot(), takes)
    assert idx == 1 and al.misread == 1 and sc is scored[1]
    assert len(scored) == 2 and scored[0].score > scored[1].score


def test_without_a_pin_best_score_wins_and_ties_go_to_the_later_take(tmp_path):
    (idx, *_), _ = pick_take(shot(), [Take(tmp_path / "a.mp4", CLEAN, 4.5), Take(tmp_path / "b.mp4", misread(), 4.5)])
    assert idx == 0
    (idx, *_), _ = pick_take(shot(), [Take(tmp_path / "a.mp4", CLEAN, 4.5), Take(tmp_path / "b.mp4", CLEAN, 4.5)])
    assert idx == 1
    assert pick_take(shot(), []) == (None, [])


def test_timeline_uses_the_pinned_take(tmp_path):
    s = parse_script({"shots": [{"id": "hook", "line": LINE}]})
    pinned = Take(tmp_path / "b.mp4", misread(), 4.5, pin=True)
    tl = build_timeline(s, {"hook": [Take(tmp_path / "a.mp4", CLEAN, 4.5), pinned]})
    assert tl.shots[0].take is pinned and tl.shots[0].take_index == 1
    assert len(tl.shots[0].scores) == 2


def test_load_takes_carries_pin(tmp_path, monkeypatch):
    import reel_director.__main__ as cli
    monkeypatch.setattr(cli, "media_duration", lambda p: 4.5)
    (tmp_path / "w.json").write_text(json.dumps(CLEAN))
    (tmp_path / "takes.json").write_text(json.dumps({"hook": [
        {"src": "a.mp4", "words": "w.json"}, {"src": "b.mp4", "words": "w.json", "pin": True}]}))
    takes = cli.load_takes(tmp_path / "takes.json")["hook"]
    assert [t.pin for t in takes] == [False, True]


def test_prep_carries_pin_into_prepped_takes(tmp_path, monkeypatch):
    import reel_director.__main__ as cli
    import reel_director.audio as audio

    def fake_clean(src, dst, denoise=True):
        dst.write_bytes(src.read_bytes())
        return {"before_lufs": -20.0, "after_lufs": -16.0}
    monkeypatch.setattr(audio, "clean_take", fake_clean)
    monkeypatch.setattr(audio, "speech_spans", lambda p: [(0.0, 10.0)])
    monkeypatch.setattr(cli, "transcribe", lambda p, model=None: CLEAN)
    for n in ("a", "b"):
        (tmp_path / f"{n}.mp4").write_bytes(b"x")
    (tmp_path / "takes.json").write_text(json.dumps({"hook": [{"src": "a.mp4"}, {"src": "b.mp4", "pin": True}]}))
    out = tmp_path / "prepped"
    assert cli.main(["prep", str(tmp_path / "takes.json"), "--out", str(out)]) == 0
    prepped = json.loads((out / "takes.json").read_text())["hook"]
    assert [t["pin"] for t in prepped] == [False, True]
    assert prepped[1] == {"src": "hook-2.mp4", "words": "hook-2.words.json", "pin": True}


@pytest.mark.parametrize("pins", [[True, True], [False, False]])
def test_multiple_or_no_pins_are_deterministic(tmp_path, pins):
    takes = [Take(tmp_path / f"{k}.mp4", CLEAN, 4.5, pin=p) for k, p in enumerate(pins)]
    (idx, *_), _ = pick_take(shot(), takes)
    assert idx == 1   # last pinned, or the later of two equal scores
