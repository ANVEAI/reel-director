# Council position memos (2026-10-20, ~06:48 IST)

## CEO

**CEO position: Reel Director v1 (06:48 IST)**

The promise only holds if the default path (write lines, record, build, no flags) produces a reel that looks edited by a person. Ship that default tonight. The preset menu can wait.

**Must ship tonight**
1. Director on by default: preset clean-pro, pace standard (median visual change 2.6 s, CV 0.35–0.75), ≥90% hard cuts, ≤3 stylised transitions per reel, ladder W1.00/M1.17, T1.32 only when the crop is at least 1440 px wide.
2. Captions in the safe zone: centred at y=1110, width ≤696 px, bottom ≤1248, 2–4 words per chunk, ≤1 highlight per chunk, always above cutaways and B-roll. The current contact sheet puts them near y≈1285, inside the platform UI band.
3. Hook: title on screen at frame 1, 4–6 words, in y 300–560. First visual change by 1.0 s (punch plus pop). First spoken word by 0.20 s.
4. Sound, the biggest quality lever: −14 LUFS-I, true peak ≤ −1.5 dBTP measured after AAC encode. Voice at least 12 LU over the bed. 8–12 ms fades at every cut. At most 1 SFX per 2 s, none on jump cuts.
5. One-button build passes on the demo in clean-pro, bold-hustle and desi-bilingual. Check the contact sheets for text outside the safe rect, stacked overlays and buried captions. Print the time from record to finished reel.

**Cut or defer**
1. pip layout and callout: there is no face tracking, so the fixed eye point at 0.38 of height will crop creators who sit off-centre.
2. Auto icon and clip B-roll: there is no licensed icon set and no user clips. Keep them in the schema, but the director never emits them.
3. Endcard on by default: 9 of 10 top Shorts end on the payoff line. Make it opt-in, overlaid on the last line, and never let it lengthen the reel.

**Risks**
1. Resolution: a 1080p webcam cropped to 9:16 is 607 px wide, so it is upscaled 1.8x before any punch. Studio must warn about this and turn punches off below 1080 px.
2. Demo footage: there is no real human take in the repo (`work/real/raw` holds only `takes.json`). The fake-camera silhouette undersells v1. Either the founder records 3 lines at 10:00, or he approves a licensed stock clip.
3. Time: builders finish at 08:35, which leaves about 85 minutes before 10:00. Freeze scope at 08:35; anything still failing gets dropped, not patched.

**Disagreement**
The contract's "B-roll 25–40%" is a number for real footage (editing-pace rule B1). Our B-roll is synthetic text cards. At 35% the face disappears for a third of the reel and it looks like a template. Cap auto cards at 15–20%, for numbers and lists only (DESIGN's own budget was ≤25%).

## CTO

**CTO memo: architecture and risk (06:48 IST)**

**Must-haves for tonight**
1. **Stay on the installed HyperFrames 0.8.177, and prove it works by 07:30.** In e2e it rendered a 10.1 s reel in 11.8 s. Picture renders a 3 s probe: a tx-dom whip, a punch and a stat count-up. Frames at t=0.5, 1.5 and 2.5 must be byte-identical whether seeked or rendered in order (check with motion-stack seekcheck).
   - Flags: `--no-best-effort --experimental-fast-capture=false`, `--crf 23` for review, `--quality delivery` for the final.
   - If the probe fails, ship hard cuts only. No version swap tonight.
2. **One clock for picture and sound.** The compiler exports `resolve_cues(tl, fps=30) -> [{type,f0,f1,params}]` with frame = floor(t·30+0.5). Mixdown imports it read-only. Integrator test: every mixed SFX lands within ±1 frame of its picture event.
3. **Shared demo output by 07:30.** Director writes `work/v1-director/demo.directed.json`. Picture and Sound test against that file, not fixtures they made up. Two runs must give byte-identical output.
4. **A grep test for seek-safety in `test_compiler_v2`:**
   - Fails on `Math.random`, `Date`, `performance.now`, `requestAnimationFrame` and `setTimeout`, and on CSS `transition` or `animation`.
   - Runtime rules: one paused GSAP timeline; grain is a pre-baked tile picked by frame number; fonts use `font-display:block`, and the page awaits `document.fonts.ready`.
   - If an import fails, the page shows the red `#rd-error` card.
5. **Fix the captions seen on the contact sheet.** They sit at about 1290 px, below the 1248 px floor. They can't be read over busy footage, and they disappear under cutaways.
   - Fix: caption layer above `#stage`, centerY 1110, stroke 0.08 em.
   - Delivery gate, measured on the AAC file: −14 ±0.5 LUFS-I, true peak ≤ −1.5 dBTP.

**Cut or defer**
1. B-roll `split`, `pip` and `clip`: ship `full` only. The others fall back to `full` with a warning.
2. `callout`, the teal-orange and mono grades, and beat-snap. desi-bilingual stays Roman-script Hinglish until textnorm accepts Devanagari.
3. The run-past-root-duration fix: the verifiers rejected that finding.

**Risks**
1. tx-dom and hf-seek have only been rendered on 0.8.142 (DESIGN D8). Must-have 1 covers this.
2. Parameter names can drift across three teams working in parallel (for example B-roll `items` or SFX `id` lookup). Fix: the shared demo file, plus `validate` on the director's output by 08:00.
3. Disk: only 9.6 GB free (98% full), we can't `rm -rf`, and HyperFrames leaves temp folders behind.
   - Abort any render when free space drops below 3 GB.
   - At most 2 renders per team.
   - Never use `--video-frame-format png`.

**Where I disagree with the contract**
`direct(script)` only sees text, but it has to hit targets measured in seconds: median visual change of 4.0, 2.6 or 1.8 s, and B-roll on 25–40% of runtime. Make it `direct(script, words=None)`. It uses real word times when takes exist and 165 wpm (`timing.estimate`) when they don't, so it stays deterministic either way.

Also, the cap of one SFX per 2 s allows twice what the research supports. The research says at most one per 4 s, at most 8 per 30 s, and no SFX on punches except the hook hit.

## Creative Director

Creative Director position memo (06:48 IST)

The current frame sheet looks like a template. Captions sit at top 64% and 88% wide, which puts them in Instagram's bottom-35% UI band. Unspoken words show dimmed and the font is the default system-ui.

**MUST-HAVES**
1. **Captions, "karaoke-steady":** the 2-4-word chunk (≤18 chars/line, ≤2 lines) enters once (5 f, 0.94→1, no overshoot). The active word changes colour in place. No dimmed unspoken words.
   - Centre y 1110, bottom ≤1248, width ≤696 px.
   - Montserrat 800 caps 76 px, 0.08 em stroke, 0/4/0 shadow.
   - ≤1 highlight per chunk, ≤12% of words, colour plus 1.12× scale.
   - Fixed position, above B-roll.
2. **Punch:** instant, on the word frame, scaled at eye height y 0.38.
   - Home level M, alternating.
   - T ≤2 per reel, only on a number, claim or punchline.
   - 1080-wide takes: M ≤1.15.
   - crc32(title) jitter ±0.02 on the ladder.
   - The director never auto-emits the eased `zoom`.
3. **Transitions:** ≤ min(3, runtime/10 s), at section boundaries only.
   - Auto palette: whip{blurMax 0.05}, push, zoomThrough{scaleIn 1.3}, 8-10 f.
   - crossfade, dip, flash, glitch and lightLeak are manual-only.
   - No SFX on jump cuts.
4. **B-roll:** 1.2-3.0 s, picture leads the word by 5 f, first at ≥2.0 s, faceless ≤6 s, face for the last 2.5 s.
   - Layouts: full for text/stat/list, pip for clips, split only for comparisons.
   - One 10-12 f entrance, no idle motion.
   - One count-up per reel (40 f, tabular figures), spoken numbers only.
5. **Presets:**
   - bold-hustle: Montserrat 900 + #FFE14D
   - clean-pro: Inter 800 sentence-case pill on blurred self
   - beast-hype: Bangers + #00E676
   - editorial: Instrument Serif titles, boxed Inter captions
   - tech-explainer: boxed on grid
   - desi-bilingual: Noto Devanagari 800, line-height ≥1.5, letter-spacing 0, boxed
   - All presets: grain ≤0.08, vignette ≤0.18.

**CUT/DEFER**
- callout
- progress bar (off by default)
- teal-orange and mono grades
- handheld shake
- emoji

**RISKS**
1. **Too many SFX:** "≤1 per 2 s" still allows 15 per 30 s. Cap at 8 per 30 s, ≥1.0 s apart.
2. **Title, overlay and caption entering on one frame:** stagger them by ≥6 f.
3. **Metronomic rhythm:** the CV of visual-change intervals must be 0.35-0.75.

**DISAGREE**
The auto `endcard` on every reel. 9 of 10 top Shorts end on the payoff, and Hoyos cut 1 s for 83→88% retention.
- Make it opt-in: a ≤1.2 s chip, captions cleared for the last 4 f, and final framing matching frame 0 so the reel loops.
- Gate the auto `title` too: only when line 1 is over 10 words, a list or a number.

## CPO

CPO memo: creator experience

**MUST-HAVES TONIGHT**
1. **Phone-safe captions.** The contact sheet shows three problems. Captions sit at y≈1290, inside the bottom-35% UI band. They vanish under the cutaway. Frame 0 has no hook text. Fix: centre y1110, bottom ≤1248, width ≤696 px, 2-4 words, 72-84 px, stroke 0.08 em, layered above broll. The hook `title` shows from frame 1 at y300-560, 80-104 px, ≤6 words.
2. **Swap the preset without re-recording.** `compile --preset X` reuses the prepped takes and transcripts. The default is `clean-pro`: standard pace, mixed-case pill, no grade, no grain. All-caps Hormozi reads dated. The Build block shows "clean-pro · 14 auto cues".
3. **A clean teleprompter.** `direct` prints shot/word/cue/why. Today `cueText` in shots.js prints every cue into the line being read. It must skip `params.auto` and show "+N auto" instead.
4. **Override, then degrade.** Add `shot.auto:false`, `style.auto_off:[kinds]` and `--no-auto`. An auto cue that can't resolve is dropped and logged. Only a manual cue may fail the build, and its error names the shot and phrase.
5. **Hinglish works.** Captions default to Roman script. Lines in U+0900-097F use Devanagari with line-height ≥1.5, letter-spacing 0, no uppercase, and a box instead of a stroke. The lexicon gets ₹, lakh and crore. Add one Roman-Hinglish and one Devanagari e2e fixture.

**CUT OR DEFER**
1. `callout`.
2. `split`/`pip` layouts and `clip` B-roll. There is no face tracking, and split puts the face in the UI band.
3. Auto endcard: opt-in only, ≤1.5 s, never on loops of 35 s or less. Top Shorts end on the payoff.

**RISKS**
1. **desi-bilingual ships broken.** The HIGH finding "Hindi words cut from takes and dropped from captions" is unverified, so it is probably not on FIXES' list. Reproduce it by 08:35 or label the preset beta.
2. **Template look.** Gate on: visual-change CV ≥0.35, ≤1 graphic layer besides captions, transitions on ≤10% of cuts, ≤6 SFX per 30 s.
3. **Confirmed quit-triggers if FIXES slips:**
   - a second R deletes a take;
   - Build says "3/3 ready" when a take failed QA;
   - words the creator really said get cut.

**DISAGREE**
The contract sets B-roll at 25-40% for every preset. The face is the creator's brand. Use calm 10-15%, standard ≤25%, punchy ≤35%. Numbers go in a chip on the face, never full screen (editing-pace P6).

## Head of Sound

MUST-HAVES
1. Click-free voice bake (mode A only). Slice at frame×1600 samples from the compiler's own frame-quantised edit list (js_round). 10 ms raised-cosine fades at every edge, zero-crossing snapped (±2 ms). Gate: no HF spike >6 dB at cuts; A/V offset ≤1 frame; audio never early.
2. Voice: HPF 80 Hz. afftdn off at SNR ≥35, nr 6 at 25–35, ≤12 below, delay compensated. Linear gain to −16 LUFS-I, measured on KEPT spans. EQ −3 dB@300 Hz, +2 dB@4 kHz. PCM intermediates only.
3. Bed: bed_rel_vo_lu −5 and duck_db 10 give speech LD ≥15 LU (fail <12); gaps sit 5–8 LU under. Carve −3 dB@250 Hz/3 kHz. Instrumental only; bass-heavy beds get a −3.0 ceiling.
4. SFX gain = voice LUFS-S + role offset − manifest lufs_m_max. Offsets: hook hit −12, pop −14, whoosh/stat −16, lowerthird −18, plus −4 over words. Transient on F+1. Average ≤1 per 4 s, ≥1.0 s apart; none on jump cuts or plain punches; no id twice running. Stats use snd.ui.count_run (snd.ui.ding does not exist); unknown ids fail validation.
5. Decoded delivered MP4: −14.0 ±0.5 LUFS-I, TP ≤ −1.5 dBTP, short-term ≤ −9 LUFS-S, A/V durations within 1 frame. WAV ceiling −2.0, AAC-LC 256k/48k, ≤3 trim rounds, else the build FAILS. No dynamic loudnorm.

CUT/DEFER
1. Mode B.
2. Beat-sync rotation and cut snapping.
3. Sonic logo and room-tone hold (3.3 s logo vs a 1.5 s endcard; breaks the loop), de-esser, no-music master.

RISKS
1. Pack mixer's AAC probe targets −1.0, not −1.5: a default render() passes its own report and fails ours.
2. e2e voice is synthetic (LRA 1.1 LU; work/real is empty), so gates can pass on a tone. Test speech48.wav.
3. Loop beds are 15–17 s; a 45 s reel loops 3×. Above 32 s, use the 30/60 s non-loop beds.

DISAGREE
60 ms attack / 250 ms release. Cleanup leaves 150–300 ms pauses, so an unheld 250 ms release swells the bed in nearly every gap, and 60 ms leaks each phrase's first consonant. Use look-ahead 80, attack 15, hold 120, release 350 ms; no re-swell in gaps <0.6 s.