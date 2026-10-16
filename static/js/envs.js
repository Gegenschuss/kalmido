/* Kalmido web client: Environments of a project (Staging, Live, ...).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.60.0 D (#1514)
// Which milestone / version runs in which environment since when. Shown at the milestone (task panel), in the "Milestones"
// block of the project page (where environments are created, renamed, deleted and the deploy webhook is switched on),
// in the roadmap (a small text at the milestone) and at the milestone's tasks ("Live since 15.10."). The milestones in
// /api/state carry `envs` [{name, since, version}] (where they run NOW), the environment list comes from
// GET /api/lists/<id>/envs. Set by hand (milestone panel), by API (set_deployment) or by the deploy webhook.
const ENV = {d: {}};
const env_day = iso => { const d = new Date(iso); return isNaN(d) ? '' : fmtDateLoc(ds(d)); };
const env_text = e => tr('{0} since {1}', e.name, env_day(e.since));
const env_ms = (lid, mid) => (listById(lid)?.milestones || []).find(m => m.id === mid);
function env_taskNote(t) {  // under "Belongs to" in a task's panel: where its milestone runs
  const es = t.milestone_id ? env_ms(t.list_id, t.milestone_id)?.envs : null;
  return es?.length ? `<div class="muted envnote">${esc(es.map(env_text).join(' · '))}</div>` : '';
}
function env_chipText(t) {  // the milestone chip of a task row
  const es = t.milestone_id ? env_ms(t.list_id, t.milestone_id)?.envs : null;
  return es?.length ? ' · ' + es.map(env_text).join(', ') : '';
}
async function env_load(lid, force) {
  const d = ENV.d[lid] || (ENV.d[lid] = {});
  if (d.busy || (!force && d.j && d.v === S.v)) return;
  d.busy = true;
  try { d.j = await rawFetch('GET', `/api/lists/${lid}/envs`); d.err = ''; }
  catch (e) { if (e.message === 'auth') return; d.err = e instanceof Offline ? 'offline' : e.message; }
  finally { d.busy = false; d.v = S.v; }
  if (routeList()?.id === lid && typeof isOverview === 'function' && isOverview()) viewSafeRender();
  else if (S.sel && S.tasks.get(S.sel)?.list_id === lid) renderDetail();
}
function env_row(e, can) {
  const c = e.current;
  const now = c ? `${esc(c.milestone || c.version)}${c.milestone && c.version && c.version !== c.milestone ? ' (' + esc(c.version) + ')' : ''} <span class="muted">· ${esc(tr('since {0}', env_day(c.at)))}</span>` : `<span class="muted">${esc(tr('Nothing put here yet'))}</span>`;
  return `<div class="envrow"><b class="envn">${esc(e.name)}</b><span class="envnow">${now}</span>${can ? `<button type="button" class="btn sm" data-env="set" data-id="${e.id}">${esc(tr('Put here…'))}</button><button type="button" class="iconbtn" data-env="edit" data-id="${e.id}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit'))}">${ic('edit', 's')}</button>` : ''}</div>`;
}
function env_ovHtml(l, can) {  // inside the "Milestones" block of the project page
  const d = ENV.d[l.id];
  if (!d || (!d.busy && d.v !== S.v)) setTimeout(() => env_load(l.id), 0);
  const j = d?.j;
  if (!j) return d?.err ? '' : `<div class="muted envbox">${esc(tr('Loading…'))}</div>`;
  const rows = j.envs.map(e => env_row(e, can)).join('');
  const sug = can && l.ptype === 'software' ? j.suggest.filter(n => !j.envs.some(e => e.name.toLowerCase() === n.toLowerCase())) : [];
  const add = can && j.envs.length < j.max ? `<div class="envadd">${sug.map(n => `<button type="button" class="btn sm" data-env="add" data-name="${esc(n)}">${ic('plus', 's')}<span>${esc(n)}</span></button>`).join('')}<button type="button" class="btn sm" data-env="add">${ic('plus', 's')}<span>${esc(tr('Add environment'))}</span></button></div>` : '';
  if (!rows && !add) return '';
  return `<div class="envbox" id="pov-envs"><h4>${esc(tr('Environments'))}</h4>${rows || `<div class="muted">${esc(tr('Where does a version run? Add Staging, Live and put milestones there.'))}</div>`}${add}</div>`;
}
// the milestone's own panel: where it runs and, for editors, the buttons to put it on an environment
function env_msHtml(t, rep) {
  const d = ENV.d[t.list_id];
  if (!d || (!d.busy && d.v !== S.v)) setTimeout(() => env_load(t.list_id), 0);
  const envs = d?.j?.envs || [], can = canEditList(t.list_id);
  const on = rep?.envs || [];
  if (!on.length && !envs.length) return '';
  const rows = envs.map(e => {
    const here = on.find(x => x.name === e.name);
    return `<div class="envrow"><b class="envn">${esc(e.name)}</b><span class="envnow">${here ? esc(tr('since {0}', env_day(here.since))) : `<span class="muted">${esc(tr('not here'))}</span>`}</span>${can && !here ? `<button type="button" class="btn sm" data-env="deploy" data-id="${e.id}" data-ms="${t.id}">${esc(tr('Put on {0}', e.name))}</button>` : ''}</div>`;
  }).join('');
  return `<h6>${esc(tr('Environments'))}</h6><div class="envbox">${rows}</div>`;
}
async function env_deploy(eid, body, name) {
  let r;
  try { r = await api('POST', `/api/envs/${eid}/deploy`, body); } catch { return; }
  histAdd({label: tr('Put on {0}', name),
    undo: async () => { await api('DELETE', `/api/envs/${eid}/deploys/${r.id}`); env_refresh(); },
    redo: async () => { r = await api('POST', `/api/envs/${eid}/deploy`, body); env_refresh(); }});
  toast(r.closed?.length ? tr('Put on {0}; {1} tasks completed', name, r.closed.length) : tr('Put on {0}', name));
  env_refresh();
}
async function env_refresh() {
  S.msr = null;
  for (const k of Object.keys(ENV.d)) ENV.d[k].v = -1;
  try { await load(); } catch { /* offline */ }
  render();
}
function env_setModal(l, e) {
  const ms = msOfList(l.id);
  const md = modal(`<h3>${esc(tr('Put on {0}', e.name))}</h3>
    <div class="row"><label for="env-ms">${tr('Milestone')}</label><select id="env-ms"><option value="">${esc(tr('None (version only)'))}</option>${ms.map(m => `<option value="${m.id}">${esc(m.title)}</option>`).join('')}</select></div>
    <div class="row"><label for="env-ver">${tr('Version')}</label><input id="env-ver" maxlength="100" placeholder="${esc(tr('e.g. 2.60.0'))}" autocomplete="off"></div>
    <p class="muted">${esc(tr('The time is now. Without a milestone the version is found by the milestone titles.'))}</p>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async ev => {
    const b = ev.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const mid = +$('#env-ms', md).value || null, ver = $('#env-ver', md).value.trim();
    if (!mid && !ver) { toast(tr('Pick a milestone or enter a version')); return; }
    md.remove();
    await env_deploy(e.id, {...(mid ? {milestone_id: mid} : {}), ...(ver ? {version: ver} : {})}, e.name);
  });
}
function env_editModal(l, e, j) {
  const md = modal(`<h3>${esc(tr('Environment'))}</h3>
    <div class="row"><label for="env-name">${tr('Name')}</label><input id="env-name" maxlength="40" value="${esc(e?.name || '')}" placeholder="${esc(tr('e.g. Staging'))}" autocomplete="off"></div>
    <div class="row"><label class="chkl"><input type="checkbox" id="env-close" ${e?.auto_close ? 'checked' : ''}> <span>${esc(tr('Complete the open tasks of a milestone when it arrives here'))}</span></label></div>
    ${e && j.manage ? `<div class="row envhook"><label>${esc(tr('Deploy webhook'))}</label><div><span class="muted">${esc(e.hook ? tr('On: your deploy script posts the version to a secret address.') : tr('Off'))}</span>
      <div class="envhb"><button type="button" class="btn sm" data-m="hook" data-how="${e.hook ? 'rotate' : 'on'}">${esc(e.hook ? tr('New address') : tr('Switch on'))}</button>${e.hook ? `<button type="button" class="btn sm" data-m="hook" data-how="off">${esc(tr('Switch off'))}</button>` : ''}</div>
      <div id="env-url"></div></div></div>` : ''}
    <div class="foot">${e ? `<button class="btn danger" data-m="del">${tr('Remove')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async ev => {
    const b = ev.target.closest('[data-m]'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { md.remove(); return; }
    try {
      if (m === 'hook') {
        const r = await api('PATCH', `/api/envs/${e.id}`, {hook: b.dataset.how});
        $('#env-url', md).innerHTML = r.url ? `<p class="muted">${esc(tr('Shown only once. POST {"version": "2.60.0"} to it.'))}</p><input readonly id="env-urlin" value="${esc(r.url)}" aria-label="${esc(tr('Deploy webhook'))}"><button type="button" class="btn sm" data-m="copy">${ic('copy', 's')}<span>${tr('Copy')}</span></button>` : '';
        env_load(l.id, true); return;
      }
      if (m === 'copy') { try { await navigator.clipboard.writeText($('#env-urlin', md).value); toast(tr('Copied')); } catch { toast(tr('Copy failed')); } return; }
      if (m === 'del') {
        await api('DELETE', `/api/envs/${e.id}`); md.remove();
        histAdd({label: tr('Environment removed'), undo: async () => { await api('POST', `/api/envs/${e.id}/restore`); env_load(l.id, true); },
          redo: async () => { await api('DELETE', `/api/envs/${e.id}`); env_load(l.id, true); }});
        env_load(l.id, true); toast(tr('Environment removed')); return;
      }
      const name = $('#env-name', md).value.trim(), ac = $('#env-close', md).checked;
      if (!name) { toast(tr('Enter a name')); return; }
      if (e) {
        const before = {name: e.name, auto_close: e.auto_close};
        await api('PATCH', `/api/envs/${e.id}`, {name, auto_close: ac});
        const put = x => async () => { await api('PATCH', `/api/envs/${e.id}`, x); env_load(l.id, true); };
        histAdd({label: tr('Environment changed'), undo: put(before), redo: put({name, auto_close: ac})});
      } else {
        let r = await api('POST', `/api/lists/${l.id}/envs`, {name, auto_close: ac});
        histAdd({label: tr('Environment added'), undo: async () => { await api('DELETE', `/api/envs/${r.id}`); env_load(l.id, true); },
          redo: async () => { await api('POST', `/api/envs/${r.id}/restore`); env_load(l.id, true); }});
      }
      md.remove(); env_load(l.id, true);
    } catch { /* api() said it */ }
  });
  if (!isMobile()) setTimeout(() => $('#env-name', md)?.focus(), 30);
}
document.addEventListener('click', async ev => {
  const b = ev.target.closest('[data-env]'); if (!b) return;
  const id = +b.dataset.id, l = routeList(), tl = S.sel ? listById(S.tasks.get(S.sel)?.list_id) : null;
  const lst = b.dataset.env === 'deploy' ? tl : (l || tl);
  const j = ENV.d[lst?.id]?.j, e = j?.envs.find(x => x.id === id);
  switch (b.dataset.env) {
    case 'add': if (lst && j) { env_editModal(lst, null, j); if (b.dataset.name) $('#env-name').value = b.dataset.name; } break;
    case 'edit': if (e) env_editModal(lst, e, j); break;
    case 'set': if (e) env_setModal(lst, e); break;
    case 'deploy': if (e) env_deploy(e.id, {milestone_id: +b.dataset.ms}, e.name); break;
  }
});
