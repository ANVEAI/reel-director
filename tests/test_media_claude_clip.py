"""v4 media: the Claude-created clip provider (claude_clip) and its prompt / contract module (clip_prompts).

No network, no Claude, no browser: `claude` and `hyperframes` are a scripted fake runner. The fake "Claude" writes
index.html into the sandbox; the fake render builds a tiny real MP4 with ffmpeg (lavfi), so the frame and seek checks
run on real pixels. Properties under test: the sandbox is a copy (nothing links back to the pack), every attempt is
validated, a rejected attempt is retried at most twice with its errors in the next prompt, `claude -p` never gets an
API key or broad tools, accepted clips are cached by brief hash (a second call runs nothing)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from reel_director.media import clip_prompts as P
from reel_director.media import license as L
from reel_director.media.cache import MediaCache
from reel_director.media.providers import claude_clip as cc

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
ENTRIES = cc.MP_ENTRIES
OK_ANSWER = {"status": "ok", "hero": "a clock", "parts": ["layers/meshGradient"], "summary": "done"}


def ffmpeg(*args):
    subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-y", *args], check=True)


def make_video(path, kind="moving", dur=3.0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "moving":
        ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=108x192:rate=30:duration={dur}", "-pix_fmt", "yuv420p", str(path))
    elif kind == "blank":
        ffmpeg("-f", "lavfi", "-i", f"color=c=0x0B0A10:size=108x192:rate=30:duration={dur}", "-pix_fmt", "yuv420p",
               str(path))
    else:                                           # frozen: one picture held for the whole clip
        still = path.with_suffix(".png")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=108x192:rate=30", "-frames:v", "1", str(still))
        ffmpeg("-loop", "1", "-i", str(still), "-t", str(dur), "-r", "30", "-pix_fmt", "yuv420p", str(path))
    return path


@pytest.fixture()
def pack(tmp_path):
    root = tmp_path / "pack"
    for rel in ENTRIES:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("export const x = 1;\n")
    return root


class Fake:
    """Stands in for `claude` and `hyperframes`; ffmpeg calls go to the real binary."""

    def __init__(self, pages, logged_in=True, render="moving", claude_result=None):
        self.pages, self.logged_in, self.render, self.claude_result = list(pages), logged_in, render, claude_result
        self.calls, self.prompts, self.envs, self.last_mp4 = [], [], [], None

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        exe = Path(cmd[0]).name
        if exe == "claude" and cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"loggedIn": self.logged_in}), "")
        if exe == "claude":
            self.prompts.append(kw["input"])
            self.envs.append(kw["env"])
            page = self.pages.pop(0)
            Path(kw["cwd"], "index.html").write_text(page(Path(kw["cwd"])) if callable(page) else page)
            out = self.claude_result or {"is_error": False, "result": "", "structured_output": OK_ANSWER,
                                         "total_cost_usd": 0.0}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")
        if exe == "hyperframes" and cmd[1] == "lint":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"errorCount": 0, "findings": []}), "")
        if exe == "hyperframes" and cmd[1] == "render":
            self.last_mp4 = make_video(cmd[cmd.index("-o") + 1], self.render)
            return subprocess.CompletedProcess(cmd, 0, "rendered", "")
        if exe == "hyperframes" and cmd[1] == "snapshot":
            out = Path(cmd[cmd.index("-o") + 1])
            out.mkdir(parents=True, exist_ok=True)
            for i, t in enumerate(cmd[cmd.index("--at") + 1].split(",")):
                ffmpeg("-ss", t, "-i", str(self.last_mp4), "-frames:v", "1", str(out / f"frame-{i:02d}-at-{t}s.png"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.run(cmd, **kw)

    def count(self, exe, sub=None):
        return sum(1 for c in self.calls if Path(c[0]).name == exe and (sub is None or c[1] == sub))


def provider(tmp_path, pack, fake, **kw):
    return cc.ClaudeClipProvider(work_root=tmp_path / "work", cache=MediaCache(tmp_path / "cache"), pack=pack,
                                 claude_bin="claude", hyperframes_bin="hyperframes", ffmpeg_bin=FFMPEG or "ffmpeg",
                                 run=fake, log=lambda s: None, **kw)


def scaffold(sb: Path) -> str:
    """What a well-behaved Claude leaves: a page that keeps the contract (the scaffold, fonts inlined)."""
    return P.scaffold_html(width=1080, height=1920, duration=3, fps=30, faces=(sb / "kit" / "fonts.css").read_text())


def with_random(sb: Path) -> str:
    return scaffold(sb).replace("const k = E.hero", "const wob = Math.random(); const k = E.hero")


# ---- spec, motif, prompt ----
def test_key_is_stable_normalised_and_versioned(monkeypatch):
    a = cc.ClipSpec("Clock  racing", context="3 hours editing")
    assert a.key() == cc.ClipSpec("clock racing ", context="3 HOURS editing").key()
    assert len(a.key()) == 16
    assert a.key() != cc.ClipSpec("clock racing", 1080, 1080, context="3 hours editing").key()
    assert a.key() != cc.ClipSpec("clock racing", context="read the script").key()
    before = a.key()
    monkeypatch.setattr(P, "PROMPT_VERSION", "cc-test")
    assert a.key() != before                                            # a prompt change re-authors every clip


@pytest.mark.parametrize("brief,context,motif", [
    ("clock racing through 3 hours of editing", "3 hours editing", "TIME DRAINING"),
    ("timeline auto-assembling with a checkmark", "edit finished before you hit record", "DONE BEFORE YOU START"),
    ("script page being read", "read the script", "THE SCRIPT"),
    ("reel pieces assembling themselves", "the reel builds itself", "IT BUILDS ITSELF"),
    ("a lighthouse in fog", "", "ONE HERO, ONE VERB"),
])
def test_motif_for_the_demo_lines(brief, context, motif):
    assert P.pick_motif(brief, context).startswith(motif)


def test_prompt_carries_brief_contract_kit_and_feedback():
    p = P.build_prompt('rocket "launching"', context="we launched", icons=["rocket", "clock"])
    assert "rocket 'launching'" in p and "we launched" in p and "LAUNCH." in p
    for must in ('data-width="1080"', 'data-height="1920"', 'data-duration="3"', 'window.__timelines["clip"]',
                 "mp/layers/overlay.js", "kit/objects3d.js", "rocket, clock", P.THREE_URL, "hyperframes lint",
                 "hyperframes snapshot", "--describe false", "bottom 22%", "frame-heights per second",
                 "on EVERY frame"):
        assert must in p, must
    assert "PREVIOUS ATTEMPT" not in p
    retry = P.build_prompt("rocket", errors=["not seek-safe: uses Math.random()"])
    assert "PREVIOUS ATTEMPT WAS REJECTED" in retry and "- not seek-safe: uses Math.random()" in retry
    square = P.build_prompt("rocket", width=1080, height=1080, duration=2.5)
    assert 'data-height="1080"' in square and 'data-duration="2.5"' in square


def test_font_faces_and_scaffold_contract(tmp_path):
    faces = P.font_faces([("Inter", "kit/fonts/inter-latin-800-normal.woff2", 800, "normal"),
                          ("Manrope", "kit/fonts/Manrope-Variable.ttf", 0, "normal")])
    assert 'font-family: "Inter"' in faces and "font-weight: 800" in faces and 'format("woff2")' in faces
    assert "font-weight: 100 900" in faces and 'format("truetype")' in faces
    html = P.scaffold_html(width=1080, height=1920, duration=3, fps=30, faces=faces, brief="a clock")
    assert 'data-composition-id="clip"' in html and 'window.__timelines["clip"] = tl' in html
    assert html.index("gsap.timeline({ paused: true })") < html.index('window.__timelines["clip"]')
    (tmp_path / "index.html").write_text(html)
    assert P.static_check(tmp_path, cc.ClipSpec("a clock")) == []


# ---- the contract checks ----
@pytest.mark.parametrize("mutate,expect", [
    (lambda h: h.replace('data-duration="3"', 'data-duration="5"'), 'data-duration="3"'),
    (lambda h: h.replace('data-width="1080"', 'data-width="1920"'), 'data-width="1080"'),
    (lambda h: h.replace('window.__timelines["clip"] = tl', 'window.__timelines["main"] = tl'), "registered"),
    (lambda h: h.replace("const k = E.hero", "const r = Math.random(); const k = E.hero"), "Math.random"),
    (lambda h: h.replace("const k = E.hero", "const n = Date.now(); const k = E.hero"), "wall clock"),
    (lambda h: h.replace("const k = E.hero", "requestAnimationFrame(() => 0); const k = E.hero"), "free-running"),
    (lambda h: h.replace("const k = E.hero", "fetch('x.json'); const k = E.hero"), "network fetch"),
    (lambda h: h.replace("</style>", "</style><img src=\"https://example.com/a.png\">"), "remote URL"),
])
def test_static_check_rejects(tmp_path, mutate, expect):
    html = P.scaffold_html(width=1080, height=1920, duration=3, fps=30, faces="")
    (tmp_path / "index.html").write_text(mutate(html))
    errs = P.static_check(tmp_path, cc.ClipSpec("x"))
    assert errs and any(expect in e for e in errs), errs


def test_static_check_allows_three_and_flags_kit_edits(tmp_path):
    html = P.scaffold_html(width=1080, height=1920, duration=3, fps=30, faces="").replace(
        "</head>", f'<script type="importmap">{{"imports":{{"three":"{P.THREE_URL}/build/three.module.js"}}}}'
                   '</script></head>')
    (tmp_path / "index.html").write_text(html)
    kit = tmp_path / "kit" / "objects3d.js"
    kit.parent.mkdir()
    kit.write_text("original")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "kit-manifest.json").write_text(json.dumps({"kit/objects3d.js": P.file_sha(kit)}))
    assert P.static_check(tmp_path, cc.ClipSpec("x")) == []
    kit.write_text("edited by the author")
    assert any("kit files were modified" in e for e in P.static_check(tmp_path, cc.ClipSpec("x")))
    assert P.static_check(tmp_path / "nope", cc.ClipSpec("x")) == ["index.html was not written"]


def test_parse_lint():
    js = json.dumps({"errorCount": 1, "warningCount": 1, "findings": [
        {"severity": "error", "code": "gsap_animates_clip_element", "message": "do not tween .clip"},
        {"severity": "warning", "code": "font_family_without_font_face", "message": "add @font-face"}]})
    errs, warns = P.parse_lint("[hint] banner\n" + js)
    assert errs == ["gsap_animates_clip_element: do not tween .clip"] and warns[0].startswith("font_family")
    assert P.parse_lint(json.dumps({"errorCount": 2, "findings": []}))[0] == ["2 lint error(s)"]
    assert P.parse_lint("✖ 1 error: root missing\n0 errors elsewhere")[0] == ["✖ 1 error: root missing"]
    assert P.parse_lint(json.dumps({"errorCount": 0, "findings": []})) == ([], [])


@needs_ffmpeg
def test_frame_check_on_real_pixels(tmp_path):
    spec = cc.ClipSpec("x")
    errs, stats = P.frame_check(make_video(tmp_path / "ok.mp4"), spec, FFMPEG)
    assert errs == [] and stats["first_change"] > 0.08 and len(stats["motion"]) == 8
    errs, _ = P.frame_check(make_video(tmp_path / "blank.mp4", "blank"), spec, FFMPEG)
    assert any("blank/empty" in e for e in errs) and any("first 6 frames" in e for e in errs)
    errs, _ = P.frame_check(make_video(tmp_path / "still.mp4", "frozen"), spec, FFMPEG)
    assert any("almost no motion" in e for e in errs) and any("frozen" in e for e in errs)
    errs, _ = P.frame_check(tmp_path / "missing.mp4", spec, FFMPEG)
    assert errs and "could not decode" in errs[0]
    sheet = P.contact_sheet(tmp_path / "ok.mp4", tmp_path / "sheet.jpg", [0.1, 1.5, 2.9], ffmpeg=FFMPEG, width=54)
    assert sheet.stat().st_size > 0


# ---- the sandbox ----
def test_prepare_stages_copies_kit_and_examples(tmp_path, pack):
    fake = Fake([])
    p = provider(tmp_path, pack, fake)
    gallery = tmp_path / "work" / "_gallery"
    gallery.mkdir(parents=True)
    for name in ("c", "a", "b"):
        (gallery / f"{name}.html").write_text(f"<!-- {name} -->")
    spec = cc.ClipSpec("clock racing", context="3 hours editing")
    sb = p.prepare(spec)
    assert sb == tmp_path / "work" / spec.key()
    for rel in ENTRIES:
        dest = sb / "mp" / rel
        assert dest.is_file() and not dest.is_symlink()
        assert os.stat(dest).st_ino != os.stat(pack / rel).st_ino        # a copy: writing it cannot reach the pack
    css = (sb / "kit" / "fonts.css").read_text()
    assert 'font-family: "Inter"' in css and 'font-family: "Instrument Serif"' in css and "italic" in css
    assert (sb / "kit" / "icons" / "clock.svg").is_file() and "objectsCtx" in (sb / "kit" / "objects3d.js").read_text()
    assert sorted(x.name for x in (sb / "kit" / "examples").iterdir()) == ["a.html", "b.html"]
    assert P.static_check(sb, spec) == []
    manifest = json.loads((sb / "out" / "kit-manifest.json").read_text())
    assert "kit/objects3d.js" in manifest and f"mp/{ENTRIES[0]}" in manifest
    (sb / "index.html").write_text("authored")
    p.prepare(spec)
    assert (sb / "index.html").read_text() == "authored"                  # a retry keeps the attempt


def test_examples_prefer_current_prompt_and_skip_the_same_brief(tmp_path, pack):
    p = provider(tmp_path, pack, Fake([]))
    gallery = tmp_path / "work" / "_gallery"
    gallery.mkdir(parents=True)
    heads = {"a1": "<!-- accepted clip; brief: a rocket -->", "b2": f"<!-- accepted clip {P.PROMPT_VERSION}; brief: "
             "a clock -->", "c3": f"<!-- accepted clip {P.PROMPT_VERSION}; brief: Script  page -->",
             "d4": f"<!-- accepted clip {P.PROMPT_VERSION}; brief: money stack -->"}
    for stem, head in heads.items():
        (gallery / f"{stem}.html").write_text(head + "\n<html></html>")
    assert cc.gallery_info(gallery / "a1.html") == ("", "a rocket")
    assert cc.gallery_info(gallery / "c3.html") == (P.PROMPT_VERSION, "Script  page")
    assert [g.stem for g in p.examples(cc.ClipSpec("script page"))] == ["b2", "d4"]   # current first, own brief never
    assert [g.stem for g in p.examples(cc.ClipSpec("a clock"))] == ["c3", "d4"]


@needs_ffmpeg
def test_store_moves_older_takes_of_the_brief_out_of_the_example_pool(tmp_path, pack):
    fake = Fake([scaffold])
    p = provider(tmp_path, pack, fake)
    gallery = tmp_path / "work" / "_gallery"
    gallery.mkdir(parents=True)
    (gallery / "old.html").write_text("<!-- accepted clip; brief: a lighthouse -->\n")
    (gallery / "other.html").write_text("<!-- accepted clip; brief: a rocket -->\n")
    res = p.generate(cc.ClipSpec("a lighthouse"))
    assert (gallery / f"{res.key}.html").read_text().startswith(f"<!-- accepted clip {P.PROMPT_VERSION}; brief: a")
    assert not (gallery / "old.html").exists() and (gallery / "superseded" / "old.html").is_file()
    assert (gallery / "other.html").is_file()


def test_child_env_and_claude_command(monkeypatch):
    for k, v in {"ANTHROPIC_API_KEY": "sk-paid", "GEMINI_API_KEY": "g", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s",
                 "CLAUDE_CODE_ENTRYPOINT": "sdk", "CLAUDE_CODE_SIMPLE": "1", "CLAUDE_AGENT_SDK_VERSION": "1",
                 "CLAUDE_CODE_OAUTH_TOKEN": "tok"}.items():
        monkeypatch.setenv(k, v)
    env = cc.child_env()
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDECODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env
    assert "GEMINI_API_KEY" not in env                  # `hyperframes snapshot` would upload frames to Gemini vision
    assert "CLAUDE_CODE_SIMPLE" not in env and "CLAUDE_AGENT_SDK_VERSION" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok" and env["NO_COLOR"] == "1" and "PATH" in env
    cmd = cc.ClaudeClipProvider(claude_bin="claude", model="opus").claude_cmd()
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == "Read,Write,Bash"
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert allowed == ["Read", "Write", "Bash(hyperframes lint:*)", "Bash(hyperframes snapshot:*)"]
    for flag in ("--restricted", "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--json-schema"):
        assert flag in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk" and cmd[-2:] == ["--model", "opus"]
    assert not any("skip-permissions" in c or "bypass" in c for c in cmd)
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == P.RESULT_SCHEMA


def test_auth_gate(tmp_path, pack, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    fake = Fake([], logged_in=False)
    p = provider(tmp_path, pack, fake)
    with pytest.raises(cc.ClipAuthError, match="claude auth login"):
        p.generate(cc.ClipSpec("clock"))
    assert p.available is False and p.status()["setup"] == cc.FOUNDER_SETUP
    assert p.search("clock") == []                                      # nothing offered that cannot be made
    assert fake.count("claude") == 2 and fake.count("hyperframes") == 0
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    fake2 = Fake([])
    p2 = provider(tmp_path, pack, fake2)
    p2.check_auth()
    assert fake2.calls == []


def test_search_offers_one_free_candidate(tmp_path, pack):
    p = provider(tmp_path, pack, Fake([]))
    (c,) = p.search("clock ticking fast", "video", duration=(1.2, 3.0), orientation="portrait", context="3 hours")
    key = cc.ClipSpec("clock ticking fast", 1080, 1920, 3.0, 30, "3 hours").key()
    assert c.id == f"claude_clip:{key}" and c.provider == "claude_clip" and c.kind == "video"
    assert (c.w, c.h, c.duration, c.cost_usd, c.license) == (1080, 1920, 3.0, 0.0, "original")
    assert c.url == f"claude-clip://{key}" and L.allowed(c.license)
    assert json.loads((tmp_path / "work" / key / "spec.json").read_text())["context"] == "3 hours"
    (sq,) = p.search("clock", orientation="square", duration=(2.0, 10.0))
    assert (sq.w, sq.h, sq.duration) == (1080, 1080, 3.0)
    assert p.search("clock", "image") == [] and p.search("  ") == [] and p.search("clock", limit=0) == []
    assert p.search("clock", min_short_side=2160) == []


# ---- generation end to end (fake Claude + fake HyperFrames, real ffmpeg) ----
@needs_ffmpeg
def test_generate_retries_with_feedback_then_caches(tmp_path, pack):
    fake = Fake([with_random, scaffold])
    p = provider(tmp_path, pack, fake)
    spec = cc.ClipSpec("clock racing through 3 hours of editing", context="3 hours editing")
    res = p.generate(spec)
    assert res.path.is_file() and res.path.suffix == ".mp4" and not res.cached
    assert res.poster and res.poster.is_file()
    assert [a["ok"] for a in res.meta["attempts"]] == [False, True]
    assert "Math.random" in res.meta["attempts"][0]["errors"][0]
    assert "PREVIOUS ATTEMPT WAS REJECTED" not in fake.prompts[0]
    assert "PREVIOUS ATTEMPT WAS REJECTED" in fake.prompts[1] and "Math.random" in fake.prompts[1]
    assert all("ANTHROPIC_API_KEY" not in e for e in fake.envs)
    renders = [c for c in fake.calls if c[:2] == ["hyperframes", "render"]]
    assert renders and all("--no-browser-gpu" in c for c in renders)      # software capture: bit-identical re-renders
    stats = res.meta["attempts"][1]["stats"]
    assert stats["seek_diff"] and all(m < cc.SEEK_TOL for m, _ in stats["seek_diff"])
    side = p.cache.meta(res.path)
    assert side["license"] == "original" and side["cost_usd"] == 0.0 and side["claude_clip"]["key"] == spec.key()
    assert (tmp_path / "work" / "_gallery" / f"{spec.key()}.html").is_file()
    n = len(fake.calls)
    again = p.generate(spec)                                            # cache hit: nothing runs
    assert again.cached and again.path == res.path and len(fake.calls) == n
    (c,) = p.search(spec.brief, context=spec.context)
    assert c.url == str(res.path) and c.thumb == str(res.poster)
    assert p.fetch(c) == res.path and p.fetch(c.to_dict()) == res.path


@needs_ffmpeg
def test_generate_gives_up_after_two_retries(tmp_path, pack):
    fake = Fake([scaffold] * 5, render="blank")
    p = provider(tmp_path, pack, fake, retries=5)                       # capped at 2 retries
    with pytest.raises(cc.ClipError, match="after 3 attempt"):
        p.generate(cc.ClipSpec("a lighthouse"))
    assert fake.count("claude", "-p") == 3 and fake.count("hyperframes", "render") == 3
    attempts = json.loads((tmp_path / "work" / cc.ClipSpec("a lighthouse").key() / "attempts.json").read_text())
    assert len(attempts) == 3 and all("blank/empty" in a["errors"][0] for a in attempts)
    assert "blank/empty" in fake.prompts[2]


@needs_ffmpeg
def test_seek_check_catches_state_between_frames(tmp_path, pack):
    fake = Fake([])
    p = provider(tmp_path, pack, fake)
    spec = cc.ClipSpec("x")
    sb = p.prepare(spec)
    mp4 = make_video(sb / "out" / "r.mp4")
    fake.last_mp4 = make_video(sb / "out" / "other.mp4", "frozen")      # snapshots disagree with the render
    errs, stats = p.seek_check(sb, spec, mp4)
    assert errs and "not seek-safe" in errs[0]
    fake.last_mp4 = mp4
    assert p.seek_check(sb, spec, mp4)[0] == []
    snaps = [c for c in fake.calls if c[:2] == ["hyperframes", "snapshot"]]
    assert snaps and all(c[c.index("--describe") + 1] == "false" for c in snaps)        # never a Gemini upload


def test_author_auth_failure_is_not_retried(tmp_path, pack):
    fake = Fake([scaffold], claude_result={"is_error": True, "result": "Failed to authenticate: OAuth expired"})
    p = provider(tmp_path, pack, fake)
    sb = p.prepare(cc.ClipSpec("x"))
    with pytest.raises(cc.ClipAuthError, match="OAuth"):
        p.author(sb, cc.ClipSpec("x"), None)
    plain = Fake([scaffold], claude_result={"is_error": False, "result": json.dumps(OK_ANSWER)})
    ans = provider(tmp_path, pack, plain).author(sb, cc.ClipSpec("x"), None)
    assert ans["hero"] == "a clock" and (sb / "out" / "prompt.txt").read_text().startswith("You are a senior")


def test_registry_builds_the_provider():
    from reel_director.media import providers as registry
    prov = registry.make("claude_clip")
    assert isinstance(prov, cc.ClaudeClipProvider) and prov.name == "claude_clip" and prov.paid is False
    assert "claude_clip" in registry.DEFAULT_ORDER["video"]
