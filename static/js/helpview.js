// @ts-check
/* Kalmido web client: the view "Help" (2.1086.0, #5820). Loaded on demand (lazyload.js module helpview) by its page #help.
   Short "How to" sections per area in everyday words with the click path, from the same source the agents search
   (docs/*.md, api/helpuser.py): GET /api/help = the topics per area in the person's language, GET /api/search?kind=help
   = the search, GET /api/help/section = one section (Markdown, drawn by renderMd of attachments.js, read-only; 2.1090.0
   #5899: with its named places a button "Show me", showme.js).
   Addresses: #help (every area), #help/area:<area> (one area first, "All topics" back), #help/<key> (one section, "Back").
   The ways in (start files): the command search (palette.js "Help" + one entry per section), "Help for this area" in the
   header's "…" (render.js), "How it works" in empty states (hlp_linkHtml) and Settings > Help.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const HV = {list: /** @type {any} */ (null), lg: '', sec: /** @type {Record<string, any>} */ ({}), q: '', hits: /** @type {any} */ (null), err: false, n: 0, from: false};  // from: a topic was opened from the list (Back = the browser's back)

const hv_lang = () => (typeof I18N !== 'undefined' && I18N.code) || 'en';
function hv_route() {
  const r = String(S.route.help || '');
  return r.startsWith('area:') ? {area: r.slice(5), key: ''} : {area: '', key: r};
}
// a section's text: soft line breaks of the Markdown (a step that goes on in the next line) join, so a step stays one item
function hv_md(text) {
  const out = [];
  for (const ln of String(text || '').split('\n')) {
    const prev = out.length ? out[out.length - 1] : '';
    if (ln.trim() && prev.trim() && !/^\s*(\d+[.)]|[-*])\s+/.test(ln) && !/^#{1,6}\s/.test(ln)) out[out.length - 1] = prev + ' ' + ln.trim();
    else out.push(ln);
  }
  return renderMd(out.join('\n'), true);
}
function hv_load() {
  if (HV.list && HV.lg === hv_lang()) return;
  const lg = hv_lang(); HV.lg = lg; HV.err = false;
  api('GET', '/api/help').then(j => { if (HV.lg === lg) { HV.list = j; hlp_palSet(j); hv_draw(); } }, () => { HV.err = true; hv_draw(); });
}
function hv_secLoad(key) {
  const c = HV.sec[key], lg = hv_lang();
  if (c && c.lg === lg) return c;
  HV.sec[key] = {lg, j: null, err: false};
  api('GET', '/api/help/section?key=' + encodeURIComponent(key)).then(j => { HV.sec[key] = {lg, j, err: false}; hv_draw(); },
    () => { HV.sec[key] = {lg, j: null, err: true}; hv_draw(); });
  return HV.sec[key];
}
function hv_search(q) {
  const n = ++HV.n; HV.q = q;
  if (!q.trim()) { HV.hits = null; hv_draw(); return; }
  api('GET', '/api/search?kind=help&q=' + encodeURIComponent(q)).then(j => { if (n === HV.n) { HV.hits = j.data || []; hv_draw(); } },
    () => { if (n === HV.n) { HV.hits = []; hv_draw(); } });
}
const hv_topic = s => `<li><a class="hvtopic" href="#help/${esc(encodeURIComponent(s.key))}" data-hvk="${esc(s.key)}">${ic('help', 's')}<span>${esc(s.title)}</span></a></li>`;
function hv_areas(only) {
  if (HV.err) return errorState({size: 'sec', retry: () => { HV.list = null; hv_load(); hv_draw(); }});
  if (!HV.list) return loadingHtml('sec');
  const areas = HV.list.areas || [];
  if (!areas.length) return emptyState({icon: 'help', title: tr('No help topics yet'), size: 'sec'});
  const sorted = only ? [...areas.filter(a => a.area === only), ...areas.filter(a => a.area !== only)] : areas;
  return sorted.map(a => `<section class="hvarea${a.area === only ? ' hvcur' : ''}" data-hva="${esc(a.area)}"><h3>${esc(a.title)}</h3><ul class="hvlist">${/*html-ok*/ a.sections.map(hv_topic).join('')/* hv_topic escapes */}</ul></section>`).join('');
}
function hv_hitsHtml() {
  if (HV.hits === null) return loadingHtml('sec');
  if (!HV.hits.length) return emptyState({icon: 'search', title: tr('Nothing found in the help'), sub: tr('Try other words, or look through the topics.'), size: 'sec'});
  return `<ul class="hvlist hvhits">${HV.hits.map(h => `<li><a class="hvtopic" href="#help/${esc(encodeURIComponent(h.key))}" data-hvk="${esc(h.key)}">${ic('help', 's')}<span><b>${esc(h.title)}</b><small class="muted">${esc(h.snippet || '')}</small></span></a></li>`).join('')}</ul>`;
}
function hv_secHtml(key) {
  const c = hv_secLoad(key);
  const back = `<button type="button" class="btn sm hvback" data-hvback>${ic('back', 's')} ${esc(tr('All help topics'))}</button>`;
  if (c.err) return back + errorState({size: 'sec', title: tr('This help topic does not exist (any more)'), sub: ''});
  if (!c.j) return back + loadingHtml('sec');
  const j = c.j;
  const show = Array.isArray(j.show) ? j.show.join(' ') : String(j.show || '');
  return `${/*html-ok*/ back}<article class="hvsec" data-hvsec="${esc(j.key)}" lang="${esc(j.lang)}"${show ? ` data-show="${esc(show)}"` : ''}><h2>${esc(j.title)}</h2><div class="md hvtext">${/*html-ok*/ hv_md(j.text)/* renderMd: escaped Markdown */}</div>${/*html-ok*/ hv_showHtml(j)}</article>`;
}
// 2.1090.0 (#5899): "Show me" under a section that marks named places (<!-- show: key -->, api/helpuser.py steps): the same
// spotlight as under an agent's chat message (showme.js), with the places' own headings and no agent's line; it only goes to
// the view and highlights, Close comes back here. A section without marks has no button.
const hv_showHtml = j => Array.isArray(j.steps) && j.steps.length ? `<div class="hvshow"><button type="button" class="btn sm" data-hvshow>${ic('eye', 's')} <span>${esc(tr('Show me'))}</span></button></div>` : '';
function hv_show() {
  const c = HV.sec[hv_route().key], steps = c?.j?.steps;
  if (!Array.isArray(steps) || !steps.length) return;
  loadModule('showme').then(() => shw_start(steps), () => { /* loadModule said it (offline) */ });  // lazy-ok: loaded first
}
function hv_inner() {
  const {area, key} = hv_route();
  if (key) return hv_secHtml(key);
  return HV.q.trim() ? hv_hitsHtml() : hv_areas(area);
}
function viewHelp() {
  hv_load();
  const {key} = hv_route();
  const search = key ? '' : `<div class="ctsearch hvsearch">${ic('search', 's')}<input type="search" id="hv-q" value="${esc(HV.q)}" placeholder="${esc(tr('Search the help…'))}" aria-label="${esc(tr('Search the help'))}" autocomplete="off"></div>`;
  return `<div class="hvpage">${/*html-ok*/ search}<div class="hvbody">${/*html-ok*/ hv_inner()/* built escaped */}</div></div>`;
}
function hv_draw() {
  const b = $('#view .hvbody'); if (!b || S.route.key !== 'help') return;
  setHtml(b, hv_inner());
}
document.addEventListener('input', e => {
  const t = /** @type {HTMLInputElement} */ (e.target);
  if (t?.id !== 'hv-q') return;
  hv_search(t.value);  // every key asks; HV.n drops the answers of older words (no hand-made delay)
});
document.addEventListener('click', e => {
  const t = /** @type {HTMLElement} */ (e.target);
  const a = t.closest?.('[data-hvk]');
  if (a && !(/** @type {MouseEvent} */ (e).ctrlKey || /** @type {MouseEvent} */ (e).metaKey)) { e.preventDefault(); HV.from = true; go('help/' + encodeURIComponent(a.getAttribute('data-hvk') || '')); return; }
  if (t.closest?.('[data-hvshow]')) { e.preventDefault(); hv_show(); return; }
  if (t.closest?.('[data-hvback]')) { e.preventDefault(); if (HV.from) { HV.from = false; history.back(); } else go('help'); }
});
