// 2.50.0 (#1197, part B): the business figures at a glance (tab "Figures" in the office, admins of the office area only):
// revenue received this month and this year against the year before (a small bar per month, this year in the accent, the
// year before faint), open and overdue invoices (a tap opens the invoice list filtered), the pipeline's weighted value,
// the cash flow of the next three months (from the cash flow tab, not computed twice) and per client hours against budget,
// invoiced, costs and margin. The server computes everything (GET /api/office/kpi); this only shows it.
const KPS = {data: null, err: null, oid: null, year: 0, q: ''};
OFC_TABS.splice(Math.max(0, OFC_TABS.findIndex(t => t[0] === 'cashflow' || t[0] === 'settings')), 0, ['kpi', 'chart', N_('Figures'), 1, () => kp_html(), 'money', 'money.kpi']);  // admins only; 2.380 F (#3411): [6] the switch

async function kp_load() {
  const q = KPS.year ? `?year=${KPS.year}` : ''; KPS.q = q;
  try { const j = await api('GET', '/api/office/kpi' + q); if (KPS.q === q) { KPS.data = j; KPS.err = null; } }
  catch (x) { KPS.err = x.message || tr('unknown'); }
  ofcDraw();
}
const kp_delta = (a, b) => {
  a = +a; b = +b;
  if (!b) return '';
  const p = Math.round((a - b) / Math.abs(b) * 100);
  return `<span class="kpdelta ${p < 0 ? 'neg' : ''}">${p > 0 ? '+' : ''}${p} %</span>`;
};
const kp_mon = ym => { const [y, m] = ym.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString(LOCALE(), {month: 'short'}); };

function kp_html() {
  if (KPS.oid !== OFC.info?.org_id) Object.assign(KPS, {oid: OFC.info?.org_id, data: null, err: null});  // another office area
  if (!ofcAdmin()) return ofcLockedHtml();  // 2.356.0 D (#3006): why, and the way to hand in receipts
  if (KPS.err) return `<div class="empty">${esc(KPS.err)}</div>`;
  if (!KPS.data || KPS.q !== (KPS.year ? `?year=${KPS.year}` : '')) { setTimeout(() => { if (!KPS.data || KPS.q !== (KPS.year ? `?year=${KPS.year}` : '')) kp_load(); }, 0); if (!KPS.data) return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = KPS.data, r = d.revenue, y = d.year, thisY = +String(d.today).slice(0, 4);
  const bar = `<div class="ofcbar"><button class="iconbtn" data-kp="prev" aria-label="${esc(tr('Earlier'))}" title="${esc(tr('Earlier'))}">${ic('left', 's')}</button><b>${y}</b>${y < thisY ? `<button class="iconbtn" data-kp="next" aria-label="${esc(tr('Later'))}" title="${esc(tr('Later'))}">${ic('right', 's')}</button><button class="btn sm ghost" data-kp="now">${tr('This year')}</button>` : ''}</div>`;
  const tile = (label, val, sub = '', go = '', extra = '') => `<${go ? `button type="button" data-kp="go" data-go="${go}"` : 'div'} class="kptile ${extra}"><small class="muted">${esc(label)}</small><b>${val}</b>${sub ? `<small class="muted">${sub}</small>` : ''}</${go ? 'button' : 'div'}>`;
  const ym = r.month_key;
  // 2.298.0 A2 (#3186): the revenue tiles say net / received, the weighted pipeline its formula, the cash flow tile that
  // expected payments count (its balance is actual + planned, kalmido/office/cashflow.py)
  const nr = esc(tr('net, received'));
  const tiles = `<div class="kptiles">
    ${tile(r.to_date ? tr('Revenue this month') : tr('Revenue in December'), ofcMoney(r.month), `${nr} · ${tr('a year earlier: {0}', ofcMoney(r.month_prev))} ${kp_delta(r.month, r.month_prev)}`)}
    ${tile(r.to_date ? tr('Revenue this year so far') : tr('Revenue {0}', y), ofcMoney(r.year), `${nr} · ${tr('a year earlier: {0}', ofcMoney(r.year_prev))} ${kp_delta(r.year, r.year_prev)}`)}
    ${tile(tr('Open items'), ofcMoney(d.invoices.open.amount), esc(`${trn('{0} invoice', '{0} invoices', d.invoices.open.count)} · ${tr('open and overdue')}`), 'open')}${/* 2.356.0 D (#3007): the accountant's word */ ''}
    ${tile(tr('Overdue|invoices'), ofcMoney(d.invoices.overdue.amount), esc(trn('{0} invoice', '{0} invoices', d.invoices.overdue.count)), 'overdue', +d.invoices.overdue.count ? 'warn' : '')}
    ${tile(tr('Pipeline, weighted'), ofcMoney(d.pipeline.weighted), esc(`${tr('value × probability')} · ${tr('{0} open', ofcMoney(d.pipeline.open))}`), 'pipeline')}
    ${tile(tr('Cash flow, next 3 months'), ofcMoney(d.cashflow.reduce((a, x) => a + +x.balance, 0)), esc(tr('Balance incl. expected payments')), 'cashflow')}</div>`;
  // revenue per month: two series (this year / the year before), one accent; legend + values on tap and in a table for screen readers
  const max = Math.max(1, ...r.months.flatMap(m => [+m.amount, +m.prev]));
  const h = v => Math.max(0, +v) / max;
  const chart = `<section class="kpchart" aria-labelledby="kp-rev"><div class="ofcbar"><h3 class="ofcgrp" id="kp-rev">${tr('Revenue per month (net, received)')}</h3><span class="spacer"></span>
    <span class="kplegend" aria-hidden="true"><span><i class="kpcur"></i>${y}</span><span><i class="kpprev"></i>${y - 1}</span></span></div>
    ${max <= 1 ? `<p class="muted ofchint">${tr('No payments received in {0} and {1} yet.', y, y - 1)}</p>` : ''}<div class="kpbars" aria-hidden="true">${r.months.map(m => `<button type="button" class="kpm ${m.month === ym ? 'cur' : ''}" tabindex="-1" title="${esc(`${kp_mon(m.month)} ${y}: ${ofcMoney(m.amount)} · ${y - 1}: ${ofcMoney(m.prev)}`)}" data-kp="tip" data-t="${esc(`${kp_mon(m.month)}: ${ofcMoney(m.amount)} (${y - 1}: ${ofcMoney(m.prev)})`)}">
      <span class="kpb"><i class="kpprev" style="transform:scaleY(${h(m.prev).toFixed(3)})"></i><i class="kpcur" style="transform:scaleY(${h(m.amount).toFixed(3)})"></i></span><small>${esc(kp_mon(m.month))}</small></button>`).join('')}</div>
    <table class="sr"><caption>${tr('Revenue per month (net, received)')}</caption><thead><tr><th>${tr('Month')}</th><th>${y}</th><th>${y - 1}</th></tr></thead><tbody>${r.months.map(m => `<tr><th>${esc(kp_mon(m.month))}</th><td>${ofcMoney(m.amount)}</td><td>${ofcMoney(m.prev)}</td></tr>`).join('')}</tbody></table></section>`;
  const pct = (p, lvl) => p == null ? '' : `<span class="kpbud" aria-hidden="true"><i class="${lvl}" style="transform:scaleX(${Math.min(1, p / 100).toFixed(3)})"></i></span><small class="kppct ${lvl}">${p} %</small>`;
  const hrs = (v, b) => b ? tr('{0} of {1} h', fmtNum(v, 1), fmtNum(b, 1)) : tr('{0} h', fmtNum(v, 1));
  const cl = d.clients.length ? `<ul class="ofclist kpcl" role="list">${d.clients.map(c => {
    const lvl = c.level === 'over' ? 'over' : c.level === 'warn' ? 'warn' : '';
    return `<li class="kpclient"><div class="kpch"><b>${esc(cdn_label(c))}</b><span class="spacer"></span><span class="rksum">${tr('Margin')} ${ofcMoney(c.margin)}${c.margin_pct != null ? ` <small class="muted">(${c.margin_pct} %)</small>` : ''}</span></div>
      <div class="kprow"><span class="muted">${tr('Hours')}</span><span>${hrs(c.hours, c.budget_h)}</span>${pct(c.pct_h, lvl)}</div>
      ${c.budget_amount ? `<div class="kprow"><span class="muted">${tr('Budget')}</span><span>${tr('{0} of {1}', ofcMoney(c.amount), ofcMoney(c.budget_amount))}</span>${pct(c.pct_amount, lvl)}</div>` : ''}
      <div class="kprow"><span class="muted">${tr('Invoiced {0}', y)}</span><span class="rksum">${ofcMoney(c.invoiced)}</span><span class="muted">${tr('Costs')} ${ofcMoney(c.costs)}</span></div>
      ${c.projects.map(p => `<div class="kprow kpproj"><a href="#l/${p.id}">${ic('brief', 's')}<span>${esc(p.name)}</span></a><span>${hrs(p.hours, p.budget_h)}</span>${pct(p.pct_h, p.pct_h >= 100 ? 'over' : p.pct_h >= 80 ? 'warn' : '')}</div>`).join('')}</li>`;
  }).join('')}</ul>` : `<p class="muted lempty">${tr('No client with hours, a budget or invoices yet.')}</p>`;
  // 2.298.0 A2 (#3186): the margin formula behind the (i) of the heading, only the revenue rule stays visible
  return bar + tiles + chart + `<h3 class="ofcgrp">${tr('Clients: budget and margin')}</h3><div class="shint">${tr('Margin = invoiced (net) minus purchases of accepted quotations and travel expenses of the client. Hours as you see them in the projects.')}</div>` + cl
    + `<p class="muted ofchint">${tr('Revenue = payments received on invoices, net.')}</p>`;
}

// the start page block "Figures" (dashboard.js): only for the admins of the office (a 403 hides it), loaded once per visit
const KPT = {data: undefined, loading: false, at: 0};
function kp_tile(card) {
  if (typeof ofcFeat === 'function' && !ofcFeat('money.kpi')) return '';  // 2.380 F (#3411): Figures switched off
  if (KPT.data === undefined || (KPT.data && Date.now() - KPT.at > 60000 && !KPT.loading)) {  // fresh after a minute
    if (!KPT.loading) {
      KPT.loading = true;
      rawFetch('GET', '/api/office/kpi').then(j => { KPT.data = j; KPT.at = Date.now(); }, () => { KPT.data = null; }).finally(() => { KPT.loading = false; if (S.route.mod === 'home') renderView(); else if (S.route.mod === 'office' && ofcTab() === 'start') ofcDraw(); });  // 2.87.9 (#1917): the office start page
    }
    if (KPT.data === undefined) return '';
  }
  const d = KPT.data;
  if (!d) return '';
  const row = (label, v, extra = '') => `<li><span class="muted">${esc(label)}</span><span class="spacer"></span><b class="rksum ${extra}">${v}</b></li>`;
  const on = n => lyo_get('home', 'kpi', n, true);  // 2.55.0 (#1065): which figures (the block's settings, lyopts.js)
  return card(`<ul class="kptl" role="list">${on('rev') ? row(tr('Revenue this month'), ofcMoney(d.revenue.month)) : ''}${on('open') ? row(tr('Open items'), ofcMoney(d.invoices.open.amount)) : ''}
    ${on('over') && +d.invoices.overdue.count ? row(tr('Overdue|invoices'), ofcMoney(d.invoices.overdue.amount), 'neg') : ''}${on('pipe') ? row(tr('Pipeline, weighted'), ofcMoney(d.pipeline.weighted)) : ''}</ul>
    <a class="linkbtn" href="#office/kpi">${tr('All figures')}</a>`);
}

// 2.356.0 D (#3007): the invoice list filtered to the open items (status open = open and overdue, office/docs.py) or the
// overdue ones -- the figure "Open items" and the palette ("Open items", "OP")
function kp_openItems(st = 'open') {
  if (typeof OFD === 'object') { OFD.kind = 'invoice'; OFD.status = st; OFD.list = null; OFD.doc = null; OFD.docId = null; }
  go('office/invoices');  // 2.380.0 B (#3409)
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-kp]'); if (!b) return;
  const a = b.dataset.kp, cur = KPS.data ? +String(KPS.data.today).slice(0, 4) : new Date().getFullYear();
  if (a === 'prev' || a === 'next') { KPS.year = (KPS.year || cur) + (a === 'prev' ? -1 : 1); if (KPS.year >= cur) KPS.year = 0; ofcDraw(); }
  else if (a === 'now') { KPS.year = 0; ofcDraw(); }
  else if (a === 'tip') toast(b.dataset.t);
  else if (a === 'go') {
    const g = b.dataset.go;
    if (g === 'open' || g === 'overdue') kp_openItems(g);  // the invoice list, the open items / overdue ones filtered
    else go('office/' + g);
  }
  else return;
  e.preventDefault();
});
