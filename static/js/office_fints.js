// @ts-check
/* Kalmido web client: 2.616.0 (#2473) the direct bank fetch over FinTS of a bank account of the office (tab Bank, button "Fetch
   from bank"), loaded on its first use (lazyload.js module fints; its stand-in fnt_open loads it, LD_CALL). One dialog: the
   account, the login name at the bank, the PIN (asked every time, never stored: it goes to the server once and lives there
   only in the memory of the running bank connection), the FinTS server of the bank and the period -> maybe the TAN method ->
   maybe the approval in the banking app (polled) or a TAN typed in -> the preview of the statement import -> the import
   (the same way as a downloaded file: duplicates, bank rules, the take-back). Closing the dialog ends the bank connection.
   Server: kalmido/office/fints.py.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const FNT_POLL_MS = 2500;  // the approval in the banking app: one status question per 2.5 s (the server asks the bank at most every 2 s)

async function fnt_open() {
  let s;
  try { s = await api('GET', '/api/office/bank/fints'); } catch (x) { toast(x.message || tr('unknown')); return; }
  if (!s.on) { toast(s.message || tr('unknown')); return; }
  const md = /** @type {any} */ (modal('')), card = $('.card', md), st = {d: null, busy: false, acct: (s.accounts.find(a => a.ok) || {}).id};
  md.classList.add('ofcdlg', 'bnkdlg', 'fntdlg');
  const head = `<h3>${tr('Fetch from bank')}</h3>`;
  const errEl = () => $('.aerr', md), err = m => { const e = errEl(); if (e) e.textContent = m || ''; };
  const foot = (ok, back) => `<div class="aerr" role="alert"></div><div class="foot">${back ? `<button class="btn" data-fn="back">${tr('Back')}</button>` : ''}<span class="spacer"></span><button class="btn" data-fn="close">${tr('Cancel')}</button>${ok ? `<button class="btn pri" data-fn="next">${esc(ok)}</button>` : ''}</div>`;
  const acct = () => s.accounts.find(a => a.id === +st.acct) || {};
  // 2.616.0 (#2473, Fable finding 4): the remembered server address was set last by somebody else -> say so before the PIN goes there
  const srvNote = a => a.server_changed ? esc(tr('The server address was changed by {0} on {1}. Please check it before you enter your PIN.', a.server_changed.by || tr('unknown'), a.server_changed.at ? fmtDateLoc(a.server_changed.at.slice(0, 10)) : '')) : '';
  const form = () => {
    const a = acct();
    card.innerHTML = `${head}<p class="muted">${tr('Kalmido asks your bank for the bookings of the account (FinTS). Your PIN is asked every time and never stored.')}</p>
      <div class="row"><label for="fn-acct">${tr('Bank account')}</label><select id="fn-acct">${s.accounts.map(x => `<option value="${x.id}" ${x.id === a.id ? 'selected' : ''} ${x.ok ? '' : 'disabled'}>${esc(x.label)} · … ${esc(x.iban_tail)}${x.ok ? '' : ' – ' + esc(tr('only German accounts'))}</option>`).join('')}</select></div>
      <div class="row"><label for="fn-login">${tr('Sign-in name')}</label><input id="fn-login" maxlength="64" autocomplete="off" spellcheck="false" value="${esc(a.login || '')}"></div>
      <div class="row"><label for="fn-pin">${tr('PIN')}</label><input id="fn-pin" type="password" maxlength="64" autocomplete="off" spellcheck="false"></div>
      <div class="row"><label for="fn-server">${tr('FinTS server of the bank')}</label><input id="fn-server" type="url" maxlength="300" autocomplete="off" spellcheck="false" placeholder="https://" value="${esc(a.server || '')}"><small class="muted">${tr('The address your bank gives for FinTS / HBCI with PIN/TAN.')}</small><small class="fn-srvchg" role="note">${srvNote(a)}</small></div>
      <div class="row"><label for="fn-from">${tr('From')}</label><input id="fn-from" type="date" value="${esc(s.since)}"></div>
      <div class="row"><label for="fn-to">${tr('To')}</label><input id="fn-to" type="date" value="${esc(today())}"></div>
      <label class="chk"><input type="checkbox" id="fn-rem" checked> ${tr('Remember the sign-in name and the server for this account (never the PIN)')}</label>
      ${foot(tr('Connect'))}`;
    $(a.login ? '#fn-pin' : '#fn-login', md)?.focus();
  };
  const rowsHtml = p => `<p class="muted">${esc([trn('{0} new', '{0} new', p.count), p.dup_count ? trn('{0} already there', '{0} already there', p.dup_count) : '', p.pending_count ? trn('{0} pending', '{0} pending', p.pending_count) : '', p.skipped ? trn('{0} with an error', '{0} with an error', p.skipped) : ''].filter(Boolean).join(' · '))}</p>
    ${typeof cfb_prevHtml === 'function' ? cfb_prevHtml(p.balances) : ''}<ul class="ofclist bnkprev" role="list">${(p.rows || []).slice(0, 200).map(r => `<li class="ofcrow ${r.error || r.dup || r.pending ? 'arch' : ''}"><span class="ofcn"><b>${esc(r.counterpart || r.purpose || tr('Row {0}', r.n))}</b><small class="muted">${esc([r.day ? fmtDateLoc(r.day) : '', r.error || (r.pending ? tr('pending – not imported') : r.dup ? tr('already there') : r.purpose)].filter(Boolean).join(' · '))}</small></span>${r.amount != null ? `<span class="bnkamt ${+r.amount > 0 ? 'in' : 'out'}">${esc(bnkAmt(r.amount))}</span>` : ''}</li>`).join('')}</ul>
    ${(p.rows || []).length > 200 ? `<p class="muted">${tr('Showing the first 200 rows')}</p>` : ''}`;
  const view = () => {
    const d = st.d, sub = `<p class="muted">${esc(d.account.label)} · … ${esc(d.account.iban_tail)} · ${esc(fmtDateLoc(d.from))} – ${esc(fmtDateLoc(d.to))}</p>`;
    if (d.state === 'mechanism') {
      card.innerHTML = `${head}${sub}<p>${tr('Which TAN method do you use?')}</p><div class="fn-mech" role="radiogroup" aria-label="${esc(tr('TAN method'))}">${d.mechanisms.map((m, i) => `<label class="chk"><input type="radio" name="fn-mech" value="${esc(m.id)}" ${i ? '' : 'checked'}> ${esc(m.name)}</label>`).join('')}</div>${foot(tr('Next'))}`;
    } else if (d.state === 'decoupled') {
      card.innerHTML = `${head}${sub}<div class="fn-wait" role="status" aria-live="polite">${typeof botBusy === 'function' ? botBusy('') : ''}<p><b>${tr('Please approve in your banking app')}</b></p>${d.challenge ? `<p class="muted">${esc(d.challenge)}</p>` : ''}<p class="muted">${tr('Kalmido continues by itself once the bank has the approval.')}</p></div>${foot('')}`;
      poll();
    } else if (d.state === 'tan') {
      card.innerHTML = `${head}${sub}${d.challenge ? `<p>${esc(d.challenge)}</p>` : ''}${d.image ? `<p><img class="fn-tanimg" alt="${esc(tr('TAN code of the bank'))}" src="${esc(d.image)}"></p>` : ''}
        <div class="row"><label for="fn-tan">${tr('TAN')}</label><input id="fn-tan" maxlength="64" autocomplete="one-time-code" inputmode="numeric" spellcheck="false"></div>${foot(tr('Next'))}`;
      $('#fn-tan', md)?.focus();
    } else if (d.state === 'preview') {
      const p = d.preview;
      card.innerHTML = `${head}${sub}<p class="muted">${esc(tr('Import into: {0}', wsName(ofcWs())))}</p>${rowsHtml(p)}${foot(p.count ? trn('Import {0} booking', 'Import {0} bookings', p.count) : '')}`;
      if (!p.count) err(p.dup_count ? tr('Every booking of this period is there already.') : tr('The bank sent no bookings for this period.'));
    }
  };
  const gone = (x) => { st.d = null; form(); err(x.message || tr('unknown')); };  // the server ended the bank connection: start again
  const call = async (method, path, data) => {
    st.busy = true; $$('button[data-fn]', md).forEach(b => { b.disabled = true; });
    try { return await api(method, path, data); }
    finally { st.busy = false; $$('button[data-fn]', md).forEach(b => { b.disabled = false; }); }
  };
  const step = async (path, data) => {
    try { st.d = (await call('POST', `/api/office/bank/fints/${encodeURIComponent(st.d.id)}/${path}`, data)).dialog; view(); }
    catch (x) { gone(x); }
  };
  const poll = () => setTimeout(async () => {
    if (!md.isConnected) { end(); return; }
    if (st.d?.state !== 'decoupled') return;
    try { const d = (await api('POST', `/api/office/bank/fints/${encodeURIComponent(st.d.id)}/poll`, {})).dialog; if (!md.isConnected) { end(); return; } const was = st.d.state; st.d = d; if (d.state !== was) view(); else poll(); }
    catch (x) { if (md.isConnected) gone(x); }
  }, FNT_POLL_MS);
  const end = () => { const d = st.d; st.d = null; if (d) api('DELETE', `/api/office/bank/fints/${encodeURIComponent(d.id)}`).catch(() => 0); };
  const rm = md.remove; md.remove = () => { end(); rm(); };  // every way out (Cancel, the backdrop, Escape) ends the bank connection
  const close = () => md.remove();
  md.addEventListener('change', e => { const t = /** @type {any} */ (e.target); if (t.id === 'fn-acct') { st.acct = t.value; const a = acct(); $('#fn-login', md).value = a.login || ''; $('#fn-server', md).value = a.server || ''; const n = $('.fn-srvchg', md); if (n) n.innerHTML = srvNote(a); } });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && /** @type {any} */ (e.target).matches?.('input:not([type=checkbox]):not([type=radio])')) { e.preventDefault(); $('button[data-fn="next"]', md)?.click(); } });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button[data-fn]'); if (!b || st.busy) return;
    if (b.dataset.fn === 'close') { close(); return; }
    if (b.dataset.fn === 'back') { end(); form(); return; }
    err('');
    if (!st.d) {
      const pinEl = $('#fn-pin', md), req = {account_id: +$('#fn-acct', md).value, login: $('#fn-login', md).value.trim(), pin: pinEl.value,
        server: $('#fn-server', md).value.trim(), from: $('#fn-from', md).value || null, to: $('#fn-to', md).value || null, remember: $('#fn-rem', md).checked};
      if (!req.login || !req.pin || !req.server) { err(tr('Please fill in the sign-in name, the PIN and the server')); return; }
      pinEl.value = '';  // the PIN leaves the page with this one request
      try { st.d = (await call('POST', '/api/office/bank/fints/start', req)).dialog; req.pin = ''; view(); }
      catch (x) { req.pin = ''; err(x.message || tr('unknown')); }
      return;
    }
    const d = st.d;
    if (d.state === 'mechanism') { await step('mechanism', {id: $('input[name="fn-mech"]:checked', md)?.value}); return; }
    if (d.state === 'tan') { const t = $('#fn-tan', md); const tan = t.value.trim(); t.value = ''; if (!tan) { err(tr('Please enter the TAN')); return; } await step('tan', {tan}); return; }
    if (d.state === 'preview' && d.preview.count) {
      // the target before the import, in words (#1940, #2934): the office area + the account
      if (!await importTargetConfirm({what: trn('{0} booking', '{0} bookings', d.preview.count), ws: ofcWs(), place: d.account.label || tr('Bank account')})) return;
      try {
        const j = await call('POST', `/api/office/bank/fints/${encodeURIComponent(d.id)}/import`, {});
        st.d = null; md.remove(); toast(trn('{0} booking imported', '{0} bookings imported', j.count));
        BNK.state = 'open'; BNK.imports = null; bnkReload();
      } catch (x) { gone(x); }
    }
  });
  form();
}
