// @ts-check
// 2.299.0 B (#3191): bank rules -- bookings of a statement marked on their own (private, ignore, no receipt needed) or a
// category for the receipt, by the counterpart's name / IBAN, a word of the purpose, an amount range, the direction. The
// office settings carry the area "Bank rules" (list, edit, on / off, delete with undo, hits); the bank list shows "by rule"
// on a booking and, once the same counterpart was marked the same way twice, the one line "Always like this?".
// Invoices and receipts are never matched by a rule. Server: kalmido/office/bankrules.py (admins of the office only).
'use strict';

const BRL = {oid: null, items: undefined, cats: [], max: 300};
const BRL_ACT = {private: N_('Private'), ignored: N_('Ignore'), noreceipt: N_('No receipt needed'), category: N_('Category')};
const BRL_DIR = {'': N_('Money in and out'), in: N_('Money in'), out: N_('Money out')};
const brl_act = r => r.action === 'category' ? tr('Category {0}', r.category || '') : tr(BRL_ACT[r.action] || r.action);

async function brl_load() {
  BRL.oid = OFC.info?.org_id;
  try { const j = await api('GET', '/api/office/bank/rules'); BRL.items = j.items || []; BRL.cats = j.categories || []; BRL.max = j.max || 300; }
  catch (x) { BRL.items = null; }
  brl_draw();
}
function brl_draw() { const sec = $('.brlset'); if (sec) sec.outerHTML = brl_settingsHtml(); }  // only this section: the settings form keeps what is typed there
const brl_stale = () => { if (typeof BNK === 'object') { BNK.data = null; } if (typeof bfbBooksStale === 'function') bfbBooksStale(); };
function brl_cond(r) {
  const amt = r.amount_min || r.amount_max ? [r.amount_min ? tr('from {0}', ofcMoney(+r.amount_min)) : '', r.amount_max ? tr('to {0}', ofcMoney(+r.amount_max)) : ''].filter(Boolean).join(' ') : '';
  return [r.counterpart ? `„${r.counterpart}“` : '', r.iban ? `${r.iban.slice(0, 4)} … ${r.iban.slice(-4)}` : '', r.purpose ? tr('purpose „{0}“', r.purpose) : '',
    r.direction ? tr(BRL_DIR[r.direction]) : '', amt].filter(Boolean).join(' · ');
}

// ---- the area in the office settings
function brl_settingsHtml() {
  if (!ofcAdmin()) return '';
  if (BRL.oid !== OFC.info?.org_id) { BRL.oid = OFC.info?.org_id; BRL.items = undefined; setTimeout(brl_load, 0); }
  const it = BRL.items;
  if (it === null) return '';  // no right to the bank (the server said no)
  const list = it === undefined ? `<p class="muted">${tr('Loading…')}</p>`
    : !it.length ? `<p class="muted brlempty">${tr('No rules yet. Mark a booking the same way twice and the bank list offers one.')}</p>`
      : `<ul class="ofclist brllist" role="list">${it.map(r => `<li class="ofcrow brlrow ${r.active ? '' : 'arch'}" data-rule="${r.id}"><span class="ofcn"><b>${esc(r.name)}</b>
        <small class="muted">${esc(brl_cond(r))} → ${esc(brl_act(r))}${r.account ? ` (${esc(r.account)})` : ''}</small><small class="muted">${esc(trn('{0} hit', '{0} hits', r.hits))}${r.last_hit_at ? ` · ${esc(fmtDateLoc(r.last_hit_at.slice(0, 10)))}` : ''}</small></span>
        <label class="chkl swl" title="${esc(r.active ? tr('Active') : tr('Paused'))}"><span class="swc"><input type="checkbox" role="switch" data-brl-on="${r.id}" ${r.active ? 'checked' : ''} aria-label="${esc(tr('Active'))}"><span class="swt" aria-hidden="true"></span></span></label>
        <button type="button" class="btn sm ghost" data-brl="edit" data-id="${r.id}">${tr('Edit')}</button>
        ${r.hits && r.action !== 'category' ? `<button type="button" class="btn sm ghost" data-brl="revert" data-id="${r.id}">${tr('Undo its marks')}</button>` : ''}
        <button type="button" class="btn sm ghost icon" data-brl="del" data-id="${r.id}" aria-label="${esc(tr('Delete'))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>`;
  return `<section class="brlset" data-fg-skip aria-labelledby="brl-h"><h3 id="brl-h">${tr('Bank rules')}</h3>
    <p class="muted ofchint">${tr('Rules mark bookings of a new statement on their own: private, ignore or no receipt needed – or name the category of the receipt. Invoices and receipts are never matched by a rule; a locked month stays as it is.')}</p>
    ${list}${it && it.length < BRL.max ? `<div class="lacts"><button type="button" class="btn sm" data-brl="new">${ic('plus', 's')} ${tr('New rule')}</button></div>` : ''}</section>`;
}

// ---- the editor (new / edit); init = the values of a new rule (a suggestion of the bank list)
function brl_edit(r, init) {
  const v = r || {action: 'private', direction: '', ...init}, md = /** @type {any} */ (modal('')), card = $('.card', md);
  md.classList.add('ofcdlg', 'brldlg');
  const cats = BRL.cats || [];
  card.innerHTML = `<h3>${r ? tr('Edit rule') : tr('New rule')}</h3>
    ${ofcRowF('brl-name', tr('Name'), ofcIn('brl-name', v.name, {max: 80, ph: tr('optional')}))}
    ${ofcRowF('brl-cp', tr('Paid to / from contains'), ofcIn('brl-cp', v.counterpart))}
    ${ofcRowF('brl-iban', tr('IBAN of the counterpart'), ofcIn('brl-iban', v.iban, {max: 40, ph: tr('optional')}))}
    ${ofcRowF('brl-pp', tr('Purpose contains'), ofcIn('brl-pp', v.purpose, {ph: tr('optional')}))}
    ${ofcRowF('brl-dir', tr('Direction'), ofcSel('brl-dir', v.direction || '', Object.entries(BRL_DIR).map(([k, n]) => [k, tr(n)])))}
    <div class="row"><label for="brl-min">${tr('Amount')}</label><span class="lacts">${ofcIn('brl-min', v.amount_min ? fmtNum(+v.amount_min, 2) : '', {num: true, ph: tr('from')})}${ofcIn('brl-max', v.amount_max ? fmtNum(+v.amount_max, 2) : '', {num: true, ph: tr('to')})}<span class="muted">${ofcSym(ofcHome())}</span></span></div>
    ${ofcRowF('brl-act', tr('Then'), ofcSel('brl-act', v.action, Object.entries(BRL_ACT).map(([k, n]) => [k, tr(n)])))}
    <div class="brl-cat" ${v.action === 'category' ? '' : 'hidden'}>${ofcRowF('brl-category', tr('Category'), ofcIn('brl-category', v.category, {max: 80, list: 'brl-cats'}), tr('A receipt matched with such a booking gets this category when it has none.'))}
      <datalist id="brl-cats">${cats.map(x => `<option value="${esc(x)}">`).join('')}</datalist>${ofcRowF('brl-acct', tr('Account (optional)'), ofcIn('brl-acct', v.account, {max: 9, num: true}))}</div>
    ${r ? '' : `<label class="chkl"><input type="checkbox" id="brl-open" checked> ${tr('Apply to the open bookings now')}</label>`}
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button type="button" class="btn" data-brd="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-brd="save">${tr('Save')}</button></div>`;
  const val = id => $(id, md)?.value.trim() || '';
  const num = id => { const s = val(id); if (!s) return null; const n = ofcNum(s); return n == null ? s : String(n); };  // an unreadable one: the server says which
  $('#brl-act', md).addEventListener('change', e => { $('.brl-cat', md).hidden = /** @type {any} */ (e.target).value !== 'category'; });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-brd]'); if (!b) return;
    if (b.dataset.brd === 'close') { md.remove(); return; }
    const body = {name: val('#brl-name'), counterpart: val('#brl-cp'), iban: val('#brl-iban'), purpose: val('#brl-pp'), direction: val('#brl-dir'),
      amount_min: num('#brl-min'), amount_max: num('#brl-max'), action: val('#brl-act'), category: val('#brl-category'), account: val('#brl-acct')};
    b.disabled = true;
    try {
      if (r) await brl_put(r.id, body, r); else await brl_new({...body, apply_open: !!$('#brl-open', md)?.checked});
      md.remove();
    } catch (x) { b.disabled = false; $('.aerr', md).textContent = x.message || tr('unknown'); }
  });
  return md;
}
const brl_body = r => ({name: r.name, counterpart: r.counterpart || '', iban: r.iban || '', purpose: r.purpose || '', direction: r.direction || '',
  amount_min: r.amount_min, amount_max: r.amount_max, action: r.action, category: r.category || '', account: r.account || '', active: !!r.active});

// ---- actions (one undo step each)
async function brl_new(body) {
  const j = await api('POST', '/api/office/bank/rules', body), id = j.rule.id;
  BRL.items = undefined; brl_stale(); brl_load();
  offerUndo(j.applied ? trn('Rule saved · {0} booking marked', 'Rule saved · {0} bookings marked', j.applied) : tr('Rule saved'), histAdd({label: tr('Bank rule made'),
    undo: async () => { await api('POST', `/api/office/bank/rules/${id}/revert`); await api('DELETE', `/api/office/bank/rules/${id}`); brl_stale(); brl_load(); },
    redo: async () => { await api('POST', `/api/office/bank/rules/${id}/restore`); if (body.apply_open) await api('POST', `/api/office/bank/rules/${id}/apply`); brl_stale(); brl_load(); }}));
  return j;
}
async function brl_put(id, body, was) {
  await api('PUT', `/api/office/bank/rules/${id}`, body); brl_stale(); brl_load();
  offerUndo(tr('Saved'), histAdd({label: tr('Bank rule changed'),
    undo: async () => { await api('PUT', `/api/office/bank/rules/${id}`, brl_body(was)); brl_load(); },
    redo: async () => { await api('PUT', `/api/office/bank/rules/${id}`, body); brl_load(); }}));
}
async function brl_on(id, on) {
  try { await api('PUT', `/api/office/bank/rules/${id}`, {active: on}); } catch (x) { toast(x.message || tr('unknown')); brl_load(); return; }
  brl_load();
  offerUndo(on ? tr('Rule switched on') : tr('Rule switched off'), histAdd({label: tr('Bank rule changed'),
    undo: async () => { await api('PUT', `/api/office/bank/rules/${id}`, {active: !on}); brl_load(); },
    redo: async () => { await api('PUT', `/api/office/bank/rules/${id}`, {active: on}); brl_load(); }}));
}
async function brl_del(id) {
  try { await api('DELETE', `/api/office/bank/rules/${id}`); } catch (x) { toast(x.message || tr('unknown')); return; }
  brl_load();
  offerUndo(tr('Rule deleted'), histAdd({label: tr('Bank rule deleted'),
    undo: async () => { await api('POST', `/api/office/bank/rules/${id}/restore`); brl_load(); },
    redo: async () => { await api('DELETE', `/api/office/bank/rules/${id}`); brl_load(); }}));
}
async function brl_revert(id) {
  const r = (BRL.items || []).find(x => x.id === id);
  if (!await askConfirm(tr('Undo the marks of this rule?'), tr('Every booking this rule marked becomes open again (not in locked months). The rule itself stays.'), {ok: tr('Undo its marks')})) return;
  let j;
  try { j = await api('POST', `/api/office/bank/rules/${id}/revert`); } catch (x) { toast(x.message || tr('unknown')); return; }
  brl_stale(); brl_load();
  const msg = trn('{0} booking open again', '{0} bookings open again', j.undone) + (j.locked ? ` · ${trn('{0} in a locked month stays', '{0} in a locked month stay', j.locked)}` : '');
  offerUndo(msg, histAdd({label: tr('Marks of a bank rule undone') + (r ? ` (${r.name})` : ''),
    undo: async () => { await api('POST', `/api/office/bank/rules/${id}/apply`); brl_stale(); brl_load(); },
    redo: async () => { await api('POST', `/api/office/bank/rules/${id}/revert`); brl_stale(); brl_load(); }}));
}

// ---- the bank list: "by rule", the rule hint of an open booking, the learned suggestion
function brl_rowHint(t) {
  const h = t.rule_hint; if (!h) return '';
  if (h.tie) return `<p class="muted bnkrh">${ic('info', 's')} ${esc(tr('Several rules fit – nothing was marked automatically.'))}</p>`;
  if (h.action === 'category') return `<p class="muted bnkrh">${ic('info', 's')} ${esc(tr('Rule {0}: category {1} for the receipt', h.name, h.category || ''))}</p>`;
  return `<div class="bnksug bnkrh"><span class="bnksn"><small class="muted">${esc(tr('Rule {0}', h.name))}</small><b>${esc(tr(BRL_ACT[h.action] || h.action))}</b></span>
    <button class="btn sm" data-bnk="match" data-id="${t.id}" data-kind="${esc(h.action)}">${tr('Assign match')}</button></div>`;
}
const brl_byRule = m => m?.by_rule ? `<small class="muted bnkbyr">${esc(tr('by rule {0}', m.by_rule.name || ''))}</small>` : '';
function brl_learned(j) { if (typeof BNK === 'object') BNK.ruleSug = j?.rule_suggestion || null; }
function brl_sugHtml() {
  const s = typeof BNK === 'object' && BNK.ruleSug; if (!s) return '';
  const who = s.counterpart || (s.iban ? `${s.iban.slice(0, 4)} … ${s.iban.slice(-4)}` : '');
  return `<div class="bnkrsug" role="status"><span class="bnkrsn"><b>${esc(tr('Always like this?'))}</b><small class="muted">${esc(who)} → ${esc(brl_act(s))}</small></span>
    <span class="spacer"></span><button type="button" class="btn sm pri" data-brl="sugok">${tr('Always')}</button><button type="button" class="btn sm ghost" data-brl="sugno">${tr('No')}</button></div>`;
}
async function brl_sugTake(yes) {
  const s = BNK.ruleSug; BNK.ruleSug = null; if (!s) return;
  if (!yes) { try { await api('POST', '/api/office/bank/rules/decline', {counterpart: s.counterpart || '', iban: s.iban || ''}); } catch (x) { toast(x.message || tr('unknown')); } ofcDraw(); return; }
  const body = {name: s.counterpart || s.iban || '', ...(s.iban ? {iban: s.iban} : {counterpart: s.counterpart}), action: s.action, category: s.category || '', direction: s.direction || '', apply_open: true};
  try { await brl_new(body); } catch (x) { toast(x.message || tr('unknown')); }
  bnkReload();
}

document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-brl]'); if (!b) return;
  const a = b.dataset.brl, id = +b.dataset.id;
  if (a === 'new') brl_edit(null);
  else if (a === 'edit') { const r = (BRL.items || []).find(x => x.id === id); if (r) brl_edit(r); }
  else if (a === 'del') brl_del(id);
  else if (a === 'revert') brl_revert(id);
  else if (a === 'sugok') brl_sugTake(true);
  else if (a === 'sugno') brl_sugTake(false);
  else return;
  e.preventDefault();
});
document.addEventListener('change', e => {
  const i = /** @type {any} */ (e.target).closest?.('[data-brl-on]'); if (!i) return;
  brl_on(+i.dataset.brlOn, i.checked);
});
