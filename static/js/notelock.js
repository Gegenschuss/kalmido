/* Kalmido web client: lock a task's note with one's own password (2.48.0, #1642).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   Built on the end-to-end keys of e2e.js (passphrase + recovery code): the note (tasks.content) is encrypted here with the
   person's content key (AES-256-GCM, AAD "kalmido-locknote:v1:<task id>:<user id>") and stored as ciphertext
   (kalmido/collab/notelock.py); the server empties the plain note. Unlocked once per session (the keys of e2e.js), the note
   can be read and changed here; "Remove lock" writes it back as a normal note. Only in own lists that are not shared. */
'use strict';

// notes: task id -> {text, open, loading, err, state} (decrypted text of this session only)
const LN = {notes: {}, saveT: null};
const ln_aad = tid => `kalmido-locknote:v1:${tid}:${S.me.id}`;
const ln_ok = () => !!(S.me && S.me.kind !== 'agent' && globalThis.crypto?.subtle);
// an own list that is not shared with people (agents may be on it: they never read a locked note); the server decides
// 2.64.1 (#1817): not in a list with a lock (its texts are encrypted with the list key already)
const ln_listOk = l => !!l && isOwner(l) && !(l.shared_people > 0) && l.org_visibility !== 'org' && !l.e2e;
// the lock under an unlocked note (detail.js): only where locking is possible and there is something to lock
function ln_btnHtml(t, ro) {
  if (ro || !ln_ok() || !(t.id > 0) || t.note_locked || t.context || !(t.content || '').trim() || !ln_listOk(listById(t.list_id))) return '';
  return `<div class="lnbar"><button type="button" class="linkbtn lnlock" data-ln="lock" title="${esc(tr('Encrypt the note with your own password'))}">${ic('lock', 's')}<span>${tr('Lock note')}</span></button></div>`;
}
// the note field of a task with a locked note (instead of the description)
function ln_html(t, ro) {
  const lock = ic('lock'), mine = !!t.note_locked_mine && ln_ok();
  const shell = (inner, cls = '') => `<div class="dsec lnote ${cls}" id="d-ln">${inner}</div>`;
  if (!mine) return shell(`<div class="lnph">${lock}<div><b>${tr('Locked note')}</b><span class="muted">${tr('Only the person who locked it can read it.')}</span></div></div>`);
  const n = LN.notes[t.id];
  if (!e2eUnlocked() || !n?.open) {
    if (n && !e2eUnlocked()) delete LN.notes[t.id];  // the keys were locked: the decrypted text goes too
    return shell(`<button type="button" class="lnph lnopen" data-ln="open">${lock}<div><b>${tr('Locked note')}</b><span class="muted">${tr('Unlock to view')}</span></div></button>`);
  }
  if (n.loading) return shell(`<div class="lnph">${lock}<div><b>${tr('Locked note')}</b><span class="muted">${tr('Decrypting…')}</span></div></div>`);
  if (n.err) return shell(`<div class="lnph">${lock}<div><b>${tr('Locked note')}</b><span class="muted">${tr('Cannot be decrypted')}</span></div></div>
    ${ro ? '' : `<div class="lnacts"><button type="button" class="btn sm danger" data-ln="drop">${ic('trash', 's')} ${tr('Delete the locked note')}</button></div>`}`);
  return shell(`<div class="lnhead">${ic('lock', 's')}<span>${tr('Locked note')}</span><span class="spacer"></span>
      <button type="button" class="btn sm" data-ln="hide" title="${esc(tr('Hide the note again'))}">${tr('Lock now')}</button>
      ${ro ? '' : `<button type="button" class="btn sm" data-ln="remove" title="${esc(tr('The note becomes a normal note again: readable by everyone who sees the task, by agents and in search.'))}">${tr('Remove lock')}</button>`}</div>
    <textarea id="d-ln-in" class="dcontent" rows="4" aria-label="${esc(tr('Locked note'))}" spellcheck="true" ${ro ? 'readonly' : ''}>${esc(n.text || '')}</textarea>
    <div class="lnmeta muted" id="d-ln-st" role="status">${esc(n.state || tr('Encrypted in your browser; only you can read it'))}</div>`, 'lnopen-on');
}
// a hint in the share dialog of a list that holds locked notes (dialogs.js shareModal)
function ln_shareHint(lid) {
  const n = [...S.tasks.values()].filter(t => t.list_id === lid && t.note_locked && !t.deleted_at).length;
  return n ? `<div class="shint lhint keep lnhint">${ic('lock', 's')} ${esc(tr('{0} locked notes in this project stay unreadable for everyone you share it with.', n))}</div>` : '';
}
// moving a task with a locked note into a shared list (undo.js patchUndoable): a hint, the note stays locked
function ln_moveHint(tid, lid) {
  const t = taskById(tid), l = listById(lid);
  if (t?.note_locked && l && !ln_listOk(l)) toast(tr('The note stays locked: nobody else in this project can read it.'));
}

async function ln_load(tid) {
  LN.notes[tid] = {tid, text: '', open: true, loading: true};
  if (S.sel === tid) renderDetail();
  try {
    const j = await rawFetch('GET', `/api/tasks/${tid}/note-lock`);
    LN.notes[tid] = {tid, text: e2eTDec().decode(await e2eOpen(E2E.ckey, j.body, ln_aad(tid))), open: true};
  } catch { LN.notes[tid] = {tid, text: '', open: true, err: true}; }
  if (S.sel === tid) renderDetail();
  return LN.notes[tid];
}
async function ln_open(tid) {
  if (!await e2eEnsure()) return null;
  return ln_load(tid);
}
// the keys ready for locking: set up first (with the warning) or unlocked
async function ln_keys() {
  await e2eLoad();
  if (!LS.get('lnWarned', false) || !e2eReady()) {
    const ok = await askConfirm(tr('Lock the note with your own password'), tr('The note is encrypted in your browser with your encryption passphrase. Only you can open it. If you lose the passphrase and the recovery code, the note is lost: nobody can restore it, not even the operator of this server.'),
      {ok: e2eReady() ? tr('Lock note') : tr('Set up')});
    if (!ok) return false;
    LS.set('lnWarned', true);
  }
  if (!e2eReady()) return e2eSetupDlg();
  return e2eUnlocked() || e2eUnlockDlg();
}
// lock: encrypt the current note, the server keeps only the ciphertext and empties the note. One undo step (= remove the lock).
async function ln_lock(tid, again) {
  const t = taskById(tid); if (!t || t.note_locked) return;
  if (!ln_listOk(listById(t.list_id))) { toast(tr('Notes can only be locked in projects that are not shared.')); return; }
  if (!again && !await ln_keys()) return;
  if (!e2eUnlocked()) return;
  if (typeof flushSaves === 'function') await flushSaves();  // the last typing reaches the server first
  if (OUT.q.some(o => ln_outHit(o, tid))) { toast(tr('Changes are still waiting to be sent. Try again when you are online.')); return; }
  const text = taskById(tid)?.content || '';
  try { await rawFetch('PUT', `/api/tasks/${tid}/note-lock`, {body: await e2eSeal(E2E.ckey, e2eTEnc().encode(text), ln_aad(tid))}); }
  catch (x) { toast(x instanceof Offline ? tr('Locking needs a connection') : x.message); return; }
  Object.assign(t, {content: '', note_locked: true, note_locked_mine: true});
  delete LN.notes[tid]; S.editContent = false;
  ln_forget(tid);
  if (!again) histAdd({label: tr('Note locked'), lids: [t.list_id], undo: async () => (await ln_remove(tid, true)) ? {} : {none: true}, redo: async () => { await ln_lock(tid, true); return {}; }});
  if (S.sel === tid) renderDetail();
  render();
  if (!again) toast(tr('Note locked'));
}
// 2.48.0 review (L7): a waiting write of this task -- its own URL (not /api/tasks/12 for 1) or a batch that carries it
function ln_outHit(o, tid) {
  const u = String(o.url || '');
  return new RegExp(`^/api/tasks/${+tid}(/|\\?|$)`).test(u) || (u === '/api/tasks/batch' && (o.body?.ids || []).map(Number).includes(+tid));
}
// 2.48.0 review (S3): the keys were locked / the person signed out: no decrypted note stays in this tab, a waiting save goes
function ln_wipe() {
  LN.notes = {}; clearTimeout(LN.saveT); LN.saveT = null;
}
// no plain copy stays in this tab: undo steps that carry the old note of this task go (the lock itself is the one new step),
// the offline copy of the state follows
function ln_forget(tid) {
  const hit = e => !!e && ((e.parts || []).some(hit) || [...(e.snaps || []), ...(e.after || [])].some(s => s && s.id === tid) || (e.ids || []).includes(tid));
  HIST.undo = HIST.undo.filter(e => !hit(e)); HIST.redo = HIST.redo.filter(e => !hit(e));
  if (typeof renderHist === 'function') renderHist();
  // 2.48.0 review (L7): an edit conflict about this note keeps both texts in localStorage: it goes
  if (S.conflicts?.some(x => x.tid === tid && x.field === 'content')) {
    S.conflicts = S.conflicts.filter(x => !(x.tid === tid && x.field === 'content')); LS.set('conflicts', S.conflicts);
    if (typeof renderTop === 'function') renderTop();
  }
  // the offline copy of the state (localStorage 'cache') gets the empty note at once, not only with the next delta
  const ct = Array.isArray(S.lpCache?.tasks) ? S.lpCache.tasks.find(x => x.id === tid) : null;
  if (ct) { Object.assign(ct, {content: '', note_locked: true, note_locked_mine: true}); if (typeof lpCacheSoon === 'function') lpCacheSoon(); }
}
// remove the lock for good: the decrypted text becomes the task's note again
async function ln_remove(tid, again) {
  const t = taskById(tid); if (!t?.note_locked_mine) return false;
  if (!again && !await askConfirm(tr('Remove the lock?'), tr('The note becomes a normal note again: readable by everyone who sees the task, by agents and in search.'), {ok: tr('Remove lock')})) return false;
  let n = LN.notes[tid];
  if (!n?.open || n.loading || n.err) n = await ln_open(tid);
  if (!n || n.err) return false;
  try { await rawFetch('DELETE', `/api/tasks/${tid}/note-lock`, {content: n.text}); }
  catch (x) { toast(x instanceof Offline ? tr('Needs a connection') : x.message); return false; }
  t.content = n.text; delete t.note_locked; delete t.note_locked_mine; delete LN.notes[tid];
  if (!again) histAdd({label: tr('Lock removed'), lids: [t.list_id], undo: async () => { await ln_lock(tid, true); return {}; }, redo: async () => (await ln_remove(tid, true)) ? {} : {none: true}});
  if (S.sel === tid) renderDetail();
  render();
  if (!again) toast(tr('Lock removed'));
  return true;
}
async function ln_save(tid) {
  const n = LN.notes[tid]; if (!n || !n.open || n.err || !e2eUnlocked()) return;
  const st = () => { const el = $('#d-ln-st'); if (el && S.sel === tid) el.textContent = n.state; };
  try { await rawFetch('PUT', `/api/tasks/${tid}/note-lock`, {body: await e2eSeal(E2E.ckey, e2eTEnc().encode(n.text), ln_aad(tid))}); n.state = tr('Encrypted and saved'); }
  catch (x) { n.state = x instanceof Offline ? tr('Offline: the locked note is saved when you are online again') : x.message; if (x instanceof Offline) LN.saveT = setTimeout(() => ln_save(tid), 15000); }
  st();
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-ln]'); if (!b || !S.sel) return;
  e.preventDefault();
  const tid = S.sel, a = b.dataset.ln;
  if (a === 'lock') ln_lock(tid);
  else if (a === 'open') { const n = await ln_open(tid); if (n && !n.err) setTimeout(() => $('#d-ln-in')?.focus(), 30); }
  else if (a === 'hide') { if (LN.saveT) { clearTimeout(LN.saveT); LN.saveT = null; await ln_save(tid); } delete LN.notes[tid]; renderDetail(); $('#d-ln .lnopen')?.focus(); }
  else if (a === 'remove') ln_remove(tid);
  else if (a === 'drop' && await askConfirm(tr('Delete the locked note?'), tr('It cannot be decrypted any more. Deleting it cannot be undone.'), {ok: tr('Delete'), danger: true})) {
    try { await rawFetch('DELETE', `/api/tasks/${tid}/note-lock`, {}); } catch (x) { toast(x.message); return; }
    const t = taskById(tid); if (t) { delete t.note_locked; delete t.note_locked_mine; t.content = ''; }
    delete LN.notes[tid]; renderDetail();
  }
});
document.addEventListener('input', e => {
  if (e.target.id !== 'd-ln-in' || !S.sel) return;
  const tid = S.sel, n = LN.notes[tid]; if (!n) return;
  n.text = e.target.value; n.state = tr('Saving…'); autosize(e.target);
  clearTimeout(LN.saveT); LN.saveT = setTimeout(() => { LN.saveT = null; ln_save(tid); }, 900);
});
document.addEventListener('focusout', e => { if (e.target.id === 'd-ln-in' && S.sel && LN.saveT) { clearTimeout(LN.saveT); LN.saveT = null; ln_save(S.sel); } });
