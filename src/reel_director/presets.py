"""Style presets (data only) and the director's rule tables they select.

A preset is a full `script.style`; a script picks one with style.preset and overrides any key.
Fonts are the OFL families bundled in src/reel_director/fonts/. Sound ids are motion-pack
sfx/manifest.json ids; transition ids are motion-pack transitions/aliases.json names.
"""
import copy
import re
import string

CAPTIONS = ("bold", "pop", "karaoke", "pill", "boxed", "minimal")
GRADES = ("none", "warm", "cool", "teal-orange", "mono")
BACKGROUNDS = ("mesh", "grid", "paper", "blur", "solid")
PACES = ("calm", "standard", "punchy")
DEFAULT_PRESET = "bold-hustle"

PRESETS: dict[str, dict] = {
    # Hormozi-style: heavy uppercase sans, one yellow accent, fast cuts, raw look, few sounds.
    "bold-hustle": {
        "font": "Montserrat", "caption": "bold", "accent": "#FFD400", "text": "#FFFFFF", "bg": "#0B0B0F",
        "look": {"grain": 0.04, "vignette": 0.18, "grade": "none"}, "background": "solid",
        "pace": "punchy", "transitions": "hard", "sfx_kit": "minimal", "music_mood": "confident",
        "music_beds": ["music.bed_tech_pulse_loop8", "music.bed_synthwave_loop8", "music.bed_deep_house_loop8"],
    },
    # Minimal B2B: clean sans pill captions, cool grade, soft transitions, quiet ticks.
    "clean-pro": {
        "font": "Inter", "caption": "pill", "accent": "#4F8CFF", "text": "#FFFFFF", "bg": "#0F172A",
        "look": {"grain": 0.0, "vignette": 0.1, "grade": "cool"}, "background": "mesh",
        "pace": "standard", "transitions": "soft", "sfx_kit": "soft", "music_mood": "optimistic",
        "music_beds": ["music.bed_corporate_bright_loop8", "music.bed_uplift_corporate_loop8",
                       "music.bed_documentary_marimba_loop8"],
    },
    # MrBeast-style pop: comic display face, saturated warm grade, energetic transitions and hits.
    "beast-hype": {
        "font": "Bangers", "caption": "pop", "accent": "#3CFF5A", "text": "#FFFFFF", "bg": "#120A2A",
        "look": {"grain": 0.0, "vignette": 0.12, "grade": "warm"}, "background": "grid",
        "pace": "punchy", "transitions": "energetic", "sfx_kit": "hype", "music_mood": "hype",
        "music_beds": ["music.bed_hype_house_loop8", "music.bed_trap_half_loop8", "music.bed_dnb_170_loop8"],
    },
    # Serif notebook: Instrument Serif, warm paper cards, calm pace, few effects.
    "editorial": {
        "font": "Instrument Serif", "caption": "minimal", "accent": "#E4572E", "text": "#FFFFFF", "bg": "#201B17",
        "look": {"grain": 0.08, "vignette": 0.22, "grade": "warm"}, "background": "paper",
        "pace": "calm", "transitions": "soft", "sfx_kit": "soft", "music_mood": "calm",
        "music_beds": ["music.bed_lofi_jazz_loop8", "music.bed_lofi_warm_loop8", "music.bed_ambient_pad_loop8"],
    },
    # Blueprint explainer: grid cards, boxed captions, cyan accent, UI blips.
    "tech-explainer": {
        "font": "Inter", "caption": "boxed", "accent": "#00D1FF", "text": "#FFFFFF", "bg": "#0A1A2F",
        "look": {"grain": 0.02, "vignette": 0.12, "grade": "cool"}, "background": "grid",
        "pace": "standard", "transitions": "clean", "sfx_kit": "tech", "music_mood": "tech",
        "music_beds": ["music.bed_tech_pulse_loop8", "music.bed_deep_house_loop8", "music.bed_suspense_pulse_loop8"],
    },
    # Hinglish-ready: Devanagari-capable sans, saffron accent, karaoke captions, Indian percussion kit.
    "desi-bilingual": {
        "font": "Noto Sans Devanagari", "caption": "karaoke", "accent": "#FF9933", "text": "#FFFFFF",
        "bg": "#1A0F2E", "look": {"grain": 0.05, "vignette": 0.15, "grade": "warm"}, "background": "mesh",
        "pace": "standard", "transitions": "pop", "sfx_kit": "desi", "music_mood": "warm",
        "music_beds": ["music.bed_desi_bounce_loop8", "music.bed_indian_fusion_loop8", "music.bed_tabla_keherwa_loop"],
    },
}
# Look (contract v2 'Look'): a subtle per-preset grade in the pack's grade params (layers/grade.js; the runtime's
# P.look.tone) and the background treatment (blur px, dim = exposure factor) on the wall behind the creator.
# Measured on the founder's real takes (tests/test_visuals.py, the pack's closed form): skin dE2000 max 0.8-1.5 per
# tone, where the v1 grades at 70 % (warm-film, cool-tech) reached 4.0 and 7.3; on rendered frames 0.5-1.5 vs 2.9-3.9.
# Shadow split-tones leave skin alone.
LOOK_TONE = {
    "bold-hustle": {"contrast": 0.10, "sat": 1.05, "split": {"shadowHue": 215, "shadowSat": 0.10}},
    "clean-pro": {"temp": -0.05, "contrast": 0.10, "sat": 1.03, "split": {"shadowHue": 220, "shadowSat": 0.12}},
    "beast-hype": {"temp": 0.02, "contrast": 0.08, "sat": 1.08},
    "editorial": {"temp": 0.06, "contrast": 0.06, "sat": 0.96, "fade": 0.015, "split": {"shadowHue": 190, "shadowSat": 0.08}},
    "tech-explainer": {"temp": -0.04, "contrast": 0.10, "sat": 1.02, "split": {"shadowHue": 200, "shadowSat": 0.14}},
    "desi-bilingual": {"temp": 0.06, "contrast": 0.08, "sat": 1.06, "split": {"shadowHue": 280, "shadowSat": 0.06}},
}
BGFX = {"bold-hustle": (10, 0.8), "clean-pro": (12, 0.82), "beast-hype": (8, 0.85), "editorial": (12, 0.8),
        "tech-explainer": (10, 0.8), "desi-bilingual": (10, 0.82)}      # contract: blur 8-14 px, dim 0.75-0.85
for _name, _p in PRESETS.items():
    _p["look"].update(tone=LOOK_TONE[_name], bgfx={"blur": BGFX[_name][0], "dim": BGFX[_name][1]})
TONE_KEYS = {"temp", "tint", "contrast", "sat", "fade", "split", "exposure", "pivot"}

# Pace profiles (editing-pace.md P1/P4/B1): S = median visual-change interval, max static run,
# B-roll coverage target (inside the contract band 25-40%), number chips on the face.
# insert = shortest B-roll insert (EP B2 1.2-3.0 s): calm reels use fewer, longer inserts.
PACE = {
    "calm":     {"S": 4.0, "max_static": 6.0, "broll": 0.27, "chips": False, "insert": 2.0},
    "standard": {"S": 2.6, "max_static": 4.0, "broll": 0.32, "chips": False, "insert": 1.6},
    "punchy":   {"S": 1.8, "max_static": 3.0, "broll": 0.37, "chips": True, "insert": 1.2},
}
BROLL_BAND = (0.25, 0.40)

# Transition families: id by boundary energy (high >= 0.75, mid >= 0.5, low) and into the last shot.
# None = hard cut. editing-pace T1/T2: stylised transitions only at section boundaries.
TRANSITIONS = {
    "hard":      {"high": "whip", "mid": "scalePunch", "low": None, "last": "scalePunch"},
    "soft":      {"high": "blurCross", "mid": "push", "low": "crossfade", "last": "blurCross"},
    "energetic": {"high": "zoomThrough", "mid": "whip", "low": "push", "last": "zoomThrough"},
    "clean":     {"high": "push", "mid": "blurCross", "low": None, "last": "swipeUp"},
    "pop":       {"high": "whip", "mid": "swipeUp", "low": None, "last": "swipeUp"},
}
# Whoosh per transition (each id is in sfx/manifest.json by_transition for that key).
TX_SFX = {
    "whip": "snd.whoosh.whip_pan", "push": "snd.whoosh.swish_s", "zoomThrough": "snd.tx.zoom_through",
    "flash": "snd.tx.flash_swell", "blurCross": "snd.tx.blur_cross", "scalePunch": "snd.tx.scale_punch",
    "swipeUp": "snd.whoosh.swish_xs", "crossfade": "snd.tx.dissolve_pad", "dip-to-black": "snd.tx.dip_to_black",
}
# SFX kits: hook hit, text pop, stat ding. Levels in dB re voice (sound.md section 5 table).
SFX_KITS = {
    "minimal": {"hook": "snd.hit.low_thump", "pop": "snd.ui.tick", "ding": "snd.device.notify_soft"},
    "soft":    {"hook": "snd.hit.soft", "pop": "snd.ui.tick", "ding": "snd.metal.ping"},
    "hype":    {"hook": "snd.hit.punch", "pop": "snd.ui.pop", "ding": "snd.device.achievement"},
    "tech":    {"hook": "snd.hit.low_thump", "pop": "snd.ui.blip", "ding": "snd.ui.success"},
    "desi":    {"hook": "snd.indian.dhol_bhangra_hit", "pop": "snd.indian.tabla_na", "ding": "snd.indian.manjira"},
    "punchy":  {"hook": "snd.hit.punch", "pop": "snd.ui.pop", "ding": "snd.device.notify_ding"},
}
SFX_LEVEL_DB = {"hook": -3.0, "whoosh": -12.0, "pop": -14.0, "ding": -12.0}
ENERGY_BIAS = {"calm": -0.15, "standard": 0.0, "punchy": 0.1}
# Per-preset direction (council 5/7, EP section 12 and A13): what makes two presets on one pace cut
# differently. cadence = CLUSTERS row offset (punch rhythm; the title still varies it per reel),
# stretch = x pace S for the punch cadence, card = B-roll card background, case = text-card label case
# (clean-pro is sentence case per council 7), tx = transition family (council 5).
DIRECTION = {
    "clean-pro":      {"cadence": 0, "stretch": 1.0, "card": "mesh", "case": "sentence", "tx": "push"},
    "tech-explainer": {"cadence": 1, "stretch": 1.0, "card": "grid", "case": "upper", "tx": "push"},
    "editorial":      {"cadence": 2, "stretch": 1.0, "card": "paper", "case": "sentence", "tx": None},
    "bold-hustle":    {"cadence": 1, "stretch": 0.9, "card": "solid", "case": "upper", "tx": "whip"},
    "beast-hype":     {"cadence": 2, "stretch": 1.1, "card": "grid", "case": "upper", "tx": "zoomThrough"},
    "desi-bilingual": {"cadence": 2, "stretch": 1.15, "card": "blur", "case": "title", "tx": "whip"},
}
CARD_CASE = {"upper": str.upper, "title": string.capwords, "sentence": str.capitalize}   # capwords: "Don't"


def card_case(text: str, case: str, source: str = "") -> str:
    """A text card's label in the preset's case. A word the script line spells with an inner capital ('AI',
    'YouTube', 'iPhone') keeps that spelling, and 'i' stays 'I', so sentence/title case never shows 'Ai'.
    An all-caps line is shouting, not spelling, so it is ignored."""
    out = CARD_CASE[case](text)
    if case == "upper":
        return out
    keep = {"i": "I"} | ({w.lower(): w for w in re.findall(r"\w+", source) if any(ch.isupper() for ch in w[1:])}
                         if source != source.upper() else {})
    return re.sub(r"\w+", lambda m: keep.get(m[0].lower(), m[0]), out)
ENDCARD = {"text": "Follow for more", "sub": "Save this for your next reel"}


class PresetError(ValueError):
    pass


def _check(style: dict) -> None:
    def need(key, allowed):
        if style.get(key) not in allowed:
            raise PresetError(f"style.{key} {style.get(key)!r} must be one of {list(allowed)}")
    need("caption", CAPTIONS)
    need("background", BACKGROUNDS)
    need("pace", PACES)
    need("transitions", TRANSITIONS)
    need("sfx_kit", SFX_KITS)
    look = style.get("look")
    if not isinstance(look, dict):
        raise PresetError("style.look must be an object {grain, vignette, grade}")
    if look.get("grade") not in GRADES:
        raise PresetError(f"style.look.grade {look.get('grade')!r} must be one of {list(GRADES)}")
    for k in ("grain", "vignette"):
        v = look.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1:
            raise PresetError(f"style.look.{k} must be a number in 0..1, got {v!r}")
    tone, fx = look.get("tone"), look.get("bgfx")
    if tone is not None and (not isinstance(tone, dict) or set(tone) - TONE_KEYS):
        raise PresetError(f"style.look.tone must be null or an object with keys from {sorted(TONE_KEYS)}")
    num = lambda v, lo, hi: isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi  # noqa: E731
    if fx not in (None, False) and not (isinstance(fx, dict) and num(fx.get("blur"), 0, 20) and num(fx.get("dim"), 0.5, 1)):
        raise PresetError("style.look.bgfx must be false or {blur: 0-20 (px), dim: 0.5-1 (exposure factor)}")


def get_preset(name: str) -> dict:
    """A copy of one preset's full style; KeyError for an unknown name."""
    return copy.deepcopy(PRESETS[name])


def resolve_style(raw: dict | None) -> dict:
    """Preset defaults + the script's overrides ('look' merges key by key). Raises PresetError."""
    raw = dict(raw or {})
    name = raw.get("preset", DEFAULT_PRESET)
    if name not in PRESETS:
        raise PresetError(f"unknown style.preset {name!r} (expected one of {sorted(PRESETS)})")
    style = copy.deepcopy(PRESETS[name])
    look = raw.pop("look", None)
    if look is not None and not isinstance(look, dict):
        raise PresetError("style.look must be an object {grain, vignette, grade}")
    style.update(raw)
    style["look"] = {**PRESETS[name]["look"], **(look or {})}
    if look and "grade" in look and "tone" not in look:   # the script picked its own grade: the preset tone steps aside
        style["look"]["tone"] = None
    style["preset"] = name
    _check(style)
    return style
