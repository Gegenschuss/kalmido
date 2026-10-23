// @ts-check
/* Kalmido web client: voice messages in the team chat (2.139.0 B, #2128), loaded on demand (lazyload.js module voice).
   Classic script sharing the global scope with the others. */
'use strict';

// Recording: getUserMedia + MediaRecorder (no library). The format is the first the browser records of audio/mp4 (AAC: plays on
// iOS and Android), webm / ogg (Opus). Tap the microphone = recording starts; the bar over the composer shows the running time,
// discard and send (stop = listen first). At most TVC_MAX_MS, then the recording stops and waits for send / discard. The file
// goes the way of every chat file (multipart POST, voice=1 + duration_ms): same quota, virus scan, encryption at rest.
// Kalmido never transcribes. Playback: one shared <audio> element (only one message plays at a time), a slim player per file.
const TVC_MAX_MS = 5 * 60 * 1000;
const TVC_TYPES = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/ogg'];
const TVC_RATES = [1, 1.5, 2];
/** @type {{st: any, audio: HTMLAudioElement | null, cur: any, rate: number, pos: Record<string, number>}} */
const TVC = {st: null, audio: null, cur: null, rate: 1, pos: {}};

const tvc_can = () => !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
const tvc_mime = () => TVC_TYPES.find(t => { try { return MediaRecorder.isTypeSupported(t); } catch { return false; } }) || '';
const tvc_ext = mime => /mp4|aac|m4a/.test(mime) ? 'm4a' : /ogg/.test(mime) ? 'ogg' : 'webm';
function tvc_clock(ms) {
  const s = Math.max(0, Math.round((ms || 0) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
const tvc_rateTxt = r => new Intl.NumberFormat(document.documentElement.lang || undefined).format(r) + '×';

// ---- composer: the microphone (only while the text box is empty and files may be sent here) + the recording bar
function tvc_micHtml(room, rid) {
  if (!tvc_can() || typeof tcx_filesOk !== 'function' || !tcx_filesOk(room)) return '';
  const typed = !!(S.drafts['team:' + rid] || '').trim();
  return `<button type="button" class="iconbtn tvcmic${typed ? ' hidden' : ''}" data-act="tvc-rec" data-rid="${rid}" title="${esc(tr('Record a voice message'))}" aria-label="${esc(tr('Record a voice message'))}">${ic('mic')}</button>`;  // 2.213.0 (#2788): the bar comes from tvc_barSlot (the button may sit in the plus menu)
}
const tvc_barSlot = rid => TVC.st?.rid === rid ? tvc_barHtml() : '';  // 2.213.0 (#2788)
function tvc_barHtml() {
  const st = TVC.st, rec = st.phase === 'rec', busy = st.phase === 'send';
  const mid = rec
    ? `<span class="tvcdot" aria-hidden="true"></span><span class="tvcclock" role="timer" aria-live="off">${tvc_clock(Date.now() - st.t0)}</span><span class="muted tvcmax">/ ${tvc_clock(TVC_MAX_MS)}</span><span class="spacer"></span>
       <button type="button" class="iconbtn" data-act="tvc-stop" title="${esc(tr('Stop and listen'))}" aria-label="${esc(tr('Stop and listen'))}">${ic('stop')}</button>`
    : `<button type="button" class="iconbtn tvcpb" data-act="tvc-preview" title="${esc(tr('Listen'))}" aria-label="${esc(tr('Listen'))}">${ic(TVC.cur === 'rec' && TVC.audio && !TVC.audio.paused ? 'pause' : 'play')}</button>
       <span class="tvcclock">${tvc_clock(st.ms)}</span>${st.auto ? `<span class="muted tvcmax">${esc(tr('Maximum length reached'))}</span>` : ''}<span class="spacer"></span>`;
  return `<div class="tvcrec${rec ? ' on' : ''}" role="group" aria-label="${esc(tr('Voice message'))}">
    <button type="button" class="iconbtn" data-act="tvc-discard" title="${esc(tr('Discard'))}" aria-label="${esc(tr('Discard'))}"${busy ? ' disabled' : ''}>${ic('trash')}</button>
    ${mid}<button type="button" class="btn pri" data-act="tvc-send"${busy ? ' disabled' : ''}>${ic('send', 's')}<span>${busy ? esc(tr('Sending…')) : esc(tr('Send'))}</span></button></div>`;
}
function tvc_draw() {
  $$('.tvcrec').forEach(x => x.remove());
  const st = TVC.st; if (!st) return;
  const mic = $(`.tccomp [data-act="tvc-rec"][data-rid="${st.rid}"]`); if (mic) mic.closest('.tccomp').insertAdjacentHTML('beforeend', tvc_barHtml());  // 2.213.0 (#2788): over the whole row, not inside the plus menu
}
function tvc_tick() {
  const st = TVC.st; if (!st || st.phase !== 'rec') return;
  const ms = Date.now() - st.t0, el = $('.tvcrec .tvcclock'); if (el) el.textContent = tvc_clock(ms);
  if (ms >= TVC_MAX_MS) tvc_stop(true);
}
async function tvc_start(rid) {
  if (TVC.st) return;
  if (!tvc_filesHere(rid)) return;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
  catch (e) {
    const n = e?.name || '';
    toast(n === 'NotAllowedError' || n === 'SecurityError' ? tr('The microphone is blocked: allow it in the browser or app settings, then try again')
      : n === 'NotFoundError' || n === 'OverconstrainedError' ? tr('No microphone found on this device') : tr('The recording could not start'), null, 6000);
    return;
  }
  const mime = tvc_mime();
  let rec;
  try { rec = mime ? new MediaRecorder(stream, {mimeType: mime}) : new MediaRecorder(stream); }
  catch { stream.getTracks().forEach(t => t.stop()); toast(tr('The recording could not start')); return; }
  tvc_audioStop();
  /** @type {any} */
  const st = TVC.st = {rid, rec, stream, chunks: [], t0: Date.now(), ms: 0, phase: 'rec', mime: rec.mimeType || mime || 'audio/webm'};
  rec.ondataavailable = e => { if (e.data?.size) st.chunks.push(e.data); };
  st.done = new Promise(res => { rec.onstop = res; });
  rec.start(1000);
  st.timer = setInterval(tvc_tick, 250);
  tvc_draw();
  $('.tvcrec [data-act="tvc-send"]')?.focus();
}
const tvc_filesHere = rid => S.tc.rid === rid && tcx_filesOk(S.tc.room);
async function tvc_stop(auto) {
  const st = TVC.st; if (!st || st.phase !== 'rec') return;
  st.phase = 'stop'; clearInterval(st.timer);
  st.ms = Math.min(Date.now() - st.t0, TVC_MAX_MS); st.auto = !!auto;
  try { if (st.rec.state !== 'inactive') st.rec.stop(); } catch { /* already stopped */ }
  await st.done;
  st.stream.getTracks().forEach(t => t.stop());
  if (TVC.st !== st) return;  // discarded meanwhile
  st.blob = new Blob(st.chunks, {type: st.mime.split(';')[0]});
  st.phase = 'review'; tvc_draw();
}
function tvc_discard() {
  const st = TVC.st; if (!st) return;
  TVC.st = null; clearInterval(st.timer);
  try { if (st.rec.state !== 'inactive') st.rec.stop(); } catch { /* already stopped */ }
  st.stream.getTracks().forEach(t => t.stop());
  if (TVC.cur === 'rec') tvc_audioStop();
  if (st.url) URL.revokeObjectURL(st.url);
  tvc_draw(); $('#tc-in')?.focus();
}
function tvc_name() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `${tr('Voice message').replace(/\s+/g, '-')}-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.${tvc_ext(TVC.st.mime)}`;
}
async function tvc_send() {
  let st = TVC.st; if (!st || st.phase === 'send') return;
  if (st.phase === 'rec') await tvc_stop();
  st = TVC.st; if (!st || st.phase !== 'review') return;
  if (!st.blob?.size) { toast(tr('The recording is empty')); tvc_discard(); return; }
  const rid = st.rid, ck = 't:' + rid, file = new File([st.blob], tvc_name(), {type: st.blob.type});
  st.phase = 'send'; tvc_draw();
  const fd = tcx_form('', replyTo(ck), null, [file]); fd.append('voice', '1'); fd.append('duration_ms', String(Math.round(st.ms)));
  let m;
  try { m = await rawFetch('POST', `/api/team/rooms/${rid}/messages`, fd); }
  catch (e) {
    if (TVC.st === st) { st.phase = 'review'; tvc_draw(); }  // the recording stays: send again or discard
    toast(e instanceof Offline ? tr('You are offline: the voice message was not sent') : e.message); return;
  }
  if (TVC.st === st) { TVC.st = null; if (TVC.cur === 'rec') tvc_audioStop(); if (st.url) URL.revokeObjectURL(st.url); tvc_draw(); }
  replySent(ck);
  const live = S.tc.rid === rid;
  if (live && !S.tc.msgs.some(x => x.id === m.id)) S.tc.msgs.push(m);
  const r = (S.tc.rooms || []).find(x => x.id === rid); if (r) { r.last = {id: m.id, user_id: m.user_id, text: file.name, created_at: m.created_at}; r.last_at = m.created_at; }
  if (live) tcPatch(true);
}

// ---- playback: one <audio> for the whole app
/** play() synchronously (iOS: inside the tap), its promise's refusal handled; err = what a refusal does */
function tvc_go(au, err) {
  let p; try { p = au.play(); } catch (e) { if (err) err(e); return; }
  if (p && typeof p.catch === 'function') p.catch(e => { if (err) err(e); });
}
function tvc_el() {
  if (TVC.audio) return TVC.audio;
  const au = TVC.audio = new Audio(); au.preload = 'metadata';
  au.addEventListener('timeupdate', tvc_progress);
  au.addEventListener('play', tvc_state); au.addEventListener('pause', tvc_state);
  au.addEventListener('ended', () => { if (TVC.cur != null) TVC.pos[TVC.cur] = 0; tvc_state(); tvc_progress(); });
  au.addEventListener('error', () => {
    const id = TVC.cur; if (id == null || !au.getAttribute('src')) return;
    $$(`[data-tvc="${id}"]`).forEach(x => x.classList.add('err'));
    toast(tr('This recording cannot be played on this device: download it instead'), null, 6000); tvc_state();
  });
  return au;
}
function tvc_audioStop() {
  const au = TVC.audio; if (!au) return;
  au.pause(); au.removeAttribute('src'); au.load(); TVC.cur = null; tvc_state();
}
const tvc_durOf = (box, au) => +box?.dataset.ms || (au && isFinite(au.duration) ? au.duration * 1000 : 0);
function tvc_progress() {
  const au = TVC.audio, id = TVC.cur; if (!au || id == null || id === 'rec') return;
  $$(`[data-tvc="${id}"]`).forEach(box => {
    const d = tvc_durOf(box, au), t = au.currentTime * 1000, s = box.querySelector('.tvcseek');
    if (s && d && document.activeElement !== s) s.value = String(Math.min(1000, Math.round(t / d * 1000)));
    const c = box.querySelector('.tvct'); if (c) c.textContent = tvc_clock(d ? Math.max(0, d - t) : t);
    TVC.pos[id] = d ? t / d : 0;
  });
}
function tvc_state() {
  const au = TVC.audio, on = au && !au.paused;
  $$('.tvcp').forEach(box => {
    const me = on && String(TVC.cur) === box.dataset.tvc, b = box.querySelector('[data-act="tvc-play"]');
    box.classList.toggle('on', !!me);
    if (b) { b.innerHTML = ic(me ? 'pause' : 'play'); b.setAttribute('aria-label', me ? tr('Pause') : tr('Play')); b.title = b.getAttribute('aria-label'); }
  });
  const pb = $('.tvcrec [data-act="tvc-preview"]'); if (pb) pb.innerHTML = ic(on && TVC.cur === 'rec' ? 'pause' : 'play');
}
function tvc_play(box, at) {
  const au = tvc_el(), id = +box.dataset.tvc;
  if (TVC.cur === id && at == null) { if (au.paused) tvc_go(au); else au.pause(); return; }
  if (TVC.cur !== id) {
    au.pause(); TVC.cur = id; au.src = box.dataset.src; au.playbackRate = TVC.rate;
    const f = at ?? TVC.pos[id] ?? 0;
    if (f > 0 && f < 1) au.addEventListener('loadedmetadata', () => { const d = tvc_durOf(box, au); if (d) au.currentTime = f * d / 1000; }, {once: true});
  } else if (at != null) { const d = tvc_durOf(box, au); if (d) au.currentTime = at * d / 1000; }
  tvc_go(au, e => { if (e?.name === 'NotSupportedError') au.dispatchEvent(new Event('error')); });
}
function tvc_preview() {
  const st = TVC.st, au = tvc_el(); if (!st?.blob) return;
  if (TVC.cur === 'rec') { if (au.paused) tvc_go(au); else au.pause(); return; }
  au.pause(); st.url ||= URL.createObjectURL(st.blob); TVC.cur = 'rec'; au.src = st.url; au.playbackRate = 1; tvc_go(au);
}
// a file of a chat message: the player (voice messages and other audio files)
function tvc_playerHtml(a) {
  const id = a.id, ms = a.duration_ms || 0, on = TVC.cur === id && TVC.audio && !TVC.audio.paused, pos = TVC.pos[id] || 0;
  const lbl = on ? tr('Pause') : tr('Play');
  return `<div class="att tvcp${a.voice ? ' voice' : ''}${on ? ' on' : ''}" data-tvc="${id}" data-src="${esc(attUrl(a))}" data-ms="${ms}">
    <button type="button" class="tvcpb" data-act="tvc-play" title="${esc(lbl)}" aria-label="${esc(lbl)}">${ic(on ? 'pause' : 'play')}</button>
    <span class="tvcmain">${a.voice ? '' : `<span class="tvcn">${esc(a.name)}</span>`}<input type="range" class="tvcseek" min="0" max="1000" step="1" value="${Math.round(pos * 1000)}" aria-label="${esc(tr('Playback position'))}"></span>
    <span class="tvct">${tvc_clock(ms && pos ? ms * (1 - pos) : ms)}</span>
    <button type="button" class="tvcrt" data-act="tvc-rate" title="${esc(tr('Playback speed'))}" aria-label="${esc(tr('Playback speed'))}">${tvc_rateTxt(TVC.rate)}</button>
    <a class="iconbtn tvcdl" href="${esc(attUrl(a, true))}" download="${esc(a.name)}" title="${esc(tr('Download'))}" aria-label="${esc(tr('Download') + ': ' + a.name)}">${ic('download', 's')}</a></div>`;
}

document.addEventListener('click', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-act^="tvc-"]'); if (!a) return;
  const act = a.dataset.act;
  if (act === 'tvc-rec') tvc_start(+a.dataset.rid);
  else if (act === 'tvc-stop') tvc_stop();
  else if (act === 'tvc-discard') tvc_discard();
  else if (act === 'tvc-send') tvc_send();
  else if (act === 'tvc-preview') tvc_preview();
  else if (act === 'tvc-play') tvc_play(a.closest('.tvcp'));
  else if (act === 'tvc-rate') {
    TVC.rate = TVC_RATES[(TVC_RATES.indexOf(TVC.rate) + 1) % TVC_RATES.length];
    if (TVC.audio && TVC.cur !== 'rec') TVC.audio.playbackRate = TVC.rate;
    $$('.tvcrt').forEach(x => { x.textContent = tvc_rateTxt(TVC.rate); });
  } else return;
  e.preventDefault(); e.stopPropagation();
});
document.addEventListener('input', ev => {
  const e = {target: /** @type {any} */ (ev.target)};
  if (e.target.classList?.contains('tvcseek')) { const box = e.target.closest('.tvcp'); if (box) tvc_play(box, +e.target.value / 1000); return; }
  if (e.target.id === 'tc-in') { const mic = e.target.closest('.tccomp')?.querySelector('.tvcmic'); if (mic) mic.classList.toggle('hidden', !!e.target.value.trim()); }
});
document.addEventListener('keydown', e => {  // Escape while recording = discard (the recording is not sent by accident)
  if (e.key === 'Escape' && TVC.st && TVC.st.phase !== 'send' && /** @type {any} */ (e.target).closest?.('.tvcrec')) { e.preventDefault(); e.stopPropagation(); tvc_discard(); }
}, true);
