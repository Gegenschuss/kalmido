// @ts-check
/* Kalmido web client: the properties of a project's tasks per project type (2.412.0, #3552).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- 2.412.0 (#3552): one source for what a task of a project shows. Every project type has a cut (the server's
// kalmido/lists/templates.py PTYPE_PROPS_OFF, the same keys): a property it switches off shows neither in the task panel
// nor as a column ("Shown fields…") nor in the task's "…" menu. The owner and the project admins switch single ones back on
// or off in the project's options (Properties; lists.props keeps only the deviations, "As the project type" clears them).
// A type change takes the new type's cut, what was switched on by hand stays on. Hidden = display only: nothing is
// deleted, agents / import / API keep setting values, and a task that already has something in a hidden property keeps
// showing it (pz_show). A blank project ('') shows everything its modules allow.
const PZ_KEYS = [['ticket', N_('Task number'), 'hash'], ['ttype', N_('Ticket type'), 'bug'], ['repo', N_('Repository and code'), 'git'],
  ['deps', N_('Dependencies'), 'deps'], ['who', N_('Assignee'), 'user'], ['points', N_('Story points'), 'hash'],
  ['time', N_('Time tracking'), 'clock'], ['video', N_('Video sign-off'), 'film'], ['client', N_('Client and contacts'), 'users'],
  ['docs', N_('Documents and invoices'), 'file'], ['tags', N_('Tags'), 'tag']];
const PZ_OFF = {software: ['video', 'client', 'docs'], agency: ['repo', 'ttype'],
  private: ['ticket', 'ttype', 'repo', 'deps', 'who', 'points', 'time', 'video', 'client', 'docs']};
// the list columns (render.js COLS) that belong to a property
const PZ_COL = {who: 'who', time: 'time', deps: 'deps', tags: 'tags'};
const pz_name = k => tr((PZ_KEYS.find(x => x[0] === k) || [0, k])[1]);
function pz_own(l) {  // the deviations of a list {key: 0 | 1}
  if (!l?.props) return {};
  if (typeof l.props === 'object') return l.props;
  try { return JSON.parse(l.props) || {}; } catch { return {}; }
}
const pz_typeOn = (pt, k) => !(PZ_OFF[pt || ''] || []).includes(k);
// the property k is on for the list lid (unknown lists, the basket, plain lists: on)
function pz_on(lid, k) {
  const l = typeof lid === 'object' ? lid : listById(lid); if (!l || !k) return true;
  const o = pz_own(l);
  return k in o ? !!+o[k] : pz_typeOn(l.ptype, k);
}
// shown at a task: on, or the task already has something in it (it stays visible at this task)
const pz_show = (t, k, has) => !t || pz_on(t.list_id, k) || !!has;
// what a switch to type pt hides that shows now (for the hint before the change)
function pz_lost(l, pt) {
  const o = pz_own(l);
  return PZ_KEYS.map(x => x[0]).filter(k => pz_on(l, k) && !pz_typeOn(pt, k) && !+o[k]);
}

// ---- the part "Properties" in the project's options (dialogs.js listModal): owner + project admins only
function pz_boxHtml(l) {
  if (!l || l.is_inbox || !canManage(l)) return '';
  const o = pz_own(l), own = Object.keys(o).length > 0;
  return `<div class="pzbox" id="l-pz"><div class="shint lhint">${esc(l.ptype ? tr('What the tasks of this project show. {0} switches off what it does not need; switch single ones back on here.', ptypeName(l.ptype)) : tr('What the tasks of this project show.'))} ${esc(tr('Hidden is display only: nothing is deleted.'))}</div>
    <div class="pzlist" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(13rem,1fr));gap:.25rem .75rem">${PZ_KEYS.map(([k, n, i]) => `<label class="chkl pzrow"><input type="checkbox" data-pz="${k}" ${pz_on(l, k) ? 'checked' : ''}>${ic(i, 's')}<span>${esc(tr(n))}</span>${k in o ? `<span class="muted pzown" style="margin-inline-start:auto">${esc(tr('changed'))}</span>` : ''}</label>`).join('')}</div>
    <div class="row pzreset"><span class="lmsum muted">${esc(own ? trn('{0} changed by hand', '{0} changed by hand', Object.keys(o).length) : tr('As the project type'))}</span><span class="spacer"></span>${own ? `<button type="button" class="btn sm" data-pz-reset>${ic('undo', 's')} ${esc(tr('As the project type'))}</button>` : ''}</div></div>`;
}
function pz_wire(md, id) {
  md.addEventListener('change', e => {
    const el = /** @type {HTMLInputElement} */ (e.target), k = el.dataset?.pz; if (!k || !el.closest('#l-pz')) return;
    e.stopPropagation();
    const l = listById(id); if (!l) return;
    const o = {...pz_own(l)};
    if (el.checked === pz_typeOn(l.ptype, k)) delete o[k]; else o[k] = el.checked ? 1 : 0;
    pz_set(id, o, el.checked ? tr('Shown: {0}', pz_name(k)) : tr('Hidden: {0}', pz_name(k))).then(() => pz_sync(md, listById(id)));
  }, true);
  md.addEventListener('click', e => {
    if (!(/** @type {Element} */ (e.target)).closest?.('[data-pz-reset]')) return;
    e.stopPropagation();
    pz_set(id, {}, tr('Properties as the project type')).then(() => pz_sync(md, listById(id)));
  });
}
function pz_sync(md, l) {
  const box = $('#l-pz', md); if (!box || !l) return;
  const html = pz_boxHtml(l); if (!html) { box.remove(); return; }
  const tmp = document.createElement('div'); tmp.innerHTML = html;
  if (tmp.firstElementChild) box.replaceWith(tmp.firstElementChild);
}
const pz_text = o => Object.keys(o).length ? JSON.stringify(Object.fromEntries(Object.keys(o).sort().map(k => [k, +o[k]]))) : '';
async function pz_set(id, o, label) {
  const l = listById(id); if (!l) return;
  const was = typeof l.props === 'string' ? l.props : pz_text(pz_own(l)), v = pz_text(o);
  if (was === v) return;
  try { await optWrite(optSet(() => listById(id), {props: v}), () => api('PATCH', '/api/lists/' + id, {props: o})); } catch { return; }
  render(); if (S.sel) renderDetail();
  const go = to => async () => { await api('PATCH', '/api/lists/' + id, {props: to}); await load(); render(); return {skipped: []}; };
  offerUndo(label, histAdd({label: tr('Properties of {0}', qn(lname(l))), undo: go(was), redo: go(v), lids: [id]}));
}
// before a type change: what goes away (nothing is deleted); false = cancelled
async function pz_askType(l, pt) {
  const lost = pz_lost(l, pt);
  if (!lost.length) return true;
  return askConfirm(tr('Switch to {0}?', ptypeName(pt)), tr('These properties are hidden then: {0}. Nothing is deleted; you can switch them back on under Properties.', lost.map(pz_name).join(', ')), {ok: tr('Switch')});
}
