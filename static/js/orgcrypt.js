// ---- 2.42.0 (#828): Settings > Organisation > "Encryption" (admins of the organisation) and the instance switch
// org_encrypt (Settings > Administration > Organisation). The server encrypts the organisation's bank / tax data, purchase
// prices, framework contract rates and stored files with a key of the organisation (kalmido/core/orgcrypt.py); here: the
// state, and the recovery key (shown after the password, with a copy button and a plain warning). No switch for members.
function ocBoxHtml(o) {
  return `<div class="ocbox" data-ocorg="${o.id}"><h5>${tr('Encryption')}</h5>
    <div class="ocst" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div></div>`;
}
function ocStateHtml(j) {
  if (!j.enabled) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('Off: the server has no key (KALMIDO_SECRET_KEY). Bank and tax data, purchase prices and files are stored unencrypted, see SELF-HOSTING.md.'))}</div>`;
  if (j.key_ok === false) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('The server key does not match this organisation’s key. Ask the server admin (SELF-HOSTING.md, recovery key).'))}</div>`;
  const when = x => x ? new Date(x).toLocaleDateString(I18N.code || 'en') : '';
  return `<div class="shint">${esc(j.active ? tr('On: bank and tax data, purchase prices, framework contract rates and the files of the organisation’s lists and documents are stored encrypted with the organisation’s own key. Everyone who may see them sees them as before.')
      : tr('Paused by the server admin: new data is stored unencrypted, encrypted data stays readable.'))}</div>
    <div class="shint">${esc(tr('The recovery key opens the organisation’s data if the server key is ever lost. Keep it offline, e.g. printed in a safe. Without the server key and without the recovery key the encrypted data is lost for good.'))}</div>
    <div class="row"><button type="button" class="btn sm" data-oc="show">${ic('key', 's')} ${tr('Show recovery key')}</button>${j.recovery_shown_at ? `<span class="muted">${esc(tr('last shown {0}', when(j.recovery_shown_at)))}</span>` : ''}</div>`;
}
async function ocLoad(box) {
  const oid = +box.dataset.ocorg, st = $('.ocst', box);
  let j; try { j = await api('GET', `/api/orgs/${oid}/encryption`); } catch { st.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  st.innerHTML = ocStateHtml(j);
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
  const adm = $('.ocadm', box.parentNode);
  if (adm && j.enabled) { adm.innerHTML = (o.orgs || []).filter(x => x.role === 'admin').map(x => `<div class="ocorg"><b>${esc(x.name)}</b>${ocBoxHtml(x)}</div>`).join(''); ocDraw(adm); }
  if (!box._ocWired) {
    box._ocWired = true;
    box.addEventListener('change', async e => {
      if (e.target.id !== 's-orgenc-on') return;
      try { await api('PUT', '/api/admin/orgcrypt', {org_encrypt: e.target.checked}); toast(tr('Saved')); } catch { e.target.checked = !e.target.checked; }
    });
  }
}
