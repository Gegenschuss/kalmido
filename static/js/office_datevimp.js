// @ts-check
/* Kalmido web client: Office & finance, the DATEV import (2.148.0 D, #2458; server: office/datevimp.py). In the DATEV
   settings (office_datev.js dx_settingsHtml calls dimp_sectionHtml): the button "Read DATEV data" (a file of the tax advisor:
   debtors / creditors or a booking batch -> preview -> take over -> undo in the toast) and the list of the suppliers
   (rename, delete with undo). dimp_obHtml(year) = the opening balances of a year for the bookkeeping. Admins only.
   Classic script sharing the global scope with the others (load order: lazyload.js, module "office"). */
'use strict';

const DIMP = /** @type {any} */ ({sup: null, supOid: null, ob: {}, obOid: null, file: null});
const DIMP_ACT = {new: N_('new'), update: N_('updated'), replace: N_('replaces'), skip: N_('skipped')};

// ---- the section in the DATEV settings
function dimp_sectionHtml() {
  if (typeof ofcAdmin !== 'function' || !ofcAdmin()) return '';
  if (DIMP.supOid !== OFC.info?.org_id) { DIMP.supOid = OFC.info?.org_id; DIMP.sup = null; }
  if (!DIMP.sup) setTimeout(dimp_supLoad, 0);
  return `<section class="dimp" data-fg-skip aria-labelledby="dimp-h"><h4 id="dimp-h">${tr('DATEV data from your tax advisor')}</h4>
    <p class="muted ofchint">${tr('Debtors and creditors (master data) or the opening balances of a booking batch. You see a preview first.')}</p>
    <div class="lacts"><button type="button" class="btn sm" data-dimp="open">${ic('upload', 's')}<span>${tr('Read DATEV data')}</span></button></div>
    <h4>${tr('Suppliers')}</h4><div id="dimp-sup">${dimp_supHtml()}</div></section>`;
}

async function dimp_supLoad() {
  try { DIMP.sup = (await api('GET', '/api/office/datev/suppliers')).items || []; } catch (x) { DIMP.sup = {error: x.message || tr('unknown')}; }
  const box = $('#dimp-sup'); if (box) box.innerHTML = dimp_supHtml();
}
function dimp_supHtml() {
  const s = DIMP.sup;
  if (!s) return `<p class="muted">${tr('Loading…')}</p>`;
  if (s.error) return `<p class="muted">${esc(s.error)}</p>`;
  if (!s.length) return `<p class="muted ofchint">${tr('No suppliers yet. They come with the creditors of a DATEV master data file.')}</p>`;
  return `<ul class="ofclist dimpsup" role="list">${s.map(x => `<li class="row" data-id="${x.id}"><label for="dimp-s-${x.id}" class="dimpacct">${esc(x.account_no)}</label>
    <span class="lacts"><input id="dimp-s-${x.id}" data-dimp-name="${x.id}" value="${esc(x.name)}" maxlength="80" aria-label="${esc(tr('Name of the supplier {0}', x.account_no))}">
    <small class="muted">${esc([x.zip, x.city].filter(Boolean).join(' '))}</small>
    <button type="button" class="ib" data-dimp="del" data-id="${x.id}" aria-label="${esc(tr('Delete supplier'))}" title="${esc(tr('Delete supplier'))}">${ic('trash', 's')}</button></span></li>`).join('')}</ul>`;
}
async function dimp_rename(el) {
  const id = +el.dataset.dimpName, x = (DIMP.sup || []).find(s => s.id === id), name = el.value.trim();
  if (!x || !name || name === x.name) { if (x && !name) el.value = x.name; return; }
  const old = x.name;
  try {
    await api('PUT', `/api/office/datev/suppliers/${id}`, {name}); x.name = name;
    toast(tr('Saved'), async () => { await api('PUT', `/api/office/datev/suppliers/${id}`, {name: old}); x.name = old; dimp_supLoad(); });
  } catch (_) { el.value = old; }
}
async function dimp_delete(id) {
  await api('DELETE', `/api/office/datev/suppliers/${id}`);
  await dimp_supLoad();
  toast(tr('Supplier deleted'), async () => { await api('POST', `/api/office/datev/suppliers/${id}/restore`); dimp_supLoad(); });
}

// ---- the dialog: file -> preview -> take over
function dimp_dialog() {
  DIMP.file = null;
  const md = ofdDlg(tr('Read DATEV data'), `<p class="muted ofchint">${tr('A DATEV file (EXTF, CSV) from your tax advisor: debtors / creditors or a booking batch. Kalmido only fills empty fields and takes over only opening balances.')}</p>
    <div class="row"><label for="dimp-file">${tr('File')}</label><input type="file" id="dimp-file" accept=".csv,.txt,text/csv,text/plain"></div>
    <div id="dimp-pv" class="dimppv" aria-live="polite"></div>`, tr('Take over'), async () => {
    if (!DIMP.file) throw new Error(tr('Choose a file first'));
    const fd = new FormData(); fd.append('file', DIMP.file);
    const j = await api('POST', '/api/office/datev/import', fd);
    DIMP.sup = null; DIMP.ob = {};
    if (typeof ofcDraw === 'function') ofcDraw();
    toast(dimp_doneText(j), async () => { await api('POST', `/api/office/datev/import/${j.run_id}/undo`); DIMP.sup = null; DIMP.ob = {}; dimp_supLoad(); if (typeof ofcDraw === 'function') ofcDraw(); }, 12000);
  });
  const ok = $('[data-m="ok"]', md); if (ok) ok.disabled = true;
  return md;
}
function dimp_doneText(j) {
  const c = j.counts || {};
  if (j.category === 21) return tr('{0} opening balances taken over', c.opening || 0);
  return tr('{0} new, {1} updated', c.new || 0, c.updated || 0);
}
async function dimp_check(input) {
  const md = input.closest('.modal') || document, pv = $('#dimp-pv', md), ok = $('[data-m="ok"]', md);
  const f = input.files && input.files[0]; DIMP.file = f || null;
  if (ok) ok.disabled = true;
  if (!f || !pv) { if (pv) pv.innerHTML = ''; return; }
  pv.innerHTML = `<p class="muted">${tr('Loading…')}</p>`;
  const fd = new FormData(); fd.append('file', f);
  let j;
  try { j = await api('POST', '/api/office/datev/import/check', fd); } catch (x) { pv.innerHTML = `<p class="aerr" role="alert">${esc(x.message || tr('unknown'))}</p>`; DIMP.file = null; return; }
  pv.innerHTML = dimp_previewHtml(j);
  if (ok) ok.disabled = !dimp_any(j);
}
function dimp_any(j) {
  const c = j.counts || {};
  return j.category === 21 ? (c.opening || 0) > 0 : (c.new || 0) + (c.updated || 0) > 0;
}
function dimp_previewHtml(j) {
  const c = j.counts || {};
  const sum = j.category === 21
    ? [tr('{0} opening balances', c.opening || 0), c.replaced ? tr('{0} replace existing ones', c.replaced) : '', c.other ? tr('{0} other bookings not taken over', c.other) : '', c.skipped ? tr('{0} skipped', c.skipped) : '']
    : [tr('{0} new', c.new || 0), tr('{0} updated', c.updated || 0), tr('{0} skipped', c.skipped || 0)];
  const head = `<p class="dimpsum" data-dimp-kind="${esc(j.kind)}"><b>${esc(j.category === 21 ? tr('Booking batch') : tr('Debtors and creditors'))}</b> · ${esc(sum.filter(Boolean).join(' · '))}</p>`;
  const hints = (j.hints || []).map(h => `<p class="muted ofchint">${esc(h)}</p>`).join('');
  const rows = (j.rows || []).map(x => {
    const act = `<small class="rotag dimpact" data-act="${esc(x.action)}">${esc(tr(DIMP_ACT[x.action] || x.action))}</small>`;
    if (j.category === 21) {
      return `<li><span class="ofcn"><b>${esc(x.account)} · ${esc(x.label || '')}</b><small class="muted">${esc([x.year, x.reason].filter(Boolean).join(' · '))}</small></span>
        <span class="ofdsum"><b>${x.amount != null ? esc(ofcMoney(x.amount)) + ' ' + esc(x.side === 'H' ? tr('Credit|side') : tr('Debit|side')) : ''}</b>${act}</span></li>`;
    }
    const v = x.values || {}, fill = Object.keys(x.fill || {}), diff = Object.entries(x.differ || {});
    const info = [x.kind === 'creditor' ? tr('Supplier') : x.kind === 'debtor' ? tr('Client') : '', [v.zip, v.city].filter(Boolean).join(' '),
      fill.length ? tr('fills: {0}', fill.join(', ')) : '', ...diff.map(([k, d]) => tr('{0} stays "{1}" (file: "{2}")', k, d.now, d.file)), x.reason, ...(x.notes || [])].filter(Boolean);
    return `<li><span class="ofcn"><b>${esc(x.account)} · ${esc(v.name || x.current || '')}</b><small class="muted">${esc(info.join(' · '))}</small></span><span class="ofdsum">${act}</span></li>`;
  }).join('');
  const more = j.total > (j.rows || []).length ? `<p class="muted ofchint">${esc(tr('The first {0} of {1} rows', (j.rows || []).length, j.total))}</p>` : '';
  return head + hints + `<ul class="ofclist dimprows" role="list">${rows}</ul>` + more;
}

// ---- the opening balances of a year (bookkeeping)
async function dimp_obLoad(year) {
  try { DIMP.ob[year] = await api('GET', `/api/office/datev/opening?year=${year}`); } catch (x) { DIMP.ob[year] = {items: [], years: [], error: x.message || tr('unknown')}; }
  const box = $('#dimp-ob'); if (box) box.outerHTML = dimp_obHtml(year);
}
function dimp_obHtml(year) {
  if (typeof ofcAdmin !== 'function' || !ofcAdmin()) return '';
  if (DIMP.obOid !== OFC.info?.org_id) { DIMP.obOid = OFC.info?.org_id; DIMP.ob = {}; }
  const j = DIMP.ob[year];
  if (!j) { setTimeout(() => { if (!DIMP.ob[year]) dimp_obLoad(year); }, 0); return '<div id="dimp-ob"></div>'; }
  if (!(j.items || []).length) return '<div id="dimp-ob"></div>';  // nothing imported: the bookkeeping looks as before
  return `<section id="dimp-ob" class="dimpob" aria-labelledby="dimp-ob-h"><h3 id="dimp-ob-h">${esc(tr('Opening balances {0}', year))}</h3>
    <ul class="ofclist" role="list">${j.items.map(x => `<li><span class="ofcn"><b>${esc(x.account)}</b><small class="muted">${esc(x.label || '')}</small></span>
      <span class="ofdsum"><b>${esc(ofcMoney(x.amount))}</b><small class="muted">${esc(x.side === 'H' ? tr('Credit|side') : tr('Debit|side'))}</small></span></li>`).join('')}</ul>
    <p class="muted ofchint">${esc(tr('Debit {0} · Credit {1}', ofcMoney(j.debit), ofcMoney(j.credit)))} · ${esc(tr('From the DATEV import; Kalmido does not book them.'))}</p></section>`;
}

document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-dimp]'); if (!b) return;
  if (b.dataset.dimp === 'open') dimp_dialog();
  else if (b.dataset.dimp === 'del') dimp_delete(+b.dataset.id).catch(() => 0);
});
document.addEventListener('change', e => {
  const t = /** @type {any} */ (e.target);
  if (t.id === 'dimp-file') dimp_check(t);
  else if (t.dataset?.dimpName) dimp_rename(t);
});
