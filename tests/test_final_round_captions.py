"""Final-round caption fixes (council 6, captions-visual 2.1).

- beast-hype's pop family (Bangers) sits on the same cap height as the house captions: cap-height parity,
  not px parity. Bangers caps measure 0.697 em on rendered frames against Inter 800's 0.727 em, so 76 px
  Bangers read ~4 % small; the pop family sets 79 px and keeps the 2-line rule inside the 276 px band.
- hype (1-2 words, cap 3): a one-word chunk held shorter than hold_need(1) merges into a neighbour when a
  legal merge exists (same sentence, inside the cap, no dangling end). 'WHAT' in the demo has none: 'WHAT IF'
  and 'WHAT IF THE' dangle and 'WHAT IF THE EDIT' is 4 words, so it stays (tests/test_polish_captions pins it).
"""
import re
from pathlib import Path

from reel_director import stagger
from reel_director.compiler import CAPTION_FAMILIES, caption_chunks

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "src" / "reel_director" / "web" / "reel.css").read_text()
MJS = (ROOT / "src" / "reel_director" / "web" / "reel.mjs").read_text()
CAP_EM = {"Inter": 0.727, "Bangers": 0.697}   # cap height per em; Bangers measured: 'H' 53 px at 76 px, 55 px at 79 px


def family_px(fam: str) -> int:
    return int(re.search(r"\.cap-%s \.cap-in \{[^}]*font-size: (\d+)px" % fam, CSS).group(1))


def asr(line, t0=0.2, step=0.3):
    out, t = [], t0
    for w in line.split():
        out.append({"w": w, "s": round(t, 3), "e": round(t + step - 0.02, 3)})
        t += step
    return out


def texts(words, chunks):
    return [" ".join(words[i]["w"] for i in c) for c in chunks]


def test_pop_captions_match_the_house_cap_height():
    px, house = family_px("pop"), 76 * CAP_EM["Inter"]                 # house cap line: 55.3 px
    assert abs(px * CAP_EM["Bangers"] - house) <= 1.0, px                # cap-height parity
    assert abs(76 * CAP_EM["Bangers"] - house) > 1.5                     # 76 px Bangers was short of it
    assert 64 <= px <= 84 and 2 * px * 1.08 <= 276                      # floor, and two lines fit the band
    assert all(family_px(f) == 76 for f in ("karaoke", "pill", "boxed"))  # other presets untouched
    assert "'cap-in': 64" in MJS and "MAX_LINES = { 'cap-in': 2 }" in MJS and "'cap-in': 276" in MJS


def test_hype_flash_merges_when_the_cap_allows(monkeypatch):
    max_w, max_c = CAPTION_FAMILIES["pop"]
    words = asr("Here's the exact system, step by step, so you can copy it.", step=0.2)
    got = caption_chunks(words, max_w, max_c)
    assert all(len(c) > 1 for c in got), texts(words, got)              # no 0.2 s 'SYSTEM,' flash
    assert all(len(c) <= 3 and not stagger.dangles(words[c[-1]]["w"]) for c in got[:-1])
    monkeypatch.setattr(stagger, "HYPE_FLASH", 0.0)                      # the rule is what changed it
    assert "system," in texts(words, caption_chunks(words, max_w, max_c))


def test_what_stays_when_every_merge_dangles():
    t = [("What", 4.26, 4.68), ("if", 4.68, 4.92), ("the", 4.92, 5.12), ("edit", 5.12, 5.44), ("was", 5.44, 5.82),
         ("finished", 5.82, 6.22), ("before", 6.22, 6.64), ("you", 6.64, 6.94), ("even", 6.94, 7.3),
         ("pressed", 7.3, 7.72), ("record?", 7.72, 8.16)]                # demo ASR times (beast-hype 'turn')
    words = [{"w": w, "s": s, "e": e} for w, s, e in t]
    got = texts(words, caption_chunks(words, *CAPTION_FAMILIES["pop"]))
    assert got[:2] == ["What", "if the edit"], got
    assert stagger.dangles("if") and stagger.dangles("the") and len("What if the edit".split()) > 3


def test_non_hype_families_ignore_the_flash_rule(monkeypatch):
    lines = ["Read the script, hit record, and the reel builds itself.",
             "What if the edit was finished before you even pressed record?",
             "Here's the exact system, step by step, so you can copy it."]
    fams = [f for f, (w, _) in CAPTION_FAMILIES.items() if w > 2]
    cases = [(f, asr(x, step=s)) for f in fams for x in lines for s in (0.2, 0.3)]
    now = [caption_chunks(w, *CAPTION_FAMILIES[f]) for f, w in cases]
    monkeypatch.setattr(stagger, "HYPE_FLASH", 0.0)
    assert now == [caption_chunks(w, *CAPTION_FAMILIES[f]) for f, w in cases]
    assert now == [caption_chunks(w, *CAPTION_FAMILIES[f]) for f, w in cases]   # deterministic
