"""Face-aware layout (v2 contract P1/P2): where captions, the hook title and stickers go, how each take is reframed
and which point punches scale around, from the face track (<take>.face.json or qa/<take>.face.json) mapped into reel
px through the clip trims, the cover fit, the reframe and the punches.

- Faces are sacred: no caption/title/sticker box overlaps the padded face (eyes+nose+mouth, pad 6 % of face h) at
  any frame; full-screen cards hide the face by design.
- Caption zone per shot, stable within it: below-chin (bottom <= 1248), else above-head (clear of the hair), else
  the lower band. No caption shows under a title or a card (capplan.py), so a title never pushes one onto the hair.
- Reframe: eye line toward 0.40 H +- 0.03 inside the resolution cap, never an edge, headroom >= 4 % H. A punching
  shot leaves its punches the whole cap (PUNCH_HEADROOM), and every shot shares one reframe scale, so a cut never
  jumps in scale or sideways (founder review: -9 % and 61 px at 3.14 s read as a mistake).
- Punches scale about the reframed eye midpoint (.fr transform-origin); .rf carries the reframe (origin 0 0).
- Title: data-params "busy" (0..1 behind the title box) picks the calm / glass / solid backing (P5).
VISUALS hook: cue elements carry data-kind, data-params and --x --y --w --h (a card's content box); split/pip cards
also --fx --fy --fw --fh (the face before relocation) and a split --split-h / --dy (top pane, face drop). Takes
sit in .rf (data-layer="take"): video.take (background), optional video.subject (alpha matte) or the prep-baked
<take>.bg.mp4 (data-bg="baked"). The plan carries face_reel. QA / director overrides: shot.caption_zone,
shot.reframe {eye_y, scale}, style.title_backdrop. Pure functions of the timeline, the face JSON and the style.
"""
import math
import statistics
from pathlib import Path

SAFE = (120, 288, 888, 1248)              # council 6 safe rect: x0, y0, x1, y1
CAP_X, CAP_W = 172, 696                   # council 6: centre x 520, width <= 696
BAND = (972, 276)                         # council 6 lower band: top, height (bottom 1248)
CAP_H = {"bold": 176, "pop": 182, "karaoke": 176, "pill": 192, "boxed": 214, "minimal": 150}  # 2 lines + plate
TITLE = (120, 300, 768, 260)              # .title-inner (council 6: y 300-560)
GFX = {"overlay": (70, 300, 860, 220), "lowerthird": (70, 930, 760, 160)}
EYE, EYE_TOL, HEADROOM = 0.40, 0.03, 0.04
PUNCH_HEADROOM = 1.10                     # a punching shot keeps the whole 1.10 cap for its punches (>= 8 %, founder)
PAD, CHIN_PAD, HAIR = 0.06, 0.10, 0.5     # x face h: rule pad; below-chin gap (beards); hair above the box
GAP = 24                                  # px between stacked boxes
CONTENT = {"full": (90, 300, 810), "split": (90, 250, 810), "pip": (90, 660, 810)}   # card content x, top, w
FULL_BOTTOM = 1420                        # a full card's content ends here when no caption sits over it (centre ~870)
MEDIA_TOP = 230                           # a real-media split pane's content top (captions paint over the media)
WIDE = (54, 972)                          # a device mockup's content x, w (>= 85 % of the frame: readable on a phone)
SPLIT_H, SPLIT_MIN, SPLIT_EYE, SPLIT_HAIR = 1056, 720, 1250, 56   # top pane max / min px; eye line in the face
# pane (CD: eyes ~1250, mouth above the platform caption UI at y 1500); px of wall kept above the hair at the seam
from .layout_geo import (DUR_SLACK, TITLE_DUR, TITLE_SNAP, _box, _feat, _head, _hit, _map, _union,  # noqa: F401
                         busyness, css_vars, data_attrs, load_face, res_cap, title_window, xywh)


class Layout:
    def __init__(self, tl, segs: list[dict], style: dict, fps: int, notes: list):
        s = tl.script
        self.tl, self.segs, self.fps, self.notes = tl, segs, fps, notes
        self.W, self.H = s.width, s.height
        self.style, self.family = style, style.get("caption", "bold")
        self.cap_h = CAP_H.get(self.family, 176)
        self.band = _box(CAP_X, BAND[0], CAP_W, BAND[1])
        self.face, self.rf, self.base, self.origin, self.kf, self.eye, self.smax = {}, {}, {}, {}, {}, {}, {}
        keep, self.notes = self.notes, []
        for si, p in enumerate(tl.shots):
            self._reframe(si, p)
        common = min([self.smax[si] for si in self.smax] + [max([self.rf[si][0] for si in self.smax] or [1.0])])
        first, self.notes = {si: (self.rf[si], self.eye.get(si)) for si in self.smax}, keep
        for si, p in enumerate(tl.shots):        # one reframe scale for every shot: no zoom / sideways jump at a cut
            self._reframe(si, p, common, first.get(si))
        self.titles, self.zones, self.samples, self.cards, self.caps = [], {}, [], [], []
        self.title_free = True        # capplan: no caption is ever on screen with a title (one text block)

    def picture(self, src) -> tuple[Path, bool]:
        """(the take's picture, baked): prepped <stem>.bg.mp4 when the look treats the background and prep baked it."""
        bg = Path(src).with_name(Path(src).stem + ".bg.mp4")
        return (bg, True) if (self.style.get("look") or {}).get("bgfx") and bg.exists() else (Path(src), False)

    # ---- reframe ---------------------------------------------------------------------------------
    def _frames(self, si: int, m0: float, m1: float) -> list[tuple[float, dict]]:
        d = self.face.get(si)
        if not d:
            return []
        dt = d.get("step", 1) / d.get("fps", 30)
        return [(i * dt, fr) for i, fr in enumerate(d["frames"]) if fr and m0 - dt - 1e-6 <= i * dt <= m1 + dt + 1e-6]

    def _reframe(self, si: int, p, common: float | None = None, prev=None) -> None:
        self.rf[si] = (1.0, 0.0, 0.0)
        if not p.take:
            return
        d, why = load_face(p.take.src, getattr(p.take, "duration", None))
        if d and (d.get("summary") or {}).get("present", 1.0) < 0.5:
            d, why = None, "face found in under half the frames"
        if not d:
            self.notes.append(f"layout: {p.shot.id}: {why}: v1 caption band, no reframe")
            return
        self.face[si] = d
        w, h, W, H = d["w"], d["h"], self.W, self.H
        c = max(W / w, H / h)
        ox, oy = (W - w * c) / 2, (H - h * c) * 0.38                  # object-fit: cover; object-position 50% 38%
        self.base[si] = (c, ox, oy)
        frs = [fr for c0 in p.clips for _, fr in self._frames(si, c0.media_in, c0.media_out)]
        if not frs:
            return
        eye = oy + c * statistics.median((f["eyes"][0][1] + f["eyes"][1][1]) / 2 for f in frs)
        cx = ox + c * statistics.median(f["box"][0] + f["box"][2] / 2 for f in frs)
        top = oy + c * statistics.median(f["box"][1] - HAIR * f["box"][3] for f in frs)
        crop_w = round(min(w, h * W / H))
        cap = res_cap(crop_w)
        punchy = any(cu.type == "zoom" or cu.type == "punch" and str(cu.params.get("level", "M")).upper() != "W"
                     for cu in p.shot.cues)
        smax = max(1.0, cap / PUNCH_HEADROOM if punchy else cap)
        ov = p.shot.meta.get("reframe") if isinstance(p.shot.meta.get("reframe"), dict) else {}
        target = min(0.43, max(0.37, float(ov.get("eye_y", EYE))))           # a QA/director override (0.37-0.43)
        smax = self.smax[si] = max(1.0, min(smax, float(ov.get("scale", smax))))
        smax = smax if common is None else min(smax, common)
        lo, hi = (target - EYE_TOL) * H, (target + EYE_TOL) * H
        need = (H - hi) / (oy + h * c - eye) if eye > hi else lo / (eye - oy) if eye < lo else 1.0
        sc = math.floor((min(smax, max(1.0, need)) if common is None else smax) * 1e4) / 1e4
        ty_lo, ty_hi = H - sc * (oy + h * c), -sc * oy
        ty = min(ty_hi, max(ty_lo, target * H - sc * eye, HEADROOM * H - sc * top))
        tx_lo, tx_hi = W - sc * (ox + w * c), -sc * ox
        tx = min(tx_hi, max(tx_lo, W / 2 - sc * cx))
        self.rf[si] = (sc, round(tx, 2) + 0.0, round(ty, 2) + 0.0)
        after = (sc * eye + ty) / H
        self.eye[si] = {"eye_y_before": round(eye / H, 4), "eye_y_after": round(after, 4), "cap": round(cap, 4)}
        if prev and prev[1] and abs(after - target) > EYE_TOL + 1e-6 >= abs(prev[1]["eye_y_after"] - target):
            self.rf[si], self.eye[si] = prev      # the shared scale would miss an eye line this shot reaches alone
            return
        if abs(after - target) > EYE_TOL + 1e-6:
            self.notes.append(f"layout: {p.shot.id}: eye line {eye / H:.3f} H -> {after:.3f} H (0.40 needs scale "
                              f"{need:.2f}, cap {smax:.3f}): " + ("lower the camera or tilt it down" if after > target
                                                                  else "raise the camera or tilt it up"))

    def scale(self, si: int) -> float:
        return self.rf[si][0]

    def reframe_css(self, sg: dict) -> str:
        s, tx, ty = self.rf[sg["shot"]]
        return "" if (s, tx, ty) == (1.0, 0.0, 0.0) else f";transform-origin:0 0;transform:translate({tx}px,{ty}px) scale({s})"

    def affine(self, si: int) -> tuple[float, tuple[float, float]]:
        """Take px -> reel px before punches: cover fit, then the reframe."""
        c, ox, oy = self.base.get(si, (1.0, 0.0, 0.0))
        s, tx, ty = self.rf[si]
        return c * s, (s * ox + tx, s * oy + ty)

    # ---- camera: punch origin and keyframes ------------------------------------------------------
    def set_camera(self, cam: list[dict]) -> None:
        for sg, c in zip(self.segs, cam):
            self.kf[sg["id"]] = c
            frs = self._frames(sg["shot"], sg["mstart"], sg["mstart"] + sg["end"] - sg["start"])
            if not frs:
                continue
            A, B = self.affine(sg["shot"])
            mx = statistics.median((f["eyes"][0][0] + f["eyes"][1][0]) / 2 for _, f in frs)
            my = statistics.median((f["eyes"][0][1] + f["eyes"][1][1]) / 2 for _, f in frs)
            self.origin[sg["id"]] = (round(min(self.W, max(0.0, A * mx + B[0])), 1),     # the reframed eye midpoint:
                                     round(min(self.H, max(0.0, A * my + B[1])), 1))     # the punch origin (.fr)
        self._continuity()
        self._samples()
        self._titles()
        for si, p in enumerate(self.tl.shots):
            self._zone(si, p)
        self._harmonize()

    def _continuity(self) -> None:
        """A shot that opens on a punch (M) after a cut takes a punch origin that lands its eyes where the last shot's
        eyes were (founder: a 61 px sideways jump at a cut read as a mistake). The origin stays in [0, W], so the frame
        stays filled; the scale change is what makes the cut read as intended."""
        for prev, sg in zip(self.segs, self.segs[1:]):
            k = self.k_at(sg, sg["start"] + 0.6 / self.fps)      # the shot's first frame (cuts sit between frames)
            if prev["shot"] == sg["shot"] or k <= 1.0 + 1e-6 or sg["id"] not in self.origin or prev["id"] not in self.origin:
                continue
            a = self._frames(prev["shot"], prev["mstart"] + prev["end"] - prev["start"] - 0.2, prev["mstart"] + prev["end"] - prev["start"])
            b = self._frames(sg["shot"], sg["mstart"], sg["mstart"] + 0.2)
            if not a or not b:
                continue
            ex = lambda f, si: self.affine(si)[0] * (f["eyes"][0][0] + f["eyes"][1][0]) / 2 + self.affine(si)[1][0]  # noqa: E731
            kp, o = self.k_at(prev, prev["end"] - 1e-3), self.origin[prev["id"]]
            target = o[0] + kp * (ex(a[-1][1], prev["shot"]) - o[0])          # where the last shot left the eyes
            e0 = ex(b[0][1], sg["shot"])
            self.origin[sg["id"]] = (round(min(self.W, max(0.0, (k * e0 - target) / (k - 1))), 1), self.origin[sg["id"]][1])

    def k_at(self, sg: dict, t: float) -> float:
        """The runtime's camera(): the latest punch level at frame round(t*fps), times the zoom envelope."""
        c = self.kf.get(sg["id"]) or {"punches": [], "zooms": []}
        f, k, z = round(t * self.fps), 1.0, 0.0
        for pf, lvl in c["punches"]:
            if f >= pf:
                k = lvl
        for t0, t1, t2, t3, sc in c["zooms"]:
            if t0 <= t <= t3:
                e = 1.0 if t1 <= t <= t2 else (t - t0) / max(1e-6, t1 - t0) if t < t1 else (t3 - t) / max(1e-6, t3 - t2)
                z = max(z, (sc - 1) * min(1.0, max(0.0, e)))
        return k * (1 + z)

    def _samples(self) -> None:
        """Face boxes in reel px over time: (t, shot, protect box, planning box, planning box up to the hair top)
        as [x0, y0, x1, y1]. Hair: HAIR x face h over Vision's box top (real-1: 0.43 measured on the render)."""
        for sg in self.segs:
            si = sg["shot"]
            for m, fr in self._frames(si, sg["mstart"], sg["mstart"] + sg["end"] - sg["start"]):
                t = min(sg["end"], max(sg["start"], sg["start"] + m - sg["mstart"]))
                A, B = self.at(sg, t)
                fh = A * fr["box"][3]
                prot = _map(_feat(fr), A, B, (PAD * fh,) * 4)
                plan = _map(_head(fr), A, B, (PAD * fh, PAD * fh, PAD * fh, CHIN_PAD * fh))
                eye = A * (fr["eyes"][0][1] + fr["eyes"][1][1]) / 2 + B[1]
                self.samples.append((round(t, 4), si, prot, plan, [plan[0], plan[1] - HAIR * fh, plan[2], plan[3]], eye))
        self.samples.sort(key=lambda x: (x[0], x[1]))

    def at(self, sg: dict, t: float) -> tuple[float, tuple[float, float]]:
        """Take px -> reel px at reel time t: cover fit, reframe, then the punch about the reframed eye."""
        (A0, B0), k = self.affine(sg["shot"]), self.k_at(sg, t)
        o = self.origin.get(sg["id"], (self.W / 2, 0.38 * self.H))
        return k * A0, (k * B0[0] + (1 - k) * o[0], k * B0[1] + (1 - k) * o[1])

    def _face(self, t0: float, t1: float, which: int = 3, shot: int | None = None):
        return _union(s[which] for s in self.samples if t0 - 1e-6 <= s[0] <= t1 + 1e-6 and shot in (None, s[1]))

    # ---- title, caption zones, stickers ----------------------------------------------------------
    def _titles(self) -> None:
        for si, p in enumerate(self.tl.shots):
            for c in p.shot.cues:
                if c.type == "title":
                    s, e = title_window(self.tl, si, c, self.tl.duration)
                    b = self.place(TITLE, s, e, prefer_max=560)
                    self.titles.append({"t0": round(s, 4), "t1": round(e, 4), "box": b, "busy": self._busy(b, (s + e) / 2)})

    def _busy(self, b, t: float) -> float | None:
        """Busyness behind a reel box at reel time t, measured on the take frame under it (P5 hook)."""
        sg = next((x for x in self.segs if x["src"] and x["start"] <= t < x["end"]), None)
        d = self.face.get(sg["shot"]) if sg else None
        if not d:
            return None
        A, B = self.at(sg, t)
        box = [(b[0] - B[0]) / A, (b[1] - B[1]) / A, (b[2] - B[0]) / A, (b[3] - B[1]) / A]
        return busyness(sg["src"], sg["mstart"] + t - sg["start"], box, (d["w"], d["h"]))

    def place(self, default, s, e, others=(), prefer_max=None):
        """The y nearest the default (tops up to prefer_max first, then anywhere in the safe rect, 6 px grid)
        where the box clears the face planning box over [s, e] and the given boxes; else the default."""
        x, y0, w, h = default
        face = self._face(s, e)
        ok = lambda y: _hit(_box(x, y, w, h), face) == 0 and all(_hit(_box(x, y, w, h), b) == 0 for b in others)  # noqa: E731
        ys = sorted({y0, *range(SAFE[1], SAFE[3] - h + 1, 6)},
                    key=lambda y: (prefer_max is not None and y > prefer_max, abs(y - y0), y))
        return next((_box(x, y, w, h) for y in ys if SAFE[1] <= y <= SAFE[3] - h and ok(y)), _box(x, y0, w, h))

    def _zone(self, si: int, p) -> None:
        t0, t1 = p.out_start, p.out_start + p.duration
        plan, prot, h = self._face(t0, t1, 3, si), self._face(t0, t1, 2, si), self.cap_h
        hair = self._face(t0, t1, 4, si)
        if not plan:
            self.zones[si] = {"zone": "lower-band", "box": self.band, "face": None}
            return
        occ = [] if self.title_free else [tt["box"] for tt in self.titles if tt["t0"] < t1 and t0 < tt["t1"]]
        top_lim = max([SAFE[1]] + [b[3] + GAP for b in occ if b[3] <= plan[1]])
        cands = [("below-chin", _box(CAP_X, max(SAFE[1], plan[3]), CAP_W, h)),
                 # as high as the title allows: clear of the hair when there is room, else under the title (on the
                 # hair, never on the face: fits() keeps it above the forehead)
                 ("above-head", _box(CAP_X, max(top_lim, min(hair[1], SAFE[3]) - GAP // 2 - h), CAP_W, h)),
                 ("lower-band", self.band)]
        fits = lambda name, b: b[1] >= top_lim - 1e-6 and b[3] <= SAFE[3] + 1e-6 and all(  # noqa: E731
            _hit(b, o) == 0 for o in occ) and _hit(b, prot if name == "lower-band" else plan) == 0
        want = p.shot.meta.get("caption_zone")                               # a QA/director override goes first
        cands.sort(key=lambda nb: nb[0] != want)
        z = next(((n, b) for n, b in cands if fits(n, b)), None)
        if want and z and z[0] != want:
            self.notes.append(f"layout: {p.shot.id}: caption zone {want} would cover the face: {z[0]} instead")
        if z is None:          # nothing clears the face: the least overlap, flagged (QA blocks it)
            z = min(cands, key=lambda nb: (_hit(nb[1], prot), [n for n, _ in cands].index(nb[0])))
            self.notes.append(f"layout: {p.shot.id}: no caption zone clears the face ({z[0]} overlaps "
                              f"{_hit(z[1], prot):.0f} px2): reframe or retake")
        self.zones[si] = {"zone": z[0], "box": z[1], "face": xywh(plan), "fits": fits}

    def _harmonize(self) -> None:
        """Shots that chose the same zone share one box (the one nearest the faces that clears every shot),
        so captions do not hop a few px at each cut."""
        for name, pick in (("above-head", min), ("below-chin", max)):
            groups: list[list[int]] = []          # boxes within 80 px: one variant (clear of the hair / on it)
            for si in sorted((si for si, z in self.zones.items() if z["zone"] == name), key=lambda k: self.zones[k]["box"][1]):
                if groups and self.zones[si]["box"][1] - self.zones[groups[-1][-1]]["box"][1] <= 80:
                    groups[-1].append(si)
                else:
                    groups.append([si])
            for sis in (g for g in groups if len(g) > 1):
                b = _box(CAP_X, pick(self.zones[si]["box"][1] for si in sis), CAP_W, self.cap_h)
                if all(self.zones[si]["fits"](name, b) for si in sis):
                    for si in sis:
                        self.zones[si]["box"] = b

    def card_caption(self, layout: str, geo=None):
        """Where captions sit over a B-roll card (style.card_captions): the lower band (full / pip), above the
        seam on a split."""
        top = geo[0] if geo else SPLIT_H
        return _box(CAP_X, top - GAP - self.cap_h, CAP_W, self.cap_h) if layout == "split" else self.band

    def card_content(self, layout: str, geo=None, media: bool | str = False):
        """A card's content box (--x --y --w --h): its layout's area, ending GAP above its captions, or (no caption
        over the card) centred in the full frame / filling the split's top pane. Real media keeps its captions:
        media="fill" (a full-frame treatment) fills the split pane under them; an object (device, polaroid,
        sticker) stays whole above them; media="wide" (a device mockup) gets the WIDE x / width."""
        x, y, w = CONTENT.get(layout, CONTENT["full"])
        x, w = WIDE if media == "wide" else (x, w)
        if not self.style.get("card_captions", False) and layout == "full" and not media:
            return _box(x, y, w, FULL_BOTTOM - y)
        if media and layout == "split":     # captions paint over B-roll; an object ends above them
            bottom = (geo[0] if geo else SPLIT_H) if media == "fill" else self.card_caption(layout, geo)[1]
            return _box(x, MEDIA_TOP, w, bottom - GAP - MEDIA_TOP)
        return _box(x, y, w, self.card_caption(layout, geo)[1] - GAP - y)

    def split_geom(self, s: float, e: float) -> tuple[int, int]:
        """(top pane height, face drop dy) for a split card over [s, e): the face pane shows the take moved down by
        dy so the eye line sits at SPLIT_EYE (mouth and beard above the platform UI), and the seam sits SPLIT_HAIR
        above the hair top (founder: the hair touched the divider). Without a face track: the v2 defaults."""
        sm = [x for x in self.samples if s - 1e-6 <= x[0] <= e + 1e-6]
        if not sm:
            return SPLIT_H, 0
        eye = statistics.median(x[5] for x in sm)
        dy = max(0, round(SPLIT_EYE - eye))
        top = min(SPLIT_H, max(SPLIT_MIN, round(min(x[4][1] for x in sm) + dy - SPLIT_HAIR)))
        return top, min(dy, top)

    def caption_pieces(self, si: int, s: float, e: float, cards: list[tuple]):
        """[(s, e, box, zone)]: a chunk split at B-roll cuts; card pieces sit where card_caption() says.
        cards: (in, out, layout[, split geometry])."""
        cuts = sorted({round(x, 6) for a, b, *_ in cards for x in (a, b) if s + 1e-6 < x < e - 1e-6})
        out = []
        for a, b in zip([s] + cuts, cuts + [e]):
            if b - a < 1 / self.fps - 1e-6:
                continue
            mid = (a + b) / 2
            lay = next(((ly, g[0] if g else None) for ca, cb, ly, *g in cards if ca <= mid < cb), None)
            if lay:
                out.append((a, b, self.card_caption(*lay), "card"))
            else:
                z = self.zones.get(si) or {"zone": "lower-band", "box": self.band}
                out.append((a, b, z["box"], z["zone"]))
        return out

    def caption_style(self, box) -> str:
        pos = "" if box == self.band else \
            f"left:{xywh(box)[0]}px;top:{xywh(box)[1]}px;width:{xywh(box)[2]}px;height:{xywh(box)[3]}px;"
        return f' style="{pos}{css_vars(box)}"'

    def sticker(self, kind: str, s: float, e: float, low: bool = False):
        """Box for a face graphic (overlay chip, lower third): clear of the face, the captions and titles."""
        x, y, w, h = GFX[kind]
        y = 700 if kind == "overlay" and low else y
        others = [tt["box"] for tt in self.titles if tt["t0"] < e and s < tt["t1"]]
        others += [z["box"] for si, z in self.zones.items()
                   if self.tl.shots[si].out_start < e and s < self.tl.shots[si].out_start + self.tl.shots[si].duration]
        return self.place((x, y, w, h), s, e, others)

    def gfx_box(self, oid: str, kind: str, s: float, e: float, low: bool = False, text: str = ""):
        """(box, inline top or None, extra data-params) for a face graphic; endcards are full-screen (exempt)."""
        if kind == "title":
            tt = next((x for x in self.titles if abs(x["t0"] - s) < 1e-3), None)
            if tt is None:
                self.titles.append(tt := {"t0": round(s, 4), "t1": round(e, 4), "box": self.place(TITLE, s, e, prefer_max=560)})
            tt.update(id=oid, text=text)
            b, dflt = tt["box"], TITLE[1]
        elif kind in GFX:
            b, dflt = self.sticker(kind, s, e, low), 700 if kind == "overlay" and low else GFX[kind][1]
            self.card(oid, kind, s, e, b, "sticker", text=text)
        else:
            b, dflt = _box(0, 0, self.W, self.H), None
            self.card(oid, kind, s, e, b, "full", text=text)
        busy = tt.get("busy") if kind == "title" else None
        extra = {} if busy is None else {"busy": busy}
        tier = {"solid": "solid", "blur": "glass"}.get(str(self.style.get("title_backdrop", "auto")))
        if kind == "title" and tier:                                         # QA fix: style.title_backdrop
            extra["backing"] = tier
        return b, (round(b[1]) if dflt is not None and round(b[1]) != dflt else None), extra

    def face_crop(self, s: float, e: float):
        return self._face(s, e)

    # ---- record ----------------------------------------------------------------------------------
    def card(self, oid, kind, s, e, b, layout: str, crop=None, text: str = "", geo=None) -> None:
        """layout: full / split / pip (B-roll; the face is hidden or relocated) or sticker (a face graphic)."""
        self.cards.append({"id": oid, "kind": kind, "t0": round(s, 4), "t1": round(e, 4), "box": xywh(b),
                           "layout": layout, "text": text, **({"face_crop": xywh(crop)} if crop else {}),
                           **({"split_h": geo[0], "dy": geo[1]} if geo else {})})

    def face_reel(self) -> list[dict]:
        """The padded face (eyes+nose+mouth) on screen over reel time; "head" = forehead to chin, "hidden" while
        a B-roll card / endcard covers or relocates the face."""
        hidden = [(c["t0"], c["t1"]) for c in self.cards if c["layout"] != "sticker"]
        return [{"t": t, "shot": self.tl.shots[si].shot.id, "box": xywh(prot), "head": xywh(plan),
                 **({"hidden": True} if any(a <= t < b for a, b in hidden) else {})} for t, si, prot, plan, *_ in self.samples]

    def doc(self) -> dict:
        face = self.face_reel()
        boxes = [(c["chunk_id"], c["t0"], c["t1"], c["box"]) for c in self.caps]
        boxes += [(tt.get("id", "title"), tt["t0"], tt["t1"], xywh(tt["box"])) for tt in self.titles]
        boxes += [(c["id"], c["t0"], c["t1"], c["box"]) for c in self.cards if c["layout"] == "sticker"]
        over = []
        for what, a, b, bx in boxes:
            r = [bx[0], bx[1], bx[0] + bx[2], bx[1] + bx[3]]
            worst = max(((_hit(r, [f["box"][0], f["box"][1], f["box"][0] + f["box"][2], f["box"][1] + f["box"][3]]), f["t"])
                         for f in face if a - 1e-6 <= f["t"] < b and not f.get("hidden")), default=(0.0, None))
            if worst[0] > 0:
                over.append({"what": what, "t": worst[1], "area_px": round(worst[0])})
        titles = [{**tt, "box": xywh(tt["box"])} for tt in self.titles]
        return {"version": 1, "w": self.W, "h": self.H, "caption_family": self.family, "captions": self.caps,
                "title": titles[0] if titles else None, "titles": titles, "cards": self.cards,
                "zones": [{"shot": self.tl.shots[si].shot.id, "zone": z["zone"], "box": xywh(z["box"]), "face": z["face"]}
                          for si, z in sorted(self.zones.items())],
                "reframe": [{"clip": sg["id"], "shot": self.tl.shots[sg["shot"]].shot.id, "scale": self.rf[sg["shot"]][0],
                             "tx": self.rf[sg["shot"]][1], "ty": self.rf[sg["shot"]][2],
                             "origin": list(self.origin[sg["id"]]) if sg["id"] in self.origin else None,
                             **self.eye.get(sg["shot"], {})} for sg in self.segs],
                "face_reel": face, "overlaps": over}
