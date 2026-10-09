/* Kalmido web client: Agents, reactions, shared list tags, tidy suggestions.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.0.0: agents, reactions, shared list tags, tidy
// Agents are users of kind "agent" (an AI assistant, a bot) that work through the API. S.agents (from /api/state) = the
// agents I share a list with: status (dot on their avatar, header chip), running / waiting jobs, unread chat answers.
// The "Agents" view (module "agents", opt-in; reachable from the chip while agents exist) lists them with their jobs
// (Approve / Reject / Stop) and opens the chat (desktop: side panel, phone: own view). Kalmido never starts an agent:
// Since 2.4.1 (#376) there is no "Wake" button (POST …/wake stays in the API for agents without an event loop).
const agentById = id => (S.agents || []).find(a => a.id === +id);
const agentsOn = () => collab() && (S.agents || []).length > 0;
// 2.22.0 (#739): the Agents tab shows with the module on even before any list is shared with an agent (then it explains how)
const agentsTab = () => feat('agents') && collab();
const isAgentUser = id => !!agentById(id) || (S.tl.agents || []).includes(+id);
const AGENT_ST = {idle: N_('ready'), working: N_('working'), waiting: N_('waiting for you'), error: N_('error'), paused: N_('paused')};
const JOB_ST = {running: N_('running'), waiting: N_('waiting for approval'), done: N_('done'), failed: N_('failed'), stopped: N_('stopped')};
// 2.4.1 (#375): offline = no event poll for 5 minutes (online null: a webhook agent / never polled, so nobody can tell);
// the age counts on from the last state load, so the header turns "offline" without a reload
const agentAge = () => (Date.now() - (S.agentsAt || Date.now())) / 1000;
// 2.6.0 (K08): "not connected" (grey) instead of a green "ready" for an agent that never got in touch (no event poll, no API
// call) or has not for 5 minutes; a webhook agent is told about events, so only its explicit "offline" counts
const agentOffline = a => !!a && (a.online === false || (!a.webhook && (a.contact_age === null || a.contact_age === undefined || a.contact_age + agentAge() > 300)));
// 2.26.0 (#949): paused with a reason ("does not answer right now: …"); (#933) "connected, but no service running": its
// token is used (an interactive session) but nothing has collected its events for 10 minutes
const agentSt = a => !a.enabled ? tr('paused') : a.status === 'paused' ? tr('paused: {0}', a.pause_reason || a.status_text || '') : agentOffline(a) ? tr('not connected') : a.limit_reached ? tr('limit reached') : a.no_service && (a.status || 'idle') === 'idle' ? tr('connected, but no service running') : tr(AGENT_ST[a.status] || AGENT_ST.idle);  // 2.1.1 (#326)
const agentDot = id => { const a = agentById(id); return a ? `<i class="adot st-${!a.enabled || a.status === 'paused' ? 'paused' : agentOffline(a) ? 'offline' : esc(a.status)}" title="${esc(agentHstLine(a))}"></i>` : ''; };
const agentBadge = () => `<span class="abadge" title="${esc(tr('Agent: an AI assistant or bot that works through the API'))}">${ic('bot', 's')}${tr('Agent')}</span>`;
// agents of a list that can pick up this task (participant agents only their own tasks)
function taskAgents(t) {
  const l = t && listById(t.list_id); if (!l || !collab()) return [];
  return listPeople(l).filter(p => { const a = agentById(p.user_id); return a && a.enabled && (p.role !== 'participant' || t.assignee_id === a.id); }).map(p => agentById(p.user_id));
}
const listAgents = l => !l ? [] : listPeople(l).map(p => agentById(p.user_id)).filter(Boolean);

// ---- header chip (like the timer pill): "Claude · 2 running · 1 waiting"
// 2.6.0 (K08): an agent that is not connected (never polled, or no poll for 5 minutes) does not keep the chip busy with its
// "running" jobs or its last reported state; only what needs me (approval, unread chat) still shows
function agentBusy() {
  if (!agentsOn()) return null;
  const busy = (S.agents || []).filter(a => a.waiting || a.chat_unread || (!agentOffline(a) && (a.running || (a.enabled && ['working', 'waiting', 'error'].includes(a.status)))));
  if (!busy.length) return null;
  const run = busy.reduce((n, a) => n + (agentOffline(a) ? 0 : a.running), 0), wait = busy.reduce((n, a) => n + a.waiting, 0), unread = busy.reduce((n, a) => n + a.chat_unread, 0);
  return {busy, run, wait, unread, n: run + wait + unread || busy.length};
}
// ---- 2.6.1 (#402): one status dot per agent in the header, ALWAYS (not only while one works): green ready, blue working,
// yellow waiting for me, grey (hollow) offline / paused / not connected, red error / limit reached. The dots sit in the
// agent pill (with "Claude · 2 running …" next to them while something runs) and, from header level tl2 on with a timer
// running, in the merged status chip; hover = names + states, a tap = the menu with every agent. Settings > Agents >
// Overview > "In the header" picks the agents (setting agents_hidden, default: all shown).
const AG_HST = {ready: N_('ready'), working: N_('working'), waiting: N_('waiting for you'), offline: N_('offline'), error: N_('error'), paused: N_('paused')};
const HDOT_MAX = 5;
const agentHidden = () => new Set(String(S.settings?.agents_hidden || '').split(',').filter(Boolean).map(Number));
const shownAgents = () => { if (!agentsOn()) return []; const h = agentHidden(); return (S.agents || []).filter(a => !h.has(a.id) && wsAgentIn(a)); };  // 2.28.0 (#935): of the shown workspace
function agentHst(a) {
  if (!a.enabled || agentOffline(a)) return 'offline';
  if (a.status === 'paused') return 'paused';  // 2.26.0 (#949): paused with a reason
  if (a.status === 'error' || a.limit_reached) return 'error';
  if (a.status === 'working' || a.running) return 'working';
  if (a.status === 'waiting' || a.waiting) return 'waiting';
  return 'ready';
}
const agentHstLine = a => `${a.name}: ${agentSt(a)}${a.status_text && agentHst(a) !== 'offline' ? ' · ' + a.status_text : ''}`;
const hdot = st => `<i class="hdot hs-${st}" aria-hidden="true"></i>`;
function hdotsHtml(ags, max = HDOT_MAX) {
  if (!ags.length || S.bandOn) return '';
  const more = ags.length > max ? ags.length - (max - 1) : 0, show = more ? ags.slice(0, max - 1) : ags;
  return `<span class="hdots">${show.map(a => hdot(agentHst(a))).join('')}${more ? `<span class="hdm">+${more}</span>` : ''}</span>`;
}
function agDotsHtml(hint) {
  const ags = S.agents || [];
  if (!ags.length || !collab()) return '';
  const hid = agentHidden();
  return `<h4 id="s-agdots-h">${tr('In the header')}</h4>
    ${hint(tr('A dot per agent shows how it is: green ready, blue working, yellow waiting for you, grey offline, red error. Point at it or tap it for names and details. Untick an agent to leave its dot out.'))}
    <div class="agdots" role="group" aria-labelledby="s-agdots-h">${ags.map(a => `<label class="chkl agdl"><input type="checkbox" data-agvis="${a.id}" ${hid.has(a.id) ? '' : 'checked'}> ${hdot(agentHst(a))}<span>${esc(a.name)}</span><span class="muted">${esc(agentSt(a))}</span></label>`).join('')}</div>`;
}
function agentChip() {
  const ab = agentBusy(), ags = shownAgents();
  if (!ab && !ags.length) return '';
  const lines = ags.map(agentHstLine);
  let txt = '', attn = false, st = '';
  if (ab) {
    const {busy, run, wait, unread} = ab;
    const parts = [run && trn('{0} running', '{0} running', run), wait && trn('{0} waiting', '{0} waiting', wait), unread && trn('{0} new message', '{0} new messages', unread)].filter(Boolean);
    if (!parts.length) parts.push(agentSt(busy[0]));
    txt = [busy.length === 1 ? busy[0].name : tr('Agents'), ...parts].join(' · ');
    attn = !!(wait || unread); st = agentBusyState();
  }
  const lab = txt || `${tr('Agents')}: ${ags.map(a => `${a.name} ${agentSt(a)}`).join(', ')}`;
  const tip = [txt, ...(lines.length ? lines : agentStatusLines())].filter(Boolean).join('\n');
  // without dots (all hidden) the pill keeps its old look: bot / avatar + the ring while one works (with dots the ring is
  // hidden by CSS: the dots say it)
  // 2.7.2 (#417): a robot always leads (the agents' status), the dots follow it
  const lead = `<span class="abot" aria-hidden="true">${ic('bot', 's')}</span>` + (ags.length ? hdotsHtml(ags) : ab.busy.length === 1 ? av(ab.busy[0].id, ab.busy[0].name, 'avatar sm') : '');
  const ring = st === 'working' ? 'aspin' : st === 'waiting' ? 'await' : '';
  return `<button class="achip ${ab ? 'busy' : 'calm'} ${attn ? 'attn' : ''} ${ring || ''}" data-act="agent-chip" aria-haspopup="menu" title="${esc(tip)}" aria-label="${esc(lab)}">${lead}${ab ? `<span class="act">${esc(txt)}</span><span class="acn" aria-hidden="true">${ab.n}</span>` : ''}</button>`;  // 2.5.2 (K01): phones show the bot + a number
}
// ---- 2.8.0 (#434) the agent band under the list / project header (desktop + tablets): every shown agent of the view
// (a list: its agents; a folder: the agents of its lists; Inbox / Today / Next 7 days / All / Assigned: all shown agents)
// with its status dot, the task it works on, a thin progress line (the task's subtasks; working without subtasks = a running
// line) and the first job waiting for my approval (👍 = approve, ✕ = reject, the same as in the Agents view). Folds per
// device (LS agband). While the band is on screen the header leaves out its agent dots (no duplicate).
const BAND_KEYS = ['inbox', 'today', 'tomorrow', 'week', 'all', 'assigned', 'doable'];
function bandAgents() {
  if (isMobile() || S.route.mod !== 'tasks' || !feat('agents')) return [];
  const sh = shownAgents(); if (!sh.length) return [];
  const k = S.route.key;
  if (k.startsWith('l:')) { const l = listById(+k.slice(2)), ids = new Set(listAgents(l).map(a => a.id)); return sh.filter(a => ids.has(a.id)); }
  if (k.startsWith('folder:')) { const ids = new Set(folderLists(k.slice(7)).flatMap(listAgents).map(a => a.id)); return sh.filter(a => ids.has(a.id)); }
  // 2.31.0 (#1052): Today shows the band only when something needs me (an error, a question / approval); "offline" or
  // "ready" is already in the header chip
  if (k === 'today') return sh.filter(a => a.waiting || a.limit_reached || ['error', 'waiting'].includes(a.status) || ['error', 'waiting'].includes(agentHst(a)));
  return BAND_KEYS.includes(k) && !isRoadmap() ? sh : [];
}
S.bandJobs = {v: -1, items: [], busy: false};
function bandJobsLoad() {
  if (S.bandJobs.busy || S.bandJobs.v === S.v) return;
  S.bandJobs.busy = true;
  api('GET', '/api/agents/jobs?state=open').then(j => { S.bandJobs.items = j.jobs || []; }).catch(() => {}).finally(() => {
    S.bandJobs.busy = false; const sig = JSON.stringify(S.bandJobs.items.map(x => x.id + x.state)); S.bandJobs.v = S.v;
    if (sig !== S.bandJobs.sig) { S.bandJobs.sig = sig; if ($('#view .agband')) renderView(); else if (S.route.key === 'today' && S.route.mod === 'tasks') viewSafeRender(); }  // 2.13.0: + the Today card
  });
}
// 2.13.0 (#453 A6): the jobs that wait for ME (approve / reject, or a proposal of mine that is ready), for the agent pill's
// sheet and the card "Waiting for you" in Today (phones have no agent band)
function waitJobs() {
  if ((S.agents || []).some(a => a.waiting)) bandJobsLoad(); else return [];
  return (S.bandJobs.items || []).filter(j => j.state === 'waiting' && ((!j.kind && j.can_act) || (j.kind && S.me && j.user_id === S.me.id && j.proposal_state === 'ready')));
}
async function waitJobsFresh() {
  if (!(S.agents || []).some(a => a.waiting) || S.bandJobs.v === S.v) return waitJobs();
  try { S.bandJobs.items = (await api('GET', '/api/agents/jobs?state=open')).jobs || []; S.bandJobs.v = S.v; } catch { /* offline: what we have */ }
  return waitJobs();
}
// 2.32.0 (#1082): approvals say 👍 / 👎 (the emoji is decoration, the button's text names it)
const thumbIc = up => `<span class="thumb" aria-hidden="true">${up ? '\u{1F44D}' : '\u{1F44E}'}</span>`;
const waitJobBtns = j => j.kind ? `<button class="btn sm pri" data-act="prop-open" data-jid="${j.id}">${tr('Review the proposal')}</button>`
  : `<button class="btn sm pri" data-act="job-do" data-jid="${j.id}" data-a="approve">${thumbIc(true)} ${tr('Approve')}</button><button class="btn sm" data-act="job-do" data-jid="${j.id}" data-a="reject">${thumbIc(false)} ${tr('Reject')}</button>`;
function waitCard() {
  // 2.13.2 (#478 F14): like the agent pill and the chat, the card follows "agents share lists with me", not the Agents
  // module (that is the tab + the band): what waits for my approval never disappears with a switch
  if (S.route.key !== 'today' || !agentsOn()) return '';
  const js = waitJobs(); if (!js.length) return '';
  return `<section class="waitcard" aria-labelledby="wc-h"><h3 id="wc-h">${hdot('waiting')} ${esc(trn('{0} job waits for you', '{0} jobs wait for you', js.length))}</h3>
    ${js.slice(0, 5).map(j => `<div class="wcrow"><div class="wci"><b>${esc(j.title)}</b><span class="muted">${esc(j.agent_name)}${j.task_id ? ` · #${j.task_id} ${esc(j.task_title || '')}` : ''}</span></div><div class="wcb">${waitJobBtns(j)}</div></div>`).join('')}
    ${js.length > 5 ? `<a class="linkbtn" href="#agents">${esc(trn('and {0} more', 'and {0} more', js.length - 5))}</a>` : ''}</section>`;
}
function agBandHtml() {
  const ags = bandAgents(); if (!ags.length) return '';
  const open = LS.get('agband', true) !== false, ids = new Set(ags.map(a => a.id));
  if (ags.some(a => a.waiting)) bandJobsLoad();
  const job = ags.some(a => a.waiting) ? (S.bandJobs.items || []).find(j => ids.has(j.agent_id) && j.state === 'waiting' && ((!j.kind && j.can_act) || (j.kind && S.me && j.user_id === S.me.id && j.proposal_state === 'ready'))) : null;
  const cell = a => {
    const st = agentHst(a), t = a.status_task ? taskById(a.status_task) : null, kids = t ? children(t.id) : [];
    const p = kids.length ? Math.round(100 * kids.filter(x => x.status).length / kids.length) : null;
    // 2.30.0 (#1039): a status without a task (a chat answer) stays in the chat and the header chip, not in a list's band
    const what = t ? `<span class="mono">#${t.id}</span> ${esc(t.title)}` : esc(st === 'offline' ? agentSt(a) : '–');
    return `<button class="agb-a hs-${st}" data-act="team-agent" data-aid="${a.id}" title="${esc(agentHstLine(a))}"><span class="agb-h">${hdot(st)}<b>${esc(a.name)}</b><span class="muted">${esc(tr(AG_HST[st]))}</span></span><span class="agb-t">${what}</span><span class="agb-p ${st === 'working' && p === null ? 'run' : ''}" aria-hidden="true"><i style="width:${p ?? (st === 'working' ? 40 : 0)}%"></i></span></button>`;
  };
  // 2.13.2 (#478 N7): in Today the card "… waits for you" shows the same jobs: the band leaves its waiting cell out there
  const wait = job && !(S.route.key === 'today' && waitCard()) ? `<div class="agb-w" role="group" aria-label="${esc(tr('{0} waits for you', job.agent_name))}"><div class="agb-wi"><span class="agb-h">${hdot('waiting')}<b>${esc(tr('{0} waits for you', job.agent_name))}</b></span><span class="agb-t">${job.task_id ? `<span class="mono">#${job.task_id}</span> ` : ''}${esc(job.title)}</span></div>${job.kind
    ? `<button class="btn sm pri" data-act="prop-open" data-jid="${job.id}">${tr('Review the proposal')}</button>`
    : `<button class="btn sm pri agb-ok" data-act="job-do" data-jid="${job.id}" data-a="approve" aria-label="${esc(tr('Approve'))}">${thumbIc(true)} ${tr('Yes|approve')}</button><button class="iconbtn agb-no" data-act="job-do" data-jid="${job.id}" data-a="reject" title="${esc(tr('Reject'))}" aria-label="${esc(tr('Reject'))}">${thumbIc(false)}</button>`}</div>` : '';
  const sum = ags.map(a => hdot(agentHst(a))).join('');
  return `<section class="agband ${open ? '' : 'closed'}" aria-label="${esc(tr('Agents live'))}"><button class="agb-tog" data-act="agband" aria-expanded="${open}" title="${esc(open ? tr('Fold the agents') : tr('Show the agents'))}" aria-label="${esc(open ? tr('Fold the agents') : tr('Show the agents'))}">${ic('chev', 's')}${open ? '' : `<span class="agb-sum">${sum}<span>${esc(ags.map(a => a.name).join(', '))}</span></span>`}</button>${open ? `<div class="agb-cells">${ags.map(cell).join('')}${wait}</div>` : (job ? `<span class="agb-wmini">${hdot('waiting')}${esc(tr('{0} waits for you', job.agent_name))}</span>` : '')}</section>`;
}
// 2.6.0 (K01): the agent pill and the running indicator merged into one compact chip (shown from header level tl2 on):
// bot + number, dot + time; a tap opens the one that is there, or a menu with both
function stChip() {
  const ab = agentBusy(), ags = shownAgents(), it = runItems();
  if ((!ab && !ags.length) || !it.length) return '';  // only one of them: its own pill shrinks instead (tl1)
  const x = it[0], who = ab ? (ab.busy.length === 1 ? ab.busy[0].name : tr('Agents')) : ags.map(a => `${a.name} ${agentSt(a)}`).join(', ');
  const lab = [who, ...it.map(r => `${tr(RUN_KIND[r.k][1])} ${r.txt}`)].join(' · ');
  const st = ab ? agentBusyState() : '';
  return `<button class="stchip ${ab && (ab.wait || ab.unread) ? 'attn' : ''} ${st === 'working' ? 'aspin' : ''}" data-act="st-chip" title="${esc([lab, ...ags.map(agentHstLine)].join('\n'))}" aria-label="${esc(lab)}" aria-haspopup="menu"><span class="sta"><span class="abot">${ic('bot', 's')}</span>${ags.length ? hdotsHtml(ags, 3) : ''}${ab ? `<b>${ab.n}</b>` : ''}</span><span class="str k-${x.k}"><span class="rec"></span>${it.length === 1 ? `<span ${x.attr}>${x.txt}</span>` : `<b>${it.length}</b>`}</span></button>`;
}
function stChipMenu(a) {
  const ab = agentBusy(), ags = shownAgents(), it = runItems();
  if (!ab && !ags.length) return runPop(a);
  if (!it.length) return agentChipMenu(a);
  const albl = ab ? [ab.busy.length === 1 ? ab.busy[0].name : tr('Agents'), ...[ab.run && trn('{0} running', '{0} running', ab.run), ab.wait && trn('{0} waiting', '{0} waiting', ab.wait), ab.unread && trn('{0} new message', '{0} new messages', ab.unread)].filter(Boolean)].join(' · ') : tr('Agents');
  menu(a, [...it.map(r => ({label: `${tr(RUN_KIND[r.k][1])} · ${r.txt} · ${r.title}`, icon: RUN_KIND[r.k][0], fn: () => runPop($('#top [data-act="st-chip"]') || a)})),
    '-', {label: albl, icon: 'bot', fn: () => agentChipMenu($('#top [data-act="st-chip"]') || a)}]);
}
// 2.6.1 (#402): every agent with its dot and state (shown ones; all of them while none is shown), then the Agents view,
// the chats and where to choose the dots
async function agentChipMenu(a) {
  const ags = S.agents || [], sh = shownAgents(), list = sh.length ? sh : ags;
  // 2.13.0 (#453 A6): what waits for me comes first, with its buttons
  const wj = (await waitJobsFresh()).slice(0, 3);
  const wait = wj.flatMap(j => [{label: `${tr('{0} waits for you', j.agent_name)}: ${j.title}`, dot: 'waiting', cls: 'minfo mwait', fn: () => go('agents')},
    j.kind ? {label: tr('Review the proposal'), icon: 'bot', fn: () => propOpen(j.id)}
      : {row: [{label: '\u{1F44D} ' + tr('Approve'), cls: 'pri', fn: () => jobDo(j.id, 'approve')}, {label: tr('Reject'), icon: 'x', fn: () => jobDo(j.id, 'reject')}]}, '-']);
  menu(a, [...wait, ...list.map(x => ({label: agentHstLine(x), dot: agentHst(x), cls: 'minfo', fn: () => x.enabled ? chatOpen(x.id) : go('agents')})),
    '-', {label: tr('Agents and jobs'), icon: 'bot', fn: () => go('agents')},
    ...ags.filter(x => x.enabled).map(x => ({label: tr('Chat with {0}', x.name) + (x.chat_unread ? ` (${x.chat_unread})` : ''), icon: 'comment', fn: () => chatOpen(x.id)})),
    {label: tr('Choose the agents shown…'), icon: 'gear', fn: () => settingsModal('agentdots')}]);
}

// ---- reactions + suggestions in the comments
// 👍 👎 ❤️ (stored as up / down / heart) or any single emoji (stored as itself, "+");
// 👍 / 👎 by an approver on an agent's comment = approval / rejection
const RX = [['up', '\u{1F44D}', N_('Agree / go')], ['down', '\u{1F44E}', N_('Disagree / no')], ['heart', '❤️', N_('Love it')]];
const RX_MORE = ['\u{1F602}', '\u{1F389}', '\u{1F440}', '\u{1F64F}', '\u{1F525}', '\u{1F4AF}', '\u{1F914}', '✅', '\u{1F680}', '\u{1F605}', '\u{1F44F}', '\u{1F622}', '\u{1F4A1}'];
const rxEmoji = k => (RX.find(x => x[0] === k) || [])[1] || k;
const rxName = k => { const x = RX.find(y => y[0] === k); return x ? tr(x[2]) : k; };
function reactHtml(c, ro) {
  if (!cmSocial(taskById(S.tl.id))) return '';  // #315: reactions are for people working together
  const rs = c.reactions || [];
  if (S.me && c.user_id === S.me.id) ro = true;  // 2.23.0 (#823): no reactions on my own comment (the others' stay visible)
  const pill = r => {
    const mine = r.users.some(u => S.me && u.id === S.me.id), names = r.users.map(u => u.name).join(', ');
    return `<button class="rx ${mine ? 'on' : ''}" data-act="c-react" data-cid="${c.id}" data-e="${esc(r.emoji)}" title="${esc(`${names} · ${rxName(r.emoji)}`)}" aria-label="${esc(rxName(r.emoji) + ': ' + names)}" aria-pressed="${mine}" ${ro ? 'disabled' : ''}>${esc(rxEmoji(r.emoji))}<span class="rxn" data-act="c-react-who" data-cid="${c.id}" data-e="${esc(r.emoji)}">${r.count}</span></button>`;
  };
  const quick = ro ? [] : RX.slice(0, 2).filter(([k]) => !rs.some(r => r.emoji === k)).map(([k, em, name]) =>
    `<button class="rx add" data-act="c-react" data-cid="${c.id}" data-e="${k}" title="${esc(tr(name))}" aria-label="${esc(tr(name))}">${em}</button>`);
  const more = ro ? '' : `<button class="rx add rxplus" data-act="c-react-more" data-cid="${c.id}" title="${esc(tr('React with an emoji'))}" aria-label="${esc(tr('React with an emoji'))}">${ic('plus', 's')}</button>`;
  // 2.13.2 (#478 F5): like the chat: given reactions stay as pills, the quick 👍 👎 + appear on hover / keyboard focus
  // (desktop) or a long press (touch) as a small bar over the comment's corner
  const q = quick.join('') + more;
  return (rs.length || q ? `<div class="rxbar">${rs.map(pill).join('')}${q ? rxTog('k' + c.id) : ''}</div>` : '') + (q ? `<div class="rxbar cmrxq" role="group" aria-label="${esc(tr('React'))}">${q}</div>` : '');
}
function reactPicker(anchor, cid, fn = null) {
  const p = openPop(anchor, `<div class="rxpick" role="dialog" aria-label="${esc(tr('Reactions'))}"><div class="rxgrid">${[...RX.map(x => [x[0], x[1], tr(x[2])]), ...RX_MORE.map(e => [e, e, e])].map(([k, em, n]) => `<button data-rx="${esc(k)}" title="${esc(n)}" aria-label="${esc(n)}">${em}</button>`).join('')}</div>
    <div class="rxcustom"><input id="rx-in" placeholder="${esc(tr('Any emoji'))}" maxlength="16" autocomplete="off" aria-label="${esc(tr('Any emoji'))}"><button class="btn sm" data-rx-ok>${tr('React')}</button></div></div>`);
  const go = v => { v = String(v || '').trim(); if (!v) return; closePop(); if (fn) fn(v); else commentReact(cid, v); };
  p.onclick = e => { const b = e.target.closest('[data-rx]'); if (b) go(b.dataset.rx); else if (e.target.closest('[data-rx-ok]')) go($('#rx-in', p).value); };
  $('#rx-in', p)?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go(e.target.value); } });
}
function sugHtml(c, ro) {
  const s = c.suggestion; if (!s) return '';
  if (s.kind === 'merge_request') return mrHtml(c, s, ro);  // 2.2.0 (#339)
  if (s.kind === 'integrate' || s.kind === 'deploy') return gateHtml(c, s, ro);  // 2.26.0 (#949)
  const t = taskById(S.sel), sec = s.section_id && S.sections.find(x => x.id === s.section_id);
  const pr = {none: N_('None'), low: N_('Low'), medium: N_('Medium'), high: N_('High')};
  const rows = [s.title && [tr('Title'), esc(s.title)], s.notes && [tr('Notes'), esc(s.notes).replace(/\n/g, '<br>')], sec && [tr('Section'), esc(sec.name)],
    s.list_tags?.length && [tr('List tags'), s.list_tags.map(g => ltagChip(g, t?.list_id)).join(' ')], s.priority && [tr('Priority'), esc(tr(pr[s.priority] || s.priority))]].filter(Boolean);
  const st = s.state === 'applied' ? tr('applied') : s.state === 'rejected' ? tr('rejected') : '';
  return `<div class="sug ${esc(s.state || 'open')}"><div class="sugh">${ic('bot', 's')}<b>${tr('Suggestion')}</b>${st ? `<span class="muted">· ${st}</span>` : ''}</div>
    <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
    ${s.state === 'open' && !ro && S.tl.can_write ? `<div class="sugb"><button class="btn sm pri" data-act="c-apply" data-cid="${c.id}">${ic('check', 's')} ${tr('Apply')}</button><span class="muted">${tr('or react with 👍 · the original text stays at the top of the notes')}</span></div>` : ''}</div>`;
}
function tlComment(cid) { return (S.tl.comments || []).find(x => x.id === cid); }
async function commentReact(cid, e) {
  const c = tlComment(cid); if (!c) return;
  let j;
  try { j = await capi('POST', `/api/comments/${cid}/reactions`, {emoji: e}); } catch { return; }
  c.reactions = j.reactions; if (j.suggestion !== undefined) c.suggestion = j.suggestion;
  drawTimeline();
  if (j.applied) { toast(tr('Suggestion applied')); await load(); render(); }
  else if (j.approval) { toast(j.approval === 'approved' ? tr('Approved') : tr('Rejected')); if (S.sel) loadTimeline(S.sel); }
}
function commentReactWho(cid, e) {
  const r = (tlComment(cid)?.reactions || []).find(x => x.emoji === e); if (!r) return;
  toast(`${rxEmoji(e)} ${r.users.map(u => u.name).join(', ')}`);
}
async function commentApply(cid) {
  try { await capi('POST', `/api/comments/${cid}/apply`); } catch { return; }
  toast(tr('Suggestion applied')); await load(); render(); if (S.sel) loadTimeline(S.sel);
}

// ---- shared list tags (tags of a list, visible to all its members; personal tags stay personal)
const listTags = lid => listById(lid)?.tags || [];
const ltagColor = (name, lid) => listTags(lid).find(x => x.name.toLowerCase() === String(name).toLowerCase())?.color || '';
function ltagChip(g, lid, cls = 'tag ltag') {
  const c = cssColor(ltagColor(g, lid));
  return `<span class="${cls}" ${c ? `style="--tc:${c}"` : ''} title="${esc(tr('List tag: visible to everyone in the list'))}">#${esc(g)}</span>`;
}
const ptagChip = (g, lid) => listById(lid)?.shared && collab() ? `<span class="tag ptag" title="${esc(tr('Personal tag: only visible to you'))}">${ic('user', 's')}#${esc(g)}</span>` : `<span class="tag">#${esc(g)}</span>`;
const hasTag = (t, g) => t.tags.includes(g) || (t.ltags || []).some(x => x.toLowerCase() === String(g).toLowerCase());
// the tag editor of the detail panel: list tags first (colour dot), personal tags with a person icon, a new name becomes
// a list tag when it matches one of the list, else a personal tag; a personal tag can be made a list tag (↑)
function tagEditHtml(t, ro) {
  const l = listById(t.list_id), shared = !!l?.shared && collab(), lt = listTags(t.list_id), mayList = canEditList(t.list_id);
  const lpills = (t.ltags || []).map(g => { const c = cssColor(ltagColor(g, t.list_id)); return `<span class="tagpill ltag" ${c ? `style="--tc:${c}"` : ''} title="${esc(tr('List tag: visible to everyone in the list'))}">#${esc(g)}${ro ? '' : `<button data-act="ltag-rm" data-tag="${esc(g)}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>`}</span>`; }).join('');
  const ppills = t.tags.map(g => `<span class="tagpill ${shared ? 'ptag' : ''}" ${shared ? `title="${esc(tr('Personal tag: only visible to you'))}"` : ''}>${shared ? ic('user', 's') : ''}#${esc(g)}${ro ? '' : `${(shared || (collab() && l && !l.is_inbox)) && mayList ? `<button data-act="tag-promote" data-tag="${esc(g)}" title="${esc(tr('Make it a list tag (visible to everyone in the list)'))}" aria-label="${esc(tr('Make it a list tag'))}">${ic('users', 's')}</button>` : ''}<button data-act="tag-rm" data-tag="${esc(g)}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>`}</span>`).join('');
  const own = [...new Set([...S.tasks.values()].flatMap(x => x.tags))].filter(g => !lt.some(x => x.name.toLowerCase() === g.toLowerCase()));
  return `<div class="tagedit">${lpills}${ppills}${ro ? '' : `<input id="d-tag" placeholder="${tr('+ Tag')}" aria-label="${esc(tr('Tags'))}" list="taglist" enterkeyhint="done" autocomplete="off">`}<datalist id="taglist">${lt.map(x => `<option value="${esc(x.name)}" label="${esc(tr('List tag'))}">`).join('')}${own.map(g => `<option value="${esc(g)}" ${shared ? `label="${esc(tr('Personal'))}"` : ''}>`).join('')}</datalist></div>`;
}
async function tagAdd(t, v) {
  const lt = listTags(t.list_id).find(x => x.name.toLowerCase() === v.toLowerCase());
  if (lt) { if (!(t.ltags || []).includes(lt.name)) await patchTask(t.id, {ltags: [...(t.ltags || []), lt.name]}); }
  else await patchTask(t.id, {tags: [...t.tags, v]});
}
async function tagPromote(t, g) {
  if (!await askConfirm(tr('Make {0} a list tag?', '#' + g), tr('Everyone in “{0}” sees it; your personal tag {1} on the tasks of this list becomes this list tag.', lname(listById(t.list_id)), '#' + g), {ok: tr('Make it a list tag')})) return;
  try { const j = await api('POST', `/api/lists/${t.list_id}/tags/promote`, {tag: g}); toast(trn('{0} task now has the list tag', '{0} tasks now have the list tag', j.count)); } catch { return; }
  await load(); render();
}
// list dialog: the list tags (members with edit rights manage them) and "Agent may tidy up entries"
function ltagsBoxHtml(l) {
  const lt = listTags(l.id), may = canEditList(l.id);
  return `${lt.length ? lt.map(x => `<div class="mrow" data-ltid="${x.id}"><span class="ltsw" style="${cssColor(x.color) ? 'background:' + cssColor(x.color) : ''}"></span><span class="n">#${esc(x.name)}</span>${may ? `<button class="iconbtn" data-lt="color" title="${tr('Color')}">${ic('palette', 's')}</button><button class="iconbtn" data-lt="ren" title="${tr('Rename')}">${ic('edit', 's')}</button><button class="iconbtn danger" data-lt="del" title="${tr('Delete')}">${ic('trash', 's')}</button>` : ''}</div>`).join('')
    : `<div class="muted mhint">${tr('No list tags yet.')}</div>`}${may ? `<div class="row"><input id="l-ltnew" placeholder="${tr('New list tag')}" maxlength="60"><button class="btn sm" data-lt="new">${ic('plus', 's')} ${tr('Add')}</button></div>` : ''}`;
}
function ltagsWire(md, lid) {
  const redraw = () => { const b = $('#l-ltags', md); if (b) b.innerHTML = ltagsBoxHtml(listById(lid)); };
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-lt]'); if (!b) return;
    const a = b.dataset.lt, tid = +b.closest('[data-ltid]')?.dataset.ltid, x = listTags(lid).find(y => y.id === tid);
    try {
      if (a === 'new') { const v = $('#l-ltnew', md).value.trim().replace(/^#/, ''); if (!v) return; await api('POST', `/api/lists/${lid}/tags`, {name: v}); }
      if (a === 'ren' && x) { const v = await askPrompt(tr('Rename the list tag'), x.name, {ok: tr('Rename')}); if (!v || v.trim() === x.name) return; await api('PATCH', `/api/list-tags/${tid}`, {name: v.trim().replace(/^#/, '')}); }
      if (a === 'color' && x) {
        const p = openPop(b, `<div class="colors ltcols" role="group" aria-label="${esc(tr('Color'))}">${LCOLORS.map(c => `<button data-c="${c}" style="background:${c || 'var(--bg4)'}" class="${(x.color || '') === c ? 'on' : ''}" aria-label="${esc(c || tr('No color'))}"></button>`).join('')}</div>`);
        p.onclick = async ev => {
          const cb = ev.target.closest('[data-c]'); if (!cb) return;
          closePop();
          try { await api('PATCH', `/api/list-tags/${tid}`, {color: cb.dataset.c}); await load(); render(); redraw(); } catch { /* shown */ }
        };
        return;
      }
      if (a === 'del' && x) {
        if (!await askConfirm(tr('Delete the list tag {0}?', '#' + x.name), tr('It is removed from every task of the list, for everyone.'), {ok: tr('Delete'), danger: true})) return;
        await api('DELETE', `/api/list-tags/${tid}`);
      }
    } catch { return; }
    await load(); render(); redraw();
  });
  md.addEventListener('keydown', e => { if (e.target.id === 'l-ltnew' && e.key === 'Enter') { e.preventDefault(); $('[data-lt="new"]', md)?.click(); } });
}
// 2.26.0: one agent per list. Sets THE agent of list lid (null = none) in one step (PUT /api/lists/<id>/agent: the old one
// leaves, the new one joins) and offers Undo (back to the previous agent). ags: [{id, name}] for the message.
async function setListAgent(lid, aid, ags = [], after = null) {
  const nm = id => ags.find(a => a.id === id)?.name || agentById(id)?.name || '';
  if (aid && !await agSafeFirst()) return false;  // 2.30.0 (#920)
  let j; try { j = await bridgeTry(ok => api('PUT', `/api/lists/${lid}/agent`, {agent_id: aid, ...(ok ? {bridge_ok: true} : {})})); } catch { await load(); render(); return false; }  // 2.30.0 (#919)
  await load(); render();
  const prev = j.previous ?? null; if (prev === aid) return true;
  const back = async () => { try { await api('PUT', `/api/lists/${lid}/agent`, {agent_id: prev}); } catch { /* shown */ } await load(); render(); after?.(); };
  toast(aid ? tr('{0} now works in “{1}”', nm(aid), lname(listById(lid) || {name: ''})) : tr('No agent in “{0}” any more', lname(listById(lid) || {name: ''})), back);
  return true;
}
const TIDY = [['off', N_('Off')], ['suggest', N_('Suggest (apply with 👍)')], ['auto', N_('Automatically')]];
// 2.4.1 (#379): exactly one agent tidies up a list: one of its agents with edit rights (participants / viewers cannot change
// other people's tasks); tidy_agent_id from the server is the chosen one or the first candidate
const tidyCands = l => listPeople(l).filter(p => ['owner', 'admin', 'edit'].includes(p.role) && (p.agent || agentById(p.user_id))).map(p => ({id: p.user_id, name: agentById(p.user_id)?.name || p.name})).sort((a, b) => a.id - b.id);
const tidyAgentSel = (l, id, attrs = '') => { const cs = tidyCands(l); return cs.length ? `<select ${id ? `id="${id}"` : ''} ${attrs} ${(l.agent_tidy || 'off') === 'off' ? 'disabled' : ''}>${cs.map(a => `<option value="${a.id}" ${a.id === l.tidy_agent_id ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}</select>` : ''; };
function tidyRowHtml(l) {
  const ags = listAgents(l); if (!ags.length) return '';
  const agentOwned = !!agentById(l.owner_id), may = ['owner', 'admin'].includes(l.role || 'owner') || (agentOwned && canEditList(l.id));
  const cands = tidyCands(l), who = cands.find(a => a.id === l.tidy_agent_id) || cands[0];
  // 2.26.0 (#928): who may address the list's agents (owner / list admins switch; default off)
  const sw = (id, k, label, hint) => `<label class="chkl swl agacc"><span class="swc"><input type="checkbox" role="switch" id="${id}" data-agacc="${k}" ${l[k] ? 'checked' : ''} ${may ? '' : 'disabled'}><span class="swt" aria-hidden="true"></span></span><span>${label}</span></label>
    <div class="shint aghint">${hint}</div>`;  // 2.32.0 (#1058): the explanation behind the (i) at the switch
  const acc = sw('l-agm', 'agent_members', tr('Members may see and use the agent'), tr('Off: only you and list admins can chat with the agent, @mention it or assign it tasks here. Members still see what it does.'))
    + sw('l-agp', 'agent_peers', tr('Agents may address each other'), tr('Off: what an agent writes or assigns here never reaches another agent. Instructions only ever come from people.'))
    // 2.34.0 (#266): "Agent follows up": once a day the list's agents get its tasks lying idle and suggest a follow-up as a comment
    + sw('l-agf', 'agent_followup', tr('Agent follows up'), tr('Once a day the agent gets the tasks of this list that lie idle and asks about them in a comment or drafts a reminder. Nothing is sent to anyone outside. Off by default.'));
  return `${acc}<div class="row"><label for="l-tidy">${tr('Agent may tidy up entries')}</label><select id="l-tidy" ${may && cands.length ? '' : 'disabled'}>${TIDY.map(([k, n]) => `<option value="${k}" ${(l.agent_tidy || 'off') === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    ${cands.length > 1 ? `<div class="row"><label for="l-tidyag">${tr('Tidy up by')}</label>${tidyAgentSel(l, 'l-tidyag', may ? '' : 'disabled')}</div>` : ''}
    <div class="shint lhint">${cands.length ? tr('{0} turns long, quickly typed entries into a short title and suggests section, tags and priority. The original text always stays at the top of the notes; every change is in the history.', esc(who.name))
      : tr('Give an agent of this list edit rights first')}</div>${listenRowHtml(l, ags, may)}`;
}
// 2.13.1 (#471): "Agent reads every comment": the chosen agents get every comment of a person in this list (not only on
// tasks they follow or where they are @mentioned). 2.30.0 (#1034): "Agent listens in": also every task created in or moved
// into the list; on by default in software projects (l.listen_default), off elsewhere (then only @mentions, assignments and
// wake reach it); a switch in every list. Tidying is its own setting above.
const listenOn = l => listAgents(l).some(a => (l.listen_agent_ids || []).includes(a.id));
const listenLabel = l => listenOn(l) ? tr('Agent listens in') : tr('Agent only via @');
function listenRowHtml(l, ags, may) {
  const on = new Set(l.listen_agent_ids || []);
  const dflt = l.listen_default ? tr('Default for software projects: on.') : tr('Default for this kind of list: off, the agent reacts only to an @mention, an assignment or a wake.');
  // 2.27.0 (#964): one agent per list: a plain switch like the two above (lists from before 2.26 with several agents keep the boxes)
  if (ags.length === 1) return `<div class="lsnrow lsn1"><label class="chkl swl agacc lsnag"><span class="swc"><input type="checkbox" role="switch" data-lsn="${ags[0].id}" ${on.has(ags[0].id) ? 'checked' : ''} ${may ? '' : 'disabled'}><span class="swt" aria-hidden="true"></span></span><span>${tr('Agent listens in')}</span></label></div>
    <div class="shint aghint">${tr('{0} gets every new or moved task and every comment people write in this list, without an @mention (only tasks it can see).', esc(ags[0].name))} ${esc(dflt)}</div>`;
  return `<div class="row lsnrow" role="group" aria-labelledby="l-lsn-h"><span class="lbl" id="l-lsn-h">${tr('Agent listens in')}</span><div class="lsnags">${ags.map(a =>
    `<label class="lsnag"><input type="checkbox" data-lsn="${a.id}" ${on.has(a.id) ? 'checked' : ''} ${may ? '' : 'disabled'}><span>${esc(a.name)}</span></label>`).join('')}</div></div>
    <div class="shint lhint">${tr('The checked agents get every new or moved task and every comment people write in this list, without an @mention (only tasks they can see).')} ${esc(dflt)}</div>`;
}
function tidyWire(md, lid) {
  md.addEventListener('change', async e => {
    const acc = e.target.dataset?.agacc;  // 2.26.0 (#928)
    if (acc) {
      try { await api('PATCH', `/api/lists/${lid}`, {[acc]: e.target.checked}); toast(tr('Saved')); await load(); render(); }
      catch { e.target.checked = !!listById(lid)?.[acc]; }
      return;
    }
    if (e.target.dataset?.lsn) {  // 2.13.1 (#471)
      const ids = $$('[data-lsn]', md).filter(x => x.checked).map(x => +x.dataset.lsn);
      try { await api('PATCH', `/api/lists/${lid}`, {listen_agent_ids: ids}); toast(tr('Saved')); await load(); render(); }
      catch { const l = listById(lid); $$('[data-lsn]', md).forEach(x => { x.checked = (l?.listen_agent_ids || []).includes(+x.dataset.lsn); }); }
      return;
    }
    const id = e.target.id; if (id !== 'l-tidy' && id !== 'l-tidyag') return;
    try {
      await api('PATCH', `/api/lists/${lid}`, id === 'l-tidy' ? {agent_tidy: e.target.value} : {tidy_agent_id: +e.target.value});
      toast(tr('Saved')); await load(); render();
      const l = listById(lid), box = $('#l-tidyrow', md); if (l && box) box.innerHTML = tidyRowHtml(l);
    } catch { const l = listById(lid); e.target.value = id === 'l-tidy' ? l?.agent_tidy || 'off' : String(l?.tidy_agent_id ?? ''); }
  });
}

// ---- the Agents view: agents with status, jobs (Approve / Reject / Stop), chat
S.jobs = {items: null, f: LS.get('jobsFilter', 'open'), err: null};
async function loadJobs() {
  try { S.jobs.items = (await api('GET', '/api/agents/jobs' + (S.jobs.f === 'open' ? '?state=open' : ''))).jobs; S.jobs.err = null; }
  catch (e) { S.jobs.err = e instanceof Offline ? tr('Only available online.') : e.message; S.jobs.items = S.jobs.items || []; }
  if (S.route.mod === 'agents') renderView();
}
function jobHtml(j) {
  const mine = j.kind && S.me && j.user_id === S.me.id;  // 2.3.0: a proposal I asked for: reviewed in its dialog
  const acts = [mine && ['requested', 'ready'].includes(j.proposal_state) && `<button class="btn sm ${j.proposal_state === 'ready' ? 'pri' : ''}" data-act="prop-open" data-jid="${j.id}">${ic('bot', 's')} ${j.proposal_state === 'ready' ? tr('Review the proposal') : tr('Open')}</button>`,
    !j.kind && j.can_act && j.state === 'waiting' && `<button class="btn sm pri" data-act="job-do" data-jid="${j.id}" data-a="approve">${thumbIc(true)} ${tr('Approve')}</button>`,
    !j.kind && j.can_act && j.state === 'waiting' && `<button class="btn sm" data-act="job-do" data-jid="${j.id}" data-a="reject">${thumbIc(false)} ${tr('Reject')}</button>`,
    j.can_stop && ['running', 'waiting'].includes(j.state) && `<button class="btn sm danger" data-act="job-do" data-jid="${j.id}" data-a="stop">${ic('stop', 's')} ${tr('Stop')}</button>`].filter(Boolean).join('');
  const last = String(j.log || '').trim().split('\n').pop();
  return `<div class="job st-${esc(j.state)}"><div class="jobh"><span class="jst">${esc(tr(JOB_ST[j.state] || j.state))}</span><b>${esc(j.title)}</b><span class="spacer"></span><span class="muted">${esc(j.agent_name)} · ${esc(relTime(j.updated_at))}</span></div>
    ${j.task_id ? `<button class="runtask" data-act="open-id" data-id="${j.task_id}">${ic('arrow', 's')}<span>${esc(j.task_title || '')}</span></button>` : ''}
    ${j.log ? `<details class="joblog"><summary>${esc(last.slice(0, 140))}</summary><pre>${esc(j.log)}</pre></details>` : ''}
    ${j.steps ? jobStepsHtml(j.id, j.steps) : ''}
    ${j.action && !(j.action === 'approve' && j.state === 'waiting') ? `<div class="muted jact">${j.action === 'approve' ? thumbIc(true) + ' ' : j.action === 'reject' ? thumbIc(false) + ' ' : ''}${esc({approve: tr('Approved by {0}', j.action_by_name), reject: tr('Rejected by {0}', j.action_by_name), stop: tr('Stopped by {0}', j.action_by_name)}[j.action] || '')}</div>` : ''}
    ${acts ? `<div class="jobb">${acts}</div>` : ''}</div>`;
}
function viewAgents() {
  if (S.jobs.items === null) { S.jobs.items = []; loadJobs(); aiuLoad().then(() => { if (S.route.mod === 'agents') renderView(); }); }  // 2.1.1: the usage card
  if (S.route.agent && chatFull()) return chatViewHtml(S.route.agent);
  const ags = (S.agents || []).filter(a => wsAgentIn(a));  // 2.28.0 (#935)
  const card = a => `<div class="agcard ${a.enabled ? '' : 'off'}">${avBtn(a.id, a.name, 'avatar lg')}<div class="agi"><b>${esc(a.name)}</b><span class="muted">${esc(agentSt(a))}${a.status_text && agentHst(a) !== 'offline' ? ' · ' + esc(a.status_text) : ''}</span>
      <span class="muted agn">${esc([a.running && trn('{0} running', '{0} running', a.running), a.waiting && trn('{0} waiting', '{0} waiting', a.waiting)].filter(Boolean).join(' · '))}</span></div>
      <div class="agb"><button class="btn sm" data-act="chat-open" data-aid="${a.id}" ${a.enabled ? '' : 'disabled'}>${ic('comment', 's')} ${tr('Chat')}${a.chat_unread ? ` <span class="nbadge">${a.chat_unread}</span>` : ''}</button>${a.approvals_open ? `<button class="btn sm apvcard" data-act="chat-open" data-aid="${a.id}">${ic('lock', 's')} ${esc(apvCount(a.approvals_open))}</button>` : ''}
      <button class="btn sm" data-act="sched-open" data-aid="${a.id}" title="${esc(tr('Planned jobs'))}">${ic('clock', 's')} ${tr('Plans')}</button></div></div>`;
  const items = S.jobs.items || [];
  if (ags.length) {  // 2.32.0 (#1063): the overview is built from blocks (Customize)
    const P = {agents: `<div class="agcards">${ags.map(card).join('')}</div>`, usage: aiuCardHtml(),
      jobs: `<div class="agjh"><h2>${tr('Jobs')}</h2><span class="spacer"></span><div class="seg" role="group"><button class="${S.jobs.f === 'open' ? 'on' : ''}" data-act="jobs-f" data-f="open">${tr('Open|jobs')}</button><button class="${S.jobs.f === 'all' ? 'on' : ''}" data-act="jobs-f" data-f="all">${tr('All')}</button></div></div>
        ${S.jobs.err ? `<div class="muted mhint">${esc(S.jobs.err)}</div>` : ''}<div class="jobs">${items.length ? items.map(jobHtml).join('') : `<div class="muted mhint">${S.jobs.f === 'open' ? tr('No running or waiting jobs.') : tr('No jobs yet.')}</div>`}</div>`,
      hint: `<div class="shint">${tr('Agents report their jobs here. Approve, Reject and Stop go to the agent at once and show up in the task’s history. On a comment of an agent, 👍 / 👎 by the list owner, a list admin or the assignee counts as approval or rejection.')}</div>`};
    return `<div class="agview">${S.ly.view === 'agents' ? '' : `<div class="lybar"><span class="spacer"></span>${lyCustomBtn('agents')}</div>`}${lyHtml('agents', P)}</div>`;
  }
  return `<div class="agview">
    ${ags.length ? `<div class="agcards">${ags.map(card).join('')}</div>` : `<div class="empty hempty">${heron('agent')}<b>${tr('No agent is available to you yet.')}</b><span>${tr('The owner of a list can let its members use the list’s agent (Share › Agents). You can also connect an agent of your own.')}</span><button type="button" class="btn" data-act="ag-setup">${ic('bot', 's')} ${tr('Connect your own agent…')}</button></div>`}
    ${ags.length ? aiuCardHtml() : ''}
    <div class="agjh"><h2>${tr('Jobs')}</h2><span class="spacer"></span><div class="seg" role="group"><button class="${S.jobs.f === 'open' ? 'on' : ''}" data-act="jobs-f" data-f="open">${tr('Open|jobs')}</button><button class="${S.jobs.f === 'all' ? 'on' : ''}" data-act="jobs-f" data-f="all">${tr('All')}</button></div></div>
    ${S.jobs.err ? `<div class="muted mhint">${esc(S.jobs.err)}</div>` : ''}
    <div class="jobs">${items.length ? items.map(jobHtml).join('') : `<div class="muted mhint">${S.jobs.f === 'open' ? tr('No running or waiting jobs.') : tr('No jobs yet.')}</div>`}</div>
    <div class="shint">${tr('Agents report their jobs here. Approve, Reject and Stop go to the agent at once and show up in the task’s history. On a comment of an agent, 👍 / 👎 by the list owner, a list admin or the assignee counts as approval or rejection.')}</div></div>`;
}
async function jobDo(jid, a) {
  if (a !== 'approve' && !await askConfirm(a === 'stop' ? tr('Stop this job?') : tr('Reject this job?'), tr('The agent is told at once.'), {ok: a === 'stop' ? tr('Stop') : tr('Reject'), danger: true})) return;
  try { await api('POST', `/api/agents/jobs/${jid}/action`, {action: a}); toast({approve: tr('Approved'), reject: tr('Rejected'), stop: tr('Stopped')}[a]); } catch { return; }
  await load(); loadJobs(); render();
}

// ---- 2.3.0 (#260 #261 #262 #263): agent proposals. A person asks an agent (project from a briefing, break down a task,
// sort the inbox, tasks from notes); the agent answers with a structured proposal; here every entry can be ticked off and
// edited, "Apply selected" creates / changes it as the person (one undo step), "Discard" tells the agent. The agent gets
// exactly the input shown in the request dialog, nothing else (the server stores it with the job, 30 days at most).
const propOn = () => collab() && feat('agents') && (S.proposers || []).length > 0;
const propWith = (one, many) => (S.proposers || []).length === 1 ? tr(one, S.proposers[0].name) : tr(many);
const PROP_ST = {requested: N_('Waiting for the proposal'), ready: N_('Proposal ready'), applied: N_('Applied'), discarded: N_('Discarded')};
const ppSafe = k => String(k).replace('.', '-');
function propAgentRow() {  // the agent choice: a select when there are several
  const ags = S.proposers || [];
  if (ags.length === 1) return `<input type="hidden" id="pp-agent" value="${ags[0].id}">`;
  return `<div class="row"><label for="pp-agent">${tr('Agent')}</label><select id="pp-agent">${ags.map(a => `<option value="${a.id}">${esc(a.name)}${a.limit_reached ? ' · ' + esc(tr('usage limit reached')) : ''}</option>`).join('')}</select></div>`;
}
function propRequest(kind, ctx = {}) {
  if (!propOn()) return;
  const who = () => { const id = +($('#pp-agent')?.value || 0); return esc((S.proposers.find(a => a.id === id) || S.proposers[0]).name); };
  let title = '', body = '';
  const inbox = S.lists.find(l => l.is_inbox && isOwner(l));
  const inboxOpen = () => inbox ? [...S.tasks.values()].filter(t => t.list_id === inbox.id && !t.parent_id && t.status === 0 && !t.deleted_at).length : 0;
  if (kind === 'project') {
    title = tr('New project from briefing');
    const folders = [...new Set(S.lists.map(l => l.folder).filter(Boolean))];
    body = `<div class="row ppcol"><label for="pp-text">${tr('Briefing')}</label><textarea id="pp-text" rows="8" maxlength="50000" placeholder="${esc(tr('Paste the briefing, or load a text file or PDF'))}"></textarea></div>
      <div class="row"><label class="btn sm ppfile">${ic('file', 's')} ${tr('Load a file (.txt, .md, .pdf)')}<input type="file" id="pp-file" accept=".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf" hidden></label><span class="muted" id="pp-fname"></span></div>
      <div class="row"><label for="pp-folder">${tr('Folder')}</label><input id="pp-folder" maxlength="60" list="pp-folders" placeholder="${esc(tr('optional'))}"><datalist id="pp-folders">${folders.map(f => `<option value="${esc(fDisp(f))}">`).join('')}</datalist></div>`;
  } else if (kind === 'subtasks') {
    const t = taskById(ctx.tid); if (!t) return;
    title = propWith(N_('Break down with {0}'), N_('Break down with an agent'));
    body = `<div class="pptask">${ic('arrow', 's')}<b>${esc(t.title)}</b></div>
      <div class="row ppcol"><label for="pp-hint">${tr('Hint (optional)')}</label><textarea id="pp-hint" rows="3" maxlength="2000" placeholder="${esc(tr('e.g. for a two-day shoot, at most 8 steps'))}"></textarea></div>`;
  } else if (kind === 'triage') {
    const n = ctx.ids ? ctx.ids.length : Math.min(100, inboxOpen());
    if (!n) { toast(tr('The inbox is empty')); return; }
    ctx.n = n;
    title = propWith(N_('Sort the inbox with {0}'), N_('Sort the inbox with an agent'));
    const ls = S.lists.filter(l => !l.is_inbox && !l.archived && canEditList(l.id));
    body = `<div class="pptask">${ic('inbox', 's')}<b>${esc(trn('{0} inbox item', '{0} inbox items', n))}</b></div>
      <div class="row ppcol"><label>${tr('Lists it may suggest')}</label><div class="pplists" id="pp-lists">
        <label class="ppall"><input type="checkbox" id="pp-lall" checked> ${tr('All my lists')}</label>
        ${ls.map(l => `<label><input type="checkbox" data-lid="${l.id}" checked> ${esc(lname(l))}</label>`).join('')}</div></div>`;
  } else if (kind === 'extract') {
    const l = listById(ctx.lid); if (!l) return;
    title = tr('Tasks from notes');
    body = `<div class="pptask">${ic('list', 's')}<b>${esc(lname(l))}</b></div>
      <div class="row ppcol"><label for="pp-text">${tr('Notes')}</label><textarea id="pp-text" rows="8" maxlength="50000" placeholder="${esc(tr('Paste the meeting notes'))}"></textarea></div>`;
  }
  const md = modal(`<h3>${ic('bot', 's')} ${esc(title)}</h3>${body}${propAgentRow()}<div class="shint" id="pp-priv"></div>
    <div class="calerr" role="alert" id="pp-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${ic('bot', 's')} ${tr('Ask for a proposal')}</button></div>`);
  md.classList.add('ppreq');
  const priv = () => {  // what exactly leaves: the consent line under the form
    const l = ctx.lid && listById(ctx.lid);
    $('#pp-priv', md).innerHTML = kind === 'project' ? tr('{0} gets exactly this text (and the folder name) and proposes a project: sections, tasks, dates and dependencies. Nothing is created until you apply it.', `<b>${who()}</b>`)
      : kind === 'subtasks' ? tr('{0} gets the title and notes of this task, the titles of its subtasks and your hint, and proposes subtasks. Nothing is created until you apply them.', `<b>${who()}</b>`)
        : kind === 'triage' ? trn('{1} gets the title and notes of this {0} inbox item and the names and sections of the lists ticked above, nothing else of your inbox. Nothing moves until you apply it.', '{1} gets the titles and notes of these {0} inbox items and the names and sections of the lists ticked above, nothing else of your inbox. Nothing moves until you apply it.', ctx.n, `<b>${who()}</b>`)
          : tr('{0} gets these notes and the names of the people in {1} (to suggest who does what) and proposes tasks for this list. Nothing is created until you apply them.', `<b>${who()}</b>`, `<b>${esc(lname(l))}</b>`);
  };
  priv();
  const err = m => { const e = $('#pp-err', md); e.textContent = m || ''; e.hidden = !m; };
  md.addEventListener('change', async e => {
    if (e.target.id === 'pp-agent') priv();
    if (e.target.id === 'pp-lall') $$('#pp-lists [data-lid]', md).forEach(x => { x.checked = e.target.checked; });
    else if (e.target.dataset?.lid) $('#pp-lall', md).checked = $$('#pp-lists [data-lid]', md).every(x => x.checked);
    if (e.target.id === 'pp-file') {
      const f = e.target.files?.[0]; if (!f) return;
      // 2.34.0 (#368): a PDF's text layer is read on the server (POST /api/pdf-text, nothing stored), cut to the field's 50000
      const pdf = /\.pdf$/i.test(f.name) || f.type === 'application/pdf';
      if (!pdf && !/\.(txt|md|markdown)$/i.test(f.name) && !/^text\/(plain|markdown)$/.test(f.type)) { err(tr('Only text files (.txt, .md) or PDF')); return; }
      let txt = '', cut = false;
      if (pdf) {
        if (f.size > 20 * 1024 * 1024) { err(tr('{0}: larger than {1} MB', f.name, 20)); return; }
        const fd = new FormData(); fd.append('file', f, f.name);
        $('#pp-fname', md).textContent = tr('Reading the PDF…'); err('');
        let j; try { j = await rawFetch('POST', '/api/pdf-text', fd); } catch (x) { $('#pp-fname', md).textContent = ''; err(x instanceof Offline ? tr('Only available online.') : x.message); return; }
        if (!md.isConnected) return;
        if (j.no_text_layer) { $('#pp-fname', md).textContent = ''; err(j.message || tr('Scanned PDF without a text layer: it cannot be read without text recognition (OCR).')); return; }
        txt = j.text || ''; cut = !!j.truncated;
      } else txt = await f.text().catch(() => '');
      if (txt.length > 50000) { if (!pdf) { err(tr('The file is too long (at most {0} characters)', (50000).toLocaleString(LOCALE()))); return; } txt = txt.slice(0, 50000); cut = true; }
      err(''); $('#pp-text', md).value = txt; $('#pp-fname', md).textContent = f.name + (cut ? ' · ' + tr('shortened to {0} characters', (50000).toLocaleString(LOCALE())) : ''); ctx.file = f.name;
    }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const q = {agent_id: +$('#pp-agent', md).value, kind};
    if (kind === 'project' || kind === 'extract') {
      q.text = $('#pp-text', md).value.trim();
      if (!q.text) { need($('#pp-text', md)); return; }
    }
    if (kind === 'project') { q.folder = $('#pp-folder', md).value.trim() || null; if (ctx.file) q.file_name = ctx.file; }
    if (kind === 'subtasks') { q.task_id = ctx.tid; q.hint = $('#pp-hint', md).value.trim() || null; }
    if (kind === 'triage') {
      q.task_ids = ctx.ids || 'all';
      q.lists = $('#pp-lall', md).checked ? 'all' : $$('#pp-lists [data-lid]', md).filter(x => x.checked).map(x => +x.dataset.lid);
    }
    if (kind === 'extract') q.list_id = ctx.lid;
    b.disabled = true; err('');
    try { await calReq('POST', '/api/proposals', q); } catch (x) { err(x.message); b.disabled = false; return; }
    md.remove();
    toast(tr('Sent to {0}: you get a notification when the proposal is ready', (S.proposers.find(a => a.id === q.agent_id) || {}).name || ''));
    if (kind === 'triage') { S.multi.clear(); S.multiMode = false; render(); }
    if (S.route.mod === 'agents') loadJobs();
  });
  setTimeout(() => $(kind === 'subtasks' ? '#pp-hint' : kind === 'triage' ? '[data-m="ok"]' : '#pp-text', md)?.focus(), 50);
}
// ---- the review dialog
S.prop = null;
function propKeys(v) {
  const p = v.proposal; if (!p) return [];
  if (v.kind === 'project') return p.tasks.flatMap((t, i) => [String(i), ...t.subtasks.map((s, k) => `${i}.${k}`)]);
  if (v.kind === 'dayplan') return p.items.map((x, i) => String(i));  // 2.10.0 (#440); 2.11.0: "does not fit" entries change nothing
  return (v.kind === 'extract' ? p.tasks : p.items).map((x, i) => String(i));
}
async function propOpen(jid) {
  let v;
  try { v = await rawFetch('GET', `/api/proposals/${jid}`); } catch (e) {  // 2.5.2 (K19): a readable reason instead of "unknown"
    toast(e instanceof Offline ? tr('Offline: only works again with a connection') : e.status === 404 ? tr('This proposal is not available: only the person who asked for it can open it, or it was removed.') : e.message); return;
  }
  $('.ppm')?.remove();
  const md = modal('');
  md.classList.add('ppm');
  S.prop = {jid, v, md, sel: new Set(propKeys(v)), ed: {}};
  propDraw();
  md.addEventListener('input', e => propEdit(e.target));
  md.addEventListener('change', e => {
    if (e.target.classList.contains('ppc')) {
      const k = e.target.closest('.ppi')?.dataset.k; if (k === undefined) return;
      const on = e.target.checked;
      on ? S.prop.sel.add(k) : S.prop.sel.delete(k);
      if (!k.includes('.')) $$(`.ppi[data-k^="${k}."]`, md).forEach(x => { const c = $('.ppc', x); c.checked = on; on ? S.prop.sel.add(x.dataset.k) : S.prop.sel.delete(x.dataset.k); x.classList.toggle('off', !on); });  // subtasks follow their task
      else if (on) { const p = k.split('.')[0]; S.prop.sel.add(p); const pr = $(`.ppi[data-k="${p}"]`, md); if (pr) { $('.ppc', pr).checked = true; pr.classList.remove('off'); } }
      e.target.closest('.ppi').classList.toggle('off', !on);
      propCount();
      return;
    }
    propEdit(e.target);
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-pp]'); if (!b) return;
    const a = b.dataset.pp;
    if (a === 'close') { md.remove(); S.prop = null; }
    if (a === 'all' || a === 'none') { S.prop.sel = new Set(a === 'all' ? propKeys(S.prop.v) : []); propDraw(); }
    if (a === 'discard') propDiscard();
    if (a === 'apply') propApply(b);
  });
}
function propEdit(el) {
  const f = el.dataset?.f, row = el.closest?.('.ppi'); if (!f || !row || !S.prop) return;
  const k = row.dataset.k, v = el.value, e = S.prop.ed[k] ||= {};
  if (f === 'title') e.title = v.trim();
  else if (f === 'due') e.due = v || null;
  else if (f === 'section') e.section = v || null;
  else if (f === 'assignee_id') e.assignee_id = v ? +v : null;
  else if (f === 'list_id') {  // triage: another list -> its sections
    e.list_id = v ? +v : null; e.section_id = null;
    const s = $('[data-f="section_id"]', row); if (s) s.outerHTML = propSecSel(e.list_id, null);
  } else if (f === 'section_id') { e.section_id = v ? +v : null; if (!('list_id' in e)) e.list_id = +$('[data-f="list_id"]', row)?.value || null; }
}
const propPrio = p => p ? `<span class="ppchip flag-${p}">${ic('flag', 's')}${esc(tr({1: N_('Low'), 3: N_('Medium'), 5: N_('High')}[p] || ''))}</span>` : '';
function propSecSel(lid, sid) {
  const l = (S.prop.v.input.lists || []).find(x => x.id === lid);
  return `<select data-f="section_id" aria-label="${esc(tr('Section'))}" ${l && l.sections.length ? '' : 'hidden'}><option value="">${tr('No section')}</option>${(l?.sections || []).map(s => `<option value="${s.id}" ${s.id === sid ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>`;
}
function propItemHtml(k, x, o = {}) {  // one entry: checkbox, title, date and the fields of its kind
  // 2.5.2 (K03): one compact line (checkbox · title · date on the right), the fields of its kind and the chips below
  const on = S.prop.sel.has(k), id = ppSafe(k), extra = (o.fields || '') + (o.chips || '');
  return `<div class="ppi ${o.sub ? 'sub' : ''} ${on ? '' : 'off'}" data-k="${k}">
    <label class="ppcl"><input type="checkbox" class="ppc" id="ppc-${id}" ${on ? 'checked' : ''} aria-label="${esc(tr('Select {0}', x.title))}"></label>
    <div class="ppb">${o.orig ? `<div class="ppo muted">${esc(o.orig)}</div>` : ''}
      <div class="pprow"><input class="ppt" data-f="title" value="${esc(x.title)}" maxlength="300" aria-label="${esc(tr('Title'))}">${dateIn('ppd-' + id, x.due || '', {label: tr('Due date'), empty: tr('No date|clear'), attrs: 'data-f="due"'})}</div>
      ${extra.trim() ? `<div class="ppf">${extra}</div>` : ''}
      ${x.notes ? `<div class="ppn muted">${esc(x.notes.replace(/\s+/g, ' ').slice(0, 240))}</div>` : ''}</div></div>`;
}
function propItemsHtml() {
  const {v} = S.prop, p = v.proposal, inp = v.input;
  if (v.kind === 'dayplan') return propDayplanHtml();  // 2.10.0 (#440)
  if (v.kind === 'project') {
    const secOpts = cur => `<option value="">${tr('No section')}</option>${p.sections.map(s => `<option ${s === cur ? 'selected' : ''}>${esc(s)}</option>`).join('')}`;
    return p.tasks.map((t, i) => propItemHtml(String(i), t, {
      fields: p.sections.length ? `<select data-f="section" aria-label="${esc(tr('Section'))}">${secOpts(t.section)}</select>` : '',
      chips: propPrio(t.priority) + (t.depends_on.length ? `<span class="ppchip">${ic('deps', 's')}${esc(tr('blocked by {0}', t.depends_on.map(d => '“' + p.tasks[d].title.slice(0, 24) + '”').join(', ')))}</span>` : '')})
      + t.subtasks.map((s, k) => propItemHtml(`${i}.${k}`, s, {sub: true})).join('')).join('');
  }
  if (v.kind === 'subtasks') return p.items.map((t, i) => propItemHtml(String(i), t, {
    chips: (t.estimate ? `<span class="ppchip">${ic('clock', 's')}${esc(fmtDur(t.estimate * 60))}</span>` : '')
      + p.dependencies.filter(d => d[0] === i).map(d => `<span class="ppchip">${ic('deps', 's')}${esc(tr('blocked by {0}', '“' + p.items[d[1]].title.slice(0, 24) + '”'))}</span>`).join('')})).join('');  // 2.5.2 (K03): no stray commas
  if (v.kind === 'extract') {
    const secs = [...new Set([...(inp.list?.sections || []), ...p.tasks.map(t => t.section).filter(Boolean)])];
    return p.tasks.map((t, i) => propItemHtml(String(i), t, {
      fields: `<select data-f="assignee_id" aria-label="${esc(tr('Assignee'))}"><option value="">${tr('Nobody')}</option>${(inp.members || []).map(m => `<option value="${m.id}" ${m.id === t.assignee_id ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select>
        <select data-f="section" aria-label="${esc(tr('Section'))}"><option value="">${tr('No section')}</option>${secs.map(s => `<option ${s === t.section ? 'selected' : ''}>${esc(s)}${(inp.list?.sections || []).includes(s) ? '' : ' ' + esc(tr('(new)'))}</option>`).join('')}</select>`})).join('');
  }
  // triage: the inbox item as it is now, where it should go
  return p.items.map((t, i) => {
    const it = (inp.items || []).find(x => x.task_id === t.task_id) || {}, cur = taskById(t.task_id);
    return propItemHtml(String(i), {title: t.rewrite_title || cur?.title || it.title || '', due: t.due, notes: ''}, {
      orig: t.rewrite_title ? cur?.title || it.title : '',
      fields: `<select data-f="list_id" aria-label="${esc(tr('List'))}"><option value="">${tr('Stay in the inbox')}</option>${(inp.lists || []).map(l => `<option value="${l.id}" ${l.id === t.list_id ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select>${propSecSel(t.list_id, t.section_id)}`,
      chips: propPrio(t.priority) + (t.tags || []).map(g => `<span class="ppchip">#${esc(g)}</span>`).join('')});
  }).join('');
}
function propCount() {
  const P = S.prop, n = P.sel.size, all = propKeys(P.v).length, b = $('[data-pp="apply"]', P.md);
  $$('.ppcount', P.md).forEach(c => { c.textContent = tr('{0} of {1} selected', n, all); });
  if (b) { b.disabled = !n; b.innerHTML = `${ic('check', 's')} ${esc(trn('Apply {0} entry', 'Apply {0} entries', n))}`; }
}
function propDraw() {
  const P = S.prop, v = P.v, st = v.state, j = v.job, p = v.proposal, agent = `<b>${esc(v.agent.name)}</b>`;
  let main = '', foot = `<span class="spacer"></span><button class="btn" data-pp="close">${tr('Close')}</button>`;
  if (st === 'requested') {
    main = `<div class="ppwait">${ic('bot')}<p>${tr('{0} is working on it. You get a notification when the proposal is ready.', agent)}</p></div>`;
    foot = `<button class="btn danger" data-pp="discard">${tr('Cancel the request')}</button>` + foot;
  } else if (st === 'ready') {
    main = `${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}
      ${v.kind === 'project' ? `<div class="row"><label for="pp-name">${tr('List name')}</label><input id="pp-name" maxlength="120" value="${esc(p.name)}"></div>
        <div class="row"><label for="pp-folder">${tr('Folder')}</label><input id="pp-folder" maxlength="60" value="${esc(p.folder || v.input.folder || '')}" placeholder="${esc(tr('optional'))}"></div>
        <label class="ppshare"><input type="checkbox" id="pp-share"> ${tr('Share the new list with {0}', esc(v.agent.name))}</label>` : ''}
      <div class="ppbar"><button class="btn sm" data-pp="all">${tr('Select all')}</button><button class="btn sm" data-pp="none">${tr('Select none')}</button></div>
      <div class="ppl">${propItemsHtml()}</div>
      <div class="shint keep">${v.kind === 'dayplan' ? tr('Applying sets the planned start and duration of the selected tasks as you; due dates stay as they are. One step, undo takes it back.') : v.kind === 'triage' ? tr('Applying moves and changes the selected inbox items as you; one step, undo takes it back.') : tr('Applying creates the selected entries as you (you own them, the history names {0}); one step, undo takes it back.', esc(v.agent.name))}</div>`;
    // 2.5.2 (K03): the footer stays visible below the entries (sticky), with the count next to Apply
    foot = `<button class="btn danger" data-pp="discard">${tr('Discard')}</button><span class="spacer"></span><span class="muted ppcount ppfc"></span><button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply"></button>`;
  } else {
    main = `<div class="ppwait">${ic(st === 'applied' ? 'check' : 'x')}<p>${st === 'applied' ? (v.applied?.undone ? tr('Applied, then undone.') : tr('Applied.')) : tr('Discarded. {0} was told.', agent)}</p></div>`;
  }
  P.md.querySelector('.card').innerHTML = `<h3>${ic('bot', 's')} ${esc(j.title)}</h3>
    <div class="pphead muted"><span class="jst">${esc(tr(PROP_ST[st] || st))}</span>${agent} · ${esc(relTime(j.updated_at))}</div>
    <div class="calerr" role="alert" id="pp-err" hidden></div>${main}<div class="foot ${st === 'ready' ? 'ppfoot' : ''}">${foot}</div>`;
  if (st === 'ready') propCount();
}
async function propApply(b) {
  const P = S.prop; if (!P || !P.sel.size) return;
  const v = P.v, q = {select: [...P.sel], edits: Object.fromEntries(Object.entries(P.ed).filter(([k]) => P.sel.has(k)))};
  if (v.kind === 'project') { q.name = $('#pp-name', P.md).value.trim() || v.proposal.name; q.folder = $('#pp-folder', P.md).value.trim(); q.share_agent = $('#pp-share', P.md).checked; }
  b.disabled = true;
  let r;
  try { r = await calReq('POST', `/api/proposals/${P.jid}/apply`, q); } catch (x) { const e = $('#pp-err', P.md); e.textContent = x.message; e.hidden = false; b.disabled = false; return; }
  P.md.remove(); S.prop = null;
  await load().catch(() => {}); render();
  const name = v.agent.name, jid = P.jid;
  const e = histAdd({label: tr('Applied the proposal of {0}', name), snaps: [], after: [], ids: [], lids: r.list_id ? [r.list_id] : [],
    undo: async () => { const x = await api('POST', `/api/proposals/${jid}/undo`); return {skipped: x.skipped || [], none: !!x.none}; },
    redo: async () => { const x = await api('POST', `/api/proposals/${jid}/redo`); return {skipped: x.skipped || [], none: !!x.none}; }});
  histToast(v.kind === 'dayplan' ? trn('{0} task planned', '{0} tasks planned', r.changed) : r.changed ? trn('{0} inbox item sorted', '{0} inbox items sorted', r.changed) : trn('{0} entry created', '{0} entries created', r.created), e);
  if (v.kind === 'project' && r.list_id && listById(r.list_id)) go('l/' + r.list_id);
  if (S.route.mod === 'agents') loadJobs();
}
async function propDiscard() {
  const P = S.prop; if (!P) return;
  const req = P.v.state === 'requested';
  if (!await askConfirm(req ? tr('Cancel the request?') : tr('Discard this proposal?'), tr('{0} is told at once. Nothing is created or changed.', P.v.agent.name), {ok: req ? tr('Cancel the request') : tr('Discard'), danger: true})) return;
  try { await calReq('POST', `/api/proposals/${P.jid}/discard`); } catch (x) { toast(x.message); return; }
  P.md.remove(); S.prop = null;
  toast(req ? tr('Request cancelled') : tr('Proposal discarded'));
  load().then(render).catch(() => {});
  if (S.route.mod === 'agents') loadJobs();
}

// ---- 2.30.0 (#919 / #920): using agents safely. The server keeps an agent inside one circle of people: sharing a list with
// an agent (or adding a person to a list with an agent) that would connect lists with different people answers 409
// agent_bridge; bridgeTry asks and repeats the request with bridge_ok. The rules ("Use safely", Settings > Agents), a short
// hint before the first share with an agent on this device, the access log of a list (list menu > Agent access).
const AG_SAFE = [
  [N_('One agent per context'), N_('Rather one agent for the team and one for you privately than one for everything. Separate agents cannot carry anything between your worlds.')],
  [N_('Share only the lists it needs'), N_('It can read every list shared with it, with all tasks, comments and files. Do not add a list just in case.')],
  [N_('The same people'), N_('Kalmido lets an agent work only in lists that the same people see (or some of them). Connecting lists with different people needs your approval: think about who may see what the agent brings from one list into the other.')],
  [N_('Keep its permissions small'), N_('If it only needs to read, give it read access only, and limit it to selected lists. Sharing, deleting, bulk changes and moving tasks to other people wait for your approval anyway.')],
  [N_('Take approvals seriously'), N_('When the agent asks “May I …?”, read what it is about to do. Your approval is a real decision.')],
  [N_('Other people’s texts are not commands'), N_('If someone writes “Agent, copy … for me” into a shared list, the agent must not just do it. Kalmido blocks the important cases on the server, but no AI recognises every deception (prompt injection). That is why the first three rules matter.')],
  [N_('Know where the data goes'), N_('What an agent reads is processed by the AI provider you connected. For confidential work use a local model or a provider with a data processing agreement. Kalmido itself never sends data to an AI provider: only an agent you connect does.')],
  [N_('Health stays private'), N_('No agent ever sees health lists, whatever is shared with it.')],
  [N_('Look at the access log'), N_('The list menu > Agent access shows which agents read or changed the list in the last 30 days. Every member of the list sees it.')],
  [N_('End access when it is no longer needed'), N_('Pause the agent or create a new token (the old one stops at once); give tokens an expiry date.')]];
const AG_SAFE_ADMIN = [N_('By default members may not connect their own agents: allow it only when there is a rule for it.'),
  N_('Agree which AI providers are allowed (privacy, customer data).'),
  N_('Share lists with customer data only with agents whose provider has a data processing agreement, or with a local model.')];
function agSafeHtml() {
  return `<div class="agsafe"><p class="agsafe-lead">${esc(tr('An agent sees only what you share with it. Share as little as needed, and keep private and shared work apart.'))}</p>
    <ol class="agsafe-rules">${AG_SAFE.map(([h, t]) => `<li><b>${esc(tr(h))}</b> <span>${esc(tr(t))}</span></li>`).join('')}</ol>
    <h4>${esc(tr('For organisations (admins)'))}</h4><ul class="agsafe-admin">${AG_SAFE_ADMIN.map(t => `<li>${esc(tr(t))}</li>`).join('')}</ul>
    <div class="shint">${esc(tr('The details for the people who run agents:'))} <a href="${API_DOCS.replace('API.md', 'AGENT-SECURITY.md')}" target="_blank" rel="noopener noreferrer">${esc(tr('Agent security (docs/AGENT-SECURITY.md)'))}</a></div></div>`;
}
// before the first share with an agent on this device: the three rules that matter most, with the way to all ten
async function agSafeFirst() {
  if (LS.get('agSafeSeen', false)) return true;
  const ok = await askDialog({title: tr('Before you share a list with an agent'), ok: tr('Share'),
    html: `<p>${esc(tr('The agent reads every task, comment and file of this list, and its AI provider processes them.'))}</p><ul class="agsafe-admin">${AG_SAFE.slice(0, 3).map(([h]) => `<li>${esc(tr(h))}</li>`).join('')}</ul><p class="muted">${esc(tr('All rules: Settings > Agents > Use safely.'))}</p>`});
  if (ok) LS.set('agSafeSeen', true);
  return ok;
}
// fn(ok) sends the request (ok: with bridge_ok). A refused bridge asks once and repeats it; "Cancel" rejects with e.declined
async function bridgeTry(fn) {
  try { return await fn(false); }
  catch (e) {
    if (e?.data?.code !== 'agent_bridge') throw e;
    if (!await askConfirm(tr('Connect lists with different people?'), e.message, {ok: tr('Connect anyway'), danger: true})) { e.declined = true; toast(tr('Not shared')); throw e; }
    return await fn(true);
  }
}
// list menu > Agent access: per agent and day how often it read / changed the list (last 30 days)
async function agAccessModal(lid) {
  let j; try { j = await api('GET', `/api/lists/${lid}/agent-access`); } catch { return; }
  const per = new Map();
  for (const r of j.data) { const a = per.get(r.agent_id) || {name: r.name, read: 0, write: 0, days: new Set(), last: r.day}; a.read += r.read; a.write += r.write; a.days.add(r.day); if (r.day > a.last) a.last = r.day; per.set(r.agent_id, a); }
  const rows = [...per.entries()].map(([id, a]) => `<div class="mrow agacc" data-agacc="${id}">${avBtn(id, a.name)}<span class="n"><b>${esc(a.name)}</b><small class="muted">${esc(tr('read {0} times, changed {1} times, on {2} days', a.read, a.write, a.days.size))} · ${esc(tr('last on {0}', fmtDayAbs(a.last)))}</small></span></div>`).join('');
  const md = modal(`<h3>${esc(tr('Agent access: {0}', lname(listById(lid) || {name: ''})))}</h3>
    <div class="shint">${esc(tr('Which agents read or changed this list in the last {0} days (one count per request). Every member of the list sees this.', j.days))}</div>
    <div class="members">${rows || `<div class="muted mhint">${esc(tr('No agent accessed this list in that time.'))}</div>`}</div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('agaccmd');
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) md.remove(); });
}
// the lists an agent / a token is limited to (none ticked = all of its lists)
function listCapHtml(sel, lists, id) {
  const on = new Set(sel || []);
  return `<details class="sdet lcap" ${on.size ? 'open' : ''}><summary>${esc(on.size ? trn('Limited to {0} list', 'Limited to {0} lists', on.size) : tr('All its lists'))}</summary>
    <p class="lcaphint muted">${esc(tr('Tick lists to limit access to them; nothing ticked = every list it is in. Other lists then do not exist for it, and it gets no events about them.'))}</p>
    <div class="lcapgrid" id="${id}">${(lists || []).map(l => `<label class="chkl"><input type="checkbox" data-lcap="${l.id}" ${on.has(l.id) ? 'checked' : ''}><span>${esc(l.name)}</span></label>`).join('') || `<span class="muted">${esc(tr('No lists yet.'))}</span>`}</div></details>`;
}
const listCapVal = (md, id) => $$(`#${id} [data-lcap]:checked`, md).map(x => +x.dataset.lcap);
// the agent's dialog: the lists it connects although their people differ (approved or from before 2.30)
function bridgesHtml(a) {
  const bs = a?.bridges || []; if (!bs.length) return '';
  const nm = l => l.name == null ? tr('a list you cannot see') : `“${l.name}”`;
  return `<div class="shint keep warn agbridges">${ic('alert', 's')} <b>${esc(tr('Connects lists with different people'))}</b><ul>${bs.map(b => `<li>${esc(nm(b.lists[0]))} + ${esc(nm(b.lists[1]))} · ${esc(b.approved ? tr('approved by {0}', b.by_name || '?') : tr('not approved (from before, or via a group)'))}</li>`).join('')}</ul>${esc(tr('Content of one list can reach the other people through the agent. Use one agent per context, limit it to selected lists, or take it out of one of them.'))}</div>`;
}

// ---- 2.34.0 (#272): planned agent jobs. A person plans jobs for an agent they may chat with ("every Monday at 9: the week
// plan"); when one is due the agent gets the event scheduled_job and answers in the chat. Kalmido runs no model itself. The
// agent card opens the dialog: my plans (an agent's managers: all of the agent's plans), on / off, Run now, Edit, Delete;
// "New plan" starts from a template (the text stays free to change). The next run in the language's date format.
const SCHED_FREQ = {daily: N_('Every day'), weekdays: N_('Every working day (Mon–Fri)'), weekly: N_('Every week on'), monthly: N_('Every month on day')};
const SCHED_LAST = {sent: N_('sent'), late: N_('sent late'), manual: N_('run by hand'), skipped: N_('skipped: the agent was switched off'),
  no_access: N_('switched off: you no longer reach the agent'), no_list: N_('switched off: the list is no longer shared with the agent')};
// the templates point at the data tools of the agent API / MCP; the text is the person's to change
const SCHED_TPL = [
  {k: 'brief', t: N_('Morning briefing'), freq: 'weekdays', time: '08:00',
    p: N_('Read my briefing for today (tool read_briefing, user_id = my id) and write me a short overview in this chat: what is due today or overdue, what is blocked and what changed since yesterday. At most ten lines, the most important first.')},
  {k: 'status', t: N_('Weekly project status'), freq: 'weekly', days: [1], time: '09:00', list: true,
    p: N_('Read the status of the list of this plan for the last 7 days (tool read_project_status) and write me a short weekly status in this chat: done, in progress, blocked, next due dates and milestones. Plain text that I can forward; no internal comments.')},
  {k: 'stale', t: N_('Follow up on stale tasks'), freq: 'weekly', days: [1], time: '10:00',
    p: N_('Look for tasks that have been lying around (tool list_stale_tasks; only the list of this plan if it has one). For each one suggest in this chat a short, friendly reminder or the next step. Send nothing to anyone else and change nothing without asking me.')},
  {k: 'time', t: N_('Check time tracking'), freq: 'weekly', days: [5], time: '16:00',
    p: N_('Check my time tracking of this week (tools get_time_gaps with user_id = my id, and list_time_entries): on which working days did I work on tasks without tracking time? List them in this chat with a suggestion. Change nothing.')},
  {k: 'own', t: N_('Own plan'), freq: 'weekly', days: [1], time: '09:00', p: ''}];
const schedWd = i => WD[i % 7];  // ISO weekday 1..7 -> short name of the language
function schedRhythm(s) {
  const t = tr(SCHED_FREQ[s.freq] || s.freq), at = fmtTimeLoc(s.time);
  if (s.freq === 'weekly') return `${t} ${(s.days || []).map(schedWd).join(', ')}, ${at}`;
  if (s.freq === 'monthly') return `${t} ${(s.days || [1])[0]}, ${at}`;
  return `${t}, ${at}`;
}
// 2.35.0 (#1107): plans show date + time in the date format of the language (de 10.10.2026 07:45, en-US 10/10/2026, 7:45 AM)
function schedWhen(iso) {
  const d = new Date(iso); if (isNaN(d)) return '';
  try { return d.toLocaleDateString(dpLocale(), {day: '2-digit', month: '2-digit', year: 'numeric'}) + ' ' + fmtTimeLoc(`${pad(d.getHours())}:${pad(d.getMinutes())}`); } catch { return fmtWhen(iso); }
}
const schedNext = s => s.next_at ? tr('next: {0}', schedWhen(s.next_at)) : tr('paused');
// lists the agent may work in for me: shared with it, not the inbox (the server checks it again)
const schedLists = aid => (S.lists || []).filter(l => !l.archived && !l.is_inbox && listAgents(l).some(a => a.id === +aid));
function schedRowHtml(s) {
  const last = s.last_state ? tr(SCHED_LAST[s.last_state] || s.last_state) + (s.last_at ? ' · ' + schedWhen(s.last_at) : '') : '';
  return `<div class="schedrow ${s.enabled ? '' : 'off'}" data-sid="${s.id}"><div class="schedi"><b>${esc(s.title)}</b>
      <small class="muted">${esc(schedRhythm(s))}${s.list_name ? ' · ' + esc(s.list_name) : ''}${s.mine ? '' : ' · ' + esc(tr('by {0}', s.by_name))}</small>
      <small class="${s.enabled ? '' : 'muted'}">${esc(schedNext(s))}${last ? ` <span class="muted">· ${esc(tr('last: {0}', last))}</span>` : ''}</small></div>
    <div class="schedb"><label class="chkl schedon" title="${esc(tr('Active'))}"><input type="checkbox" data-sm="toggle" ${s.enabled ? 'checked' : ''} aria-label="${esc(tr('Active: {0}', s.title))}"></label>
      <button type="button" class="btn sm" data-sm="run" ${s.enabled ? '' : 'disabled'}>${ic('play', 's')} ${tr('Run now')}</button>
      <button type="button" class="btn sm" data-sm="edit" aria-label="${esc(tr('Edit: {0}', s.title))}">${ic('edit', 's')}<span class="schedtx"> ${tr('Edit')}</span></button>
      <button type="button" class="btn sm danger" data-sm="del" aria-label="${esc(tr('Delete: {0}', s.title))}">${ic('trash', 's')}</button></div></div>`;
}
async function schedOpen(aid) {
  const a = agentById(aid); if (!a) return;
  let j; try { j = await api('GET', `/api/agents/${a.id}/schedules`); } catch { return; }
  const md = modal('<div class="schedbody"></div>');
  md.classList.add('schedmd');
  const draw = () => {
    const mine = j.data.filter(s => s.mine).length;
    $('.schedbody', md).innerHTML = `<h3>${ic('clock', 's')} ${esc(tr('Planned jobs: {0}', a.name))}</h3>
      <div class="shint">${esc(tr('{0} gets each plan at its time as a job and answers in your chat. It sees only the lists shared with it.', a.name))}</div>
      <div class="schedlist">${j.data.length ? j.data.map(schedRowHtml).join('') : `<div class="muted mhint">${esc(tr('No plans yet.'))}</div>`}</div>
      <div class="foot"><span class="muted">${esc(tr('{0} of {1}', mine, j.max))}</span><span class="spacer"></span><button class="btn" data-sm="close">${tr('Close')}</button>
        ${j.may_create ? `<button class="btn pri" data-sm="new" ${mine >= j.max ? 'disabled' : ''}>${ic('plus', 's')} ${tr('New plan')}</button>` : ''}</div>`;
  };
  const reload = async () => { try { j = await api('GET', `/api/agents/${a.id}/schedules`); } catch { /* api() showed it */ } draw(); };
  draw();
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-sm]'); if (!b || b.dataset.sm === 'toggle') return;
    const sid = +(b.closest('[data-sid]')?.dataset.sid || 0), s = j.data.find(x => x.id === sid);
    if (b.dataset.sm === 'close') md.remove();
    else if (b.dataset.sm === 'new') schedForm(md, a, null, reload);
    else if (b.dataset.sm === 'edit' && s) schedForm(md, a, s, reload);
    else if (b.dataset.sm === 'del' && s) {
      if (!await askConfirm(tr('Delete this plan?'), s.title, {ok: tr('Delete'), danger: true})) return;
      try { await api('DELETE', `/api/agent-schedules/${sid}`); toast(tr('Deleted')); } catch { return; }
      await reload();
    } else if (b.dataset.sm === 'run' && s) {
      b.disabled = true;
      try { await api('POST', `/api/agent-schedules/${sid}/run`); toast(tr('Sent to {0}', a.name)); } catch { b.disabled = false; return; }
      await reload();
    }
  });
  md.addEventListener('change', async e => {
    const x = e.target.closest('[data-sm="toggle"]'); if (!x) return;
    const sid = +x.closest('[data-sid]').dataset.sid;
    try { await api('PATCH', `/api/agent-schedules/${sid}`, {enabled: x.checked}); } catch { x.checked = !x.checked; return; }
    await reload();
  });
}
// the form (new or change) inside the same dialog; "Cancel" goes back to the list
function schedForm(md, a, s, done) {
  const box = $('.schedbody', md), ls = schedLists(a.id), isNew = !s;
  const tz = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { return ''; } })();
  const v = s ? {...s} : {title: '', prompt: '', freq: 'weekly', days: [1], time: '09:00', list_id: null, enabled: true};
  const freqOpts = Object.keys(SCHED_FREQ).map(f => `<option value="${f}" ${v.freq === f ? 'selected' : ''}>${esc(tr(SCHED_FREQ[f]))}</option>`).join('');
  box.innerHTML = `<h3>${ic('clock', 's')} ${esc(isNew ? tr('New plan for {0}', a.name) : tr('Edit plan'))}</h3>
    ${isNew ? `<div class="row ppcol"><span class="lbl">${tr('Start from a template')}</span><div class="schedtpl" role="group">${SCHED_TPL.map(t => `<button type="button" class="chip" data-tpl="${t.k}">${esc(tr(t.t))}</button>`).join('')}</div></div>` : ''}
    <div class="row ppcol"><label for="sc-title">${tr('Title')}</label><input id="sc-title" maxlength="120" value="${esc(v.title)}"></div>
    <div class="row ppcol"><label for="sc-prompt">${tr('What should the agent do?')}</label><textarea id="sc-prompt" rows="6" maxlength="4000">${esc(v.prompt)}</textarea></div>
    <div class="row schedrh"><label for="sc-freq">${tr('Repeat')}</label><select id="sc-freq">${freqOpts}</select>
      <span class="schedwd" id="sc-wd" role="group" aria-label="${esc(tr('Weekdays'))}">${[1, 2, 3, 4, 5, 6, 7].map(i => `<label class="chkl"><input type="checkbox" data-wd="${i}" ${(v.days || []).includes(i) ? 'checked' : ''}> ${esc(schedWd(i))}</label>`).join('')}</span>
      <input id="sc-dom" type="number" min="1" max="31" value="${v.freq === 'monthly' ? (v.days || [1])[0] : 1}" aria-label="${esc(tr('Day of the month'))}">
      <label for="sc-time" class="sr">${tr('Time')}</label>${timeIn('sc-time', v.time, {label: tr('Time'), clear: false})}</div>
    <div class="row"><label for="sc-list">${tr('List')}</label><select id="sc-list"><option value="">${tr('No list')}</option>${ls.map(l => `<option value="${l.id}" ${v.list_id === l.id ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}${v.list_id && !ls.some(l => l.id === v.list_id) ? `<option value="${v.list_id}" selected>${esc(v.list_name || '?')}</option>` : ''}</select></div>
    <div class="row"><label class="chkl"><input type="checkbox" id="sc-on" ${v.enabled ? 'checked' : ''}> ${tr('Active')}</label></div>
    <div class="shint">${esc(tr('The agent gets title, text and list at the planned time, at most once per run; after an outage only the one missed run (marked late). Times in your time zone ({0}).', s?.tz || tz || '–'))}</div>
    <div class="calerr" role="alert" id="sc-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-sf="back">${tr('Cancel')}</button><button class="btn pri" data-sf="save">${tr('Save')}</button></div>`;
  const vis = () => { const f = $('#sc-freq', box).value; $('#sc-wd', box).hidden = f !== 'weekly'; $('#sc-dom', box).hidden = f !== 'monthly'; };
  vis();
  $('#sc-freq', box).addEventListener('change', vis);
  $('#sc-title', box).focus();
  box.onclick = async e => {
    const tb = e.target.closest('[data-tpl]');
    if (tb) {
      const t = SCHED_TPL.find(x => x.k === tb.dataset.tpl);
      $('#sc-title', box).value = t.k === 'own' ? '' : tr(t.t); $('#sc-prompt', box).value = t.p ? tr(t.p) : '';
      $('#sc-freq', box).value = t.freq; $('#sc-time', box).value = t.time; dpSync($('#sc-time', box));
      $$('[data-wd]', box).forEach(x => { x.checked = (t.days || []).includes(+x.dataset.wd); });
      if (t.list && !$('#sc-list', box).value && ls.length) $('#sc-list', box).value = String(ls[0].id);
      $$('[data-tpl]', box).forEach(x => x.classList.toggle('on', x === tb)); vis();
      $(t.k === 'own' ? '#sc-title' : '#sc-prompt', box).focus();
      return;
    }
    const b = e.target.closest('[data-sf]'); if (!b) return;
    if (b.dataset.sf === 'back') { box.onclick = null; done(); return; }
    const f = $('#sc-freq', box).value;
    const d = {title: $('#sc-title', box).value.trim(), prompt: $('#sc-prompt', box).value.trim(), freq: f, time: $('#sc-time', box).value || '09:00',
      days: f === 'weekly' ? $$('[data-wd]:checked', box).map(x => +x.dataset.wd) : f === 'monthly' ? [Math.max(1, Math.min(31, +$('#sc-dom', box).value || 1))] : [],
      list_id: +$('#sc-list', box).value || null, enabled: $('#sc-on', box).checked};
    if (isNew && tz) d.tz = tz;
    const er = $('#sc-err', box), fail = m => { er.textContent = m; er.hidden = false; };
    if (!d.title) return fail(tr('Please enter a title.'));
    if (!d.prompt) return fail(tr('Please describe what the agent should do.'));
    if (f === 'weekly' && !d.days.length) return fail(tr('Pick at least one weekday'));
    b.disabled = true;
    try { await rawFetch(isNew ? 'POST' : 'PATCH', isNew ? `/api/agents/${a.id}/schedules` : `/api/agent-schedules/${s.id}`, d); }
    catch (x) { b.disabled = false; return fail(x instanceof Offline ? tr('Only available online.') : x.message); }
    toast(tr('Saved')); box.onclick = null; done();
  };
}
