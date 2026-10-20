# Third-party software, fonts and sources

Reel Director's own code is MIT (`LICENSE`). The repository bundles two third-party sets, fonts and icons (section 1). It vendors no third-party library, audio or video. Everything else it uses is installed by you or loaded at run time (section 2). The MIT grant does not cover anything listed here: each item keeps its own licence.

## 1. Bundled in the repository

| item | where | licence | notes |
|---|---|---|---|
| 8 font families from the `@fontsource` packages, version 5.3.0: Montserrat, Anton, Bebas Neue, Inter, Bangers, Instrument Serif, Noto Sans Devanagari, Archivo Black (15 woff2 files) | `src/reel_director/fonts/<family>/` | SIL OFL 1.1 | Each folder carries `OFL.txt` with the family's copyright line. None declares a Reserved Font Name. `fonts/LICENSES.json` lists the package, version, source tarball and files of each family. The files are unmodified. |
| Lucide icons, 67 glyphs from `lucide-static` 1.49.0 | `src/reel_director/icons/lucide/` (SVG), inlined as CSS masks in `src/reel_director/web/reel.css` | ISC, Copyright (c) 2026 Lucide Icons and Contributors. Feather-derived glyphs: MIT, Copyright (c) 2013-present Cole Bemis | Full texts in `icons/LICENSE`. Each SVG keeps its `@license` comment, and the CSS block has an attribution header. `icons/LICENSES.json` pins each file's sha256. |

## 2. Installed by you or loaded at run time (never vendored)

| item | how it is used | licence | notes |
|---|---|---|---|
| [motion-pack](https://github.com/ANVEAI/motion-pack) v0.3.0 (ANVE) | Your own clone (`RD_PACK`, `MOTION_PACK`). Its transition and grade-layer modules (and their imports) are hard-linked into each compiled reel. Its beds and sound effects are mixed into `mix.wav`. | MIT code, CC0 generated media | Tested against tag v0.3.0. |
| GSAP 3.14.2 | `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js">` in every compiled reel (`compiler.py`, `web/page.html`) | GSAP Standard "no charge" licence (https://gsap.com/standard-license), not an OSI licence | Reel Director only references GSAP and ships none of its code. The terms restrict use in tools that let users build visual animations without code, so check them for your own use. The script tag carries no Subresource Integrity hash. |
| MediaPipe Tasks Vision 0.10.21 | ES module and WASM loaded from jsDelivr by the Studio's framing coach (`studio/static/overlay.js`) | Apache-2.0 | The coach stays off when it cannot load. |
| BlazeFace short-range face detector model | Fetched from storage.googleapis.com by the same coach | Apache-2.0 | |
| HyperFrames CLI 0.8.177 | `npm install -g hyperframes@0.8.177`. Renders the compiled HTML project to MP4. | Apache-2.0 | The CLI sends anonymous usage telemetry unless `HYPERFRAMES_NO_TELEMETRY=1` or `DO_NOT_TRACK=1` is set. Its first render may download a headless Chrome. |
| Whisper large-v3-turbo (`mlx-community/whisper-large-v3-turbo`) | Downloaded from Hugging Face on the first transcription | MIT | |
| mlx-whisper | pip dependency | MIT | |
| Silero VAD (`silero-vad`) | pip dependency. The model ships inside the package. | MIT | |
| PyTorch | pip, through mlx-whisper and silero-vad | BSD-3-Clause | |
| SciPy | pip, through mlx-whisper (imported directly by `mixdown.py` and `levels.py`) | BSD-3-Clause | |
| NumPy | pip dependency | BSD-3-Clause | |
| soundfile (with libsndfile) | pip dependency | BSD-3-Clause (libsndfile LGPL-2.1) | |
| pyobjc-framework-Vision, pyobjc-framework-Quartz | `mac` extra | MIT | Apple Vision itself is part of macOS. |
| pytest, Playwright | `dev` extra | MIT, Apache-2.0 | Playwright drives your installed Google Chrome. |
| FFmpeg and ffprobe | Your install, called as a subprocess | LGPL-2.1+ or GPL, depending on the build | |
| Google Chrome | Your install | Vendor terms | |
| `claude` CLI (optional) | Your install and login, run headless by `review --director` | Anthropic's terms | It reads the before/after sheet, the QA overlay and the JSON reports through your own login. |

## 3. Standards and formulae (re-implemented, no code copied)

| source | used for |
|---|---|
| ITU-R BS.1770-4 | The K-weighted, gated loudness meter and the 4x oversampled true-peak measurement in `levels.py` |

The research notes in `docs/research/` cite their sources inline. They paraphrase and summarise; they do not reproduce third-party text at length.
