/** App messages. Errors stay until dismissed (keyed, so a retry replaces its own banner);
 *  guidance and results fade as toasts. */
import { $, h } from './dom.js';

const banners = new Map();

/** The message container, recreated if a page from an older Studio lacks it: a message must never
 *  turn an action that succeeded into an error ("Cannot read properties of null (reading 'append')"). */
function box(id, cls, live) {
  return $(id) || document.body.appendChild(h('div', { id, class: cls, 'aria-live': live }));
}

export function banner(msg, key = msg) {
  banners.get(key)?.remove();
  const el = h('div', { class: 'banner', role: 'alert' }, h('span', {}, msg),
    h('button', { type: 'button', class: 'icon', 'aria-label': 'Dismiss', onclick: () => clearBanner(key) }, '×'));
  banners.set(key, el);
  box('banners', 'banners', 'assertive').append(el);
}

export function clearBanner(key) {
  banners.get(key)?.remove();
  banners.delete(key);
}

export const bannerTexts = () => [...banners.values()].map(el => el.firstChild.textContent);

export function toast(msg, level = 'info', ms = 4500) {
  const el = h('div', { class: `toast ${level}`, role: 'status' }, msg);
  box('toasts', 'toasts', 'polite').append(el);
  setTimeout(() => el.remove(), ms);
}

export const badge = (text, level = '') => h('span', { class: `badge ${level}` }, text);

export function showNote(el, text, level) {
  el.textContent = text;
  el.className = `note ${level || ''}`;
  el.hidden = !text;
}

/** Centre message over the preview ("Opening camera…"); empty hides it. */
export function stageMsg(text) {
  const el = $('stage-msg');
  el.textContent = text;
  el.hidden = !text;
}
