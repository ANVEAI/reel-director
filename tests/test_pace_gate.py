"""v2 contract P3: the pace gate is enforced. A metronomic or out-of-range plan is re-planned (auto punches
moved / added / dropped, deterministic) before compile; what cannot be fixed is a hard 'fail'."""
import copy
import json
from pathlib import Path

import pytest

from reel_director import pace, pipeline, policy
from reel_director.schema import Cue, parse_script
from reel_director.timeline import build_timeline

ROOT = Path(__file__).resolve().parents[1]
LINE = ("We tested every single editing trick for a whole month and most of them simply wasted our time, "
        "so here is the one habit that actually made the difference for us.")
EVEN = (2, 6, 11, 15, 19, 24, 28)        # auto punches ~1.5 s apart on the estimated word times: CV 0.06


def metronomic(pace_name="standard", auto=True):
    data = {"title": "t", "style": {"preset": "clean-pro", "pace": pace_name}, "shots": [{"id": "a", "line": LINE}]}
    s = parse_script(policy.prepare(data))
    s.shots[0].cues += [Cue("punch", 0, 0, {"level": "M", "open": True, "auto": auto})]
    s.shots[0].cues += [Cue("punch", i, i, {"level": "W", "auto": auto}) for i in EVEN]
    return s, build_timeline(s)


@pytest.mark.parametrize("pace_name", ["standard", "punchy"])
def test_metronomic_plan_is_replanned_until_the_gate_passes(pace_name):
    s, tl = metronomic(pace_name)
    notes: list[str] = []
    P = policy._Pass(s, tl, notes)
    before = pace.gate_of(P)
    assert before["level"] == "fail" and before["value"]["cv"] < pace.CV_FAIL
    after = pace.replan(P)
    ch = P.changes()
    gaps = pace.gaps_between(ch)
    lo, hi = pace.MEDIAN_RANGE[pace_name]
    assert after["level"] != "fail" and pace.pace_cv(ch) >= pace.CV_FAIL and lo <= after["value"]["median_gap_s"] <= hi
    # the council's hard rules survive the re-plan: max static, first change <= 1.0 s, >= 2 changes by 3 s
    ends = [b - a for a, b in zip([0.0] + ch, ch + [tl.duration])]
    assert max(ends) <= policy.PACE[pace_name]["max_static"] + 1e-6
    assert ch[0] <= 1.0 + 1e-6 and sum(1 for t in ch if t <= 3.0) >= 2
    assert min(gaps) >= pace.MIN_SEP - 1e-6
    assert any("pace re-plan" in n for n in notes) and notes[-1].startswith("pace gate: OK")


def test_replan_is_deterministic():
    runs = []
    for _ in range(2):
        s, tl = metronomic()
        P = policy._Pass(copy.deepcopy(s), tl, [])
        pace.replan(P)
        runs.append([(c.type, c.start_word, c.params.get("level")) for sh in P.s.shots for c in sh.cues])
    assert runs[0] == runs[1]


def test_unfixable_rhythm_is_a_hard_fail_in_metrics_and_notes():
    s, tl = metronomic(auto=False)               # manual punches, and no auto punches allowed in the shot
    s.shots[0].meta = {"auto": {"punch": False}}
    notes: list[str] = []
    P = policy._Pass(s, tl, notes)
    g = pace.replan(P)
    assert g["level"] == "fail" and g["fix"] and "metronomic" in g["message"]
    assert notes[-1].startswith("pace gate: FAIL")
    m = pace.metrics(s, tl)
    assert m["pace_gate"]["level"] == "fail" and m["pace_gate"]["id"] == "pace"
    assert set(m["pace_gate"]) >= {"id", "level", "value", "target", "message", "fix"}     # QA report gate format


def test_a_passing_plan_is_left_alone():
    s, tl = metronomic()
    for c in [c for c in s.shots[0].cues if c.type == "punch" and not c.params.get("open")]:
        s.shots[0].cues.remove(c)
    s.shots[0].cues += [Cue("punch", i, i, {"level": "W", "auto": True}) for i in (2, 5, 13, 19, 26)]
    tl = build_timeline(s)
    notes: list[str] = []
    P = policy._Pass(s, tl, notes)
    assert pace.gate_of(P)["level"] != "fail"
    before = [(c.start_word, c.params.get("level")) for c in P.s.shots[0].cues]
    pace.replan(P)
    assert [(c.start_word, c.params.get("level")) for c in P.s.shots[0].cues] == before and notes == []


def test_short_reels_are_not_judged_on_rhythm():
    s, tl = metronomic()
    s.shots[0].cues = [c for c in s.shots[0].cues if c.start_word in (0, 2, 6)]
    P = policy._Pass(s, build_timeline(s), [])
    assert pace.gate_of(P)["level"] == "ok" and "too few" in pace.gate_of(P)["message"]


REAL = ROOT / "work" / "real-1" / "prepped" / "takes.json"


@pytest.mark.skipif(not REAL.exists(), reason="real-1 takes not on this machine")
def test_real_founder_takes_lose_the_metronome():
    """work/real-1 (bold-hustle): v1 shipped CV 0.20 with only a log note; the gate now re-plans it."""
    from reel_director.__main__ import load_takes
    takes = load_takes(REAL)
    notes: list[str] = []
    s = pipeline.load(ROOT / "examples" / "demo" / "script-lines-only.json", "bold-hustle")
    s.style["media"] = False          # the v1 card plan this gate re-plans (v4 media B-roll changes its rhythm)
    d = pipeline.direct(s, takes, notes=notes)
    m = policy.metrics(d, build_timeline(d, takes))
    assert m["cv"] >= pace.CV_TARGET and m["pace_gate"]["level"] == "ok", json.dumps(m["pace_gate"])
    assert any(n.startswith("pace gate: OK after re-plan") for n in notes)
