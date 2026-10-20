"""Auto-director: a lines-only script becomes a full cue plan. Text only, deterministic.

direct(script) returns a new Script with auto cues (params auto=True and a "why" naming the rule).
Manual cues are kept and win: an auto cue never overlaps a manual cue of the same kind, and manual
punches, B-roll, transitions and SFX count toward every budget below. Re-directing a directed script
drops the old auto cues first, so direct() is idempotent. Word times are a read-time estimate unless a
timeline (with real word times) is passed. Rules cite the research notes in docs/research/reel-craft/:
editing-pace (EP), hooks-structure (HS), captions-graphics (CG), sound (SD), trends-2026 (TR).
"""
import copy
import math
import re
from typing import NamedTuple

from . import broll_media as bm, lexicon as lx
from .presets import BROLL_BAND, DIRECTION, ENDCARD, ENERGY_BIAS, PACE, SFX_KITS, SFX_LEVEL_DB, TRANSITIONS, TX_SFX
from .schema import Cue, Script, Shot

PRE_ROLL, POST_ROLL = 0.15, 0.35        # cleanup.py keeps this much around each take
HOOK_INTERRUPT_BY = 1.0                 # EP H2: first visual change by 1.0 s
TITLE_UNTIL = 2.5                       # contract: hook text 0.0-~2.5 s
BROLL_MIN, BROLL_MAX, LIST_MAX = 1.2, 3.0, 6.0   # EP B2 (lists animate, so they may run to B3's 6 s)
BROLL_START_MIN, FACE_TAIL = 2.0, 2.0   # EP B4: first B-roll >= 2.0 s; last 2 s back on the face
MIN_SHOT = 0.8                          # EP P5: a face shot carrying speech lasts >= 0.8 s
BROLL_GAP, LAYOUT_GAP = MIN_SHOT, 3.0   # face between inserts (EP P5); split/pip flips (EP L4)
SFX_GAP = 2.0                           # contract SFX density cap: <= 1 per 2 s
TX_SPACING, TX_MAX, HARD_CUT_SHARE = 10.0, 3, 0.9   # EP T1/T2
EMPH_SHARE, EMPH_CHUNK = 0.15, 3        # CG section 5: <= 15% of words, <= 1 per 2-4 word chunk
ENDCARD_HOLD = 1.5                      # EP C12: never more than 1.5 s of card after the CTA
# EP P2: clustered intervals (runs of shorter changes, then a 1.5-2.5x S hold); multipliers on S.
CLUSTERS = ((0.85, 1.0, 1.8), (0.9, 0.8, 1.05, 1.9), (1.0, 0.85, 1.7))
ORDER = ("transition", "title", "punch", "broll", "overlay", "lowerthird", "emphasis", "sfx", "endcard")
_CLAUSE_END = re.compile(r"[,;:.!?]$")


def _glyph(params: dict, glyph: str | None) -> dict:
    return {**params, "icon": glyph} if glyph else params


class _W(NamedTuple):
    shot: int
    idx: int
    text: str
    start: float
    end: float


class _Director:
    """Auto broll params: an insert that ends on a shot's last word gets to_cut=True and a hold past the
    post-roll, so it runs to the cut and no face flash shorter than 0.8 s shows (EP P5)."""

    def __init__(self, script: Script, timeline=None, notes: list | None = None):
        self.s, self.style, self.notes = script, script.style, notes if notes is not None else []
        self.pace = PACE[self.style["pace"]]
        self.kit = SFX_KITS[self.style["sfx_kit"]]
        self.fam = TRANSITIONS[self.style["transitions"]]
        self.seed = lx.stable(script.title, self.style["preset"])
        self.manual = [[c for c in sh.cues if not c.params.get("auto")] for sh in script.shots]
        self.auto: list[list[Cue]] = [[] for _ in script.shots]
        self.words = self._times(timeline)
        self.n = len(self.words)
        self.dur = self.words[-1][-1].end + POST_ROLL
        self.energy = [self._energy(i) for i in range(self.n)]
        self.gap = max(MIN_SHOT, 0.5 * self.pace["S"])     # no visual change closer than half the pace

    # ---- timing and lookups -------------------------------------------------------------
    def _times(self, timeline) -> list[list[_W]]:
        out, t = [], 0.0
        for si, sh in enumerate(self.s.shots):
            texts = [w.text for w in sh.words]
            if timeline is not None:
                spans = [(sp.start, sp.end) for sp in timeline.shots[si].words]
            else:
                spans = lx.estimate_spans(texts, t + PRE_ROLL)
                t = spans[-1][1] + POST_ROLL
            out.append([_W(si, wi, x, a, b) for wi, (x, (a, b)) in enumerate(zip(texts, spans))])
        return out

    def texts(self, si: int) -> list[str]:
        return [w.text for w in self.s.shots[si].words]

    def on(self, si: int, kind: str) -> bool:
        flag = self.s.shots[si].meta.get("auto", True)
        return flag if isinstance(flag, bool) else bool(flag.get(kind, True))

    def cues(self, si: int, kinds=None) -> list[Cue]:
        return [c for c in self.manual[si] + self.auto[si] if kinds is None or c.type in kinds]

    def overlaps(self, si: int, kinds, a: int, b: int) -> bool:
        return any(c.start_word <= b and a <= c.end_word for c in self.cues(si, kinds))

    def add(self, si: int, ctype: str, a: int, b: int, why: str, **params) -> Cue:
        c = Cue(ctype, a, b, {**params, "auto": True, "why": why})
        self.auto[si].append(c)
        return c

    def span_t(self, si: int, a: int, b: int) -> tuple[float, float]:
        return self.words[si][a].start, self.words[si][b].end

    def _energy(self, si: int) -> float:
        sh = self.s.shots[si]
        if isinstance(sh.meta.get("energy"), (int, float)):
            return float(sh.meta["energy"])
        e = lx.shot_energy(sh.line, self.texts(si), si == 0, si == self.n - 1)
        return round(max(0.0, min(1.0, e + ENERGY_BIAS[self.style["pace"]])), 3)

    def stress(self, si: int, wi: int) -> float:
        return max(lx.stress(self.texts(si), wi), 1.0 * self.overlaps(si, {"emphasis"}, wi, wi))

    def _endcard_start(self) -> float:
        starts = [self.span_t(i, c.start_word, c.end_word)[0] for i in range(self.n) for c in self.cues(i, {"endcard"})]
        return min(starts, default=self.dur)

    def _title_end(self) -> int:
        end = max([w.idx for w in self.words[0] if w.end <= TITLE_UNTIL] or [0])
        chips = [c.start_word for c in self.cues(0, {"overlay"}) if 0 < c.start_word <= end]
        return min(chips) - 1 if chips else end      # the top band holds one item (DESIGN R-E5)

    # ---- text rules ---------------------------------------------------------------------
    def emphasis(self) -> None:
        """Numbers > money > negations get caption emphasis (CG section 5 priority order)."""
        total = sum(len(ws) for ws in self.words)
        used = sum(c.end_word - c.start_word + 1 for si in range(self.n) for c in self.cues(si, {"emphasis"}))
        budget = max(1, int(total * EMPH_SHARE)) - used
        cands = []
        for si in range(self.n):
            texts = self.texts(si)
            cands += [(0, si, a, a, "number") for a, b in lx.number_phrases(texts)]   # the number word only
            for wi, t in enumerate(texts):
                kinds = lx.word_kind_sets(t)
                if kinds & {"money", "negation"}:
                    cands.append((1 if "money" in kinds else 2, si, wi, wi, "money" if "money" in kinds else "negation"))
        for _, si, a, b, what in sorted(cands):
            if budget < b - a + 1 or not self.on(si, "emphasis"):
                continue
            if any(c.start_word - EMPH_CHUNK < b and a < c.end_word + EMPH_CHUNK for c in self.cues(si, {"emphasis"})):
                continue
            self.add(si, "emphasis", a, b, f"emphasis on {what} (CG 5: <=1 per chunk, <=15% of words)")
            budget -= b - a + 1

    def endcard(self) -> None:
        last = self.n - 1
        if any(self.cues(si, {"endcard"}) for si in range(self.n)) or not self.on(last, "endcard"):
            return
        ws, texts = self.words[last], self.texts(last)
        a = next((w.idx for w in ws if w.start >= ws[-1].end - ENDCARD_HOLD), ws[-1].idx)
        self.add(last, "endcard", a, ws[-1].idx, "CTA card over the last ~1.5 s, loop-friendly (EP C12)",
                 text=lx.cta_text(texts) or ENDCARD["text"], sub=ENDCARD["sub"])

    def chips(self) -> None:
        """Numbers shown on the face as a top-band chip, <= 1 per shot (EP P6: no B-roll over the number)."""
        if not self.pace["chips"]:
            return
        for si in range(self.n):
            if not self.on(si, "overlay") or self.cues(si, {"overlay"}):
                continue
            for a, b in lx.number_phrases(self.texts(si)):
                if self.overlaps(si, {"broll", "cutaway", "endcard"}, a, b) or (si == 0 and a < 3):
                    continue        # a chip in the first 3 words would cut the hook title short (R-E5)
                value, label = lx.number_display(self.texts(si)[a:b + 1])
                text = f"{value} {label}".strip()
                self.add(si, "overlay", a, b, "number chip on the face (EP P6, TR T34 <=4 words)",
                         text=text if len(text) <= 12 else value)
                break

    def title(self) -> None:
        """Hook text by 0.3 s (shot 'title' when given); it stops before a number chip it would repeat."""
        if self.cues(0, {"title"}) or not self.on(0, "title"):
            return
        given, chips = self.s.shots[0].meta.get("title"), [c.start_word for c in self.cues(0, {"overlay"})]
        para = None if isinstance(given, str) else lx.hook_paraphrase(self.texts(0))   # HS08: number first
        text = given if isinstance(given, str) else para or lx.hook_title(self.texts(0), min(chips, default=None))
        self.add(0, "title", 0, max(0, self._title_end()), "hook text on screen by 0.3 s, <=7 words (EP H3, HS08)",
                 text=" ".join(text.split()[:7]), **({"paraphrase": True} if para else {}))

    def lowerthird(self) -> None:
        creator = self.style.get("creator")
        if not isinstance(creator, dict) or not creator.get("name") or \
                any(self.cues(si, {"lowerthird"}) for si in range(self.n)):
            return
        for w in (w for ws in self.words for w in ws):    # CG 8.2: once, after the hook, 3-6 s, hold 2.5 s+
            if 3.0 <= w.start <= 6.0 and self.on(w.shot, "lowerthird"):
                ws = self.words[w.shot]
                b = next((x.idx for x in ws[w.idx:] if x.end - w.start >= 2.5), ws[-1].idx)
                if not self.overlaps(w.shot, {"title", "overlay", "broll", "cutaway", "endcard"}, w.idx, b):
                    self.add(w.shot, "lowerthird", w.idx, b, "name strap once after the hook (CG 8.2)",
                             text=str(creator["name"]), **({"sub": str(creator["role"])} if creator.get("role") else {}))
                    return

    # ---- B-roll ---------------------------------------------------------------------------
    def broll(self) -> None:
        """Cover 25-40% of runtime (EP B1, contract band) with inserts tied to numbers, lists and nouns."""
        target, cap = self.pace["broll"] * self.dur, BROLL_BAND[1] * self.dur
        have = sum(self._len(si, c) for si in range(self.n) for c in self.cues(si, {"broll", "cutaway"}))
        cands = [c for si in range(self.n) if self.on(si, "broll") for c in self._broll_candidates(si)]
        layouts = max(1, int(3 * self.dur / 30)) - sum(     # EP L4: <= 3 layout changes per 30 s
            c.params.get("layout", "full") != "full" for si in range(self.n) for c in self.cues(si, {"broll"}))
        from .policy import TEXT_MAX     # a label-only card ends after its phrase: the policy trims it to TEXT_MAX
        for score, si, a, b, params, why in sorted(cands, key=lambda c: (-c[0], c[1], c[2])):
            ta, tb = self.span_t(si, a, b)
            tb = min(tb, ta + TEXT_MAX) if params.get("kind") == "text" else tb     # what it will cost the band
            if have >= target:
                break
            for layout in dict.fromkeys([params["layout"] if layouts > 0 else "full", "full"]):
                if have + (tb - ta) <= cap and self._broll_fits(si, a, b, layout):
                    to_cut = {"to_cut": True, "hold": POST_ROLL + 0.15} \
                        if b == len(self.words[si]) - 1 and si + 1 < self.n else {}
                    self.add(si, "broll", a, b, why, **{**params, "layout": layout}, **to_cut)
                    have, layouts = have + tb - ta, layouts - (layout != "full")
                    break
        if have < BROLL_BAND[0] * self.dur:
            have = self._grow(have)
        if have < BROLL_BAND[0] * self.dur:
            self.notes.append(f"broll: coverage {have / self.dur:.0%} is under {BROLL_BAND[0]:.0%} "
                              "(not enough concrete nouns, numbers or lists in the lines)")

    def _grow(self, have: float) -> float:
        """Under the band: lengthen auto inserts word by word inside their sentence (EP B2 <= 3 s)."""
        for si in range(self.n):
            for c in [c for c in self.auto[si] if c.type == "broll"]:
                texts, hi = self.texts(si), LIST_MAX if c.params["kind"] == "list" else BROLL_MAX
                while have < BROLL_BAND[0] * self.dur and c.end_word + 1 < len(texts) \
                        and texts[c.end_word][-1] not in ".!?":
                    self.auto[si].remove(c)
                    a, b = c.start_word, c.end_word + 1
                    ok = self.span_t(si, a, b)[1] - self.span_t(si, a, b)[0] <= hi and \
                        self._broll_fits(si, a, b, c.params["layout"])
                    self.auto[si].append(c)
                    if not ok:
                        break
                    have += self.words[si][b].end - self.words[si][b - 1].end
                    c.end_word = b
                if c.end_word == len(texts) - 1 and si + 1 < self.n:
                    c.params.update(to_cut=True, hold=POST_ROLL + 0.15)
        return have

    def _len(self, si: int, c: Cue) -> float:
        a, b = self.span_t(si, c.start_word, c.end_word)
        return b - a

    def _extend(self, si: int, a: int, b: int, hi: float = BROLL_MAX) -> tuple[int, int] | None:
        """Grow a span to >= 1.2 s inside its clause, then across commas, never past a sentence end (<= hi s)."""
        ws, texts = self.words[si], self.texts(si)
        d, lo = (lambda: ws[b].end - ws[a].start), max(BROLL_MIN, self.pace["insert"])   # noqa: E731
        while d() < lo and b + 1 < len(ws) and not _CLAUSE_END.search(texts[b]):
            b += 1
        while d() < lo and a > 0 and not _CLAUSE_END.search(texts[a - 1]):
            a -= 1
        while d() < lo and b + 1 < len(ws) and texts[b][-1] not in ".!?":
            b += 1
        if not lo <= d() <= hi:
            return None
        a0 = 0 if ws[a].start - ws[0].start < MIN_SHOT else a     # snap to the shot's cut rather than
        b0 = len(ws) - 1 if ws[-1].end - ws[b].end < self.gap else b   # leave a short face flash (EP P5)
        return next((x, y) for x, y in ((a0, b0), (a, b0), (a0, b), (a, b)) if ws[y].end - ws[x].start <= hi)

    def _broll_candidates(self, si: int) -> list:
        texts, out, ec = self.texts(si), [], self._endcard_start()
        items = [(s, e) for s, e in (lx.enumeration(texts) or []) if self.words[si][e].end <= ec - 0.1]
        if len(items) >= 2:
            a, b = items[0][0], items[-1][1]
            d = self.span_t(si, a, b)[1] - self.span_t(si, a, b)[0]
            if BROLL_MIN <= d <= LIST_MAX:
                out.append((3.0, si, a, b, {"kind": "list", "items": [lx.item_text(texts[s:e + 1]) for s, e in items],
                            "layout": "split" if d > BROLL_MAX else "full"},
                            "list B-roll for a spoken enumeration (EP B5, TR T23)"))
        for a, b in lx.number_phrases(texts):
            if span := self._extend(si, a, b):
                value, label = lx.number_display(texts[a:b + 1])
                label = label or lx.label(texts, b + 1, content_only=True)
                out.append((3.0, si, *span, _glyph({"kind": "stat", "value": value, "label": label, "layout": "split"},
                                                   lx.glyph_for(texts[a:b + 1]) or lx.glyph_for(texts[a:span[1] + 1])),
                            "stat B-roll on a spoken number, face kept in split (EP B5 + P6)"))
        contrast = lx.starts_with_marker(self.s.shots[si].line)
        nums = lx.number_phrases(texts)
        for a, b in lx.noun_phrases(texts):
            span = self._extend(si, a, b)
            if not span or any(x <= span[1] and span[0] <= y for x, y in nums):   # EP P6: never over a number
                continue
            if icon := lx.icon_for(texts[a:b + 1]):        # params["icon"] is a vendored glyph id (icons/)
                out.append((2.0, si, *span, {"kind": "icon", "icon": lx.glyph_for(texts[a:b + 1]) or lx.PACK_GLYPH[icon],
                                             "text": lx.label(texts, a), "layout": "pip"}, "icon B-roll on a concrete noun (EP B5, L1)"))
            else:
                out.append((1.5 if contrast else 1.0, si, *span, _glyph(
                            {"kind": "text", "text": lx.broll_label(texts, a, b, span[1]), "layout": "full"},
                            lx.card_glyph(texts, a, b, span[1])), "text B-roll on a concrete noun (EP B5; TR T34 label <=4 words)"))
        return out

    def _broll_fits(self, si: int, a: int, b: int, layout: str) -> bool:
        ta, tb = self.span_t(si, a, b)
        if ta < BROLL_START_MIN or tb > self._endcard_start() - 0.1:
            return False
        if (si == 0 and a <= self._title_end() and self.on(0, "title")) or \
                (layout == "full" and tb > self.dur - FACE_TAIL):
            return False
        if self.overlaps(si, {"broll", "cutaway", "title", "overlay", "lowerthird", "endcard"}, a, b):
            return False
        cuts = [self.words[i][0].start for i in range(1, self.n)
                if (i, 0) != (si, a) and not (i == si + 1 and b == len(self.words[si]) - 1)]
        if any(min(abs(ta - t), abs(tb - t)) < MIN_SHOT for t in cuts):
            return False
        for i in range(self.n):
            for c in self.cues(i, {"broll", "cutaway"}):
                ca, cb = self.span_t(i, c.start_word, c.end_word)
                gap = LAYOUT_GAP if "full" not in (layout, c.params.get("layout", "full")) else BROLL_GAP
                chained = (i == si + 1 and c.start_word == 0 and b == len(self.words[si]) - 1) or \
                    (i == si - 1 and a == 0 and c.end_word == len(self.words[i]) - 1)   # inserts across a cut
                if ta < cb + gap and ca < tb + gap and not (chained and max(cb, tb) - min(ca, ta) <= LIST_MAX):
                    return False
        return True

    # ---- picture: transitions and the punch ladder ---------------------------------------
    def transitions(self) -> None:
        """Stylised transitions only at section boundaries, id by energy; hard cuts stay >= 90% of all
        cuts (EP T1/T2: <= 1 per 10 s, <= 3 per reel)."""
        cands = []
        for i in range(1, self.n):
            if self.cues(i, {"transition"}) or not self.on(i, "transition"):
                continue
            marker = lx.starts_with_marker(self.s.shots[i].line)
            e = max(self.energy[i - 1], self.energy[i])
            tid = self.fam["last"] if i == self.n - 1 else \
                self.fam["high" if e >= 0.75 else "mid" if e >= 0.5 else "low"]
            if tid and (marker or i in (1, self.n - 1)):
                cands.append((-(e + 0.3 * marker + 0.2 * (i in (1, self.n - 1))), i, tid, e))
        clause_cuts = sum(bool(_CLAUSE_END.search(w.text)) for ws in self.words for w in ws[:-1])
        cuts = len(self._ves()) + clause_cuts + int(self.dur / self.pace["S"])     # estimated, incl. jump cuts
        placed = [self.words[i][0].start for i in range(self.n) if self.cues(i, {"transition"})]
        budget = min(TX_MAX, math.floor((1 - HARD_CUT_SHARE) * cuts + 1e-9)) - len(placed)
        whips = 0
        for _, i, tid, e in sorted(cands):
            t = self.words[i][0].start
            if budget <= 0 or any(abs(t - p) < TX_SPACING for p in placed):
                if budget <= 0:
                    self.notes.append(f"transition into {self.s.shots[i].id!r} skipped: hard cuts stay >= 90% (EP T1)")
                continue
            params = {}
            if tid == "whip":
                params, whips = {"dir": [1, 0] if whips % 2 == 0 else [-1, 0]}, whips + 1
            self.add(i, "transition", 0, 0, f"section boundary, energy {e:.2f} -> {tid} (EP T2)", id=tid,
                     **({"params": params} if params else {}))
            placed.append(t)
            budget -= 1

    def hook_punch(self) -> None:
        ws = self.words[0]
        if not self.on(0, "punch") or any(ws[c.start_word].start <= HOOK_INTERRUPT_BY
                                          for c in self.cues(0, {"punch", "zoom"})):
            return
        cands = [w for w in ws if 0.25 <= w.start <= HOOK_INTERRUPT_BY and w.idx > 0]
        w = max(cands, key=lambda w: (self.stress(0, w.idx), -w.idx)) if cands else \
            min(ws[1:] or ws, key=lambda w: (abs(w.start - HOOK_INTERRUPT_BY), w.idx))
        self.add(0, "punch", w.idx, w.idx, "hook pattern interrupt: first visual change by 1.0 s (EP H2, HS07)",
                 level="?")

    def _ves(self) -> list[float]:
        """Visual events so far: shot cuts, B-roll in/out, punches and zooms."""
        ts = [self.words[i][0].start for i in range(1, self.n)]
        for si in range(self.n):
            for c in self.cues(si, {"broll", "cutaway"}):
                a, b = self.span_t(si, c.start_word, c.end_word)
                last = c.end_word == len(self.words[si]) - 1 and c.params.get("to_cut")
                ts += [a, (self.words[si + 1][0].start if si + 1 < self.n else self.dur) if last else b]
            ts += [self.words[si][c.start_word].start for c in self.cues(si, {"punch", "zoom"})
                   if not self._under_insert(si, c.start_word)]        # hidden reframes are not changes
        return sorted(set(round(t, 3) for t in ts))

    def _blocked(self, w: _W) -> bool:
        return self.overlaps(w.shot, {"broll", "cutaway", "endcard", "punch", "zoom"}, w.idx, w.idx) or \
            (w.idx == 0 and bool(self.cues(w.shot, {"transition"})))

    def _under_insert(self, si: int, wi: int) -> bool:
        return any(c.start_word <= wi <= c.end_word and c.params.get("layout", "full") == "full"
                   for c in self.cues(si, {"broll", "cutaway"}))

    def _section(self, t: float) -> float:
        """EP P3 pace curve: hook x0.55, payoff (65-85%) x0.8, close (last 12%) x1.4, else x1.0."""
        p = t / self.dur
        return 0.55 if t < 3.0 else 0.8 if 0.65 <= p < 0.85 else 1.4 if p >= 0.88 else 1.0

    def punches(self) -> None:
        """Punch-ins at the pace profile's cadence, clustered, never metronomic (EP P1/P2/P4)."""
        for si in range(self.n):              # EP B6: come back from a full insert on a new framing
            for c in self.cues(si, {"broll", "cutaway"}):
                e = c.end_word      # the change happens under the insert, so the face returns reframed
                if e + 1 < len(self.words[si]) and c.params.get("layout", "full") == "full" and self.on(si, "punch") \
                        and not self.overlaps(si, {"punch", "zoom"}, e, e):
                    self.add(si, "punch", e, e, "back from B-roll on a different framing (EP B6)", level="?")
        S = self.pace["S"] * DIRECTION.get(self.style["preset"], DIRECTION["clean-pro"])["stretch"]   # per preset
        words = [w for ws in self.words for w in ws if self.on(w.shot, "punch")]
        pattern = CLUSTERS[(lx.stable(self.s.title) + DIRECTION.get(self.style["preset"], {}).get("cadence", 0)) % 3]
        first = [self.words[0][c.start_word].start for c in self.cues(0, {"punch", "zoom"})]
        L, k = (min(first) if first else 0.0), self.seed % 2
        while True:
            g = S * self._section(L) * pattern[k % len(pattern)]
            k += 1
            if L + g > self.dur - 0.6:
                break
            ves = self._ves()
            nxt = next((t for t in ves if t > L + 0.4), None)
            if nxt is not None and nxt <= L + 1.3 * g:
                L = nxt
                continue
            limit = nxt - self.gap if nxt is not None else self.dur - 0.6
            ok = [w for w in words if not self._blocked(w) and w.start <= limit
                  and all(abs(w.start - v) >= self.gap for v in ves)]
            pick = [w for w in ok if L + 0.7 * g <= w.start <= L + 1.3 * g] or \
                   [w for w in ok if L + MIN_SHOT <= w.start <= L + self.pace["max_static"]]
            if not pick:
                if nxt is None:
                    break
                L = nxt
                continue
            w = max(pick, key=lambda w: (self.stress(w.shot, w.idx) - abs(w.start - L - g) / g, -w.start))
            self.add(w.shot, "punch", w.idx, w.idx,
                     f"cadence: {self.style['pace']} pace, median change {S:.2f} s, clustered (EP P1/P2)", level="?")
            L = w.start
        self._levels()

    def _levels(self) -> None:
        """Ladder W 1.00 / M 1.17 / T 1.32 (EP J1/J3): W -> M, M or T -> W; one T, late, on a number or
        money word (EP J6), entered only from W so the compiler's T -> M cap on narrow takes still changes
        level. Each shot opens at W; a cut without a transition after a W ending opens on M instead (EP J2:
        every jump cut changes level). Consecutive punches always change level."""
        t_left, prev_end = 1, None
        for si in range(self.n):
            if prev_end == "W" and not self.cues(si, {"transition"}) and self.on(si, "punch") \
                    and not self.overlaps(si, {"punch", "zoom"}, 0, 0) and not self._under_insert(si, 0):
                self.add(si, "punch", 0, 0, "shot cut without a transition changes framing (EP J2)", level="?")
            cur = "W"
            for c in sorted(self.cues(si, {"punch"}), key=lambda c: c.start_word):
                if c.params.get("level") != "?":
                    cur = c.params["level"]
                    continue
                w = self.words[si][c.start_word]
                worthy = self.stress(si, w.idx) >= 2 and w.start >= 0.5 * self.dur
                lvl = ("T" if worthy and t_left else "M") if cur == "W" else "W"
                t_left -= lvl == "T"
                c.params["level"], cur = lvl, lvl
            prev_end = cur

    # ---- sound and lint ---------------------------------------------------------------------
    def sfx(self) -> None:
        """Contract policy: hook hit, whoosh on transitions, ding on stats, pop on titles/overlays; at most
        one per 2 s, none in the first 0.3 s (but the hook hit) or the last 0.5 s (SD section 6)."""
        fixed = [self.words[si][c.start_word].start for si in range(self.n) for c in self.cues(si, {"sfx"})]
        cands = []
        for si in range(self.n):
            for c in self.cues(si) if self.on(si, "sfx") else []:
                w = self.words[si][c.start_word]
                if c.type == "punch" and si == 0 and w.start <= HOOK_INTERRUPT_BY:
                    cands.append((0, w, self.kit["hook"], "hook", "hook hit on the pattern interrupt (SD 5)"))
                elif c.type == "transition" and c.params.get("id") in TX_SFX:
                    cands.append((1, w, TX_SFX[c.params["id"]], "whoosh", "whoosh on the transition (SD 5)"))
                elif c.type == "broll" and c.params.get("kind") == "stat":
                    cands.append((2, self.words[si][c.end_word], self.kit["ding"], "ding",
                                  "ding as the stat lands (SD 5)"))
                elif c.type == "broll":
                    cands.append((3, w, self.kit["pop"], "pop", "pop as the B-roll card enters (SD 5)"))
                elif c.type in ("title", "overlay"):
                    cands.append((3, w, self.kit["pop"], "pop", f"pop as the {c.type} appears (SD 5)"))
        for _, w, sid, role, why in sorted(cands, key=lambda c: (c[0], c[1].start)):
            if (w.start < 0.3 and role != "hook") or w.start > self.dur - 0.5:
                continue
            if any(abs(w.start - t) < SFX_GAP for t in fixed):
                continue
            self.add(w.shot, "sfx", w.idx, w.idx, why, id=sid, role=role, level_db=SFX_LEVEL_DB[role],
                     **({"on": "lead"} if "B-roll" in why else {}))
            fixed.append(w.start)

    def lint(self) -> None:
        """Report the pace (EP C1: interval CV under 0.25 is the metronome tell)."""
        from .pace import pace_note         # one formula for the director and the council (gaps between changes)
        ves = [t for t in self._ves() if t > 0]
        if len(ves) >= 4:
            self.notes.append("director plan " + pace_note(ves))

    def run(self) -> Script:
        for step in (self.emphasis, self.endcard, self.lowerthird, self.broll, lambda: bm.plan(self), self.chips,
                     self.title, self.hook_punch, self.transitions, self.punches, self.sfx, self.lint):   # bm: real media
            step()
        out = copy.deepcopy(self.s)
        rank = {k: n for n, k in enumerate(ORDER)}
        for si, sh in enumerate(out.shots):
            autos = sorted(self.auto[si], key=lambda c: (c.start_word, rank[c.type], c.end_word))
            out.shots[si] = Shot(sh.id, sh.line, sh.words, copy.deepcopy(self.manual[si] + autos), dict(sh.meta))
        if out.music is None:
            out.music = {"mood": self.style["music_mood"], "auto": True,
                         "why": "bed by style.music_mood, ducked under the voice (TR T06)"}
        return out


def direct(script: Script, timeline=None, notes: list | None = None) -> Script:
    """Add auto cues to a copy of `script`. `timeline` (a timeline.Timeline) swaps the read-time
    estimate for real word times; `notes` collects lint and rules that could not fire."""
    return _Director(script, timeline, notes).run()
