"""Editing director: CLI invocation contract (Read-only tool, JSON schema, timeout, graceful skips), answer
validation, whitelisted fix application and the bounded 2-round loop. The CLI is always faked here."""
import json
import subprocess
from pathlib import Path

import pytest

from reel_director import review
from reel_director.qa import OPS

DIRECTED = {"style": {"pace": "punchy", "caption": "bold", "look": {"grade": "none", "grain": 0.04}},
            "shots": [{"id": "hook", "cues": [{"type": "punch", "at": "waste", "auto": True},
                                              {"type": "title", "at": "Most", "text": "3 HOURS"}]},
                      {"id": "turn", "cues": [{"type": "broll", "at": "edit was finished", "auto": True}]}]}
REPORT = {"gates": [{"id": "text_over_face", "level": "fail", "value": None, "target": "0", "message": "text on face",
                     "fix": {"op": "move_caption", "args": {"zone": "below-chin", "shots": ["hook"]}}},
                    {"id": "loudness", "level": "ok", "value": None, "target": "", "message": "ok", "fix": None}],
          "gate_score": 80, "score": 80, "verdict": "fix"}
ANSWER = {"score": 48, "summary": "captions sit on the mouth", "issues": [
    {"severity": "high", "what": "caption over the mouth", "where_t": 1.3,
     "fix": {"op": "move_caption", "args": {"zone": "below-chin", "shots": ["hook", "turn"]}}},
    {"severity": "medium", "what": "flat black card", "where_t": 4.8,
     "fix": {"op": "change_preset_param", "args": {"param": "background", "value": "blur"}}},
    {"severity": "low", "what": "poster behind", "where_t": None, "fix": {"op": "delete_everything", "args": {}}}]}


class Run:
    """A fake subprocess.run recording the call."""
    def __init__(self, stdout="", code=0, exc=None):
        self.stdout, self.code, self.exc, self.calls = stdout, code, exc, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.code, self.stdout, "")


def result(**kw) -> str:
    return json.dumps({"type": "result", "is_error": False, "num_turns": 4, "total_cost_usd": 0.1, **kw})


def test_cli_call_is_read_only_schema_bound_and_sends_only_paths(tmp_path):
    (tmp_path / "renders").mkdir()
    (tmp_path / "qa").mkdir()
    (tmp_path / "renders" / "before-after.png").write_bytes(b"png")
    (tmp_path / "qa" / "report.json").write_text('{"marker": "ZZ-FILE-CONTENT"}')
    run = Run(result(structured_output=ANSWER))
    d = review.run_director(tmp_path, REPORT, ["hook", "turn"], claude="/bin/claude", timeout=12, runner=run)
    cmd, kw = run.calls[0]
    assert cmd[:2] == ["/bin/claude", "-p"] and kw["timeout"] == 12 and kw["cwd"] == str(tmp_path)
    for flag, val in (("--output-format", "json"), ("--tools", "Read"), ("--allowedTools", "Read"),
                      ("--permission-mode", "dontAsk")):
        assert cmd[cmd.index(flag) + 1] == val
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == review.SCHEMA and "--safe-mode" in cmd
    prompt = cmd[2]
    assert str(tmp_path / "renders" / "before-after.png") in prompt and str(tmp_path / "qa" / "report.json") in prompt
    assert "ZZ-FILE-CONTENT" not in prompt                 # paths only: the CLI reads the files itself
    assert "Shot ids: hook, turn" in prompt and "text_over_face: fail" in prompt
    assert d["status"] == "ok" and d["score"] == 48 and d["source"] == "claude-cli"
    assert [i["fix"]["op"] for i in d["issues"]] == ["move_caption", "change_preset_param"]
    assert len(d["dropped"]) == 1                          # op outside the whitelist never reaches apply_fixes


@pytest.mark.parametrize("run,note", [
    (Run(exc=subprocess.TimeoutExpired("claude", 5)), "timed out"),
    (Run(exc=FileNotFoundError("claude")), "failed to start"),
    (Run("not json", code=1), "no JSON"),
    (Run(result(is_error=True, result="Failed to authenticate: OAuth session expired")), "claude auth login"),
    (Run(result(structured_output={"score": "high"})), "failed the schema"),
])
def test_every_failure_is_a_graceful_skip(tmp_path, run, note):
    d = review.run_director(tmp_path, REPORT, ["hook"], claude="claude", runner=run)
    assert d["status"] == "skipped" and note in d["note"] and d["issues"] == []


def test_missing_cli_skips_and_text_answers_are_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(review.shutil, "which", lambda _: None)
    assert "not installed" in review.run_director(tmp_path, REPORT, ["hook"])["note"]
    run = Run(result(result="Here you go:\n" + json.dumps(ANSWER)))
    assert review.run_director(tmp_path, REPORT, ["hook"], claude="claude", runner=run)["score"] == 48


def test_cli_env_drops_the_host_session_but_keeps_user_auth(monkeypatch):
    for k, v in (("CLAUDECODE", "1"), ("CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "1"), ("CLAUDE_CODE_ENTRYPOINT", "x"),
                 ("CLAUDE_CODE_OAUTH_TOKEN", "tok"), ("HOME", "/home/x"), ("USE_LOCAL_OAUTH", "")):
        monkeypatch.setenv(k, v)
    env = review.cli_env()
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH" not in env and "USE_LOCAL_OAUTH" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok" and env["HOME"] == "/home/x"


def test_validate_clamps_and_normalises():
    d = review.validate({"score": 140.4, "issues": [{"severity": "urgent", "what": "x" * 900, "where_t": "soon",
                                                     "fix": {"op": "reframe", "args": {"eye_y": 0.4}}}]})
    assert d["score"] == 100 and d["issues"][0]["severity"] == "medium" and d["issues"][0]["where_t"] is None
    assert len(d["issues"][0]["what"]) == 400 and review.validate(None)["status"] == "skipped"
    assert set(review.SCHEMA["properties"]["issues"]["items"]["properties"]["fix"]["properties"]["op"]["enum"]) == set(OPS)


def test_apply_fixes_whitelist_only_on_a_copy():
    fixes = [{"op": "move_caption", "args": {"zone": "below-chin", "shots": ["hook"]}},
             {"op": "move_caption", "args": {"zone": "below-chin", "shots": ["hook"]}},          # duplicate: once
             {"op": "reframe", "args": {"shots": ["hook", "turn"], "eye_y": 0.4, "scale": 1.05}},
             {"op": "drop_cue", "args": {"shot": "hook", "type": "punch", "at": "Waste,"}},
             {"op": "change_preset_param", "args": {"param": "look.grade", "value": "warm"}},
             {"op": "change_preset_param", "args": {"param": "title_backdrop", "value": "solid"}},
             {"op": "retake", "args": {"shot": "turn", "reason": "poster behind the head"}}]
    new, applied, rejected, human = review.apply_fixes(DIRECTED, fixes)
    assert len(applied) == 5 and rejected == [] and human == [{"shot": "turn", "reason": "poster behind the head"}]
    hook, turn = new["shots"]
    assert hook["caption_zone"] == "below-chin" and "caption_zone" not in turn
    assert hook["reframe"] == turn["reframe"] == {"eye_y": 0.4, "scale": 1.05}
    assert [c["type"] for c in hook["cues"]] == ["title"]
    assert new["style"]["look"] == {"grade": "warm", "grain": 0.04} and new["style"]["title_backdrop"] == "solid"
    assert DIRECTED["shots"][0]["cues"][0]["type"] == "punch" and "caption_zone" not in DIRECTED["shots"][0]


@pytest.mark.parametrize("fix,why", [
    ({"op": "drop_cue", "args": {"shot": "hook", "type": "title", "at": "Most"}}, "manual cue"),
    ({"op": "drop_cue", "args": {"shot": "hook", "type": "punch", "at": "nope"}}, "no such cue"),
    ({"op": "move_caption", "args": {"zone": "on-the-nose"}}, "zone must be"),
    ({"op": "move_caption", "args": {"zone": "below-chin", "shots": ["ghost"]}}, "unknown shot"),
    ({"op": "reframe", "args": {"eye_y": 0.30}}, "eye_y"),
    ({"op": "reframe", "args": {"eye_y": 0.40, "scale": 1.5}}, "scale"),
    ({"op": "change_preset_param", "args": {"param": "look.grain", "value": 0.5}}, "not allowed"),
    ({"op": "change_preset_param", "args": {"param": "font", "value": "Comic Sans"}}, "not allowed"),
    ({"op": "change_preset_param", "args": {"param": "accent", "value": "red"}}, "not allowed"),
    ({"op": "rm", "args": {}}, "not whitelisted"),
])
def test_apply_fixes_rejects_anything_else(fix, why):
    new, applied, rejected, _ = review.apply_fixes(DIRECTED, [fix])
    assert applied == [] and why in rejected[0][1] and new == DIRECTED


def report_with(score_):
    return {**REPORT, "gates": [{**REPORT["gates"][1]}], "gate_score": score_, "score": score_}


def test_director_loop_is_bounded_and_keeps_the_better_build():
    scores = iter([60, 70, 90, 95])
    rebuilds = []
    out = review.director_loop(DIRECTED, report_with(100), lambda d: rebuilds.append(d) or report_with(100),
                               lambda r: {**review.validate(ANSWER), "score": next(scores)}, max_rounds=5)
    assert len(rebuilds) == 2 and len(out["rounds"]) == 2                  # never more than 2 rebuilds
    assert out["report"]["score"] == 95 and out["directed"]["shots"][0]["caption_zone"] == "below-chin"


def test_director_loop_stops_when_the_score_drops_or_the_director_is_skipped():
    scores = iter([70, 60])
    out = review.director_loop(DIRECTED, report_with(100), lambda d: report_with(100),
                               lambda r: {**review.validate(ANSWER), "score": next(scores)})
    assert out["report"]["score"] == 85 and out["directed"] is DIRECTED and "did not improve" in out["rounds"][0]["stopped"]
    out = review.director_loop(DIRECTED, report_with(100), lambda d: pytest.fail("no rebuild"),
                               lambda r: review._skip("claude CLI not installed"))
    assert out["rounds"] == [{"round": 1, "stopped": "claude CLI not installed"}]


def test_gate_fixes_apply_without_a_director():
    out = review.director_loop(DIRECTED, REPORT, lambda d: report_with(100), lambda r: review._skip("off"))
    assert out["rounds"][0]["applied"] == [REPORT["gates"][0]["fix"]] and out["report"]["score"] == 100


def test_main_writes_outputs_next_to_the_build_never_into_it(tmp_path, monkeypatch):
    b, out = tmp_path / "build", tmp_path / "out"
    (b / "reel").mkdir(parents=True)
    (b / "reel" / "timeline.json").write_text(json.dumps({"shots": [{"id": "hook"}, {"id": "turn"}]}))
    (b / "directed.json").write_text(json.dumps(DIRECTED))
    ans = tmp_path / "answer.json"
    ans.write_text(json.dumps(ANSWER))

    def fake_qa(build, o):
        (Path(o) / "qa").mkdir(parents=True, exist_ok=True)
        return dict(REPORT)
    monkeypatch.setattr(review, "run_qa", fake_qa)
    assert review.main([str(b), "--out", str(out), "--director-json", str(ans), "--apply"]) == 1
    rep = json.loads((out / "qa" / "report.json").read_text())
    assert rep["director"]["score"] == 48 and rep["score"] == round((80 + 48) / 2) and rep["verdict"] == "fix"
    fixed = json.loads((out / "directed.fixed.json").read_text())
    assert fixed["style"]["background"] == "blur" and fixed["shots"][1]["caption_zone"] == "below-chin"
    assert sorted(p.name for p in b.iterdir()) == ["directed.json", "reel"]


def test_first_fix_owns_a_field_and_compatible_fixes_merge():
    fixes = [{"op": "move_caption", "args": {"zones": {"hook": "lower-band", "turn": "below-chin"}}},   # measured
             {"op": "reframe", "args": {"shots": ["hook"], "eye_y": 0.40}},
             {"op": "move_caption", "args": {"zone": "below-chin", "shots": ["hook"]}},              # director
             {"op": "reframe", "args": {"shots": ["hook"], "eye_y": 0.40, "scale": 1.1}},
             {"op": "reframe", "args": {"shots": ["hook"], "eye_y": 0.38}}]
    new, applied, rejected, _ = review.apply_fixes(DIRECTED, fixes)
    assert [f["op"] for f in applied] == ["move_caption", "reframe", "reframe"]
    assert [r[1] for r in rejected] == ["conflicts with an earlier fix on hook.caption_zone",
                                        "conflicts with an earlier fix on hook.reframe.eye_y"]
    assert new["shots"][0]["caption_zone"] == "lower-band" and new["shots"][1]["caption_zone"] == "below-chin"
    assert new["shots"][0]["reframe"] == {"eye_y": 0.4, "scale": 1.1}
