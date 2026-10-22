// @ts-check
/* Kalmido web client: 2.141.0 A (#2141, #2138) the own mailbox of a workspace and writing from the e-mail filing.
   - #mailhub (hubmail.js hbm_hubView): the section "Mailbox" -- per workspace its state; admins of an organisation (a person
     for their own private space) set up IMAP (receiving) and SMTP (sending) with "Save and check"; the passwords are never
     shown again ("unchanged" = keep them)
   - the reading view of a filed mail: "Reply"; a client's / project's e-mails: "New e-mail" -- one plain text dialog,
     the sent mail is filed with the others ("Sent"). Server: kalmido/hub/mailbox.py.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const HMB = {j: null, loading: false, at: 0};
async function hmb_load() {
  HMB.loading = true;
  try { HMB.j = await rawFetch('GET', '/api/hubmail/mailboxes'); } catch { HMB.j = HMB.j || {spaces: []}; }
  HMB.loading = false; HMB.at = Date.now();
  if (document.querySelector('.hbmhub')) { if (S.route.mod === 'clients' && typeof ms_clDraw === 'function') ms_clDraw(); else render(); }
}
function hmb_state() {
  if (!HMB.loading && (!HMB.at || Date.now() - HMB.at > 30000)) { HMB.loading = true; setTimeout(hmb_load, 0); }
  return HMB.j;
}
// the section of the hub view (hubmail.js hbm_hubView)
function hmb_hubSection() {
  const j = hmb_state(); if (!j) return '';
  const rows = (j.spaces || []).filter(x => x.manage || x.set).map(x => {
    const what = !x.set ? tr('No mailbox yet') : [x.receive ? tr('receives') : '', x.send ? tr('sends') : ''].filter(Boolean).join(' · ') + (x.active ? '' : ' · ' + tr('paused'));
    return `<li class="hbmsp hmbsp" data-hmbws="${esc(x.ws)}"><span class="hbmspn"><b>${esc(x.name)}</b><small class="muted">${x.address ? esc(x.address) + ' · ' : ''}${esc(what)}</small>
        ${x.error_text ? `<small class="hmberr" role="status">${ic('info', 's')} ${esc(x.error_text)}</small>` : ''}</span>
      ${x.manage ? `<button type="button" class="btn sm" data-hmba="edit" data-ws="${esc(x.ws)}">${ic('gear', 's')}<span>${tr(x.set ? 'Change' : 'Set up')}</span></button>` : ''}</li>`;
  }).join('');
  if (!rows) return '';
  return `<h4>${tr('Mailbox')}</h4><p class="muted">${tr('A workspace can fetch its own mailbox: its mails are filed here like forwarded ones, and replies go out from its address.')}</p><ul class="hbmspaces hmbspaces" role="list">${rows}</ul>`;
}

// ---- the mailbox dialog
const hmb_q = (md, sel) => /** @type {any} */ (md.querySelector(sel));
const hmb_v = (md, id) => String(hmb_q(md, '#' + id)?.value ?? '').trim();
function hmb_formHtml(b) {
  const x = b || {}, pw = set => set ? esc(tr('unchanged')) : '';
  const inp = (id, label, val, extra = '') => `<div class="row"><label for="${id}">${label}</label><input id="${id}" value="${esc(val ?? '')}" autocomplete="off" ${extra}></div>`;
  return `<h4>${tr('Receiving (IMAP)')}</h4>
    ${inp('hmb-ih', tr('Server'), x.imap_host, 'placeholder="imap.example.com" inputmode="url" spellcheck="false"')}
    ${inp('hmb-ip', tr('Port'), x.imap_port || '', 'inputmode="numeric" placeholder="993"')}
    <div class="row"><label for="hmb-is">${tr('Encryption')}</label><select id="hmb-is"><option value="1" ${x.imap_ssl !== false ? 'selected' : ''}>SSL / TLS</option><option value="0" ${x.imap_ssl === false ? 'selected' : ''}>${tr('None')}</option></select></div>
    ${inp('hmb-iu', tr('User|mailbox'), x.imap_user, 'spellcheck="false"')}
    <div class="row"><label for="hmb-iw">${tr('Password')}</label><input id="hmb-iw" type="password" autocomplete="new-password" placeholder="${pw(x.imap_password_set)}"></div>
    ${inp('hmb-if', tr('Folder'), x.imap_folder || 'INBOX', 'spellcheck="false"')}
    <h4>${tr('Sending (SMTP)')}</h4>
    ${inp('hmb-sh', tr('Server'), x.smtp_host, 'placeholder="smtp.example.com" inputmode="url" spellcheck="false"')}
    ${inp('hmb-sp', tr('Port'), x.smtp_port || '', 'inputmode="numeric" placeholder="587"')}
    <div class="row"><label for="hmb-st">${tr('Encryption')}</label><select id="hmb-st">${[['starttls', 'STARTTLS'], ['ssl', 'SSL / TLS'], ['none', tr('None')]].map(([v, l]) => `<option value="${v}" ${(x.smtp_tls || 'starttls') === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
    ${inp('hmb-su', tr('User|mailbox'), x.smtp_user, 'spellcheck="false"')}
    <div class="row"><label for="hmb-sw">${tr('Password')}</label><input id="hmb-sw" type="password" autocomplete="new-password" placeholder="${pw(x.smtp_password_set)}"></div>
    ${inp('hmb-fa', tr('Sender address'), x.from_addr, 'type="email" placeholder="office@example.com" spellcheck="false"')}
    ${inp('hmb-fn', tr('Sender name'), x.from_name, 'maxlength="120"')}
    ${b ? `<div class="row"><label for="hmb-on">${tr('Fetch mails')}</label><select id="hmb-on"><option value="1" ${x.active ? 'selected' : ''}>${tr('On')}</option><option value="0" ${x.active ? '' : 'selected'}>${tr('Paused')}</option></select></div>` : ''}`;
}
function hmb_checkHtml(j) {
  const ch = j?.check, b = j?.box;
  const line = (k, label) => ch?.[k] ? `<li class="${ch[k].ok ? 'hmbok' : 'hmbbad'}">${ic(ch[k].ok ? 'check' : 'x', 's')}<span>${esc(label)}: ${esc(ch[k].ok ? tr('works') : ch[k].text)}</span></li>` : '';
  const out = ch ? line('imap', tr('Receiving')) + line('smtp', tr('Sending')) : '';
  const st = !ch && b ? (b.error_text ? `<li class="hmbbad">${ic('info', 's')}<span>${esc(b.error_text)}</span></li>` : b.polled_at ? `<li class="muted">${ic('check', 's')}<span>${esc(tr('Last fetched {0}', fmtWhen(b.polled_at)))}</span></li>` : '') : '';
  return out || st ? `<ul class="hmbcheck" role="status">${out || st}</ul>` : '';
}
async function hmb_dialog(ws) {
  let j; try { j = await api('GET', `/api/hubmail/mailbox?ws=${encodeURIComponent(ws)}`); } catch { return; }
  $('.hmbdlg')?.remove();
  const name = (HMB.j?.spaces || []).find(x => x.ws === ws)?.name || wsName(ws);
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${tr('Mailbox')} · ${esc(name)}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <p class="muted">${tr('Mails of this mailbox are filed in this workspace only; the passwords are stored encrypted and never shown again.')}</p>
    <div class="hmbform">${hmb_formHtml(j.box)}</div><div class="hmbres">${hmb_checkHtml(j)}</div><p class="hmb-err" role="alert"></p>
    <div class="foot">${j.box ? `<button type="button" class="btn danger" data-hmbd="del">${ic('trash', 's')} ${tr('Remove')}</button>` : ''}${j.box?.imap_host ? `<button type="button" class="btn" data-hmbd="poll">${ic('sync', 's')} ${tr('Fetch now')}</button>` : ''}<span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button><button type="button" class="btn pri" data-hmbd="save">${tr('Save and check')}</button></div>`);
  md.classList.add('hmbdlg');
  const errEl = hmb_q(md, '.hmb-err');
  md.addEventListener('click', async e => {
    if (/** @type {any} */ (e.target).closest('[data-m="close"]')) { modalClose(md); hmb_load(); return; }
    const b = /** @type {any} */ (e.target).closest('[data-hmbd]'); if (!b || b.disabled) return;
    errEl.textContent = '';
    if (b.dataset.hmbd === 'del') {
      if (!await askConfirm(tr('Remove the mailbox?'), tr('Its mails are no longer fetched and nothing is sent from it. The filed e-mails stay.'), {ok: tr('Remove'), danger: true})) return;
      try { await api('DELETE', `/api/hubmail/mailbox?ws=${encodeURIComponent(ws)}`); } catch { return; }
      modalClose(md); hmb_load(); return;
    }
    if (b.dataset.hmbd === 'poll') {
      try { await api('POST', '/api/hubmail/mailbox/poll', {ws}); toast(tr('The mailbox is fetched now')); } catch { /* shown */ }
      setTimeout(() => { hmb_load(); if (typeof hbm_reloadAll === 'function') hbm_reloadAll(); }, 4000);
      return;
    }
    const port = id => { const v = hmb_v(md, id); return v ? +v : 0; };
    const d = {ws, imap_host: hmb_v(md, 'hmb-ih'), imap_port: port('hmb-ip'), imap_ssl: hmb_q(md, '#hmb-is').value === '1', imap_user: hmb_v(md, 'hmb-iu'),
      imap_folder: hmb_v(md, 'hmb-if'), smtp_host: hmb_v(md, 'hmb-sh'), smtp_port: port('hmb-sp'), smtp_tls: hmb_q(md, '#hmb-st').value,
      smtp_user: hmb_v(md, 'hmb-su'), from_addr: hmb_v(md, 'hmb-fa'), from_name: hmb_v(md, 'hmb-fn'), check: true};
    if (Number.isNaN(d.imap_port) || Number.isNaN(d.smtp_port)) { errEl.textContent = tr('Invalid value: {0}', tr('Port')); return; }
    const on = hmb_q(md, '#hmb-on'); if (on) d.active = on.value === '1';
    const iw = hmb_q(md, '#hmb-iw').value, sw = hmb_q(md, '#hmb-sw').value;
    if (iw) d.imap_password = iw;
    if (sw) d.smtp_password = sw;
    b.disabled = true; b.classList.add('busy');
    let r;
    try { r = await rawFetch('PUT', '/api/hubmail/mailbox', d); }
    catch (x) { errEl.textContent = x.message || tr('Error'); return; }
    finally { b.disabled = false; b.classList.remove('busy'); }
    hmb_q(md, '#hmb-iw').value = ''; hmb_q(md, '#hmb-sw').value = '';
    hmb_q(md, '.hmbform').innerHTML = hmb_formHtml(r.box);
    hmb_q(md, '.hmbres').innerHTML = hmb_checkHtml(r);
    hmb_load();
  });
}

// ---- writing: reply / new e-mail
const hmb_replyBtn = m => m && m.can_write ? `<button type="button" class="btn" data-hmbreply="${m.id}">${ic('reply', 's')} ${tr('Reply')}</button>` : '';
function hmb_newBtn(key, j) {
  const [k, id] = String(key || '').split(':');
  if (!j?.can_send || (k !== 'client' && k !== 'list')) return '';
  return `<button type="button" class="btn sm" data-hmbnew="${k}:${id}">${ic('send', 's')}<span>${tr('New e-mail')}</span></button>`;
}
async function hmb_compose(src) {
  const qs = Object.entries(src).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  let j; try { j = await api('GET', `/api/hubmail/compose?${qs}`); } catch { return; }
  $('.hmbcdlg')?.remove();
  const from = j.from?.address ? (j.from.name ? `${j.from.name} <${j.from.address}>` : j.from.address) : '';
  const to = (j.to || []).map(x => x.address).join(', ');
  const sug = (j.suggest || []).filter(x => !(j.to || []).some(y => y.address.toLowerCase() === x.address.toLowerCase()));
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${tr(j.reply ? 'Reply' : 'New e-mail')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    ${j.can_send ? `<div class="hbmhdr"><div class="hbmhf"><span class="muted">${tr('From')}</span><span>${esc(from)}</span></div>${j.via === 'server' && j.reply_to ? `<div class="hbmhf"><span class="muted">${tr('Replies to')}</span><span>${esc(j.reply_to)}</span></div>` : ''}</div>`
      : `<div class="shint keep">${ic('info', 's')} ${esc(j.hint || '')}</div>`}
    <div class="row"><label for="hmb-to">${tr('To|mail')}</label><input id="hmb-to" type="text" inputmode="email" autocomplete="off" spellcheck="false" value="${esc(to)}" placeholder="name@example.com"></div>
    ${sug.length ? `<div class="hmbsug" role="group" aria-label="${esc(tr('Suggested recipients'))}">${sug.map(x => `<button type="button" class="btn sm" data-hmbto="${esc(x.address)}" title="${esc(x.address)}">${ic('plus', 's')}<span>${esc(x.name || x.address)}</span></button>`).join('')}</div>` : ''}
    <div class="row"><label for="hmb-cc">${tr('Cc')}</label><input id="hmb-cc" type="text" inputmode="email" autocomplete="off" spellcheck="false"></div>
    <div class="row"><label for="hmb-sub">${tr('Subject')}</label><input id="hmb-sub" type="text" maxlength="300" value="${esc(j.subject || '')}"></div>
    <textarea id="hmb-text" class="hmbtext" rows="12" aria-label="${esc(tr('Text'))}">${esc(j.text || '')}</textarea>
    <p class="hmb-err" role="alert"></p>
    <div class="foot"><span class="muted hmbnote">${tr('Plain text; the mail is filed here after sending.')}</span><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-hmbc="send" ${j.can_send ? '' : 'disabled'}>${ic('send', 's')} ${tr('Send')}</button></div>`);
  md.classList.add('hmbcdlg');
  const ta = hmb_q(md, '#hmb-text');
  setTimeout(() => { if (j.reply) { ta.focus(); ta.setSelectionRange(0, 0); ta.scrollTop = 0; } else hmb_q(md, to ? '#hmb-sub' : '#hmb-to')?.focus(); }, 0);
  // 2.144.2 A (#2441): the first tap into an untouched reply keeps the cursor above the quote (touch put it at the end)
  if (j.reply) { const v0 = ta.value; ta.addEventListener('pointerup', () => setTimeout(() => { if (ta.value === v0) { ta.setSelectionRange(0, 0); ta.scrollTop = 0; } }, 0), {once: true}); }
  const errEl = hmb_q(md, '.hmb-err');
  md.addEventListener('click', async e => {
    if (/** @type {any} */ (e.target).closest('[data-m="close"]')) { modalClose(md); return; }
    const t = /** @type {any} */ (e.target).closest('[data-hmbto]');
    if (t) { const f = hmb_q(md, '#hmb-to'), cur = f.value.trim(); f.value = cur ? `${cur.replace(/,\s*$/, '')}, ${t.dataset.hmbto}` : t.dataset.hmbto; t.remove(); return; }
    const b = /** @type {any} */ (e.target).closest('[data-hmbc="send"]'); if (!b || b.disabled) return;
    errEl.textContent = '';
    const body = {...(j.reply ? {reply: j.reply} : j.list_id ? {list_id: j.list_id} : {client_id: j.client_id}),
      to: hmb_v(md, 'hmb-to'), cc: hmb_v(md, 'hmb-cc'), subject: hmb_v(md, 'hmb-sub'), text: ta.value};
    if (!body.to) { errEl.textContent = tr('Please enter a recipient'); hmb_q(md, '#hmb-to').focus(); return; }
    b.disabled = true; b.classList.add('busy');
    try { await rawFetch('POST', '/api/hubmail/send', body); }
    catch (x) {
      errEl.textContent = x.message || tr('Error');
      if (x.status === 502 && typeof hbm_reloadAll === 'function') hbm_reloadAll();  // the mail is filed as "not sent"
      return;
    } finally { b.disabled = false; b.classList.remove('busy'); }
    modalClose(md);
    toast(tr('E-mail sent'));
    if (typeof hbm_reloadAll === 'function') hbm_reloadAll();
  });
}

document.addEventListener('click', e => {
  const r = /** @type {any} */ (e.target).closest('[data-hmbreply]');
  if (r) { e.preventDefault(); const md = r.closest('.modal'); if (md) modalClose(md); hmb_compose({reply: +r.dataset.hmbreply}); return; }
  const n = /** @type {any} */ (e.target).closest('[data-hmbnew]');
  if (n) { e.preventDefault(); const [k, id] = n.dataset.hmbnew.split(':'); hmb_compose(k === 'client' ? {client_id: +id} : {list_id: +id}); return; }
  const a = /** @type {any} */ (e.target).closest('[data-hmba="edit"]');
  if (a) { e.preventDefault(); hmb_dialog(a.dataset.ws); }
});
