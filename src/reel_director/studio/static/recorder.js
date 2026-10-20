/** MediaRecorder setup: best container/codec, bitrate from frame size, and a stop() that never
 *  drops the last chunk. */

// avc3 first: parameter sets travel in-band, so a mid-take encoder restart (the camera changing
// resolution) doesn't corrupt the rest of the take as avc1 does; Chrome warns about exactly that.
// avc1 stays as the fallback for browsers without avc3 (Safari).
export const MIMES = [
  'video/mp4;codecs=avc3.640033,mp4a.40.2',
  'video/mp4;codecs=avc3,mp4a.40.2',
  'video/mp4;codecs=avc1.640033,mp4a.40.2',
  'video/mp4;codecs=avc1,mp4a.40.2',
  'video/mp4',
  'video/webm;codecs=h264,opus',
  'video/webm;codecs=vp9,opus',
  'video/webm',
];
export const AUDIO_BPS = 256000;
export const TIMESLICE_MS = 1000;
const FINAL_CHUNK_WAIT_MS = 1500;

/** First supported mime; '' lets the browser choose; null when MediaRecorder is missing. */
export function pickMime() {
  if (!window.MediaRecorder) return null;
  return MIMES.find(m => MediaRecorder.isTypeSupported(m)) ?? '';
}

/** clamp(W*H*fps*0.30, 8, 40 Mbps): generous, since the server re-encodes at CRF 14 anyway. */
export function videoBitrate(w, h, fps) {
  return Math.round(Math.min(40e6, Math.max(8e6, w * h * (fps || 30) * 0.30)));
}

export const extFor = mime => (/mp4/i.test(mime) ? 'mp4' : 'webm');

export function mimeLabel(mime) {
  if (!mime) return 'browser default format';
  const video = /avc[13]\.64/i.test(mime) ? 'H.264 High' : /avc[13]|h264/i.test(mime) ? 'H.264'
    : /vp9/i.test(mime) ? 'VP9' : /vp8/i.test(mime) ? 'VP8' : '';
  const audio = /mp4a/i.test(mime) ? 'AAC' : /opus/i.test(mime) ? 'Opus' : '';
  return [extFor(mime).toUpperCase(), video, audio].filter(Boolean).join(' · ');
}

export class TakeRecorder {
  constructor(stream, mime, videoBitsPerSecond) {
    this.chunks = [];
    this.chosenMime = mime;
    this.rec = new MediaRecorder(stream, {
      ...(mime ? { mimeType: mime } : {}), videoBitsPerSecond, audioBitsPerSecond: AUDIO_BPS,
    });
    this.rec.addEventListener('dataavailable', e => {
      if (this.discarded) return;
      if (e.data?.size) this.chunks.push(e.data);
      if (this.stopping) this.onFinal();
    });
    this.rec.addEventListener('stop', () => { this.ended = true; });
    this.rec.addEventListener('error', e => this.onError?.(e.error || new Error('MediaRecorder error')));
  }

  get mimeType() {
    return this.rec.mimeType || this.chosenMime || 'video/webm';
  }

  start() {
    this.rec.start(TIMESLICE_MS);
  }

  /** Resolves the whole take as one Blob, built only after the final dataavailable. */
  stop() {
    if (this.done) return this.done;
    this.done = new Promise((resolve, reject) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        if (this.chunks.length) resolve(new Blob(this.chunks, { type: this.mimeType }));
        else reject(new Error('the recorder produced no data'));
      };
      let gotFinal = false;
      this.onFinal = () => { gotFinal = true; };
      const afterStop = () => {
        // Spec order is dataavailable then stop, but wait briefly if a browser delivers it late.
        if (gotFinal) finish();
        else {
          this.onFinal = finish;
          setTimeout(finish, FINAL_CHUNK_WAIT_MS);
        }
      };
      // Already stopped (recorder error or every track ended): nothing more will arrive.
      if (this.ended || this.rec.state === 'inactive') finish();
      else this.rec.addEventListener('stop', afterStop, { once: true });
    });
    this.stopping = true;
    if (this.rec.state !== 'inactive') this.rec.stop();
    return this.done;
  }

  /** Stop and throw the take away (countdown cancelled or take restarted). */
  abort() {
    this.onError = null;
    this.discarded = true;
    this.chunks = [];
    if (this.rec.state !== 'inactive') this.rec.stop();
  }
}
