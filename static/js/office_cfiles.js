// 2.117.0 B (#2285): PDF files of a framework contract (the signed contract, addenda) in its dialog: upload, view, replace,
// remove (one undo step each), a date per file; the paper clip in the contracts list. A new contract keeps the chosen files
// until it is saved (office.js calls dmaAfterSave with its id). Admins write, members of the office only look.
const DMA = {pending: []};
const dmaUrl = (cid, fid) => `/api/office/contracts/${cid}/files${fid ? '/' + fid : ''}`;
const dmaClip = n => n ? `<span class="dma-clip" title="${esc(tr('{0} PDF attached', n))}" aria-label="${esc(tr('{0} PDF attached', n))}">${ic('clip', 's')}${n > 1 ? `<small>${n}</small>` : ''}</span>` : '';
function dmaSend(cid, file, o = {}) {
  const fd = new FormData(); fd.append('file', file, file.name || 'contract.pdf');
  if (o.replace) fd.append('replace', String(o.replace));
  if (o.date) fd.append('date', o.date);
  return api('POST', dmaUrl(cid), fd);
}
const dmaIsPdf = f => f && (/\.pdf$/i.test(f.name || '') || f.type === 'application/pdf');
// the row of the dialog: r = the contract (null: a new one)
function dmaRowHtml(r) {
  DMA.pending = [];
  return `<div class="row dma-row"><label id="dma-lab">${tr('Contract (PDF)')}</label><div class="dma-box" id="dma-box" data-fg-skip data-cid="${r?.id || ''}" aria-labelledby="dma-lab">${r ? `<p class="muted">${tr('Loading…')}</p>` : dmaListHtml([], null)}</div></div>`;
}
function dmaListHtml(items, cid) {
  const adm = ofcAdmin();
  const rows = items.map(f => `<li class="dma-f" data-fid="${f.id}"><button type="button" class="dma-open" data-dma="view" data-fid="${f.id}" title="${esc(tr('Open'))}">${ic('file', 's')}<span class="dma-n">${esc(f.name)}</span><small class="muted">${esc(fmtSize(f.size))}</small></button>
      <span class="dma-d">${dateIn('dma-date-' + f.id, f.date, {label: tr('Date'), clear: false, ro: !adm, attrs: `data-dma="date" data-fid="${f.id}"`})}</span>
      ${adm ? `<span class="dma-acts"><button type="button" class="iconbtn" data-dma="replace" data-fid="${f.id}" title="${esc(tr('Replace'))}" aria-label="${esc(tr('Replace'))}: ${esc(f.name)}">${ic('upload', 's')}</button><button type="button" class="iconbtn" data-dma="rm" data-fid="${f.id}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove'))}: ${esc(f.name)}">${ic('trash', 's')}</button></span>` : ''}</li>`).join('');
  const pend = cid ? '' : DMA.pending.map((f, i) => `<li class="dma-f"><span class="dma-open">${ic('file', 's')}<span class="dma-n">${esc(f.name)}</span><small class="muted">${esc(tr('is attached when you save'))}</small></span><span class="dma-acts"><button type="button" class="iconbtn" data-dma="unpick" data-i="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove'))}: ${esc(f.name)}">${ic('x', 's')}</button></span></li>`).join('');
  const list = rows || pend ? `<ul class="dma-list" role="list">${rows}${pend}</ul>` : `<p class="muted dma-none">${tr('No PDF attached yet')}</p>`;
  return list + (adm ? `<button type="button" class="btn sm dma-up" data-dma="up">${ic('upload', 's')}<span>${tr('Upload PDF')}</span></button>` : '');
}
async function dmaLoad(md) {
  const box = $('#dma-box', md); if (!box) return;
  const cid = +box.dataset.cid;
  if (!cid) { box.innerHTML = dmaListHtml([], null); return; }
  try { DMA.items = (await api('GET', dmaUrl(cid))).items || []; box.innerHTML = dmaListHtml(DMA.items, cid); }
  catch (x) { box.innerHTML = `<p class="muted">${esc(x.message || '')}</p>`; }
}
function dmaPick(multi, done) {
  const i = document.createElement('input'); i.type = 'file'; i.accept = 'application/pdf,.pdf'; i.multiple = multi;
  i.onchange = () => { const fs = [...i.files]; if (fs.length) done(fs); };
  i.click();
}
function dmaErr(md, msg) { const el = $('.aerr', md); if (el) el.textContent = msg || ''; }
async function dmaUploadAll(md, cid, files) {
  const bad = files.filter(f => !dmaIsPdf(f));
  if (bad.length) { dmaErr(md, tr('Only PDF files can be attached')); return; }
  const ids = [];
  try { for (const f of files) ids.push((await dmaSend(cid, f)).id); } catch (x) { dmaErr(md, x.message); }
  await dmaLoad(md); ofcReload('contracts');
  if (ids.length) toast(tr('Attached'), async () => { for (const id of ids) await api('DELETE', dmaUrl(cid, id)); dmaLoad(md); ofcReload('contracts'); });
}
// office.js: after a new contract was added, its chosen files go up
async function dmaAfterSave(cid) {
  const fs = DMA.pending; DMA.pending = [];
  let err = '';
  for (const f of fs) { try { await dmaSend(cid, f); } catch (x) { err = x.message || ''; } }
  if (fs.length) ofcReload('contracts');
  if (err) toast(err);
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-dma]'); if (!b || b.tagName === 'INPUT') return;
  const md = b.closest('.modal'), box = md && $('#dma-box', md); if (!box) return;
  const cid = +box.dataset.cid, a = b.dataset.dma, fid = +b.dataset.fid, f = (DMA.items || []).find(x => x.id === fid);
  dmaErr(md, '');
  if (a === 'up') {
    dmaPick(true, fs => {
      if (cid) { dmaUploadAll(md, cid, fs); return; }
      if (fs.some(x => !dmaIsPdf(x))) { dmaErr(md, tr('Only PDF files can be attached')); return; }
      DMA.pending.push(...fs); box.innerHTML = dmaListHtml([], null);
    });
  } else if (a === 'unpick') { DMA.pending.splice(+b.dataset.i, 1); box.innerHTML = dmaListHtml([], null); }
  else if (a === 'view' && f) {
    const u = dmaUrl(cid, fid);
    typeof pdfView === 'function' ? pdfView({url: u, name: f.name, size: f.size, dlUrl: u}) : window.open(u, '_blank', 'noopener');
  } else if (a === 'replace' && f) {
    dmaPick(false, async ([nf]) => {
      if (!dmaIsPdf(nf)) { dmaErr(md, tr('Only PDF files can be attached')); return; }
      try {
        const j = await dmaSend(cid, nf, {replace: fid});
        await dmaLoad(md); ofcReload('contracts');
        toast(tr('Replaced'), async () => { await api('POST', dmaUrl(cid, fid) + '/restore'); await api('DELETE', dmaUrl(cid, j.id)); dmaLoad(md); ofcReload('contracts'); });
      } catch (x) { dmaErr(md, x.message); }
    });
  } else if (a === 'rm' && f) {
    try {
      await api('DELETE', dmaUrl(cid, fid)); await dmaLoad(md); ofcReload('contracts');
      toast(tr('Removed'), async () => { await api('POST', dmaUrl(cid, fid) + '/restore'); dmaLoad(md); ofcReload('contracts'); });
    } catch (x) { dmaErr(md, x.message); }
  }
});
document.addEventListener('change', async e => {
  const inp = e.target.closest?.('input[data-dma="date"]'); if (!inp) return;
  const md = inp.closest('.modal'), cid = +$('#dma-box', md)?.dataset.cid, fid = +inp.dataset.fid;
  const f = (DMA.items || []).find(x => x.id === fid); if (!cid || !f || !inp.value || inp.value === f.date) return;
  const old = f.date;
  try {
    await api('PATCH', dmaUrl(cid, fid), {date: inp.value}); f.date = inp.value;
    toast(tr('Saved'), async () => { await api('PATCH', dmaUrl(cid, fid), {date: old}); dmaLoad(md); });
  } catch (x) { dmaErr(md, x.message); }
});
