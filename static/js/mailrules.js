// @ts-check
/* Kalmido web client: 2.581.0 (#4804) documents from the own mailbox -- the mail rules in the mailbox dialog (hubmailbox.js
   hmb_dialog, loaded with it). A rule: folder, sender, subject, has an attachment, age; attachments (and / or the mail itself)
   become documents in a folder with tags; afterwards the mail is marked read, flagged, moved or left (deleting only with its
   own switch). "Fetch documents now", the last run and its error. Server: kalmido/hub/mailrules.py.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const MBR = {ws: '', j: null};
const mbr_q = (el, sel) => /** @type {any} */ (el.querySelector(sel));
async function mbr_mount(el, ws) {
  if (!el) return;
  MBR.ws = ws;
  try { MBR.j = await rawFetch('GET', `/api/hubmail/mailbox/rules?ws=${encodeURIComponent(ws)}`); } catch { el.innerHTML = ''; return; }
  mbr_draw(el);
  if (el.dataset.mbrWired) return;
  el.dataset.mbrWired = '1';
  el.addEventListener('click', e => mbr_click(el, e));
  el.addEventListener('change', e => { const t = /** @type {any} */ (e.target); if (t.id === 'mbr-after') mbr_q(el, '.mbrmove').hidden = t.value !== 'move'; });
}
function mbr_afterText(r) {
  if (r.delete_mail) return tr('then delete it');
  return {seen: tr('then mark it read'), flag: tr('then flag it'), move: tr('then move it to {0}', r.after_folder), none: ''}[r.after] || '';
}
function mbr_ruleLine(r) {
  const cond = [r.folder ? tr('Folder') + ': ' + r.folder : '', r.from_has ? tr('Sender') + ': ' + r.from_has : '', r.subject_has ? tr('Subject') + ': ' + r.subject_has : '',
    r.need_att ? tr('with attachment') : '', trn('last {0} day', 'last {0} days', r.max_age)].filter(Boolean).join(' · ');
  const what = [r.take_files ? tr('attachments') : '', r.take_mail ? tr('the e-mail itself') : ''].filter(Boolean).join(' + ');
  return `<li class="mbrrule${r.active ? '' : ' muted'}" data-mbrid="${r.id}"><span class="mbrtxt"><b>${esc(r.name || tr('Rule'))}</b>
    <small class="muted">${esc(cond)}</small><small>${esc(tr('Documents: {0}', what))}${mbr_afterText(r) ? ' · ' + esc(mbr_afterText(r)) : ''}${r.active ? '' : ' · ' + esc(tr('paused'))}</small>${r.error_text ? `<small class="hmbbad" role="status">${ic('info', 's')} ${esc(r.error_text)}</small>` : ''}</span>
    <button type="button" class="btn sm" data-mbra="edit">${ic('edit', 's')}<span>${tr('Change')}</span></button>
    <button type="button" class="iconbtn" data-mbra="del" aria-label="${tr('Delete')}" title="${tr('Delete')}">${ic('trash', 's')}</button></li>`;
}
function mbr_statusHtml(st) {
  if (!st) return '';
  const last = st.polled_at ? tr('Documents last fetched {0}', fmtWhen(st.polled_at)) + (st.count ? ' · ' + trn('{0} document so far', '{0} documents so far', st.count) : '') : '';
  return `${st.error_text ? `<p class="hmbbad" role="status">${ic('info', 's')} ${esc(st.error_text)}</p>` : ''}${last ? `<p class="muted mbrlast">${esc(last)}</p>` : ''}`;
}
function mbr_draw(el) {
  const j = MBR.j || {rules: []};
  el.innerHTML = `<h4>${tr('Documents from this mailbox')}</h4>
    <p class="muted">${tr('Rules select e-mails of this mailbox whose attachments become documents of this workspace; each e-mail only once.')}</p>
    <ul class="mbrrules" role="list">${(j.rules || []).map(mbr_ruleLine).join('') || `<li class="muted">${tr('No rules yet')}</li>`}</ul>
    <div class="mbrstat">${mbr_statusHtml(j.status)}</div><div class="mbrform"></div><p class="mbr-err" role="alert"></p>
    <div class="row mbrbtns"><button type="button" class="btn" data-mbra="new">${ic('plus', 's')} ${tr('New rule')}</button>
    ${(j.rules || []).length ? `<button type="button" class="btn" data-mbra="fetch">${ic('sync', 's')} ${tr('Fetch documents now')}</button>` : ''}</div>`;
}
function mbr_formHtml(r) {
  const x = r || {active: true, need_att: true, take_files: true, take_mail: false, sender_from_mail: true, max_age: 30, after: 'seen', tags: [], folder: '', after_folder: ''};
  const st = MBR.j?.status || {};
  const inp = (id, label, val, extra = '') => `<div class="row"><label for="${id}">${label}</label><input id="${id}" value="${esc(val ?? '')}" autocomplete="off" ${extra}></div>`;
  const chk = (id, label, on) => `<div class="row"><label class="chk"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${label}</label></div>`;
  const folders = [`<option value="">${esc(tr('Documents (sorted as usual)'))}</option>`].concat((MBR.j?.folders || []).map(f => `<option value="${f.id}" ${x.target_id === f.id ? 'selected' : ''}>${esc(f.path)}</option>`));
  if (x.target_id && !(MBR.j?.folders || []).some(f => f.id === x.target_id)) folders.push(`<option value="${x.target_id}" selected>${esc(tr('(a folder I cannot see)'))}</option>`);
  return `<form class="mbredit" data-mbrid="${r ? r.id : ''}"><h4>${r ? tr('Change rule') : tr('New rule')}</h4>
    ${inp('mbr-name', tr('Name'), x.name, 'maxlength="80"')}
    <h5>${tr('Which e-mails')}</h5>
    ${inp('mbr-folder', tr('Folder'), x.folder, `placeholder="${esc(st.folder || 'INBOX')}" spellcheck="false" maxlength="200"`)}
    ${inp('mbr-from', tr('Sender contains'), x.from_has, 'spellcheck="false" maxlength="200" placeholder="invoice@example.com"')}
    ${inp('mbr-subj', tr('Subject contains'), x.subject_has, 'maxlength="200"')}
    ${chk('mbr-att', tr('Only e-mails with an attachment'), x.need_att)}
    ${inp('mbr-age', tr('Received in the last days'), x.max_age, 'type="number" min="1" max="365" inputmode="numeric"')}
    <h5>${tr('What becomes a document')}</h5>
    ${chk('mbr-files', tr('The attachments'), x.take_files)}
    ${chk('mbr-mail', tr('The e-mail itself (.eml)'), x.take_mail)}
    <div class="row"><label for="mbr-target">${tr('Folder of the documents')}</label><select id="mbr-target">${folders.join('')}</select></div>
    ${inp('mbr-tags', tr('Tags'), (x.tags || []).join(', '), `placeholder="${esc(tr('comma separated'))}" maxlength="400"`)}
    ${chk('mbr-sender', tr('Sender of the e-mail as the sender of the document'), x.sender_from_mail)}
    <h5>${tr('Afterwards')}</h5>
    <div class="row"><label for="mbr-after">${tr('The e-mail')}</label><select id="mbr-after">${[['seen', tr('Mark as read')], ['flag', tr('Flag')], ['move', tr('Move to a folder')], ['none', tr('Leave as it is')]]
      .map(([v, l]) => `<option value="${v}" ${x.after === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
    <div class="mbrmove" ${x.after === 'move' ? '' : 'hidden'}>${inp('mbr-dest', tr('Move to folder'), x.after_folder, 'spellcheck="false" maxlength="200"')}</div>
    ${chk('mbr-del', tr('Delete the e-mail from the mailbox afterwards'), x.delete_mail)}
    ${chk('mbr-on', tr('Rule is active'), x.active)}
    <div class="row"><span class="spacer"></span><button type="button" class="btn" data-mbra="cancel">${tr('Cancel')}</button>
    <button type="button" class="btn pri" data-mbra="save">${ic('check', 's')} ${tr('Save')}</button></div></form>`;
}
function mbr_body(f) {
  const v = id => String(mbr_q(f, '#' + id)?.value ?? '').trim(), on = id => !!mbr_q(f, '#' + id)?.checked;
  const age = +v('mbr-age');
  if (!Number.isInteger(age) || age < 1 || age > 365) return tr('Invalid value: {0}', tr('Received in the last days'));
  return {name: v('mbr-name'), folder: v('mbr-folder'), from_has: v('mbr-from'), subject_has: v('mbr-subj'), need_att: on('mbr-att'), max_age: age,
    take_files: on('mbr-files'), take_mail: on('mbr-mail'), target_id: +v('mbr-target') || null, tags: v('mbr-tags').split(',').map(t => t.trim()).filter(Boolean),
    sender_from_mail: on('mbr-sender'), after: v('mbr-after'), after_folder: v('mbr-dest'), delete_mail: on('mbr-del'), active: on('mbr-on')};
}
async function mbr_click(el, e) {
  const b = /** @type {any} */ (e.target).closest('[data-mbra]'); if (!b || b.disabled) return;
  const errEl = mbr_q(el, '.mbr-err'); errEl.textContent = '';
  const li = b.closest('[data-mbrid]'), id = li ? +li.dataset.mbrid || 0 : 0;
  const rule = (MBR.j?.rules || []).find(r => r.id === id);
  const a = b.dataset.mbra;
  if (a === 'new' || a === 'edit') { mbr_q(el, '.mbrform').innerHTML = mbr_formHtml(a === 'edit' ? rule : null); mbr_q(el, '#mbr-name')?.focus(); return; }
  if (a === 'cancel') { mbr_q(el, '.mbrform').innerHTML = ''; return; }
  if (a === 'del') {
    if (!rule || !await askConfirm(tr('Delete the rule?'), tr('The documents it made stay.'), {ok: tr('Delete'), danger: true})) return;
    try { await api('DELETE', `/api/hubmail/mailbox/rules/${id}`); } catch { return; }
    return mbr_mount(el, MBR.ws);
  }
  if (a === 'fetch') {
    try { await api('POST', '/api/hubmail/mailbox/rules/fetch', {ws: MBR.ws}); toast(tr('The documents are fetched now')); } catch { return; }
    setTimeout(() => { if (el.isConnected) mbr_mount(el, MBR.ws); }, 6000);
    return;
  }
  if (a !== 'save') return;
  const f = b.closest('form'), d = mbr_body(f);
  if (typeof d === 'string') { errEl.textContent = d; return; }
  if (d.delete_mail && !rule?.delete_mail && !await askConfirm(tr('Delete the e-mails?'), tr('Every e-mail this rule takes is deleted from the mailbox afterwards.'), {ok: tr('Delete'), danger: true})) return;
  const rid = +f.dataset.mbrid || 0;
  b.disabled = true;
  try {
    if (rid) await rawFetch('PUT', `/api/hubmail/mailbox/rules/${rid}`, {...d, expect_updated_at: rule?.updated_at});
    else await rawFetch('POST', '/api/hubmail/mailbox/rules', {...d, ws: MBR.ws});
  } catch (x) { errEl.textContent = x.message || tr('Error'); b.disabled = false; if (x.status === 409) mbr_mount(el, MBR.ws); return; }
  toast(tr('Saved'));
  mbr_mount(el, MBR.ws);
}
