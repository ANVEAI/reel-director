"""Mode A sound: bake the voice, a music bed and the SFX into one mastered mix.wav.

The takes in the composition are muted pictures; every sound the viewer hears comes from here:
- voice: each kept segment sliced sample-exact from its take, 10 ms raised-cosine fades at every
  cut, junk tails touching a cut gated to the room floor, each shot leveled on what ships;
- bed: a pack loop bed picked by mood and length, rolled so a bar downbeat lands on the hook,
  set a fixed loudness under the voice and ducked under speech (80 ms look-ahead, 15 ms attack,
  120 ms hold, 350 ms release, pauses < 0.6 s held) with a mid carve;
- SFX: pack ids anchored on frame F+1 (or legacy files), each gain-staged from its measured
  loudness re the voice and never peaking above the voice;
- master: -14 LUFS-I through a true-peak limiter, then AAC-encoded, decoded and re-measured,
  lowering the ceiling until the encoded file is <= -1.5 dBTP.
Deterministic: same timeline and files -> same samples. numpy/scipy only (no numba, no pack import).
"""
import json
import os
import subprocess
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter1d
from scipy.signal import lfilter, resample_poly

from .audio import MASTER_LUFS, MASTER_TP, SR, TAKE_LUFS
from .levels import WAV_CEIL, aac_probe, block_loudness, limiter, lufs, master, true_peak_db  # noqa: F401
from .timeline import Timeline
from .stagger import card_in

PACK = Path(os.environ.get("MOTION_PACK", "~/Developer/motion-pack-public")).expanduser()
FADE = 0.010            # every clip edge (8-12 ms per the contract)
GATE_ABOVE = 10.0       # dB over the take floor that counts as sound at a cut
GATE_MAX = 0.15         # longest junk tail/onset (s) that is gated at a cut
SHOT_GAIN_MAX = 10.0    # per-shot leveling clamp (dB)
DUCK_DB = 10.0          # bed under speech (council 9: duck 10 dB)
LOOKAHEAD, ATTACK, HOLD, RELEASE = 0.080, 0.015, 0.120, 0.350   # council 9 (Sound's measured settings)
HOLD_GAP = 0.6          # pauses shorter than this keep the bed down (no swell back in gaps < 0.6 s)
LOW_SHELF_HZ, LOW_SHELF_DB = 150.0, -5.0   # rubric 4.2: 63-86% of the beds' energy sat under 150 Hz
END_BAR_WINDOW, END_RING = 2.0, 0.12       # the bed stops on the last bar (final bar + 0.3 s), 120 ms release
LOOP_MAX_S = 32.0       # council 9: loop beds only up to 32 s
BED_REL_LU = -5.0       # un-ducked bed re the voice; ducked -> ~15 LU under the voice (council: >= 15 LU)
BED_GAIN_MAX = 15.0
TP_MARGIN = 0.1
CARD_LEAD_FRAMES = 4    # compiler.BROLL_LEAD (council 4)
SFX_LEVEL = {"ui": -14.0, "whoosh": -16.0, "transition": -14.0, "impact": -12.0, "riser": -16.0,
             "logo": -6.0, "stinger": -8.0, "custom": -14.0}   # max 100 ms loudness re voice LUFS-I
SFX_UNDER_VOICE_PEAK = 1.0   # dB: an SFX true peak never above the voice's
MOODS = {"hype": ["hype"], "energetic": ["hype"], "punchy": ["hype", "confident"], "calm": ["calm"],
         "chill": ["calm"], "minimal": ["calm"], "lofi": ["calm", "warm"], "warm": ["warm"],
         "story": ["warm"], "tech": ["tech", "curiosity"], "explainer": ["curiosity", "tech"],
         "corporate": ["optimistic", "confident"], "pro": ["optimistic", "confident"],
         "clean": ["optimistic", "calm"], "upbeat": ["optimistic", "playful"], "cinematic": ["cinematic"],
         "epic": ["cinematic", "triumphant"], "playful": ["playful"], "fun": ["playful", "comic"],
         "comic": ["comic", "playful"], "desi": ["festive", "playful"], "indian": ["festive", "calm"],
         "festive": ["festive"], "suspense": ["tense", "tension"], "tense": ["tense", "tension"],
         "editorial": ["calm", "warm"], "curious": ["curiosity"]}


# ------------------------------------------------------------------------------------------------ voice
def _decode(path: Path, cache: dict) -> np.ndarray:
    if path not in cache:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                              "-f", "f32le", "-"], check=True, capture_output=True).stdout
        cache[path] = np.frombuffer(raw, "<f4").astype(np.float64)
    return cache[path]


def _rms_db(x, win: float = 0.005) -> np.ndarray:
    return 10 * np.log10(uniform_filter1d(x ** 2, max(1, int(win * SR)), mode="nearest") + 1e-14)


def floor_db(x) -> float:
    """Take room floor: 10th percentile of 10 ms frame levels (digital silence ignored)."""
    n = int(0.01 * SR)
    db = 10 * np.log10(np.mean(x[: len(x) // n * n].reshape(-1, n) ** 2, axis=1) + 1e-14) if len(x) >= n else [-90]
    db = np.asarray(db)
    db = db[db > -100]
    return float(np.percentile(db, 10)) if len(db) else -90.0


def _fade(n: int) -> np.ndarray:
    return 0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)


def gate_edges(seg: np.ndarray, first_on: float, last_off: float, floor: float) -> tuple[np.ndarray, list[str]]:
    """Clamp a junk tail (head) or junk onset (end) that touches a cut down to the room floor.

    Only a short loud run that is contiguous with the clip edge and separated from the nearest
    kept word is touched (first_on / last_off: word edges in seconds from the clip start), so a
    word's own decay or a breath leading into a word is left alone."""
    e = _rms_db(seg)
    loud = e > floor + GATE_ABOVE
    g, notes, ramp = np.ones(len(seg)), [], int(0.005 * SR)
    clamp = np.minimum(1.0, 10 ** ((floor + 3 - e) / 20))
    if len(seg) and loud[0]:
        k = int(np.argmax(~loud)) if (~loud).any() else len(seg)
        if k <= GATE_MAX * SR and k <= (first_on + 0.01) * SR:
            g[:k] = clamp[:k]
            r = min(ramp, len(seg) - k)
            g[k:k + r] = np.minimum(1.0, clamp[k:k + r] + (1 - clamp[k:k + r]) * _fade(r))
            notes.append(f"head {k / SR * 1000:.0f} ms gated")
    if len(seg) and loud[-1]:
        k = int(np.argmax(~loud[::-1])) if (~loud).any() else len(seg)
        if k <= GATE_MAX * SR and len(seg) - k >= (last_off - 0.01) * SR:
            s = len(seg) - k
            g[s:] = np.minimum(g[s:], clamp[s:])
            r = min(ramp, s)
            g[s - r:s] = np.minimum(g[s - r:s], clamp[s - r:s] + (1 - clamp[s - r:s]) * _fade(r)[::-1])
            notes.append(f"tail {k / SR * 1000:.0f} ms gated")
    return seg * g, notes


def voice_track(tl: Timeline, n: int) -> tuple[np.ndarray, list[dict]]:
    """(stereo voice stem, per-shot info). Slots stay silent."""
    vo, cache, info = np.zeros(n), {}, []
    f = int(FADE * SR)
    for p in tl.shots:
        if not p.take or not p.clips:
            continue
        x = _decode(p.take.src, cache)
        fl = floor_db(x)
        shot = np.zeros(n)
        notes, cuts = [], []
        for c in p.clips:
            a, o, m = round(c.media_in * SR), round(c.out_start * SR), round(c.duration * SR)
            seg = np.zeros(m)
            have = x[a:a + m]
            seg[:len(have)] = have
            c_end = c.out_start + c.duration
            inside = [w for w in p.words if c.out_start - 0.02 <= w.start < c_end]
            first_on = (min(w.start for w in inside) - c.out_start) if inside else c.duration
            last_off = (max(w.end for w in inside) - c.out_start) if inside else 0.0
            seg, nts = gate_edges(seg, first_on, last_off, fl)
            notes += [f"{c.out_start:.3f}s {t}" for t in nts]
            k = min(f, m // 2)
            seg[:k] *= _fade(k)
            seg[m - k:] *= _fade(k)[::-1]
            end = min(n, o + m)
            shot[o:end] += seg[:end - o]
            cuts.append(round(c.out_start, 3))
        L = lufs(shot)
        gain = float(np.clip(TAKE_LUFS - L, -SHOT_GAIN_MAX, SHOT_GAIN_MAX)) if L > -70 else 0.0
        vo += shot * 10 ** (gain / 20)
        info.append({"shot": p.shot.id, "kept_lufs": round(L, 2), "gain_db": round(gain, 2),
                     "floor_db": round(fl, 1), "clip_starts": cuts, "gates": notes})
    return np.stack([vo, vo], 1), info


# ------------------------------------------------------------------------------------------------ bed
@lru_cache(maxsize=None)
def _manifest(rel: str) -> dict | None:
    p = PACK / rel
    return json.loads(p.read_text()) if p.exists() else None


def pick_bed(tl: Timeline) -> dict | None:
    """Deterministic bed choice: music.src, else music.id, else mood (music.mood / style.music_mood)."""
    s, D = tl.script, tl.duration
    m = s.music
    if m is False or (isinstance(m, dict) and m.get("off")):
        return None
    m = m or {}
    if m.get("src"):
        return {"id": None, "file": str((s.base_dir / m["src"]).resolve()), "loop": bool(m.get("loop", True)),
                "bpm": m.get("bpm"), "side": None}
    mood = m.get("mood") or s.style.get("music_mood")
    if not m.get("id") and not mood:
        return None
    man = _manifest("music/manifest.json")
    if not man:
        return None
    beds = [it for it in man["items"] if it["kind"] == "bed" and it["loop"]]
    if D > LOOP_MAX_S and not m.get("id"):   # council 9: non-loop beds over 32 s (no audible loop seams)
        long = [it for it in man["items"] if it["kind"] == "bed" and not it["loop"]]
        cover = [it for it in long if it["duration_s"] >= D]   # none covers the reel: the longest ends on its own
        beds = cover or sorted(long, key=lambda it: (-it["duration_s"], it["id"]))[:1] or beds
    if m.get("id"):
        want = str(m["id"]).removeprefix("music.")
        hit = [it for it in man["items"] if it["id"].removeprefix("music.") == want and it["kind"] == "bed"]
        cands = hit or beds
    else:
        moods = set(MOODS.get(str(mood).lower(), [str(mood).lower()]))
        cands = [it for it in beds if moods & set(it["mood"])] or [it for it in beds if "talking_head" in it["use"]] or beds
        cands.sort(key=lambda it: ("talking_head" not in it["use"], it["duration_s"] < D / 2.5, it["id"]))
        cands = cands[:3]
    it = cands[zlib.crc32(s.title.encode()) % len(cands)] if not m.get("id") else cands[0]
    side = _manifest("music/" + it["sidecar"]) if it.get("sidecar") else None
    return {"id": it["id"], "file": str(PACK / "music" / it["file"]), "loop": bool(it["loop"]), "bpm": it["bpm"],
            "mood": it["mood"], "side": side}


def hero_time(tl: Timeline) -> float:
    """The hook interrupt: the first punch (where the hook hit lands), else the first title, else the first word."""
    fps = tl.script.fps
    for p in tl.shots:      # the hook hit itself: its peak lands on frame F+1 (+ the sound's own offset)
        for c in p.shot.cues:
            if c.type == "sfx" and c.params.get("role") == "hook":
                e = _sfx_entry(str(c.params.get("id", ""))) or {}
                F = int(np.floor(p.words[c.start_word].start * fps + 0.5))
                return (F + 1 + int(e.get("anchor_frame_offset", 0))) / fps
    for kind in ("punch", "title"):   # never the frame-0 'open' punch: it is not a hit
        for p in tl.shots:
            for c in p.shot.cues:
                if c.type == kind and not c.params.get("open"):
                    return p.words[c.start_word].start
    return tl.shots[0].words[0].start if tl.shots and tl.shots[0].words else 0.0


def bed_grid(tl: Timeline, bed: dict) -> dict:
    """Beat grid (seconds, reel time) of the bed once rolled so a bar downbeat lands on the hero moment.
    Loop beds repeat their sidecar grid every loop; no sidecar (custom src) -> bpm only, no grid."""
    side, grid = bed.get("side"), {"bpm": bed.get("bpm"), "beats": [], "bars": [], "roll_frames": 0, "fps": 30}
    if not side:
        return grid
    bfps, L = side["meta"]["fps"], int(round(side["meta"]["length_frames"]))
    fpbar = side["tempo"]["frames_per_bar"]
    H = int(np.floor(hero_time(tl) * bfps + 0.5))
    roll = (fpbar - H % fpbar) % fpbar if bed.get("loop", True) else 0     # a non-loop bed plays from its top
    span = tl.duration * bfps
    for key, src in (("beats", side["beat_frames"]), ("bars", side["bar_frames"])):
        fr = sorted({rep * L + b - roll for rep in range(int(span // L) + 2) for b in src})
        grid[key] = [round(f / bfps, 4) for f in fr if 0 <= f < span]
    grid.update(roll_frames=roll, frames_per_bar=fpbar, fps=bfps, hero_s=round(hero_time(tl), 3))
    return grid


def plan_bed(tl: Timeline) -> dict | None:
    """The bed this timeline gets and its beat grid, without rendering audio (for accent snapping)."""
    bed = pick_bed(tl)
    return bed and {**{k: v for k, v in bed.items() if k != "side"}, "grid": bed_grid(tl, bed)}


def bed_track(tl: Timeline, bed: dict, n: int) -> tuple[np.ndarray, dict]:
    """Loaded, rolled (bar downbeat on the hero), tiled bed with edge fades, plus its beat grid."""
    y = _load(Path(bed["file"]))
    grid = bed_grid(tl, bed)
    y = np.roll(y, -grid["roll_frames"] * (SR // grid["fps"]), axis=0)
    if len(y) < n:
        y = np.tile(y, (int(np.ceil(n / len(y))), 1)) if bed.get("loop", True) else np.pad(y, ((0, n - len(y)), (0, 0)))
    y = lfilter(*_low_shelf(LOW_SHELF_HZ, LOW_SHELF_DB), y[:n], axis=0)   # phone speakers: less sub, more mid
    fi = min(n, int(0.04 * SR))
    y[:fi] *= _fade(fi)[:, None]
    win = max(END_BAR_WINDOW, grid.get("frames_per_bar", 0) / grid.get("fps", 30) + 0.3)   # always holds a bar
    end = [b for b in grid.get("bars", []) if tl.duration - win <= b <= tl.duration - 0.3]
    stop = int(round(end[-1] * SR)) if end else n          # the bed ends ON a bar, not in a fade under the CTA
    fo = min(stop, int((END_RING if end else 0.5) * SR))
    y[stop - fo:stop] *= _fade(fo)[::-1, None] if not end else _fade(fo)[::-1, None] ** 0.5
    y[stop:] = 0.0
    grid["end_s"] = round(stop / SR, 4)
    return y, grid


def speech_mask(vo_mono: np.ndarray, tl: Timeline, step: float = 0.001) -> np.ndarray:
    """Where speech is, on a 1 ms grid: voice energy over a robust threshold, OR a kept word span.
    Pauses shorter than HOLD_GAP are filled so the bed does not pump between words."""
    h = int(step * SR)
    m = len(vo_mono) // h
    e = _rms_db(vo_mono, 0.01)[: m * h : h]
    act = e[e > -100]
    mask = np.zeros(m, bool)
    if len(act):
        mask = e > max(np.percentile(act, 10) + 12, np.percentile(act, 95) - 30)
    for p in tl.shots:
        if p.take:
            for w in p.words:
                mask[int(w.start / step):int(w.end / step) + 1] = True
    idx = np.nonzero(mask)[0]
    if len(idx) > 1:
        gaps = np.nonzero(np.diff(idx) > 1)[0]
        for g in gaps:
            a, b = idx[g], idx[g + 1]
            if (b - a) * step < HOLD_GAP:
                mask[a:b] = True
    return mask


def duck_curve(mask: np.ndarray, n: int, depth: float, step: float = 0.001) -> np.ndarray:
    """0..1 duck weight per sample: full depth from LOOKAHEAD - ATTACK before speech until HOLD after
    it, reached over ATTACK and let go over RELEASE (council 9: 80 ms look-ahead, 15/120/350 ms)."""
    m = mask.astype(float)
    gate = m.copy()
    for k in range(1, int(round((LOOKAHEAD - ATTACK) / step)) + 1):
        gate[:-k] = np.maximum(gate[:-k], m[k:])
    for k in range(1, int(round(HOLD / step)) + 1):
        gate[k:] = np.maximum(gate[k:], m[:-k])
    w = gate.copy()
    A, R = int(round(ATTACK / step)), int(round(RELEASE / step))
    for k in range(1, A + 1):          # look-ahead: full depth when the word starts
        w[:-k] = np.maximum(w[:-k], gate[k:] * (1 - k / (A + 1)))
    for k in range(1, R + 1):
        w[k:] = np.maximum(w[k:], gate[:-k] * (1 - k / (R + 1)))
    w = 0.5 - 0.5 * np.cos(np.pi * w)
    return np.interp(np.arange(n), np.arange(len(w)) * step * SR, w)


def _low_shelf(f0: float, gain_db: float, q: float = 0.7071):
    """RBJ low shelf (S = 1)."""
    A, w = 10 ** (gain_db / 40), 2 * np.pi * f0 / SR
    al, cw = np.sin(w) / (2 * q), np.cos(w)
    b = A * np.array([(A + 1) - (A - 1) * cw + 2 * np.sqrt(A) * al, 2 * ((A - 1) - (A + 1) * cw),
                      (A + 1) - (A - 1) * cw - 2 * np.sqrt(A) * al])
    a = np.array([(A + 1) + (A - 1) * cw + 2 * np.sqrt(A) * al, -2 * ((A - 1) + (A + 1) * cw),
                  (A + 1) + (A - 1) * cw - 2 * np.sqrt(A) * al])
    return b / a[0], a / a[0]


def _peak_eq(f0: float, q: float, gain_db: float):
    A, w = 10 ** (gain_db / 40), 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * A, -2 * np.cos(w), 1 - al * A])
    a = np.array([1 + al / A, -2 * np.cos(w), 1 - al / A])
    return b / a[0], a / a[0]


# ------------------------------------------------------------------------------------------------ sfx
def _sfx_entry(sid: str) -> dict | None:
    man = _manifest("sfx/manifest.json")
    if not man:
        return None
    sid = sid if sid.startswith("snd.") else "snd." + sid.replace("sfx/", "").replace("/", ".")
    return next((e for e in man["sounds"] if e["id"] == sid), None)


def _load(path: Path) -> np.ndarray:
    y, sr = sf.read(str(path), always_2d=True)
    y = y.astype(np.float64)
    y = np.repeat(y, 2, axis=1) if y.shape[1] == 1 else y[:, :2]
    return resample_poly(y, SR, sr, axis=0) if sr != SR else y


def sfx_events(tl: Timeline) -> list[dict]:
    """Every sfx cue with its file, anchor sample, start sample and level (dB re voice)."""
    fps, out = tl.script.fps, []
    for p in tl.shots:
        tx_at_start = any(c.type == "transition" and c.start_word == 0 for c in p.shot.cues)
        for c in (c for c in p.shot.cues if c.type == "sfx"):
            pr = c.params
            if pr.get("id"):
                e = _sfx_entry(str(pr["id"]))
                if e is None:
                    continue
                path, anchor, cat, off = PACK / "sfx" / e["file"], int(e["anchor_sample"]), e["category"], \
                    int(e.get("anchor_frame_offset", 0))
            elif pr.get("src"):
                path, anchor, cat, off = tl.script.base_dir / pr["src"], None, "custom", 0
            else:
                continue
            on = pr.get("on") or ("cut" if c.start_word == 0 and tx_at_start and cat in ("whoosh", "transition")
                                  else "word")
            t = p.out_start if on == "cut" else (p.words[c.end_word].end if on == "end" else p.words[c.start_word].start)
            if on == "lead":        # on the B-roll card's own entrance frame (compiler: 4 frames before its word)
                t = card_in(p.out_start, t, fps, CARD_LEAD_FRAMES)   # snapped onto a near cut, as the card
            if anchor is None:     # legacy file: starts `lead` seconds before the word
                start = round(max(0.0, t - float(pr.get("lead", 0.0))) * SR)
            else:
                F = int(np.floor(t * fps + 0.5))
                start = round((F + 1 + off) * SR / fps) - anchor
            level = float(pr.get("level", pr.get("level_db", SFX_LEVEL.get(cat, -14.0)))) + float(pr.get("gain_db", 0.0))
            out.append({"shot": p.shot.id, "id": pr.get("id") or pr.get("src"), "file": str(path), "t": round(t, 3),
                        "on": on, "start": int(start), "category": cat, "level_re_voice": level})
    return out


def sfx_track(events: list[dict], n: int, vo_lufs: float, vo_tp: float) -> tuple[np.ndarray, list[dict]]:
    out, rows = np.zeros((n, 2)), []
    for ev in events:
        y = _load(Path(ev["file"]))
        if not len(y):
            continue
        cue_l = float(np.max(block_loudness(y, 0.1, 0.01)))
        gain = vo_lufs + ev["level_re_voice"] - cue_l
        gain = min(gain, vo_tp - SFX_UNDER_VOICE_PEAK - true_peak_db(y))
        s = ev["start"]
        a, b = max(0, -s), min(len(y), n - s)
        if b > a:
            out[s + a:s + b] += y[a:b] * 10 ** (gain / 20)
        rows.append({**{k: ev[k] for k in ("shot", "id", "t", "on", "category", "level_re_voice")},
                     "anchor_s": round((s + int(np.argmax(np.abs(y).max(axis=1)))) / SR, 4), "gain_db": round(gain, 2),
                     "cue_loudness_db": round(cue_l + gain, 2)})
    return out, rows


# ------------------------------------------------------------------------------------------------ mix
def mixdown(tl: Timeline, out: str | Path, stems: bool = True, nomusic: bool = True) -> dict:
    """Bake the timeline's sound into `out` (WAV, 48 kHz stereo, 24-bit). Writes `<out>.json` (the
    report: levels, AAC verification, beat grid, cues), with stems the vo/music/music_dry/sfx FLACs, and
    with a bed `<out>.nomusic.wav` (same spec, no bed) next to it."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = int(round(tl.duration * SR))
    music = tl.script.music if isinstance(tl.script.music, dict) else {}
    vo, shots = voice_track(tl, n)
    has_vo = float(np.abs(vo).max(initial=0)) > 0
    vo_l = lufs(vo) if has_vo else TAKE_LUFS + 3.0
    vo_tp = true_peak_db(vo) if has_vo else -6.0
    rep: dict = {"duration": round(n / SR, 3), "voice": {"lufs": round(vo_l, 2), "true_peak": round(vo_tp, 2),
                                                        "shots": shots}}
    bed, bed_dry, mask = pick_bed(tl), np.zeros((n, 2)), np.zeros(1, bool)
    duck = float(music.get("duck_db", DUCK_DB))
    if bed:
        bed_dry, grid = bed_track(tl, bed, n)
        bl = lufs(bed_dry)
        bg = float(min(BED_GAIN_MAX, vo_l + float(music.get("level_lu", BED_REL_LU)) - bl)) if bl > -70 else 0.0
        bed_dry *= 10 ** (bg / 20)
        mask = speech_mask(vo[:, 0], tl) if has_vo else np.zeros(1, bool)
        w = duck_curve(mask, n, duck) if has_vo else np.zeros(n)
        carved = lfilter(*_peak_eq(3000, 1.0, -3.5), lfilter(*_peak_eq(250, 0.9, -3.0), bed_dry, axis=0), axis=0)
        bed_wet = (bed_dry * (1 - w)[:, None] + carved * w[:, None]) * (10 ** (-duck * w / 20))[:, None]
        rep["bed"] = {"id": bed["id"], "file": bed["file"], "mood": bed.get("mood"), "gain_db": round(bg, 2),
                      "lufs_dry": round(lufs(bed_dry), 2), "duck_db": duck, "grid": grid}
    else:
        bed_wet = bed_dry
        rep["bed"] = None
    rows = sfx_events(tl)
    sfx, rep["sfx"] = sfx_track(rows, n, vo_l, vo_tp)
    y, G, g, ceil, probe = master_verified(vo + bed_wet + sfx)
    sf.write(str(out), y, SR, subtype="PCM_24")
    rep["master"] = {"lufs": round(lufs(y), 2), "true_peak_4x": round(true_peak_db(y), 2), "ceiling_db": round(ceil, 2),
                     "gain_db": round(20 * np.log10(G), 2), "max_gr_db": round(float(-20 * np.log10(g.min())), 2),
                     "aac": probe}
    if bed and has_vo:
        rep["bed"]["measured"] = duck_stats(bed_dry * G, bed_wet * G, vo * G, mask)
    if stems:
        for k, v in (("vo", vo), ("music", bed_wet), ("music_dry", bed_dry), ("sfx", sfx)):
            sf.write(str(out.with_name(f"{out.stem}.{k}.flac")), np.clip(v * G, -1, 1), SR, subtype="PCM_24")
    if nomusic and bed and has_vo:     # same master minus the bed: post it when adding a trending sound in-app
        ym, *_, pm = master_verified(vo + sfx)
        sf.write(str(out.with_name(f"{out.stem}.nomusic.wav")), ym, SR, subtype="PCM_24")
        rep["nomusic"] = {"file": out.stem + ".nomusic.wav", "aac": pm}
    out.with_suffix(".json").write_text(json.dumps(rep, indent=1))
    return rep


def master_verified(pre: np.ndarray):
    """-14 LUFS through the limiter, then AAC round trips that lower the ceiling until the ENCODED
    true peak is <= MASTER_TP - TP_MARGIN. Ends with a 30 ms fade to zero (clean loop seam).
    Returns (audio, gain, gain curve, ceiling used, last AAC probe)."""
    ceil, probe = WAV_CEIL, {}
    y, G, g = master(pre, MASTER_LUFS, ceil)
    fo = min(len(y), int(0.03 * SR))
    for _ in range(5):
        y[len(y) - fo:] *= _fade(fo)[::-1, None]
        probe = aac_probe(y)
        if probe["true_peak"] <= MASTER_TP - TP_MARGIN and abs(probe["lufs"] - MASTER_LUFS) <= 0.3:
            break
        if probe["true_peak"] > MASTER_TP - TP_MARGIN:
            ceil -= probe["true_peak"] - (MASTER_TP - TP_MARGIN) + 0.1
        y, G, g = master(pre, MASTER_LUFS, ceil)
    return y, G, g, ceil, probe


def duck_stats(dry: np.ndarray, wet: np.ndarray, vo: np.ndarray, mask: np.ndarray, step: float = 0.001) -> dict:
    """Duck depth inside speech (dry vs ducked bed energy, excluding attack/release edges) and the
    voice-to-bed loudness difference while talking (400 ms blocks)."""
    h = int(step * SR)
    core = mask.copy()
    pad = int(RELEASE / step)
    idx = np.nonzero(~mask)[0]
    for i in idx[np.r_[True, np.diff(idx) > 1]] if len(idx) else []:
        core[max(0, i - pad):i] = False
    sel = np.repeat(core, h)[: len(dry)]
    sel = np.pad(sel, (0, len(dry) - len(sel)))
    if not sel.any():
        return {}
    depth = 10 * np.log10(np.sum(dry[sel] ** 2) / max(np.sum(wet[sel] ** 2), 1e-20))
    return {"duck_depth_db": round(float(depth), 2), "speech_s": round(float(sel.sum() / SR), 2),
            "voice_minus_bed_lu": round(lufs(vo[sel]) - lufs(wet[sel]), 2)}
