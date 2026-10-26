// @ts-check
/* Kalmido web client: 2.123.0 C (#2103, #2107, #2108) -- files of the file store, tables and tasks in knowledge pages (wiki.js).
   - In the editor: "Insert picture or file" uploads to the page (also pasting / dropping files into the text) or picks a
     file of the file store of the SAME space: ![name](/api/files/nodes/<id>/content) / [name](…) -- a reference, no copy.
   - [[datei:<path or id>]] / [[tabelle:<name or id>]] link a file / a table; typing [[datei: or [[tabelle: suggests them.
   - What a reader may see is asked once per page (POST /api/wiki/pages/<id>/refs, wiki/wkembed.py): a file one may not
     open shows "File not available" (no name), a link one may not open stays text. Contents come from the file store's
     own routes (its rights). A locked space works the same: the ids come from the text decrypted here.
   - Read mode: an open checkbox line "- [ ] …" gets a + button (several: "Open items as tasks"): the line becomes a task
     with the quick add syntax (date, #tags, !priority), in a list to choose (default: the basket); the line then ends with
     #<id> (the task link of the pages, which shows the task's state). Ticking in the page never changes the task.
     Tasks + the page text = ONE undo step.
   Classic script sharing the global scope with wiki.js (lazyload.js: module "wiki"). */
'use strict';

const WEM_EMBED_RE = /(!?)\[([^\[\]\n]*)\]\(\/api\/files\/nodes\/(\d{1,15})\/content\)/g;
const WEM_TREF_RE = /(?<![\w&/#])#\d{1,12}\b/;
// ---- what the reader may see (one question per page, more when the text gets new references)
function wem_st(p) { return p._wem || (p._wem = {files: {}, links: {}, asked: new Set(), got: new Set(), qf: new Set(), ql: new Set(), t: 0}); }
function wem_need(p, kind, key, ref) {
  const w = wem_st(p);
  if (w.asked.has(kind + key)) return;
  (kind === 'f' ? w.qf : w.ql).add(kind === 'f' ? +key : ref);
  w.asked.add(kind + key);
  if (!w.t) w.t = setTimeout(() => wem_ask(p), 0);
}
async function wem_ask(p) {
  const w = wem_st(p), files = [...w.qf].slice(0, 200), links = [...w.ql].slice(0, 200);
  w.qf.clear(); w.ql.clear(); w.t = 0;
  if (!files.length && !links.length) return;
  try {
    const r = await rawFetch('POST', `/api/wiki/pages/${p.id}/refs`, {files, links});
    Object.assign(w.files, r.files || {}); Object.assign(w.links, r.links || {});
  } catch { /* offline / no access: everything stays a placeholder */ }
  files.forEach(id => w.got.add('f' + id)); links.forEach(x => w.got.add('l' + x.toLowerCase()));
  if (S.route.mod === 'wiki' && WK.pg === p && !WK.edit) viewSafeRender();
  else if (WK.pg === p && WK.edit && typeof wklv_redraw === 'function') wklv_redraw();  // 2.350.0 B (#3147): the live preview's blocks
}
// ---- rendering (wiki.js wk_render: wem_cut before the Markdown, wem_put after it, wem_link for [[datei:…]] / [[tabelle:…]])
const wem_cut = (src, out) => src.replace(WEM_EMBED_RE, (_, bang, label, id) => { out.push({img: !!bang, label, id}); return `⁣WEM${out.length - 1}⁣`; });
function wem_link(p, t, label) {
  const m = /^\s*(datei|tabelle)\s*:\s*(.+?)\s*$/i.exec(t);
  if (!m) return esc(t);
  const kind = m[1].toLowerCase(), key = kind + ':' + m[2].toLowerCase(), w = wem_st(p);
  wem_need(p, 'l', key, kind + ':' + m[2]);
  const x = w.links[key], lb = label || (x ? esc(x.name) : esc(t));  // label is HTML already (wk_render)
  if (!x) return `<span class="wemref">${lb}</span>`;  // not visible / not there: plain text, no name from the server
  return x.kind === 'sheet' ? `<a href="${esc(x.url)}" class="wklink wemlink">${ic('sheet', 's')}${lb}</a>`
    : `<a href="${esc(x.url)}" target="_blank" rel="noopener" class="wklink wemlink">${ic('file', 's')}${lb}</a>`;
}
function wem_put(p, h, ems) {
  const w = wem_st(p);
  h = h.replace(/⁣WEM(\d+)⁣/g, (m, i) => {
    const e = ems[+i]; if (!e) return '';
    wem_need(p, 'f', e.id);
    const x = w.files[e.id];
    if (!x) return `<span class="wemna" role="img" aria-label="${esc(tr('File not available'))}">${ic('file', 's')}<span>${esc(w.got.has('f' + e.id) ? tr('File not available') : tr('Loading…'))}</span></span>`;
    return e.img && x.image ? `<a href="${esc(x.url)}" target="_blank" rel="noopener"><img class="wkimg" src="${esc(x.url)}" alt="${esc(e.label)}" loading="lazy"></a>`
      : `<a href="${esc(x.url)}" target="_blank" rel="noopener" class="wklink wemlink">${ic('file', 's')}${esc(e.label || x.name)}</a>`;
  });
  // the state of a linked task (#123): done = struck through (shown only; the page text does not change)
  h = h.replace(/class="tref" data-tref="(\d+)"/g, (m, id) => taskById(+id)?.status === 2 ? `class="tref wemdone" data-tref="${id}"` : m);
  return wem_cbHtml(p, h);
}
// ---- open checkbox lines -> tasks
function wem_cbLines(body) {  // the open "- [ ] …" lines as renderMd draws them (no frontmatter, no code blocks), in order
  const ls = String(body || '').split('\n'), out = [];
  let i = 0, code = false;
  if (/^---[ \t]*\r?$/.test(ls[0] || '')) { const e = ls.findIndex((l, k) => k > 0 && /^---[ \t]*\r?$/.test(l)); if (e > 0) i = e + 1; }
  for (; i < ls.length; i++) {
    const ln = ls[i];
    if (/^\s*```/.test(ln)) { code = !code; continue; }
    if (code || /^\s*>/.test(ln)) continue;
    const m = /^\s*[-*]\s+\[( |x|X)\]\s*(.*)/.exec(ln);
    if (m && m[1] === ' ') out.push({raw: ln, text: m[2].replace(/\r$/, '').trim(), has: WEM_TREF_RE.test(m[2])});
  }
  return out;
}
const wem_mayTask = p => WK.idx[p.space]?.mayWrite !== false && S.me?.kind !== 'agent' && typeof createTask === 'function';
function wem_cbHtml(p, h) {
  if (!wem_mayTask(p)) return h;
  const ls = wem_cbLines(p.body), n = (h.match(/<li class="cb ">/g) || []).length;
  if (!ls.length || n !== ls.length) return h;  // the drawing does not match the text (a table, a quote): no buttons
  let k = 0;
  h = h.replace(/<li class="cb ">(<input[^>]*>)/g, m => {
    const L = ls[k++]; if (L.has || !L.text) return m;
    return `${m}<button type="button" class="iconbtn wemcb" data-wem="cb" data-k="${k - 1}" title="${esc(tr('Create as task'))}" aria-label="${esc(tr('Create as task'))}: ${esc(L.text.slice(0, 60))}">${ic('plus', 's')}</button>`;
  });
  const open = ls.filter(L => !L.has && L.text).length;
  return open > 1 ? `<div class="wemcbbar"><button type="button" class="btn sm" data-wem="cbs">${ic('check', 's')}${esc(tr('Open items as tasks'))} · ${open}</button></div>${h}` : h;
}
function wem_lists() {
  const ib = inbox();
  return [ib, ...sideOrder().filter(l => l && !l.is_inbox && !l.archived && canEditList(l.id))].filter(Boolean);
}
async function wem_cbDlg(p, ks) {
  await wk_flush();
  const all = wem_cbLines(p.body), pick = ks.map(k => all[k]).filter(L => L && !L.has && L.text);
  if (!pick.length) return;
  const ls = wem_lists(), lock = wk_e2e(p.space);
  const lockHint = lid => lock && !listById(lid)?.e2e;
  /** @type {any} */
  const md = modal(`<h3>${ic('check', 's')} ${esc(tr('Create tasks'))}</h3>
    ${pick.length > 1 ? `<ul class="wemcbl">${pick.map((L, i) => `<li><label><input type="checkbox" data-wemi="${i}" checked> <span>${esc(L.text)}</span></label></li>`).join('')}</ul>` : `<p class="wemcb1">${esc(pick[0].text)}</p>`}
    <div class="row"><label for="wem-list">${esc(tr('Project'))}</label><select id="wem-list">${ls.map(l => `<option value="${l.id}">${esc(lname(l))}</option>`).join('')}</select></div>
    <p class="muted wemhint">${esc(tr('Dates, #tags and !priority like in quick add. Ticking it in the page does not change the task.'))}</p>
    <p class="shint keep wemlock" ${lockHint(ls[0]?.id) ? '' : 'hidden'}>${ic('lock', 's')} ${esc(tr('This page is end-to-end encrypted, the chosen project is not: the task titles are stored without that lock.'))}</p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${esc(tr('Cancel'))}</button><button type="button" class="btn pri" data-m="ok">${ic('plus', 's')} ${esc(tr('Create tasks'))}</button></div>`);
  md.classList.add('wemdlg');
  const sel = $('#wem-list', md);
  sel.addEventListener('change', () => { $('.wemlock', md).hidden = !lockHint(+sel.value); });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { modalClose(md); return; }
    const use = pick.length > 1 ? pick.filter((_, i) => $(`[data-wemi="${i}"]`, md)?.checked) : pick;
    if (!use.length) return;
    b.disabled = true; modalClose(md);
    wem_cbRun(p, use, +sel.value);
  });
}
async function wem_cbRun(p, lines, lid) {
  const made = [];
  await histGroup(async () => {
    for (const L of lines) {
      const r = parseQuick(L.text, new Set());
      const body = {title: (r.title || L.text).slice(0, 500), list_id: r.list_id || lid, priority: r.priority ?? 0, tags: r.tags || [], repeat: r.repeat || ''};
      if (r.due) body.due = r.due;
      if (r.due_time) body.due_time = r.due_time;
      try { made.push({L, t: await createTask(body)}); } catch { break; }  // api() said why; what was made stays one step
    }
    if (!made.length) return;
    const pairs = made.map(({L, t}) => [L.raw, L.raw.replace(/\s+$/, '') + ' #' + t.id + (L.raw.endsWith('\r') ? '\r' : '')]);
    try { await wem_swap(p, pairs, true); } catch (e) { toast(e.message); }
    const e = histAdd({label: tr('Create tasks'), ids: [], snaps: [], lids: [], wsp: p.space,
      undo: async () => { await wem_swap(p, pairs, false); return {skipped: []}; },
      redo: async () => { await wem_swap(p, pairs, true); return {skipped: []}; }});
    histToast(trn('{0} task created', '{0} tasks created', made.length), e);
  }, tr('Create tasks'));
}
// the page text: line a -> b (fwd) or back, on the newest text of the server (someone may have saved in between)
async function wem_swap(p, pairs, fwd) {
  const url = '/api/wiki/pages/' + p.id, cur = await rawFetch('GET', url);
  if (typeof wkePage === 'function') await wkePage(cur);
  const ls = String(cur.body || '').split('\n');
  let n = 0;
  for (const [a, b] of pairs) { const [x, y] = fwd ? [a, b] : [b, a]; const i = ls.indexOf(x); if (i >= 0) { ls[i] = y; n++; } }
  if (!n) return;
  const patch = {body: ls.join('\n'), expect_updated_at: cur.updated_at};
  const r = typeof wkeApi === 'function' ? await wkeApi('PATCH', url, patch, p.space) : await rawFetch('PATCH', url, patch);
  if (WK.pg?.id === p.id) Object.assign(WK.pg, r, {backlinks: WK.pg.backlinks, _v: S.v});
  if (S.route.mod === 'wiki') viewSafeRender();
}
// ---- the editor: insert a picture / file (upload or from the file store), paste / drop files
function wem_bar(p) {
  return `<div class="wembar" role="toolbar" aria-label="${esc(tr('Formatting'))}">${wem_fmtBtns()}<button type="button" class="btn sm" data-wem="ins" aria-haspopup="menu">${ic('picture', 's')}<span class="wemlbl">${esc(tr('Insert picture or file'))}</span></button><span class="shint">${esc(tr('Markdown: # heading, - list, [[Page]] links a page, #123 a task'))}</span></div>`;  // 2.298.0 C (#3187): the syntax behind (i)
}
// 2.276.0 B (#3043): the formatting bar -- writes the same Markdown one would type (heading, bold, italic, list, checkbox, link);
// a click wraps the selection or prefixes the selected lines, a second click takes it away again. Edits go through insertText,
// so the browser's own undo works; the field's input handler saves like typing. Ctrl/Cmd+B / I in the field (2.350.0 B #3149: K = link, wklive.js).
const WEM_FI = {h: 'M5 4V16M15 4V16M5 10H15', b: 'M6 4H11A3 3 0 0 1 11 10H6ZM6 10H12A3.1 3.1 0 0 1 12 16H6Z', i: 'M9 4H15M5 16H11M12 4L8 16'};
const wem_fi = k => WEM_FI[k] ? `<svg class="i s" viewBox="0 0 20 20" aria-hidden="true">${icPath(WEM_FI[k])}</svg>` : ic(k, 's');
const WEM_FMT = [['h', 'h', N_('Heading')], ['b', 'b', N_('Bold')], ['i', 'i', N_('Italic')], ['ul', 'list', N_('List')], ['cb', 'select', N_('Checkbox')], ['ln', 'link', N_('Link')]];
function wem_fmtBtns() {
  const kb = /Mac|iP(hone|ad)/.test(navigator.platform || '') ? '⌘' : 'Ctrl+';
  return WEM_FMT.map(([k, icn, lb]) => { const t = tr(lb) + (k === 'b' ? ` (${kb}B)` : k === 'i' ? ` (${kb}I)` : '');
    return `<button type="button" class="iconbtn wemfmt" data-wemf="${k}" title="${esc(t)}" aria-label="${esc(tr(lb))}">${wem_fi(icn)}</button>`; }).join('') + '<span class="wemsep" aria-hidden="true"></span>';
}
// one replacement of [a, b) as ONE undo step, then select [s0, s1]
function wem_rep(ta, a, b, txt, s0, s1) {
  const v = ta.value;
  ta.focus(); ta.setSelectionRange(a, b);
  let ok = false; try { ok = document.execCommand('insertText', false, txt); } catch { /* not supported */ }
  if (!ok || (ta.value === v && txt !== v.slice(a, b))) { ta.setRangeText(txt, a, b, 'end'); ta.dispatchEvent(new Event('input', {bubbles: true})); }
  ta.setSelectionRange(s0, s1);
}
function wem_wrap(ta, m) {
  const v = ta.value; let s = ta.selectionStart, e = ta.selectionEnd;
  while (e > s && /\s/.test(v[e - 1])) e--;  // "word " selected by a double click: the marks hug the word
  while (s < e && /\s/.test(v[s])) s++;
  const n = m.length;
  if (s >= n && v.slice(s - n, s) === m && v.slice(e, e + n) === m && (n > 1 || (v[s - n - 1] !== '*' && v[e + n] !== '*'))) {  // marked already: take the marks away
    wem_rep(ta, s - n, e + n, v.slice(s, e), s - n, e - n); return;
  }
  const t = v.slice(s, e) || tr('Text');
  wem_rep(ta, s, e, m + t + m, s + n, s + n + t.length);
}
function wem_fmtLink(ta) {
  const v = ta.value, s = ta.selectionStart, e = ta.selectionEnd, t = v.slice(s, e).replace(/[[\]\n]/g, ' ').trim();
  if (/^https?:\/\/\S+$/.test(t)) { const md = `[${tr('Link text')}](${t})`; wem_rep(ta, s, e, md, s + 1, s + 1 + tr('Link text').length); return; }
  const lb = t || tr('Link text'), md = `[${lb}](https://)`;
  wem_rep(ta, s, e, md, t ? s + lb.length + 3 : s + 1, t ? s + md.length - 1 : s + 1 + lb.length);  // text there: the address is next
}
const WEM_LP = {ol: /^(\s*)\d{1,9}[.)][ \t]+/, h: /^(\s*)#{1,6}[ \t]+/, ul: /^(\s*)[-*+][ \t]+(?!\[[ xX]\])/, cb: /^(\s*)[-*+][ \t]+\[[ xX]\][ \t]?/};
const WEM_ANY = /^(\s*)(?:#{1,6}[ \t]+|[-*+][ \t]+\[[ xX]\][ \t]?|[-*+][ \t]+|\d{1,9}[.)][ \t]+)/;
function wem_lines(ta, k) {
  const v = ta.value, s = ta.selectionStart, e0 = ta.selectionEnd;
  const e = e0 > s && v[e0 - 1] === '\n' ? e0 - 1 : e0;  // whole lines selected: the next line is not part of it
  const a = v.lastIndexOf('\n', s - 1) + 1, z = v.indexOf('\n', e) < 0 ? v.length : v.indexOf('\n', e);
  const ls = v.slice(a, z).split('\n'), use = ls.map(l => ls.length === 1 || l.trim() !== '');
  const off = ls.every((l, i) => !use[i] || WEM_LP[k].test(l));  // every line has it already: take it away
  const pre = k === 'h' ? '## ' : k === 'cb' ? '- [ ] ' : k === 'ol' ? '1. ' : '- ';  // 2.350.0 B (#3149): + numbered
  const out = ls.map((l, i) => !use[i] ? l : off ? l.replace(WEM_LP[k], '$1') : l.replace(WEM_ANY, '$1').replace(/^(\s*)/, '$1' + pre)).join('\n');
  if (out === v.slice(a, z)) return;
  if (ls.length === 1) { const c = Math.max(a, Math.min(s + out.length - (z - a), a + out.length)); wem_rep(ta, a, z, out, c, c); }
  else wem_rep(ta, a, z, out, a, a + out.length);
}
function wem_fmt(k) {
  const ta = wk_ta(); if (!ta) return;  // 2.350.0 B (#3147): + the live preview's block
  if (k === 'b') wem_wrap(ta, '**');
  else if (k === 'i') wem_wrap(ta, '*');
  else if (k === 'ln') wem_fmtLink(ta);
  else if (WEM_LP[k]) wem_lines(ta, k);
}
function wem_insert(txt, at) {
  const ta = wk_ta(); if (!ta) return;
  const v = ta.value, a = Math.min(at?.[0] ?? ta.selectionStart ?? v.length, v.length), b = Math.min(at?.[1] ?? ta.selectionEnd ?? a, v.length);
  const pre = v.slice(0, a), sep = pre && !pre.endsWith('\n') ? '\n' : '', post = v.slice(b), tail = post.startsWith('\n') ? '' : '\n';
  ta.value = pre + sep + txt + tail + post;
  const pos = (pre + sep + txt + tail).length; ta.setSelectionRange(pos, pos); ta.focus();
  ta.dispatchEvent(new Event('input', {bubbles: true}));  // 2.350.0 B (#3147): saves like typing (wiki.js), the live block follows
}
async function wem_upload(p, files, at) {
  if (!p || !files.length) return;
  if (wk_e2e(p.space)) { toast(tr('Files cannot be added to a page of a locked space yet')); return; }
  const fd = new FormData(); files.forEach(f => fd.append('file', f));
  toast(trn('Uploading {0} file…', 'Uploading {0} files…', files.length));
  let r; try { r = await rawFetch('POST', `/api/wiki/pages/${p.id}/files`, fd); } catch (e) { toast(e.message); return; }
  const fs = r.files || []; if (!fs.length) return;
  p.files = [...(p.files || []), ...fs];  // no new drawing while typing (the text would be drawn again)
  wem_insert(fs.map(wka_md).join('\n'), at);
  const ids = fs.map(f => f.id);
  const e = histAdd({label: tr('Attach files'), ids: [], snaps: [], lids: [], wsp: p.space,
    undo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids: [], files: ids}); wk_after(p.space); return {skipped: []}; },
    redo: async () => { await rawFetch('POST', '/api/wiki/restore', {ids: [], files: ids}); wk_after(p.space); return {skipped: []}; }});
  histToast(trn('{0} file attached', '{0} files attached', fs.length), e);
}
function wem_device(p, at) {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.multiple = true; inp.accept = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.svg,application/pdf,image/*';
  inp.onchange = () => wem_upload(p, [...(inp.files || [])], at);
  inp.click();
}
const wem_md = n => `${(n.mime || '').startsWith('image/') ? '!' : ''}[${String(n.name).replace(/[[\]\n]/g, '')}](/api/files/nodes/${n.id}/content)`;
// the file store of the page's space: browse folders or search, a click inserts the reference
function wem_pick(p, at) {
  const st = {parent: null, q: '', n: 0};
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${ic('folder', 's')} ${esc(tr('From the file store'))}</h3><span class="spacer"></span><button type="button" class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="ssearch">${ic('search', 's')}<input id="wem-q" type="search" placeholder="${esc(tr('Find a file'))}" aria-label="${esc(tr('Find a file'))}" autocomplete="off"></div>
    <nav class="wemcrumbs" id="wem-crumbs" aria-label="${esc(tr('Path'))}"></nav>
    <div class="wempick" id="wem-pick" role="list"></div>
    <p class="muted wemhint">${esc(tr('Only files of this space. Readers of the page see a file only if they may open it in the file store.'))}</p>`);
  md.classList.add('wemdlg');
  const list = $('#wem-pick', md), crumbs = $('#wem-crumbs', md);
  const load = async () => {
    const n = ++st.n, sp = encodeURIComponent(p.space);
    list.innerHTML = `<p class="muted">${esc(tr('Loading…'))}</p>`;
    let j; try { j = st.q ? await rawFetch('GET', `/api/files/search?q=${encodeURIComponent(st.q)}&space=${sp}`) : await rawFetch('GET', st.parent ? `/api/files?parent=${st.parent}` : `/api/files?space=${sp}`); }
    catch (e) { if (n === st.n) list.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
    if (n !== st.n) return;
    const its = (j.items || []).filter(x => !x.no_access && (x.kind === 'file' || (x.kind === 'folder' && !st.q)));
    crumbs.innerHTML = st.q ? '' : `<button type="button" class="btn sm" data-wemc="">${esc(p.space === 'private' ? tr('Private|workspace') : wk_spaceName(p.space))}</button>${(j.crumbs || []).map(c => `<span aria-hidden="true">/</span><button type="button" class="btn sm" data-wemc="${c.id}">${esc(c.name)}</button>`).join('')}`;
    list.innerHTML = its.length ? its.map(x => `<button type="button" role="listitem" class="wemit" data-wemn="${x.id}" data-k="${x.kind}">${ic(x.kind === 'folder' ? 'folder' : (x.mime || '').startsWith('image/') ? 'picture' : 'file', 's')}<span class="wemn">${esc(x.name)}</span>${x.kind === 'file' ? `<small class="muted">${x.folder ? esc(x.folder) + ' · ' : ''}${fmtSize(x.size || 0)}</small>` : ''}</button>`).join('')
      : `<p class="muted">${esc(st.q ? tr('Nothing found') : tr('No files here yet.'))}</p>`;
    list._its = its;
  };
  let qt = 0;
  $('#wem-q', md).addEventListener('input', e => { clearTimeout(qt); qt = setTimeout(() => { st.q = e.target.value.trim(); load(); }, 250); });
  md.addEventListener('click', e => {
    if (/** @type {any} */ (e.target).closest('[data-m="close"]')) { modalClose(md); return; }
    const c = /** @type {any} */ (e.target).closest('[data-wemc]'); if (c) { st.parent = +c.dataset.wemc || null; load(); return; }
    const b = /** @type {any} */ (e.target).closest('[data-wemn]'); if (!b) return;
    const x = (list._its || []).find(i => i.id === +b.dataset.wemn); if (!x) return;
    if (x.kind === 'folder') { st.parent = x.id; load(); return; }
    modalClose(md);
    wem_insert(wem_md(x), at);
  });
  load();
  setTimeout(() => $('#wem-q', md)?.focus(), 30);
}
function wem_insMenu(a, p) {
  const ta = wk_ta(), at = ta ? [ta.selectionStart, ta.selectionEnd] : null;
  menu(a, [...(wk_e2e(p.space) ? [] : [{label: tr('Upload from this device…'), icon: 'upload', fn: () => wem_device(p, at)}]),
    ...(feat('files') ? [{label: tr('From the file store…'), icon: 'folder', fn: () => wem_pick(p, at)}] : [])]);
}
// 2.126.2 A (#2363): with the on-screen keyboard open the list sits just above it (fixed to the visual viewport); desktop keeps the CSS place
function wem_acPlace(box) {
  const vv = window.visualViewport; if (!vv) return;
  const keyb = window.innerHeight - vv.height - vv.offsetTop > 80;
  if (!keyb) { box.style.position = box.style.left = box.style.right = box.style.bottom = ''; return; }
  const wr = box.parentElement?.getBoundingClientRect(); if (!wr) return;
  box.style.position = 'fixed';
  box.style.left = Math.max(wr.left, 0) + 8 + 'px';
  box.style.right = Math.max(window.innerWidth - wr.right, 0) + 8 + 'px';
  box.style.bottom = Math.max(window.innerHeight - (vv.offsetTop + vv.height), 0) + 8 + 'px';
  if (!box._wemvv) {
    const f = () => {
      if (!box.isConnected || box.classList.contains('hidden')) { vv.removeEventListener('resize', f); vv.removeEventListener('scroll', f); box._wemvv = null; return; }
      wem_acPlace(box);
    };
    box._wemvv = f; vv.addEventListener('resize', f); vv.addEventListener('scroll', f);
  }
}
// ---- [[datei: / [[tabelle: suggestions (wiki.js wk_acUpdate hands over what follows [[)
const WEM_AC = {n: 0, sheets: {}};
function wem_ac(ta, box, q, from) {
  const m = /^\s*(datei|tabelle)\s*:\s*(.*)$/i.exec(q); if (!m) return false;
  const kind = m[1].toLowerCase(), word = m[2].trim(), p = WK.pg; if (!p) return true;
  const n = ++WEM_AC.n;
  const show = hits => {
    if (n !== WEM_AC.n || !box.isConnected) return;
    if (!hits.length) { box.classList.add('hidden'); WK.ac = null; return; }
    WK.ac = {hits, i: 0, from}; wk_acDraw(box);
  };
  const clean = s => String(s).replace(/[[\]|#\n]/g, '').trim();
  clearTimeout(WEM_AC.t);
  WEM_AC.t = setTimeout(async () => {
    try {
      if (kind === 'datei') {
        if (!feat('files')) return show([]);
        const sp = encodeURIComponent(p.space);
        const j = word ? await rawFetch('GET', `/api/files/search?q=${encodeURIComponent(word)}&space=${sp}`) : await rawFetch('GET', `/api/files?space=${sp}`);
        show((j.items || []).filter(x => x.kind === 'file' && !x.no_access).slice(0, 8).map(x => ({path: `${m[1]}:${x.id}|${clean(x.name)}`, _label: x.name, _ic: 'file'})));
      } else {
        const c = WEM_AC.sheets[p.space];
        const all = c && c.v === S.v ? c.list : (WEM_AC.sheets[p.space] = {v: S.v, list: (await rawFetch('GET', '/api/sheets?space=' + encodeURIComponent(p.space))).sheets || []}).list;
        const w = word.toLowerCase();
        show(all.filter(x => (x.title || '').toLowerCase().includes(w)).slice(0, 8).map(x => ({path: `${m[1]}:${x.id}|${clean(x.title || tr('Untitled table'))}`, _label: x.title || tr('Untitled table'), _ic: 'sheet'})));
      }
    } catch { show([]); }
  }, 200);
  return true;
}
// ---- events (own listeners: data-wem)
document.addEventListener('click', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-wem]'); if (!a || !$('#view')?.contains(a)) return;
  const p = WK.pg; if (!p) return;
  const k = a.dataset.wem;
  if (k === 'ins') wem_insMenu(a, p);
  else if (k === 'cb') { e.preventDefault(); wem_cbDlg(p, [+a.dataset.k]); }
  else if (k === 'cbs') wem_cbDlg(p, wem_cbLines(p.body).map((_, i) => i));
});
// 2.276.0 B (#3043): the bar keeps the field's focus and selection (no blur = no save, the phone's keyboard stays)
document.addEventListener('mousedown', e => { if (/** @type {any} */ (e.target).closest?.('[data-wemf]')) e.preventDefault(); });
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-wemf]'); if (!b || !$('#view')?.contains(b)) return;
  e.preventDefault(); wem_fmt(b.dataset.wemf);
});
document.addEventListener('keydown', e => {
  if (!wk_isTa(e.target) || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
  const k = e.key.toLowerCase(); if (k !== 'b' && k !== 'i') return;
  e.preventDefault(); wem_fmt(k);
});
document.addEventListener('paste', e => {
  if (!wk_isTa(e.target)) return;
  const fs = [...(e.clipboardData?.files || [])]; if (!fs.length) return;
  e.preventDefault(); wem_upload(WK.pg, fs);
});
document.addEventListener('dragover', e => { if (wk_isTa(e.target) && [...(e.dataTransfer?.types || [])].includes('Files')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
document.addEventListener('drop', e => {
  if (!wk_isTa(e.target)) return;
  const fs = [...(e.dataTransfer?.files || [])]; if (!fs.length) return;
  e.preventDefault(); wem_upload(WK.pg, fs);
});
