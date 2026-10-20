import re

import pytest

from reel_director.cleanup import MAX_PAUSE, keep_segments, score_take
from reel_director.compiler import compile_project
from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline
from reel_director.timing import align

LINE = "Most creators waste three hours editing one reel."


def shot(line=LINE):
    return parse_script({"shots": [{"id": "hook", "line": line}]}).shots[0]


def read(*pairs):
    return [{"w": w, "s": s, "e": e} for w, s, e in pairs]


CLEAN = read(("most", 0.5, 0.8), ("creators", 0.8, 1.3), ("waste", 1.3, 1.7), ("three", 1.7, 2.0),
             ("hours", 2.0, 2.4), ("editing", 2.4, 2.9), ("one", 2.9, 3.1), ("reel", 3.1, 3.5))


def test_clean_read_is_one_segment():
    al = align(shot(), CLEAN)
    segs = keep_segments(al, CLEAN, 4.5)
    assert len(segs) == 1
    assert segs[0].media_in == pytest.approx(0.35) and segs[0].media_out == pytest.approx(3.85)


def test_filler_is_cut_even_in_a_short_gap():
    asr = read(("most", 0.5, 0.8), ("creators", 0.8, 1.3), ("waste", 1.3, 1.7), ("um", 1.75, 2.0),
               ("three", 2.05, 2.35), ("hours", 2.35, 2.7), ("editing", 2.7, 3.2), ("one", 3.2, 3.4),
               ("reel", 3.4, 3.8))
    segs = keep_segments(align(shot(), asr), asr, 4.5)
    assert len(segs) == 2
    # padding stops at the filler itself: cut exactly from "um" onset to its end
    assert segs[0].media_out == pytest.approx(1.75) and segs[1].media_in == pytest.approx(2.0)


def test_long_pause_is_shortened_but_natural_pause_kept():
    asr = [dict(w) for w in CLEAN]
    for w in asr[5:]:                      # 1.2 s silence before "editing"
        w["s"] += 1.2
        w["e"] += 1.2
    asr[2]["e"] = 1.7 - (MAX_PAUSE - 0.1)  # small gap after "waste": under MAX_PAUSE, kept
    segs = keep_segments(align(shot(), asr), asr, 6.0)
    assert len(segs) == 2                                  # only the long pause is cut
    assert segs[0].media_out == pytest.approx(2.4 + 0.12)  # tail of "hours"
    assert segs[1].media_in == pytest.approx(3.6 - 0.08)   # onset of "editing"


def test_misread_take_loses_to_clean_take_with_filler():
    misread = [dict(w) for w in CLEAN]
    misread[4]["w"] = "days"
    filler = read(("um", 0.2, 0.4), *[(w["w"], w["s"], w["e"]) for w in CLEAN])
    s = shot()
    scores = []
    for asr in (misread, filler):
        al = align(s, asr)
        scores.append(score_take(al, asr, keep_segments(al, asr, 4.5)))
    assert scores[0].misread == 1 and scores[1].junk_words == 1
    assert scores[1].score > scores[0].score


def test_timeline_picks_best_take_and_maps_words_across_cuts(tmp_path):
    s = parse_script({"shots": [{"id": "hook", "line": LINE,
                                 "cues": [{"type": "overlay", "at": "editing", "text": "x"}]}]})
    bad = [dict(w) for w in CLEAN]
    bad[4]["w"] = "days"
    paused = [dict(w) for w in CLEAN]
    for w in paused[5:]:
        w["s"] += 2.0
        w["e"] += 2.0
    src = tmp_path / "t.mp4"
    src.write_bytes(b"")
    tl = build_timeline(s, {"hook": [Take(src, bad, 4.5), Take(src, paused, 6.5)]})
    p = tl.shots[0]
    assert p.take_index == 1 and len(p.clips) == 2
    c0, c1 = p.clips
    assert c1.out_start == pytest.approx(c0.out_start + c0.duration)
    editing = p.words[5]                   # said at 4.4 s in the take, after the cut
    assert editing.start == pytest.approx(c1.out_start + (4.4 - c1.media_in))
    assert tl.duration == pytest.approx(c0.duration + c1.duration)

    html = compile_project(tl, tmp_path / "out").read_text()
    assert len(re.findall(r'<video id="take-hook-\d"', html)) == 2
    overlay_start = float(re.search(r'class="clip overlay" data-start="([\d.]+)"', html).group(1))
    assert overlay_start == pytest.approx(editing.start)


def test_snap_to_speech_trims_words_stretched_over_silence():
    from reel_director.cleanup import snap_to_speech
    words = read(("most", 0.0, 1.16), ("and", 3.0, 4.2), ("reel", 4.3, 4.6))
    speech = [(0.70, 3.2), (4.05, 4.7)]
    snapped = snap_to_speech(words, speech)
    assert (snapped[0]["s"], snapped[0]["e"]) == (0.7, 1.16)   # leading silence dropped
    assert (snapped[1]["s"], snapped[1]["e"]) == (3.0, 3.2)    # trailing pause exposed
    assert (snapped[2]["s"], snapped[2]["e"]) == (4.3, 4.6)    # already in speech


def test_snap_moves_word_said_after_a_pause_to_the_later_region():
    from reel_director.cleanup import snap_to_speech
    words = read(("record", 2.2, 2.64), ("and", 2.64, 3.98))
    snapped = snap_to_speech(words, [(2.0, 2.8), (3.7, 5.6)])
    assert (snapped[1]["s"], snapped[1]["e"]) == (3.7, 3.98)


def test_padding_never_reaches_into_a_restart():
    asr = read(("most", 0.5, 0.8), ("creators", 0.8, 1.3), ("waste", 1.3, 1.62),
               ("most", 1.62, 1.9), ("creators", 1.9, 2.3), ("waste", 2.3, 2.7), ("three", 2.7, 3.0),
               ("hours", 3.0, 3.4), ("editing", 3.4, 3.9), ("one", 3.9, 4.1), ("reel", 4.1, 4.5))
    segs = keep_segments(align(shot(), asr), asr, 5.5)
    assert segs[0].media_in == pytest.approx(1.62)   # not 1.47: that is the false start's tail
