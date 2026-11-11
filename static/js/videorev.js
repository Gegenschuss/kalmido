/* Kalmido web client: video sign-offs (2.99.1 A, #1959), module "videos" (loaded on demand: lazyload.js).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// A video sign-off holds links only (Vimeo, YouTube, a direct video file over https; 2.633.0 #4777: also a direct audio file
// over https in an <audio> element; Kalmido stores no video / audio), each new link
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
  const li = rows.map(r => `<li><button type="button" class="vdrrow" data-vdr="open" data-id="${r.id}">${ic(r.kind === 'image' ? 'picture' : r.kind === 'pdf' ? 'pdf' : vdr_isAud(r.versions?.[r.versions.length - 1]) ? 'music' : 'film', 's')}<span class="vdrrt"><b>${esc(r.title)}</b>
    <small class="muted">${esc([`v${r.version}`, tr(VDR_ST[r.state] || r.state), r.open_comments ? trn('{0} open comment', '{0} open comments', r.open_comments) : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="vdrst st-${esc(r.state)}" aria-hidden="true"></span></button></li>`).join('');
  return (li ? `<ul class="vdrrows" role="list">${li}</ul>` : '')
    + (add ? `<button type="button" class="btn sm vdradd" data-vdr="new" data-k="${k}" data-i="${id}">${ic('plus', 's')} ${tr('Add video or audio link')}</button>`
      + ` <button type="button" class="btn sm vdradd" data-vdr="newfile" data-k="${k}" data-i="${id}">${ic('plus', 's')} ${tr('Add image, PDF or audio')}</button>` : '');  // 2.641.0 (#4769); 2.658.0 (#5015): + audio
}
// 2.96.3 (#1959): the section arrives after the detail - redraw it without taking the focus (comment box of #reply/<id>)
function vdr_redrawTask(tid) {
  if (S.sel !== tid || typeof renderDetail !== 'function') return;
  const a = document.activeElement, id = a?.id, ss = a?.selectionStart, se = a?.selectionEnd;
  const v = a && /^(INPUT|TEXTAREA)$/.test(a.tagName) ? a.value : null;
  renderDetail();
  const n = id && document.getElementById(id);
  if (n && n !== a && v != null && n.value !== v) n.value = v;  // 2.359.2 B (#3049): a field rebuilt meanwhile keeps what was typed (the tag field)
  if (n && n !== document.activeElement) { n.focus({preventScroll: true}); try { if (ss != null) n.setSelectionRange(ss, se); } catch (e) { /* not a text field */ } }
}
function vdr_redrawView() { if (S.route.mod === 'clients' && typeof ms_clDraw === 'function') ms_clDraw(); else renderView(); }
function vdr_taskHtml(t, ro) {
  if (!t || !(t.id > 0) || t.context) return '';
  const rows = vdr_rows('task_id', t.id, () => vdr_redrawTask(t.id));
  if (!rows) return '';
  if (ro && !rows.length) return '';
  return `<div class="dsec vdrsec" id="d-vdr"><h5>${tr('Approval')}</h5>${vdr_listHtml(rows, 'task_id', t.id, !ro)}</div>`;  // 2.623.0 (#4765): ro also = off (detail.js)
}
const vdr_count = t => (VDR.by[vdr_key('task_id', t.id)] || []).length;  // detail.js: a task with reviews shows the section outside "More details"
// 2.623.0 (#4765): "Add" only where the approval belongs: the module on and the project's property (props.js pz_on: agency and
// projects without a type, not software / private unless switched on in the project); the existing ones show everywhere
function vdr_projHtml(l) {
  if (!l || l.e2e) return '';
  const rows = vdr_rows('list_id', l.id, vdr_redrawView);
  if (!rows) return '';
  const add = typeof canEditList === 'function' && canEditList(l.id) && pz_on(l, 'video');
  if (!rows.length && !add) return '';
  return `<section class="povs vdrpov" id="pov-videos"><div class="povh"><h3>${tr('Approvals|sign-off')}</h3></div>${vdr_listHtml(rows, 'list_id', l.id, add)}</section>`;
}
function vdr_clientHtml(c) {
  if (!c || !c.id) return '';
  const rows = vdr_rows('client_id', c.id, vdr_redrawView);
  if (!rows) return '';
  const add = feat('videos');  // 2.623.0 (#4765): a client has no project type: the module alone; off = only the existing ones
  if (!rows.length && !add) return '';
  return `<div class="ctsec vdrcl"><h4>${tr('Approvals|sign-off')}</h4>${vdr_listHtml(rows, 'client_id', c.id, add)}</div>`;
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
  const md = modal(`<form class="vdrform" novalidate><h3 id="vdr-nt">${tr('Add video or audio link')}</h3><div class="shint">${esc(tr('Kalmido stores no videos or audio. YouTube links may be unlisted; video files as MP4, WebM or MOV; audio files as MP3, M4A, AAC, WAV, OGG, Opus or FLAC.'))}</div>
    <p class="muted mhint">${esc(tr('Link from Vimeo, YouTube or a video or audio file (https)'))}</p>
    <label for="vdr-url">${tr('Link')}</label><input id="vdr-url" type="url" inputmode="url" autocomplete="off" placeholder="https://" maxlength="2000" required>
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
    histToast(tr('Approval {0} created', qn(r.title)), h);
    vdr_open(r.id, r);
  });
}

// ---- the player (iframe of the built URL or <video>), driven by postMessage
// 2.240.0 D (#2886): two clicks -- a plain placeholder first (no request to the provider, no thumbnail), the player only after "Load video";
// setting video_ext_ok = "1" (own switch in Settings) loads it straight away. A direct file from another host gets the same question.
const VDR_PROV = {youtube: 'YouTube', vimeo: 'Vimeo'};
const vdr_extHost = v => { try { const h = new URL(v.url).hostname; return h && h !== location.hostname ? h : ''; } catch { return ''; } };
// 2.633.0 (#4777): audio = a direct audio file over https, played by the browser's own <audio> element (no waveform, no foreign script)
const vdr_isAud = v => !!v && v.provider === 'audio';
const vdr_isFile = v => !!v && (v.provider === 'file' || v.provider === 'audio');
function vdr_gateName(v) { return vdr_isFile(v) ? vdr_extHost(v) : VDR_PROV[v.provider] || ''; }
function vdr_playerInner(v, title) {
  if (v.provider === 'youtube' || v.provider === 'vimeo') {
    const src = v.embed + (v.provider === 'youtube' ? '&origin=' + encodeURIComponent(location.origin) : '');
    return `<iframe src="${esc(src)}" title="${esc(title)}" allow="fullscreen; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>`;
  }
  if (vdr_isAud(v)) return `<audio src="${esc(v.embed)}" controls preload="metadata" aria-label="${esc(title)}"></audio>`;
  return `<video src="${esc(v.embed)}" controls playsinline preload="none"></video>`;
}
function vdr_playerHtml(v, title) {
  if (!v) return '';
  if (vdr_stored(v) && !v.embed) return `<div class="vdrnolink">${ic('info', 's')}<p>${esc(tr('The file of this version is no longer in the file store.'))}</p></div>`;  // 2.658.0 (#5015)
  const ext = v.provider === 'youtube' || v.provider === 'vimeo' || vdr_isFile(v);
  // 2.240.0 D2 (#2886): video_ext_ok only covers YouTube/Vimeo; a direct file from another host always asks
  if (ext && (vdr_isFile(v) || S.settings?.video_ext_ok !== '1') && vdr_gateName(v)) {
    const n = vdr_gateName(v), aud = vdr_isAud(v);
    return `<div class="vdrplay vdrgate" data-prov="${v.provider}"><div class="vdrgate-in">${ic('play', 'l')}
      <p>${esc(aud ? tr('Loading the audio sends data (such as your IP address) to {0}.', n) : tr('Loading the video sends data (such as your IP address) to {0}.', n))}</p>
      <button type="button" class="btn pri sm" data-vdr="gate">${aud ? tr('Load audio') : tr('Load video')}</button>
      ${vdr_isFile(v) ? '' : `<label class="chkl"><input type="checkbox" class="vdrgate-ok"> ${tr('Do not ask again')}</label>`}</div></div>`;
  }
  if (ext) return `<div class="vdrplay" data-prov="${v.provider}">${vdr_playerInner(v, title)}</div>`;
  return `<div class="vdrnolink">${ic('info', 's')}<p>${esc(tr('This link has no time control: it opens in a new tab, comments get no timecode.'))}</p>
    <a class="btn sm" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${ic('link', 's')} ${tr('Open the video')}</a></div>`;
}
function vdr_ctl(box, prov, on) {
  const fr = box && $('iframe', box), vid = box && $('video, audio', box), origin = VDR_ORIGIN[prov] || '';
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
  md.dataset.dlgsz = 'review';  // 2.805.0 (#5357): the size grip (dialogs.js dlg_sizer)
  md.setAttribute('aria-labelledby', 'vdr-h');
  // 2.641.0 (#4769): pt = the point set on the image / page for the next comment, page = the PDF page shown, pdf = its document
  const st = VDR.cur = {md, r, ver: (r.versions[r.versions.length - 1] || {}).id, at: true, frozen: null, reply: null, ctl: null, pt: null, page: 1, pdf: null};
  onRemove(md, () => { st.ctl?.stop(); try { st.pdf?.doc.destroy(); } catch { /* gone */ } if (VDR.cur === st) VDR.cur = null; });
  vdr_draw(st, true);
  md.addEventListener('click', e => vdr_click(e, st));
  md.addEventListener('change', e => { if (e.target.id === 'vdr-ver') { st.ver = +e.target.value; st.reply = null; st.pt = null; st.page = 1; vdr_draw(st, true); } });
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
  if (player && v && v.kind && v.kind !== 'video') {  // 2.641.0 (#4769): an image / PDF with its points instead of the player
    st.ctl?.stop(); st.ctl = null; st.frozen = null;
    $('.vdrpl', md).innerHTML = vdr_mediaHtml(v);
    vdr_mediaLoad(st);
  } else if (player) {
    st.ctl?.stop();
    $('.vdrpl', md).innerHTML = vdr_playerHtml(v, r.title);
    st.ctl = v && v.timed ? vdr_ctl($('.vdrplay', md), v.provider, w => { if (w === 'dur') vdr_tlDraw(st); else if (st.frozen == null) vdr_atDraw(st); }) : null;
    st.frozen = null;
  }
  vdr_tlDraw(st); vdr_cmpDraw(st); vdr_cmsDraw(st); vdr_sigDraw(st); vdr_pinsDraw(st);
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
    ${vdr_media(v) && !st.reply ? `<button type="button" class="vdrat vdrptb ${st.pt ? 'on' : ''}" data-vdr="pt" aria-pressed="${!!st.pt}" title="${esc(st.pt ? tr('Tap to comment without a point') : tr('Tap on the image to set a point'))}">${ic('mappin', 's')}<span>${esc(st.pt ? tr('at point {0}', vdr_nextMark(st)) : tr('without point'))}</span></button>` : '' /* 2.641.0 (#4769) */}
    <textarea id="vdr-in" rows="2" maxlength="2000" placeholder="${esc(rep ? tr('Your answer') : timed ? tr('Comment at this moment') : vdr_media(v) ? tr('Tap on the image, then write') : tr('Comment'))}" aria-label="${esc(tr('Comment'))}"></textarea>
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
        ${!reply && c.at_sec == null && (c.mark || c.page) ? `<button type="button" class="vdrtc vdrpb" data-vdr="pin" data-id="${c.id}" aria-label="${esc(c.mark ? tr('Show point {0}', c.mark) : tr('Page {0}', c.page))}">${esc([c.page ? tr('p. {0}|page', c.page) : '', c.mark ? String(c.mark) : ''].filter(Boolean).join(' · '))}</button>` : '' /* 2.641.0 (#4769) */}
        <b>${esc(c.author || tr('Unknown'))}${c.customer ? ` (${esc(tr('Guest'))})` : ''}</b><small class="muted">${esc(fmtWhen(c.created_at))}</small><span class="spacer"></span>
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
  if (!r.can_write) { el.innerHTML = ''; return; }  // 2.764.0 (#5040): images / PDFs too (2.641.0 #4769: videos only)
  const sw = {open: tr('Waiting for the client'), accepted: tr('Approved|video'), declined: tr('Changes requested')};
  // 2.642.0 (#4772): several links: every running one, then the last five records (decisions, switched off, expired)
  const all = r.signoffs || [], live = all.filter(x => x.live), rest = all.filter(x => !x.live).slice(0, 5);
  const rows = [...live, ...rest].map(x => {
    const s = x.revoked_at && x.state !== 'open' ? `${sw[x.state] || x.state} · ${tr('Switched off')}` : x.revoked_at && x.state === 'open' ? tr('Switched off') : !x.live && x.state === 'open' ? tr('Expired') : sw[x.state] || x.state;
    const ex = x.live && x.expires_at ? ` · ${esc(tr('until {0}', fmtDateNum(new Date(Date.parse(x.expires_at) - 1000))))}` : '', old = x.show_old ? ` · ${esc(tr('older versions too'))}` : '';
    return `<li class="sgrow st-${esc(x.state)}"><div class="sghead"><b>${esc(s)}</b><small class="muted"> · ${esc(fmtWhen(x.created_at))}${ex}${old}</small>${x.signer_name ? ` <span class="muted">${esc(x.signer_name)}</span>` : ''}</div>
      ${x.live && x.url ? `<div class="row icalrow"><input readonly value="${esc(x.url)}" aria-label="${esc(tr('Client link'))}" data-vdrurl="${x.id}"><button type="button" class="btn sm pri" data-vdr="sigcopy" data-id="${x.id}">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm danger" data-vdr="sigstop" data-id="${x.id}">${tr('Switch off')}</button></div>` : ''}
      ${!x.live && !x.revoked_at && x.state !== 'open' ? `<div class="row"><button type="button" class="btn sm danger" data-vdr="sigstop" data-id="${x.id}">${tr('Switch off')}</button></div>` : ''}
      ${x.reason ? `<div class="muted">${esc(tr('Reason: {0}', x.reason))}</div>` : ''}</li>`;
  }).join('');
  el.innerHTML = `<h4>${tr('Client link')}</h4><p class="muted mhint">${esc(vdr_media(r.versions[r.versions.length - 1]) ? tr('Your client looks at the newest version without an account, comments at a point and approves or requests changes.') : tr('Your client watches the newest version without an account, comments at a time and approves or requests changes.'))}</p>
    ${rows ? `<ul class="sglist" role="list">${rows}</ul>` : ''}
    <div class="vdrsignew"><span class="vdrsigexp">${tr('Valid until (optional)')} ${dateIn('vdrsigdate', '', {min: today(), label: tr('Valid until (optional)'), attrs: 'class="vdrsigdate"'})}</span>
    ${r.versions.length > 1 ? `<label class="chk"><input type="checkbox" class="vdrsigold"> ${tr('The client may also see the older versions')}</label>` : ''}
    <button type="button" class="btn sm" data-vdr="signew">${ic('link', 's')} ${live.length ? tr('New client link') : tr('Create client link')}</button></div>`;
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
  const pos = vdr_media(v) && st.pt ? (v.kind === 'pdf' ? {page: st.pt.page, x: st.pt.x, y: st.pt.y} : {x: st.pt.x, y: st.pt.y}) : null;  // 2.641.0 (#4769)
  const body = st.reply ? {parent_id: st.reply, body: text} : pos ? {version_id: v.id, pos, body: text} : {version_id: v.id, at_sec: at, body: text};
  let j; try { j = await vdr_req(st, 'POST', `/api/videos/${st.r.id}/comments`, body); } catch (e) { toast(e.message); return; }
  st.reply = null; st.frozen = null; st.pt = null;
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
// 2.240.0 D (#2886): the click on "Load video": build the player now; "Do not ask again" saves video_ext_ok
function vdr_gateLoad(st, b) {
  const v = vdr_v(st), box = b.closest('.vdrgate'); if (!v || !box) return;
  if ($('.vdrgate-ok', box)?.checked) { S.settings.video_ext_ok = '1'; api('PATCH', '/api/settings', {video_ext_ok: '1'}).catch(() => {}); }
  box.classList.remove('vdrgate'); box.innerHTML = vdr_playerInner(v, st.r.title);
  st.ctl?.stop();
  st.ctl = v.timed ? vdr_ctl(box, v.provider, w => { if (w === 'dur') vdr_tlDraw(st); else if (st.frozen == null) vdr_atDraw(st); }) : null;
}
async function vdr_click(e, st) {
  const b = e.target.closest('[data-vdr],[data-m="close"]'); if (!b) { vdr_stageTap(e, st); return; }  // 2.641.0 (#4769)
  if (b.dataset.m === 'close') { st.md.remove(); return; }
  const a = b.dataset.vdr, r = st.r, rid = r.id, id = +b.dataset.id || 0;
  if (a === 'gate') { vdr_gateLoad(st, b); return; }
  if (a === 'seek') { st.ctl?.seek(+b.dataset.at || 0); st.frozen = null; return; }
  if (a === 'at') { st.at = !st.at; vdr_atDraw(st); return; }
  if (a === 'send') { vdr_send(st); return; }
  if (a === 'reply') { st.reply = id; vdr_cmpDraw(st); $('#vdr-in', st.md)?.focus(); return; }
  if (a === 'noreply') { st.reply = null; vdr_cmpDraw(st); return; }
  if (a === 'menu') { vdr_menu(b, st); return; }
  if (a === 'pt') { if (st.pt) { st.pt = null; vdr_ptDraw(st); vdr_pinsDraw(st); } else toast(tr('Tap on the image to set a point')); return; }  // 2.641.0 (#4769)
  if (a === 'pin') { vdr_pinGo(st, id); return; }
  if (a === 'mk') { vdr_cmHl(st, id); return; }
  if (a === 'pg') { vdr_pageGo(st, st.page + (+b.dataset.d || 0)); return; }
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
    if (a === 'signew') {  // 2.642.0 (#4772): expiry and "older versions too" set when the link is made; 2.766.0 (#5321): the own date picker (hidden input), no native one
      const d = $('.vdrsigdate', st.md)?.value || null, old = !!$('.vdrsigold', st.md)?.checked;
      await rawFetch('POST', `/api/videos/${rid}/signoff`, {expires: d, show_old: old}); await vdr_after(rid, 'GET', `/api/videos/${rid}`); toast(tr('Client link created'));
    }
    if (a === 'sigstop') {
      if (!await askConfirm(tr('Stop the client link?'), tr('It stops working at once.'), {ok: tr('Switch off'), danger: true})) return;
      await rawFetch('POST', `/api/videos/${rid}/signoffs/${id}/revoke`); await vdr_after(rid, 'GET', `/api/videos/${rid}`); toast(tr('Client link stopped'));
    }
    if (a === 'sigcopy') { const i = $(`[data-vdrurl="${id}"]`, st.md); try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); } }
  } catch (x) { toast(x.message); }
  if (VDR.cur === st) vdr_draw(st, false);
}
function vdr_menu(anchor, st) {
  const r = st.r, rid = r.id, w = r.can_write;
  menu(anchor, [
    w && !vdr_media(vdr_v(st)) && {label: tr('New version…'), icon: 'upload', fn: () => vdr_newVersion(st)},
    w && {label: tr('New version from a file…'), icon: 'upload', fn: () => vdr_newFile(null, 0, st)},  // 2.641.0 (#4769)
    w && {label: tr('Rename…'), icon: 'edit', fn: () => vdr_rename(st)},
    '-',
    {label: tr('Copy comments as text'), icon: 'copy', fn: () => vdr_copyText(st)},
    {label: tr('Download comments (CSV)'), icon: 'download', fn: () => { location.href = `/api/videos/${rid}/export?version_id=${st.ver}`; }},
    vdr_stored(vdr_v(st)) ? vdr_v(st).content && {label: tr('Download the file'), icon: 'download', fn: () => { location.href = vdr_v(st).content + '?dl=1'; }}
      : {label: tr('Open the original link'), icon: 'link', fn: () => window.open(vdr_v(st).url, '_blank', 'noopener,noreferrer')},
    '-',
    w && !r.versions.some(vdr_stored) && typeof smv_can === 'function' && smv_can(r.org_id) && {label: tr('Move to another workspace…'), icon: 'arrow', fn: () => vdr_move(st)},  // 2.641.0 (#4769): files stay in their workspace
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
  histToast(tr('Approval {0} deleted', qn(r.title)), histAdd({label: tr('Deleted {0}', qn(r.title)), ids: [], snaps: [], lids: [],
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
// ---- 2.641.0 (#4769): images (JPG, PNG, WebP) and PDFs of the file store in the same review: a comment sits at a point of the
// image / of a PDF page (x / y 0..1), shown as a numbered point; a tap on the image sets the point, a tap on a comment's number
// shows it (a PDF opens that page). The PDF pages come from the bundled pdf.js of the PDF preview (pdfview.js, module pdf).
const vdr_media = v => !!v && (v.kind === 'image' || v.kind === 'pdf');
// 2.658.0 (#5015): + audio files (the server decides by the first bytes; the file store's type is only the browser's guess)
const VDR_ACCEPT = 'image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf,audio/*,.mp3,.m4a,.aac,.wav,.ogg,.oga,.opus,.flac';
const VDR_FILE_RE = /^(image\/(jpeg|png|webp)|application\/pdf|audio\/[\w.+-]+)$/;
const vdr_stored = v => !!v && !!v.file_name;  // 2.658.0 (#5015): a version from the file store (image, PDF or audio)
function vdr_mediaHtml(v) {
  if (!v.content) return `<div class="vdrnolink">${ic('info', 's')}<p>${esc(tr('The file of this version is no longer in the file store.'))}</p></div>`;
  const stage = `<div class="vdrstage" data-vdr-stage>${v.kind === 'pdf' ? '<div class="vdrcv"></div>' : `<img src="${esc(v.content)}" alt="${esc(v.file_name || '')}" draggable="false">`}<div class="vdrpins"></div></div>`;
  return `<div class="vdrmedia vdrk-${v.kind}">${v.kind === 'pdf' ? `<div class="vdrpgbar" hidden><button type="button" class="iconbtn" data-vdr="pg" data-d="-1" aria-label="${esc(tr('Previous page'))}" title="${esc(tr('Previous page'))}">${ic('left')}</button>
    <span class="vdrpgno" aria-live="polite"></span><button type="button" class="iconbtn" data-vdr="pg" data-d="1" aria-label="${esc(tr('Next page'))}" title="${esc(tr('Next page'))}">${ic('right')}</button></div>
    <div class="vdrpgmsg muted">${esc(tr('Loading…'))}</div>` : ''}${stage}</div>`;
}
function vdr_mediaLoad(st) {
  const v = vdr_v(st), box = $('.vdrstage', st.md); if (!box) return;
  const img = $('img', box);
  if (img) img.addEventListener('error', () => { $('.vdrpl', st.md).innerHTML = `<div class="vdrnolink">${ic('info', 's')}<p>${esc(tr('File damaged or missing'))}</p></div>`; }, {once: true});
  if (v.kind === 'pdf') vdr_pageGo(st, st.page || 1);
}
// one PDF page at the width of the view; the document is fetched once per version (same origin, nothing in it runs)
async function vdr_pageGo(st, n) {
  const v = vdr_v(st), box = $('.vdrstage', st.md); if (!box || v.kind !== 'pdf' || !v.content) return;
  const my = st.pgen = (st.pgen || 0) + 1, msg = $('.vdrpgmsg', st.md);
  try {
    if (!st.pdf || st.pdf.ver !== v.id) {
      await loadModule('pdf');
      const res = await fetch(v.content, {credentials: 'same-origin'});
      if (!res.ok) throw new Error(tr('File damaged or missing'));
      const data = new Uint8Array(await res.arrayBuffer());
      const lib = await pv_timed(pv_load());
      const task = lib.getDocument({data, isEvalSupported: false, enableScripting: false, disableAutoFetch: true, stopAtErrors: false, useSystemFonts: true});
      const doc = await pv_timed(task.promise, task);
      if (my !== st.pgen || !st.md.isConnected) { doc.destroy(); return; }
      try { st.pdf?.doc.destroy(); } catch { /* gone */ }
      st.pdf = {ver: v.id, doc};
    }
    const doc = st.pdf.doc;
    st.page = Math.max(1, Math.min(doc.numPages, n || 1));
    const page = await doc.getPage(st.page);
    const w = Math.max(200, box.parentElement.clientWidth || 600), vp = page.getViewport({scale: w / page.getViewport({scale: 1}).width});
    const dpr = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(16e6 / (vp.width * vp.height)));
    const cv = document.createElement('canvas');
    cv.width = Math.floor(vp.width * dpr); cv.height = Math.floor(vp.height * dpr);
    cv.setAttribute('aria-label', tr('Page {0}', st.page));
    await page.render({canvas: cv, canvasContext: cv.getContext('2d'), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null}).promise;
    if (my !== st.pgen || !st.md.isConnected) return;
    $('.vdrcv', box).replaceChildren(cv);
    box.dataset.page = String(st.page);
    if (msg) msg.hidden = true;
    const bar = $('.vdrpgbar', st.md);
    if (bar) {
      bar.hidden = doc.numPages < 2;
      $('.vdrpgno', bar).textContent = tr('Page {0} of {1}', st.page, doc.numPages);
      $('[data-d="-1"]', bar).disabled = st.page <= 1; $('[data-d="1"]', bar).disabled = st.page >= doc.numPages;
    }
    if (st.pt && st.pt.page !== st.page) st.pt = null;
    vdr_pinsDraw(st); vdr_ptDraw(st);
  } catch (e) {
    if (my !== st.pgen || !st.md.isConnected) return;
    if (msg) { msg.hidden = false; msg.textContent = e?.name === 'PasswordException' ? tr('This PDF is protected with a password and cannot be shown here.') : e?.message && e.name === 'Error' ? e.message : tr('The preview could not be loaded.'); }
  }
}
// the composer's point button follows without drawing the composer again (the text typed stays)
function vdr_ptDraw(st) {
  const b = $('[data-vdr="pt"]', st.md); if (!b) return;
  b.classList.toggle('on', !!st.pt); b.setAttribute('aria-pressed', String(!!st.pt));
  b.title = st.pt ? tr('Tap to comment without a point') : tr('Tap on the image to set a point');
  $('span', b).textContent = st.pt ? tr('at point {0}', vdr_nextMark(st)) : tr('without point');
}
// the next point's number (the comments with a point of this version + 1)
const vdr_nextMark = st => vdr_top(st).filter(c => c.mark).length + 1;
function vdr_pinsDraw(st) {
  const v = vdr_v(st), el = $('.vdrpins', st.md); if (!el || !vdr_media(v)) return;
  const pdf = v.kind === 'pdf', ms = vdr_top(st).filter(c => c.mark && (!pdf || c.page === st.page));
  el.innerHTML = ms.map(c => `<button type="button" class="vdrpin ${c.done ? 'done' : ''}" data-vdr="mk" data-id="${c.id}" style="left:${(c.pos.x * 100).toFixed(2)}%;top:${(c.pos.y * 100).toFixed(2)}%" aria-label="${esc(tr('Point {0}', c.mark) + ': ' + c.body.slice(0, 60))}" title="${esc(c.body.slice(0, 80))}">${c.mark}</button>`).join('')
    + (st.pt && (!pdf || st.pt.page === st.page) ? `<span class="vdrpin new" style="left:${(st.pt.x * 100).toFixed(2)}%;top:${(st.pt.y * 100).toFixed(2)}%" aria-hidden="true">${vdr_nextMark(st)}</span>` : '');
}
function vdr_stageTap(e, st) {  // a tap on the image / page (not on a point): the point of the next comment
  const box = e.target.closest('[data-vdr-stage]'); if (!box || e.target.closest('.vdrpin') || st.reply) return false;
  const v = vdr_v(st), r = box.getBoundingClientRect();
  if (!r.width || !r.height || (v.kind === 'pdf' && !$('canvas', box))) return true;
  const cl = x => Math.round(Math.max(0, Math.min(1, x)) * 10000) / 10000;
  st.pt = {x: cl((e.clientX - r.left) / r.width), y: cl((e.clientY - r.top) / r.height), page: v.kind === 'pdf' ? st.page : null};
  vdr_pinsDraw(st); vdr_ptDraw(st);
  $('#vdr-in', st.md)?.focus({preventScroll: true});
  return true;
}
function vdr_cmHl(st, id) {  // a tap on a point: its comment in the list
  const li = $(`.vdrc[data-cid="${id}"]`, st.md); if (!li) return;
  li.scrollIntoView({block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  li.classList.remove('hl'); void li.offsetWidth; li.classList.add('hl');
}
async function vdr_pinGo(st, id) {  // a tap on a comment's number: its page, its point marked
  const c = st.r.comments.find(x => x.id === id); if (!c) return;
  if (c.page && c.page !== st.page && vdr_v(st).kind === 'pdf') await vdr_pageGo(st, c.page);
  const p = $(`.vdrpin[data-id="${id}"]`, st.md);
  $('.vdrstage', st.md)?.scrollIntoView({block: 'nearest'});
  if (p) { p.classList.remove('hl'); void p.offsetWidth; p.classList.add('hl'); p.focus({preventScroll: true}); }
}
function vdr_space(k, id) {  // the workspace of a section ('' = unknown: only the search)
  const l = k === 'list_id' ? listById(id) : k === 'task_id' ? listById(taskById(id)?.list_id) : null;
  return l ? (l.org_id ? 'org:' + l.org_id : 'private') : '';
}
// a new review (k / id = its place) or a new version (st) from an image / PDF: an upload or a file of the file store
function vdr_newFile(k, id, st) {
  const sp = st ? (st.r.org_id ? 'org:' + st.r.org_id : 'private') : vdr_space(k, id), ps = {parent: null, q: '', n: 0};
  const md = modal(`<form class="vdrform vdrfile" novalidate><h3 id="vdr-ft">${st ? tr('New version') : tr('Add image, PDF or audio')}</h3>
    <div class="shint">${esc(tr('Images (JPG, PNG, WebP), PDFs and audio files (MP3, M4A, AAC, WAV, OGG, Opus, FLAC). The file stays in the file store; comments sit at a point or, for audio, at a second.'))}</div>
    <label class="btn pri vdrup">${ic('upload', 's')} ${tr('Upload a file')}<input type="file" id="vdr-file" class="sr" accept="${VDR_ACCEPT}"></label>
    <p class="muted mhint">${esc(tr('Uploads go into the folder “Approvals” of the file store. Who may not see the file there does not see the approval.'))}</p>
    <h4>${tr('From the file store')}</h4>
    <div class="ctsearch">${ic('search', 's')}<input id="vdr-fq" type="search" placeholder="${esc(tr('Find a file'))}" aria-label="${esc(tr('Find a file'))}" autocomplete="off"></div>
    <div class="wempick vdrpick" role="list"></div>
    ${st ? '' : `<label for="vdr-ttl">${tr('Title')}</label><input id="vdr-ttl" maxlength="200" placeholder="${esc(tr('e.g. Logo draft'))}">`}
    <div class="calerr" role="alert" hidden></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button></div></form>`);
  md.setAttribute('aria-labelledby', 'vdr-ft');
  const list = $('.vdrpick', md), err = $('.calerr', md);
  const load = async () => {
    const n = ++ps.n;
    if (!ps.q && !ps.parent && !sp) { list.innerHTML = `<p class="muted">${esc(tr('Find a file'))}</p>`; return; }
    list.innerHTML = `<p class="muted">${esc(tr('Loading…'))}</p>`;
    let j; try { j = await rawFetch('GET', ps.q ? `/api/files/search?q=${encodeURIComponent(ps.q)}${sp ? '&space=' + encodeURIComponent(sp) : ''}` : ps.parent ? `/api/files?parent=${ps.parent}` : `/api/files?space=${encodeURIComponent(sp)}`); }
    catch (e) { if (n === ps.n) list.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
    if (n !== ps.n) return;
    const its = (j.items || []).filter(x => !x.no_access && ((x.kind === 'file' && VDR_FILE_RE.test(x.mime || '')) || (x.kind === 'folder' && !ps.q)));
    list.innerHTML = (ps.parent && !ps.q ? `<button type="button" role="listitem" class="wemit" data-vdrf="up">${ic('left', 's')}<span class="wemn">${esc(tr('Back'))}</span></button>` : '')
      + (its.length ? its.map(x => `<button type="button" role="listitem" class="wemit" data-vdrf="${x.id}">${ic(x.kind === 'folder' ? 'folder' : x.mime === 'application/pdf' ? 'pdf' : /^audio\//.test(x.mime || '') ? 'music' : 'picture', 's')}<span class="wemn">${esc(x.name)}</span>${x.kind === 'file' ? `<small class="muted">${fmtSize(x.size || 0)}</small>` : ''}</button>`).join('')
        : `<p class="muted">${esc(ps.q ? tr('Nothing found') : tr('No files here yet.'))}</p>`);
    list._its = its; list._up = j.parent_id ?? (j.crumbs || []).slice(-2, -1)[0]?.id ?? null;
  };
  const send = async payload => {
    err.hidden = true;
    let r; try { r = await rawFetch('POST', st ? `/api/videos/${st.r.id}/versions` : '/api/videos', payload); } catch (x) { err.textContent = x.message; err.hidden = false; return; }
    md.remove();
    if (st) { vdr_fileVersion(st, r, payload); return; }
    vdr_cache(r);
    const h = histAdd({label: tr('Created {0}', qn(r.title)), ids: [], snaps: [], lids: [],
      undo: async () => { await rawFetch('DELETE', `/api/videos/${r.id}`); vdr_cache(r, true); vdr_closeIf(r.id); return {skipped: []}; },
      redo: async () => { vdr_cache(await rawFetch('POST', `/api/videos/${r.id}/restore`)); return {skipped: []}; }});
    histToast(tr('Approval {0} created', qn(r.title)), h);
    vdr_open(r.id, r);
  };
  const title = () => ($('#vdr-ttl', md)?.value || '').trim();
  $('#vdr-file', md).addEventListener('change', e => {
    const f = e.target.files?.[0]; if (!f) return;
    const fd = new FormData();
    fd.append('file', f, f.name);
    if (!st) { fd.append(k, String(id)); if (title()) fd.append('title', title()); }
    send(fd);
  });
  const qSoon = debounce(v => { ps.q = v; load(); }, 250);  // 2.641.0 (#4769): core.js debounce, no hand-made delay (#4506)
  $('#vdr-fq', md).addEventListener('input', e => qSoon(e.target.value.trim()));
  md.addEventListener('submit', e => e.preventDefault());
  md.addEventListener('click', e => {
    if (e.target.closest('[data-m="close"]')) { md.remove(); return; }
    const b = e.target.closest('[data-vdrf]'); if (!b) return;
    // 2.962.0 (#5232): a folder deeper is a step of Back; the list's own "Back" = that step
    if (b.dataset.vdrf === 'up') { f8d_backBtn(md, () => { ps.parent = list._up || null; load(); }); return; }
    const x = (list._its || []).find(i => i.id === +b.dataset.vdrf); if (!x) return;
    if (x.kind === 'folder') { const was = ps.parent; f8d_step(md, () => { ps.parent = was; load(); }); ps.parent = x.id; load(); return; }
    send(st ? {file_id: x.id} : {[k]: id, file_id: x.id, title: title()});
  });
  load();
  setTimeout(() => $('#vdr-fq', md)?.focus(), 60);
}
function vdr_fileVersion(st, j, payload) {  // a new version from a file: shown at once, one undo step (its file stays in the file store)
  const rid = st.r.id;
  st.r = j; vdr_cache(j);
  let nid = j.new_version;
  st.ver = nid; st.pt = null; st.page = 1; vdr_draw(st, true);
  const fid = (j.versions.find(v => v.id === nid) || {}).file_id;
  histToast(tr('Version {0} added', 'v' + j.version), histAdd({label: tr('Version {0} added', 'v' + j.version), ids: [], snaps: [], lids: [],
    undo: async () => { await vdr_after(rid, 'DELETE', `/api/videos/${rid}/versions/${nid}`); return {skipped: []}; },
    redo: async () => { const x = await vdr_after(rid, 'POST', `/api/videos/${rid}/versions`, payload instanceof FormData ? {file_id: fid} : payload); nid = x.new_version; return {skipped: []}; }}));
}
document.addEventListener('click', e => {  // the sections (task, project, client)
  const b = e.target.closest('[data-vdr="open"],[data-vdr="new"],[data-vdr="newfile"]'); if (!b || b.closest('.vdrdlg')) return;
  e.preventDefault();
  if (b.dataset.vdr === 'open') vdr_open(+b.dataset.id); else if (b.dataset.vdr === 'newfile') vdr_newFile(b.dataset.k, +b.dataset.i); else vdr_new(b.dataset.k, +b.dataset.i);
});
