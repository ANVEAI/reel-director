"""Deterministic post-render QA gates (contract v2, 'Editing director') -> qa/report.json.

Every gate reads the RENDERED master or the compiled plan, never the intent: faces are detected on output frames
and intersected with the reel/layout.json boxes (text over face), caption and title contrast are measured on the
output pixels, pace comes from the compiled plan, loudness / true peak / A-V from the decoded master, black and
frozen stretches from ffmpeg, B-roll and face presence from the samples. Each gate is
{"id","level":"ok|warn|fail","value","target","message","fix"} with fix = a whitelisted director op or null.

A v1 build has no layout.json: its boxes are estimated from the v1 CSS geometry (reel.css constants) and the
report says so (layout_source "legacy-v1-estimate"). Face backend: VISION's `reel_director.face.detect_frames`
when present, else a small Apple Vision helper compiled once with swiftc (cached), else none (gate warns).

Usage: python -m reel_director.qa <build_dir> [--out DIR] [--master MP4]
"""
import argparse
import json
import re
import statistics
import subprocess
from pathlib import Path

import numpy as np

from .before_after import H, W, frame_index, grab, legacy_layout, write_png
from .pace import MEDIAN_RANGE, gaps_between, pace_cv
from .face import chin_clear_y, reframe_eye  # noqa: F401  (qa_media reads it as qa.reframe_eye)
from .qa_face import FACE_PAD, SCALE, detect_faces, face_core, head_gate, inter, pad_box, reframed

SAFE = (120, 288, 888, 1248)          # council 6 safe rect x0, y0, x1, y1
STEP = 0.2                            # output sample spacing (s)
PACE = {"calm": (4.0, 6.0, 0.15), "standard": (2.6, 4.0, 0.25), "punchy": (1.8, 3.0, 0.35)}  # median, static, B-roll
CV_FAIL, CV_LO, CV_HI = 0.25, 0.35, 0.75
EYE_TARGET, EYE_TOL = 0.40, 0.03
OPS = ("move_caption", "drop_cue", "change_preset_param", "reframe", "retake")
PENALTY = {"fail": 20, "warn": 5, "ok": 0}
PILL_ALPHA = 0.84                     # reel.css .cap-pill plate rgba(8, 8, 16, .84): >= 4.5:1 even over a white wall


def _gate(id_, level, value, target, message, fix=None) -> dict:
    return {"id": id_, "level": level, "value": value, "target": target, "message": message, "fix": fix}


# ------------------------------------------------------------------------------------------------ build
def load_build(build: Path, master: Path | None = None) -> dict:
    """Plan (rd-plan in reel/index.html), timeline, directed script, layout (or the v1 estimate), clip windows."""
    from .before_after import reel_videos
    reel = build / "reel"
    html = (reel / "index.html").read_text()
    plan = json.loads(re.search(r'<script type="application/json" id="rd-plan">(.*?)</script>', html, re.S).group(1))
    directed = json.loads((build / "directed.json").read_text()) if (build / "directed.json").exists() else {}
    if (reel / "layout.json").exists():
        layout, src = json.loads((reel / "layout.json").read_text()), "reel/layout.json"
    else:
        layout, src = legacy_layout(plan, html), "legacy-v1-estimate"
    return {"build": build, "plan": plan, "html": html, "directed": directed, "layout": layout, "layout_source": src,
            "tl": json.loads((reel / "timeline.json").read_text()), "videos": reel_videos(html),
            "master": Path(master) if master else build / "renders" / "reel-master.mp4",
            "style": directed.get("style") or {}}


def full_cards(b: dict) -> list[tuple[float, float]]:
    return [(c["t0"], c["t1"]) for c in b["layout"].get("cards", []) if c.get("layout", "full") == "full"]


def relocated(b: dict) -> list[tuple[float, float]]:
    """Split / pip card windows: the face is on screen but moved and scaled (no framing samples there)."""
    return [(c["t0"], c["t1"]) for c in b["layout"].get("cards", []) if c.get("layout") in ("split", "pip")]


def text_boxes(b: dict, t: float) -> list[dict]:
    """Boxes on screen at t (captions, title, non-full cards); [] while a full-screen card hides the face."""
    L = b["layout"]
    out = [{"id": c["chunk_id"], "kind": "caption", "box": c["box"], "text": c.get("text", "")}
           for c in L.get("captions", []) if c["t0"] <= t < c["t1"]]
    ti = L.get("title")
    if ti and ti.get("box") and ti["t0"] <= t < ti["t1"]:
        out.append({"id": ti.get("id", "title"), "kind": "title", "box": ti["box"], "text": ti.get("text", "")})
    out += [{"id": c["id"], "kind": "card", "box": c["box"], "text": c.get("text", "")}
            for c in L.get("cards", []) if c.get("layout", "full") != "full" and c.get("box") and c["t0"] <= t < c["t1"]]
    return out


def sample_times(b: dict) -> list[float]:
    D = float(b["plan"]["D"])
    ts = {frame_index(k * STEP, 30) / 30 for k in range(int(D / STEP) + 1)}
    ts |= {frame_index((c["t0"] + c["t1"]) / 2, 30) / 30 for c in b["layout"].get("captions", [])}
    return sorted(t for t in ts if t < D - 1 / 30)


def shot_at(b: dict, t: float) -> str:
    for sh in b["tl"]["shots"]:
        if sh["start"] <= t < sh["start"] + sh["duration"]:
            return sh["id"]
    return b["tl"]["shots"][-1]["id"] if b["tl"]["shots"] else ""


def fill_faces(b: dict, ts: list[float], faces: list) -> list:
    """A frame where the detector lost the face (caption across the mouth) borrows the nearest detection
    within 0.4 s of the same shot, so overlap is still measured; full-card frames stay None."""
    cards = full_cards(b)
    out = list(faces)
    for k, t in enumerate(ts):
        if out[k] is None and not any(a <= t < e for a, e in cards):
            near = [(abs(ts[j] - t), j) for j, f in enumerate(faces)
                    if f is not None and abs(ts[j] - t) <= 0.4 and shot_at(b, ts[j]) == shot_at(b, t)]
            if near:
                out[k] = {**faces[min(near)[1]], "borrowed": True}
    return out


# ------------------------------------------------------------------------------------------------ gates
def gate_text_over_face(b: dict, ts, faces) -> dict:
    hits, checked, per_shot, worst = [], 0, {}, None
    cards = full_cards(b)
    for t, f in zip(ts, faces):
        boxes = text_boxes(b, t)
        if not boxes or f is None or any(a <= t < e for a, e in cards):      # full card: face hidden by design
            continue
        checked += 1
        core = face_core(f)
        for bx in boxes:
            a = inter(bx["box"], core)
            if a > 0:
                pct = round(100 * a / (core[2] * core[3]), 1)
                hits.append(t)
                sh = shot_at(b, t)
                per_shot[sh] = per_shot.get(sh, 0) + 1
                if worst is None or pct > worst["face_covered_pct"]:
                    worst = {"t": round(t, 3), "id": bx["id"], "text": bx["text"], "face_covered_pct": pct,
                             "box": [round(v) for v in bx["box"]], "face_core": [round(v) for v in core]}
    n_hit = len(set(hits))
    val = {"frames_checked": checked, "frames_overlapping": n_hit,
           "share": round(n_hit / checked, 3) if checked else 0.0, "by_shot": per_shot, "worst": worst}
    if checked == 0:
        return _gate("text_over_face", "warn", val, "0 frames", "no face found on any frame with text: not verified")
    if not n_hit:
        return _gate("text_over_face", "ok", val, "0 frames", f"no text box touches the padded face in {checked} frames")
    return _gate("text_over_face", "fail", val, "0 frames",
                 f"text covers the face in {n_hit}/{checked} frames ({100 * n_hit / checked:.0f}%); worst "
                 f"{worst['id']} '{worst['text']}' at {worst['t']:.2f}s covers {worst['face_covered_pct']}% of the "
                 f"eyes-nose-mouth box", caption_fix(b, ts, faces, sorted(per_shot)))


def caption_fix(b: dict, ts, faces, shots) -> dict:
    """Contract zone order per shot, judged where the face lands after the auto-reframe (VISION reframe_eye: eye
    line toward 0.40 H inside the 1.10 zoom cap): below-chin if the caption fits between the beard-clear chin line
    and the safe bottom on >= 90 % of the shot's frames, else above-head (between the title band, or the safe top
    when no title is up, and the padded head top), else lower-band."""
    cap_h = max((c["box"][3] for c in b["layout"].get("captions", [])), default=180)
    ti = b["layout"].get("title")
    tally: dict[str, list[int]] = {s: [0, 0, 0] for s in shots}        # frames, below ok, above ok
    for t, f in zip(ts, faces):
        sh = shot_at(b, t)
        if f is None or sh not in tally:
            continue
        r, fh = reframed(f, H), f["box"][3]
        limit = 560 if ti and ti.get("box") and ti["t0"] <= t < ti["t1"] else SAFE[1]
        tally[sh][0] += 1
        tally[sh][1] += r["map"](chin_clear_y(f)) + cap_h <= SAFE[3]
        tally[sh][2] += r["map"](f["box"][1] - (0.2 + FACE_PAD) * fh) - cap_h >= limit
    zones = {s: "below-chin" if n and lo >= 0.9 * n else "above-head" if n and hi >= 0.9 * n else "lower-band"
             for s, (n, lo, hi) in tally.items()}
    if len(set(zones.values())) <= 1:
        return {"op": "move_caption", "args": {"zone": next(iter(zones.values()), "lower-band"), "shots": shots}}
    return {"op": "move_caption", "args": {"zones": zones}}


def _lum(rgb) -> np.ndarray:
    c = np.asarray(rgb, float) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return c @ np.array([0.2126, 0.7152, 0.0722])


def contrast(l1: float, l2: float) -> float:
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def _hex(h: str) -> tuple:
    h = (h or "#FFFFFF").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _crop(fr, box, grow=0):
    x, y, w, h = (int(round(v * SCALE)) for v in pad_box(box, grow))
    return fr[max(y, 0):max(y + h, 0), max(x, 0):max(x + w, 0)]


def _ring(fr, box, grow: int = 20) -> np.ndarray:
    """Pixels in a `grow`-px band around the box (what the text sits on), not the box itself."""
    x, y, w, h = (int(round(v * SCALE)) for v in pad_box(box, grow))
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, fr.shape[1]), min(y + h, fr.shape[0])
    m = np.ones((max(y1 - y0, 0), max(x1 - x0, 0)), bool)
    g = int(round(grow * SCALE))
    m[max(y + g - y0, 0):max(y + h - g - y0, 0), max(x + g - x0, 0):max(x + w - g - x0, 0)] = False
    return fr[y0:y1, x0:x1][m]


def _edges(g: np.ndarray, m: np.ndarray | None = None, th: float = 0.08) -> float:
    """Share of pixels whose luma gradient exceeds th (texture / busyness), optionally inside mask m."""
    if g.shape[0] < 2 or g.shape[1] < 2:
        return 0.0
    e = np.hypot(np.diff(g, axis=0)[:, :-1], np.diff(g, axis=1)[:-1]) > th
    return float(e[m[:-1, :-1]].mean()) if m is not None and m[:-1, :-1].any() else float(e.mean())


def gate_caption_contrast(b: dict, ts, frames) -> dict:
    fam = b["layout"].get("caption_family") or b["style"].get("caption", "bold")
    lt = float(_lum(_hex(b["style"].get("text", "#FFFFFF"))))
    halos = []
    for t, fr in zip(ts, frames):
        for bx in text_boxes(b, t):
            ring = _ring(fr, bx["box"]) if bx["kind"] == "caption" else np.zeros((0, 3))
            if len(ring):
                halos.append(contrast(lt, float(np.percentile(_lum(ring), 90))))
    if not halos:
        return _gate("caption_contrast", "ok", None, ">= 4.5:1", "no captions sampled")
    worst = min(halos)
    plate = {"bold": 21.0, "pop": 21.0, "karaoke": 21.0, "boxed": contrast(_lum((17, 17, 17)), 1.0)}.get(fam)
    if fam == "pill":
        plate = contrast(lt, PILL_ALPHA * float(_lum((8, 8, 16))) + (1 - PILL_ALPHA) * (1.05 / worst - 0.05))
    eff = plate if plate is not None else worst
    val = {"family": fam, "halo_min": round(worst, 2), "halo_median": round(statistics.median(halos), 2),
           "under_3_share": round(sum(h < 3 for h in halos) / len(halos), 3), "effective": round(eff, 2),
           "samples": len(halos)}
    lvl = "fail" if eff < 4.5 else "warn" if (plate == 21.0 and val["under_3_share"] > 0.5) else "ok"
    msg = (f"caption text {eff:.1f}:1 effective ({fam}); the frame around the box is {worst:.2f}:1 (worst) / "
           f"{val['halo_median']:.2f}:1 (median) against the text colour, {100 * val['under_3_share']:.0f}% of "
           f"samples under 3:1" + (", so legibility rides on the stroke alone" if lvl == "warn" else ""))
    fix = {"op": "change_preset_param", "args": {"param": "caption", "value": "pill"}} if lvl != "ok" else None
    return _gate("caption_contrast", lvl, val, ">= 4.5:1 effective", msg, fix)


def gate_title(b: dict, ts, frames, raw_frames: dict) -> dict:
    """Title text vs its plate (WCAG, text pixels dilated out), texture showing through the plate on the output,
    and busyness of the take behind the title box (contract: busy -> solid or blurred backdrop, >= 4.5:1)."""
    from scipy.ndimage import binary_dilation
    ti = b["layout"].get("title")
    if not ti or not ti.get("box"):
        return _gate("title_legibility", "ok", None, ">= 4.5:1", "no title")
    st = b["style"]
    lt = float(_lum(_hex(st.get("text", "#FFFFFF"))))
    ink = np.array([_hex(st.get("text", "#FFFFFF")), _hex(st.get("accent", "#FFE14D"))], float)
    plates, through = [], []
    for t, fr in zip(ts, frames):
        steady = ti["t0"] + (0.2 if ti["t0"] > 0 else 0.0) <= t < ti["t1"] - 0.2      # entrance / exit excluded
        reg = _crop(fr, ti["box"]).astype(float) if steady else np.zeros((0, 0, 3))
        if reg.size:
            m = ~binary_dilation(np.min(np.linalg.norm(reg[:, :, None] - ink[None, None], axis=3), axis=2) < 120,
                                 iterations=3)
            if m.any():
                plates.append(float(np.percentile(_lum(reg[m]), 90)))
                through.append(_edges(reg.mean(axis=2) / 255, m))
    busy = [_edges(_crop(fr, ti["box"]).mean(axis=2) / 255) for fr in raw_frames.values()]
    if not plates:
        return _gate("title_legibility", "ok", None, ">= 4.5:1", "title not sampled")
    c, sh, bz = contrast(lt, max(plates)), max(through), max(busy, default=0.0)
    val = {"contrast_min": round(c, 2), "show_through": round(sh, 3), "behind_edge_density": round(bz, 3),
           "busy": bz > 0.06}
    lvl = "fail" if c < 3.0 or (val["busy"] and sh > 0.03) else "warn" if c < 4.5 else "ok"
    msg = (f"title text {c:.1f}:1 over its plate; background behind the title "
           + (f"is busy (edge density {bz:.2f})" if val["busy"] else f"is calm ({bz:.2f})")
           + (f" and shows through the plate (texture {sh:.3f} > 0.03): needs a solid or blurred backdrop"
              if val["busy"] and sh > 0.03 else ""))
    fix = {"op": "change_preset_param", "args": {"param": "title_backdrop", "value": "solid"}} if lvl != "ok" else None
    return _gate("title_legibility", lvl, val, ">= 4.5:1; busy -> solid/blur backdrop", msg, fix)


def gate_safe(b: dict) -> dict:
    L, bad = b["layout"], []
    for c in L.get("captions", []) + ([L["title"]] if L.get("title") else []):
        x, y, w, h = c["box"]
        if x < SAFE[0] - 0.5 or y < SAFE[1] - 0.5 or x + w > SAFE[2] + 0.5 or y + h > SAFE[3] + 0.5:
            bad.append({"id": c.get("chunk_id") or c.get("id", "title"), "box": [round(v) for v in c["box"]]})
    return _gate("safe_zone", "fail" if bad else "ok", {"outside": bad}, f"inside x {SAFE[0]}-{SAFE[2]}, y {SAFE[1]}-{SAFE[3]}",
                 f"{len(bad)} text box(es) outside the safe rect" if bad else "all text inside the safe rect",
                 {"op": "move_caption", "args": {"zone": "lower-band"}} if bad else None)


def _norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w.lower())


def plan_changes(b: dict) -> list[tuple[float, str]]:
    """Visible picture changes of the compiled plan: cuts, punches, full-card in/out (hidden ones dropped)."""
    P, fps = b["plan"], float(b["plan"]["fps"])
    cards = full_cards(b)
    under = lambda t: any(a + 1e-6 < t < e - 1e-6 for a, e in cards)          # noqa: E731
    wins = {v["id"][5:]: (v["start"], v["start"] + v["duration"]) for v in b["videos"]}
    ch = [(v["start"], "cut") for v in b["videos"] if v["start"] > 1e-6 and not under(v["start"])]
    for seg in P.get("segs", []):
        a, e = wins.get(seg["layer"][2:], (0.0, float(P["D"])))
        ch += [(f / fps, "punch") for f, _ in seg.get("punches", []) if a + 0.5 / fps < f / fps < e and not under(f / fps)]
    for a, e in cards + relocated(b):         # split / pip cards change the picture as much as a full one
        ch += [(a, "card")] + ([(e, "card-out")] if e < float(P["D"]) - 1e-6 else [])
    ch += [(it["s"] + it["media"]["beat"], "broll-beat") for it in P.get("items", [])     # a bridged insert's punch-in
           if (it.get("media") or {}).get("beat") is not None]
    out: list[tuple[float, str]] = []
    for t, k in sorted(ch):
        if not out or t - out[-1][0] > 2.5 / fps:
            out.append((round(t, 4), k))
    return out


def pace_numbers(ch: list[float], D: float) -> dict:
    g = gaps_between(ch)
    ends = [y - x for x, y in zip([0.0] + ch, ch + [D])]
    return {"changes": len(ch), "median_gap": round(statistics.median(g), 2) if g else round(D, 2),
            "cv": round(pace_cv(ch), 3), "max_static": round(max(ends), 2), "first_change": round(ch[0], 2) if ch else None,
            "by_3s": sum(t <= 3.0 for t in ch)}


def punch_cue(b: dict, t: float) -> dict | None:
    """The auto punch cue of directed.json that lands at reel time t (its word starts within 0.12 s)."""
    for sh, tsh in zip(b["directed"].get("shots", []), b["tl"]["shots"]):
        for c in sh.get("cues", []):
            if c.get("type") == "punch" and c.get("auto") and not c.get("open"):
                w = next((w for w in tsh["words"] if _norm(w["w"]) == _norm(str(c["at"]).split()[0])), None)
                if w and abs(w["s"] - t) <= 0.12:
                    return {"shot": sh["id"], "type": "punch", "at": c["at"]}
    return None


def gate_pace(b: dict) -> dict:
    name = b["style"].get("pace", "standard")
    med, static, _ = PACE.get(name, PACE["standard"])
    lo, hi = MEDIAN_RANGE.get(name, MEDIAN_RANGE["standard"])     # the policy's re-plan range (pace.py)
    chg = plan_changes(b)
    ch, D = [t for t, _ in chg], float(b["plan"]["D"])
    v = pace_numbers(ch, D)
    rng = lambda n: n["changes"] < 4 or lo - 1e-9 <= n["median_gap"] <= hi + 1e-9      # noqa: E731 (pace.gate_of)
    bad = [m for m, c in ((f"CV {v['cv']:.2f} < {CV_FAIL} (metronomic)", v["cv"] < CV_FAIL),
                          (f"static {v['max_static']:.2f}s > {static}s", v["max_static"] > static),
                          (f"median gap {v['median_gap']}s outside {lo:.2f}-{hi:.2f}s", not rng(v)),   # enforced (P3)
                          (f"first change {v['first_change']}s > 1.0s", (v["first_change"] or 9) > 1.0)) if c]
    soft = [m for m, c in ((f"CV {v['cv']:.2f} outside {CV_LO}-{CV_HI}", not CV_LO <= v["cv"] <= CV_HI),
                           (f"{v['by_3s']} change(s) by 3 s (< 2)", v["by_3s"] < 2)) if c]
    fix = None
    if bad:      # the punch whose drop clears the most failing conditions (never adding a static / late-first one)
        nb = lambda n: (n["cv"] < CV_FAIL) + (n["max_static"] > static) + (not rng(n)) + ((n["first_change"] or 9) > 1.0)  # noqa: E731
        best = None
        for t, k in chg:
            cue = punch_cue(b, t) if k == "punch" else None
            if cue:
                n = pace_numbers([x for x in ch if x != t], D)
                if nb(n) < len(bad) and n["max_static"] <= static and (n["first_change"] or 9) <= 1.0 \
                        and (best is None or (nb(n), -n["cv"]) < best[0]):
                    best = ((nb(n), -n["cv"]), cue)
        fix = {"op": "drop_cue", "args": best[1]} if best else None
    v.update(pace=name, at=[[t, k] for t, k in chg])
    return _gate("pace", "fail" if bad else "warn" if soft else "ok", v,
                 f"{name}: median {med}s, CV {CV_LO}-{CV_HI} (fail < {CV_FAIL}), static <= {static}s, first <= 1.0s",
                 "pace: " + "; ".join(bad + soft) if bad or soft else "pace within the preset", fix)


def gate_audio(m: dict) -> list[dict]:
    bad = [s for s, c in ((f"{m['lufs']} LUFS (target -14 +-0.5)", abs(m["lufs"] + 14.0) > 0.5),
                          (f"true peak {m['true_peak']} dBTP > -1.5", m["true_peak"] > -1.5),
                          (f"short-term max {m['short_term_max']} LUFS > -9", m["short_term_max"] > -9.0)) if c]
    av = abs(m["av_offset_ms"]) <= 1000 / 30 + 0.1 and abs(m["av_duration_diff_ms"]) <= 1000 / 30 + 0.1
    lv = {k: m[k] for k in ("lufs", "true_peak", "short_term_max")}
    return [_gate("loudness", "fail" if bad else "ok", lv, "-14 +-0.5 LUFS, TP <= -1.5 dBTP, ST <= -9 LUFS",
                  "master: " + ("; ".join(bad) if bad else f"{m['lufs']} LUFS, TP {m['true_peak']} dBTP")),
            _gate("av_sync", "ok" if av else "fail", {k: m[k] for k in ("av_offset_ms", "av_duration_diff_ms")},
                  "<= 1 frame", f"A/V start offset {m['av_offset_ms']} ms, duration diff {m['av_duration_diff_ms']} ms")]


def black_frozen(master: Path, D: float) -> dict:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(master), "-vf",
                          "blackdetect=d=0.1:pix_th=0.10,freezedetect=n=0.003:d=0.5", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    bl = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    fs = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    fe = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)] + [D] * len(fs)
    return {"black": bl, "frozen": list(zip(fs, fe[:len(fs)]))}


def gate_black_frozen(b: dict, bf: dict) -> dict:
    cards = full_cards(b)
    inside = lambda s: any(s[0] >= a - 0.1 and s[1] <= e + 0.1 for a, e in cards)   # noqa: E731
    spans = [("black", s) for s in bf["black"]] + [("frozen", s) for s in bf["frozen"]]
    hard = [f"{k} {s[0]:.2f}-{s[1]:.2f}s" for k, s in spans if not inside(s)]
    soft = [f"{k} {s[0]:.2f}-{s[1]:.2f}s inside a full card" for k, s in spans if inside(s)]
    val = {k: [[round(x, 2) for x in s] for s in v] for k, v in bf.items()}
    msg = ("; ".join(hard + soft) + (" (card reads as a flat static screen)" if soft else "")) or "no black or frozen video"
    return _gate("black_frozen", "fail" if hard else "warn" if soft else "ok", val, "none outside designed cards", msg)


def score(gates: list[dict], director: dict | None = None) -> tuple[int, int, str]:
    """(gate score, overall score, verdict). A failing gate with no whitelisted fix blocks; any other fail or a
    high-severity director issue means fix; otherwise ship. Overall = mean of gates and director when present."""
    g = max(0, 100 - sum(PENALTY[x["level"]] for x in gates))
    ok = bool(director) and director.get("status") == "ok"
    fails = [x for x in gates if x["level"] == "fail"]
    high = ok and any(i.get("severity") == "high" for i in director.get("issues", []))
    verdict = "block" if any(x["fix"] is None for x in fails) else "fix" if fails or high else "ship"
    return g, (round((g + director["score"]) / 2) if ok else g), verdict


def run_qa(build: Path, out: Path, master: Path | None = None, director: dict | None = None) -> dict:
    """All deterministic gates for the build at `build` (read-only); writes out/qa/report.json + overlay.png,
    out/renders/before-after.png/.json."""
    from .before_after import before_after, media_at, overlay_sheet, take_sources
    build, out = Path(build), Path(out)
    b = load_build(build, master)
    ts = sample_times(b)
    frames = grab(b["master"], ts, (int(W * SCALE), int(H * SCALE)))
    det, backend = detect_faces(frames)
    faces = fill_faces(b, ts, det)
    ba = before_after(build, out, b["master"])
    raw, src = {}, take_sources(build, b["tl"])
    ti = b["layout"].get("title")
    for t in ([ti["t0"] + 0.25, (ti["t0"] + ti["t1"]) / 2, ti["t1"] - 0.25] if ti else []):
        sh, _, mt = media_at(b["tl"], t)
        if sh in src:
            raw[t] = grab(src[sh], [mt], (int(W * SCALE), int(H * SCALE)))[0]
    gates = [gate_text_over_face(b, ts, faces), gate_caption_contrast(b, ts, frames), gate_title(b, ts, frames, raw),
             head_gate(ts, frames, faces, lambda t: text_boxes(b, t),
                       lambda t: any(a <= t < e for a, e in full_cards(b) + relocated(b))),
             gate_safe(b), gate_pace(b), *gate_audio(ba["audio"]["master"]),
             gate_black_frozen(b, black_frozen(b["master"], float(b["plan"]["D"]))), *gate_broll_face(b, ts, faces),
             gate_media_share(b), gate_media_text(b)]
    g, s, verdict = score(gates, director)
    (out / "qa").mkdir(parents=True, exist_ok=True)
    if b["layout_source"] != "reel/layout.json":
        (out / "qa" / "layout.estimated.json").write_text(json.dumps(b["layout"], indent=1))
    caps = b["layout"].get("captions", [])
    n = min(8, len(caps))
    pick = [caps[round(k * (len(caps) - 1) / max(n - 1, 1))] for k in range(n)]
    k_of = [min(range(len(ts)), key=lambda j: abs(ts[j] - (c["t0"] + c["t1"]) / 2)) for c in pick]
    annos = [([(face_core(faces[j]), (255, 60, 60))] if faces[j] is not None else [])
             + [(x["box"], (255, 225, 77) if x["kind"] == "caption" else (80, 200, 255)) for x in text_boxes(b, ts[j])]
             for j in k_of]
    heads = [f"{c['chunk_id']} {ts[j]:.2f}S" for c, j in zip(pick, k_of)]
    if pick:
        write_png(out / "qa" / "overlay.png", overlay_sheet(frames[k_of], annos, heads,
                  "QA OVERLAY: RED = PADDED FACE (EYES-NOSE-MOUTH), YELLOW = CAPTION, BLUE = TITLE, GREY = SAFE"))
    rep = {"version": 1, "build": str(build), "master": str(b["master"]), "layout_source": b["layout_source"],
           "face_backend": backend, "samples": len(ts), "faces_detected": sum(f is not None for f in det),
           "gates": gates, "before_after": ba["png"], "overlay": "qa/overlay.png" if pick else None,
           "director": director, "gate_score": g, "score": s, "verdict": verdict}
    (out / "qa" / "report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reel_director.qa", description=__doc__.splitlines()[0])
    ap.add_argument("build")
    ap.add_argument("--out", help="output dir (default: the build dir)")
    ap.add_argument("--master")
    a = ap.parse_args(argv)
    r = run_qa(Path(a.build), Path(a.out or a.build), a.master)
    for x in r["gates"]:
        print(f"{x['level']:>4}  {x['id']:<17} {x['message']}")
    print(f"score {r['score']}  verdict {r['verdict']}  -> {Path(a.out or a.build) / 'qa' / 'report.json'}")
    return 0 if r["verdict"] == "ship" else 1


from .qa_media import gate_broll_face, gate_media_share, gate_media_text  # noqa: E402  (v4: B-roll + media gates)

if __name__ == "__main__":
    raise SystemExit(main())
