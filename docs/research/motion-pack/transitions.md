# motion-pack: transitions module, mapped for Reel Director

Pack: motion-pack `transitions/` (read-only; nothing in either repo was modified).
Skill guidance: motion-pack `skills/motion-pack/SKILL.md` (Recipe H, Gotchas), `references/gotchas.md` (HyperFrames + Transitions + Sound sections).
Research basis: motion-pack `docs/research/edit.md` sections 2 (taxonomy), 2.17 (decision table), 3.3 (interrupt ladder), 5 (sound grammar), 7.2 (talking head).
Everything below was read from code. Section 9 lists what was also run or rendered (scratch only).

---

## 0. Summary

- **50 registry ids.** 49 are visual and one (`speedRamp`) is timing-only. 26 have an exact DOM/CSS back-end (`lib/tx-dom.js` + `lib/tx-dom-x.js` DOM_X). The other 23 GL-only looks run a **DOM approximation** (`APPROX`): same timing, swap frame and sound, but a simpler look. There are also 58 ffmpeg xfade ids (`transitions/xfade-<mode>`) and edit-grammar ids (`cut`, `smash`, `dip-to-black`, `crossfade`, `whip-pan`, ...). 146 names resolve in total.
- **For Reel Director (DOM shots, `<video>` takes), use the DOM path:** `applyDom(key, p, {a, b, root, params, cut})`, driven by **one paused GSAP proxy tween per transition window** on the existing `window.__timelines.main`. This is exactly what the pack's own templates do (`templates/_shared/adapters/transitions.mjs`).
- **Two layers at a cut:** a window `[cut - pre, cut + post]` comes from `txWindow()`. The outgoing clip must run past the cut and the incoming clip must start before it, because HyperFrames hides a timed clip outside `[data-start, data-start + data-duration]`. The pack's `templates/_shared/txplan.mjs` (`txPlan` + `span`) computes this: it moves the incoming `data-media-start` back by `pre` and clamps the window to half of each neighbouring shot.
- **The talking-head twist:** the Reel Director takes carry the voice (`data-has-audio="true"`). Stretching them would double or leak speech. Use HyperFrames' detach pattern instead: a `muted` `<video>` (stretched) plus an `<audio>` over the same file at the exact, unstretched segment times. This is proven in a render (section 9).
- **Sound:** every transition has registry sound ids (`sfx/<cat>/<name>` = file `sfx/library/<category>/snd.<cat>.<name>.wav`). Each sound has a measured `anchor_ms`. House rule: the anchor lands one frame after the picture event, so `audio data-start = anchorFrame/fps - anchor_ms/1000`.

---

## 1. Module map

| path | what | use from Reel Director |
|---|---|---|
| `lib/registry.js` (+ `registry-x.js`) | source of truth: per key `{id, name, backends, timing{ms, beats, cut, ease, minFrames?}, params{type, default, min, max, opts, doc}, sfx[{id, at, offset_f, gain_db, note}], reasons, tags, use, avoid, credit?}` | yes, as data (or read `catalog.json` from Python) |
| `catalog.json` | GENERATED from the registry (schema `motion-pack/transitions@1`). Adds `timing.frames_30fps`, `frames_24fps`, `frames_on_beat{bpm: frames}`, `gl`, `dom`, `dom_approx` and `demo` paths | **best for Python** (`compiler.py`) |
| `aliases.json` | GENERATED from `lib/ids.js`: every writable name (`whip`, `whip-pan`, `zoom-through`, `dip-to-black`, `xfade-circleopen`, ...) maps to `{id, key, params, kind, approx?, xfade?}` | **Python id resolver** |
| `lib/ids.js` | `resolveTx(id)` returns `{id: 'transitions/<name>', key, params, kind: 'cut'\|'smash'\|'dom'\|'gl', approx?, xfade?}` or `null`. `ALIASES`, `GRAMMAR` | browser/Node |
| `lib/tx-core.js` | pure helpers: `EASES` (`linear`, `in/out/inOut` Quad/Cubic/Expo, `outBack`, `whip`=bezier(.7,0,.3,1), `push`=bezier(.2,.8,.2,1), `swipe`=bezier(.32,.72,0,1)), `ease(name\|fn\|[x1,y1,x2,y2], x)`, `bezier`, `snapBpm`, `beatFrames`, `beatToFrame`, **`txWindow(entry, {fps, bpm, cutFrame, durationFrames})`**, `progressAt(win, f)`, `speedRamp`, `RAMP_PRESETS`, `matchPose`, `poseToCss`, `matchDistance`, `bell`, **`resolveParams(entry, params)`** (throws on unknown param names; does NOT range-check) | yes |
| `lib/tx-dom.js` | **`applyDom(key, p, {a, b, root, params = {}, easeName = null, cut = null})`**, `DOM`, `DOM_KEYS`, `APPROX_KEYS` | **the runtime piece** |
| `lib/tx-dom-x.js` | `DOM_X` (13 real back-ends: ditherDissolve, cube, windowSlice, blinds, squeeze, polkaDots, dreamyZoom, linearBlur, pinwheel, radial, overexposure, sharedElement, sketchToRender) and `APPROX` (23 GL-only looks) | imported by tx-dom |
| `lib/sequence.js` | `planEdits(edits, {bpm})`, `stateAt(t, plan)`, `lintPlan(plan)` (edit list to "what is on screen at t") | only with `hfBind` / no-GSAP pages |
| `lib/tx-hf.js` | `hfBind(renderAt, {compositionId, duration, gsap})`: listens to `hf-seek` and, if GSAP is present, **registers its own paused timeline at `window.__timelines[compositionId]`** | **do not use** in Reel Director (it would overwrite `main`) |
| `lib/tx-gl.js` | `createTxRenderer(canvas, {webgl1})` returns `{render({key, from, to, p, params, dur_s, seed, easeName, cut, fps}), compileAll(), gl, programs}`; `textMask`, `DERIVE` | not for `<video>` takes (GL in HF is proven with canvas sources only) |
| `lib/tx-shaders.js`, `tx-shaders-x.js` | GLSL ES 1.00 | GL path only |
| `lib/tx-three.js` | `makeTransitionPass(THREE, key, params).set({from, to, p, width, height})` | three.js kit only |
| `lib/xfade.js` | `xfadeFilter(id, {duration, offset})` returns `[0:v][1:v]xfade=transition=<mode>:duration=..:offset=..[v]`; `PACK_TO_XFADE`, `XFADE` | ffmpeg proxy or preview path |
| `lib/testcard.js` | procedural test shots | demos |
| `examples/hf-dom/index.html` | 9:16 DOM demo (13 transitions; uses `hfBind` + `data-no-timeline`) | reference only |
| `examples/hf-gl/index.html` | 16:9 GL demo on canvases | reference only |
| `renders/` | 2 s demo per key (`whip_9x16.mp4`, `swipeUp_9x16.mp4`, `maskReveal_9x16.mp4` in 9:16), stills, QA json, `contact_dom.jpg` (every DOM back-end) | look before choosing |
| `tests/` | `core.test.mjs` (12 pure tests), `backends.test.mjs` (6 checks), `dom-sheet.mjs` (real Chrome; WRITES into `renders/`), `three-parity.html` | |
| `../templates/_shared/txplan.mjs` | **`txPlan(shots, fps, {bpm})`**, **`span(P, {sel, start, dur, mediaStart})`**, **`txCalls(P, {W, H, root})`** | port to Python, or call via Node |
| `../templates/_shared/adapters/transitions.mjs` | registers every resolvable id with `MP.register`; each one adds one proxy tween calling `applyDom` | the reference binding |
| `../templates/_shared/pack.mjs` | `MP.transition(tl, id, {out, in, root, start, cut, end, W, H, params})`; unknown ids become a logged hard cut | optional glue |
| `../sfx/manifest.json`, `../sfx/sweeteners.json`, `../sfx/library/**` | sound files plus measured anchors; the transition-to-sweetener map | sound pairing |

Browser import graph for `applyDom`: `tx-dom.js` imports `registry.js` (which imports `registry-x.js`), `tx-core.js` and `tx-dom-x.js` (which imports `tx-core.js`). Stage these **5 files (about 92 KB)** together. Add `ids.js` + `xfade.js` only if `resolveTx` runs in the page. `templates/_shared/compose.mjs stage()` hard-links every `lib/*.js` into `assets/mp/transitions/lib/`.

---

## 2. The placement model (two layers at a cut)

### 2.1 Window maths (`txWindow`, `tx-core.js`)
```
n    = durationFrames ?? (bpm ? round(beats*60/bpm*fps) : round(ms/1000*fps));  n = max(minFrames||2, n)
pre  = round(timing.cut * n)
start = cutFrame - pre;  end = start + n          // integer frames; the swap lands EXACTLY on cutFrame
```
- `timing.cut` is the progress at which the shot swaps (the busiest frame). House rule 1: the swap sits on the cut or beat and the transition straddles it.
- Endpoints are exact: `p <= 0` shows shot A only, `p >= 1` shows shot B only (house rule 2, no pop).
- `progressAt(win, f) = clamp((f - win.start) / win.frames)`. p is **linear**; each key's ease (`timing.ease`) is applied **inside** `applyDom`. Gotcha: never put an ease on the proxy tween.

### 2.2 Clamping and stretching (`templates/_shared/txplan.mjs`)
```js
txPlan(shots /* [{start, dur, tx?, txParams?}] in seconds, shot i>0 carries the transition INTO it */, fps, { bpm })
  -> { wins: [{ i, id, key, params, cutF, startF, endF, cut, start, end, out: [], in: [] }], todo: [], fps }
  // kinds: cut / smash -> no window; gl -> todo + hard cut; dom (incl. approx) -> window
  // pre  = min(win.cut - win.start, floor(prevShot.dur * fps / 2))
  // post = min(win.end - win.cut,   floor(shot.dur * fps / 2))
  // pre + post < 2 frames -> todo "shots too short", hard cut
span(P, { sel, start, dur, mediaStart })   // every timed element goes through this
  // ends on a windowed cut (+-1.01 frame)   -> dur extended to win.end, sel pushed to win.out
  // starts on a windowed cut                -> start = win.start, dur += pre, mediaStart = max(0, mediaStart - pre), sel pushed to win.in
txCalls(P, { W, H, root = '#root' })        // emits: MP.transition(tl, id, { out, in, root, start, cut, end, W, H, params })
```
- In the adapter, the cut passed to `applyDom` is the **actual** fraction after clamping: `cut = (ctx.cut - ctx.start) / (ctx.end - ctx.start)`. Pass it yourself.
- `mediaStart` is clamped at 0. If `media_in < pre`, the incoming picture shifts by `pre - media_in` (a sync slip). Shorten `pre` in that case. Also clamp `post` to `sourceDuration - media_out` for the outgoing take.

### 2.3 The binding (exact copy of the pack adapter's behaviour)
```js
const o = { p: 0 }, cut = (W.cut - W.start) / (W.end - W.start);
tl.fromTo(o, { p: 0 }, { p: 1, duration: W.end - W.start, ease: 'none', immediateRender: false,
  onUpdate: () => applyDom(key, o.p, { a, b, root, params, cut }) }, W.start);
```
- When seeking forward, GSAP renders every crossed window at p=1; when seeking back, it renders them at p=0. A layer that is B of window k and A of window k+1 therefore always ends in the correct state.
- Pack gotchas: call `gsap.config({ force3D: false })` and do one warm pass, `tl.seek(tl.duration()).seek(0)`, before `window.__timelines.main = tl`. Without them, frames carry 1-LSB noise between renders.

### 2.4 What `applyDom` owns
- On **every** call it first does `resetLayer(a)` and `resetLayer(b)`. That clears inline `transform, transformOrigin, filter, opacity, clipPath, (-webkit-)mask*, borderRadius, boxShadow, zIndex, backfaceVisibility, mixBlendMode` on both layers. It then clears the overlay and sets `root.style.background = ''` and `root.style.perspective = ''`.
  - Consequence: **a and b must be elements no other tween styles.** Punch-ins, framing ladders and grades go on a different element. Otherwise they are wiped, at the endpoints too.
- It creates one overlay per root, lazily: `root > .mptx-ov` (absolute, inset 0, **z-index 50**, overflow hidden). The overlay holds `.mptx-fill` (flash, dip, overexposure and tvStatic fills, filmBurn and lightLeak screen blends, dither blocks), `.mptx-bars` (shutter bars, glitch slices) and an SVG `feGaussianBlur` (whip, linearBlur). sharedElement and sketchToRender add more.
- It never touches `visibility`. HyperFrames owns clip visibility through `style.visibility`, so applyDom and the clip lifecycle compose.
- Some keys write to the root: `swipeUp` sets root background `#050505`; `cube` sets perspective and background; `iris throughBlack`, `blinds` (gap), `squeeze` (#000) and `doorway` set the background. `sketchToRender` sets the paper colour.

---

## 3. Exact HyperFrames integration for Reel Director

Today `compiler.py` writes `#root > #cam > <video class="clip take" data-has-audio="true" ...>` per kept segment, plus caption, overlay and cutaway `.clip` divs and one classic `<script>` that builds `window.__timelines["main"]`. Snapshot read at 03:00; other agents are editing it.

### 3.1 DOM shape (proven in section 9)
```html
<div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920" data-duration="D" data-fps="30">
  <div id="stage">                                   <!-- untimed; applyDom ROOT -->
    <div id="cam">                                   <!-- untimed; existing zoom/punch tweens stay here -->
      <div class="txl" id="L-hook-0">                <!-- untimed transition layer = applyDom a/b -->
        <video id="take-hook-0" class="clip take" src="assets/hook-1.mp4" muted playsinline
               data-start="0" data-duration="1.1333" data-media-start="0.5" data-track-index="0"></video>
      </div>
      <div class="txl" id="L-turn-0">
        <video id="take-turn-0" class="clip take" src="assets/turn-1.mp4" muted playsinline
               data-start="0.8333" data-duration="2.7334" data-media-start="0.8333" data-track-index="1"></video>
      </div>
    </div>
    <!-- full-screen cutaway as its own layer, stretched by pre(in) and post(out); the take keeps playing under it -->
    <div class="txl" id="L-cutaway-7"><div id="cutaway-7" class="clip cutaway" data-start="1.8" data-duration="1.4667" data-track-index="3">...</div></div>
  </div>
  <!-- captions / overlays after #stage: always above every transition -->
  <!-- voice: exact unstretched segment times, same file and media offset as the picture -->
  <audio id="vo-hook-0" src="assets/hook-1.mp4" data-start="0" data-duration="1" data-media-start="0.5" data-track-index="6" data-volume="1"></audio>
  <audio id="vo-turn-0" src="assets/turn-1.mp4" data-start="1" data-duration="2.4" data-media-start="1" data-track-index="7" data-volume="1"></audio>
  <!-- transition sweeteners: data-start = anchorFrame/fps - anchor_ms/1000 -->
  <audio id="sfx-1" src="assets/snd.whoosh.whip_pan.wav" data-start="0.8774" data-duration="0.32" data-track-index="8" data-volume="0.3"></audio>
</div>
```
CSS:
```css
#stage { position: absolute; inset: 0; overflow: hidden; isolation: isolate; }   /* keeps the z-50 overlay under captions */
#cam   { position: absolute; inset: 0; }
.txl   { position: absolute; inset: 0; }
.take  { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
```
JS (must be a **module**, since applyDom is ESM; the pack templates also build the timeline inside `<script type="module">`):
```html
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script type="module">
import { applyDom } from './assets/mp/transitions/lib/tx-dom.js';
gsap.config({ force3D: false });
const tl = gsap.timeline({ paused: true });
const root = document.getElementById('stage');
const WINS = [ /* from Python: {key, a:'#L-..', b:'#L-..', start, cut, end, params} */ ];
for (const w of WINS) {
  const a = document.querySelector(w.a), b = document.querySelector(w.b), o = { p: 0 }, cut = (w.cut - w.start) / (w.end - w.start);
  tl.fromTo(o, { p: 0 }, { p: 1, duration: w.end - w.start, ease: 'none', immediateRender: false,
    onUpdate: () => applyDom(w.key, o.p, { a, b, root, params: w.params, cut }) }, w.start);
}
/* ... existing caption / overlay / zoom tweens ... */
tl.seek(tl.duration()).seek(0);
window.__timelines = window.__timelines || {}; window.__timelines.main = tl;
</script>
```

### 3.2 Why each rule
- **Untimed `.txl` wrappers, not the `<video>`.**
  - The skill rule is "never tween a timed `.clip`/`<video>`; animate an untimed wrapper".
  - HyperFrames lint rejects a `<video data-start>` nested inside another timed element (`video_nested_in_timed_element`), so the wrapper must stay untimed.
  - applyDom's `resetLayer` would wipe any other tween on the same element.
  - During a render HyperFrames hides the `<video>` and paints a sibling `<img class="__render_frame__">`. Styles on a wrapper reach both naturally.
  - Note: the pack's own `ad`/`beat-edit` templates pass the timed `<video>` itself. HyperFrames mirrors `opacity, filter, clip-path, mask*, transform*, z-index, border-radius` from the video to the frame `<img>` (`MEDIA_VISUAL_STYLE_PROPERTIES`, same in 0.8.142 and 0.8.177) but not `box-shadow` or `backface-visibility`. A 12 fps-source test showed no stale styles (section 9). The wrapper is still the cleaner contract.
- **`#stage` as root, with `isolation: isolate`.** The overlay is z-index 50. If the root is `#root`, flash, dip and glitch fills cover the captions. Inside an isolated `#stage` they stay under captions and overlays (proven). Blend modes in the overlay (screen for filmBurn and lightLeak) then blend over the takes only, which is what we want.
- **Muted picture plus separate voice `<audio>`.** Stretched takes with their own audio would play A's tail and B's head on top of each other for the window. That is doubled or leaked speech from the trimmed regions. Detach audio:
  - `<video muted>` gets `span()` timing.
  - `<audio src=same file>` keeps the exact segment timing. Source-zero (`data-start - data-media-start`) is identical for both, so lip-sync holds.
  - Do **not** add `data-link` (it requires identical start and duration, and lint would warn `linked_clips_out_of_sync`). `data-sync-origin` is fine.
  - Overlapping `<audio>` on the same track index raises a `duplicate_audio_track` lint warning. Abutting segments are fine; alternate the track index if you add audio crossfades.
- **Cutaways in Reel Director overlay a continuing take.** For take to cutaway, A = the take's `.txl` (no stretch needed, the take keeps playing) and B = the cutaway's `.txl`. Out of the cutaway, A = the cutaway layer and B = the same take layer. Only the cutaway clip is stretched (`data-start - pre_in`, `data-duration + pre_in + post_out`). The voice is unaffected because applyDom only sets the take's `opacity`.
- **Z-order limit:** B gets `z-index: 2`. If A lives inside `#cam` and `#cam` has ever been transformed by a zoom tween, `#cam` becomes a stacking context (GSAP leaves an inline transform). A-on-top effects (the `pagePeel` and `doorway` approximations set `a.zIndex 2`) then cannot rise above a B that sits outside `#cam`. B-on-top effects (nearly all) work.
- **`root` size:** applyDom reads `root.clientWidth/Height` (1080x1920). Transforms on ancestors do not change it.
- **Do not call `hfBind`.** It registers its own `window.__timelines[compositionId]` and assumes `data-no-timeline`.
- **Data from Python:** read `transitions/catalog.json` (timing, params defaults, sfx) and `transitions/aliases.json` (`name -> {key, params, kind, approx}`), then port `txWindow` + `txPlan` + `span` (about 30 lines). Or run Node on `templates/_shared/txplan.mjs` with a shots JSON.

### 3.3 Render flags and logs
- Pin `npx --yes hyperframes@0.8.142` (skill). 0.8.177 is installed globally.
- Fast capture (`--experimental-fast-capture`, default on with macOS + GPU) failed self-verification on a DOM push window ("drawElement self-verify failed at frame 8 ... re-rendering via screenshot") and **fell back automatically**. That roughly doubles capture time on transition-heavy reels. Pass `--experimental-fast-capture=false` to skip the wasted pass (not measured further).
- `--crf 23` for reviews (default looks = CRF 16, large). Grep render logs for `Audio lowered by` (dense SFX can trip the AAC peak guard; skill: `ceilingDb -2.5`).
- HyperFrames also has **its own** 14 WebGL shader-transition blocks (`npx hyperframes add whip-pan|glitch|light-leak|cinematic-zoom|flash-through-white|sdf-iris|...`, at most 2 per video, layered composite path). They are an alternative for scene-level shader looks. They were not evaluated here and are not part of motion-pack.

---

## 4. Full catalog (30 fps window, swap point, back-end, first sound, creator fit)

`dom` = exact DOM back-end; `dom~` = DOM approximation of a GL look. Talking-head (TH) fit: G = great, O = ok, P = poor.

| key | ms / f@30 | cut | ease | DOM | first sound | TH fit | note for 9:16 talking head |
|---|---|---|---|---|---|---|---|
| flash | 120 / 4 (1+3) | 0.25 | linear | dom | camera/shutter | G (rationed) | white frame ON the cut hides it; `peak 0.7` safe; at most 3/s |
| scalePunch | 230 / 7 (2+5) | 0.30 | linear | dom | whoosh/zip, hit/punch | **G** | tagged `talking-head`; cheapest energy cut; centre on the eyes `[0.5, 0.38]` |
| whip | 300 / 9 (5+4) | 0.5 | whip | dom | whoosh/whip_pan | G | alternate `dir`; **DOM seam shows a dark band** (see gotchas) |
| push | 350 / 11 (6+5) | 0.5 | push | dom | whoosh/swish_s, ui/slide | G (into or out of cards) | `dir [0,1]` = B enters from below ("next"); reads as UI, not story |
| swipeUp | 450 / 14 | 0.5 | swipe | dom | whoosh/swish_xs | G (9:16 "next") | at most every 3 s; dark backdrop plus rounded card |
| blurCross | 350 / 11 | 0.5 | inOutQuad | dom | whoosh/swish_xs | O-G | soft hide of a cut |
| linearBlur | 400 / 12 | 0.5 | inOutQuad | dom | whoosh/swish_xs | G | "gentler whip that keeps the frame in place"; `angle 90` for vertical; no seam |
| lumaWipe | 500 / 15 | 0.5 | inOutQuad | dom (linear, radial only) | whoosh/swish_s | O | other mattes THROW in DOM (use `radial`, `blinds`, `ditherDissolve` keys) |
| iris | 450 / 14 | 0.5 | inOutCubic | dom | whoosh/swish_s | O | centre on the subject or it reads as a template |
| dissolve | 400 / 12 | 0.5 | inOutQuad | dom | tx/dissolve_pad | O | time passing; never with continuing dialogue (use a J/L cut) |
| dip | 700 / 21 | 0.5 | linear | dom | lift/down | O | chapter break; at most 1 s in short-form |
| overexposure | 700 / 21 | 0.5 | linear | dom | tx/flash_swell | O | softer dip-to-white, memory or reveal; at most 1 per 10 s |
| ditherDissolve | 600 / 18 | 0.5 | linear | dom | tx/glitch_stutter | O | tech/manifesto; cell at least 8 px at 9:16; at most 1 per 15 s |
| cube | 650 / 20 | 0.5 | inOutCubic | dom | whoosh/whoosh_m | O-P | before/after reveals; at most 2 per 30 s |
| spin | 450 / 14 | 0.5 | inOutCubic | dom | whoosh/whoosh_m | P | DOM shows **black corners** (no mirrored edges); "avoid talking heads" |
| shutter | 400 / 12 | 0.5 | linear | dom | whoosh/swish_s | P | "too designed for talking heads"; brand chapter only |
| squeeze | 450 / 14 | 0.5 | inOutQuad | dom | tx/tape_stop | O (comedy) | CRT "nope" gag |
| windowSlice / blinds / pinwheel / radial / polkaDots | 500-700 | 0.5 | inOutQuad | dom | various | P-O | graphic; `radial` = "later that day" clock wipe, once per piece |
| dreamyZoom | 800 / 24 | 0.5 | inOutCubic | dom | lift/inhale | O | lifestyle |
| match | 600 / 18 | 0.5 | linear | dom (no guides) | hit/soft | O | needs anchors (eyes to eyes): `anchorA/B [x, y, size, rot]` |
| sharedElement | 800 / 24 | 0.5 | linear | dom | ui/slide | P | `<video>` inside a shared element freezes (clones are snapshots) |
| sketchToRender | 1600 / 48 | 0.3 | linear | dom | paper/rustle | P | "avoid faces in close-up" |
| zoomThrough | 500 / 15 (7+8) | 0.48 | linear | **dom~** | lift/inhale then hit/thud | G (with fix) | DOM approx: A scales to `scaleOut` with blur, B scales from `scaleIn`. Default 0.5 shows **black around B**; use `scaleIn 1.2-1.35` (proven) |
| glitch | 250 / 8 (4+4) | 0.5 | linear | **dom~** | tx/glitch_stutter | G (hooks, rationed) | approx = x-jitter + hue-rotate/contrast at 12 Hz + red/cyan screen-blend slices; at most 1 per 2 s |
| lightLeak | 700 / 21 | 0.5 | linear | dom~ | sparkle/shimmer | O | warm lifestyle; approx = screen-blend gradient + dissolve; recolour c1-c3 to brand |
| crossWarp | 500 / 15 | 0.5 | inOutQuad | dom~ (dreamyZoom) | whoosh/swish_s | O | "when a whip is too violent" |
| filmBurn / burnOut | 800-900 | 0.5 | - | dom~ | sizzle/grain / tx/film_burn | P-O | retro or memory only |
| tvStatic | 500 / 15 | 0.5 | linear | dom~ | tx/glitch_stutter | O (gag) | "meanwhile" cutaway; under 0.5 s |
| pixelSort, hexagonalize, morph, ink, ripple, swirl, kaleido, directionalWarp, waterDrop, wind, luminanceMelt, gridFlip, bookFlip, pagePeel, doorway, maskReveal | - | - | - | dom~ | - | P | approximations far from the GL look (pixelSort, morph); swirl and kaleido read cheap on faces; maskReveal approx is only a circle iris |
| speedRamp | 800 | 0.3125 | - | curve | whoosh/reverse | P | retime only; dialogue pitch |

Beat-grid lengths: `catalog.json timing.frames_on_beat` (for example whip = 8 f at 120 BPM). On a music grid use `txWindow(entry, {fps, bpm, cutFrame})`.

---

## 5. Creator vocabulary to pack recipes (9:16, 30 fps)

| user says | id / params | when (reason code) | sound (anchor) |
|---|---|---|---|
| whip | `transitions/whip` `{dir: [1,0]}`, alternate `[-1,0]` on the next one; vertical feed `[0,1]` | ENERGY/PLACE: topic or location change, montage. At most 3 in a row | whip_pan (156 ms) at cut+1f: start = cut - 0.123 s; >= 400 ms whips: whoosh_m |
| zoom-through / zoom transition | `transitions/zoom-through` `{center: [0.5, 0.38], scaleIn: 1.3, scaleOut: 3}` (DOM approx) | ENERGY/REVEAL: "dive in" to a screen, an eye, a detail; into a cutaway card | lift/inhale ends ON the cut (start = cut - 0.243), hit/thud at cut+1f (+0.025); or sweetener tx/zoom_through (anchor 328 ms, "end") |
| flash | `transitions/flash` `{peak: 0.7}` (safe) | EMPHASIS/BEAT: punchline, number reveal, music hit. Never on every cut; at most 3/s | camera/shutter or hit/punch at cut+1f; sweetener tx/flash_swell (315 ms) |
| glitch | `transitions/glitch` (approx) | ENERGY/EMPHASIS: hook pattern interrupt, "something broke". At most 1 per 2 s, ideally 1 per 6-9 s (level 3) | tx/glitch_stutter at start+1f (start = cut - 0.201 s), ui/tick at cut+1f |
| push / slide | `transitions/push` `{dir: [0,1]}` (B from below) or `[1,0]` | PLACE: next point, into or out of a list or card | swish_s at cut+1f (cut - 0.100), ui/slide; sweetener tx/push |
| luma wipe | `transitions/luma-wipe` `{matte: 'linear', angle: 90, softness: 0.25}` or `{matte: 'radial', center: [0.5, 0.38]}` | PLACE/REVEAL: graphic punctuation | swish_s at cut+1f; sweetener tx/luma_wipe |
| punch cut / zoom cut | `transitions/scale-punch` `{center: [0.5, 0.38], from: 1.1}` | ENERGY/EMPHASIS on a key claim; disguises jump cuts | whoosh/zip ends on the cut (cut - 0.059), hit/punch at cut+1f; sweetener tx/scale_punch |
| swipe | `transitions/swipe-up` | PLACE: story-style "next" | swish_xs at cut+1f (cut - 0.028) |
| smooth / soft | `linear-blur` `{angle: 90}` or `blur-cross` | hide a cut softly | swish_xs |
| fade to black / white | `dip-to-black` / `dip-to-white` / `overexposure` | TIME: chapter, end card lead-in | lift/down (black) or shimmer (white) |
| jump cut / no transition | `transitions/cut` (hard cut) + framing ladder 1.0/1.15/1.0/1.25 on the eyes `[0.5, 0.38]` | default: same subject, new angle | none (dialogue cuts are SFX-exempt) |
| smash cut | `transitions/smash` (hard cut kind 'smash') | CONTRAST: tonal whiplash; 200 ms pre-silence, then impact | tx/smash_cut (start) |

Rationing (edit.md 3.3 interrupt ladder):
- Level 1 (about every 2.5 s): punch-in or scalePunch.
- Level 2 (about every 5 s): whip or B-roll.
- Level 3 (about every 9 s, at most 1 per 6 s): glitch, flash with a drop, smash.
- Lint fails two level-3 interrupts within 1.5 s.
- Recipe H defaults: punch-ins 1.12 at most 1 per 4 s; hold the face still 450 ms after a punchline before cutting; first B-roll at 2 s or later; B-roll leads the line by 150 ms.

---

## 6. Sound pairing (exact)

- Registry `sfx[]`: `{id: 'sfx/<cat>/<name>', at: 'cut'|'start'|'end'|'peak', offset_f, gain_db, note}`. The file is `motion-pack-public/sfx/library/<category-dir>/snd.<cat>.<name>.wav`; look up `manifest.json sounds[].file` (for example `library/whoosh/snd.whoosh.whip_pan.wav`, `library/impact/snd.hit.punch.wav`, `library/riser/snd.lift.inhale.wav`, `library/transition/snd.tx.*.wav`).
- Placement: `anchorFrame = {cut: cutF, start: startF, end: endF, peak: cutF}[at] + offset_f`, then **`<audio data-start> = anchorFrame/fps - anchor_ms/1000`**. If that is negative, set `data-start=0` and `data-media-start=-x`. Risers (`kind: fixed` anchors at their end, for example lift/inhale 243 ms) end ON the cut (`offset_f 0`).
- Alternative single "sweetener" per kind: `sfx/sweeteners.json` `{kind: [{id: 'snd.*', anchor: start|mid|end, tier, over_bed_db}]}`, where start, mid and end are the window start, cut and end:
  - whip -> whoosh.whip_pan (mid)
  - push -> tx.push (mid)
  - scalePunch -> tx.scale_punch (start)
  - zoomThrough -> tx.zoom_through (end)
  - flash -> tx.flash_swell (mid)
  - glitch -> tx.glitch_stutter (start)
  - blurCross -> tx.blur_cross (mid)
  - lumaWipe -> tx.luma_wipe (mid)
  - iris -> tx.iris_close (mid)
  - dip -> tx.dip_to_black (start)
  - smash -> tx.smash_cut (start)
  - hardCut -> tx.cut_tick (start)
- Levels:
  - `gain_db` / `over_bed_db` are dB **over the music bed** (the pack mixer solves them). The library is peak-normalised to -6 dBFS.
  - Without the mixer, under a voice use absolute stem gains like `templates/talking-head`: transition/punch -14 dB (data-volume about 0.2), emphasis pop -20 dB (0.1), B-roll whoosh -14 dB (0.2), lower third -18 dB (0.13).
  - Music ducked about 9 dB under the voice (Recipe H).
- Exempt from SFX: dialogue cuts and J/L cuts; hard cuts on a music beat.
- The pack target is that at least 80% of non-exempt transition cuts get a cue.
- Missing ids: `snd.tx.whip/swipe/dip/iris/spin` do not exist. Use the registry ids above, which all exist.

Sound placements relative to the cut at 30 fps (computed from `txWindow` + `manifest.json`):
```
flash        shutter cut+0.031 | punch cut+0.026
scalePunch   zip cut-0.059     | punch cut+0.026
whip         whip_pan cut-0.123 (whoosh_m cut-0.193 for >=400 ms)
push         swish_s cut-0.100 | ui/slide cut-0.053
swipeUp      swish_xs cut-0.028 | swipe_ding cut+0.167
glitch       glitch_stutter cut-0.201 | tick cut+0.031
zoomThrough  inhale cut-0.243 (ends on the cut) | thud cut+0.025
lumaWipe/iris swish_s cut-0.100 (iris + pop cut+0.030)
dissolve     dissolve_pad cut-0.378 (-4 dB)
blurCross/linearBlur swish_xs cut-0.028
dip          lift/down cut-0.368 | shimmer cut-0.210
overexposure flash_swell cut-0.682 | shimmer cut-0.244
lightLeak    shimmer cut-0.210 | whoosh/reverse cut-0.601
ditherDissolve glitch_stutter cut-0.401 | grain cut-0.354
```

---

## 7. Gotchas (skill + code + observed)

1. **Timed clips vanish outside their window.** Every two-layer transition needs `span()`-style stretching (skill, gotchas.md).
2. **Never tween a timed `.clip`/`<video>`.** Use untimed wrappers. Never animate `visibility`, `display` or `autoAlpha` on a `.clip` (HyperFrames lint `gsap_animates_clip_element`). applyDom does not.
3. **applyDom wipes the layers' inline styles every call** (resetLayer), so give it dedicated `.txl` layers.
4. **The overlay is z-index 50 inside root.** Use an isolated `#stage` as root, or flash, dip and glitch cover the captions.
5. **The proxy tween is linear** (`ease: 'none'`); the ease lives in applyDom (gotchas.md).
6. **`gsap.config({force3D: false})` + warm pass** before registering the timeline.
7. **DOM gaps** (gotchas.md): spin shows the background instead of mirrored edges; whip has no RGB fringe; lumaWipe is linear/radial only (others throw `lumaWipe matte 'x' is GL-only`, which breaks the onUpdate); iris star and roundRect are approximate; match has no guides. The 23 `dom~` keys keep timing, swap and sound, not the look. pixelSort and morph are far from the original. Look at the cut frame before a hero use.
8. **Observed in the proof:**
   - DOM `whip` shows a **dark vertical seam band** for about 4 frames (each layer's SVG blur fades its own edge to transparent, so the stage background shows through).
   - Mitigations: a lower `blurMax` (0.04-0.05), a `#stage` background near the footage mean colour, `linearBlur`/`crossWarp` (no seam), or the GL path. GL with `<video>` sources is untested in HyperFrames; you would draw frames into canvases.
   - The skill notes that "whip blur needs subframe sampling ... a 2D whip alone exposes black".
9. **zoomThrough DOM default `scaleIn 0.5` shows black around B.** `scaleIn 1.2-1.35` fixes it (resolveParams does not range-check; the GL doc range is 0.2-1, and GL mirrors edges instead).
10. **hfBind registers its own `__timelines[id]`.** Do not use it alongside the main timeline.
11. **GL in HyperFrames is proven with canvas sources only**; a `<video>` as a WebGL texture is untested.
12. **Flash safety:** at most 3 full-frame flashes per second, `peak: 0.7` for safe mode. The pack `eyes` checker tests WCAG flashes.
13. **sharedElement** clones are snapshots: hold shared elements still; a `<video>` inside one freezes.
14. **`mediaStart` clamps at 0** in `span()`. Keep `pre <= media_in` or the incoming picture slips.
15. **Default to the hard cut.** Every non-cut transition needs a reason code (LINK, ENERGY, CONTRAST, TIME, PLACE, REVEAL, EMPHASIS, BEAT, BRIDGE_AUDIO). The pack lint `lint.tx` exits 2 on unmotivated transitions in templates.
16. **Decision table** (README / edit.md 2.17):
    - same subject, new angle: hard cut;
    - dialogue continues across a change: J/L cut (never dissolve);
    - energy or place: whip or scalePunch;
    - time or memory: dissolve, dip or lightLeak (never glitch);
    - into a screen or eye: zoomThrough (never whip);
    - music hit or emphasis: flash or scalePunch;
    - tech or hook interrupt: glitch or whip;
    - 9:16 "next": swipeUp (never pagePeel).
17. **Short shots:** txPlan hard-cuts when `pre + post < 2` frames after clamping to half of each neighbour. Jump-cut segments under about 0.27 s cannot host a whip.
18. **Fast capture** falls back to screenshot capture on these windows (logged WARN). Nothing breaks, but time is wasted.

---

## 8. Other paths (when not DOM)
- **ffmpeg finisher** (previews, proxies): `xfadeFilter('whip', {duration: 0.3, offset: cut - 0.15})` gives `[0:v][1:v]xfade=transition=<PACK_TO_XFADE[whip]>:duration=0.3000:offset=..[v]`. All 59 strings were checked on ffmpeg 8.0.1. Every `transitions/xfade-<mode>` id resolves to the nearest pack key for DOM use.
- **GL on canvases:** `createTxRenderer(canvas).compileAll()`, then per frame `tx.render({key, from: canvasA, to: canvasB, p, params, dur_s})`. This needs the video painted into canvases per frame. Use it only if the exact GL whip (chroma fringe, mirrored edges), glitch or zoomThrough is required, and first-test it in HyperFrames.
- **Python planner:** `../cuts/cutgen.py beats --bpm 128 --pattern every_2 --tx whip --snap` (beat-grid cut lists with sound anchors).

---

## 9. Verification run for these notes (scratch only)
- `node transitions/tests/core.test.mjs`: 12/12 passed. `node transitions/tests/backends.test.mjs`: 6/6 passed (50 ids, 23 approximations, 146 names resolve). Neither writes to disk.
- `scratch-transitions/windows.mjs` computed every window and sound offset above with the pack's own `txWindow` + `manifest.json`.
- **Proof render** `scratch-transitions/proof/index.html`, rendered to `scratch-transitions/proof.mp4` (`hyperframes@0.8.142`, 4.4 s, 1080x1920, 132 frames, 11 s, 1.2 MB).
  - Setup: two real Reel Director demo takes (symlinked read-only), muted stretched pictures, separate voice `<audio>`, `.txl` wrappers, `#stage` root with isolation, and a full-screen cutaway over the continuing take.
  - Windows tested: whip (take to take), push dir [0,1] (take to cutaway), zoomThrough scaleIn 1.3 (cutaway to take), scalePunch (take to take). Each is one proxy tween with the warm pass.
  - Lint: 0 errors, 2 advisory `nested_structure_needs_subcomposition` warnings.
  - Contact sheet `scratch-transitions/sheet.jpg`: swaps land on frames 30 / 60 / 90 / 102, the caption stays above every transition, the cutaway pushes up from below, and zoomThrough lands with no black border. The whip seam band is visible on frames 28-31 (`whipmid.png`).
  - Audio: voice present; per-frame RMS shows clean segment switches and no doubling.
- **Stale-style test** (`staleD` / `staleW`): a 12 fps source rendered at 30 fps, push applied directly to `<video>` (D) versus to wrappers (W). The B edge x per frame was identical: `[720, 428, 252, 152, 96, 60, 36, 20, 8, 4, 0]`. HyperFrames extracts frames at output fps, so styles re-sync every frame. Both renders logged the fast-capture self-verify fallback.
- Not verified: GL path with `<video>` in HyperFrames; the HyperFrames-native shader blocks; audio crossfades on voice edges (`data-automation` lanes); 0.8.177 rendering (lint and render ran on 0.8.142).
