"""Spoken-form normalization so script text and ASR output compare word for word."""
import re

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
         "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"))
# Words that sound the same compare equal: audio can't tell "reel" from "real", so a take must
# never be failed as a misread for Whisper's spelling choice. Each maps to its group's first word.
_HOMOPHONES = ("reel real|reels reals|there their they're|to too two|for four fore|your you're|its it's|"
               "whose who's|here hear|right write rite|no know|new knew|by buy bye|one won|whole hole|"
               "weather whether|which witch|would wood|through threw|see sea|site sight cite|break brake|"
               "piece peace|week weak|hour our|hours ours|eight ate|seen scene|cell sell|lets let's")
# Spelling variants (OK/okay, US/UK) are the same spoken word for the same reason. An explicit list:
# edit distance or suffix rules would also hide real misreads (can/can't, then/than, our/or).
_SPELLINGS = ("okay ok|color colour|colors colours|colored coloured|favorite favourite|favorites favourites|"
              "favor favour|honor honour|humor humour|labor labour|neighbor neighbour|behavior behaviour|"
              "flavor flavour|flavors flavours|rumor rumour|gray grey|center centre|centers centres|"
              "theater theatre|meter metre|meters metres|liter litre|fiber fibre|program programme|"
              "programs programmes|catalog catalogue|dialog dialogue|analyze analyse|analyzed analysed|"
              "organize organise|organized organised|organizing organising|realize realise|realized realised|"
              "recognize recognise|apologize apologise|optimize optimise|optimized optimised|"
              "optimizing optimising|customize customise|customized customised|prioritize prioritise|"
              "monetize monetise|monetized monetised|personalize personalise|personalized personalised|"
              "traveled travelled|traveling travelling|canceled cancelled|canceling cancelling|"
              "modeling modelling|labeled labelled|jewelry jewellery|defense defence|license licence|"
              "offense offence|cheque check|tire tyre|pajamas pyjamas|skeptical sceptical")
_CANON = {w: g.split()[0] for g in (_HOMOPHONES + "|" + _SPELLINGS).split("|") for w in g.split()}
_ORDINAL = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
            "nine": "ninth", "twelve": "twelfth"}
_CURRENCY = {"$": "dollars", "₹": "rupees", "€": "euros", "£": "pounds"}
_SUFFIX_SCALE = {"k": "thousand", "m": "million", "mn": "million", "b": "billion", "bn": "billion"}
_SYMBOLS = {"&": " and ", "+": " plus ", "@": " at "}
_TOKEN = re.compile(r"[$₹€£]?\d+(?:\.\d+)?(?:(?:st|nd|rd|th|k|mn|m|bn|b)(?![a-z]))?|[a-z']+|%")

FILLERS = frozenset("um umm uh uhm uhh er erm ah ahh hmm hm mm mhm".split())
# Contractions and short forms with their spoken long forms: "it's" read as "it is" is the same line. Keys are
# canonical tokens. Applied only when comparing token runs that differ in count (never inside
# norm_tokens), so the its/it's, your/you're and lets/let's homophone groups above stay intact.
CONTRACTIONS = {k: v.split() for k, v in {
    "its": "it is", "lets": "let us", "your": "you are", "there": "they are", "whose": "who is",
    "i'm": "i am", "i've": "i have", "i'll": "i will", "i'd": "i would", "you've": "you have",
    "you'll": "you will", "you'd": "you would", "we're": "we are", "we've": "we have", "we'll": "we will",
    "they've": "they have", "they'll": "they will", "he's": "he is", "she's": "she is", "that's": "that is",
    "what's": "what is", "there's": "there is", "here's": "here is", "how's": "how is",
    "where's": "where is", "it'll": "it will", "that'll": "that will", "don't": "do not",
    "doesn't": "does not", "didn't": "did not", "can't": "can not", "won't": "will not", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not", "haven't": "have not",
    "hasn't": "has not", "hadn't": "had not", "wouldn't": "would not", "shouldn't": "should not",
    "couldn't": "could not", "gonna": "going to", "wanna": "want to", "gotta": "got to", "y'all": "you all",
    "alright": "all right", "cannot": "can not",
    # written short forms read out in full ("10x" -> "ten times")
    "x": "times", "vs": "versus", "mins": "minutes", "min": "minute", "hrs": "hours", "hr": "hour",
    "secs": "seconds", "sec": "second", "etc": "et cetera", "approx": "approximately", "mr": "mister",
    "mrs": "missus", "dr": "doctor", "govt": "government", "pct": "percent", "w": "with",
}.items()}


def number_to_words(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        return [_TENS[tens]] + ([_ONES[ones]] if ones else [])
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return [_ONES[hundreds], "hundred"] + (number_to_words(rest) if rest else [])
    if n >= 10 ** 12:                     # past the largest scale: read the digits
        return [_ONES[int(d)] for d in str(n)]
    size, name = next((s, w) for s, w in _SCALES if n >= s)
    hi, rest = divmod(n, size)
    return number_to_words(hi) + [name] + (number_to_words(rest) if rest else [])


def _ordinal(n: int) -> list[str]:
    ws = number_to_words(n)
    last = ws[-1]
    last = _ORDINAL.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return ws[:-1] + [last]


def _number_tokens(tok: str) -> list[str]:
    """'$2.5m' -> two point five million dollars; '21st' -> twenty first; '10k' -> ten thousand."""
    cur = _CURRENCY.get(tok[0])
    if cur:
        tok = tok[1:]
    whole, frac, suffix = re.fullmatch(r"(\d+)(?:\.(\d+))?([a-z]*)", tok).groups()
    if suffix in ("st", "nd", "rd", "th") and not frac:
        return _ordinal(int(whole))
    out = number_to_words(int(whole))
    if frac:
        out += ["point"] + [_ONES[int(d)] for d in frac]
    if suffix:
        out.append(_SUFFIX_SCALE.get(suffix, suffix))
    return out + ([cur] if cur else [])


def norm_tokens(text: str) -> list[str]:
    """'3,000%' -> ['three', 'thousand', 'percent']; punctuation and case dropped, homophones merged."""
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower()).replace("’", "'")
    text = re.sub(r"[&+@]", lambda m: _SYMBOLS[m.group(0)], text)
    # Dotted initialisms are one word: "A.I." -> ai, "p.m." -> pm, "U.S.A." -> usa.
    text = re.sub(r"\b[a-z](?:\.[a-z])+\b\.?", lambda m: m.group(0).replace(".", ""), text)
    out: list[str] = []
    for tok in _TOKEN.findall(text):
        if tok[0].isdigit() or tok[0] in _CURRENCY:
            out.extend(_number_tokens(tok))
        elif tok == "%":
            out.append("percent")
        else:
            tok = tok.strip("'")
            if tok:
                out.append(tok)
    for k in range(len(out) - 1):         # "$2.5 million" is said "two point five million dollars"
        if out[k] in _CURRENCY.values() and out[k + 1] in ("thousand", "million", "billion"):
            out[k], out[k + 1] = out[k + 1], out[k]
    return [_CANON.get(t, t) for t in out]


_UNITS = {w: i for i, w in enumerate(_ONES)} | {w: 10 * i for i, w in enumerate(_TENS) if w != "_"}
_UNITS |= {_CANON[w]: _UNITS[w] for w in _UNITS if w in _CANON}     # "two" is canonically "to"
_MULT = {"thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9}


def spoken_value(tokens: list[str]) -> tuple[float, tuple[str, ...]] | None:
    """The number a run of normalized tokens says, plus its trailing words:
    'twenty five hundred dollars' -> (2500, ('dollars',)). None if it doesn't start with one."""
    total, cur, seen, i = 0.0, 0.0, False, 0
    while i < len(tokens):
        t = tokens[i]
        if t in _UNITS:
            cur += _UNITS[t]
        elif t == "hundred":
            cur = (cur or 1) * 100
        elif t in _MULT:
            total, cur = total + (cur or 1) * _MULT[t], 0.0
        elif t == "point" and seen and i + 1 < len(tokens) and tokens[i + 1] in _UNITS:
            scale = 0.1
            while i + 1 < len(tokens) and tokens[i + 1] in _UNITS and _UNITS[tokens[i + 1]] < 10:
                cur, scale, i = cur + _UNITS[tokens[i + 1]] * scale, scale / 10, i + 1
        elif not (t == "and" and seen or t == "a" and not seen and tokens[i + 1:i + 2] in (["hundred"], ["thousand"],
                                                                                        ["million"], ["billion"])):
            break
        seen = seen or t not in ("a", "and")
        i += 1
    return (round(total + cur, 6), tuple(tokens[i:])) if seen else None
