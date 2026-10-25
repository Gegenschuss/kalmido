// ---- 2.42.0 (#833): Settings > Organisation > "Export the organisation" (admins of the organisation). The server builds an
// encrypted archive in the background (kalmido/admin/orgexport.py); here: start, state (polled while it runs), download,
// delete. The archive opens with the organisation's recovery key and tools/kalmido_export_decrypt.py (SELF-HOSTING.md).
const OX = {timer: 0};
function oxBoxHtml(o) {
  return `<div class="oxbox" data-oxorg="${o.id}"><h5>${tr('Export the organisation')}</h5>
    <div class="shint">${tr('An encrypted archive with the organisation’s projects, tasks, comments, files, calendars, address books, office documents and members with their roles. Not in it: the members’ private projects, projects of the organisation a member shares with nobody, deleted items, other organisations, passwords and access keys.')}</div>
    <div class="shint">${tr('To open it: the organisation’s recovery key and kalmido_export_decrypt.py (SELF-HOSTING.md). Kept for 24 hours; another Kalmido server takes it over under Settings > Data.')}</div>
    <div class="oxst" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div></div>`;
}
function oxStateHtml(j) {
  if (!j.enabled) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('The organisation export needs the server key KALMIDO_SECRET_KEY (the archive is encrypted with the organisation’s key), see SELF-HOSTING.md.'))}</div>`;
  const start = lbl => `<button type="button" class="btn sm" data-ox="start">${ic('download', 's')} ${lbl}</button>`;
  if (j.state === 'running') return botBusy(`<div class="row"><span class="muted">${tr('The export is being created…')}</span></div>`);  // 2.161.2 (#2611)
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
// 2.137.0 A (#2344): the export of a personal office by its owner (office settings): the same archive and recovery key as
// an organisation's, with the office and the owner's private clients only (admin/orgexport.py ox_build_personal)
function ox_pbBoxHtml(oid) {
  if (oid == null) return '';  // 0 = the own personal office (2.138.0 #1972)
  setTimeout(() => { const r = document.querySelector('.oxpb'); if (r) { oxDraw(r); ocDraw(r); } }, 0);
  return `<section class="oxpb" data-fg-skip aria-labelledby="oxpb-h"><h3 id="oxpb-h">${tr('Export the office')}</h3>
    <p class="muted">${tr('An encrypted archive with this office and your private clients, to take them to another Kalmido server: there under Settings > Data into an organisation or into your own office. It opens with the recovery key.')}</p>
    <div class="oxbox" data-oxorg="${+oid}"><div class="oxst" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div></div>${ocBoxHtml({id: +oid}, {title: ''})}</section>`;
}
// ---- 2.146.0 D (#2468): the retention export (kalmido/admin/retexport.py): a readable ZIP of the records the law asks to
// keep (invoices with e-invoice XML, receipts with files, cash books, bank statements, office log) -- in the settings for the
// person (own office) and the organisation's admins, and as the step before deleting an account or an organisation: the
// server deletes only after a finished export or an explicit waiver
function rxBoxHtml(kind, id) {
  const url = kind === 'org' ? `/api/retention/org/${+id}/export.zip` : '/api/retention/me/export.zip';
  return `<div class="rxbox" data-rx="${esc(kind)}"><h5>${tr('Retention export')}</h5>
    <div class="shint">${tr('A readable ZIP with the records you must keep: invoices with their e-invoice, receipts with their files, cash books, bank statements and the office log, with a table of contents.')}</div>
    <div class="shint">${tr('Keep these records yourself: invoices and receipts for 8 years, sent business letters for 6 years, books (cash book, logs, bank statements) for 10 years. Kalmido does not keep them after the deletion; the duty to keep them lies with you.')}</div>
    <div class="row"><a class="btn sm" href="${url}" download data-rxdl>${ic('download', 's')} ${tr('Download retention export')}</a></div></div>`;
}
// the step before a deletion: resolves 'exported' | 'waived' | null (cancelled); info = the server's retention object
async function rxAsk(info, title) {
  const L = {documents: tr('Finalised documents'), receipts: tr('Receipts'), project_receipts: tr('Receipts of projects'), cash: tr('Cash book entries'), bank: tr('Bank transactions'), archive: tr('Archived documents'),
    drives: tr('Drives'), trip_receipts: tr('Travel receipts in DATEV'), meals: tr('Entertainment receipts'),  // 2.152.0 (#2167, review A9)
    letters: tr('Sent letters')};  // 2.184.0 A (#2628)
  const counts = Object.entries(info.counts || {}).map(([k, n]) => `<li>${esc(L[k] || k)}: ${n}</li>`).join('');
  const md = modal(`<h3>${esc(tr('Retention export before deleting “{0}”', title))}</h3>
    <div class="shint keep warn">${ic('alert', 's')} ${esc(info.note)}</div>
    ${counts ? `<ul class="rxcounts">${counts}</ul>` : ''}
    ${info.can_export ? `<div class="row"><a class="btn sm pri" href="${esc(info.url)}" download data-rxdl>${ic('download', 's')} ${tr('Download retention export')}</a></div>`
      : `<div class="shint keep">${tr('Only the person themself (for their own office) or an admin of the organisation can download it, under Settings.')}</div>`}
    ${info.exported_at ? `<div class="shint keep">${esc(tr('Last finished export: {0}', fmtWhen(info.exported_at)))}</div>` : ''}
    <fieldset class="rxhow"><legend>${tr('Before deleting')}</legend>
      <label class="chkl"><input type="radio" name="rxhow" value="exported"> ${tr('The export is downloaded and kept')}</label>
      <label class="chkl"><input type="radio" name="rxhow" value="waived"> ${tr('I do without the export (the records are lost)')}</label>
    </fieldset>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn danger" data-m="go" disabled>${tr('Continue')}</button></div>`);
  const how = () => $('[name="rxhow"]:checked', md)?.value;
  md.addEventListener('change', () => { $('[data-m="go"]', md).disabled = !how(); });
  return new Promise(res => {
    onRemove(md, () => res(null));
    md.addEventListener('click', e => {
      const b = e.target.closest('button[data-m]'); if (!b) return;
      if (b.dataset.m === 'go') { res(how()); md.remove(); return; }
      md.remove();
    });
  });
}
