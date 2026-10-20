// 2.47.0 (#1216): the shoot calculation sheet (Drehkalkulation) -- the editor of a quotation part of kind 'shoot'.
// The part editor (office_parts.js) renders dkSheetHtml(part, doc, adm) and calls dkSheetBind(root, part); every change
// is saved with PATCH /api/office/docs/<doc>/parts/<pid> {sheet} and the server's answer (sheet + calc, kalmido/office/
// sheet.py) is drawn again: the server computes every figure. Purchase, surplus, markup and intern / extern reach admins only.
const DK = {parts: {}, adm: {}, saving: 0};
const DK_HEAD = [['shoot_days', N_('Shooting days')], ['travel_days', N_('Travel days')], ['travel_share', N_('Travel share of the day rate')],
  ['prep_days', N_('Preparation days')], ['prep_share', N_('Preparation share of the day rate')], ['nights', N_('Nights')],
  ['night_rate', N_('Price per night')], ['meal_large', N_('Meals full day')], ['meal_small', N_('Meals part day')],
  ['sat_days', N_('Saturdays')], ['sat_pct', N_('Saturday surcharge %')], ['sun_days', N_('Sundays / holidays')], ['sun_pct', N_('Sunday surcharge %')]];
const dkNum = (k, v, label, extra) => `<label class="dkf"><span>${esc(label)}</span><input data-dk="${k}" inputmode="decimal" class="numin" value="${esc(ofdNumIn(v))}" ${extra || ''}></label>`;
const dkLine = (calc, uid) => (calc?.lines || []).find(l => l.uid === uid);
const dkName = (r, d) => (ofdLang(d) === 'en' ? r.name_en || r.name : r.name) || '';

function dkSheetHtml(part, doc, adm) {
  if (!part) return '';
  DK.parts[part.id] = part; DK.adm[part.id] = !!adm;
  const s = part.sheet || {}, h = s.head || {}, c = part.calc || {}, d = doc || OFD.doc || {};
  const m = v => ofdMoney(+v || 0, d), tot = uid => { const l = dkLine(c, uid); return l ? m(l.total) : ''; };
  const del = (k, i) => `<button type="button" class="ib" data-dka="del" data-k="${k}" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>`;
  const ie = (k, v) => adm ? `<select data-dk="${k}" aria-label="${esc(tr('intern / extern'))}"><option value="intern" ${v === 'intern' ? 'selected' : ''}>${tr('intern')}</option><option value="extern" ${v !== 'intern' ? 'selected' : ''}>${tr('extern')}</option></select>` : '';
  const mk = (k, v) => adm ? `<label class="dkmk">${tr('Markup %')} <input data-dk="${k}" inputmode="decimal" class="numin" value="${esc(ofdNumIn(v || 0))}"></label>` : '';
  const head = DK_HEAD.map(([k, n]) => dkNum('head.' + k, h[k], tr(n))).join('');
  const staff = (s.staff || []).map((r, i) => `<li class="ofdit dkrow"><div class="ofditb"><b class="dkn">${esc(dkName(r, d))}</b>
    <span class="ofdnums"><input data-dk="staff.${i}.qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(r.qty))}" aria-label="${esc(tr('Number of people'))}"><span class="muted">×</span><span class="muted">${esc(m(r.rate))} ${tr('per day')}</span><b class="ofdlt">${esc(tot(r.uid))}</b></span>
    <span class="ofdflags"><label class="chkl"><input type="checkbox" data-dk="staff.${i}.prep" ${r.prep ? 'checked' : ''}> ${tr('with preparation')}</label>${ie(`staff.${i}.intext`, r.intext)}${mk(`staff.${i}.markup_pct`, r.markup_pct)}</span></div>${del('staff', i)}</li>`).join('');
  const p = s.producing || {}, k = s.km || {}, st = s.set;
  const setL = dkLine(c, 'set');
  const setHtml = st ? `<div class="dkset"><div class="row"><b>${esc(st.name || tr('Equipment set'))}</b><span class="spacer"></span><button type="button" class="btn sm" data-dka="set">${tr('Change set')}</button><button type="button" class="ib" data-dka="set-off" aria-label="${esc(tr('Remove set'))}">${ic('x', 's')}</button></div>
    <div class="dkgrid">${dkNum('set.days', st.days, tr('Days'), `placeholder="${esc(ofdNumIn(h.shoot_days))}"`)}${dkNum('set.discount_pct', st.discount_pct, tr('Discount %'))}${adm ? `<label class="dkf"><span>${tr('intern / extern')}</span>${ie('set.intext', st.intext)}</label>` : ''}</div>
    ${setL?.days_differ ? `<p class="dkhint">${esc(tr('differs from {0} shooting days', ofdQty(h.shoot_days, d)))}</p>` : ''}
    <ul class="ofdits" role="list">${(st.items || []).map((it, i) => `<li class="ofdit dkrow"><div class="ofditb"><span class="dkn">${esc(dkName(it, d))}</span><span class="ofdnums"><input data-dk="set.items.${i}.qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.qty))}" aria-label="${esc(tr('Quantity'))}"><span class="muted">× ${esc(m(it.rate))}</span></span></div>${del('set.items', i)}</li>`).join('')}</ul>
    <div class="ofdadd"><button type="button" class="btn sm" data-dka="eq">${ic('plus', 's')}<span>${tr('Add equipment')}</span></button></div>
    ${setL ? `<p class="dksum"><span>${esc(tr('{0} per day', m(setL.rate)))}</span><b>${esc(m(setL.total))}</b></p>` : ''}</div>`
    : `<div class="ofdadd"><button type="button" class="btn sm" data-dka="set">${ic('plus', 's')}<span>${tr('Choose equipment set')}</span></button></div>`;
  const extras = (s.extras || []).map((r, i) => `<li class="ofdit dkrow"><div class="ofditb"><input class="ofdtt" data-dk="extras.${i}.name" value="${esc(r.name || '')}" maxlength="200" placeholder="${esc(tr('Additional costs'))}" aria-label="${esc(tr('Description'))}">
    <span class="ofdnums"><input data-dk="extras.${i}.qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(r.qty))}" aria-label="${esc(tr('Quantity'))}"><span class="muted">×</span><input data-dk="extras.${i}.rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(r.rate))}" aria-label="${esc(tr('Price'))}"><b class="ofdlt">${esc(tot(r.uid))}</b></span>
    ${adm ? `<span class="ofdflags">${ie(`extras.${i}.intext`, r.intext)}${mk(`extras.${i}.markup_pct`, r.markup_pct)}</span>` : ''}</div>${del('extras', i)}</li>`).join('');
  const auto = ['meals', 'hotel'].map(u => { const l = dkLine(c, u); return l ? `<p class="dksum"><span>${esc(l.label)} <small class="muted">${esc(l.detail || '')} · ${esc(l.qty)} × ${esc(m(l.rate))}</small></span><b>${esc(m(l.total))}</b></p>` : ''; }).join('');
  const sums = [[tr('Sum'), c.sum], [tr('Discount'), +c.discount ? c.discount : null], [tr('Net total'), c.net]].filter(x => x[1] != null)
    .concat(adm && c.costs != null ? [[tr('Third-party costs'), c.costs], [tr('Surplus'), c.margin]] : [])
    .map(([n, v], i) => `<p class="dksum ${i > 2 || n === tr('Net total') ? 'dkstrong' : ''}"><span>${esc(n)}</span><b>${esc(m(v))}</b></p>`).join('');
  return `<div class="dksheet" data-pid="${part.id}">
    <details class="dkbox" open><summary>${tr('Shoot')}</summary><div class="dkgrid">${head}</div></details>
    <section class="dkbox"><h4>${tr('Crew')}</h4><ul class="ofdits" role="list">${staff || `<li class="muted lempty">${tr('No crew yet.')}</li>`}</ul>
      <div class="ofdadd"><button type="button" class="btn sm pri" data-dka="role">${ic('plus', 's')}<span>${tr('Add crew')}</span></button></div></section>
    <section class="dkbox"><h4>${tr('Producing')}</h4><div class="dkgrid"><label class="chkl"><input type="checkbox" data-dk="producing.on" ${p.on ? 'checked' : ''}> ${tr('Producing share of the crew')}</label>${dkNum('producing.share', p.share, tr('Share'))}</div>${dkLine(c, 'share') ? `<p class="dksum"><span></span><b>${esc(tot('share'))}</b></p>` : ''}</section>
    <section class="dkbox"><h4>${tr('Travel')}</h4><div class="dkgrid">${dkNum('km.km', k.km, tr('Kilometres'))}${dkNum('km.rate', k.rate, tr('Rate per km'))}${dkNum('km.trips', k.trips, tr('Trips'))}</div>
      ${dkLine(c, 'km') ? `<p class="dksum"><span>${esc(dkLine(c, 'km').label)}</span><b>${esc(tot('km'))}</b></p>` : ''}
      <label class="chkl"><input type="checkbox" data-dk="meals_on" ${s.meals_on ? 'checked' : ''}> ${tr('Meals for the crew')}</label>${auto}</section>
    <section class="dkbox"><h4>${tr('Equipment')}</h4>${setHtml}</section>
    <section class="dkbox"><h4>${tr('Additional costs')}</h4><ul class="ofdits" role="list">${extras}</ul>
      <div class="ofdadd"><button type="button" class="btn sm" data-dka="extra">${ic('plus', 's')}<span>${tr('Additional costs')}</span></button><button type="button" class="btn sm" data-dka="svc">${ic('plus', 's')}<span>${tr('Shooting service')}</span></button></div></section>
    <section class="dkbox dktotals"><div class="dkgrid">${dkNum('discount_pct', s.discount_pct, tr('Discount %'))}</div>${sums}</section></div>`;
}

// the request body: the stored sheet with the edits; members send no base rate of crew rows (the server keeps it)
function dkPayload(s, adm) {
  const out = JSON.parse(JSON.stringify(s || {}));
  if (!adm) for (const r of out.staff || []) delete r.rate;
  return out;
}
function dkSet(obj, path, val) {
  const ks = path.split('.'); let o = obj;
  for (let i = 0; i < ks.length - 1; i++) { const k = /^\d+$/.test(ks[i]) ? +ks[i] : ks[i]; if (o[k] == null) o[k] = {}; o = o[k]; }
  o[ks.at(-1)] = val;
}
async function dkSave(root, pid, sheet) {
  const part = DK.parts[pid], d = OFD.doc; if (!part || !d) return;
  const focus = document.activeElement?.dataset?.dk;
  DK.saving++; ofdSaveHint?.();
  try {
    const j = await rawFetch('PATCH', `/api/office/docs/${d.id}/parts/${pid}`, {sheet: dkPayload(sheet, DK.adm[pid])});
    const np = {...part, ...(j?.part || j || {})}; DK.parts[pid] = np;
    if (j?.doc_totals && OFD.doc) OFD.doc.totals = j.doc_totals;
    const pi = (OFD.doc?.parts || []).findIndex(x => x.id === pid); if (pi >= 0) OFD.doc.parts[pi] = np;
    if (root.isConnected) { root.innerHTML = dkSheetHtml(np, d, DK.adm[pid]); if (focus) $(`[data-dk="${focus}"]`, root)?.focus(); }
    ofdDraw();  // the view was drawn again meanwhile (e.g. master data loaded): draw it with the new figures; 2.113.0 (#2248): also the title page next to the open sheet
  } catch (x) { toast(x.message || tr('unknown')); }
  finally { DK.saving--; ofdSaveHint?.(); }
}
const dkCopy = pid => JSON.parse(JSON.stringify(DK.parts[pid]?.sheet || {}));

function dkSheetBind(root, part) {
  if (!root || root._dkBound) return;
  root._dkBound = true;
  const pidOf = el => +(el.closest('.dksheet')?.dataset.pid || part?.id || 0);
  // 2.47.0 (#1216): root may be a stable ancestor (the office body): the sheet box itself is replaced when the view morphs
  const boxOf = el => el.closest('.tpsheet') || root;
  root.addEventListener('change', e => {
    const el = e.target.closest('.dksheet [data-dk]'); if (!el) return;
    const pid = pidOf(el), s = dkCopy(pid), k = el.dataset.dk, box = boxOf(el);
    let v = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.tagName === 'SELECT' || /\.name$/.test(k) ? el.value : ofcNum(el.value);
    if (k === 'set.days' && v == null) v = null;
    else if (v == null) v = 0;
    dkSet(s, k, v);
    dkSave(box, pid, s);
  });
  root.addEventListener('click', e => {
    const b = e.target.closest('.dksheet [data-dka]'); if (!b) return;
    const pid = pidOf(b), s = dkCopy(pid), a = b.dataset.dka, root = boxOf(b);
    if (a === 'del') { const arr = b.dataset.k.split('.').reduce((o, k) => o?.[k], s); if (Array.isArray(arr)) { arr.splice(+b.dataset.i, 1); dkSave(root, pid, s); } return; }
    if (a === 'set-off') { s.set = null; dkSave(root, pid, s); return; }
    if (a === 'extra') { (s.extras = s.extras || []).push({name: '', qty: 1, rate: 0}); dkSave(root, pid, s); return; }
    if (a === 'role') return dkPick('crew', tr('Add crew'), r => `${dkName({name: r.name_de, name_en: r.name_en})}`, r => r.rate_day != null ? ofdMoney(r.rate_day) + ' ' + tr('per day') : '', r => { (s.staff = s.staff || []).push({role_id: r.id, qty: 1, prep: 1}); dkSave(root, pid, s); });
    if (a === 'svc') return dkPick('services', tr('Shooting service'), r => dkName({name: r.name_de, name_en: r.name_en}), r => r.daily_rate != null ? ofdMoney(r.daily_rate) : '', r => { (s.extras = s.extras || []).push({service_id: r.id, qty: 1}); dkSave(root, pid, s); }, r => r.intext === 'shooting');
    if (a === 'set') return dkPick('sets', tr('Choose equipment set'), r => r.name, r => r.discount_pct ? tr('{0} % discount', ofdQty(r.discount_pct)) : '', r => { s.set = {set_id: r.id}; dkSave(root, pid, s); });
    if (a === 'eq') return dkPick('equipment', tr('Add equipment'), r => dkName(r), r => r.daily_rate != null ? ofdMoney(r.daily_rate) + ' ' + tr('per day') : '', r => {
      const st = s.set || {}; const items = (st.items || []).map(i => ({equipment_id: i.equipment_id, qty: i.qty}));
      const ex = items.find(i => i.equipment_id === r.id); if (ex) ex.qty = (+ex.qty || 0) + 1; else items.push({equipment_id: r.id, qty: 1});
      s.set = {...st, items}; dkSave(root, pid, s);
    });
  });
}

// a picker over master data (crew roles, sets, equipment, shooting services): big rows, search, works on the phone
function dkPick(kind, title, nameOf, subOf, onPick, filter) {
  const md = modal(`<h3>${esc(title)}</h3><div class="ctsearch">${ic('search', 's')}<input id="dk-q" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off"></div><div id="dk-list" class="ofdslist"></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofdpick');
  const draw = () => {
    const q = ($('#dk-q', md)?.value || '').trim().toLowerCase();
    const rows = ofcRows(kind).filter(r => !r.archived && (!filter || filter(r)) && (!q || String(nameOf(r) || '').toLowerCase().includes(q)));
    $('#dk-list', md).innerHTML = rows.length ? `<ul class="ofclist" role="list">${rows.map(r => `<li><button type="button" class="ofcrow" data-rid="${r.id}"><span class="ofcn"><b>${esc(nameOf(r) || '')}</b><small class="muted">${esc(subOf(r) || '')}</small></span>${ic('plus', 's')}</button></li>`).join('')}</ul>`
      : `<p class="muted lempty">${Array.isArray(OFC.data[kind]) ? tr('Nothing matches.') : esc(OFC.data[kind]?.error || tr('Loading…'))}</p>`;
  };
  draw();
  if (!Array.isArray(OFC.data[kind])) (async () => { for (let i = 0; i < 60 && !Array.isArray(OFC.data[kind]) && !OFC.data[kind]?.error && md.isConnected; i++) { if (!OFC.loading[kind]) ofcLoad(kind, true); await sleep(150); } if (md.isConnected) draw(); })();
  md.addEventListener('input', e => { if (e.target.id === 'dk-q') draw(); });
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-rid],[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const r = ofcRow(kind, +b.dataset.rid); if (!r) return;
    md.remove(); onPick(r);
  });
}
