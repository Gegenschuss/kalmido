// @ts-check
// 2.470.0 (#3596, part A): the bank accounts of the office as master data -- the area in Settings > Company & office > Bank & taxes:
// list, new, edit, set as default, archive with undo. Documents, GiroCode and DATEV read the default account. Server:
// kalmido/office/bankacc.py (who may see the company's bank data, nobody else).
'use strict';

const BACC = {oid: null, items: undefined, archived: []};
const BKA_API = '/api/office/settings/bank-accounts';
const bka_iban = v => (v || '').replace(/(.{4})/g, '$1 ').trim();

async function bka_load() {
  BACC.oid = OFC.info?.org_id;
  try {
    const [j, a] = await Promise.all([api('GET', BKA_API), api('GET', `${BKA_API}?archived=1`)]);
    BACC.items = j.items || []; BACC.archived = a.items || []; await bka_setCount(j.count);
  } catch (x) { BACC.items = null; }
  bka_draw();
}
function bka_draw() { const sec = $('.bkaset'); if (sec) sec.outerHTML = bka_settingsHtml(); }  // only this section: the settings form keeps what is typed there
// the company fields show IBAN and BIC only while there is no account (ofcCompanyFieldsHtml); what documents print came from the server anew
async function bka_setCount(n) {
  const had = !!OFC.info?.bank_accounts;
  if (OFC.info) OFC.info.bank_accounts = n;
  if (had !== !!n) { await ofcInfo(true); ofcDraw(); }
}
const bka_reload = bka_load;

// ---- the area in the office settings
function bka_rowHtml(r) {
  const sub = [r.iban ? bka_iban(r.iban) : '', r.bic, r.datev_account ? tr('DATEV account {0}', r.datev_account) : ''].filter(Boolean).join(' · ');
  return `<li class="ofcrow bkarow" data-acct="${r.id}" data-bka="tap" data-id="${r.id}"><span class="ofcn"><b>${esc(r.label)}</b><small class="muted">${esc(sub)}</small></span>
    ${r.is_default ? `<span class="rotag">${esc(tr('Default'))}</span>` : `<button type="button" class="btn sm ghost" data-bka="default" data-id="${r.id}">${tr('Make default')}</button>`}
    <button type="button" class="btn sm ghost" data-bka="edit" data-id="${r.id}">${tr('Edit')}</button>
    <button type="button" class="btn sm ghost" data-bka="archive" data-id="${r.id}">${tr('Archive')}</button></li>`;
}
function bka_settingsHtml() {
  if (typeof ofcAdmin !== 'function' || !ofcAdmin()) return '';
  if (BACC.oid !== OFC.info?.org_id) { BACC.oid = OFC.info?.org_id; BACC.items = undefined; setTimeout(bka_load, 0); }
  const it = BACC.items;
  if (it === null) return '<section class="bkaset" hidden></section>';  // no right to the bank data (the server said no)
  const list = it === undefined ? `<p class="muted">${tr('Loading…')}</p>`
    : !it.length ? `<p class="muted bkaempty">${tr('No bank account yet. Documents print the free bank lines until there is one.')}</p>`
      : `<ul class="ofclist bkalist" role="list">${it.map(bka_rowHtml).join('')}</ul>`;
  const old = BACC.archived.length ? `<details class="bkaold"><summary class="muted">${esc(trn('{0} archived', '{0} archived', BACC.archived.length))}</summary><ul class="ofclist" role="list">${BACC.archived.map(r => `<li class="ofcrow bkarow arch"><span class="ofcn"><b>${esc(r.label)}</b><small class="muted">${esc(bka_iban(r.iban))}</small></span><button type="button" class="btn sm ghost" data-bka="restore" data-id="${r.id}">${tr('Restore')}</button></li>`).join('')}</ul></details>` : '';
  return `<section class="bkaset" data-fg-skip aria-labelledby="bka-h"><h3 id="bka-h">${tr('Bank accounts')}</h3>
    <p class="muted ofchint">${tr('The default account is printed on documents and goes into the GiroCode and the DATEV export. Finished documents keep the account they were made with.')}</p>
    ${list}${it ? `<div class="lacts"><button type="button" class="btn sm" data-bka="new">${ic('plus', 's')} ${tr('New bank account')}</button></div>` : ''}${old}</section>`;
}

// ---- the editor (new / edit)
function bka_edit(r) {
  const v = r || {}, md = /** @type {any} */ (modal('')), card = $('.card', md);
  md.classList.add('ofcdlg', 'bkadlg');
  card.innerHTML = `<h3>${r ? tr('Edit bank account') : tr('New bank account')}</h3>
    ${ofcRowF('bka-label', tr('Name'), ofcIn('bka-label', v.label, {max: 80, ph: tr('optional')}))}
    ${ofcRowF('bka-iban', tr('IBAN'), ofcIn('bka-iban', bka_iban(v.iban), {max: 54}))}
    ${ofcRowF('bka-bic', tr('BIC'), ofcIn('bka-bic', v.bic, {max: 11}))}
    ${ofcRowF('bka-bank', tr('Bank'), ofcIn('bka-bank', v.bank_name, {max: 120}))}
    ${ofcRowF('bka-datev', tr('DATEV account'), ofcIn('bka-datev', v.datev_account, {max: 9, ph: tr('optional')}), tr('Empty: the bank account of the DATEV settings.'))}
    ${!r && BACC.items?.length ? `<label class="chkl"><input type="checkbox" id="bka-default"> ${tr('Make default')}</label>` : ''}
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button type="button" class="btn" data-bkd="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-bkd="save">${tr('Save')}</button></div>`;
  const val = id => $(id, md)?.value.trim() || '';
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-bkd]'); if (!b) return;
    if (b.dataset.bkd === 'close') { md.remove(); return; }
    const body = {label: val('#bka-label'), iban: val('#bka-iban'), bic: val('#bka-bic'), bank_name: val('#bka-bank'), datev_account: val('#bka-datev')};
    b.disabled = true;
    try {
      if (r) await bka_put(r, body);
      else { await api('POST', BKA_API, {...body, default: !!$('#bka-default', md)?.checked}); toast(tr('Saved')); await bka_reload(); }
      md.remove();
    } catch (x) { b.disabled = false; $('.aerr', md).textContent = x.message || tr('unknown'); }
  });
  return md;
}
const bka_body = r => ({label: r.label, iban: r.iban, bic: r.bic, bank_name: r.bank_name, datev_account: r.datev_account});

// ---- actions (one undo step each)
async function bka_put(r, body) {
  const was = bka_body(r), put = b => async () => { await api('PUT', `${BKA_API}/${r.id}`, b); await bka_reload(); };
  await api('PUT', `${BKA_API}/${r.id}`, body); await bka_reload();
  offerUndo(tr('Saved'), histAdd({label: tr('Bank account changed'), undo: put(was), redo: put(body)}));
}
async function bka_default(id) {
  const was = (BACC.items || []).find(x => x.is_default), make = rid => async () => { await api('POST', `${BKA_API}/${rid}/default`); await bka_reload(); };
  try { await make(id)(); } catch (x) { toast(x.message || tr('unknown')); return; }
  if (was) offerUndo(tr('Default account changed'), histAdd({label: tr('Default account changed'), undo: make(was.id), redo: make(id)}));
}
async function bka_archive(id) {
  let j;
  try { j = await api('POST', `${BKA_API}/${id}/archive`); } catch (x) { toast(x.message || tr('unknown')); return; }
  await bka_reload();
  const back = async () => { await api('POST', `${BKA_API}/${id}/restore`); if (j.was_default) await api('POST', `${BKA_API}/${id}/default`); await bka_reload(); };
  const again = async () => { await api('POST', `${BKA_API}/${id}/archive`); await bka_reload(); };
  offerUndo(tr('Bank account archived'), histAdd({label: tr('Bank account archived'), undo: back, redo: again}));
}
async function bka_restore(id) {
  try { await api('POST', `${BKA_API}/${id}/restore`); } catch (x) { toast(x.message || tr('unknown')); return; }
  await bka_reload();
  offerUndo(tr('Bank account restored'), histAdd({label: tr('Bank account restored'),
    undo: async () => { await api('POST', `${BKA_API}/${id}/archive`); await bka_reload(); },
    redo: async () => { await api('POST', `${BKA_API}/${id}/restore`); await bka_reload(); }}));
}

// 2.525.0 (#4281): one-meaning guard: data-bka - its own actions only, else return (office_bookarch.js has other values)
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-bka]'); if (!b) return;
  const a = b.dataset.bka, id = +b.dataset.id;
  if (a === 'new') bka_edit(null);
  else if (a === 'tap' && !isMobile()) return;  // only a phone opens an account by tapping its row
  else if (a === 'edit' || a === 'tap') { const r = (BACC.items || []).find(x => x.id === id); if (r) bka_edit(r); }
  else if (a === 'default') bka_default(id);
  else if (a === 'archive') bka_archive(id);
  else if (a === 'restore') bka_restore(id);
  else return;
  e.preventDefault();
});
// on a phone the row has no buttons (office.css), a long press opens what they did
ms_rowMenu('.bkarow[data-acct]', r => {
  const by = k => () => $(`[data-bka="${k}"]`, r).click();
  menu(r, [{label: tr('Edit'), icon: 'edit', fn: by('edit')},
    $('[data-bka="default"]', r) ? {label: tr('Make default'), icon: 'check', fn: by('default')} : null,
    '-', {label: tr('Archive'), icon: 'trash', cls: 'danger', fn: by('archive')}]);
});
