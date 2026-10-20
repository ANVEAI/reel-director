"""Learn (creator): a creator profile and coaching tips from a project's takes.

  python -m reel_director.learn creator <project> [--out <project>/qa/creator.json]
  python -m reel_director.learn reference <video> [<video> ...] --out style-ref.json [--no-asr]   (styleref.py)

Framing (eye line, face size, centring) comes from qa/<take>.face.json when VISION wrote one, else a quick Apple
Vision pass on a few frames; then light level, balance and colour temperature; voice LUFS/SNR (the take QA's
numbers, or measured the same way); speech rate. creator.json lands in qa/ so the Studio's existing /media route
serves it (/media/qa/creator.json) to the framing coach. Never imports torch.
"""
import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np


# Framing targets (v2 contract): fractions of the take/reel height (y) or width (x).
EYE_TARGET, EYE_TOL = 0.40, 0.03        # auto-reframe places the eye line here
REFRAME_MAX = 1.10                       # resolution cap on 1080-wide footage (council 3)
HEADROOM = 0.04
FACE_PAD = 0.06                          # padded face box: 6 % of face height
HEAD_ABOVE_BOX = 0.40                    # hair top: ~0.4 face-box heights above Vision's box (founder takes)
CENTRE_TOL = 0.05
REEL_H = 1920
CAPTION_BOTTOM = 1248                    # council 6: caption bottom limit (reel px)
LINE_PX, BOX_PX = 88, 24                 # one 76 px caption line (x1.15) and the box's padding
CHIN_CLEAR = 0.35                        # captions start this x pupil distance under the jaw line (beard):
                                         # face.CHIN_CLEAR, measured by VISION on the founder's takes
IPD_PER_E2C = 0.567                      # pupil distance / eye-to-chin on the founder's takes
IPD_CM = 6.3                             # adult mean interpupillary distance: turns a px move into cm
# Light, voice, speech (the take QA's thresholds where they exist).
FACE_DARK, FACE_BRIGHT = 90, 205         # cheek luma, 0-255
BACKLIT = 1.55                           # bg/face luma: past what a white wall under even light explains
SIDE_LIGHT = 1.35                        # one cheek this much brighter than the other
CCT_WARM, CCT_COOL = 4800, 7500          # neutral surfaces rendered warmer/cooler than this read as a cast
BUSY_EDGES = 0.04                        # share of strong-edge pixels in the title band = busy background
SNR_FAIL, SNR_DENOISE, LUFS_QUIET = 25.0, 35.0, -30.0
WPM_BAND = (140, 185)


def _r(x, n=3):
    return None if x is None else round(float(x), n)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return float(statistics.median(xs)) if xs else None


# --- frames ---------------------------------------------------------------------------------------------------
def frames(path: Path, w: int, h: int, fps: float | None = None, gray: bool = False, limit: int | None = None):
    """Decoded frames as uint8 (N,h,w) gray or (N,h,w,3) RGB; fps=None keeps every frame."""
    vf = (f"fps={fps}," if fps else "") + f"scale={w}:{h}:flags=area,format={'gray' if gray else 'rgb24'}"
    args = ["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf] + (["-frames:v", str(limit)] if limit else [])
    raw = subprocess.run(args + ["-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    c = 1 if gray else 3
    n = len(raw) // (w * h * c)
    return np.frombuffer(raw[: n * w * h * c], np.uint8).reshape((n, h, w) if gray else (n, h, w, 3))


def luma(rgb) -> np.ndarray:
    return np.asarray(rgb, np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32)


# --- faces ----------------------------------------------------------------------------------------------------
class AppleVision:
    """Face landmarks with VNDetectFaceLandmarksRequest (pyobjc). Returns the biggest face, normalised
    top-left: {box:[x,y,w,h], eyes:[[x,y] image-left, image-right], mouth:[x,y], chin_y, conf} or None."""

    def __init__(self):
        import Quartz
        import Vision
        from Foundation import NSData
        self.Q, self.V, self.NSData = Quartz, Vision, NSData

    def __call__(self, rgb: np.ndarray) -> dict | None:
        Q, h, w = self.Q, rgb.shape[0], rgb.shape[1]
        buf = np.ascontiguousarray(rgb, np.uint8).tobytes()
        prov = Q.CGDataProviderCreateWithCFData(self.NSData.dataWithBytes_length_(buf, len(buf)))
        img = Q.CGImageCreate(w, h, 8, 24, w * 3, Q.CGColorSpaceCreateDeviceRGB(), Q.kCGImageAlphaNone, prov, None,
                              False, Q.kCGRenderingIntentDefault)
        req = self.V.VNDetectFaceLandmarksRequest.alloc().init()
        ok, _ = self.V.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None).performRequests_error_(
            [req], None)
        obs = [o for o in (req.results() or []) if o.landmarks() is not None] if ok else []
        if not obs:
            return None
        o = max(obs, key=lambda o: o.boundingBox().size.width)
        bb, lm, size = o.boundingBox(), o.landmarks(), Q.CGSizeMake(w, h)

        def pts(region):
            if region is None or not region.pointCount():
                return None
            p = region.pointsInImageOfSize_(size)
            return np.array([[p[i].x / w, 1 - p[i].y / h] for i in range(region.pointCount())])
        eyes = [pts(lm.leftPupil()), pts(lm.rightPupil())]
        if any(e is None for e in eyes):
            eyes = [pts(lm.leftEye()), pts(lm.rightEye())]
        eyes = [e.mean(0) for e in eyes if e is not None]
        lips, contour = pts(lm.outerLips()), pts(lm.faceContour())
        if len(eyes) != 2 or lips is None:
            return None
        eyes.sort(key=lambda e: e[0])
        box = [bb.origin.x, 1 - bb.origin.y - bb.size.height, bb.size.width, bb.size.height]
        return {"box": [float(v) for v in box], "eyes": [[float(e[0]), float(e[1])] for e in eyes],
                "mouth": [float(v) for v in lips.mean(0)],
                "chin_y": float(contour[:, 1].max()) if contour is not None else float(box[1] + box[3]),
                "conf": float(o.confidence())}


def face_backend():
    """Apple Vision on macOS; None where it can't load (Linux/SaaS: a mediapipe backend plugs in here later)."""
    try:
        return AppleVision()
    except Exception:   # noqa: BLE001 - optional dependency: any import/runtime failure means "no backend"
        return None


def read_face_json(path: Path) -> list[dict | None]:
    """VISION's per-take track (pixel coords of the normalized take) -> normalised samples with t."""
    d = json.loads(path.read_text())
    W, H = float(d["w"]), float(d["h"])
    out = []
    for f in d.get("frames", []):
        if not f:
            out.append(None)
            continue
        x, y, w, h = f["box"]
        eyes = sorted(([ex / W, ey / H] for ex, ey in f["eyes"]), key=lambda e: e[0])
        chin = f.get("chin_y")
        out.append({"t": f.get("t"), "box": [x / W, y / H, w / W, h / H], "eyes": eyes,
                    "mouth": [f["mouth"][0] / W, f["mouth"][1] / H], "conf": f.get("conf", 1.0),
                    "chin_y": chin / H if chin is not None else (y + h) / H})
    return out


def eye_y(f):
    return (f["eyes"][0][1] + f["eyes"][1][1]) / 2


def reframe_reach(eye: float, head_top: float, cap: float = REFRAME_MAX) -> dict:
    """Closest the auto-reframe (scale <= cap, translate, frame always filled, headroom kept) gets the eye line to
    EYE_TARGET. A frame scaled by s may move up by at most s-1 (never shows an edge) and never pulls the head top
    above HEADROOM; it can never move down (that would show the top edge)."""
    best = None
    for s in np.round(np.linspace(1.0, cap, 11), 3):
        lo = s * eye + max(-(s - 1), min(0.0, HEADROOM - s * head_top))
        out = min(max(EYE_TARGET, lo), s * eye)
        if best is None or abs(out - EYE_TARGET) < abs(best[1] - EYE_TARGET) - 1e-9:
            best = (float(s), out)
    return {"scale": _r(best[0]), "eye_y_after": _r(best[1]), "fixable": bool(abs(best[1] - EYE_TARGET) <= EYE_TOL)}


def caption_lines_below_chin(eye_to_chin: float, ipd: float, eye: float = EYE_TARGET) -> int:
    """Caption lines that fit between the chin clearance and the caption bottom limit, eyes at `eye`
    (eye_to_chin and ipd as fractions of H)."""
    top_px = (eye + eye_to_chin + CHIN_CLEAR * ipd) * REEL_H
    room = CAPTION_BOTTOM - top_px - BOX_PX
    return max(0, min(2, int(room // LINE_PX)))


def framing(faces: list[dict | None], w_px: int, h_px: int) -> dict | None:
    ok = [f for f in faces if f]
    if not ok:
        return None
    eyes = [eye_y(f) for f in ok]
    e, face_h = _med(eyes), _med(f["box"][3] for f in ok)
    chin, mouth = _med(f["chin_y"] for f in ok), _med(f["mouth"][1] for f in ok)
    top = _med(f["box"][1] for f in ok) - HEAD_ABOVE_BOX * face_h
    ipd_px = _med(abs(f["eyes"][1][0] - f["eyes"][0][0]) * w_px for f in ok)
    cx = _med((f["eyes"][0][0] + f["eyes"][1][0]) / 2 for f in ok)
    e2c = chin - e
    return {"eye_y": _r(e), "eye_y_p10_p90": [_r(np.percentile(eyes, 10)), _r(np.percentile(eyes, 90))],
            "face_h": _r(face_h), "chin_y": _r(chin), "mouth_y": _r(mouth), "eye_to_chin": _r(e2c),
            "chin_k": _r(e2c / max(mouth - e, 1e-3), 2), "head_top_y": _r(top), "center_x": _r(cx),
            "ipd_px": _r(ipd_px, 1), "present": _r(len(ok) / len(faces)), "samples": len(faces),
            "reframe": reframe_reach(e, top), "caption_lines_below_chin": caption_lines_below_chin(e2c, ipd_px / h_px),
            "px_per_cm": _r(ipd_px / IPD_CM, 2), "frame_px": [w_px, h_px]}


# --- light ----------------------------------------------------------------------------------------------------
_M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])


def _lin(rgb):
    c = np.asarray(rgb, float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def cct_k(rgb_mean) -> float | None:
    """Correlated colour temperature (McCamy) of a mean sRGB colour: ~6500 K for neutral sRGB white."""
    X, Y, Z = _M @ _lin(rgb_mean)
    if X + Y + Z <= 1e-6:
        return None
    x, y = X / (X + Y + Z), Y / (X + Y + Z)
    n = (x - 0.3320) / (0.1858 - y)
    return float(449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33)


def lab(rgb_mean) -> list[float]:
    xyz = _M @ _lin(rgb_mean) / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return [round(116 * f[1] - 16, 1), round(500 * (f[0] - f[1]), 1), round(200 * (f[1] - f[2]), 1)]


def light_stats(rgb: np.ndarray, f: dict) -> dict | None:
    """One frame: cheek patch (eyes to mouth, between the eyes' outer edges), background around the person,
    the title band's busyness (P5/P6), and the white point of near-neutral background pixels."""
    h, w = rgb.shape[:2]
    (lx, ly), (rx, ry) = f["eyes"]
    ey, my, ipd = (ly + ry) / 2, f["mouth"][1], rx - lx
    x0, x1 = int((lx - 0.15 * ipd) * w), int((rx + 0.15 * ipd) * w)
    y0, y1 = int((ey + 0.15 * (my - ey)) * h), int((my - 0.1 * (my - ey)) * h)
    cheeks = rgb[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 2, x1)]
    if cheeks.size == 0:
        return None
    patch, pl = cheeks.reshape(-1, 3).astype(float), luma(cheeks)
    half = pl.shape[1] // 2
    bx, by, bw, _ = f["box"]
    person = np.zeros((h, w), bool)
    person[int(max(0.0, by - HEAD_ABOVE_BOX * f["box"][3]) * h):, int(max(0.0, bx - 0.6 * bw) * w):
           int(min(1.0, bx + 1.6 * bw) * w)] = True
    Y = luma(rgb)
    bg = ~person
    bg[: int(0.04 * h)] = False
    px = rgb[bg].astype(float)
    mx, mn = px.max(1), px.min(1)
    neutral = px[((mx - mn) / np.maximum(mx, 1) < 0.15) & (mx > 60) & (mx < 245)]
    band = Y[int(0.156 * h):int(0.29 * h), int(0.1 * w):int(0.9 * w)]       # council 6 title band, y 300-560
    edges = np.maximum(np.abs(np.diff(band, axis=1))[:-1], np.abs(np.diff(band, axis=0))[:, :-1])
    return {"face_luma": float(pl.mean()), "face_lr": float(pl[:, :half].mean() / max(pl[:, half:].mean(), 1)),
            "bg_luma": float(Y[bg].mean()) if bg.any() else None, "skin_rgb": patch.mean(0),
            "white_rgb": (neutral if len(neutral) >= 200 else px).mean(0),
            "title_edges": float((edges > 40).mean()), "title_luma_sd": float(band.std())}


def summarize_light(stats: list[dict]) -> dict | None:
    if not stats:
        return None
    skin = np.median([s["skin_rgb"] for s in stats], axis=0)
    white = np.median([s["white_rgb"] for s in stats], axis=0)
    face, bg = _med(s["face_luma"] for s in stats), _med(s["bg_luma"] for s in stats)
    return {"face_luma": _r(face, 1), "bg_luma": _r(bg, 1), "bg_to_face": _r(bg / face if bg and face else None, 2),
            "face_lr": _r(_med(s["face_lr"] for s in stats), 2), "white_point_k": _r(cct_k(white), -1),
            "white_rgb": [round(float(v), 1) for v in white], "skin_rgb": [round(float(v), 1) for v in skin],
            "skin_lab": lab(skin), "title_band_edges": _r(_med(s["title_edges"] for s in stats)),
            "title_band_luma_sd": _r(_med(s["title_luma_sd"] for s in stats), 1),
            "busy_background": bool(_med(s["title_edges"] for s in stats) > BUSY_EDGES), "samples": len(stats)}


# --- voice and speech -----------------------------------------------------------------------------------------
def speech_rate(words: list[dict], pause: float = 0.3) -> dict | None:
    """Words per minute over the spoken span, and with pauses longer than `pause` removed (articulation)."""
    if len(words) < 3:
        return None
    span = words[-1]["e"] - words[0]["s"]
    gaps = [b["s"] - a["e"] for a, b in zip(words, words[1:])]
    talk = span - sum(g for g in gaps if g > pause)
    return {"wpm": _r(len(words) / span * 60, 1) if span > 0 else None,
            "articulation_wpm": _r(len(words) / talk * 60, 1) if talk > 0 else None,
            "pauses": sum(1 for g in gaps if g > pause), "words": len(words)}


def take_voice(media: Path, qa: dict | None, words: list[dict]) -> dict:
    """The take QA's audio numbers when present (same meter), else measured the same way."""
    if qa and qa.get("audio", {}).get("snr_db") is not None:
        a = qa["audio"]
    else:
        from .takecheck import decode_audio, integrated_lufs, noise_stats, peak_stats
        mono = decode_audio(media)
        a = {"lufs": integrated_lufs(media), **noise_stats(mono, words), **peak_stats(mono)}
    return {k: a.get(k) for k in ("lufs", "snr_db", "noise_floor_db", "peak_dbfs")}


# --- creator --------------------------------------------------------------------------------------------------
def project_takes(root: Path) -> list[str]:
    """Live take names: takes.json (studio) when present, else raw/*.mp4."""
    tj = root / "takes.json"
    if tj.exists():
        names = {Path(t["src"]).stem for v in json.loads(tj.read_text()).values()
                 for t in (v if isinstance(v, list) else [v])}
    else:
        names = {p.stem for p in (root / "raw").glob("*.mp4")}
    return sorted(n for n in names if (root / "raw" / f"{n}.mp4").exists())


def _load(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def take_faces(media: Path, face_json: Path, rgb: np.ndarray, times: list[float], backend) -> tuple[list, str]:
    """Faces matching the sampled frames: from VISION's track when present (nearest t), else the backend."""
    if face_json.exists():
        timed = [f for f in read_face_json(face_json) if f and f.get("t") is not None]
        near = [min(timed, key=lambda f: abs(f["t"] - t)) if timed else None for t in times]
        return [f if f and abs(f["t"] - t) <= 0.5 else None for f, t in zip(near, times)], "face.json"
    if backend is None:
        return [None] * len(times), "none"
    return [backend(fr) for fr in rgb], "apple-vision"


def creator_profile(root: Path, backend=None, fps: float = 1.0, per_take: int = 8) -> dict:
    from .capture import probe
    root = Path(root)
    backend = backend if backend is not None else face_backend()
    names = project_takes(root)
    faces, light, voices, rates, sources, size = [], [], [], [], set(), None
    for name in names:
        media = root / "raw" / f"{name}.mp4"
        info = probe(media)
        size = (info.width, info.height)
        sw, sh = 540, int(round(540 * info.height / info.width / 2)) * 2
        rgb = frames(media, sw, sh, fps=fps, limit=per_take)
        times = [k / fps for k in range(len(rgb))]
        fs, src = take_faces(media, root / "qa" / f"{name}.face.json", rgb, times, backend)
        sources.add(src)
        faces += fs
        light += [st for fr, f in zip(rgb, fs) if f and (st := light_stats(fr, f))]
        words = _load(root / "qa" / f"{name}.words.json") or _load(root / "prepped" / f"{name}.words.json") or []
        voices.append(take_voice(media, _load(root / "qa" / f"{name}.json"), words))
        if (r := speech_rate(words)) is not None:
            rates.append(r)
    fr = framing(faces, *size) if size else None
    prof = {"version": 1, "project": root.name, "takes": names, "face_source": sorted(sources),
            "framing": fr, "light": summarize_light(light),
            "voice": {k: _r(_med(v[k] for v in voices), 1) for k in ("lufs", "snr_db", "noise_floor_db", "peak_dbfs")}
            if voices else None,
            "speech": {"wpm": _r(_med(r["wpm"] for r in rates), 1),
                       "articulation_wpm": _r(_med(r["articulation_wpm"] for r in rates), 1),
                       "per_take": [r["wpm"] for r in rates]} if rates else None}
    prof["tips"] = coaching_tips(prof)
    prof["coach"] = {"eye_target": EYE_TARGET, "eye_tol": EYE_TOL, "chin_k": (fr or {}).get("chin_k") or 2.0,
                     "max_eye_to_chin": _r(max_eye_to_chin(1)), "max_eye_to_chin_2_lines": _r(max_eye_to_chin(2)),
                     "centre_tol": CENTRE_TOL,
                     "tip": next((t["text"] for t in prof["tips"] if t["level"] == "fix"), None)}
    return prof


def max_eye_to_chin(lines: int, ipd_per_e2c: float = IPD_PER_E2C) -> float:
    """Longest eye-to-chin distance (fraction of H) that still leaves `lines` caption lines under the chin at the
    target eye line; the chin clearance scales with the face (pupil distance ~0.57 x eye-to-chin)."""
    room = (CAPTION_BOTTOM - BOX_PX - lines * LINE_PX) / REEL_H - EYE_TARGET
    return room / (1 + CHIN_CLEAR * ipd_per_e2c)


def _tip(id_, level, text, **measured):
    return {"id": id_, "level": level, "text": text, "measured": measured}


def _framing_tips(fr: dict) -> list[dict]:
    out, ppcm, h_px = [], fr["px_per_cm"] or 1, fr["frame_px"][1]
    e, rf = fr["eye_y"], fr["reframe"]
    cm = abs(e - EYE_TARGET) * h_px / ppcm
    # Pinhole: moving the camera d cm shifts the face d * px_per_cm px (the opposite way): eyes low -> lower it.
    low = e > EYE_TARGET
    move = "lower it" if low else "raise it"
    tilt = "Tilt the camera down slightly (laptop: tip the screen forward)" if low else "Tilt the camera up slightly"
    if abs(e - EYE_TARGET) <= EYE_TOL:
        out.append(_tip("eye_line", "keep", f"Eye line on target ({e:.0%} of the height): keep this camera height.",
                        eye_y=e))
    elif not rf["fixable"]:
        out.append(_tip("eye_line", "fix", f"Your eyes sit at {e:.0%} of the frame height (target {EYE_TARGET:.0%}); "
                        f"the edit can only bring them to {rf['eye_y_after']:.0%}. {tilt}, or {move} about "
                        f"{cm:.0f} cm, so your eyes land on the yellow line.", eye_y=e, reachable=rf["eye_y_after"]))
    else:
        out.append(_tip("eye_line", "nudge", f"Eyes at {e:.0%} of the height: the edit reframes this (x{rf['scale']}), "
                        f"but {tilt.lower()} (or {move} ~{cm:.0f} cm) keeps every pixel sharp.", eye_y=e))
    n, e2c = fr["caption_lines_below_chin"], fr["eye_to_chin"]
    if n < 2:
        back = e2c / max_eye_to_chin(n + 1) - 1
        fits = "no caption line fits" if n == 0 else "one caption line fits"
        what = "captions" if n == 0 else "two-line captions"
        out.append(_tip("face_size", "nudge" if n else "fix", f"With your eyes on the line, {fits} under your chin. "
                        f"Sit back about {back:.0%} (or zoom out) to make room for {what} below your face instead of "
                        "over it.", eye_to_chin=e2c, lines=n))
    dx = fr["center_x"] - 0.5
    if abs(dx) > CENTRE_TOL:
        side = "left" if dx < 0 else "right"     # recordings are unmirrored: image-left is the creator's right
        out.append(_tip("centre", "nudge", f"You sit {abs(dx):.0%} off centre: move about "
                        f"{abs(dx) * fr['frame_px'][0] / ppcm:.0f} cm to your {side}.", center_x=fr["center_x"]))
    return out


def _light_tips(li: dict) -> list[dict]:
    out = []
    if li["face_luma"] < FACE_DARK:
        out.append(_tip("exposure", "fix", f"Your face is dark ({li['face_luma']:.0f}/255): put a lamp or window in "
                        "front of you, slightly above eye level.", face_luma=li["face_luma"]))
    elif li["face_luma"] > FACE_BRIGHT:
        out.append(_tip("exposure", "nudge", f"Your face is very bright ({li['face_luma']:.0f}/255): dim or diffuse "
                        "the light in front of you.", face_luma=li["face_luma"]))
    if li["bg_to_face"] and li["bg_to_face"] > BACKLIT:
        out.append(_tip("backlight", "nudge", f"The background is {li['bg_to_face'] - 1:.0%} brighter than your face, "
                        "so your face reads dark: put the brightest light in front of you, or dim the one behind.",
                        bg_to_face=li["bg_to_face"]))
    lr = li["face_lr"]
    if lr and max(lr, 1 / lr) > SIDE_LIGHT:
        side = "right" if lr < 1 else "left"     # the darker cheek, in the creator's own left (image-right)
        out.append(_tip("side_light", "nudge", f"One side of your face is {max(lr, 1 / lr) - 1:.0%} darker: add soft "
                        f"light on your {side} or turn a little toward the light.", face_lr=lr))
    k = li["white_point_k"]
    if k and (k < CCT_WARM or k > CCT_COOL):
        cast = "warm (yellow)" if k < CCT_WARM else "cool (blue)"
        out.append(_tip("colour", "nudge", f"The picture has a {cast} cast (white wall reads ~{k:.0f} K): use daylight "
                        "(5000-6500 K) bulbs, or switch off the mixed room light.", white_point_k=k))
    if li["busy_background"]:
        out.append(_tip("background", "nudge", "The wall behind your head is busy (posters, text): it competes with "
                        "your face and the title. A plain wall, or sitting a step forward so it falls out of focus, "
                        "reads cleaner.", title_band_edges=li["title_band_edges"]))
    return out


def coaching_tips(p: dict) -> list[dict]:
    """Concrete, measured tips; 'fix' before the next take, 'nudge' when convenient, 'keep' what works."""
    out = _framing_tips(p["framing"]) if p.get("framing") else [
        _tip("face", "fix", "No face found in the takes: check the camera points at you.")]
    out += _light_tips(p["light"]) if p.get("light") else []
    v = p.get("voice")
    if v and v["snr_db"] is not None:
        if v["lufs"] is not None and v["lufs"] < LUFS_QUIET:
            out.append(_tip("voice_level", "fix", f"Voice is quiet ({v['lufs']:.0f} LUFS): move the mic closer.",
                            lufs=v["lufs"]))
        if v["snr_db"] < SNR_FAIL:
            out.append(_tip("noise", "fix", f"Room noise is high (voice {v['snr_db']:.0f} dB above it): find a quieter "
                            "room or get the mic closer.", snr_db=v["snr_db"]))
        elif v["snr_db"] < SNR_DENOISE:
            out.append(_tip("noise", "nudge", f"Voice is {v['snr_db']:.0f} dB above the room, just under the "
                            f"{SNR_DENOISE:.0f} dB where denoise is skipped: switch off fans/AC or move the mic a "
                            "little closer so the voice stays untouched.", snr_db=v["snr_db"]))
        else:
            out.append(_tip("noise", "keep", f"Clean voice (SNR {v['snr_db']:.0f} dB): keep this room and mic "
                            "distance.", snr_db=v["snr_db"]))
    s = p.get("speech")
    if s and s["wpm"]:
        lo, hi = WPM_BAND
        level, text = ("keep", f"Speech rate {s['wpm']:.0f} wpm sits in the {lo}-{hi} band reels read well at.")
        if s["wpm"] < lo:
            level, text = "nudge", f"You speak at {s['wpm']:.0f} wpm: lift the energy toward {lo}-{hi} wpm."
        elif s["wpm"] > hi:
            level, text = "nudge", f"You speak at {s['wpm']:.0f} wpm: slow down a touch (captions need {lo}-{hi})."
        out.append(_tip("pace", level, text, wpm=s["wpm"]))
    order = {"fix": 0, "nudge": 1, "keep": 2}
    return sorted(out, key=lambda t: order[t["level"]])


# --- CLI ------------------------------------------------------------------------------------------------------
def _write(data: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.part")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=False) + "\n")
    tmp.replace(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reel_director.learn")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("creator", help="creator profile + coaching tips from a project's takes")
    c.add_argument("project")
    c.add_argument("--out", help="default: <project>/qa/creator.json (served to the Studio)")
    r = sub.add_parser("reference", help="style reference from video files you supply (never downloads)")
    r.add_argument("videos", nargs="+")
    r.add_argument("--out", required=True)
    r.add_argument("--no-asr", action="store_true", help="skip transcription (no speech rate / bed level)")
    a = ap.parse_args(argv)
    if a.cmd == "creator":
        prof = creator_profile(Path(a.project))
        out = Path(a.out) if a.out else Path(a.project) / "qa" / "creator.json"
        _write(prof, out)
        for t in prof["tips"]:
            print(f"  [{t['level']:>5}] {t['text']}")
        print(f"wrote {out}")
        return 0
    from .styleref import style_reference
    missing = [v for v in a.videos if not Path(v).is_file()]
    if missing:
        print(f"error: not a local file: {', '.join(missing)}", file=sys.stderr)
        return 2
    asr = None
    if not a.no_asr:
        from .__main__ import transcribe
        asr = transcribe
    ref = style_reference([Path(v) for v in a.videos], asr=asr)
    _write(ref, Path(a.out))
    print(f"  overrides: {json.dumps(ref['preset_overrides'])}")
    for n in ref["notes"]:
        print(f"  note: {n}")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
