/** Tiny DOM helpers: an element builder that only ever sets text (never innerHTML), and formatting. */

export const $ = id => document.getElementById(id);

/** h('button', {class: 'x', dataset: {act: 'pin'}, disabled: true}, 'Pin'): false/null props and kids are skipped. */
export function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  el.append(...kids.flat(Infinity).filter(c => c != null && c !== false));
  return el;
}

/** Fixed-point number, or an em dash when the value is missing. */
export const num = (v, digits = 0) => (Number.isFinite(v) ? v.toFixed(digits) : '—');

/** 63.4 -> "1:03.4" */
export function clock(seconds) {
  const s = Math.max(0, seconds);
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
}
