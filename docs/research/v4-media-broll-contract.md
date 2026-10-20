# v4 contract — real media B-roll engine (images, short clips, Claude clips, Veo, Higgsfield) (2026-10-20)

Scope (the maintainer's decision): implement ALL of: free stock sites (Pexels stopped issuing keys → use others),
YouTube Creative Commons (CC) videos, Claude-created clips, Google Veo on Vertex AI (through an authenticated gcloud
CLI and the user's own Google Cloud project), Higgsfield (through its developer API). Day-to-day sources will be:
free clips, YouTube CC, and Veo.

Built on 5b97205 (533 tests; e2e 315/315). A parallel workflow was building packs in src/reel_director/packs/ —
do NOT touch packs/ (the packs are not part of this release). The creator's real takes: the git-ignored work/real-1
(kept unchanged).
v2/v3 rules (faces sacred, gates, before/after, council caps) stay binding: docs/research/v2-real-footage-contract.md,
docs/research/council/decisions.md.

## Package: src/reel_director/media/
- providers/: openverse (CC images, no key), wikimedia (Commons images+video, no key), archive (Internet Archive PD/CC
  video, no key), nasa (images+video, PD, no key), pixabay / unsplash / coverr (built, inactive until a key is set via
  env/settings), youtube_cc, veo, higgsfield, claude_clip, library (user media folder), webcapture (`hyperframes capture`
  of a user-supplied URL).
- Common interface: search(query, kind: image|video, min_short_side=1080, duration=(2,10), orientation) ->
  [Candidate{id, provider, kind, title, url, thumb, w, h, duration, license, attribution, source_page, cost_usd}];
  fetch(candidate) -> local file in the cache. Paid providers return cost estimates and NEVER spend without approval.
- license.py: normalize licenses; allow commercial-safe only (CC0, PDM, PD, CC-BY; CC-BY-SA flagged share-alike;
  reject NC/ND); attribution strings; per-reel credits list written to renders/<reel>.credits.txt and shown in Studio.
- cache.py: content-addressed media cache on an external drive when one is mounted (fallback
  ~/.cache/reel-director/media); metadata sidecar JSON; LRU size cap.
- select.py: rank candidates by relevance (metadata text match + optional Claude vision rerank of thumbnails via
  `claude -p`), technical quality (resolution, bitrate, aspect, motion), license; pick best segment for clips
  (scene-detect, avoid text/watermarks/faces of other people where possible); normalize to the reel (crop/pad treatment,
  CFR 30, colour-matched to the preset grade).

## YouTube (ToS!)
- Discovery: YouTube Data API v3 search with `videoLicense=creativeCommon` (+ relevance, duration short/medium) using
  credentials from the user's own Google Cloud project. Check what exists READ-ONLY
  (`gcloud services list --enabled`, `gcloud services api-keys list`); do NOT create keys, enable APIs or change IAM —
  if something is missing, report the exact command the user must run.
- Download: YouTube's ToS forbid downloading except via YouTube's own features, even for CC videos. Implement the yt-dlp
  fetch as an OPT-IN local setting (`media.youtube_download: false` default), CC-BY only, with the ToS warning shown in
  Studio and CLI, attribution auto-added. Tests use mocks; at most ONE real CC-BY download for proof, clearly logged.

## Veo (Vertex AI, the user's Google Cloud project) and Higgsfield
- Implement clients (Veo: Vertex AI generateVideos / predictLongRunning for the current Veo model available in the
  project; Higgsfield: its developer API), cost estimators, polling, download, normalize. Prove AUTH and MODEL
  AVAILABILITY with free calls only (list/get models, permission checks). Do NOT run any paid generation — the
  maintainer approves the first paid clip. Studio must show the estimate and require approval per clip,
  with a per-reel cap (default $5) and a global daily cap ($20).

## Claude-created clips (free, subscription)
- claude_clip provider: `claude -p` (installed CLI) writes a seek-safe HyperFrames composition for a B-roll brief
  (e.g. "rocket launching", "money stack growing", "clock ticking fast") using motion-pack
  (https://github.com/ANVEAI/motion-pack: objects/ three.js, physics/, layers/, type/gfx, transitions) and Reel Director
  fonts; render 2–4 s at 1080x1920 (and 1080x1080 for pip); validate with `hyperframes lint` + a frame check; retry ≤2
  with the error fed back. Cache by brief hash.

## Treatments (reel runtime) + director
- Treatments: full-bleed with grade match, Ken Burns (eased, seeded), 2.5D parallax (Vision foreground mask of the
  image → subject layer over background layer), cutout "sticker pop" with outline + shadow, device mockups
  (phone/laptop/browser), polaroid/stack, split (B-roll top, face bottom — face-crop vars) and pip (face circle over
  B-roll), masked reveals (wipe/circle/text mask), picture-in-picture of clips with rounded corners; seek-safe.
- Director: B-roll on concrete nouns/claims (case-study recipes: 25–40% for real inserts — real media now counts;
  inserts 1.2–3 s; never over the payoff; ≤ 1 paid clip per reel by default), emits `broll` cues kind "media" with
  {query, kind, providers order, treatment, layout}; resolution step (plan time) picks + fetches media, writes
  media.json (chosen + alternates + credits) BEFORE render; Studio "B-roll" panel lets the creator swap/approve/reject
  each pick, see licenses, and approve paid generations with cost.

## Quality bar
Every provider: unit tests with recorded fixtures (no network in unit tests); one live smoke test per free provider
(small thumbnail download only) recorded in the report. Render proof on the creator's real reel with real media
B-roll from free sources + Claude clips (no paid gen). Faces sacred; captions above B-roll; deterministic given the
same media.json; files < 500 lines; no git state changes; no rm -rf; never touch the camera/mic.
