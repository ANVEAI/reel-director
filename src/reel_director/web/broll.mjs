/* Reel Director media B-roll treatments (staged to <reel>/assets/rd/broll.mjs; reel.mjs imports it only when the
   plan carries media items). prepare(items, ctx) runs once; the returned draw(it, t) sets every animated style from
   t alone (seek-safe: no Math.random, no Date, no tweens with state). Clips are HyperFrames <video class="clip">
   elements: the framework seeks and plays them; this module only moves their containers.
   it.media (treatments.py): {t: treatment, video, kb: [s0, s1, x0 %, y0 %, x1 %, y1 %], mask: circle|wipe|text,
     origin: [x %, y %] (cut-out subject centroid), match: {brightness, saturate}, device, cut,
     pos: object-position that keeps the salient run in view, org: transform origin (a split pane: the middle of
     the part above the captions), hold: s after the in when a bridged clip's last frame takes over (it keeps
     pushing in), beat: s after the in when the picture punches in (a bridged run never reads static), tint}
   Treatments: fullbleed (8-frame settle, then a slow push), kenburns (eased seeded move over the insert), parallax
   (cut-out subject zooms faster than its image, about the subject), sticker (pop + float), device (rise + tilt
   settle, screen pushes in), polaroid (drops in, stack fans, photo develops), reveal (circle from the face, wipe,
   or the media through a word), inset (rounded box pops in beside the face). The grade: the reel's #mp-grade
   filter (when the look has a tone), #rd-tint (one-accent presets) and the measured brightness / saturation match,
   set once, never animated. A device lifts about its base (never below its box: the captions sit under it). */
const c01 = (x) => Math.max(0, Math.min(1, x));
const outCubic = (x) => 1 - (1 - c01(x)) ** 3;
const outBack = (x) => { const k = c01(x) - 1; return 1 + 2.70158 * k ** 3 + 1.70158 * k ** 2; };
const inOut = (x) => 0.5 - 0.5 * Math.cos(Math.PI * c01(x));
const f2 = (x) => x.toFixed(2), f4 = (x) => x.toFixed(4);
const FULL = new Set(['fullbleed', 'kenburns', 'parallax', 'reveal']);
const SETTLE = 8;            // frames: a full-bleed insert lands with a short push-back (hard cut in, council 5)
const REVEAL_S = 0.45;       // s: circle / wipe reveal
const TEXT_HOLD = 0.5, TEXT_OPEN = 0.35;   // s: the word holds, then opens to the full picture
const HOLD_PUSH = 0.08, BEAT = 1.12;       // the held last frame's push; the beat's punch-in (about org: the payoff)

const kbAt = (kb, p) => {
  const e = inOut(p);
  return [kb[0] + (kb[1] - kb[0]) * e, kb[2] + (kb[4] - kb[2]) * e, kb[3] + (kb[5] - kb[3]) * e];
};
const kbCss = ([s, x, y]) => `translate(${f2(x)}%, ${f2(y)}%) scale(${f4(s)})`;

export function prepare(items, ctx) {
  const { F, W, H } = ctx;
  for (const it of items) {
    const m = it.media, q = (s) => it.el.querySelector(s);
    m.srcs = [...it.el.querySelectorAll('.m-src')];
    m.layer = q('.m-layer'); m.bgL = q('.m-bg'); m.fg = q('.m-fg'); m.knock = [...it.el.querySelectorAll('.m-knock')];
    m.stk = q('.m-stk'); m.dev = q('.m-dev'); m.front = q('.m-front'); m.backs = [...it.el.querySelectorAll('.m-back')];
    m.wash = q('.m-wash'); m.box = q('.mi-box'); m.cardBg = q('.bg');
    const grade = `${ctx.grade ? 'url(#mp-grade) ' : ''}${m.tint ? 'url(#rd-tint) ' : ''}` +
      `brightness(${m.match.brightness}) saturate(${m.match.saturate})`;
    for (const p of new Set(m.srcs.map((s) => s.parentElement))) p.style.filter = grade;   // static, set once
    if (m.pos) for (const s of m.srcs) s.style.objectPosition = m.pos;
    if (m.org) for (const s of m.srcs) s.style.transformOrigin = m.org;
    const o = `${m.origin[0]}% ${m.origin[1]}%`;     // the subject: what a cover crop of a wide picture keeps in view
    if (m.cut && FULL.has(m.t)) for (const s of m.srcs) s.style.objectPosition = o;
    if (m.t === 'parallax') for (const s of [m.bgL, m.fg]) if (s) s.style.transformOrigin = o;
    if (m.t === 'reveal') {   // cards sit at the frame's top left; a split card is its top pane (--split-h)
      const ph = it.layout === 'split' ? parseFloat(getComputedStyle(it.el).getPropertyValue('--split-h')) || 0.55 * H : H;
      const fb = it.layout === 'full' ? ctx.faceAt(it.s) : null;    // full: the picture opens out of the face
      m.cx = fb ? fb[0] + fb[2] / 2 : W / 2; m.cy = fb ? fb[1] + fb[3] / 2 : ph / 2;
      m.R = Math.hypot(Math.max(m.cx, W - m.cx), Math.max(m.cy, ph - m.cy)) + 8;
      if (m.cardBg && m.mask !== 'text') m.cardBg.style.opacity = '0';    // the take shows round the opening picture
    }
    m.F = F;
  }
  return draw;
}

function extra(m, u, d) {      // a bridged insert: the held last frame keeps moving; the beat punches in on its word
  let s = 1;
  if (m.hold != null && u > m.hold) s *= 1 + HOLD_PUSH * inOut((u - m.hold) / Math.max(d - m.hold, 1 / m.F));
  if (m.beat != null && u >= m.beat - 1e-6) s *= BEAT;
  return s;
}

function full(it, m, u, d) {
  if (it.inEl) it.inEl.style.transform = '';               // the card's settle would show its edges round the picture
  const p = u / d;
  let k = kbAt(m.kb, p);
  if (m.t === 'fullbleed') {
    const s = 1 + 0.05 * (1 - outCubic((u + 1 / m.F) / (SETTLE / m.F)));
    k = [k[0] * s, k[1], k[2]];
  }
  k = [k[0] * extra(m, u, d), k[1], k[2]];
  if (m.t === 'parallax') {
    const e = inOut(p);
    if (m.bgL) m.bgL.style.transform = `scale(${f4(1.08 + 0.03 * e)})`;
    if (m.fg) m.fg.style.transform = `translateY(${f2(-1.2 * e)}%) scale(${f4(1.08 + 0.13 * e)})`;
    return;
  }
  for (const s of m.srcs) s.style.transform = kbCss(k);
  if (m.t !== 'reveal') return;
  if (m.mask === 'text' && m.knock.length) {     // the word (multiply) and its outline move as one
    const o = c01((u - TEXT_HOLD) / TEXT_OPEN);
    for (const k of m.knock) {
      k.style.opacity = f4(1 - outCubic(o));
      k.style.transform = `scale(${f4(1 + 1.6 * outCubic(o))})`;
      k.style.display = o >= 1 ? 'none' : '';
    }
    return;
  }
  const q = outCubic((u + 1 / m.F) / REVEAL_S);
  if (q >= 1) { m.layer.style.clipPath = ''; if (m.cardBg) m.cardBg.style.opacity = '1'; return; }
  if (m.cardBg) m.cardBg.style.opacity = '0';
  if (m.mask === 'wipe') {
    const a = -25 + 150 * q, b = a - 25;
    m.layer.style.clipPath = `polygon(0 0, ${f2(a)}% 0, ${f2(b)}% 100%, 0 100%)`;
  } else {
    m.layer.style.clipPath = `circle(${f2(m.R * q)}px at ${f2(m.cx)}px ${f2(m.cy)}px)`;
  }
}

function sticker(it, m, u) {
  const q = (u + 1 / m.F) / 0.42;
  const pop = q >= 1 ? 1 : 0.3 + 0.7 * outBack(q), rot = -14 + 10 * outCubic(q);
  const bob = 7 * Math.sin(2 * Math.PI * u / 2.2), sway = 1.2 * Math.sin(2 * Math.PI * u / 2.9);
  m.stk.style.transform = `translateY(${f2(bob)}px) rotate(${f2(rot + sway)}deg) scale(${f4(pop)})`;
  m.stk.style.opacity = f4(c01(4 * q));
}

function device(it, m, u, d) {   // tilts up about its base and grows into its box: never below it (the captions)
  const q = outCubic((u + 1 / m.F) / 0.45);
  m.dev.style.transform = q >= 1 ? '' : `perspective(1600px) rotateX(${f2((1 - q) * 18)}deg) scale(${f4(0.9 + 0.1 * q)})`;
  m.dev.style.opacity = f4(c01((u + 1 / m.F) / 0.12));
  for (const s of m.srcs) s.style.transform = `scale(${f4((1 + 0.06 * inOut(u / d)) * extra(m, u, d))})`;
}

function polaroid(it, m, u, d) {
  const q = (u + 1 / m.F) / 0.55, e = outCubic(q);
  m.front.style.transform = `translateY(${f2((1 - (q >= 1 ? 1 : outBack(q))) * -170)}px) rotate(${f2(-12 + 9 * e)}deg)`;
  m.backs.forEach((b, i) => {
    const k = outCubic((u + 1 / m.F - 0.12 - 0.08 * i) / 0.45);
    b.style.transform = `rotate(${f2((i ? -8 : 7) * k)}deg) translateX(${f2((i ? -26 : 30) * k)}px)`;
  });
  if (m.wash) m.wash.style.opacity = f4(0.7 * (1 - outCubic(u / 0.9)));
  for (const s of m.srcs) s.style.transform = `scale(${f4(1.02 + 0.04 * inOut(u / d))})`;
}

function inset(it, m, u, d, t) {
  const q = (u + 1 / m.F) / 0.28, r = (it.e - t) / 0.2;
  const k = (q >= 1 ? 1 : 0.86 + 0.14 * outBack(q)) * (r >= 1 ? 1 : 0.92 + 0.08 * c01(r));
  m.box.style.transform = Math.abs(k - 1) < 5e-5 ? '' : `scale(${f4(k)})`;
  m.box.style.opacity = f4(c01(3 * q) * c01(r));
  if (m.t === 'inset') for (const s of m.srcs) s.style.transform = kbCss(kbAt(m.kb, u / d));
}

export function draw(it, t) {
  const m = it.media, u = t - it.s, d = Math.max(it.e - it.s, 1 / m.F);
  if (FULL.has(m.t)) full(it, m, u, d);
  else if (m.t === 'sticker' && m.stk) sticker(it, m, u);
  else if (m.t === 'device' && m.dev) device(it, m, u, d);
  else if (m.t === 'polaroid' && m.front) polaroid(it, m, u, d);
  if (m.box) inset(it, m, u, d, t);
}
