// @ts-check
/* Kalmido web client: Office & finance, locking accounting periods + the export for the tax auditor (2.148.0 A, #2471;
   server: office/periodlock.py, office/gobdexport.py). plSectionHtml() = the section "Lock periods (GoBD)" of the
   bookkeeping (office_books.js bkTabHtml): the months of the year with their lock, "Lock up to ..." (a dialog that explains
   there is no way back and asks to type the month) and the auditor's ZIP (index.xml + CSV) for a period. Admins only.
   Classic script sharing the global scope with the others (load order: lazyload.js, module "office"). */
'use strict';

const PLK = /** @type {any} */ ({data: null, oid: null, loading: false});  // not PL: paperless.js has a global PL

const plLabel = m => `${m.slice(5, 7)}/${m.slice(0, 4)}`;
const plAdd = (m, n) => { const d = new Date(+m.slice(0, 4), +m.slice(5, 7) - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; };

async function plLoad() {
  PLK.loading = true;
  try { PLK.data = await api('GET', '/api/office/periods'); } catch (x) { PLK.data = {error: x.message || tr('unknown'), months: []}; }
  PLK.loading = false;
  const box = $('#pl-sec'); if (box) box.outerHTML = plSectionHtml();
}

function plSectionHtml() {
  if (typeof ofcAdmin !== 'function' || !ofcAdmin()) return '';
  if (PLK.oid !== OFC.info?.org_id) { PLK.oid = OFC.info?.org_id; PLK.data = null; }
  if (!PLK.data) { if (!PLK.loading) setTimeout(plLoad, 0); return '<section id="pl-sec" class="plsec"></section>'; }
  const d = PLK.data, y = String(BK.year || new Date().getFullYear()), cur = d.current || '';
  if (d.error) return `<section id="pl-sec" class="plsec"><p class="muted">${esc(d.error)}</p></section>`;
  const months = [];
  for (let i = 1; i <= 12; i++) {
    const m = `${y}-${String(i).padStart(2, '0')}`, on = !!d.through && m <= d.through;
    months.push(`<li class="plm${on ? ' on' : ''}${m >= cur ? ' open' : ''}" title="${esc(on ? tr('Locked') : tr('Open'))}">${on ? ic('lock', 's') : ''}<span>${esc(plMonthShort(m))}</span></li>`);
  }
  const opts = [];  // the finished months after the last locked one, newest first
  const start = d.through ? plAdd(d.through, 1) : (d.first || plAdd(cur, -1));
  for (let m = plAdd(cur, -1); m >= start && opts.length < 36; m = plAdd(m, -1)) opts.push([m, plLabel(m)]);
  const state = d.through ? tr('Locked up to and including {0}.', plLabel(d.through)) : tr('Nothing is locked yet.');
  return `<section id="pl-sec" class="plsec" aria-labelledby="pl-h"><h3 id="pl-h">${tr('Lock periods (GoBD)')}</h3>
    <p class="muted ofchint">${esc(state)} ${tr('A locked month cannot be changed any more; corrections go into an open month.')}</p>
    <ul class="plmonths" role="list">${months.join('')}</ul>
    <div class="lacts">${opts.length ? `<label class="plpick"><span class="muted">${tr('Lock up to')}</span>${ofcSel('pl-to', opts[0][0], opts)}</label>
      <button type="button" class="btn sm" data-pl="lock">${ic('lock', 's')}<span>${tr('Lock…')}</span></button>` : ''}
      <button type="button" class="btn sm ghost" data-pl="export">${ic('download', 's')}<span>${tr('Export for the tax auditor')}</span></button></div></section>`;
}

async function plLockDialog() {
  const to = /** @type {HTMLSelectElement|null} */ ($('#pl-to'))?.value; if (!to) return;
  let hints = [];
  try { hints = (await api('GET', `/api/office/periods?check=${to}`)).hints || []; } catch (x) { toast(x.message || tr('unknown')); return; }
  const lab = plLabel(to);
  ofdDlg(tr('Lock up to {0}', lab), `<p>${esc(tr('All open months up to and including {0} are locked for good. Invoices, payments, bank matches, receipts, cash entries and trips of these months can then no longer be changed or deleted. This cannot be undone.', lab))}</p>
    ${hints.length ? `<ul class="plhints">${hints.map(h => `<li>${esc(h.text)}</li>`).join('')}</ul>` : ''}
    <div class="row"><label for="pl-confirm">${esc(tr('Type {0} to confirm', lab))}</label><input id="pl-confirm" autocomplete="off" inputmode="numeric" placeholder="${esc(lab)}"></div>`,
  tr('Lock for good'), async m => {
    const v = /** @type {HTMLInputElement} */ ($('#pl-confirm', m)).value.trim();
    if (v !== lab) throw new Error(tr('Please type {0} to confirm', lab));
    const j = await api('POST', '/api/office/periods/lock', {through: to, confirm: v});
    PLK.data = null; plLoad();
    toast(j.locked?.length === 1 ? tr('1 month locked') : tr('{0} months locked', j.locked?.length || 0));
  });
}

function plExportDialog() {
  const y = (BK.year && BK.year < new Date().getFullYear() ? BK.year : new Date().getFullYear() - 1);
  ofdDlg(tr('Export for the tax auditor'), `<p class="muted ofchint">${tr('A ZIP with the bookings, invoices, payments, receipts, cash book, clients and the log of the period as CSV tables, described in index.xml (GDPdU description standard) for the auditing software.')}</p>
    <div class="row"><label id="pl-fl">${tr('From')}</label>${dateIn('pl-from', `${y}-01-01`, {label: tr('From'), clear: false})}</div>
    <div class="row"><label id="pl-tl">${tr('To')}</label>${dateIn('pl-tot', `${y}-12-31`, {label: tr('To'), clear: false, after: 'pl-from'})}</div>`,
  tr('Download'), async m => {
    const q = `from=${encodeURIComponent($('#pl-from', m).value)}&to=${encodeURIComponent($('#pl-tot', m).value)}`;
    await api('GET', `/api/office/gobd/export?${q}&check=1`);  // a wrong period answers as text before the download
    const a = document.createElement('a'); a.href = `/api/office/gobd/export?${q}`; a.download = ''; document.body.appendChild(a); a.click(); a.remove();
  });
}

const plMonthShort = m => { try { return new Date(+m.slice(0, 4), +m.slice(5, 7) - 1, 1).toLocaleDateString(LOCALE(), {month: 'short'}); } catch { return m.slice(5, 7); } };

document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-pl]'); if (!b) return;
  if (b.dataset.pl === 'lock') plLockDialog();
  else if (b.dataset.pl === 'export') plExportDialog();
});
