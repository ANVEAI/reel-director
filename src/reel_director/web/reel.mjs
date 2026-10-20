/* Reel Director static runtime (staged to <reel>/assets/rd/reel.mjs).
   build(P) prepares the page once; the returned draw(t) sets every animated style from t alone
   (seek-safe: no Math.random, no Date, no tweens with state; the page is a pure function of time).
   Transitions are the pack's DOM back-end (applyDom on the .txl layers inside #stage); the look is the pack's
   SVG grade (toSVGFilter) with skin-safe tones (skin dE2000 <= 3 on real takes, tests/test_visuals.py).
   Hooks from the layout pass (layout.py; all optional, each with a fallback):
     cue elements: data-kind, data-params (the cue's params as JSON: card {icon, viz: "ring"|"bar", max};
       title {busy: 0..1 | backing: "calm"|"glass"|"solid"}), --x --y --w --h (the element's box, reel px);
       split/pip cards also --fx --fy --fw --fh (the face crop before relocation, reel px)
     takes: .fr carries the punch origin (eye midpoint) inline, .rf the reframe; a matte adds
       video[data-layer="subject"] over video[data-layer="background"] (reel.css treats the background only)
     P.face_reel [{t, head: [x,y,w,h]}]: the padded face (forehead to chin) on screen at t, reel px (bgfocus, split/pip)
     P.look {tone: grade params, bgfx: {blur px, dim} | false}; without it the tone falls back on P.grade */
import { applyDom } from '../mp/transitions/lib/tx-dom.js';
import { toSVGFilter } from '../mp/layers/grade.js';

const $ = (id) => document.getElementById(id);
const c01 = (x) => Math.max(0, Math.min(1, x));
const outCubic = (x) => 1 - (1 - c01(x)) ** 3;
const outBack = (x) => { const k = c01(x) - 1; return 1 + 2.70158 * k ** 3 + 1.70158 * k ** 2; };
const smooth = (x) => { x = c01(x); return x * x * (3 - 2 * x); };
const LAYER_PROPS = ['transform', 'transformOrigin', 'filter', 'opacity', 'clipPath', 'webkitMaskImage', 'maskImage', 'borderRadius',
  'boxShadow', 'zIndex', 'webkitMaskSize', 'maskSize', 'webkitMaskPosition', 'maskPosition', 'webkitMaskRepeat', 'maskRepeat',
  'backfaceVisibility', 'mixBlendMode'];
/* skin-safe tones by P.grade (skin dE2000 max 0.8-1.5 on the founder's takes); P.look.tone wins. The v1 pack grades
   at 70 % (warm-film, cool-tech) shifted skin by dE 4.0 and 7.3 (2.9-3.9 measured on rendered frames). mono is opt-in. */
const TONES = {
  warm: { temp: 0.05, contrast: 0.08, sat: 1.04, split: { shadowHue: 190, shadowSat: 0.06 } },
  cool: { temp: -0.05, contrast: 0.10, sat: 1.03, split: { shadowHue: 220, shadowSat: 0.12 } },
  'teal-orange': { contrast: 0.10, sat: 1.03, split: { shadowHue: 190, shadowSat: 0.2 } },
  mono: { sat: 0, contrast: 0.24, fade: 0.01 },
};
const MAX_H = { 'cap-in': 276, 'title-text': 260, 'card-text': 640, chip: 220, 'stat-v': 300, 'ec-main': 330 };
const MIN_PX = { 'title-text': 80, 'cap-in': 64 };   // council 6: title 80-104 px, captions never below 64 px
const MAX_LINES = { 'cap-in': 2 };                    // council 6: a caption chunk is at most 2 lines
const BUSY = { glass: 0.35, solid: 0.6 };             // title backing by background busyness (layout pass, 0..1)
const BACKING = { calm: [0.62, 1], glass: [0.55, 0.6], solid: [0.94, 1] };   // rgba(8,8,16,a) over the backdrop x brightness
const GLYPH_ALIAS = { bolt: 'zap', spark: 'sparkles', speech: 'message-circle', check: 'circle-check', cross: 'circle-x',
  tag: 'badge-percent', arrow: 'send' };           // motion-pack sticker ids in hand-written scripts
const FACE0 = [348, 615, 384, 384];                  // no face track: the v1 eye line (0.38 H), a typical face
const BGFX = { blur: 10, dim: 0.8 };                 // contract: blur 8-14 px, -15..25 % exposure, background only
const SPLIT_FACE = 0.47;   // split fallback (no --dy from the layout pass): head-box centre at 47% of the bottom pane
const TICK_LEAD = 4;       // frames a checklist item's tick lands before its spoken word (council 4: inserts lead by 4)
const PIP = { cx: 250, cy: 455, r: 160 };            // pip face circle (top left, clear of the action rail)
const HAIR = 0.45;     // focus edge above a padded head box, x its width: the hair top measured 0.36 (0.45-0.47 x the Vision box)
const BLOBS = [[0.2, 0.2, 170, 140, 0.55, 0.43, 0], [0.86, 0.5, 150, 190, 0.37, 0.61, 2.1],   // anchor x, y (share of the bg),
  [0.22, 0.82, 190, 120, 0.47, 0.33, 4.2], [0.55, 0.35, 90, 70, 0.29, 0.41, 1.3]];           // radius x, y px, rad/s x, y, phase

/* WCAG relative luminance and contrast; readable() keeps the accent when it reads, else mixes it toward
   white (dark backing) or ink (light backing) until it reaches min:1 */
const rgbOf = (s) => {
  let h = (/^#([\da-f]{3}|[\da-f]{6})$/i.exec(String(s).trim()) || [0, 'ffffff'])[1];
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  const n = parseInt(h, 16); return [n >> 16, (n >> 8) & 255, n & 255];
};
const lum = (c) => c.reduce((a, v, i) => { v /= 255; return a + [0.2126, 0.7152, 0.0722][i] * (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); }, 0);
const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
const backL = ([a, br]) => lum([8, 8, 16].map((v) => a * v + (1 - a) * 255 * br));   // worst case: a white wall behind
function readable(c, bgL, min = 4.5) {
  const to = bgL > 0.18 ? [11, 11, 15] : [255, 255, 255];
  for (let k = 0; k <= 20; k++) { const m = c.map((v, i) => Math.round(v + (to[i] - v) * k / 20)); if (ratio(lum(m), bgL) >= min) return m; }
  return to;
}
const rgb = (c) => `rgb(${c.join(', ')})`;
const params = (el) => { try { return JSON.parse((el && el.dataset.params) || '{}') || {}; } catch (e) { return {}; } };
const cssRect = (el) => {
  const cs = getComputedStyle(el), v = ['--fx', '--fy', '--fw', '--fh'].map((k) => parseFloat(cs.getPropertyValue(k)));
  return v.every(Number.isFinite) && v[2] > 0 && v[3] > 0 ? v : null;
};

/* lines a text box wraps onto: distinct tops of its word spans */
const lines = (el) => new Set([...el.querySelectorAll('.word')].map((w) => Math.round(w.offsetTop))).size;

/* shrink a text box's font until it fits its width (and band height, and line cap), never under its floor:
   at the floor the text wraps onto another line instead; measured once with real faces. In a card the
   box's other children (badge, dial) take their share of the room first. */
function fit(el) {
  const hidden = [];
  for (let p = el; p && p !== document.body; p = p.parentElement) {
    if (getComputedStyle(p).display === 'none') { hidden.push([p, p.style.display]); p.style.display = 'block'; }
  }
  const box = el.parentElement, cls = Object.keys(MAX_H).find((c) => el.classList.contains(c)), bs = getComputedStyle(box);
  const mw = getComputedStyle(el).maxWidth;            // a px cap of its own (the stat inside its ring), not a %
  let maxH = MAX_H[cls] || 1e9, maxW = Math.min(box.clientWidth || 860, 860, mw.endsWith('px') ? parseFloat(mw) : 1e9);
  if (cls === 'card-text' && box.classList.contains('card-in')) {
    const sib = [...box.children].filter((c) => c !== el), gap = parseFloat(bs.gap) || 0;
    if (bs.flexDirection === 'row') maxW -= sib.reduce((a, c) => a + c.offsetWidth + gap, 0);
    else maxH = Math.min(maxH, box.clientHeight - sib.reduce((a, c) => a + c.offsetHeight + gap, 0));
  }
  const floor = MIN_PX[cls] || 0, maxL = MAX_LINES[cls] || 1e9;
  let size = parseFloat(getComputedStyle(el).fontSize), n = 0;
  while ((el.scrollWidth > maxW + 1 || el.getBoundingClientRect().width > maxW + 1 || el.scrollHeight > maxH
          || lines(el) > maxL) && n++ < 24 && size > floor) {
    size = Math.max(floor, size * 0.93); el.style.fontSize = size.toFixed(1) + 'px';
  }
  for (const [p, d] of hidden) p.style.display = d;
}

/* hand-drawn callout paths in the svg's own pixel box (sized to the caption chunk) */
function calloutPath(kind, w, h) {
  if (kind === 'circle') return `M ${w * 0.52} 4 C ${w * 0.9} 4 ${w - 2} ${h * 0.3} ${w - 3} ${h * 0.52} C ${w - 4} ${h * 0.83} ${w * 0.7} ${h - 3} ${w * 0.47} ${h - 4}` +
    ` C ${w * 0.17} ${h - 5} 2 ${h * 0.78} 2 ${h * 0.5} C 2 ${h * 0.21} ${w * 0.22} 5 ${w * 0.6} 8`;
  if (kind === 'arrow') return `M -70 ${h + 80} Q -60 ${h * 0.75} -10 ${h * 0.55} M -10 ${h * 0.55} L -40 ${h * 0.48} M -10 ${h * 0.55} L -30 ${h * 0.82}`;
  return `M 6 ${h - 8} Q ${w * 0.5} ${h - 20} ${w - 6} ${h - 10}`;
}

function parseStat(v) {
  const m = /^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$/.exec(v);
  if (!m) return null;
  const num = parseFloat(m[2].replace(/,/g, '')), dec = (m[2].split('.')[1] || '').length;
  return { pre: m[1], num, dec, comma: m[2].includes(','), post: m[3] };
}
function fmtStat(s, x) {
  let txt = x.toFixed(s.dec);
  if (s.comma) { const [i, d] = txt.split('.'); txt = i.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (d ? '.' + d : ''); }
  return s.pre + txt + s.post;
}
/* the share of the ring a stat sweeps: percent of 100, hours of a 12-hour dial, minutes/seconds of 60, else full */
function statFrac(s, label, prm) {
  if (!s) return 1;
  if (+prm.max > 0) return c01(s.num / prm.max);
  const u = `${s.pre} ${s.post} ${label}`.toUpperCase();
  if (/%|PERCENT/.test(u)) return c01(s.num / 100);
  if (/\b(HOURS?|HRS?)\b/.test(u)) return c01(s.num / 12);
  if (/\b(MIN(UTE)?S?|SEC(OND)?S?)\b/.test(u)) return c01(s.num / 60);
  if (/\bDAYS?\b/.test(u)) return c01(s.num / (s.num <= 7 ? 7 : 30));
  return 1;
}

/* the frames a timed element is visible on, exactly as HyperFrames decides it: start/end from the
   element's own attributes, snapped onto the frame grid when within 0.001 frame (export render seek) */
function frames(el, F) {
  const snap = (x) => { const i = x * F, r = Math.round(i); return Math.abs(i - r) <= 0.001 ? r : i; };
  const s = parseFloat(el.dataset.start), d = parseFloat(el.dataset.duration);
  return [snap(s), snap(s + d)];
}
const on = (f, fr) => f >= fr[0] - 1e-6 && f < fr[1] - 1e-6;
const el = (tag, cls, html = '') => { const e = document.createElement(tag); e.className = cls; e.innerHTML = html; return e; };
/* a settled element gets no transform at all (an identity transform can keep a stale raster: 1-level noise in seekcheck) */
const sc = (k) => (Math.abs(k - 1) < 5e-5 ? '' : `scale(${k.toFixed(4)})`);

/* a vendored glyph id (or a pack sticker alias) when reel.css has its mask, else null */
let probe = null;
function glyphId(id) {
  id = String(id || '').trim(); id = GLYPH_ALIAS[id] || id;
  if (!/^[a-z][a-z0-9-]*$/.test(id)) return null;
  if (!probe) { probe = el('i', 'ico'); probe.style.display = 'none'; document.body.appendChild(probe); }
  probe.dataset.icon = id;
  return getComputedStyle(probe).getPropertyValue('--ico').trim() ? id : null;
}
function badge(id) {
  const b = el('div', 'badge', '<i class="pulse"></i><i class="pulse"></i><i class="ico"></i>');
  b.lastChild.dataset.icon = id;
  return b;
}

/* card DOM, built once: background layers, kinetic words, glyph badge, stat dial or meter, list ticks */
function buildCard(it, prm, accent, accentDark) {
  const add = (cls) => it.bg.appendChild(el('i', cls)), fx = {}, k = it.bgKind;
  if (k === 'mesh') { fx.blobs = [1, 2, 3, 4].map((n) => add('blob b' + n)); add('dots'); }
  else if (k === 'grid') { add('sky'); fx.floor = add('floor'); add('horizon'); }
  else if (k === 'paper') fx.sheen = add('sheen');
  else if (k === 'blur') add('tint');
  else if (k === 'solid') { fx.rays = add('rays'); fx.spot = add('spot'); }
  if (k !== 'paper') { add('shade'); add('vig'); }
  it.fx = fx;
  it.el.style.setProperty('--accent-text', rgb(k === 'paper' ? readable(accent, lum([244, 239, 228]), 5) : accentDark));
  const text = it.el.querySelector('.card-text');
  if (text && !text.querySelector('.tw')) {
    const ws = text.textContent.trim().split(/\s+/); text.textContent = '';
    ws.forEach((w, i) => { if (i) text.append(' '); text.append(el('span', 'tw')); text.lastChild.textContent = w; });
  }
  const tws = text ? [...text.querySelectorAll('.tw')] : [];
  tws.forEach((w) => { const i = el('span', 'tw-i'); while (w.firstChild) i.appendChild(w.firstChild); w.appendChild(i); });
  const colon = tws.findIndex((w) => /:$/.test(w.textContent.trim()));
  (colon >= 0 && colon < tws.length - 1 ? tws.slice(colon + 1) : tws.slice(-1)).forEach((w) => w.classList.add('key'));
  it.words = tws.map((w) => ({ w, i: w.firstChild, key: w.classList.contains('key') }));
  const keyText = tws.filter((w) => w.classList.contains('key')).map((w) => w.textContent.trim()).join(' ').replace(/[^\p{L}\p{N} ]/gu, '');
  if (keyText && k !== 'paper') { fx.echo = add('echo'); fx.echo.textContent = keyText; }
  const sticker = it.el.querySelector('.icon'), gid = glyphId(prm.icon || (sticker && sticker.textContent));
  if (gid && sticker) { it.badge = badge(gid); sticker.replaceWith(it.badge); }
  else if (gid && text && !it.el.querySelector('.stat-v')) { it.badge = badge(gid); text.before(it.badge); }
  if (it.badge) it.pulses = [...it.badge.querySelectorAll('.pulse')];
  const v = it.el.querySelector('.stat-v');
  if (v) {
    const lab = it.el.querySelector('.stat-l'), s = parseStat(it.value || v.textContent);
    it.stat = { el: v, s, lab, frac: statFrac(s, lab ? lab.textContent : '', prm) };
    if (prm.viz === 'bar') { const m = el('div', 'meter', '<i></i>'); v.after(m); it.stat.fill = m.firstChild; }
    else {
      const d = el('div', 'dial', '<svg class="ring" viewBox="0 0 520 520"><circle class="trk" cx="260" cy="260" r="236"/>' +
        '<circle class="tks" cx="260" cy="260" r="236" pathLength="1"/><circle class="arc glow" cx="260" cy="260" r="236" pathLength="1"/><circle class="arc" cx="260" cy="260" r="236" pathLength="1"/></svg>');
      v.before(d);
      if (gid) { const g = el('i', 'ico'); g.dataset.icon = gid; d.appendChild(g); }
      d.appendChild(v); it.stat.dial = d; it.stat.arcs = [...d.querySelectorAll('.arc')];
    }
  }
  const list = it.el.querySelector('.list');
  if (list) {
    const lis = [...list.querySelectorAll('.li')];
    if (lis.length > 1) it.spine = list.insertBefore(el('i', 'spine'), list.firstChild);
    it.lis = lis.map((li) => {
      const tk = li.querySelector('.tick');
      if (tk) tk.innerHTML = '<svg viewBox="0 0 24 24"><path pathLength="1" d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
      return { li, tick: tk, path: tk && tk.querySelector('path'), txt: li.lastElementChild };
    });
  }
}

export async function build(P) {
  const F = P.fps, D = P.D, W = P.W, H = P.H, look = P.look || {};
  const faces = [`${P.weight} 100px "${P.font}"`, '800 100px "Noto Sans Devanagari"', '700 40px Inter', '800 40px Inter', '900 40px Montserrat'];
  await Promise.all(faces.map((f) => document.fonts.load(f).catch(() => null)));
  await document.fonts.ready;

  const tone = look.tone || (P.grade && P.grade !== 'none' ? TONES[P.grade] : null);
  if (tone) { $('mp-defs').innerHTML = toSVGFilter(tone, 'mp-grade'); $('cam').style.filter = 'url(#mp-grade)'; }

  const stage = $('stage'), cam = $('cam'), caps = $('caps'), root = document.documentElement;
  const accent = rgbOf(getComputedStyle(root).getPropertyValue('--accent'));
  const ring = el('div', ''); ring.id = 'pip-ring'; stage.appendChild(ring);
  const segs = P.segs.map((s) => ({ ...s, el: $(s.fr) }));
  for (const s of segs) { const v = s.el && s.el.querySelector('.take'); s.vfr = v ? frames(v, F) : [0, 0]; s.matte = !!(s.el && s.el.querySelector('[data-layer="subject"], [data-bg="baked"]')); }   // baked: prep already treated the background
  const wins = P.windows.map((w) => ({ ...w, a: $(w.a), b: $(w.b), cut: (w.cutF - w.startF) / (w.endF - w.startF) }));
  const layers = [...new Set(wins.flatMap((w) => [w.a, w.b]))];
  const capList = P.caps.map((c) => ({ ...c, fr: frames($(c.id), F), inEl: $(c.id + '-in'), words: c.words.map(([id, s, e]) => ({ el: $(id), s, e })) }));
  const capsPlaced = [...document.querySelectorAll('#caps .cap')].some((c) => c.dataset.params || c.style.getPropertyValue('--y'));
  const items = P.items.map((it) => {
    const e = $(it.id);
    return { ...it, el: e, inEl: $(it.id + '-in'), fr: frames(e, F), bgKind: it.bg, bg: e.querySelector('.bg') };
  });
  const darkAccent = readable(accent, lum([11, 11, 15]));
  for (const it of items) {
    const prm = { ...(it.params || {}), ...params(it.el) };
    if (it.bg) buildCard(it, prm, accent, darkAccent);
    if (it.layout === 'split' || it.layout === 'pip') it.face = cssRect(it.el) || (Array.isArray(prm.face) && prm.face.length === 4 ? prm.face : null);
    it.dy = parseFloat(getComputedStyle(it.el).getPropertyValue('--dy'));   // layout pass: the face drop on a split
    it.at = Array.isArray(prm.at) ? prm.at.map(Number) : null;              // checklist: each item's spoken word (s)
    if (it.kind === 'title') {
      const tier = BACKING[it.el.dataset.backing] ? it.el.dataset.backing : BACKING[prm.backing] ? prm.backing
        : typeof prm.busy === 'number' ? (prm.busy >= BUSY.solid ? 'solid' : prm.busy >= BUSY.glass ? 'glass' : 'calm') : 'glass';
      it.el.dataset.backing = tier;
      it.el.style.setProperty('--accent-text', rgb(readable(accent, backL(BACKING[tier]))));
    }
  }
  for (const e of document.querySelectorAll('.fit')) fit(e);
  const layouts = items.filter((it) => it.kind === 'broll' && (it.layout === 'split' || it.layout === 'pip'));
  for (const L of layouts) L.top = L.layout === 'split' ? (L.el.offsetHeight || Math.round(0.55 * H)) : 0;
  const fulls = items.filter((it) => it.bg && (it.layout || 'full') === 'full');
  const callouts = P.callouts.map((c, i) => {
    const svg = $('co-' + i), hidden = [];
    for (let p = svg; p && p !== document.body; p = p.parentElement)
      if (getComputedStyle(p).display === 'none') { hidden.push([p, p.style.display]); p.style.display = 'block'; }
    const w = svg.clientWidth || 600, h = svg.clientHeight || 120;
    for (const [p, d] of hidden) p.style.display = d;
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    const path = svg.querySelector('path'); path.setAttribute('d', calloutPath(c.kind, w, h));
    return { ...c, fr: frames($(c.cap), F), path };
  });

  /* the face on screen at t: the layout pass's track, linearly between samples under 0.5 s apart */
  const FR = (P.face_reel || P.faceReel || []).map((s) => s && { t: +s.t, box: s.head || s.box })
    .filter((s) => s && Array.isArray(s.box) && s.box.length === 4).sort((a, b) => a.t - b.t);
  function faceAt(t) {
    if (!FR.length) return null;
    let lo = 0, hi = FR.length - 1;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (FR[m].t <= t) lo = m; else hi = m - 1; }
    const a = FR[lo], b = FR[lo + 1];
    if (!b || t <= a.t || b.t - a.t > 0.5) return a.box;
    const k = (t - a.t) / (b.t - a.t);
    return a.box.map((v, j) => v + (b.box[j] - v) * k);
  }
  const bgfx = look.bgfx === false || look.bgfx === null ? null : { ...BGFX, ...(look.bgfx || {}) };
  if (bgfx) { root.style.setProperty('--bf-blur', `${+bgfx.blur}px`); root.style.setProperty('--bf-dim', `${+bgfx.dim}`); }
  else root.style.setProperty('--bf-blur', '0px'), root.style.setProperty('--bf-dim', '1');
  const focus = bgfx && FR.length && segs.some((s) => !s.matte) ? cam.appendChild(el('div', '')) : null;
  const media = items.filter((it) => it.media);       // v4 real-media B-roll (broll.mjs, loaded only when used)
  const drawMedia = media.length ? (await import('./broll.mjs')).prepare(media, { F, W, H, faceAt, grade: !!tone }) : null;
  if (focus) focus.id = 'bgfocus';

  const vig = $('fx-vig'), grain = $('fx-grain'), prog = $('progress'), fill = $('progress-fill');
  vig.style.opacity = (0.7 * c01(P.vignette)).toFixed(3);
  grain.style.opacity = (0.28 * c01(P.grain)).toFixed(3);
  if (!P.progress) prog.style.display = 'none';

  function camera(t, f) {
    for (const s of segs) {
      let k = 1, z = 0;
      for (const [pf, lvl] of s.punches) if (f >= pf) k = lvl;            // instant: on the word's start frame
      for (const [t0, t1, t2, t3, sc] of s.zooms) {                        // smooth legacy zooms: max of envelopes, never a pop
        if (t < t0 || t > t3) continue;
        const e = t < t1 ? smooth((t - t0) / (t1 - t0)) : t <= t2 ? 1 : 1 - smooth((t - t2) / (t3 - t2));
        z = Math.max(z, (sc - 1) * e);
      }
      s.el.style.transform = `scale(${(k * (1 + z)).toFixed(5)})`;
    }
  }

  function transitions(f) {
    if (!wins.length) return false;
    for (const e of layers) for (const k of LAYER_PROPS) e.style[k] = '';
    let act = null, past = null, fut = null;
    for (const w of wins) {
      if (f > w.startF && f < w.endF) act = w; else if (f >= w.endF) past = w; else if (!fut) fut = w;
    }
    const run = (w, p) => applyDom(w.key, p, { a: w.a, b: w.b, root: stage, params: w.params, cut: w.cut });
    if (act) { run(act, (f - act.startF) / (act.endF - act.startF)); return true; }
    if (past) run(past, 1);           // B only (also clears the shared overlay)
    if (fut) run(fut, 0);             // A only: on a window's first frame B's clip is already live but must not show
    return false;
  }

  /* split: the card on top, the face just under the middle of the bottom pane (clear of the caption band);
     pip: the face in a circle; both from the face rect */
  function layout(t, f) {
    caps.classList.toggle('lightbg', items.some((it) => it.bg && it.bgKind === 'paper' && on(f, it.fr)));
    const L = layouts.find((it) => on(f, it.fr));
    cam.style.transformOrigin = ''; cam.style.transform = ''; cam.style.clipPath = ''; ring.style.display = 'none'; caps.style.transform = '';
    if (!L) return false;
    const fb = faceAt(t) || L.face || FACE0, fcx = fb[0] + fb[2] / 2, fcy = fb[1] + fb[3] / 2;
    if (L.layout === 'split') {
      const top = L.top, dy = Math.round(Math.max(0, Math.min(top, Number.isFinite(L.dy) ? L.dy : top + SPLIT_FACE * (H - top) - fcy)));
      cam.style.transform = `translateY(${dy}px)`; cam.style.clipPath = `inset(${top - dy}px 0 ${dy}px 0)`;
      if (!capsPlaced) caps.style.transform = `translateY(${top - 1270}px)`;
    } else {
      const { cx, cy, r } = PIP, s = Math.max(0.25, Math.min(0.7, 1.3 * r / fb[3])), oy = fcy - 0.1 * fb[3];
      cam.style.transformOrigin = `${fcx.toFixed(1)}px ${oy.toFixed(1)}px`;
      cam.style.transform = `translate(${(cx - fcx).toFixed(1)}px, ${(cy - oy).toFixed(1)}px) scale(${s.toFixed(4)})`;
      cam.style.clipPath = `circle(${(r / s).toFixed(1)}px at ${fcx.toFixed(1)}px ${oy.toFixed(1)}px)`;
      Object.assign(ring.style, { display: 'block', left: `${cx - r - 8}px`, top: `${cy - r - 8}px`, width: `${2 * r + 16}px`, height: `${2 * r + 16}px` });
    }
    return L.layout;
  }

  /* background focus without a matte: blur + dim the frame above a soft edge just over the head top (inside #cam,
     so a split relocation carries it along with the face; off in the small pip circle) */
  function backgroundFocus(t, hide) {
    if (!focus) return;
    const box = hide ? null : faceAt(t);
    focus.style.display = box ? 'block' : 'none';
    if (!box) return;
    const b = Math.max(0, box[1] - HAIR * box[2] - 8), a = Math.max(0, b - 110);   // hair: ~0.45 x head width above
    const m = `linear-gradient(180deg, #000 0, #000 ${a.toFixed(0)}px, transparent ${b.toFixed(0)}px)`;
    focus.style.webkitMaskImage = m; focus.style.maskImage = m;
  }

  function captions(t, f) {
    for (const c of capList) {
      if (!on(f, c.fr)) continue;
      // council 6: each chunk enters once (5 frames, scale 0.94 -> 1); the active word changes colour only
      const u = c01((t - c.s + 1 / F) / (5 / F));
      c.inEl.style.transform = `scale(${(0.94 + 0.06 * outCubic(u)).toFixed(4)})`;
      for (const w of c.words) {
        const on = t >= w.s && t < w.e, past = t >= w.e;
        w.el.classList.toggle('on', on); w.el.classList.toggle('past', past); w.el.classList.toggle('future', !on && !past);
      }
    }
    for (const c of callouts) if (on(f, c.fr)) c.path.style.strokeDashoffset = (1 - smooth((t - c.s) / 0.3)).toFixed(4);
  }

  /* B-roll and cutaway cards: hard cut in on a moving background; badge pops, words rise, the stat counts up
     over 18 frames (council 4) with its ring, list items build one by one */
  function card(it, t, u) {
    const f1 = 1 / F, fx = it.fx || {}, BW = W * 1.08, BH = H * 1.08;
    it.inEl.style.transform = sc(0.965 + 0.035 * outCubic((u + f1) / 0.2));
    it.bg.style.transform = sc(1.06 - 0.06 * outCubic(u / 0.9));
    if (fx.blobs) fx.blobs.forEach((b, i) => {
      const [ax, ay, rx, ry, wx, wy, p] = BLOBS[i];
      b.style.transform = `translate(${(ax * BW + rx * Math.sin(wx * t + p)).toFixed(1)}px, ${(ay * BH + ry * Math.cos(wy * t + 1.3 * p)).toFixed(1)}px)`;
    });
    if (fx.floor) fx.floor.style.backgroundPosition = `0 ${(t * 150).toFixed(1)}px`;
    if (fx.rays) fx.rays.style.transform = `rotate(${(t * 6).toFixed(2)}deg)`;
    if (fx.spot) fx.spot.style.transform = `translate(${(Math.sin(0.7 * t) * 60).toFixed(1)}px, ${(Math.cos(0.5 * t) * 40).toFixed(1)}px)`;
    if (fx.echo) fx.echo.style.transform = `translateX(${(40 - 26 * u).toFixed(1)}px)`;
    if (fx.sheen) fx.sheen.style.transform = `translateX(${(u / Math.max(0.6, it.e - it.s) * 90 - 45).toFixed(1)}%)`;
    const w0 = it.badge ? 0.12 : 0.03;
    if (it.badge) {
      const q = (u + f1) / 0.36, g = (u + f1 - 0.08) / 0.3;
      it.badge.style.transform = q >= 1 ? '' : `scale(${(0.55 + 0.45 * outBack(q)).toFixed(4)}) rotate(${((1 - outCubic(q)) * -14).toFixed(2)}deg)`;
      const ico = it.badge.lastChild; ico.style.transform = sc(0.6 + 0.4 * outBack(g)); ico.style.opacity = c01(3 * g).toFixed(3);
      it.pulses.forEach((p, j) => {
        const ph = (u - 0.3 - 0.6 * j) / 1.2, fr = ph - Math.floor(ph);
        p.style.opacity = ph < 0 ? '0' : (0.5 * (1 - fr)).toFixed(3); p.style.transform = `scale(${(1 + 0.5 * outCubic(fr)).toFixed(4)})`;
      });
    }
    it.words.forEach((w, i) => { const q = (u + f1 - w0 - 0.07 * i) / 0.34; w.i.style.transform = q >= 1 ? '' : `translateY(${((1 - outBack(q)) * 115).toFixed(1)}%)`; });
    const mk = outCubic((u - w0 - 0.07 * it.words.length - 0.2) / 0.28);
    for (const w of it.words) if (w.key) w.w.style.setProperty('--mk', mk.toFixed(3));
    if (it.stat && it.stat.s) {
      const S = it.stat, e = outCubic(u / (18 / F)), land = c01((u - 18 / F) / 0.22);
      S.el.textContent = fmtStat(S.s, S.s.num * e);
      S.el.style.transform = sc(1 + 0.06 * Math.sin(Math.PI * land));
      if (S.arcs) for (const a of S.arcs) a.style.strokeDashoffset = (1 - S.frac * e).toFixed(4);
      if (S.fill) S.fill.style.transform = `scaleX(${(S.frac * e).toFixed(4)})`;
      if (S.dial) S.dial.style.transform = sc(0.86 + 0.14 * outBack((u + f1) / 0.32));
      if (S.lab) { const q = (u - 0.22) / 0.3; S.lab.style.opacity = c01(2 * q).toFixed(3); S.lab.style.transform = q >= 1 ? '' : `translateY(${((1 - outCubic(q)) * 40).toFixed(1)}px)`; }
    }
    if (it.lis) {   // items build on their spoken word (P.at), else 0.45 s apart; the tick lands TICK_LEAD frames early
      const n = it.lis.length, gap = n ? Math.min(0.45, (it.e - it.s) * 0.6 / n) : 0;
      const at = it.at && it.at.length === n ? it.at : null;
      const a0 = (i) => (at ? Math.max(it.s, at[i] - TICK_LEAD / F - 0.2) : it.s + i * gap);
      it.lis.forEach((x, i) => {
        const q = (t + f1 - a0(i)) / 0.3;
        x.li.style.opacity = c01(3 * q).toFixed(3);
        if (x.txt) x.txt.style.transform = q >= 1 ? '' : `translateX(${((1 - outCubic(q)) * -50).toFixed(1)}px)`;
        if (x.tick) x.tick.style.transform = sc(0.6 + 0.4 * outBack(q * 1.3));
        if (x.path) x.path.style.strokeDashoffset = (1 - outCubic((q - 0.25) / 0.6)).toFixed(4);
      });
      if (it.spine) it.spine.style.transform = `scaleY(${c01((t + f1 - a0(0) - 0.15) / Math.max(a0(n - 1) - a0(0), 0.1)).toFixed(4)})`;
    }
  }

  function item(it, t) {
    const u = t - it.s, r = it.e - t, inK = (d) => c01((u + 1 / F) / d), outK = (d) => c01(r / d);
    const S = it.inEl.style;
    if (it.kind === 'overlay') {
      const k = outBack(inK(0.18)); S.transform = `scale(${(0.82 + 0.18 * k).toFixed(4)})`; S.opacity = (inK(0.1) * outK(3 / F)).toFixed(3);
    } else if (it.kind === 'title') {
      S.opacity = outK(4 / F).toFixed(3);          // council H3: the whole hook title is on frame 0 (no build-in)
    } else if (it.kind === 'lowerthird') {
      S.transform = `translateX(${(-(1 - outCubic(inK(0.27))) * 900 + (1 - outCubic(outK(0.2))) * -900).toFixed(1)}px)`;
    } else if (it.kind === 'endcard') {
      it.el.querySelector('.scrim').style.opacity = inK(0.2).toFixed(3);
      const k = outCubic(inK(0.3)); S.opacity = k.toFixed(3); S.transform = `translateY(${((1 - k) * 60).toFixed(1)}px)`;
    } else if (it.bg) card(it, t, u);
    if (it.media && drawMedia) drawMedia(it, t);
  }

  return function draw(t) {
    t = Math.max(0, Math.min(+t || 0, D));
    const f = Math.round(t * F);
    camera(t, f);
    const moving = transitions(f);
    const lay = layout(t, f);
    backgroundFocus(t, moving || lay === 'pip' || fulls.some((it) => on(f, it.fr)) || segs.some((s) => s.matte && on(f, s.vfr)));
    captions(t, f);
    for (const it of items) if (on(f, it.fr)) item(it, t);
    grain.style.backgroundPosition = `${(f * 73) % 256}px ${(f * 151) % 256}px`;
    fill.style.transform = `scaleX(${(t / D).toFixed(5)})`;
  };
}
