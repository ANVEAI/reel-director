"""Studio project folder: which takes exist, which is pinned, where their files live.

  DIR/project.json        {"script": "/abs/path/script.json"}  (script media stays relative to it)
  DIR/takes.json          {"hook": [{"src": "raw/hook-1.mp4", "pin": false}]}   input to prep
  DIR/raw/<take>.mp4      normalized take;  DIR/raw/orig/<take>.<ext> the upload as received
  DIR/qa/<take>.json      QA report (+ <take>.words.json)
  DIR/raw/discarded/      discarded takes, never hard-deleted

Take names are <shot>-<n>; n is never reused, even after a discard. Every takes.json change
happens under one lock and lands with an atomic rename.
"""
import fcntl
import json
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path

from ..schema import Script, ScriptError, load_script

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TAKE_NAME = re.compile(r"^(?P<shot>[A-Za-z0-9][A-Za-z0-9_-]*)-(?P<n>\d+)$")
UPLOAD_EXTS = ("mp4", "webm", "mov")


class ProjectError(ValueError):
    pass


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.part")   # never shared by two writers
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def build_candidates(entries: list[dict], reports: dict[str, dict]) -> list[dict]:
    """Takes the build may pick from: pinned ones and every take QA didn't send back for a retake.

    The picker scores only the read, so a clipped or noisy take with a tidier read would beat a
    clean one; QA already knows better. An unpinned take needs a QA report: one whose check
    crashed (no frames, no audio) never ships silently in place of reviewed ones (the studio only
    lets ready takes be pinned). A shot whose reviewed takes are all retakes still builds with
    them (the studio blocks Build until the creator records again or pins one).
    """
    reviewed = [e for e in entries if e.get("pin") or reports.get(e["name"])]
    good = [e for e in reviewed if e.get("pin") or reports[e["name"]].get("verdict") != "retake"]
    return good or reviewed


def best_take(entries: list[dict], reports: dict[str, dict]) -> str | None:
    """The take the pipeline will use: computed from the same build_candidates the build snapshot
    uses, so the studio's star never points at a different take than the build picks. Within
    them the pinned one wins, else the best score_take score (ties go to the later take, as in
    timeline.pick_take)."""
    cands = build_candidates(entries, reports)
    pinned = [e["name"] for e in cands if e.get("pin")]
    if pinned:
        return pinned[-1]
    best = None
    for e in cands:
        score = reports[e["name"]]["script"]["score"]   # every unpinned candidate has a report
        if best is None or score >= best[1]:
            best = (e["name"], score)
    return best[0] if best else None


class Project:
    def __init__(self, root: Path, script: Path | None = None):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        meta = self.root / "project.json"
        if meta.exists():
            known = Path(json.loads(meta.read_text())["script"])
            if script and Path(script).resolve() != known:
                raise ProjectError(f"{self.root} belongs to {known}; use a new --project folder for {script}")
            self.script_path = known
        elif script:
            self.script_path = Path(script).resolve()
        else:
            raise ProjectError(f"{self.root} is not a studio project (no project.json) and no script was given")
        self._script, self._mtime, self.script_error = None, None, None
        self.script()   # fail now, before anyone records, if the script is broken or unsafe
        for d in (self.raw, self.orig, self.qa_dir, self.discarded):
            d.mkdir(parents=True, exist_ok=True)
        if not meta.exists():
            _write_json(meta, {"script": str(self.script_path)})

    raw = property(lambda self: self.root / "raw")
    orig = property(lambda self: self.root / "raw" / "orig")
    qa_dir = property(lambda self: self.root / "qa")
    discarded = property(lambda self: self.root / "raw" / "discarded")
    takes_file = property(lambda self: self.root / "takes.json")

    # --- script ---------------------------------------------------------------------------
    def script(self) -> Script:
        """The script, reloaded when the file changes. A broken edit keeps the last good one."""
        try:
            mtime = self.script_path.stat().st_mtime_ns
        except OSError as e:
            if self._script is None:
                raise ProjectError(f"can't read script {self.script_path}: {e.strerror}") from None
            self.script_error = f"script file missing: {self.script_path}"
            return self._script
        if mtime != self._mtime:
            try:
                s = load_script(self.script_path)
                bad = [sh.id for sh in s.shots if not SAFE_ID.match(sh.id)]
                if bad:
                    raise ScriptError(f"shot id(s) {bad} can't name files: use letters, digits, '-' or '_'")
                self._script, self.script_error = s, None
            except (ScriptError, ValueError, KeyError) as e:
                if self._script is None:
                    raise
                self.script_error = str(e)
            self._mtime = mtime
        return self._script

    def check_shot(self, shot: str) -> str:
        if shot not in {s.id for s in self.script().shots}:
            raise ProjectError(f"unknown shot {shot!r}")
        return shot

    # --- takes.json -----------------------------------------------------------------------
    @contextmanager
    def _locked(self):
        """This process's lock plus an flock on DIR/.takes.lock, so a second studio (or a CLI)
        on the same folder can't lose a take to an interleaved read-modify-write."""
        with self.lock, open(self.root / ".takes.lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def takes(self) -> dict[str, list[dict]]:
        """{"hook": [{"name": "hook-1", "src": "raw/hook-1.mp4", "pin": False}, ...]}"""
        with self.lock:
            raw = json.loads(self.takes_file.read_text()) if self.takes_file.exists() else {}
        return {sid: [{"name": Path(t["src"]).stem, "src": t["src"], "pin": bool(t.get("pin"))} for t in entries]
                for sid, entries in raw.items()}

    def _save(self, takes: dict[str, list[dict]]) -> None:
        _write_json(self.takes_file, {sid: [{"src": t["src"], "pin": t["pin"]} for t in entries]
                                      for sid, entries in takes.items() if entries})

    def find(self, name: str) -> tuple[str, dict]:
        if not TAKE_NAME.match(name or ""):
            raise ProjectError(f"bad take name {name!r}")
        for sid, entries in self.takes().items():
            for t in entries:
                if t["name"] == name:
                    return sid, t
        raise ProjectError(f"no take {name!r}")

    def _used_numbers(self, shot: str) -> set[int]:
        stems = [p.name.split(".")[0] for d in (self.raw, self.orig, self.qa_dir) for p in d.iterdir()]
        stems += [p.name.split(".")[0] for p in self.discarded.rglob("*")]
        stems += [t["name"] for t in self.takes().get(shot, [])]
        return {int(m["n"]) for s in stems if (m := TAKE_NAME.match(s)) and m["shot"] == shot}

    def reserve(self, shot: str, ext: str) -> tuple[str, Path]:
        """New take name and an exclusively created file for the upload to stream into."""
        self.check_shot(shot)
        if ext not in UPLOAD_EXTS:
            raise ProjectError(f"unsupported extension {ext!r} (use one of {', '.join(UPLOAD_EXTS)})")
        with self._locked():
            n = max(self._used_numbers(shot), default=0) + 1
            for _ in range(100):    # a name another process took first: try the next one
                name, path = f"{shot}-{n}", self.orig / f"{shot}-{n}.{ext}"
                try:
                    path.open("xb").close()
                    return name, path
                except FileExistsError:
                    n += 1
        raise ProjectError(f"could not reserve a take name for {shot!r}")

    def add(self, shot: str, name: str) -> None:
        """Register a fully received take (pending until its normalized file exists)."""
        with self._locked():
            takes = self.takes()
            takes.setdefault(shot, []).append({"name": name, "src": f"raw/{name}.mp4", "pin": False})
            self._save(takes)

    def set_pin(self, name: str, pin: bool) -> None:
        """Pin one take of a shot (unpinning its others), or unpin it."""
        with self._locked():
            shot, _ = self.find(name)
            takes = self.takes()
            for t in takes[shot]:
                if pin:
                    t["pin"] = t["name"] == name
                elif t["name"] == name:
                    t["pin"] = False
            self._save(takes)

    def discard(self, name: str) -> list[str]:
        """Drop a take from takes.json and move its files under raw/discarded/."""
        with self._locked():
            shot, _ = self.find(name)
            takes = self.takes()
            takes[shot] = [t for t in takes[shot] if t["name"] != name]
            self._save(takes)
            return self.sweep(name)

    def sweep(self, name: str) -> list[str]:
        """Move whatever files a take has into raw/discarded/ (also used if a check finishes late)."""
        moved = []
        with self.lock:
            for src_dir, dst_dir in ((self.raw, self.discarded), (self.orig, self.discarded / "orig"),
                                     (self.qa_dir, self.discarded / "qa")):
                for p in src_dir.glob(f"{name}.*"):
                    if p.is_file() and p.name.split(".")[0] == name:
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        os.replace(p, dst_dir / p.name)
                        moved.append(str((dst_dir / p.name).relative_to(self.root)))
        return moved

    def is_live(self, name: str) -> bool:
        try:
            self.find(name)
            return True
        except ProjectError:
            return False

    # --- files ----------------------------------------------------------------------------
    def normalized(self, name: str) -> Path:
        return self.raw / f"{name}.mp4"

    def original(self, name: str) -> Path | None:
        return next((p for p in sorted(self.orig.glob(f"{name}.*")) if p.suffix[1:] in UPLOAD_EXTS
                     and p.stem == name), None)

    def capture_file(self, name: str) -> Path:
        return self.orig / f"{name}.capture.json"

    def qa_file(self, name: str) -> Path:
        return self.qa_dir / f"{name}.json"

    def qa(self, name: str) -> dict | None:
        p = self.qa_file(name)
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except (OSError, json.JSONDecodeError):
            return None
