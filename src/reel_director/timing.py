"""Word timing for a shot: estimated before recording, aligned to the take after.

Everything downstream (captions, cues, cuts) reads word times from here, so swapping
estimated times for real ones re-times the whole edit.
"""
import difflib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from .schema import Script, Shot
from .textnorm import CONTRACTIONS, FILLERS, norm_tokens, spoken_value

@dataclass
class Span:
    start: float
    end: float


@dataclass
class Alignment:
    times: list[Span]       # one per script word, media time
    matched: int            # script words read exactly
    total: int
    misread: int = 0        # script words said differently ("days" for "hours")
    used_asr: frozenset[int] = frozenset()   # ASR words that belong to the script read
    hits: dict[int, tuple[int, ...]] = field(default_factory=dict)  # script word -> ASR words heard for it
    misread_words: frozenset[int] = frozenset()   # which script words were misread
    ignored: frozenset[int] = frozenset()   # ASR words placed where there is no voice (hallucinations)

    @property
    def coverage(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def heard(self) -> frozenset[int]:
        """Script words the take actually backs with ASR words; the rest are interpolated."""
        return frozenset(self.hits)


def estimate(shot: Shot, wpm: float = 165.0) -> list[Span]:
    """Rough read timing: longer words take longer, punctuation adds a breath."""
    base = 60.0 / wpm
    t, out = 0.0, []
    for w in shot.words:
        dur = base * (0.55 + 0.09 * len("".join(w.norm)))
        out.append(Span(round(t, 3), round(t + dur, 3)))
        t += dur + (0.35 if w.text[-1] in ".!?" else 0.18 if w.text[-1] in ",;:" else 0.0)
    return out


def load_asr_words(path: str | Path) -> list[dict]:
    """Accepts mlx/openai whisper words ({word,start,end}) or motion-pack ({w,s,e}).
    Keeps prep's "speech": False flag (a word placed where the VAD heard no voice)."""
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, dict):
        raw = raw.get("words") or [w for seg in raw.get("segments", []) for w in seg["words"]]
    return [{"w": r.get("w", r.get("word", "")).strip(), "s": float(r.get("s", r.get("start"))),
             "e": float(r.get("e", r.get("end"))), **({"speech": False} if r.get("speech") is False else {})}
            for r in raw]


def _asr_tokens(asr: list[dict]) -> tuple[list[str], list[int]]:
    """Normalized ASR tokens and the ASR word each came from. A number Whisper split across
    words ("10" + ",000") is normalized as one."""
    toks, owner, j = [], [], 0
    while j < len(asr):
        text, owners = asr[j]["w"].strip(), [j]
        while (j + 1 < len(asr) and re.search(r"\d$", text)
               and re.match(r"[,.]\d", asr[j + 1]["w"].strip())):
            j += 1
            text += asr[j]["w"].strip()
            owners.append(j)
        t = norm_tokens(text)
        toks += t
        owner += [owners[min(len(owners) - 1, k * len(owners) // len(t))] for k in range(len(t))]
        j += 1
    return toks, owner


def _letter_groups(s: list[str], a: list[str]) -> list[tuple[list[int], list[int]]] | None:
    """Split two token runs into groups whose letters agree ('a i' | 'ai', 'set up' | 'setup');
    None when they can't be."""
    s = [t.replace("'", "") for t in s]
    a = [t.replace("'", "") for t in a]
    groups, i, j = [], 0, 0
    while i < len(s) and j < len(a):
        gi, gj, ls, la = [i], [j], s[i], a[j]
        i, j = i + 1, j + 1
        while ls != la:
            if la.startswith(ls) and i < len(s):
                ls += s[i]
                gi.append(i)
                i += 1
            elif ls.startswith(la) and j < len(a):
                la += a[j]
                gj.append(j)
                j += 1
            else:
                return None
        groups.append((gi, gj))
    return groups if i == len(s) and j == len(a) else None


def _expand(toks: list[str]) -> tuple[list[str], list[int]]:
    out, back = [], []
    for k, t in enumerate(toks):
        e = CONTRACTIONS.get(t, [t])
        out += e
        back += [k] * len(e)
    return out, back


def _bare(t: str) -> str:
    """"spacex's" -> "spacex": a possessive 's is a short sibilant Whisper often drops ("SpaceX's first" heard as
    "SpaceX first", then heard with the 's once the line is its prompt). Never an "is" contraction: "he's" read
    as "he" stays a misread."""
    return t[:-2] if t.endswith("'s") and t not in CONTRACTIONS else t


def _variant_groups(s: list[str], a: list[str]) -> list[tuple[set[int], set[int]]] | None:
    """The same words in another spelling or split: 'A.I.'/'a i', 'alright'/'all right',
    "it's"/'it is', "spacex's"/'spacex'. Groups of (script token idx, ASR token idx), or None."""
    g = _letter_groups(s, a)
    if g is not None:
        return [(set(gi), set(gj)) for gi, gj in g]
    (es, bs), (ea, ba) = _expand(s), _expand(a)
    g = _letter_groups(es, ea)
    if g is not None:
        return [({bs[i] for i in gi}, {ba[j] for j in gj}) for gi, gj in g]
    g = _letter_groups([_bare(t) for t in s], [_bare(t) for t in a])
    return None if g is None else [(set(gi), set(gj)) for gi, gj in g]


def _same_number(script_tokens: list[str], heard_tokens: list[str]) -> bool:
    """'$2,500' read as 'twenty five hundred dollars' says the same number."""
    want, got = spoken_value(script_tokens), spoken_value(heard_tokens)
    return bool(want and got and abs(want[0] - got[0]) < 1e-6 and set(want[1]) <= set(got[1])
                and len(script_tokens) > len(want[1]))


def word_map(shot: Shot, asr: list[dict]) -> tuple[dict[int, list[int]], set[int]]:
    """Script word -> the ASR words it was heard as, and which script words were misread.

    Aligned reversed so ties resolve toward the last attempt of a repeated phrase. A word is
    read exactly only when every one of its tokens is ("3,000" said as "three" drops
    "thousand"). A token run that differs in count is the same words respelled when its
    letters agree ("A.I." / "AI", "it's" / "it is"), else a different read: its non-filler
    ASR words are attached to the script words, so they are never cut as junk and QA names them.
    """
    s_tok, s_owner = [], []
    for i, w in enumerate(shot.words):
        s_tok += w.norm
        s_owner += [i] * len(w.norm)
    a_tok, a_owner = _asr_tokens(asr)
    hit: dict[int, list[int]] = {}
    exact: set[int] = set()       # script tokens heard as written (or respelled)

    def add(si: int, aj: int, ok: bool) -> None:
        hit.setdefault(s_owner[si], []).append(a_owner[aj])
        if ok:
            exact.add(si)

    ops = difflib.SequenceMatcher(a=s_tok[::-1], b=a_tok[::-1], autojunk=False).get_opcodes()
    n_s, n_a = len(s_tok), len(a_tok)
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        fs, fa = list(range(n_s - i2, n_s - i1)), list(range(n_a - j2, n_a - j1))
        # next to an exactly read stretch: a different read of these words, not unrelated speech
        anchored = any(0 <= m < len(ops) and ops[m][0] == "equal" for m in (k - 1, k + 1))
        if tag == "equal":
            for si, aj in zip(fs, fa):
                add(si, aj, True)
        elif tag == "replace":
            groups = _variant_groups([s_tok[k] for k in fs], [a_tok[k] for k in fa])
            said = [k for k in fa if a_tok[k] not in FILLERS]
            if groups is not None:
                for gi, gj in groups:
                    for si in gi:
                        for aj in sorted(gj):
                            add(fs[si], fa[aj], True)
            elif len(fs) == len(fa) and len(said) == len(fa):      # misreads keep position
                for si, aj in zip(fs, fa):
                    add(si, aj, False)
            elif anchored:                                         # fillers stay junk
                for n, aj in enumerate(said):
                    add(fs[min(len(fs) - 1, n * len(fs) // len(said))], aj, False)
        # "delete": script tokens nobody said; "insert": fillers, restarts, ad-libs (junk)
    n_exact: dict[int, int] = {}
    for si in exact:
        n_exact[s_owner[si]] = n_exact.get(s_owner[si], 0) + 1
    misread = set()
    for i, js in hit.items():
        if n_exact.get(i, 0) < len(shot.words[i].norm):
            heard = [t for j in sorted(set(js)) for t in norm_tokens(asr[j]["w"])]
            if not _same_number(shot.words[i].norm, heard):
                misread.add(i)
    return hit, misread


def _align(shot: Shot, asr: list[dict]) -> Alignment:
    hit, misread = word_map(shot, asr)
    times: list[Span | None] = [None] * len(shot.words)
    for i, js in hit.items():
        times[i] = Span(min(asr[j]["s"] for j in js), max(asr[j]["e"] for j in js))
    used = frozenset(j for js in hit.values() for j in js)
    return Alignment(_fill_gaps(times, shot), matched=len(hit) - len(misread), total=len(shot.words),
                     misread=len(misread), used_asr=used,
                     hits={i: tuple(sorted(set(js))) for i, js in hit.items()}, misread_words=frozenset(misread))


def align(shot: Shot, asr: list[dict]) -> Alignment:
    """Map each script word to its time in the take; fillers and restarts are skipped.

    Uses the last occurrence on restarts ("here is, here is how") because the keeper read is
    usually the final one. Words flagged "speech": False (Whisper text over silence, often a
    repeat of the line's end) are used only when the voiced words can't place as many script words.
    """
    al = _align(shot, asr)
    off = frozenset(j for j, w in enumerate(asr) if w.get("speech") is False)
    if not off & al.used_asr:
        return replace(al, ignored=off)
    keep = [j for j in range(len(asr)) if j not in off]
    alt = _align(shot, [asr[j] for j in keep])
    if alt.matched + alt.misread < al.matched + al.misread:
        return replace(al, ignored=off - al.used_asr)    # the VAD missed a real word: keep it
    return replace(alt, used_asr=frozenset(keep[j] for j in alt.used_asr), ignored=off,
                   hits={i: tuple(keep[j] for j in js) for i, js in alt.hits.items()})


def _fill_gaps(times: list[Span | None], shot: Shot) -> list[Span]:
    """Interpolate words the ASR missed between their matched neighbours."""
    if not any(times):
        return estimate(shot)
    out = list(times)
    known = [i for i, t in enumerate(out) if t]
    for i, t in enumerate(out):
        if t:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is not None and nxt is not None:
            a, b = out[prev].end, out[nxt].start
            step = (b - a) / (nxt - prev)
            out[i] = Span(a + step * (i - prev - 1), a + step * (i - prev))
        elif prev is not None:
            g = 0.3 * (i - prev)
            out[i] = Span(out[prev].end + g - 0.3, out[prev].end + g)
        else:
            g = 0.3 * (nxt - i)
            out[i] = Span(max(0.0, out[nxt].start - g), max(0.0, out[nxt].start - g + 0.3))
    return out
