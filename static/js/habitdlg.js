// @ts-check
/* Kalmido web client: the dialog of a habit (habitModal: new / edit, reminders, delete) (2.1156.0, #4280: moved here from habits.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

async function hab_delete(id, name) {
  await api('DELETE', '/api/habits/' + id); await load(); render();
  const msg = tr('“{0}” moved to the trash', name);
  const x = histAdd({label: msg, ids: [],
    undo: async () => { await api('POST', `/api/habits/${id}/restore`); await load(); render(); return {}; },
    redo: async () => { await api('DELETE', '/api/habits/' + id); await load(); render(); return {}; }});
  offerUndo(msg, x);
}
// 2.140.0 C (#2135): up to six reminder times; the old single time (remind_at) is the first one
const HREM_MAX = 6;
const remTimes = x => (x.remind_times || x.remind_at || '').split(',').filter(Boolean);
const remRows = ts => (ts.length ? ts : ['']).map((t, i) => `<span class="hrem">${timeIn('h-rem' + i, t, {label: tr('Reminder'), empty: tr('off')})}</span>`).join('')
  + (ts.length && ts.length < HREM_MAX ? `<button type="button" class="btn sm" data-m="remadd">${ic('plus', 's')} ${tr('Add time')}</button>` : '');
function habitModal(id) {
  const x = id ? S.habits.find(h => h.id === id) : {name: '', goal: 1, days: '1234567', per_week: 0, color: HCOLORS[1], remind_at: '', logs: {}, notes: {}, created_at: new Date().toISOString()};
  x.notes = x.notes || {};
  let selDay = null, noteTimer;
  const ver = id ? x.updated_at || x.created_at : null;  // 2.564.0 D (#4701): the version this dialog opened with
  const st = id ? habitStats(x) : null;
  let month = S.habitMonth || today().slice(0, 7);
  const heat = () => {
    const [y, m] = month.split('-').map(Number);
    const first = ds(new Date(y, m - 1, 1)), lead = (pd(first).getDay() - weekStart() + 7) % 7;
    const n = new Date(y, m, 0).getDate();
    let g = wdOrder().map(i => `<div class="wd">${WD[i]}</div>`).join('') + '<div class="d blank"></div>'.repeat(lead);
    for (let i = 1; i <= n; i++) {
      const d = `${month}-${pad(i)}`, c = x.logs[d] || 0;
      g += `<div class="d ${c >= x.goal ? 'full' : c ? 'part' : ''} ${d === today() ? 'today' : ''} ${x.notes[d] ? 'noted' : ''} ${d === selDay ? 'selday' : ''} ${d > today() ? 'fut' : ''}" data-hday="${d}">${i}</div>`;
    }
    const c = selDay ? (x.logs[selDay] || 0) : 0;
    const panel = selDay ? `<div class="hday"><div class="hdh"><b>${dayLabel(selDay, true)}</b><span class="muted">${fmtDate(selDay)}</span><span class="spacer"></span>
      ${x.goal > 1 ? `<button class="iconbtn" data-hcnt="-1" title="${esc(tr('One less'))}" aria-label="${esc(tr('One less'))}">−</button><span class="mono" title="${esc(tr('{0} of {1} today', c, x.goal))}">${c}/${x.goal}</span><button class="iconbtn" data-hcnt="1" title="${esc(tr('One more'))}" aria-label="${esc(tr('One more'))}">+</button>` : `<button class="btn sm ${c >= 1 ? 'pri' : ''}" data-hcnt="toggle">${c >= 1 ? ic('check', 's') + ' ' + tr('done') : tr('not done')}</button>`}</div>
      <textarea id="h-note" rows="2" placeholder="${tr('Note for this day')}">${esc(x.notes[selDay] || '')}</textarea></div>` : hintSeen('hday') ? '' : `<div class="muted hdhint">${tr('Tap a day: check it off or write a note')}</div>`;
    return `<div class="mcal"><div class="mh"><button class="iconbtn" data-hm="-1" title="${esc(tr('Previous month'))}" aria-label="${esc(tr('Previous month'))}">${ic('left')}</button>${MON[m - 1]} ${y}<button class="iconbtn" data-hm="1" title="${esc(tr('Next month'))}" aria-label="${esc(tr('Next month'))}">${ic('right')}</button></div></div><div class="heat" style="--hc:${cssColor(x.color) || HCOLORS[0]}">${g}</div>${panel}`;
  };
  /** @type {any} */
  const md = modal(`<h3>${id ? esc(x.name) : tr('New habit')}</h3>
    ${st ? `<div class="hstats"><div><b>${st.streak}</b><span>${tr('current streak')}</span></div><div><b>${st.best}</b><span>${tr('best streak')}</span></div><div><b>${st.total}</b><span>${tr('days total')}</span></div><div><b>${st.rate}%</b><span>${tr('last 30 days')}</span></div></div><div id="heatwrap">${heat()}</div><h4>${tr('Settings')}</h4>` : ''}
    <div class="row"><label for="h-name">${tr('Name')}</label><input id="h-name" value="${esc(x.name)}" placeholder="${tr('e.g. reading, workout, water')}"></div>
    <div class="row"><label for="h-goal">${tr('Goal per day')}</label><input id="h-goal" type="number" min="1" max="50" value="${esc(x.goal)}"></div>
    <div class="row"><label>${tr('Frequency')}</label><div class="seg" id="h-freq"><button data-freq="days" class="${x.per_week ? '' : 'on'}">${tr('Fixed days')}</button><button data-freq="week" class="${x.per_week ? 'on' : ''}">${tr('X times a week')}</button></div></div>
    <div class="row ${x.per_week ? 'hidden' : ''}" id="h-daysrow"><label>${tr('days|label')}</label><div class="wdays" id="h-days">${WD_MO().map((w, i) => `<button class="${x.days.includes(String(i + 1)) ? 'on' : ''}" data-wd="${i + 1}">${w}</button>`).join('')}</div></div>
    <div class="row ${x.per_week ? '' : 'hidden'}" id="h-pwrow"><label for="h-pw">${tr('Times per week')}</label><input id="h-pw" type="number" min="1" max="7" value="${esc(x.per_week || 3)}" style="max-width:5.625rem"><span class="muted" style="font-size:var(--fs-s)">${tr('on any days')}</span></div>
    <div class="row hremrow"><label>${tr('Reminder')}</label><div class="hrems" id="h-rems">${remRows(remTimes(x))}</div></div>
    <div class="row"><label>${tr('Colour')}</label><div class="colors" id="h-col" role="group" aria-label="${esc(tr('Colour'))}">${HCOLORS.map((c, i) => `<button type="button" style="background:${c}" class="${(cssColor(x.color) || HCOLORS[0]) === c ? 'on' : ''}" aria-pressed="${(cssColor(x.color) || HCOLORS[0]) === c}" aria-label="${esc(tr('Colour {0}', i + 1))}" data-c="${c}"></button>`).join('')}</div></div>
    <div class="foot">${id ? `<button class="btn danger" data-m="del">${tr('Delete')}</button><button class="btn" data-m="arch">${x.archived ? tr('Reactivate') : tr('Archive')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button,[data-hday]'); if (!b) return;
    if (b.dataset.wd) b.classList.toggle('on');
    if (b.dataset.c) { $$('#h-col button', md).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', String(x === b)); }); }
    if (b.dataset.hm) { const [y, m] = month.split('-').map(Number); const d = new Date(y, m - 1 + +b.dataset.hm, 1); month = ds(d).slice(0, 7); S.habitMonth = month; $('#heatwrap', md).innerHTML = heat(); }
    if (b.dataset.freq) {
      $$('#h-freq button', md).forEach(y => y.classList.toggle('on', y === b));
      $('#h-daysrow', md).classList.toggle('hidden', b.dataset.freq === 'week');
      $('#h-pwrow', md).classList.toggle('hidden', b.dataset.freq !== 'week');
      return;
    }
    if (b.dataset.hday) {  // select the day: tick / note panel below the month
      hintDone('hday');
      if (b.dataset.hday > today()) return;
      selDay = selDay === b.dataset.hday ? null : b.dataset.hday;
      $('#heatwrap', md).innerHTML = heat();
      return;
    }
    if (b.dataset.hcnt && selDay) {
      const c = x.logs[selDay] || 0;
      const n = b.dataset.hcnt === 'toggle' ? (c >= 1 ? 0 : x.goal) : Math.max(0, Math.min(x.goal, c + +b.dataset.hcnt));
      if (n) x.logs[selDay] = n; else delete x.logs[selDay];
      $('#heatwrap', md).innerHTML = heat(); render();
      await api('POST', `/api/habits/${x.id}/log`, {day: selDay, count: n});
      return;
    }
    const act = b.dataset.m;
    if (act === 'remadd') {
      const ts = $$('#h-rems input[data-dp]', md).map(i => i.value).filter(Boolean);
      $('#h-rems', md).innerHTML = remRows([...ts, ts.length ? '12:00' : '09:00']);
    }
    if (act === 'close') md.remove();
    if (act === 'save') {
      const days = $$('#h-days button.on', md).map(b => b.dataset.wd).join('') || '1234567';
      const perWeek = $('#h-freq button.on', md)?.dataset.freq === 'week' ? Math.max(1, Math.min(7, +$('#h-pw', md).value || 1)) : 0;
      const body = {name: $('#h-name', md).value.trim(), goal: Math.max(1, +$('#h-goal', md).value || 1), days, per_week: perWeek, remind_times: [...new Set($$('#h-rems input[data-dp]', md).map(i => i.value).filter(Boolean))].sort(), color: $('#h-col button.on', md)?.dataset.c || HCOLORS[0]};
      if (!body.name) return $('#h-name', md).focus();
      // 2.564.0 D (#4701): 409 = saved meantime elsewhere: api() says why, the current habit is loaded (nothing overwritten)
      if (id) { try { await api('PATCH', '/api/habits/' + id, {...body, ...(ver ? {expect_updated_at: ver} : {})}); } catch (e) { if (e.status === 409) { md.remove(); await load(); render(); } return; } }
      else await api('POST', '/api/habits', body);
      md.remove(); await load(); render();
    }
    if (act === 'arch') { await api('PATCH', '/api/habits/' + id, {archived: x.archived ? 0 : 1}); md.remove(); await load(); render(); }
    // 2.530.0 B (#4315): into the trash with its history, Undo in the toast, restorable below the list until the trash period ends
    if (act === 'del' && await askConfirm(tr('Delete “{0}”?', x.name), tr('The habit goes into the trash with every tick and note and can be restored there until the trash period ends.'), {ok: tr('Delete'), danger: true})) { md.remove(); await hab_delete(id, x.name); }
  });
  md.addEventListener('input', (/** @type {any} */ e) => {
    if (e.target.id !== 'h-note' || !selDay || !id) return;
    const day = selDay, v = e.target.value;
    if (v.trim()) x.notes[day] = v.trim(); else delete x.notes[day];
    clearTimeout(noteTimer);
    noteTimer = setTimeout(async () => { await api('POST', `/api/habits/${x.id}/log`, {day, note: v}); render(); }, 600);
  });
  if (!isTouch() && (!id))  setTimeout(() => $('#h-name', md).focus(), 50);
}
