# motion-pack `type/` (type-captions group): map for Reel Director

Pack root: motion-pack (a clone of the public repo; read-only here).
Skill: `skills/motion-pack/SKILL.md` (+ `references/apis.md` "Type", `references/gotchas.md` "Type and captions").
Everything below was read from source on 2026-10-20 and the key behaviours were checked in headless Chrome
(scratch probe: `scratch-type-captions/probe.mjs`, `probe2.mjs`, `probe3.mjs`; sheets in `scratch-type-captions/out/sheet-*.png`).
No file in either repo was modified, and no pack test was run (they write `last-run.json` into the repo). Recorded results: `type/tests/last-run.json` 28/28 pass, `cards-last-run.json` 29/29 (15 Oct).

---------------------------------------------------------------------------------------------------

## 0. TL;DR for a 1080x1920 talking-head reel

| need | use | how it is driven |
|---|---|---|
| word-by-word captions (karaoke / pill / emphasis / clean) | `type/captions.js` `chunkWords` + `type/dom.js` `mountCaptions` + `bakeCaptions` | baked into the ONE paused GSAP timeline (`tl.set` per changed frame) |
| captions WITH emoji pops, or one-word "impact" captions | `type/render-canvas.js` `drawCaptions` on a full-frame `<canvas>` | repaint on `hf-seek` (pure function of t) |
| hook / title text | `type/presets.js` presets via `dom.js` `mountType` + `bakeType` (maskRise, scaleSlam, outlineFill, blurIn, ...) | baked into the GSAP timeline |
| lower third, title card, sticker, CTA, follow button, reply card, one-word slam | `type/gfx/index.js` `mountGfx(root, items, {W,H,platform})` | repaint on `hf-seek` |
| sound for each graphic | `gfxCues(id, {at, params, dur})` / `sfxFor(id)` -> `sfx/<cat>/<name>` -> `sfx/manifest.json` id `snd.<cat>.<name>` -> `sfx/library/...wav` | `<audio>` per cue, anchor on frame F+1 |
| fonts | Manrope Variable (200-800), IBM Plex Mono SemiBold, STIX Two Text (+Italic); all OFL 1.1, in `templates/_shared/fonts/` | `@font-face` + `document.fonts.load` before building / first frame |

---------------------------------------------------------------------------------------------------

## 1. Files and exports (type/)

| file | lines (minified-ish) | exports that matter |
|---|---|---|
| `captions.js` | 55 | `normalizeWords(words)`, `chunkWords(words, opts)`, `CAPTION_STYLES` (karaoke, impact, emphasis, pill, clean), `captionFrame(chunks, t, style, {icons, iconMap, popIconFrames})`, `lintCaptions(chunks, style, opts)` |
| `dom.js` | 71 | `mountType(container, spec, {fontPx, font, H})`, `stateToVars`, `bakeType(tl, m, spec, {t0, dur, fps})`, `driveType(m, spec, {t0, dur})`, `mountCaptions(root, chunks, style, {W, H, platform, font, box})`, `bakeCaptions(tl, cm, chunks, {t0, dur, fps})`, `driveCaptions(cm, chunks, {t0, dur})`, re-export `iconSVG` |
| `render-canvas.js` | 74 | `DEFAULT_FONT`, `layout`, `drawType(g, spec, t, {W, H})`, `drawCaptions(g, chunks, t, style, {W, H, platform, box, font, icons, iconMap})` |
| `presets.js` | 96 | `PRESETS` (15), `PRESET_IDS`, `unitStates(spec, unitTexts, t)`, `holdTime(text)`, `lintType(spec)`, `lintPiece(specs)`, `SHOWN`, `mergeState` |
| `icons.js` | 39 | `ICONS` (17 owned vector icons, 100 box), `iconPath`, `drawIcon(g, id, cx, cy, size, {color, progress, rot, t, seed})`, `iconSVG(id, {color, size, lineW})`, `KEYWORDS`, `iconFor(word, extra)`, `scribbleCircle`, `scribbleUnderline` |
| `safezones.js` | 30 | `SAFE`, `PLATFORMS`, `safeRect(platform, W, H)`, `captionBox(platform, W, H, {lines, fontPx, lineHeight, gap, anchor})`, `lintRect(rect, platform, W, H)`, `lintCaptionStyle({fontPx, lines, maxCharsPerLine, maxWords}, W, H)` |
| `ease.js` | 49 | `E` (enter, hero, exit, move, soft, cam, pop, lin, sine, expoOut, quint), `seg`, `lerp`, `clamp`, `env`, `windowEnv`, `mulberry32`, `sines`, `SPRING`, `spring`, `springSettle`, `springTrack` (identical copy in layers/ and camera/) |
| `gfx/index.js` | registry | `GFX`, `GFX_IDS`, `renderSVG(id, t, {at, dur, params}, {W, H, platform, seed})`, `renderInner`, `mountGfx(root, items, {W, H, platform, seed})`, `bindHF(stack, {t0})`, `GFX_SFX`, `sfxFor(id)`, `gfxCues(id, {at, params, dur})`, `uiCues`, `measure`, `setGlyphSource`, `STICKER_NAMES`, `REACTIONS`, `MOTIONS`, layout + draw-on helpers |
| `gfx/core.js` | contract | `life(t, at, dur, inF, outF)`, `ctxFor(W, H, platform)` (`s = H/1080`; default platform = `reels` on tall, `wideTitle` on wide), `anchor(pos, ctx, w, h)`, `measure()`, `textW()`, `srcOf()` (honesty label) |
| `manifest.json` | 147 KB | `{module:'type', version:'1.0.0', components:[217]}`: 126 gfx, 56 sticker, 15 kinetic-preset, 5 caption-style, 5 layout, 3 card-system, 2 engine, 2 renderer, 1 icon-pack, 1 rules, 1 glyph-system. Each gfx row carries `sfx {id, offset_f, gain_db}`, `dur_s`, `in_frames`, `out_frames`, default `params`, `tags`, `demo`. |

The modules are plain ES modules, self-contained inside `type/` (the only `..` import is `gfx/* -> ../ease.js, ../safezones.js`). No third-party code. Copy `type/*.js` and `type/gfx/*.js` (keep the folder shape) into the project, e.g. `assets/mp/type/` (this is exactly what `templates/_shared/compose.mjs stage()` does).

## 2. Input format: words.json

`normalizeWords` accepts any of `{w|word|text, s|start, e|end, emph?}` in SECONDS (Whisper `transcript.json` words work as is; verified: `{word:' Hi', start, end}` and `{text, start, end}` both chunk). It trims, drops non-finite entries, sorts by `s`, forces `e >= s + 0.05`, and trims overlaps (`prev.e = max(prev.s + 0.04, next.s)`).
`emph: true` marks an emphasis word (emphasis style colours + pops it; RD's `emphasis` cue maps 1:1 onto it).
The pack's template contract (`templates/talking-head/words.json`): `{ "source": "...", "words": [{w, s, e, emph?}] }`. The VO gate (`gateProblems`) refuses entries not shaped `{w, s, e}` in order.
**Times must be COMPOSITION time** for the DOM/canvas caption paths (chunk times are composition seconds in every renderer since 2026-10-15; `t0` only sets the bake window). Reel Director's `timeline.json` already has per-shot words `{w, s, e}` in output time (`timeline_summary`), so feed those (concatenated over shots) straight in.
Exception: `caption.sceneBubble` word times are LOCAL to the part's `at` (subtract `at`).

## 3. Caption engine (`captions.js`)

`chunkWords(words, { maxWords = 3, maxChars = 18, lines = 2, maxGap = 0.6, breakOn = /[.?!]$/, breakOnComma = false, tail = 0.06 })`
-> `[{ words:[{w,s,e,emph}], s, e, text, index }]`. New chunk when maxWords is reached, the line budget `maxChars * lines` would overflow, the gap > maxGap, or the previous word ended a sentence. Each chunk's `e = min(lastWord.e + tail, next.s)` (no overlap).
Example: `[Hello 0-0.4, there. 0.45-0.9, Next 2.0-2.3]` -> `["Hello there." 0-0.96], ["Next" 2-2.36]`.

`CAPTION_STYLES` (size = px at 1080 wide on 9:16):

| id | mode | size / weight | look | timing |
|---|---|---|---|---|
| `karaoke` | chunk | 72 / 800 | white, active word `#FFD400` + scale 1 -> 1.12 in 4 f, unspoken words 0.55 opacity, spoken 0.78; dark stroke 0.06 em + shadow | chunk pops in 6 f (scale 0.88 -> 1, opacity x3) |
| `impact` | single | 120 / 900, UPPERCASE | ONE word at a time, slam 1.25 -> 1 in 4 f; emph word in accent | no chunk pop |
| `emphasis` | chunk | 72 / 800 | all words visible; `emph` words turn `#FF3B6B` and pop 1.12 in 5 f once spoken | chunk pop 6 f |
| `pill` | chunk | 70 / 800 | accent pill `#4A18ED` behind the active word, white text, scale 1.04 | chunk pop 6 f |
| `clean` | chunk | 54 / 600 | documentary, no word animation | 5 f fade |

A style is a plain object: customise with a spread, e.g. `{ ...CAPTION_STYLES.karaoke, accent: '#00E0FF', size: 76, popIn: 0 }`. Keys: `size, weight, upper, color, accent, inactive, activeScale, emphScale, popFrames, stroke, shadow, mode ('chunk'|'single'), popIn (s), fade, pill, pillText, slam`.

`captionFrame(chunks, t, style)` -> `null` or `{ chunk, index, words:[{i, text, active, spoken, opacity, scale, color, y, bg, emph}], icons:[{id, wordIndex, progress, seed}], style }`. Pure function of t.
`lintCaptions(chunks, style, {maxWords 4, maxCharsPerLine 18, lines 2, maxWps 5})` -> list of strings (words > 4, chars > 36, chunk < 0.25 s, > 5 words/s, overlap).
Rules baked in (README): 2-4 words per chunk, active word = the spoken word, never caption across a > 0.6 s gap or a sentence end, <= 2 lines of <= 18 chars on 9:16, 64-80 px on 9:16, caption lead 0 (never before the voice).

### Measured in headless Chrome (1080x1920, conservative safe zone, demo sentence)
- All five styles bake and seek deterministically (backward-then-forward seek = straight seek: `seekStable true` for all 5).
- Tween counts for a 7.4 s, 9-chunk track: karaoke 636, impact 570, emphasis 321, pill 636, clean 216 (~85 tweens/s worst case; a 60 s reel ~5k `tl.set`s, fine).
- Caption box (conservative): x 65-960, bottom 1224 (24 px above the safe bottom 1248), centre x **512, not 540** (the conservative rect is asymmetric: left 65, right 120). Karaoke/emphasis box y 1054-1224, impact 941-1224.
- `lintCaptionStyle` flags impact (120 px) and clean (54 px) as outside 64..80 px: expected, the lint is advisory.

### Bugs / gotchas found (not in the pack's docs)
1. **One blank frame at the start of every chunk** (karaoke, emphasis, pill, clean). Chunk opacity is `clamp(seg(t - c.s, 0, popIn) * 3)`, which is 0 on the chunk's first frame. Back-to-back chunks therefore blink: frame 131 chunk 4 visible, frame 132 chunk 5 at opacity 0.00, 133 at 0.50, 134 at 1.00 (`clean` dips over ~3 frames: 0.00, 0.13, 0.61). Fix without touching the pack: pass `{ ...style, popIn: 0 }` (verified: frame 132 -> 1.00; the word-level active pop still runs; the chunk scale-pop is lost).
2. **`impact` in the DOM path is broken for multi-word chunks.** `mountCaptions` lays every word of the chunk out in a flex row and only sets inactive words to opacity 0, so the visible word keeps its slot: "THING" sat on line 1, x 412-879, off-centre and higher than "THIS". Fix: chunk with `maxWords: 1` for impact (verified centred: THIS x 374-651, THING 279-746, TELLS 328-698), or use the canvas renderer (centres each word), or `caption.oneWordSlam`.
3. **Words disappear in inter-word gaps.** `impact` shows a word only while `s <= t < e`, so every gap in real speech is a blank frame (frame 131 above: 0.00). Karaoke loses its highlight in gaps. Before chunking, close small gaps: for consecutive words with `next.s - w.e < 0.3`, set `w.e = next.s`.
4. **The DOM caption path draws NO emoji pops.** `captionFrame` computes `icons`, but `dom.js` `capVars` ignores them. Only `drawCaptions` (canvas) draws them (verified: "fast," -> bolt, "free," -> burst12, popping 8 f above the word in the accent colour).
5. `drawCaptions` does not clear the canvas: `g.clearRect(0, 0, W, H)` before every call.
6. The demo/talking-head template does NOT use `type/captions.js` (its config says `caption: null = built-in karaoke ... TODO adapter`); `templates/_shared/adapters/type.mjs` registers presets and `type.*` gfx only. So captions.js in HyperFrames is proven by the pack's tests (`type.test.mjs` "caption bake within 2%") and by this probe, not by a shipped template render.

## 4. Three ways to put type into a Reel Director composition

Reel Director today: one root `#root[data-composition-id=main]`, `#cam` wrapper (zoom tweens) holding `<video class="clip take">`s, captions as `.clip` divs with per-word `fromTo`s, overlay/cutaway `.clip`s, sfx/music `<audio>`, one classic `<script>` that builds `tl` and sets `window.__timelines["main"] = tl`.

### Staging (once per compile)
```
<project>/assets/mp/type/*.js          <- motion-pack-public/type/*.js
<project>/assets/mp/type/gfx/*.js      <- motion-pack-public/type/gfx/*.js
<project>/assets/fonts/Manrope-Variable.ttf, IBMPlexMono-SemiBold.ttf (+ STIXTwoText*.ttf only if type.paramReadout is used)
```
compose.mjs hard-links these (its comment: "HyperFrames serves only the project dir"); RD already symlinks media into `assets/`, so use the same `asset()` helper or a copy (~1 MB of JS + 0.3 MB of fonts). Probe page that exercised exactly this layout: `scratch-type-captions/site/index.html`.

### Head
```html
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
@font-face { font-family: "Manrope"; src: url("assets/fonts/Manrope-Variable.ttf") format("truetype"); font-weight: 200 800; }
@font-face { font-family: "IBM Plex Mono"; src: url("assets/fonts/IBMPlexMono-SemiBold.ttf") format("truetype"); font-weight: 600; }
#caps, #gfx, #capcv { position: absolute; inset: 0; pointer-events: none; }   /* full-frame hosts, OUTSIDE #cam so zooms don't scale them */
</style>
```
Body order inside `#root`: `#cam` (takes) -> cutaways/overlays -> `<div id="gfx" class="clip" data-start="0" data-duration="T" data-track-index="4">` -> `<div id="caps">` (or `<canvas id="capcv" width="1080" height="1920">`) -> `<audio>`s.
Do not put `z-index` on an `#fx` host that carries blend-mode overlays (skill gotcha). Never put a CSS `transform` on an element GSAP also tweens (`gsap_css_transform_conflict`).

### Script (module; build after fonts, register LAST)
```html
<script type="module">
import { chunkWords, CAPTION_STYLES, lintCaptions } from './assets/mp/type/captions.js';
import { mountCaptions, bakeCaptions, mountType, bakeType } from './assets/mp/type/dom.js';
import { drawCaptions } from './assets/mp/type/render-canvas.js';
import { mountGfx, gfxCues } from './assets/mp/type/gfx/index.js';
const W = 1080, H = 1920, T = /* root data-duration */ 30, FPS = 30;
const WORDS = /* [{w, s, e, emph}] in composition seconds, from timeline.json */ [];
gsap.config({ force3D: false });
await Promise.all([document.fonts.load('800 72px Manrope'), document.fonts.load('600 40px "IBM Plex Mono"')]); await document.fonts.ready;
const tl = gsap.timeline({ paused: true });
/* ... RD's own tweens (cam zooms, overlays) go here as today ... */

// A) DOM captions baked into the same timeline (karaoke / pill / emphasis / clean)
const words = WORDS.map((w, i, a) => ({ ...w, e: a[i + 1] && a[i + 1].s - w.e < 0.3 ? a[i + 1].s : w.e }));  // close small gaps
const chunks = chunkWords(words, { maxWords: 3, maxChars: 18 });
const style = { ...CAPTION_STYLES.karaoke, accent: '#FFD400', popIn: 0 };                         // popIn 0 = no blank frame per chunk
const cm = mountCaptions(document.getElementById('caps'), chunks, style, { W, H, platform: 'conservative' });
bakeCaptions(tl, cm, chunks, { t0: 0, dur: T, fps: FPS });
console.info(lintCaptions(chunks, style));

// B) OR canvas captions (emoji pops; correct one-word impact), repainted per seek
// const g = document.getElementById('capcv').getContext('2d');
// const paint = (t) => { g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H); drawCaptions(g, chunks, t, CAPTION_STYLES.karaoke, { W, H, platform: 'conservative', icons: true }); };
// window.addEventListener('hf-seek', (e) => paint(e.detail.time)); paint(window.__hfThreeTime || 0);

// C) gfx parts (lower third, stickers, CTA ...), repainted per seek
const items = [
  { id: 'lowerThird.softPill', at: 0.4, dur: 2.4, params: { name: 'Alex Doe', role: 'Founder, Example Co', initials: 'AD', pos: 'tl' } },
  { id: 'sticker.place', at: 5.0, dur: 1.2, params: { name: 'fire', at: [0.78, 0.32], size: 0.6 } },
  { id: 'type.commandPill', at: T - 2.6, dur: 2.0, params: { text: 'example.com', prompt: '>', size: 60 } },
];
const gfx = mountGfx(document.getElementById('gfx'), items, { W, H, platform: 'conservative' });
window.addEventListener('hf-seek', (e) => gfx.render(e.detail.time)); gfx.render(window.__hfThreeTime || 0);
const cues = items.flatMap((it) => gfxCues(it.id, { at: it.at, params: it.params, dur: it.dur }));   // [{t, id:'sfx/..', why}] -> compile-time sfx (better: compute in Python from the same table)

tl.seek(tl.duration()).seek(0);          // warm pass (skill gotcha: 1-LSB noise without it)
window.__timelines['main'] = tl;          // register only after the build (HyperFrames rule)
</script>
```
Notes:
- Module scripts are deferred; register the timeline at the end of the async build (HyperFrames: "register only after the build completes"; `window.__timelines` is created by the runtime). If RD keeps its classic script, move the `__timelines` assignment into the module.
- `hf-seek` (`e.detail.time`, plus `window.__hfThreeTime`) is dispatched by HyperFrames 0.8.142 on every seek even with a GSAP timeline present: the pack's `demo-type-layout` and `demo-r6-type` templates use exactly this and have rendered MP4s in `templates/*/out/`.
- `gfxCues` sound times are composition seconds; resolve the id as in section 9.
- `driveCaptions(cm, chunks, {t0, dur})` is the zero-tween alternative to `bakeCaptions` (applies the same state from `hf-seek`).
- For a gfx-only page without any GSAP timeline the root needs `data-no-timeline` (motion-stack `references/2d.md`); not the case for RD.

## 5. Kinetic presets (titles, hooks) via `mountType` + `bakeType`

15 presets (`PRESETS`, numbers in frames at 30 fps):

| preset | unit | dur / stagger | look | tone |
|---|---|---|---|---|
| maskRise | word | 14 / 4 | rise 0.6 em inside a line mask, E.hero | calm-sharp (headline, premium) |
| charRise | char | 12 / 2 | char version | calm-sharp |
| wordStagger | word | 16 / 3 | opacity + rise + 6 px blur | neutral |
| charStagger | char | 12 / 1.5 | opacity + rise + scale 0.92 | kinetic-soft |
| blurIn | line | 18 / 5 | blur 24 px -> 0, scale 1.04 -> 1 | calm-soft (end card) |
| scaleSlam | word | 6 / 15 | 1.35 -> 1 in 6 f, 8 px shake over 4 f, blur first 2 f, one word per beat | kinetic-sharp (hook, CTA) |
| typewriter | char | 2 f per char, +6 f after `.,?!`, caret blinks 15 f | neutral |
| trackingCollapse | line | 20 / 6 | tracking 0.35 em -> 0 | calm-soft |
| weightMorph | word | 18 / 3 | wght 300 -> 800 (Manrope is variable) | calm-sharp |
| wipe | line | 12 / 4 | clip left -> right | neutral |
| flipSplit | line | 16 / 3 | rotateX -90 -> 0 | kinetic-sharp |
| elasticPop | word | 0.6 s / 3 | spring, zeta 0.38 (27% overshoot) or `params.zeta 0.7` (4.6%) | kinetic-soft |
| scramble | char | resolves at 8 f + 1.2 f/char | glyph decode | techy: NOT bakeable (use `driveType` or canvas) |
| glitchSplit | line | 8 | RGB split on `params.hits` | deconstructed |
| outlineFill | word | 30 / 5 | outline (0.022 em) 7 f, holds to f 15, fills f 15-27 | calm-sharp |

Spec: `{ preset, text | lines:[...], at, out, unit?, stagger?, dur?, params?, ease?, outReverse?, noExit? }` (times composition s). `out` defaults to `inDone + holdTime(text)`; exits are 30% faster than entrances.
```js
const box = document.getElementById('hook');   // positioned by CSS (left/top/width/text-align/color) inside the root
const spec = { preset: 'maskRise', lines: ['Your website', 'can talk'], at: 0.2, out: 2.4 };   // lines = one mask per line
const m = mountType(box, spec, { fontPx: 140, H: 1920, font: { weight: 800, family: 'Manrope, sans-serif', tracking: -0.035, lineHeight: 1.02 } });
bakeType(tl, m, spec, { t0: 0, dur: T, fps: 30 });
```
- To hold without an exit, the pack's own adapter uses `out: 1e9` (setting `noExit` still zeroes opacity once q >= 1: a known bug reported in `adapters/type.mjs`). Inside a timed `.clip`, HyperFrames hides it at the clip end anyway.
- Without `lines`, the whole text is ONE `.mp-line` and the browser wraps it; the mask then covers the whole block (verified: "Your website can talk" at 140 px wraps to 2 lines in an 895 px box). Pass `lines` for per-line masks.
- `fontPx` is in output px (no automatic 9:16 scaling in `mountType`); blur scales by `H/1080`.
- Accent words: the adapter recolours units matching `<em>` in the source; with `mountType` directly, set `m.units[k].el.style.color` after mounting.
- Rules: hold >= 9 fully formed frames, <= 3.5 words/s, at most two tone families per piece (`lintType`, `lintPiece`). Mask-rise frames mid-reveal look clipped by design: judge the hold frame.
- Through the pack adapter instead: `MP.type(tl, 'type/maskRise', '#el', { at, dur, fps, out: true, H })` (needs `assets/mp/pack.mjs` + `adapters/type.mjs`; the element's computed font is used). Not needed for RD.

## 6. gfx parts (SVG, `type/gfx/`): contract

Each part: `{ tags, dur (default hold s), inF, outF (entrance/exit frames @30), d (defaults), svg(L, p, ctx) }`.
`life(t, at, dur, inF, outF)`: visible from `at` to `at + inF/30 + dur + outF/30`. **`dur` is the HOLD, not the length**: to end on a cut, pass `dur = span - (inF + outF)/30` (skill gotcha; multi-voice-doc `supers.edgeF`).
`renderSVG(id, t, {at, dur, params}, {W, H, platform})` -> full-frame `<svg>` string ('' when off). `mountGfx(root, items, {W, H, platform})` -> `{ host, render(t) }` (one `<svg>` host, items = `[{id, at, dur?, params?}]`). `bindHF(stack, {t0})` = `addEventListener('hf-seek')` + first paint (note: it calls `render(t - t0)`).
Params merge over defaults key by key; numbers clamped by `gfx/limits.js` + `safe.js saneParams` (NaN/Infinity -> default). Defs ids are namespaced per item. Unknown id throws `unknown gfx <id>` at draw time (`check_ids.py` does NOT scan gfx ids).
**Scale on 9:16: `ctx.s = H / 1080 = 1.78`** for the editorial/social/sticker parts, so a 1080x1920 frame draws them 1.78x bigger than on 16:9 (only the round 4/5 and r6 parts size from the shorter side and shrink to fit). Text widths are estimated (`textW`, 0.56 em/char) in editorial/social/ui parts, measured (`measure()`) in kinetic/r3/r45/r6 parts (fonts must be loaded first).
`ctxFor` default platform: `reels` on tall frames (top 220, bottom 420 -> y1 = 1500), `wideTitle` on wide. Pass `platform: 'conservative'` to match the caption box.

### 6a. Lower thirds (`gfx/editorial.js`, `doc.js`, `ui-trace.js`)
| id | params (defaults) | in/out f, dur | sound |
|---|---|---|---|
| `lowerThird.cleanBar` | name, role, pos 'bl', accent '#4A18ED' | 14/10, 3 s | `sfx/whoosh/swish_s` +1 f, -2 dB |
| `lowerThird.boldBlock` | same (uppercase name block) | 16/10, 3 s | same |
| `lowerThird.accentRule` | + color | 18/10, 3 s | same |
| `lowerThird.softPill` | + initials 'MR' (creator style) | 12/9, 3 s | same |
| `lowerThird.newsBar` | + tag 'LIVE', ticker, speed 160 | 12/9, 4 s | `sfx/stinger/bump` |
| `lowerThird.neonBorder` | accent '#7CF7FF' | 18/9, 3 s | swish_s |
| `lowerThird.docSuper` | name, role, pos 'tl', condense 0.8, size 84, scrim 0.55 | 4/6, 2.6 s | `sfx/tx/cut_tick` |
| `lowerThird.personalTag` | name, role, personal, chip {initials 'MR', href, icon}, pos 'bl', tierAt 0.3, scale | 12/9, 3.6 s | swish_s at 0, `sfx/ui/pop` at tierAt |
`pos`: 'bl' | 'br' | 'tl' | 'tr' | 'bc' | 'tc' | 'c' | [x, y] fractions; anchored inside the platform safe rect.
Measured on 1080x1920 (sheet `out/sheet-gfx.png`):
- cleanBar default (reels) box 60,1258 -> 765,1500: BELOW the conservative safe bottom (1248) and under where Reels UI sits; with `platform:'conservative'` 65,1006 -> 770,1248, which COLLIDES with the caption band (1054-1224). Use `pos: 'tl'` on talking heads (softPill tl: 65,269 -> 833,454, clean).
- boldBlock with "Alexandria Montgomery" overflows to x 1703 (estimated widths, no shrink): keep names <= ~12 chars on 9:16 or use softPill/cleanBar.
- personalTag prints the default chip initials "MR" unless `chip: {initials}` is passed.
- Name text at 9:16 is 54 x 1.78 = 96 px, role 53 px.

### 6b. Title cards and hooks
| id | what | key params | 9:16 notes |
|---|---|---|---|
| `title.chapterCard` | full-frame dark card, mono kicker + rule + title | kicker, title, bg, accent (18/12 f, 2 s) | title is 72 x 1.78 = 128 px with NO size param or fit: "Record yourself once" overflowed (x -124..1204). Keep titles <= ~11 chars or use verbCard |
| `title.verbCard` | one giant word settles onto the first word of a smaller line; gradient sweep between chapters; fits the safe rect (shrink only) | words [{big, rest}] (<=12), chapterDur 2.4, settleAt, sweepDur, colors, ground '#07060B', ink | full-frame own ground; fits on 9:16 |
| `title.timeCard` | comedic "A LITTLE LATER..." sunburst card | text (`|` = line break), colors, rays, spin | full-frame |
| `type.glowWord` | word on a breathing multicolour halo | text, size 150, colors, halo, blur, breathe | fine on 9:16 (size 220 -> 47..1033 px) |
| `caption.oneWordSlam` | one word per beat slams 1.35 -> 1 with shake, last word in accent | words [{w, at}] (local s), size 1, hold 0.5 | font = 190 x 1.78 x size = 338 px: "TYPING." overflowed both edges. Use size ~0.4-0.5 on 9:16 (fit: size <= 880 / (chars x 0.62 x 338)) |
| `caption.replyCard` | "You asked:" question card (FAQ hook) | kicker, q, accent | fine (top band) |
| `caption.cinematic`, `caption.bilingual`, `caption.meme` | subtitle line / two-language / meme top-bottom | line / primary+secondary / top+bottom | Devanagari falls back to a system font |
| `caption.sceneBubble` | words appear on their own timestamps in a bubble beside the speaker, "Captured" tick, optional dock | words (LOCAL times), anchor [x,y] or track, side, speaker, ai | fine; clamped to safe rect |
| `caption.speakerTag` | captions with speaker chip + TTS badge | speaker, badge, lines [{t, e, text}] | only for synthetic voice (disclosure) |
| `title.progressBar`, `title.recDot`, `title.countdown321` | HUD furniture | total/chapters, label, from | |
Kinetic SVG type (`type.marquee`, `type.bleedWord`, `type.accentSwap`, `type.commandPill`, `type.flankWords`, `type.behindSubject` (needs YOUR matte), `type.electricOutline` chapter numerals, `type.textOnPath`, ...) also resolve as `type/<name>`; see `type/README.md` round 3-6 tables.

### 6c. End card / CTA
| id | what | params | sound |
|---|---|---|---|
| `type.commandPill` | outlined pill draws on around typed monospace (developer CTA, URL) | text (<=120), prompt '$', typeAt 0.55, cps 16, drawAt, size 46, pos [0.5, 0.5], ink, accent | `sfx/ui/slide` + `sfx/ui/type_key` per key (thinned to 70 ms) |
| `social.followButton` | Follow -> Following with a cursor click | label, done, pos 'bc', clickAt 0.8, accent, cursor | `sfx/ui/success` at +25 f |
| `title.partnerLockup` | "A x B" balanced marks | placeholder marks only unless `licensed: true` | `sfx/hit/soft` |
| layers `brandField` (layers module, `layers/canvas2d.js`, mounted with `layers/overlay.js mountStack`) | full-bleed brand colour, logo slot or placeholder mark + name, one line, reveal cut/iris/wipe, soft settle | at, color, ink, name, line, logo, reveal, settle | `sfx/hit/brand_field_slam` (saas bundle) |
At 9:16 `type.commandPill` at the default size 46 is small (pill 278..802 px wide, text ~46 px): use `size` 60-70 for a phone. Skill/virality rules: soft CTA at 60-70% of runtime, hard CTA end card in the last 2.5 s, held >= 1.8 s after motion settles; the link goes in the platform button / post copy (the end card stays clean; URL on the card is the norm for builder audiences); on a looping short replace the end card with a small tag at 0.8 opacity outside the bottom 35%; quiet hold on the end card is a first-class ending (explainers hold 4-9 s).

### 6d. Emoji / icons / stickers
- `icons.js`: 17 OWNED vector icons (burst8, burst12, star, spark, heart, flame, bolt, thumb, play, speech, tag, check, cross, arrow, wave, zigzag, bracket); fill icons pop (E.pop, 8 f), stroke icons draw on and wobble. `KEYWORDS` map (case-insensitive bare word): fire/hot/trending/viral -> flame, love/loved/favorite -> heart, like/great -> thumb, yes/done/correct -> check, free -> burst12, sale/price/cheap/discount/deal -> tag, fast/instant/power/speed -> bolt, new/magic/ai/smart -> spark, best/top/quality/five -> star, no/never/stop/wrong -> cross, watch/demo/video -> play, say/talk/voice/ask -> speech. Extend with `iconMap` (`{word: iconId}`). Rendered only by the canvas caption path (drawn 1.35 em above the word, 1.15 em big, accent colour or #FFD400 when the accent is white).
- Stickers: `sticker.place` (56 owned SVG stickers: 12 faces + 44 objects, incl. diya, rangoli, kite, chai, sale, new, live, free), `reaction.place` (semantic names laugh/love/wow/... -> placeholder faces), `reaction.burst` (14 rising reactions). Motions popBounce, wiggle, float, shake, orbit, spin, pulse, rise. Size = 180 x c.s x size px (320 px on 9:16 at size 1: use 0.4-0.7). Sound `sfx/ui/pop` / `sfx/cartoon/boing`.
- Real emoji: `setGlyphSource(name => svgMarkupIn100Box | null)` plugs a licensed set into `reaction.*`. Allowed: Fluent Emoji (MIT) / Noto Emoji images (Apache-2.0) fetched by `scripts/fetch-external.sh` (pinned, checksummed, ORIGIN.txt); NOT Apple Color Emoji (not licensed), NOT OpenMoji (CC BY-SA). The pack vendors no emoji files. A render that shows a fetched set is not CC0 (licence notice required).
- Call-outs for emphasis words: `callout.underline` (scribble), `callout.scribbleCircle`, `callout.handArrow` (box in frame fractions), sound `sfx/paper/rustle`.

### 6e. Numbers on screen (honesty)
`counter.countUp | wheel | statCard | ring | priceSlash` print `source: placeholder data` until you pass a real `source` (blank falls back). Never show an unsourced stat (skill hard rule 6).

## 7. Safe zones (`safezones.js`, px at 1080x1920 / 1920x1080)
| platform | top | bottom | left | right |
|---|---|---|---|---|
| conservative (union, default for captions) | 269 | 672 | 65 | 120 |
| tiktok | 150 | 480 | 60 | 140 |
| reels | 220 | 420 | 60 | 120 |
| shorts | 140 | 380 | 60 | 120 |
| ytAd | 200 | 500 | 60 | 120 |
| metaStory | 250 | 340 | 60 | 60 |
| wideTitle / wideAction (16:9) | 54 / 38 | 54 / 38 | 96 / 67 | 96 / 67 |
All tall rows are `verify: true` (sources conflict). Conservative safe rect: x 65-960, y 269-1248. `captionBox('conservative', 1080, 1920, {lines: 2, fontPx: 72})` = {x0 65, x1 960, y0 1054, y1 1224, cx 512}.

## 8. Fonts (shipped, licences, headless Chrome)
| file | font | licence | size |
|---|---|---|---|
| `templates/_shared/fonts/Manrope-Variable.ttf` (also `objects/kit/fonts/`) | Manrope 4.505, variable wght 200-800 | SIL OFL 1.1 (`OFL-Manrope.txt`) | 164,700 B |
| `IBMPlexMono-SemiBold.ttf` | IBM Plex Mono 2.3 SemiBold (600) | OFL 1.1, RFN "Plex" (`OFL-IBMPlexMono.txt`) | 140,216 B |
| `STIXTwoText.ttf`, `STIXTwoText-Italic.ttf` | STIX Two Text 2.13, wght 400-700 | OFL 1.1 (`OFL-STIXTwo.txt`) | 418,956 / 454,368 B |
Unmodified; videos made with them are not bound by the OFL; ship the licence text next to the font if you redistribute the font files.
Headless Chrome (Google Chrome stable via puppeteer-core 25.14, this machine): `document.fonts.check` true for `800 72px Manrope`, `600 40px "IBM Plex Mono"`, `italic 40px "STIX Two Text"`; measured "Captions that sell" at 72 px: Manrope 630.5 px vs fallback sans 600.1 (real face applied); Plex 777.6 px = exactly 18 x 0.6 em (real face). Gotchas: a face is fetched on first use, so load every weight you draw (`document.fonts.load('800 72px Manrope')`, the Plex weight) BEFORE the first frame or canvas/`measure()` frames differ by seek order; repaint the current time when fonts land (demo-r45-type dispatches `hf-seek` with the last time). Every pack default font stack starts with Manrope, so RD's `system-ui` look changes once captions/gfx are mounted.
Not shipped: no emoji font, no Devanagari font (bilingual caption falls back to a system font), no condensed face (docSuper condenses Manrope by scaleX).

## 9. Sound pairing (feeds RD's sfx `<audio>`)
`sfxFor(id)` -> `{id: 'sfx/<cat>/<name>', offset_f, gain_db}` (longest-prefix table `GFX_SFX`); `gfxCues(id, {at, params, dur})` -> `[{t (composition s), id, why}]` per action (typing keys, clicks, pops ...). Resolve `sfx/<cat>/<name>` -> manifest id `snd.<cat>.<name>` in `sfx/manifest.json` (`sounds[]`), file `sfx/<file>` (e.g. `sfx/whoosh/swish_s` -> `sfx/library/whoosh/snd.whoosh.swish_s.wav`, anchor 133.58 ms; `sfx/hit/punch` -> `library/impact/snd.hit.punch.wav`, anchor 6.92 ms). Skill rule: a cue for visual frame F puts its anchor sample on (F + 1) x 48000 / fps, i.e. `<audio data-start = t + 1/fps - anchor_ms/1000>`; library peak -6 dBFS; level via the mixer, never hand gain.

## 10. Skill guidance that applies (RECIPE H, talking head)
Layer order fixed: autocut silences > 0.5 s (120 ms breath) -> captions 2-4 words, active word highlighted, 64-80 px on 9:16, <= 2 lines -> B-roll 35-50% coverage, inserts 1.2-3 s leading the line by 150 ms -> punch-ins 1.12 on emphasis, max 1 per 4 s, alternate framing on jump cuts -> a lower third -> music ducked 9 dB under the voice -> SFX on emphasis, punch-ins, B-roll, lower third -> grade `documentary`. Hook text on screen by 0.3 s, <= 7 words (<= 4 on the poster frame). Captions on every spoken sentence (works on mute). QA: <= 18 chars per line, <= 2 lines, active word = spoken word, reads at 360 px wide; `eyes/look.py` wants `plan.texts [{text, t, box, fontPx, role, fg}]` to check text boxes. Emphasis scale 1.15 can collide with neighbours on long words. Never use ffmpeg `subtitles=` (no libass): burn captions through type/.

## 11. Recommended defaults for Reel Director
1. Captions: DOM `mountCaptions` + `bakeCaptions` into the single timeline, style `{...CAPTION_STYLES.karaoke, popIn: 0, accent: <brand accent>}`, `chunkWords(words, {maxWords: 3, maxChars: 18})` after closing gaps < 0.3 s, platform `conservative`, host outside `#cam`. Map RD `emphasis` cues to `emph: true` and use `emphasis` or `pill` as alternative looks.
2. If emoji pops are wanted: switch the caption layer to the canvas renderer (`drawCaptions` on hf-seek, `icons: true`, own `iconMap`), not both.
3. One-word hype sections: `impact` with `maxWords: 1` (+ closed gaps), or `caption.oneWordSlam` with `size` ~0.45 on 9:16.
4. Lower third: `lowerThird.softPill` (creator) at `pos: 'tl'`, `platform: 'conservative'`, `dur = span - 21/30`, explicit `initials`; sound `sfx/whoosh/swish_s` +1 f.
5. Hook title: `mountType` maskRise (premium) or scaleSlam (hype) with explicit `lines`, 120-150 px, in the top band (y 270-640).
6. End card: `type.commandPill` (URL, size 60-70) or layers `brandField`, last 2.5 s, held >= 1.8 s after settle; `social.followButton` as a soft CTA at 60-70%.
7. Load Manrope 800 (+ any other weights used) and Plex Mono 600 before building; warm pass; register `__timelines.main` last.
