/* Kalmido web client: the settings sections of account.js that only the settings dialog draws (account, users, groups,
   organisations, notifications, two-factor, backups, the sample project), loaded on demand with it (module "settings",
   2.65.0 #1823; moved unchanged from account.js, which keeps the sign-in, the invitations, logout and what other areas use).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';
// 1.9.0: Settings > Integrations > "Share from your phone": files, photos, links and text from any app into the inbox,
// via POST /drop with the personal upload token. Android: a ready-made import for the HTTP Shortcuts app (a ZIP with
// the address, the token and the icon); iPhone: address + token to copy for the Shortcuts app (a signed generic
// shortcut that asks for both on import is linked when the server has one, KALMIDO_IOS_SHORTCUT_URL).
const dropBase = sh => String(sh.drop_url || location.origin + '/drop').replace(/\/drop\/?$/, '');
// 2.0.2: a new upload token from Account or from "Share from your phone"; every field of the open dialog shows it at once
async function dropTokenNew(md) {
  if (!await askConfirm(tr('Create a new upload token?'), tr('The old one stops working. Update the iPhone shortcut and the HTTP Shortcuts import afterwards.'), {ok: tr('New token'), danger: true})) return;
  let j;
  try { j = await api('POST', '/api/me/drop-token'); } catch { return; }
  const tok = j.drop_token || '';
  const i = $('#s-droptok', md); if (i) { i.value = tok; i.type = 'text'; i.dataset.real = '1'; }
  toast(tr('New upload token created: update the shortcuts on your phones'));
}
function shareHtml(hint) {
  const sh = S.share || {}, ios = /^https:\/\//.test(sh.ios_shortcut || '') ? sh.ios_shortcut : '';
  return `<h4 id="s-share-h">${tr('Share from your phone')}</h4>
    ${hint(tr('Send photos, files, links and text from any app to your basket: each share becomes a task, files are attached. Works on the go too, as long as the phone reaches Kalmido.'))}
    <h5 class="ssub">${ic('phone', 's')}Android</h5>
    <div class="row"><a class="btn sm" id="s-hszip" href="/api/me/share/httpshortcuts.zip" download="kalmido-http-shortcuts.zip">${ic('download', 's')} ${tr('Download HTTP Shortcuts import')}</a></div>
    <ol class="slist">
      <li>${tr('Install the free app <b>HTTP Shortcuts</b> (Play Store or F-Droid).')}</li>
      <li>${tr('In HTTP Shortcuts: menu ⋮ > Import / Export > Import from file, choose the downloaded ZIP.')}</li>
      <li>${tr('Then in any app: Share > HTTP Shortcuts > <b>Kalmido</b> for photos and files (also several), <b>Kalmido text</b> for links and text.')}</li>
    </ol>
    ${hintK(tr('The file contains your personal upload token: keep it to yourself like a password. Links and text also work with Share > Kalmido once the app is installed.'))}
    <h5 class="ssub">${ic('phone', 's')}iPhone / iPad</h5>
    ${ios ? `<div class="row"><a class="btn sm" href="${esc(ios)}" target="_blank" rel="noopener noreferrer">${ic('plus', 's')} ${tr('Add the Kalmido shortcut')}</a></div>` : ''}
    <div class="row"><label for="s-dropurl">${tr('Server address')}</label><input id="s-dropurl" readonly value="${esc(dropBase(sh))}"><button class="btn sm" data-m="drop-copy-url">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <div class="shint">${tr('Without /drop: the shortcut adds it. (An address ending in /drop works too.)')}</div>
    <div class="row"><label for="s-droptok">${tr('Upload token')}</label><input id="s-droptok" readonly type="password" value="••••••••••••" autocomplete="new-password"><button class="btn sm" data-m="drop-copy-tok">${ic('copy', 's')} ${tr('Copy')}</button><button class="btn sm" data-m="drop-new-tok" title="${esc(tr('The old token stops working'))}">${ic('key', 's')} ${tr('New token')}</button></div>
    ${hint(tr('After a new token: paste it into the iPhone shortcut (or set the shortcut up again) and download the HTTP Shortcuts import again.'))}
    <details class="shelp sdet"><summary>${tr('Set it up in the Shortcuts app')}</summary><ol class="slist">
      ${ios ? `<li>${tr('Easiest: tap “Add the Kalmido shortcut” above, then Add Shortcut. It asks two questions: paste the server address (without /drop), then the upload token (copy them here first).')}</li>` : ''}
      <li>${tr('By hand: Shortcuts app > + (new shortcut), name it “Kalmido”.')}</li>
      <li>${tr('Tap ⓘ (details) > turn on “Show in Share Sheet”; as input accept Images, Files, URLs and Text.')}</li>
      <li>${tr('Add the action “Get Contents of URL”: URL = the server address above followed by <code class="topic">/drop</code>, Method = POST, Headers: Authorization = <code class="topic">Bearer</code> followed by a space and your upload token.')}</li>
      <li>${tr('Request Body: Form; add a field of type File named <code class="topic">file</code> with the value “Shortcut Input”. For links and text a second shortcut with a Text field named <code class="topic">text</code> instead.')}</li>
      <li>${tr('Done: in any app Share > Kalmido. The first time, iOS asks whether the shortcut may connect to your server: Always allow.')}</li>
    </ol></details>`;
}
// 2.1.0 (#317): Settings > Notifications: one matrix, events x News (the bell) / Push. The server decides (notif_ok) with
// the same rules; this mirrors them for the checkboxes. News of the events older than 2.1.0 lives in news_kinds, the rest
// (every push, News of reply / follow / new tasks / approvals / follow-ups) in the setting "notify" (json).
const NEWS_KINDS = [['mention', N_('Mentions of me')], ['assign', N_('Tasks assigned to me (or taken away)')], ['comment', N_('Comments on my tasks')],
  ['unblock', N_('A task blocking mine was completed')], ['share', N_('Lists shared with me')], ['status', N_('Project status changes')], ['complete', N_('Others completed my tasks')]];
// one checkbox -> the two stored values {notify, news_kinds}
function notifPatch(s, row, ch, on) {
  const o = nmStored(s);
  let nk = String(s.news_kinds ?? 'mention,assign,comment,unblock,share,status').split(',').filter(Boolean);
  if (ch === 'news' && NM_PRIMARY.includes(row)) nk = on ? [...new Set([...nk, NM_GROUP[row]])] : nk.filter(k => k !== NM_GROUP[row]);
  else { o[row] = {...(o[row] || {}), [ch]: on ? 1 : 0}; }
  const sorted = Object.keys(o).sort().reduce((a, k) => { a[k] = Object.keys(o[k]).sort().reduce((b, j) => { b[j] = o[k][j]; return b; }, {}); return a; }, {});
  return {notify: JSON.stringify(sorted), news_kinds: NEWS_KINDS.map(x => x[0]).filter(k => nk.includes(k)).join(',')};
}
// 2.46.6 (#1710): adm = only the admins' rows (Settings > Administration > Agents); the own matrix leaves them out
function notifMatrixHtml(s, hint, adm = false) {
  const m = notifMatrix(s), social = collab();
  const rows = NOTIF_ROWS.filter(([r, , , f]) => adm ? f === 'admin' && !!S.me?.is_admin : (social || !NM_SOCIAL.includes(r)) && (!f || (f === 'deps' ? depsOn() : f === 'admin' ? false : f === 'propose' ? propOn() : feat('agents'))));
  if (!rows.length) return '';
  const hid = adm ? 's-newsadm-h' : 's-news-h';
  const box = (r, ch, lab) => m[r][ch] === null ? `<span class="nmna" aria-label="${esc(tr('not available'))}">–</span>`
    : `<label class="nmhit"><input type="checkbox" data-nm="${r}" data-ch="${ch}" ${m[r][ch] ? 'checked' : ''} aria-label="${esc(tr(lab) + ': ' + (ch === 'news' ? tr('News') : tr('Push')))}"></label>`;  // 2.13.0: a 44 px hit area
  return `<h4 id="${hid}">${adm ? tr('What notifies you as an admin') : tr('What notifies you')}</h4>
    ${adm ? '' : hint(tr('News = under the bell in the app, Push = a notification on your devices. Your own actions never notify you. Each list can override this with its bell (list menu > Notifications).'))}
    <div class="nmx" role="table" aria-labelledby="${hid}"><div class="nmh" role="row"><span role="columnheader">${tr('Event')}</span><span role="columnheader">${tr('News')}</span><span role="columnheader">${tr('Push')}</span></div>
    ${rows.map(([r, n, d]) => `<div class="nmr" role="row"><span class="nml" role="cell">${tr(n)}${d ? `<small>${tr(d)}</small>` : ''}</span><span role="cell">${social ? box(r, 'news', n) : '<span class="nmna">–</span>'}</span><span role="cell">${box(r, 'push', n)}</span></div>`).join('')}</div>`;
}
// 2.24.0 (#910): what my files take (the storage quota of the server)
// 2.25.0 (UX-56): when this device last matched the server, with "Sync now"
const syncedTxt = () => OUT.q.length ? trn('{0} change waiting', '{0} changes waiting', OUT.q.length) : tr('Last synced: {0}', relTime(new Date(S.syncOk || Date.now()).toISOString()));
const syncHtml = () => `<h4 id="s-sync-h">${tr('Sync')}</h4><div class="row"><label>${tr('This device')}</label><span id="s-synced" class="muted" role="status">${esc(syncedTxt())}</span><button type="button" class="btn sm" data-m="sync-now">${ic('sync', 's')} ${tr('Sync now')}</button></div>`;
function storageHtml() {
  const q = S.storage; if (!q) return syncHtml();
  const pct = q.limit ? Math.min(100, q.pct) : 0;
  return `<h4 id="s-storage-h">${tr('Storage')}</h4>
    <div class="row"><label>${tr('Your files')}</label><span class="stoq ${esc(q.level)}">${q.limit ? `<span class="stobar" role="meter" aria-labelledby="s-storage-h" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(pct)}"><i style="width:${pct}%"></i></span>` : ''}<span>${esc(q.limit ? tr('{0} of {1} used', fmtSize(q.used), fmtSize(q.limit)) + (q.pool === 'org' ? ' · ' + tr('shared by the organisation') : '') : tr('{0} used · no limit', fmtSize(q.used)))}</span></span></div>
    ${q.level === 'warn' || q.level === 'high' ? `<div class="shint keep">${ic('alert', 's')} ${esc(tr('Almost full: from 100 % new files cannot be uploaded.'))}</div>` : ''}
    ${q.level === 'full' ? `<div class="row"><span class="shint keep">${ic('alert', 's')} ${esc(tr('Your storage is full: new files cannot be uploaded.'))}</span>${q.support ? `<a class="btn sm pri" href="${esc(quotaMail(q))}">${ic('send', 's')} ${tr('Contact support')}</a>` : ''}</div>` : ''}${syncHtml()}`;
}
function accountHtml() {
  const m = S.me, pw = m.auth === 'session' || m.has_password;
  return `<h4 id="s-account-h">${tr('Account')}</h4>
    <div class="row"><label>${tr('Logged in as')}</label><span class="acct">${av(m.id, m.display_name)}<b>${esc(m.display_name)}</b> <span class="muted">${esc(m.username)}${m.auth === 'proxy' ? ' · ' + tr('via single sign-on') : ''}</span></span></div>
    ${sup_accountRow()}${''/* 2.74.0 (#338): the supporter badge (self-hosted only) */}
    <div class="row"><label for="a-name">${tr('Display name')}</label><input id="a-name" value="${esc(m.display_name)}" maxlength="60" autocomplete="name" enterkeyhint="done"></div>
    <div class="row avrow"><label>${tr('Profile picture')}</label><div class="avpick" id="a-avpick">${avPickHtml()}</div></div>
    <div class="row"><label id="a-col-h">${tr('Colour')}</label><div class="pfcol" id="a-col" role="group" aria-labelledby="a-col-h">${ac_pickHtml((S.colors || {})[m.id] || '', 'me')}</div></div>
    ${pw ? `<div class="row"><label for="a-cur">${tr('Password')}</label><input type="text" class="cfhid" hidden tabindex="-1" aria-hidden="true" autocomplete="username" value="${esc(S.me?.username || '')}" readonly><input type="password" id="a-cur" placeholder="${tr('current password')}" autocomplete="current-password"><input type="password" id="a-new" placeholder="${tr('new password')}" autocomplete="new-password"><button class="btn sm" data-acc="pw">${tr('Change')}</button></div>` : ''}
    ${storageHtml()}
    ${dsc_rowHtml()}${''/* 2.49.0 (#1106): People: find, requests, findable by e-mail */}
    ${wsPaneOn() ? (lmOrgPaneOn() ? lmOrgLinkHtml() : wsPaneHtml(t => `<div class="shint">${t}</div>`)) : ''}
    ${tfaHtml()}
    ${e2eHtml()}${''/* 2.42.0 (#828, #909) */}
    ${apwHtml()}
    <details class="sdev"><summary>${ic('key', 's')}${tr('Advanced · for developers')}</summary>
    <div class="row"><label>${tr('Upload token')}</label><button class="btn sm" data-m="go-share">${ic('phone', 's')} ${tr('Share from your phone')}</button><span class="muted" style="font-size:var(--fs-s)">${tr('shown and renewed there')}</span></div>
    ${apiHtml()}</details>
    ${m.auth === 'session' ? `<div class="row alogout"><button class="btn sm" data-acc="logout">${ic('logout', 's')} ${tr('Log out')}</button></div>` : ''}`;  // 2.24.0 (UX-21): at the very end, set apart
}
// 2.88.0 (#1980): search, filter and pages (hundreds of accounts), several accounts at once
const UA8_FLT = [['people', N_('People')], ['active', N_('Active')], ['disabled', N_('Disabled')], ['admin', N_('Admins')], ['invited', N_('Invited')], ['pending', N_('Waiting for approval')], ['agents', N_('Agents')]];
const UA8_PAGE = 50;
const usersHtml = () => `<h4>${tr('Users')}</h4>
  <div class="ua8bar"><input type="search" id="a-uq" placeholder="${esc(tr('Name, user name or e-mail'))}" aria-label="${esc(tr('Search users'))}" autocomplete="off" autocapitalize="off" spellcheck="false"><select id="a-uflt" aria-label="${esc(tr('Filter'))}">${UA8_FLT.map(([k, n]) => `<option value="${k}">${esc(tr(n))}</option>`).join('')}</select></div>
  <div class="ua8sel" id="a-usel" role="region" aria-label="${esc(tr('Selected users'))}" hidden></div>
  <div class="members" id="a-users" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div>
  <div class="ua8pg" id="a-upg"></div>
  <div class="row" style="margin-top:.5rem"><button class="btn sm" data-acc="user-new">${ic('plus', 's')} ${tr('New user')}</button></div>`;
// ------------------------------------------------------------------ 2.10.0 (#441): groups
// Settings > Administration > Groups (admins): name, members (people), optionally a sign-in group (OIDC) the members follow
const grpHtml = () => collab() ? `<h4 id="s-groups-h">${tr('Groups')}</h4>
  <div class="shint">${tr('Share lists and folders with a group and assign tasks to it (“whoever has time”). New members get access at once, members who leave lose it.')}</div>
  <div class="members" id="a-groups"></div>
  <div class="row"><button class="btn sm" data-grp="new">${ic('plus', 's')} ${tr('New group')}</button></div>` : '';
function grpDraw(md) {
  const box = $('#a-groups', md); if (!box) return;
  const gs = S.groups || [];
  box.innerHTML = gs.length ? gs.map(g => `<div class="mrow" data-grow="${g.id}">${fg_gav(g.id)}<span class="n">${esc(g.name)} <span class="muted">${g.members.length ? esc(g.members.map(m => m.name).join(', ')) : tr('no members yet')}${g.synced ? ' · ' + esc(tr('sign-in group {0}', g.oidc_group)) : ''}</span></span><button class="iconbtn" data-grp="edit" data-gid="${g.id}" title="${esc(tr('Edit group'))}" aria-label="${esc(tr('Edit group {0}', g.name))}">${ic('edit', 's')}</button></div>`).join('')
    : `<div class="muted mhint">${tr('No groups yet')}</div>`;
  if (md._grpWired) return;
  md._grpWired = true;
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-grp]'); if (!b || !md.contains(b)) return;
    grpEdit(md, b.dataset.grp === 'edit' ? +b.dataset.gid : null);
  });
}
async function grpEdit(smd, gid) {
  const g = gid ? grpById(gid) : null;
  let users = [];
  try { users = (await api('GET', '/api/users')).users.filter(u => u.kind !== 'agent' && !u.disabled); } catch { return; }
  const sel = new Set((g?.members || []).map(m => m.user_id)), synced = !!g?.oidc_group;
  const md = modal(`<h3>${g ? tr('Edit group') : tr('New group')}</h3>
    <div class="row"><label for="gr-name">${tr('Name')}</label><input id="gr-name" maxlength="60" value="${esc(g?.name || '')}" placeholder="${esc(tr('e.g. Office'))}"></div>
    ${fg_pickRow(g)}
    <div class="row"><label for="gr-oidc">${tr('Sign-in group')}</label><input id="gr-oidc" maxlength="200" value="${esc(g?.oidc_group || '')}" placeholder="${esc(tr('optional · OIDC group name'))}"></div>
    <div class="shint">${tr('With a sign-in group the members come from the sign-in provider (OIDC): whoever has that group in their login is a member, checked at every login.')}</div>
    <h4 id="gr-mem-h">${tr('Members')}</h4>
    <div class="grpmem" id="gr-mem" role="group" aria-labelledby="gr-mem-h">${users.map(u => `<label class="chkl"><input type="checkbox" data-gm="${u.id}" ${sel.has(u.id) ? 'checked' : ''} ${synced ? 'disabled' : ''}> ${esc(u.display_name)} <span class="muted">${esc(u.username)}</span></label>`).join('') || `<div class="muted mhint">${tr('No other users yet. An admin can add them in the settings.')}</div>`}</div>
    <div class="calerr" role="alert" id="gr-err" hidden></div>
    <div class="foot">${g ? `<button class="btn danger" data-m="del">${ic('trash', 's')} ${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${g ? tr('Save') : tr('Create')}</button></div>`);
  md.classList.add('grpmodal');
  const syncMem = () => { const on = !!$('#gr-oidc', md).value.trim(); $$('[data-gm]', md).forEach(x => { x.disabled = on; }); };
  $('#gr-oidc', md).addEventListener('input', syncMem);
  const fgPend = fg_pickWire(md, g);  // 2.46.0 (#1605)
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const err = $('#gr-err', md);
    if (b.dataset.m === 'del') {
      if (!await askConfirm(tr('Delete the group {0}?', g.name), tr('Its members lose the access they had only through it; tasks assigned to it become unassigned.'), {ok: tr('Delete'), danger: true})) return;
      try { await calReq('DELETE', `/api/admin/groups/${gid}`); } catch (x) { err.textContent = x.message; err.hidden = false; return; }
      md.remove(); await load().catch(() => {}); render(); grpDraw(smd); toast(tr('Group deleted')); return;
    }
    const name = $('#gr-name', md).value.trim(), og = $('#gr-oidc', md).value.trim();
    if (!name) { need($('#gr-name', md)); return; }
    const q = {name, oidc_group: og, ...(og ? {} : {members: $$('[data-gm]', md).filter(x => x.checked).map(x => +x.dataset.gm)})};
    b.disabled = true;
    try { const j = await calReq(g ? 'PATCH' : 'POST', g ? `/api/admin/groups/${gid}` : '/api/admin/groups', q); await fg_pickSave(j?.id || gid, fgPend()); } catch (x) { err.textContent = x.message; err.hidden = false; b.disabled = false; return; }
    md.remove(); await load().catch(() => {}); render(); grpDraw(smd); toast(g ? tr('Group saved') : tr('Group created'));
  });
  if (!isTouch()) setTimeout(() => $('#gr-name', md)?.focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
// 2.23.0 (#799): a shared server (KALMIDO_INSTANCE_MODE=shared) says so; 2.46.0 (#1592): every other server has workspaces
const orgsHtml = () => S.instanceMode === 'shared' ? `<h4 id="a-orgs-h">${tr('Organisation')}</h4><div class="shint">${tr('A shared server: no organisations; people see only the people they are connected with and share by e-mail address (set by the server configuration).')}</div>`
  : `<h4 id="a-orgs-h">${tr('Organisations')}</h4><div class="shint">${tr('A shared server with workspaces: every organisation is its own workspace with its own admins, who manage its members. People see the members of their organisations and the people they are connected with; private lists stay invisible to an organisation.')}</div>
  <div class="members" id="a-orgs"><div class="muted mhint">${tr('Loading…')}</div></div><div class="row"><button class="btn sm" data-acc="org-new">${ic('plus', 's')} ${tr('New organisation')}</button></div>`;
// 2.46.0 (#1561): "Add person": the organisation (none / each one; exactly one: preselected, as a member) and the role in it
function omNewOrgRows() {
  const os = S.orgs || [], one = os.length === 1 ? os[0].id : 0;
  return `<div class="row"><label for="u-org">${tr('Organisation')}</label><select id="u-org"><option value="0">${tr('None (private space only)')}</option>${os.map(o => `<option value="${o.id}" ${o.id === one ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select></div>
    <div class="row" id="u-orgrow" ${one ? '' : 'hidden'}><label for="u-orgrole">${tr('Role in the organisation')}</label><select id="u-orgrole"><option value="member">${tr('Member')}</option><option value="admin">${tr('Admin of the organisation')}</option></select></div>`;
}
async function orgModal(o, done) {
  let us = []; try { us = (await api('GET', '/api/users?all=1')).users.filter(u => !u.disabled && u.kind !== 'agent'); } catch { return; }
  // 2.46.0 (#1561): fresh members (people added since the list was drawn), else saving would drop them
  if (o) { try { S.orgs = (await api('GET', '/api/admin/orgs')).orgs; o = S.orgs.find(x => x.id === o.id) || o; } catch { return; } }
  const mem = new Set(o?.members || []), adm = new Set(o?.admins || []);  // 2.28.0 (#935): + the organisation's admins
  const md = modal(`<h3>${o ? tr('Edit organisation') : tr('New organisation')}</h3>
    <div class="row"><label for="og-name">${tr('Name')}</label><input id="og-name" maxlength="60" value="${esc(o?.name || '')}"></div>
    <div class="row"><label for="og-icon">${tr('Symbol')}</label><input id="og-icon" maxlength="8" class="numin" value="${esc(o?.icon || '')}" placeholder="🏢"></div>
    <div class="row"><label for="og-dom">${tr('E-mail domains')}</label><input id="og-dom" maxlength="500" value="${esc(o?.domains || '')}" placeholder="example.com" autocapitalize="off"><span class="muted">${tr('registrations with these addresses join it')}</span></div>
    ${o ? `<div class="row"><label>${tr('Members')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Members'))}">${us.map(u => `<button type="button" class="fperson ${mem.has(u.id) ? 'on' : ''}" data-ogm="${u.id}" aria-pressed="${mem.has(u.id)}">${av(u.id, u.display_name)}<span>${esc(u.display_name)}</span></button>`).join('')}</div></div>
    <div class="row"><label>${tr('Admins of the organisation')}</label><div class="fpeople" id="og-adm" role="group" aria-label="${esc(tr('Admins of the organisation'))}">${us.filter(u => mem.has(u.id)).map(u => `<button type="button" class="fperson ${adm.has(u.id) ? 'on' : ''}" data-oga="${u.id}" aria-pressed="${adm.has(u.id)}">${av(u.id, u.display_name)}<span>${esc(u.display_name)}</span></button>`).join('')}</div></div>
    <div class="shint">${tr('Admins of an organisation manage its members, name and e-mail domains (Settings > Workspaces); they are not admins of the server.')}</div>` : `<div class="shint">${tr('You become its first member and admin; add people afterwards.')}</div>`}
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${o ? tr('Save') : tr('Create')}</button></div>`);
  md.addEventListener('click', async e => {
    const p = e.target.closest('[data-ogm]');
    if (p) { const id = +p.dataset.ogm; mem.has(id) ? mem.delete(id) : mem.add(id); if (!mem.has(id)) adm.delete(id); p.classList.toggle('on', mem.has(id)); p.setAttribute('aria-pressed', mem.has(id)); const ab = $('#og-adm', md); if (ab) ab.innerHTML = us.filter(u => mem.has(u.id)).map(u => `<button type="button" class="fperson ${adm.has(u.id) ? 'on' : ''}" data-oga="${u.id}" aria-pressed="${adm.has(u.id)}">${av(u.id, u.display_name)}<span>${esc(u.display_name)}</span></button>`).join(''); return; }
    const pa = e.target.closest('[data-oga]');
    if (pa) { const id = +pa.dataset.oga; adm.has(id) ? adm.delete(id) : adm.add(id); pa.classList.toggle('on', adm.has(id)); pa.setAttribute('aria-pressed', adm.has(id)); return; }
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      if (b.dataset.m === 'save') {
        const body = {name: $('#og-name', md).value.trim(), icon: $('#og-icon', md).value.trim(), domains: $('#og-dom', md).value};
        if (o) {
          await api('PATCH', `/api/admin/orgs/${o.id}`, {...body, members: [...mem], admins: [...adm].filter(id => mem.has(id))});
        } else await api('POST', '/api/admin/orgs', body);
      }
      md.remove(); done && done(); await load(); render();
    } catch { /* api() said it */ }
  });
}
function wsPaneHtml(hint) {
  return `<h4 id="s-ws-h">${tr('Workspaces')}</h4>${hint(tr('Private and your organisations. Every list belongs to one workspace; the switch in the sidebar shows one at a time. An organisation’s list is shared only inside it; private sharing stays invisible to the organisation.'))}
    <div class="members" id="s-ws" aria-labelledby="s-ws-h"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
function accountWire(md) {
  let users = [];
  const us = {q: '', flt: 'people', off: 0, total: 0, sel: new Set(), seq: 0};  // 2.88.0 (#1980): the page shown
  const drawUsers = async () => {
    const box = $('#a-users', md); if (!box) return;
    const n = ++us.seq, qs = new URLSearchParams({all: '1', limit: String(UA8_PAGE), offset: String(us.off), q: us.q, filter: us.flt});
    let j; try { j = await api('GET', '/api/users?' + qs); } catch { return; }
    if (n !== us.seq || !md.isConnected) return;  // a newer search answered first
    users = j.users; S.mailOut = !!j.mail_out; us.total = j.total;
    if (!users.length && us.off && j.total) { us.off = Math.max(0, Math.floor((j.total - 1) / UA8_PAGE) * UA8_PAGE); drawUsers(); return; }
    // 2.28.0 (#1011): people only; the agents are managed under Agents (one row says how many; 2.88.0: the filter Agents lists them)
    const nAg = us.flt === 'people' && !us.q ? j.agents : 0;
    box.innerHTML = (nAg ? `<div class="mrow agsum"><span class="avatar agent">${ic('bot', 's')}</span><span class="n">${esc(trn('{0} agent', '{0} agents', nAg))}</span><button class="linkbtn" data-act="agents-go">${tr('Manage under Agents')}</button></div>` : '')
      + (users.length ? '' : `<div class="muted mhint">${tr('Nothing found')}</div>`)
      + users.map(u => `<div class="mrow ${u.disabled ? 'off' : ''}" data-urow="${u.id}"><input type="checkbox" class="ua8chk" data-usel="${u.id}" aria-label="${esc(tr('Select {0}', u.display_name))}" ${us.sel.has(u.id) ? 'checked' : ''} ${u.id === S.me.id ? 'disabled' : ''}>${u.avatar ? `<span class="avatar pic"><img src="${esc(u.avatar)}" alt="" loading="lazy"></span>` : av(0, u.display_name)}<span class="n">${esc(u.display_name)}${u.kind === 'agent' ? ' ' + agentBadge() : ''} <span class="muted">${esc(u.username)}${u.is_admin ? ' · ' + tr('Admin') : ''}${u.disabled ? ' · ' + tr('disabled') : ''}${u.proxy_login ? ' · ' + tr('SSO: {0}', u.proxy_login) : ''}${u.twofa?.length ? ' · ' + tr('2FA') : ''}${u.oidc_linked ? ' · OIDC' : ''}${u.invite === 'invited' ? ' · ' + tr('Invited') : u.invite === 'expired' ? ' · ' + tr('Invitation expired') : ''}${u.signup === 'pending' ? ' · ' + tr('waits for approval') : u.signup === 'confirm' ? ' · ' + tr('registration not confirmed') : ''}</span></span>${u.signup === 'pending' ? `<button class="btn sm pri" data-acc="user-approve" data-uid="${u.id}">${ic('check', 's')} ${tr('Approve')}</button>` : ''}${u.kind === 'agent'
      ? `<button class="linkbtn agmng" data-acc="agent-edit" data-uid="${u.id}" title="${esc(tr('Open the agent dialog'))}">${tr('Managed under Agents')}</button>`
      : `<button class="iconbtn" data-acc="user-edit" data-uid="${u.id}" title="${tr('Edit user')}">${ic('edit', 's')}</button>`}</div>`).join('');
    ua8_pagerDraw(md, us); ua8_selDraw(md, us);
  };
  ua8_wire(md, us, drawUsers);
  drawUsers();
  orgsDraw(md);
  if (wsPaneOn()) { wsPaneDraw(md); wsPaneWire(md); }  // 2.28.0 (#935)
  md.addEventListener('change', async e => {  // 2.22.0 (#752): whom people see
    if (e.target.id !== 'a-vis') return;
    try { await api('PUT', '/api/admin/orgs/visibility', {mode: e.target.value}); toast(tr('Saved')); await load(); } catch { /* api() said it */ }
  });
  md.addEventListener('click', async e => {
    const p = e.target.closest('#a-avpick [data-av]');
    if (p) {
      const k = p.dataset.av;
      try {
        if (k === 'upload') avUpload();
        else if (k === 'none') { if (S.me.avatar) avSet(await api('DELETE', '/api/me/avatar')); }
        else avSet(await api('PUT', '/api/me/avatar', {preset: k}));
      } catch { /* api() showed it */ }
      return;
    }
    const b = e.target.closest('[data-acc]'); if (!b) return;
    const a = b.dataset.acc;
    try {
      if (a === 'pw') {
        const nw = $('#a-new', md).value;
        if (nw.length < 8) { toast(tr('Password: at least {0} characters', 8)); return; }
        await api('PATCH', '/api/me', {current_password: $('#a-cur', md).value, password: nw});
        $('#a-cur', md).value = ''; $('#a-new', md).value = ''; toast(tr('Password changed'));
      }
      if (a === 'logout') logout();
      if (a === 'user-new') userModal(null, () => { drawUsers(); orgsDraw(md); });  // 2.58.0 (#1724): the organisations' member counts follow at once
      if (a === 'user-approve') { await api('POST', `/api/users/${b.dataset.uid}/approve`, {}); toast(tr('Approved: the person can log in now')); drawUsers(); }  // 2.23.0 (#711)
      if (a === 'org-edit') orgModal((S.orgs || []).find(o => o.id === +b.dataset.oid), () => orgsDraw(md));
      if (a === 'org-new') orgModal(null, () => { orgsDraw(md); load().then(render).catch(() => {}); });  // 2.28.0 (#935)
      if (a === 'org-del') {
        const o = (S.orgs || []).find(x => x.id === +b.dataset.oid);
        if (o && await askConfirm(tr('Delete the organisation “{0}”?', o.name), tr('Only possible while it has no lists. Its members keep their accounts.'), {ok: tr('Delete'), danger: true})) { await api('DELETE', `/api/admin/orgs/${o.id}`); toast(tr('Deleted')); orgsDraw(md); load().then(render).catch(() => {}); }
      }
      if (a === 'user-edit') userModal(users.find(u => u.id === +b.dataset.uid), () => { drawUsers(); orgsDraw(md); });
      if (a === 'agent-edit') {
        const aj = await calReq('GET', '/api/admin/agents'), ag = aj.agents.find(x => x.id === +b.dataset.uid);
        S.agOffer = aj.scopes;
        if (ag) agModal(ag, () => { drawUsers(); agDraw(md); });
      }
    } catch { /* api() showed it */ }
  });
}
function userModal(u, done) {
  const md = modal(`<h3>${u ? tr('Edit user') : tr('New user')}</h3>
    <div class="row"><label for="u-name">${tr('Display name')}</label><input id="u-name" value="${esc(u?.display_name || '')}" maxlength="60" placeholder="${esc(tr('e.g. Alice Example'))}"></div>
    <div class="row"><label for="u-user">${tr('Username')}</label><input id="u-user" class="unin" value="${esc(u?.username || '')}" ${u ? 'disabled' : ''} autocapitalize="off" placeholder="${tr('a-z, 0-9, . - _')}"><span class="muted">${tr('for the login and @mentions')}</span></div>
    <div class="shint keep" id="u-userhint" hidden></div>
    <div class="row"><label for="u-pw">${tr('Password')}</label><input type="password" id="u-pw" autocomplete="new-password" placeholder="${u ? (u.has_password ? tr('unchanged') : tr('none (single sign-on only)')) : tr('optional, min. 8 characters')}"></div>
    <div class="row"><label for="u-proxy">${tr('SSO login')}</label><input id="u-proxy" value="${esc(u?.proxy_login || '')}" autocapitalize="off" placeholder="${tr('user name at the login proxy (optional)')}"></div>
    <div class="row"><label for="u-email">${tr('E-mail')}</label><input id="u-email" type="email" value="${esc(u?.email || '')}" autocapitalize="off" placeholder="${tr('optional, links an OIDC login')}"></div>
    ${!u && S.instanceMode === 'workspaces' && (S.orgs || []).length ? omNewOrgRows() : ''}
    ${u && S.instanceMode === 'workspaces' && (S.orgs || []).length ? `<div class="row"><label>${tr('Organisations')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Organisations'))}">${S.orgs.map(o => { const on = u ? (u.orgs || []).includes(o.id) : o.members.includes(S.me.id); return `<button type="button" class="fperson ${on ? 'on' : ''}" data-uorg="${o.id}" aria-pressed="${on}"><span aria-hidden="true">${esc(o.icon || '🏢')}</span><span>${esc(o.name)}</span></button>`; }).join('')}</div></div>` : ''}
    <div class="row"><label for="u-topic">${tr('ntfy topic')}</label><input id="u-topic" value="${esc(u?.ntfy_topic || '')}" autocapitalize="off" placeholder="${tr('empty = random')}"></div>
    ${u ? `<div class="row avrow"><label>${tr('Profile picture')}</label><div class="avpick" id="u-avpick" data-cur="${esc(u.avatar || '')}">${avPickHtml(u.avatar || '', false, u.display_name || u.username)}</div></div>` : ''}
    <div class="row"><label>${tr('Rights')}</label><label class="chkl"><input type="checkbox" id="u-admin" ${u?.is_admin ? 'checked' : ''}> ${tr('Admin')}</label>${u ? `<label class="chkl"><input type="checkbox" id="u-dis" ${u.disabled ? 'checked' : ''}> ${tr('disabled')}</label>` : ''}</div>
    ${!u || (u.kind !== 'agent' && u.id !== S.me.id) ? `<div class="row"><label>${tr('Child account')}</label><label class="chkl"><input type="checkbox" id="u-kid" aria-controls="u-parrow" aria-expanded="${!!u?.kid}" ${u?.kid ? 'checked' : ''}> ${tr('A simple view with big buttons, stars and rewards; takes part in shared lists only with what is assigned to it')}</label></div>
    <div class="row kidopts" id="u-parrow" ${u?.kid ? '' : 'hidden'}><label>${tr('Parents')}</label><div class="fpeople" id="u-parents" role="group" aria-label="${esc(tr('Parents'))}"><span class="muted">${tr('Loading…')}</span></div></div>` : ''}
    ${u && !u.is_admin && u.id !== S.me.id ? `<div class="row"><label for="u-kind">${tr('Type')}</label><select id="u-kind"><option value="user">${tr('Person')}</option><option value="agent" ${u.kind === 'agent' ? 'selected' : ''}>${tr('Agent (API only, never admin)')}</option></select></div>` : ''}
    ${u?.has_password ? `<div class="row"><label></label><label class="chkl"><input type="checkbox" id="u-nopw"> ${tr('Remove password (single sign-on only)')}</label></div>` : ''}
    ${!u ? `<div class="row"><label>${tr('Invitation')}</label><label class="chkl"><input type="checkbox" id="u-inv" checked> ${S.mailOut ? tr('Send an invitation by e-mail: the person sets their own password') : tr('Create an invitation link: the person sets their own password')}</label></div>`
      : u.kind !== 'agent' && !u.disabled ? `<div class="row"><label>${u.has_password ? tr('Password') : tr('Invitation')}</label><button type="button" class="btn sm" data-m="invite">${ic(u.has_password ? 'key' : 'send', 's')} ${u.has_password ? tr('Send a link to set a new password') : u.invite ? tr('Send the invitation again') : tr('Send an invitation')}</button></div>` : ''}
    ${u && u.kind !== 'agent' && !u.is_admin && !u.disabled && u.id !== S.me.id ? `<div class="row"><label>${tr('Sign-in link')}</label><button type="button" class="btn sm" data-m="signin">${ic('key', 's')} ${tr('Sign-in link / QR code…')}</button><span class="muted">${tr('for family members without e-mail')}</span></div>` : ''}
    ${u?.twofa?.length ? `<div class="row"><label>${tr('Two-factor')}</label><label class="chkl"><input type="checkbox" id="u-2fareset"> ${tr('Reset (lost phone / passkey and recovery codes)')}</label></div>` : ''}
    ${u?.oidc_linked ? `<div class="row"><label>OIDC</label><label class="chkl"><input type="checkbox" id="u-oidcun"> ${tr('Unlink (the next OIDC login links again by user name or e-mail)')}</label></div>` : ''}
    <div class="muted" style="font-size:var(--fs-s);line-height:1.6">${tr('Every user gets an own basket, habits, filters, tags and settings. Lists are shared from the list’s “…” menu > Share….')}</div>
    <div class="foot">${u && u.id !== S.me.id ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  // 2.19.0 (#653): a child account and its parents (people, never agents or other children)
  const par = new Set(u?.parents || []);
  const parDraw = async () => {
    const box = $('#u-parents', md); if (!box) return;
    let us = []; try { us = (await api('GET', '/api/users')).users; } catch { return; }
    if (!md.isConnected) return;
    const cand = us.filter(x => !x.disabled && x.kind !== 'agent' && !x.agent && !x.kid && x.id !== u?.id);
    if (!u && !par.size) par.add(S.me.id);
    box.innerHTML = cand.map(x => `<button type="button" class="fperson ${par.has(x.id) ? 'on' : ''}" data-upar="${x.id}" aria-pressed="${par.has(x.id)}">${av(x.id, x.display_name)}<span>${esc(x.display_name)}</span></button>`).join('') || `<span class="muted">${tr('Nobody else yet')}</span>`;
  };
  if ($('#u-parents', md)) parDraw();
  md.addEventListener('change', e => { if (e.target.id === 'u-org') $('#u-orgrow', md).hidden = !+e.target.value; });  // 2.46.0 (#1561)
  md.addEventListener('change', e => { if (e.target.id === 'u-kid') { $('#u-parrow', md).hidden = !e.target.checked; e.target.setAttribute('aria-expanded', e.target.checked);  /* 2.22.0: the child options only once ticked */ if (e.target.checked) { $('#u-admin', md).checked = false; } } });
  md.addEventListener('click', e => { const b = e.target.closest('[data-uorg]'); if (!b) return; const on = b.getAttribute('aria-pressed') !== 'true'; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });  // 2.22.0 (#752)
  md.addEventListener('click', e => { const b = e.target.closest('[data-upar]'); if (!b) return; const id = +b.dataset.upar; par.has(id) ? par.delete(id) : par.add(id); b.classList.toggle('on', par.has(id)); b.setAttribute('aria-pressed', par.has(id)); });
  md.addEventListener('click', e => {  // the picture choice is sent with "Save"
    const p = e.target.closest('#u-avpick [data-av]'); if (!p) return;
    const box = $('#u-avpick', md), k = p.dataset.av;
    box.dataset.pick = k;
    $$('[data-av]', box).forEach(x => { x.classList.toggle('on', x === p); x.setAttribute('aria-pressed', x === p); });
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'signin') { signinLink(u.id, u.display_name); return; }  // 2.23.0 (#444)
    if (b.dataset.m === 'invite') {  // 2.22.0 (#697): a new one-time link (invitation / password reset)
      try { const j = await api('POST', `/api/users/${u.id}/invite`, {send: true}); inviteResult(j, u.display_name); done && done(); } catch { /* api() said it */ }
      return;
    }
    let created = false;
    try {
      if (b.dataset.m === 'del') {
        if (!await ua8_delete(u)) return;  // 2.88.0 (#1980): the lists go to one person or are deleted along
      }
      if (b.dataset.m === 'save') {
        const body = {display_name: $('#u-name', md).value.trim(), proxy_login: $('#u-proxy', md).value.trim(), email: $('#u-email', md).value.trim(), ntfy_topic: $('#u-topic', md).value.trim(), is_admin: $('#u-admin', md).checked};
        if ($('#u-2fareset', md)?.checked) { if (!await askConfirm(tr('Reset the two-factor authentication of “{0}”?', u.display_name), tr('They log in with the password alone (or must set it up again if it is required).'), {ok: tr('Reset'), danger: true})) return; body.reset_2fa = true; }
        if ($('#u-oidcun', md)?.checked) body.oidc_unlink = true;
        if ($('#u-kid', md) && ($('#u-kid', md).checked || u?.kid)) { body.kid = $('#u-kid', md).checked; if (body.kid) { body.parents = [...par]; body.is_admin = false; } }
        const avk = $('#u-avpick', md)?.dataset.pick; if (avk) body.avatar_preset = avk === 'none' ? null : avk;
        if ($('[data-uorg]', md)) body.orgs = $$('[data-uorg][aria-pressed="true"]', md).map(x => +x.dataset.uorg);  // 2.22.0 (#752)
        const omo = $('#u-org', md); if (omo && +omo.value) body.orgs = [{id: +omo.value, role: body.kid ? 'member' : $('#u-orgrole', md).value}];  // 2.46.0 (#1561)
        const pw = $('#u-pw', md).value;
        if (pw) body.password = pw; else if ($('#u-nopw', md)?.checked) body.password = '';
        if ($('#u-kind', md) && $('#u-kind', md).value !== (u.kind || 'user')) {
          if ($('#u-kind', md).value === 'agent' && !await askConfirm(tr('Make “{0}” an agent?', u.display_name), tr('An agent works only through its API tokens: no web login, never admin. Its lists and tokens stay. Manage it under Settings > Agents.'), {ok: tr('Make agent')})) return;
          body.kind = $('#u-kind', md).value;
        }
        if (u) { body.disabled = $('#u-dis', md).checked; await api('PATCH', '/api/users/' + u.id, body); }
        else {
          body.username = $('#u-user', md).value.trim().toLowerCase(); if (!body.ntfy_topic) delete body.ntfy_topic;
          if (userNameBad(body.username)) { const h = $('#u-userhint', md); h.textContent = userNameBad(body.username); h.hidden = false; need($('#u-user', md)); return; }  // 2.28.0 (#926)
          if (!pw && $('#u-inv', md)?.checked) { body.invite = true; if (S.mailOut && !body.email) { toast(tr('Please enter the e-mail address for the invitation')); $('#u-email', md).focus(); return; } }
          const nu = await api('POST', '/api/users', body); created = true;
          if (nu.invitation) { md.remove(); done && done(); inviteResult(nu.invitation, nu.display_name); await offerCollab(); await load(); render(); return; }
        }
      }
      md.remove(); toast(tr('Saved')); done && done();
      if (created) await offerCollab();
      await load(); render();
    } catch { /* api() showed it */ }
  });
  userNameFollow(md, 'u-name', 'u-user', 'u-userhint');  // 2.28.0 (#926)
  if (!isTouch() && (!u))  setTimeout(() => $('#u-name', md).focus(), 50);
}
// 2.22.0 (#697): what happened to an invitation / reset link: sent by e-mail, or the link to copy (no SMTP, no address)
function inviteResult(j, name) {
  if (j.sent) { toast(tr('Sent to {0}: the link works once and for 7 days', j.email)); return; }
  const md = modal(`<h3>${ic('send', 's')} ${j.kind === 'reset' ? tr('Link to set a new password') : tr('Invitation link')}</h3>
    <p>${esc(j.error || tr('Send this link to {0} yourself (it works once and for 7 days):', name))}</p>
    <div class="row"><input id="inv-link" readonly value="${esc(j.link)}" aria-label="${esc(tr('Link'))}"><button type="button" class="btn" data-m="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') md.remove();
    if (b.dataset.m === 'copy') { try { await navigator.clipboard.writeText(j.link); toast(tr('Copied')); } catch { $('#inv-link', md).select(); } }
  });
}
function rcModal(codes) {
  return new Promise(done => {
    const md = modal(`<h3>${tr('Recovery codes')}</h3>${rcHtml(codes)}<div class="foot"><span class="spacer"></span><button class="btn pri" data-m="ok">${tr('I have saved them')}</button></div>`);
    md.classList.add('rcmodal');
    rcWire(md, codes);
    md.addEventListener('click', e => { if (e.target.closest('[data-m="ok"]')) { md.remove(); done(); } });
  });
}
// ---- Settings > Account > Two-factor authentication
const tfaHtml = () => `<h4 id="s-2fa-h">${tr('Two-factor authentication')}</h4><div id="s-2fa"><div class="muted mhint">${tr('Loading…')}</div></div>`;
async function tfaDraw(md, j) {
  const box = $('#s-2fa', md); if (!box) return;
  if (!j) { try { j = await api('GET', '/api/me/2fa'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; } }
  box._j = j;
  const hint = t => `<div class="shint">${t}</div>`;
  if (!j.available) {
    box.innerHTML = hint(j.via === 'proxy' || j.via === 'oidc' || S.me?.auth === 'proxy' ? tr('You log in with single sign-on: a second factor is set up at your login provider, not here.')
      : tr('Two-factor authentication is available for accounts with a password.'));
    return;
  }
  const when = x => x ? new Date(x).toLocaleDateString(I18N.code || 'en') : '';
  const on = j.totp || j.passkeys.length;
  let h = j.required ? hintK(tr('Required on this server: keep at least one method (authenticator app or passkey).')) : '';
  h += `<div class="row"><label>${tr('Authenticator app')}</label><span class="tfastate ${j.totp ? 'on' : ''}">${j.totp ? tr('On') : tr('Off')}</span>
      ${j.totp ? `<button class="btn sm" data-tfa="totp-off">${tr('Turn off')}</button>` : `<button class="btn sm pri" data-tfa="totp-on">${ic('lock', 's')} ${tr('Set up')}</button>`}</div>`;
  h += `<div class="row"><label>${tr('Passkeys')}</label><button class="btn sm" data-tfa="pk-add" ${pkSupported() ? '' : 'disabled'}>${ic('key', 's')} ${tr('Add a passkey')}</button></div>`;
  if (!pkSupported()) h += hintK(tr('Passkeys need HTTPS (or localhost), a host name instead of an IP address and a current browser.'));
  if (j.passkeys.length) h += `<div class="members pklist">${j.passkeys.map(p => `<div class="mrow" data-pk="${p.id}"><span class="avatar">${ic('key', 's')}</span><span class="n">${esc(p.name)} <small class="muted">${tr('added {0}', esc(when(p.created_at)))}${p.last_used_at ? ' · ' + tr('last used {0}', esc(when(p.last_used_at))) : ''}${p.synced ? ' · ' + tr('synced') : ''}</small></span><button class="iconbtn" data-tfa="pk-ren" title="${tr('Rename')}">${ic('edit', 's')}</button><button class="iconbtn" data-tfa="pk-del" title="${tr('Remove')}">${ic('trash', 's')}</button></div>`).join('')}</div>`;
  if (on) h += `<div class="row"><label>${tr('Recovery codes')}</label><span class="muted">${trn('{0} left', '{0} left', j.recovery_left)}</span><button class="btn sm" data-tfa="rc-new">${tr('New codes')}</button></div>`;
  h += hint(on ? tr('After your password, the login asks for a code from the app or your passkey.') + (j.passkey_login && j.passkeys.length ? ' ' + tr('A passkey also logs you in without the password (“Log in with a passkey”).') : '')
    : tr('Protects your account if your password gets out: after the password, the login also asks for a code from an app on your phone or for a passkey (fingerprint, face or security key).'));
  box.innerHTML = h;
}
function tfaWire(md) {
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-tfa]'); if (!b) return;
    const a = b.dataset.tfa, box = $('#s-2fa', md), j = box?._j || {};
    const pid = +b.closest('[data-pk]')?.dataset.pk;
    b.disabled = true;
    try {
      if (a === 'totp-on') {
        const pw = await pwPrompt(tr('Set up the authenticator app')); if (!pw) return;
        const t = await api('POST', '/api/me/2fa/totp', {password: pw.password});
        const res = await new Promise(done => {
          const m = modal(`<h3>${tr('Set up the authenticator app')}</h3><form class="totpform">${totpSetupHtml(t)}<div class="aerr" role="alert" id="totp-err"></div>
            <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Turn on')}</button></div></form>`);
          m.classList.add('totpmodal');
          m.addEventListener('click', ev => { if (ev.target.closest('[data-m="close"]')) { m.remove(); done(null); } });
          m.querySelector('form').addEventListener('submit', async ev => {
            ev.preventDefault();
            try { const r = await rawFetch('POST', '/api/me/2fa/totp/confirm', {code: $('#totp-code', m).value}); m.remove(); done(r); }
            catch (x) { $('#totp-err', m).textContent = x.message; }
          });
          setTimeout(() => $('#totp-code', m)?.focus(), 50);
        });
        if (!res) return;
        toast(tr('Two-factor authentication is on'));
        if (res.recovery_codes) await rcModal(res.recovery_codes);
        await tfaDraw(md, res); await refreshMe();
      }
      if (a === 'totp-off') {
        const pw = await pwPrompt(tr('Turn off the authenticator app'), {code: true}); if (!pw) return;
        await tfaDraw(md, await api('POST', '/api/me/2fa/totp/disable', pw)); toast(tr('Authenticator app turned off')); await refreshMe();
      }
      if (a === 'rc-new') {
        const pw = await pwPrompt(tr('New recovery codes'), {text: tr('The old codes stop working.')}); if (!pw) return;
        const r = await api('POST', '/api/me/2fa/recovery', {password: pw.password});
        await rcModal(r.recovery_codes); await tfaDraw(md, r);
      }
      if (a === 'pk-add') {
        const pw = await pwPrompt(tr('Add a passkey')); if (!pw) return;
        const o = await api('POST', '/api/me/passkeys/options', {password: pw.password});
        let cred;
        try { cred = await pkCreate(o); } catch (x) { toast(pkErr(x)); return; }
        const name = ((await askPrompt(tr('Name of this passkey'), pkDefaultName(), {ok: tr('Save')})) || '').trim() || pkDefaultName();
        const r = await api('POST', '/api/me/passkeys', {credential: cred, name});
        toast(tr('Passkey added'));
        if (r.recovery_codes) await rcModal(r.recovery_codes);
        await tfaDraw(md, r); await refreshMe();
      }
      if (a === 'pk-ren') {
        const p = (j.passkeys || []).find(x => x.id === pid); if (!p) return;
        const n = ((await askPrompt(tr('Name of this passkey'), p.name, {ok: tr('Rename')})) || '').trim(); if (!n || n === p.name) return;
        await tfaDraw(md, await api('PATCH', '/api/me/passkeys/' + pid, {name: n}));
      }
      if (a === 'pk-del') {
        const p = (j.passkeys || []).find(x => x.id === pid); if (!p) return;
        const pw = await pwPrompt(tr('Remove the passkey “{0}”?', p.name)); if (!pw) return;
        await tfaDraw(md, await api('DELETE', '/api/me/passkeys/' + pid, {password: pw.password})); toast(tr('Passkey removed')); await refreshMe();
      }
    } catch { /* api() showed it */ } finally { b.disabled = false; }
  });
}
function bkRestore(md, src) {
  // src: {name} or {upload}, plus created_at, encrypted, counts, attachment_files
  return new Promise(done => {
    const m = modal(`<h3>${tr('Restore backup')}</h3>
      <p>${tr('This replaces <b>all data on this server</b> (every user’s lists, tasks, files and settings) with the state of {0}.', `<b>${esc(aaWhen(src.created_at) || '?')}</b>`)}</p>
      <p class="muted">${trn('{0} task', '{0} tasks', src.counts?.tasks || 0)}, ${trn('{0} file', '{0} files', src.attachment_files || 0)}, ${trn('{0} user', '{0} users', src.counts?.users || 0)}. ${tr('A safety backup of the current state is made first. Everyone else is logged out.')}</p>
      <form class="pwform">${src.encrypted ? `<input type="password" id="bkr-pass" autocomplete="off" data-1p-ignore data-lpignore="true" data-bwignore placeholder="${tr('Passphrase (empty = the saved one)')}">` : ''}
      <label for="bkr-word">${tr('Type {0} to confirm', '<b>' + esc(src.word) + '</b>')}</label><input id="bkr-word" autocomplete="off" autocapitalize="characters" spellcheck="false">
      <div class="aerr" role="alert" id="bkr-err"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn danger" type="submit" id="bkr-go" disabled>${tr('Restore')}</button></div></form>`);
    m.classList.add('bkrestore');
    m.addEventListener('input', () => { $('#bkr-go', m).disabled = $('#bkr-word', m).value.trim() !== src.word; });
    m.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) { m.remove(); done(false); } });
    m.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      const go = $('#bkr-go', m); go.disabled = true; go.textContent = tr('Restoring…');
      try {
        const r = await rawFetch('POST', '/api/admin/backups/restore', {...(src.upload ? {upload: src.upload} : {name: src.name}), confirm: $('#bkr-word', m).value.trim(), passphrase: $('#bkr-pass', m)?.value || ''});
        m.remove(); md.remove();
        toast(tr('Backup restored. Safety backup: {0}', r.safety));
        clearLocal();
        setTimeout(() => location.replace('/'), 1200);
        done(true);
      } catch (x) { $('#bkr-err', m).textContent = x.message; go.disabled = false; go.textContent = tr('Restore'); }
    });
    setTimeout(() => $('#bkr-pass', m)?.focus() || $('#bkr-word', m)?.focus(), 50);
  });
}
function bkWire(md) {
  md.addEventListener('change', async e => {  // settings saved at once (U03)
    if (!e.target.closest('#s-bk') || e.target.id === 'bk-file') return;
    if (e.target.id === 'bk-pass') {
      const pw = e.target.value; if (!pw || e.target.readOnly) return;
      try { await bkDraw(md, await api('PATCH', '/api/admin/backups', {...bkBody(md), passphrase: pw})); } catch { return; }
      setSaved(null); return;
    }
    const box = $('#s-bk', md), from = box._body, to = bkBody(md);
    if (!to || JSON.stringify(from) === JSON.stringify(to)) return;
    try { await api('PATCH', '/api/admin/backups', to); } catch { await bkDraw(md); return; }
    box._body = to;
    const put = v => async () => { const j = await api('PATCH', '/api/admin/backups', v); const m = $('.smodal'); if (m) await bkDraw(m, j); return {skipped: []}; };
    setSaved(histAdd({label: tr('Changed setting: {0}', tr('Backups')), sett: true, undo: put(from), redo: put(to)}));
  });
  md.addEventListener('change', async e => {
    if (e.target.id !== 'bk-file') return;
    const f = e.target.files[0]; if (!f) return;
    const j = $('#s-bk', md)?._j || {};
    toast(tr('Uploading and checking…'));
    try {
      const r = await fetch('/api/admin/backups/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream'}, body: f});
      const res = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(res.error || tr('Error {0}', r.status));
      await bkRestore(md, {...res, word: j.confirm_word || 'RESTORE'});
    } catch (x) { toast(x.message); }
    e.target.value = '';
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-bk]'); if (!b) return;
    const box = $('#s-bk', md), j = box?._j || {}, name = b.closest('[data-bkn]')?.dataset.bkn, item = (j.items || []).find(x => x.name === name);
    b.disabled = true;
    try {
      if (b.dataset.bk === 'now') { await bkDraw(md, await api('POST', '/api/admin/backups')); toast(tr('Backup started')); }
      if (b.dataset.bk === 'del' && item) { if (!await askConfirm(tr('Delete the backup of {0}?', aaWhen(item.created_at)), tr('The file is removed from the server.'), {ok: tr('Delete'), danger: true})) return; await bkDraw(md, await api('DELETE', '/api/admin/backups/' + encodeURIComponent(name))); }
      if (b.dataset.bk === 'verify' && item) {
        const pass = item.encrypted && !j.passphrase_set ? await askPrompt(tr('Passphrase of this backup'), '', {input: {type: 'password'}}) : '';
        if (pass === null) return;
        const r = await api('POST', `/api/admin/backups/${encodeURIComponent(name)}/verify`, {passphrase: pass || ''});
        toast(tr('Backup is complete and readable ({0}, {1}).', trn('{0} task', '{0} tasks', r.counts?.tasks || 0), trn('{0} file', '{0} files', r.attachment_files || 0)));
      }
      if (b.dataset.bk === 'restore' && item) await bkRestore(md, {name, encrypted: item.encrypted, created_at: item.created_at, counts: item.counts, attachment_files: item.attachment_files, word: j.confirm_word || 'RESTORE'});
    } catch { /* api() showed it */ } finally { b.disabled = false; }
  });
}
// every module a purpose switches (on or off); the rest (agents, clients …) stays as it is (server: PURPOSE_MODS)
const PURPOSE_ALL = ['cal', 'timeline', 'matrix', 'kanban', 'habits', 'pomo', 'stats', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'family', 'events', 'contacts', 'contracts', 'home', 'care', 'health', 'review', 'travel', 'reading'];
// the admin just created the second user while collaboration is off for the server: offer to turn it on
async function offerCollab() {
  if (S.collabAll !== false || !S.me?.is_admin) return;
  let n = 0;
  try { n = (await api('GET', '/api/users')).users.filter(u => !u.disabled).length; } catch { return; }
  if (n !== 2) return;
  const md = modal(`<h3>${tr('Turn on collaboration now?')}</h3><p class="muted">${tr('Sharing lists, assigning tasks, comments and News, for both of you. You can change it any time under Settings > Modules.')}</p>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="no">${tr('Not now')}</button><button class="btn pri" data-m="yes">${tr('Yes, turn on')}</button></div>`);
  md.classList.add('collabask');
  await new Promise(done => md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'yes') {
      try { const j = await api('PATCH', '/api/admin/settings', {collab_all: true, collab_personal_on: true}); if (j && j.version) S.about = j; S.collabAll = true; toast(tr('Collaboration is on for everyone')); } catch { /* api() showed it */ }
    }
    md.remove(); done();
  }));
}
// ---- 1.8.0: sample project "Example: Image film for client Muster" + a packing checklist (built on the server, in the
// user's language, only with the modules that are on). Offered in the setup and the welcome tour, created / removed
// under Settings > Data (and the command palette). Removing takes exactly what the sample created: tasks the user
// added stay, and so does their list.
const sampleDefault = () => depsOn() || fieldsOn() || timeOn() || progressOn();  // "Projects & team"-like setups
const sampleRowHtml = () => S.sample ? `<label>${tr('Sample')}</label><button class="btn sm danger" data-m="sample-rm">${ic('trash', 's')} ${tr('Remove sample project')}</button><span class="muted" style="font-size:var(--fs-s)">${esc(S.sample.lists.map(l => l.name).join(', '))}</span>`
  : `<label>${tr('Sample')}</label><button class="btn sm" data-m="sample-add">${ic('plus', 's')} ${tr('Create sample project')}</button>`;
const sampleHtml = hint => `<h4 id="s-sample-h">${tr('Sample project')}</h4>
      ${hint(tr('An example video production with sections, dates, dependencies and a packing checklist: a quick way to see how projects work. Private to you, without reminders.'))}
      <div class="row" id="s-sample">${sampleRowHtml()}</div>`;
// ---- 2.88.0 (#1980): the user management for hundreds of accounts -- search (after a short pause in typing), filter,
// pages of 50, several accounts at once (disable / enable / add to an organisation) and deleting an account that owns lists
function ua8_wire(md, us, draw) {
  let tq = 0;
  md.addEventListener('input', e => {
    if (e.target.id !== 'a-uq') return;
    clearTimeout(tq); tq = setTimeout(() => { us.q = e.target.value.trim(); us.off = 0; draw(); }, 300);
  });
  md.addEventListener('change', async e => {
    const t = e.target;
    if (t.id === 'a-uflt') { us.flt = t.value; us.off = 0; draw(); return; }
    if (t.dataset?.usel) { const id = +t.dataset.usel; t.checked ? us.sel.add(id) : us.sel.delete(id); ua8_selDraw(md, us); return; }
    if (t.id === 'a-uborg' && +t.value) {
      const o = (S.orgs || []).find(x => x.id === +t.value); t.value = '';
      if (o && await askConfirm(trn('Add {0} person to “{1}”?', 'Add {0} people to “{1}”?', us.sel.size, o.name), tr('They become members of the organisation; their other organisations stay.'), {ok: tr('Add')})) await ua8_bulk(md, us, draw, 'org_add', o.id);
    }
  });
  md.addEventListener('click', async e => {
    const p = e.target.closest('[data-upg]');
    if (p) { us.off = Math.max(0, us.off + (+p.dataset.upg) * UA8_PAGE); draw(); $('#a-uq', md)?.scrollIntoView({block: 'nearest'}); return; }
    const b = e.target.closest('[data-ubulk]'); if (!b) return;
    if (b.dataset.ubulk === 'clear') { us.sel.clear(); $$('[data-usel]', md).forEach(x => { x.checked = false; }); ua8_selDraw(md, us); return; }
    if (b.dataset.ubulk === 'disable' && !await askConfirm(trn('Disable {0} account?', 'Disable {0} accounts?', us.sel.size), tr('They are logged out and cannot log in until enabled again. Nothing is deleted.'), {ok: tr('Disable'), danger: true})) return;
    await ua8_bulk(md, us, draw, b.dataset.ubulk);
  });
}
function ua8_pagerDraw(md, us) {
  const box = $('#a-upg', md); if (!box) return;
  const to = Math.min(us.total, us.off + UA8_PAGE);
  box.innerHTML = us.total > UA8_PAGE ? `<button type="button" class="iconbtn" data-upg="-1" aria-label="${esc(tr('Previous page'))}" title="${esc(tr('Previous page'))}" ${us.off ? '' : 'disabled'}>${ic('left', 's')}</button><span class="muted">${esc(tr('{0}–{1} of {2}', us.off + 1, to, us.total))}</span><button type="button" class="iconbtn" data-upg="1" aria-label="${esc(tr('Next page'))}" title="${esc(tr('Next page'))}" ${to < us.total ? '' : 'disabled'}>${ic('right', 's')}</button>`
    : us.total > 1 ? `<span class="muted">${esc(trn('{0} account', '{0} accounts', us.total))}</span>` : '';
}
function ua8_selDraw(md, us) {
  const box = $('#a-usel', md); if (!box) return;
  box.hidden = !us.sel.size;
  if (!us.sel.size) { box.innerHTML = ''; return; }
  const os = S.instanceMode === 'workspaces' ? (S.orgs || []) : [];
  box.innerHTML = `<span class="n">${esc(tr('{0} selected', us.sel.size))}</span><button type="button" class="btn sm" data-ubulk="disable">${tr('Disable')}</button><button type="button" class="btn sm" data-ubulk="enable">${tr('Enable')}</button>`
    + (os.length ? `<select id="a-uborg" aria-label="${esc(tr('Add to an organisation'))}"><option value="0">${tr('Add to an organisation …')}</option>${os.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('')}</select>` : '')
    + `<button type="button" class="linkbtn" data-ubulk="clear">${tr('Clear selection')}</button>`;
}
async function ua8_bulk(md, us, draw, action, orgId) {
  const ids = [...us.sel];
  let j; try { j = await api('POST', '/api/users/bulk', {ids, action, ...(orgId ? {org_id: orgId} : {})}); } catch { return; }
  us.sel.clear(); await draw();
  const msg = j.failed.length ? tr('{0} changed, {1} not: {2}', j.ok.length, j.failed.length, j.failed[0].error) : tr('{0} changed', j.ok.length);
  if (action === 'org_add' || !j.ok.length) { toast(msg); return; }
  const back = action === 'disable' ? 'enable' : 'disable', ok = j.ok;  // one undo step: the same accounts back
  offerUndo(msg, histAdd({label: tr('Users'),
    undo: async () => { await api('POST', '/api/users/bulk', {ids: ok, action: back}); if (md.isConnected) draw(); return {skipped: []}; },
    redo: async () => { await api('POST', '/api/users/bulk', {ids: ok, action}); if (md.isConnected) draw(); return {skipped: []}; }}));
}
// Deleting an account (instance admin, or an organisation admin for an account of their organisation alone): without lists
// the short question as before; with lists the dialog names them (as far as the admin may see them) and asks: hand them all
// to one person (the default) or delete them along (the user name typed to confirm). Resolves true when the account went
// (or, for an organisation admin who may not delete it, left the organisation).
async function ua8_delete(u) {
  let j; try { j = await api('GET', `/api/users/${u.id}/delete-info`); } catch { return false; }
  const name = u.display_name || u.name || '';
  if (!j.can_delete) return ua8_orgRemove(u, name, j);
  if (!j.lists.length) {
    if (!await askConfirm(tr('Delete user “{0}”?', name), tr('Their basket, habits, filters and focus history are deleted.'), {ok: tr('Delete user'), danger: true})) return false;
    try { await api('DELETE', '/api/users/' + u.id); } catch { return false; }
    return true;
  }
  const shared = j.lists.filter(l => l.shared).length, locked = j.lists.some(l => l.locked), cand = j.candidates, foreign = j.lists.some(l => l.foreign);
  const lname = l => l.name != null ? esc(l.name) : esc(l.org ? tr('A list of {0}', l.org) : tr('A private list'));
  const md = modal(`<h3>${esc(tr('Delete user “{0}”?', name))}</h3>
    <div class="shint keep">${esc(trn('{1} still owns {0} list. Choose what happens to it.', '{1} still owns {0} lists. Choose what happens to them.', j.lists.length, name))}</div>
    <div class="members ua8lists">${j.lists.map(l => `<div class="mrow"><span class="n">${l.locked ? ic('lock', 's') + ' ' : ''}${lname(l)} <span class="muted">${l.org && l.name != null ? esc(l.org) + ' · ' : ''}${l.shared ? esc(l.members.length ? tr('shared with {0}', l.members.join(', ') + (l.shared > l.members.length ? ' ' + tr('+{0}', l.shared - l.members.length) : '')) : trn('shared with {0} person', 'shared with {0} people', l.shared)) : esc(tr('not shared'))}</span></span></div>`).join('')}</div>
    <fieldset class="ua8how"><legend>${tr('The lists')}</legend>
      <label class="chkl"><input type="radio" name="ua8how" value="transfer" ${cand.length ? 'checked' : 'disabled'}> ${tr('Hand them over to')}</label>
      <select id="ua8-to" aria-label="${esc(tr('New owner'))}" ${cand.length ? '' : 'disabled'}>${cand.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select>
      ${cand.length ? '' : `<div class="shint keep">${tr('Nobody can take over every one of these lists (an organisation’s list stays in its organisation). Hand single lists over first or delete them along.')}</div>`}
      ${locked ? `<div class="shint keep">${ic('lock', 's')} ${tr('Lists with the lock: the new owner can read them once a member who holds the key opens them.')}</div>` : ''}
      <label class="chkl"><input type="radio" name="ua8how" value="delete" ${foreign ? 'disabled' : cand.length ? '' : 'checked'}> ${tr('Delete them along')}</label>
      ${foreign ? `<div class="shint keep">${tr('Lists of an organisation you do not belong to cannot be deleted along: hand them over instead.')}</div>` : ''}
      <div id="ua8-del" ${cand.length || foreign ? 'hidden' : ''}>
        ${shared ? `<div class="shint keep warn">${ic('alert', 's')} ${esc(trn('{0} of these lists is shared: the other people lose it too.', '{0} of these lists are shared: the other people lose them too.', shared))}</div>` : ''}
        <div class="row"><label for="ua8-conf">${esc(tr('Type {0} to confirm', j.username))}</label><input id="ua8-conf" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
      </div>
    </fieldset>
    <div class="shint">${tr('Invoices and filed documents do not belong to a list: they stay.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn danger" data-m="go">${tr('Delete user')}</button></div>`);
  const how = () => $('[name="ua8how"]:checked', md)?.value;
  const sync = () => { $('#ua8-del', md).hidden = how() !== 'delete'; $('#ua8-to', md).disabled = how() !== 'transfer'; $('[data-m="go"]', md).disabled = how() === 'delete' ? $('#ua8-conf', md).value.trim() !== j.username : !how(); };
  md.addEventListener('change', sync); md.addEventListener('input', sync); sync();
  return new Promise(res => {
    onRemove(md, () => res(false));
    md.addEventListener('click', async e => {
      const b = e.target.closest('button[data-m]'); if (!b) return;
      if (b.dataset.m === 'close') { md.remove(); return; }
      const q = how() === 'transfer' ? `lists=transfer&to=${+$('#ua8-to', md).value}` : `lists=delete&confirm=${encodeURIComponent($('#ua8-conf', md).value.trim())}`;
      b.disabled = true;
      try { await api('DELETE', `/api/users/${u.id}?${q}`); } catch { b.disabled = false; return; }
      res(true); md.remove();
    });
  });
}
// an organisation admin and an account they may not delete (another organisation too, a server admin, private lists): only
// "Remove from the organisation", its lists of the organisation going to the member chosen here
async function ua8_orgRemove(u, name, j) {
  if (!j.org_id) { toast(j.reason); return false; }
  const md = modal(`<h3>${esc(tr('Delete user “{0}”?', name))}</h3><div class="shint keep">${esc(j.reason)}</div>
    <div class="row"><label for="ua8-heir">${tr('Lists of the organisation go to')}</label><select id="ua8-heir">${[{id: S.me.id, name: tr('Me')}, ...j.heirs.filter(p => p.id !== S.me.id)].map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn danger" data-m="go">${tr('Remove from the organisation')}</button></div>`);
  return new Promise(res => {
    onRemove(md, () => res(false));
    md.addEventListener('click', async e => {
      const b = e.target.closest('button[data-m]'); if (!b) return;
      if (b.dataset.m === 'close') { md.remove(); return; }
      const to = +$('#ua8-heir', md).value;
      try { await api('DELETE', `/api/orgs/${j.org_id}/members/${u.id}${to !== S.me.id ? '?to=' + to : ''}`); } catch { return; }
      toast(tr('Removed')); res('removed'); md.remove();
    });
  });
}
