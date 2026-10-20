/** Cameras and mics: discovery, classification, native-format probing and remembered choices. */

// Same patterns the take QA uses (takecheck.py), so the studio warns about what QA will flag.
const VIRTUAL = /BlackHole|Zoom|Teams|Loom|Aggregate|Multi-Output|Virtual|Soundflower/i;
const BLUETOOTH = /AirPods|Bluetooth|Beats|Buds|Headset|Hands-?Free|Jabra|Bose|WH-1000|WF-1000/i;
const DESK_VIEW = /Desk View/i;
export const IPHONE = /iPhone|iPad/i;
const BUILT_IN = /MacBook|Built-in|Internal|iMac/i;
const PSEUDO_IDS = new Set(['default', 'communications']);   // Chrome's aliases of real devices
const STORE = 'reelStudio.v1';
const SIZES = {
  portrait: { width: { ideal: 1080 }, height: { ideal: 1920 } },
  landscape: { width: { ideal: 3840 }, height: { ideal: 2160 } },
};

// --- remembered choices (per browser; the studio works the same without them) ----------------

export function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(STORE)) || {};
  } catch {
    return {};
  }
}

export function savePrefs(patch) {
  try {
    localStorage.setItem(STORE, JSON.stringify({ ...loadPrefs(), ...patch }));
  } catch { /* storage blocked (private window): choices just aren't remembered */ }
}

// --- classification ---------------------------------------------------------------------------

/** "virtual" | "bluetooth" | "iphone" | "builtin" | "external" */
export function micKind(label = '') {
  if (VIRTUAL.test(label)) return 'virtual';
  if (BLUETOOTH.test(label)) return 'bluetooth';
  if (IPHONE.test(label)) return 'iphone';
  if (BUILT_IN.test(label)) return 'builtin';
  return 'external';
}

export function micWarning(label) {
  const kind = micKind(label);
  if (kind === 'virtual') return { level: 'fail', text: 'This is a virtual audio device, not a microphone: takes will be silent or carry another app’s audio. Pick a real mic.' };
  if (kind === 'bluetooth') return { level: 'warn', text: 'Bluetooth mic: low quality (narrow-band hands-free mode while it records). Use the MacBook, iPhone or a USB mic.' };
  return null;
}

/** Problems the browser reports after opening the mic (processing left on, narrow-band rate). */
export function micSettingsWarnings(s) {
  const out = [];
  const on = ['echoCancellation', 'noiseSuppression', 'autoGainControl'].filter(k => s[k] === true);
  if (on.length) out.push(`The browser kept ${on.join(', ')} on, which colours the voice.`);
  if (s.sampleRate && s.sampleRate < 44100) out.push(`The mic runs at ${s.sampleRate / 1000} kHz: expect dull, narrow-band audio.`);
  return out;
}

// --- 9:16 geometry (same rounding as capture.effective_9x16 on the server) --------------------

/** Largest 9:16 rectangle inside a WxH frame: what survives the reel's centre crop. */
export function effective9x16(w, h) {
  if (!w || !h) return [0, 0];
  return w * 16 > h * 9 ? [Math.floor(h * 9 / 16), h] : [w, Math.floor(w * 16 / 9)];
}

/** [x, y, w, h] of the centre 9:16 crop in frame pixels (the compiler uses object-fit: cover). */
export function cropRect(w, h) {
  const [cw, ch] = effective9x16(w, h);
  return [(w - cw) / 2, (h - ch) / 2, cw, ch];
}

/** Punch-ins need the 9:16 crop to be >= 1061 px wide: the compiler caps a punch at 1.10 x cropW / 1080 and
 *  switches punches off under 1.08 (council 3 + founder review: smaller punches read as wobble). A 1080p landscape webcam leaves a 607 px crop. */
export const PUNCH_MIN_W = 1061;
export function verdict(effW) {
  if (effW >= 1080) return { level: 'ok', text: 'Full HD 9:16' };
  if (effW >= PUNCH_MIN_W) return { level: 'warn', text: 'OK — slightly upscaled, punch-ins capped' };
  if (effW >= 720) return { level: 'warn', text: `Upscaled — no punch-ins (needs ${PUNCH_MIN_W} px of 9:16 width)` };
  return { level: 'fail', text: 'Low — no punch-ins' };
}

const area = ([w, h]) => w * h;

// --- opening devices --------------------------------------------------------------------------

export function stopStream(stream) {
  stream?.getTracks().forEach(t => t.stop());
}

export function describeMediaError(e, what = 'camera/microphone') {
  const name = e?.name || '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return `Access to the ${what} is blocked. Click the camera icon in the address bar, choose Allow, then reload. `
      + 'On macOS also allow Chrome in System Settings → Privacy & Security → Camera and Microphone.';
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return `${what} was not found: it may have been disconnected.`;
  if (name === 'NotReadableError' || name === 'AbortError') {
    return `${what} could not start. Another app (FaceTime, Zoom, Photo Booth, OBS…) may be using it: close it, then pick the device again.`;
  }
  return `${what}: ${e?.message || e}`;
}

/** {cams, mics} with labels. Desk View is hidden (it films the desk, not a face). */
export async function getDevices() {
  const md = navigator.mediaDevices;
  if (!md?.getUserMedia) {
    throw new Error('camera access needs a secure page: open the studio at http://127.0.0.1:<port>/ or http://localhost:<port>/');
  }
  let all = await md.enumerateDevices();
  const unlabelled = kind => all.some(d => d.kind === kind) && !all.some(d => d.kind === kind && d.label);
  if (unlabelled('videoinput') || unlabelled('audioinput')) {
    // Labels (needed to spot iPhone, Desk View and virtual mics) stay empty until permission is granted.
    stopStream(await md.getUserMedia({ video: unlabelled('videoinput'), audio: unlabelled('audioinput') }));
    all = await md.enumerateDevices();
  }
  return {
    cams: all.filter(d => d.kind === 'videoinput' && !DESK_VIEW.test(d.label)),
    mics: all.filter(d => d.kind === 'audioinput' && !PSEUDO_IDS.has(d.deviceId)),
  };
}

/** Open a camera at a native format near `mode` ("portrait" | "landscape"). */
export async function openCamera(deviceId, mode) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    // resizeMode "none": native camera formats only, never a browser rescale of a smaller mode.
    video: { deviceId: { exact: deviceId }, resizeMode: 'none', frameRate: { ideal: 30 }, ...SIZES[mode] },
  });
  const track = stream.getVideoTracks()[0];
  const settings = track.getSettings();
  return { stream, track, settings, mode, eff: effective9x16(settings.width, settings.height) };
}

/** Portrait first, then landscape max; keep the larger effective 9:16 area (portrait on a tie:
 *  every encoded pixel is then on screen). Each probe releases the camera so the next can pick
 *  another native format. */
async function probe(deviceId) {
  const p = await openCamera(deviceId, 'portrait');
  stopStream(p.stream);
  let l = null;
  try {
    l = await openCamera(deviceId, 'landscape');
    stopStream(l.stream);
  } catch { /* the landscape probe is optional: the portrait result stands */ }
  const best = l && area(l.eff) > area(p.eff) ? l : p;
  return { mode: best.mode, width: best.settings.width, height: best.settings.height, eff: best.eff };
}

export function cachedProfile(device) {
  return (loadPrefs().profiles || {})[device.deviceId] || null;
}

export async function cameraProfile(device, fresh = false) {
  const cached = !fresh && cachedProfile(device);
  if (cached) return cached;
  const prof = await probe(device.deviceId);
  savePrefs({ profiles: { ...(loadPrefs().profiles || {}), [device.deviceId]: prof } });
  return prof;
}

/** Open a camera in its best 9:16 mode (profiled once, then remembered). */
export async function openBestCamera(device) {
  let prof = await cameraProfile(device);
  let cam = await openCamera(device.deviceId, prof.mode);
  if (area(cam.eff) < area(prof.eff)) {   // the camera changed since it was profiled: measure again
    stopStream(cam.stream);
    prof = await cameraProfile(device, true);
    cam = await openCamera(device.deviceId, prof.mode);
  }
  return cam;
}

/** Default camera: highest effective 9:16 area, tie → iPhone. Cameras that fail to open are
 *  reported in `skipped` (e.g. busy in another app), not silently ignored. */
export async function defaultCamera(cams) {
  let best = null;
  const skipped = [];
  for (const d of cams) {
    try {
      const prof = await cameraProfile(d);
      const a = area(prof.eff), b = best ? area(best.prof.eff) : -1;
      if (a > b || (a === b && IPHONE.test(d.label) && !IPHONE.test(best.d.label))) best = { d, prof };
    } catch (e) {
      skipped.push(describeMediaError(e, d.label || 'a camera'));
    }
  }
  return { device: best?.d || null, skipped };
}

/** Default mic: first real external/USB mic, else the chosen iPhone's mic, else the MacBook mic.
 *  Never a virtual device; Bluetooth only as a last resort (it is warned about). */
export function defaultMic(mics, cam) {
  const real = mics.filter(m => !['virtual', 'bluetooth'].includes(micKind(m.label)));
  const external = real.find(m => micKind(m.label) === 'external');
  if (external) return external;
  if (cam && IPHONE.test(cam.label)) {
    const owner = cam.label.replace(/\s*Camera.*$/i, '');
    const phones = real.filter(m => micKind(m.label) === 'iphone');
    const phone = phones.find(m => m.label.startsWith(owner)) || phones[0];
    if (phone) return phone;
  }
  return real.find(m => /MacBook/i.test(m.label)) || real.find(m => micKind(m.label) === 'builtin')
    || real[0] || mics.find(m => micKind(m.label) === 'bluetooth') || null;
}

/** Open a mic with every browser voice process off: the teleprompter has no far-end audio to
 *  cancel, and AGC/noise suppression pump and smear a voice take. */
export async function openMic(deviceId) {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: false,
    audio: {
      deviceId: { exact: deviceId },
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      voiceIsolation: false,          // ignored where unsupported
      sampleRate: { ideal: 48000 },
      channelCount: { ideal: 1 },
    },
  });
  const track = stream.getAudioTracks()[0];
  return { stream, track, settings: track.getSettings() };
}
