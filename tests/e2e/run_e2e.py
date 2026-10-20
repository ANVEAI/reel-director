"""End-to-end run of the Reel Director studio in real headless Chrome with a fake camera and mic.

  .venv/bin/python tests/e2e/run_e2e.py [--headed] [--skip-import] [--skip-build] [--port N]

1. Makes the demo media (scripts/make_demo_media.py) if examples/demo/media is missing, and the
   per-take fake media (make_fake_media.py: 1080x1920 MJPEG camera + `say` wav, flawed on purpose).
2. Starts `python -m reel_director studio examples/demo/script.json --project work/e2e/project
   --port <free> --no-open`. The previous e2e project is removed first, but only a directory this
   harness created (it carries a .e2e-owned marker); anything else there stops the run.
3. Per take: launches Google Chrome (Playwright channel="chrome", headless) with
   --use-fake-device-for-media-stream and that take's files, selects the shot through the
   window.__studio test hook, records with the Space key (countdown, record, Space), waits for the
   upload and the QA, taking screenshots at each stage.
4. Asserts the QA (misread -> retake with the misread listed; clean -> great/ok; restart and pause
   takes cut, not retaken), the capture rules (mime, bitrates, EC/NS/AGC off, native size, resizeMode
   none), normalization (CFR H.264 High, mono 48 kHz AAC, faststart, A/V in sync), the auto-picker's
   best take, Pin/Unpin from the shot list, and the API's safety (traversal, bad ids/exts, Range,
   127.0.0.1 only).
5. Imports an iPhone-style rotated .mov through the UI's file input (must come out upright 1080x1920),
   checks POST /api/build is refused while it is checking, then discards it with the UI's Discard.
6. Clicks "Build reel" and checks the master: duration (whole reel and per shot), -14 +/- 1 LUFS and
   true peak <= -0.9 dBTP (measured with ffmpeg, not only as reported), and that the picker used
   hook-2, turn-2 and a cta take (cta-1's pause is cut, so either is fine).

Outputs in work/e2e/: screens/NN-<take>-<stage>.png in run order, report.json, server.log, media/.
Exit code 0 only when every hard check passed; WARN lines are quality hints. A full run takes about
4 minutes (first fake-media generation adds ~40 s; it is cached in work/e2e/media/ afterwards).
Needs playwright in .venv (`uv pip install --python .venv/bin/python playwright`; never `playwright
install`: the installed Google Chrome is driven), ffmpeg/ffprobe and macOS `say`.
"""
import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_fake_media as fake  # noqa: E402
from checks import (Checker, check_capture, check_files, check_master, check_qa, check_report,  # noqa: E402
                    orientation, originals, probe, problems, thumb)
from driver import MIN_LEAD, ROOT, SCRIPT, Recorder, Studio, free_port, log, open_browser  # noqa: E402

WORK = ROOT / "work" / "e2e"
DEMO_MEDIA = ROOT / "examples" / "demo" / "media"
MARKER = ".e2e-owned"
EXPECTED_PICK = {"hook": {"hook-2"}, "turn": {"turn-2"}, "cta": {"cta-1", "cta-2"}}   # cta-1's pause is cut
BUILD_STEPS = ["prep", "compile", "render", "master"]


def ensure_demo_media() -> None:
    if all((DEMO_MEDIA / f).exists() for f in ("bed.wav", "whoosh.wav", "pop.wav")):
        return
    log("making demo media (scripts/make_demo_media.py)")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_demo_media.py")], check=True, cwd=ROOT)


def fresh_project(path: Path) -> Path:
    path = path.resolve()
    if WORK.resolve() not in path.parents:
        raise SystemExit(f"--project must be inside {WORK}")
    if path.exists():
        if not (path / MARKER).exists():
            raise SystemExit(f"{path} exists and was not made by this harness; move it away first")
        shutil.rmtree(path)   # only a project this harness created (marker checked above)
    path.mkdir(parents=True)
    (path / MARKER).write_text("made by tests/e2e/run_e2e.py; replaced on the next run\n")
    return path


def lan_ip() -> str | None:
    """This Mac's LAN address (a UDP connect sends no packet), or None when offline."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


def takes_json(studio: Studio) -> dict:
    return json.loads((studio.project / "takes.json").read_text())


# ---------- per take ----------

def check_take(ck: Checker, studio: Studio, t: dict, run, took: dict, session, ui_text: str) -> None:
    f = t["name"]
    ck(f"{f}: window.__studio.state() answers", run.state is not None, type(run.state).__name__)
    ck(f"{f}: teleprompter shows the shot's line", run.line_shown, soft=True)
    ck(f"{f}: recorded with the first word intact", run.lead >= MIN_LEAD, f"lead-in {run.lead:.2f}s")
    check_capture(ck, f, run.instrument)
    ck(f"{f}: no page errors", not session.page_errors, session.page_errors[:3])
    ck(f"{f}: no console errors", not session.console_errors, session.console_errors[:3], soft=True)
    if ck(f"{f}: QA finished", took.get("status") == "ready", f"{took.get('status')} {str(took.get('qa'))[:200]}") \
            and check_report(ck, run.name, t["shot"], took["qa"]):
        check_qa(ck, t, run.name, took["qa"], run.stopped - run.started)
        ck(f"{f}: UI shows the verdict", took["qa"]["verdict"] in ui_text.lower(), soft=True)
    check_files(ck, studio.project, run.name)


# ---------- project-wide ----------

def check_picks(ck: Checker, studio: Studio, names: dict[str, str]) -> None:
    for s in studio.get("/api/project")["shots"]:
        want = {names[f] for f in EXPECTED_PICK[s["id"]] if f in names}
        ck(f"best take for {s['id']} is {'/'.join(sorted(want))}", s.get("best") in want, s.get("best"))
    tj = takes_json(studio)
    for f, name in names.items():
        e = next((e for e in tj.get(f.rsplit("-", 1)[0], []) if e.get("src") == f"raw/{name}.mp4"), None)
        ck(f"takes.json lists {name} (unpinned)", e is not None and not e.get("pin"), e)


def take_action(ck: Checker, studio: Studio, page, name: str, act: str, done) -> None:
    """Click a take's Pin/Unpin/Discard button in the shot list (accepting Discard's confirm) and
    wait until the server shows `done(studio)`; falls back to the API so later checks still run."""
    asked: list[str] = []

    def confirm(d) -> None:
        asked.append(d.message)
        d.accept()

    btn = page.locator(f'[data-act="{act}"][data-name="{name}"]')
    if ck(f"UI shows a {act} button for {name}", btn.count() == 1, f"{btn.count()} found"):
        page.on("dialog", confirm)
        btn.click()
    else:
        studio.post(f"/api/takes/{name}/{act}")
    end = time.time() + 15
    while not done(studio) and time.time() < end:
        page.wait_for_timeout(300)   # pumps Playwright events, so the confirm() handler runs
    page.remove_listener("dialog", confirm)
    ck(f"{act} {name} reaches the server", done(studio))
    if act == "discard":
        ck(f"discard {name} asks for confirmation first", asked, asked[:1], soft=True)


def check_pin(ck: Checker, studio: Studio, page, names: dict[str, str]) -> None:
    h1, h2 = names["hook-1"], names["hook-2"]
    take_action(ck, studio, page, h1, "pin", lambda st: (st.take(h1) or {}).get("pin") is True)
    shot = studio.shot("hook")
    pins = {t["name"]: t.get("pin") for t in shot["takes"]}
    ck(f"pin {h1}: only it is pinned", pins.get(h1) is True and sum(map(bool, pins.values())) == 1, pins)
    ck(f"pinned {h1} becomes the take the picker will use", shot.get("best") == h1, shot.get("best"))
    ck("takes.json carries the pin",
       any(e.get("src") == f"raw/{h1}.mp4" and e.get("pin") is True for e in takes_json(studio).get("hook", [])))
    page.wait_for_timeout(500)
    take_action(ck, studio, page, h1, "unpin", lambda st: (st.take(h1) or {}).get("pin") is False)
    shot = studio.shot("hook")
    unpinned = not any(t.get("pin") for t in shot["takes"])
    ck(f"unpin {h1}: auto-pick returns to {h2}", shot.get("best") == h2 and unpinned, f"best={shot.get('best')}")


def check_api(ck: Checker, studio: Studio, name: str) -> None:
    """Strict JSON, no path traversal, validated uploads, Range support, loopback-only binding."""
    _, _, body = studio.request("GET", "/api/project")
    ck("/api/project is strict JSON (no NaN/Infinity, which JSON.parse rejects)",
       not re.search(rb"\b(NaN|Infinity)\b", body))
    for path in ("/media/../../../pyproject.toml", "/media/..%2f..%2f..%2fpyproject.toml",
                 "/media/%2e%2e/%2e%2e/%2e%2e/pyproject.toml", "/media/raw/..%2f..%2f..%2f..%2fpyproject.toml",
                 "/media/%2fetc%2fhosts", "/media//etc/hosts"):
        st, _, b = studio.request("GET", path)
        ck(f"GET {path} stays inside the project", st != 200 and b"[project]" not in b and b"localhost" not in b, st)
    before = studio.take_shots()
    for q in ("shot=..%2F..%2Fevil&source=record&ext=mp4", "shot=nope&source=record&ext=mp4",
              "shot=hook&source=record&ext=exe", "shot=hook&source=record&ext=..%2Fx"):
        st, _ = studio.post(f"/api/takes?{q}", b"\0" * 64, {"Content-Type": "application/octet-stream"})
        ck(f"POST /api/takes?{q} -> 400", st == 400, st)
    ck("rejected uploads created no takes", studio.take_shots() == before)
    size = (studio.project / "raw" / f"{name}.mp4").stat().st_size
    st, hdr, b = studio.request("GET", f"/media/raw/{name}.mp4", headers={"Range": "bytes=0-99"})
    cr = {k.lower(): v for k, v in hdr.items()}.get("content-range", "")
    ck("/media answers byte ranges (206, Content-Range, exact bytes)",
       st == 206 and cr == f"bytes 0-99/{size}" and len(b) == 100, f"{st} {cr!r} {len(b)} bytes")
    ip = lan_ip()
    if ip:
        with socket.socket() as s:
            s.settimeout(1.0)
            open_on_lan = s.connect_ex((ip, studio.port)) == 0
        ck(f"server not reachable on the LAN address {ip} (127.0.0.1 only)", not open_on_lan)


# ---------- import ----------

def make_import(take: dict, media: Path, dst: Path) -> Path:
    """iPhone-style portrait recording: landscape-coded H.264 with a -90 degree display matrix (.mov)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".coded.mp4")
    start = take["speech_start"] - 1.0
    dur = take["stop_at"] - start
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "mjpeg", "-framerate", "30",
                    "-i", str(media / take["mjpeg"]), "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                    "-i", str(media / take["wav"]), "-t", f"{dur:.3f}", "-vf", "transpose=2",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    str(tmp)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-display_rotation:v:0", "-90", "-i", str(tmp),
                    "-c", "copy", str(dst)], check=True)
    tmp.unlink()
    return dst


def import_test(ck: Checker, studio: Studio, page, rec: Recorder, manifest: dict, qa_timeout: float) -> None:
    log("import: iPhone-style rotated .mov through the UI's file input")
    media = Path(manifest["dir"])
    take = next(t for t in manifest["takes"] if t["name"] == "hook-2")
    src = make_import(take, media, WORK / "import" / "iphone-portrait.mov")
    v = probe(src)["v"]
    rot = [sd["rotation"] for sd in v.get("side_data_list", []) if "rotation" in sd]
    ck("import fixture is landscape-coded with a rotation matrix", (v["width"], v["height"]) == (1920, 1080) and rot,
       f"{v['width']}x{v['height']} rotation {rot}")
    shots = [s["id"] for s in studio.get("/api/project")["shots"]]
    page.evaluate("id => window.__studio.selectShot(id)", "hook")
    tagged = page.locator('input[type="file"][data-shot="hook"]')
    inputs = page.locator('input[type="file"]')
    n = inputs.count()
    if not ck("UI has an Import file input (one per shot)", tagged.count() == 1 or n in (1, len(shots)),
              f"{n} file input(s)"):
        return
    before = set(studio.take_shots())
    pick = tagged if tagged.count() == 1 else inputs.nth(shots.index("hook") if n == len(shots) else 0)
    pick.set_input_files(str(src))
    name = studio.wait_new_take("hook", before, 120)
    if (studio.take(name) or {}).get("status") == "checking":
        st, _ = studio.post("/api/build")
        ck("POST /api/build -> 409 while a take is still checking", st == 409, st)
    rec.shoot(page, "import", "checking")
    t = studio.wait_checked(name, qa_timeout)
    page.wait_for_timeout(1500)
    rec.shoot(page, "import", "qa")
    if not ck(f"import {name}: QA finished", t.get("status") == "ready", t.get("status")):
        return
    qa = t["qa"]
    ck(f"import {name}: rotation applied, 1080x1920", (qa["video"]["width"], qa["video"]["height"]) == (1080, 1920),
       f"{qa['video']['width']}x{qa['video']['height']}")
    frame, still = thumb(studio.project / "raw" / f"{name}.mp4", 1.0), thumb(media / "frames" / "hook-2.png")
    up, flipped = orientation(frame, still)
    ck(f"import {name}: picture upright", up < 0.5 and up < flipped / 3,
       f"diff {up:.2f} upright vs {flipped:.2f} flipped")
    ck(f"import {name}: clean read -> great/ok", qa["verdict"] in {"great", "ok"}, f"{qa['verdict']}; {problems(qa)}")
    orig = originals(studio.project, name)
    ck(f"import {name}: original kept as .mov", [p.suffix for p in orig] == [".mov"], [p.name for p in orig])
    take_action(ck, studio, page, name, "discard", lambda st: name not in st.take_shots())
    listed = any(e.get("src") == f"raw/{name}.mp4" for es in takes_json(studio).values() for e in es)
    ck(f"discard {name}: gone from takes.json", not listed)
    moved = [p.name for p in (studio.project / "raw" / "discarded").glob(f"{name}*")]
    ck(f"discard {name}: moved to raw/discarded, not deleted",
       moved and not (studio.project / "raw" / f"{name}.mp4").exists(), moved)


# ---------- build ----------

def expected_duration(manifest: dict) -> tuple[float, float]:
    """Clean reads + each shot's pre/post roll, with slack for the cutter and the renderer."""
    from reel_director.cleanup import POST_ROLL, PRE_ROLL
    clean = [t for t in manifest["takes"] if not t["flaw"]]
    est = sum(t["speech_s"] for t in clean) + len(clean) * (PRE_ROLL + POST_ROLL)
    return est * 0.85, est * 1.2


def build_test(ck: Checker, studio: Studio, page, rec: Recorder, names: dict, manifest: dict,
               timeout: float) -> dict:
    from playwright.sync_api import TimeoutError as PwTimeout
    from playwright.sync_api import expect
    log("build: clicking Build reel")
    btn = page.get_by_role("button", name=re.compile(r"^\s*build reel", re.I))
    if not btn.count():
        btn = page.get_by_role("button", name=re.compile(r"build", re.I))
    btn = btn.first
    try:
        expect(btn).to_be_enabled(timeout=30_000)
    except AssertionError as e:
        ck("Build reel button is enabled once every shot has a ready take", False, str(e).splitlines()[0])
        return {}
    rec.shoot(page, "build", "ready")
    btn.click()
    end = time.time() + 15
    while (b := studio.get("/api/build"))["state"] == "idle" and time.time() < end:
        time.sleep(0.3)
    if not ck("clicking Build reel starts the build", b["state"] in {"running", "done"}, b["state"]):
        return b
    st, _ = studio.post("/api/build")
    ck("POST /api/build -> 409 while a build is running",
       st == 409 or studio.get("/api/build")["state"] != "running", st)
    seen, end = [], time.time() + timeout
    while b["state"] == "running" and time.time() < end:
        if b.get("step") not in seen:
            seen.append(b.get("step"))
            log(f"  build step: {b.get('step')}")
            rec.shoot(page, "build", str(b.get("step") or "running"))
        time.sleep(2)
        b = studio.get("/api/build")
    log(f"  build {b['state']}: " + " | ".join(b.get("log", [])[-3:]))
    if not ck("build finished", b["state"] == "done", f"{b['state']}: " + " | ".join(b.get("log", [])[-8:])):
        rec.shoot(page, "build", "error")
        return b
    order = [s for s in seen if s in BUILD_STEPS]
    ck("build reported its steps in order", order == [s for s in BUILD_STEPS if s in seen], seen, soft=True)
    try:
        page.wait_for_function("() => [...document.querySelectorAll('video')].some(v => "
                               "(v.currentSrc || v.src || '').includes('reel-master'))", timeout=15_000)
        shown = True
    except PwTimeout:
        shown = False
    ck("UI loads the master reel into a player", shown)
    page.wait_for_timeout(2500)
    rec.shoot(page, "build", "done")
    res = b.get("result") or {}
    ck("build result video is /media/renders/reel-master.mp4", res.get("video") == "/media/renders/reel-master.mp4",
       res.get("video"))
    picks = {s["id"]: s for s in res.get("shots", [])}
    for sid, fakes in EXPECTED_PICK.items():
        got = Path(str(picks.get(sid, {}).get("take"))).stem
        ck(f"auto-picker used {'/'.join(sorted(names[f] for f in fakes))} for {sid}", got in {names[f] for f in fakes},
           got)
    if Path(str(picks.get("cta", {}).get("take"))).stem == names["cta-1"]:
        ck("cta-1's 2 s pause was cut in the reel", (picks["cta"].get("cuts") or 0) >= 1, picks["cta"].get("cuts"))
    tl_path = studio.project / "reel" / "timeline.json"
    tl = json.loads(tl_path.read_text()) if tl_path.exists() else None
    if tl:   # each shot is just its read: lead-in, pauses, false starts and tails are gone
        from reel_director.cleanup import POST_ROLL, PRE_ROLL
        clean = {t["shot"]: t["speech_s"] for t in manifest["takes"] if not t["flaw"]}
        for sh in tl["shots"]:
            lo, hi = clean[sh["id"]] - 0.3, clean[sh["id"]] + PRE_ROLL + POST_ROLL + 0.6
            ck(f"reel shot {sh['id']} is just the read ({lo:.1f}-{hi:.1f}s)", lo <= sh["duration"] <= hi,
               f"{sh['duration']:.2f}s")
    check_master(ck, studio.project / "renders" / "reel-master.mp4", res, expected_duration(manifest),
                 tl["duration"] if tl else None)
    st, _, body = studio.request("GET", res.get("video") or "/media/renders/reel-master.mp4",
                                 headers={"Range": "bytes=0-1023"})
    ck("master streams to the player with Range (206)", st == 206 and len(body) == 1024, st)
    return b


# ---------- main ----------

def run(args, ck: Checker) -> dict:
    out = {"names": {}, "takes": {}, "build": None}
    screens = WORK / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    for old in screens.glob("*.png"):   # numbered per run: stale ones would interleave with this run's
        old.unlink()
    ensure_demo_media()
    log("fake media")
    manifest = fake.generate(preroll=args.preroll)
    media = Path(manifest["dir"])
    lines = {s["id"]: s["line"] for s in json.loads(SCRIPT.read_text())["shots"]}
    studio = Studio(fresh_project(args.project), args.port or free_port(), WORK / "server.log")
    log(f"studio on {studio.url}, project {studio.project}")
    studio.start()
    session = None
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            rec = Recorder(studio, screens)
            try:
                for t in manifest["takes"]:
                    log(f"take {t['name']} ({t['flaw'] or 'clean read'})")
                    if session:
                        session.close()
                    session = open_browser(pw, studio, media / t["mjpeg"], media / t["wav"], args.headed, args.scale)
                    r = rec.record(session, t, lines[t["shot"]])
                    out["names"][t["name"]] = r.name
                    took = studio.wait_checked(r.name, args.qa_timeout)
                    session.page.wait_for_timeout(1500)   # the UI polls /api/project
                    r.screens.append(rec.shoot(session.page, t["name"], "qa"))
                    qa = took.get("qa") or {}
                    log(f"  QA {r.name}: {qa.get('verdict')} ({problems(qa) if qa else took.get('status')})")
                    check_take(ck, studio, t, r, took, session, session.page.inner_text("body"))
                    out["takes"][t["name"]] = {**asdict(r), "qa": qa}
                names = out["names"]
                log("project checks: best takes, takes.json, pin, API safety")
                check_picks(ck, studio, names)
                check_pin(ck, studio, session.page, names)
                check_api(ck, studio, names["hook-2"])
                if not args.skip_import:
                    import_test(ck, studio, session.page, rec, manifest, args.qa_timeout)
                if not args.skip_build:
                    out["build"] = build_test(ck, studio, session.page, rec, names, manifest, args.build_timeout)
            except Exception as e:   # record, screenshot and keep the report: never lose the evidence
                ck("e2e flow ran to the end", False, f"{type(e).__name__}: {e}")
                traceback.print_exc()
                if session:
                    try:
                        rec.shoot(session.page, "flow", "error")
                        out["page_log"] = session.page.evaluate("() => window.__e2e || null")
                    except Exception:
                        pass
                print(f"--- server.log tail ---\n{studio.log_tail()}")
            finally:
                if session:
                    session.close()
    finally:
        studio.stop()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reel Director studio end-to-end run")
    ap.add_argument("--project", type=Path, default=WORK / "project")
    ap.add_argument("--port", type=int, default=0, help="default: a free port")
    ap.add_argument("--preroll", type=float, default=fake.PREROLL, help="room tone before each read (s)")
    ap.add_argument("--headed", action="store_true", help="show the Chrome windows")
    ap.add_argument("--scale", type=float, default=1.0, help="screenshot device scale factor")
    ap.add_argument("--qa-timeout", type=float, default=300)
    ap.add_argument("--build-timeout", type=float, default=1800)
    ap.add_argument("--skip-import", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args(argv)
    ck, t0 = Checker(), time.time()
    out = run(args, ck)
    report = {"ok": not ck.failures, "seconds": round(time.time() - t0), **out,
              "checks": [asdict(c) for c in ck.checks]}
    (WORK / "report.json").write_text(json.dumps(report, indent=2, default=str))
    passed = sum(c.ok for c in ck.checks)
    print(f"\n{passed}/{len(ck.checks)} checks passed, {len(ck.failures)} failed, {len(ck.warnings)} warnings "
          f"in {report['seconds']}s")
    for c in ck.failures:
        print(f"  FAIL {c.name}  ({c.detail})")
    for c in ck.warnings:
        print(f"  WARN {c.name}  ({c.detail})")
    print(f"screens: {WORK / 'screens'}\nreport:  {WORK / 'report.json'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
