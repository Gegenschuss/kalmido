/* Kalmido web client: the tracked time of a project in a window (2.43.0, #1434).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// A click on "Tracked" in a project / folder header (the span carries data-tsum="listId,listId") opens "Tracked time · name":
// the sum in hours and days (+ budget bar), split by person and by task, a period (all / this month / last month / custom), the
// latest entries, CSV for this project, the time module with the filter, and (one project) "Delete all times of this project".
const tz_PER = [['all', N_('All time')], ['month', N_('This month')], ['lastmonth', N_('Last month')], ['custom', N_('Custom')]];
function tz_range(per, from, to) {
  const t = today(), m0 = t.slice(0, 8) + '01';
  if (per === 'month') return [m0, monthEnd(m0)];
  if (per === 'lastmonth') { const d = pd(m0), p = ds(new Date(d.getFullYear(), d.getMonth() - 1, 1)); return [p, monthEnd(p)]; }
  if (per === 'custom' && from && to) return from <= to ? [from, to] : [to, from];
  return ['', ''];
}
function tz_query(ids, per, from, to) {
  const [f, t] = tz_range(per, from, to), q = new URLSearchParams({scope: hasSharing() ? 'all' : 'mine', lists: ids.join(',')});
  if (f) { q.set('from', f); q.set('to', t); }
  return q.toString();
}
function tz_bars(rows, total) {
  return rows.map(([n, s]) => `<div class="tzrow"><span class="tzn">${esc(n)}</span><span class="tzb" role="img" aria-label="${esc(fmtDur(s))}"><i style="width:${total ? Math.max(2, Math.round(s / total * 100)) : 0}%"></i></span><b>${esc(fmtDur(s))}</b></div>`).join('');
}
function tz_body(ids, d) {
  const ls = ids.map(listById).filter(Boolean), sec = d.total.seconds, h = sec / 3600;
  const days = ls.length ? ls.reduce((a, l) => a + (d.lists.find(x => x.id === l.id)?.seconds || 0) / 3600 / dayHOf(l), 0) : 0;
  const bud = ls.reduce((a, l) => a + +(S.timeLists?.[l.id]?.b || 0), 0), pct = bud ? Math.min(100, Math.round(h / bud * 100)) : 0;
  const dtxt = Math.abs(days - 1) < .05 ? tr('{0} day|time', fmtNum(1)) : tr('{0} days|time', fmtNum(days));
  const users = d.users.map(u => [u.name, u.seconds]), tasks = d.lists.flatMap(l => l.tasks).sort((a, b) => b.seconds - a.seconds).slice(0, 8).map(t => [t.title || tr('No task'), t.seconds]);
  const last = d.entries.slice().reverse().slice(0, 8);
  return `<div class="tzsum ${bud && h > bud ? 'over' : ''}"><b>${esc(fmtNum(h))} h</b><span class="muted">${esc(dtxt)}</span>${bud ? `<span class="tbud" role="img" aria-label="${esc(tr('{0} % of the budget', Math.round(h / bud * 100)))}"><i style="width:${pct}%"></i></span><span class="tbn">${esc(fmtNum(h))}/${esc(fmtNum(bud))} h</span>` : ''}</div>
    ${d.total.count ? `<h4>${tr('By person')}</h4>${tz_bars(users, sec)}<h4>${tr('By task')}</h4>${tz_bars(tasks, sec)}
    <h4>${tr('Latest entries')}</h4>${last.map(e => `<div class="tzent"><span class="muted">${esc(fmtDate(e.day))}</span><span class="tzn">${esc(e.title || tr('No task'))}${e.user_name ? ` · ${esc(e.user_name)}` : ''}</span><b>${esc(fmtDur(e.seconds))}</b></div>`).join('')}`
    : `<div class="muted mhint">${tr('No time tracked in this period.')}</div>`}`;
}
async function tz_open(ids, name) {
  let per = 'all', from = '', to = '';
  const one = ids.length === 1 ? ids[0] : 0;
  const md = modal(`<h3>${tr('Tracked time')} · ${esc(name)}</h3>
    <div class="tzper"><select id="tz-per" aria-label="${esc(tr('Period'))}">${tz_PER.map(([k, n]) => `<option value="${k}">${esc(tr(n))}</option>`).join('')}</select>
      <span id="tz-cust" hidden><input type="date" id="tz-from"> <input type="date" id="tz-to"></span></div>
    <div id="tz-body"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><a class="btn" id="tz-csv" download>${ic('download', 's')} CSV</a><button class="btn" data-m="tz-open">${tr('Open in time tracking')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>
    ${one && !isViewer(one) ? `<div class="tzdanger"><button class="btn danger" data-m="tz-wipe">${ic('trash', 's')} ${tr('Delete all times of this project')}</button></div>` : ''}`);
  md.classList.add('tzmodal');
  const load = async () => {
    const q = tz_query(ids, per, from, to), box = $('#tz-body', md);
    $('#tz-csv', md).href = '/api/time/export.csv?' + q;
    try { const d = await rawFetch('GET', '/api/time/report?' + q); if (box.isConnected) box.innerHTML = tz_body(ids, d); }
    catch (e) { box.innerHTML = `<div class="muted mhint">${e instanceof Offline ? tr('Only available online.') : esc(e.message)}</div>`; }
  };
  $('#tz-per', md).onchange = e => { per = e.target.value; $('#tz-cust', md).hidden = per !== 'custom'; if (per !== 'custom' || (from && to)) load(); };
  $('#tz-from', md).onchange = e => { from = e.target.value; if (from && to) load(); };
  $('#tz-to', md).onchange = e => { to = e.target.value; if (from && to) load(); };
  md.addEventListener('click', e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') modalClose(md);
    else if (b.dataset.m === 'tz-open') { modalClose(md); tz_toModule(ids, per, from, to); }
    else if (b.dataset.m === 'tz-wipe') { modalClose(md); tz_wipe(one, name); }
  });
  load();
}
const isViewer = lid => !['owner', 'admin', 'edit', 'participant'].includes(listRole(lid));
// the time module with the project as filter (period: all = from the beginning)
function tz_toModule(ids, per, from, to) {
  const [f, t] = tz_range(per, from, to);
  S.tv.client = null; S.tv.lists = ids.slice(); LS.set('timeLists', S.tv.lists);
  S.tv.period = 'custom'; S.tv.from = f || '2000-01-01'; S.tv.to = t || today();
  LS.set('timePeriod', 'custom'); LS.set('timeFrom', S.tv.from); LS.set('timeTo', S.tv.to);
  go('time');
}
// "Delete all times of this project": count + hours first, type the project's name, then one Undo step
async function tz_wipe(lid, name) {
  let pv;
  try { pv = await rawFetch('GET', `/api/lists/${lid}/time/delete-all`); } catch (e) { toast(e instanceof Offline ? tr('Only available online.') : e.message); return; }
  if (!pv.count) { toast(pv.billed ? tr('Nothing to delete: {0} already billed, they stay', pv.billed) : tr('No time tracked in this project.')); return; }
  const md = modal(`<h3>${tr('Delete all times of this project')}</h3>
    <p>${pv.all ? tr('{0} entries ({1}) of everybody in {2} will be deleted.', pv.count, fmtDur(pv.seconds), esc(name)) : tr('Your {0} entries ({1}) in {2} will be deleted. Entries of others stay.', pv.count, fmtDur(pv.seconds), esc(name))}</p>
    ${pv.billed ? `<p class="muted">${tr('{0} entries are already billed and stay.', pv.billed)}</p>` : ''}
    <p class="muted">${tr('Save a CSV first: it is the only copy afterwards.')} <a href="/api/time/export.csv?${esc(tz_query([lid], 'all', '', ''))}" download>CSV</a></p>
    <label class="shint keep">${tr('Type the project name to confirm')}<input type="text" id="tz-conf" autocomplete="off" placeholder="${esc(name)}"></label>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn danger" data-m="go" disabled>${tr('Delete')}</button></div>`);
  const inp = $('#tz-conf', md), go_ = $('[data-m=go]', md);
  inp.oninput = () => { go_.disabled = inp.value.trim() !== name; };
  if (!isTouch()) setTimeout(() => inp.focus(), 50);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') return modalClose(md);
    if (go_.disabled) return;
    go_.disabled = true;
    let r;
    try { r = await rawFetch('POST', `/api/lists/${lid}/time/delete-all`, {confirm: inp.value.trim()}); } catch (er) { go_.disabled = false; toast(er.message); return; }
    modalClose(md);
    await timeChanged(r);
    const back = r.entries, msg = tr('{0} time entries deleted', r.deleted);
    const x = histAdd({label: msg, res: r, lids: [lid],
      undo: async h => { const j = await rawFetch('POST', `/api/lists/${lid}/time/restore`, {entries: back}); await timeChanged(j); return {q: j?._q || null}; },
      redo: async h => { const j = await rawFetch('POST', `/api/lists/${lid}/time/delete-all`, {confirm: name}); await timeChanged(j); return {q: j?._q || null}; }});
    offerUndo(msg, x);
  });
}
// the click (and Enter / Space on the focusable span) on "Tracked"
function tz_hit(e) {
  const el = e.target.closest?.('.tsum[data-tsum]'); if (!el || MW_ON) return;
  const ids = el.dataset.tsum.split(',').map(Number).filter(Boolean), ls = ids.map(listById).filter(Boolean); if (!ls.length) return;
  e.preventDefault(); e.stopPropagation();
  tz_open(ids, ls.length === 1 ? lname(ls[0]) : (el.dataset.tsumName || lname(ls[0])));
}
document.addEventListener('click', tz_hit, true);
document.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches?.('.tsum[data-tsum]')) tz_hit(e); }, true);
