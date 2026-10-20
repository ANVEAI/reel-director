"""Sign-off must-fixes (20 Oct, final fixer): hook title, highlights, B-roll timing/label, pace formula,
punch variety under the cap, resolution guard, sound anchors, bed spectrum/ending and non-loop beds."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from reel_director import compiler, lexicon as lx, mixdown, pace, pipeline, policy, stagger
from reel_director.schema import parse_script
from reel_director.timeline import build_timeline

ROOT = Path(__file__).resolve().parents[1]
LINES = ROOT / "examples" / "demo" / "script-lines-only.json"
HOOK = "Most creators waste three hours editing one reel.".split()


def directed(preset="clean-pro", data=None):
    raw = data or json.loads(LINES.read_text())
    s = parse_script(policy.prepare(raw, preset))
    notes: list[str] = []
    d = pipeline.direct(s, None, notes=notes)
    return d, build_timeline(d), notes


def test_hook_title_is_a_number_first_paraphrase_not_the_spoken_line():
    assert lx.hook_paraphrase(HOOK) == "3 HOURS PER REEL?"
    assert lx.hook_paraphrase("I made $40,000 from one reel and nobody believed me.".split()) == "$40,000 FROM 1 REEL?"
    assert lx.hook_paraphrase("Nothing numeric here at all.".split()) is None
    for preset in ("clean-pro", "bold-hustle"):
        d, _, _ = directed(preset)
        (title,) = [c for c in d.shots[0].cues if c.type == "title"]
        assert title.params["text"] == "3 HOURS PER REEL?"            # the council pass keeps the paraphrase
        assert 4 <= len(title.params["text"].split()) <= 6


def test_one_highlight_per_chunk_the_number_word_shown_as_digits():
    assert lx.display_words(HOOK)[3] == "3" and lx.display_words(HOOK)[6] == "one"   # 'one reel' is not a number
    assert lx.display_words("is ninety percent of it".split())[1] == "90"
    assert lx.display_words("two million views".split()) == ["two", "million", "views"]   # multi-word: as written
    for preset in ("clean-pro", "bold-hustle", "desi-bilingual"):
        d, _, _ = directed(preset)
        for sh in d.shots:
            for c in sh.cues:
                if c.type == "emphasis":
                    assert c.start_word == c.end_word, (preset, sh.id)
    css = (ROOT / "src" / "reel_director" / "web" / "reel.css").read_text()
    assert ".cap-bold .word.on, .cap-pop .word.on { color: var(--accent); }" in css          # active: colour only
    assert ".cap-bold .word.emph, .cap-pop .word.emph, .cap-karaoke .word.emph { background: var(--accent)" in css


def test_text_broll_label_names_the_idea_without_the_spoken_words():
    turn = "What if the edit was finished before you even pressed record?".split()
    assert lx.broll_label(turn, 3, 3, 7) == "EDIT: DONE"
    assert lx.broll_label("cut every pause longer than half".split(), 1, 3) == "PAUSE"


def test_caption_chunks_join_single_words_and_stagger_off_graphic_entrances():
    texts = ["Read", "the", "script,", "hit", "record,"]
    assert stagger.merge_singles([[0, 1], [2], [3, 4]], texts) == [[0, 1, 2], [3, 4]]
    assert stagger.merge_singles([[0], [1, 2]], ["So", "here", "we"]) == [[0, 1, 2]]
    assert stagger.merge_singles([[0, 1], [2]], ["It", "ends.", "Next"]) == [[0, 1], [2]]   # never across a sentence end
    f = 1 / 30
    # title at frame 0, first chunk at frame 4.5 -> frame 6; a card 4 frames before a chunk -> chunk 6 frames after it
    assert stagger.stagger([0.15], [1.0], [0.0], 30) == [0.2]
    assert abs(stagger.stagger([2.0, 5.12], [4.0, 6.0], [5.12 - 4 * f], 30)[1] - (5.12 + 2 * f)) < 1e-6
    # a chunk entering 2 frames BEFORE a card moves earlier rather than later
    assert abs(stagger.stagger([1.0, 3.0], [2.0, 4.0], [3.0 + 2 * f], 30)[1] - (3.0 - 4 * f)) < 1e-6


def test_pace_rhythm_is_measured_between_changes_not_from_frame_0():
    ch = [0.57, 2.59, 4.14, 6.14, 8.0, 10.0]
    with_lead = [b - a for a, b in zip([0.0] + ch, ch)]
    assert pace.pace_cv(ch) < np.std(with_lead) / np.mean(with_lead)      # the lead-in no longer inflates CV
    assert "metronomic" in pace.pace_note([1.0, 3.0, 5.0, 7.0, 9.0])
    d, tl, notes = directed("clean-pro")
    m = policy.metrics(d, tl)
    assert m["cv"] == round(pace.pace_cv(policy._Pass(d, tl, []).changes()), 2)
    assert sum(1 for n in notes if n.startswith(("pace:", "director plan pace:"))) == 1 and notes[-1].startswith("pace:")


def test_capped_punches_vary_under_the_cap(tmp_path):
    b = compiler._Builder.__new__(compiler._Builder)
    b.s = SimpleNamespace(title="Reel Director demo")
    got = {b.punch_scale(1.17, 1.10, f) for f in range(0, 400, 7)}
    assert all(1.06 <= k <= 1.10 for k in got) and len(got) > 10
    assert b.punch_scale(1.17, 1.10 * 607 / 1080, 30) == 1.0                # under 1.06: punches off


def test_punches_switched_off_by_the_resolution_guard_are_not_counted(monkeypatch):
    d, tl, _ = directed("clean-pro")
    before = len(policy._Pass(d, tl, []).changes())
    for p in tl.shots:
        p.take = SimpleNamespace(src="landscape-1080p.mp4")
    monkeypatch.setattr(compiler, "probe_size", lambda path: (1920, 1080))   # 9:16 crop 607 px -> cap 0.62
    P = policy._Pass(d, tl, [])
    assert all(P.punch_off(si) for si in range(len(tl.shots)))
    assert len(P.changes()) < before


def test_hook_hit_anchors_the_bed_and_open_punch_is_ignored():
    d, tl, _ = directed("clean-pro")
    hook = [c for c in d.shots[0].cues if c.type == "sfx" and c.params.get("role") == "hook"]
    assert hook
    w = tl.shots[0].words[hook[0].start_word].start
    assert abs(mixdown.hero_time(tl) - (int(np.floor(w * 30 + 0.5)) + 1) / 30) < 1e-9
    for c in list(d.shots[0].cues):
        if c.type == "sfx":
            d.shots[0].cues.remove(c)
    tl2 = build_timeline(d)
    first = next(c for c in d.shots[0].cues if c.type == "punch" and not c.params.get("open"))
    assert mixdown.hero_time(tl2) == tl2.shots[0].words[first.start_word].start > 0


def test_broll_entrances_get_a_pop_on_the_card_frame():
    d, tl, _ = directed("clean-pro")
    for si, sh in enumerate(d.shots):
        for c in sh.cues:
            if c.type == "broll" and c.params.get("kind") != "stat":
                pops = [x for x in sh.cues if x.type == "sfx" and x.start_word == c.start_word]
                assert pops and pops[0].params["on"] == "lead" and pops[0].params["id"] == "snd.ui.pop"
    for ev in mixdown.sfx_events(tl):
        if ev["on"] == "lead":
            p = next(p for p in tl.shots if p.shot.id == ev["shot"])
            card = [x for x in p.shot.cues if x.type == "broll"][0]
            assert abs(ev["t"] - max(p.out_start, p.words[card.start_word].start - 4 / 30)) < 1e-3


def test_long_reels_get_a_non_loop_bed_and_the_bed_is_shelved_and_ends_on_a_bar():
    long = json.loads((ROOT / "examples" / "demo" / "script-lines-only.json").read_text())
    long["shots"] = long["shots"] * 4
    for k, sh in enumerate(long["shots"]):
        long["shots"][k] = {**sh, "id": f"{sh['id']}{k}"}
    d, tl, _ = directed("clean-pro", long)
    assert tl.duration > 32 and mixdown.pick_bed(tl)["loop"] is False
    d, tl, _ = directed("clean-pro")
    bed = mixdown.pick_bed(tl)
    y, grid = mixdown.bed_track(tl, bed, int(tl.duration * mixdown.SR))
    assert grid["end_s"] in grid["bars"] and not np.any(y[int((grid["end_s"] + 0.01) * mixdown.SR):])
    b, a = mixdown._low_shelf(150.0, -5.0)
    from scipy.signal import freqz
    _, h = freqz(b, a, worN=[40.0, 1000.0], fs=mixdown.SR)
    assert abs(20 * np.log10(abs(h[0])) + 5.0) < 0.6 and abs(20 * np.log10(abs(h[1]))) < 0.5
