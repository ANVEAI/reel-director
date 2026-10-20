"""Caption craft (reel-knowledge captions-visual rules 2.1, council 6): chunks never end on an article,
preposition, conjunction or possessive; they break after punctuation, keep a number with its unit, stay
2-4 words (1-2, at most 3, for the hype family) and two short lines, and hold max(0.5, 0.35 + 0.28 x words)
where timing allows (merge rather than flash). The runtime never shrinks a caption below 64 px."""
import json
import re

import pytest

from reel_director import compiler, stage, stagger
from reel_director.compiler import CAPTION_FAMILIES, caption_chunks, compile_project
from reel_director.schema import parse_script
from reel_director.timeline import Take, build_timeline


def asr(line, t0=0.2, step=0.3):
    out, t = [], t0
    for w in line.split():
        out.append({"w": w, "s": round(t, 3), "e": round(t + step - 0.02, 3)})
        t += step
    return out


def texts(words, chunks):
    return [" ".join(words[i]["w"] for i in c) for c in chunks]


LINES = ["Follow for the next breakdown.",
         "Read the script, hit record, and the reel builds itself.",
         "What if the edit was finished before you even pressed record?",
         "So stop editing for hours and start writing better first lines.",
         "My best reel had a three second hook, and it got two million views in a week.",
         "Here's the exact system, step by step, so you can copy it."]


@pytest.mark.parametrize("family", sorted(CAPTION_FAMILIES))
@pytest.mark.parametrize("line", LINES)
def test_no_chunk_ends_on_a_dangling_word_and_sizes_hold(family, line):
    max_w, max_c = CAPTION_FAMILIES[family]
    words = asr(line)
    chunks = caption_chunks(words, max_w, max_c)
    assert [i for c in chunks for i in c] == list(range(len(words)))          # every word, once, in order
    for c, t in zip(chunks, texts(words, chunks)):
        assert not stagger.dangles(words[c[-1]]["w"]), (family, t)
        assert len(c) <= min(4, max_w + 1) and len(t) <= max_c + 6, (family, t)
        assert all(words[i]["w"][-1] not in ".!?" for i in c[:-1]), (family, t)   # never across a sentence end


def test_follow_for_the_is_gone():
    words = asr("Follow for the next breakdown.")
    for family, (max_w, max_c) in CAPTION_FAMILIES.items():
        got = texts(words, caption_chunks(words, max_w, max_c))
        assert "Follow for the" not in got and "Follow for" not in got, (family, got)
    assert texts(words, caption_chunks(words, 3, 16)) in (["Follow for the next", "breakdown."],
                                                          ["Follow", "for the next breakdown."],
                                                          ["Follow", "for the next", "breakdown."])


def test_breaks_after_punctuation_and_keeps_number_with_unit():
    words = asr("Read the script, hit record, and the reel builds itself.")
    assert texts(words, caption_chunks(words, 3, 18))[:2] == ["Read the script,", "hit record,"]
    words = asr("Most creators waste 3 hours editing one reel.")
    for max_w, max_c in CAPTION_FAMILIES.values():
        got = texts(words, caption_chunks(words, max_w, max_c))
        assert any("3 hours" in t for t in got), got


def test_spoken_number_unit_never_splits_and_short_single_merges():
    words = [{"w": w, "s": s, "e": e} for w, s, e in [("We", 0.15, 0.4), ("hit", 0.4, 0.65), ("three", 0.9, 1.6),
                                                       ("thousand", 0.9, 1.6), ("views", 1.6, 2.0), ("today.", 2.0, 2.5)]]
    assert any(2 in c and 3 in c for c in caption_chunks(words, 3, 18))
    # greedy 3 + 1 would flash 'manually.' alone; 2 + 2 holds better (merge rather than flash)
    words = asr("Stop editing reels manually.", step=0.25)
    assert texts(words, caption_chunks(words, 3, 18)) == ["Stop editing", "reels manually."]
    assert stagger.hold_need(1) == 0.63 or abs(stagger.hold_need(1) - 0.63) < 1e-9
    assert stagger.hold_need(0) == 0.5 and abs(stagger.hold_need(4) - 1.47) < 1e-9


def test_hype_family_stays_short_and_lead_in_may_run_on():
    words = asr("First, write the script before you ever touch the camera.")
    got = texts(words, caption_chunks(words, 2, 14))
    assert all(len(t.split()) <= 3 for t in got) and not any(t.endswith(" the") for t in got), got
    assert caption_chunks(words, 2, 14) == caption_chunks(words, 2, 14)       # deterministic


def test_dangling_word_list():
    assert all(stagger.dangles(w) for w in ("the", "A", "of", "to", "for", "and", "but", "or", "my", "your", "with"))
    assert not any(stagger.dangles(w) for w in ("the,", "for.", "reel", "Follow", "breakdown.", ""))


@pytest.mark.skipif(not (stage.pack_root() / "transitions" / "aliases.json").exists(), reason="motion-pack not installed")
def test_compiled_captions_follow_the_craft_rules(tmp_path):
    lines = {"a": "Follow for the next breakdown.", "b": "Read the script, hit record, and the reel builds itself."}
    s = parse_script({"shots": [{"id": k, "line": v} for k, v in lines.items()]}, base_dir=tmp_path)
    takes = {}
    for sid, line in lines.items():
        (tmp_path / f"{sid}.mp4").write_bytes(b"")
        w = asr(line, t0=1.0)
        takes[sid] = [Take(tmp_path / f"{sid}.mp4", w, w[-1]["e"] + 2.0)]
    tl = build_timeline(s, takes)
    orig = compiler.probe_size
    compiler.probe_size = lambda path: (1080, 1920)
    try:
        html = compile_project(tl, tmp_path / "out").read_text()
    finally:
        compiler.probe_size = orig
    plan = json.loads(re.search(r'id="rd-plan">(.*?)</script>', html, re.S).group(1))
    chunks = {c["id"]: c for c in plan["caps"]}
    for cid, inner in re.findall(r'<div id="(cap-\d+)-in" class="cap-in fit">(.*?)</div>', html):
        words = re.findall(r'<span id="[^"]+" class="word[^"]*">([^<]*)</span>', inner)
        assert words and not stagger.dangles(words[-1]), words
        c = chunks[cid]
        if words[-1].endswith("."):                    # a shot's last chunk holds its readable minimum
            assert c["e"] - c["s"] >= stagger.hold_need(len(words)) - 1e-3, (words, c)
    rt = (stage.WEB / "reel.mjs").read_text()
    assert "'cap-in': 64" in rt and "MAX_LINES = { 'cap-in': 2 }" in rt
