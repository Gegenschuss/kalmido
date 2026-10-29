// @ts-check
// 2.425.0 C (#3453): "Receipt fetcher" in Settings > Integrations, below the folder watcher (docscan.js dsc_integrHtml /
// dsc_integrDraw): a helper program on the person's computer fetches invoices from portals and uploads them into the office's
// documents. Here: connect one with a setup code (shown once), its portals with on / off, last run, new receipts and an error,
// and disconnect it. Only with the office. Kalmido stores no passwords, cookies or logins (the helper keeps its own sign-ins).
const FXS = {code: '', ws: '', j: /** @type {any} */ (null)};
NOTIF_ROWS.push(['fetcher', N_('Receipt fetcher'), N_('a portal of your receipt fetcher reports an error, for example a sign-in that ran out')]);
function fx_html() {
  if (!feat('office')) return '';
  return `<h4 id="s-fetch-h">${tr('Receipt fetcher')}</h4><div id="s-fetch" class="dsc-embed fx-box"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
function fx_ws() {
  const cur = typeof wsCur === 'function' ? wsCur() : 'private';
  return cur.startsWith('org:') ? cur : 'private';
}
async function fx_draw(/** @type {ParentNode} */ md) {
  const box = /** @type {HTMLElement|null} */ (md.querySelector('#s-fetch')); if (!box) return;
  const ws = fx_ws();
  try { FXS.j = await api('GET', `/api/docs/fetchers?ws=${encodeURIComponent(ws)}`); } catch { box.innerHTML = ''; return; }
  if (FXS.code && FXS.ws !== ws) FXS.code = '';
  FXS.ws = ws;
  if (box.isConnected) box.innerHTML = fx_bodyHtml(FXS.j);
}
function fx_portalHtml(f, p) {
  const st = [p.last_run ? tr('last run {0}', relTime(p.last_run)) : tr('not run yet'), p.new ? trn('{0} new receipt', '{0} new receipts', p.new) : ''].filter(Boolean).join(' · ');
  return `<li class="dc-rule fx-portal${p.error ? ' fx-err' : ''}${p.enabled ? '' : ' off'}"><span><b>${esc(p.name)}</b><small class="muted">${esc(st)}</small>
    ${p.error ? `<small class="fx-errtxt" role="note">${ic('alert', 's')} ${esc(p.error)}</small>` : ''}</span>
    <label class="chkl"><input type="checkbox" data-fxp="${f.id}:${esc(p.key)}" ${p.enabled ? 'checked' : ''} aria-label="${esc(tr('Fetch from {0}', p.name))}"> ${tr('On')}</label></li>`;
}
function fx_bodyHtml(j) {
  const intro = `<p class="muted">${tr('A helper program on your computer fetches invoices from portals like Amazon and uploads them as PDFs into these documents; they are recognised like any upload. You sign in to the portals only in the helper: Kalmido never stores passwords, cookies or logins.')}</p>`;
  if (!j.api) return intro + `<p class="muted">${tr('The API is turned off on this server, so there are no receipt fetchers.')}</p>`;
  const one = f => `<div class="dsc-way fx-one${f.ok ? '' : ' off'}"><div class="fx-head"><span><b>${esc(f.name)}</b> <span class="muted">${esc(f.target)}</span>
      <small class="muted">${f.last_seen_at ? esc(tr('last report {0}', relTime(f.last_seen_at))) : tr('not connected yet')}</small></span>
      <button type="button" class="iconbtn danger" data-fx="del:${f.id}" aria-label="${esc(tr('Disconnect {0}', f.name))}" title="${esc(tr('Disconnect'))}">${ic('trash')}</button></div>
    ${f.portals.length ? `<ul class="dc-rules">${f.portals.map(p => fx_portalHtml(f, p)).join('')}</ul>` : `<p class="muted">${tr('The portals appear here after the first report of the helper.')}</p>`}</div>`;
  return `${intro}${j.fetchers.map(one).join('')}${FXS.code ? fx_codeHtml() : ''}
    <details class="dc-radd dsc-new fx-new"${j.fetchers.length || FXS.code ? '' : ' open'}><summary>${tr('Connect a receipt fetcher')}</summary>
      <div class="row"><label for="fx-name">${tr('Name')}</label><input id="fx-name" maxlength="60" value="${esc(tr('My computer'))}" autocomplete="off"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-fx="new">${tr('Create setup code')}</button></div></details>`;
}
function fx_codeHtml() {
  return `<div class="dsc-code" role="status"><p><b>${tr('Setup code')}</b> <span class="muted">${tr('Only visible now')}</span></p>
    <div class="dsc-row"><input id="fx-code" readonly value="${esc(FXS.code)}" aria-label="${esc(tr('Setup code'))}"><button type="button" class="btn sm" data-fx="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <p class="muted">${tr('Paste the code into the receipt fetcher. It then uploads into the place shown above and reports its portals here.')}</p></div>`;
}
document.addEventListener('click', async e => {
  const b = /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (e.target).closest?.('#s-fetch [data-fx]')); if (!b) return;
  const md = document, a = b.dataset.fx || '';
  if (a === 'copy') { dsc_copy(FXS.code); return; }
  if (a === 'new') {
    const name = (/** @type {HTMLInputElement|null} */ (md.querySelector('#fx-name'))?.value || '').trim();
    if (!name) { /** @type {HTMLElement|null} */ (md.querySelector('#fx-name'))?.focus(); return; }
    let j; b.setAttribute('disabled', ''); try { j = await api('POST', '/api/docs/fetchers', {ws: fx_ws(), name}); } catch { b.removeAttribute('disabled'); return; }
    FXS.code = j.code; FXS.ws = fx_ws();
    await fx_draw(md);
    /** @type {HTMLElement|null} */ (md.querySelector('#fx-code'))?.focus();
    return;
  }
  if (a.startsWith('del:')) {
    const id = +a.slice(4), f = (FXS.j?.fetchers || []).find(x => x.id === id); if (!f) return;
    if (!await askConfirm(tr('Disconnect the receipt fetcher “{0}”?', f.name), tr('Its key stops working at once; the receipts it brought stay.'), {ok: tr('Disconnect'), danger: true})) return;
    try { await api('DELETE', `/api/docs/fetchers/${id}`); } catch { return; }
    toast(tr('Disconnected: {0}', f.name));
    await fx_draw(md);
  }
});
document.addEventListener('change', async e => {
  const el = /** @type {HTMLInputElement} */ (e.target); if (!el.matches?.('#s-fetch [data-fxp]')) return;
  const [id, key] = String(el.dataset.fxp).split(/:(.*)/s);
  try { await api('PATCH', `/api/docs/fetchers/${+id}/portals/${encodeURIComponent(key)}`, {enabled: el.checked}); } catch { el.checked = !el.checked; return; }
  el.closest('.fx-portal')?.classList.toggle('off', !el.checked);
  const p = (FXS.j?.fetchers || []).find(x => x.id === +id)?.portals.find(x => x.key === key); if (p) p.enabled = el.checked;
});
