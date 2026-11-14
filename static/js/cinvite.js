// @ts-check
/* Kalmido web client: inviting people without an account by a link or a QR code (2.1156.0, #4550). Loaded on demand
   (lazyload.js module "cinvite": the button in "Find people", the page /#cinv/<token>). The server is accounts/cinvite.py.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const CNV = {items: [], limits: {}, made: null};
const cnv_$ = (s, r) => /** @type {any} */ ((r || document).querySelector(s));  // typed loosely (inputs, dialogs as root)
const CNV_KEY = 'kalmido.cinv';  // the token of an opened link waits here over a sign-in (the login reloads the page)
const cnv_post = (path, b) => fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(b)})
  .then(async r => ({r, j: await r.json().catch(() => ({}))}));

// ------------------------------------------------------------------ the inviting person: make, show, take back
function cnv_html() {
  const m = CNV.made, l = CNV.limits || {};
  const made = !m ? '' : `<div class="cnv-made" role="status">
      <p class="shint">${esc(tr('Send this link to the person or let them scan the code. It works once and until {0}; it is shown only now.', fmtDayAbs(m.item.expires_at)))}</p>
      <div class="qrbox"><img src="${esc(m.qr)}" alt="${esc(tr('QR code'))}" width="240" height="240"></div>
      <div class="row"><input id="cnv-link" readonly value="${esc(m.link)}" aria-label="${esc(tr('Invitation link'))}">
        <button type="button" class="btn" data-cnv="copy">${ic('copy', 's')} ${tr('Copy')}</button>${navigator.share ? `<button type="button" class="btn" data-cnv="share">${ic('send', 's')} ${tr('Share')}</button>` : ''}</div></div>`;
  const items = CNV.items || [];
  return `<div class="lhdr"><h3>${ic('link', 's')} ${tr('Invite by link')}</h3><span class="spacer"></span><button class="iconbtn" data-cnv="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <p class="shint">${esc(tr('For someone without an account: whoever opens the link creates an account and is connected with you at once.'))}</p>
    <form class="row" data-cnv-form><input id="cnv-note" maxlength="80" autocomplete="off" placeholder="${esc(tr('For whom? (only you see this)'))}" aria-label="${esc(tr('For whom? (only you see this)'))}">
      <button type="submit" class="btn pri">${ic('plus', 's')} ${tr('Create link')}</button></form>
    ${/*html-ok*/ made}
    ${items.length ? `<h4 id="cnv-open-h">${tr('Open invitation links')}</h4><div class="members" aria-labelledby="cnv-open-h">${items.map(x => `<div class="mrow cnv-row">
      <span class="n">${esc(x.note || tr('Invitation link'))}</span><span class="muted dsc-st">${esc(tr('runs out {0}', fmtDayAbs(x.expires_at)))}</span>
      <button type="button" class="btn sm" data-cnv="withdraw" data-id="${esc(String(x.id))}">${tr('Withdraw')}</button></div>`).join('')}</div>` : ''}
    <div class="shint">${esc(tr('At most {0} open links, {1} new ones a day.', l.open || 20, l.day || 10))}</div>`;
}

async function cnv_load() {
  const j = await api('GET', '/api/disc/invites');
  CNV.items = j.items || []; CNV.limits = j.limits || {};
}

function cnv_draw(md) {
  const v = cnv_$('#cnv-note', md)?.value || '';
  cnv_$('.card', md).innerHTML = cnv_html();
  const i = cnv_$('#cnv-note', md); if (i) i.value = v;
}

async function cnv_open() {
  CNV.made = null;
  try { await cnv_load(); } catch { return; }
  const md = modal(cnv_html());
  md.classList.add('dscmodal', 'cnvmodal');
  md.addEventListener('submit', async e => {
    const t = /** @type {any} */ (e.target); if (!t.closest('[data-cnv-form]')) return;
    e.preventDefault();
    const btn = t.querySelector('button[type=submit]'); btn.disabled = true;
    try { CNV.made = await api('POST', '/api/disc/invites', {note: cnv_$('#cnv-note', md).value.trim()}); cnv_$('#cnv-note', md).value = ''; await cnv_load(); }
    catch { /* api() showed the message */ } finally { btn.disabled = false; }
    if (md.isConnected) cnv_draw(md);
  });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-cnv]'); if (!b || !md.contains(b)) return;
    const k = b.dataset.cnv, id = +b.dataset.id;
    if (k === 'close') { md.remove(); return; }
    if (k === 'copy') { const t = CNV.made?.link || ''; try { await navigator.clipboard.writeText(t); toast(tr('Copied')); } catch { cnv_$('#cnv-link', md)?.select(); } return; }
    if (k === 'share') { try { await navigator.share({url: CNV.made.link, title: tr('Invitation to {0}', APP_NAME)}); } catch { /* closed */ } return; }
    if (k === 'withdraw') {
      b.disabled = true;
      const name = (b.closest('.cnv-row')?.querySelector('.n')?.textContent || '').trim();
      try {
        await api('DELETE', `/api/disc/invites/${id}`);
        if (CNV.made?.item?.id === id) CNV.made = null;
        const again = async fn => { await fn(); await cnv_load(); if (md.isConnected) cnv_draw(md); return {}; };
        const h = histAdd({label: tr('Withdrew the invitation link {0}', name), undo: () => again(() => api('POST', `/api/disc/invites/${id}/restore`)),
          redo: () => again(() => api('DELETE', `/api/disc/invites/${id}`))});
        histToast(tr('Withdrew the invitation link {0}', name), h);
        await cnv_load();
      } catch { /* shown */ }
      if (md.isConnected) cnv_draw(md);
    }
  });
  setTimeout(() => cnv_$('#cnv-note', md)?.focus({preventScroll: true}), 0);
  return md;
}

// ------------------------------------------------------------------ the person who opens a link (/#cinv/<token>)
// main.js calls it first: true = this screen took over (nobody signed in); false = signed in, the app starts and asks after it
async function cnv_boot(tok) {
  const {r, j} = await cnv_post('/api/auth/cinv/check', {token: tok}).catch(() => ({r: null, j: {}}));
  if (r && r.ok && j.signed_in) { try { sessionStorage.setItem(CNV_KEY, tok); } catch { /* no storage */ } return false; }
  await i18nLoad(uiLang());
  const el = document.createElement('div');
  el.className = 'modal authscreen';
  lg_decor(el);
  const logo = `<div class="alogo">${/*html-ok*/ logoSvg(40)}<b>${/*html-ok*/ wordSvg()}</b></div>`;
  const card = h => { el.innerHTML = `<div class="card">${/*html-ok*/ logo}${/*html-ok*/ h}</div>`; };
  if (!r || !r.ok) {
    card(`<p role="alert">${esc(r ? j.error || httpErrText(r.status) : tr('Server not reachable.'))}</p><button class="btn pri" type="button" data-cnv="go">${tr('Continue')}</button>`);
  } else {
    card(`<h2 class="invh">${esc(tr('{0} invites you to {1}', j.name, APP_NAME))}</h2>
      <p class="muted">${esc(tr('Create your account: you are connected with {0} right away.', j.name))}</p>
      <form id="cnv-form" autocomplete="on">
        <label class="aulab" for="cnv-name">${tr('Your name')}</label><input id="cnv-name" maxlength="60" autocomplete="name" required>
        ${j.mail ? `<label class="aulab" for="cnv-mail">${tr('E-mail address')}</label><input id="cnv-mail" type="email" inputmode="email" autocomplete="email" autocapitalize="off" spellcheck="false" maxlength="200" required>` : `<label class="aulab" for="cnv-pw">${tr('Password')}</label><input id="cnv-pw" type="password" autocomplete="new-password" required minlength="${esc(String(j.min_password || 8))}" placeholder="${esc(tr('at least {0} characters', j.min_password || 8))}">
        <label class="aulab" for="cnv-pw2">${tr('Repeat the password')}</label><input id="cnv-pw2" type="password" autocomplete="new-password" required>`}
        <div class="aerr" role="alert" id="cnv-err"></div>
        <button class="btn pri" type="submit">${tr('Create account and connect')}</button>
        <p class="aulink">${tr('Already have an account?')} <button type="button" class="linkbtn" data-cnv="signin">${tr('Sign in')}</button></p>
      </form>`);
    cnv_$('#cnv-form', el).addEventListener('submit', async e => {
      e.preventDefault();
      const errEl = cnv_$('#cnv-err', el), pw = cnv_$('#cnv-pw', el)?.value || '';
      if (!j.mail && pw.length < (j.min_password || 8)) { errEl.textContent = tr('Password: at least {0} characters', j.min_password || 8); return; }
      if (!j.mail && pw !== cnv_$('#cnv-pw2', el).value) { errEl.textContent = tr('The two passwords are not the same'); return; }
      const sub = /** @type {any} */ (e.target).querySelector('button[type=submit]'); sub.disabled = true;
      const mail = j.mail ? cnv_$('#cnv-mail', el).value.trim() : '';  // Fable F1: without e-mail no address (nothing proves it)
      const res = await cnv_post('/api/auth/cinv/accept', {token: tok, name: cnv_$('#cnv-name', el).value.trim(), lang: I18N.code || 'en', ...(j.mail ? {email: mail} : {password: pw})}).catch(() => null);
      sub.disabled = false;
      if (!res) { errEl.textContent = tr('Server not reachable.'); return; }
      if (!res.r.ok) { errEl.textContent = res.j.error || httpErrText(res.r.status); return; }
      if (res.j.enrol) { await authEnrol(el, logo); return; }
      if (res.j.mail) { card(`<h2 class="invh">${tr('Thank you!')}</h2><p role="status">${esc(tr('Check your e-mail: open the link we sent to {0} to confirm your address and choose your password. Then you are connected with {1}.', mail, j.name))}</p>`); return; }
      card(`<h2 class="invh">${esc(tr('Welcome!'))}</h2><p role="status">${esc(tr('You are connected with {0}. Your username for signing in: {1}', j.name, res.j.username || ''))}</p><button class="btn pri" type="button" data-cnv="go">${tr('Continue')}</button>`);
    });
  }
  el.addEventListener('click', e => {
    const k = /** @type {any} */ (e.target).closest('[data-cnv]')?.dataset.cnv;
    if (k === 'go') location.replace('/');
    if (k === 'signin') { try { sessionStorage.setItem(CNV_KEY, tok); } catch { /* no storage */ } location.replace('/'); }
  });
  document.body.appendChild(el);
  cnv_$('#app')?.setAttribute('inert', '');
  setTimeout(() => cnv_$('#cnv-name', el)?.focus({preventScroll: true}), 50);
  return true;
}

// after the start of a signed-in app: a link opened here (or before the sign-in) asks "Connect with X?"
async function cnv_after() {
  let tok = '';
  try { tok = sessionStorage.getItem(CNV_KEY) || ''; sessionStorage.removeItem(CNV_KEY); } catch { return; }
  if (!tok) return;
  const {r, j} = await cnv_post('/api/auth/cinv/check', {token: tok}).catch(() => ({r: null, j: {}}));
  if (!r || !r.ok) { toast(r ? j.error || httpErrText(r.status) : tr('Server not reachable.')); return; }
  if (j.own) { toast(tr('This is your own invitation link. Send it to the person you want to invite.'), null, 8000); return; }
  if (!j.may) { toast(tr('Only people can accept an invitation')); return; }
  if (j.connected) { toast(tr('You are already connected with {0}.', j.name)); return; }
  if (!await askConfirm(tr('Connect with {0}?', j.name), tr('{0} invited you. Connected, you can share lists and write to each other.', j.name), {ok: tr('Connect')})) return;
  const res = await cnv_post('/api/auth/cinv/accept', {token: tok}).catch(() => null);
  if (!res || !res.r.ok) { toast(res ? res.j.error || httpErrText(res.r.status) : tr('Server not reachable.')); return; }
  await load(); render();
  toast(tr('Connected with {0}', j.name));
}
