"""Studio e2e plumbing: the server subprocess and its JSON API, and one fake-device Chrome per take.

Recording is scheduled against the fake mic, which starts playing its wav when getUserMedia opens
it (page load), not when recording starts. A passive init script logs getUserMedia opens and
MediaRecorder start/stop times (it calls straight through and changes nothing), and Space is
pressed so recording starts ~1 s before the speech. The real lead-in is then measured in the
uploaded file and fed back, so later takes land on target even if the first guess was off.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples" / "demo" / "script.json"
VIEWPORT = {"width": 1440, "height": 900}   # laptop screen, per the studio spec
MIME_PREFS = ["video/mp4;codecs=avc3.640033,mp4a.40.2", "video/mp4;codecs=avc3,mp4a.40.2",   # recorder.js order
              "video/mp4;codecs=avc1.640033,mp4a.40.2", "video/mp4;codecs=avc1,mp4a.40.2", "video/mp4",
              "video/webm;codecs=h264,opus", "video/webm;codecs=vp9,opus", "video/webm"]
VIDEO_EXTS = {".mp4", ".webm", ".mov"}
LEAD_TARGET = 1.2   # seconds of room tone before the first word in a recorded take
MIN_LEAD = 0.3      # below this the first word was (or nearly was) cut off: retake

INSTRUMENT_JS = r"""
(() => {
  const log = window.__e2e = {opens: [], recorders: [], starts: [], stops: [], errors: []};
  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) {
    const gum = md.getUserMedia.bind(md);
    md.getUserMedia = async (c) => {
      const s = await gum(c);
      const a = s.getAudioTracks()[0], v = s.getVideoTracks()[0];
      log.opens.push({t: Date.now(), constraints: JSON.parse(JSON.stringify(c || {})),
        audio: a ? {label: a.label, settings: a.getSettings()} : null,
        video: v ? {label: v.label, settings: v.getSettings()} : null});
      return s;
    };
  }
  if (window.MediaRecorder) {
    const MR = window.MediaRecorder;
    window.MediaRecorder = class extends MR {
      constructor(stream, opts) {
        super(stream, opts);
        const a = stream.getAudioTracks()[0], v = stream.getVideoTracks()[0];
        log.recorders.push({t: Date.now(), mime: this.mimeType, opts: JSON.parse(JSON.stringify(opts || {})),
          audio: a ? a.getSettings() : null, video: v ? v.getSettings() : null});
        this.addEventListener('start', () => log.starts.push(Date.now()));
        this.addEventListener('stop', () => log.stops.push(Date.now()));
      }
    };
  }
  addEventListener('error', e => log.errors.push(String(e.message)));
  addEventListener('unhandledrejection', e => log.errors.push(String((e.reason && e.reason.message) || e.reason)));
})();
"""

READY_JS = """() => {
  const e = window.__e2e, st = window.__studio && window.__studio.state && window.__studio.state();
  if (!st || st.ready === false || !e || !e.opens.some(o => o.audio)) return false;
  return [...document.querySelectorAll('video')].some(v => v.srcObject && v.videoWidth > 0);
}"""


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Studio:
    """`python -m reel_director studio` as a subprocess, plus its HTTP API."""

    def __init__(self, project: Path, port: int, log_path: Path):
        self.project, self.port, self.log_path = project, port, log_path
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout: float = 60) -> None:
        cmd = [sys.executable, "-m", "reel_director", "studio", str(SCRIPT), "--project", str(self.project),
               "--port", str(self.port), "--no-open"]
        self._log = open(self.log_path, "w")
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=self._log, stderr=subprocess.STDOUT,
                                     env={**os.environ, "PYTHONUNBUFFERED": "1",
                                          "RD_MEDIA_OFFLINE": "1"})   # v4 B-roll: no network in the e2e build
        end = time.time() + timeout
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"studio exited with {self.proc.returncode}:\n{self.log_tail()}")
            try:
                if self.request("GET", "/api/project")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"studio not answering on {self.url} after {timeout:.0f}s:\n{self.log_tail()}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc:
            self._log.close()

    def log_tail(self, n: int = 30) -> str:
        return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-n:]) if self.log_path.exists() else ""

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict | None = None) -> tuple[int, dict, bytes]:
        req = urllib.request.Request(self.url + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def get(self, path: str) -> dict:
        status, _, body = self.request("GET", path)
        if status != 200:
            raise RuntimeError(f"GET {path} -> {status}: {body[:300]!r}")
        return json.loads(body)

    def post(self, path: str, body: bytes = b"", headers: dict | None = None) -> tuple[int, dict]:
        status, _, raw = self.request("POST", path, body, headers)
        try:
            return status, json.loads(raw or b"{}")
        except ValueError:
            return status, {"raw": raw[:300].decode(errors="replace")}

    def shot(self, sid: str) -> dict:
        return next(s for s in self.get("/api/project")["shots"] if s["id"] == sid)

    def take(self, name: str) -> dict | None:
        for s in self.get("/api/project")["shots"]:
            for t in s["takes"]:
                if t["name"] == name:
                    return t
        return None

    def take_shots(self) -> dict[str, str]:
        """Every take name -> its shot id."""
        return {t["name"]: s["id"] for s in self.get("/api/project")["shots"] for t in s["takes"]}

    def wait_new_take(self, sid: str, before: set[str], timeout: float) -> str:
        end = time.time() + timeout
        while time.time() < end:
            new = {n: s for n, s in self.take_shots().items() if n not in before}
            if new:
                name, got = sorted(new.items())[0]
                if got != sid:
                    raise RuntimeError(f"take {name} landed in shot {got!r}, expected {sid!r}")
                return name
            time.sleep(0.4)
        raise TimeoutError(f"no new take for shot {sid!r} after {timeout:.0f}s (upload failed?)")

    def wait_checked(self, name: str, timeout: float) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            t = self.take(name)
            if t and t.get("status") in ("ready", "error"):
                return t
            time.sleep(1.0)
        raise TimeoutError(f"take {name} still checking after {timeout:.0f}s")


def chrome_args(mjpeg: Path, wav: Path) -> list[str]:
    return ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-video-capture={mjpeg}", f"--use-file-for-fake-audio-capture={wav}%noloop",
            "--autoplay-policy=no-user-gesture-required"]   # meters' AudioContext + the reel player


@dataclass
class Session:
    browser: object
    page: object
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)

    def close(self) -> None:
        self.browser.close()


def open_browser(pw, studio: Studio, mjpeg: Path, wav: Path, headed: bool, scale: float) -> Session:
    browser = pw.chromium.launch(channel="chrome", headless=not headed, args=chrome_args(mjpeg, wav))
    ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=scale)
    ctx.grant_permissions(["camera", "microphone"], origin=studio.url)
    ctx.add_init_script(INSTRUMENT_JS)
    page = ctx.new_page()
    s = Session(browser, page)
    page.on("console", lambda m: m.type == "error" and not m.location.get("url", "").endswith("/favicon.ico")
            and s.console_errors.append(m.text))
    page.on("pageerror", lambda e: s.page_errors.append(str(e)))
    return s


def blur(page) -> None:
    page.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")


def until(page, t: float) -> None:
    """Wait (pumping page events) until wall-clock time t."""
    page.wait_for_timeout(max(0.0, t - time.time()) * 1000)


def speech_lead(path: Path) -> float:
    """Seconds of room tone before the first word of a recorded file (0 if speech starts at once)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                          "asetpts=PTS-STARTPTS,silencedetect=n=-40dB:d=0.25", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"silence_start: (-?[\d.e-]+).*?silence_end: ([\d.]+)", err, re.S)
    return float(m.group(2)) if m and float(m.group(1)) < 0.05 else 0.0


@dataclass
class TakeRun:
    fake: str
    shot: str
    name: str = ""            # the server's take name
    attempts: int = 0
    pressed: float = 0.0      # wall clock, seconds
    started: float = 0.0
    stopped: float = 0.0
    lead: float = 0.0         # measured room tone before the first word in the upload
    instrument: dict = field(default_factory=dict)
    state: object = None      # window.__studio.state() right before recording
    line_shown: bool = False
    screens: list[str] = field(default_factory=list)


class Recorder:
    """Records takes through the real UI, adapting to the measured countdown and mic-start offset."""

    def __init__(self, studio: Studio, screens: Path):
        self.studio, self.screens = studio, screens
        self.countdown = 3.0      # spec: 3-2-1; replaced by the measured value after each take
        self.open_offset = 0.0    # real mic start minus logged getUserMedia resolve time
        self.shots = 0

    def shoot(self, page, label: str, stage: str) -> str:
        """Numbered screenshot (so the folder reads in run order); returns its file name."""
        self.shots += 1
        name = f"{self.shots:02d}-{label}-{stage}.png"
        page.screenshot(path=str(self.screens / name))
        return name

    def record(self, session: Session, take: dict, line: str, upload_timeout: float = 120) -> TakeRun:
        run = TakeRun(take["name"], take["shot"])
        page = session.page
        for attempt in range(1, 4):
            run.attempts = attempt
            if attempt == 1:
                page.goto(self.studio.url)
            else:
                page.reload()
            page.wait_for_function(READY_JS, timeout=45_000)
            page.evaluate("id => window.__studio.selectShot(id)", run.shot)
            page.wait_for_timeout(400)
            run.state = page.evaluate("() => window.__studio.state ? window.__studio.state() : null")
            run.line_shown = " ".join(line.split()) in " ".join(page.inner_text("body").split())
            run.screens.append(self.shoot(page, run.fake, "ready"))
            opened = page.evaluate("() => window.__e2e.opens.filter(o => o.audio).map(o => o.t)")[-1] / 1000
            press_at = opened + self.open_offset + take["speech_start"] - LEAD_TARGET - self.countdown
            if time.time() > press_at + 0.2:
                log(f"  {run.fake}: page ready {time.time() - press_at:.1f}s after the scheduled press; reloading "
                    f"(attempt {attempt})")
                continue
            n0 = page.evaluate("() => window.__e2e.starts.length")
            before = set(self.studio.take_shots())
            until(page, press_at)
            blur(page)
            run.pressed = time.time()
            page.keyboard.press("Space")
            if self.countdown > 1.5:
                page.wait_for_timeout(900)
                run.screens.append(self.shoot(page, run.fake, "countdown"))
            page.wait_for_function(f"() => window.__e2e.starts.length > {n0}", timeout=(self.countdown + 8) * 1000)
            run.started = page.evaluate("() => window.__e2e.starts.at(-1)") / 1000
            self.countdown = run.started - run.pressed
            # The mic may have restarted after the press (UI re-opened it): use the last open before start.
            opens = page.evaluate("() => window.__e2e.opens.filter(o => o.audio).map(o => o.t)")
            mic_start = max(t for t in opens if t / 1000 <= run.started) / 1000 + self.open_offset
            stop_at = mic_start + take["stop_at"]
            until(page, run.started + (stop_at - run.started) / 2)
            run.screens.append(self.shoot(page, run.fake, "recording"))
            n1 = page.evaluate("() => window.__e2e.stops.length")
            until(page, stop_at)
            blur(page)
            page.keyboard.press("Space")
            page.wait_for_function(f"() => window.__e2e.stops.length > {n1}", timeout=10_000)
            run.stopped = page.evaluate("() => window.__e2e.stops.at(-1)") / 1000
            run.name = self.studio.wait_new_take(run.shot, before, upload_timeout)
            run.screens.append(self.shoot(page, run.fake, "uploaded"))
            run.lead = speech_lead(self._uploaded_file(run.name))
            # Where the speech really was tells us when the mic file really started.
            self.open_offset += (run.started + run.lead - take["speech_start"]) - mic_start
            log(f"  {run.fake} -> {run.name}: countdown {self.countdown:.2f}s, lead {run.lead:.2f}s, "
                f"mic offset {self.open_offset:+.2f}s")
            if run.lead >= MIN_LEAD:
                break
            log(f"  {run.fake}: first word clipped (lead {run.lead:.2f}s); discarding {run.name} and retrying")
            self.studio.post(f"/api/takes/{run.name}/discard")
        else:
            raise RuntimeError(f"{run.fake}: could not record with the speech intact in 3 attempts")
        run.instrument = page.evaluate("() => window.__e2e")
        run.instrument["first_supported"] = page.evaluate(
            "prefs => prefs.find(m => MediaRecorder.isTypeSupported(m)) || null", MIME_PREFS)
        return run

    def _uploaded_file(self, name: str, timeout: float = 60) -> Path:
        """The take as uploaded (raw/orig) or normalized (raw/), whichever exists first."""
        end = time.time() + timeout
        while time.time() < end:
            hits = [p for p in sorted((self.studio.project / "raw" / "orig").glob(f"{name}.*"))
                    if p.suffix in VIDEO_EXTS] + sorted((self.studio.project / "raw").glob(f"{name}.mp4"))
            if hits and hits[0].stat().st_size > 0:
                time.sleep(0.3)   # let a still-being-written file settle
                return hits[0]
            time.sleep(0.3)
        raise TimeoutError(f"no file for take {name} under {self.studio.project / 'raw'}")

