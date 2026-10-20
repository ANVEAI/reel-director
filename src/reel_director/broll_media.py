"""Real-media B-roll planning (v4 contract): the director's media inserts and the council pass that caps them.

The director (director.run -> plan) turns concrete nouns into `broll` cues of kind "media":
    {"kind": "media", "query": "video editing timeline", "media": "image" | "video",
     "providers": [...in order...], "treatment": "kenburns", "layout": "full" | "split" | "pip" | "inset",
     "slot": "<shot>.<word>", "text": <fallback label>, "icon": <fallback glyph>, "paid_ok": false}
Resolution (mediaplan.resolve -> media.select) picks + fetches the file into media.json BEFORE render; a cue that
does not resolve falls back to the text card it replaced, so a reel never breaks on a missing picture.

Densities are the edit recipes of ~/Developer/reel-knowledge/editing-pacing/case-studies.md section 3 (R1-R6;
`share` = face-off B-roll share of runtime, `insert` = insert length), clamped to the contract (inserts 1.2-3.0 s,
real-media share <= 40 %). `visual` = media time a reel aims for, face-kept insets included (the founder asked for
more visuals; insets keep the face, so they do not spend the face-off share); >= 25 % (contract v4: real inserts
25-40 %; v4 panel: one 1.2 s insert in 11 s is too little). Split inserts may run to 3.0 s and bridge into the next
split card (broll_flow: no face jump). Rules: B-roll on concrete nouns,
never over a number (EP P6, the stat card owns it), never over the payoff (the last clause of the last shot),
<= 1 paid clip per reel by default (paid providers only on that cue, and only with approval in Studio).
Deterministic: no clock, no random; treatment rotation and Ken Burns moves are seeded from crc32.
"""
from . import broll_flow
from . import lexicon as lx

INSERT = (1.2, 3.0)                 # contract: inserts 1.2-3 s
SHARE_MAX = 0.40                    # contract: 25-40 % for real inserts (the cap)
FIRST = 2.5                         # council 4 + 6: first insert after the hook title (>= 2.0 s, title to 2.5 s)
FACE_GAP, FACE_TAIL = 1.5, 2.5      # council 4: face between face-off inserts; face for the last 2.5 s
PAID = ("veo", "higgsfield")
IMAGE_PROVIDERS = ("library", "openverse", "wikimedia", "unsplash", "pixabay", "nasa")
VIDEO_PROVIDERS = ("library", "pixabay", "coverr", "wikimedia", "archive", "nasa", "youtube_cc", "claude_clip")
TREATMENTS = ("fullbleed", "kenburns", "parallax", "sticker", "device", "polaroid", "reveal", "inset")
IMAGE_ONLY = {"parallax", "sticker", "polaroid"}
FACE_KEPT = {"inset", "split", "pip"}        # layouts where the face stays on screen (not face-off time)

# Recipe -> media density and treatment palette ((treatment, layout) in rotation order).
RECIPES = {
    "retention-classic": {"share": (0.05, 0.15), "insert": (1.2, 1.5), "visual": 0.25,   # R1 Hormozi: face-dominant
                          "palette": (("inset", "inset"), ("sticker", "inset"), ("device", "split"))},
    "quiet-authority": {"share": (0.00, 0.10), "insert": (2.0, 3.0), "visual": 0.25,     # R2 Leila / Codie
                        "palette": (("device", "full"), ("inset", "inset"), ("kenburns", "split"))},
    "calm-premium": {"share": (0.25, 0.40), "insert": (2.5, 3.0), "visual": 0.32,        # R3 Abdaal: slow, real
                     "palette": (("kenburns", "full"), ("parallax", "full"), ("polaroid", "full"),
                                 ("fullbleed", "full"))},
    "motion-graphics-explainer": {"share": (0.30, 0.40), "insert": (1.5, 3.0), "visual": 0.35,   # R4 Gadzhi
                                  "palette": (("device", "full"), ("reveal", "full"), ("kenburns", "split"),
                                              ("parallax", "full"))},
    "story-hype": {"share": (0.20, 0.35), "insert": (1.2, 2.5), "visual": 0.30,          # R5 MrBeast / Hoyos
                   "palette": (("fullbleed", "full"), ("reveal", "full"), ("sticker", "inset"),
                               ("kenburns", "pip"))},
    "desi-explainer": {"share": (0.20, 0.30), "insert": (1.2, 2.5), "visual": 0.25,      # R6 Warikoo / finance
                       "palette": (("device", "full"), ("kenburns", "full"), ("polaroid", "full"),
                                   ("sticker", "inset"))},
}
PRESET_RECIPE = {"bold-hustle": "retention-classic", "clean-pro": "quiet-authority", "editorial": "calm-premium",
                 "tech-explainer": "motion-graphics-explainer", "beast-hype": "story-hype",
                 "desi-bilingual": "desi-explainer"}
PACE_RECIPE = {"calm": "calm-premium", "standard": "quiet-authority", "punchy": "story-hype"}

# Concrete nouns that have a picture: trigger words -> (search query, image|video, family). Families pick the
# treatment: screen -> device mockup, object -> cutout sticker / parallax, scene -> Ken Burns / parallax,
# people -> polaroid, action -> a moving clip.
_WORDS = {
    "edit edits editing editor timeline": ("video editing timeline on a laptop screen", "video", "screen"),
    "reel reels shorts tiktok instagram": ("vertical video on a smartphone screen", "video", "screen"),
    "video videos footage clip clips film": ("filming a video with a camera", "video", "action"),
    "camera record recording filming": ("camera recording close up", "video", "object"),
    "creator creators youtuber youtubers influencer influencers": ("content creator filming at a desk", "video", "people"),
    "script scripts notebook notes": ("handwritten notes in a notebook", "image", "object"),
    "phone smartphone mobile app apps": ("smartphone in hand", "image", "screen"),
    "laptop computer": ("laptop on a desk", "image", "object"),
    "website websites online internet browser google": ("website on a laptop screen", "image", "screen"),
    "money cash dollars rupees salary income revenue profit profits": ("stack of money", "image", "object"),
    "clock hour hours minute minutes deadline": ("clock ticking", "video", "object"),
    "coffee mug": ("coffee mug on a desk", "image", "object"),
    "office desk workspace studio": ("tidy workspace desk", "image", "scene"),
    "city cities street streets": ("city street time lapse", "video", "scene"),
    "team people audience crowd customers clients followers": ("crowd of people", "video", "people"),
    "rocket launch": ("rocket launch", "video", "action"),
    "chart charts graph analytics data growth": ("growth chart on a screen", "image", "screen"),
    "microphone mic podcast": ("podcast microphone", "image", "object"),
    "book books course courses lesson": ("open book on a table", "image", "object"),
    "car cars road": ("car driving on a road", "video", "action"),
    "home house": ("bright home interior", "image", "scene"),
    "food meal kitchen": ("food on a kitchen table", "image", "object"),
    "gym workout fitness": ("gym workout", "video", "action"),
    "travel trip flight plane airport": ("airplane taking off", "video", "action"),
    "family kids friends": ("family together at home", "image", "people"),
    "email emails inbox newsletter": ("email inbox on a laptop", "image", "screen"),
    "store shop shopping": ("shopping store", "image", "scene"),
    "keyboard typing": ("typing on a keyboard", "video", "action"),
    "idea ideas lightbulb": ("light bulb glowing", "image", "object"),
    "trophy award": ("gold trophy", "image", "object"),
}
WORDS = {w: v for ws, v in _WORDS.items() for w in ws.split()}
DEVICE = {"phone": "phone smartphone mobile app apps reel reels shorts tiktok instagram",
          "browser": "website websites online internet browser google email emails inbox newsletter"}
_DEVICE = {w: d for d, ws in DEVICE.items() for w in ws.split()}
REVEAL = ("circle", "wipe", "text")
KB_MOVES = ((1.0, 1.12, 0, 0, 0, -2), (1.14, 1.02, 0, -2, 0, 0), (1.10, 1.10, 3, 0, -3, 0), (1.06, 1.16, -2, 1, 1, -1))


def recipe(style: dict) -> dict | None:
    """The style's media recipe with its overrides, or None when real-media B-roll is off (style.media false)."""
    cfg = style.get("media", True)
    if cfg is False or (isinstance(cfg, dict) and cfg.get("off")):
        return None
    name = style.get("pace_profile") or style.get("recipe")
    name = name if name in RECIPES else PRESET_RECIPE.get(style.get("preset"),
                                                          PACE_RECIPE.get(style.get("pace"), "quiet-authority"))
    r = {**RECIPES[name], "name": name, "paid": 1}
    if isinstance(cfg, dict):
        for k in ("share", "insert", "visual", "paid", "palette"):
            if k in cfg:
                r[k] = tuple(map(tuple, cfg[k])) if k == "palette" else tuple(cfg[k]) if k in ("share", "insert") \
                    else cfg[k]
    lo, hi = r["insert"]
    r["insert"] = (max(INSERT[0], float(lo)), min(INSERT[1], max(float(hi), INSERT[0])))
    r["share"] = (float(r["share"][0]), min(SHARE_MAX, float(r["share"][1])))
    return r


def media_word(text: str) -> tuple[str, str, str] | None:
    w = lx.bare(text)
    return WORDS.get(w) or (WORDS.get(w[:-1]) if w.endswith("s") else None)


def device_for(texts: list[str]) -> str:
    return next((_DEVICE[lx.bare(t)] for t in texts if lx.bare(t) in _DEVICE), "laptop")


def providers(kind: str, family: str, paid: bool = False) -> list[str]:
    base = list(VIDEO_PROVIDERS if kind == "video" else IMAGE_PROVIDERS)
    if kind == "video" and family == "object":           # abstract objects ("clock ticking"): a Claude clip early
        base.remove("claude_clip")
        base.insert(1, "claude_clip")
    return base + list(PAID) if paid and kind == "video" else base


def kenburns(seed: int) -> list[float]:
    """[s0, s1, x0, y0, x1, y1]: one of four eased moves (zoom in, zoom out, pan, push and drift), seeded."""
    return list(KB_MOVES[seed % len(KB_MOVES)])


def params(texts: list[str], a: int, b: int, hit: tuple[str, str, str], treatment: str, layout: str, slot: str,
           fallback: dict | None = None) -> dict:
    q, kind, fam = hit
    prm = {"kind": "media", "query": q, "media": kind, "providers": providers(kind, fam), "treatment": treatment,
           "layout": layout, "slot": slot, "family": fam,
           "text": (fallback or {}).get("text") or lx.broll_label(texts, a, b, b)}
    if treatment == "device":
        prm["device"] = device_for(texts[a:b + 1])
    if treatment == "reveal":
        prm["mask"] = REVEAL[lx.stable(slot) % len(REVEAL)]
    if glyph := (fallback or {}).get("icon") or lx.glyph_for(texts[a:b + 1]):
        prm["icon"] = glyph
    return prm


def pick_treatment(r: dict, kind: str, fam: str, prev: str | None, k: int) -> tuple[str, str]:
    """The palette entry for this insert: the family's natural treatment when the palette has it, else rotation;
    never the previous insert's treatment twice in a row; image-only treatments never on a clip."""
    pal = [p for p in r["palette"] if not (kind == "video" and p[0] in IMAGE_ONLY)] or [("fullbleed", "full")]
    natural = {"screen": "device", "object": "sticker" if kind == "image" else "inset", "people": "polaroid",
               "scene": "parallax" if kind == "image" else "kenburns", "action": "fullbleed"}.get(fam)
    order = [p for p in pal if p[0] == natural] + pal[k % len(pal):] + pal[:k % len(pal)]
    return next((p for p in order if p[0] != prev), order[0])


# ---- director ---------------------------------------------------------------------------------------------
def _payoff_start(dr) -> int:
    texts = dr.texts(dr.n - 1)
    j = len(texts) - 1
    while j > 0 and texts[j - 1][-1:] not in ".!?,;:":
        j -= 1
    return max(j, len(texts) - 2)


def _blocked(dr, si: int, a: int, b: int) -> bool:
    texts = dr.texts(si)
    nums = lx.number_phrases(texts)
    items = lx.enumeration(texts) or []
    if any(x <= b and a <= y for x, y in nums):                        # EP P6: the number is the stat card's
        return True
    if len(items) >= 2 and items[0][0] <= b and a <= items[-1][1]:      # the checklist owns its enumeration
        return True
    return si == dr.n - 1 and b >= _payoff_start(dr)                    # never over the payoff


def _cands(dr, r: dict) -> list[tuple]:
    out = []
    for si in range(dr.n):
        if not dr.on(si, "broll"):
            continue
        texts = dr.texts(si)
        for wi, t in enumerate(texts):
            hit = media_word(t)
            if not hit or _blocked(dr, si, wi, wi):
                continue
            span = dr._extend(si, wi, wi, r["insert"][1])
            if not span or _blocked(dr, si, *span):
                continue
            weight = {"screen": 3, "action": 3, "object": 2, "scene": 2, "people": 1}[hit[2]]
            out.append((-weight, si, wi, span, hit))
    return sorted(out, key=lambda c: (c[0], c[1], c[2]))


def _media_time(dr) -> float:
    return sum(dr._len(si, c) for si in range(dr.n) for c in dr.cues(si, {"broll"}) if c.params.get("kind") == "media")


def plan(dr) -> None:
    """Director step (after the cards): upgrade auto text/icon cards on concrete nouns to real media, then add media
    inserts on the strongest remaining nouns until the recipe's `visual` share; rotate treatments; <= 1 paid cue."""
    r = recipe(dr.style)
    if r is None:
        return
    for si in range(dr.n):                     # 1. a card on a noun with a picture becomes that picture
        texts = dr.texts(si)
        for c in [c for c in dr.auto[si] if c.type == "broll" and c.params.get("kind") in ("text", "icon")]:
            hit = next((h for t in texts[c.start_word:c.end_word + 1] if (h := media_word(t))), None)
            if hit and not _blocked(dr, si, c.start_word, c.end_word):
                fb = {"text": c.params.get("text"), "icon": c.params.get("icon")}
                c.params = {**{k: v for k, v in c.params.items() if k in ("to_cut", "hold", "auto", "why")},
                            **params(texts, c.start_word, c.end_word, hit, "kenburns", "full",
                                     f"{dr.s.shots[si].id}.{c.start_word}", fb),
                            "from_card": True,
                            "why": f"real-media B-roll on a concrete noun ({r['name']} recipe, contract v4)"}
    target, band = r["visual"] * dr.dur, SHARE_MAX * dr.dur
    for _, si, wi, (a, b), hit in _cands(dr, r):    # 2. more media on the strongest nouns, up to the visual share
        if _media_time(dr) >= target:
            break
        total = sum(dr._len(i, c) for i in range(dr.n) for c in dr.cues(i, {"broll", "cutaway"}))
        ta, tb = dr.span_t(si, a, b)
        if dr.overlaps(si, {"broll", "cutaway", "title", "overlay", "lowerthird", "endcard"}, a, b) or \
                total + tb - ta > band or any(min(abs(ta - v), abs(tb - v)) < dr.gap for v in dr._ves()):
            continue           # EP B1 band (<= 40 % in all); EP P1: no visual change closer than half the pace
        for layout in ("inset", "full"):
            if dr._broll_fits(si, a, b, layout) and dr.span_t(si, a, b)[0] >= FIRST:
                prm = params(dr.texts(si), a, b, hit, "inset" if layout == "inset" else "kenburns", layout,
                             f"{dr.s.shots[si].id}.{a}")
                dr.add(si, "broll", a, b, f"real-media B-roll on a concrete noun ({r['name']} recipe, contract v4)",
                       **prm)
                break
    assign(dr, r)


def assign(dr, r: dict) -> None:
    """Treatments in time order (palette rotation, no repeats), the layout each implies (re-checked against the face
    rules), and the paid flag on the first full-layout clip only (<= r['paid'] per reel)."""
    media = sorted(((dr.span_t(si, c.start_word, c.end_word)[0], si, c) for si in range(dr.n)
                    for c in dr.auto[si] if c.type == "broll" and c.params.get("kind") == "media"), key=lambda x: x[:2])
    prev, paid = None, 0
    for k, (_, si, c) in enumerate(media):
        p = c.params
        want = pick_treatment(r, p["media"], p.get("family", "scene"), prev, k + lx.stable(dr.s.title))
        flat = next(t for t in (("kenburns", "parallax", "fullbleed") if p["media"] == "image"   # a full-frame
                                else ("fullbleed", "reveal", "kenburns")) if t != prev)          # stand-in, new look
        opts = [want, (want[0] if want[0] not in ("inset", "sticker") else flat, "full"),
                (p.get("treatment", flat), p.get("layout", "full"))]
        dr.auto[si].remove(c)
        treat, layout = next((o for o in opts if dr._broll_fits(si, c.start_word, c.end_word, o[1])), opts[-1])
        dr.auto[si].append(c)
        texts = dr.texts(si)
        hit = (p["query"], p["media"], p.get("family", "scene"))
        c.params = {**p, **params(texts, c.start_word, c.end_word, hit, treat, layout, p["slot"],
                                  {"text": p.get("text"), "icon": p.get("icon")})}
        c.params["kb"] = kenburns(lx.stable(dr.s.title, p["slot"]))
        if paid < r["paid"] and p["media"] == "video" and layout == "full":
            c.params.update(paid_ok=True, providers=providers("video", p.get("family", "scene"), paid=True))
            paid += 1
        prev = treat
    if media:
        dr.notes.append(f"media: {len(media)} real-media insert(s) planned ({r['name']} recipe, visual share "
                        f"{_media_time(dr) / dr.dur:.0%}, face-off cap {r['share'][1]:.0%})")


# ---- council pass ---------------------------------------------------------------------------------------
def take(P) -> list[tuple[int, object]]:
    """policy.broll(): lift the auto media cues out before the card rules run (they keep their own layouts)."""
    out = [(si, c) for si, c in P.autos("broll") if c.params.get("kind") == "media"]
    for si, c in out:
        P.s.shots[si].cues.remove(c)
    return out


def _payoff_t(P) -> float:
    li = len(P.s.shots) - 1
    texts = [w.text for w in P.s.shots[li].words]
    j = len(texts) - 1
    while j > 0 and texts[j - 1][-1:] not in ".!?,;:":
        j -= 1
    return P.t(li, max(j, len(texts) - 2))


def _trim(P, si: int, c, top: float) -> tuple[float, float]:
    while c.end_word > c.start_word and P.span(si, c)[1] - P.span(si, c)[0] > top + 1e-6:
        c.end_word -= 1
        c.params.pop("to_cut", None)
    return P.span(si, c)


def _as_card(P, si: int, c, kept: list, payoff_t: float) -> str | None:
    """A media insert the caps refuse goes back to the label card it replaced, under the card rules (TEXT_MAX,
    first insert, face gap and tail, the council's card share); returns why it cannot, else None."""
    from .policy import TEXT_MAX
    p = c.params
    c.params = {**{k: p[k] for k in ("auto", "why", "hold", "background", "icon") if k in p},
                "kind": "text", "text": p.get("text") or p.get("query", ""), "layout": "full"}
    a, b = _trim(P, si, c, TEXT_MAX)
    full = [(x, y) for _, k, x, y in kept if k.params.get("layout", "full") not in FACE_KEPT]
    cards = sum(y - x for _, k, x, y in kept if k.params.get("kind") != "media"
                and k.params.get("layout", "full") not in FACE_KEPT)
    return (f"insert shorter than {INSERT[0]}s" if b - a < INSERT[0] - 1e-6 else
            f"first insert starts at >= {FIRST}s" if a < FIRST - 1e-6 else
            "never over the payoff" if b > payoff_t + 1e-6 else
            f"face on screen for the last {FACE_TAIL}s" if b > P.T - FACE_TAIL + 1e-6 else
            f"needs {FACE_GAP}s of face between inserts" if any(a < y + FACE_GAP and x < b + FACE_GAP for x, y in full)
            else f"B-roll cap {P.pace['broll']:.0%} of runtime" if cards + b - a > P.pace["broll"] * P.T + 1e-6
            else None)


def enforce(P, media: list) -> None:
    """Re-add the media cues that obey the caps: insert 1.2 s..recipe max, first after the title, never over the
    payoff, face-off inserts >= 1.5 s apart and off the last 2.5 s, face-off share <= recipe cap, <= N paid. One the
    caps refuse goes split (face track), else back to the label card it replaced (card rules), else it drops.
    Each keeps a fallback card in the preset's style (label case, card background) for when it does not resolve."""
    from . import presets
    r = recipe(P.style) or {**RECIPES["quiet-authority"], "paid": 1}
    card = presets.DIRECTION.get(P.name, presets.DIRECTION["clean-pro"])
    for si, c in media:
        c.params["background"] = c.params.get("background", card["card"])
        if c.params.get("text"):
            c.params["text"] = presets.card_case(str(c.params["text"]), card["case"], P.s.shots[si].line)
    T, top, payoff_t = P.T, min(INSERT[1], r["insert"][1]), _payoff_t(P)
    kept = [(si, c, *P.span(si, c)) for si, sh in enumerate(P.s.shots) for c in sh.cues if c.type in ("broll", "cutaway")]
    off = sum(b - a for si, c, a, b in kept if c.params.get("layout", "full") not in FACE_KEPT)
    paid = sum(1 for _, c, *_ in kept if c.params.get("paid_ok"))
    for si, c in sorted(media, key=lambda x: (P.t(x[0], x[1].start_word), x[0])):
        P.s.shots[si].cues.append(c)
        a, b = _trim(P, si, c, top)
        full = c.params.get("layout", "full") not in FACE_KEPT
        crowd = any(a < y + 0.5 and x < b + 0.5 for _, _, x, y in kept)       # any insert this close: no room
        why = (f"insert shorter than {INSERT[0]}s" if b - a < INSERT[0] - 1e-6 else
               f"first insert starts at >= {FIRST}s" if a < FIRST - 1e-6 else
               "never over the payoff" if b > payoff_t + 1e-6 else "no room between inserts" if crowd else None)
        face = None if not full or why else (
            f"face on screen for the last {FACE_TAIL}s" if b > T - FACE_TAIL + 1e-6 else
            f"needs {FACE_GAP}s of face between inserts" if any(a < y + FACE_GAP and x < b + FACE_GAP
                                                                  for _, k, x, y in kept
                                                                  if k.params.get("layout", "full") not in FACE_KEPT)
            else f"face-off B-roll cap {r['share'][1]:.0%} ({r['name']})" if off + b - a > r["share"][1] * T + 1e-6
            else None)
        if face and P.has_face(si) and c.params.get("treatment") not in ("inset", "sticker"):
            c.params["layout"], full = "split", False      # the face stays on screen under the media (v2 split)
            P.notes.append(f"council: media in {P.s.shots[si].id!r} goes split ({face})")
        if not why and c.params.get("layout") == "split":   # face kept: the contract's 3.0 s, not the recipe's cutaway
            broll_flow.grow(P, si, c, payoff_t)
            a, b = P.span(si, c)
        elif (face or why) and c.params.get("from_card") and not (back := _as_card(P, si, c, kept, payoff_t)):
            P.notes.append(f"council: media in {P.s.shots[si].id!r} keeps its label card ({face or why})")
            kept.append((si, c, *P.span(si, c)))
            off += P.span(si, c)[1] - P.span(si, c)[0]
            continue
        elif face or why:
            P.drop(si, c, (face or why) + (f"; as a card: {back}" if c.params.get("kind") == "text" else ""))
            continue
        off += (b - a) if full else 0.0
        if c.params.get("paid_ok"):
            if paid >= r["paid"]:
                c.params.update(paid_ok=False, providers=[p for p in c.params.get("providers", []) if p not in PAID])
            paid += 1
        kept.append((si, c, a, b))
    broll_flow.split_flow(P)




def _edges(P, si: int, c, r: dict) -> list[tuple[int, int]]:
    """The word spans this media insert may move to: start up to 3 words later, any end up to 1 word later, inside
    its rules (1.2 s..recipe max, after the title, never over the payoff, 0.5 s clear of other inserts; full layouts
    keep the face gap, the face tail and the face-off share)."""
    top, payoff_t, T = min(INSERT[1], r["insert"][1]), _payoff_t(P), P.T
    others = [(k, *P.span(i, k)) for i, sh in enumerate(P.s.shots) for k in sh.cues
              if k.type in ("broll", "cutaway") and k is not c]
    full = c.params.get("layout", "full") not in FACE_KEPT
    off = sum(y - x for k, x, y in others if k.params.get("layout", "full") not in FACE_KEPT)
    (a0, b0), n, out = (c.start_word, c.end_word), len(P.s.shots[si].words), []
    for a, b in ((a, b) for a in range(a0, a0 + 4) for b in range(a, b0 + 2) if b < n and (a, b) != (a0, b0)):
        c.start_word, c.end_word = a, b
        x, y = P.span(si, c)
        if (INSERT[0] - 1e-6 <= y - x <= top + 1e-6 and x >= FIRST - 1e-6 and y <= payoff_t + 1e-6
                and not any(x < q + 0.5 and p < y + 0.5 for _, p, q in others)
                and not (full and (y > T - FACE_TAIL + 1e-6 or off + y - x > r["share"][1] * T + 1e-6 or any(
                    x < q + FACE_GAP and p < y + FACE_GAP for k, p, q in others
                    if k.params.get("layout", "full") not in FACE_KEPT)))):
            out.append((a, b))
    c.start_word, c.end_word = a0, b0
    return out


def pace_fit(P, replan) -> dict:
    """The enforced pace gate (P3) with real inserts: the punch re-plan first. When the gate still fails (a real
    insert is longer than the label card it replaced and can even out the run of changes), try each auto media
    insert's other legal edges (_edges) with a fresh punch re-plan and keep the best (gate passes first, then the
    lowest pace penalty). Deterministic: fixed candidate order, ties keep the earlier one."""
    import copy
    from .pace import _penalty, gate_of
    g = replan(P)
    if g["level"] != "fail":
        return g
    r = recipe(P.style) or {**RECIPES["quiet-authority"]}
    snap, notes = [copy.deepcopy(sh.cues) for sh in P.s.shots], list(P.notes)

    def restore():
        for sh, cs in zip(P.s.shots, snap):
            sh.cues[:] = copy.deepcopy(cs)
        P.notes[:] = notes
    where = [(si, ci) for si, sh in enumerate(P.s.shots) for ci, c in enumerate(sh.cues)
             if c.type == "broll" and c.params.get("auto") and c.params.get("kind") == "media"]
    best = ((True, _penalty(P)), None)
    for si, ci in where:
        for a, b in _edges(P, si, P.s.shots[si].cues[ci], r):
            restore()
            c = P.s.shots[si].cues[ci]
            c.start_word, c.end_word = a, b
            replan(P)
            key = (gate_of(P)["level"] == "fail", round(_penalty(P), 6))
            if key < best[0]:
                best = (key, (si, ci, a, b))
    restore()
    if best[1] is None:
        return g
    si, ci, a, b = best[1]
    c = P.s.shots[si].cues[ci]
    P.notes[:] = [x for x in P.notes if not x.startswith("pace gate: ")]   # the final re-plan's verdict stands
    P.notes.append(f"council: media in {P.s.shots[si].id!r} moved from words {c.start_word}-{c.end_word} to {a}-{b} "
                   "for the pace (a real insert evened out the run of changes)")
    c.start_word, c.end_word = a, b
    return replan(P)
