"""Director + sound polish (20 Oct): presets cut visibly differently inside the council gates, energetic
presets reach their SFX density (pop on card entrances, count-up on the stat card, whoosh only with a
transition, never the same sample twice in a row), and reels over 32 s get a non-loop bed."""
import copy
import json
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from reel_director import broll_media, mixdown, pace, pipeline, policy, presets
from reel_director.schema import Cue, parse_script
from reel_director.timeline import build_timeline

ROOT = Path(__file__).resolve().parents[1]
LINES = json.loads((ROOT / "examples" / "demo" / "script-lines-only.json").read_text())
LONG = {"title": "Long test reel", "style": {"preset": "bold-hustle"}, "shots": [   # = work/v1-director/long.json
    {"id": "hook", "line": "I made $40,000 from one reel and nobody believed me."},
    {"id": "promise", "line": "Here's the exact system, step by step, so you can copy it."},
    {"id": "s1", "line": "First, write the script before you ever touch the camera."},
    {"id": "s2", "line": "Second, record five short takes, not one long take."},
    {"id": "s3", "line": "Third, cut every pause longer than half a second."},
    {"id": "turn", "line": "But here's the part nobody tells you: the hook is ninety percent of the work."},
    {"id": "proof", "line": "My best reel had a three second hook, and it got two million views in a week."},
    {"id": "payoff", "line": "So stop editing for hours and start writing better first lines."},
    {"id": "cta", "line": "Follow for the next breakdown."}]}
LONG_CARDS = {"title": "Long reel", "shots": [     # = tests/test_policy.py LONG: two text cards in a row
    {"id": "hook", "line": "I made $40,000 last month with one simple trick."},
    {"id": "a", "line": "First, I stopped editing every single reel by hand."},
    {"id": "b", "line": "Second, I wrote the script before I ever pressed record."},
    {"id": "c", "line": "Third, I let the tool cut my pauses, my ums and my restarts."},
    {"id": "d", "line": "That saved me three hours a day, every single day this year."},
    {"id": "e", "line": "Now I post twice a day and my views went up ten times."},
    {"id": "cta", "line": "Follow for the full setup and save this for later."}]}
DEMO4 = ["clean-pro", "bold-hustle", "beast-hype", "desi-bilingual"]
ENERGETIC = ["bold-hustle", "beast-hype"]
CARD_SOUNDS = {policy.SFX_IDS["pop"], policy.SFX_IDS["pop_alt"], policy.SFX_IDS["ding"]}
HAS_PACK = (mixdown.PACK / "music" / "manifest.json").exists()


def run(data: dict, preset: str):
    s = parse_script(policy.prepare(copy.deepcopy(data), preset))
    notes: list[str] = []
    d = pipeline.direct(s, None, notes=notes)
    return d, build_timeline(d), notes


def cue_plan(d) -> list:
    return [(sh.id, c.type, c.start_word, c.end_word,
             json.dumps({k: v for k, v in c.params.items() if k not in ("auto", "why")}, sort_keys=True))
            for sh in d.shots for c in sh.cues]


def sfx(d, tl) -> list[tuple[float, str, int, Cue]]:
    P = policy._Pass(d, tl, [])
    return sorted((P.t(si, c.start_word), c.params.get("id"), si, c)
                  for si, sh in enumerate(d.shots) for c in sh.cues if c.type == "sfx")


@pytest.mark.parametrize("data", [LINES, LONG, LONG_CARDS], ids=["demo", "long", "long-cards"])
def test_the_four_demo_presets_cut_differently(data):
    plans = {p: cue_plan(run(data, p)[0]) for p in DEMO4}
    for a, b in combinations(DEMO4, 2):
        if data is LINES and {a, b} == {"clean-pro", "desi-bilingual"}:
            continue    # read-time estimate: no card survives the 2.5 s face tail, so the two standard presets
            # differ only on the card (dry.py's real takes keep one) and the caption style
        assert plans[a] != plans[b], f"{a} and {b} give the same cue plan"


@pytest.mark.parametrize("preset", DEMO4)
def test_cards_carry_the_preset_style(preset):
    d, _, _ = run(LONG, preset)
    look = presets.DIRECTION[preset]
    cards = [c.params for sh in d.shots for c in sh.cues if c.type == "broll" and c.params.get("auto")]
    assert cards and all(p["background"] == look["card"] for p in cards)
    lines = {id(c.params): sh.line for sh in d.shots for c in sh.cues}
    assert all(p["text"] == presets.card_case(p["text"], look["case"], lines[id(p)]) for p in cards if p["kind"] == "text")
    if preset == "clean-pro":                       # council 7: sentence case
        assert any(p["kind"] == "text" and p["text"] != p["text"].upper() for p in cards)


@pytest.mark.parametrize("preset", ["clean-pro", "desi-bilingual", "bold-hustle"])
def test_card_case_keeps_the_scripts_spelling(preset):
    """Sentence/title case must not respell 'YouTube' as 'Youtube' or 'AI' as 'Ai' (verifier, 20 Oct)."""
    data = copy.deepcopy(LINES)
    data["shots"][1]["line"] = "What if your YouTube edit was finished before you even pressed record?"
    d, _, _ = run(data, preset)
    texts = [c.params["text"] for sh in d.shots for c in sh.cues      # v4: a media insert keeps its label card
             if c.type == "broll" and c.params.get("kind") in ("text", "media")]
    want = "YOUTUBE" if presets.DIRECTION[preset]["case"] == "upper" else "YouTube"
    assert texts and all(want in t for t in texts), texts
    assert presets.card_case("AI WRITES MY HOOK", "sentence", "AI writes my hook") == "AI writes my hook"
    assert presets.card_case("10X FASTER WITH AI", "title", "10X faster with AI") == "10X Faster With AI"
    assert presets.card_case("EDIT: DONE", "sentence", "WHAT IF THE EDIT WAS DONE") == "Edit: done"


@pytest.mark.parametrize("data", [LINES, LONG, LONG_CARDS], ids=["demo", "long", "long-cards"])
@pytest.mark.parametrize("preset", DEMO4)
def test_council_gates_hold(preset, data):
    d, tl, _ = run(data, preset)
    m, pc = policy.metrics(d, tl), policy.PACE[d.style["pace"]]
    cap = max(pc["broll"], broll_media.recipe(d.style)["share"][1])      # v4: real media counts (recipe cap)
    assert m["broll_share"] <= cap + 1e-6 and m["hard_cut_share"] >= 0.9
    assert m["first_change_s"] <= 1.0 and m["changes_by_3s"] >= 2
    assert m["max_static_s"] <= pc["max_static"] + 1e-6 and m["cv"] >= pace.CV_FAIL
    assert m["sfx"] <= max(1, int(pc["sfx30"] * tl.duration / 30))
    ev = sfx(d, tl)
    assert all(b[0] - a[0] >= 1.0 - 1e-6 for a, b in zip(ev, ev[1:]))      # council 8 (and never within 250 ms)
    assert all(a[1] != b[1] for a, b in zip(ev, ev[1:]))                    # no repeats
    assert all(t <= tl.duration - 0.5 for t, *_ in ev)
    tx = [c for sh in d.shots for c in sh.cues if c.type == "transition"]
    assert all(c.params["id"] == presets.DIRECTION[preset]["tx"] for c in tx)
    P = policy._Pass(d, tl, [])
    for si, sh in enumerate(d.shots):
        for c in sh.cues:
            if c.type == "broll":
                a, b = P.span(si, c)
                assert b <= tl.duration - policy.FACE_TAIL + 1e-6 and b - a >= policy.INSERT[0] - 1e-6


@pytest.mark.parametrize("data", [LINES, LONG], ids=["demo", "long"])
@pytest.mark.parametrize("preset", DEMO4)
def test_card_and_transition_sounds_sit_on_their_events(preset, data):
    d, tl, _ = run(data, preset)
    for t, sid, si, c in sfx(d, tl):
        sh, role = d.shots[si], c.params.get("role")
        if role == "whoosh":                                               # whoosh only with a transition
            assert any(x.type == "transition" for x in sh.cues)
        elif sid in CARD_SOUNDS:
            card = [x for x in sh.cues if x.type == "broll" and x.start_word == c.start_word]
            assert card and c.params.get("on") == "lead"
            assert (sid == policy.SFX_IDS["ding"]) == (card[0].params["kind"] == "stat")
            assert c.params["level_db"] == (-14.0 if role == "pop" else -12.0)   # pop at tier 3
        assert sid != policy.SFX_IDS["pop_alt"] or preset in ENERGETIC


@pytest.mark.parametrize("data", [LINES, LONG], ids=["demo", "long"])
@pytest.mark.parametrize("preset", ENERGETIC)
def test_energetic_presets_sound_every_card_and_outnumber_standard(preset, data):
    d, tl, _ = run(data, preset)
    heard = {(si, c.start_word) for _, sid, si, c in sfx(d, tl) if sid in CARD_SOUNDS}
    cards = {(si, c.start_word) for si, sh in enumerate(d.shots) for c in sh.cues if c.type == "broll"}
    assert cards and cards <= heard
    std, got = policy.metrics(*run(data, "clean-pro")[:2])["sfx"], policy.metrics(d, tl)["sfx"]
    assert got > std if data is LONG else got >= std


def test_a_run_of_cards_keeps_its_pops_on_energetic_presets():
    d, tl, _ = run(LONG_CARDS, "beast-hype")
    ids = [sid for _, sid, _, _ in sfx(d, tl)]
    assert policy.SFX_IDS["pop_alt"] in ids and policy.metrics(d, tl)["sfx"] == 7      # = 8 per 30 s target
    d, tl, notes = run(LONG_CARDS, "clean-pro")
    assert policy.SFX_IDS["pop_alt"] not in [sid for _, sid, _, _ in sfx(d, tl)]


def test_no_repeats_switches_a_repeated_pop_to_the_variant():
    def fake(n):
        cues = [Cue("sfx", i, i, {"id": "snd.ui.pop", "role": "pop"}) for i in range(n)]
        P = NS(s=NS(shots=[NS(id="a", cues=list(cues))]), dropped=[])
        P.drop = lambda si, c, why: (P.s.shots[si].cues.remove(c), P.dropped.append(why))
        return P, [(float(i), "snd.ui.pop", 0, c) for i, c in enumerate(cues)]
    P, kept = fake(3)
    pace.no_repeats(P, kept, "snd.ui.pop", "snd.ui.pop_down")
    assert [c.params["id"] for c in P.s.shots[0].cues] == ["snd.ui.pop", "snd.ui.pop_down", "snd.ui.pop"]
    assert not P.dropped
    P, kept = fake(3)
    pace.no_repeats(P, kept, "snd.ui.pop", None)                          # calm/standard: council 8 as before
    assert len(P.s.shots[0].cues) == 1 and P.dropped == ["no repeated SFX"] * 2


@pytest.mark.skipif(not HAS_PACK, reason="motion-pack music manifest not installed")
@pytest.mark.parametrize("D,loop", [(12.7, True), (32.0, True), (33.0, False), (39.28, False), (70.0, False)])
def test_beds_over_32_s_never_loop(D, loop):
    for mood in ("confident", "hype", "optimistic", "warm"):
        tl = NS(script=NS(music={"mood": mood, "auto": True}, style={}, title="Long test reel", base_dir=ROOT),
                duration=D)
        assert mixdown.pick_bed(tl)["loop"] is loop


@pytest.mark.skipif(not HAS_PACK, reason="motion-pack music manifest not installed")
@pytest.mark.parametrize("preset", DEMO4)
def test_long_reel_gets_a_non_loop_bed(preset):
    d, tl, _ = run(LONG, preset)
    assert tl.duration > mixdown.LOOP_MAX_S and "id" not in d.music       # the policy pins no loop bed
    bed = mixdown.plan_bed(tl)
    assert bed and bed["loop"] is False and bed["grid"]["roll_frames"] == 0
