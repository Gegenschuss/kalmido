// @ts-check
/* Kalmido web client: the projects of an organisation for its admins (oadmOpen: list, take back, outreach log) (2.1156.0, #4280: moved here from account.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

// ---- 2.35.0 (#1101): an organisation admin's "Lists of the organisation": the lists that belong to the organisation (never
// private lists, private sharing or inboxes) with owner, numbers and the last change - never their contents. Archive / restore,
// hand over to another person of the organisation, delete for good from the archive (the name typed to confirm); a history.
const OADM_ACT = {archive: N_('{0} archived {1}'), restore: N_('{0} restored {1}'), delete: N_('{0} deleted {1} permanently'), trash: N_('{0} moved {1} to the trash'), undelete: N_('{0} restored {1} from the trash'), purge: N_('{0} deleted {1} permanently'), owner: N_('{0} handed {1} to {2}'),
  edit: N_('{0} changed {1}'), icon: N_('{0} changed the icon of {1}'),  // 2.56.0 (#1795)
  moveout: N_('{0} moved {1} out of the organisation'),  // 2.148.1 B (#2483)
  outok: N_('{0} released {1} for its maker to take it back'), outno: N_('{0} rejected giving {1} back'),  // 2.361.2 (#2923)
  export: N_('{0} exported {1} with the account export'),  // 2.148.1 C (#2492)
  tasks: N_('{0} looked at the tasks of {1}'), tasksall: N_('{0} looked at the tasks of all projects')};  // 2.574.0 (#3376): the read-only task view
function oadmRow(x) {
  const sub = [x.owner_agent ? tr('Owner: {0} (agent)', x.owner_name) : tr('Owner: {0}', x.owner_name), tr('{0} open', x.open) + ' / ' + trn('{0} task', '{0} tasks', x.tasks),
    trn('{0} member', '{0} members', x.members), tr('changed {0}', fmtDateLoc(String(x.changed_at || '').slice(0, 10)) || '–'), x.folder && tr('Folder: {0}', fDisp(x.folder))].filter(Boolean);  // 2.39.1 (#1188): + folder path
  return `<div class="mrow oadmrow ${x.archived ? 'off' : ''}" data-olid="${x.id}"><span class="n"><b>${ole_mark(x)}${esc(x.name)}</b>${x.archived ? ` <span class="muted">${esc(tr('archived'))}</span>` : ''}<small class="muted">${esc(sub.join(' · '))}</small></span>
    <span class="oadmb">${x.archived ? `<button type="button" class="btn sm" data-oa="restore">${tr('Restore')}</button><button type="button" class="btn sm danger" data-oa="delete">${tr('Delete…')}</button>`
      : `<button type="button" class="btn sm" data-oa="edit">${tr('Edit')}</button><button type="button" class="btn sm" data-oa="archive">${tr('Archive')}</button>`}<button type="button" class="btn sm" data-oa="owner">${tr('Hand over…')}</button></span></div>`;  // 2.56.0 (#1795): + Edit
}
// 2.361.2 (#2923): what a member asks back (they brought it in or made it): release = they may move it into their private space
const OOR_KIND = {list: N_('Project'), sheet: N_('Table'), file: N_('File or folder'), wiki: N_('Knowledge page'), clients: N_('Client'),
  poll: N_('Poll'), video: N_('Video sign-off'), bookmark: N_('Bookmark'), drafts: N_('Draft'), letters: N_('Letter')};  // 2.361.2 B (#2923): + drafts; 2.356.1 (#3344): + letters
const oor_kind = k => OOR_KIND[k] ? tr(OOR_KIND[k]) : k;
function oorHtml(rs) {
  const open = (rs || []).filter(r => r.state === 'open');
  if (!open.length) return '';
  return `<h4 class="oadmh">${esc(tr('Asked back'))} <span class="muted">${open.length}</span></h4>
    <div class="shint keep">${esc(tr('These members brought something into the organisation or made it there and ask to take it back into their private workspace. Release it and they can move it themselves; nobody else in the organisation sees it there afterwards.'))}</div>
    ${open.map(r => `<div class="mrow oorrow" data-oor="${r.id}"><span class="n"><b>${esc(r.name || '–')}</b><small class="muted">${esc([oor_kind(r.kind), tr('asked by {0}', r.by), fmtWhen(r.created_at)].join(' · '))}</small></span>
      <span class="oadmb"><button type="button" class="btn sm pri" data-oord="approve">${esc(tr('Release'))}</button><button type="button" class="btn sm" data-oord="decline">${esc(tr('Reject'))}</button></span></div>`).join('')}`;
}
function oadmDraw(md, j) {
  md._j = j;
  const live = j.lists.filter(x => !x.archived), arch = j.lists.filter(x => x.archived);
  // 2.39.1 (#1188): grouped by owner (listadmin.js)
  $('#oadm-body', md).innerHTML = oorHtml(j.out_requests) + (j.lists.length ? `${lmOadmBody({lists: live}, oadmRow)}${arch.length ? `<h4 class="oadmh">${esc(tr('Archive'))}</h4>${lmOadmBody({lists: arch}, oadmRow)}` : ''}`
    : `<div class="muted mhint">${tr('The organisation has no projects yet.')}</div>`)
    + (j.log.length ? `<details class="sdet oadmlog"><summary>${tr('History')} <span class="muted">${j.log.length}</span></summary>${j.log.filter(r => OADM_ACT[r.action]).map(r => `<div class="mrow"><span class="n">${tr(OADM_ACT[r.action], `<b>${esc(r.by || '?')}</b>`, `<b>${esc(r.list_name)}</b>`, `<b>${esc(r.to || '')}</b>`)}<small class="muted">${esc(fmtWhen(r.at))}${r.owner && r.action !== 'owner' ? ' · ' + esc(tr('Owner: {0}', r.owner)) : ''}${ole_logDetail(r)}</small></span></div>`).join('')}</details>` : '');
}
async function oadmOpen(oid, name) {
  /** @type {any} */
  const md = modal(`<h3>${esc(tr('Projects of the organisation {0}', name))}</h3>
    <div class="shint keep">${tr('The projects of the organisation that are shared with at least one more person, with names and numbers: their contents stay with their people. Private projects stay invisible, also when they are shared.')}</div>
    <div class="shint lmohint">${ic('info', 's')} ${tr('A project is missing? It is probably private and only shared. Its owner can move it into the organisation: project menu > Edit project… > Workspace.')}</div>
    <div class="members oadm" id="oadm-body"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('oadmmd');
  try { oadmDraw(md, await api('GET', `/api/orgs/${oid}/lists`)); } catch { $('#oadm-body', md).innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; }
  md.addEventListener('click', async (/** @type {any} */ e) => {
    if (e.target.closest('[data-m="close"]')) { md.remove(); return; }
    const od = e.target.closest('[data-oord]');
    if (od) {  // 2.361.2 (#2923): one click releases / declines a member's request
      od.disabled = true;
      try { const r = await api('POST', `/api/orgs/${oid}/out-requests/${+od.closest('[data-oor]').dataset.oor}`, {decision: od.dataset.oord});
        toast(r.state === 'approved' ? tr('Released: the person can take it back now') : tr('Rejected'));
      } catch { /* api() showed it */ }
      try { oadmDraw(md, await api('GET', `/api/orgs/${oid}/lists`)); } catch { /* offline */ }
      return;
    }
    const b = e.target.closest('[data-oa]'); if (!b) return;
    const x = (md._j?.lists || []).find(l => l.id === +b.closest('[data-olid]').dataset.olid); if (!x) return;
    const k = b.dataset.oa, base = `/api/orgs/${oid}/lists/${x.id}`;
    if (k === 'edit') { ole_edit(md, oid, x); return; }  // 2.56.0 (#1795)
    try {
      let j = null;
      if (k === 'archive') {
        if (!await askConfirm(tr('Archive “{0}”?', x.name), tr('The project leaves the sidebar of everyone in it; nothing is deleted. {0} and the members are told. You or the owner can restore it.', x.owner_name), {ok: tr('Archive')})) return;
        j = await api('POST', base + '/archive', {archived: true}); toast(tr('Archived'));
      } else if (k === 'restore') { j = await api('POST', base + '/archive', {archived: false}); toast(tr('Restored')); }
      else if (k === 'delete') {
        const v = await (/** @type {any} */ (askDialog))({title: x.e2e ? tr('Delete “{0}” permanently?', x.name) : tr('Delete “{0}”?', x.name), danger: true, ok: x.e2e ? tr('Delete permanently') : tr('Delete'),  // 2.102.0 A (#1988): the organisation's list trash
          html: `<p>${esc(x.e2e ? tr('This cannot be undone. Its tasks go to the trash in the basket of {0} and can be restored from there; its files and the sharing are lost. {0} and the members are told.', x.owner_name) : otr_orgNote(x.owner_name))}</p><p>${esc(tr('Type the name of the project to delete it'))}</p>`,
          input: {placeholder: x.name, max: 200}});
        if (v === null) return;
        if (v.trim() !== x.name.trim()) { toast(tr('The name does not match: nothing was deleted')); return; }
        j = await api('DELETE', base, {confirm: v.trim()});
        if (j?.trash) otr_offerUndo(x.id, x.name); else toast(tr('Deleted'));
      } else if (k === 'owner') {
        const ps = (md._j.people || []).filter(p => p.id !== x.owner_id);
        if (!ps.length) { toast(tr('Nobody else in the organisation to hand it to')); return; }
        const sel = `<label for="oadm-to">${esc(tr('New owner'))}</label><select id="oadm-to">${ps.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select>`;
        let to = 0;
        const okd = (/** @type {any} */ (askDialog))({title: tr('Hand “{0}” over', x.name), ok: tr('Hand over'), html: `<p>${esc(tr('{0} stays in the project as its admin. The new owner manages its sharing from now on.', x.owner_name))}</p><div class="row">${sel}</div>`});
        setTimeout(() => { const s0 = $('#oadm-to'); if (s0) { to = +s0.value; s0.addEventListener('change', () => { to = +s0.value; }); } }, 0);
        if (!await okd) return;
        j = await api('POST', base + '/owner', {user_id: to}); toast(tr('Handed over'));
      }
      if (j) oadmDraw(md, j);
      await load(); render();
    } catch { /* api() showed it */ }
  });
}
// ---- 2.56.0 (#1795): an organisation admin changes the name (with its emoji), the icon and the colour of a list of the
// organisation -- nothing else, never its contents (PATCH /api/orgs/{id}/lists/{id}, .../icon). The same pickers as the list
// dialog; Save = one undo step (name / colour), a picture is set at once like in the list dialog. The owner and the members
// are told by the server.
const ole_mark = x => x.icon && liconOk(x.icon) ? `<img class="licon ole-ic" src="${esc(x.icon)}" alt="" loading="lazy" decoding="async">`
  : x.color ? `<i class="ole-sw" style="background:${cssColor(lp_col({color: x.color}) || x.color)}" aria-hidden="true"></i>` : '';
function ole_logDetail(r) {
  const d = r.detail || {}, out = [];
  if (d.name) out.push(tr('Name: {0} → {1}', d.name[0], d.name[1]));
  if (d.color) out.push(d.color[1] ? tr('new colour') : tr('colour removed'));
  if (d.icon) out.push(d.icon[1] === 'picture' ? tr('own picture') : d.icon[1] ? tr('preset picture') : tr('picture removed'));
  return out.length ? ' · ' + esc(out.join(' · ')) : '';
}
function ole_edit(om, oid, x) {
  const base = `/api/orgs/${oid}/lists/${x.id}`;
  let m0 = x.name.match(EMO_RE);
  let emo = m0 ? m0[1] : '';
  const nm0 = m0 ? x.name.slice(m0[0].length) : x.name, col0 = lp_col({color: x.color});
  const pick = () => `<span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(x)}`;
  const emoBtn = () => x.icon ? licon(x, 'licon m') : sbiEmo(emo) || ic('list');
  /** @type {any} */
  const md = modal(`<h3>${esc(tr('Edit “{0}”', x.name))}</h3>
    <div class="shint keep">${esc(tr('Only the name, the icon and the colour: the contents stay with the people of the project. {0} and the members are told.', x.owner_name || '?'))}</div>
    <div class="row"><label for="ole-name">${tr('Name')}</label><button type="button" class="emobtn" id="ole-emo" title="${tr('Select icon')}" aria-label="${tr('Select icon')}">${emoBtn()}</button><input id="ole-name" value="${esc(nm0)}" maxlength="200"></div>
    <div class="emogrid hidden" id="ole-emogrid"><button type="button" data-emo="" class="none" title="${tr('No icon')}">${ic('ban', 's')}</button>${sbiGrid().map(e => `<button type="button" data-emo="${e}" class="${e === emo && !x.icon ? 'on' : ''}">${sbiEmo(e)}</button>`).join('')}
      <div class="lipickw">${pick()}</div></div>
    <div class="row"><label>${tr('Colour')}</label><div class="colors" id="ole-col" role="group" aria-label="${esc(tr('Colour'))}">${lp_dlgBtns(col0)}</div></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="cancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('olemd');
  const redraw = j => { if (j && om.isConnected) oadmDraw(om, j); };
  const iconSet = async how => {  // like liconSet, through the organisation's route; the emoji leaves the name with a picture
    let j;
    try {
      if (how === 'none') j = await api('DELETE', base + '/icon');
      else if (how instanceof Blob) { const fd = new FormData(); fd.append('file', how, 'icon.png'); j = await api('POST', base + '/icon', fd); }
      else j = await api('PUT', base + '/icon', {preset: how});
    } catch { return; }
    x.icon = j.icon || ''; redraw(j);
    if (x.icon && emo && m0 && x.name.startsWith(m0[0])) {  // the emoji leaves the name at once (as in the list dialog)
      const nm = x.name.slice(m0[0].length).trim() || nm0;
      try { redraw(await api('PATCH', base, {name: nm})); x.name = nm; m0 = null; } catch { /* api() said why */ }
    }
    if (x.icon) { emo = ''; $$('#ole-emogrid [data-emo]', md).forEach(y => y.classList.remove('on')); $('#ole-emogrid', md).classList.add('hidden'); }
    $('#ole-emo', md).innerHTML = emoBtn(); $('.lipickw', md).innerHTML = pick();
  };
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'cancel') { md.remove(); return; }
    if (b.id === 'ole-emo') { $('#ole-emogrid', md).classList.toggle('hidden'); return; }
    if (b.dataset.c !== undefined) { $$('#ole-col button', md).forEach(y => { y.classList.toggle('on', y === b); y.setAttribute('aria-pressed', String(y === b)); }); return; }
    if (b.dataset.licon) {
      const k = b.dataset.licon;
      if (k !== 'upload') { await iconSet(k); return; }
      const go = async f => {
        if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
        const bl = await avCropModal(f, {title: tr('Project icon'), png: true, square: true}); if (bl) await iconSet(bl);
      };
      const f0 = fpass_take(); if (f0) { go(f0); return; }  // 2.633.0 (#4920): the file of the fixed input before the button (liconPickHtml)
      const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
      inp.addEventListener('change', async () => {
        const f = inp.files?.[0]; if (!f) return;
        go(f);
      });
      inp.click(); return;
    }
    if (b.dataset.emo !== undefined) {
      if (x.icon && b.dataset.emo) await iconSet('none');  // an emoji replaces the picture
      emo = b.dataset.emo;
      $$('#ole-emogrid [data-emo]', md).forEach(y => y.classList.toggle('on', y === b && !!emo));
      $('#ole-emo', md).innerHTML = emoBtn(); $('#ole-emogrid', md).classList.add('hidden');
      return;
    }
    if (b.dataset.m !== 'save') return;
    const nm = $('#ole-name', md).value.trim();
    if (!nm) { toast(tr('Name missing')); $('#ole-name', md).focus(); return; }
    const name = emo === (m0 ? m0[1] : '') && nm === nm0 ? x.name : (x.icon ? '' : emo) + nm, c = $('#ole-col button.on', md)?.dataset.c ?? col0;
    const before = {}, after = {};
    if (name !== x.name) { before.name = x.name; after.name = name; }
    if (c !== col0) { before.color = x.color || ''; after.color = lp_keep(x, c); }
    if (!Object.keys(after).length) { md.remove(); return; }
    const put = v => async () => { const j = await api('PATCH', base, v); redraw(j); await load().catch(() => {}); render(); };
    try { await put(after)(); } catch { return; }  // api() said why
    md.remove();
    offerUndo(tr('Saved'), histAdd({label: tr('Project “{0}” changed', after.name || x.name), undo: put(before), redo: put(after)}));
  });
  md.addEventListener('keydown', (/** @type {any} */ e) => { if (e.key === 'Enter' && e.target.id === 'ole-name') { e.preventDefault(); $('[data-m="save"]', md).click(); } });
  if (!isTouch()) setTimeout(() => $('#ole-name', md).focus(), 50);
  return md;
}
