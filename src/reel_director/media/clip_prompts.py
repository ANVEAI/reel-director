"""Prompts and the authoring kit for Claude-created B-roll clips (v4 media contract, `claude_clip` provider).

`claude -p` gets ONE prompt (build_prompt) and a sandbox that already holds a renderable scaffold (scaffold_html), the
founder's motion-pack modules (mp/), the Reel Director fonts (kit/fonts.css + kit/fonts/), owned line icons
(kit/icons/), a three.js shim for the pack's 3D objects (kit/objects3d.js) and up to two accepted clips from earlier
briefs (kit/examples/). KIT lists only parts proven to render in HyperFrames; RULES carry the gotchas found while
judging the first clips frame by frame; MOTIFS steer common briefs toward a picture that reads in one second.
The contract checks live here too (static_check, parse_lint, frame_check), next to the rules they enforce.
PROMPT_VERSION is part of the brief hash: bump it when the prompt changes and the clip cache re-authors.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np

PROMPT_VERSION = "cc-v5"
COMP_ID = "clip"
GSAP_URL = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.160.0"

# the strict output contract: `claude -p --json-schema` validates the final answer against this
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "error"]},
        "hero": {"type": "string", "description": "the one hero image of the clip, in a few words"},
        "parts": {"type": "array", "items": {"type": "string"}, "description": "motion-pack ids / kit parts used"},
        "self_check": {"type": "string", "description": "what lint and your own snapshot review showed"},
        "summary": {"type": "string"},
    },
    "required": ["status", "hero", "parts", "summary"],
}

DEFAULT_STYLE = {
    "bg": "#0B0A10", "surface": "#17151F", "ink": "#F5F3FA", "muted": "#8D8A9C",
    "accent": "#7C5CFF", "accent2": "#FFB547", "good": "#2BD98B",
    "display": "Inter", "headline": "Montserrat", "serif": "Instrument Serif",
}

# brief keywords -> art direction that reads in 1.2-3 s (a hint, never a script: Claude still designs the shot)
MOTIFS = [
    (("hour", "hours", "clock", "time", "minutes", "slow", "late", "deadline", "waiting", "forever"),
     "TIME DRAINING. Hero: a large premium analog clock (SVG: metallic gradient bezel, dark face, 60 ticks, 12/3/6/9, "
     "glowing cap, a soft glass sheen) about 70% of the frame width. The minute hand sweeps several full turns "
     "(ease in-out, already moving on frame 0) with 6-7 fading ghost copies as motion blur; the hour hand crawls "
     "and an amber elapsed-time arc grows behind it from where it started. Above: a pill with a pulsing red dot, a "
     "1-word label and an HH:MM:SS readout spinning up to the brief's number (digits only from the brief). Below: an "
     "editing timeline card whose clip blocks keep popping in while the view zooms out to fit the growing pile. "
     "Warm amber glow, dark plum field, slow push-in with a degree of roll."),
    (("finished", "done", "ready", "complete", "check", "before you", "already", "instant", "automatic"),
     "DONE BEFORE YOU START. Hero: an editor timeline card (window dots, a 1-word label, ruler ticks, 4 tracks with "
     "gutter icons: B-roll, face video cut into jump-cut segments, caption pills, a music waveform). On frame 0 the "
     "face track is already laid and its last segment is landing (the edit is mid-assembly, never an empty card); the "
     "other clips arrive from just outside the card and snap onto their tracks with spring overshoot and a white impact "
     "flash (caption pills rise from below, one after another, so they never cross), the playhead sweeps once, the card "
     "dims and a glossy green check badge pops over it with a spring, the tick draws on, two rings pulse out and a "
     "short spark halo bursts BEHIND the badge. Under the card an idle REC pill still reads 00:00 while a cursor drifts "
     "toward it - the edit is done before recording starts. Dot-grid field with a soft glow."),
    (("script", "read", "page", "words", "write", "lines", "teleprompter", "story"),
     "THE SCRIPT. Hero: one cream paper page (rounded 28px, fine paper noise, deep soft shadow) tilted slightly in 3D "
     "and drifting toward camera, 80% of the frame width. A mono eyebrow + a terracotta scene heading, then 6 lines of "
     "short spoken-style script in a 64px serif. Lines already read are dim with a faint marker; the current lines get "
     "a word-by-word highlighter (amber marker band behind the lower half of each word, the space included so the band "
     "is continuous) and a caret riding the read point; the reading finishes by 80% of the clip. Warm key light behind "
     "the page, small warm bokeh."),
    (("build", "builds", "itself", "assemble", "pieces", "puzzle", "together", "auto", "magic", "creates"),
     "IT BUILDS ITSELF. Hero: a phone (dark metallic bezel, dynamic island, 55-60% of the frame width) whose screen "
     "shows dashed empty slots. On frame 0 the face-video tile has just landed and the next piece is mid-flight beside "
     "the phone (no piece cut by the frame edge on frame 0). Pieces fly in on curved paths with rotation and land with "
     "spring overshoot, staggered ~0.25 s: the face-video tile (gradient + user icon), a B-roll PiP tile, a caption "
     "pill with two bold words, a music waveform strip, three small tool chips; each landing flashes a ring and its "
     "slot fades. Then the phone bumps once, a sheen sweeps across the glass, a progress bar fills and a short spark "
     "halo flares BEHIND the phone. Slow 3D turn of the phone; violet halo."),
    (("money", "revenue", "cash", "sales", "profit", "grow", "growth", "income", "rupee", "dollar"),
     "MONEY GROWING. Hero: coin/notes stack or a bar chart rising with spring overshoot, counter rolling (number "
     "from the brief only, otherwise no digits), sparkles on peaks, upward camera drift."),
    (("rocket", "launch", "takeoff", "skyrocket", "blast"),
     "LAUNCH. Hero: a stylised rocket (SVG shapes, not clip-art) lifting from a pad with smoke puffs (layers "
     "`smoke`), speed lines and camera shake that decays, a glowing exhaust; it exits frame top as the smoke fills."),
]
FALLBACK_MOTIF = ("ONE HERO, ONE VERB. Pick the single most concrete noun of the brief, draw it big and beautifully "
                  "(SVG/canvas/three.js), and give it one clear action that completes within the clip, with depth "
                  "(background field, hero, foreground particles) and continuous camera drift.")

KIT = """## The kit in this folder (read-only: never edit kit/ or mp/)
- `index.html`  the scaffold you edit: root, fonts, GSAP, one paused timeline, one seek-safe `draw(t)`. It already
  renders. Keep its contract lines (marked KEEP); replace the demo scene.
- `kit/examples/*.html` (when present): accepted clips from earlier briefs. Read one first for the contract and the
  quality bar; never copy its picture.
- `kit/fonts.css` (+ kit/fonts/*): @font-face for Inter 400/700/800, Montserrat 800/900, Anton, Bebas Neue, Archivo
  Black, Instrument Serif (+italic), Bangers, Manrope (variable), IBM Plex Mono 500/600. The scaffold inlines it.
- `kit/icons/<name>.svg`: owned Lucide line icons (24x24, stroke currentColor). Paste the <path>s inline into your SVG
  (Read the file) so you can colour them. Names: {icons}.
- `mp/` = the founder's motion-pack (ES modules, pure functions of t). Tested entry points:
  * Backgrounds, particles, film finish -> `import {{ mountStack }} from './mp/layers/overlay.js'`. One stack UNDER
    the scene for the background, one OVER it for vignette + grain (as in the scaffold), each `.render(t)` in draw:
      mountStack(bgEl, [{{kind:'meshGradient', params:{{colors:['#2A1B5C','#0B0A10','#123A5C'], bg:'#0B0A10', blobs:5,
        speed:0.08, grain:0.035, seed:13}}}}], {{width:W, height:H, fps:30, seed:13}})
    backgrounds: meshGradient (palette peach|lilac|sky|dusk|mint|ink, or colors+bg) | dotGrid {{color, bg, spacing,
    radius, drift:[x,y], glow, glowColor, glowAt}} | gridTunnel | auroraRibbon. particles: sparks {{x, y, count,
    spread:2 (=360deg), speed, gravity, life, color, burstAt}} (a one-shot burst at x,y frame fractions; speed is in
    frame-heights per second: 0.25-0.4 with life 0.6-0.7 and gravity <= 0.15 for a halo around a hero; speed > 0.6
    throws streaks across the whole frame that read as scratches) confetti
    embers smoke snow motes {{count, size<=2, intensity<=0.5}}. lens/film: bokeh {{count, radius:[0.012,0.035],
    intensity<=0.3}} glow leaks vignette {{amount}} grain {{stock:'film35'}} dust paper. One background, one grain,
    one vignette. A burst goes in its own stack placed BEHIND the hero, so only its halo shows.
  * Editor graphics as SVG strings -> `import {{ renderSVG }} from './mp/type/gfx/index.js'`
      el.innerHTML = renderSVG('ui.checklist', t, {{at:0, params:{{theme:'dark', box:[0.1,0.3,0.8,0.36],
        title:'Edit', steps:['Cuts','Captions','B-roll','Music'], start:0.2, step:0.45, accent:'#2BD98B'}}}}, {{W, H}});
    ids: ui.checklist ui.agentActivity ui.promptBar ui.nodeGraph ui.connectRows ui.fileChip counter.countUp
    counter.wheel counter.ring title.timecodeHUD title.progressBar title.recDot callout.underline
    callout.scribbleCircle callout.handArrow fx.impact.speedLines fx.emotion.sparkle reaction.burst chart.bar
    chart.line type.commandPill. Read mp/type/gfx/<file>.js for an id's params (`d:` defaults) before using it.
  * Stroke draw-on for your own SVG -> `import {{ prepareDrawOn, drawOnAt }} from './mp/type/gfx/index.js'`, or a
    path's stroke-dasharray/-dashoffset from getTotalLength() measured ONCE at build time.
  * Easing + springs (pure) -> `import {{ E, clamp, seg, lerp, sstep, spring, springTrack, mulberry32 }} from
    './mp/type/ease.js'`. E.enter E.hero E.pop E.move E.soft E.expoOut map 0..1; seg(t,a,b) maps time to 0..1;
    spring(t - t0, {{zeta:0.5, f:2.2}}) is a step that overshoots and settles (0 before t0); springTrack(t,
    [[t0,v0],[t1,v1]], 'ui'|'panel'|'camera'|'headline'|'mascot'). Physics = closed-form springs, ballistic arcs
    and damped sines; never a live simulation.
  * 3D (optional, when depth sells the hero): three.js 0.160 through exactly this importmap
      <script type="importmap">{{"imports":{{"three":"{three}/build/three.module.js",
        "three/addons/":"{three}/examples/jsm/"}}}}</script>
    new THREE.WebGLRenderer({{canvas, antialias:true, alpha:true}}); setPixelRatio(1); setSize(W,H,false); render in
    draw(t). The pack's objects work through the shim: `import {{ objectsCtx }} from './kit/objects3d.js'; const ctx =
    objectsCtx(renderer, scene);` then e.g. `makePuck(ctx, scene, {{r:0.24, t:0.08}}).set([x,y,z], rotY)` (a glossy
    lock -> check coin: rotate PI to flip) and `makeTile(ctx, scene, {{icon:'mic'|'page'|'lens'|'deck'|'image'|'pen'|
    'wave'|'check'|'lock'|'x'}}).set([x,y,z], {{yaw}})` from './mp/objects/lib/panels.js'; makePhone / makeLaptop
    (devices.js), makeClock / makeReadout (readouts.js), makeSheet (paper.js) take the same ctx - read their source
    for params. Add a HemisphereLight fill + a key DirectionalLight. Never import mp/objects/index.js or its kit/.
- Seeded randomness only: `const rnd = mulberry32(42)` at build time; never Math.random / Date / performance.now.
"""

RULES = """## Hard rules (the render is rejected if any fails)
1. Write only `index.html` in this folder (one self-contained file; inline CSS/JS/SVG). Never edit kit/ or mp/. No
   network: no fetch(), no remote images or fonts; the only remote URLs allowed are the GSAP script already in the
   scaffold and the three.js importmap above.
2. Keep the scaffold contract: root `<div id="root" data-composition-id="{cid}" data-start="0" data-width="{w}"
   data-height="{h}" data-duration="{dur}" data-fps="{fps}">`; ONE `gsap.timeline({{paused:true}})` registered LAST as
   `window.__timelines["{cid}"] = tl`; the clock tween that calls draw(t) across the whole duration; the `hf-seek`
   listener. Every pixel is a pure function of t: the checker seeks out of order and compares with the render, so
   draw(t) must set every animated property on every call (no `x += v`, no state kept between frames).
3. Never put a CSS transform on an element that GSAP also moves (set transforms in draw(t), or gsap.fromTo). Never
   tween visibility/display/autoAlpha. Never use the class name `clip` for your own elements (HyperFrames reserves
   it). No `<br>` in text. Measure DOM layout (offsetLeft, getTotalLength...) ONCE after `await document.fonts.ready`
   and before the timeline is registered - never inside draw(t).
4. Frame 0 is already a finished, strong picture in motion: no black/empty first frame, no fade-in from black, the
   first visible change lands by frame 6 (start the first move before t=0, e.g. spring(t + 0.1, ...)). Something
   moves on EVERY frame to the very end (drift, parallax, shimmer); the action completes by ~85% of the clip and the
   tail settles but never freezes.
5. This is B-roll that cuts into a talking-head reel: captions are laid over it later. So: no paragraphs, at most 1-3
   short labels (1-2 words each, >= 26px); no logos, brand names, real product UI or invented statistics (a number
   only if it is in the brief); keep the hero inside x 60..{w60}, y {ytop}..{ybot} on EVERY frame (a camera push-in scales it: check the last
   frame); keep the bottom 22% calm and dark (no cursor or particle passing through it).
6. Premium bar: one hero, big (55-80% of the frame width), depth (background field + hero + foreground accents),
   soft real shadows and light, crisp vector edges, 2-3 colours from the palette, eases/springs (linear only for
   drift), staggered secondary motion, subtle grain + vignette. Check every element stays inside its card/track (no
   overflow at the right edge), labels never sit on top of icons, particles never cover the hero. It reads in 1 s.
"""

TASK = """You are a senior motion designer. Build a {dur}-second {w}x{h} B-roll clip as a HyperFrames composition.

BRIEF: "{brief}"
CONTEXT (the spoken line it sits under, if any): "{context}"
ART DIRECTION: {motif}
PALETTE: bg {bg}, surface {surface}, ink {ink}, muted {muted}, accent {accent}, accent2 {accent2}, success {good}.
TYPE: {display} (UI/labels), {headline} 800/900 (punchy labels), {serif} (script/page text) - all in kit/fonts.css.

{kit}
{rules}
## Workflow
1. Read index.html (the scaffold) and one kit/examples file if present. Plan 3 beats across {dur}s (establish already
   in motion -> the action -> the payoff that still breathes).
2. Write index.html. Run `hyperframes lint .` and fix every error and warning.
3. Run `hyperframes snapshot . --at {snaps} --no-end --describe false -o snap` (exactly so: no frame upload)
   and Read snap/contact-sheet.jpg (or the PNGs). Judge it as a picky creative director at phone size: hero
   instantly readable and big, premium light and depth, nothing clipped or overflowing, no empty or flat frame, no
   text on icons, particles not covering the hero. Fix the weakest frame and snapshot again (at most 2 review rounds).
4. Answer with the JSON result (status ok only if lint is clean and you looked at the snapshots).
{feedback}"""

FEEDBACK = """
## PREVIOUS ATTEMPT WAS REJECTED - fix these problems first (the current index.html is that attempt):
{errors}
"""

# kit/objects3d.js: the minimal ctx the pack's objects (mp/objects/lib/*.js) need outside their own kit harness
OBJECTS_SHIM = """/* Reel Director kit: the ctx motion-pack objects (mp/objects/lib/*.js) need in a plain three.js scene.
   import { objectsCtx } from './kit/objects3d.js'; const ctx = objectsCtx(renderer, scene);
   import { makePuck, makeTile } from './mp/objects/lib/panels.js'; makePuck(ctx, scene, { r: 0.24 }).set([0, 0, 0], ry);
   Colours stay as designed (no tone mapping); metals and glazes reflect a soft room environment. */
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
export function objectsCtx(renderer, scene, { W = 1080, H = 1920, LEN = 3, colors = {} } = {}) {
  renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.NoToneMapping;
  const env = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = env;
  return { THREE, renderer, scene, W, H, LEN, aspect: W > H ? 'wide' : 'tall', K_KEY: [1, 1, 1], metalEnv: env, probes: {},
    C: { colors: { backdrop: '#f5f2ea', slab: '#fbfaf7', violet: '#4a18ed', red: '#e5483a', mint: '#34d399', amber: '#ffa64d', ink: '#111111', ...colors } },
    add(parent, m, { cast = false, recv = true, name = null } = {}) { m.castShadow = cast; m.receiveShadow = recv; if (name) m.name = name; parent.add(m); return m; },
    emis(hex, amt) { return new THREE.Color(hex).multiplyScalar(amt); } };
}
"""


def pick_motif(brief: str, context: str = "") -> str:
    words = set(re.findall(r"[a-z]+", f"{brief} {context}".lower()))
    text = f" {brief} {context} ".lower()
    best, score = FALLBACK_MOTIF, 0
    for keys, motif in MOTIFS:
        s = sum(1 for k in keys if (k in words if " " not in k else k in text))
        if s > score:
            best, score = motif, s
    return best


def snap_times(duration: float) -> str:
    return ",".join(f"{duration * f:.2f}" for f in (0.03, 0.35, 0.65, 0.95))


def build_prompt(brief: str, *, width: int = 1080, height: int = 1920, duration: float = 3.0, fps: int = 30,
                 context: str = "", style: dict | None = None, icons: list[str] | None = None,
                 errors: list[str] | None = None) -> str:
    st = {**DEFAULT_STYLE, **(style or {})}
    kit = KIT.format(icons=", ".join(icons or []) or "(none)", three=THREE_URL)
    rules = RULES.format(cid=COMP_ID, w=width, h=height, dur=_num(duration), fps=fps, w60=width - 60,
                         ytop=int(height * 0.12), ybot=int(height * 0.76))
    fb = FEEDBACK.format(errors="\n".join(f"- {e}" for e in errors)) if errors else ""
    return TASK.format(dur=_num(duration), w=width, h=height, brief=_clean(brief), context=_clean(context),
                       motif=pick_motif(brief, context), kit=kit, rules=rules, snaps=snap_times(duration),
                       feedback=fb, **st)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).replace('"', "'").strip()[:400]


def _num(x: float) -> str:
    return f"{float(x):g}"


def font_faces(fonts: list[tuple[str, str, int, str]]) -> str:
    """@font-face rules for [(family, rel_url, weight, style)] (weight 0 = variable 100..900)."""
    out = []
    for fam, url, weight, style in fonts:
        w = "100 900" if not weight else str(weight)
        fmt = "woff2" if url.endswith(".woff2") else "truetype"
        out.append(f"@font-face {{ font-family: \"{fam}\"; src: url(\"{url}\") format(\"{fmt}\"); font-weight: {w}; "
                   f"font-style: {style}; font-display: block; }}")
    return "\n".join(out)


def scaffold_html(*, width: int, height: int, duration: float, fps: int, faces: str, style: dict | None = None,
                  brief: str = "") -> str:
    """A renderable starting point: background field + a placeholder hero that moves. Claude replaces the scene."""
    st = {**DEFAULT_STYLE, **(style or {})}
    return SCAFFOLD.replace("__W__", str(width)).replace("__H__", str(height)).replace("__D__", _num(duration)) \
        .replace("__FPS__", str(fps)).replace("__CID__", COMP_ID).replace("__GSAP__", GSAP_URL) \
        .replace("__FACES__", faces).replace("__BG__", st["bg"]).replace("__INK__", st["ink"]) \
        .replace("__ACCENT__", st["accent"]).replace("__BRIEF__", json.dumps(_clean(brief)))


SCAFFOLD = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=__W__, height=__H__" />
<title>clip</title>
<script src="__GSAP__"></script>
<style>
__FACES__
html, body { margin: 0; width: __W__px; height: __H__px; background: __BG__; }
#root { position: relative; width: 100%; height: 100%; overflow: hidden; background: __BG__; color: __INK__;
  font-family: "Inter", sans-serif; }
.layer { position: absolute; inset: 0; }
#hero { position: absolute; left: 50%; top: 42%; width: 520px; height: 520px; margin: -260px 0 0 -260px;
  border-radius: 120px; background: linear-gradient(145deg, __ACCENT__, #2A1B5C); box-shadow: 0 60px 120px rgba(0,0,0,.55); }
</style>
</head>
<body>
<!-- KEEP: the root contract (id, size, duration, fps) -->
<div id="root" data-composition-id="__CID__" data-start="0" data-width="__W__" data-height="__H__" data-duration="__D__" data-fps="__FPS__">
  <div id="bg" class="layer"></div>
  <div id="scene" class="layer"><div id="hero"></div></div>
  <div id="fx" class="layer"></div>
</div>
<script type="module">
import { mountStack } from "./mp/layers/overlay.js";
import { E, seg, clamp } from "./mp/type/ease.js";
const W = __W__, H = __H__, D = __D__, BRIEF = __BRIEF__;
const bg = mountStack(document.getElementById("bg"), [{ kind: "meshGradient", params: { palette: "ink", speed: 0.08, grain: 0.04 } }], { width: W, height: H, fps: __FPS__, seed: 7 });
const fx = mountStack(document.getElementById("fx"), [{ kind: "vignette", params: { amount: 0.3 } }, { kind: "grain", params: { stock: "film35" } }], { width: W, height: H, fps: __FPS__, seed: 7 });
const hero = document.getElementById("hero");
function draw(t) {                       // KEEP: everything that is not a GSAP tween is drawn here from t alone
  t = clamp(t, 0, D);
  bg.render(t); fx.render(t);
  const k = E.hero(seg(t, 0, 1.2));
  gsap.set(hero, { rotation: -12 + 12 * k + 2 * Math.sin(t * 2), scale: 0.8 + 0.2 * k });
}
const tl = gsap.timeline({ paused: true });   // KEEP: one paused timeline
// add GSAP tweens for DOM elements here, e.g. tl.fromTo("#label", { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "power3.out" }, 0.4);
const clock = { t: 0 };                       // KEEP: the clock tween drives draw(t) on every frame
tl.fromTo(clock, { t: 0 }, { t: D, duration: D, ease: "none", immediateRender: false, onUpdate: () => draw(clock.t) }, 0);
window.addEventListener("hf-seek", (e) => draw(e.detail && e.detail.time));   // KEEP
draw(0);
window.__timelines["__CID__"] = tl;          // KEEP: registered last
</script>
</body>
</html>
"""


# ---- the contract checks (the provider runs them on every attempt; tests run them on fixtures) ----
ALLOWED_URLS = (GSAP_URL, THREE_URL)
BANNED = [(re.compile(r"Math\.random\s*\("), "Math.random() (use mulberry32 from mp/type/ease.js)"),
          (re.compile(r"Date\.now\s*\(|new Date\s*\("), "a wall clock (Date)"),
          (re.compile(r"performance\.now\s*\("), "performance.now()"),
          (re.compile(r"requestAnimationFrame|setAnimationLoop|setInterval\s*\("), "a free-running loop (rAF/interval)"),
          (re.compile(r"\bfetch\s*\(|XMLHttpRequest"), "a network fetch")]


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def static_check(sb: Path, spec) -> list[str]:
    """The composition keeps the contract: root attrs, the registered timeline, no clocks/randomness/network, kit intact."""
    idx = sb / "index.html"
    if not idx.exists():
        return ["index.html was not written"]
    html = idx.read_text(errors="replace")
    errs = []
    root = re.search(r"<div[^>]*\bid=\"root\"[^>]*>", html)
    tag = root.group(0) if root else ""
    for attr, want in (("data-composition-id", COMP_ID), ("data-width", spec.width), ("data-height", spec.height),
                       ("data-duration", _num(spec.duration))):
        if not re.search(rf'{attr}="{re.escape(str(want))}"', tag):
            errs.append(f'the root <div id="root"> must keep {attr}="{want}"')
    if not re.search(rf"window\.__timelines\[[\"']{COMP_ID}[\"']\]\s*=", html):
        errs.append(f'the paused timeline must be registered as window.__timelines["{COMP_ID}"]')
    for rx, what in BANNED:
        if rx.search(html):
            errs.append(f"not seek-safe: uses {what}")
    for url in sorted(set(re.findall(r"https?://[^\s\"'<>)`]+", html))):
        if not url.startswith(ALLOWED_URLS) and "www.w3.org/" not in url:
            errs.append(f"remote URL not allowed: {url[:80]}")
    man = sb / "out" / "kit-manifest.json"
    if man.exists():
        changed = [rel for rel, h in json.loads(man.read_text()).items()
                   if not (sb / rel).is_file() or file_sha(sb / rel) != h]
        if changed:
            errs.append(f"kit files were modified (read-only): {', '.join(changed[:4])}")
    return errs


def parse_lint(text: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) from `hyperframes lint --json` (falls back to scanning plain text)."""
    try:
        data = json.loads(text[text.index("{"):]) if "{" in text else None
    except ValueError:
        data = None
    if isinstance(data, dict):
        found = data.get("findings") or []
        fmt = lambda f: f"{f.get('code') or f.get('rule', '')}: {f.get('message', '')}".strip(": ")
        errs = [fmt(f) for f in found if str(f.get("severity", "")).lower() == "error"]
        warns = [fmt(f) for f in found if str(f.get("severity", "")).lower() == "warning"]
        if not errs and data.get("errorCount"):
            errs = [f"{data['errorCount']} lint error(s)"]
        return errs, warns
    return [ln.strip() for ln in text.splitlines() if re.search(r"\berror\b", ln, re.I) and "0 error" not in ln], []


def gray_frames(src: Path, times: list[float], ffmpeg: str = "ffmpeg", run=subprocess.run, w: int = 108,
                h: int = 192) -> list:
    """Downscaled luma frames of a video (or an image, t=0) at `times`; None where decoding failed."""
    out = []
    for t in times:
        r = run([ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-vf",
                 f"scale={w}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True,
                timeout=60)
        buf = r.stdout if isinstance(r.stdout, (bytes, bytearray)) else b""
        out.append(np.frombuffer(buf, np.uint8).reshape(h, w).astype(np.float32) if len(buf) == w * h else None)
    return out


def frame_check(mp4: Path, spec, ffmpeg: str = "ffmpeg", run=subprocess.run) -> tuple[list[str], dict]:
    """Frames are pictures (not flat/empty), frame 0 is one, the first change lands by frame 6, motion to the end."""
    fr, D = spec.fps, spec.duration
    times = [0.0, 6 / fr] + [D * k / 8 for k in range(1, 8)] + [D - 2 / fr]
    sw, sh = (108, 192) if spec.height >= spec.width else (192, 108)
    frames = gray_frames(mp4, times, ffmpeg, run, sw, sh)
    if any(f is None for f in frames):
        return [f"could not decode frames at {[round(t, 2) for t, f in zip(times, frames) if f is None]} s"], {}
    errs: list[str] = []
    empty = lambda f: float(f.std()) < 3.0 or float((np.abs(f - np.median(f)) > 12).mean()) < 0.004
    blanks = [round(t, 2) for t, f in zip(times, frames) if empty(f)]
    if blanks:
        errs.append(f"blank/empty frames at {blanks} s (flat colour or nothing drawn; frame 0 must already be a picture)")
    diffs = [float(np.abs(a - b).mean()) for a, b in zip(frames[1:], frames[2:])]
    first = float(np.abs(frames[0] - frames[1]).mean())
    if first < 0.08:
        errs.append("nothing changes in the first 6 frames (frame 0 must already be in motion)")
    if max(diffs) < 1.5:
        errs.append(f"almost no motion (largest change between samples {max(diffs):.2f}); the hero action is missing")
    if diffs[-1] < 0.05 and diffs[-2] < 0.05:
        errs.append("the last ~0.7 s is frozen; keep a drift/shimmer moving to the end")
    return errs, {"frame_std": [round(float(f.std()), 1) for f in frames], "motion": [round(d, 2) for d in diffs],
                  "first_change": round(first, 2)}


def contact_sheet(mp4: Path, out_jpg: Path, times: list[float], fps: int = 30, ffmpeg: str = "ffmpeg",
                  width: int = 270) -> Path:
    """One strip of frames at `times` (report / Studio picker)."""
    pick = "+".join(f"eq(n\\,{round(t * fps)})" for t in times)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(mp4), "-vf",
                    f"select='{pick}',scale={width}:-2,tile={len(times)}x1:padding=6", "-fps_mode", "vfr",
                    "-frames:v", "1", "-q:v", "3", str(out_jpg)], check=True, timeout=120)
    return out_jpg
