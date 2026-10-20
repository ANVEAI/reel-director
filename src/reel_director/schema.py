"""Script + cue schema. Cues anchor to words of a shot's line, never to seconds.

script.json:
{
  "title": "...", "width": 1080, "height": 1920, "fps": 30,
  "style": {"preset": "bold-hustle", "accent": "#FFD400"},
  "music": {"mood": "confident"},
  "shots": [{
    "id": "hook",
    "line": "Most creators waste three hours editing one reel.",
    "cues": [
      {"type": "overlay", "at": "three hours", "text": "3 HRS"},
      {"type": "punch", "at": "reel", "level": "M"},
      {"type": "sfx", "at": "waste", "id": "snd.whoosh.whip_pan"},
      {"type": "broll", "at": "editing", "until": "reel", "kind": "text", "text": "Timeline hell"},
      {"type": "emphasis", "at": "waste"}
    ]
  }]
}

"at" is a phrase from the line, matched as spelled (numbers, case and punctuation normalised:
"3" matches "three"; "2" never matches "to"). Append "@2" (or "#2") directly after the phrase for
its second occurrence: "one reel@2". A '#' anywhere else is part of the phrase ("#1 tool"). The cue
spans that phrase, or runs to the end of "until" when given. Anchors are resolved at load time so a
bad anchor fails before anyone records. style.preset picks a full style from presets.py.
"""
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .lexicon import spoken_tokens
from .presets import PresetError, resolve_style
from .textnorm import norm_tokens

CUE_TYPES = {"overlay", "sfx", "zoom", "cutaway", "emphasis", "punch", "transition", "broll", "title",
             "lowerthird", "endcard", "callout"}
BROLL_KINDS = {"text": ("text",), "stat": ("value", "label"), "list": ("items",), "icon": ("icon", "text"),
               "clip": ("src",), "media": ("query",)}   # media: real B-roll (v4), resolved into media.json
BROLL_LAYOUTS = ("full", "split", "pip", "inset")   # inset: media in a box beside the face (face kept)
PUNCH_LEVELS = ("W", "M", "T")
CALLOUTS = ("underline", "circle", "arrow")
TITLE_MAX_WORDS = 7
DEFAULT_STYLE = {"accent": "#FFD400", "text": "#FFFFFF", "bg": "#0B0B0F"}   # = the default preset's colours
_NTH = re.compile(r"(.*\S)[#@](\d+)")     # 'reel@2' / 'reel#2'; '#1 tool' and 'the #1' never match


class ScriptError(ValueError):
    pass


@dataclass
class Word:
    text: str          # as displayed in captions
    norm: list[str]    # spoken-form tokens used for matching


@dataclass
class Cue:
    type: str
    start_word: int
    end_word: int      # inclusive
    params: dict


@dataclass
class Shot:
    id: str
    line: str
    words: list[Word]
    cues: list[Cue]
    meta: dict = field(default_factory=dict)   # other shot keys (role, energy, title, auto)


@dataclass
class Script:
    title: str
    width: int
    height: int
    fps: int
    style: dict
    music: dict | None
    shots: list[Shot]
    base_dir: Path = field(default_factory=Path.cwd)


def split_words(line: str) -> list[Word]:
    return [Word(t, n) for t in line.split() if (n := norm_tokens(t))]


def _exact(text: str) -> str:
    return " ".join(spoken_tokens(text))


def _hits(words: list[Word], phrase: str, key=_exact) -> list[tuple[int, int]]:
    target = [key(w.text) for w in split_words(phrase)]
    if not target:
        raise ScriptError(f"empty anchor {phrase!r}")
    have = [key(w.text) for w in words]
    n = len(target)
    return [(i, i + n - 1) for i in range(len(have) - n + 1) if have[i:i + n] == target]


def find_phrase(words: list[Word], anchor: str) -> tuple[int, int]:
    """Word span of an anchor. Anchors match the spelled word (homophones are merged only for ASR,
    where they would land '2' on an earlier 'to' or 'their' on 'there')."""
    anchor = anchor.strip()
    m = _NTH.fullmatch(anchor)
    if m:
        nth, hits = int(m.group(2)), _hits(words, m.group(1))
        if nth < 1:
            raise ScriptError(f"anchor {anchor!r}: occurrence must be @1 or higher")
        if nth <= len(hits):
            return hits[nth - 1]
        if literal := _hits(words, anchor):        # a word that really ends in '#2'
            return literal[0]
        raise ScriptError(f"anchor {anchor!r} not found in line (occurrence {nth} of "
                          f"{m.group(1)!r}; the line has {len(hits)})")
    if hits := _hits(words, anchor):
        return hits[0]
    sounds = _hits(words, anchor, key=lambda t: " ".join(norm_tokens(t)))
    hint = ""
    if sounds:
        s, e = sounds[0]
        hint = f" (did you mean {' '.join(w.text for w in words[s:e + 1])!r}?)"
    raise ScriptError(f"anchor {anchor!r} not found in line{hint}")


def anchor_for(words: list[Word], start: int, end: int) -> str:
    """Inverse of find_phrase: the anchor text (with '@N' when needed) for words[start..end]."""
    text = " ".join(w.text for w in words[start:end + 1])
    hits = _hits(words, text)
    n = next((k + 1 for k, (s, _) in enumerate(hits) if s == start), 1)
    return text if n == 1 else f"{text}@{n}"


def pack_root() -> Path | None:
    """motion-pack: $RD_PACK (stage.py's variable), $MOTION_PACK (mixdown.py's), $REEL_DIRECTOR_PACK, else
    ~/Developer/motion-pack-public; None when it has no sfx manifest."""
    env = next((os.environ[k] for k in ("RD_PACK", "MOTION_PACK", "REEL_DIRECTOR_PACK") if os.environ.get(k)), None)
    root = Path(env).expanduser() if env else Path.home() / "Developer" / "motion-pack-public"
    return root if (root / "sfx" / "manifest.json").is_file() else None


@lru_cache(maxsize=4)
def _pack_ids(root: str) -> tuple[frozenset, frozenset, frozenset]:
    r = Path(root)
    sfx = frozenset(s["id"] for s in json.loads((r / "sfx" / "manifest.json").read_text())["sounds"])
    tx = frozenset(json.loads((r / "transitions" / "aliases.json").read_text())["aliases"])
    music_path = r / "music" / "manifest.json"
    music = frozenset(i["id"] for i in json.loads(music_path.read_text())["items"]) if music_path.is_file() \
        else frozenset()
    return sfx, tx, music


def pack_ids() -> tuple[frozenset, frozenset, frozenset] | None:
    """(sfx ids, transition aliases, music ids) from motion-pack, or None when no pack is installed
    (id checks are then skipped)."""
    root = pack_root()
    return _pack_ids(str(root)) if root else None


def _text(kind: str, raw: dict, key: str = "text") -> None:
    v = raw.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ScriptError(f"{kind} cue needs '{key}'")


def _check_broll(raw: dict) -> None:
    bk = raw.get("kind")
    if bk not in BROLL_KINDS:
        raise ScriptError(f"broll cue needs 'kind' in {sorted(BROLL_KINDS)}, got {bk!r}")
    if raw.get("layout", "full") not in BROLL_LAYOUTS:
        raise ScriptError(f"broll cue 'layout' must be one of {list(BROLL_LAYOUTS)}")
    if raw.get("layout") == "inset" and bk != "media":
        raise ScriptError("broll layout 'inset' is for kind 'media' only")
    for key in BROLL_KINDS[bk]:
        if key == "items":
            items = raw.get("items")
            if not isinstance(items, list) or not items or not all(isinstance(i, str) and i.strip() for i in items):
                raise ScriptError("broll list needs 'items': a non-empty list of text")
        elif key == "label":
            if not isinstance(raw.get("label"), str):
                raise ScriptError("broll stat needs 'label' (text, may be empty)")
        else:
            _text(f"broll {bk}", raw, key)


def _check_params(kind: str, raw: dict, shot_index: int, start: int) -> None:
    ids = pack_ids()
    if kind in {"overlay", "cutaway", "title", "lowerthird", "endcard"}:
        _text(kind, raw)
    if kind == "title" and len(raw["text"].split()) > TITLE_MAX_WORDS:
        raise ScriptError(f"title cue text has {len(raw['text'].split())} words (max {TITLE_MAX_WORDS})")
    if kind in {"lowerthird", "endcard"} and "sub" in raw and not isinstance(raw["sub"], str):
        raise ScriptError(f"{kind} cue 'sub' must be text")
    if kind == "sfx":
        if ("src" in raw) == ("id" in raw) or not (raw.get("src") or raw.get("id")):
            raise ScriptError("sfx cue needs exactly one of 'src' (file) or 'id' (pack sound)")
        if "id" in raw and ids and raw["id"] not in ids[0]:
            raise ScriptError(f"sfx id {raw['id']!r} is not in the pack's sfx/manifest.json")
    if kind == "zoom" and "scale" in raw and not (isinstance(raw["scale"], (int, float)) and 1 <= raw["scale"] <= 2):
        raise ScriptError(f"zoom cue 'scale' must be a number in 1..2, got {raw['scale']!r}")
    if kind == "punch" and raw.get("level") not in PUNCH_LEVELS:
        raise ScriptError(f"punch cue needs 'level' in {list(PUNCH_LEVELS)}, got {raw.get('level')!r}")
    if kind == "transition":
        _text(kind, raw, "id")
        if ids and raw["id"] not in ids[1]:
            raise ScriptError(f"transition id {raw['id']!r} is not in the pack's transitions/aliases.json")
        if "params" in raw and not isinstance(raw["params"], dict):
            raise ScriptError("transition cue 'params' must be an object")
        if start != 0:
            raise ScriptError("transition cue must anchor on the shot's first word (it leads into the shot)")
        if shot_index == 0:
            raise ScriptError("transition cue on the first shot: there is no previous shot to come from")
    if kind == "broll":
        _check_broll(raw)
    if kind == "callout" and raw.get("kind") not in CALLOUTS:
        raise ScriptError(f"callout cue needs 'kind' in {list(CALLOUTS)}, got {raw.get('kind')!r}")


def _parse_cue(words: list[Word], raw: dict, shot_index: int = 0) -> Cue:
    kind = raw.get("type")
    if kind not in CUE_TYPES:
        raise ScriptError(f"unknown cue type {kind!r} (expected one of {sorted(CUE_TYPES)})")
    if not isinstance(raw.get("at"), str):
        raise ScriptError(f"{kind} cue needs an 'at' anchor")
    start, end = find_phrase(words, raw["at"])
    if "until" in raw:
        until_end = find_phrase(words, str(raw["until"]))[1]
        if until_end < start:
            raise ScriptError(f"'until' {raw['until']!r} comes before 'at' {raw['at']!r}")
        end = until_end
    _check_params(kind, raw, shot_index, start)
    params = {k: v for k, v in raw.items() if k not in {"type", "at", "until"}}
    return Cue(kind, start, end, params)


def _check_music(music, ids) -> None:
    if music in (None, False):
        return
    if not isinstance(music, dict) or not any(music.get(k) for k in ("src", "id", "mood")):
        raise ScriptError("music needs one of 'src' (file), 'id' (pack bed) or 'mood', or false for none")
    if music.get("id") and ids and ids[2] and music["id"] not in ids[2]:
        raise ScriptError(f"music id {music['id']!r} is not in the pack's music/manifest.json")


def parse_script(data: dict, base_dir: Path | None = None) -> Script:
    shots, ids = [], set()
    for si, raw in enumerate(data.get("shots") or []):
        sid = raw.get("id") or f"shot{si + 1}"
        if sid in ids:
            raise ScriptError(f"duplicate shot id {sid!r}")
        ids.add(sid)
        words = split_words(raw.get("line", ""))
        if not words:
            raise ScriptError(f"shot {sid!r} has no spoken words")
        cues = []
        for ci, rc in enumerate(raw.get("cues") or []):
            try:
                cues.append(_parse_cue(words, rc, si))
            except ScriptError as e:
                raise ScriptError(f"shot {sid!r} cue {ci}: {e}") from None
        meta = {k: v for k, v in raw.items() if k not in {"id", "line", "cues"}}
        shots.append(Shot(sid, raw["line"], words, cues, meta))
    if not shots:
        raise ScriptError("script has no shots")
    try:
        style = resolve_style(data.get("style"))
    except PresetError as e:
        raise ScriptError(str(e)) from None
    _check_music(data.get("music"), pack_ids())
    return Script(
        title=data.get("title", "Untitled reel"),
        width=int(data.get("width", 1080)),
        height=int(data.get("height", 1920)),
        fps=int(data.get("fps", 30)),
        style=style,
        music=data.get("music"),
        shots=shots,
        base_dir=base_dir or Path.cwd(),
    )


def load_script(path: str | Path) -> Script:
    path = Path(path)
    return parse_script(json.loads(path.read_text()), base_dir=path.parent.resolve())


def cue_to_dict(words: list[Word], c: Cue) -> dict:
    out = {"type": c.type}
    if c.end_word - c.start_word <= 3:
        out["at"] = anchor_for(words, c.start_word, c.end_word)
    else:
        out["at"] = anchor_for(words, c.start_word, c.start_word)
        out["until"] = anchor_for(words, c.end_word, c.end_word)
    return {**out, **c.params}


def script_to_dict(s: Script) -> dict:
    """A Script (e.g. the director's output) back to script.json form; parse_script round-trips it."""
    return {
        "title": s.title, "width": s.width, "height": s.height, "fps": s.fps, "style": s.style,
        **({"music": s.music} if s.music is not None else {}),
        "shots": [{"id": sh.id, "line": sh.line, **sh.meta, "cues": [cue_to_dict(sh.words, c) for c in sh.cues]}
                  for sh in s.shots],
    }
