// @ts-check
// 2.111.0 B (#2056): invitations by e-mail to attendees outside Kalmido (the switch in the event editor) and the secret
// subscription link of an event calendar (the calendar's menu). The server decides who really gets a mail
// (kalmido/events/invite.py): new addresses, everyone after a change of time / place / title / repeat, nobody without the tick.
const evi_key = a => a.contact_id ? 'c' + a.contact_id : 'e' + String(a.email || '').toLowerCase();

async function evi_init(md, ev, atts) {  // called once by evEditor after the attendees are drawn
  const st = md._evi = {orig: new Set((ev?.attendees || []).filter(a => !a.user_id && a.email).map(evi_key)), info: null, touched: false, atts, gv: !!ev?.guests_visible};
  md.addEventListener('change', e => { const t = /** @type {any} */ (e.target); if (t.id === 'ev-inv') st.touched = true; if (t.id === 'ev-gv') st.gv = t.checked; });
  evi_draw(md, atts);
  try { st.info = await api('GET', '/api/evinvite' + (ev?.id && evWrite(evCal(ev.cal_id)) ? `?event_id=${ev.id}` : '')); } catch { st.info = null; }
  if (md.isConnected) evi_draw(md, st.atts);
}

function evi_draw(md, atts) {  // the row under "People": only while someone outside Kalmido is (or was) invited
  const st = md._evi; if (!st) return;
  st.atts = atts;
  let row = $('#ev-invrow', md);
  if (!row) { const at = $('.evatts', md); if (!at) return; at.insertAdjacentHTML('afterend', '<div class="row evinv" id="ev-invrow" hidden></div>'); row = $('#ev-invrow', md); }
  const ext = atts.filter(a => !a.user_id && a.email);
  // 2.380 H (#3392): "Guest list visible to guests" - the invitation names all external guests instead of only the recipient
  let gv = $('#ev-gvrow', md);
  if (!gv) { row.insertAdjacentHTML('afterend', '<div class="row evinv" id="ev-gvrow" hidden></div>'); gv = $('#ev-gvrow', md); }
  const gvOn = ext.length && !(st.info && !st.info.mail_ok);  // only where invitations go out
  gv.hidden = !gvOn;
  gv.innerHTML = gvOn ? `<label for="ev-gv">${esc(tr('Guest list visible to guests'))}</label><label class="swc"><input type="checkbox" id="ev-gv" ${st.gv ? 'checked' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Guest list visible to guests'))}</span></label>` : '';
  if (!ext.length && !st.orig.size) { row.hidden = true; row.innerHTML = ''; return; }
  row.hidden = false;
  if (st.info && !st.info.mail_ok) {
    row.innerHTML = `<span class="rlab"></span><span class="muted mhint">${esc(tr('E-mail sending is not set up on this server'))}. ${esc(tr('People outside Kalmido are not notified.'))}</span>`;
    return;
  }
  const cb = $('#ev-inv', md);
  const fresh = ext.some(a => !st.orig.has(evi_key(a))), invited = (st.info?.invited || []).length > 0;
  const on = cb && st.touched ? cb.checked : (fresh || invited);
  row.innerHTML = `<label for="ev-inv">${esc(tr('Send the invitation by e-mail'))}</label><label class="swc"><input type="checkbox" id="ev-inv" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Send the invitation by e-mail'))}</span></label>`;
}

function evi_gv(md) {  // 2.380 H (#3392): the body field guests_visible of the save (null: no external guest, left as it is)
  const st = md._evi; return st && $('#ev-gvrow', md) && !$('#ev-gvrow', md).hidden ? !!st.gv : null;
}

function evi_on(md) {  // the body flag send_invites of the save
  const row = $('#ev-invrow', md), cb = $('#ev-inv', md);
  return !!(row && !row.hidden && cb && cb.checked);
}

// ---- the subscription link of a calendar (GET /ical/ev/<id>.<secret>.ics): each person their own, it shows what they see
async function evf_modal(c) {
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${ic('link', 's')} ${esc(tr('Subscription link'))}</h3><span class="spacer"></span><button class="iconbtn" data-evf="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted">${esc(c.name)}</p><div id="evf-body"><div class="muted mhint">${esc(tr('Loading…'))}</div></div>
    <p class="muted mhint">${esc(tr('Anyone who has the link sees the events of this calendar. Keep it to yourself.'))}</p>
    <details class="evmore"><summary>${esc(tr('How to subscribe'))}</summary><p class="muted">${tr('<b>iPhone / iPad:</b> Settings > Apps > Calendar > Calendar Accounts > Add Account > Other > Add Subscribed Calendar, paste the link. <b>Mac:</b> Calendar > File > New Calendar Subscription.')}</p><p class="muted">${tr('<b>Outlook:</b> Add calendar > Subscribe from web.')}</p></details>
    <div class="foot"><span class="spacer"></span><button class="btn" data-evf="close">${esc(tr('Close'))}</button></div>`);
  md.classList.add('evfmodal');
  const draw = j => {
    const box = $('#evf-body', md); if (!box) return;
    if (!j.url) { box.innerHTML = `<div class="row"><button class="btn pri" data-evf="create">${ic('cal', 's')} ${esc(tr('Create subscription link'))}</button></div>`; return; }
    box.innerHTML = `<div class="row icalrow"><input id="evf-url" readonly value="${esc(j.url)}" aria-label="${esc(tr('Subscription link'))}"><button class="btn pri" data-evf="copy">${ic('copy', 's')} ${esc(tr('Copy'))}</button></div>
      <div class="row evfbtns"><a class="btn" href="${esc(j.url.replace(/^https?:/, 'webcal:'))}">${ic('cal', 's')} ${esc(tr('Open in calendar app'))}</a><button class="btn" data-evf="rotate">${ic('key', 's')} ${esc(tr('New link'))}</button><button class="btn danger" data-evf="off">${esc(tr('Turn the link off'))}</button></div>`;
  };
  try { draw(await api('GET', `/api/evcals/${c.id}/feed`)); } catch { $('#evf-body', md).innerHTML = `<div class="muted mhint">${esc(tr('Only available online.'))}</div>`; }
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-evf]'); if (!b) return;
    const a = b.dataset.evf;
    if (a === 'close') { md.remove(); return; }
    if (a === 'copy') {
      const i = $('#evf-url', md);
      try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); }
      return;
    }
    if (a === 'rotate' && !await askConfirm(tr('Create a new link?'), tr('Calendars subscribed with the old one stop updating.'), {ok: tr('New link'), danger: true})) return;
    if (a === 'off' && !await askConfirm(tr('Turn the link off'), tr('Subscribed calendars stop updating.'), {ok: tr('Turn off'), danger: true})) return;
    b.disabled = true;
    try { draw(await api('POST', `/api/evcals/${c.id}/feed`, {action: a})); } catch { b.disabled = false; return; }
    if (a === 'rotate') toast(tr('New link created, the old one no longer works'));
  });
  return md;
}
