// 2.48.0 (#1152): Paperless-ngx in the settings of the documents (self-hosted servers only; a hosted server answers 404
// and nothing is shown). One connection per workspace: connect (address + API token, the token is never shown again),
// the preview with the mapping (tag -> tag | folder | skip, correspondent -> sender, document type -> type), the import
// in the background with progress + Stop, and optionally new documents every few minutes. Kalmido only reads there.
// 2.69.0 A (#1846): also on a hosted server (public HTTPS only), the place in the server's queue, the storage quota, and the
// second way: an export ZIP of document_exporter, uploaded in parts (plh_*), then the same preview + run.
const PL = {ws: null, d: null, prev: null, poll: 0, seq: 0, up: null};
const PL_EVERY_TXT = {15: N_('every 15 minutes'), 30: N_('every 30 minutes'), 60: N_('every hour'), 240: N_('every 4 hours'), 1440: N_('once a day')};

// the slot in the documents settings (docs.js dc_sDraw): drawn from the cached state, loaded once per workspace
function pl_slot(s) {
  if (PL.ws !== s.ws) { PL.ws = s.ws; PL.d = null; pl_load(); }
  return `<div class="pl-slot">${pl_html()}</div>`;
}
async function pl_load() {
  const ws = PL.ws, seq = ++PL.seq;
  let d = null; try { d = await rawFetch('GET', `/api/paperless?ws=${encodeURIComponent(ws)}`); } catch { d = null; }
  if (seq !== PL.seq) return;
  PL.d = d || {available: false};
  pl_draw();
}
function pl_draw() {
  const el = $('.pl-slot'); if (el) el.innerHTML = pl_html();
  clearTimeout(PL.poll);
  const st = PL.d?.conn?.run?.state, zs = PL.d?.zip?.run?.state;
  if (el && !PL.up && (['queued', 'busy', 'stop'].includes(st) || ['queued', 'busy', 'stop'].includes(zs))) PL.poll = setTimeout(pl_load, 2000);
}
function pl_html() {
  const d = PL.d; if (!d || !d.available) return '';
  const c = d.conn, can = d.can_manage;
  let h = `<h4>${tr('Paperless-ngx')}</h4><p class="muted">${tr('Bring the documents of your Paperless-ngx server into Kalmido: files, text, date, tags, correspondents and document types. Kalmido only reads there and never changes anything.')}</p>`;
  if (!c) {
    if (!can) return h + `<p class="muted">${tr('Not connected.')}</p>` + plh_html(d);
    return h + `<h5 class="plh-way">${tr('Connect by address')}</h5>${d.hosted ? `<p class="muted">${tr('Only public HTTPS addresses work here. Is your Paperless-ngx only reachable in your own network? Use an export ZIP below.')}</p>` : ''}
      <div class="row"><label for="pl-url">${tr('Address')}</label><input id="pl-url" type="url" inputmode="url" autocomplete="off" placeholder="https://paperless.example.com"></div>
      <div class="row"><label for="pl-tok">${tr('API token')}</label><input id="pl-tok" type="password" autocomplete="off"></div>
      <p class="pl-err" role="alert"></p>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-pl="connect">${tr('Connect')}</button></div>` + plh_html(d);
  }
  const r = c.run, running = ['queued', 'busy', 'stop'].includes(r.state);
  h += `<p class="pl-conn"><span class="pl-url">${esc(c.url)}</span>${can && !running ? ` <button type="button" class="linkbtn" data-pl="edit">${tr('Change')}</button> <button type="button" class="linkbtn" data-pl="disconnect">${tr('Disconnect')}</button>` : ''}</p>`;
  if (c.error_text) h += `<p class="pl-err" role="alert">${esc(c.error_text)}</p>`;
  else if (c.synced_at && !running) h += `<p class="muted">${tr('Last looked: {0}', fmtWhen(c.synced_at))}</p>`;
  if (running) {
    const pct = r.total ? Math.min(100, Math.round(r.done * 100 / r.total)) : 0;
    h += `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(${r.total ? pct / 100 : 0.05})"></i></div>
      <span>${r.state === 'stop' ? tr('Stopping…') : r.state === 'queued' && r.place ? tr('Waiting, place {0} in the queue', r.place) : r.total ? tr('{0} of {1} documents', r.done, r.total) : tr('Import starts…')}</span>
      ${can && r.state !== 'stop' ? `<button type="button" class="btn sm" data-pl="stop">${tr('Stop')}</button>` : ''}</div>`;
  } else if (r.kind === 'all' && r.done) {
    h += `<p class="muted">${tr('Last import: {0} new, {1} already there, {2} failed', r.new, r.skipped, r.failed)}</p>`;
  }
  if (can) {
    h += `<label class="chkl"><input type="checkbox" data-pl="follow" ${c.follow ? 'checked' : ''}> ${tr('Bring in new documents automatically')}</label>
      ${c.follow ? `<div class="row"><label for="pl-every">${tr('How often')}</label><select id="pl-every" data-pl="every">${d.every_choices.map(m => `<option value="${m}" ${c.every_min === m ? 'selected' : ''}>${tr(PL_EVERY_TXT[m] || String(m))}</option>`).join('')}</select></div>` : ''}
      ${running ? '' : `<button type="button" class="btn sm" data-pl="preview">${tr('Import documents…')}</button>`}`;
  }
  return h + plh_html(d);
}
async function pl_put(body) {
  const j = await api('PUT', '/api/paperless', {ws: PL.ws, ...body});
  PL.d = j; pl_draw(); return j;
}
// the preview sheet: counts + the mapping, then "Start import"
async function pl_preview(zip) {
  const base = zip ? '/api/paperless/zip' : '/api/paperless';  // 2.69.0 A (#1846): the same sheet for an uploaded export
  const md = modal(`<div class="lhdr"><h3>${tr('Import from Paperless-ngx')}</h3><span class="spacer"></span><button class="iconbtn" data-plp="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div><div class="pl-pbody"><p class="muted">${tr('Loading…')}</p></div>`);
  md.classList.add('pl-pmd');
  let p; try { p = await api('GET', `${base}/preview?ws=${encodeURIComponent(PL.ws)}`); } catch { md.remove(); return; }
  PL.prev = p;
  const tagRow = t => `<li class="pl-map" data-id="${t.id}"><span class="pl-from">${esc(t.name)} <span class="muted">${t.count}</span></span>
      <select data-plk="tags" aria-label="${esc(tr('Becomes'))}"><option value="tag" ${t.to === 'tag' ? 'selected' : ''}>${tr('Tag')}</option><option value="folder" ${t.to === 'folder' ? 'selected' : ''}>${tr('Folder')}</option><option value="skip" ${t.to === 'skip' ? 'selected' : ''}>${tr('Leave out')}</option></select>
      <input data-pln value="${esc(t.target)}" maxlength="120" aria-label="${esc(tr('Name in Kalmido'))}" ${t.to === 'skip' ? 'disabled' : ''}></li>`;
  const labRow = (k, t) => `<li class="pl-map" data-id="${t.id}"><span class="pl-from">${esc(t.name)} <span class="muted">${t.count}</span></span>
      <select data-plk="${k}" aria-label="${esc(tr('Becomes'))}"><option value="keep" ${t.to === 'keep' ? 'selected' : ''}>${tr(k === 'senders' ? 'Sender' : 'Document type')}</option><option value="skip" ${t.to === 'skip' ? 'selected' : ''}>${tr('Leave out')}</option></select>
      <input data-pln value="${esc(t.target)}" maxlength="120" aria-label="${esc(tr('Name in Kalmido'))}" ${t.to === 'skip' ? 'disabled' : ''}></li>`;
  const sec = (title, rows) => rows.length ? `<details class="pl-sec" ${rows.length <= 8 ? 'open' : ''}><summary>${title} <span class="muted">${rows.length}</span></summary><ul class="pl-maps">${rows.join('')}</ul></details>` : '';
  const left = Math.max(0, p.count - p.already);
  $('.pl-pbody', md).innerHTML = `<p>${tr('{0} documents in Paperless-ngx', p.count)}${p.already ? ` · ${tr('{0} already imported', p.already)}` : ''}</p>
    <p class="muted">${tr('Each document comes with its file, text, date and notes. Documents that are already here are left out.')}</p>
    ${plh_size_html(p.size)}
    ${sec(tr('Tags'), p.tags.map(tagRow))}${sec(tr('Correspondents → senders'), p.senders.map(t => labRow('senders', t)))}${sec(tr('Document types'), p.types.map(t => labRow('types', t)))}
    <div class="foot"><button type="button" class="btn" data-plp="close">${tr('Cancel')}</button><span class="spacer"></span><button type="button" class="btn pri" data-plp="start" ${left && p.size?.fits !== 'no' ? '' : 'disabled'}>${tr('Import {0} documents', left)}</button></div>`;
  md.addEventListener('change', e => {
    const s = e.target.closest('select[data-plk]'); if (!s) return;
    const inp = $('[data-pln]', s.closest('li')); if (inp) inp.disabled = s.value === 'skip';
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-plp]'); if (!b) return;
    if (b.dataset.plp === 'close') { md.remove(); return; }
    const mapping = {tags: {}, senders: {}, types: {}};
    $$('.pl-map', md).forEach(li => {
      const s = $('select', li), name = $('[data-pln]', li).value.trim(), k = s.dataset.plk, id = li.dataset.id;
      if (k === 'tags') mapping.tags[id] = {to: s.value, name};
      else mapping[k][id] = s.value === 'skip' ? '' : name;
    });
    b.disabled = true;
    try { PL.d = await api('POST', `${base}/import`, {ws: PL.ws, mapping}); } catch { b.disabled = false; return; }
    md.remove(); pl_draw(); toast(tr('Import started: it runs in the background'));
  });
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-pl]'); if (!b || b.matches('input,select')) return;
  const a = b.dataset.pl, root = b.closest('.pl-slot');
  if (a === 'connect') {
    const url = $('#pl-url', root)?.value.trim() || PL.d?.conn?.url || '', token = $('#pl-tok', root)?.value.trim() || '', er = $('.pl-err', root);
    b.disabled = true;
    try { await rawFetch('PUT', '/api/paperless', {ws: PL.ws, url, token}).then(j => { PL.d = j; pl_draw(); toast(tr('Connected with Paperless-ngx')); }); }
    catch (x) { if (er) er.textContent = x?.message || tr('Paperless-ngx could not be reached'); b.disabled = false; }
    return;
  }
  if (a === 'edit') { const keep = PL.d; PL.d = {...keep, conn: null}; pl_draw(); const u = $('#pl-url'); if (u) { u.value = keep.conn.url; u.focus(); } return; }
  if (a === 'disconnect') {
    if (!await askConfirm(tr('Disconnect Paperless-ngx?'), tr('The token is removed. Documents already imported stay in Kalmido.'), {ok: tr('Disconnect')})) return;
    PL.d = await api('DELETE', `/api/paperless?ws=${encodeURIComponent(PL.ws)}`).catch(() => PL.d); pl_draw(); return;
  }
  if (a === 'stop') { PL.d = await api('POST', '/api/paperless/stop', {ws: PL.ws}).catch(() => PL.d); pl_draw(); return; }
  if (a === 'preview') pl_preview();
  if (a === 'zip-pick' || a === 'zip-go') $('#plh-file', root)?.click();
  if (a === 'zip-preview') pl_preview(true);
  if (a === 'zip-cancel') { if (PL.up) PL.up.abort = true; }
  if (a === 'zip-stop') { PL.d = await api('POST', '/api/paperless/zip/stop', {ws: PL.ws}).catch(() => PL.d); pl_draw(); return; }
  if (a === 'zip-drop') {
    if (!await askConfirm(tr('Discard the uploaded export?'), tr('The uploaded file is deleted. Documents already imported stay in Kalmido.'), {ok: tr('Discard')})) return;
    PL.d = await api('DELETE', `/api/paperless/zip?ws=${encodeURIComponent(PL.ws)}`).catch(() => PL.d); pl_draw();
  }
});
document.addEventListener('change', async e => {
  if (e.target.id === 'plh-file' && e.target.closest('.pl-slot')) { const f = e.target.files?.[0]; e.target.value = ''; if (f) plh_upload(f); return; }
  const el = e.target.closest('.pl-slot [data-pl]'); if (!el) return;
  if (el.dataset.pl === 'follow') {
    const to = el.checked, set = v => async () => { await pl_put({follow: v}); return {}; };
    try { await set(to)(); } catch { el.checked = !to; return; }
    const label = to ? tr('Bring in new documents automatically') : tr('No longer bring in new documents automatically');
    histToast(label, histAdd({label, sett: true, undo: set(!to), redo: set(to)}));
  }
  if (el.dataset.pl === 'every') {
    const from = PL.d.conn.every_min, to = +el.value, set = v => async () => { await pl_put({every_min: v}); return {}; };
    await set(to)().catch(() => null);
    histToast(tr('Changed setting: {0}', tr('How often')), histAdd({label: tr('Changed setting: {0}', tr('How often')), sett: true, undo: set(from), redo: set(to)}));
  }
});

// ---- 2.69.0 A (#1846): an export ZIP of Paperless-ngx (document_exporter), for a server Kalmido cannot reach
const PLH_ACTIVE = ['queued', 'busy', 'stop'];
function plh_html(d) {
  if (!d?.can_manage) return '';
  const z = d.zip, up = PL.up, r = z?.run;
  let h = `<div class="plh-zip"><h5 class="plh-way">${tr('From a Paperless-ngx export (ZIP)')}</h5>`;
  const intro = `<p class="muted">${tr('For a Paperless-ngx that is only reachable in your own network: create an export on its server with {0} and upload the ZIP here. No connection needed.', '<code>document_exporter ../export --zip</code>')}</p>`;
  const pick = (label, pri) => `<input type="file" id="plh-file" accept=".zip,application/zip" hidden><button type="button" class="btn sm${pri ? ' pri' : ''}" data-pl="zip-pick">${label}</button>`;
  if (up) {
    const pct = up.total ? Math.min(100, Math.round(up.done * 100 / up.total)) : 0;
    return h + `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(${pct / 100})"></i></div>
      <span>${up.check ? tr('Checking the export…') : tr('Uploading: {0} of {1}', fmtBytes(up.done), fmtBytes(up.total))}</span>
      ${up.check ? '' : `<button type="button" class="btn sm" data-pl="zip-cancel">${tr('Cancel')}</button>`}</div></div>`;
  }
  if (r && PLH_ACTIVE.includes(r.state)) {
    const pct = r.total ? Math.min(100, Math.round(r.done * 100 / r.total)) : 0;
    return h + `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(${r.total ? pct / 100 : 0.05})"></i></div>
      <span>${r.state === 'stop' ? tr('Stopping…') : r.state === 'queued' ? (r.place ? tr('Waiting, place {0} in the queue', r.place) : tr('Import starts…')) : r.total ? tr('{0} of {1} documents', r.done, r.total) : tr('Import starts…')}</span>
      ${r.state !== 'stop' ? `<button type="button" class="btn sm" data-pl="zip-stop">${tr('Stop')}</button>` : ''}</div></div>`;
  }
  if (z?.state === 'ready' && z.mine) {
    return h + `<p>${tr('Uploaded: {0}', esc(z.name || 'ZIP'))} <span class="muted">${fmtBytes(z.size)}</span></p>
      <div class="foot"><button type="button" class="btn sm" data-pl="zip-drop">${tr('Discard')}</button><span class="spacer"></span><button type="button" class="btn sm pri" data-pl="zip-preview">${tr('Import documents…')}</button></div></div>`;
  }
  if (z?.state === 'upload' && z.mine) {
    return h + `<p class="muted">${tr('The upload of {0} stopped at {1} %. Choose the same file again to continue.', esc(z.name || 'ZIP'), Math.floor(z.got * 100 / Math.max(1, z.size)))}</p>
      <div class="foot"><button type="button" class="btn sm" data-pl="zip-drop">${tr('Discard')}</button><span class="spacer"></span>${pick(tr('Continue…'), true)}</div></div>`;
  }
  if (z?.state === 'bad') h += `<p class="pl-err" role="alert">${esc(z.error_text)}</p>`;
  if (z?.state === 'done' && r) {
    if (r.error_text) h += `<p class="pl-err" role="alert">${esc(r.error_text)}</p>`;
    h += `<p class="muted">${tr('Last import from a ZIP: {0} new, {1} already there, {2} failed', r.new, r.skipped, r.failed)}</p>`;
    if (typeof pll_line === 'function' && r.learn) h += pll_line(r.learn);
  }
  if (z && ['upload', 'ready'].includes(z.state) && !z.mine) return h + `<p class="muted">${tr('Another import is under way in this area')}</p></div>`;
  return h + intro + `<p class="pl-err plh-err" role="alert"></p>${pick(tr('Choose ZIP file…'))}</div>`;
}
function plh_size_html(sz) {
  if (!sz || sz.need == null) return '';
  const need = (sz.exact ? '' : tr('about') + ' ') + fmtBytes(sz.need);
  if (sz.free == null) return `<p class="muted">${tr('Needs {0} of storage.', need)}</p>`;
  const t = tr('Needs {0} of storage, {1} free.', need, fmtBytes(sz.free));
  if (sz.fits === 'no') return `<p class="pl-err" role="alert">${t} ${tr('Free up storage first: the documents do not fit.')}</p>`;
  if (sz.fits === 'maybe') return `<p class="pl-warn" role="status">${t} ${tr('It may not all fit: the import stops cleanly when the storage is full.')}</p>`;
  return `<p class="muted">${t}</p>`;
}
// the upload in parts (the server says the part size); a lost answer sends the same part again, Cancel discards it
async function plh_upload(f) {
  const ws = PL.ws, er = () => $('.plh-err');
  const fail = msg => { PL.up = null; pl_draw(); const x = er(); if (x) x.textContent = msg; };
  if (!/\.zip$/i.test(f.name) && f.type !== 'application/zip') return fail(tr('Choose the ZIP file of the export'));
  if (f.size > (PL.d?.zip_max || Infinity)) return fail(tr('The file is larger than {0} MB', Math.round(PL.d.zip_max / 1048576)));
  let z = PL.d?.zip;
  const resume = z && z.state === 'upload' && z.mine && z.size === f.size && z.name === f.name.slice(-120);
  PL.up = {done: resume ? z.got : 0, total: f.size, abort: false};
  pl_draw();
  try {
    if (!resume) { PL.d = await rawFetch('POST', '/api/paperless/zip', {ws, size: f.size, name: f.name}); z = PL.d.zip; }
    let n = z.next;
    while (n * z.chunk < f.size) {
      if (PL.up.abort || PL.ws !== ws) { PL.up = null; await api('DELETE', `/api/paperless/zip?ws=${encodeURIComponent(ws)}`).then(j => { PL.d = j; }).catch(() => null); pl_draw(); return; }
      const fd = new FormData(); fd.append('ws', ws); fd.append('n', String(n)); fd.append('part', f.slice(n * z.chunk, Math.min(f.size, (n + 1) * z.chunk)), 'part');
      if ((n + 1) * z.chunk >= f.size) { PL.up.check = true; pl_draw(); }  // the server checks the export after the last part
      let j = null;
      for (let t = 0; t < 3 && !j; t++) { try { j = await rawFetch('POST', '/api/paperless/zip/part', fd); } catch (x) { if (t === 2 || (x?.status && x.status < 500)) throw x; await new Promise(res => setTimeout(res, 1500)); } }
      n++; PL.up.done = Math.min(f.size, n * z.chunk);
      PL.d = j; pl_draw();
    }
  } catch (x) { return fail(x?.message || tr('The upload failed')); }
  PL.up = null; pl_draw();
  if (PL.d?.zip?.state === 'ready') pl_preview(true);
}
