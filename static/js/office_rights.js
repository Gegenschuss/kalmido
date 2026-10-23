// @ts-check
// 2.187.0 A (#2476): the page "Rights" of the office's settings (office/rights, the tab next to General | Templates).
// A person who manages the office rights (org admin, personal office owner, a group with the special "rights") sees three
// sections: People (the groups of every member and agent, saved at once), Groups (the fixed templates to copy, the own
// groups: a level per area grouped like the office menu + the specials, every change saves itself) and Log (who changed
// what for whom, before -> after). Everybody else sees "My rights" (read only). The server checks every change
// (kalmido/office/rights.py: nobody hands out more than they have, admins are fixed, agents never manage rights).
'use strict';

const ORR = {data: null, err: null, oid: null, log: null, logErr: null, logBusy: false, open: new Set(), busy: false};
const ORR_SUBS = [['people', 'users', N_('People')], ['groups', 'shield', N_('Groups|rights')], ['log', 'clock', N_('Log|rights')]];
const ORR_LV = {none: N_('No access'), own: N_('Own entries only'), view: N_('View|rights'), edit: N_('Edit|rights'), manage: N_('Manage|rights')};
const orr_lvName = lv => tr(ORR_LV[lv] || lv);
const orr_sub = () => { const k = LS.get('orrSub', 'people'); return ORR_SUBS.some(x => x[0] === k) ? k : 'people'; };

async function orr_load() {
  ORR.busy = true;
  const oid = OFC.info?.org_id;
  try { const j = await api('GET', '/api/office/rights'); if (oid === OFC.info?.org_id) { ORR.data = j; ORR.err = null; } }
  catch (x) { ORR.err = x.message || tr('unknown'); }
  ORR.busy = false;
  ofcDraw();
}
async function orr_logLoad() {
  ORR.logBusy = true;
  try { const j = await api('GET', '/api/office/rights/log'); ORR.log = j.items || []; ORR.logErr = null; }
  catch (x) { ORR.logErr = x.message || tr('unknown'); }
  ORR.logBusy = false;
  ofcDraw();
}
const orr_reset = () => { ORR.data = null; ORR.log = null; ORR.err = null; ORR.logErr = null; };

function orr_html() {
  if (ORR.oid !== OFC.info?.org_id) { ORR.oid = OFC.info?.org_id; orr_reset(); ORR.open.clear(); }
  if (ORR.err) return `<div class="empty">${esc(ORR.err)}</div>`;
  if (!ORR.data) { if (!ORR.busy) { ORR.busy = true; setTimeout(orr_load, 0); } return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = ORR.data, mg = d.mine?.manager;
  if (!mg) return `<div class="orr">${orr_mineHtml(d)}</div>`;
  const hint = d.personal ? tr('Here you are your own admin. Give your agents a group so they reach the office.')
    : tr('Org admins always see everything. Members without a group keep their previous access.');
  const cur = orr_sub();
  const subs = `<div class="seg aisub orrsub" role="tablist" aria-label="${esc(tr('Sections'))}">${ORR_SUBS.map(([k, i, n]) => `<button type="button" role="tab" data-orr="sub" data-k="${k}" aria-selected="${k === cur}" class="${k === cur ? 'on' : ''}">${ic(i, 's')}<span>${esc(tr(n))}</span></button>`).join('')}</div>`;
  const body = cur === 'groups' ? orr_groupsHtml(d) : cur === 'log' ? orr_logHtml(d) : orr_peopleHtml(d);
  return `<div class="orr"><p class="muted orr-hint">${ic('shield', 's')}<span>${esc(hint)}</span></p>${subs}<div class="orr-sec" role="tabpanel">${body}</div></div>`;
}

// ---- names of the groups (templates + own groups)
const orr_all = d => [...(d.templates || []), ...(d.groups || [])];
const orr_refName = (d, ref) => orr_all(d).find(x => x.ref === ref)?.name || tr('Deleted group');

// ---- People
function orr_peopleHtml(d) {
  const ps = d.people || [];
  if (!ps.length) return `<p class="muted">${tr('Nobody here yet.')}</p>`;
  return `<ul class="orr-people" role="list">${ps.map(p => orr_personHtml(d, p)).join('')}</ul>`;
}
function orr_personHtml(d, p) {
  const tag = p.agent ? `<span class="orr-tag">${ic('bot', 's')}${tr('Agent')}</span>` : p.role === 'admin' ? `<span class="orr-tag">${tr('Admin|role')}</span>` : '';
  const head = `<span class="orr-pn">${ic(p.agent ? 'bot' : 'user')}<b>${esc(p.name)}</b>${tag}</span>`;
  const names = (p.groups || []).map(r => orr_refName(d, r)).join(', ');
  if (p.fixed) return `<li class="orr-p">${head}<span class="orr-fixed muted">${esc(tr('Organisation admin, always sees everything'))}</span></li>`;
  if (!p.can_edit) return `<li class="orr-p">${head}<span class="orr-fixed"><span>${esc(names)}</span><small class="muted">${esc(p.id === S.me?.id ? tr('You cannot change your own office rights') : tr('Has more rights than you can hand out'))}</small></span></li>`;
  const opts = orr_all(d).filter(g => g.can_give || (p.groups || []).includes(g.ref)).filter(g => !(p.agent && g.key === 'legacy'))
    .map(g => `<label class="chkl"><input type="checkbox" data-orr="pg" data-pid="${p.id}" value="${esc(g.ref)}" ${(p.groups || []).includes(g.ref) ? 'checked' : ''}><span>${esc(g.name)}</span></label>`).join('');
  const k = 'p:' + p.id;
  return `<li class="orr-p">${head}<details class="orr-pick" data-orr-open="${k}" ${ORR.open.has(k) ? 'open' : ''}><summary><span>${esc(names)}</span>${ic('chev', 's')}</summary><div class="orr-opts" role="group" aria-label="${esc(tr('Groups of {0}', p.name))}">${opts}</div></details></li>`;
}
async function orr_personSave(el) {
  const box = el.closest('.orr-opts'), pid = +el.dataset.pid, ref = el.value; if (!box) return;
  const all = /** @type {HTMLInputElement[]} */ ($$('input[data-orr="pg"]', box));
  const solo = r => r === 'tpl:legacy' || r === 'tpl:none';  // "Previous access" / "No office access" stand alone
  if (el.checked) all.forEach(x => { if (x !== el && (solo(ref) || solo(x.value))) x.checked = false; });
  const refs = all.filter(x => x.checked).map(x => x.value);
  ORR.open.add('p:' + pid);
  try { await api('PUT', `/api/office/rights/people/${pid}`, {groups: refs}); toast(tr('Saved')); ORR.log = null; }
  catch (x) { toast(x.message || tr('unknown')); }
  await orr_load();
}

// ---- Groups
function orr_matrixHtml(d, g, edit) {
  const caps = d.caps?.levels || {}, cs = d.caps?.specials || [], dis = edit ? '' : 'disabled';
  const areas = d.areas || [];
  const sel = a => {
    const lvs = (d.levels || []).filter(l => l !== 'own' || a.own);
    const capI = (d.levels || []).indexOf(caps[a.key] || 'none');
    return `<select data-orr="lv" data-gid="${g.id || ''}" data-area="${esc(a.key)}" aria-label="${esc(a.name)}" ${dis}>${lvs.map(l => `<option value="${l}" ${(g.levels || {})[a.key] === l ? 'selected' : ''} ${edit && (d.levels || []).indexOf(l) > capI ? 'disabled' : ''}>${esc(orr_lvName(l))}</option>`).join('')}</select>`;
  };
  const grp = OFM_GROUPS.map(mg => { const as = areas.filter(a => a.group === mg[0]); return as.length ? `<div class="orr-mg"><h4>${esc(tr(mg[2]))}</h4>${as.map(a => `<label class="orr-row"><span>${esc(a.name)}</span>${sel(a)}</label>`).join('')}</div>` : ''; }).join('');
  const sp = (d.specials || []).map(s => `<label class="chkl"><input type="checkbox" data-orr="sp" data-gid="${g.id || ''}" value="${esc(s.key)}" ${(g.specials || []).includes(s.key) ? 'checked' : ''} ${edit && cs.includes(s.key) ? '' : 'disabled'}><span>${esc(s.name)}</span></label>`).join('');
  return `<div class="orr-matrix">${grp}</div><div class="orr-sp"><h4>${tr('Special rights')}</h4>${sp}</div>`;
}
function orr_groupsHtml(d) {
  const tpl = (d.templates || []).map(t => {
    const k = t.ref, copy = t.can_give && t.key !== 'legacy' ? `<button type="button" class="btn sm" data-orr="copy" data-ref="${esc(t.ref)}">${ic('copy', 's')}<span>${tr('Copy')}</span></button>` : '';
    const inner = t.levels ? orr_matrixHtml(d, t, false) : `<p class="muted">${esc(t.hint)}</p>`;
    return `<li><details class="orr-g" data-orr-open="${k}" ${ORR.open.has(k) ? 'open' : ''}><summary><span class="ofcn"><b>${esc(t.name)}</b><small class="muted">${esc(t.hint)}</small></span>${ic('chev', 's')}</summary><div class="orr-gb">${copy ? `<div class="orr-act">${copy}</div>` : ''}${inner}</div></details></li>`;
  }).join('');
  const own = (d.groups || []).map(g => {
    const k = g.ref, edit = !!g.can_edit && !!g.can_give;
    const why = !g.can_edit ? tr('You are in this group yourself: another person who manages the rights changes it') : !g.can_give ? tr('This group has more rights than you can hand out') : '';
    return `<li><details class="orr-g" data-orr-open="${k}" ${ORR.open.has(k) ? 'open' : ''}><summary><span class="ofcn"><b>${esc(g.name)}</b><small class="muted">${esc(orr_sumLine(d, g))}</small></span>${ic('chev', 's')}</summary><div class="orr-gb">
      ${why ? `<p class="muted orr-why">${ic('lock', 's')}<span>${esc(why)}</span></p>` : ''}
      <div class="row"><label for="orr-n-${g.id}">${tr('Name')}</label><input id="orr-n-${g.id}" data-orr="name" data-gid="${g.id}" value="${esc(g.name)}" maxlength="80" ${edit ? '' : 'disabled'}></div>
      ${orr_matrixHtml(d, g, edit)}
      ${edit ? `<div class="orr-act"><button type="button" class="btn sm danger" data-orr="del" data-gid="${g.id}">${ic('trash', 's')}<span>${tr('Delete group')}</span></button></div>` : ''}</div></details></li>`;
  }).join('');
  return `<h3>${tr('Own groups')}</h3>${own ? `<ul class="orr-gl" role="list">${own}</ul>` : `<p class="muted">${tr('No own group yet. Copy a template to adjust it.')}</p>`}
    <h3>${tr('Templates')}</h3><ul class="orr-gl" role="list">${tpl}</ul>`;
}
// "Bank: View · Receipts: Own entries only …" in short: how many areas per level
function orr_sumLine(d, g) {
  const n = {}; for (const a of d.areas || []) { const l = (g.levels || {})[a.key] || 'none'; if (l !== 'none') n[l] = (n[l] || 0) + 1; }
  const parts = ['manage', 'edit', 'view', 'own'].filter(l => n[l]).map(l => `${orr_lvName(l)}: ${n[l]}`);
  return parts.length ? parts.join(' · ') : orr_lvName('none');
}
async function orr_groupPatch(gid, b) {
  ORR.open.add('g:' + gid);
  try { await api('PATCH', `/api/office/rights/groups/${gid}`, b); toast(tr('Saved')); ORR.log = null; }
  catch (x) { toast(x.message || tr('unknown')); }
  await orr_load();
}
async function orr_copy(ref) {
  try { const j = await api('POST', '/api/office/rights/groups', {from: ref}); ORR.open.add(j.ref); toast(tr('Group “{0}” created', j.name)); ORR.log = null; }
  catch (x) { toast(x.message || tr('unknown')); }
  await orr_load();
}
async function orr_del(gid) {
  const g = (ORR.data?.groups || []).find(x => x.id === gid); if (!g) return;
  if (!await askConfirm(tr('Delete the group “{0}”?', g.name), tr('Its members keep their other groups; without one they have no office access.'), {ok: tr('Delete'), danger: true})) return;
  try { await api('DELETE', `/api/office/rights/groups/${gid}`); toast(tr('Deleted')); ORR.log = null; }
  catch (x) { toast(x.message || tr('unknown')); }
  await orr_load();
}

// ---- Log
const ORR_ACT = {member_groups: N_('changed the groups of {0}'), group_create: N_('created the group {0}'), group_change: N_('changed the group {0}'), group_delete: N_('deleted the group {0}')};
function orr_logHtml(d) {
  if (ORR.logErr) return `<div class="empty">${esc(ORR.logErr)}</div>`;
  if (!ORR.log) { if (!ORR.logBusy) { ORR.logBusy = true; setTimeout(orr_logLoad, 0); } return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (!ORR.log.length) return `<p class="muted">${tr('No change of the office rights yet.')}</p>`;
  const when = iso => typeof ofdWhen === 'function' ? ofdWhen(iso) : iso;
  return `<ul class="orr-log" role="list">${ORR.log.map(x => {
    const gname = x.after?.name || x.before?.name || (x.group ? orr_refName(d, x.group) : '');
    const what = tr(ORR_ACT[x.action] || x.action, x.action === 'member_groups' ? x.user_name || '?' : gname);
    const lines = orr_logLines(d, x);
    return `<li><details class="orr-le" data-orr-open="l:${x.id}" ${ORR.open.has('l:' + x.id) ? 'open' : ''}><summary><span class="muted">${esc(when(x.at))}</span> <b>${esc(x.by_name || '?')}</b> <span>${esc(what)}</span></summary>${lines.length ? `<ul class="orr-ld" role="list">${lines.map(l => `<li>${esc(l)}</li>`).join('')}</ul>` : ''}</details></li>`;
  }).join('')}</ul>`;
}
function orr_logLines(d, x) {
  const an = k => (d.areas || []).find(a => a.key === k)?.name || k, sn = k => (d.specials || []).find(s => s.key === k)?.name || k;
  const arrow = (a, b) => tr('{0} → {1}', a, b);
  if (x.action === 'member_groups') return [arrow((x.before || []).map(r => orr_refName(d, r)).join(', ') || tr('Previous access'), (x.after || []).map(r => orr_refName(d, r)).join(', '))];
  const b = x.before || {}, a = x.after || {}, out = [];
  if (x.action === 'group_change' && b.name !== a.name) out.push(`${tr('Name')}: ${arrow(b.name || '', a.name || '')}`);
  for (const ar of d.areas || []) {
    const lb = (b.levels || {})[ar.key] || 'none', la = (a.levels || {})[ar.key] || 'none';
    if (x.action === 'group_change' ? lb !== la : (x.action === 'group_create' ? la : lb) !== 'none') out.push(`${an(ar.key)}: ${x.action === 'group_change' ? arrow(orr_lvName(lb), orr_lvName(la)) : orr_lvName(x.action === 'group_create' ? la : lb)}`);
  }
  const sb = b.specials || [], sa = a.specials || [];
  for (const s of sa) if (!sb.includes(s)) out.push(tr('+ {0}', sn(s)));
  for (const s of sb) if (!sa.includes(s) && x.action !== 'group_delete') out.push(tr('− {0}', sn(s)));
  return out;
}

// ---- My rights (everybody who does not manage the rights)
function orr_mineHtml(d) {
  const m = d.mine || {}, sp = m.specials || [];
  const rows = OFM_GROUPS.map(mg => { const as = (d.areas || []).filter(a => a.group === mg[0]); return as.length ? `<div class="orr-mg"><h4>${esc(tr(mg[2]))}</h4>${as.map(a => `<div class="orr-row"><span>${esc(a.name)}</span><b class="orr-lv lv-${esc(m.levels?.[a.key] || 'none')}">${esc(orr_lvName(m.levels?.[a.key] || 'none'))}</b></div>`).join('')}</div>` : ''; }).join('');
  const sps = (d.specials || []).map(s => `<li>${ic(sp.includes(s.key) ? 'check' : 'x', 's')}<span${sp.includes(s.key) ? '' : ' class="muted"'}>${esc(s.name)}</span></li>`).join('');
  return `<h3>${tr('My rights')}</h3><p class="muted orr-hint">${ic('shield', 's')}<span>${esc(m.legacy ? tr('You have the previous access of your organisation role. A person who manages the office rights can change it.') : tr('Your office rights come from your groups. A person who manages the office rights can change them.'))}</span></p>
    <div class="orr-matrix">${rows}</div><div class="orr-sp"><h4>${tr('Special rights')}</h4><ul class="orr-spl" role="list">${sps}</ul></div>`;
}

// ---- events
document.addEventListener('click', e => {
  const t = /** @type {HTMLElement} */ (e.target);
  for (const p of $$('.orr-pick[open]')) if (!p.contains(t)) /** @type {HTMLDetailsElement} */ (p).open = false;  // the group picker closes like a menu
  const b = /** @type {HTMLElement|null} */ (t.closest?.('[data-orr]'));
  if (!b || b.tagName === 'INPUT' || b.tagName === 'SELECT') return;
  const k = b.dataset.orr;
  if (k === 'sub') { LS.set('orrSub', b.dataset.k); ofcDraw(); }
  else if (k === 'copy') orr_copy(b.dataset.ref || '');
  else if (k === 'del') orr_del(+(b.dataset.gid || 0));
  else return;
  e.preventDefault();
});
document.addEventListener('change', e => {
  const el = /** @type {HTMLInputElement} */ (e.target); if (!el.closest?.('.orr')) return;
  const k = el.dataset.orr, gid = +(el.dataset.gid || 0);
  if (k === 'pg') orr_personSave(el);
  else if (k === 'lv' && gid) orr_groupPatch(gid, {levels: {[el.dataset.area || '']: el.value}});
  else if (k === 'sp' && gid) orr_groupPatch(gid, {specials: $$(`input[data-orr="sp"][data-gid="${gid}"]`).filter(x => /** @type {HTMLInputElement} */ (x).checked).map(x => /** @type {HTMLInputElement} */ (x).value)});
  else if (k === 'name' && gid) { if (el.value.trim()) orr_groupPatch(gid, {name: el.value.trim()}); else { el.value = (ORR.data?.groups || []).find(x => x.id === gid)?.name || ''; } }
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const p = /** @type {HTMLDetailsElement|null} */ ((/** @type {HTMLElement} */ (e.target)).closest?.('.orr-pick[open]')); if (!p) return;
  p.open = false; /** @type {HTMLElement|null} */ (p.querySelector('summary'))?.focus(); e.stopPropagation();
});
// the open sections stay open after a save (the page is drawn again)
document.addEventListener('toggle', e => {
  const el = /** @type {HTMLDetailsElement} */ (e.target); const k = el?.dataset?.orrOpen; if (!k) return;
  if (el.open) ORR.open.add(k); else ORR.open.delete(k);
}, true);
// another workspace / a change of my own groups: read again on the next look
document.addEventListener('visibilitychange', () => { if (!document.hidden && S.route.mod === 'office' && S.route.tab === 'rights' && ORR.data) orr_load(); });
