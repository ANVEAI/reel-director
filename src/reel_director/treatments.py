"""Media B-roll treatments, compiler side (v4 contract): a resolved media cue -> HTML + a plan item that
web/broll.mjs animates as a pure function of time (seek-safe; clips play through HyperFrames' own <video> clips).

Treatments: fullbleed (cover, grade-matched), kenburns (eased, seeded move), parallax (2.5D: the image under its
Vision cut-out subject, zoomed about the subject), sticker (cut-out with a baked white outline, pops), device
(phone / laptop / browser mockup), polaroid (photo with a fanned stack behind), reveal (circle from the face / wipe /
the media seen through a word), inset (rounded picture-in-picture beside the face). Layouts: full (the face is hidden
by design), split (media pane on top, face below), pip (face circle over the media), inset (face kept: the box is
placed clear of the padded face, the captions and the title, else the insert falls back to split).
Faces: only full-layout inserts cover the face; captions always paint above B-roll (#caps after #stage) and a media
card's content box ends above its caption band. Colour: the media gets the reel's grade (#mp-grade, at runtime) and
a gentle brightness / saturation match to the take (sqrt of the ratio of means, clamped), measured here; presets with
one loud accent (MEDIA_TINT) also pull the picture toward it (#rd-tint: luminance onto the accent, partly).
Final round (panel review of v4): a laptop / browser that would be narrower than DEVICE_MIN of the frame (always, over
a split's captions) gives way to the screen filling the pane; a clip's payoff (media_fit.payoff) lands on the line's
result word; the picture's salient run sits in view (above a split's captions, inside a device screen); a split insert
bridged to the next split card (broll_media.split_flow) holds the clip's last frame to the cut, and a beat on a word
punches the picture in so the run never reads static.
"""
import html
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import layout as lyt
from . import media_fit as mf
from . import mediaplan
from .broll_media import TREATMENTS, kenburns
from .lexicon import bare, stable

VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
FULL_FRAME = {"fullbleed", "kenburns", "parallax", "reveal"}       # the media fills the card (or the split pane)
NEEDS_IMAGE = {"parallax", "sticker", "polaroid"}
STORY = (30, 240, 930, 1500)        # x0, y0, x1, y1: clear of the platform header, action rail and caption UI
INSET_W, INSET_H, INSET_MIN = (840, 720, 640, 560, 480, 420, 360, 320, 280, 250, 230), 560, 52000
MATCH = ((0.85, 1.15), (0.80, 1.20))      # brightness, saturation clamps
FALLBACK_MAX = 1.5                         # s: = policy.TEXT_MAX (a label card ends after its phrase)
OWN = {"own", "original", "user-capture"}  # the creator's own media: nothing to credit
GENERATED = {"claude_clip": "Claude motion graphic", "veo": "Google Veo", "higgsfield": "Higgsfield"}
PHONE_MIN_W = 240                          # px: a phone mockup narrower than this reads as a thumbnail
DEVICE_MIN = 0.85                          # a laptop / browser narrower than this share of the frame: the screen fills
HOLD_MAX = 1.5                             # s: a bridged insert holds its clip's last frame at most this long
HEADER_SOFT = 120                          # px: a split pane's top under the platform header (content sits lower)
MEDIA_TINT = {"bold-hustle": 0.45}         # preset -> strength of the accent tint on real media (one-accent looks)


def _e(s) -> str:
    return html.escape(str(s))


@lru_cache(maxsize=256)
def duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


@lru_cache(maxsize=256)
def stats(path: str, t: float = 0.0) -> tuple[float, float] | None:
    """(mean luma, mean saturation) 0..1 of one frame (64 px wide), for the colour match."""
    try:
        seek = ["-ss", f"{t:.3f}"] if t > 0 else []          # a still has no time to seek to (ffmpeg: no frame)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *seek, "-i", path, "-frames:v",
                              "1", "-vf", "scale=64:64,format=rgb24", "-f", "rawvideo", "pipe:1"],
                             capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if len(raw) != 64 * 64 * 3:
        return None
    a = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(float) / 255
    return float((a @ [0.2126, 0.7152, 0.0722]).mean()), float((a.max(1) - a.min(1)).mean())


def match(media: tuple | None, take: tuple | None) -> dict:
    """{brightness, saturate}: half-way (sqrt) to the take's means, clamped; identity when either is unknown."""
    if not media or not take or media[0] < 0.02 or media[1] < 0.02:
        return {"brightness": 1.0, "saturate": 1.0}
    (b0, b1), (s0, s1) = MATCH
    return {"brightness": round(min(b1, max(b0, (take[0] / media[0]) ** 0.5)), 3),
            "saturate": round(min(s1, max(s0, (take[1] / max(media[1], 1e-3)) ** 0.5)), 3)}


def _doc(b) -> dict:
    if not hasattr(b, "_media_doc"):
        b._media_doc = mediaplan.load(mediaplan.media_path(b.out))
        b._media_src = {}
    return b._media_doc


def source(b, prm: dict) -> dict | None:
    """The media a cue renders: its own `src` (a local file, e.g. the creator's library) or its media.json pick."""
    doc, slot = _doc(b), str(prm.get("slot") or "")
    key = slot or f'{prm.get("src")}|{prm.get("treatment")}'     # a manual cue: its file and look
    if key in b._media_src:
        return b._media_src[key]
    if prm.get("src"):
        p = (b.s.base_dir / str(prm["src"])).resolve()
        info = {"path": str(p), "provider": "library", "license": prm.get("license", "own"), "id": p.name} \
            if p.is_file() else None
        for k in ("cutout", "sticker", "origin", "segment", "attribution"):
            if info and prm.get(k) is not None:
                info[k] = str((b.s.base_dir / prm[k]).resolve()) if k in ("cutout", "sticker") else prm[k]
    else:
        info = mediaplan.chosen(doc, slot)
    if info and not prm.get("src") and not _sa_ok(b, info):
        b.notes.append(f"media {key}: {info.get('license')} is share-alike (the whole reel would inherit it): opt in "
                       "with style.media.allow_share_alike or RD_MEDIA_SHARE_ALIKE=1; the label card shows")
        info = None
    if info:
        info = dict(info)
        info["video"] = Path(info["path"]).suffix.lower() in VIDEO_EXT
        info["treatment"] = prm.get("treatment") if prm.get("src") else info.get("treatment") or prm.get("treatment")
        if info["treatment"] in ("parallax", "sticker") and not info["video"] and not info.get("cutout"):
            try:
                from . import cutout
                info.update(cutout.make(Path(info["path"]), mediaplan.media_path(b.out).parent / "media" /
                                        (slot or Path(info["path"]).stem)))
            except Exception as e:      # parallax falls back to a soft focus layer, the sticker to a photo card
                b.notes.append(f"media {key}: no cutout ({type(e).__name__}: {e})")
    b._media_src[key] = info
    return info


def _sa_ok(b, info: dict) -> bool:
    """CC BY-SA renders only on the creator's opt-in (founder: share-alike would reach the whole reel)."""
    from .media import license as L
    cfg = (getattr(b, "style", None) or {}).get("media")
    return not L.info(str(info.get("license") or "")).share_alike or L.share_alike_ok(cfg if isinstance(cfg, dict) else None)


def shows_captions(b, prm: dict) -> bool:
    """Captions stay on over real media (it carries no text of its own); a text-card fallback hides them."""
    k = prm.get("kind")
    return k == "clip" or (k == "media" and source(b, prm) is not None)


def fallback_end(b, c, s0: float, e: float) -> float:
    """The card's out as the captions plan it: an unresolved media cue shows its label card (ends FALLBACK_MAX after
    its in, policy.TEXT_MAX); a clip ends with the clip unless it is bridged (timing)."""
    if c.params.get("kind") != "media":
        return e
    src = source(b, c.params)
    if src is None:
        return min(e, s0 + FALLBACK_MAX)
    p = next((p for p in b.tl.shots if p.out_start - 1e-6 <= s0 < p.out_start + p.duration), None)
    words = [(p.shot.words[k].text, b.clamp(p.words[k].start)) for k in range(c.start_word, len(p.words))] if p else None
    return timing(b, s0, e, src, c.params, words)["e"]


def _placement(b, s: float):
    return next((p for p in b.tl.shots if p.out_start - 1e-6 <= s < p.out_start + p.duration), None)


def timing(b, s: float, e: float, src: dict, prm: dict, words=None) -> dict:
    """{seg0, e, hold, beat} of a media insert at [s, e): a clip's payoff lands on the line's hit word (media_fit),
    the insert ends with the clip unless it is bridged (then the last frame holds, <= HOLD_MAX), a bridged run's beat
    word -> its time. Cached per (slot, in) so the captions' plan and the emitted card agree."""
    cache = b.__dict__.setdefault("_media_tm", {})
    key = (str(prm.get("slot") or src.get("path")), round(s, 4))
    if key in cache:
        return cache[key]
    p = _placement(b, s)
    if words is None and p:
        words = [(p.shot.words[k].text, b.clamp(w.start)) for k, w in enumerate(p.words) if w.start >= s - 0.2]
    beat = None
    if prm.get("beat") is not None and p and 0 <= int(prm["beat"]) < len(p.words):
        beat = b.clamp(p.words[int(prm["beat"])].start)
    out = {"seg0": None, "e": e, "hold": None, "beat": beat if beat is not None and s + 0.3 < beat < e - 0.3 else None,
           "peak": None, "hit": None}
    if src.get("video"):
        seg, dur = src.get("segment") or [0.0, None], duration(src["path"])
        seg0, end = float(seg[0] or 0.0), float(seg[1]) if seg[1] else dur
        peak = mf.payoff(src["path"], dur)
        hit = mf.hit(words or [], s, e) if peak is not None else None
        if hit is not None:
            seg0, end = mf.align(peak, hit, s, dur), dur
            out.update(peak=peak, hit=round(hit, 4))
        left = end - seg0
        if 0 < left < e - s - 1e-6:
            if prm.get("bridge") and e - s - left <= HOLD_MAX + 1e-6:
                out["hold"] = round(left, 4)
            else:
                out["e"] = s + max(1.0 / b.fps, left)
        out["seg0"] = round(seg0, 3)
    cache[key] = out
    return out


def fallback(prm: dict) -> dict:
    """An unresolved media cue shows the card it replaced: its label (+ glyph), full or split."""
    out = {"kind": "text", "text": prm.get("text") or str(prm.get("query", "")).split(" ")[0],
           "layout": "full" if prm.get("layout") in ("inset", None) else prm["layout"]}
    return {**out, **({"icon": prm["icon"]} if prm.get("icon") else {}),
            **({"background": prm["background"]} if prm.get("background") else {})}


def _take_stats(b) -> tuple | None:
    p = next((p for p in b.tl.shots if p.take and p.clips), None)
    return stats(str(p.take.src), round(float(p.clips[0].media_in) + 0.5, 3)) if p else None


def _media_el(b, oid: str, src: dict, s: float, e: float, cls: str = "m-src", path: str | None = None,
              track: int = 2) -> str:
    url = b.asset(Path(path or src["path"]))
    if src["video"] and not path:
        tm = (getattr(b, "_media_tm", {}) or {}).get(src.get("_tm")) or {}
        seg0 = tm.get("seg0") if tm.get("seg0") is not None else float((src.get("segment") or [0.0])[0] or 0.0)
        if tm.get("hold") and (hv := mf.held(src["path"], seg0, tm["hold"], e - s - tm["hold"] + 0.1,
                                             mediaplan.media_path(b.out).parent / "media" / f"{Path(src['path']).stem[:16]}"
                                             f"-{seg0:.3f}-{tm['hold']:.3f}-{e - s:.3f}.mp4")):
            url, seg0 = b.asset(hv), 0.0              # the clip with its last frame held to the cut
        return (f'<video id="{oid}" class="clip {cls}" src="{url}" muted playsinline data-start="{b.r(s)}" '
                f'data-duration="{b.r(e - s)}" data-media-start="{b.r(seg0)}" data-track-index="{track}"></video>')
    return f'<img id="{oid}" class="{cls}" src="{url}" alt="" draggable="false">'


def _word(prm: dict) -> str:
    """The reveal's word: the label's longest word (<= 9 letters), upper case."""
    ws = [bare(w) for w in str(prm.get("text") or prm.get("query") or "").split() if bare(w)]
    w = max(ws, key=len, default="NOW")
    return w[:9].upper()


def _body(b, oid: str, treat: str, src: dict, s: float, e: float, prm: dict) -> str:
    m = lambda cls="m-src", path=None, track=2: _media_el(b, f"{oid}-{cls.split()[-1]}", src, s, e, cls, path, track)  # noqa: E731
    if treat == "parallax":
        fg = m("m-src m-fg", src["cutout"]) if src.get("cutout") else m("m-src m-fg soft", src["path"])
        return f'<div class="m-layer">{m("m-src m-bg")}{fg}</div>'
    if treat == "reveal":
        w = _word(prm)
        kn = min(300, round(1700 / max(1, len(w))))
        ky = "" if prm.get("layout") == "split" else \
            f";--ky:{bright_band(src['path'], float((src.get('segment') or [0.0])[0] or 0.0) + 0.5 * src['video'], kn)}px"
        knock = "".join(f'<div class="m-knock{x}" style="--kn:{kn}px{ky}"><span>{_e(w)}</span></div>'
                        for x in ("", " line")) if prm.get("mask") == "text" else ""
        return f'<div class="m-layer m-reveal">{m()}</div>{knock}'
    if treat in FULL_FRAME:
        return f'<div class="m-layer">{m()}</div>'
    if treat == "sticker":
        return (f'<div class="m-stk"><div class="m-stk-in">{m("m-src m-cut", src["sticker"])}</div></div>'
                if src.get("sticker") else f'<div class="m-stk photo"><div class="m-stk-in">{m()}</div></div>')
    if treat == "device":
        dev = prm.get("device") if prm.get("device") in ("phone", "laptop", "browser") else "laptop"
        bar = (f'<div class="m-bar"><i></i><i></i><i></i><span>{_e(src.get("source_host") or "reel.director")}</span></div>'
               if dev == "browser" else "")
        notch = '<i class="m-island"></i>' if dev == "phone" else ""
        base = '<div class="m-base"></div>' if dev == "laptop" else ""
        return (f'<div class="m-dev {dev}"><div class="m-lid">{bar}<div class="m-scr">{m()}</div>{notch}</div>'
                f'{base}</div>')
    if treat == "polaroid":
        cap = "" if prm.get("layout") == "split" else _e(str(prm.get("text") or "").capitalize()[:28])  # split: the
        # captions sit over the photo's foot; one text at a time
        return (f'<div class="m-pola"><i class="m-back b1"></i><i class="m-back b2"></i><figure class="m-front">'
                f'<div class="m-ph">{m()}<i class="m-wash"></i></div><figcaption>{cap}</figcaption></figure></div>')
    return f'<div class="m-inset-in">{m()}</div>'


@lru_cache(maxsize=64)
def bright_band(path: str, t: float, band: int, lo: int = 240, hi: int = 900) -> int:
    """Top y (reel px) of the brightest band-tall strip of the picture as it covers the 1080x1920 frame, inside
    [lo, hi] (above the caption band): where a word cut out of a dark overlay reads. 380 when unknown."""
    w, h = 135, 240                      # 1/8 of the reel
    seek = ["-ss", f"{t:.3f}"] if t > 0 else []
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *seek, "-i", path, "-frames:v", "1", "-vf",
                              f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=gray",
                              "-f", "rawvideo", "pipe:1"], capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return 380
    if len(raw) != w * h:
        return 380
    rows, k = np.frombuffer(raw, np.uint8).reshape(h, w).mean(axis=1), max(1, round(0.9 * band / 8))
    best = max(range(lo // 8, max(lo // 8, (hi - band) // 8) + 1), key=lambda y: (round(float(rows[y:y + k].mean()), 1),
                                                                                -abs(8 * y - 380)))
    return 8 * best


@lru_cache(maxsize=256)
def dims(path: str) -> tuple[int, int]:
    """(width, height) of an image or clip; (0, 0) when unknown."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip().split(",")
    try:
        return int(out[0]), int(out[1])
    except (ValueError, IndexError):
        return 0, 0


def aspect(path: str) -> float:
    """Width / height of an image or clip (1.0 when unknown)."""
    w, h = dims(path)
    return max(0.3, min(3.0, w / h)) if w and h else 1.0


def _inset_box(b, s: float, e: float, ar: float):
    """The largest box of the media's aspect (clamped 0.56-1.78, >= INSET_MIN px2) inside the story area, >= GAP px
    clear of the padded face over [s, e], the captions, titles and stickers on screen; highest first, centred before
    the sides. None when nothing fits (the insert goes split: a thumbnail-sized picture reads as a mistake)."""
    lay, g = b.lay, lyt.GAP
    face = lay._face(s, e, 4)           # the head up to the hair top (HAIR x face h): nothing sits on the hair
    others = [tt["box"] for tt in lay.titles if tt["t0"] < e and s < tt["t1"]]
    others += [z["box"] for si, z in lay.zones.items()
               if b.tl.shots[si].out_start < e and s < b.tl.shots[si].out_start + b.tl.shots[si].duration]
    others += [lyt._box(*c["box"]) for c in lay.cards if c["layout"] == "sticker" and c["t0"] < e and s < c["t1"]]
    others = [[o[0] - g, o[1] - g, o[2] + g, o[3] + g] for o in others + ([face] if face else [])]
    x0, y0, x1, y1 = STORY
    ar = max(0.56, min(1.78, ar))
    for w in INSET_W:
        h = min(INSET_H, round(w / ar))
        if w * h < INSET_MIN:
            break
        for y in range(y0, y1 - h + 1, 12):
            for x in dict.fromkeys(((x0 + x1 - w) // 2, x0, x1 - w)):
                box = lyt._box(x, y, w, h)
                if all(lyt._hit(box, o) == 0 for o in others):
                    return box
    return None


def _plan_item(treat: str, src: dict, prm: dict, mt: dict, fit: dict | None = None) -> dict:
    kb = prm.get("kb") if isinstance(prm.get("kb"), list) and len(prm["kb"]) == 6 else \
        kenburns(stable(prm.get("slot") or src.get("path")))
    if src["video"] and treat in ("fullbleed", "inset", "device", "reveal"):
        kb = [1.0, 1.04, 0, 0, 0, 0]        # real motion carries the shot: only a slow push
    return {"t": treat, "video": src["video"], "kb": [float(x) for x in kb], "mask": prm.get("mask", "circle"),
            "origin": src.get("origin") or [50, 50], "match": mt, "device": prm.get("device"),
            "cut": bool(src.get("cutout") or src.get("sticker")), **(fit or {})}


def device_width(dev: str, w: float, h: float) -> float:
    """The mockup's width in a w x h content box (reel.css: laptop lid 16:10.4 + 28 px base, browser 4:3.3, phone
    9:19.5)."""
    return min(w, (h - 28) * 16 / 10.4 if dev == "laptop" else h * 4 / 3.3 if dev == "browser" else h * 9 / 19.5)


def _screen(dev: str, w: float, h: float) -> tuple[float, float]:
    """The device screen's size in a w x h content box (the reel.css paddings)."""
    dw = device_width(dev, w, h)
    if dev == "laptop":
        return dw - 36, dw * 10.4 / 16 - 44
    if dev == "browser":
        return dw, dw * 3.3 / 4 - 66
    return dw - 32, min(h, dw * 19.5 / 9) - 32


def _cover(path: str, w: float, h: float, band: tuple[float, float] | None = None, soft: float = 0.0):
    """(object-position, (x, y) px of the media's top-left, scale) of a cover-fitted picture in a w x h box that
    keeps its salient content whole and in view (inside `band` vertically); None when the media size is unknown."""
    mw, mh = dims(path)
    if not mw or not mh or w <= 0 or h <= 0:
        return None
    k = max(w / mw, h / mh)
    px, py = mf.offset(mf.cols(path), mw * k, w), mf.offset(mf.rows(path), mh * k, h, band, soft)
    return f"{px:g}% {py:g}%", ((w - mw * k) * px / 100, (h - mh * k) * py / 100), k


def _fit(b, treat: str, layout: str, src: dict, s: float, e: float, prm: dict, tm: dict) -> dict:
    """Plan-item extras for broll.mjs: pos (object-position), org (transform origin), hold / beat (s after the in),
    tint. A split pane's picture keeps its salient run above the captions; a device screen keeps it on screen."""
    out = {}
    if layout == "split" and treat in FULL_FRAME and treat != "reveal":
        geo = b.lay.split_geom(s, e)
        band = (0.0, float(b.lay.card_caption("split", geo)[1] - lyt.GAP))
        if cv := _cover(src["path"], b.s.width, geo[0], band, HEADER_SOFT):
            (ox, oy), k = cv[1], cv[2]
            mw, mh = dims(src["path"])
            xy = mf.payoff_xy(src["path"], duration(src["path"]), tm["peak"]) if tm.get("peak") is not None else None
            cx, cy = (ox + xy[0] * mw * k, oy + xy[1] * mh * k) if xy else (b.s.width / 2, sum(band) / 2)
            out.update(pos=cv[0], org=f"{round(min(max(cx, 0), b.s.width))}px {round(min(max(cy, band[0]), band[1]))}px")
    elif treat == "device":
        geo = b.lay.split_geom(s, e) if layout == "split" else None
        x0, y0, x1, y1 = b.lay.card_content(layout, geo, "wide")
        dev = prm.get("device") if prm.get("device") in ("phone", "laptop", "browser") else "laptop"
        if cv := _cover(src["path"], *_screen(dev, x1 - x0, y1 - y0)):
            out["pos"] = cv[0]
    if tm.get("hold"):
        out["hold"] = tm["hold"]
    if tm.get("beat") is not None:
        out["beat"] = round(tm["beat"] - s, 4)
    if MEDIA_TINT.get((b.style or {}).get("preset")):
        out["tint"] = True
        if not getattr(b, "_tint", False):
            b._tint = True
            b.stage_el.append(_tint_svg(str(b.style.get("accent") or "#FFD400"), MEDIA_TINT[b.style["preset"]]))
    return out


def _tint_svg(accent: str, k: float) -> str:
    """#rd-tint: (1 - k) x the picture + k x its luminance carried onto the accent (blacks stay black)."""
    a = [int(accent.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)] if len(accent.lstrip("#")) == 6 else [1, .83, 0]
    g = 1 / max(0.3, 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2])
    lum = (0.2126, 0.7152, 0.0722)
    rows = [" ".join(f"{(1 - k) * (i == j) + k * a[i] * g * lum[j]:.4f}" for j in range(3)) + " 0 0" for i in range(3)]
    return ('<svg class="rd-defs" width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="rd-tint" '
            f'color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="{" ".join(rows)} 0 0 0 1 0"/>'
            '</filter></svg>')


def emit(b, s: float, e: float, prm: dict) -> bool:
    """Emit one media insert (card or inset). False when the cue has no media (the caller shows its fallback)."""
    src = source(b, prm)
    if not src:
        return False
    treat = src.get("treatment") if src.get("treatment") in TREATMENTS else "kenburns"
    if src["video"] and treat in NEEDS_IMAGE:
        treat = "fullbleed" if treat == "parallax" else "inset" if treat == "sticker" else "device"
    layout = prm.get("layout") if prm.get("layout") in ("full", "split", "pip", "inset") else "full"
    if treat in ("inset", "sticker") and layout != "inset":
        layout = "inset" if treat == "inset" else layout
    if treat == "device" and layout in ("split", "full"):
        dev = prm.get("device") if prm.get("device") in ("phone", "laptop", "browser") else "laptop"
        x0, y0, x1, y1 = b.lay.card_content(layout, b.lay.split_geom(s, e) if layout == "split" else None, "wide")
        dw = device_width(dev, x1 - x0, y1 - y0)
        if dw < (PHONE_MIN_W if dev == "phone" else DEVICE_MIN * b.s.width):
            b.notes.append(f"broll-{b.n + 1}: a {dev} {'above the split captions ' if layout == 'split' else ''}would be "
                           f"{dw / b.s.width:.0%} of the frame wide (thumbnail-sized): the screen fills the "
                           f"{'pane' if layout == 'split' else 'card'} instead")
            treat = "fullbleed" if src["video"] else "kenburns"
    tm = timing(b, s, e, src, prm)
    e, src = tm["e"], {**src, "_tm": (str(prm.get("slot") or src.get("path")), round(s, 4))}
    mt = match(stats(src["path"], 0.5 if src["video"] else 0.0), _take_stats(b))
    oid = f"broll-{b.n + 1}"
    if layout == "inset":
        box = _inset_box(b, s, e, src.get("aspect") if treat == "sticker" and src.get("sticker") else aspect(src["path"]))
        if box is None:
            b.notes.append(f"{oid}: no room beside the face for the inset at {s:.2f}s: split instead")
            layout, treat = "split", ("kenburns" if treat in ("inset", "sticker") and not src["video"] else
                                      "fullbleed" if treat in ("inset", "sticker") else treat)
        else:
            oid = b.uid("broll")
            body = _body(b, oid, treat, src, s, e, prm)
            attrs = lyt.data_attrs("broll", {**prm, "treatment": treat}, box)
            b.stage_el.append(f'<div id="{oid}" class="clip minset t-{treat}" data-start="{b.r(s)}" '
                              f'data-duration="{b.r(e - s)}" data-track-index="3"{attrs}><div id="{oid}-in" '
                              f'class="mi-box">{body}</div></div>')
            b.lay.card(oid, "broll", s, e, box, "sticker", text=str(prm.get("query", "")))
            b.items.append({"id": oid, "kind": "broll", "s": round(s, 4), "e": round(e, 4), "layout": "inset",
                            "bkind": "media", "media": _plan_item(treat, src, prm, mt, _fit(b, treat, layout, src,
                                                                                            s, e, prm, tm))})
            b.lay.cards[-1].update(media=treat, obj=list(lyt.xywh(box)))
            return True
    body = _body(b, oid, treat, src, s, e, prm)
    full = " m-full" if treat in FULL_FRAME else ""
    b.card("broll", s, e, {**prm, "treatment": treat}, body, layout, extra=f" b-media t-{treat}{full}")
    b.items[-1].update(bkind="media", media=_plan_item(treat, src, prm, mt, _fit(b, treat, layout, src, s, e, prm, tm)))
    obj = None if treat in FULL_FRAME else b.lay.card_content(
        layout, b.lay.split_geom(s, e) if layout == "split" else None, "wide" if treat == "device" else True)
    b.lay.cards[-1].update(media=treat, obj=list(lyt.xywh(obj)) if obj else None)   # QA media_text: the object's box
    return True


def credits_of(b) -> list[str]:
    """Credits of the media this build shows (media.json picks + the creator's own files). A generated insert gets a
    disclosure line (no licence to credit, but the platforms' AI labels need to know which inserts are generated)."""
    out = []
    for key, src in sorted((getattr(b, "_media_src", {}) or {}).items()):
        if src and src.get("provider") in GENERATED:
            how = ("reused from the Reel Director clip gallery" if (src.get("extra") or {}).get("reused")
                   else "made for this reel")
            out.append(f"{src.get('title') or Path(src['path']).name}: AI-generated insert "
                       f"({GENERATED[src['provider']]}), {how}")
        elif src and (src.get("attribution") or str(src.get("license", "")).lower() not in OWN):
            line = src.get("attribution") or f"{src.get('title') or Path(src['path']).name}, " \
                f"{src.get('license', 'license unknown')} ({src.get('provider', '?')})"
            out.append(line if src.get("video") else line.replace("(cropped, trimmed, graded)", "(cropped, graded)"))
    return list(dict.fromkeys(out))
