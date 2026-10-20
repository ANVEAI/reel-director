# hooks-structure: hooks and storyboard structure for talking-head reels (Reel Director)

Scope: 1080x1920 talking-head reels, 15-60 s. The creator only reads a script; the director must decide hook treatment, beat roles, timing, loop seam and ending by rule. This note covers the **script and storyboard layer** (what is said when, and how each beat is staged). Captions styling, cut pace and sound live in the sibling notes (`captions-graphics.md`, `editing-pace.md`, `sound.md`, `trends-2026.md`). Where a number here overlaps theirs, it is aligned and cross-referenced.

Evidence labels used throughout:
- **measured**: a platform metric definition, a dataset with a stated method, or my own count on a named sample (sample size given).
- **consensus**: several independent practitioner or platform-published sources agree; no controlled test.
- **rule-of-thumb**: one creator's practice, my reading of a small sample, or a house default. Tune by Reel Director's own analytics.

Honesty notes on this pass:
- The shared web-search budget ran out mid-pass. Remaining gaps are listed in section 12.
- I read YouTube Shorts pages in a normal browser (titles, view counts, durations, a few paused frames). No media was downloaded. YouTube's transcript panel worked for 6 Hormozi Shorts. It then returned HTTP 400, so I stopped rather than work around it. Transcripts are used for counts and structure only; nothing is reproduced here beyond short paraphrase.
- I could not read Instagram Reels without logging in. YouTube Shorts from the same creators (who cross-post) stand in for Reels. Dan Koe's reach is mostly on Instagram and X, so his YouTube numbers understate him.

---

## 0. The answer in twelve lines (for the director)

1. **The opening is now measured directly.** Instagram's skip rate is the share of viewers who leave in the first 3 s (Aug 2025). YouTube shows "viewed vs swiped away". Meta measured an average dwell of **1.7 s per mobile feed item**, and recall after **0.25 s** of exposure (2016). Frame 0 and the first spoken words carry the hook. Nothing comes before them.
2. **First spoken word at ≤ 0.20 s. Line 1 ≤ 14 words, with the topic word, figure or name inside the first 8 words.** No greeting, self-intro or agenda.
3. **Stack two hook devices in line 1** (a specific figure, a named entity, a contrast or negation, "you", or a withheld referent such as "this"). 53% of 287 top Shorts titles from six educator creators stack two or more.
4. **Hook text by 0.3 s, 4-6 words.** The median top-Short title in the sample is **6 words**.
5. **Use the context → "but" → snapback shape** when line 1 sets context. The contrast word lands inside 6 s (Kallaway; observed in Codie Sanchez's 13M-view Short at about 2.5 s).
6. **Spine:** hook (0-3 s) → promise or foreshadow (≤ 3 s, by about 8 s) → 2-4 beats, each with a micro-payoff, joined by "but" or "so" → turn at 45-70% → **payoff starting in the final 20%** → hard stop.
7. **End on the payoff, not a card.** 9 of 10 top Shorts I checked end on the speaker's payoff line, with no end card and no spoken "follow". At most 0.5 s of picture after the last word.
8. **Length by job:** one idea 15-25 s; claim with proof, story or explained list 35-55 s. The top-Short sample has a median of **46.5 s** (n = 54); 52% sit at 45-60 s.
9. **Never pad.** On Kuaishou the median per-video completion rate falls from about 50% for 8 s videos to about 33% at 20-30 s and about 25% at 41-59 s. Every added second must buy new information.
10. **Loop every reel of 35 s or less, and the 7-12 s cutdown.** The last line completes or calls back to line 1, and the last frame matches frame 0's framing.
11. **Pick the hook family by format.** Dilemma or figure (Warikoo), celebrity or "how X really" (Codie), named concept (Ali Abdaal), second-person aphorism (Dan Koe), first-person story or confession (Hormozi), guest list-claim (Raj Shamani).
12. **Test hooks, not bodies.** Three hook variants on one identical body, posted as Trial Reels. Keep the variant with the lowest skip rate.

---

## 1. What is measured about the opening seconds

| fact | number | source | grade |
|---|---|---|---|
| Instagram **skip rate** = share of viewers who scroll past before the first 3 s. It replaced "view rate". The retention chart sits beside it ("the flatter the line, the more engaged") | 3 s window | Instagram via Social Samosa, 25 Aug 2025; Metricool explainer | measured (platform definition) |
| Third-party "healthy skip rate" bands (under 30-40% good, over 50% weak hook) | 30-50% | blogs only | **unverified**; use your own history (`trends-2026.md` §7) |
| YouTube "viewed vs swiped away" (also "stayed to watch"); no published seconds threshold | n/a | creator glossaries | consensus |
| Average viewed rate across Shorts per Jenny Hoyos: about **70%**; hers about **85%**. She treats **≥ 90% average retention** as the floor for a breakout. On her channel, Shorts under 30 s needed **> 100%** (rewatches) | 70 / 85 / 90 / 100% | Creator Science podcast (primary interview) | rule-of-thumb (one top creator's channel data) |
| Hoyos: trimming the final second of a 32 s Short, where retention fell from 70% to 45%, raised average retention from **83% to 88%** | +5 pp | same | rule-of-thumb (one case) |
| Mobile feed: people spend **1.7 s** per item on average (desktop 2.5 s); **0.25 s** exposure gives statistically significant recall | 1.7 s, 0.25 s | Facebook IQ, 20 Apr 2016 (Fors Marsh tests; 850+ ads, Nielsen ad-recall regression r² = 0.82) | measured (old, ads, Meta) |
| Over **63%** of TikTok auction ads with the highest CTR state the key message in the first **3 s**. Ads shot vertically show **+25%** 6 s watch-through. **33%** of top-VTR ads break the fourth wall (talk to camera). **40%** of top-VTR ads use concise text overlays | 63% / 25% / 33% / 40% | TikTok for Business, "9 Creative Tips" PDF (undated, about 2021-22) | measured (platform correlation, ads, not causal) |
| Kuaishou **median per-video completion rate** by video length (read from Fig. 4): about 0.8 at 1 s, **0.5 at ~8 s**, 0.4 at ~15 s, **0.33 at 19-30 s**, about 0.28 at 31-40 s, **0.25-0.28 at 41-59 s**. Top-quartile videos: about 0.67 (8-18 s), 0.6 (19-30 s), 0.5 (30-40 s), 0.45 (41-59 s). Average view time rises almost linearly with length (about 37 s for 60 s videos) | see left | Quan et al., "Alleviating Video-Length Effect for Micro-video Recommendation" (Tsinghua and Tencent; arXiv 2308.14276, ACM TOIS) | measured (research; Chinese platforms, 2021-22 data) |
| On WeChat Channels the **last video watched before a user exits the app tends to be longer** than average (fatigue) | distribution shift | same paper, Fig. 2 | measured (research) |
| Kuaishou's D2Q ranks watch time as a quantile **within a duration group**, so long videos get no free credit | n/a | Zhan et al., KDD 2022 (arXiv 2206.06003) | measured (research; see `trends-2026.md` §1.4) |

**What this means for a deterministic director:**
- The first 1-2 s decide the skip. Spend them on the stake, not on the person's name.
- Per-video completion falls steeply over the first ~15 s and then flattens. Front-load information, and keep each later second dense.
- A completion-normalised ranker punishes padding, and a long video that bores someone may end their session.

---

## 2. My sample study: what top educator and business creators actually do

### 2.1 Method

- **Titles and views:** the top ~48 Shorts by the YouTube "Popular" sort for six creators: @AlexHormozi, @aliabdaal, @CodieSanchezCT, @DanKoeTalks, @warikoo, @RajShamani (n = 287). @tanmaybhat (comedy and reaction) was listed but kept out of the educator counts. Read 20 Oct 2026.
- **Durations:** the player length for the top 7-12 Shorts per creator (n = 54).
- **Transcripts:** 6 Hormozi top Shorts (YouTube auto-captions, 7-8 s segments) for speech rate, hook length and payoff position.
- **Frames:** 0.4 s, 2.5 s and the final 1.2 s of the #1 Short for five creators (13 frames in all).
- **Classification:** regex multi-label tagging of titles (`raw/classify.py`). A spot check suggests the error rate is about ±10 percentage points per label.
- **Caveat:** Shorts titles are a proxy for the hook. In the 6 transcripts, the spoken first line matches the title's device every time.

### 2.2 Hook-device mix per creator (share of top ~48 titles; a title can carry several devices)

| device | Hormozi | Ali Abdaal | Codie Sanchez | Dan Koe | Warikoo | Raj Shamani | all (287) |
|---|---|---|---|---|---|---|---|
| specific figure ($, ₹, grams, times, IQ) | 15% | 19% | **42%** | 12% | **53%** | 8% | 25% |
| question | 12% | 6% | 19% | 2% | **72%** | 23% | 22% |
| named person, brand or guest | 10% | 15% | 23% | 0% | 23% | **56%** | 21% |
| "how / why X really works" | 10% | 19% | **25%** | 15% | 21% | 21% | 18% |
| withheld referent ("this", "these", "...", "spoiler") | **23%** | 6% | **29%** | 10% | 9% | 10% | 15% |
| negative or warning (stop, avoid, worst, lost) | 19% | 2% | 19% | **27%** | 4% | 15% | 14% |
| numbered list (3 hacks, 13 books) | 10% | **25%** | 6% | 4% | 4% | 15% | 11% |
| second-person claim ("You only need...") | 2% | 0% | 0% | **48%** | 4% | 4% | 10% |
| first-person story or confession | **27%** | 10% | 8% | 4% | 0% | 4% | 9% |
| A vs B choice or dilemma | 2% | 2% | 2% | 6% | **38%** | 2% | 9% |
| named concept ("The X Effect", "The Y Method") | 2% | **23%** | 17% | 0% | 0% | 0% | 7% |
| **two or more devices stacked** | 38% | 35% | 69% | 42% | **83%** | 54% | **53%** |

**Reading the table:**
- Each creator owns one or two hook families.
- Stacking two or more devices is the norm (53%). Within a creator, though, stacked titles did **not** reliably rank higher: top-10 versus the rest differed by 0.1-0.4 labels, in both directions. Treat stacking as a craft default, not a proven lift.
- **Title length: median 6 words for every creator; p90 8-11.** This matches the house cap of 7 hook words or fewer.

### 2.3 Length of top Shorts (n = 54)

| creator | n | median | range | share 30-60 s |
|---|---|---|---|---|
| Hormozi | 12 | 40 s | 18-151 | 58% |
| Ali Abdaal | 7 | 57 s | 39-60 | 100% |
| Codie Sanchez | 9 | 48 s | 43-60 | 100% |
| Dan Koe | 9 | 59 s | 29-167 | 67% |
| Ankur Warikoo | 9 | 36 s | 29-56 | 89% |
| Raj Shamani | 8 | 52.5 s | 29-60 | 88% |
| **all** | **54** | **46.5 s** (p25 38, p75 58.6) | | under 30 s: 13%; 30-44 s: 30%; **45-60 s: 52%**; over 60 s: 6% |

This agrees with Socialinsider's 2026 Reels data (about 6M brand Reels: 45-60 s had the best engagement rate, 0.35%, and the most median views, 10,374) and Galloway's Shorts study (50-60 s best). It disagrees with the older "15-35 s" house default for talking-head; see `trends-2026.md` §2.

### 2.4 Speech rate, hook length and payoff position (Hormozi, 5 monologue transcripts)

| Short (views) | length | words | words/s | line 1 (paraphrase, word count) | where the payoff starts |
|---|---|---|---|---|---|
| Build the Right Foundation (9.5M) | 54 s | 195 | 3.6 | "If I asked you to build the tallest tower in 10 s, here's how" (17 words; conditional + live prop demo) | lesson at 47 s = **87%** |
| When I was single (9M) | 45 s | 237 | 5.3 | single, ate at one chain 500+ times (figure inside 15 words) | no lesson; anecdote ends mid-sentence (loop-like cut) |
| Always Be Ready (8.7M) | 55 s | 293 | 5.3 | cold open at a gas station with a kid selling perfume (in medias res) | three rules from 38 s = **69%**, last line at 96% |
| Cheat code at 34 (4.9M) | 18 s | 72 | 4.0 | the "wish I knew at 24" frame (12 words) | single claim; the whole Short is the payoff |
| Top 13 books (4.7M) | 43 s | 173 | 4.0 | "I buy ~50 books a year, study a few" (credibility figure in 7 words), then "here are the only ones" | rapid list, about **2.7 s per item** |

- **Words per second:** 3.6-5.3, median 4.0. That is 240 wpm, against conversational speech at 140-160 wpm. Some of this is likely editing: silences cut, and possibly sped up.
- **CTAs:** a 6th transcript (a 151 s hot-seat clip) is dialogue. None of the 6 contains a spoken CTA.

### 2.5 Frames: what the screen does at 0.4 s, 2.5 s and the end

| creator, #1 Short | 0.4 s | 2.5 s | last 1.2 s |
|---|---|---|---|
| Hormozi, Foundation | creator plus a **physical prop** (a tower of boxes) mid-action; one-word caption at mid-frame | the prop demo continues | lesson line on the face |
| Codie Sanchez, Ryan Reynolds (13M) | face in a podcast set; **name-drop as a huge condensed-caps caption** (1-2 words, y about 58%) | **already cut to celebrity B-roll**; the "but it's actually" contrast spoken | thesis words as a 2-word caption on the face (callback to the title); **no end card** |
| Dan Koe, One hour | very tight face, cinematic grade; 3-word serif caption on a black bar at mid-frame | key figure as a caption ("60 minutes") | payoff line on the face, restating the hook's promise; **no end card** |
| Warikoo, iPhone vs Apple shares (27M) | medium close-up in a studio; **animated cutout in the headroom** (a flag) | iPhone cutout plus a **price tag figure** in the headroom; small caption pill | **giant figure reveal** in the headroom plus a face reaction; **no end card** |
| Raj Shamani, Top 4 businesses (29M) | guest clip; yellow 2-line caption states a **numbered claim** ("there are 4 businesses...") | same | branded podcast end card while the voice finishes (the only end card seen) |
| Ali Abdaal, Atomic Habits lessons | **prop pushed toward the lens** (the book), focus pull | the book held beside the face | (not checked) |

**Patterns:**
- **Object-first hooks** appear in 4 of 6 frame-0 checks: a prop, a cutout or celebrity B-roll by 2.5 s.
- **No persistent headline bar** in any of the 6. The big word-level caption *is* the text hook.
- **9 of 10 endings** (6 Hormozi transcripts plus 4 frame checks) stop on the payoff.

### 2.6 Tanmay Bhat (comedy and reaction, for contrast)

"Wait for it" or "Wait for end" appears in **6 of the top 50** titles. It is an explicit delayed-payoff promise, which is the comedy cousin of the educator "foreshadow" line. Most of his other titles are reaction labels ("Bro needs to slow down") rather than claims.

---

## 3. Hook taxonomy for a script-read talking head

Each type lists: a line-1 template, the frame-0 visual, the text-hook rule, when to use it, who uses it, and the evidence grade. All example lines are mine.

| id | type | line-1 template (≤ 14 words) | frame 0 → 2.5 s visual | hook text (≤ 6 words) | use when | seen in | grade |
|---|---|---|---|---|---|---|---|
| `bold-claim` | contrarian or bold claim | "[Common belief] is wrong. [Short reason]" / "You only need [small thing]" | tight face; punch-in on the claim word by 1.0 s | the claim, compressed | opinion, mindset, strategy | Dan Koe (48% second-person claims), Hormozi | consensus |
| `figure-proof` | specific figure as proof or shock | "I [did X] [N] times / for [N] years" / "This [thing] makes [₹/$ N] a month" | face plus a figure card in the headroom at the moment it is spoken | the figure + a 1-2 word noun | proof-led, money, results | Codie (42%), Warikoo (53%), Hormozi | consensus (prevalence measured) |
| `question` | question to the viewer (specific, answerable, with stakes) | "Would you take [A] or [B]?" / "How much do you need to be in the top 1%?" | face, eyebrows up; options as two chips | the question, ≤ 6 words | finance, comparisons, quizzes | Warikoo (72%) | consensus |
| `dilemma-reveal` | A vs B with a withheld numeric answer | "[₹1 that doubles daily] or [₹1 crore today]?" | both options as headroom cards; a running calculation through the body | "A or B?" | calculable comparisons | Warikoo (38% A vs B; top Short 27M) | measured (prevalence), rule-of-thumb (format) |
| `curiosity-gap` | withheld referent | "This [boring] business quietly makes millionaires" / "Gas stations don't make money from gas" | object partly shown, or a blurred card | "This business...", or a spoiler line | mechanism reveals, "how X really works" | Codie (29%), Hormozi (23%) | consensus |
| `negative` | warning, mistake, avoidance | "Stop [common action]" / "The worst [thing] you can buy" | face; red-accent keyword | "Stop [X]" / "Never [X]" | loss-averse audiences, myth-busting | Dan Koe (27%), Codie, Hormozi (about 19% each) | consensus |
| `story-cold-open` | in medias res, first person | "[Time cue] I was [mid-action] when [odd thing]" | face, slightly wider; one establishing B-roll by 2-3 s | the stake, not the setting | lessons from an event | Hormozi (27% first-person) | consensus |
| `named-concept` | label or named idea | "The [X] Effect explains why you [pain]" | face plus a title-card chip with the concept name | the concept name | psychology, frameworks | Ali Abdaal (23%) | rule-of-thumb |
| `authority-borrow` | named person, brand or guest | "How [famous person] actually made [figure]" / guest's strongest claim first | celebrity or brand card by 2.5 s (rights-cleared only) | the name + verb | clips, case studies | Raj (56%), Codie (23%) | consensus (prevalence measured) |
| `list-promise` | numbered list with a stated count | "[N] [things] that [benefit]; the last one is [tease]" | face plus a count chip "1/N" | "[N] [things]" | how-to, recommendations | Ali (25%), Raj (15%), Hormozi | consensus |
| `conditional-demo` | hypothetical plus a live demonstration | "If I asked you to [task] in [time], here's what you'd do" | prop or action in frame at 0.0 s | the task | concepts with a physical metaphor | Hormozi #1 Short (9.5M) | rule-of-thumb (one strong case) |
| `pattern-interrupt` | visual oddity (pairs with any verbal type) | (verbal from any row) | unexpected prop, extreme close-up, object thrust toward the lens | (from the verbal type) | when the script has a physical noun | Hormozi, Ali, Warikoo | consensus (motion-pack archetype) |

**Hook anatomy (how the first 2-3 sentences work):**
1. **Context lean** (sentence 1). Make the topic and the "who it's for" obvious, then add a benefit, a pain or a surprise. **Scroll-stop interjection** (sentence 2 opens with *but / however / yet / actually*; Hinglish *lekin / par*). **Contrarian snapback** (the new angle, which opens a question). Source: Kallaway via secondary summaries. That source also gives 3-5 words of bold on-screen text and value inside about 4 s for short-form. [consensus]
2. **Hook → foreshadow.** After the hook, at most two short lines (≤ 3 s) set up what the viewer will see at the end. Each body beat then changes the situation ("but... therefore"). Source: Jenny Hoyos, primary. [rule-of-thumb]
3. **Hook → retain → reward.** Every content unit has a stop, a reason to stay, and the promised thing delivered. Source: Hormozi via secondary summaries. [consensus]
4. **Plain words.** Hoyos keeps narration at about a 5th-grade reading level or lower, and explains jargon instead of using it. [rule-of-thumb]

**Banned openers (lint, first 8 spoken words):**
- The list: "hey guys / hi everyone / welcome back / my name is / today I'm going to / in this video / so, / let me tell you / I want to talk about".
- **Exception:** a credibility clause of 7 words or fewer that contains a specific figure ("I've bought 26 businesses", "I read 50 books a year").
- An unverified but widely repeated Hormozi anecdote: cutting a 3 s lead-in took one video from 40k to 780k views. Treat the number as folklore and the direction as consensus.

---

## 4. The first 3 seconds, frame by frame (deterministic spec, 30 fps)

| time | picture | words (speech) | on-screen text | audio |
|---|---|---|---|---|
| frame 0 (0.00 s) | face, tight (H4 in `editing-pace.md`) **or** the prop or payoff visual already moving; never black, a logo or a title card | the first content word **at ≤ 0.20 s** (trim the breath) | hook text **at ≤ 0.3 s** (frame 0 preferred), or a big word-level caption already showing the first word | voice; bed and SFX may enter on the first key word (`sound.md`) |
| 0.0-1.0 s | at most 1 camera or layout move | the topic noun, figure or name **inside the first 8 words** (≈ 2.5 s at 3.2 w/s) | ≤ 6 words, the same idea as the spoken line | |
| ≤ 1.0 s | **first visual change**: a punch-in on the key word, or the figure or name card popping into the headroom | | | optional soft hit on the key word |
| 1.0-2.5 s | if line 1 names an object, person or figure, show it (cutout, B-roll, card) by **2.5 s**; otherwise a second framing step | line 1 ends (≤ 14 words) | captions continue word by word | |
| 2.5-3.0 s | face back for the contrast line | the contrast word ("but / actually") if the context-lean shape is used; the proposition is complete by **3.0 s** (hard cap 6 s) | hook title exits (8 frames) or shrinks to the topic pill | |
| 3.0-6.0 s | face, medium | promise or foreshadow line (≤ 2 sentences, ≤ 3 s total) | for a list: a count chip "1/N" appears | |

---

## 5. Beat structures (storyboards) the director can apply

### 5.1 Roles

Every `shots[].id` in `script.json` gets one role:
- **Required:** `hook`, `payoff`.
- **Optional:** `promise`, `context`, `problem`, `proof`, `example`, `item`, `turn`, `send`, `cta`.

A `turn` is required when the script runs 25 s or more. The roles map one to one onto the house spine: hook, promise, 2-4 beats with micro-payoffs, best payoff in the final 20%, then the loop seam or CTA (`story-script` "Reel or hook test"; `virality.md` §2).

### 5.2 Templates (share of runtime; words at about 3.0 w/s after trimming)

**A. Claim → proof → turn → payoff** (opinion, strategy; 35-50 s)

| beat | position | words (45 s) | edit treatment |
|---|---|---|---|
| hook | 0-7% | ≤ 14 | §4 |
| promise | 7-15% | ≤ 12 | topic pill |
| proof 1 (figure, example) | 15-35% | 25-30 | figure card; B-roll from about 10 s (`editing-pace.md` B rules) |
| proof 2 or the common mistake | 35-55% | 25-30 | B-roll or screen; L2 interrupt at the beat start |
| **turn** ("but...") | 55-70% | 10-15 | L3 interrupt (framing jump plus hit); **400-600 ms pause before the payoff line** |
| payoff | 80-97% | 12-20 | tightest framing; one emphasis word; payoff figure at the largest text size in the video |
| stop | last 0.3-0.5 s | 0 | hard cut; loop seam if ≤ 35 s |

**B. Story → lesson** (Hormozi "Always Be Ready"; 40-55 s)
- Cold open on the odd moment (0-5%).
- Escalation in 2-3 "but / so" steps (5-55%).
- The click or decision is the turn (45-60%).
- The lesson comes as at most 3 numbered rules, one sentence each, starting at **65-75%**.
- The last line ties back to the opening object or person.

**C. Numbered list** (count stated in the hook; best item last)
- **Rapid-fire** (≥ 7 items): **2-4 s per item**, names only, a count chip on every item. Example: Hormozi's 13 books at about 2.7 s per item.
- **Explained** (3-5 items): **8-15 s per item**: name card, then one line of why, then one proof visual. Example: Raj's 4 businesses at about 12 s per item over 58 s.
- Tease the last item in the hook ("the last one costs nothing").

**D. Dilemma → calculation → number reveal** (Warikoo; 30-45 s)
- The hook poses A vs B with figures.
- The body runs the calculation as headroom cards: price, then years, then growth. The face stays in the lower 55%.
- The reveal figure lands at **90-97%**, set in the largest type of the video, with a held face reaction of 0.5-1.0 s and no outro.

**E. Named concept explainer** (Ali Abdaal; 40-60 s)
- Concept name and pain (hook) → one origin or study line → 1-2 everyday examples on B-roll → how to use it (turn) → a one-line takeaway (payoff).

**F. Hot seat or Q&A** (Hormozi "Should I sell my company?", 151 s; Raj guest clips)
- The question or the guest's strongest claim comes first, even if it is later in the source.
- Trim to the single decisive answer.
- For guests, a name super after the hook at 3-6 s (`captions-graphics.md` §8.2).
- Use this only for 2-person content. Reel Director's single-reader case maps to "reads both sides" only if labelled.

**G. One-punch** (15-25 s; Hormozi "Cheat code at 34", 18 s)
- Hook (the claim) → one reason → restated claim (payoff), with a loop seam.

### 5.3 Micro-payoff and connector rules
- **Something new at least every 6-8 s.** A figure, a name, an example or a list item counts. Setup never runs longer than 8 s without a payoff. [rule-of-thumb; aligns with the house "2-4 beats, each with a micro-payoff"]
- **Beats are joined by cause or contrast** (but / so / therefore / which means), not "and then". Lint: at least 1 causal or contrast connector per 2 body beats. Source: Hoyos "but therefore". [consensus]
- **Withhold the answer.** The hook's question or figure is answered only in the payoff beat. Lint: the payoff's key noun or figure must not appear in the body before 80% of runtime. [rule-of-thumb; Hoyos "withhold answers until the end"]

---

## 6. Length vs retention: the rule

- **Default lengths by template** (aligned with `trends-2026.md` T07):
  - G (one-punch): 15-25 s.
  - A, B, D: 35-50 s.
  - C (explained list) and E: 45-58 s.
  - Shorts with any third-party music stay at ≤ 59.5 s.
- **Words, not seconds, set the length.** The director knows the speaker's real rate from the take.
  - Target speech density after silence trim: ≥ 2.8 words/s.
  - Top-creator sample: 3.6-5.3 w/s (Hormozi, n = 5).
  - If the take is under 2.6 w/s, tighten pauses first (`trends-2026.md` T12), then apply pitch-preserving tempo up to ×1.10. Never go over ×1.15. [rule-of-thumb]
- **Script word budget per template** at 3.0 w/s: 15 s ≈ 45 words; 30 s ≈ 90; 45 s ≈ 135; 55 s ≈ 165. Warn when the script exceeds the band by more than 10%. Fail when line 1 is over 14 words.
- **Never pad.** Per-video completion falls fast from 8 s to 30 s and keeps falling to 59 s (Kuaishou, measured), and duration-debiased rankers (D2Q) give no credit for length. If a draft needs more time, add a proof beat. Never slow the read.

---

## 7. Loops, endings and CTAs

- **Why loops pay:**
  - Shorts count a view on every start or replay (since 31 Mar 2025) [measured].
  - Hoyos needs more than 100% retention for Shorts under 30 s [rule-of-thumb].
  - Emplifi: loops of 7 s or less gave +18.7% replay rate [measured, vendor; see `trends-2026.md`].
- **Three script-level seams:**
  1. **Sentence-wrap.** The last line ends on a fragment that reads straight into line 1 ("...and that's exactly why" → "most people never get rich"). Lint: the last 3-6 words plus the first 3-6 words form one grammatical clause (human check, or an LLM check offline).
  2. **Callback.** The payoff reuses at least 1 content word or figure from line 1. Seen in Codie (billion ↔ billionaire), Dan Koe (one hour ↔ a year of hours), Hormozi (build the tower ↔ build it right).
  3. **Answer-loop.** Line 1 is a question; the last line is its answer stated as a fact, so the replay re-asks the question.
- **Picture seam:**
  - The last frame uses frame 0's framing (scale within ±3%, same subject position).
  - Captions are cleared on the final 3-4 frames.
  - No fade to black.
  - The audio bed level at the seam is within 3 dB of the start, with a 120 ms crossfade on audio only (house loop QA, `virality.md` §3).
- **Endings:**
  - Stop ≤ 0.5 s after the last word.
  - No end card or outro on organic posts.
  - Measured in my sample: 9 of 10 top Shorts end on the payoff; the exception is a podcast brand card.
  - The house "quiet hold" end shape (`launch-playbook.md`) is for launch films and explainers, not talking-head reels.
- **CTA:**
  - At most 1, soft, ≤ 8 words.
  - Place it in the body at 60-85%, before the payoff or merged with the send line (`trends-2026.md` T16). Never after the payoff.
  - None of the 6 Hormozi transcripts has a spoken CTA. Motion-pack round 4/5 found no spoken CTA in any tier-A explainer.
  - Links go in the caption, the pinned comment or the platform button (`social-video`).

---

## 8. On-screen text hooks: how they relate to the structure

- **The word-level caption is the default text hook.** 4 of 6 #1 Shorts show the hook words as big captions from frame 0, and none uses a separate headline bar.
- **A separate hook title** (`captions-graphics.md` §8.1: y 300-560, ≤ 7 words, by 0.3 s) is **ON** when any of these hold:
  - a guest or podcast clip;
  - a list (it shows the count);
  - a dilemma (it shows both options);
  - line 1 runs over 10 words, or the topic noun comes after word 8.

  It is **OFF** otherwise. [rule-of-thumb]
- **Hook-title wording:** the same idea as line 1 in different words, 4-6 words. The sample's median title is 6 words. Put the figure or the name first when line 1 contains one.
- **Figures and names get their own card.** A figure or named entity in line 1 gets a card in the headroom (above the head, inside the safe rectangle) within 0.3 s of being spoken. The payoff figure is the largest text in the video (Warikoo). [rule-of-thumb]
- **Hinglish:** Roman script, with 1-2 key words in CAPS for emphasis (Warikoo's titles put CAPS on 2-4 words each), English nouns kept in English, and ₹ written as a symbol with crore or lakh (not 10,000,000). [rule-of-thumb; script choice from `trends-2026.md` §6]

---

## 9. Named creators: what each does (craft, never copy)

- **Alex Hormozi** (4.58M subscribers on YouTube; top Shorts 2-9.5M views)
  - Hook mix: first-person story or confession (27%), withheld referent (23%), warning (19%).
  - Lengths: 18-55 s (median 40 s); hot-seat clips run to 151 s.
  - Delivery: very dense (3.6-5.3 w/s).
  - Frame 0: often a prop or demonstration (the box tower).
  - Ending: the lesson lands at 69-87%, then a hard stop with no CTA.
  - Editing as described by tool vendors (estimates): a jump cut every 1-3 s, word-by-word bold captions with a highlight colour. His latest uploads use stacked two-person split-screen.
  - Structure label: hook → retain → reward per "content unit" (secondary sources).
- **Ali Abdaal** (6.7M; top Shorts 0.5-4.3M)
  - Hook mix: **named concepts** (The Halo Effect, The Stockdale Paradox, The Diderot Effect: 23%) and "N tips in under 60 s" (25%).
  - Lengths: 39-60 s (median 57 s).
  - Frame 0: a prop thrust toward the lens; stock-style B-roll with cutout outlines.
  - Delivery: calm, explanatory. The top Shorts are 2020-23 uploads.
- **Codie Sanchez** (2.26M; top Shorts 1.3-13M)
  - Hook mix: **figures** (42%), celebrity money (Ryan Reynolds, Reese Witherspoon, Rihanna), "how X really makes money" (25%), withheld referents with "spoiler" (29%).
  - Lengths: 43-60 s (median 48 s).
  - Frame 0: her face on the podcast set with a 1-2 word giant condensed-caps caption; celebrity B-roll by 2.5 s.
  - Ending: thesis words on her face, no card.
  - Third-party analyses describe the formula as surprising claim → show the math → concrete steps.
- **Dan Koe** (1.44M on YouTube; much larger on IG and X; top Shorts 0.04-0.33M)
  - Hook mix: **second-person aphorisms** (48%) and negatives (27%), e.g. "You only need one hour", "Most people are mentally overweight".
  - Lengths: 29-167 s (median 59 s).
  - Frame 0: very tight face, cinematic grade, 2-3 word yellow serif captions (on a black bar at the hook).
  - Ending: the line restates the hook's promise (a loop-friendly callback).
- **Ankur Warikoo** (7.15M; top Shorts 7-27M)
  - Hook mix: **questions** (72%), **₹ figures** (53%), **A vs B dilemmas** (38%).
  - Lengths: 29-56 s (median 36 s, the shortest in the sample).
  - Language: Hinglish titles with CAPS emphasis.
  - Frame: medium close-up in the studio; animated cutouts and price tags in the **headroom**; a small caption pill.
  - Ending: a big **number reveal** plus a face reaction, no card.
  - Several top Shorts are street or student Q&A ("coin toss", "which would you choose").
- **Raj Shamani** (19.9M; top Shorts 5-29M)
  - Hook mix: **guest or celebrity clips** (56% named), "Reality of X", lists ("Top 4 profitable businesses in India", 29M).
  - Lengths: 29-60 s (median 52.5 s).
  - Frame: yellow bold 2-line captions low in frame; a logo bug top-left.
  - Ending: the only branded end card seen in the sample (podcast logo plus platform icons), with the voice continuing under it.
- **Tanmay Bhat** (5.5M; comedy and reaction)
  - "Wait for it" delayed payoff in 6 of the top 50 titles. Reaction labels; not an educator format.
- **Jenny Hoyos** (Shorts strategist, primary podcast)
  - Hook visual sketched first, and it must work on mute.
  - Foreshadow of 2 lines (≤ 3 s), then a "but therefore" body, then an abrupt end.
  - About 34 s on YouTube; 10-20 s worked better on TikTok.
  - 5th-grade reading level; ≥ 90% retention to break out.
- **Kallaway** (short-form strategist, secondary summaries)
  - Context lean → scroll-stop interjection → contrarian snapback.
  - 3-5 words of bold on-screen text; value inside about 4 s; staccato short sentences first; "cult hopping" (wrap a niche idea in a famous name).
- **Paddy Galloway and Chris Gileta** (5,400 Shorts, 33 channels, about 2023; secondary)
  - 50-60 s Shorts averaged the most views (1.7M).
  - Average view duration over 50 s gave about 4.1M views vs about 1.8M at 40-50 s. The lesson is AVD, not length alone.

---

## 10. Script lint for `script.json` (machine-checkable, before recording)

Reel Director's schema has `shots[{id, line, cues}]` with word-anchored cues. Proposed checks (FAIL blocks recording; WARN shows a note):

| check | rule | level |
|---|---|---|
| L01 | a shot with role `hook` exists and is first | FAIL |
| L02 | line 1 (the first sentence of the hook) has ≤ 14 words | FAIL over 14; WARN at 12-14 |
| L03 | the first 8 words contain a topic noun, figure or named entity (a content word that is not a pronoun or filler) | WARN |
| L04 | no banned opener in the first 8 words (§3), apart from the credibility-figure exception | FAIL |
| L05 | line 1 stacks two or more devices (figure, name, contrast or negation, "you", withheld referent) | WARN |
| L06 | if the hook is a context lean, a contrast word appears within the first ~18 words (≈ 6 s) | WARN |
| L07 | the hook title (if ON) is 4-6 words and shares ≥ 1 content word with line 1 but is not identical to it | WARN |
| L08 | a `payoff` shot exists, and its estimated start (from word counts) is ≥ 75% of runtime | FAIL if missing; WARN under 75% |
| L09 | runtime ≥ 25 s → a `turn` shot exists at 45-70% | WARN |
| L10 | no shot after `payoff`, except a `loop` fragment of ≤ 6 words | FAIL |
| L11 | at least 1 cause or contrast connector per 2 body shots | WARN |
| L12 | at most 1 `cta`, ≤ 8 words, placed before `payoff` | FAIL |
| L13 | the payoff's key figure or noun is not stated before 80% (withheld answer) | WARN |
| L14 | runtime ≤ 35 s → a loop seam (sentence-wrap, callback or answer-loop) is declared | WARN |
| L15 | total words within ±10% of the template budget at the speaker's measured rate (or 3.0 w/s by default) | WARN |
| L16 | Flesch-Kincaid grade: hook ≤ 6, whole script ≤ 8 | WARN |
| L17 | list scripts state the count in the hook and keep items within ±25% of the same length | WARN |
| L18 | three hook variants exist (`hooks[]`) on an identical body for testing | WARN (only when testing is on) |

Auto-cues the director adds from roles, so the creator writes none:
- **`hook`:** hook title (if ON), a punch-in on the key word by 1.0 s, a headroom card for any figure or name, and the frame-0 prop or cutout when line 1 names a physical noun.
- **`promise`:** topic pill, and the count chip for lists.
- **`turn`:** an L3 interrupt and a 400-600 ms pre-payoff pause.
- **`payoff`:** tightest framing, an emphasis word, and the largest figure card.
- **End:** the loop seam QA, and the hard stop.

---

## 11. Rule table (copy into the director's config)

IDs use the prefix HS so they do not collide with `editing-pace.md` H1-H4 or `trends-2026.md` T01-T22.

| id | rule | number | evidence | confidence |
|---|---|---|---|---|
| HS01 | Speech starts at once; trim the breath and greeting | first content word ≤ 0.20 s | IG skip window 3 s; Meta 1.7 s feed dwell; all 6 Hormozi transcripts start on content at 0:00 | consensus |
| HS02 | Line 1 is short and front-loaded | ≤ 14 words; topic noun, figure or name inside the first 8 words | top-title median 6 words (n = 287); Hormozi line 1 is 7-17 words; TikTok: 63% of top-CTR ads deliver the message by 3 s | rule-of-thumb (sample-measured) |
| HS03 | Banned openers | 0 greetings, self-intros or agendas in the first 8 words (credibility-figure exception ≤ 7 words) | TikTok 3 s message; Hoyos; the lead-in-cut anecdote (unverified) | consensus |
| HS04 | Proposition complete early | ≤ 3.0 s (hard cap 6 s) | TikTok ads help; IG skip window (= T03) | consensus |
| HS05 | Stack hook devices | ≥ 2 of {figure, named entity, contrast or negation, "you", withheld referent} in line 1 | 53% of 287 top titles (Warikoo 83%, Codie 69%); no within-creator lift measured | rule-of-thumb |
| HS06 | Context → contrast → snapback | contrast word inside 6 s when line 1 is context | Kallaway (secondary); Codie 13M-view Short has "but... actually" at about 2.5 s | consensus |
| HS07 | Object-first visual when the script names one | prop, cutout or B-roll of the named object, person or figure by 1.0-2.5 s; else a punch-in by 1.0 s | 4 of 6 #1 Shorts; `editing-pace.md` H2 | rule-of-thumb |
| HS08 | Hook text | by 0.3 s, 4-6 words (cap 7), same idea in different words | title median 6 words; Kallaway 3-5 words; house virality §1 | consensus |
| HS09 | Hook title only when needed | ON for guest, list, dilemma, or line 1 over 10 words; else the word caption is the hook | 0 of 6 #1 Shorts use a headline bar | rule-of-thumb |
| HS10 | Plain language | FK grade ≤ 6 in the hook, ≤ 8 overall; first 10 s sentences ≤ 14 words | Hoyos 5th-grade rule (primary); Kallaway staccato start | rule-of-thumb |
| HS11 | Role every shot | required hook and payoff; turn required at ≥ 25 s | story-script spine; Hoyos; Hormozi hook-retain-reward | consensus |
| HS12 | Foreshadow after the hook | ≤ 2 sentences, ≤ 3 s, ending by about 8 s; promises the end without giving it | Hoyos (primary); house retention structure 3-6 s | consensus |
| HS13 | Turn placement and staging | 45-70% of runtime, opened by a contrast word; L3 interrupt plus a 400-600 ms pre-payoff pause | Hormozi turns at about 42-70%; story-script 30 s beat sheet 60-73%; T12 | rule-of-thumb |
| HS14 | Payoff late | best line starts at 80-95% (never under 70%) | inspected payoff starts: 69%, 87%, 96%, 97%, 97%; house "final 20%" | measured (n = 5) + consensus |
| HS15 | Hard stop | ≤ 0.5 s of picture after the last word; no end card or outro on organic posts | 9 of 10 top Shorts end on the payoff; Hoyos last-second trim 83→88% | measured (small sample) + rule-of-thumb |
| HS16 | Micro-payoff cadence | new information (figure, name, example, item) every ≤ 6-8 s | house 2-4 beats with micro-payoffs; Hoyos "each beat changes the situation" | rule-of-thumb |
| HS17 | Causal connectors | ≥ 1 but/so/therefore per 2 body beats | Hoyos "but therefore" | consensus |
| HS18 | Withhold the answer | the payoff figure or noun is not stated before 80% | Hoyos (withholds answers); Warikoo's number reveal at 96% | rule-of-thumb |
| HS19 | List pacing | count in the hook; rapid-fire 2-4 s per item (≥ 7 items); explained 8-15 s per item (3-5 items); best item last | Hormozi 13 books ≈ 2.7 s per item; Raj 4 items ≈ 12 s each; trends 4.4 | rule-of-thumb |
| HS20 | Dilemma format | A vs B with figures in the hook; calculation as headroom cards; reveal at 90-97% with a 0.5-1.0 s face hold | Warikoo top-47: 38% A vs B, 72% questions, 53% figures; #1 Short 27M | measured (descriptive) |
| HS21 | Story format | cold open mid-action; ≤ 3 one-sentence rules from 65-75%; last line ties to the opening object | Hormozi "Always Be Ready" (8.7M) | rule-of-thumb |
| HS22 | Length by template | one-punch 15-25 s; claim, story or dilemma 35-50 s; explained list or concept 45-58 s | top-Short sample median 46.5 s, 52% at 45-60 s (n = 54); Socialinsider 45-60 s peak; Galloway 50-60 s | measured |
| HS23 | Never pad | words = seconds × speaker rate; add a proof beat rather than slow down | Kuaishou median completion ≈ 50% (8 s) → 33% (20-30 s) → 25% (41-59 s); D2Q duration-debiasing | measured (research) |
| HS24 | Speech density | ≥ 2.8 w/s after trim; tempo ≤ ×1.10 only if under 2.6 w/s | Hormozi 3.6-5.3 w/s (n = 5) | rule-of-thumb |
| HS25 | Loop seam | ≤ 35 s reels and the 7-12 s cutdown: last line wraps into or calls back to line 1; last-frame framing = frame 0 (±3% scale); no fade; bed within 3 dB | Shorts replays count (31 Mar 2025); Hoyos > 100% retention under 30 s; Emplifi +18.7% replay | consensus |
| HS26 | Callback | the payoff reuses ≥ 1 content word or figure from line 1 | Codie, Dan Koe, Hormozi #1 Shorts | rule-of-thumb |
| HS27 | Figure and name cards | any figure or name in line 1 gets a headroom card within 0.3 s of being spoken; the payoff figure is the largest text | Warikoo (₹ price at 2.5 s, reveal at the end); Codie celebrity B-roll by 2.5 s | rule-of-thumb |
| HS28 | CTA discipline | ≤ 1 soft CTA, ≤ 8 words, at 60-85%, never after the payoff | 0 of 6 Hormozi transcripts have a spoken CTA; motion-pack round 4/5: no spoken CTA in tier-A explainers; T16 | consensus |
| HS29 | Hook testing | 3 variants that change only line 1, the hook text and the frame-0 visual; identical body; Trial Reels; keep the lowest skip rate | house measure loop; Hoyos tests several hooks per idea; Mosseri Trial Reels | consensus |
| HS30 | Hook family per format | finance or comparison → question or dilemma; business case → figure plus name; mindset → second-person claim; psychology → named concept; lesson → story cold open; clip → guest claim plus list | per-creator mix (§2.2) | rule-of-thumb |
| HS31 | Hinglish hooks | Roman script; CAPS on 1-2 key words; English nouns kept; ₹ with crore or lakh | Warikoo titles (CAPS on 2-4 words each); IIT Delhi Hinglish data via trends §6 | rule-of-thumb |
| HS32 | Delayed-payoff promise (comedy) | an explicit "wait for it" style tease only for reaction or comedy; educators use "the last one..." instead | Tanmay Bhat 6 of top 50 titles | rule-of-thumb |

---

## 12. Conflicts, gaps and what to verify next

- **Length:** the house `platforms.md` says Reels and Shorts run 15-35 s. My sample and the 2026 data say 35-55 s for script-led talking heads. Same resolution as `trends-2026.md` §2: keep 15-35 s for music-led pieces and ads.
- **Hook text timing:** `trends-2026.md` T02 says frame 0, while `editing-pace.md` H3 and `captions-graphics.md` say by 0.3 s. Both are compatible. Frame 0 is preferred; 0.3 s is the lint limit.
- **Speech rate:** `trends-2026.md` T11 budgets 2.7 w/s, while top creators measured 3.6-5.3 w/s. Use the speaker's own measured rate, warn under 2.6, and never force it above about 3.5 with tempo.
- **Not verified this pass (search budget exhausted):**
  - Hormozi's own wording for hook types in *$100M Leads*.
  - Ali Abdaal's and Dan Koe's own statements on reel structure.
  - The Teixeira, Wedel and Pieters zapping and branding studies. From memory, they show that early, prominent branding increases skipping; this needs re-checking before it is cited.
  - TikTok newsroom "How TikTok recommends videos" (HTTP 503).
  - The Emplifi and Meta-Toluna figures, which are cited second-hand from `trends-2026.md`.
- **Next tests worth running on Reel Director's own posts:**
  - Hook stacking (one device vs two or more) on an identical body.
  - Headline bar ON vs OFF.
  - Loop seam vs a hard ending on 25-35 s reels.
  - Each test runs 3 + 3 posts, read on IG skip rate and YT viewed rate at 72 h.

---

## 13. Sources

**Platforms and data**
- Instagram skip rate and retention chart (25 Aug 2025): https://www.socialsamosa.com/news-2/instagram-retention-chart-skip-rate-new-performance-metrics-reels-9730992 ; explainer https://metricool.com/instagram-reel-analytics/
- Socialinsider Reels length (about 6M Reels, H1 2026): https://socialinsider.io/blog/instagram-reels-length/
- TikTok for Business "9 Creative Tips" PDF: https://ads.tiktok.com/business/library/Auction_Ads_Creative_Tips.pdf
- Facebook IQ, "Capturing Attention in Feed" (20 Apr 2016): https://www.facebook.com/business/news/insights/capturing-attention-feed-video-creative
- Quan et al., Alleviating Video-Length Effect (Kuaishou and WeChat completion vs length): https://arxiv.org/abs/2308.14276
- Zhan et al., D2Q duration debiasing (KDD 2022): https://arxiv.org/abs/2206.06003
- YouTube "viewed vs swiped away" (third-party glossary): https://www.creatoressentials.com/glossary/viewed-vs-swiped-away/

**Creators and strategists**
- Jenny Hoyos on Creator Science (primary interview): https://creatorscience.com/podcast/jenny-hoyos/
- Kallaway hook framework (secondary summaries): https://youtubesummary.com/summary/LmXpbP7dD48 ; https://opentools.ai/youtube-summary/how-to-create-irresistible-hooks-and-blow-up-your-content
- Paddy Galloway and Chris Gileta Shorts study (secondary): https://videogen.io/blog/decoding-the-youtube-shorts-algorithm-a-deep-dive-into-3-3-billion-views
- Hormozi "content unit" hook-retain-reward (secondary): https://www.skool.com/acceleratoruniversity/what-three-parts-make-up-an-effective-content-unit ; lead-in anecdote (unverified): https://www.skool.com/lead-gen-mastery-4994/why-your-content-fails-in-the-first-3-seconds-and-how-to-fix-it
- Hormozi editing style (vendor estimates): https://www.choppity.com/tools/recreate-video-editing-style/alex-hormozi/
- Codie Sanchez analyses (third-party): https://outlierkit.com/channel/codiesanchezct ; https://castmagic.io/creators/codie-sanchez
- Channels read (Popular sort, 20 Oct 2026): https://www.youtube.com/@AlexHormozi/shorts ; https://www.youtube.com/@aliabdaal/shorts ; https://www.youtube.com/@codiesanchezct/shorts ; https://www.youtube.com/@DanKoeTalks/shorts ; https://www.youtube.com/@warikoo/shorts ; https://www.youtube.com/@RajShamani/shorts ; https://www.youtube.com/@tanmaybhat/shorts

**Local references**
- motion-pack `skills/motion-pack/references/{virality,success-patterns,critic,platforms}.md`
- motion-pack `skills/story-script/SKILL.md` and `references/formats.md`
- motion-pack `skills/social-video/references/measure.md`
- other agent skills: `hook-generator`, `reels-scripting`
- motion-pack `docs/research/edit.md` §3, §7.2
- Sibling notes: `trends-2026.md`, `editing-pace.md`, `captions-graphics.md`, `sound.md`

**Raw working files (counts only, no media)**
- `raw/titles.txt` (287 titles with view counts)
- `raw/classify.py` (device tagger)
- `raw/js.txt` (the transcript-count snippet used on 6 pages)
