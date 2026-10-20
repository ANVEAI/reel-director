"""Auto-director: golden output for 3 presets, the playbook rules as properties, manual cues win,
determinism, idempotence. Regenerate goldens with REEL_DIRECTOR_REGEN_GOLDEN=1 after a deliberate change."""
import copy
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from reel_director import lexicon as lx
from reel_director.director import _Director, direct
from reel_director.presets import PACE, PRESETS
from reel_director.schema import load_script, parse_script, script_to_dict
from reel_director.timeline import build_timeline

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "golden"
LINES = json.loads((ROOT / "examples" / "demo" / "script-lines-only.json").read_text())
LONG = {"title": "Long test reel", "shots": [
    {"id": "hook", "line": "I made $40,000 from one reel and nobody believed me."},
    {"id": "promise", "line": "Here's the exact system, step by step, so you can copy it."},
    {"id": "s1", "line": "First, write the script before you ever touch the camera."},
    {"id": "s2", "line": "Second, record five short takes, not one long take."},
    {"id": "s3", "line": "Third, cut every pause longer than half a second."},
    {"id": "turn", "line": "But here's the part nobody tells you: the hook is ninety percent of the work."},
    {"id": "proof", "line": "My best reel had a three second hook, and it got two million views in a week."},
    {"id": "payoff", "line": "So stop editing for hours and start writing better first lines."},
    {"id": "cta", "line": "Follow for the next breakdown."}]}
# EP P1 allowed medians; calm's floor is 2.4 s, not 3.0: the contract's 25-40% B-roll band adds two edges
# per insert, which a calm reel at EP B1's 10-25% coverage would not have.
# standard 1.9 (was 2.0): an insert now enters on its noun, 4 frames ahead (council 4), instead of snapping
# to the shot cut up to 1.3 s early, so the plan has one more change; the council gate is pace.metrics.
MEDIAN_RANGE = {"calm": (2.4, 6.0), "standard": (1.9, 3.5), "punchy": (1.3, 2.4)}


def directed(preset, data=LINES):
    data = copy.deepcopy(data)
    data["style"] = {**data.get("style", {}), "preset": preset}
    s, notes = parse_script(data), []
    return s, direct(s, notes=notes), notes


def plan(preset, data=LINES):
    """The directed script plus a _Director view of it that sees every cue (for word times and VEs)."""
    s, d, _ = directed(preset, data)
    dr = _Director(d)
    dr.manual, dr.auto = [list(sh.cues) for sh in d.shots], [[] for _ in d.shots]
    return dr, d


@pytest.mark.parametrize("preset", ["bold-hustle", "clean-pro", "editorial"])
def test_golden_direct_output(preset):
    _, d, notes = directed(preset)
    got = json.loads(json.dumps({"script": script_to_dict(d), "notes": notes}, sort_keys=True))
    path = GOLDEN / f"director_{preset}.json"
    if os.environ.get("REEL_DIRECTOR_REGEN_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    assert got == json.loads(path.read_text())


def test_golden_files_differ_by_preset():
    a, b = (json.loads((GOLDEN / f"director_{p}.json").read_text()) for p in ("bold-hustle", "clean-pro"))
    ta = [c.get("id") for sh in a["script"]["shots"] for c in sh["cues"] if c["type"] in ("transition", "sfx")]
    tb = [c.get("id") for sh in b["script"]["shots"] for c in sh["cues"] if c["type"] in ("transition", "sfx")]
    assert ta != tb


@pytest.mark.parametrize("data", [LINES, LONG], ids=["demo", "long"])
@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_playbook_rules_hold(preset, data):
    dr, d = plan(preset, data)
    n_words = sum(len(sh.words) for sh in d.shots)
    autos = [(si, c) for si, sh in enumerate(d.shots) for c in sh.cues]
    assert all(c.params.get("auto") is True and c.params.get("why") for _, c in autos)
    parse_script(json.loads(json.dumps(script_to_dict(d))))           # validates against the schema + pack
    t = lambda si, c: dr.words[si][c.start_word].start                 # noqa: E731
    by = lambda kind: [(si, c) for si, c in autos if c.type == kind]   # noqa: E731
    # hook: text from frame 0, <= 7 words; a punch (pattern interrupt) by 1.0 s
    (ti, title), = by("title")
    assert ti == 0 and title.start_word == 0 and 1 <= len(title.params["text"].split()) <= 7
    assert any(si == 0 and t(si, c) <= 1.0 for si, c in by("punch"))
    # punch ladder: valid levels, every punch changes level, T at most once
    for sh in d.shots:
        levels = [c.params["level"] for c in sorted(sh.cues, key=lambda c: c.start_word) if c.type == "punch"]
        assert set(levels) <= {"W", "M", "T"} and "W" not in levels[:1]
        assert all(x != y for x, y in zip(levels, levels[1:]))
        assert all(y != "T" or x == "W" for x, y in zip(["W"] + levels, levels))   # T cap to M still changes
    assert sum(c.params["level"] == "T" for _, c in by("punch")) <= 1
    # B-roll: 25-40% of runtime, never in the first 2 s, tied to the line's words
    cover = sum(dr.span_t(si, c.start_word, c.end_word)[1] - dr.span_t(si, c.start_word, c.end_word)[0]
                for si, c in by("broll"))
    assert 0.25 <= cover / dr.dur <= 0.40, cover / dr.dur
    assert all(t(si, c) >= 2.0 for si, c in by("broll"))
    # transitions: only into later shots, at their first word, <= 3, >= 10 s apart
    tx = [t(si, c) for si, c in by("transition")]
    assert all(si > 0 and c.start_word == 0 for si, c in by("transition"))
    assert len(tx) <= 3 and all(b - a >= 10.0 for a, b in zip(tx, tx[1:]))
    # SFX: <= 1 per 2 s, none in the last 0.5 s
    sfx = sorted(t(si, c) for si, c in by("sfx"))
    assert all(b - a >= 2.0 for a, b in zip(sfx, sfx[1:])) and all(x <= dr.dur - 0.5 for x in sfx)
    # emphasis: every number phrase it could afford, <= 15% of words
    emph = sum(c.end_word - c.start_word + 1 for _, c in by("emphasis"))
    assert 0 < emph <= max(1, int(0.15 * n_words))
    # end card on the last shot, ending on the last word
    (ei, end), = by("endcard")
    assert ei == len(d.shots) - 1 and end.end_word == len(d.shots[-1].words) - 1
    assert d.music["mood"] == PRESETS[preset]["music_mood"]


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_pace_profile_cadence_on_a_long_reel(preset):
    dr, d = plan(preset, LONG)
    ves = dr._ves()
    gaps = [b - a for a, b in zip(ves, ves[1:])]
    lo, hi = MEDIAN_RANGE[PRESETS[preset]["pace"]]
    assert lo <= statistics.median(gaps) <= hi
    cv = statistics.pstdev(gaps) / statistics.mean(gaps)
    assert cv >= 0.25, f"metronomic: CV {cv:.2f}"                   # EP C1
    assert max(gaps) <= PACE[PRESETS[preset]["pace"]]["max_static"] + 1.2   # EP P4 (+ beat hold)


def test_stat_list_and_text_brolls_come_from_the_words():
    _, d = plan("bold-hustle", LONG)
    kinds = {c.params["kind"]: c for sh in d.shots for c in sh.cues if c.type == "broll"}
    assert {"stat", "text"} <= set(kinds)
    stats = {(c.params["value"], c.params["label"]) for sh in d.shots for c in sh.cues
             if c.type == "broll" and c.params["kind"] == "stat"}
    assert ("2,000,000", "VIEWS") in stats and ("90%", "WORK") in stats
    _, demo, _ = directed("bold-hustle")
    lists = [c.params for sh in demo.shots for c in sh.cues if c.type == "broll" and c.params["kind"] == "list"]
    assert lists and lists[0]["items"][:2] == ["READ THE SCRIPT", "HIT RECORD"]


def test_manual_cues_are_kept_and_win():
    s = load_script(ROOT / "examples" / "demo" / "script.json")
    d = direct(s)
    for sh, dsh in zip(s.shots, d.shots):
        manual = [(c.type, c.start_word, c.end_word, c.params) for c in sh.cues]
        assert [(c.type, c.start_word, c.end_word, c.params) for c in dsh.cues[:len(manual)]] == manual
        auto = dsh.cues[len(manual):]
        for c in auto:     # no auto cue of a kind overlaps a manual cue of the same kind
            assert not any(m.type == c.type and m.start_word <= c.end_word and c.start_word <= m.end_word
                           for m in sh.cues)
    dr = _Director(d)
    sfx = sorted(dr.words[si][c.start_word].start for si, sh in enumerate(d.shots) for c in sh.cues
                 if c.type == "sfx")
    manual_sfx = {dr.words[si][c.start_word].start for si, sh in enumerate(s.shots) for c in sh.cues if c.type == "sfx"}
    assert all(b - a >= 2.0 or {a, b} <= manual_sfx for a, b in zip(sfx, sfx[1:]))
    assert d.music == s.music                                # a given bed is never replaced


def test_deterministic_idempotent_and_process_independent():
    _, d1, n1 = directed("clean-pro", LONG)
    _, d2, n2 = directed("clean-pro", LONG)
    j1 = json.dumps(script_to_dict(d1), sort_keys=True)
    assert j1 == json.dumps(script_to_dict(d2), sort_keys=True) and n1 == n2
    again = direct(parse_script(json.loads(j1)))            # re-directing drops and rebuilds auto cues
    assert json.dumps(script_to_dict(again), sort_keys=True) == j1
    code = ("import json,sys; from reel_director.schema import parse_script, script_to_dict; "
            "from reel_director.director import direct; d=json.load(sys.stdin); "
            "print(json.dumps(script_to_dict(direct(parse_script(d))), sort_keys=True))")
    data = {**LONG, "style": {"preset": "clean-pro"}}
    out = subprocess.run([sys.executable, "-c", code], input=json.dumps(data), capture_output=True, text=True,
                         env={**os.environ, "PYTHONHASHSEED": "12345"}, check=True).stdout.strip()
    assert out == j1


def test_shot_opt_out_creator_strap_and_real_timeline():
    data = copy.deepcopy(LONG)
    data["shots"][3]["auto"] = False
    data["shots"][5]["auto"] = {"broll": False}
    data["style"] = {"preset": "clean-pro", "creator": {"name": "Alex Doe", "role": "Founder"}}
    s = parse_script(data)
    d = direct(s)
    assert not [c for c in d.shots[3].cues if c.params.get("auto")]
    assert not [c for c in d.shots[5].cues if c.type == "broll"]
    straps = [c for sh in d.shots for c in sh.cues if c.type == "lowerthird"]
    assert len(straps) == 1 and straps[0].params["text"] == "Alex Doe" and straps[0].params["sub"] == "Founder"
    timed = direct(s, timeline=build_timeline(s))            # real word times drive the same rules
    assert [c.type for sh in timed.shots for c in sh.cues if c.type == "title"] == ["title"]


def test_lexicon_features():
    t = "Post 5 reels a week and grow 40% in two months".split()
    assert [" ".join(t[a:b + 1]) for a, b in lx.number_phrases(t)] == ["5 reels", "40%", "two months"]
    assert lx.number_display(["three", "hours"]) == ("3", "HOURS")
    assert lx.number_display(["two", "million", "views"]) == ("2,000,000", "VIEWS")
    assert lx.number_display(["ninety", "percent"]) == ("90%", "")
    assert lx.spoken_tokens("2") == ["two"] and lx.spoken_tokens("their") == ["their"]
    assert lx.enumeration("Step by step, so you can, copy it.".split()) is None
    assert not lx.is_numeric("one", "reel") and lx.is_numeric("one", "hour")
    assert lx.hook_title("Most creators waste three hours editing one reel.".split(), 3) == "Most creators waste"
    assert lx.cta_text("Follow for the next breakdown.".split()) == "Follow for the next breakdown"
    assert lx.icon_for(["camera"]) == "play" and lx.icon_for(["banana"]) is None


@pytest.mark.parametrize("shots", [
    [{"line": "Go."}],
    [{"line": "3 2 1."}, {"line": "Now!"}],
    [{"line": " ".join(f"word{i}" if i % 7 else "never" for i in range(40)) + "."}],
    [{"line": "We are the #1 tool, email me @alexdoe, and save 50% today."}, {"line": "Follow, share, and save this."}],
    [{"line": "Most creators waste three hours.", "cues": [{"type": "title", "at": "Most", "text": "Stop wasting"}]},
     {"line": "Here's the fix.", "cues": [{"type": "transition", "at": "Here's", "id": "flash"},
                                         {"type": "endcard", "at": "fix.", "text": "Save it"}]}],
    [{"line": "Yeh reel banane mein sirf 5 minute lagte hain, bhai."}, {"line": "Aur editing? Zero."}],
], ids=["one-word", "numbers-only", "long-line", "hash-at-symbols", "manual-furniture", "hinglish"])
@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_edge_case_scripts_direct_cleanly(shots, preset):
    data = {"title": "edge", "style": {"preset": preset}, "shots": [{"id": f"s{i}", **sh} for i, sh in enumerate(shots)]}
    d = direct(parse_script(data))
    back = parse_script(json.loads(json.dumps(script_to_dict(d))))
    assert len([c for sh in back.shots for c in sh.cues if c.type == "title"]) == 1
    assert len([c for sh in back.shots for c in sh.cues if c.type == "endcard"]) == 1
