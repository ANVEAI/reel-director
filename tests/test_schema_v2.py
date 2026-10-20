"""Schema v2: anchors ('#'/'@' occurrences, homophones), new cue types, presets, round trip."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from reel_director.presets import (CAPTIONS, PRESETS, SFX_KITS, TRANSITIONS, TX_SFX, resolve_style)
from reel_director.schema import (ScriptError, find_phrase, pack_ids, parse_script, script_to_dict,
                                  split_words)

ROOT = Path(__file__).resolve().parents[1]
FONTS = {"Montserrat", "Anton", "Bebas Neue", "Inter", "Bangers", "Instrument Serif", "Noto Sans Devanagari",
         "Archivo Black"}
needs_pack = pytest.mark.skipif(pack_ids() is None, reason="motion-pack not installed")


def shot(line, cues, **style):
    return parse_script({"style": style, "shots": [{"id": "a", "line": line, "cues": cues}]}).shots[0]


def two_shots(cue):
    return parse_script({"shots": [{"id": "a", "line": "One two."}, {"id": "b", "line": "Three four.",
                                                                    "cues": [cue]}]})


# ---- review finding: '#' inside an anchor crashed validate with a bare ValueError --------------
def test_hash_in_anchor_is_part_of_the_phrase():
    ws = split_words("We are the #1 tool and still #1")
    assert find_phrase(ws, "#1 tool") == (3, 4)
    assert find_phrase(ws, "the #1") == (2, 3)
    assert find_phrase(ws, "#1") == (3, 3)
    assert find_phrase(ws, "still #1") == (6, 7)
    assert find_phrase(ws, "#1#2") == (7, 7) and find_phrase(ws, "#1@2") == (7, 7)


def test_occurrence_syntax_at_and_hash_both_work():
    ws = split_words("one reel, then one reel more")
    assert find_phrase(ws, "one reel@2") == find_phrase(ws, "one reel#2") == (3, 4)
    with pytest.raises(ScriptError, match="occurrence 3"):
        find_phrase(ws, "one reel@3")
    with pytest.raises(ScriptError, match="@1 or higher"):
        find_phrase(ws, "reel@0")


def test_bad_hash_anchor_is_a_script_error_not_a_crash(tmp_path):
    with pytest.raises(ScriptError, match="not found"):
        find_phrase(split_words("hit record now"), "hit record#two")
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"shots": [{"id": "a", "line": "We are the #1 tool for reels.",
                                        "cues": [{"type": "overlay", "at": "#1 tool", "text": "No. 1"}]}]}))
    r = subprocess.run([sys.executable, "-m", "reel_director", "validate", str(p)], capture_output=True, text=True,
                       cwd=ROOT)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr
    p.write_text(json.dumps({"shots": [{"id": "a", "line": "hit record now",
                                        "cues": [{"type": "overlay", "at": "hit record#two", "text": "x"}]}]}))
    r = subprocess.run([sys.executable, "-m", "reel_director", "validate", str(p)], capture_output=True, text=True,
                       cwd=ROOT)
    assert r.returncode != 0 and "Traceback" not in r.stderr and "not found" in r.stderr


# ---- review finding: homophone merge landed anchors on the wrong word -------------------------
def test_anchor_never_lands_on_a_homophone():
    s = shot("I want to show you 2 tricks", [{"type": "overlay", "at": "2", "text": "x"}])
    assert (s.cues[0].start_word, s.cues[0].end_word) == (5, 5)
    ws = split_words("Go there, put their stuff there.")
    assert find_phrase(ws, "their") == (3, 3)
    assert find_phrase(ws, "there#2") == find_phrase(ws, "there@2") == (5, 5)
    assert find_phrase(split_words("I want to show you 2 tricks"), "two") == (5, 5)    # spelled number = digits
    assert find_phrase(split_words("Most creators waste 3 hours"), "three hours") == (3, 4)


def test_homophone_anchor_fails_loudly_with_a_hint():
    with pytest.raises(ScriptError, match="did you mean 'reel'"):
        find_phrase(split_words("Edit one reel today"), "real")
    with pytest.raises(ScriptError, match="not found"):
        find_phrase(split_words("Here's how to do it"), "2")


def test_asr_matching_still_merges_homophones():
    assert split_words("their")[0].norm == split_words("there")[0].norm      # Word.norm feeds timing.align


# ---- new cue types ----------------------------------------------------------------------------
@pytest.mark.parametrize("cue, err", [
    ({"type": "punch", "at": "beta"}, "level"),
    ({"type": "punch", "at": "beta", "level": "XL"}, "level"),
    ({"type": "broll", "at": "beta"}, "kind"),
    ({"type": "broll", "at": "beta", "kind": "stat", "value": "3"}, "label"),
    ({"type": "broll", "at": "beta", "kind": "list", "items": []}, "items"),
    ({"type": "broll", "at": "beta", "kind": "icon", "icon": "bolt"}, "text"),
    ({"type": "broll", "at": "beta", "kind": "clip"}, "src"),
    ({"type": "broll", "at": "beta", "kind": "text", "text": "x", "layout": "grid"}, "layout"),
    ({"type": "title", "at": "alpha"}, "text"),
    ({"type": "title", "at": "alpha", "text": "one two three four five six seven eight"}, "max 7"),
    ({"type": "lowerthird", "at": "alpha"}, "text"),
    ({"type": "endcard", "at": "alpha", "text": "x", "sub": 3}, "sub"),
    ({"type": "callout", "at": "alpha", "kind": "star"}, "callout"),
    ({"type": "sfx", "at": "alpha"}, "exactly one"),
    ({"type": "sfx", "at": "alpha", "src": "a.wav", "id": "snd.ui.pop"}, "exactly one"),
    ({"type": "zoom", "at": "alpha", "scale": 5}, "scale"),
    ({"type": "sparkle", "at": "alpha"}, "unknown cue type"),
])
def test_new_cue_params_are_validated(cue, err):
    with pytest.raises(ScriptError, match=err):
        shot("alpha beta gamma", [cue])


def test_new_cue_types_parse():
    s = shot("alpha beta gamma delta", [
        {"type": "punch", "at": "beta", "level": "T"},
        {"type": "broll", "at": "beta", "until": "delta", "kind": "list", "items": ["A", "B"], "layout": "split"},
        {"type": "broll", "at": "alpha", "kind": "stat", "value": "3", "label": "HOURS"},
        {"type": "title", "at": "alpha", "until": "beta", "text": "Alpha beta"},
        {"type": "lowerthird", "at": "gamma", "text": "Alex", "sub": "Founder"},
        {"type": "endcard", "at": "delta", "text": "Follow for more"},
        {"type": "callout", "at": "gamma", "kind": "underline"},
        {"type": "sfx", "at": "alpha", "src": "media/pop.wav"},
    ])
    assert [c.type for c in s.cues] == ["punch", "broll", "broll", "title", "lowerthird", "endcard", "callout", "sfx"]
    assert (s.cues[1].start_word, s.cues[1].end_word) == (1, 3)


def test_transition_leads_into_a_later_shot_only():
    s = two_shots({"type": "transition", "at": "Three", "id": "whip", "params": {"dir": [1, 0]}})
    assert s.shots[1].cues[0].params["id"] == "whip"
    with pytest.raises(ScriptError, match="first word"):
        two_shots({"type": "transition", "at": "four", "id": "whip"})
    with pytest.raises(ScriptError, match="first shot"):
        shot("alpha beta", [{"type": "transition", "at": "alpha", "id": "whip"}])
    with pytest.raises(ScriptError, match="params"):
        two_shots({"type": "transition", "at": "Three", "id": "whip", "params": [1]})


@needs_pack
def test_pack_ids_are_checked():
    with pytest.raises(ScriptError, match="transitions/aliases.json"):
        two_shots({"type": "transition", "at": "Three", "id": "teleport"})
    with pytest.raises(ScriptError, match="sfx/manifest.json"):
        shot("alpha", [{"type": "sfx", "at": "alpha", "id": "snd.nope"}])
    with pytest.raises(ScriptError, match="music/manifest.json"):
        parse_script({"music": {"id": "music.nope"}, "shots": [{"line": "alpha"}]})
    assert shot("alpha", [{"type": "sfx", "at": "alpha", "id": "snd.ui.pop"}]).cues[0].params["id"] == "snd.ui.pop"


def test_music_needs_a_source():
    with pytest.raises(ScriptError, match="music needs"):
        parse_script({"music": {"volume": 0.2}, "shots": [{"line": "alpha"}]})
    assert parse_script({"music": False, "shots": [{"line": "alpha"}]}).music is False
    assert parse_script({"music": {"mood": "warm"}, "shots": [{"line": "alpha"}]}).music == {"mood": "warm"}


# ---- presets -----------------------------------------------------------------------------------
def test_six_presets_are_full_styles():
    assert {"bold-hustle", "clean-pro", "beast-hype", "editorial", "tech-explainer", "desi-bilingual"} <= set(PRESETS)
    keys = {"font", "caption", "accent", "text", "bg", "look", "background", "pace", "transitions", "sfx_kit",
            "music_mood"}
    for name in PRESETS:
        st = resolve_style({"preset": name})
        assert keys <= set(st) and st["preset"] == name and st["font"] in FONTS and st["caption"] in CAPTIONS
        assert {"grain", "vignette", "grade"} <= set(st["look"])
    assert "Devanagari" in PRESETS["desi-bilingual"]["font"]


def test_preset_overrides_merge_and_bad_values_fail():
    st = resolve_style({"preset": "clean-pro", "accent": "#FF0000", "look": {"grain": 0.3}})
    assert st["accent"] == "#FF0000" and st["look"] == {**PRESETS["clean-pro"]["look"], "grain": 0.3}
    assert parse_script({"shots": [{"line": "alpha"}]}).style["preset"] == "bold-hustle"    # v1 scripts
    assert parse_script({"style": {"accent": "#00FF00"}, "shots": [{"line": "a"}]}).style["accent"] == "#00FF00"
    for bad, err in [({"preset": "vaporwave"}, "unknown style.preset"), ({"caption": "comic"}, "caption"),
                     ({"look": {"grade": "sepia"}}, "grade"), ({"look": {"grain": 2}}, "grain"),
                     ({"pace": "warp"}, "pace")]:
        with pytest.raises(ScriptError, match=err):
            parse_script({"style": bad, "shots": [{"line": "alpha"}]})


@needs_pack
def test_preset_sound_transition_and_music_ids_exist_in_the_pack():
    sfx, tx, music = pack_ids()
    assert {i for kit in SFX_KITS.values() for i in kit.values()} <= sfx
    assert set(TX_SFX.values()) <= sfx and set(TX_SFX) <= tx
    assert {t for fam in TRANSITIONS.values() for t in fam.values() if t} <= tx
    assert {b for p in PRESETS.values() for b in p["music_beds"]} <= music
    root = Path.home() / "Developer" / "motion-pack-public"
    moods = {m for i in json.loads((root / "music" / "manifest.json").read_text())["items"] for m in i.get("mood") or []}
    assert {p["music_mood"] for p in PRESETS.values()} <= moods


# ---- round trip -------------------------------------------------------------------------------
def test_script_to_dict_round_trips_with_occurrences():
    data = {"title": "t", "style": {"preset": "editorial"}, "music": {"mood": "calm"},
            "shots": [{"id": "a", "line": "one reel, then one reel and the #1 reel", "role": "hook",
                       "cues": [{"type": "overlay", "at": "one reel@2", "text": "x"},
                                {"type": "broll", "at": "then", "until": "reel@3", "kind": "text", "text": "y"},
                                {"type": "emphasis", "at": "#1"}]}]}
    s = parse_script(data)
    d = script_to_dict(s)
    assert d["shots"][0]["role"] == "hook" and d["shots"][0]["cues"][0]["at"] == "one reel@2"
    back = parse_script(json.loads(json.dumps(d)))
    assert [(c.type, c.start_word, c.end_word, c.params) for c in back.shots[0].cues] == \
           [(c.type, c.start_word, c.end_word, c.params) for c in s.shots[0].cues]
    assert back.style == s.style and back.music == s.music
