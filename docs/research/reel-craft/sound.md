# reel-craft / sound

Area: sound design for 1080x1920 talking-head reels (15-60 s). The creator only reads a script; everything else
(bed, ducking, SFX, silence, loudness, voice chain) is chosen by rules. Research only: no media downloaded, no repo
modified. Date: 2026-10-20.

How to read this:
- **Evidence grades**: A = primary/official page read this session; B = peer-reviewed paper (abstract/summary read) or
  consistent secondary sources; C = standard engineering practice / from memory, not re-read; D = vendor or blog claim,
  unverified or conflicting; L = local measured data from motion-pack reference rounds (motion-pack `skills/motion-pack/
  references/success-patterns.md`, `docs/research/sound.md`).
- **Confidence labels** on each rule: `measured` (a study or our own measurement supports the number), `consensus`
  (several independent sources agree; no single measurement), `rule-of-thumb` (a starting value to tune).
- The web-search budget for this run ran out near the end, so a few items are flagged "not verified" in section 11.

What already exists locally (read, reuse, do not duplicate): motion-pack `research/sound.md` sections 3 (mixing rules,
over-bed table, ducking envelope), 4.10 (transition sweeteners), 5 (loudness), 6 (talking-head sound table and voice
chain), 8 (BPM grid, presets); `research/expansion-audio.md` (licence verdicts for SFX/music sources);
`references/platforms.md`, `virality.md`, `launch-playbook.md`, `critic.md`. This file adds the web evidence from 2019-2026,
the trending-audio and licensing reality, SFX density, amateur-audio detectors, and maps it to Reel Director.

---

## 0. Reel Director today (read-only look at this repo, commit 7f21fa9)

| Where | What it does now | Gap against the rules below |
|---|---|---|
| `audio.py` | HPF 80 Hz + `afftdn nf=-25`, each take leveled to **-16 LUFS** (`TAKE_LUFS`), master `loudnorm` to **-14 LUFS / -1.0 dBTP**, LRA 11, AAC 192k, 48 kHz | No de-ess, no EQ, no compression; `loudnorm` falls back to dynamic mode when the source LRA exceeds the target LRA (ffmpeg docs, C), which can pump; TP -1.0 leaves little margin for platform re-encode (use -1.5) |
| `compiler.py` music | One bed, `data-volume` **0.18** (about -14.9 dB) for the whole reel, no ducking | A static gain cannot hit a voice-to-bed loudness difference; it depends on the bed's own loudness. Needs measured-bed gain + speech-keyed ducking (rules C1-C4) |
| `compiler.py` sfx | Cue `sfx` anchored to a word, `lead` param, default volume **0.8** | Volume is not relative to the voice and assets are not loudness-normalised; no density lint, no round-robin, no role table (section 5) |
| `takecheck.py` | Clip check (>10 samples at -0.3 dBFS), SNR fail <15 dB, warn <25 dB, silent < -40 LUFS | Good base. Add the amateur-audio detectors in section 8 (echo, gated holes, one-channel voice, take-to-take level jumps, lyrics under speech, LD under 10 LU) |

---

## 1. Platform loudness and sound-on reality

| Platform | What is known | Grade | Rule |
|---|---|---|---|
| YouTube (incl. Shorts) | Normalises to **-14 LUFS** since a 2019 change (before that, a non-LUFS reference "closer to -13"); louder uploads are turned down; quieter uploads are not reliably turned up (secondary sources agree) | B | Never master louder than -14: it buys nothing and costs dynamics. Never master quieter than about -15: quiet stays quiet |
| Instagram Reels | Meta publishes no loudness spec. Vendor guides conflict (-14 vs "-10 to -12 preferred"). Served audio is HE-AAC (one developer's DASH-manifest teardown) | D | -14 LUFS-I, TP <= -1.5 dBTP; test-upload to confirm |
| TikTok | No published spec; vendors split between -14 and -10..-12 | D | Same as Instagram |
| Spotify (reference only) | -14 LUFS documented; TP -1 dB (-2 if louder) | A (local, fetched earlier) | Confirms -14 as the de facto web number |
| Apple Podcasts (voice reference) | -16 LUFS +-1, TP <= -1 dBFS; a mono file reads about 3 LU lower than the same signal in stereo | B | Use -16 LUFS as the **voice stem** target before the bed and SFX are added |

Sound-on share (sets how much meaning may live only in audio):
- Reels: about **80% viewed with sound on** (EssenceMediacom with Meta, 2,300+ brand-lift studies, via Campaign UK) [B];
  ">75%" in a Meta Marketing API write-up [D]; "90%" from a Meta summit recap [D].
- TikTok: "over 93% of top-performing videos use audio" (TikTok Creative Accelerator), reported with a 16.05%
  impressions lift [B, platform-supplied]; 88% of users say sound is essential (TikTok) [B, platform-supplied].
- So: design sound-on first, but keep captions carrying full meaning for the 10-25% muted viewers (and X/LinkedIn,
  which autoplay muted).

---

## 2. Voice chain for phone and laptop mics (deterministic, ffmpeg-friendly)

Order matters: clean first, shape second, control third, level last.

| Step | Setting | Why / evidence | Confidence |
|---|---|---|---|
| 1. DC + high-pass | 80 Hz male / 100-120 Hz female voice, 12-18 dB/oct (pick from the take's measured F0: cutoff = min(0.8 x median F0, 120 Hz)) | Removes handling and HVAC rumble; 80-100 Hz is the cited range (iZotope-attributed cheat sheet; several guides); "no universal cutoff, set by ear" | consensus |
| 2. Denoise | Spectral, max **10-12 dB** reduction (ffmpeg `afftdn nf=-25` is in range). If using AI enhance (Adobe Enhance v2, Descript Studio Sound), run at a moderate strength, not 100% | Over-strong NR gives the "robotic / underwater" sound that listeners immediately read as amateur (Adobe community reports, forum consensus) | consensus |
| 3. De-reverb (only if RT60 estimate > 0.4 s) | Light, max 6 dB | Aggressive de-reverb thins the voice; prevention (soft room) beats repair | consensus |
| 4. Mud cut | -2 to -4 dB, 200-400 Hz, Q about 1 | Small cut "thins the boom"; iZotope-attributed 200-500 Hz narrow cuts | consensus |
| 5. Laptop/phone "boxiness" | -2 dB at 500-800 Hz, Q 1.2, only when the band is > 3 dB above a speech reference curve | Small-capsule mics in small rooms | rule-of-thumb |
| 6. Presence | +2 to +3 dB, 3-5 kHz, Q 0.9 | Intelligibility band; also the band phone speakers reproduce best | consensus |
| 7. De-ess | Split-band, 5-8 kHz, 3-4 dB reduction | Sibilance sits around 5-8 kHz; split-band is more transparent | consensus |
| 8. Compressor | 3:1, threshold so GR is 3-6 dB on loud syllables, attack 10-15 ms, release 100-150 ms | 2:1-3:1 natural voice, 3-7 dB GR (cheat-sheet range); local chain uses 3:1 / 12 ms / 120 ms | consensus |
| 9. Level | Two-pass `loudnorm` **linear** to -16 LUFS-I (set target LRA >= measured LRA so it stays linear), TP -1.5 | Apple Podcast voice target; leaves ~2 LU for bed + SFX to land the -14 master | consensus |
| 10. Phrase leveling check | Short-term (3 s) loudness of consecutive sentences within **+-3 LU**; else apply clip gain per sentence before compression | Level jumps between takes are a top amateur tell | rule-of-thumb |

Quality gates on the raw take (extend `takecheck.py`):
- SNR >= 25 dB ok, 15-25 warn, < 15 fail (already in repo).
- Noise floor in pauses after processing <= **-60 dBFS** ideal (ACX audiobook convention), <= -50 dBFS acceptable under a
  music bed. Re-measure after loudness gain: normalisation raises the floor (Premiere user report: below -60 became
  -50s/-40s after Match Loudness) [D].
- Voice must be on both channels. A lav/USB mic recorded into only the left channel is a classic phone/laptop mistake:
  if |L - R| loudness > 6 LU, sum to mono and dual-mono it.
- Sample rate 48 kHz, AAC >= 192 kbps in the master (repo already does this).

---

## 3. Dialogue editing (cuts, gaps, breaths, room tone)

| Rule | Number | Evidence | Confidence |
|---|---|---|---|
| Crossfade every audio edit | 5-10 ms equal-power, at a zero crossing; never the NLE 2-frame (60 ms) default inside words | Practitioner sources converge on 5-10 ms; a dialogue-editing book notes 2 frames is too long for precise dialogue edits | consensus |
| Never leave digital silence between words | Fill every removed gap with 40-80 ms of the take's own room tone at its natural level (about -55 to -60 dBFS) | A silent hole sounds worse than the click it replaced; room-tone jumps make edits audible (Descript) | consensus |
| Gap after a sentence | Trim to 150-300 ms (after a full stop about 250 ms; after a comma 80-150 ms); never below 60 ms (plurals and fricatives get eaten: Descript users report 10-15% of auto gap cuts delete too much) | Descript forum feature requests and user reports | rule-of-thumb |
| Breaths | Attenuate -8 to -12 dB rather than delete when they sit inside a phrase; delete when a cut already lands there | Standard podcast/VO practice | consensus |
| Planned pause | Exactly one deliberate 0.4-0.8 s pause allowed before the payoff line (the bed drops with it, rule C7) | Local reference rounds: 1-3 s reset dips before reveals in tier-A films (L) | rule-of-thumb |
| Lip sync | SFX and edits: audio at picture frame F + 1 (33 ms late at 30 fps); never more than ~15 ms early | ITU-R BT.1359 / ATSC windows: audio-early is noticed sooner than audio-late (local research, B-) | consensus |

---

## 4. Music bed: level, ducking, choice

### 4.1 Level and ducking (the numbers)

| # | Rule | Number | Evidence | Confidence |
|---|---|---|---|---|
| C1 | Voice-over-bed loudness difference (LD) during speech, measured as short-term LUFS of voice minus bed | **>= 12 LU hard floor, 15 LU default**, 18-20 LU when speech is fast (>170 wpm) or the bed is busy | Torcoli et al. 2019 (JAES, 22 listeners): recommend **>= 10 LU** commentary over music, >= 15 LU over ambience; **non-experts preferred LDs 4 LU larger than experts**. Phone audiences are non-experts, so 10 + 4 = 14, round to 15. Epidemic Sound: dialogue -18..-9 dB, music under dialogue -30..-35 dB (about 15-20 dB apart). Guide: "duck 15-20 dB under during talking" | measured (preference study) + consensus |
| C2 | Bed level with no speech (pre-hook music, B-roll montage, end card) | 6-9 dB above its ducked level, i.e. LD 6-8 LU under the voice's typical level; music-only intros at -16 to -18 LUFS-S | Epidemic Sound: music without dialogue -18 to -22 dB vs -30..-35 under dialogue (about 12 dB swing); local duck depth 9 dB | consensus |
| C3 | Duck envelope (deterministic, from word timings, not a compressor) | depth 9 dB (6-12), look-ahead 80 ms so the duck starts before the first syllable, attack 30-80 ms, release 300-500 ms | CapCut creator defaults 6-12 dB / 30-80 ms / 250-700 ms [D]; local house envelope 9 dB, 80 ms look-ahead, 350 ms release | consensus |
| C4 | Do not release inside short gaps | Only release the duck when the speech gap is **>= 0.8 s**; shorter gaps hold the duck (prevents pumping, the "breathing bed") | rule-of-thumb from pumping complaints | rule-of-thumb |
| C5 | Spectral carve under speech | Bed: -3 dB peaking at 2-4 kHz (Q 1) and -3 dB at 250 Hz while ducked | Local rule 5; speech intelligibility band (ANSI SII band importance, C) | consensus |
| C6 | No lyrics under speech | Instrumental only under any spoken word; a vocal track may play only in speech-free segments >= 2 s | Perham & Currie 2014: reading comprehension about 61% in silence, 55% with instrumental, 38% with lyrical music, liked or disliked (via secondary summary) [B]; irrelevant-speech effect. Note the Douyin study (IJA 2026, 6,606 videos): *vocal* background music raised likes, comments and shares, so vocals help in no-VO segments, not under the voice | measured |
| C7 | Planned dropout before the payoff/reveal line | Bed to -60 dB (or hum only) for 0.4-1.0 s, back on the first word of the payoff with an impact; once per reel | Local references: mid-film reset dips 1-3 s at -39..-52 dBFS before reveals; a 1.5-2 s gap ending exactly on the reveal (L); launch-playbook "late drop" | measured (L, small n) |
| C8 | Pre-hit vacuum | Dip the bed 2-4 dB for 100 ms (3 frames) ending on any hero hit | Local rule 6 | rule-of-thumb |

Gain formula for the compiler (replaces the static 0.18):
`bed_gain_dB = (voice_LUFS_S_median - LD_target) - bed_LUFS_S_median_measured`, then apply the C3 duck envelope on top
for no-speech regions (+depth). Measure the bed on the exact section used, not the whole song.

### 4.2 Choosing the bed by mood and tempo

Research basis: tempo is the strongest driver of **arousal**; mode (major/minor) is the strongest driver of **valence**,
and for non-musicians tempo can override mode (2008 / 2011 / 2013 / 2024 studies summarised in search; a 2023 study used
>110 BPM as "fast" and <90 BPM as "slow") [B]. Tempo bands below are rule-of-thumb mappings onto that finding.

| Script mood tag (from the script or a classifier) | BPM (snap to whole frames at 30 fps) | Mode / palette | Arrangement under speech |
|---|---|---|---|
| calm, trust, personal story | 70-90 (75, 90) | major or dorian; keys, soft pad, brushed hat | pad + soft kick only |
| explainer, how-to, business advice | 90-110 (100, 105.88) | major/mixolydian; pluck arp, light shuffle | drums + bass + pad; no lead |
| upbeat, product, motivation | 110-128 (112.5, 120, 128.57) | major; claps, plucks | drop the lead under speech |
| hype, announcement, montage | 128-150 (128.57, 138.46, 150) or half-time 140/70 | minor or major; 808, risers | strip to kick + bass under speech |
| curiosity, suspense hook, myth-bust | 60-90 with a tick/pulse | minor / chromatic cluster, drone | drone + tick |

Bed construction rules:
- One bed per reel <= 30 s; at most one bed change (a "drop" or switch on the turn line at 40-60% of runtime) for 30-60 s.
- No melodic lead in 1-4 kHz under speech; leads only in gaps (masking).
- Phone-speaker audibility: phone microspeakers resonate around 450-800 Hz (Knowles datasheets) and roll off below it;
  a measured phone speaker spec reads 230 Hz-10 kHz +-3.5 dB (HTC One). A bed whose energy is mostly < 150 Hz vanishes on
  a phone and booms on headphones. Require bed energy in 300 Hz-2 kHz (pad/keys/pluck) so it is audible on a phone.
- Backtime the bed: a phrase end or button lands on the last CTA word or the last frame. End on a ring-out or a hard
  button on the last downbeat, not a fade-out (local rule); loops crossfade 120 ms with < 3 dB RMS jump at the seam.
- Custom/owned music beats recognisable music for brand recall (MediaScience 2021, TikTok-commissioned) [B-]. Default to
  owned/synthesised beds (motion-pack `music/`), which also carry zero Content ID risk.

---

## 5. SFX vocabulary (event -> sound -> anchor -> level)

Normalise every SFX asset at import (max momentary loudness, 400 ms, to -14 LUFS-M; or peak to -1 dBFS for transients
under 100 ms), then apply the role offset below relative to the voice stem. "Re voice" = the sound's max momentary
loudness minus the voice's short-term loudness. Values harmonise the local talking-head table (motion-pack sound.md
section 6) with creator guidance; all are rule-of-thumb starting values.

| Event in the script/edit | SFX | Anchor | Level re voice | Max per reel (30 s) |
|---|---|---|---|---|
| Hook, first frame | impact/boom (sub 40-90 Hz + 2-5 kHz transient layer so it reads on a phone) | frame 0 + 1; voice starts <= 0.3 s | -3 to 0 dB (hero) | 1 |
| Reveal / payoff after a dropout | impact or "stab" in the bed key | first frame of the payoff word + 1 | -3 to 0 dB | 1 (hero tier: >= 8-10 s from another hero) |
| Riser into the reveal | 0.5-2 s (1 bar at bed tempo) noise sweep **plus a harmonic/tonal layer**; hard 5 ms stop 1 frame before the hit | ends at hit frame - 1 | -10 to -6 dB, rising | 1-2 |
| B-roll cutaway in/out, whip transition | whoosh, peak on the cut (starts 150-300 ms before), panned with motion | peak = cut frame + 1 | -14 to -10 dB | 3-4 |
| Keyword caption / overlay text appears | soft pop or tick (short, 1-4 kHz) | text-appear frame + 1 | -16 to -12 dB | 3-5 (keywords only, not every caption) |
| List item 1..n | pop with pitch walking up the bed scale (A5, B5, C#6, E6) | item appear + 1 | -18 to -14 dB | per item, <= 5 |
| Number / stat lands | ding/chime in the bed key | final value frame + 1 | -14 to -10 dB | 2 |
| Number roll-up counter | tick train, <= 12 ticks/s, round-robin pitch +-3% | per increment | -24 to -20 dB | 1 counter |
| Screen recording / typing / UI | keyboard or mouse click, round-robin takes | per keystroke shown | -22 to -16 dB | as shown |
| Photo, screenshot freeze, "snapshot" | camera shutter | freeze frame + 1 | -14 to -10 dB | 1 |
| Zoom punch-in on emphasis | low "thump" + tiny zip, or nothing | scale-peak frame + 1 | -18 to -14 dB | on <= 1 in 3 punch-ins |
| Jump cut | none, or 6-10 ms "cut tick" | cut + 1 | -24 to -20 dB | optional |
| "Wait..." / pattern interrupt / myth-bust | record scratch or tape-stop (comedy), error buzz (myth) | event + 1 | -14 to -10 dB | 1 |
| CTA / end card | sonic logo (section 7) | logo frame + 1 | +3 to +5 dB over the bed, <= voice level | 1 |

Placement rules:
- An SFX overlapping a spoken word gets an extra -4 dB and must avoid the 1-4 kHz band (use a low thump or 6 kHz+ air
  instead) so it does not mask the consonants.
- Risers need a harmonic layer: the perceptual "looming" bias (rising-intensity sounds judged as approaching and
  prioritised by attention; Neuhoff 1998 Nature; Bach et al. 2008 Cerebral Cortex: rising intensity triggers orienting
  and amygdala activity) appeared for harmonic tones but not broadband noise in the rhesus study (Ghazanfar, Neuhoff,
  Logothetis 2002) [B]. A white-noise-only riser leaves attention on the table.
- Sync a short sound exactly with the on-screen keyword that matters: the "pip and pop" effect (Van der Burg et al. 2008,
  JEP:HPP) showed a non-informative tone synchronous with a visual change sharply cut visual search time; a visual cue
  with the same timing did not help [B]. This is the scientific case for a pop on the keyword, and also why it should be
  reserved for the one word the eye must find.
- Round-robin: never the same sample twice in a row; seed per index, pitch +-3%, gain +-1.5 dB, timing exact (local).
- Tune tonal SFX (ding, pop, logo, riser tone) to the bed key.

---

## 6. SFX density (how many, how close)

Evidence is thin, so these are lints, not targets:
- Measured habit: a dataset of 16,942 e-commerce videos (mean 45.8 s) averaged **2.3 SFX per video** (about 3 per
  minute); tagged roles were prompt/attention 44%, transition 14%, humour 12%, action 11%, surprise 9% of 39,670 key
  moments; mean SFX duration about 2.2 s (D&M paper, arXiv 2408.13226, 2024) [B]. That is creator habit, not a retention
  optimum.
- Style analyses: the 2021 "Hormozi style" put a sound on "every movement"; a 2026 analysis calls stock whooshes generic
  and recommends "dynamic minimalism" (drop the stock SFX, keep subtle cues as "auditory bullet points") [D, opinion]. A
  style-recreation tool describes current Hormozi clips as **no SFX on transitions, quiet low-energy music, clean close
  voice**, jump cuts every 1-3 s, 10-20% punch-ins [D].
- Local hierarchy (motion-pack rule 4): hero <= 1 per 8-10 s and >= 90 frames apart; tier 2 <= 1 per 1.5-2 s on
  average; tier 3 any rate at -6 dB under tier 2.

Auto-director lint (rule-of-thumb):

| Preset | Tier-1+2 SFX per 30 s | Hero hits | Other limits |
|---|---|---|---|
| `clean` (default for business/education talking heads) | 4-6 | 1 | no SFX on > 30% of cuts |
| `energetic` | 8-12 | 2 (>= 10 s apart) | no SFX on > 50% of cuts |
| `none` (voice + bed only) | 0-1 | 0-1 (end logo) | for serious topics (grief, health, money harm) |

Always: no two tier-2 SFX within 1.0 s; no SFX in the first 0.3 s except the hook hit; no SFX inside the last 0.5 s
except the logo; SFX never louder than the voice except the single hero hit.

---

## 7. Sonic branding

| Rule | Number | Evidence | Confidence |
|---|---|---|---|
| Sonic logo at the end card, identical every reel | 1-3 s, 2-5 notes, singable after one hearing (Netflix "ta-dum" about 2.5 s, 2 notes; Intel about 3 s, 5 notes; secondary) | Ipsos 2020: sonic logos were the most effective distinctive brand asset measured (8.53 odds of appearing in a high-performing ad; secondhand via an Oxford thesis) [B-]. Audacy x Veritonic 2023 (113 ads, 330+ consumers): sonic branding raised ad recall **+17% radio, +14% podcast** [B, vendor study]. TikTok's own logo: 52% recognition, 73% positive emotion (Kantar for TikTok) [B, platform] | measured (vendor) |
| Pair the sound with the name | Logo sound lands on the same frame the brand name/handle appears | Veritonic coverage: about 7.5x more likely to identify the brand when the name is used with the sound [D, secondhand] | rule-of-thumb |
| Logo key = bed key | Last bed chord = logo chord | Local rule 7 | consensus |
| House SFX palette | Fix 6-10 house SFX (pop, whoosh, ding, impact, riser, click, shutter) tuned to the brand key; reuse across all reels | Consistency over time is what drives recall (Veritonic); custom beats recognisable audio on recall (MediaScience 2021) | rule-of-thumb |
| No sonic logo at the start | Frame 0 is the hook, not a bumper | Local: hook rules, no logo bumper (critic.md); TikTok: 90% of ad recall lands in the first 6 s (local launch-playbook) | consensus |

---

## 8. What makes audio sound amateur (detectors for `takecheck` and a mix critic)

Why it matters: in Newman & Schwarz 2018 (Science Communication; 97 + 99 participants), the same talks with poor audio
were judged worse, the speaker less intelligent and less likeable, and the research less important [B]. BBC/Channel 4/
Widex research (2011, 8,000-panel + 508 over-65s): about 70% had some trouble hearing speech; 62% of over-65s said
background music reduced enjoyment; poor speech intelligibility came more often from **recording** problems than from the
music mix [B, secondary].

| Tell | Detector (deterministic) | Threshold | Fix |
|---|---|---|---|
| Clipping | samples >= -0.3 dBFS | > 10 samples fail (repo) | re-record; declip only as rescue |
| Room echo / hollow voice | blind RT60 or C50 estimate on speech | RT60 > 0.4 s warn, > 0.7 s fail (rule-of-thumb) | light de-reverb (<= 6 dB); prompt the creator to record near soft furnishings |
| Noise / hiss | SNR, floor in pauses | SNR < 25 warn, < 15 fail; floor > -50 dBFS after processing warn | denoise <= 12 dB |
| NR artifacts ("underwater", "robotic") | spectral flatness drop + musical-noise detector, or simply denoise depth | reduction > 12 dB warn | lower NR / AI-enhance strength |
| Gated holes between words | frames < -80 dBFS inside a sentence | any fail | room-tone fill (section 3) |
| Level jumps between sentences/takes | short-term LUFS delta of adjacent sentences | > 3 LU warn, > 6 LU fail | clip gain per sentence |
| Voice on one channel | L-R loudness difference | > 6 LU fail | dual-mono the voice |
| Sibilance | 5-8 kHz band peaks vs speech RMS | > +6 dB spikes warn | split-band de-ess 3-4 dB |
| Plosive pops | < 150 Hz bursts exceeding the voice by 6 dB | any warn | HPF + clip-gain the pop |
| Music masks voice | LD during speech (C1) | < 10 LU fail, 10-12 warn | duck deeper, carve 2-4 kHz |
| Lyrics under speech | vocal-activity detector on the bed stem during speech | any fail | swap the bed section |
| Bed pumping | duck releases inside gaps < 0.8 s | any warn | hold the duck (C4) |
| SFX louder than voice | role offsets (section 5) | any non-hero SFX > voice | apply role gain |
| Same whoosh every cut | identical sample id consecutive / SFX on > 50% of cuts | warn | round-robin, thin out |
| Fade-out mid-phrase / abrupt music cut at end | bed end not on a phrase boundary | warn | backtime the bed |
| Too quiet on phone | master < -16 LUFS-I | warn (forum claim: below -16 is hard to hear on phone speakers [D]) | master to -14 |
| Over-loud / smashed | master > -12 LUFS-I or TP > -1 dBTP | fail | it gets turned down anyway (YouTube) and sounds squashed |
| Mic-tone change between shots | spectral-centroid / tilt delta between takes | > 3 dB tilt at 3 kHz warn | match EQ |

---

## 9. Trending audio and licensing reality

What the platforms actually say:
- **Instagram/Facebook**: the in-app music library "is intended for personal, non-commercial use", and certain business
  accounts and certain post types do not get it; those accounts may get the **Sound Collection** (14,000+ royalty-free
  songs and sounds, licensed for use inside Meta apps only) (Meta help page, via search summary) [A-]. A royalty-free
  tab/"RF" label appeared in Meta's Edits app in July 2025 per secondary sources [D]. Boosting a Reel that uses library
  music gets the boost rejected or the audio muted (vendor reports) [D]. The Reels editor has two sliders: the
  video's original audio and the added track (third-party help article) [B].
- **TikTok**: business accounts are limited to the Commercial Music Library (vendors say about 1M tracks) [D]; TikTok's
  Creative Center "Songs" trends can be filtered by "Approved for business use", which TikTok describes as royalty-free,
  professionally made sounds only (user-generated sounds excluded) [B, TikTok help via summary]. CML tracks are cleared
  for TikTok only [D].
- **YouTube Shorts** [A, Google help pages fetched]: vertical 1-3 min uploads count as Shorts since 15 Oct 2024; any Short
  **longer than one minute with an active Content ID claim is blocked globally**; songs added through the Shorts audio
  library create a special claim that cannot be disputed; songs added in an outside editor get ordinary claims; a 3-min
  Short can use most songs for up to 90 s (some 60 or 30 s); YouTube Audio Library royalty-free tracks are not claimed.
  **Revenue**: a Short with no music sends all its engaged-view revenue to the Creator Pool; **one track sends half**,
  two tracks one third; the creator keeps 45% of their allocation either way.
- Fingerprinting catches music regardless of how quietly it sits in the mix (vendor statement) [D, but consistent with how
  Content ID / Rights Manager work, C].

Does trending audio boost reach? Not proven. No primary Meta/TikTok statement with numbers was found; the "30-50% more
reach" figures circulating are attributed to HubSpot without a link and contradict each other [D]. What is supported:
TikTok says 93% of top-performing videos use *some* audio [B, platform]; a 2024 thesis on 519 Ryanair and Duolingo posts
found platform-native features including trending sounds consistently raised engagement [B, n = 2 brands]; the Douyin
study found vocal background music raised likes, comments and shares [B].

Rules for the auto-director:
1. Always render three outputs: `master.mp4` (voice + SFX + owned/cleared bed), `master_nomusic.mp4` (voice + SFX
   only, same loudness target), and stems (`vo.wav`, `sfx.wav`, `music.wav`). The no-music master is the one to post when
   the user wants to attach a trending sound in-app.
2. Never bake a commercial/trending song into an exported file, and never reuse Meta Sound Collection, TikTok CML or
   YouTube Audio Library audio in a file posted on a different platform.
3. YouTube Shorts default = owned bed or no music (keeps 100% of the Short's allocation and zero claim risk). A Short over
   60 s must have zero third-party music.
4. Business accounts (AnveVoice is one) default to owned beds; in-app sounds only from Sound Collection / CML /
   "Approved for business use".
5. In-app trending-sound recipe (the user does this at post time; the director writes it into the post checklist): post
   `master_nomusic`, add the sound, set the added track low enough that the voice stays clearly on top (target LD
   >= 15 LU; the slider is perceptual, so check by ear on a phone at mid volume), keep original audio at 100%.
   Whether this lifts reach is a hypothesis: A/B it (same script, sound vs no sound) before making it a default.
6. "Trending window" figures (peak 3-10 days) are unsourced [D]; if used, only attach sounds whose usage is still rising
   in the Creative Center / Reels trending list on post day.

---

## 10. Named examples studied (what each does with sound)

- **Alex Hormozi clips** (2021 vs now): 2021 style put an SFX on every movement; current clips (per a style-recreation
  tool) use no transition SFX, a quiet low-energy bed, a clean close-mic voice, jump cuts every 1-3 s, 10-20% punch-ins.
  A 2026 analysis says the stock "woosh" now reads as generic. Lesson: voice-led, SFX as punctuation only.
- **"Dynamic minimalism" (2026 creator trend, opinion)**: strip emojis, flashes and stock SFX; keep word-by-word captions,
  cuts, zooms and a few subtle cues.
- **Duolingo on TikTok**: mascot plus trending audio, first-person voice; the 2024 thesis credits trend-aligned sound for
  higher engagement than Ryanair, which leaned on original audio with mixed results (Ryanair also uses trending audio per
  a marketing write-up).
- **Daniel Schiffer B-roll/product reels**: reviewers single out the sound design and music as a core part of the
  appeal; every visible action gets a sound and transitions are matched to motion (no published breakdown of his chain).
- **Netflix "ta-dum"** (about 2.5 s, 2 notes), **Intel** (about 3 s, 5 notes), **TikTok's sonic logo** (Kantar: 52%
  recognition, 73% positive): short, consistent, name-paired mnemonics.
- **Local motion-pack reference rounds (28 + 22 measured films)**: VO-led films about -18 LUFS, music-led about
  -14.2; 13/28 open quiet for 1-2 s while frame 0 moves; 17/28 end >= 10 dB under the body; 61-89% of cuts in VO
  documentaries fall inside a speech line (the voice is the continuity); cut-on-onset >= 60% only predicts quality for
  music-led edits.
- **Iman Gadzhi style**: only freelancer and asset-pack descriptions were found (cinematic beds, transitions with SFX);
  no primary breakdown, so not used as evidence.

---

## 11. Open questions and things not verified

1. Instagram/TikTok loudness: still no platform spec or independent measurement. Do the upload test: one 20 s clip at
   -14 and one at -10 LUFS-I, private upload, compare in-app playback on a phone (motion-pack sound.md 5.3 open item).
2. YouTube "Stable Volume" (a mobile playback dynamic-range feature) could flatten planned dropouts on YouTube mobile;
   the search budget ran out before this was checked.
3. Premiere/CapCut auto-duck default values were not readable (Adobe help 403; CapCut 451). The duck numbers here rest
   on Torcoli (LD), Epidemic Sound (levels) and the local house envelope.
4. The Perham & Currie percentages come from a secondary summary; the Ipsos 8.53 figure is secondhand from a thesis.
5. Trending-audio reach effect: unproven; run A/B on own account before defaulting to it.
6. SFX density optimum: no retention study exists in what was found; the presets in section 6 are lints to tune with
   retention graphs.

---

## 12. Sources

Loudness and platforms
- Production Advice, YouTube loudness (-14 LUFS since 2019): https://productionadvice.co.uk/youtube-loudness/ [B]
- YouTube normalisation summaries: https://en.wikipedia.org/wiki/Audio_normalization , https://youlean.co/?p=30813 ,
  https://violetrecording.com/how-to-master-for-youtube/ [B/D]
- Social LUFS vendor claims (conflicting): https://opus.pro/blog/best-loudness-normalizers ,
  https://openclip.app/learn/audio-normalization [D]
- Instagram DASH teardown (HE-AAC): https://dev.to/ai_ai_c7d6c56f61323774fca/inside-instagrams-dash-manifest-from-mpd-to-segment-to-stitched-mp4-118e [D]
- Apple Podcasts -16 LUFS +-1, TP -1: https://podnews.net/article/lufs-lkfs-for-podcasters [B]
- Sound-on: https://www.campaignlive.co.uk/article/delivering-impact-rise-reels/1875392 (80%, EssenceMediacom/Meta) [B];
  https://zeroabove.co.uk/insights/video-marketing-3-key-insights-from-the-meta-marketing-summit/ [D];
  https://ppc.land/meta-reports-3-5-billion-daily-reels-shares-unveils-new-marketing-api-features-for-developers/ [D]
- TikTok audio: https://ads.tiktok.com/business/creativecenter/quicktok/online/tiktok_creative_accelerator (93%) ;
  https://www.searchenginejournal.com/tiktok-reveals-what-makes-a-high-performing-ad-on-its-platform/418657/ (93.02%, +16.05%) ;
  https://ads.tiktok.com/business/en/blog/roundup-how-to-use-power-of-sound-tiktok ;
  https://www.socialmediatoday.com/news/tiktok-shares-new-data-on-the-importance-of-audio-elements-in-on-platform-p/603739 [B, platform]
- TikTok sonic identity: https://newsroom.tiktok.com/en-ca/moving-to-the-beat-of-our-global-community-with-our-sonic-identity-ca (503 on fetch; numbers via search summary) [B]

Mixing, ducking, intelligibility
- Torcoli et al. 2019, JAES 67(12) "Preferred levels for background ducking...": https://cris.fau.de/publications/234640600 ,
  https://www.audioblog.iis.fraunhofer.com/?p=4251 , https://salford-repository.worktribe.com/output/1371938/background-ducking-to-produce-esthetically-pleasing-audio-for-tv-with-clear-speech [B]
- Geary, Torcoli et al. 2020, voice-over-voice LDs: https://salford-repository.worktribe.com/output/1341554/loudness-differences-for-voice-over-voice-audio-in-tv-and-streaming [B]
- Epidemic Sound mixing levels: https://www.epidemicsound.com/blog/audio-mixing-for-video [B]
- Ducking 15-20 dB guide: https://subscribr.ai/p/youtube-audio-sound-mixing [D]
- CapCut ducking numbers (search summary; page 451 on fetch): https://www.capcut.com/create/audio-ducking-for-clear-dialogue-in-video [D]
- BBC/Channel 4/Widex speech intelligibility: https://hearinghealthmatters.org/hearing-news-watch/2011/what-their-telly-tells-them-most-brits-sometimes-cant-tell ,
  https://tvtechnology.com/miscellaneous/the-importance-of-speech-intelligibility [B]
- Perham & Currie 2014 (Applied Cognitive Psychology 28:279-284): https://pure.cardiffmet.ac.uk/en/publications/does-listening-to-preferred-music-improve-reading-comprehension-p/ ,
  https://learningandthebrain.com/blog/but-i-study-much-better-with-my-music-on [B]
- Douyin engagement study (Dong et al., Int. J. Advertising, online 17 May 2026): https://researchportal.tuni.fi/fi/publications/what-leads-to-consumer-engagement-towards-short-form-videos-on-do/ [B]
- Newman & Schwarz 2018, Science Communication 40(2): https://openresearch-repository.anu.edu.au/items/67350c38-062b-4837-84c9-81419829d59d ,
  https://today.usc.edu/?p=8635 [B]

Voice chain and editing
- EQ/compression ranges: https://mixinggpt.com/blog/mixing-vocals-cheat-sheet-eq-compression-effects ,
  https://davinciresolveclub.com/fairlight-eq-dialogue/ , https://www.sageaudio.com/articles/how-to-make-voice-over-sound-better [D/B]
- De-essing 5-8 kHz, 3-4 dB: https://openclip.app/learn/de-essing.md , https://sounddesign.irpr.agency/glossary/de-esser/ [D]
- Adobe Enhance v2 strength reports: https://community.adobe.com/t5/adobe-podcast-discussions/enhance-speech-v2-is-here/td-p/14992650/highlight/true/page/2 ,
  https://soundsprofitable.com/press-release/adobe-podcast-team-launches-feature-update-enhance-speech-v2/ [D]
- Echo/reverb and NR artifacts: https://sounddesign.irpr.agency/guides/how-to-fix-echoey-audio/ ,
  https://www.swellai.com/blog/understanding-echo-and-reverb , https://www.vegascreativesoftware.info/us/forum/what-s-wrong-with-this-audio--87199 [D]
- ACX noise floor -60 dB and normalisation raising the floor: https://forum.audacityteam.org/t/getting-noise-floor-to-60-db-in-audacity/49263/4 ,
  https://community.adobe.com/t5/premiere-pro-discussions/floor-noise-is-below-60-db-until-i-adjust-for-rms-and-peak/td-p/11419375 [D]
- Crossfades and room tone: https://descript.com/blog/article/crossfade-audio-what-crossfade-is-and-how-to-edit-it ,
  https://www.taylorfrancis.com/books/9780080927626/chapters/10.4324/9780080927626-8 , https://manual.audacityteam.org/man/fade_and_crossfade.html [B]
- Descript word gaps: https://help.descript.com/hc/en-us/articles/10164807277453-Shorten-word-gaps ,
  https://feedback.descript.com/feature-requests/p/edit-word-gap-duration-from-the-script [D]

Phone playback
- HTC One speaker 230 Hz-10 kHz +-3.5 dB: https://www.soundandvision.com/node/111446 [B]
- Knowles microspeaker f0 800 Hz (1 cc cavity) / 450 Hz (baffle): https://static6.arrow.com/aropdfconversion/8afdd4ebeb3e0ec3780b8e8df60d8a1148267b0f/bms1511f11c08h3.5rplfpdf.pdf [A-]
- Microspeaker bass extension 630 -> 300 Hz: https://resolve.cambridge.org/core/journals/journal-of-mechanics/article/abs/bass-extension-of-microspeaker-system-on-mobile-device/2F765A1986D3D93F3D8A365ACC4C8A7A [B]

Perception
- Van der Burg et al. 2008, "Pip and pop": https://research.vu.nl/ws/files/2321477/Burg%20Journal%20of%20Vision%208(5)%202008%20u.pdf ,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC3393717 [B]
- Looming sounds: https://ideas.repec.org/a/nat/nature/v395y1998i6698d10.1038_25862.html (Neuhoff 1998) ,
  https://boris.unibe.ch/21529/ (Bach et al. 2008) , https://labs.sonicfield.org/library/sex-acceleration-brain-imaging-and-rhesus-monkeys-converging-evidence-for-an-evo [B]
- Tempo/mode and emotion: https://pmc.ncbi.nlm.nih.gov/articles/PMC11893886 , https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2018.02118/pdf ,
  https://jyx.jyu.fi/bitstream/123456789/41594/1/Fabio%20Morreale%20-%20The%20Effect%20Of%20Expertise%20In%20Evaluating%20Emotions%20In%20Music.pdf [B]
- Tempo of hits (122 BPM average top-20 in 2020): https://www.insidehook.com/music/songs-really-getting-faster/amp [D]

SFX density and style
- D&M e-commerce SFX dataset: https://arxiv.org/html/2408.13226 [B]
- Hormozi style: https://joyspace.ai/hormozi-editing-style-2026-analysis [D], https://www.choppity.com/tools/recreate-video-editing-style/alex-hormozi/ [D],
  https://riverside.com/blog/hormozi-style-videos [D]
- Reel sound design (qualitative): https://sounddesign.irpr.agency/guides/how-sound-design-improves-reels/ [D]
- Schiffer: https://lensvid.com/technique/epic-b-roll-fun-in-the-gingerbread-house-behind-the-scenes/ , https://nofilmschool.com/dynamic-b-roll-footage [D]
- Ryanair vs Duolingo thesis (2024, 519 posts): https://borykereso.uni-bge.hu/Record/dolg59055/Description [B]; https://thebrandberries.com/which-brands-are-nailing-their-tiktok-strategy-by-nour-hamam/ [D]

Sonic branding
- Audacy x Veritonic 2023: https://www.businesswire.com/news/home/20230213005383/en ,
  https://www.insideradio.com/free/study-finds-sonic-branding-boosts-audio-ad-recall-by-double-digits/article_b59d5d8e-abc1-11ed-aa19-371c4086bdc8.html [B, vendor]
- Ipsos 2020 sonic logo (via thesis): https://ora.ox.ac.uk/objects/uuid:a3db49b9-75e6-41c9-b31e-586b4f76b605/files/rt148fj539 [B-]
- YouGov sonic branding: https://yougov.com/articles/40973-invest-sonic-branding-boost-consumer-recall-and-re [B]
- Logo durations (secondary): https://mindmeld.substack.com/p/45-why-does-sonic-branding-matter , https://oakgen.ai/blog/sonic-logo-guide [D]

Licensing
- YouTube Shorts monetisation (revenue split): https://support.google.com/youtube/answer/12504220 [A]
- YouTube Shorts claims and 1-min block: https://support.google.com/youtube/answer/13053317 , https://support.google.com/youtube/answer/13486873 , https://support.google.com/youtube/answer/15424877 [A]
- Instagram music library / Sound Collection: https://help.instagram.com/402084904469945 (page body not retrievable; text via search summary) [A-];
  https://www.soundstripe.com/blogs/instagram-music-library , https://www.foximusic.com/blog/?p=587 [D]
- Instagram audio sliders: https://support.vistasocial.com/hc/en-us/articles/51949258945051-Adding-Trending-Audio-to-Instagram-Reels [B]
- TikTok CML and Creative Center filter: https://ads.tiktok.com/help/article/how-to-use-trends , https://www.shopify.com/blog/how-to-find-trending-sounds-tiktok ,
  https://www.soundstripe.com/blogs/why-can-i-only-use-commercial-sounds-on-tiktok , https://www.joinstatus.com/blog-for-brands/tiktok-commerical-music-library [B/D]
- Trending-audio reach claims (unverified): https://socialk.it/en/blog/instagram-trending-audio-strategy , https://influenceflow.io/resources/mastering-trending-audio-on-reels-in-2026-your-ultimate-guide-to-going-viral/ [D]
