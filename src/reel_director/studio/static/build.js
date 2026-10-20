/** Build: start prep → compile → render → master → review, poll its progress and log tail, then play the
 *  finished reel with its loudness numbers, the take chosen for every shot and the QA review: verdict,
 *  gate list, the editing director's notes and the before/after sheet (raw take vs edit). The style preset
 *  picker sets the director's preset for the next build. "Preview edit" runs in the same worker at
 *  any time (even with no takes): your takes where they exist, RECORD slots elsewhere, same dialog. */
import { getBuild, mediaUrl, setOptions, setPreset, startBuild, startPreview } from './api.js';
import { h, num } from './dom.js';
import { shotReadiness, takeReason } from './shots.js';
import { S, allTakes } from './state.js';
import { banner, clearBanner, toast } from './ui.js';

const STEPS = ['prep', 'compile', 'render', 'master', 'review'];
const PREVIEW_STEPS = ['prep', 'compile', 'render'];   // review-quality render carries the mix: no master pass
const PREVIEW_LABEL = 'Preview — slots show where you appear';
const STEP_TITLE = {
  prep: 'Clean audio, transcribe takes', compile: 'Pick takes, cut, assemble the edit',
  render: 'Render with HyperFrames', master: 'Mix and deliver (−14 LUFS, −1.5 dBTP)',
  review: 'Check the reel: QA gates, before/after (+ editing director)',
};
const VERDICT = { ship: 'Ready to post', fix: 'Needs a fix', block: 'Blocked' };
const MASTER = '/media/renders/reel-master.mp4';
const POLL_MS = 1000;
let panel = null, timer = null;

class BuildPanel {
  /** els: {button, why, steps, state, log, open, dialog, video, stats, shots, preview?, title?} */
  constructor(els, onStart, onPreview) {
    this.els = els;
    this.resultKey = '';
    els.button.addEventListener('click', () => {
      els.button.blur();
      onStart();
    });
    els.preview?.addEventListener('click', () => {
      els.preview.blur();
      onPreview();
    });
    els.open.addEventListener('click', () => {
      els.open.blur();
      this.openResult();
    });
    els.dialog.addEventListener('close', () => els.video.pause());
    els.video.addEventListener('error', () => {
      if (this.resultKey) banner(`The finished reel could not be loaded (${els.video.currentSrc || MASTER}).`, 'reel');
    });
  }

  setEnabled(ok, why, previewOk = true) {
    this.els.button.disabled = !ok;
    this.els.why.textContent = why;
    if (this.els.preview) this.els.preview.disabled = !previewOk;
  }

  update(b) {
    const state = b?.state || 'idle';
    const preview = b?.kind === 'preview';
    const steps = preview ? PREVIEW_STEPS : STEPS;
    const at = steps.indexOf(b?.step);
    this.els.steps.replaceChildren(...steps.map((s, i) => {
      let cls = '';
      if (state === 'done' || (state !== 'idle' && i < at)) cls = 'done';
      else if (i === at && state === 'running') cls = 'active';
      else if (i === at && state === 'error') cls = 'error';
      return h('li', { class: cls, title: STEP_TITLE[s] }, s);
    }));
    const pct = Number.isFinite(b?.progress) ? ` ${Math.round(b.progress)}%` : '';   // HyperFrames' render progress
    const what = preview ? 'Preview' : 'Running';
    this.els.state.textContent = {
      idle: '', running: `${what}: ${STEP_TITLE[b?.step] || 'starting'}…${pct}`, done: preview ? 'Preview ready.' : 'Done.',
      error: `${preview ? 'Preview failed' : 'Failed'} during ${b?.step || 'the build'}: ${b?.error || 'see the log below'}.`,
    }[state] ?? state;
    this.els.state.className = `build-state ${state}`;
    this.showLog(b?.log || [], state);
    const result = state === 'done' ? b.result : null;
    this.els.open.hidden = !result;
    this.els.open.textContent = result?.preview ? 'Watch the preview' : 'Watch the finished reel';
    if (result) this.fillResult(result);
  }

  showLog(lines, state) {
    const pre = this.els.log;
    const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
    pre.textContent = lines.join('\n');
    pre.hidden = !lines.length;
    pre.classList.toggle('error', state === 'error');
    if (stick || state === 'error') pre.scrollTop = pre.scrollHeight;
  }

  fillResult(r) {
    const key = JSON.stringify(r);
    if (key === this.resultKey) return;
    this.resultKey = key;
    const { stats, shots, video, title, dialog } = this.els;
    const label = r.preview ? (r.label || PREVIEW_LABEL) : 'Finished reel';
    if (title) {
      title.textContent = label;
      title.classList.toggle('preview-title', !!r.preview);
    }
    dialog.setAttribute('aria-label', label);
    clearBanner('reel');
    video.src = mediaUrl(r.video || MASTER);   // same URL every build; load() fetches the new file
    video.load();
    if (r.preview) {     // review quality, not delivered: no loudness numbers, slots instead
      const slots = (r.shots || []).filter(s => !s.take).length;
      stats.replaceChildren(`${num(r.duration, 1)} s · `, r.preset ? `${r.preset} · ` : '',
        Number.isFinite(r.build_s) ? `built in ${num(r.build_s, 0)} s · ` : '',
        slots ? `${slots} slot(s) still to record` : 'every shot has a take');
      this.fillQa(null);   // a preview is not reviewed
      shots.replaceChildren(...(r.shots || []).map(s =>
        h('tr', {}, h('td', {}, s.id), h('td', {}, s.take ?? 'RECORD slot'), h('td', {}, s.take ? num(s.cuts) : '—'))));
      return;
    }
    // Delivery targets: -14 LUFS +/- 0.5 and a true peak at or under -1.5 dBTP; a miss is flagged, not hidden.
    const loud = Number.isFinite(r.lufs) && Math.abs(r.lufs + 14) > 0.5, peak = Number.isFinite(r.true_peak) && r.true_peak > -1.5;
    stats.replaceChildren(`${num(r.duration, 1)} s · `, r.preset ? `${r.preset} · ` : '',
      Number.isFinite(r.build_s) ? `built in ${num(r.build_s, 0)} s · ` : '',
      h('span', { class: loud ? 'off-target' : null, title: loud ? 'Target is -14 LUFS (±0.5)' : null }, `${num(r.lufs, 1)} LUFS integrated`),
      ' · ', h('span', { class: peak ? 'off-target' : null, title: peak ? 'Above the -1.5 dBTP ceiling: may distort after platform re-encoding' : null },
        `true peak ${num(r.true_peak, 1)} dBTP${peak ? ' (over −1.5)' : ''}`));
    shots.replaceChildren(...(r.shots || []).map(s =>
      h('tr', {}, h('td', {}, s.id), h('td', {}, s.take ?? '—'), h('td', {}, num(s.cuts)))));
    this.fillQa(r.qa);
  }

  /** The review step's report: verdict + score, every gate (failures first), the director, before/after. */
  fillQa(qa) {
    const box = document.getElementById('reel-qa');
    if (!box) return;
    box.hidden = !qa;
    if (!qa) return;
    const verdict = document.getElementById('reel-verdict'), gates = document.getElementById('reel-gates');
    const dir = document.getElementById('reel-director'), img = document.getElementById('reel-ba');
    if (qa.error) {
      verdict.replaceChildren(`Quality check did not run: ${qa.error}`);
      gates.replaceChildren(); dir.textContent = ''; img.hidden = true;
      return;
    }
    verdict.replaceChildren(h('span', { class: `pill ${qa.verdict}` }, VERDICT[qa.verdict] || qa.verdict || '?'),
      `score ${num(qa.score)}`, qa.gate_score !== qa.score ? ` (gates ${num(qa.gate_score)})` : '');
    const order = { fail: 0, warn: 1, ok: 2 };
    gates.replaceChildren(...[...(qa.gates || [])].sort((a, b) => order[a.level] - order[b.level]).map(g =>
      h('li', { class: `lvl-${g.level}` }, h('b', {}, g.level), `${g.id.replace(/_/g, ' ')}: ${g.message}`)));
    const d = qa.director;
    const rounds = (qa.rounds || []).map(x => x.stopped ? `round ${x.round}: ${x.stopped}`
      : `round ${x.round}: ${num(x.score_before)} → ${num(x.score_after)}`);
    dir.textContent = !d ? 'Editing director: off (turn it on next to the Build button).'
      : d.status === 'ok' ? `Editing director: ${num(d.score)}/100. ${d.summary || ''} ${rounds.join('; ')}`.trim()
        : `Editing director skipped: ${d.note || 'no answer'}`;
    img.hidden = !qa.before_after;
    if (qa.before_after) {
      img.src = mediaUrl(qa.before_after);
      document.getElementById('reel-ba-link').href = mediaUrl(qa.before_after);
    }
  }

  openResult() {
    if (!this.resultKey) return;
    if (!this.els.dialog.open) this.els.dialog.showModal();
    this.els.video.play().catch(() => { /* autoplay refused: the controls are right there */ });
  }
}

export function initBuild(els) {
  panel = new BuildPanel({
    preview: document.getElementById('preview-btn'), title: document.getElementById('reel-title'), ...els,
  }, onBuild, onPreview);
  for (const key of ['director', 'matte']) {
    const box = document.getElementById(`opt-${key}`);
    box?.addEventListener('change', async () => {
      try {
        const opts = await setOptions({ [key]: box.checked });
        if (S.project) S.project.options = opts;
      } catch (e) {
        banner(`Could not change the option: ${e.message}`, 'options');
        box.checked = !!S.project?.options?.[key];
      }
    });
  }
  const pick = document.getElementById('preset-pick');
  pick?.addEventListener('change', async () => {
    try {
      await setPreset(pick.value);
      if (S.project) S.project.preset = pick.value;
      toast(`Style: ${pick.value}`, 'ok');
    } catch (e) {
      banner(`Could not change the style: ${e.message}`, 'preset');
      pick.value = S.project?.preset || '';
    }
  });
}

/** Fill the style picker from the project (presets, the chosen one, beta labels). */
function updatePreset() {
  const pick = document.getElementById('preset-pick');
  const p = S.project;
  if (!pick || !p?.presets) return;
  if (pick.options.length !== p.presets.length) {
    pick.replaceChildren(...p.presets.map(n =>
      h('option', { value: n }, (p.beta_presets || []).includes(n) ? `${n} (beta)` : n)));
  }
  if (document.activeElement !== pick) pick.value = p.preset;
  pick.disabled = S.build?.state === 'running';
  for (const key of ['director', 'matte']) {
    const box = document.getElementById(`opt-${key}`);
    if (!box) continue;
    if (document.activeElement !== box) box.checked = !!p.options?.[key];
    box.disabled = S.build?.state === 'running';
  }
}

async function onBuild() {
  try {
    await startBuild();
  } catch (e) {
    banner(e.status === 409 ? `Build not started: ${e.message}` : `Could not start the build: ${e.message}`, 'build');
    return;
  }
  clearBanner('build');
  applyBuild({ state: 'running', step: 'prep', log: [] }, true);
}

async function onPreview() {
  try {
    await startPreview();
  } catch (e) {
    banner(e.status === 409 ? `Preview not started: ${e.message}` : `Could not start the preview: ${e.message}`, 'build');
    return;
  }
  clearBanner('build');
  applyBuild({ state: 'running', kind: 'preview', step: null, log: [] }, true);
}

async function pollBuild() {
  try {
    applyBuild(await getBuild(), true);
    clearBanner('build-poll');
  } catch (e) {
    banner(`Lost contact with the build: ${e.message}. Retrying…`, 'build-poll');
    clearTimeout(timer);
    timer = setTimeout(pollBuild, 2 * POLL_MS);
  }
}

/** Show a build status; `live` means it follows a build seen running in this tab. */
export function applyBuild(b, live) {
  const was = S.build?.state;
  S.build = b || { state: 'idle' };
  panel.update(S.build);
  clearTimeout(timer);
  if (S.build.state === 'running') timer = setTimeout(pollBuild, POLL_MS);
  if (live && was === 'running' && S.build.state === 'done') {
    toast(S.build.kind === 'preview' ? 'Preview ready' : 'Reel built', 'ok');
    panel.openResult();
  }
  // the compiler's resolution guard: say it out loud, not only in the log (council 3: "Studio warns")
  const off = S.build.state === 'done' && (S.build.result?.director || []).find((l) => /punches off/.test(l));
  if (off) banner(`No punch-ins in this reel: ${off.replace(/^note:\s*(compile:\s*)?/, '')}. `
    + 'Punch-ins need a 9:16 crop at least 1061 px wide (portrait framing or a 1440p+ camera).', 'punch-off');
  else clearBanner('punch-off');
  if (live && was === 'running' && S.build.state === 'error') {
    banner(`${S.build.kind === 'preview' ? 'Preview' : 'Build'} failed during ${S.build.step || 'a step'}: `
      + `${S.build.error || 'see the log in the Build panel'}`, 'build');
  }
  updateBuildButton();
}

/** Why shots whose only checked takes QA sent back block the build: "hook (Misread: …)". */
function retakeWhy(shots) {
  return shots.map(s => {
    const best = (s.takes || []).find(t => t.name === s.best) || (s.takes || []).find(t => t.status === 'ready');
    const why = best ? takeReason(best).replace(/\.\s.*$/, '').slice(0, 90) : '';
    return why ? `${s.id} (${why})` : s.id;
  }).join(', ');
}

/** Enabled once every shot has a usable take (not a QA retake, unless pinned) and nothing is
 *  still uploading or being checked. */
export function updateBuildButton() {
  if (!panel) return;
  updatePreset();
  const shots = S.project?.shots || [];
  const missing = shots.filter(s => shotReadiness(s) === 'none').map(s => s.id);
  const retakes = shots.filter(s => shotReadiness(s) === 'retake');
  const busy = allTakes().filter(t => t.status === 'checking').length + S.uploads.filter(u => u.state === 'uploading').length;
  // While recording, a build would compete with the encoder and miss the take in progress.
  const why = S.build?.state === 'running' ? 'Building…'
    : S.rec !== 'idle' ? 'Finish the take first'
      : !shots.length ? 'Loading the project…'
        : missing.length ? `Needs a ready take for: ${missing.join(', ')}`
          : busy ? `Waiting for ${busy} take(s) to finish uploading / checking`
            : retakes.length ? `QA says retake for ${retakeWhy(retakes)}: record again, or Pin a take to build with it anyway`
              : '';
  panel.setEnabled(!why, why, S.build?.state !== 'running');   // Preview edit: any time, even with no takes
}
