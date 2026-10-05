/* Kalmido web client: Account, users (admin), login, groups, passkeys, two-factor, sign-in policy, backups, the sample project.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ account, users (admin), login
// settings sections: own account (name, password, upload token, log out) + user admin for admins
// 1.9.0: profile picture in Settings > Account: a preset picture, an own photo (cropped square here, resized on the server)
// or none (initials). Shown wherever the initials were: sidebar, assignees, comments, News, members.
const AV_PRESETS = [['coffee', N_('Coffee')], ['headphones', N_('Headphones')], ['camera', N_('Camera')], ['sleepy', N_('Sleepy')], ['laptop', N_('Laptop')],
  ['plant', N_('Plant')], ['robot', N_('Robot')], ['shades', N_('Sunglasses')], ['party', N_('Party')], ['glasses', N_('Reading')]];
function avPickHtml(cur = S.me?.avatar || '', own = true, name = S.me?.display_name) {
  return AV_PRESETS.map(([k, n]) => `<button type="button" class="avopt ${cur === `/static/avatars/${k}.svg` ? 'on' : ''}" data-av="${k}" title="${esc(tr(n))}" aria-label="${esc(tr(n))}" aria-pressed="${cur === `/static/avatars/${k}.svg`}"><img src="/static/avatars/${k}.svg" alt=""></button>`).join('') +
    (own ? `<button type="button" class="avopt up ${cur.startsWith('/api/avatar/') ? 'on' : ''}" data-av="upload" title="${esc(tr('Upload a photo…'))}" aria-label="${esc(tr('Upload a photo…'))}">${cur.startsWith('/api/avatar/') ? `<img src="${esc(cur)}" alt="">` : ic('plus')}</button>` : '') +
    `<button type="button" class="avopt none ${cur ? '' : 'on'}" data-av="none" title="${esc(tr('No picture (initials)'))}" aria-label="${esc(tr('No picture (initials)'))}" aria-pressed="${!cur}">${esc(initials(name))}</button>`;
}
async function avSet(j) {
  S.me.avatar = j.avatar || '';
  if (j.avatar) (S.avatars ||= {})[S.me.id] = j.avatar; else if (S.avatars) delete S.avatars[S.me.id];
  const box = $('#a-avpick'); if (box) box.innerHTML = avPickHtml();
  const acct = $('.acct'); if (acct) acct.firstElementChild.outerHTML = av(S.me.id, S.me.display_name);
  render();
}
// photo: square crop (drag to move, slider to zoom), sent as a 512 px JPEG; the server re-encodes it anyway
function avCropModal(file, opt = {}) {
  return new Promise(res => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onerror = () => { URL.revokeObjectURL(url); toast(tr('This picture cannot be read')); res(null); };
    img.onload = () => {
      const md = modal(`<h3>${esc(opt.title || tr('Profile picture'))}</h3><div class="avcrop"><canvas width="256" height="256" id="av-cv" aria-label="${esc(tr('Drag to move the picture'))}"></canvas></div>
        <div class="row"><label for="av-zoom">${tr('Zoom')}</label><input type="range" id="av-zoom" min="1" max="4" step="0.01" value="1"></div>
        <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Use picture')}</button></div>`);
      const cv = $('#av-cv', md), cx = cv.getContext('2d'), side = Math.min(img.width, img.height);
      let z = 1, ox = (img.width - side) / 2, oy = (img.height - side) / 2, drag = null;
      const clamp = () => { const s = side / z; ox = Math.max(0, Math.min(img.width - s, ox)); oy = Math.max(0, Math.min(img.height - s, oy)); };
      const draw = (c = cx, px = 256) => { const s = side / z; clamp(); if (opt.png) c.clearRect(0, 0, px, px); else { c.fillStyle = '#fff'; c.fillRect(0, 0, px, px); } c.drawImage(img, ox, oy, s, s, 0, 0, px, px); };
      draw();
      cv.addEventListener('pointerdown', e => { drag = {x: e.clientX, y: e.clientY, ox, oy}; cv.setPointerCapture?.(e.pointerId); });
      cv.addEventListener('pointermove', e => { if (!drag) return; const k = side / z / cv.getBoundingClientRect().width; ox = drag.ox - (e.clientX - drag.x) * k; oy = drag.oy - (e.clientY - drag.y) * k; draw(); });
      cv.addEventListener('pointerup', () => { drag = null; });
      $('#av-zoom', md).addEventListener('input', e => { const s0 = side / z, cxm = ox + s0 / 2, cym = oy + s0 / 2; z = +e.target.value; const s1 = side / z; ox = cxm - s1 / 2; oy = cym - s1 / 2; draw(); });
      const done = v => { URL.revokeObjectURL(url); if (md.isConnected) md.remove(); res(v); };
      onRemove(md, () => done(null));
      md.addEventListener('click', e => {
        const b = e.target.closest('button[data-m]'); if (!b) return;
        if (b.dataset.m === 'close') { done(null); return; }
        const out = document.createElement('canvas'); out.width = out.height = 512; draw(out.getContext('2d'), 512);
        out.toBlob(bl => done(bl), opt.png ? 'image/png' : 'image/jpeg', 0.9);
      });
    };
    img.src = url;
  });
}
async function avUpload(url = '/api/me/avatar', done = avSet) {  // 2.1.2 (#346): also an agent's picture (admins)
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
  inp.addEventListener('change', async () => {
    const f = inp.files?.[0]; if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
    const bl = await avCropModal(f); if (!bl) return;
    const fd = new FormData(); fd.append('file', bl, 'avatar.jpg');
    try { done(await api('POST', url, fd)); toast(tr('Profile picture saved')); } catch { /* api() showed it */ }
  });
  inp.click();
}
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
    ${hint(tr('Send photos, files, links and text from any app to your inbox: each share becomes a task, files are attached. Works on the go too, as long as the phone reaches Kalmido.'))}
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
    <div class="row"><label for="s-droptok">${tr('Upload token')}</label><input id="s-droptok" readonly type="password" value="••••••••••••" autocomplete="off"><button class="btn sm" data-m="drop-copy-tok">${ic('copy', 's')} ${tr('Copy')}</button><button class="btn sm" data-m="drop-new-tok" title="${esc(tr('The old token stops working'))}">${ic('key', 's')} ${tr('New token')}</button></div>
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
  ['unblock', N_('A task I wait on was completed')], ['share', N_('Lists shared with me')], ['status', N_('Project status changes')], ['complete', N_('Others completed my tasks')]];
const NOTIF_ROWS = [
  ['comment', N_('Comments on my tasks'), N_('tasks I created or am assigned to')],
  ['reply', N_('Replies to my comment'), N_('someone comments right after me')],
  ['follow', N_('Comments on tasks I follow'), N_('tasks I commented on')],
  ['mention', N_('Mentions of me')],
  ['assign', N_('Tasks assigned to me (or taken away)')],
  ['newtask', N_('New tasks in shared lists'), N_('created by someone else')],
  ['complete', N_('Others completed my tasks')],
  ['status', N_('Project status changes')],
  ['share', N_('Lists shared with me')],
  ['unblock', N_('A task I wait on was completed'), '', 'deps'],
  ['approval', N_('An agent waits for my approval'), '', 'agents'],
  ['followup', N_('Follow-up day of a task waiting on external')],
  ['reminder', N_('Reminders'), N_('due dates of my tasks')],
  ['nag', N_('Repeated reminders'), N_('until the task is done; not during your quiet hours')],  // 2.7.0 (#413)
  ['usage', N_('An agent reached a usage limit'), N_('admins: 80 % and 100 % of a limit'), 'admin'],  // 2.1.1 (#326)
  ['proposal', N_('A proposal I asked an agent for is ready'), '', 'propose'],  // 2.3.0: only with an agent I may ask
  ['chat', N_('Team chat'), N_('direct messages; in channels only when you are mentioned (or the list bell is “All”)')],  // 2.17.0 (#419)
  ['errreport', N_('New error reports'), N_('a new error from a project list’s error-report webhook became a ticket (repeats stay quiet)')]];  // 2.18.0
const NM_GROUP = {comment: 'comment', reply: 'comment', follow: 'comment', mention: 'mention', assign: 'assign', complete: 'complete', status: 'status', share: 'share', unblock: 'unblock'};
const NM_PRIMARY = ['comment', 'mention', 'assign', 'complete', 'status', 'share', 'unblock'];
const NM_NEWS_NEW = {newtask: 0, approval: 0, followup: 1, usage: 1, proposal: 1, errreport: 1};
const NM_PUSH = {comment: 1, reply: 1, follow: 1, mention: 1, assign: 1, newtask: 0, complete: 1, status: 0, share: 0, unblock: 1, approval: 1, followup: 1, reminder: 1, usage: 1, proposal: 1, nag: 1, chat: 1, errreport: 1};
const NM_SOCIAL = ['comment', 'reply', 'follow', 'mention', 'assign', 'newtask', 'complete', 'status', 'share', 'unblock', 'approval', 'proposal', 'chat', 'errreport'];
const nmStored = s => { try { const o = JSON.parse(s.notify || '{}'); return o && typeof o === 'object' ? o : {}; } catch { return {}; } };
function notifMatrix(s) {
  const nk = new Set(String(s.news_kinds ?? 'mention,assign,comment,unblock,share,status').split(',')), o = nmStored(s), out = {};
  for (const [r] of NOTIF_ROWS) {
    const x = o[r] && typeof o[r] === 'object' ? o[r] : {};
    const news = r === 'reminder' || r === 'nag' || r === 'chat' ? null : NM_PRIMARY.includes(r) ? nk.has(NM_GROUP[r]) : 'news' in x ? !!x.news : r in NM_GROUP ? nk.has(NM_GROUP[r]) : !!NM_NEWS_NEW[r];
    out[r] = {news, push: 'push' in x ? !!x.push : !!NM_PUSH[r]};
  }
  return out;
}
// one checkbox -> the two stored values {notify, news_kinds}
function notifPatch(s, row, ch, on) {
  const o = nmStored(s);
  let nk = String(s.news_kinds ?? 'mention,assign,comment,unblock,share,status').split(',').filter(Boolean);
  if (ch === 'news' && NM_PRIMARY.includes(row)) nk = on ? [...new Set([...nk, NM_GROUP[row]])] : nk.filter(k => k !== NM_GROUP[row]);
  else { o[row] = {...(o[row] || {}), [ch]: on ? 1 : 0}; }
  const sorted = Object.keys(o).sort().reduce((a, k) => { a[k] = Object.keys(o[k]).sort().reduce((b, j) => { b[j] = o[k][j]; return b; }, {}); return a; }, {});
  return {notify: JSON.stringify(sorted), news_kinds: NEWS_KINDS.map(x => x[0]).filter(k => nk.includes(k)).join(',')};
}
function notifMatrixHtml(s, hint) {
  const m = notifMatrix(s), social = collab();
  const rows = NOTIF_ROWS.filter(([r, , , f]) => (social || !NM_SOCIAL.includes(r)) && (!f || (f === 'deps' ? depsOn() : f === 'admin' ? !!S.me?.is_admin : f === 'propose' ? propOn() : feat('agents'))));
  const box = (r, ch, lab) => m[r][ch] === null ? `<span class="nmna" aria-label="${esc(tr('not available'))}">–</span>`
    : `<label class="nmhit"><input type="checkbox" data-nm="${r}" data-ch="${ch}" ${m[r][ch] ? 'checked' : ''} aria-label="${esc(tr(lab) + ': ' + (ch === 'news' ? tr('News') : tr('Push')))}"></label>`;  // 2.13.0: a 44 px hit area
  return `<h4 id="s-news-h">${tr('What notifies you')}</h4>
    ${hint(tr('News = under the bell in the app, Push = a notification on your devices. Your own actions never notify you. Each list can override this with its bell (list menu > Notifications).'))}
    <div class="nmx" role="table" aria-labelledby="s-news-h"><div class="nmh" role="row"><span role="columnheader">${tr('Event')}</span><span role="columnheader">${tr('News')}</span><span role="columnheader">${tr('Push')}</span></div>
    ${rows.map(([r, n, d]) => `<div class="nmr" role="row"><span class="nml" role="cell">${tr(n)}${d ? `<small>${tr(d)}</small>` : ''}</span><span role="cell">${social ? box(r, 'news', n) : '<span class="nmna">–</span>'}</span><span role="cell">${box(r, 'push', n)}</span></div>`).join('')}</div>`;
}
function accountHtml() {
  const m = S.me, pw = m.auth === 'session' || m.has_password;
  return `<h4 id="s-account-h">${tr('Account')}</h4>
    <div class="row"><label>${tr('Logged in as')}</label><span class="acct">${av(m.id, m.display_name)}<b>${esc(m.display_name)}</b> <span class="muted">${esc(m.username)}${m.auth === 'proxy' ? ' · ' + tr('via single sign-on') : ''}</span></span></div>
    <div class="row"><label for="a-name">${tr('Display name')}</label><input id="a-name" value="${esc(m.display_name)}" maxlength="60" autocomplete="name" enterkeyhint="done"></div>
    <div class="row avrow"><label>${tr('Profile picture')}</label><div class="avpick" id="a-avpick">${avPickHtml()}</div></div>
    ${pw ? `<div class="row"><label for="a-cur">${tr('Password')}</label><input type="password" id="a-cur" placeholder="${tr('current password')}" autocomplete="current-password"><input type="password" id="a-new" placeholder="${tr('new password')}" autocomplete="new-password"><button class="btn sm" data-acc="pw">${tr('Change')}</button></div>` : ''}
    ${m.auth === 'session' ? `<div class="row"><label></label><button class="btn sm" data-acc="logout">${ic('logout', 's')} ${tr('Log out')}</button></div>` : ''}
    ${tfaHtml()}
    ${apwHtml()}
    <details class="sdev"><summary>${ic('key', 's')}${tr('Advanced · for developers')}</summary>
    <div class="row"><label>${tr('Upload token')}</label><button class="btn sm" data-m="go-share">${ic('phone', 's')} ${tr('Share from your phone')}</button><span class="muted" style="font-size:var(--fs-s)">${tr('shown and renewed there')}</span></div>
    ${apiHtml()}</details>`;
}
const usersHtml = () => `<h4>${tr('Users')}</h4><div class="members" id="a-users"><div class="muted mhint">${tr('Loading…')}</div></div>
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
  box.innerHTML = gs.length ? gs.map(g => `<div class="mrow" data-grow="${g.id}"><span class="avatar gav">${ic('users', 's')}</span><span class="n">${esc(g.name)} <span class="muted">${g.members.length ? esc(g.members.map(m => m.name).join(', ')) : tr('no members yet')}${g.synced ? ' · ' + esc(tr('sign-in group {0}', g.oidc_group)) : ''}</span></span><button class="iconbtn" data-grp="edit" data-gid="${g.id}" title="${esc(tr('Edit group'))}" aria-label="${esc(tr('Edit group {0}', g.name))}">${ic('edit', 's')}</button></div>`).join('')
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
    <div class="row"><label for="gr-oidc">${tr('Sign-in group')}</label><input id="gr-oidc" maxlength="200" value="${esc(g?.oidc_group || '')}" placeholder="${esc(tr('optional · OIDC group name'))}"></div>
    <div class="shint">${tr('With a sign-in group the members come from the sign-in provider (OIDC): whoever has that group in their login is a member, checked at every login.')}</div>
    <h4 id="gr-mem-h">${tr('Members')}</h4>
    <div class="grpmem" id="gr-mem" role="group" aria-labelledby="gr-mem-h">${users.map(u => `<label class="chkl"><input type="checkbox" data-gm="${u.id}" ${sel.has(u.id) ? 'checked' : ''} ${synced ? 'disabled' : ''}> ${esc(u.display_name)} <span class="muted">${esc(u.username)}</span></label>`).join('') || `<div class="muted mhint">${tr('No other users yet. An admin can add them in the settings.')}</div>`}</div>
    <div class="calerr" role="alert" id="gr-err" hidden></div>
    <div class="foot">${g ? `<button class="btn danger" data-m="del">${ic('trash', 's')} ${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${g ? tr('Save') : tr('Create')}</button></div>`);
  md.classList.add('grpmodal');
  const syncMem = () => { const on = !!$('#gr-oidc', md).value.trim(); $$('[data-gm]', md).forEach(x => { x.disabled = on; }); };
  $('#gr-oidc', md).addEventListener('input', syncMem);
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
    try { await calReq(g ? 'PATCH' : 'POST', g ? `/api/admin/groups/${gid}` : '/api/admin/groups', q); } catch (x) { err.textContent = x.message; err.hidden = false; b.disabled = false; return; }
    md.remove(); await load().catch(() => {}); render(); grpDraw(smd); toast(g ? tr('Group saved') : tr('Group created'));
  });
  if (!isTouch()) setTimeout(() => $('#gr-name', md)?.focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
// the "Groups" part of the share dialog of a list: shared directly (role + remove) or through a folder (read-only here)
function shareGroupsHtml(cur, mng, roleSel) {
  const gs = cur.groups || [], cand = (S.groups || []).filter(g => !gs.some(x => x.group_id === g.id && x.via === 'list'));
  if (!gs.length && !(mng && cand.length)) return '';
  return gs.map(x => `<div class="mrow" data-gsh="${x.group_id}"><span class="avatar gav">${ic('users', 's')}</span><span class="n">${esc(x.name)}${x.via !== 'list' ? ` <span class="muted">${esc(tr('via the folder {0}', fDisp(x.via)))}</span>` : ''}</span>${mng && x.via === 'list'
    ? `${roleSel(`data-grole="${x.group_id}"`, x.role, tr('Role of the group {0}', x.name))}<button class="iconbtn" data-grm="${x.group_id}" title="${esc(tr('Stop sharing with the group'))}" aria-label="${esc(tr('Stop sharing with the group {0}', x.name))}">${ic('x', 's')}</button>`
    : `<span class="muted" title="${esc(roleHelp(x.role))}">${esc(roleLabel(x.role))}</span>`}</div>`).join('')
    + (mng && cand.length ? `<div class="mrow madd"><select id="l-addgrp" aria-label="${esc(tr('Share with a group'))}"><option value="">${tr('Share with a group …')}</option>${cand.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join('')}</select>${roleSel('id="l-grprole"', 'edit')}<button class="btn sm" data-m="share-grp">${ic('plus', 's')} ${tr('Add')}</button></div>` : '');
}
// folder menu "Share with a group…": every own list in the folder (and its subfolders, also later ones)
async function folderGroupsModal(f) {
  if (!collab() || !(S.groups || []).length) { toast(tr('An admin creates groups in Settings > Administration')); return; }
  const md = modal(`<div class="lhdr"><h3>${esc(tr('Share the folder “{0}”', fDisp(f)))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="shint">${tr('Every list of yours in this folder and its subfolders is shared with the group, also lists you put there later. A list taken out of the folder is no longer shared through it.')}</div>
    <div class="members" id="fg-list"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('shmodal');
  const roleSel = (attr, cur_, lab) => `<select ${attr} aria-label="${esc(lab || tr('Role'))}">${ROLES.map(([v, n, h]) => `<option value="${v}" title="${esc(tr(h))}" ${v === cur_ ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>`;
  const draw = async () => {
    let gs; try { gs = (await calReq('GET', '/api/folders/groups?folder=' + encodeURIComponent(f))).groups; } catch { return; }
    if (!md.isConnected) return;
    const cand = (S.groups || []).filter(g => !gs.some(x => x.group_id === g.id));
    $('#fg-list', md).innerHTML = gs.map(x => `<div class="mrow"><span class="avatar gav">${ic('users', 's')}</span><span class="n">${esc(x.name)}</span>${roleSel(`data-fgrole="${x.group_id}"`, x.role, tr('Role of the group {0}', x.name))}<button class="iconbtn" data-fgrm="${x.group_id}" title="${esc(tr('Stop sharing with the group'))}" aria-label="${esc(tr('Stop sharing with the group {0}', x.name))}">${ic('x', 's')}</button></div>`).join('')
      + (cand.length ? `<div class="mrow madd"><select id="fg-add" aria-label="${esc(tr('Share with a group'))}"><option value="">${tr('Share with a group …')}</option>${cand.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join('')}</select>${roleSel('id="fg-role"', 'edit')}<button class="btn sm" data-m="fg-add">${ic('plus', 's')} ${tr('Add')}</button></div>` : '')
      || `<div class="muted mhint">${tr('No groups yet')}</div>`;
  };
  const act = async fn => { try { await fn(); await load(); render(); draw(); } catch { /* api() showed it */ } };
  md.addEventListener('change', e => {
    const r = e.target.closest('[data-fgrole]');
    if (r) act(() => api('PUT', `/api/folders/groups/${r.dataset.fgrole}`, {folder: f, role: r.value}));
  });
  md.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'fg-add') { const g = +$('#fg-add', md).value; if (g) act(() => api('PUT', `/api/folders/groups/${g}`, {folder: f, role: $('#fg-role', md).value})); return; }
    if (b.dataset.fgrm) act(() => api('DELETE', `/api/folders/groups/${b.dataset.fgrm}?folder=${encodeURIComponent(f)}`));
  });
  draw();
}
// 2.22.0 (#752): organisations (admins): name, emoji, members; whom people see (everyone / own organisation / own contacts)
const VIS_UI = [['all', N_('Everyone on this server')], ['org', N_('Only people of their own organisations')], ['contacts', N_('Only people they are connected with (no directory, share by e-mail address)')]];
const orgsHtml = () => `<h4 id="a-orgs-h">${tr('Organisations')}</h4><div class="members" id="a-orgs"><div class="muted mhint">${tr('Loading…')}</div></div>
  <div class="row"><label for="a-vis">${tr('People see')}</label><select id="a-vis"></select></div>
  <div class="shint">${tr('Whom people see in the share dialog, as attendees and in the user list. Admins always see everyone. With several companies or households on one server: own organisation or own contacts.')}</div>
  <div class="row" style="margin-top:.5rem"><button class="btn sm" data-acc="org-new">${ic('plus', 's')} ${tr('New organisation')}</button></div>`;
async function orgsDraw(md) {
  const box = $('#a-orgs', md); if (!box) return;
  let j; try { j = await api('GET', '/api/admin/orgs'); } catch { return; }
  S.orgs = j.orgs;
  box.innerHTML = j.orgs.length ? j.orgs.map(o => `<div class="mrow"><span class="fem" aria-hidden="true">${esc(o.icon || '🏢')}</span><span class="n">${esc(o.name)} <span class="muted">${esc(trn('{0} member', '{0} members', o.members.length))}</span></span><button class="iconbtn" data-acc="org-edit" data-oid="${o.id}" title="${esc(tr('Edit organisation'))}" aria-label="${esc(tr('Edit {0}', o.name))}">${ic('edit', 's')}</button></div>`).join('') : `<div class="muted mhint">${tr('No organisation yet.')}</div>`;
  const vs = $('#a-vis', md); if (vs) vs.innerHTML = VIS_UI.map(([k, n]) => `<option value="${k}" ${k === j.visibility ? 'selected' : ''}>${esc(tr(n))}</option>`).join('');
}
async function orgModal(o, done) {
  let us = []; try { us = (await api('GET', '/api/users')).users.filter(u => !u.disabled); } catch { return; }
  const mem = new Set(o?.members || []);
  const md = modal(`<h3>${o ? tr('Edit organisation') : tr('New organisation')}</h3>
    <div class="row"><label for="og-name">${tr('Name')}</label><input id="og-name" maxlength="60" value="${esc(o?.name || '')}"></div>
    <div class="row"><label for="og-icon">${tr('Symbol')}</label><input id="og-icon" maxlength="8" class="numin" value="${esc(o?.icon || '')}" placeholder="🏢"></div>
    <div class="row"><label>${tr('Members')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Members'))}">${us.map(u => `<button type="button" class="fperson ${mem.has(u.id) ? 'on' : ''}" data-ogm="${u.id}" aria-pressed="${mem.has(u.id)}">${av(u.id, u.display_name)}<span>${esc(u.display_name)}</span></button>`).join('')}</div></div>
    <div class="foot">${o ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const p = e.target.closest('[data-ogm]');
    if (p) { const id = +p.dataset.ogm; mem.has(id) ? mem.delete(id) : mem.add(id); p.classList.toggle('on', mem.has(id)); p.setAttribute('aria-pressed', mem.has(id)); return; }
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      if (b.dataset.m === 'del') { if (!await askConfirm(tr('Delete the organisation “{0}”?', o.name), tr('Its people stay; they are only no longer members.'), {ok: tr('Delete'), danger: true})) return; await api('DELETE', `/api/admin/orgs/${o.id}`); }
      if (b.dataset.m === 'save') { const body = {name: $('#og-name', md).value.trim(), icon: $('#og-icon', md).value.trim(), members: [...mem]}; if (o) await api('PATCH', `/api/admin/orgs/${o.id}`, body); else await api('POST', '/api/admin/orgs', body); }
      md.remove(); done && done(); await load(); render();
    } catch { /* api() said it */ }
  });
}
function accountWire(md) {
  let users = [];
  const drawUsers = async () => {
    const box = $('#a-users', md); if (!box) return;
    try { const j = await api('GET', '/api/users'); users = j.users; S.mailOut = !!j.mail_out; } catch { return; }
    // 2.1.2 (#346): agents are rows too (badge); they are edited in their own dialog (Settings > Agents)
    box.innerHTML = users.map(u => `<div class="mrow ${u.disabled ? 'off' : ''}" data-urow="${u.id}">${u.avatar ? `<span class="avatar pic"><img src="${esc(u.avatar)}" alt="" loading="lazy"></span>` : av(0, u.display_name)}<span class="n">${esc(u.display_name)}${u.kind === 'agent' ? ' ' + agentBadge() : ''} <span class="muted">${esc(u.username)}${u.is_admin ? ' · ' + tr('Admin') : ''}${u.disabled ? ' · ' + tr('disabled') : ''}${u.proxy_login ? ' · ' + tr('SSO: {0}', u.proxy_login) : ''}${u.paperless_access && S.paperless?.configured ? ' · Paperless' : ''}${u.twofa?.length ? ' · ' + tr('2FA') : ''}${u.oidc_linked ? ' · OIDC' : ''}${u.invite === 'invited' ? ' · ' + tr('Invited') : u.invite === 'expired' ? ' · ' + tr('Invitation expired') : ''}</span></span>${u.kind === 'agent'
      ? `<button class="linkbtn agmng" data-acc="agent-edit" data-uid="${u.id}" title="${esc(tr('Open the agent dialog'))}">${tr('Managed under Agents')}</button>`
      : `<button class="iconbtn" data-acc="user-edit" data-uid="${u.id}" title="${tr('Edit user')}">${ic('edit', 's')}</button>`}</div>`).join('');
  };
  drawUsers();
  orgsDraw(md);
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
      if (a === 'user-new') userModal(null, drawUsers);
      if (a === 'org-new') orgModal(null, () => orgsDraw(md));  // 2.22.0 (#752)
      if (a === 'org-edit') orgModal((S.orgs || []).find(o => o.id === +b.dataset.oid), () => orgsDraw(md));
      if (a === 'user-edit') userModal(users.find(u => u.id === +b.dataset.uid), drawUsers);
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
    <div class="row"><label for="u-user">${tr('Username')}</label><input id="u-user" value="${esc(u?.username || '')}" ${u ? 'disabled' : ''} autocapitalize="off" placeholder="${tr('a-z, 0-9, . - _')}"></div>
    <div class="row"><label for="u-name">${tr('Display name')}</label><input id="u-name" value="${esc(u?.display_name || '')}" maxlength="60"></div>
    <div class="row"><label for="u-pw">${tr('Password')}</label><input type="password" id="u-pw" autocomplete="new-password" placeholder="${u ? (u.has_password ? tr('unchanged') : tr('none (single sign-on only)')) : tr('optional, min. 8 characters')}"></div>
    <div class="row"><label for="u-proxy">${tr('SSO login')}</label><input id="u-proxy" value="${esc(u?.proxy_login || '')}" autocapitalize="off" placeholder="${tr('user name at the login proxy (optional)')}"></div>
    <div class="row"><label for="u-email">${tr('E-mail')}</label><input id="u-email" type="email" value="${esc(u?.email || '')}" autocapitalize="off" placeholder="${tr('optional, links an OIDC login')}"></div>
    ${(S.orgs || []).length > 1 || (u && (S.orgs || []).length) ? `<div class="row"><label>${tr('Organisations')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Organisations'))}">${S.orgs.map(o => { const on = u ? (u.orgs || []).includes(o.id) : o.members.includes(S.me.id); return `<button type="button" class="fperson ${on ? 'on' : ''}" data-uorg="${o.id}" aria-pressed="${on}"><span aria-hidden="true">${esc(o.icon || '🏢')}</span><span>${esc(o.name)}</span></button>`; }).join('')}</div></div>` : ''}
    <div class="row"><label for="u-topic">${tr('ntfy topic')}</label><input id="u-topic" value="${esc(u?.ntfy_topic || '')}" autocapitalize="off" placeholder="${tr('empty = random')}"></div>
    ${u ? `<div class="row avrow"><label>${tr('Profile picture')}</label><div class="avpick" id="u-avpick" data-cur="${esc(u.avatar || '')}">${avPickHtml(u.avatar || '', false, u.display_name || u.username)}</div></div>` : ''}
    <div class="row"><label>${tr('Rights')}</label><label class="chkl"><input type="checkbox" id="u-admin" ${u?.is_admin ? 'checked' : ''}> ${tr('Admin')}</label>${S.paperless?.configured ? `<label class="chkl" title="${tr('Search, link and view documents of the Paperless archive')}"><input type="checkbox" id="u-pl" ${u?.paperless_access ? 'checked' : ''}> ${tr('Paperless access')}</label>` : ''}${u ? `<label class="chkl"><input type="checkbox" id="u-dis" ${u.disabled ? 'checked' : ''}> ${tr('disabled')}</label>` : ''}</div>
    ${!u || (u.kind !== 'agent' && u.id !== S.me.id) ? `<div class="row"><label>${tr('Child account')}</label><label class="chkl"><input type="checkbox" id="u-kid" aria-controls="u-parrow" aria-expanded="${!!u?.kid}" ${u?.kid ? 'checked' : ''}> ${tr('A simple view with big buttons, stars and rewards; takes part in shared lists only with what is assigned to it')}</label></div>
    <div class="row kidopts" id="u-parrow" ${u?.kid ? '' : 'hidden'}><label>${tr('Parents')}</label><div class="fpeople" id="u-parents" role="group" aria-label="${esc(tr('Parents'))}"><span class="muted">${tr('Loading…')}</span></div></div>` : ''}
    ${u && !u.is_admin && u.id !== S.me.id ? `<div class="row"><label for="u-kind">${tr('Type')}</label><select id="u-kind"><option value="user">${tr('Person')}</option><option value="agent" ${u.kind === 'agent' ? 'selected' : ''}>${tr('Agent (API only, never admin, no Paperless)')}</option></select></div>` : ''}
    ${u?.has_password ? `<div class="row"><label></label><label class="chkl"><input type="checkbox" id="u-nopw"> ${tr('Remove password (single sign-on only)')}</label></div>` : ''}
    ${!u ? `<div class="row"><label>${tr('Invitation')}</label><label class="chkl"><input type="checkbox" id="u-inv" checked> ${S.mailOut ? tr('Send an invitation by e-mail: the person sets their own password') : tr('Create an invitation link: the person sets their own password')}</label></div>`
      : u.kind !== 'agent' && !u.disabled ? `<div class="row"><label>${u.has_password ? tr('Password') : tr('Invitation')}</label><button type="button" class="btn sm" data-m="invite">${ic(u.has_password ? 'key' : 'send', 's')} ${u.has_password ? tr('Send a link to set a new password') : u.invite ? tr('Send the invitation again') : tr('Send an invitation')}</button></div>` : ''}
    ${u?.twofa?.length ? `<div class="row"><label>${tr('Two-factor')}</label><label class="chkl"><input type="checkbox" id="u-2fareset"> ${tr('Reset (lost phone / passkey and recovery codes)')}</label></div>` : ''}
    ${u?.oidc_linked ? `<div class="row"><label>OIDC</label><label class="chkl"><input type="checkbox" id="u-oidcun"> ${tr('Unlink (the next OIDC login links again by user name or e-mail)')}</label></div>` : ''}
    <div class="muted" style="font-size:var(--fs-s);line-height:1.6">${tr('Every user gets an own inbox, habits, filters, tags and settings. Lists are shared from the list’s “…” menu > Share….')}</div>
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
    if (b.dataset.m === 'invite') {  // 2.22.0 (#697): a new one-time link (invitation / password reset)
      try { const j = await api('POST', `/api/users/${u.id}/invite`, {send: true}); inviteResult(j, u.display_name); done && done(); } catch { /* api() said it */ }
      return;
    }
    let created = false;
    try {
      if (b.dataset.m === 'del') {
        if (!await askConfirm(tr('Delete user “{0}”?', u.display_name), tr('Their inbox, habits, filters and focus history are deleted. Lists they own must be deleted first.'), {ok: tr('Delete user'), danger: true})) return;
        await api('DELETE', '/api/users/' + u.id);
      }
      if (b.dataset.m === 'save') {
        const body = {display_name: $('#u-name', md).value.trim(), proxy_login: $('#u-proxy', md).value.trim(), email: $('#u-email', md).value.trim(), ntfy_topic: $('#u-topic', md).value.trim(), is_admin: $('#u-admin', md).checked};
        if ($('#u-2fareset', md)?.checked) { if (!await askConfirm(tr('Reset the two-factor authentication of “{0}”?', u.display_name), tr('They log in with the password alone (or must set it up again if it is required).'), {ok: tr('Reset'), danger: true})) return; body.reset_2fa = true; }
        if ($('#u-oidcun', md)?.checked) body.oidc_unlink = true;
        if ($('#u-pl', md)) body.paperless_access = $('#u-pl', md).checked;
        if ($('#u-kid', md) && ($('#u-kid', md).checked || u?.kid)) { body.kid = $('#u-kid', md).checked; if (body.kid) { body.parents = [...par]; body.is_admin = false; } }
        const avk = $('#u-avpick', md)?.dataset.pick; if (avk) body.avatar_preset = avk === 'none' ? null : avk;
        if ($('[data-uorg]', md)) body.orgs = $$('[data-uorg][aria-pressed="true"]', md).map(x => +x.dataset.uorg);  // 2.22.0 (#752)
        const pw = $('#u-pw', md).value;
        if (pw) body.password = pw; else if ($('#u-nopw', md)?.checked) body.password = '';
        if ($('#u-kind', md) && $('#u-kind', md).value !== (u.kind || 'user')) {
          if ($('#u-kind', md).value === 'agent' && !await askConfirm(tr('Make “{0}” an agent?', u.display_name), tr('An agent works only through its API tokens: no web login, never admin, no Paperless. Its lists and tokens stay. Manage it under Settings > Agents.'), {ok: tr('Make agent')})) return;
          body.kind = $('#u-kind', md).value;
        }
        if (u) { body.disabled = $('#u-dis', md).checked; await api('PATCH', '/api/users/' + u.id, body); }
        else {
          body.username = $('#u-user', md).value.trim().toLowerCase(); if (!body.ntfy_topic) delete body.ntfy_topic;
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
  if (!isTouch() && (!u))  setTimeout(() => $('#u-user', md).focus(), 50);
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
// 2.22.0 (#697): the page "Set up your account" (the link of an invitation or a password reset: /#invite/<token>)
async function inviteScreen(tok) {
  history.replaceState(null, '', location.pathname);  // the token leaves the address bar (and the history) at once
  let info = null;
  try { const r = await fetch('/api/auth/invite/check', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({token: tok})}); info = await r.json(); if (!r.ok) info = {error: info.error || tr('Error {0}', r.status)}; } catch { info = {error: tr('Server not reachable.')}; }
  await i18nLoad(info.lang || uiLang());
  const el = document.createElement('div');
  el.className = 'modal authscreen';
  const logo = `<div class="alogo">${logoSvg(40)}<b>${APP_NAME}</b></div>`;
  if (info.error) {
    el.innerHTML = `<div class="card">${logo}<p role="alert">${esc(info.error)}</p><button class="btn pri" type="button" data-au="login">${tr('To the login')}</button></div>`;
  } else {
    el.innerHTML = `<div class="card">${logo}
      <h2 class="invh">${esc(info.kind === 'reset' ? tr('Set a new password') : tr('Welcome, {0}!', info.display_name))}</h2>
      <p class="muted">${esc(info.kind === 'reset' ? tr('Choose a new password for “{0}”.', info.username) : tr('Choose your own password to finish your account.'))}</p>
      <form id="inv-form" autocomplete="on">
        <label class="aulab" for="inv-user">${tr('Username')}</label><input id="inv-user" name="username" autocomplete="username" readonly value="${esc(info.username)}">
        <label class="aulab" for="inv-pw">${tr('New password')}</label><input id="inv-pw" type="password" autocomplete="new-password" required minlength="${info.min_password || 8}" placeholder="${esc(tr('at least {0} characters', info.min_password || 8))}">
        <label class="aulab" for="inv-pw2">${tr('Repeat the password')}</label><input id="inv-pw2" type="password" autocomplete="new-password" required>
        <label class="chkl"><input type="checkbox" id="inv-2fa"> ${tr('Set up two-factor sign-in right after (recommended)')}</label>
        <div class="aerr" role="alert" id="inv-err"></div>
        <button class="btn pri" type="submit">${info.kind === 'reset' ? tr('Save and log in') : tr('Set up my account')}</button>
      </form></div>`;
    el.querySelector('#inv-form').addEventListener('submit', async e => {
      e.preventDefault();
      const errEl = $('#inv-err', el), pw = $('#inv-pw', el).value;
      if (pw.length < (info.min_password || 8)) { errEl.textContent = tr('Password: at least {0} characters', info.min_password || 8); return; }
      if (pw !== $('#inv-pw2', el).value) { errEl.textContent = tr('The two passwords are not the same'); return; }
      try {
        const r = await fetch('/api/auth/invite/accept', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({token: tok, password: pw})});
        const res = await r.json().catch(() => ({}));
        if (!r.ok) { errEl.textContent = res.error || tr('Error {0}', r.status); return; }
        if (res.enrol) { await authEnrol(el, logo); return; }
        if ($('#inv-2fa', el).checked) LS.set('after2fa', true);
        location.replace('/');
      } catch { errEl.textContent = tr('Server not reachable.'); }
    });
  }
  el.addEventListener('click', e => { if (e.target.closest('[data-au="login"]')) location.replace('/'); });
  document.body.appendChild(el);
  $('#app')?.setAttribute('inert', '');
  setTimeout(() => $('#inv-pw', el)?.focus(), 50);
}
async function logout() {
  if (OUT.q.length && !await askConfirm(trn('{0} change is not synced yet and will be lost. Log out anyway?', '{0} changes are not synced yet and will be lost. Log out anyway?', OUT.q.length), '', {ok: tr('Log out'), danger: true})) return;
  await wpDisable().catch(() => {});  // this device stops getting the pushes of the account that logs out
  try { await fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}); } catch { /* offline */ }
  clearLocal(); location.replace('/');
}
// login / first-run setup / "no account" screen (built-in login; with single sign-on the proxy logs in)
async function authScreen(j) {
  if ($('.authscreen')) return;
  let info = {};
  try { info = await (await fetch('/api/auth/info')).json(); } catch { /* offline */ }
  await i18nLoad(info.lang || uiLang());
  if ($('.authscreen')) return;
  const kind = info.setup ? 'setup' : j.auth;
  const el = document.createElement('div');
  el.className = 'modal authscreen';
  // 2.14.0: the first account (welcome) shows the heron instead of the small mark
  const logo = kind === 'setup' ? `<div class="alogo hwelc">${heron('welcome', 'hwel')}<b>${APP_NAME}</b></div>` : `<div class="alogo">${logoSvg(40)}<b>${APP_NAME}</b>${info.org ? `<small class="aorg">${esc(info.org)}</small>` : ''}</div>`;  // 2.22.0 (#752): the organisation
  if (kind === 'no_account' || kind === 'disabled') {
    el.innerHTML = `<div class="card">${logo}<p>${kind === 'disabled' ? esc(tr('The account “{0}” is disabled.', j.login || '')) : esc(tr('There is no {0} account for “{1}” yet.', APP_NAME, j.login || ''))}</p><p class="muted">${tr('Please ask the admin to create one (or to enable it).')}</p></div>`;
  } else {
    const setup = kind === 'setup';
    el.innerHTML = `<div class="card">${logo}
      ${setup ? `<p>${tr('Welcome! Create the first account, it becomes the admin.')}</p>${info.login ? `<p class="muted">${esc(tr('Signed in at the login proxy as “{0}”: the account is linked to it, a password is optional.', info.login))}</p>` : ''}` : ''}
      <form id="auth-form" autocomplete="on">
        <label class="aulab" for="au-user">${tr('Username')}</label><input id="au-user" name="username" autocapitalize="off" autocomplete="username" required value="${setup && info.login ? esc(String(info.login).toLowerCase()) : ''}">
        ${setup ? `<label class="aulab" for="au-name">${tr('Display name')}</label><input id="au-name" maxlength="60" autocomplete="name" placeholder="${tr('optional')}">` : ''}
        <label class="aulab" for="au-pw">${tr('Password')}</label><span class="pwwrap"><input id="au-pw" name="password" type="password" autocomplete="${setup ? 'new-password' : 'current-password'}" ${setup && info.login ? '' : 'required'} ${setup ? `placeholder="${tr('at least {0} characters', 8)}"` : ''}><button type="button" class="iconbtn pweye" data-au="pwshow" aria-pressed="false" aria-label="${esc(tr('Show password'))}" title="${esc(tr('Show password'))}">${ic('eye', 's')}</button></span>
        ${setup ? '' : `<label class="chkl"><input type="checkbox" id="au-rem" checked> ${tr('Stay logged in')}</label>`}
        <div class="aerr" role="alert" id="au-err"></div>
        <button class="btn pri" type="submit">${setup ? tr('Create account') : tr('Log in')}</button>
        ${!setup && (info.oidc || (info.passkey_login && pkSupported())) ? `<div class="aor"><span>${tr('or')}</span></div>` : ''}
        ${!setup && info.oidc ? `<button type="button" class="btn" data-au="oidc">${ic('link', 's')} ${esc(tr('Log in with {0}', info.oidc.label))}</button>` : ''}
        ${!setup && info.passkey_login && pkSupported() ? `<button type="button" class="btn" data-au="passkey">${ic('key', 's')} ${tr('Log in with a passkey')}</button>` : ''}
      </form></div>`;
    const le = (location.hash.match(/login-error=([a-z_]+)/) || [])[1];
    if (le) { $('#au-err', el).textContent = (info.login_errors || {})[le] || (info.login_errors || {}).failed || le; history.replaceState(null, '', location.pathname); }
    el.addEventListener('click', e => {
      const b = e.target.closest('[data-au]'); if (!b) return;
      const rem = $('#au-rem', el)?.checked !== false;
      if (b.dataset.au === 'oidc') location.href = '/api/auth/oidc/start?remember=' + (rem ? 1 : 0);
      if (b.dataset.au === 'passkey') authPasskey($('#au-err', el), rem);
      if (b.dataset.au === 'pwshow') { const i = $('#au-pw', el), on = i.type === 'password'; i.type = on ? 'text' : 'password'; b.setAttribute('aria-pressed', String(on)); i.focus(); }  // 2.13.0 (#453 P7)
    });
    el.querySelector('#auth-form').addEventListener('submit', async e => {
      e.preventDefault();
      const errEl = $('#au-err', el);
      const body = setup ? {username: $('#au-user', el).value.trim(), display_name: $('#au-name', el).value.trim(), password: $('#au-pw', el).value, wizard: true}
        : {username: $('#au-user', el).value.trim(), password: $('#au-pw', el).value, remember: $('#au-rem', el).checked};
      try {
        const r = await fetch(setup ? '/api/auth/setup' : '/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(body)});
        const res = await r.json().catch(() => ({}));
        if (!r.ok) { errEl.textContent = res.error || tr('Error {0}', r.status); return; }
        if (setup) { await setupChoices(el, logo); return; }
        if (res.twofa) { await authTwofa(el, logo, res.methods || ['totp']); return; }
        if (res.enrol) { await authEnrol(el, logo); return; }
        location.replace(afterLogin());
      } catch { errEl.textContent = tr('Server not reachable.'); }
    });
  }
  document.body.appendChild(el);
  $('#app')?.setAttribute('inert', '');  // 2.13.0 (#453 P7): nothing behind the login (the hidden "New task" button) gets the focus
  setTimeout(() => $('#au-user', el)?.focus(), 50);
}
// ------------------------------------------------------------------ passkeys (WebAuthn), two-factor, backups
// base64url <-> ArrayBuffer for the WebAuthn JSON the server sends / expects (py_webauthn format)
const b64uBuf = s => { s = String(s).replace(/-/g, '+').replace(/_/g, '/'); const b = atob(s + '='.repeat((4 - s.length % 4) % 4)); const u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u.buffer; };
const bufB64u = buf => { const u = new Uint8Array(buf); let s = ''; for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i]); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
// passkeys need a secure context (HTTPS or localhost) and a domain name (no IP address)
const pkSupported = () => !!(window.PublicKeyCredential && navigator.credentials && window.isSecureContext && !/^[\d.]+$|^\[|:/.test(location.hostname));
async function pkCreate(o) {
  const pk = {...o, challenge: b64uBuf(o.challenge), user: {...o.user, id: b64uBuf(o.user.id)},
    excludeCredentials: (o.excludeCredentials || []).map(c => ({...c, id: b64uBuf(c.id)})), extensions: {credProps: true}};
  const cred = await navigator.credentials.create({publicKey: pk});
  const r = cred.response;
  return {id: cred.id, rawId: bufB64u(cred.rawId), type: cred.type, authenticatorAttachment: cred.authenticatorAttachment || undefined,
    response: {clientDataJSON: bufB64u(r.clientDataJSON), attestationObject: bufB64u(r.attestationObject), transports: r.getTransports ? r.getTransports() : []},
    clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {}};
}
async function pkGet(o) {
  const pk = {...o, challenge: b64uBuf(o.challenge), allowCredentials: (o.allowCredentials || []).map(c => ({...c, id: b64uBuf(c.id)}))};
  const cred = await navigator.credentials.get({publicKey: pk});
  const r = cred.response;
  return {id: cred.id, rawId: bufB64u(cred.rawId), type: cred.type,
    response: {clientDataJSON: bufB64u(r.clientDataJSON), authenticatorData: bufB64u(r.authenticatorData), signature: bufB64u(r.signature), userHandle: r.userHandle ? bufB64u(r.userHandle) : null},
    clientExtensionResults: {}};
}
const pkErr = e => e && (e.name === 'NotAllowedError' || e.name === 'AbortError') ? tr('Cancelled.') : (e?.message || String(e));
// a device name for a new passkey (editable later)
function pkDefaultName() {
  const ua = navigator.userAgent || '';
  const os = /iPhone|iPad/.test(ua) ? 'iPhone / iPad' : /Android/.test(ua) ? 'Android' : /Mac OS X/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : /Linux/i.test(ua) ? 'Linux' : '';
  return os ? tr('Passkey ({0})', os) : tr('Passkey');
}
// POST without the offline queue / session handling (login screen: no session yet)
async function authPost(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(body || {})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.error || tr('Error {0}', r.status)); e.status = r.status; e.j = j; throw e; }
  return j;
}
// recovery codes: shown exactly once (copy / download / "saved")
function rcHtml(codes) {
  return `<p class="muted">${tr('Each code works once, if you lose your phone or passkey. Store them somewhere safe (password manager, printout). They are not shown again.')}</p>
    <div class="rcodes">${codes.map(c => `<code>${esc(c)}</code>`).join('')}</div>
    <div class="row rcbtns"><button type="button" class="btn sm" data-rc="copy">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm" data-rc="dl">${ic('download', 's')} ${tr('Download')}</button></div>`;
}
function rcWire(el, codes) {
  el.addEventListener('click', async e => {
    const b = e.target.closest('[data-rc]'); if (!b) return;
    const text = `${APP_NAME} – ${tr('Recovery codes')} (${location.host})\n\n${codes.join('\n')}\n`;
    if (b.dataset.rc === 'copy') { try { await navigator.clipboard.writeText(text); toast(tr('Copied')); } catch { toast(tr('Copy failed, select the codes by hand')); } }
    if (b.dataset.rc === 'dl') {
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type: 'text/plain'})); a.download = `${APP_NAME.toLowerCase()}-recovery-codes.txt`;
      document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }
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
// asks for the current password (and optionally a code); resolves {password, code} or null
function pwPrompt(title, {code = false, text = ''} = {}) {
  return new Promise(done => {
    const md = modal(`<h3>${esc(title)}</h3>${text ? `<p class="muted">${text}</p>` : ''}<form class="pwform">
      <input type="password" id="pp-pw" placeholder="${tr('current password')}" autocomplete="current-password" required>
      ${code ? `<input id="pp-code" placeholder="${tr('Code from the app or a recovery code')}" autocomplete="one-time-code" autocapitalize="off" required>` : ''}
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Continue')}</button></div></form>`);
    md.classList.add('pwprompt');
    const close = v => { md.remove(); done(v); };
    md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) close(null); });
    md.querySelector('form').addEventListener('submit', e => { e.preventDefault(); close({password: $('#pp-pw', md).value, code: code ? $('#pp-code', md).value.trim() : ''}); });
    setTimeout(() => $('#pp-pw', md)?.focus(), 50);
  });
}
// the TOTP setup step (QR code + secret + first code); used in the settings and at a forced enrolment
const totpSetupHtml = j => `<p class="muted">${tr('Scan the QR code with an authenticator app (for example Aegis, 2FAS, Google Authenticator, 1Password, Bitwarden) or enter the key by hand, then type the 6-digit code it shows.')}</p>
  <div class="totpqr"><img src="${esc(j.qr)}" alt="${tr('QR code')}" width="200" height="200"></div>
  <div class="row totpkey"><label>${tr('Key')}</label><code class="topic" id="totp-secret">${esc(j.secret)}</code></div>
  <input id="totp-code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="${tr('6-digit code')}" aria-label="${tr('6-digit code')}">`;
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
async function refreshMe() { try { S.me = {...S.me, ...(await api('GET', '/api/me'))}; } catch { /* offline */ } }
// ---- login screen: second step, forced enrolment, passkey login
async function authTwofa(el, logo, methods) {
  const card = el.querySelector('.card');
  let recovery = !methods.includes('totp') && !methods.includes('passkey');
  const draw = () => {
    card.innerHTML = `${logo}<p>${recovery ? tr('Enter one of your recovery codes.') : methods.includes('totp') ? tr('Enter the code from your authenticator app.') : tr('Confirm the login with your passkey.')}</p>
      <form id="tfa-form" autocomplete="off">
        ${recovery || methods.includes('totp') ? `<input id="tfa-code" ${recovery ? 'autocapitalize="off" placeholder="xxxxx-xxxxx"' : `inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="${tr('6-digit code')}"`} aria-label="${recovery ? tr('Recovery code') : tr('6-digit code')}" required>
        <button class="btn pri" type="submit">${tr('Verify')}</button>` : ''}
        ${methods.includes('passkey') && !recovery ? `<button type="button" class="btn ${methods.includes('totp') ? '' : 'pri'}" data-tfa="pk" ${pkSupported() ? '' : 'disabled'}>${ic('key', 's')} ${tr('Use a passkey')}</button>` : ''}
        <div class="aerr" role="alert" id="tfa-err"></div>
        <div class="alinks">${methods.includes('recovery') && !recovery ? `<button type="button" class="linkbtn" data-tfa="rc">${tr('Use a recovery code')}</button>` : ''}${recovery && (methods.includes('totp') || methods.includes('passkey')) ? `<button type="button" class="linkbtn" data-tfa="back2">${tr('Back')}</button>` : ''}<button type="button" class="linkbtn" data-tfa="restart">${tr('Log in again')}</button></div>
      </form>`;
    setTimeout(() => $('#tfa-code', card)?.focus(), 50);
  };
  const fail = x => { if (x.j?.expired) { location.replace('/'); return; } $('#tfa-err', card).textContent = x.message; };
  const done = res => { if (res.recovery_left !== undefined && res.recovery_left < 3) LS.set('rcWarn', res.recovery_left); location.replace(afterLogin()); };
  draw();
  card.addEventListener('submit', async e => {
    e.preventDefault();
    const v = $('#tfa-code', card).value.trim();
    try { done(await authPost('/api/auth/2fa', recovery ? {recovery: v} : {code: v})); } catch (x) { fail(x); }
  });
  card.addEventListener('click', async e => {
    const b = e.target.closest('[data-tfa]'); if (!b) return;
    if (b.dataset.tfa === 'rc') { recovery = true; draw(); }
    if (b.dataset.tfa === 'back2') { recovery = false; draw(); }
    if (b.dataset.tfa === 'restart') location.replace('/');
    if (b.dataset.tfa === 'pk') {
      try { const o = await authPost('/api/auth/2fa/passkey/options'); done(await authPost('/api/auth/2fa/passkey', {credential: await pkGet(o)})); }
      catch (x) { if (x instanceof Error && x.j) fail(x); else $('#tfa-err', card).textContent = pkErr(x); }
    }
  });
}
async function authEnrol(el, logo) {
  const card = el.querySelector('.card');
  const codes = async res => { card.innerHTML = `${logo}<h3>${tr('Recovery codes')}</h3>${rcHtml(res.recovery_codes || [])}<div class="sufoot"><button type="button" class="btn pri" data-en="go">${tr('I have saved them')}</button></div>`; rcWire(card, res.recovery_codes || []); };
  const start = () => {
    card.innerHTML = `${logo}<p>${tr('Two-factor authentication is required on this server. Set it up now, then you are logged in.')}</p>
      <div class="enrolopts"><button type="button" class="btn pri" data-en="totp">${ic('lock', 's')} ${tr('Use an authenticator app')}</button>
      <button type="button" class="btn" data-en="pk" ${pkSupported() ? '' : 'disabled'}>${ic('key', 's')} ${tr('Use a passkey')}</button></div>
      ${pkSupported() ? '' : `<p class="muted">${tr('Passkeys need HTTPS (or localhost), a host name instead of an IP address and a current browser.')}</p>`}
      <div class="aerr" role="alert" id="en-err"></div><div class="alinks"><button type="button" class="linkbtn" data-en="restart">${tr('Log in again')}</button></div>`;
  };
  const fail = x => { if (x.j?.expired) { location.replace('/'); return; } const e = $('#en-err', card) || $('#totp-err', card); if (e) e.textContent = x.message || pkErr(x); };
  start();
  card.addEventListener('submit', async e => {
    e.preventDefault();
    try { await codes(await authPost('/api/auth/enrol/totp/confirm', {code: $('#totp-code', card).value})); } catch (x) { fail(x); }
  });
  card.addEventListener('click', async e => {
    const b = e.target.closest('[data-en]'); if (!b) return;
    try {
      if (b.dataset.en === 'restart' || b.dataset.en === 'go') location.replace('/');
      if (b.dataset.en === 'back') start();
      if (b.dataset.en === 'totp') {
        const t = await authPost('/api/auth/enrol/totp');
        card.innerHTML = `${logo}<form id="en-totp">${totpSetupHtml(t)}<div class="aerr" role="alert" id="totp-err"></div><button class="btn pri" type="submit">${tr('Turn on')}</button></form><div class="alinks"><button type="button" class="linkbtn" data-en="back">${tr('Back')}</button></div>`;
        setTimeout(() => $('#totp-code', card)?.focus(), 50);
      }
      if (b.dataset.en === 'pk') {
        const o = await authPost('/api/auth/enrol/passkey/options');
        let cred;
        try { cred = await pkCreate(o); } catch (x) { $('#en-err', card).textContent = pkErr(x); return; }
        await codes(await authPost('/api/auth/enrol/passkey', {credential: cred, name: pkDefaultName()}));
      }
    } catch (x) { fail(x); }
  });
}
async function authPasskey(errEl, remember) {
  try {
    const o = await authPost('/api/auth/passkey/options', {remember});
    const cred = await pkGet(o);
    await authPost('/api/auth/passkey', {credential: cred});
    location.replace('/');
  } catch (x) { errEl.textContent = x instanceof Error && x.j ? x.message : pkErr(x); }
}
// ---- Settings > Users > Whole server: sign-in (2FA policy, passkey login, OIDC)
function signinHtml(hint) {
  const a = S.about || {}, o = a.oidc || {};
  let h = `<h4 id="s-signin-h">${tr('Sign-in')}</h4>
    <div class="featgrid">
      <label class="wide"><input type="checkbox" id="s-2fareq" ${a.twofa_required ? 'checked' : ''}><span>${tr('Require two-factor authentication for built-in logins')}<small class="muted">${tr('Everyone who logs in with a password must set up an authenticator app or a passkey at the next login. Single sign-on logins (login proxy, OIDC) are not affected: there the login provider is responsible.')}</small></span></label>
      <label class="wide"><input type="checkbox" id="s-pklogin" ${a.passkey_login !== false ? 'checked' : ''}><span>${tr('Allow logging in with a passkey without the password')}<small class="muted">${tr('A passkey someone added in Settings > Account then also works on its own (the device asks for the fingerprint, face or PIN).')}</small></span></label>
    </div>
    <h4 id="s-oidc-h">${tr('Login with an OIDC provider')}</h4>`;
  if (!o.configured) return h + hint(tr('Not configured yet. Log in with Authentik, Keycloak, Authelia, PocketID, Google, Microsoft Entra or any other OpenID Connect provider: fill in the provider below (or set the KALMIDO_OIDC_* variables) and register this redirect URI at the provider: {0}', `<code class="topic">${esc(o.redirect_uri || '')}</code>`)) + oidcForm(o, hint);
  const row = (l, v) => v ? `<div class="row"><label>${l}</label><code class="topic">${esc(v)}</code></div>` : '';
  h += row(tr('Provider'), o.issuer) + row(tr('Client ID'), o.client_id) +
    `<div class="row"><label>${tr('Redirect URI')}</label><code class="topic" id="s-oidcredir">${esc(o.redirect_uri)}</code><button class="btn sm" data-m="oidc-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>` +
    row(tr('Scopes'), o.scopes) + row(tr('User name claim'), o.username_claim) + row(tr('Required group'), o.required_group) + row(tr('Admin group'), o.admin_group) +
    row(tr('Admin e-mail domains'), o.admin_domains) +
    hint(tr('The client secret is {0}.', o.secret_set ? tr('set') : tr('not set (public client with PKCE)')) + ' ' +
      trn('{0} user is linked to the provider.', '{0} users are linked to the provider.', o.linked || 0)) +
    `<div class="featgrid"><label class="wide"><input type="checkbox" id="s-oidcauto" ${o.autocreate ? 'checked' : ''}><span>${tr('Create accounts on the first OIDC login')}<small class="muted">${tr('Off: only users an admin created can log in; the first login links them by user name or verified e-mail. On: anyone the provider lets through gets an account.')}</small></span></label></div>`;
  if (o.error) h += `<div class="shint cnote">${tr('Last problem with the provider: {0}', esc(o.error))}</div>`;
  return h + oidcForm(o, hint);
}
// 2.9.0 (#438): the provider set up here (stored, the client secret encrypted with KALMIDO_SECRET_KEY); a field set by a
// KALMIDO_OIDC_* variable is locked (the environment wins)
const OIDC_DOCS = 'https://github.com/Gegenschuss/kalmido/blob/main/docs/OIDC.md';
const OIDC_FORM = [['issuer', N_('Provider'), 'https://auth.example.com/application/o/kalmido/'], ['client_id', N_('Client ID'), ''], ['client_secret', N_('Client secret'), ''],
  ['scopes', N_('Scopes'), 'openid profile email'], ['username_claim', N_('User name claim'), 'preferred_username'], ['groups_claim', N_('Groups claim'), 'groups'],
  ['required_group', N_('Required group'), ''], ['admin_group', N_('Admin group'), ''], ['admin_domains', N_('Admin e-mail domains'), 'example.com'], ['label', N_('Button label'), 'OpenID Connect']];
function oidcForm(o, hint) {
  const env = new Set(o.env || []), st = o.stored || {};
  const f = OIDC_FORM.map(([k, n, ph]) => {
    const lock = env.has(k), sec = k === 'client_secret';
    const val = lock ? (sec ? '' : o[k === 'admin_domains' ? 'admin_domains' : k] || '') : sec ? '' : st[k] || '';
    const pl = lock ? tr('set by the server environment') : sec ? (o.secret_set && !env.has(k) ? tr('set (unchanged)') : tr('empty = public client with PKCE')) : ph;
    return `<div class="row"><label for="oi-${k}">${tr(n)}</label><input id="oi-${k}" data-oik="${k}" ${sec ? 'type="password" autocomplete="new-password"' : 'autocomplete="off" spellcheck="false"'} value="${esc(val)}" placeholder="${esc(pl)}" ${lock ? 'readonly' : ''}>${sec && o.secret_set && !lock ? `<button class="btn sm" data-oidc="secret-del">${tr('Remove')}</button>` : ''}</div>`;
  }).join('');
  return `<details class="shelp sdet oidcform" ${o.configured ? '' : 'open'}><summary>${o.configured ? tr('Change the provider settings') : tr('Set up the provider')}</summary>
    ${f}
    ${hint(tr('Admin e-mail domains: comma-separated. Whoever logs in with a verified e-mail of one of them becomes an admin, like the admin group (and no longer is one otherwise; the last admin always stays).'))}
    ${env.size ? hint(tr('Fields set with KALMIDO_OIDC_* environment variables are locked here: the environment always wins.')) : ''}
    ${o.secret_lost ? `<div class="shint cnote">${tr('The stored client secret cannot be read with the current KALMIDO_SECRET_KEY: enter it again.')}</div>` : ''}
    ${!o.secret_key && !env.has('client_secret') ? `<div class="shint iiok">${tr('Without KALMIDO_SECRET_KEY on the server the client secret can only be set as an environment variable.')}</div>` : ''}
    <div class="row"><button class="btn sm pri" data-oidc="save">${tr('Save')}</button>${o.configured ? `<button class="btn sm" data-oidc="check">${ic('check', 's')} ${tr('Check provider')}</button>` : ''}<a class="btn sm" href="${OIDC_DOCS}" target="_blank" rel="noopener noreferrer">${ic('help', 's')} ${tr('Provider guides')}</a></div>
    <div class="shint" id="oi-res" role="status" aria-live="polite"></div></details>`;
}
function oidcWire(md) {
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-oidc]'); if (!b) return;
    const res = $('#oi-res', md), env = new Set(S.about?.oidc?.env || []);
    if (b.dataset.oidc === 'check') {
      b.disabled = true;
      try { const j = await calReq('POST', '/api/admin/oidc/check', {}); res.textContent = j.ok ? tr('The provider answers: {0}', j.issuer) : tr('Provider check failed: {0}', j.error); }
      catch (x) { res.textContent = x.message; } finally { b.disabled = false; }
      return;
    }
    const body = {};
    if (b.dataset.oidc === 'secret-del') body.client_secret = '';
    else $$('[data-oik]', md).forEach(i => { const k = i.dataset.oik; if (env.has(k) || (k === 'client_secret' && !i.value)) return; body[k] = i.value.trim(); });
    b.disabled = true;
    try {
      const o = await calReq('PUT', '/api/admin/oidc', body);
      if (S.about) S.about.oidc = o;
      toast(tr('Saved'));
      const box = $('#s-signin', md); if (box) box.innerHTML = signinHtml(t => `<div class="shint">${t}</div>`);
    } catch (x) { res.textContent = x.message; } finally { b.disabled = false; }
  });
}
// ---- Settings > Users > Whole server > Backups
// 2.13.0: "Check storage": files of tasks / projects that are missing, empty or cut off on disk (read-only)
const stoHtml = () => `<h4 id="s-sto-h">${tr('Check storage')}</h4><div class="row"><button class="btn sm" data-m="sto-check">${ic('search', 's')} ${tr('Check storage')}</button></div><div id="s-sto" role="status" aria-live="polite"></div>`;
async function stoCheck(md) {
  const box = $('#s-sto', md); if (!box) return;
  box.innerHTML = `<div class="muted mhint">${tr('Loading…')}</div>`;
  let j; try { j = await api('GET', '/api/admin/storage-check'); } catch { box.innerHTML = ''; return; }
  const P = {missing: N_('missing'), empty: N_('empty'), size: N_('incomplete')};
  box.innerHTML = !j.problems.length ? `<div class="muted mhint">${esc(trn('{0} file checked, all fine', '{0} files checked, all fine', j.checked))}</div>`
    : `<div class="mhint warn">${esc(trn('{0} damaged or missing file', '{0} damaged or missing files', j.problems.length))}</div><ul class="stol">${j.problems.map(p => `<li><b>${esc(p.name)}</b> <span class="muted">${esc(p.where)} · ${esc(tr(P[p.problem]))}</span>${p.kind === 'attachment' && p.owner ? ` <button class="linkbtn" data-act="open-id" data-id="${p.owner}">${tr('Open')}</button>` : ''}</li>`).join('')}</ul>`;
}
const bkHtml = () => `<h4 id="s-bk-h">${tr('Backups')}</h4><div id="s-bk"><div class="muted mhint">${tr('Loading…')}</div></div>`;
const BK_KIND = {auto: N_('automatic'), manual: N_('manual'), safety: N_('before a restore')};
const fmtBytes = n => n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round((n || 0) / 1e3)) + ' kB';
async function bkDraw(md, j) {
  const box = $('#s-bk', md); if (!box) return;
  if (!j) { try { j = await api('GET', '/api/admin/backups'); } catch (x) { box.innerHTML = `<div class="muted mhint">${x.status === 404 ? esc(x.message) : tr('Only available online.')}</div>`; return; } }
  box._j = j;
  const hint = t => `<div class="shint">${t}</div>`;
  let h = `<div class="featgrid"><label class="wide"><input type="checkbox" id="bk-on" ${j.on ? 'checked' : ''}><span>${tr('Automatic backups')}<small class="muted">${tr('Every day a copy of the database and all attachments goes into the folder {0} on the server. Copy that folder somewhere else too (another disk, your usual server backup): a backup on the same disk does not help if the disk dies.', `<code>${esc(j.dir)}</code>`)}</small></span></label></div>
    <div class="row"><label for="bk-time">${tr('Time')}</label>${timeIn('bk-time', j.time, {label: tr('Time'), clear: false})}</div>
    <div class="row"><label for="bk-daily">${tr('Keep')}</label><input type="number" class="aanum" id="bk-daily" min="1" max="365" value="${j.keep_daily}"><span class="muted">${tr('daily')}</span><input type="number" class="aanum" id="bk-weekly" min="0" max="520" value="${j.keep_weekly}"><span class="muted">${tr('weekly')}</span></div>
    <div class="featgrid"><label class="wide"><input type="checkbox" id="bk-enc" ${j.encrypt ? 'checked' : ''}><span>${tr('Encrypt backups')}<small class="muted">${tr('AES-256 with a passphrase. Without the passphrase an encrypted backup cannot be restored, not even by you or the admin. Write it down somewhere safe (password manager).')}</small></span></label></div>
    <div class="row"><label for="bk-pass">${tr('Passphrase')}</label><input type="password" id="bk-pass" autocomplete="new-password" placeholder="${j.passphrase_env ? tr('set by the server operator') : j.passphrase_set ? tr('set (unchanged)') : tr('at least 10 characters')}" ${j.passphrase_env ? 'readonly' : ''}></div>
    <div class="row"><button class="btn sm" data-bk="now" ${j.running ? 'disabled' : ''}>${ic('archive', 's')} ${tr('Back up now')}</button></div>`;
  const st = [j.running ? (j.running === 'restore' ? tr('A restore is running…') : tr('Backup running…')) : j.last_ok ? tr('Last backup: {0}.', esc(aaWhen(j.last_ok))) : tr('No backup yet.'),
    tr('Backups use {0}, {1} free on the disk.', fmtBytes(j.total_bytes), j.free_bytes ? fmtBytes(j.free_bytes) : '?')];
  h += hint(st.join(' '));
  if (j.last_error) h += `<div class="shint cnote">${tr('The last backup failed ({0}): {1}', esc(aaWhen(j.last_error_at)), esc(j.last_error))}</div>`;
  h += j.items.length ? `<div class="members bklist">${j.items.map(x => `<div class="mrow bkrow" data-bkn="${esc(x.name)}"><span class="n"><b>${esc(aaWhen(x.created_at))}</b> · ${tr(BK_KIND[x.kind] || x.kind)} · ${fmtBytes(x.size)}${x.encrypted ? ` · ${ic('lock', 's')} ${tr('encrypted')}` : ''}
      <small class="muted" style="display:block">${x.unreadable ? tr('unreadable') : `${trn('{0} task', '{0} tasks', x.counts.tasks || 0)}, ${trn('{0} file', '{0} files', x.attachment_files || 0)}, ${trn('{0} user', '{0} users', x.counts.users || 0)} · v${esc(x.app_version)}`}</small></span>
      <a class="iconbtn" href="/api/admin/backups/${encodeURIComponent(x.name)}/download" download="${esc(x.name)}" title="${tr('Download')}">${ic('download', 's')}</a>
      <button class="iconbtn" data-bk="verify" title="${tr('Check')}">${ic('check', 's')}</button><button class="iconbtn" data-bk="restore" title="${tr('Restore')}">${ic('undo', 's')}</button><button class="iconbtn" data-bk="del" title="${tr('Delete')}">${ic('trash', 's')}</button></div>`).join('')}</div>` : `<div class="muted mhint">${tr('No backups yet.')}</div>`;
  h += `<div class="row"><label for="bk-file">${tr('Restore from a file')}</label>${fileBtn('bk-file', '.zip,.enc,application/zip')}</div>
    ${hint(tr('Larger files: copy them into the backup folder on the server instead, they then show up in the list.'))}`;
  box.innerHTML = h;
  box._body = bkBody(md);
  if (j.running && !box._poll) box._poll = setTimeout(async () => { box._poll = null; if (md.isConnected) await bkDraw(md); }, 1500);
}
function bkRestore(md, src) {
  // src: {name} or {upload}, plus created_at, encrypted, counts, attachment_files
  return new Promise(done => {
    const m = modal(`<h3>${tr('Restore backup')}</h3>
      <p>${tr('This replaces <b>all data on this server</b> (every user’s lists, tasks, files and settings) with the state of {0}.', `<b>${esc(aaWhen(src.created_at) || '?')}</b>`)}</p>
      <p class="muted">${trn('{0} task', '{0} tasks', src.counts?.tasks || 0)}, ${trn('{0} file', '{0} files', src.attachment_files || 0)}, ${trn('{0} user', '{0} users', src.counts?.users || 0)}. ${tr('A safety backup of the current state is made first. Everyone else is logged out.')}</p>
      <form class="pwform">${src.encrypted ? `<input type="password" id="bkr-pass" autocomplete="off" placeholder="${tr('Passphrase (empty = the saved one)')}">` : ''}
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
const bkBody = md => $('#bk-on', md) ? {on: $('#bk-on', md).checked, time: $('#bk-time', md).value || '03:30', keep_daily: Math.max(1, +$('#bk-daily', md).value || 14), keep_weekly: Math.max(0, +$('#bk-weekly', md).value || 0), encrypt: $('#bk-enc', md).checked} : null;
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
const PURPOSES = [['me', 'user', N_('For me'), N_('Your own tasks: lists, reminders and the calendar. More views any time under Settings > Modules.')],
  // 2.22.0 (#741): "Home" for one person or a couple: Home & life with contracts, devices, staying in touch, health, journal
  ['home', 'home', N_('Home'), N_('Your household and life: contracts, warranties and upkeep, staying in touch, health, a journal, trips and read later.')],
  ['family', 'family', N_('Family'), N_('Shared lists, a shopping list with shop areas, household chores taking turns, birthdays, a meal plan and accounts for children.')],
  ['team', 'users', N_('Team'), N_('Sharing, assigning, comments, time tracking, a timeline with dependencies, custom fields and project progress.')],
  ['software', 'code', N_('Software projects'), N_('Everything of Team plus a software project: a board from backlog to done, bug and feature tickets, a repository.')]];
const PURPOSE_MODS = {me: ['cal', 'events', 'contacts'],
  home: ['cal', 'events', 'contacts', 'habits', 'contracts', 'home', 'care', 'health', 'review', 'travel', 'reading'],
  family: ['cal', 'habits', 'comments', 'collab', 'family', 'events', 'contacts', 'contracts', 'home', 'travel'],
  team: ['cal', 'timeline', 'matrix', 'kanban', 'habits', 'pomo', 'stats', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts'],
  software: ['cal', 'timeline', 'matrix', 'kanban', 'habits', 'pomo', 'stats', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts']};
// First-run setup, step 2 ("What do you want to use?"): only right after the first admin was created, never on
// existing installs. Three presets (1.2: "Simple list"; "Just me" preselected; "Projects & team" = everything), then
// the single modules to fine-tune. Collaboration + time tracking are the instance switches; the other modules
// become the default of new users (the admin gets them too). "Skip" leaves everything on. All changeable later.
const SETUP_MAIN = [['collab', N_('Collaboration'), N_('Share lists, assign tasks, @mentions, activity and News')],
  ['time', N_('Time tracking'), N_('Timers and manual time entries on tasks, reports and CSV export')]];
const SETUP_MODS = [['cal', N_('Calendar'), N_('Month, week and day view of your tasks')], ['timeline', N_('Timeline'), N_('Tasks with start and end as bars over time')],
  ['events', N_('Events'), N_('Appointments in your own calendars next to the tasks, shared calendars, invitations, synced with the phone’s calendar')],
  ['contacts', N_('Contacts'), N_('Your address books: contacts linked to tasks and events, birthdays, synced with the phone’s contacts')],
  ['matrix', N_('Eisenhower matrix'), N_('Urgent and important in four quadrants')], ['kanban', N_('Kanban'), N_('Lists as boards with columns')],
  ['habits', N_('Habits'), N_('Daily and weekly habits with streaks')], ['pomo', N_('Focus (Pomodoro)'), N_('Focus timer and stopwatch')],
  ['stats', N_('Statistics'), N_('Completions, on-time rate, focus time and streaks')], ['progress', N_('Project progress'), N_('Progress per list and a “Where is it stuck?” overview')],
  ['deps', N_('Dependencies'), N_('Tasks that wait on other tasks, with arrows in the timeline (Gantt)')], ['fields', N_('Custom fields'), N_('Own fields per list, such as budget, client or phase')],
  ['paperless', N_('Paperless link'), N_('Link documents from Paperless-ngx to tasks')],
  ['comments', N_('Comments'), N_('Timestamped notes on your tasks; in shared lists with collaboration also @mentions and News')],
  ['family', N_('Family'), N_('Birthdays, household chores taking turns, shopping lists with shop areas, a meal plan, deadlines, packing lists and accounts for children')]];
// 2.7.0 (K21, #405): a simple start for a new instance; one question "Start with" below. 2.19.0 (#653): the presets are the
// answers to "What do you use Kalmido for?" (For me = the simple start, Family, Team, Software projects)
const SETUP_PRESETS = Object.fromEntries(PURPOSES.map(([k, i, n, d]) => [k, {name: n, icon: i, desc: d,
  off: [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]).filter(x => x !== 'paperless' && !PURPOSE_MODS[k].includes(x))}]));
async function setupChoices(el, logo) {
  let st = {};
  try { st = await (await fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}})).json(); } catch { /* offline: defaults */ }
  const langs = st.languages || [{code: 'en', name: 'English'}];
  const pl = !!st.paperless?.configured;
  const all = [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]);
  let lang = I18N.code || 'en', preset = 'me', picked, custOpen = false, start = '';
  const apply = k => { preset = k; picked = new Set(all.filter(x => !SETUP_PRESETS[k].off.includes(x))); };
  apply('me');
  // 2.13.2 (#478 F12): step 2 shown again after a reload (setup still pending) starts from what is on now, not from
  // "Simple list" ("Start" would switch modules off again); a new account (all modules on = the default) keeps "Simple list"
  const fs0 = st.settings?.features;
  if (typeof fs0 === 'string' && !all.filter(x => x !== 'family').every(x => fs0.split(',').includes(x))) {  // everything on = the untouched default (2.19.0: Family is off by default)
    const on = new Set(fs0.split(',')); picked = new Set(all.filter(x => on.has(x) && (x !== 'collab' || st.collab_all !== false) && (x !== 'time' || st.time_all !== false)));
    preset = Object.keys(SETUP_PRESETS).find(k => all.every(x => picked.has(x) === !SETUP_PRESETS[k].off.includes(x))) || '';
  }
  // 2.7.0 (K21): one question "Start with": empty, the sample project, or a project of a built-in type (agency, software, personal)
  const STARTS = [['', N_('Empty|start'), 'list', N_('Your Inbox and Today, nothing else')], ['sample', N_('Sample project'), 'eye', N_('A small video production with dates and a packing list, to look around; remove it any time under Settings > Data')],
    ...PTYPE_UI.slice(1).map(([k, n, i, d]) => [k, n, i, d])];
  const row = ([k, n, d]) => `<label class="suse"><input type="checkbox" data-use="${k}" ${picked.has(k) ? 'checked' : ''}><span><b>${tr(n)}</b><small class="muted">${tr(d)}</small></span></label>`;
  const matches = k => all.every(x => picked.has(x) === !SETUP_PRESETS[k].off.includes(x));
  const draw = () => {
    el.innerHTML = `<div class="card setupcard">${logo}
      <div class="seg" id="su-lang">${langs.map(L => `<button type="button" data-su-lang="${esc(L.code)}" class="${L.code === lang ? 'on' : ''}" lang="${esc(L.code)}">${langName(L)}</button>`).join('')}</div>
      <h3>${tr('What do you use Kalmido for?')}</h3>
      <p class="muted">${tr('Pick a start, untick what you do not need. Everything can be changed later in Settings.')}</p>
      <div class="supresets">${Object.entries(SETUP_PRESETS).map(([k, p]) => `<button type="button" class="supreset ${matches(k) ? 'on' : ''}" data-su-preset="${k}" aria-pressed="${matches(k)}"><b>${ic(p.icon, 's')}${tr(p.name)}</b><small class="muted">${tr(p.desc)}</small></button>`).join('')}</div>
      <details class="sucust" ${custOpen ? 'open' : ''}><summary>${tr('Customize…')} <span class="muted">${tr('{0} of {1} modules on', [...picked].filter(k => k !== 'paperless' || pl).length, SETUP_MAIN.length + SETUP_MODS.filter(([k]) => k !== 'paperless' || pl).length)}</span></summary>
      <div class="suse-main">${SETUP_MAIN.map(row).join('')}</div>
      <div class="suse-list">${SETUP_MODS.filter(([k]) => k !== 'paperless' || pl).map(row).join('')}</div></details>
      <h3 id="su-start-h">${tr('Start with')}</h3>
      <div class="sustarts ptcards" role="radiogroup" aria-labelledby="su-start-h">${STARTS.map(([k, n, i, d]) => `<button type="button" class="ptcard ${k === start ? 'on' : ''}" role="radio" aria-checked="${k === start}" data-su-start="${k}">${ic(i, 's')}<b>${tr(n)}</b><small class="muted">${tr(d)}</small></button>`).join('')}</div>
      <p class="muted sunote">${tr('More projects any time: Lists > + > New project.')}</p>
      <div class="aerr" role="alert" id="su-err"></div>
      <div class="sufoot"><button type="button" class="btn pri" data-su="go">${tr('Start')}</button></div></div>`;
    $('.sucust', el)?.addEventListener('toggle', e => { custOpen = e.target.open; });
  };
  draw();
  el.addEventListener('change', e => {
    const c = e.target.closest('[data-use]'); if (!c) return;
    c.checked ? picked.add(c.dataset.use) : picked.delete(c.dataset.use);
    $$('[data-su-preset]', el).forEach(b => { b.classList.toggle('on', matches(b.dataset.suPreset)); b.setAttribute('aria-pressed', matches(b.dataset.suPreset)); });
    const sm = $('.sucust summary .muted', el); if (sm) sm.textContent = tr('{0} of {1} modules on', [...picked].filter(k => k !== 'paperless' || pl).length, SETUP_MAIN.length + SETUP_MODS.filter(([k]) => k !== 'paperless' || pl).length);
  });
  el.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.suLang) { lang = b.dataset.suLang; await i18nLoad(lang); LS.set('lang', lang); draw(); return; }
    if (b.dataset.suPreset) { apply(b.dataset.suPreset); if (b.dataset.suPreset === 'software') start = 'software'; else if (start === 'software') start = ''; draw(); return; }
    if (b.dataset.suStart !== undefined) {
      start = b.dataset.suStart;
      // a project type needs its modules (agency: time tracking + custom fields, software: kanban + dependencies)
      for (const m of {agency: ['time', 'fields'], software: ['kanban', 'deps']}[start] || []) picked.add(m);
      draw(); return;
    }
    const post = async (url, body) => { const r = await fetch(url, {method: url.endsWith('settings') ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(body)}); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || tr('Error {0}', r.status)); };
    try {
      if (b.dataset.su === 'go') await post('/api/admin/setup', {lang, collab_all: picked.has('collab'), time_all: picked.has('time'), modules: SETUP_MODS.map(x => x[0]).filter(k => picked.has(k) || (k === 'paperless' && !pl)), sample: start === 'sample', ...(start && start !== 'sample' ? {project_type: start} : {}), ...(matches(preset) ? {purpose: preset} : {})});
      else return;
      location.replace('/');
    } catch (err) { $('#su-err', el).textContent = err.message || tr('Server not reachable.'); }
  });
}
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
function sectionMenu(anchor, sid) {
  const s = S.sections.find(x => x.id === sid);
  menu(anchor, [
    {label: tr('Rename'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename section'), s.name, {ok: tr('Rename')}); if (n && n.trim()) sectionRename(sid, n.trim()); }},
    {label: tr('Move left / up'), icon: 'left', fn: () => moveSection(sid, -1)},
    {label: tr('Move right / down'), icon: 'right', fn: () => moveSection(sid, 1)},
    '-',
    {label: tr('Delete (tasks stay)'), icon: 'trash', cls: 'flag-5', fn: () => sectionDelete(sid)},
  ]);
}

// ---- 1.8.0: sample project "Example: Image film for client Muster" + a packing checklist (built on the server, in the
// user's language, only with the modules that are on). Offered in the setup and the welcome tour, created / removed
// under Settings > Data (and the command palette). Removing takes exactly what the sample created: tasks the user
// added stay, and so does their list.
const sampleDefault = () => depsOn() || fieldsOn() || timeOn() || progressOn();  // "Projects & team"-like setups
async function sampleCreate({open = true} = {}) {
  let j; try { j = await api('POST', '/api/sample', {}); } catch { return null; }
  await load();
  toast(j.created ? tr('Sample project created. Remove it any time under Settings > Data.') : tr('The sample project already exists'));
  if (open && j.list_id) go('l/' + j.list_id); else render();
  return j;
}
function sampleSummary(sm) {
  const extra = sm.lists.reduce((a, l) => a + (l.extra || 0), 0);
  return [sm.lists.length ? tr('Removes {0} and their {1}.', sm.lists.map(l => `“${l.name}”`).join(tr(' and ')), trn('{0} sample task', '{0} sample tasks', sm.tasks))
    : trn('Removes {0} sample task.', 'Removes {0} sample tasks.', sm.tasks),
  extra ? trn('{0} task you added stays, and so does its list.', '{0} tasks you added stay, and so do their lists.', extra) : '',
  tr('Nothing else is affected.')].filter(Boolean).join(' ');
}
async function sampleRemove() {
  const sm = S.sample;
  if (!sm) { toast(tr('There is no sample project')); return false; }
  if (!await askConfirm(tr('Remove the sample project?'), sampleSummary(sm), {ok: tr('Remove'), danger: true})) return false;
  let j; try { j = await api('DELETE', '/api/sample'); } catch { return false; }
  if (S.route.mod === 'tasks' && sm.lists.some(l => S.route.key === 'l:' + l.id) && !j.kept_lists) go(START_KEY);
  await load(); render();
  toast(trn('Sample project removed ({0} task)', 'Sample project removed ({0} tasks)', j.tasks || 0));
  return true;
}
const sampleRowHtml = () => S.sample ? `<label>${tr('Sample')}</label><button class="btn sm danger" data-m="sample-rm">${ic('trash', 's')} ${tr('Remove sample project')}</button><span class="muted" style="font-size:var(--fs-s)">${esc(S.sample.lists.map(l => l.name).join(', '))}</span>`
  : `<label>${tr('Sample')}</label><button class="btn sm" data-m="sample-add">${ic('plus', 's')} ${tr('Create sample project')}</button>`;
const sampleHtml = hint => `<h4 id="s-sample-h">${tr('Sample project')}</h4>
      ${hint(tr('An example video production with sections, dates, dependencies and a packing checklist: a quick way to see how projects work. Private to you, without reminders.'))}
      <div class="row" id="s-sample">${sampleRowHtml()}</div>`;
