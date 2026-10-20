"""Subject matte per take: the person cut out of the background, for background treatment.

  treat_background(media, out) -> the take with only its background blurred / darkened, baked in
                                  one ffmpeg pass: a drop-in clip (the recommended path)
  matte(media, out)            -> prepped/<take>.matte.webm: the take's pixels with the person as
                                  alpha (VP9 yuva420p, ALPHA_MODE=1), for layouts that put the
                                  person over designed backgrounds
  matte(media, out, "mask")    -> a grey matte video (white = person), H.264

Measured on the founder's hook-1 (1080x1920, 6.4 s) in a 3 s HyperFrames render: baseline 6.7 s,
baked treat_background 7.5 s, alpha WebM over a CSS blur(10px) copy 8.7 s. The WebM path also
shows cut-out tells the bake avoids (luma of the 1-4 px band outside the silhouette vs the wall:
-50 vs -1): CSS blur smears hair and shirt into the wall and the soft alpha lets the unblurred
wall through. Prep cost: ~13-16 s per take, ~55 ms/frame of it in Vision.

Backend: Apple Vision VNGeneratePersonSegmentationRequest, "accurate" level (1512x2016 mask).
Picked on real frames over "balanced" (soft halo on hair) and VNGenerateForegroundInstanceMask
(keeps the chair as foreground). `hyperframes remove-background` (u2net_human_seg) is the
portable alternative. Masks and outputs are deterministic; nothing here imports torch.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .capture import VIDEO_ARGS
from .face import FaceUnavailable, VisionBackend, frames, probe_video

QUALITY = "accurate"
BLUR = 14.0          # background blur sigma in px (contract: 8-14; founder: the FOCUS poster still read at 10)
DIM = 0.25           # background exposure cut (contract: 15-25%; 20% left the poster legible behind captions)
BLUR_FAR = 34.0      # sigma px at the top of the frame, easing to BLUR by FAR_TO x H: a lens-like focus falloff. Measured
FAR_TO = (0.30, 0.40)  # on real-1: the word-cloud poster (180 px letters) still read as "FOCUS" at 14 px; the contract's 8-14
                     # holds around the subject, the far wall above the head gets the depth blur (founder review)
WEBM_CRF = 30        # VP9: the alpha plane and the subject stay clean at this level on real takes
SHRINK = 2           # px the subject alpha is eroded by before feathering (kills the light rim)
FEATHER = 1.0        # px gaussian on the subject alpha edge
GROW = 3             # half-size px the mask is dilated by before it weights the background blur


class Segmenter(Protocol):
    name: str

    def mask(self, rgbx: np.ndarray) -> np.ndarray:
        """Person mask (any resolution, same aspect as the frame), uint8 0..255."""


class VisionSegmenter:
    name = "vision-person"

    def __init__(self, quality: str = QUALITY) -> None:
        self.vb = VisionBackend()   # raises FaceUnavailable off macOS / without pyobjc
        import Quartz
        import Vision
        self.Q, self.V = Quartz, Vision
        levels = {"fast": Vision.VNGeneratePersonSegmentationRequestQualityLevelFast,
                  "balanced": Vision.VNGeneratePersonSegmentationRequestQualityLevelBalanced,
                  "accurate": Vision.VNGeneratePersonSegmentationRequestQualityLevelAccurate}
        if quality not in levels:
            raise ValueError(f"quality must be one of {', '.join(levels)}")
        self.level = levels[quality]

    def mask(self, rgbx: np.ndarray) -> np.ndarray:
        Q, V = self.Q, self.V
        req = V.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)
        req.setQualityLevel_(self.level)
        req.setOutputPixelFormat_(Q.kCVPixelFormatType_OneComponent8)
        handler = V.VNImageRequestHandler.alloc().initWithCGImage_options_(self.vb.cgimage(rgbx), None)
        ok, err = handler.performRequests_error_([req], None)
        if not ok or not req.results():
            raise RuntimeError(f"Vision person segmentation failed: {err}")
        pb = req.results()[0].pixelBuffer()
        Q.CVPixelBufferLockBaseAddress(pb, Q.kCVPixelBufferLock_ReadOnly)
        try:
            w, h, bpr = Q.CVPixelBufferGetWidth(pb), Q.CVPixelBufferGetHeight(pb), Q.CVPixelBufferGetBytesPerRow(pb)
            buf = Q.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * h)
            return np.frombuffer(buf, np.uint8).reshape(h, bpr)[:, :w].copy()
        finally:
            Q.CVPixelBufferUnlockBaseAddress(pb, Q.kCVPixelBufferLock_ReadOnly)


def get_segmenter(quality: str = QUALITY) -> Segmenter:
    if sys.platform != "darwin":
        raise FaceUnavailable("person segmentation needs macOS Vision (or `hyperframes remove-background`)")
    return VisionSegmenter(quality)


def _gop(fps: float) -> int:
    """Keyframe every 2 s, as capture.normalize does: HyperFrames seeks freeze on sparse keyframes."""
    return max(1, round(2 * fps))


def _encode(media: Path, out: Path, graph: str, codec: list[str], masks: Callable[[], object], mw: int, mh: int,
            fps: float, audio: bool = False) -> None:
    """ffmpeg with the take as input 0 and raw grey masks on stdin as input 1, paired by frame index."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(media), "-f", "rawvideo", "-pix_fmt", "gray",
           "-s", f"{mw}x{mh}", "-framerate", f"{fps:.6f}", "-i", "pipe:0", "-filter_complex", graph, "-map", "[v]",
           *(["-map", "0:a:0?", "-c:a", "copy"] if audio else ["-an"]), *codec, "-fflags", "+bitexact", str(out)]
    with tempfile.TemporaryFile() as err:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err)
        try:
            for m in masks():
                p.stdin.write(np.ascontiguousarray(m).tobytes())
        except BrokenPipeError:
            pass
        finally:
            p.stdin.close()
            p.wait()
        if p.returncode != 0:
            err.seek(0)
            raise RuntimeError("ffmpeg failed: " + err.read().decode(errors="replace").strip()[-400:])


class _Masks:
    """Streams one mask per frame and keeps the numbers for the report."""

    def __init__(self, media: Path, seg: Segmenter, w: int, h: int) -> None:
        self.media, self.seg, self.w, self.h = media, seg, w, h
        self.first = seg.mask(next(frames(media, 1, w, h))[1])
        self.n, self.seconds, self.coverage = 0, 0.0, []

    def __call__(self):
        for _, img in frames(self.media, 1, self.w, self.h):
            t = time.perf_counter()
            m = self.seg.mask(img)
            self.seconds += time.perf_counter() - t
            if m.shape != self.first.shape:
                raise RuntimeError(f"mask size changed mid-take: {m.shape} vs {self.first.shape}")
            self.n += 1
            self.coverage.append(float(np.mean(m >= 128)))
            yield m


def _report(media: Path, out: Path, kind: str, masks: _Masks, seg: Segmenter, t0: float) -> dict:
    total = time.perf_counter() - t0
    return {"take": media.stem, "out": str(out), "kind": kind, "backend": seg.name, "frames": masks.n,
            "mask_size": [int(masks.first.shape[1]), int(masks.first.shape[0])],
            "segment_ms_per_frame": round(1000 * masks.seconds / max(masks.n, 1), 1),
            "seconds": round(total, 2), "bytes": out.stat().st_size,
            "person_share": round(float(np.median(masks.coverage)), 3) if masks.coverage else 0.0}


def matte(media: Path, out: Path, kind: str = "alpha", quality: str = QUALITY, seg: Segmenter | None = None) -> dict:
    """Write the subject matte of a take. kind "alpha": WebM (VP9 yuva420p, the take's own pixels
    with the person as alpha); kind "mask": grey H.264 matte. Returns timings and sizes."""
    media, out = Path(media), Path(out)
    if kind not in ("alpha", "mask"):
        raise ValueError("kind must be 'alpha' or 'mask'")
    t0 = time.perf_counter()
    seg = seg or get_segmenter(quality)
    w, h, fps = probe_video(media)
    masks = _Masks(media, seg, w, h)
    mh, mw = masks.first.shape
    scale = f"setpts=N/({fps:.6f}*TB),scale={w}:{h}:flags=bicubic,format=gray"
    if kind == "alpha":
        graph = f"[0:v]setpts=N/({fps:.6f}*TB),format=yuv420p[c];[1:v]{scale}[m];[c][m]alphamerge,format=yuva420p[v]"
        codec = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", str(WEBM_CRF), "-b:v", "0", "-deadline", "good",
                 "-cpu-used", "4", "-row-mt", "1", "-auto-alt-ref", "0", "-g", str(_gop(fps))]
    else:
        graph = f"[1:v]{scale},format=yuv420p[v]"
        codec = [*VIDEO_ARGS, "-g", str(_gop(fps))]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.part{out.suffix}")
    _encode(media, tmp, graph, codec, masks, mw, mh, fps)
    tmp.replace(out)
    return _report(media, out, kind, masks, seg, t0)


def _treat_graph(w: int, h: int, fps: float, blur: float, dim: float, far: float | None = None) -> str:
    """Person over a blurred, darkened background, without the two cut-out tells measured on the
    founder's takes: a light rim (soft mask edges letting un-dimmed wall through) and a dark glow
    (the blur smearing hair and shirt into the wall). The subject alpha is shrunk SHRINK px and
    feathered; the background is a normalized blur of background-only pixels (sum(bg*w)/sum(w),
    w = 1 - dilated mask), at half size in 16-bit, so nothing of the person bleeds into it. With `far`, a
    second, stronger blur takes over toward the top of the frame (FAR_TO: full above 0.30 H, none below 0.40 H)."""
    hw, hh, k, sg = w // 2 // 2 * 2, h // 2 // 2 * 2, 1.0 - dim, blur / 2
    pts = f"setpts=N/({fps:.6f}*TB)"
    norm = "blend=all_expr='if(gt(B\\,32)\\,min(65535\\,A*65535/B)\\,0)'"
    head = (f"[0:v]{pts},format=gbrp,split[a][b];"
            f"[1:v]{pts},scale={w}:{h}:flags=bicubic,format=gray,split[ma][mb];"
            f"[ma]{'erosion,' * SHRINK}gblur=sigma={FEATHER:g}[mf];[a][mf]alphamerge[fg];"
            f"[b]scale={hw}:{hh}:flags=area,format=gbrp16le[bs];"
            f"[mb]scale={hw}:{hh}:flags=area,{'dilation,' * GROW}negate,format=gbrp16le,split[w1][w2];"
            f"[bs][w1]blend=all_mode=multiply[pm];")
    if far is None or far <= blur:
        fill = f"[pm]gblur=sigma={sg:g}:steps=3[pb];[w2]gblur=sigma={sg:g}:steps=3[wb];[pb][wb]{norm}[fill];"
    else:
        a0, a1, sf = FAR_TO[0] * hh, FAR_TO[1] * hh, far / 2
        fill = (f"[pm]split[p1][p2];[w2]split[q1][q2];"
                f"[p1]gblur=sigma={sg:g}:steps=3[pb];[q1]gblur=sigma={sg:g}:steps=3[wb];[pb][wb]{norm}[near];"
                f"[p2]gblur=sigma={sf:g}:steps=3[pc];[q2]gblur=sigma={sf:g}:steps=3[wc];[pc][wc]{norm}[farb];"
                f"[near][farb]blend=all_expr='A+(B-A)*clip(({a1:.1f}-Y)/{a1 - a0:.1f}\\,0\\,1)'[fill];")
    return (head + fill + f"[fill]colorchannelmixer=rr={k:g}:gg={k:g}:bb={k:g},scale={w}:{h}:flags=bicubic,format=gbrp[bg];"
            f"[bg][fg]overlay=format=gbrp,format=yuv420p[v]")


def treat_background(media: Path, out: Path, blur: float = BLUR, dim: float = DIM, quality: str = QUALITY,
                     seg: Segmenter | None = None, far: float | None = BLUR_FAR) -> dict:
    """The take with only its background blurred (gaussian sigma `blur` px) and darkened by `dim`;
    the person keeps the original pixels, so skin cannot shift. Audio is copied."""
    media, out = Path(media), Path(out)
    t0 = time.perf_counter()
    seg = seg or get_segmenter(quality)
    w, h, fps = probe_video(media)
    masks = _Masks(media, seg, w, h)
    mh, mw = masks.first.shape
    graph = _treat_graph(w, h, fps, blur, dim, far)
    codec = [*VIDEO_ARGS, "-g", str(_gop(fps)), "-movflags", "+faststart"]   # same encode as a normalized take
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.part{out.suffix}")
    _encode(media, tmp, graph, codec, masks, mw, mh, fps, audio=True)
    tmp.replace(out)
    return {**_report(media, out, "treated", masks, seg, t0), "blur": blur, "dim": dim, "blur_far": far}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="python -m reel_director.matte", description="subject matte for a take")
    ap.add_argument("media")
    ap.add_argument("--out", required=True)
    ap.add_argument("--kind", choices=["alpha", "mask", "treated"], default="alpha")
    ap.add_argument("--quality", choices=["fast", "balanced", "accurate"], default=QUALITY)
    args = ap.parse_args(argv)
    if args.kind == "treated":
        r = treat_background(Path(args.media), Path(args.out), quality=args.quality)
    else:
        r = matte(Path(args.media), Path(args.out), args.kind, args.quality)
    print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
