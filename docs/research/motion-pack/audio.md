# motion-pack "audio" group (music/ + sfx/): notes for Reel Director

Source of truth read for this note (all read-only):
motion-pack `music/{README.md,grid.py,compose.py,presets.py,build_music.py,mixer.py,logo.py,manifest.json,library/beds/*.json,tempo_maps.json}`,
motion-pack `sfx/{README.md,manifest.json,bundles.json,sweeteners.json,mpaudio/sweeteners.py}`,
`templates/_shared/{audio.py,plan.mjs}`, `templates/talking-head/{make.mjs,config.mjs}`, `cuts/{cutgen.py,patterns.json}`, `transitions/catalog.json`,
skill `skills/motion-pack/SKILL.md` + `references/{apis,gotchas,success-patterns,platforms,critic}.md`, and Reel Director's
`src/reel_director/{compiler.py,audio.py}` (to see what it does today).

Verified by running (outputs only in a scratch folder, `scratch-audio/`, not kept; NUMBA_CACHE_DIR / PYTHONPYCACHEPREFIX redirected, both repos confirmed untouched):
`mixtest.py`, `mixtest2.py` (a 20 s talking-head mix from three real Reel Director demo takes), `composetest.py` (a custom-length bed). Works with both the
system `python3` (3.11.7, numba 0.59) and Reel Director's own `.venv/bin/python` (3.11.7, numba 0.68, scipy 1.17).

---------------------------------------------------------------------------------------------------------------------------

## 0. TL;DR for Reel Director

1. **Bake ONE mix WAV with `music/mixer.py` and put it in the composition as a single `<audio>` at 0; mute the take `<video>`s.** This is the motion-pack
   way (skill gotcha: "HyperFrames sound integration is mode A only: one baked mix.wav at 0. Per-clip `<audio>` with data-start = (F+1)/fps is not built yet";
   SKILL rule: "Never gain SFX by hand ... the level is set in the plan"). The mixer gives: SFX anchor on (F+1) frames, cue levels solved relative to the voice
   or the bed (K-weighted), bed ducked 9 dB under the voice with a mid carve, tier-1 pre-hit vacuum, true-peak limiter, -14 LUFS-I / -1.5 dBTP, AAC probes
   so HyperFrames never lowers the track, the last 0.15 s digital zero, stems. A 20 s mix renders in about 4 s.
2. The dialogue goes INTO the mixer as `vo`: build `vo.wav` on the output timeline from the kept segments (same `media_in`, `out_start`, `duration` the
   compiler already uses for the `<video class="clip take">` elements), with a 6 ms crossfade at each jump cut (`cuts/patterns.json talking_head.autocut.crossfade_ms`).
3. Bed: a seamless loop bed from `music/library/beds/` picked by mood with `use` containing `talking_head` (bundle `talking_head` recommends presets
   `lofi_warm`, `uplift_corporate`, 100-120 BPM). Loop beds tile to any length; end them with `automate_bed` (fade to -40 dB over ~1 s before the end card)
   plus a sonic logo / stinger, or compose a custom-length bed with a `tail` section (`compose()` with a structure list).
4. SFX ids: `snd.<seg>.<name>` (plan form `sfx/<seg>/<name>`); use the `talking_head` bundle roles and its `levels_re_voice_db` as `over_vo_db` for cues that land
   INSIDE a word, and `over_bed_db` for cues that land in a speech gap (measured: `over_vo_db` in a gap crushes the cue, see section 7).
5. Beat grid: from the bed's sidecar JSON (`beat_frames`, `bar_frames`, `kick_frames`, `drop_frames`, `riser_frames`, `sections`), tiled for loop beds. In a
   talking-head (VO-led) reel do NOT move jump cuts to beats (cuts sit in breaths; critic mode `vo`); instead rotate the loop so a bar downbeat lands on the
   hero moment, and snap visual accents (punch-ins, overlay pops, b-roll in) to the nearest beat only when the word allows (within about 2 frames).

---------------------------------------------------------------------------------------------------------------------------

## 1. Files, formats, sizes

| what | path (repo-relative) | format | size |
|---|---|---|---|
| music beds (41) | `music/library/beds/<bed_id>.wav` + `<bed_id>.json` sidecar | 48 kHz, 24-bit PCM, stereo; mastered -16 LUFS-I, TP <= -1.5 dBTP | 229 MB total; a loop bed is 2.5-5.5 MB (16-32 s) |
| music stingers (10) | `music/library/stingers/sting_*.wav` | 48k/24/stereo, TP -3.0 | 12 MB |
| music sonic logos (14) | `music/library/logos/logo_*.wav` | 48k/24/stereo, TP -3.0 | 14 MB |
| music manifest | `music/manifest.json` (`items[]`: id `music.<name>`, kind bed/stinger/logo, file, bpm, frames_per_beat, bars, loop, mood, use, sections, drop_frames, sidecar, lufs_i, true_peak_db, duration_s, anchor_sample for stingers/logos) | JSON | |
| tempo maps | `music/tempo_maps.json` (`"<bpm>@<fps>fps"` -> bpm snapped, frames_per_beat, frames_per_bar, bar_seconds, riser_1bar_s, snap_error_pct; `ramps`) | JSON | |
| SFX (301 in 26 families) | `sfx/library/<category>/snd.<seg>.<name>.wav` (the manifest `file` field, relative to `sfx/`) | 48k/24/stereo, peak-normalised -6 dBFS, trimmed, edge-faded | 156 MB total; typical cue 10-500 KB |
| SFX manifest | `sfx/manifest.json` (`sounds[]`, `by_tag`, `by_transition`) | JSON | |
| SFX bundles | `sfx/bundles.json` (15 video types -> roles -> ids, bed presets, BPM range, levels) | JSON | |
| transition sweeteners | `sfx/sweeteners.json` (generated from `sfx/mpaudio/sweeteners.py` TABLE) | JSON | |
| external CC0 (optional, NOT in the public repo, never commit) | a local-only `sfx/library_ext/` (`manifest_ext.json`: 717 Kenney + OwlishMedia foley, ids `ext.<set>.<name>`) | 48k/24, -6 dBFS | 476 MB |

The WAV masters are present locally (they are not in git; `python3 music/build_music.py` / `python3 sfx/build_library.py` rebuild them; GitHub Release zips lag `main`).
Licence: all pack-generated audio is CC0 (`LICENSE-MEDIA`), code MIT. Kenney / OwlishMedia are CC0 but stay outside the repo.

Python requirements: numpy, scipy, numba, soundfile (`requirements.txt` pins 3.11 + numpy 1.26.4, scipy 1.11.4, numba 0.59.0; newer versions work, only the
synthesis SHA bits can differ). `music/mixer.py` also shells out to `ffmpeg` (AAC probes with `aac` and macOS `aac_at`). fps must divide 48000
(24, 25, 30, 48, 50, 60): `Mix` asserts it; 29.97 is not supported.

---------------------------------------------------------------------------------------------------------------------------

## 2. Music: beds with beat grids

### 2.1 Bed sidecar JSON (`music/library/beds/<id>.json`)
```
{ "meta": {preset, structure, seed, fps:30, bpm, bpm_requested, frames_per_beat, frames_per_bar, bars, key_midi, scale, prog, loop,
           length_frames, length_s, sections:[{name, bar0, frame0, bars, energy}], chords:[roman...], tuning, (tempo_ramp)},
  "tempo": {bpm, frames_per_beat, frames_per_bar, beat_seconds, bar_seconds, snap_error_pct},
  "beat_frames": [0, 24, 48, ...]   (ints, every beat of ONE pass of the file),
  "bar_frames":  [0, 96, ...]       (ints, downbeats),
  "kick_frames": [0.0, 42.48, ...]  (FLOATS: humanize / swing; round() before snapping),
  "clap_snare_frames": [...],       (floats)
  "drop_frames": [...],             (structured beds only: section drops / hook hit; [] for loop beds)
  "riser_frames": [...],            (riser START frames; each riser ends 1 frame before the drop 1 bar later)
  "markers"/"sam_frames"/"khali_frames": trailer arc / tabla thekas only }
```
All frames are at the build fps (30). Every beat is a whole number of frames (tempo snap: `n = round(fps*60/bpm)`, `bpm_snap = fps*60/n`):
at 30 fps 120/100/90/75/60 are exact; 110 -> 112.5 (16 f), 118 -> 120 (15), 128 -> 128.57 (14), 140 -> 138.46 (13), 170 -> 163.64 (11).
Loop beds: exactly 8 bars, seamless (ring-out folded onto the head), `meta.loop: true`; the beat grid repeats every `meta.length_frames`.
Structured (non-loop) beds: `bars x bar_seconds` of music + a 3 s ring-out tail in the WAV (so `bed_playful_bounce_hook6` = 2 bars at 120 = 4 s + 3 s = 7.0 s).

### 2.2 Beds suited to talking-head reels (loop, `use` contains `talking_head`; numbers measured, from music/README.md)
| id | BPM (snapped) | f/beat | loop s | mood | bass < 150 Hz | notes |
|---|---|---|---|---|---|---|
| `bed_lofi_warm_loop8` | 75 | 24 | 25.6 | warm, calm | 54% | bundle `talking_head` default; steady low end (good for duck reading) |
| `bed_uplift_corporate_loop8` | 112.5 | 16 | 17.1 | warm, optimistic | 48% | bundle `talking_head` default; product / explainer |
| `bed_lofi_jazz_loop8` | 81.82 | 22 | 23.5 | calm, warm | 54% | swung 7ths, D dorian |
| `bed_ambient_pad_loop8` | 60 | 30 | 32.0 | calm, cinematic | 63% | no drums; TP -5.5 |
| `bed_documentary_marimba_loop8` | 90 | 20 | 21.3 | curiosity, optimistic | 38% | sparse bass: ears duck reading jumps 1-9 dB |
| `bed_acoustic_folk_pluck_loop8` | 100 | 18 | 19.2 | warm, optimistic | 37% | same sparse-bass caveat |
| `bed_corporate_bright_loop8` | 120 | 15 | 16.0 | optimistic, warm | 70% | E major |
| `bed_deep_house_loop8` | 120 | 15 | 16.0 | tech, calm | 86% | very bass-heavy |
| `bed_jazz_walk_loop8` | 138.46 | 13 | 13.9 | playful, warm | 72% | |
| `bed_comedy_pizzicato_loop8` | 128.57 | 14 | 14.9 | comic, playful | 44% | |
| `bed_raga_calm_loop8` | 69.23 | 26 | 27.7 | calm, warm | 64% | India, JI |
| `bed_tabla_teental_loop` / `bed_tabla_keherwa_loop` | 100 / 112.5 | 18 / 16 | 19.2 / 17.1 | calm,warm / warm,playful | 41% / 33% | sidecar has sam / khali frames |
Other loop beds (not tagged talking_head): `bed_tech_pulse_loop8` (120, tech/confident, 60%), `bed_hype_house_loop8` (128.57), `bed_trap_half_loop8` (138.46),
`bed_cinematic_drone_loop8` (75), `bed_playful_bounce_loop8` (120, 32%), `bed_desi_bounce_loop8` (100), `bed_suspense_tick_loop8` (94.74), `bed_anthem_build_loop8` (120),
`bed_indian_fusion_loop8`, `bed_bhangra_hype_loop8`, `bed_festive_dhol_loop8`, `bed_synthwave_loop8`, `bed_dnb_170_loop8`, `bed_chiptune_8bit_loop8`,
`bed_orchestral_synth_epic_loop8`, `bed_suspense_pulse_loop8`, `bed_bhangra_dhol_loop`, `bed_tabla_dadra_loop`.

Bass-share by role (skill, round 4/5): proof / explainer 20-36%, VO documentary 15-34%, hype / trailer 50-61%, brand launch 50-60%. Most pack beds are
bass-heavy; check with `python3 ears/listen.py master.wav --role vo_doc|explainer|...`.
Gotcha (duck measurement): for a VO-led film pick a bed with a steady low end (`bed_lofi_warm_loop8`, `bed_uplift_corporate_loop8`, `bed_ambient_pad_loop8`)
and set the duck to 12 dB (`Mix.duck_db = 12`, cue sheet `"vo": {"duck_db": 12}`) so ears reads it.

### 2.3 Structured beds (fixed length, drops and sections in frames @30)
| id | BPM | WAV s | drop_frames | riser start frames | sections (name@frame0, energy) |
|---|---|---|---|---|---|
| `bed_hype_house_reel15` | 128.57 | 17.9 | [0 (hook hit), 224] | [168] | hook@0 1.0, verse@56 .55, build@168 .6-.85, drop@224 1.0, tail@392 .2 |
| `bed_tech_pulse_ad30` | 120 | 33.0 | [60, 240, 600] | [0, 180, 540] | intro@0, build@60, drop@240, break@540, final@600, tail@840 |
| `bed_corporate_bright_explainer60` | 120 | 63.0 | [1560] | [1500] | intro, verse@120, lift@600, main@840, break@1440, outro@1560, tail@1740 |
| `bed_cinematic_drone_cine30` | 75 | 35.0 | [576] | [480] | drone, rise@192, swell@384, peak@576, fall@768 |
| `bed_anthem_ramp16` | 100->128 ramp | 36.7 | [] | [] | intro, build@144, drop@576, final@1008, tail@1080 (non-uniform beat_frames in sidecar) |
| `bed_playful_bounce_hook6` / `bed_chiptune_cold_open3` / `bed_comedy_pizzicato_sting` | 120 / 150 / 128.57 | 7.0 / 6.2 / 6.7 | [0] | [] | hit/hook then tail |
| `bed_orchestral_epic_outro8` | 90 | 13.7 | [] | [] | final@0, tail@240 |
| `bed_trailer_arc` | 120 | 36.0 | [480, 930] | [420, 810] | markers: act2 240, act3 480, gap 720-810, crescendo 810, visual_cut 929, hit 930, hold 975, end 1080. NOT a loop, never trim after gap_start |

### 2.4 Selecting a bed by mood / length (code)
```python
import json, os, math
PACK = os.path.expanduser(os.environ.get("MOTION_PACK", "~/Developer/motion-pack-public"))
MAN = json.load(open(os.path.join(PACK, "music/manifest.json")))
def beds(mood=None, use="talking_head", loop=True, min_s=0.0):
    return [it for it in MAN["items"] if it["kind"] == "bed" and it["loop"] == loop
            and (not use or use in it["use"]) and (not mood or mood in it["mood"])
            and (loop or it["duration_s"] >= min_s)]
bed = beds(mood="warm")[0]                       # e.g. music.bed_uplift_corporate_loop8
wav = os.path.join(PACK, "music", bed["file"]); side = json.load(open(os.path.join(PACK, "music", bed["sidecar"])))
```
Mood vocabulary in the manifest: tech, confident, warm, optimistic, hype, tension, edgy, cinematic, tense, playful, comic, calm, festive, curiosity,
triumphant, retro. `use`: launch, ad, talking_head, beat_edit, short_film, mime.
Length: a LOOP bed fits any length (the mixer tiles it along time; `Mix.add_bed(loop=True)` / `mixer.tile_rows`); a structured bed is fixed; for an exact
musical ending at the reel length compose one (2.5).

### 2.5 Composing a bed to an exact length (deterministic, about 1-9 s; first call JIT-compiles numba)
```python
import sys, math; sys.path.insert(0, PACK + "/music")       # music/_path.py then puts sfx/ (mpaudio, recipes) on sys.path
import compose as C, grid, mixer
bpm, fpb = grid.snap_bpm(C.PRESETS["uplift_corporate"]["bpm"], 30)
bars = math.ceil(T_reel / (fpb * 4 / 30))
r = C.compose("uplift_corporate", [("intro", 1, 0.45), ("main", bars - 2, 0.7), ("tail", 1, 0.15)], seed=5, fps=30)   # structure: str key or list of (name, bars, energy|(e0,e1))
y, G, g = mixer.master(r["mix"], -16.0, -1.5)    # optional preview level; Mix re-levels the bed against the voice anyway
# r["events"]: [{kind, sample, frame}] kinds kick/kick_soft/clap/snare/drop/hook_hit/riser/button; r["meta"]: as the sidecar meta
```
Signature: `compose(preset="tech_pulse", structure="loop_8", seed=1, fps=30, bpm=None, key=None, loop=None)` -> `{stems:{drums,bass,harmony,lead,fx}, mix, events, meta}`.
Rules inside: an energy step >= 0.3 between sections (non-loop) adds a crash + kick + a 1-bar noise riser ending 1 frame before the new section ("drop");
section 0 with energy >= 0.9 adds an audible hook hit on frame 0; a section named `tail` adds a tonic pad + bell "button" ending. Keep energy steps < 0.3
under continuous VO if you do not want crashes. Measured: 13 bars of uplift_corporate = 27.7 s music + 3 s ring-out, -16.0 LUFS, 8.6 s wall clock cold.
Presets (28): tech_pulse, uplift_corporate, hype_house, trap_half, cinematic_drone, playful_bounce, lofi_warm, desi_bounce, suspense_tick, anthem_build,
indian_fusion, bhangra_hype, raga_calm, festive_dhol, lofi_jazz, synthwave, deep_house, dnb_170, ambient_pad, chiptune_8bit, acoustic_folk_pluck,
documentary_marimba, orchestral_synth_epic, jazz_walk, comedy_pizzicato, corporate_bright, suspense_pulse, anthem_ramp.
Structures: loop_8, ad_30s, reel_15s, cine_30s, cine_60s, hook_6s, cold_open_3s, explainer_60s, sting_only, outro_8s, anthem_ramp_16.
Also: `theka.render_theka('teental'|'keherwa'|'dadra', fps, cycles, seed, bpm=None, tanpura=True)`, `theka.render_bhangra(fps, bars, seed, bpm=100)`,
`trailer.render_trailer('trailer_arc', fps, seed, act_bars=(4,4,4))` + `trailer.finish(y, fps)`.

### 2.6 Stingers and sonic logos
- Music library (NOT addressable by `Mix.add_cue`, which only knows sfx ids): `music/library/stingers/sting_{button_major,button_minor,rise_hit_2bar,rise_hit_1bar,pluck_resolve,tension_stab,bounce_out,lofi_chord,epic_swell,outro_sparkle}.wav`
  and `music/library/logos/logo_pattern_*`, `logo_brand_*` (fictional brands), `logo_sitar_*`; manifest gives `anchor_sample` (anchor lands on (F+1)).
  `logo.render_logo(name="Brand", seed=3)` -> `(stereo, anchor_sample, info)`: SHA-256-hashed, stable, original motif per brand name.
- SFX library equivalents that the mixer CAN place: `snd.logo.{ascend_land,drop_land,fifth_lift,hybrid,pulse_pad,question,two_note}` (tier 1, anchor = landing
  note 221-561 ms, ~3 s) and `snd.stinger.{alert,bump,cut_to_black,question,reveal,win}`. Bundle `talking_head` end card = `snd.logo.hybrid`.

---------------------------------------------------------------------------------------------------------------------------

## 3. Beat grid for snapping cuts

- Python: `music/grid.py`
  - `snap_bpm(bpm, fps) -> (bpm_snapped, frames_per_beat)`
  - `tempo_map(bpm, fps=30, bars=16, beats_per_bar=4, start_frame=0) -> {bpm, frames_per_beat, frames_per_bar, beat_seconds, bar_seconds, beat_frames, bar_frames, riser_1bar_s, snap_error_pct, ...}`
  - `tempo_ramp_map(bpm0, bpm1, fps=30, bars=8, ...)` (per-bar whole-frame beats), `cut_map(bpm, fps=30, bars=8, pattern="steady_beat", start_frame=0)`
    patterns steady_beat [1], bar_hold [4], two_beat [2], half_beat [0.5], accelerate [4,4,2,2,1,1,1,1], drop_build [...], syncopated [1.5,1.5,1] (in beats) -> `{frames, beats, frames_per_beat, end_frame}`
  - `frame_to_sample(f, fps)`, `samples_per_frame(fps)` (= 1600 at 30 fps).
- JS: `templates/_shared/plan.mjs beatGrid(bpm, fps, seconds, offset=0) -> {bpm, framesPerBeat, beatSec, beats:[s...]}`.
- CLI: `python3 cuts/cutgen.py beats --bpm 128 --fps 30 --pattern every_2 --bars 8 --snap [--tx whip]` (cuts + transition windows + sound anchor frames);
  `python3 cuts/cutgen.py snap --cuts 0,44,91 --fps 30 --onsets 1.5,3.0 [--tol 2]` (moves each cut to the nearest onset within 2 frames, refuses collisions).
- From a pack bed: use the sidecar. For a LOOP bed tiled over the edit, expand the grid with the loop period (and the rotation, below):
```python
def expand_grid(side, length_frames, start_frame=0, roll_frames=0):
    L = int(round(side["meta"]["length_frames"])); beats, bars = set(), set()
    for rep in range(-1, length_frames // L + 2):
        for b in side["beat_frames"]:
            f = start_frame + rep * L + b - roll_frames
            if 0 <= f < length_frames: beats.add(f)
        for b in side["bar_frames"]:
            f = start_frame + rep * L + b - roll_frames
            if 0 <= f < length_frames: bars.add(f)
    return sorted(beats), sorted(bars)
```
- **Put a downbeat on the hero frame (loop beds only; rolling a seamless loop keeps it seamless; tested):**
```python
fpbar = side["tempo"]["frames_per_bar"]
roll = (fpbar - HERO_FRAME % fpbar) % fpbar
y_rot = np.roll(y_bed, -roll * 1600, axis=0)     # then Mix.add_bed(y_rot, loop=True); grid = expand_grid(side, N, 0, roll)
```
  (test: uplift_corporate, hero frame 146 -> bars at 18, 82, 146, 210 ...). For a non-loop bed use `add_bed(start_frame=HERO - drop_frame)` (bed starts later)
  or compose with the drop section starting at `ceil(HERO / fpbar)` bars.
- **Rules by edit mode (skill + critic):** music-led cut pieces: >= 60% of cuts within 2 frames of an onset (`cutgen.py snap`). VO-led talking head
  (`plan.audio.mode: "vo"`): cuts never inside a word; jump cuts stay in the breaths; scoring a VO film in `music` mode "produces a failing sync score that
  means nothing". So: snap only visual ACCENTS (punch-in start, overlay pop-in, b-roll in, caption emphasis) to the nearest beat/kick when it is within
  about 2 frames and does not move them off their word; hits land on the grid, never between beats, in beat edits. A pack bed's kick lands on frame F, the
  SFX on F + 1 (do not "fix" that one-frame offset).
- A sync share is only evidence against its chance level (refstudy prints `chance_share`, `z_vs_chance`).

---------------------------------------------------------------------------------------------------------------------------

## 4. SFX library

Id scheme: registry id `snd.<seg>.<name>`; plan / catalog form `sfx/<seg>/<name>`. The segment is the REGISTRY segment, not the category:
`snd.hit.*` lives in category impact, `snd.tx.*` in transition, `snd.lift.*`/`snd.riser.*` in riser, `snd.amb.*` in ambience, `snd.sizzle.*`/`snd.sparkle.*` in sparkle.
`templates/_shared/audio.py` silently skips an unknown id: check ids (`python3 tools/check_ids.py`) and compare cue counts.

Manifest fields per sound: id, category, tags, tier (1 hero, 2 accent, 3 punctuation), desc, use, duration_s, samples, anchor_sample, anchor_ms,
anchor_kind (peak | fixed | loop), anchor_frame_offset (-1 for risers), tonal, loop, seed, peak_dbfs (-6), true_peak_dbtp, lufs_integrated, lufs_m_max,
lufs_s_max, centroid_hz, crest_db, sub28_db, sha, phone_drop_db, phone_safe, pairs_with (transition kinds), roles, place_rule, over_bed_db (default target), file.

### 4.1 Core ids for reels (dur s | anchor ms | tier | LUFS-I | default over_bed dB | notes)
Whoosh (anchor = loudest sample -> put it on the frame of maximum on-screen velocity / the cut):
- `snd.whoosh.swish_xs` 0.12 | 61 | t3 | -20.4 | +2 | caption slide, UI swipe (role caption)
- `snd.whoosh.swish_s` 0.20 | 134 | t3 | -20.5 | +2 | element / b-roll IN (role broll)
- `snd.whoosh.swish_out` 0.20 | 63 | t3 | -19.9 | +2 | element / b-roll OUT (role broll)
- `snd.whoosh.zip` 0.09 | 59 | t3 | -24.7 | +2 | zoom punch-in zip, speed lines
- `snd.whoosh.whip_pan` 0.32 | 156 | t2 | -18.5 | +2 | whip transition
- `snd.whoosh.whoosh_m` 0.45 | 226 | t2 | -18.5 | +2 | standard transition whoosh; `whoosh_in_m` 0.50 | 343 (object arrives); `whoosh_l` 0.80 | 502; `whoosh_xl` 1.50 | 1018 (t1 title swell)
- `snd.whoosh.reverse` 0.60 | 601 (fixed, pre-hit swell ending on the anchor); `blade`, `fire`, `flyby`, `magic_swirl`, `scifi_pass`
Hits (crest anchor ms ~3-25):
- `snd.hit.punch` 0.20 | 7 | t3 | -19.1 | +4.5 | zoom punch-ins, jump-cut emphasis (bundle hook_word)
- `snd.hit.soft` 0.30 | 10 | t3 | phone:weak | dissolves, soft landings; `snd.hit.low_thump` 0.20 | 10 | t3 | phone:weak (pair with a mid cue)
- `snd.hit.thud` 0.45 | 8 | t2; `snd.hit.stab` 1.10 | 75 | t2 (A major brand stab); `snd.hit.boom_meme` 1.40 | 24 | t2 (comedy punch-in / freeze)
- tier 1 (max one per 5-10 s, never within 3 s): `snd.hit.cinema` 2.89 | 258, `sub_drop` 1.20 | 3 (phone:weak), `taiko` 1.60 | 25, `braam` 3.30 | 151, `deep_impact`, `metal_cinematic`, `bass_drop_wobble`
Pops / clicks / UI (tier 3):
- `snd.ui.pop` 0.10 | 3 | -22.7 | +4 | word appears (bundle keyword_pop); `snd.ui.pop_down` 0.10 | 3 (element disappears)
- `snd.ui.click` 0.10 | 2 | -28.8; `snd.ui.tick` 0.03 | 2; `snd.tx.cut_tick` 0.05 | 2 (hard-cut tick, bundle jump_cut); `snd.ui.blip` 0.14 | 4 (list item)
- `snd.ui.slide` 0.20 | 86 (lower third); `snd.ui.count_run` 0.90 | 623 (stat count-up, anchor = the ding); `snd.ui.count_tick` 0.05 | 2 (one per increment)
- `snd.ui.success` 0.55 | 64; `snd.ui.notify` 0.82 | 26; `snd.ui.swipe_ding` 0.50 | 66; `snd.ui.type_key`, `snd.ui.typing_burst` 1.43 | 381; `snd.ui.mic_on/off`, `snd.ui.error`
- `snd.device.mouse_click`, `keyboard_mech_soft/clack`, `message_sent/received`, `notify_ding`, `loading_tick`, `progress_fill`
Risers / lifts (anchor = END; `anchor_frame_offset = -1`: give the mixer the HIT's visual frame and it ends one frame before the hit):
- `snd.lift.inhale` 0.24 | 243 (300 ms breath before a word or title) | t3
- `snd.riser.tape_up` 0.50 | 501; `riser.noise_1bar` 1.82 | 1817; `riser.pitch_noise` 1.94; `riser.reverse_cymbal` 2.40; `riser.glitch_stutter` 2.0;
  `riser.noise_2bar` 3.67; `riser.supersaw_2bar` 4.0; `riser.snare_roll_build` 4.0; `riser.string_tension` 4.0; `riser.shepard` 4.0; `riser.siren` 2.0; `riser.heartbeat` 4.0; `riser.noise_4bar` 7.31
- Downlifters (anchor = START, on the drop): `snd.lift.down` 0.86, `snd.lift.down_long` 1.92
Transition sweeteners (`snd.tx.*`): `scale_punch` 0.30 | 73 (zoom punch-in: 60 Hz punch + zip), `push` 0.24 | 141, `blur_cross` 0.59 | 281, `dissolve_pad` 0.94 | 378,
`flash_swell` 0.69 | 315, `glitch_stutter` 0.35 | 101, `luma_wipe` 0.48 | 233, `mask_reveal` 0.94 | 240 (end), `zoom_through` 0.80 | 328 (thud),
`freeze_hit` 0.45 | 1 (start), `tape_stop` 0.35 | 1, `smash_cut` 0.70 | 4 (t1, place after silence), `dip_to_black` 0.85 | 2, `light_leak`, `film_burn`,
`ink_bloom` (phone:weak), `iris_open/close`, `match_link`, `morph_warble`, `pixel_dissolve`, `shutter_flash`, `speed_ramp` 0.80 | 651, `tape_down`.
Loops (anchor_kind loop; run to the end unless `until_frame`): `snd.amb.room_tone` (ships -18.1 LUFS-I; sit 20-26 dB under the bed: `over_bed_db: -26`),
`snd.amb.studio_air`, `snd.amb.office`, `snd.ui.agent_working` (4 s), `snd.ui.listening_loop`, `snd.elec.crackle_loop`.

All ids tagged `use` talking_head (78): see `sfx/manifest.json` filter; roles index: caption (pop, pop_down, tick, click, blip, swish_xs, mic_on/off, notify, ...),
textReveal (pop, blip, type_key, typing_burst, lift.inhale, foley.typewriter), broll (swish_s, swish_out), statReveal (count_run, count_tick, success, cash.ka_ching),
freeze (camera.shutter, cartoon.record_scratch, hit.boom_meme, cartoon.sad_brass).

### 4.2 Bundle `talking_head` (sfx/bundles.json)
"voice first, sfx are punctuation 12-24 dB under the voice, no tier 1 except the end logo"; bed presets lofi_warm, uplift_corporate; BPM 100-120; -14 LUFS.
| role | id | level re voice (dB) |
|---|---|---|
| keyword_pop | `snd.ui.pop` | -14 |
| punch_in | `snd.tx.scale_punch` | -14 |
| jump_cut | `snd.tx.cut_tick` | -22 |
| broll_in / broll_out | `snd.whoosh.swish_s` / `snd.whoosh.swish_out` | -18 |
| stat | `snd.ui.count_run` | -16 |
| list_item | `snd.ui.blip` | -18 |
| breath | `snd.lift.inhale` | - |
| interrupt | `snd.stinger.alert` | -16 |
| hook_word | `snd.hit.punch` | - |
| end_card | `snd.logo.hybrid` | - (over bed default +5) |
| room_tone | `snd.amb.room_tone` | - |
Related: `cuts/patterns.json talking_head`: punch_in sfx `sfx/hit/punch`, scale 1.12, in 140 ms, max 1 per 4 s; cut_tick `sfx/ui/tick` gain -18 (note: differs from the
bundle's `snd.tx.cut_tick`); reframe alternate 1.0/1.15/1.0/1.25 on each jump cut; beat_hold 450 ms after a punchline. The motion-pack talking-head template
(`templates/talking-head/config.mjs`) uses absolute stem gains: punch `sfx/tx/scale_punch` -14 dB, emphasis `sfx/ui/pop` -20 dB, b-roll `sfx/whoosh/swish_s` -14 dB,
lower third `sfx/ui/slide` -18 dB. Other bundles worth borrowing: `kinetic_type` (word pop, type_key, swish_xs, title_word hit.punch), `beat_edit`, `saas_launch`, `product_ad`.

### 4.3 Transition kind -> sweetener (sfx/mpaudio/sweeteners.py TABLE; `Mix.add_transition(kind, frame, duration_frames, energy, direction)`)
where = which frame of the transition window the ANCHOR serves: start = frame, mid = frame + duration//2, end = frame + duration; gain_db = (energy - 0.5) x 6.
| kind | id (where, tier, over_bed) |
|---|---|
| hardCut | `snd.tx.cut_tick` (start, 3, 0.0); + `snd.hit.low_thump` (start, 3, +2) at energy >= 0.7; NOTHING at energy < 0.35 |
| whip | `snd.whoosh.whip_pan` (mid, 2, +2) |
| push | `snd.tx.push` (mid, 3, +1) |
| scalePunch | `snd.tx.scale_punch` (start, 3, +3) |
| zoomThrough | `snd.tx.zoom_through` (end, 2, +3) |
| flash | `snd.tx.flash_swell` (mid, 2, +2) |
| glitch | `snd.tx.glitch_stutter` (start, 2, +3) |
| dissolve | `snd.tx.dissolve_pad` (mid, 3, -2) |
| dipToBlack / dip | `snd.tx.dip_to_black` (start, 2, -2) |
| blurCross | `snd.tx.blur_cross` (mid, 3, 0) |
| match | `snd.tx.match_link` (start, 3, +1) |
| morph / ink / iris / lumaWipe | `tx.morph_warble` mid / `tx.ink_bloom` mid / `tx.iris_close` (or iris_open with direction="open") mid / `tx.luma_wipe` mid |
| maskReveal | `snd.tx.mask_reveal` (end, 3, +2) |
| speedRamp | `snd.tx.speed_ramp` (mid, 2, +2) |
| freezeHold | `snd.tx.freeze_hit` (start, 2, +3) |
| smash | `snd.tx.smash_cut` (start, 1, +4.5) (comedy smash: 200 ms of silence before; `cutgen.py smash`) |
| shutter | `snd.whoosh.swish_s` (start) + `snd.camera.shutter` (mid) |
| swipeUp | `snd.whoosh.swish_xs` (mid) |
| spin | `snd.whoosh.whoosh_m` (mid) |
| pagePeel | `snd.paper.flip` (mid) |
| pixelSort / ditherDissolve | `snd.tx.glitch_stutter` + `snd.sizzle.grain` |
| jcut | none |
Any other kind falls back to `transitions/catalog.json` `sfx` rows (`{"id":"sfx/whoosh/whip_pan","at":"cut","offset_f":1,"gain_db":2}`): catalog convention
"anchor lands at (at + offset_f) frames", i.e. offset_f already contains the +1 rule; when feeding the MIXER use frame = at_frame + offset_f - 1 (as
`sweeteners.catalog_rows` does). JS `templates/_shared/plan.mjs TX_SFX` maps 'transitions/<kind>' -> one sfx id (note: flash -> shutter_flash there,
flash_swell in Python; iris -> iris_open there).

---------------------------------------------------------------------------------------------------------------------------

## 5. Loudness of the assets
- SFX: every file peak-normalised to -6 dBFS (TP about -5 to -6 dBTP). LUFS-I is not comparable across short sounds; the manifest also has momentary /
  short-term maxima. Range: whooshes LUFS-M max -15..-25; ui pops/clicks -22..-29; hits -13..-22; risers -6..-17; logos -12..-14. The library level is
  headroom for layering, not a mix level: the mixer solves each cue's level.
- Default over-bed targets (K-weighted, 60 ms from the anchor; risers 200 ms before it): hero hit +4.5, whoosh +2, ui +4, logo +5, tx +2.5, riser +4,
  foley +3, indian +3.5; > +6 is linted (R2, no jump scares). Talking-head cues sit under the voice instead (`over_vo_db` -12..-22).
- Beds: mastered to -16.0 LUFS-I stand-alone, TP -1.5..-5.5 dBTP (preview level; the mixer re-levels: with a voice present, the un-ducked bed is set to
  voice LUFS -1 LU (`Mix.bed_rel_vo_lu = -1.0`) then ducked 9 dB under speech, so about -10 LU under the voice while talking).
- Music stingers -12.7..-18.3 LUFS-I, TP -3.0; music logos -13.9..-15.2 (sitar -21.5), TP -3.0.
- Ambience loops: 8 s; level them about -10 dB re the bed (loop default) and room tone -20..-26.
- House master: -14 LUFS-I, TP <= -1.5 dBTP on the WAV, AAC probes <= -1.0 dBTP; HyperFrames lowers the WHOLE track if the AAC is hotter than -1 dBTP.
  Platforms: IG / TikTok / X / LinkedIn publish no loudness spec (grade D); YouTube turns loud content down toward -14.

---------------------------------------------------------------------------------------------------------------------------

## 6. Timing contract (how to time SFX to transitions and overlays)

The v9 hit contract (exact, tested): a cue whose VISUAL frame is F puts its anchor sample on `(F + 1) x 48000 / fps` (one frame after the picture).
In seconds, for a hand-placed `<audio>`: `start_s = (F + 1 + anchor_frame_offset) / fps - anchor_ms / 1000`; if start_s < 0 use `data-start="0"` and
`data-media-start = -start_s`. Quantise F = round(t * fps) ONCE in the compiler (python rounds half to even; a JS plan may pick the other neighbour: ears saw 1-frame errors).
- Hard cut / jump cut at output frame Fc: `snd.tx.cut_tick` (or `snd.ui.tick`) at F = Fc (a tick so the cut is not a sterile hole; skip on quiet cuts).
- Whoosh on a moving element / transition: F = frame of maximum on-screen velocity = the blur midpoint = `start + duration//2`; the sound's anchor is its
  loudest sample, so the whoosh PEAKS on the cut. (Reel Director's current `lead` seconds-before-the-word is replaced by this anchor math.)
- Riser into a hit at Fh: give the riser F = Fh; its `anchor_frame_offset = -1` makes it END on Fh x spf, one frame before the hit lands at Fh + 1.
  Downlifter: anchor = start, put it on the drop frame.
- Overlay / sticker / caption pop-in: F = first frame the element is visible (or the frame its scale-in overshoot peaks); pop-out (`ui.pop_down`,
  `whoosh.swish_out`) on the first frame of the exit.
- Zoom punch-in on a word: `snd.tx.scale_punch` (or `snd.hit.punch`) at the punch start frame; `snd.whoosh.zip` ends ON the cut (catalog offset_f 0).
- B-roll / cutaway in: `snd.whoosh.swish_s` at the first visible frame; out: `snd.whoosh.swish_out` at the exit. B-roll leads the line by 150 ms (recipe H).
- Lower third: `snd.ui.slide` at its entrance. Stat counter: `snd.ui.count_run` with its anchor (the ding) on the frame the number lands, or `ui.count_tick` per increment.
- Loops: start at F, stop with `until_frame` (40 ms fade).
- Short-form: an audible event on frames 0-2 (lint R10 checks `first cue frame > 2`), or the voice starting on frame 0 (pass `voice_first_frame` to `lint_cues`),
  or a planned quiet open in `plan.audio.quiet` (<= 2 s). Last 0.15 s digital zero (the mixer does it).
- Hierarchy (lint R4): tier-1 at most one per ~5 s and never within 3 s; tier-2 average spacing >= 1.0 s; R9: the same id 3+ times in 8 events -> vary
  (the mixer already round-robins repeated ids: seed + occurrence, +/-1.5 dB). R12: a phone-weak tier 1-2 cue needs a phone-safe partner within 3 frames.
- Beat hold: keep the face 450 ms after a punchline before cutting.

---------------------------------------------------------------------------------------------------------------------------

## 7. The mixer: exact API, cue sheet, measured behaviour

```python
import sys; sys.path.insert(0, PACK + "/music"); import mixer       # music/_path.py adds PACK/sfx to sys.path
m = mixer.Mix(fps=30, length_s=T)                    # Mix(fps=30, length_s=20.0, lib=None); lib = mixer.Library(sfx_dir) reads sfx/manifest.json
m.add_bed(bed_audio, start_frame=0, gain_db=0.0, loop=True, lufs=None)   # float (n,2) or (n,) at 48 kHz; loop tiles along time
m.automate_bed([{"frame": f, "gain_db": g}, ...])   # linear in dB between breakpoints, held outside; applied after the voice-relative level, before the duck
m.add_vo(vo_audio, start_frame=0, gain_db=0.0)       # ducks the bed (duck_db, look-ahead 80 ms, attack 15 / hold 120 / release 350 ms) + mid carve (-3 dB @250 Hz, -3.5 @3 kHz)
m.duck_db = 12.0                                      # optional (default 9); m.bed_rel_vo_lu = -1.0 (un-ducked bed vs voice, LU)
m.add_cue(sid, frame, tier=None, over_bed_db=None, over_vo_db=None, gain_db=0.0, pan=0.0, seed=None, why="", until_frame=None)
m.add_transition(kind, frame, duration_frames=0, energy=0.5, direction=None)
rep = m.render(out_dir, name="master", lufs=-14.0, ceiling_db=-1.5, duck=True, solve=True, aac=True, phone=True, stems=True, tail_zero_s=0.15)
audio = rep.pop("_audio")    # writes <out>/master.wav (PCM_24), master_report.json, stem_music.flac, stem_sfx.flac, stem_vo.flac, nomusic.flac
issues = mixer.lint_cues([{"id": c["id"], "frame": c["frame"], "tier": c["tier"], "over_bed_db": c["over_bed_db"]} for c in m.cues],
                         fps=30, short_form=True, voice_first_frame=0, lib=m.lib, quiet=None)
```
CLI form: `python3 music/mixer.py cuesheet.json --out DIR` with
```json
{"fps": 30, "length_s": 20, "bed": {"file": "bed.wav", "loop": true, "gain_db": 0, "start_frame": 0, "automation": [{"frame": 560, "gain_db": 0}, {"frame": 590, "gain_db": -40}]},
 "vo": {"file": "vo.wav", "start_frame": 0, "duck_db": 12},
 "cues": [{"id": "snd.ui.pop", "frame": 40, "over_vo_db": -14}, {"id": "snd.tx.cut_tick", "frame": 160, "over_bed_db": -19}],
 "transitions": [{"kind": "whip", "frame": 90, "duration_frames": 8, "energy": 0.6}],
 "quiet": [{"t": [0, 1.2], "kind": "open", "why": "..."}],
 "master": {"lufs": -14, "ceiling_db": -1.5}}
```
(paths relative to the cue sheet's folder; prints the report, `WARN` lines and `LINT` lines). `templates/_shared/audio.py <plan.json> <out.wav>` is the
template wrapper (plan cues `{id:'sfx/ui/pop', t, overVoDb?, overBedDb?}`, `plan.music = 'music/<bed id>'`, `plan.vo`, `plan.duckDb`, `plan.bedAutomation`,
`plan.ceilingDb`, `plan.fadeInMs`, `plan.audio.quiet`); without a bed and with `--stem` it places cues at absolute `gainDb` (talking-head template).

Measured in scratch (20.1 s, three real takes concatenated as vo, `bed_lofi_warm_loop8` / `bed_uplift_corporate_loop8`, 9-10 cues):
- master -14.01 LUFS-I, TP -1.50, AAC probes aac -1.29 / aac_at -1.46 dBTP, tail zero ok, stem sum error 0.0, render 4.3 s.
- Cues inside speech with `over_vo_db`: measured exactly the target (-14.0 / -18.0).
- **Gotcha found: `over_vo_db` on a cue whose 60 ms window falls in a speech GAP** (before the first word, in a breath, at a jump cut, which is always a gap)
  asks for -39 .. -57 dB trims; the solver clips at -30 dB and warns (`trim_clipped_from_db`): the cue ends up 22-30 dB under the bed, inaudible. There is no
  voice floor (the bed path has one: bed integrated - 10 dB). Fix: choose the reference per cue from the word spans: anchor window overlaps a word ->
  `over_vo_db = level_re_voice`; otherwise `over_bed_db` (measured: `over_bed_db = level_re_voice + 3` landed exactly, e.g. -11 for a -14 role).
- `add_transition("hardCut", ...)` gives `snd.tx.cut_tick` at over_bed 0.0 dB (as loud as the local bed). For talking-head jump cuts prefer an explicit
  `add_cue("snd.tx.cut_tick", F, over_bed_db=-19)` (the bundle's -22 re voice).
- With a voice present, `add_bed(gain_db=...)` is overridden: render() re-levels the whole bed buffer to voice LUFS + `bed_rel_vo_lu` unless `add_bed(lufs=...)`
  was given. To make the bed quieter under a talking head set `m.bed_rel_vo_lu` (e.g. -4) or `m.duck_db`. (`templates/_shared/audio.py`'s `musicGainDb` is
  therefore ignored when `plan.vo` is set.)
- Cue levels are measured against the UN-dipped, UN-automated bed: a logo over a bed you automate down still measures +5 over the full bed.
- R10 fired for a first cue on frame 3 (`> 2`); passing `voice_first_frame=0` (talking head: the voice is on frame 0) clears it.
- Music-library stingers / logos are not in the sfx manifest, so `add_cue` cannot place them; use `snd.logo.*` / `snd.stinger.*` or mix them in yourself.
- External CC0 ids (`ext.*`) are not known to `mixer.Library` either (would need a merged manifest with seed / anchor_kind / over_bed defaults).

---------------------------------------------------------------------------------------------------------------------------

## 8. Instantiating it in a HyperFrames composition

Audio is never driven by the GSAP timeline: HyperFrames owns media playback from `data-start` / `data-duration` / `data-media-start` / `data-volume`
(never `play()`/`pause()`/seek in code; never tween volume with GSAP; every `<audio>` needs an `id` or it is silent; no `crossorigin`).

### Mode A (recommended: the pack's mode)
```html
<!-- inside #cam: the takes keep their timing but are MUTED (their sound is inside mix.wav) -->
<video id="take-0" class="clip take" src="assets/take1.mp4" muted playsinline
       data-start="0" data-duration="2.400" data-media-start="1.120" data-track-index="0"></video>
...
<!-- one baked master at 0 -->
<audio id="mix" src="assets/mix.wav" data-start="0" data-duration="{T}" data-track-index="9" data-volume="1"></audio>
```
Pipeline in the compiler (Python, after the timeline is solved):
1. `vo.wav`: for each kept segment, slice the cleaned take audio `[round(media_in*48000) : + round(duration*48000)]`, 6 ms fades, add at `round(out_start*48000)`.
2. Pick / rotate / compose the bed (sections 2.4, 2.5, 3). 3. Turn every cue into a mixer cue (section 6 frames; reference per section 7).
4. `Mix.render(work_dir)` -> copy `master.wav` to the composition's assets; keep `master_report.json` for QA.
5. Visual beat sync: GSAP positions from the grid, e.g. `tl.fromTo("#bg", {scale:1.02},{scale:1,duration:0.18,ease:"power2.out",immediateRender:false}, beatFrame/30)`.
HyperFrames re-encodes AAC: if the render log says `Audio lowered by X dB`, lower `ceiling_db` (-2.0 .. -3.0; -3.0 up front for bass-heavy 60% beds or
click-dense UI cues) and/or fade the first 40 ms in when the mix starts on a hit (`plan.fadeInMs: 40`). Always grep the render log for `lowered`.
Reel Director's own `audio.master()` loudnorm pass afterwards should then be a near no-op (keep it as a guard, TP -1.0).

### Mode B (keep per-element audio, what compiler.py does today)
Per SFX: `<audio id="sfx-N" src="assets/snd.ui.pop.wav" data-start="{(F+1+off)/fps - anchor_ms/1000}" data-duration="{duration_s}" data-track-index="7" data-volume="{10**(gainDb/20)}">`
with the talking-head template's absolute gains (-14 punch / b-roll, -20 emphasis pop, -18 lower third / tick) since the takes are levelled to -16 LUFS;
music `<audio id="music">` with a static `data-volume` and HyperFrames' own `data-fx-carve` / `data-automation` lanes for ducking (hyperframes-audio skill:
carve against a voice GROUP, `npx hyperframes check` before render). This loses the measured levels, the pre-hit vacuum, the AAC probes and the stems,
and motion-pack has not validated it ("per-clip `<audio>` ... is not built yet").

### Today's Reel Director (read-only observation)
`compiler.py` emits each `sfx` cue as its own `<audio data-volume=0.8>` placed at `span.start - lead`, and the music as `<audio id="music" data-volume=0.18>` with no
ducking; `audio.py` levels each take to -16 LUFS and loudnorms the final MP4 to -14 / -1.0. Moving to mode A replaces the hand volumes with solved levels and
moves every SFX onto the F+1 anchor contract.

---------------------------------------------------------------------------------------------------------------------------

## 9. QA after render
- `python3 ears/listen.py out.mp4 --plan plan.json --mode vo --transcript words.json [--role vo_doc|explainer] [--json ears.json --md ears.md]`
  (loudness, TP, tail silence, ducking depth >= 9 dB, cues on F + 1, no cut inside a word, dead air, repetition, mono). Plan fields: `audio.mode`,
  `audio.quiet [{t:[a,b], kind: open|dip|gap|hold, why}]`, `audio.role`. It measures; one human listen at phone size and on headphones is still required.
- `python3 templates/_shared/sheet.py out.mp4 sheet.jpg t1,t2,...` prints LUFS-I and TP of the DELIVERED file (target -14 +/- 0.5, TP <= -1.0).
- Mixer report: per cue `measured_over_bed_db`, `measured_over_vo_db`, `trim_clipped_from_db`, `phone_ok`, `gr_db`; `warnings`.

## 10. Skill guidance and gotchas (motion-pack SKILL.md + references), condensed
- "Sound is half the cut": anchor on (F+1); a whoosh peaks on the cut; a riser ends one frame before the hit; every transition gets its paired sweetener.
- Master -14 LUFS-I, TP <= -1.5 dBTP on the WAV (-2.0 if clicky transients push the AAC probe over), <= -1.0 on the delivered file.
- Never gain SFX by hand (editor, ffmpeg volume): set `overBedDb` / `overVoDb`, or `gainDb` only when there is no bed.
- Recipe H (talking head): autocut silences > 0.5 s keeping a 120 ms breath; captions 2-4 words; b-roll 35-50% coverage, 1.2-3 s each, leading the line by
  150 ms; punch-ins 1.12 on emphasis max 1 per 4 s; lower third; bed ducked 9 dB; SFX on emphasis, punch-ins, b-roll and the lower third.
- Sound may enter 1-2 s after a moving frame 0 if planned (`plan.audio.quiet` kind open); quiet end-card hold (<= 9 s) is a first-class ending, but a
  pulsing bed that merely falls still reads as a decay: put `snd.amb.room_tone` at `over_bed_db: -26` under the hold while the bed falls to -40.
- A bare click track as a bed makes the solver ask for 60-80 dB trims (use a steady tone or a real bed).
- The library is measured, not auditioned: listen once before a hero use (Indian beds' chroma warnings come from drum partials; glass / bell / bubble
  tables are grade C).
- Determinism: same code + seed -> same bytes; SHAs are per CPU platform; anchors are not.
- Do not write into the pack from another project: set `NUMBA_CACHE_DIR` and `PYTHONPYCACHEPREFIX` (numba `cache=True` writes next to the source;
  `python -I` ignores PYTHON* env vars).
