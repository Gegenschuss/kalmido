// @ts-check
// 2.153.0 (#2028): at a letter: the linked documents (answers / reply), the history of the matter, the follow-up.
// Server: kalmido/office/letterlinks.py. Pushes into LT_HOOKS (office_letters.js).
'use strict';
// 2.1094.0 (#5902): err / resErr / thErr = why the references, the search or the history did not load (shown with "Try again")
const LTK = {id: null, d: null, x: null, seq: 0, pick: '', q: '', res: [], thread: null, open: false, err: '', resErr: '', thErr: ''};
function ltkSection(d) {
  if (!d || !d.id) return '';
  if (LTK.id !== d.id) Object.assign(LTK, {id: d.id, x: null, pick: '', q: '', res: [], thread: null, open: false, err: '', resErr: '', thErr: ''});
  LTK.d = d;
  if (!LTK.x && !LTK.err) ltkLoad();
  return `<section class="ltk" data-lid="${d.id}" aria-label="${esc(tr('Reference'))}">${ltkHtml()}</section>`;
}
async function ltkLoad() {
  const id = LTK.id, seq = ++LTK.seq;
  let x = null, err = ''; try { x = await api('GET', `/api/office/letters/${id}/links`); } catch (e) { x = null; err = ofcErrHere(e); }
  if (seq !== LTK.seq || LTK.id !== id) return;
  LTK.x = x; LTK.err = err; ltkDraw();
  if (LTK.open) ltkThread();
}
function ltkDraw() { const el = $(`.ltk[data-lid="${LTK.id}"]`); if (el) el.innerHTML = ltkHtml(); }
// 2.979.0 (#5667): an undo / redo the server did: the references of the open letter come again (a link taken back shows again)
histReloader('letterlinks', () => { if (!LTK.id || !LTK.x) return; if ($(`.ltk[data-lid="${LTK.id}"]`)) return ltkLoad(); LTK.x = null; });
const ltkDay = v => v ? dayLabel(v, true) : '';
const LTK_KIND = {answers: N_('Answer to'), reply: N_('Answer')}  // 2.446.0 (#3763): marked for the language files;
function ltkHtml() {
  const x = LTK.x, d = LTK.d; if (!d) return '';
  // 2.1094.0 (#5902): while loading the one loading block, a failure the reason + "Try again" (it was an empty section)
  if (!x) return `<h4 class="ltk-h">${tr('Reference')}</h4>${/*html-ok*/ LTK.err ? errorState({sub: LTK.err, size: 'row', retry: () => { LTK.err = ''; ltkDraw(); ltkLoad(); }}) : loadingHtml('row')}`;
  const sent = d.status !== 'draft';
  const links = x.links.length ? `<ul class="ltk-list">${x.links.map(l => `<li><span class="ltk-k">${esc(tr(LTK_KIND[l.kind] || l.kind))}</span>
      <a href="${esc(l.href)}">${esc(l.title)}</a><span class="muted">${esc([l.sender, ltkDay(l.date)].filter(Boolean).join(' · '))}</span>
      <button type="button" class="iconbtn ltk-x" data-ltk="unlink:${l.node_id}:${l.kind}" aria-label="${esc(tr('Unlink'))}" title="${esc(tr('Unlink'))}">${ic('x', 's')}</button></li>`).join('')}</ul>`
    : emptyState({title: tr('No document linked yet.'), size: 'row', cls: 'ltk-none'});  // 2.1076.0 (#5450)
  const refBtn = !sent && x.ref_line && x.ref_line !== (d.ref_line || '') ? `<button type="button" class="btn sm" data-ltk="refline">${tr('Reference line from the reference')}</button>` : '';
  const acts = `<div class="ltk-acts"><button type="button" class="btn sm" data-ltk="pick:answers">${ic('link', 's')} ${tr('Select a reference')}</button>
    ${sent ? `<button type="button" class="btn sm" data-ltk="pick:reply">${ic('inbox', 's')} ${tr('Assign an answer')}</button>` : ''}${refBtn}</div>`;
  const picker = LTK.pick ? `<div class="ltk-pick" role="search"><input type="search" class="ltk-q" value="${esc(LTK.q)}" placeholder="${esc(tr('Search documents'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off">
      <ul class="ltk-res">${LTK.res.map(r => `<li><button type="button" class="ltk-hit" data-ltk="link:${r.id}">${esc(r.name)}<span class="muted">${esc([r.sender?.name, ltkDay(r.date)].filter(Boolean).join(' · '))}</span></button></li>`).join('')
      || (LTK.resErr ? `<li>${/*html-ok*/ errorState({sub: LTK.resErr, size: 'row', retry: () => ltkSearch(LTK.q)})}</li>` : LTK.q ? `<li>${/*html-ok*/ ofcNoHit('', 'row')}</li>` : '')}</ul>
      <button type="button" class="btn sm" data-ltk="pickclose">${tr('Cancel')}</button></div>` : '';
  const f = x.followup || {};
  const fu = f.answered ? `<p class="ltk-fu">${ic('done', 's')} ${tr('Answer received')}</p>`
    : f.task_id ? `<p class="ltk-fu">${ic('alarm', 's')} <a href="#t/${f.task_id}">${tr('Follow-up task created')}</a></p>`
    : f.due ? `<p class="ltk-fu muted">${ic('alarm', 's')} ${esc(tr('Follow-up due on {0}', ltkDay(f.due)))}</p>` : '';
  const th = LTK.thread;
  const thread = `<details class="ltk-th" ${LTK.open ? 'open' : ''}><summary>${tr('History')}</summary>${/*html-ok*/ LTK.thErr ? errorState({sub: LTK.thErr, size: 'row', retry: () => { LTK.thErr = ''; ltkDraw(); ltkThread(); }}) : !th ? (LTK.open ? loadingHtml('row') : '') : th.length ? `<ol class="ltk-tl">${th.map(i => `<li class="ltk-${i.dir}">
      ${ic(i.dir === 'out' ? 'send' : 'inbox', 's')}<span class="muted">${esc(ltkDay(i.date))}</span>
      ${i.type === 'letter' && i.id === LTK.id ? `<b>${esc(i.title || tr('Letter'))}</b>` : `<a href="${esc(i.href)}">${esc(i.title || tr('Letter'))}</a>`}</li>`).join('')}</ol>` : emptyState({title: tr('Nothing found'), size: 'row', cls: 'ltk-thnone'})}</details>`;  // 2.1094.0 (#5902): the one block
  return `<h4 class="ltk-h">${tr('Reference')}</h4>${links}${acts}${picker}${fu}${thread}`;
}
async function ltkThread() {
  const id = LTK.id;
  let x = null; try { x = await api('GET', `/api/office/letters/${id}/thread`); } catch (e) { if (LTK.id === id) { LTK.thErr = ofcErrHere(e); ltkDraw(); } return; }  // 2.1094.0 (#5902)
  if (LTK.id !== id) return;
  LTK.thread = x.items; LTK.thErr = ''; ltkDraw();
}
let ltkT = 0;
function ltkSearch(q) {
  LTK.q = q; clearTimeout(ltkT);
  ltkT = setTimeout(async () => {
    const id = LTK.id, ws = LTK.x?.docs_ws || 'all';
    let r = null; try { r = q.trim() ? await api('GET', `/api/docs?ws=${encodeURIComponent(ws)}&q=${encodeURIComponent(q.trim())}&limit=20&facets=0`) : {docs: []}; }
    catch (e) { if (LTK.id === id && LTK.q === q) { LTK.res = []; LTK.resErr = ofcErrHere(e); ltkDraw(); } return; }  // 2.1094.0 (#5902): said, not silent
    if (LTK.id !== id || LTK.q !== q) return;
    LTK.res = r.docs || []; LTK.resErr = '';
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
  let tr0 = x.trash || null;  // 2.567.0 (#4707); 2.905.0 (#5414): the undo takes the links out of the core's trash
  histToast(msg, histAdd({label: msg,
    undo: async () => { if (tr0) { for (const i of tr0.ids || [tr0.id]) await api('POST', `/api/office/trash/core/${tr0.kind}/${i}/restore?undo=1`); } const y = tr0 ? await api('GET', `/api/office/letters/${lid}/links`) : await api('POST', `/api/office/letters/${lid}/links`, {node_id: nid, kind}); if (LTK.id === lid) ltkSet(y); return {}; },
    redo: async () => { const y = await api('DELETE', `/api/office/letters/${lid}/links/${nid}?kind=${kind}`); tr0 = y.trash || null; if (LTK.id === lid) ltkSet(y); return {}; }}));
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
  let ver = d.updated_at || '';
  histToast(tr('Reference line filled in'), histAdd({label: tr('Reference line filled in'),
    // 2.566.0 (#4704): each way against the version the step before left (core.js undoStep): changed elsewhere since -> said, kept
    undo: () => undoStep(`/api/office/letters/${lid}`, {ref_line: old}, ver, {label: tr('Reference line filled in'), then: x => { ver = x.updated_at || ver; }}).finally(ltkReloadLetter),
    redo: () => undoStep(`/api/office/letters/${lid}`, {ref_line: line}, ver, {label: tr('Reference line filled in'), then: x => { ver = x.updated_at || ver; }}).finally(ltkReloadLetter)}));
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest('.ltk [data-ltk]'); if (!b) return;
  const [a, p1, p2] = b.dataset.ltk.split(':');
  if (a === 'pick') { LTK.pick = p1; LTK.q = ''; LTK.res = []; LTK.resErr = ''; ltkDraw(); $(`.ltk[data-lid="${LTK.id}"] .ltk-q`)?.focus(); return; }
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
