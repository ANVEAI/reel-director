/** Reel Director Studio entry: the record flow (countdown → record → stop → upload), keyboard,
 *  live sensors, the automation test hook, and start-up. */
import { initBroll } from './broll.js';
import { initBuild, updateBuildButton } from './build.js';
import { setPickersBusy, startDevices } from './devicepanel.js';
import { micKind, savePrefs } from './devices.js';
import { $, clock, num } from './dom.js';
import { AudioMeter, ExposureMeter, exposureHint } from './meters.js';
import { FaceHint, Stage } from './overlay.js';
import { AUDIO_BPS, TIMESLICE_MS, TakeRecorder, extFor } from './recorder.js';
import { S, shotById } from './state.js';
import { cancelAdvance, queueUpload, refreshProject, renderSidebar, showVerdict, stepShot, selectShot, stopPlayer, wireShotList } from './takes.js';
import { banner, bannerTexts, toast } from './ui.js';

// The recorder starts on the countdown's "1", a second before the creator speaks, so the first
// word can never be clipped by recorder start-up latency; prep trims the lead-in anyway.
const LEAD_IN = 1;
const TEXT_INPUT = /^(text|search|email|number|password|tel|url|date|time|datetime-local|month|week)$/;

const video = $('preview'), recBtn = $('rec-btn');
const stage = new Stage($('stage'), video, $('overlay'));
const meter = new AudioMeter({ mask: $('meter-mask'), hold: $('meter-hold'), clip: $('clip'), readout: $('meter-read'), noise: $('noise') });
const face = new FaceHint();
let countTimer = null, tickTimer = null, recStart = 0;

// --- recording state --------------------------------------------------------------------------

function setRec(state) {
  S.rec = state;
  document.body.dataset.rec = state;
  recBtn.textContent = { idle: 'Record', countdown: 'Cancel', recording: 'Stop', stopping: 'Saving…' }[state];
  recBtn.disabled = state === 'stopping';
  $('rec-badge').hidden = $('rec-pill').hidden = state !== 'recording';
  if (state === 'recording') {
    stage.setFace(null);
    $('face-hint').hidden = true;
  }
  setPickersBusy(false);
  renderSidebar();
  updateBuildButton();
}

function recordBlocker() {
  if (S.cam?.track.readyState !== 'live') return 'no camera is running';
  if (S.mic?.track.readyState !== 'live') return 'no microphone is running';
  if (!shotById(S.shot)) return 'no shot is selected';
  if (S.mime === null) return 'this browser has no MediaRecorder';
  if (S.build?.state === 'running') return 'a reel is building (it would compete with the camera encoder): wait for it';
  return '';
}

/** Record looks unavailable, and says why, whenever a new take couldn't start. */
function updateRecordButton() {
  const why = S.rec === 'idle' ? recordBlocker() : '';
  recBtn.disabled = S.rec === 'stopping' || !!why;
  recBtn.title = why ? `Can't record: ${why}` : '';
  const el = $('rec-why');
  if (el.textContent !== why) el.textContent = why ? `Can't record: ${why}.` : '';
}

function toggleRecord() {
  if (S.rec === 'idle') startCountdown();
  else if (S.rec === 'countdown') cancelCountdown();
  else if (S.rec === 'recording') stopRecording();
}

function startCountdown() {
  const why = recordBlocker();
  if (why) return toast(`Can't record: ${why}`, 'fail');
  cancelAdvance();
  showVerdict('');               // the countdown takes its place under the lens
  if (S.playing) stopPlayer();   // playback would leak into the mic
  setRec('countdown');
  let n = 3;
  showCount(n);
  countTimer = setInterval(() => {
    n -= 1;
    if (n === LEAD_IN && !beginRecorder()) return;
    if (n > 0) return showCount(n);
    clearInterval(countTimer);
    showCount(0);
    goLive();
  }, 1000);
}

function showCount(n) {
  const el = $('countdown'), pill = $('count-pill');
  el.hidden = pill.hidden = n <= 0;
  pill.textContent = `Recording in ${n}…`;
  el.textContent = n;
  el.classList.remove('tick');
  void el.offsetWidth;   // restart the pop animation
  el.classList.add('tick');
}

/** Sent as X-Capture-Info: device labels, live track settings, format and bitrates. */
function captureInfo() {
  return {
    source: 'record', shot: S.shot,
    video: { label: S.camDev.label, mode: S.cam.mode, settings: S.cam.track.getSettings(), effective_9x16: S.cam.eff },
    audio: { label: S.micDev.label, kind: micKind(S.micDev.label), settings: S.mic.track.getSettings() },
    mime: S.mime, videoBitsPerSecond: S.vbps, audioBitsPerSecond: AUDIO_BPS, timeslice_ms: TIMESLICE_MS,
    lead_in_s: LEAD_IN, preview_mirrored: S.prefs.mirror, recording_mirrored: false,
    user_agent: navigator.userAgent, started_at: new Date().toISOString(),
  };
}

function beginRecorder() {
  try {
    // The raw camera track: preview mirroring is CSS on the <video>, so the take is never mirrored.
    const r = new TakeRecorder(new MediaStream([S.cam.track, S.mic.track]), S.mime, S.vbps);
    r.info = captureInfo();
    r.onError = e => {
      banner(`Recorder error: ${e.message}`);
      if (S.rec === 'recording') stopRecording();
    };
    r.start();
    Object.assign(S, { recorder: r, recShot: S.shot });
    meter.beginTake();
    return true;
  } catch (e) {
    cancelCountdown();
    banner(`Recording could not start: ${e.message}`);
    return false;
  }
}

function goLive() {
  setRec('recording');
  recStart = performance.now();
  const est = shotById(S.recShot)?.estimate_s || 0;
  $('rec-est').textContent = est ? `/ ~${num(est, 1)} s` : '';
  const show = () => {
    const t = (performance.now() - recStart) / 1000;
    $('rec-time').textContent = $('rec-pill-time').textContent = clock(t);
    $('rec-badge').classList.toggle('over', est > 0 && t > 3 * est);   // QA warns past 3x the read
  };
  show();
  tickTimer = setInterval(show, 100);
}

/** Stop and throw away the countdown or take in progress. */
function cancelCountdown() {
  clearInterval(countTimer);
  clearInterval(tickTimer);
  showCount(0);
  S.recorder?.abort();
  S.recorder = null;
  meter.endTake();
  setRec('idle');
}

async function stopRecording() {
  const r = S.recorder;
  if (!r || S.rec !== 'recording') return;
  clearInterval(tickTimer);
  const seconds = (performance.now() - recStart) / 1000;
  setRec('stopping');
  const levels = meter.endTake();
  try {
    const blob = await r.stop();   // resolves after the final dataavailable
    const info = { ...r.info, mime: r.mimeType, duration_s: +(seconds + LEAD_IN).toFixed(2), spoken_window_s: +seconds.toFixed(2), levels };
    queueUpload({ shot: S.recShot, source: 'record', ext: extFor(r.mimeType), blob, info });
    if (levels.clip_events) toast(`The mic clipped ${levels.clip_events}× in that take: lower the input level or move back a little.`, 'warn', 7000);
  } catch (e) {
    banner(`Recording failed: ${e.message}`);
  } finally {
    S.recorder = null;
    setRec('idle');
  }
}

/** R: set the take in progress aside and count in again on the same shot. The bytes are never
 *  dropped: the take uploads and is discarded at once, so it lands in raw/discarded/ (recoverable)
 *  without competing for the reel. During the countdown only the lead-in exists, so it is aborted.
 *  From idle R does nothing, so it can't be learned as a record / stop toggle. */
function restartTake() {
  if (S.rec === 'stopping') return;
  if (S.rec === 'idle') return toast('R starts over a take in progress. Press Space to record.');
  if (S.rec === 'recording' && S.recorder) {
    const r = S.recorder, shot = S.recShot, seconds = (performance.now() - recStart) / 1000;
    r.onError = null;     // a late error must not stop the next take
    S.recorder = null;    // so cancelCountdown() doesn't abort() it
    cancelCountdown();
    r.stop().then(blob => queueUpload({ shot, source: 'record', ext: extFor(r.mimeType), blob, setAside: true,
      info: { ...r.info, mime: r.mimeType, duration_s: +(seconds + LEAD_IN).toFixed(2), restarted: true } }))
      .catch(e => banner(`The take you started over could not be kept: ${e.message}`));
    toast('Take set aside in raw/discarded/: counting in again');
  } else {
    cancelCountdown();
  }
  startCountdown();
}

// --- keyboard + wiring ------------------------------------------------------------------------

function isTyping(t) {
  if (!(t instanceof HTMLElement)) return false;
  if (t.isContentEditable || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') return true;
  return t.tagName === 'INPUT' && TEXT_INPUT.test(t.type);
}

/** A control focused from the keyboard keeps its own Space (toggle a checkbox, press a button).
 *  Clicked controls are blurred right away, so for mouse users Space stays record / stop. */
const NATIVE_SPACE = 'button, select, summary, a[href], input[type="checkbox"], input[type="radio"]';
const nativeSpace = t => t instanceof Element && t !== recBtn && t.matches(NATIVE_SPACE);

function onKey(e) {
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || e.isComposing || isTyping(e.target)) return;
  if ($('reel-dialog').open) return;
  if (e.key === ' ' && nativeSpace(e.target)) return;
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  const act = {
    ' ': toggleRecord, n: () => stepShot(1), ArrowRight: () => stepShot(1), p: () => stepShot(-1),
    ArrowLeft: () => stepShot(-1), r: restartTake, Escape: () => S.rec === 'countdown' && cancelCountdown(),
  }[k];
  if (!act) return;
  e.preventDefault();   // also stops Space from scrolling or "clicking" a focused button
  if (!e.repeat) act();
}

function wire() {
  addEventListener('keydown', onKey);
  // The Record button would also click on Space keyup: Space already toggled recording on keydown.
  addEventListener('keyup', e => {
    if (e.key === ' ' && !isTyping(e.target) && !nativeSpace(e.target) && !$('reel-dialog').open) e.preventDefault();
  });
  recBtn.addEventListener('click', () => {
    recBtn.blur();
    toggleRecord();
  });
  for (const [id, key] of [['mirror', 'mirror'], ['auto-advance', 'autoAdvance']]) {
    const box = $(id);
    box.checked = S.prefs[key];
    box.addEventListener('change', () => {
      S.prefs[key] = box.checked;
      savePrefs({ ui: S.prefs });
      stage.setMirror(S.prefs.mirror);
      box.blur();
    });
  }
  wireShotList();
  addEventListener('focus', () => S.rec === 'idle' && refreshProject());
  addEventListener('beforeunload', e => {
    if (S.rec === 'idle' && !S.uploads.length) return;
    e.preventDefault();   // unsent takes live only in this tab
    e.returnValue = '';
  });
  addEventListener('error', e => {
    // Third-party code (the optional MediaPipe hint) and Chrome's benign ResizeObserver notice stay in the console.
    if (/ResizeObserver loop/.test(e.message) || (e.filename && !e.filename.startsWith(location.origin))) return;
    banner(`Unexpected error: ${e.message}`);
  });
  addEventListener('unhandledrejection', e => banner(`Unexpected error: ${e.reason?.message || e.reason}`));
}

function startSensors() {
  new ExposureMeter(video, () => stage.box?.crop, r => {
    const hint = exposureHint(r), el = $('exposure');
    el.textContent = `Brightness ${Math.round(r.luma)} / 255 · ${hint.text}`;
    el.className = `readout ${hint.level}`;
  });
  face.load().then(ok => {
    if (!ok) return;   // offline or CDN blocked: the hint simply stays hidden
    setInterval(() => {
      if (S.rec === 'recording' || document.hidden || !S.cam) return;   // never compete with the encoder
      const f = face.detect(video, stage.box?.crop);
      stage.setFace(f);
      const el = $('face-hint');
      el.hidden = !f;
      if (f) {
        el.textContent = f.hint;
        el.className = `face-hint ${f.good ? 'ok' : 'warn'}`;
      }
    }, 250);
  });
}

// Test hook for automation (tests/e2e): read-only state plus shot selection.
window.__studio = {
  state: () => ({
    shot: S.shot,
    recording: S.rec,   // "idle" | "countdown" | "recording" | "stopping"
    ready: S.cam?.track.readyState === 'live' && S.mic?.track.readyState === 'live',
    camera: S.cam && { id: S.camDev.deviceId, label: S.camDev.label, mode: S.cam.mode, settings: S.cam.track.getSettings(), effective_9x16: S.cam.eff },
    mic: S.mic && { id: S.micDev.deviceId, label: S.micDev.label, kind: micKind(S.micDev.label), settings: S.mic.track.getSettings() },
    mime: S.mime, videoBitsPerSecond: S.vbps, audioBitsPerSecond: AUDIO_BPS,
    uploads: S.uploads.map(u => ({ shot: u.shot, state: u.state, progress: u.progress, error: u.error })),
    lastTake: S.lastTake,
    build: S.build?.state || 'idle',
    errors: bannerTexts(),
  }),
  selectShot: id => selectShot(id),
};

async function init() {
  initBuild({
    button: $('build-btn'), why: $('build-why'), steps: $('build-steps'), state: $('build-state'), log: $('build-log'),
    open: $('reel-open'), dialog: $('reel-dialog'), video: $('reel-video'), stats: $('reel-stats'), shots: $('reel-shots'),
  });
  initBroll();          // v4: the B-roll panel (media picks, licences, paid approvals)
  wire();
  setRec('idle');
  setInterval(updateRecordButton, 500);   // camera, mic, shot and build state all change elsewhere
  stage.setMirror(S.prefs.mirror);
  startSensors();
  await refreshProject();
  await startDevices({
    meter,
    onLost: () => (S.rec === 'recording' ? stopRecording() : S.rec === 'countdown' && cancelCountdown()),
  });
}

init();
