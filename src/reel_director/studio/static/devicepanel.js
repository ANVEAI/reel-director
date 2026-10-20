/** Camera + mic pickers: open the best devices, show their real formats and warnings, follow
 *  hot-plugging (iPhone walking away, USB mic plugged in). Also reads the creator profile that
 *  `learn creator` writes (qa/creator.json): its framing numbers tune the coach, its top tip shows here. */
import {
  IPHONE, cachedProfile, defaultCamera, defaultMic, describeMediaError, getDevices, loadPrefs, micKind,
  micSettingsWarnings, micWarning, openBestCamera, openMic, savePrefs, stopStream, verdict,
} from './devices.js';
import { getCreator } from './api.js';
import { $, h, num } from './dom.js';
import { setCoachProfile } from './overlay.js';
import { AUDIO_BPS, mimeLabel, pickMime, videoBitrate } from './recorder.js';
import { S } from './state.js';
import { badge, banner, clearBanner, showNote, stageMsg, toast } from './ui.js';

const video = $('preview'), camSel = $('cam-select'), micSel = $('mic-select');
let hooks = { meter: null, onLost: () => {} };
let devTimer = null;
let creatorTip = '';   // the creator profile's most useful tip ("From your last takes: …"), if there is one

const findDevice = (list, saved) => saved && (list.find(d => d.deviceId === saved.id) || list.find(d => d.label === saved.label));

function remember(kind, dev) {
  savePrefs({ devices: { ...loadPrefs().devices, [kind]: { id: dev.deviceId, label: dev.label } } });
}

/** opts: {meter: AudioMeter, onLost(): stop or cancel a take when a device disappears} */
export async function startDevices(opts) {
  hooks = opts;
  loadCreatorProfile();   // not awaited: optional, never delays the camera
  camSel.addEventListener('change', () => pick(camSel, S.cams, useCamera));
  micSel.addEventListener('change', () => pick(micSel, S.mics, useMic));
  try {
    ({ cams: S.cams, mics: S.mics } = await getDevices());
  } catch (e) {
    banner(describeMediaError(e), 'devices');
    stageMsg('No camera access');
    camSel.replaceChildren(new Option('Camera blocked', ''));
    micSel.replaceChildren(new Option('Microphone blocked', ''));
    // Once access is allowed (address bar), start over: nothing was recorded yet, so a reload is safe.
    for (const name of ['camera', 'microphone']) {
      navigator.permissions?.query({ name })
        .then(st => { st.onchange = () => st.state === 'granted' && location.reload(); })
        .catch(() => { /* this browser can't watch the permission: the banner says to reload */ });
    }
    return;
  }
  navigator.mediaDevices.addEventListener('devicechange', () => {
    clearTimeout(devTimer);
    devTimer = setTimeout(onDeviceChange, 400);
  });
  if (!S.cams.length) banner('No camera found. Connect one (or bring your iPhone close for Continuity Camera): the list updates by itself.', 'camera');
  if (!S.mics.length) banner('No microphone found. Connect one: the list updates by itself.', 'mic');
  const saved = loadPrefs().devices || {};
  let cam = findDevice(S.cams, saved.camera);   // only explicit choices are saved, so a better new camera still wins
  if (!cam && S.cams.length) {
    stageMsg('Finding the camera with the best 9:16 picture…');
    const r = await defaultCamera(S.cams);
    r.skipped.forEach(m => banner(m));
    cam = r.device;
  }
  if (cam) await useCamera(cam, false);
  else stageMsg('No camera');
  const mic = findDevice(S.mics, saved.mic) || defaultMic(S.mics, S.camDev);
  if (mic) await useMic(mic, false);
  else if (S.mics.length) banner('Only virtual audio devices were found (BlackHole, Zoom, Teams, Loom…). Connect a real microphone or choose one by hand.', 'mic');
  renderPickers();
}

function pick(sel, list, use) {
  const d = list.find(x => x.deviceId === sel.value);
  sel.blur();   // a focused select would swallow Space and the arrow keys
  if (d) use(d, true);
}

async function useCamera(dev, chosen) {
  if (S.rec !== 'idle') return toast('Finish the take before switching camera');
  stopStream(S.cam?.stream);
  S.cam = null;
  video.srcObject = null;
  clearBanner('camera');
  stageMsg(`Opening ${dev.label || 'camera'}…`);
  setPickersBusy(true);
  try {
    const cam = await openBestCamera(dev);
    Object.assign(S, { cam, camDev: dev });
    cam.track.addEventListener('ended', () => trackEnded('Camera', dev));
    video.srcObject = cam.stream;
    if (chosen) remember('camera', dev);
    showCamera();
    stageMsg('');
  } catch (e) {
    banner(describeMediaError(e, dev.label || 'camera'), 'camera');
    stageMsg('Camera unavailable');
  } finally {
    setPickersBusy(false);
    renderPickers();
  }
}

function showCamera() {
  const s = S.cam.settings, [ew, eh] = S.cam.eff, v = verdict(ew), fps = Math.round(s.frameRate || 0);
  S.mime = pickMime();
  S.vbps = videoBitrate(s.width, s.height, fps);
  $('cam-badges').replaceChildren(badge(`${s.width}×${s.height} native`), badge(`${fps || '?'} fps`, fps && fps < 24 ? 'warn' : ''),
    badge(`9:16 ${ew}×${eh}`), badge(v.text, v.level));
  $('fmt').textContent = S.mime === null ? 'This browser cannot record (no MediaRecorder)'
    : `Records ${mimeLabel(S.mime)} · ${num(S.vbps / 1e6, 1)} Mbps video · ${AUDIO_BPS / 1000} kbps audio · never mirrored`;
  if (S.mime === null) banner('This browser has no MediaRecorder: record in Chrome (Import still works here).', 'recorder');
  const tip = v.level === 'ok' ? ''
    : IPHONE.test(S.camDev.label)
      ? 'Continuity Camera is landscape-only, so the 9:16 crop is upscaled. For full 1080×1920, film in the iPhone Camera app (portrait, 4K) and use Import.'
      : 'The 9:16 crop is narrower than 1080 px and will be upscaled. A portrait-capable or 4K camera gives a sharper reel.';
  showNote($('cam-note'), [tip, creatorTip].filter(Boolean).join(' '), v.level === 'ok' ? '' : v.level);
}

/** GET /api/creator (qa/creator.json, refreshed by the studio after each take's check): tune the framing
 *  coach and surface one tip. Null until a take is checked; any failure leaves the defaults. */
export async function loadCreatorProfile() {
  try {
    const p = (await getCreator())?.profile;
    if (!p) return;
    setCoachProfile(p?.coach);
    const tips = Array.isArray(p?.tips) ? p.tips : [];
    const t = tips.find(x => x.level === 'fix') || tips.find(x => x.level === 'nudge');
    creatorTip = typeof t?.text === 'string' ? `From your last takes: ${t.text}` : '';
    if (creatorTip && S.cam) showCamera();
  } catch { /* no profile, or not JSON: the coach keeps its defaults */ }
}

async function useMic(dev, chosen) {
  if (S.rec !== 'idle') return toast('Finish the take before switching microphone');
  stopStream(S.mic?.stream);
  S.mic = null;
  clearBanner('mic');
  setPickersBusy(true);
  try {
    const mic = await openMic(dev.deviceId);
    Object.assign(S, { mic, micDev: dev });
    mic.track.addEventListener('ended', () => trackEnded('Microphone', dev));
    if (chosen) remember('mic', dev);
    showMic();
    hooks.meter.attach(mic.track);
  } catch (e) {
    banner(S.mic ? `Level meter unavailable: ${e.message}` : describeMediaError(e, dev.label || 'microphone'), 'mic');
  } finally {
    setPickersBusy(false);
    renderPickers();
  }
}

function showMic() {
  const s = S.mic.settings, w = micWarning(S.micDev.label);
  const notes = [w?.text, ...micSettingsWarnings(s)].filter(Boolean);
  showNote($('mic-warn'), notes.join(' '), w?.level || (notes.length ? 'warn' : ''));
  if (w?.level === 'fail') banner(`${S.micDev.label}: ${w.text}`, 'mic');   // virtual device: warn loudly
  const raw = !['echoCancellation', 'noiseSuppression', 'autoGainControl'].some(k => s[k] === true);
  $('mic-badges').replaceChildren(badge(s.sampleRate ? `${s.sampleRate / 1000} kHz` : 'rate ?'),
    badge(`${s.channelCount || '?'} ch`), badge(raw ? 'no browser processing' : 'processing on', raw ? 'ok' : 'warn'));
}

export function setPickersBusy(busy) {
  camSel.disabled = micSel.disabled = busy || S.rec !== 'idle';
}

function fillSelect(sel, list, current, label) {
  const opts = list.map(d => h('option', { value: d.deviceId }, label(d)));
  if (!current) opts.unshift(h('option', { value: '', disabled: true }, list.length ? 'Choose…' : 'None found'));
  sel.replaceChildren(...opts);
  sel.value = current?.deviceId || '';
}

function renderPickers() {
  fillSelect(camSel, S.cams, S.cam ? S.camDev : null, d => {
    const p = cachedProfile(d);
    return `${d.label || 'Camera'}${p ? ` — 9:16 ${p.eff[0]}×${p.eff[1]}` : ''}`;
  });
  fillSelect(micSel, S.mics, S.mic ? S.micDev : null, d =>
    `${d.label || 'Microphone'}${{ virtual: ' — virtual, not a mic', bluetooth: ' — Bluetooth, low quality' }[micKind(d.label)] || ''}`);
}

async function onDeviceChange() {
  let list;
  try {
    list = await getDevices();
  } catch (e) {
    return banner(describeMediaError(e), 'devices');
  }
  list.cams.filter(d => !S.cams.some(c => c.deviceId === d.deviceId)).forEach(d => toast(`Camera connected: ${d.label}`));
  list.mics.filter(d => !S.mics.some(m => m.deviceId === d.deviceId)).forEach(d => toast(`Microphone connected: ${d.label}`));
  Object.assign(S, list);
  if (S.rec === 'idle' && !S.cam && S.cams.length) {
    const r = await defaultCamera(S.cams);
    if (r.device) await useCamera(r.device, false);
  }
  if (S.rec === 'idle' && !S.mic) {
    const m = defaultMic(S.mics, S.camDev);
    if (m) await useMic(m, false);
  }
  renderPickers();
}

function trackEnded(kind, dev) {
  banner(`${kind} “${dev.label}” stopped (unplugged, or taken by another app). Choose it again or pick another.`,
    kind === 'Camera' ? 'camera' : 'mic');
  hooks.onLost();   // keeps what was recorded so far; QA will judge it
  if (kind === 'Camera') {
    S.cam = null;
    stageMsg('Camera disconnected');
  } else S.mic = null;
  renderPickers();
}
