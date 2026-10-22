'use strict';
// 2.50.0 (#1200): approval links with a simple electronic signature - on a sent quotation (office) and in the list dialog >
// Public link (acceptance of the project / a section / a milestone). The customer decides on a server page without the app;
// here: create, copy, stop, and the protocol (who, when, address, device).
const sg_note = () => tr('Simple electronic signature: usually enough to accept a quotation or confirm an acceptance; not for contracts that the law requires in written form (they need a qualified signature). This is not legal advice.');
const sg_stTxt = s => ({open: tr('Waiting for the customer'), accepted: tr('Accepted|document'), declined: tr('Declined')})[s] || s;
function sg_row(x) {
  const st = x.revoked_at && x.state === 'open' ? tr('Turned off') : !x.live && x.state === 'open' ? tr('Expired') : sg_stTxt(x.state);
  const proto = x.state !== 'open' ? `<div class="sgproto">${esc([x.signer_name, x.signer_email].filter(Boolean).join(' · '))}<br>${esc(fmtWhen(x.signed_at))} · ${esc(tr('Address {0}', x.ip || '?'))}<br><small class="muted">${esc(x.user_agent || '')}</small>${x.reason ? `<br>${esc(tr('Reason: {0}', x.reason))}` : ''}<br><small class="muted">SHA-256 ${esc((x.doc_hash || '').slice(0, 16))}…</small></div>` : '';
  const live = x.live && x.url ? `<div class="row icalrow"><input readonly value="${esc(x.url)}" aria-label="${esc(tr('Approval link'))}" data-sgurl="${x.id}"><button type="button" class="btn sm pri" data-sg="copy" data-id="${x.id}">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm danger" data-sg="stop" data-id="${x.id}">${tr('Turn off')}</button></div>` : '';
  return `<li class="sgrow st-${esc(x.state)}"><div class="sghead"><b>${esc(st)}</b>${x.title ? ` <span class="muted">${esc(x.title)}</span>` : ''}<small class="muted"> · ${esc(fmtWhen(x.created_at))}</small></div>${live}${proto}</li>`;
}
function sg_draw(box, j, list) {
  const rows = j.signoffs || [], live = rows.some(x => x.live);
  const pick = list ? `<div class="row"><label for="sg-what">${tr('Acceptance of')}</label><select id="sg-what"><option value="">${tr('the whole project')}</option>${(j.sections || []).map(s => `<option value="s${s.id}">${esc(tr('Section: {0}', s.name))}</option>`).join('')}${(j.milestones || []).map(m => `<option value="t${m.id}">${esc(tr('Milestone: {0}', m.title))}</option>`).join('')}</select></div>` : '';
  box.innerHTML = `${rows.length ? `<ul class="sglist" role="list">${rows.map(sg_row).join('')}</ul>` : ''}
    ${pick}<div class="row"><label for="sg-exp">${tr('Valid until')}</label>${dateIn('sg-exp', '', {min: today(), label: tr('Valid until'), empty: tr('no expiry')})}</div>
    <div class="row"><button type="button" class="btn sm ${live ? '' : 'pri'}" data-sg="new">${ic('link', 's')} ${list ? tr('Request acceptance') : live ? tr('New approval link') : tr('Create approval link')}</button></div>
    <div class="shint">${esc(sg_note())}</div><div class="calerr" role="alert" data-sgerr hidden></div>`;
}
// the quotation (office_docs.js draws the placeholder for sent and decided quotations)
const SG_ACTIONS = {signoff_link: N_('approval link created'), signoff_revoke: N_('approval link stopped'), signoff_accepted: N_('accepted by the customer'),
  signoff_declined: N_('declined by the customer')};
function sg_box(d) {
  if (typeof OFD_ACTIONS === 'object') Object.assign(OFD_ACTIONS, SG_ACTIONS);  // the office log's words (office_docs.js loads later)
  if (d.kind !== 'offer' || d.status === 'draft') return '';
  setTimeout(() => sg_load(d.id), 0);
  return `<section class="ofdsec sgsec"><h3 class="sgh">${tr('Approval by the customer')}</h3><div id="sg-box" data-doc="${d.id}"><div class="muted mhint">${tr('Loading…')}</div></div></section>`;
}
function sg_load(did) {
  const box = document.getElementById('sg-box'); if (!box || +box.dataset.doc !== did) return;
  api('GET', `/api/office/docs/${did}/signoffs`).then(j => sg_draw(box, j, false)).catch(() => { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; });
}
// the list dialog > Public link (owner): integrations.js draws the placeholder
function sg_list_box(lid) {
  setTimeout(() => api('GET', `/api/lists/${lid}/signoffs`).then(j => { const b = document.getElementById('sg-lbox'); if (b && +b.dataset.lid === lid) sg_draw(b, j, true); }).catch(() => {}), 0);
  return `<div class="cvsec sgsec"><div class="cvh">${tr('Acceptance with signature')}</div><div id="sg-lbox" data-lid="${lid}"><div class="muted mhint">${tr('Loading…')}</div></div></div>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-sg]'); if (!b) return;
  const box = b.closest('#sg-box, #sg-lbox'); if (!box) return;
  const did = +box.dataset.doc || 0, lid = +box.dataset.lid || 0, a = b.dataset.sg;
  const err = box.querySelector('[data-sgerr]'), show = m => { if (err) { err.textContent = m || ''; err.hidden = !m; } };
  if (a === 'copy') { const i = box.querySelector(`[data-sgurl="${b.dataset.id}"]`); try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); } return; }
  if (a === 'stop' && !await askConfirm(tr('Stop the approval link?'), tr('It stops working at once.'), {ok: tr('Turn off'), danger: true})) return;
  b.disabled = true; show('');
  try {
    if (a === 'new') {
      const body = {expires: box.querySelector('#sg-exp')?.value || null}, w = box.querySelector('#sg-what')?.value || '';
      if (w[0] === 's') body.section_id = +w.slice(1); else if (w[0] === 't') body.task_id = +w.slice(1);
      await calReq('POST', did ? `/api/office/docs/${did}/signoff` : `/api/lists/${lid}/signoffs`, body);
      toast(tr('Approval link created'));
    }
    if (a === 'stop') { await calReq('POST', did ? `/api/office/signoffs/${b.dataset.id}/revoke` : `/api/lists/${lid}/signoffs/${b.dataset.id}/revoke`); toast(tr('Approval link stopped')); }
    const j = await api('GET', did ? `/api/office/docs/${did}/signoffs` : `/api/lists/${lid}/signoffs`);
    sg_draw(box, j, !did);
  } catch (x) { show(x.message); } finally { b.disabled = false; }
});
