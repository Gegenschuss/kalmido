// @ts-check
// 2.124.0 C (#2113): one table shared with single people or agents (read | write), loaded with the tables (lazyload.js).
// The sheet's "…" menu gets "Share…" for who may change the table through its workspace (can_share from the server); the
// dialog is built like the file store's Share dialog (ablage.js ab_share): the shares with a role each and a cross, "Share
// with …" (people of the workspace, its agents), by e-mail address (the answer never tells whether the address has an
// account). Every add / stop / role change is one Undo step. The overview shows "Shared" on a table with shares and puts
// the tables shared with me into their own group (sheets.js shvOverview).
const shs$ = (s, r) => /** @type {any} */ ((r || document).querySelector(s));
const shsUrl = (sid, shid) => `/api/sheets/${sid}/shares${shid ? '/' + shid : ''}`;
async function shsReq(m, url, b) { try { return await api(m, url, b); } catch { return null; } }
function shsAfter(sid) { shvAfterIdx(sid); if (SHV.sh?.id === sid) shvLoad(sid, true); }

async function shsOpen(sh) {
  const sid = sh.book_id || sh.id;  // 2.124.0 E (#2116): the shares of the whole table (its first sheet)
  let d; try { d = await api('GET', shsUrl(sid)); } catch { return; }
  shs$('.shsdlg')?.remove();
  const roleSel = (attr, cur) => `<select ${attr} aria-label="${esc(tr('Role'))}"><option value="read" ${cur === 'read' ? 'selected' : ''}>${tr('Can view')}</option><option value="write" ${cur === 'write' ? 'selected' : ''}>${tr('Can edit')}</option></select>`;
  const title = sh.title || tr('Untitled table');
  const md = modal(`<div class="lhdr"><h3>${esc(tr('Share “{0}”', title))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="shint lhint keep">${tr('Only this table is shared, not the rest of the workspace or the attached list.')} ${tr('Agents see exactly what is shared with them, nothing else; every access shows up in the history.')}</div>
    <div class="shws">${esc(sh.space && sh.space !== 'private' ? shvSpaceName(sh.space) : tr('Private|workspace'))} <small class="muted">${esc(tr('Only people and agents of this workspace'))}</small></div>
    <div id="shs-list" class="members"></div>
    <div class="abshadd shsadd">
      <select id="shs-t" aria-label="${esc(tr('Share with …'))}"><option value="">${tr('Share with …')}</option>
        ${d.people.length ? `<optgroup label="${esc(tr('People'))}">${d.people.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</optgroup>` : ''}
        ${d.agents.length ? `<optgroup label="${esc(tr('Agents'))}">${d.agents.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</optgroup>` : ''}</select>
      ${roleSel('id="shs-r"', 'read')}
      <button type="button" class="btn sm" data-shs="add">${ic('plus', 's')} ${tr('Add')}</button></div>
    <div class="row shmail"><input id="shs-mail" type="email" autocomplete="off" placeholder="${esc(tr('Share by e-mail address'))}" aria-label="${esc(tr('Share by e-mail address'))}"><button type="button" class="btn sm" data-shs="mail">${ic('send', 's')} ${tr('Add')}</button></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('shmodal', 'shsdlg');
  let shares = d.shares || [];
  const draw = () => {
    const box = shs$('#shs-list', md); if (!box) return;
    box.innerHTML = shares.map(s => `<div class="mrow" data-sid="${s.id}">${av(s.user_id, s.name)}<span class="n">${esc(s.name)}${s.agent ? agentBadge() : ''}</span>${roleSel(`data-shsr="${s.id}"`, s.role)}<button class="iconbtn" data-shsx="${s.id}" title="${esc(tr('Stop sharing'))}" aria-label="${esc(tr('Stop sharing with {0}', s.name))}">${ic('x', 's')}</button></div>`).join('')
      || `<div class="muted mhint">${tr('Not shared yet')}</div>`;
  };
  draw();
  const add = async b => { const r = await api('POST', shsUrl(sid), b); shares = r.shares || shares; draw(); shsAfter(sid); return r; };  // 2.148.1 A (#2490): by address no list
  const idOf = uid => (shares.find(q => q.user_id === uid) || {}).id;
  md.addEventListener('click', async e => {
    const t = /** @type {any} */ (e.target);
    if (t.closest('[data-m="close"]')) { modalClose(md); return; }
    if (t.closest('[data-shs="add"]')) {
      const sel = shs$('#shs-t', md), uid = +sel.value, role = shs$('#shs-r', md).value;
      if (!uid) { sel.focus(); return; }
      try { await add({user_id: uid, role}); } catch { return; }
      const nm = sel.selectedOptions[0]?.textContent || '';
      sel.value = '';
      offerUndo(tr('Shared with {0}', nm), histAdd({label: tr('Share “{0}”', title),
        undo: async () => { const i = idOf(uid); if (i) await shsReq('DELETE', shsUrl(sid, i)); shsAfter(sid); return {}; },
        redo: async () => { await shsReq('POST', shsUrl(sid), {user_id: uid, role}); shsAfter(sid); return {}; }}));
      return;
    }
    if (t.closest('[data-shs="mail"]')) {
      const inp = shs$('#shs-mail', md), email = inp.value.trim(), role = shs$('#shs-r', md).value;
      if (!email || !inp.checkValidity()) { inp.focus(); return; }
      try { await add({email, role}); } catch { return; }
      inp.value = '';
      toast(tr('If the address belongs to a person who can get the table, it is shared with them now.'));
      return;
    }
    const x = t.closest('[data-shsx]');
    if (x) {
      const s = shares.find(q => q.id === +x.dataset.shsx); if (!s) return;
      let r; try { r = await api('DELETE', shsUrl(sid, s.id)); } catch { return; }
      shares = r.shares; draw(); shsAfter(sid);
      offerUndo(tr('No longer shared with {0}', s.name), histAdd({label: tr('Stop sharing “{0}”', title),
        undo: async () => { await shsReq('POST', shsUrl(sid), {user_id: s.user_id, role: s.role}); shsAfter(sid); return {}; },
        redo: async () => { await shsReq('DELETE', shsUrl(sid, s.id)); shsAfter(sid); return {}; }}));
    }
  });
  md.addEventListener('change', async e => {
    const r = /** @type {any} */ (e.target).closest('[data-shsr]'); if (!r) return;
    const s = shares.find(q => q.id === +r.dataset.shsr), was = s?.role, to = r.value;
    try { shares = (await api('PATCH', shsUrl(sid, r.dataset.shsr), {role: to})).shares; } catch { return; }
    draw(); shsAfter(sid);
    offerUndo(tr('Role changed'), histAdd({label: tr('Role in “{0}”', title),
      undo: async () => { await shsReq('PATCH', shsUrl(sid, r.dataset.shsr), {role: was}); shsAfter(sid); return {}; },
      redo: async () => { await shsReq('PATCH', shsUrl(sid, r.dataset.shsr), {role: to}); shsAfter(sid); return {}; }}));
  });
}
SHV_HOOKS.menu.push(sh => sh?.can_share && S.me?.kind !== 'agent' ? [{label: tr('Share…'), icon: 'users', fn: () => shsOpen(sh)}] : []);
