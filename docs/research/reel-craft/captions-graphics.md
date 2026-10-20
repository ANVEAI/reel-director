# Captions and on-screen graphics: rules for Reel Director (1080x1920, 15-60 s talking head)

Research notes, 2026-10-20. Area key: `captions-graphics`. Research only: no media was downloaded, and the reel-director and motion-pack-public repos were not modified. I read the local skills and research docs listed in the brief and ran three local measurements: WCAG contrast with `frame-design/scripts/contrast.py`, font metrics with fontTools on fonts already on disk, and visual-angle maths.

**Evidence labels used below**
- **[M] measured**: a peer-reviewed study, platform-published data or my own computation from published constants.
- **[V] vendor-measured**: a large corpus with an unpublished method. It shows correlation only.
- **[C] consensus**: several independent practitioner or vendor sources agree, with no controlled test behind them.
- **[R] rule of thumb**: a house or editor default. Tune it with your own retention graphs.

**Search budget note:** I used up the web-search budget for this turn. I could not verify three items by search: Instagram's "borders reduce recommendation" guidance, the primary page for Mayer's temporal-contiguity effect size, and YouTube's official Shorts text guidance. They are marked **UNVERIFIED** below.

---

## 0. Director defaults (copy into the caption theme)

```jsonc
{
  "captions": {
    "mode": "phrase-karaoke",          // show a 2-4 word phrase; highlight the active word inside it
    "chunk": { "minWords": 2, "maxWords": 4, "maxChars": 18, "maxLines": 2, "preferLines": 1,
               "minHold_s": 0.5, "maxHold_s": 2.5, "breakOn": [".", "?", "!", ",+pause>=0.25s", "pause>=0.5s", "discourse:but|so|and then|because"],
               "leadFrames": 2, "holdGap_s": 0.3, "clearGap_s": 0.6, "maxCps": 20 },
    "font": { "family": "Montserrat", "weight": 800, "case": "upper", "tracking_em": -0.01, "lineHeight": 1.05 },
    "size_px": { "base": 76, "min": 64, "emphasis": 1.18, "slamWord": 120 },
    "fill": "#FFFFFF",
    "stroke": { "color": "#000000", "width_em": 0.08 },          // 6 px at 76 px
    "shadow": { "x": 0, "y": 4, "blur": 0, "color": "rgba(0,0,0,0.45)" },
    "box_alt": { "fill": "rgba(0,0,0,0.78)", "pad_em": [0.18, 0.32], "radius_em": 0.22 },
    "highlight": { "color": "#FFE14D", "secondCue": "scale1.12+weight900", "maxShareOfWords": 0.15, "maxPerChunk": 1 },
    "anim": { "in": "pop 0.85->1.06->1.00 over 140 ms (outBack)", "activeWord": "colour swap + scale 1.00->1.10 in 4 f", "out": "cut", "maxAnimatedProps": 2 },
    "position": { "anchorX": 540, "centerY": 1110, "maxWidth_px": 696, "bottomLimitY": 1248, "faceClearance_px": 40 },
    "emoji": { "enabled": "tone!=serious", "maxPer10s": 2, "minGapChunks": 3, "size_capHeight": 1.2, "set": "Noto|Twemoji|OpenMoji|Fluent" }
  },
  "safeRect": { "strict":  { "x": [120, 888], "y": [288, 1248] },
                "organic": { "x": [90, 930],  "y": [270, 1248], "rightColumnBelowY840_maxX": 900 } },
  "hookTitle":  { "zoneY": [300, 560], "size_px": [80, 104], "maxWords": 7, "onBy_s": 0.3, "style": "box" },
  "lowerThird": { "name_px": [52, 60], "title_px": [40, 44], "hold_s": [2.5, 3.5], "inF": 12, "outF": 8 },
  "callout":    { "strokePx": [8, 12], "drawOnF": [10, 16], "syncToWord_f": [-3, 0], "minHold_s": 0.8, "maxVisible": 1, "contrastMin": 3.0 },
  "progressBar": { "enabled": false }
}
```

---

## 1. Platform UI safe zones (1080x1920)

### 1.1 What each platform publishes (2026)

The platforms publish safe zones **for ads only**. Organic posts sit in the same full-screen feed with the same username, caption, audio row and action column, so the ad templates are the best proxy.

| platform | top | bottom | left | right | extra exclusion | source and status |
|---|---|---|---|---|---|---|
| Instagram Reels | 269 (14%) | 672 (35%) | 65 (6%) | 65 (6%) | Right action column 227 px wide below y=1152. Ads with disclaimers keep the bottom 40% (768 px) clear. | Meta 14/35/6% via AdKit (updated 2026-09-10) and Socialync (read 2026-10-11) **[C, Meta-attributed]**. Billo (2026-06-16) reports that Stories and Reels share one safe zone from March 2026, with the bottom at "20-35%", and advises using the full 35%. |
| TikTok (In-Feed) | 240 | 660 | 120 | 120 | Right column 300 px wide below y=840 in the ad template; Socialync measured 180 px. The Anchor 4-line caption takes a 1014 px bottom. | AdKit says its numbers come from TikTok's 720x1280 labelled template x1.5 (2026-09-10). TikTok's help page (updated June 2026) publishes no numbers, only downloadable files: "the longer the caption, the smaller the safe zone" **[C]**. |
| YouTube Shorts | 288 | 672 | 48 | 192 | (none) | Read from Google's 1080x1920 vertical-ad safe-zone image (Google Ads help 13547298) via AdKit and Socialync **[C, Google-attributed]**. |

Shorts gained a "Clear screen" mode on 2026-06-25 that lets the viewer hide all overlays. The default view still shows the UI, so it changes nothing here.

### 1.2 Rectangles the director should use

- **Strict (default when one file goes to all three platforms) [M, derived]:** the union of the three published sets is **x 120..888, y 288..1248**, which is 768 x 960 px. Below y=840, TikTok's ad column (x > 780) also applies, but no talking-head caption ever needs to sit there because captions end at y 1248. Large text at y 840-1248 must keep its right edge at or left of 888.
- **Centred caption width [M, derived]:** a block centred on x=540 can be at most 2 x min(540-120, 888-540) = **696 px** wide in the strict rect. If width is tight, shift the anchor to x=504 (the centre of the safe rect). That buys 768 px and the 36 px offset is barely visible.
- **Organic, single platform [R]:** x 90..930, y 270..1248.
- **Faces and key text stay out of the bottom 35%** (y > 1248). This is the most repeated rule across sources **[C]**.

### 1.3 Conflicts with the local references

- `motion-pack type/safezones.js` per-platform rows (tiktok 150/480, reels 220/420, shorts 140/380) are **looser than the 2026 published templates**. The `conservative` union (269 / 672 / 65 / 120) is close, but the 2026 sources call for **top 288** (Shorts), **left 120** (TikTok) and **right 192** (Shorts). Recommendation: update the union to 288/672/120/192. That is a change to the pack, not to this research; the pack itself was not edited.
- `captions-overlay` places the caption line in "the bottom ~5-8% of canvas height". In 9:16 social, that band sits under the platform UI. **Do not use it for Reels, TikTok or Shorts.** It is fine only for 16:9 web or hero films.

---

## 2. Legibility model: how big text must be

Inputs, all **[M]**:
- **Critical print size** (the smallest text read at full speed) is about **0.2° x-height** for normally sighted readers. The fluent range runs from 0.2° to 2° (Legge and Bigelow 2011, J. Vision).
- **Phone viewing distance** has a mean of **32.2 cm** for web pages and 36.2 cm for text messages (Bababekova et al. 2011, n = 100 and 129).
- **Screen width:** a 6.1" phone is about 65.1 mm wide (1179 px at 460 ppi), and a 9:16 video fills that width, so 1 video px = 0.0603 mm.
- **Font x-height:** Inter 0.546 em, Manrope 0.540 em, Montserrat 0.525 em (fontTools, measured locally). I used 0.53.

| font px | x-height | angle | x critical size | chars per 860 px line (0.62 em / 0.72 em / 0.46 em average advance) |
|---|---|---|---|---|
| 40 | 21 px | 0.23° | 1.1x | 35 / 30 / 47 |
| 48 | 25 px | 0.27° | 1.4x | 29 / 25 / 39 |
| 56 | 30 px | 0.32° | 1.6x | 25 / 21 / 33 |
| 64 | 34 px | 0.36° | 1.8x | 22 / 19 / 29 |
| 72 | 38 px | 0.41° | 2.0x | 19 / 17 / 26 |
| 80 | 42 px | 0.46° | 2.3x | 17 / 15 / 23 |
| 90 | 48 px | 0.51° | 2.6x | 15 / 13 / 21 |
| 100 | 53 px | 0.57° | 2.8x | 14 / 12 / 19 |
| 120 | 64 px | 0.68° | 3.4x | 12 / 10 / 16 |

The three average-advance columns stand for three font widths:
- **0.62 em:** Inter Bold caps (measured 0.616 em).
- **0.72 em:** Montserrat Black caps (estimated; Regular measures 0.631 em).
- **0.46 em:** a condensed face such as Impact, Anton or Bebas Neue (Impact measures 0.459 em).

Rules that follow:
- **Primary captions: at least 64 px and 72-84 px by default** [M-derived plus R]. That gives at least 1.8x the critical size, a reserve for motion and glance reading and for older eyes. The low-vision literature suggests about 2:1 reserve for spot reading and 3:1 for fluent reading [R, from clinical practice]. It agrees with the local frame-design band of 64-80 px [C].
- **Any text that must be read: at least 40 px; 44 px preferred** [M-derived]. **This corrects the local house floor of 30 px for 9:16 labels.** At 30 px, a lowercase x-height subtends about 0.17°, below the critical print size. An all-caps label at 30 px (cap height about 0.23°) is only marginal. Honesty labels, lower-third titles and end-card fine print should be at least 40 px, or 36 px if all caps.
- **Single-word "slam" emphasis: 110-130 px.** This is the local `cap.impact` 6.5%-of-height size. Use it only for one or two words, because at 125 px a 696 px line holds about 8 characters [M-derived]. It must not be the default rail size.
- **Fit algorithm (deterministic):** measure the real width with the shipped font (HarfBuzz or canvas `measureText`). Never count characters. If the chunk is wider than maxWidth at the base size:
  1. Break it into 2 lines at a syntactic boundary.
  2. If it still does not fit, scale down, but not below 64 px.
  3. If it still does not fit, split the chunk.

---

## 3. Chunking and timing (word-by-word vs phrase)

### Evidence

- **Phrase chunks beat word-by-word display for reading effort [M].** Rajendran et al. 2013 (Perspectives 21(1)) eye-tracked four styles. Phrase-segmented subtitles gave the fewest fixations and crossovers and the shortest fixation durations, and chunking cut the time spent reading. Word-by-word display caused more switching between text and image.
- **Viewers prefer line breaks at syntactic boundaries [M].** Gerber-Morón and Szarkowska 2018 (JEMR 11(3); 68 hearing and 19 deaf or hard-of-hearing viewers).
- **Viewers keep up with fast subtitles [M].** Szarkowska and Gerber-Morón 2018 (PLoS ONE 13(6), n = 74) tested 12, 16 and 20 characters per second. Viewers coped even at 20 cps, and slow subtitles caused re-reading and frustration. So captions synced to speech at about 3-4 words per second are fine.
- **Short-form practice is 2-4 words visible, with the active word highlighted [C].** Sources: local `edit.md` (maxWords 4, maxChars 22); Blitzcut (2-3 words by default, 2-5 band); Viberoll (2-4 words); CapCut Hormozi tutorials (2-3 words).
- **Animated captions are common at the top [V].** OpusClip's Q1 2026 analysis found 80.2% of its viral-tier clips (top 10% by views) burn captions in and 78.6% animate them. The sample size behind those two figures is unclear and the data is correlational. **No controlled test isolates caption format** (Blitzcut's 2026 evidence review).
- **Captions in general [M, weak].** Facebook's internal tests (2016) found captioned video ads gained +12% average view time. Verizon Media / Publicis (2019, n = 5,616, self-report) found 80% of people were more likely to finish a video with captions. Treat the "+15-25% retention" and "2x" figures as vendor claims [V].
- **The accessibility objection [C, qualitative].** Deaf viewers on r/deaf and a Disabled World essay say per-word animation is "visual noise", ties reading speed to talking speed and outruns slow readers. A 1998 study cited by DCMP found better retention at 78 wpm than at 116 wpm for students.

### Rules

1. **Mode = phrase-karaoke.** Show a 2-4 word phrase and highlight the active word at `word.start`. Never reveal words one at a time across the whole video. One-word chunks are only for interjections ("Wait.") and planned slams (at most 1 per 5 s).
2. **Break a chunk** at any of [R, from the local embedded-captions grouping plus edit.md]:
   - a sentence end (. ? !);
   - a comma followed by a pause of at least 250 ms;
   - a pause of at least 500 ms;
   - a discourse reset ("but", "so", "because", "and then");
   - 4 words, 18 characters per line, or 2.5 s, whichever comes first.
   Never split a determiner or adjective from its noun, a number from its unit, or a verb from its particle.
3. **Timing:**
   - **In** = first word.start − 2 frames.
   - **Active word** = word.start (no lead).
   - **Out** = min(next.in, last.end + 0.25 s).
   - If the gap to the next chunk is under 0.3 s, hold the chunk until the next one (no flicker). If the gap is 0.6 s or more, clear the screen (silence reads as silence).
   - Minimum on screen is 0.5 s; merge anything shorter into a neighbour.
   - At most one caption chunk is visible at a time.
4. **Speed cap:** caption characters per second must stay at or below 20 [M, Szarkowska]. Above that, drop fillers (um, uh, "you know", "like", repeated words) and condense function words. Keep numbers, names and negations verbatim.
5. **Text cards that are not speech** (hook title, list items, stats) use the local hold formula: max(0.5 s, 0.35 + 0.28 s per word), with at most 3.5 words per second and at least 9 frames fully formed [R, local type module].
6. **Order of build** [R, local edit.md]: cut silences, then captions, B-roll, punch-ins, music, SFX, grade. Captions are rebuilt from word timings after every cut.

---

## 4. Typeface, case, stroke, shadow, box

### 4.1 Fonts (free licences only, real weights)

| role | pick | why | licence |
|---|---|---|---|
| Default rail (business, educational) | **Montserrat 800-900** caps | The Hormozi-style look; very heavy, wide caps [C] | OFL |
| Clean or premium | Inter 800, Manrope 800, Plus Jakarta Sans 800, DM Sans 800 | Calmer; sentence case works | OFL |
| Condensed (long words, more characters per line) | Anton 400, Archivo ExtraCondensed 800-900, Barlow Condensed 800, Oswald 700, Bebas Neue (caps only) | 0.45-0.5 em average advance, so about 30% more characters per line [M, metric] | OFL |
| Comic / MrBeast-like | Bangers (OFL) or Luckiest Guy (Apache-2.0) | Komika Axis, the font usually attributed to MrBeast, is freeware with unclear commercial terms; do not ship it | OFL / Apache |
| Maximum legibility | Atkinson Hyperlegible 700 | Glyphs designed to be told apart | OFL |
| Hinglish / Devanagari | Poppins 800 (Latin and Devanagari), Mukta 800, Noto Sans Devanagari 800 | One family for mixed scripts | OFL |

- **At most 2 families per video:** one for captions and one for titles. Request only weights the family ships, because faux bold is an AI tell [R, local frame-design].
- **Tracking:** −0.01 em for heavy caps at 72 px and up. Line height 1.0-1.08 for 2-line caps [R].

### 4.2 Case and punctuation

- **All caps is fine for 2-4 word chunks.** Arditi and Cho 2007 (Vision Research) found uppercase more legible near the size threshold and no different at larger sizes [M, small n]. Tinker found caps slow down *continuous* reading [M, older]. Neither applies to 3-word chunks.
- **Lowercase without punctuation reads as native and casual** [M, weak]. In Duraj and Szarkowska 2025 (J. Audiovisual Translation 8(1)), an n = 171 survey preferred lowercase, no-punctuation subtitles with emojis for casual or humorous TikTok content. Their field test was 2 pairs of videos with 246-953 viewers each, which is weak. Participants wanted correct punctuation for serious content.
- **Director rule:**
  - tone `hype`/`business` → caps;
  - tone `casual`/`story` → lowercase, no trailing periods or commas, keep ? and !;
  - tone `serious`/`medical`/`finance` → sentence case with punctuation.

### 4.3 Making text readable over footage [M, contrast.py]

| pair | contrast | verdict |
|---|---|---|
| White on mid-grey #808080 (typical footage) | 3.95:1 | **Fails 4.5:1.** Bare white text over video is not safe; a treatment is required |
| White on black stroke or box | 21:1 | Passes |
| Yellow #FFE14D on black | 16.1:1 | Passes. **Best highlight** |
| Hormozi-reported yellow #F7C204 on black | 12.7:1 | Passes |
| Green #00E676 on black | 12.6:1 | Passes |
| Red #FF3B30 on black | 5.9:1 | Passes, but 1.1:1 on grey footage, so it needs the stroke |
| Sky #4DA3FF on black | 8.0:1 | Passes |
| Purple #A855F7 on black | 5.3:1 | Passes, barely |
| **ANVE violet #4A18ED on black** | **2.64:1** | **Fails.** Never use it as a text colour on a black stroke. Use it as a **box fill with white text (7.94:1)** |
| Yellow #FFE14D on white | 1.30:1 | Never put yellow text on a light box |

Treatments, in order of robustness:
1. **Box** (solid or 75-85% black, padding 0.18 x 0.32 em, radius 0.2 em). The W3C/BBC discussion and vendor rankings agree [C]. The W3C comments note that drop shadows add "busyness" for some cognitive conditions [C].
2. **Stroke** of 6-10% of font size (8% default; 6 px at 76 px), plus a hard shadow at 0/4 px, 35-60% black [R, local cap.impact].
3. **Shadow only:** the weakest; avoid it over bright or busy footage [C].

Whatever the treatment, measure the text against what it actually sits on (its stroke or box). With no stroke or box, measure against the lightest and darkest frames it crosses [R, local frame-design].

---

## 5. Emphasis and highlight rules

- **How many words to highlight [M]:** deaf and hard-of-hearing viewers preferred **5-15% of caption words** highlighted. 5% was the most readable and 15% the easiest to follow; 25-35% was too much (Kafle, Yeung and Huenerfauth, ASSETS 2019, n = 30 in the main study). The follow-up (TACCESS 2021, n = 72) recommended **bold, word-level** highlighting.
- **Distraction risk [M]:** Weingärtner et al. 2024 (MUM, n = 66) found time-synced keyword highlights were preferred for *learning* but "too distracting to replace standard captions" for everyday viewing. Keep highlights sparse.
- **Why emphasis works [M]:** in multimedia learning, signalling has a positive effect: g = 0.53 on retention and 0.33 on transfer (Schneider et al. 2018, via a secondary source), d = 0.38 (Alpizar, Adesope and Wong 2020, 29 studies) and r = 0.17 (Richter, Scheiter and Eitel 2016). Effects are larger for low-prior-knowledge viewers, which is the cold-feed audience.

Director rules:
1. **At most 1 highlighted word per chunk and at most 15% of all words per video.** Aim for about 10%.
2. **What to highlight, in priority order:**
   1. numbers and their units ("$10K", "3x", "90 days"), always written as digits;
   2. the payoff noun or verb of the sentence;
   3. negations or contrasts ("never", "stop", "wrong");
   4. named entities in the hook.
   Never highlight function words.
3. **Colour plus a second cue,** because colour alone fails for colour-blind viewers (WCAG 1.4.1). Use scale 1.10-1.18x and/or weight 900 or an underline bar.
4. **Colour semantics (creator convention [C]):**
   - yellow = key point (default);
   - green = gain, money, yes;
   - red = loss, mistake, no.
   Use **one accent by default**. Add green and red only for explicit good-vs-bad contrasts, and never rely on red versus green alone (red-green colour blindness) without the second cue.
5. **Numbers:** a count-up only for one stat card per video, easing out over about 40 frames with no overshoot on quantities, using tabular figures [R, local].
6. **SFX coupling:** an emphasis word may take a soft pop at about −18 dBFS, at most one per sentence [R, local cap.emph].

---

## 6. Emoji

- **Evidence [M, weak]:** Duraj and Szarkowska 2025. Viewers preferred emoji plus lowercase subtitles for casual content. Their open answers complained about overuse ("an emoji at the end of every subtitle adds nothing") and asked for emojis to **replace specific words**, "in moderation". Quso.ai's post-text data (not burned-in captions) found emoji-free post captions got more median views [V]. Captions.ai and Submagic offer auto-emoji on keywords [C].
- **Rules [R]:**
  - Off for serious, medical, finance or legal tones.
  - Otherwise **at most 2 per 10 s, at least 3 chunks apart**, never two in a row.
  - Only where the emoji **adds meaning**: a concrete noun (💰 🧠 ⏰), a reaction (😳), or a replacement for a word.
  - Size about 1.2x cap height. Place it above the chunk, centred, or inline replacing the word. Never at the end of every line.
  - Pop in over 6-8 frames, no continuous wobble.
  - Use open-licensed sets (Noto Color Emoji Apache-2.0/OFL, Twemoji CC-BY-4.0 with attribution, OpenMoji CC BY-SA 4.0, Microsoft Fluent Emoji MIT). Do not render Apple Color Emoji into commercial videos.

---

## 7. Placement and layout

- **Caption block:**
  - centre x = 540 (or 504 when width is tight);
  - **block centre y about 1110 (58%)**;
  - block bottom ≤ 1248;
  - **block top ≥ chin_y + 40 px** (do not cover the mouth, which lip-readers use [C, captioning practice]).
  The local `cap.impact` uses y = 56%, which agrees [R]. 2026 vendor guides put Reels captions "500-1400 px from the bottom, centred" (y 520-1420) [C]. Our 1248 limit is stricter.
- **Talking-head framing assumption:** eyes at about 33-38% of the height (y 630-730) and chin at about y 900-1000, which leaves y 1040-1248 free for 1-2 caption lines. If the face is framed lower (chin below 1100), move the caption block *above* the head (y 300-560), or punch out (scale 0.92).
- **Keep one position all video** [R and C]. Captions do not jump between the face and B-roll. A full-screen B-roll keeps the same caption position. A split-screen layout with B-roll on top (y 0-960) and the face below moves captions to the seam (centre y = 960 ± 60).
- **Research note [M]:** speaker-following subtitles near the action shorten saccades and increase fixations on relevant image areas (Kurzhals et al., CHI 2017, n = 40). That supports chest-level captions near the face over bottom-of-frame captions.
- **One focal text at a time:** captions, the hook title and a callout never animate in on the same frame. Stagger them by at least 6 frames [R].

---

## 8. Other on-screen graphics

### 8.1 Hook title / headline bar
- On screen **by 0.3 s**, at most 7 words (at most 4 on the poster frame) [R, local virality and critic].
- Zone y 300-560, 80-104 px, box style (white box with black text, or the brand box with white text), 1-2 lines.
- It must say the same thing as the first spoken line, in different words, so the layered hook agrees [C, local edit.md].
- Hold it through the hook (0-3 s), then either exit (8 frames) or shrink to a 44-52 px "topic pill" at the top-left of the safe rect for the rest of the video. The shrink is the "podcast-clip" persistent-headline variant [C].
- **UNVERIFIED:** Instagram has said Reels with borders or letterboxing are less likely to be recommended. A black band around a small video is a border, so keep the video full-bleed and float the title over it.

### 8.2 Lower thirds
- Use only when the speaker's identity is a credibility asset (an expert, a founder). Show it once, **after the hook**, at 3-6 s [R].
- Name 52-60 px, title 40-44 px (raised from the local 32-40 px floor by section 2).
- Left-aligned at x = 120, y about 860-980, which sits above the caption block. Do not stack it on the captions.
- Bar wipe 10 frames, name slide 12 frames offset 4 frames, **hold 2.5-3.5 s**, out in 8 frames; exits are faster than entrances [R, local visual.md]. At most 2 lines and no logos inside it.

### 8.3 Progress bars and counters
- **No published test shows a burned-in progress bar raising watch time** [C: none found]. Shorts and TikTok already draw native progress or seek bars at the bottom, and Instagram has been tested with one.
- **Default: off.** For list or tutorial formats of 40 s or more, use a **segmented chapter counter** instead ("2/3" pill, 40-48 px, top-left of the safe rect), which turns each step into an open loop [R].
- If a bar is used: at y = 288-298 (below the top UI), 8-10 px high, accent colour, linear, full width of the safe rect. Never at the bottom.

### 8.4 Callouts, arrows, circles, underlines (over B-roll or screenshots)
- The signalling evidence is in section 5 [M]. Temporal contiguity (the cue arrives with the words that name it) is strongly supported in Mayer's work; the exact effect size is **UNVERIFIED** here.
- **Sync:** the draw-on starts 0-3 frames before the onset of the word that names the thing.
- **Style:** draw-on 10-16 frames (stroke-dashoffset), hold at least 0.8 s or until the idea changes, out in 6 frames. Stroke 8-12 px at 1080 width, round caps, accent colour plus a 3-4 px dark halo, so it reaches **3:1 non-text contrast** (WCAG 1.4.11) against the local background.
- **Discipline:** at most 1 callout visible, at most 1 per 3 s [R]. Hand-drawn scribble style (circle, arrow, underline) for creator tone, clean vector for product UI [R, local icon set].
- Callouts point **into** the safe rect, never at the platform UI.

### 8.5 Brand consistency ("caption DNA")
- One theme file per creator series fixes the font, weight, size, case, fill, stroke, highlight colour, position, animation and emoji policy. Never vary it per video [R and C: Hormozi and MrBeast are recognised by caption style alone, per vendor breakdowns].
- Change at most one variable per test batch, so retention changes can be attributed [R].

---

## 9. Accessibility and quality checklist (machine-checkable)

- [ ] Every spoken sentence has a caption (local R14 `audioOffTest`).
- [ ] Names, numbers and brand terms are corrected after automatic speech recognition. One review found auto-caption accuracy around 94% [V]. Keep a per-creator glossary.
- [ ] Characters per second ≤ 20 per chunk, at most 4 words, at most 2 lines, at most 18 characters per line, at least 0.5 s on screen.
- [ ] Contrast: fill against stroke or box ≥ 4.5:1. Callouts and graphics ≥ 3:1. Measured on the darkest and lightest frames when no stroke or box is used.
- [ ] Text size: captions ≥ 64 px; any must-read text ≥ 40 px (36 px if all caps).
- [ ] Every text box inside the strict rect: x 120-888, y 288-1248.
- [ ] Highlighted words ≤ 15% of the total, each with a second cue besides colour.
- [ ] ≤ 3 flashes per second (WCAG 2.3.1). No continuous caption wobble; at most 2 animated properties per chunk.
- [ ] On YouTube, also upload an SRT so platform captions and search work. Burned-in text cannot be resized by viewers.
- [ ] Captions never cover the mouth (chin + 40 px rule).

---

## 10. Named examples studied (what each does)

Most of these come from third-party descriptions, mainly caption-tool vendors. Verify frame by frame before copying a specific value.

1. **Alex Hormozi (Shorts/Reels):** heavy Montserrat-style caps (Black 900 is commonly cited), white fill with a black outline, 2-3 words, word-timed. Keyword colours: yellow (#F7C204 per one vendor; Kapwing lists #EAC70C), green for money, red for negatives. Centre-low position. Sources: Submagic, Kapwing, Blitzcut, CapCut tutorials [C].
2. **MrBeast Shorts:** a comic display face (Komika or Komika Axis per Submagic and DesignBeep; one translated guide says CCSignLanguage), uppercase, thick black stroke, keyword highlight with a shadow, the same style since the channel started [C]. The Komika licence is unclear, so use Bangers or Luckiest Guy.
3. **Iman Gadzhi:** **lowercase** white captions, no colour changes, and the active word's weight shifting from light to bold. A minimal "luxury" style (Submagic) [C].
4. **Ali Abdaal:** restrained captions. Sources conflict: one describes word-by-word with a fade or colour change, another a phrase reveal set beside the speaker over a desaturated base (Submagic vs Choppity) [C, conflicting].
5. **Diary of a CEO clips ("trailerization"):** a shocking guest line, then a cut to the host, then on-screen text that opens a curiosity gap; burned-in captions with bold keyword highlighting (Joyspace, Choppity) [C].
6. **OpusClip corpus (Q1 2026):** 80.2% of viral-tier clips burned in captions and 78.6% animated them; the viral median length was 41 s [V].
7. **Duraj and Szarkowska 2025, TikTok cat videos:** lowercase with emoji compared against standard subtitles, with preference and engagement measured; overuse of emoji was criticised [M, weak].
8. **Tool presets that encode the convention:**
   - Submagic: a words-per-line setting, a Position Y slider (no horizontal move), size presets.
   - Captions.ai: words per line, lines per page, auto-emoji on keywords, "AI Emphasis".
   - A ComfyUI "Hormozi" preset: position 75, size 58, 3 words per line (a plugin's own default, not authoritative).
   Together they show that chunk size, Y position and keyword emphasis are the knobs creators tune [C].
9. **Varun Mayya (Indian tech creator):** described in a hiring brief as fast-paced and audio-reactive, with bold on-screen elements and sound-synced visuals [C, weak]. This is the Hinglish/Indian benchmark; study his recent Reels directly.

---

## 11. Conflicts and open items for the orchestrator

1. **Safe zones:** the local per-platform rows are outdated (section 1.3). Adopt the strict rect 120/288/888/1248.
2. **The local 30 px label floor is below the critical print size.** Raise it to ≥ 40 px (36 px if all caps).
3. **`cap.impact` at 6.5% of height (125 px) is a slam size, not a rail size.** Rail 72-84 px; slam 110-130 px for one or two words.
4. **The captions-overlay bottom band of 5-8% is invalid for 9:16 social.**
5. **To verify on a device before shipping:**
   - TikTok's real organic right column (180 px measured vs 300 px in the ad template);
   - the Instagram bottom stack after the reported late-2025 UI growth;
   - the Instagram "border" downranking claim.
6. **No controlled A/B test exists** on caption style versus retention. Reel Director should log the caption theme id per post and compare retention curves within one creator, changing one variable at a time.

---

## Sources

Platform and safe zones
- https://adkit.so/tools/safe-zones/instagram (2026-09-10) · https://adkit.so/tools/safe-zones/tiktok (2026-09-10) · https://adkit.so/tools/safe-zones/youtube (2026-09-10)
- https://www.socialync.io/tools/safe-zones/youtube-shorts (read 2026-10-11)
- https://billo.app/blog/meta-ads-safe-zones (2026-06-16)
- https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads (updated June 2026)
- https://support.google.com/google-ads/answer/13547298 (Google vertical-video safe-zone image)
- https://reap.video/blog/short-form-video-safe-zones (2026-09-07)
- https://www.androidheadlines.com/2026/06/youtube-shorts-gets-a-new-clear-screen-mode-and-more-playback-controls.html

Reading, legibility and chunking research
- Legge & Bigelow 2011, J. Vision: https://pmc.ncbi.nlm.nih.gov/articles/PMC3428264
- Bababekova et al. 2011, Optom Vis Sci: https://pubmed.ncbi.nlm.nih.gov/21499163/
- Rajendran et al. 2013, Perspectives 21(1): https://portalcientifico.uvigo.gal/documentos/65351ae67bba975a1caae049
- Gerber-Morón & Szarkowska 2018, JEMR 11(3): https://ddd.uab.cat/record/238546
- Szarkowska & Gerber-Morón 2018, PLoS ONE 13(6): https://discovery.ucl.ac.uk/id/eprint/10050653/
- Arditi & Cho 2007, Vision Research: https://pmc.ncbi.nlm.nih.gov/articles/PMC2016788
- Kurzhals et al. 2017 (CHI): https://unpaywall.org/10.1145%2F3025453.3025772
- Netflix Timed Text general requirements: https://backlothelp.netflix.com/hc/en-us/articles/215758617
- DCMP presentation rate: https://dcmp.org/learn/5-captioning-guidelines-for-the-dcmp
- BBC guideline summary: https://clevercast.com/bbc-subtitling-guidelines

Emphasis, signalling and emoji
- Kafle, Yeung & Huenerfauth 2019 (ASSETS): https://par.nsf.gov/servlets/purl/10170034
- Weingärtner et al. 2024 (MUM): https://madoc.bib.uni-mannheim.de/68300/1/3701571.3701574.pdf
- Signalling meta-analyses: https://inspire.acu.edu.au/articles/signalling · https://rex.libraries.wsu.edu/esploro/outputs/journalArticle/A-meta-analysis-of-signaling-principle-in/99900601052901842
- Duraj & Szarkowska 2025, JAT 8(1): https://jatjournal.org/index.php/jat/article/view/339
- https://quso.ai/research/do-emojis-increase-views

Caption effect data and evidence reviews
- https://www.opus.pro/blog/anatomy-of-a-viral-tiktok-2026
- https://blitzcutai.com/blog/animated-captions-vs-static-captions · https://blitzcutai.com/blog/word-by-word-captions-vs-full-sentence-captions
- https://www.businessinsider.in/facebook-wants-advertisers-to-get-a-lot-better-at-silent-video/articleshow/50936233.cms
- https://www.disabled-world.com/disability/accessibility/karaoke-captions.php

Creator styles
- https://www.submagic.co/blog/how-to-make-captions-like-mrbeast · https://designbeep.com/2025/12/14/mrbeast-font/
- https://www.kapwing.com/explore/alex-hormozi-style-captions-template · https://lilys.ai/en/notes/create-youtube-shorts-20260115/capcut-hormozi-captions
- https://submagic.co/blog/how-to-make-captions-like-iman-gadzhi · https://www.submagic.co/blog/make-captions-like-ali-abdaal · https://www.choppity.com/tools/recreate-video-editing-style/ali-abdaal/
- https://joyspace.ai/diary-of-ceo-formula-trailerize-podcast
- https://help.captions.ai/docs/captions/styles · https://care.submagic.co/en/category/fonts-captions-16gu1vw/

Local references read
- motion-pack `skills/frame-design/{SKILL.md, references/type-and-color.md}`
- motion-pack `skills/motion-pack/references/{platforms,virality,critic,success-patterns,launch-playbook}.md`
- motion-pack `skills/{story-script, social-video}`
- other agent skills: `captions-overlay`, `embedded-captions` (`references/caption-grouping.md`, `layout-heuristics.md`), `talking-head-recut`, `reels-scripting`, `hook-generator`, `caption-writer-sms`
- motion-pack `docs/research/{edit.md §7, visual.md §4}` and `type/safezones.js`, read-only
