// @ts-check
// 2.124.0 A (#2115): the simple chart of a table - bars or a line from its columns, plain SVG (no chart library). The setting
// (kind, the column of the labels, 1-6 columns with numbers) is stored per table (PUT /api/sheets/<id>/chart, sheets/shchart.py);
// the values are the evaluated cells the view already has (formulas computed, filters of the view respected), so the chart
// follows every change live. One accent: the first series lilac, the others lilac shades and grey, lines also dashed so a
// series is never told by its colour alone; a legend from two series on. Tap (or hover) a column of the chart: its values.
// Without a setting nothing is drawn and the table looks exactly as before. Writing it is one Undo step.
const SHC = {hide: /** @type {Record<number, boolean>} */ ({}), tip: /** @type {string|null} */ (null)};
const SHC_MAX = 500;  // rows drawn at most (the note says so)
const SHC_H = 200, SHC_L = 52, SHC_B = 40, SHC_T = 18;  // the drawing's height and margins (SVG units = px)

function shc_on(sh) { return !!(sh && sh.chart && Array.isArray(sh.chart.y) && sh.chart.y.length); }
function shc_data(sh, ch) {  // {ys: [columns], pts: [{label, vals: [{v, d} | null]}], more}
  const rows = typeof shvVisRows === 'function' ? shvVisRows(sh) : sh.rows || [];
  const ys = ch.y.map(id => sh._col.get(id)).filter(Boolean), xc = ch.x != null ? sh._col.get(ch.x) : null;
  const pts = [];
  let more = false;
  for (const r of rows) {
    const vals = ys.map(c => {
      const x = sh._at.get(r.id + ':' + c.id);
      return x && !x.error && typeof x.value === 'number' ? {v: c.kind === 'percent' ? x.value * 100 : x.value, d: String(x.display ?? x.value)} : null;
    });
    const lc = xc ? sh._at.get(r.id + ':' + xc.id) : null;
    const label = xc ? (lc && !lc.error ? String(lc.display ?? lc.value ?? '') : '') : String(sh._rowNo.get(r.id) || '');
    if (vals.every(v => !v) && !(xc && label)) continue;  // the empty rows of a table stay out
    if (pts.length >= SHC_MAX) { more = true; break; }
    pts.push({label, vals});
  }
  return {ys, pts, more};
}
function shc_nice(lo, hi) {  // the axis: [min, max, step] with round steps, 0 always inside
  lo = Math.min(0, lo); hi = Math.max(0, hi);
  if (lo === hi) hi = 1;
  const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step, step];
}
function shc_num(v) {
  try { return new Intl.NumberFormat(LOCALE(), {notation: 'compact', maximumFractionDigits: 1}).format(v); } catch (e) { return String(Math.round(v * 10) / 10); }
}
function shc_cut(t, n) { return t.length > n ? t.slice(0, n - 1) + '…' : t; }
function shc_svg(sh, ch, dt) {
  const n = dt.pts.length, ns = dt.ys.length, bar = ch.type !== 'line';
  const view = document.getElementById('view'), avail = Math.min(1400, Math.max(280, (view?.clientWidth || 600) - 64));  // the width there is
  const gmin = bar ? Math.max(44, ns * 16 + 16) : 44, W = Math.max(avail, SHC_L + n * gmin + 12), gw = (W - SHC_L - 12) / Math.max(1, n);
  const ph = SHC_H - SHC_T - SHC_B;
  let lo = Infinity, hi = -Infinity;
  for (const p of dt.pts) for (const v of p.vals) if (v) { lo = Math.min(lo, v.v); hi = Math.max(hi, v.v); }
  if (lo === Infinity) { lo = 0; hi = 1; }
  const [y0, y1, step] = shc_nice(lo, hi), Y = v => SHC_T + ph - (v - y0) / (y1 - y0) * ph;
  const out = [];
  for (let v = y0; v <= y1 + step / 2; v += step) {  // recessive grid + the axis labels
    const y = Y(v).toFixed(1);
    out.push(`<line class="shc-grid${Math.abs(v) < step / 1e6 ? ' shc-zero' : ''}" x1="${SHC_L}" x2="${W - 6}" y1="${y}" y2="${y}"></line><text class="shc-ax" x="${SHC_L - 6}" y="${y}" text-anchor="end" dy="0.32em">${esc(shc_num(v))}</text>`);
  }
  const every = Math.max(1, Math.ceil(64 / gw)), chars = Math.max(4, Math.floor(gw * every / 7));  // x labels that do not collide
  const lbl = n * ns <= 24;  // a value on each bar only while there are few
  dt.pts.forEach((p, i) => {
    const x0 = SHC_L + i * gw;
    if (i % every === 0) out.push(`<text class="shc-ax" x="${(x0 + gw / 2).toFixed(1)}" y="${SHC_H - SHC_B + 16}" text-anchor="middle">${esc(shc_cut(p.label, chars))}</text>`);
    if (bar) p.vals.forEach((v, k) => {
      if (!v) return;
      const bw = Math.min(32, (gw - 12) / ns), x = x0 + (gw - bw * ns) / 2 + k * bw, ya = Y(Math.max(0, v.v)), yb = Y(Math.min(0, v.v)), h = Math.max(1, yb - ya);
      const r = Math.min(4, (bw - 2) / 2, h);
      out.push(v.v >= 0
        ? `<path class="shc-s${k}" d="M${x + 1} ${yb}V${ya + r}q0 ${-r} ${r} ${-r}H${x + bw - 1 - r}q${r} 0 ${r} ${r}V${yb}Z"></path>`
        : `<path class="shc-s${k}" d="M${x + 1} ${ya}V${yb - r}q0 ${r} ${r} ${r}H${x + bw - 1 - r}q${r} 0 ${r} ${-r}V${ya}Z"></path>`);
      if (lbl) out.push(`<text class="shc-val" x="${(x + bw / 2).toFixed(1)}" y="${(v.v >= 0 ? ya - 4 : yb + 11).toFixed(1)}" text-anchor="middle">${esc(shc_num(v.v))}</text>`);
    });
  });
  if (!bar) dt.ys.forEach((c, k) => {  // a line per series (gaps where a row has no number), markers on few points
    let d = '', pen = false;
    dt.pts.forEach((p, i) => { const v = p.vals[k]; if (!v) { pen = false; return; } d += `${pen ? 'L' : 'M'}${(SHC_L + i * gw + gw / 2).toFixed(1)} ${Y(v.v).toFixed(1)}`; pen = true; });
    out.push(`<path class="shc-ln shc-s${k}" d="${d}"></path>`);
    if (n <= 40) dt.pts.forEach((p, i) => { const v = p.vals[k]; if (v) out.push(`<circle class="shc-dot shc-s${k}" cx="${(SHC_L + i * gw + gw / 2).toFixed(1)}" cy="${Y(v.v).toFixed(1)}" r="4"></circle>`); });
    const li = dt.pts.map(p => p.vals[k]).map((v, i) => v ? i : -1).filter(i => i >= 0).pop();
    if (li != null && ns <= 4) out.push(`<text class="shc-val" x="${(SHC_L + li * gw + gw / 2).toFixed(1)}" y="${(Y(dt.pts[li].vals[k].v) - 9).toFixed(1)}" text-anchor="middle">${esc(shc_num(dt.pts[li].vals[k].v))}</text>`);
  });
  dt.pts.forEach((p, i) => out.push(`<rect class="shc-hit" data-shc-i="${i}" x="${SHC_L + i * gw}" y="${SHC_T}" width="${gw}" height="${ph}"><title>${esc(p.label)}</title></rect>`));
  return `<svg class="shc-svg" viewBox="0 0 ${W} ${SHC_H}" style="width:${W / 16}rem;height:${SHC_H / 16}rem" role="img" aria-label="${esc(tr('Chart of {0}', sh.title || tr('Table')))}">${out.join('')}</svg>`;
}
function shc_html(sh) {  // the chart above the formula bar ('' without a setting or when hidden)
  if (!shc_on(sh) || SHC.hide[sh.id]) return '';
  const ch = sh.chart, dt = shc_data(sh, ch);
  const legend = dt.ys.length > 1 ? `<ul class="shc-leg">${dt.ys.map((c, k) => `<li><i class="shc-key shc-s${k}${ch.type === 'line' ? ' shc-kl' : ''}" aria-hidden="true"></i>${esc(c.title || c.letter || '')}</li>`).join('')}</ul>`
    : `<span class="shc-one muted">${esc(dt.ys[0]?.title || '')}</span>`;
  const body = !dt.ys.length ? `<p class="muted">${tr('The columns of the chart are gone. Choose new ones.')}</p>`
    : !dt.pts.length ? `<p class="muted">${tr('No numbers to show yet.')}</p>`
      : `<div class="shc-scroll">${shc_svg(sh, ch, dt)}</div>${dt.more ? `<p class="muted shc-note">${tr('The first {0} rows are shown.', SHC_MAX)}</p>` : ''}`;
  return `<section class="shc" id="shc-box" aria-label="${esc(tr('Chart'))}"><div class="shc-head">${ic('chart', 's')}${legend}<span class="spacer"></span>
    ${sh.can_write ? `<button type="button" class="iconbtn" data-shc="edit" title="${esc(tr('Edit chart…'))}" aria-label="${esc(tr('Edit chart…'))}">${ic('edit', 's')}</button>` : ''}
    <button type="button" class="iconbtn" data-shc="hide" title="${esc(tr('Hide chart'))}" aria-label="${esc(tr('Hide chart'))}">${ic('x', 's')}</button></div>
    ${body}<div class="shc-tip" id="shc-tip" role="status" aria-live="polite" hidden></div></section>`;
}
function shc_patch(sh) {  // after a write merged into the open sheet: redraw the chart only when it changed
  const box = document.getElementById('shc-box'), html = shc_html(sh);
  if (!box) { if (html) { const bar = document.querySelector('.shvsheet .shvbar'); if (bar) bar.insertAdjacentHTML('beforebegin', html); } return; }
  if (!html) { box.remove(); return; }
  const t = document.createElement('template'); t.innerHTML = html.trim();
  const nb = t.content.firstElementChild;
  if (nb && nb.outerHTML !== box.outerHTML) box.replaceWith(nb);
}
function shc_tipShow(i) {  // the values of one column of the chart (tap / hover)
  const sh = SHV.sh, tip = document.getElementById('shc-tip'); if (!shc_on(sh) || !tip) return;
  const dt = shc_data(sh, sh.chart), p = dt.pts[i]; if (!p) { tip.hidden = true; return; }
  tip.innerHTML = `<b>${esc(p.label)}</b>${dt.ys.map((c, k) => `<span><i class="shc-key shc-s${k}${sh.chart.type === 'line' ? ' shc-kl' : ''}" aria-hidden="true"></i>${esc(c.title || c.letter || '')}: ${esc(p.vals[k] ? p.vals[k].d : '–')}</span>`).join('')}`;
  tip.hidden = false;
  document.querySelectorAll('#shc-box .shc-hit.on').forEach(x => x.classList.remove('on'));
  document.querySelector(`#shc-box .shc-hit[data-shc-i="${i}"]`)?.classList.add('on');
}

async function shc_save(sh, chart, label) {  // one Undo step (the old setting back)
  const id = sh.id, old = sh.chart || null;
  const set = async v => { const r = await rawFetch('PUT', `/api/sheets/${id}/chart`, {chart: v}); if (SHV.sh?.id === id) { SHV.sh.chart = r.chart || null; SHV.sh.rev = r.rev; delete SHC.hide[id]; shc_patch(SHV.sh); } };
  try { await set(chart); } catch (e) { toast(e.message); return; }
  histToast(label, histAdd({label, ids: [], snaps: [], lids: [], undo: async () => { await set(old); return {skipped: []}; }, redo: async () => { await set(chart); return {skipped: []}; }}));
}
function shc_dialog(sh) {  // kind, the labels' column, the columns with numbers
  if (!sh?.can_write) return;
  const ch = sh.chart || {type: 'bar', x: null, y: []}, cols = sh.columns || [];
  const num = c => ['number', 'currency', 'percent'].includes(c.kind);
  const ys = ch.y.length ? ch.y : cols.filter(num).slice(0, 1).map(c => c.id);
  const xs = ch.y.length ? ch.x : (cols.find(c => !num(c)) || {id: null}).id;
  const md = modal(`<h3>${tr('Chart')}</h3>
    <fieldset class="shc-kind"><legend>${tr('Kind')}</legend><label class="chkl"><input type="radio" name="shc-t" value="bar" ${ch.type !== 'line' ? 'checked' : ''}> ${tr('Bars')}</label><label class="chkl"><input type="radio" name="shc-t" value="line" ${ch.type === 'line' ? 'checked' : ''}> ${tr('Line|chart')}</label></fieldset>
    <div class="row"><label for="shc-x">${tr('Labels from')}</label><select id="shc-x"><option value="">${tr('Row numbers')}</option>${cols.map(c => `<option value="${c.id}" ${xs === c.id ? 'selected' : ''}>${esc(c.title || c.letter || '')}</option>`).join('')}</select></div>
    <fieldset class="shc-ys"><legend>${tr('Numbers from (up to 6 columns)')}</legend>${cols.map(c => `<label class="chkl"><input type="checkbox" value="${c.id}" ${ys.includes(c.id) ? 'checked' : ''}> ${esc(c.title || c.letter || '')}${num(c) ? '' : ` <small class="muted">${tr('Text')}</small>`}</label>`).join('')}</fieldset>
    <p class="muted mhint" id="shc-err" role="alert"></p>
    <div class="foot">${sh.chart ? `<button type="button" class="btn" data-m="rm">${ic('trash', 's')}${tr('Remove chart')}</button>` : ''}<span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target instanceof Element ? /** @type {HTMLElement|null} */ (e.target.closest('button[data-m]')) : null; if (!b) return;
    const a = b.dataset.m;
    if (a === 'close') { md.remove(); return; }
    if (a === 'rm') { md.remove(); await shc_save(sh, null, tr('Chart removed')); return; }
    if (a !== 'save') return;
    const y = [...md.querySelectorAll('.shc-ys input:checked')].map(i => +(/** @type {HTMLInputElement} */ (i)).value);
    const err = md.querySelector('#shc-err');
    if (!y.length || y.length > 6) { if (err) err.textContent = tr('Choose one to {0} columns with numbers', 6); return; }
    const xv = (/** @type {HTMLSelectElement|null} */ (md.querySelector('#shc-x')))?.value || '';
    const t = (/** @type {HTMLInputElement|null} */ (md.querySelector('input[name="shc-t"]:checked')))?.value === 'line' ? 'line' : 'bar';
    const x = xv ? +xv : null;
    md.remove();
    await shc_save(sh, {type: t, x, y: y.filter(v => v !== x)}, sh.chart ? tr('Chart changed') : tr('Chart added'));
  });
}

document.addEventListener('click', e => {
  const t = e.target instanceof Element ? e.target : null; if (!t || !t.closest('#shc-box')) return;
  const b = /** @type {HTMLElement|null} */ (t.closest('[data-shc]')), sh = SHV.sh; if (!sh) return;
  if (b?.dataset.shc === 'edit') shc_dialog(sh);
  else if (b?.dataset.shc === 'hide') { SHC.hide[sh.id] = true; document.getElementById('shc-box')?.remove(); }
  else { const h = /** @type {HTMLElement|null} */ (t.closest('.shc-hit')); if (h) shc_tipShow(+(h.dataset.shcI || 0)); }
});
document.addEventListener('pointerover', e => {  // a mouse shows the values on hover too (touch: the tap above)
  if (e.pointerType !== 'mouse' || !(e.target instanceof Element)) return;
  const h = /** @type {HTMLElement|null} */ (e.target.closest('#shc-box .shc-hit')); if (h) shc_tipShow(+(h.dataset.shcI || 0));
});
SHV_HOOKS.menu.push(sh => sh.can_write
  ? [{label: shc_on(sh) ? tr('Edit chart…') : tr('Chart…'), icon: 'chart', fn: () => shc_dialog(sh)}, ...(shc_on(sh) && SHC.hide[sh.id] ? [{label: tr('Show chart'), icon: 'chart', fn: () => { delete SHC.hide[sh.id]; shc_patch(sh); }}] : [])]
  : shc_on(sh) && SHC.hide[sh.id] ? [{label: tr('Show chart'), icon: 'chart', fn: () => { delete SHC.hide[sh.id]; shc_patch(sh); }}] : []);
