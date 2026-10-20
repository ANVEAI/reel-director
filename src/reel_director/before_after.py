"""Before/after sheet for the editing director (contract v2): the raw take frame next to the edited frame at
the same media moment (6-8 pairs) plus the audio numbers before and after (raw take -> prepped take -> master),
written to renders/before-after.png + .json. Also the imaging primitives QA shares: exact frame grabs by index,
a 5x7 bitmap font (ffmpeg here has no drawtext, and Pillow is not a dependency) and a deterministic PNG writer.

Usage: python -m reel_director.before_after <build_dir> [--out DIR] [--master MP4] [--pairs N]
"""
import argparse
import json
import math
import re
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np

W, H, FPS = 1080, 1920, 30
TILE = (270, 480)                 # sheet tile: a quarter of the reel frame
BG, INK, ACCENT, DIM = (17, 17, 20), (240, 240, 240), (255, 225, 77), (150, 150, 160)

# 5x7 glyphs, one base-32 digit per row (MSB = left pixel). Lower case is drawn as upper case.
_B32 = "0123456789ABCDEFGHIJKLMNOPQRSTUV"
FONT = {
    "0": "EHJLPHE", "1": "4C4444E", "2": "EH1248V", "3": "V2421HE", "4": "26AIV22", "5": "VGU11HE",
    "6": "68GUHHE", "7": "V124888", "8": "EHHEHHE", "9": "EHHF12C", "A": "EHHVHHH", "B": "UHHUHHU",
    "C": "EHGGGHE", "D": "SIHHHIS", "E": "VGGUGGV", "F": "VGGUGGG", "G": "EHGNHHF", "H": "HHHVHHH",
    "I": "E44444E", "J": "72222IC", "K": "HIKOKIH", "L": "GGGGGGV", "M": "HRLLHHH", "N": "HHPLJHH",
    "O": "EHHHHHE", "P": "UHHUGGG", "Q": "EHHHLID", "R": "UHHUKIH", "S": "FGGE11U", "T": "V444444",
    "U": "HHHHHHE", "V": "HHHHHA4", "W": "HHHLLLA", "X": "HHA4AHH", "Y": "HHHA444", "Z": "V1248GV",
    " ": "0000000", ".": "00000CC", ",": "0000C48", ":": "0CC0CC0", "-": "000V000", "+": "044V440",
    "/": "01248G0", "%": "OP248J3", "(": "2488842", ")": "8422248", "=": "00V0V00", "<": "248G842",
    ">": "8421248", "?": "EH12404", "!": "4444404", '"': "AA00000", "'": "4400000", "_": "000000V",
    "#": "AAVAVAA", "|": "4444444", "[": "E88888E", "]": "E22222E", "*": "04LEL40", "&": "CIK8LID",
}
_GLYPH = {c: np.array([[(_B32.index(r) >> (4 - i)) & 1 for i in range(5)] for r in rows], bool)
          for c, rows in FONT.items()}


def frame_index(t: float, fps: float = FPS) -> int:
    """Council 10: frame = floor(t * fps + 0.5)."""
    return int(math.floor(t * fps + 0.5))


def probe_fps(src: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True, check=True).stdout.strip()
    a, _, b = out.partition("/")
    return float(a) / float(b or 1)


def grab(src: Path, times: list[float], size: tuple[int, int] = (540, 960), fps: float | None = None) -> np.ndarray:
    """RGB frames (len(times), h, w, 3) at the exact frame indices of `times` (one decode pass, select filter)."""
    from .media import media_duration
    fps = fps or probe_fps(src)
    last = max(int(round(media_duration(Path(src)) * fps)) - 1, 0)
    idx = [min(max(frame_index(t, fps), 0), last) for t in times]
    uniq = sorted(set(idx))
    if not uniq:
        return np.zeros((0, size[1], size[0], 3), np.uint8)
    sel = "+".join(f"eq(n\\,{i})" for i in uniq)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"select='{sel}',scale={size[0]}:{size[1]}:flags=area",
                        "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, check=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, size[1], size[0], 3)
    if len(fr) < len(uniq):        # an index past the end: repeat the last decoded frame
        fr = np.concatenate([fr, np.repeat(fr[-1:], len(uniq) - len(fr), 0)]) if len(fr) else \
            np.zeros((len(uniq), size[1], size[0], 3), np.uint8)
    pos = {i: k for k, i in enumerate(uniq)}
    return np.stack([fr[pos[i]] for i in idx])


def write_png(path: Path, img: np.ndarray, level: int = 6) -> Path:
    """Deterministic RGB PNG (zlib, filter 0) without Pillow."""
    img = np.ascontiguousarray(img, np.uint8)
    h, w, _ = img.shape
    raw = np.concatenate([np.zeros((h, 1), np.uint8), img.reshape(h, w * 3)], axis=1).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, level)) + chunk(b"IEND", b""))
    return path


def text_width(s: str, scale: int = 3) -> int:
    return len(s) * 6 * scale - scale


def text(img: np.ndarray, x: int, y: int, s: str, scale: int = 3, color=INK, bg=None) -> int:
    """Draw `s` with the bitmap font at (x, y) (top-left); returns the x after the text. Clipped to the image."""
    s = s.upper()
    if bg is not None:
        rect(img, (x - scale * 2, y - scale * 2, text_width(s, scale) + scale * 4, 7 * scale + scale * 4), bg, fill=True)
    for ch in s:
        g = _GLYPH.get(ch, _GLYPH["?"])
        m = np.kron(g, np.ones((scale, scale), bool))
        y0, x0 = max(y, 0), max(x, 0)
        y1, x1 = min(y + m.shape[0], img.shape[0]), min(x + m.shape[1], img.shape[1])
        if y1 > y0 and x1 > x0:
            img[y0:y1, x0:x1][m[y0 - y:y1 - y, x0 - x:x1 - x]] = color
        x += 6 * scale
    return x


def rect(img: np.ndarray, box, color, t: int = 3, fill: bool = False) -> None:
    """Outline (or fill) box = [x, y, w, h] in image pixels, clipped."""
    x, y, w, h = (int(round(v)) for v in box)
    hh, ww = img.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, ww), min(y + h, hh)
    if x1 <= x0 or y1 <= y0:
        return
    if fill:
        img[y0:y1, x0:x1] = color
        return
    for a, b, c, d in ((y0, min(y0 + t, y1), x0, x1), (max(y1 - t, y0), y1, x0, x1),
                       (y0, y1, x0, min(x0 + t, x1)), (y0, y1, max(x1 - t, x0), x1)):
        img[a:b, c:d] = color


# ------------------------------------------------------------------------------------------------ build files
def reel_videos(index_html: str) -> list[dict]:
    """The take clips of a compiled reel: [{"id", "src", "start", "duration", "media_start"}] from reel/index.html."""
    out = []
    for m in re.finditer(r"<video ([^>]*class=\"clip take\"[^>]*)>", index_html):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        out.append({"id": a.get("id", ""), "src": a.get("src", ""), "start": float(a.get("data-start", 0)),
                    "duration": float(a.get("data-duration", 0)), "media_start": float(a.get("data-media-start", 0))})
    return out


def take_sources(build: Path, tl: dict) -> dict[str, Path]:
    """shot id -> the raw (normalized) take the shot was cut from: build-takes.json, else the reel's own asset."""
    bt = {}
    if (build / "build-takes.json").exists():
        bt = json.loads((build / "build-takes.json").read_text())
    vids = reel_videos((build / "reel" / "index.html").read_text()) if (build / "reel" / "index.html").exists() else []
    out = {}
    for sh in tl.get("shots", []):
        cands = bt.get(sh["id"]) or []
        k = sh.get("take", 0) or 0
        if k < len(cands) and (build / cands[k]["src"]).exists():
            out[sh["id"]] = build / cands[k]["src"]
            continue
        v = next((v for v in vids if v["id"].startswith(f"take-{sh['id']}-")), None)
        if v:
            out[sh["id"]] = build / "reel" / v["src"]
    return out


def asset_sources(build: Path) -> dict[str, Path]:
    """shot id -> the prepped asset the reel plays (cleaned audio, same picture and timing as the raw take)."""
    vids = reel_videos((build / "reel" / "index.html").read_text())
    return {v["id"][5:].rsplit("-", 1)[0]: build / "reel" / v["src"] for v in vids}


def _clips(tl: dict) -> list[tuple]:
    return [(sh["id"], c["start"], c["start"] + c["media_out"] - c["media_in"], c["media_in"])
            for sh in tl.get("shots", []) for c in sh.get("clips", [])]


def media_at(tl: dict, t: float, fps: float = FPS) -> tuple[str, float, float]:
    """(shot id, reel t clamped into its clip, media t) for reel time t: the clip under t, else the nearest one."""
    clips = _clips(tl)
    best = min(clips, key=lambda c: 0.0 if c[1] <= t < c[2] else min(abs(t - c[1]), abs(t - c[2] + 1 / fps)))
    t = min(max(t, best[1]), best[2] - 1 / fps)
    return best[0], round(t, 4), round(best[3] + t - best[1], 4)


def moments(tl: dict, n: int = 6, fps: float = FPS) -> list[dict]:
    """n frame-exact moments spread over the reel, each mapped to its shot's media time."""
    D = float(tl.get("duration") or max((c[2] for c in _clips(tl)), default=0.0))
    out = []
    for k in range(n):
        sh, t, mt = media_at(tl, frame_index((k + 0.5) * D / n, fps) / fps, fps)
        out.append({"t": t, "shot": sh, "media_t": mt})
    return out


def overlay_sheet(frames: np.ndarray, annos: list[list[tuple]], heads: list[str], title: str,
                  safe=(120, 288, 888, 1248), gap: int = 16) -> np.ndarray:
    """QA contact sheet: output frames (any size, 9:16) with reel-space boxes drawn on them.
    annos[k] = [(box [x, y, w, h] in 1080x1920 pixels, colour), ...]; the safe rect is drawn grey."""
    (tw, th), n = TILE, len(frames)
    img = np.empty((96 + th + 2 * gap, n * tw + (n + 1) * gap, 3), np.uint8)
    img[:] = BG
    text(img, gap, 16, title, 3, ACCENT)
    k_ = tw / W
    for k in range(n):
        x = gap + k * (tw + gap)
        fr = frames[k]
        ys = np.linspace(0, fr.shape[0] - 1, th).astype(int)
        xs = np.linspace(0, fr.shape[1] - 1, tw).astype(int)
        tile = fr[ys][:, xs].copy()
        rect(tile, (safe[0] * k_, safe[1] * k_, (safe[2] - safe[0]) * k_, (safe[3] - safe[1]) * k_), DIM, 1)
        for box, col in annos[k]:
            rect(tile, [v * k_ for v in box], col, 2)
        img[96:96 + th, x:x + tw] = tile
        text(img, x, 70, heads[k], 2, INK)
    return img


# v1 geometry (reel.css): captions centred at (520, 1110) in a 696 px band, 76 px heavy caps with a 12 px stroke;
# title 100 px, box from y 300 in a 768 px column. Letter advance 0.72 em, word margins 0.16 em, space 0.28 em:
# measured on the real-1 master (MOST CREATORS wraps at 696, WAS FINISHED is 617 px of ink on one line).
ADV, MARGIN, SPACE = 0.72, 0.16, 0.28


def _line_w(words: list[str], px: float) -> float:
    """Words marked with a leading '*' are emphasis markers (0.14 em padding each side)."""
    n = sum(len(w.lstrip("*")) for w in words)
    return (n * ADV + len(words) * MARGIN + max(len(words) - 1, 0) * SPACE
            + 0.28 * sum(w.startswith("*") for w in words)) * px


def wrap(words: list[str], px: float, max_w: float) -> list[list[str]]:
    lines: list[list[str]] = [[]]
    for w in words:
        if lines[-1] and _line_w(lines[-1] + [w], px) > max_w:
            lines.append([])
        lines[-1].append(w)
    return lines


def _spans(html: str, el_id: str, cls: str) -> list[str]:
    m = re.search(rf'<div id="{re.escape(el_id)}-in"[^>]*>(.*?)</div></div>', html, re.S)
    found = re.findall(rf'<span [^>]*class="{cls}([^"]*)"[^>]*>([^<]*)</span>', m.group(1)) if m else []
    return [("*" if "emph" in c else "") + w for c, w in found]


def legacy_layout(plan: dict, html: str) -> dict:
    """A contract-format layout for a v1 build (no reel/layout.json): text boxes estimated from the v1 CSS."""
    m = re.search(r'<body class="cap-([\w-]+)"', html)
    fam = m.group(1) if m else "bold"
    stroke = 12 if fam in ("bold", "pop", "karaoke") else 0
    padx, pady = {"pill": (48, 26), "boxed": (24, 24)}.get(fam, (0, 0))
    caps = []
    for c in plan.get("caps", []):
        words = [w.upper() if fam in ("bold", "pop", "boxed") else w for w in _spans(html, c["id"], "word")]
        lines = wrap(words, 76, 696)
        w = max(_line_w(l, 76) for l in lines) + stroke + padx
        h = (len(lines) - 1) * 1.08 * 76 + 0.72 * 76 + stroke + pady
        caps.append({"chunk_id": c["id"], "t0": c["s"], "t1": c["e"], "zone": "lower-band",
                     "text": " ".join(w.lstrip("*") for w in words),
                     "box": [round(520 - w / 2, 1), round(1110 - h / 2, 1), round(w, 1), round(h, 1)]})
    title, cards = None, []
    for it in plan.get("items", []):
        if it["kind"] == "title":
            words = _spans(html, it["id"], "tw")
            lines = wrap(words, 100, 704)
            w = max(_line_w(l, 100) for l in lines) + 64
            title = {"id": it["id"], "t0": it["s"], "t1": it["e"], "text": " ".join(words),
                     "box": [round(504 - w / 2, 1), 300.0, round(w, 1), round(len(lines) * 102 + 40.0, 1)]}
        elif it["kind"] in ("broll", "cutaway", "card"):
            full = it.get("layout", "full") == "full"
            cards.append({"id": it["id"], "t0": it["s"], "t1": it["e"], "layout": it.get("layout", "full"),
                          "box": [0, 0, W, H] if full else [80, 380, 850, 720]})
    return {"version": 1, "source": "legacy-v1-estimate", "caption_family": fam, "captions": caps, "title": title,
            "cards": cards, "reframe": [], "face_reel": []}


# ------------------------------------------------------------------------------------------------ audio
def audio_numbers(build: Path, tl: dict, master: Path) -> dict:
    """Before -> after: each raw take's LUFS / true peak / SNR, the prepped (cleaned) take, then the master."""
    from .audio import decode, loudness, snr_db, streams
    from .levels import block_loudness
    raw, prepped = take_sources(build, tl), asset_sources(build)
    takes = []
    for sh in tl.get("shots", []):
        r, p = raw.get(sh["id"]), prepped.get(sh["id"])
        if not r:
            continue
        a, b = loudness(r), (loudness(p) if p else None)
        takes.append({"shot": sh["id"], "raw": r.name, "raw_lufs": round(a["I"], 1), "raw_tp": round(a["tp"], 1),
                      "raw_snr_db": snr_db(r), "prepped_lufs": round(b["I"], 1) if b else None,
                      "prepped_tp": round(b["tp"], 1) if b else None, "prepped_snr_db": snr_db(p) if p else None})
    m = loudness(master)
    st = float(block_loudness(decode(master), win=3.0, hop=0.1).max())
    s = streams(master)
    a, v = s.get("audio", {}), s.get("video", {})
    return {"takes": takes,
            "master": {"lufs": round(m["I"], 1), "true_peak": round(m["tp"], 1), "short_term_max": round(st, 1),
                       "av_offset_ms": round(1000 * (a.get("start", 0.0) - v.get("start", 0.0)), 1),
                       "av_duration_diff_ms": round(1000 * (a.get("duration", 0.0) - v.get("duration", 0.0)), 1)},
            "targets": {"lufs": -14.0, "lufs_tol": 0.5, "true_peak_max": -1.5, "short_term_max": -9.0}}


def audio_lines(au: dict) -> list[str]:
    out = []
    for t in au["takes"]:
        out.append(f"{t['shot']} ({t['raw']}): RAW {t['raw_lufs']} LUFS TP {t['raw_tp']} SNR {t['raw_snr_db']} DB"
                   + (f"  -> CLEANED {t['prepped_lufs']} LUFS TP {t['prepped_tp']} SNR {t['prepped_snr_db']} DB"
                      if t["prepped_lufs"] is not None else ""))
    m = au["master"]
    out.append(f"MASTER: {m['lufs']} LUFS (TARGET -14 +-0.5)  TP {m['true_peak']} DBTP (<= -1.5)  "
               f"ST MAX {m['short_term_max']} LUFS (<= -9)  A/V {m['av_offset_ms']} MS")
    return out


# ------------------------------------------------------------------------------------------------ sheet
def sheet(raw: np.ndarray, edit: np.ndarray, heads: list[str], raw_labels: list[str], edit_labels: list[str],
          title: str, lines: list[str], gap: int = 16) -> np.ndarray:
    """Two rows (RAW over EDIT) of TILE-sized frames, column heads, and a text panel underneath."""
    n, (tw, th) = len(heads), TILE
    width = max(n * tw + (n + 1) * gap, 2 * gap + max((text_width(s, 2) for s in lines), default=0))
    top, ph = 96, 28 + 26 * len(lines)
    img = np.empty((top + 2 * th + 3 * gap + ph + 24, width, 3), np.uint8)
    img[:] = BG
    text(img, gap, 16, title, 4, ACCENT)
    for k in range(n):
        x = gap + k * (tw + gap)
        text(img, x, top - 26, heads[k], 2, DIM)
        for row, (fr, lab) in enumerate(((raw, raw_labels), (edit, edit_labels))):
            y = top + row * (th + gap)
            tile = fr[k]
            if tile.shape[:2] != (th, tw):
                ys = np.linspace(0, tile.shape[0] - 1, th).astype(int)
                xs = np.linspace(0, tile.shape[1] - 1, tw).astype(int)
                tile = tile[ys][:, xs]
            img[y:y + th, x:x + tw] = tile
            text(img, x + 8, y + 8, lab[k], 2, ACCENT if row else INK, bg=(0, 0, 0))
    y = top + 2 * th + 3 * gap
    for s in lines:
        text(img, gap, y, s, 2, INK)
        y += 26
    return img


def before_after(build: Path, out: Path, master: Path | None = None, n: int = 6) -> dict:
    """Write out/renders/before-after.png + .json for the build at `build` (read-only)."""
    build, out = Path(build), Path(out)
    master = Path(master) if master else build / "renders" / "reel-master.mp4"
    tl = json.loads((build / "reel" / "timeline.json").read_text())
    ms = moments(tl, max(1, min(8, n)))
    raw_src = take_sources(build, tl)
    edit = grab(master, [m["t"] for m in ms], TILE)
    raw = np.zeros_like(edit)
    by_src: dict[Path, list[int]] = {}
    for k, m in enumerate(ms):
        if m["shot"] in raw_src:
            by_src.setdefault(raw_src[m["shot"]], []).append(k)
    for src, ks in by_src.items():
        fr = grab(src, [ms[k]["media_t"] for k in ks], TILE)
        for j, k in enumerate(ks):
            raw[k] = fr[j]
            ms[k]["raw_src"] = str(src.relative_to(build)) if src.is_relative_to(build) else str(src)
    au = audio_numbers(build, tl, master)
    heads = [f"{m['shot']} T {m['t']:.2f}S" for m in ms]
    img = sheet(raw, edit, heads, [f"RAW {m['media_t']:.2f}S" for m in ms], [f"EDIT {m['t']:.2f}S" for m in ms],
                "BEFORE / AFTER: RAW TAKE VS EDITED REEL, SAME MEDIA MOMENT", ["AUDIO BEFORE -> AFTER"] + audio_lines(au))
    png = write_png(out / "renders" / "before-after.png", img)
    res = {"version": 1, "build": str(build), "master": str(master), "png": "renders/before-after.png",
           "pairs": ms, "audio": au}
    (out / "renders" / "before-after.json").write_text(json.dumps(res, indent=1))
    return {**res, "png_path": str(png)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reel_director.before_after", description=__doc__.splitlines()[0])
    ap.add_argument("build")
    ap.add_argument("--out", help="output project dir (default: the build dir)")
    ap.add_argument("--master")
    ap.add_argument("--pairs", type=int, default=6)
    a = ap.parse_args(argv)
    r = before_after(Path(a.build), Path(a.out or a.build), a.master, a.pairs)
    print(json.dumps({"png": r["png_path"], "pairs": len(r["pairs"]), "audio": r["audio"]["master"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
