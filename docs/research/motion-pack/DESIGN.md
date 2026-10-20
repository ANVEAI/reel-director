# Reel Director x motion-pack: integration design

Status: design only. Nothing in Reel Director (RD) or motion-pack (pack, `P/` below) was modified.
Grounding: RD `src/reel_director/{schema,compiler,timeline,audio,timing,cleanup,textnorm}.py` and `studio/runtime.py` as of 2026-10-20 03:00; `examples/demo/script.json`; `work/demo/final2/timeline.json` (used for the worked example); the six scratch notes in this folder (`transitions.md`, `cuts-camera.md`, `layers-looks.md`, `type-captions.md`, `audio.md`, `qa-templates.md`); the motion-pack skill (`SKILL.md` Recipe H, hard rules, gotchas); and direct reads of pack code: `transitions/catalog.json`, `transitions/aliases.json`, `transitions/lib/tx-core.js txWindow`, `templates/_shared/txplan.mjs`, `templates/_shared/adapters/transitions.mjs`, `camera/{cam2d,bake}.js`, `type/{captions,dom,safezones}.js`, `type/gfx/index.js`, `layers/overlay.js`, `music/mixer.py`, `music/manifest.json`, `sfx/manifest.json`, `sfx/bundles.json`, `sfx/mpaudio/sweeteners.py`, `cuts/cutgen.py`, `cuts/patterns.json`, `eyes/manifest.json`; the installed HyperFrames 0.8.177 CLI help and runtime bundle, and the `hyperframes-audio` skill.

Items marked **[verify]** are design choices that no probe has proven yet. Each one has a test in section 8.

---------------------------------------------------------------------------------------------------------------------------

## 0. Decisions at a glance

| # | decision | why (evidence) |
|---|---|---|
| D1 | The creator writes only `shots[].line` (plus optional `style.preset`). A deterministic **auto-director** (`director.py`, text only) adds word-anchored cues. A **planner** (`planner.py`, timing-aware) rations them against real word times and builds one frame-exact `edit_plan.json`. | Cues already anchor to words (schema.py), so text-only direction works before recording. Rationing (4 s punch gap, interrupt ladder, windows) needs real times. |
| D2 | `edit_plan.json` is the single contract between all later stages: compiler (picture), mixdown (sound), QA (eyes/ears `plan.json` + `words.json`). | Lets four work packages proceed in parallel (section 9). The pack's own rule is "one plan.json drives the picture, the sound and the checks". |
| D3 | Composition = `#stage` (applyDom root, `isolation: isolate`) > `#cam` (outer handheld, baked) > `.txl` (applyDom layer, untimed) > `.fr` (per-segment framing, baked) > `<video class="clip take" muted>`. Cutaways are `.txl` siblings of `#cam` inside `#stage`. Captions, titles, gfx, grain, progress and end card come after `#stage`. | Proven separately in scratch renders: transitions proof (`scratch-transitions/proof`, 0.8.142) and camera lint+snapshot (`scratch-cuts-camera/comp`, 0.8.177). The two-wrapper camera removes the 9:16 edge exposure (cuts-camera G2). |
| D4 | Soundtrack is **mode A**: `music/mixer.py` bakes VO + bed + SFX into one `mix.wav` at -14 LUFS-I / -2.0 dBTP with AAC probes. Every take `<video>` is muted. Delivery remuxes `master.wav` as AAC 256k over the rendered picture. | This is the pack's only validated HyperFrames sound path. It gives measured cue levels, ducking and AAC-safe peaks. Muting the takes also removes the doubled-speech problem of stretched transition clips (transitions.md 3.2). |
| D5 | A **mode B** (HyperFrames-native ducking) is kept as fallback and as the requested "ducking via HyperFrames audio features". It uses `data-audio-group` voice/sfx/music, a Python-computed `data-automation` volume lane on the bed, an optional `data-fx-carve` against group `voice`, and a root `truepeak` chain. | These attributes exist in the installed 0.8.177 runtime (grep: `data-automation` 15 files, `data-audio-group` 6, `data-fx-carve` 2, `truepeak` 6). The pack has not validated them, so they are not the default. |
| D6 | The page JS is a **static runtime module** (`assets/rd/reel.mjs`, source `src/reel_director/web/reel.mjs`). The compiler emits only DOM plus one `<script type="application/json" id="rd-plan">`. | It makes the JS unit-testable and keeps the Python compiler to data. A dynamic `import()` lets a failed pack import paint a red error card instead of a silent no-layer render (layers-looks gotcha 14). |
| D7 | Pack JS and fonts are staged by **hard link** (fallback symlink, then copy) into `<project>/assets/mp/...` at the pack's own relative layout. The file list is the computed static-import closure of the entry modules. | Costs no disk on the same APFS volume (9.6 GB free). Mirrors `templates/_shared/compose.mjs stage()`. The closure walk fails at compile time instead of failing silently at render. |
| D8 | Rendering pins `npx --yes hyperframes@0.8.142` (the pack's proven version) via `hf.py:HF_VERSION`. Flags: `--crf 23` for review, `--crf 18` for delivery, `--experimental-fast-capture=false`. Moving the pin to 0.8.177 is a one-line change after the A/B test in section 8 passes. | The transition windows, hf-seek layers and type gfx were rendered on 0.8.142. 0.8.177 has been verified for lint+snapshot only, though its runtime does contain the `hf-seek` dispatch. Fast capture self-verify failed on DOM windows and fell back automatically, doubling capture. |
| D9 | Quality gate = static lints + mixer report + `hyperframes lint/validate` + render-log greps + stills + **eyes** + **ears** in subprocesses, with pack thresholds (critic rows ≥ 8, no fail). There is a bounded auto-fix loop of at most 2 rounds. | Pack production gate 6 and critic.md. eyes/ears always exit 0, so RD must parse the JSON. |

---------------------------------------------------------------------------------------------------------------------------

## 1. Pipeline

```
script.json (lines, optional style.preset)                                      creator
   │ schema.parse_script (v2, back-compatible)
   ▼
director.direct(script)  ──► reel/directed.json   (text-only, deterministic: every cue + "auto": true + "why")
   │                        Studio shows it before recording; creator may pin/suppress
   ▼
timeline.build_timeline(script, takes)            (existing: best take, keep segments, word times)
   │
   ▼
planner.plan(timeline, directed, preset, pack)   ──► reel/edit_plan.json   (frame-quantised; THE contract)
   ├─ quantise clips to frames
   ├─ beatsync: pick bed, rotate loop, trim post-rolls so shot cuts land on beats (never touching words)
   ├─ transition windows (txWindow/txPlan/span port), camera, captions, titles, cutaways, gfx, end card
   ├─ interrupt-ladder lint + relief, cue sheet (SFX pairing, levels), eyes plan.json + words.json
   ▼
mixdown.run(plan)  ──► reel/assets/mix.wav (+ .cache/mix/master_report.json, stems)   (mixer subprocess)
   ▼
compiler.compile(plan) ──► reel/index.html + reel/assets/{mp,rd,fonts,media}/ (hard links)
   ▼
hf.lint + hf.validate  ──► fail fast on lint errors / JS errors / missing assets
   ▼
hf.render (npx hyperframes@0.8.142, --crf 18, fast capture off) ──► renders/reel.mp4 (+ render.log)
   ▼
audio.deliver(reel.mp4, master.wav) ──► renders/reel-master.mp4   (copy video, AAC 256k of master.wav, faststart)
   ▼
qa.gate(project) ──► qa/report.json  (eyes + ears + mixer + render log + stills) ──► Studio "Quality" panel
```

New CLI subcommands (WP5): `direct`, `plan`, `mix`, `qa`, plus `build`, which runs the whole chain. Existing `compile` keeps its flags and gains `--preset`, `--no-auto`, `--mix baked|live|none`. The Studio `_build()` becomes prep → compile (direct+plan+mix+compile) → lint/validate → render → deliver → qa.

---------------------------------------------------------------------------------------------------------------------------

## 2. `script.json` schema additions (v2, back-compatible)

### 2.1 New and changed top-level fields

| field | type | default | meaning |
|---|---|---|---|
| `style.preset` | `"clean" \| "punchy" \| "hype"` | `"punchy"` | Selects the director and planner rule table (section 3.2). |
| `style.accent`, `style.text`, `style.bg` | hex | as today | `accent` is used for chips, progress, gfx accents and the caption underline. `bg` is used for cards. |
| `style.look` | grade name (`layers/presets/grades.js`) or look name (`layers/presets/looks.js`) | preset (`documentary`) | One grade **or** one look, applied to `#cam` only. |
| `style.captions` | `{style: "pill"\|"karaoke"\|"clean", size: 64..80, plate: bool, upper_emphasis: bool}` | preset | Caption overrides. |
| `style.creator` | `{name, role, initials, handle}` | none | Enables the lower third (`lowerThird.softPill`) and the soft CTA (`social.followButton`). |
| `style.brand` | `{name, url, logo}` (logo path relative to script) | none | End card: `brandField` when `logo` is set, otherwise `type.commandPill` with `url`. |
| `style.grain`, `style.vignette`, `style.progress`, `style.handheld` | | preset | Finishing overrides. |
| `music` | `{"id": "music/<bed id>"}` \| `{"mood": "warm"}` \| `{"src": "file.wav", "bpm": 120}` \| `false` | preset | A pack bed by id (`music/bed_lofi_warm_loop8`), by mood, a custom file (legacy `src`, grid from `bpm` if given), or no music. Legacy `volume` is ignored in mode A. |
| `mix` | `{mode: "baked"\|"live", duck_db: 12, bed_rel_vo_lu: -2, ceiling_db: -2.0}` | preset | Soundtrack mode and levels (section 6). |
| `director` | `{enabled: true, seed: int}` | `{enabled: true}` | `seed` defaults to `crc32(title)`. It only breaks ties; output never uses a clock or `random`. |
| `end_card` | `{line?, url?, hold: 3.0}` \| `false` | auto | CTA end card, 3.0-4.5 s (the eyes `endcard_hold_s` spec). |
| `fps` | int | 30 | Must be in {24, 25, 30, 48, 50, 60} when `mix.mode == "baked"` (the mixer asserts `48000 % fps == 0`). |

### 2.2 New shot fields

| field | meaning |
|---|---|
| `role` | `"hook" \| "body" \| "cta"`. Auto: shot 0 = hook, last shot = cta. |
| `energy` | 0..1 override of the director's energy estimate. |
| `title` | Hook or chapter title text. The auto hook title is derived when it is absent (section 3.4, R-H2). |
| `transition_in` | `{"id": "transitions/<name>", "params": {...}, "reason": "ENERGY"}` for the shot boundary *into* this shot (shot i > 0). Any name in `P/transitions/aliases.json` resolves (`whip`, `scale-punch`, `zoom-through`, `push`, `swipe-up`, `linear-blur`, `blur-cross`, `glitch`, `flash`, `dip-to-black`, `cut`, `smash`, ...). Only kind `dom` ids get a window; `cut`/`smash` are hard cuts. |
| `auto` | `false` disables all auto cues for the shot, or `{"punch": false, "cutaway": false, "chip": false, "sfx": false, ...}` disables per kind. |

### 2.3 Cue types

Existing types keep their meaning: `overlay`, `sfx`, `zoom`, `cutaway`, `emphasis`. New and extended:

| type | required | optional | renders as |
|---|---|---|---|
| `punch` | `at` | `scale` (multiplier, default preset), `hold` (s, then a 0.25 s settle-back), `kind: "punch"\|"crash"` | `cam2d.punchIn2d` / `crashZoom` on the segment's `.fr` |
| `zoom` | `at` | `scale`, `hold` | **alias of `punch`** (no more `#cam` fromTo) |
| `sfx` | `at` and one of `id` / `src` | `level` (dB re voice), `anchor: "start"\|"end"` (which word edge = visual frame F) | mixer cue. `id` is `sfx/<cat>/<name>` (resolves to `snd.<cat>.<name>`). `src` becomes a custom `file:` sound. `lead` is ignored (the anchor contract replaces it). |
| `cutaway` | `at`, `text` | `until`, `hold`, `bg: {kind, params}`, `tx_in`, `tx_out` (transition ids), `preset` (type preset) | full-frame card over the continuing take, windowed Canvas2D background |
| `overlay` | `at`, `text` | `hold`, `kind: "chip"` | top-band chip, pop with `snd.ui.pop` |
| `title` | `at`, `text` | `preset` (`maskRise`, `scaleSlam`, `blurIn`, ...), `out` | `type/dom.js mountType + bakeType` |
| `lower_third` | `at` | `name`, `role`, `initials` (else from `style.creator`) | `lowerThird.softPill`, pos `tl` |
| `callout` | `at` | `kind: "underline"\|"circle"` | **reserved, not v1**: needs word boxes the compiler does not have |
| `sticker` | `at`, `name` | `pos` [x, y], `size` (0.4-0.7) | `sticker.place` |
| `stat` | `at`, `value`, `source` | `kind: "countUp"\|"statCard"` | `counter.*`. **`source` is required** (pack hard rule 6; parse fails without it) |
| `accent` | `at`, `kind: "flash"\|"shake"\|"confetti"\|"invert"` | | flash = `invertFlash` layer (≤ 1 per piece), shake = `shake2d`, confetti = `confetti burstAt` |
| `hold` | `at` | `ms` (default 450) | beat hold: `lock2d` window after the word plus post-roll extension |
| `riser` | `at` | `id` (default preset) | riser ending one frame before the word's frame |
| `suppress` | `at`, `what` | | removes an auto cue of kind `what` anchored on this phrase |

Parsing rules added to `schema._parse_cue`:
- An unknown transition or sound id fails at load time, checked against `aliases.json` and `sfx/manifest.json`. Pack JSON is loaded through `mp/pack.py`; with no pack installed, id checks are skipped with a warning.
- `stat` without `source` fails.
- `sfx` needs exactly one of `id` / `src`.

### 2.4 Example (`examples/demo/script.json`, v2)

```json
{
  "title": "Reel Director demo",
  "width": 1080, "height": 1920, "fps": 30,
  "style": {
    "preset": "punchy",
    "accent": "#FFD400",
    "creator": {"name": "Alex Doe", "role": "Founder", "initials": "AD", "handle": "@alexdoe"},
    "brand": {"name": "Reel Director", "url": "reeldirector.app"}
  },
  "music": {"mood": "warm"},
  "mix": {"mode": "baked"},
  "shots": [
    {
      "id": "hook",
      "line": "Most creators waste three hours editing one reel.",
      "cues": [
        {"type": "sfx", "at": "waste", "src": "media/whoosh.wav"},
        {"type": "emphasis", "at": "waste"},
        {"type": "overlay", "at": "three hours", "text": "3 HRS / REEL"},
        {"type": "zoom", "at": "one reel", "scale": 1.14}
      ]
    },
    {
      "id": "turn",
      "line": "What if the edit was finished before you even pressed record?",
      "transition_in": {"id": "transitions/whip", "params": {"dir": [1, 0]}, "reason": "ENERGY"},
      "cues": [
        {"type": "cutaway", "at": "finished", "until": "record", "text": "EDIT FIRST. RECORD LAST.",
         "bg": {"kind": "meshGradient", "params": {"palette": "dusk", "grain": 0.04}}, "tx_in": "transitions/push"},
        {"type": "sfx", "at": "finished", "id": "sfx/ui/pop"}
      ]
    },
    {
      "id": "cta",
      "line": "Read the script, hit record, and the reel builds itself.",
      "cues": [
        {"type": "emphasis", "at": "builds itself"},
        {"type": "sfx", "at": "builds", "id": "sfx/ui/pop"}
      ]
    }
  ],
  "end_card": {"line": "Edit first. Record last.", "hold": 3.0}
}
```

The minimal form, which the auto-director turns into a complete reel:

```json
{"title": "Reel Director demo", "style": {"preset": "punchy"},
 "shots": [{"id": "hook", "line": "Most creators waste three hours editing one reel."},
           {"id": "turn", "line": "What if the edit was finished before you even pressed record?"},
           {"id": "cta",  "line": "Read the script, hit record, and the reel builds itself."}]}
```

Back-compat: every v1 script parses unchanged. Mappings: `zoom` → `punch`, `sfx.src` → `file:` sound. `music.src` keeps working; a `music.volume` is honoured only in mode B.

---------------------------------------------------------------------------------------------------------------------------

## 3. Auto-director (lines only to full cue plan, deterministic)

### 3.1 Two passes

1. **`director.direct(script) -> Script`** (text only; runs at `validate`, in Studio before recording, and at compile).
   - Adds cues with `"auto": true`, `"why": "<rule id>"` and, for rationed kinds, `"candidate": true` plus `"score"`.
   - Explicit cues are never removed or moved. An auto cue of the same kind on an overlapping phrase is dropped (explicit wins).
   - Output `reel/directed.json`: sorted keys, floats to 3 decimals. Byte-identical for the same script, preset and pack rev.
2. **`planner.plan(...)`** (timing-aware).
   - Picks which candidates fire under the cadence and ladder rules.
   - Resolves frames and windows, and writes `edit_plan.json`.
   - Only the planner knows seconds. Every rule below says which pass enforces it.

Determinism rules: no `random`, no clock. Ties break by word index, then `zlib.crc32(f"{title}|{shot_id}|{rule}")` (never Python `hash()`, which is salted per process).

### 3.2 Style presets (`presets.py`, data only)

| knob | `clean` (calm founder/explainer) | `punchy` (default) | `hype` |
|---|---|---|---|
| energy bias | -0.15 | 0 | +0.15 |
| punch cadence N / hard min gap | 7 s / 4 s | 5 s / 4 s | 4 s / 4 s |
| punch scale (`punchIn2d to`), frames | 1.08, 4 | 1.12, 4 | 1.12, 4 (hook: `crashZoom to 1.2, returnAt +0.6 s`) |
| ladder on jump cuts (`.fr` base scale) | 1.0 / 1.08 / 1.0 / 1.15 | 1.0 / 1.15 / 1.0 / 1.25 (patterns.json) | 1.0 / 1.15 / 1.0 / 1.25 |
| shot-boundary palette by E (≥ 0.75 / ≥ 0.5 / ≥ 0.3 / < 0.3) | linearBlur{angle 0} / blurCross / blurCross / cut | whip{blurMax 0.05} / scalePunch{center eyes} / blurCross / cut | whip{blurMax 0.05} / scalePunch / linearBlur / scalePunch |
| into the CTA shot | blurCross | swipeUp | swipeUp |
| cutaway in / out | blurCross / blurCross | push{dir [0,1]} (zoomThrough if E ≥ 0.75) / zoomThrough{center eyes, scaleIn 1.3, scaleOut 3} | zoomThrough / zoomThrough |
| internal jump cut promoted to scalePunch (L1 slot) | never | ≤ 1 per 8 s | ≤ 1 per 5 s |
| L3 accents | none | none | `glitch` at a cut ≤ 1.5 s (hook only) + `flash{peak 0.7}` on a number reveal at a cut, ≤ 1 per 9 s |
| cutaway coverage budget (auto) | ≤ 12% of content | ≤ 25% | ≤ 30% |
| number chips (auto overlay) | off | ≤ 1 per shot | ≤ 1 per shot |
| hook title preset | maskRise | maskRise | scaleSlam |
| captions | pill, plate, 72 px | pill, plate, 72 px | pill, plate, 72 px, upper |
| look / vignette / grain | documentary / 0.15 / upload-safe | documentary / 0.18 / upload-safe | documentary / 0.20 / upload-safe |
| handheld level (`handheld2d`) | 0.3 | `subtle` (0.4) | 0.6 |
| progress bar | off | on | on |
| keyword pops (`snd.ui.pop` / `snd.ui.blip`) | off | numbers + emphasis | all stressed words, rationed 1 per 1.5 s |
| jump-cut tick (`snd.tx.cut_tick`) | off | on | on |
| bed list (ordered, crc32 picks among the first 3 that fit) | lofi_warm, ambient_pad, lofi_jazz | uplift_corporate, acoustic_folk_pluck, documentary_marimba, corporate_bright | tech_pulse, corporate_bright, deep_house |
| duck_db / bed_rel_vo_lu / ceiling_db | 12 / -4 / -2.0 | 12 / -2 / -2.0 | 10 / -1 / -3.0 |
| riser into CTA | `snd.riser.tape_up` | `snd.riser.noise_1bar` | `snd.riser.noise_1bar` |
| cutaway background | meshGradient{palette ink, grain .04} | meshGradient{palette dusk, grain .04}; dotGrid{bg = style.bg, color = accent, hole .22} for list cards | gridTunnel{bg = style.bg, color = accent}; auroraRibbon for the single pivot card |
| cutaway beat pulses (scale 1.03 → 1 on beats) | off | off | on |
| soft CTA (`social.followButton` at 65% runtime) | off | on if `creator.handle` | on if `creator.handle` |

### 3.3 Text features (`lexicon.py`, deterministic)

- **Numbers.** A word is numeric when its `norm_tokens` contain any of `_ONES`, `_TENS`, `hundred`, `thousand`, `million`, `billion`, `percent`, or the raw text contains a digit, `%`, `$`, `₹`, or `x` after a digit. A **number phrase** is the maximal run of numeric words plus one following unit word from `{hours, hrs, minutes, days, weeks, months, years, percent, x, times, k, users, dollars, rupees}`. Display text converts number words to digits and upper-cases (for example "three hours" becomes `3 HOURS`); captions keep the script text.
- **Power words.** never, only, stop, mistake, wrong, secret, nobody, everyone, free, instantly, fast, easy, best, worst, actually, truth, waste, why, how, finally, without, before, after, itself.
- **CTA lexicon.** follow, comment, save, share, subscribe, link, try, download, sign up, dm, visit, join, get.
- **Contrast markers** (cutaway candidates). but, instead, the truth, here's, what if, the problem, the secret, stop, imagine.
- **Stressed-word rank** per shot: explicit `emphasis` words > numbers > power words > the longest content word of length ≥ 6 > the first content word. Function words (the, a, to, of, and, in, on, is, was, you, your, it, that) are never stressed.
- **Shot energy.**
  - Base: hook 0.80, cta 0.60, body 0.50.
  - Adjustments: +0.10 if the line contains `!`; +0.10 if it has a number phrase; +0.05 if it ends with `?`; +0.10 if it has two or more power words; -0.10 if the line is 18 words or more.
  - Then add the preset bias and clamp to [0, 1]. `shot.energy` overrides.

### 3.4 Rules

Each rule is tagged D (director, text) or P (planner, timing). Numbers are 30 fps unless stated.

**Hook (shot role hook)**
- **R-H1 (P) pattern interrupt in the first 1.5 s.**
  - The director emits a `punch` candidate (`why: hook_interrupt`) on the top stressed word, with `alt` = the next 3 ranked words.
  - The planner fires the first one whose start lies in [0.30, 1.50] s.
  - If none does: in hype, a `glitch` window at the first internal jump cut in [0.4, 1.5] s; otherwise a camera-only punch at the word onset nearest 1.0 s; with no word there, at 1.0 s itself.
  - It is the only camera move in the first 1.0 s (virality: at most one camera or layout move in the first second). Sound: `snd.hit.punch` (bundle role `hook_word`); clean uses `snd.tx.scale_punch`.
- **R-H2 (D) hook title on screen by frame 1.** Text selection:
  1. `shot.title` if given.
  2. Else the line, if it has 7 words or fewer.
  3. Else the first clause up to `,.;:?!`, if 7 words or fewer.
  4. Else the first 5 words, minus a trailing function word.
  5. If an explicit or auto chip in the hook shows a number phrase, the title stops before that phrase (no duplicate).

  Layout:
  - Split into at most 2 balanced lines.
  - `fontPx = min(140, floor(895 / (maxLineChars * 0.56)))`; if this is under 96 (the eyes headline floor), the title is dropped and logged.
  - Preset `maskRise` (or `scaleSlam` in hype), `at = 1/fps`.
  - `out` = min(hook end - 0.2, max(at + 0.35 + 0.28 * words, end of the title's words + 0.4), start of the first top-band chip - 0.05).

  Sound: `snd.ui.pop` at F = 1. This gives an audible event by frame 2, which clears mixer lint R10 and ears "first audible event by frame 3".
- **R-H3 (P) frame 0 is in motion.** Handheld is on from frame 0; the title starts at frame 1; a slow push applies when the first segment is longer than 4 s. Eyes wants the first visible change by frame 6.

**Rhythm (all shots)**
- **R-P1 (D+P) punch-in every N seconds.**
  - The director marks every stressed word as a `punch` candidate with a score (rank weight + 0.2 if numeric).
  - The planner walks the timeline. After the last punch at time L, it picks the best-scored candidate starting in [L + N - 1, L + N + 1]. If there is none, it picks the best one in [L + 4, L + N + 2].
  - Exclusions: never within 4 s of another punch (pack `min_gap_s`, crash zooms count); never under a cutaway; never within ±0.2 s of a transition window; never in the end card.
  - Explicit `punch`/`zoom` cues always fire. Breaking the 4 s gap only produces a lint warning.
- **R-P2 (P) zoom cap.** `base * to ≤ CAP`. `CAP = 1.30` when the take's short side is ≤ 1080 px, rising linearly to 1.6 at 2160 px (cuts-camera G10: 1.25 * 1.12 = 1.40 is a visible upscale).
  - If an auto punch lands on a segment whose `base * to > CAP`, the segment's base is re-picked: 1.0 if the previous segment's base is not 1.0, else 1.15.
  - An explicit punch is clamped to `CAP / base`.
- **R-P3 (P) static limit.** No stretch longer than 3.5 s without an L1+ event (virality R4; eyes pacing warns at 3.5 s). Fillers, in order:
  1. A punch candidate (if the 4 s gap allows).
  2. A **settle-back**, `push2d to = 1/punchTo` over 0.5 s, ease `soft`, ≥ 3.5 s after the last punch (counts as L2 "zoom-out reveal").
  3. `push2d lin 1.0 → 1.06` across segments longer than 4 s with no punch (patterns `slow_push`).
- **R-P4 (D) emphasis on numbers.**
  - Every number phrase gets an `emphasis` cue. Emphasis words render UPPERCASE in captions (`captions.upper_emphasis`).
  - Number phrases top the punch rank.
  - punchy/hype add one `overlay` chip per shot with the digit display text (≤ 12 characters) at the phrase, unless an explicit overlay overlaps it.
  - Honesty: a chip only repeats what the creator says. `stat` counters require `source`.
- **R-P5 (D+P) keyword pops.** Emphasis or number words that receive no punch and no chip get `snd.ui.pop`/`snd.ui.blip` (alternating) at the word start, rationed to 1 per 1.5 s (punchy) or 1 per 1.0 s (hype).

**Transitions**
- **R-T1 (D) every shot boundary gets a `transition_in`.**
  - The id comes from the preset palette using E = max(e_prev, e_next), with the reason code ENERGY (whip), EMPHASIS (scalePunch), PLACE (blurCross, linearBlur, swipeUp) or none (cut).
  - The boundary into the CTA shot uses the preset's "into CTA" id.
  - Whips alternate `dir` [1,0] / [-1,0]. After 3 whips in a row the 4th becomes linearBlur{angle 0}.
- **R-T2 (P) feasibility.**
  - `txPlan` clamps (half of each neighbouring segment) plus two RD clamps: `pre ≤ floor(media_in_incoming * fps)` (no sync slip; transitions.md gotcha 14) and `post ≤ floor((src_dur - media_out_outgoing) * fps)`.
  - If `pre + post < 2` the boundary becomes a hard cut with a `todo` entry.
  - `lumaWipe` mattes other than linear/radial are refused at load time (they throw inside onUpdate). `sharedElement` and `spin` are refused for takes.
- **R-T3 (P) internal jump cuts** (from cleanup):
  - Hard cut plus a ladder reframe. The base changes at every cut, which disguises the jump (Recipe H).
  - In punchy/hype, one jump cut may be promoted to `scalePunch{center [0.5,0.38]}` as an L1 slot when no punch is within ±2 s, both sides are ≥ 0.27 s, and the preset rate allows it.
  - Never a dissolve while dialogue continues.
- **R-T4 (P) cutaway in/out.** A cutaway gets the preset's in/out ids, with B = cutaway layer and A = the visible take layer (the reverse on the way out).
  - If the cutaway ends within 3 frames of a shot-boundary window, its end extends to that boundary. The boundary transition then uses the cutaway layer as A (as in the demo).
- **R-T5 (P) interrupt ladder lint.**
  - Levels: punch, scalePunch and ladder reframe are L1; whip, push, zoomThrough, swipeUp, blurCross, linearBlur, cutaway, chip, lower third and settle-back are L2; glitch, flash, smash and confetti are L3.
  - Run `cutgen.lint_interrupts(events, duration)`, loaded from the pack with `sys.dont_write_bytecode = True`.
  - On `major_pair`: downgrade the later L3 to scalePunch.
  - On `fatigue`: downgrade the lowest-priority **auto** L2 in the last rising window. Order: chip, then soft transition, then whip to scalePunch. Repeat until clean, mirroring `cutgen._relieve_fatigue`.
  - Explicit cues are never downgraded; they only warn.

**Cutaways (creator-only B-roll substitute)**
- **R-C1 (D) candidates.** A sentence containing a contrast marker, a list marker ("first", "second", "step", "three things") or a number phrase, in a body shot. Text = the anchored phrase upper-cased, ≤ 6 words, split into ≤ 3 lines of ≤ 12 characters, with number words as digits.
- **R-C2 (P) selection.**
  - Greedy by score under the preset coverage budget.
  - Constraints: start ≥ 2.0 s; ≥ 4 s apart; 1.2-3.0 s long; picture leads the line by 150 ms (`split.broll_lead`); never in the hook's first 1.5 s or in the CTA shot.
  - Card text `fontPx = min(110, floor(830 / (maxLineChars * 0.56)))`, preset `maskRise` (`scaleSlam` in hype), white on the preset background (dark palettes only).

**CTA and furniture**
- **R-E1 (D) end card** unless `end_card: false`. It is a 3.0 s segment appended after the last shot (eyes `endcard_hold_s` [3.0, 4.5]).
  - `brandField{reveal: 'iris', revealDur 0.35, color: accent, ink: '#FFFFFF', name, line, logo}` if `brand.logo` is set; otherwise `type.commandPill{text: brand.url, size 64, pos [0.5, 0.5]}` plus a `blurIn` line.
  - Sound: `snd.logo.hybrid` (bundle `talking_head.end_card`, the only tier-1 cue) at the reveal-complete frame.
- **R-E2 (D) riser into the CTA.** The preset riser with F = the CTA boundary cut frame. The mixer's `anchor_frame_offset -1` makes it end one frame before the transition hit.
- **R-E3 (P) soft CTA.** `social.followButton{label 'Follow', done 'Following', pos 'bc'}` at 0.65 × content runtime, only if `creator.handle` is set, the frame is not under a cutaway, and the preset is punchy or hype. It is dropped if it would sit in the caption band (it uses the `bc` anchor inside the conservative rect: **[verify]** the box against the caption band; drop it on overlap).
- **R-E4 (P) lower third.** One `lowerThird.softPill{pos 'tl', platform 'conservative', initials}` with `dur = 2.4 - 21/30` (hold). It goes in the first top-band slot ≥ 2.5 s that is free of titles, chips and cutaways and starts ≤ 50% of content runtime; otherwise it is skipped.
- **R-E5 (P) top-band scheduler.** The band y 269-640 is one resource. Priority: hook title > explicit overlay > auto chip > lower third. A lower-priority item moves to the next free slot or is dropped (logged).
- **R-E6 (D+P) beat hold.** The last sentence of a shot that ends with `!`, or a sentence of ≤ 6 words following a longer one in the same shot, gets `hold` on its last word.
  - The planner extends that shot's post-roll to ≥ 0.45 s when media allows (`take.duration` and no junk word after) and adds `lock2d [e, e + 0.45]`.

**Sound pairing** (P; the full table is in 6.4). Every visual event above maps to one pack sound id, one anchor frame and one level reference. The planner writes the cue sheet. Rotation lists keep R9 from firing. Every id must exist in `sfx/manifest.json`.

### 3.5 Worked example: the demo, preset `punchy`

Real word times from `work/demo/final2/timeline.json`. Clips are frame-quantised (section 4.2): boundaries 2.63 → f79, 4.12 → f124, 8.41 → f252, 10.62 → f319, 12.55 → f377. The end card runs f377-467, so D = 15.5667 s.

| t (s) / frame | event | rule | sound (mixer frame F, reference, dB) |
|---|---|---|---|
| 0.033 / 1 | hook title `maskRise` "Most creators / waste" (122 px, out 1.60; stops before the "3 HRS" chip) | R-H2, R-E5 | `snd.ui.pop` F1, bed, -10 |
| 1.200 / 36 | punch "waste" ×1.12 (base 1.0). Bar downbeat here (bed rotated, section 6.2) | R-H1 | explicit `file:media/whoosh.wav` F36, voice, -14 (replaces auto `snd.hit.punch`) |
| 1.733 / 52 | explicit chip "3 HRS / REEL" (snapped +2 f to a beat, still inside "three" 1.65-1.99) | R-P4, beat snap | `snd.ui.pop` F52, voice, -14 |
| 2.633 / 79 | jump cut; ladder base 1.0 → 1.15 | R-T3 | `snd.tx.cut_tick` F79, bed, -18 |
| 3.100 / 93 | explicit zoom "one reel" 1.14, clamped to 1.30/1.15 = 1.130 (lint warn: 1.9 s after the previous punch) | R-P2 | none (explicit cue had no sfx) |
| 3.967-4.267 / 119-128, cut 124 | whip dir [1,0], blurMax 0.05, E = max(0.9, 0.55) | R-T1 | `snd.whoosh.whip_pan` F124, voice ("What" starts 4.133), -14 |
| 5.433-5.800 / 163-174, cut 169 | cutaway in: push dir [0,1] (E = 0.55) | R-T4 | `snd.whoosh.swish_s` F169, voice, -16 |
| 5.800 / 174 | explicit `sfx/ui/pop` at "finished" | | `snd.ui.pop` F174, voice, -14 |
| 6.58-8.40 | riser into the CTA (ends f252) | R-E2 | `snd.riser.noise_1bar` F252, bed (window 8.2-8.4 is a gap), -12 |
| 8.167-8.633 / 245-259, cut 252 | swipeUp, cutaway layer → cta-0 (the cutaway end 8.32 s was extended to the boundary) | R-T1 (into CTA), R-T4 | `snd.whoosh.swish_xs` F252, bed, -12 |
| 10.633 / 319 | jump cut; ladder base 1.25 → 1.0 | R-T3 | `snd.tx.cut_tick` F319, bed, -18 |
| 11.333 / 340 | punch "builds" ×1.12 (explicit emphasis, score top; on a beat) | R-P1 | explicit `snd.ui.pop` at "builds" F341, voice, -14 (replaces auto `snd.tx.scale_punch`) |
| 12.567-15.567 / 377-467 | end card `commandPill` "reeldirector.app" + `blurIn` line (no logo given) | R-E1 | `snd.logo.hybrid` F388, bed, +5; `snd.amb.room_tone` F431 until 467, bed, -26 |

Rules that did not fire:
- R-E4: the lower third had no free slot ≤ 50% of runtime; it is skipped and logged.
- R-E3: the content runtime is 12.6 s and 0.65 × 12.6 = 8.2 s falls under the cutaway, so the follow button is dropped.
- R-C2: the turn shot already has the explicit cutaway covering 65% of it, which exceeds the budget, so no auto cutaway.
- Interrupt lint: L-levels [1 @1.2, 2 @1.73, 1 @2.63, 1 @3.1, 2 @4.13, 2 @5.63, 2 @8.4, 1 @10.63, 1 @11.33]. No L3, so no major_pair. The 5 s windows sum to [7, 4] (third window partial), so no fatigue.

---------------------------------------------------------------------------------------------------------------------------

## 4. Planner and the `edit_plan.json` contract

### 4.1 Contract (WP2 writes it; WP3, WP4 and WP5 read it)

```json
{
  "version": 1, "fps": 30, "W": 1080, "H": 1920,
  "duration": 15.5667, "content_end": 12.5667,
  "preset": "punchy", "seed": 1828463711,
  "pack": {"root": "<motion-pack checkout>", "rev": "<git rev-parse HEAD>", "hf": "0.8.142"},
  "style": {"accent": "#FFD400", "ink": "#0B0B0F", "text": "#FFFFFF", "bg": "#0B0B0F", "stage": "#2B2622",
            "look": "documentary", "vignette": 0.18, "grain": "upload-safe", "plate": "rgba(8,8,16,0.62)",
            "capAccent": "linear-gradient(0deg, #FFD400 0 8px, rgba(255,255,255,0.16) 8px 100%)"},
  "fonts": ["800 72px Manrope", "800 122px Manrope", "800 110px Manrope", "600 40px \"IBM Plex Mono\""],
  "segments": [
    {"id": "hook-0", "shot": "hook", "src": "assets/media/hook-1.mp4", "slot": false, "track": 0,
     "pic": {"start": 0.0, "dur": 2.6333, "mediaStart": 0.55},
     "vo":  {"start": 0.0, "dur": 2.6333, "mediaStart": 0.55},
     "vis": [0.0, 2.6333], "base": 1.0,
     "moves": [{"kind": "punch", "at": 1.2, "to": 1.12, "frames": 4}]},
    {"id": "hook-1", "shot": "hook", "src": "assets/media/hook-1.mp4", "slot": false, "track": 1,
     "pic": {"start": 2.6333, "dur": 1.6333, "mediaStart": 5.0033},
     "vo":  {"start": 2.6333, "dur": 1.5, "mediaStart": 5.0033},
     "vis": [2.6333, 4.2667], "base": 1.15,
     "moves": [{"kind": "punch", "at": 3.1, "to": 1.1304, "frames": 4}]},
    {"id": "turn-0", "shot": "turn", "src": "assets/media/turn-1.mp4", "slot": false, "track": 0,
     "pic": {"start": 3.9667, "dur": 4.4333, "mediaStart": 2.6267},
     "vo":  {"start": 4.1333, "dur": 4.2667, "mediaStart": 2.7933},
     "vis": [3.9667, 8.4], "base": 1.0,
     "moves": [{"kind": "push", "at": 3.9667, "dur": 4.4333, "to": 1.06}]}
  ],
  "cutaways": [
    {"id": "cutaway-1", "layer": "L-cutaway-1", "start": 5.4333, "dur": 3.2, "text": "EDIT FIRST. RECORD LAST.",
     "lines": ["EDIT FIRST.", "RECORD LAST."], "fontPx": 110, "preset": "maskRise", "textAt": 5.6667,
     "bg": {"kind": "meshGradient", "params": {"palette": "dusk", "grain": 0.04}, "seed": 5}, "beats": []}
  ],
  "windows": [
    {"key": "whip", "id": "transitions/whip", "a": "#L-hook-1", "b": "#L-turn-0", "startF": 119, "cutF": 124, "endF": 128,
     "start": 3.9667, "cut": 4.1333, "end": 4.2667, "params": {"dir": [1, 0], "blurMax": 0.05}, "reason": "ENERGY", "level": 2, "approx": false, "auto": true},
    {"key": "push", "id": "transitions/push", "a": "#L-turn-0", "b": "#L-cutaway-1", "startF": 163, "cutF": 169, "endF": 174,
     "start": 5.4333, "cut": 5.6333, "end": 5.8, "params": {"dir": [0, 1]}, "reason": "PLACE", "level": 2, "approx": false, "auto": false},
    {"key": "swipeUp", "id": "transitions/swipe-up", "a": "#L-cutaway-1", "b": "#L-cta-0", "startF": 245, "cutF": 252, "endF": 259,
     "start": 8.1667, "cut": 8.4, "end": 8.6333, "params": {}, "reason": "PLACE", "level": 2, "approx": false, "auto": true}
  ],
  "camera": {"eyes": [0.5, 0.38], "handheld": 0.4, "locks": [], "cap": 1.30},
  "captions": {"style": "pill", "overrides": {"size": 72, "inactive": 1, "activeScale": 1.04, "popIn": 0,
                 "accent": "<= style.capAccent", "pillText": "#FFFFFF"}, "plate": true,
               "chunks": [{"index": 0, "s": 0.15, "e": 1.19, "text": "Most creators WASTE",
                           "words": [{"w": "Most", "s": 0.15, "e": 0.61, "emph": false},
                                     {"w": "creators", "s": 0.61, "e": 1.19, "emph": false},
                                     {"w": "WASTE", "s": 1.19, "e": 1.65, "emph": true}]}]},
  "titles": [{"id": "title-hook", "el": "title-hook-in", "start": 0.0, "dur": 1.8,
              "spec": {"preset": "maskRise", "lines": ["Most creators", "waste"], "at": 0.0333, "out": 1.6}, "fontPx": 122}],
  "overlays": [{"id": "overlay-1", "start": 1.7333, "dur": 2.1667, "text": "3 HRS / REEL"}],
  "gfx": [],
  "endcard": {"start": 12.5667, "dur": 3.0, "kind": "commandPill",
              "gfx": {"id": "type.commandPill", "at": 12.6, "dur": 2.4, "params": {"text": "reeldirector.app", "size": 64, "pos": [0.5, 0.5]}},
              "line": {"spec": {"preset": "blurIn", "lines": ["Edit first. Record last."], "at": 13.0, "out": 1e9}, "fontPx": 64}},
  "progress": {"dur": 12.5667},
  "bed": {"id": "music.bed_uplift_corporate_loop8", "file": "music/library/beds/bed_uplift_corporate_loop8.wav",
          "bpm": 112.5, "fpb": 16, "fpbar": 64, "roll_frames": 28, "hero_frame": 36},
  "beats": [4, 20, 36, 52, 68, 84, 100, 116, 132],
  "cues": [
    {"id": "snd.ui.pop", "frame": 1, "ref": "bed", "db": -10, "role": "title_in", "why": "R-H2"},
    {"id": "file:media/whoosh.wav", "frame": 36, "ref": "vo", "db": -14, "role": "explicit", "why": "script"},
    {"id": "snd.whoosh.whip_pan", "frame": 124, "ref": "vo", "db": -14, "role": "tx.whip", "why": "R-T1"},
    {"id": "snd.riser.noise_1bar", "frame": 252, "ref": "bed", "db": -12, "role": "riser", "why": "R-E2"},
    {"id": "snd.logo.hybrid", "frame": 388, "ref": "bed", "db": 5, "role": "end_card", "why": "R-E1"},
    {"id": "snd.amb.room_tone", "frame": 431, "until": 467, "ref": "bed", "db": -26, "role": "room_tone", "why": "R-E1"}
  ],
  "mix": {"mode": "baked", "duck_db": 12, "bed_rel_vo_lu": -2, "ceiling_db": -2.0, "fade_in_ms": 40,
          "automation": [{"frame": 0, "gain_db": 0}, {"frame": 431, "gain_db": 0}, {"frame": 461, "gain_db": -30}],
          "quiet": [{"t": [14.4, 15.5667], "kind": "hold", "why": "end card quiet hold"}]},
  "lint": {"interrupts": {"fail": [], "windows": [7, 4]}, "warnings": ["explicit punch @3.10 is 1.90 s after the previous (min 4 s)"], "todo": []}
}
```

Rules for the contract:
- All times are composition seconds on the frame grid (`k/fps`, 4 decimals). Frames are integers.
- `pic` is the stretched picture (`<video muted>` timing). `vo` is the exact voice range for `vo.wav` and mode-B voice `<audio>`.
- `vis` is the window to bake the segment camera over.
- Cue `frame` is the **visual** frame F. The mixer adds +1 itself, so it is never pre-added.

### 4.2 Frame quantisation (fixes sub-frame clip edges)

For each clip: `q = js_round(out_start * fps)`, `δ = q/fps - out_start`, `media_in += δ`. Then `dur = (q_next - q)/fps`. This keeps source-zero (`start - media_start`) constant, so lip sync holds and the voice moves ≤ 16.7 ms. Every later word time shifts by its clip's δ. `js_round(x) = floor(x + 0.5)` (JS `Math.round`). Python's banker's `round()` must not be used anywhere frame math must match the JS runtime (`round(4.5) == 4` in Python, 5 in JS).

### 4.3 Transition windows: exact port of `txWindow` / `txPlan` / `span` (`mp/txplan.py`)

```python
def tx_window(entry, fps, cut_frame, bpm=None, duration_frames=None):      # == transitions/lib/tx-core.js txWindow
    tm = entry["timing"]
    if duration_frames is not None: n = duration_frames
    elif bpm: n = js_round(tm["beats"] * 60 / bpm * fps)
    else: n = js_round(tm["ms"] / 1000 * fps)
    n = max(tm.get("minFrames") or 2, n)
    pre = js_round(tm["cut"] * n)
    return {"start": cut_frame - pre, "cut": cut_frame, "end": cut_frame - pre + n, "frames": n}

def window_for(boundary, catalog, aliases, fps):                            # == txplan.mjs txPlan + RD clamps
    r = aliases[boundary.tx_name]                                           # {"id","key","params","kind","approx"?}
    if r["kind"] in ("cut", "smash") or r["key"] is None: return None
    if r["kind"] != "dom": return Todo("GL-only: hard cut")
    w = tx_window(catalog[r["key"]], fps, boundary.cut_f)
    pre  = min(w["cut"] - w["start"], boundary.prev_frames // 2, int(boundary.in_media_in * fps))
    post = min(w["end"] - w["cut"],   boundary.next_frames // 2, int(boundary.out_media_left * fps))
    if pre + post < 2: return Todo("shots too short for a window: hard cut")
    return Window(key=r["key"], id=r["id"], params={**r["params"], **boundary.params},
                  startF=boundary.cut_f - pre, cutF=boundary.cut_f, endF=boundary.cut_f + post, approx=r.get("approx", False))
```

Stretching follows `span()`:
- An element ending on a windowed cut gets `dur = end - start`.
- An element starting on it gets `start = window.start`, `dur += pre/fps`, `mediaStart -= pre/fps`.
- Segment layers alternate `track` 0/1, so stretched overlaps never share a track.
- `applyDom` receives the real cut fraction `(cut - start) / (end - start)`.
- Parity test: compare against `node P/templates/_shared/txplan.mjs` on fixtures (section 8).

### 4.4 Camera plan

There are two writers on two elements, never one element:
- **`#cam`** gets `lock2d(handheld2d(c2({}), {level, seed}), locks)`, baked over [0, D] about the centre with `cover: true`. This hides handheld edges exactly (coverScale assumes a centre origin).
- **`.fr` of each segment** gets `c2({scale: base, origin: [0.5, 0.38]})`, then `moves` in order (`punchIn2d`, `push2d`, settle = `push2d to < 1`, `crashZoom`), then `lock2d(locks)`. It is baked over that segment's `vis`.
  - Scale ≥ 1 about an interior origin always covers, so no floor is needed.
  - G2's 31% edge-exposure problem disappears.

The numbers chosen (resolving pack drift G9):
- Ladder: patterns.json 1.0/1.15/1.0/1.25 (punchy, hype).
- Punch: `punchIn2d to 1.12, durFrames 4` (≈ 133 ms; patterns 140 ms; expoOut built in).
- Settle-back: 0.5 s `soft`.
- Slow push: 1.0 → 1.06 `lin`.
- Beat hold: 450 ms.

### 4.5 Captions (`mp/captions.py`, Python port of `type/captions.js`)

1. Words in output time come from all shots. Emphasis words are upper-cased when `upper_emphasis` is set.
2. **Close gaps < 0.3 s** (`w.e = next.s`), because type-captions bug 3 makes words blink out in gaps.
3. Run `normalizeWords` and then `chunkWords(maxWords 3, maxChars 18, lines 2, maxGap 0.6, breakOn [.?!]$, tail 0.06)`, ported line for line. A node parity test checks it.
4. Chunks are emitted with `index`, `s`, `e`, `text`, `words`. The JS calls `mountCaptions` with these chunks directly and never re-chunks, so eyes `plan.texts` and the picture can never disagree.

**Caption colour policy (forced by the eyes contrast model).**
- eyes measures contrast as min(fg vs P5, fg vs P95) of every non-fg pixel in the box and does not credit a stroke. A light accent highlight (for example `#FFD400`) or dimmed inactive words therefore become "backdrop" and fail (< 3:1).
- So captions use style `pill` with:
  - `inactive: 1`;
  - white text, `pillText: '#FFFFFF'`;
  - a dark plate `rgba(8,8,16,0.62)` behind the chunk;
  - the active-word "pill" = `style.capAccent`, a CSS gradient: an 8 px accent underline bar plus a 16% white tint.
- `capVars` sets `background: m.style.accent` through `tl.set`, so any CSS background string works.
- The bar is about 2-3% of the box area, which keeps P95 dark. **[verify]** with eyes on a still.

Boxes for `plan.texts` (tight, inside the plate):
- `fontPx = 72`.
- Lines are a greedy wrap at 18 characters.
- `width = min(895, 0.50 * fontPx * maxLineChars + 52)`, centred at x 512.
- `y1 = 1224 - 12`, `y0 = y1 - lines * 1.18 * 72`.
- The box is then shrunk 6 px per side. That keeps it inside the conservative rect and over plate pixels only.
- The 0.50 em/char estimate comes from Manrope 800 measured at 0.4865 em/char (type-captions section 8).

### 4.6 Other planner outputs

- **Titles, chips, cutaway text and end-card line** become `titles[]` / `overlays[]` / `cutaways[].lines` with explicit `lines` and `fontPx`. Each also produces a `plan.texts` box, estimated at 0.56 em/char and centred in its band.
- **gfx items** (lower third, follow button, commandPill) use measured boxes from `mp/gfx_boxes.json`. WP4 measures this table once, with a snapshot probe per part at 1080x1920 and `platform 'conservative'`. Any id missing from the table gets no `fg` (eyes caps an estimated fg at warn) and a lint warning.
- **`plan.json`** (eyes/ears) and **`words.json`**: section 7.2.

---------------------------------------------------------------------------------------------------------------------------

## 5. Compiler changes (exact emission)

### 5.1 What goes away from today's `compiler.py`

- The `tl.fromTo("#cam", {scale}...)` zoom tweens. `#cam` now has exactly one writer, `bakeGSAP` (cuts-camera G4).
- The per-word caption `fromTo` pairs and the `.caption` divs at `top: 64%`, 82 px, stroke-only. They failed eyes safezones and contrast on demo-week2.
- `data-has-audio="true"` / `data-volume` on takes (they are muted), per-cue SFX `<audio>` and the music `<audio>` (mode A).
- The classic `<script>`. It is replaced by a module that registers `window.__timelines.main` last, after `gsap.config({force3D: false})` and a warm pass (both missing today).

### 5.2 `index.html` (generated; `{...}` = values from the plan)

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080, height=1920" />
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<link rel="stylesheet" href="assets/rd/reel.css" />
<style>:root { --accent: {accent}; --ink: {ink}; --text: {text}; --bg: {bg}; --stage: {stage}; --plate: {plate}; }</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs id="mp-defs"></defs></svg>
<div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920" data-duration="{D}" data-fps="{fps}">
  <div id="stage">
    <div id="cam">
      <!-- one per kept segment; .txl = applyDom layer, .fr = baked framing; the <video> is never styled -->
      <div class="txl" id="L-hook-0"><div class="fr" id="F-hook-0">
        <video id="take-hook-0" class="clip take" src="assets/media/hook-1.mp4" muted playsinline
               data-start="0" data-duration="2.6333" data-media-start="0.55" data-track-index="0"></video></div></div>
      <div class="txl" id="L-hook-1"><div class="fr" id="F-hook-1">
        <video id="take-hook-1" class="clip take" src="assets/media/hook-1.mp4" muted playsinline
               data-start="2.6333" data-duration="1.6333" data-media-start="5.0033" data-track-index="1"></video></div></div>
      <!-- unrecorded shot: same wrappers, a slot card instead of a video -->
      <div class="txl" id="L-cta-0"><div class="fr" id="F-cta-0">
        <div id="slot-cta-0" class="clip slot" data-start="8.1667" data-duration="2.4667" data-track-index="0">
          <div class="slot-inner"><div class="slot-tag">RECORD · cta</div><div class="slot-line">Read the script, ...</div></div></div></div></div>
    </div>
    <div class="txl" id="L-cutaway-1">
      <div id="cutaway-1" class="clip cutaway" data-start="5.4333" data-duration="3.2" data-track-index="3">
        <div class="cut-bg" id="cutaway-1-bg"></div>
        <div class="cut-text" id="cutaway-1-in"></div></div></div>
  </div>
  <div id="fx-mid" class="fx"></div>                                      <!-- vignette (normal blend) -->
  <div id="title-hook" class="clip band" data-start="0" data-duration="1.8" data-track-index="4">
    <div class="title-text" id="title-hook-in"></div></div>
  <div id="overlay-1" class="clip band" data-start="1.7333" data-duration="2.1667" data-track-index="4">
    <div class="chip" id="overlay-1-in">3 HRS / REEL</div></div>
  <div id="gfx" class="clip" data-start="0" data-duration="{D}" data-track-index="5"></div>
  <div id="caps"></div>
  <div id="fx-top" class="fx"></div>                                      <!-- grain (overlay blend): NO z-index/opacity/transform here -->
  <div id="progress"><div id="progress-fill"></div></div>
  <div id="endcard" class="clip endcard" data-start="12.5667" data-duration="3" data-track-index="6">
    <div id="endcard-fx" class="fx"></div><div class="end-line" id="endcard-line"></div></div>
  <audio id="mix" src="assets/mix.wav" data-start="0" data-duration="{D}" data-track-index="9" data-volume="1"></audio>
  <div id="rd-error"></div>
</div>
<script type="application/json" id="rd-plan">{edit_plan JSON with "</" escaped as "<\/"}</script>
<script type="module">
  const P = JSON.parse(document.getElementById('rd-plan').textContent);
  window.__timelines = window.__timelines || {};
  try { const m = await import('./assets/rd/reel.mjs'); await m.build(P); }
  catch (e) {                         // a failed pack import or build paints a red card instead of a silent no-layer render
    const el = document.getElementById('rd-error'); el.textContent = 'REEL BUILD ERROR: ' + (e && e.message); el.style.display = 'flex';
    const tl = gsap.timeline({ paused: true }); tl.set({}, {}, P.duration); window.__timelines.main = tl; console.error(e);
  }
</script>
</body>
</html>
```

Paint order follows the pack stack rule:
1. footage + grade;
2. vignette;
3. story type (titles, chips, gfx, captions);
4. grain;
5. brand/UI (progress, end card).

HyperFrames paints in DOM order. `data-track-index` is display only.

### 5.3 `assets/rd/reel.css` (static, from `src/reel_director/web/reel.css`)

```css
@font-face { font-family: "Manrope"; src: url("../fonts/Manrope-Variable.ttf") format("truetype"); font-weight: 200 800; }
@font-face { font-family: "IBM Plex Mono"; src: url("../fonts/IBMPlexMono-SemiBold.ttf") format("truetype"); font-weight: 600; }
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 1080px; height: 1920px; overflow: hidden; background: var(--bg); }
body { font-family: Manrope, system-ui, sans-serif; color: var(--text); }
#root { position: relative; width: 100%; height: 100%; overflow: hidden; background: var(--bg); }
#stage { position: absolute; inset: 0; overflow: hidden; isolation: isolate; background: var(--stage); } /* applyDom root: its z-50 overlay stays under captions; bg = mean footage colour hides the whip seam band */
#cam { position: absolute; inset: 0; filter: url(#mp-grade); }        /* grade the footage only */
.txl, .fr { position: absolute; inset: 0; }
.take { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: 50% 38%; }
.slot { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
        background: repeating-linear-gradient(135deg, #15151c 0 40px, #1b1b24 40px 80px); }
.slot-inner { width: 80%; border: 4px dashed var(--accent); border-radius: 28px; padding: 56px 48px; }
.slot-tag { color: var(--accent); font-size: 40px; font-weight: 800; letter-spacing: 4px; margin-bottom: 28px; }
.slot-line { font-size: 46px; line-height: 1.3; opacity: 0.85; }
.cutaway { position: absolute; inset: 0; overflow: hidden; background: var(--bg); }
.cut-bg { position: absolute; inset: 0; }
.cut-text { position: absolute; left: 95px; right: 150px; top: 640px; height: 600px; display: flex; align-items: center;
            justify-content: center; text-align: center; color: var(--text); }
.fx { position: absolute; inset: 0; pointer-events: none; }
.band { position: absolute; left: 65px; width: 895px; top: 269px; height: 371px; display: flex; align-items: flex-start; justify-content: center; }
.title-text { display: inline-block; max-width: 895px; text-align: center; color: var(--text); background: var(--plate);
              border-radius: 28px; padding: 14px 30px 20px; }
.chip { display: inline-block; background: var(--accent); color: var(--ink); font-weight: 800; font-size: 76px; line-height: 1.05;
        padding: 18px 40px; border-radius: 24px; box-shadow: 0 14px 36px rgba(0,0,0,.4); }
#gfx, #caps { position: absolute; inset: 0; pointer-events: none; }
.rd-plate { display: inline-flex; flex-wrap: wrap; justify-content: center; column-gap: 20px; max-width: 100%;
            padding: 8px 26px 12px; border-radius: 26px; background: var(--plate); }
#progress { position: absolute; left: 0; top: 0; width: 100%; height: 12px; background: rgba(255,255,255,.22); }
#progress-fill { width: 100%; height: 100%; background: var(--accent); transform-origin: 0 50%; }
.endcard { position: absolute; inset: 0; background: var(--bg); }
.end-line { position: absolute; left: 65px; width: 895px; top: 1080px; text-align: center; color: var(--text); }
#rd-error { display: none; position: absolute; inset: 0; background: #FF0033; color: #fff; font: 800 64px/1.2 Manrope, sans-serif;
            align-items: center; justify-content: center; text-align: center; padding: 120px; }
```

The stage colour `--stage` is the mean RGB of the first take's middle frame:

```
ffmpeg -v error -ss <mid> -i take -frames:v 1 -vf scale=1:1 -f rawvideo -pix_fmt rgb24 -
```

This is the transitions.md mitigation for the whip seam. It is computed at compile time and cached per take hash.

### 5.4 `assets/rd/reel.mjs` (static runtime; the only JS the reel runs)

```js
import { applyDom } from '../mp/transitions/lib/tx-dom.js';
import * as C from '../mp/camera/cam2d.js';
import { bakeGSAP } from '../mp/camera/bake.js';
import { CAPTION_STYLES } from '../mp/type/captions.js';
import { mountCaptions, bakeCaptions, mountType, bakeType } from '../mp/type/dom.js';
import { mountGfx, bindHF as bindGfx } from '../mp/type/gfx/index.js';
import { mountStack, bindHF as bindLayers } from '../mp/layers/overlay.js';
import { toSVGFilter } from '../mp/layers/grade.js';
import { GRADES } from '../mp/layers/presets/grades.js';
import { lookParams } from '../mp/layers/presets/looks.js';

const $ = (id) => document.getElementById(id);
const FONT = { weight: 800, family: 'Manrope, sans-serif', tracking: -0.035, lineHeight: 1.02 };

/* render a Canvas2D stack only inside [start, start + dur] (seek-safe: render is a pure function of u) */
function bindWindow(stack, start, dur, fps) {
  const f = (t) => { if (t < start - 1 / fps || t > start + dur + 1 / fps) return; const u = t - start; stack.render(u, { frame: Math.round(u * fps) }); };
  window.addEventListener('hf-seek', (e) => f(e.detail.time)); f(window.__hfThreeTime || 0); stack.ready().then(() => f(window.__hfThreeTime || 0));
}

export async function build(P) {
  const { W, H, fps: F, duration: D } = P;
  gsap.config({ force3D: false });
  await Promise.all(P.fonts.map((f) => document.fonts.load(f))); await document.fonts.ready;
  const tl = gsap.timeline({ paused: true });

  // 1. one grade or one look, footage only (#cam)
  $('mp-defs').innerHTML = toSVGFilter(GRADES[P.style.look] || lookParams(P.style.look), 'mp-grade');

  // 2. camera: outer handheld about the centre (cover), inner framing per segment about the eyes
  let outer = C.handheld2d(C.c2({}), { level: P.camera.handheld, seed: P.seed % 65536 });
  if (P.camera.locks.length) outer = C.lock2d(outer, P.camera.locks);
  bakeGSAP(tl, '#cam', outer, { t0: 0, dur: D, fps: F, W, H, cover: true });
  const EY = P.camera.eyes;
  for (const s of P.segments) {
    let cam = C.c2({ scale: s.base, origin: EY });
    for (const m of s.moves) {
      if (m.kind === 'punch') cam = C.punchIn2d(cam, { at: m.at, to: m.to, durFrames: m.frames, origin: EY, fps: F });
      else if (m.kind === 'push' || m.kind === 'settle') cam = C.push2d(cam, { at: m.at, dur: m.dur, to: m.to, ease: m.kind === 'push' ? 'lin' : 'soft', origin: EY });
      else if (m.kind === 'crash') cam = C.crashZoom(cam, { at: m.at, to: m.to, frames: 4, origin: EY, fps: F, returnAt: m.returnAt ?? null });
      else if (m.kind === 'shake') cam = C.shake2d(cam, { hits: m.hits, px: 8 });
    }
    if (P.camera.locks.length) cam = C.lock2d(cam, P.camera.locks);
    bakeGSAP(tl, '#F-' + s.id, cam, { t0: s.vis[0], dur: s.vis[1] - s.vis[0], fps: F, W, H, cover: false });
  }

  // 3. transitions: one linear proxy tween per window; the key's ease lives inside applyDom
  const root = $('stage');
  for (const w of P.windows) {
    const a = document.querySelector(w.a), b = document.querySelector(w.b), o = { p: 0 }, cut = (w.cut - w.start) / (w.end - w.start);
    tl.fromTo(o, { p: 0 }, { p: 1, duration: w.end - w.start, ease: 'none', immediateRender: false,
      onUpdate: () => applyDom(w.key, o.p, { a, b, root, params: w.params, cut }) }, w.start);
  }

  // 4. captions: Python chunks (same rules as chunkWords), dark plate, baked into the one timeline
  const style = { ...CAPTION_STYLES[P.captions.style], ...P.captions.overrides, accent: P.style.capAccent };
  const cm = mountCaptions($('caps'), P.captions.chunks, style, { W, H, platform: 'conservative', font: 'Manrope, sans-serif' });
  if (P.captions.plate) for (const e of cm.els) { const p = document.createElement('div'); p.className = 'rd-plate'; e.words.forEach((s) => p.appendChild(s)); e.el.appendChild(p); }
  bakeCaptions(tl, cm, P.captions.chunks, { t0: 0, dur: D, fps: F });

  // 5. kinetic titles (hook, cutaway text, end-card line)
  const type = (el, spec, fontPx, t0, dur) => { const m = mountType($(el), spec, { fontPx, H, font: FONT }); bakeType(tl, m, spec, { t0, dur, fps: F }); };
  for (const t of P.titles) { type(t.el, t.spec, t.fontPx, t.start, t.dur); tl.fromTo('#' + t.el, { opacity: 0 }, { opacity: 1, duration: 4 / F, immediateRender: true }, t.start); }
  for (const c of P.cutaways) type(c.id + '-in', { preset: c.preset, lines: c.lines, at: c.textAt, out: 1e9 }, c.fontPx, c.start, c.dur);
  if (P.endcard && P.endcard.line) type('endcard-line', P.endcard.line.spec, P.endcard.line.fontPx, P.endcard.start, P.endcard.dur);

  // 6. chips: one pop each (the wrapper is the timed clip; we animate its child)
  for (const o of P.overlays) tl.fromTo('#' + o.id + '-in', { scale: 0.82, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.18, ease: 'back.out(2)', immediateRender: false }, o.start);
  for (const c of P.cutaways) for (const b of c.beats) tl.fromTo('#' + c.id + '-in', { scale: 1.03 }, { scale: 1, duration: 0.18, ease: 'power2.out', immediateRender: false }, b);

  // 7. global finish by DOM position (never z-index/opacity/transform on .fx)
  bindLayers(mountStack($('fx-mid'), [{ kind: 'vignette', params: { amount: P.style.vignette, roundness: 1 } }], { width: W, height: H, fps: F, seed: 7 }), { fps: F });
  bindLayers(mountStack($('fx-top'), [{ kind: 'grain', params: { stock: P.style.grain } }], { width: W, height: H, fps: F, seed: 11 }), { fps: F });

  // 8. cutaway backgrounds: Canvas2D kinds, windowed (one render per frame per visible card)
  for (const c of P.cutaways) bindWindow(mountStack($(c.id + '-bg'), [{ kind: c.bg.kind, params: c.bg.params }], { width: W, height: H, fps: F, seed: c.bg.seed }), c.start, c.dur, F);

  // 9. gfx parts (lower third, follow button, command pill), repainted per seek
  const items = [...P.gfx, ...(P.endcard && P.endcard.gfx ? [P.endcard.gfx] : [])];
  if (items.length) bindGfx(mountGfx($('gfx'), items, { W, H, platform: 'conservative', seed: P.seed % 65536 }));

  // 10. brandField end card (only when a logo is given)
  if (P.endcard && P.endcard.kind === 'brandField') {
    const st = mountStack($('endcard-fx'), [{ kind: 'brandField', params: P.endcard.params }], { width: W, height: H, fps: F });
    await st.ready(); bindLayers(st, { t0: P.endcard.start, fps: F });
  }

  // 11. progress bar (plain scaleX, seek-safe)
  if (P.progress) tl.fromTo('#progress-fill', { scaleX: 0 }, { scaleX: 1, duration: P.progress.dur, ease: 'none', immediateRender: true }, 0);

  // 12. canvas/SVG text measured with real faces: repaint the current time once
  window.dispatchEvent(new CustomEvent('hf-seek', { detail: { time: window.__hfThreeTime || 0 } }));

  // 13. warm pass, then register (HyperFrames: register only after the build)
  tl.seek(tl.duration()).seek(0);
  window.__timelines.main = tl;
  window.__rd = { ok: true, windows: P.windows.length, chunks: P.captions.chunks.length, segments: P.segments.length };
}
```

Invariants this runtime keeps. The HyperFrames and pack lints check these:
- No tween touches a timed `.clip`, `<video>` or `<audio>`.
- Each element has a single writer: `#cam` = bake, `.fr` = bake, `.txl` = applyDom (which resets its inline styles every call), caption spans = bakeCaptions.
- No GSAP `visibility`, `display` or `autoAlpha`.
- Audio is never driven from JS.
- `#progress-fill` has no CSS transform (`gsap_css_transform_conflict`).

### 5.5 Asset staging (`stage.py`; disk-lean)

| what | from | to | how |
|---|---|---|---|
| takes | `prepped/<shot>-<k>.mp4` | `reel/assets/media/` | symlink (as today; proven in demo-week2 renders) |
| pack JS | entry modules `transitions/lib/tx-dom.js`, `camera/bake.js`, `camera/cam2d.js`, `type/captions.js`, `type/dom.js`, `type/gfx/index.js`, `layers/overlay.js`, `layers/grade.js`, `layers/presets/grades.js`, `layers/presets/looks.js` + their **static-import closure** | `reel/assets/mp/<same relative path>` | `os.link`, fallback `os.symlink`, fallback `shutil.copy2` |
| fonts | `P/templates/_shared/fonts/Manrope-Variable.ttf`, `IBMPlexMono-SemiBold.ttf` (+ OFL texts) | `reel/assets/fonts/` | hard link |
| RD runtime | `src/reel_director/web/reel.mjs`, `reel.css` | `reel/assets/rd/` | copy (≈ 10 KB) |
| sound | `mixdown` output | `reel/assets/mix.wav` | written (48 kHz/24-bit: 17 MB per minute) |
| logo | `style.brand.logo` | `reel/assets/brand/` | symlink |

Closure walk:
- Regex over `^\s*(import|export)\b[^'"]*from\s*['"](\.[^'"]+)['"]` and bare `import\s*['"](\.[^'"]+)['"]`, resolved relative to each file and recursed.
- It fails compile with the missing path, so a missing file is a compile error instead of a silent render.
- Expected sizes from the notes: transitions about 92 KB (5 files), camera 27 KB (3), the layers closure 25 files (221 KB, including `type/gfx/{safe,pathsample,media,core}.js` and `type/{ease,safezones}.js`), and the `type/gfx` closure 31 files (561 KB).
- The pack modules have no dynamic `import()` (grep).

Other staging rules:
- The pack rev (`git -C P rev-parse HEAD`, read-only) goes into `edit_plan.pack.rev`.
- Re-staging is idempotent: unlink and relink, as `asset()` already does.
- Disk per build is about 0.3 MB of real files plus `mix.wav`. Studio keeps the last 2 renders: `renders/reel.mp4` (CRF 18 ≈ 20-40 MB per minute) and `reel-master.mp4`.

### 5.6 Render invocation (`hf.py`)

```
npx --yes hyperframes@{HF_VERSION} lint <reel>                    -> 0 errors (advisory warnings allowed: nested_structure_needs_subcomposition, timeline_track_too_dense)
npx --yes hyperframes@{HF_VERSION} validate <reel>                -> 0 JS errors, 0 missing assets
npx --yes hyperframes@{HF_VERSION} render <reel> -o renders/reel.mp4 --crf 18 --experimental-fast-capture=false --workers 2 --quiet
npx --yes hyperframes@{HF_VERSION} snapshot <reel> --at <t,...> --no-end --describe false -o qa/stills    (always --describe false and -o)
```

- Review renders use `--crf 23`.
- Studio's current `RENDER_ARGS = ["--quality", "delivery"]` is replaced by these flags. **[verify]** that 0.8.142 accepts `--experimental-fast-capture=false`; it logged the fallback on 0.8.142.

---------------------------------------------------------------------------------------------------------------------------

## 6. Audio plan

### 6.1 Mode A (default): one baked master

`mixdown.run(plan)` is WP3. The mixer runs in a **subprocess** (`python -m reel_director.mixjob job.json`) with these environment variables set before Python starts:
- `NUMBA_CACHE_DIR=<project>/.cache/numba`
- `PYTHONPYCACHEPREFIX=<project>/.cache/pyc`
- `PYTHONDONTWRITEBYTECODE=1`

There is no `-I` (it would ignore those vars). The subprocess keeps numba out of the mlx process and keeps numba's `cache=True` from writing into the pack.

1. **vo.wav.**
   - Decode each used take once: `ffmpeg -v error -i <take> -vn -ac 2 -ar 48000 -f f32le -`.
   - For each segment's `vo`, take the slice `[js_round(mediaStart*48000), +round(dur*48000))`, apply 6 ms (288-sample) linear fades in and out (`patterns.autocut.crossfade_ms`), and add it at `start*48000` (= frame × 1600).
   - Slots contribute silence. The length is D.
2. **Bed** (section 6.2): `sf.read(bed)` → 40 ms fade-in on the first 1920 samples → `np.roll(y, -roll_frames*1600, axis=0)` (a rolled seamless loop stays seamless).
3. **Mix:**
   ```python
   m = mixer.Mix(fps, D, lib=RDLibrary())
   m.duck_db, m.bed_rel_vo_lu = plan.mix.duck_db, plan.mix.bed_rel_vo_lu
   m.add_bed(y, loop=True)
   m.automate_bed(plan.mix.automation)
   m.add_vo(vo)
   for c in plan.cues:
       m.add_cue(c.id, c.frame,
                 over_vo_db=c.db if c.ref == "vo" else None,
                 over_bed_db=c.db if c.ref == "bed" else None,
                 why=c.why, until_frame=c.get("until"))
   rep = m.render(out, "master", lufs=-14.0, ceiling_db=plan.mix.ceiling_db, stems=True)
   lint = mixer.lint_cues([...], fps, short_form=True, lib=m.lib, quiet=plan.mix.quiet)
   ```
4. **`RDLibrary(mixer.Library)`** handles custom `file:` sounds (legacy `src` cues) without touching the pack.
   - It adds `by_id["file:<rel>"] = {id, category: "custom", tier: 3, over_bed_db: 2.0, anchor_kind: "peak", anchor_frame_offset: 0, loop: False, tags: [], seed: 0, anchor_sample: argmax|x|, phone_safe: True}` and pre-fills `_cache` with the file resampled to 48 kHz stereo (scipy `resample_poly`).
   - It overrides `audio(sid, seed)` to return the cached array (or `(array, anchor)` when seeded) for `file:` ids. `Mix.add_cue` round-robins repeated ids through a seeded re-render, which custom files cannot do. **[verify]**
5. Copy `master.wav` to `reel/assets/mix.wav`. Write `.cache/mix/master_report.json` and `mix_lint.json`; QA reads both.
6. **Delivery** (`audio.deliver`, replacing `master()` in mode A):
   ```
   ffmpeg -i renders/reel.mp4 -i reel/assets/mix.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 256k -ar 48000 -movflags +faststart renders/reel-master.mp4
   ```
   - This is the exact encoder and bitrate the mixer's AAC probe used (`aac_probe(x, enc="aac", bitrate="256k")`). The delivered peak therefore matches the probe, whatever HyperFrames did to its own audio track.
   - Optional colour tags without re-encoding: `-bsf:v h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1`, added only if eyes/encode reports untagged colour. **[verify]**
   - After muxing, `audio.measure()` on the delivered file must read -14 ± 0.5 LUFS-I and TP ≤ -1.0.

### 6.2 Bed selection, beat grid, beat sync

- **Selection** (`mixdown.pick_bed`, deterministic):
  1. `music.id`, if given.
  2. Else the preset's ordered list, filtered by `music.mood` against `music/manifest.json` (items with `kind == "bed"`, `loop: true`, `mood` ∩ requested).
  3. Prefer beds whose loop is ≥ D / 2.5, to limit audible repetition.
  4. Pick `candidates[crc32(title) % min(3, n)]`.
  5. Ceiling -3.0 when the bed is in the bass-heavy set {ambient_pad 63%, corporate_bright 70%, deep_house 86%, jazz_walk 72%, raga_calm 64%, tech_pulse 60%} (audio.md 2.2).
  6. `music: false` gives no bed: `has_bed` is false and the cues use `over_vo_db` only.
  7. A custom `music.src` is loaded as-is. Its grid comes from `music.bpm` (`grid.tempo_map`); without one there is no beat sync.
- **Grid:** the sidecar `beat_frames` / `bar_frames` (all 30 fps; loop beds repeat every `meta.length_frames`). It is expanded with `expand_grid(side, N, 0, roll)` (audio.md section 3). For other fps the sidecar frames are rescaled `f * fps/30` and rounded with js_round. Beds are only exact at 30 fps; 24/25 fps lose the whole-frame beat.
- **Rotation (hero downbeat):** hero = the hook-interrupt frame. Score each `roll ∈ [0, fpbar)` that places the hero on a beat by `2·[hero on a bar downbeat] + #shot-boundary cuts that can reach a beat (below)`. Take the argmax; ties go to the smaller roll.
- **Cut snap without harming speech:**
  - A shot-boundary cut may move **earlier only**, by trimming the outgoing shot's post-roll: from `media_out` down to ≥ last word end + 0.12 s, and never below a beat-hold extension.
  - Words, jump cuts and the incoming media are untouched. Later times shift by the trim.
  - Slack is about (0.35 - 0.12) s ≈ 6 frames at 30 fps.
- **Accent snap:** punch starts, chip pops and keyword pops move to the nearest beat when |Δ| ≤ 2 frames and the new frame stays in [word.s - 2f, word.e).
- **VO mode:** jump cuts never move (critic: talking heads are `vo` mode; a 60% onset target would be meaningless). The pack bed's kick is on F and the SFX on F+1 by design; that offset is never "fixed".
- **Demo result:** uplift_corporate (16 f/beat, 64 f/bar), hero f36 → roll 28, bars at 36, 100, 164, 228, 292, 356. The cuts at 124 and 252 would need 8-frame trims (slack 6.9), so they stay. The chip snaps 50 → 52 and the punch snaps 341 → 340.
- **Experimental alternative (off by default):** `music.fit: "compose"` calls `compose(preset, [("intro",1,0.45), ("main",bars-2,0.7), ("tail",1,0.15)], seed, fps)` so the bed resolves on the end card. **[verify]** whether the 0.55 downward energy step adds an unwanted crash under the voice; the pack inserts a riser and crash at steps ≥ 0.3.

### 6.3 Ducking

- **Mode A (default).** The mixer ducks the bed from the actual voice signal:
  - envelope depth `duck_db` (12 for VO-led, so ears can read ≥ 9 dB), look-ahead 80 ms, attack 15, hold 120, release 350 ms;
  - a mid carve of -3 dB at 250 Hz and -3.5 dB at 3 kHz;
  - the un-ducked bed set to voice LUFS + `bed_rel_vo_lu`;
  - tier-2 make-room dips and tier-1 pre-hit vacuum;
  - end-card behaviour through `automate_bed`: bed held 1.8 s into the end card, then down to -30 dB, plus room tone -26 over the bed under the hold.
- **Mode B (`mix.mode: "live"`, HyperFrames-native).** It needs the 0.8.177 pin [verify].
  - Takes stay muted pictures. The voice is `<audio>` per segment at the exact `vo` times (transitions.md 3.2: same file and `data-media-start`, so source-zero matches and lip sync holds).
  - SFX are `<audio>`. The bed is a pre-tiled, rotated `assets/bed.wav` written by mixdown.

  ```html
  <audio id="vo-hook-0" src="assets/media/hook-1.mp4" data-start="0" data-duration="2.6333" data-media-start="0.55"
         data-track-index="7" data-audio-group="voice" data-volume="1"></audio>
  <audio id="sfx-3" src="assets/sfx/snd.ui.pop.wav" data-start="1.7302" data-duration="0.1015" data-track-index="10"
         data-audio-group="sfx" data-volume="0.2"></audio>
  <audio id="music" src="assets/bed.wav" data-start="0" data-duration="15.5667" data-track-index="12" data-audio-group="music" data-volume="1"
         data-automation="{&quot;version&quot;:1,&quot;lanes&quot;:[{&quot;target&quot;:&quot;volume&quot;,&quot;points&quot;:[{&quot;t&quot;:0,&quot;v&quot;:0.79},{&quot;t&quot;:0.07,&quot;v&quot;:0.79},{&quot;t&quot;:0.085,&quot;v&quot;:0.2},...]}]}"></audio>
  <!-- on #root (master bus): -->
  data-fx-chain="{&quot;version&quot;:1,&quot;nodes&quot;:[{&quot;type&quot;:&quot;truepeak&quot;,&quot;id&quot;:&quot;m1&quot;,&quot;label&quot;:&quot;Delivery ceiling&quot;,&quot;params&quot;:{&quot;ceiling&quot;:-3,&quot;lookahead&quot;:3,&quot;release&quot;:80}}]}"
  ```

  - **Duck lane:** computed in Python from the output-time words, merging speech regions separated by gaps < 0.6 s. Per region [s, e] the points are: (s - 0.095, v_full), (s - 0.08, v_duck), (e + 0.12, v_duck), (e + 0.47, v_full). `v_full = 10^(bed_rel_vo_lu/20)` relative to the -16 LUFS bed and voice; `v_duck = v_full · 10^(-duck_db/20)`.
  - Rules from the hyperframes-audio skill: an explicit t = 0 point, ≤ 512 points (adjacent regions merge until under the cap), `t` relative to the clip start, attributes double-quoted with `&quot;`.
  - **[verify]** whether a lane value multiplies `data-volume` or replaces it; the design sets `data-volume="1"` so both readings agree.
  - **Optional carve:** `node <hyperframes-audio skill>/scripts/carve.mjs --comp reel/index.html --bed music` writes `data-fx-carve` against the group `voice`. It needs `@hyperframes/core` resolvable, which is not installed by default, so it is skipped with a note.
  - **SFX timing (mode B):** `data-start = (F + 1 + anchor_frame_offset)/fps - anchor_ms/1000`. If that is negative, use `data-start = 0` and `data-media-start = -x`.
  - **SFX gains (mode B):** absolute gains from `templates/talking-head` against -16 LUFS takes: punch -14 dB (`data-volume` 0.20), emphasis pop -20 (0.10), whoosh -14 (0.20), lower third -18 (0.13), tick -22 (0.08).
  - **Master:** the existing `audio.master()` loudnorm (-14 / -1.0). Then grep the render log for `Audio lowered by`.
  - Mode B loses the measured cue levels, the AAC probes and ears cue-anchor detection. It stays a fallback.

### 6.4 SFX pairing and gain staging (planner table; ids verified in `sfx/manifest.json` / `bundles.json` / `catalog.json`)

**Level reference per cue:**
- If the cue's 60 ms K-window after the anchor (200 ms before it for `snd.riser.*`) overlaps any output word span: `over_vo_db = L` (the role level).
- Otherwise: `over_bed_db = L + 2 - bed_rel_vo_lu` (= L + 3 at the measured `bed_rel_vo_lu = -1`, which landed exactly in audio.md section 7).

This avoids the measured failure where `over_vo_db` in a speech gap was clipped at -30 dB and became inaudible.

| visual event | id (rotation variants) | visual frame F | L (dB re voice) | presets |
|---|---|---|---|---|
| hook title in | `snd.ui.pop` | title `at` frame (1) | -14 | all |
| hook interrupt punch | `snd.hit.punch` (clean: `snd.tx.scale_punch`) | punch frame | -12 | all |
| punch-in | `snd.tx.scale_punch` / `snd.hit.punch` | punch frame | -14 | all |
| crash zoom | `snd.hit.punch` + `snd.whoosh.zip` (zip F = punch - 1) | punch frame | -12 | hype |
| keyword pop | `snd.ui.pop` / `snd.ui.blip` | word start | -14 (hype -12) | punchy, hype |
| chip in | `snd.ui.pop` | chip start | -14 | punchy, hype |
| hard jump cut | `snd.tx.cut_tick` | cut | -22 | punchy, hype (skipped within 0.5 s of another cue) |
| window transition | catalog `sfx[0]` of the key (punchy) / all rows (hype) / `sfx[0]` at -2 dB (clean) | `{cut, start, end, peak}[at] + offset_f - 1` (catalog `offset_f` already includes the +1) | whip -14, scalePunch -14, zoomThrough -14 (inhale -18), push/swipeUp -16, blurCross/linearBlur -18, glitch -14, flash -14, dip -18 | all |
| settle-back (zoom-out) | `snd.whoosh.swish_out` | settle start | -20 | punchy, hype |
| cutaway text reveal | none (the transition carries it) | | | |
| lower third | `snd.ui.slide` | entrance | -18 | all |
| follow button | `gfxCues('social.followButton', ...)` (`sfx/ui/success` at +25 f) | as returned | -16 | punchy, hype |
| stat (with source) | `snd.ui.count_run` (anchor = the ding) | landing frame | -16 | all |
| riser into CTA | preset riser (`snd.riser.noise_1bar` 1.82 s / `snd.riser.tape_up` 0.5 s; `anchor_frame_offset -1`) | CTA cut frame | -16 | all |
| flash / invert accent | `snd.camera.shutter` | flash frame | -14 | hype |
| end card | `snd.logo.hybrid` (tier 1, over bed +5 fixed) | reveal-complete frame | bed +5 | all |
| end hold | `snd.amb.room_tone`, `until_frame` = last frame | end start + 1.8 s | bed -26 fixed | all |
| explicit `sfx` cue | the given id / `file:` | word start (or end with `anchor: "end"`) | `level` or -14 | all |

Collision rules:
- An explicit cue within ±3 frames of an auto cue replaces it.
- Two auto cues within 2 frames: keep the higher tier.
- Rotation: the k-th use of a role takes `variants[k % n]` whenever the same id appears in the last 7 cues (lint R9).
- Tier-1 is only the end card (lint R4).
- Phone-weak ids (`snd.hit.sub_drop`, `low_thump`, `soft`, `taiko`, `snd.tx.ink_bloom`) are not used, so R12 never needs a partner.
- The cue sheet passes `mixer.lint_cues` with no R2, R4, R9, R10 or R12 before mixing. If it does not, the planner fails with the list.

### 6.5 Master spec

- WAV: -14 LUFS-I, TP ≤ -2.0 dBTP (preset; -3.0 for bass-heavy beds), AAC probes ≤ -1.0, last 0.15 s digital zero. The mixer does all of these.
- Delivered MP4: -14 ± 0.5 LUFS-I, TP ≤ -1.0.
- If the render log ever shows `Audio lowered by` (mode B), lower the ceiling one step (-2.0, then -3.0) and re-mix once.

---------------------------------------------------------------------------------------------------------------------------

## 7. Quality gates

### 7.1 Gate list (`qa.py`, results in `qa/report.json`, shown in Studio)

| stage | check | threshold (PASS) | source |
|---|---|---|---|
| G0 compile | ids resolve | transitions in `aliases.json` with kind dom/cut/smash; sfx in `manifest.json`; gfx ids in `type/manifest.json` components; pack import closure complete | hard rule 1 (gfx ids are not checked by `check_ids.py`) |
| G1 plan | interrupt ladder | `lint_interrupts` fail == []; static stretch ≤ 3.5 s; auto punch gap ≥ 4 s; L3 ≥ 6 s apart; flashes ≤ 3/s | patterns.json interrupts, virality |
| G2 plan | captions and text | chunks ≤ 3 words (≤ 4 if explicit), ≤ 18 chars/line, ≤ 2 lines, ≥ 0.25 s, ≤ 5 w/s (`lintCaptions` port); every `plan.texts` box inside x 65-960 / y 269-1248; font floors (caption 64-80, headline ≥ 96, lowerthird ≥ 48, endcard ≥ 30) | safezones.js, eyes spec |
| G3 mix | mixer report | master -14.0 ± 0.2; WAV TP ≤ ceiling; AAC probes ≤ -1.0; no cue with `trim_clipped_from_db`; `phone_ok` for all; `lint_cues` empty | mixer.py |
| G4 build | `hyperframes lint` / `validate` | 0 errors; 0 JS errors; 0 missing assets; no `duplicate_audio_track` (mode A) | gotchas |
| G5 render | render log | exit 0; no `Audio lowered by`; fast-capture fallback noted only | gotchas |
| G6 stills | snapshot sheet | at 0, 0.2 s, the hook interrupt, every window's cut-1 / cut / cut+1, each cutaway mid, the end card: `#rd-error` red (mean ≈ (255,0,51)) absent; frame 0 mean luma > 16 | `hyperframes snapshot --describe false -o qa/stills` |
| G7 delivered | loudness | -14 ± 0.5 LUFS-I, TP ≤ -1.0 dBTP | hard rule 5 |
| G8 delivered | **eyes** | no check `fail`; `critic_hook_2s`, `critic_phone_readability`, `critic_motion`, `critic_variety` ≥ 8; `banding` and `encode` not fail | critic.md, gate 6 |
| G9 delivered | **ears** | no check `fail`; `critic_sound_sync` ≥ 8; `speech` ≥ 8 (duck ≥ 9 dB where measurable, speech-to-music ≥ 10 dB in 300-3.4k, 110-175 wpm); loudness pass; plan cues on F+1 (pack ids; `file:` cues "not detectable" is allowed) | critic.md |

Verdict: **PASS** when nothing fails. **WARN** when only warns remain; the top 3 `top_issues` are shown with `viewer` / `listener`, `fix` and `t`. **FAIL** when any check fails.

The skill still requires one human look at a 360 px still and one listen on a phone. Studio shows `qa/phone_*.png`:

```
ffmpeg -v error -ss <t> -i reel-master.mp4 -frames:v 1 -vf scale=360:-2 qa/phone_<t>.png
```

It is made at 0, 1, 2 s, 25/50/75% and the end, together with the 2 fps sheet (`fps=2,scale=180:-2,tile=6xN`).

### 7.2 eyes and ears invocation

```bash
PY=/opt/anaconda3/bin/python3         # pack-pinned numpy 1.26.4 / scipy 1.11.4 / numba 0.59.0; fallback: RD .venv python
ENV="PYTHONDONTWRITEBYTECODE=1 NUMBA_CACHE_DIR=<project>/.cache/numba EARS_CLAP_MODEL="
$PY P/eyes/look.py renders/reel-master.mp4 --plan reel/plan.json --json qa/eyes.json --md qa/eyes.md --quiet
$PY P/ears/listen.py renders/reel-master.mp4 --plan reel/plan.json --transcript reel/words.json --mode vo --mood off \
    --json qa/ears.json --md qa/ears.md --quiet
```

- Never use `--mood gemini` (a paid cloud call). Both CLIs exit 0, so parse `checks[].status`, `scores`, `top_issues`.
- Each takes about 2-3 s on a 6-13 s clip.
- Run them as subprocesses: never import them into the mlx/silero process.

`reel/plan.json` (planner output, the eyes/ears schema from qa-templates.md section 1):

```json
{"fps": 30, "size": [1080, 1920], "platform": "reels.organic", "template": "talking-head", "seconds": 15.5667,
 "shots": [{"id": "hook-0", "start": 0.0, "dur": 2.6333, "tx": "transitions/cut"},
           {"id": "hook-1", "start": 2.6333, "dur": 1.5, "tx": "transitions/cut"},
           {"id": "turn-0", "start": 4.1333, "dur": 4.2667, "tx": "transitions/whip"},
           {"id": "cta-0", "start": 8.4, "dur": 2.2333, "tx": "transitions/swipe-up"},
           {"id": "cta-1", "start": 10.6333, "dur": 1.9333, "tx": "transitions/cut"},
           {"id": "endcard", "start": 12.5667, "dur": 3.0, "hold": true}],
 "texts": [{"id": "cap0", "text": "Most creators WASTE", "t": [0.15, 1.19], "box": [227, 1127, 797, 1206], "fontPx": 72, "role": "caption", "fg": "#FFFFFF"},
           {"id": "title-hook", "text": "Most creators waste", "t": [0.0333, 1.6], "box": [146, 289, 878, 560], "fontPx": 122, "role": "headline", "fg": "#FFFFFF"},
           {"id": "overlay-1", "text": "3 HRS / REEL", "t": [1.7333, 3.9], "box": [252, 300, 772, 390], "fontPx": 76, "role": "headline", "fg": "#0B0B0F"},
           {"id": "cutaway-1", "text": "EDIT FIRST. RECORD LAST.", "t": [5.6667, 8.4], "box": [168, 830, 856, 1090], "fontPx": 110, "role": "headline", "fg": "#FFFFFF"},
           {"id": "endcard-url", "text": "reeldirector.app", "t": [12.6, 15.5667], "box": [300, 920, 724, 1000], "fontPx": 64, "role": "endcard", "fg": "#FFFFFF"}],
 "holds": [{"t": [13.5, 15.5667], "why": "end card settled"}],
 "paceRule": {"aslMax": 4.5, "longMax": 7},
 "cues": [{"id": "sfx/ui/pop", "t": 0.0333}, {"id": "sfx/whoosh/whip_pan", "t": 4.1333}, {"id": "sfx/logo/hybrid", "t": 12.9333}],
 "audio": {"mode": "vo", "role": "explainer", "quiet": [{"t": [14.4, 15.5667], "kind": "hold", "why": "end card quiet hold"}]}}
```

How `plan.json` is filled:
- `shots` has one entry per **kept clip**, so ears checks every jump cut against word boundaries.
- Cutaways are **not** shots: they are inserts over a continuing voice and cut inside sentences on purpose, as in multi-voice-doc, where ears passes.
- Chip and text boxes are the inner plate rect only. A box that includes shadow or footage would put dark pixels at P5 next to dark ink and fail contrast.
- Cue `t` is the visual frame F/fps, written as `sfx/<cat>/<name>`.

`reel/words.json` is `{"words": [{"w", "s", "e"}]}` in output time, after quantisation and beat sync.

### 7.3 Bounded auto-fix loop (≤ 2 rounds; the critic loop stops when a score does not move)

| top issue | knob change (deterministic) |
|---|---|
| eyes/banding fail | grain `{stock: 'upload-safe', amount: 0.045}`, delivery `--crf 16` |
| eyes/safezones fail | caption `size` 72 → 66; chip and title `fontPx` -10% |
| eyes/readability contrast < 3 | plate alpha +0.1 (cap 0.78); title plate on |
| eyes/frames frozen | add a `push2d` 1.0 → 1.04 on the flagged card or end card, or mark a hold if it is intended |
| eyes/flashes fail | downgrade flash → scalePunch |
| eyes/frame0 fail (dark subject) | cannot be fixed in the edit: report "re-record with light on the face" (Studio take check) |
| ears/loudness TP | `ceiling_db` -3.0, re-mix + re-deliver (no re-render needed in mode A) |
| ears/speech ducking < 9 dB | `duck_db` 14, `bed_rel_vo_lu` -4, re-mix only |
| ears/sync first sound late | title-in cue to F 0 |
| ears/repetition | stricter rotation (all roles alternate) |
| ears/tone mud (voice) | optional vo EQ in mixdown (peaking -3 dB @ 300 Hz, Q 1), reported to the creator |

Sound-only fixes re-run mix → deliver → ears and never re-render (mode A pays off here).

---------------------------------------------------------------------------------------------------------------------------

## 8. Test plan

All test output goes under `tmp_path` or `<project>/.cache`. Nothing is written into the pack (no pack tests run in place: camera/type tests write `last-run*.json`; cutgen needs `-B`). Node parity tests skip when `node` is missing.

### 8.1 Unit tests (pure Python, < 10 s total)

| file | asserts |
|---|---|
| `tests/test_schema_v2.py` | v1 demo parses unchanged; new fields default; `zoom` → punch; `stat` without `source` fails; bad transition id fails (fixture aliases); `fps` 29 with baked mix fails; `sfx` with both `id` and `src` fails |
| `tests/test_director.py` | **determinism**: same input gives byte-identical `directed.json` (run twice and in a subprocess with a different `PYTHONHASHSEED`); golden files per preset for the demo; hook has a title ≤ 7 words, ≥ 96 px, and an interrupt candidate; every shot i > 0 has `transition_in` with a reason (or `cut`); number phrases get `emphasis` (+ chip in punchy); CTA end card present; explicit cues untouched; `auto: false` respected; `suppress` removes exactly one |
| `tests/test_txplan.py` | `js_round` (4.5 → 5); `tx_window` equals catalog `frames_30fps` for all 49 keys; clamps (`pre ≤ media_in`, `pre + post < 2` → hard cut); span stretches A and B and moves `mediaStart`; **node parity**: `node -e` runs `txplan.mjs txPlan` on 10 fixture shot lists and gets identical windows |
| `tests/test_captions_port.py` | Python `chunk_words` equals JS `chunkWords` (node) on fixtures including gaps > 0.6, sentence ends, 18-char overflow; gap closing; upper-cased emphasis; boxes inside the conservative rect |
| `tests/test_planner.py` | demo + fixture timelines. Quantisation keeps `start - mediaStart` per segment; punches ≥ 4 s apart (auto); hook interrupt in [0.3, 1.5]; cap ≤ 1.30 for 1080p; no stretch > 3.5 s without an event; `lint_interrupts` clean; top band has no overlaps; cutaway coverage ≤ budget; windows never overlap; each window's a and b are visible at `cut`; `plan.json` validates against the eyes schema (`eyes.core.plan_texts` called in a subprocess) |
| `tests/test_beatsync.py` | rotation puts the hero on a downbeat; moves are earlier-only and within slack; no word time inside a trimmed region; accents snap ≤ 2 f and stay inside their word; demo numbers (roll 28; snaps 50 → 52 and 341 → 340; cuts 124 and 252 unchanged) |
| `tests/test_mixdown.py` | vo.wav assembly is sample-exact on synthetic sine "takes" (segment k = frequency k; checks placement and 288-sample fades); level-reference choice (in word → vo, gap → bed with the formula); cue-sheet shape; `pick_bed` is deterministic and respects mood; `RDLibrary` `file:` entry anchors at the peak |
| `tests/test_compiler_v2.py` | HTML parses (html5lib or a stdlib parser); every `.clip` has `data-start`/`data-duration`; no `<video>` inside a timed element; all `<video>` muted with no `data-has-audio`; ids unique; every `<audio>` has an id; no inline z-index/opacity/transform/filter on `.fx`; `rd-plan` JSON round-trips (with `</` escaped); asset links exist |
| `tests/test_stage.py` | the closure walk resolves the 10 entry modules (expected counts per module, per section 5.5); hard link on the same volume (`st_ino` equal); a missing-file fixture raises |
| `tests/test_qa.py` | parse the recorded `scratch-qa/rd-eyes.json` / `rd-ears.json` (copied as fixtures): demo-week2 → FAIL with the known checks (frame0, frames, banding, safezones; tail-zero), the fix map picks the right knobs; thresholds table |

### 8.2 Integration (seconds, no render)

- **Mixer:** a 6 s synthetic vo + `bed_lofi_warm_loop8` + 6 cues through `mixjob`.
  - Expect -14.0 ± 0.2 LUFS-I, TP ≤ -2.0, AAC probe ≤ -1.0, tail zero, `lint_cues` empty.
  - Every cue's `measured_over_vo_db` / `measured_over_bed_db` is within ±1 dB of target.
  - Confirm the pack tree is untouched: `git -C P status --porcelain` is identical before and after, and no new `__pycache__` mtimes.
- **Runtime module smoke (headless):** `hyperframes lint` + `validate` on the compiled demo (fake media from `tests/e2e/make_fake_media.py`). Expect 0 errors and `window.__rd.ok` true, read through `hyperframes snapshot` plus the absence of `#rd-error` red.

### 8.3 Render-based (opt-in `-m render`; scratch output; ≤ 200 MB disk; about 2-4 min)

| id | what | pass |
|---|---|---|
| R1 | snapshot stills of the demo at the key times (G6 list) | no red error card; at each window cut-1 / cut / cut+1 the incoming layer appears exactly at the cut frame (column-mean difference spike at cut, not cut±1); captions visible above every window (caption plate pixels unchanged in the band across the window); cutaway background non-uniform (std > 4); grain present (frame-to-frame noise in a flat card > 0) |
| R2 | **seek-order determinism**: `snapshot --at 6.0,1.0,6.0,11.0,6.0` | the three 6.0 stills are identical or > 60 dB PSNR (blurs may add GPU noise) |
| R3 | full demo render, `--crf 23 --workers 2 --experimental-fast-capture=false`, then deliver | render exit 0; no `Audio lowered by`; G7, G8 and G9 PASS; record wall time |
| R4 | **whip seam check**: stills at whip cut-2 .. cut+1 | the darkest 40 px column's mean luma ≥ 0.6 × the frame mean. Failing this switches the preset default to `linearBlur` |
| R5 | **0.8.142 vs 0.8.177 A/B**: R1 stills on both versions | PSNR > 45 dB per still and hf-seek layers present in both. Passing moves `HF_VERSION` to 0.8.177 and unlocks mode B |
| R6 | **mode B**: render the demo with `mix.mode: live` on 0.8.177 | bed ducks under the voice (ears speech duck ≥ 9 dB); no voice doubling (per-frame RMS continuity at windows) |
| R7 | **caption contrast trick**: eyes readability on R3 with the `capAccent` underline | captions contrast ≥ 4.5 (pass); otherwise fall back to the pack `pill` purple `#4A18ED` accent |
| R8 | **slots animatic**: compile with no takes (all slots), render `--crf 28` | mix has bed + SFX with silent vo; eyes frame0 / frames no fail (the planned holds cover the slots) |

### 8.4 End to end

The existing Playwright e2e (`tests/e2e/run_e2e.py`) gets one new assertion: the Studio build ends with `qa/report.json` verdict ≠ FAIL, and the Quality panel lists the top issues. The e2e uses fake media, so eyes frame0 may warn; it must not fail.

---------------------------------------------------------------------------------------------------------------------------

## 9. Implementation split (file-disjoint work packages for parallel agents)

The shared contracts are frozen in this document: cue types (2.3), `edit_plan.json` (4.1), `plan.json` / `words.json` (7.2) and the mix job (6.1). Each package copies the example JSON into its **own** fixture file, so packages never touch each other's files.

**Coordination:** other agents are editing `__main__.py`, `timeline.py`, `textnorm.py`, `studio/*` and tests right now (git status: modified, plus new `studio/`, `takecheck.py`, `capture.py`).
- No package edits `timeline.py` or `textnorm.py`. `beatsync.py` builds a new `Timeline` from dataclasses.
- WP5 owns `__main__.py` and `studio/runtime.py` and starts after those agents land, or rebases onto them.

| WP | owns (create / edit) | consumes | delivers | acceptance |
|---|---|---|---|---|
| **WP1 Director + schema** | edit `schema.py`; new `director.py`, `presets.py`, `lexicon.py`; `tests/test_schema_v2.py`, `tests/test_director.py`, `tests/fixtures/director/*.json` | pack `aliases.json` and `sfx/manifest.json` (read-only, via a tiny local loader; switch to `mp/pack.py` after WP2 lands) | `direct(script) -> Script` with auto cues (`auto`, `why`, `candidate`, `score`, `alt`); `directed_json()`; preset tables (3.2) | 8.1 schema + director tests green; demo goldens for 3 presets; v1 tests in `tests/test_core.py` still pass |
| **WP2 Planner** | new `mp/__init__.py`, `mp/pack.py` (pack locator `RD_MOTION_PACK` / default `~/Developer/motion-pack-public`, JSON catalogs, bytecode-free module loader, rev), `mp/txplan.py`, `mp/captions.py`, `mp/gfx_boxes.json` (placeholder; WP4 fills it), `planner.py`, `beatsync.py`, `eyesplan.py`; tests `test_txplan.py`, `test_captions_port.py`, `test_planner.py`, `test_beatsync.py` | WP1 cue dataclasses (fields per 2.3; stub until WP1 lands); existing `Timeline` | `plan(timeline, script, preset) -> dict` (edit_plan v1), `write_plan(project)` → `edit_plan.json`, `plan.json`, `words.json` | all 8.1 planner tests incl. node parity; demo `edit_plan.json` matches section 4.1 / 3.5 numbers |
| **WP3 Audio** | new `mixdown.py`, `mixjob.py`; edit `audio.py` (add `deliver()`, keep `master()` for mode B); tests `test_mixdown.py`, `test_mix_integration.py` (marker `slow`) | `edit_plan.json` (fixture copy) | `mixdown.run(plan, project)` → `assets/mix.wav`, `master_report.json`, `mix_lint.json`; `pick_bed`; mode-B helpers `duck_lane(words, ...)`, `sfx_audio_tags(plan)`; `deliver(render, wav, out)` | 8.1 mixdown + 8.2 mixer integration green; pack tree unchanged |
| **WP4 Compiler + runtime** | rewrite `compiler.py`; new `stage.py`, `web/reel.mjs`, `web/reel.css`; fill `mp/gfx_boxes.json` via a one-off probe script `scripts/measure_gfx_boxes.mjs` (output written to RD only); tests `test_compiler_v2.py`, `test_stage.py` | `edit_plan.json` (fixture copy); `mix.wav` path convention | `compile_project(plan, out)` → `index.html` + staged assets; `timeline.json` kept for Studio (`timeline_summary` unchanged) | 8.1 compiler + stage tests; 8.2 lint/validate smoke; R1 + R2 stills pass on 0.8.142 |
| **WP5 QA + CLI + Studio** | new `qa.py`, `hf.py`; edit `__main__.py` (subcommands `direct`, `plan`, `mix`, `qa`, `build`; `compile` gains `--preset`, `--no-auto`, `--mix`), `studio/runtime.py` (`_build` steps and `RENDER_ARGS`), Studio Quality panel in `studio/static/`; tests `test_qa.py`, `tests/render/test_render_smoke.py` (marker `render`) | all of the above | one-button build: prep → direct → plan → mix → compile → lint/validate → render → deliver → qa; `qa/report.json`; the fix loop (7.3) | 8.1 qa tests; R3-R8 run and recorded in the session handoff; Studio e2e assertion (8.4) |

Order and parallelism:
- WP1, WP2, WP3 and WP4 start together against the frozen contracts.
- WP2 is on the critical path for real data. WP3 and WP4 run on fixture plans until WP2's demo plan exists, then switch fixtures.
- WP5 starts with fixtures (recorded eyes/ears JSON) and integrates last.
- Estimated effort: WP1 1 day, WP2 2 days, WP3 1 day, WP4 1.5 days, WP5 1.5 days.

---------------------------------------------------------------------------------------------------------------------------

## 10. Risks and open items (each with its test)

1. **DOM whip seam band** (about 4 frames). Mitigation: `blurMax 0.05` plus the mean-colour stage. R4 decides between whip and `linearBlur` as the preset default.
2. **zoomThrough DOM black border** at `scaleIn 0.5`. Fixed with `scaleIn 1.3` (proven); `resolveParams` does not range-check, so the planner always sets it.
3. **Fast capture fallback** doubles capture time on window-heavy reels. It is disabled by flag; check that 0.8.142 accepts the flag (R3).
4. **HF version.** The pin is 0.8.142 until R5. 0.8.177's runtime contains the `hf-seek` dispatch (grep), but no render of hf-seek layers has run on it yet. Mode B needs 0.8.177.
5. **Caption accent through a CSS-gradient `background`** set by `capVars` + `tl.set`. GSAP sets non-numeric strings on `set`; R7 verifies the picture and eyes contrast. Fallback: pack pill `#4A18ED`.
6. **`RDLibrary` custom `file:` sounds** depend on `Library.entry` / `audio` internals (read at `music/mixer.py:41-65`). Pin it with the WP3 integration test. Pack mixer changes would surface there.
7. **Estimated text boxes** (0.50-0.56 em/char) can disagree with real layout. The WP4 gfx-box probe and R1 stills measure the real boxes; eyes' 0.5 px tolerance makes an over-wide estimate fail safezones. The estimate is therefore conservative-narrow and then shrunk 6 px.
8. **Light leaks** stay off (they wash the whole 9:16 frame even at intensity 0.05). Only a windowed accent with `edge: 'bottom'`, `intensity ≤ 0.1`, layer opacity 0.3-0.5 is allowed, and only explicitly.
9. **Per-take grading** uses the SVG filter on `#cam` (about 6 ms per frame compositor cost, rough probe). Alternatives, both unverified with pack cubes: HyperFrames `data-color-grading` LUT per take, or an ffmpeg `lut3d` pre-bake at prep.
10. **Background effects behind the creator** (type behind subject, background replacement) need a person matte. They are out of scope; `type.behindSubject` exists but needs "YOUR matte".
11. **Licensing.** Pack code is MIT and its audio CC0. Manrope and Plex Mono are OFL (ship the OFL texts next to the staged fonts). Do not use the external Kenney/OwlishMedia sets (`ext.*`) in RD: the mixer cannot place them and they must stay out of git.
