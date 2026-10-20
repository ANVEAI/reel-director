# Editing pace for high-retention talking-head reels: rules for Reel Director

Area: editing-pace. Date: 2026-10-20. Research only. No video or media was downloaded. I read web pages, papers, vendor breakdowns and the local motion-pack research.

Target: 1080x1920 talking-head reels of 15-60 s. The creator only reads a script. Cuts, framing, B-roll, layout, transitions and the edit side of SFX come from rules.

## 0. Evidence labels and an honesty note

- **measured**: a number from a study, a dataset, or a count someone actually made (lab experiments, Cinemetrics-style analysis, a journalist's cut count, our own `refstudy.py` measurements).
- **consensus**: the same mechanism shows up in independent practitioner sources and does not contradict research. The direction is solid; the exact number is a default.
- **rule-of-thumb**: one vendor, one editor or our own house default. Tune it with retention graphs.

The plain truth: **no public, controlled study ties cut frequency in short-form talking-head video to retention.** Platforms publish no pacing thresholds. Nearly every "cut every N seconds" figure online comes from a vendor blog with no stated method, and these blogs contradict each other: 1.5-2 s, 1.5-3 s (TikTok), 2.5-4 s (Reels), 3-5 s, 3-7 s.

So this file builds on three things:
1. Measured attention and editing research: film ASL trends, edit blindness, arousal and memory, EEG.
2. A 2026 dataset of ~9.6K TikToks annotated by an LLM.
3. Creator breakdowns, used as a style ladder.

Thresholds stay as config, as in the local `lint.pace`.

The session hit its shared web-search cap (200 searches) partway through this research. As a result, these were **not** researched and are left as gaps:
- frame-level breakdowns of MrBeast **Shorts** specifically;
- Jenny Hoyos' Shorts method;
- Indian talking-head creators such as Varun Mayya and Ankur Warikoo.

Fetches of already-known URLs continued after the cap.

---

## 1. What is actually measured

| # | Finding | Source | Use for the director |
|---|---|---|---|
| M1 | Hollywood ASL fell from about 10 s (1930s-40s) to **under 4 s after 2000**. In recent films, **shorter shots carry more motion (r = -.46)**. Shot-length sequences increasingly follow a **1/f pattern**: runs of short shots and long shots cluster, the way attention fluctuates | Cutting et al. 2011, *i-Perception* 2(6) "Quicker, faster, darker", 160 films; Cutting, DeLong & Nothelfer 2010 *Psych Science* | (a) A 2-3.5 s ASL for talking head is *about cinema pace*, not faster. (b) Couple motion to short shots. (c) Vary shot length in clusters (1/f), not with uniform random jitter and never metronomically |
| M2 | A quarter of cuts between two views of the same scene go unnoticed. That rises to about **a third when the cut coincides with a sudden onset of motion**. Edits that follow continuity rules produce more edit blindness | Smith & Henderson 2008, *J. Eye Movement Research* | Snap jump cuts to a head move, gesture or the plosive onset of a word. Keep the eye line continuous |
| M3 | A faster rate of edits (camera changes *within the same scene*) raised physiological arousal, self-reported arousal and memory | Lang et al. 2000, *J. Broadcasting & Electronic Media* 44(1) | Punch-ins and angle changes within one take are cheap attention, not confusion |
| M4 | The limited-capacity model predicts that pacing plus arousing content raises encoding **until overload, after which encoding falls**. The 1999 TV study is the overload case. A 2007 radio study found no overload | Lang, Bolls, Potter & Kawahara 1999, JOBEM 43(4); Lang et al. 2007 | Do not stack fast cutting on top of dense information. Slow the edit when the line carries a number, a claim or a definition |
| M5 | Fast, chaotic editing (same narrative, more cuts, continuity rules broken) **inhibited blinking (more attention) but shifted brain activity from frontal to visual areas**. The authors' phrase: more attentional scope, less conscious processing | Andreu-Sánchez et al. 2018, *Neuroscience* 394:83-97 | Chaotic or "brainrot" pacing holds eyes but loses the message. For a founder or educational reel, organised pacing wins |
| M6 | Eye tracking of talking-head video found that changing the visual is the single biggest lever. **Residual fixation**: after a scene change the eyes stay where they were, so put the next frame's point of interest in the same spot. Overlays tied to the audio were looked at **82%** of the time | NN/g, Pernice 2017 (case study, small n) | Scale punch-ins around the eyes. Return from B-roll to the same eye position. Overlays near the face band |
| M7 | Vertical video, n = 40, own phones: a **centred subject gave longer fixations and fewer saccades** than a subject who moved around the frame | RealEye blog on Baig 2025 (summary only, no numbers published) | Keep the face horizontally centred. Do not reframe the face left and right between cuts |
| M8 | 9,649 Estonian brand/organisation TikToks, 77 variables annotated by an LLM. **Editing pace (4 levels) is a significant variable**: best level vs the rest is +34% likes, +41% shares, +39% saves. The paper does not say which level wins. **Binary "dynamic editing" (more than one cut per 3-4 s) was not reliable for likes (+5%, n.s.; +14% for saves only)**. "Jump cuts prominent" was n.s. on every outcome. The largest single effect was **original spoken audio** (about +83 likes against a median of 253). Matching the common format of the field also predicted more likes (+33% per SD of similarity): a "legibility" advantage | Paekivi & Karjus, arXiv 2606.16053 (June 2026, preprint) | **Fast cutting by itself is not the driver.** Pace that fits the content matters. The creator's own voice talking to camera is the asset. Familiar grammar beats novelty for its own sake |
| M9 | MrBeast, 3 Mar 2024: he slowed videos down and wanted scenes to "let ... breathe". Tubefilter compared 60 s from the midpoint of a March 2023 video with a newer one: **the 2023 video had 16 more cuts**. In the earlier "retention-edit" era an editor described a **new cut every 1.3-1.5 s, each under 2 s** | Tubefilter newsletter, 5 Mar 2024; Gigazine 2024 quoting editor Dara Pesheva | The 1.3 s overstim cadence is the *old* ceiling. Views rose after the slowdown, but that is confounded (by budget, topics and so on), so read it as direction, not proof |
| M10 | Our own refstudy measurements of X references: (a) one talking-head take at **188 wpm**, **0 hard cuts**, the speaker shrinks to **PiP during diagrams**, dense overlays: 536K views, 283x followers. (b) A 106 s talking head with slot words: **40 cuts, ASL about 2.65 s**, tier B (looks boosted). (c) Tier-A launch films: **median shot about 2.8 s**; one launch film median 1.93 s | motion-pack `docs/research/reference-round3-2026-10.md`, `success-patterns.md` | Proof that a one-take plus overlays/PiP edit can reach. 2-3 s is the measured centre for edited pieces |
| M11 | YouTube Shorts has counted a view on start or replay since 31 Mar 2025 | MediaPost, Brandwatch (in local edit.md) | Loop seam and first-frame energy feed the view count directly |
| M12 | Compressed-speech studies: comprehension often breaks down **above about 225-275 wpm**. Removing pauses helps mostly at very high rates | Older lab studies (Arons review; Rocco 1969) | Cap effective speech rate after silence removal (rule S4) |

Platform-policy context (sourced, not about pace): YouTube's 15 Jul 2025 YPP update renamed "repetitious" content to **"inauthentic content"**, aimed at mass-produced and templated videos. In January 2026 Mosseri argued that imperfection and rawness will signal authenticity as AI floods feeds (secondary reporting). For us, a recognisable auto-edit template is now a platform and audience liability, not only an aesthetic one.

---

## 2. The creator style ladder (vendor breakdowns: estimates, not measured)

Shot length per creator, from Choppity's "recreate the style" pages (2025-26) and OpusClip's 2026 aesthetics list. These are a tool vendor's eyeball estimates, but they form a consistent ladder:

| Style | Shot length | Punch-ins | Captions | B-roll | Sound | Feel |
|---|---|---|---|---|---|---|
| "Brainrot stack" (OpusClip) | 0.6-0.8 s | n/a | 3-colour kinetic | gameplay underlay | ASMR layer | max scope, min processing (M5) |
| **Alex Hormozi** Shorts | **1-3 s jump cuts**, zero dead air | **10-20%**, alternating centred medium and tight close-up; speaker fills **at least 60%** of frame | uppercase heavy sans (Montserrat-Black-like), white with thick black stroke, **active word yellow**, 2-4 words, lower third, pop with small bounce, from frame 1 | minimal (sources conflict) | no SFX on cuts (2025+ version), subtle low music, close mic | the template everyone copied |
| Tom Noske | 1-4 s | face fills **70-80%**, shallow DOF | yellow/orange caps with 3D shadow, or single white words | **B&W letterboxed cinematic B-roll as rhythm breaks** | music rises under B-roll and drops for speech; impact on text reveals | premium-creator |
| Codie Sanchez | 2-5 s, jumps between angles | medium | white multi-line blocks, text-heavy listicle hook in frame 1 | occasional | voice-led, light music | approachable business |
| Ali Abdaal | 2-5 s, **cuts at thought transitions** | wider medium, off-centre to leave room for text | phrase-by-phrase handwritten text *beside* the speaker, yellow keywords | none noted | barely audible lo-fi | calm intellectual |
| Leila Hormozi | **3-8 s**, few jump cuts, **pauses kept** | minimal; consistent framing | often none burned in | none | **no music** | authority by restraint |
| "Talking-head static" founder (OpusClip 2026) | **one shot, no cuts** | none | text slightly off-centre, hard-cut paragraphs | none | voice | anti-edit authenticity |
| Green-screen explainer (OpusClip 2026) | visual swap **every 4-6 s** | n/a | n/a | the background *is* the B-roll | clean VO, minimal music | news / commentary |

The "Hormozi style" as of 2026: the mechanics still work (silence removal, punch-ins, word-level captions, big hook text). Commentators (vendor, opinion) say the *look* reads as copycat "guru content": the default yellow/green heavy font, emoji on every line, and an SFX on every move. The update is "dynamic minimalism": the same cuts, clean sans, brand-colour keyword, fewer pops, purposeful B-roll.

MrBeast lessons that transfer from the leaked production memo (long-form; authenticity unconfirmed by the company):
- Front-load the opening.
- The opening must match the promise of the title and thumbnail immediately.
- Compress time early.
- Place "re-engagement" beats at fixed points (about minute 3 and minute 6 in long-form).
- Stair-step the stakes.
- Do not signal the ending early, and end abruptly.

Scaled to a 30-45 s reel:
- hook ≤ 3 s;
- promise by about 5 s;
- re-engagement beats about every 8-12 s;
- the best payoff in the last 25%;
- cut out ≤ 0.5 s after the last word, or loop.

---

## 3. Rules for the deterministic auto-director

Notation:
- **Visual event (VE)**: any of
  - a hard cut that changes framing;
  - a framing step (punch in or out);
  - B-roll in or out;
  - a layout change (full, PiP, split);
  - a full-screen text card;
  - the start of a slow push.
- These are **not** VEs: a caption word advancing, a caption colour emphasis, or a small overlay pop.
- **S** = the profile's base ASL (rule P1).
- Reel Director cues anchor to words, so every time below resolves to the nearest word boundary in the right direction.

### P. Pace profile

- **P1 Choose one profile per reel and keep it.**

  | Profile | S (median VE interval) | Allowed range | Fit |
  |---|---|---|---|
  | `calm` | 4.0 s | 3.0-6.0 s | story, opinion, emotional, premium founder |
  | `standard` (default) | 2.6 s | 2.0-3.5 s | educational, product, B2B |
  | `punchy` | 1.8 s | 1.3-2.4 s | lists, tips, entertainment |

  Never go below a 1.3 s median: that was the overstim era (M9). [rule-of-thumb, anchored on M1, M9, M10 and the style ladder]
- **P2 Varied, clustered shot lengths.** Shot-length variation (CV) must be 0.35-0.75. Generate lengths with clustering (runs of 2-4 shorter VEs that build into a payoff, then one long hold of 1.5-2.5xS on the payoff line), not i.i.d. jitter. Fail the lint if CV < 0.25: that is the metronomic AI tell. [rule-of-thumb, anchored on M1's 1/f]
- **P3 Pace curve over the reel**, as a multiplier on S:

  | Section | Multiplier | Notes |
  |---|---|---|
  | Hook 0-3 s | 0.5-0.6 | |
  | Promise/setup to ~20% | 1.0 | |
  | Body | 1.0 | each beat accelerates (0.7) into its micro-payoff, then holds (1.5-2.0) |
  | Payoff, at 65-85% of runtime | 0.8 | densest proof and B-roll |
  | Close (last 10-15%) | 1.3-1.5 | face to camera, CTA, loop seam |

  [consensus: best payoff late and accelerate-then-hold are common across practitioners; the multipliers are rule-of-thumb]
- **P4 Max static interval** (no VE and no deliberate hold): `calm` 6 s, `standard` 4 s, `punchy` 3 s. A deliberate beat-hold after a punchline may add up to 1.2 s. [rule-of-thumb; the local R4 is 3.5 s]
- **P5 Min shot length.** A face shot carrying speech must last at least **0.8 s** (at least 0.5 s only inside a hook montage). B-roll must last at least **0.8 s**, or 0.5 s only in a deliberate 3-shot burst. Anything shorter reads as flicker. [rule-of-thumb]
- **P6 Information-density brake.** When a line has a number, a definition or a two-part claim, multiply S by 1.3 for that line and put no B-roll *over* the number. Show the number as an overlay on the face instead. [M4, M5 direction; the multiplier is a rule-of-thumb]

### H. Hook (0-3 s)

- **H1** Frame 0 is the face mid-word or the payoff visual. It is never black, a logo or a title card. [consensus]
- **H2** Have at least **2 VEs** in the first 3.0 s, and the first by **1.0 s** (for example: open tight, step to medium on the second clause, then a text card or B-roll flash). YouTube's ABCD playbook says to use multiple shots in the first 5 s with tight framing. [consensus; ABCD lift numbers unverified]
- **H3** Hook text on screen by 0.3 s, at most 7 words, saying the same idea as the spoken line. [consensus]
- **H4** Open on the tighter framing (M or T) and save the widest framing for later. A tight face reads at thumbnail size and in the swipe. [rule-of-thumb]

### J. Jump cuts and framing ladder

Most Reel Director cuts are retake and pause removals inside one camera angle. That makes them jump cuts.

- **J1 Framing ladder** (scale about the eye point):

  | Level | Scale | Note |
  |---|---|---|
  | W | 1.00 | eyes at y ≈ 0.36-0.40 of frame height |
  | M | 1.15-1.20 | |
  | T | 1.30-1.35 | only if the source has native pixels: effective width ≥ 1.33 x 1080 = 1440 px; Reel Director already caps capture at 1440 |

  With a 1080-wide source, cap scale at 1.15 and allow at most 1 T for the whole reel. [Hormozi breakdown 10-20%; 1of10 110-120% every 2nd-3rd cut; TimeBolt's defaults of 125/150/175% assume 4K; consensus]
- **J2 Every jump cut changes level by at least one step, which means at least about 15% in scale.** A scale change under 10% on a jump cut reads as a glitch. Film grammar puts the floor at about 20% in size or 30° in angle. [consensus]
- **J3 Level pattern.** Alternate around the home level M, for example M→W→M→T→M→W. Do not climb W→M→T in consecutive cuts unless it is the deliberate escalation into the payoff line. Never hold the same level across 3 consecutive jump cuts unless B-roll sits between them. [rule-of-thumb, local critic "no three same-scale shots in a row"]
- **J4 Eye anchor.** Across any face-to-face cut, the eye midpoint moves by no more than **5% of frame height and 5% of width**. Scale about the eyes, not the frame centre. [M6, M7; air.io gives "within about 10%"; 5% is our stricter default]
- **J5 Cut point.** Cut in the silence gap after the padded word tail (S2). Prefer the frame of a head or hand movement, or the onset of the next word's plosive, within ±3 frames. [M2]
- **J6 Reserve T** for the 1-2 most important lines in the reel (the claim, the punchline, the number). Using T more often devalues it. [rule-of-thumb]

### Z. Zoom types

The present Reel Director `zoom` cue eases in over 0.25 s and back out inside the shot. That is the "auto-zoom" look.

- **Z1 Cut-punch (default).** An instant scale change on a cut frame, 0 ms. This is what the J-ladder uses. [consensus]
- **Z2 Emphasis zoom (animated).** Ease in over 120-200 ms, outCubic, on the stressed word. Hold it to the next cut, **with no animated zoom-out**: reset on the next cut. At most 1 per 8 s and **at most 3 per reel**. Never on consecutive lines. [rule-of-thumb; an in-and-out "breathing" zoom on each sentence is the template tell]
- **Z3 Slow push** for any face shot held ≥ 3 s: linear 1.00→1.04-1.06 over the shot (≤ 2%/s). It counts as a VE only if the shot runs ≥ 4 s. Pair short shots with motion and long shots with gentle push. [M1 motion coupling; rule-of-thumb]
- **Z4** Never have more than one zoom or push active at once. Never zoom during B-roll that already has camera motion. [rule-of-thumb]

### S. Silence removal

- **S1 Pauses.**

  | Pause | Rule | Basis |
  |---|---|---|
  | Between sentences | trim to **0.15-0.30 s** (keep the breath) | [consensus] |
  | Inside a sentence, > 0.35 s | shorten to 0.10-0.18 s | [consensus] |
  | After a punchline or key claim | keep a **0.4-0.7 s** "beat hold" with the face still | [consensus; local `th.beatHold` 450 ms] |
  | Before a reveal | keep 0.3-0.5 s | [consensus] |

  Reel Director's current MAX_PAUSE of 0.45 is a loose ceiling for `standard`. Use 0.30 for `standard`, 0.20 for `punchy` and 0.50 for `calm`.
- **S2 Padding around kept words.**
  - Before the word: **60-80 ms**. Reel Director uses 80 ms, which is fine. TimeBolt's 10 ms left pad risks clipping word onsets with Whisper-grade timestamps.
  - After the word: **120-150 ms**. Reel Director uses 120 ms. TimeBolt says lower values clip speech.
  - Audio crossfade on every cut: **6-10 ms minimum, 2 frames (67 ms) preferred** (1of10).
  - Run continuous room tone under all cuts so the noise floor does not step.

  [measured tool defaults and consensus]
- **S3 Do not remove silences shorter than 0.5 s by detector alone.** Tools warn that < 0.5 s produces too many cuts (TimeBolt). Shorten those pauses with word-timed edits, or leave them. [rule-of-thumb]
- **S4 Speech-rate guard.** After cleanup, the effective rate should be 160-200 wpm. Our measured one-take reached 188 wpm.
  - Above 210 wpm, warn "breathless": restore breaths, starting with the inter-sentence ones.
  - Above 230 wpm, fail. That is near the 225-275 wpm comprehension cliff (M12).

  [M12 measured (lab, older); band is rule-of-thumb]
- **S5 Clipping checks.** Fail on a first syllable lost, an audible click, or a breath cut mid-way. Keep a breath whole or remove it whole. [consensus]

### B. B-roll / cutaways

- **B1 Coverage.**
  - `standard`: **25-40% of runtime**.
  - `punchy`: 30-45%.
  - `calm`: 10-25%.

  Viberoll gives 30-50%. The local default was 0.35-0.5. We stay lower because the arXiv data (M8) favours person-focused original audio, and the one-take PiP reference reached people. Above 50%, the speaker stops being the through-line. [consensus range; our choice is rule-of-thumb]
- **B2 Length.**
  - An insert lasts **1.2-3.0 s**.
  - Screen recordings, UI demos and charts may run 3-6 s if they have internal motion (a cursor, a counter).
  - Nothing static runs past 4 s.

  [consensus: the 2-4 s cluster across sources]
- **B3 Consecutive B-roll without the face**: at most **6 s** in `standard`. Above that it turns into a voice-over montage. [rule-of-thumb; a Reddit editor split shows both camps]
- **B4 Timing.**
  - Picture in **0-150 ms before** the anchor word: a micro J-cut. Out on a phrase end, never mid-word.
  - First B-roll at ≥ 2.0 s, unless the hook *is* a payoff visual.
  - The last 2-3 s return to the face for the CTA.

  [consensus; local `lead_ms` 150]
- **B5 Anchor B-roll on concrete nouns, numbers and claims, never on filler or transition phrases.** Show the *specific* thing (the actual UI, product, receipt, chart). Ban keyword-literal generic stock: saying "money" and showing a cash stock clip. Never reuse the same asset within 15 s unless it is a deliberate callback. [consensus; local R18]
- **B6 Return from B-roll to a *different* framing level than the one before it.** That gives a free jump-cut disguise, while still obeying J4's eye anchor. [rule-of-thumb]

### L. Layouts: PiP, split, green screen

- **L1 Use PiP when the visual is the content** (UI, screenshot, chart, tweet, code) and the speaker stays the anchor.
  - Speaker bubble or rectangle at **28-35% of frame width**, inside the safe zone (above the bottom ~35% UI band), on the side opposite the visual's focal point.
  - Hold the layout for **at least 3 s**, and usually for the whole idea.

  [measured reference M10a; layout sizes rule-of-thumb]
- **L2 Use a vertical split (top/bottom 50/50) only for comparison**: this vs that, before/after, claim vs evidence, reaction. Hold at least 3 s. At most 2 split segments per 30 s. [consensus: "split when both panels matter equally, PiP when one is primary"]
- **L3 Green-screen / cutout over a background image** is for commentary on an artifact (news, a post, a doc). Swap the background **every 4-6 s**. [rule-of-thumb, OpusClip 2026]
- **L4 A layout change is a level-2 interrupt.** Do not flip layouts back and forth inside 3 s. At most 3 layout changes per 30 s. [rule-of-thumb]

### T. Transitions

- **T1 Hard cuts make up at least 90% of all cuts.** Every face-to-face jump cut is a hard cut. **Never put a dissolve, fade or slide between jump cuts.** [consensus: Filmdaft, CapCut and local edit.md 2.1]
- **T2 Stylised transitions** (whip, zoom-through, glitch, flash) only at **section boundaries**: hook→body, topic shift, body→payoff, payoff→CTA. At most **1 per 10 s** and **3 per reel**. Each one needs a `reason` from the local enum. [consensus; counts are rule-of-thumb]
- **T3 Never a transition inside a sentence.** For B-roll in and out, use cuts with an L/J audio bridge, not effects. [consensus]
- **T4 Use a smash cut** (hard cut plus contrast in sound or level) for tonal whiplash or a comedy turn. It is the cheapest strong interrupt. [consensus]

### I. Interrupt ladder (scaled for talking head)

- **I1 Three levels.**

  | Level | Interval | Examples |
  |---|---|---|
  | **L1** | every 2-3 s | framing step, caption emphasis |
  | **L2** | every 5-8 s | B-roll, text card, layout change, Z2 |
  | **L3** | every 10-15 s | section change with a T2 transition, a music change or drop, the smash cut into the payoff |

  - No two L3s within 6 s.
  - Do not escalate the summed level in 4 consecutive 5-s windows (fatigue rule, kept from local virality.md).
  - For a 30 s reel that means 2-3 L3s in total: end of hook, the turn, the CTA.

  [rule-of-thumb; local ladder had L3 at about 9 s, widened here for talking head]
- **I2 Re-engagement beats** (the MrBeast memo, scaled down): one L3 plus a spoken open loop ("but here's the part nobody tells you") at about 35-45% of runtime in reels ≥ 30 s. Add a second at about 65-75% in reels ≥ 45 s. [consensus]

### X. Edit-side sound coupling (detail belongs to the sound area)

- **X1 SFX** only on L2/L3 VEs and Z2 emphasis. **None on dialogue jump cuts or L1 steps.** Average at most 1 SFX per 4 s, and at most 8 per 30 s. A whoosh peaks on the cut frame; an impact lands 0 to +1 frame late, never early. [consensus: the 2026 Hormozi-update commentary, AIR "SFX in moderation"; counts rule-of-thumb]
- **X2 Music** ducks under speech and may rise 3-6 dB under B-roll-only passages (Tom Noske pattern). Whether there is music at all follows the profile: `calm` may run without music (Leila Hormozi pattern). [consensus]

### C. Anti-cheap / anti-AI-template lint (fail or warn)

1. **Metronome:** VE interval CV < 0.25, or the same punch scale and ease repeated on more than 70% of cuts. *(fail)*
2. **Breathing zooms:** an animated zoom in and out inside the same shot, or a zoom on more than 50% of sentences. *(fail)*
3. **SFX on every cut**, or an emoji or sticker on more than 1 line in 4. *(warn)*
4. **Default template captions:** the stock heavy-yellow or green-stroke look with no brand colour; more than 2 caption colours; captions over the mouth, or in the top ~14% or bottom ~35% UI zones. *(warn)*
5. **Literal or generic stock B-roll**, AI B-roll with visible artifacts, or B-roll unrelated to the claim. *(fail if detected or flagged)*
6. **Breathless audio:** > 210 wpm after cleanup, zero breaths for > 15 s, clipped onsets, clicks, room-tone steps. *(warn/fail per S4/S5)*
7. **A transition on more than 10% of cuts**, any dissolve between jump cuts, or a glitch or flash without a reason. *(fail)*
8. **Upscaled punch** beyond native pixels (soft face), or a jump-cut scale step < 10%. *(fail)*
9. **Teleporting head:** the eye anchor moves > 5% between face shots. *(fail)*
10. **No quiet moment:** no beat-hold ≥ 0.4 s anywhere in a reel ≥ 20 s, or the interrupt level never drops. *(warn)*
11. **Layering overload:** more than 3 independently moving elements on screen at once (face, caption, overlay, plus B-roll motion). *(warn; M5)*
12. **Logo or intro card at frame 0**, or an outro card that holds more than 1.5 s after the CTA on a loop-intended reel. *(fail)*
13. **Over-coverage:** B-roll above 50% or a face absence above 6 s in `standard`. *(warn)*

### F. Format presets (all built on the rules above)

| Format | Profile | B-roll | Layout | Notes |
|---|---|---|---|---|
| Founder opinion / story | calm | 10-20% | full face | 1-2 T moments, music optional, long beat holds |
| Educational / how-it-works | standard | 25-35% | PiP for UI | P6 brake on numbers |
| Product demo | standard | (screen = content) | PiP 60-80% of runtime | swap screen visuals every 4-6 s |
| List / tips (3-5 items) | punchy | 30-40% | full | one L2 per item boundary, number card per item |
| Commentary on an artifact (post, news, competitor) | standard | — | green-screen/cutout | background swaps every 4-6 s |

---

## 4. Concrete pace budget for a 30 s `standard` reel (worked example)

Hook: 0-3 s

| Time | Event |
|---|---|
| 0.0 | T-framing face, hook text |
| 1.0 | jump to M on clause 2 |
| 2.2 | specific B-roll 1.2 s (the payoff object) |

Promise: 3.4-6 s
- M face, open loop.
- Hard cut to W at about 5 s.

Body: 6-20 s, three micro-beats
- Each beat: face (M/W alternate) → B-roll or PiP 1.5-3 s on the concrete noun → face hold on the beat's point.
- One L3 at about 12 s (section change: whip + music lift + spoken "but").

Payoff: 20-26 s
- The densest stretch: proof B-roll or UI, 2 quick inserts (1.2 s each), then a **T punch** on the payoff line.
- Beat-hold 0.5 s.

Close: 26-30 s
- M face, CTA spoken plus text.
- Cut ≤ 0.4 s after the last word, or a loop line that hands back to frame 0.

Totals:
- about 12-14 VEs, median interval about 2.4 s, CV about 0.5;
- B-roll/PiP about 30%;
- 2 stylised transitions;
- about 6 SFX.

## 5. Gaps worth closing next (when search budget allows)

- MrBeast **Shorts** frame-level grammar (cut count, caption placement, VO vs on-camera share). Today we have only long-form memo principles and editor quotes.
- Jenny Hoyos' Shorts method, and Indian talking-head creators (Varun Mayya green-screen, Ankur Warikoo, Dhruv Rathee Shorts), as the closest audience match for ANVE.
- Which `cat_editing_pace_sp` level wins in Paekivi & Karjus. The paper's Figure 3 / supplement or the authors' repo may show the "best level" per variable.
- Our own measurement: run `tools/refstudy.py` on public links (study, not download-and-keep, per ToS) of 20 top talking-head reels to get a real ASL/CV/punch-frequency distribution. Every number in section 3 should then be re-fitted.

## 6. Sources

Measured / research:
- Cutting, Brunick, DeLong, Iricinschi, Candan (2011) *Quicker, faster, darker*, i-Perception: https://pmc.ncbi.nlm.nih.gov/articles/PMC3485803/
- Smith & Henderson (2008) Edit blindness, JEMR: https://bop.unibe.ch/JEMR/article/view/2264
- Lang et al. (2000) edits, arousal, memory, JOBEM: https://scholars.cityu.edu.hk/en/publications/the-effects-of-edits-on-arousal-attention-and-memory-for-televisi/ (doi 10.1207/s15506878jobem4401_7)
- Lang, Bolls, Potter, Kawahara (1999) production pacing and arousing content, JOBEM 43(4):451-475 (citation only; overload result from the LC4MP literature; full text not read)
- Andreu-Sánchez et al. (2018) Neuroscience 394:83-97, summary: https://ddd.uab.cat/pub/uabdivulga/uabdivulga_a2019m2/uabdivulga_a2019m2a4iENG.pdf
- NN/g, Talking-head video 2.0 eyetracking (2017): https://www.nngroup.com/articles/talking-head-video/
- RealEye (2025) vertical video centred subject: https://www.realeye.io/blog/post/the-gravity-of-the-center-what-grabs-attention-in-vertical-videos
- Paekivi & Karjus (2026) arXiv 2606.16053: https://arxiv.org/abs/2606.16053 ; codebook: https://github.com/SanderPaekivi/tiktok_scraper_gemini_annotator (prompt.txt)
- Compressed speech review (Arons): https://ocw.mit.edu/courses/mas-632-conversational-computer-systems-fall-2008/ee5c83dac8079f6d25bb657f5ed393bd_arons_timecomp.pdf
- Marketing Trends Congress 2025, length vs engagement (inverted U, about 35 s optimum reported): https://archives.marketing-trends-congress.com/2025/pages/PDF/060.pdf

Journalism / primary-ish:
- Tubefilter on MrBeast's change of pace (Mar 2024): https://newsletter.tubefilter.com/p/mrbeast-change-of-pace-tweet
- Gigazine on retention editing / "Beastification" (Apr 2024): https://gigazine.net/gsc_news/en/20240403-retention-editing-beastification-may-be-end
- MrBeast production memo (transcription): https://www.alexanderjarvis.com/memo-how-to-succeed-in-mrbeast-production/
- YouTube "inauthentic content" YPP update (Jul 2025): https://www.plagiarismtoday.com/2025/07/08/youtube-targets-inauthentic-content/
- Mosseri on rawness / AI (Jan 2026): https://www.tubefilter.com/2026/01/06/adam-mosseri-instagram-warning-generative-ai-deepfakes/

Vendor / practitioner (rule-of-thumb tier):
- Choppity style pages: Alex Hormozi https://www.choppity.com/tools/recreate-video-editing-style/alex-hormozi/ ; Leila Hormozi …/leila-hormozi/ ; Tom Noske …/tom-noske/ ; Codie Sanchez …/codie-sanchez/ ; Ali Abdaal …/ali-abdaal/
- Joyspace, Hormozi style in 2026: https://joyspace.ai/hormozi-editing-style-2026-analysis
- OpusClip, 11 editing aesthetics 2026: https://www.opus.pro/blog/editing-aesthetics-dominating-short-form-2026
- TimeBolt feature/settings page: https://www.timebolt.io/features
- 1of10, jump cuts: https://1of10.com/blog/what-is-a-jump-cut/
- Viberoll talking-head checklist: https://viberoll.questera.ai/learn/talking-head-video-editing-checklist/
- AIR Media-Tech retention editing (long-form): https://air.io/en/youtube-hacks/advanced-retention-editing-cutting-patterns-that-keep-viewers-past-minute-8
- Shortzly pacing guide: https://shortzly.com/blog/short-form-video-pacing-editing-guide
- motion-pack: `docs/research/edit.md` (sections 3.3, 6, 7.2); `skills/motion-pack/references/` `virality.md`, `critic.md`, `platforms.md`, `success-patterns.md`; `docs/research/reference-round3-2026-10.md`.
- Reel Director current constants read (not modified): `cleanup.py` PAD_BEFORE 0.08 / PAD_AFTER 0.12 / MAX_PAUSE 0.45; `compiler.py` ZOOM_EASE 0.25 eased in and out; `capture.py` MAX_EFFECTIVE_WIDTH 1440.
