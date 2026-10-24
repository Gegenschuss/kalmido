/* Kalmido web client: finding people by e-mail, connection requests (2.49.0, #1106).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.49.0 (#1106): People (Settings > Account, the share dialog)
// One dialog: find a person by their full e-mail address (exact match, the same neutral answer for everything that is not
// findable), check my address books, requests in / out, my connections, the people I blocked, and my own "Findable by
// e-mail" (off by default; on = a confirmation link goes to my address). Every action is one undo step. The server is
// accounts/discover.py; agents have no access to any of it.
const DSC = {data: null, found: null, check: null};
const dsc_esc = s => esc(String(s ?? ''));
const dsc_av = p => `<span class="avatar${p.avatar ? ' pic' : ''}">${p.avatar ? `<img src="${dsc_esc(p.avatar)}" alt="" loading="lazy" decoding="async" draggable="false">` : dsc_esc(initials(p.name))}</span>`;
const dsc_on = () => !!S.me && !S.me.kid && collab();

// the row in Settings > Account
function dsc_rowHtml() {
  if (!dsc_on()) return '';
  return `<h4 id="s-dsc-h">${tr('People')}</h4>
    <div class="row"><label>${tr('Find people')}</label><button type="button" class="btn sm" data-dsc-open>${ic('users', 's')} ${tr('Find a person …')}</button></div>
    <div class="shint">${tr('Find people by their e-mail address and connect with them; requests and connections. Who may find you is your choice there.')}</div>`;
}

async function dsc_load() {
  DSC.data = await api('GET', '/api/disc');
  return DSC.data;
}

const dsc_stateHtml = p => ({
  connected: `<span class="muted dsc-st">${ic('check', 's')} ${tr('Connected')}</span>`,
  sent: `<span class="muted dsc-st">${tr('Request sent')}</span>`,
  incoming: `<button type="button" class="btn sm pri" data-dsc="accept-p" data-uid="${p.id}">${tr('Accept|connection')}</button>`,
})[p.state] || `<button type="button" class="btn sm pri" data-dsc="connect" data-ref="${dsc_esc(p.ref)}">${ic('plus', 's')} ${tr('Connect')}</button>`;
const dsc_personRow = (p, right) => `<div class="mrow dsc-row">${dsc_av(p)}<span class="n">${dsc_esc(p.name)}</span>${right}</div>`;

function dsc_html() {
  const d = DSC.data || {}, pr = d.profile || {};
  const inc = d.incoming || [], out = d.outgoing || [], cons = d.connections || [], bl = d.blocked || [];
  const found = DSC.found === undefined || DSC.found === null ? '' : DSC.found === false
    ? `<div class="muted mhint dsc-none" role="status">${tr('Not found. Only people who switched on “Findable by e-mail” can be found, and only with their full address.')}</div>`
    : dsc_personRow(DSC.found, dsc_stateHtml(DSC.found));
  const chk = DSC.check;
  const checkHtml = !chk ? '' : `<div class="dsc-check" role="status">${chk.people.length ? chk.people.map(p => dsc_personRow(p, dsc_stateHtml(p))).join('')
    : `<div class="muted mhint">${chk.books ? tr('None of your contacts can be found yet.') : tr('You have no contacts with e-mail addresses yet.')}</div>`}
    ${chk.skipped ? `<div class="shint">${tr('{0} addresses were not checked today (daily limit).', chk.skipped)}</div>` : ''}</div>`;
  const st = !pr.on ? '' : pr.confirmed ? tr('Findable by {0}', pr.email) : pr.pending ? tr('Waiting for your confirmation: open the link in the mail to {0}.', pr.email)
    : tr('Your address changed or was not confirmed: switch off and on again to confirm it.');
  return `<div class="lhdr"><h3>${ic('users', 's')} ${tr('Find people')}</h3><span class="spacer"></span><button class="iconbtn" data-dsc="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <form class="row dsc-find" data-dsc-form><input id="dsc-email" type="email" inputmode="email" autocomplete="off" autocapitalize="off" spellcheck="false" maxlength="200"
      placeholder="${dsc_esc(tr('Full e-mail address'))}" aria-label="${dsc_esc(tr('Full e-mail address'))}" enterkeyhint="search"><button type="submit" class="btn pri">${ic('search', 's')} ${tr('Search')}</button></form>
    <div id="dsc-found" aria-live="polite">${found}</div>
    ${feat('contacts') ? `<div class="row"><button type="button" class="btn sm" data-dsc="check">${ic('book', 's')} ${tr('Check my address book')}</button></div>
      <div class="shint">${tr('Shows which of your contacts use Kalmido and can be found. The addresses stay on this server.')}</div>${checkHtml}` : ''}
    ${inc.length ? `<h4 id="dsc-req-h">${tr('Requests')}</h4><div class="members" aria-labelledby="dsc-req-h">${inc.map(r => dsc_personRow(r.person,
      `<button type="button" class="btn sm pri" data-dsc="accept" data-rid="${r.id}">${tr('Accept|connection')}</button><button type="button" class="btn sm" data-dsc="decline" data-rid="${r.id}">${tr('Decline|connection')}</button><button type="button" class="iconbtn" data-dsc="block" data-uid="${r.person.id}" title="${dsc_esc(tr('Block|person'))}" aria-label="${dsc_esc(tr('Block {0}', r.person.name))}">${ic('ban', 's')}</button>`)).join('')}</div>` : ''}
    ${out.length ? `<h4 id="dsc-out-h">${tr('Sent requests')}</h4><div class="members" aria-labelledby="dsc-out-h">${out.map(r => dsc_personRow(r.person,
      `<span class="muted dsc-st">${tr('Request sent')}</span><button type="button" class="btn sm" data-dsc="withdraw" data-rid="${r.id}" data-ref="${dsc_esc(r.person.ref)}">${tr('Withdraw')}</button>`)).join('')}</div>` : ''}
    ${cons.length ? `<h4 id="dsc-con-h">${tr('Connections')}</h4><div class="members" aria-labelledby="dsc-con-h">${cons.map(r => dsc_personRow(r.person,
      `<button type="button" class="btn sm" data-dsc="drop" data-uid="${r.person.id}">${tr('Disconnect')}</button>`)).join('')}</div>` : ''}
    <h4 id="dsc-me-h">${tr('Findable by e-mail')}</h4>
    <div class="row"><label class="chkl"><input type="checkbox" id="dsc-findable" ${pr.on ? 'checked' : ''}> ${tr('Others can find me by my e-mail address')}</label></div>
    ${st ? `<div class="shint dsc-me" role="status">${dsc_esc(st)}</div>` : ''}
    <div class="shint">${tr('Only someone who knows your full address finds you. Nothing else is shown until you accept.')}</div>
    ${bl.length ? `<h4 id="dsc-bl-h">${tr('Blocked')}</h4><div class="members" aria-labelledby="dsc-bl-h">${bl.map(r => dsc_personRow(r.person,
      `<button type="button" class="btn sm" data-dsc="unblock" data-uid="${r.person.id}">${tr('Unblock')}</button>`)).join('')}</div>` : ''}`;
}

function dsc_draw(md) {
  const em = $('#dsc-email', md)?.value || '', foc = document.activeElement?.id;
  $('.card', md).innerHTML = dsc_html();
  const i = $('#dsc-email', md); if (i) { i.value = em; if (foc === 'dsc-email') i.focus(); }
}

// one undo step around an action; refresh = also reload the state (the people I see changed)
function dsc_step(md, label, undo, redo, refresh) {
  const again = async fn => { await fn(); await dsc_load(); if (refresh) { await load(); render(); } if (md.isConnected) dsc_draw(md); return {}; };
  const e = histAdd({label, undo: () => again(undo), redo: () => again(redo)});
  histToast(label, e);
}

async function dsc_open() {
  if (!dsc_on()) return;
  DSC.found = null; DSC.check = null;
  try { await dsc_load(); } catch { return; }
  const md = modal(dsc_html());
  md.classList.add('dscmodal');
  md.addEventListener('submit', async e => {
    if (!e.target.closest('[data-dsc-form]')) return;
    e.preventDefault();
    const v = $('#dsc-email', md).value.trim(); if (!v) return;
    try { const r = await api('POST', '/api/disc/find', {email: v}); DSC.found = r.person || false; } catch { return; }
    dsc_draw(md);
  });
  md.addEventListener('change', async e => {
    if (e.target.id !== 'dsc-findable') return;
    const on = e.target.checked;
    try { const r = await api('PUT', '/api/disc', {on}); DSC.data.profile = r.profile; if (r.sent) toast(tr('We sent you a mail: confirm your address with its link.')); }
    catch { e.target.checked = !on; return; }
    dsc_draw(md);
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-dsc]'); if (!b || !md.contains(b)) return;
    const k = b.dataset.dsc, rid = +b.dataset.rid, uid = +b.dataset.uid, ref = b.dataset.ref;
    const name = (b.closest('.dsc-row')?.querySelector('.n')?.textContent || '').trim();
    if (k === 'close') { md.remove(); return; }
    b.disabled = true;
    try {
      if (k === 'check') {
        DSC.check = await api('POST', '/api/disc/check');
      } else if (k === 'connect') {
        const r = await api('POST', '/api/disc/requests', {ref});
        const set = p => { if (p && p.ref === ref) p.state = r.state; };
        set(DSC.found); (DSC.check?.people || []).forEach(set);
        if (r.state === 'connected') { await load(); render(); toast(tr('Connected with {0}', name)); }
        else dsc_step(md, tr('Sent a connection request to {0}', name), () => api('DELETE', `/api/disc/requests/${r.id}`), () => api('POST', '/api/disc/requests', {ref}));
      } else if (k === 'accept' || k === 'accept-p') {
        const id = k === 'accept' ? rid : (DSC.data.incoming || []).find(x => x.person.id === uid)?.id; if (!id) return;
        await api('POST', `/api/disc/requests/${id}/accept`);
        const set = p => { if (p && p.id === uid) p.state = 'connected'; };
        set(DSC.found); (DSC.check?.people || []).forEach(set);
        await load(); render();
        dsc_step(md, tr('Connected with {0}', name), () => api('POST', `/api/disc/requests/${id}/reopen`), () => api('POST', `/api/disc/requests/${id}/accept`), true);
      } else if (k === 'decline') {
        await api('POST', `/api/disc/requests/${rid}/decline`);
        dsc_step(md, tr('Declined the request of {0}', name), () => api('POST', `/api/disc/requests/${rid}/reopen`), () => api('POST', `/api/disc/requests/${rid}/decline`));
      } else if (k === 'withdraw') {
        await api('DELETE', `/api/disc/requests/${rid}`);
        let cur = rid;
        dsc_step(md, tr('Withdrew the request to {0}', name), async () => { cur = (await api('POST', '/api/disc/requests', {ref})).id; }, () => api('DELETE', `/api/disc/requests/${cur}`));
      } else if (k === 'drop') {
        await api('DELETE', `/api/disc/connections/${uid}`);
        await load(); render();
        dsc_step(md, tr('Disconnected from {0}', name), () => api('POST', `/api/disc/connections/${uid}/restore`), () => api('DELETE', `/api/disc/connections/${uid}`), true);
      } else if (k === 'block') {
        const r = await api('POST', `/api/disc/blocks/${uid}`);
        if (r.unlinked) { await load(); render(); }
        dsc_step(md, tr('Blocked {0}', name), async () => { await api('DELETE', `/api/disc/blocks/${uid}`); if (r.unlinked) await api('POST', `/api/disc/connections/${uid}/restore`); },
          () => api('POST', `/api/disc/blocks/${uid}`), r.unlinked);
      } else if (k === 'unblock') {
        await api('DELETE', `/api/disc/blocks/${uid}`);
        dsc_step(md, tr('Unblocked {0}', name), () => api('POST', `/api/disc/blocks/${uid}`), () => api('DELETE', `/api/disc/blocks/${uid}`));
      }
      await dsc_load();
    } catch { /* api() showed the message */ } finally { b.disabled = false; }
    if (md.isConnected) dsc_draw(md);
  });
  setTimeout(() => $('#dsc-email', md)?.focus({preventScroll: true}), 0);
  return md;
}

// any [data-dsc-open] (Settings > Account, the share dialog) opens the dialog
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-dsc-open]'); if (!b) return;
  e.preventDefault(); dsc_open();
});

// the link of the confirmation mail (#dsc-confirm/<token>) and the push / News (#dsc), once the app has started
function dsc_hash() {
  const h = location.hash, m = h.match(/^#dsc-confirm\/([A-Za-z0-9_-]{20,100})$/);
  if (!m && h !== '#dsc') return;
  const run = async () => {
    history.replaceState(null, '', '/');
    if (m) {
      try { await api('POST', '/api/disc/confirm', {token: m[1]}); toast(tr('Your address is confirmed: people can find you by it now.')); } catch { /* shown */ }
    }
    dsc_open();
  };
  let n = 0;
  const wait = () => { if (S.booted && S.me) run(); else if (++n < 120) setTimeout(wait, 500); };
  wait();
}
window.addEventListener('hashchange', dsc_hash);
dsc_hash();
