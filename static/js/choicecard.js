// 2.41.0 (#1383): one component for an agent's answer buttons, approval cards and suggestions -- in the agent chat
// (agentchat.js) and in task comments (collab.js). The data is the same in both places: choices = {choices: [{id, label,
// style?}], multi, approval?: {title, what, std?}, expires_at?, withdrawn_at?, outcome?}, choice = the answer {ids, at,
// user_id, user_name?, via}, choice_state open | answered | expired | withdrawn (#1037: only the newest question is live,
// an approval card stays open until answered). attrs(id) = the data attributes of a button (who handles the press).
function ccApvHead(ap, open, src = '') {
  return (open ? `<div class="apvh">${ic('lock', 's')}<span>${esc(tr('Approval needed'))}</span></div>` : '')
    + (ap ? `<div class="apvt">${esc(ap.title)}</div>${ap.what ? `<div class="apvw">${esc(tr('If yes: {0}', ap.what))}</div>` : ''}${/*html-ok*/ /* escaped inside */ ccApvStep(ap, src && !open ? src + '|d' : src)}` : '');  // a decided card: its own entry (the state at the answer)
}
// 2.1068.0 (#5831): a line diff as rows [[op, line]] (op ' ' / '+' / '-' / '…' = a gap) -- one rendering for the knowledge
// history (wkhist.js) and the approval card; + / − in front, not only the colour
function txtDiffHtml(rows) {
  const h = rows.map(([t, x]) => t === '…' ? `<div class="wkhd gap" aria-hidden="true">…</div>`
    : `<div class="wkhd ${t === '+' ? 'add' : t === '-' ? 'del' : ''}"><span class="wkhdm" aria-hidden="true">${t === '+' ? '+' : t === '-' ? '−' : ''}</span><span class="sr">${t === '+' ? tr('added:') : t === '-' ? tr('removed:') : ''}</span><span>${esc(x) || '&nbsp;'}</span></div>`).join('');
  return `<div class="wkhdiff" role="group" aria-label="${esc(tr('Changes'))}">${/*html-ok*/ /* rows built with esc() above */ h}</div>`;
}
// 2.1068.0 (#5831): the steps whose change the server shows as a diff (agents/apvdiff.py APVD_STEPS)
const ccApvTextStep = st => !!st && (
  (st.method === 'PATCH' && /^\/api\/v1\/(wiki\/pages|comments|tasks)\/\d+$/.test(st.path || '') && !!st.body && ['body', 'notes', 'content'].some(k => typeof st.body[k] === 'string'))
  || (st.method === 'POST' && /^\/api\/v1\/(wiki\/pages\/\d+|tasks\/\d+\/notes|lists\/\d+\/overview)\/(append|replace-section)$/.test(st.path || ''))  // 2.1082.0 (#5830): + notes, description, sections
  || (st.method === 'PATCH' && /^\/api\/v1\/lists\/\d+\/overview$/.test(st.path || '') && typeof st.body?.description === 'string'));
S.apvd = S.apvd || {};
// the words of a diff: "Knowledge page Wiki/2D: 1 line added, nothing removed"
function ccApvdWords(d) {
  const nm = d.kind === 'wiki' ? tr('Knowledge page {0}', d.ref || d.name) : d.kind === 'task' ? tr('Notes of task {0}', [d.ref, d.name].filter(Boolean).join(' '))
    : d.kind === 'project' ? tr('Description of project {0}', d.name) : tr('Comment on task {0}', [d.ref, d.name].filter(Boolean).join(' '));
  if (d.hidden) return `${nm}: ${d.hidden === 'encrypted' ? tr('encrypted, the change cannot be shown') : d.hidden === 'gone' ? tr('no longer there') : tr('you cannot read it, the change is not shown')}`;
  const add = d.added ? trn('{0} line added', '{0} lines added', d.added) : tr('nothing added'), del = d.removed ? trn('{0} line removed', '{0} lines removed', d.removed) : tr('nothing removed');
  return `${nm}: ${add}, ${del}`;
}
function ccApvdBody(d, src) {
  if (!d || d.hidden) return '';
  const note = [d.changed && !d.decided ? `<div class="apvdchg" data-apvd-changed>${esc(tr('Changed since the card was made - the change is shown against the text now'))}</div>` : '',
    d.decided ? `<div class="muted" data-apvd-decided>${esc(tr('As it was when the card was answered'))}</div>` : '',
    d.no_heading ? `<div class="apvdchg">${esc(tr('The heading {0} is no longer on the page', d.no_heading))}</div>` : ''].join('');
  return note + (d.rows?.length ? txtDiffHtml(d.rows) : '') + (d.more && !d.decided ? `<button type="button" class="btn sm" data-act="apvd-all" data-apvd-src="${esc(src)}">${esc(tr('Show everything'))}</button>` : '');
}
// fetched once per card (src = chat:<id> | comment:<id>), then every element of that card is filled in
async function ccApvdLoad(src, full = false) {
  const e = S.apvd[src]; if (e && (e.busy || (e.d !== undefined && !full))) return;
  S.apvd[src] = {...(e || {}), busy: true};
  const [k, id] = src.split('|')[0].split(':');
  let d = null;
  try { d = (await api('GET', `/api/approvals/diff?${k}=${id}${full ? '&full=1' : ''}`)).diff; } catch (err) { d = e?.d ?? null; }
  S.apvd[src] = {d, busy: false};
  for (const n of document.querySelectorAll(`[data-apvd="${CSS.escape(src)}"]`)) ccApvdFill(n, d, src);
}
function ccApvdFill(n, d, src) {
  const sm = n.querySelector('summary [data-apvd-words]'), bd = n.querySelector('[data-apvd-body]');
  if (sm) sm.textContent = d ? ccApvdWords(d) : tr('Step details');
  if (bd) bd.innerHTML = ccApvdBody(d, src);
}
// 2.235.0 A2 (#2891): what the Yes really approves (the server binds method, path and body), one-way, the agent's recommendation.
// 2.1068.0 (#5831): a step that replaces or adds to a text (a knowledge page, a task's notes, a project's description, a
// comment) shows the change itself (the server reckons it, collapsed one line in words, open: the changed lines); the
// technical line "Step: …" is inside the fold for every step; src = chat:<message id> | comment:<comment id>
function ccApvStep(ap, src = '') {
  const st = ap.step, b = st && st.body && typeof st.body === 'object' && !Array.isArray(st.body) ? st.body : null;
  let t = '', w = '';
  if (st) {
    const p = String(st.path || '').replace(/^\/api\/v1(?=\/)/, ''), m = p.match(/^\/tasks\/(\d+)$/);
    w = st.method === 'DELETE' && m ? tr('Delete task {0}', m[1])
      : p === '/tasks/batch' && b && Array.isArray(b.ids) ? tr('{0} tasks, action {1}', b.ids.length, String(b.action || '')) : '';
    t = `${st.method} ${p}` + (b && Object.keys(b).length ? ' · ' + tr('Fields: {0}', Object.keys(b).join(', ')) : '');
  }
  let fold = '';
  if (st) {
    const dv = !!src && ccApvTextStep(st), c = dv ? S.apvd[src] : null, d = c?.d;
    const sum = dv ? (d ? ccApvdWords(d) : d === null ? tr('Step details') : tr('Loading…')) : w ? tr('Step: {0}', w) : tr('Step details');
    fold = `<details class="apvdet" ${dv ? `data-apvd="${esc(src)}"` : ''}><summary><span data-apvd-words>${esc(sum)}</span></summary>${dv ? `<div data-apvd-body>${/*html-ok*/ /* escaped inside */ d ? ccApvdBody(d, src) : ''}</div>` : ''}<div class="apvw" data-apv-step>${esc(tr('Step: {0}', t))}</div></details>`;
    if (dv && (!c || c.d === undefined)) setTimeout(() => ccApvdLoad(src), 0);
  }
  return fold
    + (ap.one_way ? `<div class="apvw" data-apv-oneway><b>${esc(tr('One-way step – cannot be undone'))}</b></div>` : '')
    + (ap.recommend ? `<div class="apvw" data-apv-rec>${esc(tr('The agent recommends: {0}', ap.recommend === 'yes' ? tr('Yes') : tr('No')))}</div>` : '');
}
const ccApvLbl = (ch, id) => { const ap = ch.approval, c = (ch.choices || []).find(x => x.id === id); return ap?.std || !c ? (id === 'yes' ? tr('Yes, go ahead') : tr('No')) : c.label; };
// 2.46.6 (#1711): pen = the attributes of the pen next to "Yes" ('' = none): "Yes, but: <card text>" into the message box
const ccApvEditText = ch => tr('Yes, but:') + ' ' + (ch.approval?.title || '');
function ccApvBtns(ch, attrs, pen = '') {
  const yes = `<button type="button" class="cchb st-primary cpermb" ${attrs('yes')}>${thumbIc(true)}<span>${esc(ccApvLbl(ch, 'yes'))}</span></button>`;
  const pb = pen ? `<button type="button" class="cchpen" ${pen} title="${esc(tr('Edit before sending'))}" aria-label="${esc(tr('Edit before sending: {0}', ccApvLbl(ch, 'yes')))}">${ic('edit', 's')}</button>` : '';
  return `<div class="cchoices cperm apvbtns" role="group" aria-label="${esc(tr('Approval needed'))}">${pen ? `<span class="cchw">${yes}${pb}</span>` : yes}<button type="button" class="cchb cpermb" ${attrs('no')}>${thumbIc(false)}<span>${esc(ccApvLbl(ch, 'no'))}</span></button></div>`;
}
// the line of a decided / closed approval card; t = the text of an answered one (the chat: "Approved by … at …")
function ccApvState(ch, ans, st, t) {
  const oc = ch.outcome;
  if (st === 'expired' || (st === 'withdrawn' && oc === 'expired')) return `<div class="cpermst exp" role="status">${ic('clock', 's')}<span>${esc(tr('Not answered – not approved'))}</span></div>`;
  if (!ans) return `<div class="cpermst exp" role="status"><span>${esc(tr('Closed by the agent'))}</span></div>`;  // review N1: never "Approved"
  const ok = (ans.ids || []).includes('yes');
  return `<div class="cpermst ${ok ? 'ok' : 'no'}" role="status">${thumbIc(ok)}<span>${esc(t)}</span></div>`;
}
// answer buttons / suggestions (not an approval card): o = {ch, ans, sel (Set of picked ids, multi), attrs(id), pen(c) (the
// pen next to an open suggestion: its html, or ''), send (the attributes of "Send" with multi), done (the text after an answer)}
// 2.565.0 (#4713): a long label (up to 200 characters) -> class cchl: the button takes the full width on a phone
const ccIsLong = c => String(c.label || '').length > 40;
function ccButtons(o) {
  const {ch, ans} = o, ids = new Set(ans?.ids || []), multi = !!ch.multi, sel = o.sel || new Set();
  const btn = c => `<button type="button" class="cchb${ccIsLong(c) ? ' cchl' : ''} ${c.style ? 'st-' + esc(c.style) : ''} ${ids.has(c.id) || sel.has(c.id) ? 'on' : ''}" ${o.attrs(c.id)} ${ans ? 'disabled' : ''} ${multi ? `aria-pressed="${sel.has(c.id)}"` : ''}>${ids.has(c.id) ? ic('check', 's') : ''}<span>${esc(c.label)}</span></button>`;
  const pen = c => { const p = o.pen ? o.pen(c) : ''; return p ? `<span class="cchw${ccIsLong(c) ? ' cchl' : ''}">${btn(c)}${p}</span>` : btn(c); };
  return `<div class="cchoices ${ans ? 'done' : ''}" role="group" aria-label="${esc(tr('Answer'))}">${ch.choices.map(ans ? btn : pen).join('')}${multi && !ans && o.send ? `<button type="button" class="btn sm pri cchsend" ${o.send} ${sel.size ? '' : 'disabled'}>${ic('send', 's')} ${tr('Send')}</button>` : ''}${ans ? `<small class="muted cchans">${esc(o.done || tr('Answered'))} · ${fmtWhen(ans.at)}</small>` : ''}</div>`;
}

// ---- comments: the card under an agent's comment
S.ccPick = S.ccPick || {};
const ccWhen = iso => { const d = new Date(iso); return isNaN(+d) ? '' : fmtStamp(d, false); };
function ccCmtState(c) {
  const ch = c.choices; if (!ch) return null;
  if (c.choice) return 'answered';
  if (c.choice_state && c.choice_state !== 'open') return c.choice_state;
  if (ch.approval) return ch.expires_at && Date.parse(ch.expires_at) <= Date.now() ? 'expired' : 'open';
  return (S.tl.comments || []).some(x => x.id > c.id && !x.choices?.approval) ? 'expired' : 'open';  // #1037
}
// may I press? people who can edit the task (the server also asks whether the agent takes instructions from me)
const ccCanAnswer = ro => !ro && !!S.tl.can_write && !!S.me && !isAgentUser(S.me.id);
function ccCommentHtml(c, ro = false) {
  const ch = c.choices; if (!ch || !(ch.choices || []).length) return '';
  const st = ccCmtState(c), ans = c.choice, can = ccCanAnswer(ro);
  const attrs = id => `data-cc="pick" data-cid="${c.id}" data-ch="${esc(id)}"`;
  if (ch.approval) {
    const open = st === 'open', who = ans?.user_name || '';
    const t = ans ? ((ans.ids || []).includes('yes') ? tr('{0} from {1}, {2}', ccApvLbl(ch, 'yes'), who, ccWhen(ans.at)) : tr('{0} from {1}, {2}', ccApvLbl(ch, 'no'), who, ccWhen(ans.at))) : '';
    // 2.144.5 A (#2001): only an approver decides (the server's choice_can: a manager of the list, the assignee, an admin)
    const dec = can && c.choice_can !== false, wait = can ? tr('Waiting for a decision by the project’s managers, the assignee or an admin') : tr('Waiting for an answer');
    return `<div class="cccard apv${open ? ' apvopen' : ''}" role="group" aria-label="${esc(tr('Approval needed'))}">${/*html-ok*/ /* the card's head, its texts escaped inside */ ccApvHead(ch.approval, open, 'comment:' + c.id)}${open ? (dec ? ccApvBtns(ch, attrs, `data-ccpen="${c.id}" data-ch="yes"`) : `<div class="cpermst exp"><span>${esc(wait)}</span></div>`) : ccApvState(ch, ans, st, t)}</div>`;
  }
  if (st !== 'open' && st !== 'answered') return '';  // expired / withdrawn: gone, as in the chat
  if (st === 'open' && !can) return '';
  return ccButtons({ch, ans, sel: S.ccPick[c.id], attrs, send: `data-cc="send" data-cid="${c.id}"`,
    done: ans?.user_name ? tr('Answered by {0}', ans.user_name) : '',
    pen: x => `<button type="button" class="cchpen" data-ccpen="${c.id}" data-ch="${esc(x.id)}" title="${esc(tr('Edit before sending'))}" aria-label="${esc(tr('Edit before sending: {0}', x.label))}">${ic('edit', 's')}</button>`});
}
async function ccAnswer(cid, id, send = false) {
  const c = tlComment(cid); if (!c || c.choice || ccCmtState(c) !== 'open') return;
  if (c.choices?.multi && !send) { const s = S.ccPick[cid] ||= new Set(); s.has(id) ? s.delete(id) : s.add(id); drawTimeline(); return; }
  const ids = send ? [...(S.ccPick[cid] || [])] : [id]; if (!ids.length) return;
  let j;
  try { j = await capi('POST', `/api/comments/${cid}/choice`, {choice_ids: ids}); }
  catch { if (S.sel) loadTimeline(S.sel); return; }  // capi said it (409: no longer current, 403): the card follows the server
  delete S.ccPick[cid];
  Object.assign(c, {choices: j.choices, choice: j.choice, choice_state: j.choice_state, choice_can: j.choice_can});
  const t = taskById(S.sel); if (t && c.choices?.approval && t.approvals_open) { t.approvals_open--; viewSafeRender(); }
  drawTimeline();
  if (j.answer_comment_id && S.sel) loadTimeline(S.sel);  // a suggestion was sent as my comment
}
// the pen: the suggestion into the comment box (not sent), after the text already there
function ccToBox(cid, id) {
  const c = tlComment(cid), x = c?.choices?.approval && id === 'yes' ? {label: ccApvEditText(c.choices)} : (c?.choices?.choices || []).find(y => String(y.id) === String(id)), ta = $('#c-input');  // 2.46.6 (#1711)
  if (!x || !ta) return;
  const v = ta.value.replace(/\s+$/, '');
  ta.value = v ? v + (/\n/.test(v) ? '\n' : ' ') + x.label : x.label;
  ta.dispatchEvent(new Event('input', {bubbles: true}));
  ta.closest('.ccomp')?.classList.add('used');
  ta.focus({preventScroll: true}); ta.setSelectionRange(ta.value.length, ta.value.length);
}
document.addEventListener('click', e => {
  const p = e.target.closest?.('[data-ccpen]');
  if (p) { e.preventDefault(); e.stopPropagation(); ccToBox(+p.dataset.ccpen, p.dataset.ch); return; }
  // 2.525.0 (#4281): the credit card sheet (office_cards.js) uses data-cc too - only a card's own pick / send with its
  // comment id count here (one-meaning guard: data-cc)
  const b = e.target.closest?.('[data-cc]'); if (!b || b.disabled || !b.dataset.cid || (b.dataset.cc !== 'pick' && b.dataset.cc !== 'send')) return;
  e.preventDefault(); e.stopPropagation();
  ccAnswer(+b.dataset.cid, b.dataset.ch, b.dataset.cc === 'send');
});
// 2.46.6 (#1711): "Yes" of an approval card in a comment: Alt+click / right click (desktop) and a long press (touch) = the pen
const CC_APV_ED = '.cccard.apv .cchw .cchb[data-cc="pick"]';
let ccLong = null, ccLongDone = 0;
document.addEventListener('click', e => {
  const b = e.target.closest?.(CC_APV_ED); if (!b || b.disabled) return;
  if (e.altKey || Date.now() - ccLongDone < 600) { e.preventDefault(); e.stopPropagation(); if (e.altKey) ccToBox(+b.dataset.cid, 'yes'); }
}, true);
document.addEventListener('contextmenu', e => {
  const b = e.target.closest?.(CC_APV_ED); if (!b || b.disabled) return;
  e.preventDefault(); if (ccLong) { clearTimeout(ccLong.t); ccLong = null; ccLongDone = Date.now(); ccToBox(+b.dataset.cid, 'yes'); return; } if (Date.now() - ccLongDone > 600) ccToBox(+b.dataset.cid, 'yes');  // 2.46.7: Android fires contextmenu before the long-press timer: one insert, not two
});
document.addEventListener('pointerdown', e => {
  const b = e.pointerType === 'touch' && e.target.closest?.(CC_APV_ED); if (!b || b.disabled) return;
  const x = e.clientX, y = e.clientY; clearTimeout(ccLong?.t);
  ccLong = {x, y, t: setTimeout(() => { ccLong = null; ccLongDone = Date.now(); ccToBox(+b.dataset.cid, 'yes'); }, 500)};
});
document.addEventListener('pointermove', e => { if (ccLong && Math.hypot(e.clientX - ccLong.x, e.clientY - ccLong.y) > 10) { clearTimeout(ccLong.t); ccLong = null; } });
for (const ev of ['pointerup', 'pointercancel']) document.addEventListener(ev, () => { if (ccLong) { clearTimeout(ccLong.t); ccLong = null; } });
