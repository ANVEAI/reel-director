# Reel Director v1 "motion" build — frozen contract (2026-10-20, deadline: builders done by 08:35 IST)

Repo: this repo at HEAD 183ad68 (74 unit tests green, e2e green). venv: .venv/bin/python.
Pack: motion-pack (https://github.com/ANVEAI/motion-pack), read-only; MIT code, CC0 audio. HyperFrames installed: 0.8.177 (use it; do NOT npx another version).
Full design (aspirational, ~7 days): docs/research/motion-pack/DESIGN.md — use it for exact pack APIs, but ship the v1 scope below.
Research to apply: docs/research/reel-craft/{editing-pace,captions-graphics,sound,trends-2026,hooks-structure}.md,
docs/research/asset-packs/{market,sources}.md.

## The contract (do not change shapes; add params freely)
Script/Shot/Cue dataclasses in schema.py stay: `Cue(type, start_word, end_word, params: dict)` anchored by phrase `at`/`until`.
Cue types (schema validates required params; compiler renders; director emits):
- `overlay` {text}                       existing: card near top
- `cutaway` {text}                       existing: full-screen text card (must sit UNDER captions)
- `zoom` {scale, hold}                   existing: smooth push (keep for back-compat)
- `emphasis` {}                          existing: caption word emphasis
- `sfx` {src | id}                       `id` = pack sfx id from sfx/manifest.json (resolved to file); `src` = path
- `punch` {level: "W"|"M"|"T"}           NEW instant framing change ON the word's start frame, holds until next punch/shot end.
                                         Ladder W=1.00, M=1.17, T=1.32 scaled around eye point (~0.38 of height). T only if take width ≥1440, else cap M.
- `transition` {id, params?}             NEW at a shot's FIRST word = transition INTO this shot from the previous shot. id = pack alias
                                         (transitions/aliases.json), e.g. "whip","push","zoomThrough","flash","dip-to-black","crossfade".
- `broll` {kind, layout, ...}            NEW motion-graphic B-roll over the anchored span while the voice continues.
                                         kind: "text"{text} | "stat"{value, label} (count-up number) | "list"{items[]} | "icon"{icon, text}
                                               | "clip"{src} (user/stock clip; blur-fill if not 9:16).
                                         layout: "full" (default) | "split" (b-roll top 55%, face bottom) | "pip" (b-roll full, face circle).
- `title` {text}                         NEW hook text on screen from 0.0–~2.5 s (top third, safe zone), ≤7 words.
- `lowerthird` {text, sub?}              NEW name/role strap.
- `endcard` {text, sub?}                 NEW CTA card over the last ~1.5 s (follow/save), loop-friendly.
- `callout` {kind: "underline"|"circle"|"arrow"} NEW hand-drawn highlight on the caption or overlay (optional, nice).
Style (script.style dict): `preset` name + overrides: font, caption ("bold"|"pop"|"karaoke"|"pill"|"boxed"|"minimal"), accent, text, bg,
  look {grain 0..1, vignette 0..1, grade: "none"|"warm"|"cool"|"teal-orange"|"mono"}, background (cutaway/broll bg family:
  "mesh"|"grid"|"paper"|"blur"|"solid"), pace ("calm"|"standard"|"punchy"), transitions (family), sfx_kit, music_mood.
Music (script.music): {src | id (pack music bed id) | mood, volume?}; default chosen from style.music_mood by reel length.
Presets (presets.py): at least 6 — bold-hustle (Hormozi), clean-pro (minimal B2B), beast-hype (MrBeast pop), editorial (serif/notebook),
  tech-explainer (grid/blueprint), desi-bilingual (Hinglish-ready: Devanagari-capable font). Each = full style above.

## Ownership (file-disjoint; never edit another team's files)
- TEAM DIRECTOR: schema.py (new cue validation, '#'-in-anchor crash fix via explicit occurrence syntax "phrase@2" while keeping "#2" working,
  homophone-anchor fix), new director.py, presets.py, lexicon.py, examples/demo/script-lines-only.json, tests/test_director.py,
  tests/test_schema_v2.py. `director.direct(script) -> Script` adds auto cues (params["auto"]=True, params["why"]) obeying the playbook:
  hook pattern interrupt ≤1.0 s (title + punch/whoosh), punch ladder cadence by pace profile (median visual-change 4.0/2.6/1.8 s, clustered,
  never metronomic, no 3 same levels in a row), B-roll 25–40% of runtime tied to concrete nouns/numbers (stat for numbers, list for
  enumerations, text otherwise), ≥90% hard cuts (transitions only at shot boundaries that are section changes, chosen by energy),
  SFX policy (whoosh on transitions, pop on overlays/titles, ding on stats; density cap ≤1 per 2 s), emphasis on numbers/money/negations,
  endcard on last shot. Existing manual cues are kept and win over auto ones. Deterministic (same input → same output).
- TEAM PICTURE: compiler.py (rewrite allowed; keep compile_project(timeline, out) and timeline_summary signatures), new stage.py
  (hard-link/symlink pack JS + fonts into <project>/assets/mp/), new src/reel_director/web/reel.mjs + reel.css (static runtime: transitions via
  pack transitions/lib/tx-dom.js applyDom proxy tweens, punches, broll scenes, captions families, looks, progress bar, title/lowerthird/
  endcard/callout), new src/reel_director/fonts/ (OFL fonts + OFL.txt; see FONTS below), tests/test_compiler_v2.py, tests/test_stage.py.
  Must fix review findings: cutaway/broll under captions (z-order), overlay stacking (shorten hold when next overlay starts), zoom pop with
  close zooms, asset basename collisions, run-past-root-duration on last words, captions chunk across a single ASR number word.
  Takes: picture <video muted> per kept segment; transitions stretch picture only (txPlan/span port) — voice audio comes from the mix.
- TEAM SOUND: new mixdown.py (mode A: bake voice segments with 8–12 ms fades at every cut, bed, SFX into mix.wav; ducking bed under
  voice ~10–14 dB with 60 ms attack / 250 ms release; SFX gain-staged by measured loudness; bed picked from pack music library by mood &
  length with beat grid; master -14 LUFS, true peak ≤ -1.5 dBTP verified AFTER AAC encode with a corrective trim loop),
  edit audio.py (fix: take leveling must never fall back to dynamic loudnorm/timestamp gaps — use measured linear gain + limiter;
  compensate afftdn delay; adaptive denoise by SNR (skip when SNR ≥ 35 dB); add deliver(render_mp4, mix_wav, out) remux),
  tests/test_mixdown.py. Reuse pack music/mixer.py if it fits (read-only import via sys.path), else own code.
- TEAM FIXES: textnorm.py, timing.py, cleanup.py, timeline.py, takecheck.py, studio/project.py, studio/static/* — apply the confirmed review
  findings (list in prompt). Tests: tests/test_review_fixes.py.
- INTEGRATOR (after all teams): __main__.py (new `direct` subcommand; `compile --preset X --no-auto`; build path uses director + mixdown +
  deliver), studio/runtime.py build steps, examples, e2e updates, renders, verification.

## FONTS (OFL only, from the npm registry @fontsource packages, woff2 latin + devanagari subsets only, ≤ 3 MB total)
Montserrat (800/900), Anton (400), Bebas Neue (400), Inter (variable or 400/700/800), Bangers (400), Instrument Serif (400/italic),
Noto Sans Devanagari (700/800), Archivo Black (400). Copy only the needed woff2 + OFL.txt into src/reel_director/fonts/<family>/ and record
name/version/license/source in src/reel_director/fonts/LICENSES.json. Install packages into a temp dir under work/, not the project deps.

## Quality bar (every team)
Deterministic, seek-safe (no Math.random/Date in page JS), files < 500 lines, unit tests green (.venv/bin/python -m pytest -q tests --ignore=tests/e2e),
measure before/after. Never access the real camera/mic. No git state changes. No rm -rf. Work dirs: work/v1-<team>/.
