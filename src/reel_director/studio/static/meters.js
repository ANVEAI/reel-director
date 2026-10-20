/** Live meters: audio peak level with hold + clip light + room noise floor, and exposure (luma). */

export const CLIP_DB = -0.3;      // the take QA's clipping line
const FLOOR_DB = -60;             // left edge of the meter
const HOLD_MS = 1500;
const RELEASE_DB_PER_S = 24;      // PPM-like fall-back after a peak
const CLIP_LIGHT_MS = 2000;
const NOISE_WINDOW = 120;         // RMS samples (one per 50 ms) = the last 6 s
const toDb = v => (v > 0 ? 20 * Math.log10(v) : -Infinity);
const pct = db => Math.max(0, Math.min(100, ((db - FLOOR_DB) / -FLOOR_DB) * 100));

/** Room noise class. QA fails a take under 15 dB SNR and warns under 25; speech sits near
 *  -30..-20 dBFS RMS, so a floor above -45 already threatens the SNR warning. */
export function noiseClass(db) {
  if (db <= -55) return { level: 'ok', text: 'quiet' };
  if (db <= -45) return { level: 'warn', text: 'some background noise' };
  return { level: 'fail', text: 'noisy: switch off fans/AC, close windows' };
}

export class AudioMeter {
  /** els: {mask, hold, clip, readout, noise} */
  constructor(els) {
    this.els = els;
    this.ctx = null;
    this.level = this.peak = FLOOR_DB;
    this.peakAt = this.clipUntil = this.lastTick = this.lastRms = this.lastText = this.lastNoise = 0;
    this.rms = [];
    this.idle = true;
    this.noiseDb = null;
    const resume = () => this.ctx?.state === 'suspended' && this.ctx.resume();
    addEventListener('pointerdown', resume);
    addEventListener('keydown', resume);
    requestAnimationFrame(t => this.tick(t));
  }

  attach(track) {
    this.src?.disconnect();
    this.ctx ??= new AudioContext();
    this.src = this.ctx.createMediaStreamSource(new MediaStream([track]));
    this.an = this.ctx.createAnalyser();
    this.an.fftSize = 2048;          // 43 ms window at 48 kHz, read every frame: no peak is missed
    this.buf = new Float32Array(this.an.fftSize);
    this.src.connect(this.an);
    this.rms = [];
    this.noiseDb = null;
    if (this.ctx.state === 'suspended') this.ctx.resume();   // may need a click; the listeners retry
  }

  /** Start counting take stats (clips, max peak); the noise floor freezes while recording. */
  beginTake() {
    this.idle = false;
    this.clips = 0;
    this.takePeak = -Infinity;
  }

  endTake() {
    this.idle = true;
    const r = (v, d = 1) => (Number.isFinite(v) ? +v.toFixed(d) : null);
    return { peak_dbfs: r(this.takePeak), clip_events: this.clips || 0, room_noise_dbfs: r(this.noiseDb) };
  }

  tick(now) {
    requestAnimationFrame(t => this.tick(t));
    if (!this.an) return;
    if (this.ctx.state !== 'running') {
      this.els.readout.textContent = 'Click anywhere to start the level meter';
      return;
    }
    this.an.getFloatTimeDomainData(this.buf);
    let peak = 0, sum = 0;
    for (const v of this.buf) {
      const a = Math.abs(v);
      if (a > peak) peak = a;
      sum += v * v;
    }
    const pDb = toDb(peak), rDb = toDb(Math.sqrt(sum / this.buf.length));
    const dt = Math.min(0.1, (now - (this.lastTick || now)) / 1000);
    this.lastTick = now;
    this.level = Math.max(pDb, this.level - RELEASE_DB_PER_S * dt, FLOOR_DB);
    if (pDb >= this.peak || now - this.peakAt > HOLD_MS) {
      this.peak = Math.max(pDb, this.level);
      this.peakAt = now;
    }
    if (pDb >= CLIP_DB) {
      if (!this.idle && now > this.clipUntil) this.clips += 1;   // count events, not frames
      this.clipUntil = now + CLIP_LIGHT_MS;
    }
    if (!this.idle) this.takePeak = Math.max(this.takePeak, pDb);
    if (this.idle && now - this.lastRms >= 50) {
      this.rms.push(rDb);
      if (this.rms.length > NOISE_WINDOW) this.rms.shift();
      this.lastRms = now;
    }
    this.render(now);
  }

  render(now) {
    const { mask, hold, clip, readout, noise } = this.els;
    mask.style.width = `${100 - pct(this.level)}%`;
    hold.style.left = `calc(${pct(this.peak)}% - 2px)`;
    clip.classList.toggle('on', now < this.clipUntil);
    if (now - this.lastText > 150) {
      this.lastText = now;
      const db = Math.round(this.peak);
      readout.textContent = `Peak ${this.peak > FLOOR_DB ? `${db > 0 ? '+' : ''}${db}` : '< −60'} dBFS`;
    }
    if (this.idle && now - this.lastNoise > 500 && this.rms.length >= 20) {
      this.lastNoise = now;
      // 10th percentile of short-term RMS: the floor between words, even if someone is talking.
      const sorted = [...this.rms].sort((a, b) => a - b);
      this.noiseDb = Math.max(-120, sorted[Math.floor(sorted.length * 0.1)]);
      const c = noiseClass(this.noiseDb);
      noise.textContent = `Room noise ${this.noiseDb <= -90 ? '< −90' : this.noiseDb.toFixed(0)} dBFS · ${c.text}`;
      noise.className = `readout ${c.level}`;
    }
  }
}

/** Exposure hint with the take QA's thresholds (full-range luma of the subject window: 60 / 200). */
export function exposureHint({ luma, hot }) {
  if (luma < 60) return { level: 'warn', text: 'too dark: add light in front of you' };
  if (luma > 200) return { level: 'warn', text: 'too bright: dim the light or move away from the window' };
  if (hot > 0.06) return { level: 'warn', text: 'highlights clipping: keep bright windows and lamps out of frame' };
  return { level: 'ok', text: 'good' };
}

// The subject window of the 9:16 crop (x0, y0, x1, y1), as takecheck.SUBJECT: exposure is judged
// on where the face sits, so a white wall or a dark room behind a well-lit face doesn't warn.
const SUBJECT = [0.25, 0.12, 0.75, 0.62];

/** Samples mean luma of the subject window (and the crop's clipped share) every 500 ms. */
export class ExposureMeter {
  constructor(video, getCrop, onUpdate) {
    this.c = Object.assign(document.createElement('canvas'), { width: 54, height: 96 });
    this.g = this.c.getContext('2d', { willReadFrequently: true });
    setInterval(() => this.sample(video, getCrop(), onUpdate), 500);
  }

  sample(video, crop, onUpdate) {
    if (!crop || video.readyState < 2 || document.hidden) return;
    const [x, y, w, h] = crop;
    const { width: W, height: H } = this.c;
    this.g.drawImage(video, x, y, w, h, 0, 0, W, H);   // raw frame: never affected by preview mirroring
    const px = this.g.getImageData(0, 0, W, H).data;
    const [x0, y0, x1, y1] = [SUBJECT[0] * W, SUBJECT[1] * H, SUBJECT[2] * W, SUBJECT[3] * H].map(Math.round);
    let sum = 0, inside = 0, hot = 0;
    for (let i = 0; i < px.length; i += 4) {
      const luma = 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2];   // BT.709, as encoded
      const col = (i / 4) % W, row = Math.floor(i / 4 / W);
      if (col >= x0 && col < x1 && row >= y0 && row < y1) {
        sum += luma;
        inside += 1;
      }
      if (luma >= 250) hot += 1;
    }
    onUpdate({ luma: sum / Math.max(1, inside), hot: hot / (px.length / 4) });
  }
}
