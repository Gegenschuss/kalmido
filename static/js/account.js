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
// 2.47.1 (#1721): the palette of the fixed account colours as round buttons (the own colour here, an agent's in its settings)
const AC_NAMES = [N_('Blue'), N_('Orange'), N_('Green'), N_('Purple'), N_('Red'), N_('Teal'), N_('Yellow'), N_('Pink'), N_('Sky blue'), N_('Brown'), N_('Violet'), N_('Lime')];
const ac_pickHtml = (cur, who) => AC_COLORS.map((c, i) => `<button type="button" data-accol="${c}" data-acwho="${esc(String(who))}" style="--acol:${c}" title="${esc(tr(AC_NAMES[i]))}" aria-label="${esc(tr(AC_NAMES[i]))}" aria-pressed="${cur === c}"></button>`).join('');
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-accol]'); if (!b) return;
  e.preventDefault();
  const c = b.dataset.accol, who = b.dataset.acwho, aid = who === 'me' ? 0 : +who;
  const prev = (S.colors || {})[aid || S.me.id] || '';
  try { await api('PATCH', aid ? `/api/agents/${aid}/color` : '/api/me', {color: c}); } catch { return; }  // the error is shown
  (S.colors ||= {})[aid || S.me.id] = c;
  if (aid && prev && prev !== c && typeof histAdd === 'function') {  // 2.83.0 (#1775): one undo step for an agent's colour
    const put = v => async () => { await api('PATCH', `/api/agents/${aid}/color`, {color: v}); S.colors[aid] = v; render(); return {}; };
    offerUndo(tr('Saved'), histAdd({label: tr('Colour changed'), undo: put(prev), redo: put(c)}));
  }
  for (const x of b.parentElement.children) x.setAttribute('aria-pressed', String(x === b));
  const acct = $('.acct'); if (acct && !aid) acct.firstElementChild.outerHTML = av(S.me.id, S.me.display_name);
  render();
});
async function avSet(j) {
  S.me.avatar = j.avatar || '';
  if (j.avatar) (S.avatars ||= {})[S.me.id] = j.avatar; else if (S.avatars) delete S.avatars[S.me.id];
  const box = $('#a-avpick'); if (box) box.innerHTML = avPickHtml();
  const acct = $('.acct'); if (acct) acct.firstElementChild.outerHTML = av(S.me.id, S.me.display_name);
  render();
}
// photo: square crop (drag to move, slider to zoom), sent as a 512 px JPEG; the server re-encodes it anyway
// 2.24.0 (#825): with a round mask (the corners outside the circle are dimmed, a thin ring shows the edge), a big and a
// small preview (the size of the sidebar), two-finger pinch, the mouse wheel and the keyboard (arrows move, + / - zoom).
// The browser applies the photo's EXIF rotation when it draws it; the server strips EXIF / GPS on the re-encode.
function avCropModal(file, opt = {}) {
  return new Promise(res => {
    // 2.24.0 (#825): a data: URL, not blob: (the Content-Security-Policy allows img-src 'self' data: only; a blob: URL made
    // every photo "cannot be read", so the crop dialog never opened)
    const img = new Image(), fr = new FileReader();
    let url = '';
    img.onerror = () => { toast(tr('This picture cannot be read')); res(null); };
    img.onload = () => {
      const md = modal(`<h3>${esc(opt.title || tr('Profile picture'))}</h3><div class="avcrop"><canvas width="512" height="512" id="av-cv" tabindex="0" role="img" aria-label="${esc(tr('Drag to move the picture, pinch or use + and − to zoom'))}"></canvas>
        <div class="avprev" aria-hidden="true"><canvas width="96" height="96" id="av-pv"></canvas><canvas width="40" height="40" id="av-pv2"></canvas></div></div>
        <div class="row"><label for="av-zoom">${tr('Zoom')}</label><input type="range" id="av-zoom" min="1" max="4" step="0.01" value="1"></div>
        <div class="shint keep">${esc(tr('Move the picture with a finger or the mouse; the circle is what others see.'))}</div>
        <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Use picture')}</button></div>`);
      md.classList.add('avcropmd'); if (opt.square) md.classList.add('sq');
      const cv = $('#av-cv', md), cx = cv.getContext('2d'), side = Math.min(img.width, img.height), zin = $('#av-zoom', md);
      let z = 1, ox = (img.width - side) / 2, oy = (img.height - side) / 2;
      const clamp = () => { const s = side / z; ox = Math.max(0, Math.min(img.width - s, ox)); oy = Math.max(0, Math.min(img.height - s, oy)); };
      const paint = (c, px) => { const s = side / z; clamp(); if (opt.png) c.clearRect(0, 0, px, px); else { c.fillStyle = '#fff'; c.fillRect(0, 0, px, px); } c.drawImage(img, ox, oy, s, s, 0, 0, px, px); };
      const round = (c, px) => { c.save(); c.beginPath(); c.arc(px / 2, px / 2, px / 2, 0, Math.PI * 2); c.clip(); paint(c, px); c.restore(); };
      const draw = () => {
        paint(cx, 512);
        if (!opt.square) {  // the mask: dim outside the circle, a light ring on its edge
          cx.save(); cx.beginPath(); cx.rect(0, 0, 512, 512); cx.arc(256, 256, 252, 0, Math.PI * 2, true); cx.fillStyle = 'rgba(10,12,16,.58)'; cx.fill('evenodd');
          cx.beginPath(); cx.arc(256, 256, 252, 0, Math.PI * 2); cx.lineWidth = 3; cx.strokeStyle = 'rgba(255,255,255,.9)'; cx.stroke(); cx.restore();
        }
        for (const [id, px] of [['#av-pv', 96], ['#av-pv2', 40]]) { const c = $(id, md)?.getContext('2d'); if (c) { c.clearRect(0, 0, px, px); (opt.square ? paint : round)(c, px); } }
      };
      const zoomTo = (nz, fx = .5, fy = .5) => { nz = Math.max(1, Math.min(4, nz)); const s0 = side / z, px = ox + s0 * fx, py = oy + s0 * fy; z = nz; const s1 = side / z; ox = px - s1 * fx; oy = py - s1 * fy; zin.value = z; draw(); };
      draw();
      const pts = new Map(); let drag = null, pinch = null;
      const k = () => side / z / cv.getBoundingClientRect().width;
      cv.addEventListener('pointerdown', e => { pts.set(e.pointerId, {x: e.clientX, y: e.clientY}); cv.setPointerCapture?.(e.pointerId);
        if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = {d: Math.hypot(a.x - b.x, a.y - b.y) || 1, z}; drag = null; } else drag = {x: e.clientX, y: e.clientY, ox, oy}; });
      cv.addEventListener('pointermove', e => { if (!pts.has(e.pointerId)) return; pts.set(e.pointerId, {x: e.clientX, y: e.clientY});
        if (pinch && pts.size === 2) { const [a, b] = [...pts.values()]; zoomTo(pinch.z * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d); return; }
        if (drag) { ox = drag.ox - (e.clientX - drag.x) * k(); oy = drag.oy - (e.clientY - drag.y) * k(); draw(); } });
      const up = e => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) drag = null; else { const p = [...pts.values()][0]; drag = {x: p.x, y: p.y, ox, oy}; } };
      cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
      cv.addEventListener('wheel', e => { e.preventDefault(); const r = cv.getBoundingClientRect(); zoomTo(z * (e.deltaY < 0 ? 1.08 : 1 / 1.08), (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height); }, {passive: false});
      cv.addEventListener('keydown', e => {
        const st = side / z * (e.shiftKey ? .1 : .03), mv = {ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st]}[e.key];
        if (mv) { e.preventDefault(); ox += mv[0]; oy += mv[1]; draw(); return; }
        if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomTo(z * 1.1); } else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomTo(z / 1.1); }
      });
      zin.addEventListener('input', e => zoomTo(+e.target.value));
      const done = v => { url = ''; if (md.isConnected) md.remove(); res(v); };
      onRemove(md, () => done(null));
      md.addEventListener('click', e => {
        const b = e.target.closest('button[data-m]'); if (!b) return;
        if (b.dataset.m === 'close') { done(null); return; }
        const out = document.createElement('canvas'); out.width = out.height = 512; paint(out.getContext('2d'), 512);
        out.toBlob(bl => done(bl), opt.png ? 'image/png' : 'image/jpeg', 0.9);
      });
    };
    fr.onload = () => { url = String(fr.result || ''); img.src = url; };
    fr.onerror = img.onerror;
    fr.readAsDataURL(file);
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
  ['unblock', N_('A task blocking mine was completed'), '', 'deps'],
  ['approval', N_('An agent waits for my approval'), '', 'agents'],
  ['followup', N_('Follow-up day of a task waiting on someone')],
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
// 2.28.0 (#926): the display name comes first and may be anything; the username (login, @mention) is suggested from it
// ("Team Dev AI" -> "team-dev-ai") until typed by hand, and a wrong one gets an error that names the suggestion
const USER_RE = /^[a-z0-9._-]{1,32}$/;
const slugUser = n => String(n || '').toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9._-]+/g, '-').replace(/^[-._]+|[-._]+$/g, '').slice(0, 32);
const userNameBad = v => USER_RE.test(v) ? '' : (slugUser(v) ? tr('Spaces and capitals are not allowed here – did you mean {0}? The display name may be anything.', slugUser(v)) : tr('Username: 1-32 characters a-z, 0-9, dot, dash, underscore'));
// wires a display-name field to a username field: the suggestion follows the name until the username was typed by hand
function userNameFollow(md, nameId, userId, hintId) {
  const nm = $('#' + nameId, md), un = $('#' + userId, md); if (!nm || !un) return;
  un.dataset.auto = un.value ? '' : '1';
  nm.addEventListener('input', () => { if (un.dataset.auto) un.value = slugUser(nm.value); });
  un.addEventListener('input', () => { un.dataset.auto = ''; const h = hintId && $('#' + hintId, md); if (h) { h.textContent = userNameBad(un.value); h.hidden = !h.textContent; } });
}
// the "Groups" part of the share dialog of a list: shared directly (role + remove) or through a folder (read-only here)
function shareGroupsHtml(cur, mng, roleSel) {
  const gs = cur.groups || [], cand = (S.groups || []).filter(g => !gs.some(x => x.group_id === g.id && x.via === 'list'));
  if (!gs.length && !(mng && cand.length)) return '';
  return gs.map(x => `<div class="mrow" data-gsh="${x.group_id}">${fg_gav(x.group_id)}<span class="n">${esc(x.name)}${x.via !== 'list' ? ` <span class="muted">${esc(tr('via the folder {0}', fDisp(x.via)))}</span>` : ''}</span>${mng && x.via === 'list'
    ? `${roleSel(`data-grole="${x.group_id}"`, x.role, tr('Role of the group {0}', x.name))}<button class="iconbtn" data-grm="${x.group_id}" title="${esc(tr('Stop sharing with the group'))}" aria-label="${esc(tr('Stop sharing with the group {0}', x.name))}">${ic('x', 's')}</button>`
    : `<span class="muted" title="${esc(roleHelp(x.role))}">${esc(roleLabel(x.role))}</span>`}</div>`).join('')
    + (mng && cand.length ? `<div class="mrow madd"><select id="l-addgrp" aria-label="${esc(tr('Share with a group'))}"><option value="">${tr('Share with a group …')}</option>${cand.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join('')}</select>${roleSel('id="l-grprole"', 'edit')}<button class="btn sm" data-m="share-grp">${ic('plus', 's')} ${tr('Add')}</button></div>` : '');
}
// 2.41.0 (#1420): sharing a folder with a group is part of the folder's Share dialog (folderShareModal, sharedlg.js)
// 2.22.0 (#752): organisations (admins): name, emoji, members; whom people see (everyone / own organisation / own contacts)
const VIS_UI = [['all', N_('Everyone on this server')], ['org', N_('Only people of their own organisations')], ['contacts', N_('Only people they are connected with (no directory, share by e-mail address)')]];
async function orgsDraw(md) {
  const box = $('#a-orgs', md); if (!box) return;
  let j; try { j = await api('GET', '/api/admin/orgs'); } catch { return; }
  S.orgs = j.orgs;
  box.innerHTML = j.orgs.length ? j.orgs.map(o => `<div class="mrow">${o.icon_url ? orgIconHtml(o) : `<span class="fem" aria-hidden="true">${esc(o.icon || '🏢')}</span>`}<span class="n">${esc(o.name)} <span class="muted">${esc(trn('{0} member', '{0} members', o.members.length))}${(o.admins || []).length ? ' · ' + esc(trn('{0} admin', '{0} admins', o.admins.length)) : ''}${o.domains ? ' · ' + esc(o.domains) : ''}</span></span>${j.editable ? `<button class="iconbtn" data-acc="org-edit" data-oid="${o.id}" title="${esc(tr('Edit organisation'))}" aria-label="${esc(tr('Edit {0}', o.name))}">${ic('edit', 's')}</button>` : ''}${j.creatable ? `<button class="iconbtn danger" data-acc="org-del" data-oid="${o.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete {0}', o.name))}">${ic('trash', 's')}</button>` : ''}</div>`).join('') : `<div class="muted mhint">${tr('No organisation yet.')}</div>`;
  // 2.30.0 (#1036): the nightly boundary check's count (memberships across the boundary between workspaces)
  const bd = j.boundary;
  if (bd && j.orgs.length) box.insertAdjacentHTML('beforeend', oa_boundaryHtml(bd));  // 2.46.0 (#1563): unfoldable, with "Clean up"
  const vs = $('#a-vis', md); if (vs) vs.innerHTML = VIS_UI.map(([k, n]) => `<option value="${k}" ${k === j.visibility ? 'selected' : ''}>${esc(tr(n))}</option>`).join('');
}
// ---- 2.28.0 (#935): Settings > Workspaces -- my organisations; an organisation's admin adds / removes members and sets their
// role (also when not an admin of the server), renames it, sets its e-mail domains
const wsPaneOn = () => wsOn() && !S.me?.kid;
async function wsPaneDraw(md) {
  const box = $('#s-ws', md); if (!box) return;
  let j; try { j = await api('GET', '/api/orgs'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  const mm = Object.keys(j.mismatches || {}).length;
  const org = o => `<details class="sdet wsorg" data-oid="${o.id}" ${j.orgs.length === 1 ? 'open' : ''}><summary>${o.icon_url ? orgIconHtml(o) : `<span class="fem" aria-hidden="true">${esc(o.icon || '🏢')}</span>`}<b>${esc(o.name)}</b> <span class="muted">${esc(trn('{0} member', '{0} members', o.members.length))} · ${esc(trn('{0} list', '{0} lists', o.lists))}${o.role === 'admin' ? ' · ' + esc(tr('you are an admin')) : ''}</span></summary>
    ${o.members.map(m => `<div class="mrow ${m.disabled ? 'off' : ''}">${av(m.id, m.name)}<span class="n">${esc(m.name)}${m.agent ? ' ' + agentBadge() : ''}${m.id === S.me?.id ? ' ' + tr('(me)') : ''}</span>${o.role === 'admin' && j.manage && !m.agent ? `<select data-wsrole="${m.id}" aria-label="${esc(tr('Role of {0}', m.name))}"><option value="member" ${m.role !== 'admin' ? 'selected' : ''}>${tr('Member')}</option><option value="admin" ${m.role === 'admin' ? 'selected' : ''}>${tr('Admin')}</option></select><button class="iconbtn" data-wsrm="${m.id}" title="${esc(m.id === S.me?.id ? tr('Leave the organisation') : tr('Remove from the organisation'))}" aria-label="${esc(m.id === S.me?.id ? tr('Leave the organisation') : tr('Remove {0} from the organisation', m.name))}">${ic('x', 's')}</button>${m.id !== S.me?.id ? `<button class="iconbtn danger" data-wsdel="${m.id}" title="${esc(tr('Delete account'))}" aria-label="${esc(tr('Delete the account of {0}', m.name))}">${ic('trash', 's')}</button>` : ''/* 2.88.0 (#1980) */}` : `<span class="muted">${m.agent ? tr('Agent') : m.role === 'admin' ? tr('Admin') : tr('Member')}</span>`}</div>`).join('')}
    ${o.role === 'admin' && j.manage ? `<div class="row wsadd"><input id="ws-add-${o.id}" type="email" placeholder="${esc(tr('Add by e-mail address'))}" aria-label="${esc(tr('Add by e-mail address'))}" autocomplete="off"><button class="btn sm" data-wsadd="${o.id}">${ic('plus', 's')} ${tr('Add')}</button></div>
    <div class="row"><label for="ws-name-${o.id}">${tr('Name')}</label><input id="ws-name-${o.id}" value="${esc(o.name)}" maxlength="60"><label for="ws-dom-${o.id}">${tr('E-mail domains')}</label><input id="ws-dom-${o.id}" value="${esc(o.domains || '')}" placeholder="example.com"><button class="btn sm" data-wssave="${o.id}">${tr('Save')}</button></div>` : ''}
    ${o.role === 'admin' && j.manage ? `<div class="row wsic"><label>${tr('Symbol')}</label><span class="wsicprev">${orgIconHtml(o)}</span><button type="button" class="btn sm" data-wsic="up">${ic('picture', 's')} ${tr('Upload a picture…')}</button>${o.icon_url ? `<button type="button" class="btn sm" data-wsic="rm">${tr('Remove the picture')}</button>` : ''}</div>` : ''}${''/* 2.87.9 (#1913) */}
    ${o.role === 'admin' ? `<div class="row"><button type="button" class="btn sm" data-oadm="${o.id}">${ic('list', 's')} ${tr('Lists of the organisation')}</button></div>` : ''}
    ${o.role === 'admin' ? ocBoxHtml(o) : ''}${''/* 2.42.0 (#828): encryption + recovery key */}
    ${o.role === 'admin' ? oxBoxHtml(o) : ''}
    ${o.role === 'admin' ? whoBoxHtml(o) : ''}${''/* 2.115.0 A (#2061): the organisation's webhooks */}
    ${o.role !== 'admin' || !j.manage ? `<div class="row"><button class="btn sm" data-wsrm="${S.me?.id}" data-oidx="${o.id}">${ic('logout', 's')} ${tr('Leave the organisation')}</button></div>` : ''}</details>`;
  box.innerHTML = (j.orgs.length ? j.orgs.map(org).join('') : `<div class="muted mhint">${tr('You belong to no organisation: everything is private.')}</div>`)
    + (mm ? `<div class="shint keep">${ic('alert', 's')} ${esc(trn('{0} list of yours has an agent of another workspace (from before the workspaces). Open the list’s Share dialog to take it out or keep it.', '{0} lists of yours have an agent of another workspace (from before the workspaces). Open the lists’ Share dialogs to take it out or keep it.', mm))}</div>` : '');
  if (!S.me?.kid) box.insertAdjacentHTML('beforeend', `<div class="ocorg">${ocBoxHtml({id: 0}, {title: `${tr('Your personal office')}: ${tr('Encryption')}`})}</div>`);  // 2.138.0 C (#1972): its recovery key (hidden without encrypted data)
  oxDraw(box);  // 2.42.0 (#833): the export sections of the organisations I administer
  whoDraw(box);  // 2.115.0 A (#2061): their webhooks
  ocDraw(box);  // 2.42.0 (#828): their encryption sections
  wsc_paneDraw(box);  // 2.53.0 (#1474): each organisation's colour (its admins choose)
  pmeta_paneDraw(box);  // 2.61.0 B (#1819): whether photos lose their metadata on upload (its admins choose)
  if (typeof xl_paneDraw === 'function') xl_paneDraw(box);  // 2.112.1 B (#2058): external share links of its files allowed
  if (typeof oinvDraw === 'function') oinvDraw(box);  // 2.115.0 B (#2062): invite by e-mail + the open invitations
}
function wsPaneWire(md) {
  md.addEventListener('change', async e => {
    const r = e.target.dataset?.wsrole; if (!r) return;
    const oid = +e.target.closest('[data-oid]').dataset.oid;
    try { await api('PUT', `/api/orgs/${oid}/members`, {user_id: +r, role: e.target.value}); toast(tr('Saved')); } catch { /* shown */ }
    wsPaneDraw(md);
  });
  md.addEventListener('click', async e => {
    const oa = e.target.closest('[data-oadm]');
    if (oa) { const o = (($('#s-ws', md)._j || {}).orgs || []).find(x => x.id === +oa.dataset.oadm); oadmOpen(+oa.dataset.oadm, o?.name || ''); return; }  // 2.35.0 (#1101)
    const wi = e.target.closest('[data-wsic]');
    if (wi) { wsIconPick(md, +wi.closest('[data-oid]').dataset.oid, wi.dataset.wsic); return; }  // 2.87.9 (#1913)
    const wd = e.target.closest('[data-wsdel]');
    if (wd) {  // 2.88.0 (#1980): an organisation admin deletes an account of only this organisation (else: remove, lists to a member)
      const o = (($('#s-ws', md)._j || {}).orgs || []).find(x => x.id === +wd.closest('[data-oid]').dataset.oid), m = o?.members.find(x => x.id === +wd.dataset.wsdel);
      const r = m && await ua8_delete({id: m.id, display_name: m.name});
      if (r) { if (r === true) toast(tr('Deleted')); await load(); render(); wsPaneDraw(md); }
      return;
    }
    const b = e.target.closest('[data-wsadd],[data-wsrm],[data-wssave]'); if (!b) return;
    const oid = +(b.dataset.oidx || b.closest('[data-oid]')?.dataset.oid || 0);
    try {
      if (b.dataset.wsadd) { const em = $('#ws-add-' + oid, md).value.trim(); if (!em) return; const r = await api('PUT', `/api/orgs/${oid}/members`, {email: em}); toast(r.by_email ? tr('If this address has an account, the person is now a member.') : tr('Added')); }
      else if (b.dataset.wssave) { await api('PATCH', `/api/orgs/${oid}`, {name: $('#ws-name-' + oid, md).value.trim(), domains: $('#ws-dom-' + oid, md).value}); toast(tr('Saved')); }
      else if (b.dataset.wsrm) {
        const uid = +b.dataset.wsrm, self = uid === S.me?.id, o = (($('#s-ws', md)._j || {}).orgs || []).find(x => x.id === oid), m = o?.members.find(x => x.id === uid);
        if (!await askConfirm(self ? tr('Leave the organisation “{0}”?', o?.name || '') : tr('Remove {0} from the organisation?', m?.name || ''), self ? tr('Your lists of this workspace go to one of its admins and you leave every list of the organisation.') : tr('The person’s lists of this workspace come to you and the person leaves every list of the organisation.'), {ok: self ? tr('Leave') : tr('Remove'), danger: true})) return;
        await api('DELETE', `/api/orgs/${oid}/members/${uid}`); toast(self ? tr('You left the organisation') : tr('Removed'));
      }
      await load(); render();
    } catch { /* api() showed it */ }
    wsPaneDraw(md);
  });
}
// 2.87.9 (#1913): an organisation admin sets an own picture as its symbol (cropped square like a list icon) or removes it
async function wsIconPick(md, oid, how) {
  const done = async () => { toast(tr('Saved')); await load(); render(); wsPaneDraw(md); };
  if (how === 'rm') { try { await api('DELETE', `/api/orgs/${oid}/icon`); await done(); } catch { /* api() showed it */ } return; }
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
  inp.addEventListener('change', async () => {
    const f = inp.files?.[0]; if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
    const bl = await avCropModal(f, {title: tr('Symbol'), png: true, square: true}); if (!bl) return;
    const fd = new FormData(); fd.append('file', bl, 'icon.png');
    try { await api('POST', `/api/orgs/${oid}/icon`, fd); await done(); } catch { /* api() showed it */ }
  });
  inp.click();
}
// ---- 2.35.0 (#1101): an organisation admin's "Lists of the organisation": the lists that belong to the organisation (never
// private lists, private sharing or inboxes) with owner, numbers and the last change - never their contents. Archive / restore,
// hand over to another person of the organisation, delete for good from the archive (the name typed to confirm); a history.
const OADM_ACT = {archive: N_('{0} archived {1}'), restore: N_('{0} restored {1}'), delete: N_('{0} deleted {1} for good'), trash: N_('{0} moved {1} to the trash'), undelete: N_('{0} restored {1} from the trash'), purge: N_('{0} deleted {1} for good'), owner: N_('{0} handed {1} to {2}'),
  edit: N_('{0} changed {1}'), icon: N_('{0} changed the icon of {1}')};  // 2.56.0 (#1795)
function oadmRow(x) {
  const sub = [x.owner_agent ? tr('Owner: {0} (agent)', x.owner_name) : tr('Owner: {0}', x.owner_name), tr('{0} open', x.open) + ' / ' + trn('{0} task', '{0} tasks', x.tasks),
    trn('{0} member', '{0} members', x.members), tr('changed {0}', fmtDateLoc(String(x.changed_at || '').slice(0, 10)) || '–'), x.folder && tr('Folder: {0}', fDisp(x.folder))].filter(Boolean);  // 2.39.1 (#1188): + folder path
  return `<div class="mrow oadmrow ${x.archived ? 'off' : ''}" data-olid="${x.id}"><span class="n"><b>${ole_mark(x)}${esc(x.name)}</b>${x.archived ? ` <span class="muted">${esc(tr('archived'))}</span>` : ''}<small class="muted">${esc(sub.join(' · '))}</small></span>
    <span class="oadmb">${x.archived ? `<button type="button" class="btn sm" data-oa="restore">${tr('Restore')}</button><button type="button" class="btn sm danger" data-oa="delete">${tr('Delete…')}</button>`
      : `<button type="button" class="btn sm" data-oa="edit">${tr('Edit')}</button><button type="button" class="btn sm" data-oa="archive">${tr('Archive')}</button>`}<button type="button" class="btn sm" data-oa="owner">${tr('Hand over…')}</button></span></div>`;  // 2.56.0 (#1795): + Edit
}
function oadmDraw(md, j) {
  md._j = j;
  const live = j.lists.filter(x => !x.archived), arch = j.lists.filter(x => x.archived);
  // 2.39.1 (#1188): grouped by owner (listadmin.js)
  $('#oadm-body', md).innerHTML = (j.lists.length ? `${lmOadmBody({lists: live}, oadmRow)}${arch.length ? `<h4 class="oadmh">${esc(tr('Archive'))}</h4>${lmOadmBody({lists: arch}, oadmRow)}` : ''}`
    : `<div class="muted mhint">${tr('The organisation has no lists yet.')}</div>`)
    + (j.log.length ? `<details class="sdet oadmlog"><summary>${tr('History')} <span class="muted">${j.log.length}</span></summary>${j.log.filter(r => OADM_ACT[r.action]).map(r => `<div class="mrow"><span class="n">${tr(OADM_ACT[r.action], `<b>${esc(r.by || '?')}</b>`, `<b>${esc(r.list_name)}</b>`, `<b>${esc(r.to || '')}</b>`)}<small class="muted">${esc(fmtWhen(r.at))}${r.owner && r.action !== 'owner' ? ' · ' + esc(tr('Owner: {0}', r.owner)) : ''}${ole_logDetail(r)}</small></span></div>`).join('')}</details>` : '');
}
async function oadmOpen(oid, name) {
  const md = modal(`<h3>${esc(tr('Lists of the organisation {0}', name))}</h3>
    <div class="shint keep">${tr('The lists of the organisation that are shared with at least one more person, with names and numbers: their contents stay with their people. Private lists stay invisible, also when they are shared.')}</div>
    <div class="shint lmohint">${ic('info', 's')} ${tr('A list is missing? It is probably private and only shared. Its owner can move it into the organisation: list menu > Edit list… > Workspace.')}</div>
    <div class="members oadm" id="oadm-body"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('oadmmd');
  try { oadmDraw(md, await api('GET', `/api/orgs/${oid}/lists`)); } catch { $('#oadm-body', md).innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; }
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-m="close"]')) { md.remove(); return; }
    const b = e.target.closest('[data-oa]'); if (!b) return;
    const x = (md._j?.lists || []).find(l => l.id === +b.closest('[data-olid]').dataset.olid); if (!x) return;
    const k = b.dataset.oa, base = `/api/orgs/${oid}/lists/${x.id}`;
    if (k === 'edit') { ole_edit(md, oid, x); return; }  // 2.56.0 (#1795)
    try {
      let j = null;
      if (k === 'archive') {
        if (!await askConfirm(tr('Archive “{0}”?', x.name), tr('The list leaves the sidebar of everyone in it; nothing is deleted. {0} and the members are told. You or the owner can restore it.', x.owner_name), {ok: tr('Archive')})) return;
        j = await api('POST', base + '/archive', {archived: true}); toast(tr('Archived'));
      } else if (k === 'restore') { j = await api('POST', base + '/archive', {archived: false}); toast(tr('Restored')); }
      else if (k === 'delete') {
        const v = await askDialog({title: x.e2e ? tr('Delete “{0}” permanently?', x.name) : tr('Delete “{0}”?', x.name), danger: true, ok: x.e2e ? tr('Delete permanently') : tr('Delete'),  // 2.102.0 A (#1988): the organisation's list trash
          html: `<p>${esc(x.e2e ? tr('This cannot be undone. Its tasks go to the trash in the basket of {0} and can be restored from there; its files and the sharing are lost. {0} and the members are told.', x.owner_name) : otr_orgNote(x.owner_name))}</p><p>${esc(tr('Type the name of the list to delete it'))}</p>`,
          input: {placeholder: x.name, max: 200}});
        if (v === null) return;
        if (v.trim() !== x.name.trim()) { toast(tr('The name does not match: nothing was deleted')); return; }
        j = await api('DELETE', base, {confirm: v.trim()});
        if (j?.trash) otr_offerUndo(x.id, x.name); else toast(tr('Deleted'));
      } else if (k === 'owner') {
        const ps = (md._j.people || []).filter(p => p.id !== x.owner_id);
        if (!ps.length) { toast(tr('Nobody else in the organisation to hand it to')); return; }
        const sel = `<label for="oadm-to">${esc(tr('New owner'))}</label><select id="oadm-to">${ps.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select>`;
        let to = 0;
        const okd = askDialog({title: tr('Hand “{0}” over', x.name), ok: tr('Hand over'), html: `<p>${esc(tr('{0} stays in the list as its admin. The new owner manages its sharing from now on.', x.owner_name))}</p><div class="row">${sel}</div>`});
        setTimeout(() => { const s0 = $('#oadm-to'); if (s0) { to = +s0.value; s0.addEventListener('change', () => { to = +s0.value; }); } }, 0);
        if (!await okd) return;
        j = await api('POST', base + '/owner', {user_id: to}); toast(tr('Handed over'));
      }
      if (j) oadmDraw(md, j);
      await load(); render();
    } catch { /* api() showed it */ }
  });
}
// ---- 2.56.0 (#1795): an organisation admin changes the name (with its emoji), the icon and the colour of a list of the
// organisation -- nothing else, never its contents (PATCH /api/orgs/{id}/lists/{id}, .../icon). The same pickers as the list
// dialog; Save = one undo step (name / colour), a picture is set at once like in the list dialog. The owner and the members
// are told by the server.
const ole_mark = x => x.icon ? `<img class="licon ole-ic" src="${esc(x.icon)}" alt="" loading="lazy" decoding="async">`
  : x.color ? `<i class="ole-sw" style="background:${cssColor(lp_col({color: x.color}) || x.color)}" aria-hidden="true"></i>` : '';
function ole_logDetail(r) {
  const d = r.detail || {}, out = [];
  if (d.name) out.push(tr('Name: {0} → {1}', d.name[0], d.name[1]));
  if (d.color) out.push(d.color[1] ? tr('new colour') : tr('colour removed'));
  if (d.icon) out.push(d.icon[1] === 'picture' ? tr('own picture') : d.icon[1] ? tr('preset picture') : tr('picture removed'));
  return out.length ? ' · ' + esc(out.join(' · ')) : '';
}
function ole_edit(om, oid, x) {
  const base = `/api/orgs/${oid}/lists/${x.id}`;
  let m0 = x.name.match(EMO_RE);
  let emo = m0 ? m0[1] : '';
  const nm0 = m0 ? x.name.slice(m0[0].length) : x.name, col0 = lp_col({color: x.color});
  const pick = () => `<span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(x)}`;
  const emoBtn = () => x.icon ? licon(x, 'licon m') : sbiEmo(emo) || ic('list');
  const md = modal(`<h3>${esc(tr('Edit “{0}”', x.name))}</h3>
    <div class="shint keep">${esc(tr('Only the name, the icon and the colour: the contents stay with the people of the list. {0} and the members are told.', x.owner_name || '?'))}</div>
    <div class="row"><label for="ole-name">${tr('Name')}</label><button type="button" class="emobtn" id="ole-emo" title="${tr('Choose icon')}" aria-label="${tr('Choose icon')}">${emoBtn()}</button><input id="ole-name" value="${esc(nm0)}" maxlength="200"></div>
    <div class="emogrid hidden" id="ole-emogrid"><button type="button" data-emo="" class="none" title="${tr('No icon')}">${ic('ban', 's')}</button>${sbiGrid().map(e => `<button type="button" data-emo="${e}" class="${e === emo && !x.icon ? 'on' : ''}">${sbiEmo(e)}</button>`).join('')}
      <div class="lipickw">${pick()}</div></div>
    <div class="row"><label>${tr('Color')}</label><div class="colors" id="ole-col" role="group" aria-label="${esc(tr('Color'))}">${lp_dlgBtns(col0)}</div></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="cancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('olemd');
  const redraw = j => { if (j && om.isConnected) oadmDraw(om, j); };
  const iconSet = async how => {  // like liconSet, through the organisation's route; the emoji leaves the name with a picture
    let j;
    try {
      if (how === 'none') j = await api('DELETE', base + '/icon');
      else if (how instanceof Blob) { const fd = new FormData(); fd.append('file', how, 'icon.png'); j = await api('POST', base + '/icon', fd); }
      else j = await api('PUT', base + '/icon', {preset: how});
    } catch { return; }
    x.icon = j.icon || ''; redraw(j);
    if (x.icon && emo && m0 && x.name.startsWith(m0[0])) {  // the emoji leaves the name at once (as in the list dialog)
      const nm = x.name.slice(m0[0].length).trim() || nm0;
      try { redraw(await api('PATCH', base, {name: nm})); x.name = nm; m0 = null; } catch { /* api() said why */ }
    }
    if (x.icon) { emo = ''; $$('#ole-emogrid [data-emo]', md).forEach(y => y.classList.remove('on')); $('#ole-emogrid', md).classList.add('hidden'); }
    $('#ole-emo', md).innerHTML = emoBtn(); $('.lipickw', md).innerHTML = pick();
  };
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'cancel') { md.remove(); return; }
    if (b.id === 'ole-emo') { $('#ole-emogrid', md).classList.toggle('hidden'); return; }
    if (b.dataset.c !== undefined) { $$('#ole-col button', md).forEach(y => { y.classList.toggle('on', y === b); y.setAttribute('aria-pressed', String(y === b)); }); return; }
    if (b.dataset.licon) {
      const k = b.dataset.licon;
      if (k !== 'upload') { await iconSet(k); return; }
      const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
      inp.addEventListener('change', async () => {
        const f = inp.files?.[0]; if (!f) return;
        if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
        const bl = await avCropModal(f, {title: tr('List icon'), png: true, square: true}); if (bl) await iconSet(bl);
      });
      inp.click(); return;
    }
    if (b.dataset.emo !== undefined) {
      if (x.icon && b.dataset.emo) await iconSet('none');  // an emoji replaces the picture
      emo = b.dataset.emo;
      $$('#ole-emogrid [data-emo]', md).forEach(y => y.classList.toggle('on', y === b && !!emo));
      $('#ole-emo', md).innerHTML = emoBtn(); $('#ole-emogrid', md).classList.add('hidden');
      return;
    }
    if (b.dataset.m !== 'save') return;
    const nm = $('#ole-name', md).value.trim();
    if (!nm) { toast(tr('Name missing')); $('#ole-name', md).focus(); return; }
    const name = emo === (m0 ? m0[1] : '') && nm === nm0 ? x.name : (x.icon ? '' : emo) + nm, c = $('#ole-col button.on', md)?.dataset.c ?? col0;
    const before = {}, after = {};
    if (name !== x.name) { before.name = x.name; after.name = name; }
    if (c !== col0) { before.color = x.color || ''; after.color = lp_keep(x, c); }
    if (!Object.keys(after).length) { md.remove(); return; }
    const put = v => async () => { const j = await api('PATCH', base, v); redraw(j); await load().catch(() => {}); render(); };
    try { await put(after)(); } catch { return; }  // api() said why
    md.remove();
    offerUndo(tr('Saved'), histAdd({label: tr('List “{0}” changed', after.name || x.name), undo: put(before), redo: put(after)}));
  });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'ole-name') { e.preventDefault(); $('[data-m="save"]', md).click(); } });
  if (!isTouch()) setTimeout(() => $('#ole-name', md).focus(), 50);
  return md;
}
// 2.49.0 (#1553): the login page's backdrop (a soft violet gradient + a glow that pulses in CSS and follows the mouse: one
// frame per movement, no loop; fixed on touch screens and with reduced motion) and the line under the card (survive innerHTML)
function lg_decor(el) {
  el.dataset.lgfoot = tr('Tasks, team and office in one place.');
  if (!matchMedia('(hover: hover) and (pointer: fine)').matches || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  let x = 0, y = 0, f = 0;
  el.addEventListener('pointermove', e => {
    x = e.clientX; y = e.clientY;
    if (!f) f = requestAnimationFrame(() => { f = 0; el.style.setProperty('--lgx', x + 'px'); el.style.setProperty('--lgy', y + 'px'); });
  }, {passive: true});
}
function lg_hello() {
  const h = new Date().getHours();
  return h >= 5 && h < 11 ? tr('Good morning, nice to have you here.') : h >= 18 || h < 5 ? tr('Good evening, nice to have you here.') : tr('Welcome back, nice to have you here.');
}
// 2.22.0 (#697): the page "Set up your account" (the link of an invitation or a password reset: /#invite/<token>)
async function inviteScreen(tok) {
  history.replaceState(null, '', location.pathname);  // the token leaves the address bar (and the history) at once
  let info = null;
  try { const r = await fetch('/api/auth/invite/check', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({token: tok})}); info = await r.json(); if (!r.ok) info = {error: info.error || tr('Error {0}', r.status)}; } catch { info = {error: tr('Server not reachable.')}; }
  await i18nLoad(info.lang || uiLang());
  const el = document.createElement('div');
  el.className = 'modal authscreen';
  lg_decor(el);  // 2.49.0 (#1553)
  const logo = `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div>`;
  if (info.error) {
    el.innerHTML = `<div class="card">${logo}<p role="alert">${esc(info.error)}</p><button class="btn pri" type="button" data-au="login">${tr('To the login')}</button></div>`;
  } else {
    el.innerHTML = `<div class="card">${logo}
      <h2 class="invh">${esc(info.kind === 'reset' ? tr('Set a new password') : info.kind === 'signup' ? tr('Confirm your registration') : tr('Welcome, {0}!', info.display_name))}</h2>
      <p class="muted">${esc(info.kind === 'reset' ? tr('Choose a new password for “{0}”.', info.username) : tr('Choose your own password to finish your account.'))}</p>
      <form id="inv-form" autocomplete="on">
        <label class="aulab" for="inv-user">${tr('Username')}</label><input id="inv-user" name="username" autocomplete="username" readonly value="${esc(info.username)}">
        <label class="aulab" for="inv-pw">${tr('New password')}</label><input id="inv-pw" type="password" autocomplete="new-password" required minlength="${info.min_password || 8}" placeholder="${esc(tr('at least {0} characters', info.min_password || 8))}">
        <label class="aulab" for="inv-pw2">${tr('Repeat the password')}</label><input id="inv-pw2" type="password" autocomplete="new-password" required>
        <label class="chkl"><input type="checkbox" id="inv-2fa"> ${tr('Set up two-factor sign-in right after (recommended)')}</label>
        <div class="aerr" role="alert" id="inv-err"></div>
        <button class="btn pri" type="submit">${info.kind === 'reset' ? tr('Save and log in') : tr('Set up my account')}</button>
        ${info.kind === 'reset' ? `<p class="muted">${esc(tr('App passwords (CalDAV) and API tokens stay valid. If someone else may have had access, check them under Settings > Account (API tokens: Advanced · for developers).'))}</p>` : ''}${''/* 2.58.0 (#1792): L3, a hint only -- nothing is revoked */}
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
        if (res.twofa) { await authTwofa(el, logo, res.methods || ['totp']); return; }  // 2.49.0 (#1531): two-factor stays required after a reset
        if (res.enrol) { await authEnrol(el, logo); return; }
        if (res.pending) { $('.card', el).innerHTML = `${logo}<h2 class="invh">${tr('Thank you!')}</h2><p role="status">${tr('Your account waits for an admin to approve it. You can log in once it is approved.')}</p><button class="btn pri" type="button" data-au="login">${tr('To the login')}</button>`; return; }  // 2.23.0 (#711)
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
  if (kd_pinNeed()) return kd_pinAsk(logout);  // 2.49.0 (#1551): a child with the parents' PIN
  if (OUT.q.length && !await askConfirm(trn('{0} change is not synced yet and will be lost. Log out anyway?', '{0} changes are not synced yet and will be lost. Log out anyway?', OUT.q.length), '', {ok: tr('Log out'), danger: true})) return;
  await wpDisable().catch(() => {});  // this device stops getting the pushes of the account that logs out
  await e2eForget();  // 2.42.0 (#828): keys remembered on this device go
  try { await fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}); } catch { /* offline */ }
  try { for (const k of await caches.keys()) await caches.delete(k); } catch { /* no Cache Storage */ }  // 2.126.0 D (#1992 O4): the app loads again from the server
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
  lg_decor(el);  // 2.49.0 (#1553)
  // 2.14.0: the first account (welcome) shows the figure instead of the small mark (2.136.0, #2193: the bot, happy eyes)
  const logo = kind === 'setup' ? `<div class="alogo hwelc">${botFig('erledigt', 'hwel')}<b>${wordSvg()}</b></div>` : `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b>${info.org ? `<small class="aorg">${esc(info.org)}</small>` : ''}</div>`;  // 2.22.0 (#752): the organisation
  if (kind === 'no_account' || kind === 'disabled') {
    el.innerHTML = `<div class="card">${logo}<p>${kind === 'disabled' ? esc(tr('The account “{0}” is disabled.', j.login || '')) : esc(tr('There is no {0} account for “{1}” yet.', APP_NAME, j.login || ''))}</p><p class="muted">${tr('Please ask the admin to create one (or to enable it).')}</p></div>`;
  } else {
    const setup = kind === 'setup';
    el.innerHTML = `<div class="card">${logo}
      ${setup ? '' : `<p class="lghello">${esc(lg_hello())}</p>`}${''/* 2.49.0 (#1553) */}
      ${setup ? `<p>${tr('Welcome! Create the first account, it becomes the admin.')}</p>${info.login ? `<p class="muted">${esc(tr('Signed in at the login proxy as “{0}”: the account is linked to it, a password is optional.', info.login))}</p>` : ''}` : ''}
      <form id="auth-form" autocomplete="on">
        ${setup && info.setup_code ? `<label class="aulab" for="au-code">${tr('Setup code')}</label><input id="au-code" autocapitalize="off" autocomplete="one-time-code" spellcheck="false" required aria-describedby="au-code-h"><div class="shint shcode" id="au-code-h">${tr('The server prints it into its log at start: {0}', '<code>docker compose logs kalmido</code>')}</div>` : ''}${''/* 2.45.0 (#1515) */}
        <label class="aulab" for="au-user">${tr('Username')}</label><input id="au-user" name="username" autocapitalize="off" autocomplete="username" required value="${setup && info.login ? esc(String(info.login).toLowerCase()) : ''}">
        ${setup ? `<label class="aulab" for="au-name">${tr('Display name')}</label><input id="au-name" maxlength="60" autocomplete="name" placeholder="${tr('optional')}">` : ''}
        <label class="aulab" for="au-pw">${tr('Password')}</label><span class="pwwrap"><input id="au-pw" name="password" type="password" autocomplete="${setup ? 'new-password' : 'current-password'}" ${setup && info.login ? '' : 'required'} ${setup ? `placeholder="${tr('at least {0} characters', 8)}"` : ''}><button type="button" class="iconbtn pweye" data-au="pwshow" aria-pressed="false" aria-label="${esc(tr('Show password'))}" title="${esc(tr('Show password'))}">${ic('eye', 's')}</button></span>
        ${setup ? '' : `<div class="lgopts"><label class="chkl"><input type="checkbox" id="au-rem" checked> ${tr('Stay logged in')}</label>${info.forgot ? `<button type="button" class="linkbtn lgforgot" data-au="forgot">${tr('Forgot your password?')}</button>` : ''}</div>`}${''/* 2.49.0 (#1531, #1553): one row */}
        <div class="aerr" role="alert" id="au-err"></div>
        <button class="btn pri" type="submit">${setup ? tr('Create account') : tr('Log in')}</button>
        ${!setup && (info.oidc || (info.passkey_login && pkSupported())) ? `<div class="aor"><span>${tr('or')}</span></div>` : ''}
        ${!setup && info.oidc ? `<button type="button" class="btn" data-au="oidc">${ic('link', 's')} ${esc(tr('Log in with {0}', info.oidc.label))}</button>` : ''}
        ${!setup && info.passkey_login && pkSupported() ? `<button type="button" class="btn" data-au="passkey">${ic('key', 's')} ${tr('Log in with a passkey')}</button>` : ''}
        ${!setup && info.signup ? `<p class="aulink">${tr('New here?')} <button type="button" class="linkbtn" data-au="signup">${tr('Create account')}</button></p>` : ''}
      </form></div>`;
    const le = (location.hash.match(/login-error=([a-z_]+)/) || [])[1];
    if (le) { $('#au-err', el).textContent = (info.login_errors || {})[le] || (info.login_errors || {}).failed || le; history.replaceState(null, '', location.pathname); }
    el.addEventListener('click', e => {
      const b = e.target.closest('[data-au]'); if (!b) return;
      const rem = $('#au-rem', el)?.checked !== false;
      if (b.dataset.au === 'oidc') location.href = '/api/auth/oidc/start?remember=' + (rem ? 1 : 0);
      if (b.dataset.au === 'passkey') authPasskey($('#au-err', el), rem);
      if (b.dataset.au === 'signup') signupScreen(el, logo, info);  // 2.23.0 (#711)
      if (b.dataset.au === 'forgot') lg_forgotScreen(el, logo, $('#au-user', el).value.trim());  // 2.49.0 (#1531)
      if (b.dataset.au === 'back') { el.remove(); $('#app')?.removeAttribute('inert'); authScreen(j); }
      if (b.dataset.au === 'pwshow') { const i = $('#au-pw', el), on = i.type === 'password'; i.type = on ? 'text' : 'password'; b.setAttribute('aria-pressed', String(on)); i.focus(); }  // 2.13.0 (#453 P7)
    });
    el.querySelector('#auth-form').addEventListener('submit', async e => {
      e.preventDefault();
      const errEl = $('#au-err', el);
      const body = setup ? {username: $('#au-user', el).value.trim(), display_name: $('#au-name', el).value.trim(), password: $('#au-pw', el).value, wizard: true, lang: I18N.code || 'en', ...($('#au-code', el) ? {setup_code: $('#au-code', el).value.trim()} : {})}  // 2.24.0 (UX-22): the language seen here sticks
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
  setTimeout(() => ($('#au-code', el) || $('#au-user', el))?.focus(), 50);
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
// ---- 2.23.0 (#711): registration on the login page (admins): the mode and the e-mail domains
const SIGNUP_UI = [['off', N_('Off: only admins add people')], ['domain', N_('Only addresses of certain e-mail domains')], ['approval', N_('Anyone, after an admin approves')], ['open', N_('Anyone with a confirmed e-mail address')]];
function signupAdminHtml(a) {
  const mode = a.signup_mode || 'off', org = !!a.has_orgs;  // 2.46.0 (#1592): any server with an organisation
  const dis = k => (k === 'domain' || k === 'open') && !a.mail_out ? 'disabled' : k === 'open' && org ? 'disabled' : '';
  return `<h4 id="s-signup-h">${tr('Registration on the login page')}</h4>
    <div class="row"><label for="s-signup">${tr('Who can register')}</label><select id="s-signup">${SIGNUP_UI.map(([k, n]) => `<option value="${k}" ${k === mode ? 'selected' : ''} ${dis(k)}>${esc(tr(n))}</option>`).join('')}</select></div>
    <div class="row" id="s-sdomrow" ${mode === 'domain' ? '' : 'hidden'}><label for="s-sdom">${tr('E-mail domains')}</label><input id="s-sdom" value="${esc(a.signup_domains || '')}" placeholder="example.com, example.org" autocapitalize="off"></div>
    <div class="shint">${esc([tr('New people confirm their address with a link (or wait for an admin), choose their password and start without access to lists: share lists with them. Never an admin or a child account.'),
      a.mail_out ? '' : tr('Without e-mail sending (SMTP) only “after an admin approves” works.'), org ? tr('This server has organisations: open registration is not possible (only their e-mail domains or with approval).') : ''].filter(Boolean).join(' '))}</div>
    <label class="wide"><input type="checkbox" id="s-oinv" ${a.org_invites !== false ? 'checked' : ''}><span>${tr('Organisation admins may invite new people by e-mail')}<small class="muted">${tr('They get an account in that organisation and an e-mail to choose a password. Off: only admins of the server create accounts.')}</small></span></label>`;  // 2.115.0 B (#2062)
}
document.addEventListener('change', async e => {
  const id = e.target.id; if (id !== 's-signup' && id !== 's-sdom' && id !== 's-oinv') return;
  try {
    const j = await api('PATCH', '/api/admin/settings', id === 's-signup' ? {signup_mode: e.target.value} : id === 's-oinv' ? {org_invites: e.target.checked} : {signup_domains: e.target.value});  // 2.115.0 B (#2062): + s-oinv
    if (j && j.version) S.about = j;
    const r = $('#s-sdomrow'); if (r) r.hidden = (S.about?.signup_mode || 'off') !== 'domain';
    if (id === 's-sdom') e.target.value = S.about?.signup_domains || '';
    toast(tr('Saved'));
  } catch { if (id === 's-signup') e.target.value = S.about?.signup_mode || 'off'; }
});
// the form "Create account" on the login page (#711)
// 2.49.0 (#1531): "Forgot your password?": e-mail address or user name -> a one-time link by mail (the answer is always the same)
function lg_forgotScreen(el, logo, pre = '') {
  el.innerHTML = `<div class="card">${logo}
    <h2 class="invh">${tr('Forgot your password?')}</h2>
    <p class="muted">${tr('Enter the e-mail address or user name of your account. We send a link to set a new password to the address stored for it.')}</p>
    <form id="fg-form" autocomplete="on">
      <label class="aulab" for="fg-login">${tr('E-mail or user name')}</label><input id="fg-login" name="username" autocomplete="username" autocapitalize="off" spellcheck="false" maxlength="200" required value="${esc(pre)}">
      <div class="aerr" role="alert" id="fg-err"></div>
      <button class="btn pri" type="submit">${tr('Send the link')}</button>
      <button class="linkbtn" type="button" data-au="back">${tr('Back to the login')}</button>
    </form></div>`;
  el.querySelector('#fg-form').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = $('#fg-err', el), btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
      const r = await fetch('/api/auth/forgot', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({login: $('#fg-login', el).value.trim()})});
      const res = await r.json().catch(() => ({}));
      if (!r.ok) { errEl.textContent = res.error || tr('Error {0}', r.status); btn.disabled = false; return; }
      $('.card', el).innerHTML = `${logo}<h2 class="invh">${tr('Check your e-mail')}</h2><p role="status" class="lgsent">${tr('If an account with a stored e-mail address matches, a link to set a new password is on its way.')}</p><p class="muted">${tr('No mail after a few minutes? Look in the spam folder or ask an admin.')}</p><button class="btn" type="button" data-au="back">${tr('Back to the login')}</button>`;
    } catch { errEl.textContent = tr('Server not reachable.'); btn.disabled = false; }
  });
  setTimeout(() => $('#fg-login', el)?.focus(), 50);
}
function signupScreen(el, logo, info) {
  const pw = !!info.signup?.password;
  el.innerHTML = `<div class="card">${logo}
    <h2 class="invh">${tr('Create account')}</h2>
    <p class="muted">${esc(info.signup?.mode === 'approval' ? tr('An admin approves new accounts before the first login.') : tr('You get an e-mail with a link to confirm your address and choose your password.'))}</p>
    <form id="su-form" autocomplete="on">
      <label class="aulab" for="su-name">${tr('Your name')}</label><input id="su-name" name="name" autocomplete="name" maxlength="60" required>
      <label class="aulab" for="su-mail">${tr('E-mail')}</label><input id="su-mail" name="email" type="email" autocomplete="email" autocapitalize="off" required>
      ${pw ? `<label class="aulab" for="su-pw">${tr('Password')}</label><input id="su-pw" type="password" autocomplete="new-password" minlength="${info.signup.min_password || 8}" required placeholder="${esc(tr('at least {0} characters', info.signup.min_password || 8))}">` : ''}
      <div class="aerr" role="alert" id="su-err"></div>
      <button class="btn pri" type="submit">${tr('Create account')}</button>
      <button class="linkbtn" type="button" data-au="back">${tr('Back to the login')}</button>
    </form></div>`;
  el.querySelector('#su-form').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = $('#su-err', el);
    try {
      const r = await fetch('/api/auth/signup', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'},
        body: JSON.stringify({name: $('#su-name', el).value.trim(), email: $('#su-mail', el).value.trim(), lang: I18N.code || 'en', ...(pw ? {password: $('#su-pw', el).value} : {})})});
      const res = await r.json().catch(() => ({}));
      if (!r.ok) { errEl.textContent = res.error || tr('Error {0}', r.status); return; }
      $('.card', el).innerHTML = `${logo}<h2 class="invh">${tr('Almost done')}</h2><p role="status">${esc(res.mail ? tr('If the address can be used, an e-mail with a link is on its way. Open it to choose your password.') : tr('Your account waits for an admin to approve it. You can log in once it is approved.'))}</p><button class="btn" type="button" data-au="back">${tr('Back to the login')}</button>`;
    } catch { errEl.textContent = tr('Server not reachable.'); }
  });
  setTimeout(() => $('#su-name', el)?.focus(), 50);
}
// ---- Settings > Users > Whole server: sign-in (2FA policy, passkey login, OIDC)
function signinHtml(hint) {
  const a = S.about || {}, o = a.oidc || {};
  let h = `<h4 id="s-signin-h">${tr('Sign-in')}</h4>
    <div class="featgrid">
      <label class="wide"><input type="checkbox" id="s-2fareq" ${a.twofa_required ? 'checked' : ''}><span>${tr('Require two-factor authentication for built-in logins')}<small class="muted">${tr('Everyone who logs in with a password must set up an authenticator app or a passkey at the next login. Single sign-on logins (login proxy, OIDC) are not affected: there the login provider is responsible.')}</small></span></label>
      <label class="wide"><input type="checkbox" id="s-pklogin" ${a.passkey_login !== false ? 'checked' : ''}><span>${tr('Allow logging in with a passkey without the password')}<small class="muted">${tr('A passkey someone added in Settings > Account then also works on its own (the device asks for the fingerprint, face or PIN).')}</small></span></label>
    </div>
    ${signupAdminHtml(a)}
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
const stoHtml = () => `<h4 id="s-sto-h">${tr('Check storage')}</h4><div class="row"><button class="btn sm" data-m="sto-check">${ic('search', 's')} ${tr('Check storage')}</button></div><div id="s-sto" role="status" aria-live="polite"></div><div id="s-scn"></div>`;  // 2.61.0 (#1818): + s-scn
// 2.61.0 (#1818): the virus scanner's state below "Check storage" (one line; drawn once per opening)
async function scnStatus(md) {
  const box = $('#s-scn', md); if (!box || box.dataset.done) return;
  box.dataset.done = '1';
  let j; try { j = await api('GET', '/api/admin/upload-scan'); } catch { box.dataset.done = ''; return; }
  const st = j.state === 'off' ? tr('Virus scanner: off (KALMIDO_CLAMD is not set). Uploads are not checked.')
    : j.state === 'ok' ? tr('Virus scanner: active.') : tr('Virus scanner: not reachable. Uploads are taken and marked “Unchecked”; the check follows once it runs again.');
  const n = [j.unchecked ? trn('{0} file waits for the check', '{0} files wait for the check', j.unchecked) : '', j.infected ? trn('{0} locked file (malware found)', '{0} locked files (malware found)', j.infected) : ''].filter(Boolean);
  box.innerHTML = `<div class="shint${j.state === 'down' || j.infected ? ' cnote' : ''}">${esc(st)}${n.length ? ' ' + esc(n.join(' · ')) : ''}</div>`;
}
async function stoCheck(md) {
  const box = $('#s-sto', md); if (!box) return;
  box.innerHTML = `<div class="muted mhint">${tr('Loading…')}</div>`;
  let j; try { j = await api('GET', '/api/admin/storage-check'); } catch { box.innerHTML = ''; return; }
  const P = {missing: N_('missing'), empty: N_('empty'), size: N_('incomplete')};
  box.innerHTML = !j.problems.length ? `<div class="muted mhint">${esc(trn('{0} file checked, all fine', '{0} files checked, all fine', j.checked))}</div>`
    : `<div class="mhint warn">${esc(trn('{0} damaged or missing file', '{0} damaged or missing files', j.problems.length))}</div><ul class="stol">${j.problems.map(p => `<li><b>${esc(p.name)}</b> <span class="muted">${esc(p.where)} · ${esc(tr(P[p.problem]))}</span>${p.kind === 'attachment' && p.owner ? ` <button class="linkbtn" data-act="open-id" data-id="${p.owner}">${tr('Open')}</button>` : ''}</li>`).join('')}</ul>`;
}
const bkHtml = () => `<h4 id="s-bk-h">${tr('Backups')}</h4><div class="shint">${tr('The server key KALMIDO_SECRET_KEY is not part of a backup: keep it separately. A backup restores the encrypted organisation data only with that key (or with the organisations’ recovery keys).')}</div><div id="s-bk"><div class="muted mhint">${tr('Loading…')}</div></div>`;
const BK_KIND = {auto: N_('automatic'), manual: N_('manual'), safety: N_('before a restore')};
const fmtBytes = n => n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round((n || 0) / 1e3)) + ' kB';
async function bkDraw(md, j) {
  const box = $('#s-bk', md); if (!box) return;
  scnStatus(md);  // 2.61.0 (#1818): the virus scanner's line (once)
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
  h += j.items.length ? `<div class="members bklist">${j.items.map(x => `<div class="mrow bkrow" data-bkn="${esc(x.name)}"><span class="n"><b>${esc(aaWhen(x.created_at))}</b> · ${tr(BK_KIND[x.kind] || x.kind)} · ${fmtBytes(x.size)}${x.encrypted ? ` · ${ic('lock', 's')} ${tr('encrypted')}` : ''}${x.legacy ? ` · ${tr('old (SQLite), moved over when restored')}` : ''}
      <small class="muted" style="display:block">${x.unreadable ? tr('unreadable') : `${trn('{0} task', '{0} tasks', x.counts.tasks || 0)}, ${trn('{0} file', '{0} files', x.attachment_files || 0)}, ${trn('{0} user', '{0} users', x.counts.users || 0)} · v${esc(x.app_version)}`}</small></span>
      <a class="iconbtn" href="/api/admin/backups/${encodeURIComponent(x.name)}/download" download="${esc(x.name)}" title="${tr('Download')}">${ic('download', 's')}</a>
      <button class="iconbtn" data-bk="verify" title="${tr('Check')}">${ic('check', 's')}</button><button class="iconbtn" data-bk="restore" title="${tr('Restore')}">${ic('undo', 's')}</button><button class="iconbtn" data-bk="del" title="${tr('Delete')}">${ic('trash', 's')}</button></div>`).join('')}</div>` : `<div class="muted mhint">${tr('No backups yet.')}</div>`;
  h += `<div class="row"><label for="bk-file">${tr('Restore from a file')}</label>${fileBtn('bk-file', '.zip,.enc,application/zip')}</div>
    ${hint(tr('Larger files: copy them into the backup folder on the server instead, they then show up in the list.'))}`;
  box.innerHTML = h;
  box._body = bkBody(md);
  if (j.running && !box._poll) box._poll = setTimeout(async () => { box._poll = null; if (md.isConnected) await bkDraw(md); }, 1500);
}
const bkBody = md => $('#bk-on', md) ? {on: $('#bk-on', md).checked, time: $('#bk-time', md).value || '03:30', keep_daily: Math.max(1, +$('#bk-daily', md).value || 14), keep_weekly: Math.max(0, +$('#bk-weekly', md).value || 0), encrypt: $('#bk-enc', md).checked} : null;
const PURPOSES = [['me', 'user', N_('For me'), N_('Your own tasks: lists, reminders and the calendar. More views any time under Settings > Modules.')],
  // 2.22.0 (#741): "Home" for one person or a couple: Home & life with contracts, devices, staying in touch, health, journal
  ['home', 'home', N_('Home'), N_('Your household and life: contracts, warranties and upkeep, staying in touch, health, a journal, trips and read later.')],
  ['family', 'family', N_('Family'), N_('Shared lists, a shopping list with shop areas, household chores taking turns, birthdays, a meal plan and accounts for children.')],
  ['team', 'users', N_('Team'), N_('Sharing, assigning, comments, time tracking, a timeline with dependencies, custom fields and project progress.')],
  ['software', 'code', N_('Software projects'), N_('Everything of Team plus a software project: a board from backlog to done, bug and feature tickets, a repository.')],
  // 2.36.1 (#1021): the business area
  ['office', 'brief', N_('Office & finance'), N_('Everything of Team plus clients, workload, forms and the office: services and rates, quotations with a calculator, text blocks and PDF documents of your organisation.')]];
const PURPOSE_MODS = {me: ['cal', 'events', 'contacts'],
  home: ['cal', 'events', 'contacts', 'habits', 'contracts', 'home', 'care', 'health', 'review', 'travel', 'reading'],
  family: ['cal', 'habits', 'comments', 'collab', 'family', 'events', 'contacts', 'contracts', 'home', 'travel'],
  // 2.25.0 (UX-25): Team / Software hold only what the name promises (no habits, focus timer, matrix, statistics)
  team: ['cal', 'timeline', 'kanban', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts'],
  software: ['cal', 'timeline', 'kanban', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts'],
  office: ['cal', 'timeline', 'kanban', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts', 'clients', 'workload', 'forms', 'office']};
// 2.36.1 (#1021): the modules a purpose switches ON in addition (never off by another purpose; server: PURPOSE_EXTRA)
const PURPOSE_EXTRA = {office: ['clients', 'workload', 'forms', 'office']};
// First-run setup, step 2 ("What do you want to use?"): only right after the first admin was created, never on
// existing installs. Three presets (1.2: "Simple list"; "Just me" preselected; "Projects & team" = everything), then
// the single modules to fine-tune. Collaboration + time tracking are the instance switches; the other modules
// become the default of new users (the admin gets them too). "Skip" leaves everything on. All changeable later.
const SETUP_MAIN = [['collab', N_('Collaboration'), N_('Share lists, assign tasks, @mentions, activity and News')],
  ['a:time', N_('Time|area'), N_('Time tracking on tasks with reports, and the focus timer')]];  // 2.44.0 (#1187): the area Time
// 2.44.0 (#1187): the areas offered here and the modules each one switches (Office: contacts here; clients and the office come
// with the purpose "Office & finance", server PURPOSE_EXTRA); with a matching purpose only the modules the purpose holds
const MG_SU_AREA = {'a:time': ['time', 'pomo'], 'a:review': ['review', 'stats'], 'a:life': ['family', 'contracts', 'home', 'care', 'health', 'travel', 'reading'], 'a:office': ['contacts']};
const mg_suIn = (k, x) => MG_SU_AREA[x] ? MG_SU_AREA[x].some(p => PURPOSE_MODS[k].includes(p)) : PURPOSE_MODS[k].includes(x);
const mg_suHas = (on, x) => MG_SU_AREA[x] ? MG_SU_AREA[x].some(p => on.has(p)) : on.has(x);
const SETUP_MODS = [['cal', N_('Calendar'), N_('Month, week and day view of your tasks')], ['timeline', N_('Timeline'), N_('Tasks with start and end as bars over time')],
  ['events', N_('Events'), N_('Appointments in your own calendars next to the tasks, shared calendars, invitations, synced with the phone’s calendar')],
  ['a:office', N_('Office|area'), N_('Your contacts; clients and the office come with “Office & finance”')],
  ['matrix', N_('Eisenhower matrix'), N_('Urgent and important in four quadrants')], ['kanban', N_('Kanban'), N_('Lists as boards with columns')],
  ['habits', N_('Habits'), N_('Daily and weekly habits with streaks')],
  ['a:review', N_('Review|area'), N_('Statistics, and your day and week in review with a private journal')], ['progress', N_('Project progress'), N_('Progress per list and the project status (“Where is it stuck?”)')],
  ['deps', N_('Dependencies'), N_('Tasks blocked by other tasks, with arrows in the timeline (Gantt)')], ['fields', N_('Custom fields'), N_('Own fields per list, such as budget, client or phase')],
  ['comments', N_('Comments'), N_('Timestamped notes on your tasks; in shared lists with collaboration also @mentions and News')],
  ['a:life', N_('Home|area'), N_('Family (chores, shopping, meal plan, accounts for children) and Home & life (contracts, devices, health, trips)')]];
// 2.7.0 (K21, #405): a simple start for a new instance; one question "Start with" below. 2.19.0 (#653): the presets are the
// answers to "What do you use Kalmido for?" (For me = the simple start, Family, Team, Software projects)
const SETUP_PRESETS = Object.fromEntries(PURPOSES.map(([k, i, n, d]) => [k, {name: n, icon: i, desc: d,
  off: [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]).filter(x => !mg_suIn(k, x))}]));
// 2.25.0 (UX-19): the same count as Settings > Modules: what is picked here against every module (the ones not offered
// here, such as Home & life or Clients, start off and are switched on later in Settings > Modules)
function setupCount(picked) {
  const here = SETUP_MAIN.length + SETUP_MODS.length, all = MOD_GROUPS.flatMap(([, ks]) => ks).length;
  const on = picked.size;
  return all > here ? tr('{0} of {1} modules on · {2} more in Settings > Modules', on, all, all - here) : tr('{0} of {1} modules on', on, all);
}
async function setupChoices(el, logo) {
  let st = {};
  try { st = await (await fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}})).json(); } catch { /* offline: defaults */ }
  const langs = st.languages || [{code: 'en', name: 'English'}];
  const all = [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]);
  let lang = I18N.code || 'en', preset = 'me', picked, custOpen = false, start = '';
  const askOrg = st.about?.instance_mode !== 'shared' && !st.about?.org_name_env && !st.about?.has_orgs;  // 2.23.0 (#799): asked once; 2.46.0 (#1592): creates the first organisation
  // 2.24.0 (UX-23): the purpose first; the name of the organisation only for a team / company, empty allowed (the
  // instance's default name is not offered as a value), changeable later under Administration > Organisation
  let orgName = (st.me?.orgs?.[0] || '').toLowerCase() === APP_NAME.toLowerCase() ? '' : st.me?.orgs?.[0] || '';
  // 2.46.1 (#1591): "Switch on all modules" (null = untouched: the presets decide as before); it sets the modules below,
  // never the two server switches on top (collaboration, time for everyone)
  let modsAll = null;
  const pm_su = () => { if (modsAll !== null) for (const [k] of SETUP_MODS) modsAll ? picked.add(k) : picked.delete(k); };
  const apply = k => { preset = k; picked = new Set(all.filter(x => !SETUP_PRESETS[k].off.includes(x))); pm_su(); };
  apply('me');
  // 2.13.2 (#478 F12): step 2 shown again after a reload (setup still pending) starts from what is on now, not from
  // "Simple list" ("Start" would switch modules off again); a new account (all modules on = the default) keeps "Simple list"
  const fs0 = st.settings?.features;
  if (typeof fs0 === 'string' && !all.filter(x => x !== 'a:life' && x !== 'a:review').every(x => mg_suHas(new Set(fs0.split(',')), x))) {  // everything on = the untouched default (2.19.0: Family is off by default; 2.44.0: Home, and Review without the journal)
    const on = new Set(fs0.split(',')); picked = new Set(all.filter(x => mg_suHas(on, x) && (x !== 'collab' || st.collab_all !== false) && (x !== 'a:time' || st.time_all !== false)));
    preset = Object.keys(SETUP_PRESETS).find(k => all.every(x => picked.has(x) === !SETUP_PRESETS[k].off.includes(x))) || '';
  }
  // 2.7.0 (K21): one question "Start with": empty, the sample project, or a project of a built-in type (agency, software, personal)
  const STARTS = [['', N_('Empty|start'), 'list', N_('Your Basket and Today, nothing else')], ['sample', N_('Sample project'), 'eye', N_('A small video production with dates and a packing list, to look around; remove it any time under Settings > Data')],
    ...PTYPE_UI.slice(1).map(([k, n, i, d]) => [k, n, i, d])];
  const row = ([k, n, d]) => `<label class="suse"><input type="checkbox" data-use="${k}" ${picked.has(k) ? 'checked' : ''}><span><b>${tr(n)}</b><small class="muted">${tr(d)}</small></span></label>`;
  const matches = k => all.every(x => picked.has(x) === !SETUP_PRESETS[k].off.includes(x));
  const draw = () => {
    el.innerHTML = `<div class="card setupcard">${logo}
      <div class="seg" id="su-lang">${langs.map(L => `<button type="button" data-su-lang="${esc(L.code)}" class="${L.code === lang ? 'on' : ''}" lang="${esc(L.code)}">${langName(L)}</button>`).join('')}</div>
      <h3>${tr('What do you use Kalmido for?')}</h3>
      <p class="muted">${tr('Pick a start, untick what you do not need. Everything can be changed later in Settings.')}</p>
      <div class="supresets">${Object.entries(SETUP_PRESETS).map(([k, p]) => `<button type="button" class="supreset ${matches(k) ? 'on' : ''}" data-su-preset="${k}" aria-pressed="${matches(k)}"><b>${ic(p.icon, 's')}${tr(p.name)}</b><small class="muted">${tr(p.desc)}</small></button>`).join('')}</div>
      ${pm_allHtml('su-modsall', modsAll ?? SETUP_MODS.every(([k]) => picked.has(k)))}
      ${askOrg && ['team', 'software', 'office'].includes(preset) ? `<h3><label for="su-org">${tr('Name of your team or company')} <span class="muted">${tr('(optional)')}</span></label></h3><input id="su-org" class="suorg" maxlength="60" value="${esc(orgName)}" placeholder="${esc(tr('e.g. your company'))}"><p class="muted">${tr('Shown next to the app name and in invitations. You can change it later in Settings > Administration > Organisation.')}</p>` : ''}
      <details class="sucust" ${custOpen ? 'open' : ''}><summary>${tr('Customize…')} <span class="muted">${esc(setupCount(picked))}</span></summary>
      <div class="suse-main">${SETUP_MAIN.map(row).join('')}</div>
      <div class="suse-list">${SETUP_MODS.map(row).join('')}</div></details>
      <h3 id="su-start-h">${tr('Start with')}</h3>
      <div class="sustarts ptcards" role="radiogroup" aria-labelledby="su-start-h">${STARTS.map(([k, n, i, d]) => `<button type="button" class="ptcard ${k === start ? 'on' : ''}" role="radio" aria-checked="${k === start}" data-su-start="${k}">${ic(i, 's')}<b>${tr(n)}</b><small class="muted">${tr(d)}</small></button>`).join('')}</div>
      <p class="muted sunote">${tr('More projects any time: Lists > + > New project.')}</p>
      <div class="aerr" role="alert" id="su-err"></div>
      <div class="sufoot"><button type="button" class="btn pri" data-su="go">${tr('Start')}</button></div></div>`;
    $('.sucust', el)?.addEventListener('toggle', e => { custOpen = e.target.open; });
  };
  draw();
  el.addEventListener('input', e => { if (e.target.id === 'su-org') orgName = e.target.value; });
  el.addEventListener('change', e => {
    if (e.target.id === 'su-modsall') { modsAll = e.target.checked; pm_su(); draw(); return; }
    const c = e.target.closest('[data-use]'); if (!c) return;
    c.checked ? picked.add(c.dataset.use) : picked.delete(c.dataset.use);
    $$('[data-su-preset]', el).forEach(b => { b.classList.toggle('on', matches(b.dataset.suPreset)); b.setAttribute('aria-pressed', matches(b.dataset.suPreset)); });
    const sm = $('.sucust summary .muted', el); if (sm) sm.textContent = setupCount(picked);
  });
  el.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.suLang) { lang = b.dataset.suLang; await i18nLoad(lang); LS.set('lang', lang); draw(); return; }
    if (b.dataset.suPreset) { apply(b.dataset.suPreset); if (b.dataset.suPreset === 'software') start = 'software'; else if (start === 'software') start = ''; draw(); return; }
    if (b.dataset.suStart !== undefined) {
      start = b.dataset.suStart;
      // a project type needs its modules (agency: time tracking + custom fields, software: kanban + dependencies)
      for (const m of {agency: ['a:time', 'fields'], software: ['kanban', 'deps']}[start] || []) picked.add(m);
      draw(); return;
    }
    const post = async (url, body) => { const r = await fetch(url, {method: url.endsWith('settings') ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(body)}); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || tr('Error {0}', r.status)); };
    try {
      if (b.dataset.su === 'go') await post('/api/admin/setup', {lang, collab_all: picked.has('collab'), time_all: picked.has('a:time'), modules: [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]).filter(k => picked.has(k) && k !== 'collab').flatMap(k => MG_SU_AREA[k] ? MG_SU_AREA[k].filter(p => !matches(preset) || PURPOSE_MODS[preset].includes(p)) : [k]), sample: start === 'sample', ...(start && start !== 'sample' ? {project_type: start} : {}), ...(matches(preset) || (modsAll !== null && preset) ? {purpose: preset} : {}), ...(modsAll !== null ? {all_modules: modsAll} : {}), examples: start === 'sample', ...(askOrg && ['team', 'software', 'office'].includes(preset) && orgName.trim() ? {org_name: orgName.trim()} : {})});
      else return;
      location.replace('/');
    } catch (err) { $('#su-err', el).textContent = err.message || tr('Server not reachable.'); }
  });
}
function sectionMenu(anchor, sid) {
  const s = S.sections.find(x => x.id === sid);
  menu(anchor, [
    {label: tr('Rename'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename section'), s.name, {ok: tr('Rename')}); if (n && n.trim()) sectionRename(sid, n.trim()); }},
    {label: tr('Move left / up'), icon: 'left', fn: () => moveSection(sid, -1)},
    {label: tr('Move right / down'), icon: 'right', fn: () => moveSection(sid, 1)},
    wip_menuItem(sid),  // 2.60.0 (#1510)
    '-',
    {label: tr('Delete section (tasks stay)'), icon: 'trash', cls: 'flag-5', fn: () => sectionDelete(sid)},
  ]);
}

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
