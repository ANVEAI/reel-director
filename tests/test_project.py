import http.client
import json
import shutil
import threading
import time

import pytest

from reel_director.studio.project import Project, ProjectError, best_take, build_candidates
from reel_director.studio.runtime import Studio
from reel_director.studio.server import RangeNotSatisfiable, StudioServer, contained, parse_range, safe_parts

SCRIPT = {"title": "t", "shots": [{"id": "hook", "line": "Most creators waste three hours.",
                                   "cues": [{"type": "overlay", "at": "three hours", "text": "3 HRS"}]},
                                  {"id": "cta", "line": "Hit record."}]}


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "script.json").write_text(json.dumps(SCRIPT))
    return Project(tmp_path / "p", tmp_path / "script.json")


def upload(p: Project, shot: str, data: bytes = b"video") -> str:
    name, path = p.reserve(shot, "webm")
    path.write_bytes(data)
    p.add(shot, name)
    return name


# --- project ------------------------------------------------------------------------------

def test_project_records_its_script_and_refuses_another(proj, tmp_path):
    meta = json.loads((proj.root / "project.json").read_text())
    assert meta == {"script": str((tmp_path / "script.json").resolve())}
    assert Project(proj.root).script_path == proj.script_path          # reopen without the script arg
    (tmp_path / "other.json").write_text(json.dumps(SCRIPT))
    with pytest.raises(ProjectError, match="belongs to"):
        Project(proj.root, tmp_path / "other.json")


def test_unsafe_shot_ids_are_refused_before_recording(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"shots": [{"id": "../x", "line": "hi there"}]}))
    with pytest.raises(Exception, match="can't name files"):
        Project(tmp_path / "p", tmp_path / "s.json")


def test_take_names_count_up_per_shot_and_are_never_reused(proj):
    a, b, c = upload(proj, "hook"), upload(proj, "hook"), upload(proj, "cta")
    assert (a, b, c) == ("hook-1", "hook-2", "cta-1")
    proj.normalized(b).write_bytes(b"norm")
    proj.qa_file(b).write_text("{}")
    moved = proj.discard(b)
    assert sorted(moved) == ["raw/discarded/hook-2.mp4", "raw/discarded/orig/hook-2.webm",
                             "raw/discarded/qa/hook-2.json"]
    assert [t["name"] for t in proj.takes()["hook"]] == ["hook-1"]
    assert upload(proj, "hook") == "hook-3"
    disk = json.loads(proj.takes_file.read_text())
    assert disk == {"hook": [{"src": "raw/hook-1.mp4", "pin": False}, {"src": "raw/hook-3.mp4", "pin": False}],
                    "cta": [{"src": "raw/cta-1.mp4", "pin": False}]}


def test_reserve_validates_shot_and_extension(proj):
    for shot, ext in (("../x", "mp4"), ("nope", "mp4"), ("hook", "exe"), ("hook", "mp4/../x")):
        with pytest.raises(ProjectError):
            proj.reserve(shot, ext)
    assert not any(proj.orig.iterdir())


def test_pin_is_exclusive_within_a_shot(proj):
    a, b, c = upload(proj, "hook"), upload(proj, "hook"), upload(proj, "cta")
    proj.set_pin(c, True)
    proj.set_pin(a, True)
    proj.set_pin(b, True)
    pins = {t["name"]: t["pin"] for ts in proj.takes().values() for t in ts}
    assert pins == {a: False, b: True, c: True}
    proj.set_pin(a, False)                     # unpinning another take leaves the pin alone
    assert proj.find(b)[1]["pin"] is True
    proj.set_pin(b, False)
    assert proj.find(b)[1]["pin"] is False
    with pytest.raises(ProjectError, match="no take"):
        proj.set_pin("hook-9", True)


def test_best_take_follows_pin_then_score_then_later():
    rep = lambda score: {"script": {"score": score}}   # noqa: E731
    entries = [{"name": "h-1"}, {"name": "h-2"}, {"name": "h-3"}]
    assert best_take(entries, {"h-1": rep(90), "h-2": rep(95), "h-3": rep(80)}) == "h-2"
    assert best_take(entries, {"h-1": rep(90), "h-2": rep(90)}) == "h-2"
    assert best_take(entries, {}) is None                       # all still checking
    entries[0]["pin"] = True
    assert best_take(entries, {"h-2": rep(99)}) == "h-1"


def test_retakes_lose_to_any_usable_take_unless_pinned():
    rep = lambda score, v: {"script": {"score": score}, "verdict": v}   # noqa: E731
    entries = [{"name": "h-1"}, {"name": "h-2"}, {"name": "h-3"}]
    clipped = {"h-1": rep(99, "retake"), "h-2": rep(90, "ok"), "h-3": rep(80, "great")}
    assert best_take(entries, clipped) == "h-2"              # the tidier read clipped: QA knows better
    assert [e["name"] for e in build_candidates(entries, clipped)] == ["h-2", "h-3"]
    only_bad = {"h-1": rep(70, "retake"), "h-2": rep(75, "retake")}
    assert best_take(entries[:2], only_bad) == "h-2"         # nothing better: the shot still builds
    assert build_candidates(entries[:2], only_bad) == entries[:2]
    assert best_take(entries, {"h-1": rep(99, "retake")}) == "h-1"   # others still checking
    entries[0]["pin"] = True
    assert best_take(entries, clipped) == "h-1" and build_candidates(entries, clipped)[0]["name"] == "h-1"


# --- http helpers -------------------------------------------------------------------------

def test_parse_range():
    assert parse_range(None, 100) is None
    assert parse_range("bytes=0-", 100) == (0, 99)
    assert parse_range("bytes=10-19", 100) == (10, 19)
    assert parse_range("bytes=90-500", 100) == (90, 99)
    assert parse_range("bytes=-10", 100) == (90, 99)
    assert parse_range("bytes=0-1,5-6", 100) is None and parse_range("items=1-2", 100) is None
    assert parse_range("bytes=9-3", 100) is None
    for bad in ("bytes=100-", "bytes=-0"):
        with pytest.raises(RangeNotSatisfiable):
            parse_range(bad, 100)


def test_paths_cannot_escape(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.mp4").write_bytes(b"x")
    (tmp_path / "raw" / "link.mp4").symlink_to("/etc/hosts")
    for raw in ("../etc/passwd", "raw/../../x", "raw/%2e%2e/x", "raw/..%2fx", "raw//a.mp4", ".hidden", "raw/%00"):
        assert safe_parts(raw) is None, raw
    assert contained(tmp_path, ["raw", "a.mp4"]) == (tmp_path / "raw" / "a.mp4").resolve()
    assert contained(tmp_path, ["raw", "link.mp4"]) is None      # symlink out of the project
    assert contained(tmp_path, ["raw"]) is None                  # directories aren't served


# --- live server, workers stubbed ---------------------------------------------------------

@pytest.fixture
def server(proj):
    def normalize(src, dst):
        shutil.copy(src, dst)
        return {"fps": 30}

    def check(name):
        time.sleep(0.05)
        score = 90 + int(name.split("-")[-1])
        proj.qa_file(name).write_text(json.dumps({"take": name, "verdict": "great", "script": {"score": score}}))

    studio = Studio(proj, normalize=normalize, check=check)
    studio.start()
    httpd = StudioServer(("127.0.0.1", 0), studio)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    studio.stop()


def call(httpd, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    is_json = (r.getheader("Content-Type") or "").startswith("application/json")
    return r.status, json.loads(data) if is_json else data, r


def wait_ready(httpd, shot, n):
    for _ in range(100):
        _, proj, _ = call(httpd, "GET", "/api/project")
        takes = next(s for s in proj["shots"] if s["id"] == shot)["takes"]
        if len(takes) == n and all(t["status"] == "ready" for t in takes):
            return proj
        time.sleep(0.05)
    raise AssertionError(f"takes never became ready: {takes}")


def test_api_round_trip(server):
    info = json.dumps({"audio": {"label": "Alex’s iPhone Microphone"}}, ensure_ascii=True)
    st, body, _ = call(server, "POST", "/api/takes?shot=hook&source=record&ext=webm", b"0123456789",
                       {"X-Capture-Info": info, "Origin": f"http://127.0.0.1:{server.server_address[1]}"})
    assert (st, body["name"]) == (201, "hook-1")
    call(server, "POST", "/api/takes?shot=hook&source=import&ext=mov", b"abcdefghij")
    proj = wait_ready(server, "hook", 2)
    hook = proj["shots"][0]
    assert hook["cues"] == [{"type": "overlay", "at_words": "three hours", "text": "3 HRS"}]
    assert hook["best"] == "hook-2" and hook["estimate_s"] > 1
    t1 = hook["takes"][0]
    assert t1["src"] == "raw/hook-1.mp4" and t1["url"] == "/media/raw/hook-1.mp4" and t1["qa"]["verdict"] == "great"
    cap = json.loads(server.studio.project.capture_file("hook-1").read_text())
    assert cap["client"]["audio"]["label"] == "Alex’s iPhone Microphone" and cap["normalized"] == {"fps": 30}

    assert call(server, "POST", "/api/takes/hook-1/pin")[1]["pin"] is True
    assert call(server, "GET", "/api/project")[1]["shots"][0]["best"] == "hook-1"
    assert call(server, "POST", "/api/takes/hook-1/unpin")[1]["pin"] is False
    st, body, _ = call(server, "POST", "/api/takes/hook-2/discard")
    assert st == 200 and "raw/discarded/hook-2.mp4" in body["moved"]
    assert [t["name"] for t in call(server, "GET", "/api/project")[1]["shots"][0]["takes"]] == ["hook-1"]
    assert call(server, "POST", "/api/takes/hook-2/pin")[0] == 404

    st, data, r = call(server, "GET", "/media/raw/hook-1.mp4", headers={"Range": "bytes=2-5"})
    assert (st, data, r.getheader("Content-Range"), r.getheader("Accept-Ranges")) == (206, b"2345", "bytes 2-5/10",
                                                                                         "bytes")
    assert call(server, "GET", "/media/raw/hook-1.mp4", headers={"Range": "bytes=50-"})[0] == 416
    st, data, _ = call(server, "GET", "/media/raw/hook-1.mp4")
    assert (st, data) == (200, b"0123456789")


@pytest.mark.parametrize("path", ["/media/../../etc/passwd", "/media/raw/%2e%2e/%2e%2e/script.json",
                                  "/media/project.json", "/media/raw/orig/../../takes.json", "/static/../server.py",
                                  "/media/raw/discarded/../../../script.json", "/media/%2fetc/passwd"])
def test_traversal_is_impossible(server, path):
    assert call(server, "GET", path)[0] == 404


def test_uploads_are_validated(server):
    for q in ("shot=../x&source=record&ext=mp4", "shot=nope&source=record&ext=mp4",
              "shot=hook&source=record&ext=exe", "shot=hook&source=webcam&ext=mp4"):
        assert call(server, "POST", f"/api/takes?{q}", b"x")[0] == 400, q
    assert call(server, "POST", "/api/takes?shot=hook&source=record&ext=mp4", b"")[0] == 400
    assert not list(server.studio.project.orig.glob("*.mp4"))


def test_favicon_does_not_404(server):
    assert call(server, "GET", "/favicon.ico")[0] in (200, 204)


def test_cross_site_requests_are_refused(server):
    assert call(server, "POST", "/api/takes/hook-1/discard", headers={"Origin": "https://evil.example"})[0] == 403
    assert call(server, "GET", "/api/project", headers={"Host": "evil.example:80"})[0] == 403


def test_build_waits_for_checks(server):
    server.studio._set("hook-7", "checking", stage="checking")
    server.studio.project.add("hook", "hook-7")
    st, body, _ = call(server, "POST", "/api/build")
    assert st == 409 and "hook-7" in body["error"]
    assert call(server, "GET", "/api/build")[1]["state"] == "idle"
