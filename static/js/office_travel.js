// 2.47.3 (#1022, part B): travel expenses in the office (tab "Travel expenses", admins of the office area only). Trips with
// their receipts (Kalmido keeps no receipt images: they live in DATEV, only the tick "in DATEV" + an optional DATEV number),
// the receipts still missing the tick, an evaluation by month / year / person / project / client / category (CSV) and billing
// receipts on to a draft quotation / invoice (purchase = amount, never twice). Server: kalmido/office/travel.py.
const RK = {data: null, loading: false, err: null, year: String(new Date().getFullYear()), filter: 'all', open: null, view: 'trips', by: 'month', rep: null, sel: new Set()};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['travel', 'plane', N_('Travel expenses'), 1, () => rk_travelHtml()]);  // admins only
const RK_BY = [['month', N_('Month')], ['year', N_('Year')], ['person', N_('Person')], ['project', N_('Project')], ['client', N_('Client')], ['category', N_('Category')]];
const rk_reload = () => { RK.data = null; RK.rep = null; ofcDraw(); };
const rk_cat = k => (RK.data?.categories || []).find(c => c.key === k)?.label || k;
const rk_home = () => RK.data?.currency || ofcCur();
const rk_amt = (n, cur) => !cur || cur === rk_home() ? ofcMoney(n) : `${fmtNum(+n, 2)} ${esc(cur)}`;
const rk_trip = id => (RK.data?.trips || []).find(t => t.id === id);
const rk_span = t => t.date_to && t.date_to !== t.date_from ? `${fmtDateLoc(t.date_from)} – ${fmtDateLoc(t.date_to)}` : fmtDateLoc(t.date_from);
const rk_client = id => (RK.data?.clients || []).find(c => c.id === id)?.name || '';
const rk_purpose = t => [t.purpose === 'acquisition' ? tr('Acquisition / research') : '', rk_client(t.client_id), t.project].filter(Boolean).join(' · ');

async function rk_load() {
  if (RK.loading) return;
  RK.loading = true;
  try { RK.data = await api('GET', '/api/office/trips' + (RK.year ? `?year=${RK.year}` : '')); RK.err = null; }
  catch (x) { RK.data = null; RK.err = x.message || tr('unknown'); }
  RK.loading = false;
  ofcDraw();
}
async function rk_loadReport() {
  const y = RK.year, q = `by=${RK.by}` + (y ? `&from=${y}-01-01&to=${y}-12-31` : '') + (RK.filter === 'missing' ? '&missing=1' : '');
  try { RK.rep = Object.assign(await api('GET', '/api/office/trips/report?' + q), {q}); } catch (x) { RK.rep = {error: x.message || tr('unknown'), q}; }
  ofcDraw();
}

// ---- the tab
function rk_travelHtml() {
  if (RK.oid !== OFC.info?.org_id) Object.assign(RK, {oid: OFC.info?.org_id, data: null, rep: null, open: null, err: null, sel: new Set()});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see travel expenses.')}</div>`;
  if (RK.err) return `<div class="empty">${esc(RK.err)}</div>`;
  if (!RK.data) { if (!RK.loading) setTimeout(rk_load, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (RK.open && rk_trip(RK.open)) return rk_tripHtml(rk_trip(RK.open));
  const y0 = new Date().getFullYear(), years = [y0 + 1, y0, y0 - 1, y0 - 2, y0 - 3].map(String);
  const miss = RK.data.missing || 0;
  const bar = `<div class="ofcbar rkbar"><select id="rk-year" aria-label="${esc(tr('Year'))}"><option value="">${tr('All years')}</option>${years.map(y => `<option ${y === RK.year ? 'selected' : ''}>${y}</option>`).join('')}</select>
    <div class="seg" role="group" aria-label="${esc(tr('Show'))}"><button type="button" data-rk="filter" data-v="all" class="${RK.filter === 'all' ? 'on' : ''}" aria-pressed="${RK.filter === 'all'}">${tr('All')}</button><button type="button" data-rk="filter" data-v="missing" class="${RK.filter === 'missing' ? 'on' : ''}" aria-pressed="${RK.filter === 'missing'}">${tr('Not in DATEV')}${miss ? ` <span class="rkbadge">${miss}</span>` : ''}</button></div>
    <div class="seg" role="group" aria-label="${esc(tr('View'))}"><button type="button" data-rk="view" data-v="trips" class="${RK.view === 'trips' ? 'on' : ''}" aria-pressed="${RK.view === 'trips'}">${tr('Trips')}</button><button type="button" data-rk="view" data-v="report" class="${RK.view === 'report' ? 'on' : ''}" aria-pressed="${RK.view === 'report'}">${tr('Evaluation')}</button></div>
    <span class="spacer"></span><button class="btn sm pri" data-rk="new">${ic('plus', 's')}<span>${tr('New trip')}</span></button></div>`;
  return bar + (RK.view === 'report' ? rk_reportHtml() : rk_listHtml());
}
function rk_listHtml() {
  let trips = RK.data.trips || [];
  if (RK.filter === 'missing') trips = trips.filter(t => t.missing);
  if (!trips.length) return `<div class="empty nempty eact">${ic('plane')}<span>${RK.filter === 'missing' ? tr('Every receipt is ticked as in DATEV.') : tr('No trips yet. Add the first one with its receipts.')}</span></div>`;
  return `<ul class="ofclist rklist" role="list">${trips.map(t => `<li><button type="button" class="ofcrow" data-rk="open" data-id="${t.id}"><span class="ofcn"><b>${esc(t.dest || tr('Trip'))}</b>
    <small class="muted">${esc([rk_span(t), rk_purpose(t), (t.people || []).map(p => p.name).join(', ')].filter(Boolean).join(' · '))}</small></span>
    ${t.missing ? `<span class="rotag rkmiss">${esc(trn('{0} not in DATEV', '{0} not in DATEV', t.missing))}</span>` : ''}<span class="rksum">${ofcMoney(t.total)}</span>${ic('chev', 's')}</button></li>`).join('')}</ul>`;
}
function rk_tripHtml(t) {
  const its = RK.filter === 'missing' ? t.items.filter(i => !i.datev) : t.items;
  const head = `<div class="ofcbar"><button class="btn sm ghost" data-rk="back">${ic('back', 's')}<span>${tr('All trips')}</span></button><span class="spacer"></span>
    <button class="btn sm" data-rk="edit" data-id="${t.id}">${ic('edit', 's')}<span>${tr('Edit trip')}</span></button></div>
    <div class="rkhead"><h3>${esc(t.dest || tr('Trip'))}</h3><p class="muted">${esc([rk_span(t), t.overnight ? tr('with overnight stay') : '', rk_purpose(t)].filter(Boolean).join(' · '))}</p>
    ${(t.people || []).length ? `<p class="muted">${esc(tr('Participants'))}: ${esc(t.people.map(p => p.name).join(', '))}</p>` : ''}${t.km ? `<p class="muted">${esc(tr('{0} km', fmtNum(+t.km, 0)))}</p>` : ''}${t.note ? `<p class="rknote">${esc(t.note)}</p>` : ''}</div>`;
  const rows = its.map(i => `<li class="rkit"><label class="rksel"><input type="checkbox" data-rk="sel" data-id="${i.id}" ${RK.sel.has(i.id) ? 'checked' : ''} ${i.billed ? 'disabled' : ''} aria-label="${esc(tr('Select'))}"></label>
    <button type="button" class="ofcrow" data-rk="item" data-id="${i.id}"><span class="ofcn"><b>${esc(rk_cat(i.category))}${i.text ? ` · ${esc(i.text)}` : ''}</b><small class="muted">${esc([fmtDateLoc(i.date), i.currency !== rk_home() ? `${fmtNum(+i.amount, 2)} ${i.currency}` : '', i.datev_no ? tr('DATEV no. {0}', i.datev_no) : ''].filter(Boolean).join(' · '))}</small></span>
    ${i.billed ? `<span class="rotag">${esc(tr('Billed on {0}', i.billed.number || tr('Draft')))}</span>` : ''}<span class="rksum">${ofcMoney(i.amount_home)}</span></button>
    <label class="chkl rkdatev"><input type="checkbox" data-rk="datev" data-id="${i.id}" ${i.datev ? 'checked' : ''}> ${tr('in DATEV')}</label></li>`).join('');
  const nsel = t.items.filter(i => RK.sel.has(i.id) && !i.billed).length;
  return head + `<div class="ofcbar"><b>${tr('Receipts')}</b><span class="muted">${ofcMoney(t.total)}</span><span class="spacer"></span>
    ${nsel ? `<button class="btn sm" data-rk="bill">${ic('receipt', 's')}<span>${esc(trn('Bill {0} receipt on', 'Bill {0} receipts on', nsel))}</span></button>` : ''}
    <button class="btn sm pri" data-rk="add" data-id="${t.id}">${ic('plus', 's')}<span>${tr('Add receipt')}</span></button></div>`
    + (rows ? `<ul class="ofclist rkits" role="list">${rows}</ul><p class="muted ofchint">${tr('Receipts themselves stay in DATEV; tick them here once they are uploaded there.')}</p>` : `<div class="empty nempty">${tr('No receipts yet.')}</div>`);
}
function rk_reportHtml() {
  const q = `by=${RK.by}` + (RK.year ? `&from=${RK.year}-01-01&to=${RK.year}-12-31` : '') + (RK.filter === 'missing' ? '&missing=1' : '');
  if (!RK.rep || RK.rep.q !== q) { setTimeout(rk_loadReport, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (RK.rep.error) return `<div class="empty">${esc(RK.rep.error)}</div>`;
  const by = `<div class="seg wrap" role="group" aria-label="${esc(tr('Sums by'))}">${RK_BY.map(([k, n]) => `<button type="button" data-rk="by" data-v="${k}" class="${k === RK.by ? 'on' : ''}" aria-pressed="${k === RK.by}">${tr(n)}</button>`).join('')}</div>`;
  const lab = g => RK.by === 'month' ? rk_month(g.label) : RK.by === 'category' ? rk_cat(g.key) : g.label;
  const rows = RK.rep.rows.map(g => `<tr><td>${esc(lab(g))}</td><td class="num muted">${g.count}</td><td class="num">${ofcMoney(g.amount)}</td></tr>`).join('');
  return `<div class="ofcbar">${by}<span class="spacer"></span><a class="btn sm" href="/api/office/trips/report?${esc(q)}&format=csv" download>${ic('download', 's')} CSV</a></div>`
    + (RK.rep.rows.length ? `<table class="rktab"><thead><tr><th>${tr(RK_BY.find(x => x[0] === RK.by)[1])}</th><th class="num">${tr('Receipts')}</th><th class="num">${tr('Amount')}</th></tr></thead><tbody>${rows}</tbody>
      <tfoot><tr><th>${tr('Total')}</th><th class="num">${RK.rep.count}</th><th class="num">${ofcMoney(RK.rep.total)}</th></tr></tfoot></table>${RK.by === 'person' ? `<p class="muted ofchint">${tr('A receipt is shared equally between the participants of its trip.')}</p>` : ''}`
      : `<div class="empty nempty">${tr('No receipts in this period.')}</div>`);
}
const rk_month = ym => { const [y, m] = String(ym).split('-').map(Number); return y && m ? new Date(y, m - 1, 1).toLocaleDateString(LOCALE(), {month: 'long', year: 'numeric'}) : ym; };

// ---- dialogs
function rk_tripModal(t) {
  const d = RK.data, ppl = new Set((t?.people || []).filter(p => p.id).map(p => p.id)), free = (t?.people || []).filter(p => !p.id).map(p => p.name).join(', ');
  const md = modal(`<h3>${t ? tr('Edit trip') : tr('New trip')}</h3>
    <div class="row"><label id="rk-fl">${tr('From')}</label>${dateIn('rk-from', t?.date_from || new Date().toISOString().slice(0, 10), {label: tr('From'), clear: false})}</div>
    <div class="row"><label id="rk-tl">${tr('To')}</label>${dateIn('rk-to', t?.date_to || '', {label: tr('To'), empty: tr('same day')})}</div>
    ${ofcRowF('rk-dest', tr('Destination / route'), ofcIn('rk-dest', t?.dest, {max: 300, ph: tr('e.g. Hamburg – Berlin')}))}
    ${ofcChk('rk-over', tr('Overnight stay'), t?.overnight)}
    <div class="row"><span class="rklab">${tr('Participants')}</span><div class="rkppl">${(d.people || []).map(p => `<label class="chkl"><input type="checkbox" data-pid="${p.id}" ${ppl.has(p.id) ? 'checked' : ''}> ${esc(p.name)}</label>`).join('')}</div></div>
    ${ofcRowF('rk-free', tr('Other people'), ofcIn('rk-free', free, {max: 600, ph: tr('Names, separated by commas')}))}
    ${ofcRowF('rk-purpose', tr('Purpose'), ofcSel('rk-purpose', t?.purpose || 'job', [['job', tr('Job for a client / project')], ['acquisition', tr('Acquisition / research')]]))}
    ${ofcRowF('rk-client', tr('Client'), ofcSel('rk-client', t?.client_id || '', (d.clients || []).map(c => [c.id, c.name]), tr('none')))}
    ${ofcRowF('rk-project', tr('Project'), ofcIn('rk-project', t?.project, {list: 'rk-projs'}))}<datalist id="rk-projs">${(d.projects || []).map(p => `<option value="${esc(p)}">`).join('')}</datalist>
    ${ofcRowF('rk-km', tr('Kilometres'), ofcIn('rk-km', t?.km != null ? fmtNum(+t.km, 0) : '', {num: true, ph: tr('optional')}))}
    <div class="row"><label for="rk-note">${tr('Note')}</label><textarea id="rk-note" rows="2" maxlength="2000">${esc(t?.note || '')}</textarea></div>
    <div class="aerr" role="alert"></div>
    <div class="foot">${t ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${t ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        if (!await askConfirm(tr('Delete the trip “{0}” with its receipts?', t.dest || rk_span(t)), '', {ok: tr('Delete'), danger: true})) return;
        const j = await api('DELETE', `/api/office/trips/${t.id}`); md.remove(); RK.open = null; rk_reload();
        toast(tr('Deleted'), async () => { await api('POST', '/api/office/trips', j.trip); rk_reload(); });
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const people = [...$$('[data-pid]', md).filter(x => x.checked).map(x => ({id: +x.dataset.pid})), ...v('#rk-free').split(',').map(s => s.trim()).filter(Boolean).map(name => ({name}))];
      const body = {date_from: v('#rk-from'), date_to: v('#rk-to'), dest: v('#rk-dest'), overnight: $('#rk-over', md).checked ? 1 : 0, people, purpose: v('#rk-purpose'),
        client_id: +v('#rk-client') || null, project: v('#rk-project'), km: ofcNum(v('#rk-km')), note: v('#rk-note')};
      if (t) {
        const old = {date_from: t.date_from, date_to: t.date_to, dest: t.dest, overnight: t.overnight, people: t.people, purpose: t.purpose, client_id: t.client_id, project: t.project, km: t.km, note: t.note};
        await api('PATCH', `/api/office/trips/${t.id}`, body); md.remove(); rk_reload();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/trips/${t.id}`, old); rk_reload(); });
      } else {
        const j = await api('POST', '/api/office/trips', body); md.remove(); RK.open = j.id; rk_reload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/trips/${j.id}`); RK.open = null; rk_reload(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}
function rk_itemModal(t, i) {
  const home = rk_home(), cur = i?.currency || home;
  const md = modal(`<h3>${i ? tr('Edit receipt') : tr('Add receipt')}</h3>
    <div class="row"><label id="rk-dl">${tr('Date')}</label>${dateIn('rk-date', i?.date || t.date_from || '', {label: tr('Date'), empty: tr('optional')})}</div>
    ${ofcRowF('rk-cat', tr('Category'), ofcSel('rk-cat', i?.category || 'train', (RK.data.categories || []).map(c => [c.key, c.label])))}
    ${ofcRowF('rk-amt', tr('Amount'), ofcIn('rk-amt', i ? fmtNum(+i.amount, 2) : '', {num: true}))}
    ${ofcRowF('rk-cur', tr('Currency'), ofcIn('rk-cur', cur, {max: 3, list: 'rk-curs'}))}<datalist id="rk-curs">${[home, 'EUR', 'USD', 'GBP', 'CHF'].filter((x, k, a) => a.indexOf(x) === k).map(x => `<option value="${x}">`).join('')}</datalist>
    <div class="rkfx" ${cur === home ? 'hidden' : ''}>${ofcRowF('rk-fx', tr('Exchange rate (1 {0} = …)', home), ofcIn('rk-fx', i?.fx_rate ? fmtNum(+i.fx_rate, 4) : '', {num: true}))}
      <p class="muted ofchint rkfxout"></p></div>
    ${ofcRowF('rk-text', tr('Text'), ofcIn('rk-text', i?.text, {max: 300, ph: tr('e.g. ICE Hamburg – Berlin')}))}
    ${ofcChk('rk-datev', tr('Receipt is in DATEV'), i?.datev)}
    ${ofcRowF('rk-dno', tr('DATEV receipt number'), ofcIn('rk-dno', i?.datev_no, {max: 60, ph: tr('optional')}))}
    <div class="aerr" role="alert"></div>
    <div class="foot">${i ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${i ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  const fx = () => {
    const c = ($('#rk-cur', md).value || '').trim().toUpperCase(), box = $('.rkfx', md); box.hidden = !c || c === home;
    const a = ofcNum($('#rk-amt', md).value), r = ofcNum($('#rk-fx', md).value);
    $('.rkfxout', md).textContent = !box.hidden && a != null && r ? tr('= {0} in {1}', fmtNum(a / r, 2), home) : '';
  };
  md.addEventListener('input', fx); fx();
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        const j = await api('DELETE', `/api/office/trips/${t.id}/items/${i.id}`); md.remove(); rk_reload();
        const o = j.item; toast(tr('Deleted'), async () => { await api('POST', `/api/office/trips/${t.id}/items`, {date: o.date, category: o.category, amount: o.amount, currency: o.currency, fx_rate: o.fx_rate, amount_home: o.amount_home, text: o.text, datev: o.datev, datev_no: o.datev_no}); rk_reload(); });
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const c = v('#rk-cur').trim().toUpperCase() || home;
      const body = {date: v('#rk-date'), category: v('#rk-cat'), amount: ofcNum(v('#rk-amt')), currency: c, text: v('#rk-text'), datev: $('#rk-datev', md).checked ? 1 : 0, datev_no: v('#rk-dno')};
      if (c !== home) body.fx_rate = ofcNum(v('#rk-fx'));
      if (i) {
        const old = {date: i.date, category: i.category, amount: i.amount, currency: i.currency, fx_rate: i.fx_rate, amount_home: i.amount_home, text: i.text, datev: i.datev, datev_no: i.datev_no};
        await api('PATCH', `/api/office/trips/${t.id}/items/${i.id}`, body); md.remove(); rk_reload();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/trips/${t.id}/items/${i.id}`, old); rk_reload(); });
      } else {
        const j = await api('POST', `/api/office/trips/${t.id}/items`, body); md.remove(); rk_reload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/trips/${t.id}/items/${j.item_id}`); rk_reload(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}
async function rk_billModal(t) {
  const ids = t.items.filter(i => RK.sel.has(i.id) && !i.billed).map(i => i.id); if (!ids.length) return;
  let docs = [];
  try { docs = (await api('GET', `/api/office/trips/bill-docs${t.client_id ? `?client_id=${t.client_id}` : ''}`)).docs || []; } catch (x) { toast(x.message || ''); return; }
  const kind = d => d.kind === 'invoice' ? tr('Invoice') : tr('Quotation');
  const md = modal(`<h3>${tr('Bill receipts on')}</h3>
    <p class="muted">${esc(trn('{0} receipt becomes a position with the amount as purchase price.', '{0} receipts become positions with the amount as purchase price.', ids.length))}</p>
    ${docs.length ? ofcRowF('rk-doc', tr('Quotation or invoice (draft)'), ofcSel('rk-doc', docs[0].id, docs.map(d => [d.id, [kind(d), d.number || tr('Draft'), d.project_title, d.client_id ? rk_client(d.client_id) : ''].filter(Boolean).join(' · ')])))
      : `<div class="empty nempty">${tr('There is no quotation or invoice in draft. Create one first.')}</div>`}
    ${ofcRowF('rk-mk', tr('Markup in %'), ofcIn('rk-mk', '', {num: true, ph: '0'}))}
    ${ids.length > 1 ? ofcChk('rk-one', tr('One position for all receipts'), false) : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${docs.length ? `<button class="btn pri" data-m="save">${tr('Bill on')}</button>` : ''}</div>`);
  md.classList.add('ofcdlg');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      const j = await api('POST', '/api/office/trips/bill', {doc_id: +$('#rk-doc', md).value, item_ids: ids, markup_pct: ofcNum($('#rk-mk', md).value), one: $('#rk-one', md)?.checked ? 1 : 0});
      md.remove(); RK.sel.clear(); rk_reload();
      toast(tr('Billed on {0}', j.number || tr('Draft')), async () => { await api('POST', '/api/office/trips/unbill', {item_ids: j.items, positions: j.positions}); rk_reload(); });
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}

// ---- events
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-rk]'); if (!b || b.tagName === 'INPUT') return;
  const a = b.dataset.rk, t = RK.open ? rk_trip(RK.open) : null;
  if (a === 'new') rk_tripModal(null);
  else if (a === 'open') { RK.open = +b.dataset.id; RK.sel.clear(); ofcDraw(); }
  else if (a === 'back') { RK.open = null; RK.sel.clear(); ofcDraw(); }
  else if (a === 'edit' && t) rk_tripModal(t);
  else if (a === 'add' && t) rk_itemModal(t, null);
  else if (a === 'item' && t) { const i = t.items.find(x => x.id === +b.dataset.id); if (i) rk_itemModal(t, i); }
  else if (a === 'bill' && t) rk_billModal(t);
  else if (a === 'filter') { RK.filter = b.dataset.v; ofcDraw(); }
  else if (a === 'view') { RK.view = b.dataset.v; RK.open = null; ofcDraw(); }
  else if (a === 'by') { RK.by = b.dataset.v; ofcDraw(); }
  else return;
  e.preventDefault();
});
document.addEventListener('change', async e => {
  const x = e.target;
  if (x.id === 'rk-year') { RK.year = x.value; RK.open = null; rk_reload(); return; }
  if (x.dataset?.rk === 'sel') { if (x.checked) RK.sel.add(+x.dataset.id); else RK.sel.delete(+x.dataset.id); ofcDraw(); return; }
  if (x.dataset?.rk !== 'datev' || !RK.open) return;
  const tid = RK.open, iid = +x.dataset.id, on = x.checked ? 1 : 0;
  try {
    await api('PATCH', `/api/office/trips/${tid}/items/${iid}`, {datev: on}); rk_reload();
    toast(on ? tr('Ticked as in DATEV') : tr('Tick removed'), async () => { await api('PATCH', `/api/office/trips/${tid}/items/${iid}`, {datev: on ? 0 : 1}); rk_reload(); });
  } catch (y) { x.checked = !on; toast(y.message || ''); }
});
