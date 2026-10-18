// 2.48.0 (#1152): Paperless-ngx in the settings of the documents (self-hosted servers only; a hosted server answers 404
// and nothing is shown). One connection per workspace: connect (address + API token, the token is never shown again),
// the preview with the mapping (tag -> tag | folder | skip, correspondent -> sender, document type -> type), the import
// in the background with progress + Stop, and optionally new documents every few minutes. Kalmido only reads there.
// 2.69.0 A (#1846): also on a hosted server (public HTTPS only), the place in the server's queue, the storage quota, and the
// second way: an export ZIP of document_exporter, uploaded in parts (plh_*), then the same preview + run.
const PL = {ws: null, d: null, prev: null, poll: 0, seq: 0, up: null, at: 0, fail: 0};
const PL_EVERY_TXT = {15: N_('every 15 minutes'), 30: N_('every 30 minutes'), 60: N_('every hour'), 240: N_('every 4 hours'), 1440: N_('once a day')};
const PLH_ACTIVE = ['queued', 'busy', 'stop'];
const pl_running = d => PLH_ACTIVE.includes(d?.conn?.run?.state) || PLH_ACTIVE.includes(d?.zip?.run?.state) || (d?.zip?.state === 'check' && !!d.zip.mine);

// the slot: mode 'full' = Settings > Integrations (connection, import, ZIP), 'docs' = the documents settings (docs.js dc_sDraw:
// only the progress of a running import and a way to the import / to the settings). 2.87.9 (#1936)
// 2.87.9 (#1938): a slot drawn again (a settings dialog opened again) loads afresh unless the state is from just now: before,
// it drew the cached state of the last poll ("104 of 182") and never asked again while the import ran on
function pl_slot(s, mode = 'docs') {
  if (PL.ws !== s.ws) { PL.ws = s.ws; PL.d = null; PL.fail = 0; }
  if (!PL.d || Date.now() - PL.at > 1500) pl_load();
  // the answer may come before the dialog is on screen (no slot to poll for yet): once it is, a running import polls on
  setTimeout(() => { if ($('.pl-slot') && !PL.up && pl_running(PL.d)) pl_draw(); }, 0);
  return `<div class="pl-slot" data-plmode="${mode}">${pl_html(mode)}</div>`;
}
// Settings > Integrations (settings.js): the workspace shown in the sidebar (or the private one with "All")
function pl_setHtml() {
  const cur = typeof wsCur === 'function' ? wsCur() : 'private';
  return pl_slot({ws: PL.ws && PL.up ? PL.ws : cur.startsWith('org:') ? cur : 'private'}, 'full');
}
async function pl_load() {
  const ws = PL.ws, seq = ++PL.seq;
  let d = null, lost = false;
  try { d = await rawFetch('GET', `/api/paperless?ws=${encodeURIComponent(ws)}`); }
  catch (x) { lost = !x?.status || x.status >= 500 || x.status === 429; d = null; }
  if (seq !== PL.seq) return;
  // 2.87.9 (#1938): a lost answer (offline, the server busy) keeps the last state and asks again, a little later each time
  if (lost && PL.d) { PL.fail++; pl_draw(); return; }
  const was = PL.d?.ws === ws && pl_running(PL.d) && !PL.up;
  PL.fail = 0; PL.at = Date.now();
  PL.d = d || {available: false};
  if (was && !pl_running(PL.d)) toast(tr('Import from Paperless-ngx finished'));  // 2.87.9 (#1938): done = said once
  pl_draw();
  // 2.81.0 (#1874): the server checks an uploaded export in the background; once it is ready the preview opens as before
  if (PL.zopen === ws && PL.d?.zip?.state !== 'check') { PL.zopen = null; if (PL.d?.zip?.state === 'ready' && PL.d.zip.mine) pl_preview(true); }
}
function pl_draw() {
  const els = $$('.pl-slot');
  els.forEach(el => { el.innerHTML = pl_html(el.dataset.plmode); });
  clearTimeout(PL.poll);
  // 2.87.9 (#1938): polls while a run goes on and a slot shows it; a slot drawn later loads again (pl_slot)
  if (els.length && !PL.up && pl_running(PL.d)) PL.poll = setTimeout(pl_load, Math.min(10000, 2000 * (PL.fail + 1)));
  pl_jumpNow();
}
function pl_jumpNow() {  // 2.87.9 (#1936): the jump from the search / the documents settings lands on the section
  const h = PL.jump && $('#s-pl-h'); if (!h) return;
  PL.jump = false; h.scrollIntoView?.({block: 'start'}); h.classList.add('flash'); setTimeout(() => h.classList.remove('flash'), 1600);
}
// 2.87.9 (#1940): where a run files the documents, in words
function pl_toText(r) {
  if (r?.target === 'private') return r.mine ? tr('your private space') : tr('the private space of the person who started it');
  return PL.ws === 'private' ? tr('your private space') : tr('the organisation {0}', wsName(PL.ws));
}
// a running import: bar, count, target (#1940), Stop and the line that it runs on without the window (#1935)
function pl_runHtml(r, stop) {
  const pct = r.total ? Math.min(100, Math.round(r.done * 100 / r.total)) : 0;
  return `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(${r.total ? pct / 100 : 0.05})"></i></div>
      <span>${r.state === 'stop' ? tr('Stopping…') : r.state === 'queued' ? (r.place ? tr('Waiting, place {0} in the queue', r.place) : tr('Import starts…')) : r.total ? tr('{0} of {1} documents', r.done, r.total) : tr('Import starts…')}</span>
      ${stop && r.state !== 'stop' ? `<button type="button" class="btn sm" data-pl="${stop}">${tr('Stop')}</button>` : ''}</div>
    <p class="muted pl-to">${esc(tr('Into {0}', pl_toText(r)))}</p>
    ${r.state === 'stop' ? '' : `<p class="muted pl-bg">${tr('Runs on in the background. You can close the window.')}</p>`}`;
}
// the upload of an export ZIP (the browser sends it: the window has to stay open)
function plh_upHtml(up) {
  const pct = up.total ? Math.min(100, Math.round(up.done * 100 / up.total)) : 0;
  return `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(${pct / 100})"></i></div>
      <span>${up.check ? tr('Checking the export…') : tr('Uploading: {0} of {1}', fmtBytes(up.done), fmtBytes(up.total))}</span>
      ${up.check ? '' : `<button type="button" class="btn sm" data-pl="zip-cancel">${tr('Cancel')}</button>`}</div>
    ${up.check ? '' : `<p class="muted pl-bg">${tr('Keep the window open until the upload is done.')}</p>`}`;
}
// 2.87.9 (#1936): the documents settings only show a running import and the way to the import / to the settings
function pl_docsHtml(d) {
  const r = d.conn?.run, z = d.zip, can = d.can_manage;
  let h = `<h4>${tr('Paperless-ngx')}</h4>`, busy = false;
  if (PL.up) { h += plh_upHtml(PL.up); busy = true; }
  if (r && PLH_ACTIVE.includes(r.state)) { h += pl_runHtml(r, can && 'stop'); busy = true; }
  if (z?.run && PLH_ACTIVE.includes(z.run.state)) { h += pl_runHtml(z.run, can && 'zip-stop'); busy = true; }
  else if (z?.state === 'check' && z.mine) { h += `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(1)"></i></div><span>${tr('Checking the export…')}</span></div><p class="muted pl-bg">${tr('Runs on in the background. You can close the window.')}</p>`; busy = true; }
  if (!busy && can && d.conn) h += `<p class="pl-docs"><button type="button" class="btn sm" data-pl="preview">${tr('Import from Paperless-ngx…')}</button></p>`;
  h += `<p class="pl-docs"><button type="button" class="linkbtn" data-pl="goset">${d.conn || !can ? tr('Paperless-ngx in the settings') : tr('Connect in the settings')}</button></p>`;
  return h;
}
function pl_html(mode) {
  const d = PL.d; if (!d || !d.available) return '';
  if (mode !== 'full') return pl_docsHtml(d);
  const c = d.conn, can = d.can_manage;
  // 2.87.9 (#1936): one connection per workspace: the section names it and switches between them (not during an upload)
  const wss = typeof wsOn === 'function' && wsOn() ? ['private', ...(S.me.workspaces || []).map(w => 'org:' + w.id)] : [];
  let h = `<h4 id="s-pl-h">${tr('Paperless-ngx')}</h4>${wss.length ? `<div class="row"><label for="pl-ws">${tr('Workspace')}</label><select id="pl-ws" data-pl="ws" ${PL.up ? 'disabled' : ''}>${wss.map(w => `<option value="${esc(w)}" ${w === PL.ws ? 'selected' : ''}>${esc(wsName(w))}</option>`).join('')}</select></div>` : ''}<p class="muted">${tr('Bring the documents of your Paperless-ngx server into Kalmido: files, text, date, tags, correspondents and document types. Kalmido only reads there and never changes anything.')}</p>`;
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
    h += pl_runHtml(r, can && 'stop');  // 2.87.9 (#1935, #1940)
  } else if (r.kind === 'all' && r.done) {
    h += `<p class="muted">${tr('Last import: {0} new, {1} already there, {2} failed', r.new, r.skipped, r.failed)}</p>`;
    h += pll_line(r.learn);  // 2.69.0 B (#1847)
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
    ${sec(tr('Tags'), p.tags.map(tagRow))}${sec(tr('Correspondents → senders'), p.senders.map(t => labRow('senders', t)))}${sec(tr('Document types'), p.types.map(t => labRow('types', t)))}${pll_preview_html(p)}
    <div class="foot"><button type="button" class="btn" data-plp="close">${tr('Cancel')}</button><span class="spacer"></span><button type="button" class="btn pri" data-plp="start" ${left && p.size?.fits !== 'no' ? '' : 'disabled'}>${tr('Import {0} documents', left)}</button></div>`;
  md.addEventListener('change', e => {
    const s = e.target.closest('select[data-plk]'); if (!s) return;
    const inp = $('[data-pln]', s.closest('li')); if (inp) inp.disabled = s.value === 'skip';
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-plp]'); if (!b) return;
    if (b.dataset.plp === 'close') { md.remove(); return; }
    const mapping = {tags: {}, senders: {}, types: {}, rules: $('#pll-rules', md) ? $('#pll-rules', md).checked : true};  // 2.69.0 B (#1847)
    $$('.pl-map', md).forEach(li => {
      const s = $('select', li), name = $('[data-pln]', li).value.trim(), k = s.dataset.plk, id = li.dataset.id;
      if (k === 'tags') mapping.tags[id] = {to: s.value, name};
      else mapping[k][id] = s.value === 'skip' ? '' : name;
    });
    b.disabled = true;
    // 2.87.9 (#1940): where the documents go, in words; from an organisation also "Rather into private"
    const to = await importTargetConfirm({what: trn('{0} document', '{0} documents', left), ws: PL.ws, privOk: true});
    if (!to) { b.disabled = false; return; }
    try { PL.d = await api('POST', `${base}/import`, {ws: PL.ws, mapping, ...(to === 'private' ? {target: 'private'} : {})}); } catch { b.disabled = false; return; }
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
    catch (x) {  // 2.87.9 (#1936): the slot may have been drawn again meanwhile: the error goes into the one on screen
      const e2 = er?.isConnected ? er : $('.pl-slot[data-plmode="full"] .pl-err') || er;
      if (e2) e2.textContent = x?.message || tr('Paperless-ngx could not be reached'); b.disabled = false; }
    return;
  }
  if (a === 'edit') { const keep = PL.d; PL.d = {...keep, conn: null}; pl_draw(); const u = $('#pl-url'); if (u) { u.value = keep.conn.url; u.focus(); } return; }
  if (a === 'disconnect') {
    if (!await askConfirm(tr('Disconnect Paperless-ngx?'), tr('The token is removed. Documents already imported stay in Kalmido.'), {ok: tr('Disconnect')})) return;
    PL.d = await api('DELETE', `/api/paperless?ws=${encodeURIComponent(PL.ws)}`).catch(() => PL.d); pl_draw(); return;
  }
  if (a === 'stop') { PL.d = await api('POST', '/api/paperless/stop', {ws: PL.ws}).catch(() => PL.d); pl_draw(); return; }
  if (a === 'preview') pl_preview();
  if (a === 'goset') { b.closest('.dc-smd')?.remove(); pl_openSettings(); return; }  // 2.87.9 (#1936)
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
  if (el.dataset.pl === 'ws') { PL.ws = el.value; PL.d = null; PL.fail = 0; pl_draw(); pl_load(); return; }  // 2.87.9 (#1936)
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

// 2.69.0 B (#1847): the matching rules of Paperless-ngx in the preview (a switch, on by default) and what the last import learnt
function pll_preview_html(p) {
  const r = p && p.rules; if (!r) return '';
  const n = r.convert || 0, bad = r.unsupported || [];
  if (!n && !r.dup && !r.auto && !bad.length) return '';
  const WHY = {long: N_('pattern too long'), pattern: N_('pattern too complex'), unknown: N_('unknown kind'), limit: N_('rule limit reached')};
  let h = `<div class="pll-rules">`;
  if (n) h += `<label class="chkl"><input type="checkbox" id="pll-rules" ${r.on === false ? '' : 'checked'}> ${tr('Take over the matching rules from Paperless-ngx ({0})', n)}</label>`;
  const notes = [];
  if (r.dup) notes.push(tr('{0} rules are already here', r.dup));
  if (r.auto) notes.push(tr('{0} use “Auto” in Paperless-ngx: Kalmido learns them from the imported documents', r.auto));
  if (notes.length) h += `<p class="muted">${esc(notes.join(' · '))}</p>`;
  if (bad.length) h += `<details class="pll-bad"><summary class="muted">${tr('{0} rules cannot be taken over', r.unsupported_n || bad.length)}</summary><ul>${bad.map(b => `<li>${esc(b.name)} <span class="muted">${esc(tr(WHY[b.why] || b.why))}</span></li>`).join('')}</ul></details>`;
  return h + '</div>';
}
function pll_line(l) {
  if (!l) return '';
  const parts = [];
  if (l.trained) parts.push(tr('learnt from {0} documents', l.trained));
  if (l.rules_new) parts.push(tr('{0} rules taken over', l.rules_new));
  if (l.unsupported_n) parts.push(tr('{0} rules not taken over', l.unsupported_n));
  return parts.length ? `<p class="muted pll-line">${esc(parts.join(' · '))}</p>` : '';
}
// ---- 2.69.0 A (#1846): an export ZIP of Paperless-ngx (document_exporter), for a server Kalmido cannot reach
function plh_html(d) {
  if (!d?.can_manage) return '';
  const z = d.zip, up = PL.up, r = z?.run;
  let h = `<div class="plh-zip"><h5 class="plh-way">${tr('From a Paperless-ngx export (ZIP)')}</h5>`;
  const intro = `<p class="muted">${tr('For a Paperless-ngx that is only reachable in your own network: create an export on its server with {0} and upload the ZIP here. No connection needed.', '<code>document_exporter ../export --zip</code>')}</p>`;
  const pick = (label, pri) => `<input type="file" id="plh-file" accept=".zip,application/zip" hidden><button type="button" class="btn sm${pri ? ' pri' : ''}" data-pl="zip-pick">${label}</button>`;
  if (up) return h + plh_upHtml(up) + '</div>';  // 2.87.9 (#1935): the upload needs the window open
  if (r && PLH_ACTIVE.includes(r.state)) return h + pl_runHtml(r, 'zip-stop') + '</div>';  // 2.87.9 (#1935, #1940)
  if (z?.state === 'check' && z.mine) {  // 2.81.0 (#1874): the server checks the export in the background
    return h + `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(1)"></i></div><span>${tr('Checking the export…')}</span></div><p class="muted pl-bg">${tr('Runs on in the background. You can close the window.')}</p></div>`;
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
    h += pll_line(r.learn);
  }
  if (z && ['upload', 'check', 'ready'].includes(z.state) && !z.mine) return h + `<p class="muted">${tr('Another import is under way in this area')}</p></div>`;
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
  PL.up = null;
  if (PL.d?.zip?.state === 'check') PL.zopen = ws;  // 2.81.0 (#1874): pl_load opens the preview once the check is done
  pl_draw();
  if (PL.d?.zip?.state === 'ready') pl_preview(true);
}

// 2.87.9 (#1936, #1934): Settings > Integrations > Paperless-ngx (the search, the documents settings jump there)
function pl_openSettings() { PL.jump = true; Promise.resolve(settingsModal('paperless')).then(() => setTimeout(pl_jumpNow, 50)); }
// 2.87.9 (#1934): the search's "Import from Paperless-ngx…": the import of the shown workspace; without a connection the
// settings, where it is set up
async function pl_importActive() {
  const cur = typeof wsCur === 'function' ? wsCur() : 'private', ws = cur.startsWith('org:') ? cur : 'private';
  if (PL.ws !== ws || !PL.d) { PL.ws = ws; PL.d = null; await pl_load(); }
  if (PL.d?.conn && PL.d.can_manage && !pl_running(PL.d)) return pl_preview();
  pl_openSettings();
}
