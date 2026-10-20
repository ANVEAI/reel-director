"""Split-layout flow for real-media inserts (v4 final round, panel review of the founder's reel).

grow(P, si, c, payoff_t): a split insert keeps the face on screen, so the recipe's insert length (written for face-off
  cutaways, e.g. 1.2-1.5 s in retention-classic) does not bind it: it may run to the contract's 3.0 s, word by word,
  never onto a number, the checklist's enumeration or the payoff, and >= 0.5 s clear of other inserts.
split_flow(P): founder: no split -> full face -> split jump with less than FACE_GAP (1.5 s) of face between. A split
  media insert that ends closer than that to the next split card runs on to it when that card opens the next shot
  (one continuous split, to the cut; the clip's last frame holds, treatments.timing), else it ends FACE_GAP before
  the card (>= 1.2 s), else it drops. A bridged run longer than the preset's max static gets a beat word near its
  middle (the picture punches in there: a visible change, broll.mjs). Deterministic; idempotent.
"""
from . import lexicon as lx

INSERT = (1.2, 3.0)
FACE_GAP = 1.5
CLEAR = 0.5                 # s between inserts (broll_media.enforce's crowd rule)


def _others(P, c) -> list[tuple[float, float]]:
    return [P.span(i, k) for i, sh in enumerate(P.s.shots) for k in sh.cues if k.type in ("broll", "cutaway") and k is not c]


def grow(P, si: int, c, payoff_t: float, top: float = INSERT[1]) -> None:
    texts = [w.text for w in P.s.shots[si].words]
    nums, items = lx.number_phrases(texts), lx.enumeration(texts) or []
    others = _others(P, c)
    while c.end_word + 1 < len(texts):
        k = c.end_word + 1
        if any(x <= k <= y for x, y in nums) or (len(items) >= 2 and items[0][0] <= k <= items[-1][1]):
            return
        c.end_word = k
        a, b = P.span(si, c)
        if b - a > top + 1e-6 or b > payoff_t + 1e-6 or any(a < q + CLEAR and p < b + CLEAR for p, q in others):
            c.end_word = k - 1
            return


def _splits(P) -> list[tuple[float, float, int, object]]:
    out = [(*P.span(si, c), si, c) for si, sh in enumerate(P.s.shots) for c in sh.cues
           if c.type == "broll" and c.params.get("layout") == "split"]
    return sorted(out, key=lambda x: (x[0], x[2]))


def split_flow(P) -> None:
    for a, b, si, c in _splits(P):
        if c.params.get("kind") != "media" or not c.params.get("auto"):
            continue
        nxt = next(((a2, sj) for a2, _, sj, k in _splits(P) if k is not c and a2 > a + 1e-6), None)
        if nxt is None or not 1e-3 < nxt[0] - b < FACE_GAP - 1e-6:
            continue
        a2, sj = nxt
        p, sid = P.tl.shots[si], P.s.shots[si].id
        cut, last = p.out_start + p.duration, len(P.s.shots[si].words) - 1
        if sj == si + 1 and abs(a2 - cut) < 0.1:
            c.end_word = last
            c.params.update(to_cut=True, hold=round(cut - P.t(si, last, True) + 0.05, 3), bridge=True)
            c.params.pop("beat", None)
            x, y = P.span(si, c)
            if y - x > float(P.pace.get("max_static", 4.0)) - 1e-6:
                mid = (x + y) / 2
                ks = [k for k in range(c.start_word + 1, last + 1) if x + 1.0 <= P.t(si, k) <= y - 0.6]
                if ks:
                    c.params["beat"] = min(ks, key=lambda k: (abs(P.t(si, k) - mid), k))
            P.notes.append(f"council: media in {sid!r} runs on to the next split at {a2:.2f}s (one continuous split: "
                           f"{a2 - b:.2f}s of face between would jump; founder){' with a beat' if 'beat' in c.params else ''}")
            continue
        while c.end_word > c.start_word and a2 - P.span(si, c)[1] < FACE_GAP - 1e-6:
            c.end_word -= 1
            c.params.pop("to_cut", None)
        x, y = P.span(si, c)
        if a2 - y < FACE_GAP - 1e-6 or y - x < INSERT[0] - 1e-6:
            P.drop(si, c, f"split card at {a2:.2f}s: no room for {FACE_GAP}s of face before it")
        else:
            P.notes.append(f"council: media in {sid!r} ends {FACE_GAP}s before the next split card (no face jump)")
