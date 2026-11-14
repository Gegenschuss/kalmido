/* Kalmido web client: Account, users (admin), login, groups, passkeys, two-factor, sign-in policy, backups, the sample project.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ account, users (admin), login
// settings sections: own account (name, password, upload token, log out) + user admin for admins
// 1.9.0: profile picture in Settings > Account: a preset picture, an own photo (cropped square here, resized on the server)
// or none (initials). Shown wherever the initials were: sidebar, assignees, comments, News, members.
// 2.170.0 (#2675): no props on the pictures any more, so the names are only keys; the title describes what the picture
// shows (hair or antenna, face), AV_BOTS_N for the bots (avTitle)
const AV_PRESETS = [['coffee', N_('Beard, cheerful')], ['headphones', N_('Curls, calm')], ['camera', N_('Bun, glancing')],
  ['sleepy', N_('Long hair, sleepy')], ['laptop', N_('Swept hair, calm')], ['plant', N_('Ponytail, winking')], ['robot', N_('Afro, wide-eyed')],
  ['shades', N_('Very short hair, cool')], ['party', N_('Bob, cheerful')], ['glasses', N_('Headscarf, calm')]];
const AV_BOTS_N = [N_('Ball antenna, cheerful'), N_('Ring antenna, calm'), N_('Bent antenna, glancing'), N_('Drooping antenna, sleepy'),
  N_('Zigzag antenna, calm'), N_('Forked antenna, winking'), N_('Two lamps, wide-eyed'), N_('Lamp antenna, cool'), N_('Curly antenna, cheerful'),
  N_('Tall antenna, calm')];
// 2.170.0 (#2675): AV_PRESETS draw people (user pictures), AV_BOTS the bot of the same name (agents); groups and project
// icons offer both
const AV_BOTS = AV_PRESETS.map(([k], i) => ['a-' + k, AV_BOTS_N[i]]);
const avTitle = k => tr([...AV_PRESETS, ...AV_BOTS].find(([x]) => x === k)?.[1] || 'Profile picture');
function avPickHtml(cur = S.me?.avatar || '', own = true, name = S.me?.display_name, set = AV_PRESETS) {
  return set.map(([k]) => `<button type="button" class="avopt ${cur === `/static/avatars/${k}.svg` ? 'on' : ''}" data-av="${k}" title="${esc(avTitle(k))}" aria-label="${esc(avTitle(k))}" aria-pressed="${cur === `/static/avatars/${k}.svg`}"><img src="/static/avatars/${k}.svg" alt=""></button>`).join('') +
    (own ? `<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" hidden data-fpass><button type="button" class="avopt up ${cur.startsWith('/api/avatar/') ? 'on' : ''}" data-av="upload" title="${esc(tr('Upload a photo…'))}" aria-label="${esc(tr('Upload a photo…'))}">${cur.startsWith('/api/avatar/') ? `<img src="${esc(cur)}" alt="">` : ic('plus')}</button>` : '') +
    `<button type="button" class="avopt none ${cur ? '' : 'on'}" data-av="none" title="${esc(tr('No picture (initials)'))}" aria-label="${esc(tr('No picture (initials)'))}" aria-pressed="${!cur}">${esc(initials(name))}</button>`;
}
// 2.633.0 (#4920): fixed hidden file input, its change uploads (a drop onto the window too, dropany.js). For pickers whose
// button is wired in other files (profile / agent picture, project icon): the change hands the file to the click of the button
// right after the input (<input data-fpass hidden><button>), and the button's own upload path takes it (fpass_take) instead of
// opening the file picker - same checks, same crop, same toasts. A click on the button alone still opens the picker.
const FPASS = {f: /** @type {File|null} */ (null)};
const fpass_take = () => { const f = FPASS.f; FPASS.f = null; return f; };
document.addEventListener('change', e => {
  const t = e.target; if (!t.matches?.('input[type="file"][data-fpass]') || !t.files?.length) return;
  FPASS.f = t.files[0]; t.value = '';
  try { t.nextElementSibling?.click(); } finally { FPASS.f = null; }  // taken synchronously by the button's handler, else dropped
});
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
  if (aid) for (const el of document.querySelectorAll(`[data-agid="${aid}"]`)) el.style.setProperty('--agcol', c);  // 2.438.0 A (#3322): bubbles take the new colour at once
  if (aid) for (const el of document.querySelectorAll(`[data-agacc="${aid}"]`)) { el.style.setProperty('--agcol', c); if (typeof wac_agentPut === 'function') wac_agentPut(el, c); }  // 2.542.0 (#4604): the chat's accent too
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
  const go = async f => {
    if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
    const bl = await avCropModal(f); if (!bl) return;
    const fd = new FormData(); fd.append('file', bl, 'avatar.jpg');
    try { done(await api('POST', url, fd)); toast(tr('Profile picture saved')); } catch { /* api() showed it */ }
  };
  const f0 = fpass_take(); if (f0) { go(f0); return; }  // 2.633.0 (#4920): the file of the fixed input before the button (avPickHtml)
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
  inp.addEventListener('change', async () => {
    const f = inp.files?.[0]; if (!f) return;
    go(f);
  });
  inp.click();
}
const NOTIF_ROWS = [
  ['comment', N_('Comments on my tasks'), N_('tasks I created or am assigned to')],
  ['reply', N_('Replies to my comment'), N_('someone comments right after me')],
  ['follow', N_('Comments on tasks I follow'), N_('tasks I commented on')],
  ['mention', N_('Mentions of me')],
  ['assign', N_('Tasks assigned to me (or taken away)')],
  ['newtask', N_('New tasks in shared projects'), N_('created by someone else')],
  ['complete', N_('Others completed my tasks')],
  ['status', N_('Project status changes')],
  ['share', N_('Projects shared with me')],
  ['unblock', N_('A task blocking mine was completed'), '', 'deps'],
  ['approval', N_('An agent waits for my approval'), '', 'agents'],
  ['signoff', N_('Client decisions'), N_('a client approved or rejected through a link (quotation, document, video)')],  // 2.266.0 (#2965)
  ['followup', N_('Follow-up day of a task waiting on someone')],
  ['reminder', N_('Reminders'), N_('due dates of my tasks')],
  ['nag', N_('Repeated reminders'), N_('until the task is done; not during your quiet hours')],  // 2.7.0 (#413)
  ['usage', N_('An agent reached a usage limit'), N_('admins: 80 % and 100 % of a limit, sign-ins of organisation admins from a new address, registrations'), 'admin'],  // 2.1.1 (#326)
  ['proposal', N_('A proposal I asked an agent for is ready'), '', 'propose'],  // 2.3.0: only with an agent I may ask
  ['chat', N_('Team chat'), N_('direct messages; in channels only when you are mentioned (or the project bell is “All”)')],  // 2.17.0 (#419)
  ['errreport', N_('New error reports'), N_('a new error from a project’s error-report webhook became a ticket (repeats stay quiet)')]];  // 2.18.0
// 2.425.0 (#3453 review): the receipt fetcher's row lives here (docfetch.js comes lazily with the documents: the row was missing until then)
NOTIF_ROWS.push(['fetcher', N_('Receipt fetcher'), N_('a portal of your receipt fetcher reports an error, for example a sign-in that ran out'), 'office']);
NOTIF_ROWS.push(['docflow', N_('Document flows'), N_('a flow of your documents tells you about a document')]);  // 2.581.0 (#4803): News only
NOTIF_ROWS.push(['integration', N_('Integrations'), N_('a forwarding, webhook, mailbox or git connection of yours stopped working')]);  // 2.367.3 (#2971)
NOTIF_ROWS.push(['limits', N_('E-mail limits of public pages'), N_('your client portal or booking page used up its sign-in or confirmation e-mails')]);  // 2.453.0 (#3781): News only
NOTIF_ROWS.push(['notice', N_('Notices from the server'), N_('a maintenance notice sent as a push')]);  // 2.367.4 (#2974): push only
NOTIF_ROWS.push(['office', N_('Payments and overdue invoices'), N_('a payment was booked on an invoice of your office, an invoice is past its due date or a sent quotation runs out without an answer (no push for those two)'), 'office']);  // 2.367.4 (#2972); 2.1064.0 (#5818): + quotations
NOTIF_ROWS.push(['calsub', N_('Calendar subscriptions'), N_('a calendar you subscribed to failed three times in a row')]);  // 2.367.2 (#2969): News only
NOTIF_ROWS.push(['timebudget', N_('Budget warnings'), N_('a project or task of yours reached 80 % or 100 % of its budget in hours (once per threshold)')]);  // 2.555.0 (#4570)
const NM_GROUP = {comment: 'comment', reply: 'comment', follow: 'comment', mention: 'mention', assign: 'assign', complete: 'complete', status: 'status', share: 'share', unblock: 'unblock'};
const NM_PRIMARY = ['comment', 'mention', 'assign', 'complete', 'status', 'share', 'unblock'];
const NM_NEWS_NEW = {newtask: 0, approval: 1, followup: 1, usage: 1, proposal: 1, errreport: 1, signoff: 1, limits: 1, calsub: 1, office: 1};  // 2.266.0 (#2965): signoff
const NM_PUSH = {comment: 1, reply: 1, follow: 1, mention: 1, assign: 1, newtask: 0, complete: 1, status: 0, share: 0, unblock: 1, approval: 1, followup: 1, reminder: 1, usage: 1, proposal: 1, nag: 1, chat: 1, errreport: 1, signoff: 1, office: 1, notice: 1};
const NM_SOCIAL = ['comment', 'reply', 'follow', 'mention', 'assign', 'newtask', 'complete', 'status', 'share', 'unblock', 'approval', 'proposal', 'chat', 'errreport'];
/** @type {any} */ (NM_NEWS_NEW).timebudget = 1; /** @type {any} */ (NM_PUSH).timebudget = 1; NM_SOCIAL.push('timebudget');  // 2.555.0 (#4570): News + push on by default, needs the collaboration module like the News
const nmStored = s => { try { const o = JSON.parse(s.notify || '{}'); return o && typeof o === 'object' ? o : {}; } catch { return {}; } };
function notifMatrix(s) {
  const nk = new Set(String(s.news_kinds ?? 'mention,assign,comment,complete,unblock,share,status').split(',')), o = nmStored(s), out = {};
  for (const [r] of NOTIF_ROWS) {
    const x = o[r] && typeof o[r] === 'object' ? o[r] : {};
    const news = r === 'reminder' || r === 'nag' || r === 'chat' || r === 'notice' ? null : NM_PRIMARY.includes(r) ? nk.has(NM_GROUP[r]) : 'news' in x ? !!x.news : r in NM_GROUP ? nk.has(NM_GROUP[r]) : !!NM_NEWS_NEW[r];
    out[r] = {news, push: r === 'limits' || r === 'calsub' ? null : 'push' in x ? !!x.push : !!NM_PUSH[r]};
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
// 2.152.0 (#2164): the label of a retired organisation (bundle C: here, since acctset.js loads on demand since 2.149.0)
const odlRetiredLabel = o => esc(tr('kept until {0}', fmtDate(o.retain_until))) + (o.retired_personal ? ' · ' + esc(tr('office of a deleted account')) : '');
async function orgsDraw(md) {
  const box = $('#a-orgs', md); if (!box) return;
  let j; try { j = await api('GET', '/api/admin/orgs'); } catch { return; }
  S.orgs = j.orgs;
  box.innerHTML = j.orgs.length ? j.orgs.map(o => `<div class="mrow">${o.icon_url ? orgIconHtml(o) : `<span class="fem" aria-hidden="true">${o.icon ? esc(o.icon) : ic('building')}</span>`}<span class="n">${esc(o.name)} <span class="muted">${o.retired_at ? odlRetiredLabel(o) : esc(trn('{0} member', '{0} members', o.people ?? o.members.length))}${(o.admins || []).length ? ' · ' + esc(trn('{0} admin', '{0} admins', o.admins.length)) : ''}${o.domains ? ' · ' + esc(o.domains) : ''}</span></span>${j.editable && !o.retired_at && !o.apart ? `<button class="iconbtn${j.creatable ? ' ms-phsr' : ''}" data-acc="org-edit" data-oid="${o.id}" title="${esc(tr('Edit organisation'))}" aria-label="${esc(tr('Edit {0}', o.name))}">${ic('edit', 's')}</button>` : ''}${j.creatable ? `<button class="iconbtn danger${j.editable && !o.retired_at && !o.apart ? ' ms-phsr' : ''}" data-acc="org-del" data-oid="${o.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete {0}', o.name))}">${ic('trash', 's')}</button>${/*html-ok*/ j.editable && !o.retired_at && !o.apart ? ms_dots('.ms-phsr', o.name) : ''}` : ''}</div>`).join('') : `<div class="muted mhint">${tr('No organisation yet.')}</div>`;
  // 2.30.0 (#1036): the nightly boundary check's count (memberships across the boundary between workspaces)
  const bd = j.boundary;
  if (bd && j.orgs.length) box.insertAdjacentHTML('beforeend', oa_boundaryHtml(bd));  // 2.46.0 (#1563): unfoldable, with "Clean up"
  const vs = $('#a-vis', md); if (vs) vs.innerHTML = VIS_UI.map(([k, n]) => `<option value="${k}" ${k === j.visibility ? 'selected' : ''}>${esc(tr(n))}</option>`).join('');
}
// 2.143.0 D (#2156): Administration > Organisation: activity per organisation (numbers only; + one row for people without one)
const actHtml = () => `<h4 id="s-act-h">${tr('Activity per organisation')}</h4><div id="s-act" class="shint">${tr('Loading…')}</div>`;
// 2.1156.0 (#4280): the settings sections of account.js that only the settings dialog draws (Workspaces pane, sign-up / sign-in / OIDC, storage, backups) moved to acctadm.js (loaded on demand, static/js/lazyload.js)
// ---- 2.28.0 (#935): Settings > Workspaces -- my organisations; an organisation's admin adds / removes members and sets their
// role (also when not an admin of the server), renames it; its e-mail domains only an admin of the server (2.467.0, #3898)
const wsPaneOn = () => wsOn() && !S.me?.kid;
// 2.1156.0 (#4280): the projects of an organisation for its admins (oadmOpen: list, take back, outreach log) moved to orgadmin.js (loaded on demand, static/js/lazyload.js)
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
// 2.955.0 (#5239): the Dada quote of the day (quotes_dada.js, loaded on demand; before the sign-in too): the line when the file
// is in, else a placeholder that the file fills once it is (the next drawing has the line at once, no jump on a redraw)
// 2.1030.0 (#5785): Spanish, French, Italian and Dutch load their own texts beside it (module quotes_<code>, the file of that
// language only); while it is missing (offline, an error) the line falls back to English instead of staying away
let qd_miss = '';
function qd_slot(/** @type {string} */ cls) {
  const ui = typeof I18N !== 'undefined' ? I18N.code : 'en', mod = ['es', 'fr', 'it', 'nl'].includes(ui) && qd_miss !== ui ? 'quotes_' + ui : 'quotes';
  if (typeof qd_html === 'function' && (mod === 'quotes' || (typeof QD_TR !== 'undefined' && QD_TR[ui]))) return qd_html(cls);
  if (typeof loadModule === 'function') loadModule(mod).then(() => qd_fill(), () => { if (mod !== 'quotes') qd_miss = ui; if (typeof qd_fill === 'function') qd_fill(); });  // offline without the file: no line (English without the language's file)
  return `<div class="qdslot" data-qd="${esc(cls)}"></div>`;
}
// 2.22.0 (#697): the page "Set up your account" (the link of an invitation or a password reset: /#invite/<token>)
async function inviteScreen(tok) {
  history.replaceState(null, '', location.pathname);  // the token leaves the address bar (and the history) at once
  let info = null;
  try { const r = await fetch('/api/auth/invite/check', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({token: tok})}); info = await r.json(); if (!r.ok) info = {error: info.error || httpErrText(r.status)}; } catch { info = {error: tr('Server not reachable.')}; }
  await i18nLoad(info.lang || uiLang());
  const el = document.createElement('div');
  el.className = 'modal authscreen';
  lg_decor(el);  // 2.49.0 (#1553)
  const logo = `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div>`;
  if (info.error) {
    el.innerHTML = `<div class="card">${logo}<p role="alert">${esc(info.error)}</p><button class="btn pri" type="button" data-au="login">${tr('Go to sign-in')}</button></div>`;
  } else {
    el.innerHTML = `<div class="card">${logo}
      <h2 class="invh">${esc(info.kind === 'reset' ? tr('Set a new password') : info.kind === 'signup' ? tr('Confirm your registration') : tr('Welcome, {0}!', info.display_name))}</h2>
      ${info.kind === 'invite' && (info.invited_by || info.org_name) ? `<p class="invby">${esc(info.invited_by ? tr('{0} invites you to {1}.', info.invited_by, info.org_name || APP_NAME) : tr('You are invited to {0}.', info.org_name))}</p>` : ''}${''/* 2.365.0 (#2802): who invites, into which organisation */}
      <p class="muted">${esc(info.kind === 'reset' ? tr('Choose a new password for “{0}”.', info.username) : tr('Choose your own password to finish your account.'))}</p>
      <form id="inv-form" autocomplete="on">
        <label class="aulab" for="inv-user">${tr('Username')}</label><input id="inv-user" name="username" autocomplete="username" readonly value="${esc(info.username)}">
        <label class="aulab" for="inv-pw">${tr('New password')}</label><input id="inv-pw" type="password" autocomplete="new-password" required minlength="${info.min_password || 8}" placeholder="${esc(tr('at least {0} characters', info.min_password || 8))}">
        <label class="aulab" for="inv-pw2">${tr('Repeat the password')}</label><input id="inv-pw2" type="password" autocomplete="new-password" required>
        <label class="chkl"><input type="checkbox" id="inv-2fa"> ${tr('Set up two-factor sign-in right after (recommended)')}</label>
        <div class="aerr" role="alert" id="inv-err"></div>
        <button class="btn pri" type="submit">${info.kind === 'reset' ? tr('Save and sign in') : tr('Set up my account')}</button>
        ${info.kind === 'reset' ? `<p class="muted">${esc(tr('The new password revokes your app passwords (CalDAV) and your own API tokens; create new ones afterwards if you need them under Settings > Account (API tokens: Advanced · for developers). Agents keep their tokens.'))}</p>` : ''}${''/* 2.58.0 (#1792): L3; 2.360.0 (#2496): the reset revokes them */}
      </form></div>`;
    el.querySelector('#inv-form').addEventListener('submit', async e => {
      e.preventDefault();
      const errEl = $('#inv-err', el), pw = $('#inv-pw', el).value;
      if (pw.length < (info.min_password || 8)) { errEl.textContent = tr('Password: at least {0} characters', info.min_password || 8); return; }
      if (pw !== $('#inv-pw2', el).value) { errEl.textContent = tr('The two passwords are not the same'); return; }
      try {
        const r = await fetch('/api/auth/invite/accept', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({token: tok, password: pw})});
        const res = await r.json().catch(() => ({}));
        if (!r.ok) { errEl.textContent = res.error || httpErrText(r.status); return; }
        if (res.twofa) { await authTwofa(el, logo, res.methods || ['totp']); return; }  // 2.49.0 (#1531): two-factor stays required after a reset
        if (res.enrol) { await authEnrol(el, logo); return; }
        if (res.pending) { $('.card', el).innerHTML = `${logo}<h2 class="invh">${tr('Thank you!')}</h2><p role="status">${tr('Your account waits for an admin to approve it. You can sign in once it is approved.')}</p><button class="btn pri" type="button" data-au="login">${tr('Go to sign-in')}</button>`; return; }  // 2.23.0 (#711)
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
// 2.743.0 (#4284): a sign-out without network could not end the session on the server (HttpOnly cookie): this browser keeps
// a mark (outside the tasks.* keys clearLocal wipes) and the next load of the state ends that session before anything else,
// so a shared device does not open the account again once it is online. The sign-in screen (= the server knows no session) drops it.
const LGO_KEY = 'kalmido.logoutPending';
async function lgo_pending() {
  let p = null;
  try { p = localStorage.getItem(LGO_KEY); } catch { return; }
  if (!p) return;
  try { if ((await fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}})).ok) localStorage.removeItem(LGO_KEY); } catch { /* still offline: the state load goes the offline way too */ }
}
async function logout() {
  if (kd_pinNeed()) return kd_pinAsk(logout);  // 2.49.0 (#1551): a child with the parents' PIN
  if (OUT.q.length && !await askConfirm(trn('{0} change is not synced yet and will be lost. Sign out anyway?', '{0} changes are not synced yet and will be lost. Sign out anyway?', OUT.q.length), '', {ok: tr('Sign out'), danger: true})) return;
  await wpDisable().catch(() => {});  // this device stops getting the pushes of the account that logs out
  await e2eForget();  // 2.42.0 (#828): keys remembered on this device go
  let gone = false;
  try { gone = (await fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}})).ok; } catch { /* offline */ }
  if (!gone) try { localStorage.setItem(LGO_KEY, '1'); } catch { /* private mode */ }  // 2.743.0 (#4284): the session still lives on the server: the next load ends it first (lgo_pending)
  try { for (const k of await caches.keys()) await caches.delete(k); } catch { /* no Cache Storage */ }  // 2.126.0 D (#1992 O4): the app loads again from the server
  await Promise.race([clearLocal(), new Promise(r => setTimeout(r, 1500))]); location.replace('/');  // 2.143.0 C2 (#2153): the IndexedDB queue is empty before the page goes
}
// 2.306.0 B (#2887): the operator's privacy statement / imprint (Settings > Help and the login page); '' = no link
const legalLinks = (l, cls) => [['privacy_url', N_('Privacy')], ['imprint_url', N_('Imprint')]].filter(([k]) => /^https?:\/\//i.test(l?.[k] || ''))
  .map(([k, n]) => `<a class="${cls} lglegal" data-legal="${k}" href="${esc(l[k])}" target="_blank" rel="noopener noreferrer">${tr(n)}</a>`).join('');
// login / first-run setup / "no account" screen (built-in login; with single sign-on the proxy logs in)
async function authScreen(j) {
  if ($('.authscreen')) return;
  try { localStorage.removeItem(LGO_KEY); } catch { /* private mode */ }  // 2.743.0 (#4284): no session on the server any more
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
      ${/*html-ok*/ setup ? '' : qd_slot('lgq')}${''/* 2.49.0 (#1553); 2.955.0 (#5239): the Dada quote of the day instead of the greeting */}
      ${setup ? `<p>${tr('Welcome! Create the first account, it becomes the admin.')}</p>${info.login ? `<p class="muted">${esc(tr('Signed in at the sign-in proxy as “{0}”: the account is linked to it, a password is optional.', info.login))}</p>` : ''}` : ''}
      <form id="auth-form" autocomplete="on">
        ${setup && info.setup_code ? `<label class="aulab" for="au-code">${tr('Setup code')}</label><input id="au-code" autocapitalize="off" autocomplete="one-time-code" spellcheck="false" required aria-describedby="au-code-h"><div class="shint shcode" id="au-code-h">${tr('The server prints it into its log at start: {0}', '<code>docker compose logs kalmido</code>')}</div>` : ''}${''/* 2.45.0 (#1515) */}
        <label class="aulab" for="au-user">${tr('Username')}</label><input id="au-user" name="username" autocapitalize="off" autocomplete="username" required value="${setup && info.login ? esc(String(info.login).toLowerCase()) : ''}">
        ${setup ? `<label class="aulab" for="au-name">${tr('Display name')}</label><input id="au-name" maxlength="60" autocomplete="name" placeholder="${tr('optional')}">` : ''}
        <label class="aulab" for="au-pw">${tr('Password')}</label><span class="pwwrap"><input id="au-pw" name="password" type="password" autocomplete="${setup ? 'new-password' : 'current-password'}" ${setup && info.login ? '' : 'required'} ${setup ? `placeholder="${tr('at least {0} characters', 8)}"` : ''}><button type="button" class="iconbtn pweye" data-au="pwshow" aria-pressed="false" aria-label="${esc(tr('Show password'))}" title="${esc(tr('Show password'))}">${ic('eye', 's')}</button></span>
        ${setup ? '' : `<div class="lgopts"><label class="chkl"><input type="checkbox" id="au-rem" checked> ${tr('Stay signed in')}</label>${info.forgot ? `<button type="button" class="linkbtn lgforgot" data-au="forgot">${tr('Forgot your password?')}</button>` : ''}</div>`}${''/* 2.49.0 (#1531, #1553): one row */}
        <div class="aerr" role="alert" id="au-err"></div>
        <button class="btn pri" type="submit">${setup ? tr('Create account') : tr('Sign in')}</button>
        ${!setup && (info.oidc || (info.passkey_login && pkSupported())) ? `<div class="aor"><span>${tr('or')}</span></div>` : ''}
        ${!setup && info.oidc ? `<button type="button" class="btn" data-au="oidc">${ic('link', 's')} ${esc(tr('Sign in with {0}', info.oidc.label))}</button>` : ''}
        ${!setup && info.passkey_login && pkSupported() ? `<button type="button" class="btn" data-au="passkey">${ic('key', 's')} ${tr('Sign in with a passkey')}</button>` : ''}
        ${!setup && info.signup ? `<p class="aulink">${tr('New here?')} <button type="button" class="linkbtn" data-au="signup">${tr('Create account')}</button></p>` : ''}
      </form>${legalLinks(info.legal, 'linkbtn') ? `<p class="aulegal">${legalLinks(info.legal, 'linkbtn')}</p>` : ''}</div>`;
    const le = (location.hash.match(/login-error=([a-z_]+)/) || [])[1];
    if (le) { $('#au-err', el).textContent = (info.login_errors || {})[le] || (info.login_errors || {}).failed || tr('Sign-in failed. Please try again.'); history.replaceState(null, '', location.pathname); }
    el.addEventListener('click', e => {
      const b = e.target.closest('[data-au]'); if (!b) return;
      const rem = $('#au-rem', el)?.checked !== false;
      if (b.dataset.au === 'oidc') { const ret = afterLogin(); location.href = '/api/auth/oidc/start?remember=' + (rem ? 1 : 0) + (ret.startsWith('/oauth/authorize?') ? '&ret=' + encodeURIComponent(ret) : ''); }  // 2.674.0 (#4028): back to the consent page of an app (accounts/oidc.py oidc_ret_ok)
      if (b.dataset.au === 'passkey') authPasskey($('#au-err', el), rem);
      if (b.dataset.au === 'signup') signupScreen(el, logo, info);  // 2.23.0 (#711)
      if (b.dataset.au === 'forgot') lg_forgotScreen(el, logo, $('#au-user', el).value.trim());  // 2.49.0 (#1531)
      if (b.dataset.au === 'back') { el.remove(); $('#app')?.removeAttribute('inert'); authScreen(j); }
      if (b.dataset.au === 'pwshow') { const i = $('#au-pw', el), on = i.type === 'password'; i.type = on ? 'text' : 'password'; b.setAttribute('aria-pressed', String(on)); i.focus(); }  // 2.13.0 (#453 P7)
    });
    el.querySelector('#auth-form').addEventListener('submit', async e => {
      e.preventDefault();
      const errEl = $('#au-err', el);
      let tz = ''; try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { /* no zone: the server's stays */ }  // 2.368.3 (#2985): kept at the first login only
      const body = setup ? {username: $('#au-user', el).value.trim(), display_name: $('#au-name', el).value.trim(), password: $('#au-pw', el).value, wizard: true, lang: I18N.code || 'en', tz, ...($('#au-code', el) ? {setup_code: $('#au-code', el).value.trim()} : {})}  // 2.24.0 (UX-22): the language seen here sticks
        : {username: $('#au-user', el).value.trim(), password: $('#au-pw', el).value, remember: $('#au-rem', el).checked, tz};
      try {
        const r = await fetch(setup ? '/api/auth/setup' : '/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(body)});
        const res = await r.json().catch(() => ({}));
        if (!r.ok && res.deleting) { lg_delScreen(el, logo, {username: body.username, password: body.password, at: res.delete_at}); return; }  // 2.553.0 (#1413)
        if (!r.ok) { errEl.textContent = res.error || httpErrText(r.status); return; }
        if (setup) { await setupChoices(el, logo); return; }
        if (res.twofa) { await authTwofa(el, logo, res.methods || ['totp']); return; }
        if (res.enrol) { await authEnrol(el, logo); return; }
        location.replace(afterLogin());
      } catch { errEl.textContent = tr('Server not reachable.'); }
    });
    const dc = (location.hash.match(/delete-cancel=([\w.-]+)/) || [])[1];  // 2.553.0 (#1413): the link of the mail
    if (dc) { history.replaceState(null, '', location.pathname); lg_delScreen(el, logo, {token: dc}); }
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
  if (!r.ok) { const e = new Error(j.error || httpErrText(r.status)); e.status = r.status; e.j = j; throw e; }
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
const totpSetupHtml = j => `<p class="muted">${tr('Scan the QR code with an authenticator app (e.g. 2FAS, Aegis) and enter the 6-digit code.')}</p>
  <div class="totpqr"><img src="${esc(j.qr)}" alt="${tr('QR code')}" width="200" height="200"></div>
  <div class="row totpkey"><label>${tr('Key')}</label><code class="topic" id="totp-secret">${esc(j.secret)}</code></div>
  <input id="totp-code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="${tr('6-digit code')}" aria-label="${tr('6-digit code')}">`;
async function refreshMe() { try { S.me = {...S.me, ...(await api('GET', '/api/me'))}; } catch { /* offline */ } }
// ---- login screen: second step, forced enrolment, passkey login
async function authTwofa(el, logo, methods) {
  const card = el.querySelector('.card');
  let recovery = !methods.includes('totp') && !methods.includes('passkey');
  const draw = () => {
    card.innerHTML = `${logo}<p>${recovery ? tr('Enter one of your recovery codes.') : methods.includes('totp') ? tr('Enter the code from your authenticator app.') : tr('Confirm the sign-in with your passkey.')}</p>
      <form id="tfa-form" autocomplete="off">
        ${recovery || methods.includes('totp') ? `<input id="tfa-code" ${recovery ? 'autocapitalize="off" placeholder="xxxxx-xxxxx"' : `inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="${tr('6-digit code')}"`} aria-label="${recovery ? tr('Recovery code') : tr('6-digit code')}" required>
        <button class="btn pri" type="submit">${tr('Verify')}</button>` : ''}
        ${methods.includes('passkey') && !recovery ? `<button type="button" class="btn ${methods.includes('totp') ? '' : 'pri'}" data-tfa="pk" ${pkSupported() ? '' : 'disabled'}>${ic('key', 's')} ${tr('Use a passkey')}</button>` : ''}
        <div class="aerr" role="alert" id="tfa-err"></div>
        <div class="alinks">${methods.includes('recovery') && !recovery ? `<button type="button" class="linkbtn" data-tfa="rc">${tr('Use a recovery code')}</button>` : ''}${recovery && (methods.includes('totp') || methods.includes('passkey')) ? `<button type="button" class="linkbtn" data-tfa="back2">${tr('Back')}</button>` : ''}<button type="button" class="linkbtn" data-tfa="restart">${tr('Sign in again')}</button></div>
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
    card.innerHTML = `${logo}<p>${tr('Two-factor authentication is required on this server. Set it up now, then you are signed in.')}</p>
      <div class="enrolopts"><button type="button" class="btn pri" data-en="totp">${ic('lock', 's')} ${tr('Use an authenticator app')}</button>
      <button type="button" class="btn" data-en="pk" ${pkSupported() ? '' : 'disabled'}>${ic('key', 's')} ${tr('Use a passkey')}</button></div>
      ${pkSupported() ? '' : `<p class="muted">${tr('Passkeys need HTTPS (or localhost), a host name instead of an IP address and a current browser.')}</p>`}
      <div class="aerr" role="alert" id="en-err"></div><div class="alinks"><button type="button" class="linkbtn" data-en="restart">${tr('Sign in again')}</button></div>`;
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
        card.innerHTML = `${logo}<form id="en-totp">${totpSetupHtml(t)}<div class="aerr" role="alert" id="totp-err"></div><button class="btn pri" type="submit">${tr('Switch on')}</button></form><div class="alinks"><button type="button" class="linkbtn" data-en="back">${tr('Back')}</button></div>`;
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
// 2.611.0 (#4019): an admin without a password: the server asks a fresh sign-in (403 reauth_needed) before a switch that
// opens the server. Passkey: signed in again here, true = send the switch again. OIDC: the step-up at the provider
// (prompt=login), back on the page the switch is turned again by hand (ocStepUpBack: "Confirmed. Now try the step again.")
async function reauthFresh(d) {
  if (d.stepup !== 'oidc' && !d.passkey) { toast(d.error || tr('Please sign in again, then try again.')); return false; }
  if (!await askConfirm(tr('Sign in again'), d.error, {ok: tr('Sign in again')})) return false;
  if (d.stepup === 'oidc') {
    try { sessionStorage.setItem('rck-stepup', '0:su'); } catch { /* storage off: no message on the way back */ }
    location.href = '/api/auth/oidc/start?stepup=su&org=0';
    return false;
  }
  try {
    const j = await authPost('/api/auth/passkey', {credential: await pkGet(await authPost('/api/auth/passkey/options', {keep: true}))});
    if (S.me && j.user?.id !== S.me.id) { location.replace('/'); return false; }  // another account's passkey: that account now
    return true;
  } catch (x) { toast(x instanceof Error && x.j ? x.message : pkErr(x)); return false; }
}
document.addEventListener('change', async e => {
  const id = e.target.id; if (id !== 's-signup' && id !== 's-sdom' && id !== 's-oinv' && id !== 's-spriv' && id !== 's-cinv') return;
  try {
    const b = id === 's-signup' ? {signup_mode: e.target.value} : id === 's-oinv' ? {org_invites: e.target.checked} : id === 's-spriv' ? {signup_private: e.target.checked} : id === 's-cinv' ? {cinv_signup: e.target.checked} : {signup_domains: e.target.value};  // 2.115.0 B (#2062): + s-oinv; 2.422.0 (#2937): + s-spriv
    const ask = id === 's-signup' || id === 's-spriv' || id === 's-cinv';  // 2.1156.0 (#4550): switching it on asks for the password
    let j; try { j = await (ask ? rawFetch : api)('PATCH', '/api/admin/settings', b); } catch (x) {  // 2.360.0 A (#2496): the mode asks for the password
      if (ask && x.data?.reauth_needed) { if (!await reauthFresh(x.data)) throw x; j = await api('PATCH', '/api/admin/settings', b); } else {  // 2.611.0 (#4019)
      if (!x.data?.password_needed) { if (ask) toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); throw x; }
      const p = await pwPrompt(tr('Confirm with your password')); if (!p) throw x;
      j = await api('PATCH', '/api/admin/settings', {...b, password: p.password}); }
    }
    if (j && j.version) S.about = j;
    const r = $('#s-sdomrow'); if (r) r.hidden = (S.about?.signup_mode || 'off') !== 'domain';
    if (id === 's-sdom') e.target.value = S.about?.signup_domains || '';
    if (id === 's-spriv') { const o = $('#s-signup option[value="open"]'); if (o && S.about?.mail_out) o.disabled = !S.about?.signup_private; }  // 2.422.0 (#2937)
    toast(tr('Saved'));
  } catch {
    if (id === 's-signup') e.target.value = S.about?.signup_mode || 'off';
    if (id === 's-spriv') e.target.checked = !!S.about?.signup_private;
    if (id === 's-cinv') e.target.checked = !!S.about?.cinv_signup;  // 2.1156.0 (#4550)
  }
});
// the form "Create account" on the login page (#711)
// 2.49.0 (#1531): "Forgot your password?": e-mail address or user name -> a one-time link by mail (the answer is always the same)
// 2.553.0 (#1413): an account whose deletion was asked for: the sign-in (right password) or the mail's link offers only
// "Cancel the deletion" (POST /api/auth/delete-cancel, admin/selfdelete.py); afterwards the ordinary sign-in
function lg_delScreen(el, logo, o) {
  el.innerHTML = `<div class="card">${logo}
    <h2 class="invh">${tr('Your account will be deleted')}</h2>
    <p role="status">${esc(o.at ? tr('Your account will be deleted permanently on {0}. It is locked until then.', fmtDate(String(o.at).slice(0, 10))) : tr('Cancel the deletion of your account? It can be used again afterwards.'))}</p>
    <div class="aerr" role="alert" id="dc-err"></div>
    <button class="btn pri" type="button" data-dc="go">${tr('Cancel the deletion')}</button>
    <button class="linkbtn" type="button" data-au="back">${tr('Back to sign-in')}</button></div>`;
  $('[data-dc="go"]', el).addEventListener('click', async e => {
    const b = e.currentTarget; b.disabled = true;
    try {
      await authPost('/api/auth/delete-cancel', o.token ? {token: o.token} : {username: o.username, password: o.password});
      $('.card', el).innerHTML = `${logo}<h2 class="invh">${tr('The deletion was cancelled')}</h2><p role="status">${tr('Your account can be used again. Please sign in.')}</p><button class="btn pri" type="button" data-au="back">${tr('Go to sign-in')}</button>`;
    } catch (x) { $('#dc-err', el).textContent = x.message; b.disabled = false; }
  });
}
function lg_forgotScreen(el, logo, pre = '') {
  el.innerHTML = `<div class="card">${logo}
    <h2 class="invh">${tr('Forgot your password?')}</h2>
    <p class="muted">${tr('E-mail address or user name – we send a link for a new password.')}</p>
    <form id="fg-form" autocomplete="on">
      <label class="aulab" for="fg-login">${tr('E-mail or user name')}</label><input id="fg-login" name="username" autocomplete="username" autocapitalize="off" spellcheck="false" maxlength="200" required value="${esc(pre)}">
      <div class="aerr" role="alert" id="fg-err"></div>
      <button class="btn pri" type="submit">${tr('Send the link')}</button>
      <button class="linkbtn" type="button" data-au="back">${tr('Back to sign-in')}</button>
    </form></div>`;
  el.querySelector('#fg-form').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = $('#fg-err', el), btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
      const r = await fetch('/api/auth/forgot', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({login: $('#fg-login', el).value.trim()})});
      const res = await r.json().catch(() => ({}));
      if (!r.ok) { errEl.textContent = res.error || httpErrText(r.status); btn.disabled = false; return; }
      $('.card', el).innerHTML = `${logo}<h2 class="invh">${tr('Check your e-mail')}</h2><p role="status" class="lgsent">${tr('If an account with a stored e-mail address matches, a link to set a new password is on its way.')}</p><p class="muted">${tr('No e-mail after a few minutes? Look in the spam folder or ask an admin.')}</p><button class="btn" type="button" data-au="back">${tr('Back to sign-in')}</button>`;
    } catch { errEl.textContent = tr('Server not reachable.'); btn.disabled = false; }
  });
  setTimeout(() => $('#fg-login', el)?.focus(), 50);
}
function signupScreen(el, logo, info) {
  const pw = !!info.signup?.password;
  el.innerHTML = `<div class="card">${logo}
    <h2 class="invh">${tr('Create account')}</h2>
    <p class="muted">${esc(info.signup?.mode === 'approval' ? tr('An admin approves new accounts before the first sign-in.') : tr('You get an e-mail with a link to confirm your address and choose your password.'))}</p>
    <form id="su-form" autocomplete="on">
      <label class="aulab" for="su-name">${tr('Your name')}</label><input id="su-name" name="name" autocomplete="name" maxlength="60" required>
      <label class="aulab" for="su-mail">${tr('E-mail')}</label><input id="su-mail" name="email" type="email" autocomplete="email" autocapitalize="off" required>
      ${pw ? `<label class="aulab" for="su-pw">${tr('Password')}</label><input id="su-pw" type="password" autocomplete="new-password" minlength="${info.signup.min_password || 8}" required placeholder="${esc(tr('at least {0} characters', info.signup.min_password || 8))}">` : ''}
      <div class="aerr" role="alert" id="su-err"></div>
      <button class="btn pri" type="submit">${tr('Create account')}</button>
      <button class="linkbtn" type="button" data-au="back">${tr('Back to sign-in')}</button>
    </form></div>`;
  el.querySelector('#su-form').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = $('#su-err', el);
    try {
      const r = await fetch('/api/auth/signup', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'},
        body: JSON.stringify({name: $('#su-name', el).value.trim(), email: $('#su-mail', el).value.trim(), lang: I18N.code || 'en', ...(pw ? {password: $('#su-pw', el).value} : {})})});
      const res = await r.json().catch(() => ({}));
      if (!r.ok) { errEl.textContent = res.error || httpErrText(r.status); return; }
      $('.card', el).innerHTML = `${logo}<h2 class="invh">${tr('Almost done')}</h2><p role="status">${esc(res.mail ? tr('If the address can be used, an e-mail with a link is on its way. Open it to choose your password.') : tr('Your account waits for an admin to approve it. You can sign in once it is approved.'))}</p><button class="btn" type="button" data-au="back">${tr('Back to sign-in')}</button>`;
    } catch { errEl.textContent = tr('Server not reachable.'); }
  });
  setTimeout(() => $('#su-name', el)?.focus(), 50);
}
const fmtBytes = n => fmtSize(Math.max(n || 0, 1024));  // 2.450.0 (#3770): fmtSize, at least "1 KB"
const PURPOSES = [['me', 'user', N_('For me'), N_('Your own tasks: projects, reminders and the calendar. More views any time under Settings > Modules.')],
  // 2.22.0 (#741): "Home" for one person or a couple: Home & life with contracts, devices, staying in touch, health, journal
  ['home', 'home', N_('Home|area'), N_('Your household and life: contracts, warranties and upkeep, staying in touch, health, a journal, trips and read later.')],
  ['family', 'family', N_('Family'), N_('Shared projects, a shopping list with shop areas, household chores taking turns, birthdays, a meal plan and accounts for children.')],
  ['team', 'users', N_('Team'), N_('Sharing, assigning, comments, time tracking, a timeline with dependencies, custom fields and project progress.')],
  ['software', 'code', N_('Software projects'), N_('Everything of Team plus a software project: a board from backlog to done, bug and feature tickets, a repository.')],
  // 2.36.1 (#1021): the business area
  ['office', 'brief', N_('Office & finance'), N_('Everything of Team plus clients, workload, forms and the office: services and rates, quotations with a calculator, text blocks and PDF documents of your organisation.')]];
const PURPOSE_MODS = {me: ['cal', 'events', 'contacts'],
  home: ['cal', 'events', 'contacts', 'habits', 'contracts', 'home', 'care', 'health', 'review', 'travel', 'reading'],
  family: ['cal', 'habits', 'comments', 'collab', 'family', 'events', 'contacts', 'contracts', 'home', 'travel'],
  // 2.25.0 (UX-25): Team / Software hold only what the name promises (no habits, focus timer, matrix, statistics)
  team: ['cal', 'timeline', 'kanban', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts', 'agents'],
  software: ['cal', 'timeline', 'kanban', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts'],
  office: ['cal', 'timeline', 'kanban', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts', 'clients', 'workload', 'forms', 'office', 'agents']};
// 2.36.1 (#1021): the modules a purpose switches ON in addition (never off by another purpose; server: PURPOSE_EXTRA)
// 2.217.0 B (#2797): Team and Office & finance switch the module Agents on too (server: PURPOSE_EXTRA)
const PURPOSE_EXTRA = {office: ['clients', 'workload', 'forms', 'office', 'agents', 'videos'], team: ['agents', 'videos']};  // 2.623.0 (#4765): + videos (Approval), as the server
// First-run setup, step 2 ("What do you want to use?"): only right after the first admin was created, never on
// existing installs. Three presets (1.2: "Simple list"; "Just me" preselected; "Projects & team" = everything), then
// the single modules to fine-tune. Collaboration + time tracking are the instance switches; the other modules
// become the default of new users (the admin gets them too). "Skip" leaves everything on. All changeable later.
const SETUP_MAIN = [['collab', N_('Collaboration'), N_('Share projects, assign tasks, @mentions, history and News')],
  ['a:time', N_('Time|area'), N_('Time tracking on tasks with reports, and the focus timer')]];  // 2.44.0 (#1187): the area Time
// 2.44.0 (#1187): the areas offered here and the modules each one switches (Office: contacts here; clients and the office come
// with the purpose "Office & finance", server PURPOSE_EXTRA); with a matching purpose only the modules the purpose holds
const MG_SU_AREA = {'a:time': ['time', 'pomo'], 'a:review': ['review', 'stats'], 'a:life': ['family', 'contracts', 'home', 'care', 'health', 'travel', 'reading'], 'a:office': ['contacts']};
const mg_suIn = (k, x) => MG_SU_AREA[x] ? MG_SU_AREA[x].some(p => PURPOSE_MODS[k].includes(p)) : PURPOSE_MODS[k].includes(x);
const mg_suHas = (on, x) => MG_SU_AREA[x] ? MG_SU_AREA[x].some(p => on.has(p)) : on.has(x);
const SETUP_MODS = [['cal', N_('Calendar'), N_('Month, week and day view of your tasks')], ['timeline', N_('Timeline'), N_('Tasks with start and end as bars over time')],
  ['events', N_('Events'), N_('Appointments and shared calendars, synced with the phone')],
  ['a:office', N_('Office|area'), N_('Your contacts; clients and the office come with “Office & finance”')],
  ['matrix', N_('Eisenhower matrix'), N_('Urgent and important in four quadrants')], ['kanban', N_('Kanban'), N_('Projects as boards with columns')],
  ['habits', N_('Habits'), N_('Daily and weekly habits with streaks')],
  ['a:review', N_('Review|area'), N_('Statistics, and your day and week in review with a private journal')], ['progress', N_('Project progress'), N_('Progress per project and the project status (“Where is it stuck?”)')],
  ['deps', N_('Dependencies'), N_('Tasks blocked by other tasks, with arrows in the timeline (Gantt)')], ['fields', N_('Custom fields'), N_('Own fields per project, such as budget, client or phase')],
  ['comments', N_('Comments'), N_('Timestamped notes on tasks')],
  ['a:life', N_('Home|area'), N_('Family (chores, shopping, meal plan, accounts for children) and Home & life (contracts, devices, health, trips)')]];
// 2.7.0 (K21, #405): a simple start for a new instance; one question "Start with" below. 2.19.0 (#653): the presets are the
// answers to "What do you use Kalmido for?" (For me = the simple start, Family, Team, Software projects)
const SETUP_PRESETS = Object.fromEntries(PURPOSES.map(([k, i, n, d]) => [k, {name: n, icon: i, desc: d,
  off: [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]).filter(x => !mg_suIn(k, x))}]));
// 2.25.0 (UX-19): the same count as Settings > Modules. 2.364.0 A (#3015): counted the same way, too: the single modules
// the setup switches on (as the server's admin_setup: the modules sent, collaboration and time, the purpose's extras or
// "all modules") against every single module there (an area by its parts, without what is switched off for everyone)
const SU_LIFE = ['contracts', 'home', 'care', 'health', 'review', 'travel', 'reading'];  // server: family._LIFE
function setupCount(picked, mods, purpose, modsAll) {
  const fk = new Set(FEATS.map(x => x[0]));
  const units = [...new Set(MOD_GROUPS.flatMap(([, ks]) => ks).flatMap(k => k.startsWith('a:') ? mg_feats(k.slice(2)) : [k]))]
    .filter(k => fk.has(k) && !(k === 'collab' && !picked.has('collab')) && !(k === 'time' && !picked.has('a:time')));
  const on = new Set([...mods, 'collab', 'time']);
  if (purpose && modsAll === true) units.forEach(k => on.add(k));
  else if (purpose && modsAll !== false) [...(PURPOSE_MODS[purpose] || []).filter(k => SU_LIFE.includes(k)), ...(PURPOSE_EXTRA[purpose] || [])].forEach(k => on.add(k));
  return tr('{0} of {1} modules on', units.filter(k => on.has(k)).length, units.length);
}
// 2.364.0 A (#3015): what a start adds on top of the modules ticked below (they differ only there: Team, Software projects
// and Office & finance offer the same modules here)
const SU_ADDS = {team: () => [tr('Agents')], software: () => [tr('a software project with a board')],
  office: () => ['clients', 'workload', 'forms', 'office', 'agents'].map(k => tr(FEATS.find(x => x[0] === k)?.[1] || k))};
async function setupChoices(el, logo) {
  let st = {};
  try { st = await (await fetch('/api/state?lz=1&lzl=', {headers: {'X-Requested-With': 'kalmido'}})).json(); } catch { /* offline: defaults */ }
  const langs = st.languages || [{code: 'en', name: 'English'}];
  const all = [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]);
  let lang = I18N.code || 'en', preset = 'me', picked, custOpen = false, start = '';
  const askOrg = st.about?.instance_mode !== 'shared' && !st.about?.org_name_env && !st.about?.has_orgs;  // 2.23.0 (#799): asked once; 2.46.0 (#1592): creates the first organisation
  // 2.24.0 (UX-23): the purpose first; the name of the organisation only for a team / company, empty allowed (the
  // instance's default name is not offered as a value), changeable later under Administration > Organisation
  let industry = indCodes(st.industry);  // 2.578.0 (#4573): the app's industry, default none; 2.828.0 (#5511): the codes ticked
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
    const fits = k => !!SETUP_PRESETS[k] && all.every(x => picked.has(x) === !SETUP_PRESETS[k].off.includes(x));
    preset = fits(st.settings?.purpose || '-') ? st.settings.purpose : Object.keys(SETUP_PRESETS).find(fits) || '';  // 2.364.0 A (#3015): the chosen start, not the first fitting
  }
  // 2.7.0 (K21): one question "Start with": empty, the sample project, or a project of a built-in type (agency, software, personal)
  const STARTS = [['', N_('Empty|start'), 'list', N_('Your Basket and Today, nothing else')], ['sample', N_('Sample project'), 'eye', N_('A small client project with dates and a checklist, to look around; remove it any time under Settings > Data')],  // 2.578.0 (#4573): the film text only with Film & Video (draw)
    ...PTYPE_UI.slice(1).filter(([k]) => k !== 'social').map(([k, n, i, d]) => [k, n, i, d]),  // 2.670.0 (#5120): Social media plan (#1957) is no start card of the setup
    ['import', N_('Import from another app'), 'download', N_('Todoist, Trello, Asana, Notion and more: you start empty and the import opens right away')]];  // 2.538.0 (#4361)
  const row = ([k, n, d]) => `<label class="suse"><input type="checkbox" data-use="${k}" ${picked.has(k) ? 'checked' : ''}><span><b>${tr(n)}</b><small class="muted">${tr(d)}</small></span></label>`;
  // 2.144.2 A (#2369): preset '' (modules fit no purpose) matches nothing, so "Start" switches nothing extra off
  const matches = k => !!SETUP_PRESETS[k] && all.every(x => picked.has(x) === !SETUP_PRESETS[k].off.includes(x));
  // 2.364.0 A (#3015): only the tile picked is marked (Team, Software projects and Office & finance hold the same modules
  // here, so matching alone marked all three), and only while the ticks still fit it
  const isOn = k => k === preset && matches(k);
  const suMods = () => [...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]).filter(k => picked.has(k) && k !== 'collab').flatMap(k => MG_SU_AREA[k] ? MG_SU_AREA[k].filter(p => !matches(preset) || PURPOSE_MODS[preset].includes(p)) : [k]);
  const suPurpose = () => matches(preset) || (modsAll !== null && preset) ? preset : '';
  const suCount = () => setupCount(picked, suMods(), suPurpose(), modsAll);
  const suAllSync = () => { const a = $('#su-modsall', el); if (a) a.indeterminate = !a.checked && SETUP_MODS.some(([k]) => picked.has(k)); };  // 2.364.0 A (#3015): some on = half
  // 2.312.0 B (#3264): the note on health data (Art. 9 GDPR) while Home or Review (health, journal) is picked
  const suPriv = () => modPrivHtml(['a:life', 'a:review'].filter(x => picked.has(x)).flatMap(x => MG_SU_AREA[x]));
  const draw = () => {
    el.innerHTML = `<div class="card setupcard">${logo}
      ${''/* 2.365.0 (#2802): the language as a small menu top right (it took half a phone screen; the browser's language is preselected) */}<details class="sulang" id="su-lang"><summary title="${esc(tr('Language'))}">${ic('globe', 's')}<span>${langName(langs.find(L => L.code === lang) || {code: lang, name: lang})}</span></summary><div class="sulangs">${langs.map(L => `<button type="button" data-su-lang="${esc(L.code)}" class="${L.code === lang ? 'on' : ''}" lang="${esc(L.code)}" aria-pressed="${L.code === lang}">${langName(L)}</button>`).join('')}</div></details>
      <h3>${tr('What do you use Kalmido for?')}</h3>
      <p class="muted">${tr('Select a start, untick what you do not need. Can be changed later.')}</p>
      <div class="supresets">${Object.entries(SETUP_PRESETS).map(([k, p]) => `<button type="button" class="supreset ${isOn(k) ? 'on' : ''}" data-su-preset="${k}" aria-pressed="${isOn(k)}"><b>${ic(p.icon, 's')}${tr(p.name)}</b> <small class="muted">${tr(p.desc)}</small>${SU_ADDS[k] ? ` <small class="suadds">${esc(tr('Adds: {0}', SU_ADDS[k]().join(', ')))}</small>` : ''}</button>`).join('')}</div>
      <div class="supriv" id="su-priv">${suPriv()}</div>
      ${pm_allHtml('su-modsall', modsAll ?? SETUP_MODS.every(([k]) => picked.has(k)))}
      ${askOrg && ['team', 'software', 'office'].includes(preset) ? `<h3><label for="su-org">${tr('Name of your team or company')} <span class="muted">${tr('(optional)')}</span></label></h3><input id="su-org" class="suorg" maxlength="60" value="${esc(orgName)}" placeholder="${esc(tr('e.g. your company'))}"><p class="muted">${tr('Shown next to the app name and in invitations.')}</p>` : ''}
      <details class="sucust" ${custOpen ? 'open' : ''}><summary>${tr('Customise…')} <span class="muted">${esc(suCount())}</span></summary>
      <div class="suse-main">${SETUP_MAIN.map(row).join('')}</div>
      <div class="suse-list">${SETUP_MODS.map(row).join('')}</div></details>
      <h3 id="su-start-h">${tr('Start with')}</h3>
      <div class="sustarts ptcards" role="radiogroup" aria-labelledby="su-start-h">${STARTS.map(([k, n, i, d]) => `<button type="button" class="ptcard ${k === start ? 'on' : ''}" role="radio" aria-checked="${k === start}" data-su-start="${k}">${ic(i, 's')}<b>${tr(n)}</b><small class="muted">${k === 'sample' && industry.includes('film') ? tr('A small video production with dates and a packing list, to look around; remove it any time under Settings > Data') : tr(d)}</small></button>`).join('')}</div>
      ${st.industry?.choices?.length ? `<h3 id="su-ind-l">${tr('Industry')}</h3>${/*html-ok*/ indBoxes(st.industry, industry, 'su-ind', 'su-ind-l')}<p class="muted">${tr('Adds the functions of the industries ticked to the whole app, several at once, e.g. Film & Video: the shoot calculation in quotations and the image film as sample project. None ticked: everything stays general.')}</p>` : ''}${''/* 2.578.0 (#4573) */}
      <div class="aerr" role="alert" id="su-err"></div>
      <div class="sufoot"><button type="button" class="btn pri" data-su="go">${tr('Start')}</button></div></div>`;
    $('.sucust', el)?.addEventListener('toggle', e => { custOpen = e.target.open; });
    suAllSync();
  };
  draw();
  el.addEventListener('input', e => { if (e.target.id === 'su-org') orgName = e.target.value; });
  el.addEventListener('change', e => {
    if (e.target.id === 'su-modsall') { modsAll = e.target.checked; pm_su(); draw(); return; }
    if (e.target.closest('#su-ind')) { industry = indPicked($('#su-ind', el)); draw(); return; }  // 2.578.0 (#4573); 2.828.0 (#5511): boxes
    const c = e.target.closest('[data-use]'); if (!c) return;
    c.checked ? picked.add(c.dataset.use) : picked.delete(c.dataset.use);
    $$('[data-su-preset]', el).forEach(b => { b.classList.toggle('on', isOn(b.dataset.suPreset)); b.setAttribute('aria-pressed', isOn(b.dataset.suPreset)); });
    const sm = $('.sucust summary .muted', el); if (sm) sm.textContent = suCount();
    const ma = $('#su-modsall', el); if (ma && modsAll === null) ma.checked = SETUP_MODS.every(([k]) => picked.has(k)); suAllSync();
    const sp = $('#su-priv', el); if (sp) sp.innerHTML = suPriv();  // 2.312.0 B (#3264)
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
    const post = async (url, body) => { const r = await fetch(url, {method: url.endsWith('settings') ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(body)}); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || httpErrText(r.status)); };
    try {
      if (b.dataset.su === 'go') await post('/api/admin/setup', {lang, collab_all: picked.has('collab'), time_all: picked.has('a:time'), modules: suMods(), sample: start === 'sample', ...(industry.length ? {industries: industry} : {}), ...(start && start !== 'sample' && start !== 'import' ? {project_type: start} : {}), ...(suPurpose() ? {purpose: suPurpose()} : {}), ...(modsAll !== null ? {all_modules: modsAll} : {}), examples: start === 'sample', ...(askOrg && ['team', 'software', 'office'].includes(preset) && orgName.trim() ? {org_name: orgName.trim()} : {})});
      else return;
      if (start === 'import') { try { sessionStorage.setItem('kalmido-suimport', '1'); LS.set('settingsSec', 'data'); } catch { /* private mode: the card only starts empty */ } }  // 2.538.0 (#4361): main.js opens Settings > Data > Import
      location.replace('/');
    } catch (err) { $('#su-err', el).textContent = err.message || tr('Server not reachable.'); }
  });
}
function sectionMenu(anchor, sid, head = []) {  // 2.1151.0 B (#3835): head = items on top (dnd.js secHeadMenu: the head's "+")
  const s = S.sections.find(x => x.id === sid);
  menu(anchor, [...head,
    {label: tr('Rename'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename section'), s.name, {ok: tr('Rename')}); if (n && n.trim()) sectionRename(sid, n.trim()); }},
    ...(isTouch() ? [] : [  // 2.1151.0 B (#3835): a touch screen drags the head (dnd.js / secdrag.js)
      {label: tr('Move left / up'), icon: 'left', fn: () => moveSection(sid, -1)},
      {label: tr('Move right / down'), icon: 'right', fn: () => moveSection(sid, 1)}]),
    wip_menuItem(sid),  // 2.60.0 (#1510)
    dw_menuItem(sid),  // 2.410.0 B (#3515)
    sk_menuItem(sid, anchor),  // 2.577.0 (#3354)
    '-',
    {label: tr('Delete section (tasks stay)'), icon: 'trash', cls: 'flag-5', fn: () => sectionDelete(sid)},
  ]);
}

async function sampleCreate({open = true} = {}) {
  let j; try { j = await api('POST', '/api/sample', {}); } catch { return null; }
  await load();
  toast(j.created ? tr('Sample project created') : tr('The sample project already exists'));
  if (open && j.list_id) go('l/' + j.list_id); else render();
  return j;
}
function sampleSummary(sm) {
  const extra = sm.lists.reduce((a, l) => a + (l.extra || 0), 0);
  return [sm.lists.length ? tr('Removes {0} and their {1}.', sm.lists.map(l => `“${l.name}”`).join(tr(' and ')), trn('{0} sample task', '{0} sample tasks', sm.tasks))
    : trn('Removes {0} sample task.', 'Removes {0} sample tasks.', sm.tasks),
  extra ? trn('{0} task you added stays, and so does its project.', '{0} tasks you added stay, and so do their projects.', extra) : '',
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
