// @ts-check
// 2.299.0 C (#3192): the bank bookings without a receipt (tab "Bank", view "Without receipt"; admins of the office area only):
// money paid out that no receipt matched yet, or (second filter) money received that no invoice matched yet; filters month and
// account (with more than one account imported). Per row: upload the receipt (it becomes a receipt of the office's documents and
// is matched at once), drag a receipt without a booking onto the row (computer) or choose it from the candidates (phone),
// "No receipt needed" once, or "... remember" (a bank rule, office_bankrules.js; hidden while the server has no rules).
// Locked months: no actions, a hint. The counter of the office start page and the reminder section of the office settings
// live here too. Server: kalmido/office/banknorc.py (list, counter, reminder) + office/bank.py (match / unmatch).
const BNR = {oid: null, dir: 'out', month: '', account: '', data: null, err: null, q: '', pick: null, cand: null, rules: undefined, cnt: undefined, cntAt: 0, cntLoading: false, rem: null, remLoading: false, hash: ''};
// the link #office/bank/norc (the reminder task, the start page) opens this view once; the tab's own switch leaves it
const bnr_route = () => { if (location.hash.split('/')[2] === 'norc' && BNR.hash !== location.hash) BNK.state = 'norc'; BNR.hash = location.hash; return true; };
const bnr_q = () => `dir=${BNR.dir}${BNR.month ? `&month=${BNR.month}` : ''}${BNR.account ? `&account=${encodeURIComponent(BNR.account)}` : ''}`;
const bnr_mon = m => { const [y, mo] = m.split('-').map(Number); try { return new Intl.DateTimeFormat(LOCALE(), {month: 'long', year: 'numeric'}).format(new Date(y, mo - 1, 1)); } catch { return m; } };

async function bnr_load() {
  const q = bnr_q(); BNR.q = q;
  try { const j = await api('GET', '/api/office/bank/noreceipt?' + q); if (BNR.q === q) { BNR.data = j; BNR.err = null; } }
  catch (x) { BNR.err = x.message || tr('unknown'); }
  if (BNR.rules === undefined) {  // the rules come with part B: without the route (404) the "remember" button stays hidden
    BNR.rules = null;
    // a plain fetch: an unknown route answers an HTML 404, which rawFetch would take for an expired session (reload)
    fetch('/api/office/bank/rules', {headers: {'X-Requested-With': 'kalmido'}, credentials: 'same-origin'}).then(r => r.ok && (r.headers.get('content-type') || '').includes('json'), () => false)
      .then(ok => { BNR.rules = ok; ofcDraw(); });
  }
  ofcDraw();
}
const bnr_reload = () => { BNR.data = null; BNR.pick = null; BNR.cand = null; BNR.cnt = undefined; if (typeof BNK === 'object') BNK.data = null; if (typeof bfbBooksStale === 'function') bfbBooksStale(); ofcDraw(); };

function bnr_html() {
  if (BNR.oid !== OFC.info?.org_id) Object.assign(BNR, {oid: OFC.info?.org_id, data: null, err: null, month: '', account: '', pick: null, cand: null, rules: undefined, rem: null});
  if (BNR.err) return `<div class="empty">${esc(BNR.err)}</div>`;
  if (!BNR.data || BNR.q !== bnr_q()) { setTimeout(() => { if (BNR.q !== bnr_q() || !BNR.data) bnr_load(); }, 0); if (!BNR.data) return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = BNR.data, n = d.counts || {}, out = BNR.dir === 'out';
  const segs = [['out', tr('Payments without a receipt'), n.out], ['in', tr('Income without an invoice'), n.in]];
  const months = d.months || [], accts = d.accounts || [];
  const bar = `<div class="ofcbar bnrbar"><div class="seg" role="group" aria-label="${esc(tr('Show'))}">${segs.map(([k, t, c]) => `<button type="button" data-bnr="dir" data-v="${k}" class="${BNR.dir === k ? 'on' : ''}" aria-pressed="${BNR.dir === k}">${esc(t)}${c ? ` <small>${c}</small>` : ''}</button>`).join('')}</div>
    <select data-bnr-f="month" aria-label="${esc(tr('Month'))}"><option value="">${esc(tr('All months'))}</option>${months.map(m => `<option value="${m}" ${m === BNR.month ? 'selected' : ''}>${esc(bnr_mon(m))}</option>`).join('')}</select>
    ${accts.length ? `<select data-bnr-f="account" aria-label="${esc(tr('Account'))}"><option value="">${esc(tr('All accounts'))}</option>${accts.map(a => `<option value="${esc(a)}" ${a === BNR.account ? 'selected' : ''}>${esc(cfb_acct(a))}</option>`).join('')}</select>` : ''}</div>`;
  const items = d.items || [];
  const list = items.length ? `<ul class="bnklist" role="list">${items.map(bnr_row).join('')}</ul>`
    : `<div class="empty">${ic('check')}<span>${out ? tr('Every payment has its receipt.') : tr('Every income has its invoice.')}</span></div>`;
  const rc = out && !isMobile() && items.length ? bnr_rcHtml(d.receipts || []) : '';
  const miss = out ? bnv_missHtml(d.missing || []) : '';  // 2.425.0 B (#3451)
  return bar + miss + (rc ? `<div class="bnrcols"><div>${list}</div>${rc}</div>` : list)
    + `<p class="muted ofchint">${out ? tr('Drop a file or a receipt from the right onto a booking to match it. Bank fees or tax payments need no receipt.') : tr('Money received that no invoice matched yet.')}</p>`
    + (out ? bnv_html() : '');
}
function bnr_row(t) {
  const out = +t.amount < 0, title = t.counterpart || t.purpose || tr('Booking');
  const head = `<div class="bnkhead"><span class="bnkn"><b>${esc(title)}</b><small class="muted">${esc([fmtDateLoc(t.day), t.counterpart ? t.purpose : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="bnkamt ${out ? 'out' : 'in'}">${esc(bnkAmt(t.amount))}</span></div>`;
  if (t.locked) return `<li class="bnkrow done" data-tx="${t.id}">${head}<p class="muted bnkmiss">${tr('This month is locked: nothing can be changed here.')}</p></li>`;
  const mem = BNR.rules && (t.iban || t.counterpart) ? `<button class="btn sm ghost" data-bnr="remember" data-id="${t.id}">${tr('No receipt needed – remember')}</button>` : '';
  const acts = `<div class="bnkacts">${out ? `<label class="btn sm">${ic('upload', 's')}<span>${tr('Upload receipt')}</span><input type="file" data-bnr-up="${t.id}" accept="${esc(typeof BK_ACCEPT === 'string' ? BK_ACCEPT : 'application/pdf,image/*')}" hidden></label>` : ''}
    <button class="btn sm" data-bnr="pick" data-id="${t.id}" aria-expanded="${BNR.pick === t.id}">${ic('search', 's')}<span>${out ? tr('Choose receipt…') : tr('Choose invoice…')}</span></button>
    <button class="btn sm ghost" data-bnr="noreceipt" data-id="${t.id}">${tr('No receipt needed')}</button>${mem}</div>`;
  return `<li class="bnkrow" data-tx="${t.id}" ${out ? `data-bnr-drop="${t.id}"` : ''}>${head}${acts}${BNR.pick === t.id ? bnr_pickHtml(t) : ''}</li>`;
}
function bnr_pickHtml(t) {
  const c = BNR.cand;
  const rows = !c ? `<p class="muted">${tr('Loading…')}</p>` : !c.length ? `<p class="muted">${tr('Nothing found')}</p>`
    : `<ul class="ofclist" role="list">${c.map(x => `<li><button type="button" class="ofcrow" data-bnr="match" data-id="${t.id}" data-kind="${x.kind}" data-mid="${x.id}"><span class="ofcn"><b>${esc(x.label || tr(BNK_KIND[x.kind]))}</b><small class="muted">${esc(fmtDateLoc(x.date))}</small></span><span class="rksum">${ofcMoney(x.amount)}</span></button></li>`).join('')}</ul>`;
  return `<div class="bnkother">${rows}</div>`;
}
function bnr_rcHtml(rcs) {
  return `<aside class="bnrrc" aria-label="${esc(tr('Receipts without a booking'))}"><h3 class="ofcgrp">${tr('Receipts without a booking')}</h3>
    ${rcs.length ? `<ul class="ofclist" role="list">${rcs.map(r => `<li class="ofcrow bnrdrag" draggable="true" data-bnr-rc="${r.id}"><span class="ofcn"><b>${esc(r.label || tr('Receipt'))}</b><small class="muted">${esc(fmtDateLoc(r.date))}</small></span><span class="rksum">${ofcMoney(r.amount)}</span></li>`).join('')}</ul>`
      : `<p class="muted">${tr('No open receipts around these bookings.')}</p>`}</aside>`;
}

// ---- actions (one undo step each)
async function bnr_match(tid, kind, mid) {
  const req = {kind, ...(mid ? {id: +mid} : {})};
  try { await api('POST', `/api/office/bank/tx/${tid}/match`, req); } catch (x) { return; }
  bnr_reload();
  offerUndo(tr('Matched'), histAdd({label: tr('Bank booking matched'),
    undo: async () => { await api('POST', `/api/office/bank/tx/${tid}/unmatch`); bnr_reload(); },
    redo: async () => { await api('POST', `/api/office/bank/tx/${tid}/match`, req); bnr_reload(); }}));
}
async function bnr_upload(tid, file) {
  const fd = new FormData();
  fd.append('files', file, file.name || 'receipt.pdf'); fd.append('ws', BNR.data?.upload_ws || 'private');
  let j; try { j = await api('POST', '/api/docs', fd); } catch (x) { return; }
  for (const e of j.errors || []) toast(e);
  const id = (j.ids || [])[0] || (j.dups || [])[0]?.id;
  if (!id) return;
  try {
    if ((j.ids || []).length) await api('PUT', `/api/docs/${id}/receipt`, {keep: true});  // a receipt of the office even before its amount is read
    await api('POST', `/api/office/bank/tx/${tid}/match`, {kind: 'receipt', id});
  } catch (x) { bnr_reload(); return; }
  const fresh = (j.ids || []).length > 0;
  bnr_reload();
  offerUndo(tr('Receipt added'), histAdd({label: tr('Bank booking matched'),
    undo: async () => { await api('POST', `/api/office/bank/tx/${tid}/unmatch`); if (fresh) await api('DELETE', `/api/files/nodes/${id}`); bnr_reload(); },
    redo: async () => { if (fresh) await api('POST', `/api/files/nodes/${id}/restore`); await api('POST', `/api/office/bank/tx/${tid}/match`, {kind: 'receipt', id}); bnr_reload(); }}));
}
async function bnr_remember(tid) {
  const t = (BNR.data?.items || []).find(x => x.id === tid); if (!t) return;
  const spec = {...(t.iban ? {iban: t.iban} : {counterpart: t.counterpart}), name: t.counterpart || t.iban, direction: +t.amount < 0 ? 'out' : 'in', action: 'noreceipt', apply_open: true};
  let j; try { j = await api('POST', '/api/office/bank/rules', spec); } catch (x) { return; }
  const rid = j.rule?.id;
  bnr_reload();
  offerUndo(trn('Rule saved, {0} booking matched', 'Rule saved, {0} bookings matched', j.applied || 0), histAdd({label: tr('Bank rule saved'),
    undo: async () => { if (rid) await api('DELETE', `/api/office/bank/rules/${rid}`); await api('POST', `/api/office/bank/tx/${tid}/unmatch`).catch(() => null); bnr_reload(); },
    redo: async () => { await api('POST', '/api/office/bank/rules', spec); bnr_reload(); }}));
}
async function bnr_cand(tid) {
  try { const j = await api('GET', `/api/office/bank/tx/${tid}/candidates`); if (BNR.pick === tid) BNR.cand = j.items || []; } catch (x) { BNR.cand = []; }
  if (BNR.pick === tid) ofcDraw();
}

document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-bnr]'); if (!b) return;
  const a = b.dataset.bnr, id = +b.dataset.id;
  if (a === 'dir') { BNR.dir = b.dataset.v; BNR.month = ''; BNR.pick = null; ofcDraw(); }
  else if (a === 'noreceipt') bnr_match(id, 'noreceipt');
  else if (a === 'remember') bnr_remember(id);
  else if (a === 'match') bnr_match(id, b.dataset.kind, b.dataset.mid);
  else if (a === 'pick') { BNR.pick = BNR.pick === id ? null : id; BNR.cand = null; ofcDraw(); if (BNR.pick) bnr_cand(id); }
  else if (a === 'open') { if (typeof BNK === 'object') BNK.state = 'norc'; go('office/bank/norc'); }
  else return;
  e.preventDefault();
});
document.addEventListener('change', e => {
  const t = /** @type {any} */ (e.target);
  const f = t.closest?.('[data-bnr-f]'); if (f) { BNR[f.dataset.bnrF] = f.value; BNR.pick = null; ofcDraw(); return; }
  const up = t.closest?.('[data-bnr-up]'); if (up && up.files?.length) { bnr_upload(+up.dataset.bnrUp, up.files[0]); up.value = ''; }
});
// computer: a receipt of the right column or a file dropped onto a booking
document.addEventListener('dragstart', e => { const r = /** @type {any} */ (e.target).closest?.('[data-bnr-rc]'); if (r && e.dataTransfer) { e.dataTransfer.setData('text/x-kalmido-receipt', r.dataset.bnrRc); e.dataTransfer.effectAllowed = 'link'; } });
const bnr_dropOk = e => { const ty = [...(e.dataTransfer?.types || [])]; return ty.includes('text/x-kalmido-receipt') || ty.includes('Files'); };
document.addEventListener('dragover', e => { const row = /** @type {any} */ (e.target).closest?.('[data-bnr-drop]'); if (row && bnr_dropOk(e)) { e.preventDefault(); $$('[data-bnr-drop].on').forEach(x => x !== row && x.classList.remove('on')); row.classList.add('on'); } });
document.addEventListener('dragleave', e => { const row = /** @type {any} */ (e.target).closest?.('[data-bnr-drop]'); if (row && !row.contains(/** @type {any} */ (e).relatedTarget)) row.classList.remove('on'); });
document.addEventListener('drop', e => {
  const row = /** @type {any} */ (e.target).closest?.('[data-bnr-drop]'); if (!row || !bnr_dropOk(e)) return;
  e.preventDefault(); row.classList.remove('on');
  const rc = e.dataTransfer.getData('text/x-kalmido-receipt'), tid = +row.dataset.bnrDrop;
  if (rc) bnr_match(tid, 'receipt', rc);
  else if (e.dataTransfer.files?.length) bnr_upload(tid, e.dataTransfer.files[0]);
});

// ---- the counter on the office start page (admins of the office only: the route answers others 403 = no counter)
function bnr_startHtml() {
  if (BNR.cnt === undefined || (Date.now() - BNR.cntAt > 60000 && !BNR.cntLoading)) {
    if (!BNR.cntLoading) {
      BNR.cntLoading = true;
      rawFetch('GET', '/api/office/bank/noreceipt/count').then(j => { BNR.cnt = j; }, () => { BNR.cnt = null; }).finally(() => { BNR.cntLoading = false; BNR.cntAt = Date.now(); if (S.route.mod === 'office' && ofcTab() === 'start') ofcDraw(); });
    }
    if (BNR.cnt === undefined) return '';
  }
  const n = BNR.cnt?.out || 0;
  if (!n) return '';
  return `<button type="button" class="oflr bnrcnt" data-bnr="open">${ic('receipt')}<span>${esc(trn('{0} booking without a receipt', '{0} bookings without a receipt', n))}</span>${ic('chev', 's')}</button>`;
}

// ---- the reminder (office settings, area Data): off / weekly / monthly, the responsible person; every field saves itself
async function bnr_remLoad() {
  if (BNR.remLoading) return;
  BNR.remLoading = true;
  try { BNR.rem = await api('GET', '/api/office/bank/noreceipt/reminder'); } catch (x) { BNR.rem = false; }
  BNR.remLoading = false;
  ofcDraw();
}
function bnr_settingsHtml(dis) {
  if (!ofcAdmin()) return '';
  const d = BNR.rem;
  if (d === false) return '';
  if (!d) { if (!BNR.remLoading) setTimeout(bnr_remLoad, 0); return ''; }
  const ppl = d.people || [], opt = (v, t) => `<option value="${v}" ${d.every === v ? 'selected' : ''}>${esc(t)}</option>`;
  return `<h3>${tr('Bank bookings without a receipt')}</h3>
    ${ofcRowF('bnr-every', tr('Reminder'), `<select id="bnr-every" data-bnr-rem="every" ${dis}>${opt('off', tr('Off'))}${opt('week', tr('Weekly'))}${opt('month', tr('Monthly'))}</select>`, tr('a task while bookings without a receipt are there; done by itself once the list is empty'))}
    ${ppl.length > 1 && d.every !== 'off' ? ofcRowF('bnr-user', tr('Responsible person'), `<select id="bnr-user" data-bnr-rem="user" ${dis}>${ppl.map(p => `<option value="${p.id}" ${p.id === (d.user || S.me?.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`) : ''}
    ${d.lost ? `<p class="aerr" role="alert">${tr('The person responsible is no longer an administrator. Please choose someone else.')}</p>` : ''}`;
}
document.addEventListener('change', async e => {
  const el = /** @type {any} */ (e.target).closest?.('[data-bnr-rem]'); if (!el) return;
  const k = el.dataset.bnrRem, v = k === 'user' ? +el.value : el.value, was = BNR.rem ? BNR.rem[k] : null;
  try { BNR.rem = await api('PUT', '/api/office/bank/noreceipt/reminder', {[k]: v}); } catch (x) { bnr_remLoad(); return; }
  ofcDraw();
  if (was != null && was !== v) offerUndo(tr('Saved'), histAdd({label: tr('Reminder changed'),
    undo: async () => { BNR.rem = await api('PUT', '/api/office/bank/noreceipt/reminder', {[k]: was}); ofcDraw(); },
    redo: async () => { BNR.rem = await api('PUT', '/api/office/bank/noreceipt/reminder', {[k]: v}); ofcDraw(); }}));
});

// ---- 2.425.0 B (#3451): recurring providers (the same counterpart at a regular rhythm; server: kalmido/office/bankvend.py).
// Above the list: "Invoice <provider> <month> missing" once the office's days after the booking passed, with the portal link
// and the upload / drop field of the booking (the receipt is matched at once, as on every row). Below the list: the providers
// with their portal link, the hint on / off and "No receipt needed" (their bookings leave this list); the days. Every field
// saves itself, one undo step each.
const BNV = {oid: null, data: null, loading: false, open: false, all: false};
const BNV_HINTS = 5;  // hints shown before "Show all"
const BNV_EVERY = {week: N_('Weekly'), month: N_('Monthly'), quarter: N_('Quarterly'), year: N_('Yearly')};
function bnv_missHtml(hs) {
  if (!hs.length) return '';
  const more = BNV.all ? 0 : hs.length - BNV_HINTS;
  if (more > 0) hs = hs.slice(0, BNV_HINTS);
  const acc = esc(typeof BK_ACCEPT === 'string' ? BK_ACCEPT : 'application/pdf,image/*');
  return `<section class="bnvmiss" aria-label="${esc(tr('Missing invoices of recurring providers'))}"><h3 class="ofcgrp">${tr('Missing invoices of recurring providers')}</h3>
    <ul class="bnklist" role="list">${hs.map(h => `<li class="bnkrow bnvhint" data-bnr-drop="${h.id}" data-bnv-hint="${h.id}"><div class="bnkhead"><span class="bnkn"><b>${esc(h.text)}</b><small class="muted">${esc(fmtDateLoc(h.day))}</small></span><span class="bnkamt out">${esc(bnkAmt(-h.amount))}</span></div>
      <div class="bnkacts">${h.portal ? `<a class="btn sm" href="${esc(h.portal)}" target="_blank" rel="noopener noreferrer">${ic('link', 's')}<span>${tr('Customer portal')}</span></a>` : ''}<label class="btn sm">${ic('upload', 's')}<span>${tr('Upload receipt')}</span><input type="file" data-bnr-up="${h.id}" accept="${acc}" hidden></label></div></li>`).join('')}</ul>
    ${more > 0 ? `<button type="button" class="btn sm ghost bnvmore" data-bnv-all>${esc(tr('Show all ({0})', hs.length + more))}</button>` : ''}</section>`;
}
async function bnv_load() {
  if (BNV.loading) return;
  BNV.loading = true;
  try { BNV.data = await api('GET', '/api/office/bank/vendors'); } catch (x) { BNV.data = false; }
  BNV.loading = false;
  ofcDraw();
}
function bnv_html() {
  if (BNV.oid !== OFC.info?.org_id) Object.assign(BNV, {oid: OFC.info?.org_id, data: null});
  if (BNV.data === false) return '';
  if (!BNV.data) { if (!BNV.loading) setTimeout(bnv_load, 0); return ''; }
  const vs = BNV.data.items || [];
  const rows = vs.length ? `<ul class="bnklist" role="list">${vs.map(v => {
    const k = esc(JSON.stringify([v.kind, v.match]));
    const sub = [v.every ? tr(BNV_EVERY[v.every]) : '', v.last_day ? fmtDateLoc(v.last_day) : '', v.amount ? ofcMoney(v.amount) : ''].filter(Boolean).join(' · ');
    return `<li class="bnkrow bnvrow ${v.active && !v.noreceipt ? '' : 'done'}" data-bnv-k="${k}"><div class="bnkhead"><span class="bnkn"><b>${esc(v.name)}</b><small class="muted">${esc(sub)}</small></span></div>
      <label class="bnvportal"><span class="muted">${tr('Customer portal')}</span><input type="url" inputmode="url" data-bnv-portal value="${esc(v.portal)}" placeholder="https://" aria-label="${esc(tr('Customer portal'))}: ${esc(v.name)}"${v.portal_suggested ? ` title="${esc(tr('Suggestion'))}"` : ''}></label>
      <div class="bnkacts"><label class="chkl"><input type="checkbox" data-bnv="active" ${v.active ? 'checked' : ''}><span>${tr('Remind me of missing invoices')}</span></label>
      <label class="chkl"><input type="checkbox" data-bnv="noreceipt" ${v.noreceipt ? 'checked' : ''}><span>${tr('No receipt needed')}</span></label></div></li>`;
  }).join('')}</ul>` : `<p class="muted">${tr('No recurring providers found yet. A counterpart that takes money out regularly (monthly, yearly) shows up here.')}</p>`;
  return `<details class="bnvlist" ${BNV.open ? 'open' : ''}><summary data-bnv-open>${tr('Recurring providers')}${vs.length ? ` <small>${vs.length}</small>` : ''}</summary>
    ${ofcRowF('bnv-days', tr('Invoice missing after'), `<input id="bnv-days" type="number" min="0" max="90" step="1" inputmode="numeric" data-bnv-days value="${BNV.data.days}"> <span class="muted">${tr('days')}</span>`)}
    ${rows}</details>`;
}
async function bnv_put(path, req, undoReq) {
  try { BNV.data = await api('PUT', path, req); } catch (x) { bnv_load(); return; }
  bnr_reload();
  offerUndo(tr('Saved'), histAdd({label: tr('Recurring provider changed'),
    undo: async () => { BNV.data = await api('PUT', path, undoReq); bnr_reload(); },
    redo: async () => { BNV.data = await api('PUT', path, req); bnr_reload(); }}));
}
document.addEventListener('click', e => {
  const t = /** @type {any} */ (e.target), s = t.closest?.('[data-bnv-open]');
  if (s) BNV.open = !s.parentElement.open;
  else if (t.closest?.('[data-bnv-all]')) { BNV.all = true; ofcDraw(); }
});
document.addEventListener('change', e => {
  const t = /** @type {any} */ (e.target);
  if (t.matches?.('[data-bnv-days]')) {
    const v = Math.round(+t.value), was = BNV.data?.days;
    if (!(v >= 0 && v <= 90)) { t.value = was; return; }
    bnv_put('/api/office/bank/vendors/settings', {days: v}, {days: was});
    return;
  }
  const row = t.closest?.('[data-bnv-k]'); if (!row) return;
  const [kind, match] = JSON.parse(row.dataset.bnvK), v = (BNV.data?.items || []).find(x => x.kind === kind && x.match === match); if (!v) return;
  if (t.matches('[data-bnv-portal]')) {
    const p = t.value.trim();
    if (p && !/^https:\/\/\S+$/.test(p)) { toast(tr('The link must start with https://')); t.value = v.portal; return; }
    bnv_put('/api/office/bank/vendors', {kind, match, portal: p}, {kind, match, portal: v.portal_suggested ? '' : v.portal});
  } else if (t.dataset.bnv) {
    const f = t.dataset.bnv;
    bnv_put('/api/office/bank/vendors', {kind, match, [f]: t.checked}, {kind, match, [f]: !!v[f]});
  }
});
