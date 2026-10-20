/** Preview stage: fits the 9:16 crop to the screen, draws the framing guides, and a calm framing coach
 *  (MediaPipe face detector from the CDN; silently absent when offline). The target eye line is the one the
 *  edit's auto-reframe aims for, so a take framed on it needs no zoom. Creator-specific numbers (chin
 *  proportion, limits) come from qa/creator.json via setCoachProfile(); the defaults are the founder's takes. */
import { cropRect } from './devices.js';

export const SAFE_BOTTOM = 0.20;   // Reels/TikTok caption + buttons band
export const SAFE_RIGHT = 0.12;    // like / comment / share column
export const EYELINE = 0.40;       // learn.EYE_TARGET: the reframe target (v2 contract)
const MP_VERSION = '0.10.21';      // pinned: Feb 2025, last of the long-stable 0.10 line
const MP_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`;
const FACE_MODEL = 'https://storage.googleapis.com/mediapipe-models/face_detector/'
  + 'blaze_face_short_range/float16/1/blaze_face_short_range.tflite';
const LOAD_TIMEOUT_MS = 20000;
export const GOOD = 'Framing looks good';

/** Coach numbers (fractions of the 9:16 crop). learn.py writes the same keys into creator.json "coach". */
export const COACH = {
  eye_target: EYELINE, eye_tol: 0.03,
  chin_k: 1.94,               // eye-to-chin / eye-to-mouth (Apple Vision on the founder's takes)
  max_eye_to_chin: 0.16,      // one caption line still fits under the chin (+ beard clearance), eyes on the line
  centre_tol: 0.05,
};
const EYE_OUT = 2, EYE_BACK = 1.3;   // x eye_tol: hint past 2x (the reframe absorbs less), calm again under 1.3x
const CENTRE_OUT = 2, CENTRE_BACK = 1.2;
const SMALL_E2C = 0.07;              // eyes-to-chin under 7 % of the height: the face is tiny
const SMOOTH = 0.3;                  // exponential smoothing per 250 ms detection (~0.8 s time constant)
const HOLD_MS = 1500;                // a new state must last this long before the hint changes
const MIN_SHOW_MS = 2500;            // and a shown hint stays at least this long: no flicker
const LOST_MS = 2000;                // no face this long before saying so
const STALE_MS = 1500;               // a pause longer than this (recording, hidden tab) restarts the smoothing
const SETTLE = 3;                    // readings before the first verdict (one noisy frame never speaks)

/** Merge a creator profile's "coach" block (unknown keys and out-of-range values are ignored). */
export function setCoachProfile(coach) {
  if (!coach || typeof coach !== 'object') return;
  for (const k of Object.keys(COACH)) {
    const v = coach[k];
    if (typeof v === 'number' && Number.isFinite(v) && v > 0 && v < 4) COACH[k] = v;
  }
}

export class Stage {
  constructor(el, video, canvas) {
    Object.assign(this, { el, video, canvas, mirror: true, face: null, box: null });
    new ResizeObserver(() => this.layout()).observe(el);
    video.addEventListener('loadedmetadata', () => this.layout());
    video.addEventListener('resize', () => this.layout());
  }

  setMirror(on) {
    this.mirror = on;
    this.layout();
  }

  setFace(face) {
    this.face = face;
    this.draw();
  }

  /** Scale so the 9:16 crop fills the stage; the rest of a landscape frame shows, dimmed, around it. */
  layout() {
    const W = this.el.clientWidth, H = this.el.clientHeight;
    const vw = this.video.videoWidth, vh = this.video.videoHeight;
    if (!W || !H || !vw || !vh) return;
    const crop = cropRect(vw, vh);
    const s = Math.min(W / crop[2], H / crop[3]);
    Object.assign(this.video.style, {
      width: `${vw * s}px`, height: `${vh * s}px`,
      left: `${W / 2 - (crop[0] + crop[2] / 2) * s}px`, top: `${H / 2 - (crop[1] + crop[3] / 2) * s}px`,
      transform: this.mirror ? 'scaleX(-1)' : 'none',   // preview only: the recorded track is untouched
    });
    const w = crop[2] * s, h = crop[3] * s;
    this.box = { W, H, x: (W - w) / 2, y: (H - h) / 2, w, h, crop };
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(W * dpr);
    this.canvas.height = Math.round(H * dpr);
    this.draw();
  }

  draw() {
    const b = this.box;
    if (!b) return;
    const g = this.canvas.getContext('2d');
    g.setTransform(this.canvas.width / b.W, 0, 0, this.canvas.height / b.H, 0, 0);
    g.clearRect(0, 0, b.W, b.H);
    g.font = '600 11px -apple-system, system-ui, sans-serif';
    // Dim everything outside the crop.
    g.fillStyle = 'rgba(0, 0, 0, 0.62)';
    g.beginPath();
    g.rect(0, 0, b.W, b.H);
    g.rect(b.x, b.y, b.w, b.h);
    g.fill('evenodd');
    // App UI zones, placed in output coordinates: a mirrored preview shows the right column on the left.
    const sr = b.w * SAFE_RIGHT, sb = b.h * SAFE_BOTTOM;
    g.fillStyle = 'rgba(255, 90, 95, 0.16)';
    g.fillRect(this.mirror ? b.x : b.x + b.w - sr, b.y, sr, b.h - sb);
    g.fillRect(b.x, b.y + b.h - sb, b.w, sb);
    label(g, 'app UI covers this', b.x + 8, b.y + b.h - 8, 'rgba(255, 255, 255, 0.8)');
    // Target eye line, with the band the edit treats as "on the line".
    const ey = b.y + b.h * COACH.eye_target, tol = b.h * COACH.eye_tol;
    g.fillStyle = 'rgba(255, 212, 0, 0.07)';
    g.fillRect(b.x, ey - tol, b.w, 2 * tol);
    for (const [color, width, dash] of [['rgba(0, 0, 0, 0.55)', 3.5, []], ['rgba(255, 212, 0, 0.9)', 1.5, [8, 6]]]) {
      g.setLineDash(dash);   // dark underlay keeps the dashed line visible on bright or yellow scenes
      g.strokeStyle = color;
      g.lineWidth = width;
      g.beginPath();
      g.moveTo(b.x, ey);
      g.lineTo(b.x + b.w, ey);
      g.stroke();
    }
    g.setLineDash([]);
    label(g, 'eyes here', b.x + 8, ey - 7, 'rgba(255, 212, 0, 1)');
    g.strokeStyle = 'rgba(255, 255, 255, 0.45)';
    g.lineWidth = 1;
    g.strokeRect(b.x + 0.5, b.y + 0.5, b.w - 1, b.h - 1);
    this.drawFace(g, b);
  }

  /** Face box, the creator's current eye line across it, and (when off the band) a quiet arrow to the target. */
  drawFace(g, b) {
    const f = this.face;
    if (!f || f.none) return;
    const x = b.x + (this.mirror ? 1 - f.x - f.w : f.x) * b.w, w = f.w * b.w;
    g.strokeStyle = f.good ? 'rgba(61, 220, 132, 0.9)' : 'rgba(255, 176, 32, 0.95)';
    g.lineWidth = 2;
    g.strokeRect(x, b.y + f.y * b.h, w, f.h * b.h);
    if (typeof f.eye !== 'number') return;
    const y = b.y + f.eye * b.h, ty = b.y + COACH.eye_target * b.h;
    g.beginPath();
    g.moveTo(x - 6, y);
    g.lineTo(x + w + 6, y);
    g.stroke();
    if (Math.abs(y - ty) <= b.h * COACH.eye_tol) return;
    const ax = x + w + 14, dir = ty < y ? -1 : 1;
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(ax, y);
    g.lineTo(ax, ty - dir * 3);
    g.moveTo(ax - 5, ty - dir * 9);
    g.lineTo(ax, ty - dir * 3);
    g.lineTo(ax + 5, ty - dir * 9);
    g.stroke();
  }
}

/** Text with a dark outline so it reads on any scene. */
function label(g, text, x, y, color) {
  g.lineWidth = 3;
  g.lineJoin = 'round';   // mitred joins spike on glyph corners
  g.strokeStyle = 'rgba(0, 0, 0, 0.8)';
  g.strokeText(text, x, y);
  g.lineJoin = 'miter';
  g.fillStyle = color;
  g.fillText(text, x, y);
}

const timeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timed out')), ms))]);

/** One detection -> crop-relative measures: box, eye line, eyes-to-chin, eye midpoint x. */
export function measure(d, vw, vh, [cx, cy, cw, ch]) {
  const bb = d.boundingBox, kp = d.keypoints || [];
  const box = { x: (bb.originX - cx) / cw, y: (bb.originY - cy) / ch, w: bb.width / cw, h: bb.height / ch };
  // BlazeFace keypoints (normalised to the frame): 0/1 eyes, 2 nose tip, 3 mouth centre.
  const eyePx = kp.length >= 2 ? ((kp[0].y + kp[1].y) / 2) * vh : bb.originY + bb.height * 0.4;
  const mouthPx = kp.length >= 4 ? kp[3].y * vh : bb.originY + bb.height * 0.75;
  const midPx = kp.length >= 2 ? ((kp[0].x + kp[1].x) / 2) * vw : bb.originX + bb.width / 2;
  return { box, eye: (eyePx - cy) / ch, e2c: COACH.chin_k * Math.max(0, (mouthPx - eyePx) / ch), mid: (midPx - cx) / cw };
}

/** The most important framing issue in a (smoothed) measure, or null. `active` is the issue on screen now:
 *  it only clears once the measure is well back inside (hysteresis), so a hint never flaps at a threshold. */
export function judge(m, active = null) {
  const eyeTol = COACH.eye_tol * (active === 'eye-low' || active === 'eye-high' ? EYE_BACK : EYE_OUT);
  const dEye = m.eye - COACH.eye_target;
  // Pinhole camera: moving it down lifts the face in the frame, so eyes below the line -> lower or tilt down.
  if (dEye > eyeTol) return { id: 'eye-low', hint: 'Eyes below the line: lower the camera a little or tilt it down' };
  if (dEye < -eyeTol) return { id: 'eye-high', hint: 'Eyes above the line: raise the camera a little or tilt it up' };
  if (m.e2c > COACH.max_eye_to_chin + (active === 'far' ? -0.01 : 0.01)) {
    return { id: 'far', hint: 'Sit back a little: leave room under your chin for captions' };
  }
  if (m.e2c < SMALL_E2C) return { id: 'near', hint: 'Move a little closer: your face is small in the frame' };
  const cTol = COACH.centre_tol * (active === 'left' || active === 'right' ? CENTRE_BACK : CENTRE_OUT);
  // Unmirrored frame: image-left is the creator's right, so a face left of centre moves to their left.
  if (m.mid < 0.5 - cTol) return { id: 'left', hint: 'Centre yourself: move a little to your left' };
  if (m.mid > 0.5 + cTol) return { id: 'right', hint: 'Centre yourself: move a little to your right' };
  const bx = m.box;
  if (bx.x + bx.w > 1 - SAFE_RIGHT || bx.y + bx.h > 1 - SAFE_BOTTOM) return { id: 'ui', hint: 'Your face is under the app UI area' };
  return null;
}

/** Smooths detections and only changes the hint once a new state has held for HOLD_MS (and the old one was
 *  shown for MIN_SHOW_MS): calm, never blocking, never a flashing instruction. */
export class Coach {
  constructor() {
    this.reset();
  }

  reset() {
    Object.assign(this, { s: null, n: 0, shown: null, started: false, pending: null, pendingAt: 0, shownAt: 0, lostAt: null, last: -Infinity });
  }

  /** m: a measure() or null (no face); now: ms. Returns what the stage and the hint pill show (null while it
   *  settles: the studio then hides both). */
  update(m, now) {
    if (now - this.last > STALE_MS) this.reset();
    this.last = now;
    if (!m) {
      this.lostAt ??= now;
      return now - this.lostAt >= LOST_MS ? { none: true, good: false, hint: 'No face found in the frame' } : this.view();
    }
    this.lostAt = null;
    const s = this.s, k = SMOOTH;
    this.s = s ? { box: m.box, eye: s.eye + k * (m.eye - s.eye), e2c: s.e2c + k * (m.e2c - s.e2c), mid: s.mid + k * (m.mid - s.mid) }
      : { ...m };
    if (++this.n < SETTLE) return null;
    const want = judge(this.s, this.shown?.id ?? null);
    const key = want?.id ?? 'good';
    if (!this.started) this.show(want, now);                       // first verdict: no extra wait
    else if (key === (this.shown?.id ?? 'good')) this.pending = null;
    else if (this.pending !== key) Object.assign(this, { pending: key, pendingAt: now });
    else if (now - this.pendingAt >= HOLD_MS && now - this.shownAt >= MIN_SHOW_MS) this.show(want, now);
    return this.view();
  }

  show(want, now) {
    Object.assign(this, { shown: want, shownAt: now, pending: null, started: true });
  }

  view() {
    if (!this.started) return null;
    return { ...this.s.box, eye: this.s.eye, good: !this.shown, hint: this.shown?.hint ?? GOOD, issue: this.shown?.id ?? null };
  }
}

export class FaceHint {
  constructor() {
    this.det = null;
    this.lastTs = 0;
    this.coach = new Coach();
  }

  /** Resolves false when MediaPipe can't load (offline, CDN blocked). Never throws: it is optional. */
  async load() {
    try {
      const mp = await timeout(import(`${MP_BASE}/vision_bundle.mjs`), LOAD_TIMEOUT_MS);
      const files = await timeout(mp.FilesetResolver.forVisionTasks(`${MP_BASE}/wasm`), LOAD_TIMEOUT_MS);
      const make = delegate => mp.FaceDetector.createFromOptions(files, {
        baseOptions: { modelAssetPath: FACE_MODEL, delegate }, runningMode: 'VIDEO', minDetectionConfidence: 0.5,
      });
      this.det = await timeout(make('GPU').catch(() => make('CPU')), LOAD_TIMEOUT_MS);
      return true;
    } catch (e) {
      console.info('Face framing hint unavailable:', e?.message || e);
      return false;
    }
  }

  /** {x, y, w, h (fractions of the crop), eye, good, hint, issue} | {none, hint} | null when it can't run. */
  detect(video, crop) {
    if (!this.det || video.readyState < 2 || !crop) return null;
    try {
      const now = performance.now();
      this.lastTs = Math.max(now, this.lastTs + 1);   // MediaPipe needs increasing timestamps
      const dets = this.det.detectForVideo(video, this.lastTs).detections || [];
      const big = dets.length ? dets.reduce((a, d) => (d.boundingBox.width > a.boundingBox.width ? d : a)) : null;
      return this.coach.update(big && measure(big, video.videoWidth, video.videoHeight, crop), now);
    } catch (e) {
      console.info('Face detection failed:', e?.message || e);
      return null;
    }
  }
}
