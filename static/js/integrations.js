/* Kalmido web client: API tokens + scopes, webhooks, public links, calendar apps (CalDAV).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ package B: API tokens, webhooks, public links
const API_DOCS = 'https://github.com/Gegenschuss/kalmido/blob/main/docs/API.md';
// a secret shown exactly once (new API token, webhook signing secret), with copy
function secretModal(title, value, text) {
  const md = modal(`<h3>${esc(title)}</h3><div class="shint">${text}</div>
    <div class="row icalrow"><input id="sec-val" readonly value="${esc(value)}" aria-label="${esc(title)}" spellcheck="false"><button class="btn sm pri" data-m="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const i = $('#sec-val', md);
    try { await navigator.clipboard.writeText(i.value); toast(tr('Copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected text')); }
  });
  setTimeout(() => { const i = $('#sec-val', md); if (i) { i.focus(); i.select(); } }, 50);
  return md;
}
// Settings > Account > API tokens (personal access tokens for /api/v1)
const apiHtml = () => S.api?.enabled ? `<h4 id="s-api-h">${tr('API tokens')}</h4>
  <div class="shint">${tr('For scripts and integrations such as Home Assistant or n8n: send a token as “Authorization: Bearer …” to /api/v1. A token acts as you and never has more rights than you. It is shown only once.')} <a href="${API_DOCS}" target="_blank" rel="noopener noreferrer">${tr('API documentation')}</a></div>
  <div class="members" id="s-toks"><div class="muted mhint">${tr('Loading…')}</div></div>
  <div class="row"><button class="btn sm" data-tok="new">${ic('key', 's')} ${tr('New token')}</button></div>` : '';
async function tokDraw(md) {
  const box = $('#s-toks', md); if (!box) return;
  let j; try { j = await api('GET', '/api/me/tokens'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._t = j.tokens; box._j = j;
  box.innerHTML = j.tokens.length ? j.tokens.map(t => `<div class="mrow tokrow ${t.expired ? 'off' : ''}" data-tokid="${t.id}"><span class="n"><b>${esc(t.name)}</b> <code class="topic">${esc(t.prefix)}…</code><small class="muted">${esc(scopeSummary(t.effective_scopes || t.scopes))}${t.allowed_ips?.length ? ' · ' + esc(tr('only from {0}', t.allowed_ips.join(', '))) : ''} · ${t.expired ? tr('expired') : t.expires_at ? esc(tr('valid until {0}', fmtWhen(t.expires_at))) : tr('no expiry')} · ${t.last_used_at ? esc(tr('last used {0}', relTime(t.last_used_at))) : tr('never used')}</small></span><button class="iconbtn" data-tok="edit" title="${esc(tr('Permissions'))}" aria-label="${esc(tr('Permissions of {0}', t.name))}">${ic('lock', 's')}</button><button class="iconbtn danger" data-tok="del" title="${tr('Revoke')}" aria-label="${tr('Revoke')}">${ic('trash', 's')}</button></div>`).join('')
    : `<div class="muted mhint">${tr('No tokens yet.')}</div>`;
}
function tokWire(md) {
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-tok]'); if (!b) return;
    if (b.dataset.tok === 'new') { tokModal(() => tokDraw(md), $('#s-toks', md)._j?.scopes); return; }
    const row = b.closest('[data-tokid]'), t = ($('#s-toks', md)._t || []).find(x => x.id === +row?.dataset.tokid); if (!t) return;
    if (b.dataset.tok === 'edit') {  // 2.15.0 (#479): what the token may do + from where
      permModal(tr('Permissions of {0}', t.name), $('#s-toks', md)._j?.scopes || [], t.scopes, t.allowed_ips, async (scopes, ips) => {
        await calReq('PATCH', `/api/me/tokens/${t.id}`, {scopes, allowed_ips: ips}); toast(tr('Saved')); tokDraw(md);
      });
      return;
    }
    if (!await askConfirm(tr('Revoke the token “{0}”?', t.name), tr('Scripts that use it stop working at once.'), {ok: tr('Revoke'), danger: true})) return;
    try { await api('DELETE', `/api/me/tokens/${t.id}`); toast(tr('Token revoked')); } catch { /* api() showed it */ }
    tokDraw(md);
  });
}
// ---- 2.15.0 (#479) permissions (scopes) of tokens and agents: one compact grid of switches, the explanations behind (i),
// scopes outside the admin's limit greyed out; "write" (a token from before 2.15) shows as every permission
const SCOPE_ALL = ['read', 'tasks:write', 'comments', 'structure', 'delete', 'attachments:read', 'attachments:write', 'time', 'export', 'account', 'admin-read'];
const SCOPE_SHORT = {read: N_('Read'), 'tasks:write': N_('Tasks'), comments: N_('Comments'), structure: N_('Structure'), delete: N_('Delete & trash'), 'attachments:read': N_('Read files'), 'attachments:write': N_('Upload files'), time: N_('Time tracking'), export: N_('Export'), account: N_('Account settings'), 'admin-read': N_('Admin read')};
const scopeExpand = sc => (sc || []).includes('write') ? SCOPE_ALL.filter(x => x !== 'admin-read' || sc.includes('admin-read')) : (sc || []);
function scopeSummary(sc) {
  const e = scopeExpand(sc);
  if (e.length <= 1) return tr('read only');
  if (SCOPE_ALL.filter(x => x !== 'admin-read' && x !== 'account').every(x => e.includes(x))) return tr('all permissions');
  return e.filter(x => x !== 'read').map(x => tr(SCOPE_SHORT[x] || x)).join(', ');
}
function scopesHtml(offer, sel, legend) {
  const on = new Set(scopeExpand(sel));
  return `<fieldset class="scopes"><legend>${esc(legend || tr('Permissions'))}</legend>
    <div class="shint pl">${esc(offer.map(o => `${o.label}: ${o.help}`).join('\n'))}</div>
    <div class="scgrid">${offer.map(o => `<label class="chkl sc ${o.allowed ? '' : 'off'}"${o.allowed ? '' : ` title="${esc(tr('Not allowed on this server'))}"`}><input type="checkbox" data-scope="${esc(o.scope)}" ${o.scope === 'read' || (on.has(o.scope) && o.allowed) ? 'checked' : ''} ${o.scope === 'read' || !o.allowed ? 'disabled' : ''}><span>${esc(o.label)}</span></label>`).join('')}</div></fieldset>`;
}
const scopesVal = md => ['read', ...$$('.scopes [data-scope]:checked', md).map(x => x.dataset.scope).filter(x => x !== 'read')];
const ipsRow = (v, id) => `<div class="row"><label for="${id}">${tr('Only from')}</label><input id="${id}" value="${esc(v || '')}" placeholder="${esc(tr('any address'))}" autocomplete="off" autocapitalize="off" spellcheck="false" inputmode="url"></div>
    <div class="shint">${tr('Optional: IP addresses or networks such as 203.0.113.0/24, separated by commas. Requests from anywhere else are refused. Behind a reverse proxy this relies on its trusted-proxy setting.')}</div>`;
function permModal(title, offer, sel, ips, save, extra) {
  const md = modal(`<h3>${esc(title)}</h3>${scopesHtml(offer, sel)}${ipsRow((ips || []).join(', '), 'pm-ips')}${extra || ''}
    <div class="foot stfoot"><div class="calerr" role="alert" id="pm-err" hidden></div><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const err = $('#pm-err', md); b.disabled = true;
    try { await save(scopesVal(md), $('#pm-ips', md).value.trim(), md); md.remove(); } catch (x) { err.textContent = x.message; err.hidden = false; } finally { b.disabled = false; }
  });
  return md;
}
// a new token for an agent: with an expiry (never by default)
async function agTokenModal(a, url) {
  const md = modal(`<h3>${esc(tr('New API token for {0}', a.name))}</h3>
    <div class="shint keep warn">${tr('Every older token of this agent stops working at once.')}</div>
    <div class="row"><label for="agt-exp">${tr('Expires')}</label><select id="agt-exp"><option value="">${tr('never')}</option><option value="30">${tr('in 30 days')}</option><option value="90">${tr('in 90 days')}</option><option value="365">${tr('in a year')}</option></select></div>
    <div class="calerr" role="alert" id="agt-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri danger" data-m="ok">${tr('New API token')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    b.disabled = true;
    try {
      const v = $('#agt-exp', md).value, r = await calReq('POST', url, {expires_days: v ? +v : null});
      md.remove();
      secretModal(tr('API token of {0}', a.name), r.token, tr('Copy it now into the agent’s configuration: it is shown only this once.'));
    } catch (x) { const er = $('#agt-err', md); er.textContent = x.message; er.hidden = false; } finally { b.disabled = false; }
  });
}
function tokModal(done, offer) {
  const md = modal(`<h3>${tr('New API token')}</h3>
    <div class="row"><label for="tk-name">${tr('Name')}</label><input id="tk-name" maxlength="60" placeholder="${tr('e.g. Home Assistant')}"></div>
    ${scopesHtml(offer || [], ['read'])}
    ${ipsRow('', 'tk-ips')}
    <div class="foot stfoot"><div class="calerr" role="alert" id="tk-err" hidden></div>
      <span class="sfexp"><label for="tk-exp">${tr('Expires')}</label><select id="tk-exp"><option value="30">${tr('in 30 days')}</option><option value="90" selected>${tr('in 90 days')}</option><option value="365">${tr('in a year')}</option><option value="">${tr('never')}</option></select></span>
      <button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Create')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const name = $('#tk-name', md).value.trim(), err = $('#tk-err', md);
    if (!name) { need($('#tk-name', md)); return; }
    const scopes = scopesVal(md);
    b.disabled = true;
    try {
      const j = await calReq('POST', '/api/me/tokens', {name, scopes, allowed_ips: $('#tk-ips', md).value.trim(), expires_days: $('#tk-exp', md).value ? +$('#tk-exp', md).value : null});
      md.remove(); done && done();
      secretModal(tr('Your new API token'), j.token, tr('Copy it now: it is shown only this once. Anyone with this token can act as you within its access rights. Example:') + ` <code class="topic">curl -H "Authorization: Bearer ${esc(j.prefix)}…" ${esc(location.origin)}/api/v1/me</code>`);
    } catch (x) { err.textContent = x.message; err.hidden = false; } finally { b.disabled = false; }
  });
  if (!isTouch()) setTimeout(() => $('#tk-name', md)?.focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
// ------------------------------------------------------------------ 2.9.0 (#435): calendar apps (CalDAV) + app passwords
const DAV_DOCS = 'https://github.com/Gegenschuss/kalmido/blob/main/docs/CALDAV.md';
const apwHtml = () => S.caldav?.enabled ? `<h4 id="s-apw-h">${tr('App passwords')}</h4>
  <div class="shint keep">${tr('For calendar apps (CalDAV): one password per device, shown only once. Your Kalmido password never goes into a calendar app. If a device gets lost, revoke its password; the other devices keep working.')}</div>
  <div class="members" id="s-apws"><div class="muted mhint">${tr('Loading…')}</div></div>
  <div class="row"><button class="btn sm" data-apw="new">${ic('key', 's')} ${tr('New app password')}</button><button class="btn sm" data-apw="howto">${ic('cal', 's')} ${tr('Set up calendar apps')}</button></div>` : '';
async function apwDraw(md) {
  const box = $('#s-apws', md); if (!box) return;
  let j; try { j = await api('GET', '/api/me/app-passwords'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._t = j.items;
  box.innerHTML = j.items.length ? j.items.map(t => `<div class="mrow tokrow" data-apwid="${t.id}"><span class="n"><b>${esc(t.name)}</b><small class="muted">${esc(tr('created {0}', fmtWhen(t.created_at)))} · ${t.last_used_at ? esc(tr('last used {0}', relTime(t.last_used_at))) : tr('never used')}${t.last_client ? ' · ' + esc(t.last_client.slice(0, 60)) : ''}</small></span><button class="iconbtn danger" data-apw="del" title="${tr('Revoke')}" aria-label="${esc(tr('Revoke the app password “{0}”', t.name))}">${ic('trash', 's')}</button></div>`).join('')
    : `<div class="muted mhint">${tr('No app passwords yet.')}</div>`;
}
function apwModal(md) {
  const m = modal(`<h3>${tr('New app password')}</h3>
    <div class="row"><label for="apw-name">${tr('Name')}</label><input id="apw-name" maxlength="60" placeholder="${tr('e.g. iPhone, Thunderbird')}"></div>
    <div class="calerr" role="alert" id="apw-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Create')}</button></div>`);
  m.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { m.remove(); return; }
    const name = $('#apw-name', m).value.trim(), er = $('#apw-err', m);
    if (!name) { need($('#apw-name', m)); return; }
    b.disabled = true;
    try {
      const j = await calReq('POST', '/api/me/app-passwords', {name});
      m.remove(); apwDraw(md);
      secretModal(tr('Your new app password'), j.password, tr('Enter it in the calendar app now, together with your user name {0}: it is shown only this once.', `<code class="topic">${esc(S.caldav?.username || S.me?.username || '')}</code>`));
    } catch (x) { er.textContent = x.message; er.hidden = false; } finally { b.disabled = false; }
  });
  m.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'apw-name') { e.preventDefault(); $('[data-m="ok"]', m).click(); } });
  setTimeout(() => $('#apw-name', m)?.focus(), 50);
}
function apwWire(md) {
  md.addEventListener('click', async e => {
    const c = e.target.closest('[data-davcopy]');
    if (c) { try { await navigator.clipboard.writeText(c.dataset.davcopy); toast(tr('Copied')); } catch { toast(tr('Copy failed')); } return; }
    const b = e.target.closest('[data-apw]'); if (!b) return;
    if (b.dataset.apw === 'new') { apwModal(md); return; }
    if (b.dataset.apw === 'howto') { $('.snav [data-sec="integr"]', md)?.click(); setTimeout(() => $('#s-dav-h', md)?.scrollIntoView({block: 'start'}), 0); return; }
    if (b.dataset.apw === 'list') { $('.snav [data-sec="account"]', md)?.click(); setTimeout(() => $('#s-apw-h', md)?.scrollIntoView({block: 'start'}), 0); return; }
    const row = b.closest('[data-apwid]'), t = ($('#s-apws', md)?._t || []).find(x => x.id === +row?.dataset.apwid); if (!t) return;
    if (!await askConfirm(tr('Revoke the app password “{0}”?', t.name), tr('The calendar app that uses it stops syncing at once.'), {ok: tr('Revoke'), danger: true})) return;
    try { await api('DELETE', `/api/me/app-passwords/${t.id}`); toast(tr('App password revoked')); } catch { /* api() showed it */ }
    apwDraw(md);
  });
}
function caldavHtml(hint) {
  const d = S.caldav; if (!d?.enabled || !S.me) return '';
  const cp = (label, v, id) => `<div class="row davrow"><label for="${id}">${label}</label><input id="${id}" readonly value="${esc(v)}" spellcheck="false"><button class="btn sm" data-davcopy="${esc(v)}" aria-label="${esc(tr('Copy {0}', label))}">${ic('copy', 's')} ${tr('Copy')}</button></div>`;
  const srv = `<code class="topic">${esc(d.server)}</code>`, url = `<code class="topic">${esc(d.url)}</code>`, prin = `<code class="topic">${esc(d.principal)}</code>`;
  return `<h4 id="s-dav-h">${tr('Calendar apps (CalDAV)')}</h4>
    ${hint(tr('Your lists as task lists in Reminders (iPhone, iPad, Mac), Thunderbird, Evolution or on Android with Tasks.org or DAVx⁵: changes go both ways. Every list you see is one task list there; completed tasks stay for {0} days.', d.done_days))}
    ${cp(tr('Server'), d.server, 'dav-srv')}${cp(tr('CalDAV address'), d.url, 'dav-url')}${cp(tr('User name'), d.username, 'dav-user')}
    <div class="row"><label>${tr('Password')}</label><button class="btn sm pri" data-apw="new">${ic('key', 's')} ${tr('New app password')}</button><button class="linkbtn" data-apw="list">${tr('Manage app passwords')}</button></div>
    ${hint(tr('Log in with your user name and an app password, never with your Kalmido password.'))}
    <details class="shelp sdet"><summary>${tr('Step by step')}</summary><ul class="slist">
      <li>${tr('<b>iPhone / iPad:</b> Settings > Apps > Calendar > Calendar Accounts > Add Account > Other > Add CalDAV Account. Server {0}, your user name and the app password. Then switch on Reminders in the new account. Not found? Advanced Settings > Account URL {1}.', srv, prin)}</li>
      <li>${tr('<b>Mac:</b> System Settings > Internet Accounts > Add Account > Add Other Account > CalDAV account. Account type Manual, user name, app password, server address {0}; then tick Reminders. Not found? Account type Advanced, server path {1}, port 443, SSL on.', srv, `<code class="topic">${esc(new URL(d.principal).pathname)}</code>`)}</li>
      <li>${tr('<b>Thunderbird (Windows, macOS, Linux):</b> Tasks > New Calendar > On the Network. User name and location {0}, Find Calendars; enter the app password when asked and let Thunderbird remember it. Tick the lists you want: their tasks show under Tasks.', url)}</li>
      <li>${tr('<b>Android, Tasks.org:</b> Settings > Synchronization > Add account > CalDAV. URL {0}, user name, app password. Every list becomes a list in Tasks.org.', url)}</li>
      <li>${tr('<b>Android, DAVx⁵:</b> + > Login with URL and user name. Base URL {0}, user name, app password, Create account. Under CalDAV tick the lists; DAVx⁵ asks which task app shows them (Tasks.org, jtx Board or OpenTasks).', url)}</li>
      <li>${tr('<b>Linux, Evolution:</b> File > New > Task List, type CalDAV, URL {0}, user name, Find Task Lists, pick a list.', url)}</li>
      <li>${tr('<b>Windows:</b> the Windows Calendar app and Outlook do not sync tasks over CalDAV. Use Thunderbird.')}</li></ul></details>
    <details class="shelp sdet"><summary>${tr('What syncs')}</summary><ul class="slist">
      <li>${tr('Title, notes, due date and time, start, priority, done / won\'t do, tags, subtasks, repeat rules (daily to yearly), reminders and the link. Assignee, sections, comments, files and custom fields stay in Kalmido; other details a calendar app saves come back to it unchanged.')}</li>
      <li>${tr('Lists you may only view are read-only there. Deleting a task in a calendar app moves it to the trash in Kalmido. New lists are created in Kalmido.')}</li>
      <li>${tr('Reminders on iPhone and Mac keep tags and subtasks to themselves: what you set in Kalmido stays.')}</li></ul></details>
    ${S.me.is_admin ? hint(tr('Admins: behind a login proxy (forward auth, single sign-on) the paths /dav/ and /.well-known/caldav must bypass the proxy login, because calendar apps cannot log in there. Kalmido checks the app password itself.')) + `<a class="slink" href="${DAV_DOCS}" target="_blank" rel="noopener noreferrer">${tr('CalDAV guide')}</a>` : ''}`;
}
// Settings > Integrations > Webhooks
const WH_EV_NAMES = {'task.created': N_('Task created'), 'task.updated': N_('Task changed'), 'task.completed': N_('Task completed'), 'task.reopened': N_('Task reopened'),
  'task.deleted': N_('Task deleted'), 'comment.created': N_('New comment'), 'list.shared': N_('List shared')};
const whHtml = () => S.webhooks?.enabled ? `<h4 id="s-wh-h">${tr('Webhooks')}</h4>
  <div class="shint">${tr('Kalmido sends a signed POST request to your URL when something changes in lists you can see, for example to n8n or Home Assistant. Failed deliveries are retried after 1 min, 5 min, 30 min and 2 h; after that the webhook is turned off.')}</div>
  <a class="slink" href="${API_DOCS}#webhooks" target="_blank" rel="noopener noreferrer">${tr('How to verify the signature')}</a>
  <div class="members" id="s-whs"><div class="muted mhint">${tr('Loading…')}</div></div>
  <div class="row"><button class="btn sm" data-wh="new">${ic('plus', 's')} ${tr('Add webhook')}</button></div>` : '';
function whState(w) {
  if (!w.enabled) return `<span class="calerr" role="alert">${w.disabled_reason === 'failures' ? tr('turned off after failed deliveries') : tr('off')}</span>`;
  if (!w.last) return esc(tr('no deliveries yet'));
  return w.last.ok ? esc(tr('last delivery ok {0}', relTime(w.last.at))) : `<span class="calerr" role="alert">${esc(tr('last delivery failed: {0}', w.last.error_text))}</span>`;
}
async function whDraw(md) {
  const box = $('#s-whs', md); if (!box) return;
  let j; try { j = await api('GET', '/api/me/webhooks'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  box.innerHTML = j.hooks.length ? j.hooks.map(w => `<div class="mrow whrow ${w.enabled ? '' : 'off'}" data-whid="${w.id}"><span class="n"><b>${esc(w.name || urlHost(w.url))}</b> <span class="muted">${esc(urlHost(w.url))}</span><small class="muted">${esc(trn('{0} event|webhook', '{0} events|webhook', w.events.length))} · ${whState(w)}${w.pending ? ' · ' + esc(trn('{0} waiting', '{0} waiting', w.pending)) : ''}</small></span>
      <button class="iconbtn" data-wh="test" title="${tr('Send test')}" aria-label="${tr('Send test')}" ${w.enabled ? '' : 'disabled'}>${ic('send', 's')}</button>
      <button class="iconbtn" data-wh="log" title="${tr('Delivery log')}" aria-label="${tr('Delivery log')}">${ic('list', 's')}</button>
      <button class="iconbtn" data-wh="edit" title="${tr('Edit')}" aria-label="${tr('Edit')}">${ic('edit', 's')}</button>
      <button class="iconbtn danger" data-wh="del" title="${tr('Remove')}" aria-label="${tr('Remove')}">${ic('trash', 's')}</button></div>`).join('')
    : `<div class="muted mhint">${tr('No webhooks yet.')}</div>`;
}
function whWire(md) {
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-wh]'); if (!b) return;
    const box = $('#s-whs', md);
    if (b.dataset.wh === 'new') { whModal(null, box?._j, () => whDraw(md)); return; }
    const w = (box?._j?.hooks || []).find(x => x.id === +b.closest('[data-whid]')?.dataset.whid); if (!w) return;
    const a = b.dataset.wh;
    if (a === 'edit') whModal(w, box._j, () => whDraw(md));
    if (a === 'log') whLog(w);
    if (a === 'test') {
      b.disabled = true;
      try { const r = await api('POST', `/api/me/webhooks/${w.id}/test`); toast(r.ok ? tr('Test delivered (HTTP {0}, {1} ms)', r.status, r.ms) : tr('Test failed: {0}', r.error_text)); } catch { /* api() showed it */ }
      b.disabled = false; whDraw(md);
    }
    if (a === 'del') {
      if (!await askConfirm(tr('Remove the webhook “{0}”?', w.name || urlHost(w.url)), tr('Nothing is sent to this address any more.'), {ok: tr('Remove'), danger: true})) return;
      try { await api('DELETE', `/api/me/webhooks/${w.id}`); toast(tr('Webhook removed')); } catch { /* api() showed it */ }
      whDraw(md);
    }
  });
}
function whModal(w, j, done) {
  const evs = (j?.events || Object.keys(WH_EV_NAMES)), on = new Set(w ? w.events : ['task.created', 'task.completed']);
  const md = modal(`<h3>${w ? tr('Edit webhook') : tr('Add webhook')}</h3>
    <div class="row"><label for="wh-name">${tr('Name')}</label><input id="wh-name" maxlength="60" value="${esc(w?.name || '')}" placeholder="${tr('optional')}"></div>
    <div class="row"><label for="wh-url">${tr('URL')}</label><input id="wh-url" type="url" value="${esc(w?.url || '')}" placeholder="https://…" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
    <div class="shint keep">${tr('https:// only; http:// and addresses in your own network only for hosts an admin allowed (Settings > Administration > Advanced).')}</div>
    <div class="featgrid" id="wh-evs">${evs.map(x => `<label><input type="checkbox" data-whev="${esc(x)}" ${on.has(x) ? 'checked' : ''}> ${esc(tr(WH_EV_NAMES[x] || x))} <code class="muted">${esc(x)}</code></label>`).join('')}</div>
    ${w ? `<div class="row"><label></label><label class="chkl"><input type="checkbox" id="wh-on" ${w.enabled ? 'checked' : ''}> ${tr('Active')}</label><button class="btn sm" data-m="secret">${ic('key', 's')} ${tr('New secret')}</button></div>` : ''}
    <div class="shint keep">${tr('Only tasks and lists you can see are sent, with your tags. The signing secret is shown once after saving.')}</div>
    <div class="calerr" role="alert" id="wh-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    const err = $('#wh-err', md), show = m => { err.textContent = m || ''; err.hidden = !m; };
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'secret') {
      if (!await askConfirm(tr('Create a new signing secret?'), tr('The receiver must use the new one from now on.'), {ok: tr('New secret'), danger: true})) return;
      try { const r = await calReq('POST', `/api/me/webhooks/${w.id}/secret`); secretModal(tr('Signing secret'), r.secret, tr('Copy it now into the receiver: it is shown only this once. It signs every delivery (header X-Kalmido-Signature).')); } catch (x) { show(x.message); }
      return;
    }
    const body = {name: $('#wh-name', md).value.trim(), url: $('#wh-url', md).value.trim(), events: $$('[data-whev]', md).filter(x => x.checked).map(x => x.dataset.whev)};
    if (w) body.enabled = $('#wh-on', md).checked;
    if (!body.url) { need($('#wh-url', md)); return; }
    if (!body.events.length) { show(tr('Choose at least one event')); return; }
    b.disabled = true; show('');
    try {
      const r = await calReq(w ? 'PATCH' : 'POST', w ? `/api/me/webhooks/${w.id}` : '/api/me/webhooks', body);
      md.remove(); done && done();
      if (!w) secretModal(tr('Signing secret'), r.secret, tr('Copy it now into the receiver: it is shown only this once. It signs every delivery (header X-Kalmido-Signature).'));
      else toast(tr('Saved'));
    } catch (x) { show(x.message); } finally { b.disabled = false; }
  });
  if (!isTouch()) setTimeout(() => $(w ? '#wh-name' : '#wh-url', md)?.focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
async function whLog(w) {
  let j; try { j = await api('GET', `/api/me/webhooks/${w.id}/log`); } catch { return; }
  const md = modal(`<h3>${tr('Delivery log')}</h3><div class="shint keep">${esc(w.name || urlHost(w.url))} · ${tr('the last {0} attempts, newest first; bodies are never stored', 50)}</div>
    <div class="members whlog">${j.items.length ? j.items.map(x => `<div class="mrow ${x.ok ? '' : 'off'}"><span class="n"><b>${esc(x.event)}</b>${x.attempt > 1 ? ' · ' + esc(tr('attempt {0}', x.attempt)) : ''} · ${x.ok ? esc(tr('ok')) : `<span class="calerr" role="alert">${esc(x.error_text || tr('failed'))}</span>`}${x.status ? ` · HTTP ${esc(String(x.status))}` : ''} · ${esc(String(x.ms))} ms<small class="muted">${esc(fmtWhen(x.created_at))}${x.delivery ? ' · ' + esc(x.delivery.slice(0, 8)) : ''}</small></span></div>`).join('') : `<div class="muted mhint">${tr('Nothing sent yet.')}</div>`}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) md.remove(); });
}
// list dialog > Public link (owner): create / change / copy / new link / turn off
const pubDate = x => x ? ds(new Date(new Date(x) - 1000)) : '';  // stored: the start of the day after the last valid day
function pubDraw(md, lid, j) {
  const box = $('#l-pub', md); if (!box) return;
  const k = j.link;
  box._j = j;
  box.innerHTML = `${k ? `<div class="row icalrow"><input id="lp-url" readonly value="${esc(k.url)}" aria-label="${tr('Public link')}"><button class="btn sm pri" data-lp="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
      <div class="shint">${k.expired ? `<span class="calerr" role="alert">${tr('Expired')}</span> · ` : ''}${esc(trn('opened {0} time', 'opened {0} times', k.views))}${k.last_used_at ? ' · ' + esc(tr('last {0}', relTime(k.last_used_at))) : ''}</div>` : `<div class="shint keep">${tr('People without an account can open the list through a secret link: only this list, without comments, assignees or files.')}</div>`}
    <div class="row"><label for="lp-mode">${tr('Access')}</label><select id="lp-mode"><option value="view">${tr('View only')}</option><option value="tick" ${k?.mode === 'tick' ? 'selected' : ''}>${tr('View and tick off')}</option></select></div>
    <div class="row"><label for="lp-exp">${tr('Valid until')}</label>${dateIn('lp-exp', pubDate(k?.expires_at), {min: today(), label: tr('Valid until'), empty: tr('no expiry')})}</div>
    <div class="row"><label for="lp-pw">${tr('Password')}</label><input type="password" id="lp-pw" autocomplete="new-password" placeholder="${k?.has_password ? tr('saved, empty = keep') : tr('optional')}">${k?.has_password ? `<label class="chkl"><input type="checkbox" id="lp-nopw"> ${tr('remove')}</label>` : ''}</div>
    <div class="row"><label></label><label class="chkl"><input type="checkbox" id="lp-notes" ${k?.notes ? 'checked' : ''}> ${tr('Show task notes')}</label></div>
    <div class="row">${k ? `<button class="btn sm" data-lp="save">${tr('Save link settings')}</button><button class="btn sm" data-lp="regen">${ic('key', 's')} ${tr('New link')}</button><button class="btn sm danger" data-lp="off">${tr('Turn off')}</button>` : `<button class="btn sm pri" data-lp="save">${ic('link', 's')} ${tr('Create public link')}</button>`}</div>
    <div class="calerr" role="alert" id="lp-err" hidden></div>`;
}
function pubWire(md, lid) {
  api('GET', `/api/lists/${lid}/public-link`).then(j => pubDraw(md, lid, j)).catch(() => { const b = $('#l-pub', md); if (b) b.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-lp]'); if (!b) return;
    const err = $('#lp-err', md), show = m => { if (err) { err.textContent = m || ''; err.hidden = !m; } };
    const a = b.dataset.lp;
    if (a === 'copy') { const i = $('#lp-url', md); try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); } return; }
    if (a === 'regen' && !await askConfirm(tr('Create a new link?'), tr('The old one stops working at once.'), {ok: tr('New link'), danger: true})) return;
    if (a === 'off' && !await askConfirm(tr('Turn the public link off?'), tr('It stops working at once.'), {ok: tr('Turn off'), danger: true})) return;
    b.disabled = true; show('');
    try {
      let j;
      if (a === 'save') {
        const body = {mode: $('#lp-mode', md).value, notes: $('#lp-notes', md).checked, expires: $('#lp-exp', md).value || null};
        if ($('#lp-pw', md).value) body.password = $('#lp-pw', md).value; else if ($('#lp-nopw', md)?.checked) body.password = '';
        j = await calReq('PUT', `/api/lists/${lid}/public-link`, body);
        toast(tr('Public link saved'));
      }
      if (a === 'regen') { j = await calReq('POST', `/api/lists/${lid}/public-link/regenerate`); toast(tr('New link created, the old one no longer works')); }
      if (a === 'off') { j = await calReq('DELETE', `/api/lists/${lid}/public-link`); toast(tr('Public link turned off')); }
      pubDraw(md, lid, j);
    } catch (x) { show(x.message); } finally { b.disabled = false; }
  });
}
