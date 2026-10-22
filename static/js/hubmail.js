/* Kalmido web client: 2.84.0 A (#1198) e-mail as an input of the hub -- the section "E-mails" of a client's card and of a
   project page (list, search, the reading view, "Copy address") and the hub inbox (#mailhub, from Office > Clients): the
   own filing address per workspace and the mails "Not assigned" with Assign / Delete. Server: kalmido/hub/hubmail.py.
   Assign and Delete = one undo step each. 2.141.0 A (#2141, #2138): the mailbox of a workspace + Reply / New e-mail in
   hubmailbox.js. 2.141.0 B (#2140, #2139): the HTML view (sandboxed frame of the server's cleaned page), Task / Event from a mail.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const HBM = {s: {}};  // key ('client:<id>' | 'list:<id>' | 'inbox:0') -> {j, q, loading, seq}
function hbm_url(key) {
  const [k, id] = key.split(':'), q = (HBM.s[key]?.q || '').trim();
  const u = k === 'inbox' ? '/api/hubmail/inbox' : `/api/hubmail/mails?${k === 'client' ? 'client_id' : 'list_id'}=${id}`;
  return q ? `${u}${u.includes('?') ? '&' : '?'}q=${encodeURIComponent(q)}` : u;
}
async function hbm_load(key) {
  const s = HBM.s[key] = HBM.s[key] || {q: ''};
  const seq = s.seq = (s.seq || 0) + 1;
  s.loading = true;
  try { const j = await rawFetch('GET', hbm_url(key)); if (seq === s.seq) s.j = j; }
  catch (e) { if (seq === s.seq) s.j = s.j || {mails: [], total: 0, err: e.message || ''}; }
  s.loading = false; s.at = Date.now();
  if (seq === s.seq) hbm_paint(key);
}
const hbm_reloadAll = () => Promise.all(Object.keys(HBM.s).map(hbm_load));
// a section paints its own body (the search field keeps the focus); the first answer draws the whole view once
function hbm_paint(key) {
  const s = HBM.s[key], first = !s.painted, el = document.querySelector(`[data-hbm="${key}"]`);
  s.painted = true;
  if (el && !first && !key.startsWith('inbox')) { const b = el.querySelector('.hbmbody'); if (b) b.innerHTML = hbm_listHtml(key); const h = el.querySelector('.hbmhead'); if (h) h.innerHTML = hbm_headHtml(key); }
  else if (S.route.mod === 'clients') ms_clDraw();
  else render();
}
// loaded on the first paint, again when the section is drawn after half a minute (new mails come in the background)
const hbm_state = key => {
  const s = HBM.s[key];
  if (!s) { HBM.s[key] = {q: ''}; setTimeout(() => hbm_load(key), 0); }
  else if (!s.loading && s.at && Date.now() - s.at > 30000) { s.loading = true; setTimeout(() => hbm_load(key), 0); }
  return HBM.s[key];
};

function hbm_headHtml(key) {
  const j = HBM.s[key]?.j;
  const nw = typeof hmb_newBtn === 'function' ? hmb_newBtn(key, j) : '';  // 2.141.0 A (#2138): hubmailbox.js
  if (!j || key.startsWith('inbox') || !j.can_address) return nw;
  return `${nw}<button type="button" class="btn sm" data-hbma="copy" data-hbmk="${key}" title="${esc(tr('Mails to this address are filed here'))}">${ic('copy', 's')}<span>${tr('Copy address')}</span></button>${j.address ? `<button type="button" class="iconbtn" data-hbma="menu" data-hbmk="${key}" aria-haspopup="menu" aria-label="${esc(tr('Address'))}" title="${esc(tr('Address'))}">${ic('dots', 's')}</button>` : ''}`;
}
function hbm_listHtml(key) {
  const s = HBM.s[key], j = s?.j, inbox = key.startsWith('inbox');
  if (!j) return `<p class="muted">${tr('Loading…')}</p>`;
  if (!j.mails.length) return `<p class="muted hbmempty">${(s.q || '').trim() ? tr('No e-mail matches.') : inbox ? tr('Nothing waits here: every e-mail found its client.')
    : j.enabled ? tr('No e-mails yet. Send or forward mails to the address of this client or project (Copy address), they are filed here.') : tr('No e-mails yet.')}</p>`;
  const more = j.total > j.mails.length ? `<p class="muted">${tr('{0} more: search to narrow them down', j.total - j.mails.length)}</p>` : '';
  return `<ul class="hbmlist" role="list">${j.mails.map(m => `<li class="hbmrow">
    <button type="button" class="hbmopen" data-hbmopen="${m.id}" data-hbmk="${key}">
      <span class="hbmtop"><b class="hbmfrom">${m.dir === 'out' ? `${ic('send', 's')} ${esc(tr('To {0}', m.to_list || ''))}` : esc(m.from_name || m.from_addr || tr('Unknown sender'))}</b>${m.state === 'failed' ? `<span class="hmbtag bad">${tr('Not sent')}</span>` : m.state === 'sending' ? `<span class="hmbtag">${tr('Sending…')}</span>` : m.dir === 'out' ? `<span class="hmbtag">${tr('Sent')}</span>` : ''}${m.files ? `<span class="hbmclip muted" title="${esc(trn('{0} attachment', '{0} attachments', m.files))}">${ic('clip', 's')}${m.files}</span>` : ''}<time class="muted">${esc(fmtWhen(m.sent_at || m.created_at))}</time></span>
      <span class="hbmsubj">${esc(m.subject || tr('(no subject)'))}</span>
      ${key.startsWith('client') && m.list_name ? `<span class="muted hbmproj">${ic('brief', 's')} ${esc(m.list_name)}</span>` : ''}
    </button>
    ${inbox ? `<span class="hbmacts"><button type="button" class="btn sm" data-hbmasg="${m.id}" data-hbmk="${key}">${tr('Assign')}</button><button type="button" class="iconbtn" data-hbmdel="${m.id}" data-hbmk="${key}" aria-label="${esc(tr('Delete'))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></span>` : ''}
  </li>`).join('')}</ul>${more}`;
}
function hbm_bodyHtml(key) {
  const s = hbm_state(key);
  return `<div class="hbmwrap" data-hbm="${key}"><div class="hbmq">${ic('search', 's')}<input type="search" data-hbmq="${key}" value="${esc(s.q || '')}" placeholder="${esc(tr('Search e-mails'))}" aria-label="${esc(tr('Search e-mails'))}" autocomplete="off" enterkeyhint="search"></div>
    <div class="hbmhead hbmhl">${hbm_headHtml(key)}</div><div class="hbmbody">${hbm_listHtml(key)}</div></div>`;
}
// the client's card (clientpage.js) and the project page (projects.js); nothing before the first answer, nothing while the
// mail input is off and nothing is filed
function hbm_clientHtml(c) {
  const key = 'client:' + c.id, j = hbm_state(key).j;
  if (!j || (!j.enabled && !j.can_send && !j.total && !(HBM.s[key].q || '').trim())) return '';  // shown once loaded (2.141.0 A: or sending works)
  return `<div class="ctsec hbmsec"><h4>${ic('mail', 's')} ${tr('E-mails')}</h4>${hbm_bodyHtml(key)}</div>`;
}
function hbm_projHtml(l) {
  if (!l || l.kind !== 'project' || l.e2e) return '';
  const key = 'list:' + l.id, j = hbm_state(key).j;
  if (!j || (!j.enabled && !j.can_send && !j.total && !(HBM.s[key].q || '').trim())) return '';  // shown once loaded (2.141.0 A: or sending works)
  return `<section class="povs hbmsec hbmpov" id="pov-mails"><div class="povh"><h3>${tr('E-mails')}</h3></div>${hbm_bodyHtml(key)}</section>`;
}
function hbm_hubView() {
  const key = 'inbox:0', j = hbm_state(key).j;
  const sp = (j?.spaces || []).map(x => `<li class="hbmsp"><span class="hbmspn"><b>${esc(x.name)}</b><small class="muted">${x.address ? esc(x.address) : tr('No address yet')}</small></span>
      <button type="button" class="btn sm" data-hbma="copy" data-hbmk="${key}" data-ws="${esc(x.ws)}">${ic('copy', 's')}<span>${tr(x.address ? 'Copy address' : 'Create address')}</span></button>
      ${x.address ? `<button type="button" class="iconbtn" data-hbma="menu" data-hbmk="${key}" data-ws="${esc(x.ws)}" aria-haspopup="menu" aria-label="${esc(tr('Address'))}" title="${esc(tr('Address'))}">${ic('dots', 's')}</button>` : ''}</li>`).join('');
  const intro = !j ? '' : j.enabled ? `<p class="muted">${tr('Forward e-mails to your filing address (or send it a copy): a mail from the address of a client or of one of its contact persons is filed with that client, everything else waits here until you assign it.')}</p>`
    : `<p class="muted">${tr('Receiving e-mail is not set up on this server (an admin sets up the mailbox).')}</p>`;
  return `<div class="ctview hbmhub"><h2 class="msclh"><a href="#clients" class="linkbtn">${ic('back', 's')}<span>${tr('Clients')}</span></a><span class="muted" aria-hidden="true">›</span><span>${tr('E-mail filing')}</span></h2>
    ${intro}${sp ? `<h4>${tr('Your filing addresses')}</h4><ul class="hbmspaces" role="list">${sp}</ul>` : ''}${typeof hmb_hubSection === 'function' ? hmb_hubSection() : ''}
    <h4>${tr('Not assigned')}</h4>${hbm_bodyHtml(key)}</div>`;
}

// ---- the reading view
async function hbm_open(id, key) {
  let m; try { m = await api('GET', `/api/hubmail/mails/${id}`); } catch { return; }
  $('.hbmdlg')?.remove();
  const f = (label, val) => val ? `<div class="hbmhf"><span class="muted">${esc(label)}</span><span>${esc(val)}</span></div>` : '';
  const att = (m.attachments || []).map(a => `<li><a class="linkbtn" href="/api/hubmail/mails/${m.id}/files/${a.id}" target="_blank" rel="noopener">${ic(a.id === m.eml_id ? 'mail' : 'clip', 's')}<span>${esc(a.name)}</span></a><span class="muted"> · ${fmtSize(a.size || 0)}${a.scan === 'unchecked' ? ' · ' + esc(tr('not checked for viruses')) : ''}</span></li>`).join('');
  const where = m.list_name ? `${m.list_name}${m.client_name ? ' · ' + m.client_name : ''}` : m.client_name || tr('Not assigned');
  const md = modal(`<div class="lhdr"><h3>${esc(m.subject || tr('(no subject)'))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="hbmhdr">${f(tr('From'), m.from_name ? `${m.from_name} <${m.from_addr}>` : m.from_addr)}${f(tr('To|mail'), m.to)}${f(tr('Date'), fmtWhen(m.sent_at || m.created_at))}${f(tr('Filed with'), where)}</div>
    ${m.note ? `<div class="shint keep">${ic('info', 's')} ${esc(m.note)}</div>` : ''}
    ${hbm_actRowHtml(m)}${hbm_madeHtml(m.made)}
    ${hbm_viewHtml(m, key)}
    ${att ? `<h4>${tr('Attachments')}</h4><ul class="hbmatt" role="list">${att}</ul>` : ''}
    ${m.folder_id ? `<p><a class="linkbtn" href="#ablage/${m.folder_id}" data-m="close">${ic('folder', 's')}<span>${tr('Attachments in the file store')}</span></a></p>` : ''}
    <div class="foot">${typeof hmb_replyBtn === 'function' ? hmb_replyBtn(m) : ''}${m.can_write ? `<button type="button" class="btn danger" data-hbmd="del">${ic('trash', 's')} ${tr('Delete')}</button><button type="button" class="btn" data-hbmd="asg">${tr('Assign…')}</button>` : ''}<span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('hbmdlg');
  md.addEventListener('click', e => {
    if (e.target.closest('[data-m="close"]')) { modalClose(md); return; }
    if (hbm_viewClick(e, md, m, key)) return;  // 2.141.0 B (#2140, #2139): Text / HTML, Load images, Task / Event from it
    const b = e.target.closest('[data-hbmd]'); if (!b) return;
    modalClose(md);
    if (b.dataset.hbmd === 'del') hbm_del(m.id); else hbm_assign(m);
  });
}

// ---- 2.141.0 B (#2140): the HTML view -- the server's own cleaned page (/api/hubmail/mails/<id>/html, own strict CSP) in a
// frame without scripts and without the app's origin (sandbox: no allow-scripts / allow-same-origin; links open in a new tab,
// popups leave the sandbox so the opened page works normally); external pictures only after "Load images" (this view only)
const HBMV = {};  // mail id -> {v: 'html' | 'text', img: bool} while its reading view is open
function hbm_viewHtml(m, key) {
  const st = HBMV[m.id] = HBMV[m.id] || {v: m.html ? 'html' : 'text', img: false};
  const html = m.html && st.v === 'html';
  const seg = m.html ? `<div class="seg hbmseg" role="group" aria-label="${esc(tr('Show as'))}">${[['text', N_('Text')], ['html', N_('HTML')]].map(([k, n]) =>
    `<button type="button" data-hbmv="${k}" class="${st.v === k ? 'on' : ''}" aria-pressed="${st.v === k}">${tr(n)}</button>`).join('')}</div>` : '';
  const img = html && m.html_ext && !st.img ? `<div class="hbmimg muted">${ic('picture', 's')}<span>${tr('External images are blocked.')}</span><button type="button" class="linkbtn" data-hbmv="img">${tr('Load images')}</button></div>` : '';
  const body = html ? `<iframe class="hbmframe" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" title="${esc(m.subject || tr('E-mail'))}"
      src="/api/hubmail/mails/${m.id}/html${st.img ? '?images=1' : ''}"></iframe>` : `<div class="hbmtext">${esc(m.body || '')}</div>`;
  return `<div class="hbmview" data-hbmview="${m.id}">${seg || img ? `<div class="hbmvbar">${seg}${img}</div>` : ''}${body}</div>`;
}
// ---- 2.141.0 B (#2139): Task / Event from the mail (in its workspace), and what was made from it already. Part A's "Reply"
// sits in the same row (hbm_actRowHtml)
function hbm_actRowHtml(m) {
  return `<div class="hbmactrow"><button type="button" class="btn sm" data-hbmmk="task">${ic('done', 's')}<span>${tr('Task from it')}</span></button>${hbm_evOn() ? `<button type="button" class="btn sm" data-hbmmk="event">${ic('cal', 's')}<span>${tr('Event from it')}</span></button>` : ''}</div>`;
}
const hbm_evOn = () => feat('events');
function hbm_madeHtml(made) {
  if (!made?.length) return '';
  return `<div class="hbmmade">${made.map(x => `<button type="button" class="linkbtn" data-hbmgo="${x.kind}:${x.id}">${ic(x.kind === 'task' ? 'done' : 'cal', 's')}<span>${esc(x.kind === 'task' ? tr('Task: {0}', x.title) : tr('Event: {0}', x.title))}</span></button>`).join('')}</div>`;
}
async function hbm_go(kind, id) {
  if (kind === 'task') { if (!taskById(id)) await load().catch(() => {}); openDetail(id); }
  else if (typeof evOpen === 'function') evOpen(id);
}
function hbm_viewClick(e, md, m, key) {
  const v = e.target.closest('[data-hbmv]');
  if (v) {
    const st = HBMV[m.id];
    if (v.dataset.hbmv === 'img') st.img = true; else st.v = v.dataset.hbmv;
    const box = md.querySelector('[data-hbmview]'); if (box) box.outerHTML = hbm_viewHtml(m, key);
    return true;
  }
  const g = e.target.closest('[data-hbmgo]');
  if (g) { const [k, id] = g.dataset.hbmgo.split(':'); modalClose(md); hbm_go(k, +id); return true; }
  const mk = e.target.closest('[data-hbmmk]');
  if (mk) { modalClose(md); hbm_make(m, key, mk.dataset.hbmmk); return true; }
  return false;
}
async function hbm_make(m, key, kind) {
  let t; try { t = await api('GET', `/api/hubmail/mails/${m.id}/make`); } catch { return; }
  const ev = kind === 'event', picks = ev ? t.calendars : t.lists;
  $('.hbmmkdlg')?.remove();
  const opts = picks.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('');
  const md = modal(`<div class="lhdr"><h3>${ev ? tr('Event from the e-mail') : tr('Task from the e-mail')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    ${picks.length ? `<div class="row"><label for="hbm-mkt">${tr('Title')}</label><input id="hbm-mkt" maxlength="300" value="${esc(t.title || '')}"></div>
    <div class="row"><label for="hbm-mkp">${ev ? tr('Calendar') : tr('List')}</label><select id="hbm-mkp">${opts}</select></div>
    ${ev ? `<div class="row hbmmkd"><label>${tr('Date')}${dateIn('hbm-mkd', today(), {label: tr('Date')})}</label><label>${tr('Time')}${timeIn('hbm-mkh', '', {label: tr('Time'), empty: tr('All day')})}</label></div>`
      : `<div class="row"><label>${tr('Due')}${dateIn('hbm-mkd', '', {label: tr('Due'), empty: tr('No date')})}</label></div>`}
    <p class="shint keep">${tr('The description takes the start of the text and the sender; the e-mail stays linked.')}</p>`
    : `<p class="muted">${ev ? tr('No calendar of this workspace you can write in.') : tr('No list of this workspace you can write in.')}</p>`}
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${picks.length ? `<button class="btn pri" data-m="save">${ic('check', 's')} ${tr('Create')}</button>` : ''}</div>`);
  md.classList.add('hbmmkdlg');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { modalClose(md); hbm_open(m.id, key); return; }
    const title = $('#hbm-mkt', md).value.trim(), pid = +$('#hbm-mkp', md).value, d = $('#hbm-mkd', md)?.value || '';
    let j;
    try {
      if (ev) { const h = $('#hbm-mkh', md)?.value || ''; j = await api('POST', `/api/hubmail/mails/${m.id}/event`, {cal_id: pid, title, start: d ? (h ? `${d}T${h}` : d) : today()}); }
      else j = await api('POST', `/api/hubmail/mails/${m.id}/task`, {list_id: pid, title, ...(d ? {due: d} : {})});
    } catch { return; }
    modalClose(md);
    if (!ev) load().catch(() => {});
    if (ev && typeof calInvalidate === 'function') calInvalidate();
    hbm_open(m.id, key);
    toast(ev ? tr('Event created') : tr('Task created'), () => hbm_go(ev ? 'event' : 'task', ev ? j.event_id : j.task_id), 6000, tr('Open'));
  });
}

// ---- assign, delete (one undo step each)
const hbm_send = (id, t) => api('POST', `/api/hubmail/mails/${id}/assign`, {client_id: t.client_id || null, list_id: t.list_id || null});
async function hbm_assign(m) {
  let t; try { t = await api('GET', `/api/hubmail/targets?mail=${m.id}`); } catch { return; }
  $('.hbmadlg')?.remove();
  const row = (k, x, icn) => `<li><button type="button" class="hbmpick" data-hbmt="${k}:${x.id}">${ic(icn, 's')}<span>${esc(k === 'client' ? cdn_label(x) : x.name)}</span></button></li>`;
  const back = m.mine && (m.client_id || m.list_id) ? `<li><button type="button" class="hbmpick" data-hbmt="none:0">${ic('inbox', 's')}<span>${tr('Not assigned')}</span></button></li>` : '';
  const md = modal(`<div class="lhdr"><h3>${tr('Assign the e-mail')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="hbmq">${ic('search', 's')}<input type="search" id="hbm-tq" placeholder="${esc(tr('Search clients and projects'))}" aria-label="${esc(tr('Search clients and projects'))}" autocomplete="off"></div>
    ${t.clients.length ? `<h4>${tr('Clients')}</h4><ul class="hbmpicks" role="list">${t.clients.map(x => row('client', x, 'brief')).join('')}</ul>` : ''}
    ${t.projects.length ? `<h4>${tr('Projects')}</h4><ul class="hbmpicks" role="list">${t.projects.map(x => row('list', x, 'folder')).join('')}</ul>` : ''}
    ${back ? `<ul class="hbmpicks" role="list">${back}</ul>` : ''}
    ${!t.clients.length && !t.projects.length ? `<p class="muted">${tr('No client or project in this workspace.')}</p>` : ''}
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button></div>`);
  md.classList.add('hbmadlg');
  md.addEventListener('input', e => {
    if (e.target.id !== 'hbm-tq') return;
    const q = e.target.value.trim().toLowerCase();
    for (const b of md.querySelectorAll('.hbmpick')) b.parentElement.hidden = !!q && !b.textContent.toLowerCase().includes(q);
  });
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-m="close"]')) { modalClose(md); return; }
    const b = e.target.closest('[data-hbmt]'); if (!b) return;
    const [k, id] = b.dataset.hbmt.split(':'), to = k === 'client' ? {client_id: +id} : k === 'list' ? {list_id: +id} : {};
    let j; try { j = await hbm_send(m.id, to); } catch { return; }
    modalClose(md);
    await hbm_reloadAll();
    const name = j.mail.list_name || j.mail.client_name || tr('Not assigned');
    ms_hist(tr('Filed with {0}', name), tr('E-mail assigned'), async () => { await hbm_send(m.id, j.prev); await hbm_reloadAll(); },
      async () => { await hbm_send(m.id, to); await hbm_reloadAll(); });
  });
}
async function hbm_del(id) {
  try { await api('DELETE', `/api/hubmail/mails/${id}`); } catch { return; }
  await hbm_reloadAll();
  ms_hist(tr('E-mail deleted'), tr('E-mail deleted'), async () => { await api('POST', `/api/hubmail/mails/${id}/restore`, {}); await hbm_reloadAll(); },
    async () => { await api('DELETE', `/api/hubmail/mails/${id}`); await hbm_reloadAll(); });
}

// ---- the address (made on the first tap)
function hbm_target(key, ws) {
  const [k, id] = key.split(':');
  return k === 'client' ? {client_id: +id} : k === 'list' ? {list_id: +id} : {ws: ws || 'private'};
}
async function hbm_addr(key, ws, renew) {
  let j; try { j = await api('POST', '/api/hubmail/address', {...hbm_target(key, ws), ...(renew ? {renew: true} : {})}); } catch { return; }
  if (j.address) await copyText(j.address);
  hbm_load(key);
}
function hbm_addrMenu(b, key, ws) {
  menu(b, [{label: tr('New address'), icon: 'sync', fn: async () => {
    if (await askConfirm(tr('Make a new address?'), tr('The old address stops working at once.'), {ok: tr('New address')})) hbm_addr(key, ws, true);
  }}, {label: tr('Turn the address off'), icon: 'x', fn: async () => {
    if (!await askConfirm(tr('Turn the address off?'), tr('Mails to it are no longer filed. The filed e-mails stay.'), {ok: tr('Turn off'), danger: true})) return;
    const t = hbm_target(key, ws), qs = Object.entries(t).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    try { await api('DELETE', `/api/hubmail/address?${qs}`); } catch { return; }
    hbm_load(key);
  }}]);
}

// ---- events
document.addEventListener('input', e => {
  const k = e.target.dataset?.hbmq; if (!k) return;
  const s = HBM.s[k]; if (!s) return;
  s.q = e.target.value; clearTimeout(s.t); s.t = setTimeout(() => hbm_load(k), 200);
});
document.addEventListener('click', e => {
  const a = e.target.closest('[data-hbmasg]');
  if (a) { const m = (HBM.s[a.dataset.hbmk]?.j?.mails || []).find(x => x.id === +a.dataset.hbmasg); if (m) hbm_assign(m); return; }
  const d = e.target.closest('[data-hbmdel]');
  if (d) { hbm_del(+d.dataset.hbmdel); return; }
  const b = e.target.closest('[data-hbma]'); if (!b) return;
  const key = b.dataset.hbmk, ws = b.dataset.ws;
  if (b.dataset.hbma === 'copy') hbm_addr(key, ws, false);
  else if (b.dataset.hbma === 'menu') hbm_addrMenu(b, key, ws);
});
