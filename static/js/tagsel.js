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

// ---- the tag picker: resolves with the chosen names, or null (cancelled). all: [{name}], cur: [names] chosen at the start
async function dt_pick({title, all, cur, ok}) {
  const names = [], seen = new Set();
  for (const n of [...(all || []).map(x => x.name || x), ...(cur || [])]) { const k = String(n || '').toLowerCase(); if (k && !seen.has(k)) { seen.add(k); names.push(String(n)); } }
  const on = new Set((cur || []).map(x => String(x).toLowerCase()));
  const pill = n => `<button type="button" class="tsp ${on.has(n.toLowerCase()) ? 'tsp-in' : ''}" data-tsp="${esc(n)}" aria-pressed="${on.has(n.toLowerCase())}">${on.has(n.toLowerCase()) ? ic('check', 's') + ' ' : ''}${esc(n)}</button>`;
  const draw = md => { const b = $('.tspick', md); if (b) b.innerHTML = names.map(pill).join('') || `<span class="muted">${tr('No tags yet')}</span>`; };
  const add = md => {
    const inp = $('#ts-new', md), v = (inp?.value || '').replace(/\s+/g, ' ').trim().slice(0, 120); if (!v) return;
    if (!names.some(x => x.toLowerCase() === v.toLowerCase())) names.push(v);
    on.add(v.toLowerCase()); inp.value = ''; draw(md); inp.focus();
  };
  const r = await askDialog({title, ok: ok || tr('Save'), cancel: tr('Cancel'),
    html: `<div class="tspick" role="group" aria-label="${esc(tr('Tags'))}"></div><div class="tsnew"><input id="ts-new" maxlength="120" placeholder="${esc(tr('New tag'))}" aria-label="${esc(tr('New tag'))}" autocomplete="off"><button type="button" class="btn sm" data-tsadd="1">${ic('plus', 's')} ${tr('Add')}</button></div>`,
    after: md => {
      md.classList.add('tsdlg'); draw(md);
      md.addEventListener('click', e => {
        const p = e.target.closest('[data-tsp]');
        if (p) { const k = p.dataset.tsp.toLowerCase(); if (on.has(k)) on.delete(k); else on.add(k); draw(md); $$('[data-tsp]', md).find(x => x.dataset.tsp.toLowerCase() === k)?.focus(); return; }
        if (e.target.closest('[data-tsadd]')) add(md);
      });
      md.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'ts-new' && e.target.value.trim()) { e.preventDefault(); add(md); } });
    }});
  if (r === false || r == null) return null;
  return names.filter(n => on.has(n.toLowerCase()));
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
  return bar + `<div class="ablist" role="list">${items.map(n => ab_rowHtml(n, false)).join('')}</div>`;
}
const dt_abItem = id => (DT_AB.res?.items || []).find(x => x.id === +id) || null;
function dt_abDetails(n) {
  const w = ab_canWrite(n.role) && !n.in_trash;
  return `<h4>${tr('Tags')}</h4><div class="abdtags">${(n.tags || []).map(t => `<span class="abtag">${esc(t.name)}</span>`).join('') || `<span class="muted">${tr('No tags yet')}</span>`}
    ${w ? `<button type="button" class="btn sm" data-abd="tags">${ic('tag', 's')} ${tr('Edit tags…')}</button>` : ''}</div>`;
}
async function dt_abPut(id, names) { const r = await api('PUT', `/api/files/nodes/${id}/tags`, {tags: names}); DT_AB.res = null; ab_reload(); return r; }
async function dt_abEdit(n, after) {
  let t; try { t = await api('GET', `/api/files/nodes/${n.id}/tags`); } catch { return; }
  const was = (t.tags || []).map(x => x.name);
  const names = await dt_pick({title: tr('Tags of “{0}”', n.name), all: t.all || [], cur: was, ok: tr('Save')});
  if (!names || (names.length === was.length && names.every((x, i) => x === was[i]))) return;
  try { await dt_abPut(n.id, names); } catch { return; }
  if (after) after();
  const step = v => async () => { try { await dt_abPut(n.id, v); } catch { /* shown */ } return {}; };
  offerUndo(tr('Tags of {0} changed', n.name), histAdd({label: tr('Tags of {0} changed', n.name), undo: step(was), redo: step(names)}));
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
