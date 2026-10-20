/** Project snapshot and polling, shot selection, the shot list, take actions, imports and uploads. */
import { getProject, mediaUrl, takeAction, uploadTake } from './api.js';
import { applyBuild, updateBuildButton } from './build.js';
import { $, h } from './dom.js';
import { fitPrompter, renderShots, setPrompter, shotReadiness, takeReason, takeVerdict, updateUploadProgress } from './shots.js';
import { S, allTakes, shotById } from './state.js';
import { banner, clearBanner, toast } from './ui.js';

const ADVANCE_MS = 1500;
const POLL_MS = 1000;
const IDLE_POLL_MS = 5000;    // takes changed from another tab or the API show up without a reload
const IMPORT_EXT = { mp4: 'mp4', m4v: 'mp4', mov: 'mov', qt: 'mov', webm: 'webm' };
const list = $('shots');
const prompter = { pos: $('shot-pos'), line: $('line'), cues: $('cues') };
const player = h('video', { class: 'take-player', controls: true, playsinline: true, preload: 'auto' });
const statuses = new Map();   // take name -> last seen status, to notice QA results arriving
let projTimer = null, projSeq = 0, advanceTimer = null, uploadSeq = 0, sidebarSig = '';

// --- project snapshot -------------------------------------------------------------------------

/** Reload /api/project; keeps polling every second while any take is still being checked. */
export async function refreshProject() {
  clearTimeout(projTimer);
  const seq = ++projSeq;
  try {
    const p = await getProject();
    if (seq !== projSeq) return;     // a newer refresh already landed
    if (serverRestarted(p)) return;
    S.project = p;
    clearBanner('server');
    onProject();
  } catch (e) {
    banner(`Can't load the project: ${e.message}. Retrying…`, 'server');
    projTimer = setTimeout(refreshProject, 3000);
    return;
  }
  clearTimeout(projTimer);
  const checking = allTakes().some(t => t.status === 'checking');
  projTimer = setTimeout(refreshProject, checking ? POLL_MS : IDLE_POLL_MS);
}

/** The studio server was restarted under this tab: reload when nothing would be lost, else ask.
 *  (A tab kept from before a restart can hold a poll or upload that died with the old server.) */
function serverRestarted(p) {
  const was = S.project?.boot;
  if (!was || !p.boot || p.boot === was) return false;
  if (S.rec === 'idle' && !S.uploads.length) {
    location.reload();
    return true;
  }
  banner('The studio server restarted. Finish or save this take, then reload the page (Cmd+R).', 'server');
  return false;
}

function onProject() {
  const p = S.project;
  $('title').textContent = p.title;
  document.title = `${p.title} · Studio`;
  if (p.script_error) banner(`script.json has an error, so the studio keeps the last good version: ${p.script_error}`, 'script');
  else clearBanner('script');
  for (const s of p.shots) {
    for (const t of s.takes || []) {
      if (statuses.get(t.name) === 'checking' && t.status !== 'checking') qaArrived(s, t);
      statuses.set(t.name, t.status);
    }
  }
  if (!shotById(S.shot)) selectShot(nextEmptyShot(null) || p.shots[0]?.id);
  if (!S.build) applyBuild(p.build || null, false);   // later changes come from polling /api/build
  const ready = p.shots.filter(s => shotReadiness(s) === 'ready').length;
  const retake = p.shots.filter(s => shotReadiness(s) === 'retake').length;
  $('summary').textContent = `${ready} / ${p.shots.length} shots ready${retake ? ` · ${retake} need${retake === 1 ? 's' : ''} a retake` : ''}`
    + ` · ${allTakes().length} take(s)`;
  renderSidebar();
  updateBuildButton();
}

function qaArrived(shot, t) {
  if (t.status === 'error') {
    banner(`Quality check failed for ${t.name}: ${takeReason(t)}`, `qa-${t.name}`);
    return;
  }
  const v = takeVerdict(t), why = takeReason(t);
  toast(`${t.name}: ${v}${why ? ` — ${why}` : ''}`, { great: 'ok', ok: 'warn' }[v] || 'fail', 7000);
  showVerdict(`${t.name}: ${v.toUpperCase()}${why ? ` — ${why}` : v === 'great' ? ' — nice read' : ''}`, v);
  if (v === 'great' && S.prefs.autoAdvance && t.name === S.lastTake && shot.id === S.shot && S.rec === 'idle') {
    clearTimeout(advanceTimer);
    advanceTimer = setTimeout(() => {
      const next = S.rec === 'idle' && S.shot === shot.id && nextEmptyShot(shot.id);
      if (next) selectShot(next);
    }, ADVANCE_MS);
  }
}

/** The QA verdict in the teleprompter header, right under the lens, for a few seconds. */
let verdictTimer = null;
export function showVerdict(text, v) {
  const el = $('verdict-pill');
  clearTimeout(verdictTimer);
  el.hidden = !text;
  if (!text) return;
  el.textContent = text;
  el.title = text;
  el.className = `verdict-pill ${v}`;
  verdictTimer = setTimeout(() => { el.hidden = true; }, 10000);
}

/** Next shot (wrapping) with no take and no upload in flight. */
function nextEmptyShot(fromId) {
  const shots = S.project?.shots || [];
  const start = shots.findIndex(s => s.id === fromId) + 1;
  return [...shots.slice(start), ...shots.slice(0, start)]
    .find(s => s.id !== fromId && !(s.takes || []).length && !S.uploads.some(u => u.shot === s.id))?.id || null;
}

export const cancelAdvance = () => clearTimeout(advanceTimer);

// --- shot selection ---------------------------------------------------------------------------

export function selectShot(id) {
  const shots = S.project?.shots || [];
  const i = shots.findIndex(s => s.id === id);
  if (i < 0) return false;
  if (S.rec !== 'idle' && id !== S.shot) {
    toast('Finish the take before switching shots');
    return false;
  }
  cancelAdvance();
  S.shot = id;
  setPrompter(prompter, shots[i], i, shots.length);
  renderSidebar();
  list.querySelector('.shot.current')?.scrollIntoView({ block: 'nearest' });
  return true;
}

export function stepShot(delta) {
  const shots = S.project?.shots || [];
  const i = shots.findIndex(s => s.id === S.shot);
  const next = shots[Math.min(shots.length - 1, Math.max(0, i + delta))];
  if (next && next.id !== S.shot) selectShot(next.id);
}

/** Rebuild the list only when something visible changed (progress bars are patched in place). */
export function renderSidebar() {
  const sig = JSON.stringify([S.project?.shots, S.shot, [...S.expanded], S.playing, S.rec === 'idle', S.build?.state,
    S.uploads.map(u => [u.id, u.state, u.error])]);
  if (sig === sidebarSig) return;
  sidebarSig = sig;
  renderShots(list, S.project, { current: S.shot, expanded: S.expanded, uploads: S.uploads, playing: S.playing, recording: S.rec !== 'idle', building: S.build?.state === 'running' });
  if (S.playing) list.querySelector(`li[data-take="${CSS.escape(S.playing)}"]`)?.append(player);   // keeps playing
}

// --- take actions, inline player, imports -----------------------------------------------------

async function takeCmd(name, act) {
  // The running build reads the takes' files: moving one away mid-build fails it.
  if (act === 'discard' && S.build?.state === 'running') return toast('A reel is building from these takes: discard after it finishes.', 'warn');
  if (act === 'discard' && !confirm(`Discard take ${name}?\nIt moves to raw/discarded/ (nothing is deleted).`)) return;
  try {
    await takeAction(name, act);
    if (act === 'discard') {
      S.expanded.delete(name);
      if (S.playing === name) stopPlayer();
    }
    await refreshProject();
  } catch (e) {
    banner(`Could not ${act} ${name}: ${e.message}`);
  }
}

function togglePlay(name) {
  const t = allTakes().find(x => x.name === name);
  if (!t || S.playing === name) return stopPlayer();
  S.playing = name;
  player.src = mediaUrl(t.url || t.src);
  renderSidebar();
  player.play().catch(e => e.name !== 'AbortError' && banner(`Can't play ${name}: ${e.message}`));
}

export function stopPlayer() {
  player.pause();
  player.removeAttribute('src');
  player.load();
  player.remove();
  S.playing = null;
  renderSidebar();
}

function importFile(shot, file) {
  const ext = IMPORT_EXT[(file.name.split('.').pop() || '').toLowerCase()];
  if (!ext) return banner(`Can't import “${file.name}”: use an .mp4, .mov or .webm video.`);
  queueUpload({ shot, source: 'import', ext, blob: file, fileName: file.name, info: {
    source: 'import', shot, user_agent: navigator.userAgent,
    file: { name: file.name, size: file.size, type: file.type, lastModified: file.lastModified },
  } });
}

// --- uploads: never lose a take; a failure keeps the bytes for Retry / Save -------------------

/** job: {shot, source: "record" | "import", ext, blob, info, fileName?} */
export function queueUpload(job) {
  const u = { id: ++uploadSeq, progress: 0, state: 'uploading', error: '', ...job };
  S.uploads.push(u);
  sendUpload(u);
}

async function sendUpload(u) {
  Object.assign(u, { state: 'uploading', progress: 0, error: '' });
  clearBanner(`upload-${u.id}`);
  renderSidebar();
  updateBuildButton();
  try {
    const { name } = await uploadTake({ ...u, onProgress: p => { u.progress = p; updateUploadProgress(list, u); } });
    if (u.setAside) {
      // A take started over with R: keep the bytes, out of the reel (raw/discarded/).
      S.uploads = S.uploads.filter(x => x !== u);
      await takeAction(name, 'discard').catch(e => banner(`${name} was uploaded but not set aside: ${e.message}. `
        + 'Discard it by hand if you don\'t want it.', `upload-${u.id}`));
      await refreshProject();
      renderSidebar();
      updateBuildButton();
      return;
    }
    if (u.source === 'record') S.lastTake = name;
    statuses.set(name, 'checking');   // so its QA result counts as "arrived" even if it lands fast
    S.uploads = S.uploads.filter(x => x !== u);
    await refreshProject();
  } catch (e) {
    Object.assign(u, { state: 'failed', error: `Upload failed: ${e.message}. The take is kept in this tab: Retry, or Save it to disk.` });
    banner(`Upload of a ${u.shot} take failed: ${e.message}`, `upload-${u.id}`);
  }
  renderSidebar();
  updateBuildButton();
}

function saveUpload(u) {
  const a = h('a', { href: URL.createObjectURL(u.blob), download: u.fileName || `${u.shot}-unsent-${u.id}.${u.ext}` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
}

function dropUpload(u) {
  if (!confirm('Throw away this unsent take? It only exists in this browser tab.')) return;
  S.uploads = S.uploads.filter(x => x !== u);
  clearBanner(`upload-${u.id}`);
  renderSidebar();
  updateBuildButton();
}

export function wireShotList() {
  list.addEventListener('click', e => {
    const b = e.target.closest('[data-act]');
    if (!b || b.tagName === 'INPUT') return;
    b.blur();   // Space must keep meaning record/stop, not "press the last clicked button"
    const { act, name, shot, upload } = b.dataset;
    const u = S.uploads.find(x => String(x.id) === upload);
    ({
      select: () => selectShot(shot), play: () => togglePlay(name),
      expand: () => { S.expanded.has(name) ? S.expanded.delete(name) : S.expanded.add(name); renderSidebar(); },
      pin: () => takeCmd(name, 'pin'), unpin: () => takeCmd(name, 'unpin'), discard: () => takeCmd(name, 'discard'),
      retry: () => u && sendUpload(u), save: () => u && saveUpload(u), drop: () => u && dropUpload(u),
      'import-pick': () => b.parentElement.querySelector('input[data-act="import"]')?.click(),
    })[act]?.();
  });
  list.addEventListener('change', e => {
    const input = e.target;
    if (input.dataset.act !== 'import' || !input.files?.length) return;
    importFile(input.dataset.shot, input.files[0]);
    input.value = '';
    input.blur();
  });
  player.addEventListener('error', () => S.playing && banner(`Can't play ${S.playing}: the file could not be loaded.`));
  let frame = 0;
  addEventListener('resize', () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => fitPrompter(prompter.line));
  });
}
