// @ts-check
/* Kalmido web client, 2.1045.0 (#5823): the whole knowledge area of a workspace shared at once with an agent. "Share…" at the
   head of the area (the space's menu "…", a right-click / long press on "Knowledge" in the side panel) opens the one Share
   dialog (fsshare.js) on the area's root node "Knowledge": agents only, view or edit -- everything below, also what is added
   later. Before a share is made the dialog says how many folders / pages become visible and how many folders are excluded.
   Below each agent's share: "Excluded:" and "Exclude folders…" (several at once). A folder's menu: "Exclude from the area
   share" / "Include again"; the folder row shows "not for <agent>". The exclusions are the agent's data lock (wiki_folders,
   PATCH /api/agents/<id>/data-lock), the facts come from GET /api/wiki/area-share (wiki/wkarea.py). An encrypted space: a
   sentence instead of the dialog. Part of the lazily loaded knowledge module (lazyload.js). */
'use strict';

const WKAR = /** @type {Record<string, any>} */ ({});
const wkar_q = sp => `/api/wiki/area-share?space=${encodeURIComponent(sp)}`;
async function wkar_load(sp) {
  if (!sp || S.me?.kid || S.me?.kind === 'agent') return;
  let j; try { j = await api('GET', wkar_q(sp)); } catch { return; }
  const was = JSON.stringify(WKAR[sp] || null); WKAR[sp] = j;
  // drawn again only when a mark can change (the menus read WKAR when they open)
  if (S.route.mod === 'wiki' && was !== JSON.stringify(j) && (was !== 'null' || (j.shares || []).some(s => s.excluded.length))) renderView();
}
const wkar_lockSay = () => toast(tr('This workspace is encrypted in the browser: its knowledge area cannot be shared.'));
// the area's menu items (the space's "…", the side panel's "Knowledge")
function wkar_items(sp) {
  const a = WKAR[sp], d = typeof WK !== 'undefined' ? WK.idx[sp] : null;
  if (S.me?.kid || S.me?.kind === 'agent') return [];
  if (a?.locked || (typeof wk_locked === 'function' && wk_locked(sp))) return [{label: tr('Share whole knowledge area…'), icon: 'lock', fn: wkar_lockSay}];
  if (!a?.may && !(d?.root && d.mayWrite !== false)) return [];
  return [{label: tr('Share whole knowledge area…'), icon: 'users', fn: () => wkar_share(sp)}];
}
// the tree's root node "Knowledge" of a space (all workspaces view): its menu
function wkar_rootItems(nid) {
  if (typeof WK === 'undefined') return null;
  const sp = Object.keys(WK.idx).find(k => WK.idx[k]?.root === nid);
  return sp ? wkar_items(sp) : null;
}
const wkar_names = (sp, fid) => (WKAR[sp]?.shares || []).filter(s => s.excluded.includes(fid)).map(s => s.name);
// the mark at an excluded folder's row
function wkar_mark(sp, fid) {
  const ns = wkar_names(sp, fid); if (!ns.length) return '';
  const t = tr('not for {0}', ns.join(', '));
  return `<span class="wkamark" title="${esc(t)}">${ic('eyeoff', 's')}<span>${esc(t)}</span></span>`;
}
// a folder's menu: exclude it from / include it again in each agent's area share
function wkar_folderItems(sp, fid) {
  const sh = (WKAR[sp]?.shares || []).filter(s => s.editable); if (!sh.length) return [];
  const one = sh.length === 1;
  return sh.map(s => s.excluded.includes(fid)
    ? {label: one ? tr('Include again') : tr('Include again for {0}', s.name), icon: 'eye', fn: () => wkar_setEx(sp, s, [fid], false)}
    : {label: one ? tr('Exclude from the area share') : tr('Exclude from the area share for {0}', s.name), icon: 'eyeoff', fn: () => wkar_setEx(sp, s, [fid], true)});
}
// the exclusions are the agent's data lock: read it whole, change these folders, write it back (other spaces' ids stay)
async function wkar_setEx(sp, s, fids, on, quiet) {
  let cur; try { cur = (await api('GET', `/api/agents/${s.agent_id}/data-lock`)).data_lock.wiki_folders.map(x => x.id); } catch { return false; }
  const next = on ? [...new Set([...cur, ...fids])] : cur.filter(x => !fids.includes(x));
  if (next.length === cur.length && next.every((x, i) => x === cur[i])) return true;
  try { await api('PATCH', `/api/agents/${s.agent_id}/data-lock`, {wiki_folders: next}); } catch { return false; }
  await wkar_load(sp); if (S.route.mod === 'wiki') renderView();
  if (!quiet) offerUndo(on ? tr('Excluded from the area share for {0}', s.name) : tr('Included again for {0}', s.name),
    histAdd({label: tr('Area share of {0}', s.name), undo: () => wkar_setEx(sp, s, fids, !on, true), redo: () => wkar_setEx(sp, s, fids, on, true)}));
  return true;
}
const wkar_fname = (sp, id) => (WK.idx[sp]?.folders || []).find(f => f.id === id)?.path || tr('Folder');
// "Excluded:" + "Exclude folders…" under each agent's share (the Share dialog's own section)
function wkar_extra(box, sp) {
  const a = WKAR[sp]; if (!box || !a) return;
  const lim = a.limit ? `<div class="shint lhint keep">${ic('alert', 's')} ${esc(tr('This knowledge area is very large: not every page can be reached through the share.'))}</div>` : '';
  box.innerHTML = lim + `<h4>${esc(tr('Agents with the whole knowledge area'))}</h4>` + ((a.shares || []).length ? (a.shares || []).map(s => `<div class="wkaex" data-wka-agent="${s.agent_id}">
      <div><b>${esc(s.name)}</b> <small class="muted">${esc(tr('{0} folders / {1} pages', a.folders, a.pages))}</small></div>
      <div class="muted">${esc(tr('Excluded:'))} ${s.excluded.length ? s.excluded.map(id => `<span class="wkaexf">${esc(wkar_fname(sp, id))}${s.editable ? ` <button type="button" class="linkbtn" data-wka-in="${id}" aria-label="${esc(tr('Include again'))}" title="${esc(tr('Include again'))}">${ic('x', 's')}</button>` : ''}</span>`).join(', ') : esc(tr('nothing'))}</div>
      ${s.editable ? `<button type="button" class="btn sm" data-wka-pick="${s.agent_id}">${ic('eyeoff', 's')} ${esc(tr('Exclude folders…'))}</button>` : `<small class="muted">${esc(tr('Only who may change this agent can exclude folders.'))}</small>`}</div>`).join('')
    : `<div class="muted mhint">${esc(tr('No agent sees the whole knowledge area yet.'))}</div>`);
  if (box._wka) return; box._wka = 1;
  box.addEventListener('click', async e => {
    const t = /** @type {any} */ (e.target);
    const s = (WKAR[sp]?.shares || []).find(x => x.agent_id === +(t.closest('[data-wka-agent]')?.dataset.wkaAgent));
    if (!s) return;
    const inb = t.closest('[data-wka-in]');
    if (inb) { if (await wkar_setEx(sp, s, [+inb.dataset.wkaIn], false)) wkar_extra(box, sp); return; }
    if (t.closest('[data-wka-pick]')) { const ids = await wkar_pick(sp, s); if (ids?.length && await wkar_setEx(sp, s, ids, true)) wkar_extra(box, sp); }
  });
}
// several folders at once
async function wkar_pick(sp, s) {
  const fs = (WK.idx[sp]?.folders || []).filter(f => !s.excluded.includes(f.id)).sort((x, y) => x.path.localeCompare(y.path));
  if (!fs.length) { toast(tr('There is no folder left to exclude.')); return null; }
  let picked = /** @type {number[]} */ ([]);
  const ok = await askDialog({title: tr('Exclude folders for {0}', s.name), ok: tr('Exclude'),
    html: `<p class="muted">${esc(tr('The agent no longer sees these folders and everything in them, also what is added later. A folder or page inside that you share with it on its own stays visible.'))}</p><div class="wkapick">${fs.map(f => `<label class="chk"><input type="checkbox" value="${f.id}"> ${esc(f.path)}</label>`).join('')}</div>`,
    submit: () => { picked = $$('.wkapick input:checked').map(x => +(/** @type {any} */ (x)).value); return picked.length ? true : false; }});
  return ok ? picked : null;
}
// the dialog itself
async function wkar_share(sp) {
  if ((typeof wk_locked === 'function' && wk_locked(sp))) { wkar_lockSay(); return; }
  await wkar_load(sp);
  const a = WKAR[sp];
  if (a?.locked) { wkar_lockSay(); return; }
  if (!a?.root) { toast(tr('Add a page first: an empty knowledge area has nothing to share.')); return; }
  if (!a.may) { toast(tr('Only who may write in this workspace can share its knowledge area.')); return; }
  let box = null;
  await fs_shareDialog(a.root, {org: false,
    hint: tr('Shares the whole knowledge area of this workspace with an agent: every folder and page, also the ones added later. People keep sharing single folders or pages.'),
    confirm: async (target, role) => {
      const [k, v] = String(target).split(':'); if (k !== 'agent_id') return true;
      let p; try { p = (await api('GET', wkar_q(sp) + `&agent_id=${+v}`)).preview; } catch { return false; }
      return askDialog({title: tr('Share the whole knowledge area?'), ok: tr('Share'),
        body: tr('{0} folders / {1} pages visible, {2} folders excluded.', p.folders, p.pages, p.excluded) + ' ' + (role === 'edit' ? tr('The agent can change these pages.') : tr('The agent can read these pages.'))});
    },
    onChange: async () => { await wkar_load(sp); if (typeof wk_after === 'function') wk_after(sp); if (box) wkar_extra(box, sp); },
    extra: (/** @type {any} */ b) => { box = b; wkar_extra(b, sp); }});
}
// a right-click / long press on "Knowledge" at the top of the side panel (wiki.js wk_panelHtml: data-wkarea)
document.addEventListener('contextmenu', e => {
  const t = /** @type {any} */ (e.target).closest?.('#side [data-wkarea]'); if (!t) return;
  const it = wkar_items(t.dataset.wkarea); if (!it.length) return;
  e.preventDefault(); menu(t, it);
});
