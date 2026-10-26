// @ts-check
/* Kalmido web client: 2.126.1 A (#2123 #2124) -- texts worded by a connected agent, on request. Kalmido itself calls no model:
   the person asks one of their agents, the agent gets the event job_request with exactly the data it may read and answers
   with a proposal. Three places ask:
   - an office document draft (quotation, invoice, reminder), section "Introduction and closing": "Draft text with an agent"
     (only when an agent of the office area may draft and the area lets agents read office data, and the draft can be changed);
   - a document / receipt (document sheet): "Summarise with an agent" (the same office switches, and the agent sees the file);
   - the status report dialog of a list: "Word the report with an agent" (a list shared with the agent).
   The proposal sheet of agents.js (propOpen / propDraw) shows for these kinds the text in an editable field with Copy,
   Discard and Take over. Taking over writes the field as the person (one undo step); the report text is kept with the job
   and replaces the fixed text in the status report dialog. Nothing is sent to a client. Server: kalmido/agents/asstprop.py.
   2.299.0 E (#3194): receipt_read -- "Read with an agent" on a document / receipt (the line of the recognised values,
   receipts.js rx_html): the agent's values show as "Read by the agent (name)" with Take over / Discard (the proposal's apply /
   discard, one undo step), the checks and a suggested bank booking (matched by the person). Server: kalmido/agents/rcread.py.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const AST_KINDS = ['office_text', 'doc_summary', 'report', 'receipt_read'];  // 2.299.0 E (#3194): + receipt_read
const AST = {/** @type {Record<string, any[]>} */ agents: {}, /** @type {Record<string, boolean>} */ busy: {}};
/** @param {any} v */
const ast_is = v => AST_KINDS.includes(v?.kind);
/** @param {string} s @param {any} [r] @returns {any} */
const ast$ = (s, r) => (r || document).querySelector(s);  // $ / $$ typed loosely (dialogs as root)
/** @param {string} s @param {any} [r] @returns {any[]} */
const ast$$ = (s, r) => [...(r || document).querySelectorAll(s)];

// ---- who may be asked (GET /api/proposals/agents?kind=...), per document / list, cached for the open view
/** @param {string} kind @param {string} q @returns {any[] | null} */
function ast_agents(kind, q) {
  const k = kind + '?' + q;
  if (k in AST.agents) return AST.agents[k];
  if (!AST.busy[k]) {
    AST.busy[k] = true;
    rawFetch('GET', `/api/proposals/agents?kind=${kind}&${q}`).then(j => { AST.agents[k] = j.agents || []; }).catch(() => { AST.agents[k] = []; })
      .finally(() => { AST.busy[k] = false; ast_redraw(kind, q); });
  }
  return null;
}
/** @param {string} kind @param {string} q */
function ast_redraw(kind, q) {
  ast$$(`[data-ast-slot="${kind}?${q}"]`).forEach(el => { el.outerHTML = ast_btnHtml(kind, q, el.dataset.astLabel || ''); });
}
/** @param {string} kind @param {string} q @param {string} label */
function ast_btnHtml(kind, q, label) {
  const ags = ast_agents(kind, q);
  const btn = ags?.length ? `<button type="button" class="btn sm ast-ask" data-ast-ask="${kind}" data-ast-q="${esc(q)}">${ic('bot', 's')}<span>${esc(label)}</span></button>` : '';
  return `<span class="ast-slot" data-ast-slot="${kind}?${esc(q)}" data-ast-label="${esc(label)}">${btn}</span>`;
}
const ast_forget = (/** @type {string} */ kind, /** @type {string} */ q) => { delete AST.agents[kind + '?' + q]; };

// office_docs.js (section "Introduction and closing"): the button under the two texts
/** @param {any} d */
function ast_ofdBtn(d) {
  if (!d || !d.can_edit || !['offer', 'invoice', 'reminder'].includes(d.kind)) return '';
  return `<div class="row ast-row">${ast_btnHtml('office_text', 'doc_id=' + d.id, tr('Draft text with an agent'))}</div>`;
}
// docs.js (the document sheet): the summary taken over + the button
/** @param {any} d */
function ast_docSlot(d) {
  if (!d) return '';
  const sum = d.summary ? `<div class="ast-sum"><span class="muted">${esc(tr('Summary'))}</span><div class="md">${renderMd(d.summary, true)}</div></div>` : '';
  const btn = d.role && d.role !== 'view' ? `<div class="ast-row">${ast_btnHtml('doc_summary', 'doc_id=' + d.id, tr('Summarise with an agent'))}</div>` : '';
  return sum || btn ? `<div class="ast-doc">${sum}${btn}</div>` : '';
}
// projects.js (the status report dialog): the button in the foot; a text taken over replaces the fixed text
/** @param {any} md @param {any} st @param {any} j @param {number} lid */
function ast_rpt(md, st, j, lid) {
  st.ast = {lid, from: j.from, to: j.to, fixed: j.markdown, agent: j.agent_text || null, useFixed: false};
  const k = 'list_id=' + lid;
  AST.agents['report?' + k] = j.agents || [];
  const foot = ast$('.foot', md), old = ast$('[data-ast-slot]', foot);
  const html = ast_btnHtml('report', k, tr('Word the report with an agent'));
  if (old) old.outerHTML = html; else foot?.insertAdjacentHTML('afterbegin', html);
  ast_rptShow(md, st);
}
/** @param {any} md @param {any} st */
function ast_rptShow(md, st) {
  const a = st.ast, prev = ast$('#rpt-prev', md); if (!a || !prev) return;
  const use = a.agent && !a.useFixed;
  st.md = use ? a.agent.text : a.fixed;
  prev.innerHTML = renderMd(st.md, true);
  let n = ast$('.ast-rptnote', md);
  if (!a.agent) { n?.remove(); return; }
  const html = `<p class="ast-rptnote muted">${esc(use ? tr('The text an agent worded (you took it over).') : tr('The fixed text.'))}
    <button type="button" class="linkbtn" data-ast-rpt="toggle">${esc(use ? tr('Show the fixed text') : tr('Show the agent’s text'))}</button></p>`;
  if (n) n.outerHTML = html; else prev.insertAdjacentHTML('beforebegin', html);
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target)?.closest?.('[data-ast-rpt]'); if (!b) return;
  const md = b.closest('.modal'), st = md?._rptSt; if (!st?.ast) return;
  st.ast.useFixed = !st.ast.useFixed; ast_rptShow(md, st);
});

// ---- the request dialog: agent (a choice when there are several), field (office texts), a short wish
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target)?.closest?.('[data-ast-ask]'); if (!b) return;
  e.preventDefault();
  ast_ask(b.dataset.astAsk, b.dataset.astQ, b);
});
/** @param {string} kind @param {string} q @param {any} src */
function ast_ask(kind, q, src) {
  const ags = AST.agents[kind + '?' + q] || []; if (!ags.length) return;
  const id = +(q.split('=')[1] || 0), rptMd = kind === 'report' ? src.closest('.modal') : null, rs = rptMd?._rptSt;
  const title = {office_text: tr('Draft text with an agent'), doc_summary: tr('Summarise with an agent'), report: tr('Word the report with an agent'),
    receipt_read: tr('Read with an agent')}[kind];
  const agSel = ags.length > 1 ? `<div class="row"><label for="ast-agent">${tr('Agent')}</label><select id="ast-agent">${ags.map(a => `<option value="${a.id}" ${a.limit_reached ? 'disabled' : ''}>${esc(a.name)}${a.limit_reached ? ' · ' + esc(tr('usage limit reached')) : ''}</option>`).join('')}</select></div>`
    : `<p class="muted">${esc(tr('{0} writes a draft. You get a notification when it is ready.', ags[0].name))}</p>`;
  const field = kind === 'office_text' ? `<div class="row"><label for="ast-field">${tr('Text')}</label><select id="ast-field"><option value="intro">${tr('Introduction')}</option><option value="closing">${tr('Closing')}</option></select></div>` : '';
  const hint = {office_text: tr('The agent gets the document without purchase prices, the client and the current text. Nothing is sent.'),
    doc_summary: tr('The agent gets what it may read of this document anyway. Nothing is changed before you take it over.'),
    receipt_read: tr('The agent reads the file it may see anyway, where it runs. Kalmido sends nothing out. Nothing is changed before you take the values over.'),
    report: tr('The agent gets the status report of this period (without comments, notes and names; your tracked hours only as a total). Nothing goes to the client.')}[kind];
  const md = modal(`<h3>${ic('bot', 's')} ${esc(title)}</h3>${agSel}${field}
    <div class="row"><label for="ast-wish">${tr('Your wish')}</label></div><textarea id="ast-wish" rows="2" maxlength="500" placeholder="${esc(tr('optional, e.g. friendly and short'))}"></textarea>
    <p class="muted ast-hint">${esc(hint)}</p><div class="calerr" role="alert" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${ic('send', 's')} ${tr('Ask')}</button></div>`);
  md.classList.add('ast-askm');
  md.addEventListener('click', async ev => {
    const x = /** @type {any} */ (ev.target)?.closest?.('[data-m]'); if (!x) return;
    if (x.dataset.m === 'close') { md.remove(); return; }
    /** @type {any} */
    const body = {kind, agent_id: +(/** @type {any} */ (ast$('#ast-agent', md))?.value || ags[0].id), wish: /** @type {any} */ (ast$('#ast-wish', md)).value.trim() || null};
    if (kind === 'report') { body.list_id = id; if (rs?.ast) { body.from = rs.ast.from; body.to = rs.ast.to; } body.lang = S.settings?.lang || 'en'; }
    else body.doc_id = id;
    if (kind === 'office_text') body.field = /** @type {any} */ (ast$('#ast-field', md)).value;
    x.disabled = true;
    try { await calReq('POST', '/api/proposals', body); } catch (er) { const el = ast$('.calerr', md); el.textContent = er.message; el.hidden = false; x.disabled = false; return; }
    md.remove();
    toast(tr('Sent to {0} – you will be notified.', (ags.find(a => a.id === body.agent_id) || ags[0]).name));
  });
  setTimeout(() => ast$('#ast-wish', md)?.focus(), 50);
}

// ---- the proposal sheet (agents.js propDraw / propApply)
/** @param {any} v */
function ast_draw(v) {
  if (v.kind === 'receipt_read') return rcr_draw(v);  // 2.299.0 E (#3194)
  const p = v.proposal || {}, t = v.target || {}, kind = v.kind;
  const what = kind === 'office_text' ? (v.input?.field === 'closing' ? tr('Closing') : tr('Introduction')) + (t.number ? ' · ' + t.number : '')
    : kind === 'doc_summary' ? tr('Summary') + (t.name ? ' · ' + t.name : '') : tr('Status report');
  const gone = t.gone || t.editable === false;
  const how = kind === 'report' ? tr('Taking it over shows this text in the status report dialog instead of the fixed text; copy or share it from there. Nothing goes to the client.')
    : kind === 'doc_summary' ? tr('Taking it over saves the text as the summary of the document, as you. Undo possible.')
    : tr('Taking it over replaces the text of the draft, as you. Nothing is sent. Undo possible.');
  const main = `<div class="ast-head"><span class="muted">${esc(tr('Proposal by {0}', v.agent.name))}</span> · <b>${esc(what)}</b></div>
    <textarea id="ast-text" class="ast-text" rows="${kind === 'report' ? 12 : 7}" aria-label="${esc(tr('Text'))}">${esc(p.text || '')}</textarea>
    ${t.text && kind !== 'report' ? `<details class="ast-was"><summary class="muted">${esc(tr('Current text'))}</summary><div class="muted">${esc(t.text)}</div></details>` : ''}
    ${gone ? `<div class="shint">${esc(kind === 'office_text' ? tr('The document is finalised or sent: the text can no longer be taken over.') : tr('This is no longer available to you.'))}</div>` : ''}
    <div class="shint keep">${esc(how)}</div>`;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Discard'))}">${thumbIc(false)} ${esc(tr('Discard'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button><button class="btn" data-ast-copy="1">${ic('copy', 's')} ${esc(tr('Copy'))}</button>
    <button class="btn pri" data-pp="apply" ${gone ? 'disabled' : ''}>${ic('check', 's')} ${esc(tr('Take over'))}</button>`;
  return {main, foot};
}
/** @param {any} P @param {any} q */
function ast_apply(P, q) {
  const v = ast$('#ast-text', P.md)?.value;
  if (typeof v === 'string' && v !== (P.v.proposal?.text || '')) q.edits = {0: {text: v}};
}
document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target)?.closest?.('[data-ast-copy]'); if (!b) return;
  const v = ast$('#ast-text', b.closest('.modal'))?.value || '';
  try { await navigator.clipboard.writeText(v); toast(tr('Copied')); } catch { toast(tr('Could not copy')); }
});
/** @param {any} v */
const ast_toast = v => v.kind === 'report' ? tr('Report text taken over') : v.kind === 'doc_summary' ? tr('Summary saved')
  : v.kind === 'receipt_read' ? tr('Values taken over') : tr('Text taken over into the draft');
/** @param {any} v @param {boolean} [applied] */
function ast_after(v, applied) {  // the open view follows apply / undo / redo
  const id = v.target?.doc_id;
  if (v.kind === 'office_text' && id && typeof ofdLoadDoc === 'function' && typeof OFD === 'object' && OFD.doc?.id === id) ofdLoadDoc(id, true);
  if (v.kind === 'receipt_read' && id) rcr_refresh(id);  // 2.299.0 E (#3194)
  if (v.kind === 'doc_summary' && id && typeof DC === 'object' && DC.doc?.id === id && typeof dc_load === 'function') {
    rawFetch('GET', `/api/docs/${id}`).then(d => { if (DC.doc?.id === id) { DC.doc = d; dc_mdDraw(ast$('.dc-md')); } }).catch(() => {});
  }
  if (v.kind !== 'report') return;
  const open = ast$$('.rptmodal');
  open.forEach(md => md._rptLoad?.());
  const rp = v.input?.report || {};  // taken over: the text is used in the status report dialog, so it opens there (same period)
  if (applied && !open.length && typeof rptModal === 'function' && rp.list?.id) rptModal(rp.list.id, {from: rp.from, to: rp.to});
}
/** @param {any} v @param {any} e */
function ast_hist(v, e) {
  const u = e.undo, r = e.redo;
  e.undo = async () => { const x = await u(); ast_after(v); return x; };
  e.redo = async () => { const x = await r(); ast_after(v); return x; };
}

// ---- 2.299.0 E (#3194): an agent reads a receipt (kind receipt_read)
const RCR_FIELDS = /** @type {Record<string, string>} */ ({amount: 'Amount', vat_pct: 'VAT rate', sender: 'Sender', date: 'Date', category: 'Category'});
/** @param {any} v @param {string} [cur] */
const rcr_money = (v, cur) => v == null || v === '' ? '' : typeof dc_money === 'function' ? dc_money(v, cur) : `${fmtNum(+v, 2)} ${cur || ''}`.trim();
/** @param {any} p  the values the agent read -> "supplier · no. · date · net · VAT 19 % · gross" */
function rcr_parts(p) {
  const cur = p.currency || '';
  return [p.supplier && `<b>${esc(p.supplier)}</b>`, p.invoice_no && esc(tr('No. {0}', p.invoice_no)), p.date && esc(fmtDateLoc(p.date)),
    p.net && `${tr('net')} ${esc(rcr_money(p.net, cur))}`, p.vat_pct && esc(tr('VAT {0} %', p.vat_pct)), p.gross && `${tr('gross')} ${esc(rcr_money(p.gross, cur))}`,
    p.category && esc(p.category)].filter(Boolean);
}
/** @param {any[]} ch */
const rcr_checksHtml = ch => ch?.length ? `<ul class="rcr-checks">${ch.map(x => `<li class="shint${x.level === 'warn' ? ' cnote' : ''}">${esc(x.text)}</li>`).join('')}</ul>` : '';
/** @param {any} b @param {number} id */
function rcr_bankHtml(b, id) {
  if (!b) return '';
  const what = `${esc(fmtDateLoc(b.day))} · ${esc(rcr_money(b.amount, b.currency))}${b.counterpart ? ' · ' + esc(b.counterpart) : ''}`;
  return `<div class="rcr-bank"><span><span class="muted">${tr('Matching bank booking')}:</span> ${what}</span>
    ${b.this ? `<span class="muted">${tr('Matched')}</span>` : b.matched ? `<span class="muted">${tr('Matched with something else')}</span>`
    : `<button type="button" class="btn sm" data-rcr="bank:${+b.id}:${id}">${tr('Match')}</button>`}</div>`;
}
// receipts.js rx_html: the line under the recognised values -- the agent is reading / its values / the button
/** @param {any} d */
function rcr_html(d) {
  if (!d?.id || d.role === 'view') return '';
  const a = d.agent_read;
  if (!a) return `<div class="ast-row rcr-ask">${ast_btnHtml('receipt_read', 'doc_id=' + d.id, tr('Read with an agent'))}</div>`;
  if (a.state !== 'ready') return `<div class="rx-sug rcr-wait" role="status"><span class="muted">${esc(tr('{0} is reading the receipt …', a.agent?.name || ''))}</span></div>`;
  const p = a.values || {}, parts = rcr_parts(p);
  return `<div class="rx-sug rcr-sug" role="group" aria-label="${esc(tr('Read by the agent ({0})', a.agent?.name || ''))}">
    <span><span class="muted">${esc(tr('Read by the agent ({0})', a.agent?.name || ''))}:</span> ${parts.join(' · ') || esc(tr('no values'))}</span>
    <span class="rc-acts"><button type="button" class="btn sm" data-rcr="discard:${+a.job}:${d.id}">${tr('Discard')}</button><button type="button" class="btn sm pri" data-rcr="apply:${+a.job}:${d.id}">${tr('Take over')}</button></span></div>
    ${rcr_checksHtml(a.checks)}${rcr_bankHtml(a.bank, d.id)}`;
}
// the proposal sheet (agents.js propDraw): the values, the positions (shown only), what Take over sets, the checks
/** @param {any} v */
function rcr_draw(v) {
  const p = v.proposal || {}, t = v.target || {}, gone = t.gone || t.editable === false, cur = p.currency || '';
  const row = (/** @type {string} */ l, /** @type {any} */ x) => x ? `<tr><th scope="row">${esc(l)}</th><td>${x}</td></tr>` : '';
  const rates = (p.vat_rates || []).map((/** @type {any} */ r) => `${esc(tr('VAT {0} %', r.pct))}${r.net ? ' · ' + tr('net') + ' ' + esc(rcr_money(r.net, cur)) : ''}${r.vat ? ' · ' + esc(rcr_money(r.vat, cur)) : ''}`).join('<br>');
  const pos = (p.positions || []).length ? `<details class="rcr-pos"><summary>${esc(trn('{0} position', '{0} positions', p.positions.length))}</summary>
    <table class="rcr-tab"><tbody>${p.positions.map((/** @type {any} */ x) => `<tr><td>${esc(x.text)}</td><td>${x.qty ? esc(fmtNum(+x.qty, 3)) + ' ×' : ''}</td><td>${esc(rcr_money(x.net, cur))}</td><td>${x.vat_pct ? esc(tr('VAT {0} %', x.vat_pct)) : ''}</td></tr>`).join('')}</tbody></table>
    <p class="muted">${esc(tr('Positions are only shown: a receipt has no field for them.'))}</p></details>` : '';
  const main = `<div class="ast-head"><span class="muted">${esc(tr('Proposal by {0}', v.agent.name))}</span> · <b>${esc(tr('Read receipt'))}${t.name ? ' · ' + esc(t.name) : ''}</b></div>
    <table class="rcr-tab"><tbody>${row(tr('Supplier'), esc(p.supplier || ''))}${row(tr('VAT ID'), esc(p.vat_id || ''))}${row(tr('Tax number'), esc(p.tax_no || ''))}
    ${row(tr('Invoice number'), esc(p.invoice_no || ''))}${row(tr('Date'), esc(fmtDateLoc(p.date || '')))}${row(tr('net'), esc(rcr_money(p.net, cur)))}
    ${row(tr('VAT'), esc(rcr_money(p.vat, cur)))}${row(tr('gross'), esc(rcr_money(p.gross, cur)))}${row(tr('VAT rate'), p.vat_pct ? esc(tr('VAT {0} %', p.vat_pct)) : '')}
    ${row(tr('VAT rates'), rates)}${row(tr('Category'), esc(p.category || ''))}${row(tr('Account'), esc(p.account || ''))}</tbody></table>${pos}
    ${rcr_checksHtml(t.checks)}${rcr_bankHtml(t.bank, t.doc_id)}
    ${gone ? `<div class="shint">${esc(tr('This is no longer available to you.'))}</div>` : ''}
    <div class="shint keep">${esc(t.new?.length ? tr('Taking it over sets {0} and keeps the values with the document, as you. One step, undo takes it back.', t.new.map((/** @type {string} */ k) => tr(RCR_FIELDS[k] || k)).join(', '))
      : tr('Taking it over keeps the values with the document (invoice number, VAT ID), as you. One step, undo takes it back.'))}</div>`;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Discard'))}">${thumbIc(false)} ${esc(tr('Discard'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button>${t.doc_id ? `<a class="btn" href="#docs/${+t.doc_id}">${esc(tr('Open document'))}</a>` : ''}
    <button class="btn pri" data-pp="apply" ${gone ? 'disabled' : ''}>${ic('check', 's')} ${esc(tr('Take over'))}</button>`;
  return {main, foot};
}
/** @param {number} id  the open document sheet / receipt sheet / receipt box follow a take-over, an undo, a discard */
async function rcr_refresh(id) {
  if (typeof DC === 'object' && DC.doc?.id === id) {
    try { const d = await rawFetch('GET', `/api/docs/${id}`); if (DC.doc?.id === id) { DC.doc = d; dc_mdDraw(ast$('.dc-md')); if (typeof dc_load === 'function') dc_load(); } } catch { /* offline */ }
  }
  if (typeof RC === 'object' && RC.id === id && typeof rc_load === 'function') rc_load();
  if (typeof bkRxAfter === 'function') bkRxAfter(id);
}
document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target)?.closest?.('[data-rcr]'); if (!b) return;
  const [act, a1, a2] = b.dataset.rcr.split(':'), x = +a1, id = +a2;
  b.disabled = true;
  try {
    if (act === 'apply') {
      await calReq('POST', `/api/proposals/${x}/apply`, {select: ['0']});
      const label = tr('Values taken over');
      histToast(label, histAdd({label, undo: async () => { await calReq('POST', `/api/proposals/${x}/undo`); await rcr_refresh(id); return {}; },
        redo: async () => { await calReq('POST', `/api/proposals/${x}/redo`); await rcr_refresh(id); return {}; }}));
    } else if (act === 'discard') {
      await calReq('POST', `/api/proposals/${x}/discard`);
      toast(tr('Suggestion discarded'));
    } else if (act === 'bank') {  // the bank's own match (office admins), its undo the bank's unmatch
      await calReq('POST', `/api/office/bank/tx/${x}/match`, {kind: 'receipt', id});
      const label = tr('Booking matched');
      histToast(label, histAdd({label, undo: async () => { await calReq('POST', `/api/office/bank/tx/${x}/unmatch`); await rcr_refresh(id); return {}; },
        redo: async () => { await calReq('POST', `/api/office/bank/tx/${x}/match`, {kind: 'receipt', id}); await rcr_refresh(id); return {}; }}));
    }
  } catch (er) { toast(/** @type {any} */ (er)?.message || tr('unknown')); b.disabled = false; return; }
  await rcr_refresh(id);
});
