// @ts-check
// 2.124.0 A (#2115): the simple chart of a table - bars or a line from its columns, plain SVG (no chart library). The setting
// (kind, the column of the labels, 1-6 columns with numbers) is stored per table (PUT /api/sheets/<id>/chart, sheets/shchart.py);
// the values are the evaluated cells the view already has (formulas computed, filters of the view respected), so the chart
// follows every change live. One accent: the first series lilac, the others lilac shades and grey, lines also dashed so a
// series is never told by its colour alone; a legend from two series on. Tap (or hover) a column of the chart: its values.
// Without a setting nothing is drawn and the table looks exactly as before. Writing it is one Undo step.
// 2.578.0 (#3462): + stacked bars, pie and ring (donut): one accent and its shades again, every second part hatched so parts are
// never told by colour alone; a pie shows one column (the parts of its positive numbers, from the ninth on as "Other") with a
// legend of label, value and share.
const SHC = {hide: /** @type {Record<number, boolean>} */ ({}), tip: /** @type {string|null} */ (null)};
const SHC_MAX = 500;  // rows drawn at most (the note says so)
const SHC_H = 200, SHC_L = 52, SHC_B = 40, SHC_T = 18;  // the drawing's height and margins (SVG units = px)
const SHC_KINDS = ['bar', 'stacked', 'line', 'pie', 'donut'], SHC_ONE = ['pie', 'donut'], SHC_SLICES = 8;  // 2.578.0 (#3462)
function shc_hatched(k) { return (k % 2 === 1) !== (k >= 6); }  // 2.578.0 (#3462): every second part (and the 7th on) hatched
function shc_defs(sh) { return `<defs><pattern id="shc-h${sh.id}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line class="shc-hl" x1="0" y1="0" x2="0" y2="6"></line></pattern></defs>`; }
function shc_part(sh, k, d, extra) {  // one filled part (a stacked segment / a slice), hatched on top where shc_hatched says so
  const p = `<path class="shc-s${k % 6}${extra ? ' ' + extra : ''}" d="${d}"></path>`;
  return shc_hatched(k) ? p + `<path class="shc-hatch" fill="url(#shc-h${sh.id})" d="${d}"></path>` : p;
}

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
  if (SHC_ONE.includes(ch.type)) return shc_pieSvg(sh, ch, shc_slices(dt));  // 2.578.0 (#3462)
  const n = dt.pts.length, ns = dt.ys.length, bar = ch.type !== 'line', stack = ch.type === 'stacked';
  const view = document.getElementById('view'), avail = Math.min(1400, Math.max(280, (view?.clientWidth || 600) - 64));  // the width there is
  const gmin = bar && !stack ? Math.max(44, ns * 16 + 16) : 44, W = Math.max(avail, SHC_L + n * gmin + 12), gw = (W - SHC_L - 12) / Math.max(1, n);
  const ph = SHC_H - SHC_T - SHC_B;
  let lo = Infinity, hi = -Infinity;
  for (const p of dt.pts) {
    if (stack) { let up = 0, dn = 0; for (const v of p.vals) if (v) { if (v.v >= 0) up += v.v; else dn += v.v; } if (p.vals.some(v => v)) { lo = Math.min(lo, dn); hi = Math.max(hi, up); } continue; }  // 2.578.0 (#3462): the sums
    for (const v of p.vals) if (v) { lo = Math.min(lo, v.v); hi = Math.max(hi, v.v); }
  }
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
    if (stack) {  // 2.578.0 (#3462): the series on top of each other (negative numbers below zero), the sum above
      const bw = Math.min(40, gw - 12), x = x0 + (gw - bw) / 2;
      let up = 0, dn = 0;
      p.vals.forEach((v, k) => {
        if (!v || !v.v) return;
        const a = v.v >= 0 ? up : dn, b = a + v.v;
        if (v.v >= 0) up = b; else dn = b;
        const ya = Y(Math.max(a, b)), yb = Y(Math.min(a, b));
        out.push(shc_part(sh, k, `M${(x + 1).toFixed(1)} ${yb.toFixed(1)}V${ya.toFixed(1)}H${(x + bw - 1).toFixed(1)}V${yb.toFixed(1)}Z`));
      });
      if (lbl && (up || dn)) out.push(`<text class="shc-val" x="${(x + bw / 2).toFixed(1)}" y="${(Y(up) - 4).toFixed(1)}" text-anchor="middle">${esc(shc_num(up + dn))}</text>`);
    }
    if (bar && !stack) p.vals.forEach((v, k) => {
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
  return `<svg class="shc-svg" viewBox="0 0 ${W} ${SHC_H}" style="width:${W / 16}rem;height:${SHC_H / 16}rem" role="img" aria-label="${esc(tr('Chart of {0}', sh.title || tr('Table')))}">${stack ? shc_defs(sh) : ''}${out.join('')}</svg>`;
}
function shc_slices(dt) {  // 2.578.0 (#3462): the parts of a pie: the positive numbers of the first column, the ninth on as "Other"
  const all = dt.pts.map((p, i) => ({label: p.label, v: p.vals[0] ? p.vals[0].v : 0, d: p.vals[0] ? p.vals[0].d : '', i})).filter(x => x.v > 0);
  const total = all.reduce((a, x) => a + x.v, 0);
  if (all.length <= SHC_SLICES) return {parts: all, total};
  const rest = all.slice(SHC_SLICES - 1), v = rest.reduce((a, x) => a + x.v, 0);
  return {parts: [...all.slice(0, SHC_SLICES - 1), {label: tr('Other'), v, d: shc_num(v), i: -1}], total};
}
function shc_pct(v, total) { try { return new Intl.NumberFormat(LOCALE(), {style: 'percent', maximumFractionDigits: 1}).format(v / total); } catch (e) { return Math.round(v / total * 1000) / 10 + ' %'; } }
function shc_pieSvg(sh, ch, sl) {  // 2.578.0 (#3462): a pie / ring, the parts clockwise from twelve o'clock
  const R = 88, C = SHC_H / 2, ri = ch.type === 'donut' ? 52 : 0, out = [];
  let a = -Math.PI / 2;
  const pt = (r, t) => `${(C + r * Math.cos(t)).toFixed(2)} ${(C + r * Math.sin(t)).toFixed(2)}`;
  sl.parts.forEach((p, k) => {
    const t = p.v / sl.total * 2 * Math.PI, b = a + t, big = t > Math.PI ? 1 : 0;
    let d;
    if (sl.parts.length === 1) d = ri ? `M${pt(R, -Math.PI / 2)}A${R} ${R} 0 1 1 ${pt(R, Math.PI * 1.5 - 1e-4)}ZM${pt(ri, -Math.PI / 2)}A${ri} ${ri} 0 1 0 ${pt(ri, Math.PI * 1.5 - 1e-4)}Z`
      : `M${pt(R, -Math.PI / 2)}A${R} ${R} 0 1 1 ${pt(R, Math.PI * 1.5 - 1e-4)}Z`;
    else d = ri ? `M${pt(R, a)}A${R} ${R} 0 ${big} 1 ${pt(R, b)}L${pt(ri, b)}A${ri} ${ri} 0 ${big} 0 ${pt(ri, a)}Z` : `M${C} ${C}L${pt(R, a)}A${R} ${R} 0 ${big} 1 ${pt(R, b)}Z`;
    out.push(shc_part(sh, k, d, 'shc-sl'));
    if (p.i >= 0) out.push(`<path class="shc-slhit" data-shc-i="${p.i}" d="${d}"><title>${esc(p.label)}: ${esc(p.d)} (${esc(shc_pct(p.v, sl.total))})</title></path>`);
    a = b;
  });
  if (ri) out.push(`<text class="shc-val shc-total" x="${C}" y="${C}" text-anchor="middle" dy="0.32em">${esc(shc_num(sl.total))}</text>`);
  return `<svg class="shc-svg shc-pie" viewBox="0 0 ${SHC_H} ${SHC_H}" style="width:${SHC_H / 16}rem;height:${SHC_H / 16}rem" role="img" aria-label="${esc(tr('Chart of {0}', sh.title || tr('Table')))}">${shc_defs(sh)}${out.join('')}</svg>`;
}
function shc_pieLegend(sh, sl) {  // label, value and share of every part (the colour is never the only hint)
  return `<ul class="shc-leg shc-pleg">${sl.parts.map((p, k) => `<li${p.i >= 0 ? ` data-shc-i="${p.i}"` : ''}><i class="shc-key shc-s${k % 6}${shc_hatched(k) ? ' shc-kh' : ''}" aria-hidden="true"></i>${esc(p.label || '–')} <span class="muted">${esc(p.d)} · ${esc(shc_pct(p.v, sl.total))}</span></li>`).join('')}</ul>`;
}
function shc_html(sh) {  // the chart above the formula bar ('' without a setting or when hidden)
  if (!shc_on(sh) || SHC.hide[sh.id]) return '';
  const ch = sh.chart, dt = shc_data(sh, ch), one = SHC_ONE.includes(ch.type);
  if (one) dt.ys = dt.ys.slice(0, 1);  // 2.578.0 (#3462): a pie shows its first column
  const sl = one ? shc_slices(dt) : null;
  const legend = one ? `<span class="shc-one muted">${esc(dt.ys[0]?.title || '')}</span>` : dt.ys.length > 1 ? `<ul class="shc-leg">${dt.ys.map((c, k) => `<li><i class="shc-key shc-s${k}${ch.type === 'line' ? ' shc-kl' : ch.type === 'stacked' && shc_hatched(k) ? ' shc-kh' : ''}" aria-hidden="true"></i>${esc(c.title || c.letter || '')}</li>`).join('')}</ul>`
    : `<span class="shc-one muted">${esc(dt.ys[0]?.title || '')}</span>`;
  const body = !dt.ys.length ? `<p class="muted">${tr('The columns of the chart are gone. Choose new ones.')}</p>`
    : !dt.pts.length || (sl && !sl.parts.length) ? `<p class="muted">${tr('No numbers to show yet.')}</p>`
      : sl ? `<div class="shc-piebox">${shc_pieSvg(sh, ch, sl)}${shc_pieLegend(sh, sl)}</div>`
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
  if (SHC_ONE.includes(sh.chart.type)) dt.ys = dt.ys.slice(0, 1);
  tip.innerHTML = `<b>${esc(p.label)}</b>${dt.ys.map((c, k) => `<span><i class="shc-key shc-s${k}${sh.chart.type === 'line' ? ' shc-kl' : ''}" aria-hidden="true"></i>${esc(c.title || c.letter || '')}: ${esc(p.vals[k] ? p.vals[k].d : '–')}</span>`).join('')}`;
  tip.hidden = false;
  document.querySelectorAll('#shc-box [data-shc-i].on').forEach(x => x.classList.remove('on'));
  document.querySelectorAll(`#shc-box [data-shc-i="${i}"]`).forEach(x => x.classList.add('on'));  // 2.578.0 (#3462): + pie parts
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
    <fieldset class="shc-kind"><legend>${tr('Kind')}</legend>${SHC_KINDS.map(k => `<label class="chkl"><input type="radio" name="shc-t" value="${k}" ${(SHC_KINDS.includes(ch.type) ? ch.type : 'bar') === k ? 'checked' : ''}> ${(/** @type {Record<string, string>} */ ({bar: tr('Bars'), stacked: tr('Stacked bars'), line: tr('Line|chart'), pie: tr('Pie|chart'), donut: tr('Ring|chart')}))[k]}</label>`).join('')}</fieldset>
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
    const tv = (/** @type {HTMLInputElement|null} */ (md.querySelector('input[name="shc-t"]:checked')))?.value || 'bar';
    const t = SHC_KINDS.includes(tv) ? tv : 'bar';  // 2.578.0 (#3462): + stacked, pie, donut
    if (SHC_ONE.includes(t) && y.filter(v => v !== (xv ? +xv : null)).length > 1) { if (err) err.textContent = tr('A pie or ring chart shows one column with numbers'); return; }
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
  else { const h = /** @type {HTMLElement|null} */ (t.closest('[data-shc-i]')); if (h) shc_tipShow(+(h.dataset.shcI || 0)); }  // 2.578.0 (#3462): + pie parts and their legend
});
document.addEventListener('pointerover', e => {  // a mouse shows the values on hover too (touch: the tap above)
  if (e.pointerType !== 'mouse' || !(e.target instanceof Element)) return;
  const h = /** @type {HTMLElement|null} */ (e.target.closest('#shc-box [data-shc-i]')); if (h) shc_tipShow(+(h.dataset.shcI || 0));
});
SHV_HOOKS.menu.push(sh => sh.can_write
  ? [{label: shc_on(sh) ? tr('Edit chart…') : tr('Chart…'), icon: 'chart', fn: () => shc_dialog(sh)}, ...(shc_on(sh) && SHC.hide[sh.id] ? [{label: tr('Show chart'), icon: 'chart', fn: () => { delete SHC.hide[sh.id]; shc_patch(sh); }}] : [])]
  : shc_on(sh) && SHC.hide[sh.id] ? [{label: tr('Show chart'), icon: 'chart', fn: () => { delete SHC.hide[sh.id]; shc_patch(sh); }}] : []);
