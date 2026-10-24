// 2.73.0 A (#661): several Kalmido servers in one app -- Settings > Account > Servers. The accounts of this person on other
// Kalmido servers (work + home); this server talks to them (kalmido/accounts/servers.py), the browser never sees a token.
// For the combined views (msvview.js): msvLinks() / msvSelf() (buffered) and the event 'msv:changed' after every change.
const MSV = {p: null};
function msvFetch(force) {
  if (force || !MSV.p) MSV.p = rawFetch('GET', '/api/servers').catch(e => { MSV.p = null; throw e; });
  return MSV.p;
}
const msvLinks = force => msvFetch(force).then(j => j.links || []);
const msvSelf = force => msvFetch(force).then(j => j.self || {});
function msvChanged() { MSV.p = null; document.dispatchEvent(new CustomEvent('msv:changed')); }
const msvInk = c => /^#[0-9a-f]{6}$/i.test(c || '') && ac_darkInk(c);  // light colours carry dark letters (like the account colours)
const msvBadge = (short, color) => `<span class="msvb${msvInk(color) ? ' dk' : ''}" style="--msvc:${esc(color || '#6e56cf')}" aria-hidden="true">${esc(short || '?')}</span>`;
const msvHost = u => { try { return new URL(u).host; } catch { return u || ''; } };
async function msvReq(method, url, body) {
  try { return await rawFetch(method, url, body); }
  catch (e) { throw new Error(e instanceof Offline ? tr('Offline: only works again with a connection') : e.message); }
}
const msvHtml = () => `<h4 id="s-msv-h">${tr('Servers')}</h4>
  <div class="shint keep">${tr('Show accounts on other Kalmido servers here too (e.g. work and home). The data stays there.')}</div>
  <div class="members" id="s-msv"><div class="muted mhint">${tr('Loading…')}</div></div>
  <div class="row msvbtns"><button class="btn sm pri" data-msva="add">${ic('plus', 's')} ${tr('Add server')}</button><button class="btn sm" data-msva="code">${ic('key', 's')} ${tr('Create a connection code for another server')}</button></div>`;
async function msvDraw(md) {
  // the section stands in Settings > Account above "Advanced · for developers"
  let box = $('#s-msv', md);
  if (!box) {
    const anchor = $('#s-account-h', md)?.parentElement?.querySelector(':scope > details.sdev'); if (!anchor) return;
    const sec = document.createElement('div'); sec.className = 'msvsec'; sec.innerHTML = msvHtml();
    anchor.before(sec); box = $('#s-msv', md);
  }
  msvWire(md);
  let j; try { j = await msvFetch(true); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  const me = j.self || {}, links = j.links || [];
  const selfRow = `<div class="mrow msvrow" data-msvid="self">${msvBadge(me.short, me.color)}<span class="n"><b>${esc(me.name || '')}</b><small class="muted">${tr('The server this app runs on')}${links.some(l => l.default_inbox) ? '' : ' · ' + tr('Quick add lands here')}</small></span><button class="iconbtn" data-msva="edit" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit {0}', me.name || ''))}">${ic('edit', 's')}</button></div>`;
  box.innerHTML = selfRow + links.map(l => `<div class="mrow msvrow ${l.ok ? '' : 'off'}" data-msvid="${l.id}">${msvBadge(l.short, l.color)}<span class="n"><b>${esc(l.name)}</b><small class="muted">${esc(msvHost(l.base_url))}${l.remote_me?.name ? ' · ' + esc(l.remote_me.name) : ''}${l.default_inbox ? ' · ' + tr('Quick add lands here') : ''}</small><small class="msvst ${l.ok ? 'ok' : 'bad'}">${l.ok ? tr('Connected') : esc(l.err_text || tr('Not reachable'))}</small></span><button class="iconbtn" data-msva="edit" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit {0}', l.name))}">${ic('edit', 's')}</button><button class="iconbtn danger" data-msva="del" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove {0}', l.name))}">${ic('trash', 's')}</button></div>`).join('')
    + (links.length ? '' : `<div class="muted mhint">${tr('No other server connected yet.')}</div>`);
}
const msvColHtml = cur => `<div class="pfcol msvcol" role="group" aria-labelledby="msv-col-h">${AC_COLORS.map((c, i) => `<button type="button" data-msvcol="${c}" style="--acol:${c}" title="${esc(tr(AC_NAMES[i]))}" aria-label="${esc(tr(AC_NAMES[i]))}" aria-pressed="${cur === c}"></button>`).join('')}</div>`;
function msvColWire(md) {
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-msvcol]'); if (!b) return;
    $$('[data-msvcol]', md).forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    const bd = $('.msvprev', md); if (bd) { bd.style.setProperty('--msvc', b.dataset.msvcol); bd.classList.toggle('dk', msvInk(b.dataset.msvcol)); }
  });
}
const msvColVal = md => $('[data-msvcol][aria-pressed="true"]', md)?.dataset.msvcol;
function msvWire(md) {
  if (md._msvWired) return;
  md._msvWired = true;
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-msva]'); if (!b || !md.contains(b)) return;
    const box = $('#s-msv', md), j = box?._j || {}, a = b.dataset.msva;
    if (a === 'add') { msvAddModal(md); return; }
    if (a === 'code') { msvCodeModal(); return; }
    const rid = b.closest('[data-msvid]')?.dataset.msvid; if (!rid) return;
    if (rid === 'self') { if (a === 'edit') msvEditModal(md, null, j.self || {}); return; }
    const l = (j.links || []).find(x => x.id === +rid); if (!l) return;
    if (a === 'edit') { msvEditModal(md, l); return; }
    if (a === 'del') {
      if (!await askConfirm(tr('Remove the server {0}?', l.name), tr('Its tasks no longer show here. Nothing is deleted on the other server. The token stays valid there: revoke it there under Settings > Account > API tokens.'), {ok: tr('Remove'), danger: true})) return;
      const del = async () => { await msvReq('DELETE', `/api/servers/${l.id}`); msvChanged(); msvDraw(md); return {}; };
      const back = async () => { await msvReq('POST', `/api/servers/${l.id}/restore`); msvChanged(); msvDraw(md); return {}; };
      try { await del(); } catch (x) { toast(x.message); return; }
      const label = tr('Removed server {0}', l.name);
      histToast(label, histAdd({label, sett: true, undo: back, redo: del}));
    }
  });
}
function msvAddModal(smd) {
  const md = modal(`<h3>${tr('Add server')}</h3>
    <div class="shint keep">${tr('On the other server: Settings > Account > Servers > “Create a connection code for another server”. Paste the code here.')}</div>
    <div class="row"><label for="msv-code">${tr('Connection code')}</label><textarea id="msv-code" rows="3" spellcheck="false" autocomplete="off" placeholder="kalmido-link:…"></textarea></div>
    <details class="msvman"><summary>${tr('Address and token instead')}</summary>
      <div class="row"><label for="msv-url">${tr('Address')}</label><input id="msv-url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://kalmido.example.com"></div>
      <div class="row"><label for="msv-tok">${tr('API token')}</label><input id="msv-tok" type="password" autocomplete="off" spellcheck="false" placeholder="abk_…"></div>
      <div class="shint">${tr('A personal API token of your account there (Settings > Access) with the permissions: read, change tasks, delete, calendar, comments.')}</div>
    </details>
    <div class="row"><label for="msv-name">${tr('Name')}</label><input id="msv-name" maxlength="60" placeholder="${esc(tr('e.g. Work'))}"></div>
    <div class="calerr" role="alert" id="msv-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Connect')}</button></div>`);
  md.classList.add('msvmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const er = $('#msv-err', md), code = $('#msv-code', md).value.trim(), url = $('#msv-url', md).value.trim(), tok = $('#msv-tok', md).value.trim();
    const name = $('#msv-name', md).value.trim();
    if (!code && !(url && tok)) { er.textContent = tr('Paste a connection code, or enter address and token.'); er.hidden = false; return; }
    b.disabled = true; er.hidden = true;
    try {
      const l = await msvReq('POST', '/api/servers', {...(code ? {code} : {base_url: url, token: tok}), ...(name ? {name} : {})});
      md.remove(); msvChanged(); msvDraw(smd);
      toast(l.missing_scopes?.length ? tr('Connected with {0}. The token lacks: {1}', l.name, l.missing_scopes.join(', ')) : tr('Connected with {0}', l.name));
    } catch (x) { er.textContent = x.message; er.hidden = false; b.disabled = false; }
  });
  setTimeout(() => $('#msv-code', md)?.focus(), 30);
}
function msvEditModal(smd, l, me) {
  const cur = l || me, self = !l;
  const md = modal(`<h3>${self ? tr('This server') : tr('Edit server')}</h3>
    <div class="row msvhead">${msvBadge(cur.short, cur.color).replace('class="msvb', 'class="msvprev msvb')}<span class="muted">${self ? tr('How this server is labelled next to the other servers') : esc(cur.base_url)}</span></div>
    <div class="row"><label for="msv-en">${tr('Name')}</label><input id="msv-en" maxlength="60" value="${esc(cur.name || '')}"></div>
    <div class="row"><label for="msv-es">${tr('Short name')}</label><input id="msv-es" class="msvshort" maxlength="3" autocapitalize="characters" autocomplete="off" value="${esc(cur.short || '')}"><small class="muted">${tr('1 to 3 letters or digits, shown on every project and task of this server')}</small></div>
    <div class="row"><label id="msv-col-h">${tr('Colour')}</label>${msvColHtml(cur.color)}</div>
    ${self ? '' : `<label class="chkl wide"><input type="checkbox" id="msv-ei" ${l.default_inbox ? 'checked' : ''}><span>${tr('Quick add lands here by default')}</span></label>
    <details class="msvman"><summary>${tr('Replace the token')}</summary><div class="row"><label for="msv-et">${tr('API token')}</label><input id="msv-et" type="password" autocomplete="off" spellcheck="false" placeholder="abk_…"></div><div class="shint">${tr('A new token of the same account on that server, for example after the old one expired.')}</div></details>`}
    <div class="calerr" role="alert" id="msv-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Save')}</button></div>`);
  md.classList.add('msvmodal');
  msvColWire(md);
  $('#msv-es', md).addEventListener('input', e => { const v = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 3); if (v !== e.target.value) e.target.value = v; const p = $('.msvprev', md); if (p) p.textContent = v || '?'; });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const er = $('#msv-err', md), to = {name: $('#msv-en', md).value.trim(), short: $('#msv-es', md).value.trim(), color: msvColVal(md) || cur.color};
    if (!self) { to.default_inbox = $('#msv-ei', md).checked; const t = $('#msv-et', md).value.trim(); if (t) to.token = t; }
    const from = {name: cur.name, short: cur.short, color: cur.color, ...(self ? {} : {default_inbox: !!l.default_inbox})};
    const url = self ? '/api/servers/self' : `/api/servers/${l.id}`;
    const put = v => async () => { await msvReq('PATCH', url, v); msvChanged(); msvDraw(smd); return {}; };
    b.disabled = true; er.hidden = true;
    try { await put(to)(); } catch (x) { er.textContent = x.message; er.hidden = false; b.disabled = false; return; }
    md.remove();
    const redo = {...to}; delete redo.token;  // a replaced token is not undone (the old one may be revoked)
    const label = tr('Changed server {0}', to.name || cur.name);
    histToast(label, histAdd({label, sett: true, undo: put(from), redo: put(redo)}));
  });
}
function msvCodeModal() {
  const md = modal(`<h3>${tr('Connection code')}</h3>
    <div class="shint keep">${tr('Creates a personal API token for your account on this server, with just what the other app needs. You can revoke it any time under Settings > Account > API tokens.')}</div>
    <div class="row"><label for="msv-cn">${tr('For')}</label><input id="msv-cn" maxlength="40" placeholder="${esc(tr('e.g. Home server'))}"></div>
    <div class="msvout" hidden><textarea id="msv-cv" rows="4" readonly spellcheck="false"></textarea>
      <div class="shint keep">${tr('On the other device or server, paste it under Settings > Account > Servers. The code is shown only this once.')}</div></div>
    <div class="calerr" role="alert" id="msv-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button><button class="btn" data-m="copy" hidden>${ic('copy', 's')} ${tr('Copy')}</button><button class="btn pri" data-m="ok">${tr('Create')}</button></div>`);
  md.classList.add('msvmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'copy') { copyText($('#msv-cv', md).value); return; }
    const er = $('#msv-err', md); b.disabled = true; er.hidden = true;
    try {
      const j = await msvReq('POST', '/api/servers/code', {name: $('#msv-cn', md).value.trim()});
      $('#msv-cv', md).value = j.code; $('.msvout', md).hidden = false; b.hidden = true; $('[data-m="copy"]', md).hidden = false;
      $('#msv-cn', md).disabled = true; $('#msv-cv', md).select();
    } catch (x) { er.textContent = x.message; er.hidden = false; b.disabled = false; }
  });
}
