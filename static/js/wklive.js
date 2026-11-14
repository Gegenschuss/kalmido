// @ts-check
/* Kalmido web client: 2.350.0 B (#3149) -- slash commands of the knowledge editor, the task search, reading styles.
   - 2.554.0 (#4052): the live preview with a field per block (#3147) and the Source / Preview switch (#3128) are gone: the one
     editor is wkcm.js (CodeMirror 6). What stays here works on it through wiki.js wk_ta (the editor's stand-in field) and on
     the plain field of "Edit as Markdown" (#wk-body) alike.
   - Slash commands (#3149, both editors): "/" at the start of a line opens a menu (heading, lists, table, code, mind
     map, formula, diagram (2.382.0 #3153), picture / file, embedded table, page link, date, templates); typing filters it, arrows / Enter / Esc like the
     [[ suggestions (they share #wk-ac). Ctrl/Cmd+K link, Ctrl/Cmd+Shift+7 / 8 / 9 numbered list / list / checkbox.
   Classic script sharing the global scope with wiki.js (lazyload.js: module "wiki"). */
'use strict';

/** @type {any} */
const WKLV = {tk: /** @type {any} */ (null)};  // 2.371.3 (#3333): tk = the task search after "/" -> "Task (#)"; 2.554.0 (#4052): the block preview (#3147) is replaced by wkcm.js
// ---- slash commands (#3149): "/" at the start of a line, in both editors (wiki.js wk_acUpdate / wk_acPick)
/** @type {any[]} */
const WKLV_CMDS = [
  ['h', 'h', N_('Heading'), 'heading überschrift titre título titolo kop', '## '],
  ['ul', 'list', N_('List'), 'list liste bullet liste lista lijst puce viñeta elenco', '- '],
  ['ol', 'list', N_('Numbered list'), 'numbered nummer ordered 1. numérotée numerada numerata genummerd', '1. '],
  ['cb', 'select', N_('Checkbox'), 'checkbox todo häkchen aufgabe case tâche casilla tarea casella compito vakje taak', '- [ ] '],
  ['tb', 'sheet', N_('Table'), 'table tabelle tableau tabla tabella tabel', null],
  ['code', 'code', N_('Code'), 'code', null],
  ['mm', 'mindmap', N_('Mind map'), 'mindmap mind map carte mentale mapa mental mappa mentale', null],
  ['math', 'calc', N_('Formula'), 'formula formel math latex katex formule fórmula formula', null],  // 2.382.0 (#3153): drawn by diagram.js
  ['mmd', 'chart', N_('Diagram'), 'diagram diagramm mermaid flowchart chart diagramme diagrama diagramma', null],
  ['file', 'picture', N_('Picture or file'), 'picture image bild file datei upload image imagen immagine afbeelding fichier archivo file bestand', null],
  ['emb', 'sheet', N_('Embed a table'), 'embed einbetten table tabelle intégrer incrustar incorporare insluiten tableau tabla tabella tabel', '[[tabelle:'],
  ['ln', 'link', N_('Link to a page'), 'link verweis page seite [[ lien enlace collegamento koppeling página pagina', '[['],
  ['embp', 'note', N_('Embed a page'), 'embed einbetten page seite ![[ intégrer incrustar incorporare insluiten página pagina', '![['],  // 2.371.2 (#3151)
  ['date', 'cal', N_('Date'), 'date datum today heute fecha data aujourd\'hui hoy oggi vandaag', null],
  ['task', 'check', N_('Task (#)'), 'task aufgabe # ticket tâche tarea compito taak', null],  // 2.371.3 (#3333): a search over the tasks the person sees
];
function wklv_cmds(sp) {
  const e2e = wk_e2e(sp);
  /** @type {any[]} */
  const cs = WKLV_CMDS.filter(c => c[0] !== 'emb' || (feat('sheets') && !e2e)).filter(c => c[0] !== 'file' || !e2e || feat('files'))
    .map(c => ({k: c[0], _ic: c[1], _label: tr(c[2]), words: (tr(c[2]) + ' ' + c[3]).toLowerCase(), ins: c[4], path: ''}));
  for (const t of wk_pages(sp).filter(x => wk_isTpl(x.path) && x.id !== WK.pg?.id).slice(0, 20)) {
    const n = wk_base(t.path); cs.push({k: 'tpl', id: t.id, _ic: 'note', _label: tr('Template') + ': ' + n, words: ('template vorlage ' + n).toLowerCase(), path: ''});
  }
  return cs;
}
// true = the menu is the one shown (the [[ suggestions do not look)
function wklv_slash(ta, box) {
  const s = ta.selectionStart, v = ta.value, a = v.lastIndexOf('\n', s - 1) + 1, m = /^\/([^\s/]{0,24})$/.exec(v.slice(a, s));
  if (!m || ta.selectionEnd !== s) return false;
  const q = m[1].toLowerCase(), hits = wklv_cmds(WK.pg?.space || wk_cur()).filter(c => !q || c.words.split(/\s+/).some(w => w.startsWith(q)) || c.words.includes(q)).slice(0, 12);
  if (!hits.length) { box.classList.add('hidden'); WK.ac = null; return true; }
  WK.ac = {hits, i: 0, from: a, cmd: true};
  wk_acDraw(box);
  return true;
}
// the chosen command: "/…" goes, its Markdown comes (one undo step: wkembed.js wem_rep)
async function wklv_slashPick(ta, c) {
  const p = WK.pg, a = WK.ac.from, z = ta.selectionStart;
  WK.ac = null; $('#wk-ac')?.classList.add('hidden');
  const put = (txt, c0 = txt.length, c1 = c0) => wem_rep(ta, a, z, txt, a + c0, a + c1);
  if (c.ins) { put(c.ins); if (c.ins.includes('[[')) wk_acUpdate(ta); return; }
  if (c.k === 'tb') { const h = `| ${tr('Column')} 1 | ${tr('Column')} 2 |\n| --- | --- |\n|  |  |`; put(h, h.length - 5); return; }
  if (c.k === 'code') { put('```\n\n```', 4); return; }
  if (c.k === 'mm') { const t = tr('Topic'), h = `\`\`\`mindmap\n${t}\n  ${tr('Idea')}\n\`\`\``; put(h, 11, 11 + t.length); return; }
  if (c.k === 'math') { put('```math\nE = mc^2\n```', 8, 16); return; }  // 2.382.0 (#3153): the example selected
  if (c.k === 'mmd') { const h = '```mermaid\nflowchart LR\n  A --> B\n```'; put(h, 26, 33); return; }
  if (c.k === 'date') { put(fmtDate(today())); return; }
  if (c.k === 'task') { put('#'); WKLV.tk = {at: a}; wk_acUpdate(ta); return; }  // 2.371.3 (#3333)
  if (c.k === 'file') {
    put('');
    const at = [a, a];
    if (!p) return;
    if (wk_e2e(p.space) || !feat('files')) { if (!wk_e2e(p.space)) wem_device(p, at); else wem_pick(p, at); return; }
    menu(ta.el || ta, [{label: tr('Upload from this device…'), icon: 'upload', fn: () => wem_device(p, at)}, {label: tr('From the file store…'), icon: 'folder', fn: () => wem_pick(p, at)}]);
    return;
  }
  if (c.k === 'tpl') {
    let t; try { t = await rawFetch('GET', '/api/wiki/pages/' + c.id); if (typeof wkePage === 'function') await wkePage(t); } catch (e) { toast(e.message); return; }
    if (!ta.isConnected) return;
    const f = wk_tplFill(wk_bodyStrip(t.body).replace(/\n+$/, ''), p?.path || '');  // 2.371.2 (#3151): {{datum}}, {{cursor}} …
    put(f.text, f.at >= 0 ? f.at : f.text.length);
  }
}
// ---- 2.371.3 (#3333): "/" -> "Task (#)" puts "#" and opens a search over the tasks the person sees: what follows the "#" is
// the query (the tasks loaded here first, then from 2 characters the server's search GET /api/search, 250 ms after the last
// key, a newer query drops the older answer); a pick puts "[[#id]] " (2.619.0, #4947). Only after the command: a "#word" typed by hand stays a tag.
// Sealed spaces too ([[#id]] is plain text in the decrypted page).
function wklv_tkHit(t) { return {tid: t.id, path: '#' + t.id, _label: '#' + t.id + ' ' + (t.title || '…'), _ic: 'check'}; }
function wklv_tkLocal(q) {
  const n = /^\d+$/.test(q) ? +q : 0, w = q.toLowerCase(), out = [];
  const exact = n && S.tasks.get(n); if (exact) out.push(exact);
  const all = [...S.tasks.values()].filter(t => t && t.id > 0 && t !== exact && (!w || (t.title || '').toLowerCase().includes(w) || String(t.id).startsWith(w)));
  all.sort((x, y) => (x.status ? 1 : 0) - (y.status ? 1 : 0) || String(y.updated_at || '').localeCompare(String(x.updated_at || '')));
  return out.concat(all).slice(0, 8);
}
// true = the task search owns the box (wiki.js wk_acUpdate asks it first)
function wklv_tk(ta, box) {
  const tk = WKLV.tk; if (!tk) return false;
  const s = ta.selectionStart, v = ta.value, m = ta.selectionEnd === s && s > tk.at && v[tk.at] === '#' ? /^#([^\s#\[\]]{0,40})$/.exec(v.slice(tk.at, s)) : null;
  if (!m) { WKLV.tk = null; return false; }
  const q = m[1].trim();
  const show = ts => {
    if (WKLV.tk !== tk || !box.isConnected) return;
    if (!ts.length) { box.classList.add('hidden'); WK.ac = null; return; }
    WK.ac = {hits: ts.map(wklv_tkHit), i: 0, from: tk.at, tk: true}; wk_acDraw(box);
  };
  const loc = wklv_tkLocal(q).slice(0, q.length < 2 ? 8 : 4);  // room for the server's hits
  show(loc);
  clearTimeout(tk.t); tk.q = q;
  if (q.length < 2 || S.me?.kid || !OUT.online || OUT.down) return true;
  tk.t = setTimeout(async () => {
    let r; try { r = await rawFetch('GET', '/api/search?limit=8&q=' + encodeURIComponent(q)); } catch { return; }  // offline / error: the local hits stay
    if (WKLV.tk !== tk || tk.q !== q) return;
    const have = new Set(loc.map(t => t.id));
    show(loc.concat((r.hits || []).map(h => h.task).filter(t => t && !have.has(t.id))).slice(0, 8));
  }, 250);
  return true;
}
function wklv_tkPick(ta, h) {
  const a = WK.ac.from, z = ta.selectionStart, txt = '[[#' + h.tid + ']] ';  // 2.619.0 (#4947): the task link of a page
  WKLV.tk = null; WK.ac = null; $('#wk-ac')?.classList.add('hidden');
  wem_rep(ta, a, z, txt, a + txt.length, a + txt.length);
}
// ---- 2.371.3 (#3152): reading styles -- a fixed choice (never CSS of its own): the space's default (WK.idx[sp].style, its
// admins / the private space's person set it, PUT /api/wiki/style) and the person's own choice (the account setting wkSt,
// LOOK_KEYS: '' = like the space, 'clear' = Clear even when the space says otherwise). Only a known value becomes a class.
const WKST = {book: N_('Book|reading style'), compact: N_('Compact'), notepad: N_('Notepad')};
function wkst_of(sp) {
  const own = LS.get('wkSt', ''), d = WK.idx[sp]?.style || '';
  const k = own === 'clear' ? '' : own && WKST[own] ? own : d;
  return WKST[k] ? k : '';
}
const wkst_cls = sp => (k => k ? ' wkst-' + k : '')(wkst_of(sp));
function wkst_items(p) {
  if (!p || S.me?.kind === 'agent') return [];
  return [{label: tr('Reading style…'), icon: 'book', more: wkst_menu(p.space)}];
}
function wkst_menu(sp) {
  const own = LS.get('wkSt', ''), d = WK.idx[sp]?.style || '', clear = tr('Clear|reading style'), name = k => k ? tr(WKST[k]) : clear;
  const mine = (k, label) => ({label, on: own === k, fn: () => { if (k) LS.set('wkSt', k); else LS.del('wkSt'); renderView(); }});
  const items = [{head: tr('For me')}, mine('', tr('Like the workspace ({0})', name(d))), mine('clear', name('')), ...Object.keys(WKST).map(k => mine(k, name(k)))];
  if (WK.idx[sp]?.may_style) {
    items.push({head: tr('Default of the workspace')}, ...['', ...Object.keys(WKST)].map(k => ({label: name(k), on: d === k, fn: async () => {
      try { await api('PUT', '/api/wiki/style', {space: sp, style: k}); } catch (e) { toast(e.message); return; }
      if (WK.idx[sp]) WK.idx[sp].style = k;
      renderView();
    }})));
  }
  return items;
}
// Ctrl/Cmd+K: a link (instead of the command field) while writing; Ctrl/Cmd+Shift+7 / 8 / 9: numbered list / list / checkbox
document.addEventListener('keydown', e => {
  const t = /** @type {any} */ (e.target); if (!wk_isTa(t) || !(e.ctrlKey || e.metaKey) || e.altKey || e.isComposing) return;
  const k = !e.shiftKey && e.key.toLowerCase() === 'k' ? 'ln' : e.shiftKey ? {Digit7: 'ol', Digit8: 'ul', Digit9: 'cb'}[e.code] : '';
  if (!k) return;
  e.preventDefault(); e.stopPropagation(); wem_fmt(k);
});
// ---- 2.1153.0 (#5525): a page as a presentation -- "Present" in the page's "…" menu (also for who may only read). Only a view:
// the page is drawn as when reading (wk_render; a page of an encrypted space is decrypted already) and cut into slides, nothing
// is stored. A slide starts at every heading of the top two levels ("#" and "##"; a page whose top heading is "###" cuts at
// those); text before the first heading becomes a title slide with the page's name. Full screen where the browser allows it
// (the overlay fills the window anyway, e.g. on an iPhone); arrow keys, Page keys, Space, Enter, Home / End, a swipe sideways
// (swipenav.js) and ‹ › in the bar leaf; Esc, ×, the phone's Back (backclose.js), leaving full screen or another address end it.
// A link on a slide ends it and opens. Checkboxes on a slide are only shown (they never tick the page).
const WKP = {/** @type {any} */ el: null, i: 0, /** @type {string[]} */ sl: [], sp: '', full: false, /** @type {any} */ sw: null};
/** @type {Record<string, number>} */
const WKP_LV = {H4: 4, H5: 5, H6: 6};  // renderMd draws "#" as <h4>, "##" as <h5>, "###" and deeper as <h6>
function wkp_items(p) {
  if (!p || !wk_bodyStrip(p.body).trim()) return [];
  return [{label: tr('Present'), icon: 'play', fn: () => wkp_open(p)}];
}
// the page's drawing cut into slides (the HTML of each)
function wkp_slides(p) {
  const box = document.createElement('div');
  box.innerHTML = wk_render(p);  // the page's own drawing (renderMd escapes), as #wk-md shows it
  const nodes = [...box.childNodes], lv = nodes.map(n => WKP_LV[/** @type {any} */ (n).tagName] || 0);
  const cut = Math.max(5, Math.min(7, ...lv.filter(Boolean)));
  /** @type {string[][]} */
  const out = [];
  nodes.forEach((n, k) => {
    if (!out.length || (lv[k] && lv[k] <= cut)) out.push([]);
    out[out.length - 1].push(n.nodeType === 1 ? /** @type {any} */ (n).outerHTML : esc(n.textContent || ''));
  });
  const first = nodes.findIndex(n => n.nodeType === 1 || (n.textContent || '').trim());
  if (out.length && !(lv[first] && lv[first] <= cut)) out[0].unshift(`<h4>${esc(wk_base(p.path))}</h4>`);  // the title slide
  return out.map(x => x.join('')).filter(x => x.replace(/<[^>]*>/g, '').trim() || /<(img|svg|table|pre|iframe|figure|video)\b/i.test(x));
}
const wkp_slideHtml = (/** @type {number} */ i) => `<section class="wkpslide md ntmd wkmd${esc(wkst_cls(WKP.sp))}" aria-roledescription="${esc(tr('Slide'))}" aria-label="${esc(tr('Slide {0} of {1}', i + 1, WKP.sl.length))}">${/*html-ok*/ WKP.sl[i] || '' /* the page's drawing (wk_render) */}</section>`;
function wkp_cbOff(/** @type {any} */ el) { for (const x of $$('input', el)) x.disabled = true; return el; }
async function wkp_open(p) {
  if (WK.dirty) await wk_flush();
  const pg = WK.pg?.id === p.id ? WK.pg : p;
  wkp_close();
  WKP.sl = wkp_slides(pg); WKP.sp = pg.space; WKP.i = 0;
  if (!WKP.sl.length) { toast(tr('Empty page.')); return; }
  const m = /** @type {any} */ (document.createElement('div'));
  m.id = 'wkp'; m.className = 'wkp'; m.tabIndex = -1;
  m.setAttribute('role', 'dialog'); m.setAttribute('aria-modal', 'true'); m.setAttribute('aria-label', tr('Presentation: {0}', wk_base(pg.path)));
  m.innerHTML = `<div class="wkpstage"></div><div class="wkpbar"><button type="button" class="iconbtn" data-wkp="-1" title="${esc(tr('Previous slide'))}" aria-label="${esc(tr('Previous slide'))}">${ic('left')}</button><span class="wkpno" role="status" aria-live="polite"></span><button type="button" class="iconbtn" data-wkp="1" title="${esc(tr('Next slide'))}" aria-label="${esc(tr('Next slide'))}">${ic('right')}</button><span class="wkpttl">${esc(wk_base(pg.path))}</span><button type="button" class="iconbtn" data-wkp="x" title="${esc(tr('End presentation'))}" aria-label="${esc(tr('End presentation'))}">${ic('x')}</button></div>`;
  document.body.appendChild(m);
  WKP.el = m;
  kb_push('dialog', m, {close: () => wkp_close()});
  m.addEventListener('click', wkp_click);
  m.addEventListener('keydown', wkp_key);
  // lazy-ok-begin: swOn runs only once swipenav.js is in (the typeof / loadModule below)
  const swOn = () => { if (WKP.el === m && !WKP.sw) WKP.sw = swn_attach(m, {area: t => t && !t.closest?.('.wkpbar') ? $('.wkpslide', m) : null, can: d => !!WKP.sl[WKP.i + d],
    go: d => wkp_go(WKP.i + d, true), peek: d => { const x = document.createElement('div'); x.innerHTML = wkp_slideHtml(WKP.i + d); return {el: wkp_cbOff(x.firstElementChild)}; }}); };
  // lazy-ok-end
  if (typeof swn_attach === 'function') swOn();
  else if (navigator.maxTouchPoints > 0 || isTouch()) loadModule('swipenav').then(swOn).catch(() => {});
  wkp_go(0);
  m.focus({preventScroll: true});
  try { if (!document.fullscreenElement && m.requestFullscreen) m.requestFullscreen().then(() => { WKP.full = WKP.el === m; }, () => {}); } catch { /* not allowed here */ }
}
function wkp_go(/** @type {number} */ i, swiped = false) {
  const m = WKP.el; if (!m) return;
  const was = WKP.i;
  WKP.i = Math.max(0, Math.min(WKP.sl.length - 1, i));
  const st = $('.wkpstage', m);
  st.innerHTML = wkp_slideHtml(WKP.i);
  wkp_cbOff(st); st.scrollTop = 0;  // sprung-ok: a new slide starts at its top (the person leafed)
  if (!swiped && was !== WKP.i && typeof swn_slideIn === 'function') swn_slideIn($('.wkpslide', st), WKP.i > was ? 1 : -1);
  $('.wkpno', m).textContent = `${WKP.i + 1} / ${WKP.sl.length}`;
  $('[data-wkp="-1"]', m).disabled = WKP.i === 0;
  $('[data-wkp="1"]', m).disabled = WKP.i >= WKP.sl.length - 1;
  if (typeof dg_draw === 'function') dg_draw(/** @type {any} */ (st));  // formulas / diagrams of the slide (diagram.js, loaded by wk_render when the page has any)
}
function wkp_close() {
  const m = WKP.el; if (!m) return;
  WKP.el = null; WKP.sw = null; kb_pop(m); m.remove();
  if (WKP.full && document.fullscreenElement) document.exitFullscreen?.()?.catch?.(() => {});
  WKP.full = false;
  $('#view [data-wk="pmenu"]')?.focus({preventScroll: true});
}
function wkp_click(/** @type {any} */ e) {
  const t = e.target, b = t.closest?.('[data-wkp]');
  if (b) { e.preventDefault(); if (b.dataset.wkp === 'x') wkp_close(); else wkp_go(WKP.i + +b.dataset.wkp); return; }
  if (WKP.sw?.recent?.()) { e.preventDefault(); return; }  // the end of a swipe opens nothing
  if (t.closest?.('a[href]')) setTimeout(wkp_close, 0);  // a link leaves the presentation (it opens after this click)
}
/** @type {Record<string, number>} */
const WKP_KEYS = {ArrowRight: 1, ArrowDown: 1, PageDown: 1, ' ': 1, Enter: 1, ArrowLeft: -1, ArrowUp: -1, PageUp: -1, Backspace: -1};
function wkp_key(/** @type {any} */ e) {
  if (e.altKey || e.ctrlKey || e.metaKey || e.isComposing) return;
  const k = e.key, onBtn = !!e.target.closest?.('button,a');
  let to = WKP_KEYS[k] || 0;
  if (k === ' ' && e.shiftKey) to = -1;
  if (to && !((k === 'Enter' || k === ' ') && onBtn)) wkp_go(WKP.i + to);
  else if (k === 'Home' || k === 'End') wkp_go(k === 'Home' ? 0 : WKP.sl.length - 1);
  else if (k === 'Escape') wkp_close();
  else return;
  e.preventDefault(); e.stopPropagation();
}
document.addEventListener('fullscreenchange', () => { if (WKP.el && WKP.full && !document.fullscreenElement) { WKP.full = false; wkp_close(); } });  // the browser's own Esc of full screen ends it too
window.addEventListener('hashchange', () => { if (WKP.el) wkp_close(); });
