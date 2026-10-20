"""Caption plan: which words get a caption chunk, when, and where (compiler helper; real-1 review fixes).

One text block at a time (CD / HQ / founder review of the real-1 reels, 20 Oct):
- Under a title no caption shows: the hook title IS the hook's text block. layout.title_window ends the title on
  a word start near 2.5 s, so captions resume on a fresh chunk (no title + caption + head stacked in the top 40 %).
- Under a B-roll card the card is the text (its label, checklist or stat), so the caption no longer repeats it;
  a checklist ticks each item on its spoken word instead. style.card_captions = true restores the v2 behaviour
  (captions over cards, split at the card's edges).
- A chunk never straddles a title or card edge: the visible words are chunked per run between those windows,
  so a phrase never jumps ~500 px mid-chunk ("WHAT IF THE EDIT" across the card's in).
Pure functions of the builder's timeline, cues and layout (deterministic).
"""
from . import lexicon as lx
from . import layout as lyt
from . import stagger
from . import treatments


def hidden_windows(b) -> list[dict]:
    """[{s, e, si, idx}] reel spans where captions are off: every title and full card (idx None: every word), and
    the checklist's own words on a split card (idx: those word indices of shot si; its other words, 'and the reel',
    are captioned in the card's band). style.card_captions keeps every caption over the cards."""
    out, cards_off = [], not b.style.get("card_captions", False)
    for si, p in enumerate(b.tl.shots):
        shot_end = min(p.out_start + p.duration, b.D, b.tx_in.get(si + 1, b.D))
        for c in p.shot.cues:
            w = None
            if c.type == "title":
                w = lyt.title_window(b.tl, si, c, b.D)
            elif c.type == "broll" and cards_off and not treatments.shows_captions(b, c.params):   # real media: on
                w = b.broll_span(p, c, shot_end)
            elif c.type == "cutaway" and cards_off:
                w = b.cutaway_span(p, c, shot_end)
            if w:
                split = c.type == "broll" and c.params.get("layout") in ("split", "pip")
                idx = item_words(p, c, list(c.params.get("items") or [])) if split and c.params.get("kind") == "list" else None
                out.append({"s": w[0], "e": w[1], "si": si, "idx": idx})
    return sorted(out, key=lambda x: (x["s"], x["e"]))


TAIL = 0.25    # s: a word starting this close to a full window's end is still captioned (from the window's out)


def _hidden(w: dict, si: int, hide: list[dict]) -> bool:
    return any(h["s"] - 1e-6 <= w["s"] < (max(h["s"], h["e"] - TAIL) if h["idx"] is None else h["e"]) - 1e-6
               and (h["idx"] is None or h["si"] == si and w["i"] in h["idx"]) for h in hide)


def _runs(words: list[dict], si: int, hide: list[dict]) -> list[list[dict]]:
    """Visible words in runs that no hidden word and no window edge interrupts (a chunk never jumps mid-phrase)."""
    edges = sorted({x for h in hide for x in (h["s"], h["e"])})
    runs, cur = [], []
    for w in words:
        if _hidden(w, si, hide):
            if cur:
                runs.append(cur)
            cur = []
            continue
        if cur and any(cur[-1]["s"] < x <= w["s"] + 1e-6 for x in edges):
            runs.append(cur)
            cur = []
        cur.append(w)
    return runs + [cur] if cur else runs


def plan(b, max_w: int, max_c: int) -> list[dict]:
    """Caption chunks [{id, s, e, raw, si, shot, first, last, ws}] for the whole reel."""
    out, graphics = [], stagger.graphic_entrances(b.tl, b.fps, b.BROLL_LEAD)
    hide = hidden_windows(b)
    for si, p in enumerate(b.tl.shots):
        shot_end = min(p.out_start + p.duration, b.D)
        nxt_shot = b.tl.shots[si + 1].out_start if si + 1 < len(b.tl.shots) else b.D
        emph = {i for c in p.shot.cues if c.type == "emphasis" for i in range(c.start_word, c.end_word + 1)}
        shown = lx.display_words([w.text for w in p.shot.words])        # 'three hours' -> '3 hours'
        words = [{"w": shown[i], "s": b.clamp(t.start), "e": b.clamp(t.end), "i": i, "emph": i in emph}
                 for i, (w, t) in enumerate(zip(p.shot.words, p.words))]
        for i in range(len(words) - 1):            # close small gaps so words never blink out
            if 0 < words[i + 1]["s"] - words[i]["e"] < 0.3:
                words[i]["e"] = words[i + 1]["s"]
        chunks = [[run[k] for k in idx] for run in _runs(words, si, hide)
                  for idx in b.caption_chunks(run, max_w, max_c)]           # one-word chunks priced in
        starts = stagger.stagger([c[0]["s"] for c in chunks], [c[-1]["e"] for c in chunks], graphics, b.fps)
        for ci, ws in enumerate(chunks):
            s = max([starts[ci]] + [h["e"] for h in hide if h["idx"] is None and h["s"] - 1e-6 <= starts[ci] < h["e"]])
            wall = min([h["s"] for h in hide if h["s"] > s + 1e-6] + [h["e"] for h in hide if h["e"] > s + 1e-6
                                                                      and h["idx"] is not None] + [b.D])
            nxt = starts[ci + 1] if ci + 1 < len(chunks) else None
            e = nxt if nxt is not None else min(shot_end, ws[-1]["e"] + 0.3)
            if nxt is None:                        # the shot's last chunk holds its readable minimum
                e = max(e, min(shot_end, nxt_shot, s + stagger.hold_need(len(ws))))
            e = min(e, wall)
            if e - s < 1 / b.fps:
                continue
            out.append({"id": b.uid("cap"), "s": round(s, 4), "e": round(e, 4), "raw": (s, e), "si": si,
                        "shot": p.shot.id, "first": ws[0]["i"], "last": ws[-1]["i"], "ws": ws})
    return out


def emit(b, chunks: list[dict]) -> list[dict]:
    """One element per piece, split at B-roll cuts and boxed by the face-aware layout (contract P1)."""
    out = []
    for ch in chunks:
        for k, (a, e, box, zone) in enumerate(b.lay.caption_pieces(ch["si"], *ch["raw"], b.card_spans)):
            pid = ch["id"] if k == 0 else f'{ch["id"]}p{k}'
            wl = [[f'{pid}-w{w["i"]}', round(w["s"], 4), round(w["e"], 4)] for w in ch["ws"]]
            spans = " ".join(f'<span id="{wid}" class="{"word emph" if w["emph"] else "word"}">{b.esc(w["w"])}</span>'
                             for (wid, _, _), w in zip(wl, ch["ws"]))
            b.caps.append(f'    <div id="{pid}" class="clip cap" data-start="{b.r(a)}" data-duration="{b.r(e - a)}" '
                          f'data-track-index="5" data-zone="{zone}"{b.lay.caption_style(box)}><div id="{pid}-in" '
                          f'class="cap-in fit">{spans}{{callouts:{pid}}}</div></div>')
            out.append({"id": pid, "s": ch["s"], "e": round(e, 4), "words": wl, "shot": ch["shot"],
                        "first": ch["first"], "last": ch["last"]})
            b.lay.caps.append({"chunk_id": pid, "shot": ch["shot"], "t0": round(a, 4), "t1": round(e, 4),
                               "box": lyt.xywh(box), "zone": zone, "text": " ".join(w["w"] for w in ch["ws"])})
    return out


def _item_starts(p, c, items: list[str]) -> list[int]:
    norm = lambda w: "".join(ch for ch in w.lower() if ch.isalnum())           # noqa: E731
    texts = [norm(w.text) for w in p.shot.words]
    out, k = [], c.start_word
    for it in items:
        first = norm(str(it).split()[0]) if str(it).split() else ""
        k = next((j for j in range(k, len(texts)) if texts[j] == first), None)
        if k is None:
            return []
        out.append(k)
        k += 1
    return out


def item_words(p, c, items: list[str]) -> set[int]:
    """Word indices a checklist spells out (each item's words from its first spoken word): not captioned."""
    return {k + j for k, it in zip(_item_starts(p, c, items), items) for j in range(len(str(it).split()))}


def list_ticks(p, c, items: list[str]) -> list[float]:
    """Reel time each checklist item is spoken (its first word, in order from the card's first word), so the
    item builds and ticks on its word (HQ: 'HIT RECORD' ticked 23 frames before 'hit'). [] when unmatched."""
    return [round(p.words[k].start, 4) for k in _item_starts(p, c, items)]
