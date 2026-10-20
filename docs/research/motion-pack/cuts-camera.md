# motion-pack: cuts + camera, mapped for Reel Director (#cam wrapper)

Read-only map, 2026-10-20. Sources: motion-pack `{cuts,camera}` (README, manifest, code),
`templates/talking-head`, `layers/demo/hf`, `templates/proof-film/tall`, skill `skills/motion-pack/SKILL.md` +
`references/{apis,gotchas,virality,critic}.md`, Reel Director `src/reel_director/compiler.py`. Probe scripts and a
HyperFrames test composition were in a scratch folder (`scratch-cuts-camera/`, not kept; nothing in either repo was touched).

---------------------------------------------------------------------------------------------------------------------------

## 0. TL;DR for Reel Director

* The camera module is pure JS (ES modules, no deps): `camera/cam2d.js` (+ its import `camera/ease.js`) and `camera/bake.js`.
  Every move is `preset(base, params) -> (t) => state`, a pure function of COMPOSITION seconds. Nest modifiers.
* Drive `#cam` with **`bakeGSAP(tl, '#cam', cam, { t0: 0, dur, fps, W: 1080, H: 1920, cover: true })`**: one `tl.set` per frame
  on the existing paused `window.__timelines.main` (1801 sets for a 60 s reel at 30 fps). Seek-safe, random access tested.
* Build the camera per KEPT SEGMENT with `sequence2d` (hard reset at each jump cut), reframe ladder on the eyes, punch-in on the
  claim/emphasis word, slow push on long static segments, then wrap the whole thing in `handheld2d(level 'subtle')`.
* `cuts/cutgen.py talking` gives the same plan as data (ladder scale, punch frame, slow push, cut-tick SFX) if you want Python
  to decide and JS only to draw. `cutgen.py lint-interrupts` lints the cadence of the final cue list. Retime = `cuts/retime.py`
  (ffmpeg) or, on HyperFrames 0.8.177, a `data-playback-rate` / `data-automation` rate lane on the `<video>`.
* VERIFIED in this session on hyperframes 0.8.177: a composition shaped like Reel Director's output (`#cam` > two
  `<video class="clip take">` jump-cut segments, caption outside `#cam`) with a `type="module"` script that imports the staged
  `assets/mp/camera/*.js` and bakes the camera: `hyperframes lint` 0 errors, `hyperframes snapshot --at 0.5,1.2,2.6` shows base
  framing, the punch-in, and the 1.15 reframe after the jump cut, caption unaffected.

---------------------------------------------------------------------------------------------------------------------------

## 1. Files to stage into a Reel Director project

| file | size | why |
|---|---|---|
| `camera/cam2d.js` | 19 KB | all 2D moves + `toGSAP` / `toCSS` / `coverScale` / lints |
| `camera/ease.js`  | 5.5 KB | imported by cam2d.js as `./ease.js` (house eases `E`, `env`, `sines`, `springTrack`). Must sit next to cam2d.js |
| `camera/bake.js`  | 2.6 KB | `bakeGSAP`, `driveSeek`; imports `./cam2d.js` |

Copy to `<project>/assets/mp/camera/` (the pack's own templates use `assets/mp/<module>/`). MIT licence (`LICENSE`).
They are ES modules: the page script that imports them must be `<script type="module">` (Reel Director's `_PAGE` currently
uses a classic `<script>`; a classic script cannot `import`). GSAP stays the global from the CDN `<script>`.
Do NOT copy `cam3d.js` (three.js camera) unless a three.js layer is added.

Alternative without modules: run node at compile time to evaluate the camera and embed the per-frame `toGSAP` values as a JSON
array, then a classic loop does `tl.set('#cam', v, i/fps)` (frame 0 as `tl.fromTo(..., {duration: 1/fps/2, immediateRender:true}, 0)`,
see gotcha G6). Same numbers, more moving parts; the module route is simpler.

---------------------------------------------------------------------------------------------------------------------------

## 2. camera/cam2d.js: exact API

State (all moves read/write it): `{ x, y, scale, rot, blur, blurAngle, origin:[ox, oy] }`
* `x, y` in units of **frame HEIGHT** (resolution independent; px = x * H). `rot` degrees (+ = clockwise). `scale` multiplies.
* `origin` = transform-origin as fractions of W,H (default `[0.5, 0.5]`). Punches re-centre on a face box / the eyes.
* `blur` = motion-streak length in px at 1080p (only whips/crash zooms set it). Extra keys: `dof` (rackFocus2D), `dive`
  (scaleDive), `pin` (pullbackToScreen).

Constants/helpers: `ID2` (frozen identity state), `asFn2(b)` (state or fn -> fn), `c2(partialState)` (copy + defaults).
`ease` names (ease.js `E`): `enter hero exit move soft cam pop lin sine expoOut quint` (ANVE kit beziers). Any param `ease:` takes a
name or a function.

### Moves (all `(base, opts) => (t) => state`; times are composition seconds)

| fn | defaults | what / when for a talking head |
|---|---|---|
| `push2d(base, {at=0, dur=1.2, to=1.12, ease='hero', origin})` | x1.12 in 1.2 s | push-in. Slow push for long shots: `{at: segStart, dur: segDur, to: 1.06, ease: 'lin', origin: EYES}` (patterns `slow_push` 1.0->1.06 linear when shot > 4 s). HOLDS `to` after the window |
| `pull2d(base, {at=0, dur=1.6, from=1.15, ease='move'})` | 1.15 -> 1 | pull-out / zoom-out reveal (L2 interrupt) |
| `pan2d(base, {at=0, dur=2, dx=0.1, dy=0, ease='cam'})` | dx in frame heights | reframe drift |
| `whip2d(base, {at=0, dur=7/30, dx=1.2, mode='out'|'in', rollDeg=1.5, fps=30})` + `whipMid2(at, dur)` | 7-frame quint sweep, sets `blur` | transition move; ALONE IT EXPOSES BLACK (needs the next shot under it / the transitions module). Cut at `whipMid2` |
| `handheld2d(base, {level='doc', seed=1, rollOn=true})` | levels `subtle` 0.4 / `doc` 1 / `action` 2.5 (or a number) | closed-form seeded sines 0.37/0.83/1.31 Hz (+-5 px x level) + 7.1/9.3 Hz micro (0.8 px), roll +-0.25 deg x level, scale x(1 + 0.014 x level). Same seed = same shake. Use `subtle` on a talking head |
| `punchCadence(base, {boundaries=[], scales=[1,1.08,1,1.15], origins=null, durFrames=6, snap=false, fps=30})` | 6-frame expoOut step at each boundary | retention reframes at sentence boundaries / jump cuts. `snap:true` = instant jump. Scale cycles; `origins` cycles too. NOTE default ladder differs from patterns.json (see G9) |
| `punchIn2d(base, {at=0, to=1.12, durFrames=6, returnAt=null, origin=null, fps=30})` | 6-frame expoOut | single punch on a claim word. `returnAt` is an INSTANT snap back (k=0), not an ease |
| `beatPunch2d(base, {hits=[], amount=0.035, attack=1/30, decay=8/30})` | env: 1 f up, 8 f down | music-hit pulses; RECIPE B uses amount 0.08. `hits` = seconds (from a bed sidecar or `cutgen beats`) |
| `kenBurns(base, {at=0, dur=4, from=1, to=1.08, drift=[0.02,-0.01], ease='sine'})` | | stills / B-roll cards |
| `dutch2d(base, {at=0, dur=20/30, deg=6})` | | tilt (no cover fix; use `toGSAP(...,{cover:true})`) |
| `breathe2d(base, {amp=0.012, period=4})` | | idle breathing zoom on a held frame |
| `shake2d(base, {hits=[], px=10, rotDeg=0.6, decay=4/30, seed=1})` | decays over ~4 frames | impact shake on a hit/smash (px are 1080p-height units: 18 px at H=1920) |
| `lock2d(base, [[a,b], ...])` | | freeze the WHOLE camera (incl. handheld if it is inside) over windows: use for the 450 ms beat hold after a punchline and under key on-screen text. Put it OUTSIDE handheld2d to freeze the shake too |
| `sequence2d([[t0, camA], [t1, camB], ...])` | | hard switch between cameras at t_i (each cam still gets absolute t). The tool for per-jump-cut framing |
| `crashZoom(base, {at=0, to=1.6, frames=4, overshoot=0.06, shakePx=6, returnAt=null, origin=null, fps=30, seed=3})` | 4 f expo slam, overshoot, shake, blur; returnAt eases back in 6 f | comedy / shock beat. Counts as a punch-in (max 1 per 4 s) |
| `doubleTake(base, {at=0, beats=[0,0.35,0.7], to=[1.12,1.0,1.3], frames=5, origin=null, fps=30})` | | comedy "wait, what?" |
| `dollySnap(base, {at=0, snapAt=2, creepTo=1.06, snapTo=1.22, frames=6, origin=null, fps=30})` | | creep then snap on the reveal word/beat |
| `rackFocus2D(base, {at=0, dur=0.8, from='fg', maxBlur=10, breathing=0.015})` | writes `state.dof={fg,bg}` px | layered shots only (apply CSS blur to fg/bg layers yourself) |
| `dutchRoll(base, {at=0, dur=14/30, deg=6, sway=0, period=3.5, preset=null, aspect=16/9})`, `DUTCH_PRESETS` unease 6 / comedy 12 / thriller 9+sway 1.2 / drunk 4+sway 4 | pop ease, exact cover scale built in (12 deg on 9:16 = x1.348) | comedy/unease tilt |
| `parallaxStack(cam, depths, {W=1920, H=1080})` | | one camera -> per-layer CSS for a 2.5D stack (depth 0 locked, 1 = camera) |
| `scaleDive(...)`, `scaleDiveCSS(state, nLevels, {W,H})`, `pullbackToScreen(...)`, `mapPoint2(state, point, aspect)` | | powers-of-ten dive / end on a screen-in-a-room: motion-graphics cutaways, not the talking-head layer |

`PRESETS_2D` exports the move map by name (handy for a data-driven compiler: `PRESETS_2D[name](base, params)`).

### Output helpers
* `toGSAP(state, {W=1920, H=1080, cover=false})` -> `{x, y, scale, rotation, transformOrigin}` (px, deg). **Pass W:1080, H:1920.**
* `toCSS(state, {W, H, cover})` -> `{transform, transformOrigin, filter}` (filter = isotropic blur fallback when blur > 0.5).
* `coverScale(rotDeg, tx, ty, W, H)` exact minimum scale that hides edges ASSUMING the origin is the frame centre (see G2).
* `blurFilterSVG(id='mp-streak')` markup + `blurStd(state, H)` -> stdDeviation "bx by" for the streak filter node.
* `lintPunchCadence(cam, duration, {fps=30, minGapSec=4, minStep=0.03, windowFrames=8})` -> `{onsets, violations}`.

### camera/bake.js
```js
bakeGSAP(tl, target, cam, { t0 = 0, dur, fps = 30, W = 1920, H = 1080, cover = false, blurNode = null })
//  frames i = 0..round(dur*fps): v = toGSAP(cam(t0 + i/fps)); i==0 -> tl.fromTo(target, v, {...v, duration: 1/fps/2, ease:'none', immediateRender:true}, t0)
//  (a set() exactly at the timeline origin reverts on a backward seek); else tl.set(target, v, t0 + i/fps). Holds the t0 picture before t0, the last sample after.
driveSeek(target, cam, { t0 = 0, dur = Infinity, W, H, cover, blurNode })
//  listens to window 'hf-seek' (e.detail.time), applies toCSS transform + origin directly (no filter), initial frame from window.__hfThreeTime || 0.
```
Both call the same pure function; tested identical at t0 = 0, 0.4, 2, 3.5, 7.25 (`camera/tests/camera.test.mjs`) and the DOM
matrix after 40 random-access GSAP seeks matches the pure function to 5e-5 (`tests/last-run2d.json`).
Prefer `bakeGSAP` in Reel Director: the GSAP timeline stays the single source of truth, Studio scrubbing works, nothing depends on
the three adapter's `hf-seek` event. `driveSeek` is what `templates/proof-film/tall` uses (manual `hf-seek` listener with
`toCSS(..., {W:1080, H:1920})`), so it also works, but then nothing else may write `#cam` from the timeline.

### ease.js extras worth knowing
`env(t, hits, {attack, decay, curve})` beat envelope; `sines(seed, freqs, amps)` closed-form noise; `mulberry32(seed)`;
`springTrack(t, [[t0,v0],[t1,v1],...], cls)` seekable springs, classes `ui panel camera headline mascot` (`camera` = critically
damped glide, never overshoots) - a nice alternative ease for a "settle" reframe. Identical copies live in `layers/` and `type/`.

---------------------------------------------------------------------------------------------------------------------------

## 3. Wiring into Reel Director's composition (tested shape)

Reel Director today: `#root > #cam > <video class="clip take" data-start data-duration data-media-start>` per kept segment,
captions/overlays/cutaways/sfx/music OUTSIDE `#cam`, one paused `tl` at `window.__timelines["main"]`, and the `zoom` cue does
`tl.fromTo("#cam", {scale:1}, {scale, duration: 0.25, ease:"power2.out"})` + a 0.25 s return. `#cam` is an untimed wrapper,
which is exactly what the pack requires ("never tween a timed .clip or <video>; animate an untimed wrapper").

Compiler-side data (Python) -> one JSON blob -> one module script:

```html
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
...
<script type="module">
  import * as C from './assets/mp/camera/cam2d.js';
  import { bakeGSAP } from './assets/mp/camera/bake.js';
  const CAM = /* compiler JSON */ { fps: 30, W: 1080, H: 1920, dur: 31.4, eyes: [0.5, 0.38], floor: 1.02,
    ladder: [1.0, 1.15, 1.0, 1.25], handheld: 'subtle', seed: 7,
    segments: [ { start: 0, dur: 2.5, punch: 1.0 }, { start: 2.5, dur: 4.6, punch: null }, ... ],   // one per kept clip (out_start, duration)
    locks: [[12.40, 12.85]],          // beat holds after punchlines (450 ms)
    hits: [], impacts: [] };          // optional: music hits for beatPunch2d, smash cuts for shake2d
  const E = CAM.eyes;
  const seg = CAM.segments.map((s, i) => {
    let f = C.c2({ scale: Math.max(CAM.floor, CAM.ladder[i % CAM.ladder.length]), origin: E });   // reframe ladder on the eyes
    if (s.punch != null) f = C.punchIn2d(f, { at: s.punch, to: 1.12, durFrames: 4, origin: E, fps: CAM.fps });   // holds to the next cut
    else if (s.dur > 4) f = C.push2d(f, { at: s.start, dur: s.dur, to: 1.06, ease: 'lin', origin: E });          // slow push on long shots
    return [s.start, f];
  });
  let cam = C.sequence2d(seg);
  if (CAM.hits.length) cam = C.beatPunch2d(cam, { hits: CAM.hits, amount: 0.035 });
  if (CAM.impacts.length) cam = C.shake2d(cam, { hits: CAM.impacts, px: 8 });
  cam = C.handheld2d(cam, { level: CAM.handheld, seed: CAM.seed });
  if (CAM.locks.length) cam = C.lock2d(cam, CAM.locks);          // outside handheld: freezes the shake too
  window.__timelines = window.__timelines || {};
  const tl = gsap.timeline({ paused: true });
  /* ... the compiler's caption / overlay tweens ... (NOT the old #cam zoom fromTo: see G4) */
  bakeGSAP(tl, '#cam', cam, { t0: 0, dur: CAM.dur, fps: CAM.fps, W: CAM.W, H: CAM.H, cover: true });
  window.__timelines['main'] = tl;
</script>
```
The test copy of this (2 segments, punch at 1.0 s, cut at 2.5 s) is
`scratch-cuts-camera/comp/index.html` (scratch, not kept); lint 0 errors (1 warning about the caption div structure that
Reel Director's own captions also trigger), snapshots in `../snaps/` (`sheet.png` = 0.5 s / 1.2 s / 2.6 s).

Cue mapping (Reel Director cue -> camera part):
| Reel Director | camera part | numbers (pack) |
|---|---|---|
| each kept clip (jump cut) | `sequence2d` segment with ladder scale on the eyes | `talking_head.reframe_alternate` 1.0 / 1.15 / 1.0 / 1.25, anchor [0.5, 0.38] |
| `zoom` cue / `emphasis` claim | `punchIn2d` at the word start (or `crashZoom` for a comedic slam) | 1.12, 140 ms (4 f) in, hold to next cut, max 1 per 4 s; crash zooms count as punch-ins |
| zoom with explicit `hold` + return | `crashZoom(..., {to, returnAt})` (6 f eased return) or nest `push2d` up + `pull2d` back | punchIn2d's returnAt is an instant snap |
| static segment > 4 s with no punch | `push2d` linear 1.0 -> 1.06 over the segment | `slow_push` |
| punchline | `lock2d` window of 0.45 s after the punchline word end, then cut | `beat_hold.hold_ms` 450 (400-600) |
| music beat accents | `beatPunch2d` hits from the bed sidecar / `cutgen beats --snap` | amount 0.035 (0.08 for beat edits) |
| smash / impact | `shake2d` hits = smash frame / fps | px 10 at 1080p height, 4 f decay |
| whole reel | `handheld2d` level `subtle`, fixed seed | doc = 1, action = 2.5 |

---------------------------------------------------------------------------------------------------------------------------

## 4. cuts/: cut rhythm + punch-in plan as data (stdlib Python, deterministic, JSON on stdout)

Run as `python3 -B cuts/cutgen.py <sub> ...` (or `import cutgen` after `sys.path.insert(0, cuts_dir)`; it imports `story45` and
`story6` from the same folder at import time, and reads `patterns.json` + `../transitions/catalog.json` for `--tx`).
Frame rule everywhere: `frame_of(t) = floor(t*fps + 0.5)`; SFX cue `anchor_frame = visual_frame + 1` (the pack's hit contract).

### patterns.json blocks relevant to talking heads (house heuristics, tunable)
* `talking_head.autocut`: silence_min 500 ms, breath_keep 120 ms, pad_before 60 ms, pad_after 90 ms, crossfade 6 ms, fillers
  um/uh/like/you know (analysis belongs to the talking-head-recut / video-use skills; Reel Director's own cleanup already does this).
* `talking_head.reframe_alternate`: scales [1.0, 1.15, 1.0, 1.25], anchor [0.5, 0.38] ("every jump cut changes framing, anchored on the eyes").
* `talking_head.punch_in`: scale_to 1.12, in_ms 140, ease outCubic, min_gap_s 4.0, hold_until next_cut, sfx `sfx/hit/punch`.
* `talking_head.slow_push`: 1.0 -> 1.06 linear when the shot is longer than 4 s.
* `talking_head.beat_hold`: 450 ms; `talking_head.cut_tick`: `sfx/ui/tick` at -18 dB (optional, "so cuts are not sterile").
* `split.broll_lead`: picture leads the VO by 150 ms; `split.J` audio leads 400 ms (200-800), `L` trails 600 ms (200-1200), xfade 80 ms.
* `smash`: 200 ms pre-silence, 4 ms ramp, impact at cut + 1 frame, `sfx/hit/sub_drop` (alt `boom_meme`), lint 12 dB / 0.4 luma jump.
* `interrupts`: L1 every 2.5 s (punch-in, caption emphasis, new angle, scalePunch), L2 every 5 s (B-roll, text card, whip,
  zoom-out reveal, colour field), L3 every 9 s >= 6 s apart (smash, glitch, flash + music drop, format switch); 25% jitter;
  lint: two L3 within 1.5 s, or 4 consecutive 5 s windows of rising summed level (fatigue).
* `pace.talking_head`: ASL 2.5-5.0 s, 6-12 shots per 30 s. `onset_snap`: +-2 frames, 60% target (music-led ONLY; a talking
  head is `vo` mode: cuts under the voice, never inside a word, see critic.md).

### cutgen subcommands that matter here (all verified this session)
```
python3 -B cuts/cutgen.py talking --cuts 0,72,150,260,400 --fps 30 --end-frame 520 --claims 80,160,300
```
-> `{fps, segments:[{i, start, end, scale, anchor:[0.5,0.38], sfx:[{sfx:'sfx/ui/tick', anchor_frame: start+1, gain_db:-18}, ...],
    punch_in?:{frame, scale_to: scale*1.12, in_frames: 4, ease:'outCubic'}, punch_in_skipped?: msg, slow_push?:{from, to: scale*1.06, ease:'linear'}}]}`.
Library: `cutgen.talking(cut_frames, fps, end_frame=None, claims=())`. Rules: ladder by segment index; only the FIRST claim inside
a segment is considered; a claim < 4 s after the last punch is skipped (message); slow push only when the segment is > 4 s AND has
no punch; punch SFX `sfx/hit/punch` +3 dB at claim + 1; `end_frame` defaults to last cut + 3 s. Feed it Reel Director's clip
starts in output frames and the emphasis/zoom word start frames as claims; then emit the JSON segments into the camera blob above.

```
python3 -B cuts/cutgen.py split --mode broll_lead --cut-frame 120 --fps 30   # -> picture_cut_frame 116 (VO frame 120): B-roll leads 150 ms
python3 -B cuts/cutgen.py split --mode J --cut-frame 120 --fps 30            # audio_cut_s 3.6, crossfade samples, ambience bridge 1500 ms
python3 -B cuts/cutgen.py smash --cut-frame 120 --fps 30                     # silence_start_s 3.8, impact anchor_frame 121 + sample
python3 -B cuts/cutgen.py interrupts --duration 30 --fps 30 --seed 4         # seeded ladder + its own lint (never fails)
python3 -B cuts/cutgen.py lint-interrupts schedule.json [--duration S]       # exit 1 on major_pair or fatigue; schedule = [{level, time_s}]
python3 -B cuts/cutgen.py anaphora --words words.json --phrase "no more"     # cut at token start - 1 f on each repeat + type/accentSwap slot + swish_xs SFX
python3 -B cuts/cutgen.py command-burst --words words.json                   # a response cut on floor(word_end*fps)+1 after each command
python3 -B cuts/cutgen.py beats --bpm 120 --fps 30 --pattern every_bar --bars 8 [--snap] [--tx whip]   # music-hit times for beatPunch2d
```
Library: `cutgen.lint_interrupts(events, duration)`, `cutgen.snap_cuts_to_onsets(cut_frames, onsets_s, fps, tol_frames=None)`,
`cutgen.beat_cuts(bpm, fps, pattern, bars, offset, snap, tx)`, `cutgen.split(mode, cut_frame, fps, ms, sr)`, `cutgen.smash(cut_frame, fps)`.
Use for Reel Director: the `interrupts` GENERATOR is random (seeded), not word-aware, so don't place cues from it; instead convert
the compiled cue list to `[{level, time_s}]` (punch/emphasis = 1, cutaway/overlay/B-roll = 2, smash/format switch = 3) and run
`lint_interrupts` + the static-limit check (something changes at least every 3.5 s, virality R4).

### Retime (speed ramps, freeze, rewind)
`cuts/retime.json` presets (anchor-relative keys `[t, rate]`, rate = source s per output s, 0 = freeze) + SFX bundle:
`rampIn`, `rampOut`, `heroRamp` (fast-slow-fast), `bulletTime`, `reverseFlash` (0.4 s backwards at 2x then forward),
`freezeStamp` (freeze 0.8 s + `sfx/tx/freeze_hit` + record scratch; pair with `layout.freezeFrame` name card).
```
python3 -B cuts/retime.py plan   --preset freezeStamp --anchor 2.0 --dur 4 [--fps 30] [--step 2]   # segments, out_frames, sfx [{id, frame, gain_db}]
python3 -B cuts/retime.py ffmpeg --preset heroRamp --anchor 2.0 --dur 6 --input in.mp4 --out out.mp4 [--no-audio] [--run]
```
Exact integration of the piecewise-linear rate in 2-frame pieces (source never drifts); audio = atempo chain, SILENCE under
freeze/reverse (lay the preset SFX). Output length != input length: every later word anchor must be re-timed. For a talking head
only the gag presets make sense (freezeStamp on a reaction, reverseFlash rewind gag); never ramp speech.
HyperFrames 0.8.177 (installed CLI) also has constant `data-playback-rate` (0.1-10, pitch-preserved) and a `rate` lane in
`data-automation` on the `<video>` (`{"version":1,"lanes":[{"target":"rate","points":[{"t":0,"v":1},...]}]}`, `t` clip-local) -
i.e. ramps without ffmpeg, but rate 0 (freeze) is outside 0.1..10, so freezeStamp still needs ffmpeg or a still. A constant
1.05-1.15x on a slow take is a legitimate pacing tool (word anchors scale by 1/rate). The pack itself was measured on 0.8.142.
JS twin: `transitions/lib/tx-core.js speedRamp(keys, {anchor, easeName='inOutCubic'})` + `RAMP_PRESETS` (eased between keys,
so it is not bit-identical to retime.py's linear integration).

---------------------------------------------------------------------------------------------------------------------------

## 5. Skill guidance that applies (motion-pack SKILL.md / references)

* RECIPE H (talking head): fixed layer order: autocut (> 0.5 s, keep 120 ms breath) -> captions 2-4 words, active word, 64-80 px
  on 9:16, <= 2 lines -> B-roll 35-50% coverage, 1.2-3 s, leading the line by 150 ms -> **punch-ins 1.12 on emphasis, max 1 per
  4 s; on every jump cut alternate the framing anchored on the eyes** -> lower third -> bed ducked 9 dB -> SFX on emphasis,
  punch-ins, B-roll, lower third -> grade `documentary`. Beat hold: keep the face still 450 ms after a punchline, then cut.
* "Camera comedy / drama: crashZoom, doubleTake, dollySnap, dutchRoll, rackFocus2D, parallaxStack - crash zooms count as punch-ins".
* virality.md: at most 1 camera or layout move in the first 1.0 s; frame 0 already in motion (first visible change by frame 6);
  interrupt ladder L1/L2/L3 with jitter; "when every sentence brings a zoom, flash, meme and whoosh, the interruptions become the pattern".
* critic.md: a talking head is `plan.audio.mode: "vo"`: cuts under the voice, none inside a word; the 60% cut-on-onset target is
  NOT for VO films (tier-A VO films sat at 40-59%).
* Beat edit (RECIPE B): `cam2d.beatPunch2d` at 1.08 on the grid.

---------------------------------------------------------------------------------------------------------------------------

## 6. Gotchas (pack-documented + found by probing this session)

G1. **Defaults are 16:9.** `toGSAP/toCSS/bakeGSAP/parallaxStack` default to `W=1920, H=1080`; `dutchRoll/mapPoint2/pullbackToScreen`
    default `aspect=16/9`. Pass `W:1080, H:1920` (and `aspect: 9/16` where it exists). x/y are frame-HEIGHT units, so handheld
    and shake px scale by 1920/1080 = 1.78 on a vertical frame (handheld `doc` peaks at 16 px on 9:16, measured).
G2. **handheld2d's built-in edge hiding (+1.4% x level) is NOT enough on 9:16.** Measured over 60 s: without `cover`, ~53% of
    frames show 4 px (subtle) / 9-10 px (doc) of black edge. `cover:true` fixes it only when the origin is the centre; with the
    eyes origin [0.5, 0.38] ~31% of frames still expose up to 1.6 px (subtle) / 4 px (doc) because `coverScale` assumes a centre
    origin. Fix (measured 0 exposed frames): a scale floor of 1.01 (subtle) / 1.02 (doc) on every segment, or two wrappers
    (outer `#cam` = handheld about the centre with cover:true, inner frame div = ladder/punch about the eyes with scale >= 1).
G3. **Modifiers hold their end state forever.** `push2d` stays at `to`, `punchIn2d` stays punched (unless `returnAt`), after their
    window. Build one camera per kept segment and switch with `sequence2d` so every jump cut resets the framing.
G4. **One writer per element.** `bakeGSAP` writes x/y/scale/rotation/transformOrigin on `#cam` every frame. Reel Director's
    existing zoom cue (`tl.fromTo("#cam", {scale}...)`) would fight it; fold zoom cues into the camera function (or move them
    to an inner wrapper). Same for anything else that tweens `#cam`.
G5. `punchIn2d`'s `returnAt` is an instant snap back (fine at a cut, jarring mid-shot); `crashZoom` returns over 6 frames.
G6. **A GSAP `set()` exactly at the timeline origin reverts on a backward seek to 0** (bake.js comment); bake uses
    `fromTo(... immediateRender:true)` for frame 0. The pack's own `templates/talking-head` writes `tl.set('#fr-i', {scale}, 0)`,
    which has this risk; copy the bake's pattern, not the template's.
G7. `fps` passed to bakeGSAP must equal the composition fps (`data-fps`), or the camera steps at the wrong rate.
G8. **Stage the three files together** (`cam2d.js` imports `./ease.js`, `bake.js` imports `./cam2d.js`) and load them from a
    `type="module"` script; init `window.__timelines = window.__timelines || {}` in the module (HyperFrames' own docs do).
G9. **Number drift inside the pack - pick one and own it:** reframe ladder 1.0/1.15/1.0/1.25 (patterns.json, cutgen, template)
    vs `punchCadence` default 1.00/1.08/1.00/1.15; punch-in 140 ms outCubic (patterns; cutgen `in_frames` 4) vs `punchIn2d`
    6 f expoOut vs template `back.out(1.6)` 140 ms vs Reel Director's 0.25 s power2.out.
G10. **Compounding zoom:** ladder 1.25 x punch 1.12 = 1.40 (cutgen output `scale_to: 1.4`). On a 1080-wide phone source that is a
    visible upscale; cap the product (e.g. <= 1.3) or record 4K.
G11. `lintPunchCadence` counts the snap reframes at jump cuts as punch-ins (it flags any scale rise >= 0.03), so lint the
    punch-only camera (no ladder) against the 4 s rule, or ignore violations within a frame of a cut.
G12. `whip2d` alone exposes black - needs the next shot underneath (a transitions-module window), and the streak needs the
    SVG `blurNode` (`blurFilterSVG` + `blurStd`); `driveSeek`/`bakeGSAP` never set a CSS `filter`.
G13. **SFX placement:** ids are `sfx/<cat>/<name>` -> manifest `snd.<cat>.<name>` -> file `sfx/library/<family>/snd.<cat>.<name>.wav`
    (hit -> impact/, tx -> transition/). Each sound has an `anchor_ms` (e.g. tx.scale_punch 73 ms, whoosh.swish_s 134 ms,
    hit.punch 7 ms) and the rule "anchor sample lands on (visual frame + 1)". For a per-cue `<audio>` (Reel Director style):
    `data-start = (F_visual + 1)/fps - anchor_ms/1000`. The pack's own HyperFrames path is a single baked `mix.wav` (gotchas: mode A only).
G14. `cutgen talking`: one claim per segment, slow push suppressed on punched segments, default `end_frame` = last cut + 3 s.
G15. The interrupt generator is seeded random, not word-aware: lint with it, don't place with it.
G16. retime output changes the clip length, silences audio under freeze/reverse, and the ffmpeg command carries no codec
    flags (defaults); re-anchor words after it.
G17. Don't run the pack tests in place: `camera/tests/*.mjs` write `last-run*.json` into the repo; `cutgen` writes `__pycache__`
    unless run with `python3 -B`. The pure probes in this session imported the modules read-only.
G18. Minor: `camera/manifest.json` demo paths say `.png`; the files in `camera/demo/out/` are `.jpg`.
G19. The pack's HyperFrames gotchas were measured on 0.8.142; the installed CLI is 0.8.177 (this session's lint + snapshot ran
    on 0.8.177 without issue).

---------------------------------------------------------------------------------------------------------------------------

## 7. Evidence from this session (scratch only)

* `scratch-cuts-camera/probe.mjs`: vertical camera values at key times (ladder + punch + subtle handheld): 1.0056 -> 1.1564 on
  the cut at 2.4 s (snap), punch reaches x1.12 in 4 frames, back to 1.0056 at the next cut; handheld doc peak 16.2 px / 0.43 deg
  at H=1920; eased 6-frame cadence step reaches 1.0548 of 1.08 one frame in; crashZoom 1.0 -> 1.247 one frame in, overshoot,
  6-frame return; shake2d decays in ~4 frames.
* `scratch-cuts-camera/cover.mjs`, `cover2.mjs`: the edge-exposure measurements in G2.
* `scratch-cuts-camera/talking.json`, `interrupts.json`, `words.json`: cutgen outputs quoted above.
* `scratch-cuts-camera/comp/` + `snaps/sheet.png`: HyperFrames 0.8.177 lint + snapshot of the Reel-Director-shaped composition.
