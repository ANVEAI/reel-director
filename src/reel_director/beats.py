"""Punch beats of the council pass (policy._Pass): where the auto punches land and at which level.

Moved out of policy.py (file-size rule) and extended by the real-1 review:
- payoff(): the reel's last phrase ('builds itself.') owns the last punch (CD: the payoff had no beat; bold-hustle's
  punch sat inside the split pane), its last word takes the caption emphasis, and levels() lands it on M, the
  frame-0 level, so the loop closes where it opened.
Rules otherwise as before: open at M (frame 0), first change 0.5-1.0 s, >= 2 changes by 3 s, no static stretch
over the pace's max, one clustered change for rhythm, levels always change, no same-level cut < 1.2 s apart,
hard cuts >= 90 %. `P` is the council pass; nothing here reads a clock or a random source.
"""
from .pace import cluster
from .stagger import dangles

SNAP, HARD_SHARE_TX, FRAME, PAYOFF_SEP = 0.7, 0.10, 1 / 30, 0.6
HOLD_TO, CARD_MAX = 1.2, {"split": 6.0, "pip": 6.0}   # a card out this close before a punch holds to it; split cap


def punches(P) -> None:
    for si, c in P.autos("punch"):
        if si == 0 and P.t(si, c.start_word) < 0.5 - 1e-6:
            P.drop(si, c, "first punch lands at 0.5-1.0 s")
    if P.s.shots and P.auto_ok(0, "punch"):
        if not any(c.type == "punch" and c.params.get("open") for c in P.s.shots[0].cues):
            P.add(0, "punch", 0, "opens at M on frame 0 (council 3)", level="M", open=True)
        if not any(0.5 - 1e-6 <= P.t(si, c.start_word) <= 1.0 + 1e-6 for si, c in P.autos("punch")
                   if not c.params.get("open")):
            w = next((k for k, x in enumerate(P.tl.shots[0].words) if 0.5 <= x.start <= 1.0), None)
            if w is not None:
                P.add(0, "punch", w, "first visual change by 1.0 s (H2)", level="W")
    payoff(P)
    snap(P)
    early(P)
    fill_static(P)
    cluster(P)
    hold_cards(P)
    P.levels()
    if same_level_cuts(P):
        P.levels()
    hard_share(P)


def hold_cards(P) -> None:
    """A card whose out lands < HOLD_TO s before a punch in its shot holds until that punch: the face comes back ON
    the punch, one change instead of two 0.9 s apart (CD: the payoff beat; HQ: pace). Never past the card's cap."""
    from .policy import INSERT, TEXT_MAX
    for si, c in P.autos("broll"):
        a, b = P.span(si, c)
        nxt = min(((P.pt(si, x), x.start_word) for x in P.s.shots[si].cues if x.type == "punch"
                   and not x.params.get("open") and P.pt(si, x) > b - 1e-6), default=None)
        if nxt is None or nxt[0] - b >= HOLD_TO or nxt[1] - 1 <= c.end_word:
            continue
        top = CARD_MAX.get(c.params.get("layout"), TEXT_MAX if c.params.get("kind") == "text" else INSERT[1])
        e0, c.end_word = c.end_word, nxt[1] - 1
        if P.span(si, c)[1] - a > top + 1e-6:
            c.end_word = e0
            continue
        c.params.pop("to_cut", None)
        P.notes.append(f"council: {c.params.get('kind')} card in {P.s.shots[si].id!r} holds to the punch at "
                       f"{nxt[0]:.2f}s (face returns on the beat)")


def payoff_word(P, li: int) -> tuple[int, int] | None:
    """(punch word, emphasis word) of the last shot's final phrase: the last two words of its last clause, the
    punch on the first content word of them ('builds'), the emphasis on the last ('itself.')."""
    texts = [w.text for w in P.s.shots[li].words]
    if len(texts) < 2:
        return None
    k, j = len(texts) - 1, len(texts) - 1
    while j > 0 and texts[j - 1][-1:] not in ".!?,;:":
        j -= 1
    wi = max(j, k - 1)
    while wi < k and dangles(texts[wi]):
        wi += 1
    return wi, k


def payoff(P) -> None:
    li = len(P.s.shots) - 1
    if li < 0 or not P.auto_ok(li, "punch") or P.punch_off(li):
        return
    pw = payoff_word(P, li)
    if pw is None:
        return
    wi, ki = pw
    t = P.t(li, wi)
    if P.under_insert(t) or t > P.T - 0.6 or t < P.tl.shots[li].out_start + 0.3:
        return
    for c in [c for c in P.s.shots[li].cues if c.type == "punch" and c.params.get("auto") and not c.params.get("open")]:
        ct = P.pt(li, c)
        if P.under_insert(ct) or ct > t - PAYOFF_SEP:
            P.drop(li, c, "the payoff punch owns the last beat (lost under a card or crowding it)")
    if not any(c.type == "punch" and c.start_word == wi for c in P.s.shots[li].cues):
        P.add(li, "punch", wi, "payoff beat on the last phrase, back on the frame-0 level (CD review)", level="M",
              payoff=True)
    if P.auto_ok(li, "emphasis"):
        for c in [c for c in P.s.shots[li].cues if c.type == "emphasis" and c.params.get("auto")]:
            P.s.shots[li].cues.remove(c)         # one highlight per chunk: the payoff word wins its chunk
        P.add(li, "emphasis", ki, "payoff word takes the highlight (CD review)", payoff=True)


def breath(P, si: int, pay) -> bool:
    """The payoff shot sits on M before its payoff punch (it opened there): add a W punch on a free word between the
    last change and the payoff, so the payoff still punches in and the reel ends on M. False when there is no room."""
    t1 = P.pt(si, pay) - PAYOFF_SEP
    t0 = max([x for x in P.changes() if x < t1] + [P.tl.shots[si].out_start]) + PAYOFF_SEP
    w = next((k for k, x in enumerate(P.tl.shots[si].words) if t0 - 1e-6 <= x.start <= t1 + 1e-6
              and not P.under_insert(x.start)), None)
    if w is None:
        return False
    P.add(si, "punch", w, "W breath before the payoff punch", level="W")
    return True


def snap(P) -> None:
    """A punch within SNAP s of a jump cut moves onto the cut (EP J2: the level change hides the
    jump), so the two never land a few frames apart."""
    cuts = sorted(P.jump_cuts())
    for si, c in P.autos("punch"):
        if c.params.get("open") or c.params.get("on") == "cut" or c.params.get("payoff"):
            continue
        t = P.t(si, c.start_word)
        near = [k for k in cuts if abs(k - t) <= SNAP and P.tl.shots[si].out_start < k]
        if not near or (si == 0 and 0.5 <= t <= 1.0):
            continue
        k = min(near, key=lambda x: abs(x - t))
        wi = next((j for j, w in enumerate(P.tl.shots[si].words) if w.start >= k - 1e-6), None)
        if wi is None or any(x.type == "punch" and x is not c and x.start_word == wi for x in P.s.shots[si].cues):
            P.drop(si, c, "a punch already sits on that jump cut")
            continue
        c.start_word = c.end_word = wi
        c.params["on"] = "cut"


def early(P) -> None:
    """Council 2: at least 2 picture changes by 3.0 s (hook pace): add a punch 0.8 s after the first."""
    ch = [t for t in P.changes() if t <= 3.0]
    if len(ch) >= 2:
        return
    lo = (ch[0] if ch else 0.5) + 0.8
    for si, p in enumerate(P.tl.shots):
        if not P.auto_ok(si, "punch"):
            continue
        w = next((k for k, x in enumerate(p.words) if lo <= x.start <= 3.0 and not P.under_insert(x.start)), None)
        if w is not None:
            P.add(si, "punch", w, ">= 2 picture changes by 3 s (council 2)", level="W")
            return


def same_level_cuts(P) -> bool:
    """Council 2 (no same-level cuts < 1.2 s apart), extended to every cut between two face shots (founder review:
    a same-scale cut between takes reads as a camera jump): such a shot opens on M (an 'open' punch adds no change;
    layout._continuity then keeps the eyes where they were). A shot that opens on a card is exempt."""
    added = False
    for i in range(1, len(P.s.shots)):
        sh, cut = P.s.shots[i], P.tl.shots[i].out_start
        if not P.auto_ok(i, "punch") or any(c.type == "transition" or c.type == "punch" and (
                c.params.get("open") or not c.params.get("auto") or P.pt(i, c) < cut + 0.5) for c in sh.cues) \
                or any(c.type in ("broll", "cutaway") and P.span(i, c)[0] <= cut + 2 * FRAME for c in sh.cues):
            continue
        prev = sorted((c for c in P.s.shots[i - 1].cues if c.type == "punch"), key=lambda c: P.pt(i - 1, c))
        end = prev[-1].params.get("level", "M") if prev else "MW"[i > 1]
        if end == "W":
            added = bool(P.add(i, "punch", 0, "no same-level cut < 1.2 s apart (council 2)", level="M", open=True))
    return added


def hard_share(P) -> None:
    """>= 90% of picture changes are hard cuts: drop auto transitions (latest first) until true."""
    tx = P.autos("transition")
    while tx:
        n_tx = sum(1 for sh in P.s.shots for c in sh.cues if c.type == "transition")
        if n_tx <= HARD_SHARE_TX * len(P.changes()) + 1e-9:
            return
        si, c = tx.pop()
        P.drop(si, c, f"hard cuts must stay >= 90% ({len(P.changes())} picture changes)")


def fill_static(P) -> None:
    """Add a punch in the middle of any face stretch longer than the pace's max static."""
    for _ in range(12):
        ch = [0.0] + P.changes() + [P.T]
        gaps = [(b - a, a, b) for a, b in zip(ch, ch[1:]) if b - a > P.pace["max_static"]]
        if not gaps:
            return
        _, a, b = max(gaps)
        mid = (a + b) / 2
        best = None
        for si, p in enumerate(P.tl.shots):
            if not P.auto_ok(si, "punch"):
                continue
            for wi, w in enumerate(p.words):
                if a + 0.8 <= w.start <= b - 0.8 and not P.under_insert(w.start):
                    if best is None or abs(w.start - mid) < abs(best[2] - mid):
                        best = (si, wi, w.start)
        if best is None:
            P.notes.append(f"council: static {b - a:.1f}s at {a:.1f}s has no word to punch on")
            return
        P.add(best[0], "punch", best[1], f"max static {P.pace['max_static']}s", level="W")
