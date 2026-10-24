// @ts-check
// 2.140.0 B (#2136): a private device <-> a piece of office equipment (life/devlink.py). The device's task panel shows
// "Linked with ..." with a jump to the equipment, "Update from there" and "Remove link", or "Add to the office equipment"
// (own office / an organisation as admin; the net price is confirmed in the dialog). A broken link (left the organisation,
// the equipment deleted) is a hint with "Remove link", never an error. The office side is in office_assets.js (astLink*).
// Loaded with life.js (lazyload.js LD_MODS life); life.js lifeDetailHtml calls dlDeviceHtml.
const DL = {byTask: {}};

function dlDeviceHtml(t, ro) {
  if (!t || t.id <= 0) return '';
  const st = DL.byTask[t.id];
  if (!st) setTimeout(() => dlLoad(t.id), 0);
  return `<div class="dlbox" data-dl-task="${t.id}" data-ro="${ro ? 1 : 0}">${st ? dlInner(t.id, st, ro) : ''}</div>`;
}
async function dlLoad(tid) {
  let j; try { j = await rawFetch('GET', `/api/life/devices/${tid}/link`); } catch { j = {link: null, offices: []}; }  // no module / no right: nothing to offer
  DL.byTask[tid] = j;
  for (const box of $$(`.dlbox[data-dl-task="${tid}"]`)) box.innerHTML = dlInner(tid, j, box.dataset.ro === '1');
}
function dlInner(tid, st, ro) {
  const l = st.link, o = l?.other;
  const row = (label, val) => `<div class="row"><label>${esc(label)}</label><span class="lacts">${val}</span></div>`;
  if (!l) {
    if (ro || !(st.offices || []).length) return '';
    return row(tr('Office'), `<button type="button" class="btn sm" data-dl="to-office" data-id="${tid}">${ic('building', 's')}<span>${tr('Add to the office equipment')}</span></button>`);
  }
  const rm = `<button type="button" class="btn sm" data-dl="unlink" data-link="${l.id}" data-id="${tid}">${ic('x', 's')}<span>${tr('Remove link')}</span></button>`;
  if (o.state !== 'ok') {
    const why = o.state === 'noaccess' ? tr('The linked office equipment is out of reach (no access to that office any more).') : tr('The linked office equipment does not exist any more.');
    return row(tr('Office'), `<span class="muted dlhint">${ic('alert', 's')} ${esc(why)}</span>${ro ? '' : rm}`);
  }
  return row(tr('Office'), `<span class="dllink">${ic('link', 's')} ${esc(tr('Linked with “{0}”', o.name))}<small class="muted">${esc(o.office_name)}${o.archived ? ' · ' + esc(tr('archived')) : ''}</small></span>
    <button type="button" class="btn sm" data-dl="open-eq" data-id="${tid}">${ic('right', 's')}<span>${tr('Open')}</span></button>
    ${ro ? '' : `<button type="button" class="btn sm" data-dl="pull" data-link="${l.id}" data-id="${tid}">${ic('repeat', 's')}<span>${tr('Update from there')}</span></button>${rm}`}`);
}

// the dialog: which office, the name and the net price (the device's price is what was paid)
function dlToOffice(tid) {
  const t = S.tasks.get(tid), f = t?.fam || {}, offs = DL.byTask[tid]?.offices || [];
  if (!offs.length) return;
  const name = [f.name, f.model].filter(Boolean).join(' ');
  const md = modal(`<h3>${ic('building', 's')} ${tr('Add to the office equipment')}</h3>
    <p class="muted">${esc(tr('A copy of the device in the office equipment, linked with it. Later changes are not copied by themselves.'))}</p>
    ${offs.length > 1 ? `<div class="row"><label for="dl-off">${tr('Office')}</label><select id="dl-off">${offs.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('')}</select></div>` : `<input type="hidden" id="dl-off" value="${offs[0].id}">`}
    <div class="row"><label for="dl-name">${tr('Name')}</label><input id="dl-name" maxlength="200" value="${esc(name)}"></div>
    <div class="row"><label for="dl-net">${tr('Purchase price (net)')}</label><input id="dl-net" class="numin" inputmode="decimal" value="${f.price != null ? esc(fmtNum(f.price, 2)) : ''}" aria-describedby="dl-neth"></div>
    <p class="muted shint" id="dl-neth">${esc(tr('Without VAT. The device shows what you paid; please check the net price.'))}</p>
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Add')}</button></div>`);
  md.classList.add('dldlg');
  const mdq = /** @type {any} */ (md);  // $() takes a root element; tsc reads its parameter as a Document
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest?.('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'save') return;
    b.disabled = true;
    const net = String($('#dl-net', mdq).value || '').trim().replace(/\s/g, '');
    const body = {office_id: +$('#dl-off', mdq).value || 0, name: $('#dl-name', mdq).value, ...(net ? {purchase_net: numBody(net)} : {})};
    try { DL.byTask[tid] = {link: (await rawFetch('POST', `/api/life/devices/${tid}/to-office`, body)).link, offices: []}; }
    catch (er) { const x = $('.aerr', mdq); if (x) x.textContent = er.message || ''; b.disabled = false; return; }
    md.remove(); dlLoad(tid);
    toast(tr('Added to the office equipment'));
  });
  setTimeout(() => $('#dl-name', mdq)?.focus(), 30);
}

// to the equipment: the office of its workspace, then its editor
async function dlOpenEquip(tid) {
  const o = DL.byTask[tid]?.link?.other; if (!o || o.state !== 'ok') return;
  if (typeof wsCur === 'function' && wsCur() !== o.ws && typeof wsSet === 'function') await wsSet(o.ws);
  go('office/equipment');
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 150));
    const row = typeof ofcRow === 'function' ? ofcRow('equipment', o.equipment_id) : null;
    if (row && typeof ofcModal === 'function') { ofcModal('equipment', row); return; }
  }
}

document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-dl]'); if (!b || b.disabled) return;
  e.preventDefault();
  const tid = +b.dataset.id, lid = +b.dataset.link;
  if (b.dataset.dl === 'to-office') dlToOffice(tid);
  else if (b.dataset.dl === 'open-eq') dlOpenEquip(tid);
  else if (b.dataset.dl === 'pull') {
    if (!await askConfirm(tr('Update from the office equipment?'), tr('Name, serial number, purchase date and price are taken over from there.'), {ok: tr('Update')})) return;
    b.disabled = true;
    try { await rawFetch('POST', `/api/life/device-links/${lid}/pull`, {into: 'device'}); toast(tr('Updated')); } catch (er) { toast(er.message || tr('unknown')); }
    b.disabled = false; dlLoad(tid);
  } else if (b.dataset.dl === 'unlink') {
    if (!await askConfirm(tr('Remove the link?'), tr('The device and the office equipment both stay; only the link goes.'), {ok: tr('Remove link')})) return;
    b.disabled = true;
    try { await rawFetch('DELETE', `/api/life/device-links/${lid}`); } catch (er) { toast(er.message || tr('unknown')); }
    delete DL.byTask[tid]; dlLoad(tid);
  }
});
