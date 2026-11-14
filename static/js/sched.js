// @ts-check
/* Kalmido web client: the plans of an agent (schedOpen: planned jobs, their rhythm and lists) (2.1156.0, #4280: moved here from agents.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

// 2.126.1 B (#2126): what a plan does -- a job in the chat (as before) or "Sort the basket": a proposal card in the morning
const SCHED_ACT = {chat: N_('Job in the chat'), review: N_('Review in the chat'), triage: N_('Sort the basket (proposal)')};  // 2.992.0 (#5684): review = a job in the chat that is a review (the agent's review model)
// lists the agent may work in for me: shared with it, not the inbox (the server checks it again)
const schedLists = aid => (S.lists || []).filter(l => !l.archived && !l.is_inbox && listAgents(l).some(a => a.id === +aid));
function schedRowHtml(s) {
  const last = s.last_state ? tr(SCHED_LAST[s.last_state] || s.last_state) + (s.last_at ? ' · ' + schedWhen(s.last_at) : '') : '';
  return `<div class="schedrow ${s.enabled ? '' : 'off'}" data-sid="${s.id}"><div class="schedi"><b>${esc(s.title)}</b>
      <small class="muted">${esc(s.action === 'triage' ? tr('Sort the basket') + ' · ' : s.action === 'review' ? tr('Review|kind of a planned job') + ' · ' : '')}${esc(schedRhythm(s))}${s.list_name ? ' · ' + esc(s.list_name) : ''}${s.mine ? '' : ' · ' + esc(tr('by {0}', s.by_name))}</small>
      <small class="${s.enabled ? '' : 'muted'}">${esc(schedNext(s))}${last ? ` <span class="muted">· ${esc(tr('last: {0}', last))}</span>` : ''}</small></div>
    <div class="schedb"><label class="chkl schedon" title="${esc(tr('Active'))}"><input type="checkbox" data-sm="toggle" ${s.enabled ? 'checked' : ''} aria-label="${esc(tr('Active: {0}', s.title))}"></label>
      <button type="button" class="btn sm" data-sm="run" ${s.enabled ? '' : 'disabled'}>${ic('play', 's')} ${tr('Run now')}</button>
      <button type="button" class="btn sm" data-sm="edit" aria-label="${esc(tr('Edit: {0}', s.title))}">${ic('edit', 's')}<span class="schedtx"> ${tr('Edit')}</span></button>
      <button type="button" class="btn sm danger" data-sm="del" aria-label="${esc(tr('Delete: {0}', s.title))}">${ic('trash', 's')}</button></div></div>`;
}
async function schedOpen(aid) {
  const a = agentById(aid); if (!a) return;
  let j; try { j = await api('GET', `/api/agents/${a.id}/schedules`); } catch { return; }
  /** @type {any} */
  const md = modal('<div class="schedbody"></div>');
  md.classList.add('schedmd');
  const draw = () => {
    const mine = j.data.filter(s => s.mine).length, own = j.data.filter(s => s.mine && !s.list_check && !s.share_wait), allOff = own.length && own.every(s => !s.enabled);
    // 2.826.0 (#5510): pause / resume all of my plans with this agent in one step (with undo); the chat stays on
    // allBtn: built just above from ic() and esc(tr()) (html-ok below)
    const allBtn = own.length ? `<div class="schedall"><button type="button" class="btn sm" data-sm="all">${ic(allOff ? 'play' : 'pause', 's')} ${esc(allOff ? tr('Resume all') : tr('Pause all'))}</button></div>` : '';
    $('.schedbody', md).innerHTML = `<h3>${ic('clock', 's')} ${esc(tr('Planned jobs: {0}', a.name))}</h3>
      <div class="shint">${esc(tr('{0} gets each plan at its time as a job and answers in your chat. It sees only the projects shared with it.', a.name))}</div>${/*html-ok*/ allBtn}
      <div class="schedlist">${j.data.length ? j.data.map(schedRowHtml).join('') : `<div class="muted mhint">${esc(tr('No plans yet.'))}</div>`}</div>
      <div class="foot"><span class="muted">${esc(tr('{0} of {1}', mine, j.max))}</span><span class="spacer"></span><button class="btn" data-sm="close">${tr('Close')}</button>
        ${j.may_create ? `<button class="btn pri" data-sm="new" ${mine >= j.max ? 'disabled' : ''}>${ic('plus', 's')} ${tr('New plan')}</button>` : ''}</div>`;
  };
  const reload = async () => { try { j = await api('GET', `/api/agents/${a.id}/schedules`); } catch { /* api() showed it */ } draw(); };
  draw();
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-sm]'); if (!b || b.dataset.sm === 'toggle') return;
    const sid = +(b.closest('[data-sid]')?.dataset.sid || 0), s = j.data.find(x => x.id === sid);
    if (b.dataset.sm === 'close') md.remove();
    else if (b.dataset.sm === 'all') {  // 2.826.0 (#5510)
      const own = j.data.filter(x => x.mine && !x.list_check && !x.share_wait), on = own.length > 0 && own.every(x => !x.enabled);
      b.disabled = true;
      let r; try { r = await api('PATCH', `/api/agents/${a.id}/schedules`, {enabled: on}); } catch { b.disabled = false; return; }
      await reload();
      const ids = r.changed || [];
      if (ids.length) toast(on ? trn('{0} plan resumed', '{0} plans resumed', ids.length) : trn('{0} plan paused', '{0} plans paused', ids.length),
        async () => { try { await api('PATCH', `/api/agents/${a.id}/schedules`, {enabled: !on, ids}); } catch { return; } if (md.isConnected) await reload(); });
    } else if (b.dataset.sm === 'new') schedForm(md, a, null, reload);
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
  md.addEventListener('change', async (/** @type {any} */ e) => {
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
  const v = s ? {action: 'chat', ...s} : {action: 'chat', title: '', prompt: '', freq: 'weekly', days: [1], time: '09:00', list_id: null, enabled: true};
  const freqOpts = Object.keys(SCHED_FREQ).map(f => `<option value="${f}" ${v.freq === f ? 'selected' : ''}>${esc(tr(SCHED_FREQ[f]))}</option>`).join('');
  box.innerHTML = `<h3>${ic('clock', 's')} ${esc(isNew ? tr('New plan for {0}', a.name) : tr('Edit plan'))}</h3>
    ${isNew ? `<div class="row ppcol"><span class="lbl">${tr('Start from a template')}</span><div class="schedtpl" role="group">${SCHED_TPL.map(t => `<button type="button" class="chip" data-tpl="${t.k}">${esc(tr(t.t))}</button>`).join('')}</div></div>` : ''}
    ${s?.list_check ? '' : `<div class="row ppcol"><label for="sc-act">${tr('Kind')}</label><select id="sc-act">${Object.keys(SCHED_ACT).map(k => `<option value="${k}" ${v.action === k ? 'selected' : ''}>${esc(tr(SCHED_ACT[k]))}</option>`).join('')}</select></div>`}
    <div class="row ppcol"><label for="sc-title">${tr('Title')}</label><input id="sc-title" maxlength="120" value="${esc(v.title)}"></div>
    <div class="row ppcol"><label for="sc-prompt">${tr('What should the agent do?')} <span class="muted schedopt">${tr('optional')}</span></label><textarea id="sc-prompt" rows="6" maxlength="4000">${esc(v.prompt)}</textarea></div>
    <div class="row schedrh"><label for="sc-freq">${tr('Repeat')}</label><select id="sc-freq">${freqOpts}</select>
      <span class="schedwd" id="sc-wd" role="group" aria-label="${esc(tr('Weekdays'))}">${[1, 2, 3, 4, 5, 6, 7].map(i => `<label class="chkl"><input type="checkbox" data-wd="${i}" ${(v.days || []).includes(i) ? 'checked' : ''}> ${esc(schedWd(i))}</label>`).join('')}</span>
      <input id="sc-dom" type="number" min="1" max="31" value="${v.freq === 'monthly' ? (v.days || [1])[0] : 1}" aria-label="${esc(tr('Day of the month'))}">
      <label for="sc-time" class="sr">${tr('Time')}</label>${timeIn('sc-time', v.time, {label: tr('Time'), clear: false})}</div>
    <div class="row" id="sc-listrow"><label for="sc-list">${tr('Project')}</label><select id="sc-list"><option value="">${tr('No project')}</option>${ls.map(l => `<option value="${l.id}" ${v.list_id === l.id ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}${v.list_id && !ls.some(l => l.id === v.list_id) ? `<option value="${v.list_id}" selected>${esc(v.list_name || '?')}</option>` : ''}</select></div>
    <div class="row"><label class="chkl"><input type="checkbox" id="sc-on" ${v.enabled ? 'checked' : ''}> ${tr('Active')}</label></div>
    <div class="shint" id="sc-trhint" hidden>${esc(tr('At the planned time {0} gets the open items of your basket and your projects, like the button "Sort the basket", and proposes where each one belongs. You find the proposal as a card and decide; nothing is moved before. An empty basket sends nothing.', a.name))}</div>
    <div class="shint" id="sc-chhint">${esc(tr('The agent gets title, text and project at the planned time, at most once per run; after an outage only the one missed run (marked late). Times in your time zone ({0}).', s?.tz || tz || '–'))}</div>
    <div class="calerr" role="alert" id="sc-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-sf="back">${tr('Cancel')}</button><button class="btn pri" data-sf="save">${tr('Save')}</button></div>`;
  const act = () => $('#sc-act', box)?.value || 'chat';
  const vis = () => {
    const f = $('#sc-freq', box).value, tri = act() === 'triage'; $('#sc-wd', box).hidden = f !== 'weekly'; $('#sc-dom', box).hidden = f !== 'monthly';
    $('#sc-listrow', box).hidden = tri; $('.schedopt', box).hidden = !tri; $('#sc-trhint', box).hidden = !tri; $('#sc-chhint', box).hidden = tri;  // 2.126.1 B (#2126)
    $('.schedtpl', box)?.closest('.row')?.toggleAttribute('hidden', tri);
  };
  vis();
  $('#sc-freq', box).addEventListener('change', vis);
  $('#sc-act', box)?.addEventListener('change', () => {  // 2.126.1 B (#2126): "Sort the basket" starts as every working day at 7:30
    if (act() === 'triage' && isNew) {
      if (!$('#sc-title', box).value.trim()) $('#sc-title', box).value = tr('Sort the basket');
      $('#sc-freq', box).value = 'weekdays'; $('#sc-time', box).value = '07:30'; dpSync($('#sc-time', box));
    }
    vis();
  });
  $('#sc-title', box).focus();
  // 2.962.0 (#5232): the form is a step of Back over the plans: Back = Cancel, the list comes back; saving leaves the step
  const back = () => { box.onclick = null; done(); };
  f8d_step(md, back);
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
    if (b.dataset.sf === 'back') { f8d_backBtn(md, back); return; }
    const f = $('#sc-freq', box).value;
    const d = {title: $('#sc-title', box).value.trim(), prompt: $('#sc-prompt', box).value.trim(), freq: f, time: $('#sc-time', box).value || '09:00',
      days: f === 'weekly' ? $$('[data-wd]:checked', box).map(x => +x.dataset.wd) : f === 'monthly' ? [Math.max(1, Math.min(31, +$('#sc-dom', box).value || 1))] : [],
      list_id: act() === 'triage' ? null : +$('#sc-list', box).value || null, enabled: $('#sc-on', box).checked};
    if ($('#sc-act', box)) d.action = act();  // 2.126.1 B (#2126)
    if (isNew && tz) d.tz = tz;
    const er = $('#sc-err', box), fail = m => { er.textContent = m; er.hidden = false; };
    if (!d.title) return fail(tr('Please enter a title.'));
    if (!d.prompt && act() !== 'triage') return fail(tr('Please describe what the agent should do.'));
    if (f === 'weekly' && !d.days.length) return fail(tr('Select at least one weekday'));
    b.disabled = true;
    try { await rawFetch(isNew ? 'POST' : 'PATCH', isNew ? `/api/agents/${a.id}/schedules` : `/api/agent-schedules/${s.id}`, d); }
    catch (x) { b.disabled = false; return fail(x instanceof Offline ? tr('Only available online.') : x.message); }
    toast(tr('Saved')); box.onclick = null; f8d_stepDrop(md); done();
  };
}
