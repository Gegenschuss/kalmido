// @ts-check
/* Kalmido web client: Office & finance, the balance sheet with double-entry bookkeeping (2.666.0, #3461; server:
   office/ledger_dbl.py). ldbHtml() = the page #office/books/ledger of the bookkeeping (office_books.js bkTabHtml, a button in
   its bar while the profit determination is "balance sheet"): the balance sheet, the profit and loss account, the trial
   balance (each as CSV), the entries by hand (adjusting and opening entries: a small form) and the year-end closing (a dialog,
   no way back). ldb_setHtml() = the choice "income statement / balance sheet" and the size in Settings > Company & office >
   Bank & taxes (office.js ost_taxHtml). Admins only (as the income statement).
   Classic script sharing the global scope with the others (load order: lazyload.js, module "office"). */
'use strict';

const LDB = /** @type {any} */ ({oid: null, cfg: null, cfgLoading: false, year: new Date().getFullYear() - 1, d: null, err: null, seq: 0, susa: false, loading: false});

const ldbMoney = v => ofcMoney(+v || 0);
const ldbBase = () => '/api/office/books/ledger';

async function ldbCfgLoad() {
  LDB.cfgLoading = true;
  try { LDB.cfg = await api('GET', `${ldbBase()}/settings`); } catch (x) { LDB.cfg = {error: x.message || tr('unknown')}; }
  LDB.cfgLoading = false;
  const box = $('#ldb-set'); if (box) box.outerHTML = ldb_setHtml();
}

// Settings > Company & office > Bank & taxes: the profit determination and the size of the balance sheet
function ldb_setHtml() {
  if (typeof ofcAdmin !== 'function' || !ofcAdmin()) return '';
  if (LDB.oid !== OFC.info?.org_id) Object.assign(LDB, {oid: OFC.info?.org_id, cfg: null, d: null, err: null});
  const head = `<h3 id="ldb-seth">${tr('Profit determination')}</h3>`;
  if (!LDB.cfg) { if (!LDB.cfgLoading) setTimeout(ldbCfgLoad, 0); return `<section id="ldb-set" class="ldbset">${head}</section>`; }
  if (LDB.cfg.error) return `<section id="ldb-set" class="ldbset">${head}<p class="muted">${esc(LDB.cfg.error)}</p></section>`;
  const c = LDB.cfg;
  const sug = c.suggest === 'balance' && c.method !== 'balance' ? `<p class="bk-warn" data-ldb-suggest>${esc(tr('A corporation (e.g. GmbH, UG) draws up a balance sheet, no income/expense statement.'))}</p>` : '';
  return `<section id="ldb-set" class="ldbset" aria-labelledby="ldb-seth">${head}
    ${ofcRowF('ldb-method', tr('Profit determination'), ofcSel('ldb-method', c.method, [['euer', tr('Income/expense statement (EÜR)')], ['balance', tr('Balance sheet (double-entry bookkeeping)')]]),
      tr('The balance sheet books the invoices, receipts, payments, bank, cash book and depreciation in debit and credit on the accounts of the chart {0} (as the DATEV export).', c.chart))}
    ${c.method === 'balance' ? ofcRowF('ldb-size', tr('Size of the company'), ofcSel('ldb-size', c.size, [['small', tr('Small (section 267 HGB)')], ['micro', tr('Micro (section 267a HGB)')]]), tr('Decides how detailed the balance sheet and the profit and loss account are.')) : ''}
    ${sug}</section>`;
}

async function ldbCfgSet(k, v) {
  try { LDB.cfg = await api('PUT', `${ldbBase()}/settings`, {[k]: v}); LDB.d = null; if (typeof BK === 'object' && BK.info) BK.info.ledger = LDB.cfg.method; toast(tr('Saved')); }
  catch (x) { toast(x.message || tr('unknown')); }
  const box = $('#ldb-set'); if (box) box.outerHTML = ldb_setHtml();
}

async function ldbLoad() {
  const seq = ++LDB.seq;
  try {
    const d = await api('GET', `${ldbBase()}?year=${LDB.year}`);
    if (seq !== LDB.seq) return;
    Object.assign(LDB, {d, err: null, cfg: d.settings});
  } catch (x) { if (seq === LDB.seq) { LDB.err = x.message || tr('unknown'); LDB.d = null; } }
  LDB.loading = false;
  ofcDraw();
}
const ldbReload = () => { LDB.d = null; LDB.err = null; ofcDraw(); };

// the page #office/books/ledger
function ldbHtml() {
  if (LDB.oid !== OFC.info?.org_id) Object.assign(LDB, {oid: OFC.info?.org_id, cfg: null, d: null, err: null});
  const back = `<a class="btn sm ghost" href="#office/books">${ic('back', 's')}<span>${tr('Bookkeeping')}</span></a>`;
  const years = ofcYearOpts(typeof BK === 'object' ? BK.info?.years : null, LDB.year, 1).map(y => [y, y]);
  const bar = `<div class="ofcbar bk-bar">${back}<h3 class="ofcgrp">${tr('Balance sheet')}</h3><span class="spacer"></span><label class="bk-year"><span class="muted">${tr('Year')}</span>${ofcSel('ldb-year', LDB.year, years)}</label></div>`;
  if (LDB.err) return bar + `<div class="empty">${esc(LDB.err)}</div>`;
  if (!LDB.d || LDB.d.year !== LDB.year) { if (!LDB.loading) { LDB.loading = true; setTimeout(ldbLoad, 0); } return bar + `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = LDB.d;
  if (d.settings?.method !== 'balance') return bar + `<div class="empty">${esc(tr('Switch the profit determination to the balance sheet first.'))} ${ofcSetLink('tax', tr('Profit determination'))}</div>`;
  const ok = d.checks.balanced && +d.checks.difference === 0;
  const state = `<p class="${ok ? 'muted ofchint' : 'bk-warn'}" data-ldb-check="${ok ? 'ok' : 'off'}">${esc(ok ? tr('Debit = credit, assets = equity and liabilities.') : tr('The balance sheet does not balance (difference {0}).', ldbMoney(d.checks.difference)))}${d.closed ? ` <b>${esc(tr('The year {0} is closed.', d.year))}</b>` : ''}</p>`;
  const hints = (d.hints || []).map(h => `<p class="bk-warn" data-ldb-hint="${esc(h.key || '')}">${esc(h.text)}</p>`).join('');
  return bar + state + hints + ldbBsHtml(d) + ldbPlHtml(d) + ldbSusaHtml(d) + ldbEntriesHtml(d) + ldbCloseHtml(d) + `<p class="muted bk-note">${esc(d.note)}</p>`;
}

const ldbCsv = (what, y) => `<a class="btn sm ghost" href="${ldbBase()}/${what}.csv?year=${y}" download>${ic('download', 's')}<span>CSV</span></a>`;

function ldbBsHtml(d) {
  const side = s => {
    const rows = d.bs.filter(r => r.side === s).map(r => `<tr${r.level ? '' : ' class="bk-tot"'}><th scope="row">${r.level ? '&nbsp;&nbsp;' : ''}${esc(r.label)}</th><td class="num">${ldbMoney(r.amount)}</td></tr>`).join('');
    const tot = s === 'a' ? d.checks.assets : d.checks.liabilities;
    return `<h4 class="bk-h">${esc(s === 'a' ? tr('Assets') : tr('Equity and liabilities'))}</h4><table class="bk-tab ldb-bs" data-ldb-side="${s}"><thead><tr><th>${esc(s === 'a' ? tr('Assets') : tr('Equity and liabilities'))}</th><th class="num">${tr('Amount')}</th></tr></thead><tbody>${rows}
      <tr class="bk-tot"><th scope="row">${tr('Total')}</th><td class="num" data-ldb-total="${s}">${ldbMoney(tot)}</td></tr></tbody></table>`;
  };
  return `<section class="bk-sec" aria-labelledby="ldb-bsh"><div class="ofcbar"><h3 class="ofcgrp" id="ldb-bsh">${tr('Balance sheet as of {0}', fmtDay('year', pd(`${d.year}-12-31`)))}</h3><span class="spacer"></span>${ldbCsv('bs', d.year)}</div>
    ${side('a')}${side('p')}</section>`;
}

function ldbPlHtml(d) {
  const rows = d.pl.filter(r => +r.amount).map(r => `<tr><th scope="row">${esc(r.label)}</th><td class="num">${r.kind === 'e' ? '- ' : ''}${ldbMoney(r.amount)}</td></tr>`).join('')
    || `<tr><td colspan="2" class="muted">${tr('None')}</td></tr>`;
  return `<section class="bk-sec" aria-labelledby="ldb-plh"><div class="ofcbar"><h3 class="ofcgrp" id="ldb-plh">${tr('Profit and loss account {0}', d.year)}</h3><span class="spacer"></span>${ldbCsv('pl', d.year)}</div>
    <table class="bk-tab ldb-pl"><tbody>${rows}</tbody></table>
    <div class="bk-profit"><span>${tr('Net income / net loss for the year')}</span><b class="${+d.result < 0 ? 'neg' : ''}" data-ldb-result>${ldbMoney(d.result)}</b></div></section>`;
}

function ldbSusaHtml(d) {
  const head = `<div class="ofcbar"><h3 class="ofcgrp" id="ldb-ssh">${tr('Trial balance {0}', d.year)}</h3><span class="spacer"></span>
    <button type="button" class="btn sm ghost" data-ldb="susa" aria-expanded="${LDB.susa}">${esc(LDB.susa ? tr('Hide') : tr('Show'))}</button>${ldbCsv('susa', d.year)}${ldbCsv('journal', d.year)}</div>`;
  if (!LDB.susa) return `<section class="bk-sec" aria-labelledby="ldb-ssh">${head}</section>`;
  const th = `<thead><tr><th>${tr('Account')}</th><th class="num">${tr('Opening balance')}</th><th class="num">${tr('Debit')}</th><th class="num">${tr('Credit')}</th><th class="num">${tr('Balance')}</th></tr></thead>`;
  const rows = d.susa.map(r => `<tr><th scope="row">${esc(r.account)} <small class="muted">${esc(r.label)}</small></th><td class="num">${ldbMoney(r.open)}</td><td class="num">${ldbMoney(r.debit)}</td><td class="num">${ldbMoney(r.credit)}</td><td class="num">${ldbMoney(r.balance)}</td></tr>`).join('');
  return `<section class="bk-sec" aria-labelledby="ldb-ssh">${head}<table class="bk-tab ldb-susa">${th}<tbody>${rows}
    <tr class="bk-tot"><th scope="row">${tr('Total')}</th><td></td><td class="num">${ldbMoney(d.checks.debit)}</td><td class="num">${ldbMoney(d.checks.credit)}</td><td></td></tr></tbody></table></section>`;
}

function ldbEntriesHtml(d) {
  const rows = d.entries.map(e => `<li class="ofcrow" data-ldb-entry="${e.id}"><span class="ofcn"><b>${esc(e.text || (e.kind === 'open' ? tr('Opening entry') : tr('Adjusting entry')))}</b>
    <small class="muted">${esc([fmtDateLoc(e.day), `${tr('Debit')} ${e.debit}`, `${tr('Credit')} ${e.credit}`, e.kind === 'open' ? tr('Opening entry') : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="rksum">${ldbMoney(e.amount)}</span>${d.closed || e.ref ? '' : `<button type="button" class="btn sm ghost" data-ldb="del" data-id="${e.id}" aria-label="${esc(tr('Delete'))}">${ic('trash', 's')}</button>`}</li>`).join('');
  return `<section class="bk-sec" aria-labelledby="ldb-enh"><div class="ofcbar"><h3 class="ofcgrp" id="ldb-enh">${tr('Entries by hand')}</h3><span class="spacer"></span>
    ${d.closed ? '' : `<button type="button" class="btn sm" data-ldb="add">${ic('plus', 's')}<span>${tr('New entry')}</span></button>`}</div>
    <p class="muted ofchint">${esc(tr('Accruals, provisions and corrections as an adjusting entry; the opening balances of the first year as opening entries against account {0}.', d.susa.find(r => r.class === 'open')?.account || '9000'))}</p>
    ${rows ? `<ul class="ofclist" role="list">${rows}</ul>` : `<p class="muted">${tr('None')}</p>`}</section>`;
}

function ldbCloseHtml(d) {
  if (d.closed || d.year >= new Date().getFullYear()) return '';
  return `<section class="bk-sec" aria-labelledby="ldb-clh"><div class="ofcbar"><h3 class="ofcgrp" id="ldb-clh">${tr('Year-end closing {0}', d.year)}</h3><span class="spacer"></span>
    <button type="button" class="btn sm" data-ldb="close">${ic('lock', 's')}<span>${tr('Close year…')}</span></button></div>
    <p class="muted ofchint">${esc(tr('Carries the balances into {0}, the result onto the profit / loss carried forward, and locks every month of {1} (GoBD).', d.year + 1, d.year))}</p></section>`;
}

function ldbEntryDialog() {
  const y = LDB.year;
  ofdDlg(tr('New entry'), `<div class="row"><label for="ldb-ekind">${tr('Kind')}</label>${ofcSel('ldb-ekind', 'manual', [['manual', tr('Adjusting entry')], ['open', tr('Opening entry')]])}</div>
    <div class="row"><label id="ldb-edl">${tr('Date')}</label>${dateIn('ldb-eday', `${y}-12-31`, {label: tr('Date'), clear: false})}</div>
    ${ofcRowF('ldb-edebit', tr('Debit account'), `<input id="ldb-edebit" inputmode="numeric" autocomplete="off" maxlength="9">`)}
    ${ofcRowF('ldb-ecredit', tr('Credit account'), `<input id="ldb-ecredit" inputmode="numeric" autocomplete="off" maxlength="9">`)}
    ${ofcRowF('ldb-eamt', tr('Amount'), `<input id="ldb-eamt" inputmode="decimal" class="numin" autocomplete="off">`)}
    ${ofcRowF('ldb-etext', tr('Text'), `<input id="ldb-etext" maxlength="200" autocomplete="off">`)}`,
  tr('Save'), async m => {
    const v = id => /** @type {HTMLInputElement} */ ($('#' + id, m)).value.trim();
    const n = ofcNum(v('ldb-eamt'));
    if (n == null || n <= 0) throw new Error(tr('Invalid value: {0}', tr('Amount')));
    await api('POST', `${ldbBase()}/entries`, {kind: v('ldb-ekind'), day: v('ldb-eday'), debit: v('ldb-edebit'), credit: v('ldb-ecredit'), amount: n.toFixed(2), text: v('ldb-etext')});
    toast(tr('Saved')); ldbReload();
  });
}

async function ldbEntryDelete(id) {
  const e = LDB.d?.entries.find(x => x.id === id); if (!e) return;
  if (!await askConfirm(tr('Delete this entry?'), '', {ok: tr('Delete')})) return;
  try { await api('DELETE', `${ldbBase()}/entries/${id}?expect_updated_at=${encodeURIComponent(e.updated_at)}`); toast(tr('Deleted')); ldbReload(); }
  catch (x) { toast(x.message || tr('unknown')); }
}

function ldbCloseDialog() {
  const d = LDB.d, y = String(d.year);
  ofdDlg(tr('Close the year {0}', y), `<p>${esc(tr('The balances of {0} become the opening entries of {1}, the result ({2}) goes onto the profit / loss carried forward and every month of {0} is locked permanently. This cannot be undone.', y, d.year + 1, ldbMoney(d.result)))}</p>
    <div class="row"><label for="ldb-confirm">${esc(tr('Type {0} to confirm', y))}</label><input id="ldb-confirm" autocomplete="off" inputmode="numeric" placeholder="${esc(y)}"></div>`,
  tr('Close permanently'), async m => {
    if (/** @type {HTMLInputElement} */ ($('#ldb-confirm', m)).value.trim() !== y) throw new Error(tr('Please type {0} to confirm', y));
    const j = await api('POST', `${ldbBase()}/close`, {year: d.year});
    toast(tr('The year {0} is closed.', j.year)); ldbReload();
  });
}

// one-meaning guard: data-ldb carries only these string actions
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-ldb]'); if (!b) return;
  const a = b.dataset.ldb;
  if (a === 'susa') { LDB.susa = !LDB.susa; ofcDraw(); }
  else if (a === 'add') ldbEntryDialog();
  else if (a === 'del') ldbEntryDelete(+b.dataset.id);
  else if (a === 'close') ldbCloseDialog();
});
document.addEventListener('change', e => {
  const x = /** @type {any} */ (e.target);
  if (x.id === 'ldb-year') { LDB.year = +x.value; LDB.d = null; ofcDraw(); }
  else if (x.id === 'ldb-method') ldbCfgSet('method', x.value);
  else if (x.id === 'ldb-size') ldbCfgSet('size', x.value);
});
