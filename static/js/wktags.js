// @ts-check
/* Kalmido web client: 2.371 (#3150) -- tags of knowledge pages and the ```abfrage block (wiki.js draws both).
   Tags: #word in the text (starting with a letter; #123 stays a task) or "tags:" in the frontmatter. In the text they are
   links to the tag's list (#wiki/t/<tag>, under "All" #wiki/s/<space>/t/<tag>); the panel has a group "Tags" below the
   folders, a phone the list below the pages. The ```abfrage block (```query) shows pages with tags / in a folder / with a
   property, or their open checkboxes, as a list or a table -- fresh on every change (S.v). The server answers both
   (wiki/wktags.py: tags as hashes, only pages the reader may read); a space with the lock (or offline, from the copy)
   does the same here with the texts this browser opened, same rules as the server. Nothing is stored.
   Loaded with the module "wiki" (lazyload.js). Classic script sharing the global scope with the others. */
'use strict';

const WKT = {list: {}, pages: {}, q: {}, busy: {}};
const WKT_ONE = /^\p{L}[\p{L}\p{N}_/-]{0,59}$/u;
const WKTG_RE = /(?<![\p{L}\p{N}_&/#\\])#(\p{L}[\p{L}\p{N}_/-]{0,59})/gu;
const WKT_CUT = [/^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/, /^[ \t]*(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^[ \t]*\1[ \t]*$|(?![\s\S]))/gm,
  /`[^`\n]*`/g, /\[\[[^\[\]\n]*\]\]/g, /\]\([^()\s]*\)/g, /<[^<>\n]{1,500}>/g];  // as wktags.py _WKT_CUT
const WKT_MAX = 50;
// [[key, shown], ...] of a text: the frontmatter's tags first, then the #tags (wktags.py wkt_tags)
function wkt_tags(text) {
  const out = new Map(), add = t => { t = String(t).trim().replace(/^#+/, '').replace(/[/-]+$/, ''); if (t && WKT_ONE.test(t) && out.size < WKT_MAX && !out.has(t.toLowerCase())) out.set(t.toLowerCase(), t); };
  text = String(text || '');
  const fm = typeof wkeFront === 'function' ? wkeFront(text) : {};
  for (const k of ['tags', 'tag']) { const v = fm[k]; for (const x of Array.isArray(v) ? v : String(v || '').split(/[,\s]+/)) add(x); }
  let s = text;
  for (const rx of WKT_CUT) s = s.replace(rx, ' ');
  for (const m of s.matchAll(WKTG_RE)) add(m[1]);
  return [...out.entries()];
}
const wkt_go = (tag, sp) => (wk_all() ? 'wiki/s/' + sp + '/' : 'wiki/') + 't/' + encodeURIComponent(tag);
// the texts are here: a space with the lock (opened in the browser) or the offline copy
const wkt_local = sp => wk_e2e(sp) || !!WK.idx[sp]?.off;
const wkt_tpl = p => /^(templates|vorlagen)\//i.test(p.path || '');
async function wkt_fetch(key, url, sp) {
  if (WKT.busy[key]) return;
  WKT.busy[key] = true;
  const box = key[0] === 'l' ? WKT.list : key[0] === 'p' ? WKT.pages : WKT.q, k = key.slice(2);
  try { box[k] = {v: S.v, j: await rawFetch('GET', url)}; }
  catch (e) { if (e.message === 'auth') return; box[k] = {v: S.v, j: null, err: e instanceof Offline ? tr('Knowledge pages are only available online.') : e.message}; }
  finally { WKT.busy[key] = false; }
  if (S.route.mod === 'wiki') wk_redraw();
  if (sp && typeof sbb_sync === 'function') sbb_sync('wiki');
}
// the tags of a space [{tag, n}] (null = loading)
function wkt_spaceTags(sp) {
  const d = WK.idx[sp];
  if (wkt_local(sp)) {
    if (!d?.pages) return null;
    const n = new Map(), shown = new Map();
    for (const p of d.pages) if (!wkt_tpl(p)) for (const [k, t] of wkt_tags(p.body)) { n.set(k, (n.get(k) || 0) + 1); if (!shown.has(k)) shown.set(k, t); }
    return [...n.keys()].sort((a, b) => n.get(b) - n.get(a) || (a < b ? -1 : a > b ? 1 : 0)).slice(0, 300).map(k => ({tag: shown.get(k), n: n.get(k)}));
  }
  const c = WKT.list[sp];
  if (!c || c.v !== S.v) wkt_fetch('l:' + sp, '/api/wiki/tags?space=' + encodeURIComponent(sp), sp);
  return c ? c.j?.tags || [] : null;
}
// the pages of a space with one tag [{id, path}] (null = loading)
function wkt_tagPages(sp, tag) {
  const key = tag.toLowerCase();
  if (wkt_local(sp)) { const d = WK.idx[sp]; return d?.pages ? d.pages.filter(p => !wkt_tpl(p) && wkt_tags(p.body).some(([k]) => k === key)).sort((a, b) => a.path.localeCompare(b.path, LOCALE())) : null; }
  const c = WKT.pages[sp + '\n' + key];
  if (!c || c.v !== S.v) wkt_fetch('p:' + sp + '\n' + key, '/api/wiki/tags?space=' + encodeURIComponent(sp) + '&tag=' + encodeURIComponent(tag));
  return c ? c.j?.pages || [] : null;
}
// the group "Tags" of the panel: a node of sbb_treeHtml (closed until opened), its tags below it; null = no tags
function wkt_panelNode(sp) {
  const tags = WK.idx[sp]?.pages ? wkt_spaceTags(sp) : null; if (!tags?.length) return null;
  const at = S.route.mod === 'wiki' && wk_open() === sp ? (S.route.wtag || '').toLowerCase() : '';
  return {k: 'wkt:' + sp, name: tr('Tags'), icon: 'tag', go: wkt_go(tags[0].tag, sp), on: false, kids: true, open: !!at,
    sub: () => tags.map(t => ({k: 'wkt:' + sp + ':' + t.tag.toLowerCase(), name: '#' + t.tag, icon: 'tag', go: wkt_go(t.tag, sp), on: at === t.tag.toLowerCase(), kids: false}))};
}
// a phone: the tags below the space's pages
function wkt_sideHtml(sp) {
  const tags = WK.idx[sp]?.pages ? wkt_spaceTags(sp) : null; if (!tags?.length) return '';
  return `<nav class="wktags" aria-label="${esc(tr('Tags'))}"><h4>${ic('tag', 's')}${esc(tr('Tags'))}</h4><p>${tags.slice(0, 60).map(t => `<a href="#${esc(wkt_go(t.tag, sp))}" class="wktag">#${esc(t.tag)}</a>`).join(' ')}</p></nav>`;
}
// the open tag (#wiki/t/<tag>): its pages as rows like a folder's
function wkt_viewHtml(sp, tag) {
  const ps = wkt_tagPages(sp, tag), c = wkt_local(sp) ? null : WKT.pages[sp + '\n' + tag.toLowerCase()];
  const rows = ps == null ? `<div class="muted mhint">${tr('Loading…')}</div>` : c?.err ? `<div class="muted mhint">${esc(c.err)}</div>`
    : ps.length ? `<ul class="wktree wkdlist" aria-label="${esc(tr('Pages'))}">${ps.map(p => `<li class="wkrow"><a href="#wiki/${p.id}" class="wkitem">${ic('note', 's')}<span>${esc(p.path)}</span></a></li>`).join('')}</ul>`
    : `<div class="empty">${tr('No page has this tag.')}</div>`;
  return `<div class="nthead"><div class="wktitle"><nav class="wkcrumbs" aria-label="${esc(tr('Path'))}"><a href="#${esc(wk_home(sp))}">${esc(wk_rootName(sp))}</a><span aria-hidden="true">/</span><span>${esc(tr('Tags'))}</span></nav><h2 class="wktagh">${ic('tag', 's')}#${esc(tag)}</h2></div></div><nav id="wk-res" aria-label="${esc(tr('Pages'))}">${rows}</nav>`;
}
// the #tags of a rendered text as links (not inside code / pre / links; the html is the app's Markdown)
function wkt_linkHtml(h, sp) {
  let skip = 0;
  return h.replace(/<(\/?)([a-zA-Z][\w-]*)[^>]*>|(?<![\p{L}\p{N}_&/#\\])#(\p{L}[\p{L}\p{N}_/-]{0,59})/gu, (m, cl, tag, t) => {
    if (tag) { if (/^(code|pre|a)$/i.test(tag)) skip = Math.max(0, skip + (cl ? -1 : 1)); return m; }
    if (skip > 0) return m;
    const x = t.replace(/[/-]+$/, ''), rest = t.slice(x.length);
    return `<a href="#${esc(wkt_go(wk_unesc(x), sp))}" class="wktag">#${x}</a>${rest}`;
  });
}
// the frontmatter's tags as links (wk_attrsHtml)
const wkt_attrHtml = (v, sp) => (Array.isArray(v) ? v : String(v || '').split(/[,\s]+/)).map(x => String(x).trim().replace(/^#+/, '')).filter(x => WKT_ONE.test(x))
  .map(x => `<a href="#${esc(wkt_go(x, sp))}" class="wktag">#${esc(x)}</a>`).join(' ');

// ---- the ```abfrage block (wktags.py wkq_parse / wkq_match / the route): the same keys and rules
const WKQ_RE = /^```(?:abfrage|query)[ \t]*\r?\n([\s\S]*?)^```[ \t]*$/gim;
const WKQ_KEYS = {tag: 'tag', tags: 'tag', ordner: 'folder', folder: 'folder', eigenschaft: 'prop', property: 'prop', zeige: 'show', show: 'show',
  sortiere: 'sort', sort: 'sort', grenze: 'limit', limit: 'limit', als: 'as', as: 'as', spalten: 'cols', columns: 'cols'};
const WKQ_SHOW = {seiten: 'pages', pages: 'pages', aufgaben: 'tasks', tasks: 'tasks', checkboxen: 'tasks'};
const WKQ_AS = {liste: 'list', list: 'list', tabelle: 'table', table: 'table'};
const WKQ_SORT = {name: 'name', 'geändert': 'updated', geaendert: 'updated', updated: 'updated', erstellt: 'created', created: 'created'};
const WKQ_DESC = {absteigend: true, desc: true, aufsteigend: false, asc: false};
function wkq_parse(text) {
  const q = {tags: [], folder: '', props: [], show: 'pages', sort: 'name', desc: false, limit: 50, as: 'list', cols: [], errors: []};
  for (const ln of String(text || '').split(/\r?\n/).slice(0, 40)) {
    const s = ln.trim(); if (!s || s.startsWith('//')) continue;
    const m = /^([^\P{L}\d][\p{L}\p{N}_]*)\s*:\s*(.*)$/u.exec(s), k = m ? WKQ_KEYS[m[1].toLowerCase()] : null;
    if (!m || !k) { q.errors.push(s.slice(0, 80)); continue; }
    const v = m[2].trim(), lv = v.toLowerCase();
    if (k === 'tag') { for (let x of v.split(/[,\s]+/)) { x = x.trim().replace(/^#+/, '').replace(/[/-]+$/, ''); if (x && WKT_ONE.test(x) && !q.tags.includes(x.toLowerCase())) q.tags.push(x.toLowerCase()); } }
    else if (k === 'folder') q.folder = v.replace(/^[/ ]+|[/ ]+$/g, '').toLowerCase();
    else if (k === 'prop') { const i = v.indexOf('='), pk = (i < 0 ? v : v.slice(0, i)).trim(); if (pk) q.props.push([pk.slice(0, 40), i < 0 ? null : v.slice(i + 1).trim().replace(/^["']+|["']+$/g, '').toLowerCase()]); }
    else if (k === 'show' && WKQ_SHOW[lv]) q.show = WKQ_SHOW[lv];
    else if (k === 'as' && WKQ_AS[lv]) q.as = WKQ_AS[lv];
    else if (k === 'sort' && v) { const parts = v.split(/\s+/); if (parts.length > 1 && parts[parts.length - 1].toLowerCase() in WKQ_DESC) q.desc = WKQ_DESC[parts.pop().toLowerCase()]; const w = parts.join(' '); q.sort = WKQ_SORT[w.toLowerCase()] || 'p:' + w.slice(0, 40); }
    else if (k === 'limit') { const n = /^-?\d+$/.test(v) ? parseInt(v, 10) : NaN; if (Number.isNaN(n)) q.errors.push(s.slice(0, 80)); else q.limit = Math.max(1, Math.min(200, n)); }
    else if (k === 'cols') q.cols = v.split(',').map(x => x.trim().slice(0, 40)).filter(Boolean).slice(0, 8);
    else q.errors.push(s.slice(0, 80));
  }
  return q;
}
const wkq_attr = (a, k) => { for (const [x, v] of Object.entries(a || {})) if (x.toLowerCase() === k.toLowerCase()) return v; return null; };
function wkq_match(q, path, attrs) {
  const lp = String(path).toLowerCase();
  if (q.folder && !lp.startsWith(q.folder + '/')) return false;
  for (const [k, v] of q.props) {
    const a = wkq_attr(attrs, k);
    if (a == null || a === '' || Array.isArray(a) && !a.length) return false;
    if (v != null && !(Array.isArray(a) ? a.map(x => String(x).toLowerCase()) : [String(a).toLowerCase()]).includes(v)) return false;
  }
  return true;
}
function wkq_sortKey(q, d) {
  if (q.sort === 'name') return [0, d.path.toLowerCase()];
  if (q.sort === 'updated' || q.sort === 'created') return [0, d[q.sort + '_at'] || ''];
  let a = wkq_attr(d.attrs, q.sort.slice(2)); a = Array.isArray(a) ? a.join(', ') : a;
  return a == null || a === '' ? [1, ''] : [0, String(a).toLowerCase()];
}
const wkq_cmp = (x, y) => x < y ? -1 : x > y ? 1 : 0;
const WKQ_TASK = /^[ \t]*(?:>[ \t]?)*[-*+][ \t]+\[ \][ \t]+(.+?)[ \t]*$/gm;
function wkq_tasks(text) {  // [[line, text]] of the open checkboxes, not in code blocks
  const t = String(text || '').replace(/^[ \t]*(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^[ \t]*\1[ \t]*$|(?![\s\S]))/gm, m => '\n'.repeat((m.match(/\n/g) || []).length));
  return [...t.matchAll(WKQ_TASK)].map(m => [t.slice(0, m.index).split('\n').length, m[1].slice(0, 300)]);
}
// the query run here over pages with their texts ({id, path, attrs, body, updated_at, created_at}): the route's answer
function wkq_run(q, pages, self) {
  const ds = pages.filter(p => p.id !== self && !wkt_tpl(p) && (!q.tags.length || (ks => q.tags.every(t => ks.has(t)))(new Set(wkt_tags(p.body).map(x => x[0])))) && wkq_match(q, p.path, p.attrs));
  ds.sort((a, b) => { const x = wkq_sortKey(q, a), y = wkq_sortKey(q, b); return q.desc ? x[0] - y[0] || wkq_cmp(y[1], x[1]) || wkq_cmp(b.path.toLowerCase(), a.path.toLowerCase()) : wkq_cmp(x[0], y[0]) || wkq_cmp(x[1], y[1]) || wkq_cmp(a.path.toLowerCase(), b.path.toLowerCase()); });
  const out = {show: q.show, as: q.as, cols: q.cols, errors: q.errors, pages: [], tasks: []};
  if (q.show === 'tasks') {
    const ts = ds.slice(0, 500).flatMap(d => wkq_tasks(d.body).map(([line, text]) => ({page_id: d.id, path: d.path, line, text})));
    return {...out, tasks: ts.slice(0, q.limit), total: ts.length, more: ts.length > q.limit};
  }
  const keep = new Set([...q.cols, ...q.props.map(x => x[0])].map(x => x.toLowerCase()));
  return {...out, pages: ds.slice(0, q.limit).map(d => ({id: d.id, path: d.path, updated_at: d.updated_at, created_at: d.created_at, attrs: Object.fromEntries(Object.entries(d.attrs || {}).filter(([k]) => keep.has(k.toLowerCase())))})), total: ds.length, more: ds.length > q.limit};
}
// the block in a page p: the result from the server (fresh on every change) or, with the texts here, run in the browser
function wkq_html(p, text) {
  let j = null, err = '';
  if (wkt_local(p.space)) { const d = WK.idx[p.space]; if (!d?.pages) { wk_load(p.space); } else j = wkq_run(wkq_parse(text), d.pages, p.id); }
  else {
    const key = p.id + '\n' + text, c = WKT.q[key];
    if (!c || c.v !== S.v) wkt_fetch('q:' + key, '/api/wiki/query?page=' + p.id + '&q=' + encodeURIComponent(String(text).slice(0, 2000)));
    if (c?.j?.e2e) { const d = WK.idx[p.space]; j = d?.pages ? wkq_run(wkq_parse(text), d.pages, p.id) : null; }
    else { j = c?.j || null; err = c?.err || ''; }
  }
  if (!j) return `<p class="muted wkq">${esc(err || tr('Loading…'))}</p>`;
  const bad = j.errors?.length ? `<p class="muted wkqerr">${ic('info', 's')}${esc(tr('Not understood: {0}', j.errors.join(' · ')))}</p>` : '';
  const more = j.more ? `<p class="muted wkqmore">${esc(tr('{0} of {1} shown', (j.show === 'tasks' ? j.tasks : j.pages).length, j.total))}</p>` : '';
  const link = (id, path) => `<a href="#wiki/${id}" class="wklink">${esc(wk_base(path))}</a>`;
  if (j.show === 'tasks') {
    if (!j.tasks.length) return `<div class="wkq">${bad}<p class="muted">${tr('No open checkbox matches.')}</p></div>`;
    return `<div class="wkq">${bad}<ul class="wkqtasks">${j.tasks.map(t => `<li><input type="checkbox" disabled aria-hidden="true"> <span>${esc(t.text)}</span> <small class="muted">${link(t.page_id, t.path)}</small></li>`).join('')}</ul>${more}</div>`;
  }
  if (!j.pages.length) return `<div class="wkq">${bad}<p class="muted">${tr('No page matches this query.')}</p></div>`;
  const val = v => esc(Array.isArray(v) ? v.join(', ') : v == null ? '' : String(v));
  if (j.as === 'table') {
    const cols = j.cols?.length ? j.cols : null;
    return `<div class="wkq">${bad}<div class="mdtbl"><table class="wkqt"><thead><tr><th>${tr('Page')}</th>${cols ? cols.map(c => `<th>${esc(c)}</th>`).join('') : `<th>${tr('Changed')}</th>`}</tr></thead><tbody>${j.pages.map(r => `<tr><td>${link(r.id, r.path)}</td>${cols ? cols.map(c => `<td>${val(wkq_attr(r.attrs, c))}</td>`).join('') : `<td>${esc(fmtWhen(r.updated_at))}</td>`}</tr>`).join('')}</tbody></table></div>${more}</div>`;
  }
  return `<div class="wkq">${bad}<ul class="wkqlist">${j.pages.map(r => `<li>${link(r.id, r.path)}${wk_dirOf(r.path) ? ` <small class="muted">${esc(wk_dirOf(r.path))}</small>` : ''}</li>`).join('')}</ul>${more}</div>`;
}
