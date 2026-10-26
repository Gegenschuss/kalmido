// @ts-check
// 2.236.0 A (#2904-#2911): the dialog "Work style and notifications" of an agent: budget, work and quiet times, tasks at once +
// queue, priority rule, report style, when/where it reports. Autosave per field: PATCH /api/agents/<id>/work-style with ONLY the
// changed key (quiet tick like the neighbours), no save bar. Opened from Settings > Agents, the agent dialog of the admins and the
// permission menu of the chat header; the owner of a personal agent or an instance admin (team agent) only - the server answers 404
// for everyone else. Kalmido never runs the agent: its host reads these values (GET /api/v1/agent "work_style").
const AW_OPTS = {
  budget_period: [['', N_('No budget')], ['day', N_('Per day')], ['week', N_('Per week')]],
  budget_metric: [['tokens', N_('Tokens')], ['cost', N_('Costs')]],
  work_mode: [['always', N_('Always')], ['office', N_('Office hours only')]],
  quiet_mode: [['off', N_('Off')], ['on', N_('On')]],
  report_length: [['line', N_('One line')], ['short', N_('Short')], ['long', N_('Detailed')]],
  push: [['limits', N_('Only at limits')], ['results', N_('At every result')], ['never', N_('Never')]],
  results_to: [['comment', N_('Comment on the task')], ['chat', N_('Chat')], ['both', N_('Both (comment + one line in the chat)')]],
};
const aw_sel = (k, v) => `<select id="aw-${k}" data-aw="${k}">${AW_OPTS[k].map(([o, n]) => `<option value="${o}" ${String(v) === o ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>`;
const aw_chk = (k, v, label) => `<label class="chkl"><input type="checkbox" id="aw-${k}" data-aw="${k}" ${v ? 'checked' : ''}> ${esc(label)}</label>`;
const aw_hm = (k, v, label) => `<span class="awtime">${timeIn('aw-' + k, v || '', {label, clear: false, attrs: `data-aw="${k}"`})}</span>`;
const aw_dow = i => new Date(2024, 0, 1 + i).toLocaleDateString(LOCALE(), {weekday: 'short'});  // 1 Jan 2024 = Monday
const aw_num = n => Number(n).toLocaleString(LOCALE(), {maximumFractionDigits: 2});
const aw_langs = () => [['', tr('Like my profile')], ...(S.languages || []).map(l => [l.code, l.name])];
// the line under the budget fields: what is used so far (B delivers budget_state: null = no budget)
function aw_budgetLine(b) {
  if (!b) return '';
  const unit = b.metric === 'cost' ? tr('costs') : tr('tokens'), when = b.period === 'week' ? tr('this week') : tr('today');
  const t = tr('{0}: {1} of {2} {3} ({4} %)', when, aw_num(b.used), aw_num(b.limit), unit, aw_num(b.pct));
  return `<div class="awstate ${b.paused ? 'warn' : ''}" role="status">${esc(t)}${b.paused ? ' · ' + esc(b.resets_at ? tr('Paused until {0}', fmtWhen(b.resets_at)) : tr('Paused')) : ''}</div>`;
}
// the queue: a plain fetch, not api() - a missing route or an error must give "no list", never the page reload api() does on an HTML answer
const aw_queue = base => fetch(base + '/queue', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.ok ? r.json() : null).catch(() => null);
function aw_queueHtml(q) {
  if (!q) return '';
  const items = q.items || [];
  if (!items.length) return `<div class="muted mhint">${tr('No tasks in the queue.')}</div>`;
  return `<div class="awq">${items.map(x => x.hidden ? `<div class="mrow awqi ${x.state}"><span class="n muted">${esc(tr('A task you cannot see'))}</span><span class="awqs">${x.state === 'active' ? esc(tr('active')) : esc(tr('waits, place {0}', x.position))}</span></div>` : `<div class="mrow awqi ${x.state}"><span class="n"><button type="button" class="linkbtn" data-aw-task="${x.task_id}">${esc(x.title)}</button><small class="muted">${esc(x.list_name || '')}</small></span><span class="awqs">${x.state === 'active' ? esc(tr('active')) : esc(tr('waits, place {0}', x.position))}</span></div>`).join('')}</div>`;
}
function aw_html(ws, st) {
  const off = ws.budget_period === '', office = ws.work_mode === 'office', quiet = ws.quiet_mode === 'on';
  // 2.235.0 (#2891 #2902 #2903): the sections Control / Data the agent never sees / Standing rules (agentcontrol.js, agentlock.js, agentrules.js)
  return `<div id="aw-control"></div><div id="aw-lock"></div><div id="aw-rules"></div>
    <h4 id="aw-h-budget">${tr('Budget')}</h4>
    <div class="row"><label for="aw-budget_period">${tr('Period')}</label>${aw_sel('budget_period', ws.budget_period)}</div>
    <div class="awsub" id="aw-budget" ${off ? 'hidden' : ''}>
      <div class="row"><label for="aw-budget_metric">${tr('Measured in')}</label>${aw_sel('budget_metric', ws.budget_metric)}</div>
      <div class="row"><label for="aw-budget_limit">${tr('Limit')}</label><input id="aw-budget_limit" data-aw="budget_limit" inputmode="decimal" autocomplete="off" value="${esc(ws.budget_limit ?? '')}" placeholder="${esc(tr('No limit'))}"></div>
      <div class="row"><label for="aw-budget_warn_pct">${tr('Notice from')}</label><span class="agpct"><input id="aw-budget_warn_pct" data-aw="budget_warn_pct" type="number" min="0" max="99" step="1" inputmode="numeric" value="${esc(ws.budget_warn_pct)}"><span class="muted">%</span></span></div>
      <div id="aw-bstate"></div>
      <div class="shint">${tr('From the limit on the agent pauses until the next period; before that it sends a notice.')}</div>
    </div>
    <h4 id="aw-h-time">${tr('Work time and quiet time')}</h4>
    <div class="row"><label for="aw-work_mode">${tr('Works')}</label>${aw_sel('work_mode', ws.work_mode)}</div>
    <div class="awsub" id="aw-office" ${office ? '' : 'hidden'}>
      <div class="row"><label>${tr('From')}</label>${aw_hm('work_from', ws.work_from, tr('From'))}<span class="muted">${tr('to')}</span>${aw_hm('work_to', ws.work_to, tr('To'))}</div>
      <div class="row"><label id="aw-days-h">${tr('Weekdays')}</label><div class="awdays" role="group" aria-labelledby="aw-days-h">${[1, 2, 3, 4, 5, 6, 7].map(d => `<label class="chkl awday"><input type="checkbox" data-aw-day="${d}" ${ws.work_days.includes(d) ? 'checked' : ''}><span>${esc(aw_dow(d - 1))}</span></label>`).join('')}</div></div>
    </div>
    <div class="row"><label for="aw-quiet_mode">${tr('Quiet time for messages')}</label>${aw_sel('quiet_mode', ws.quiet_mode)}</div>
    <div class="awsub" id="aw-quiet" ${quiet ? '' : 'hidden'}>
      <div class="row"><label>${tr('From')}</label>${aw_hm('quiet_from', ws.quiet_from, tr('From'))}<span class="muted">${tr('to')}</span>${aw_hm('quiet_to', ws.quiet_to, tr('To'))}</div>
      <div class="shint">${tr('The agent keeps working quietly; the messages come together at the end of the quiet time.')}</div>
    </div>
    <h4 id="aw-h-par">${tr('Tasks at once')}</h4>
    <div class="row"><label for="aw-max_parallel">${tr('At most')}</label><span class="agpct"><input id="aw-max_parallel" data-aw="max_parallel" type="number" min="0" max="20" step="1" inputmode="numeric" value="${esc(ws.max_parallel)}"><span class="muted" id="aw-nolimit">${ws.max_parallel ? '' : esc(tr('no limit'))}</span></span></div>
    <div class="shint">${tr('0 = no limit. The rest waits in the queue.')}</div>
    <div id="aw-queue"></div>
    <h4 id="aw-h-prio">${tr('Priority rule')}</h4>
    <textarea id="aw-priority_rule" data-aw="priority_rule" rows="3" maxlength="500" placeholder="${esc(tr('e.g. bugs first, then office, then new things'))}" aria-labelledby="aw-h-prio">${esc(ws.priority_rule)}</textarea>
    <div class="shint">${tr('In your words; the agent reads it with every choice of the next task.')}</div>
    <h4 id="aw-h-rep">${tr('Reports')}</h4>
    <div class="row"><label for="aw-report_length">${tr('Length')}</label>${aw_sel('report_length', ws.report_length)}</div>
    <div class="row"><label for="aw-report_lang">${tr('Language')}</label><select id="aw-report_lang" data-aw="report_lang">${aw_langs().map(([c, n]) => `<option value="${esc(c)}" ${ws.report_lang === c ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
    <div class="row"><label></label>${aw_chk('report_tables', ws.report_tables, tr('Tables allowed'))}</div>
    <div class="row"><label></label>${aw_chk('report_jargon', ws.report_jargon, tr('Technical terms allowed'))}</div>
    <h4 id="aw-h-msg">${tr('Messages')}</h4>
    <div class="row"><label for="aw-push">${tr('May disturb')}</label>${aw_sel('push', ws.push)}</div>
    <div class="shint">${tr('Limits: a one-way step, a refusal, a stop or an error.')}</div>
    <div class="row"><label for="aw-results_to">${tr('Results go to')}</label>${aw_sel('results_to', ws.results_to)}</div>
    <div class="row"><label></label>${aw_chk('next_step', ws.next_step, tr('Next step as a button at the end of every answer'))}</div>`;
}
// parses the field of key k into the value the server wants (null = invalid, shown under the field)
function aw_read(k, el) {
  if (k === 'budget_limit') { const s = el.value.trim().replace(',', '.'); if (!s) return null; const n = +s; return Number.isFinite(n) && n > 0 ? n : undefined; }
  if (k === 'budget_warn_pct' || k === 'max_parallel') { const s = el.value.trim(); return /^\d+$/.test(s) ? +s : undefined; }
  if (el.type === 'checkbox') return el.checked;
  return el.value;
}
async function awOpen(agent) {
  const aid = agent.id, base = `/api/agents/${aid}`;
  let j;
  try { j = await api('GET', base + '/work-style'); } catch (e) { toast(e instanceof Offline ? tr('Only available online.') : e.message); return; }
  let ws = j.work_style;
  const md = /** @type {any} */ (modal(`<h3>${esc(tr('Work style and notifications'))}</h3>
    <div class="shint keep">${esc(tr('How {0} works and reports. Changes are saved at once; the agent reads them at its next contact.', agent.name))}</div>
    <div id="aw-body">${aw_html(ws, j.state)}</div>
    <div class="calerr" role="alert" id="aw-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`));
  md.classList.add('awdlg');
  const $b = s => $(s, md), show = m => { const e = $b('#aw-err'); e.textContent = m || ''; e.hidden = !m; };
  const stateDraw = b => { const e = $b('#aw-bstate'); if (e) e.innerHTML = aw_budgetLine(b); };
  stateDraw(j.budget_state);
  awc_mount(md, agent); awl_mount(md, agent); awr_mount(md, agent);  // 2.235.0 A-C: each draws into its container
  aw_queue(base).then(q => { const e = $b('#aw-queue'); if (e) e.innerHTML = aw_queueHtml(q); });  // 404 / error: no list
  const reveal = () => {
    $b('#aw-budget').hidden = ws.budget_period === ''; $b('#aw-office').hidden = ws.work_mode !== 'office'; $b('#aw-quiet').hidden = ws.quiet_mode !== 'on';
    $b('#aw-nolimit').textContent = ws.max_parallel ? '' : tr('no limit');
  };
  let chain = Promise.resolve();  // saves one after the other: the server merges key by key (read, change, write)
  const save = (k, v, el) => chain = chain.then(() => save1(k, v, el));
  const save1 = async (k, v, el) => {
    show('');
    try {
      const r = await api('PATCH', `${base}/work-style`, {[k]: v});
      ws = r.work_style; if ('budget_state' in r) stateDraw(r.budget_state);
      if (k === 'max_parallel') aw_queue(base).then(q => { const e = $b('#aw-queue'); if (e) e.innerHTML = aw_queueHtml(q); });
      reveal(); savedTick(el);
    } catch (e) {
      show(e instanceof Offline ? tr('Only available online.') : e.message);
      if (el && k in ws) { if (el.type === 'checkbox') el.checked = !!ws[k]; else el.value = ws[k] ?? ''; }
    }
  };
  md.addEventListener('change', e => {
    const el = /** @type {any} */ (e.target).closest('[data-aw], [data-aw-day]'); if (!el) return;
    if (el.dataset.awDay) {
      const days = $$('[data-aw-day]', md).filter(x => x.checked).map(x => +x.dataset.awDay);
      if (!days.length) { el.checked = true; show(tr('Pick at least one weekday.')); return; }
      save('work_days', days, el); return;
    }
    const k = el.dataset.aw, v = aw_read(k, el);
    if (v === undefined) { show(tr('Invalid value: {0}', el.getAttribute('aria-label') || k)); el.value = ws[k] ?? ''; return; }
    if (k === 'priority_rule' && v.trim() === ws.priority_rule) return;
    save(k, v, el);
  });
  md.addEventListener('click', e => {
    const t = /** @type {any} */ (e.target).closest('[data-aw-task]');
    if (t) { const id = +t.dataset.awTask; md.remove(); (async () => { if (!taskById(id)) { try { (S.extra ||= []).push(await rawFetch('GET', `/api/tasks/${id}`)); } catch { toast(tr('Task not found')); return; } } openDetail(id); })(); return; }
    if (/** @type {any} */ (e.target).closest('[data-m="close"]')) md.remove();
  });
}
