# Sign-off reviews of v1 demo reels (2026-10-20, ~08:00 IST, before the final fix round)

## Creative Director

Score: 68/100. Verdict: ship-with-fixes.

What I checked: integrated loudness is -14.0 LUFS on all four reels, true peak -1.9 to -2.2 dBTP, and the tail fades to about -50 dB. A jump scan found no clicks. Pace numbers and determinism hold. The demo takes have no face and no reel has a transition or stat card, so framing is not proven yet.

MUST-FIX:
1. **Hook title is too small and repeats the voice.** fit() shrinks the 100 px title to about 70 px, below the council's 80–104 px and no bigger than the 76 px captions. It also repeats the spoken line word for word, so "Most creators" is on screen twice at 0.4 s. Files: `web/reel.mjs` fit() should wrap at an 80 px floor; `director.py` should write a shorter paraphrase in digits, e.g. "3 HOURS PER REEL?".
2. **Too many highlights per chunk.** The two-word emphasis "three hours" gives two accent words in one chunk (clean-pro, desi-bilingual), against the ≤1 rule. They share the active word's colour, and the number is spelled out. Files: `director.py` (one word), `textnorm.py` (write "3"), `reel.css` (add a second cue such as weight or underline).
3. **B-roll card repeats the voice.** "EDIT WAS FINISHED" shows from the word "What", about 1 s before those words are spoken, then sits above the matching caption. The card enters at frame 127 and the caption at 128, against the ≥6-frame rule. Files: `director.py` (a short label, not the spoken words), `policy.py` (enforce the gap).
4. **Punches collapse on 1080-wide takes.** Scales are exactly 1.00 and 1.10, with the jitter always clamped, so they repeat like a metronome. A 1080p landscape webcam turns punches off with only a log line. Files: `compiler.py` (vary below the cap), a Studio banner, and a `devices.js` capture-size check before the 10:00 founder session.
5. **One punch is hidden.** The return punch lands at 6.63 s under the B-roll card, which leaves at 6.94 s, at the same level used before the card. Fix in `policy.py`.

## CPO

72/100. Verdict: ship-with-fixes. This holds for the internal v1 only; the reels can't be an external demo until the founder's real footage is recorded at 10:00.

I checked this myself at 08:00 IST. Unit tests: 259 passed. HEAD is still 183ad68.

**Holds up:**
- All four MP4s measure -14.0 LUFS, true peak -1.9 to -2.2 dBTP, short-term max -13.6.
- No clicks at the cuts: the largest jump is 0.51× normal.
- The title is up from frame 0 inside y 300–560, and captions sit at y≈1110.
- B-roll stays at or under 22%, and the last 2.5 s stay on the take.

**Weak:**
- The gradient demo takes have no face, so the punch-ins can't be seen.
- No reel shows a transition, a stat card or a second SFX.
- bold-hustle and beast-hype have identical cues, and so do clean-pro and desi-bilingual.

**MUST-FIX**
1. Transitions and the 18-frame stat count-up have never been rendered on the final code. Render `work/v1-director/long.json` in bold-hustle and check the sheet at those frames. If either fails, disable it at 08:35 (`policy.py`, `web/reel.mjs`).
2. Punches switch off silently when the 9:16 crop is under 1041 px. A 1080p landscape webcam gives 607 px. `devices.js` `verdict()` says "OK — upscaled" from 720 px; make it say "no punch-ins" below 1041, and show the compiler's note as a banner in the reel dialog (`build.js`). Do this before 10:00.
3. The two pace measures disagree. The director's note says clean-pro and desi are "CV 0.22 metronomic", which fails the council's 0.25 floor. The JSON reports 0.36 because it also counts the 0.57 s lead-in. After the hook the gaps are only 1.55–2.50 s. Use one formula in `director.py` and `policy.py`, then cluster the punches.
4. Some caption chunks have two highlights: the emphasis covers "three hours" and the active word adds another. In desi, "hit record," has both words in the accent colour. Limit emphasis to one word (`director.py`) and give the active word and emphasis different colours (`reel.css`). Separately, one-word chunks like "SCRIPT," break the 2–4 word rule.
5. For 2.5 s the title repeats the caption word for word. Its entrance is only 5 frames from the first caption's (the minimum is 6). Reword the title with the figure first, as `hooks-structure.md` §8 says.

## Head of Sound

Score: 74/100. Verdict: ship-with-fixes.

Passes, measured at 08:01 IST:
- **Loudness:** -14.0 LUFS integrated, true peak -1.9 to -2.2 dBTP, short-term max -13.6, LRA 1.4, AAC 255 kbps at 48 kHz.
- **Cuts and ducking:** the voice is at -80 dB at every cut, so there are no clicks. The 10 dB duck holds through every gap shorter than 0.6 s, so the bed does not pump.
- **Levels and sync:** the shots match within 0.2 LU. Voice minus bed is 15.8 to 16.1 LU. The hook hit peaks on the punch frame (frame 18). 259 tests are green.

MUST-FIX:
1. **Hook hit lands off the beat** (`mixdown.py:185` `hero_time`). It now picks the policy's `open` punch at 0.15 s instead of the hook hit at 0.600 s, so the bed's bar downbeat moved away from the hit. The hit lands before the next beat by 67 ms (clean-pro, bold-hustle), 33 ms (beast-hype) and 167 ms (desi-bilingual, where the bed hits +15.5 dB at 0.76 s), which sounds like a double hit. Fix: skip `params.open` punches, or anchor on the `role=hook` sfx cue.
2. **The bed disappears on phone speakers.** 63–86% of its energy is below 150 Hz and only 8.5–14.5% sits in 300 Hz–2 kHz (rubric 4.2). Add a -4 to -6 dB low shelf in `mixdown`, then re-measure voice minus bed.
3. **The council's non-loop bed rule for reels over 32 s is not implemented.** `mixdown.py:169` keeps only loop beds, so the 10 non-loop pack beds are never picked, and `policy.py:440` only pins a bed up to 32 s.
4. **Every preset has exactly 1 SFX** (2.4 per 30 s; the rubric asks 4–6, or 8–12 for energetic). The B-roll card at 4.14 s enters with no sound. Add `snd.ui.pop` at -14 dB on B-roll entrances (director/policy).
5. **The bed fades out over the last 1.0 s, under the CTA** (`mixdown.py:227`). End it on a bar instead.

Smaller issues: audio leads the picture by 10–23 ms at 3 of the 4 cuts, still inside ±1 frame. Zero-crossing alignment of the cut fades is still not done. The demo voice is macOS `say`, so the voice chain is unproven on a real mic until the 10:00 footage.

## Head of Quality

**Score: 66/100. Verdict: ship-with-fixes.** Land these before the 08:35 freeze, or disable them under the freeze rule.

Delivery checks out on my own measurements of all four MP4s: −14.0 LUFS, −1.9 to −2.2 dBTP true peak, −13.6 short-term max, AAC 256k at 48 kHz, and no clicks at the four cuts. 259 tests pass and HEAD is still 183ad68.

**MUST-FIX**
1. **The reported pace hides a gate failure.** `policy.metrics()` counts the 0→0.57 s lead-in when it computes CV. Measured between changes, CV is 0.23 for clean-pro and desi-bilingual. The council fails anything under 0.25, and the JSON's own director note says "metronomic". Fix the metric and add one clustered change at standard pace (`policy.py` metrics/fill_static, `director.py` punches).
2. **Too many highlighted words per chunk.** Emphasis covers both "three hours", and the active word is coloured too, so the whole chunk turns accent. bold-hustle and beast-hype use the same colour for both, so you can't see the active word. Emphasise one word only and style it differently from the active word (`director.py` emphasis, `reel.css`).
3. **The hook title fails three ways.**
   - It copies line 1 word for word; HS08 asks for a paraphrase with the number first.
   - The captions repeat it directly below for 2.5 s.
   - `fit()` in `reel.mjs` has no minimum size, so it shrinks the title to about 69–75 px. The council range is 80–104, and the captions are 76.
4. **The text B-roll shows "EDIT WAS FINISHED" at 4.13 s, while the voice is still saying "What if the".** "edit" is spoken at 5.12 s, about 30 frames late against the council's 4. Start the insert at "edit" (`director.py` broll).
5. **Risk for the founder session at 10:00.** A 1080p landscape webcam leaves a 9:16 crop 608 px wide, so the resolution cap drops to 0.62 and every punch is silently turned off. Studio only writes a log line, and `policy.changes()` still counts the disabled punches. Add a banner in `build.js` and leave disabled punches out of the metrics.

**Notes:** None of the demos has a transition. The demo takes are gradients with no face. The integrator edited files owned by Picture, Sound and Fixes, and ran about 13 renders against a limit of 2 per team, so those owners need to sign off on the edits.