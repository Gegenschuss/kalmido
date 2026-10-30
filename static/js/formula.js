/* Kalmido web client: calculating with custom fields (2.43.0, #1328). The formula field's dialog part, the sum row under
   the number columns of a list and the key figures (tiles) of a project page. Formulas are computed by the server; the
   client only shows them. */

// ---- the formula field in "New field" / "Edit field": the formula with field names ({Name}), a button per number field
// that inserts it, what empty fields count as, the unit
const FX_AGGS = [['sum', N_('Sum')], ['avg', N_('Average')], ['count', N_('Count')], ['min', N_('Minimum')], ['max', N_('Maximum')]];
const FX_NUM_TYPES = ['number', 'formula', 'currency', 'rating'];  // 2.156.0 B (#2069): what sums up / counts as a number
const fxNumFields = (lid, not) => fieldsAll(lid).filter(f => (FX_NUM_TYPES.includes(f.type) || f.type === 'checkbox') && f.id !== not);
// 2.298.0 A2 (#3186): the formula help folded into "Formula help" (no longer a kept hint)
function fxModalExtra(lid, f) {
  const o = f?.options || {}, fs = fxNumFields(lid, f?.id);
  return `<div class="row fxrow"><label for="fd-fx">${tr('Formula')}</label><textarea id="fd-fx" rows="2" maxlength="500" spellcheck="false" placeholder="${esc(tr('e.g. {Amount} - {Refunded}'))}">${esc(o.formula || '')}</textarea></div>
    <div class="fxins" role="group" aria-label="${esc(tr('Insert a field'))}">${fs.length ? fs.map(x => `<button type="button" class="btn sm" data-fxins="${esc(x.name)}">${esc(x.name)}</button>`).join('') : `<span class="muted">${esc(tr('Add a number field first.'))}</span>`}</div>
    <details class="shelp sdet fxhelp"><summary>${tr('Formula help')}</summary><div class="muted">${esc(tr('Allowed: + - * / ( ), numbers, field names in braces, comparisons (= <> < > <= >=) and the functions of tables:'))}
      <code>WENN/IF</code> <code>SUMME/SUM</code> <code>RUNDEN/ROUND</code> <code>MIN</code> <code>MAX</code> <code>MITTELWERT/AVERAGE</code> <code>ANZAHL/COUNT</code>.
      ${esc(tr('Separate the values with ; or , e.g. WENN({Hours} > 8; {Hours} * 1.5; {Hours}). Division by 0 shows as an error in the field.'))}</div></details>
    <div class="row"><label for="fd-fxe">${tr('Empty fields')}</label><select id="fd-fxe"><option value="zero">${tr('count as 0')}</option><option value="blank" ${o.empty === 'blank' ? 'selected' : ''}>${tr('leave the result empty')}</option></select></div>
    <div class="row"><label for="fd-unit">${tr('Unit')}</label><input id="fd-unit" value="${esc(o.unit || '')}" maxlength="12" placeholder="${tr('optional, e.g. € or h')}" style="max-width:8.75rem"></div>`;
}
function fxModalBody(md) {
  return {formula: $('#fd-fx', md).value.trim(), options: {unit: $('#fd-unit', md).value.trim(), empty: $('#fd-fxe', md).value}};
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-fxins]'); if (!b) return;
  const ta = b.closest('.modal')?.querySelector('#fd-fx'); if (!ta) return;
  const ins = '{' + b.dataset.fxins + '}', a = ta.selectionStart ?? ta.value.length, z = ta.selectionEnd ?? a;
  ta.value = ta.value.slice(0, a) + ins + ta.value.slice(z); ta.focus(); ta.setSelectionRange(a + ins.length, a + ins.length);
});
// the delete confirmation warns when formulas read the field (they stay empty then)
function fxUsedWarn(fid) {
  const by = (S.fields || []).filter(f => f.type === 'formula' && (f.options?.expr || '').includes(`{#${fid}}`)).map(f => f.name);
  return by.length ? ' ' + tr('Formulas that use it stay empty: {0}', by.join(', ')) : '';
}

// ---- the number format of a result: the person's language, at most 2 decimals, the unit after it
function fxFmt(v, unit) {
  if (v == null || !Number.isFinite(+v)) return '–';
  const s = (+v).toLocaleString(LOCALE(), {maximumFractionDigits: 2});
  return unit ? s + (unit === '%' ? ' %' : ' ' + unit) : s;
}
function fxAgg(a, xs, n) {  // xs = the numbers of the shown tasks with a value, n = how many tasks are shown
  if (a === 'count') return xs.length;
  if (!xs.length) return null;
  if (a === 'avg') return xs.reduce((s, x) => s + x, 0) / xs.length;
  if (a === 'min') return Math.min(...xs);
  if (a === 'max') return Math.max(...xs);
  return xs.reduce((s, x) => s + x, 0);
}

// ---- the sum row under a list's columns (wide layouts): number and formula columns over the shown tasks (filter,
// collapsed sections included). A click on a result picks the calculation; saved for the list (owner / list admins,
// for everyone, with undo), the others' choice stays on this device.
const fxSumCols = (l, lc) => lc.filter(k => k !== 'id').map(k => [k, k.startsWith('f:') ? fieldById(+k.slice(2)) : null]);
const fxSumAgg = (l, k) => (LS.get('fxsum.' + l.id) || {})[k] || (l.col_sums || {})[k] || 'sum';
// 2.410.0 (#3437): a budget field ("Budget h", the server's names in timetrack.py) counts once per branch, like the project
// header: a task whose subtasks carry budgets counts their sum, not its own value (which stays stored and is shown as a hint).
const FX_BUDGET_NAMES = ['budget h', 'budget (h)', 'budget hours', 'budget std', 'budget (std)', 'budget-stunden', 'budgetstunden'];
const fxIsBudget = f => !!f && f.type === 'number' && [...FX_BUDGET_NAMES, tr('Budget h').toLowerCase()].includes((f.name || '').trim().toLowerCase());
function fxOwnBudget(f, t) { const v = t.fields?.[f.id], x = v == null || v === '' ? NaN : Number(v); return Number.isFinite(x) && x > 0 ? x : null; }
function fxBranch(f, t, seen = new Set()) {  // the budget of a task's branch (null = none anywhere in it)
  if (seen.has(t.id)) return null;
  seen.add(t.id);
  let s = null;
  for (const k of children(t.id)) { const x = fxBranch(f, k, seen); if (x != null) s = (s || 0) + x; }
  return s != null ? s : fxOwnBudget(f, t);
}
function fxBranchSum(f, ts) {  // the shown tasks; a task under another shown task is counted with it
  const ids = new Set(ts.map(t => t.id)), under = t => { for (let p = taskById(t.parent_id), n = 0; p && n < 50; p = taskById(p.parent_id), n++) if (ids.has(p.id)) return true; return false; };
  return ts.filter(t => !under(t)).map(t => fxBranch(f, t)).filter(x => x != null);
}
function fxBudgetCell(f, t) {  // '' = the plain cell; else the subtasks' sum, grey, and the own value as a hint when it differs
  if (!fxIsBudget(f) || !children(t.id).length) return '';
  const own = fxOwnBudget(f, t), sub = children(t.id).map(k => fxBranch(f, k)).filter(x => x != null);
  if (!sub.length) return '';
  const s = sub.reduce((a, x) => a + x, 0), tip = tr('Sum of the subtasks') + (own != null && own !== s ? ' · ' + tr('own value {0}', fxFmt(own, f.options?.unit)) : '');
  return `<span class="fxbr" title="${esc(tip)}">${esc(fxFmt(s, f.options?.unit))}${own != null && own !== s ? `<small class="fxown">${esc(tr('own value {0}', fxFmt(own, f.options?.unit)))}</small>` : ''}</span>`;
}
function fxSumRow(l, lc, tasks) {
  if (!l || !lc || isMobile()) return '';
  const cs = fxSumCols(l, lc);
  if (!cs.some(([k, f]) => k === 'time' || f && FX_NUM_TYPES.includes(f.type))) return '';  // 2.380.0 A (#3424): the tracked-time column counts too
  const ts = tasks.filter(t => t.id && !t.context);
  return `<div class="fxsum" data-lid="${l.id}" role="group" aria-label="${esc(tr('Sum row'))}"><span class="spacer"><span class="fxsn">${esc(trn('{0} task', '{0} tasks', ts.length))}</span></span>${cs.map(([k, f], i) => {
    if (k === 'time') {  // 2.380.0 A (#3424): the sum of the tracked time of the shown tasks, as the cells read
      const sec = ts.reduce((n, t) => n + (t.id > 0 ? taskTime(t.id)[0] : 0), 0);
      return `<span class="lc ${lcCls(k)} ${lcOvf(i)}" data-k="time">${sec >= 60 ? `<span class="fxsb fxst" title="${esc(tr('Tracked time'))}"><i>${esc(tr('Sum'))}</i> ${esc(fmtDur(sec))}</span>` : ''}</span>`;
    }
    if (!f || !FX_NUM_TYPES.includes(f.type)) return `<span class="lc ${lcCls(k)} ${lcOvf(i)}" data-k="${esc(k)}"></span>`;
    const a = fxSumAgg(l, k), xs = fxIsBudget(f) ? fxBranchSum(f, ts) : ts.map(t => t.fields?.[f.id]).filter(v => v != null && v !== '').map(Number).filter(Number.isFinite);
    const v = fxAgg(a, xs, ts.length), an = tr((FX_AGGS.find(x => x[0] === a) || FX_AGGS[0])[1]);
    if (f.type === 'currency' && a !== 'count' && v != null) {  // 2.156.0 B (#2069): the sum in the field's currency
      const m = cfk_money(v, f.options?.currency);
      return `<span class="lc ${lcCls(k)} ${lcOvf(i)}" data-k="${esc(k)}"><button type="button" class="fxsb" data-fxsum="${esc(k)}" title="${esc(an + ': ' + f.name)}" aria-label="${esc(an + ' ' + f.name + ': ' + m)}" aria-haspopup="menu"><i>${esc(an)}</i> ${esc(m)}</button></span>`;
    }
    return `<span class="lc ${lcCls(k)} ${lcOvf(i)}" data-k="${esc(k)}"><button type="button" class="fxsb" data-fxsum="${esc(k)}" title="${esc(an + ': ' + f.name)}" aria-label="${esc(an + ' ' + f.name + ': ' + fxFmt(v, a === 'count' ? '' : f.options?.unit))}" aria-haspopup="menu"><i>${esc(an)}</i> ${esc(fxFmt(v, a === 'count' ? '' : f.options?.unit))}</button></span>`;
  }).join('')}</div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('.fxsum [data-fxsum]'); if (!b) return;
  const l = listById(+b.closest('.fxsum').dataset.lid), k = b.dataset.fxsum; if (!l) return;
  const cur = fxSumAgg(l, k), f = fieldById(+k.slice(2));
  const kp = canManage(l) && !l.archived && !l.is_inbox && f ? ['-', {label: tr('Key figure on the project page…'), icon: 'chart',
    fn: () => fxKpiModal(l.id, {title: f.name, agg: cur === 'avg' ? 'avg' : cur === 'count' ? 'count' : 'sum', field: f.id, state: 'all'})}] : [];
  menu(b, [...FX_AGGS.map(([a, n]) => ({label: tr(n), on: a === cur, fn: () => fxSumSet(l.id, k, a)})), ...kp]);
});
async function fxSumSet(lid, k, a, quiet) {
  const l = listById(lid); if (!l) return;
  if (!canManage(l)) { LS.set('fxsum.' + lid, {...(LS.get('fxsum.' + lid) || {}), [k]: a}); render(); return; }
  const prev = l.col_sums || {}, next = {...prev, [k]: a};
  if (LS.get('fxsum.' + lid)) LS.del('fxsum.' + lid);
  if (JSON.stringify(prev) === JSON.stringify(next)) return;
  await fxSumSave(lid, prev, next);
  const go = v => async () => { await fxSumSave(lid, null, v); return {}; };
  const e = histAdd({label: tr('Sum row of {0}', qn(lname(l))), undo: go(prev), redo: go(next), lids: [lid]});
  histToast(tr('Sum row saved for everyone in the project'), e);
}
async function fxSumSave(lid, _, v) {
  try { await optWrite(optSet(() => listById(lid), {col_sums: v}), () => api('PATCH', '/api/lists/' + lid, {col_sums: v})); } catch { /* api() said why */ }
  render();
}

// ---- key figures of a project page: tiles on top, computed by the server (GET /api/lists/<id>/kpis) over the tasks the
// person may see. Owner / list admins set them up (title, field, calculation, which tasks).
const FX_KPI_AGGS = [['sum', N_('Sum')], ['count', N_('Count')], ['avg', N_('Average')], ['ratio', N_('Ratio A ÷ B in %')]];
const FX_KPI_STATES = [['all', N_('All tasks')], ['open', N_('Open tasks')], ['done', N_('Completed tasks')]];
async function fxKpiLoad(lid, force) {
  const K = S.fxK || (S.fxK = {}), d = K[lid] || (K[lid] = {});
  if (d.busy || (!force && d.data && d.v === S.v)) return;
  d.busy = true;
  try { d.data = (await api('GET', `/api/lists/${lid}/kpis`)).data; d.v = S.v; d.err = ''; }
  catch (e) { d.err = e?.message || 'offline'; d.v = S.v; }
  finally { d.busy = false; }
  if (routeList()?.id === lid) viewSafeRender();
}
function fxKpiPart(l) {  // the block "Key figures" of the project page (POV_BLOCKS 'kpis'); undefined = none set up yet
  const has = (l.kpis || []).length, can = canManage(l) && !l.archived;
  if (!has) return undefined;  // set up from the sum row of the list ("Key figure on the project page…")
  const d = S.fxK?.[l.id];
  if (has && (!d || (!d.busy && d.v !== S.v))) setTimeout(() => fxKpiLoad(l.id), 0);
  const btn = can ? `<button type="button" class="btn sm" data-fxkpi-edit="${l.id}">${ic('edit', 's')}<span>${has ? tr('Edit') : tr('Add key figure')}</span></button>` : '';
  const tiles = has ? `<div class="fxkpis">${(d?.data || l.kpis.map(k => ({...k, value: undefined}))).map(k =>
    `<div class="fxk"><span class="fxkt">${esc(k.title)}</span><b class="fxkv">${k.value === undefined ? '…' : esc(fxFmt(k.value, k.agg === 'count' ? '' : k.unit))}</b></div>`).join('')}</div>` : '';
  return x => povSec('kpis', tr('Key figures'), tiles, btn + x, has ? '' : tr('Totals of your number fields at a glance.'));
}
document.addEventListener('click', e => { const b = e.target.closest?.('[data-fxkpi-edit]'); if (b) { e.preventDefault(); fxKpiModal(+b.dataset.fxkpiEdit); } });
function fxKpiModal(lid, add) {  // add = a new tile to start with (from the sum row)
  const l = listById(lid); if (!l || !canManage(l)) return;
  const fs = fieldsAll(lid), nums = fs.filter(f => FX_NUM_TYPES.includes(f.type)), conds = fs.filter(f => f.type === 'select' || f.type === 'checkbox');
  let ks = JSON.parse(JSON.stringify(l.kpis || []));
  if (add) ks.push(add);
  if (!ks.length) ks.push({title: '', agg: 'sum', field: nums[0]?.id ?? null, state: 'all'});
  const opt = (v, cur, n) => `<option value="${esc(v)}" ${String(cur ?? '') === String(v) ? 'selected' : ''}>${esc(n)}</option>`;
  const fsel = (i, key, cur) => `<select data-fxk="${i}" data-key="${key}" aria-label="${esc(key === 'field2' ? tr('Divided by') : tr('Field'))}">${nums.map(f => opt(f.id, cur, f.name)).join('')}</select>`;
  const condOpts = k => { const f = conds.find(x => x.id === +k.cond_field); return !f ? '' : f.type === 'checkbox' ? opt('1', k.cond_value, tr('ticked')) + opt('', k.cond_value, tr('not ticked')) : (f.options?.options || []).map(o => opt(o.id, k.cond_value, o.name)).join(''); };
  const row = (k, i) => `<li class="fxkr" data-i="${i}">
      <input data-fxk="${i}" data-key="title" value="${esc(k.title || '')}" maxlength="60" placeholder="${esc(tr('Title'))}" aria-label="${esc(tr('Title'))}">
      <select data-fxk="${i}" data-key="agg" aria-label="${esc(tr('Calculation'))}">${FX_KPI_AGGS.map(([a, n]) => opt(a, k.agg, tr(n))).join('')}</select>
      ${k.agg === 'count' ? '' : fsel(i, 'field', k.field)}${k.agg === 'ratio' ? `<span class="muted">÷</span>${fsel(i, 'field2', k.field2)}` : ''}
      <select data-fxk="${i}" data-key="state" aria-label="${esc(tr('Which tasks'))}">${FX_KPI_STATES.map(([a, n]) => opt(a, k.state || 'all', tr(n))).join('')}</select>
      <select data-fxk="${i}" data-key="cond_field" aria-label="${esc(tr('Condition'))}">${opt('', k.cond_field, tr('without condition'))}${conds.map(f => opt(f.id, k.cond_field, f.name + ' =')).join('')}</select>
      ${k.cond_field ? `<select data-fxk="${i}" data-key="cond_value" aria-label="${esc(tr('Value'))}">${condOpts(k)}</select>` : ''}
      <button type="button" class="iconbtn" data-fxkrm="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></li>`;
  const md = modal(`<h3>${ic('chart', 's')}${tr('Key figures')}</h3>
    <p class="muted">${esc(tr('Tiles on top of the project page, the same for everyone who sees the project. Computed over the tasks each person may see.'))}</p>
    ${nums.length ? '' : `<p class="rohint">${esc(tr('Add a number field first.'))}</p>`}
    <ul class="fxkls"></ul><button type="button" class="btn sm" data-m="fxk-add">${ic('plus', 's')} ${tr('Key figure')}</button>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('fxkmd');
  const draw = () => { $('.fxkls', md).innerHTML = ks.map(row).join(''); };
  draw();
  md.addEventListener('change', e => {
    const i = e.target.dataset.fxk; if (i === undefined) return;
    const k = ks[+i], key = e.target.dataset.key, v = e.target.value;
    k[key] = ['field', 'field2', 'cond_field'].includes(key) ? (v ? +v : null) : v;
    if (key === 'agg' && v !== 'count' && k.field == null) k.field = nums[0]?.id ?? null;
    if (key === 'agg' && v === 'ratio' && k.field2 == null) k.field2 = nums[1]?.id ?? nums[0]?.id ?? null;
    if (key === 'cond_field') { const f = conds.find(x => x.id === +v); k.cond_value = f?.type === 'select' ? f.options?.options?.[0]?.id || '' : '1'; }
    if (['agg', 'cond_field'].includes(key)) draw();
  });
  md.addEventListener('input', e => { if (e.target.dataset.key === 'title') ks[+e.target.dataset.fxk].title = e.target.value; });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.fxkrm !== undefined) { ks.splice(+b.dataset.fxkrm, 1); draw(); return; }
    const a = b.dataset.m;
    if (a === 'close') { md.remove(); return; }
    if (a === 'fxk-add') { ks.push({title: '', agg: 'sum', field: nums[0]?.id ?? null, state: 'all'}); draw(); $$('.fxkr input', md).pop()?.focus(); return; }
    if (a === 'save') {
      const prev = l.kpis || [], next = ks.map(k => ({...k, field: k.agg === 'count' ? null : k.field, field2: k.agg === 'ratio' ? k.field2 : undefined}));
      if (!await fxKpiSave(lid, next)) return;
      md.remove();
      const go = v => async () => { await fxKpiSave(lid, v); return {}; };
      histToast(tr('Key figures saved'), histAdd({label: tr('Key figures of {0}', qn(lname(l))), undo: go(prev), redo: go(next), lids: [lid]}));
    }
  });
}
// 2.46.2 (#1659): the key figures show at once (optimistic, an error puts the old ones back), their values follow behind
async function fxKpiSave(lid, v) {
  try { await optWrite(optSet(() => listById(lid), {kpis: v}), async () => { const r = await api('PATCH', '/api/lists/' + lid, {kpis: v}); if (r?.kpis) Object.assign(listById(lid) || {}, {kpis: r.kpis}); }); }
  catch { return false; }
  fxKpiLoad(lid, true).then(() => render(), () => {});
  return true;
}
