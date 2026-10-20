"""Council v1 policy (20 Oct 2026): the binding caps, applied after the director.

The director proposes; this pass makes the auto cues obey the council's numbers. Manual cues are
never touched (they only fail the build through schema validation). Every change is logged in
`notes`, so `direct` and Studio can say what was dropped and why. Deterministic: no clock, no random;
the only "jitter" lives in the compiler, seeded from crc32(title).

Inputs are reel times from a timeline (build_timeline), so rules use real word times.
"""
import copy
from dataclasses import replace

from . import presets
from . import beats
from . import broll_flow, broll_media
from .pace import metrics, no_repeats, pace_note, replan  # noqa: F401  (metrics re-exported: policy.metrics)
from .schema import Cue, Script, ScriptError, pack_ids
from .stagger import card_in

DEFAULT_PRESET = "clean-pro"
BETA_PRESETS = {"desi-bilingual"}          # Devanagari input is deferred (council 3)
STYLE_PATCH = {"bold-hustle": {"accent": "#FFE14D"}, "beast-hype": {"accent": "#00E676"},
               "editorial": {"caption": "boxed"}}
LOOK_CAP = {"grain": 0.08, "vignette": 0.18}
PACE = {   # council 2: median visual change, max static, B-roll cap, SFX per 30 s, auto transitions per T s
    "calm":     {"median": 4.0, "max_static": 6.0, "broll": 0.15, "sfx30": 3, "tx_every": None},
    "standard": {"median": 2.6, "max_static": 4.0, "broll": 0.25, "sfx30": 6, "tx_every": 12.0},
    "punchy":   {"median": 1.8, "max_static": 3.0, "broll": 0.35, "sfx30": 8, "tx_every": 10.0},
}
TX_FAMILY = {k: v["tx"] for k, v in presets.DIRECTION.items() if v["tx"]}   # council 5: one family per preset
TX_MS = 300                                # 9 frames at 30 fps (council 5: 8-10 frames)
SFX_IDS = {"pop": "snd.ui.pop", "pop_alt": "snd.ui.pop_down", "ding": "snd.ui.count_run",   # pop_alt: energetic
           "whip": "snd.whoosh.whip_pan", "push": "snd.tx.push", "zoomThrough": "snd.tx.zoom_through"}
HOOK_HIT = {"bold-hustle": "snd.hit.punch", "beast-hype": "snd.hit.punch"}   # others: snd.hit.soft
SFX_RANK = {"hook": 0, "whoosh": 1, "ding": 2, "pop": 3}
INSERT = (1.2, 3.0)                        # council 4: insert length
TEXT_MAX = 1.5      # a full-screen text card (label only) ends after its phrase (founder: <= 1.4 s, face on the payoff)
FIRST_INSERT, FACE_GAP, FACE_TAIL, LEAD = 2.0, 1.5, 2.5, 4 / 30
TITLE_UNTIL, TITLE_WORDS = 2.5, (4, 6)
SPLIT_KINDS, SPLIT_GAP = ("list", "stat"), 0.5   # v2: a list/stat card the face rules would drop goes split
EMPH_SHARE, FRAME = 0.12, 1 / 30


def prepare(data: dict, preset: str | None = None) -> dict:
    """Raw script dict -> the dict to parse: --preset wins, else the script's, else clean-pro; the
    council's preset patch and look caps fill keys the script did not set itself."""
    data = copy.deepcopy(data)
    st = dict(data.get("style") or {})
    if preset:
        st["preset"] = preset
    st.setdefault("preset", DEFAULT_PRESET)
    for k, v in STYLE_PATCH.get(st["preset"], {}).items():
        st.setdefault(k, v)
    look = dict(st.get("look") or {})
    base = presets.PRESETS.get(st["preset"], {}).get("look", {})
    for k, cap in LOOK_CAP.items():
        look.setdefault(k, min(float(base.get(k, 0.0)), cap))
    st["look"] = look
    st.setdefault("progress", False)       # progress bar is deferred (council 3)
    data["style"] = st
    return data


class _Pass:
    def __init__(self, s: Script, tl, notes: list):
        self.s, self.tl, self.notes = copy.deepcopy(s), tl, notes
        self.style = s.style
        self.name = s.style.get("preset", DEFAULT_PRESET)
        self.pace = PACE.get(s.style.get("pace", "standard"), PACE["standard"])
        self.T = tl.duration

    # -- helpers -----------------------------------------------------------------------------------
    def t(self, si: int, wi: int, end: bool = False) -> float:
        w = self.tl.shots[si].words[wi]
        return w.end if end else w.start

    def pt(self, si: int, c: Cue) -> float:
        """When a punch lands: frame 0 of its shot (open), its clip's cut (on=cut), else its word."""
        p, t = self.tl.shots[si], self.t(si, c.start_word)
        if c.params.get("open"):
            return p.out_start
        if c.params.get("on") == "cut":
            return max([cl.out_start for cl in p.clips if cl.out_start <= t + 1e-6] or [t])
        return t

    def autos(self, kind: str) -> list[tuple[int, Cue]]:
        out = [(si, c) for si, sh in enumerate(self.s.shots) for c in sh.cues
               if c.type == kind and c.params.get("auto")]
        return sorted(out, key=lambda x: (self.t(x[0], x[1].start_word), x[0]))

    def drop(self, si: int, c: Cue, why: str) -> None:
        self.s.shots[si].cues.remove(c)
        self.notes.append(f"council: dropped auto {c.type} in {self.s.shots[si].id!r} at "
                          f"{self.t(si, c.start_word):.2f}s ({why})")

    def add(self, si: int, kind: str, wi: int, why: str, **params) -> Cue:
        c = Cue(kind, wi, wi, {**params, "auto": True, "why": f"council: {why}"})
        self.s.shots[si].cues.append(c)
        return c

    def span(self, si: int, c: Cue) -> tuple[float, float]:
        p = self.tl.shots[si]
        a, b = self.t(si, c.start_word), self.t(si, c.end_word, True)
        if c.type in ("broll", "cutaway") or c.params.get("to_cut"):   # the compiler holds a card past its word
            b = min(p.out_start + p.duration, b + float(c.params.get("hold", 0.25 if c.type == "cutaway" else 0.2)))
        if c.type == "broll":     # the compiler's span: 4-frame lead snapped onto a near cut, out on the next word
            a = card_in(p.out_start, a, round(1 / FRAME), round(LEAD / FRAME))
            ws = getattr(p, "words", None) or []
            if c.end_word + 1 < len(ws) and ws[c.end_word + 1].start >= a + INSERT[0] - 1e-6:
                b = min(b, ws[c.end_word + 1].start)
            return a, b
        return a - LEAD, b

    def has_face(self, si: int) -> bool:
        from .layout import load_face
        take = self.tl.shots[si].take
        return bool(take) and load_face(take.src, getattr(take, "duration", None))[0] is not None

    def auto_ok(self, si: int, kind: str) -> bool:
        a = self.s.shots[si].meta.get("auto", True)
        return a is not False and not (isinstance(a, dict) and a.get(kind) is False)

    def jump_cuts(self) -> list[float]:
        return [c.out_start for p in self.tl.shots for c in p.clips[1:]]

    def punch_off(self, si: int) -> bool:
        """The compiler's resolution guard (council 3): a 9:16 crop under 1061 px switches punches off."""
        from .compiler import PUNCH_MIN_CAP, probe_size
        take = self.tl.shots[si].take
        w, h = probe_size(str(take.src)) if take else (0, 0)
        crop = round(min(w, h * self.s.width / self.s.height)) if w and h else 0
        return bool(crop) and 1.10 * crop / 1080 < PUNCH_MIN_CAP

    # -- rules -------------------------------------------------------------------------------------
    def simple(self) -> None:
        for si, c in self.autos("zoom"):
            self.drop(si, c, "no auto zoom")
        if not self.style.get("endcard"):
            for si, c in self.autos("endcard"):
                self.drop(si, c, "endcard is opt-in (style.endcard)")

    def title(self) -> None:
        for si, c in self.autos("title"):
            words = self.s.shots[si].words
            chip = next((o for sj, o in self.autos("overlay") if sj == si and o.start_word == c.end_word + 1), None)
            if chip and chip.end_word - c.start_word + 1 <= TITLE_WORDS[1]:
                c.end_word = chip.end_word          # the hook number belongs in the title (chip is dropped below)
            n = c.end_word - c.start_word + 1
            end = c.start_word + min(max(n, TITLE_WORDS[0]), TITLE_WORDS[1]) - 1
            for k in range(c.start_word, min(end, len(words) - 1) + 1):   # stop after a clause end
                if words[k].text[-1:] in ".!?;:" and k - c.start_word + 1 >= TITLE_WORDS[0]:
                    end = k
                    break
            c.end_word = min(end, len(words) - 1)
            if not c.params.get("paraphrase"):      # HS08: a number-first paraphrase is kept as written
                c.params["text"] = " ".join(w.text.strip(".,!?;:\"'") for w in words[c.start_word:c.end_word + 1])
        titles = [(0.0, TITLE_UNTIL)] if self.autos("title") or any(
            c.type == "title" for sh in self.s.shots for c in sh.cues) else []
        for si, c in self.autos("overlay"):       # <= 1 graphic besides captions
            a, b = self.t(si, c.start_word), self.t(si, c.end_word, True) + 1.4
            if any(a < te and ts < b for ts, te in titles):
                self.drop(si, c, "title is on screen: one graphic at a time")

    def broll(self) -> None:
        card = presets.DIRECTION.get(self.name, presets.DIRECTION[DEFAULT_PRESET])   # card style per preset
        media = broll_media.take(self)          # v4 real-media inserts keep their layouts: capped after the cards
        for si, c in self.autos("broll"):
            p = c.params
            p.update(layout="full", background=p.get("background", card["card"]))
            if p.get("kind") == "clip":
                self.drop(si, c, "clip B-roll is deferred")
                continue
            if p.get("kind") == "icon":
                p.update(kind="text", text=p.get("text") or p.get("icon", ""))
                p.pop("icon", None)
            if p.get("kind") == "text" and p.get("text"):
                p["text"] = presets.card_case(str(p["text"]), card["case"], self.s.shots[si].line)
            top = TEXT_MAX if p.get("kind") == "text" else INSERT[1]
            while c.end_word > c.start_word and self.span(si, c)[1] - self.span(si, c)[0] > top + 1e-6:
                c.end_word -= 1
                c.params.pop("to_cut", None)
                if self.span(si, c)[1] - self.span(si, c)[0] < INSERT[0] - 1e-6:   # never trim under the minimum
                    c.end_word += 1
                    break
        first = max(FIRST_INSERT, TITLE_UNTIL)
        kept: list[tuple[float, float]] = []
        for si, c in self.autos("broll"):
            a, b = self.span(si, c)
            gap = a - kept[-1][1] if kept else 99.0
            face = (f"face on screen for the last {FACE_TAIL}s" if b > self.T - FACE_TAIL + 1e-6
                    else f"needs {FACE_GAP}s of face between inserts" if gap < FACE_GAP - 1e-6 else None)
            if a < first - 1e-6:
                self.drop(si, c, f"first insert starts at >= {first:.1f}s")
            elif b - a < INSERT[0] - 1e-6:
                self.drop(si, c, f"insert shorter than {INSERT[0]}s")
            elif face and c.params.get("kind") in SPLIT_KINDS and gap >= SPLIT_GAP and self.has_face(si):
                c.params["layout"] = "split"        # v2: the face stays on screen under the card (face track)
                self.notes.append(f"council: {c.params['kind']} card in {self.s.shots[si].id!r} goes split ({face})")
            elif face:
                self.drop(si, c, face)
            else:
                kept.append((a, b))
        cap = self.pace["broll"] * self.T
        rank = {"stat": 0, "list": 1, "text": 2}
        order = sorted(self.autos("broll"), key=lambda x: (rank.get(x[1].params.get("kind"), 3), self.t(x[0], x[1].start_word)))
        used = sum(b - a for sh_i, sh in enumerate(self.s.shots) for c in sh.cues
                   if c.type in ("broll", "cutaway") and not c.params.get("auto") for a, b in [self.span(sh_i, c)])
        for si, c in order:
            a, b = self.span(si, c)
            if c.params.get("layout") == "split":     # the face stays on screen: not face-off time
                continue
            if used + (b - a) > cap + 1e-6:
                self.drop(si, c, f"B-roll cap {self.pace['broll']:.0%} of runtime")
            else:
                used += b - a
        for si, c in [x for x in self.autos("broll") if x[1].params.get("kind") == "stat"][1:]:   # <= 1 stat, kept ones
            c.params.update(kind="text", text=presets.card_case(
                f"{c.params.get('value', '')} {c.params.get('label', '')}".strip(), card["case"], self.s.shots[si].line))
        broll_media.enforce(self, media)

    def transitions(self) -> None:
        """Family per preset, 9 frames, count by runtime; never into a shot that opens on an insert
        (two changes in a few frames): such a transition moves to a free section boundary or drops."""
        every = self.pace["tx_every"]
        n = 0 if every is None or self.name not in TX_FAMILY else min(3, int(self.T // every))
        fam = TX_FAMILY.get(self.name)

        def free(si: int) -> bool:
            cut = self.tl.shots[si].out_start
            return self.auto_ok(si, "transition") and not any(
                c.type in ("broll", "cutaway") and self.span(si, c)[0] < cut + 1.0 for c in self.s.shots[si].cues) \
                and not any(c.type == "transition" for c in self.s.shots[si].cues)
        for k, (si, c) in enumerate(self.autos("transition")):
            if k >= n:
                self.drop(si, c, f"auto transitions capped at {n} for {self.T:.1f}s")
                continue
            c.params["id"], c.params["ms"] = fam, TX_MS
            c.params["params"] = {"dir": c.params.get("params", {}).get("dir", [1, 0])} if fam == "whip" else {}
            self.s.shots[si].cues.remove(c)
            ok = free(si)
            self.s.shots[si].cues.append(c)
            if ok:
                continue
            to = next((j for j in sorted(range(1, len(self.s.shots)), key=lambda j: abs(j - si)) if free(j)), None)
            whoosh = [x for x in self.s.shots[si].cues if x.type == "sfx" and x.params.get("role") == "whoosh"
                      and x.params.get("auto")]
            if to is None:
                self.drop(si, c, "its shot opens on an insert and no other boundary is free")
                continue
            for x in [c] + whoosh:
                self.s.shots[si].cues.remove(x)
                x.start_word = x.end_word = 0
                self.s.shots[to].cues.append(x)
            self.notes.append(f"council: moved auto transition from {self.s.shots[si].id!r} to "
                              f"{self.s.shots[to].id!r} (insert at the cut)")

    def punches(self) -> None:
        """Open at M (frame 0), first change 0.5-1.0 s, levels always change, <= 1 T, last frame = M (beats.py)."""
        beats.punches(self)

    def changes(self) -> list[float]:
        """Instant picture changes: jump cuts, shot cuts, visible punches, insert in/out (2-frame merge)."""
        ts = [c for c in self.jump_cuts()] + [p.out_start for p in self.tl.shots[1:]]
        for si, sh in enumerate(self.s.shots):
            for c in sh.cues:
                if c.type == "punch" and not c.params.get("open") and not self.punch_off(si):
                    t = self.pt(si, c)
                    if not self.under_insert(t):
                        ts.append(t)
                elif c.type in ("broll", "cutaway"):
                    ts.extend(self.span(si, c))
                    ts += [self.t(si, int(c.params["beat"]))] if c.params.get("beat") is not None else []
        out: list[float] = []
        for t in sorted(t for t in ts if 0 < t < self.T):
            if not out or t - out[-1] > 2 * FRAME + 1e-6:
                out.append(t)
        return out

    def under_insert(self, t: float) -> bool:
        return any(c.type in ("broll", "cutaway") and self.span(si, c)[0] <= t <= self.span(si, c)[1]
                   for si, sh in enumerate(self.s.shots) for c in sh.cues)

    def levels(self, again: bool = True) -> None:
        """Each shot starts at W (shot 0 at M); consecutive punches always change level; at most one T
        (two over 45 s), entered from W; the last punch of the reel lands on M (loop = frame 0). A payoff punch
        that would land on W gets a W breath before it (beats.payoff) rather than being dropped."""
        t_left = 2 if self.T > 45 else 1
        li = max((si for si, sh in enumerate(self.s.shots) if any(c.type == "punch" for c in sh.cues)), default=None)
        if li not in (None, 0) and self.auto_ok(li, "punch"):
            sh = self.s.shots[li]
            for c in [c for c in sh.cues if c.type == "punch" and c.params.get("parity")]:
                sh.cues.remove(c)            # re-decided on every call: a re-plan may have changed the run
            if not any(c.type == "punch" and (c.params.get("open") or not c.params.get("auto")) for c in sh.cues) \
                    and sum(1 for c in sh.cues if c.type == "punch") % 2 == 0:
                # an even run from W would end on W: open the last shot at M on its cut (no extra change)
                self.add(li, "punch", 0, "last frame matches frame 0 (M)", level="M", open=True, parity=True)
        allp = []
        for si, sh in enumerate(self.s.shots):
            ps = sorted((c for c in sh.cues if c.type == "punch"), key=lambda c: (not c.params.get("open"),
                                                                                 self.pt(si, c)))
            allp.append(ps)
        for si, ps in enumerate(allp):
            cur = "W"
            for c in ps:
                lvl = str(c.params.get("level", "M")).upper()
                if not c.params.get("auto"):
                    cur = lvl
                    continue
                if c.params.get("open"):
                    cur = c.params["level"] = "M"
                    continue
                if lvl == "T" and cur == "W" and t_left > 0:
                    t_left -= 1
                else:
                    lvl = "W" if cur != "W" else "M"
                c.params["level"] = cur = lvl
        last = next((ps for ps in reversed(allp) if ps), None)
        if last and last[-1].params.get("auto") and last[-1].params["level"] != "M":
            prev = last[-2].params["level"] if len(last) > 1 else "W"
            si = allp.index(last)
            if prev != "M":
                last[-1].params["level"] = "M"
            elif last[-1].params.get("payoff") and again and beats.breath(self, si, last[-1]):
                self.levels(False)
            else:
                self.drop(si, last[-1], "last frame matches frame 0 (M)")

    def sfx(self) -> None:
        for si, c in self.autos("broll"):      # every kept card enters with a pop (tier 3), the stat with its count-up
            role = "ding" if c.params.get("kind") == "stat" else "pop"
            if self.auto_ok(si, "sfx") and not any(
                    x.type == "sfx" and x.start_word == c.start_word for x in self.s.shots[si].cues):
                self.add(si, "sfx", c.start_word, f"{role} as the B-roll card enters (SD 5)", id=SFX_IDS[role],
                         role=role, level_db=-12.0 if role == "ding" else -14.0, on="lead")
        for si, c in self.autos("sfx"):        # a pop or ding with no kept card entering on its word goes
            if (c.params.get("on") == "lead" or c.params.get("role") == "ding") and not any(
                    x.type == "broll" and x.start_word == c.start_word for x in self.s.shots[si].cues):
                self.drop(si, c, "no kept B-roll card enters on its word")
        hook = HOOK_HIT.get(self.name, "snd.hit.soft")
        txs = {si: c.params["id"] for si, c in self.autos("transition")}
        for si, c in self.autos("sfx"):
            role = c.params.get("role")
            if role == "hook":
                c.params["id"] = hook
            elif role == "whoosh":
                fam = txs.get(si)
                if fam is None:
                    self.drop(si, c, "its transition was dropped")
                    continue
                c.params["id"] = SFX_IDS.get(fam, c.params["id"])
            elif role in SFX_IDS:
                c.params["id"] = SFX_IDS[role]
        punch_t = [self.pt(si, c) for si, sh in enumerate(self.s.shots) for c in sh.cues   # a punch under a card
                   if c.type == "punch" and not c.params.get("open") and not self.under_insert(self.pt(si, c))]  # is unseen
        hits = self.jump_cuts() + punch_t
        cap = max(1, int(self.pace["sfx30"] * self.T / 30))
        cand = sorted(self.autos("sfx"), key=lambda x: (SFX_RANK.get(x[1].params.get("role"), 9),
                                                        self.t(x[0], x[1].start_word)))
        kept: list[tuple[float, str, int, Cue | None]] = [
            (self.t(si, c.start_word), c.params.get("id") or c.params.get("src", ""), si, None)
            for si, sh in enumerate(self.s.shots) for c in sh.cues if c.type == "sfx" and not c.params.get("auto")]
        for si, c in cand:
            role = c.params.get("role")
            t = self.tl.shots[si].out_start if role == "whoosh" else self.t(si, c.start_word)
            if c.params.get("on") == "lead":          # a card's sound sits on the card's own first frame
                t = card_in(self.tl.shots[si].out_start, t, round(1 / FRAME), round(LEAD / FRAME))
            if t > self.T - 0.5:
                self.drop(si, c, "no SFX in the last 0.5 s")
            elif role not in ("hook", "whoosh") and any(abs(t - h) <= FRAME + 1e-6 for h in hits):
                self.drop(si, c, "only the hook hit may sit on a jump cut or punch")
            elif any(abs(t - k[0]) < 1.0 for k in kept):
                self.drop(si, c, "SFX >= 1.0 s apart")
            elif len(kept) >= cap:
                self.drop(si, c, f"SFX cap {self.pace['sfx30']} per 30 s")
            else:
                kept.append((t, c.params["id"], si, c))
        no_repeats(self, kept, SFX_IDS["pop"], SFX_IDS["pop_alt"] if self.name in HOOK_HIT else None)

    def emphasis(self) -> None:
        total = sum(len(sh.words) for sh in self.s.shots)
        cap = max(1, int(EMPH_SHARE * total))
        have = sum(1 for sh in self.s.shots for c in sh.cues if c.type == "emphasis" and not c.params.get("auto"))
        for si, c in sorted(self.autos("emphasis"), key=lambda x: not x[1].params.get("payoff")):   # payoff first
            if have >= cap:
                self.drop(si, c, f"<= {EMPH_SHARE:.0%} of words highlighted")
            else:
                have += 1

    def music(self) -> None:
        m = self.s.music
        if isinstance(m, dict) and not m.get("off"):
            m.setdefault("duck_db", 10.0)       # council 9: duck 10 dB, voice >= 15 LU over the bed
            m.setdefault("level_lu", -5.0)
            ids = pack_ids()
            beds = [b for b in self.style.get("music_beds") or [] if not ids or b in ids[2]]
            if m.get("auto") and not (m.get("id") or m.get("src")) and beds and self.T <= 32.0:
                m["id"] = beds[0]               # the preset's own first bed (loop beds only up to 32 s)

    def validate(self) -> None:
        ids = pack_ids()
        for sh in self.s.shots:
            for c in sh.cues:
                if c.type == "sfx" and c.params.get("id") and ids and c.params["id"] not in ids[0]:
                    raise ScriptError(f"shot {sh.id!r}: unknown sfx id {c.params['id']!r}")

    def run(self) -> Script:
        for step in (self.simple, self.title, self.broll, self.transitions, self.punches,
                     lambda: broll_media.pace_fit(self, replan),    # the enforced pace gate (P3), media edges (v4)
                     lambda: broll_flow.split_flow(self),            # no split -> face -> split jump (v4 final)
                     self.sfx, self.emphasis, self.music, self.validate):
            step()
        for sh in self.s.shots:
            sh.cues.sort(key=lambda c: (c.start_word, c.type, c.end_word))
        return self.s


def enforce(directed: Script, tl, notes: list | None = None) -> Script:
    """Council caps on a directed script; `tl` = build_timeline(directed, takes). The final pace note
    (the same formula as metrics()) replaces the director's estimate, so the two never disagree."""
    notes = notes if notes is not None else []
    out = _Pass(directed, tl, notes).run()
    notes[:] = [n for n in notes if not n.startswith(("pace:", "director plan pace:"))]
    notes.append(pace_note(_Pass(out, tl, []).changes()))
    return out
