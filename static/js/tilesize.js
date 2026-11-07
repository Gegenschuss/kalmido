// @ts-check
/* Kalmido web client: 2.583.0 (#4812) the size of the cards of the documents and of the file store (ONE part for both:
   docs.js viewDocs, abdocs.js abd_toolsHtml / abd_card, tagsel.js through abd_cardsHtml2). A slider in the bar above the
   cards (7 to 28 rem card width, stepless, keys like any slider), Ctrl / Cmd + mouse wheel, a trackpad pinch and two fingers
   on the card area (drag.js pz_attach: only the area, the page keeps the browser's zoom, #3311), Ctrl + Plus / Minus / 0 on
   the area. The grid fills its width (auto-fill): small cards = more columns. Remembered per person, a computer and a phone
   each their own (the settings dc_tile_d / dc_tile_m). Small cards show the picture only (the name on hover / focus); from
   TS_TEXT sender, date and amount below it; from TS_SHARP a card loads the sharper preview (800 px, ?size=l) where there
   is one. The size is a CSS variable on the root (--dc-tw) and the class dc-tsm, so every redraw of any card list keeps it.
   No animation (a reduced motion setting needs nothing). Loaded with the documents (lazyload.js, module docs). */
'use strict';

const TS_MIN = 7, TS_MAX = 28, TS_TEXT = 9, TS_SHARP = 13;  // rem; the server checks the same range (accounts/settings.py)
const ts_key = () => isMobile() ? 'dc_tile_m' : 'dc_tile_d';
const ts_std = () => isMobile() ? 9.5 : 11;  // the sizes before #4812 (docs.css)
const ts_clamp = v => Math.round(Math.min(TS_MAX, Math.max(TS_MIN, v)) * 4) / 4;
/** @type {{v: number|null, sharp: boolean|null}} v = the size while it changes (before it is saved) */
const TS = {v: null, sharp: null};
function ts_get() {
  if (TS.v != null) return TS.v;
  const v = parseFloat(S.settings?.[ts_key()]);
  return v >= TS_MIN && v <= TS_MAX ? v : ts_std();
}
const ts_sharp = () => ts_get() >= TS_SHARP;
// the root follows the size: the variable, the class of small cards, the sliders on screen, the pictures (small / sharp)
function ts_apply() {
  const v = ts_get(), r = document.documentElement;
  r.style.setProperty('--dc-tw', v + 'rem');
  r.classList.toggle('dc-tsm', v < TS_TEXT);
  for (const s of /** @type {NodeListOf<HTMLInputElement>} */ (document.querySelectorAll('input.ts-range'))) if (+s.value !== v) s.value = String(v);
  const sharp = v >= TS_SHARP;
  if (TS.sharp === sharp) return;
  TS.sharp = sharp;
  for (const img of /** @type {NodeListOf<HTMLImageElement>} */ (document.querySelectorAll('img[data-dctl]'))) {
    const u = sharp ? img.dataset.dctl : img.dataset.dcts;
    if (u && img.getAttribute('src') !== u) img.setAttribute('src', u);
  }
}
// a new size: shown at once, saved once it rests (the other kind of device keeps its own)
function ts_set(v, save = true) {
  TS.v = ts_clamp(v);
  ts_apply();
  if (!save) return;
  ts_saveLater();
}
const ts_saveLater = debounce(() => ts_save(), 400);  // saved once it rests (core.js debounce, no hand-made delay)
async function ts_save() {
  ts_saveLater.cancel();
  if (TS.v == null) return;
  const k = ts_key(), v = String(TS.v);
  if (S.settings) S.settings[k] = v;
  TS.v = null;
  try { await api('PATCH', '/api/settings', {[k]: v}); } catch { /* shown; the size holds until the next load */ }
}
// a card picture: the small preview, the sharp one (when there is one) from TS_SHARP; both noted for a later change of size
function ts_img(url, urlL) {
  const src = urlL && ts_sharp() ? urlL : url;
  return `<img src="${esc(src)}" data-dcts="${esc(url)}"${urlL ? ` data-dctl="${esc(urlL)}"` : ''} alt="" loading="lazy">`;
}
// the slider of the bar (documents, file store cards); drawing it syncs the root (a redraw after a load, another device kind)
function ts_barHtml() {
  setTimeout(ts_apply, 0);
  const v = ts_get(), t = tr('Card size');
  return `<label class="ts-bar" title="${esc(t + ' (' + tr('Ctrl + mouse wheel') + ')')}">${ic('grid', 's')}<input type="range" class="ts-range" min="${TS_MIN}" max="${TS_MAX}" step="0.25" value="${v}" aria-label="${esc(t)}"></label>`;
}
const ts_area = t => /** @type {Element|null} */ (t?.closest?.('.dc-grid') || null);

document.addEventListener('input', e => {
  const s = /** @type {HTMLInputElement} */ (e.target);
  if (s?.classList?.contains('ts-range')) ts_set(+s.value);
});
// two fingers, Ctrl + wheel, a trackpad pinch, Safari's gesture: only on the card area
if (typeof pz_attach === 'function') pz_attach(document, {area: ts_area, start: () => ({s: ts_get()}), move: (d, k) => ts_set(d.s * k, false), end: () => ts_save()});
// Cmd + wheel (a Mac mouse; Ctrl + wheel comes through pz_attach)
document.addEventListener('wheel', e => {
  if (!e.metaKey || e.ctrlKey || !ts_area(e.target)) return;
  e.preventDefault();
  const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
  ts_set(ts_get() * Math.exp(-Math.max(-25, Math.min(25, dy)) * .01));
}, {passive: false});
// Ctrl / Cmd + Plus / Minus / 0 with the focus on the area: one step bigger / smaller, 0 = the standard size
document.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || !ts_area(document.activeElement)) return;
  const k = e.key, v = ts_get();
  if (k === '+' || k === '=') ts_set(v * 1.15);
  else if (k === '-') ts_set(v / 1.15);
  else if (k === '0') ts_set(ts_std());
  else return;
  e.preventDefault();
});
addEventListener('resize', () => { if (TS.v == null) ts_apply(); });  // a computer window made phone-narrow: its own size
ts_apply();
