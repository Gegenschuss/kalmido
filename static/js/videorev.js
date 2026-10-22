/* Kalmido web client: video sign-offs (2.99.1 A, #1959), module "videos" (loaded on demand: lazyload.js).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// A video sign-off holds links only (Vimeo, YouTube, a direct video file over https; Kalmido stores no video), each new link
// a version. Comments sit at a second of their version: typing pauses the player and keeps its time ("at 01:23", tap to drop
// it), a tap on a timecode or a mark on the time line jumps there. The player is driven through its postMessage protocol:
// no script of Vimeo / YouTube is loaded; messages count only from the player's own frame and origin. Sections: a task's
// panel (detail.js), a project's overview (projects.js), a client's card (clientpage.js). Every action is one undo step.
const VDR = {by: {}, busy: {}, cur: null};
const VDR_ORIGIN = {youtube: 'https://www.youtube-nocookie.com', vimeo: 'https://player.vimeo.com'};
const VDR_ST = {open: N_('In review'), approved: N_('Approved|video'), changes: N_('Changes requested')};
const vdr_p2 = n => String(n).padStart(2, '0');
function vdr_tc(s) {
  if (s == null) return '';
  s = Math.floor(s);
  const h = Math.floor(s / 3600);
  return h ? `${h}:${vdr_p2(Math.floor(s / 60) % 60)}:${vdr_p2(s % 60)}` : `${vdr_p2(Math.floor(s / 60))}:${vdr_p2(s % 60)}`;
}
const vdr_key = (k, id) => `${k}:${id}`;

// ---- the sections (a task, a project, a client): the reviews there + "Add video link"
function vdr_rows(k, id, redraw) {
  const key = vdr_key(k, id), c = VDR.by[key];
  if (!c && !VDR.busy[key]) {
    VDR.busy[key] = 1;
    api('GET', `/api/videos?${k}=${id}`).then(j => { VDR.by[key] = j.reviews || []; }, () => { VDR.by[key] = []; })
      .finally(() => { delete VDR.busy[key]; redraw(); });
  }
  return c || null;
}
function vdr_listHtml(rows, k, id, add) {
  const li = rows.map(r => `<li><button type="button" class="vdrrow" data-vdr="open" data-id="${r.id}">${ic('film', 's')}<span class="vdrrt"><b>${esc(r.title)}</b>
    <small class="muted">${esc([`v${r.version}`, tr(VDR_ST[r.state] || r.state), r.open_comments ? trn('{0} open comment', '{0} open comments', r.open_comments) : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="vdrst st-${esc(r.state)}" aria-hidden="true"></span></button></li>`).join('');
  return (li ? `<ul class="vdrrows" role="list">${li}</ul>` : '')
    + (add ? `<button type="button" class="btn sm vdradd" data-vdr="new" data-k="${k}" data-i="${id}">${ic('plus', 's')} ${tr('Add video link')}</button>` : '');
}
// 2.96.3 (#1959): the section arrives after the detail - redraw it without taking the focus (comment box of #reply/<id>)
function vdr_redrawTask(tid) {
  if (S.sel !== tid || typeof renderDetail !== 'function') return;
  const a = document.activeElement, id = a?.id, ss = a?.selectionStart, se = a?.selectionEnd;
  renderDetail();
  const n = id && document.getElementById(id);
  if (n && n !== document.activeElement) { n.focus({preventScroll: true}); try { if (ss != null) n.setSelectionRange(ss, se); } catch (e) { /* not a text field */ } }
}
function vdr_redrawView() { if (S.route.mod === 'clients' && typeof ms_clDraw === 'function') ms_clDraw(); else renderView(); }
function vdr_taskHtml(t, ro) {
  if (!t || !(t.id > 0) || t.context) return '';
  const rows = vdr_rows('task_id', t.id, () => vdr_redrawTask(t.id));
  if (!rows) return '';
  if (ro && !rows.length) return '';
  return `<div class="dsec vdrsec" id="d-vdr"><h5>${tr('Video sign-off')}</h5>${vdr_listHtml(rows, 'task_id', t.id, !ro)}</div>`;
}
const vdr_count = t => (VDR.by[vdr_key('task_id', t.id)] || []).length;  // detail.js: a task with reviews shows the section outside "More details"
function vdr_projHtml(l) {
  if (!l || l.e2e) return '';
  const rows = vdr_rows('list_id', l.id, vdr_redrawView);
  if (!rows) return '';
  const add = typeof canEditList === 'function' && canEditList(l.id);
  if (!rows.length && !add) return '';
  return `<section class="povs vdrpov" id="pov-videos"><div class="povh"><h3>${tr('Video sign-offs')}</h3></div>${vdr_listHtml(rows, 'list_id', l.id, add)}</section>`;
}
function vdr_clientHtml(c) {
  if (!c || !c.id) return '';
  const rows = vdr_rows('client_id', c.id, vdr_redrawView);
  if (!rows) return '';
  return `<div class="ctsec vdrcl"><h4>${tr('Video sign-offs')}</h4>${vdr_listHtml(rows, 'client_id', c.id, true)}</div>`;
}
// a review changed: the cached sections follow (it leaves every other place, its own place shows it)
function vdr_cache(r, gone) {
  const home = r.task_id ? vdr_key('task_id', r.task_id) : r.list_id ? vdr_key('list_id', r.list_id) : r.client_id ? vdr_key('client_id', r.client_id) : '';
  for (const key of Object.keys(VDR.by)) {
    const rows = VDR.by[key], i = rows.findIndex(x => x.id === r.id);
    if (key === home && !gone) { if (i >= 0) rows[i] = r; else rows.unshift(r); } else if (i >= 0) rows.splice(i, 1);
  }
  if (r.task_id) vdr_redrawTask(r.task_id);
  vdr_redrawView();
}
const vdr_forget = () => { VDR.by = {}; };

// ---- a new review: a link (+ an optional title)
function vdr_new(k, id) {
  const md = modal(`<form class="vdrform" novalidate><h3 id="vdr-nt">${tr('Add video link')}</h3>
    <p class="muted mhint">${esc(tr('Kalmido stores no videos: paste a link from Vimeo, YouTube (also unlisted) or a direct video file (MP4, WebM, MOV) over https.'))}</p>
    <label for="vdr-url">${tr('Video link')}</label><input id="vdr-url" type="url" inputmode="url" autocomplete="off" placeholder="https://" maxlength="2000" required>
    <label for="vdr-ttl">${tr('Title')}</label><input id="vdr-ttl" maxlength="200" placeholder="${esc(tr('e.g. Rough cut'))}">
    <div class="calerr" role="alert" hidden></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="submit" class="btn pri">${tr('Add')}</button></div></form>`);
  md.setAttribute('aria-labelledby', 'vdr-nt');
  setTimeout(() => $('#vdr-url', md)?.focus(), 60);
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) md.remove(); });
  $('form', md).addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('.calerr', md), ok = $('[type="submit"]', md);
    ok.disabled = true; err.hidden = true;
    let r;
    try { r = await rawFetch('POST', '/api/videos', {[k]: id, url: $('#vdr-url', md).value.trim(), title: $('#vdr-ttl', md).value.trim()}); } catch (x) { err.textContent = x.message; err.hidden = false; ok.disabled = false; return; }
    md.remove();
    vdr_cache(r);
    const h = histAdd({label: tr('Created {0}', qn(r.title)), ids: [], snaps: [], lids: [],
      undo: async () => { await rawFetch('DELETE', `/api/videos/${r.id}`); vdr_cache(r, true); vdr_closeIf(r.id); return {skipped: []}; },
      redo: async () => { vdr_cache(await rawFetch('POST', `/api/videos/${r.id}/restore`)); return {skipped: []}; }});
    histToast(tr('Video sign-off {0} created', qn(r.title)), h);
    vdr_open(r.id, r);
  });
}

// ---- the player (iframe of the built URL or <video>), driven by postMessage
function vdr_playerHtml(v, title) {
  if (!v) return '';
  if (v.provider === 'youtube' || v.provider === 'vimeo') {
    const src = v.embed + (v.provider === 'youtube' ? '&origin=' + encodeURIComponent(location.origin) : '');
    return `<div class="vdrplay" data-prov="${v.provider}"><iframe src="${esc(src)}" title="${esc(title)}" allow="fullscreen; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>`;
  }
  if (v.provider === 'file') return `<div class="vdrplay" data-prov="file"><video src="${esc(v.embed)}" controls playsinline preload="none"></video></div>`;
  return `<div class="vdrnolink">${ic('info', 's')}<p>${esc(tr('This link has no time control: it opens in a new tab, comments get no timecode.'))}</p>
    <a class="btn sm" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${ic('link', 's')} ${tr('Open the video')}</a></div>`;
}
function vdr_ctl(box, prov, on) {
  const fr = box && $('iframe', box), vid = box && $('video', box), origin = VDR_ORIGIN[prov] || '';
  const c = {cur: 0, dur: 0, stop: () => {}};
  const send = o => { try { fr.contentWindow.postMessage(JSON.stringify(o), origin); } catch { /* the frame is gone */ } };
  const dur = d => { if (+d > 0 && !c.dur) { c.dur = +d; on('dur'); } };
  c.pause = () => { if (vid) vid.pause(); else if (fr && prov === 'vimeo') send({method: 'pause'}); else if (fr) send({event: 'command', func: 'pauseVideo', args: []}); };
  c.seek = s => { if (vid) vid.currentTime = s; else if (fr && prov === 'vimeo') send({method: 'setCurrentTime', value: s}); else if (fr) send({event: 'command', func: 'seekTo', args: [s, true]}); };
  if (vid) {
    vid.addEventListener('timeupdate', () => { c.cur = vid.currentTime; on('t'); });
    vid.addEventListener('loadedmetadata', () => dur(vid.duration));
  } else if (fr && origin) {
    const hello = () => prov === 'vimeo' ? (send({method: 'addEventListener', value: 'timeupdate'}), send({method: 'getDuration'}))
      : send({event: 'listening', id: 'vdr', channel: 'widget'});
    const msg = e => {
      if (e.origin !== origin || e.source !== fr.contentWindow) return;
      let d; try { d = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; } catch { return; }
      if (!d || typeof d !== 'object') return;
      if (prov === 'vimeo') {
        if (d.event === 'ready') hello();
        if (d.event === 'timeupdate' && d.data) { c.cur = +d.data.seconds || 0; dur(d.data.duration); on('t'); }
        if (d.method === 'getDuration') dur(d.value);
      } else if ((d.event === 'infoDelivery' || d.event === 'initialDelivery') && d.info) {
        if (typeof d.info.currentTime === 'number') { c.cur = d.info.currentTime; on('t'); }
        dur(d.info.duration);
      }
    };
    window.addEventListener('message', msg);
    fr.addEventListener('load', () => { hello(); setTimeout(hello, 1000); });
    c.stop = () => window.removeEventListener('message', msg);
  }
  return c;
}

// ---- the review view (a dialog): player, time line, comments of the version, composer, menu
async function vdr_open(id, have) {
  let r = have;
  if (!r || !r.comments) { try { r = await api('GET', `/api/videos/${id}`); } catch { return; } }
  $('.vdrdlg')?.remove();
  const md = modal(`<div class="lhdr vdrhd"><h3 id="vdr-h"></h3><span class="spacer"></span><span class="vdrvsel"></span>
      <button class="iconbtn" data-vdr="menu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button>
      <button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="vdrbody"><div class="vdrstate"></div><div class="vdrpl"></div><div class="vdrtl" aria-label="${esc(tr('Comments on the time line'))}"></div>
      <div class="vdrcmp"></div><ul class="vdrcms" role="list"></ul><div class="vdrsig"></div></div>`);
  md.classList.add('vdrdlg');
  md.setAttribute('aria-labelledby', 'vdr-h');
  const st = VDR.cur = {md, r, ver: (r.versions[r.versions.length - 1] || {}).id, at: true, frozen: null, reply: null, ctl: null};
  onRemove(md, () => { st.ctl?.stop(); if (VDR.cur === st) VDR.cur = null; });
  vdr_draw(st, true);
  md.addEventListener('click', e => vdr_click(e, st));
  md.addEventListener('change', e => { if (e.target.id === 'vdr-ver') { st.ver = +e.target.value; st.reply = null; vdr_draw(st, true); } });
  md.addEventListener('focusin', e => {  // typing pauses the player and keeps its time for the comment
    if (e.target.id !== 'vdr-in' || st.frozen != null) return;
    st.ctl?.pause(); st.frozen = st.ctl ? st.ctl.cur : 0; vdr_atDraw(st);
  });
  md.addEventListener('keydown', e => { if (e.target.id === 'vdr-in' && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); vdr_send(st); } });
}
const vdr_closeIf = id => { if (VDR.cur?.r.id === id) VDR.cur.md.remove(); };
const vdr_v = st => st.r.versions.find(v => v.id === st.ver) || st.r.versions[st.r.versions.length - 1];
function vdr_draw(st, player) {
  const {md, r} = st, v = vdr_v(st), ro = !r.can_write;
  $('#vdr-h', md).textContent = r.title;
  $('.vdrvsel', md).innerHTML = r.versions.length > 1 ? `<label class="sr" for="vdr-ver">${tr('Version')}</label><select id="vdr-ver">${r.versions.slice().reverse().map(x => `<option value="${x.id}" ${x.id === v.id ? 'selected' : ''}>v${x.n}</option>`).join('')}</select>` : `<span class="vdrv1">v${v ? v.n : 1}</span>`;
  $('.vdrstate', md).innerHTML = `<span class="vdrchip st-${esc(r.state)}">${esc(tr(VDR_ST[r.state] || r.state))}</span>`
    + (v && v.id !== r.versions[r.versions.length - 1].id ? `<span class="muted">${esc(tr('An older version: its comments stay here'))}</span>` : '')
    + (ro ? '' : `<span class="spacer"></span>${r.state === 'open' ? `<button type="button" class="btn sm" data-vdr="state" data-st="approved">${ic('check', 's')} ${tr('Mark as approved')}</button>`
      : `<button type="button" class="btn sm" data-vdr="state" data-st="open">${ic('undo', 's')} ${tr('Back to review')}</button>`}`);
  if (player) {
    st.ctl?.stop();
    $('.vdrpl', md).innerHTML = vdr_playerHtml(v, r.title);
    st.ctl = v && v.timed ? vdr_ctl($('.vdrplay', md), v.provider, w => { if (w === 'dur') vdr_tlDraw(st); else if (st.frozen == null) vdr_atDraw(st); }) : null;
    st.frozen = null;
  }
  vdr_tlDraw(st); vdr_cmpDraw(st); vdr_cmsDraw(st); vdr_sigDraw(st);
}
const vdr_top = st => st.r.comments.filter(c => c.version_id === st.ver && !c.parent_id);
function vdr_tlDraw(st) {
  const el = $('.vdrtl', st.md), d = st.ctl?.dur || 0, ms = vdr_top(st).filter(c => c.at_sec != null);
  el.hidden = !d || !ms.length;
  if (el.hidden) { el.innerHTML = ''; return; }
  el.innerHTML = ms.map(c => `<button type="button" class="vdrmk ${c.done ? 'done' : ''}" data-vdr="seek" data-at="${c.at_sec}" style="left:${Math.min(100, c.at_sec / d * 100).toFixed(2)}%" aria-label="${esc(vdr_tc(c.at_sec) + ' ' + c.author + ': ' + c.body.slice(0, 60))}" title="${esc(vdr_tc(c.at_sec) + ' · ' + c.body.slice(0, 80))}"></button>`).join('');
}
function vdr_atDraw(st) {
  const b = $('[data-vdr="at"]', st.md); if (!b) return;
  const t = st.frozen != null ? st.frozen : st.ctl ? st.ctl.cur : 0;
  b.setAttribute('aria-pressed', String(st.at));
  b.classList.toggle('on', st.at);
  $('span', b).textContent = st.at ? tr('at {0}|timecode', vdr_tc(t)) : tr('without time');
}
function vdr_cmpDraw(st) {
  const v = vdr_v(st), timed = v && v.timed && !st.reply;
  const rep = st.reply && st.r.comments.find(c => c.id === st.reply);
  $('.vdrcmp', st.md).innerHTML = `${rep ? `<div class="vdrrep muted">${ic('reply', 's')}<span>${esc(tr('Answer to {0}', rep.author))}</span><button type="button" class="linkbtn" data-vdr="noreply">${tr('Cancel')}</button></div>` : ''}
    <div class="vdrin">${timed ? `<button type="button" class="vdrat on" data-vdr="at" aria-pressed="true" title="${esc(tr('Tap to comment without a time'))}">${ic('clock', 's')}<span></span></button>` : ''}
    <textarea id="vdr-in" rows="2" maxlength="2000" placeholder="${esc(rep ? tr('Your answer') : timed ? tr('Comment at this moment') : tr('Comment'))}" aria-label="${esc(tr('Comment'))}"></textarea>
    <button type="button" class="btn pri sm" data-vdr="send" aria-label="${esc(tr('Send'))}">${ic('send', 's')}</button></div>`;
  vdr_atDraw(st);
}
function vdr_cmsDraw(st) {
  const r = st.r, kids = {}, uid = S.me?.id;
  for (const c of r.comments) if (c.parent_id) (kids[c.parent_id] = kids[c.parent_id] || []).push(c);
  const one = (c, reply) => {
    const mine = c.author_id && c.author_id === uid, can = r.can_write || mine;
    return `<li class="vdrc ${c.done ? 'done' : ''} ${c.customer ? 'cust' : ''}" data-cid="${c.id}">
      <div class="vdrch">${!reply && c.at_sec != null ? `<button type="button" class="vdrtc" data-vdr="seek" data-at="${c.at_sec}" aria-label="${esc(tr('Jump to {0}', vdr_tc(c.at_sec)))}">${esc(vdr_tc(c.at_sec))}</button>` : ''}
        <b>${esc(c.author || tr('Unknown'))}</b>${c.customer ? `<span class="rotag">${tr('Customer')}</span>` : ''}<small class="muted">${esc(fmtWhen(c.created_at))}</small><span class="spacer"></span>
        ${!reply ? `<button type="button" class="iconbtn" data-vdr="reply" data-id="${c.id}" aria-label="${esc(tr('Reply'))}" title="${esc(tr('Reply'))}">${ic('reply', 's')}</button>` : ''}
        ${!reply && can ? `<button type="button" class="iconbtn vdrdone ${c.done ? 'on' : ''}" data-vdr="done" data-id="${c.id}" aria-pressed="${c.done}" aria-label="${esc(c.done ? tr('Mark as open') : tr('Mark as done'))}" title="${esc(c.done ? tr('Mark as open') : tr('Mark as done'))}">${ic('check', 's')}</button>` : ''}
        ${can ? `<button type="button" class="iconbtn" data-vdr="del" data-id="${c.id}" aria-label="${esc(tr('Delete'))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button>` : ''}</div>
      <div class="vdrcb">${esc(c.body)}</div>${(kids[c.id] || []).length ? `<ul class="vdrre" role="list">${kids[c.id].map(k => one(k, true)).join('')}</ul>` : ''}</li>`;
  };
  const top = vdr_top(st);
  $('.vdrcms', st.md).innerHTML = top.length ? top.map(c => one(c)).join('') : `<li class="muted vdrempty">${tr('No comments yet.')}</li>`;
}
function vdr_sigDraw(st) {
  const r = st.r, el = $('.vdrsig', st.md);
  if (!r.can_write) { el.innerHTML = ''; return; }
  const sw = {open: tr('Waiting for the customer'), accepted: tr('Approved|video'), declined: tr('Changes requested')};
  const rows = (r.signoffs || []).slice(0, 5).map(x => {
    const s = x.revoked_at && x.state === 'open' ? tr('Turned off') : !x.live && x.state === 'open' ? tr('Expired') : sw[x.state] || x.state;
    return `<li class="sgrow st-${esc(x.state)}"><div class="sghead"><b>${esc(s)}</b><small class="muted"> · ${esc(fmtWhen(x.created_at))}</small>${x.signer_name ? ` <span class="muted">${esc(x.signer_name)}</span>` : ''}</div>
      ${x.live && x.url ? `<div class="row icalrow"><input readonly value="${esc(x.url)}" aria-label="${esc(tr('Customer link'))}" data-vdrurl="${x.id}"><button type="button" class="btn sm pri" data-vdr="sigcopy" data-id="${x.id}">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm danger" data-vdr="sigstop" data-id="${x.id}">${tr('Turn off')}</button></div>` : ''}
      ${x.reason ? `<div class="muted">${esc(tr('Reason: {0}', x.reason))}</div>` : ''}</li>`;
  }).join('');
  el.innerHTML = `<h4>${tr('Customer link')}</h4><p class="muted mhint">${esc(tr('Your customer watches the newest version without an account, comments at a time and approves or requests changes.'))}</p>
    ${rows ? `<ul class="sglist" role="list">${rows}</ul>` : ''}<button type="button" class="btn sm" data-vdr="signew">${ic('link', 's')} ${(r.signoffs || []).some(x => x.live) ? tr('New customer link') : tr('Create customer link')}</button>`;
}

// ---- actions
async function vdr_req(st, method, url, body) {
  const r = await rawFetch(method, url, body);
  if (r && r.versions) { st.r = r; vdr_cache(r); }
  return r;
}
async function vdr_send(st) {
  const ta = $('#vdr-in', st.md), text = (ta?.value || '').trim();
  if (!text) { ta?.focus(); return; }
  const v = vdr_v(st), at = v.timed && st.at && !st.reply ? Math.round((st.frozen != null ? st.frozen : st.ctl ? st.ctl.cur : 0) * 10) / 10 : null;
  const body = st.reply ? {parent_id: st.reply, body: text} : {version_id: v.id, at_sec: at, body: text};
  let j; try { j = await vdr_req(st, 'POST', `/api/videos/${st.r.id}/comments`, body); } catch (e) { toast(e.message); return; }
  st.reply = null; st.frozen = null;
  vdr_draw(st, false);
  const cid = j.comment_id, rid = st.r.id;
  const h = histAdd({label: tr('Comment added'), ids: [], snaps: [], lids: [],
    undo: async () => { await vdr_after(rid, 'DELETE', `/api/videos/${rid}/comments/${cid}`); return {skipped: []}; },
    redo: async () => { await vdr_after(rid, 'POST', `/api/videos/${rid}/comments/${cid}/restore`); return {skipped: []}; }});
  histToast(tr('Comment added'), h);
}
async function vdr_after(rid, method, url, body) {  // an undo / redo step: the open view follows when it shows this review
  const r = await rawFetch(method, url, body);
  if (r && r.versions) { vdr_cache(r); const st = VDR.cur; if (st && st.r.id === rid) { st.r = r; if (!r.versions.some(v => v.id === st.ver)) st.ver = r.versions[r.versions.length - 1].id; vdr_draw(st, !r.versions.some(v => v.id === st.ver)); } }
  return r;
}
async function vdr_click(e, st) {
  const b = e.target.closest('[data-vdr],[data-m="close"]'); if (!b) return;
  if (b.dataset.m === 'close') { st.md.remove(); return; }
  const a = b.dataset.vdr, r = st.r, rid = r.id, id = +b.dataset.id || 0;
  if (a === 'seek') { st.ctl?.seek(+b.dataset.at || 0); st.frozen = null; return; }
  if (a === 'at') { st.at = !st.at; vdr_atDraw(st); return; }
  if (a === 'send') { vdr_send(st); return; }
  if (a === 'reply') { st.reply = id; vdr_cmpDraw(st); $('#vdr-in', st.md)?.focus(); return; }
  if (a === 'noreply') { st.reply = null; vdr_cmpDraw(st); return; }
  if (a === 'menu') { vdr_menu(b, st); return; }
  try {
    if (a === 'done') {
      const was = !!r.comments.find(c => c.id === id)?.done, set = v => vdr_after(rid, 'PATCH', `/api/videos/${rid}/comments/${id}`, {done: v});
      await set(!was);
      histToast(was ? tr('Marked as open') : tr('Marked as done'), histAdd({label: was ? tr('Marked as open') : tr('Marked as done'), ids: [], snaps: [], lids: [],
        undo: async () => { await set(was); return {skipped: []}; }, redo: async () => { await set(!was); return {skipped: []}; }}));
    }
    if (a === 'del') {
      await vdr_after(rid, 'DELETE', `/api/videos/${rid}/comments/${id}`);
      histToast(tr('Comment deleted'), histAdd({label: tr('Comment deleted'), ids: [], snaps: [], lids: [],
        undo: async () => { await vdr_after(rid, 'POST', `/api/videos/${rid}/comments/${id}/restore`); return {skipped: []}; },
        redo: async () => { await vdr_after(rid, 'DELETE', `/api/videos/${rid}/comments/${id}`); return {skipped: []}; }}));
    }
    if (a === 'state') {
      const was = r.state, set = v => vdr_after(rid, 'PATCH', `/api/videos/${rid}`, {state: v});
      await set(b.dataset.st);
      histToast(tr(VDR_ST[b.dataset.st]), histAdd({label: tr(VDR_ST[b.dataset.st]), ids: [], snaps: [], lids: [],
        undo: async () => { await set(was); return {skipped: []}; }, redo: async () => { await set(b.dataset.st); return {skipped: []}; }}));
    }
    if (a === 'signew') { await rawFetch('POST', `/api/videos/${rid}/signoff`, {expires: null}); await vdr_after(rid, 'GET', `/api/videos/${rid}`); toast(tr('Customer link created')); }
    if (a === 'sigstop') {
      if (!await askConfirm(tr('Stop the customer link?'), tr('It stops working at once.'), {ok: tr('Turn off'), danger: true})) return;
      await rawFetch('POST', `/api/videos/${rid}/signoffs/${id}/revoke`); await vdr_after(rid, 'GET', `/api/videos/${rid}`); toast(tr('Customer link stopped'));
    }
    if (a === 'sigcopy') { const i = $(`[data-vdrurl="${id}"]`, st.md); try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); } }
  } catch (x) { toast(x.message); }
  if (VDR.cur === st) vdr_draw(st, false);
}
function vdr_menu(anchor, st) {
  const r = st.r, rid = r.id, w = r.can_write;
  menu(anchor, [
    w && {label: tr('New version…'), icon: 'upload', fn: () => vdr_newVersion(st)},
    w && {label: tr('Rename…'), icon: 'edit', fn: () => vdr_rename(st)},
    '-',
    {label: tr('Copy comments as text'), icon: 'copy', fn: () => vdr_copyText(st)},
    {label: tr('Download comments (CSV)'), icon: 'download', fn: () => { location.href = `/api/videos/${rid}/export?version_id=${st.ver}`; }},
    {label: tr('Open the original link'), icon: 'link', fn: () => window.open(vdr_v(st).url, '_blank', 'noopener,noreferrer')},
    '-',
    w && typeof smv_can === 'function' && smv_can(r.org_id) && {label: tr('Move to another workspace…'), icon: 'arrow', fn: () => vdr_move(st)},
    w && {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: () => vdr_delete(st)}], null, null, r.title);
}
async function vdr_newVersion(st) {
  const url = await askPrompt(tr('New version'), '', {input: {max: 2000, placeholder: 'https://', type: 'url'}, ok: tr('Add'), body: tr('Paste the link of the new cut. The comments of the older versions stay with them.')});
  if (url == null || !url.trim()) return;
  const rid = st.r.id;
  let j; try { j = await vdr_req(st, 'POST', `/api/videos/${rid}/versions`, {url: url.trim()}); } catch (e) { toast(e.message); return; }
  let nid = j.new_version;
  st.ver = nid; vdr_draw(st, true);
  histToast(tr('Version {0} added', 'v' + j.version), histAdd({label: tr('Version {0} added', 'v' + j.version), ids: [], snaps: [], lids: [],
    undo: async () => { await vdr_after(rid, 'DELETE', `/api/videos/${rid}/versions/${nid}`); return {skipped: []}; },
    redo: async () => { const x = await vdr_after(rid, 'POST', `/api/videos/${rid}/versions`, {url: url.trim()}); nid = x.new_version; return {skipped: []}; }}));
}
async function vdr_rename(st) {
  const cur = st.r.title, t = await askPrompt(tr('Rename'), cur, {input: {max: 200}, ok: tr('Rename')});
  if (t == null || !t.trim() || t.trim() === cur) return;
  const rid = st.r.id, set = v => vdr_after(rid, 'PATCH', `/api/videos/${rid}`, {title: v});
  try { await set(t.trim()); } catch (e) { toast(e.message); return; }
  histToast(tr('Renamed'), histAdd({label: tr('Renamed {0}', qn(t.trim())), ids: [], snaps: [], lids: [],
    undo: async () => { await set(cur); return {skipped: []}; }, redo: async () => { await set(t.trim()); return {skipped: []}; }}));
}
async function vdr_copyText(st) {
  let j; try { j = await api('GET', `/api/videos/${st.r.id}/export?format=text&version_id=${st.ver}`); } catch { return; }
  try { await navigator.clipboard.writeText(j.text); toast(tr('Comments copied')); } catch { toast(tr('Could not copy')); }
}
async function vdr_delete(st) {
  const r = st.r;
  try { await rawFetch('DELETE', `/api/videos/${r.id}`); } catch (e) { toast(e.message); return; }
  st.md.remove(); vdr_cache(r, true);
  histToast(tr('Video sign-off {0} deleted', qn(r.title)), histAdd({label: tr('Deleted {0}', qn(r.title)), ids: [], snaps: [], lids: [],
    undo: async () => { vdr_cache(await rawFetch('POST', `/api/videos/${r.id}/restore`)); return {skipped: []}; },
    redo: async () => { await rawFetch('DELETE', `/api/videos/${r.id}`); vdr_cache(r, true); vdr_closeIf(r.id); return {skipped: []}; }}));
}
// to the other workspace: into a project there (the review always keeps a place in the app); the undo = the same move back
async function vdr_move(st) {
  const r0 = st.r, rid = r0.id, from = r0.org_id || null;
  const req = (to, extra) => rawFetch('POST', `/api/videos/${rid}/move-space`, {to: smv_ws(to), ...extra});
  const places = async to => (S.lists || []).filter(l => !l.is_inbox && !l.archived && !l.e2e && (l.org_id || null) === (to || null) && canEditList(l.id))
    .map(l => ({id: l.id, label: lname(l)}));
  const res = await smv_open({what: qn(r0.title), from, places, check: (to, place) => req(to, {dry: 1, place: place || null}),
    run: async (to, place) => { try { return await req(to, {place: place || null}); } catch (e) { toast(e.message); throw e; } }});
  if (!res || !res.ok) return;
  let mid = res.move_id;
  st.md.remove(); vdr_forget(); vdr_cache(res.review);
  histToast(tr('Moved to {0}', wsName(res.space)), histAdd({label: tr('Moved {0}', qn(r0.title)), ids: [], snaps: [], lids: [], wsp: res.space,
    undo: async () => { const b = await req(from, {undo: mid}); mid = b.move_id; vdr_forget(); vdr_cache(b.review); return {skipped: []}; },
    redo: async () => { const b = await req(res.space === 'private' ? null : +res.space.slice(4), {undo: mid}); mid = b.move_id; vdr_forget(); vdr_cache(b.review); return {skipped: []}; }}));
}
document.addEventListener('click', e => {  // the sections (task, project, client)
  const b = e.target.closest('[data-vdr="open"],[data-vdr="new"]'); if (!b || b.closest('.vdrdlg')) return;
  e.preventDefault();
  if (b.dataset.vdr === 'open') vdr_open(+b.dataset.id); else vdr_new(b.dataset.k, +b.dataset.i);
});
