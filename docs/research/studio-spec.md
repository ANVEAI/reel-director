# Reel Director Studio — spec and API contract (Week 3)

Existing pipeline (read these first): src/reel_director/{schema,timing,cleanup,timeline,compiler,audio,media,__main__}.py,
tests/, examples/demo/script.json, scripts/make_demo_media.py. Commits so far: Week 0–2.

## Goal
A local "studio" the creator opens in their browser. It uses any connected camera (built-in FaceTime HD,
iPhone via Continuity Camera, USB cameras) and microphone, shows each shot's line as a teleprompter,
records takes, checks each take's quality immediately (technical + did they read the script), and with one
button runs the full pipeline (prep → compile → HyperFrames render → master) and plays the finished reel.
Highest possible quality is the priority. No new heavy dependencies; stdlib HTTP server, plain HTML/JS/CSS
(no build step, no frameworks).

## Device facts (measured on the development Mac; device names are examples)
- Chrome 155 at /Applications/Google Chrome.app. Safari also present. Studio must work in Chrome; Safari best-effort.
- Video devices (AVFoundation): "FaceTime HD Camera" — native modes 1920x1080, 1280x720, **1080x1920 (portrait)**,
  1760x1328, 1328x1760, 1552x1552, 640x480 @ up to 30 fps. "<Name>’s iPhone Camera" (Continuity Camera) —
  landscape modes only: 1920x1440, 1920x1080, 1280x720, 640x480 @ 30/60 fps. "<Name>’s iPhone Desk View Camera" — must be
  hidden (not a face camera). Note the curly apostrophe in labels.
- Audio inputs: virtual devices such as ZoomAudioDevice, BlackHole 2ch, Microsoft Teams Audio, LoomAudioDevice (all VIRTUAL — never default to them,
  warn loudly if chosen), MacBook Pro Microphone (real), <Name>’s iPhone Microphone (real), AirPods Pro (Bluetooth: low-band
  HFP when mic is active — warn "low quality").
- ffmpeg 8.0.1 has astats, ebur128, signalstats, blurdetect filters. Keep files lean: never store uncompressed video.
- mlx-whisper must run in a process that has NOT imported torch (torch first = silent crash). Silero VAD imports torch.
  Therefore heavy steps run as subprocesses (`python -m reel_director ...`), never in the server process.

## Capture rules (quality-critical)
- getUserMedia video: `deviceId: {exact}`, `resizeMode: "none"` (native camera formats only, no browser rescale),
  frameRate ideal 30. Try portrait first `{width:{ideal:1080}, height:{ideal:1920}}`; read `track.getSettings()`;
  then try landscape max `{width:{ideal:3840}, height:{ideal:2160}}`; keep whichever gives the larger
  **effective 9:16 area** (= the largest 9:16 rectangle inside the frame). Show the result: native WxH, fps, effective
  9:16 WxH, and a verdict: >=1080 wide "Full HD 9:16", 720–1079 "OK — upscaled", <720 "Low".
- getUserMedia audio: `deviceId: {exact}`, `echoCancellation:false, noiseSuppression:false, autoGainControl:false`,
  `sampleRate: {ideal: 48000}`, `channelCount: {ideal: 1}`. (Teleprompter has no far-end audio; browser processing hurts voice.)
- Default device choice: video = highest effective 9:16 area, tie → iPhone; never "Desk View". Audio = first real
  external/USB mic, else the mic of the chosen iPhone camera if iPhone selected, else "MacBook Pro Microphone"; never a
  virtual device by default (names matching /BlackHole|Zoom|Teams|Loom|Aggregate|Multi-Output|Virtual|Soundflower/i).
- MediaRecorder mime preference: `video/mp4;codecs=avc1.640033,mp4a.40.2`, `video/mp4;codecs=avc1,mp4a.40.2`,
  `video/mp4`, `video/webm;codecs=h264,opus`, `video/webm;codecs=vp9,opus`, `video/webm`. videoBitsPerSecond =
  clamp(W*H*fps*0.30, 8e6, 40e6); audioBitsPerSecond 256000; `start(1000)` timeslice.
- Preview may be mirrored for front cameras; the recording is never mirrored.
- Server normalizes every upload: constant frame rate (round source fps to 24/25/30/60, default 30), H.264 High
  `-crf 14 -preset medium -pix_fmt yuv420p`, audio mono 48 kHz AAC 256k with `aresample=async=1` (fix drift),
  `+faststart`. Original upload kept as raw/orig/<name>.<ext> (it is small; needed for forensics).
- Also support **Import**: uploading an existing file (e.g. native iPhone 4K portrait recording) to a shot goes through the
  same normalization + QA. Normalization must apply rotation metadata (iPhone files) — ffmpeg autorotate does this when
  re-encoding.

## Project layout
`python -m reel_director studio SCRIPT --project DIR [--port 8765] [--no-open]`
- DIR/project.json  {"script": "<absolute path to script.json>"}  (created on first run; script media paths stay relative
  to the script's own folder, so never copy the script)
- DIR/raw/<shot>-<n>.mp4 normalized takes, DIR/raw/orig/<shot>-<n>.<ext> originals, n = 1,2,3… never reused
- DIR/qa/<shot>-<n>.json take QA report (schema below)
- DIR/takes.json  {"<shot>": [{"src": "raw/hook-1.mp4", "pin": false}, ...]}   ← input to `prep`
- DIR/prepped/, DIR/reel/, DIR/renders/reel.mp4, DIR/renders/reel-master.mp4, DIR/build.log
- Discarded takes are removed from takes.json and moved to DIR/raw/discarded/ (never hard-deleted).

## Pipeline change: pinned takes
takes.json entries may carry `"pin": true`. prep must carry `pin` into prepped/takes.json; load_takes/Take must carry it;
timeline.pick_take must use the pinned take if one exists (still score all for the report). Unit-test it.

## Take QA (module src/reel_director/takecheck.py, CLI `python -m reel_director check-take MEDIA --script SCRIPT --shot ID --out QA.json`)
Runs in a subprocess (mlx only, NO torch import). Report JSON:
{
 "take": "hook-2", "shot": "hook", "created": <unix seconds>,
 "video": {"width","height","fps","duration","effective_9x16": [w,h], "luma_mean": 0-255, "luma_p5", "luma_p95",
           "blur": <blurdetect mean>, "vfr_source": bool},
 "audio": {"sample_rate","peak_dbfs","clipped_samples","lufs","noise_floor_db","snr_db"},
 "script": {"coverage": 0-1, "misread": [{"expected","heard"}], "missing": [words], "junk": [words],
            "kept_seconds", "cuts", "score"},
 "checks": [{"id","level": "ok"|"warn"|"fail","message"}],   // human-readable, actionable ("Too dark: add light in front of you")
 "verdict": "great"|"ok"|"retake"
}
Thresholds (tune if evidence says otherwise, document in code): fail if coverage < 0.85 or any misread, peak >= -0.3 dBFS with
clipped_samples > 10 (clipping), lufs < -40 (silent/wrong mic), snr < 15 dB; warn if snr < 25, luma_mean < 60 or > 200,
effective 9:16 width < 1080, blur high, fps < 24, duration > 3x estimated read. Verdict: any fail → retake; any warn → ok; else great.
Script check reuses timing.align + cleanup.keep_segments + cleanup.score_take on the transcript (mlx-whisper large-v3-turbo via
the existing `transcribe` helper). Write words to qa/<take>.words.json for reuse.

## HTTP API (stdlib ThreadingHTTPServer; bind 127.0.0.1 ONLY; JSON everywhere)
- GET  /                      → studio page; GET /static/<file> → studio assets (src/reel_director/studio/static/)
- GET  /api/project           → {"title","width","height","fps", "shots":[{"id","line","estimate_s","cues":[{"type","at_words":"three hours","text"?}],
                                  "takes":[{"name","src","pin","qa": <report or null while pending>,"status":"checking"|"ready"|"error"}],
                                  "best": "<take name or null>"}], "build": <build status>}
- POST /api/takes?shot=<id>&source=record|import&ext=mp4|webm|mov   body = raw bytes; headers X-Capture-Info: JSON (device labels,
                                  track settings, mime, bitrate). → 201 {"name": "hook-3"} immediately; normalization + QA run in a
                                  background worker; status visible via /api/project. Reject unknown shot ids and any ext outside the list (400).
                                  Shot ids are validated against the script — never used raw in paths without validation.
- POST /api/takes/<name>/pin      → pin this take (unpins others of the shot); POST /api/takes/<name>/unpin
- POST /api/takes/<name>/discard  → move to raw/discarded, drop from takes.json
- GET  /media/<path under DIR>    → serve take/render files with HTTP Range support (video seeking); path traversal impossible.
- POST /api/build                 → start prep→compile→render→master in a background thread (409 if running or any take still checking)
- GET  /api/build                 → {"state":"idle"|"running"|"done"|"error","step":"prep"|"compile"|"render"|"master","log":[last 40 lines],
                                     "result":{"video":"/media/renders/reel-master.mp4","duration","lufs","true_peak","shots":[{"id","take","cuts"}]}}
Every subprocess uses sys.executable -m reel_director …; render uses `hyperframes render <reel dir> -o <renders/reel.mp4>`.

## Studio UI (src/reel_director/studio/static/index.html, studio.js, studio.css)
Layout for a laptop screen, dark theme:
- **Top center (closest to the webcam): the teleprompter** — current shot's full line, very large (≥ 44px, max ~2 lines,
  auto-fit), high contrast, so the creator's eyes stay near the lens. Below it a thin row with cues for this shot
  ("'three hours' → overlay 3 HRS / REEL") in small muted text.
- Center: live camera preview with a 9:16 frame guide (dim outside the crop when the camera is landscape), headroom/eyeline
  guide line at ~1/3 from top, and the reel UI safe zone (bottom ~20% and right ~12% where Instagram/TikTok UI covers) shaded.
- Live meters: audio level meter with peak hold and red clip warning; room-noise readout measured while idle; exposure
  readout (mean luma sampled from a small canvas every 500 ms) with "too dark/too bright" hints; badges for native
  resolution, fps, effective 9:16 resolution + verdict.
- Optional face-framing hint via MediaPipe Tasks Vision FaceDetector loaded from cdn.jsdelivr.net (exact pinned version);
  if it fails to load (offline), hide the hint silently — never block recording.
- Device pickers (camera, mic) with warnings for virtual/Bluetooth mics and Desk View hidden; remembered in localStorage.
- Shot list (sidebar): each shot with its takes, QA verdict badge (great/ok/retake + reason on hover/expand), which take the
  auto-picker will use (★ best) and pin/discard buttons; play a take inline.
- Record flow: Space or button → 3-2-1 countdown (visual) → recording (red border + timer) → Space/Stop → upload with progress
  → card shows "checking…" then the QA result. Keys: Space record/stop, N/→ next shot, P/← previous shot, R retake same shot.
  After a "great" take, auto-advance to the next shot without a take after 1.5 s (can be disabled).
- "Build reel" button enabled when every shot has ≥1 ready take; shows step progress + log tail; on done plays
  /media/renders/reel-master.mp4 with loudness/true-peak numbers and per-shot chosen take + cut count.
- Import button per shot (file input accept="video/*") for native-camera recordings.
- Errors are shown, never swallowed (permission denied, no devices, upload failed, QA error).

## E2E harness (tests/e2e/)
Python Playwright (pip install playwright into .venv; use channel="chrome" so NO browser download) launching real Chrome
headless with `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream
--use-file-for-fake-video-capture=<1080x1920 .mjpeg> --use-file-for-fake-audio-capture=<take.wav>%noloop`.
One browser launch per take (each take has its own spoken wav made with macOS `say`, including deliberate flaws:
a misread take, a filler+restart take, a long-pause take, plus clean takes). Starts the studio server on a temp project
(copy of examples/demo/script.json's folder is NOT needed — point --script at examples/demo/script.json and --project at a
temp dir under work/e2e), records via the real UI (keyboard Space), waits for QA, asserts QA verdicts make sense
(misread take → retake with the misread listed; clean takes great/ok), clicks Build, waits for done, asserts the master exists,
duration within expected range, LUFS -14±1, true peak ≤ -0.9, and that the auto-picker chose the clean takes. Saves screenshots
of the studio UI (recording state, QA state, done state) to work/e2e/screens/ for visual review. Single command:
`.venv/bin/python tests/e2e/run_e2e.py`. Keep pytest unit tests fast (e2e is NOT collected by default pytest run).
