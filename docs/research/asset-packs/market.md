# Market taxonomy: what a high-quality talking-head reel needs (Reel Director)

Researched 2026-10-20. This is research only: nothing was downloaded or installed, and motion-pack and reel-director were not modified.
Scope: 1080x1920 talking-head reels, where the creator records only themselves and Claude pre-builds the edit (HyperFrames + GSAP, using motion-pack parts).
Licensing rule applied: a user of the SaaS must be able to publish the video commercially. Accept OFL, CC0, MIT, ISC and Apache-2.0. Flag CC-BY (it needs attribution). Reject NC, ND, SA (for bundled assets), GPL/AGPL (for code we ship), and anything "free for personal use".

**How reliable the sources are.** Most 2025-26 sources are tool vendors' blogs: Submagic, BlitzCut, OpusClip, Captions, VEED and others. They agree on *what* editors use. Their retention and engagement numbers are marketing, not measurement, so I treat every number below as a starting default to A/B test, not a law.

---

## 0. What the leading tools ship (reference for categories only)

| Tool | What it bundles, relevant to us | Source |
|---|---|---|
| **CapCut** | Transition panel categories: Trending, Basic, Camera, Overlay, Light Effect, Split, Distortion, Glitch, Blur, Social Media, Slide, MG, Mask. Text templates, effects, filters, auto-captions, beat sync, auto cutout (used for "text behind subject"). | capcut.com/tools/free-video-transitions; capcut.com/resource/how-to-put-text-behind-a-person-in-capcut |
| **Captions (captions.ai)** | Caption Style panel controls: text, emphasis and active-word colour; active-word *background*; caption background (padding, radius); stroke; shadow; emojis (size, timing, position); AI Emphasis (underline, emphasis, supersize); split words (words per line, lines per page); font (custom fonts, autofit, case override, hide punctuation); transitions (active-word bg transition, caption transition, randomized rotation, auto movement, auto scale). 30+ caption presets on web, 75+ claimed. **AI Edit "styles"** bundle captions, B-roll, motion graphics, music and transitions as one look: Prism Pro, Paper II, Prime, Elevate, Impact II, Sketch, Lens, Vista, Pop, Orbit, Y2K, Form, Bloom, Chalk, Linen, Evo, Focus, Lift, Stack, Align, plus Analog, Blueprint, Clarity, Core, Film and Vinyl II (95+ in total). Also offers zooms, denoise, eye contact, background replace and trim of filler words. | captions.ai/help/docs/captions/styles; captions.ai/features/edit-with-ai |
| **Submagic** | Creator-named caption templates (Hormozi in 3-4 variants, MrBeast, Devin Jatho, Iman Gadzhi, Ali Abdaal), in the categories Trending / Premium / Emoji / Speakers / New, 35+ styles. Also auto zoom, B-roll by transcript keywords, transitions, sound effects, music, silence and filler removal. | submagic.co blog pages (Hormozi, MrBeast, Devin Jatho, Iman, Ali Abdaal); aivideopicks review 2026 |
| **VEED** | 28 subtitle styles (per its Subtitles API). Named dynamic presets: Glide, Glide2, Pulse, Paloma, Handwritten, Whisper, Fusion. Effects: Box Highlight, Karaoke, Impact Pop, Color Highlight. AI emphasis. | support.veed.io dynamic subtitles; VEED subtitles API |
| **Edits by Meta** | About 30 transitions and 30 filters; auto captions; beat markers; cutout with tracking; image-to-video. May 2026 added transition pacing control, text and sticker opacity, and 200+ new SFX. Jul 2026 added **bilingual auto-captions (15 languages incl. Hindi)**, template overlays and clip-lock. | TechCrunch guide 2025; globaldatinginsights May and Jul 2026; socialmediatoday |
| **OpusClip** | Animated caption templates with emoji and keyword highlights, brand templates, hook titles, AI B-roll. Its blog "11 editing aesthetics dominating short-form 2026" is the best style map found. | opus.pro/blog/editing-aesthetics-dominating-short-form-2026 |
| **Motion Array / Envato packs** | Recurring pack categories: animated titles, swipe-up/CTA icons, vertical transitions, overlays (grain, VHS, light leaks, particles), lower thirds (50-piece packs), arrows and callouts, scribbles and doodles (circles, underlines, exclamations, frames), subscribe/notify buttons, Shorts UI overlays, LUT packs. | motionarray.com blog; elements.envato.com scribble and light-leak listings; Gumroad editor packs |

**Takeaway.** In 2026 the products sell **looks**, not loose parts. Each "style" is one coordinated bundle of caption family, font pair, palette, overlay texture, transition family, SFX family, music mood and B-roll treatment. Reel Director's packs should be organised the same way (section P), on top of an atomic library.

---

## A. Caption style families (the single most visible asset)

Sound-off viewing is cited at about 70-85% on TikTok/Reels (FontMirror). That is a vendor estimate, but every source agrees captions carry the message.
2026 movement: word-by-word kinetic captions are the baseline. Chunks are slowing to **2-4 words held 600-900 ms**. **Mixed case with capitalised keywords is replacing all-caps**, which now "reads as direct-response or dated" (FontMirror). Hook text sits dead centre, roughly 80-120 px on 1080x1920.

| # | Family | Defining spec (defaults to test) | Typical niche | Priority |
|---|---|---|---|---|
| 1 | **Bold-highlight ("Hormozi")** | Heavy sans (Montserrat Black 900 or Anton; TheBoldFont is the original). Caps or mixed case. White fill, thick black stroke 5-8 px or a hard shadow. **One keyword per line in yellow #F7C204, green #02FB23 or red**. 2-4 words per page, 60-75 px Montserrat or 70-85 px Anton. Word-by-word pop. The keyword is enlarged on the beat it is spoken. Newer variant: yellow stroke plus slight shadow, pop in from bottom. | business, education, coaching | MUST |
| 2 | **Comic-pop ("Beast")** | Komika is the original (custom licence); free substitutes are **Bangers** and Luckiest Guy. Caps, heavy black outline, keyword green (or yellow) with glow/shadow, about 2 words per page, appears and disappears fast, slight random rotation. | entertainment, challenges, hype | MUST |
| 3 | **Karaoke colour-fill** | Whole phrase visible; the active word fills or sweeps to an accent colour; 3-6 words, max 2 lines. | general, music-adjacent | MUST |
| 4 | **Active-word pill / box highlight** | A rounded rectangle (brand colour) slides behind the active word; text stays white. This is VEED's "Box Highlight" and Captions' "active word background". | SaaS, explainer, brand-forward | MUST |
| 5 | **Subtitle block / boxed** | Phrase on a solid or semi-opaque box (TikTok "classic"), Roboto/TikTok Sans, 3-5 words, minimal motion. Reads well on busy frames but covers more of the picture. | tutorials, step-by-step, accessibility | MUST |
| 6 | **Single-word slam** | One word at a time, centre, big, slight scale/fade/bounce per word. | fast talkers, motivation, opinion | SHOULD |
| 7 | **Minimal clean** | Sentence case, Inter/TikTok Sans/Geist medium-semibold, white with a soft 1-2 px shadow or thin 2-3 px outline, fade only. | premium B2B, founders, aesthetic | MUST |
| 8 | **Lowercase weight-shift ("Iman")** | Mostly lowercase, white only, no colour keywords; each word animates **light to bold weight** as it is spoken. Needs a *variable* font. | luxury, entrepreneur, calm authority | SHOULD |
| 9 | **Editorial serif / storyteller** | Serif (Instrument Serif, Playfair, DM Serif) with italic keywords; can pair with a sans for the rest. Comparable to Subclip "Serif Storyteller" and Captions "Byline". | storytelling, finance-premium, personal essays | SHOULD |
| 10 | **Emoji-pop / AI emphasis** | Keyword triggers an emoji above the line (pop 6-8 frames), plus supersize or underline on emphasis words. | lifestyle, general creators | MUST (as a modifier on 1-7) |
| 11 | **Glow-float ("Devin Jatho")** | Montserrat ExtraBold caps, 3 light/pastel colours, outer glow, gentle floating motion. | lifestyle, fitness, motivational | NICE |
| 12 | **Handwritten / marker / notebook** | Marker or hand font (Permanent Marker, Caveat, Kalam) on paper textures. Captions "Paper II / Sketch / Chalk" and VEED "Handwritten" are the closest matches. | teachers, creatives, study | SHOULD |
| 13 | **Retro / Y2K / chrome** | Shrikhand/Bungee/Monoton, chrome or gradient fill, VHS overlay. Captions "Y2K", "Vinyl II". | fashion, music, nostalgia | NICE |
| 14 | **Bilingual / dual-line** | Primary-language line plus a smaller secondary-language line. Meta Edits shipped this in Jul 2026 (15 languages incl. Hindi). Hinglish romanised plus Devanagari is a real need in India. | multilingual and India creators | SHOULD |
| 15 | **Typewriter / terminal** | Mono font, caret, per-character reveal. | dev, tech, AI | NICE (motion-pack `typewriter` exists) |

**Caption engine mechanics every family needs (MUST).** These matter as much as the looks.
- Word-level timestamps.
- Chunking of 2-4 words, breaking at clause boundaries and pauses.
- A hold of max(0.5 s, 0.35 + 0.28 s/word); motion-pack's rule already matches the 600-900 ms market norm.
- Max 2 lines and ≤18 chars per line.
- One fixed vertical position: lower-middle third, clear of the top ~220 px and bottom ~320-450 px. Hooks go centre.
- Keyword/emphasis detection (numbers, money, negations, superlatives, names).
- An emoji map; number formatting ("$10,000"); profanity masking; a custom-vocabulary/brand-names dictionary.
- Per-word style overrides.
- Off-centre "static paragraph" mode for the anti-polish talking-head style (OpusClip aesthetic #3).

---

## B. Fonts (largest gap in motion-pack today)

motion-pack bundles only **Manrope, IBM Plex Mono and STIX Two Text**. The market caption families above need roughly 25-35 families. Picks are all OFL or Apache-2.0 (Google Fonts) unless marked.

| Role | Market reference font | Licence-safe pick(s) | Priority |
|---|---|---|---|
| Heavy geometric sans (Hormozi, default) | Montserrat Black/ExtraBold; "The Bold Font" | **Montserrat** (variable, OFL), **Anton** (OFL), **Archivo Black** / Archivo variable incl. width (OFL), **Poppins** ExtraBold/Black (OFL, also has Devanagari), Rubik Black, Figtree | MUST |
| Condensed display (fitness, hooks) | Bebas Neue, Oswald, The Bold Font | **Bebas Neue**, **Oswald**, League Gothic, Barlow Condensed, Big Shoulders Display (all OFL) | MUST |
| Comic / playful (Beast) | Komika Axis (Apostrophic Labs custom licence: freeware, but repackaging needs written permission, so do not bundle) | **Bangers** (OFL), **Luckiest Guy** (Apache-2.0), Lilita One, Titan One, Bowlby One (OFL) | MUST |
| Platform-native / neutral | TikTok "Classic" (Proxima Nova, commercial), SF Pro (Apple licence covers mockups only, so reject), Instagram Sans (proprietary, reject) | **TikTok Sans** (OFL 1.1, official repo), **Roboto / Roboto Flex** (OFL), **Inter** (OFL), Geist (OFL) | MUST |
| Clean grotesk / minimal | LL Circular (commercial), Satoshi / General Sans / Clash (Fontshare ITF licence: free to use but not to redistribute, so flag and do not bundle) | **Inter / Inter Display**, **Manrope** (have), DM Sans, Space Grotesk, Plus Jakarta Sans (OFL) | MUST |
| Variable weight-morph (Iman style) | — | **Inter**, **Montserrat**, **Roboto Flex**, **Fraunces** (variable OFL) | SHOULD |
| Serif / editorial | Playfair Display; premium finance pairs serif logotypes with sans captions | **Instrument Serif**, **Playfair Display**, DM Serif Display, Fraunces, Newsreader, Young Serif (OFL) | SHOULD |
| Wide / extended (premium, "Druk Wide" feel) | Druk Wide (Commercial Type, reject) | **Unbounded**, **Syne**, Archivo Expanded (width axis), Dela Gothic One, Krona One (OFL) | SHOULD |
| Handwritten / marker (annotations, notes) | — | **Permanent Marker** (Apache-2.0), **Caveat**, Kalam, Patrick Hand, Gochi Hand (OFL), Rock Salt (Apache-2.0) | SHOULD |
| Retro / Y2K / display | Shrikhand | **Shrikhand**, **Bungee**, Monoton, Rubik Mono One, Righteous (OFL) | NICE |
| Script (rare, accent words only) | — | Pacifico, Yellowtail, Dancing Script (OFL) | NICE |
| Mono / tech | — | IBM Plex Mono (have), JetBrains Mono, Geist Mono, Space Mono (OFL) | SHOULD |
| Indic (Hindi/Hinglish captions) | — | **Noto Sans Devanagari**, **Mukta**, **Hind**, Baloo 2, Tiro Devanagari Hindi (OFL); Poppins covers Devanagari too | SHOULD (MUST if India is a launch market) |
| **Colour emoji font for the renderer** | Apple Color Emoji (proprietary, never ship) | **Noto Color Emoji** (OFL). Render hosts (Linux/Docker headless Chrome) otherwise show tofu or a different emoji set from the creator's Mac. | MUST |

Format: ship woff2, subset Latin plus Latin-ext (plus Devanagari where needed), and prefer variable files. Size: about 8-15 MB as woff2 for the whole set, versus 40-80 MB as full TTF.

---

## C. Emoji, stickers, icons

| Item | What the market uses | Licence-safe source | Priority |
|---|---|---|---|
| Static emoji graphics (3D/colour) for emoji-pop captions | Apple-style 3D emoji; Captions/Submagic animate them | **Microsoft Fluent Emoji** (MIT; 3D, Color, Flat and High-Contrast variants; trademark logos excluded upstream; check the repo LICENSE). Noto Emoji images (Apache-2.0). Twemoji graphics are CC-BY 4.0 (attribution, so flag). OpenMoji is CC BY-SA (reject for bundling). | MUST |
| Animated emoji (Lottie/WebP) | "Animated emoji" packs from Motion Array | **Noto Animated Emoji**: reported CC BY 4.0 (attribution, so FLAG; verify on googlefonts.github.io/noto-emoji-animation). Alternative: animate Fluent 3D PNGs procedurally (pop, wobble, bounce), which needs no attribution. | SHOULD |
| Social UI stickers | like/follow/subscribe buttons, notification bell, comment-reply bubble, DM/iMessage bubble, tweet/post card, search bar, cursor click | Build owned. motion-pack has `social.followButton`, notification, replyBubble/replyCard, chatBubbles, ui.promptBar. **Never** copy platform logos or trademarked UI exactly; use generic "follow" and "comment" shapes. | MUST (exists; needs 9:16 variants and generic-brand versions) |
| Icon set (for B-roll cards, lists, lower thirds) | line icons in explainer cards | **Lucide** (ISC), **Phosphor** (MIT, 6 weights incl. duotone/fill), **Tabler** (MIT), Material Symbols (Apache-2.0). Remix Icon: verify the current licence before use. | SHOULD |
| Sticker / cut-out illustration set (people, hands, objects) | "doodle people", reaction stickers with a white die-cut border | Open Peeps / Open Doodles (CC0, verify); make the white "die-cut" border and drop shadow procedurally. | NICE |
| LottieFiles free animations | widely used | "Lottie Simple License": commercial use OK, but redistribution must carry the same licence and terms are per-animation. FLAG: do not bulk-bundle; vet individually. | NICE |

---

## D. Annotation layer: arrows, highlighters, circles, underlines

Market evidence: "hand-drawn yellow highlighter swipes, red circles and arrows" layered over captions are a named 2026 trend. They work for tutorials, comparisons and reaction ads, and work poorly for luxury (FontMirror). Scribble/doodle packs are staple marketplace items (Motion Array blog Apr 2025; Envato "underlines pack 32 doodle", "hand-drawn scribble frames").

Needed set (MUST), all procedural so they stay licence-free:
- Draw-on arrows: straight, curved, squiggle, loop-de-loop, double-head, "this →" with a label.
- Circle and ellipse scribbles: single, double, messy.
- Rectangles and boxes.
- Underlines: straight, wavy, double, scribble.
- Highlighter swipes behind words: marker texture with ragged ends.
- Strike-out/cross-out, check and X marks, brackets, exclamation and question marks, sparkle/burst accents.
- A "spotlight" dim-the-rest effect.

Parameters: stroke width, roughness, colour, and draw-on duration of 6-12 frames with a pen-scratch or marker SFX. Generator option: **rough.js / rough-notation (MIT)**.
motion-pack has: `handArrow`, `callout.scribbleCircle`, `underline`, highlight-bar, `selectionBox`, `spotlight`, `type.strikeOut`. Gap: more arrow shapes, brush/marker texture variants, and a curated "annotation style" per style pack.

---

## E. Structural graphics: hook, lower thirds, chips, progress, end cards

| Element | Practice | Priority |
|---|---|---|
| **Hook title / headline banner** (0-3 s) | Big centred or top-centre headline over the speaker. OpusClip and Submagic sell "hook titles". The first frame must already be content: no fade from black. | MUST |
| **Lower third / name tag** | Creator name or handle plus role on first appearance, about 2-3 s. Vox-style explainers add lower thirds plus charts and maps every 8-10 s. motion-pack: 7 lower-third styles incl. `personalTag`. | SHOULD |
| **Source / citation chip** | Small "source: …" chip when a claim or stat is made. Builds trust and suits a talking head ("B-roll as evidence"). | SHOULD |
| **List counters / step pills** | "1/3", "Tip #2" chips that persist per section. | MUST for listicle reels |
| **Stat / number cards** | Count-up numbers, price slash, before/after. | SHOULD |
| **Progress bar** | A thin bar at the top or bottom, optionally split into chapters. No controlled evidence it lifts retention. Vendors frame it for **mid-form (≥45-60 s)**, not 15 s clips. Make it optional and default it on only for >45 s. | NICE |
| **End: loop-back ending** | End on a line that flows back into the opening so the reel replays seamlessly. Avoid "thanks for watching" outros. | MUST (as a script/edit rule plus a matched first and last frame) |
| **End: follow / part-2 card** | Put the CTA *before* the expected drop-off, not at the very end. A short follow chip mid-video, or a ≤1-1.5 s end card. A sonic-logo sting is optional. | SHOULD |
| **Reel cover frame** | The Instagram grid crops covers to **3:4 (≈1080x1440, centre)** since 2025. Keep title text in the middle ~60%. | MUST (cover export) |

---

## F. Zoom / punch-in patterns (motion, not assets, but a preset library)

The market convention is to change the frame or visual every **~3-7 s**. A zoom, a text card or a B-roll cut all count. A long single-camera shot needs a change after 5-10 s. Sources are vendor blogs; test it.

| Pattern | Spec default | Use |
|---|---|---|
| **Jump-cut punch-in (alternate framing)** | Hard cut 100% → 112-125% centred on the face (eyes on the upper-third line), alternating back to 100% every 1-3 cuts. On 1080p sources stay ≤110-115% without upscaling. 4K sources have about 2x headroom. | MUST; hides jump cuts |
| **Slow push** | 100 → 105-110% over a sentence or a few seconds | MUST; keeps static shots alive |
| **Snap / emphasis zoom** | 6-8 frame expo-out to 130-150% on the emphasis word, with motion blur and a whoosh that lands when the camera stops | MUST |
| **Impact shake** | 2-4 frame decaying shake on a hit or boom | SHOULD |
| **Double-take** | In, back, harder in (comedic) | NICE |
| **Zoom-out reveal** | Pull to show a B-roll card beside the speaker | NICE |
| **Speed ramp** | On B-roll and transitions only, not on speech | NICE |

Dependency (MUST): **face tracking** so punch-ins keep the face framed. MediaPipe Face Detection/Landmarker is Apache-2.0.
motion-pack `cam2d` already has `punchCadence`, `crashZoom`, `doubleTake`, `dollySnap`, `handheld2d` and `whip2d`. Gap: face-anchored origin and a 1080p-source zoom ceiling lint.

---

## G. Transitions (talking head uses few, well)

In a talking head, about 90% of edits are **hard cuts or jump cuts**. Designed transitions belong at section changes, into and out of B-roll, and at hook → body. Over-use "becomes the pattern and stops interrupting anything" (practitioner warning).
Families seen across CapCut, Edits and marketplace packs:
- Basic: cut, dissolve, dip to black or white, flash.
- Camera: whip pan, zoom-through, spin, shake.
- Slide/push/swipe-up.
- Mask/shape wipes: circle iris, luma wipe, ink.
- Light effect: light leak, film burn, overexposure.
- Glitch/distortion: RGB split, pixel sort, VHS, warp.
- Blur: zoom blur, directional blur.
- Split: grid, window slice, blinds.
- MG / social media: page peel, card swap.
- Overlay: animated shape covers.

motion-pack's 50 transitions cover all of these (flash, whip, zoomThrough, lightLeak, filmBurn, glitch, maskReveal, swipeUp, spin, pagePeel, pixelSort, dreamyZoom, linearBlur, windowSlice and more, each with paired SFX). **No asset gap.** What's needed is a *talking-head transition policy* per style pack: at most one designed transition per ~10-15 s, and each style pack owns 2-3 transition families.

---

## H. B-roll practices and layouts

Practice defaults (vendor guides; test them):
- B-roll covers **30-60%** of the reel.
- A visual change every **3-8 s**, with no stretch longer than 10 s unchanged.
- Each clip runs **1-4 s**; screen recordings can run longer.
- Place B-roll on **concrete nouns and specific claims**.
- **Evidence beats mood**: the real screenshot, logo or article beats generic stock.
- Keep **one visual language** per video.
- Overlay B-roll when the speaker matters; go full-screen when the visual must be read.
- Use L/J-cuts.

Layouts needed (MUST unless noted):
1. Full-screen cutaway.
2. **Split-screen top/bottom** (9:16 staple; also the "brainrot stack").
3. **Picture-in-picture face bubble** over a screen recording.
4. **Floating card**: rounded 24-40 px corners, soft shadow, slight 3D tilt, over the blurred or dimmed speaker.
5. **Green-screen explain**: the speaker cut out in the left or right third, with context filling the other side, swapped every 4-6 s. Needs segmentation.
6. **Screenshot pop** (tweet/article/review) with highlighter.
7. **Blur-fill** for horizontal clips: the same clip blurred and scaled behind. This is a must for any 16:9 source.
8. **Text-behind-subject**: a headline between the background and the segmented speaker. CapCut has a dedicated template, posted 2025-05-24. Needs person segmentation; this is SHOULD.

Since the creator only records themselves, Reel Director's B-roll is mostly **pre-built motion-graphic cards**: stat, list, quote, chart, UI mock, screenshot frame, map, timeline. Optional extras are user-uploaded screenshots/screen recordings and a stock API.

| B-roll source | Licence notes | Priority |
|---|---|---|
| Owned motion-graphic B-roll cards (motion-pack gfx/ui/charts) | MIT/owned | MUST |
| User uploads (screenshots, screen recordings, product shots) | the user's own | MUST (upload slot + frame treatments) |
| Pexels API (video) | Commercial use OK and no attribution needed in the final video. **But the API requires a prominent Pexels link and photographer credit in our UI**, needs an approval and demo, bans standalone redistribution and "similar/competing service" use, and limits to 200 req/h and 20k/mo by default. Rendered-into-video is fine; do **not** cache or bundle the clips as a pack. | SHOULD |
| Pixabay API | Pixabay Content License: commercial OK; no standalone redistribution. FLAG: Pixabay *music* has a history of Content ID claims. | NICE (video only) |
| Mixkit | Free licence, but its terms bar packaging items in downloadable bundles or selling them unaltered, and some videos carry a "Restricted" (personal-use) licence. **Reject for bundling.** | reject for packs |
| AI-generated B-roll (Veo/Seedance/Higgsfield etc.) | per-provider ToS; cost per second | NICE |
| Gameplay for the "brainrot" split (Subway Surfers etc.) | copyrighted, **reject**. Substitute owned procedural "satisfying loops" (kinetic sand, marble run, parkour runner in three.js). | NICE (owned loops) |

---

## I. Backgrounds

Used for hook cards, text-only B-roll cards, split-screen fills, green-screen replacement, quote/list cards and end cards.

| Family | Notes | Priority | motion-pack |
|---|---|---|---|
| Solid brand colour plus subtle grain | the most-used card base | MUST | brandField |
| Linear/radial gradient plus grain ("grainy gradient") | | MUST | have (grade/grain) |
| Animated mesh / aurora gradient | soft premium look; pastel for wellness/beauty palettes | MUST | `meshGradient`, `auroraRibbon` |
| Grids: graph paper, dot grid, perspective grid, blueprint | tech/explainer | MUST | `dotGrid`, `gridTunnel`; add a flat graph-paper/blueprint variant |
| Paper / notebook / kraft / cardboard / canvas | "Paper/Sketch/Linen" looks | SHOULD | `paperFold`, `crumple`, `cardboard`, `canvas`; add lined notebook and sticky-note |
| Chalkboard / whiteboard | teacher looks (Captions "Chalk") | SHOULD | add |
| Blurred self (blur-fill or defocused speaker) | the most common talking-head backdrop for cards | MUST | needs a plate-blur util |
| Bokeh / light orbs | lifestyle | NICE | `bokeh`, `motes` |
| Studio sweep / gradient wall (behind a cut-out speaker) | green-screen replacement | SHOULD | add (needs segmentation) |
| Abstract animated shapes / blobs / waves | playful | NICE | partial |
| Real CC0 photo textures (paper, concrete, fabric) | optional realism upgrade | NICE | source: **ambientCG / Poly Haven (CC0)** |

---

## J. Overlays / textures

The market staples in grain, dust and VHS packs (Motion Array, Envato, Payhip, Gumroad) are: film grain (16/35 mm), dust and scratches, light leaks, lens flares, bokeh, VHS/camcorder/REC HUD, glitch/RGB split, vignette, paper texture, halftone, scanlines/CRT, frames (polaroid, film sprocket, phone frame), particles (confetti, sparks, snow), and speed lines.
motion-pack covers essentially all of these procedurally: `grain` (stocks), `dust`, `leaks`, `vignette`, `bokeh`, `flareStreak`/`flareGhosts`/`starburst`, `lensDirt`, `vhs`, `recHUD`, `timecode`, `sprocket`, `polaroid`/`instax`, `halftone`, `speedLines`, `paper`, `burnEdge`, confetti and sparks, plus Finisher halation and bloom.
**Gap: none at the asset level.** Two needs remain:
- A per-style-pack "finish recipe" for talking heads. Grain must be light on faces; OpusClip's "phone-first cinematic" is one LUT plus light grain.
- A lint that keeps texture overlays off the caption layer.

Real scanned grain or leak plates are NICE only; procedural output is deterministic and licence-free.

---

## K. Colour: input transforms and looks

**MUST (quality-critical, often overlooked): input normalisation.**
- iPhone records **HDR HLG / Dolby Vision (Rec.2100)** by default. When it is treated as SDR it comes out washed out.
- Pros, and Apple Log 2 users, also record Apple Log.
- Reel Director must detect transfer characteristics (ffprobe `color_transfer=arib-std-b67`, `smpte2084`, or Apple Log) and tone-map to Rec.709 SDR *before* compositing in Chrome. Use ffmpeg zscale/tonemap, or a cube built from the published curves.
- motion-pack has LogC3, S-Log3 and V-Log → 709 cubes. Missing: **HLG → 709**, **Apple Log → 709** and Dolby Vision handling.

**Looks (LUT families) talking-head creators use:**

| Look | Notes | Priority |
|---|---|---|
| Neutral "clean punch" (slight contrast and saturation, skin-safe) | the default; most reels | MUST |
| Warm creator / golden skin | flattering faces | MUST |
| Teal-orange cinematic (skin-protected) | "most requested" grade, from vendor claims | SHOULD |
| Film emulation: warm "portra-like", green "fuji-like", faded matte | phone-first cinematic, documentary realism | SHOULD |
| B&W high-contrast | emphasis segments | SHOULD |
| Pastel / airy (wellness, beauty) | | NICE |
| Moody desaturated / cool | | NICE |
| Neon night | | NICE |

motion-pack has 45 owned looks (incl. teal-orange, faded 90s, matte cool/warm, golden/blue hour, high-key beauty, B&W filters, pastel, neon night). **Gaps:**
- A skin-tone-protect option.
- Per-shot exposure and white-balance auto-match, so multiple takes on different days look like one session.
- Look strength calibrated on real phone footage. The looks were judged on a test plate only (motion-pack's "honest limits").

---

## L. Sound effects: taxonomy and placement map

What editors use (Morphic, Jupitrr, Finchley, marketplace packs), and where:

| SFX | Placement rule | motion-pack |
|---|---|---|
| Whoosh/swish (xs-xl), whip | transitions, snap zooms (lands when the camera stops), text fly-ins | have (15) |
| Pop / bubble / click | each caption chunk *or* callout appear. Use sparingly: one per callout, not per word. | have |
| Ding / bell / notification | stat reveal, "subscribe" or follow chip, a list item checked | have |
| Riser (noise, reverse cymbal, tension) | 1-2 bars before a reveal or hook payoff | have (16) |
| Impact / boom / sub-drop / "meme boom" | reveal frame, punchline, big number | have (19) |
| Camera shutter | screenshot or B-roll photo pop, flash transition | have |
| Record scratch / rewind / tape stop | "wait, back up", pattern interrupt | have |
| Typing / keyboard / mouse click | UI and screen-recording B-roll, typewriter captions | have |
| Cash register / coin | money claims | have |
| Error buzz / wrong / correct / success | myth vs fact, X vs check | have |
| Sparkle / twinkle / magic | before/after, glow-up, AI | have |
| Pen scratch / marker squeak | annotation draw-on | partial (foley pen_click). **Add marker-draw and pencil-scribble loops.** |
| Glitch stutter | glitch transitions | have |
| Heartbeat / tension drone | suspense | have |
| Crowd cheer / laugh / aww / boo | reactions (synth) | have |

The rule from the market is **restraint**: "a light sound effect on obvious changes rather than layering effects on everything." Generic whooshes everywhere make every moment feel the same.
motion-pack's SFX library (26 categories, all synthesised, CC0) already exceeds marketplace "editor packs" in breadth. Gaps:
- Annotation-drawing sounds.
- Optional *recorded* realism. Kenney audio is CC0; Freesound has a CC0-only filter. Sonniss GDC bundles are royalty-free, but standalone redistribution is barred, so do not ship them as a raw library in a SaaS.

Meta Edits added 200+ SFX in May 2026, which shows SFX breadth is a competitive feature.

---

## M. Music beds and beat-sync

- **Moods** talking-head reels need: lo-fi/chill hip-hop, upbeat pop/corporate, acoustic/folk, cinematic ambient/piano (emotional), trap/phonk/hype, deep house/minimal, funky/comedy, and regional (Indian: dhol/bhangra/tabla lo-fi).
- **Licensing reality.** Trending platform audio cannot be licensed by a SaaS. Business accounts are limited to the platform's commercial sound libraries, and trending sounds are added in-app at upload time. So the in-render music must be owned or CC0.
- **motion-pack** already synthesises CC0 beds across many genres (acoustic folk, ambient, anthem, bhangra, chiptune, cinematic, comedy, corporate, deep house, …) plus stingers and sonic logos.
  - Gap: longer-form, more "produced" sounding beds (60-90 s with arrangement changes), and stems for ducking.
  - Recorded CC0 option: **FreePD.com** (Kevin MacLeod's public-domain site; the README says CC0; verify per track).
  - Incompetech is CC-BY (attribution, flag).
  - Pixabay Music carries a Content ID claim risk (flag).
  - YouTube Audio Library: verify terms before any use.
- **Mix defaults:**
  - Voice is the anchor.
  - Music sits about **10-20 LU under voice** (broadcast study: ≥10 LU commentary-to-music).
  - Sidechain ducking depth about −12 to −20 dB with 500-1500 ms release, so music stays down across pauses.
  - Master to about **−14 LUFS integrated, −1 dBTP**. This is an observed working target, not a published platform spec. motion-pack `ears` already checks levels.
- **Beat-sync practice.** Speech drives cut timing in talking heads. Music is used to (a) land the hook/reveal on a downbeat or drop, (b) snap SFX, zooms and B-roll cuts to the nearest beat when within ±2 frames, and (c) cut montage sections on beats.
  - Edits ships auto beat markers. motion-pack has `tempo_maps.json`, so owned beds already have exact beat grids, and no detection is needed for them.
  - For user-supplied music, beat detection with **librosa (ISC)** is fine. **Avoid** aubio (GPL), Essentia (AGPL) and madmom's pretrained models (CC BY-NC-SA) in shipped code.

---

## N. Voice polish chain (MUST; quality lever #1 for talking heads)

Every competitor sells it: Captions "Denoise", CapCut "Enhance voice", Adobe Podcast-style. A bad mic ruins a perfect edit.

Preset chain:
1. High-pass at 70-90 Hz.
2. Noise reduction: RNNoise (BSD-3) or DeepFilterNet (MIT/Apache-2.0). Verify model weights' licences.
3. De-ess.
4. Gentle compression (3:1).
5. Presence EQ.
6. Silence/filler trim: cut pauses >~0.5 s between sentences and keep breaths between ideas.
7. Loudness normalisation.

These are presets and tooling rather than media assets, but they belong in the "pack" so every reel sounds pro.

---

## O. Platform specs the packs must respect (MUST)

- **Canvas:** 1080x1920, 30 fps typical. 4K source gives zoom headroom.
- **Reels safe zones.** Sources disagree, so use the conservative union:
  - Top ≥220-250 px.
  - Bottom ≥320-450 px. Reels' bottom UI is heavier than TikTok's (~250 px).
  - Right ≥100-120 px (action rail).
  - Left ≥60 px.
  - The safe core is about 1010x1280 centred.
  - motion-pack `safezones.js` exists; verify its numbers against this union.
- **Cover:** 9:16 export, plus title inside the centre 3:4 (1080x1440) for the IG grid.
- **Audio:** −14 LUFS, −1 dBTP.
- **Photosensitivity:** flashes ≤3 per second (motion-pack lints this).

---

## P. Style packs: coordinated bundles (how the market sells "looks")

Modelled on Captions AI Edit styles, Submagic's creator templates and OpusClip's 2026 aesthetics. Each pack is one JSON preset over atomic parts. Proposed starter set:

| Pack | Caption family | Fonts | Palette | Overlay / finish | Transitions | SFX family | Music | B-roll treatment | Priority |
|---|---|---|---|---|---|---|---|---|---|
| **Bold Hustle** | Hormozi bold-highlight | Montserrat Black / Anton | white, black, #F7C204, #02FB23 | none / slight vignette | punch cuts, flash, whip | whoosh, pop, impact, cash | upbeat trap / corporate | full-screen + floating cards | MUST |
| **Clean Pro** (B2B/SaaS) | minimal clean or active-word pill | Inter / Geist + Instrument Serif accents | brand + neutral | light grain | dissolve, push, mask wipe | soft click, ding, swish_xs | corporate bright / deep house | floating UI cards, screenshots | MUST |
| **Beast Hype** | comic-pop | Bangers / Luckiest Guy | saturated primaries, green keywords | impact frames, speed lines | crash zoom, spin, glitch | boom, record scratch, riser | hype / phonk | emoji-pop, reaction stickers | MUST |
| **Editorial** (storyteller/premium) | serif storyteller or lowercase weight-shift | Instrument Serif + Inter (variable) | off-white, ink, one accent | film grain light, matte look | dissolve, blur cross, dip | soft hits, paper | ambient piano / cinematic | archival duotone, quotes | SHOULD |
| **Notebook** (teacher/creator) | handwritten/marker | Caveat / Permanent Marker + Inter | paper, ink blue, highlighter yellow | paper texture, doodles | page peel, ink | pen scratch, paper, pop | acoustic / lo-fi | sticky-note and notebook cards | SHOULD |
| **Film Analog** (phone-first cinematic) | minimal sentence case | Fraunces / DM Serif + Geist Mono | warm | one film look, 35 mm grain, leaks, halation | light leak, film burn, dip | projector, shutter, soft whoosh | lo-fi / acoustic | documentary B-roll, polaroid frames | SHOULD |
| **Tech Blueprint** | typewriter / active-word pill | Space Grotesk / JetBrains Mono | navy, cyan, white | grid bg, scanlines light | glitch, pixel dissolve, window slice | UI blips, typing, scan sweep | minimal electronic | UI mocks, terminal, charts | SHOULD |
| **Explainer News** (Vox-like) | subtitle block | Roboto Flex / Inter + condensed heads | neutral + red accent | none | push, luma wipe | ticks, dings, map swish | low ambient | lower thirds, charts/maps every 8-10 s | SHOULD |
| **Pastel Wellness** | glow-float or minimal | Fredoka/Nunito-style rounded + serif | pastel / beige | mesh gradient, bokeh | dreamy zoom, dissolve | sparkle, soft pop | acoustic / ambient | soft cards | NICE |
| **Y2K Retro** | retro chrome | Shrikhand / Bungee | chrome, hot pink, cyan | VHS, REC HUD, chromatic | VHS glitch, tv static | tape stop, glitch | chiptune / synth | camcorder frames | NICE |
| **Desi Bilingual** | bilingual dual-line | Poppins + Mukta/Noto Devanagari | festive gold / saffron | warm look | whip, flash | dhol hits, tabla | bhangra / Indian lo-fi | — | SHOULD (if India is a target) |
| **Split Stack** (brainrot) | single-word slam, 3-colour | Montserrat Black | white plus 2 pops | — | hard cuts 0.6-0.8 s | ASMR, pop | none / ASMR | owned satisfying loops in the bottom half | NICE |

---

## Q. Licensing ledger (decisions)

- **Accept, bundle freely:**
  - Google Fonts OFL and Apache families listed above, plus TikTok Sans (OFL) and Noto Color Emoji (OFL).
  - Fluent Emoji (MIT); Lucide (ISC); Phosphor and Tabler (MIT); Material Symbols (Apache-2.0).
  - rough.js / rough-notation (MIT); MediaPipe (Apache-2.0); librosa (ISC).
  - ambientCG and Poly Haven textures (CC0); Kenney audio (CC0); Freesound CC0-only items; FreePD (CC0, verify).
  - Everything motion-pack synthesises (MIT code, CC0 media).
- **Flag (attribution or per-item terms):**
  - Noto Animated Emoji (CC BY 4.0, reported); Twemoji graphics (CC BY 4.0); Incompetech (CC BY).
  - Q-DDL LUTs (CC BY).
  - LottieFiles Simple License (same-terms redistribution, per-item).
  - Pexels/Pixabay APIs: in-app credit is required, and no caching or bundling.
  - Remix Icon (verify the current licence); DeepFilterNet/RNNoise model weights (verify).
- **Reject for bundling:**
  - Komika Axis/Komika (repackaging needs written permission) and The Bold Font (custom; verify before any use).
  - Proxima Nova, SF Pro, Instagram Sans and Druk (commercial or proprietary).
  - Fontshare ITF fonts: Satoshi, General Sans, Clash (no redistribution).
  - Mixkit (no bundling; some items are personal-only); Sonniss GDC as a raw library; OpenMoji (CC BY-SA).
  - BBC SFX (RemArc, non-commercial); madmom models (NC); aubio (GPL); Essentia (AGPL); RobustVideoMatting (GPL-3.0).
  - Gameplay footage; spectraFilm LUTs (custom licence: "free use, free share, no resale", per a forum report).

---

## R. Prioritised summary (what Reel Director should have)

**MUST**
1. Caption engine plus families 1-5, 7 and 10 (Hormozi, Beast, karaoke, pill, boxed, minimal, emoji modifier).
2. OFL caption font pack (~25 families) plus the **Noto Color Emoji** render font.
3. Emoji graphics (Fluent MIT).
4. Hook title banner.
5. Annotation set (arrows, circles, underlines, highlighter).
6. Zoom/punch-in presets with **face tracking**.
7. Voice polish chain plus silence trim.
8. **HDR/HLG/Apple Log → Rec.709 input normalisation**.
9. Neutral and warm skin-safe looks.
10. SFX placement map (have assets).
11. Music beds with beat grids and ducking (have).
12. B-roll layouts: full, split, PiP, floating card, blur-fill, screenshot pop.
13. Motion-graphic B-roll cards.
14. Safe-zone and cover (3:4) rules.
15. Loop-back ending.
16. 3-4 starter style packs (Bold Hustle, Clean Pro, Beast Hype, plus one of Editorial or Notebook).

**SHOULD**
- Caption families 6, 8, 9, 12 and 14 (incl. Devanagari fonts).
- Animated emoji (with attribution) or procedural animation of static emoji.
- Icon set.
- Text-behind-subject and green-screen explain (person segmentation).
- Lower thirds, citation chips, list counters, stat cards (have).
- Follow / part-2 chip.
- Film, teal-orange and B&W looks; skin protect; take-to-take colour match.
- Pexels stock API.
- Annotation draw SFX.
- Longer produced music beds and stems.
- 4-6 more style packs.

**NICE**
- Glow-float, retro/Y2K and typewriter caption families.
- Progress bar (default on for >45 s only).
- Real CC0 photo textures.
- Recorded CC0 SFX layer.
- Lottie sticker library (vetted per item).
- AI B-roll.
- Owned "satisfying loop" bottom-half clips.
- Double-take and zoom-out-reveal zooms.
- Pastel, Y2K and Split Stack packs.

---

## Sources

- Submagic blog: [Hormozi captions](https://www.submagic.co/blog/how-to-make-alex-hormozi-captions), [MrBeast captions](https://www.submagic.co/blog/how-to-make-captions-like-mrbeast), [Devin Jatho](https://www.submagic.co/blog/how-to-make-subtitles-like-devin-jatho-in-3-clicks), [Ali Abdaal](https://www.submagic.co/blog/make-captions-like-ali-abdaal), [Iman Gadzhi](https://submagic.co/blog/how-to-make-captions-like-iman-gadzhi); [Submagic review 2026](https://aivideopicks.com/posts/submagic-review-2026.html)
- Captions: [styles doc](https://captions.ai/help/docs/captions/styles.md), [Edit with AI](https://captions.ai/features/edit-with-ai)
- BlitzCut: [caption fonts](https://blitzcutai.com/blog/best-caption-fonts-tiktok), [caption styles 2026](https://blitzcutai.com/blog/best-caption-style-tiktok)
- [Virlo: 18 Shorts fonts](https://virlo.ai/blog/youtube-shorts-fonts)
- [FontMirror: typography trends for short-form](https://www.fontmirror.com/en/typography-trends-shaping-short-form-ai-video-content/)
- [OpusClip: 11 editing aesthetics 2026](https://www.opus.pro/blog/editing-aesthetics-dominating-short-form-2026)
- [OpenClip karaoke presets](https://openclip.app/use-cases/karaoke-captions.md)
- [VEED dynamic subtitles](https://support.veed.io/en/articles/12000003-dynamic-subtitles)
- Edits by Meta: [TechCrunch guide](https://techcrunch.com/2025/08/12/a-guide-to-using-edits-metas-new-capcut-rival-for-short-form-video-editing), [May 2026 update](https://www.globaldatinginsights.com/featured/meta-rolls-out-new-features-for-edits-video-editing-app/), [Jul 2026 bilingual captions](https://www.globaldatinginsights.com/featured/meta-edits-app-adds-bilingual-captions-and-new-video-tools/)
- CapCut: [transitions](https://capcut.com/tools/free-video-transitions), [text behind person](https://www.capcut.com/resource/how-to-put-text-behind-a-person-in-capcut), [template](https://www.capcut.com/template-detail/textbehindsubject/7507937836256070973)
- [Viberoll talking-head checklist](https://viberoll.questera.ai/learn/talking-head-video-editing-checklist/)
- [Argil B-roll guide 2026](https://argil.ai/blog/what-is-b-roll-the-complete-guide-for-video-creators-in-2026)
- [Morphic YouTube SFX](https://morphic.com/resources/sounds/youtube-sound-effects)
- [Quso zoom guide](https://quso.ai/blog/zoom-in-on-video.html)
- Motion Array: [scribble/doodle article](https://blog.motionarray.com/?p=28980), [AE template packs](https://motionarray.com/learn/premiere-pro/after-effects-animations/)
- Envato: [scribble underlines pack](https://elements.envato.com/underlines-pack-scribble-elements-32-doodle-animat-RU6EHP6), [light leaks](https://elements.envato.com/light-leaks-B6ZBDZ3)
- Safe zones: [Remotion social safe zones](https://www.remotion.dev/elements/overlays/social-safe-zones/), [Posterly checker](https://www.poster.ly/tools/safe-zone-checker), [First Pier](https://www.firstpier.com/resources/instagram-ad-safe-zones)
- Instagram 3:4 grid: [Planoly](https://planoly.com/blog/guide-to-instagrams-new-vertical-grid), [Hopper HQ](https://help.hopperhq.com/en/articles/10907941-instagram-s-vertical-grid)
- Loudness: [OpusClip normalizers](https://opus.pro/blog/best-loudness-normalizers), [OpenClip loudness](https://openclip.app/learn/loudness-standard); [Salford ducking study](https://salford-repository.worktribe.com/OutputFile/1489990)
- Progress bar: [Zubtitle](https://zubtitle.com/blog/why-mid-form-video-is-making-a-comeback-on-tiktok-and-reels)
- Loops: [CapCut seamless loops](https://www.capcut.com/create/seamless-loop-videos-continuity-techniques)
- HDR: [DaVinci Resolve Club iPhone HDR→SDR](https://davinciresolveclub.com/iphone-hdr-to-sdr-davinci-resolve/), [Adobe community](https://community.adobe.com/bug-reports-728/iphone-rec-2100-hlg-footage-becomes-washed-out-in-premiere-pro-on-windows-1635208)
- LUTs: [PetaPixel teal/orange](https://petapixel.com/2017/02/23/orange-teal-look-popular-hollywood/), [CG Channel Q-DDL 800 LUTs (CC BY)](https://www.cgchannel.com/2020/01/download-800-free-3d-luts/), [pixls spectrafilm](https://discuss.pixls.us/t/spektrafilm-luts/57879)
- Licences:
  - [TikTok Sans OFL](https://github.com/tiktok/TikTokSans); [TikTok dev blog](https://developers.tiktok.com/blog/tiktok-sans-open-source)
  - [Komika Axis licence](https://www.fontsquirrel.com/license/Komika-Axis)
  - [Fluent Emoji MIT (summary)](https://emojifyi.com/glossary/microsoft-fluent-emoji/); [Noto animated emoji (CC BY via animated_emoji)](https://pub.dev/packages/animated_emoji)
  - [Mixkit info](https://mixkit.co/llm-info/); [Pexels API guidelines](https://help.pexels.com/hc/en-us/articles/900005852323)
  - [FreePD README](https://a.ocv.me/pub/stuff/music/freepd/README.md)
  - [LottieFiles licensing](https://help.lottiefiles.com/hc/en-us/articles/900002438343-Can-I-use-a-free-animation-on-Lottiefiles-for-commercial-business-use)
  - [Sonniss licence summary](https://licenseorg.com/guide/music-audio/sonniss)
- Local: motion-pack READMEs (type, layers, camera, transitions/catalog.json, sfx/library, music/library), read only.
