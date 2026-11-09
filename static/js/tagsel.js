// @ts-check
/* Kalmido web client: 2.122.0 B (#2099 #2294 #2295) parts the file store (ablage.js) and the documents (docs.js) share,
   loaded on demand (lazyload.js module tagsel; the documents module needs it, the file store loads it when it opens):
   - the tag picker: the tags of a workspace as buttons to switch on / off plus a field for a new tag (dt_pick);
   - tag buttons for a filter that switch between "with", "without" and off (dt_pills / dt_cycle);
   - choosing a range with Shift (dt_rsClick): a click sets the anchor, Shift-click chooses everything between the anchor and
     the target in the order shown (a target already chosen: the range is unchosen), Ctrl / Cmd-click switches one. The
     anchor belongs to one list (another folder / filter = a new anchor). Phones: no Shift, nothing changes there.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- the tag picker: resolves with the chosen names, or null (cancelled). all: [{name}], cur: [names] chosen at the start.
// 2.742.0 (#4862): the tag field (tf_html below) in a dialog, the same as in a document; known: only names of all (remove)
async function dt_pick({title, all, cur, ok, known = false}) {
  const at = {root: /** @type {HTMLElement|null} */ (null)};
  const r = await askDialog({title, ok: ok || tr('Save'), cancel: tr('Cancel'),
    html: tf_html({id: 'ts-new', vals: (cur || []).map(String), all: all || [], label: tr('Tags'), ph: tr('Add a tag…'), noNew: known}),
    after: md => { md.classList.add('tsdlg'); at.root = $('.tfld', md); setTimeout(() => $('#ts-new', md)?.focus(), 0); }});
  tf_close();
  const root = at.root;
  if (r === false || r == null || !root) return null;
  const inp = /** @type {HTMLInputElement|null} */ (root.querySelector('.tfin'));
  if (inp && tf_norm(inp.value)) { const v = inp.value; inp.value = ''; tf_add(root, v.split(',')); }  // typed, not yet taken
  return tf_vals(root);
}

// ---- filter buttons: st = {name: 'in' | 'not'}; a click goes off -> in -> not -> off (dt_cycle)
const dt_pills = (list, st, attr, tri = true) => (list || []).map(x => {
  const s = st[x.name] || '';
  return `<button type="button" class="tsp ${s ? 'tsp-' + s : ''}" data-${attr}="${esc(x.name)}" aria-pressed="${s ? 'true' : 'false'}" title="${esc(tri ? tr('Tap: with · without · off') : x.name)}">${s === 'not' ? `<span class="tsig" aria-hidden="true">−</span><span class="sr">${tr('not')} </span>` : s ? '<span class="tsig" aria-hidden="true">+</span>' : ''}${esc(x.name)}</button>`;
}).join('');
function dt_cycle(st, name, tri = true) {
  const s = st[name];
  if (!s) st[name] = 'in'; else if (s === 'in' && tri) st[name] = 'not'; else delete st[name];
  return st;
}

// ---- choosing a range with Shift
const dt_el = e => /** @type {HTMLElement} */ (e.target);
const DT_RS = {key: '', id: null};
const dt_rsMouse = e => e.pointerType ? e.pointerType === 'mouse' : !(typeof isTouch === 'function' && isTouch());  // Shift-click turns choosing on with a mouse only
function dt_rsReset() { DT_RS.key = ''; DT_RS.id = null; }
function dt_rsAnchor(key, id) { DT_RS.key = key; DT_RS.id = id; }
// e: the click; key: the list it is in; id: the target; ids: the order shown; has(id) / set(id, on): the caller's choice
function dt_rsClick(e, key, id, ids, has, set) {
  if (DT_RS.key !== key) dt_rsAnchor(key, null);
  if (e.shiftKey && DT_RS.id != null && DT_RS.id !== id) {
    const a = ids.indexOf(DT_RS.id), b = ids.indexOf(id);
    if (a >= 0 && b >= 0) {
      const on = !has(id);
      for (const x of ids.slice(Math.min(a, b), Math.max(a, b) + 1)) set(x, on);
      return;  // the anchor stays: the next Shift-click spans from it again
    }
  }
  set(id, !has(id)); dt_rsAnchor(key, id);
}
// Shift + mouse button in a list: no text marking (the click chooses instead)
document.addEventListener('mousedown', e => { if (e.shiftKey && dt_el(e).closest?.('.ablist, .dc-grid')) e.preventDefault(); });

// ---- the file store (ablage.js): tags on the rows and in the details, set with the picker; the tag filter of a space
// (with / without these tags, every one / one of them) shows the matching files and folders of the whole space with
// their path. The filter belongs to the space it was set in; ablage.js asks through typeof guards (this file loads on
// demand when the file store opens).
const DT_AB = {sp: '', st: {}, ids: {}, mode: 'any', res: null};
const dt_abOn = sp => !!sp && sp !== 'trash' && DT_AB.sp === sp && Object.keys(DT_AB.st).length > 0;
const dt_abTags = n => n.tags?.length ? `<span class="abtags">${n.tags.slice(0, 3).map(t => `<span class="abtag">${esc(t.name)}</span>`).join('')}${n.tags.length > 3 ? `<span class="abtag">+${n.tags.length - 3}</span>` : ''}</span>` : '';
const dt_abBtn = sp => sp && sp !== 'trash' ? `<button type="button" class="btn sm ${dt_abOn(sp) ? 'on' : ''}" data-dtab="filter" data-sp="${esc(sp)}" aria-haspopup="dialog">${ic('tag', 's')} ${tr('Tags')}</button>` : '';
function dt_abParams(sp) {
  const p = new URLSearchParams({space: sp});
  for (const [name, s] of Object.entries(DT_AB.st)) p.append(s === 'not' ? 'not' : 'tag', (DT_AB.ids[name] || []).join(','));
  if (DT_AB.mode === 'all') p.set('mode', 'all');
  return p.toString();
}
async function dt_abLoad(sp) {
  const key = dt_abParams(sp);
  DT_AB.res = {key, items: null};
  let j; try { j = await api('GET', '/api/files/tagged?' + key); } catch { j = {items: [], more: false}; }
  if (DT_AB.res?.key !== key) return;
  DT_AB.res = {key, items: j.items || [], more: !!j.more};
  ab_draw();
}
function dt_abBody(sp) {
  const key = dt_abParams(sp), r = DT_AB.res;
  if (!r || r.key !== key) setTimeout(() => dt_abLoad(sp), 0);
  const items = r && r.key === key ? r.items : null;
  const fx = Object.entries(DT_AB.st).map(([name, s]) => `<button type="button" class="tsfx ${s === 'not' ? 'not' : ''}" data-dtabx="${esc(name)}" aria-label="${esc(tr('Remove filter {0}', name))}">${s === 'not' ? `${tr('not')} ` : ''}${esc(name)} ${ic('x', 's')}</button>`).join('');
  const bar = `<div class="tsfbar" role="group" aria-label="${esc(tr('Filter'))}">${fx}${Object.keys(DT_AB.st).length > 1 ? `<span class="tsfn">${DT_AB.mode === 'all' ? tr('every one') : tr('one of them')}</span>` : ''}
    ${items ? `<span class="tsfn" aria-live="polite">${esc(trn('{0} hit', '{0} hits', items.length))}${r.more ? '+' : ''}</span>` : ''}<button type="button" class="linkbtn" data-dtab="clear">${tr('Reset filters')}</button></div>`;
  if (!items) return bar + `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (!items.length) return bar + `<div class="empty abempty">${ic('tag')}<span>${tr('No files with these tags')}</span></div>`;
  // 2.521.0 (#4398): a filter never changes the chosen view: a folder / space shown as cards stays cards while tags filter it
  if (typeof abd_cardsOn === 'function' && typeof abd_cardsHtml2 === 'function' && abd_cardsOn(ab_key(S.route))) return bar + abd_cardsHtml2({items});
  return bar + `<div class="ablist" role="list">${items.map(n => ab_rowHtml(n, false)).join('')}</div>`;
}
const dt_abItem = id => (DT_AB.res?.items || []).find(x => x.id === +id) || null;
function dt_abDetails(n) {
  const w = ab_canWrite(n.role) && !n.in_trash;
  return `<h4>${tr('Tags')}</h4><div class="abdtags">${(n.tags || []).map(t => `<span class="abtag">${esc(t.name)}</span>`).join('') || `<span class="muted">${tr('No tags yet')}</span>`}
    ${w ? `<button type="button" class="btn sm" data-abd="tags">${ic('tag', 's')} ${tr('Edit tags…')}</button>` : ''}</div>`;
}
// 2.564.0 (#4701): seen = the tags shown before (_prev): only what was added / removed here applies, a tag set elsewhere stays
async function dt_abPut(id, names, seen) { const r = await api('PUT', `/api/files/nodes/${id}/tags`, {tags: names, ...(seen ? {_prev: {tags: seen}} : {})}); DT_AB.res = null; ab_reload(); return r; }
async function dt_abEdit(n, after) {
  let t; try { t = await api('GET', `/api/files/nodes/${n.id}/tags`); } catch { return; }
  const was = (t.tags || []).map(x => x.name);
  const names = await dt_pick({title: tr('Tags of “{0}”', n.name), all: t.all || [], cur: was, ok: tr('Save')});
  if (!names || (names.length === was.length && names.every((x, i) => x === was[i]))) return;
  try { await dt_abPut(n.id, names, was); } catch { return; }
  if (after) after();
  const step = (v, p) => async () => { try { await dt_abPut(n.id, v, p); } catch { /* shown */ } return {}; };
  offerUndo(tr('Tags of {0} changed', n.name), histAdd({label: tr('Tags of {0} changed', n.name), undo: step(was, names), redo: step(names, was)}));
}
async function dt_abFilter(sp) {
  let list; try { list = (await api('GET', `/api/files/tags?space=${encodeURIComponent(sp)}`)).tags || []; } catch { return; }
  if (DT_AB.sp !== sp) Object.assign(DT_AB, {sp, st: {}, ids: {}, mode: 'any', res: null});
  for (const x of list) DT_AB.ids[x.name] = x.ids;
  if (!list.length && !Object.keys(DT_AB.st).length) { toast(tr('No tags in this space yet. Add them in the details of a file or folder.')); return; }
  const md = modal(`<div class="lhdr"><h3>${tr('Filter by tags')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="tsflt"><div class="tsgrp" role="group" aria-label="${esc(tr('Tags'))}"></div>
    <div class="tsrow"><div class="seg" role="radiogroup" aria-label="${esc(tr('Several tags'))}"></div></div></div>
    <div class="foot"><button type="button" class="btn" data-dtf="clear">${tr('Reset filters')}</button><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('tsdlg');
  const draw = () => {
    md.querySelector('.tsgrp').innerHTML = dt_pills(list, DT_AB.st, 'dtf');
    md.querySelector('.seg').innerHTML = ['any', 'all'].map(m => `<button type="button" role="radio" data-dtfm="${m}" aria-checked="${DT_AB.mode === m}">${m === 'all' ? tr('every one') : tr('one of them')}</button>`).join('');
  };
  const apply = () => { draw(); DT_AB.res = null; AB.selOn = false; AB.sel.clear(); ab_draw(); };
  draw();
  md.addEventListener('click', e => {
    if (dt_el(e).closest('[data-m="close"]')) { modalClose(md); return; }
    const p = dt_el(e).closest('[data-dtf]');
    if (p) { if (p.dataset.dtf === 'clear') DT_AB.st = {}; else dt_cycle(DT_AB.st, p.dataset.dtf); apply(); return; }
    const m = dt_el(e).closest('[data-dtfm]');
    if (m) { DT_AB.mode = m.dataset.dtfm; apply(); }
  });
}
document.addEventListener('click', e => {
  const b = dt_el(e).closest?.('[data-dtab], [data-dtabx]'); if (!b || !b.closest('.abview')) return;
  if (b.dataset.dtabx) { delete DT_AB.st[b.dataset.dtabx]; DT_AB.res = null; ab_draw(); return; }
  if (b.dataset.dtab === 'filter') dt_abFilter(b.dataset.sp);
  else if (b.dataset.dtab === 'clear') { DT_AB.st = {}; DT_AB.res = null; ab_draw(); }
});
// the file store: Shift / Ctrl / Cmd on the checkboxes of the rows (AB.sel), Shift-click on a row turns choosing on
document.addEventListener('click', e => {
  if (typeof AB === 'undefined' || !dt_el(e).closest?.('.ablist') || dt_abOn(AB.data?.space || ab_curSpace())) return;
  const row = dt_el(e).closest('.abrow'), box = dt_el(e).closest('[data-absel="one"]');
  if (!row || dt_el(e).closest('[data-ab="menu"], [data-ab="restore"]')) return;
  const id = +row.dataset.abid, key = 'ab:' + AB.dkey;
  if (box) {
    if (!(e.shiftKey || e.ctrlKey || e.metaKey)) { dt_rsAnchor(key, id); return; }  // a plain click: the box itself, the anchor here
  } else {
    if (!((e.shiftKey && dt_rsMouse(e)) || (AB.selOn && (e.ctrlKey || e.metaKey)))) return;
    if (!AB.selOn) { if (!document.querySelector('[data-absel="mode"]')) return; AB.selOn = true; AB.sel.clear(); dt_rsReset(); }
  }
  e.preventDefault(); e.stopPropagation();
  const ids = [...document.querySelectorAll('.ablist .abrow')].map(r => +r.dataset.abid);
  dt_rsClick(e, key, id, ids, x => AB.sel.has(x), (x, on) => { if (on) AB.sel.add(x); else AB.sel.delete(x); });
  ab_draw();
  // a box the page kept has its own state (it wins over the attribute), and the cancelled click puts the clicked box back
  // after this handler: set them once the click is over
  setTimeout(() => { for (const b of /** @type {NodeListOf<HTMLInputElement>} */ (document.querySelectorAll('.ablist [data-absel="one"]'))) b.checked = AB.sel.has(+b.dataset.id); }, 0);
}, true);

// ---- 2.742.0 (#4862): the tag field, ONE part for documents (docview.js), the file store and the editing of several
// (dt_pick): the given tags as pills with an x, a text field behind them; from the first letter a list of its own (no
// <datalist>, it looks different in every browser) with the known tags (the start first, then within; the hit in bold),
// the arrow keys + Enter / Tab take one, a comma or Enter makes a new one ("New: …" as the last line), Backspace in the
// empty field takes the last pill away. single: one value (2.761.0 #4868, sender / document type, see tf1_* below). Accessible as a combobox with
// a listbox and aria-activedescendant. The list lives in <body> (a redraw of the view, which morphs the field, keeps it
// open; a dialog does not clip it). A change sets the hidden field (attrs, e.g. data-dcp="tags", its value the names
// joined by ", ") and sends it a change event: the caller saves as before. Names come in as text only (esc / textContent).
const TFLD = {all: new Map(), lb: null, inp: null, act: -1, rows: [], own: false};
const tf_norm = s => String(s ?? '').replace(/\s+/g, ' ').trim().slice(0, 120);
const tf_pillHtml = (v, ro) => `<span class="tsp tsp-in tfp" data-tfv="${esc(v)}"><span class="tft">${esc(v)}</span>${ro ? '' : `<button type="button" class="tfx" data-tfx tabindex="-1" aria-label="${esc(tr('Remove {0}', v))}">${ic('x', 's')}</button>`}</span>`;
// id: the text field's id (a <label for> names it); all: the known names; vals: the given ones; attrs: on the hidden field
function tf_html({id, vals, all, ro = false, single = false, attrs = '', ph = '', label = '', noNew = false}) {
  TFLD.all.set(id, (all || []).map(x => tf_norm(x?.name ?? x)).filter(Boolean));
  const vs = (vals || []).map(tf_norm).filter(Boolean);
  if (single) return tf1_html(id, vs[0] || '', {ro, attrs, ph, label, noNew});
  return `<div class="tfld${single ? ' tf1' : ''}${ro ? ' tfro' : ''}" data-tf="${esc(id)}"${single ? ' data-tf1' : ''}${noNew ? ' data-tfnonew' : ''}><span class="tfps">${vs.map(v => tf_pillHtml(v, ro)).join('')}</span>${ro ? '' : `<input id="${esc(id)}" class="tfin" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${esc(id)}-lb" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="enter" maxlength="120"${label ? ` aria-label="${esc(label)}"` : ''}${ph && !vs.length ? ` placeholder="${esc(ph)}"` : ''}>`}<input type="hidden" class="tfval" ${attrs} value="${esc(vs.join(', '))}"></div>`;
}
// 2.761.0 (#4868): one value (sender / document type, also in the flows): no pill, the value stands in the text field itself
// (one can correct a letter), the same list from the first letter; taking a row or Enter sets the field and sends it ONE
// change event (attrs sit on the text field, e.g. data-dcp="sender": the caller saves as with a plain field). Free text
// stays a new value (noNew: not), a known name is taken in its own spelling. A comma is part of a name here.
function tf1_html(id, v, {ro, attrs, ph, label, noNew}) {
  return `<div class="tfld tf1${ro ? ' tfro' : ''}" data-tf="${esc(id)}" data-tf1${noNew ? ' data-tfnonew' : ''}><input id="${esc(id)}" class="tfin" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${esc(id)}-lb" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="done" maxlength="120" value="${esc(v)}"${label ? ` aria-label="${esc(label)}"` : ''}${ph ? ` placeholder="${esc(ph)}"` : ''} ${attrs}${ro ? ' disabled' : ''}></div>`;
}
const tf1_is = inp => !!inp.closest('.tfld')?.hasAttribute('data-tf1');
// the value as it is saved: a known name in its own spelling; a new one only without noNew (else the last saved one)
function tf1_norm(inp, v) {
  const root = inp.closest('.tfld'), n = tf_norm(v); if (!root || !n) return n;
  const known = (TFLD.all.get(root.dataset.tf) || []).find(x => x.toLowerCase() === n.toLowerCase());
  return known || (root.hasAttribute('data-tfnonew') ? (inp.getAttribute('value') || '') : n);
}
// sets the value and tells the caller once; the browser's own change when leaving the field afterwards is the same one
function tf1_commit(inp, v) {
  inp.value = tf1_norm(inp, v); /** @type {any} */ (inp)._tf1sent = inp.value;  // a property: a redraw (morph) keeps it, an attribute it would drop
  TFLD.own = true;
  try { inp.dispatchEvent(new Event('change', {bubbles: true})); } finally { TFLD.own = false; }
}
const tf_vals = root => [...root.querySelectorAll('.tfp')].map(p => /** @type {HTMLElement} */ (p).dataset.tfv || '');
// sets the pills (the field's own drawing, the caller's redraw draws the same) and tells the hidden field
function tf_set(root, vals, tell = true) {
  const ro = root.classList.contains('tfro'), seen = new Set(), out = [];
  for (const v of vals.map(tf_norm)) { const k = v.toLowerCase(); if (v && !seen.has(k)) { seen.add(k); out.push(v); } }
  const ps = root.querySelector('.tfps'); if (ps) ps.innerHTML = out.map(v => tf_pillHtml(v, ro)).join('');
  const inp = root.querySelector('.tfin'); if (inp && out.length) inp.removeAttribute('placeholder');
  const h = root.querySelector('.tfval'); if (!h) return out;
  const nv = out.join(', ');
  if (h.value !== nv) { h.value = nv; if (tell) h.dispatchEvent(new Event('change', {bubbles: true})); }
  return out;
}
// names taken (one or several at once = one change): a known one in its own spelling (one value: tf1_commit)
function tf_add(root, names) {
  const all = TFLD.all.get(root.dataset.tf) || [], cur = tf_vals(root);
  const out = [...cur];
  for (const name of Array.isArray(names) ? names : [names]) {
    const v = tf_norm(name); if (!v) continue;
    const known = all.find(x => x.toLowerCase() === v.toLowerCase());
    if (!known && root.hasAttribute('data-tfnonew')) continue;
    if (!out.some(x => x.toLowerCase() === v.toLowerCase())) out.push(known || v);
  }
  if (out.length !== cur.length || out.some((x, i) => x !== cur[i])) tf_set(root, out);
}
// the hits of q: the known names not given yet, the ones starting with q first, then the ones containing it
function tf_hits(root, q) {
  const all = TFLD.all.get(root.dataset.tf) || [], cur = new Set(root.hasAttribute('data-tf1') ? [] : tf_vals(root).map(x => x.toLowerCase())), k = q.toLowerCase();
  const free = all.filter(x => !cur.has(x.toLowerCase()));
  if (!k) return free.slice(0, 50);
  return [...free.filter(x => x.toLowerCase().startsWith(k)), ...free.filter(x => !x.toLowerCase().startsWith(k) && x.toLowerCase().includes(k))].slice(0, 50);
}
const tf_mark = (s, q) => { const i = q ? s.toLowerCase().indexOf(q.toLowerCase()) : -1; return i < 0 ? esc(s) : `${esc(s.slice(0, i))}<b>${esc(s.slice(i, i + q.length))}</b>${esc(s.slice(i + q.length))}`; };
function tf_close() {
  if (TFLD.inp) { TFLD.inp.setAttribute('aria-expanded', 'false'); TFLD.inp.removeAttribute('aria-activedescendant'); }
  TFLD.lb?.remove(); TFLD.lb = null; TFLD.inp = null; TFLD.act = -1; TFLD.rows = [];
}
// opens / draws the list under the field; all = every free name (ArrowDown in the empty field)
function tf_open(inp, all = false) {
  const root = inp.closest('.tfld'); if (!root) return;
  const q = tf_norm(inp.value);
  if (!q && !all) { tf_close(); return; }
  const hits = tf_hits(root, q), rows = hits.map(v => ({v, nw: false}));
  const given = tf_vals(root).some(x => x.toLowerCase() === q.toLowerCase());
  if (q && !root.hasAttribute('data-tfnonew') && !given && !hits.some(x => x.toLowerCase() === q.toLowerCase())) rows.push({v: q, nw: true});
  if (!rows.length) { tf_close(); return; }
  if (TFLD.inp && TFLD.inp !== inp) tf_close();
  const id = inp.id + '-lb';
  let lb = TFLD.lb;
  if (!lb) { lb = document.createElement('ul'); lb.className = 'tflb'; lb.setAttribute('role', 'listbox'); document.body.appendChild(lb); }
  lb.id = id; lb.setAttribute('aria-label', inp.getAttribute('aria-label') || /** @type {any} */ (inp).labels?.[0]?.textContent || tr('Tags'));
  const keep = TFLD.rows[TFLD.act]?.v;
  TFLD.lb = lb; TFLD.inp = inp; TFLD.rows = rows;
  // the best hit is marked at once (Enter takes it); a name typed exactly: that one
  let act = keep != null ? rows.findIndex(r => r.v === keep) : -1;
  if (act < 0) act = q || all ? 0 : -1;
  TFLD.act = act;
  lb.innerHTML = rows.map((r, i) => `<li role="option" id="${esc(id)}-${i}" data-tfo="${i}" aria-selected="${i === act}" class="${r.nw ? 'tfnew' : ''}">${r.nw ? esc(tr('New: {0}', '\u0001')).replace('\u0001', `<b>${esc(r.v)}</b>`) : tf_mark(r.v, q)}</li>`).join('');
  inp.setAttribute('aria-expanded', 'true');
  tf_actSet(act);
  tf_place();
}
function tf_actSet(i) {
  const lb = TFLD.lb, inp = TFLD.inp; if (!lb || !inp) return;
  TFLD.act = i;
  for (const o of lb.children) o.setAttribute('aria-selected', String(+(/** @type {HTMLElement} */ (o).dataset.tfo) === i));
  const o = i >= 0 ? lb.children[i] : null;
  if (o) { inp.setAttribute('aria-activedescendant', o.id); o.scrollIntoView?.({block: 'nearest'}); } else inp.removeAttribute('aria-activedescendant');
}
// under the field (above it when there is no room below, e.g. the phone's keyboard)
function tf_place() {
  const lb = TFLD.lb, root = TFLD.inp?.closest('.tfld');
  if (!lb || !root || !root.isConnected) { tf_close(); return; }
  const r = root.getBoundingClientRect(), vh = window.visualViewport?.height || window.innerHeight, below = vh - r.bottom, up = below < 160 && r.top > below;
  lb.style.left = `${Math.max(4, r.left)}px`; lb.style.width = `${Math.max(r.width, 160)}px`;
  lb.style.top = up ? '' : `${r.bottom + 2}px`; lb.style.bottom = up ? `${window.innerHeight - r.top + 2}px` : '';
  lb.style.maxHeight = `${Math.max(120, Math.min(320, (up ? r.top : below) - 12))}px`;
}
// takes the marked row (or the typed text); false: nothing to take
function tf_take(inp, typed = false) {
  const root = inp.closest('.tfld'); if (!root) return false;
  const r = !typed && TFLD.inp === inp ? TFLD.rows[TFLD.act] : null, v = r ? r.v : tf_norm(inp.value);
  if (!v) return false;
  if (root.hasAttribute('data-tf1')) { tf_close(); if (!(typed && tf1_norm(inp, v) === inp.getAttribute('value'))) tf1_commit(inp, v); return true; }  // 2.761.0 (#4868): Enter on the saved value saves nothing
  inp.value = '';
  tf_add(root, v); tf_close();
  return true;
}
document.addEventListener('input', e => {
  const inp = dt_el(e).closest?.('.tfin'); if (!inp) return;
  const el = /** @type {HTMLInputElement} */ (inp);
  if (el.value.includes(',') && !tf1_is(el)) {  // a comma: what stands before it becomes a tag (also pasted "a, b, c")
    const parts = el.value.split(','), rest = parts.pop() || '', root = el.closest('.tfld');
    el.value = rest.trimStart();
    if (root) tf_add(root, parts);
  }
  tf_open(el);
});
// before the view's / dialog's own keys (Esc closes the list, not the view; Enter takes, it does not send the dialog)
document.addEventListener('keydown', e => {
  const inp = /** @type {HTMLInputElement} */ (dt_el(e).closest?.('.tfin')); if (!inp || e.isComposing) return;
  const open = TFLD.inp === inp && !!TFLD.lb, n = TFLD.rows.length, stop = () => { e.preventDefault(); e.stopPropagation(); };
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    stop();
    if (!open) { tf_open(inp, true); if (e.key === 'ArrowUp' && TFLD.rows.length) tf_actSet(TFLD.rows.length - 1); return; }
    tf_actSet(e.key === 'ArrowDown' ? (TFLD.act + 1) % n : (TFLD.act <= 0 ? n - 1 : TFLD.act - 1));
  } else if (e.key === 'Enter') {
    if (open && TFLD.act >= 0) { stop(); tf_take(inp); } else if (tf_norm(inp.value)) { stop(); tf_take(inp, true); }
  } else if (e.key === 'Tab' && !e.shiftKey) {
    if (open && TFLD.act >= 0) { stop(); tf_take(inp); }
  } else if (e.key === 'Escape') {
    if (open) { stop(); tf_close(); }
  } else if (e.key === 'Backspace' && !inp.value && inp.selectionStart === 0 && !tf1_is(inp)) {
    const root = inp.closest('.tfld'), cur = root ? tf_vals(root) : [];
    if (root && cur.length) { stop(); tf_set(root, cur.slice(0, -1)); }
  }
}, true);
// leaving the field: typed text becomes a tag (the field's change event), the list closes
document.addEventListener('change', e => {
  const inp = /** @type {HTMLInputElement} */ (dt_el(e).closest?.('.tfin')); if (!inp) return;
  if (tf1_is(inp)) {  // 2.761.0 (#4868): one value - the change goes on to the caller, once per value
    if (TFLD.own) return;
    const v = tf1_norm(inp, inp.value), sent = /** @type {any} */ (inp)._tf1sent; inp.value = v; /** @type {any} */ (inp)._tf1sent = null;
    if (sent === v) e.stopPropagation();
    return;
  }
  e.stopPropagation();
  const root = inp.closest('.tfld'), v = inp.value; if (!root || !tf_norm(v)) return;
  inp.value = '';
  tf_add(root, v.split(','));
}, true);
document.addEventListener('focusin', e => { const inp = dt_el(e).closest?.('.tf1 .tfin'); if (inp) /** @type {any} */ (inp)._tf1sent = null; });  // 2.761.0 (#4868)
document.addEventListener('focusout', e => { if (TFLD.inp && dt_el(e) === TFLD.inp) setTimeout(() => { if (TFLD.inp && document.activeElement !== TFLD.inp) tf_close(); }, 0); });
// a row of the list: the press keeps the focus in the field, the click takes the row
document.addEventListener('mousedown', e => { if (dt_el(e).closest?.('.tflb') || dt_el(e).closest?.('.tfx')) e.preventDefault(); });
document.addEventListener('click', e => {
  const o = dt_el(e).closest?.('.tflb [data-tfo]');
  if (o && TFLD.inp) { const inp = TFLD.inp; tf_actSet(+(/** @type {HTMLElement} */ (o).dataset.tfo)); tf_take(inp); inp.focus(); return; }
  const x = dt_el(e).closest?.('.tfx');
  if (x) {
    const root = x.closest('.tfld'), v = /** @type {HTMLElement} */ (x.closest('.tfp'))?.dataset.tfv; if (!root || v == null) return;
    e.preventDefault(); e.stopPropagation();
    tf_set(root, tf_vals(root).filter(y => y !== v));
    /** @type {HTMLElement} */ (root.querySelector('.tfin'))?.focus();
    return;
  }
  const root = dt_el(e).closest?.('.tfld');
  if (root && !dt_el(e).closest('.tfin')) /** @type {HTMLElement} */ (root.querySelector('.tfin'))?.focus();
});
window.addEventListener('scroll', () => { if (TFLD.lb) tf_place(); }, true);
window.addEventListener('resize', () => { if (TFLD.lb) tf_place(); });
window.addEventListener('hashchange', tf_close);
