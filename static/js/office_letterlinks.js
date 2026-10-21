// @ts-check
// 2.153.0 (#2028): at a letter: the linked documents (answers / reply), the history of the matter, the follow-up.
// Server: kalmido/office/letterlinks.py. Pushes into LT_HOOKS (office_letters.js).
'use strict';
const LTK = {id: null, d: null, x: null, seq: 0, pick: '', q: '', res: [], thread: null, open: false};
function ltkSection(d) {
  if (!d || !d.id) return '';
  if (LTK.id !== d.id) Object.assign(LTK, {id: d.id, x: null, pick: '', q: '', res: [], thread: null, open: false});
  LTK.d = d;
  if (!LTK.x) ltkLoad();
  return `<section class="ltk" data-lid="${d.id}" aria-label="${esc(tr('Reference'))}">${ltkHtml()}</section>`;
}
async function ltkLoad() {
  const id = LTK.id, seq = ++LTK.seq;
  let x = null; try { x = await api('GET', `/api/office/letters/${id}/links`); } catch { x = null; }
  if (seq !== LTK.seq || LTK.id !== id) return;
  LTK.x = x; ltkDraw();
  if (LTK.open) ltkThread();
}
function ltkDraw() { const el = $(`.ltk[data-lid="${LTK.id}"]`); if (el) el.innerHTML = ltkHtml(); }
const ltkDay = v => v ? dayLabel(v, true) : '';
const LTK_KIND = {answers: 'Answer to', reply: 'Answer'};
function ltkHtml() {
  const x = LTK.x, d = LTK.d; if (!x || !d) return '';
  const sent = d.status !== 'draft';
  const links = x.links.length ? `<ul class="ltk-list">${x.links.map(l => `<li><span class="ltk-k">${esc(tr(LTK_KIND[l.kind] || l.kind))}</span>
      <a href="${esc(l.href)}">${esc(l.title)}</a><span class="muted">${esc([l.sender, ltkDay(l.date)].filter(Boolean).join(' · '))}</span>
      <button type="button" class="iconbtn ltk-x" data-ltk="unlink:${l.node_id}:${l.kind}" aria-label="${esc(tr('Unlink'))}" title="${esc(tr('Unlink'))}">${ic('x', 's')}</button></li>`).join('')}</ul>`
    : `<p class="muted ltk-none">${tr('No document linked yet.')}</p>`;
  const refBtn = !sent && x.ref_line && x.ref_line !== (d.ref_line || '') ? `<button type="button" class="btn sm" data-ltk="refline">${tr('Reference line from the reference')}</button>` : '';
  const acts = `<div class="ltk-acts"><button type="button" class="btn sm" data-ltk="pick:answers">${ic('link', 's')} ${tr('Choose a reference')}</button>
    ${sent ? `<button type="button" class="btn sm" data-ltk="pick:reply">${ic('inbox', 's')} ${tr('Assign an answer')}</button>` : ''}${refBtn}</div>`;
  const picker = LTK.pick ? `<div class="ltk-pick" role="search"><input type="search" class="ltk-q" value="${esc(LTK.q)}" placeholder="${esc(tr('Search documents'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off">
      <ul class="ltk-res">${LTK.res.map(r => `<li><button type="button" class="ltk-hit" data-ltk="link:${r.id}">${esc(r.name)}<span class="muted">${esc([r.sender?.name, ltkDay(r.date)].filter(Boolean).join(' · '))}</span></button></li>`).join('')
      || (LTK.q ? `<li class="muted">${tr('Nothing found')}</li>` : '')}</ul>
      <button type="button" class="btn sm" data-ltk="pickclose">${tr('Cancel')}</button></div>` : '';
  const f = x.followup || {};
  const fu = f.answered ? `<p class="ltk-fu">${ic('done', 's')} ${tr('Answer received')}</p>`
    : f.task_id ? `<p class="ltk-fu">${ic('alarm', 's')} <a href="#t/${f.task_id}">${tr('Follow-up task created')}</a></p>`
    : f.due ? `<p class="ltk-fu muted">${ic('alarm', 's')} ${esc(tr('Follow-up due on {0}', ltkDay(f.due)))}</p>` : '';
  const th = LTK.thread;
  const thread = `<details class="ltk-th" ${LTK.open ? 'open' : ''}><summary>${tr('History')}</summary>${!th ? '' : th.length ? `<ol class="ltk-tl">${th.map(i => `<li class="ltk-${i.dir}">
      ${ic(i.dir === 'out' ? 'send' : 'inbox', 's')}<span class="muted">${esc(ltkDay(i.date))}</span>
      ${i.type === 'letter' && i.id === LTK.id ? `<b>${esc(i.title || tr('Letter'))}</b>` : `<a href="${esc(i.href)}">${esc(i.title || tr('Letter'))}</a>`}</li>`).join('')}</ol>` : `<p class="muted">${tr('Nothing found')}</p>`}</details>`;
  return `<h4 class="ltk-h">${tr('Reference')}</h4>${links}${acts}${picker}${fu}${thread}`;
}
async function ltkThread() {
  const id = LTK.id;
  let x = null; try { x = await api('GET', `/api/office/letters/${id}/thread`); } catch { return; }
  if (LTK.id !== id) return;
  LTK.thread = x.items; ltkDraw();
}
let ltkT = 0;
function ltkSearch(q) {
  LTK.q = q; clearTimeout(ltkT);
  ltkT = setTimeout(async () => {
    const id = LTK.id, ws = LTK.x?.docs_ws || 'all';
    let r = null; try { r = q.trim() ? await api('GET', `/api/docs?ws=${encodeURIComponent(ws)}&q=${encodeURIComponent(q.trim())}&limit=20&facets=0`) : {docs: []}; } catch { return; }
    if (LTK.id !== id || LTK.q !== q) return;
    LTK.res = r.docs || [];
    const el = $(`.ltk[data-lid="${id}"] .ltk-res`); if (el) { ltkDraw(); const i = $(`.ltk[data-lid="${id}"] .ltk-q`); if (i) { i.focus(); i.setSelectionRange(q.length, q.length); } }
  }, 250);
}
function ltkSet(x) { if (x) { LTK.x = {...LTK.x, ...x}; ltkDraw(); } if (LTK.open) ltkThread(); }
async function ltkLink(nid, kind) {
  const lid = LTK.id;
  const x = await api('POST', `/api/office/letters/${lid}/links`, {node_id: nid, kind}).catch(() => null); if (!x) return;
  LTK.pick = ''; LTK.q = ''; LTK.res = [];
  ltkSet(x);
  if (x.ref_line && LTK.d && x.ref_line !== (LTK.d.ref_line || '')) { LTK.d.ref_line = x.ref_line; ltkReloadLetter(); }
  const msg = tr('Document linked');
  histToast(msg, histAdd({label: msg,
    undo: async () => { const y = await api('DELETE', `/api/office/letters/${lid}/links/${nid}?kind=${kind}`); if (LTK.id === lid) ltkSet(y); return {}; },
    redo: async () => { const y = await api('POST', `/api/office/letters/${lid}/links`, {node_id: nid, kind}); if (LTK.id === lid) ltkSet(y); return {}; }}));
}
async function ltkUnlink(nid, kind) {
  const lid = LTK.id;
  const x = await api('DELETE', `/api/office/letters/${lid}/links/${nid}?kind=${kind}`).catch(() => null); if (!x) return;
  ltkSet(x);
  const msg = tr('Document unlinked');
  histToast(msg, histAdd({label: msg,
    undo: async () => { const y = await api('POST', `/api/office/letters/${lid}/links`, {node_id: nid, kind}); if (LTK.id === lid) ltkSet(y); return {}; },
    redo: async () => { const y = await api('DELETE', `/api/office/letters/${lid}/links/${nid}?kind=${kind}`); if (LTK.id === lid) ltkSet(y); return {}; }}));
}
function ltkReloadLetter() { if (typeof ltReload === 'function') ltReload(); }
function ltkRefField() { return $('[name="ref_line"]') || $('[data-ltf="ref_line"]') || $('#lt-ref_line'); }
async function ltkRefLine() {
  const lid = LTK.id, line = LTK.x?.ref_line; if (!line) return;
  const inp = ltkRefField();
  if (inp) {  // the editor is open: fill the field, the editor saves it like a typed change
    const old = inp.value;
    inp.value = line; inp.dispatchEvent(new Event('input', {bubbles: true})); inp.dispatchEvent(new Event('change', {bubbles: true}));
    if (LTK.d) LTK.d.ref_line = line;
    ltkDraw();
    histToast(tr('Reference line filled in'), histAdd({label: tr('Reference line filled in'),
      undo: async () => { const i = ltkRefField(); if (i) { i.value = old; i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new Event('change', {bubbles: true})); } else await api('PATCH', `/api/office/letters/${lid}`, {ref_line: old}); return {}; },
      redo: async () => { const i = ltkRefField(); if (i) { i.value = line; i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new Event('change', {bubbles: true})); } else await api('PATCH', `/api/office/letters/${lid}`, {ref_line: line}); return {}; }}));
    return;
  }
  const old = LTK.d?.ref_line || '';
  const d = await api('PATCH', `/api/office/letters/${lid}`, {ref_line: line}).catch(() => null); if (!d) return;
  LTK.d = {...LTK.d, ...d}; ltkDraw(); ltkReloadLetter();
  histToast(tr('Reference line filled in'), histAdd({label: tr('Reference line filled in'),
    undo: async () => { await api('PATCH', `/api/office/letters/${lid}`, {ref_line: old}); ltkReloadLetter(); return {}; },
    redo: async () => { await api('PATCH', `/api/office/letters/${lid}`, {ref_line: line}); ltkReloadLetter(); return {}; }}));
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest('.ltk [data-ltk]'); if (!b) return;
  const [a, p1, p2] = b.dataset.ltk.split(':');
  if (a === 'pick') { LTK.pick = p1; LTK.q = ''; LTK.res = []; ltkDraw(); $(`.ltk[data-lid="${LTK.id}"] .ltk-q`)?.focus(); return; }
  if (a === 'pickclose') { LTK.pick = ''; ltkDraw(); return; }
  if (a === 'link') { ltkLink(+p1, LTK.pick || 'answers'); return; }
  if (a === 'unlink') { ltkUnlink(+p1, p2); return; }
  if (a === 'refline') ltkRefLine();
});
document.addEventListener('input', e => { if (/** @type {any} */ (e.target).matches?.('.ltk .ltk-q')) ltkSearch(/** @type {any} */ (e.target).value); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && /** @type {any} */ (e.target).matches?.('.ltk .ltk-q')) { LTK.pick = ''; ltkDraw(); } });
document.addEventListener('toggle', e => {
  if (!/** @type {any} */ (e.target).matches?.('.ltk .ltk-th')) return;
  LTK.open = /** @type {any} */ (e.target).open;
  if (LTK.open && !LTK.thread) ltkThread();
}, true);
LT_HOOKS.sections.push(ltkSection);
