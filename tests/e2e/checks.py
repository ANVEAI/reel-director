"""Assertions for the studio e2e run: a checker that records every result, and media measurements.

Hard checks are the spec's contract (QA verdicts, capture rules, normalization, master loudness,
picker choices); soft checks are quality hints that are reported but never fail the run.
"""
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

VERDICTS = {"great", "ok", "retake"}
REPORT_KEYS = {
    "": {"take", "shot", "created", "video", "audio", "script", "checks", "verdict"},
    "video": {"width", "height", "fps", "duration", "effective_9x16", "luma_mean", "luma_p5", "luma_p95", "blur",
              "vfr_source"},
    "audio": {"sample_rate", "peak_dbfs", "clipped_samples", "lufs", "noise_floor_db", "snr_db"},
    "script": {"coverage", "misread", "missing", "junk", "kept_seconds", "cuts", "score"},
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    soft: bool = False


class Checker:
    """Collects PASS/FAIL/WARN results and prints each as it happens."""

    def __init__(self):
        self.checks: list[Check] = []

    def __call__(self, name: str, ok, detail: str = "", soft: bool = False) -> bool:
        c = Check(name, bool(ok), str(detail), soft)
        self.checks.append(c)
        mark = "PASS" if c.ok else "WARN" if soft else "FAIL"
        print(f"    {mark} {name}" + (f"  ({c.detail})" if c.detail else ""), flush=True)
        return c.ok

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.soft]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.soft]


# ---------- measurements ----------

def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    data["v"] = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    data["a"] = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    return data


def ratio(r: str) -> float:
    num, _, den = (r or "0/1").partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


def loudness(path: Path) -> dict:
    """Integrated loudness (LUFS) and true peak (dBTP) by ffmpeg's EBU R128 meter."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                          "ebur128=peak=true:framelog=quiet", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = err[err.rfind("Summary:"):]
    return {"lufs": float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1)),
            "true_peak": float(re.search(r"True peak:\s+Peak:\s+(-?[\d.inf]+)", summary).group(1))}


def peak_db(path: Path) -> float:
    """Sample peak (dBFS) over all audio channels."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                          "astats=measure_overall=Peak_level:measure_perchannel=none", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"Peak level dB: (-?[\d.]+|-inf)", err)[-1])


def faststart(path: Path) -> bool:
    """moov atom before mdat, so the browser can start playing before the whole file arrives."""
    order, pos, size = [], 0, path.stat().st_size
    with open(path, "rb") as f:
        while pos < size and len(order) < 50:
            f.seek(pos)
            head = f.read(16)
            n, kind = int.from_bytes(head[:4], "big"), head[4:8].decode("latin-1")
            n = int.from_bytes(head[8:16], "big") if n == 1 else size - pos if n == 0 else n
            order.append(kind)
            if n < 8:
                break
            pos += n
    return "moov" in order and "mdat" in order and order.index("moov") < order.index("mdat")


def thumb(path: Path, at: float | None = None) -> np.ndarray:
    """27x48 grayscale thumbnail of one frame (autorotated, like any player shows it)."""
    seek = ["-ss", str(at)] if at is not None else []
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", *seek, "-i", str(path), "-frames:v", "1",
                          "-vf", "scale=27:48", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(48, 27).astype(np.float32)


def orientation(frame: np.ndarray, ref: np.ndarray) -> tuple[float, float]:
    """Mean abs difference of z-scored thumbnails, upright and rotated 180 degrees.

    z-scoring makes it immune to video-range vs full-range levels and encoder tone shifts.
    """
    z = lambda x: (x - x.mean()) / (x.std() + 1e-6)   # noqa: E731
    f, r = z(frame), z(ref)
    return float(np.abs(f - r).mean()), float(np.abs(f[::-1, ::-1] - r).mean())


# ---------- take QA ----------

def check_report(ck: Checker, name: str, shot: str, qa: dict) -> bool:
    """The QA report has every field of the spec's schema and a verdict consistent with its checks."""
    missing = [f"{sec + '.' if sec else ''}{k}" for sec, keys in REPORT_KEYS.items()
               for k in keys - set(qa.get(sec, {}) if sec else qa)]
    if not ck(f"{name}: QA report has the spec's fields", not missing, f"missing {missing}" if missing else ""):
        return False
    ck(f"{name}: QA report names its take and shot", (qa["take"], qa["shot"]) == (name, shot),
       f"{qa['take']}/{qa['shot']}")
    levels = [c.get("level") for c in qa["checks"]]
    ck(f"{name}: every check has id, level and an actionable message",
       all(c.get("id") and c.get("message") and c.get("level") in {"ok", "warn", "fail"} for c in qa["checks"]))
    want = "retake" if "fail" in levels else "ok" if "warn" in levels else "great"
    ck(f"{name}: verdict follows the checks (any fail -> retake, any warn -> ok)", qa["verdict"] == want,
       f"verdict {qa['verdict']}, checks say {want}")
    return True


def problems(qa: dict) -> str:
    return "; ".join(f"{c['level']}: {c['message']}" for c in qa["checks"] if c.get("level") != "ok") or "none"


def check_qa(ck: Checker, take: dict, name: str, qa: dict, recorded_s: float) -> None:
    """Technical numbers plus the per-flaw expectations of the fake reads."""
    v, a, s = qa["video"], qa["audio"], qa["script"]
    fake, flaw = take["name"], take["flaw"]
    ck(f"{fake}: QA sees the 1080x1920 camera, full 9:16", (v["width"], v["height"], list(v["effective_9x16"]))
       == (1080, 1920, [1080, 1920]), f"{v['width']}x{v['height']}, eff {v['effective_9x16']}")
    ck(f"{fake}: QA fps ~30", 29.5 <= v["fps"] <= 30.5, v["fps"])
    ck(f"{fake}: take duration matches the recording", abs(v["duration"] - recorded_s) <= 0.6,
       f"{v['duration']:.2f}s vs recorded {recorded_s:.2f}s")
    # QA describes the source as captured (Chrome's fake mic is 44.1 kHz stereo); the normalized
    # take's 48 kHz mono is asserted in check_files.
    ck(f"{fake}: QA reads the captured audio rate", a["sample_rate"] in (44100, 48000), a["sample_rate"])
    # The fake voice peaks at speech_peak_dbfs; browser AGC or processing would move it.
    ck(f"{fake}: capture keeps the voice level (no AGC)",
       abs(a["peak_dbfs"] - take["speech_peak_dbfs"]) <= 1.5,
       f"take peak {a['peak_dbfs']} dBFS vs source {take['speech_peak_dbfs']} dBFS")
    ck(f"{fake}: no clipping", a["clipped_samples"] == 0, a["clipped_samples"])
    ck(f"{fake}: SNR >= 25 dB for a -60 dBFS room", a["snr_db"] >= 25, f"{a['snr_db']} dB", soft=True)
    ck(f"{fake}: exposure in range", 60 <= v["luma_mean"] <= 200, v["luma_mean"], soft=True)
    misread = s["misread"]
    if flaw.startswith("misread"):
        ck(f"{fake}: misread take -> retake", qa["verdict"] == "retake", f"{qa['verdict']}; {problems(qa)}")
        hit = any("hour" in str(m.get("expected", "")).lower() and "day" in str(m.get("heard", "")).lower()
                  for m in misread)
        ck(f"{fake}: misread listed as hours -> days", hit, misread)
        return
    ck(f"{fake}: no misread", not misread, misread)
    ck(f"{fake}: script covered", s["coverage"] >= 0.95, s["coverage"])
    if not flaw:
        ck(f"{fake}: clean take -> great/ok", qa["verdict"] in {"great", "ok"}, f"{qa['verdict']}; {problems(qa)}")
        ck(f"{fake}: clean take -> great", qa["verdict"] == "great", problems(qa), soft=True)
        return
    ck(f"{fake}: usable take ({flaw}) is not a retake", qa["verdict"] != "retake", f"{qa['verdict']}; {problems(qa)}")
    kept = f"kept {s['kept_seconds']}s of {take['speech_s']}s spoken"
    if "restart" in flaw:
        # A restart before the keeper read is trimmed off the front (no cut); its words are junk.
        junk = [re.sub(r"[^a-z']", "", str(w).lower()) for w in s["junk"]]
        ck(f"{fake}: false start reported as junk", "what" in junk and "edit" in junk, s["junk"])
        ck(f"{fake}: filler 'um' reported as junk", "um" in junk, s["junk"], soft=True)   # Whisper may drop it
        ck(f"{fake}: false start trimmed from the kept read", s["kept_seconds"] <= take["speech_s"] - 0.8, kept)
    if "pause" in flaw:
        # QA word times are Whisper's (no VAD snap), which stretch into pauses, so kept_seconds is
        # only approximate here; the reel-level length is checked after the build.
        ck(f"{fake}: the long pause gets cut", s["cuts"] >= 1, f"{s['cuts']} cut(s); {kept}")


def originals(project: Path, name: str) -> list[Path]:
    """The upload as received (raw/orig/<take>.<ext>); sidecars like .capture.json are skipped."""
    return [p for p in sorted((project / "raw" / "orig").glob(f"{name}.*")) if p.suffix in {".mp4", ".webm", ".mov"}]


def check_files(ck: Checker, project: Path, name: str) -> None:
    """Normalized take is CFR H.264 High + mono 48 kHz AAC, faststart, in sync; original and QA kept."""
    mp4 = project / "raw" / f"{name}.mp4"
    if not ck(f"{name}: normalized take raw/{name}.mp4 exists", mp4.exists()):
        return
    d = probe(mp4)
    v, a = d["v"], d["a"]
    ck(f"{name}: H.264 High yuv420p", (v.get("codec_name"), v.get("profile"), v.get("pix_fmt"))
       == ("h264", "High", "yuv420p"), f"{v.get('codec_name')} {v.get('profile')} {v.get('pix_fmt')}")
    ck(f"{name}: constant 30 fps", v.get("r_frame_rate") == "30/1" and abs(ratio(v.get("avg_frame_rate")) - 30) < 0.05,
       f"r {v.get('r_frame_rate')} avg {v.get('avg_frame_rate')}")
    ck(f"{name}: AAC mono 48 kHz", (a.get("codec_name"), a.get("channels"), a.get("sample_rate"))
       == ("aac", 1, "48000"), f"{a.get('codec_name')} {a.get('channels')}ch {a.get('sample_rate')}")
    dv, da = float(v.get("duration", 0)), float(a.get("duration", 0))
    ck(f"{name}: audio and video tracks end together", abs(dv - da) <= 0.1, f"video {dv:.3f}s audio {da:.3f}s")
    ck(f"{name}: faststart", faststart(mp4))
    orig = originals(project, name)
    if ck(f"{name}: original upload kept in raw/orig", len(orig) == 1, [p.name for p in orig]):
        # Browsers often record a mono mic as two identical channels; a summing downmix adds +3 dB.
        up, out = peak_db(orig[0]), peak_db(mp4)
        ck(f"{name}: normalization keeps the voice level (peak within 1 dB of the upload)", abs(out - up) <= 1.0,
           f"upload {up:.1f} dBFS -> take {out:.1f} dBFS", soft=True)
    ck(f"{name}: qa/{name}.json and .words.json written",
       (project / "qa" / f"{name}.json").exists() and (project / "qa" / f"{name}.words.json").exists())


# ---------- capture rules ----------

def _is_none_resize(c) -> bool:
    return c == "none" or (isinstance(c, dict) and "none" in (c.get("exact"), c.get("ideal")))


def check_capture(ck: Checker, fake: str, inst: dict) -> None:
    """getUserMedia + MediaRecorder settings the studio actually used (from the passive page log)."""
    if not ck(f"{fake}: MediaRecorder created", inst.get("recorders")):
        return
    rec = inst["recorders"][-1]
    opts, vs, au = rec["opts"], rec.get("video") or {}, rec.get("audio") or {}
    norm = lambda m: re.sub(r"\s", "", (m or "").lower())   # noqa: E731
    asked = opts.get("mimeType") or rec["mime"]
    ck(f"{fake}: recorder uses the first supported mime of the spec's list",
       norm(asked) == norm(inst.get("first_supported")), f"{asked} (first supported: {inst.get('first_supported')})")
    w, h, fps = vs.get("width", 0), vs.get("height", 0), vs.get("frameRate", 0)
    want = min(max(w * h * fps * 0.30, 8e6), 40e6)
    got = opts.get("videoBitsPerSecond") or 0
    ck(f"{fake}: videoBitsPerSecond = clamp(W*H*fps*0.30, 8e6, 40e6)", abs(got - want) <= 0.03 * want,
       f"{got:.0f} vs {want:.0f}")
    ck(f"{fake}: audioBitsPerSecond 256000", opts.get("audioBitsPerSecond") == 256000, opts.get("audioBitsPerSecond"))
    ck(f"{fake}: camera at native 1080x1920 (no browser rescale)", (w, h) == (1080, 1920), f"{w}x{h}")
    ck(f"{fake}: camera ~30 fps", 29 <= fps <= 31, fps, soft=True)
    flags = {k: au.get(k) for k in ("echoCancellation", "noiseSuppression", "autoGainControl")}
    ck(f"{fake}: mic processing off (EC/NS/AGC)", flags == dict.fromkeys(flags, False), flags)
    vids = [o["constraints"].get("video") for o in inst["opens"] if isinstance(o["constraints"].get("video"), dict)]
    ck(f"{fake}: video requested with resizeMode none", any(_is_none_resize(c.get("resizeMode")) for c in vids),
       [c.get("resizeMode") for c in vids])
    ck(f"{fake}: no uncaught page errors", not inst.get("errors"), inst.get("errors"))


# ---------- master ----------

def check_master(ck: Checker, path: Path, result: dict, expect_s: tuple[float, float],
                 timeline_s: float | None) -> None:
    """The delivered reel: format, duration, loudness and true peak measured independently."""
    if not ck("master renders/reel-master.mp4 exists", path.exists(), path):
        return
    d = probe(path)
    v, a = d["v"], d["a"]
    ck("master is 1080x1920 H.264", (v.get("codec_name"), v.get("width"), v.get("height")) == ("h264", 1080, 1920),
       f"{v.get('codec_name')} {v.get('width')}x{v.get('height')}")
    ck("master is 30 fps", abs(ratio(v.get("avg_frame_rate")) - 30) < 0.1, v.get("avg_frame_rate"))
    ck("master audio is 48 kHz AAC", (a.get("codec_name"), a.get("sample_rate")) == ("aac", "48000"),
       f"{a.get('codec_name')} {a.get('sample_rate')}")
    dur = float(d["format"]["duration"])
    lo, hi = expect_s
    ck("master duration in the expected range", lo <= dur <= hi, f"{dur:.2f}s, expected {lo:.1f}-{hi:.1f}s")
    if timeline_s is not None:
        ck("master duration equals the compiled timeline", abs(dur - timeline_s) <= 0.1,
           f"{dur:.3f}s vs timeline {timeline_s:.3f}s")
    ck("master audio and video end together",
       abs(float(v.get("duration", dur)) - float(a.get("duration", dur))) <= 0.1,
       f"video {v.get('duration')} audio {a.get('duration')}")
    m = loudness(path)
    ck("master loudness -14 +/- 1 LUFS (measured)", abs(m["lufs"] + 14) <= 1.0, f"{m['lufs']} LUFS")
    ck("master true peak <= -0.9 dBTP (measured)", m["true_peak"] <= -0.9, f"{m['true_peak']} dBTP")
    for key in ("lufs", "true_peak"):
        got = result.get(key)
        ck(f"build result {key} agrees with measurement", isinstance(got, (int, float)) and abs(got - m[key]) <= 0.5,
           f"reported {got}, measured {m[key]}")
    ck("build result duration agrees with the file", abs(float(result.get("duration") or 0) - dur) <= 0.1,
       f"reported {result.get('duration')}, file {dur:.3f}")
