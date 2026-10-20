/** Teleprompter, and the shot list: takes, QA verdicts, ★ best, pin/discard/import, pending uploads. */
import { h, num } from './dom.js';

const LINE_H = 1.18;     // keep in sync with `.line { line-height }` in studio.css
const MIN_PX = 44;       // readable at arm's length; long lines wrap rather than shrink below this
const VERDICT_TEXT = { great: 'great', ok: 'ok', retake: 'retake', checking: 'checking…', error: 'QA error', ready: 'ready' };
const STAGE_TEXT = { queued: 'queued…', normalizing: 'converting…', checking: 'checking…' };

// --- teleprompter -----------------------------------------------------------------------------

export function setPrompter(els, shot, index, total) {
  els.pos.textContent = `Shot ${index + 1} / ${total} · ${shot.id} · ~${num(shot.estimate_s, 1)} s read`;
  els.line.textContent = shot.line;
  els.cues.textContent = (shot.cues || []).map(cueText).join('  ·  ');
  els.cues.title = els.cues.textContent;
  fitPrompter(els.line);
}

function cueText(c) {
  return `‘${c.at_words}’ → ${c.type}${c.text ? ` ${c.text}` : ''}`;
}

/** Largest font (>= 44 px) that keeps the line within two lines of the prompter's narrow width,
 *  else within three: a third line costs less eye travel than a wider measure. */
export function fitPrompter(el) {
  const max = Math.round(Math.min(104, Math.max(56, innerHeight * 0.085)));
  for (const lines of [2, 3]) {
    const fits = px => {
      el.style.fontSize = `${px}px`;
      return el.scrollHeight <= Math.ceil(px * LINE_H * lines) + 1 && el.scrollWidth <= el.clientWidth + 1;
    };
    let lo = MIN_PX, hi = max;
    if (!fits(lo)) continue;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (fits(mid)) lo = mid;
      else hi = mid - 1;
    }
    el.style.fontSize = `${lo}px`;
    return;
  }
  el.style.fontSize = `${MIN_PX}px`;
}

// --- shot list --------------------------------------------------------------------------------

export function takeVerdict(t) {
  if (t.status === 'checking') return 'checking';
  if (t.status === 'error') return 'error';
  return t.qa?.verdict || 'ready';
}

const problems = t => (t.qa?.checks || []).filter(c => c.level !== 'ok');
// Root causes first: a muted mic also fails the script check, but "check the mic" is the fix.
const FAIL_RANK = ['silent', 'clipping', 'noise', 'misread', 'coverage'];
const rank = c => (FAIL_RANK.indexOf(c.id) + FAIL_RANK.length + 1) % (FAIL_RANK.length + 1);

/** The one line shown under a take: the error, else its worst check. */
export function takeReason(t) {
  if (t.status === 'error') return t.error || t.qa?.error || 'The quality check failed: see the studio server log.';
  const p = problems(t);
  const fails = p.filter(c => c.level === 'fail').sort((a, b) => rank(a) - rank(b));
  return (fails[0] || p[0])?.message || '';
}

/** A take the build may use: checked, and either pinned or not sent back by QA (mirrors
 *  project.build_candidates; pinning a retake is the creator accepting it). */
export const usableTake = t => t.status === 'ready' && (t.pin || takeVerdict(t) !== 'retake');

/** 'ready' | 'retake' (only takes QA sent back) | 'none' (no checked take yet). */
export function shotReadiness(s) {
  const takes = s.takes || [];
  if (takes.some(usableTake)) return 'ready';
  return takes.some(t => t.status === 'ready') ? 'retake' : 'none';
}

/** ui: {current, expanded:Set, uploads:[], playing, recording, building} */
export function renderShots(list, project, ui) {
  list.replaceChildren(...(project?.shots || []).map((s, i) => shotItem(s, i, ui)));
}

function shotItem(s, i, ui) {
  const takes = s.takes || [];
  const ups = ui.uploads.filter(u => u.shot === s.id);
  const ready = takes.filter(t => t.status === 'ready');
  const busy = takes.some(t => t.status === 'checking') || ups.some(u => u.state === 'uploading');
  const best = takes.find(t => t.name === s.best);
  const bv = best ? takeVerdict(best) : '';   // the ★ take's verdict colours the shot: a retake isn't "done"
  const star = s.best ? `★ ${s.best}${bv === 'retake' ? ' · retake' : ''}` : `${ready.length} ready`;
  const [cls, text] = busy ? ['busy', 'checking…']
    : ready.length ? [{ retake: 'retake', ok: 'warn' }[bv] || 'done', star]
      : ['empty', takes.length ? 'no usable take' : 'no take yet'];
  return h('li', { class: `shot${s.id === ui.current ? ' current' : ''}`, dataset: { shot: s.id } },
    h('button', { type: 'button', class: 'shot-head', dataset: { act: 'select', shot: s.id }, title: 'Select this shot' },
      h('span', { class: 'shot-num' }, i + 1),
      h('span', { class: 'shot-id' }, s.id),
      h('span', { class: `shot-state ${cls}` }, text),
      h('span', { class: 'shot-line' }, s.line)),
    takes.length || ups.length
      ? h('ul', { class: 'takes' }, takes.map(t => takeItem(t, s, ui)), ups.map(uploadItem)) : null,
    h('div', { class: 'shot-foot' },
      // A real button (reachable with Tab) that opens the hidden file input next to it.
      h('button', { type: 'button', class: 'small', disabled: ui.recording, dataset: { act: 'import-pick', shot: s.id },
        title: 'Add a video filmed with another app, e.g. the iPhone Camera app in 4K portrait' }, 'Import video…'),
      h('input', { type: 'file', accept: 'video/*', hidden: true, disabled: ui.recording, tabindex: -1,
        dataset: { act: 'import', shot: s.id } })));
}

function takeItem(t, shot, ui) {
  const v = takeVerdict(t);
  const open = ui.expanded.has(t.name);
  const reason = takeReason(t);
  const tip = problems(t).map(c => `${c.level.toUpperCase()}: ${c.message}`).join('\n');
  return h('li', { class: `take v-${v}${open ? ' open' : ''}`, dataset: { take: t.name } },
    h('div', { class: 'take-row' },
      h('button', { type: 'button', class: 'icon', dataset: { act: 'play', name: t.name },
        disabled: v === 'checking', title: ui.playing === t.name ? 'Stop playback' : 'Play this take',
        'aria-label': `${ui.playing === t.name ? 'Stop' : 'Play'} ${t.name}` }, ui.playing === t.name ? '■' : '▶'),
      h('button', { type: 'button', class: 'take-name', dataset: { act: 'expand', name: t.name },
        'aria-expanded': String(open), title: 'Show the quality report' },
      t.name, shot.best === t.name ? h('span', { class: `star${usableTake(t) ? '' : ' unusable'}`,
        title: usableTake(t) ? 'The auto-picker will use this take'
          : 'Best take so far, but QA says retake: record again, or Pin it to build with it anyway' }, '★') : null),
      t.pin ? h('span', { class: 'pin', title: 'Pinned: used regardless of score' }, 'pinned') : null,
      h('span', { class: `badge v-${v}`, title: tip || null }, (v === 'checking' && STAGE_TEXT[t.stage]) || VERDICT_TEXT[v] || v),
      h('span', { class: 'take-actions' },
        h('button', { type: 'button', class: 'small', dataset: { act: t.pin ? 'unpin' : 'pin', name: t.name },
          disabled: t.status !== 'ready' || ui.recording,
          title: t.pin ? 'Let the auto-picker choose again' : 'Always use this take for the shot' }, t.pin ? 'Unpin' : 'Pin'),
        h('button', { type: 'button', class: 'small danger', dataset: { act: 'discard', name: t.name },
          disabled: ui.recording || ui.building,
          title: ui.building ? 'A reel is building from these takes: discard after it finishes'
            : 'Move to raw/discarded (nothing is deleted)' }, 'Discard'))),
    reason && !(open && t.qa) ? h('p', { class: 'take-reason' }, reason) : null,   // the open report lists it
    open ? qaDetails(t) : null);
}

const row = (k, v) => [h('dt', {}, k), h('dd', {}, v)];

function qaDetails(t) {
  const qa = t.qa;
  if (!qa) return h('div', { class: 'qa' }, h('p', { class: 'muted' }, t.status === 'checking' ? 'Checking…' : 'No quality report.'));
  const v = qa.video || {}, a = qa.audio || {}, s = qa.script || {};
  const eff = Array.isArray(v.effective_9x16) ? v.effective_9x16.join('×') : '—';
  return h('div', { class: 'qa' },
    h('ul', { class: 'checks' }, (qa.checks || []).map(c => h('li', { class: `lvl-${c.level}` }, c.message))),
    h('dl', {},
      row('Script', `${num(s.coverage * 100)}% read · score ${num(s.score, 1)} · ${num(s.cuts)} cut(s) · ${num(s.kept_seconds, 1)} s kept`),
      s.misread?.length ? row('Misread', s.misread.map(m => `“${m.heard}” for “${m.expected}”`).join(', ')) : null,
      s.missing?.length ? row('Missing', s.missing.join(' ')) : null,
      s.junk?.length ? row('Cut out', s.junk.join(' ')) : null,
      row('Video', `${num(v.width)}×${num(v.height)} · ${num(v.fps, 2)} fps · 9:16 ${eff} · brightness ${num(v.subject_luma ?? v.luma_mean)}`
        + ` · blur ${num(v.blur, 1)}${v.vfr_source ? ' · variable-rate source' : ''}`),
      row('Audio', `${num(a.lufs, 1)} LUFS · peak ${num(a.peak_dbfs, 1)} dBFS · SNR ${num(a.snr_db)} dB`
        + ` · noise ${num(a.noise_floor_db)} dB${a.clipped_samples ? ` · ${a.clipped_samples} clipped samples` : ''}`)));
}

const pct = p => `${Math.round(p * 100)}%`;

function uploadItem(u) {
  const failed = u.state === 'failed';
  return h('li', { class: `take upload${failed ? ' v-error' : ''}`, dataset: { upload: u.id } },
    h('div', { class: 'take-row' },
      h('span', { class: 'take-name' }, u.source === 'import' ? `import: ${u.fileName}` : u.setAside ? 'set-aside take' : 'new take'),
      failed ? h('span', { class: 'badge v-error' }, 'upload failed')
        : [h('progress', { max: 1, value: u.progress }), h('span', { class: 'badge', dataset: { pct: '' } }, pct(u.progress))],
      failed ? h('span', { class: 'take-actions' },
        h('button', { type: 'button', class: 'small', dataset: { act: 'retry', upload: u.id } }, 'Retry'),
        h('button', { type: 'button', class: 'small', dataset: { act: 'save', upload: u.id } }, 'Save file'),
        h('button', { type: 'button', class: 'small danger', dataset: { act: 'drop', upload: u.id } }, 'Drop')) : null),
    u.error ? h('p', { class: 'take-reason' }, u.error) : null);
}

/** Upload progress is patched in place so the list isn't rebuilt on every progress event. */
export function updateUploadProgress(list, u) {
  const li = list.querySelector(`li[data-upload="${u.id}"]`);
  if (!li) return;
  const bar = li.querySelector('progress');
  if (bar) bar.value = u.progress;
  const label = li.querySelector('[data-pct]');
  if (label) label.textContent = pct(u.progress);
}
