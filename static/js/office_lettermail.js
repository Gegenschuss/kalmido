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
  try { j = await api('GET', '/api/office/letter-blocks'); } catch (x) { toast(x.message || ''); return; }
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
      : `<li class="muted">${esc(q ? tr('Nothing found') : tr('No text blocks yet. Take over a sample or write your own.'))}</li>`;
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
        const old = {name: t.name, body: t.body};
        await api('PATCH', `/api/office/letter-blocks/${t.id}`, v); md.remove(); after();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/letter-blocks/${t.id}`, old); after(); });
      } else {
        const j = await api('POST', '/api/office/letter-blocks', v); md.remove(); after();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/letter-blocks/${j.id}`); after(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
async function ltmStarters(after) {
  let j;
  try { j = await api('GET', '/api/office/letter-blocks/starters'); } catch (x) { toast(x.message || ''); return; }
  /** @type {any} */
  const md = modal(`<h3>${tr('Use sample')}</h3><p class="muted">${esc(j.note || '')}</p>
    ${ofcRowF('ltm-slang', tr('Language'), ofcSel('ltm-slang', j.lang, (S.languages || []).map(L => [L.code, L.name])))}
    <ul class="ofclist ltm-starters" role="list">${j.starters.map(s => `<li><div class="ofcrow"><span class="ofcn"><b>${esc(s.name)}</b></span><button type="button" class="btn sm pri" data-m="take" data-k="${esc(s.key)}">${tr('Take over')}</button></div></li>`).join('')}</ul>
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
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}

// ---- send by e-mail: to, cc, subject, the covering text; where answers arrive
async function ltmMailModal(id) {
  let j, info;
  try { [j, info] = await Promise.all([api('GET', `/api/office/letters/${id}/mail-draft`), ltmInfo()]); } catch (x) { toast(x.message || ''); return; }
  const hint = j.reply_address ? tr('Answers go to {0} and are linked to this letter automatically.', j.reply_address)
    : tr('There is no document address for this office: answers go to the company e-mail and are assigned to the letter by hand.');
  /** @type {any} */
  const md = modal(`<h3>${tr('Send by e-mail')}</h3>
    ${ofcRowF('ltm-to', tr('Recipient'), `<input id="ltm-to" type="email" inputmode="email" autocomplete="off" maxlength="254" value="${esc(j.to)}">`)}
    ${ofcRowF('ltm-cc', 'Cc', `<input id="ltm-cc" type="email" inputmode="email" autocomplete="off" maxlength="254">`)}
    ${ofcRowF('ltm-subj', tr('Subject'), ofcIn('ltm-subj', j.subject, {max: 200}))}
    <label for="ltm-text" class="dtp-lab">${tr('Message')}</label><textarea id="ltm-text" class="dtp-ta" rows="7" maxlength="5000">${esc(j.text)}</textarea>
    <p class="muted ofchint">${ic('clip', 's')} ${esc(j.filename)}</p>
    <p class="muted ofchint">${esc(hint)}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="send">${ic('send', 's')} ${tr('Send')}</button></div>`);
  md.classList.add('ofcdlg', 'ltm-dlg');
  const close = fgModal(md);
  if (info && info.mail_on === false) $('.aerr', md).textContent = tr('Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)');
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    b.disabled = true;
    try {
      await api('POST', `/api/office/letters/${id}/send-mail`, {to: $('#ltm-to', md).value.trim(), cc: $('#ltm-cc', md).value.trim(),
        subject: $('#ltm-subj', md).value, text: $('#ltm-text', md).value});
      md.remove(); toast(tr('Sent')); ltmReload();
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}

document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-ltm]'); if (!b) return;
  e.preventDefault();
  if (b.dataset.ltm === 'blocks') ltmBlocksModal(true);
  else if (b.dataset.ltm === 'manage') ltmBlocksModal(false);
  else if (b.dataset.ltm === 'mail') ltmMailModal(+b.dataset.id);
});

// a draft: the text block button above the text, "Send by e-mail" with the letter's buttons; no letter open: manage
LT_HOOKS.tools.push(d => (d && d.status === 'draft') ? `<button type="button" class="btn sm" data-ltm="blocks">${ic('note', 's')} ${tr('Insert text block')}</button>` : '');
LT_HOOKS.actions.push(d => {
  if (!d || d.status !== 'draft') return '';
  setTimeout(ltmFillSlots, 0);
  return `<span data-ltm-slot="mail" data-id="${d.id}"></span>`;
});
LT_HOOKS.sections.push(d => d ? '' : `<div class="ltm-manage"><button type="button" class="btn" data-ltm="manage">${ic('note', 's')} ${tr('Text blocks')}</button></div>`);
