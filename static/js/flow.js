// @ts-check
/* Kalmido web client, 2.393.2 A (#3374): the card "Flow" of a project page (block 'flow', projects.js POV_BLOCKS): lead time and cycle time
   (median / 85 %), the cumulative flow per column (stacked areas, one accent in steps) and the bug trend per week (bar pairs),
   each also as a table. Computed by the server from the task history (GET /api/lists/<id>/flow?days=30|90), loaded when
   the card is drawn; the period (30 / 90 days) is remembered per project on this device. */
'use strict';

/** @type {Record<number, any>} */
const FLW = {};
/** @param {number} lid */
const flw_days = lid => (LS.get('flwDays', {}) || {})[lid] === 90 ? 90 : 30;
async function flw_load(lid, force) {
  const days = flw_days(lid), d = FLW[lid] || (FLW[lid] = {});
  if (d.busy || (!force && d.j && d.v === S.v && d.days === days)) return;
  d.busy = true;
  try { d.j = await api('GET', `/api/lists/${lid}/flow?days=${days}`); d.err = ''; }
  catch (e) { d.err = e?.message || 'offline'; }
  finally { d.busy = false; d.v = S.v; d.days = days; }
  if (routeList()?.id === lid) viewSafeRender();
}
const flw_dd = v => v == null ? '–' : tr('{0} days|flow', fmtNum(v));
function flw_colName(k) {
  if (k.kind === 'none') return tr('No column');
  if (k.kind === 'gone') return tr('Earlier column');
  return typeof le2eShow === 'function' ? le2eShow(k.name) : k.name || '';
}
// stacked from the bottom: done first, then the columns from the last board column to the first
function flw_cfdSvg(j) {
  const cols = j.cfd.columns, days = j.cfd.days, n = days.length; if (n < 2) return '';
  const ser = [{name: tr('Completed'), v: days.map(d => d.done)}, ...cols.map((k, i) => ({name: flw_colName(k), v: days.map(d => d.columns[i])})).reverse()];
  const W = 300, H = 100, P = 2, tot = days.map((_, i) => ser.reduce((s, x) => s + x.v[i], 0)), max = Math.max(1, ...tot);
  const X = i => (P + i / (n - 1) * (W - 2 * P)).toFixed(1), Y = v => (H - P - v / max * (H - 2 * P)).toFixed(1);
  const acc = days.map(() => 0), op = i => (1 - i * 0.7 / Math.max(1, ser.length - 1)).toFixed(2);
  const polys = ser.map((x, si) => {
    const lo = acc.slice(); x.v.forEach((v, i) => { acc[i] += v; });
    const pts = [...acc.map((v, i) => `${X(i)},${Y(v)}`), ...lo.map((v, i) => `${X(i)},${Y(v)}`).reverse()].join(' ');
    return `<polygon points="${pts}" fill="var(--accent)" fill-opacity="${op(si)}"><title>${esc(x.name)}</title></polygon>`;
  }).join('');
  const last = days[n - 1], lab = tr('Cumulative flow: {0} open, {1} done on {2}', tot[n - 1] - last.done, last.done, fmtDate(last.day));
  const lg = ser.map((x, si) => `<span><i style="background:var(--accent);opacity:${op(si)}"></i>${esc(x.name)}</span>`).reverse().join('');
  return `<svg class="msburn flwcfd" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(lab)}">${polys}</svg><div class="flwlg" aria-hidden="true">${lg}</div>`;
}
function flw_cfdTable(j) {
  const cols = j.cfd.columns;
  return `<details class="msbtab"><summary>${tr('Show as table')}</summary><table><thead><tr><th scope="col">${tr('Day')}</th>${cols.map(k => `<th scope="col">${esc(flw_colName(k))}</th>`).join('')}<th scope="col">${tr('Completed')}</th></tr></thead><tbody>${j.cfd.days.map(d => `<tr><td>${esc(fmtDate(d.day))}</td>${d.columns.map(v => `<td>${v}</td>`).join('')}<td>${d.done}</td></tr>`).join('')}</tbody></table></details>`;
}
function flw_bugHtml(j) {
  const ws = j.bugs || []; if (!ws.some(w => w.created || w.done)) return `<div class="muted">${tr('No bugs in this period.')}</div>`;
  const max = Math.max(1, ...ws.map(w => Math.max(w.created, w.done))), B = 10, G = 3, S2 = 10, H = 60, wd = ws.length * (2 * B + G + S2) - S2;
  const y = v => H - Math.round(v / max * (H - 2));
  const bars = ws.map((w, i) => { const x = i * (2 * B + G + S2), wk = w.week.split('-W')[1] || w.week;
    return `<g><title>${esc(tr('Week {0}: {1} new, {2} completed', wk, w.created, w.done))}</title><rect x="${x}" y="${y(w.created)}" width="${B}" height="${H - y(w.created)}" rx="2" fill="var(--accent)" fill-opacity=".4"/><rect x="${x + B + G}" y="${y(w.done)}" width="${B}" height="${H - y(w.done)}" rx="2" fill="var(--accent)"/><text x="${x + B + G / 2}" y="${H + 11}" class="sptlab" text-anchor="middle">${esc(wk)}</text></g>`; }).join('');
  const sumC = ws.reduce((s, w) => s + w.created, 0), sumD = ws.reduce((s, w) => s + w.done, 0);
  return `<svg class="flwbug" viewBox="0 0 ${Math.max(wd, 1)} ${H + 14}" role="img" aria-label="${esc(tr('Bug trend: {0} new, {1} completed', sumC, sumD))}">${bars}</svg>
    <div class="flwlg" aria-hidden="true"><span><i style="background:var(--accent);opacity:.4"></i>${tr('New bugs')}</span><span><i style="background:var(--accent)"></i>${tr('Completed bugs')}</span></div>
    <details class="msbtab"><summary>${tr('Show as table')}</summary><table><thead><tr><th scope="col">${tr('Week')}</th><th scope="col">${tr('New bugs')}</th><th scope="col">${tr('Completed bugs')}</th></tr></thead><tbody>${ws.map(w => `<tr><td>${esc(w.week)}</td><td>${w.created}</td><td>${w.done}</td></tr>`).join('')}</tbody></table></details>`;
}
function flw_html(l) {
  const d = FLW[l.id], days = flw_days(l.id);
  if (!d || (!d.busy && (d.v !== S.v || d.days !== days))) setTimeout(() => flw_load(l.id), 0);
  const j = d?.j;
  if (!j) return `<div class="muted">${d?.err ? (d.err === 'offline' ? tr('Only available online.') : esc(d.err)) : tr('Loading…')}</div>`;
  const tile = (t, v) => `<div class="fxk"><span class="fxkt">${esc(t)}</span><b class="fxkv">${esc(flw_dd(v))}</b></div>`;
  const tiles = `<div class="fxkpis">${tile(tr('Lead time, median'), j.lead_time.median)}${tile(tr('Lead time, 85 %'), j.lead_time.p85)}${tile(tr('Cycle time, median'), j.cycle_time.median)}</div>`;
  const notes = [tr('{0} tasks completed in the period', j.lead_time.n)];
  if (j.e2e) notes.push(tr('Locked project: only open and done count, no columns.'));
  else if (!j.cycle_time.columns.length) notes.push(tr('Cycle time counts from a column named “In Arbeit”, “In progress”, “Doing” or “WIP”.'));
  if (j.capped) notes.push(tr('Only the newest {0} tasks are counted.', fmtNum(2000)));
  return `<div class="flw">${tiles}<div class="muted flwnote">${notes.map(esc).join(' · ')}</div>
    <h6>${tr('Cumulative flow')}</h6>${flw_cfdSvg(j)}${flw_cfdTable(j)}<h6>${tr('Bug trend')}</h6>${flw_bugHtml(j)}</div>`;
}
function flw_povPart(l) {  // the block "Flow" of the project page; undefined = not offered (the basket)
  if (!l || l.is_inbox) return undefined;
  const days = flw_days(l.id);
  const seg = `<span class="seg flwseg" role="group" aria-label="${esc(tr('Period'))}">${[30, 90].map(n => `<button type="button" data-flw-days="${n}" data-id="${l.id}" class="${n === days ? 'on' : ''}" aria-pressed="${n === days}">${esc(tr('{0} days|flow', n))}</button>`).join('')}</span>`;
  return x => povSec('flow', tr('Flow'), flw_html(l), seg + x);
}
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-flw-days]'); if (!(b instanceof HTMLElement)) return;
  e.preventDefault();
  const lid = +b.dataset.id, m = LS.get('flwDays', {}) || {};
  m[lid] = +b.dataset.flwDays === 90 ? 90 : 30; LS.set('flwDays', m);
  flw_load(lid, true); viewSafeRender();
});
