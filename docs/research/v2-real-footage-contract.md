# v2 "real footage" contract — face-aware, richer visuals, QA + editing director (2026-10-20)

Built on 4fe77c9 (374 unit tests, e2e 315/315). venv .venv/bin/python.
The first real-footage test (FaceTime HD 1080x1920 native, MacBook mic) lives in the git-ignored work/real-1 and is kept
unchanged; experiments copy its takes to work/real-1-v2/ (or read them in place). Its build: renders/reel-master.mp4.

## Problems found on real footage (all must be fixed and proven on work/real-1 takes)
P1 Captions sit across the face in every frame (caption band fixed at y≈1110; founder's eyes at ~0.50 H, mouth ~0.58 H).
P2 Punch-ins scale around a fixed 0.38 H point, not the face.
P3 Pace gate failed (CV 0.20 "metronomic" < 0.25) but the build shipped with only a log note — gates must fix or fail.
P4 B-roll card is a flat black screen with white text — reads cheap.
P5 Title box (semi-transparent grey) is hard to read over a busy wall poster.
P6 Busy background (word-cloud wall poster) competes with the face.
P7 QA misread message is confusing ('heard "pass the" for "pressed"' when the creator said "pressed the record").

## Data contracts
- Face track per take (from VISION): `qa/<take>.face.json` =
  {"version":1,"take":"hook-1","w":1080,"h":1920,"fps":30,"step":3,
   "frames":[{"t":0.0,"box":[x,y,w,h],"eyes":[[lx,ly],[rx,ry]],"mouth":[mx,my],"chin_y":...,"conf":0.98}|null...],
   "summary":{"eye_y_med":0.50,"face_h_med":0.27,"center_x_med":0.52,"present":0.99,"stable":true}}
  Pixel coords of the NORMALIZED take (raw/<take>.mp4). Smoothed (no jitter). Backend: Apple Vision via pyobjc
  (VNDetectFaceLandmarksRequest) on macOS; interface allows a mediapipe backend later (SaaS/Linux). No torch import.
- Subject matte per take (optional, VISION): `prepped/<take>.matte.webm` (alpha) via `hyperframes remove-background`
  (or Apple Vision VNGeneratePersonSegmentationRequest) — only if it measurably improves the frame and renders < 2x slower.
- Layout (LAYOUT → QA/VISUALS): compiler writes `reel/layout.json` =
  {"captions":[{"chunk_id","t0","t1","box":[x,y,w,h],"zone":"below-chin|above-head|lower-band"}], "title":{...},
   "cards":[...], "reframe":[{"clip","scale","tx","ty"}], "face_reel":[{"t","box"}]} in REEL coordinates (1080x1920).
- QA report (QA): `qa/report.json` = {"gates":[{"id","level":"ok|warn|fail","value","target","message","fix"}],
   "before_after":"renders/before-after.png","director":{...}|null,"score":0-100,"verdict":"ship|fix|block"}.

## Rules
- Faces are sacred: no caption/title/card/sticker box may overlap the padded face box (eyes+nose+mouth, pad 6% of face h)
  at any frame, except full-screen B-roll cards (face hidden by design). Measure on layout.json AND verify on rendered
  frames by detecting the face in the output and intersecting with layout boxes.
- Caption zone choice per shot (stable within a shot; may change only at a cut/punch): prefer below-chin inside the safe
  rect (y ≤ 1248 bottom); else above-head (between title band and forehead); else lower-band with the face reframed up.
- Auto-reframe per take: place the eye line at 0.40 H ± 0.03 via translate + scale ≤ resolution cap (1.10 for 1080-wide);
  never show edges/black; keep headroom ≥ 4% H.
- Punches scale around the eye midpoint (from the face track), clamped so the frame stays filled.
- Title legibility: measure background busyness (edge density + luma variance) behind the title box on the take frames;
  busy → solid/opaque accent box or blurred backdrop (backdrop-filter) with WCAG ≥ 4.5:1; calm → current style.
- Pace gate is enforced: if CV < 0.25 or median gap outside preset range, the policy re-plans (vary punch spacing/levels)
  before compile; a remaining failure blocks "great" and is shown in the Studio.
- B-roll visuals must look designed: animated backgrounds (gradient mesh / grid / blur-of-the-take), kinetic type
  entrance, icons (MIT/ISC icon sets via npm: Lucide/Phosphor/Tabler — vendored SVG subset + license), stat counters with
  ring/bar, list builds, and face-aware split/pip layouts (face crop from the face track). One accent, max 2 type families.
- Look: subtle grade per preset (contrast/saturation/warmth) + optional background treatment using the matte (blur 8–14 px
  and/or −15–25% exposure on the background only). Skin must not shift hue (ΔE on skin patch ≤ 3).
- Determinism and seek-safety unchanged; files < 500 lines; unit tests green; never touch the real camera/mic; no rm -rf;
  no git state changes (integrator commits nothing; the main session commits).

## Editing director (QA team)
- `before_after.py`: raw take frame vs edited frame at the same media moments (6–8 pairs) + audio before/after numbers
  (raw LUFS/SNR → master) → renders/before-after.png + .json.
- `review.py`: optional `--director` step runs `claude -p` (installed CLI 2.1.278, user's subscription) headless with the
  before/after sheet + contact sheet + layout/QA JSON, a strict rubric, and a JSON schema for output
  {"score","issues":[{"severity","what","where_t","fix":{"op":"move_caption|drop_cue|change_preset_param|reframe|retake","args"}}]}.
  Pipeline applies only whitelisted ops, re-compiles/re-renders, max 2 rounds, stops when score doesn't improve.
  Must degrade gracefully (no CLI / timeout → skipped with a note). Never sends anything except local files to the CLI.
- Deterministic gates run always; the director review is opt-in flag + Studio toggle.

## Learn (LEARN team)
- `learn.py creator <project>`: creator profile from takes (eye line, face size, light level/temperature, voice LUFS/SNR,
  speech rate) → `creator.json`; Studio framing coach uses it ("raise camera ~5 cm / sit back").
- `learn.py reference <video files the user supplies>`: shot boundaries (scene detect), cut rate, caption region estimate,
  speech rate, music/voice levels, loudness → `style-ref.json` that can seed a preset override. Never downloads videos.
