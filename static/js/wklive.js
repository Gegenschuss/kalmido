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
