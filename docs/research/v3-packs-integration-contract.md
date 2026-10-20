# v3 contract — packs + creator case studies into the product (2026-10-20)

Built on 7531ad9 (533 unit tests, e2e 315/315) plus a work-in-progress src/reel_director/packs/ (looks/, backgrounds/,
overlays/, motion/, styles/, catalog.json, README.md; 15 style packs with a lookbook in renders/lookbook/). The packs
are not part of this release (see the README's Roadmap). Real takes: the git-ignored work/real-1 (kept unchanged) and
the v2 build tooling in work/v2-final/tools (build.sh <preset>) and work/real-1-v2 (prepped takes, face tracks).
Council rules: docs/research/council/decisions.md. v2 contract: docs/research/v2-real-footage-contract.md
(faces sacred, gates, before/after, director review) — all v2 rules stay binding.

Knowledge to apply (creator case-study notes kept outside this repository; read the relevant parts):
- hooks and scripting — 6 storyboard templates (T1-T6) + selector
- editing and pacing — 6 edit recipes mapped onto presets
- sound and music — 6 sound kits (JSON, pack ids verified)
- captions and visuals — 8 style specs; rules — safe zones, anti-patterns
- platform trends — formats to support next (screenshot backgrounds, screen recording first)

## Goals
G1 Every pack style is a selectable preset end to end (director → layout → compile → mix → render → QA): LUT applied
   to the takes (ffmpeg lut3d at prep, cached per take+lut+intensity, skin guard), palette, fonts, caption family,
   background for cards/title band, overlays (grain/vignette etc.), text animations, callouts, transition tier, SFX kit,
   music mood, pace recipe, B-roll card style. Existing 6 presets map onto or are replaced by the pack styles
   (keep their ids working as aliases).
G2 Auto-director uses the storyboard templates (T1-T6 + selector) and the edit recipes; sound kits drive SFX/bed.
G3 Studio: style picker with lookbook thumbnails, live preview via "Preview edit"; style chosen per project.
G4 Matte: Vision bottom-strip temporal hold for hand/forearm dropouts (runs ≤ 4 frames; no ghosting on entering
   limbs) — measured before/after on hook-1, turn-2, cta-1 (dropout frames from docs: turn-2 41,43,46-48,127,130,
   161-162,185-188,191; cta-1 60,61,64,91,121,122,139,166,168,169).
G5 The creator's real reel (work/real-1) re-rendered in the 4 best-fitting styles for its niche (business /
   creator tools): operator-bold, clean-explainer, finance-pro or cinematic-doc, desi-hinglish — with before/after
   + QA; all gates pass.
G6 Quality: unit tests green, e2e 315/315, deterministic builds, seek-safe runtime, files < 500 lines, faces sacred.

## Ownership (file-disjoint)
- TEAM STYLES-ENGINE: presets.py, director.py, lexicon.py, policy.py, pace.py, new storyboard.py, tests.
- TEAM LOOK-RENDER: compiler.py, layout.py, capplan.py, web/reel.mjs, web/reel.css, stage.py (stage pack modules),
  new lut.py (prep-time LUT bake with cache), tests.
- TEAM SOUND-KITS: mixdown.py, audio.py, tests.
- TEAM MATTE+STUDIO: matte.py, studio/static/* (style picker + lookbook thumbs), studio/server.py+runtime.py (style
  endpoint), tests.
- INTEGRATOR: pipeline.py, __main__.py, packs/* fixes, e2e, real reel renders, report.
Never touch work/real-1; no git state changes; no rm -rf; never use the real camera/mic; stop processes you start.
