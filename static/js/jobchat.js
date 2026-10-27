/* Kalmido web client: talking to one job of an agent (2.56.0, #1791 / #1793).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// #1791: "Message" on a running job's card (Agents view): a small dialog (a sheet on phones), the text goes to the agent as
// the 'job' event {action: message, text}; the job itself does not change.
// #1793: a job's own history. The tag "Clara · Job #220" on a job's messages in the agent chat (and the job's name at the
// start of such a message) opens the chat filtered to that job (GET /api/agents/<id>/chat?job=<id>: its messages, mine to
// it, the agent's answers to those); a bar under the header shows its name + title and leads back to the whole chat. What I
// type there goes out as "Job 220: …" (review: always the number), the way the agent's service routes it (#1456). An ended
// job keeps its history, the box is off. Running jobs with a name are in the agent menu of the top bar.
// The chat keeps one state (S.chat); S.chat.job = {id} switches it to the job's history (agentchat.js asks jc_q / jc_send).
S.jc = {jobs: {}, at: 0, busy: null, asked: new Set()};
const jc_live = j => !!j && ['running', 'waiting'].includes(j.state);
const jc_label = j => j?.name || tr('Job #{0}', j?.id);
const jc_rest = j => { const t = String(j?.title || ''); return j?.name && t.startsWith(j.name + ':') ? t.slice(j.name.length + 1).trim() : t; };
const jc_cur = () => S.chat.job ? S.jc.jobs[S.chat.job.id] || {id: S.chat.job.id} : null;
const jc_ended = () => { const j = jc_cur(); return !!j && !!j.state && !jc_live(j); };
const jc_q = () => S.chat.job ? '&job=' + +S.chat.job.id : '';
const jc_key = () => S.chat.job ? String(S.chat.job.id) : '';
function jc_put(list) { for (const x of list || []) if (x && x.id) S.jc.jobs[x.id] = x; }
// the jobs I see with their names and states: every running one + the newest ended ones (one request, at most every 15 s)
function jc_sync(force = false) {
  if (S.jc.busy) return S.jc.busy;
  if (!force && Date.now() - S.jc.at < 15000) return Promise.resolve();
  S.jc.at = Date.now();
  return S.jc.busy = api('GET', '/api/agents/jobs?limit=50').then(j => jc_put(j.jobs)).catch(() => {}).finally(() => { S.jc.busy = null; });
}
async function jc_one(jid) {
  if (S.jc.jobs[jid]) return S.jc.jobs[jid];
  if (!jobNoOk(+jid)) return null;  // 2.284.2: never "?id=NaN" / "?id=0"
  try { const j = await rawFetch('GET', `/api/agents/jobs?id=${+jid}`); jc_put(j.jobs); } catch { /* offline / not mine: no toast */ }
  return S.jc.jobs[jid] || null;
}
// a job tag in the chat whose job is not known yet: fetched once, then the chat draws again (names, links)
function jc_need(no) {
  if (S.jc.jobs[no] || S.jc.asked.has(no) || !jobNoOk(no)) return;
  S.jc.asked.add(no);
  clearTimeout(jc_need.t);
  jc_need.t = setTimeout(async () => {
    await jc_sync(true);
    for (const n of [...S.jc.asked].filter(n => !S.jc.jobs[n]).slice(0, 5)) await jc_one(n);
    chatPatch({keep: true});
  }, 50);
}

// ---- the chat (agentchat.js): the tag, the leading name, the bar, sending, the box of an ended job
function jc_tagHtml(jb, m) {
  const j = S.jc.jobs[jb.no]; if (!j) jc_need(jb.no);
  const t = tr('Open the chat of {0}', jc_label(j?.name ? j : {id: jb.no, name: jb.name})), here = S.chat.job && +S.chat.job.id === jb.no;
  return `<button type="button" class="jobtag jc-tag" data-act="jc-open" data-jid="${jb.no}" data-aid="${+m.agent_id || +S.chat.aid}"${here ? ' disabled' : ''} title="${esc(t)}" aria-label="${esc(t)}"><i></i>${jb.name || j?.name ? `<b>${esc(jb.name || j.name)}</b>` : esc(tr('Job #{0}', jb.no))}</button>`;  // 2.59.0 (#1827): the name, else "Job #N"
}
// "Clara: …" / "Clara (Release …)" at the very start of a job's message: the name becomes the same link as the tag
function jc_bodyHtml(html, jb) {
  const n = S.jc.jobs[jb.no]?.name; if (!n || (S.chat.job && +S.chat.job.id === jb.no)) return html;
  const re = new RegExp('^((?:<[a-z0-9]+(?:\\s[^>]*)?>)*)' + esc(n).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=[:\\s(])');
  return html.replace(re, (_, pre) => `${pre}<button type="button" class="jc-name" data-act="jc-open" data-jid="${jb.no}" data-aid="${+S.chat.aid}">${esc(n)}</button>`);
}
// lazy-ok-begin: 2.149.0 F (#2519): the job bar and the job rows are drawn inside the agent chat (agentchat.js loaded)
function jc_barHtml() {
  if (!S.chat.job) return '';
  const j = jc_cur(), end = jc_ended(), rest = jc_rest(j);
  const pj = +j.parent_id || 0, jb = {no: +j.id, name: j.name || '', parent: pj, pname: pj ? S.jc.jobs[pj]?.name || '' : ''};  // 2.59.0 (#1827)
  return `<div class="jcbar${jn9_part(jb) ? ' jpart' : ''}" id="jc-bar" style="--jcol:${jn9_jobColor(jb)}"><button type="button" class="iconbtn jcback" data-act="jc-back" title="${esc(tr('Back to the whole chat'))}" aria-label="${esc(tr('Back to the whole chat'))}">${ic('back', 's')}</button><i class="jcdot" aria-hidden="true"></i><div class="jcn"><b>${esc(jc_label(j))}</b>${rest ? `<span>${esc(rest)}</span>` : ''}</div>${end ? `<span class="jcend">${esc(tr('Job has ended'))}</span>` : ''}</div>`;
}
// lazy-ok-end
const jc_ph = a => S.chat.job ? (jc_ended() ? tr('Job has ended') : tr('Message to {0}…', jc_label(jc_cur()))) : tr('Message to {0}…', a.name);
// what the box sends: in a job's history (2.153.0 #1962: its own chat) "Job 220: <text>" (unless it already starts with that or the job's name) --
// review: always the number, a title like "Release: 2.56" would otherwise address a job "Release" nobody knows
// 2.153.0 (#1962): the job's id goes along as job_id (jc_field) for hosts that route by it; the prefix stays, hosts that read
// only the text still reach the job
function jc_send(body) {
  if (!S.chat.job || !body) return body;
  const j = jc_cur(), pre = `Job ${j.id}:`, low = body.toLowerCase();
  return low.startsWith(pre.toLowerCase()) || (j.name && low.startsWith(j.name.toLowerCase() + ':')) ? body : `${pre} ${body}`;
}
const jc_field = () => S.chat.job ? {job_id: +S.chat.job.id} : {};
// after every chat patch: the bar and the box follow the job's state (fetched at most every 15 s)
function jc_patch() {
  if (!S.chat.job) return;
  const b = $('#jc-bar'), h = jc_barHtml(); if (b && !wk_sameEl(b, h)) b.outerHTML = h;  // 2.119.1 D (#2310)
  const ci = $('#chat-in'), ph = jc_ph(agentById(S.chat.aid) || {}); if (ci && ci.placeholder !== ph) { ci.placeholder = ph; ci.setAttribute('aria-label', ph); }
  if (!S.jc.busy && Date.now() - S.jc.at > 15000) jc_sync().then(() => { if (S.chat.job) jc_patch(); });
}
// open the history of job jid (null = the whole chat again) in the chat of agent aid, where the chat is (panel or page)
async function jc_open(aid, jid) {
  const j = jid ? await jc_one(jid) : null;
  if (jid && !j) { toast(tr('Job not found')); return; }
  jc_enter(+aid || j?.agent_id, j);
}
// 2.152.8 (#2711): on a touch device Back (key / swipe) in a job's history leads to the whole chat, like the bar's back button.
// Entering a job's history pushes one history entry (backclose.js pattern), Back pops it and popstate leaves the job; leaving
// the history another way takes the entry away again. A free overlay entry of backclose.js is reused instead of a second one.
const jc_bk = {pushed: false, skip: false};
function jc_hist(on, back = true) {
  if (typeof isTouch !== 'function' || !isTouch()) return;
  if (on && !jc_bk.pushed) {
    if (history.state?.f8d && !f8d_open()) history.replaceState({jc: 1}, '', location.href);
    else history.pushState({jc: 1}, '', location.href);
    jc_bk.pushed = true;
  } else if (!on && jc_bk.pushed) {
    jc_bk.pushed = false;
    if (back && history.state?.jc) { jc_bk.skip = true; history.back(); }  // only our own entry; after a route change it is not ours
  }
}
window.addEventListener('popstate', e => {
  if (jc_bk.skip) { jc_bk.skip = false; e.stopImmediatePropagation(); return; }
  if (!jc_bk.pushed || history.state?.jc) return;
  jc_bk.pushed = false;
  if (S.chat.job) { e.stopImmediatePropagation(); jc_enter(S.chat.aid, null); }
}, true);
function jc_enter(aid, j) {
  if (!aid) return;
  const ci = $('#chat-in'); if (ci && S.chat.aid) S.drafts['chat:' + S.chat.aid] = ci.value;
  S.chat = {aid: +aid, msgs: [], err: null, ...(j ? {job: {id: j.id}} : {})};
  if (chatFull()) {
    // the phone chat page is never rebuilt by renderView (render.js, #451): the page swaps its chat itself
    const v = S.route.mod === 'agents' && +S.route.agent === +aid && $('#view .chview');
    if (v) { v.outerHTML = chatViewHtml(aid); chatFit(); chatLoad().then(() => chatPatch({bottom: true})); }
    else { if (!/^#agents\//.test(location.hash)) S.chatBack = location.hash.slice(1); go('agents/' + aid); }
    jc_hist(!!j);  // after go(): the entry belongs to the chat page's route
    return;
  }
  const p = $('#achat');
  if (p && !p.classList.contains('hidden')) { chatDraw(); chatLoad(); } else chatOpen(aid, {jc: true});
  jc_hist(!!j);
}

// ---- #1791: "Message" on the job card
const jc_cardBtn = j => !j.kind && j.can_stop && jc_live(j) ? `<button class="btn sm" data-act="jc-msg" data-jid="${j.id}">${ic('comment', 's')} ${tr('Message')}</button>` : '';
async function jc_msg(jid) {
  const j = (S.jobs?.items || []).find(x => x.id === jid) || S.jc.jobs[jid] || {id: jid};
  let ta = null;
  const ok = await askDialog({title: tr('Message to {0}', jc_label(j)), ok: tr('Send'),
    html: `<textarea id="jc-text" class="jc-text" rows="4" maxlength="4000" aria-label="${esc(tr('Message to {0}', jc_label(j)))}"></textarea><p class="muted jc-hint">${esc(tr('The job reads it after its next step.'))}</p>`,
    after: md => {
      ta = $('#jc-text', md); const b = $('[data-cd="yes"]', md); b.disabled = true;
      ta.addEventListener('input', () => { b.disabled = !ta.value.trim(); });
      ta.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && ta.value.trim()) { e.preventDefault(); b.click(); } });
      setTimeout(() => ta.focus(), 60);
    }});
  const text = ok && ta ? ta.value.trim() : '';
  if (!text) return;
  try { await api('POST', `/api/agents/jobs/${jid}/action`, {action: 'message', text}); toast(tr('Sent to {0}', jc_label(j))); }
  catch { /* api() shows the error */ }
}

// ---- #1793: running jobs with a name in the agent menu of the top bar (only the ones for me)
function jc_menuItems() {
  const ags = new Set((S.agents || []).filter(a => a.enabled).map(a => a.id));
  const js = Object.values(S.jc.jobs).filter(j => jc_live(j) && j.name && j.user_id === S.me?.id && ags.has(j.agent_id)).sort((a, b) => a.id - b.id);
  return js.map(j => { const r = jc_rest(j); return {label: j.name + (r ? ' · ' + (r.length > 48 ? r.slice(0, 47) + '…' : r) : ''), icon: 'comment', fn: () => jc_enter(j.agent_id, j)}; });
}

// ---- 2.63.0 (#1482): "Conversation" on the job card: the last messages of the job's own history (same endpoint as the chat,
// ?job=), loaded when unfolded, refreshed on live updates while open; 403 / 404 (not my agent) = no section
S.jth = {};  // job id -> {msgs, v, at, busy, hide}
function jth_html(j) {
  if (j.kind || !j.agent_id) return '';
  const t = S.jth[j.id] || {}, open = !!S.jobThOpen?.[j.id];
  if (t.hide) return '';
  if (open && !t.busy && (!t.at || (t.v !== S.v && Date.now() - t.at > 3000))) setTimeout(() => jth_load(j), 0);
  const body = !t.msgs ? `<p class="muted">${tr('Loading…')}</p>` : t.msgs.length
    ? t.msgs.map(m => `<div class="jthm ${m.from === 'agent' ? 'ag' : 'me'}"><span class="muted">${esc(fmtWhen(m.created_at))}</span><p>${esc(String(m.body || '').slice(0, 400))}</p></div>`).join('') : `<p class="muted">${tr('No messages yet.')}</p>`;
  // data-k: its own key for the redraw (the history .joblog of the same card has the same data-jid)
  return `<details class="jobth" data-k="jth${j.id}" data-jid="${j.id}"${open ? ' open' : ''}><summary>${tr('Conversation')}</summary><div class="jthbody">${open ? body : ''}${open ? `<button type="button" class="btn sm" data-act="jc-open" data-jid="${j.id}" data-aid="${j.agent_id}">${ic('comment', 's')} ${tr('Open the whole conversation')}</button>` : ''}</div></details>`;
}
async function jth_load(j) {
  const t = S.jth[j.id] || (S.jth[j.id] = {});
  if (t.busy) return;
  t.busy = true;
  try {
    const r = await rawFetch('GET', `/api/agents/${+j.agent_id}/chat?limit=5&job=${+j.id}`);
    t.msgs = (r.messages || []).slice(-5); t.v = S.v; t.at = Date.now();
  } catch (e) { if (e && [403, 404].includes(e.status)) t.hide = true; else t.at = Date.now(); }
  t.busy = false;
  const d = document.querySelector(`details.jobth[data-jid="${j.id}"]`);
  if (d) d.outerHTML = jth_html(j);
}
document.addEventListener('toggle', e => {
  const d = e.target instanceof Element && e.target.matches?.('details.jobth') ? e.target : null; if (!d) return;
  (S.jobThOpen || (S.jobThOpen = {}))[d.dataset.jid] = d.open;
  const j = (S.jobs?.items || []).find(x => x.id === +d.dataset.jid);
  if (d.open && j) { const t = S.jth[j.id]; if (!t || !t.msgs) jth_load(j); else { d.outerHTML = jth_html(j); } }
}, true);

// ---- 2.96.0 C (#2015): one card per job in the agent chat. The messages of a job (job_id, the "Job #N" start, or the
// agent's answer to a message of mine addressed to the job) become ONE card at the place of the job's newest message: name
// (a part job "Leader / Name"), version (from the title), state (from the job: S.jc.jobs, filled by the chat answer's
// jobs), the first line of the newest message, its time. A tap unfolds the job's messages under it (open / closed kept
// per device). Always visible: approval / permission questions (any message with buttons stays its own row), the end
// result and errors (under the card, 5 lines + "Show more"). The kind of a message: job_msg of the server, else read from
// the text (a leading ✅ = result, ⚠️ ⏰ ⏹ = error). A filter above the messages: All / Only me and <agent> / Jobs
// (kept per device; on a phone a menu). The folded rows stay in the page (hidden), so search and reply quotes find them
// (jcd_reveal unfolds). Without a single job: no filter, the chat as before. A job's own history (?job=) has no cards.
S.jcd = {map: new Map(), n: 0, more: new Set(), under: new Set()};  // 2.153.0 (#1962): under = the ids shown under their card
const JCD_KINDS = ['say', 'question', 'result', 'error'];
const JCD_SHOW = new Set(['result', 'error', 'question']);  // 2.153.0 (#1962): + question, under the card
const JCD_LINES = 3;  // 2.153.0 (#1962): at most this many under the card (the newest)
const JCD_RES_RE = /^\s*✅/, JCD_ERR_RE = /^\s*(?:⚠|⏰|⏹)/;
const JCD_VER_RE = /\d+\.\d+(?:\.\d+)?[a-z]?/;
const JCD_ST = {running: N_('running'), waiting: N_('waiting'), done: N_('finished'), failed: N_('Error'), stopped: N_('stopped')};
const JCD_ADDR_RE = /^\s*@?(?:job\s*#?|#)(\d+)\s*:/i;
function jcd_kind(m) {
  if (m.kind === 'notice' || m.job_msg === 'start') return 'say';  // 2.153.0 (#1962): the start line is never a result
  if (JCD_KINDS.includes(m.job_msg)) return m.job_msg;
  const b = m.body || '';
  return JCD_RES_RE.test(b) ? 'result' : JCD_ERR_RE.test(b) ? 'error' : 'say';
}
// the jobs of the chat answer ({id: {...}}) into the known jobs, without losing what the job list knows of them
function jcd_put(jobs) { for (const x of Object.values(jobs || {})) if (x && x.id) S.jc.jobs[x.id] = {...S.jc.jobs[x.id], ...x}; }
// the job a message of mine is addressed to ("Job 82: …", "#82: …", "Clara: …"; the way the agent's service reads it)
function jcd_addr(body) {
  const b = String(body || ''), x = JCD_ADDR_RE.exec(b); if (x) return +x[1];
  const low = b.trimStart().toLowerCase().replace(/^@/, '');
  let best = 0;
  for (const j of Object.values(S.jc.jobs)) if (j.name && j.id > best && (!S.chat.aid || !j.agent_id || +j.agent_id === +S.chat.aid) && low.startsWith(j.name.toLowerCase() + ':')) best = +j.id;
  return best;
}
// the job card a message belongs to (0 = a row of its own)
function jcd_jobOf(m, byId) {
  if (m.choices) return 0;
  return jcd_jobNo(m, byId);
}
// 2.144.0 A (#2416): the job an agent message comes from, buttons or not (a job's result mostly carries the suggestion
// buttons, since 2.122.1 also approval cards): the filter asks this, the card keeps a message with buttons as its own row
function jcd_jobNo(m, byId) {
  if (m.job_id && (m.from !== 'agent' || m.kind === 'notice')) return +m.job_id;  // 2.153.0 (#1962): typed in the job's chat, its start line
  if (m.from !== 'agent' || m.kind === 'notice') return 0;
  const jb = ux_jobOf(m); if (jb) return jb.no;
  const q = m.reply_to && byId.get(m.reply_to);
  return q && q.from !== 'agent' ? (+q.job_id || jcd_addr(q.body)) : 0;
}
// 2.144.0 A (#2416): a row through the filter. "Only me and <agent>": my messages and the main agent's, of the jobs only
// open approvals / permission questions that wait for me. "Jobs": the job rows and my messages addressed to a job.
function jcd_pass(m, f, no) {
  if (f === 'all') return true;
  if (f === 'res') return !no || jcd_kind(m) === 'result' || jcd_kind(m) === 'error' || (apvHeld(m) && chatChoiceSt(m) === 'open');  // lazy-ok: agent chat only; 2.290.0 B (#3157): + the jobs' end results / errors
  if (f === 'me') return !no || (apvHeld(m) && chatChoiceSt(m) === 'open');  // lazy-ok: 2.149.0 F (#2519): the agent chat's filter
  return !!no || (m.from !== 'agent' && m.kind !== 'notice' && !!jcd_addr(m.body));
}
const JCD_FILTERS = ['all', 'me', 'res', 'jobs'];  // 2.290.0 B (#3157)
const jcd_filter = () => { const f = S.chat.job || !S.jcd.n ? 'all' : LS.get('jcdFilt', 'all'); return JCD_FILTERS.includes(f) ? f : 'all'; };
const jcd_open = no => !!LS.get('jcdOpen', {})[no];
function jcd_setOpen(no, on) {
  const o = LS.get('jcdOpen', {}); if (on) o[no] = 1; else delete o[no];
  const ks = Object.keys(o); if (ks.length > 200) ks.sort((a, b) => a - b).slice(0, ks.length - 200).forEach(k => delete o[k]);
  LS.set('jcdOpen', o);
}
// chatMsgs(): the rows (row = the html of one message) with the job messages gathered into cards and the filter applied
function jcd_rows(a, row) {
  const ms = S.chat.msgs;
  if (S.chat.job) { S.jcd.map = new Map(); return jcs_rows(ms, row); }  // 2.153.0 (#1962): + its progress lines
  const byId = new Map(ms.map(m => [m.id, m])), of = new Map(), per = new Map(), last = new Map(), jn = new Map();
  ms.forEach((m, i) => {
    const no = jcd_jobNo(m, byId); if (!no) return;
    jn.set(m.id, no); if (m.choices) return;  // 2.144.0 A (#2416): a row of its own, but still a job's
    of.set(m.id, no); if (!per.has(no)) per.set(no, []); per.get(no).push(m); last.set(no, i);
  });
  S.jcd.map = of; S.jcd.n = new Set(jn.values()).size;
  if (!S.jcd.n) return ms.map(row);
  const f = jcd_filter(), out = [];
  ms.forEach((m, i) => {
    const no = of.get(m.id);
    if (f === 'res' && jn.has(m.id)) {  // 2.290.0 B (#3157): only the end result / error of a job, its name in front; no card
      const k = jcd_kind(m);
      if (jcd_pass(m, f, jn.get(m.id))) out.push(k === 'result' || k === 'error' ? jcr_html(jn.get(m.id), m, row) : row(m));
      return;
    }
    if (no) { if (f !== 'me' && f !== 'res' && last.get(no) === i) out.push(jcd_cardHtml(no, per.get(no), row)); return; }
    if (jcd_pass(m, f, jn.get(m.id) || 0)) out.push(row(m));
  });
  if (!out.length) out.push(`<div class="muted cmempty" data-k="jcdempty">${esc(tr('No messages yet.'))}</div>`);
  return out;
}
// 2.290.0 B (#3157): a job's end result in the filter "Me, <agent> and job results": the job's name, then the folded result
function jcr_html(no, m, row) {
  const j = S.jc.jobs[no] || {}; if (!S.jc.jobs[no]) jc_need(no);
  S.jcd.under.add(m.id);
  return `<div class="jcdrf" data-k="jcr${m.id}" style="--jcol:${jn9_jobColor({no, parent: +j.parent_id || 0, name: j.name || '', pname: j.parent_name || ''})}"><div class="jcdrn"><i class="jcddot" aria-hidden="true"></i><b>${esc(j.name || tr('Job #{0}', no))}</b></div>${jcd_resHtml(m, row)}</div>`;  // lazy-ok: only called by jcd_rows (agent chat loaded)
}
function jcd_line(body) {
  const l = String(body || '').split('\n').map(x => x.replace(/^[\s#>*_`-]+/, '').replace(/[*_`]+/g, '').trim()).find(Boolean) || '';
  return l.length > 160 ? l.slice(0, 159) + '…' : l;
}
// lazy-ok-begin: 2.149.0 F (#2519): a job's card in the agent chat (agentchat.js loaded)
function jcd_cardHtml(no, list, row) {
  const j = S.jc.jobs[no] || {}; if (!S.jc.jobs[no]) jc_need(no);
  const src = list.map(ux_jobOf).find(x => x && x.no === no) || {};
  const name = j.name || src.name || '', pj = +j.parent_id || src.parent || 0;
  const pname = pj ? j.parent_name || S.jc.jobs[pj]?.name || src.pname || '' : '';
  const jb = {no, parent: pj, name, pname};
  // 2.153.0 (#1962): under the card only the newest results / questions / errors (folded like 2.144.0 B) and the link to the
  // job's own chat; everything else stays folded in the card
  const vis = list.filter(m => JCD_SHOW.has(jcd_kind(m))).slice(-JCD_LINES), hid = list.filter(m => !vis.includes(m));
  vis.forEach(m => S.jcd.under.add(m.id)); hid.forEach(m => S.jcd.under.delete(m.id));
  const lm = list[list.length - 1], lk = jcd_kind(lm);
  const st = j.state || (lk === 'result' ? 'done' : lk === 'error' ? 'failed' : '');
  const ver = j.version ?? (JCD_VER_RE.exec(j.title || '') || [''])[0];
  const label = (pname && !name.toLowerCase().startsWith(pname.toLowerCase()) ? pname + ' / ' : '') + (name || tr('Job #{0}', no));
  const open = hid.length > 0 && jcd_open(no), hd = `<span class="jcdt"><i class="jcddot" aria-hidden="true"></i><b>${esc(label)}</b>${ver ? `<span class="jcdv">${esc(ver)}</span>` : ''}${st ? `<span class="jcdst st-${esc(st)}">${esc(tr(JCD_ST[st] || st))}</span>` : ''}<time>${esc(fmtWhen(lm.created_at))}</time>${hid.length ? ic('chev', 's') : ''}</span><span class="jcdl">${esc(jcd_line(lm.body))}</span>`;
  const head = hid.length
    ? `<button type="button" class="jcdh" data-jca="tog" data-jcd="${no}" aria-expanded="${open}" aria-controls="jcdh-${no}" title="${esc(tr(open ? 'Show less' : 'Show more'))}">${hd}</button>`
    : `<div class="jcdh">${hd}</div>`;
  return `<div class="jcd${open ? ' open' : ''}${jn9_part(jb) ? ' jpart' : ''}${st === 'failed' || st === 'stopped' ? ' jcderr' : ''}" data-k="jcd${no}" data-jcd="${no}" style="--jcol:${jn9_jobColor(jb)}">${head}${hid.length ? `<div class="jcdhist" id="jcdh-${no}"${open ? '' : ' hidden'}>${hid.map(row).join('')}</div>` : ''}${vis.map(m => jcd_resHtml(m, row)).join('')}${jcs_goHtml(no, j.agent_id)}</div>`;
}
// lazy-ok-end
// the end result / an error under the card: 5 lines, "Show more" for longer ones
function jcd_resHtml(m, row) {
  const long = jcf_long(m), more = S.jcd.more.has(m.id);
  if (typeof acset_get === 'function' && acset_get('jobs') === 'line' && jcd_line(m.body) !== String(m.body || '').trim()) {  // 2.233.0 A (#2848): chat setting "folded to the first line"
    const b = `<button type="button" class="linkbtn jcdmore" data-jca="more" data-jm="${m.id}" aria-expanded="${more}">${esc(tr(more ? 'Show less' : 'Show more'))}</button>`;
    return more ? `<div class="jcdres${jcd_kind(m) === 'error' ? ' jcdx' : ''}">${jcm_inBubble(row(m), b)}</div>`
      : `<div class="jcdres acset-j1${jcd_kind(m) === 'error' ? ' jcdx' : ''}"><button type="button" class="acset-jl" data-jca="more" data-jm="${m.id}" aria-expanded="false" title="${esc(tr('Show more'))}">${esc(jcd_line(m.body))}</button></div>`;
  }
  return `<div class="jcdres${long && !more ? ' jcdclamp' : ''}${jcd_kind(m) === 'error' ? ' jcdx' : ''}">${long ? jcm_inBubble(row(m), `<button type="button" class="linkbtn jcdmore" data-jca="more" data-jm="${m.id}" aria-expanded="${more}">${esc(tr(more ? 'Show less' : 'Show more'))}</button>`) : row(m)}</div>`;
}
// 2.144.0 B (#2417): "Fold long messages" for every message at once (a header icon, kept per device). Folded = the cut of the
// job result (jcd_resHtml: 5 lines + "Show more"); a message opened on its own stays open (S.jcd.more, the last 200 ids, kept
// per device); "Show less" on a single message switches the mode on for all.
const JCF_MAX = 200;
try { S.jcd.more = new Set(LS.get('jcfOpen', [])); } catch (e) { /* storage not readable: nothing open */ }
const jcf_on = () => LS.get('jcfOn', '') === '1';
const jcf_long = m => { const b = String(m.body || ''); return b.split('\n').length > 5 || b.length > 400; };
function jcf_save() {
  const a = [...S.jcd.more]; if (a.length > JCF_MAX) S.jcd.more = new Set(a.slice(-JCF_MAX));
  LS.set('jcfOpen', [...S.jcd.more]);
}
function jcf_more(id) { if (S.jcd.more.has(id)) S.jcd.more.delete(id); else S.jcd.more.add(id); jcf_save(); }
function jcf_fold(id) { S.jcd.more.delete(id); jcf_save(); jcf_set(true); }
function jcf_set(on) { LS.set('jcfOn', on ? '1' : ''); }
// 2.152.4 (#2659): only a job's messages fold (in the agent chat the ones S.jcd.map gives a job, in a job's own chat the job's
// own); the person's and the main agent's messages always stay open, without a button
const jcf_job = m => S.chat.job ? m.from === 'agent' : S.jcd.map.has(m.id);
// the row of a message with the cut (long messages only; a job result in a card is cut by jcd_resHtml)
function jcf_wrap(m, html) {
  if (m.kind === 'notice' || m.choices || S.chat.edit === m.id || !jcf_long(m) || !jcf_job(m)) return html;
  if (S.jcd.map.has(m.id) && S.jcd.under.has(m.id)) return html;  // 2.153.0 (#1962): under the card, not every result
  const on = jcf_on(), more = S.jcd.more.has(m.id), cut = on && !more;
  const btn = `<button type="button" class="linkbtn jcdmore" data-jca="${on ? 'more' : 'fold'}" data-jm="${m.id}"${on ? ` aria-expanded="${more}"` : ''}>${esc(tr(cut ? 'Show more' : 'Show less'))}</button>`;
  const h = jcm_inBubble(html, btn);
  return cut ? h.replace('class="cmsg ', 'class="cmsg jcfcut ') : h;
}
const jcf_row = fn => m => jcf_wrap(m, fn(m));
function jcf_toggle() { jcf_set(!jcf_on()); chatPatch({keep: true}); }  // 2.152.2 C (#2627): the chat menu's entry, no header icon any more
// 2.122.3 jcm (#2340): put the button right after the message text (end of the .cbub div), before steps / suggestion / time
function jcm_inBubble(html, btn) {
  const st = html.indexOf('<div class="cbub'); if (st < 0) return html + btn;
  const re = /<(\/?)div\b/g; re.lastIndex = st; let d = 0, x;
  while ((x = re.exec(html))) {
    d += x[1] ? -1 : 1;
    if (!d) { const e = html.indexOf('>', x.index) + 1; return html.slice(0, e) + btn + html.slice(e); }
  }
  return html + btn;
}
// 2.144.0 A (#2419): no filter row above the messages any more, on every width the icon in the header (jcd_fbtnHtml)
function jcd_filtHtml() { return ''; }
// 2.152.2 C (#2627): the header shows only search + the menu (dots); the filter, "Fold long messages" and "Always show steps" are
// entries of that menu (agentchat.js chat-head-menu). The menu icon carries the dot while the filter is not "All".
// (2.117.0 C #2260 / 2.144.0 A #2419 had the filter as an own icon.)
function jcd_fbtnHtml() {
  const t = tr('More'), dot = !S.chat.job && S.jcd.n && jcd_filter() !== 'all';
  return `<button type="button" class="iconbtn jcdfbtn" id="jcd-fbtn" data-act="chat-head-menu" aria-haspopup="menu" title="${esc(t)}" aria-label="${esc(t)}">${ic('dots', 's')}${dot ? '<i class="jcdfdot" aria-hidden="true"></i>' : ''}</button>`;
}
const jcd_filterName = () => ({all: tr('All'), me: tr('Only me and {0}', agentById(S.chat.aid)?.name || ''), res: tr('Me, {0} and job results', agentById(S.chat.aid)?.name || ''), jobs: tr('Jobs')})[jcd_filter()];
// the three choices as the submenu of the menu entry "Filter: …"
function jcd_choices() {
  const f = jcd_filter(), a = agentById(S.chat.aid);
  return [['all', tr('All')], ['me', tr('Only me and {0}', a?.name || '')], ['res', tr('Me, {0} and job results', a?.name || '')], ['jobs', tr('Jobs')]].map(([k, l]) => ({label: l, on: f === k, fn: () => jcd_setFilter(k)}));
}
// after every chat patch (agentchat.js chatPatch): the filter icon follows (shown once a job is in the chat)
function jcd_patch() {
  const c = $('#jcd-fbtn'), g = jcd_fbtnHtml(); if (c && !wk_sameEl(c, g)) c.outerHTML = g;
}
function jcd_setFilter(f) {
  if (!JCD_FILTERS.includes(f)) return;
  LS.set('jcdFilt', f); chatPatch({bottom: true}); jcd_patch();
}
// search hits / reply quotes / pins (collab.js msgJump): a message in a folded card or hidden by the filter comes into view
function jcd_reveal(id) {
  const no = S.jcd.map.get(+id), m = S.chat.msgs.find(x => x.id === +id);
  let ch = false;
  if (jcd_filter() !== 'all' && m) { const r = document.querySelector(`#chat-msgs [data-mid="a:${+id}"]`); if (!r) { LS.set('jcdFilt', 'all'); ch = true; } }
  if (no && m && !S.jcd.under.has(m.id) && !jcd_open(no)) { jcd_setOpen(no, true); ch = true; }
  if (m && jcf_long(m) && (jcf_on() || (no && S.jcd.under.has(m.id))) && !S.jcd.more.has(m.id)) { S.jcd.more.add(m.id); jcf_save(); ch = true; }  // 2.144.0 B (#2417): the target is unfolded
  if (ch) { chatPatch({keep: true}); jcd_patch(); }
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-jca]'); if (!b || b.tagName === 'SELECT' || !b.closest('#chat-msgs')) return;
  const box = $('#chat-msgs');
  // unfold / fold / more: the tapped card stays where it is on the screen (no jump to the bottom)
  const k = b.dataset.jca === 'tog' ? `.jcdh[data-jcd="${b.dataset.jcd}"]` : `.jcdmore[data-jm="${b.dataset.jm}"]`, y0 = b.getBoundingClientRect().top;
  if (b.dataset.jca === 'tog') jcd_setOpen(+b.dataset.jcd, !jcd_open(+b.dataset.jcd));
  else if (b.dataset.jca === 'more') { const id = +b.dataset.jm; jcf_more(id); }
  else if (b.dataset.jca === 'fold') jcf_fold(+b.dataset.jm);
  else return;
  const top = box ? box.scrollTop : 0;
  chatPatch({keep: true});
  const n = box && box.querySelector(k);
  if (box) { box.scrollTop = top + (n ? n.getBoundingClientRect().top - y0 : 0); S.chat.pin = chatNear(box); }
  n?.focus({preventScroll: true});
});

// ---- 2.153.0 (#1962): a chat of its own per job. The whole chat shows a job as its card (start line, the newest
// results, questions, errors under it) and the link "Open the job chat"; the job's own chat (?job=) shows its messages, what I
// typed there (sent with job_id, jc_field) and the job's progress lines (its log, S.chat.prog) as grey lines in time order.
function jcs_goHtml(no, aid) {
  return `<button type="button" class="linkbtn jcsgo" data-act="jc-open" data-jid="${no}" data-aid="${+aid || +S.chat.aid}"><span>${esc(tr('To the job chat'))}</span>${ic('arrow', 's')}</button>`;  // 2.290.0 B (#3145): quiet grey link at the right, arrow instead of the bubble
}
function jcs_rows(ms, row) {
  const lo = S.chat.more && ms.length ? Date.parse(ms[0].created_at) : -Infinity;
  const pr = (S.chat.prog || []).map((p, i) => ({...p, i, t: Date.parse(p.at)})).filter(p => p.t >= lo), out = [];
  let k = 0;
  for (const m of ms) {
    const t = Date.parse(m.created_at);
    while (k < pr.length && pr[k].t <= t) out.push(jcs_progHtml(pr[k++]));
    out.push(row(m));
  }
  while (k < pr.length) out.push(jcs_progHtml(pr[k++]));
  return out;
}
const jcs_progHtml = p => `<div class="cnotice jcsp" role="note" data-k="jp${p.i}_${p.t}" title="${esc(fmtWhen(p.at))}"><span>${esc(p.text || '')}</span></div>`;
