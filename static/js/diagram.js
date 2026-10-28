// @ts-check
/* Kalmido web client: 2.382.0 (#3153) -- formulas and Mermaid diagrams on knowledge pages.
   - wiki.js wk_render leaves a ```math / ```mermaid block (and "$$ … $$" lines, turned into ```math) as a code block and
     an inline \( … \) as a .wkimath span with its source; this module (lazyload.js: module "diagram") is loaded only when a
     page has one of them and draws them in place: the read view, the live preview (wklive.js) and pages shared with me.
   - The libraries ship with Kalmido (static/vendor/katex, static/vendor/mermaid: MIT, README with version and source) and
     are loaded only for the kind of block a page has (KaTeX for formulas, Mermaid for diagrams), never from a CDN and not
     in the service worker's precache. No network / a broken block: the source stays as a code block with a short hint.
   - Mermaid runs with securityLevel "strict" (its own sanitizer), no HTML labels, no click callbacks; the SVG is cleaned
     once more (no script, no on… attributes, no javascript: links) before it goes into the page. Light / dark follows the
     app's theme. KaTeX: throwOnError off (an error shows as red source), trust off, limits on size and macro expansion.
   Classic script sharing the global scope with the others. */
'use strict';

/** @type {any} */
const DGM = {k: null, m: null, seen: new Map(), n: 0, q: Promise.resolve(), obs: null, light: null};
const DGM_SEL = '.wkmd pre[data-lang="math"]:not([data-dg]), .wkmd pre[data-lang="mermaid"]:not([data-dg]), .wkmd .wkimath:not([data-dg])';
function dg_script(src) {
  return new Promise((ok, no) => {
    const s = document.createElement('script'); s.src = src;
    s.onload = ok; s.onerror = () => { s.remove(); no(new Error(tr('Could not be loaded'))); };
    document.head.appendChild(s);
  });
}
function dg_katex() {
  if (!DGM.k) {
    if (!document.querySelector('link[data-dgkatex]')) {
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/static/vendor/katex/katex.min.css'; l.dataset.dgkatex = '1'; document.head.appendChild(l);
    }
    DGM.k = dg_script('/static/vendor/katex/katex.min.js').then(() => /** @type {any} */ (window).katex).catch(e => { DGM.k = null; throw e; });
  }
  return DGM.k;
}
function dg_mermaid() {
  if (!DGM.m) DGM.m = dg_script('/static/vendor/mermaid/mermaid.min.js').then(() => /** @type {any} */ (window).mermaid).catch(e => { DGM.m = null; throw e; });
  return DGM.m;
}
const dg_light = () => { const t = document.documentElement.dataset.theme; return t === 'light' || (t !== 'dark' && typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: light)').matches); };
function dg_tex(k, tex, display) {
  return k.renderToString(tex, {displayMode: display, throwOnError: false, errorColor: '#c62828', trust: false, strict: 'ignore', maxSize: 40, maxExpand: 500, output: 'htmlAndMathml'});
}
// the SVG once more without anything that could run (Mermaid's strict mode cleaned it already)
function dg_clean(svg) {
  const d = new window.DOMParser().parseFromString(svg, 'image/svg+xml'), r = d.documentElement;
  if (!r || r.nodeName !== 'svg') return '';
  r.querySelectorAll('script, iframe, object, embed, a').forEach(x => { if (x.nodeName === 'a') x.replaceWith(...x.childNodes); else x.remove(); });
  for (const x of [r, ...r.querySelectorAll('*')]) {
    for (const a of [...x.attributes]) if (/^on/i.test(a.name) || (/href$/i.test(a.name) && !/^#/.test(a.value))) x.removeAttribute(a.name);
  }
  r.removeAttribute('height'); r.setAttribute('role', 'img'); r.setAttribute('aria-label', tr('Diagram'));
  return new window.XMLSerializer().serializeToString(r);
}
async function dg_svg(src) {
  const light = dg_light(), key = (light ? 'l' : 'd') + src;
  if (DGM.seen.has(key)) return DGM.seen.get(key);
  const mm = await dg_mermaid();
  mm.initialize({startOnLoad: false, securityLevel: 'strict', theme: light ? 'neutral' : 'dark', htmlLabels: false, flowchart: {htmlLabels: false}, fontFamily: 'inherit', suppressErrorRendering: true});
  const id = 'dgmm' + (++DGM.n);
  try {
    const {svg} = await mm.render(id, src);
    const h = dg_clean(svg);
    if (!h) throw new Error(tr('The diagram could not be drawn'));
    DGM.seen.set(key, h);
    return h;
  } finally { document.getElementById(id)?.remove(); document.getElementById('d' + id)?.remove(); }
}
// Mermaid measured its texts outside the page; in the page the app's font can be wider: the view box follows the drawing
function dg_fit(svg) {
  let b; try { b = svg?.getBBox(); } catch { return; }
  if (!b || !b.width || !b.height) return;  // not shown (yet): keep Mermaid's box
  const p = 8, w = Math.ceil(b.width + 2 * p), h = Math.ceil(b.height + 2 * p);
  svg.setAttribute('viewBox', `${Math.floor(b.x - p)} ${Math.floor(b.y - p)} ${w} ${h}`);
  svg.style.maxWidth = w + 'px';
}
// a block that cannot be drawn keeps its source (code block) with a short hint above it
function dg_fail(el, what, e) {
  const box = el.closest('.mdcode') || el;
  if (box.previousElementSibling?.classList.contains('wkdgerr')) return;
  const n = document.createElement('p'); n.className = 'wkdgerr muted'; n.setAttribute('role', 'note');
  n.textContent = what + (e?.message ? ': ' + String(e.message).split('\n')[0].slice(0, 160) : '');
  box.before(n);
}
async function dg_one(el) {
  el.dataset.dg = '1';
  if (el.classList.contains('wkimath')) {
    const tex = el.dataset.tex || '';
    try { el.innerHTML = dg_tex(await dg_katex(), tex, false); el.classList.add('on'); } catch { /* no network: the source stays */ }
    return;
  }
  const src = el.textContent || '', box = el.closest('.mdcode') || el, mermaid = el.dataset.lang === 'mermaid';
  if (!src.trim()) return;
  try {
    const d = document.createElement('div');
    if (mermaid) { d.className = 'wkdg wkdgmm'; d.innerHTML = await dg_svg(src); }
    else { d.className = 'wkdg wkdgmath'; d.setAttribute('role', 'math'); d.innerHTML = dg_tex(await dg_katex(), src, true); }
    d.dataset.src = src;
    if (box.isConnected) { box.replaceWith(d); if (mermaid) dg_fit(d.querySelector('svg')); }
  } catch (e) { if (box.isConnected) dg_fail(el, mermaid ? tr('The diagram could not be drawn') : tr('The formula could not be drawn'), e); }
}
// every block not drawn yet, one after the other (Mermaid renders one at a time)
function dg_draw(root) {
  dg_watch();
  const els = [...(root || document).querySelectorAll(DGM_SEL)];
  for (const el of els) DGM.q = DGM.q.then(() => dg_one(el)).catch(() => {});
  return DGM.q;
}
// later drawings (the live preview redraws its blocks from a cache, the share dialog, another page) are found as they come;
// watched from the first page with a formula / diagram on (a module loaded by the test suites' ld_all watches nothing)
function dg_watch() {
  if (DGM.obs || typeof MutationObserver !== 'function') return;
  let t = 0;
  const later = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : f => setTimeout(f, 16);
  DGM.obs = new MutationObserver(() => { if (!t) t = later(() => { t = 0; dg_draw(); }); });
  DGM.obs.observe(document.body, {childList: true, subtree: true});
  DGM.light = dg_light();
  try { matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => setTimeout(dg_retheme, 0)); } catch { /* old browser */ }
  new MutationObserver(() => dg_retheme()).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
}
// the theme changed: the diagrams are drawn again in the other colours
function dg_retheme() {
  const l = dg_light(); if (l === DGM.light) return;
  DGM.light = l;
  document.querySelectorAll('.wkdgmm[data-src]').forEach(d => {
    const el = /** @type {HTMLElement} */ (d), pre = document.createElement('pre');
    pre.className = 'mdpre'; pre.dataset.lang = 'mermaid'; pre.textContent = el.dataset.src || ''; el.replaceWith(pre);
  });
  dg_draw();
}
