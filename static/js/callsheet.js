// @ts-check
/* Kalmido web client: the call sheet of a shoot day (2.855.0, #1956), module "callsheet" (lazyload.js, loaded by the button
   "Call sheet" of a booking in the disposition, dispo.js dp_editSheet; only with the industry Film & Video). One dialog per
   shoot day (= one job of the disposition): what the app knows is shown (day, crew, project, client, production), the day
   details are typed in (set phone, location, call times, lunch, wrap, weather, important, cast, transport, the shot list's
   day, a directions sketch as a picture) and saved with the version read (409 -> reload offer); "PDF" downloads / shares
   the call sheet (server hub/callsheet.py). The address becomes a link to the device's map app on a tap, nothing is fetched.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const CS_ROWS = {
  calls: [['dept', N_('Department')], ['time', N_('Time')]],
  contacts: [['role', N_('Role')], ['name', N_('Name')], ['phone', N_('Phone')]],
  cast: [['role', N_('Role')], ['name', N_('Name')], ['phone', N_('Phone')], ['arrival', N_('Arrival')], ['makeup', N_('Make-up')], ['costume', N_('Costume')], ['ready', N_('Ready')]],
  transport: [['vehicle', N_('Vehicle / driver')], ['from', N_('From')], ['to', N_('To')], ['riders', N_('Passengers')], ['cargo', N_('Cargo')], ['call', N_('Call time')]],
};
const CS_CALL_DEPTS = [N_('Production'), N_('Lighting'), N_('Camera'), N_('Director'), N_('Make-up / costume'), N_('Cast')];
const CS_MAX = 4 * 1024 * 1024;

/** the form's elements (inputs, buttons) of the dialog: the type check knows them as any */
const cs_one = (s, r) => /** @type {any} */ ($(s, r));
const cs_all = (s, r) => /** @type {any[]} */ ($$(s, r));
const cs_url = (job, org, tail = '') => `/api/team/dispo/callsheet/${encodeURIComponent(job)}${tail}?org=${org}`;
/** a link that opens the address in the device's map app (Apple devices: Apple Maps, else Google Maps); nothing before the tap */
function cs_mapHref(t) {
  const q = encodeURIComponent(t);
  return /iPad|iPhone|iPod|Macintosh/.test(navigator.userAgent) ? `https://maps.apple.com/?q=${q}` : `https://www.google.com/maps/search/?api=1&query=${q}`;
}

// 2.986.0 (#5649): client and agency from the contacts -- a select of the area's contacts the person may read (like the
// disposition's places, dispo.js dp_fillHtml), the contact's company, person, phone and e-mail below it; the free text stays
// as the fallback (shown while no contact is chosen). A new call sheet starts with the agency remembered at the project.
const cs_ctLabel = x => [x.person, x.company].filter(Boolean).join(' – ') || '?';
const cs_ctCard = x => x ? [x.company, x.person, x.phone, x.email].filter(Boolean).join(' · ') : '';
function cs_ctHtml(k, label, cur, list, freeHtml) {
  // review F1: the contact chosen is always a choice (also beyond the first 500 of the list)
  const opts = (cur && !(list || []).some(x => x.id === cur.id) ? [cur, ...list || []] : list || []).map(x => `<option value="${esc(String(x.id))}" ${cur && cur.id === x.id ? 'selected' : ''}>${esc(cs_ctLabel(x))}</option>`).join('');
  return `<div class="row"><label for="cs-${esc(k)}_contact">${tr(label)}</label><select id="cs-${esc(k)}_contact" data-f="${esc(k)}_contact" data-n="1">
      <option value="">${esc(k === 'client' ? tr('From the client file or free text') : tr('Free text'))}</option>${/*html-ok*/ opts}</select></div>
    <p class="muted cshint csct" data-ct="${esc(k)}"${cur ? '' : ' hidden'}>${esc(cs_ctCard(cur))}</p>
    <div class="csfree" data-ct="${esc(k)}"${cur ? ' hidden' : ''}>${/*html-ok*/ freeHtml}</div>`;
}

// 2.993.0 (#5650): three logos in a row on top of the call sheet -- production left (the office logo of the area), agency in
// the middle, client right (the photo of the contact chosen in the form). A missing one leaves its place empty (a fixed box
// of the 3er grid, the others keep theirs). Who may change the contact gets "Add logo": the picture is saved at the contact as
// its photo (PUT .../photo/<contact>); without a contact chosen the dialog first asks for one (the choice of #5649).
const CS_LOGO_ALT = {production: N_('Logo of the production'), agency: N_('Logo of the agency'), client: N_('Logo of the client')};
/** the contact chosen in the form for k (agency / client): its entry of the choice, else null */
function cs_logoCt(cs, k, md) {
  const a = cs.auto || {}, sel = md ? cs_one(`#cs-${k}_contact`, md) : null;
  const id = sel ? +sel.value : (a[`${k}_contact`] || (k === 'agency' && !cs.updated_at && !(cs.data || {}).agency ? a.agency_default : null))?.id;
  if (!id) return null;
  return (a.contacts || []).find(x => x.id === id) || [a.client_contact, a.agency_contact, a.agency_default].find(x => x && x.id === id) || null;
}
/** the inner part of the logo place k */
function cs_logoCell(cs, k, md) {
  const ver = cs._lv || {};
  if (k === 'production') return cs.auto?.production?.logo ? `<img src="${esc(cs_url(cs.job, cs.org_id, '/logo'))}" alt="${esc(tr(CS_LOGO_ALT[k]))}">` : '';  // sprung-ok: fixed logo box (.cslogo)
  const ct = cs_logoCt(cs, k, md);
  if (ct?.photo) return `<img src="${esc(cs_url(cs.job, cs.org_id, '/photo/' + ct.id))}&v=${esc(String(ver[ct.id] || 0))}" alt="${esc(tr(CS_LOGO_ALT[k]))}">`;  // sprung-ok: fixed logo box (.cslogo)
  const can = cs.can_edit && (ct ? ct.can_photo : (cs.auto?.contacts || []).some(x => x.can_photo));
  return can ? `<button type="button" class="btn sm ghost" data-cs="logo" data-k="${esc(k)}" aria-label="${esc(tr(CS_LOGO_ALT[k]))}">${ic('upload', 's')} ${tr('Add logo')}</button>` : '';
}
function cs_logosHtml(cs, md) {
  return `<div class="cslogos">${['production', 'agency', 'client'].map(k => `<div class="cslogo" data-logo="${esc(k)}">${/*html-ok*/ cs_logoCell(cs, k, md)}</div>`).join('')}</div>`;
}

/** one line of an editable table (key of CS_ROWS) */
function cs_lineHtml(key, r) {
  return `<div class="csrow" data-k="${esc(key)}">${CS_ROWS[key].map(([c, label]) => `<input data-c="${esc(c)}" maxlength="200" value="${esc(r[c] || '')}" placeholder="${esc(tr(label))}" aria-label="${esc(tr(label))}">`).join('')}<button type="button" class="iconbtn" data-cs="rowdel" aria-label="${esc(tr('Remove line'))}" title="${esc(tr('Remove line'))}">${ic('x', 's')}</button></div>`;
}
function cs_rowsHtml(key, rows) {
  return `<div class="csrows" data-k="${esc(key)}" style="--cs-cols:${CS_ROWS[key].length}">${/*html-ok*/ rows.map(r => cs_lineHtml(key, r)).join('')}</div><button type="button" class="btn sm ghost" data-cs="rowadd" data-k="${esc(key)}">${ic('plus', 's')} ${tr('Add line')}</button>`;
}

function cs_formHtml(cs) {
  const d = cs.data || {}, a = cs.auto || {};
  const txt = (k, label, ph = '', max = 200) => `<div class="row"><label for="cs-${esc(k)}">${tr(label)}</label><input id="cs-${esc(k)}" data-f="${esc(k)}" maxlength="${esc(String(max))}" value="${esc(d[k] || '')}" placeholder="${esc(ph)}"></div>`;
  const area = (k, label, ph = '', max = 1500) => `<div class="row"><label for="cs-${esc(k)}">${tr(label)}</label><textarea id="cs-${esc(k)}" data-f="${esc(k)}" rows="2" maxlength="${esc(String(max))}" placeholder="${esc(ph)}">${esc(d[k] || '')}</textarea></div>`;
  const cl = a.client || {}, prod = a.production || {};
  const calls = d.calls?.length ? d.calls : CS_CALL_DEPTS.map(x => ({dept: tr(x), time: ''}));
  // 2.1158.0 (#4566 A): the packing list -- the devices booked for the day (from the quotation with their quantity), the rows
  // without a device as text lines; ticking off is part of the day details (data.pack), saved with "Save"
  const pack = a.pack || [], ticked = new Set(d.pack || []);
  const packLi = x => `<li><label><input type="checkbox" data-pk="${esc(x.key)}" ${ticked.has(x.key) ? 'checked' : ''}><span class="cspq">${esc(String(x.qty))} ×</span> <span class="cspn">${esc(x.name)}</span>${x.set ? ` <small class="muted">(${esc(x.set)})</small>` : ''}${x.category ? ` <small class="muted cspc">${esc(x.category)}</small>` : ''}${x.text ? ` <small class="muted">${tr('text only')}</small>` : ''}</label></li>`;
  const packHtml = `<details class="cssec cspacksec"${pack.length ? ' open' : ''}><summary>${tr('Packing list')}${pack.length ? ` <span class="muted cspcount">${esc(tr('{0} of {1} packed', pack.filter(x => ticked.has(x.key)).length, pack.length))}</span>` : ''}</summary>
    ${pack.length ? `<ul class="cspack">${/*html-ok*/ pack.map(packLi).join('')}</ul>` : `<p class="muted">${tr('No equipment booked for this shoot day yet.')}</p>`}
    <p class="muted cshint">${tr('The packing list comes from the equipment booked for this shoot day; what is ticked is kept with "Save".')}</p></details>`;
  const crew = (a.crew || []).map(p => `<li class="${p.open ? 'csopen' : ''}"><b>${esc(p.function || '')}</b> <span>${esc(p.name)}</span> <span class="muted">${esc([p.phone, p.mail].filter(Boolean).join(' · '))}</span></li>`).join('');
  return `${/*html-ok*/ cs_logosHtml(cs)}<h3>${tr('Call sheet')}: ${esc(a.project || a.title || '')}</h3>
    <p class="muted">${esc(fmtDayAbs(a.date))}${a.project && a.title ? ' · ' + esc(a.title) : ''}</p>
    <details class="cssec" open><summary>${tr('Header')}</summary>
      ${/*html-ok*/ txt('subtitle', N_('Subtitle'), a.project && a.title !== a.project ? a.title : '')}
      <div class="csgrid2">${/*html-ok*/ txt('day_no', N_('Shoot day no.'), '1', 12)}${/*html-ok*/ txt('set_name', N_('Set phone: name'))}${/*html-ok*/ txt('set_phone', N_('Set phone: number'), '', 60)}</div>
      <p class="muted cshint">${tr('Production')}: ${esc([prod.name, ...(prod.lines || [])].filter(Boolean).join(', ') || tr('from the master data of the office'))}</p>
      ${/*html-ok*/ cs_ctHtml('client', N_('Client'), a.client_contact, a.contacts, area('client', N_('Client: free text'), [cl.name, cl.contact, cl.address, cl.phone, cl.email].filter(Boolean).join('\n') || tr('Company, contact person, phone, e-mail'), 400))}
      ${/*html-ok*/ cs_ctHtml('agency', N_('Agency'), a.agency_contact || (!cs.updated_at && !d.agency ? a.agency_default : null), a.contacts, area('agency', N_('Agency: free text'), tr('optional'), 400))}
      <p class="lbl">${tr('Contacts')}</p><p class="muted cshint">${tr('Empty: the crew functions of the bookings with their phone numbers.')}</p>${/*html-ok*/ cs_rowsHtml('contacts', d.contacts || [])}
    </details>
    <details class="cssec" open><summary>${tr('Location')}</summary>
      ${/*html-ok*/ txt('loc_name', N_('Location'))}
      <div class="row"><label for="cs-loc_address">${tr('Address')}</label><input id="cs-loc_address" data-f="loc_address" maxlength="300" value="${esc(d.loc_address || '')}"></div>
      <p class="csmap">${d.loc_address ? `<a href="${esc(cs_mapHref(d.loc_address))}" target="_blank" rel="noopener noreferrer">${ic('link', 's')} ${tr('Open in maps')}</a>` : ''}</p>
      ${/*html-ok*/ area('parking', N_('Parking / directions'))}
      ${/*html-ok*/ area('transit', N_('Public transport'), tr('Lines and stop'), 1000)}
    </details>
    <details class="cssec" open><summary>${tr('Times')}</summary>
      <p class="lbl">${tr('Call on set')}</p>${/*html-ok*/ cs_rowsHtml('calls', calls)}
      <div class="csgrid2">${/*html-ok*/ txt('shoot_start', N_('Shoot start'), a.start || '07:30', 20)}${/*html-ok*/ txt('lunch_from', N_('Lunch from'), '13:00', 20)}${/*html-ok*/ txt('lunch_to', N_('Lunch until'), '14:00', 20)}${/*html-ok*/ txt('wrap', N_('Wrap'), a.end || '', 20)}${/*html-ok*/ txt('strike', N_('Strike until'), '', 20)}</div>
      ${/*html-ok*/ txt('weather', N_('Weather'), tr('Sunrise, sunset, temperature'), 400)}
      ${/*html-ok*/ area('important', N_('Important'), tr('optional'), 3000)}
    </details>
    <details class="cssec"${d.cast?.length ? ' open' : ''}><summary>${tr('Cast')}</summary>${/*html-ok*/ cs_rowsHtml('cast', d.cast || [])}</details>
    <details class="cssec"${d.transport?.length ? ' open' : ''}><summary>${tr('Transport')}</summary><p class="muted cshint">${tr('Empty call time: "Own arrangement".')}</p>${/*html-ok*/ cs_rowsHtml('transport', d.transport || [])}</details>
    <details class="cssec"><summary>${tr('Crew list')}</summary>${crew ? `<ul class="cscrew">${/*html-ok*/ crew}</ul>` : `<p class="muted">${tr('Nobody booked yet.')}</p>`}<p class="muted cshint">${tr('The crew comes from the bookings of this shoot day; phone numbers and e-mails from the address book.')}</p></details>
    ${/*html-ok*/ packHtml}
    ${(a.shot_days || []).length ? `<div class="row"><label for="cs-shot_day">${tr('Shots of the day')}</label><select id="cs-shot_day" data-f="shot_day"><option value="">${tr('None')}</option>${a.shot_days.map(n => `<option value="${esc(n)}" ${d.shot_day === n ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>` : ''}
    <details class="cssec"${cs.sketch ? ' open' : ''}><summary>${tr('Directions sketch')}</summary>
      <div class="cssketch">${cs.sketch ? `<img src="${esc(cs.sketch_url)}&v=${esc(encodeURIComponent(cs.updated_at))}" alt="${esc(tr('Directions sketch'))}">` : `<p class="muted">${tr('A screenshot or drawing (PNG or JPEG); it gets a page of its own, with "Parking / directions" below it.')}</p>`}</div>
      <label class="btn sm">${ic('upload', 's')} ${cs.sketch ? tr('Replace picture') : tr('Select picture')}<input type="file" id="cs-sketch" accept="image/png,image/jpeg" hidden></label>
      ${cs.sketch ? `<button type="button" class="btn sm ghost" data-cs="sketchdel">${ic('trash', 's')} ${tr('Remove picture')}</button>` : ''}
    </details>
    ${/*html-ok*/ area('attachments', N_('More attachments'), tr('One per line'), 1000)}
    <p class="cserr" role="alert" hidden></p>
    <input type="file" id="cs-logofile" accept="image/png,image/jpeg" hidden>
    <div class="foot"><button class="btn" data-cs="close">${tr('Close')}</button><span class="spacer"></span>
      <button class="btn" data-cs="pdf">${ic('download', 's')} ${tr('PDF')}</button>${navigator.canShare ? `<button class="btn" data-cs="share">${ic('share', 's')} ${tr('Share')}</button>` : ''}
      ${cs.can_edit ? `<button class="btn" data-cs="mail">${ic('mail', 's')} ${tr('Send by e-mail')}</button>` : ''}
      ${cs.can_edit ? `<button class="btn pri" data-cs="save">${ic('check', 's')} ${tr('Save')}</button>` : ''}</div>`;
}

/** the form's values as the server's data object */
function cs_collect(md) {
  /** @type {Record<string, any>} */
  const out = {};
  cs_all('[data-f]', md).forEach(el => { const v = el.value.trim(); if (v) out[el.dataset.f] = el.dataset.n ? +v : v; });  // 2.986.0 (#5649): data-n = a contact id
  for (const k of Object.keys(CS_ROWS)) {
    const rows = cs_all(`.csrow[data-k="${k}"]`, md).map(r => Object.fromEntries(cs_all('input', r).map(i => [i.dataset.c, i.value.trim()]))).filter(r => Object.values(r).some(Boolean));
    if (k === 'calls' && rows.every(r => !r.time)) continue;  // only the suggested departments without a time: nothing to keep
    if (rows.length) out[k] = rows;
  }
  const pk = cs_all('[data-pk]', md).filter(x => x.checked).map(x => x.dataset.pk).sort();  // 2.1158.0 (#4566 A): ticked lines
  if (pk.length) out.pack = pk;
  return out;
}

const cs_readFile = f => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => no(r.error); r.readAsDataURL(f); });

/** opens the call sheet of shoot day `job` in area `org` */
async function cs_open(job, org) {
  let cs;
  try { cs = (await api('GET', cs_url(job, org))).callsheet; } catch { return; /* api() said it */ }
  const md = /** @type {any} */ (modal('')), card = cs_one('.card', md);
  md.classList.add('csmd');
  let sketch;  // undefined = unchanged, '' = remove, data URI = new
  const draw = () => {
    setHtml(card, cs_formHtml(cs));
    if (!cs.can_edit) cs_all('input, textarea, select, [data-cs="rowadd"], [data-cs="rowdel"], [data-cs="sketchdel"]', md).forEach(x => { if (!x.closest('.foot')) x.disabled = true; });
  };
  draw();
  const err = t => { const e = cs_one('.cserr', md); if (e) { e.textContent = t || ''; e.hidden = !t; } };
  const save = async () => {
    const before = {data: cs.data || {}};
    const v = {data: cs_collect(md), expect_updated_at: cs.updated_at || undefined, ...(sketch !== undefined ? {sketch} : {})};
    try {
      const r = await api('PUT', cs_url(job, org), v);
      cs = {...r.callsheet, _lv: cs._lv}; sketch = undefined; err('');  // 2.993.0 (#5650): _lv = the logos uploaded here (a new picture, not the cached one)
      // 2.855.0 (#1956, review F3): back / forward carry the version this save left - a change by someone else since is a
      // 409 (api() says it) and nothing is overwritten
      let ver = cs.updated_at;
      const put = x => async () => { try { ver = (await api('PUT', cs_url(job, org), {...x, expect_updated_at: ver})).callsheet.updated_at; } catch { /* api() said it */ } };
      histAdd({label: tr('Call sheet saved'), undo: put(before), redo: put({data: v.data})});
      toast(tr('Saved'));
      draw();
      return true;
    } catch (e) {
      if (e?.status === 409 && e.data?.callsheet) {
        err(tr('Someone else saved this call sheet meanwhile. Load the newer version (your changes here are dropped) or copy them first.'));
        const b = document.createElement('button'); b.type = 'button'; b.className = 'btn sm'; b.dataset.cs = 'reload'; b.textContent = tr('Load the newer version');
        cs_one('.cserr', md)?.append(' ', b);
        md._cur = e.data.callsheet;
      }
      return false;
    }
  };
  const pdfBlob = async () => {
    const r = await fetch(cs_url(job, org, '/pdf'), {credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
    if (!r.ok) throw new Error(tr('The PDF could not be made.'));
    return r.blob();
  };
  const fname = () => `callsheet-${(cs.auto?.date || '')}.pdf`;
  // 2.993.0 (#5650): the logos -- a place drawn again, the upload (saved at the contact), the contact chosen first
  const cs_logoDraw = k => { const box = cs_one(`.cslogo[data-logo="${k}"]`, md); if (box) setHtml(box, cs_logoCell(cs, k, md)); };
  const cs_logoPick = k => { const f = cs_one('#cs-logofile', md); if (f) { f.dataset.k = k; f.click(); } };
  const cs_logoUp = async (f, k) => {
    const ct = cs_logoCt(cs, k, md);
    if (!ct) return;
    if (!/^image\/(png|jpeg)$/.test(f.type)) { toast(tr('Please select a PNG or JPEG picture')); return; }
    if (f.size > CS_MAX) { toast(tr('The picture is too large (at most {0} MB)', 4)); return; }
    try {
      const r = await api('PUT', cs_url(job, org, '/photo/' + ct.id), {photo: await cs_readFile(f)});
      for (const x of [...(cs.auto?.contacts || []), cs.auto?.client_contact, cs.auto?.agency_contact, cs.auto?.agency_default]) if (x && x.id === ct.id) Object.assign(x, r.contact);
      cs._lv = {...cs._lv, [ct.id]: Date.now()};
      cs_logoDraw('agency'); cs_logoDraw('client');
      toast(tr('The logo is saved as the photo of the contact.'));
    } catch { /* api() said it */ }
  };
  const cs_logoAsk = k => {  // no contact chosen yet: the choice first (the contacts the person may change)
    const list = (cs.auto?.contacts || []).filter(x => x.can_photo);
    const m = modal(`<h3>${esc(tr(CS_LOGO_ALT[k]))}</h3><p class="muted cshint">${tr('The logo is saved as the photo of the contact.')}</p>
      <div class="row"><label for="cs-logoct">${tr('Contact')}</label><select id="cs-logoct">${list.map(x => `<option value="${esc(String(x.id))}">${esc(cs_ctLabel(x))}</option>`).join('')}</select></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-csl="cancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-csl="ok">${ic('upload', 's')} ${tr('Select picture')}</button></div>`);
    m.addEventListener('click', e => {
      const b = /** @type {any} */ (e.target).closest?.('[data-csl]'); if (!b) return;
      const v = cs_one('#cs-logoct', m)?.value;
      m.remove();
      if (b.dataset.csl !== 'ok' || !v) return;
      const sel = cs_one(`#cs-${k}_contact`, md);
      if (sel) { sel.value = v; sel.dispatchEvent(new Event('change', {bubbles: true})); }
      toast(tr('Save the call sheet to keep the contact chosen.'));
      cs_logoPick(k);
    });
  };
  md.addEventListener('change', async e => {
    const t = /** @type {any} */ (e.target);
    if (t.dataset?.n && t.dataset.f) {  // 2.986.0 (#5649): a contact chosen -> its card, else the free text
      const k = t.dataset.f.replace(/_contact$/, ''), x = (cs.auto?.contacts || []).find(y => y.id === +t.value);
      const card = cs_one(`.csct[data-ct="${k}"]`, md), free = cs_one(`.csfree[data-ct="${k}"]`, md);
      if (card) { card.textContent = cs_ctCard(x); card.hidden = !x; }
      if (free) free.hidden = !!x;
      cs_logoDraw(k);  // 2.993.0 (#5650): the logo of the contact chosen
    }
    if (t.dataset?.pk) {  // 2.1158.0 (#4566 A): the count of the packing list follows the ticks (saved with "Save")
      const all = cs_all('[data-pk]', md), cnt = cs_one('.cspcount', md);
      if (cnt) cnt.textContent = tr('{0} of {1} packed', all.filter(x => x.checked).length, all.length);
    }
    if (t.id === 'cs-logofile' && t.files?.[0]) { await cs_logoUp(t.files[0], t.dataset.k); t.value = ''; return; }
    if (t.id === 'cs-loc_address') { const p = cs_one('.csmap', md); if (p) setHtml(p, t.value.trim() ? `<a href="${esc(cs_mapHref(t.value.trim()))}" target="_blank" rel="noopener noreferrer">${ic('link', 's')} ${tr('Open in maps')}</a>` : ''); }
    if (t.id === 'cs-sketch' && t.files?.[0]) {
      const f = t.files[0];
      if (!/^image\/(png|jpeg)$/.test(f.type)) { toast(tr('Please select a PNG or JPEG picture')); t.value = ''; return; }
      if (f.size > CS_MAX) { toast(tr('The picture is too large (at most {0} MB)', 4)); t.value = ''; return; }
      sketch = await cs_readFile(f);
      const box = cs_one('.cssketch', md); if (box) setHtml(box, `<img src="${esc(sketch)}" alt="${esc(tr('Directions sketch'))}"><p class="muted">${tr('Saved with "Save".')}</p>`);
    }
  });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest?.('[data-cs]'); if (!b || b.disabled) return;
    const k = b.dataset.cs;
    if (k === 'close') { md.remove(); pcs_after(); return; }
    if (k === 'rowadd') { const box = cs_one(`.csrows[data-k="${b.dataset.k}"]`, md); if (!box) return; const tmp = document.createElement('div'); setHtml(tmp, cs_lineHtml(b.dataset.k, {})); box.append(...tmp.childNodes); cs_one('.csrow:last-child input', box)?.focus(); return; }
    if (k === 'rowdel') { b.closest('.csrow')?.remove(); return; }
    if (k === 'logo') { if (cs_logoCt(cs, b.dataset.k, md)) cs_logoPick(b.dataset.k); else cs_logoAsk(b.dataset.k); return; }
    if (k === 'sketchdel') { sketch = ''; const box = cs_one('.cssketch', md); if (box) setHtml(box, `<p class="muted">${tr('The picture goes with "Save".')}</p>`); b.remove(); return; }
    if (k === 'reload') { if (md._cur) { cs = md._cur; md._cur = null; sketch = undefined; draw(); } return; }
    if (k === 'save') { b.disabled = true; await save(); b.disabled = false; return; }
    if (k === 'mail') {  // 2.1155.0 (#5652): what the form shows is what goes out (saved first when changed)
      const dirty = sketch !== undefined || JSON.stringify(cs_collect(md)) !== JSON.stringify(cs.data || {});
      if (dirty && !(await save())) return;
      cs_mail(job, org);
      return;
    }
    if (k === 'pdf' || k === 'share') {
      const dirty = sketch !== undefined || JSON.stringify(cs_collect(md)) !== JSON.stringify(cs.data || {});
      if (cs.can_edit && dirty && !(await save())) return;  // what the form shows is what the PDF says (saved first when changed)
      b.disabled = true;
      try {
        const blob = await pdfBlob();
        const file = new File([blob], fname(), {type: 'application/pdf'});
        if (k === 'share' && navigator.canShare?.({files: [file]})) { await navigator.share({files: [file], title: tr('Call sheet')}).catch(() => {}); }
        else { const u = URL.createObjectURL(blob), x = document.createElement('a'); x.href = u; x.download = fname(); document.body.append(x); x.click(); x.remove(); setTimeout(() => URL.revokeObjectURL(u), 30000); }
      } catch (er) { toast(er.message || tr('The PDF could not be made.')); }
      b.disabled = false;
    }
  });
}

// ---- 2.1155.0 (#5652): the call sheet by e-mail (decision of 14.11.2026): a mail with the PDF attached to the
// distribution -- crew, agency, client, each recipient ticked and can be left out one by one; before sending ALWAYS the
// preview with the recipients, the subject, the text (with the signature) and the PDF; no link. The server only takes
// addresses of the distribution (hub/callsheet.py cs_mail_post) and sends each recipient a mail of their own.
const CS_MAIL_GROUPS = [['crew', N_('Crew')], ['agency', N_('Agency')], ['client', N_('Client')]];
/** one recipient of the choice (a checkbox, ticked) */
function cs_rcptHtml(x, on) {
  return `<label class="csrcpt"><input type="checkbox" data-csm-to="${esc(x.email)}"${on ? ' checked' : ''}><span class="csrn">${esc(x.name)}${x.role ? ` <span class="muted">${esc(x.role)}</span>` : ''}</span><span class="csre muted">${esc(x.email)}</span></label>`;
}
function cs_mailFormHtml(m, st) {
  const groups = CS_MAIL_GROUPS.map(([g, label]) => {
    const xs = m.recipients.filter(x => x.group === g), no = m.without.filter(x => x.group === g);
    if (!xs.length && !no.length) return '';
    return `<fieldset class="csrg"><legend>${tr(label)}</legend>${/*html-ok*/ xs.map(x => cs_rcptHtml(x, st.to.has(x.email))).join('')}
      ${no.length ? `<p class="muted cshint">${trh('Without an e-mail address: {0}', no.map(x => x.name).join(', '))}</p>` : ''}</fieldset>`;
  }).join('');
  const none = !m.recipients.length;
  return `<h3>${tr('Send the call sheet')}</h3>
    ${none ? `<p class="muted">${tr('Nobody in the distribution has an e-mail address yet. Add them to the contacts of the crew, the agency or the client.')}</p>` : `<p class="lbl">${tr('Recipients')}</p>${/*html-ok*/ groups}`}
    ${none && m.without.length ? `<p class="muted cshint">${trh('Without an e-mail address: {0}', m.without.map(x => x.name).join(', '))}</p>` : ''}
    <div class="row"><label for="csm-subject">${tr('Subject')}</label><input id="csm-subject" maxlength="200" value="${esc(st.subject)}"></div>
    <div class="row"><label for="csm-text">${tr('Text')}</label><textarea id="csm-text" rows="5" maxlength="5000">${esc(st.text)}</textarea></div>
    <p class="muted cshint">${tr('Attachment')}: ${esc(m.filename)}${m.sender?.note ? ' · ' + esc(m.sender.note) : ''}</p>
    <p class="cserr" role="alert" hidden></p>
    <div class="foot"><button type="button" class="btn" data-csm="cancel">${tr('Cancel')}</button><span class="spacer"></span>
      <button type="button" class="btn pri" data-csm="preview"${none ? ' disabled' : ''}>${ic('eye', 's')} ${tr('Preview')}</button></div>`;
}
function cs_mailPreviewHtml(p, pdfUrl) {
  const who = p.recipients.map(x => `<li><b>${esc(x.name)}</b> <span class="muted">${esc(x.email)}</span></li>`).join('');
  return `<h3>${tr('Preview')}</h3>
    <p class="muted cshint">${tr('Everyone gets an e-mail of their own; the recipients do not see one another.')}</p>
    <p class="lbl">${tr('To ({0})', p.recipients.length)}</p><ul class="csprev">${/*html-ok*/ who}</ul>
    ${p.sender?.address ? `<p class="lbl">${tr('From')}</p><p>${esc([p.sender.name, p.sender.address].filter(Boolean).join(' · '))}</p>` : ''}
    <p class="lbl">${tr('Subject')}</p><p class="csmsubj">${esc(p.subject)}</p>
    <p class="lbl">${tr('Text')}</p><div class="csmtext">${esc(p.text)}</div>
    <p class="lbl">${tr('Attachment')}</p><p><a class="btn sm" href="${esc(pdfUrl)}" target="_blank" rel="noopener" data-csm="pdf">${ic('file', 's')} ${esc(p.file.name)} <span class="muted">${esc(fmtSize(p.file.size))}</span></a></p>
    <p class="cserr" role="alert" hidden></p>
    <div class="foot"><button type="button" class="btn" data-csm="back">${tr('Back')}</button><span class="spacer"></span>
      <button type="button" class="btn pri" data-csm="send">${ic('send', 's')} ${tr('Send')}</button></div>`;
}
/** opens the mail dialog of the call sheet of shoot day `job` (saved before) */
async function cs_mail(job, org) {
  let m;
  try { m = await api('GET', cs_url(job, org, '/mail')); } catch { return; /* api() said it */ }
  if (!m.sender?.way) { toast(tr('E-mail sending is not set up on this server yet: whoever runs the server sets it up.')); return; }
  const st = {to: new Set(m.recipients.map(x => x.email)), subject: m.subject, text: m.text, step: 'form'};
  const md = /** @type {any} */ (modal('')), card = cs_one('.card', md);
  md.classList.add('csmd', 'csmail');
  const err = t => { const e = cs_one('.cserr', md); if (e) { e.textContent = t || ''; e.hidden = !t; } };
  const keep = () => {  // the form's values into st (before the preview, so "Back" shows them again)
    if (st.step !== 'form') return;
    st.to = new Set(cs_all('[data-csm-to]', md).filter(x => x.checked).map(x => x.dataset.csmTo));
    st.subject = cs_one('#csm-subject', md)?.value ?? st.subject;
    st.text = cs_one('#csm-text', md)?.value ?? st.text;
  };
  const sync = () => { const b = cs_one('[data-csm="preview"]', md); if (b && m.recipients.length) b.disabled = !cs_all('[data-csm-to]', md).some(x => x.checked); };
  const form = () => { st.step = 'form'; setHtml(card, cs_mailFormHtml(m, st)); sync(); };
  const req = preview => ({to: [...st.to], subject: st.subject, text: st.text, ...(preview ? {preview: true} : {})});
  form();
  md.addEventListener('change', e => { if (/** @type {any} */ (e.target).dataset?.csmTo !== undefined) sync(); });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest?.('[data-csm]'); if (!b || b.disabled) return;
    const k = b.dataset.csm;
    if (k === 'cancel') { md.remove(); return; }
    if (k === 'back') { form(); return; }
    if (k === 'preview') {
      keep();
      if (st.to.size > m.max) { err(tr('At most {0} recipients at once', m.max)); return; }
      b.disabled = true;
      try {
        const p = await api('POST', cs_url(job, org, '/mail'), req(true));
        st.step = 'preview';
        setHtml(card, cs_mailPreviewHtml(p, cs_url(job, org, '/pdf') + '&inline=1'));
      } catch { b.disabled = false; /* api() said it */ }
      return;
    }
    if (k === 'send') {
      b.disabled = true; b.textContent = tr('Sending…');
      try {
        const r = await api('POST', cs_url(job, org, '/mail'), req(false));
        if (r.failed?.length) {
          setHtml(card, `<h3>${tr('Send the call sheet')}</h3><p>${trh('Sent to {0} of {1} recipients.', r.sent.length, r.sent.length + r.failed.length)}</p>
            <p class="lbl">${tr('Not sent')}</p><ul class="csprev">${/*html-ok*/ r.failed.map(x => `<li><b>${esc(x.email)}</b> <span class="muted">${esc(x.error)}</span></li>`).join('')}</ul>
            <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-csm="cancel">${tr('Close')}</button></div>`);
        } else { md.remove(); toast(trn('Call sheet sent to {0} recipient', 'Call sheet sent to {0} recipients', r.sent.length)); }
      } catch { b.disabled = false; b.textContent = tr('Send'); /* api() said it */ }
    }
  });
}

// ---- 2.988.0 (#5651): the tab "Call sheets" of a project (projects.js viewChoices, only with Film & Video and the module
// "dispo"): every call sheet of the project as a row (date, shoot day no., location, PDF); a tap opens it (cs_open). "New
// call sheet" asks for the day; the server makes the shoot day in the background (one open place of the disposition) and the
// call sheet (POST /api/team/dispo/callsheets). The way through Disposition > shoot day > "Call sheet" stays as it is.
S.pcsD = S.pcsD || {};  // list id -> {j, v, busy, err}
async function pcs_load(lid, force) {
  const d = S.pcsD[lid] || (S.pcsD[lid] = {});
  if (d.busy || (!force && d.j && d.v === S.v)) return;
  d.busy = true;
  try { d.j = await rawFetch('GET', `/api/team/dispo/callsheets?list=${lid}`); d.v = S.v; d.err = ''; }
  catch (e) { if (e.message === 'auth') return; d.err = e instanceof Offline ? 'offline' : e.message; d.v = S.v; }
  finally { d.busy = false; }
  if (routeList()?.id === lid && pcsOn(routeList())) viewSafeRender();
}
/** after the call sheet dialog: the project's tab (when it is the page shown) loads its rows again (a location saved) */
function pcs_after() { const l = routeList(); if (l && pcsOn(l)) pcs_load(l.id, true); }
/** one row of the tab (a key for the calm view: data-k) */
function pcs_rowHtml(x) {
  const pdf = `/api/team/dispo/callsheet/${encodeURIComponent(x.job)}/pdf?org=${encodeURIComponent(String(x.org_id))}`;
  const no = x.day_no ? tr('Shoot day {0}', x.day_no) : '';
  return `<div class="pcsrow" data-k="cs-${esc(x.job)}"><button type="button" class="pcsopen" data-pcs="open" data-job="${esc(x.job)}" data-org="${esc(String(x.org_id))}">
    <span class="pcsd">${esc(fmtDayAbs(x.date))}${x.start ? ` <span class="muted">${esc(x.start)}</span>` : ''}</span><span class="pcsn">${esc(no)}</span>
    <span class="pcsl">${x.location ? esc(x.location) : `<span class="muted">${tr('No location yet')}</span>`}</span></button>
    <a class="btn sm" href="${esc(pdf)}" download data-pcs="pdf" title="${esc(tr('Call sheet as PDF'))}" aria-label="${esc(tr('Call sheet as PDF'))}">${ic('download', 's')}<span>${tr('PDF')}</span></a></div>`;
}
function viewProjCs() {
  const l = routeList(), d = S.pcsD[l.id];
  if (!d || (!d.busy && d.v !== S.v)) setTimeout(() => pcs_load(l.id), 0);
  const head = listHead(l, {noPill: true});
  if (!d?.j) return `<div class="pov pcs">${/*html-ok*/ head}<div class="muted mhint">${d?.err ? esc(errText(d.err, tr('The call sheets could not be loaded'))) : tr('Loading…')}</div></div>`;
  const j = d.j, can = !!j.can_add && !l.archived;
  const bar = `<div class="pcsbar"><h3>${tr('Call sheets')}</h3><span class="spacer"></span>${can ? `<button type="button" class="btn sm pri" data-pcs="new">${ic('plus', 's')}<span>${tr('New call sheet')}</span></button>` : ''}</div>`;
  const rows = j.callsheets || [];
  const body = j.locked ? `<p class="muted pcsempty">${tr('This project is locked: its call sheets are not shown here.')}</p>`
    : rows.length ? `<div class="pcslist">${/*html-ok*/ rows.map(pcs_rowHtml).join('')}</div>`
      : `<p class="muted pcsempty">${can ? tr('No call sheets yet. "New call sheet" makes one for a shoot day.') : tr('No call sheets yet.')}</p>`;
  return `<div class="pov pcs">${/*html-ok*/ head}${/*html-ok*/ bar}${/*html-ok*/ body}</div>`;
}
/** "New call sheet": the day, then the shoot day in the background and the call sheet opens */
function pcs_new(l) {
  const md = modal(`<h3>${tr('New call sheet')}</h3><div class="row"><label for="pcs-day">${tr('Shoot day')}</label>${/*html-ok*/ dateIn('pcs-day', today())}</div>
    <p class="muted cshint">${tr('The shoot day is added to the disposition with an open place for the crew.')}</p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-pcs="cancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-pcs="make">${ic('check', 's')} ${tr('Create')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest?.('[data-pcs]'); if (!b) return;
    if (b.dataset.pcs === 'cancel') { md.remove(); return; }
    if (b.dataset.pcs !== 'make' || b.disabled) return;
    const day = /** @type {any} */ (cs_one('#pcs-day', md))?.value || '';
    if (!day) { toast(tr('Please select a date')); return; }
    b.disabled = true;
    try {
      const r = await api('POST', '/api/team/dispo/callsheets', {list_id: l.id, date: day});
      md.remove();
      let ids = [r.booking_id];
      histAdd({label: tr('Call sheet created'), srv: true,
        undo: async () => { try { ids = (await api('DELETE', `/api/team/dispo/bookings/${ids[0]}?all=1`)).ids || ids; } catch { /* api() said it */ } pcs_load(l.id, true); },
        redo: async () => { try { await api('POST', '/api/team/dispo/bookings/restore', {ids}); } catch { /* api() said it */ } pcs_load(l.id, true); }});
      await pcs_load(l.id, true);
      if (r.callsheet) cs_open(r.callsheet.job, r.callsheet.org_id);
    } catch { b.disabled = false; /* api() said it */ }
  });
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('#view [data-pcs]'); if (!b) return;
  const l = routeList(); if (!l) return;
  if (b.dataset.pcs === 'open') { cs_open(b.dataset.job, +b.dataset.org); return; }
  if (b.dataset.pcs === 'new') pcs_new(l);
});
