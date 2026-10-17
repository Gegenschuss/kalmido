// ---- 2.42.0 (#833): Settings > Organisation > "Export the organisation" (admins of the organisation). The server builds an
// encrypted archive in the background (kalmido/admin/orgexport.py); here: start, state (polled while it runs), download,
// delete. The archive opens with the organisation's recovery key and tools/kalmido_export_decrypt.py (SELF-HOSTING.md).
const OX = {timer: 0};
function oxBoxHtml(o) {
  return `<div class="oxbox" data-oxorg="${o.id}"><h5>${tr('Export the organisation')}</h5>
    <div class="shint">${tr('An encrypted archive with the organisation’s lists, tasks, comments, files, calendars, address books, office documents and members with their roles. Not in it: the members’ private lists, other organisations, passwords and access keys.')}</div>
    <div class="shint">${tr('To open it you need the organisation’s recovery key (section Encryption) and the tool kalmido_export_decrypt.py, see SELF-HOSTING.md. The file is kept for 24 hours. On another Kalmido server an admin of an organisation takes it over under Settings > Data.')}</div>
    <div class="oxst" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div></div>`;
}
function oxStateHtml(j) {
  if (!j.enabled) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('The organisation export needs the server key KALMIDO_SECRET_KEY (the archive is encrypted with the organisation’s key), see SELF-HOSTING.md.'))}</div>`;
  const start = lbl => `<button type="button" class="btn sm" data-ox="start">${ic('download', 's')} ${lbl}</button>`;
  if (j.state === 'running') return `<div class="row"><span class="muted">${tr('The export is being created…')}</span></div>`;
  if (j.state === 'done') return `<div class="row oxdone"><span class="n">${esc(j.file)} <span class="muted">(${esc(fmtSize(j.bytes || 0))}) · ${esc(tr('available until {0}', fmtWhen(j.expires_at)))}</span></span></div>
    <div class="row"><a class="btn sm" href="/api/orgs/${j.oid}/export/file" download data-ox="dl">${ic('download', 's')} ${tr('Download')}</a><button type="button" class="btn sm" data-ox="del">${ic('trash', 's')} ${tr('Delete now')}</button>${start(tr('Create again'))}</div>`;
  return (j.state === 'failed' ? `<div class="shint keep">${ic('alert', 's')} ${esc(j.error || '')}</div>` : '') + `<div class="row">${start(tr('Create export'))}</div>`;
}
async function oxLoad(box) {
  const oid = +box.dataset.oxorg, st = $('.oxst', box);
  let j; try { j = await api('GET', `/api/orgs/${oid}/export`); } catch { st.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  st.innerHTML = oxStateHtml({...j, oid});
  if (j.state === 'running') { clearTimeout(OX.timer); OX.timer = setTimeout(() => { if (box.isConnected) oxLoad(box); }, 2500); }
}
function oxDraw(root) {
  root.querySelectorAll('.oxbox').forEach(oxLoad);
  if (root._oxWired) return;
  root._oxWired = true;
  root.addEventListener('click', async e => {
    const b = e.target.closest('[data-ox]'); if (!b || b.dataset.ox === 'dl') return;
    const box = b.closest('.oxbox'), oid = +box.dataset.oxorg;
    try {
      if (b.dataset.ox === 'start') await api('POST', `/api/orgs/${oid}/export`);
      else if (b.dataset.ox === 'del') {
        if (!await askConfirm(tr('Delete the export now?'), tr('The archive is removed from the server. You can create a new one at any time.'), {ok: tr('Delete'), danger: true})) return;
        await api('DELETE', `/api/orgs/${oid}/export`); toast(tr('Deleted'));
      }
    } catch { /* api() showed it */ }
    oxLoad(box);
  });
}
