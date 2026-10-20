"""v2 integration: prep looks (face track + background matte), the QA/director fix overrides the layout honours,
the baked background picture, the review/fix-round loop, the Studio review step, options and creator profile."""
import json
import re
from pathlib import Path

import pytest

from reel_director import __main__ as cli
from reel_director import compiler, layout, pipeline, stage
from reel_director.compiler import compile_project
from reel_director.schema import parse_script
from reel_director.studio import runtime
from reel_director.studio.project import Project
from reel_director.studio.runtime import Studio, qa_view
from reel_director.timeline import Take, build_timeline
from test_layout import A, B, asr, face_doc

needs_pack = pytest.mark.skipif(not (stage.pack_root() / "transitions" / "aliases.json").exists(),
                                reason="motion-pack not installed")


def compile_with(tmp_path, meta_a=None, style=None, bg=False, out="out"):
    data = {"title": "Integrate", "style": style or {},
            "shots": [{"id": "a", "line": A, **(meta_a or {})}, {"id": "b", "line": B}]}
    s = parse_script(data, base_dir=tmp_path)
    (tmp_path / "prepped").mkdir(exist_ok=True)
    takes = {}
    for sid, line in (("a", A), ("b", B)):
        src = tmp_path / "prepped" / f"{sid}.mp4"
        src.write_bytes(b"")
        w = asr(line)
        dur = round(w[-1]["e"] + 2.0, 3)
        takes[sid] = [Take(src, w, dur)]
        (tmp_path / "prepped" / f"{sid}.face.json").write_text(json.dumps(face_doc(sid, dur)))
        if bg:
            (tmp_path / "prepped" / f"{sid}.bg.mp4").write_bytes(b"")
    tl = build_timeline(s, takes)
    orig = compiler.probe_size
    compiler.probe_size = lambda path: (1080, 1920)
    try:
        html = compile_project(tl, tmp_path / out).read_text()
    finally:
        compiler.probe_size = orig
    plan = json.loads(re.search(r'id="rd-plan">(.*?)</script>', html, re.S).group(1))
    return html, plan, json.loads((tmp_path / out / "layout.json").read_text())


# ---------------------------------------------------------------------------------------------- compile
@needs_pack
def test_baked_background_is_the_picture_only_when_the_look_treats_the_background(tmp_path):
    html, plan, _ = compile_with(tmp_path, style={"preset": "clean-pro"}, bg=True)
    assert html.count('data-bg="baked"') == 2 and 'src="assets/a.bg.mp4"' in html
    assert plan["look"]["bgfx"] and plan["preset"] == "clean-pro"
    off = {"preset": "clean-pro", "look": {"grain": 0.0, "vignette": 0.0, "grade": "none", "bgfx": False}}
    html2, plan2, _ = compile_with(tmp_path, style=off, bg=True, out="out2")
    assert 'data-bg="baked"' not in html2 and 'src="assets/a.mp4"' in html2 and plan2["look"]["bgfx"] is False


@needs_pack
def test_fix_overrides_reach_the_layout(tmp_path):
    _, _, base = compile_with(tmp_path, out="o0")
    zone0 = next(z for z in base["zones"] if z["shot"] == "a")["zone"]
    want = "lower-band" if zone0 != "lower-band" else "above-head"
    _, _, moved = compile_with(tmp_path, meta_a={"caption_zone": want}, out="o1")
    z = next(z for z in moved["zones"] if z["shot"] == "a")
    assert z["zone"] == want or z["zone"] == zone0           # tried first; kept off the face when it cannot fit
    rf0 = next(r for r in base["reframe"] if r["shot"] == "a")
    _, _, low = compile_with(tmp_path, meta_a={"reframe": {"eye_y": 0.43, "scale": 1.0}}, out="o2")
    rf = next(r for r in low["reframe"] if r["shot"] == "a")
    assert rf["scale"] == 1.0 and rf0["scale"] >= rf["scale"]
    html, _, _ = compile_with(tmp_path, meta_a={"cues": []}, style={"title_backdrop": "solid"}, out="o3")
    for m in re.finditer(r'class="clip title[^"]*"[^>]*data-params="([^"]*)"', html):
        assert '&quot;backing&quot;: &quot;solid&quot;' in m.group(1)


def test_layout_picture_needs_bgfx_and_the_baked_file(tmp_path):
    src = tmp_path / "hook-1.mp4"
    src.write_bytes(b"")
    lay = layout.Layout.__new__(layout.Layout)
    lay.style = {"look": {"bgfx": {"blur": 10, "dim": 0.8}}}
    assert lay.picture(src) == (src, False)
    (tmp_path / "hook-1.bg.mp4").write_bytes(b"")
    assert lay.picture(src) == (tmp_path / "hook-1.bg.mp4", True)
    lay.style = {"look": {"bgfx": False}}
    assert lay.picture(src) == (src, False)


def test_policy_counts_the_card_hold_like_the_compiler():
    from reel_director import policy
    from reel_director.schema import Cue

    class T:
        pass
    P = policy._Pass.__new__(policy._Pass)
    sh = T()
    sh.out_start, sh.duration = 0.0, 10.0
    P.tl = T()
    P.tl.shots = [sh]
    P.t = lambda si, wi, end=False: 2.0 if end else 1.0
    a, b = P.span(0, Cue("broll", 0, 0, {"hold": 0.5}))
    assert b == pytest.approx(2.5)
    assert P.span(0, Cue("broll", 0, 0, {}))[1] == pytest.approx(2.2)
    assert P.span(0, Cue("punch", 0, 0, {}))[1] == pytest.approx(2.0)


# ---------------------------------------------------------------------------------------------- CLI
def test_prep_looks_tracks_faces_and_bakes_the_matte_only_when_asked(tmp_path, monkeypatch):
    from reel_director import face, matte
    a, gone = tmp_path / "hook-1.mp4", tmp_path / "missing.mp4"
    a.write_bytes(b"x")
    seen = {"faces": [], "bg": []}
    monkeypatch.setattr(face, "prep_faces", lambda media, out: seen["faces"].append(list(media)))
    monkeypatch.setattr(matte, "treat_background", lambda m, o: seen["bg"].append(o) or {"blur": 10, "dim": 0.2})
    cli.prep_looks([a, gone], tmp_path, matte=False)
    assert seen == {"faces": [[a]], "bg": []}
    cli.prep_looks([a], tmp_path, matte=True)
    assert seen["bg"] == [tmp_path / "hook-1.bg.mp4"]

    def boom(media, out):
        raise RuntimeError("vision crashed")
    monkeypatch.setattr(face, "prep_faces", boom)
    cli.prep_looks([a], tmp_path, matte=False)              # never fails prep


def test_learn_subcommand_routes_to_learn(monkeypatch):
    from reel_director import learn
    got = []
    monkeypatch.setattr(learn, "main", lambda argv: got.append(argv) or 0)
    assert cli.main(["learn", "creator", "work/x"]) == 0 and got == [["creator", "work/x"]]


# ---------------------------------------------------------------------------------------------- review loop
def _fake_build(tmp_path):
    b = tmp_path / "build"
    (b / "reel").mkdir(parents=True)
    (b / "reel" / "timeline.json").write_text(json.dumps({"shots": [{"id": "hook"}]}))
    (b / "directed.json").write_text(json.dumps({"shots": [{"id": "hook", "cues": []}], "style": {}}))
    (b / "build-takes.json").write_text(json.dumps({"hook": [{"src": "raw/hook-1.mp4", "pin": False}]}))
    return b


def _gate(level, fix=None):
    return {"id": "text_over_face", "level": level, "value": 0, "target": 0, "message": "m", "fix": fix}


@pytest.mark.parametrize("improves", [True, False])
def test_review_build_keeps_a_fix_round_only_when_it_scores_better(tmp_path, monkeypatch, improves):
    from reel_director import qa, review
    b = _fake_build(tmp_path)
    fix = {"op": "move_caption", "args": {"zone": "above-head", "shots": ["hook"]}}

    def run_qa(build, out, master=None, director=None):
        first = Path(build) == b
        (Path(out) / "qa").mkdir(parents=True, exist_ok=True)
        (Path(out) / "renders").mkdir(parents=True, exist_ok=True)
        (Path(out) / "renders" / "reel-master.mp4").write_text("first" if first else "round")
        gates = [_gate("fail", fix)] if first or not improves else [_gate("ok")]
        g, s, v = qa.score(gates)
        return {"gates": gates, "gate_score": g, "score": s, "verdict": v, "before_after": "renders/before-after.png"}
    monkeypatch.setattr(qa, "run_qa", run_qa)
    monkeypatch.setattr(review, "run_director", lambda *a, **k: {"status": "skipped", "note": "no CLI", "issues": []})
    monkeypatch.setattr(pipeline, "build_fn", lambda script, out, takes, no_auto=False: {
        "index": Path(out) / "index.html", "mix": Path(out).parent / "mix" / "mix.wav"})
    monkeypatch.setattr(pipeline, "render", lambda reel, mp4, log=print: Path(mp4))
    import reel_director.audio as audio
    monkeypatch.setattr(audio, "deliver", lambda *a, **k: {"lufs": -14.0, "true_peak": -2.0, "ok": True})
    rep = pipeline.review_build(b, {"hook": []}, director=True, rounds=2, log=lambda *_: None)
    rd = b / "director" / "round-1"
    assert json.loads((rd / "directed.json").read_text())["shots"][0]["caption_zone"] == "above-head"
    assert json.loads((rd / "build-takes.json").read_text())["hook"][0]["src"] == "../../raw/hook-1.mp4"
    if improves:
        assert rep["final"] == "director/round-1" and rep["verdict"] == "ship"
        assert (b / "renders" / "reel-master.mp4").read_text() == "round"     # promoted
        assert rep["rounds"][0]["deliver"]["lufs"] == -14.0
    else:
        assert rep["final"] == "." and "did not improve" in rep["rounds"][0]["stopped"]
        assert (b / "renders" / "reel-master.mp4").read_text() == "first"
    assert json.loads((b / "qa" / "report.json").read_text())["final"] == rep["final"]


# ---------------------------------------------------------------------------------------------- studio
SCRIPT = {"title": "t", "shots": [{"id": "hook", "line": "Most creators waste three hours."}]}


@pytest.fixture
def studio(tmp_path, monkeypatch):
    (tmp_path / "script.json").write_text(json.dumps(SCRIPT))
    monkeypatch.setattr(runtime.shutil, "which", lambda name: f"/opt/bin/{name}")
    monkeypatch.setattr(runtime, "_duration", lambda path: 3.0)
    return Studio(Project(tmp_path / "p", tmp_path / "script.json"), check=lambda name: None)


def test_options_and_preset_share_the_settings_file(studio):
    assert studio.options() == {"director": False, "matte": True}      # the matte look is on by default
    assert studio.set_options({"director": "1", "matte": "0"}) == (200, {"director": True, "matte": False})
    assert studio.set_preset("bold-hustle")[0] == 200
    assert studio.options()["director"] and studio.preset() == "bold-hustle"
    assert studio.set_options({"bogus": "1"})[0] == 400
    assert studio.project_view()["options"] == {"director": True, "matte": False}


def test_creator_profile_endpoint_and_refresh_after_a_take_check(studio):
    assert studio.creator()["profile"] is None
    (studio.project.qa_dir / "creator.json").write_text(json.dumps({"coach": {"eye_target": 0.4}}))
    assert studio.creator()["profile"]["coach"]["eye_target"] == 0.4
    calls = []
    st = Studio(studio.project, check=lambda name: None, learn=lambda: calls.append(1))
    st.project.qa = lambda name: {"verdict": "great"}
    st._qa("hook-1")
    assert calls == [1] and st.status["hook-1"]["status"] == "ready"


def test_review_step_flags_and_qa_view(studio, tmp_path):
    calls = []
    studio._step = lambda step, cmd, logf: calls.append((step, cmd)) or []
    root = studio.project.root
    assert studio._review(None, False) is None and calls[-1][1][-2:] == ["review", str(root)]
    studio._review(None, True)
    assert calls[-1][1][-5:] == ["--director", "--rounds", "2", "--takes", str(root / "prepped" / "takes.json")]
    (root / "renders").mkdir(exist_ok=True)
    (root / "renders" / "before-after.png").write_bytes(b"png")
    rep = {"verdict": "ship", "score": 90, "gate_score": 85, "final": "director/round-1",
           "gates": [{"id": "pace", "level": "warn", "message": "m", "value": 1, "fix": None}],
           "director": {"status": "ok", "score": 95, "summary": "good", "issues": []},
           "rounds": [{"round": 1, "dir": "director/round-1", "score_before": 80, "score_after": 90,
                       "deliver": {"lufs": -14.1, "true_peak": -2.0, "av_start_offset_ms": 0.0}}]}
    (root / "qa" / "report.json").write_text(json.dumps(rep))
    v = qa_view(root)
    assert v["verdict"] == "ship" and v["gates"] == [{"id": "pace", "level": "warn", "message": "m"}]
    assert v["before_after"].startswith("/media/renders/before-after.png?v=") and v["deliver"]["lufs"] == -14.1
    studio._step = lambda step, cmd, logf: (_ for _ in ()).throw(RuntimeError("qa crashed"))
    assert studio._review(None, False) == {"error": "qa crashed"}


# ---------------------------------------------------------------------------------------------- split cards
def _directed_with_tail_list(tmp_path, faces: bool):
    from reel_director import policy
    data = {"title": "Split", "style": {"preset": "bold-hustle"},
            "shots": [{"id": "a", "line": A}, {"id": "b", "line": B, "cues": [
                {"type": "broll", "at": "before", "until": "pressed", "kind": "list", "items": ["READ", "RECORD"],
                 "layout": "full", "auto": True}]}]}
    s = parse_script(policy.prepare(data), base_dir=tmp_path)
    (tmp_path / "prepped").mkdir(parents=True, exist_ok=True)
    takes = {}
    for sid, line in (("a", A), ("b", B)):
        src = tmp_path / "prepped" / f"{sid}.mp4"
        src.write_bytes(b"")
        w = asr(line)
        dur = round(w[-1]["e"] + 1.0, 3)
        takes[sid] = [Take(src, w, dur)]
        if faces:
            (tmp_path / "prepped" / f"{sid}.face.json").write_text(json.dumps(face_doc(sid, dur)))
    tl = build_timeline(s, takes)
    notes: list[str] = []
    return policy.enforce(s, tl, notes), notes


def test_a_list_card_the_face_rules_would_drop_goes_split_when_the_face_is_tracked(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "probe_size", lambda path: (1080, 1920))
    d, notes = _directed_with_tail_list(tmp_path, faces=True)
    card = next(c for c in d.shots[1].cues if c.type == "broll")
    assert card.params["layout"] == "split" and any("goes split" in n for n in notes)
    d2, notes2 = _directed_with_tail_list(tmp_path / "noface", faces=False)
    assert not [c for c in d2.shots[1].cues if c.type == "broll"]
    assert any("face on screen for the last" in n for n in notes2)


def test_qa_counts_split_cards_as_changes_and_skips_them_for_framing():
    from reel_director import qa
    vid = [{"id": "take-a-0", "src": "a.mp4", "start": 0.0, "duration": 6.0, "media_start": 0.0}]
    b = {"plan": {"fps": 30, "D": 6.0, "segs": []}, "videos": vid, "style": {"pace": "standard"},
         "layout": {"cards": [{"id": "broll-1", "t0": 2.0, "t1": 4.0, "layout": "split"}],
                    "reframe": [{"shot": "a", "eye_y_before": 0.53}]},
         "tl": {"shots": [{"id": "a", "start": 0.0, "duration": 6.0}]}}
    assert [k for _, k in qa.plan_changes(b)] == ["card", "card-out"]
    low = {"box": [380, 1200, 320, 380], "eyes": [[470, 1400], [610, 1400]], "mouth": [540, 1540], "chin_y": 1600}
    mid = {"box": [380, 900, 320, 380], "eyes": [[470, 1000], [610, 1000]], "mouth": [540, 1140], "chin_y": 1200}
    ts = [k * 0.5 for k in range(12)]
    faces = [low if 2.0 <= t < 4.0 else mid for t in ts]                  # the split pane's face is not the framing
    g = qa.gate_broll_face(b, ts, faces)[1]
    assert g["value"]["a"]["eye_y"] == pytest.approx(1000 / 1920, abs=1e-3)
    assert g["value"]["a"]["reachable_eye_y"] < 0.5 and g["level"] == "warn" and "lower" in g["message"]
