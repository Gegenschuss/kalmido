// @ts-check
// 2.124.0 E (#2116): several sheets in one table, loaded with the tables (lazyload.js). The sheet bar under the grid (like a
// spreadsheet): the sheets as tabs (tap = open it, tap on the open one = its menu: rename, duplicate, move, delete; drag to
// move on a computer), "+" = a new sheet after the open one. One sheet: only a quiet "+" (who may change the table), the view
// stays as before. Every change is one Undo step; a deleted sheet goes to the trash and Undo brings it back. Each sheet is
// a sheet of its own on the server (GET /api/sheets/<id> with its id): the bar opens it by its route #sheets/<id>.
const shbUrl = (bid, tid, x) => `/api/sheets/${bid}/tabs${tid ? '/' + tid : ''}${x ? '/' + x : ''}`;
const shbBid = sh => sh?.book_id || sh?.id;
const shbOpen = id => { if (S.route.mod === 'sheets' && S.route.sh === id) return; location.replace('#sheets/' + id); };

function shb_barHtml(sh) {
  const tabs = sh.tabs || [], w = sh.can_write;
  if (tabs.length < 2 && !w) return '';
  const add = w ? `<button type="button" class="shbadd iconbtn" data-shb="add" title="${esc(tr('Add sheet'))}" aria-label="${esc(tr('Add sheet'))}">${ic('plus', 's')}</button>` : '';
  if (tabs.length < 2) return `<div class="shbbar one">${add}</div>`;
  return `<div class="shbbar"><div class="shbtabs" role="tablist" aria-label="${esc(tr('Sheets'))}">${tabs.map(t => {
    const on = t.id === sh.id;
    return `<button type="button" role="tab" class="shbtab${on ? ' on' : ''}" aria-selected="${on}" ${on ? 'aria-haspopup="menu"' : ''} data-shb="tab" data-id="${t.id}" ${w ? 'draggable="true"' : ''} title="${esc(on && w ? tr('Sheet menu') : t.name)}">${esc(t.name)}${on && w ? ic('down', 's') : ''}</button>`;
  }).join('')}</div>${add}</div>`;
}

async function shbReq(m, url, b) { return await rawFetch(m, url, b); }
async function shbAfter(go) {  // reload the open sheet (its bar) and the overview (the number of sheets)
  for (const d of Object.values(SHV.idx)) d.v = -1;
  if (go && go !== SHV.sh?.id) { shbOpen(go); return; }
  if (SHV.sh) await shvLoad(SHV.sh.id, true);
}
const shbTabs = () => SHV.sh?.tabs || [];
const shbName = id => shbTabs().find(t => t.id === id)?.name || '';

async function shbAdd(sh, copy) {
  const bid = shbBid(sh), from = sh.id;
  let r; try { r = await shbReq('POST', shbUrl(bid), {after_id: sh.id, ...(copy ? {copy_of: sh.id, name: tr('{0} (copy)', shbName(sh.id))} : {})}); } catch (e) { toast(e.message); return; }
  const tid = r.tab.id, name = r.tab.name;
  await shbAfter(tid);
  const e = histAdd({label: tr('Created {0}', qn(name)), ids: [], snaps: [], lids: [],
    undo: async () => { await shbReq('DELETE', shbUrl(bid, tid)); await shbAfter(from); return {skipped: []}; },
    redo: async () => { await shbReq('POST', shbUrl(bid, tid, 'restore')); await shbAfter(tid); return {skipped: []}; }});
  histToast(tr('Sheet {0} created', qn(name)), e);
}
async function shbRename(sh, tid) {
  const bid = shbBid(sh), cur = shbName(tid);
  const t = await askPrompt(tr('Rename sheet'), cur, {input: {max: 100}, ok: tr('Rename')});
  if (t == null || !t.trim() || t.trim() === cur) return;
  const set = async v => { await shbReq('PATCH', shbUrl(bid, tid), {name: v}); await shbAfter(); };
  try { await set(t.trim()); } catch (e) { toast(e.message); return; }
  const e = histAdd({label: tr('Renamed {0}', qn(t.trim())), ids: [], snaps: [], lids: [], undo: async () => { await set(cur); return {skipped: []}; }, redo: async () => { await set(t.trim()); return {skipped: []}; }});
  histToast(tr('Renamed'), e);
}
async function shbMove(sh, tid, to) {
  const bid = shbBid(sh), was = shbTabs().findIndex(t => t.id === tid);
  if (was < 0 || to < 0 || to >= shbTabs().length || to === was) return;
  const set = async p => { await shbReq('PATCH', shbUrl(bid, tid), {pos: p}); await shbAfter(); };
  try { await set(to); } catch (e) { toast(e.message); return; }
  const e = histAdd({label: tr('Move {0}', qn(shbName(tid))), ids: [], snaps: [], lids: [], undo: async () => { await set(was); return {skipped: []}; }, redo: async () => { await set(to); return {skipped: []}; }});
  histToast(tr('Moved'), e);
}
async function shbDelete(sh, tid) {
  const bid = shbBid(sh), tabs = shbTabs(), i = tabs.findIndex(t => t.id === tid), name = shbName(tid);
  const next = tabs[i + 1] || tabs[i - 1];
  try { await shbReq('DELETE', shbUrl(bid, tid)); } catch (e) { toast(e.message); return; }
  await shbAfter(tid === sh.id ? next?.id : null);
  const e = histAdd({label: tr('Deleted {0}', qn(name)), ids: [], snaps: [], lids: [],
    undo: async () => { await shbReq('POST', shbUrl(bid, tid, 'restore')); await shbAfter(tid); return {skipped: []}; },
    redo: async () => { await shbReq('DELETE', shbUrl(bid, tid)); await shbAfter(next?.id); return {skipped: []}; }});
  histToast(tr('Sheet {0} deleted', qn(name)), e);
}
function shbMenu(sh, tid, a) {
  const tabs = shbTabs(), i = tabs.findIndex(t => t.id === tid), t = tabs[i]; if (!t) return;
  menu(a, [{label: tr('Rename…'), icon: 'edit', fn: () => shbRename(sh, tid)},
    {label: tr('Duplicate'), icon: 'copy', fn: () => shbAdd(sh, true)},
    ...(i > 0 ? [{label: tr('Move left'), icon: 'left', fn: () => shbMove(sh, tid, i - 1)}] : []),
    ...(i < tabs.length - 1 ? [{label: tr('Move right'), icon: 'right', fn: () => shbMove(sh, tid, i + 1)}] : []),
    ...(t.first ? [] : ['-', {label: tr('Delete sheet'), icon: 'trash', cls: 'flag-5', fn: () => shbDelete(sh, tid)}])], null, null, t.name);
}

document.addEventListener('click', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-shb]');
  const sh = SHV.sh;
  if (!a || !sh || !$('#view')?.contains(a)) return;
  if (a.dataset.shb === 'add') { shbAdd(sh, false); return; }
  const id = +a.dataset.id;
  if (id !== sh.id) shbOpen(id);
  else if (sh.can_write) shbMenu(sh, id, a);
});
document.addEventListener('dblclick', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-shb="tab"]');
  if (a && SHV.sh?.can_write && +a.dataset.id === SHV.sh.id) { closePop(); shbRename(SHV.sh, SHV.sh.id); }
});
// drag a tab onto another one (a computer; on a phone: the menu's Move left / right)
document.addEventListener('dragstart', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-shb="tab"]');
  if (!a || !SHV.sh?.can_write) return;
  e.dataTransfer?.setData('text/x-kalmido-sheet', a.dataset.id); if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  a.classList.add('drag');
});
document.addEventListener('dragend', e => { /** @type {any} */ (e.target).closest?.('[data-shb="tab"]')?.classList.remove('drag'); });
document.addEventListener('dragover', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-shb="tab"]');
  if (a && e.dataTransfer?.types.includes('text/x-kalmido-sheet')) e.preventDefault();
});
document.addEventListener('drop', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-shb="tab"]'), sh = SHV.sh;
  const tid = +(e.dataTransfer?.getData('text/x-kalmido-sheet') || 0);
  if (!a || !sh || !tid) return;
  e.preventDefault();
  shbMove(sh, tid, shbTabs().findIndex(t => t.id === +a.dataset.id));
});
