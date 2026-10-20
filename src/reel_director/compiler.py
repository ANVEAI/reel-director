"""Timeline -> standalone HyperFrames project (index.html + staged assets).

The HTML (every element, every caption word) is generated from the timeline; a small plan JSON
drives the static runtime (assets/rd/reel.mjs), which renders each frame as a pure function of
time. Picture and sound are separate: takes are muted <video> layers, the voice comes from the
baked mix (compile_project(..., mix=...)) or, without a mix, from per-clip <audio> at the exact
unstretched edit times. Transitions stretch picture only (the pack's txWindow/span rules).
"""
import hashlib
import html
import json
import math
import subprocess
import zlib
from functools import lru_cache
from pathlib import Path

from . import capplan
from . import layout as lyt
from . import stage, stagger, treatments
from .media import media_duration
from .timeline import Timeline

_PAGE = (stage.WEB / "page.html").read_text()

GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
LADDER = {"W": 1.0, "M": 1.17, "T": 1.32}
T_MIN_WIDTH = 1440          # a T punch needs a take this wide to stay sharp, else it is capped at M
PUNCH_MIN_CAP = 1.08        # council 3 said 1.06; founder review measured 4-6.5 % punches as camera wobble on real
                            # footage, so a punch changes the frame >= 8 % or is off (the cap stays the 1.10 guard)
BROLL_LEAD = 4              # frames an insert leads its word (council 4), never before its shot's cut
OVERLAY_HOLD, CUTAWAY_MIN = 1.4, 1.2   # s an overlay stays past its phrase; a cutaway's readable minimum
ZOOM_EASE, TITLE_DUR, ENDCARD_DUR, LOWER_MIN = 0.25, lyt.TITLE_DUR, 1.6, 2.5
CAPTION_FAMILIES = {"bold": (3, 16), "pop": (2, 14), "karaoke": (4, 22), "pill": (3, 18),
                    "boxed": (3, 16), "minimal": (4, 24)}           # max words, max chars per chunk
FONTS = {"Montserrat": 900, "Anton": 400, "Bebas Neue": 400, "Inter": 800, "Bangers": 400,
         "Instrument Serif": 400, "Noto Sans Devanagari": 800, "Archivo Black": 400}
GRADES = {"none": None, "warm": "warm-film", "cool": "cool-tech", "teal-orange": None, "mono": None}
DEFAULT_STYLE = {"font": "Montserrat", "caption": "bold", "accent": "#FFD400", "text": "#FFFFFF",
                 "bg": "#0B0B0F", "ink": "#0B0B0F", "look": {"grain": 0.15, "vignette": 0.25, "grade": "none"},
                 "background": "mesh", "progress": True}
BACKGROUNDS = {"mesh", "grid", "paper", "blur", "solid"}
BAKED = ' data-bg="baked"'      # the picture is prep's background-treated take (matte.treat_background)


def _r(x: float) -> str:
    """6 decimals: frame-grid times stay within 0.001 frame, so HyperFrames snaps them onto the frame."""
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


def js_round(x: float) -> int:
    """JS Math.round (Python's round() is banker's: round(4.5) == 4)."""
    return math.floor(x + 0.5)


def _e(s) -> str:
    return html.escape(str(s))


def _merge(base: dict, over: dict) -> None:
    for k, v in (over or {}).items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v


def resolve_style(style: dict | None) -> dict:
    """Defaults <- preset (presets.py, when present) <- the script's own overrides (look merged per key)."""
    style = dict(style or {})
    base = json.loads(json.dumps(DEFAULT_STYLE))
    if style.get("preset"):
        try:
            from . import presets
            get = getattr(presets, "get_preset", None)
            pre = get(style["preset"]) if get else getattr(presets, "PRESETS", {}).get(style["preset"])
        except (ImportError, KeyError, ValueError):
            pre = None
        _merge(base, pre or {})
    _merge(base, style)
    if base["caption"] not in CAPTION_FAMILIES:
        base["caption"] = "bold"
    if base["font"] not in FONTS:
        base["font"] = "Montserrat"
    if base["background"] not in BACKGROUNDS:
        base["background"] = "mesh"
    return base


@lru_cache(maxsize=64)
def probe_size(path: str) -> tuple[int, int]:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0, 0


def caption_chunks(words: list[dict], max_words: int, max_chars: int) -> list[list[int]]:
    """Group words into caption chunks (stagger.craft_chunks: caption craft rules). Script words that share
    one spoken (ASR) word, e.g. 'three thousand' said as '3,000', always stay together; chunks break after
    punctuation and never end on an article, preposition, conjunction or possessive."""
    return stagger.craft_chunks(words, max_words, max_chars)


class _Builder:
    BROLL_LEAD, esc, r = BROLL_LEAD, staticmethod(_e), staticmethod(_r)
    caption_chunks = staticmethod(caption_chunks)

    def __init__(self, tl: Timeline, out: Path, mix: Path | None):
        self.tl, self.out, self.s, self.mix = tl, out, tl.script, mix
        self.fps, self.D = tl.script.fps, tl.duration
        self.style = resolve_style(tl.script.style)
        self.stage_el, self.gfx, self.caps, self.audio, self.cam = [], [], [], [], []
        self.items, self.callouts, self.notes, self.card_spans = [], [], [], []
        self.names: dict[str, Path] = {}
        self.n, self.punch_off_noted = 0, False

    def uid(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}-{self.n}"

    def clamp(self, t: float) -> float:
        return max(0.0, min(t, self.D))

    def asset(self, src: Path) -> str:
        """Link a media file into assets/ under its own name, or under a hashed name when a different
        file already took that name (two different 'hit.wav' must never overwrite each other)."""
        src = Path(src).resolve()
        name = src.name
        if self.names.get(name, src) != src:
            name = f"{src.stem}-{hashlib.sha1(str(src).encode()).hexdigest()[:8]}{src.suffix}"
        self.names[name] = src
        if src.exists():
            stage.link(src, self.out / "assets" / name)
        return f"assets/{name}"

    # ---- picture: one muted layer per kept segment, stretched by transition windows -------------
    def segments(self) -> list[dict]:
        segs = []
        for si, p in enumerate(self.tl.shots):
            sid = p.shot.id
            if p.take:
                w, h = probe_size(str(p.take.src))
                crop_w = round(min(w, h * self.s.width / self.s.height)) if w and h else 0   # width of the 9:16 crop
                for k, c in enumerate(p.clips):
                    segs.append({"id": f"{sid}-{k}", "el": f"take-{sid}-{k}", "shot": si, "start": c.out_start,
                                 "end": c.out_start + c.duration, "mstart": c.media_in, "media_in": c.media_in,
                                 "left": max(0.0, p.take.duration - c.media_out), "src": p.take.src, "width": w,
                                 "crop_w": crop_w})
            else:
                segs.append({"id": f"{sid}-0", "el": f"slot-{sid}", "shot": si, "start": p.out_start,
                             "end": p.out_start + p.duration, "mstart": 0.0, "media_in": 1e9, "left": 1e9,
                             "src": None, "width": 0, "crop_w": 0})
        for k, s in enumerate(segs):        # stretched neighbours never share a track
            s["vo"], s["track"] = (s["start"], s["end"], s["mstart"]), k % 2
        return segs

    def windows(self, segs: list[dict]) -> list[dict]:
        """Port of the pack's txWindow + span(): window n frames around the cut, clamped to half of
        each neighbour and to the media each take has beyond the cut."""
        aliases, catalog = stage.transition_tables()
        out, F = [], self.fps
        for si, p in enumerate(self.tl.shots):
            cues = [c for c in p.shot.cues if c.type == "transition"]
            if si == 0 or not cues:
                continue
            c = cues[0]
            name = str(c.params.get("id", "cut"))
            r = aliases.get(name)
            if not r:
                raise ValueError(f"shot {p.shot.id!r}: unknown transition {name!r}")
            if r["kind"] in ("cut", "smash") or not r.get("key"):
                continue
            a = [s for s in segs if s["shot"] == si - 1][-1]
            b = [s for s in segs if s["shot"] == si][0]
            tm = catalog[r["key"]]["timing"]
            n = max(tm.get("minFrames") or 2, js_round(float(c.params.get("ms", tm["ms"])) / 1000 * F))
            pre0 = js_round(tm["cut"] * n)
            cut_f = js_round(b["start"] * F)
            a_frames, b_frames = js_round((a["end"] - a["start"]) * F), js_round((b["end"] - b["start"]) * F)
            pre = max(0, min(pre0, a_frames // 2, b_frames // 2, math.floor(b["media_in"] * F + 1e-6)))
            post = max(0, min(n - pre0, a_frames // 2, b_frames // 2, math.floor(a["left"] * F + 1e-6)))
            if pre + post < 2:
                self.notes.append(f"{p.shot.id}: shots too short for {name}: hard cut")
                continue
            start_f, end_f = cut_f - pre, cut_f + post
            b["mstart"] = max(0.0, b["mstart"] - (b["start"] - start_f / F))
            b["start"] = start_f / F
            a["end"] = max(a["end"], end_f / F)
            params = {**r.get("params", {}), **(c.params.get("params") or {})}
            out.append({"key": r["key"], "id": r["id"], "a": "L-" + a["id"], "b": "L-" + b["id"],
                        "startF": start_f, "cutF": cut_f, "endF": end_f, "params": params, "shot": p.shot.id})
        return out

    def camera(self, segs: list[dict]) -> list[dict]:
        """Per segment: the shot's punch ladder (instant, about the eyes) and legacy smooth zooms."""
        plan = []
        for sg in segs:
            p = self.tl.shots[sg["shot"]]
            shot_end = min(p.out_start + p.duration, self.D)
            punches, zooms = [], []
            cap = self.punch_cap(sg) / self.lay.scale(sg["shot"])   # the reframe already spent some of the cap
            for c in p.shot.cues:
                t = self.clamp(p.words[c.start_word].start)
                if c.type == "punch":
                    if c.params.get("open"):              # the shot opens at this level (shot 0: frame 0)
                        t = p.out_start
                    elif c.params.get("on") == "cut":     # lands on its clip's jump cut (hides the jump)
                        t = max([cl.out_start for cl in p.clips if cl.out_start <= t + 1e-6] or [t])
                    lvl = str(c.params.get("level", "M")).upper()
                    if lvl == "T" and sg["crop_w"] < T_MIN_WIDTH:    # unknown width counts as narrow
                        lvl = "M"
                    f = js_round(t * self.fps)
                    punches.append([f, self.punch_scale(LADDER.get(lvl, LADDER["M"]), cap, f)])
                elif c.type == "zoom":
                    end = p.words[c.end_word].end
                    t3 = min(shot_end, end + float(c.params.get("hold", 0.6)) + ZOOM_EASE)
                    ramp = min(ZOOM_EASE, max(0.0, (t3 - t) / 2))
                    if ramp > 0:
                        zooms.append([round(t, 4), round(t + ramp, 4), round(t3 - ramp, 4), round(t3, 4),
                                      float(c.params.get("scale", 1.12))])
            plan.append({"fr": "F-" + sg["id"], "punches": sorted(punches), "zooms": zooms})
        return plan

    def punch_cap(self, sg: dict) -> float:
        """Council Z3: a punch never upscales past 1.10 x cropW / 1080; under 1.06 punches are off."""
        cap = lyt.res_cap(sg["crop_w"])
        if cap < PUNCH_MIN_CAP and not self.punch_off_noted:
            self.punch_off_noted = True
            self.notes.append(f"punches off: the take is only {sg['crop_w']} px wide in the 9:16 crop (cap {cap:.2f})")
        return cap

    def punch_scale(self, lvl: float, cap: float, f: int) -> float:
        """Ladder level (capped), 0-0.01 under it by a jitter seeded from crc32(title, frame): never above the cap,
        never under PUNCH_MIN_CAP (a smaller punch reads as camera wobble), so capped punches still vary."""
        if cap < PUNCH_MIN_CAP - 1e-9 or lvl <= 1.0:
            return 1.0
        j = (zlib.crc32(f"{self.s.title}:{f}".encode()) % 1001) / 100000
        return round(max(PUNCH_MIN_CAP, min(cap, lvl) - j), 4)

    def emit_segments(self, segs: list[dict]) -> None:
        for sg in segs:
            tm = f'data-start="{_r(sg["start"])}" data-duration="{_r(sg["end"] - sg["start"])}" '
            common = f'{tm}data-track-index="{sg["track"]}"'
            if sg["src"]:
                src, ms = self.asset(sg["src"]), f'data-media-start="{_r(sg["mstart"])}"'
                matte, (pic, baked) = Path(sg["src"]).with_name(Path(sg["src"]).stem + ".matte.webm"), self.lay.picture(sg["src"])
                inner = (f'<video id="{_e(sg["el"])}" class="clip take" src="{self.asset(pic)}" muted playsinline {common} {ms} '
                         f'data-layer="background"{BAKED if baked else ""}></video>')
                if matte.exists():      # subject layer (alpha) over the background (layout.py: the VISUALS hook)
                    inner += (f'<video id="subj-{_e(sg["id"])}" class="clip take subject" src="{self.asset(matte)}" muted '
                              f'playsinline {tm}data-track-index="{10 + sg["track"]}" {ms} data-layer="subject"></video>')
                inner = f'<div class="rf" data-layer="take" style="position:absolute;inset:0{self.lay.reframe_css(sg)}">{inner}</div>'
                if not self.mix:            # no baked mix: the voice plays at the exact (unstretched) edit
                    vs, ve, vm = sg["vo"]
                    self.audio.append(f'<audio id="vo-{_e(sg["id"])}" src="{src}" data-start="{_r(vs)}" '
                                      f'data-duration="{_r(ve - vs)}" data-media-start="{_r(vm)}" '
                                      f'data-track-index="{6 + sg["track"]}" data-volume="1"></audio>')
            else:
                p = self.tl.shots[sg["shot"]]
                inner = (f'<div id="{_e(sg["el"])}" class="clip slot" {common}><div class="slot-inner">'
                         f'<div class="slot-tag">RECORD · {_e(p.shot.id)}</div>'
                         f'<div class="slot-line">{_e(p.shot.line)}</div></div></div>')
            org = f' style="transform-origin:{o[0]}px {o[1]}px"' if (o := self.lay.origin.get(sg["id"])) else ""  # P2: eyes
            self.cam.append(f'<div class="txl" id="L-{_e(sg["id"])}" data-layout-allow-overflow><div class="fr" id="F-{_e(sg["id"])}"{org}>'
                            f'{inner}</div></div>')

    # ---- captions (capplan.py: one text block at a time, chunks never straddle a title / card edge) --------
    def captions(self) -> list[dict]:
        return capplan.plan(self, *CAPTION_FAMILIES[self.style["caption"]])

    def emit_captions(self, chunks: list[dict]) -> list[dict]:
        return capplan.emit(self, chunks)

    def broll_span(self, p, c, shot_end: float) -> tuple[float, float]:
        """A B-roll card's [in, out): 4 frames before its word (snapped onto a near cut), held past its last word
        but never into the next word, so the caption after it starts a fresh chunk on the card's out frame."""
        s0 = stagger.card_in(p.out_start, self.clamp(p.words[c.start_word].start), self.fps, BROLL_LEAD)
        e = min(shot_end, max(self.clamp(p.words[c.end_word].end) + float(c.params.get("hold", 0.2)), s0 + 1.0))
        if c.end_word + 1 < len(p.words) and p.words[c.end_word + 1].start >= s0 + CUTAWAY_MIN - 1e-6:
            e = min(e, p.words[c.end_word + 1].start)     # never at the price of a card under its readable minimum
        return s0, treatments.fallback_end(self, c, s0, e)

    def cutaway_span(self, p, c, shot_end: float) -> tuple[float, float]:
        s0, e0 = self.clamp(p.words[c.start_word].start), self.clamp(p.words[c.end_word].end)
        return s0, min(shot_end, max(e0 + float(c.params.get("hold", 0.25)), s0 + CUTAWAY_MIN))

    # ---- cues ------------------------------------------------------------------------------------
    def cues(self, caps: list[dict]) -> None:
        overlays, titles, shots = [], [], self.tl.shots
        cards = sorted(self.clamp(p.words[c.start_word].start) for p in shots for c in p.shot.cues
                       if c.type in ("cutaway", "broll"))

        def until_card(s0: float, end: float) -> float:     # face graphics give way to the next full card
            return min([end] + [t for t in cards if s0 + 1e-6 < t < end])
        for si, p in enumerate(shots):
            shot_end = min(p.out_start + p.duration, self.D,   # cards end where a transition out begins
                           self.tx_in.get(si + 1, self.D))
            for c in p.shot.cues:
                s0, e0, k = self.clamp(p.words[c.start_word].start), self.clamp(p.words[c.end_word].end), c.type
                if k == "overlay":
                    overlays.append((s0, e0, c, shot_end))
                elif k == "cutaway":
                    self.card("cutaway", *self.cutaway_span(p, c, shot_end), c.params,
                              f'<div class="card-text fit">{_e(c.params["text"])}</div>')
                elif k == "broll":
                    prm = c.params
                    if prm.get("kind") == "list":           # each item builds and ticks on its spoken word
                        prm = {**prm, "at": capplan.list_ticks(p, c, list(prm.get("items", []))[:5])}
                    self.broll(*self.broll_span(p, c, shot_end), prm)
                elif k == "title":
                    s, e = lyt.title_window(self.tl, si, c, self.D)
                    titles.append((s, e))
                    body = " ".join(f'<span class="tw">{_e(w)}</span>' for w in str(c.params["text"]).split())
                    self.gfx_item("title", s, e, f'<div class="title-text fit">{body}</div>', prm=c.params)
                elif k == "lowerthird":
                    sub = f'<div class="lt-sub">{_e(c.params["sub"])}</div>' if c.params.get("sub") else ""
                    self.gfx_item("lowerthird", s0, until_card(s0, min(self.D, max(e0 + 1.5, s0 + LOWER_MIN))),
                                  f'<div class="lt-bar"></div><div class="lt-main">{_e(c.params["text"])}</div>{sub}', prm=c.params)
                elif k == "endcard":
                    s = max(s0, self.D - float(c.params.get("dur", ENDCARD_DUR)))
                    sub = f'<div class="ec-sub">{_e(c.params["sub"])}</div>' if c.params.get("sub") else ""
                    self.gfx_item("endcard", s, self.D, f'<div class="ec-card"><div class="ec-main fit">'
                                  f'{_e(c.params["text"])}</div>{sub}</div>', pre='<div class="scrim"></div>', prm=c.params)
                elif k == "callout":
                    cap = next((x for x in caps if x["shot"] == p.shot.id and x["first"] <= c.start_word <= x["last"]), None)
                    if cap:
                        self.callouts.append({"cap": cap["id"], "kind": c.params.get("kind", "underline"),
                                              "s": round(max(s0, cap["s"]), 4), "e": cap["e"]})
                    else:       # its word is spoken under a title or card: no caption to draw on (capplan)
                        self.notes.append(f"{p.shot.id}: callout on {p.shot.words[c.start_word].text!r} skipped "
                                          "(no caption under a title or card)")
                elif k == "sfx" and not self.mix:
                    self.sfx(s0, c.params)
        overlays.sort(key=lambda o: o[0])
        for j, (s0, e0, c, shot_end) in enumerate(overlays):     # an overlay ends when the next one starts
            end = min(shot_end, e0 + float(c.params.get("hold", OVERLAY_HOLD)))
            if j + 1 < len(overlays):
                end = min(end, overlays[j + 1][0])
            end = until_card(s0, end)
            if end - s0 < 2 / self.fps:
                continue
            low = " low" if any(ts < end and s0 < te for ts, te in titles) else ""
            self.gfx_item("overlay", s0, end, f'<div class="chip fit">{_e(c.params["text"])}</div>', extra=low, prm=c.params)

    def card(self, kind, s, e, params, body, layout="full", extra="") -> None:
        oid = self.uid(kind)
        bg = params.get("background") or self.style["background"]
        bg = bg if bg in BACKGROUNDS else "mesh"
        geo = self.lay.split_geom(s, e) if layout == "split" else None   # top pane height + face drop (eyes ~1250)
        media = ("fill" if " m-full" in extra else "wide" if " t-device" in extra else True) if "b-media" in extra else False
        content = self.lay.card_content(layout, geo, media)  # --x..--h: clear of its captions
        crop = self.lay.face_crop(s, e) if layout != "full" else None      # split/pip: where the face is (VISUALS)
        more = (";" + lyt.css_vars(crop, "f") if crop else "") + (f";--split-h:{geo[0]}px;--dy:{geo[1]}px" if geo else "")
        attrs = lyt.data_attrs(kind, params, content, more)
        extra += " solo" if layout == "full" and not self.style.get("card_captions") and "b-media" not in extra else ""
        self.stage_el.append(f'<div id="{oid}" class="clip card {kind} {layout}{extra}" data-start="{_r(s)}" '
                             f'data-duration="{_r(e - s)}" data-track-index="3"{attrs}><div class="bg bg-{bg}" data-layout-allow-overflow></div>'
                             f'<div id="{oid}-in" class="card-in">{body}</div></div>')
        self.card_spans.append((s, e, layout, geo))
        full = [0, 0, self.s.width, self.s.height]
        self.lay.card(oid, kind, s, e, full if layout == "full" else content, layout, crop,
                      str(params.get("text") or params.get("value") or " / ".join(params.get("items") or [])), geo)
        self.items.append({"id": oid, "kind": kind, "s": round(s, 4), "e": round(e, 4), "layout": layout, "bg": bg})

    def broll(self, s, e, prm) -> None:
        if prm.get("kind") == "media" and treatments.emit(self, s, e, prm):     # v4 real media (treatments.py)
            return
        prm = treatments.fallback(prm) if prm.get("kind") == "media" else prm  # unresolved: the card it replaced
        kind, layout = prm.get("kind", "text"), prm.get("layout", "full")
        layout = layout if layout in {"full", "split", "pip"} else "full"
        oid0 = f"broll-{self.n + 1}"          # the id card() is about to give this B-roll
        if kind == "stat":
            body = (f'<div class="stat-v fit">{_e(prm["value"])}</div>'
                    f'<div class="stat-l">{_e(prm.get("label", ""))}</div>')
        elif kind == "list":
            body = '<div class="list">' + "".join(f'<div class="li"><span class="tick"></span><span>{_e(x)}</span></div>'
                                                  for x in list(prm.get("items", []))[:5]) + "</div>"
        elif kind == "icon":
            body = (f'<div class="icon">{_e(prm.get("icon", "★"))}</div>'
                    f'<div class="card-text fit">{_e(prm.get("text", ""))}</div>')
        elif kind == "clip":
            path = self.s.base_dir / prm["src"]
            src = self.asset(path)
            dur = max(1 / self.fps, min(e - s, media_duration(path) - float(prm.get("from", 0))))
            e = s + dur
            v = (f'data-start="{_r(s)}" data-duration="{_r(dur)}" data-media-start="{_r(float(prm.get("from", 0)))}" '
                 f'data-track-index="2"')
            body = (f'<video id="{oid0}-fill" class="clip bfill" src="{src}" muted playsinline {v}></video>'
                    f'<video id="{oid0}-fit" class="clip bfit" src="{src}" muted playsinline {v}></video>')
        else:
            kind = "text"
            body = '<div class="card-text fit">' + " ".join(
                f'<span class="tw">{_e(w)}</span>' for w in str(prm.get("text", "")).split()) + "</div>"
        self.card("broll", s, e, prm, body, layout, extra=f" b-{kind}")
        self.items[-1]["bkind"] = kind
        if kind == "stat":
            self.items[-1]["value"] = str(prm["value"])

    def gfx_item(self, kind, s, e, body, pre="", extra="", prm=None) -> None:
        oid = self.uid(kind)
        box, top, more = self.lay.gfx_box(oid, kind, s, e, bool(extra), str((prm or {}).get("text", "")))  # clear of the face
        st = f' style="top:{top}px"' if top is not None else ""
        self.gfx.append(f'<div id="{oid}" class="clip {kind}{extra}" data-start="{_r(s)}" data-duration="{_r(e - s)}" '
                        f'data-track-index="4"{lyt.data_attrs(kind, {**(prm or {}), **more}, box)}>{pre}<div id="{oid}-in" '
                        f'class="g-in {kind}-inner"{st}>{body}</div></div>')
        self.items.append({"id": oid, "kind": kind, "s": round(s, 4), "e": round(e, 4)})

    def sfx(self, s0, prm) -> None:
        path = stage.resolve_sfx(prm["id"]) if prm.get("id") else self.s.base_dir / prm["src"]
        start = max(0.0, s0 - float(prm.get("lead", 0.0)))
        if start >= self.D - 1 / self.fps:
            return
        self.audio.append(f'<audio id="{self.uid("sfx")}" src="{self.asset(path)}" data-start="{_r(start)}" '
                          f'data-duration="{_r(min(media_duration(path), self.D - start))}" '
                          f'data-track-index="8" data-volume="{prm.get("volume", 0.8)}"></audio>')

    # ---- page ------------------------------------------------------------------------------------
    def build(self) -> tuple[str, dict]:
        segs = self.segments()
        wins = self.windows(segs)
        self.tx_in = {next(i for i, p in enumerate(self.tl.shots) if p.shot.id == w['shot']): w['startF'] / self.fps
                      for w in wins}
        self.lay = lyt.Layout(self.tl, segs, self.style, self.fps, self.notes)   # reframe per take (face track)
        cam = self.camera(segs)
        self.lay.set_camera(cam)                  # punch origins, face in reel px, title and caption zones
        self.emit_segments(segs)
        caps = self.captions()
        self.cues(caps)
        caps = self.emit_captions(caps)
        if self.mix:
            self.audio.append(f'<audio id="mix" src="{self.asset(self.mix)}" data-start="0" data-duration="{_r(self.D)}" '
                              f'data-track-index="9" data-volume="1"></audio>')
        elif self.s.music and self.s.music.get("src"):
            self.audio.append(f'<audio id="music" data-timeline-role="music" '
                              f'src="{self.asset(self.s.base_dir / self.s.music["src"])}" data-start="0" '
                              f'data-duration="{_r(self.D)}" data-track-index="9" '
                              f'data-volume="{self.s.music.get("volume", 0.18)}"></audio>')
        st, look = self.style, self.style.get("look") or {}
        grade = str(look.get("grade", "none"))
        plan = {"W": self.s.width, "H": self.s.height, "fps": self.fps, "D": self.D,
                "grade": grade if grade in GRADES else "none", "gradePack": GRADES.get(grade),
                "grain": float(look.get("grain", 0)), "vignette": float(look.get("vignette", 0)),
                "font": st["font"], "weight": FONTS[st["font"]], "caption": st["caption"],
                "segs": [{"layer": "L-" + s["id"], **c} for s, c in zip(segs, cam)],
                "face_reel": self.lay.face_reel(), "look": look, "preset": st.get("preset"),
                "windows": wins, "caps": caps, "items": self.items, "callouts": self.callouts,
                "progress": bool(st.get("progress", True)), "notes": self.notes}
        body = "\n".join(self.caps)
        for cap in caps:
            svgs = "".join(f'<svg class="callout co-{_e(co["kind"])}" id="co-{i}"><path pathLength="1"/></svg>'
                           for i, co in enumerate(self.callouts) if co["cap"] == cap["id"])
            body = body.replace(f"{{callouts:{cap['id']}}}", svgs)
        return _PAGE.format(
            title=_e(self.s.title), w=self.s.width, h=self.s.height, fps=self.fps, dur=_r(self.D), gsap=GSAP,
            vars=_css_vars(st), cls=f"cap-{st['caption']}", cam="\n      ".join(self.cam),
            stage="\n    ".join(self.stage_el), gfx="\n  ".join(self.gfx), caps=body,
            audio="\n  ".join(self.audio), plan=json.dumps(plan).replace("</", "<\\/")), plan


def _css_vars(st: dict) -> str:
    fam = st["font"]
    return (f"--accent: {st['accent']}; --text: {st['text']}; --bg: {st['bg']}; --ink: {st.get('ink', '#0B0B0F')}; "
            f"--font: \"{fam}\", \"Noto Sans Devanagari\", sans-serif; --weight: {FONTS[fam]};")


def compile_project(tl: Timeline, out: str | Path, mix: str | Path | None = None) -> Path:
    """Write <out>/index.html (+ assets). With `mix` (a baked mix.wav) the page carries no voice,
    SFX or music of its own; without it, voice/SFX/music are separate <audio> elements as before."""
    (out := Path(out)).mkdir(parents=True, exist_ok=True)
    stage.stage(out)
    (out / "assets" / "rd" / "broll.mjs").write_text((stage.WEB / "broll.mjs").read_text())   # media treatments
    b = _Builder(tl, out, Path(mix).resolve() if mix else None)
    page, plan = b.build()
    (out / "layout.json").write_text(json.dumps(b.lay.doc(), indent=1))     # reel px: QA and VISUALS read it
    (index := out / "index.html").write_text(page)
    (out / "timeline.json").write_text(json.dumps({**timeline_summary(tl), "notes": plan["notes"],
                                                   "credits": treatments.credits_of(b)}, indent=2))   # v4 media
    return index


def timeline_summary(tl: Timeline) -> dict:
    return {"duration": tl.duration, "shots": [
        {"id": p.shot.id, "recorded": p.take is not None, "start": p.out_start, "duration": p.duration,
         "take": p.take_index, "coverage": round(p.coverage, 3),
         "clips": [{"start": c.out_start, "media_in": c.media_in, "media_out": c.media_out} for c in p.clips],
         "candidates": [vars(sc) for sc in p.scores],
         "words": [{"w": w.text, "s": t.start, "e": t.end} for w, t in zip(p.shot.words, p.words)]}
        for p in tl.shots]}
