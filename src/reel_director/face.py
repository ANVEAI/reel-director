"""Face track per take: eyes, mouth, chin and face box every `step` frames, smoothed.

Writes `qa/<take>.face.json` (v2 contract) in pixels of the normalized take, top-left origin:
  {"version":1,"take","w","h","fps","step","backend",
   "frames":[{"t","box":[x,y,w,h],"eyes":[[lx,ly],[rx,ry]],"mouth":[mx,my],"chin_y","conf"} | null, ...],
   "summary":{"eye_y_med","face_h_med","center_x_med","present","stable", ...extras}}
"eyes" are the pupils, image-left first. "mouth" is the centre of the outer lip contour and
"chin_y" the lowest point of the jaw contour. Ratios are shares of w (x) or h (y).

Backend: Apple Vision (VNDetectFaceLandmarksRequest, revision pinned) through pyobjc on macOS,
measured at 16 ms per 1080x1920 frame. `FaceBackend` is the seam for a mediapipe backend on
Linux/SaaS. Nothing here imports torch.

Smoothing is offline and zero-phase: gaps up to MAX_GAP samples are interpolated (a detector
blink), then each run of samples gets a 5-sample median (outliers) and a gaussian of SIGMA
samples. On the four real takes this cuts eye-line jitter (std of the 2nd difference) from
4.1-4.8 px to 0.7-1.0 px while keeping head moves.

Prep renames takes (raw/turn-2.mp4 became prepped/turn-1.mp4 in work/real-1), so track the clip
a consumer will load and key the JSON by that clip's stem; video is stream-copied by prep, so
pixels and times match the raw take.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Protocol

import numpy as np

VERSION = 1
STEP = 3              # analyse every 3rd frame (10 samples/s at 30 fps)
MAX_GAP = 2           # samples: a missed detection this short is interpolated
MEDIAN = 5            # samples: outlier rejection window
SIGMA = 1.5           # samples: gaussian smoothing (0.15 s at step 3, 30 fps)
IPD_CM = 6.3          # mean adult interpupillary distance: the ruler for "move ~N cm"
STABLE_PRESENT = 0.9  # a "stable" take has the face in >= 90% of samples...
STABLE_EYE_Y = 0.04   # ...an eye line whose p5-p95 spread is <= 4% of H...
STABLE_X = 0.06       # ...and a face centre whose p5-p95 spread is <= 6% of W
PAD = 0.06            # protected-box pad as a share of face height ("faces are sacred")
# Protected box (eyes+nose+mouth), in units of the pupil distance. Measured on the real takes
# from Vision's eye and lip contours: eye corners 0.20 beyond the pupils, eye lids +-0.06,
# lips 0.43 half-width and 0.24 below their centre (brows sit 0.40 above the eye line).
EYE_SIDE, EYE_TOP, LIP_SIDE, LIP_BOTTOM = 0.25, 0.10, 0.45, 0.25
# chin_y is Vision's jaw line. A beard hangs lower: 0.24-0.29 x pupil distance (35-45 px) on the
# founder's takes, so anything placed "below the chin" starts CHIN_CLEAR below it.
CHIN_CLEAR = 0.35
TARGET_EYE_Y = 0.40   # contract: eye line at 0.40 H +- 0.03 after the auto-reframe
EYE_TOL = 0.03
REFRAME_MAX = 1.10    # contract: reframe scale cap for 1080-wide takes


class FaceUnavailable(RuntimeError):
    """No face backend on this machine (not macOS, or pyobjc Vision not installed)."""


@dataclass(frozen=True)
class Face:
    box: tuple[float, float, float, float]              # x, y, w, h
    eyes: tuple[tuple[float, float], tuple[float, float]]  # pupils, image-left first
    mouth: tuple[float, float]
    chin_y: float
    conf: float

    def vector(self) -> list[float]:
        (lx, ly), (rx, ry) = self.eyes
        return [*self.box, lx, ly, rx, ry, *self.mouth, self.chin_y, self.conf]

    @classmethod
    def from_vector(cls, v) -> Face:
        v = [float(x) for x in v]
        return cls(tuple(v[0:4]), ((v[4], v[5]), (v[6], v[7])), (v[8], v[9]), v[10], v[11])


class FaceBackend(Protocol):
    name: str

    def detect(self, rgbx: np.ndarray) -> Face | None:
        """The main face in an (h, w, 4) uint8 RGBX frame, in its pixel coords; None if no face."""


# --- Apple Vision ---------------------------------------------------------------------------

class VisionBackend:
    name = "vision"

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise FaceUnavailable("Apple Vision needs macOS (a mediapipe backend is the Linux path)")
        try:
            import Quartz
            import Vision
        except ImportError as e:
            raise FaceUnavailable("pyobjc Vision is not installed: pip install 'reel-director[mac]'") from e
        self.Q, self.V = Quartz, Vision
        self.space = Quartz.CGColorSpaceCreateDeviceRGB()

    def cgimage(self, rgbx: np.ndarray):
        h, w = rgbx.shape[:2]
        buf = np.ascontiguousarray(rgbx).tobytes()
        prov = self.Q.CGDataProviderCreateWithData(None, buf, len(buf), None)
        return self.Q.CGImageCreate(w, h, 8, 32, w * 4, self.space, self.Q.kCGImageAlphaNoneSkipLast, prov, None,
                                    False, self.Q.kCGRenderingIntentDefault)

    def detect(self, rgbx: np.ndarray) -> Face | None:
        h, w = rgbx.shape[:2]
        req = self.V.VNDetectFaceLandmarksRequest.alloc().init()
        req.setRevision_(self.V.VNDetectFaceLandmarksRequestRevision3)   # pinned: same input, same output
        handler = self.V.VNImageRequestHandler.alloc().initWithCGImage_options_(self.cgimage(rgbx), None)
        ok, err = handler.performRequests_error_([req], None)
        if not ok:
            raise RuntimeError(f"Vision face landmarks failed: {err}")
        faces = [f for f in (self._face(o, w, h) for o in (req.results() or [])) if f]
        return max(faces, key=lambda f: f.box[2] * f.box[3], default=None)

    def _face(self, obs, w: int, h: int) -> Face | None:
        lm = obs.landmarks()
        if lm is None:
            return None
        size = self.Q.CGSizeMake(w, h)

        def pts(region) -> np.ndarray | None:
            if region is None or region.pointCount() == 0:
                return None
            p = region.pointsInImageOfSize_(size)
            return np.array([(p[i].x, h - p[i].y) for i in range(region.pointCount())], dtype=np.float64)

        eyes = []
        for pupil, contour in ((lm.leftPupil(), lm.leftEye()), (lm.rightPupil(), lm.rightEye())):
            p = pts(pupil)
            p = p if p is not None else pts(contour)
            if p is None:
                return None
            eyes.append(tuple(p.mean(axis=0)))
        lips, jaw = pts(lm.outerLips()), pts(lm.faceContour())
        if lips is None:
            return None
        bb = obs.boundingBox()
        box = (bb.origin.x * w, (1 - bb.origin.y - bb.size.height) * h, bb.size.width * w, bb.size.height * h)
        chin = float(jaw[:, 1].max()) if jaw is not None else box[1] + box[3]
        eyes.sort()
        return Face(box, (eyes[0], eyes[1]), tuple(lips.mean(axis=0)), chin,
                    float(min(obs.confidence(), lm.confidence())))


BACKENDS: dict[str, Callable[[], FaceBackend]] = {"vision": VisionBackend}


def get_backend(name: str = "auto") -> FaceBackend:
    """'auto' picks the first backend that loads on this machine; raises FaceUnavailable if none."""
    names = list(BACKENDS) if name == "auto" else [name]
    errors = []
    for n in names:
        if n not in BACKENDS:
            raise FaceUnavailable(f"unknown face backend {n!r} (have: {', '.join(BACKENDS)})")
        try:
            return BACKENDS[n]()
        except FaceUnavailable as e:
            errors.append(str(e))
    raise FaceUnavailable("; ".join(errors))


# --- frames ---------------------------------------------------------------------------------

def probe_video(media: Path) -> tuple[int, int, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,avg_frame_rate", "-of", "json", str(media)],
                         check=True, capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = (s.get("avg_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return int(s["width"]), int(s["height"]), fps


def frames(media: Path, step: int = 1, w: int | None = None, h: int | None = None) -> Iterator[tuple[int, np.ndarray]]:
    """(frame index, (h, w, 4) RGBX) for every `step`-th decoded frame, streamed."""
    if w is None or h is None:
        w, h, _ = probe_video(media)
    vf = (f"select='not(mod(n\\,{step}))'," if step > 1 else "") + "format=rgb0"
    n = w * h * 4
    with tempfile.TemporaryFile() as err:
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-i", str(media), "-map", "0:v:0", "-vf", vf,
                              "-fps_mode", "passthrough", "-f", "rawvideo", "pipe:1"],
                             stdout=subprocess.PIPE, stderr=err)
        k = 0
        try:
            while len(buf := p.stdout.read(n)) == n:
                yield k * step, np.frombuffer(buf, np.uint8).reshape(h, w, 4)
                k += 1
        finally:
            p.stdout.close()
            if p.poll() is None:
                p.kill()
            p.wait()
        if k == 0:
            err.seek(0)
            raise RuntimeError(f"no video frames decoded from {media}: {err.read().decode(errors='replace')[-300:]}")


def frames_at(media: Path, times: Iterable[float]) -> list[np.ndarray]:
    """RGBX frames at given seconds (for checking a rendered output against its layout)."""
    w, h, _ = probe_video(media)
    out = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(media), "-frames:v", "1",
                            "-f", "rawvideo", "-pix_fmt", "rgb0", "pipe:1"], capture_output=True, check=True)
        out.append(np.frombuffer(r.stdout[: w * h * 4], np.uint8).reshape(h, w, 4))
    return out


def detect_at(media: Path, times: Iterable[float], backend: FaceBackend | None = None) -> list[dict | None]:
    """Unsmoothed faces at given seconds, as contract frame dicts (QA: is a caption on the face?)."""
    backend = backend or get_backend()
    times = list(times)
    return [_frame_dict(t, f) if (f := backend.detect(img)) else None
            for t, img in zip(times, frames_at(media, times), strict=True)]


# --- smoothing ------------------------------------------------------------------------------

def _runs(valid: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate([[0], valid.astype(np.int8), [0]])))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist()))


def _fill_gaps(v: np.ndarray, max_gap: int) -> np.ndarray:
    """Linearly interpolate interior NaN rows of up to `max_gap` samples."""
    v = v.copy()
    valid = ~np.isnan(v[:, 0])
    for a, b in _runs(~valid):
        if a > 0 and b < len(v) and b - a <= max_gap:
            w = (np.arange(a, b) - (a - 1))[:, None] / (b - (a - 1))
            v[a:b] = v[a - 1] * (1 - w) + v[b] * w
    return v


def _filter(x: np.ndarray, median: int, sigma: float) -> np.ndarray:
    """Median then gaussian along axis 0, edge-padded (zero phase: no lag)."""
    n = len(x)
    if n < 3:
        return x
    m = min(median, n if n % 2 else n - 1)
    r = m // 2
    padded = np.pad(x, ((r, r), (0, 0)), mode="edge")
    med = np.median(np.stack([padded[i:i + n] for i in range(m)]), axis=0)
    rad = int(np.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-rad, rad + 1) / sigma) ** 2)
    k /= k.sum()
    padded = np.pad(med, ((rad, rad), (0, 0)), mode="edge")
    return sum(k[i] * padded[i:i + n] for i in range(len(k)))


def smooth(raw: list[Face | None], max_gap: int = MAX_GAP, median: int = MEDIAN,
           sigma: float = SIGMA) -> list[Face | None]:
    """Fill short gaps, then median + gaussian within each run of detections. Confidence is
    left unsmoothed (interpolated across filled gaps)."""
    if not raw:
        return []
    v = np.array([f.vector() if f else [np.nan] * 12 for f in raw], dtype=np.float64)
    v = _fill_gaps(v, max_gap)
    valid = ~np.isnan(v[:, 0])
    for a, b in _runs(valid):
        v[a:b, :11] = _filter(v[a:b, :11], median, sigma)
    return [Face.from_vector(row) if ok else None for row, ok in zip(v, valid, strict=True)]


# --- track ----------------------------------------------------------------------------------

def _r(x: float, nd: int = 1) -> float:
    return round(float(x), nd)


def _frame_dict(t: float, f: Face) -> dict:
    return {"t": round(t, 3), "box": [_r(x) for x in f.box], "eyes": [[_r(x) for x in e] for e in f.eyes],
            "mouth": [_r(x) for x in f.mouth], "chin_y": _r(f.chin_y), "conf": _r(f.conf, 3)}


def _q(vals: list[float], q: float) -> float:
    return float(np.percentile(vals, q))


def summary(frames_: list[dict | None], w: int, h: int, detected: int | None = None) -> dict:
    """Per-take framing numbers (ratios of w/h). `detected` = raw detections (before gap fill)."""
    ok = [f for f in frames_ if f]
    n = len(frames_)
    present = (detected if detected is not None else len(ok)) / n if n else 0.0
    if not ok:
        return {"eye_y_med": None, "face_h_med": None, "center_x_med": None, "present": round(present, 3),
                "stable": False}
    eye_y = [(f["eyes"][0][1] + f["eyes"][1][1]) / 2 / h for f in ok]
    cx = [(f["box"][0] + f["box"][2] / 2) / w for f in ok]
    s = {"eye_y_med": float(np.median(eye_y)), "face_h_med": float(np.median([f["box"][3] / h for f in ok])),
         "center_x_med": float(np.median(cx)), "present": present,
         "eye_x_med": float(np.median([(f["eyes"][0][0] + f["eyes"][1][0]) / 2 / w for f in ok])),
         "top_y_med": float(np.median([f["box"][1] / h for f in ok])),
         "mouth_y_med": float(np.median([f["mouth"][1] / h for f in ok])),
         "chin_y_med": float(np.median([f["chin_y"] / h for f in ok])),
         "ipd_px_med": float(np.median([np.hypot(f["eyes"][1][0] - f["eyes"][0][0], f["eyes"][1][1] - f["eyes"][0][1])
                                        for f in ok])),
         "eye_y_spread": _q(eye_y, 95) - _q(eye_y, 5), "center_x_spread": _q(cx, 95) - _q(cx, 5)}
    s["stable"] = bool(present >= STABLE_PRESENT and s["eye_y_spread"] <= STABLE_EYE_Y
                       and s["center_x_spread"] <= STABLE_X)
    return {k: (round(v, 1) if k == "ipd_px_med" else round(v, 4)) if isinstance(v, float) else v
            for k, v in s.items()}


def face_track(media: Path, out: Path | None = None, step: int = STEP, backend: FaceBackend | None = None) -> dict:
    """Track the face in a normalized take; write the contract JSON to `out` (if given) and return it."""
    media = Path(media)
    backend = backend or get_backend()
    w, h, fps = probe_video(media)
    raw: list[Face | None] = []
    idx: list[int] = []
    for i, img in frames(media, step, w, h):
        idx.append(i)
        raw.append(backend.detect(img))
    sm = smooth(raw)
    frames_ = [_frame_dict(i / fps, f) if f else None for i, f in zip(idx, sm, strict=True)]
    track = {"version": VERSION, "take": media.stem, "w": w, "h": h, "fps": round(fps, 3), "step": step,
             "backend": backend.name, "frames": frames_,
             "summary": summary(frames_, w, h, detected=sum(1 for f in raw if f))}
    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.name}.part")
        tmp.write_text(json.dumps(track, separators=(",", ":")))
        tmp.replace(out)
    return track


def load(path: Path) -> dict:
    track = json.loads(Path(path).read_text())
    if track.get("version") != VERSION:
        raise ValueError(f"{path}: face track version {track.get('version')!r}, expected {VERSION}")
    return track


# --- helpers for layout / QA ----------------------------------------------------------------

def face_at(track: dict, t: float) -> dict | None:
    """The tracked face at `t` seconds: linear between the two nearest samples, None in a gap."""
    fr = track["frames"]
    if not fr:
        return None
    dt = track["step"] / track["fps"]
    k = min(max(t / dt, 0.0), len(fr) - 1.0)
    a, b = int(np.floor(k)), int(np.ceil(k))
    fa, fb, u = fr[a], fr[b], k - a
    if a == b or fa is None or fb is None:
        return fa if u < 0.5 else fb      # in a gap: the nearer sample, which may be None
    va, vb = Face.from_vector(_vec(fa)), Face.from_vector(_vec(fb))
    mix = [x * (1 - u) + y * u for x, y in zip(va.vector(), vb.vector(), strict=True)]
    return _frame_dict(t, Face.from_vector(mix))


def _vec(f: dict) -> list[float]:
    return [*f["box"], *f["eyes"][0], *f["eyes"][1], *f["mouth"], f["chin_y"], f["conf"]]


def protected_box(frame: dict, pad: float = PAD) -> list[float]:
    """Eyes + nose + mouth, padded by `pad` x face height: no caption/title/card box may overlap it."""
    (lx, ly), (rx, ry) = frame["eyes"]
    mx, my = frame["mouth"]
    ipd = max(np.hypot(rx - lx, ry - ly), 1.0)
    p = pad * frame["box"][3]
    x0 = min(lx - EYE_SIDE * ipd, mx - LIP_SIDE * ipd) - p
    x1 = max(rx + EYE_SIDE * ipd, mx + LIP_SIDE * ipd) + p
    y0 = min(ly, ry) - EYE_TOP * ipd - p
    y1 = my + LIP_BOTTOM * ipd + p
    return [_r(x0), _r(y0), _r(x1 - x0), _r(y1 - y0)]


def chin_clear_y(frame: dict, clear: float = CHIN_CLEAR) -> float:
    """First y below the chin (and a beard) where a caption may start."""
    (lx, ly), (rx, ry) = frame["eyes"]
    return _r(frame["chin_y"] + clear * max(np.hypot(rx - lx, ry - ly), 1.0))


def reframe_eye(eye_y: float, target: float = TARGET_EYE_Y, max_scale: float = REFRAME_MAX) -> tuple[float, float]:
    """(scale, eye line after) for the best frame-filling reframe toward `target` (ratios of H).
    Zoom s shows a window of height 1/s whose top may sit anywhere in [0, 1 - 1/s]; the eye then
    lands at (eye_y - top) * s. The smallest zoom that reaches the target wins."""
    best = (1.0, eye_y)
    for k in range(0, 101):
        s = 1.0 + (max_scale - 1.0) * k / 100
        top = min(max(eye_y - target / s, 0.0), 1.0 - 1.0 / s)
        out = (eye_y - top) * s
        if abs(out - target) < abs(best[1] - target) - 1e-9:
            best = (round(s, 4), out)
        if abs(out - target) < 1e-6:
            break
    return best[0], round(best[1], 4)


def overlaps(a: list[float], b: list[float]) -> bool:
    """Do two [x, y, w, h] boxes intersect (touching edges do not count)?"""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def px_per_cm(s: dict) -> float | None:
    """Pixels per centimetre at the face, from the pupil distance (mean adult 6.3 cm)."""
    return s["ipd_px_med"] / IPD_CM if s.get("ipd_px_med") else None


# --- prep / CLI -----------------------------------------------------------------------------

def prep_faces(media: Iterable[Path], qa_dir: Path, log: Callable[[str], None] = print,
               backend: FaceBackend | None = None) -> dict[str, dict]:
    """Prep hook: write qa_dir/<take>.face.json for each take; {} (with a note) when no backend."""
    try:
        backend = backend or get_backend()
    except FaceUnavailable as e:
        log(f"  face track skipped: {e}")
        return {}
    out = {}
    for m in media:
        s = face_track(Path(m), Path(qa_dir) / f"{Path(m).stem}.face.json", backend=backend)["summary"]
        out[Path(m).stem] = s
        if s["eye_y_med"] is None:
            log(f"  {Path(m).stem}: no face found")
        else:
            log(f"  {Path(m).stem}: face {s['present']:.0%}, eye line {s['eye_y_med']:.2f} H, "
                f"face {s['face_h_med']:.2f} H, centre {s['center_x_med']:.2f} W{'' if s['stable'] else ', moving'}")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m reel_director.face", description="face track for takes")
    ap.add_argument("media", nargs="+")
    ap.add_argument("--qa", required=True, help="directory for <take>.face.json")
    args = ap.parse_args(argv)
    prep_faces([Path(m) for m in args.media], Path(args.qa))
    return 0


if __name__ == "__main__":
    sys.exit(main())
