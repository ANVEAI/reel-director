"""Fake camera + microphone files for the studio e2e run: one pair per take, made with macOS `say`.

Per take (written to work/e2e/media/ by default):
  <take>.wav    mono 48 kHz 16-bit: PREROLL s of room tone, 1.0 s room tone, the line read by `say`,
                1.5 s room tone, then EXTRA s more room tone. Chrome's fake mic starts playing the file
                when getUserMedia opens the device (page load), not when recording starts, so the
                pre-roll covers page load + the 3-2-1 countdown; run_e2e.py times Space from the mic's
                start so the recorder starts ~1.2 s before the first word. The room tone (pink noise,
                ~-60 dBFS RMS) keeps the take realistic: a noise floor to measure, never digital silence.
  <take>.mjpeg  1080x1920 MJPEG (Chrome plays MJPEG fake cameras at a fixed 30 fps) showing the take id,
                its flaw, the line and a running camera clock, so screenshots show which take is live.
  manifest.json timings measured from the files (speech onset/end via silencedetect), read by run_e2e.py.

Takes and their deliberate flaws: hook-1 misreads "three days", hook-2 clean, turn-1 "um" + restart,
turn-2 clean, cta-1 a 2 s pause after "record,", cta-2 clean.

Run: .venv/bin/python tests/e2e/make_fake_media.py [--out work/e2e/media] [--preroll 8] [--force]
Needs ffmpeg/ffprobe, macOS `say`, numpy, and Playwright driving the installed Google Chrome
(channel="chrome") to typeset the frames (this ffmpeg has no drawtext).
"""
import argparse
import html
import json
import math
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples" / "demo" / "script.json"
OUT = ROOT / "work" / "e2e" / "media"
VERSION = 4            # bump when the media design changes, to invalidate cached files

W, H, FPS = 1080, 1920, 30
PREROLL, LEAD, TAIL, EXTRA = 8.0, 1.0, 1.5, 3.0   # pre-roll covers a cold first page load + countdown
STOP_PAD = 0.5         # recording stops this long after the trailing 1.5 s of room tone
VIDEO_EXTRA = 2.0      # video outlasts the wav a little (Chrome loops it; the clock then restarts)
VOICE, RATE = "Samantha", 170
PEAK_DBFS = -6.0       # speech peak: loud, natural, far from clipping
NOISE_AMP = 0.005      # anoisesrc pink amplitude -> ~-60 dBFS RMS (measured: a=0.01 is -53.9)
JPEG_Q = 5             # mjpeg -q:v (2 best .. 31 worst); 5 keeps text crisp at ~75 KB/frame

CELL_W, CELL_H = 70, 130                 # one clock glyph
CLOCK_CHARS = "0123456789:."
DIGITS = (260, 1326, 8 * CELL_W, CELL_H)  # x, y, w, h of "MM:SS.cc"
BAR = (260, 1474, 8 * CELL_W, 12)          # sweeps once per second
PANEL_BG = (16, 16, 20)
BAR_BG, BAR_FG = (42, 42, 51), (255, 212, 0)
TINTS = {"hook": ("#b3a3e6", "#8a77bf", "#5e4f8f"), "turn": ("#a3d8e3", "#6aa8b6", "#447684"),
         "cta": ("#ebbd99", "#c3916b", "#86603f")}


@dataclass(frozen=True)
class FakeTake:
    name: str            # shot id + take number, in recording order
    shot: str
    text: str | None     # what `say` reads ([[slnc ms]] is a pause); None = the script line, clean
    flaw: str = ""


TAKES = [
    FakeTake("hook-1", "hook", "Most creators waste three days editing one reel.", "misread: 'three days'"),
    FakeTake("hook-2", "hook", None),
    FakeTake("turn-1", "turn",
             "Um, what if the edit was, what if the edit was finished before you even pressed record?",
             "filler 'um' + restart"),
    FakeTake("turn-2", "turn", None),
    FakeTake("cta-1", "cta", "Read the script, hit record, [[slnc 2000]] and the reel builds itself.",
             "2 s pause after 'record,'"),
    FakeTake("cta-2", "cta", None),
]


def run(*cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def ffprobe(path: Path) -> dict:
    return json.loads(run("ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)).stdout)


def silences(path: Path, noise_db: float, min_s: float) -> list[tuple[float, float]]:
    """Silent spans (start, end) per ffmpeg silencedetect."""
    err = run("ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
              f"silencedetect=n={noise_db}dB:d={min_s}", "-f", "null", "-").stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return list(zip(starts, ends + [math.inf] * (len(starts) - len(ends)), strict=True))


def level_db(path: Path, start: float, end: float) -> dict:
    """RMS and peak dBFS of a time range."""
    err = run("ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
              f"atrim={start}:{end},astats=measure_overall=RMS_level+Peak_level:measure_perchannel=none",
              "-f", "null", "-").stderr
    return {"rms": float(re.findall(r"RMS level dB: (-?[\d.inf]+)", err)[-1]),
            "peak": float(re.findall(r"Peak level dB: (-?[\d.inf]+)", err)[-1])}


def script_lines() -> dict[str, str]:
    return {s["id"]: s["line"] for s in json.loads(SCRIPT.read_text())["shots"]}


def spoken(take: FakeTake, lines: dict[str, str]) -> str:
    return take.text or lines[take.shot]


# ---------- audio ----------

def make_wav(take: FakeTake, text: str, dst: Path, preroll: float, seed: int, tmp: Path) -> dict:
    """Room tone + the read placed so speech starts exactly at preroll + LEAD."""
    aiff = tmp / f"{take.name}.aiff"
    voice = ["-v", VOICE] if VOICE in run("say", "-v", "?").stdout else []
    run("say", *voice, "-r", str(RATE), "-o", str(aiff), text)
    sil = silences(aiff, -50, 0.05)
    dur = float(ffprobe(aiff)["format"]["duration"])
    onset = sil[0][1] if sil and sil[0][0] < 0.01 else 0.0
    offset = sil[-1][0] if sil and sil[-1][1] >= dur - 0.01 else dur
    peak = float(re.findall(r"max_volume: (-?[\d.]+)", run(
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(aiff), "-af", "volumedetect", "-f", "null", "-").stderr)[0])
    delay_ms = round((preroll + LEAD - onset) * 1000)
    total = preroll + LEAD + (offset - onset) + TAIL + EXTRA
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-f", "lavfi",
        "-i", f"anoisesrc=r=48000:c=pink:a={NOISE_AMP}:d={total:.3f}:seed={seed}",
        "-filter_complex",
        f"[0]aresample=48000,volume={PEAK_DBFS - peak:.2f}dB,adelay={delay_ms}:all=1[v];"
        f"[v][1]amix=inputs=2:normalize=0:duration=longest,atrim=0:{total:.3f}[a]",
        "-map", "[a]", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(dst))
    # Measure the result instead of trusting the arithmetic: room tone sits ~40 dB under speech.
    gaps = silences(dst, -40, 0.25)
    speech_start = gaps[0][1]
    speech_end = gaps[-1][0] if gaps[-1][1] == math.inf or gaps[-1][1] >= total - 0.05 else total
    return {"wav_duration": round(float(ffprobe(dst)["format"]["duration"]), 3),
            "speech_start": round(speech_start, 3), "speech_end": round(speech_end, 3),
            "speech_s": round(speech_end - speech_start, 3),
            "stop_at": round(speech_end + TAIL + STOP_PAD, 3),
            "noise_rms_dbfs": round(level_db(dst, 0.5, preroll - 0.5)["rms"], 1),
            "speech_peak_dbfs": round(level_db(dst, speech_start, speech_end)["peak"], 1)}


# ---------- video ----------

FONT = "-apple-system, system-ui, 'Helvetica Neue', sans-serif"
MONO = "ui-monospace, Menlo, monospace"


def frame_html(take: FakeTake, text: str) -> str:
    top, mid, bot = TINTS[take.shot]
    x, y, w, h = DIGITS
    bx, by, bw, bh = BAR
    flaw = html.escape(take.flaw or "clean read")
    flaw_color = "#ffb4a8" if take.flaw else "#b8f5c8"
    line = html.escape(re.sub(r"\s*\[\[[^\]]*\]\]\s*", " … ", text))
    rgb = "rgb({},{},{})".format(*PANEL_BG)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden}}
body{{position:relative;color:#fff;font-family:{FONT};
  background:linear-gradient(180deg,{top} 0%,{mid} 55%,{bot} 100%)}}
.grid{{position:absolute;inset:0;background-size:180px 180px;background-image:
  linear-gradient(rgba(255,255,255,.10) 2px,transparent 2px),
  linear-gradient(90deg,rgba(255,255,255,.10) 2px,transparent 2px)}}
.fig{{position:absolute;background:#454c5c}}
.head{{left:340px;top:390px;width:400px;height:500px;border-radius:50%}}
.neck{{left:465px;top:850px;width:150px;height:210px}}
.torso{{left:90px;top:1010px;width:900px;height:1000px;border-radius:450px 450px 0 0}}
.eye{{position:absolute;top:610px;width:64px;height:26px;border-radius:50%;background:#d9dde6}}
.tag{{position:absolute;top:92px;width:100%;text-align:center;font:600 32px/1 {FONT};letter-spacing:10px;
  text-shadow:0 2px 10px rgba(0,0,0,.5)}}
.take{{position:absolute;top:146px;width:100%;text-align:center;font:800 150px/1 {FONT};letter-spacing:-2px;
  text-shadow:0 6px 24px rgba(0,0,0,.35)}}
.flaw{{position:absolute;top:306px;width:100%;text-align:center}}
.flaw span{{display:inline-block;padding:12px 28px;border-radius:999px;background:rgba(0,0,0,.55);
  font:700 40px/1 {FONT};color:{flaw_color}}}
.line{{position:absolute;left:96px;right:96px;top:1030px;padding:24px 34px;border-radius:24px;
  background:rgba(0,0,0,.45);font:500 40px/1.3 {FONT};text-align:center}}
.panel{{position:absolute;left:{x - 60}px;top:{y - 50}px;width:{w + 120}px;height:{h + 110}px;
  border-radius:28px;background:{rgb}}}
.plabel{{position:absolute;left:{x}px;top:{y - 36}px;font:600 24px/1 {FONT};letter-spacing:6px;opacity:.7}}
.foot{{position:absolute;bottom:120px;width:100%;text-align:center;font:600 30px/1 {MONO};opacity:.75}}
</style></head><body><div class="grid"></div>
<div class="fig head"></div><div class="fig neck"></div><div class="fig torso"></div>
<div class="eye" style="left:430px"></div><div class="eye" style="left:586px"></div>
<div class="tag">FAKE CAMERA · E2E</div><div class="take">{take.name}</div><div class="flaw"><span>{flaw}</span></div>
<div class="line">“{line}”</div>
<div class="panel"></div><div class="plabel">CAMERA CLOCK</div>
<div class="foot">{W}×{H} · {FPS} fps · MJPEG</div></body></html>"""


def glyph_html() -> str:
    cells = "".join(f"<div>{c}</div>" for c in CLOCK_CHARS)
    rgb = "rgb({},{},{})".format(*PANEL_BG)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0}} body{{background:{rgb};display:flex}}
div{{width:{CELL_W}px;height:{CELL_H}px;line-height:{CELL_H}px;text-align:center;color:#f5f5f7;
  font:700 112px/{CELL_H}px {MONO}}}</style></head><body>{cells}</body></html>"""


def png_rgb(path: Path, w: int, h: int) -> np.ndarray:
    """Decode a PNG to an HxWx3 uint8 array (ffmpeg, so no imaging library is needed)."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).copy()


def typeset(takes: list[FakeTake], lines: dict[str, str], frames_dir: Path) -> dict[str, np.ndarray]:
    """Render each take's still frame and the clock glyphs with headless Chrome."""
    from playwright.sync_api import sync_playwright
    frames_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for t in takes:
            page.set_content(frame_html(t, spoken(t, lines)))
            png = frames_dir / f"{t.name}.png"
            page.screenshot(path=str(png))
            out[t.name] = png_rgb(png, W, H)
        page.set_content(glyph_html())
        png = frames_dir / "clock-glyphs.png"
        page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": CELL_W * len(CLOCK_CHARS), "height": CELL_H})
        out["_glyphs"] = png_rgb(png, CELL_W * len(CLOCK_CHARS), CELL_H)
        browser.close()
    return out


def clock_text(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def make_mjpeg(base: np.ndarray, glyphs: np.ndarray, seconds: float, dst: Path) -> dict:
    """Pipe frames (still + live clock + per-second sweep bar) into ffmpeg's MJPEG encoder."""
    n = math.ceil(seconds * FPS)
    x, y, w, h = DIGITS
    bx, by, bw, bh = BAR
    cells = {c: glyphs[:, i * CELL_W:(i + 1) * CELL_W] for i, c in enumerate(CLOCK_CHARS)}
    frame = base.copy()
    # Full-range JPEG (yuvj420p) is what MJPEG decoders, including Chrome's, assume.
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-", "-c:v", "mjpeg",
                            "-q:v", str(JPEG_Q), "-pix_fmt", "yuvj420p", "-f", "mjpeg", str(dst)],
                           stdin=subprocess.PIPE)
    for i in range(n):
        t = i / FPS
        for k, c in enumerate(clock_text(t)):
            frame[y:y + h, x + k * CELL_W:x + (k + 1) * CELL_W] = cells[c]
        fill = int(bw * (t % 1.0))
        frame[by:by + bh, bx:bx + bw] = BAR_BG
        frame[by:by + bh, bx:bx + fill] = BAR_FG
        enc.stdin.write(frame.tobytes())
    enc.stdin.close()
    if enc.wait():
        raise RuntimeError(f"ffmpeg mjpeg encode failed for {dst}")
    luma = float((base[..., 0] * 0.2126 + base[..., 1] * 0.7152 + base[..., 2] * 0.0722).mean())
    return {"frames": n, "video_duration": round(n / FPS, 3), "luma_mean": round(luma, 1)}


# ---------- driver ----------

def params(preroll: float) -> dict:
    return {"version": VERSION, "preroll": preroll, "lead": LEAD, "tail": TAIL, "extra": EXTRA,
            "voice": VOICE, "rate": RATE, "takes": [asdict(t) for t in TAKES], "script": script_lines()}


def verify(entry: dict, out: Path, preroll: float) -> list[str]:
    """Problems with one take's generated files (empty list = good)."""
    errs = []
    wav = ffprobe(out / entry["wav"])["streams"][0]
    if (wav["codec_name"], int(wav["sample_rate"]), wav["channels"]) != ("pcm_s16le", 48000, 1):
        errs.append(f"wav format {wav['codec_name']} {wav['sample_rate']} Hz {wav['channels']} ch")
    if abs(entry["speech_start"] - (preroll + LEAD)) > 0.08:
        errs.append(f"speech starts at {entry['speech_start']} s, expected {preroll + LEAD}")
    if not -65 < entry["noise_rms_dbfs"] < -55:
        errs.append(f"room tone {entry['noise_rms_dbfs']} dBFS RMS, expected ~-60")
    if not -7.5 < entry["speech_peak_dbfs"] < -4.5:
        errs.append(f"speech peak {entry['speech_peak_dbfs']} dBFS, expected ~{PEAK_DBFS}")
    vid = json.loads(run("ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                         "stream=codec_name,width,height,nb_read_packets", "-of", "json",
                         str(out / entry["mjpeg"])).stdout)["streams"][0]
    if (vid["codec_name"], vid["width"], vid["height"]) != ("mjpeg", W, H):
        errs.append(f"video {vid['codec_name']} {vid['width']}x{vid['height']}")
    if int(vid["nb_read_packets"]) != entry["frames"]:
        errs.append(f"video has {vid['nb_read_packets']} frames, expected {entry['frames']}")
    if not 70 <= entry["luma_mean"] <= 180:
        errs.append(f"frame mean luma {entry['luma_mean']} outside 70-180 (QA would flag exposure)")
    return errs


def generate(out: Path = OUT, preroll: float = PREROLL, force: bool = False) -> dict:
    """Make (or reuse) every take's wav + mjpeg; returns the manifest."""
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    want = params(preroll)
    if mpath.exists() and not force:
        old = json.loads(mpath.read_text())
        if old.get("params") == want and all((out / e[k]).exists() for e in old["takes"] for k in ("wav", "mjpeg")):
            return old
    lines = script_lines()
    stills = typeset(TAKES, lines, out / "frames")
    entries = []
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        for i, t in enumerate(TAKES, 1):
            e = {**asdict(t), "spoken": spoken(t, lines), "wav": f"{t.name}.wav", "mjpeg": f"{t.name}.mjpeg"}
            e |= make_wav(t, e["spoken"], out / e["wav"], preroll, i, Path(tmp))
            e |= make_mjpeg(stills[t.name], stills["_glyphs"], e["wav_duration"] + VIDEO_EXTRA, out / e["mjpeg"])
            e["mjpeg_mb"] = round((out / e["mjpeg"]).stat().st_size / 1e6, 1)
            entries.append(e)
            print(f"  {t.name:<7} speech {e['speech_start']:5.2f}-{e['speech_end']:5.2f}s  stop@{e['stop_at']:5.2f}s  "
                  f"noise {e['noise_rms_dbfs']} dBFS  luma {e['luma_mean']}  {e['frames']} frames {e['mjpeg_mb']} MB")
    problems = {e["name"]: p for e in entries if (p := verify(e, out, preroll))}
    if problems:
        raise RuntimeError(f"fake media failed verification: {problems}")
    manifest = {"params": want, "dir": str(out), "takes": entries}
    mpath.write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--preroll", type=float, default=PREROLL)
    ap.add_argument("--force", action="store_true", help="regenerate even if the manifest is current")
    args = ap.parse_args(argv)
    m = generate(args.out.resolve(), args.preroll, args.force)
    print(f"fake media ({len(m['takes'])} takes) -> {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
