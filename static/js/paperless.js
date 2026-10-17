// 2.48.0 (#1152): Paperless-ngx in the settings of the documents (self-hosted servers only; a hosted server answers 404
// and nothing is shown). One connection per workspace: connect (address + API token, the token is never shown again),
// the preview with the mapping (tag -> tag | folder | skip, correspondent -> sender, document type -> type), the import
// in the background with progress + Stop, and optionally new documents every few minutes. Kalmido only reads there.
const PL = {ws: null, d: null, prev: null, poll: 0, seq: 0};
const PL_EVERY_TXT = {15: N_('every 15 minutes'), 30: N_('every 30 minutes'), 60: N_('every hour'), 240: N_('every 4 hours'), 1440: N_('once a day')};

// the slot in the documents settings (docs.js dc_sDraw): drawn from the cached state, loaded once per workspace
function pl_slot(s) {
  if (PL.ws !== s.ws) { PL.ws = s.ws; PL.d = null; pl_load(); }
  return `<div class="pl-slot">${pl_html()}</div>`;
}
async function pl_load() {
  const ws = PL.ws, seq = ++PL.seq;
  let d = null; try { d = await rawFetch('GET', `/api/paperless?ws=${encodeURIComponent(ws)}`); } catch { d = null; }  // 404 on a hosted server: nothing shown
  if (seq !== PL.seq) return;
  PL.d = d || {available: false};
  pl_draw();
}
function pl_draw() {
  const el = $('.pl-slot'); if (el) el.innerHTML = pl_html();
  clearTimeout(PL.poll);
  const st = PL.d?.conn?.run?.state;
  if (el && ['queued', 'busy', 'stop'].includes(st)) PL.poll = setTimeout(pl_load, 2000);
}
function pl_html() {
  const d = PL.d; if (!d || !d.available) return '';
  const c = d.conn, can = d.can_manage;
  let h = `<h4>${tr('Paperless-ngx')}</h4><p class="muted">${tr('Bring the documents of your Paperless-ngx server into Kalmido: files, text, date, tags, correspondents and document types. Kalmido only reads there and never changes anything.')}</p>`;
  if (!c) {
    if (!can) return h + `<p class="muted">${tr('Not connected.')}</p>`;
    return h + `<div class="row"><label for="pl-url">${tr('Address')}</label><input id="pl-url" type="url" inputmode="url" autocomplete="off" placeholder="https://paperless.example.com"></div>
      <div class="row"><label for="pl-tok">${tr('API token')}</label><input id="pl-tok" type="password" autocomplete="off"></div>
      <p class="pl-err" role="alert"></p>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-pl="connect">${tr('Connect')}</button></div>`;
  }
  const r = c.run, running = ['queued', 'busy', 'stop'].includes(r.state);
  h += `<p class="pl-conn"><span class="pl-url">${esc(c.url)}</span>${can && !running ? ` <button type="button" class="linkbtn" data-pl="edit">${tr('Change')}</button> <button type="button" class="linkbtn" data-pl="disconnect">${tr('Disconnect')}</button>` : ''}</p>`;
  if (c.error_text) h += `<p class="pl-err" role="alert">${esc(c.error_text)}</p>`;
  else if (c.synced_at && !running) h += `<p class="muted">${tr('Last looked: {0}', fmtWhen(c.synced_at))}</p>`;
  if (running) {
    const pct = r.total ? Math.min(100, Math.round(r.done * 100 / r.total)) : 0;
    h += `<div class="pl-run" role="status"><div class="pl-bar"><i style="transform:scaleX(${r.total ? pct / 100 : 0.05})"></i></div>
      <span>${r.state === 'stop' ? tr('Stopping…') : r.total ? tr('{0} of {1} documents', r.done, r.total) : tr('Import starts…')}</span>
      ${can && r.state !== 'stop' ? `<button type="button" class="btn sm" data-pl="stop">${tr('Stop')}</button>` : ''}</div>`;
  } else if (r.kind === 'all' && r.done) {
    h += `<p class="muted">${tr('Last import: {0} new, {1} already there, {2} failed', r.new, r.skipped, r.failed)}</p>`;
    h += pll_line(r.learn);  // 2.69.0 B (#1847)
  }
  if (can) {
    h += `<label class="chkl"><input type="checkbox" data-pl="follow" ${c.follow ? 'checked' : ''}> ${tr('Bring in new documents automatically')}</label>
      ${c.follow ? `<div class="row"><label for="pl-every">${tr('How often')}</label><select id="pl-every" data-pl="every">${d.every_choices.map(m => `<option value="${m}" ${c.every_min === m ? 'selected' : ''}>${tr(PL_EVERY_TXT[m] || String(m))}</option>`).join('')}</select></div>` : ''}
      ${running ? '' : `<button type="button" class="btn sm" data-pl="preview">${tr('Import documents…')}</button>`}`;
  }
  return h;
}
async function pl_put(body) {
  const j = await api('PUT', '/api/paperless', {ws: PL.ws, ...body});
  PL.d = j; pl_draw(); return j;
}
// the preview sheet: counts + the mapping, then "Start import"
async function pl_preview() {
  const md = modal(`<div class="lhdr"><h3>${tr('Import from Paperless-ngx')}</h3><span class="spacer"></span><button class="iconbtn" data-plp="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div><div class="pl-pbody"><p class="muted">${tr('Loading…')}</p></div>`);
  md.classList.add('pl-pmd');
  let p; try { p = await api('GET', `/api/paperless/preview?ws=${encodeURIComponent(PL.ws)}`); } catch { md.remove(); return; }
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
    ${sec(tr('Tags'), p.tags.map(tagRow))}${sec(tr('Correspondents → senders'), p.senders.map(t => labRow('senders', t)))}${sec(tr('Document types'), p.types.map(t => labRow('types', t)))}${pll_preview_html(p)}
    <div class="foot"><button type="button" class="btn" data-plp="close">${tr('Cancel')}</button><span class="spacer"></span><button type="button" class="btn pri" data-plp="start" ${left ? '' : 'disabled'}>${tr('Import {0} documents', left)}</button></div>`;
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
    try { PL.d = await api('POST', '/api/paperless/import', {ws: PL.ws, mapping}); } catch { b.disabled = false; return; }
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
});
document.addEventListener('change', async e => {
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
