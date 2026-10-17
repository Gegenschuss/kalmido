// ---- 2.42.0 (#828): Settings > Organisation > "Encryption" (admins of the organisation) and the instance switch
// org_encrypt (Settings > Administration > Organisation). The server encrypts the organisation's bank / tax data, purchase
// prices, framework contract rates and stored files with a key of the organisation (kalmido/core/orgcrypt.py); here: the
// state, and the recovery key (shown after the password, with a copy button and a plain warning). No switch for members.
// 2.46.0 (#1563): opt.title = the one heading (default "Encryption"), opt.title === '' = none (the section heading above says it)
function ocBoxHtml(o, opt = {}) {
  const t = opt.title ?? tr('Encryption');
  return `<div class="ocbox" data-ocorg="${o.id}">${t ? `<h5>${esc(t)}</h5>` : ''}
    <div class="ocst" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div></div>`;
}
function ocStateHtml(j) {
  if (!j.enabled) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('Off: the server has no key (KALMIDO_SECRET_KEY). Bank and tax data, purchase prices and files are stored unencrypted, see SELF-HOSTING.md.'))}</div>`;
  if (j.key_ok === false) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('The server key does not match this organisation’s key. Ask the server admin (SELF-HOSTING.md, recovery key).'))}</div>`;
  const when = x => x ? new Date(x).toLocaleDateString(I18N.code || 'en') : '';
  // 2.46.0 (#1563): one text, so one "More information" link
  return `<div class="shint">${esc(j.active ? tr('On: bank and tax data, purchase prices, framework contract rates and the files of the organisation’s lists and documents are stored encrypted with the organisation’s own key. Everyone who may see them sees them as before.')
      : tr('Paused by the server admin: new data is stored unencrypted, encrypted data stays readable.'))} ${esc(tr('The recovery key opens the organisation’s data if the server key is ever lost. Keep it offline, e.g. printed in a safe. Without the server key and without the recovery key the encrypted data is lost for good.'))}</div>
    <div class="row"><button type="button" class="btn sm" data-oc="show">${ic('key', 's')} ${tr('Show recovery key')}</button>${j.recovery_shown_at ? `<span class="muted">${esc(tr('last shown {0}', when(j.recovery_shown_at)))}</span>` : ''}</div>`;
}
async function ocLoad(box) {
  const oid = +box.dataset.ocorg, st = $('.ocst', box);
  let j; try { j = await api('GET', `/api/orgs/${oid}/encryption`); } catch { st.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  st.innerHTML = ocStateHtml(j) + (st.closest('.ocadm') ? '' : pm_cryptScopeHtml(j.scope));  // 2.46.1 (#1641): once per page
}
async function ocShowRecovery(oid, needPw) {
  let pw = '';
  if (needPw) {
    const p = await pwPrompt(tr('Show recovery key'), {text: esc(tr('Confirm with your password. Showing the key is noted in the office log.'))});
    if (!p) return;
    pw = p.password;
  }
  let j; try { j = await api('POST', `/api/orgs/${oid}/encryption/recovery`, {password: pw}); } catch { return; /* api() showed it */ }
  const md = modal(`<h3>${tr('Recovery key')}</h3>
    <p class="shint keep">${ic('alert', 's')} ${esc(tr('Anyone with this key and a copy of the data can read the organisation’s encrypted data. Keep it offline and never send it by e-mail or chat. Without the server key and without this key the data is lost.'))}</p>
    <div class="row"><code class="topic ocrk" id="oc-rk">${esc(j.recovery_key)}</code></div>
    <div class="foot"><button type="button" class="btn" data-m="copy">${ic('copy', 's')} ${tr('Copy')}</button><span class="spacer"></span><button type="button" class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'copy') toast(await clipCopy(j.recovery_key) ? tr('Copied') : tr('Copy failed, select the text by hand'));
    if (b.dataset.m === 'close') md.remove();
  });
}
function ocDraw(root) {
  root.querySelectorAll('.ocbox').forEach(ocLoad);
  if (root._ocWired) return;
  root._ocWired = true;
  root.addEventListener('click', async e => {
    const b = e.target.closest('[data-oc]'); if (!b) return;
    const box = b.closest('.ocbox'), oid = +box.dataset.ocorg;
    if (b.dataset.oc === 'show') { await ocShowRecovery(oid, box._j?.password !== false); ocLoad(box); }
  });
}
// Administration > Organisation: the instance switch (with the boxes of the organisations I administer)
const ocAdminHtml = hint => `<h4 id="s-orgenc-h">${tr('Encryption of organisation data')}</h4>
  ${hint(tr('Bank and tax data, purchase prices, framework contract rates and the files of organisations are stored encrypted with a key per organisation, made from the server key KALMIDO_SECRET_KEY. Switched off, new data is stored unencrypted; encrypted data stays readable.'))}
  <div id="s-orgenc" aria-labelledby="s-orgenc-h"><div class="muted mhint">${tr('Loading…')}</div></div><div class="ocadm"></div>`;
async function ocAdminDraw(md) {
  const box = $('#s-orgenc', md); if (!box) return;
  let j, o; try { [j, o] = await Promise.all([api('GET', '/api/admin/orgcrypt'), api('GET', '/api/orgs')]); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box.innerHTML = j.enabled ? `<div class="featgrid"><label class="wide"><input type="checkbox" id="s-orgenc-on" ${j.org_encrypt ? 'checked' : ''}><span>${tr('Encrypt organisation data')}<small class="muted">${tr('Recommended. Existing data is encrypted in the background.')}</small></span></label></div>`
    : `<div class="shint keep">${ic('alert', 's')} ${esc(tr('Off: the server has no key (KALMIDO_SECRET_KEY). Bank and tax data, purchase prices and files are stored unencrypted, see SELF-HOSTING.md.'))}</div>`;
  box.insertAdjacentHTML('beforeend', pm_cryptScopeHtml(j.scope));  // 2.46.1 (#1641): what is encrypted, what not
  const adm = $('.ocadm', box.parentNode);
  if (adm && j.enabled) { const mine = (o.orgs || []).filter(x => x.role === 'admin'); adm.innerHTML = mine.map(x => `<div class="ocorg">${ocBoxHtml(x, {title: mine.length > 1 ? x.name : ''})}</div>`).join(''); ocDraw(adm); }  // 2.46.0 (#1563): one heading (the organisation's name only with several)
  if (!box._ocWired) {
    box._ocWired = true;
    box.addEventListener('change', async e => {
      if (e.target.id !== 's-orgenc-on') return;
      try { await api('PUT', '/api/admin/orgcrypt', {org_encrypt: e.target.checked}); toast(tr('Saved')); } catch { e.target.checked = !e.target.checked; }
    });
  }
}

// ---- 2.46.0 (#1563): the boundary check in Administration > Organisation: unfolds to kind, object and person / agent; "Clean up"
// takes out the memberships of people (the server rule of the nightly run), agents must be moved to the right workspace by hand
const OA_TYPE = {list: N_('List'), calendar: N_('Calendar'), book: N_('Address book'), agent: N_('Agent'), client: N_('Client'), event: N_('Appointment')};  // 2.59.0 (#1735): client: a contact person's address book link; 2.87.0 (#1983): event: an invitation
function oa_boundaryHtml(bd) {
  if (!bd.violations) return `<div class="mhint muted" id="a-orgs-bd">${esc(tr('Boundary check: nothing crosses the boundary between workspaces'))}</div>`;
  const head = trn('Boundary check: {0} membership crosses the boundary between workspaces', 'Boundary check: {0} memberships cross the boundary between workspaces', bd.violations);
  const det = bd.details || [];
  const rows = det.map(x => `<div class="mrow"><span class="n">${esc(tr(OA_TYPE[x.type] || x.type))}: <b>${esc(x.name || '#' + x.id)}</b> <span class="muted">${esc(x.user || '#' + x.user_id)}${x.agent ? ' ' + esc(tr('Agent')) : ''}</span></span></div>`).join('');
  const more = bd.violations > det.length ? `<div class="muted mhint">${esc(trn('and {0} more', 'and {0} more', bd.violations - det.length))}</div>` : '';
  const fix = det.some(x => x.fixable) ? `<div class="row"><button type="button" class="btn sm" data-oa="repair">${ic('check', 's')} ${tr('Clean up')}</button></div>` : '';
  const ag = det.some(x => x.agent) ? `<div class="shint keep">${esc(tr('Move the agent to the right workspace (Settings > Agents).'))}</div>` : '';
  return `<details class="sdet" id="a-orgs-bd"><summary class="mhint">${esc(head)}</summary><div class="members">${rows}</div>${more}${ag}${fix}</details>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-oa="repair"]'); if (!b) return;
  const md = b.closest('.modal') || document;
  if (!await askConfirm(tr('Clean up the boundary?'), tr('Takes people out of the lists, calendars and address books of an organisation they do not belong to. Agents stay as they are. This cannot be undone here.'), {ok: tr('Clean up'), danger: true})) return;
  let j; try { j = await api('POST', '/api/admin/orgs/boundary/repair', {}); } catch { return; /* api() said it */ }
  toast(j.removed ? trn('{0} membership removed', '{0} memberships removed', j.removed) : tr('Nothing to clean up'));
  if (typeof orgsDraw === 'function') orgsDraw(md);
});
