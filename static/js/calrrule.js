// @ts-check
// 2.155.0 C (#2075): an own repeat rule for an event ("every 2nd Tuesday", Mon + Wed + Fri). The event editor's Repeat list
// has a "Custom…" entry that opens this small dialog; the result is a plain RRULE body (without the end, the editor's own
// "Ends" row keeps that). Parts the form cannot show (BYMONTH, ...) are kept as they are.
const CRR_FREQS = ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'];
// the rule body -> the form's state; `start` (YYYY-MM-DD...) supplies the defaults (its day, weekday, n-th weekday)
function crr_parse(base, start) {
  const p = /** @type {Record<string, string>} */ ({});
  for (const x of String(base || '').replace(/^RRULE:/, '').split(';')) { const [k, v] = x.split('='); if (k) p[k] = v; }
  const d = pd(String(start || today()).slice(0, 10));
  const f = CRR_FREQS.includes(p.FREQ) ? p.FREQ : 'WEEKLY';
  const wd0 = RR_WD[d.getDay()], pos0 = Math.ceil(d.getDate() / 7) > 4 ? -1 : Math.ceil(d.getDate() / 7);
  const st = {f, n: Math.max(1, Math.min(99, +p.INTERVAL || 1)), days: new Set(/** @type {string[]} */ ([])), mode: 'day', md: d.getDate(), pos: pos0, wd: wd0, rest: /** @type {string[]} */ ([]), keep: false};
  const nth = crr_nthOf(p);
  if (f === 'WEEKLY' && p.BYDAY && !/\d/.test(p.BYDAY)) p.BYDAY.split(',').forEach(x => st.days.add(x));
  if (f === 'WEEKLY' && !st.days.size) st.days.add(wd0);
  if (f === 'MONTHLY') {
    if (nth) { st.mode = 'nth'; st.pos = nth.pos; st.wd = nth.wd; }
    else if (/^\d+$/.test(p.BYMONTHDAY || '')) st.md = Math.min(31, +p.BYMONTHDAY);
  }
  // what the form does not edit stays: for weekly / monthly BYDAY, BYMONTHDAY and BYSETPOS are rebuilt, otherwise they ride along
  const own = f === 'WEEKLY' ? ['BYDAY'] : f === 'MONTHLY' ? ['BYDAY', 'BYMONTHDAY', 'BYSETPOS'] : [];
  for (const [k, v] of Object.entries(p)) if (!['FREQ', 'INTERVAL', 'COUNT', 'UNTIL', ...own].includes(k)) st.rest.push(`${k}=${v}`);
  if (f === 'MONTHLY' && st.mode === 'day' && p.BYDAY) { st.keep = true; st.rest.push(`BYDAY=${p.BYDAY}`); if (p.BYSETPOS) st.rest.push(`BYSETPOS=${p.BYSETPOS}`); }  // e.g. last weekday: kept, not edited
  return st;
}
function crr_build(st) {
  const parts = [`FREQ=${st.f}`];
  if (st.n > 1) parts.push(`INTERVAL=${st.n}`);
  if (st.f === 'WEEKLY') parts.push(`BYDAY=${RR_WD.filter(x => st.days.has(x)).sort((a, b) => ((RR_WD.indexOf(a) + 6) % 7) - ((RR_WD.indexOf(b) + 6) % 7)).join(',')}`);
  if (st.f === 'MONTHLY' && !st.keep) parts.push(st.mode === 'nth' ? `BYDAY=${st.pos}${st.wd}` : `BYMONTHDAY=${st.md}`);
  return [...parts, ...st.rest].join(';');
}
const crr_ordWord = pos => pos < 0 ? tr('last|nth') : tr(CRR_ORD[pos - 1]);

function crr_html(st) {
  const plural = trn('day', 'days', st.n), units = [['DAILY', plural], ['WEEKLY', trn('week', 'weeks', st.n)], ['MONTHLY', trn('month', 'months', st.n)], ['YEARLY', trn('year', 'years', st.n)]];
  const wds = wdOrder().map(i => `<button type="button" class="${st.days.has(RR_WD[i]) ? 'on' : ''}" data-crrwd="${RR_WD[i]}" aria-pressed="${st.days.has(RR_WD[i])}" aria-label="${esc(WDL[i])}">${esc(WD[i])}</button>`).join('');
  const posOpts = [1, 2, 3, 4, -1].map(p => `<option value="${p}" ${st.pos === p ? 'selected' : ''}>${esc(crr_ordWord(p))}</option>`).join('');
  const wdOpts = wdOrder().map(i => `<option value="${RR_WD[i]}" ${st.wd === RR_WD[i] ? 'selected' : ''}>${esc(WDL[i])}</option>`).join('');
  return `<div class="lhdr"><h3>${tr('Custom repeat')}</h3><span class="spacer"></span><button class="iconbtn" data-crr="cancel" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="row crrrow"><label for="crr-n">${tr('Every|repeat')}</label><input type="number" id="crr-n" class="numin" min="1" max="99" inputmode="numeric" value="${st.n}" aria-label="${esc(tr('Interval'))}">
      <select id="crr-f" aria-label="${esc(tr('Unit'))}">${units.map(([v, n]) => `<option value="${v}" ${st.f === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
    ${st.f === 'WEEKLY' ? `<div class="row crrrow"><span class="rlab">${tr('On')}</span><div class="rrwd" role="group" aria-label="${esc(tr('On'))}" style="display:flex">${wds}</div></div>` : ''}
    ${st.f === 'MONTHLY' && !st.keep ? `<div class="row crrrow"><span class="rlab" id="crr-ml">${tr('On')}</span><div class="crrmon" role="radiogroup" aria-labelledby="crr-ml">
      <label class="crropt"><input type="radio" name="crr-m" value="day" ${st.mode === 'day' ? 'checked' : ''}> <span>${esc(tr('on day {0}', ''))}</span><input type="number" id="crr-md" class="numin" min="1" max="31" inputmode="numeric" value="${st.md}" aria-label="${esc(tr('on day {0}', ''))}"></label>
      <label class="crropt"><input type="radio" name="crr-m" value="nth" ${st.mode === 'nth' ? 'checked' : ''}> <span>${esc(tr('on the'))}</span><select id="crr-pos" aria-label="${esc(tr('on the'))}">${posOpts}</select><select id="crr-wd" aria-label="${esc(tr('Weekday'))}">${wdOpts}</select></label></div></div>` : ''}
    <div class="row crrprev"><span class="rlab">${tr('Repeat')}</span><span class="muted" id="crr-prev">${esc(repeatLabelBase(crr_build(st)))}</span></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-crr="cancel">${tr('Cancel')}</button><button class="btn pri" data-crr="ok">${tr('OK')}</button></div>`;
}

// opens the dialog on top of `parent` (which steps aside); done(rule) gets the rule body, nothing is called on cancel
function crr_open(parent, base, start, done) {
  const st = crr_parse(base, start);
  modalSub(parent, () => {
    const md = /** @type {any} */ (modal(crr_html(st)));  // bundle C: $() takes the dialog as its root
    md.classList.add('evmodal', 'crrmodal');
    const redraw = (focus) => { md.firstElementChild && (md.firstElementChild.innerHTML = crr_html(st)); if (focus) /** @type {HTMLElement|null} */ ($(focus, md))?.focus(); };
    const prev = () => { const el = $('#crr-prev', md); if (el) el.textContent = repeatLabelBase(crr_build(st)); };
    md.addEventListener('change', e => {
      const t = /** @type {HTMLInputElement} */ (e.target);
      if (t.id === 'crr-n' || t.id === 'crr-f') {
        st.n = Math.max(1, Math.min(99, +/** @type {HTMLInputElement} */ ($('#crr-n', md)).value || 1)); const f = /** @type {HTMLSelectElement} */ ($('#crr-f', md)).value;
        if (f !== st.f) { st.f = f; st.keep = false; if (f === 'WEEKLY' && !st.days.size) st.days.add(crr_parse('', start).wd); st.rest = st.rest.filter(x => !/^(BYDAY|BYMONTHDAY|BYSETPOS)=/.test(x)); }
        redraw(t.id === 'crr-n' ? '#crr-n' : '#crr-f'); return;
      }
      if (t.name === 'crr-m') st.mode = t.value;
      if (t.id === 'crr-md') { st.md = Math.max(1, Math.min(31, +t.value || 1)); st.mode = 'day'; const r = /** @type {HTMLInputElement|null} */ ($('input[name="crr-m"][value="day"]', md)); if (r) r.checked = true; }
      if (t.id === 'crr-pos' || t.id === 'crr-wd') { if (t.id === 'crr-pos') st.pos = +t.value; else st.wd = t.value; st.mode = 'nth'; const r = /** @type {HTMLInputElement|null} */ ($('input[name="crr-m"][value="nth"]', md)); if (r) r.checked = true; }
      prev();
    });
    md.addEventListener('click', e => {
      const b = /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (e.target).closest('[data-crrwd], [data-crr]')); if (!b) return;
      if (b.dataset.crrwd) {
        if (st.days.has(b.dataset.crrwd)) { if (st.days.size > 1) st.days.delete(b.dataset.crrwd); } else st.days.add(b.dataset.crrwd);
        redraw(`[data-crrwd="${b.dataset.crrwd}"]`); return;
      }
      if (b.dataset.crr === 'cancel') md.remove();
      else if (b.dataset.crr === 'ok') { const rule = crr_build(st); md.remove(); done(rule); }
    });
    return md;
  });
}

// the event editor's wiring: "Custom…" opens the dialog, picking it again for a custom rule edits it, cancel puts the old choice back
function crr_wire(md, st, getStart) {
  const sel = /** @type {HTMLSelectElement|null} */ ($('#ev-rep', md)); if (!sel) return;
  let last = sel.value;
  const label = r => repeatLabelBase(rrBase(r));
  const apply = rule => {
    st.rrule = rule;
    const k = evRepKey(rule, getStart());
    sel.querySelectorAll('option[value="custom"]').forEach(o => o.remove());
    if (k === 'custom') sel.insertAdjacentHTML('afterbegin', `<option value="custom">${esc(label(rule))}</option>`);
    sel.value = k; last = k;
    $('#ev-repend', md).hidden = !k;
    $('.crredit', md)?.toggleAttribute('hidden', k !== 'custom');
  };
  sel.insertAdjacentHTML('afterend', `<button type="button" class="iconbtn crredit" data-crredit title="${esc(tr('Edit repeat'))}" aria-label="${esc(tr('Edit repeat'))}" ${sel.value === 'custom' ? '' : 'hidden'}>${ic('edit', 's')}</button>`);
  md.addEventListener('change', e => {
    if (/** @type {HTMLElement} */ (e.target).id !== 'ev-rep') return;
    if (sel.value === '__custom') {
      const cur = last === 'custom' ? rrBase(st.rrule) : last ? evRepRule(last, getStart()) : '';
      crr_open(md, cur, getStart(), apply);
      sel.value = last;  // until OK
      return;
    }
    last = sel.value;
    $('.crredit', md)?.toggleAttribute('hidden', sel.value !== 'custom');
  });
  md.addEventListener('click', e => {
    if (!(/** @type {HTMLElement} */ (e.target).closest('[data-crredit]'))) return;
    crr_open(md, rrBase(st.rrule), getStart(), apply);
  });
}
