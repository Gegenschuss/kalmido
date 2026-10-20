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
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const AST_KINDS = ['office_text', 'doc_summary', 'report'];
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
  const title = {office_text: tr('Draft text with an agent'), doc_summary: tr('Summarise with an agent'), report: tr('Word the report with an agent')}[kind];
  const agSel = ags.length > 1 ? `<div class="row"><label for="ast-agent">${tr('Agent')}</label><select id="ast-agent">${ags.map(a => `<option value="${a.id}" ${a.limit_reached ? 'disabled' : ''}>${esc(a.name)}${a.limit_reached ? ' · ' + esc(tr('usage limit reached')) : ''}</option>`).join('')}</select></div>`
    : `<p class="muted">${esc(tr('{0} writes a draft. You get a notification when it is ready.', ags[0].name))}</p>`;
  const field = kind === 'office_text' ? `<div class="row"><label for="ast-field">${tr('Text')}</label><select id="ast-field"><option value="intro">${tr('Introduction')}</option><option value="closing">${tr('Closing')}</option></select></div>` : '';
  const hint = {office_text: tr('The agent gets the document without purchase prices, the client and the current text. Nothing is sent.'),
    doc_summary: tr('The agent gets what it may read of this document anyway. Nothing is changed before you take it over.'),
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
    toast(tr('Sent to {0}: you get a notification when the proposal is ready', (ags.find(a => a.id === body.agent_id) || ags[0]).name));
  });
  setTimeout(() => ast$('#ast-wish', md)?.focus(), 50);
}

// ---- the proposal sheet (agents.js propDraw / propApply)
/** @param {any} v */
function ast_draw(v) {
  const p = v.proposal || {}, t = v.target || {}, kind = v.kind;
  const what = kind === 'office_text' ? (v.input?.field === 'closing' ? tr('Closing') : tr('Introduction')) + (t.number ? ' · ' + t.number : '')
    : kind === 'doc_summary' ? tr('Summary') + (t.name ? ' · ' + t.name : '') : tr('Status report');
  const gone = t.gone || t.editable === false;
  const how = kind === 'report' ? tr('Taking it over shows this text in the status report dialog instead of the fixed text; copy or share it from there. Nothing goes to the client.')
    : kind === 'doc_summary' ? tr('Taking it over saves the text as the summary of the document, as you. One step, undo takes it back.')
    : tr('Taking it over replaces the text of the draft, as you. Nothing is sent. One step, undo takes it back.');
  const main = `<div class="ast-head"><span class="muted">${esc(tr('Proposal by {0}', v.agent.name))}</span> · <b>${esc(what)}</b></div>
    <textarea id="ast-text" class="ast-text" rows="${kind === 'report' ? 12 : 7}" aria-label="${esc(tr('Text'))}">${esc(p.text || '')}</textarea>
    ${t.text && kind !== 'report' ? `<details class="ast-was"><summary class="muted">${esc(tr('Current text'))}</summary><div class="muted">${esc(t.text)}</div></details>` : ''}
    ${gone ? `<div class="shint">${esc(kind === 'office_text' ? tr('The document is finalised or sent: the text can no longer be taken over.') : tr('This is no longer available to you.'))}</div>` : ''}
    <div class="shint keep">${esc(how)}</div>`;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Discard'))}">👎 ${esc(tr('Discard'))}</button><span class="spacer"></span>
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
const ast_toast = v => v.kind === 'report' ? tr('Report text taken over') : v.kind === 'doc_summary' ? tr('Summary saved') : tr('Text taken over into the draft');
/** @param {any} v @param {boolean} [applied] */
function ast_after(v, applied) {  // the open view follows apply / undo / redo
  const id = v.target?.doc_id;
  if (v.kind === 'office_text' && id && typeof ofdLoadDoc === 'function' && typeof OFD === 'object' && OFD.doc?.id === id) ofdLoadDoc(id, true);
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
