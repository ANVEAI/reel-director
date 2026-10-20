# motion-pack module group "layers-looks": map for Reel Director

Scope: motion-pack `layers/` (overlay.js, backgrounds*.js, canvas2d*.js, fx2.js, finisher.js, grade.js, stylize.js, presets/, looks/), plus `type/gfx/editorial.js title.progressBar`. Read-only survey on 20 Oct 2026. Both repos were left untouched. All test output went to a scratch folder (`scratch-layers-looks/`, not kept).

Skill sources: motion-pack `skills/motion-pack/SKILL.md` ("Reach for X", RECIPE H, Gotchas), `references/apis.md` (## Layers), `references/gotchas.md` (HyperFrames + "Layers and camera"), `references/critic.md` (banding), frame-design SKILL ("Looks and grain").

---

## 0. TL;DR for Reel Director (talking head, 1080x1920, one paused GSAP timeline)

1. **Stage the module closure.** `layers/overlay.js` needs 25 files: all of `layers/*.js`, `layers/lib/*`, `layers/presets/*` **plus** `type/gfx/{safe,pathsample,media,core}.js` and `type/{ease,safezones}.js` (221 KB). Copy them into `<project>/assets/mp/` with the same relative layout (`assets/mp/layers/...`, `assets/mp/type/...`). HyperFrames serves only the project directory. A copy of `layers/` on its own fails to import, and the failure is silent: the render simply has no layers.
2. **Drive layers by time, not by GSAP.** Every layer is a pure function of `t` and `frame`. `bindHF(stack, {t0, fps})` renders on every `hf-seek` window event. I checked that HyperFrames 0.8.142 and 0.8.163 both dispatch `CustomEvent('hf-seek', {detail: {time, waitUntil}})` on every seek. `t0` is the clip's `data-start`, so params like `at`, `riseAt`, `burstAt` and `flashes` are in local time.
3. **Order the global finish by DOM position, never by container z-index, opacity or transform.** The stack rule, bottom to top, is: footage + grade, leaks/bokeh/glow, paper, vignette, story type (captions, overlays), dust, grain, brand/UI, bars. HyperFrames paints in DOM / CSS z-index order (`data-track-index` is display only).
4. **Defaults for a talking-head reel:** grade `documentary` on `#cam` only; `vignette` (amount 0.15-0.2, roundness 1); `grain` stock `upload-safe` (or `digital-soft`); a top progress bar. Cutaway and title-card backgrounds: `meshGradient`, `dotGrid` or `auroraRibbon`. End card: `brandField`. Light leaks are off by default; on 9:16 they need taming (section 5).

---

## 1. Files and how to stage them

| need | files (repo-relative) | size |
|---|---|---|
| overlays, backgrounds, Canvas2D kinds (`mountStack`, `bindHF`, `lintOverlayStack`) | `layers/overlay.js` + closure: `layers/{backgrounds-r6,backgrounds,canvas2d-r3,canvas2d-r45,canvas2d,ease,finisher,fx2,grade,limits}.js`, `layers/lib/{fx-params,gl,glsl-common,glsl-fx,glsl-passes}.js`, `layers/presets/{finish,grades,stocks}.js`, `type/ease.js`, `type/safezones.js`, `type/gfx/{core,media,pathsample,safe}.js` | 25 files, 221 KB |
| grade emitters (`toSVGFilter`, `toCube`, `mixGrade`, `gradeRGB`) | `layers/grade.js` (no imports) + `layers/presets/grades.js` | 12 KB |
| 45 looks (params) | `layers/presets/looks.js` (`LOOKS`, `LOOK_NAMES`, `lookParams(name)`, `LOOK_TAGS`) | 8 KB |
| look LUT files | `layers/looks/look.<name>.cube` (17^3, ~132 KB each); `log.{logc3,slog3,vlog}-to-709.cube`, `neutral.rolloff-709.cube` (33^3, ~970 KB) | 9.5 MB total; copy only the one you use |
| stylize looks (`mountLook` duotone / threshold1bit, `mountGradeIn`) | `layers/stylize.js` (no imports) | 15 KB |
| canvas fonts (brandField, dotCondense word, embeddingCloud, epicycleDraw) | `templates/_shared/fonts/Manrope-Variable.ttf` (165 KB), `IBMPlexMono-SemiBold.ttf` (140 KB), OFL | |
| progress bar (pack part) | `type/gfx/index.js` closure: 31 files, 561 KB. A plain GSAP bar is simpler (section 8). | |

How the pack does it: `templates/_shared/compose.mjs stage(dir, {layers: true})` hard-links `layers/**/*.js` into `assets/mp/layers/` and `type/*.js` + `type/gfx/*.js` into `assets/mp/type/`, falling back to a copy. The talking-head template mounts layers this way (`templates/talking-head/make.mjs` lines 54-55):

```js
import { mountStack, bindHF } from './assets/mp/layers/overlay.js';
bindHF(mountStack(document.getElementById('fx'), [{kind:'vignette',params:{}},{kind:'grain',params:{stock:'digital-soft'}}], { width: W, height: H, fps: F, seed: 11 }), { fps: F });
```

In that template `#fx` is `<div id="fx" class="clip" data-start="0" data-duration="T" data-track-index="5"></div>`, the last visual element in `#root`.

Reel Director's page builds its timeline in a classic inline `<script>` with GSAP from the CDN. Add a separate `<script type="module">` for the layers. Module scripts run after the classic script and before DOMContentLoaded, so the timeline is already registered and the layers mount before HyperFrames captures. Run `npx --yes hyperframes@0.8.142 validate <project>` after compiling: it reports JS errors and missing assets, and a failed module import otherwise renders silently with no layers.

---

## 2. Timing model (seek-safe)

- `mountStack(root, layers, {width, height, fps, seed})` appends one absolutely positioned `<canvas class="mp-layer">` per layer to `root`, sorted by kind `order`, with the kind's CSS `mix-blend-mode`. It returns `{ layers, ready(), render(t, {frame, cuts}), dispose() }`.
  - Layer spec: `{ kind, params?, order?, blend?, opacity? }`. `opacity` sets the canvas's own CSS opacity. That is safe; container opacity is not (section 7).
- `bindHF(stack, { t0 = 0, fps = 30 })` (overlay.js) does three things:
  - listens to `hf-seek` and calls `stack.render(t - t0, { frame: Math.round((t - t0) * fps) })`;
  - renders once at `window.__hfThreeTime || 0`;
  - repaints once `stack.ready()` resolves (images).
- Canvas2D kinds and backgrounds use `t = frame / fps` when `frame` is passed, so time is quantised to frames. GL overlays use `uFrame` for grain and dust patterns and `uTime` for drift.
- There is no clock, no `Math.random` and no history: only seeded hashes. The pack tests show the same calls and bits in forward, reversed and shuffled order. My 1080x1920 probe gave identical per-layer pixel hashes at t = 2.5 and t = 2.0 after seeking to 5.1, 0.2 and 7.9 (leaks, vignette, grain, meshGradient).
- **Do not drive layers from GSAP `onUpdate`.** `hf-seek` is the path the pack verified. A paused-timeline seek may suppress callbacks.
- **Windowed renderer for per-cutaway backgrounds** (my recommendation, not a pack API). `bindHF` re-renders a stack on every frame of the whole reel even while its clip is hidden, so N cutaway backgrounds cost N renders per frame. Render only inside the window:

  ```js
  function bindWindow(stack, start, dur, fps) {
    const f = (t) => {
      if (t < start - 1 / fps || t > start + dur + 1 / fps) return;
      const u = t - start;
      stack.render(u, { frame: Math.round(u * fps) });
    };
    window.addEventListener('hf-seek', (e) => f(e.detail.time));
    f(window.__hfThreeTime || 0);
    stack.ready().then(() => f(window.__hfThreeTime || 0));
  }
  ```

  It stays seek-safe because `render` is a pure function of `u`.

---

## 3. Stack rule and DOM order for Reel Director

Pack stack rule (README "Stack rule (binding)", apis.md): leaks/bokeh/glow, **grade**, paper, vignette, scanlines, **story type**, dust, grain, **brand**, bars, dither. Light leaks sit below the type. Grain goes over everything except brand and bars. One grade per piece (two per scene at most, with a 12-frame `mixGrade` crossfade). Kind `order` values: background 1, leaks 10, bokeh 11, glow 12, fx2 lens 13-19, paper and texture plates 30, halftone 31, vignette 40, embeddingCloud 40, scanlines 50, vhs 52, rainGlass 55, dotCondense/convergeToDot 57, speedLines 58, dust 60, grain 70, audio-reactive 80, confetti 85, tornEdge 88, invertFlash 89, bars 90, impactFrame 91, recHUD 92, timecode 93, sprocket 94, gateEdge 95, polaroid/instax 96, brandField 97.

Proposed `#root` children, in DOM order:

```html
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs id="mp-defs"></defs></svg>   <!-- grade filter (outside #root is fine) -->
<div id="root" data-composition-id="main" ...>
  <div id="cam" style="filter:url(#mp-grade)"> <video class="clip take" ...> ... </div>   <!-- grade the footage only -->
  <div id="fx-low"  class="fx"></div>    <!-- leaks / bokeh / glow (screen) -->
  <!-- cutaways: <div id="cutaway-N" class="clip cutaway" data-start data-duration><div class="cut-bg" id="cutaway-N-bg"></div><div id="cutaway-N-in" class="cutaway-inner">...</div></div> -->
  <div id="fx-mid"  class="fx"></div>    <!-- vignette (normal) -->
  <!-- overlays + captions (story type) -->
  <div id="fx-top"  class="fx"></div>    <!-- dust, grain -->
  <div id="progress"><div id="progress-fill"></div></div>
  <div id="endcard" class="clip" data-start=".." data-duration=".."><div id="endcard-fx" class="fx"></div></div>
  <audio ...>
</div>
```

CSS: `.fx { position:absolute; inset:0; pointer-events:none }`. **No z-index, opacity, transform, filter, isolation or will-change on `.fx` or on any ancestor between a blend canvas and `#root`** (section 7).

Reel Director today emits captions and cutaways interleaved per shot into one `body` list. The cutaway is appended after its shot's captions, so an opaque full-frame cutaway paints over that shot's captions. The layering above needs separate lists, or z-index on caption and cutaway elements themselves (never on the `.fx` containers).

Pack module (sketch):

```html
<script type="module">
import { mountStack, bindHF } from './assets/mp/layers/overlay.js';
import { toSVGFilter } from './assets/mp/layers/grade.js';
import { GRADES } from './assets/mp/layers/presets/grades.js';
import { lookParams } from './assets/mp/layers/presets/looks.js';
const W = 1080, H = 1920, F = 30, $ = (id) => document.getElementById(id);

// one grade (or one look) on the footage wrapper
$('mp-defs').innerHTML = toSVGFilter(GRADES['documentary'], 'mp-grade');   // or toSVGFilter(lookParams('matte-cool'), 'mp-grade')

// global finish
bindHF(mountStack($('fx-mid'), [{ kind: 'vignette', params: { amount: 0.18, roundness: 1 } }], { width: W, height: H, fps: F, seed: 7 }), { fps: F });
bindHF(mountStack($('fx-top'), [{ kind: 'grain', params: { stock: 'upload-safe' } }], { width: W, height: H, fps: F, seed: 11 }), { fps: F });
// optional, tamed for 9:16 (section 5):
// bindHF(mountStack($('fx-low'), [{ kind: 'leaks', opacity: 0.4, params: { intensity: 0.08, loop: true, edge: 'bottom' } }], { width: W, height: H, fps: F, seed: 3 }), { fps: F });

// per-cutaway background (emitted by the compiler: id, start, dur, kind, params)
for (const b of window.__MP_BGS || []) bindWindow(mountStack($(b.id + '-bg'), [{ kind: b.kind, params: b.params }], { width: W, height: H, fps: F, seed: b.seed ?? 5 }), b.start, b.dur, F);

// end card
const end = mountStack($('endcard-fx'), [{ kind: 'brandField', params: { at: 0, color: ACCENT, ink: '#FFFFFF', name: 'Brand', line: 'One line.', logo: 'assets/logo.png', reveal: 'iris', revealDur: 0.35 } }], { width: W, height: H, fps: F });
bindHF(end, { t0: END_START, fps: F });   // bindHF repaints when the logo image has decoded

// canvas text needs its face before the frame is drawn: repaint the current time once fonts land (pattern from templates/demo-r6-pivot)
let last = window.__hfThreeTime || 0;
window.addEventListener('hf-seek', (e) => { last = e.detail.time; });
Promise.all([document.fonts.load('800 60px Manrope'), document.fonts.load('600 30px Manrope')])
  .then(() => window.dispatchEvent(new CustomEvent('hf-seek', { detail: { time: last } })));
</script>
```

(`bindWindow` is from section 2. Add `@font-face { font-family: Manrope; src: url(assets/fonts/Manrope-Variable.ttf) }` when canvas text is used.)

---

## 4. Parts catalogue (exact APIs and params)

### 4.1 Core overlay kinds (`overlay.js KINDS`, one WebGL2 canvas each)

| kind | blend | order | params (defaults) |
|---|---|---|---|
| `grain` | overlay (opaque mid-grey canvas) | 70 | `stock` 'film35' (clean, digital-soft, film35, film16, super8, vhs, upload-safe, none), `amount`, `sizePx`, `chroma`, `fps` (each overrides the stock) |
| `vignette` | normal | 40 | `amount` 0.2, `inner` 0.35, `outer` 1.414, `roundness` 0.6 (0 = elliptical to the frame, 1 = circular in pixels, stable on 9:16), `color` **[r,g,b] floats** [0,0,0] |
| `leaks` | screen | 10 | `on` true, `intensity` 0.6, `count` 3 (max 5), `edge` 'any' (left, right, top, bottom), `colors` ['#FF6A1A','#FFB347','#E8336D'], `seed` 7, `loop` false (true = breathing 0.65-1.0 x intensity), `envelope` {start 0, in 0.5, hold 1.0, out 1.0} (used when loop is false), `flashes` [t or {t, attack, decay}] (frames, default 3 / 12) |
| `dust` | normal | 60 | `density` 0.6, `hair` 1, `scratch` 0.7, `under` 0.35 (assumed plate luma for mark polarity) |
| `bokeh` | screen | 11 | `count` 18, `radius` [0.02, 0.09], `intensity` 0.5, `soft` 0.25, `hex` 0, `drift` 0.04, `colors` |
| `glow` | screen | 12 | `pools` [{x, y (measured from the BOTTOM), r, color hex, intensity}] (max 3) |
| `paper` | multiply | 30 | `amount` 0.5, `scale` 1, `fiber` 1, `angle` 0.4, `tint` [r,g,b] floats |
| `scanlines` | normal | 50 | `pitch` 3, `depth` 0.18, `mask` 0 |
| `bars` | normal | 90 | `ratio` 2.39, `reveal` {at, dur} or null |

Grain stocks (`presets/stocks.js`): amount, sizePx, chroma, fps.
- `clean` 0.020 / 1.0 / 0 / 30
- `digital-soft` 0.035 / 1.2 / 0.10 / 30 (the talking-head template and RECIPE A default)
- `film35` 0.070 / 1.4 / 0.35 / 24
- `film16` 0.110 / 1.8
- `super8` 0.160 / 2.4 / 18 fps
- `vhs` 0.090 / 1.6 / chroma 0.8
- `upload-safe` 0.030 / 1.5 / 0 / 30, for a clean look that must survive platform re-encoding, which smears 1 px grain

Overlay grain behaves like midBias 1: quiet in shadows and highlights. Exact kit grain needs the Finisher.

`lintOverlayStack(layers, {plateBaked: {grain, vignette, bloom}})` returns warnings: more than one grain, vignette, paper, scanlines or bars; or grain/vignette already baked into the plate.

### 4.2 Grades and looks (`grade.js`, `presets/grades.js`, `presets/looks.js`, `looks/*.cube`)

- `GRADES`:
  - `neutral`
  - `premium-product`
  - `warm-film`
  - `cool-tech`
  - `retro-vhs`
  - `nostalgic-print`
  - `bright-playful`
  - `noir`
  - `documentary` (tags talking-head, interview, founder, vlog; RECIPE H step 8). Fields: `temp`, `tint`, `exposure`, `contrast` 0..1, `slope` / `offset` / `power` (ASC CDL), `sat`, `split` {shadowHue, shadowSat, highHue, highSat, balance}, `fade`.
- 45 `LOOKS` share the same parameter space; `lookParams(name)` drops the `_tags`. Names:
  - bleach-bypass, bleach-soft, cross-process, day-for-night, teal-orange, teal-orange-soft, two-strip
  - cyanotype, sepia, selenium, bw-neutral, bw-red/orange/yellow/green/blue-filter, bw-high-key, bw-low-key
  - faded-90s, faded-film, matte-cool, matte-warm, golden-hour, blue-hour, overcast
  - neon-night, neon-teal-pink, pastel, high-key-beauty, tobacco-wash, green-matrix, sodium-street
  - clean-commercial, vivid-pop, food-warm, muted-earth, arctic-white, desert-heat, monsoon-green
  - festive-gold, horror-cold, dream-glow, newsprint, security-cam, lofi-polaroid
- Rule: **one look per piece; a look replaces the grade, never stacks on it.** Send log footage through `log.<cam>-to-709.cube` first. Phone footage is not log.
- Emitters:
  - `toSVGFilter(params, id='mp-grade', n=256)` returns a `<filter>` string for `<defs>`; apply with `el.style.filter = 'url(#id)'`. Measured SVG mean dE ≤ 0.6.
  - `toCube(params, title, size=33)` returns `.cube` text; measured ffmpeg `lut3d` max 1.34 levels against the JS reference.
  - `mixGrade(a, b, k)` crossfades two grades.
  - `gradeRGB(prepare(p), [r,g,b])` is the JS reference.
  - I verified in node that `toCube(GRADES.documentary)` writes a 33^3 cube (970 KB) and that `toSVGFilter(lookParams('matte-cool'))` builds (14 KB string).
- **Three ways to apply a look to the footage only** (never to captions or brand: grade is below story type in the stack rule, and the HF docs say "keep the brand colors exact"):
  1. **Pack SVG filter on `#cam`.** The pack path, seek-safe, no time input. It costs compositor time: rough rAF probe at 1080x1920 went from 8.3 to 14 ms mean, p95 9 to 33 ms (not a HyperFrames render measurement). The filter applies to the zoom-scaled `#cam` too, which is fine.
  2. **HyperFrames native grading on each take** (HF 0.8.142 `media-treatment` "lut" family; maximum cube size 64; intensity animatable through the CSS variable `--hf-color-grading-lut-intensity` on the registered GSAP timeline): `<video class="clip take" ... data-color-grading='{"lut":{"src":"assets/looks/look.matte-cool.cube","intensity":0.85}}'>`. Prefer `hyperframes media-treatment --project . --selector '#take-x-0' --grading '<json>' --dry-run|--apply`. HF also has `grade-compare --for frame.png --luts a.cube,b.cube` to pick a look. **Not verified with the pack cubes in this session.**
  3. **ffmpeg pre-bake on the takes:** `ffmpeg -i take.mov -vf lut3d=file=look.cube -c:v libx264 -crf 14 -c:a copy take.graded.mp4`. Zero render-time cost and deterministic; costs a re-encode and disk.
- Stylize (`stylize.js`):
  - `mountLook(el, 'duotone' | 'threshold1bit', params, {H})` returns `{id, update, dispose}`. Static SVG filter; put it on a **still** wrapper (the Bayer phase follows the element). Needs an opaque source.
  - `mountGradeIn(el, {stops, at, dur, ease: lin|soft|hero|sine|expoOut, reverse, amount, contrast, pivot}).render(t)`: an animated gradient map that resolves to natural colour. Call `render(t)` on every `hf-seek` (it only rewrites two arithmetic weights; at w = 0 the filter is removed).
  - `.cube` emitters exist for duotone (`toCube('duotone', p)`) and gradeIn (`gradeInCube(p, w)`).

### 4.3 Backgrounds (`backgrounds.js`, `backgrounds-r6.js`; Canvas2D, opaque, blend normal, order 1; mount with `mountStack` like any kind)

| kind | params (defaults) | use in reels |
|---|---|---|
| `meshGradient` | `palette` peach / lilac / sky / dusk / mint / ink (or `colors` [3-8 hex] + `bg`), `base` flat / vertical, `blobs` 5, `size` 0.62, `travel` 0.16, `speed` 0.05 Hz, `loop` 0 (L = exact repeat), `seed` 3, `grain` 0.04 (keep ≥ 0.02 against banding), `grainFps` 24, `intensity` 1 | default SaaS cutaway or title-card field. Light palettes do not suit white captions; use `ink` or `dusk` for white type. |
| `dotGrid` | `color` '#4A18ED', `bg` '#F5F2EA', `spacing` 36, `radius` 3, `drift` [0,0] px/s, `fade` 0.5, `hole` 0 (clear radius behind type, fraction of H), `glow` 0.5, `glowColor`, `glowAt` [0.5,0.5], `glowRadius` 0.55, `intensity` | statement card with a clean hole behind the words |
| `gridTunnel` | `color`, `bg`, `lines` 8, `depth` 12, `drift` 0.5 rings/s, `zoom` 0, `vp` [0.5,0.5], `width` 2, `fade` 0.9 | tech energy card |
| `auroraRibbon` | `colors` 2-5 hex (placeholders), `bg` '#030206' (null = transparent), `riseAt` 0.4, `rise` 1.4, `lead` 0.1, `height` 0.24, `crest` 0.1, `waves` 3, `spread` 0.1, `core` 0.7, `halo` 0.45, `speed` 0.035, `kick` 0.3, `kickDur` 0.35, `loop` 0 (exact seam, already risen), `grain` 0.4, `grainFps` 24, `res` 96, `intensity` 1, `seed` 6 | dark "solution" or pivot card; `cuesR6('auroraRibbon', {riseAt})` gives `sfx/hit/sub_drop` at `riseAt - lead`. A fade for the hold is the host's job: tween the canvas opacity, not a container's. |
| `hexMosaic` (K2D, order 1) | `radius` 64, `gap` 5, `faces` ['color','engrave'], `palette`, `images` [], `waves` [{at, from, speed}], `speed` 1500, `flip` 0.32, `loop`, `panel` {rect, color, radius} | brand-texture backdrop |

### 4.4 Canvas2D accents (`canvas2d.js`, `canvas2d-r3.js`, `canvas2d-r45.js`; params clamped by `limits.js`)

- **Finishing furniture**
  - `brandField` (end card, order 97): `at`, `color`, `ink`, `name`, `line`, `logo` (URL or image; `await stack.ready()`), `mark` 'orbit', `reveal` cut / iris / wipe, `revealDur` 0.35, `settle` 0.9, `scaleFrom` 1.08, `lineDelay` 0.18, `y` 0.46, `size` 0.11. Hold ≥ 1.8 s after it settles.
  - `invertFlash` (difference, order 89): `at` [s...], `frames` 2 (max 3), `color`; `safeFlashes` / `lintFlashes` cap it at ≤ 3 onsets per second.
  - `recHUD` (`label`, `start`, `battery`), `timecode` (`style` vhs / crt / film, `date`), `sprocket`, `gateEdge`, `polaroid`, `instax`, `impactFrame` (`at`, `frames` 3).
- **Particles** (closed form):
  - `sparks` (screen; `burstAt` turns it into a one-shot burst)
  - `confetti` (normal, order 85; `burstAt`, `x`, `y`, `colors`)
  - `embers`, `snow`, `motes` (screen), `smoke` (normal)
- **Audio-reactive:** `arBars`, `arRing`, `arWave`, `arSpectrum`, each driven by `beats` [s] or `env` (values per frame or per band) via `envAt`.
- **Explainer layers:**
  - `dotCondense` (`to` fewer / line / word, `text`, `at`, `dur`)
  - `convergeToDot` (`at`, `dur`, `reverse`)
  - `hologramBeam` (screen; dark plates only)
  - `embeddingCloud` (query chip; `images`; fonts)
  - `epicycleDraw` (SVG path traced by circles; fonts)
  - `cuesR45(kind, params)` gives one sound per action.

### 4.5 fx2 GL kinds (`fx2.js`, one WebGL2 canvas each)

- Lens: `flareStreak`, `flareGhosts`, `starburst`, `lensDirt` (screen).
- Atmosphere: `fog`, `godRays` (screen), `rainGlass` (normal).
- Film / retro: `burnEdge` (screen, `edge`), `vhs` (normal).
- Comic: `halftone` (multiply), `speedLines` (normal).
- Texture plates: `paperFold`, `crumple`, `cardboard`, `canvas`, `cloth`, `concrete` (multiply), `brushedMetal` (overlay), `tornEdge` (normal).
- `noiseMap` (luma matte).

Defaults are listed by `node -e "import('./layers/fx2.js').then(m=>console.log(m.FX2_KINDS))"`. Skill: "one hero light effect per shot"; "multiply plates go under type".

### 4.6 Finisher (`finisher.js`)

`new Finisher(canvas, preset, {width, height, fps}).setSource(plateCanvas).setType(typeCanvas).render(t, {frame, hits, cuts})`. It needs plate pixels on a canvas, and "GL in HyperFrames is proven with canvas sources only" (a `<video>` as a GL texture during a render is untested). That makes it a poor fit for a DOM talking-head reel. Use overlays plus the SVG grade instead. Its `documentary` finish recipe (sharpen 0.3, bloom 0.1, vignette 0.12, grain digital-soft) is the reference look for talking heads.

---

## 5. Light leaks on 9:16: measured in this session (they need taming)

The leak blobs are gaussians sized in frame-height units, with x distances multiplied by the aspect ratio. On 1080x1920 they span the whole width. Results from my probe (leaks canvas alone, M3 Pro Chromium; mean luma of the screen-blended canvas, 0-255, by thirds top / mid / bottom):

| setting | top | mid | bottom |
|---|---|---|---|
| `edge: left`, intensity 0.05, loop | 47 | 53 | 51 |
| `edge: left`, intensity 0.15, loop | 83 | 92 | 88 |
| `edge: top`, intensity 0.05 | 59 | 40 | 18 |
| `edge: bottom`, intensity 0.05 | 17 | 36 | 56 |
| windowed `{loop: false, intensity: 0.3, envelope: {start: 2, in: 0.25, hold: 0.2, out: 0.6}}`, t = 1.9 / 2.3 / 3.2 | 0 / 112 / 0 | 0 / 123 / 0 | 0 / 117 / 0 |

Every whole-frame row is a wash: even intensity 0.05 lifts blacks. In a screenshot at 0.22 the dark shirt turned pink-brown and the saturated swatches went milky.

- **`flashes` and `cuts` drive the leak to FULL intensity whatever the `intensity` value.** At a flash peak the mean colour was (252, 182, 150) over the whole frame. That is a full-frame flash: it counts toward WCAG ≤ 3 flashes/s (`eyes/flashes`), and it is too much for a talking head. Scale it with the layer's `opacity` (canvas opacity, e.g. 0.3-0.5), or use a windowed `envelope` instead of `flashes`.
- **With `loop: false` and no `envelope` there is a trap:** the default envelope (start 0, in 0.5, hold 1, out 1) shows the leak only in the first 2.5 s of the stack's time.
- **Recommendation:**
  - Off by default.
  - For a warm "memory" or tonal-break accent, use `edge: 'bottom'` or `'top'` (keeps the face cleaner), `intensity` 0.05-0.1, layer `opacity` 0.3-0.5, and a windowed envelope around that moment.
  - The skill says `filmBurn` / `lightLeak` only for memory or a tonal break.

---

## 6. Measured in this session (1080x1920; Chromium ANGLE Metal on an M3 Pro; JS render plus a forced GPU sync, mean ms per frame over 30 frames)

- leaks 1.4, vignette 1.2, grain 1.4
- meshGradient 1.7-2.9, dotGrid 2.4, gridTunnel 9.4, **auroraRibbon 21.6**, hexMosaic 1.6
- fog 8.0, dust 6.7, lensDirt 4.3, paper 3.0
- dotCondense (word) 2.6, convergeToDot 1.1, brandField 0.7, confetti 0.5, motes 0.6, invertFlash 0.2, arWave 0.6

The whole probe stack (leaks + vignette + grain + one cutaway meshGradient) costs 2.8-3.6 ms per seek. None of this is a bottleneck for an offline HyperFrames render. auroraRibbon is the heavy one: keep it windowed.

Probe page and copies (scratch, not kept): `scratch-layers-looks/web/index.html`. Generated cube: `scratch-layers-looks/grade.documentary.cube`. HF media-treatment catalogue: `scratch-layers-looks/mt-all.json`.

---

## 7. Gotchas (pack and verified here)

1. **Isolation turns grain into a flat grey frame (verified).** The grain canvas is an opaque mid-grey sheet with `mix-blend-mode: overlay`. Anything that makes its container a stacking context isolates the blend, and the whole reel goes grey: z-index with position, `opacity < 1`, `transform` (even `scale(1.001)`), `filter`, `isolation: isolate`, `will-change`. I reproduced it with `opacity: 0.99` and with `transform: scale(1.001)` on the grain container. Screen layers (leaks, bokeh, glow) and multiply layers (paper) fail the same way, less visibly. `opacity` on the canvas itself (`{kind, opacity}`) is fine (verified). Pack gotcha: "Do not put z-index on the #fx container ... set z on the canvases." Never put a blend layer inside a container that GSAP fades, scales or moves. `#cam` gets zoom tweens, so a leak inside `#cam` would blend with the footage only.
2. **Timed clips vanish outside `[data-start, data-start + data-duration]`.** Never tween a timed `.clip` or `<video>` directly; animate an untimed wrapper.
3. **GSAP determinism:** `gsap.config({ force3D: false })` and a warm pass `tl.seek(tl.duration()).seek(0)` before `window.__timelines['main'] = tl`. Without them frames carry 1-LSB noise between renders. Reel Director does neither today.
4. **Canvas text** (brandField, dotCondense word mode, embeddingCloud, epicycleDraw) draws in the fallback font until the face loads. Load the faces, then repaint the current time (re-dispatch `hf-seek`). Set `ctx.font` before `measureText`.
5. **Layer images** (`brandField.logo` URL, `hexMosaic` / `embeddingCloud` `images`) load once and draw only when decoded. `await stack.ready()` before the first frame; `bindHF` repaints when they land.
6. **One WebGL context per GL layer.** Each core overlay kind and each fx2 kind opens its own WebGL2 context. Chrome caps live WebGL contexts per page (commonly 16; past that the oldest is lost). This is my note, not in the pack docs. Keep one global finishing stack, use Canvas2D kinds (backgrounds, K2D) per cutaway, and `stack.dispose()` calls `loseContext`.
7. **Plate-based effects** (bloom, halation, chroma, lens, diffusion) only exist in the Finisher. A DOM composition cannot do them.
8. **No double finishing.** One grain, one vignette, one grade (`lintOverlayStack`). A look replaces the grade.
9. **Banding:** dark vignettes and soft gradients band after x264. Keep grain above them (that is the stack order) and keep meshGradient `grain` ≥ 0.02. `eyes/banding` fix: `upload-safe` grain, or encode at CRF 18 or lower.
10. **`bars` on 9:16** (`ratio` 2.39) would paint huge black bars; `eyes` flags unplanned bars. Don't.
11. **meshGradient and contrast:** keep type contrast checked over the brightest blob. hologramBeam is screen-blended, so it vanishes on white plates.
12. **GPU-gradient snapshots** can differ by 1/255 between identical runs (Canvas2D GPU path). Compare against a same-conditions baseline, not by hash.
13. **Grades are starting values** judged on synthetic stills. Re-judge on the real takes; `hyperframes grade-compare` helps.
14. **Missing modules fail silently in a render.** Run `hyperframes validate` and look at a still.

---

## 8. Progress bar (retention furniture)

- **Pack part:** `title.progressBar` in `type/gfx/editorial.js`, params `{ total: 30, chapters: [], edge: 'top', height: 8 (px at 1080; scaled by H/1080, so 14 px on 1920), accent: '#4A18ED', track: 'rgba(255,255,255,0.25)' }`.
  - It fills `clamp((t - at) / total)` linearly.
  - Mount: `import { mountGfx, bindHF } from './assets/mp/type/gfx/index.js'; bindHF(mountGfx(el, [{ id: 'title.progressBar', at: 0, dur: T, params: { total: T, accent: ACCENT, chapters: [...] } }], { W: 1080, H: 1920 }));`.
  - Pass `dur: T`: the part defaults to `dur` 30 and would disappear after 30 s plus 6 frames.
  - Needs the 31-file `type/gfx` closure (561 KB).
- **Simpler and equally seek-safe in Reel Director's classic script:**
  - HTML: `<div id="progress" style="position:absolute;left:0;top:0;width:100%;height:12px;background:rgba(255,255,255,.25)"><div id="progress-fill" style="height:100%;background:ACCENT;transform-origin:0 50%;transform:scaleX(0)"></div></div>`
  - Timeline: `tl.fromTo('#progress-fill', { scaleX: 0 }, { scaleX: 1, duration: DUR, ease: 'none', immediateRender: false }, 0);`
  - Chapter ticks are static divs at `left: (t / DUR * 100)%`.
- **Placement:** the top edge sits under the platform header on Reels and TikTok, and the bottom edge under the app's own scrubber and caption band. Verify in the app. It is furniture, not text, so the 269-1248 px text safe band does not apply strictly. Put it above grain (brand/UI layer).

---

## 9. Recommended defaults for a high-quality talking-head reel

1. **Grade `documentary`** (pack RECIPE H) as an SVG filter on `#cam`, or one look instead (e.g. `matte-cool` for tech/SaaS, `teal-orange-soft` for lifestyle) when the brand calls for it. Never both. Never on captions or brand.
2. **`vignette`** `{amount: 0.15-0.2, roundness: 1}` above cutaways and below captions.
3. **`grain`** `{stock: 'upload-safe'}` (survives re-encode) or `'digital-soft'` (template default), on top.
4. **Progress bar**, plain GSAP `scaleX`.
5. **Cutaway and title-card backgrounds**, windowed:
   - `meshGradient` (palette matched to the caption colour, `grain` 0.04);
   - `dotGrid` with `hole` behind statement text;
   - `auroraRibbon` for the single "solution" or pivot beat (dark; 22 ms/frame);
   - `gridTunnel` for a tech beat.
   - One field per scene.
6. **End card:** `brandField` (`reveal: 'iris'` or `'wipe'`, the real logo URL, then `await ready`), held ≥ 1.8 s, with a `sfx/hit/brand_field_slam` or `sfx/logo` sting.
7. **Accents, sparingly:**
   - `invertFlash` on one punchline (≤ 3 per second, ≤ 3 frames);
   - `confetti` `burstAt` on a win;
   - `arWave` / `arRing` with `beats` from the word timings under a voice-only cutaway;
   - leaks only as a windowed, opacity-scaled tonal-break accent.
8. **Avoid by default:** Finisher, bars, scanlines, vhs, burnEdge, dust, paper (retro-only looks); lens flares and fog over faces; more than one hero light effect per shot.
