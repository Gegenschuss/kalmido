/* Kalmido web client: Home & life (modules contracts, home, care, health, review, travel, reading): the view, its dialogs,
   the review + journal, staying in touch on a contact's card, trips, read later (Karakeep).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.22.0 (#663): "Home & life". Seven modules, each off by default (Settings > Modules > At home). Kalmido connects and
// reminds instead of rebuilding special tools: a contract is a task due on the last day to cancel (repeating with the
// renewal), a device a task due when the warranty ends, upkeep a repeating task, a health entry a task in a private health
// list (never visible to agents), a trip a list with dates. The view loads GET /api/life (contacts and Karakeep are not in
// /api/state); the review has its own view with the private journal.
// 2.65.0 (#1823): LIFE_MODS, lifeOn and fmtMoney are in lazyload.js (this file loads on demand, module life)
// 2.173.0 A (#2680): travel and staying in touch exist per space (Private or an organisation, like Reading): the view
// shows the shown workspace's (rd_space; under "All workspaces" Private or the one picked here), in an organisation only
// these two; contracts, devices, health, budget and family stay private
const LF = {data: null, loading: false, seq: 0, space: '', sp: ''};  // space = picked under "All workspaces", sp = the space loaded
const lf_sp = () => rd_space(LF.space);
const lf_org = () => lf_sp().startsWith('org:');
// may the person add in the shown organisation (guests, read-only and accounting do not)
const lf_ro = () => lf_org() && ['readonly', 'guest', 'accounting'].includes(wsOrg(lf_sp().slice(4))?.role);
const RV = {period: 'day', date: null, data: null, loading: false, seq: 0, edit: null, t: null, chain: null};
const HEALTH_TYPES = [['appointment', N_('Appointment'), 'stetho'], ['checkup', N_('Check-up'), 'clipboard'], ['vaccination', N_('Vaccination'), 'syringe'], ['medication', N_('Medication'), 'pill']];  // 2.223.0 C (#2820): app icons
const PERIOD_WORD = {month: N_('per month'), quarter: N_('per quarter'), year: N_('per year')};
const MOODS = [[1, '😞', N_('Bad')], [2, '😕', N_('Not so good')], [3, '😐', N_('Okay')], [4, '🙂', N_('Good')], [5, '😄', N_('Great')]];
const lifeKind = t => t?.fam?.kind;
const isLifeTask = t => ['contract', 'device', 'upkeep', 'health', 'bookmark'].includes(lifeKind(t));
const lifeWhen = (d, soon = 30) => { if (!d) return ''; const n = daysTo(d); return `<span class="fwhen ${n < 0 ? 'over' : n <= soon ? 'soon' : ''}">${esc(Math.abs(n) <= 14 ? daysWord(n) : fmtDateLoc(d))}</span>`; };
const noticeWord = (n, u) => !n ? tr('no notice period') : u === 'd' ? trn('{0} day', '{0} days', n) : u === 'w' ? trn('{0} week', '{0} weeks', n) : trn('{0} month', '{0} months', n);

async function lifeLoad() {
  const seq = ++LF.seq;
  LF.loading = true;
  const sp = lf_sp();
  try { const j = await api('GET', '/api/life?space=' + encodeURIComponent(sp)); if (seq === LF.seq) { LF.data = j; LF.sp = sp; } }
  catch (e) { if (seq === LF.seq) { LF.data = LF.data || {modules: []}; LF.sp = sp; if (e.status === 404) LF.space = ''; } }
  LF.loading = false;
  if (S.route.mod === 'life' && seq === LF.seq) { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('life', viewLife()))); }
}
const lifeReload = () => { LF.data = null; return lifeLoad(); };

// ---- the view "Home & life"
function viewLife() {
  if ((!LF.data || LF.sp !== lf_sp()) && !LF.loading) setTimeout(lifeLoad, 0);  // 2.173.0 A (#2680): another space shown
  const d = LF.data, org = lf_org(), ro = lf_ro();
  const card = (k, icon, title, body, acts = '', n = '') => `<section class="dcard fcard lcard lc-${k}" aria-labelledby="lh-${k}"><h2 id="lh-${k}">${ic(icon, 's')}<span>${esc(title)}</span>${n !== '' ? `<span class="dcn">${n}</span>` : ''}<span class="spacer"></span></h2>${body}${acts ? `<div class="fcfoot">${acts}</div>` : ''}</section>`;
  const btn = (act, icon, label, extra = '') => `<button type="button" class="btn sm" data-act="${act}" ${extra}>${ic(icon, 's')}<span>${esc(label)}</span></button>`;
  const open = id => `href="#t/${id}"`;
  if (!d) return `<div class="dash life"><p class="muted lempty">${tr('Loading…')}</p></div>`;
  const cards = [];
  if (d.contracts) {
    const c = d.contracts, its = c.items;
    const sum = its.some(x => x.monthly != null) ? `<div class="lsum"><span><b>${esc(fmtMoney(c.monthly))}</b> ${tr('per month')}</span><span class="muted">${esc(fmtMoney(c.yearly))} ${tr('per year')}</span></div>` : '';
    const rows = its.length ? `<ul class="flist">${its.map(x => `<li><a ${open(x.task_id)} class="frow"><span class="ft"><b>${esc(x.name)}</b><span class="muted">${esc([x.provider, x.cost != null ? fmtMoney(x.cost) + ' ' + tr(PERIOD_WORD[x.per]) : '', x.ends ? tr('runs until {0}', fmtDateLoc(x.ends)) : ''].filter(Boolean).join(' · '))}</span></span><span class="lwhen"><small class="muted">${tr('cancel by')}</small>${lifeWhen(x.due, 45)}</span></a></li>`).join('')}</ul>`
      : `<p class="muted">${tr('Phone, electricity, streaming, insurance: add your contracts and get reminded before the last day to cancel.')}</p>`;
    cards.push(card('contracts', 'file', tr('Contracts & subscriptions'), sum + rows, btn('life-contract', 'plus', tr('Contract')), its.filter(x => x.days != null && x.days <= 45).length || ''));
  }
  if (feat('budget') && !org) cards.push(bg_homeCard());  // 2.72.0 (#1333): the household budget (budget.js)
  if (feat('feeds') && !org) cards.push(rss_homeCard());  // 2.85.0 B (#1162): feeds (feeds.js)
  if (d.home) {
    const h = d.home;
    const devs = h.devices.length ? `<h3 class="lsub">${tr('Devices & warranty')}</h3><ul class="flist">${h.devices.map(x => `<li><a ${open(x.task_id)} class="frow"><span class="ft"><b>${esc(x.name)}</b><span class="muted">${esc([x.model, x.bought ? tr('bought {0}', fmtDateLoc(x.bought)) : ''].filter(Boolean).join(' · '))}</span></span>${x.warranty ? `<span class="lwhen"><small class="muted">${x.days < 0 ? tr('warranty ended') : tr('warranty until')}</small>${lifeWhen(x.warranty, 60)}</span>` : `<span class="muted">${tr('no warranty date')}</span>`}</a></li>`).join('')}</ul>` : '';
    const ups = h.upkeep.length ? `<h3 class="lsub">${tr('Upkeep')}</h3><ul class="flist">${h.upkeep.map(x => `<li><a ${open(x.task_id)} class="frow"><span class="ft"><b>${esc(x.title)}</b><span class="muted">${esc([x.item, x.every_months ? trn('every {0} month', 'every {0} months', x.every_months) : ''].filter(Boolean).join(' · '))}</span></span>${lifeWhen(x.due, 14)}</a></li>`).join('')}</ul>` : '';
    cards.push(card('home', 'tool', tr('Home & devices'), devs + ups || `<p class="muted">${tr('Heating, smoke detectors, tyres; devices with their warranty and receipt: Kalmido reminds you in time.')}</p>`,
      btn('life-device', 'plus', tr('Device')) + btn('life-upkeep', 'repeat', tr('Upkeep'))));
  }
  if (d.care) {
    const c = d.care;
    const body = !c.contacts ? `<p class="muted">${tr('Staying in touch needs the module Contacts (Settings > Modules).')}</p>`
      : c.items.length ? `<ul class="flist">${c.items.map(x => `<li class="frow lcare"><a href="#contacts/${x.contact_id}" class="ft"><b>${esc(x.fn)}</b><span class="muted">${esc(x.last ? tr('last contact {0}', fmtDateLoc(x.last)) : tr('no contact noted yet'))}${x.note ? ' · ' + esc(x.note) : ''}</span></a>${x.days <= 0 ? `<span class="fwhen ${x.days < 0 ? 'over' : 'soon'}">${esc(x.days < 0 ? trn('{0} day overdue', '{0} days overdue', -x.days) : tr('today'))}</span>` : `<span class="fwhen">${esc(daysWord(x.days))}</span>`}${ro ? '' : `<button type="button" class="btn sm" data-act="life-touch" data-cid="${x.contact_id}" title="${esc(tr('We were in touch today'))}">${ic('check', 's')}<span>${tr('In touch')}</span></button>`}</li>`).join('')}</ul>`
      : `<p class="muted">${org ? tr('Open a contact of this organisation and choose how often you want to be in touch: Kalmido tells you when it has been too long.') : tr('Open a contact and choose how often you want to be in touch: Kalmido tells you when it has been too long.')}</p>`;
    cards.push(card('care', 'users', tr('Staying in touch'), body, c.contacts ? `<a class="btn sm" href="#contacts">${ic('users', 's')}<span>${tr('Contacts')}</span></a>` : '', c.items.filter(x => x.days <= 0).length || ''));
  }
  if (d.health) {
    const its = d.health.items.filter((x, i) => (x.days != null && x.days <= 60) || i < 4).slice(0, 10);
    const ty = k => HEALTH_TYPES.find(x => x[0] === k) || HEALTH_TYPES[0];
    const body = its.length ? `<ul class="flist">${its.map(x => `<li><a ${open(x.task_id)} class="frow"><span class="fem" aria-hidden="true">${ic(ty(x.type)[2])}</span><span class="ft"><b>${esc(x.title)}</b><span class="muted">${esc([tr(ty(x.type)[1]), x.who, x.time].filter(Boolean).join(' · '))}</span></span>${lifeWhen(x.due, 7)}</a></li>`).join('')}</ul>`
      : `<p class="muted">${tr('Appointments, check-ups, vaccinations and medication, for you and the family. Private: never visible to agents.')}</p>`;
    cards.push(card('health', 'heart', tr('Health'), body, btn('life-health', 'plus', tr('Health entry')), its.filter(x => x.days != null && x.days <= 7).length || ''));
  }
  if (d.travel) {
    const ts = d.travel.trips;
    const body = ts.length ? `<ul class="flist">${ts.map(x => `<li><a href="#l/${x.list_id}" class="frow"><span class="fem" aria-hidden="true">${x.state === 'now' ? '🧳' : x.state === 'past' ? '🏁' : '✈️'}</span><span class="ft"><b>${esc(x.name)}</b><span class="muted">${esc([x.where, fmtDateLoc(x.from) + ' – ' + fmtDateLoc(x.to)].filter(Boolean).join(' · '))}</span></span><span class="lwhen"><small class="muted">${esc(tr('{0} open', x.open))}</small>${x.state === 'upcoming' ? `<span class="fwhen ${x.days <= 7 ? 'soon' : ''}">${esc(daysWord(x.days))}</span>` : `<span class="fwhen">${esc(x.state === 'now' ? tr('travelling') : tr('done|trip'))}</span>`}</span></a></li>`).join('')}</ul>`
      : `<p class="muted">${tr('A trip gets its own project: bookings, what to do before you leave and the packing list.')}</p>`;
    cards.push(card('travel', 'plane', tr('Travel'), body, ro ? '' : btn('life-trip', 'plus', tr('Trip'))));
  }
  if (d.reading) {
    const r = d.reading, kk = r.karakeep || {};
    const body = (r.items.length ? `<ul class="flist">${r.items.slice(0, 8).map(x => `<li class="frow"><a ${open(x.task_id)} class="ft"><b>${esc(x.title)}</b>${x.url ? `<span class="muted lurl">${esc(x.url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 60))}</span>` : ''}</a>${x.url ? `<a class="iconbtn" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer" title="${esc(tr('Open the link'))}" aria-label="${esc(tr('Open {0}', x.title))}">${ic('link', 's')}</a>` : ''}</li>`).join('')}</ul>${r.count > 8 ? `<p class="muted">${esc(trn('and {0} more', 'and {0} more', r.count - 8))}</p>` : ''}`
      : `<p class="muted">${tr('Nothing to read yet. Links you add to a “Read later” project, or bookmarks from Karakeep, show up here.')}</p>`)
      + (kk.connected ? `<p class="muted lkk">${ic(kk.error ? 'alert' : 'sync', 's')} ${esc(kk.error ? tr('Karakeep: {0}', kk.error) : kk.synced_at ? tr('Karakeep, fetched {0}', fmtDateLoc(kk.synced_at.slice(0, 10))) : tr('Karakeep connected'))}</p>` : '');
    const acts = `<a class="btn sm" href="#reading">${ic('book', 's')}<span>${tr('Open')}</span></a>`  // 2.172.0 B (#2679): the view Read later (area Reading)
      + `<a class="btn sm" href="#bookmarks">${ic('bookmark', 's')}<span>${tr('Bookmarks')}</span></a>`  // 2.97.0 A (#1950): the bookmarks (bookmarks.js)
      + (r.lists.length ? `<a class="btn sm" href="#l/${r.lists[0]}">${ic('book', 's')}<span>${tr('Reading list')}</span></a>` : '')
      + (kk.connected ? btn('life-kksync', 'sync', tr('Fetch now')) : '') + btn('life-kk', 'link', kk.connected ? tr('Karakeep…') : tr('Connect Karakeep…'));
    cards.push(card('reading', 'book', tr('Read later'), body, acts, r.count || ''));
  }
  const spSel = rd_pick(lf_sp(), 'data-lf-space');  // 2.173.0 A (#2680): only under "All workspaces"
  const head = spSel ? `<div class="bmbar lfbar"><span class="spacer"></span>${spSel}</div>` : '';
  if (!cards.length) return `<div class="dash life">${head}<div class="empty nempty eact">${ic('home')}<span>${org ? tr('Switch on travel or staying in touch under Settings > Modules.') : tr('Switch on the parts of Home & life you want under Settings > Modules.')}</span><button type="button" class="btn" data-act="life-mods">${tr('Modules')}</button></div></div>`;
  return `<div class="dash fam life">${head}<div class="dgrid">${cards.join('')}</div></div>`;
}

// ---- dialogs
function lifeListOpts(kind, sel) {
  const ls = S.lists.filter(l => !l.archived && canEditList(l.id) && !l.is_inbox && (kind === 'health' ? l.life === 'health' : true));
  const def = ls.find(l => l.life === kind);
  const names = {contracts: N_('New project: Contracts'), home: N_('New project: Home & devices'), health: N_('New project: Health')};
  if (ls.length <= 1 && def) return '';
  return `<div class="row"><label for="lf-list">${tr('Project')}</label><select id="lf-list">${def ? '' : `<option value="">${tr(names[kind])}</option>`}${ls.map(l => `<option value="${l.id}" ${l.id === (sel || def?.id) ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>`;
}
const leadOpts = (sel, list = [0, 1, 3, 7, 14, 30, 60, 90]) => list.map(n => `<option value="${n}" ${n === sel ? 'selected' : ''}>${n ? trn('{0} day before', '{0} days before', n) : tr('on the day')}</option>`).join('');
async function lifeDone(md, t, msg) {
  md.remove(); await load(); render(); LF.data = null;
  if (S.route.mod === 'life') lifeLoad();
  if (t) toast(msg || tr('Added: {0}', t.title), () => openDetail(t.id), 6000, tr('Open'));
}
function lifeErr(md, er) { const e = $('.aerr', md); if (e) e.textContent = er.message || ''; }
// 2.269.0 C (#3017): saved elsewhere in between (409) -- a bar with "Reload" instead of overwriting (also the budget dialogs)
function lifeConflict(md, reload) {
  const e = $('.aerr', md); if (!e) return;
  e.innerHTML = `${esc(tr('Changed in the meantime'))} · ${esc(tr('Reload shows the saved version; your input here is not saved.'))} <button type="button" class="btn sm" data-lf-reload>${tr('Reload')}</button>`;
  $('[data-lf-reload]', e).addEventListener('click', ev => { ev.stopPropagation(); reload(); });
}
const lifeFoot = (ok = tr('Add')) => `<div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${esc(ok)}</button></div>`;
function lifeModal(html, save, focus) {
  const md = modal(html);
  md.classList.add('famdlg', 'lifedlg');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'save') { b.disabled = true; try { await save(md); } catch (er) { lifeErr(md, er); } finally { b.disabled = false; } }
  });
  setTimeout(() => $(focus, md)?.focus(), 30);
  return md;
}
// a contract: new, or (t) change the one of a task (the due date follows the end of the term and the notice period)
function contractModal(t) {
  const f = t?.fam || {};
  const ends = t?.due ? lifeEnd(t.due, f.notice || 0, f.nu || 'm') : '';
  const renew = t ? lifeRenew(t.repeat) : 12;
  const md = lifeModal(`<h3>${ic('file', 's')} ${t ? tr('Edit contract') : tr('New contract')}</h3>
    <div class="row"><label for="lf-name">${tr('Contract')}</label><input id="lf-name" maxlength="100" autocomplete="off" value="${esc(f.name || '')}" placeholder="${esc(tr('e.g. Mobile phone, electricity, streaming'))}"></div>
    <div class="row"><label for="lf-prov">${tr('Provider')}</label><input id="lf-prov" maxlength="100" autocomplete="off" value="${esc(f.provider || '')}" placeholder="${esc(tr('optional'))}"></div>
    <div class="row"><label for="lf-cost">${tr('Cost')}</label><span class="lcost"><input id="lf-cost" inputmode="decimal" class="numin" value="${f.cost != null ? esc(String(f.cost)) : ''}" placeholder="0,00" aria-label="${esc(tr('Cost'))}"><select id="lf-per" aria-label="${esc(tr('Period'))}">${Object.entries(PERIOD_WORD).map(([k, w]) => `<option value="${k}" ${(f.per || 'month') === k ? 'selected' : ''}>${tr(w)}</option>`).join('')}</select></span></div>
    <div class="row"><label id="lf-endl">${tr('Current term ends')}</label>${dateIn('lf-ends', ends, {label: tr('Current term ends'), empty: tr('choose')})}</div>
    <div class="row"><label for="lf-notice">${tr('Notice period')}</label><span class="lcost"><input id="lf-notice" type="number" inputmode="numeric" min="0" max="365" class="numin" value="${esc(String(f.notice ?? 1))}" aria-label="${esc(tr('Notice period'))}"><select id="lf-nu" aria-label="${esc(tr('Unit'))}"><option value="d" ${f.nu === 'd' ? 'selected' : ''}>${tr('days')}</option><option value="w" ${f.nu === 'w' ? 'selected' : ''}>${tr('weeks')}</option><option value="m" ${!f.nu || f.nu === 'm' ? 'selected' : ''}>${tr('months')}</option></select></span></div>
    <div class="row"><label for="lf-renew">${tr('Then')}</label><select id="lf-renew">${[[0, tr('it ends')], [1, tr('renews monthly')], [3, tr('renews every 3 months')], [6, tr('renews every 6 months')], [12, tr('renews every year')], [24, tr('renews every 2 years')]].map(([v, w]) => `<option value="${v}" ${v === renew ? 'selected' : ''}>${esc(w)}</option>`).join('')}</select></div>
    <div class="row"><label for="lf-lead">${tr('Remind me')}</label><select id="lf-lead">${leadOpts(f.lead ?? 14)}</select></div>
    <details class="lmore"><summary>${tr('More')}</summary>
      <div class="row"><label for="lf-acc">${tr('Paid from')}</label><input id="lf-acc" maxlength="100" value="${esc(f.account || '')}" placeholder="${esc(tr('e.g. joint account, credit card'))}"></div>
      <div class="row"><label>${tr('Since')}</label>${dateIn('lf-start', f.start || '', {label: tr('Since'), empty: tr('optional')})}</div></details>
    ${t ? '' : lifeListOpts('contracts')}
    <div class="shint lhint keep">${tr('Due on the last day to cancel. Ticking it off means you keep it: it moves on to the next term.')}</div>
    ${lifeFoot(t ? tr('Save') : tr('Add'))}`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    const name = v('#lf-name'), endsV = v('#lf-ends');
    if (!name) { $('#lf-name', md).focus(); throw new Error(tr('Please enter a name')); }
    if (!endsV) throw new Error(tr('Please enter the date'));
    const cost = v('#lf-cost'), notice = +v('#lf-notice') || 0, nu = v('#lf-nu'), rn = +v('#lf-renew'), lead = +v('#lf-lead');
    const costN = parseNum(cost) ?? -1;
    if (cost && !(costN >= 0 && costN < 1e8)) { $('#lf-cost', md).focus(); throw new Error(tr('Invalid value: {0}', tr('Cost'))); }  // 2.263.0 (#2976): "1.500,00" / "1,500.00" too
    if (!t) {
      const nt = await rawFetch('POST', '/api/life/contracts', {name, ends: endsV, provider: v('#lf-prov'), ...(cost ? {cost: parseNum(cost)} : {}), per: v('#lf-per'), notice, notice_unit: nu,
        renew_months: rn, lead_days: lead, ...(v('#lf-acc') ? {account: v('#lf-acc')} : {}), ...(v('#lf-start') ? {start: v('#lf-start')} : {}), ...(v('#lf-list') ? {list_id: +v('#lf-list')} : {})});
      return lifeDone(md, nt);
    }
    const fam = {kind: 'contract', name, provider: v('#lf-prov'), per: v('#lf-per'), notice, nu, lead, ...(cost ? {cost: parseNum(cost)} : {}),
      ...(v('#lf-acc') ? {account: v('#lf-acc')} : {}), ...(v('#lf-start') ? {start: v('#lf-start')} : {})};
    await patchUndoable(t.id, {fam, due: lifeDue(endsV, notice, nu), repeat: lifeRule(rn), reminders: [lead ? lead * 1440 : null, 0].filter(x => x != null).join(','),
      title: tr('Cancel or renew the contract: {0}', name)});
    md.remove(); LF.data = null; renderDetail?.();
  }, '#lf-name');
  return md;
}
// date maths of a contract (the same as the server: due = end of term minus the notice period)
function lifeShift(s, n, u, sign) { const d = pd(s); if (u === 'd') d.setDate(d.getDate() + sign * n); else if (u === 'w') d.setDate(d.getDate() + sign * 7 * n); else { const day = d.getDate(); d.setDate(1); d.setMonth(d.getMonth() + sign * n); d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate())); } return ds(d); }
const lifeEnd = (due, n, u) => lifeShift(due, n, u, 1);
const lifeDue = (end, n, u) => lifeShift(end, n, u, -1);
function lifeRenew(rep) { const m = /^FREQ=MONTHLY(?:;INTERVAL=(\d+))?$/.exec(rep || ''), y = /^FREQ=YEARLY(?:;INTERVAL=(\d+))?$/.exec(rep || ''); return m ? +(m[1] || 1) : y ? +(y[1] || 1) * 12 : 0; }
const lifeRule = m => !m ? '' : m === 12 ? 'FREQ=YEARLY' : m % 12 === 0 ? `FREQ=YEARLY;INTERVAL=${m / 12}` : m === 1 ? 'FREQ=MONTHLY' : `FREQ=MONTHLY;INTERVAL=${m}`;

function deviceModal() {
  lifeModal(`<h3>${ic('tool', 's')} ${tr('New device')}</h3>
    <div class="row"><label for="lf-name">${tr('Device')}</label><input id="lf-name" maxlength="100" autocomplete="off" placeholder="${esc(tr('e.g. Washing machine, laptop, e-bike'))}"></div>
    <div class="row"><label for="lf-model">${tr('Model')}</label><input id="lf-model" maxlength="100" autocomplete="off" placeholder="${esc(tr('optional'))}"></div>
    <div class="row"><label>${tr('Bought on')}</label>${dateIn('lf-bought', today(), {label: tr('Bought on'), empty: tr('optional')})}</div>
    <div class="row"><label>${tr('Warranty until')}</label>${dateIn('lf-warr', addDays(today(), 730), {label: tr('Warranty until'), empty: tr('none')})}</div>
    <div class="row"><label for="lf-lead">${tr('Remind me')}</label><select id="lf-lead">${leadOpts(30)}</select></div>
    ${lifeListOpts('home')}
    <div class="shint lhint keep">${tr('Attach the receipt to the task, so it is at hand when something breaks.')}</div>
    ${lifeFoot()}`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    if (!v('#lf-name')) { $('#lf-name', md).focus(); throw new Error(tr('Please enter a name')); }
    const t = await rawFetch('POST', '/api/life/devices', {name: v('#lf-name'), model: v('#lf-model'), ...(v('#lf-bought') ? {bought: v('#lf-bought')} : {}),
      ...(v('#lf-warr') ? {warranty: v('#lf-warr')} : {}), lead_days: +v('#lf-lead'), ...(v('#lf-list') ? {list_id: +v('#lf-list')} : {})});
    return lifeDone(md, t);
  }, '#lf-name');
}
async function upkeepModal() {
  let pre = [];
  try { pre = (await api('GET', '/api/life/upkeep-presets')).presets; } catch { /* without suggestions */ }
  const md = lifeModal(`<h3>${ic('repeat', 's')} ${tr('Upkeep')}</h3>
    ${pre.length ? `<div class="lpre" role="group" aria-label="${esc(tr('Suggestions'))}">${pre.map(p => `<button type="button" class="tagchip" data-pre="${esc(p.key)}">${esc(p.title)}</button>`).join('')}</div>` : ''}
    <div class="row"><label for="lf-title">${tr('What')}</label><input id="lf-title" maxlength="200" autocomplete="off" placeholder="${esc(tr('e.g. Service the heating'))}"></div>
    <div class="row"><label for="lf-every">${tr('Every')}</label><select id="lf-every">${[1, 2, 3, 6, 12, 24, 36, 60].map(n => `<option value="${n}" ${n === 12 ? 'selected' : ''}>${trn('{0} month', '{0} months', n)}</option>`).join('')}</select></div>
    <div class="row"><label>${tr('Next time')}</label>${dateIn('lf-next', today(), {label: tr('Next time'), clear: false})}</div>
    <div class="row"><label for="lf-lead">${tr('Remind me')}</label><select id="lf-lead">${leadOpts(7)}</select></div>
    ${lifeListOpts('home')}
    ${lifeFoot()}`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    if (!v('#lf-title')) { $('#lf-title', md).focus(); throw new Error(tr('Please enter a title')); }
    const t = await rawFetch('POST', '/api/life/upkeep', {title: v('#lf-title'), every_months: +v('#lf-every'), next: v('#lf-next') || today(), lead_days: +v('#lf-lead'),
      ...(v('#lf-list') ? {list_id: +v('#lf-list')} : {})});
    return lifeDone(md, t);
  }, '#lf-title');
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-pre]'); if (!b) return;
    const p = pre.find(x => x.key === b.dataset.pre); if (!p) return;
    $('#lf-title', md).value = p.title; $('#lf-every', md).value = String(p.every_months);
    $$('[data-pre]', md).forEach(x => x.setAttribute('aria-pressed', x === b));
  });
}
function healthModal() {
  let type = 'appointment';
  const md = lifeModal(`<h3>${ic('heart', 's')} ${tr('Health entry')}</h3>
    <div class="ptcards ltypes" role="radiogroup" aria-label="${esc(tr('Kind'))}">${HEALTH_TYPES.map(([k, n, e], j) => `<button type="button" class="ptcard ${j ? '' : 'on'}" role="radio" aria-checked="${!j}" data-ht="${k}">${ic(e)}<b>${tr(n)}</b></button>`).join('')}</div>
    <div class="row"><label for="lf-title">${tr('What')}</label><input id="lf-title" maxlength="200" autocomplete="off"></div>
    <div class="row"><label for="lf-who">${tr('For whom')}</label><input id="lf-who" maxlength="100" autocomplete="off" placeholder="${esc(tr('optional, e.g. Lina'))}"></div>
    <div class="row lh-day"><label id="lf-dayl">${tr('Date')}</label>${dateIn('lf-day', today(), {label: tr('Date'), clear: false})}</div>
    <div class="row lh-time"><label>${tr('Time')}</label>${timeIn('lf-time', '', {label: tr('Time'), empty: tr('none')})}</div>
    <div class="row lh-every" hidden><label for="lf-every">${tr('Repeat')}</label><select id="lf-every">${[[0, tr('once')], [6, tr('every 6 months')], [12, tr('every year')], [24, tr('every 2 years')], [36, tr('every 3 years')], [60, tr('every 5 years')], [120, tr('every 10 years')]].map(([v, w]) => `<option value="${v}">${esc(w)}</option>`).join('')}</select></div>
    <div class="row lh-times" hidden><label for="lf-times">${tr('Times')}</label><input id="lf-times" value="08:00, 20:00" placeholder="08:00, 20:00" autocomplete="off"></div>
    ${lifeListOpts('health')}
    <div class="shint lhint keep">${ic('lock', 's')} ${tr('Health entries live in a private project: agents never see it, API tokens only with the permission “Health & journal”.')}</div>
    ${lifeFoot()}`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    if (!v('#lf-title')) { $('#lf-title', md).focus(); throw new Error(tr('Please enter a title')); }
    const b = {type, title: v('#lf-title'), who: v('#lf-who'), date: v('#lf-day') || today(), ...(v('#lf-list') ? {list_id: +v('#lf-list')} : {})};
    if (type === 'medication') b.times = v('#lf-times').split(/[,;\s]+/).filter(Boolean).map(x => /^\d:/.test(x) ? '0' + x : x);
    else { if (v('#lf-time')) b.time = v('#lf-time'); if (type !== 'appointment') b.every_months = +v('#lf-every'); }
    const j = await rawFetch('POST', '/api/life/health', b);
    return lifeDone(md, j.tasks[0], j.tasks.length > 1 ? trn('{0} reminder added', '{0} reminders added', j.tasks.length) : null);
  }, '[data-ht="appointment"]');
  const sync = () => {
    $('.lh-every', md).hidden = !['checkup', 'vaccination'].includes(type);
    $('.lh-times', md).hidden = type !== 'medication'; $('.lh-time', md).hidden = type === 'medication';
    $('#lf-dayl', md).textContent = type === 'medication' ? tr('From') : type === 'vaccination' ? tr('Next due') : tr('Date');
    $('#lf-title', md).placeholder = {appointment: tr('e.g. Dentist'), checkup: tr('e.g. Check-up at the GP'), vaccination: tr('e.g. Tetanus booster'), medication: tr('e.g. Vitamin D')}[type];
    if (type === 'vaccination' && $('#lf-every', md).value === '0') $('#lf-every', md).value = '120';
    if (type === 'checkup' && $('#lf-every', md).value === '0') $('#lf-every', md).value = '12';
  };
  sync();
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-ht]'); if (!b) return;
    type = b.dataset.ht; $$('[data-ht]', md).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); }); sync();
  });
}
function tripModal(l) {
  const tp = l?.trip || {};
  const md = lifeModal(`<h3>${ic('plane', 's')} ${l ? tr('Edit trip') : tr('New trip')}</h3>
    <div class="row"><label for="lf-name">${tr('Trip')}</label><input id="lf-name" maxlength="100" autocomplete="off" value="${esc(l?.name || '')}" placeholder="${esc(tr('e.g. Summer in Italy'))}"></div>
    <div class="row"><label for="lf-where">${tr('Where to')}</label><input id="lf-where" maxlength="100" autocomplete="off" value="${esc(tp.where || '')}" placeholder="${esc(tr('optional'))}"></div>
    <div class="row"><label>${tr('From')}</label>${dateIn('lf-from', tp.from || addDays(today(), 30), {label: tr('From'), clear: false})}</div>
    <div class="row"><label>${tr('To')}</label>${dateIn('lf-to', tp.to || addDays(today(), 37), {label: tr('To'), clear: false})}</div>
    ${l ? '' : `<div class="row"><label for="lf-pack">${tr('Packing list')}</label><select id="lf-pack"><option value="">${tr('None')}</option>${PACK_UI.map(([k, n, e]) => `<option value="${k}" ${k === 'holiday' ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select></div>
    ${feat('events') ? `<div class="row"><label>${tr('Calendar')}</label><label class="chkl"><input type="checkbox" id="lf-ev" checked> ${tr('Add the trip as an all-day event')}</label></div>` : ''}`}
    ${lifeFoot(l ? tr('Save') : tr('Create'))}`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    if (!v('#lf-name')) { $('#lf-name', md).focus(); throw new Error(tr('Please enter a name')); }
    if (v('#lf-to') < v('#lf-from')) throw new Error(tr('The end must be after the start'));
    const trip = {from: v('#lf-from'), to: v('#lf-to'), ...(v('#lf-where') ? {where: v('#lf-where')} : {})};
    if (l) { await rawFetch('PATCH', `/api/lists/${l.id}`, {name: v('#lf-name'), trip}); md.remove(); await load(); render(); return; }
    const j = await rawFetch('POST', '/api/life/trips', {name: v('#lf-name'), ...trip, packing: v('#lf-pack'), event: !!$('#lf-ev', md)?.checked, space: lf_sp()});  // 2.173.0 A (#2680): in the shown space
    md.remove(); await load(); LF.data = null; go('l/' + j.list_id); toast(tr('Trip created: {0}', v('#lf-name')));
  }, '#lf-name');
  return md;
}
// 2.173.0 A (#2680): "Travel expenses" on a trip -- one trip of the office made from it (period, destination, name), later
// the same one opened (kalmido/life/tripcost.py); for who makes travel expenses there: the admins of the trip's organisation,
// a private trip in the person's own office. No costs in the trip planning itself.
const lf_costOk = l => typeof officeOn === 'function' && officeOn() && (!l.org_id || wsOrg(l.org_id)?.role === 'admin');
async function lf_tripCost(lid) {
  const l = listById(lid); if (!l) return;
  let j; try { j = await api('POST', `/api/life/trips/${lid}/expenses`, {}); } catch { return; }  // api() said it
  const ws = wsOf(l);
  if (wsOn() && wsCur() !== ws && wsOptions().includes(ws)) await wsSet(ws);  // the office of the trip's space
  LF_COST[lid] = j.trip_id;  // 2.173.1 A (#2714)
  window.lf_rkOpen = {trip: j.trip_id, office: j.office_id};  // office_travel.js opens it once that office is loaded
  go('office/travel');
  if (j.created) toast(tr('Travel expenses created for {0}', l.name));
}
// 2.173.1 A (#2714): the button tells whether travel expenses are linked already (asked once per trip and load, quietly)
const LF_COST = {};  // lid -> office trip id | null; undefined = not asked yet
function lf_costBtn(l) {
  if (LF_COST[l.id] === undefined) {
    LF_COST[l.id] = null;
    rawFetch('GET', `/api/life/trips/${l.id}/expenses`).then(j => {
      if (!j?.trip_id) return;
      LF_COST[l.id] = j.trip_id;
      const b = document.querySelector(`[data-act="life-tripcost"][data-lid="${l.id}"]`); if (b) b.outerHTML = lf_costBtn(l);
    }).catch(() => {});
  }
  const on = !!LF_COST[l.id];
  return `<button type="button" class="btn sm" data-act="life-tripcost" data-lid="${l.id}">${ic(on ? 'check' : 'receipt', 's')}<span>${on ? tr('Open travel expenses') : tr('Travel expenses')}</span></button>`;
}
// the list bar of a trip / a contracts, home, health or reading list (like the Family list bars)
function lifeBar(l) {
  if (!l?.life || l.archived || !feat({contracts: 'contracts', home: 'home', health: 'health', travel: 'travel', reading: 'reading'}[l.life])) return '';
  if (l.life === 'travel') {
    const t = l.trip; if (!t) return '';
    const n = daysTo(t.from);
    return `<div class="fambar lifebar">${ic('plane', 's')}<span class="ltrip"><b>${esc([t.where, fmtDateLoc(t.from) + ' – ' + fmtDateLoc(t.to)].filter(Boolean).join(' · '))}</b>${n > 0 ? `<span class="muted"> · ${esc(daysWord(n))}</span>` : ''}</span><span class="spacer"></span>${lf_costOk(l) ? lf_costBtn(l) : ''}${canEditList(l.id) && l.role === 'owner' ? `<button type="button" class="btn sm" data-act="life-tripedit" data-lid="${l.id}">${ic('edit', 's')}<span>${tr('Edit trip')}</span></button>` : ''}</div>`;
  }
  const b = {contracts: ['life-contract', 'file', N_('Contract')], home: ['life-device', 'tool', N_('Device')], health: ['life-health', 'heart', N_('Health entry')], reading: ['', 'book', '']}[l.life];
  return `<div class="fambar lifebar">${b[0] ? `<button type="button" class="btn" data-act="${b[0]}">${ic(b[1], 's')}<span>${tr(b[2])}</span></button>` : ''}${l.life === 'health' ? `<span class="muted">${ic('lock', 's')} ${tr('Private: never visible to agents')}</span>` : ''}<span class="spacer"></span>${l.life === 'reading' ? `<a class="btn" href="#reading">${ic('book', 's')}<span>${tr('Read later')}</span></a>` : `<a class="btn" href="#life">${ic('home', 's')}<span>${tr('Home & life')}</span></a>`}</div>`;  // 2.172.0 B (#2679): a read-later project -> its view
}
// Karakeep: connect, choose the list, fetch
async function kkModal() {
  let cur = {connected: false};
  try { cur = await api('GET', '/api/life/karakeep'); } catch { return; }
  const rl = S.lists.filter(l => l.life === 'reading' && !l.archived && canEditList(l.id));
  const md = lifeModal(`<h3>${ic('book', 's')} ${tr('Karakeep')}</h3>
    <p class="muted">${tr('Links you save in Karakeep become bookmarks, notes become tasks of your “Read later” project; archived bookmarks and ticked tasks are archived in Karakeep.')}</p>
    <div class="row"><label for="kk-url">${tr('Address')}</label><input id="kk-url" type="url" inputmode="url" autocomplete="off" value="${esc(cur.url || '')}" placeholder="https://karakeep.example.com"></div>
    <div class="row"><label for="kk-tok">${tr('API key')}</label><input id="kk-tok" type="password" autocomplete="new-password" placeholder="${esc(cur.token_set ? tr('saved – enter a new one to replace it') : tr('Karakeep > Settings > API keys'))}"></div>
    ${rl.length > 1 ? `<div class="row"><label for="kk-list">${tr('Project')}</label><select id="kk-list">${rl.map(l => `<option value="${l.id}" ${l.id === cur.list_id ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>` : ''}
    <div class="row"><label>${tr('When ticked')}</label><label class="chkl"><input type="checkbox" id="kk-arch" ${cur.connected && !cur.archive ? '' : 'checked'}> ${tr('archive the bookmark in Karakeep')}</label></div>
    ${cur.error ? `<p class="aerr">${esc(cur.error)}</p>` : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot">${cur.connected ? `<button class="btn danger" data-m="kk-del">${tr('Disconnect')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${cur.connected ? tr('Save') : tr('Connect')}</button></div>`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    const b = {url: v('#kk-url'), archive: !!$('#kk-arch', md).checked, ...(v('#kk-tok') ? {token: v('#kk-tok')} : {}), ...(v('#kk-list') ? {list_id: +v('#kk-list')} : {})};
    if (!b.url) { $('#kk-url', md).focus(); throw new Error(tr('Please enter the address')); }
    if (!cur.token_set && !b.token) { $('#kk-tok', md).focus(); throw new Error(tr('Please enter the API key')); }
    await rawFetch('PUT', '/api/life/karakeep', b);
    const j = await rawFetch('POST', '/api/life/karakeep/sync', {});
    md.remove(); await load(); lifeReload(); toast(trn('{0} bookmark fetched', '{0} bookmarks fetched', j.added));
  }, '#kk-url');
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-m="kk-del"]')) {
      if (!await askConfirm(tr('Disconnect Karakeep?'), tr('The API key is removed; the tasks stay.'), {ok: tr('Disconnect'), danger: true})) return;
      try { await api('DELETE', '/api/life/karakeep'); } catch { return; }
      md.remove(); lifeReload();
    }
  });
}

// ---- a task of Home & life in the task panel
function lifeDetailHtml(t, l, ro) {
  if (!t || t.id <= 0 || t.context || !isLifeTask(t)) return '';
  const f = t.fam, k = f.kind, rows = [];
  const row = (label, val) => `<div class="row"><label>${esc(label)}</label><span>${val}</span></div>`;
  if (k === 'contract') {
    const end = t.due ? lifeEnd(t.due, f.notice || 0, f.nu || 'm') : '';
    if (f.provider) rows.push(row(tr('Provider'), esc(f.provider)));
    if (f.cost != null) rows.push(row(tr('Cost'), esc(fmtMoney(f.cost) + ' ' + tr(PERIOD_WORD[f.per || 'month']))));
    if (end) rows.push(row(tr('Current term ends'), esc(fmtDateLoc(end))));
    rows.push(row(tr('Notice period'), esc(noticeWord(f.notice || 0, f.nu))));
    const rn = lifeRenew(t.repeat); rows.push(row(tr('Then'), esc(!rn ? tr('it ends') : rn === 12 ? tr('renews every year') : trn('renews every {0} month', 'renews every {0} months', rn))));
    if (f.account) rows.push(row(tr('Paid from'), esc(f.account)));
    if (!ro && feat('contracts')) rows.push(`<div class="row"><span></span><span class="lacts"><button type="button" class="btn sm" data-act="life-cedit" data-id="${t.id}">${ic('edit', 's')}<span>${tr('Edit contract')}</span></button><button type="button" class="btn sm" data-act="life-cancelled" data-id="${t.id}">${ic('x', 's')}<span>${tr('Cancelled|contract')}</span></button></span></div>`);
  } else if (k === 'device') {
    if (f.model) rows.push(row(tr('Model'), esc(f.model)));
    if (f.bought) rows.push(row(tr('Bought on'), esc(fmtDateLoc(f.bought))));
    if (f.warranty) rows.push(row(tr('Warranty until'), esc(fmtDateLoc(f.warranty))));
    if (f.serial) rows.push(row(tr('Serial number'), esc(f.serial)));  // 2.140.0 B (#2136): serial, price, the office link (devlink.js)
    if (f.price != null) rows.push(row(tr('Price'), esc(fmtMoney(f.price))));
    if (typeof dlDeviceHtml === 'function') rows.push(dlDeviceHtml(t, ro));
  } else if (k === 'upkeep') {
    const rn = lifeRenew(t.repeat); if (rn) rows.push(row(tr('Every'), esc(trn('{0} month', '{0} months', rn))));
  } else if (k === 'health') {
    const ty = HEALTH_TYPES.find(x => x[0] === f.type) || HEALTH_TYPES[0];
    rows.push(row(tr('Kind'), ic(ty[2], 's') + ' ' + esc(tr(ty[1])) + (f.who ? ' · ' + esc(f.who) : '')));
    rows.push(`<div class="row"><span></span><span class="muted">${ic('lock', 's')} ${tr('Private: never visible to agents')}</span></div>`);
  } else if (k === 'bookmark') {
    rows.push(row(tr('From'), esc('Karakeep') + (f.arch ? ' · ' + esc(tr('archived')) : '')));
  }
  const head = {contract: N_('Contract'), device: N_('Device'), upkeep: N_('Upkeep'), health: N_('Health'), bookmark: N_('Read later')}[k];
  return rows.length ? `<div class="dsec lifesec"><h5>${tr(head)}</h5><div class="famf">${rows.join('')}</div></div>` : '';
}

// ---- staying in touch on a contact's card
const CARE_EVERY = [[0, N_('off')], [14, N_('every 2 weeks')], [30, N_('every month')], [61, N_('every 2 months')], [91, N_('every 3 months')], [182, N_('every 6 months')], [365, N_('every year')]];
function lifeCareHtml(c) {
  if (!feat('care') || !c) return '';
  const bo = (S.books || []).find(b => b.id === c.book_id)?.org_id;  // 2.173.0 A (#2680): not for guests / read-only of the book's organisation
  if (bo && ['readonly', 'guest', 'accounting'].includes(wsOrg(bo)?.role)) return '';
  const cr = c.care || {every_days: 0, last: null, note: ''};
  const opts = CARE_EVERY.some(x => x[0] === cr.every_days) ? CARE_EVERY : [...CARE_EVERY, [cr.every_days, trn('every {0} day', 'every {0} days', cr.every_days)]];
  return `<div class="ctsec ctcare"><h4>${tr('Stay in touch')}</h4>
    <div class="row"><label for="ct-care">${tr('How often')}</label><select id="ct-care" data-cid="${c.id}">${opts.map(([v, w]) => `<option value="${v}" ${v === cr.every_days ? 'selected' : ''}>${esc(typeof w === 'string' && CARE_EVERY.some(x => x[1] === w) ? tr(w) : w)}</option>`).join('')}</select></div>
    <div class="row"><label>${tr('Last contact')}</label><span class="lacts"><span>${esc(cr.last ? fmtDateLoc(cr.last) : tr('not noted yet'))}</span><button type="button" class="btn sm" data-act="life-touch" data-cid="${c.id}">${ic('check', 's')}<span>${tr('In touch today')}</span></button></span></div>
    <div class="row"><label for="ct-cnote">${tr('Note')}</label><input id="ct-cnote" data-cid="${c.id}" maxlength="500" value="${esc(cr.note || '')}" placeholder="${esc(tr('e.g. what you talked about last time'))}"></div></div>`;
}
async function careSet(cid, body) {
  try {
    const cr = await api('PUT', `/api/contacts/${cid}/care`, body);
    if (typeof CT === 'object' && CT.card?.id === cid) { CT.card = {...CT.card, care: cr}; ctDraw(); }  // 2.53.0 (#1410): contacts.js loads on demand
    LF.data = null; if (S.route.mod === 'life') lifeLoad();
    return cr;
  } catch { return null; }
}
document.addEventListener('change', e => {
  const el = e.target;
  if (el.id === 'ct-care') careSet(+el.dataset.cid, {every_days: +el.value});
  else if (el.id === 'ct-cnote') careSet(+el.dataset.cid, {note: el.value});
  else if (el.matches?.('[data-lf-space]')) { LF.space = el.value; LF.data = null; lifeLoad(); }  // 2.173.0 A (#2680)
});

// ---- the review: the day or week, the journal
async function rvLoad() {
  const seq = ++RV.seq;
  RV.loading = true;
  try { const j = await api('GET', `/api/life/review?period=${RV.period}&date=${RV.date || today()}`); if (seq === RV.seq) RV.data = j; } catch { if (seq === RV.seq) RV.data = RV.data || null; }
  RV.loading = false;
  if (S.route.mod === 'review' && seq === RV.seq) { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('review', viewReview()))); }
}
function viewReview() {
  RV.date = RV.date || today();
  if (RV.period === 'hist') return viewJournalHist();  // 2.140.0 C (#2133)
  const r = RV.data;
  if ((!r || r.period !== RV.period || !(r.from <= RV.date && RV.date <= r.to)) && !RV.loading) setTimeout(rvLoad, 0);
  const seg = `<div class="seg" role="radiogroup" aria-label="${esc(tr('Period'))}">${[['day', tr('Day')], ['week', tr('Week')], ['hist', tr('History')]].map(([k, w]) => `<button type="button" role="radio" data-act="rv-period" data-p="${k}" class="${RV.period === k ? 'on' : ''}" aria-checked="${RV.period === k}">${esc(w)}</button>`).join('')}</div>`;
  const label = !r ? '' : r.from === r.to ? fmtDayAbs(r.from) : fmtDayAbs(r.from) + ' – ' + fmtDayAbs(r.to);
  const nav = `<span class="fwnav"><button type="button" class="iconbtn" data-act="rv-move" data-d="-1" aria-label="${esc(RV.period === 'week' ? tr('Previous week') : tr('Previous day'))}" title="${esc(RV.period === 'week' ? tr('Previous week') : tr('Previous day'))}">${ic('left', 's')}</button><b class="rvlab" aria-live="polite">${esc(label)}</b><button type="button" class="iconbtn" data-act="rv-move" data-d="1" aria-label="${esc(RV.period === 'week' ? tr('Next week') : tr('Next day'))}" title="${esc(RV.period === 'week' ? tr('Next week') : tr('Next day'))}">${ic('right', 's')}</button>${RV.date !== today() ? `<button type="button" class="btn sm" data-act="rv-today">${tr('Today')}</button>` : ''}</span>`;
  const head = `<div class="dashhead rvhead">${seg}${nav}<span class="spacer"></span>${lyCustomBtn('review')}</div>`;  // 2.43.0 (#1452)
  if (!r) return `<div class="dash review">${head}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  const li = (arr, f) => arr.length ? `<ul class="flist">${arr.slice(0, 30).map(f).join('')}</ul>${arr.length > 30 ? `<p class="muted">${esc(trn('and {0} more', 'and {0} more', arr.length - 30))}</p>` : ''}` : '';
  const tl = x => `<a href="#t/${x.task_id}" class="frow"><span class="ft"><b>${esc(x.title)}</b><span class="muted">${esc(lname(listById(x.list_id)) || '')}</span></span>${x.due ? `<span class="fwhen rvwhen">${esc(dayLabel(x.due))}</span>` : ''}</a>`;  // 2.223.0 B (#2822): the date as in the task list
  const card = (k, icon, title, body, n) => `<section class="dcard fcard lcard rv-${k}" aria-labelledby="rvh-${k}"><h2 id="rvh-${k}">${ic(icon, 's')}<span>${esc(title)}</span><span class="dcn">${n}</span></h2>${body}</section>`;
  const days = r.period === 'week' ? [...Array(7)].map((_, i) => addDays(r.from, i)) : [r.from];
  const jsel = days.includes(RV.edit) ? RV.edit : days.includes(today()) ? today() : days[days.length - 1];
  const je = (r.journal || []).find(x => x.day === jsel) || {text: '', mood: null};
  const jdays = r.period === 'week' ? `<div class="rvjdays" role="tablist" aria-label="${esc(tr('Day'))}">${days.map(d => { const has = (r.journal || []).some(x => x.day === d); return `<button type="button" role="tab" data-act="rv-jday" data-day="${d}" class="${d === jsel ? 'on' : ''} ${has ? 'has' : ''}" aria-selected="${d === jsel}" ${d > addDays(today(), 1) ? 'disabled' : ''}>${esc(WD[pd(d).getDay()] + ' ' + pd(d).getDate())}</button>`; }).join('')}</div>` : '';
  const journal = r.journal ? `<section class="dcard fcard lcard rvjournal" aria-labelledby="rvh-j"><h2 id="rvh-j">${ic('journal', 's')}<span>${tr('Journal')}</span><span class="spacer"></span><span class="muted rvsaved" aria-live="polite"></span></h2>${jdays}
    <div class="rvmood" role="radiogroup" aria-label="${esc(tr('How was the day?'))}">${MOODS.map(([v, e, w]) => `<button type="button" role="radio" data-act="rv-mood" data-v="${v}" class="${je.mood === v ? 'on' : ''}" aria-checked="${je.mood === v}" title="${esc(tr(w))}" aria-label="${esc(tr(w))}">${e}</button>`).join('')}</div>
    <textarea id="rv-text" data-day="${jsel}" rows="6" maxlength="20000" placeholder="${esc(tr('What happened, what went well, what is on your mind?'))}" aria-label="${esc(tr('Journal of {0}', fmtDayAbs(jsel)))}">${esc(je.text)}</textarea>
    <p class="muted rvpriv">${ic('lock', 's')} ${tr('Only you can read your journal.')}</p></section>` : '';
  // 2.43.0 (#1452): the cards are blocks of the view builder (width, height, order, hide at their "…" menu)
  return `<div class="dash fam review">${head}${lyHtml('review', {
    done: card('done', 'done', tr('Done'), li(r.done, x => `<li>${tl(x)}</li>`) || `<p class="muted">${tr('Nothing ticked off yet.')}</p>`, r.done.length),
    open: card('open', 'alert', tr('Still open'), li(r.open, x => `<li>${tl(x)}</li>`) || `<p class="muted">${tr('Nothing left over.')}</p>`, r.open.length),
    moved: r.moved.length ? card('moved', 'skip', tr('Moved'), li(r.moved, x => `<li>${tl(x)}</li>`), r.moved.length) : '',
    next: card('next', 'cal', tr('Coming up'), li(r.next, x => `<li>${tl(x)}</li>`) || `<p class="muted">${tr('Nothing due in the next seven days.')}</p>`, r.next.length),
    ...(r.journal ? {journal} : {})})}</div>`;
}
// ---- 2.140.0 C (#2133): the journal history: all entries (newest first), search, mood filter, export, mood statistics
const JH = {q: '', mood: 0, days: 30, from: '', to: '', items: [], next: null, loaded: false, loading: false, stats: null, seq: 0, t: null};
const jhParams = () => { const p = new URLSearchParams(); if (JH.q) p.set('q', JH.q); if (JH.mood) p.set('mood', JH.mood); if (JH.from) p.set('from', JH.from); if (JH.to) p.set('to', JH.to); return p; };
const jhMood = v => (MOODS.find(m => m[0] === v) || [])[1] || '';
function jhHit(text) {  // a short excerpt around the first match, the match marked
  const q = JH.q.toLowerCase(), low = text.toLowerCase(), i = q ? low.indexOf(q) : -1;
  const a = Math.max(0, i > 60 ? i - 60 : 0), part = text.slice(a, a + 220);
  const pre = a ? '… ' : '', post = a + 220 < text.length ? ' …' : '';
  if (i < 0) return esc(pre + part + post);
  const k = i - a;
  return esc(pre) + esc(part.slice(0, k)) + '<mark>' + esc(part.slice(k, k + q.length)) + '</mark>' + esc(part.slice(k + q.length) + post);
}
function jhListHtml() {
  if (!JH.loaded) return `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (!JH.items.length) return `<p class="muted lempty">${JH.q || JH.mood || JH.from || JH.to ? tr('No entries found.') : tr('No journal entries yet.')}</p>`;
  return `<ul class="jhlist">${JH.items.map(x => `<li><button type="button" class="jhrow" data-act="rv-hopen" data-day="${x.day}"><span class="jhd"><b>${esc(fmtDayAbs(x.day))}</b><span class="jhm" aria-hidden="true">${jhMood(x.mood)}</span></span><span class="jhtx">${jhHit(x.text || '')}</span></button></li>`).join('')}</ul>`
    + (JH.next ? `<p><button type="button" class="btn sm" data-act="rv-hmore" ${JH.loading ? 'disabled' : ''}>${tr('Load more')}</button></p>` : '');
}
function jhStatsHtml() {
  const s = JH.stats;
  const seg = `<div class="seg" role="radiogroup" aria-label="${esc(tr('Period'))}">${[30, 90, 365].map(n => `<button type="button" role="radio" data-act="rv-hdays" data-n="${n}" class="${JH.days === n ? 'on' : ''}" aria-checked="${JH.days === n}">${esc(trn('{0} day', '{0} days', n))}</button>`).join('')}</div>`;
  if (!s) return seg + `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (!s.rated) return seg + `<p class="muted lempty">${tr('No moods in this period.')}</p>`;
  const mx = Math.max(1, ...Object.values(s.dist));
  const bars = MOODS.map(([v, e, w]) => `<div class="jhbar" title="${esc(tr(w))}"><span aria-hidden="true">${e}</span><span class="jhtrack"><i style="width:${Math.round(100 * s.dist[v] / mx)}%"></i></span><span class="mono">${s.dist[v]}</span></div>`).join('');
  const n = s.series.length, pts = s.series.map((x, i) => [n > 1 ? 8 + 284 * i / (n - 1) : 150, 92 - (x.avg - 1) * 21]);
  const line = `<svg class="jhline" viewBox="0 0 300 100" preserveAspectRatio="none" role="img" aria-label="${esc(tr('Average mood over time'))}"><polyline fill="none" vector-effect="non-scaling-stroke" points="${pts.map(p => p.join(',')).join(' ')}"/>${pts.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="2.5"/>`).join('')}</svg>`;
  const lab = s.period === 'month' ? tr('Average per month') : tr('Average per week');
  return `${seg}<p class="jhavg"><b>${fmtNum(s.avg, 1)}</b> <span class="muted">${esc(tr('average of {0} rated days', s.rated))}</span></p><div class="jhbars">${bars}</div><p class="muted jhlab">${esc(lab)}</p>${line}`;
}
function viewJournalHist() {
  if (!JH.loaded && !JH.loading) setTimeout(() => { jhLoad(); jhStats(); }, 0);
  const seg = `<div class="seg" role="radiogroup" aria-label="${esc(tr('Period'))}">${[['day', tr('Day')], ['week', tr('Week')], ['hist', tr('History')]].map(([k, w]) => `<button type="button" role="radio" data-act="rv-period" data-p="${k}" class="${RV.period === k ? 'on' : ''}" aria-checked="${RV.period === k}">${esc(w)}</button>`).join('')}</div>`;
  const exp = f => `/api/life/journal/export?format=${f}${JH.from ? '&from=' + JH.from : ''}${JH.to ? '&to=' + JH.to : ''}`;
  const moods = `<div class="rvmood jhmoods" role="radiogroup" aria-label="${esc(tr('Mood'))}"><button type="button" class="btn sm ${JH.mood ? '' : 'on'}" role="radio" data-act="rv-hmood" data-v="0" aria-checked="${!JH.mood}">${tr('All')}</button>${MOODS.map(([v, e, w]) => `<button type="button" role="radio" data-act="rv-hmood" data-v="${v}" class="${JH.mood === v ? 'on' : ''}" aria-checked="${JH.mood === v}" title="${esc(tr(w))}" aria-label="${esc(tr(w))}">${e}</button>`).join('')}</div>`;
  return `<div class="dash fam review jhist"><div class="dashhead rvhead">${seg}<span class="spacer"></span></div>
    <section class="dcard fcard lcard" aria-labelledby="jh-h"><h2 id="jh-h">${ic('journal', 's')}<span>${tr('Journal')}</span></h2>
      <div class="jhsearch"><input type="search" id="jh-q" value="${esc(JH.q)}" maxlength="200" placeholder="${esc(tr('Search the journal'))}" aria-label="${esc(tr('Search the journal'))}" enterkeyhint="search"></div>
      ${moods}
      <div class="jhrange"><label>${tr('From')} ${dateIn('jh-from', JH.from, {label: tr('From'), empty: tr('any')})}</label><label>${tr('To')} ${dateIn('jh-to', JH.to, {label: tr('To'), empty: tr('any')})}</label></div>
      <div id="jh-list">${jhListHtml()}</div>
      <div class="fcfoot"><span class="muted">${tr('Download')}</span><a class="btn sm" href="${esc(exp('md'))}" download>${ic('download', 's')} Markdown</a><a class="btn sm" href="${esc(exp('csv'))}" download>${ic('download', 's')} CSV</a></div>
      <p class="muted rvpriv">${ic('lock', 's')} ${tr('Only you can read your journal.')}</p></section>
    <section class="dcard fcard lcard" aria-labelledby="jh-s"><h2 id="jh-s">${ic('chart', 's')}<span>${tr('Mood')}</span></h2><div id="jh-stats">${jhStatsHtml()}</div></section></div>`;
}
const jhDrawList = () => { const el = $('#jh-list'); if (el && S.route.mod === 'review' && RV.period === 'hist') setHtml(el, jhListHtml()); };
async function jhLoad(more) {
  const seq = ++JH.seq; JH.loading = true;
  if (!more) { JH.items = []; JH.next = null; JH.loaded = false; jhDrawList(); }
  const p = jhParams(); if (more && JH.next) p.set('before', JH.next);
  try {
    const j = await api('GET', '/api/life/journal?' + p);
    if (seq !== JH.seq) return;
    JH.items = more ? [...JH.items, ...j.entries] : j.entries; JH.next = j.next;
  } catch { if (seq !== JH.seq) return; }
  JH.loaded = true; JH.loading = false; jhDrawList();
}
async function jhStats() {
  try { JH.stats = await api('GET', '/api/life/journal/stats?days=' + JH.days); } catch { JH.stats = null; return; }
  const el = $('#jh-stats'); if (el && RV.period === 'hist') setHtml(el, jhStatsHtml());
}
document.addEventListener('input', e => {
  if (e.target.id !== 'jh-q') return;
  clearTimeout(JH.t); JH.t = setTimeout(() => { JH.q = e.target.value.trim(); jhLoad(); }, 300);
});
document.addEventListener('change', e => {
  if (e.target.id !== 'jh-from' && e.target.id !== 'jh-to') return;
  JH[e.target.id === 'jh-from' ? 'from' : 'to'] = e.target.value; jhLoad();
  $$('.jhist a[download]').forEach(a => { a.href = a.href.replace(/&(from|to)=[^&]*/g, '') + (JH.from ? '&from=' + JH.from : '') + (JH.to ? '&to=' + JH.to : ''); });
});
// 2.269.0 C (#3017): one save after the other (each one's base = the answer of the one before) with expect_updated_at ("" = no
// entry seen): written on the other device meanwhile -> 409, the bar offers "Reload" instead of overwriting
function rvSave(day, patch) { RV.chain = (RV.chain || Promise.resolve()).then(() => rvSave0(day, patch)); return RV.chain; }
async function rvSave0(day, patch) {
  const r = RV.data; if (!r?.journal) return;
  const cur = r.journal.find(x => x.day === day) || {day, text: '', mood: null, updated_at: ''};
  const next = {...cur, ...patch};
  try {
    const j = await rawFetch('PUT', `/api/life/journal/${day}`, {text: next.text, mood: next.mood, expect_updated_at: cur.updated_at || ''});
    r.journal = [...r.journal.filter(x => x.day !== day), ...(j.text || j.mood ? [j] : [])].sort((a, b) => a.day.localeCompare(b.day));
    const s = $('.rvsaved'); if (s) s.textContent = tr('Saved');
  } catch (x) {
    if (x.status === 409 && x.data?.entry) { rv_conflict(r, x.data.entry); return; }
    if (x.message !== 'auth') toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message);
  }
}
function rv_conflict(r, theirs) {
  const s = $('.rvsaved'); if (!s) { toast(tr('Changed in the meantime')); return; }
  s.innerHTML = `${esc(tr('Changed in the meantime'))} · ${esc(tr('Reload shows the saved version; your input here is not saved.'))} <button type="button" class="btn sm" data-rv-reload>${tr('Reload')}</button>`;
  $('[data-rv-reload]', s).addEventListener('click', ev => {
    ev.stopPropagation(); clearTimeout(RV.t); RV.t = null;
    r.journal = [...r.journal.filter(x => x.day !== theirs.day), ...(theirs.text || theirs.mood ? [theirs] : [])].sort((a, b) => a.day.localeCompare(b.day));
    renderView();
  });
}
document.addEventListener('input', e => {
  if (e.target.id !== 'rv-text') return;
  const el = e.target, s = $('.rvsaved'); if (s) s.textContent = '';
  clearTimeout(RV.t); RV.t = setTimeout(() => rvSave(el.dataset.day, {text: el.value}), 700);
});
document.addEventListener('focusout', e => { if (e.target.id === 'rv-text' && RV.t) { clearTimeout(RV.t); RV.t = null; rvSave(e.target.dataset.day, {text: e.target.value}); } });

// ---- clicks
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-act^="life-"], [data-act^="rv-"]'); if (!a || a.disabled) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act, id = +a.dataset.id || 0;
  if (k === 'life-contract') contractModal();
  else if (k === 'life-cedit') { const t = taskById(id); if (t) contractModal(t); }
  else if (k === 'life-cancelled') {
    const t = taskById(id); if (!t) return;
    if (!await askConfirm(tr('Cancelled “{0}”?', t.fam?.name || t.title), tr('The contract is ticked off and does not come back. It stays in the done tasks.'), {ok: tr('Cancelled')})) return;
    try { await api('PATCH', `/api/tasks/${id}`, {repeat: ''}); await api('POST', `/api/tasks/${id}/complete`, {}); } catch { return; }
    await load(); render(); LF.data = null; toast(tr('Contract cancelled'));
  }
  else if (k === 'life-device') deviceModal();
  else if (k === 'life-upkeep') upkeepModal();
  else if (k === 'life-health') healthModal();
  else if (k === 'life-trip') tripModal();
  else if (k === 'life-tripedit') tripModal(listById(+a.dataset.lid));
  else if (k === 'life-tripcost') { a.disabled = true; await lf_tripCost(+a.dataset.lid); a.disabled = false; }  // 2.173.0 A (#2680)
  else if (k === 'life-kk') kkModal();
  else if (k === 'life-kksync') { a.disabled = true; try { const j = await api('POST', '/api/life/karakeep/sync', {}); await load(); toast(trn('{0} bookmark fetched', '{0} bookmarks fetched', j.added)); } catch { /* api() said it */ } a.disabled = false; lifeReload(); }
  else if (k === 'life-touch') { const cr = await careSet(+a.dataset.cid, {last: 'today'}); if (cr) toast(tr('Noted: in touch today')); }
  else if (k === 'life-mods') settingsModal('modules');
  else if (k === 'rv-period') { RV.period = a.dataset.p; RV.data = null; renderView(); }
  else if (k === 'rv-move') { RV.date = addDays(RV.date || today(), (RV.period === 'week' ? 7 : 1) * +a.dataset.d); RV.edit = null; renderView(); $(`#view [data-act="rv-move"][data-d="${a.dataset.d}"]`)?.focus(); }
  else if (k === 'rv-today') { RV.date = today(); RV.edit = null; renderView(); }
  else if (k === 'rv-hopen') { RV.period = 'day'; RV.date = a.dataset.day; RV.edit = a.dataset.day; RV.data = null; renderView(); }
  else if (k === 'rv-hmore') jhLoad(true);
  else if (k === 'rv-hmood') { JH.mood = +a.dataset.v; renderView(); jhLoad(); }
  else if (k === 'rv-hdays') { JH.days = +a.dataset.n; JH.stats = null; renderView(); jhStats(); }
  else if (k === 'rv-jday') { RV.edit = a.dataset.day; renderView(); $(`#view [data-act="rv-jday"][data-day="${a.dataset.day}"]`)?.focus(); }
  else if (k === 'rv-mood') {
    const ta = $('#rv-text'), day = ta?.dataset.day; if (!day) return;
    const cur = (RV.data?.journal || []).find(x => x.day === day)?.mood, v = +a.dataset.v;
    await rvSave(day, {mood: cur === v ? null : v, text: ta.value});
    $$('[data-act="rv-mood"]').forEach(x => { const on = +x.dataset.v === (cur === v ? null : v); x.classList.toggle('on', on); x.setAttribute('aria-checked', on); });
  }
});
