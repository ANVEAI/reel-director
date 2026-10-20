"""Preview edit: POST /api/preview runs the directed reel with the takes so far and RECORD slots for
the rest, in the build worker, at review quality, to renders/preview.mp4. Tools are stubbed."""
import http.client
import json
import threading
import time
from pathlib import Path

import pytest

from reel_director.studio import runtime
from reel_director.studio.project import Project
from reel_director.studio.runtime import PREVIEW_LABEL, Studio
from reel_director.studio.server import StudioServer

SCRIPT = {"title": "t", "shots": [{"id": "hook", "line": "Most creators waste three hours."},
                                  {"id": "cta", "line": "Hit record."}]}


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "script.json").write_text(json.dumps(SCRIPT))
    return Project(tmp_path / "p", tmp_path / "script.json")


def _arg(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


class Tools:
    """Stands in for Studio._step: records each step, writes what the real tool would."""

    def __init__(self, render_gate: threading.Event | None = None, render_fails: bool = False):
        self.calls: list[tuple[str, list[str]]] = []
        self.gate, self.fails = render_gate, render_fails

    def __call__(self, step: str, cmd: list[str], logf) -> list[str]:
        self.calls.append((step, cmd))
        if step == "compile":
            out = Path(_arg(cmd, "--out"))
            out.mkdir(parents=True, exist_ok=True)
            recorded = "--takes" in cmd
            shots = [{"id": "hook", "take": 0 if recorded else None, "recorded": recorded,
                      "clips": [{}, {}] if recorded else [], "coverage": 1.0 if recorded else 0.0},
                     {"id": "cta", "take": None, "recorded": False, "clips": [], "coverage": 0.0}]
            (out / "timeline.json").write_text(json.dumps({"shots": shots}))
            return ["  hook  slot (not recorded)", "  director: preset clean-pro, 3 visual changes"]
        if step == "render":
            if self.gate:
                assert self.gate.wait(5)
            if self.fails:
                raise RuntimeError("render failed: Chrome crashed")
            Path(_arg(cmd, "-o")).write_bytes(b"fake mp4")
        return []

    def steps(self) -> list[str]:
        return [s for s, _ in self.calls]

    def cmd(self, step: str) -> list[str]:
        return next(c for s, c in self.calls if s == step)


@pytest.fixture
def studio(proj, monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: f"/opt/bin/{name}")
    monkeypatch.setattr(runtime, "_duration", lambda path: 12.5)
    st = Studio(proj)
    st._step = Tools()
    return st


def finish(st: Studio) -> dict:
    for _ in range(200):
        b = st.build_status()
        if b["state"] != "running":
            return b
        time.sleep(0.02)
    raise AssertionError("preview never finished")


def add_take(proj: Project, st: Studio, shot: str, status: str = "ready") -> str:
    name, path = proj.reserve(shot, "webm")
    path.write_bytes(b"video")
    proj.add(shot, name)
    proj.normalized(name).parent.mkdir(parents=True, exist_ok=True)
    proj.normalized(name).write_bytes(b"normalized")
    if status == "ready":
        proj.qa_file(name).parent.mkdir(parents=True, exist_ok=True)
        proj.qa_file(name).write_text(json.dumps({"take": name, "verdict": "great", "script": {"score": 95}}))
    st._set(name, status)
    return name


# --- runtime step ---------------------------------------------------------------------------

def test_preview_with_zero_takes_is_all_slots(proj, studio):
    code, body = studio.start_build(preview=True)
    assert code == 202 and body["kind"] == "preview"
    b = finish(studio)
    assert b["state"] == "done", b
    tools = studio._step
    assert tools.steps() == ["compile", "render"]          # nothing to prep
    comp = tools.cmd("compile")
    assert "--takes" not in comp and _arg(comp, "--preset") == "clean-pro"
    assert _arg(comp, "--out") == str(proj.root / "preview" / "reel")   # the build's reel/ is never touched
    render = tools.cmd("render")
    assert render[-2:] == ["--quality", "draft"] and Path(_arg(render, "-o")).parent == proj.root / "preview"
    r = b["result"]
    assert r["preview"] is True and r["label"] == PREVIEW_LABEL and r["video"] == "/media/renders/preview.mp4"
    assert [(s["id"], s["take"]) for s in r["shots"]] == [("hook", None), ("cta", None)] and r["slots"] == 2
    assert r["duration"] == 12.5 and r["director"] == ["director: preset clean-pro, 3 visual changes"]
    assert (proj.root / "renders" / "preview.mp4").read_bytes() == b"fake mp4"
    assert json.loads((proj.root / "renders" / "preview.json").read_text()) == r
    assert not (proj.root / "renders" / "reel-master.mp4").exists()
    assert not (proj.root / "build-takes.json").exists()


def test_preview_uses_recorded_takes_and_slots_the_rest(proj, studio):
    name = add_take(proj, studio, "hook")
    assert studio.start_build(preview=True)[0] == 202
    b = finish(studio)
    assert b["state"] == "done", b
    tools = studio._step
    assert tools.steps() == ["prep", "compile", "render"]
    prep = tools.cmd("prep")
    assert prep[prep.index("prep") + 1] == str(proj.root / "preview-takes.json")
    assert _arg(prep, "--out") == str(proj.root / "preview" / "prepped")
    assert list(json.loads((proj.root / "preview-takes.json").read_text())) == ["hook"]
    assert _arg(tools.cmd("compile"), "--takes") == str(proj.root / "preview" / "prepped" / "takes.json")
    shots = b["result"]["shots"]
    assert [(s["id"], s["take"], s["cuts"]) for s in shots] == [("hook", name, 1), ("cta", None, 0)]
    assert b["result"]["slots"] == 1


def test_preview_runs_while_takes_are_checked_and_leaves_them_out(proj, studio):
    add_take(proj, studio, "hook", status="checking")
    assert studio.start_build()[0] == 409                 # the real build waits for the check
    assert studio.start_build(preview=True)[0] == 202     # the preview doesn't
    assert finish(studio)["state"] == "done"
    assert studio._step.steps() == ["compile", "render"]


def test_preview_uses_the_chosen_preset(proj, studio):
    assert studio.set_preset("bold-hustle")[0] == 200
    studio.start_build(preview=True)
    assert finish(studio)["result"]["preset"] == "bold-hustle"
    assert _arg(studio._step.cmd("compile"), "--preset") == "bold-hustle"


def test_failed_render_reports_and_keeps_the_old_preview(proj, studio):
    (proj.root / "renders").mkdir()
    (proj.root / "renders" / "preview.mp4").write_bytes(b"old")
    studio._step = Tools(render_fails=True)
    studio.start_build(preview=True)
    b = finish(studio)
    assert b["state"] == "error" and "Chrome crashed" in b["error"] and b["kind"] == "preview"
    assert (proj.root / "renders" / "preview.mp4").read_bytes() == b"old"


# --- endpoint -------------------------------------------------------------------------------

@pytest.fixture
def server(studio):
    httpd = StudioServer(("127.0.0.1", 0), studio)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    studio.stop()


def call(httpd, method, path):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    c.request(method, path)
    r = c.getresponse()
    data = r.read()
    c.close()
    is_json = (r.getheader("Content-Type") or "").startswith("application/json")
    return r.status, json.loads(data) if is_json else data


def test_preview_endpoint_renders_and_serves(server, studio):
    code, body = call(server, "POST", "/api/preview")
    assert code == 202 and body["state"] == "running" and body["kind"] == "preview"
    assert finish(studio)["state"] == "done"
    code, b = call(server, "GET", "/api/build")
    assert code == 200 and b["kind"] == "preview" and b["result"]["slots"] == 2
    assert call(server, "GET", b["result"]["video"]) == (200, b"fake mp4")
    assert call(server, "GET", "/api/preview")[0] == 405


def test_preview_endpoint_409_while_a_build_runs(server, studio):
    gate = threading.Event()
    studio._step = Tools(render_gate=gate)
    try:
        assert call(server, "POST", "/api/preview")[0] == 202
        code, body = call(server, "POST", "/api/preview")
        assert code == 409 and "already running" in body["error"]
        assert call(server, "POST", "/api/build")[0] == 409
        assert call(server, "POST", "/api/preset?name=bold-hustle")[0] == 409
    finally:
        gate.set()
    assert finish(studio)["state"] == "done"
    assert call(server, "POST", "/api/preview")[0] == 202   # free again once it is done
    finish(studio)
