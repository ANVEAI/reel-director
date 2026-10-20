"""Council v1 policy (integrator): caps on the director's auto cues, the build pipeline and the CLI."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from reel_director import broll_media, director, pipeline, policy
from reel_director.schema import ScriptError, parse_script, script_to_dict
from reel_director.timeline import build_timeline

ROOT = Path(__file__).resolve().parents[1]
LINES = ROOT / "examples" / "demo" / "script-lines-only.json"
LONG = {
    "title": "Long reel", "style": {"preset": "bold-hustle"},
    "shots": [
        {"id": "hook", "line": "I made $40,000 last month with one simple trick."},
        {"id": "a", "line": "First, I stopped editing every single reel by hand."},
        {"id": "b", "line": "Second, I wrote the script before I ever pressed record."},
        {"id": "c", "line": "Third, I let the tool cut my pauses, my ums and my restarts."},
        {"id": "d", "line": "That saved me three hours a day, every single day this year."},
        {"id": "e", "line": "Now I post twice a day and my views went up ten times."},
        {"id": "cta", "line": "Follow for the full setup and save this for later."},
    ],
}


def directed(data: dict, preset: str | None = None):
    s = parse_script(policy.prepare(data, preset))
    notes: list[str] = []
    d = pipeline.direct(s, None, notes=notes)
    return d, build_timeline(d), notes


def autos(d, kind):
    return [(sh.id, c) for sh in d.shots for c in sh.cues if c.type == kind and c.params.get("auto")]


@pytest.mark.parametrize("preset", ["bold-hustle", "clean-pro", "beast-hype", "desi-bilingual", "editorial", "tech-explainer"])
def test_council_caps_hold_for_every_preset(preset):
    d, tl, notes = directed(LONG, preset)
    m = policy.metrics(d, tl)
    pace = policy.PACE[d.style["pace"]]
    assert not autos(d, "zoom") and not autos(d, "endcard")            # no auto zoom; endcard opt-in
    # v4 contract: real media counts toward the case-study band (recipe cap, <= 40 %); cards keep the council's cap
    assert m["broll_share"] <= max(pace["broll"], broll_media.recipe(d.style)["share"][1]) + 1e-6
    assert m["hard_cut_share"] >= 0.9
    assert m["first_change_s"] is not None and m["first_change_s"] <= 1.0
    assert m["max_static_s"] <= pace["max_static"] + 1e-6
    br = autos(d, "broll")
    assert all(c.params.get("layout", "full") == "full" and c.params["kind"] in ("text", "stat", "list")
               for _, c in br if c.params["kind"] != "media")
    assert all(c.params["layout"] in ("full", "split", "pip", "inset") for _, c in br if c.params["kind"] == "media")
    assert sum(1 for _, c in br if c.params["kind"] == "stat") <= 1
    sfx = sorted(policy._Pass(d, tl, []).t(si, c.start_word) for si, sh in enumerate(d.shots) for c in sh.cues if c.type == "sfx")
    assert all(b - a >= 1.0 - 1e-6 for a, b in zip(sfx, sfx[1:]))
    assert len(sfx) <= max(1, int(pace["sfx30"] * tl.duration / 30))
    assert all(sid in policy.SFX_IDS.values() or sid.startswith("snd.hit.") for sid in
               (c.params["id"] for _, c in autos(d, "sfx")))
    tx = autos(d, "transition")
    assert all(c.params["id"] == policy.TX_FAMILY[preset] and c.params["ms"] == 300 for _, c in tx)
    if d.style["pace"] == "calm":
        assert not tx


def test_punches_open_at_M_change_every_time_and_end_on_M():
    d, tl, _ = directed(LONG, "bold-hustle")
    m = policy.metrics(d, tl)
    levels = [lv for _, lv, _ in m["punches"]]
    assert m["punches"][0][1] == "M" and m["punches"][0][2] == 0.0       # frame 0 at M
    assert levels[-1] == "M"                                             # loop: last frame = frame 0
    assert sum(1 for lv in levels if lv == "T") <= 1
    per_shot: dict[str, list[str]] = {}
    for sid, lv, _ in m["punches"]:
        per_shot.setdefault(sid, []).append(lv)
    for sid, lv in per_shot.items():
        prev = "M" if sid == "hook" else "W"
        for x in (lv[1:] if sid == "hook" else lv):
            assert x != prev, (sid, lv)
            prev = x
    first = [t for sid, lv, t in m["punches"] if t > 0]
    assert 0.5 <= first[0] <= 1.0


def test_hook_title_is_4_to_6_words_and_alone_on_screen():
    d, tl, _ = directed(json.loads(LINES.read_text()), "bold-hustle")
    (_, t), = autos(d, "title")
    assert 4 <= len(t.params["text"].split()) <= 6
    assert not [c for _, c in autos(d, "overlay") if tl.shots[0].words[c.start_word].start < policy.TITLE_UNTIL]


def test_manual_cues_are_never_touched():
    data = json.loads(LINES.read_text())
    data["shots"][1]["cues"] = [{"type": "transition", "at": "What", "id": "flash"},
                               {"type": "sfx", "at": "edit", "id": "snd.ui.pop"},
                               {"type": "zoom", "at": "finished", "scale": 1.12}]
    d, _, _ = directed(data, "clean-pro")
    manual = [c for c in d.shots[1].cues if not c.params.get("auto")]
    assert [(c.type, c.params.get("id")) for c in manual] == [("transition", "flash"), ("sfx", "snd.ui.pop"), ("zoom", None)]


def test_unknown_auto_sfx_id_fails_and_endcard_opt_in_works():
    data = json.loads(LINES.read_text())
    data["style"] = {"preset": "clean-pro", "endcard": True}
    d, _, _ = directed(data)
    assert autos(d, "endcard")
    bad = parse_script(policy.prepare(json.loads(LINES.read_text())))
    bad.shots[0].cues.append(director.Cue("sfx", 1, 1, {"id": "snd.ui.ding", "auto": True, "role": "pop"}))
    p = policy._Pass(bad, build_timeline(bad), [])
    p.s.shots[0].cues[-1].params["role"] = "other"
    with pytest.raises(ScriptError, match="snd.ui.ding"):
        p.validate()


def test_prepare_defaults_and_preset_patch():
    d = policy.prepare({"shots": []})
    assert d["style"]["preset"] == "clean-pro" and d["style"]["progress"] is False
    h = policy.prepare({"style": {"preset": "editorial"}}, "bold-hustle")["style"]
    assert h["preset"] == "bold-hustle" and h["accent"] == "#FFE14D" and h["look"]["grain"] <= 0.08
    e = parse_script(policy.prepare({"shots": [{"id": "a", "line": "hi there"}]}, "editorial"))
    assert e.style["look"]["vignette"] <= 0.18 and e.style["caption"] == "boxed"
    own = policy.prepare({"style": {"preset": "bold-hustle", "accent": "#123456"}})
    assert own["style"]["accent"] == "#123456"                           # the script's own keys win


def test_auto_off_and_skip_shots():
    data = json.loads(LINES.read_text())
    data["style"] = {"auto_off": True}
    d, _, notes = directed(data)
    assert not any(c.params.get("auto") for sh in d.shots for c in sh.cues) and "director off" in notes[0]
    data["style"] = {"auto_skip_shots": ["turn"]}
    d, _, _ = directed(data)
    assert not any(c.params.get("auto") for c in d.shots[1].cues)
    assert any(c.params.get("auto") for c in d.shots[0].cues)
    data["style"] = {"auto_skip_shots": ["nope"]}
    with pytest.raises(ScriptError, match="nope"):
        directed(data)


def test_deterministic_and_round_trips():
    a, _, _ = directed(LONG, "beast-hype")
    b, _, _ = directed(LONG, "beast-hype")
    ja, jb = json.dumps(script_to_dict(a), sort_keys=True), json.dumps(script_to_dict(b), sort_keys=True)
    assert ja == jb
    again = parse_script(json.loads(ja))
    assert [[(c.type, c.start_word, c.end_word) for c in sh.cues] for sh in again.shots] == \
           [[(c.type, c.start_word, c.end_word) for c in sh.cues] for sh in a.shots]


def test_cli_direct_and_compile_write_directed_json_never_script(tmp_path):
    before = LINES.read_text()
    out = tmp_path / "d.json"
    r = subprocess.run([sys.executable, "-m", "reel_director", "direct", str(LINES), "--out", str(out),
                        "--preset", "beast-hype"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text())
    assert d["style"]["preset"] == "beast-hype" and any(c.get("auto") for sh in d["shots"] for c in sh["cues"])
    r = subprocess.run([sys.executable, "-m", "reel_director", "compile", str(LINES), "--out", str(tmp_path / "reel"),
                        "--preset", "clean-pro", "--no-auto"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "reel" / "index.html").exists() and (tmp_path / "directed.json").exists()
    assert not any(c.get("auto") for sh in json.loads((tmp_path / "directed.json").read_text())["shots"] for c in sh["cues"])
    assert LINES.read_text() == before


def _code(js: str) -> str:
    import re
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)(^|[^:'\"])//.*$", r"\1", js)


def test_page_js_is_seek_safe_grep():
    """Council gate: no clock or randomness in anything the page runs (runtime, page, staged pack modules)."""
    import re
    from reel_director import stage
    files = [stage.WEB / "reel.mjs", stage.WEB / "page.html"]
    root = stage.pack_root()
    if (root / stage.ENTRIES[0]).exists():
        files += [root / rel for rel in stage.import_closure(root)]
    bad = re.compile(r"Math\.random\s*\(|Date\.now\s*\(|new\s+Date\s*\(|performance\.now\s*\(|requestAnimationFrame\s*\(")
    hits = [f"{f.name}: {m.group(0)}" for f in files for m in bad.finditer(_code(f.read_text()))]
    assert len(files) >= 3 and not hits, hits


def test_devanagari_line_fails_loudly_instead_of_dropping_words(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"shots": [{"id": "a", "line": "Yeh reel sirf पाँच मिनट mein banti hai."}]}, ensure_ascii=False))
    with pytest.raises(ScriptError, match="पाँच"):
        pipeline.load(f, "desi-bilingual")
    assert len(parse_script({"shots": [{"id": "a", "line": "Yeh reel sirf पाँच मिनट mein banti hai."}]}).shots[0].words) == 6


def test_two_changes_by_three_seconds_on_estimated_times():
    for preset in ("clean-pro", "editorial", "desi-bilingual"):
        d, tl, _ = directed(LONG, preset)
        assert policy.metrics(d, tl)["changes_by_3s"] >= 2, preset
