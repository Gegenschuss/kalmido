/* Kalmido web client: the built-in assistant (2.75.0, #1411).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.75.0 (#1411): the built-in assistant
// The one way Kalmido itself calls a language model: the operator configures an OpenAI-compatible endpoint, every person
// switches it on for themselves and ticks the lists it may read (Settings > Assistant). Without a configuration
// /api/state has no "assistant" and nothing of this file shows. Text results (summary, reply draft) open in a small dialog
// (Copy, Add as comment); everything else comes as a proposal (the existing proposal dialog: Apply / Discard / Undo), so the
// assistant never changes anything by itself. Entry points: the task detail's menu, the basket header, Today's "…" menu. Its own agents stay what they are ("Agents").
const ASST_KINDS = {summary: N_('Summary'), draft: N_('Reply draft'), extract: N_('Extract tasks'), tags: N_('Tags and due date'), triage: N_('Basket sort'), dayplan: N_('Day plan'), lists: N_('Shared projects')};
const ASST_ST = {ok: N_('Done|assistant'), error: N_('Error'), timeout: N_('Took too long'), denied: N_('Refused'), truncated: N_('Shortened')};
const ASST_MAX = 30;  // tasks per basket sort (server limit)
const asst_avail = () => !!S.assistant && !!S.me && !S.me.kid;  // configured; children never (the server says off too)
const asst_ready = () => asst_avail() && !!S.assistant.on;
const asst_shared = lid => (S.assistant?.list_ids || []).includes(+lid);
const asst_myInbox = () => S.lists.find(l => l.is_inbox && isOwner(l));
const asst_canList = l => !!l && !l.is_inbox && !l.archived && l.life !== 'health' && l.life !== 'budget' && !l.e2e  // vorint: no budget (2.72), no list with the lock (2.64a)
  && l.owner_id === S.me?.id;  // 2.148.1 D (#2489): only own lists
const asst_taskOk = t => { const l = t && listById(t.list_id); return !!l && (asst_shared(l.id) || (l.is_inbox && isOwner(l))); };
const asst_onSync = v => { if (!S.assistant) return; S.assistant.on = String(v) === '1'; render(); };  // settings switch + its undo

// one call; the button stays locked while the model works (the server's time limit, 60 s by default)
async function asst_run(body, btn) {
  if (asst_run.busy) { toast(tr('Asking the assistant…')); return null; }
  asst_run.busy = true;
  if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.classList.add('asstbusy'); }
  const wait = tr('Asking the assistant…');
  toast(wait, null, 90000);
  try { return await calReq('POST', '/api/assistant/run', body); }
  catch (x) { toast(x.message || tr('The assistant is not reachable right now')); return null; }
  finally {
    asst_run.busy = false;
    if (btn) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.classList.remove('asstbusy'); }
    const el = $('#toast'); if (el && el.textContent === wait) el.classList.add('hidden');
  }
}
async function asst_go(body, btn) {  // a proposal kind: opens the proposal dialog, a text kind: the text dialog
  const r = await asst_run(body, btn); if (!r) return;
  if (r.job_id) { propOpen(r.job_id); return; }
  asst_textModal(r, body.task_id);
}

// ---- text result: Copy / Add as comment (one undo step: the comment goes again)
function asst_textModal(r, tid) {
  const t = tid ? taskById(tid) : null;
  const md = modal(`<h3>${ic('sparkle', 's')} ${esc(tr(ASST_KINDS[r.kind] || 'Assistant'))}</h3>
    ${t ? `<p class="muted asstfor">${esc(tr('For: {0}', String(t.title || '').slice(0, 80)))}</p>` : ''}
    ${r.truncated ? `<div class="shint keep">${ic('info', 's')} ${esc(tr('The text was shortened'))}</div>` : ''}
    <div class="assttext" tabindex="0">${commentBody(r.text || '', {})}</div>
    <p class="shint">${esc(tr('Written by the assistant ({0}). Check it before you use it.', S.assistant?.provider || ''))}</p>
    <div class="foot"><button class="btn" data-asstm="copy">${ic('copy', 's')} ${tr('Copy')}</button>
      ${t && feat('comments') ? `<button class="btn" data-asstm="comment">${ic('comment', 's')} ${tr('Add as comment')}</button>` : ''}
      <span class="spacer"></span><button class="btn pri" data-asstm="close">${tr('Close')}</button></div>`);
  md.classList.add('asstmd');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-asstm]'); if (!b) return;
    const k = b.dataset.asstm;
    if (k === 'close') { md.remove(); return; }
    if (k === 'copy') { try { await navigator.clipboard.writeText(r.text || ''); toast(tr('Copied')); } catch { toast(tr('Copying is blocked in this browser')); } return; }
    if (k === 'comment') { b.disabled = true; if (await asst_comment(tid, r.text || '')) md.remove(); else b.disabled = false; }
  });
}
async function asst_comment(tid, text) {
  const post = async () => (await capi('POST', `/api/tasks/${tid}/comments`, {body: text})).id;
  let cid;
  try { cid = await post(); } catch { return false; }
  const back = async () => { if (cid) await api('DELETE', `/api/comments/${cid}`); cid = null; if (S.sel === tid) loadTimeline(tid); return {skipped: []}; };
  const again = async () => { cid = await post(); if (S.sel === tid) loadTimeline(tid); return {skipped: []}; };
  if (S.sel === tid) loadTimeline(tid);
  histToast(tr('Comment added'), histAdd({label: tr('Comment added'), ids: [], undo: back, redo: again}));
  return true;
}

// ---- entry points
function asst_detailBtn(t, ck) {  // detail panel, next to the task's other buttons
  if (!asst_ready() || ck || !(t?.id > 0) || !asst_lOk(t)) return '';
  return `<button type="button" class="iconbtn asstb" data-asst="task" data-id="${t.id}" aria-haspopup="menu" title="${esc(tr('Assistant'))}" aria-label="${esc(tr('Assistant'))}">${ic('sparkle')}<span class="dpw">${esc(tr('Assistant'))}</span></button>`;
}
const asst_lOk = t => { const l = listById(t.list_id); return !!l && l.life !== 'health' && l.life !== 'budget' && !l.e2e; };
function asst_taskMenu(b, tid) {
  const t = taskById(tid); if (!t) return;
  if (!asst_taskOk(t)) {  // its list is not shared: say so and offer the place to change it
    menu(b, [{head: tr('Assistant')}, {label: tr('Share this project with the assistant first'), icon: 'info', dis: true},
      {label: tr('Shared projects…'), icon: 'gear', fn: () => settingsModal('assistant')}], null, null, tr('Assistant'));
    return;
  }
  menu(b, [{head: tr('Assistant')},
    {label: tr('Summarize'), icon: 'note', fn: () => asst_go({kind: 'summary', task_id: tid}, b)},
    {label: tr('Draft a reply…'), icon: 'reply', fn: () => asst_draftAsk(tid, b)},
    {label: tr('Extract tasks'), icon: 'sub', fn: () => asst_extract(tid, b)},
    {label: tr('Suggest tags and due date'), icon: 'tag', fn: () => asst_go({kind: 'tags', task_id: tid}, b)}], null, null, tr('Assistant'));
}
function asst_draftAsk(tid, b) {
  const md = modal(`<h3>${tr('Draft a reply')}</h3>
    <div class="row"><label for="asst-ins">${tr('What kind of reply?')}</label><input id="asst-ins" maxlength="300" value="${esc(tr('a short, friendly reply'))}"></div>
    <div class="foot"><button class="btn" data-asstd="close">${tr('Cancel')}</button><span class="spacer"></span><button class="btn pri" data-asstd="go">${ic('sparkle', 's')} ${tr('Draft')}</button></div>`);
  const go = () => { const ins = $('#asst-ins', md).value.trim() || tr('a short, friendly reply'); md.remove(); asst_go({kind: 'draft', task_id: tid, instruction: ins}, b); };
  md.addEventListener('click', e => { const x = e.target.closest('[data-asstd]'); if (!x) return; if (x.dataset.asstd === 'go') go(); else md.remove(); });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'asst-ins') { e.preventDefault(); go(); } });
  setTimeout(() => $('#asst-ins', md)?.select(), 0);
}
function asst_extract(tid, b) {  // target = the task's list when shared, else one of the shared lists
  const t = taskById(tid), own = t && asst_shared(t.list_id) ? t.list_id : null;
  if (own) { asst_go({kind: 'extract', task_id: tid, list_id: own}, b); return; }
  const ls = (S.assistant?.list_ids || []).map(listById).filter(asst_canList);
  if (!ls.length) { toast(tr('Share a project with the assistant first: Settings > Assistant')); return; }
  if (ls.length === 1) { asst_go({kind: 'extract', task_id: tid, list_id: ls[0].id}, b); return; }
  menu(b, [{head: tr('New tasks go to')}, ...ls.map(l => ({label: l.name, lic: l, fn: () => asst_go({kind: 'extract', task_id: tid, list_id: l.id}, b)}))], null, null, tr('Extract tasks'));
}
function asst_inboxBtn() {  // basket header: sort the marked items (or the first 30 open ones) with the assistant
  if (!asst_ready() || !asst_myInbox() || !asst_inboxIds().length) return '';
  return `<button type="button" class="btn sm tf asstsortb" data-asst="triage" data-act="asst-triage" data-ico="sparkle" title="${esc(tr('Sort with the assistant'))}">${ic('sparkle', 's')}<span class="bl">${tr('Sort with the assistant')}</span></button>`;
}
function asst_inboxIds() {
  const ib = asst_myInbox(); if (!ib) return [];
  const open = openTasks().filter(t => t.list_id === ib.id && !t.parent_id && t.status === 0 && !t.deleted_at);
  const marked = S.multi?.size ? open.filter(t => S.multi.has(t.id)) : [];
  return (marked.length ? marked : open.sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id)).slice(0, ASST_MAX).map(t => t.id);
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-asst]'); if (!b || b.disabled) return;
  e.preventDefault(); e.stopPropagation();
  const k = b.dataset.asst;
  if (k === 'task') asst_taskMenu(b, +b.dataset.id);
  else if (k === 'triage') { const ids = asst_inboxIds(); if (!ids.length) toast(tr('The basket is empty')); else asst_go({kind: 'triage', task_ids: ids}, b); }
});

// ---- Settings > Assistant
function asst_paneHtml(hint) {
  if (!asst_avail()) return '';
  const a = S.assistant, on = new Set(a.list_ids || []);
  const ls = S.lists.filter(asst_canList).sort((x, y) => String(x.name).localeCompare(String(y.name)));
  return `<h4 id="s-asst-h">${tr('Assistant')}</h4>
    ${hint(tr('Summarizes, drafts replies, suggests tags and dates, sorts the basket and plans your day. Everything only as a proposal: the assistant changes nothing by itself.'))}
    <div class="row"><label>${tr('Assistant')}</label><label class="chkl"><input type="checkbox" id="s-asst-on" ${a.on ? 'checked' : ''}> ${tr('Use the assistant')}</label></div>
    <div class="shint keep asstprov">${ic('info', 's')} <span>${esc(tr('Shared projects and the texts you choose are sent to {0} ({1}).', a.provider || '', a.host || ''))} ${esc(tr('Model: {0}', a.model || ''))}</span></div>
    <h4 id="s-asst-lists-h">${tr('Projects the assistant may read')}</h4>
    ${hint(tr('Only tasks of the projects ticked here go to the assistant, and only when you ask it. Basket tasks go only when you pick them yourself; health projects and locked notes never.'))}
    <div class="lcapgrid asstlists" id="s-asst-lists">${ls.map(l => `<label class="chkl"><input type="checkbox" data-asstl="${l.id}" ${on.has(l.id) ? 'checked' : ''}><span>${esc(l.name)}</span></label>`).join('') || `<span class="muted">${esc(tr('No projects yet.'))}</span>`}</div>
    <h4 id="s-asst-log-h">${tr('Log')}</h4>
    ${hint(tr('Every call with its time, kind, status and length. The texts themselves are not kept.'))}
    <div id="s-asst-log"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
function asst_helpHtml() {  // Settings > Help: one line with a way to the section
  return asst_avail() ? `<h4>${tr('Assistant')}</h4><div class="shelp">${esc(tr('The built-in assistant works only on the projects you share with it and only when you ask it; its results are proposals you accept or reject.'))} <button type="button" class="linkbtn" data-asstgo>${esc(tr('Open the assistant settings'))}</button></div>` : '';
}
function asst_admHtml() {  // Settings > Administration > Server: the instance's assistant (filled when shown)
  return asst_avail() && S.me?.is_admin ? `<h4 id="s-asst-adm-h">${tr('Assistant')}</h4><div id="s-asst-adm"><div class="muted mhint">${tr('Loading…')}</div></div>` : '';
}
async function asst_logDraw(md, more) {
  const box = $('#s-asst-log', md); if (!box) return;
  md._asstN = more ? Math.min(200, (md._asstN || 50) + 50) : (md._asstN || 50);
  let j; try { j = await calReq('GET', `/api/assistant/log?limit=${md._asstN}`); } catch (x) { box.innerHTML = `<div class="muted mhint">${esc(x.message)}</div>`; return; }
  const it = j.items || [];
  box.innerHTML = it.length ? `<div class="tblwrap"><table class="assttbl"><thead><tr><th>${tr('Time')}</th><th>${tr('Kind')}</th><th>${tr('Status')}</th><th>${tr('Duration')}</th></tr></thead><tbody>
      ${it.map(r => `<tr class="st-${esc(r.status)}"><td>${esc(fmtWhen(r.at))}</td><td>${esc(tr(ASST_KINDS[r.kind] || r.kind))}${r.task_id ? ` <span class="muted">#${+r.task_id}</span>` : ''}</td><td>${esc(tr(ASST_ST[r.status] || r.status))}</td><td>${r.ms ? esc(fmtNum(r.ms / 1000, 1)) + ' s' : '–'}</td></tr>`).join('')}</tbody></table></div>
      ${it.length >= md._asstN && md._asstN < 200 ? `<button type="button" class="btn sm" data-asstlog="more">${tr('Load more')}</button>` : ''}`
    : `<div class="muted mhint">${tr('No calls yet.')}</div>`;
}
async function asst_admDraw(md) {
  const box = $('#s-asst-adm', md); if (!box || box._done) return;
  box._done = true;
  let j; try { j = await calReq('GET', '/api/admin/assistant'); } catch (x) { box._done = false; box.innerHTML = `<div class="muted mhint">${esc(x.message)}</div>`; return; }
  const ds = j.days || [], sum = k => ds.reduce((n, d) => n + (+d[k] || 0), 0);
  box.innerHTML = `<ul class="slist asstadm">
      <li>${esc(tr('Provider: {0} ({1})', j.provider || '', j.host || ''))}</li><li>${esc(tr('Model: {0}', j.model || ''))}</li>
      <li>${esc(tr('Time limit {0} s, at most {1} characters per call', j.timeout_s ?? '', fmtNum(+j.max_chars || 0, 0)))}</li>
      <li>${esc(tr('Today: {0} calls, {1} errors', j.today?.calls || 0, j.today?.errors || 0))}</li>
      <li>${esc(tr('Last 30 days: {0} calls, {1} errors', sum('calls'), sum('errors')))}</li></ul>
    <div class="shint">${tr('The address, the model and the key are set by the operator (environment variables, see the self-hosting guide).')}</div>`;
}
function asst_paneDraw(md) {  // the shown section loads its data (Assistant: the log, Administration: the instance block)
  const p = $('.spane:not(.hidden)', md)?.dataset.pane;
  if (p === 'assistant') asst_logDraw(md);
  if (p === 'users') asst_admDraw(md);
}
function asst_setWire(md) {
  md.addEventListener('click', e => { if (e.target.closest('[data-asstlog="more"]')) asst_logDraw(md, true); if (e.target.closest('[data-asstgo]')) $('.snav [data-sec="assistant"]', md)?.click(); });
  md.addEventListener('change', async e => {
    const el = e.target; if (!el.dataset?.asstl) return;
    const from = [...(S.assistant?.list_ids || [])], to = $$('[data-asstl]:checked', md).map(x => +x.dataset.asstl);
    const put = async ids => {
      const j = await calReq('PUT', '/api/assistant/lists', {list_ids: ids});
      S.assistant.list_ids = (j.lists || []).map(l => l.id);
      $$('[data-asstl]', md).forEach(x => { x.checked = S.assistant.list_ids.includes(+x.dataset.asstl); });
      if ($('#s-asst-log', md)) asst_logDraw(md);
      render(); return {skipped: []};
    };
    try { await put(to); } catch (x) { toast(x.message); el.checked = !el.checked; return; }
    const lab = tr('Projects the assistant may read');
    setSaved(histAdd({label: tr('Changed setting: {0}', lab), sett: true, undo: () => put(from), redo: () => put(to)}));
  });
  asst_paneDraw(md);
}
