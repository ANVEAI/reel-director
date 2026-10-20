# Reel Director council: binding decisions for v1 (20 Oct, 06:56 IST)

The contract still governs ownership, deadlines and the quality bar.
- **Integrator:** apply these through your own files and send in-file changes to the team that owns the file.
- **08:35 freeze:** anything still failing gets disabled. Nobody patches it after the freeze.

## 1. Where the memos disagreed, and the ruling

| Topic | Positions | Ruling | Why |
|---|---|---|---|
| B-roll share | Contract 25–40%; CEO and CPO lower | Cap at 15 / 25 / 35% for calm / standard / punchy. Never pad to reach it. | The 25–40% research figure assumes real inserts. Ours are text cards. (R1, B5) |
| SFX density | Contract allows 1 per 2 s; CTO and CD want 8 per 30 s | Tighter cap wins: 3 / 6 / 8 per 30 s | Still inside the contract. Matches research rule T3. |
| Ducking times | Contract 60 / 250 ms; Sound | Sound's measured values win | Measured, not estimated |
| Endcard | — | Opt-in only | All five memos agree, plus research A12 and Hoyos |
| CD's title gate | CD | Rejected. Title goes on frame 0. | Research H3 |
| M1.17 punch on 1080-wide footage | — | Capped by the resolution guard (Z3) | Upscaling past the guard looks soft |
| `direct(script, words=None)` | CTO | Approved | The new argument is optional, so existing callers keep working. |
| Root-duration fix | — | Skip | The verifiers rejected that finding |
| Hindi words dropped | CPO | Reproduce by 08:35, or ship desi-bilingual labelled "beta" | The finding is not verified yet |

## 2. Decisions

### 1. Defaults and overrides
- clean-pro, pace standard, director on.
- `compile --preset X` reuses the prepped takes.
- Auto cues go to `directed.json`, never into `script.json`.
- Switches: `--no-auto`, `style.auto_off`, `style.auto_skip_shots`.
- An auto cue that can't resolve is dropped and logged. Only manual cues fail the build, and the error names the shot and phrase.

### 2. Pace (calm / standard / punchy)
- Median visual change: 4.0 / 2.6 / 1.8 s.
- Coefficient of variation 0.35–0.75. Below 0.25 fails.
- Max static: 6 / 4 / 3 s.
- First visual change ≤1.0 s, and ≥2 changes by 3 s.
- Never 3 of the same punch level in a row. No same-level cuts <1.2 s apart.

### 3. Punch
- Instant, centred on eye height (y = 0.38).
- Opens at M. First punch at 0.5–1.0 s.
- Ladder: W 1.00 / M 1.17 / T 1.32. Each level is capped at 1.10 × cropW / 1080.
- T only when cropW ≥ 1440. At most 1 per reel (2 if the reel is over 45 s). Only on a number or the payoff.
- If the cap is below 1.06, punches are off and Studio warns.
- Jitter ±0.02, seeded from crc32(title), never above the cap.
- The last frame uses the same punch level as frame 0.
- No auto `zoom`.

### 4. B-roll
- Full-screen only.
- At most 1 stat card per reel, counting up over 18 frames.
- Each insert 1.2–3.0 s, leading its word by 4 frames. First insert at ≥2.0 s.
- ≥1.5 s of face between inserts. Never more than 6 s without the face.
- Face on screen for the last 2.5 s and for the payoff.

### 5. Transitions
- ≥90% of cuts are hard cuts.
- Auto transitions per reel, for runtime T seconds:
  - standard: at most min(3, ⌊T/12⌋)
  - punchy: at most min(3, ⌊T/10⌋)
  - calm: none
- Section boundaries only, one family per reel, 8–10 frames.
  - push: clean-pro, tech-explainer
  - whip: bold-hustle, desi-bilingual
  - zoomThrough: beast-hype
- If the probe fails, hard cuts only.

### 6. Captions
**Placement**
- Centre x 520, y 1110. Width ≤696, bottom ≤1248, top layer.
- Safe rect: x 120–888, y 288–1248.

**Chunks and type**
- 2–4 words per chunk, ≤18 characters per line, ≤2 lines.
- 76 px, never below 64 px.
- 0.08 em stroke, or a box.
- Each chunk enters once: 5 frames, scale 0.94→1.
- The active word changes colour only. No dimmed words.
- ≤1 highlight per chunk, and ≤12% of all words highlighted.

**Title and layering**
- Title from frame 0 to 2.5 s: 4–6 words, y 300–560, 80–104 px.
- Text entrances ≥6 frames apart.
- ≤1 graphic on screen besides captions.

### 7. Presets
All presets keep grain ≤0.08 and vignette ≤0.18.

| Preset | Font and style | Accent | Pace |
|---|---|---|---|
| clean-pro | Inter 800, sentence-case pill | — | standard |
| bold-hustle | Montserrat 900 | #FFE14D | punchy |
| beast-hype | Bangers | #00E676 | punchy |
| editorial | Instrument Serif, boxed Inter captions | — | calm |
| tech-explainer | Boxed captions on a grid | — | standard |
| desi-bilingual | Noto Sans Devanagari 800. Roman script by default. Devanagari lines get line-height 1.5 and a box. | — | standard |

desi-bilingual's lexicon adds ₹, lakh and crore.

### 8. SFX
- ≥1.0 s apart, no repeats.
- Hook: `snd.hit.soft`, or `snd.hit.punch` for bold-hustle and beast-hype. It is the only SFX allowed on a jump cut or punch.
- No SFX in the last 0.5 s.
- Ids:
  - pop: `snd.ui.pop`
  - stat: `snd.ui.count_run`
  - whip: `snd.whoosh.whip_pan`
  - push: `snd.tx.push`
  - zoomThrough: `snd.tx.zoom_through`
- Unknown ids fail the build.

### 9. Audio
**Voice**
- 10 ms raised-cosine fades at every cut, aligned to a zero crossing within ±2 ms.
- High-pass at 80 Hz. Denoise only when the signal-to-noise ratio is below 35 dB.
- Voice set to −16 LUFS with a fixed gain, no dynamic loudness normalisation.

**Music bed**
- Voice ≥15 LU louder than the bed. Below 12 LU fails.
- Duck 10 dB. Look-ahead 80 ms, attack 15 ms, hold 120 ms, release 350 ms.
- Don't let the bed swell back in gaps under 0.6 s.
- Use non-loop beds for reels over 32 s.

**Delivered MP4 (measured after decoding)**
- −14 ±0.5 LUFS integrated.
- True peak ≤ −1.5 dBTP.
- Short-term loudness ≤ −9 LUFS.
- WAV ceiling −2.0 dBFS.
- AAC 256 kbps, 48 kHz.
- At most 3 trim rounds, otherwise the build fails.

### 10. Sync
- `resolve_cues(tl, 30)` converts with frame = floor(t·30 + 0.5).
- Demo directed by 07:30 and validated by 08:00.

### 11. Gates
Run on clean-pro, bold-hustle and desi-bilingual:
- Tests green, and re-runs byte-identical.
- Seekcheck and the seek-safety grep test pass.
- Contact sheets clean.
- Every metric above within limits. SFX and A/V within ±1 frame of their events. No clicks.
- The three quit-trigger bugs verified fixed.
- Record-to-reel time printed.
- Disk ≥3 GB free before each render. ≤2 renders per team. No PNG frames.

## 3. Deferred
**Visual**
- Split, picture-in-picture, clip and icon B-roll.
- Callout.
- Teal-orange and mono grades.
- Shake, emoji, progress bar.
- Endcard on by default.

**Audio**
- Mode B.
- Beat-sync.
- Sonic logo.
- Room tone.
- De-esser.

**Language**
- Devanagari input.
