// @ts-check
// 2.153.0 (#2029, #2030): send a letter by e-mail (PDF attached) and the text blocks of the office area.
// Server: kalmido/office/lettermail.py. Pushes into LT_HOOKS (office_letters.js).
'use strict';
const LTM = {info: null, infoP: null, ta: null};

// the server's mail facts once per page (mail server on, where answers arrive)
function ltmInfo() {
  if (LTM.info) return Promise.resolve(LTM.info);
  if (!LTM.infoP) LTM.infoP = api('GET', '/api/office/letters/mail-info').then(j => (LTM.info = j)).catch(() => { LTM.infoP = null; return {mail_on: false}; });
  return LTM.infoP;
}
// "Send by e-mail" appears once the server confirmed a mail server (the slot fills itself)
function ltmFillSlots() {
  ltmInfo().then(j => document.querySelectorAll('[data-ltm-slot="mail"]').forEach(el => {
    el.outerHTML = j.mail_on ? `<button type="button" class="btn" data-ltm="mail" data-id="${esc(el.dataset.id)}">${ic('send', 's')} ${tr('Send by e-mail')}</button>` : '';
  }));
}
const ltmReload = () => { if (typeof ltReload === 'function') ltReload(); };

// the text field the block goes into: the letter text the person worked in last, else the editor's text field
document.addEventListener('focusin', e => { const t = /** @type {any} */ (e.target); if (t && t.tagName === 'TEXTAREA' && !t.closest('.modal')) LTM.ta = t; });
function ltmTarget() {
  if (LTM.ta && LTM.ta.isConnected) return LTM.ta;
  return document.getElementById('lt-body') || document.querySelector('#view textarea');
}
function ltmInsert(text) {
  const ta = ltmTarget(); if (!ta) return false;
  const a = ta.selectionStart ?? ta.value.length, z = ta.selectionEnd ?? a;
  ta.focus();
  ta.setRangeText(text, a, z, 'end');
  ta.dispatchEvent(new Event('input', {bubbles: true}));
  return true;
}

// ---- text blocks: pick (search, insert at the cursor) and manage (new, change, delete with undo, samples)
async function ltmBlocksModal(pick) {
  let j;
  try { j = await api('GET', '/api/office/letter-blocks'); } catch (x) { ofcErr(x); return; }
  let blocks = j.blocks || [];
  /** @type {any} */
  const md = modal(`<h3>${tr('Text blocks')}</h3>
    <div class="row"><input id="ltm-q" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off"></div>
    <ul class="ofclist ltm-blocks" role="list"></ul>
    <p class="muted ofchint">${esc(j.note || '')}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><button class="btn" data-m="starters">${tr('Use sample')}</button><button class="btn" data-m="new">${ic('plus', 's')} ${tr('New text block')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofcdlg', 'ltm-dlg');
  const close = fgModal(md);
  const draw = () => {
    const q = ($('#ltm-q', md).value || '').trim().toLowerCase();
    const xs = blocks.filter(b => !q || (b.name + ' ' + b.body).toLowerCase().includes(q));
    $('.ltm-blocks', md).innerHTML = xs.length ? xs.map(b => `<li><div class="ofcrow ltm-row">
        <button type="button" class="ltm-pick ofcn" data-m="${pick ? 'ins' : 'edit'}" data-id="${b.id}"><b>${esc(b.name)}</b><small class="muted">${esc((b.body || '').slice(0, 120))}</small></button>
        ${pick ? `<button type="button" class="btn sm" data-m="edit" data-id="${b.id}" aria-label="${esc(tr('Edit'))}" title="${esc(tr('Edit'))}">${ic('edit', 's')}</button>` : ''}</div></li>`).join('')
      : `<li class="muted">${esc(q ? tr('Nothing found') : tr('No text blocks yet. Add a sample or write your own.'))}</li>`;
  };
  const reload = async () => { try { blocks = (await api('GET', '/api/office/letter-blocks')).blocks || []; draw(); } catch (x) { /* the list stays */ } };
  draw();
  $('#ltm-q', md).addEventListener('input', draw);
  setTimeout(() => $('#ltm-q', md)?.focus(), 0);
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    const m = b.dataset.m, blk = blocks.find(x => x.id === +b.dataset.id);
    if (m === 'close') { close(); return; }
    if (m === 'ins' && blk) {
      md.remove();
      if (!ltmInsert(blk.body)) toast(tr('Click into the letter text first'));
      return;
    }
    if (m === 'edit' && blk) { ltmBlockEdit(blk, reload); return; }
    if (m === 'new') { ltmBlockEdit(null, reload); return; }
    if (m === 'starters') ltmStarters(reload);
  });
}
function ltmBlockEdit(t, after) {
  /** @type {any} */
  const md = modal(`<h3>${t ? tr('Edit text block') : tr('New text block')}</h3>
    ${ofcRowF('ltm-bname', tr('Name'), ofcIn('ltm-bname', t?.name, {max: 120}))}
    <label for="ltm-bbody" class="dtp-lab">${tr('Text')}</label><textarea id="ltm-bbody" class="dtp-ta" rows="10" maxlength="20000">${esc(t?.body || '')}</textarea>
    <div class="aerr" role="alert"></div>
    <div class="foot">${t ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${t ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg', 'ltm-dlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        await api('DELETE', `/api/office/letter-blocks/${t.id}`); md.remove(); after();
        toast(tr('Deleted'), async () => { await api('POST', `/api/office/letter-blocks/${t.id}/restore`); after(); });
        return;
      }
      const v = {name: $('#ltm-bname', md).value, body: $('#ltm-bbody', md).value};
      if (t) {
        // 2.560.0 C (#4700): with expect_updated_at (saved elsewhere meanwhile -> 409 and the bar); the undo writes back only
        // the changed keys, with the version this save left
        const old = {name: t.name, body: t.body};
        const sv = await ofcSave(md, `/api/office/letter-blocks/${t.id}`, t, v); md.remove(); after();  // 2.576.0 (#4794): only the changed fields (objsave.js)
        if (!sv) return;
        const back = Object.fromEntries(Object.entries(old).filter(([k, x]) => String(x ?? '') !== String(sv?.[k] ?? '')));
        if (Object.keys(back).length) toast(tr('Saved'), async () => { try { await rawFetch('PATCH', `/api/office/letter-blocks/${t.id}`, sv?.updated_at ? {...back, expect_updated_at: sv.updated_at} : back); } catch (x) { toast(x.status === 409 ? tr('Changed in the meantime') : ofcErrTxt(x)); } after(); });
        else toast(tr('Saved'));
      } else {
        const j = await api('POST', '/api/office/letter-blocks', v); md.remove(); after();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/letter-blocks/${j.id}`); after(); });
      }
    } catch (x) {
      const el = $('.aerr', md); if (!el) return;
      if (typeof objConflict === 'function' && await objConflict(md, x, r => { const m2 = ltmBlockEdit(r, after); after(); return m2; })) return;  // 2.576.0 (#4794): the merge bar
      el.textContent = ofcErrHere(x);
    }
  });
}
async function ltmStarters(after) {
  let j;
  try { j = await api('GET', '/api/office/letter-blocks/starters'); } catch (x) { ofcErr(x); return; }
  /** @type {any} */
  const md = modal(`<h3>${tr('Use sample')}</h3><p class="muted">${esc(j.note || '')}</p>
    ${ofcRowF('ltm-slang', tr('Language'), ofcSel('ltm-slang', j.lang, (S.languages || []).map(L => [L.code, L.name])))}
    <ul class="ofclist ltm-starters" role="list">${j.starters.map(s => `<li><div class="ofcrow"><span class="ofcn"><b>${esc(s.name)}</b></span><button type="button" class="btn sm pri" data-m="take" data-k="${esc(s.key)}">${tr('Add')}</button></div></li>`).join('')}</ul>
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      const t = await api('POST', '/api/office/letter-blocks', {starter: b.dataset.k, lang: $('#ltm-slang', md).value});
      md.remove(); after();
      toast(tr('Text block “{0}” added', t.name), async () => { await api('DELETE', `/api/office/letter-blocks/${t.id}`); after(); });
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = ofcErrHere(x); }
  });
}

// ---- 2.439.0 (#3617): the person's own part of the office's mails. The editor (signature, logo, sender name, answer address,
// way out) and what both send dialogs show: the signature to leave off for this mail, the answer address, one sentence on the sender
const ofmProfile = async () => { try { return await api('GET', '/api/office/mail-profile'); } catch { return null; } };
const ofmSigBox = t => t ? `<pre class="ofm-sig">${esc(t)}</pre>` : `<p class="muted ofchint">${tr('No signature')}</p>`;
/** the rows of a send dialog; rt: show the answer address (a letter with its own address has none to choose) */
function ofmSendHtml(p, rt, dis) {
  if (!p) return '';
  const d = dis ? 'disabled' : '';
  return `${rt ? ofcRowF('ofm-reply', tr('Answers to'), `<input id="ofm-reply" type="email" inputmode="email" autocomplete="off" maxlength="254" value="${esc(p.reply_to || p.default_reply_to || '')}" ${d}>`) : ''}
    <div class="ofm-send"><div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofm-on" ${p.signature ? 'checked' : 'disabled'} ${d}> ${tr('Attach signature')}</label><button type="button" class="linkbtn" data-ofmsig="edit">${tr('Edit')}</button></div>
    <div class="ofm-box">${ofmSigBox(p.signature)}</div></div>
    <p class="muted ofchint">${esc(p.note || '')}</p>`;
}
function ofmSendBody(md) {
  const on = $('#ofm-on', md), rt = $('#ofm-reply', md);
  return {...(on ? {signature: on.checked} : {}), ...(rt ? {reply_to: rt.value.trim()} : {})};
}
async function ofmSigModal(done) {
  const p = await ofmProfile(); if (!p) { toast(tr('Only available online.')); return; }
  const ways = {server: tr('Server address'), workspace: tr('Mailbox of the workspace'), private: tr('My own mailbox')};
  /** @type {any} */
  const md = modal(`<h3>${tr('E-mail signature')}</h3>
    <p class="muted ofchint">${esc(tr('Goes under your quotations, invoices, reminders and letters by e-mail. The signature picture of letters stays apart.'))}</p>
    <label for="ofm-text" class="dtp-lab">${tr('Signature|e-mail')}</label><textarea id="ofm-text" class="dtp-ta" rows="6" maxlength="1000">${esc(p.signature)}</textarea>
    <div class="row"><button type="button" class="linkbtn" data-m="prefill">${tr('Fill from name and company data')}</button></div>
    ${p.has_logo ? ofcChk('ofm-logo', tr('Show logo'), p.logo) : ''}
    <div class="ofm-prev" aria-label="${esc(tr('Preview'))}"><img id="ofm-prevlogo" src="${esc(p.logo_data || '')}" alt="" height="48"><pre class="ofm-sig" id="ofm-prevtext"></pre></div>
    ${ofcRowF('ofm-name', tr('Sender name'), `<input id="ofm-name" maxlength="120" autocomplete="off" value="${esc(p.from_name)}" placeholder="${esc(p.default_from_name)}">`)}
    ${ofcRowF('ofm-rt', tr('Answers to'), `<input id="ofm-rt" type="email" inputmode="email" autocomplete="off" maxlength="254" value="${esc(p.reply_to)}" placeholder="${esc(p.default_reply_to)}">`)}
    ${p.ways.length > 1 ? ofcRowF('ofm-via', tr('Send through'), ofcSel('ofm-via', p.via, p.ways.map(w => [w.key, w.address ? `${ways[w.key]} (${w.address})` : ways[w.key]]))) : ''}
    <p class="muted ofchint">${esc(p.note)}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('ofcdlg', 'ofm-dlg');
  const close = fgModal(md), ta = $('#ofm-text', md);
  let reset = false;
  const paint = () => { $('#ofm-prevtext', md).textContent = ta.value; const l = $('#ofm-prevlogo', md); l.hidden = !(p.has_logo && $('#ofm-logo', md)?.checked); };
  paint();
  md.addEventListener('input', e => { if (/** @type {any} */ (e.target).id === 'ofm-text') reset = false; paint(); });
  md.addEventListener('change', paint);
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    if (b.dataset.m === 'prefill') { ta.value = p.default_signature; reset = true; paint(); return; }
    b.disabled = true;
    try {
      const j = await api('PUT', '/api/office/mail-profile', {signature: reset ? null : ta.value, from_name: $('#ofm-name', md).value, reply_to: $('#ofm-rt', md).value.trim(),
        ...($('#ofm-logo', md) ? {logo: $('#ofm-logo', md).checked} : {}), ...($('#ofm-via', md) ? {via: $('#ofm-via', md).value} : {})});
      md.remove(); toast(tr('Saved')); done?.(j);
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = ofcErrHere(x); }
  });
}

// ---- send by e-mail: to, cc, subject, the covering text; where answers arrive
async function ltmMailModal(id) {
  let j, info;
  const prof = await ofmProfile();
  // 2.595.0 (#4906): an e-mail address typed a moment ago is still in LT.pend (saved 1.5 s after the last key): save it first
  if (typeof LT !== 'undefined' && LT.pend && LT.pend.d.id === id) await ltSave(LT.pend.d, true);
  try { [j, info] = await Promise.all([api('GET', `/api/office/letters/${id}/mail-draft`), ltmInfo()]); } catch (x) { ofcErr(x); return; }
  if (!j.to) j.to = ($('#lt-rcpt_email')?.value || '').trim();  // 2.595.0 (#4906): the form's E-mail field, when the server has none yet
  const hint = j.reply_address ? tr('Answers go to {0} and are linked to this letter automatically.', j.reply_address)
    : tr('There is no document address for this office: answers go to the company e-mail and are assigned to the letter by hand.');
  /** @type {any} */
  const md = modal(`<h3>${tr('Send by e-mail')}</h3>
    ${ofcRowF('ltm-to', tr('Recipient'), `<input id="ltm-to" type="email" inputmode="email" autocomplete="off" maxlength="254" value="${esc(j.to)}">`)}
    ${ofcRowF('ltm-cc', 'Cc', `<input id="ltm-cc" type="email" inputmode="email" autocomplete="off" maxlength="254">`)}
    ${ofcRowF('ltm-subj', tr('Subject'), ofcIn('ltm-subj', j.subject, {max: 200}))}
    <label for="ltm-text" class="dtp-lab">${tr('Message')}</label><textarea id="ltm-text" class="dtp-ta" rows="7" maxlength="5000">${esc(j.text)}</textarea>
    <p class="muted ofchint">${ic('clip', 's')} ${esc(j.filename)}</p>
    ${ofmSendHtml(prof, !j.reply_address)}
    <p class="muted ofchint">${esc(hint)}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="send">${ic('send', 's')} ${tr('Send')}</button></div>`);
  md.classList.add('ofcdlg', 'ltm-dlg');
  const close = fgModal(md);
  if (info && info.mail_on === false) $('.aerr', md).textContent = ofcNoMail();  // 2.802.0 (#5451)
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    b.disabled = true;
    try {
      await api('POST', `/api/office/letters/${id}/send-mail`, {to: $('#ltm-to', md).value.trim(), cc: $('#ltm-cc', md).value.trim(),
        subject: $('#ltm-subj', md).value, text: $('#ltm-text', md).value, ...ofmSendBody(md)});
      md.remove(); toast(tr('Sent')); ltmReload();
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = ofcErrHere(x); }
  });
}

document.addEventListener('click', e => {
  const o = /** @type {any} */ (e.target).closest?.('[data-ofmsig]');  // 2.500.0 (#4058): its own attribute, data-ofm is the office's navigation (areas.js, office_tree.js)
  if (o) {  // 2.439.0 (#3617): from a send dialog: back in it with the new signature
    const send = o.closest('.ofm-send');
    ofmSigModal(j => { if (!send?.isConnected) return; $('.ofm-box', send).innerHTML = ofmSigBox(j.signature); const on = $('#ofm-on', send); on.disabled = !j.signature; on.checked = !!j.signature; });
    return;
  }
  const b = /** @type {any} */ (e.target).closest?.('[data-ltm]'); if (!b) return;
  e.preventDefault();
  if (b.dataset.ltm === 'blocks') ltmBlocksModal(true);
  else if (b.dataset.ltm === 'manage') ltmBlocksModal(false);
  else if (b.dataset.ltm === 'mail') ltmMailModal(+b.dataset.id);
  else if (b.dataset.ltm === 'sig') ofmSigModal();
});

// a draft: the text block button above the text, "Send by e-mail" with the letter's buttons; no letter open: manage
LT_HOOKS.tools.push(d => (d && d.status === 'draft') ? `<button type="button" class="btn sm" data-ltm="blocks">${ic('note', 's')} ${tr('Insert text block')}</button>` : '');
LT_HOOKS.actions.push(d => {
  if (!d || d.status !== 'draft') return '';
  setTimeout(ltmFillSlots, 0);
  return `<span data-ltm-slot="mail" data-id="${d.id}"></span>`;
});
LT_HOOKS.sections.push(d => d ? '' : `<div class="ltm-manage"><button type="button" class="btn" data-ltm="manage">${ic('note', 's')} ${tr('Text blocks')}</button></div>`);
