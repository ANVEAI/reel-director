"""Subject cut-outs for media B-roll (v4 treatments): the 2.5D parallax subject layer and the "sticker pop".

make(image, out_stem) -> {"cutout": <stem>.cutout.png (the image with the subject as alpha),
                          "sticker": <stem>.sticker.png (the subject with a white outline baked in, cropped to it),
                          "origin": [x %, y %] (subject centroid: the parallax zoom origin),
                          "box": [x0 %, y0 %, x1 %, y1 %] (subject bounds in the image), "subject": share of pixels}
Backend: Apple Vision VNGenerateForegroundInstanceMaskRequest (all instances; macOS 14+) through pyobjc, else
`hyperframes remove-background` (u2net, people-first). Images are decoded and encoded with ffmpeg (no PIL), so
the outputs are deterministic for the same input. Masks are cached next to the outputs (re-run skips them).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

MAX_SIDE = 1600          # px: the decoded image's long side (enough for a 1080x1920 cover at 1.2x)
OUTLINE = 12             # px: the sticker's white stroke at MAX_SIDE
MIN_SUBJECT = 0.02       # a mask under 2 % of the image is no subject (an empty or failed mask)


class CutoutError(RuntimeError):
    pass


def decode(path: Path, max_side: int = MAX_SIDE) -> np.ndarray:
    """(h, w, 4) RGBA uint8, the long side scaled to <= max_side (first frame of a video)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    w, h = int(s["width"]), int(s["height"])
    k = min(1.0, max_side / max(w, h))
    w, h = max(2, round(w * k / 2) * 2), max(2, round(h * k / 2) * 2)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-frames:v", "1", "-vf",
                          f"scale={w}:{h}:flags=lanczos,format=rgba", "-f", "rawvideo", "pipe:1"],
                         capture_output=True, check=True).stdout
    if len(raw) != w * h * 4:
        raise CutoutError(f"could not decode {path.name}")
    return np.frombuffer(raw, np.uint8).reshape(h, w, 4).copy()


def encode_png(rgba: np.ndarray, out: Path) -> Path:
    h, w = rgba.shape[:2]
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
                    "-i", "pipe:0", "-frames:v", "1", "-fflags", "+bitexact", str(out)],
                   input=np.ascontiguousarray(rgba).tobytes(), check=True, capture_output=True)
    return out


def vision_mask(rgba: np.ndarray) -> np.ndarray:
    """0..255 foreground mask (every salient instance) at the image size, Apple Vision."""
    from .face import VisionBackend
    vb = VisionBackend()                       # raises FaceUnavailable off macOS / without pyobjc
    Q, V = vb.Q, vb.V
    if not hasattr(V, "VNGenerateForegroundInstanceMaskRequest"):
        raise CutoutError("Vision foreground masks need macOS 14+")
    rgbx = rgba.copy()
    rgbx[..., 3] = 255
    handler = V.VNImageRequestHandler.alloc().initWithCGImage_options_(vb.cgimage(rgbx), None)
    req = V.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    ok, err = handler.performRequests_error_([req], None)
    if not ok or not req.results():
        raise CutoutError(f"no foreground subject ({err})")
    obs = req.results()[0]
    pb, err = obs.generateScaledMaskForImageForInstances_fromRequestHandler_error_(obs.allInstances(), handler, None)
    if pb is None:
        raise CutoutError(f"Vision mask failed: {err}")
    Q.CVPixelBufferLockBaseAddress(pb, Q.kCVPixelBufferLock_ReadOnly)
    try:
        w, h, bpr = Q.CVPixelBufferGetWidth(pb), Q.CVPixelBufferGetHeight(pb), Q.CVPixelBufferGetBytesPerRow(pb)
        buf = Q.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * h)
        m = np.frombuffer(buf, np.float32).reshape(h, bpr // 4)[:, :w]
        m = np.clip(m * 255.0 + 0.5, 0, 255).astype(np.uint8)
    finally:
        Q.CVPixelBufferUnlockBaseAddress(pb, Q.kCVPixelBufferLock_ReadOnly)
    if m.shape != rgba.shape[:2]:
        raise CutoutError(f"mask {m.shape} does not match the image {rgba.shape[:2]}")
    return m


def hf_mask(path: Path, rgba: np.ndarray) -> np.ndarray:
    """Fallback: `hyperframes remove-background <image> -o <png>` alpha, resized to the decoded image."""
    hf = shutil.which("hyperframes")
    if not hf:
        raise CutoutError("no Vision and no hyperframes CLI for a cutout")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "cut.png"
        subprocess.run([hf, "remove-background", str(path), "-o", str(out)], capture_output=True, check=True, timeout=300)
        h, w = rgba.shape[:2]
        raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(out), "-vf", f"scale={w}:{h},format=rgba",
                              "-f", "rawvideo", "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 4)[..., 3].copy()


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    """Binary-ish dilation by r px (iterated 3x3 max: an octagon), on 0..255."""
    out = m.copy()
    for _ in range(max(0, r)):
        p = np.pad(out, 1)
        out = np.maximum.reduce([p[1:-1, 1:-1], p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:],
                                 p[:-2, :-2], p[:-2, 2:], p[2:, :-2], p[2:, 2:]])
    return out


def sticker(rgba: np.ndarray, m: np.ndarray, outline: int = OUTLINE) -> tuple[np.ndarray, list[int]]:
    """The subject over a white outline (dilated alpha), cropped to the outline's bounds plus a margin."""
    ring = dilate(m, outline)
    ys, xs = np.nonzero(ring > 127)
    pad = outline + 4
    y0, y1 = max(0, ys.min() - pad), min(m.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(m.shape[1], xs.max() + pad + 1)
    a = m[y0:y1, x0:x1].astype(np.float32)[..., None] / 255
    rgb = rgba[y0:y1, x0:x1, :3].astype(np.float32) * a + 255 * (1 - a)       # subject over white
    alpha = ring[y0:y1, x0:x1]
    out = np.dstack([np.clip(rgb + 0.5, 0, 255).astype(np.uint8), alpha])
    return out, [int(x0), int(y0), int(x1), int(y1)]


def make(image: Path, stem: Path, mask_fn=None) -> dict:
    """Cut the subject out of `image`; writes <stem>.cutout.png and <stem>.sticker.png (+ <stem>.cutout.json)."""
    image, stem = Path(image), Path(stem)
    meta_p = stem.with_name(stem.name + ".cutout.json")
    if meta_p.is_file():
        try:
            meta = json.loads(meta_p.read_text())
            if meta.get("src") == str(image) and all(Path(meta[k]).is_file() for k in ("cutout", "sticker")):
                return {k: meta[k] for k in ("cutout", "sticker", "origin", "box", "subject", "aspect")}
        except (OSError, ValueError, KeyError):
            pass
    rgba = decode(image)
    if mask_fn is None:
        try:
            m = vision_mask(rgba)
        except Exception:
            m = hf_mask(image, rgba)
    else:
        m = mask_fn(rgba)
    share = float((m > 127).mean())
    if share < MIN_SUBJECT:
        raise CutoutError(f"no subject found in {image.name} ({share:.1%} of the image)")
    h, w = m.shape
    ys, xs = np.nonzero(m > 127)
    cut = rgba.copy()
    cut[..., 3] = m
    cut_p = encode_png(cut, stem.with_name(stem.name + ".cutout.png"))
    st, box = sticker(rgba, m)
    st_p = encode_png(st, stem.with_name(stem.name + ".sticker.png"))
    info = {"cutout": str(cut_p), "sticker": str(st_p),
            "origin": [round(100 * float(xs.mean()) / w, 2), round(100 * float(ys.mean()) / h, 2)],
            "box": [round(100 * box[0] / w, 2), round(100 * box[1] / h, 2), round(100 * box[2] / w, 2),
                    round(100 * box[3] / h, 2)],
            "subject": round(share, 4), "aspect": round(st.shape[1] / st.shape[0], 4)}
    meta_p.write_text(json.dumps({**info, "src": str(image)}, indent=1))
    return info
