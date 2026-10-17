/* Kalmido web client: the lock per list -- dialogs and display (2.64.1, #1817). The lock section of the list dialog, member
   status (key pending, not set up, safety number, rotation pending), placeholders, disabled features with their reason, the
   administration overview. Uses the data layer liste2e.js (le2e*). */
'use strict';

// Wording (decision E10): "encrypted in the browser"; "end-to-end" only in the explanation, together with its limit.
// The display reads the lock state from the list in the state (l.e2e, e2e_gen, e2e_rotate, e2e_pending, e2e_mine); every
// action goes through the data layer (le2eStart / le2eStop / le2eResume / le2eRelease / le2eUnlock / le2eSafety ...).
const LE2U = {run: {}, rot: {}, chg: {}};  // rot: list id -> {done, total} of the re-encryption after a key change (2.64.2); chg: key changes per list  // list id -> {kind: 'start' | 'stop' | 'resume', done, total} while a switch runs in this tab
const LE2U_NA = N_('Not available in encrypted lists');
const le2u_mode = lid => listById(lid)?.e2e || null;
const le2u_on = lid => !!le2u_mode(lid);
// the data layer (part C) by name; typeof works for names that are not declared (yet)
const le2u_fns = () => ({le2eLocked: typeof le2eLocked, le2eInfo: typeof le2eInfo, le2eUnlock: typeof le2eUnlock, le2eReady: typeof le2eReady,
  le2eStart: typeof le2eStart, le2eStop: typeof le2eStop, le2eResume: typeof le2eResume, le2eRelease: typeof le2eRelease, le2eSafety: typeof le2eSafety,
  le2eKeyChanged: typeof le2eKeyChanged, le2eAcceptKey: typeof le2eAcceptKey, le2eRotate: typeof le2eRotate, le2eReenc: typeof le2eReenc});
const le2u_fn = n => le2u_fns()[n] === 'function';
const le2u_locked = t => !!t && le2u_on(t.list_id) && (le2u_fn('le2eLocked') ? !!le2eLocked(t) : t._le2e === 'locked');
// a member of a locked list who has no key of the current generation yet (waits for the owner / a list admin)
const le2u_waiting = lid => { const l = listById(lid); return !!l && l.e2e === 'on' && l.e2e_mine === false; };
const le2u_info = (lid, force) => le2u_fn('le2eInfo') ? le2eInfo(lid, force) : rawFetch('GET', `/api/lists/${lid}/e2e`);
const le2u_na = () => tr(LE2U_NA);
// a greyed-out feature with its reason (the share dialog's look, sharedlg.js fshGrey)
const le2u_grey = (txt, why = le2u_na()) => `<div class="fshgrey le2ugrey" aria-disabled="true"><span>${ic('lock', 's')} ${esc(txt)}</span><small class="muted">${esc(why)}</small></div>`;

// ------------------------------------------------------------------ marks: sidebar, header of the list
function le2u_mark(l, cls = 'le2um') {
  if (!l?.e2e) return '';
  const t = l.e2e === 'on' ? tr('Encrypted in the browser') : l.e2e === 'decrypting' ? tr('Being decrypted') : tr('Being encrypted');
  return `<span class="${cls}${l.e2e === 'on' ? '' : ' busy'}" role="img" title="${esc(t)}" aria-label="${esc(t)}">${ic('lock', 's')}</span>`;
}
const le2u_sideMark = l => le2u_mark(l, 'shr le2um');
const le2u_headMark = l => le2u_mark(l, 'le2um le2uh');

// ------------------------------------------------------------------ placeholders: task row, detail
function le2u_who(lid) {  // who can release the key: the owner (a list admin can too)
  const l = listById(lid); return l?.owner_name || (l && isOwner(l) ? S.me?.display_name : '') || tr('The owner');
}
function le2u_ttlHtml(t) {
  if (le2u_waiting(t.list_id)) return `<span class="le2uph wait">${ic('lock', 's')}<span>${esc(tr('Key pending – {0} has to release it', le2u_who(t.list_id)))}</span></span>`;
  return `<span class="le2uph" role="button" tabindex="0" data-le2u="unlock" data-lid="${t.list_id}" aria-label="${esc(tr('Encrypted – unlock'))}">${ic('lock', 's')}<span>${esc(tr('Encrypted – unlock'))}</span></span>`;
}
function le2u_detailHtml(t) {
  if (le2u_waiting(t.list_id)) return `<div class="dsec le2ud"><div class="lnph">${ic('lock')}<div><b>${esc(tr('Encrypted in the browser'))}</b><span class="muted">${esc(tr('Key pending – {0} has to release it', le2u_who(t.list_id)))}</span></div></div></div>`;
  return `<div class="dsec le2ud"><button type="button" class="lnph lnopen" data-le2u="unlock" data-lid="${t.list_id}">${ic('lock')}<div><b>${esc(tr('Encrypted in the browser'))}</b><span class="muted">${esc(tr('Unlock to read and change the title and description'))}</span></div></button></div>`;
}
async function le2u_unlock(lid) {
  if (!le2u_fn('le2eUnlock')) return;
  let ok = false;
  try { ok = await le2eUnlock(lid); } catch (x) { if (x?.message) toast(x.message); return; }
  // 2.64.1 review 2 (M2): texts that do not open with the unwrapped key (a swapped list key) or no key at all: said, never silent
  const n = typeof le2eUnreadable === 'function' ? le2eUnreadable(lid) : 0;
  if (n) toast(tr('{0} texts of this list cannot be opened with your key. Compare the safety numbers with the members.', n));
  else if (!ok && !le2u_waiting(lid) && typeof e2eUnlocked === 'function' && e2eUnlocked()) toast(tr('The list key could not be opened. Compare the safety numbers with the members.'));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-le2u="unlock"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();  // the row would open the detail: here it unlocks first
  le2u_unlock(+b.dataset.lid);
}, true);
// 2.64.1 review (L5): the row's placeholder is reachable with Tab; Enter / Space on it unlocks (the row's own keys stay as they are)
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const b = e.target.closest?.('.le2uph[data-le2u="unlock"]'); if (!b || e.target !== b) return;
  e.preventDefault(); e.stopPropagation();
  le2u_unlock(+b.dataset.lid);
}, true);

// ------------------------------------------------------------------ the bar above a locked list (render.js render0)
function le2u_barHtml(l) {
  const run = LE2U.run[l.id], btn = (act, txt, pri) => `<button type="button" class="btn sm${pri ? ' pri' : ''}" data-le2ubar="${act}" data-lid="${l.id}">${esc(txt)}</button>`;
  if (run) return `${ic('lock', 's')}<span class="annt">${esc(run.kind === 'stop' ? tr('Decrypting the list…') : tr('Encrypting the list…'))}</span>${le2u_pbar(run)}`;
  if (l.e2e === 'encrypting' || l.e2e === 'decrypting') {
    const t = l.e2e === 'encrypting' ? tr('This list is being encrypted. Texts can be changed again when it is done.') : tr('This list is being decrypted. Texts can be changed again when it is done.');
    return `${ic('lock', 's')}<span class="annt">${esc(t)}</span>${canManage(l) ? btn('resume', tr('Continue'), true) : ''}`;
  }
  if (l.e2e !== 'on') return '';
  if (l.e2e_mine === false) return `${ic('lock', 's')}<span class="annt">${esc(tr('Key pending – {0} has to release it', le2u_who(l.id)))}</span>`;
  const n = canManage(l) ? +l.e2e_pending || 0 : 0;
  if (n) return `${ic('key', 's')}<span class="annt">${esc(trn('{0} person is waiting for the key', '{0} people are waiting for the key', n))}</span>${btn('release', tr('Release'), true)}`;
  if (le2u_fn('le2eReady') && !le2eReady(l.id)) return `${ic('lock', 's')}<span class="annt">${esc(tr('Encrypted list: unlock to read and write.'))}</span>${btn('unlock', tr('Unlock'), true)}`;
  return '';
}
function le2u_barSync() {
  const main = $('#main'); if (!main) return;
  const l = S.route?.mod === 'tasks' && typeof routeList === 'function' ? routeList() : null;
  const html = l && (l.e2e || LE2U.run[l.id]) ? le2u_barHtml(l) : '';
  let bar = $('#le2ubar');
  if (!html) { bar?.remove(); return; }
  if (!bar) {
    bar = document.createElement('div'); bar.id = 'le2ubar'; bar.className = 'annbar le2ubar'; bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', tr('Encrypted in the browser'));
    const ab = $('#ntfask') || $('#annbar'); if (ab) ab.after(bar); else main.prepend(bar);
  }
  if (bar.innerHTML !== html) bar.innerHTML = html;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-le2ubar]'); if (!b) return;
  const lid = +b.dataset.lid, a = b.dataset.le2ubar;
  if (a === 'unlock') le2u_unlock(lid);
  else if (a === 'release') le2u_release(lid);
  else if (a === 'resume') le2u_run(lid, 'resume');
});
document.addEventListener('le2e:change', () => { le2u_barSync(); const md = $('#l-e2e')?.closest('.modal'); if (md) le2u_listDraw(md, +$('#l-e2e').dataset.lid); });

// ------------------------------------------------------------------ progress of switching on / off (abort-safe)
const le2u_pbar = r => { const p = r && r.total ? Math.min(1, r.done / r.total) : 0; return `<span class="le2upb" role="progressbar" aria-valuemin="0" aria-valuemax="${r?.total || 0}" aria-valuenow="${r?.done || 0}" aria-label="${esc(tr('Progress'))}"><i style="transform:scaleX(${p.toFixed(3)})"></i></span><span class="muted le2upn">${r?.total ? esc(tr('{0} of {1}', r.done, r.total)) : ''}</span>`; };
function le2u_progUi(lid) {
  le2u_barSync();
  const box = $(`#l-e2e[data-lid="${lid}"] .le2uprog`), r = LE2U.run[lid];
  if (box && r) box.innerHTML = le2u_pbar(r);
}
// kind: start | stop | resume; the switch itself (keys, todo / bulk / finish) is the data layer's
async function le2u_run(lid, kind, password) {
  if (LE2U.run[lid]) return false;
  const fn = kind === 'start' ? 'le2eStart' : kind === 'stop' ? 'le2eStop' : 'le2eResume';
  if (!le2u_fn(fn)) { toast(tr('Please reload the app.')); return false; }
  LE2U.run[lid] = {kind: kind === 'resume' ? (le2u_mode(lid) === 'decrypting' ? 'stop' : 'start') : kind, done: 0, total: 0};
  const onProgress = p => { const r = LE2U.run[lid]; if (!r || !p) return; r.done = +p.done || 0; r.total = +p.total || 0; le2u_progUi(lid); };
  le2u_progUi(lid); le2u_listRedraw(lid);
  let ok = false;
  try {
    await (kind === 'stop' ? le2eStop(lid, password, onProgress) : kind === 'start' ? le2eStart(lid, onProgress) : le2eResume(lid, onProgress));
    ok = true;
    toast(LE2U.run[lid].kind === 'stop' ? tr('The lock of the list is open') : tr('The list is encrypted in the browser'));
  } catch (x) {
    if (x?.message) toast(x.message);
  } finally {
    delete LE2U.run[lid];
    try { await load(); } catch { /* offline: the next sync */ }
    render(); le2u_listRedraw(lid);
  }
  return ok;
}
async function le2u_release(lid) {
  if (!le2u_fn('le2eRelease')) return;
  let j; try { j = await le2u_info(lid, true); } catch (x) { toast(x?.message || tr('Not possible right now')); return; }
  const ids = (j.pending || []).filter(p => p.has_keys).map(p => p.user_id);
  if (!ids.length) { toast(tr('Nobody waiting has set up encryption yet')); return; }
  let r; try { r = await le2eRelease(lid, ids); } catch (x) { if (x?.message) toast(x.message); return; }
  const n = ids.length - (r?.skipped?.length || 0);  // 2.64.1 review: a copy the server kept (skipped) is no new release
  toast(trn('Key released for {0} person', 'Key released for {0} people', n));
  try { await load(); } catch { /* next sync */ }
  render(); le2u_listRedraw(lid);
  $$('.shmodal').forEach(md => { if (md._le2uLid === lid) { md._le2u = null; md._le2uDraw?.(); } });
}

// ------------------------------------------------------------------ list dialog: "Encrypted in the browser" (dialogs.js listModal)
const le2u_listRowHtml = l => !l?.id || l.is_inbox || S.me?.kind === 'agent' || !globalThis.crypto?.subtle ? ''
  : `<h4 id="l-e2e-h">${ic('lock', 's')} ${tr('Encrypted in the browser')}</h4><div class="le2ul" id="l-e2e" data-lid="${l.id}" aria-labelledby="l-e2e-h"><div class="muted mhint">${tr('Loading…')}</div></div>`;
const LE2U_WAY = {agent: N_('Remove the agent first'), public_link: N_('Delete the public link first'), org_open: N_('Take back “Everyone in the organisation” first'),
  participant: N_('Change the participant role first'),
  // 2.64.1 review (L4): the server's code is folder_participant; owner_setup (M2)
  folder_participant: N_('Change the participant role of the folder first'), owner_setup: N_('The owner sets it up in Settings > Account')};
function le2u_blockersHtml(bl) {
  if (!bl?.length) return '';
  return `<ul class="le2ubl" aria-label="${esc(tr('Not possible yet'))}">${bl.map(b => `<li>${ic('alert', 's')}<span>${esc(b.text || '')}${LE2U_WAY[b.code] ? ` <b>${esc(tr(LE2U_WAY[b.code]))}</b>` : ''}</span>${['agent', 'public_link', 'participant'].includes(b.code) ? `<button type="button" class="linkbtn" data-le2ul="share" data-code="${esc(b.code)}">${esc(tr('Share…'))}</button>` : ''}</li>`).join('')}</ul>`;
}
const le2u_ruleHtml = () => `<p class="shint lhint keep le2uexp">${esc(tr('End-to-end in the browser: the server only sees encrypted texts. Limit: a manipulated server could deliver changed app code; members keep what they have seen.'))}</p>`;
// 2.64.2 D (#1817): attachments and the list chat are encrypted with the list key now (the hint "not yet encrypted", E9, is gone).
// After a member left, the key changes (rotation) and the older contents are encrypted again in the background; until that is
// done the honest hint stays, with the progress and, for the owner / a list admin, the button to change the key or to continue.
const le2u_rotBusy = j => !!j && (j.rotate > 0 || j.reenc > 0);
function le2u_rotHint(j, lid) {
  if (!le2u_rotBusy(j)) return '';
  const r = LE2U.rot[lid], run = !!r;
  const btn = !j.can_manage || run ? '' : j.rotate > 0 ? (le2u_fn('le2eRotate') ? `<button type="button" class="btn sm" data-le2rot="rotate" data-lid="${lid}">${esc(tr('Change the key now'))}</button>` : '')
    : le2u_fn('le2eReenc') ? `<button type="button" class="btn sm" data-le2rot="reenc" data-lid="${lid}">${esc(tr('Continue'))}</button>` : '';
  return `<div class="shint lhint keep le2urot" data-lid="${lid}">${ic('alert', 's')} <span>${esc(tr('A member has left this list. The key is being changed; until everything is encrypted again, former members can still decrypt older contents with their old key.'))}</span>`
    + (run ? `<span class="le2urotp">${le2u_pbar(r)}</span>` : '') + (btn ? `<span class="row">${btn}</span>` : '') + '</div>';
}
document.addEventListener('le2e:progress', e => {
  const d = e.detail || {}; if (!d.lid || d.kind !== 'reenc') return;
  if (d.total && d.done >= d.total) delete LE2U.rot[d.lid]; else LE2U.rot[d.lid] = {done: +d.done || 0, total: +d.total || 0};
  $$(`.le2urot[data-lid="${d.lid}"] .le2urotp`).forEach(x => { if (LE2U.rot[d.lid]) x.innerHTML = le2u_pbar(LE2U.rot[d.lid]); });
  if (!LE2U.rot[d.lid]) le2u_listRedraw(d.lid);
});
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-le2rot]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const lid = +b.dataset.lid, a = b.dataset.le2rot;
  if (typeof e2eEnsure === 'function' && !await e2eEnsure()) return;
  b.disabled = true; LE2U.rot[lid] = {done: 0, total: 0};
  try {
    if (a === 'rotate') await le2eRotate(lid, true);
    else await le2eReenc(lid, () => {});
  } catch (x) { if (x?.message) toast(x.message); } finally { delete LE2U.rot[lid]; }
  try { await load(); } catch { /* next sync */ }
  render(); le2u_listRedraw(lid);
}, true);
function le2u_listHtml(l, j, err) {
  const own = isOwner(l), run = LE2U.run[l.id];
  if (err) return `<div class="muted mhint">${esc(err)}</div>`;
  if (!j) return `<div class="muted mhint">${tr('Loading…')}</div>`;
  const mode = j.mode || null;
  const sw = (on, dis, title) => `<label class="chkl le2usw"${title ? ` title="${esc(title)}"` : ''}><input type="checkbox" role="switch" id="l-e2e-sw" ${on ? 'checked' : ''} ${dis ? 'disabled' : ''} aria-describedby="l-e2e-st"> ${esc(tr('Encrypt the texts of this list in the browser'))}</label>`;
  if (run || mode === 'encrypting' || mode === 'decrypting') {
    const st = (run ? run.kind === 'stop' : mode === 'decrypting') ? tr('Being decrypted') : tr('Being encrypted');
    return `<div class="row"><span class="tfastate" id="l-e2e-st">${esc(st)}</span></div><div class="le2uprog">${run ? le2u_pbar(run) : ''}</div>
      ${run ? `<div class="shint lhint">${esc(tr('Keep this window open. If it is closed, it continues as soon as you open the list again.'))}</div>`
        : `<div class="shint lhint">${esc(tr('Interrupted. It continues as soon as you open the list again.'))}</div>${j.can_manage ? `<div class="row"><span></span><button type="button" class="btn sm pri" data-le2ul="resume">${esc(tr('Continue'))}</button></div>` : ''}`}`;
  }
  if (mode === 'on') {
    const mine = (j.keys || []).some(k => k.gen === j.gen);
    return `<div class="row"><span class="tfastate on" id="l-e2e-st">${ic('lock', 's')} ${esc(tr('On'))}</span><span class="muted">${esc(tr('Titles, descriptions, comments, notes, attachments and the list chat are encrypted in the browser.'))}</span></div>
      ${mine ? '' : `<div class="shint lhint keep">${esc(tr('Key pending – {0} has to release it', l.owner_name || tr('The owner')))}</div>`}
      ${j.can_manage && (j.pending || []).length ? `<div class="row"><span class="muted">${esc(trn('{0} person is waiting for the key', '{0} people are waiting for the key', j.pending.length))}</span><button type="button" class="btn sm" data-le2ul="release">${esc(tr('Release'))}</button></div>` : ''}
      ${le2u_rotHint(j, l.id)}${le2u_ruleHtml()}
      <div class="row le2uacts"><button type="button" class="btn sm" data-le2ul="share">${ic('users', 's')} ${esc(tr('Members and keys…'))}</button>${own ? `<button type="button" class="btn sm" data-le2ul="stop">${esc(tr('Open the lock…'))}</button>` : ''}</div>`;
  }
  // open list
  const may = !!j.can_manage, setup = typeof e2eReady === 'function' && e2eReady(), bl = j.blockers || [];
  const why = !may ? tr('Only the owner and list admins can switch this on') : !setup ? tr('Set up your encryption first') : bl.length ? tr('Not possible yet') : '';
  return `<div class="row">${sw(false, !!why, why)}</div><div class="muted mhint" id="l-e2e-st">${esc(tr('Off'))}</div>
    ${may && !setup ? `<div class="shint lhint keep">${esc(tr('Your own encryption is not set up yet: a passphrase and a recovery code in Settings > Account.'))} <button type="button" class="linkbtn" data-le2ul="setup">${esc(tr('Set up'))}</button></div>` : ''}
    ${may ? le2u_blockersHtml(bl) : ''}
    <div class="shint lhint">${esc(tr('Only members can read titles, descriptions, comments and notes. No agents, no tasks by e-mail and no public link in this list.'))}</div>`;
}
function le2u_listDraw(md, lid) {
  const box = $('#l-e2e', md); if (!box) return;
  const l = listById(lid); if (!l) return;
  box.innerHTML = le2u_listHtml(l, box._j, box._err);
}
function le2u_listRedraw(lid) { const box = $(`#l-e2e[data-lid="${lid}"]`); if (box) le2u_listLoad(box.closest('.modal'), lid, true); }
async function le2u_listLoad(md, lid, force) {
  const box = md && $('#l-e2e', md); if (!box) return;
  le2u_listDraw(md, lid);
  try { box._j = await le2u_info(lid, force); box._err = ''; } catch (x) { box._err = x?.message || tr('Not possible right now'); }
  if (box.isConnected) le2u_listDraw(md, lid);
}
function le2u_listWire(md, lid) {
  const box = $('#l-e2e', md); if (!box) return;
  le2u_listLoad(md, lid);
  box.addEventListener('change', async e => {
    if (e.target.id !== 'l-e2e-sw') return;
    e.stopPropagation(); e.target.checked = false;  // switched on only after the notice
    if (await le2u_startDlg(lid, box._j)) le2u_run(lid, 'start');
    else le2u_listDraw(md, lid);
  });
  box.addEventListener('click', async e => {
    const b = e.target.closest('[data-le2ul]'); if (!b) return;
    e.stopPropagation();
    const a = b.dataset.le2ul;
    if (a === 'setup') { if (typeof e2eEnsure === 'function') e2eEnsure(); return; }
    if (a === 'share') { modalSub(md, () => shareModal(lid, {back: true, focus: b.dataset.code === 'agent' ? 'agents' : undefined})); return; }
    if (a === 'resume') { le2u_run(lid, 'resume'); return; }
    if (a === 'release') { le2u_release(lid); return; }
    if (a === 'stop') le2u_stop(lid);
  });
}
// the notice before switching on (concept section 4, short form 1-4); OK only after "I have read this"
async function le2u_startDlg(lid, j) {
  if (typeof e2eEnsure === 'function' && !await e2eEnsure()) return false;
  try { j = await le2u_info(lid, true); } catch (x) { toast(x?.message || tr('Not possible right now')); return false; }
  if ((j.blockers || []).length) { toast(tr('Not possible yet')); return false; }
  const ppl = (j.members || []).filter(m => m.kind !== 'agent');
  const miss = ppl.filter(m => !m.has_keys);
  const rows = ppl.map(m => `<li class="${m.has_keys ? 'ok' : 'no'}">${ic(m.has_keys ? 'check' : 'x', 's')}<span>${esc(m.name)}${S.me && m.user_id === S.me.id ? ' ' + esc(tr('(me)')) : ''}</span><small class="muted">${esc(m.has_keys ? tr('Encryption set up') : tr('Encryption not set up'))}</small></li>`).join('');
  const html = `${le2u_ruleHtml()}
    <ol class="le2unote">
      <li>${esc(tr('Passphrase and recovery code lost = the contents are lost. Nobody can restore them, not even the operator.'))}</li>
      <li>${esc(tr('Protects against a database leak, backups and the operator. Does not protect against a manipulated server (the app code comes from the server) or against members who have already seen the contents.'))}</li>
      <li>${esc(tr('In this list there are then no agents, no tasks by e-mail, no texts in calendar subscriptions and notifications, and no public link.'))}</li>
      <li>${esc(tr('Everyone in the list needs encryption set up:'))}<ul class="le2umem" aria-label="${esc(tr('Members'))}">${rows}</ul></li>
    </ol>
    ${miss.length ? `<p class="shint keep">${esc(tr('{0}: not set up yet. They go on the waiting list and see placeholders until they have set it up and the key is released to them.', miss.map(m => m.name).join(', ')))}</p>` : ''}
    <p class="shint keep">${esc(tr('Encrypted: titles, descriptions, subtasks, comments, notes, section names, free-text fields, links and code snippets. Readable stay: dates, status, priority, assignees, list name and tags.'))}</p>
    <p class="shint keep">${esc(tr('Attachments and the messages of the list chat are encrypted with it.'))}</p>
    <p class="shint keep">${esc(tr('Your personal recovery code is enough: there is no extra code for the list.'))}</p>
    <label class="chkl le2uack"><input type="checkbox" id="le2u-ack"> ${esc(tr('I have read this'))}</label>`;
  return askDialog({title: tr('Encrypt this list in the browser?'), html, ok: tr('Encrypt list'), after: d => {
    const ok = $('[data-cd="yes"]', d), ack = $('#le2u-ack', d); ok.disabled = true;
    ack.addEventListener('change', () => { ok.disabled = !ack.checked; });
    $('form', d).addEventListener('submit', e => { if (!ack.checked) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
  }});
}
// the way back: only the owner, with the account password (like removing one's keys in e2e.js)
async function le2u_stop(lid) {
  if (!await askConfirm(tr('Open the lock of this list?'), tr('Your browser decrypts every text and stores it readable again. Then search, agents and calendar texts work again. Old backups keep the encrypted texts.'), {ok: tr('Open the lock')})) return;
  if (typeof e2eEnsure === 'function' && !await e2eEnsure()) return;
  let password = '';
  if (E2E.st?.password !== false) {
    const p = await pwPrompt(tr('Confirm with your password'), {text: esc(tr('Opening the lock of a list needs your account password.'))});
    if (!p) return;
    password = p.password;
  }
  le2u_run(lid, 'stop', password);
}

// ------------------------------------------------------------------ share dialog: key state per person (dialogs.js shareModal)
function le2u_memberState(j, uid) {
  const m = (j.members || []).find(x => x.user_id === uid), w = (j.pending || []).find(x => x.user_id === uid);
  if (m && (m.key_gens || []).includes(j.gen)) return 'ok';
  if (w ? !w.has_keys : m && !m.has_keys) return 'none';
  return 'wait';
}
function le2u_rowExtra(j, uid, name, changed) {
  const st = le2u_memberState(j, uid), m = (j.members || []).find(x => x.user_id === uid), me = S.me && uid === S.me.id;
  const lab = st === 'ok' ? tr('Key present') : st === 'wait' ? tr('Key pending') : tr('Has not set up encryption yet');
  return `<span class="le2ust ${st}" title="${esc(lab)}">${ic(st === 'ok' ? 'key' : st === 'wait' ? 'hourglass' : 'alert', 's')}<span>${esc(lab)}</span></span>`
    + (st === 'wait' && j.can_manage && !me && !changed ? `<button type="button" class="btn sm" data-le2us="release" data-uid="${uid}" aria-label="${esc(tr('Release the key for {0}', name))}">${esc(tr('Release'))}</button>` : '')
    + (!me && m?.pub ? `<button type="button" class="iconbtn" data-le2us="safety" data-uid="${uid}" title="${esc(tr('Safety number'))}" aria-label="${esc(tr('Safety number of {0}', name))}">${ic('key', 's')}</button>` : '');
}
function le2u_shareHtml(j, changed) {
  const n = (j.pending || []).filter(p => p.has_keys).length;
  const warn = changed.map(([uid, name]) => `<div class="e2ewarn le2uchg" role="alert">${ic('alert', 's')}<span>${esc(tr('The key of {0} has changed. Compare the safety number with them before you release a key to them.', name))}</span><button type="button" class="btn sm" data-le2us="safety" data-uid="${uid}">${esc(tr('Safety number'))}</button><button type="button" class="btn sm" data-le2us="accept" data-uid="${uid}">${esc(tr('Understood'))}</button></div>`).join('');
  return `<div class="shint lhint keep">${ic('lock', 's')} ${esc(tr('Encrypted in the browser: compare the safety number with each person once on each of your devices; until then the key seen first counts unchecked. Participants and agents are not possible in this list.'))}</div>`
    + le2u_rotHint(j, j.list_id) + warn
    + (j.can_manage && n ? `<div class="row le2upend"><span>${esc(trn('{0} person is waiting for the key', '{0} people are waiting for the key', n))}</span><button type="button" class="btn sm pri" data-le2us="release-all">${esc(tr('Release'))}</button></div>` : '');
}
async function le2u_changed(j) {  // [[uid, name]] whose public key differs from the one this browser saw before
  if (!le2u_fn('le2eKeyChanged')) return [];
  const out = [];
  for (const m of j.members || []) {
    if ((S.me && m.user_id === S.me.id) || !m.pub) continue;
    try { if (await le2eKeyChanged(m.user_id)) out.push([m.user_id, m.name]); } catch { /* offline */ }
  }
  return out;
}
// called at the end of every draw() of the share dialog: rows and selects are new each time
function le2u_share(md, lid) {
  const l = listById(lid); if (!l?.e2e) return;
  md._le2uLid = lid;
  md._le2uDraw = () => le2u_share(md, lid);
  // decision E4: no participant role in a locked list; agents are not offered (finding M4)
  $$('select[data-mrole], #l-addrole, select[data-grole], #l-grprole', md).forEach(s => { $$('option[value="participant"]', s).forEach(o => o.remove()); });
  const aw = $('#sh-agwrap', md);
  if (aw && !aw.querySelector('.le2ugrey')) aw.innerHTML = le2u_grey(tr('Assign an agent')) + le2u_grey(tr('Listen in and tidy up'));
  const st = $('#sh-st-ag', md); if (st) st.textContent = le2u_na();
  const sec = $('#sh-sec-ag', md); if (sec) sec.hidden = false;
  const j = md._le2u;
  if (!j) {
    if (!md._le2uLoading) {
      md._le2uLoading = true;
      le2u_info(lid, true).then(async x => { md._le2u = x; md._le2uChg = await le2u_changed(x); }).catch(() => {}).finally(() => { md._le2uLoading = false; if (md.isConnected && md._le2u) le2u_share(md, lid); });
    }
    return;
  }
  const chg = md._le2uChg || [], chgIds = new Set(chg.map(c => c[0]));
  $$('#l-members .mrow[data-uid]', md).forEach(r => {
    $('.le2uex', r)?.remove();
    const uid = +r.dataset.uid, name = $('.n', r)?.textContent || '';
    r.insertAdjacentHTML('beforeend', `<span class="le2uex">${le2u_rowExtra(j, uid, name, chgIds.has(uid))}</span>`);
  });
  let top = $('#le2u-share', md);
  if (!top) { top = document.createElement('div'); top.id = 'le2u-share'; top.className = 'le2ushare'; $('#l-members', md)?.before(top); }
  const html = le2u_shareHtml(j, chg); if (top.innerHTML !== html) top.innerHTML = html;
  if (!md._le2uWired) {
    md._le2uWired = true;
    md.addEventListener('click', async e => {
      const b = e.target.closest('[data-le2us]'); if (!b) return;
      e.stopPropagation();
      const a = b.dataset.le2us, uid = +b.dataset.uid;
      if (a === 'safety') { le2u_safetyDlg(uid, (md._le2u?.members || []).find(m => m.user_id === uid)?.name || ''); return; }
      if (a === 'accept') { if (le2u_fn('le2eAcceptKey')) await le2eAcceptKey(uid); md._le2uChg = (md._le2uChg || []).filter(c => c[0] !== uid); le2u_share(md, lid); return; }
      if (a === 'release' || a === 'release-all') {
        if (!le2u_fn('le2eRelease')) return;
        const ids = a === 'release' ? [uid] : (md._le2u?.pending || []).filter(p => p.has_keys && !(md._le2uChg || []).some(c => c[0] === p.user_id)).map(p => p.user_id);
        if (!ids.length) return;
        b.disabled = true;
        try { const r = await le2eRelease(lid, ids); toast(trn('Key released for {0} person', 'Key released for {0} people', ids.length - (r?.skipped?.length || 0))); } catch (x) { if (x?.message) toast(x.message); b.disabled = false; return; }
        md._le2u = null; try { await load(); } catch { /* next sync */ } render(); le2u_share(md, lid);
      }
    });
  }
}
async function le2u_safetyDlg(uid, name) {
  let num = null;
  if (typeof e2eEnsure === 'function' && !await e2eEnsure()) return;
  try { num = le2u_fn('le2eSafety') ? await le2eSafety(uid) : null; } catch { /* offline */ }
  await askDialog({title: tr('Safety number'), html: num ? `<p>${esc(tr('Compare this number with {0} (in person or by phone). If it is the same on both devices, nobody sits in between.', name))}</p><code class="e2ecode">${esc(num)}</code>`
    : `<p>${esc(tr('{0} has not set up encryption yet', name))}</p>`, ok: tr('OK'), cancel: tr('Close')});
}

// ------------------------------------------------------------------ 2.64.2 D (#1817): safety numbers of all members, list chat and attachments
// le2uSafetyList: every person of the list with a key, their safety number and the warning when a key changed (with "Understood").
// le2uChanHead(room) / le2uAttHead(task): the line in the head of the list chat (part C) and of the attachments (part B) of a
// list with the lock -- synchronous HTML; the key-change warning is filled in after the check (le2u_headFill).
async function le2u_chgOf(lid, force) {
  const j = await le2u_info(lid, force);
  LE2U.chg[lid] = await le2u_changed(j);
  return j;
}
async function le2uSafetyList(lid) {
  if (typeof e2eEnsure === 'function' && !await e2eEnsure()) return;
  let j; try { j = await le2u_chgOf(lid, true); } catch (x) { toast(x?.message || tr('Not possible right now')); return; }
  const chg = new Set((LE2U.chg[lid] || []).map(c => c[0]));
  const ppl = (j.members || []).filter(m => m.kind !== 'agent' && m.has_keys && !(S.me && m.user_id === S.me.id));
  const nums = await Promise.all(ppl.map(m => (le2u_fn('le2eSafety') ? le2eSafety(m.user_id) : Promise.resolve(null)).catch(() => null)));
  const rows = ppl.map((m, i) => `<li class="le2usl${chg.has(m.user_id) ? ' chg' : ''}"><b>${esc(m.name)}</b>`
    + (chg.has(m.user_id) ? `<span class="e2ewarn" role="alert">${ic('alert', 's')} ${esc(tr('The key of {0} has changed.', m.name))} <button type="button" class="btn sm" data-le2usl="accept" data-uid="${m.user_id}">${esc(tr('Understood'))}</button></span>` : '')
    + `<code class="e2ecode">${esc(nums[i] || tr('Not available'))}</code></li>`).join('');
  await askDialog({title: tr('Safety numbers'), html: `<p class="shint">${esc(tr('Compare each number with the person (in person or by phone). If it is the same on both devices, nobody sits in between.'))}</p>`
    + (rows ? `<ul class="le2uslist">${rows}</ul>` : `<p class="muted">${esc(tr('Nobody else in this list has a key yet.'))}</p>`), ok: tr('OK'), cancel: tr('Close'), after: d => {
    d.addEventListener('click', async e => {
      const b = e.target.closest('[data-le2usl="accept"]'); if (!b) return;
      e.preventDefault();
      const uid = +b.dataset.uid;
      if (le2u_fn('le2eAcceptKey')) await le2eAcceptKey(uid);
      LE2U.chg[lid] = (LE2U.chg[lid] || []).filter(c => c[0] !== uid);
      b.closest('li')?.classList.remove('chg'); b.closest('.e2ewarn')?.remove();
      le2u_headFill(lid);
    });
  }});
}
function le2u_head(lid, what) {
  const l = listById(lid); if (!l?.e2e) return '';
  if (LE2U.chg[lid] === undefined && !LE2U['chk' + lid]) { LE2U['chk' + lid] = 1; le2u_chgOf(lid).catch(() => {}).finally(() => { delete LE2U['chk' + lid]; le2u_headFill(lid); }); }
  return `<div class="le2uhd" data-lid="${lid}" data-what="${what}">${ic('lock', 's')}<span>${esc(tr('Encrypted in the browser'))}</span>`
    + `<button type="button" class="linkbtn" data-le2uhd="safety" data-lid="${lid}">${esc(tr('Safety numbers'))}</button><span class="le2uhdw">${le2u_headWarn(lid)}</span></div>`;
}
function le2u_headWarn(lid) {
  const c = LE2U.chg[lid] || [];
  return c.length ? `<span class="e2ewarn" role="alert">${ic('alert', 's')} ${esc(tr('Key changed: {0}', c.map(x => x[1]).join(', ')))}</span>` : '';
}
function le2u_headFill(lid) { $$(`.le2uhd[data-lid="${lid}"] .le2uhdw`).forEach(x => { x.innerHTML = le2u_headWarn(lid); }); }
const le2uChanHead = room => le2u_head(room?.list_id, 'chan');
const le2uAttHead = t => le2u_head(t?.list_id, 'att');
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-le2uhd="safety"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  le2uSafetyList(+b.dataset.lid);
}, true);

// ------------------------------------------------------------------ features that are off in a locked list
// the share dialog's public link part (dialogs.js shareModal)
const le2u_pubHtml = () => le2u_grey(tr('Public link'));
// the playbook area of the list dialog (dialogs.js listModal) and the e-mail address of a list (dashboard.js mailHtml)
const le2u_pbHtml = () => `<h4>${tr('Playbook')}</h4>${le2u_grey(tr('Playbook'))}`;
const le2u_mailRow = x => `<div class="row mailrow"><label>${esc(x.name)}</label>${le2u_grey(tr('Create tasks by e-mail'), tr('Mails cannot be encrypted in the browser: the address of this list is off.'))}</div>`;
// News: the key was released to me (part A, kind e2e_key) and entries of a locked list without text (part B, enc: true)
function le2u_newsText(it, who, q) {
  return tr('{0} released the key for {1} to you', who, q(newsListName(it)));
}
function le2u_newsTitle(it) {  // the title of the task of a news entry of a locked list: decrypted here, else neutral
  const t = it.task_id && taskById(it.task_id);
  return t && t.title && !le2u_locked(t) ? t.title : tr('Encrypted task');
}

// ------------------------------------------------------------------ Settings > Administration > Encryption (cryptscope.js)
function le2u_scopeHtml(sc) {
  if (!sc || !Array.isArray(sc.browser) || !sc.browser.length) return '';
  return `<div class="pmcs br"><b>${ic('lock', 's')} ${esc(tr('Encrypted in the browser (lists with a lock)'))}</b><ul>${sc.browser.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
}

// ------------------------------------------------------------------ in-app help: Settings > Account > End-to-end encryption (e2e.js)
const le2u_helpHtml = () => `<p class="muted le2uhelp"><b>${esc(tr('Lists with a lock'))}</b> ${esc(tr('In the list dialog the owner or a list admin switches on “Encrypted in the browser”: titles, descriptions, comments, notes, section names, free-text fields, links and code snippets are then only readable for members with a key. Attachments and the list chat are encrypted with it. Agents, tasks by e-mail, public links and texts in calendars and notifications are off in such a list. When a member leaves, the key changes and older contents are encrypted again in the background. Your personal recovery code is enough.'))}</p>`;
