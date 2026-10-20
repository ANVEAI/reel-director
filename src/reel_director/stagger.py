"""Caption timing rules the compiler applies on top of the word times (council 6, CG 7).

- Chunking (craft_chunks, captions-visual rules 2.1): 2-4 words (1-2 for hype), break after punctuation,
  never end on an article/preposition/conjunction/possessive, keep a number with its unit, and prefer a
  merge to a flash: each chunk should hold max(0.5, 0.35 + 0.28 s x words) where the speech allows.
- merge_singles (legacy helper): a one-word chunk joins its neighbour ("READ THE" / "SCRIPT," -> one chunk).
- Text entrances >= 6 frames apart: a caption chunk never enters within 6 frames of the hook title or a
  graphic (B-roll card, cutaway, chip, strap). The chunk moves, never the graphic, so a card still
  leads its word by exactly 4 frames and its entrance SFX stays on the card's frame.
Pure functions of their inputs (deterministic, no clock).
"""
GAP_FRAMES = 6
MAX_WORDS = 4
# captions-visual rules 2.1: a chunk never ends on a word that leans on the next one (article, preposition,
# conjunction, possessive); it moves to the next chunk ("FOLLOW FOR / THE" -> "FOLLOW / FOR THE NEXT").
DANGLING = frozenset("a an the of to for and but or nor so yet if as at by in on into onto upon with from "
                     "than via per my your his her its our their whose every each one this these those".split())
HARD_BREAK, SOFT_BREAK = ".!?", ",;:"
# hype (1-2 words, cap 3): a one-word chunk held shorter than hold_need(1) pays HYPE_FLASH, so it merges into a
# neighbour whenever the 3-word cap allows. Its dangling cost rises by the same amount, so a merge that
# would end on 'if' / 'the' still never beats the flash: the penalty only applies when a legal merge exists
# (inside the sentence and the cap, no dangling end), so 'WHAT' / 'IF THE EDIT' stays ('WHAT IF' dangles).
HYPE_FLASH = 40.0
UNITS = frozenset("% percent hours hrs hour minutes mins minute seconds secs second days day weeks week months "
                  "month years year views followers likes times x k lakh crore million billion steps reels".split())


def hold_need(n_words: int) -> float:
    """Minimum readable hold for a chunk of n words: max(0.5 s, 0.35 + 0.28 s x words)."""
    return max(0.5, 0.35 + 0.28 * n_words)


def dangles(word: str) -> bool:
    w = word.strip()
    return bool(w) and w[-1] not in HARD_BREAK + SOFT_BREAK and w.strip("\"'“”‘’()").lower() in DANGLING


def splits_number(word: str, nxt: str) -> bool:
    """'3 / hours' or '$40,000 / views': a number is never parted from the unit that follows it."""
    return word[-1:].isdigit() and nxt.strip(".,!?;:").lower() in UNITS


def _units(words: list[dict]) -> list[list[int]]:
    """Script words that share one spoken (ASR) word ('three thousand' said as '3,000') form one unit."""
    units, cur = [], []
    for i, w in enumerate(words):
        prev = words[cur[-1]] if cur else None
        if prev and not (abs(w["s"] - prev["s"]) < 1e-6 and abs(w["e"] - prev["e"]) < 1e-6):
            units.append(cur)
            cur = []
        cur.append(i)
    return units + [cur] if cur else units


def craft_chunks(words: list[dict], max_words: int, max_chars: int) -> list[list[int]]:
    """Chunk words for captions with the lowest total craft cost, one sentence at a time (a chunk never
    runs across . ! ?). Hard: <= hard_w words (4; 3 for the 1-2-word hype family) and <= max_chars + 6
    characters (two short lines), never splitting a spoken unit. Costs: ending on a dangling word, running
    across , ; : or a pause >= 0.3 s, words/chars over the family size, a one-word flash, and the shortfall
    against hold_need() given when the next chunk would replace it. Deterministic (pure, no clock)."""
    if not words:
        return []
    units, hype = _units(words), max_words <= 2
    hard_w, hard_c = min(4, max_words + 1), max_chars + 6

    def legal(a: int, b: int) -> bool:                 # units[a:b] inside one sentence, the cap, no dangling end
        idx = [i for u in units[a:b] for i in u]
        chars = sum(len(words[i]["w"]) + 1 for i in idx) - 1
        return (0 <= a and b <= len(units) and len(idx) <= hard_w and chars <= hard_c
                and all(words[u[-1]]["w"][-1:] not in HARD_BREAK for u in units[a:b - 1])
                and not (idx[-1] < len(words) - 1 and dangles(words[idx[-1]]["w"])))

    def mergeable(a: int, b: int) -> bool:             # can units[a:b] join a neighbour within the family cap?
        return any(legal(a, b + j) or legal(a - j, b) for j in range(1, hard_w))

    def cost(a: int, b: int) -> float | None:          # chunk = units[a:b]
        idx = [i for u in units[a:b] for i in u]
        n, chars = len(idx), sum(len(words[i]["w"]) + 1 for i in idx) - 1
        if b - a > 1 and (n > hard_w or chars > hard_c):
            return None
        c = 5.0 + (8 if hype else 12) * max(0, n - max_words) + 2 * max(0, chars - max_chars)
        if idx[-1] < len(words) - 1 and (dangles(words[idx[-1]]["w"])
                                         or splits_number(words[idx[-1]]["w"], words[idx[-1] + 1]["w"])):
            c += 60 + (HYPE_FLASH if hype else 0)
        for u in units[a:b - 1]:          # a sentence's one-word lead-in ('First,') may run on
            last, nxt = words[u[-1]], words[u[-1] + 1]
            lead = len(u) == 1 and (u[0] == 0 or words[u[0] - 1]["w"][-1:] in HARD_BREAK)
            c += (12 if lead else 30) * (last["w"][-1:] in SOFT_BREAK)
            c += 15 * (nxt["s"] - last["e"] >= 0.3)
        if n == 1:
            c += 4 if hype else 20
        end = words[idx[-1] + 1]["s"] if idx[-1] + 1 < len(words) else words[idx[-1]]["e"] + 0.3
        hold = end - words[idx[0]]["s"]
        if hype and n == 1 and hold < hold_need(1) - 1e-6 and mergeable(a, b):
            c += HYPE_FLASH    # a one-word flash loses to a legal merge; none legal ('WHAT' + 'IF THE'): it stays
        return c + 40 * max(0.0, hold_need(n) - hold) + 20 * (hold < 0.5 - 1e-6)

    chunks, a = [], 0
    while a < len(units):                           # one sentence: units up to and including a hard break
        b = a
        while b < len(units) - 1 and words[units[b][-1]]["w"][-1:] not in HARD_BREAK:
            b += 1
        b += 1
        best = {a: (0.0, a)}
        for k in range(a + 1, b + 1):
            for m in range(k - 1, a - 1, -1):
                c = cost(m, k)
                if c is None:
                    break
                tot = best[m][0] + c
                if k not in best or tot < best[k][0] - 1e-9:
                    best[k] = (tot, m)
        cuts, k = [], b
        while k > a:
            cuts.append((best[k][1], k))
            k = best[k][1]
        chunks += [[i for u in units[m:k] for i in u] for m, k in reversed(cuts)]
        a = b
    return chunks


def merge_singles(chunks: list[list[int]], texts: list[str], max_words: int = MAX_WORDS) -> list[list[int]]:
    """Join one-word chunks to the previous chunk (not across a sentence end), else to the next one."""
    out: list[list[int]] = []
    for ch in chunks:
        if out and (len(ch) == 1 or len(out[-1]) == 1) and len(out[-1]) + len(ch) <= max_words \
                and texts[out[-1][-1]][-1:] not in ".!?":
            out[-1] = out[-1] + ch
        else:
            out.append(ch)
    return out


SNAP_CUT_FRAMES = 6


def card_in(out_start: float, word_t: float, fps: int, lead_frames: int) -> float:
    """A B-roll card's first frame: lead_frames before its word, never before its shot's cut, and ON the cut when
    it would land within SNAP_CUT_FRAMES after it (CD review: the CTA take flashed for 1 frame at 7.50 s)."""
    s = max(out_start, word_t - lead_frames / fps)
    return out_start if s - out_start < SNAP_CUT_FRAMES / fps + 1e-6 else s


def graphic_entrances(tl, fps: int, lead_frames: int) -> list[float]:
    """Reel times at which a text graphic enters, exactly as the compiler places them."""
    out = []
    for si, p in enumerate(tl.shots):
        for c in p.shot.cues:
            t = p.words[c.start_word].start
            if c.type == "title":
                out.append(0.0 if si == 0 else t)
            elif c.type == "broll":
                out.append(card_in(p.out_start, t, fps, lead_frames))
            elif c.type in ("cutaway", "overlay", "lowerthird"):
                out.append(t)
    return sorted(out)


def stagger(starts: list[float], ends: list[float], graphics: list[float], fps: int) -> list[float]:
    """Move chunk starts off any graphic entrance by >= 6 frames: later when the chunk would enter at or
    after the graphic, earlier when it would enter just before it (never before the previous chunk)."""
    g = GAP_FRAMES / fps
    out = list(starts)
    for k, s in enumerate(out):
        for e in graphics:
            if abs(s - e) < g - 1e-6:
                lo = out[k - 1] + 1 / fps if k else 0.0
                if s < e and e - g >= lo:
                    s = e - g
                elif e + g < ends[k] - 1 / fps:
                    s = e + g
        out[k] = round(s, 6)
    return out
