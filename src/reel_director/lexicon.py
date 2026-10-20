"""Deterministic text features for the auto-director (no NLP model, no randomness).

Word lists, number phrases, noun phrases, enumerations, icon picks and a read-time estimate. Every
function is pure: the same line always gives the same features.
"""
import re
import zlib

from . import textnorm
from .textnorm import norm_tokens

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen").split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "million": 10 ** 6, "crore": 10 ** 7,
          "billion": 10 ** 9}
NUMBER_WORDS = frozenset(ONES) | frozenset(TENS) | frozenset(SCALES) | {"percent", "point", "half"}
UNITS = frozenset("""seconds second minutes minute mins hours hour hrs days day weeks week months month years
    year percent x times k users followers views subscribers dollars dollar bucks rupees rupee lakh crore
    reels videos posts clients customers people steps tips ways mistakes tools things rules books hacks""".split())
FUNCTION = frozenset("""a an the to of and or but in on at by for from with as is are was were be been being it its
    this that these those i you your we our they their them he she his her my me us do does did so if then than
    just very really can will would could should has have had there here what when where who how which all
    some any even also too into out up down over about after before because while""".split())
NEGATIONS = frozenset("""never not no nobody nothing none nowhere don't doesn't didn't can't won't isn't aren't
    wasn't weren't shouldn't wouldn't couldn't stop wrong mistake mistakes without""".split())
MONEY = frozenset("""money cash price cost costs paid pay salary profit revenue income free cheap expensive
    rupees dollars lakh crore million billion rich broke""".split())
POWER = frozenset("""never only stop mistake wrong secret nobody everyone free instantly fast easy best worst
    actually truth waste why how finally without before after itself""".split())
CONTRAST = ("but", "instead", "the truth", "here's", "heres", "what if", "the problem", "the secret",
            "stop", "imagine", "actually", "so", "now", "except", "however")
LIST_MARKERS = ("first", "second", "third", "step", "next", "finally", "lastly")
CTA_VERBS = frozenset("follow comment save share subscribe like link try download join dm visit".split())
DETERMINERS = frozenset("the a an your my our their this that these those one every each his her".split())
VERBS = frozenset("""be have do say get make go know take see come think look want give use find tell ask work
    seem feel try leave call edit record read hit press build builds waste show post watch start stop need
    keep let put mean become help talk turn begin run move live believe bring happen write sit stand lose pay
    meet include continue set learn change lead understand follow create spend grow open walk win offer
    remember love consider appear buy wait serve send expect stay fall cut reach remain suggest raise pass
    sell require decide pull shoot plan fix sign join gets makes takes says goes knows thinks wants gives uses
    finds tells works feels tries calls edits records reads hits presses shows posts watches starts stops
    needs keeps puts means helps turns runs moves lives brings writes loses pays learns changes creates
    spends grows wins buys sends was were is are am did done got made said""".split())
# Pack sticker ids (motion-pack type/icons.js ICONS) by trigger word.
ICON_WORDS = {
    "play": "video videos reel reels clip clips watch record recording camera youtube shorts film",
    "bolt": "fast faster quick quickly instantly speed power energy",
    "tag": "price prices cost costs money cash free cheap sale offer rupees dollars paid",
    "spark": "ai new magic automatic auto itself idea ideas",
    "flame": "hot trending viral fire",
    "heart": "love loved favorite like likes",
    "speech": "say said talk voice script scripts read comment comments speak",
    "check": "done finished correct works ready",
    "cross": "wrong mistake mistakes never stop fail failed",
    "star": "best top quality rating",
    "arrow": "next step steps point",
}
_ICON_OF = {w: icon for icon, ws in ICON_WORDS.items() for w in ws.split()}
# Card glyphs: vendored Lucide ids (src/reel_director/icons) by trigger noun or state word; a B-roll card
# shows the glyph beside its label. tests/test_visuals.py checks that every id here is vendored.
GLYPH_WORDS = {
    "clock": "hour hours minute minutes second seconds time clock", "hourglass": "wait waiting later patience",
    "calendar": "day days week weeks month months year years daily weekly schedule calendar",
    "zap": "fast faster quick quickly instantly instant speed power energy", "rocket": "launch boost growth rocket",
    "clapperboard": "edit edits editing edited editor reel reels film", "video": "video videos clip clips footage",
    "camera": "camera record recording shoot filming", "mic": "voice audio podcast mic microphone",
    "scissors": "cut cuts trim trimmed", "wand-sparkles": "magic automatic automatically auto itself",
    "sparkles": "ai new", "brain": "brain think thinking smart", "bot": "bot robot agent agents",
    "dollar-sign": "money cash dollars dollar price cost costs paid pay salary revenue income",
    "indian-rupee": "rupees rupee lakh crore", "wallet": "budget spend spent wallet", "piggy-bank": "savings",
    "coins": "earn earnings profit profits", "badge-percent": "percent discount sale offer",
    "trending-up": "grow grew growing views reach viral trending", "trending-down": "drop dropped decline",
    "chart-column": "stats data results analytics numbers metrics", "target": "goal goals target focus",
    "trophy": "win wins winner winning", "star": "best quality rating review reviews", "heart": "love loved",
    "thumbs-up": "like likes", "flame": "hot fire", "message-circle": "comment comments chat reply dm dms",
    "megaphone": "marketing ads ad brand announce", "users": "people creators audience followers team clients customers",
    "user": "creator founder", "eye": "watch watched attention", "circle-x": "wrong mistake mistakes fail failed",
    "ban": "never stop quit", "triangle-alert": "warning danger risk problem problems",
    "lightbulb": "idea ideas tip tips hack hacks secret", "book-open": "script scripts story book",
    "list-checks": "steps checklist plan process system", "file-text": "caption captions notes document",
    "smartphone": "phone mobile app apps instagram tiktok shorts", "laptop": "laptop computer",
    "globe": "website online internet world", "mail": "email emails newsletter inbox", "search": "search google seo",
    "lock": "private secure security", "gift": "free bonus gift", "shopping-cart": "buy shop store sell sales",
    "briefcase": "business job career", "settings": "tool tools setup", "graduation-cap": "course lesson learn student",
    "send": "post posts publish upload", "music": "music song beat",
}
GLYPH_STATE = {"DONE": "circle-check", "WASTED": "hourglass", "FREE": "gift", "FAST": "zap", "SOLD": "shopping-cart"}
PACK_GLYPH = {"play": "play", "bolt": "zap", "tag": "badge-percent", "spark": "sparkles", "flame": "flame",   # pack sticker
              "heart": "heart", "speech": "message-circle", "check": "circle-check", "cross": "circle-x",   # id -> glyph
              "star": "star", "arrow": "send"}
_GLYPH_OF = {w: g for g, ws in GLYPH_WORDS.items() for w in ws.split()}


def spoken_tokens(text: str) -> list[str]:
    """norm_tokens without the homophone merge: '2' -> ['two'] (not 'to'), 'their' stays 'their'.
    Falls back to the merged tokens whenever this replica of the tokenizer disagrees with textnorm."""
    canon = norm_tokens(text)
    cmap = getattr(textnorm, "_CANON", {})
    if not any(t in cmap.values() for t in canon):
        return canon
    try:
        guess = _pre_canon(text)
    except Exception:            # textnorm internals changed shape: keep the merged form
        return canon
    if len(guess) == len(canon) and all(cmap.get(g, g) == c for g, c in zip(guess, canon)):
        return guess
    return canon


def _pre_canon(text: str) -> list[str]:
    tn = textnorm
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower()).replace("’", "'")
    symbols = getattr(tn, "_SYMBOLS", {})
    if symbols:
        text = re.sub("[" + re.escape("".join(symbols)) + "]", lambda m: symbols[m.group(0)], text)
    text = re.sub(r"\b[a-z](?:\.[a-z])+\b\.?", lambda m: m.group(0).replace(".", ""), text)
    currency = getattr(tn, "_CURRENCY", {})
    pattern = getattr(tn, "_TOKEN", re.compile(r"\d+|[a-z']+|%"))
    numtok = getattr(tn, "_number_tokens", lambda t: tn.number_to_words(int(t)))
    out: list[str] = []
    for tok in pattern.findall(text):
        if tok[0].isdigit() or tok[0] in currency:
            out.extend(numtok(tok))
        elif tok == "%":
            out.append("percent")
        elif tok.strip("'"):
            out.append(tok.strip("'"))
    for k in range(len(out) - 1):
        if out[k] in currency.values() and out[k + 1] in ("thousand", "million", "billion"):
            out[k], out[k + 1] = out[k + 1], out[k]
    return out


def bare(text: str) -> str:
    """Lower-case word with surrounding punctuation stripped ('Reel,' -> 'reel')."""
    return re.sub(r"^[^\w$₹#@]+|[^\w%]+$", "", text.lower().replace("’", "'"))


def stable(*parts) -> int:
    """Process-independent tie-breaker (never Python's salted hash())."""
    return zlib.crc32("|".join(map(str, parts)).encode())


def is_numeric(text: str, next_text: str = "") -> bool:
    """'3', '$2k', '40%', 'three', 'twenty'; 'one' only before a unit ('one hour', not 'one reel')."""
    if re.search(r"\d", text):
        return True
    toks = spoken_tokens(text)
    if not toks or not all(t in NUMBER_WORDS for t in toks):
        return False
    if toks == ["one"] or toks == ["half"]:
        return bare(next_text) in UNITS
    return toks != ["point"]


def words_to_number(toks: list[str]) -> int | None:
    total, cur, seen = 0, 0, False
    for t in toks:
        if t in ONES:
            cur += ONES.index(t)
        elif t in TENS:
            cur += 20 + 10 * TENS.index(t)
        elif t == "hundred":
            cur = (cur or 1) * 100
        elif t in SCALES:
            total, cur = total + (cur or 1) * SCALES[t], 0
        elif t == "and" and seen:
            continue
        else:
            break
        seen = True
    return total + cur if seen else None


def number_phrases(texts: list[str]) -> list[tuple[int, int]]:
    """Maximal runs of numeric words plus one following unit or plural noun: (first, last) inclusive."""
    out, i = [], 0
    while i < len(texts):
        if not is_numeric(texts[i], texts[i + 1] if i + 1 < len(texts) else ""):
            i += 1
            continue
        j = i
        while j + 1 < len(texts) and is_numeric(texts[j + 1], texts[j + 2] if j + 2 < len(texts) else "") \
                and not re.search(r"[.,!?;:]$", texts[j]):
            j += 1
        if j + 1 < len(texts) and not re.search(r"[.,!?;:]$", texts[j]):
            nxt = bare(texts[j + 1])
            if nxt in UNITS or (nxt.endswith("s") and nxt not in FUNCTION and nxt not in VERBS and len(nxt) > 3):
                j += 1
        out.append((i, j))
        i = j + 1
    return out


def number_display(texts: list[str]) -> tuple[str, str]:
    """('three', 'hours') -> ('3', 'HOURS'); ('$2,500',) -> ('$2,500', ''). Value and unit label."""
    nums, label = [], []
    for t in texts:
        (nums if (not label and is_numeric(t, "x")) else label).append(t)
    raw = " ".join(bare(t) for t in nums)
    if re.search(r"\d", raw):
        value = re.sub(r"\s+", " ", raw).upper()
    else:
        n = words_to_number(spoken_tokens(raw))
        value = f"{n:,}" if n is not None else raw.upper()
        if "percent" in spoken_tokens(raw):
            value, label = value + "%", [w for w in label if bare(w) != "percent"]
    return value, " ".join(bare(w) for w in label).upper()


def word_kind_sets(text: str) -> set[str]:
    w = bare(text)
    kinds = set()
    if w in NEGATIONS:
        kinds.add("negation")
    if w in MONEY or re.search(r"[$₹]", text):
        kinds.add("money")
    if w in POWER:
        kinds.add("power")
    if w in CTA_VERBS:
        kinds.add("cta")
    return kinds


def is_content(text: str) -> bool:
    w = bare(text)
    return len(w) >= 3 and w not in FUNCTION and w not in VERBS


def noun_phrases(texts: list[str]) -> list[tuple[int, int]]:
    """Determiner/number + content words ('the edit', 'one reel', 'your next video'): concrete-noun spans.
    The determiner is excluded from the span; '-ing'/'-ed' words only count right after a determiner."""
    out, i = [], 0
    while i < len(texts) - 1:
        if bare(texts[i]) in DETERMINERS and not re.search(r"[.,!?;:]$", texts[i]):
            j = i + 1
            while j < len(texts) and (is_content(texts[j]) and not bare(texts[j]).endswith(("ing", "ed"))
                                      or j == i + 1 and len(bare(texts[j])) >= 3 and bare(texts[j]) not in FUNCTION):
                if re.search(r"[.,!?;:]$", texts[j]) or j - i >= 3:
                    break
                j += 1
            last = j if j < len(texts) and j - i < 3 and is_content(texts[j]) else j - 1
            if last > i:
                out.append((i + 1, last))
                i = last + 1
                continue
        i += 1
    return out


def enumeration(texts: list[str]) -> list[tuple[int, int]] | None:
    """'Read the script, hit record, and the reel builds itself.' -> three item spans, else None.
    A list is 3+ comma-separated items of <= 5 words in one sentence, the last opened by 'and'/'or'
    ('step by step, so you can' is not one), or 2+ clause-initial first/second/third markers."""
    s0 = 0
    for k, t in enumerate(texts):
        if re.search(r"[.!?]$", t) or k == len(texts) - 1:
            if items := _items(texts, s0, k):
                return items
            s0 = k + 1
    markers = [k for k, t in enumerate(texts) if bare(t) in LIST_MARKERS
               and (k == 0 or re.search(r"[,;:.!?]$", texts[k - 1]))]
    if len(markers) < 2:
        return None
    bounds = markers + [len(texts)]
    return [(bounds[n], bounds[n + 1] - 1) for n in range(len(markers))]


def _items(texts: list[str], s: int, e: int) -> list[tuple[int, int]] | None:
    items, start = [], s
    for k in range(s, e + 1):
        if texts[k].endswith(",") or k == e:
            items.append((start, k))
            start = k + 1
    if len(items) < 3 or bare(texts[items[-1][0]]) not in ("and", "or"):
        return None
    items[-1] = (items[-1][0] + 1, items[-1][1])
    longest = max(b - a for a, b in items[1:])
    items[0] = (max(items[0][0], items[0][1] - longest), items[0][1])     # drop a lead-in ('I like apples')
    return None if any(b - a > 4 or b < a for a, b in items) else items


_BREAKS = frozenset("and or but so because before after while if then than with from to of in on at by for".split())


def label(texts: list[str], a: int, content_only: bool = False) -> str:
    """Upper-case label of <= 4 words from texts[a]: it skips a leading determiner and stops at the
    clause end, at a conjunction or preposition, or at another function word once it has 2 words.
    content_only keeps just the next 2 content words ('of the work' -> 'WORK')."""
    out = []
    for t in texts[a:]:
        w = bare(t)
        if content_only:
            if w not in FUNCTION and len(w) >= 2:
                out.append(w.upper())
        elif out and (len(out) == 4 or w in _BREAKS or (w in FUNCTION and len(out) >= 2)):
            break
        elif w not in DETERMINERS or out:
            out.append(w.upper())
        if re.search(r"[,;:.!?]$", t) or (content_only and len(out) == 2):
            break
    return " ".join(out)


def item_text(texts: list[str]) -> str:
    words = [bare(t) for t in texts]
    while words and words[0] in ("and", "or", "then", "the", "a", "an"):
        words = words[1:]
    return " ".join(words).upper()


def icon_for(texts: list[str]) -> str | None:
    for t in texts:
        if (icon := _ICON_OF.get(bare(t))):
            return icon
    return None


def glyph_for(texts: list[str], last: bool = True) -> str | None:
    """Card glyph for a phrase: its head noun (the last trigger word), or the first with last=False."""
    hits = [g for t in texts if (g := _GLYPH_OF.get(bare(t)))]
    return (hits[-1] if last else hits[0]) if hits else None


def card_glyph(texts: list[str], a: int, b: int, end: int | None = None) -> str | None:
    """A text card's glyph: the state its label names ('the edit was finished' -> EDIT: DONE -> circle-check),
    else the phrase's head noun, else the first trigger word up to `end`."""
    stop = (b if end is None else end) + 1
    state = next((_STATE_OF[bare(t)] for t in texts[a:stop] if bare(t) in _STATE_OF), None)
    return GLYPH_STATE[state] if state else glyph_for(texts[a:b + 1]) or glyph_for(texts[a:stop], False)


def starts_with_marker(line: str, markers=CONTRAST + LIST_MARKERS) -> bool:
    head = " ".join(bare(t) for t in line.split()[:3])
    return any(head == m or head.startswith(m + " ") for m in markers)


def estimate_spans(texts: list[str], t0: float = 0.0, wps: float = 2.75) -> list[tuple[float, float]]:
    """Read-time estimate at ~165 wpm (trends-2026 T11 budgets 2.7 w/s); longer words take longer and
    trimmed pauses follow punctuation (editing-pace S1: 0.15-0.30 s between sentences)."""
    base, t, out = 1.0 / wps, t0, []
    for text in texts:
        letters = len("".join(spoken_tokens(text))) or 1
        dur = base * (0.55 + 0.09 * letters)
        out.append((round(t, 3), round(t + dur, 3)))
        t += dur + (0.25 if text[-1] in ".!?" else 0.12 if text[-1] in ",;:" else 0.0)
    return out


def shot_energy(line: str, texts: list[str], first: bool, last: bool) -> float:
    """Shot energy before the pace bias (motion-pack DESIGN 3.3): hook 0.8, last shot 0.6, body 0.5;
    +0.1 for '!', a number or 2+ power words, +0.05 for a question, -0.1 for an 18+ word line."""
    e = 0.8 if first else 0.6 if last else 0.5
    e += 0.1 * ("!" in line) + 0.05 * line.rstrip().endswith("?") + 0.1 * bool(number_phrases(texts))
    return e + 0.1 * (sum(bare(t) in POWER for t in texts) >= 2) - 0.1 * (len(texts) >= 18)


def stress(texts: list[str], wi: int) -> float:
    """Stressed-word rank (DESIGN 3.3): number 3 > money 2 > negation/power 1.5 > content 0.5 > function 0."""
    if any(a <= wi <= b for a, b in number_phrases(texts)):
        return 3.0
    kinds = word_kind_sets(texts[wi])
    return 2.0 if "money" in kinds else 1.5 if kinds & {"negation", "power"} else 0.5 if is_content(texts[wi]) else 0.0


def hook_title(texts: list[str], chip_at: int | None = None) -> str:
    """Hook title words (motion-pack DESIGN R-H2): a line of <= 7 words, else its first clause, else up
    to the last number/noun phrase ending in words 3-7, else the first 5 words; it stops before a number
    chip at word >= 2 (no duplicate) and never ends on a function word."""
    clean = [t.strip(".,;:!?\"'") for t in texts]
    if len(texts) <= 7:
        return " ".join(w for w in clean if w)
    stop = next((k for k, t in enumerate(texts) if re.search(r"[,;:.!?]$", t)), len(texts) - 1)
    ends = [b for a, b in number_phrases(texts) + noun_phrases(texts) if 2 <= b <= 6]
    words = clean[:stop + 1] if stop < 7 else clean[:max(ends) + 1] if ends else clean[:5]
    if chip_at is not None and 2 <= chip_at < len(words):
        words = words[:chip_at]
    while len(words) > 2 and bare(words[-1]) in FUNCTION:
        words = words[:-1]
    return " ".join(w for w in words if w)


def cta_text(texts: list[str]) -> str | None:
    """The creator's own CTA clause ('Follow for the next breakdown'), never an invented offer."""
    k = next((k for k, t in enumerate(texts) if bare(t) in CTA_VERBS), None)
    if k is None:
        return None
    words = []
    for t in texts[k:k + 5]:
        words.append(bare(t))
        if re.search(r"[,;:.!?]$", t):
            break
    return " ".join(words).capitalize()


_STATE = {"DONE": "finished done complete completed ready built solved fixed", "WASTED": "waste wasted wasting lost",
          "FREE": "free", "FAST": "fast faster quick quickly instantly", "SOLD": "sold"}
_STATE_OF = {w: k for k, ws in _STATE.items() for w in ws.split()}
_PREPS = frozenset("from in on with for into".split())


def hook_paraphrase(texts: list[str]) -> str | None:
    """HS08: the hook title restates the line with its number first, never word for word.
    'Most creators waste three hours editing one reel.' -> '3 HOURS PER REEL?'. None without a number."""
    nums = number_phrases(texts)
    if not nums:
        return None
    a, b = nums[0]
    value, unit = number_display(texts[a:b + 1])
    out = [value] + unit.split()[:2]
    ce = next((k for k in range(b, len(texts)) if re.search(r"[,;:.!?]$", texts[k])), len(texts) - 1)
    if unit and not unit.endswith("S") and b < ce and is_content(texts[b + 1]):
        out.append(bare(texts[b + 1]).upper())          # '3 SECOND HOOK'
    for x, y in noun_phrases(texts):
        if b + 1 < x <= ce:
            det, prev = bare(texts[x - 1]), bare(texts[x - 2]) if x >= 2 else ""
            noun = [bare(t).upper() for t in texts[x:y + 1]][-2:]
            if det in ("one", "a", "an", "each", "every", "per"):
                out += ([prev.upper(), "1"] if prev in _PREPS else ["PER"]) + noun
            elif det in _PREPS:
                out += [det.upper()] + noun
            break
    if len(out) < 2:
        return None
    return " ".join(out[:6]) + "?"


def broll_label(texts: list[str], a: int, b: int, end: int | None = None) -> str:
    """A text card's label that names the idea without repeating the spoken words: the head noun of the
    phrase texts[a..b] plus a state word up to `end` ('the edit was finished' -> 'EDIT: DONE'); else the
    noun alone (TR T34, <= 4 words)."""
    heads = [bare(t).upper() for t in texts[a:b + 1] if is_content(t) and bare(t) not in DETERMINERS]
    heads = heads[:1] if heads and re.search(r"(ER|EST|LY)$", heads[-1]) else heads   # 'pause longer' -> PAUSE
    noun = heads[-1:] or label(texts, a, content_only=True).split()[:1]
    state = next((_STATE_OF[bare(t)] for t in texts[a:(b if end is None else end) + 1] if bare(t) in _STATE_OF), None)
    return f"{noun[0]}: {state}" if noun and state and state != noun[0] else " ".join(noun) or label(texts, a)


def display_words(texts: list[str]) -> list[str]:
    """Caption display: a one-word spoken number before its unit shows as digits ('three hours' ->
    '3 hours'); everything else is shown as written. Timing and matching still use the written words."""
    out = list(texts)
    for a, b in number_phrases(texts):
        if a < b and (not is_numeric(texts[a + 1], "x") or bare(texts[a + 1]) == "percent") \
                and not re.search(r"\d", texts[a]):
            n = words_to_number(spoken_tokens(texts[a]))
            if n is not None:
                m = re.match(r"^(\W*)(.*?)(\W*)$", texts[a])
                out[a] = f"{m.group(1)}{n}{m.group(3)}"
    return out
