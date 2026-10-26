// @ts-check
/* Kalmido web client: the agent runtime section "Interim summary" (2.233.0 B, #3189): when the agent's host ends a chat
   conversation with a summary and starts a fresh one (session size, runs, minutes of pause, the daily summary time =
   runtime nightly_reset). Kalmido only stores it (GET /api/v1/agent "runtime"); every field saves at once. Shown in the
   admin's agent dialog (agentchat.js, below "Runtime") and in the permissions dialog of a personal agent (settings.js).
   base = /api/admin/agents/<id> or /api/my/agents/<id>. */
'use strict';

const AGZ_SIZES = [['small', N_('Small'), '0.4 MB'], ['medium', N_('Medium'), '0.8 MB'], ['large', N_('Large'), '1.5 MB']];
// the section; own = also its own time field (the admin dialog already has #ag-nr: agz_wire moves it in here)
/** @param {any} a @param {boolean} [own] */
function agz_html(a, own) {
  if (!a) return '';
  const rt = a.runtime || {}, size = rt.rotate_size || 'medium', idle = rt.rotate_idle_min ?? 45;
  return `<div class="agzsec" data-agz="${a.id}"><h4 id="agz-h">${tr('Interim summary')}</h4>
    <div class="shint">${tr('The agent then starts a new conversation with a summary of the previous one: this saves cost, but it can forget details. Its host applies it.')}</div>
    <div class="row"><label for="agz-size">${tr('Session size')}</label><select id="agz-size" data-agzk="rotate_size">${AGZ_SIZES.map(([k, n, mb]) => `<option value="${k}" ${size === k ? 'selected' : ''}>${esc(tr(n))} (${mb})</option>`).join('')}</select></div>
    <div class="row"><label for="agz-runs">${tr('After messages')}</label><input id="agz-runs" class="numin" data-agzk="rotate_runs" type="number" min="10" max="500" step="1" inputmode="numeric" value="${rt.rotate_runs ?? 60}"></div>
    <div class="row"><label for="agz-idle">${tr('After a pause of')}</label><span class="agpct"><input id="agz-idle" class="numin" data-agzk="rotate_idle_min" type="number" min="0" max="1440" step="1" inputmode="numeric" value="${idle}"><span class="muted">${tr('min')}</span></span></div>
    <div class="shint">${tr('Pause: 0 = never; it counts only from the small size on.')}</div>
    ${own ? `<div class="row agznr"><label>${tr('Daily summary')}</label>${timeIn('agz-nr', rt.nightly_reset || '', {label: tr('Daily summary'), empty: tr('Agent default')})}</div>` : '<div class="agznr-slot"></div>'}</div>`;
}
/** @type {Record<string, number[]>} */
const AGZ_RANGE = {rotate_runs: [10, 500], rotate_idle_min: [5, 1440]};
// autosave of the section's fields; in the admin dialog the existing "Nightly fresh restart" row moves in as "Daily summary"
/** @param {any} md @param {any} a @param {string} base */
function agz_wire(md, a, base) {
  const sec = a && $(`.agzsec[data-agz="${a.id}"]`, md); if (!sec) return;
  const slot = $('.agznr-slot', sec), nr = slot && $('#ag-nr', md)?.closest('.row');
  if (nr) { const l = $('label', nr); if (l) l.textContent = tr('Daily summary'); slot.replaceWith(nr); nr.classList.add('agznr'); }
  sec.addEventListener('change', async (/** @type {any} */ e) => {
    const el = e.target, k = el.dataset.agzk || (['ag-nr', 'agz-nr'].includes(el.id) ? 'nightly_reset' : ''); if (!k) return;
    const rt = a.runtime || (a.runtime = {});
    const raw = String(el.value);
    /** @type {string | number} */
    let v = raw;
    if (AGZ_RANGE[k]) {
      const [lo, hi] = AGZ_RANGE[k], n = +raw;
      if (!/^\d+$/.test(raw) || !((n >= lo && n <= hi) || (k === 'rotate_idle_min' && n === 0))) {
        toast(k === 'rotate_runs' ? tr('Messages: a number from {0} to {1}', lo, hi) : tr('Pause: 0 or {0} to {1} minutes', lo, hi));
        el.value = rt[k] ?? ''; return;
      }
      v = n;
    }
    try {
      const r = await api('PATCH', base, {runtime: {[k]: v}});
      if (r?.runtime) a.runtime = r.runtime;
      savedTick(el.type === 'hidden' ? $(`[data-dpfor="${el.id}"]`, md) || el : el);
    } catch { if (el.type !== 'hidden') el.value = rt[k] ?? ''; /* api() said it */ }
  });
}
