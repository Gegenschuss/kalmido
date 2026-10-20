// 2.55.0 (#1455): the newsletter connection (Contacts > More > Newsletter…). Kalmido sends no newsletters itself: it keeps
// the contacts, segments and consent and syncs them with a newsletter service (listmonk; Brevo / CleverReach as a
// preview). The service sends, runs the double opt-in, the unsubscribe link and the bounces; unsubscriptions, bounces and
// confirmed opt-ins come back to the contacts. One connection per workspace (an organisation: its admins; a person's own
// space: that person). The access data are never shown again (only "set" + the last characters).
const NWL = {ws: null, d: null, poll: 0, seq: 0, imp: null};
const NWL_KIND_TXT = {listmonk: 'listmonk', brevo: 'Brevo', cleverreach: 'CleverReach'};
const NWL_ST_TXT = {'': N_('Unknown'), yes: N_('Consented'), pending: N_('Double opt-in pending'), unsub: N_('Unsubscribed'), bounce: N_('Bounced')};
const NWL_USER_TXT = {listmonk: N_('API user'), cleverreach: N_('Client ID')};
const NWL_TOKEN_TXT = {listmonk: N_('API token'), brevo: N_('API key'), cleverreach: N_('Client secret')};

// the workspaces the person may connect: their own space + the organisations they administer
function nwl_wsList() {
  return ['private', ...(S.me?.workspaces || []).filter(w => w.role === 'admin').map(w => 'org:' + w.id)];
}
function nwl_open() {
  const list = nwl_wsList(), cur = wsCur();
  NWL.ws = list.includes(cur) ? cur : list.includes(NWL.ws) ? NWL.ws : list[0];
  NWL.d = null; NWL.imp = null;
  const md = modal(`<div class="lhdr"><h3>${tr('Newsletter')}</h3><span class="spacer"></span><button class="iconbtn" data-nwl="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div><div class="nwl-body"><p class="muted">${tr('Loading…')}</p></div>`);
  md.classList.add('nwl-md');
  onRemove(md, () => clearTimeout(NWL.poll));
  nwl_load();
}
async function nwl_load() {
  const seq = ++NWL.seq;
  let d; try { d = await api('GET', `/api/newsletter?ws=${encodeURIComponent(NWL.ws)}`); } catch { d = null; }
  if (seq !== NWL.seq) return;
  NWL.d = d; nwl_draw();
}
function nwl_draw() {
  const el = $('.nwl-md .nwl-body'); if (!el) return;
  el.innerHTML = nwl_html();
  clearTimeout(NWL.poll);
  if (NWL.d?.conn?.busy || NWL.d?.runs?.[0]?.state === 'busy') NWL.poll = setTimeout(nwl_load, 2000);
}
const nwl_wsSel = () => { const l = nwl_wsList(); return l.length > 1 ? `<div class="row"><label for="nwl-ws">${tr('Workspace')}</label><select id="nwl-ws" data-nwlc="ws">${l.map(w => `<option value="${esc(w)}" ${w === NWL.ws ? 'selected' : ''}>${esc(wsName(w))}</option>`).join('')}</select></div>` : ''; };
function nwl_formHtml(kind, c) {
  const d = NWL.d, k = d.kinds.find(x => x.kind === kind) || d.kinds[0];
  return `<div class="row"><label for="nwl-kind">${tr('Newsletter service')}</label><select id="nwl-kind" data-nwlc="kind">${d.kinds.map(x => `<option value="${x.kind}" ${x.kind === k.kind ? 'selected' : ''}>${esc(NWL_KIND_TXT[x.kind] || x.kind)}${x.preview ? ' · ' + esc(tr('Preview')) : ''}</option>`).join('')}</select></div>
    ${k.preview ? `<p class="nwl-prev">${tr('Preview: this connection follows the service’s public documentation and has not been tried against the real service yet.')}</p>` : ''}
    <div class="row"><label for="nwl-url">${tr('Address')}</label><input id="nwl-url" type="url" inputmode="url" autocomplete="off" value="${esc(c && c.kind === k.kind ? c.url : '')}" placeholder="${esc(k.default_url || 'https://listmonk.example.com')}"></div>
    ${NWL_USER_TXT[k.kind] ? `<div class="row"><label for="nwl-user">${tr(NWL_USER_TXT[k.kind])}</label><input id="nwl-user" autocomplete="off" placeholder="${c ? esc(tr('unchanged')) : ''}"></div>` : ''}
    <div class="row"><label for="nwl-tok">${tr(NWL_TOKEN_TXT[k.kind])}</label><input id="nwl-tok" type="password" autocomplete="off" placeholder="${c ? esc(tr('unchanged')) : ''}"></div>
    <p class="nwl-err" role="alert"></p>
    <div class="foot">${c ? `<button type="button" class="btn" data-nwl="cancel">${tr('Cancel')}</button>` : ''}<span class="spacer"></span><button type="button" class="btn pri" data-nwl="connect">${tr('Connect')}</button></div>`;
}
function nwl_html() {
  const d = NWL.d;
  if (!d) return `${nwl_wsSel()}<p class="muted">${tr('Only admins of the organisation can change this')}</p>`;
  const why = `<p class="muted nwl-why">${tr('Kalmido does not send newsletters itself. A newsletter service does: it keeps the proof of the double opt-in, puts an unsubscribe link into every mail, handles bounces and sends from its own well-known servers. Kalmido keeps your contacts, segments and consent and syncs them with it.')}</p>`;
  const c = d.conn;
  if (!c || NWL.edit) return nwl_wsSel() + why + (d.key_ok ? nwl_formHtml(NWL.edit || c?.kind || 'listmonk', c) : `<p class="nwl-err">${tr('The server key is missing: the access data cannot be stored safely')}</p>`) + (c ? '' : nwl_impHtml());
  const busy = c.busy || d.runs?.[0]?.state === 'busy';
  const n = d.contacts;
  let h = nwl_wsSel() + why;
  h += `<p class="nwl-conn"><b>${esc(NWL_KIND_TXT[c.kind] || c.kind)}</b>${c.preview ? ` <span class="nwl-tag">${tr('Preview')}</span>` : ''} <span class="muted">${esc(c.url || '')}</span> <span class="muted">· ${c.hint ? tr('Access data set (…{0})', c.hint) : tr('Access data set')}</span>
    <button type="button" class="linkbtn" data-nwl="edit">${tr('Change')}</button> <button type="button" class="linkbtn" data-nwl="disconnect">${tr('Disconnect')}</button></p>`;
  if (c.error_text) h += `<p class="nwl-err" role="alert">${esc(c.error_text)}</p>`;
  if (c.kind === 'listmonk') h += `<div class="row"><label for="nwl-mode">${tr('Who goes to the service')}</label><select id="nwl-mode" data-nwlc="mode"><option value="consented" ${c.mode === 'consented' ? 'selected' : ''}>${tr('Only contacts who consented')}</option><option value="doi" ${c.mode === 'doi' ? 'selected' : ''}>${tr('Also “double opt-in pending” (the service asks them)')}</option></select></div>`;
  h += `<label class="chkl"><input type="checkbox" data-nwlc="auto" ${c.auto ? 'checked' : ''}> ${tr('Sync once a day')}</label>`;
  h += `<p class="muted">${tr('{0} contacts, {1} with an e-mail address · {2} consented, {3} pending, {4} unsubscribed or bounced', n.total, n.email, n.yes, n.pending, n.blocked)}</p>`;
  h += `<h4>${tr('Segments')}</h4>`;
  h += (d.segments || []).length ? `<ul class="nwl-segs">${d.segments.map(s => `<li><div class="nwl-sn"><b>${esc(s.name)}</b> <span class="muted">→ ${s.list_name ? esc(s.list_name) : tr('no list yet')}</span>
      <div class="muted">${esc(nwl_ruleTxt(s.rule))} · ${tr('{0} go to the service, {1} on the list', s.counts.send, s.counts.on_list)}</div></div>
      <button type="button" class="iconbtn" data-nwl="seg-edit" data-sid="${s.id}" aria-label="${esc(tr('Edit'))}" title="${esc(tr('Edit'))}">${ic('edit', 's')}</button>
      <button type="button" class="iconbtn" data-nwl="seg-del" data-sid="${s.id}" aria-label="${esc(tr('Delete'))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>`
    : `<p class="muted">${tr('No segments yet: a segment picks contacts by group, company or address book and fills one list at the service.')}</p>`;
  h += `<div class="foot"><button type="button" class="btn" data-nwl="seg-new">${ic('plus', 's')} ${tr('New segment')}</button><span class="spacer"></span>
    <button type="button" class="btn pri" data-nwl="sync" ${busy || !(d.segments || []).length ? 'disabled' : ''}>${busy ? tr('Sync running…') : tr('Sync now')}</button></div>`;
  if ((d.runs || []).length) {
    h += `<details class="nwl-log"><summary>${tr('Log')}</summary><ul>${d.runs.map(r => `<li><span class="muted">${esc(fmtWhen(r.started_at))}</span> ${esc(tr(r.kind === 'auto' ? 'daily' : 'by hand'))} ·
      ${r.state === 'busy' ? tr('running') : esc(tr('{0} added, {1} updated, {2} taken off, {3} unsubscribed, {4} bounced, {5} confirmed', r.counts.added || 0, r.counts.renamed || 0, r.counts.removed || 0, r.counts.unsub || 0, r.counts.bounce || 0, r.counts.confirmed || 0))}
      ${r.errors.map(x => `<div class="nwl-err">${esc(x.text || x.code)}</div>`).join('')}</li>`).join('')}</ul></details>`;
  }
  return h + nwl_impHtml();
}
// 2.141.0 C (#2143): consent import from a CSV (E-mail, Date, Source): preview first, then import
function nwl_impHtml() {
  const i = NWL.imp, p = i?.pre;
  let h = `<h4>${tr('Import consents')}</h4><p class="muted">${tr('A CSV file with the columns E-mail, Date and Source (optional). It only records proof for contacts that are already in your address books; nothing is sent.')}</p>
    <div class="row"><label for="nwl-imp-file">${tr('CSV file')}</label><input id="nwl-imp-file" type="file" accept=".csv,text/csv,text/plain"></div>`;
  if (p) {
    h += `<p class="nwl-imp-sum">${tr('{0} rows: {1} valid, {2} with a problem', p.rows, p.valid, p.errors_count)} · ${tr('{0} will be recorded, {1} stay as they are, {2} not in the address books', p.will_change, p.kept, p.unmatched)}</p>`;
    if (p.errors.length) h += `<ul class="nwl-imp-err">${p.errors.map(x => `<li><span class="muted">${tr('Line {0}', x.line)}</span> ${esc(x.email)} · ${esc(x.reason)}</li>`).join('')}</ul>`;
    h += `<div class="foot"><button type="button" class="btn" data-nwl="imp-cancel">${tr('Cancel')}</button><span class="spacer"></span><button type="button" class="btn pri" data-nwl="imp-go" ${p.will_change ? '' : 'disabled'}>${tr('Import')}</button></div>`;
  }
  return h;
}
function nwl_ruleTxt(r) {
  const p = [];
  if (r.tags?.length) p.push(tr('Groups: {0}', r.tags.join(', ')));
  if (r.companies?.length) p.push(tr('Companies: {0}', r.companies.join(', ')));
  if (r.books?.length) p.push(tr('Address books: {0}', r.books.map(id => NWL.d.facets.books.find(b => b.id === id)?.name || '?').join(', ')));
  return p.length ? p.join(' · ') : tr('All contacts of this workspace');
}
async function nwl_put(body) {
  NWL.d = await api('PUT', '/api/newsletter', {ws: NWL.ws, ...body}); nwl_draw(); return {};
}
// the segment sheet: name, groups / companies / address books (OR within, AND between), the list at the service
async function nwl_segEdit(s) {
  const f = NWL.d.facets, r = s?.rule || {tags: [], companies: [], books: []};
  const chips = (k, items, on) => items.length ? `<div class="fpeople nwl-chips" role="group" data-k="${k}">${items.map(x => { const v = typeof x === 'object' ? x.id : x, t = typeof x === 'object' ? x.name : x, a = on.includes(v); return `<button type="button" class="fperson ${a ? 'on' : ''}" aria-pressed="${a}" data-v="${esc(String(v))}">${esc(t)}</button>`; }).join('')}</div>` : `<p class="muted">${tr('None')}</p>`;
  const md = modal(`<div class="lhdr"><h3>${s ? tr('Edit segment') : tr('New segment')}</h3><span class="spacer"></span><button class="iconbtn" data-ns="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="row"><label for="ns-name">${tr('Name')}</label><input id="ns-name" maxlength="120" value="${esc(s?.name || '')}"></div>
    <h4>${tr('Groups')}</h4>${chips('tags', f.tags, r.tags || [])}
    <h4>${tr('Companies')}</h4>${chips('companies', f.companies, r.companies || [])}
    <h4>${tr('Address books')}</h4>${chips('books', f.books, r.books || [])}
    <p class="muted">${tr('Nothing picked = every contact of this workspace. Within one kind any match counts, across kinds all must match.')}</p>
    <div class="row"><label for="ns-list">${tr('List at the service')}</label><select id="ns-list"><option value="">${tr('Loading…')}</option></select></div>
    <p class="nwl-err" role="alert"></p>
    <div class="foot"><button type="button" class="btn" data-ns="close">${tr('Cancel')}</button><span class="spacer"></span><button type="button" class="btn pri" data-ns="save">${tr('Save')}</button></div>`);
  md.classList.add('nwl-smd');
  api('GET', `/api/newsletter/lists?ws=${encodeURIComponent(NWL.ws)}`).then(j => {
    const sel = $('#ns-list', md); if (!sel) return;
    sel.innerHTML = `<option value="__new">${tr('Create a new list with the segment’s name')}</option>` + j.lists.map(l => `<option value="${esc(l.id)}" ${s?.list_id === l.id ? 'selected' : ''}>${esc(l.name)}</option>`).join('');
  }).catch(() => { const sel = $('#ns-list', md); if (sel) sel.innerHTML = `<option value="${esc(s?.list_id || '')}">${esc(s?.list_name || tr('No list'))}</option>`; });
  md.addEventListener('click', async e => {
    const ch = e.target.closest('.nwl-chips [data-v]');
    if (ch) { const on = !ch.classList.contains('on'); ch.classList.toggle('on', on); ch.setAttribute('aria-pressed', on); return; }
    const b = e.target.closest('[data-ns]'); if (!b) return;
    if (b.dataset.ns === 'close') { md.remove(); return; }
    const pick = k => $$(`.nwl-chips[data-k="${k}"] .on`, md).map(x => k === 'books' ? +x.dataset.v : x.dataset.v);
    const lid = $('#ns-list', md).value;
    const body = {ws: NWL.ws, name: $('#ns-name', md).value.trim(), rule: {tags: pick('tags'), companies: pick('companies'), books: pick('books')}};
    if (lid === '__new') body.create_list = true; else body.list_id = lid;
    b.disabled = true;
    try {
      const j = await rawFetch(s ? 'PATCH' : 'POST', s ? `/api/newsletter/segments/${s.id}` : '/api/newsletter/segments', body);
      NWL.d = j; nwl_draw(); md.remove();
      if (!s && j.segment_id) {  // ONE undo step: the new segment goes again (its list at the service stays)
        let sid = j.segment_id;
        histAdd({label: tr('New segment'), sett: true,
          undo: async () => { NWL.d = await api('DELETE', `/api/newsletter/segments/${sid}?ws=${encodeURIComponent(body.ws)}`); nwl_draw(); return {}; },
          redo: async () => { const x = await api('POST', '/api/newsletter/segments', {...body, create_list: undefined, list_id: NWL.d?.segments?.find(y => y.id === sid)?.list_id || ''}); sid = x.segment_id; NWL.d = x; nwl_draw(); return {}; }});
      }
    } catch (x) { $('.nwl-err', md).textContent = x?.message || tr('Could not save'); b.disabled = false; }
  });
}
async function nwl_impCall(apply) {
  const i = NWL.imp;
  return api('POST', '/api/newsletter/consent/import', {ws: NWL.ws, csv: i.text, filename: i.name, apply});
}
document.addEventListener('change', async e => {
  const f = e.target.closest('#nwl-imp-file'); if (!f || !f.files[0]) return;
  const file = f.files[0];
  if (file.size > 2 * 1024 * 1024) { toast(tr('The file is too large (at most {0} MB)', 2)); return; }
  NWL.imp = {name: file.name, text: await file.text(), pre: null};
  try { NWL.imp.pre = await nwl_impCall(false); } catch { NWL.imp = null; }
  nwl_draw();
});
document.addEventListener('click', async e => {
  const b = e.target.closest('.nwl-md [data-nwl]'); if (!b) return;
  const a = b.dataset.nwl, d = NWL.d;
  if (a === 'imp-cancel') { NWL.imp = null; nwl_draw(); return; }
  if (a === 'imp-go') {
    b.disabled = true;
    try { const r = await nwl_impCall(true); NWL.imp = null; nwl_load(); toast(tr('{0} consents recorded', r.applied)); } catch { b.disabled = false; }
    return;
  }
  if (a === 'close') { b.closest('.nwl-md')?.remove(); return; }
  if (a === 'edit') { NWL.edit = d.conn.kind; nwl_draw(); return; }
  if (a === 'cancel') { NWL.edit = null; nwl_draw(); return; }
  if (a === 'connect') {
    const v = id => $(id)?.value.trim() || '', kind = v('#nwl-kind'), er = $('.nwl-md .nwl-err');
    const body = {ws: NWL.ws, kind, url: v('#nwl-url')};
    if (v('#nwl-user')) body.user = v('#nwl-user');
    if (v('#nwl-tok')) body.token = v('#nwl-tok');
    b.disabled = true;
    try { NWL.d = await rawFetch('PUT', '/api/newsletter', body); NWL.edit = null; nwl_draw(); toast(tr('Connected with the newsletter service')); }
    catch (x) { if (er) er.textContent = x?.message || tr('The newsletter service could not be reached'); b.disabled = false; }
    return;
  }
  if (a === 'disconnect') {
    if (!await askConfirm(tr('Disconnect the newsletter service?'), tr('The access data, segments and log are removed. The lists at the service and the consent of your contacts stay.'), {ok: tr('Disconnect'), danger: true})) return;
    NWL.d = await api('DELETE', `/api/newsletter?ws=${encodeURIComponent(NWL.ws)}`).catch(() => d); nwl_draw(); return;
  }
  if (a === 'seg-new') { nwl_segEdit(null); return; }
  if (a === 'seg-edit') { nwl_segEdit(d.segments.find(s => s.id === +b.dataset.sid)); return; }
  if (a === 'seg-del') {
    const s = d.segments.find(x => x.id === +b.dataset.sid); if (!s) return;
    if (!await askConfirm(tr('Delete the segment “{0}”?', s.name), tr('Its list at the newsletter service stays as it is.'), {ok: tr('Delete'), danger: true})) return;
    const ws = NWL.ws;
    try { NWL.d = await api('DELETE', `/api/newsletter/segments/${s.id}?ws=${encodeURIComponent(ws)}`); } catch { return; }
    nwl_draw();
    let sid = s.id;  // ONE undo step: the segment comes back with its rule and list
    const label = tr('Segment deleted');
    histToast(label, histAdd({label, sett: true,
      undo: async () => { const x = await api('POST', '/api/newsletter/segments', {ws, name: s.name, rule: s.rule, list_id: s.list_id}); sid = x.segment_id; NWL.d = x; nwl_draw(); return {}; },
      redo: async () => { NWL.d = await api('DELETE', `/api/newsletter/segments/${sid}?ws=${encodeURIComponent(ws)}`); nwl_draw(); return {}; }}));
    return;
  }
  if (a === 'sync') {
    b.disabled = true;
    try { NWL.d = await api('POST', '/api/newsletter/sync', {ws: NWL.ws}); } catch { b.disabled = false; return; }
    nwl_draw(); toast(tr('Sync started: it runs in the background'));
  }
});
document.addEventListener('change', async e => {
  const el = e.target.closest('.nwl-md [data-nwlc]'); if (!el) return;
  const k = el.dataset.nwlc;
  if (k === 'ws') { NWL.ws = el.value; NWL.edit = null; NWL.d = null; nwl_draw(); nwl_load(); return; }
  if (k === 'kind') { NWL.edit = el.value; const keep = {url: $('#nwl-url')?.value}; nwl_draw(); if (keep.url && el.value === 'listmonk') $('#nwl-url').value = keep.url; return; }
  if (k === 'auto' || k === 'mode') {
    const from = k === 'auto' ? NWL.d.conn.auto : NWL.d.conn.mode, to = k === 'auto' ? el.checked : el.value;
    const set = v => () => nwl_put({[k]: v});
    try { await set(to)(); } catch { if (k === 'auto') el.checked = from; else el.value = from; return; }
    const label = tr('Changed setting: {0}', k === 'auto' ? tr('Sync once a day') : tr('Who goes to the service'));
    histToast(label, histAdd({label, sett: true, undo: set(from), redo: set(to)}));
  }
});

// ---- the consent in the contact card (contacts.js ctCardHtml) ----------------------------------------------------------
// shown once a consent is set (unknown = no line; it is set through the contact's menu, nwl_ctItem)
function nwl_ctf(c, w) {
  const n = c.newsletter; if (!n || !n.status || !(c.emails || []).length) return '';
  const blocked = ['unsub', 'bounce'].includes(n.status);
  const meta = [n.at ? fmtDayAbs(n.at.slice(0, 10)) : '', n.source === 'service' ? tr('reported by the newsletter service') : n.source].filter(Boolean).join(' · ');
  return `<div class="ctf nwl-ctf">${ic('mail', 's')}<span class="ctfl muted">${tr('Newsletter')}</span><span><span class="nwl-st nwl-st-${esc(n.status || 'none')}">${esc(tr(NWL_ST_TXT[n.status || '']))}</span>${meta ? ` <span class="muted">${esc(meta)}</span>` : ''}
    ${w && !blocked ? ` <button type="button" class="linkbtn" data-nwlct="${c.id}">${tr('Change')}</button>` : ''}</span></div>`;
}
async function nwl_consentSet(ids, status, source) {
  return api('PUT', '/api/newsletter/consent', {ids, status, source: source || ''});
}
// the entry in the contact's menu (contacts.js cmenu): only with an address, a writable book and no unsub / bounce
function nwl_ctItem(c, w, anchor) {
  if (!w || !c.newsletter || !(c.emails || []).length || ['unsub', 'bounce'].includes(c.newsletter.status)) return null;
  return {label: tr('Newsletter consent…'), icon: 'mail', fn: () => nwl_ctPick(anchor, c)};
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-nwlct]'); if (!b) return;
  const c = CT.card; if (!c || c.id !== +b.dataset.nwlct) return;
  nwl_ctPick(b, c);
});
function nwl_ctPick(b, c) {
  const old = {...c.newsletter};
  const apply = async (status, source) => {
    try { await nwl_consentSet([c.id], status, source); } catch { return; }
    const redo = async () => { await nwl_consentSet([c.id], status, source); if (CT.card?.id === c.id) ctOpen(c.id); return {}; };
    const undo = async () => { await nwl_consentSet([c.id], old.status || '', old.source || ''); if (CT.card?.id === c.id) ctOpen(c.id); return {}; };
    const label = tr('Newsletter: {0}', tr(NWL_ST_TXT[status]));
    histToast(label, histAdd({label, undo, redo}));
    ctOpen(c.id);
  };
  menu(b, [{label: tr(NWL_ST_TXT.yes), icon: 'check', fn: async () => {
    const src = await askPrompt(tr('Where does the consent come from?'), '', {ok: tr('Save'), input: {placeholder: tr('e.g. sign-up form, trade fair, written consent'), max: 200}});
    if (src && src.trim()) apply('yes', src.trim());
  }}, {label: tr(NWL_ST_TXT.pending), icon: 'clock', fn: () => apply('pending', '')},
  {label: tr(NWL_ST_TXT['']), icon: 'x', fn: () => apply('', '')}]);
}
