import re

import pytest

from reel_director.compiler import compile_project
from reel_director.schema import ScriptError, find_phrase, parse_script, split_words
from reel_director.textnorm import norm_tokens
from reel_director.timeline import Take, build_timeline
from reel_director.timing import align

LINE = "Most creators waste 3 hours editing one reel. Here is how to fix it."


def script(cues=None, **extra):
    return parse_script({"shots": [{"id": "hook", "line": LINE, "cues": cues or []}], **extra})


def words(*pairs):
    """('most', 0.0, 0.3), ... -> asr word dicts"""
    return [{"w": w, "s": s, "e": e} for w, s, e in pairs]


def test_norm_expands_numbers_and_percent():
    assert norm_tokens("3,000%") == ["three", "thousand", "percent"]
    assert norm_tokens("Reel's!") == ["reel's"]
    assert norm_tokens("—") == []


def test_homophones_are_never_a_misread():
    assert norm_tokens("one real") == norm_tokens("one reel") and norm_tokens("4") == norm_tokens("for")
    assert norm_tokens("their") == norm_tokens("They're") and norm_tokens("days") != norm_tokens("hours")
    shot = parse_script({"shots": [{"id": "a", "line": "Editing one reel takes hours."}]}).shots[0]
    al = align(shot, [{"w": w, "s": i, "e": i + 0.5} for i, w in enumerate("Editing one real takes ours.".split())])
    assert al.coverage == 1.0 and al.misread == 0


def test_find_phrase_matches_spoken_form_and_occurrence():
    ws = split_words("one reel, then one reel more")
    assert find_phrase(ws, "one reel") == (0, 1)
    assert find_phrase(ws, "one reel#2") == (3, 4)
    assert find_phrase(split_words(LINE), "three hours") == (3, 4)   # "3" in the line


def test_bad_anchor_fails_before_recording():
    with pytest.raises(ScriptError, match="cue 0.*not found"):
        script([{"type": "overlay", "at": "four hours", "text": "x"}])
    with pytest.raises(ScriptError, match="needs 'text'"):
        script([{"type": "overlay", "at": "reel"}])
    with pytest.raises(ScriptError, match="before"):
        script([{"type": "cutaway", "at": "reel", "until": "waste", "text": "x"}])


def test_align_skips_filler_and_takes_last_restart():
    shot = script().shots[0]
    asr = words(("Most", 0.0, 0.3), ("creators", 0.3, 0.8), ("waste", 0.8, 1.2), ("three", 1.2, 1.5),
                ("hours", 1.5, 1.9), ("editing", 1.9, 2.4), ("one", 2.4, 2.6), ("reel.", 2.6, 3.0),
                ("Um,", 3.2, 3.5), ("here", 3.8, 4.0), ("is.", 4.0, 4.2),
                ("Here", 4.5, 4.7), ("is", 4.7, 4.9), ("how", 4.9, 5.1), ("to", 5.1, 5.2),
                ("fix", 5.2, 5.5), ("it.", 5.5, 5.8))
    al = align(shot, asr)
    assert al.coverage == 1.0
    assert al.times[8].start == 4.5   # "Here" is the keeper read, not the false start


def test_align_interpolates_missed_words():
    shot = parse_script({"shots": [{"line": "alpha beta gamma delta"}]}).shots[0]
    al = align(shot, words(("alpha", 0.0, 0.5), ("delta", 2.0, 2.5)))
    assert al.matched == 2
    assert 0.5 <= al.times[1].start < al.times[2].start <= 2.0


def test_timeline_retimes_cues_to_the_take(tmp_path):
    s = script([{"type": "overlay", "at": "three hours", "text": "3 HRS"}])
    preview = build_timeline(s)
    slow = [("most", 1.0, 1.4), ("creators", 1.4, 2.0), ("waste", 2.0, 2.6), ("three", 2.6, 3.0),
            ("hours", 3.0, 3.5), ("editing", 3.5, 4.1), ("one", 4.1, 4.3), ("reel", 4.3, 4.8),
            ("here", 5.2, 5.4), ("is", 5.4, 5.6), ("how", 5.6, 5.8), ("to", 5.8, 5.9),
            ("fix", 5.9, 6.2), ("it", 6.2, 6.5)]
    take = Take(tmp_path / "hook.mp4", words(*slow), duration=7.5)
    (tmp_path / "hook.mp4").write_bytes(b"")
    final = build_timeline(s, {"hook": [take]})

    p = final.shots[0]
    assert len(p.clips) == 1 and p.clips[0].media_in == pytest.approx(0.85)   # 1.0 - pre-roll
    assert p.words[3].start == pytest.approx(2.6 - 0.85)      # "3" lands where it was said
    assert final.duration != preview.duration

    html = compile_project(final, tmp_path / "out").read_text()
    m = re.search(r'class="clip overlay" data-start="([\d.]+)"', html)
    assert float(m.group(1)) == pytest.approx(1.75)
    root_dur = float(re.search(r'data-composition-id="main"[^>]*?data-duration="([\d.]+)"', html, re.S).group(1))
    assert root_dur == pytest.approx(final.duration)
    assert 'data-media-start="0.85"' in html
    assert (tmp_path / "out" / "assets" / "hook.mp4").exists()


def test_preview_has_slots_and_valid_structure(tmp_path):
    s = script([{"type": "zoom", "at": "reel"}, {"type": "emphasis", "at": "waste"}])
    html = compile_project(build_timeline(s), tmp_path).read_text()
    assert 'id="slot-hook"' in html and "<video" not in html
    assert 'window.__timelines["main"] = tl;' in html
    assert html.count('class="word emph"') == 1
    assert "immediateRender: false" in html
