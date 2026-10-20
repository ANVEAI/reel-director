# External asset sources for Reel Director: licence check and sizes

Checked on 2026-10-20. This was research only: nothing was downloaded into a project, nothing was installed, and neither reel-director nor motion-pack-public was changed.

**How sizes were measured.** Font sizes come from the Fontsource metadata API (`api.fontsource.org/v1/fonts/<id>`) plus HEAD `Content-Length` on the jsDelivr woff2 files. Repo and file sizes come from GitHub contents and git-tree listings (`gh api`). Emoji sizes come from HEAD requests to fonts.gstatic.com. Licence lines were read from LICENSE or OFL.txt files through `gh api`, or from the licence pages linked below.

**Licence rule used here.** Accept OFL, CC0, MIT, ISC, Apache-2.0 and BSD. CC-BY is acceptable only with an automatic attribution ledger (see section 9). Reject CC-BY-SA as a default, along with NC, ND, "free for personal use" and anything with no licence.

---

## 0. What motion-pack already covers (read-only check of a motion-pack clone)

| Area | Already in motion-pack | Gap for 9:16 talking-head reels |
|---|---|---|
| Fonts | Manrope VF, IBM Plex Mono, STIX Two Text (OFL, `templates/_shared/fonts/`) | There are no caption display faces (Anton, Bebas, Montserrat Black and similar). There is **no Devanagari font**: `type/README.md` says "Devanagari in `caption.bilingual` falls back to a system font". |
| Emoji | `type/icons.js` has 15 owned vector stickers. `setGlyphSource(fn)` is the hook for a licensed set. `scripts/fetch-external.sh` fetches 279 Fluent Emoji (MIT) | Fluent 3D PNGs are only **256x256** (checked from the PNG header of `assets/Fire/3D/fire_3d.png`), so they go soft when they pop at 400 px or more on 1080x1920. There is no emoji *font* pinned in the caption stack, so on macOS Chrome falls back to **Apple Color Emoji**, which is not licensed for this use. There are no animated emoji. |
| Icons | Lucide subset (111 SVG, ISC/MIT) and Phosphor subset (108, MIT) via fetch-external | Optional: the full Lucide set (1,899), Tabler (6,238) and Material Symbols (about 4,300). |
| Grain, dust, leaks, vignette, bokeh, paper, scanlines | **Procedural**: `layers/overlay.js`, `layers/finisher.js`, and grain stocks clean / digital-soft / film35 / film16 / super8 / vhs / upload-safe | Nothing crucial is missing. See section 4: procedural beats stock here. |
| LUTs / looks | **45 procedural looks** (`layers/looks/look.*.cube`, 17^3), 3 log-to-709 cubes, a neutral roll-off, and `grade.js` emitting `.cube` | Nothing crucial is missing. See section 5. |
| Backgrounds | Procedural `meshGradient` and `auroraRibbon` | Photo or real-world plates: CC0 textures (section 4) and B-roll APIs (section 7). |
| Lottie | The motion-stack skill gives the verdict: lottie-web SVG renderer by default, dotLottie through an `hf-seek` bridge | It has no Lottie *content* source (section 6). |

---

## 1. Fonts: caption and display faces (Latin)

Every font in this table is on Google Fonts and Fontsource, with the licence verified in the `google/fonts` repo. None of the OFL.txt files checked declares a Reserved Font Name, so subsetting is safe (the copyright lines were checked for Montserrat, Anton, Bebas Neue, Poppins, Inter, Archivo Black, Oswald, Bricolage Grotesque, Instrument Serif, Bangers and Roboto Flex). OFL places no restriction on rendered output such as videos. Bundling the files inside the SaaS is also allowed, provided the OFL.txt ships with them and the font is never sold on its own.

The size columns are latin-subset woff2 in KB (Fontsource v5 CDN, 2026-10-20). "VF wght" is the variable file with the weight axis only. "VF all" is the `standard` file with every registered axis.

| Family | Licence | Type / axes | Static latin per weight (KB) | VF wght (KB) | VF all (KB) | Full upstream TTF | Notes |
|---|---|---|---|---|---|---|---|
| Anton | OFL-1.1 | static 400 | 18 | - | - | 167 KB | Tall condensed caption face. Latin, latin-ext, Vietnamese. |
| Bebas Neue | OFL-1.1 (c) Dharma Type | static 400 only | 13 | - | - | 60 KB | Caps only. No bold: fake bold with stroke. |
| Montserrat | OFL-1.1 | VF wght 100-900 + ital | 17-19 (all 9 weights = 163) | **37** | - | 727 KB | ExtraBold 800 and Black 900 are covered by the VF. The classic reel caption face. |
| Poppins | OFL-1.1 (ITF) | static 100-900 + italics | 7-8 (9 weights = 69) | - | - | about 150 KB per weight | **Has a Devanagari subset** (35-39 KB per weight), so one family covers Hinglish (section 2). |
| Inter | OFL-1.1 | VF wght 100-900, opsz 14-32, ital | 23-24 (9 = 211) | 47 | 71 | 856 KB | Clean UI or "explainer" captions. |
| Archivo Black | OFL-1.1 | static 400 | 18 | - | - | 89 KB | Heavy grotesk. |
| Archivo | OFL-1.1 | VF wght 100-900, **wdth 62-125**, ital | 13-14 | 34 | 88 | - | The width axis allows condensed-to-expanded morphs. |
| Oswald | OFL-1.1 | VF wght 200-700 | 12 (6 = 73) | 28 | - | 168 KB | Condensed. |
| Bricolage Grotesque | OFL-1.1 | VF wght 200-800, wdth 75-100, opsz 12-96 | 21-22 (7 = 152) | 40 | 128 | 399 KB | Trendy, characterful. |
| TikTok Sans | OFL-1.1 | VF wght 300-900, wdth 75-150, opsz 12-36, slnt | 25-26 | 44 | 124 | 744 KB | Open-licensed on Google Fonts. Do not imply platform endorsement in preset names. |
| Geist | OFL-1.1 | VF wght 100-900 + ital | 12-13 | 29 | - | - | Tech / SaaS look. |
| Roboto Flex | OFL-1.1 | VF with 13 axes (wght 100-1000, wdth 25-151, GRAD, opsz...) | 14 | 34 | **244** | - | Best for `weightMorph` and width-squash kinetic type. Heavy if every axis ships. |
| Rubik | OFL-1.1 | VF wght 300-900 | 17-19 | 35 | - | - | Rounded grotesk. Also covers Arabic and Hebrew. |
| Lexend | OFL-1.1 | VF wght 100-900 | 14-15 | 39 | - | - | Readability-tuned. |
| League Spartan | OFL-1.1 | VF wght 100-900 | 12-13 | 23 | - | - | Geometric bold. |
| Barlow Condensed | OFL-1.1 | static 100-900 | 20-22 | - | - | - | Sports / news lower thirds. |
| Big Shoulders | OFL-1.1 | VF wght 100-900, opsz 10-72 | 14 | 36 | 57 | - | Condensed display. |
| Unbounded | OFL-1.1 | VF wght 200-900 | 19-21 | 50 | - | - | Wide display. |
| Space Grotesk | OFL-1.1 | VF wght 300-700 | 13 | 22 | - | - | |
| Plus Jakarta Sans | OFL-1.1 | VF wght 200-800 + ital | 12 | 27 | - | - | |
| Outfit / Sora / Syne / Figtree / Inter Tight | OFL-1.1 | VF | 10-22 | 20-44 | - | - | Alternates for brand kits. |
| Instrument Serif | OFL-1.1 | static 400 (+ italic) | 21 | - | - | - | The current "editorial serif" reel trend. |
| DM Serif Display | OFL-1.1 | static 400 | 24 | - | - | - | |
| Playfair Display | OFL-1.1 | VF wght 400-900 + ital | 21-23 | 38 | - | - | |
| Luckiest Guy | **Apache-2.0** | static 400 | 17 | - | - | 72 KB | Chunky meme / gaming captions. Apache is fine. |
| Bangers | OFL-1.1 | static 400 | 23 | - | - | - | Comic. |
| Lilita One | OFL-1.1 | static 400 | 10 | - | - | - | Chunky rounded caption. |
| Titan One / Paytone One / Bowlby One SC / Dela Gothic One / Rubik Mono One | OFL-1.1 | static 400 | 10-23 | - | - | - | Heavy display alternates. |
| Fredoka | OFL-1.1 | VF wght 300-700, wdth 75-125 | 15-16 | 29 | 66 | - | Friendly rounded. |
| Bungee | OFL-1.1 | static 400 | 14 | - | - | - | Signage. |
| Chewy | **Apache-2.0** | static 400 | 19 | - | - | - | |
| Permanent Marker | **Apache-2.0** | static 400 | 29 | - | - | 73 KB | Hand-written marker annotations. |
| Caveat | OFL-1.1 | VF wght 400-700 | 48-50 | 73 | - | - | Handwritten notes and arrows. |
| Pacifico | OFL-1.1 | static 400 | 32 | - | - | - | Script. |
| JetBrains Mono | OFL-1.1 | VF wght 100-800 + ital | 21 | 39 | - | - | Code captions (Plex Mono is already in the pack). |
| Shrikhand | OFL-1.1 | static 400 | 16 | - | - | - | Also covers **Gujarati**. |

**Pack budget.** A caption pack of about 16 faces (Montserrat VF, Inter VF, Poppins at 4 weights, Anton, Bebas Neue, Archivo Black, Oswald VF, Bricolage all-axes, TikTok Sans all-axes, Instrument Serif, Lilita One, Luckiest Guy, Bangers, Permanent Marker, Caveat VF, JetBrains Mono VF) comes to **about 0.7 MB** of latin woff2 (rough sum of the table rows). Add about 15% if latin-ext is included.

**Rejected or flagged.** The following were not fetched because their licences are known to be custom or proprietary. Each is a "do not use" until a written licence is shown:
- Fontshare faces (Satoshi, Clash Display, General Sans): ITF Free Font License. Commercial use is allowed, but redistribution in a product is not, so they cannot be bundled in a SaaS.
- "The Bold Font" and Komika Axis: personal-use or freeware licences that are unclear.
- Gilroy, Proxima Nova and Mont: commercial.

**How to ship.** Vendor the exact woff2 files with their OFL.txt and pin the Fontsource npm version, for example `@fontsource/anton@5.3.0` (npm version from the API). Do not use `@latest` from the CDN in renders, because determinism requires pinned bytes. Await `document.fonts.ready` before the first frame (motion-pack type parts already require this).

## 2. Fonts: Devanagari and Indic (Hindi and Hinglish creators)

All are OFL-1.1 and all are on Google Fonts and Fontsource. "Deva" is the devanagari-subset woff2 in KB. Chrome shapes Devanagari through HarfBuzz, so conjuncts and matras render correctly in HyperFrames.

**Rule for Hinglish:** pick a family with a *matched* Latin and Devanagari design, so that mixed lines like "ये hack 100% काम करता है" do not switch faces mid-line. Poppins, Mukta, Hind, Baloo 2, Anek Devanagari, Noto Sans Devanagari, Teko, Rajdhani and Khand all ship both scripts.

| Family | Licence / copyright | Type / axes | Deva per weight (KB) | VF deva wght (KB) | Latin VF / static (KB) | Full upstream TTF | Use |
|---|---|---|---|---|---|---|---|
| Noto Sans Devanagari | OFL-1.1 (Noto Project Authors 2022) | VF wght 100-900, wdth 62.5-100 | 48-53 | **118** | 25 (VF) | 627 KB | Default safe fallback, with full Unicode coverage. |
| Noto Serif Devanagari | OFL-1.1 | VF wght 100-900, wdth | 49-54 | 124 | 29 | - | Editorial serif. |
| Poppins | OFL-1.1 (ITF) | static 100-900 | 35-39 | - | 7-8 | - | **Best single family for Hinglish captions**: the same geometric design in both scripts, and the smallest files. |
| Mukta | OFL-1.1 (c) Girish Dalvi, Ek Type | static 200-800 | 92-104 | - | 20-21 | about 410-430 KB per weight | Clean humanist. Heavier files. |
| Hind | OFL-1.1 (c) Indian Type Foundry | static 300-700 | 69-73 | - | 15-16 | about 280-300 KB per weight | Workhorse text face. |
| Baloo 2 | OFL-1.1 (Ek Type) | VF wght 400-800 | 56-64 | **112** | 32 | 667 KB | Chunky, friendly. The best "YouTuber" Hindi caption face. |
| Anek Devanagari | OFL-1.1 (Ek Type) | VF wght 100-800, **wdth 75-125** | 81-93 | 252 (all axes: latin 112) | 44 | 2.1 MB | Width axis for squash and stretch kinetic type. Heaviest file. |
| Teko | OFL-1.1 | VF wght 300-700 | 28-32 | **62** | 15 | - | Condensed sports / impact. Lightest Devanagari. |
| Rajdhani | OFL-1.1 | static 300-700 | 72-77 | - | 14-15 | - | Squared techno. |
| Khand | OFL-1.1 | static 300-700 | 76-88 | - | 14-15 | - | Condensed. |
| Yatra One | OFL-1.1 | static 400 | 70 | - | 15 | - | Display / festive. |
| Rozha One | OFL-1.1 | static 400 | 71 | - | 18 | - | High-contrast display headline. |
| Kalam | OFL-1.1 | static 300/400/700 | 103-107 | - | 21-22 | - | Handwritten Hindi notes. |
| Tiro Devanagari Hindi | OFL-1.1 | static 400 | 97 | - | 26 | - | Bookish serif. |
| Martel | OFL-1.1 | static 200-900 | 40-45 | - | 18-19 | - | Serif. |
| Eczar | OFL-1.1 | VF wght 400-800 | 45-50 | 86 | 26 | - | Display serif. |
| Sarpanch | OFL-1.1 | static 400-900 | 61-64 | - | 13-14 | - | Squared display, up to Black. |
| Biryani / Karma / Laila / Gotu / Amita / Palanquin Dark | OFL-1.1 | static | 35-133 | - | 13-33 | - | Alternates. |

**Other Indic scripts** for wider Indian reach. Each figure is the variable wght woff2 for that script subset:
- Anek family, all OFL variable: Bangla 152 KB, Tamil 50, Telugu 137, Gujarati 155, Gurmukhi 31, Kannada 111, Malayalam 65, Odia 87.
- Baloo siblings, also OFL: Baloo Thambi 2 (Tamil) 37 KB, Baloo Da 2 (Bengali) 88 KB, and the rest of the family.

**Pack budget.** A Devanagari caption pack of Poppins (4 weights), Noto Sans Devanagari VF, Baloo 2 VF, Teko VF, Mukta (3 weights), Hind (2 weights) and Rozha One comes to about **1.1 MB** (deva plus latin woff2). Adding Anek VF brings it to about 1.4 MB.

## 3. Emoji and icons

### Emoji (static)

| Set | Licence (verified) | Source | Size | Verdict |
|---|---|---|---|---|
| **Noto Color Emoji (font)** | **OFL-1.1** (`2D/fonts/LICENSE`; google/fonts `ofl/notocoloremoji/OFL.txt`) | github.com/googlefonts/noto-emoji (release `v2026-09-24-unicode18_0`, Unicode 18) | `NotoColorEmoji.ttf` (CBDT) 10.2 MB. `Noto-COLRv1.ttf` 4.8 MB. Fontsource single woff2 5.5 MB. Google Fonts CSS2 serves 11 unicode-range slices, about 2.0 MB total. google/fonts TTF 24 MB | **MUST.** Pin it as the last family in *every* caption font stack, so Chrome never falls back to Apple Color Emoji on a Mac render box. COLRv1 renders in Chrome. Use CBDT for broad compatibility. |
| **Noto Emoji 2D images** (SVG / PNG) | **Apache-2.0** ("Tools and most image resources are under the Apache license"). Flags in `third_party/region-flags` are public domain | same repo, `2D/svg`, `2D/png/{32,72,128,512}` | 3,751 SVG = 40 MB. 3,750 PNG at 512 = 91 MB | **MUST** as the vector emoji source for `setGlyphSource` (SVG scales cleanly to 1080x1920). |
| **Noto 3D Emoji** (new in 2026) | Images Apache-2.0; `3D/fonts` OFL-1.1 (LICENSE file in folder) | same repo, `3D/png/{32,72,128,512}`. Fonts are in Git LFS, or `Noto-3D-Emoji-Fonts.zip` (821 MB) on the release | **512x512 PNG** (header verified). 4,007 files: 845 MB at 512 (about 220 KB each), 63 MB at 128, 27 MB at 72 | **SHOULD.** It replaces Fluent 3D (256 px) for big "3D emoji pop" moments. Fetch per-emoji, on demand, or a curated subset of about 300 (about 65 MB). Never fetch the whole set. |
| Fluent Emoji (Microsoft) | MIT, Copyright (c) Microsoft Corporation. The LICENSE file is MIT, and the README says nothing more about the assets | github.com/microsoft/fluentui-emoji | 1,595 emoji, each with 3D PNG (256x256, for example fire = 26 KB), Color SVG, Flat SVG and High Contrast SVG. Repo 133 MB | Already in motion-pack (279 subset). Keep it. Its 3D PNGs are low-res for 9:16. |
| Twemoji (jdecked fork) | Graphics **CC-BY 4.0**, code MIT | github.com/jdecked/twemoji v17.0.3 (`@twemoji/api@17.0.3`) | 4,009 SVG = 9.7 MB | **NICE / flagged.** Attribution is required. Twemoji accepts a mention in an About page for software, but each creator's published video is a separate share, so it needs a credit line. Use it only behind the attribution ledger (section 9). |
| OpenMoji | **CC BY-SA 4.0** (openmoji.org/faq: video use should credit in the description, credits or voice-over) | github.com/hfg-gmuend/openmoji 17.0.0 | SVG colour zip 5.1 MB, 618 px PNG zip 45 MB | **REJECT as default.** Share-alike can attach to the adapted video, and motion-pack's THIRD_PARTY.md already refuses it. |
| Apple Color Emoji | Proprietary | the macOS system font | - | **REJECT.** It is the trap that Chrome fallback walks into. |
| "Animated Fluent Emojis" (Tarikul-Islam-Anik) | NOASSERTION. The README says they are Microsoft *Teams* animated emoji, which were never released openly | github.com/Tarikul-Islam-Anik/Animated-Fluent-Emojis | - | **REJECT** (provenance). |

### Emoji (animated): see section 6, Noto Animated Emoji (CC BY 4.0, 881 Lottie files).

### Icons

| Set | Licence (verified) | Count / size | Verdict |
|---|---|---|---|
| Lucide 1.59.0 (2026-10-17) | **ISC**. The Feather-derived icons (the list is in LICENSE) are **MIT** (c) Cole Bemis. GitHub shows NOASSERTION because of the dual file | 1,899 SVG = 754 KB. Release zip 1.4 MB, font zip 5.0 MB | Already a subset in motion-pack. Optionally widen it to the full set. |
| **Tabler Icons** v3.49.0 (2026-10-05) | **MIT** ("Tabler Icons is licensed under the MIT License") | 6,238 (5,184 outline = 2.9 MB SVG; 1,054 filled = 644 KB). Adjustable stroke-width | **SHOULD.** It is the largest MIT stroke set, and good for draw-on animation (the pack's SVGO config already handles stroke sets). |
| Phosphor (core v2.0.8) | **MIT** (c) 2023 Phosphor Icons | 1,512 icons x 6 weights (thin, light, regular, bold, fill, duotone). Regular = 746 KB SVG | Already a subset in motion-pack. |
| **Material Symbols** (Outlined / Rounded / Sharp) | **Apache-2.0** (github.com/google/material-design-icons: "available ... under the Apache License Version 2.0"; attribution "not required"). *Fontsource metadata labels it OFL-1.1, which looks wrong: treat it as Apache-2.0* | About 4,300 glyphs (the codepoints index has 4,301 lines). Variable fonts with FILL 0-1, wght 100-700, GRAD -50..200, opsz 20-48: woff2 is 3.9 MB Outlined, 5.3 MB Rounded, 3.4 MB Sharp. **Google Fonts `&icon_names=` subsetting: 10 icons with all 4 axes = 25 KB woff2** (measured) | **SHOULD.** The FILL axis animates as an outline-to-solid "selected" pop. Ship icon_names subsets, not the 4-5 MB file. |
| Heroicons | MIT | about 300 | NICE (small). |
| Iconoir | MIT | 1,600+ | NICE. |
| Remix Icon | **Custom "Remix Icon License v1.0" (Jan 2026)**, no longer Apache. It permits SaaS use but forbids competing icon libraries, standalone packs and logo use | - | **AVOID** (non-OSI and changes over time). Tabler or Lucide cover the same need. |
| Simple Icons (brand logos) | CC0-1.0 for the SVG data. **The trademarks still belong to each brand** | about 3,000 brands | **FLAG.** Use a logo only to *refer to* the brand (such as "posted on Instagram"), never to imply endorsement, and follow each brand's guidelines. Keep it out of default templates. |
| Material Design Icons (Templarian, community) | NOASSERTION (mixed: Apache plus community "Pictogrammers Free License") | 7,000+ | AVOID (mixed licence). |

## 4. Textures and overlays (film grain, dust, light leaks, paper)

**Finding: no truly CC0 film grain or light-leak video library could be verified.**
- Searches returned only paid packs, Gumroad "pay what you want" packs with no stated or custom licences, CC-licensed packs that need credit, and Uppbeat clips with no stated licence.
- An Openverse search (`license=cc0,pdm`, "film grain") returned 240 hits that are mostly AI-generated Flickr art, not usable grain plates.
- Pexels and Pixabay *do* host grain and leak clips under their own licences. Both forbid standalone redistribution, so they cannot ship as a bundled overlay library (section 7).

**Recommendation: procedural is better for grain, dust, scratches, light leaks, vignette, bokeh, halation, scanlines, VHS and paper grain.** motion-pack already generates all of these deterministically (seek-safe, resolution-independent, no licence or attribution, zero bytes):
- `layers/overlay.js` handles DOM HyperFrames.
- `layers/finisher.js` handles plate pixels: bloom, halation, chroma.
- The 7 grain stocks give a measured sigma.

If a "real scanned film" feel is wanted later, there are two ways to get it with clean rights:
- (a) Shoot owned plates: a lens-off light leak (the cap held against the mount) or a scanned blank film leader. Material you shoot is yours to release as CC0.
- (b) Bake procedural plates with the pack's Blender recipes and ship the bakes as CC0 loops.

For still photographic textures (paper, cardboard, fabric, concrete, plaster backdrops and "paper cut-out" looks), these CC0 sources are verified:

| Source | Licence (verified) | Size / API | Verdict |
|---|---|---|---|
| **ambientCG** | **CC0 1.0** ("copy, modify, distribute and perform the assets, even for commercial purposes"; credit optional). docs.ambientcg.com/license/ | API `ambientcg.com/api/v2/full_json` (and v3). On 2026-10-20: 12 paper, 7 cardboard, 121 fabric, 78 concrete, 39 plaster, 10 grunge. The PBR zip for Paper006 is 4.5 MB at 1K-JPG, 17 MB at 2K, 69 MB at 4K. Only the Color map is needed (about 1/5 of the zip) | **SHOULD.** Curate 15-25 colour maps at 2K (roughly 40-80 MB) as a CC0 "paper / fabric / wall" background pack. |
| **Poly Haven** | **CC0** ("You can use our assets for any purpose", redistribution and bundling allowed). The ToS bans scraping. Building on the *live API* requires a "Powered by Poly Haven" credit (Public-API README) | Textures and HDRIs (for three.js / Blender 3D backgrounds and reflections) | **SHOULD** for 3D scenes. Curate and vendor files rather than calling the live API, so no credit line is needed. |
| Texture Ninja | The site is JS-rendered and its licence text could not be read | - | Unverified, skip. |
| Prelinger Archives (archive.org) | Per-item: many are public domain or CC, but "the user assumes all risk" | - | Only a per-clip, hand-checked source of real film texture. Not a bundle. |

## 5. LUTs

**Recommendation: generate .cube LUTs procedurally. motion-pack already does, and it is the better path.**
- It has 45 named looks, 3 log-to-709 cubes and a neutral roll-off, with `grade.js` emitting GLSL, SVG filter or `.cube` from one closed-form grade.
- That means zero licence risk, one consistent look across the DOM, WebGL and ffmpeg `lut3d` paths, and parameters that can animate (`look.gradeIn`).
- New looks are a parameter set, not a download.

| Candidate | Licence | Size | Verdict |
|---|---|---|---|
| "Free LUT packs" (FreeVisuals, Gropixe, IWLTBAP and similar) | Custom promotional terms, no open licence, and typically no redistribution | small | **REJECT** for bundling. |
| Q-DDL "800+ free LUTs" (20 packs x 40, .cube) | **CC BY 4.0** (per CG Channel, 2020-01-19). It is distributed through an ad-shortener at quickddl.net | - | **NICE at most / flagged**: attribution per video, unclear provenance, and many named after film stocks (trademarks). Prefer procedural. |
| RawTherapee Film Simulation Collection (HaldCLUT) | **No licence statement found** (forum threads only *suggest* CC-BY or CC-BY-SA). Uses Kodak / Fuji stock names | - | **REJECT** until a licence is shown. |
| Tony McMapface (h3r2tic) | **MIT OR Apache-2.0** (both LICENSE files present) | 48^3 `.spi3d` 4.4 MB; `.dds` 432 KB | NICE: an HDR *display transform* for three.js / Blender CG plates, not a creative grade. |
| OpenColorIO-Config-ACES | **BSD-3-Clause** | - | NICE, for a colour-managed 3D pipeline only. |
| AgX (sobotka/AgX, EaryChow/AgX) | **No licence** (GitHub null) | - | REJECT. Re-implement it from the published description instead, the way the pack did with Khronos PBR Neutral. |

## 6. Lottie and animated stickers

| Source | Licence (verified) | Size | Verdict |
|---|---|---|---|
| **Noto Animated Emoji** (Google) | **CC BY 4.0**. The site FAQ, answering "Can I use these animated assets commercially: for a video, for broadcast, apps", says "Animated Noto Emoji is licensed under" CC BY 4.0 (legalcode link) | **881 animated emoji** (`googlefonts.github.io/noto-emoji-animation/data/api.json`). Per emoji: `lottie.json`, 512x512 `.webp` / `.gif` / `.avif`, and `emoji.svg` at `fonts.gstatic.com/s/e/notoemoji/latest/<cp>/`. Measured: fire Lottie 29 KB / webp 185 KB / gif 464 KB; joy 58 / 609 / 1,149 KB; exploding-head 140 / 596 / 1,071 KB; rocket 80 / 181 / 256 KB. The full Lottie set is roughly 60 MB (estimate) | **SHOULD.** It is the highest-value animated emoji source for reels. Use the Lottie through the lottie-web SVG renderer (motion-stack verdict). The FAQ says the static "rest" frame is a marked keyframe, which suits pop-in or hold. **Requires attribution**, so wire the ledger (section 9). |
| LottieFiles free animations | **Lottie Simple License (FL 9.13.21)**: commercial use allowed and attribution not required. **But:** redistribution "must contain (and be subject to) the same terms", no "compiling Files from LottieFiles" for a similar or competing service, and the help page adds "Cannot redistribute as standalone animation files" and "Cannot resell the original animation files". Each animation page may add restrictions | - | **Do not bundle** them into a Reel Director library (compiling plus a standalone redistribution risk). At most, let a user import a LottieFiles animation into their own project, and keep its URL in the ledger. |
| Rive Community / Marketplace | **CC BY** (CC BY 4.0) on every community file | - | NICE, behind the ledger. motion-stack has a Rive verdict. |
| Lordicon | Free tier is based on **CC BY-ND 4.0, non-commercial** | - | **REJECT.** |
| lottie-web / dotlottie-web / lottie-player (players) | MIT | - | These are players only: already covered by motion-stack. |
| Open Peeps / Open Doodles / Humaaans (Pablo Stanley), as static SVG illustration stickers | **CC0** (openpeeps.com: "Free for commercial and personal use under CC0 License"; humaaans.com: "CC0 Free for commercial or personal use") | small SVG kits | NICE: a hand-drawn people and doodle sticker pack that can be animated with GSAP draw-on. |

**Is procedural better?** For stickers, arrows, underlines, call-out bubbles, check marks, counters and the like: **yes**.
- Author them as GSAP / SVG parts (motion-pack `type/gfx`), or generate Lottie with the `text-to-lottie` skill. Both are owned, CC0 and seek-safe.
- Lottie from outside is only worth it for things that are expensive to draw, which mainly means animated emoji.

## 7. Stock B-roll APIs (in-product use)

| API | Key | Limits | Attribution / product terms (verified) | Video specifics | Verdict |
|---|---|---|---|---|---|
| **Pexels API** | Free key with a Pexels account | 200 req/hour, 20,000/month by default. Higher limits are free on request: show your attribution implementation, and Pexels may grant unlimited | You must show a "prominent link to Pexels" and credit photographers "when possible". "You may not copy or replicate core functionality of Pexels" (for example a wallpaper app). ToS s.8 forbids "Bulk, large-scale or systematic copying" and using or compiling Content "to replicate a similar or competing service". Licence: free, modify, no attribution in the video; no selling unaltered copies, no trademark use, no endorsement implied, identifiable people never shown in a bad light | `/v1/videos/search` with **`orientation=portrait`** and `size` (large = 4K, medium = Full HD, small = HD). Multiple `video_files` up to 4096x2160, plus HLS. `per_page` max 80 | **MUST** as the primary B-roll source. The pattern is a search triggered per reel, with credit shown in the app UI. Download clips into that user's render cache. Never pre-bulk-download into a shared library. |
| **Pixabay API** | Free key with an account | **100 req / 60 s** per key. "Requests must be cached for 24 hours". "Systematic mass downloads are not allowed"; the API is "made for real human requests" | You must "show your users where the images and videos are from, whenever search results are displayed". Images: no permanent hotlinking, download to your own server. Videos "may be embedded directly ... Yet, we recommend storing them on your server". Content Licence: no "Standalone" sale or distribution, no commercial use of trademarked content, care with recognisable people | `video_type` all / film / animation, `category`, `min_width` / `min_height`. **No orientation filter for video**: filter w<h client-side. Renditions are large / medium / small / tiny with byte sizes in the JSON (doc example: 1920x1080 12 s = 6.3 MB; 640x360 = 1.0 MB) | **SHOULD** as a second source and fallback. |
| Coverr API | **Key only by emailing team@coverr.co** with a use-case | Not published | Docs: free "as long as you don't charge for it yourself, AKA re-sell or use the videos for commercial use". You must show a clickable Coverr logo. Licence: "You may not use our content to build or offer a service that is similar to or competes with Coverr.co"; videos "can't be ... offered as part of services to which providing videos can help" | `is_vertical` flag, `max_width` / `max_height`, mp4 URLs with a token. The library was about 3.6k videos in the doc example | **REJECT for a paid SaaS** without a written commercial agreement. |
| Unsplash API (stills) | Key and app review | Not stated; access is cut off "if abused" | **Must hotlink** `photo.urls`, must trigger the `download_location` endpoint, must credit Unsplash and the photographer. The API is for "non-automated" experiences and must not replicate Unsplash | stills only | **AVOID** for a render pipeline (hotlinking conflicts with baking frames). |
| Mixkit (Envato) | No public API | - | The licence text sits in a JS modal and **could not be retrieved**, so it is unverified | - | Skip. |
| Openverse API | Anonymous (20/min burst, 200/day) or registered | - | Per-item CC licences. Images and audio only, **no video** | - | NICE for CC0 stills or audio search with per-item checks. |

**Is procedural better?** No. B-roll is real-world footage. The alternatives are AI-generated B-roll (the Seedance / Higgsfield skills, with their own terms and an AI-disclosure label) or the creator's own footage.

## 8. Recommended "packs" to add (gap list)

1. **Caption font pack (Latin)**, about 0.7 MB, OFL/Apache: see the section 1 budget. Wire it into frame-design's type pairing and the motion-pack `type` presets.
2. **Devanagari / Hinglish font pack**, about 1.1-1.4 MB, OFL: this fixes the `caption.bilingual` system-font fallback.
3. **Emoji pack**: pin Noto Color Emoji (OFL) at the end of every caption font stack. Use Noto 2D SVG (Apache) through `setGlyphSource`. Fetch Noto 3D 512 PNG (Apache) per emoji on demand.
4. **Animated emoji pack**: Noto Animated Emoji Lottie (CC BY 4.0), fetched on demand and logged to the ledger.
5. **Icon pack**: full Tabler (MIT) plus Material Symbols via `icon_names` subsets (Apache).
6. **CC0 texture / background pack**: 15-25 ambientCG colour maps at 2K, plus a few Poly Haven HDRIs for 3D.
7. **B-roll connector**: Pexels (primary) and Pixabay (fallback), searched per reel, credit shown in the UI, clips cached per user.
8. **Style packs** (caption style, grade, overlay and font presets): these are **owned code, not downloads**. They combine section 1-2 fonts, motion-pack looks and overlays, and frame-design palettes. **Do not name presets after real creators** (for example "Hormozi style" or "MrBeast style"); use neutral names such as "bold-pop" or "boxed-yellow".

Already covered, so do not add: SFX and music (motion-pack synthesised plus Kenney / OwlishMedia CC0), transitions, grain / leaks / dust, LUT looks, mesh and aurora backgrounds.

## 9. Attribution ledger (needed before any CC-BY source)

CC BY 4.0 s.3(a) obliges whoever *shares* the material to credit it. Here that is the creator who publishes the reel, not just the SaaS. If Reel Director uses any CC-BY asset (Noto Animated Emoji, Twemoji, Rive community, Q-DDL), it should:
- write `credits.json` per render (asset id, author, licence, URL);
- append a ready-made line to the social-video post copy, for example "Animated emoji: Noto Emoji Animation by Google, CC BY 4.0";
- block publishing if the line was removed.

MIT, ISC, Apache-2.0 and OFL assets need their licence texts in the app's third-party notices page, but no per-video credit. CC0 needs nothing.

## Sources (licence pages read on 2026-10-20)
- Fontsource API: https://api.fontsource.org/v1/fonts/{id} (licence, subsets, axes). Google Fonts repo: https://github.com/google/fonts (OFL.txt per family)
- Noto Emoji: https://github.com/googlefonts/noto-emoji (README licence section; 2D/fonts/LICENSE; 3D/fonts/LICENSE)
- Noto Animated Emoji: https://googlefonts.github.io/noto-emoji-animation/ (FAQ: CC BY 4.0; data/api.json = 881 entries)
- OpenMoji: https://openmoji.org/faq/. Twemoji: https://github.com/jdecked/twemoji. Fluent Emoji: https://github.com/microsoft/fluentui-emoji
- Lucide: https://github.com/lucide-icons/lucide (LICENSE). Tabler: https://github.com/tabler/tabler-icons. Phosphor: https://github.com/phosphor-icons/core. Material Symbols: https://github.com/google/material-design-icons. Remix Icon: https://github.com/Remix-Design/RemixIcon/blob/master/License
- LottieFiles: https://lottiefiles.com/page/license, https://help.lottiefiles.com/animation-licensing-basics-, full text mirrored at https://doc.qt.io/qt-6/qtlottieanimation-attribution-happy-star.html
- Rive: https://rive.app/docs/community/marketplace-overview. Lordicon: https://lordicon.com/licenses
- Pexels: https://www.pexels.com/license/, https://www.pexels.com/api/documentation/, https://www.pexels.com/terms-of-service/
- Pixabay: https://pixabay.com/api/docs/, https://pixabay.com/service/license-summary/
- Coverr: https://coverr.co/license, https://api.coverr.co/docs/ (and /docs/auth/, /docs/videos/)
- Unsplash: https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines
- ambientCG: https://docs.ambientcg.com/license/. Poly Haven: https://polyhaven.com/license, https://github.com/Poly-Haven/Public-API
- Tony McMapface: https://github.com/h3r2tic/tony-mc-mapface. OCIO ACES: https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES. Q-DDL LUTs: https://www.cgchannel.com/?p=111770
- Open Peeps (CC0): https://www.openpeeps.com/. Humaaans (CC0): https://www.humaaans.com/
