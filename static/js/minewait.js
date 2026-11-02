// @ts-check
/* 2.392.0 D (#3369): the view "Waiting for me" (#mine_wait): everything that waits for me over every workspace, from GET
   /api/inbox (agents/waiting.py). Each row leads to its target; waiting jobs keep their buttons. The sidebar row counts all of
   it, the card in Today (agents.js, waitCard) links here instead of repeating it. */
const MW_GROUPS = [['job', N_('Jobs')], ['approval', N_('Approvals')], ['gate', N_('Merge and deploy requests')], ['review', N_('Reviews')],
  ['blocked', N_('Blocked')], ['irreversible', N_('One-way steps without a yes')], ['parked', N_('Parked')]];  // 2.392.2 (#3365): parked
S.mw = {items: null, counts: {}, total: 0, at: 0};
async function mwLoad(force = false) {
  if (!force && Date.now() - S.mw.at < 60000) return;
  S.mw.at = Date.now();
  let j; try { j = await api('GET', '/api/inbox'); } catch { return; }  // offline: the last answer stays
  const sig = x => (x || []).map(i => i.kind + i.id).join();
  const same = S.mw.items && sig(S.mw.items) === sig(j.items);
  S.mw = {...S.mw, items: j.items || [], counts: j.counts || {}, total: j.total || 0};
  if (same || !S.booted) return;
  renderSide();
  if (S.route.mod === 'tasks' && (S.route.key === 'mine_wait' || S.route.key === 'today')) renderView();
}
const mwCount = () => S.mw.total;
const mwToDo = () => S.mw.total - (S.mw.counts.blocked || 0) - (S.mw.counts.parked || 0);  // what only I can settle: my blocked tasks are in the briefing already, parked ones wait on purpose
// a list with the lock: the server holds ciphertexts, the app opens the task's title where it has the key
function mwTitle(x) {
  const t = x.task_id && taskById(x.task_id), own = x.title && !le2eIs(x.title) ? x.title : '';
  if (own) return own;
  if (t?.title && !le2u_locked(t)) return t.title;
  return x.task_title && !le2eIs(x.task_title) ? x.task_title : tr('Encrypted task');
}
const mwHref = x => x.kind === 'job' && !x.task_id ? '#agents' : x.task_id ? `#t/${x.task_id}` : '';
function mwRow(x) {
  const tt = x.task_title && !le2eIs(x.task_title) ? x.task_title : '', title = mwTitle(x);
  const sub = [x.agent_name, x.list_name, x.task_id && tt !== title ? `#${x.task_id} ${tt}` : '', x.kind === 'parked' ? x.why : ''].filter(Boolean).join(' · ');
  const body = `<span class="wci"><b>${esc(title)}</b><span class="muted">${esc(sub)}</span></span>`;
  if (x.kind === 'job') return `<div class="wcrow"><a class="mwa" href="${esc(mwHref(x))}">${body}</a><div class="wcb">${waitJobBtns({id: x.id, kind: x.proposal})}</div></div>`;
  if (x.source === 'chat') return `<button type="button" class="wcrow mwa" data-act="chat-open" data-aid="${x.agent_id}">${body}</button>`;
  return `<a class="wcrow mwa" href="${esc(mwHref(x))}">${body}</a>`;
}
function viewMineWait() {
  if (S.mw.items === null) { mwLoad(true); return `<div class="empty">${esc(tr('Loading…'))}</div>`; }
  if (!S.mw.items.length) return symEmpty('done', tr('Nothing waits for you'));
  return `<div class="mwv">${MW_GROUPS.map(([k, name]) => {
    const xs = S.mw.items.filter(x => x.kind === k);
    return xs.length ? `<section class="waitcard mwg" aria-label="${esc(tr(name))}"><h3>${esc(tr(name))} <span class="muted">${xs.length}</span></h3>${xs.map(mwRow).join('')}</section>` : '';
  }).join('')}</div>`;
}
