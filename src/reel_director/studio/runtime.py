"""Studio runtime: take intake workers (normalize, then QA) and the one-button build.

Build (v2): prep (+ face tracks, + the background matte when the Studio option is on) -> compile (director +
council caps -> directed.json, face-aware layout, mixdown -> mix/mix.wav, page) -> render -> deliver (the step
keeps its UI name "master": picture + baked mix, verified -14 LUFS / -1.5 dBTP) -> review (QA gates on the
rendered master -> qa/report.json, before/after -> renders/before-after.png; with the "director" option the
headless editing director reviews it and up to 2 fix rounds rebuild, kept only when the score improves).
After each take's QA the creator profile (qa/creator.json, GET /api/creator) is refreshed for the coach.
Preview edit: the same worker, any time, even with zero takes: prep (only the takes so far) -> compile
(RECORD slots where a shot has no take) -> render at review quality -> renders/preview.mp4. It works in
<project>/preview/, so the last build's reel/, mix/ and prepped/ stay as they were.

Shared by the HTTP handlers. Heavy work (Whisper, the pipeline) runs as `python -m reel_director
...` subprocesses: mlx-whisper must load before torch in a process, so this one imports neither.
Takes are processed one at a time per stage, and Whisper never runs twice at once (QA vs prep).
"""
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from .. import capture
from .. import presets
from ..audio import MASTER_LUFS, MASTER_TP
from ..timing import estimate
from .broll import Broll
from .project import Project, best_take, build_candidates

QA_TIMEOUT = 900
# "delivery" is HyperFrames' high-quality encode; the master pass copies this video stream.
RENDER_ARGS = ["--quality", "delivery"]
PREVIEW_ARGS = ["--quality", "draft"]   # review quality: fast; the render carries the mix, no master pass
PREVIEW_LABEL = "Preview — slots show where you appear"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
HF_PROGRESS = "@hf-progress "         # HyperFrames' machine-readable progress lines
DELIVER = "@deliver "                  # `deliver` prints its measured result as one JSON line
DEFAULT_PRESET = "clean-pro"
BETA_PRESETS = ("desi-bilingual",)
OPTIONS = {"director": False, "matte": True}   # Studio toggles (studio-settings.json); matte: real-1 bg edges -100 %
LEARN_TIMEOUT = 120


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return round(float(out), 3) if out else 0.0


def _clean(word: str) -> str:
    return word.strip(".,!?;:\"'“”‘’()")


def _kill_tree(proc: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
    """Signal a tool and everything it started (HyperFrames runs Chrome and ffmpeg children)."""
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class Studio:
    """Project state shared by the request handlers and the background workers."""

    def __init__(self, project: Project, normalize=capture.normalize, check=None, learn=None):
        self.project = project
        # Changes on every server start: a tab opened against an earlier server reloads instead of
        # carrying stale state (an upload or poll that died with the old process) into the new one.
        self.boot = f"{os.getpid()}-{time.time_ns()}"
        self.normalize_fn = normalize
        self.check_fn = check or self._check_subprocess
        self.learn_fn = learn or (self._learn_subprocess if check is None else (lambda: None))
        self.lock = threading.Lock()      # status + build state
        self.mlx = threading.Lock()       # one Whisper process at a time (QA vs prep)
        self.status: dict[str, dict] = {}
        self.norm_q: queue.Queue = queue.Queue()
        self.qa_q: queue.Queue = queue.Queue()
        self.procs: set[subprocess.Popen] = set()
        self.log: deque[str] = deque(maxlen=40)
        self.build = {"state": "idle", "step": None, "result": None, "error": None}
        self.settings_file = project.root / "studio-settings.json"
        self.broll = Broll(project)        # v4: the B-roll panel over <project>/media.json

    # --- preset ---------------------------------------------------------------------------
    def _settings(self) -> dict:
        try:
            raw = json.loads(self.settings_file.read_text())
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def options(self) -> dict:
        """Studio toggles: director (editing director review + fix rounds), matte (background blur via the matte)."""
        raw = self._settings()
        return {k: bool(raw.get(k, v)) for k, v in OPTIONS.items()}

    def set_options(self, q: dict) -> tuple[int, dict]:
        vals = {k: str(q[k]).lower() in ("1", "true", "on", "yes") for k in OPTIONS if k in q}
        if not vals:
            return 400, {"error": f"name one of {sorted(OPTIONS)}, e.g. ?director=1"}
        with self.lock:
            if self.build["state"] == "running":
                return 409, {"error": "a build is running: change the options when it is done"}
        self.settings_file.write_text(json.dumps({**self._settings(), **vals}, indent=1))
        return 200, self.options()

    def creator(self) -> dict:
        """The creator profile `learn creator` wrote (qa/creator.json) for the framing coach, or null."""
        try:
            return {"profile": json.loads((self.project.qa_dir / "creator.json").read_text())}
        except (OSError, ValueError):
            return {"profile": None, "note": "no creator profile yet: it is made after the first take's check"}

    def preset(self) -> str:
        """The build's style preset: the Studio choice, else the script's style.preset, else clean-pro."""
        name = self._settings().get("preset")
        if not name:
            try:
                raw = json.loads(self.project.script_path.read_text())
                name = (raw.get("style") or {}).get("preset")
            except (OSError, ValueError, AttributeError):
                name = None
        return name if name in presets.PRESETS else DEFAULT_PRESET

    def set_preset(self, name: str) -> tuple[int, dict]:
        if name not in presets.PRESETS:
            return 400, {"error": f"unknown preset {name!r} (one of {sorted(presets.PRESETS)})"}
        with self.lock:
            if self.build["state"] == "running":
                return 409, {"error": "a build is running: change the preset when it is done"}
        self.settings_file.write_text(json.dumps({**self._settings(), "preset": name}, indent=1))
        return 200, {"preset": name}

    # --- take intake ----------------------------------------------------------------------
    def start(self) -> None:
        """Resume where a previous session stopped, then start the workers."""
        p = self.project
        for entries in p.takes().values():
            for t in entries:
                name = t["name"]
                if p.qa(name):
                    self._set(name, "ready")
                elif p.normalized(name).exists():
                    self._set(name, "checking", stage="queued")
                    self.qa_q.put(name)
                elif p.original(name):
                    self.enqueue(name)
                else:
                    self._set(name, "error", error="take files are missing")
        self._load_last_build()
        for target, q in ((self._normalize, self.norm_q), (self._qa, self.qa_q)):
            threading.Thread(target=self._worker, args=(target, q), daemon=True).start()

    def stop(self) -> None:
        for q in (self.norm_q, self.qa_q):
            q.put(None)
        for proc in list(self.procs):
            _kill_tree(proc)

    def enqueue(self, name: str) -> None:
        self._set(name, "checking", stage="queued")
        self.norm_q.put(name)

    def _set(self, name: str, status: str, stage: str | None = None, error: str | None = None) -> None:
        with self.lock:
            self.status[name] = {"status": status, "stage": stage, "error": error}

    def _worker(self, target, q: queue.Queue) -> None:
        while (name := q.get()) is not None:
            try:
                if self.project.is_live(name):
                    target(name)
            except Exception as e:   # one bad take must never stop the queue
                self._set(name, "error", error=str(e) or type(e).__name__)
                print(f"take {name}: {e}", file=sys.stderr, flush=True)
            if not self.project.is_live(name):   # discarded mid-check: tidy late files away
                self.project.sweep(name)

    def _normalize(self, name: str) -> None:
        p = self.project
        self._set(name, "checking", stage="normalizing")
        orig = p.original(name)
        if orig is None:
            raise capture.CaptureError("the original upload is missing")
        info = self.normalize_fn(orig, p.normalized(name))
        cap = p.capture_file(name)
        if cap.exists():
            meta = json.loads(cap.read_text())
            cap.write_text(json.dumps({**meta, "normalized": info}, indent=1))
        self._set(name, "checking", stage="queued")
        self.qa_q.put(name)

    def _qa(self, name: str) -> None:
        self._set(name, "checking", stage="checking")
        with self.mlx:
            self.check_fn(name)
        if self.project.qa(name) is None:
            raise RuntimeError("the take check wrote no report")
        self._set(name, "ready")
        try:
            self.learn_fn()        # the coach's creator profile; optional, never fails a take
        except Exception as e:
            print(f"creator profile: {e}", file=sys.stderr, flush=True)

    def _learn_subprocess(self) -> None:
        rc, lines = self.spawn([sys.executable, "-m", "reel_director", "learn", "creator", str(self.project.root)],
                               timeout=LEARN_TIMEOUT)
        if rc != 0:
            raise RuntimeError(lines[-1] if lines else f"exit {rc}")

    def _check_subprocess(self, name: str) -> None:
        p = self.project
        shot, _ = p.find(name)
        cmd = [sys.executable, "-m", "reel_director", "check-take", str(p.normalized(name)), "--script",
               str(p.script_path), "--shot", shot, "--out", str(p.qa_file(name))]
        if orig := p.original(name):
            cmd += ["--source", str(orig)]
        if p.capture_file(name).exists():
            cmd += ["--capture-info", str(p.capture_file(name))]
        rc, lines = self.spawn(cmd, timeout=QA_TIMEOUT)
        if rc != 0:
            raise RuntimeError("take check failed: " + (lines[-1] if lines else f"exit {rc}"))

    def spawn(self, cmd: list[str], on_line=None, timeout: float | None = None) -> tuple[int, list[str]]:
        """Run a tool, streaming its output lines; killed when the studio stops or on timeout."""
        env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                                cwd=self.project.root, errors="replace", start_new_session=True)
        self.procs.add(proc)
        timer = threading.Timer(timeout, _kill_tree, (proc, signal.SIGKILL)) if timeout else None
        if timer:
            timer.start()
        lines: deque[str] = deque(maxlen=200)
        try:
            for raw in proc.stdout:
                line = ANSI.sub("", raw).rstrip()
                if line.strip():
                    lines.append(line)
                    if on_line:
                        on_line(line)
            return proc.wait(), list(lines)
        finally:
            if timer:
                timer.cancel()
            self.procs.discard(proc)

    # --- views ----------------------------------------------------------------------------
    def take_view(self, t: dict) -> dict:
        with self.lock:
            st = dict(self.status.get(t["name"], {"status": "checking", "stage": "queued", "error": None}))
        qa = self.project.qa(t["name"]) if st["status"] != "checking" else None
        return {"name": t["name"], "src": t["src"], "url": f"/media/{t['src']}", "pin": t["pin"], "qa": qa, **st}

    def project_view(self) -> dict:
        s = self.project.script()
        takes = self.project.takes()
        shots = []
        for shot in s.shots:
            entries = takes.get(shot.id, [])
            views = [self.take_view(t) for t in entries]
            reports = {v["name"]: v["qa"] for v in views if v["qa"] and v["status"] == "ready"}
            cues = []
            for c in shot.cues:
                span = shot.words[c.start_word:c.end_word + 1]
                cue = {"type": c.type, "at_words": " ".join(_clean(w.text) for w in span)}
                cue.update({k: c.params[k] for k in ("text", "scale") if k in c.params})
                if c.type == "sfx":
                    cue["src"] = Path(c.params["src"]).name
                cues.append(cue)
            shots.append({"id": shot.id, "line": shot.line, "estimate_s": round(estimate(shot)[-1].end, 2),
                          "cues": cues, "takes": views, "best": best_take(entries, reports)})
        return {"title": s.title, "width": s.width, "height": s.height, "fps": s.fps, "shots": shots,
                "preset": self.preset(), "presets": list(presets.PRESETS), "beta_presets": list(BETA_PRESETS),
                "options": self.options(),
                "build": self.build_status(), "script_error": self.project.script_error,
                "project": str(self.project.root), "boot": self.boot}

    # --- build ----------------------------------------------------------------------------
    def build_status(self) -> dict:
        with self.lock:
            return {**self.build, "log": list(self.log)}

    def _load_last_build(self) -> None:
        r = self.project.root / "renders"
        if (r / "reel-master.json").exists() and (r / "reel-master.mp4").exists():
            try:
                result = json.loads((r / "reel-master.json").read_text())
            except ValueError:
                return
            self.build = {"state": "done", "step": "master", "result": result, "error": None}
            log = self.project.root / "build.log"
            if log.exists():
                self.log.extend(log.read_text(errors="replace").splitlines()[-40:])

    def start_build(self, preview: bool = False) -> tuple[int, dict]:
        """The reel build, or (preview=True) the preview edit; one at a time in the same worker."""
        with self.lock:
            if self.build["state"] == "running":
                return 409, {"error": "a build is already running"}
            busy = sorted(n for n, s in self.status.items() if s["status"] == "checking" and self.project.is_live(n))
            if busy and not preview:     # a preview just leaves takes still being checked out
                return 409, {"error": f"takes still being checked: {', '.join(busy)}"}
            self.build = {"state": "running", "kind": "preview" if preview else "reel", "step": None, "result": None,
                          "error": None, "started": time.time()}
            self.log.clear()
        threading.Thread(target=self._preview if preview else self._build, daemon=True).start()
        return 202, self.build_status()

    def _snapshot(self, dest: Path | None = None) -> dict[str, list[str]]:
        """Freeze the build's input: usable takes of current shots, in order (build-takes.json).
        Takes QA marked "retake" stay out while the shot has a better one (see build_candidates).
        Takes still being checked are left out (their normalized file may be half written)."""
        p = self.project
        ids = [s.id for s in p.script().shots]
        takes = p.takes()
        with self.lock:
            checking = {n for n, st in self.status.items() if st["status"] == "checking"}
        snap, data = {}, {}
        for sid in ids:
            usable = [t for t in takes.get(sid, []) if p.normalized(t["name"]).exists() and t["name"] not in checking]
            usable = build_candidates(usable, {t["name"]: p.qa(t["name"]) for t in usable})
            if usable:
                snap[sid] = [t["name"] for t in usable]
                data[sid] = [{"src": t["src"], "pin": t["pin"]} for t in usable]
        (dest or p.root / "build-takes.json").write_text(json.dumps(data, indent=2))
        return snap

    def _step(self, step: str, cmd: list[str], logf) -> list[str]:
        with self.lock:
            self.build.update(step=step, progress=None)

        def emit(line: str) -> None:
            """Everything goes to build.log; the UI's tail gets the human lines and a progress %."""
            logf.write(line + "\n")
            logf.flush()
            with self.lock:
                if line.startswith(HF_PROGRESS):
                    try:
                        self.build["progress"] = float(json.loads(line[len(HF_PROGRESS):])["pct"])
                    except (ValueError, KeyError, TypeError):
                        pass
                elif "[Render:trace]" not in line and not line.startswith(DELIVER):
                    self.log.append(line)
        emit(f"== {step}: {' '.join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))}")
        rc, lines = self.spawn(cmd, on_line=emit)
        if rc != 0:
            raise RuntimeError(f"{step} failed: {lines[-1] if lines else f'exit {rc}'}")
        return lines

    def _build(self) -> None:
        p, py = self.project, [sys.executable, "-m", "reel_director"]
        r = p.root / "renders"
        r.mkdir(exist_ok=True)
        part = r / ".reel-master.part.mp4"
        try:
            with open(p.root / "build.log", "w") as logf:
                snap, opts = self._snapshot(), self.options()
                with self.mlx:
                    self._step("prep", py + ["prep", str(p.root / "build-takes.json"), "--out", str(p.root / "prepped")]
                               + (["--matte"] if opts["matte"] else []), logf)
                preset = self.preset()
                comp = self._step("compile", py + ["compile", str(p.script_path), "--out", str(p.root / "reel"),
                                                   "--takes", str(p.root / "prepped" / "takes.json"),
                                                   "--preset", preset], logf)
                hf = shutil.which("hyperframes")
                if not hf:
                    raise RuntimeError("hyperframes CLI not found on PATH")
                self._step("render", [hf, "render", str(p.root / "reel"), "-o", str(r / "reel.mp4"),
                                      *RENDER_ARGS], logf)
                out = self._step("master", py + ["deliver", str(r / "reel.mp4"), str(p.root / "mix" / "mix.wav"),
                                                  str(part)], logf)
                os.replace(part, r / "reel-master.mp4")   # a player mid-stream keeps the old file
                qa = self._review(logf, opts["director"])
                result = self._result(snap, "\n".join(out), qa)
                result["preset"] = preset
                result["build_s"] = round(time.time() - self.build.get("started", time.time()), 1)   # takes -> reel
                result["director"] = [ln.strip() for ln in comp if ln.strip().startswith(("director:", "note:", "mix:"))]
                (r / "reel-master.json").write_text(json.dumps(result, indent=1))
            with self.lock:
                self.build.update(state="done", result=result, finished=time.time())
        except Exception as e:
            with self.lock:
                self.build.update(state="error", error=str(e), finished=time.time())
                self.log.append(f"error: {e}")
        finally:
            if part.exists():
                part.unlink()

    @staticmethod
    def _shots(snap: dict[str, list[str]], timeline: Path) -> list[dict]:
        """Per shot: the take the compiler chose (None = a RECORD slot), its cuts and coverage."""
        shots = []
        for s in json.loads(timeline.read_text())["shots"]:
            names, k = snap.get(s["id"], []), s["take"]
            take = names[k] if k is not None and k < len(names) else None
            shots.append({"id": s["id"], "take": take, "cuts": max(0, len(s["clips"]) - 1) if s["recorded"] else 0,
                          "coverage": s["coverage"]})
        return shots

    def _preview(self) -> None:
        """Preview edit: the directed reel with the takes so far and RECORD slots for the rest."""
        p, py = self.project, [sys.executable, "-m", "reel_director"]
        r, work = p.root / "renders", p.root / "preview"
        r.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        part = work / "preview.mp4"     # moved into renders/ only once the render is complete
        try:
            with open(work / "build.log", "w") as logf:
                snap = self._snapshot(p.root / "preview-takes.json")
                preset = self.preset()
                cmd = py + ["compile", str(p.script_path), "--out", str(work / "reel"), "--preset", preset]
                if snap:
                    with self.mlx:
                        self._step("prep", py + ["prep", str(p.root / "preview-takes.json"),
                                                 "--out", str(work / "prepped")], logf)
                    cmd += ["--takes", str(work / "prepped" / "takes.json")]
                comp = self._step("compile", cmd, logf)
                hf = shutil.which("hyperframes")
                if not hf:
                    raise RuntimeError("hyperframes CLI not found on PATH")
                part.unlink(missing_ok=True)
                self._step("render", [hf, "render", str(work / "reel"), "-o", str(part), *PREVIEW_ARGS], logf)
                if not part.exists():
                    raise RuntimeError("render wrote no video")
                os.replace(part, r / "preview.mp4")
                shots = self._shots(snap, work / "reel" / "timeline.json")
                result = {"video": "/media/renders/preview.mp4", "duration": _duration(r / "preview.mp4"),
                          "preview": True, "label": PREVIEW_LABEL, "preset": preset, "shots": shots,
                          "slots": sum(s["take"] is None for s in shots),
                          "build_s": round(time.time() - self.build.get("started", time.time()), 1),
                          "director": [ln.strip() for ln in comp
                                       if ln.strip().startswith(("director:", "note:", "mix:"))]}
                (r / "preview.json").write_text(json.dumps(result, indent=1))
            with self.lock:
                self.build.update(state="done", result=result, finished=time.time())
        except Exception as e:
            with self.lock:
                self.build.update(state="error", error=str(e), finished=time.time())
                self.log.append(f"error: {e}")

    def _review(self, logf, director: bool) -> dict | None:
        """QA gates + before/after (+ the editing director and its fix rounds). The reel is already delivered:
        a review that fails is reported in the result, never fatal."""
        p, py = self.project, [sys.executable, "-m", "reel_director"]
        cmd = py + ["review", str(p.root)]
        if director:
            cmd += ["--director", "--rounds", "2", "--takes", str(p.root / "prepped" / "takes.json")]
        try:
            self._step("review", cmd, logf)
        except Exception as e:
            with self.lock:
                self.log.append(f"review: {e}")
            return {"error": str(e)}
        return qa_view(p.root)

    def _result(self, snap: dict[str, list[str]], master_out: str, qa: dict | None = None) -> dict:
        d = next((json.loads(ln[len(DELIVER):]) for ln in master_out.splitlines() if ln.startswith(DELIVER)), None)
        d = (qa or {}).get("deliver") or d       # a director round's master replaced the first one
        m = re.search(r"(-?[\d.]+) -> (-?[\d.]+) LUFS, true peak (-?[\d.]+) dBTP", master_out)
        shots = self._shots(snap, self.project.root / "reel" / "timeline.json")
        master = self.project.root / "renders" / "reel-master.mp4"
        lufs = d["lufs"] if d else float(m[2]) if m else None
        tp = d["true_peak"] if d else float(m[3]) if m else None
        return {"video": "/media/renders/reel-master.mp4", "duration": _duration(master),
                "lufs": lufs, "true_peak": tp, "target_lufs": MASTER_LUFS, "target_true_peak": MASTER_TP,
                "av_offset_ms": d.get("av_start_offset_ms") if d else None, "shots": shots,
                "credits": self.broll.write_credits(),        # v4: renders/reel.credits.txt beside the reel
                "qa": {k: v for k, v in (qa or {}).items() if k != "deliver"} or None}


def qa_view(root: Path) -> dict | None:
    """What the result dialog shows from qa/report.json: verdict, score, gate list, director, before/after."""
    try:
        rep = json.loads((root / "qa" / "report.json").read_text())
    except (OSError, ValueError):
        return None
    d = rep.get("director") or None
    rounds = rep.get("rounds") or []
    final = next((h for h in rounds if h.get("dir") == rep.get("final")), None)
    stamp = int((root / "renders" / "before-after.png").stat().st_mtime) if (root / "renders" / "before-after.png").exists() else 0
    return {"verdict": rep.get("verdict"), "score": rep.get("score"), "gate_score": rep.get("gate_score"),
            "gates": [{k: g.get(k) for k in ("id", "level", "message")} for g in rep.get("gates", [])],
            "director": {k: d.get(k) for k in ("status", "score", "summary", "note", "issues")} if d else None,
            "rounds": [{k: h.get(k) for k in ("round", "score_before", "score_after", "stopped")} for h in rounds],
            "final": rep.get("final", "."), "deliver": (final or {}).get("deliver"),
            "before_after": f"/media/renders/before-after.png?v={stamp}" if stamp else None,
            "overlay": "/media/qa/overlay.png" if (root / "qa" / "overlay.png").exists() else None}
