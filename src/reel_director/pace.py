"""One pace formula for the director's plan, the council pass and the reports (council 2).

Rhythm (median gap, CV) is measured BETWEEN visual changes: the lead-in before the first change and
the tail after the last one are not intervals of the edit, so counting them hid a metronomic cut
(0.57 s lead-in reported CV 0.36 for a 0.22 edit). Max static still counts both ends: a frozen
opening or ending is a static stretch the viewer sees.

The pace gate is enforced (v2 contract P3): when the rhythm is metronomic (CV < 0.25) or the median gap
leaves the pace's range, replan() re-plans the auto punches (move one to another word, add a clustered
one, or drop one, the best-scoring change first, deterministic) until the gate passes or no change helps;
gate() then reports level "fail", which blocks "great" (Studio / QA show it).
"""
import statistics

CV_FAIL, CV_TARGET, CV_MAX = 0.25, 0.35, 0.75
MEDIAN_FLOOR = 0.6         # a clustered punch never pulls the median gap under 0.6 x the pace median
MEDIAN_RANGE = {"calm": (2.4, 6.0), "standard": (1.9, 3.5), "punchy": (1.3, 2.4)}   # council 2 medians +- EP P1
MIN_SEP, SNAP_CUT, REPLAN_ROUNDS = 0.6, 0.7, 8    # s between a re-planned punch and any change / a jump cut


def gaps_between(changes: list[float]) -> list[float]:
    ch = sorted(changes)
    return [b - a for a, b in zip(ch, ch[1:])]


def pace_cv(changes: list[float]) -> float:
    g = gaps_between(changes)
    return statistics.pstdev(g) / statistics.mean(g) if len(g) > 1 and statistics.mean(g) > 0 else 0.0


def pace_note(changes: list[float]) -> str:
    g = gaps_between(changes)
    med = statistics.median(g) if g else 0.0
    cv = pace_cv(changes)
    return (f"pace: {len(changes)} visual changes, median gap {med:.2f} s, CV {cv:.2f} (between changes)"
            + (f" (metronomic: under {CV_FAIL})" if cv < CV_FAIL else ""))


def metrics(s, tl) -> dict:
    """The council's pace numbers for one reel (visual changes, B-roll share, SFX, transitions)."""
    from .policy import _Pass
    P = _Pass(s, tl, [])
    ch = P.changes()
    g = gaps_between(ch)
    ends = [b - a for a, b in zip([0.0] + ch, ch + [tl.duration])]
    br = sum(b - a for si, sh in enumerate(s.shots) for c in sh.cues if c.type in ("broll", "cutaway")
             and c.params.get("layout", "full") == "full" for a, b in [P.span(si, c)])   # split/pip keep the face
    on = sum(b - a for si, sh in enumerate(s.shots) for c in sh.cues if c.type in ("broll", "cutaway")
             for a, b in [P.span(si, c)])                               # every layout: what the viewer sees (v4 panel)
    tx = sum(1 for sh in s.shots for c in sh.cues if c.type == "transition")
    cuts = len(ch)          # every instant picture change is a cut; a transition replaces one
    return {"duration": round(tl.duration, 3), "visual_changes": len(ch),
            "median_gap_s": round(statistics.median(g), 2) if g else round(tl.duration, 2),
            "cv": round(pace_cv(ch), 2), "max_static_s": round(max(ends), 2) if ends else None,
            "first_change_s": round(ch[0], 2) if ch else None, "changes_by_3s": sum(1 for t in ch if t <= 3.0),
            "broll_share": round(br / tl.duration, 3) if tl.duration else 0.0,      # face-off (the council's cap)
            "broll_on_screen": round(on / tl.duration, 3) if tl.duration else 0.0,
            "transitions": tx, "cuts": cuts, "hard_cut_share": round(1 - tx / cuts, 3) if cuts else 1.0,
            "sfx": sum(1 for sh in s.shots for c in sh.cues if c.type == "sfx"), "pace_gate": gate_of(P),
            "punches_off": sorted({sh.id for si, sh in enumerate(s.shots) if P.punch_off(si)}),
            "punches": [[sh.id, c.params.get("level"), round(P.pt(si, c), 2)]
                        for si, sh in enumerate(s.shots) for c in sh.cues if c.type == "punch"]}


def cluster(self) -> None:
    """EP P2 / council 2 (CV 0.35-0.75, < 0.25 fails): an even run of changes gets one clustered punch,
    0.7-1.0 s after a change, on the word that lifts the between-change CV most, as long as the median gap
    stays >= 0.6 x the pace's median. `self` is the council pass (policy._Pass); it runs after fill_static
    and before levels."""
    for _ in range(1):
        ch = self.changes()
        if len(ch) < 3 or pace_cv(ch) >= CV_TARGET:
            return
        best = None
        for si, p in enumerate(self.tl.shots):
            if not self.auto_ok(si, "punch") or self.punch_off(si):
                continue
            for wi, w in enumerate(p.words):
                near = min(abs(w.start - t) for t in ch)
                after = min((w.start - t for t in ch if t < w.start), default=9.0)
                if 0.7 - 1e-6 <= after <= 1.0 + 1e-6 and near >= 0.7 - 1e-6 and 1.0 < w.start < self.T - 2.5 \
                        and not self.under_insert(w.start) and not any(
                        x.type == "punch" and x.start_word == wi for x in p.shot.cues):
                    cv = pace_cv(ch + [w.start])
                    if statistics.median(gaps_between(ch + [w.start])) < MEDIAN_FLOOR * self.pace["median"]:
                        continue
                    if best is None or cv > best[0] + 1e-9:
                        best = (cv, si, wi)
        if best is None or best[0] <= pace_cv(ch) + 0.02:
            return
        self.add(best[1], "punch", best[2], f"clustered change, CV {pace_cv(ch):.2f} -> {best[0]:.2f}", level="W")


def no_repeats(P, kept: list, pop: str, alt: str | None) -> None:
    """Council 8 (no repeats): an SFX identical to the one before it is dropped. With `alt` (the energetic
    presets), a repeated card pop switches to the tier-3 variant `alt` instead, so a run of cards keeps its
    pops (sound-music 4: pop on every card entrance) without the same sample twice in a row."""
    prev = None
    for _, sid, si, c in sorted(kept, key=lambda k: k[0]):
        if c is not None and sid == prev == pop and alt:
            sid = c.params["id"] = alt
        if sid == prev and c is not None and c in P.s.shots[si].cues:
            P.drop(si, c, "no repeated SFX")
            continue
        prev = sid


# ---- the enforced pace gate (contract P3) ---------------------------------------------------------
def _range(P) -> tuple[float, float]:
    return MEDIAN_RANGE.get(P.s.style.get("pace", "standard"), MEDIAN_RANGE["standard"])


def gate_of(P) -> dict:
    """QA-format gate: fail when CV < 0.25 or the median gap is outside the pace's range (>= 3 gaps)."""
    ch = P.changes()
    g, (lo, hi) = gaps_between(ch), _range(P)
    cv, med = round(pace_cv(ch), 2), round(statistics.median(g), 2) if g else None
    val, tgt = {"cv": cv, "median_gap_s": med, "visual_changes": len(ch)}, {"cv": [CV_TARGET, CV_MAX], "median_gap_s": [lo, hi]}
    if len(g) < 3:
        return {"id": "pace", "level": "ok", "value": val, "target": tgt, "fix": None,
                "message": f"{len(ch)} visual changes: too few to measure a rhythm"}
    bad = ([f"CV {cv:.2f} under {CV_FAIL} (metronomic)"] if cv < CV_FAIL else []) + \
        ([f"median gap {med:.2f}s outside {lo}-{hi}s"] if not lo - 1e-9 <= med <= hi + 1e-9 else [])
    level = "fail" if bad else "warn" if not CV_TARGET <= cv <= CV_MAX else "ok"
    msg = "; ".join(bad) if bad else f"CV {cv:.2f}, median gap {med:.2f}s" + ("" if level == "ok" else " (CV outside 0.35-0.75)")
    fix = "pace re-plan found no better punch layout: record a longer take or add a B-roll beat" if bad else None
    return {"id": "pace", "level": level, "value": val, "target": tgt, "message": msg, "fix": fix}


def _penalty(P) -> float:
    """Lower is better: the gate (CV, median) plus the council's hard pace rules, which a re-plan never breaks."""
    ch = P.changes()
    g, (lo, hi) = gaps_between(ch), _range(P)
    if len(g) < 2:
        return 0.0
    cv, med = pace_cv(ch), statistics.median(g)
    ends = [b - a for a, b in zip([0.0] + ch, ch + [P.T])]
    return (100 * max(0.0, CV_FAIL - cv) + 10 * max(0.0, CV_TARGET - cv) + 10 * max(0.0, cv - CV_MAX)
            + 50 * max(0.0, lo - med, med - hi) + 200 * max(0.0, max(ends) - P.pace["max_static"])
            + 200 * (ch[0] > 1.0 + 1e-6) + 200 * (sum(1 for t in ch if t <= 3.0) < 2))


def _free(P, t: float, others: list[float]) -> bool:
    return (0.5 - 1e-6 <= t <= P.T - 0.5 and not P.under_insert(t) and all(abs(t - x) >= MIN_SEP - 1e-6 for x in others)
            and all(abs(t - j) >= SNAP_CUT - 1e-6 for j in P.jump_cuts()))


def _candidates(P):
    """(penalty, order, apply) for every single re-plan step, evaluated in place and undone."""
    out = []
    movable = [(si, c) for si, c in P.autos("punch") if not c.params.get("open") and not c.params.get("on")
               and not c.params.get("payoff")
               and str(c.params.get("level", "M")).upper() != "T" and not (si == 0 and P.pt(si, c) <= 1.0 + 1e-6)]
    for si, c in movable:
        cues, w0 = P.s.shots[si].cues, c.start_word
        cues.remove(c)
        ch = P.changes()
        out.append((_penalty(P), (2, P.t(si, w0), si, w0), ("drop", si, c, None)))
        for wi, w in enumerate(P.tl.shots[si].words):
            if wi != w0 and _free(P, w.start, ch) and not any(x.type == "punch" and x.start_word == wi for x in cues):
                c.start_word = c.end_word = wi
                cues.append(c)
                out.append((_penalty(P), (0, P.t(si, w0), si, wi), ("move", si, c, wi)))
                cues.remove(c)
        c.start_word = c.end_word = w0
        cues.append(c)
    ch = P.changes()
    for si, p in enumerate(P.tl.shots):
        if not P.auto_ok(si, "punch") or P.punch_off(si):
            continue
        for wi, w in enumerate(p.words):
            if _free(P, w.start, ch) and not any(x.type == "punch" and x.start_word == wi for x in P.s.shots[si].cues):
                c = P.add(si, "punch", wi, "pace re-plan", level="W")
                out.append((_penalty(P), (1, w.start, si, wi), ("add", si, c, wi)))
                P.s.shots[si].cues.remove(c)
    return out


def replan(P) -> dict:
    """Contract P3: re-plan the auto punches until the pace gate passes (or nothing improves), then
    restore the council's level rules; the final gate is noted and returned."""
    before = gate_of(P)
    if before["level"] != "fail":
        return before
    for _ in range(2):
        for _ in range(REPLAN_ROUNDS):
            base = _penalty(P)
            if gate_of(P)["level"] != "fail" and base < 1e-9:
                break
            cands = _candidates(P)
            if not cands:
                break
            pen, _, (op, si, c, wi) = min(cands, key=lambda x: (x[0], x[1]))
            if pen >= base - 1e-6:
                break
            t0 = P.pt(si, c) if op != "add" else None
            if op == "drop":
                P.drop(si, c, "pace re-plan: an even run of changes")
                continue
            if op == "add":
                P.s.shots[si].cues.append(c)
            c.start_word = c.end_word = wi
            c.params["why"] = "council: pace re-plan (CV / median gap)"
            P.notes.append(f"council: pace re-plan {op} auto punch in {P.s.shots[si].id!r} "
                           + (f"{t0:.2f}s -> " if t0 is not None else "at ") + f"{P.t(si, wi):.2f}s (penalty {base:.1f} -> {pen:.1f})")
        from . import beats
        P.levels()
        if beats.same_level_cuts(P):
            P.levels()
        beats.hard_share(P)
        if gate_of(P)["level"] != "fail":
            break
    after = gate_of(P)
    P.notes.append(f"pace gate: {after['level'].upper()} after re-plan: {before['message']} -> {after['message']}")
    return after
