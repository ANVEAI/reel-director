"""Face detection on rendered frames for QA (contract v2 'faces are sacred').

VISION's reel_director.face is the single source of truth: its backend (Apple Vision via pyobjc) detects the
faces, its protected_box() is the padded eyes+nose+mouth box no text may touch, chin_clear_y() is where a caption
may start under a beard, and reframe_eye() says how far the eye line can move inside the 1.10 zoom cap. Without
pyobjc (no `[mac]` extra) a small Apple Vision helper compiled once with swiftc stands in (cached by source hash
under $REEL_DIRECTOR_CACHE, default ~/.cache/reel-director); without either, QA warns that faces were not checked.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import face as vision
from .before_after import write_png

FACE_PAD = 0.06                       # contract: padded face box, 6 % of face height
SCALE = 0.5                           # QA analysis frames are 540x960


# ------------------------------------------------------------------------------------------------ geometry
def inter(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def pad_box(b, p: float) -> list[float]:
    return [b[0] - p, b[1] - p, b[2] + 2 * p, b[3] + 2 * p]


def face_core(f: dict) -> list[float]:
    """Padded eyes+nose+mouth box (contract 'faces are sacred'): VISION's protected_box, in reel pixels."""
    return vision.protected_box(f)


def face_record(d: dict, s: float) -> dict | None:
    """Swift helper output (one image) -> contract per-frame face (largest face), scaled by s to reel pixels."""
    faces = sorted(d.get("faces") or [], key=lambda f: -f["box"][2] * f["box"][3])
    if not faces:
        return None
    f, lm = faces[0], faces[0].get("landmarks") or {}
    box = [v * s for v in f["box"]]
    rec = {"box": [round(v, 1) for v in box], "conf": round(float(f.get("conf", 0)), 3)}
    if lm.get("leftEye") and lm.get("rightEye") and lm.get("outerLips"):
        eyes = sorted((np.mean(np.asarray(lm[k], float), 0) * s).tolist() for k in ("leftEye", "rightEye"))
        rec["eyes"] = [[round(v, 1) for v in e] for e in eyes]
        rec["mouth"] = [round(v * s, 1) for v in np.mean(np.asarray(lm["outerLips"], float), 0)]
        if lm.get("faceContour"):
            rec["chin_y"] = round(max(p[1] for p in lm["faceContour"]) * s, 1)
    else:
        x, y, w, h = box
        rec.update(eyes=[[x + 0.3 * w, y + 0.4 * h], [x + 0.7 * w, y + 0.4 * h]], mouth=[x + 0.5 * w, y + 0.78 * h])
    rec.setdefault("chin_y", round(box[1] + box[3], 1))
    return rec


# ------------------------------------------------------------------------------------------------ face backend
_SWIFT = r"""
import Foundation
import ImageIO
import Vision
var out: [[String: Any]] = []
for p in CommandLine.arguments.dropFirst() {
  guard let s = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil),
        let img = CGImageSourceCreateImageAtIndex(s, 0, nil) else { out.append(["path": p, "faces": []]); continue }
  let W = Double(img.width), H = Double(img.height)
  let req = VNDetectFaceLandmarksRequest()
  try? VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
  var faces: [[String: Any]] = []
  for f in req.results ?? [] {
    let b = f.boundingBox
    var lm: [String: Any] = [:]
    if let L = f.landmarks {
      let rs: [(String, VNFaceLandmarkRegion2D?)] = [("leftEye", L.leftEye), ("rightEye", L.rightEye),
        ("nose", L.nose), ("outerLips", L.outerLips), ("faceContour", L.faceContour)]
      for (k, r) in rs { if let r = r { lm[k] = r.pointsInImage(imageSize: CGSize(width: W, height: H)).map { [Double($0.x), H - Double($0.y)] } } }
    }
    faces.append(["box": [b.minX * W, (1 - b.maxY) * H, b.width * W, b.height * H], "conf": Double(f.confidence), "landmarks": lm])
  }
  out.append(["path": p, "faces": faces])
}
FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]))
"""


def swift_helper() -> Path | None:
    """Compile the Apple Vision helper once (keyed by its source hash); None off macOS / without swiftc."""
    cache = Path(os.environ.get("REEL_DIRECTOR_CACHE", Path.home() / ".cache" / "reel-director"))
    b = cache / f"qa-face-{hashlib.sha1(_SWIFT.encode()).hexdigest()[:12]}"
    if b.exists():
        return b
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        return None
    cache.mkdir(parents=True, exist_ok=True)
    src = b.with_suffix(".swift")
    src.write_text(_SWIFT)
    tmp = b.with_name(b.name + ".tmp")
    if subprocess.run(["swiftc", "-O", "-o", str(tmp), str(src)], capture_output=True, timeout=300).returncode:
        return None
    os.replace(tmp, b)
    return b


def _vision_faces(frames: np.ndarray, s: float) -> list[dict | None] | None:
    try:
        be = vision.get_backend()
    except vision.FaceUnavailable:
        return None
    out = []
    for fr in frames:
        f = be.detect(np.dstack([fr, np.zeros(fr.shape[:2], np.uint8)]))
        out.append(None if f is None else {
            "box": [round(v * s, 1) for v in f.box], "eyes": [[round(v * s, 1) for v in e] for e in f.eyes],
            "mouth": [round(v * s, 1) for v in f.mouth], "chin_y": round(f.chin_y * s, 1), "conf": round(f.conf, 3)})
    return out


def detect_faces(frames: np.ndarray, s: float = 1 / SCALE) -> tuple[list[dict | None], str]:
    """Largest face per frame in reel pixels (contract per-frame format), plus the backend name."""
    out = _vision_faces(frames, s)
    if out is not None:
        return out, "reel_director.face/vision"
    b = swift_helper()
    if b is None:
        return [None] * len(frames), "none"
    with tempfile.TemporaryDirectory() as td:
        paths = [str(write_png(Path(td) / f"f{k:04d}.png", fr, level=1)) for k, fr in enumerate(frames)]
        r = subprocess.run([str(b), *paths], capture_output=True, timeout=600)
    if r.returncode:
        return [None] * len(frames), "none"
    return [face_record(d, s) for d in json.loads(r.stdout)], "apple-vision-swift"


def reframed(f: dict, h: float) -> dict:
    """Where the face lands after the auto-reframe (VISION reframe_eye: eye line toward 0.40 H, zoom <= 1.10,
    frame always filled): {"scale", "eye_y", "map"} with map(y) -> y after, in pixels of height h."""
    eye = (f["eyes"][0][1] + f["eyes"][1][1]) / 2 / h
    sc, after = vision.reframe_eye(eye)
    top = eye - after / sc
    return {"scale": sc, "eye_y": after, "map": lambda y: (y / h - top) * sc * h}


# ------------------------------------------------------------------------------------------------ head clearance
HEAD_CLEAR = 16                       # px: text sits >= 16 px above the person matte's head top (HQ review, real-1)
HAIR_EST = 0.48                       # no segmenter: head top = face box top - 0.48 x face h (real-1 matte, 0.46-0.50)


def head_tops(frames: np.ndarray, faces: list, s: float = 1 / SCALE) -> tuple[list[float | None], str]:
    """Head top (reel px) per frame: walk up the person matte from the forehead through rows the subject fills
    (>= 15 % of the face's middle columns, gaps <= 3 px), so hair counts and a caption touching the hair merges
    into it (and is caught). Without Apple Vision segmentation: the face box top - HAIR_EST x face h."""
    try:
        from .matte import get_segmenter
        seg = get_segmenter()
    except Exception:                      # no macOS Vision: the estimate
        seg = None
    out = []
    for fr, f in zip(frames, faces):
        if f is None:
            out.append(None)
            continue
        x, y, w, h = f["box"]
        if seg is None:
            out.append(y - HAIR_EST * h)
            continue
        m = seg.mask(np.dstack([fr, np.zeros(fr.shape[:2], np.uint8)]))
        sy, sx = m.shape[0] / (fr.shape[0] * s), m.shape[1] / (fr.shape[1] * s)
        cols = m[:, max(0, int((x + 0.15 * w) * sx)):max(1, int((x + 0.85 * w) * sx))] >= 128
        r, top, gap = int((y + 0.1 * h) * sy), None, 0
        while r >= 0 and gap <= 3 * sy:
            if cols[r].mean() >= 0.15:
                top, gap = r, 0
            else:
                gap += 1
            r -= 1
        out.append(None if top is None else top / sy)
    return out, "vision-person" if seg is not None else "estimate"


def head_gate(ts, frames, faces, boxes_at, skip) -> dict:
    """Text over the hair (HQ: the face-core gate passed while hook captions sat on the hair): every caption / title
    box that overlaps the head's columns and sits above the chin must end >= HEAD_CLEAR px above the matte's head
    top. Frames under a full card or a split / pip relocation are skipped (skip(t) -> True)."""
    keep = [k for k, (t, f) in enumerate(zip(ts, faces)) if f is not None and not skip(t)
            and any(bx["kind"] in ("caption", "title") for bx in boxes_at(t))]
    tops, how = head_tops(frames[keep], [faces[k] for k in keep]) if keep else ([], "none")
    bad, worst, checked = [], None, 0
    for k, top in zip(keep, tops):
        if top is None:
            continue
        f, t = faces[k], ts[k]
        x, y, w, h = f["box"]
        checked += 1
        for bx in (b for b in boxes_at(t) if b["kind"] in ("caption", "title")):
            bx0, by0, bw, bh = bx["box"]
            if bx0 < x + 0.9 * w and x + 0.1 * w < bx0 + bw and by0 < f.get("chin_y", y + h):
                clear = top - (by0 + bh)
                if worst is None or clear < worst["clearance_px"]:
                    worst = {"t": round(t, 3), "id": bx["id"], "text": bx.get("text", ""), "clearance_px": round(clear, 1),
                             "head_top": round(top, 1), "box": [round(v) for v in bx["box"]]}
                if clear < HEAD_CLEAR:
                    bad.append(t)
    n = len(set(bad))
    val = {"frames_checked": checked, "frames_on_hair": n, "head_top_from": how, "worst": worst}
    tgt = f">= {HEAD_CLEAR} px above the head top"
    if not checked:
        return {"id": "head_clearance", "level": "ok", "value": val, "target": tgt, "fix": None,
                "message": "no caption or title above a visible face"}
    if not n:
        return {"id": "head_clearance", "level": "ok", "value": val, "target": tgt, "fix": None,
                "message": f"text clears the head top by >= {worst['clearance_px']:.0f} px in {checked} frames"}
    return {"id": "head_clearance", "level": "fail", "value": val, "target": tgt,
            "fix": {"op": "move_caption", "args": {"zone": "above-head"}},
            "message": f"text sits on the hair in {n}/{checked} frames; worst {worst['id']} '{worst['text']}' at "
                       f"{worst['t']:.2f}s ends {-worst['clearance_px']:.0f} px below the head top"}
