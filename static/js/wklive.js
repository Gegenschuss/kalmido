// @ts-check
/* Kalmido web client: 2.350.0 B (#3147, #3149) -- the knowledge editor with live preview and slash commands.
   - Live preview (#3147): the page text is cut into blocks (heading, paragraph, list, table, quote, code / mind map fence,
     front matter, blank lines). Every block is drawn with the page renderer (wiki.js wk_render); the block with the cursor
     is a growing <textarea id="wk-blk"> with its raw Markdown. The page stays ONE Markdown string: saving, conflicts,
     offline outbox, history and locked spaces get the same text as the plain text editor (wiki.js wk_flush -> wklv_src).
     A click into a drawn block opens it near that place, arrow up / down at the edge moves to the next block, Backspace
     at the start joins with the block above, Enter on an empty last line starts a new block, Esc shows everything drawn.
     A textarea per block (no contenteditable): the phone's keyboard, selection and undo stay the browser's own.
   - The plain text editor stays as it was (#wk-body): LS "wkEd" = 'text' (an account setting like the appearance,
     dialogs.js LOOK_KEYS), switched in the page's "…" menu and, 2.382.0 (#3128), with "Source" / "Preview" in the bar.
   - Slash commands (#3149, both editors): "/" at the start of a line opens a menu (heading, lists, table, code, mind
     map, formula, diagram (2.382.0 #3153), picture / file, embedded table, page link, date, templates); typing filters it, arrows / Enter / Esc like the
     [[ suggestions (they share #wk-ac). Ctrl/Cmd+K link, Ctrl/Cmd+Shift+7 / 8 / 9 numbered list / list / checkbox.
   Classic script sharing the global scope with wiki.js (lazyload.js: module "wiki"). */
'use strict';

const wklv_on = () => LS.get('wkEd', '') !== 'text';
/** @type {any} */
const WKLV = {pid: 0, body: '', bl: [], k: -1, pre: '', post: '', cache: new Map(), down: false, t: 0, tk: /** @type {any} */ (null)};  // 2.371.3 (#3333): tk = the task search after "/" -> "Task (#)"
// ---- the blocks: line ranges [a, b) that cover every line; joined with '\n' they give the text back exactly
const WKLV_FENCE = /^\s{0,3}(`{3,}|~{3,})/, WKLV_LI = /^\s*(?:[-*+]|\d{1,9}[.)])[ \t]+/, WKLV_HR = /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/;
const wklv_kind = l => /^\s*$/.test(l) ? 'gap' : WKLV_FENCE.test(l) ? 'code' : /^\s{0,3}#{1,6}(\s|$)/.test(l) ? 'h' : WKLV_HR.test(l) ? 'hr'
  : /^\s*\|/.test(l) ? 'table' : /^\s{0,3}>/.test(l) ? 'quote' : WKLV_LI.test(l) ? 'list' : 'p';
function wklv_split(body) {
  const ls = String(body).split('\n'), out = [];
  let i = 0;
  if (/^---[ \t]*$/.test(ls[0] || '')) {  // front matter (wk_bodyStrip): up to its closing line
    const z = ls.findIndex((l, j) => j > 0 && /^---[ \t]*$/.test(l));
    if (z > 0) { out.push({a: 0, b: z + 1, t: 'fm'}); i = z + 1; }
  }
  while (i < ls.length) {
    const a = i, t = wklv_kind(ls[i]);
    if (t === 'code') { const f = WKLV_FENCE.exec(ls[i])[1]; i++; while (i < ls.length && !ls[i].trim().startsWith(f)) i++; i = Math.min(i + 1, ls.length); }
    else if (t === 'h' || t === 'hr') i++;
    else if (t === 'gap') while (i < ls.length && wklv_kind(ls[i]) === 'gap') i++;
    else if (t === 'list') { i++; while (i < ls.length && ls[i].trim() && (WKLV_LI.test(ls[i]) || /^\s/.test(ls[i]))) i++; }
    else if (t === 'p') { i++; while (i < ls.length && wklv_kind(ls[i]) === 'p') i++; }
    else { i++; while (i < ls.length && wklv_kind(ls[i]) === t) i++; }  // table, quote
    out.push({a, b: i, t});
  }
  return out;
}
// the blocks with their place in the text: s / e = start / end offset, txt = their raw Markdown
function wklv_blocks(body) {
  const ls = String(body).split('\n'), offs = [];
  let n = 0; for (const l of ls) { offs.push(n); n += l.length + 1; }
  return wklv_split(body).map(x => { const txt = ls.slice(x.a, x.b).join('\n'); return {...x, s: offs[x.a], e: offs[x.a] + txt.length, txt, n: x.b - x.a}; });
}
const wklv_ta = () => /** @type {any} */ ($('#wk-blk'));
// the page text now (the open block's field counts)
function wklv_cur() { const ta = wklv_ta(); return ta && WKLV.k >= 0 ? WKLV.pre + ta.value + WKLV.post : WKLV.body; }
// a drawn block after the open one moved by what was typed since the drawing
const wklv_at = i => WKLV.bl[i].s + (WKLV.k >= 0 && i > WKLV.k ? wklv_cur().length - WKLV.len0 : 0);
// wiki.js wk_flush: the text to save while the live editor is open on page p (null = not this editor)
function wklv_src(p) { return p && WKLV.pid === p.id && (wklv_ta() || $('#wk-live')) ? {value: wklv_cur()} : null; }
function wklv_blockHtml(p, x) {
  if (x.t === 'gap') return '';
  if (x.t === 'fm') return `<pre class="wklvfm">${esc(x.txt)}</pre>`;
  let h = WKLV.cache.get(x.txt);
  if (h == null) {
    h = wk_render(Object.assign({}, p, {body: x.txt}))  // the "as a task" buttons count the lines of the whole page (read mode has them)
      .replace(/<div class="wemcbbar">[\s\S]*?<\/div>/, '').replace(/<button type="button" class="iconbtn wemcb"[\s\S]*?<\/button>/g, '');
    WKLV.cache.set(x.txt, h);
  }
  return h;
}
// the editor's place in wiki.js wk_pageHtml (instead of the textarea #wk-body)
function wklv_html(p) {
  if (WKLV.pid !== p.id || !WK.dirty) { if (WKLV.pid !== p.id) WKLV.cache.clear(); WKLV.pid = p.id; WKLV.body = String(p.body || ''); WKLV.k = -1; }
  if (typeof wem_st === 'function') wem_st(p);  // the block copies share the page's file / link answers (wkembed.js)
  if (!WKLV.body.trim()) WKLV.k = 0;  // an empty page opens its (only) block
  return `<div id="wk-live" class="wklive md ntmd wkmd">${wklv_inner(p)}</div>`;
}
function wklv_inner(p) {
  const bl = WKLV.bl = wklv_blocks(WKLV.body);
  if (WKLV.k >= bl.length) WKLV.k = bl.length - 1;
  const x = bl[WKLV.k];
  WKLV.pre = x ? WKLV.body.slice(0, x.s) : ''; WKLV.post = x ? WKLV.body.slice(x.e) : ''; WKLV.len0 = WKLV.body.length;
  return bl.map((b, i) => i === WKLV.k
    ? `<textarea id="wk-blk" class="wkblk" rows="1" aria-label="${esc(tr('Text'))}" placeholder="${esc(tr('Write … ([[Page]], #123, / for commands)'))}">${esc(b.txt)}</textarea>`
    : `<div class="wklb wklb-${b.t}${b.t === 'gap' ? ' wkgap' + Math.min(b.n, 4) : ''}" data-lb="${i}">${wklv_blockHtml(p, b)}</div>`).join('');
}
function wklv_fit(ta) { if (!ta) return; ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; }
// draw again with the block that holds offset caret open (null = everything drawn)
function wklv_draw(caret, focus) {
  const box = $('#wk-live'), p = WK.pg; if (!box || !p || WKLV.pid !== p.id) return;
  WKLV.body = wklv_cur();
  if (caret == null) WKLV.k = -1;
  else { const bl = wklv_blocks(WKLV.body), k = bl.findIndex(x => caret <= x.e); WKLV.k = k < 0 ? bl.length - 1 : k; }
  box.innerHTML = wklv_inner(p);
  WK.ac = null; $('#wk-ac')?.classList.add('hidden');
  const ta = wklv_ta(); if (!ta) return;
  wklv_fit(ta);
  if (focus) { const c = Math.max(0, Math.min((caret ?? 0) - WKLV.pre.length, ta.value.length)); ta.focus({preventScroll: true}); ta.setSelectionRange(c, c); }
}
const wklv_open = (off, focus = true) => wklv_draw(off, focus);
function wklv_close() { if (WKLV.k >= 0) wklv_draw(null, false); }
// a new text (a joined line, a ticked box …): drawn again, open at caret
function wklv_set(body, caret) { WKLV.body = body; WKLV.k = -1; wklv_draw(caret, caret != null); wk_queue(); }
// after the file / link answers came (wkembed.js wem_ask): the drawn blocks again, the open one stays
function wklv_redraw() {
  const box = $('#wk-live'); if (!box || !WK.pg) return;
  WKLV.cache.clear();
  for (const el of box.querySelectorAll('.wklb[data-lb]')) { const x = WKLV.bl[+el.dataset.lb]; if (x) el.innerHTML = wklv_blockHtml(WK.pg, x); }
}
// the place in the raw text of a click into a drawn block: its visible text before the click, matched letter by letter
function wklv_clickOff(el, e, raw) {
  const d = /** @type {any} */ (document);
  const cp = d.caretPositionFromPoint?.(e.clientX, e.clientY), cr = !cp && d.caretRangeFromPoint?.(e.clientX, e.clientY);
  const node = cp ? cp.offsetNode : cr?.startContainer, at = cp ? cp.offset : cr?.startOffset;
  if (!node || !el.contains(node)) return raw.length;
  const r = document.createRange(); r.setStart(el, 0);
  try { r.setEnd(node, at); } catch { return raw.length; }
  let j = 0;
  for (const c of r.toString()) { if (/\s/.test(c)) continue; const n = raw.indexOf(c, j); if (n >= 0) j = n + 1; }
  return Math.min(j, raw.length);
}
// the next block in a direction that is not one plain blank line
function wklv_step(dir) {
  for (let i = WKLV.k + dir; i >= 0 && i < WKLV.bl.length; i += dir) { const x = WKLV.bl[i]; if (x.t !== 'gap' || x.n > 1) return i; }
  return -1;
}
function wklv_key(e) {
  const ta = e.target, v = ta.value, s = ta.selectionStart, z = ta.selectionEnd;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); wklv_close(); return; }
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || s !== z) return;
  if (e.key === 'ArrowUp' && !v.slice(0, s).includes('\n')) {
    const i = wklv_step(-1); if (i < 0) return;
    e.preventDefault(); wklv_open(WKLV.bl[i].e);
  } else if (e.key === 'ArrowDown' && !v.slice(z).includes('\n')) {
    const i = wklv_step(1); if (i < 0) return;
    e.preventDefault(); wklv_open(wklv_at(i));
  } else if (e.key === 'Backspace' && s === 0 && WKLV.pre) {  // joins with the block above (the line break goes)
    e.preventDefault(); wklv_set(WKLV.pre.slice(0, -1) + v + WKLV.post, WKLV.pre.length - 1);
  } else if (e.key === 'Enter' && s === v.length && /\n[ \t]*$/.test(v) && WKLV.bl[WKLV.k]?.t !== 'fm'
    && !['gap', 'code'].includes(wklv_kind(v.split('\n').find(l => l.trim()) || ''))) {  // Enter on an empty last line: a new block below
    e.preventDefault(); wklv_set(WKLV.pre + v + '\n' + WKLV.post, WKLV.pre.length + v.length + 1);
  }
}
// the field left for something outside the editor (not a menu / dialog it opened): everything drawn
function wklv_blur() {
  clearTimeout(WKLV.t);
  WKLV.t = setTimeout(() => {
    if (WKLV.down) { wklv_blur(); return; }
    const a = document.activeElement;
    if (!$('#wk-live') || a?.id === 'wk-blk' || a?.closest?.('.wkedwrap, .modal, #pop') || $('.modal, #pop:not(.hidden)')) return;
    wklv_close();
  }, 250);
}
document.addEventListener('pointerdown', e => { WKLV.down = !!/** @type {any} */ (e.target).closest?.('#wk-live'); }, true);
document.addEventListener('pointerup', () => { setTimeout(() => { WKLV.down = false; }, 0); }, true);
document.addEventListener('pointercancel', () => { WKLV.down = false; }, true);
document.addEventListener('click', e => {
  const t = /** @type {any} */ (e.target), box = t.closest?.('#wk-live'); if (!box || t.id === 'wk-blk') return;
  const el = t.closest('.wklb[data-lb]'), i = el ? +el.dataset.lb : -1, x = WKLV.bl[i];
  if (x && t.matches('input[type="checkbox"][data-mdline]')) {  // a box that can be ticked: its line in this block
    e.preventDefault(); e.stopPropagation();
    const ls = x.txt.split('\n'), n = +t.dataset.mdline, at = wklv_at(i), cur = wklv_cur();
    if (!ls[n]) return;
    ls[n] = ls[n].replace(/\[( |x|X)\]/, (_, c) => c === ' ' ? '[x]' : '[ ]');
    wklv_set(cur.slice(0, at) + ls.join('\n') + cur.slice(at + x.txt.length), null);
    return;
  }
  if (t.closest('a[href]:not([href="#wiki"]), a[data-wk="create"], button, input, select, summary, label, video, audio')) return;  // links, missing pages, players work as in reading
  e.preventDefault();
  if (!x) { wklv_open(wklv_cur().length); return; }  // below the last block: at the end
  wklv_open(wklv_at(i) + (x.t === 'gap' ? 0 : wklv_clickOff(el, e, x.txt)));
}, true);
document.addEventListener('input', e => {
  const ta = /** @type {any} */ (e.target); if (ta.id !== 'wk-blk') return;
  WKLV.body = WKLV.pre + ta.value + WKLV.post; wklv_fit(ta);
});
document.addEventListener('keydown', e => {
  const ta = /** @type {any} */ (e.target);
  if (ta.id === 'wk-blk' && !e.defaultPrevented && !e.isComposing) wklv_key(e);
});
document.addEventListener('focusout', e => { if (/** @type {any} */ (e.target).id === 'wk-blk') wklv_blur(); });
// the suggestions / commands just below the open block (a phone with its keyboard open keeps wkembed.js wem_acPlace)
function wklv_acPlace(box) {
  const ta = wklv_ta();
  if (!ta || box.style.position === 'fixed') { box.style.top = ''; return; }
  const wr = box.parentElement?.getBoundingClientRect(); if (!wr) return;
  box.style.top = Math.round(ta.getBoundingClientRect().bottom - wr.top + 4) + 'px';  // the list sits in .wkedwrap, the field in #wk-live below the bar
}
// ---- plain text <-> live preview (an account setting, LOOK_KEYS): the page's "…" entry and, 2.382.0 (#3128), the button
// "Source" / "Preview" in the formatting bar (wkembed.js wem_bar); both name what a click shows
async function wklv_toggle() {
  await wk_flush();
  if (wklv_on()) LS.set('wkEd', 'text'); else LS.del('wkEd');
  WKLV.pid = 0; renderView();
  if (WK.edit) setTimeout(() => { const ta = wk_ta(); if (ta) ta.focus(); else if (WKLV.k >= 0) wklv_ta()?.focus(); }, 30);
}
const wklv_toLbl = () => wklv_on() ? N_('Source') : N_('Preview');
function wklv_menuItem() { return {label: tr(wklv_toLbl()), icon: wklv_on() ? 'code' : 'edit', fn: wklv_toggle}; }
function wklv_srcBtn() {
  const t = tr(wklv_toLbl());
  return `<button type="button" class="btn sm wemsrc" data-wem="src" title="${esc(t)}">${ic(wklv_on() ? 'code' : 'edit', 's')}<span class="wemlbl">${esc(t)}</span></button>`;
}
// ---- slash commands (#3149): "/" at the start of a line, in both editors (wiki.js wk_acUpdate / wk_acPick)
/** @type {any[]} */
const WKLV_CMDS = [
  ['h', 'h', N_('Heading'), 'heading überschrift', '## '],
  ['ul', 'list', N_('List'), 'list liste bullet', '- '],
  ['ol', 'list', N_('Numbered list'), 'numbered nummer ordered 1.', '1. '],
  ['cb', 'select', N_('Checkbox'), 'checkbox todo häkchen aufgabe', '- [ ] '],
  ['tb', 'sheet', N_('Table'), 'table tabelle', null],
  ['code', 'code', N_('Code'), 'code', null],
  ['mm', 'mindmap', N_('Mind map'), 'mindmap mind map', null],
  ['math', 'calc', N_('Formula'), 'formula formel math latex katex', null],  // 2.382.0 (#3153): drawn by diagram.js
  ['mmd', 'chart', N_('Diagram'), 'diagram diagramm mermaid flowchart chart', null],
  ['file', 'picture', N_('Picture or file'), 'picture image bild file datei upload', null],
  ['emb', 'sheet', N_('Embed a table'), 'embed einbetten table tabelle', '[[tabelle:'],
  ['ln', 'link', N_('Link to a page'), 'link verweis page seite [[', '[['],
  ['embp', 'note', N_('Embed a page'), 'embed einbetten page seite ![[', '![['],  // 2.371.2 (#3151)
  ['date', 'cal', N_('Date'), 'date datum today heute', null],
  ['task', 'check', N_('Task (#)'), 'task aufgabe # ticket', null],  // 2.371.3 (#3333): a search over the tasks the person sees
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
    menu(ta, [{label: tr('Upload from this device…'), icon: 'upload', fn: () => wem_device(p, at)}, {label: tr('From the file store…'), icon: 'folder', fn: () => wem_pick(p, at)}]);
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
// key, a newer query drops the older answer); a pick puts "#id ". Only after the command: a "#word" typed by hand stays a tag.
// Sealed spaces too (#id is plain text in the decrypted page).
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
  const a = WK.ac.from, z = ta.selectionStart, txt = '#' + h.tid + ' ';
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
  const items = [{head: tr('For me')}, mine('', tr('Like the space ({0})', name(d))), mine('clear', name('')), ...Object.keys(WKST).map(k => mine(k, name(k)))];
  if (WK.idx[sp]?.may_style) {
    items.push({head: tr('Default of the space')}, ...['', ...Object.keys(WKST)].map(k => ({label: name(k), on: d === k, fn: async () => {
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
