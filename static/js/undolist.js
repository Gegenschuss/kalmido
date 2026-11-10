// @ts-check
/* Kalmido web client: the list "Recent steps" (2.773.0, #5250: undo across devices, stage 2; takes up #5242).
   Loaded on demand (lazyload.js module undolist): a right-click / long-press on the ← button opens it as a window (ul_open),
   the account menu's "Recent steps" as a page (#steps, viewSteps) - one component, the same rows, the same buttons.
   Rows, newest first:
     - changes still waiting in the outbox that no step of this browser names (on top, "not sent yet")
     - the person's step groups of the server (GET /api/undo, kalmido/core/undoweb.py; every device of the person): time,
       area, device, label; "Undo up to here" (POST /api/undo/to/<id>), "Redo" for an undone group; a barrier (finalised,
       sent, paid ...) or a group too big for copies is greyed and so is everything older (the server stops there); a group
       nothing of which may be changed any more is greyed with its reason
     - the steps of this browser in areas that are not on the server's history yet (undo.js HIST, label "only this device");
       the steps the server lists itself (office documents, the core dialogs: e.srv) are not shown twice
   "Undo up to here" takes back every row above it and the row, newest first: runs of this browser's steps go through
   undo.js histStep(only), runs of server groups through /api/undo/to; a conflict leaves that part and names it (the rest of
   the group goes back, the server decides), a barrier ends the run. Live: the person's own "self" counter of the 4-s poll
   (core.js, S.lpA.undo, #5407) reloads the server rows; the rows are patched in place and the row at the top of the view stays
   where it is (no jump, #5224). Classic script sharing the global scope with the others. */
'use strict';

const UL = {items: null, err: '', undo: undefined, busy: false, note: '', t: 0, n: 0, html: new WeakMap(), at: 0};
const UL_MAX = 100;

const ul_key = e => { if (!e.ulk) e.ulk = ++UL.n; return 'l:' + e.ulk; };
const ul_qOf = e => !!e && (e.parts ? e.parts.flatMap(ul_qOf) : e.q ? [e.q] : []);
function ul_qLabel(q) {
  const m = String(q.url || '').match(/^\/api\/tasks\/(-?\d+)/), t = m ? S.tasks.get(+m[1]) : null, title = t?.title || q.body?.title || '';
  return title ? tr('Edited {0}', qn(String(title).slice(0, 40))) : trn('{0} change waiting', '{0} changes waiting', 1);
}
function ul_dev(d) {
  if (!d) return '';
  if (d === histDevice()) return tr('This device');
  return String(d).replace(/ \([a-z0-9]{4}\)$/, '');
}
function ul_time(ms) {
  if (!ms) return '';
  const d = new Date(ms), now = new Date();
  const o = d.toDateString() === now.toDateString() ? {hour: '2-digit', minute: '2-digit'} : {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'};
  return d.toLocaleString(LOCALE(), /** @type {any} */ (o));
}
// the rows (see the head of the file); off = cannot be undone from here, why = the reason shown under it
// the tasks a step of this browser changed (a bundled step: its parts too)
const ul_tids = e => !e ? [] : [...(e.snaps || []), ...(e.after || [])].map(x => +rid(x.id)).filter(Boolean).concat((e.parts || []).flatMap(ul_tids));
function ul_rows() {
  const linked = new Set(HIST.undo.flatMap(ul_qOf));
  const pend = OUT.q.filter(q => !q.done && !linked.has(q)).map(q => ({key: 'q:' + q.k, kind: 'q', label: ul_qLabel(q), at: 0, off: true, why: tr('Not sent yet')}));
  const loc = HIST.undo.filter(e => !e.srv).map(e => ({key: ul_key(e), kind: 'l', e, label: e.label, at: e.at || 0, area: e.area, pend: histPending(e)}));
  // #3860 (CI red of 2.848.0, undo_ui): since 2.774.0 (#5251) the server records every task step too (kind 'task', "Edited …"); a
  // step this browser still holds in its own history is listed once, as its own row: the server's twin of it (same device, same
  // task, not older than the own step's second - the server's times are whole seconds) stays out, else both rows interleaved by
  // the second and "Back up to here" took the change back twice
  const mine = new Map();
  for (const e of HIST.undo) if (!e.srv) for (const id of ul_tids(e)) mine.set(id, Math.min(mine.get(id) ?? Infinity, Math.floor((e.at || 0) / 1000) * 1000));
  const twin = g => g.kind === 'task' && !!g.device && g.device === histDevice() && mine.has(+g.ref_id) && (Date.parse(g.at) || 0) >= /** @type {number} */ (mine.get(+g.ref_id));
  const srv = (UL.items || []).filter(g => !twin(g)).map(g => ({key: 's:' + g.id, kind: 's', g, label: g.label || tr('Change'), at: Date.parse(g.at) || 0, area: g.area, dev: g.device, state: g.state}));
  const rows = [...loc, ...srv].sort((a, b) => b.at - a.at).slice(0, UL_MAX);
  let wall = '';
  for (const r of rows) {
    if (wall) { r.off = true; r.why = wall; continue; }
    if (r.kind !== 's') continue;
    if (r.state === 'barrier') { r.off = true; r.why = tr('Cannot be undone, so older steps stay'); wall = tr('Behind a step that cannot be undone'); }
    else if (r.state === 'toobig') { r.off = true; r.why = trn('Too big to undo ({0} object)', 'Too big to undo ({0} objects)', r.g.parts || 0); wall = tr('Behind a step that cannot be undone'); }
    else if (r.state === 'noaccess') { r.off = true; r.why = tr('You may not change it any more, so it cannot be undone'); }
    else if (r.state === 'undone') { r.redo = true; r.why = tr('Undone'); }
    else if (r.state === 'partial') r.why = tr('Partly undone');
  }
  return [...pend, ...rows];
}
function ul_rowHtml(r) {
  const meta = [ul_time(r.at), r.area ? histAreaName(r.area) : '', r.kind === 's' ? ul_dev(r.dev) : r.kind === 'l' ? tr('only this device') : ''].filter(Boolean).join(' · ');
  const tags = [r.why, r.pend ? tr('waiting for the connection') : ''].filter(Boolean).join(' · ');
  const btn = r.redo ? `<button type="button" class="btn sm" data-ul-redo="${r.g.id}"${UL.busy ? ' disabled' : ''}>${esc(tr('Redo'))}</button>`
    : r.kind === 'q' ? '' : `<button type="button" class="btn sm" data-ul-go="${esc(r.key)}"${r.off || UL.busy ? ' disabled aria-disabled="true"' : ''}>${esc(tr('Back up to here'))}</button>`;
  return `<li class="ulrow ul-${r.kind}${r.off ? ' uloff' : ''}${r.redo ? ' ulundone' : ''}" data-ul="${esc(r.key)}"><div class="ulmain"><span class="ullab">${esc(r.label || '')}</span>`
    + `${meta ? `<small class="ulmeta">${esc(meta)}</small>` : ''}${tags ? `<small class="ultag">${esc(tags)}</small>` : ''}</div>${btn}</li>`;
}
function ul_inner() {
  const rows = ul_rows();
  const note = UL.note ? `<p class="ulnote" role="status">${esc(UL.note)}</p>` : '';
  const err = UL.err ? `<p class="muted ulerr">${esc(UL.err)}</p>` : UL.items === null && S.me?.kind !== 'agent' ? `<p class="muted lempty">${esc(tr('Loading…'))}</p>` : '';
  if (!rows.length) return note + err + (UL.items !== null || UL.err ? `<p class="muted ulempty">${esc(tr('Nothing to undo'))}</p>` : '');
  return `${note}${err}<ol class="ullist" aria-label="${esc(tr('Recent steps'))}">${rows.map(ul_rowHtml).join('')}</ol>`;
}
// the hosts: the window's body scrolls itself, the page's body scrolls with #view
function ul_hosts() { return /** @type {HTMLElement[]} */ ([...document.querySelectorAll('.ulbody')]); }
function ul_scroller(h) { return h.classList.contains('ulpg') ? $('#view') || h : h; }
// in place: the first row seen at the top stays where it is (rows above it may come and go)
function ul_paint(h, html) {
  if (UL.html.get(h) === html) return;
  const sc = ul_scroller(h), top = sc.getBoundingClientRect().top;
  let key = '', off = 0;
  if (sc.scrollTop > 0) for (const li of h.querySelectorAll('.ulrow')) { const r = li.getBoundingClientRect(); if (r.bottom > top) { key = li.getAttribute('data-ul') || ''; off = r.top - top; break; } }
  const fo = /** @type {HTMLElement|null} */ (document.activeElement?.closest?.('.ulbody') ? document.activeElement : null);
  const fk = fo?.getAttribute('data-ul-go') || fo?.getAttribute('data-ul-redo') || '';
  h.innerHTML = html; UL.html.set(h, html);
  const find = (sel, attr, v) => /** @type {HTMLElement|undefined} */ ([...h.querySelectorAll(sel)].find(x => attr.some(a => x.getAttribute(a) === v)));
  if (key) { const li = find('.ulrow', ['data-ul'], key); if (li) sc.scrollTop += li.getBoundingClientRect().top - top - off; }
  if (fk) find('[data-ul-go], [data-ul-redo]', ['data-ul-go', 'data-ul-redo'], fk)?.focus({preventScroll: true});
}
function ul_draw() { const html = ul_inner(); for (const h of ul_hosts()) ul_paint(h, html); }
async function ul_fetch() {
  if (S.me?.kind === 'agent') { UL.items = []; return; }
  try {
    const j = await rawFetch('GET', '/api/undo?limit=' + UL_MAX);
    UL.items = j.items || []; UL.err = ''; UL.at = Date.now();
  } catch (x) {
    if (UL.items === null) UL.items = [];
    UL.err = x instanceof Offline ? tr('Only available online.') + ' ' + tr('The steps of this device are listed.') : '';
  }
}
// live while a host is open: the own counter moved -> the server's rows again; else the rows of this browser (cheap)
function ul_live() {
  if (UL.t) return;
  UL.undo = S.lpA?.undo;
  UL.t = setInterval(() => {
    if (!ul_hosts().length) { clearInterval(UL.t); UL.t = 0; UL.note = ''; return; }
    if (S.lpA?.undo !== UL.undo && !UL.busy) { UL.undo = S.lpA?.undo; ul_fetch().then(ul_draw); return; }
    ul_draw();
  }, 1000);
}
function ul_head() { return `<div class="ulhead"><h2>${esc(tr('Recent steps'))}</h2><p class="muted">${esc(tr('Your steps of the last {0} days on every device, newest first.', 30))}</p></div>`; }
// the window (right-click / long-press on ←)
function ul_open(anchor) {
  UL.note = '';
  const p = openPop(anchor, `<div class="ulpop" role="dialog" aria-label="${esc(tr('Recent steps'))}">${ul_head()}<div class="ulbody">${ul_inner()}</div></div>`);
  p.classList.add('ulwin');
  if (!isMobile()) {  // as wide as it needs, inside the window
    const r = anchor.getBoundingClientRect(), w = p.offsetWidth, h = p.offsetHeight;
    p.style.left = Math.max(12, Math.min(r.left, innerWidth - w - 12)) + 'px';
    p.style.top = (r.bottom + 6 + h > innerHeight - 12 ? Math.max(12, r.top - h - 6) : r.bottom + 6) + 'px';
  }
  ul_fetch().then(ul_draw);
  ul_live();
  return p;
}
// the page (#steps, the account menu)
function viewSteps() {
  if (UL.items === null || Date.now() - UL.at > 4000) ul_fetch().then(ul_draw);
  setTimeout(ul_live, 0);
  return `<div class="ulpage">${ul_head()}<div class="ulbody ulpg">${ul_inner()}</div></div>`;
}
const ul_stayed = (st, items) => st.map(x => { const g = items.find(i => i.id === x.group); return `${g?.label || tr('Change')}: ${x.reason}`; });
// "Undo up to here" (see the head of the file)
async function ul_go(key) {
  if (UL.busy || HIST.busy) return;
  const rows = ul_rows().filter(r => r.kind !== 'q'), t = rows.findIndex(r => r.key === key);
  if (t < 0 || rows[t].off) return;
  UL.busy = true; UL.note = ''; ul_draw();
  const items = UL.items || [], msg = [], stayed = [];
  let n = 0, srv = false;
  try {
    for (let i = 0; i <= t;) {
      const kind = rows[i].kind; let j = i;
      while (j <= t && rows[j].kind === kind) j++;
      const run = rows.slice(i, j); i = j;
      if (kind === 'l') {
        const r = await histStep('undo', 1, run.map(x => x.e));
        n += r.done;
        if (r.stop || r.done < run.length) break;
        continue;
      }
      const todo = run.filter(x => x.state !== 'undone');
      if (!todo.length) continue;
      srv = true;
      const a = await api('POST', `/api/undo/to/${todo[todo.length - 1].g.id}`);
      n += (a.undone || []).length + (a.partial || []).length;
      stayed.push(...ul_stayed(a.stayed || [], items));
      if (a.stopped) { msg.push(tr('Stopped before a step that cannot be undone: {0}', a.stopped.label || '')); break; }
    }
  } catch (x) { console.warn('recent steps', x); /* api() said why */ } finally {
    UL.busy = false;
  }
  if (srv) {
    try { if (OUT.online && !OUT.q.length) await load(); render(); } catch { /* the page may be gone */ }
    if (typeof ofdDraw === 'function' && typeof OFD !== 'undefined' && OFD.doc) { OFD.list = null; ofdDraw(); }  // lazy-ok: an open office document shows what came back
  }
  await ul_fetch();
  const head = trn('{0} step undone', '{0} steps undone', n);
  UL.note = [head, ...msg, stayed.length ? tr('Stayed as it is: {0}', stayed.slice(0, 5).join('; ') + (stayed.length > 5 ? ' …' : '')) : ''].filter(Boolean).join(' ');
  if (srv) toast(UL.note, null, stayed.length ? 10000 : 5000);
  ul_draw();
}
async function ul_redo(gid) {
  if (UL.busy) return;
  UL.busy = true; UL.note = ''; ul_draw();
  try {
    const a = await api('POST', `/api/undo/${+gid}/redo`);
    const st = ul_stayed(a.stayed || [], UL.items || []);
    UL.note = [a.text, st.length ? tr('Stayed as it is: {0}', st.slice(0, 5).join('; ')) : ''].filter(Boolean).join(' ');
    try { if (OUT.online && !OUT.q.length) await load(); render(); } catch { /* the page may be gone */ }
  } catch { /* api() said why */ } finally { UL.busy = false; }
  await ul_fetch();
  ul_draw();
}
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('.ulbody [data-ul-go], .ulbody [data-ul-redo]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const k = b.getAttribute('data-ul-go');
  if (k) ul_go(k); else ul_redo(b.getAttribute('data-ul-redo'));
});
