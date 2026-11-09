// @ts-check
/* Kalmido web client: the call sheet of a shoot day (2.802.0, #1956), module "callsheet" (lazyload.js, loaded by the button
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

/** one line of an editable table (key of CS_ROWS) */
function cs_lineHtml(key, r) {
  return `<div class="csrow" data-k="${key}">${CS_ROWS[key].map(([c, label]) => `<input data-c="${c}" maxlength="200" value="${esc(r[c] || '')}" placeholder="${esc(tr(label))}" aria-label="${esc(tr(label))}">`).join('')}<button type="button" class="iconbtn" data-cs="rowdel" aria-label="${esc(tr('Remove line'))}" title="${esc(tr('Remove line'))}">${ic('x', 's')}</button></div>`;
}
function cs_rowsHtml(key, rows) {
  return `<div class="csrows" data-k="${key}" style="--cs-cols:${CS_ROWS[key].length}">${rows.map(r => cs_lineHtml(key, r)).join('')}</div><button type="button" class="btn sm ghost" data-cs="rowadd" data-k="${key}">${ic('plus', 's')} ${tr('Add line')}</button>`;
}

function cs_formHtml(cs) {
  const d = cs.data || {}, a = cs.auto || {}, v = k => esc(d[k] || '');
  const txt = (k, label, ph = '', max = 200) => `<div class="row"><label for="cs-${k}">${tr(label)}</label><input id="cs-${k}" data-f="${k}" maxlength="${max}" value="${v(k)}" placeholder="${esc(ph)}"></div>`;
  const area = (k, label, ph = '', max = 1500) => `<div class="row"><label for="cs-${k}">${tr(label)}</label><textarea id="cs-${k}" data-f="${k}" rows="2" maxlength="${max}" placeholder="${esc(ph)}">${v(k)}</textarea></div>`;
  const cl = a.client || {}, prod = a.production || {};
  const calls = d.calls?.length ? d.calls : CS_CALL_DEPTS.map(x => ({dept: tr(x), time: ''}));
  const crew = (a.crew || []).map(p => `<li class="${p.open ? 'csopen' : ''}"><b>${esc(p.function || '')}</b> <span>${esc(p.name)}</span> <span class="muted">${esc([p.phone, p.mail].filter(Boolean).join(' · '))}</span></li>`).join('');
  return `<h3>${tr('Call sheet')}: ${esc(a.project || a.title || '')}</h3>
    <p class="muted">${esc(fmtDayAbs(a.date))}${a.project && a.title ? ' · ' + esc(a.title) : ''}</p>
    <details class="cssec" open><summary>${tr('Header')}</summary>
      ${txt('subtitle', N_('Subtitle'), a.project && a.title !== a.project ? a.title : '')}
      <div class="csgrid2">${txt('day_no', N_('Shoot day no.'), '1', 12)}${txt('set_name', N_('Set phone: name'))}${txt('set_phone', N_('Set phone: number'), '', 60)}</div>
      <p class="muted cshint">${tr('Production')}: ${esc([prod.name, ...(prod.lines || [])].filter(Boolean).join(', ') || tr('from the master data of the office'))}</p>
      ${area('client', N_('Client'), [cl.name, cl.contact, cl.address, cl.phone, cl.email].filter(Boolean).join('\n') || tr('Company, contact person, phone, e-mail'), 400)}
      ${area('agency', N_('Agency'), tr('optional'), 400)}
      <p class="lbl">${tr('Contacts')}</p><p class="muted cshint">${tr('Empty: the crew functions of the bookings with their phone numbers.')}</p>${cs_rowsHtml('contacts', d.contacts || [])}
    </details>
    <details class="cssec" open><summary>${tr('Location')}</summary>
      ${txt('loc_name', N_('Location'))}
      <div class="row"><label for="cs-loc_address">${tr('Address')}</label><input id="cs-loc_address" data-f="loc_address" maxlength="300" value="${v('loc_address')}"></div>
      <p class="csmap">${d.loc_address ? `<a href="${esc(cs_mapHref(d.loc_address))}" target="_blank" rel="noopener noreferrer">${ic('link', 's')} ${tr('Open in maps')}</a>` : ''}</p>
      ${area('parking', N_('Parking / directions'))}
      ${area('transit', N_('Public transport'), tr('Lines and stop'), 1000)}
    </details>
    <details class="cssec" open><summary>${tr('Times')}</summary>
      <p class="lbl">${tr('Call on set')}</p>${cs_rowsHtml('calls', calls)}
      <div class="csgrid2">${txt('shoot_start', N_('Shoot start'), a.start || '07:30', 20)}${txt('lunch_from', N_('Lunch from'), '13:00', 20)}${txt('lunch_to', N_('Lunch until'), '14:00', 20)}${txt('wrap', N_('Wrap'), a.end || '', 20)}${txt('strike', N_('Strike until'), '', 20)}</div>
      ${txt('weather', N_('Weather'), tr('Sunrise, sunset, temperature'), 400)}
      ${area('important', N_('Important'), tr('optional'), 3000)}
    </details>
    <details class="cssec"${d.cast?.length ? ' open' : ''}><summary>${tr('Cast')}</summary>${cs_rowsHtml('cast', d.cast || [])}</details>
    <details class="cssec"${d.transport?.length ? ' open' : ''}><summary>${tr('Transport')}</summary><p class="muted cshint">${tr('Empty call time: "Own arrangement".')}</p>${cs_rowsHtml('transport', d.transport || [])}</details>
    <details class="cssec"><summary>${tr('Crew list')}</summary>${crew ? `<ul class="cscrew">${crew}</ul>` : `<p class="muted">${tr('Nobody booked yet.')}</p>`}<p class="muted cshint">${tr('The crew comes from the bookings of this shoot day; phone numbers and e-mails from the address book.')}</p></details>
    ${(a.shot_days || []).length ? `<div class="row"><label for="cs-shot_day">${tr('Shots of the day')}</label><select id="cs-shot_day" data-f="shot_day"><option value="">${tr('None')}</option>${a.shot_days.map(n => `<option value="${esc(n)}" ${d.shot_day === n ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>` : ''}
    <details class="cssec"${cs.sketch ? ' open' : ''}><summary>${tr('Directions sketch')}</summary>
      <div class="cssketch">${cs.sketch ? `<img src="${esc(cs.sketch_url)}&v=${encodeURIComponent(cs.updated_at)}" alt="${esc(tr('Directions sketch'))}">` : `<p class="muted">${tr('A screenshot or drawing (PNG or JPEG); it gets a page of its own, with "Parking / directions" below it.')}</p>`}</div>
      <label class="btn sm">${ic('upload', 's')} ${cs.sketch ? tr('Replace picture') : tr('Select picture')}<input type="file" id="cs-sketch" accept="image/png,image/jpeg" hidden></label>
      ${cs.sketch ? `<button type="button" class="btn sm ghost" data-cs="sketchdel">${ic('trash', 's')} ${tr('Remove picture')}</button>` : ''}
    </details>
    ${area('attachments', N_('More attachments'), tr('One per line'), 1000)}
    <p class="cserr" role="alert" hidden></p>
    <div class="foot"><button class="btn" data-cs="close">${tr('Close')}</button><span class="spacer"></span>
      <button class="btn" data-cs="pdf">${ic('download', 's')} ${tr('PDF')}</button>${navigator.canShare ? `<button class="btn" data-cs="share">${ic('share', 's')} ${tr('Share')}</button>` : ''}
      ${cs.can_edit ? `<button class="btn pri" data-cs="save">${ic('check', 's')} ${tr('Save')}</button>` : ''}</div>`;
}

/** the form's values as the server's data object */
function cs_collect(md) {
  /** @type {Record<string, any>} */
  const out = {};
  cs_all('[data-f]', md).forEach(el => { const v = el.value.trim(); if (v) out[el.dataset.f] = v; });
  for (const k of Object.keys(CS_ROWS)) {
    const rows = cs_all(`.csrow[data-k="${k}"]`, md).map(r => Object.fromEntries(cs_all('input', r).map(i => [i.dataset.c, i.value.trim()]))).filter(r => Object.values(r).some(Boolean));
    if (k === 'calls' && rows.every(r => !r.time)) continue;  // only the suggested departments without a time: nothing to keep
    if (rows.length) out[k] = rows;
  }
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
      cs = r.callsheet; sketch = undefined; err('');
      const put = x => async () => { try { const cur = (await api('GET', cs_url(job, org))).callsheet; await api('PUT', cs_url(job, org), {...x, expect_updated_at: cur.updated_at}); } catch { /* api() said it */ } };
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
  md.addEventListener('change', async e => {
    const t = /** @type {any} */ (e.target);
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
    if (k === 'close') { md.remove(); return; }
    if (k === 'rowadd') { const box = cs_one(`.csrows[data-k="${b.dataset.k}"]`, md); if (!box) return; box.insertAdjacentHTML('beforeend', cs_lineHtml(b.dataset.k, {})); cs_one('.csrow:last-child input', box)?.focus(); return; }
    if (k === 'rowdel') { b.closest('.csrow')?.remove(); return; }
    if (k === 'sketchdel') { sketch = ''; const box = cs_one('.cssketch', md); if (box) setHtml(box, `<p class="muted">${tr('The picture goes with "Save".')}</p>`); b.remove(); return; }
    if (k === 'reload') { if (md._cur) { cs = md._cur; md._cur = null; sketch = undefined; draw(); } return; }
    if (k === 'save') { b.disabled = true; await save(); b.disabled = false; return; }
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
