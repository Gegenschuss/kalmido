// @ts-check
/* Kalmido web client: editing the custom field types of 2.156.0 B (#2069), loaded on demand (lazyload.js module cfkinds): the
   menus of a column cell (multiple choice, rating), the picker of a task link and the field dialog's part for currency and
   rating. What the values look like and the taps in the detail panel stay at start (render.js, "2.156.0 B"). */
const CFK_CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'SEK', 'NOK', 'DKK', 'PLN', 'CZK', 'HUF', 'JPY', 'CAD', 'AUD'];

// ---- the cell of a column (tablecells.js tcEdit)
function cfkTcEdit(cell, t, f, v, put) {
  if (f.type === 'multiselect') {
    const ids = new Set(cfk_ids(v));
    menu(cell, [{label: f.name, dis: true, cls: 'mhead'}, '-', ...(f.options?.options || []).map(o => ({label: o.name, swc: o.color || '', on: ids.has(o.id),
      fn: () => { const n = new Set(ids); n.has(o.id) ? n.delete(o.id) : n.add(o.id); put(cfk_msVal(f, n)); }})),
    ...(v != null ? ['-', {label: tr('Empty the field'), icon: 'x', fn: () => put(null)}] : [])]);
    return true;
  }
  if (f.type === 'rating') {
    menu(cell, [{label: f.name, dis: true, cls: 'mhead'}, '-', ...Array.from({length: cfk_max(f)}, (_, i) => ({label: tr('{0} of {1}', i + 1, cfk_max(f)), icon: 'star', on: +(v || 0) === i + 1, fn: () => put(String(i + 1))})),
      ...(v != null ? ['-', {label: tr('Empty the field'), icon: 'x', fn: () => put(null)}] : [])]);
    return true;
  }
  if (f.type === 'task') { cfkPick(t, f, put); return true; }
  return false;
}

// ---- choosing the linked task: the open tasks I can see (the same look as every task picker, .tpk)
function cfkPick(t, f, done) {
  const md = /** @type {any} */ (modal(`<h3>${esc(f.name)}</h3>
    <input id="cfk-q" placeholder="${esc(tr('Search open tasks'))}" autocomplete="off" style="width:100%;margin-top:.5rem" aria-label="${esc(tr('Search open tasks'))}">
    <div class="dplist tpk" id="cfk-list" role="listbox" aria-label="${esc(tr('Open tasks'))}"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button></div>`));
  md.classList.add('dpmodal');
  const draw = () => {
    const q = norm(/** @type {HTMLInputElement} */ ($('#cfk-q', md)).value || '');
    const arr = openTasks().filter(x => x.id > 0 && x.id !== t.id && !x.context && (!q || norm(x.title).includes(q)))
      .sort((a, b) => (b.list_id === t.list_id ? 1 : 0) - (a.list_id === t.list_id ? 1 : 0) || bySort(a, b)).slice(0, 60);
    $('#cfk-list', md).innerHTML = arr.length ? arr.map(x => `<button type="button" class="tpkrow" role="option" data-cfkp="${x.id}"><span class="tpkt">${esc(x.title)}</span><span class="tpkm">${esc(lname(listById(x.list_id)))}</span></button>`).join('')
      : `<div class="muted mhint">${tr('No matching open task.')}</div>`;
  };
  draw();
  md.addEventListener('input', e => { if (/** @type {any} */ (e.target).id === 'cfk-q') draw(); });
  md.addEventListener('click', e => {
    const b = /** @type {any} */ (e.target).closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.cfkp) { md.remove(); done(b.dataset.cfkp); }
  });
  setTimeout(() => { if (!isMobile()) /** @type {HTMLInputElement} */ ($('#cfk-q', md)).focus(); }, 50);
}

// ---- the "New field" dialog (projects.js fieldModal): the settings of currency and rating
function cfkModalExtra(x, type, f) {  // x = the dialog's part to fill
  x.innerHTML = cfk_extraHtml(type, f);
}
function cfk_extraHtml(type, f) {
  if (type === 'currency') {
    const cur = f?.options?.currency || 'EUR', list = CFK_CURRENCIES.includes(cur) ? CFK_CURRENCIES : [cur, ...CFK_CURRENCIES];
    return `<div class="row"><label for="fd-cur">${tr('Currency')}</label><select id="fd-cur">${list.map(c => `<option value="${c}" ${c === cur ? 'selected' : ''}>${c}</option>`).join('')}</select></div>`;
  }
  if (type === 'rating') {
    const mx = cfk_max(f || {options: {}});
    return `<div class="row"><label for="fd-rmax">${tr('Stars')}</label><select id="fd-rmax">${[3, 4, 5, 6, 7, 8, 9, 10].map(n => `<option value="${n}" ${n === mx ? 'selected' : ''}>${n}</option>`).join('')}</select></div>`;
  }
  if (type === 'task') return `<div class="shint keep">${tr('Links one other task. Everyone sees its title only if they may see that task.')}</div>`;
  return '';
}
