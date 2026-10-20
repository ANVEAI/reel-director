"""TEAM VISUALS (v2 real-footage contract P4/P5/P6, 'B-roll visuals', 'Look', 'Title legibility'): vendored icons and
their licence, the lexicon's glyph picks, skin-safe preset tones (skin dE2000 <= 3, measured on the founder's takes),
WCAG contrast of the title backings and card type, the layout hooks in reel.css, and the runtime's seek-safety."""
import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from reel_director import icons, lexicon as lx, presets, stage
from reel_director.director import direct
from reel_director.schema import parse_script

ROOT = Path(__file__).resolve().parents[1]
MJS = (stage.WEB / "reel.mjs").read_text()
CSS = (stage.WEB / "reel.css").read_text()
LINES = json.loads((ROOT / "examples" / "demo" / "script-lines-only.json").read_text())
# skin patches (24 x 24 px means) from work/real-1 prepped takes: hook-1, turn-1, cta-1 cheeks and forehead
SKIN = [(239.5, 205.6, 178.8), (222.6, 158.9, 129.4), (182, 130.5, 107.2), (190.7, 140.2, 113.7), (162.2, 116.2, 96.9),
        (195.1, 148.6, 124.9), (222.5, 168.4, 132.7), (185.7, 127.1, 109.3), (204.7, 155.4, 133.6)]
LUMA = (0.2126, 0.7152, 0.0722)
V1_COOL = {"temp": -0.14, "contrast": 0.196, "slope": [0.972, 1, 1.049], "power": [1.014, 1, 0.986], "sat": 1.07,  # v1: cool-tech
           "split": {"shadowHue": 258.5, "shadowSat": 0.21, "highHue": 244.5, "highSat": 0.056, "balance": -0.035}, "fade": 0.0035}


def js_obj(name: str) -> dict:
    """A small literal object from reel.mjs (const NAME = {...};) as Python data."""
    body = re.search(r"const %s = (\{.*?\});" % name, MJS, re.S).group(1)
    body = re.sub(r",\s*([}\]])", r"\1", re.sub(r"//[^\n]*", "", body).replace("'", '"'))
    return json.loads(re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', body))


# ---- WCAG and colour -----------------------------------------------------------------------------
def lum(c):
    lin = [v / 255 / 12.92 if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in c]
    return sum(w * v for w, v in zip(LUMA, lin))


def ratio(a, b):
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def hexrgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def readable(c, bg_l, mn=4.5):
    """reel.mjs readable(): the accent, else mixed toward white (dark backing) or ink (light) until it reads."""
    to = (11, 11, 15) if bg_l > 0.18 else (255, 255, 255)
    for k in range(21):
        m = [math.floor(v + (t - v) * k / 20 + 0.5) for v, t in zip(c, to)]
        if ratio(lum(m), bg_l) >= mn:
            return m
    return list(to)


def lab(rgb):
    lin = [v / 255 / 12.92 if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in rgb]
    X = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    Y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    Z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116  # noqa: E731
    return 116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))


def de2000(p, q):
    (L1, a1, b1), (L2, a2, b2), r = p, q, math.pi / 180
    Cb = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1, h2 = math.degrees(math.atan2(b1, a1p)) % 360, math.degrees(math.atan2(b2, a2p)) % 360
    dh = h2 - h1 - 360 if h2 - h1 > 180 else h2 - h1 + 360 if h2 - h1 < -180 else h2 - h1
    dH = 2 * math.sqrt(C1p * C2p) * math.sin(dh * r / 2)
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hb = (h1 + h2 + (360 if h1 + h2 < 360 else -360)) / 2 if abs(h1 - h2) > 180 else (h1 + h2) / 2
    T = 1 - 0.17 * math.cos((hb - 30) * r) + 0.24 * math.cos(2 * hb * r) + 0.32 * math.cos((3 * hb + 6) * r) \
        - 0.2 * math.cos((4 * hb - 63) * r)
    SL, SC, SH = 1 + 0.015 * (Lb - 50) ** 2 / math.sqrt(20 + (Lb - 50) ** 2), 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    RT = -2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) * math.sin(60 * math.exp(-(((hb - 275) / 25) ** 2)) * r)
    dL, dC = (L2 - L1) / SL, (C2p - C1p) / SC
    return math.sqrt(dL ** 2 + dC ** 2 + (dH / SH) ** 2 + RT * dC * (dH / SH))


def grade_rgb(p, rgb):
    """Port of motion-pack layers/grade.js gradeRGB (the closed form the SVG filter emits), rgb in 0..1."""
    cl = lambda x: min(1.0, max(0.0, x))  # noqa: E731
    ss = lambda a, b, x: (lambda t: t * t * (3 - 2 * t))(cl((x - a) / (b - a)))  # noqa: E731
    sp = {"shadowHue": 0, "shadowSat": 0, "highHue": 0, "highSat": 0, "balance": 0, **p.get("split", {})}
    g, temp, tint = 2 ** (p.get("exposure", 0) / 2.2), p.get("temp", 0), p.get("tint", 0)
    wb, k, piv = (g * (1 + 0.1 * temp), g * (1 - 0.06 * tint), g * (1 - 0.1 * temp)), 14 * p.get("contrast", 0), p.get("pivot", 0.46)
    lg = lambda x: 1 / (1 + math.exp(-k * (x - piv)))  # noqa: E731
    f0, inv = (lg(0), 1 / (lg(1) - lg(0))) if k else (0, 1)
    v3 = lambda key, d: p.get(key, [d] * 3) if isinstance(p.get(key, d), list) else [p.get(key, d)] * 3  # noqa: E731
    slope, offset, power = v3("slope", 1), v3("offset", 0), v3("power", 1)
    c = [(lg(cl(x * wb[i])) - f0) * inv if k else cl(x * wb[i]) for i, x in enumerate(rgb)]
    c = [cl(max(v * slope[i] + offset[i], 0) ** power[i]) for i, v in enumerate(c)]
    lu = sum(w * v for w, v in zip(LUMA, c))
    c = [cl(lu + (v - lu) * p.get("sat", 1)) for v in c]

    def tone(h, s):
        h = ((h / 360) % 1) * 6
        hc = [cl(abs(h - 3) - 1), cl(2 - abs(h - 2)), cl(2 - abs(h - 4))]
        hl = sum(w * v for w, v in zip(LUMA, hc))
        return [(v - hl) * s * 0.5 for v in hc]
    lu, bal = sum(w * v for w, v in zip(LUMA, c)), sp["balance"]
    ws, wh = 1 - ss(0, 0.55 + bal * 0.4, lu), ss(0.45 + bal * 0.4, 1, lu)
    st, ht = tone(sp["shadowHue"], sp["shadowSat"]), tone(sp["highHue"], sp["highSat"])
    fade = p.get("fade", 0)
    return [cl(fade + (v + st[i] * ws + ht[i] * wh) * (1 - fade)) for i, v in enumerate(c)]


def skin_de(tone):
    return max(de2000(lab(s), lab([255 * v for v in grade_rgb(tone, [x / 255 for x in s])])) for s in SKIN)


# ---- icons and the lexicon -----------------------------------------------------------------------
def test_vendored_icons_carry_their_licence_and_hashes():
    lic = json.loads((icons.HERE / "LICENSES.json").read_text())["lucide"]
    assert lic["license"] == "ISC" and lic["package"] == "lucide-static" and (icons.HERE / "LICENSE").is_file()
    assert "ISC License" in (icons.HERE / "LICENSE").read_text()
    assert sorted(lic["files"]) == sorted(f"lucide/{i}.svg" for i in icons.ids()) and len(icons.ids()) >= 40
    for rel, sha in lic["files"].items():
        assert hashlib.sha256((icons.HERE / rel).read_bytes()).hexdigest() == sha, rel
    for i in icons.ids():                      # inline-safe: no script, no external reference
        s = icons.svg(i)
        assert s.startswith("<svg") and "<script" not in s and "href" not in s and "currentColor" not in s


def test_reel_css_icon_block_is_generated_from_the_vendored_set():
    a, b = CSS.index(icons.BEGIN), CSS.index(icons.END) + len(icons.END)
    assert CSS[a:b] == icons.css_block()
    assert len(re.findall(r'\.ico\[data-icon="[a-z0-9-]+"\]', CSS)) == len(icons.ids())


def test_every_glyph_the_lexicon_or_runtime_can_name_is_vendored():
    named = set(lx.GLYPH_WORDS) | set(lx.GLYPH_STATE.values()) | set(lx.PACK_GLYPH.values()) | set(js_obj("GLYPH_ALIAS").values())
    assert {g for g in named if not icons.exists(g)} == set()
    assert set(lx.PACK_GLYPH) == set(lx.ICON_WORDS)           # every pack sticker the director picks maps to a glyph


def test_glyph_picks_name_the_idea():
    turn = "What if the edit was finished before you even pressed record?".split()
    assert lx.card_glyph(turn, 3, 3, 7) == "circle-check"      # EDIT: DONE -> the state, not the noun
    assert lx.card_glyph("the edit".split(), 1, 1) == "clapperboard"
    assert lx.glyph_for("three hours".split()) == "clock" and lx.glyph_for(["banana"]) is None
    assert lx.glyph_for("save money".split()) == "dollar-sign"


@pytest.mark.parametrize("preset", ["clean-pro", "bold-hustle"])
def test_director_puts_a_vendored_glyph_on_text_and_stat_cards(preset):
    data = copy.deepcopy(LINES)
    data["style"] = {"preset": preset}
    d = direct(parse_script(data))
    cards = [c.params for sh in d.shots for c in sh.cues if c.type == "broll"]
    assert any(p.get("icon") == "circle-check" and p.get("text") == "EDIT: DONE" for p in cards)
    assert all(icons.exists(p["icon"]) for p in cards if "icon" in p)
    assert direct(parse_script(data)).shots[1].cues == d.shots[1].cues       # deterministic


# ---- look: skin-safe tones and the background treatment -------------------------------------------
def test_grade_port_matches_the_pack_reference():
    pack, node = stage.pack_root() / "layers" / "grade.js", shutil.which("node")
    if not pack.is_file() or not node:
        pytest.skip("motion-pack or node missing")
    for tone in (presets.LOOK_TONE["editorial"], V1_COOL):
        js = (f"import {{ gradeRGB }} from '{pack.as_uri()}'; const t = {json.dumps(tone)};"
              f"console.log(JSON.stringify({json.dumps([[s / 255 for s in c] for c in SKIN])}.map((c) => gradeRGB(t, c))));")
        ref = json.loads(subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30).stdout)
        for c, r in zip(SKIN, ref):
            assert all(abs(a - b) < 1e-9 for a, b in zip(grade_rgb(tone, [x / 255 for x in c]), r))


@pytest.mark.parametrize("preset", sorted(presets.PRESETS))
def test_preset_tone_keeps_skin_and_background_treatment_in_contract(preset):
    look = presets.PRESETS[preset]["look"]
    assert set(look["tone"]) <= presets.TONE_KEYS and skin_de(look["tone"]) <= 3.0          # contract: skin dE <= 3
    assert 8 <= look["bgfx"]["blur"] <= 14 and 0.75 <= look["bgfx"]["dim"] <= 0.85         # blur 8-14 px, -15..25 %
    st = presets.resolve_style({"preset": preset, "look": {"grade": "mono"}})
    assert st["look"]["tone"] is None                     # a script's own grade replaces the preset tone


def test_runtime_fallback_tones_are_skin_safe_where_v1_grades_were_not():
    tones = js_obj("TONES")
    assert {"warm", "cool", "teal-orange"} <= set(tones)
    assert all(skin_de(tones[k]) <= 3.0 for k in ("warm", "cool", "teal-orange"))
    assert skin_de(V1_COOL) > 3.0                         # the v1 cool-tech grade at 70 % failed the skin rule


def test_bad_look_fields_are_refused():
    for look in ({"tone": {"hue": 3}}, {"bgfx": {"blur": 40, "dim": 0.8}}, {"bgfx": {"blur": 10}}, {"tone": "warm"}):
        with pytest.raises(presets.PresetError):
            presets.resolve_style({"preset": "clean-pro", "look": look})
    assert presets.resolve_style({"preset": "clean-pro", "look": {"bgfx": False}})["look"]["bgfx"] is False


# ---- title legibility and card contrast (WCAG) -----------------------------------------------------
def test_title_backings_match_css_and_reach_4_5_to_1_over_a_white_wall():
    backing = js_obj("BACKING")
    calm = re.search(r"\.title-text \{[^}]*background: rgba\(8, 8, 16, (\.\d+)\)", CSS).group(1)
    glass = re.search(r'\.title\[data-backing="glass"\] \.title-text \{ background: rgba\(8, 8, 16, (\.\d+)\); '
                      r'backdrop-filter: blur\(\d+px\) brightness\((\.\d+)\)', CSS).groups()
    solid = re.search(r'\.title\[data-backing="solid"\] \.title-text \{ background: rgba\(8, 8, 16, (\.\d+)\)', CSS).group(1)
    assert backing == {"calm": [float(calm), 1], "glass": [float(glass[0]), float(glass[1])], "solid": [float(solid), 1]}
    busy = js_obj("BUSY")
    assert 0 < busy["glass"] < busy["solid"] < 1
    for tier, (a, br) in backing.items():
        bg_l = lum([a * v + (1 - a) * 255 * br for v in (8, 8, 16)])     # worst case: white behind the backing
        assert ratio(lum((255, 255, 255)), bg_l) >= 4.5, tier
        for name, p in presets.PRESETS.items():
            acc = readable(hexrgb(p["accent"]), bg_l)
            assert ratio(lum(acc), bg_l) >= 4.5, (tier, name)
            if ratio(lum(hexrgb(p["accent"])), bg_l) >= 4.5:
                assert acc == list(hexrgb(p["accent"]))            # the accent itself when it already reads


@pytest.mark.parametrize("preset", sorted(presets.PRESETS))
def test_card_type_and_glyph_contrast(preset):
    p, ink, paper = presets.PRESETS[preset], (11, 11, 15), (244, 239, 228)
    acc = hexrgb(p["accent"])
    assert ratio(lum(readable(acc, lum(ink))), lum(ink)) >= 4.5            # key word on a dark card
    assert ratio(lum(readable(acc, lum(paper), 5)), lum(paper)) >= 5.0    # key word on paper
    assert ratio(lum(ink), lum(paper)) >= 4.5 and ratio(lum(hexrgb(p["text"])), lum(ink)) >= 4.5
    assert ratio(lum(ink), lum(acc)) >= 3.0                                # glyph (ink) on the accent badge: 1.4.11


# ---- layout hooks and runtime rules -----------------------------------------------------------------
def test_layout_hooks_in_css():
    assert re.search(r"\.cap \{ position: absolute; left: var\(--x, 172px\); width: var\(--w, 696px\); "
                     r"top: var\(--y, 972px\); height: var\(--h, 276px\);", CSS)
    assert "left: var(--x, 120px); width: var(--w, 768px); top: var(--y, 300px); height: var(--h, 260px)" in CSS
    card_in = re.search(r"\n\.card-in \{[^}]*\}", CSS).group(0)     # layout.py card_content(): clear of the captions
    assert "left: var(--x, 90px); top: var(--y, 300px); width: var(--w, 810px); height: var(--h, 648px)" in card_in
    assert '.rf:has(> [data-layer="subject"]) > [data-layer="background"]' in CSS
    for kind in ("mesh", "grid", "paper", "blur", "solid"):
        assert f".bg-{kind} " in CSS
    assert "--fx" in MJS and "face_reel" in MJS and "dataset.params" in MJS


def test_runtime_is_seek_safe_and_within_size():
    code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", MJS, flags=re.S))
    for bad in ("Math.random", "Date.", "new Date", "performance.now", "requestAnimationFrame", "setTimeout"):
        assert bad not in code, bad
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert "animation" not in css and "transition:" not in css
    for f in (stage.WEB / "reel.mjs", stage.WEB / "reel.css", ROOT / "src" / "reel_director" / "director.py",
              ROOT / "src" / "reel_director" / "lexicon.py", ROOT / "src" / "reel_director" / "presets.py"):
        assert len(f.read_text().splitlines()) < 500, f.name
    assert "outCubic(u / (18 / F))" in MJS                 # council 4: the stat counts up over 18 frames
