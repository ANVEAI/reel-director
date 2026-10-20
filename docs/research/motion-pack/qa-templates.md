# motion-pack module group "qa-templates": eyes, ears, storyboard, templates (+ gotchas.md, critic.md)

Pack: motion-pack (P below). Skill: `skills/motion-pack/SKILL.md` in motion-pack,
`references/critic.md`, `references/gotchas.md`. Everything below was read from source and, where marked VERIFIED,
run on 2026-10-20 with outputs only under a scratch folder (`scratch-qa/`, not kept). Nothing in either repo was edited.

---------------------------------------------------------------------------------------------------------------------
## 0. TL;DR for Reel Director

* `eyes/look.py` (picture) and `ears/listen.py` (sound) are deterministic, model-free critics of a DELIVERED MP4.
  numpy + scipy + ffmpeg only (ears also pulls numba through `sfx/mpaudio`). No torch unless you opt into CLAP mood.
  ~2-3 s wall each on a 6-13 s 1080x1920 clip. Both suites pass here (eyes 61 tests / 147 s, ears 39 tests / 111 s; VERIFIED).
* Run them as a SUBPROCESS from Reel Director (never import into the mlx/silero process). Use
  `/opt/anaconda3/bin/python3` (numpy 1.26.4, scipy 1.11.4, numba 0.59.0 = the pack's pinned requirements.txt) or the
  reel-director `.venv` python (numpy 1.26.4, scipy 1.17.1, numba 0.68.0, also has torch 2.14 via silero-vad, which eyes/ears
  never import). Env: `PYTHONDONTWRITEBYTECODE=1 NUMBA_CACHE_DIR=<scratch> EARS_CLAP_MODEL=` (unset).
* Exit code is ALWAYS 0 (unless undecodable). The gate must parse `--json` output: `checks[].status`, `scores`, `top_issues`.
* The critics only become exact when Reel Director emits a `plan.json` (texts with boxes, shots per kept clip, holds,
  `audio.mode: "vo"`, platform, template) and a `words.json` transcript in OUTPUT time. Neither template in the pack
  writes `plan.texts` boxes; Reel Director must write them itself (it knows its CSS).
* Real findings on `reel-director/renders/demo-week2.mp4` (VERIFIED, no plan): eyes frame0 FAIL (dark, subject 1.11:1),
  frozen 5.97-8.33 s FAIL (2.36 s static card), banding FAIL (dark gradient, 97% worst frame), safezones FAIL (captions at
  top:64% = y~1229 run below the conservative bottom 1248). ears: tail not digital zero FAIL, mud warn (+10.6 dB 250-500 Hz),
  first audible frame 6 warn. With transcript: speech PASS (160 wpm, SMR 40.9 dB).
* Copy `templates/talking-head` structure (autocut -> framing ladder -> punch-ins -> karaoke captions -> B-roll ->
  lower third -> layers -> one mix.wav) but NOT its caption numbers (100 px, stroke-only contrast, no master pass:
  eyes/ears flag all three, VERIFIED). Audio model to copy: `templates/multi-voice-doc` (muted picture + one mastered
  `mix.wav` from `music/mixer.py` with VO duck).

---------------------------------------------------------------------------------------------------------------------
## 1. eyes (visual critic) - `P/eyes/`

Files: `look.py` (CLI + `analyze`), `core.py` (probe/decode/cuts/platform rect/plan parsing), `checks_frames.py`,
`checks_text.py`, `checks_edit.py`, `report.py`, `manifest.json` (ALL thresholds in `spec`), `tests/` (61 tests +
`*.mutants.json`). Size 420 KB. Deps: numpy, scipy, ffmpeg/ffprobe on PATH (env `FFMPEG`, `FFPROBE` override). Pillow
only in tests. No clock, no download.

### CLI
```bash
PYTHONDONTWRITEBYTECODE=1 python3 P/eyes/look.py <video.mp4> \
   [--plan plan.json] [--platform reels.organic|tiktok.organic|shorts.organic|meta.ad.9x16|yt.ad.15|x.video|linkedin.video|hero.web|yt.bumper.6
                       | conservative|tiktok|reels|shorts|ytAd|metaStory|wideTitle|wideAction] \
   [--format hype_ad|beat_edit|talking_head|mime_spot|short_film] [--draft] [--fps 30] \
   [--json out/eyes.json] [--md out/eyes.md] [--quiet]
```
* `--platform`: a `templates/_shared/plan.mjs` preset OR a `type/safezones.js` id. **A preset on a 9:16 frame ALWAYS uses the
  `conservative` rect: x 65-960, y 269-1248 at 1080x1920** (left 65, right 120, top 269, bottom 672). The `reels` safezones id
  is a different, looser rect (x 60-960, y 220-1500). Default: plan.platform, else by aspect (`conservative` for 9:16).
* `--format talking_head` = cuts/patterns.json pace: ASL 2.5-5.0 s, 6-12 shots per 30 s (default from plan.template
  `talking-head`).
* `--draft` waives resolution/bit-rate rules (animatics at 960x540).

### Library
```python
import sys; sys.path.insert(0, P)
from eyes.look import analyze          # (look.py inserts the pack root itself when run as a script)
rep = analyze(path, plan=plan_dict, platform=None, fmt=None, draft=False, fps=None, name=None, only=None)
# only=['frame0','frames','flashes','banding','safezones','readability','pacing','composition','encode'] subset
```
Recommend the CLI in a subprocess instead (isolation, numba/numpy versions).

### Report shape (`--json`)
```
{input, duration_s, width, height, fps, platform, plan: bool, frames,
 checks: [{id:'eyes/<name>', category, status:'pass|warn|fail|n/a|info', measured:{...}, target:str,
           issues:[{severity:'warn|fail', t:[a,b], what, fix, viewer, kind}], notes:[str]}],
 scores: {hook, continuity, flashes, banding, safezones, readability, pacing, composition, encode,   # 1-10 or null
          critic_hook_2s, critic_phone_readability, critic_motion, critic_variety},
 top_issues: [{check, severity, t, viewer, fix}]   # 3, one per check first, weighted by viewer_weight}
```
Scoring: each category starts 10, fail -3, warn -1, one problem (`kind`) counts once, any fail caps at 7.
critic rows: hook_2s=hook; phone_readability=min(safezones, readability); motion=min(continuity, flashes);
variety=min(pacing, composition). banding, encode have no row ("fix before delivery").

### The 9 checks (thresholds from manifest spec)
| check (category) | fails / warns |
|---|---|
| frame0 (hook) | black (mean<=16 & std<6) or flat (std<=3) FAIL; std<=12 warn; subject WCAG (P85 vs P15 around strongest DoG spot) <1.5 FAIL, <3 warn; first visible change after frame 6 warn, after 0.5 s FAIL |
| frames (continuity) | unplanned black >=3 frames FAIL; black tail >=0.3 s warn, >=1 s FAIL; empty >=0.5 warn >=1 s FAIL; frozen (diff<0.15 lvl, <=0.01% px moved 6 lvl) >=0.5 s warn, >=2 s FAIL; timestamp gap >1.5 frames = stall FAIL. Planned holds/dips are notes; without plan a freeze to the end <=4.5 s = end card |
| flashes | WCAG 2.3.1 general + red flash, >3 in any 1 s FAIL |
| banding | up to 12 native frames; staircase share >=4% warn; FAIL when 25% of samples >=20% |
| safezones | plan mode: each `texts[].box` vs rect (0.5 px tol) -> FAIL; detect mode (no boxes): persistent text-like edge blocks >=50% outside FAIL, >=15% warn (flags in-scene UI text too) |
| readability | per text: size at 1080 (shorter side) vs floors (tall: read 56, headline 96, caption 64, label 30, endcard 30, lowerthird 48, inworld 28 px); caption on 9:16 >80 px warn; <9 px on a 360 px phone FAIL; hold < 0.35+0.28*words (>=0.5 s) FAIL (warn if >=80% or role caption: captions only ever warn); label <2 s FAIL; read line >6 words warn; contrast (fg hex vs P5/P95 of backdrop luminance, worst of up to 3 frames) <3 FAIL, <4.5 warn (capped to warn when fg estimated); hook text start > 0.3 s on tall presets warn; hook >7 words warn |
| pacing | hard cuts only (diff >=2.5% & 4x neighbours); static stretch >3.5 s warn, >7 s FAIL (planned hold exempt); plan.paceRule {aslMax, longMax} or format ASL range warns |
| composition | 2nd saliency blob >=80% of the first on 30% of key frames warn; black bars >=2% warn, >=15% area FAIL (unless plan.eyes.letterbox / layers name bars); wrong aspect FAIL; short side <1080 warn, <720 FAIL |
| encode | not yuv420p FAIL; not h264 / moov after mdat / HD untagged colour / GOP >5 s (FAIL >10 s) / <0.01 bpp (FAIL <0.004) / blockiness >=1.75 (FAIL 2.5) warn |

### What the plan can tell eyes (`core.plan_texts / plan_holds / plan_black`)
```json
{"fps": 30, "size": [1080, 1920], "platform": "reels.organic", "template": "talking-head",
 "shots": [{"id": "hook-0", "start": 0.0, "dur": 2.63, "tx": "transitions/cut"},
           {"id": "card-1", "start": 5.97, "dur": 2.36, "hold": true}],
 "texts": [{"id": "cap0", "text": "Most creators waste", "t": [0.10, 1.19],
            "box": [65, 1054, 960, 1224], "fontPx": 72, "role": "caption", "fg": "#FFFFFF", "lines": 1},
           {"id": "ov1", "text": "3 HOURS", "t": [1.65, 3.2], "box": [190, 700, 890, 820], "fontPx": 96, "role": "headline", "fg": "#000000"}],
 "holds": [{"t": [5.97, 8.33], "why": "cutaway card"}],
 "black": [],
 "paceRule": {"aslMax": 4, "longMax": 6},
 "eyes": {"letterbox": false},
 "audio": {"mode": "vo", "quiet": [{"t": [11.0, 12.55], "kind": "hold", "why": "end card"}]}}
```
* texts sources in order: `plan.texts` / `plan.eyes.texts` (exact: box, fontPx, role, fg) -> else `shots[].text`+`textDur`
  (timing only) -> else talking-head `captions[]` `{words:[{w}], start, end}` (timing only, role caption).
* `t` may be `[a,b]` or `start`+`end`/`dur`; box `[x0,y0,x1,y1]` px of `plan.size` frame (scaled to delivered width);
  box may also be `{x0,y0,x1,y1}`.
* roles: read (default), headline, caption, label, endcard, lowerthird, inworld.
* holds: `shots[].hold: true` (+start/dur), `plan.holds`/`plan.eyes.holds [{t,why}]`, `audio.quiet` kind `hold`.
* dips: `plan.black [[a,b]]`, or a shot whose `tx`/`transition` contains `dip` (0.5 s window).

### VERIFIED experiment (talking-head demo + a hand plan with caption boxes)
`templates/talking-head/out/talking-head.mp4` with explicit `texts` (box 86..994 x 1075..1180, fontPx 100, fg #FFFFFF):
safezones FAIL (right edge 994 > 960 by 34 px), readability FAIL: worst contrast 1.36:1. Captions are white with an 8 px
dark `-webkit-text-stroke` over a bright backdrop: **eyes does not credit a stroke** (stroke pixels count as backdrop; the
ratio is min(fg vs P5, fg vs P95) of the backdrop, P95 = bright scene 0.72 rel. lum.). Only a scrim/pill behind the
caption (or a calm dark backdrop) passes 4.5:1. Also: a word highlighted in an ACCENT colour is not "fg" (fg = within RGB
distance 60 of the declared hex), so its pixels join the backdrop sample; a light accent next to white text can drag the
P95 side. Prefer a dark pill + white text + accent pill/underline, or accept the warn. The lower third (#111 on white
box) measured 10.9:1.
Lesson for boxes: give a TIGHT box around the rendered text block (not the full caption band) and a real `fg`.

### Caption layout that passes eyes (from `P/type/safezones.js`)
* `captionBox('conservative', 1080, 1920, {lines: 2, fontPx: 72})` -> x 65..960, y1 = 1248 - 24 = 1224, y0 = 1224 - 2*1.18*72 = 1054.
* `lintCaptionStyle`: 9:16 captions 64-80 px at 1080 wide, <=2 lines, <=18 chars/line, 1-4 words per chunk (talking head 3).
* Reel Director today: `.caption{top:64%}` (y=1229) + `font-size:82px` + `.word.emph{1.2em}` (98 px) -> bottom of band
  ~1321 (1 line of 82 px x 1.12) to ~1413 (2 lines) > 1248 (FAIL), 82 px (>80 warn). Move to the captionBox band, 72 px, emphasis by colour/weight not size
  (gotcha: 1.15x emphasis collides with neighbours).

---------------------------------------------------------------------------------------------------------------------
## 2. ears (audio critic) - `P/ears/`

Files: `listen.py` (CLI + `analyze`), `core.py` (decode, side inputs, STFT, onsets, tempo, short-term loudness, LRA,
TP envelope, mixer cue takes), `checks_level.py`, `checks_time.py`, `checks_shape.py`, `report.py`, `mood.py`,
`manifest.json`, `tests/` (39 tests). Size 416 KB. Deps: numpy, scipy, ffmpeg; imports `P/sfx/mpaudio/meter.py` (BS.1770-4)
via `sys.path.insert(PACK/sfx)` -> `mpaudio/__init__` imports `dsp` -> **numba is a hard import** (`@njit(cache=True)`:
set `NUMBA_CACHE_DIR` so it never touches `P/sfx/mpaudio/__pycache__`). Cue-anchor checks lazily import
`sfx/recipes` + `mpaudio.registry` and re-render the pack sound takes (only for pack ids). torch only if `EARS_CLAP_MODEL`
is a directory (then `transformers`+`torch` loaded, local only). `--mood gemini` = paid cloud call: never.

### CLI
```bash
PYTHONDONTWRITEBYTECODE=1 NUMBA_CACHE_DIR=/tmp/x EARS_CLAP_MODEL= python3 P/ears/listen.py <video.mp4|master.wav> \
   [--plan plan.json] [--transcript words.json|whisper.json|study.json] [--cuts cuts.json] [--ref study.json ...] \
   [--mode auto|music|vo|continuous] [--events events.json] [--role proof|explainer|hype|trailer|vo_doc|brand_launch] \
   [--loop] [--target-lufs -14] [--fps 30] [--mood off] [--json out/ears.json] [--md out/ears.md] [--quiet]
```
* Reel Director: `--mode vo` (or `plan.audio.mode: "vo"`), `--transcript words.json` (OUTPUT time), `--mood off`.
* `.wav/.flac/.aif` input is judged as a master (TP <= -1.5, digital-silent tail); MP4 as delivered (TP <= -1.0).
* fps: --fps, else plan.fps, else video, else 30.

### Library
`from ears.listen import analyze; analyze(x(n,2)@48k, fps, is_master, channels, plan, cuts=[s], transcript=[(s,e,nwords)],
refs=[(name, study)], loop, target_lufs, name, mode, quiet, events, words=[(s,e)], role)`; decode with `ears.core.decode(path)`,
transcript with `core.speech_from(json)` + `core.words_from(json)`. (CLI in a subprocess is simpler.)

### Report shape: same as eyes, but issue key `listener` (not `viewer`), plus `mode`, `channels`, `is_master`,
`mood {available, text, ...}`. scores: loudness, cleanliness, tone, speech, sync, structure, variety, stereo, compare(n/a),
`critic_sound_sync` = min(loudness, cleanliness, sync, structure).

### Checks (manifest spec)
| check | verdict |
|---|---|
| loudness | -14 +-0.5 LU pass, +-1.5 warn (else FAIL); TP <= -1.0 dBTP delivered / -1.5 master (+0.01 tol); LRA <= 10 LU; last 0.15 s digital zero (FAIL when not) |
| clipping | any flat-topped run >=3 samples or over FAIL; PLR <8 warn, <5 FAIL |
| tone | per-octave vs 500-2k: sub -24..12, low -10..10, mud -8..6, presence -16..2, sibilance -26..-3, air -38..-4 dB; flags with time ranges |
| speech | needs a transcript for verdicts: ducking >=9 dB (warn 6) measured <100 Hz against a >=~1 s music-only stretch next to the line; speech-to-music in 300-3.4k >=10 dB (warn 5); 110-175 wpm |
| sync | first audible event by frame 3 (or planned quiet open <=2 s); mode vo: no cut inside a word (needs word timings), cut-on-onset info only; plan cues at (F+1)*48000/fps within 0.5 frame (only pack sfx ids found by matched filter, else "not detectable") |
| structure | dead air >=2 s unplanned warn; planned quiet over max (open 2, dip/gap 4, hold 9 s) warn; flat (LRA<2 & no drop) warn; late drop warn; ending shape |
| repetition | same non-musical sound >3 times in 10 s warn |
| stereo | mono loss >1.5 dB warn, >3 FAIL; anti-phase warn |
| compare | only with --ref / --role; info |

Transcript formats accepted: talking-head `words.json` `{"words":[{"w","s","e"}]}` (lines split at gaps >0.3 s),
Whisper JSON (`segments[].words[{start,end}]`), refstudy `study.json`.
Plan fields ears reads: `fps`, `shots[].start` (cuts = every shot start > 0: so emit one shot PER KEPT CLIP so each jump cut
is checked against words), `cues[{id:'sfx/<cat>/<name>', t}]`, `audio{mode, quiet[{t,kind,why}], events, role}`
(top-level `audioMode/quiet/motionEvents/audioRole` also read). A list-valued `plan.audio` (multi-voice-doc) is ignored.

### VERIFIED runs
* talking-head demo, `--mode vo`, no transcript: loudness FAIL -19.46 LUFS (demo has no master pass; input audio + SFX
  stem only) and tail -19.7 dBFS FAIL; speech n/a. 2.1 s wall.
* reel-director `renders/demo-week2.mp4` + transcript built from `work/demo/final2/timeline.json` shot words + plan shots:
  loudness FAIL only because the last 0.15 s is not digital zero (-13.58 LUFS, -1.51 dBTP are fine); tone warn (mud +10.6,
  air -32: voice-only, dull top); sync warn: first audible frame 6 (mark `audio.quiet` open or put sound on frame 0);
  speech PASS (160 wpm, SMR 40.9). 1.4 s wall. Fix the tail: a 30-50 ms fade then >=0.15 s of zeros in the final mux
  (music/mixer.py master does this), or `ffmpeg -af "afade=t=out:st=<T-0.2>:d=0.05,apad"` + trim.

---------------------------------------------------------------------------------------------------------------------
## 3. Evidence pack + quick stills

### `P/tools/critic_pack.sh <video.mp4> <out_dir> [composition_dir]`
Writes sheet_2fps.jpg, motion_strip.jpg, phone/*.png (360 px wide at 0, 1, 2 s, 25/50/75%, end), loop2x.mp4 + seam.jpg,
refstudy/ (`tools/refstudy.py --whisper none`; numpy + matplotlib), ears/, eyes/, critic.json, review.md.
Env: `PYTHON`, `EARS_MODE`, `EYES_PLATFORM`, `EYES_FORMAT`, `EYES_DRAFT=1`, `HF`. It reads `<comp>/out/plan.json` and
`<comp>/words.json` ONLY when a composition dir is given, and then ALSO renders the composition twice as png-sequence
(determinism) - heavy on disk (avoid at ~9 GB free). For Reel Director, call eyes/ears directly with the plan, and copy
the ffmpeg one-liners for the sheet/phone frames:
```bash
ffmpeg -v error -i in.mp4 -vf "fps=2,scale=180:-2,tile=6x<rows>:padding=2:color=white" -frames:v 1 sheet_2fps.jpg
ffmpeg -v error -ss <t> -i in.mp4 -frames:v 1 -vf "scale=360:-2" phone_<t>.png
```
### `P/templates/_shared/sheet.py <mp4> <out.jpg> t1,t2,...` (needs Pillow + numpy + sfx/mpaudio meter)
Contact sheet decoded from the delivered MP4 (270 px tiles, 6 across for 9:16) + prints `LUFS-I x TP y dBTP dur z`.

### `hyperframes snapshot` (local CLI is 0.8.177; pack pins 0.8.142)
`hyperframes snapshot <projectDir> --at 1.2,3.4 --no-end --describe false -o <outDir>` (also `--frames N`, `--range a,b`,
`--zoom <selector|x,y,w,h>`, `--against ref.mp4`, `--no-browser-gpu` for deterministic SwiftShader). ALWAYS
`--describe false` (Gemini call when GEMINI_API_KEY is set) and ALWAYS `-o` (default writes into
`<project>/.hyperframes/artifacts/snapshots`). Good for per-shot stills before a full render.

---------------------------------------------------------------------------------------------------------------------
## 4. storyboard - `P/storyboard/`

`python3 P/storyboard/board.py shotlist.json [--design design.json] [--plan plan.json] [--music music/<bed>|--bpm N]
[--out dir] [--safe conservative] [--real auto|always|never] [--project <comp dir>] [--hero-frac 0.6] [--allow-lint]
[--no-animatic] [--no-pdf] [--cut-ticks]`. Library: `from storyboard.board import build; code, report = build(shotlist,
design, plan_path, out=..., make_animatic=False, real_mode='never', allow_lint=True)`. Exit 0 drawn / 1 refused by the
story-script linter / 2 unreadable.
* Input is a story-script `shotlist.json` (`skills/story-script/assets/shotlist.example.json`): `{title, format ('reel'
  allowed), fps, aspect '9:16', logline, stake, turn{at_s}, payoff, hooks[...], shots:[{id, beat, role, start_s, dur_s,
  scale (WS/MS/MCU/CU/ECU/CARD/SCREEN...), action, sound, text, text_kind (super|in_world|label|card), honesty, camera,
  transition{kind, reason}}]}`. Linter `skills/story-script/scripts/lint_shotlist.py` (stdlib only) runs first; `--allow-lint`
  waives (recorded).
* Outputs: storyboard.png/.html/.pdf, panels/<id>.png, report.json (per-panel reading speed <=3.5 w/s, text outside safe
  rect, label hold >=2 s), animatic.plan.json, animatic.mp4/.wav (music/mixer.py, -14 LUFS, burnt timecode).
* `--plan` + built composition: REAL key frames via `npx -y hyperframes@0.8.142 snapshot <proj> --at ... --no-end
  --describe false -o <out>/real`, expecting `frame-*.png` (override the command with `STORYBOARD_SNAPSHOT_CMD`; 0.8.177's
  file naming was not verified). project dir = `--project`, else the folder above `out/` holding index.html, else the plan's
  own folder.
* Deps: Pillow, numpy, soundfile, ffmpeg, node (reads type/safezones.js). VERIFIED sheet-only run: 3.5 s.
* Fit for Reel Director: a pre-record "script approved" sheet/animatic; Reel Director's compiler already renders
  `RECORD · <id>` slot cards for unrecorded shots, which is its own animatic. Optional, not part of the gate.

---------------------------------------------------------------------------------------------------------------------
## 5. templates - talking-head reel structure to copy

### `P/templates/talking-head/` (config.mjs, make.mjs, words.json, index.html, out/plan.json, out/talking-head.mp4)
`node make.mjs [--set input=/abs/talk.mp4 --set platform=reels.organic]` then `hyperframes render . -o out/x.mp4 --crf 23`.
Pipeline (`buildPlan(C)` in config.mjs, helpers in `_shared/plan.mjs`):
1. `autocut(words, {silenceMin:0.5, padBefore:0.06, padAfter:0.09})` -> keep ranges; segs quantised to frames
   (`q = round(x*fps)/fps`), output time accumulates.
2. framing ladder per jump cut `[1.0, 1.15, 1.0, 1.25]`, anchor `[0.5, 0.38]` (transform-origin + object-position 50% 38%:
   the eyes line) - `tl.set('#fr-i', {scale}, 0)` on an UNTIMED wrapper `.frame#fr-i` around each timed `<video>`.
3. punch-ins on `emph` words: `tl.fromTo('#fr-i', {scale:b}, {scale:b*1.12, duration:0.14, ease:'back.out(1.6)'}, t)`, at
   most one per `minGap` 4 s.
4. captions `chunkCaptions(words, {maxWords:3, maxChars:15, pause:0.25, lead:2/30, minHold:0.35})`; per chunk a
   `.clip.cap` div (track 3) with `<span id="w-k-j">` words; pop `fromTo(scale .85 -> 1.06 -> 1)` 70+70 ms; karaoke via
   `tl.set(word, {color: accent, scale: emph?1.15:1}, max(c.start, w.s))` then back to white at next word start.
5. B-roll `<video class="clip fill broll" muted data-track-index="1">` anchored to a word, starts 150 ms before it,
   never before 2.0 s, 35-50% coverage target.
6. lower third `<section class="clip lt">` + `MP.type(tl, 'type/wipe', '#lt-box', {at, dur, fps, out:true})`.
7. layers: `<div id="fx" class="clip" data-track-index="5">` + `mountStack(fx, [{kind:'vignette'},{kind:'grain',
   params:{stock:'digital-soft'}}], {width, height, fps, seed:11})` and `bindHF(stack, {fps})` (listens to `hf-seek`).
8. SFX: plan cues `sfx/tx/scale_punch -14 dB` (punch), `sfx/ui/pop -20` (emphasis), `sfx/whoosh/swish_s -14` (B-roll),
   `sfx/ui/slide -18` (lower third) mixed by `_shared/audio.py --stem` into ONE `<audio id="mix" src="assets/media/mix.wav"
   data-start="0" data-track-index="9">`; input audio rides on each `<video data-has-audio="true">`.
9. `window.__timelines['main'] = gsap.timeline({paused:true})`. plan: `{template:'talking-head', fps, seconds, size, safe,
   keep, segs, captions, punches, broll, shots(=segs), cues, claims:[], coverage, paceRule:{aslMax:4, longMax:6}, lint}`.
Known defects (eyes/ears VERIFIED on its own demo): 100 px captions (>80), right edge 994 > 960, stroke-only contrast
1.4-3.4:1, no master pass (-19.5 LUFS, tail not silent), one banded end frame. Copy the structure, fix those numbers.
SKILL recipe H extras: captions 64-80 px, <=2 lines, <=18 chars/line; bed ducked 9 dB (12 for VO-led) under the voice;
grade `documentary`; keep the face still 450 ms after a punchline, then cut.

### `P/templates/multi-voice-doc/` (audio model to copy)
Picture `<video ... muted>`; all speech is one `vo.wav`; `_shared/audio.py` hands bed + cues + vo to `music/mixer.py`:
cue sheet `{fps, length_s, bed{file, gain_db, loop:false, automation[{frame, gain_db}]}, cues[{id:'snd.<cat>.<name>',
frame, gain_db, over_vo_db?, over_bed_db?}], master{lufs:-14, ceiling_db}, quiet, vo{file, start_frame:0, duck_db}}`,
`python3 music/mixer.py sheet.json --out dir`. Plan knobs: `duckDb: 12`, `ceilingDb: -2.0`, `fadeInMs: 40`,
`bedAutomation` (end card: bed up 1.8 s then -30 dB). Speaker cuts land mid-breath, never inside a word (checked in
`lint_vo`); J-cut audio leads 130 ms; supers `lowerThird.docSuper` with `dur` minus the part's in/out edge frames.
Result: ears all pass (duck median 12 dB, speech 21 dB over music, 160 wpm).

### Other templates
Some local templates outside the public repo put VO + captions in render-tall/ (9:16)
with `build_captions.py` (whisper word timestamps -> `caption.speakerTag`) - eyes-v3..v5 reports in their `out/`. Their
README records the fixes that moved eyes: grain stock `upload-safe` + dithered final encode
`ffmpeg -vf noise=alls=4:allf=t+u -crf 18 -tune grain` (banding fail -> pass), motion from frame 1, slow camera pushes
through holds (no stalls), everything inside x 65-960 / y 269-1248 on 9:16. `proof-film` and `demo-r6-pivot` show
`plan.audio` with planned `open`/`gap`/`hold` quiet.

---------------------------------------------------------------------------------------------------------------------
## 6. Skill guidance and gotchas that bite a talking-head reel

From SKILL.md / critic.md:
* Production gate 6: eyes on the delivered MP4 shows no fail and no category <8 you cannot explain; ears no fail; one human
  look at a 360 px still and one listen on a phone. Scores are ceilings (never score above eyes/ears without fixing).
* Critic loop: fix the worst 3 locally, re-render into a new review folder, stop when every row >=8; if a score doesn't move
  in 2 rounds the problem is upstream (script/design).
* Hard rules: master -14 LUFS-I, WAV TP <= -1.5 (-2.0 if clicky), delivered MP4 <= -1.0 dBTP, last 0.15 s digital zero;
  never gain SFX by hand; hits on (F+1)*48000/fps; frame 0 in motion, first change by frame 6; flash <= 3/s.
* VO-led reels must be scored in `vo` mode (music-mode cut sync is meaningless for them).

From gotchas.md:
* HyperFrames hides a timed clip outside its window; never tween a timed `.clip`/`<video>` - animate an untimed wrapper
  (Reel Director's `#cam` wrapper is right).
* `z-index` on the overlay (`#fx`) container kills `mix-blend-mode` of grain/vignette - set z on the canvases.
* HyperFrames lowers the WHOLE track if its AAC re-encode goes over -1 dBTP (logged only with `--debug`; grep the render
  log for `lowered`); a hit in the first ~15 ms overshoots: `fadeInMs: 40`, ceiling -2.0 (-3.0 for bass-heavy beds).
* GSAP determinism: `gsap.config({force3D:false})` and one warm pass `tl.seek(tl.duration()).seek(0)` before registering
  the timeline (Reel Director's compiler does neither today).
* Default render CRF 16 (~18 Mb/s); `--crf 23` for reviews.
* Room-tone/ambience loops: always set gain and `until_frame`.
* Ducking is only measurable next to a >=~1 s music-only stretch; wall-to-wall VO -> "not measurable". For VO films
  `duckDb: 12` and a bed with steady low end.
* Placeholder/guide speech must be ~160 wpm or ears calls it rushed.
* Mark intended quiet (`plan.audio.quiet`) and intended still holds (`plan.holds`/`shots[].hold`) or they are faults.
* Emphasis scale 1.15x collides with neighbours on long words.
* ffmpeg here has no libass and no drawtext: burn captions in the DOM/canvas.
* Banding is a dark-midtone problem (luma 25-110): soft blurs/vignettes/dark gradients need grain (`upload-safe`, >=0.02)
  or dither; tag renders bt709.
* `hyperframes snapshot --describe` is a cloud call by default when GEMINI_API_KEY is set.
* eyes needs the plan; a 9:16 plan with a 16:9 render fails composition on purpose (pass `--platform`).

---------------------------------------------------------------------------------------------------------------------
## 7. Proposed Reel Director quality gate (concrete)

1. Compiler writes, next to index.html: `plan.json` (schema in section 1, `template:'talking-head'`,
   `platform:'reels.organic'`, `size:[1080,1920]`, `fps`, `seconds`, `shots` = one per kept clip/cutaway with `hold:true` for
   static cards, `texts` = every caption chunk (tight box, fontPx, role caption, fg TEXT colour) + overlays (role headline)
   + cutaways (role read/headline), `holds`, `paceRule:{aslMax:4,longMax:6}`, `audio:{mode:'vo', role:'explainer',
   quiet:[...]}`) and `words.json` `{"words":[{"w","s","e"}]}` in output time.
2. After render (subprocess, isolated python, env above):
   `python3 P/eyes/look.py out.mp4 --plan plan.json --json eyes.json --md eyes.md --quiet`
   `python3 P/ears/listen.py out.mp4 --plan plan.json --transcript words.json --mode vo --mood off --json ears.json --md ears.md --quiet`
3. Gate = PASS when no check has `status == 'fail'` and `eyes.scores.critic_* >= 8`, `ears.scores.critic_sound_sync >= 8`,
   `ears.scores.speech >= 8`; surface `top_issues[].viewer/listener + fix + t` in the Studio UI. Warn-only allowances:
   readability caption-timing warns (word-synced captions), `eyes/composition` hero proxy, `ears/tone` notes.
4. Typical fixes to bake into the compiler: caption band y 1054-1224 at 72 px with a 40-60% dark pill; grain layer
   (`upload-safe`) over everything (kills banding + "frozen" cards); slow push on cutaway cards or `hold:true`; frame 0 in
   motion with a readable subject; one mastered mix.wav (VO + music ducked 12 dB + SFX) with 40 ms fade-in, -2.0 dB
   ceiling, 0.15 s digital-zero tail; colour-tagged H.264 yuv420p faststart, GOP <=2 s.
