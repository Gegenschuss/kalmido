// @ts-check
/* Kalmido web client: the "Plan my day" / "Fill free time" dialog (2.10.0, #440), moved out of dayplan.js and loaded on its
   first use (2.149.0 F, #2518; lazyload.js module dayplan, stand-in dayplanModal). The timeline it draws (dpTimeline,
   dpRowsOf) and the cards of Today stay in dayplan.js (loaded at start).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const dpAgents = () => (S.proposers || []).filter(a => a.online !== false && !a.limit_reached);
async function dayplanModal(mode = 'day', day = today()) {
  $('.dpm')?.remove();
  const md = /** @type {any} */ (modal(`<div class="calerr" role="alert" id="dp-err" hidden></div><div class="muted mhint">${tr('Loading…')}</div>`));
  md.classList.add('dpm');
  const st = {mode, day, p: null, sel: new Set(), cals: false}, alt = day !== today() ? day : addDays(today(), 1);
  await cvxCals().catch(() => {});  // 2.36.1 (#956): the subscriptions for the "Calendars" line
  const draw = () => {
    const p = st.p; if (!p || !md.isConnected) return;
    const rows = [...dpRowsOf(p), ...p.plan.map((t, i) => ({...t, kind: 'plan', key: String(i)}))];
    const defer = p.nofit || [];
    const ev = p.events.filter(e => !e.all_day).length, allDay = p.events.filter(e => e.all_day);
    const ags = dpAgents(), n = st.sel.size;
    md.querySelector('.card').innerHTML = `<div class="lhdr"><h3>${st.mode === 'fill' ? tr('Fill free time') : tr('Plan my day')}</h3><span class="spacer"></span><button class="iconbtn" data-dp="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
      <div class="dptabs"><div class="seg" role="group" aria-label="${esc(tr('What to plan'))}"><button data-dp="mode" data-v="day" class="${st.mode === 'day' ? 'on' : ''}" aria-pressed="${st.mode === 'day'}">${tr('Plan my day')}</button><button data-dp="mode" data-v="fill" class="${st.mode === 'fill' ? 'on' : ''}" aria-pressed="${st.mode === 'fill'}">${tr('Fill free time')}</button></div>
        <div class="seg" role="group" aria-label="${esc(tr('Day'))}"><button data-dp="day" data-v="${today()}" class="${st.day === today() ? 'on' : ''}" aria-pressed="${st.day === today()}">${tr('Today')}</button><button data-dp="day" data-v="${alt}" class="${st.day === alt ? 'on' : ''}" aria-pressed="${st.day === alt}">${alt === addDays(today(), 1) ? tr('Tomorrow') : esc(fmtDayAbs(alt))}</button></div></div>
      <div class="dpsum muted">${esc(tr('{0}, working hours {1}–{2}', fmtDayAbs(p.date), p.work.start, p.work.end))} · ${esc(trn('{0} event', '{0} events', ev))} · ${esc(tr('{0} planned', fmtH(p.plan.reduce((n, t) => n + (t.duration || 0), 0))))} · ${esc(tr('{0} still free', fmtH(p.free_min)))}${allDay.length ? ' · ' + esc(tr('all day: {0}', allDay.map(e => e.title).join(', '))) : ''}</div>
      ${ab2_dayHint(p.away)}<div class="calerr" role="alert" id="dp-err" hidden></div>
      ${cvxPlanRow(st.cals)}
      ${dpTimeline(rows, defer, {sel: st.sel, acts: true})}
      <div class="shint keep">${tr('Applying sets the planned start and duration of the selected tasks (a task without a duration gets {0} minutes); due dates and deadlines stay as they are. Undo possible.', p.default_duration)}</div>
      <div class="foot ppfoot">${ags.length ? `<button class="btn" data-dp="agent">${ic('bot', 's')} ${tr('Let an agent plan')}</button>` : ''}<span class="spacer"></span><button class="btn" data-dp="close">${tr('Cancel')}</button><button class="btn pri" data-dp="apply" ${n ? '' : 'disabled'}>${ic('check', 's')} ${esc(trn('Apply {0} entry', 'Apply {0} entries', n))}</button></div>`;
  };
  const fetchPlan = async () => {
    try { st.p = await calReq('GET', `/api/dayplan?date=${st.day}&mode=${st.mode}`); } catch (x) { const e = $('#dp-err', md); if (e) { e.textContent = x.message; e.hidden = false; } return; }
    st.sel = new Set(st.p.plan.map((x, i) => String(i)));
    draw();
  };
  md.addEventListener('toggle', (/** @type {any} */ e) => { if (e.target.classList?.contains('cvxdp')) st.cals = e.target.open; }, true);
  md.addEventListener('change', async (/** @type {any} */ e) => {
    const cp = e.target.closest('[data-cvxplan]');  // 2.36.1 (#956): a calendar counts (or not) when planning -> plan again
    if (cp) { await cvxOff('plan_cals_off', cp.dataset.cvxplan, !cp.checked); fetchPlan(); return; }
    if (!e.target.classList.contains('ppc')) return;
    const r = e.target.closest('.ppi'); if (!r) return;
    e.target.checked ? st.sel.add(r.dataset.k) : st.sel.delete(r.dataset.k);
    r.classList.toggle('off', !e.target.checked);
    const b = $('[data-dp="apply"]', md); if (b) { b.disabled = !st.sel.size; b.innerHTML = `${ic('check', 's')} ${esc(trn('Apply {0} entry', 'Apply {0} entries', st.sel.size))}`; }
  });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-dp]'); if (!b) return;
    const a = b.dataset.dp;
    if (a === 'close') { md.remove(); return; }
    if (a === 'mode' || a === 'day') { st[a] = b.dataset.v; fetchPlan(); return; }
    if (a === 'agent') { dpAskAgent(b, st.day, st.mode, md); return; }
    if (a === 'nofit-tm') { b.disabled = true; if (await dpApply([[+b.dataset.id, {plan_start: `${addDays(st.p.date, 1)}T${st.p.work.start}`}]], tr('Planned for tomorrow'))) fetchPlan(); else b.disabled = false; return; }
    if (a === 'nofit-date') { const t = taskById(+b.dataset.id); if (t) { md.remove(); datePop($(`#view .trow[data-id="${t.id}"]`) || $("#top h1"), t.id); } return; }
    if (a === 'apply') {
      const p = st.p, items = [];
      p.plan.forEach((t, i) => { if (st.sel.has(String(i))) items.push([t.task_id, {plan_start: `${p.date}T${t.start}`, duration: t.duration}]); });
      b.disabled = true;
      if (await dpApply(items, st.mode === 'fill' ? tr('Filled free time') : tr('Planned the day'))) md.remove(); else b.disabled = false;
    }
  });
  fetchPlan();
}
// applies [[task id, {plan_start, duration}]] as ONE history step (batch patch_each; undo sets the old values back)
async function dpApply(items, label) {
  const pairs = [], data = {};
  for (const [id, v] of items) {
    const t = taskById(id); if (!t) continue;
    const before = snapTask(t), prev = {};
    for (const k of Object.keys(v)) prev[k] = t[k] ?? null;
    data[id] = {...v, _prev: prev};
    pairs.push([before, {id, ...v}, Object.keys(v)]);
  }
  if (!pairs.length) return true;
  let r;
  try { r = await api('POST', '/api/tasks/batch', {ids: pairs.map(p => p[0].id), action: 'patch_each', data: {items: data}}); } catch { return false; }
  await load().catch(() => {}); render();
  const e = histFields(label, pairs, {res: r});
  histToast(trn('{0} task planned', '{0} tasks planned', pairs.length), e);
  return true;
}
async function dpAskAgent(anchor, day, mode, md) {
  const ags = dpAgents(); if (!ags.length) return;
  const ask = async a => {
    try { await calReq('POST', '/api/proposals', {agent_id: a.id, kind: 'dayplan', date: day, mode}); } catch (x) { toast(x.message); return; }
    md?.remove();
    toast(tr('{0} is planning your day. You get a notification when the plan is ready.', a.name), null, 6000);
    load().then(render).catch(() => {});
  };
  if (ags.length === 1) ask(ags[0]); else menu(anchor, ags.map(a => ({label: a.name, icon: 'bot', fn: () => ask(a)})));
}
