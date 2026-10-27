// @ts-check
// 2.153.0 (#2028): letters in the office (tab "Correspondence", admins of the office area): the list of letters
// (recipient, date, subject, status), the editor (recipient from clients / address book, date, subject, text, signature,
// channel), the PDF (DIN 5008 form B), copy, send / delivered. Server: kalmido/office/letters.py.
// Hooks for the other parts (they push functions; each gets the letter and returns HTML or does its part):
// LT_HOOKS.tools = buttons above the text (C: text blocks), .actions = buttons of a letter (C: send by e-mail, B: links),
// .sections = blocks below the editor (B: links + history; in the list without an open letter they get null).
// Open from elsewhere: #office/letters/<id>, #office/letters/new?answers=<document id> (the server prefills recipient
// and reference line, office/letterlinks.py). ltReload() loads everything anew and redraws, ltCurrent() = the open letter.
// The fields carry id="lt-<column>" name="<column>" (the text: #lt-body); the other parts read / fill them.
'use strict';
const LT_HOOKS = {tools: [], actions: [], sections: []};
const LT = {data: null, cur: null, loading: false, err: null, oid: undefined, fStatus: '', fClient: '', q: '', rc: [], rcSeq: 0, undo: null, making: '', pend: null, hid: false};  // 2.269.0 C (#3017): pend = the typed form not saved yet
LT.miss = {};  // 2.296.0 C (#3165): letter id -> the details its template could not fill (named in the editor and before sending)
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, /** @type {any} */ (['letters', 'mail', N_('Correspondence'), 1, () => ltTabHtml(), 'sell']));  // admins only; group "sell" like the documents
const LT_ST = {draft: N_('Draft'), sent: N_('Sent'), delivered: N_('Delivered')};
const LT_CH = {post: N_('Post'), email: N_('E-mail'), registered: N_('Registered mail'), fax: N_('Fax')};
const LT_FIELDS = ['rcpt_name', 'rcpt_address', 'rcpt_email', 'letter_date', 'ref_line', 'subject', 'body', 'greeting', 'sign_name', 'channel', 'tracking_no', 'followup_days'];
function ltReload() { LT.data = null; LT.cur = null; ofcDraw(); }
const ltCurrent = () => LT.cur;
const ltHooks = (k, d) => LT_HOOKS[k].map(f => { try { return f(d) || ''; } catch (x) { console.error(x); return ''; } }).join('');
const ltStTag = d => `<span class="rotag dtp-st lt-st-${esc(d.status)}">${esc(tr(LT_ST[d.status] || d.status))}</span>`;
const ltIn = (col, v, o = {}) => `<input id="lt-${col}" name="${col}" value="${esc(v ?? '')}" maxlength="${o.max || 300}" ${o.type ? `type="${o.type}"` : ''} ${o.num ? 'inputmode="numeric"' : ''} ${o.ph ? `placeholder="${esc(o.ph)}"` : ''} ${o.ro ? 'readonly' : ''} autocomplete="off">`;
const ltRow = (col, label, field, hint) => ofcRowF('lt-' + col, label, field, hint);
const ltPdfUrl = (d, dl) => `/api/office/letters/${d.id}/pdf${dl ? '?dl=1' : ''}`;

async function ltLoad() {
  if (LT.loading) return;
  LT.loading = true;
  try { LT.data = await api('GET', '/api/office/letters'); LT.err = null; }
  catch (x) { LT.data = null; LT.err = x.message || tr('unknown'); }
  LT.loading = false;
  ofcDraw();
}
async function ltOpen(id) {
  if (LT.loading) return;
  LT.loading = true;
  if (LT.pend && LT.pend.d.id !== id) await ltSave(LT.pend.d, true);  // 2.269.0 C (#3017): the letter left before its save
  try { LT.cur = await api('GET', `/api/office/letters/${id}`); } catch { LT.cur = {id, missing: true}; }
  LT.loading = false;
  ofcDraw();
  if (!LT.cur.missing) lt_keepRestore(LT.cur);
}
// #office/letters/new[?answers=<document id>]: a new draft at once, then its editor (the address stays clean)
async function ltMakeFromHash(h) {
  if (LT.making === h) return;
  LT.making = h;
  const m = /answers=(\d+)/.exec(h), b = m ? {answers: +m[1]} : {};
  try {
    const j = await api('POST', '/api/office/letters', b);
    LT.data = null; LT.cur = j; LT.making = '';
    location.replace(`#office/letters/${j.id}`);
    toast(tr('Created'), async () => { await api('DELETE', `/api/office/letters/${j.id}`); ltReload(); go('office/letters'); });
  } catch (x) { LT.making = ''; toast(x.message || tr('unknown')); go('office/letters'); }
}

// ---- the tab
function ltTabHtml() {
  if (LT.oid !== OFC.info?.org_id) Object.assign(LT, {oid: OFC.info?.org_id, data: null, cur: null, err: null, fStatus: '', fClient: '', q: ''});  // another office area
  // review A3 (2.153.0): the role accounting reads the bookkeeping, not the correspondence (the server answers 403)
  if (OFC.info?.role !== 'admin') return `<div class="empty">${tr('Only for admins of the office.')}</div>`;
  if (/^#office\/letters\/new\b/.test(location.hash)) { setTimeout(() => ltMakeFromHash(location.hash), 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (LT.err) return `<div class="empty">${esc(LT.err)}</div>`;
  if (!LT.data) { if (!LT.loading) setTimeout(ltLoad, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const id = S.route.tab === 'letters' ? S.route.id : null;
  if (id) {
    if (!LT.cur || LT.cur.id !== id) { if (!LT.loading) setTimeout(() => ltOpen(id), 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
    if (LT.cur.missing) return `<div class="empty">${tr('This letter does not exist or you cannot see it.')}</div>`;
    return LT.cur.status === 'draft' ? ltEditHtml(LT.cur) : ltViewHtml(LT.cur);
  }
  LT.cur = null;
  return ltListHtml();
}
function ltListHtml() {
  const d = LT.data, all = d.letters || [], q = LT.q.trim().toLowerCase();
  const rows = all.filter(x => (!LT.fStatus || x.status === LT.fStatus) && (!LT.fClient || x.client_id === +LT.fClient)
    && (!q || [x.rcpt_name, x.subject, x.ref_line, x.client_name, x.tracking_no].join(' ').toLowerCase().includes(q)));
  const cls = (d.clients || []).filter(c => all.some(x => x.client_id === c.id));
  const bar = `<div class="ofcbar dtp-bar lt-bar">
    <input id="lt-q" type="search" value="${esc(LT.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}">
    <select id="lt-fs" aria-label="${esc(tr('Status'))}"><option value="">${tr('All states')}</option>${Object.entries(LT_ST).map(([k, n]) => `<option value="${k}" ${k === LT.fStatus ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>
    ${cls.length ? `<select id="lt-fc" aria-label="${esc(tr('Client'))}"><option value="">${tr('All clients')}</option>${cls.map(c => `<option value="${c.id}" ${String(c.id) === LT.fClient ? 'selected' : ''}>${esc(c.display_name || c.name)}</option>`).join('')}</select>` : ''}
    <span class="spacer"></span><button class="btn sm ghost" data-lt="profile">${ic('edit', 's')}<span>${tr('Signature')}</span></button><button class="btn sm pri" data-lt="new">${ic('plus', 's')}<span>${tr('New letter')}</span></button></div>`;
  const list = !rows.length ? `<div class="empty nempty eact">${ic('mail')}<span>${all.length ? tr('No letters match the filter.') : tr('No letters yet. Write one to an authority, an insurer or a client.')}</span>${all.length ? '' : `<button class="btn pri" data-lt="new">${tr('New letter')}</button>`}</div>`
    : `<ul class="ofclist dtp-list lt-list" role="list">${rows.map(x => `<li><button type="button" class="ofcrow" data-lt="open" data-id="${x.id}"><span class="ofcn"><b>${esc(x.rcpt_name || tr('No recipient'))}</b>
    <small class="muted">${esc([fmtDateLoc(x.letter_date) || x.letter_date, x.subject, tr(LT_CH[x.channel] || x.channel)].filter(Boolean).join(' · '))}</small></span>${ltStTag(x)}${ic('chev', 's')}</button></li>`).join('')}</ul>`;
  return bar + list + (typeof oft_sharedHtml === 'function' ? oft_sharedHtml('letters') : '') + ltHooks('sections', null);  // 2.351.0 A (#2823): + shared through a folder
}
function ltHead(d) {
  return `<div class="ofcbar"><button class="btn sm ghost" data-lt="back">${ic('back', 's')}<span>${tr('All letters')}</span></button><span class="spacer"></span>
    <a class="btn sm" href="${ltPdfUrl(d)}" target="_blank" rel="noopener" data-lt="pdf">${ic('pdf', 's')}<span>${d.status === 'draft' ? tr('Preview (PDF)') : 'PDF'}</span></a>
    <button class="iconbtn" data-lt="more" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>
    <div class="dtp-head"><h3>${esc(d.subject || tr('New letter'))} ${ltStTag(d)}</h3><p class="dtp-meta">${[d.client_id && d.client_name ? `${ic('brief', 's')} <a href="#client/${d.client_id}">${esc(d.client_name)}</a>` : '', d.contact_id ? `${ic('user', 's')} <a href="#contacts/${d.contact_id}">${esc(tr('Contact'))}</a>` : '', d.agent_id ? `${ic('bot', 's')} ${esc(tr('Drafted by an agent'))}` : ''].filter(Boolean).join('<span class="muted"> · </span>')}</p></div>`;
}
function ltEditHtml(d) {
  const mine = d.created_by === LT.data?.me || !d.created_by;  // 2.357.0 C (#3158): an agent's draft is signed by the person handling it
  const chOpts = Object.entries(LT_CH).map(([k, n]) => [k, tr(n)]);
  return ltHead(d) + `<div class="dtp-form lt-form">
    <section class="lt-rc" aria-label="${esc(tr('Recipient'))}">
      ${ofcRowF('lt-rsearch', tr('Recipient'), `<input id="lt-rsearch" type="search" autocomplete="off" placeholder="${esc(tr('Search clients and contacts'))}" aria-controls="lt-sug" aria-autocomplete="list">`)}
      <ul id="lt-sug" class="lt-sug" role="listbox" aria-label="${esc(tr('Suggestions'))}" hidden></ul>
      <input type="hidden" id="lt-client_id" name="client_id" value="${esc(d.client_id || '')}"><input type="hidden" id="lt-contact_id" name="contact_id" value="${esc(d.contact_id || '')}">
      ${ltRow('rcpt_name', tr('Name'), ltIn('rcpt_name', d.rcpt_name))}
      ${ltRow('rcpt_address', tr('Address'), `<textarea id="lt-rcpt_address" name="rcpt_address" rows="4" maxlength="600" class="lt-addr">${esc(d.rcpt_address || '')}</textarea>`)}
      ${(d.warnings || []).map(w => `<p class="muted ofchint" role="status">${ic('alert', 's')} ${esc(w)}</p>`).join('')}
      ${ltRow('rcpt_email', tr('E-mail'), ltIn('rcpt_email', d.rcpt_email, {max: 254, type: 'email'}))}
    </section>
    <div class="lt-two">${ofcRowF('lt-letter_date', tr('Date'), dateIn('lt-letter_date', d.letter_date, {label: tr('Date'), clear: false, attrs: 'name="letter_date"'}))}
      ${ltRow('ref_line', tr('Reference line'), ltIn('ref_line', d.ref_line, {ph: tr('e.g. Your letter of 01.10.2026')}))}</div>
    ${ltRow('subject', tr('Subject'), ltIn('subject', d.subject))}
    ${LT.miss[d.id] ? `<p class="dtp-warn" role="status">${esc(tr('Missing details (left out in the PDF): {0}', LT.miss[d.id].join(', ')))}</p>` : ''}
    <label for="lt-body" class="dtp-lab">${tr('Text')}</label>${ltHooks('tools', d)}<textarea id="lt-body" name="body" class="dtp-ta" rows="14" maxlength="60000" spellcheck="true">${esc(d.body || '')}</textarea>
    <p class="muted ofchint">${esc(tr('Paragraphs are separated by an empty line, list items start with -.'))}</p>
    <div class="lt-two">${ltRow('greeting', tr('Greeting'), ltIn('greeting', d.greeting, {max: 120}))}${ltRow('sign_name', tr('Name under the letter'), ltIn('sign_name', d.sign_name, {max: 120}))}</div>
    ${mine ? ofcChk('lt-sign_image', tr('With my signature'), d.sign_image && LT.data?.profile?.has_image) : ''}
    <div class="lt-two">${ltRow('channel', tr('Sent by'), ofcSel('lt-channel', d.channel || 'post', chOpts).replace('<select ', '<select name="channel" '))}
      <div class="row lt-trk" ${d.channel === 'registered' ? '' : 'hidden'}><label for="lt-tracking_no">${esc(tr('Tracking number'))}</label>${ltIn('tracking_no', d.tracking_no, {max: 120})}</div></div>
    ${ltRow('followup_days', tr('Follow-up after days'), ltIn('followup_days', d.followup_days || '', {max: 3, num: 1, ph: '14'}), tr('0 or empty = no follow-up'))}
    <div class="aerr" role="alert" id="lt-err"></div>
    <div class="foot dtp-acts"><button class="btn danger ghost" data-lt="arch">${ic('archive', 's')}<span>${tr('Delete')}</span></button><span class="spacer"></span>
      ${ltHooks('actions', d)}<button class="btn" data-lt="save">${tr('Save')}</button><button class="btn pri" data-lt="sent">${ic('send', 's')}<span>${tr('Mark as sent')}</span></button></div>
  </div>${ltHooks('sections', d)}`;
}
function ltViewHtml(d) {
  const facts = [[tr('Date'), fmtDateLoc(d.letter_date) || d.letter_date], [tr('Sent by'), tr(LT_CH[d.channel] || d.channel)], d.tracking_no ? [tr('Tracking number'), d.tracking_no] : null,
    [tr('Sent'), fmtWhen(d.sent_at)], d.delivered_at ? [tr('Delivered'), fmtWhen(d.delivered_at)] : null, d.followup_due ? [tr('Follow-up'), fmtDateLoc(d.followup_due) || d.followup_due] : null].filter(Boolean);
  return ltHead(d) + `<div class="lt-facts">${facts.map(([a, b]) => `<div><span class="muted">${esc(a)}</span><b>${esc(b)}</b></div>`).join('')}</div>
    <div class="dtp-doc dtp-final lt-paper"><address class="lt-to">${esc([d.rcpt_name, d.rcpt_address].filter(Boolean).join('\n'))}</address>
      ${d.ref_line ? `<p class="muted lt-ref">${esc(d.ref_line)}</p>` : ''}<p><b>${esc(d.subject || '')}</b></p><div class="lt-text">${esc(d.body || '')}</div>
      <p class="lt-text">${esc([d.greeting, d.sign_name].filter(Boolean).join('\n\n'))}</p></div>
    <p class="muted ofchint">${esc(tr('A sent letter stays as it is; for a new version edit a copy.'))}</p>
    <div class="ofcbar dtp-acts"><button class="btn sm" data-lt="copy">${ic('copy', 's')}<span>${tr('Edit a copy')}</span></button>
      ${d.status === 'sent' ? `<button class="btn sm pri" data-lt="delivered">${ic('check', 's')}<span>${tr('Delivered')}</span></button>` : ''}
      ${d.node_id ? `<a class="btn sm ghost" href="#docs/${d.node_id}">${ic('file', 's')}<span>${tr('In the documents')}</span></a>` : ''}${ltHooks('actions', d)}</div>${ltHooks('sections', d)}`;
}

// ---- recipient suggestions (clients of the office, address book contacts of its space)
let ltRcTimer = null;
function ltRcSoon(q) { clearTimeout(ltRcTimer); ltRcTimer = setTimeout(() => ltRcLoad(q), 250); }
async function ltRcLoad(q) {
  const seq = ++LT.rcSeq;
  let rows = [];
  try { rows = (await api('GET', '/api/office/letters/recipients?q=' + encodeURIComponent(q))).recipients || []; } catch { rows = []; }
  if (seq !== LT.rcSeq) return;
  LT.rc = rows.slice(0, 12);
  const box = $('#lt-sug'); if (!box) return;
  box.innerHTML = LT.rc.length ? LT.rc.map((x, i) => `<li role="option"><button type="button" class="lt-sugb" data-lt="rc" data-i="${i}">${ic(x.kind === 'client' ? 'brief' : 'user', 's')}<span><b>${esc(x.label)}</b><small class="muted">${esc(x.sub || '')}</small></span></button></li>`).join('')
    : `<li class="muted lt-sugn">${esc(tr('Nothing found'))}</li>`;
  box.hidden = false;
}
function ltRcPick(x) {
  const set = (k, v) => { const el = $('#lt-' + k); if (el) { el.value = v ?? ''; el.dispatchEvent(new Event('input', {bubbles: true})); } };
  set('rcpt_name', x.rcpt_name); set('rcpt_address', x.rcpt_address); set('rcpt_email', x.rcpt_email);
  set('client_id', x.client_id || ''); set('contact_id', x.contact_id || '');
  const s = $('#lt-rsearch'); if (s) s.value = '';
  const box = $('#lt-sug'); if (box) box.hidden = true;
  $('#lt-subject')?.focus();
}

// ---- saving a draft (quietly after typing; "Save" at once with an undo step back to the state the letter was opened with)
function ltForm() {
  const v = k => $('#lt-' + k)?.value ?? '';
  const b = {};
  for (const k of LT_FIELDS) if ($('#lt-' + k)) b[k] = v(k);
  b.followup_days = +b.followup_days || 0;
  b.client_id = +v('client_id') || null; b.contact_id = +v('contact_id') || null;
  if ($('#lt-sign_image')) b.sign_image = $('#lt-sign_image').checked ? 1 : 0;
  return b;
}
const ltSnap = d => Object.fromEntries([...LT_FIELDS, 'client_id', 'contact_id', 'sign_image'].map(k => [k, d[k] ?? (k === 'followup_days' ? 0 : k.endsWith('_id') ? null : '')]));
async function ltSave(d, quiet) {
  // 2.269.0 C (#3017): sends the form as typed (LT.pend: also after the editor is gone -- another letter, the list, the tab
  // hidden) with expect_updated_at; saved elsewhere meanwhile -> a bar with "Reload" instead of overwriting
  if (d.status !== 'draft') return true;
  clearTimeout(ltSaveTimer);
  if ($('#lt-body') && LT.cur === d) ltPend(d);
  const p = LT.pend, t = p ? p.d : d;
  LT.pend = null;
  const b = p ? p.b : null, old = LT.undo && LT.undo.id === t.id ? LT.undo.v : ltSnap(t);
  const same = !b || Object.keys(b).every(k => String(b[k] ?? '') === String(t[k] ?? ''));
  try {
    if (!same) Object.assign(t, await rawFetch('PATCH', `/api/office/letters/${t.id}`, t.updated_at ? {...b, expect_updated_at: t.updated_at} : b));
    lt_keepDrop(t.id);
    if (!quiet) { LT.undo = null; toast(tr('Saved'), async () => { await api('PATCH', `/api/office/letters/${t.id}`, old); LT.cur = null; LT.data = null; ofcDraw(); }); }
    else if (!same && !(LT.undo && LT.undo.id === t.id)) LT.undo = {id: t.id, v: old};
    const el = $('#lt-err'); if (el) el.textContent = '';
    return true;
  } catch (x) {
    if (x.status === 409 && x.data?.letter) { lt_conflict(t, x.data.letter); return false; }
    if (!LT.pend && p) LT.pend = p;  // offline / signed out: it waits (and stays in this browser, lt_keep) for the next try
    const el = $('#lt-err'); if (el && x.message !== 'auth') el.textContent = x instanceof Offline ? tr('Offline: only works again with a connection') : x.message || '';
    return false;
  }
}
let ltSaveTimer = null;
const ltSaveSoon = () => { if (LT.cur) ltPend(LT.cur); clearTimeout(ltSaveTimer); ltSaveTimer = setTimeout(() => { const d = LT.pend?.d; if (d) ltSave(d, true); }, 1500); };
// 2.269.0 C (#3017): the form of draft d as it is now; kept in this browser until the server has it (a sign-in in between)
const LT_KEEP = id => 'tasks.ltpend.' + (S.me?.id || 0) + '.' + id;  // 2.269.0 review: per account; the 'tasks.' prefix is wiped at logout (clearLocal)
function ltPend(d) {
  if (!$('#lt-body') || d.status !== 'draft') return;
  LT.pend = {d, b: ltForm()};
  try { localStorage.setItem(LT_KEEP(d.id), JSON.stringify({base: d.updated_at || '', b: LT.pend.b})); } catch { /* full or private mode */ }
}
function lt_keepDrop(id) { try { localStorage.removeItem(LT_KEEP(id)); } catch { /* private mode */ } }
// a draft opened again: input kept from before (the sign-in page, a closed tab) is sent now when nobody saved since, else a hint
function lt_keepRestore(d) {
  let k = null; try { k = JSON.parse(localStorage.getItem(LT_KEEP(d.id)) || 'null'); } catch { /* broken */ }
  if (!k?.b || d.status !== 'draft') { if (k) lt_keepDrop(d.id); return; }
  if (Object.keys(k.b).every(x => String(k.b[x] ?? '') === String(d[x] ?? ''))) { lt_keepDrop(d.id); return; }  // arrived already
  if (k.base !== (d.updated_at || '')) { lt_keepDrop(d.id); toast(tr('Changed in the meantime')); return; }
  LT.pend = {d, b: k.b};
  ltSave(d, true).then(ok => { if (ok) { toast(tr('Saved')); ofcDraw(); } });
}
function lt_conflict(d, cur) {
  const el = $('#lt-err');
  if (!el || LT.cur !== d) { toast(tr('Changed in the meantime')); return; }  // the editor is gone: at least the hint
  el.innerHTML = `${esc(tr('Changed in the meantime'))} · ${esc(tr('Reload shows the saved version; your input here is not saved.'))} <button type="button" class="btn sm" data-lt-reload>${tr('Reload')}</button>`;
  $('[data-lt-reload]', el).addEventListener('click', () => { clearTimeout(ltSaveTimer); LT.pend = null; lt_keepDrop(d.id); LT.undo = null; LT.cur = cur; ofcDraw(); });
}
// the app goes to the background (phone): saved at once; the tab closes: a fetch with keepalive outlives it (lt_keep holds the
// input in case it does not arrive), a page shown again from the cache reloads the letter (its updated_at is the server's now)
document.addEventListener('visibilitychange', () => { if (document.hidden && LT.pend) ltSave(LT.pend.d, true); });
window.addEventListener('pagehide', () => {
  const p = LT.pend; if (!p) return;
  clearTimeout(ltSaveTimer); LT.pend = null; LT.hid = true;
  try { fetch(`/api/office/letters/${p.d.id}`, {method: 'PATCH', keepalive: true, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify(p.d.updated_at ? {...p.b, expect_updated_at: p.d.updated_at} : p.b)}).catch(() => {}); } catch { /* the kept copy stays */ }
});
window.addEventListener('pageshow', e => { if (e.persisted && LT.hid) { LT.hid = false; LT.cur = null; if (S.route.mod === 'office' && S.route.tab === 'letters') ofcDraw(); } });

// ---- dialogs
function ltNewModal() {
  const d = LT.data || {}, ts = d.templates || [];
  if (!ts.length) { ltCreate({}); return; }
  /** @type {any} */
  const md = modal(`<h3>${tr('New letter')}</h3>
    ${ofcRowF('lt-ntpl', tr('Template'), ofcSel('lt-ntpl', '', ts.map(t => [t.id, t.name]), tr('empty letter')))}
    ${ofcRowF('lt-ncl', tr('Client'), ofcSel('lt-ncl', '', (d.clients || []).map(c => [c.id, c.display_name || c.name]), tr('none')), tr('The variables of the template are filled from the client.'))}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Create')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const err = await ltCreate({template_id: +$('#lt-ntpl', md).value || null, client_id: +$('#lt-ncl', md).value || null});
    if (err) { const el = $('.aerr', md); if (el) el.textContent = err; } else md.remove();
  });
}
async function ltCreate(b) {
  try {
    const j = await api('POST', '/api/office/letters', b);
    if (j.unfilled_labels?.length) LT.miss[j.id] = j.unfilled_labels;
    LT.data = null; LT.cur = j; LT.undo = null; go(`office/letters/${j.id}`);
    toast(tr('Created'), async () => { await api('DELETE', `/api/office/letters/${j.id}`); ltReload(); go('office/letters'); });
    return '';
  } catch (x) { if (!b.template_id && !b.client_id) toast(x.message || tr('unknown')); return x.message || tr('unknown'); }
}
// 2.351.0 A (#2823): the folder of Correspondence the letter goes into when it is sent (the folders the person may add to,
// with their path; office_tree.js) -- filed as the letter's reference node, the PDF stays filed in the documents as before
function lt_foldRow() {
  const fs = typeof oft_get === 'function' ? (oft_get('letters')?.folders || []).filter(f => oft_canW(f)) : [];
  return fs.length ? ofcRowF('lt-sfold', tr('Folder'), ofcSel('lt-sfold', '', [['', tr('No folder')], ...fs.map(f => [String(f.id), oft_path('letters', f)])])) : '';
}
async function ltSentModal(d) {
  if (typeof oft_load === 'function' && !OFT.d.letters) await oft_load('letters');  // 2.351.0 A (#2823): the folders to pick
  /** @type {any} */
  const md = modal(`<h3>${tr('Mark as sent')}</h3><p class="muted">${esc(tr('The letter is then fixed and its PDF is filed in the documents.'))}</p>
    ${ofcRowF('lt-schan', tr('Sent by'), ofcSel('lt-schan', d.channel || 'post', Object.entries(LT_CH).map(([k, n]) => [k, tr(n)])))}
    <div class="row lt-strk" ${d.channel === 'registered' ? '' : 'hidden'}><label for="lt-strack">${esc(tr('Tracking number'))}</label>${ofcIn('lt-strack', d.tracking_no, {max: 120})}</div>
    ${ofcRowF('lt-sfu', tr('Follow-up after days'), `<input id="lt-sfu" inputmode="numeric" maxlength="3" value="${esc(String(d.followup_days || 14))}">`, tr('0 = no follow-up'))}
    ${lt_foldRow()}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${ic('send', 's')} ${tr('Mark as sent')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('change', e => { if (/** @type {any} */ (e.target).id === 'lt-schan') $('.lt-strk', md).hidden = /** @type {any} */ (e.target).value !== 'registered'; });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    b.disabled = true;
    try {
      const ch = $('#lt-schan', md).value;
      const j = await api('POST', `/api/office/letters/${d.id}/sent`, {channel: ch, tracking_no: ch === 'registered' ? $('#lt-strack', md).value : '', followup_days: Math.max(0, Math.min(365, +$('#lt-sfu', md).value || 0))});
      const fid = +($('#lt-sfold', md)?.value || 0);
      if (fid) { try { await api('POST', '/api/files/refs', {ref_kind: 'office_letter', ref_id: d.id, parent_id: fid}); } catch { /* shown; the letter is sent */ } }
      if (typeof oft_after === 'function') oft_after('letters');
      md.remove(); LT.cur = j; LT.data = null; ofcDraw();
      toast(tr('Sent and filed'));
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
// 2.357.0 C (#3158): the own signature: a picture (its light background made transparent) or drawn with finger / trackpad
const LT_PAD_W = 600, LT_PAD_H = 200;
/** a picture (data URL) -> PNG data URL with near-white pixels transparent, at most 1200 px wide */
function ltSigClear(url) {
  return new Promise((ok, no) => {
    const im = new Image();
    im.onload = () => {
      const sc = Math.min(1, 1200 / im.width), cv = document.createElement('canvas');
      cv.width = Math.max(1, Math.round(im.width * sc)); cv.height = Math.max(1, Math.round(im.height * sc));
      const cx = /** @type {CanvasRenderingContext2D} */ (cv.getContext('2d')); cx.drawImage(im, 0, 0, cv.width, cv.height);
      const px = cx.getImageData(0, 0, cv.width, cv.height), a = px.data;
      for (let i = 0; i < a.length; i += 4) { const l = (a[i] + a[i + 1] + a[i + 2]) / 3; if (l > 200) a[i + 3] = l > 235 ? 0 : Math.round(a[i + 3] * (235 - l) / 35); }
      cx.putImageData(px, 0, 0); ok(cv.toDataURL('image/png'));
    };
    im.onerror = () => no(new Error(tr('Please choose a PNG or JPEG picture')));
    im.src = url;
  });
}
/** the drawing field in el: pointer strokes in ink colour; -> {url(): PNG data URL or '' when empty, clear()} */
function ltSigPad(el) {
  el.innerHTML = `<canvas class="lt-pad" width="${LT_PAD_W}" height="${LT_PAD_H}" aria-label="${esc(tr('Draw your signature here'))}" style="width:100%;max-width:${LT_PAD_W}px;aspect-ratio:3/1;touch-action:none;background:#fff;border:1px solid var(--line, #ccd);border-radius:8px;cursor:crosshair"></canvas>`;
  const cv = /** @type {HTMLCanvasElement} */ ($('canvas', el)), cx = /** @type {CanvasRenderingContext2D} */ (cv.getContext('2d'));
  let drawn = false, last = null;
  cx.lineWidth = 3; cx.lineCap = 'round'; cx.lineJoin = 'round'; cx.strokeStyle = '#1a2340';
  const at = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * LT_PAD_W / r.width, (e.clientY - r.top) * LT_PAD_H / r.height]; };
  cv.addEventListener('pointerdown', e => { e.preventDefault(); try { cv.setPointerCapture?.(e.pointerId); } catch { /* not a live pointer */ } last = at(e); cx.beginPath(); cx.arc(last[0], last[1], 1.4, 0, 7); cx.fillStyle = cx.strokeStyle; cx.fill(); drawn = true; });
  cv.addEventListener('pointermove', e => { if (!last) return; const p = at(e); cx.beginPath(); cx.moveTo(last[0], last[1]); cx.lineTo(p[0], p[1]); cx.stroke(); last = p; });
  for (const t of ['pointerup', 'pointercancel', 'pointerleave']) cv.addEventListener(t, () => { last = null; });
  return {url: () => drawn ? cv.toDataURL('image/png') : '', clear: () => { cx.clearRect(0, 0, LT_PAD_W, LT_PAD_H); drawn = false; }};
}
/** opts.draw: open with the drawing field; done(profile) after saving */
function ltProfileModal(opts = {}) {
  const P = opts.profile || LT.data?.profile || {};
  let img = P.image || '', pad = null;
  const pic = () => img ? `<img src="${esc(img)}" alt="${esc(tr('Signature picture'))}" class="lt-sigimg">` : `<p class="muted">${tr('No signature picture yet.')}</p>`;
  /** @type {any} */
  const md = modal(`<h3>${tr('Signature')}</h3><p class="muted">${esc(tr('The picture is only printed in your own letters.'))}</p>
    ${ofcRowF('lt-pgreet', tr('Greeting'), ofcIn('lt-pgreet', P.greeting, {max: 120, ph: P.default_greeting}))}
    ${ofcRowF('lt-pname', tr('Name under the letter'), ofcIn('lt-pname', P.name, {max: 120, ph: P.default_name}))}
    <div class="row"><label>${tr('Signature picture')}</label><div class="lt-sigbox">${pic()}</div></div>
    <div class="lt-padbox" hidden></div>
    <div class="row lt-sigbtns"><label class="btn sm">${ic('upload', 's')} ${tr('Choose picture')}<input type="file" id="lt-pfile" accept="image/png,image/jpeg" hidden></label>
      <button type="button" class="btn sm" data-m="draw">${ic('edit', 's')} ${tr('Draw')}</button>
      <button type="button" class="btn sm ghost" data-m="padclr" hidden>${tr('Clear')}</button>
      <button type="button" class="btn sm ghost danger" data-m="rm" ${img ? '' : 'hidden'}>${tr('Remove')}</button></div>
    <p class="muted ofchint">${esc(tr('PNG or JPEG, at most 300 KB; a scan of your signature on a white background.'))} ${esc(tr('A light background is made transparent. Or draw it with your finger or trackpad.'))}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md), err = t => { const el = $('.aerr', md); if (el) el.textContent = t || ''; };
  let changed = false;
  md.addEventListener('change', e => {
    if (/** @type {any} */ (e.target).id !== 'lt-pfile') return;
    const f = /** @type {any} */ (e.target).files?.[0]; if (!f) return;
    if (!/^image\/(png|jpeg)$/.test(f.type)) { err(tr('Please choose a PNG or JPEG picture')); return; }
    if (f.size > 12 * 1024 * 1024) { err(tr('The picture is too large (at most {0} KB)', 300)); return; }  // 2.357.0 C (#3158): made smaller here
    const r = new FileReader();
    r.onload = async () => {
      try { img = await ltSigClear(String(r.result || '')); } catch (x) { err(x.message || ''); return; }
      if (img.length * 3 / 4 > 300 * 1024) { img = P.image || ''; err(tr('The picture is too large (at most {0} KB)', 300)); return; }
      changed = true; padOff(); $('.lt-sigbox', md).innerHTML = pic(); $('[data-m="rm"]', md).hidden = false; err('');
    };
    r.readAsDataURL(f);
  });
  const padOff = () => { pad = null; const pb = $('.lt-padbox', md); pb.hidden = true; pb.innerHTML = ''; $('[data-m="padclr"]', md).hidden = true; $('.lt-sigbox', md).hidden = false; };
  const padOn = () => { const pb = $('.lt-padbox', md); pb.hidden = false; pad = ltSigPad(pb); $('[data-m="padclr"]', md).hidden = false; $('.lt-sigbox', md).hidden = true; };
  if (opts.draw && !img) padOn();
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    if (b.dataset.m === 'draw') { padOn(); return; }
    if (b.dataset.m === 'padclr') { pad?.clear(); return; }
    if (b.dataset.m === 'rm') { img = ''; changed = true; padOff(); $('.lt-sigbox', md).innerHTML = pic(); b.hidden = true; return; }
    const old = {greeting: P.greeting || '', name: P.name || '', image: P.image || ''};
    if (pad?.url()) { img = pad.url(); changed = true; }
    try {
      const body = {greeting: $('#lt-pgreet', md).value, name: $('#lt-pname', md).value};
      if (changed && img) body.image = img;
      let j = await api('PUT', '/api/office/letters/profile', body);
      if (changed && !img && old.image) j = await api('DELETE', '/api/office/letters/profile/image');
      md.remove(); if (LT.data) LT.data.profile = j;
      if (opts.done) opts.done(j); else ofcDraw();
      toast(tr('Saved'), async () => {
        const o = await api('PUT', '/api/office/letters/profile', {greeting: old.greeting, name: old.name, ...(old.image ? {image: old.image} : {})});
        if (LT.data) LT.data.profile = old.image ? o : await api('DELETE', '/api/office/letters/profile/image');
        ofcDraw();
      });
    } catch (x) { err(x.message || ''); }
  });
}
async function ltArchive(d) {
  try {
    await api('DELETE', `/api/office/letters/${d.id}`); clearTimeout(ltSaveTimer); LT.data = null; LT.cur = null; go('office/letters');
    toast(tr('Deleted'), async () => { await api('POST', `/api/office/letters/${d.id}/restore`); LT.data = null; LT.cur = null; go(`office/letters/${d.id}`); });
  } catch (x) { toast(x.message || tr('unknown')); }
}
async function ltCopy(d) {
  try {
    const j = await api('POST', '/api/office/letters', {copy_of: d.id});
    LT.data = null; LT.cur = j; LT.undo = null; go(`office/letters/${j.id}`);
    toast(tr('Copy created'), async () => { await api('DELETE', `/api/office/letters/${j.id}`); LT.data = null; LT.cur = null; go(`office/letters/${d.id}`); });
  } catch (x) { toast(x.message || tr('unknown')); }
}
async function ltAsTemplate(d) {
  if (d.status === 'draft' && !await ltSave(d, true)) return;
  try {
    const t = await api('POST', `/api/office/letters/${d.id}/template`, {});
    if (LT.data) LT.data = null;
    toast(tr('Template “{0}” added', t.name), async () => { await api('DELETE', `/api/office/doc-templates/${t.id}`); LT.data = null; ofcDraw(); });
    ofcDraw();
  } catch (x) { toast(x.message || tr('unknown')); }
}

// ---- events
document.addEventListener('click', async e => {
  if (!/** @type {any} */ (e.target).closest?.('.lt-rc')) { const s = $('#lt-sug'); if (s && !s.hidden) s.hidden = true; }  // the suggestions close outside
  const b = /** @type {any} */ (e.target).closest?.('[data-lt]'); if (!b || b.tagName === 'INPUT' || b.tagName === 'SELECT') return;
  if (b.closest('.modal')) return;  // letters have no data-lt in dialogs; the list dialog's list tags (agents.js) use data-lt too
  const a = b.dataset.lt, d = S.route.tab === 'letters' && S.route.id && LT.cur?.id === S.route.id ? LT.cur : null;
  if (a === 'pdf') {  // a draft is saved first, then the PDF opens (the viewer when there is one)
    e.preventDefault();
    if (d && d.status === 'draft' && !await ltSave(d, true)) return;
    const u = b.getAttribute('href'), name = (d?.subject || 'letter') + '.pdf';
    if (typeof pdfView === 'function') pdfView({url: u, name, dlUrl: u + '?dl=1'}); else window.open(u, '_blank', 'noopener');
    return;
  }
  e.preventDefault();
  if (a === 'new') ltNewModal();
  else if (a === 'profile') ltProfileModal();
  else if (a === 'open') { LT.cur = null; LT.undo = null; go(`office/letters/${b.dataset.id}`); }
  else if (a === 'back') { if (d && d.status === 'draft') { clearTimeout(ltSaveTimer); await ltSave(d, true); } LT.data = null; go('office/letters'); }
  else if (a === 'rc') { const x = LT.rc[+b.dataset.i]; if (x) ltRcPick(x); }
  else if (a === 'save' && d) ltSave(d);
  else if (a === 'sent' && d) {
    clearTimeout(ltSaveTimer);
    if (!await ltSave(d, true)) return;
    // 2.296.0 C (#3165): what the template could not fill is named once more before the letter is fixed
    if (LT.miss[d.id] && !await askConfirm(tr('Mark as sent'), tr('Missing details (left out in the PDF): {0}', LT.miss[d.id].join(', ')), {ok: tr('Continue'), cancel: tr('Back')})) return;
    ltSentModal(d);
  }
  else if (a === 'delivered' && d) {
    try { LT.cur = await api('POST', `/api/office/letters/${d.id}/delivered`); LT.data = null; ofcDraw(); toast(tr('Marked as delivered'), async () => { LT.cur = await api('DELETE', `/api/office/letters/${d.id}/delivered`); LT.data = null; ofcDraw(); }); }
    catch (x) { toast(x.message || tr('unknown')); }
  } else if (a === 'copy' && d) ltCopy(d);
  else if (a === 'arch' && d) ltArchive(d);
  else if (a === 'more' && d) {
    menu(b, [
      {label: tr('Edit a copy'), icon: 'copy', fn: () => ltCopy(d)},
      {label: tr('Save as template'), icon: 'file', fn: () => ltAsTemplate(d)},
      {label: tr('Download PDF'), icon: 'download', fn: async () => { if (d.status !== 'draft' || await ltSave(d, true)) location.assign(ltPdfUrl(d, true)); }},
      {label: tr('Delete'), icon: 'archive', cls: 'danger', fn: () => ltArchive(d)}]);
  }
});
document.addEventListener('change', e => {
  const x = /** @type {any} */ (e.target), id = x.id;
  if (id === 'lt-fs') { LT.fStatus = x.value; ofcDraw(); }
  else if (id === 'lt-fc') { LT.fClient = x.value; ofcDraw(); }
  else if (S.route.mod === 'office' && S.route.tab === 'letters' && S.route.id && id.startsWith('lt-') && !x.closest('.modal')) {
    if (id === 'lt-channel') { const t = $('.lt-trk'); if (t) t.hidden = x.value !== 'registered'; }
    if (id === 'lt-sign_image' && x.checked && !LT.data?.profile?.has_image) {  // 2.357.0 C (#3158): no picture yet -> set it up first
      x.checked = false;
      ltProfileModal({draw: true, done: j => { if (LT.data) LT.data.profile = j; const el = $('#lt-sign_image'); if (j.has_image && el) { el.checked = true; ltSaveSoon(); } }});
      return;
    }
    if (id !== 'lt-rsearch') ltSaveSoon();
  }
});
document.addEventListener('input', e => {
  const x = /** @type {any} */ (e.target);
  if (x.id === 'lt-q') { LT.q = x.value; ofcDraw(); return; }
  if (S.route.mod !== 'office' || S.route.tab !== 'letters' || !S.route.id || !x.id?.startsWith('lt-') || x.closest('.modal')) return;
  if (x.id === 'lt-rsearch') { if (x.value.trim()) ltRcSoon(x.value.trim()); else { const box = $('#lt-sug'); if (box) box.hidden = true; } return; }
  ltSaveSoon();
});
document.addEventListener('focusin', e => { if (/** @type {any} */ (e.target).id === 'lt-rsearch' && !/** @type {any} */ (e.target).value.trim()) ltRcLoad(''); });
