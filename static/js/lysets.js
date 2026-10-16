/* Kalmido web client: saved arrangements of a view (2.55.0, #1069) and arrangements sent as templates (#1068).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.55.0 (#1069) several saved arrangements per view
// A view built with LY (dashboard.js) can keep named arrangements ("Focus", "Overview"; server: accounts/layoutsets.py, the
// same on every device). The header shows a switch next to "Arrange blocks…" once the view has one saved arrangement
// besides the standard; before that only "Save as arrangement…" in a block's "…" menu and while customizing. Switching copies
// the saved arrangement into the view's own value (so the standard bar, "Different on the phone" and older versions work
// unchanged); changes made while one is active go into it as well (the server follows). Every step is one undo step.
S.lyv = null;  // {rows: [{id, key, name, layout, pos, source, active}], at}
const LYV = {busy: false};

// the key of view v on the server: LY[v].key, or "list:<id>" for the project page
function lyv_key(v) {
  const d = LY[v]; if (!d) return '';
  if (d.key) return d.key;
  const id = v === 'project' && routeList()?.id;
  return id ? 'list:' + id : '';
}
const lyv_rows = key => (S.lyv?.rows || []).filter(r => r.key === key).sort((a, b) => a.pos - b.pos || a.id - b.id);
// all of the person's saved arrangements (B, #1066, calls it after a 👍); the view redraws
function lyv_reload() {
  return api('GET', '/api/layouts/saved').then(j => { S.lyv = {rows: j.saved || [], at: Date.now()}; viewSafeRender(); return S.lyv; })
    .catch(() => { S.lyv ||= {rows: [], at: Date.now()}; return S.lyv; });
}
function lyv_load() {
  if (LYV.busy || (S.lyv && Date.now() - S.lyv.at < 120000) || !S.me) return;
  LYV.busy = true; lyv_reload().finally(() => { LYV.busy = false; });
}
// the view's own value as stored (project page: my own arrangement of it)
function lyv_own(v) {
  const d = LY[v];
  if (d.src) return S.povD[routeList()?.id]?.j?.layout?.mine || '';
  return LY_PEND[d.key] ?? S.settings?.[d.key] ?? '';
}
// the active one; a value without an arrangement (back to the standard) is none (the server ends "active" the same way)
function lyv_active(v, key = lyv_key(v)) {
  const r = lyv_rows(key).find(x => x.active);
  if (r && !wgHasLayout(wgJ(lyv_own(v)))) { r.active = false; return null; }
  return r || null;
}
// the arrangement the view shows now, as a value to store (the standard merged in where the own value has none)
const lyv_current = v => wgStr(lyRaw(v));
// a value from the server becomes the view's own value right here
function lyv_apply(v, key, value) {
  const d = LY[v];
  if (d.src) { const l = routeList(), dd = l && 'list:' + l.id === key && S.povD[l.id]; if (dd?.j) dd.j.layout = {...dd.j.layout, mine: value || ''}; }
  else if (S.settings) { delete LY_PEND[key]; S.settings[key] = value || ''; }
  renderView();
}
const lyv_mark = (key, id) => { for (const r of lyv_rows(key)) r.active = r.id === id; };
// one call after the saves still on their way (lyQueue), so an older save cannot overwrite the switch
const lyv_call = (m, p, b) => new Promise((res, rej) => lyQueue(() => api(m, p, b).then(res, rej)));

// ---- switching
async function lyv_switchTo(v, key, id, value) {  // id = a saved one, else the own value becomes value ('' = the standard)
  const j = id ? await lyv_call('POST', `/api/layouts/saved/${id}/activate`) : await lyv_call('POST', '/api/layouts/saved/standard', {key, value: value || ''});
  lyv_mark(key, id || 0); lyv_apply(v, key, j.value);
  return {};
}
async function lyv_activate(id, v) {
  const r = (S.lyv?.rows || []).find(x => x.id === id); if (!r) return;
  v ||= Object.keys(LY).find(x => lyv_key(x) === r.key); if (!v) return;
  const key = r.key, old = {id: lyv_active(v, key)?.id || 0, value: lyv_own(v)};
  try { await lyv_switchTo(v, key, id); } catch { return; }
  const e = histAdd({label: tr('Arrangement switched'), undo: () => lyv_switchTo(v, key, old.id, old.value), redo: () => lyv_switchTo(v, key, id)});
  histToast(tr('Showing “{0}”', r.name), e);
}
async function lyv_standard(v) {
  const key = lyv_key(v), d = LY[v], old = {id: lyv_active(v, key)?.id || 0, value: lyv_own(v)};
  const sw = d.src ? null : wgSwitches(wgJ(old.value).opts), nv = sw ? JSON.stringify({opts: sw}) : '';  // a block's switches stay
  try { await lyv_switchTo(v, key, 0, nv); } catch { return; }
  const e = histAdd({label: tr('Arrangement switched'), undo: () => lyv_switchTo(v, key, old.id, old.value), redo: () => lyv_switchTo(v, key, 0, nv)});
  histToast(tr('Showing the standard'), e);
}

// ---- save as / rename / delete / order
async function lyv_saveAs(v) {
  const key = lyv_key(v); if (!key) return;
  if (lyv_rows(key).length >= 12) { toast(tr('At most {0} saved arrangements per view', 12)); return; }
  const name = (await askPrompt(tr('Save arrangement as'), '', {ok: tr('Save'), input: {max: 60, placeholder: tr('e.g. Focus or Overview')}}))?.trim();
  if (!name) return;
  const layout = lyv_current(v), old = {id: lyv_active(v, key)?.id || 0, value: lyv_own(v)};
  let cur = 0;
  const make = async () => {
    const j = await lyv_call('POST', '/api/layouts/saved', {key, name, layout, activate: true});
    cur = j.saved.id; (S.lyv ||= {rows: [], at: Date.now()}).rows.push(j.saved); lyv_mark(key, cur); lyv_apply(v, key, j.value);
    return j;
  };
  const drop = async () => {
    await lyv_call('DELETE', `/api/layouts/saved/${cur}`); S.lyv.rows = S.lyv.rows.filter(x => x.id !== cur);
    await lyv_switchTo(v, key, old.id, old.value); return {};
  };
  let j; try { j = await make(); } catch { return; }
  const e = histAdd({label: tr('Arrangement saved'), undo: drop, redo: () => make().then(() => ({}))});
  histToast(tr('Saved as “{0}”', j.saved.name), e);
}
async function lyv_patch(id, b) {
  const j = await lyv_call('PATCH', `/api/layouts/saved/${id}`, b);
  const i = S.lyv.rows.findIndex(x => x.id === id); if (i >= 0) S.lyv.rows[i] = j.saved;
  if (b.pos != null) await lyv_reload();
  return j;
}
async function lyv_rename(id, after) {
  const r = S.lyv?.rows.find(x => x.id === id); if (!r) return;
  const name = (await askPrompt(tr('Rename arrangement'), r.name, {ok: tr('Rename'), input: {max: 60}}))?.trim();
  if (!name || name === r.name) return;
  const old = r.name; let j;
  try { j = await lyv_patch(id, {name}); } catch { return; }
  const nn = j.saved.name, step = n => async () => { await lyv_patch(id, {name: n}); renderView(); after?.(); return {}; };
  histToast(tr('Renamed'), histAdd({label: tr('Arrangement renamed'), undo: step(old), redo: step(nn)}));
  renderView(); after?.();
}
async function lyv_delete(id, after) {
  const r = S.lyv?.rows.find(x => x.id === id); if (!r) return;
  const v = Object.keys(LY).find(x => lyv_key(x) === r.key);
  let d, cur = id;
  const del = async () => { const j = await lyv_call('DELETE', `/api/layouts/saved/${cur}`); S.lyv.rows = S.lyv.rows.filter(x => x.id !== cur); d = j.deleted; renderView(); after?.(); return {}; };
  const back = async () => {
    const j = await lyv_call('POST', '/api/layouts/saved', {key: d.key, name: d.name, layout: d.layout, pos: d.index, activate: d.active || undefined});
    cur = j.saved.id; await lyv_reload(); if (j.value != null && v) lyv_apply(v, d.key, j.value); after?.(); return {};
  };
  try { await del(); } catch { return; }
  histToast(tr('“{0}” deleted', r.name), histAdd({label: tr('Arrangement deleted'), undo: back, redo: del}));
}
async function lyv_move(id, dl, after) {
  const r = S.lyv?.rows.find(x => x.id === id); if (!r) return;
  const rows = lyv_rows(r.key), i = rows.findIndex(x => x.id === id), j = i + dl; if (j < 0 || j >= rows.length) return;
  const step = p => async () => { await lyv_patch(id, {pos: p}); after?.(); return {}; };
  try { await step(j)(); } catch { return; }
  histAdd({label: tr('Arrangement moved'), undo: step(i), redo: step(j)});
  announce(dl < 0 ? tr('Moved up') : tr('Moved down'));
}

// ---- the switch in the header (next to "Arrange blocks…"), the menu, the entries elsewhere
function lyv_btn(v) {
  if (!LY[v] || S.ly.view === v) return '';
  setTimeout(lyv_load, 0);
  const key = lyv_key(v), rows = key ? lyv_rows(key) : []; if (!rows.length) return '';
  const a = lyv_active(v, key), nm = a ? a.name : tr('Standard');
  return `<button type="button" class="btn sm lyvsw${a ? ' on' : ''}" data-act="lyv-menu" data-lyv="${v}" aria-haspopup="menu" title="${esc(tr('Arrangement: {0}', nm))}" aria-label="${esc(tr('Arrangement: {0}', nm))}"><span class="lyvnm">${esc(nm)}</span>${ic('down', 's')}</button>`;
}
function lyv_menu(a) {
  const v = a.dataset.lyv, key = lyv_key(v); if (!key) return;
  const rows = lyv_rows(key), act = lyv_active(v, key);
  menu(a, [{head: tr('Arrangement')}, {label: tr('Standard'), icon: 'grid', on: !act, fn: () => { if (act) lyv_standard(v); }},
    ...rows.map(r => ({label: r.name, icon: r.source === 'template' ? 'send' : r.source === 'agent' ? 'bot' : 'bookmark', on: act?.id === r.id,
      fn: () => { if (act?.id !== r.id) lyv_activate(r.id, v); }})),
    '-', ...lyv_menuItems(v, true), {label: tr('Manage arrangements…'), icon: 'edit', fn: () => lyv_manage(v)}], null, null, tr('Arrangement'));
}
// Today keeps its switch in the view's "…" menu (render.js topMoreItems): a second level, once there is a saved arrangement
function lyv_viewMenu(v) {
  setTimeout(lyv_load, 0);
  const key = lyv_key(v), rows = key ? lyv_rows(key) : []; if (!rows.length) return [];
  const act = lyv_active(v, key);
  return [{label: tr('Arrangement: {0}', act ? act.name : tr('Standard')), icon: 'bookmark', more: [{label: tr('Standard'), icon: 'grid', on: !act, fn: () => { if (act) lyv_standard(v); }},
    ...rows.map(r => ({label: r.name, icon: 'bookmark', on: act?.id === r.id, fn: () => { if (act?.id !== r.id) lyv_activate(r.id, v); }})),
    '-', {label: tr('Manage arrangements…'), icon: 'edit', fn: () => lyv_manage(v)}]}];
}
// entries for a block's "…" menu (widgets.js) and the switch: save as, send as a template
function lyv_menuItems(v, all) {
  if (!LY[v] || !lyv_key(v) || (!all && S.ly.view === v && S.ly.std)) return [];
  return [{label: tr('Save as arrangement…'), icon: 'bookmark', fn: () => lyv_saveAs(v)},
    ...(collabOn() ? [{label: tr('Send as template…'), icon: 'send', fn: () => lyv_send(v)}] : [])];
}
// while customizing: where the changes go, and the same two actions
function lyv_edBar(v) {
  if (S.ly.std || !lyv_key(v)) return '';
  const a = lyv_active(v);
  return `<div class="lyvbar">${a ? `<span class="muted">${esc(tr('Changes go into “{0}”', a.name))}</span>` : ''}<span class="spacer"></span><button type="button" class="btn sm" data-act="lyv-save" data-lyv="${v}">${ic('bookmark', 's')}<span>${tr('Save as arrangement…')}</span></button>${collabOn() ? `<button type="button" class="btn sm" data-act="lyv-send" data-lyv="${v}">${ic('send', 's')}<span>${tr('Send as template…')}</span></button>` : ''}</div>`;
}
const collabOn = () => typeof feat !== 'function' || feat('collab');
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="lyv-"]'); if (!a || !LY[a.dataset.lyv]) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act, v = a.dataset.lyv;
  if (k === 'lyv-menu') lyv_menu(a);
  else if (k === 'lyv-save') lyv_saveAs(v);
  else if (k === 'lyv-send') lyv_send(v);
}, true);

// ---- "Manage arrangements": rename, order, delete (each one undo step)
function lyv_manage(v) {
  const key = lyv_key(v); if (!key) return;
  const md = modal(`<h3 id="lyvm-t">${esc(tr('Manage arrangements'))}</h3><div class="lyvlist" role="list"></div>
    <p class="muted lyvhint">${esc(tr('The standard is what the view shows without an own arrangement.'))}</p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-lyvm="close">${tr('Done')}</button></div>`);
  md.classList.add('lyvm'); md.setAttribute('role', 'dialog'); md.setAttribute('aria-labelledby', 'lyvm-t');
  const draw = () => {
    if (!md.isConnected) return;
    const rows = lyv_rows(key), n = rows.length;
    $('.lyvlist', md).innerHTML = rows.length ? rows.map((r, i) => `<div class="lyvrow" role="listitem" data-id="${r.id}"><span class="lyvrn">${esc(r.name)}${r.active ? ` <small class="muted">${tr('active')}</small>` : ''}</span>
      <button type="button" class="iconbtn" data-lyvm="up" ${i ? '' : 'disabled'} aria-label="${esc(tr('Move up') + ': ' + r.name)}">${ic('up', 's')}</button>
      <button type="button" class="iconbtn" data-lyvm="down" ${i < n - 1 ? '' : 'disabled'} aria-label="${esc(tr('Move down') + ': ' + r.name)}">${ic('down', 's')}</button>
      <button type="button" class="iconbtn" data-lyvm="ren" aria-label="${esc(tr('Rename') + ': ' + r.name)}" title="${esc(tr('Rename'))}">${ic('edit', 's')}</button>
      <button type="button" class="iconbtn" data-lyvm="del" aria-label="${esc(tr('Delete') + ': ' + r.name)}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></div>`).join('')
      : `<p class="muted">${esc(tr('No saved arrangements yet.'))}</p>`;
  };
  draw();
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-lyvm]'); if (!b) return;
    const w = b.dataset.lyvm, id = +b.closest('[data-id]')?.dataset.id;
    if (w === 'close') { modalClose(md); return; }
    const refocus = () => { draw(); setTimeout(() => $(`[data-id="${id}"] [data-lyvm="${w}"]:not([disabled])`, md)?.focus() || $('[data-lyvm]', md)?.focus(), 30); };
    if (w === 'up' || w === 'down') lyv_move(id, w === 'up' ? -1 : 1, refocus);
    else if (w === 'ren') lyv_rename(id, refocus);
    else if (w === 'del') lyv_delete(id, refocus);
  });
}

// ------------------------------------------------------------------ 2.55.0 (#1068) an arrangement as a template
// Only the arrangement travels (blocks, order, widths, heights, a block's switches), never content: a block the recipient
// cannot see stays empty for them. Recipients: people I see (as the share dialog offers them; the server checks it), not
// agents; a project page only to people with access to it.
let LYV_PPL = null, LYV_PPL_AT = 0;
async function lyv_people() {
  if (LYV_PPL && Date.now() - LYV_PPL_AT < 120000) return LYV_PPL;
  LYV_PPL_AT = Date.now();
  try { LYV_PPL = (await api('GET', '/api/users')).users.filter(u => !u.agent && u.kind !== 'agent' && !u.disabled && u.id !== S.me?.id); } catch { LYV_PPL = []; }
  return LYV_PPL;
}
async function lyv_send(v) {
  const key = lyv_key(v); if (!key) return;
  const ppl = await lyv_people(), a = lyv_active(v, key);
  if (!ppl.length) { toast(tr('There is nobody to send it to.')); return; }
  const md = modal(`<form novalidate><h3 id="lyvs-t">${esc(tr('Send as template'))}</h3>
    <p class="muted">${esc(tr('They get the arrangement of this view as a suggestion, never its content. Each person decides whether to take it over.'))}</p>
    <label class="fl">${tr('Name')}<input id="lyvs-n" maxlength="60" value="${esc(a?.name || '')}" placeholder="${esc(tr('e.g. Focus or Overview'))}" autocomplete="off"></label>
    <input type="search" id="lyvs-q" placeholder="${esc(tr('Search people'))}" aria-label="${esc(tr('Search people'))}" autocomplete="off">
    <div class="lyvppl" role="group" aria-label="${esc(tr('People'))}">${ppl.map(u => `<label class="chkl lyvp" data-q="${esc((u.display_name + ' ' + u.username).toLowerCase())}"><input type="checkbox" value="${u.id}"> ${esc(u.display_name || u.username)}</label>`).join('')}</div>
    <div class="foot"><span class="muted lyvcnt" aria-live="polite"></span><span class="spacer"></span><button type="button" class="btn" data-lyvs="no">${tr('Cancel')}</button><button type="submit" class="btn pri">${tr('Send')}</button></div></form>`);
  md.classList.add('lyvs'); md.setAttribute('role', 'dialog'); md.setAttribute('aria-labelledby', 'lyvs-t');
  const picked = () => $$('.lyvppl input:checked', md).map(x => +x.value);
  const cnt = () => { const n = picked().length; $('.lyvcnt', md).textContent = n ? tr('{0} chosen', n) : ''; $$('.lyvppl input:not(:checked)', md).forEach(x => { x.disabled = n >= 20; }); };
  md.addEventListener('change', cnt);
  $('#lyvs-q', md).addEventListener('input', e => { const q = e.target.value.trim().toLowerCase(); $$('.lyvp', md).forEach(x => { x.hidden = !!q && !x.dataset.q.includes(q); }); });
  md.addEventListener('click', e => { if (e.target.closest('[data-lyvs="no"]')) modalClose(md); });
  $('form', md).addEventListener('submit', async e => {
    e.preventDefault();
    const name = $('#lyvs-n', md).value.trim(), to = picked();
    if (!name) { $('#lyvs-n', md).focus(); toast(tr('Give the arrangement a name')); return; }
    if (!to.length) { toast(tr('Choose at least one person')); return; }
    try { await api('POST', '/api/layouts/offers', {key, name, layout: lyv_current(v), to}); } catch { return; }
    modalClose(md); toast(to.length === 1 ? tr('Template sent') : tr('Template sent to {0} people', to.length));
  });
  setTimeout(() => $('#lyvs-n', md)?.focus(), 30);
}
// the view of a key (preview of a template): LY entry with that key, the project page for "list:<id>"
const lyv_viewOf = key => key.startsWith('list:') ? 'project' : Object.keys(LY).find(x => LY[x].key === key);
function lyv_preview(key, layout) {
  const v = lyv_viewOf(key); if (!v) return '';
  let p, bs;
  try { bs = lyBlocks(v); p = lyPref(v, {raw: wgJ(layout), phone: false}); } catch { return ''; }
  const wl = w => tr((WG_WN.find(x => x[0] === w) || [0, '', 'Half'])[2]);
  const vis = p.order.filter(k => !p.hidden.has(k));
  return `<ol class="lyvprev">${vis.map(k => `<li><span>${esc(tr(bs.find(b => b[0] === k)?.[1] || k))}</span><small class="muted">${esc(isMobile() ? '' : wl(p.w(k)))}</small></li>`).join('')}</ol>${p.hidden.size ? `<p class="muted">${esc(tr('Hidden: {0}', [...p.hidden].map(k => tr(bs.find(b => b[0] === k)?.[1] || k)).join(', ')))}</p>` : ''}`;
}
// from the News item "lytpl": the template with its preview, "Take over" / "Decline"
async function lyv_offerOpen(oid) {
  let o; try { o = await api('GET', `/api/layouts/offers/${+oid}`); } catch { return; }
  const v = lyv_viewOf(o.key), vt = v ? LY[v].title() : '';
  const md = modal(`<h3 id="lyvo-t">${esc(tr('Arrangement “{0}”', o.name))}</h3>
    <p>${esc(tr('{0} sent you this arrangement as a template.', o.from.name))}${vt ? ` <span class="muted">${esc(vt)}</span>` : ''}</p>
    <p class="muted">${esc(tr('Only the arrangement of the blocks comes along, nothing of its content.'))}</p>
    ${lyv_preview(o.key, o.layout)}
    <label class="chkl"><input type="checkbox" id="lyvo-act" checked> ${tr('Show it right away')}</label>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-lyvo="no">${tr('Decline')}</button><button type="button" class="btn pri" data-lyvo="yes">${tr('Take over')}</button></div>`);
  md.classList.add('lyvo'); md.setAttribute('role', 'dialog'); md.setAttribute('aria-labelledby', 'lyvo-t');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-lyvo]'); if (!b) return;
    b.disabled = true;
    try {
      if (b.dataset.lyvo === 'no') { await lyv_call('POST', `/api/layouts/offers/${o.id}/decline`); modalClose(md); toast(tr('Template declined')); }
      else {
        const act = $('#lyvo-act', md).checked, j = await lyv_call('POST', `/api/layouts/offers/${o.id}/accept`, {activate: act});
        modalClose(md); await lyv_reload();
        if (act && j.value != null) {
          const k = o.key;
          if (!k.startsWith('list:') && S.settings) { delete LY_PEND[k]; S.settings[k] = j.value || ''; }
          else { const dd = S.povD?.[+k.slice(5)]; if (dd?.j) dd.j.layout = {...dd.j.layout, mine: j.value || ''}; }
        }
        toast(tr('Saved as “{0}”', j.saved.name), v ? () => { if (v === 'project') go('l/' + o.key.slice(5)); else lyv_goView(v); } : null, 6000, tr('Open'));
      }
      S.nf && (S.nf.items = (S.nf.items || []).filter(x => !(x.kind === 'lytpl' && +x.data?.offer === +o.id)));
      renderView();
    } catch { b.disabled = false; }
  });
}
// the route of a view on the builder (the toast's "Open")
const LYV_ROUTE = {home: 'home', today: 'today', time: 'time', agents: 'agents', projects: 'overview', review: 'review'};
const lyv_goView = v => go(LYV_ROUTE[v] || v);
