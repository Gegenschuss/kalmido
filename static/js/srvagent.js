// @ts-check
// 2.557.0 C (#4670): the setup of a server agent ("Kalmido AI"): it runs on the Kalmido server with the person's own API key of
// a model provider, no computer of one's own. A normal agent (provider "kalmido-server") + its server settings
// (GET / PUT /api/agents/<id>/server, the models live from the provider, the latest runs) + the starter pack
// (POST /api/agents/<id>/server/starter, kalmido/agents/srvstarter.py). The dialog "New agent" asks for the defaults first
// (GET /api/agents/server/defaults: the agent has no id yet). The key is a password field and comes back only as its last
// four characters ("…abcd"): replace or delete it. Lazy module "agentchat" (lazyload.js).
const SRV_PROV = 'kalmido-server';
// the five items of the starter pack (all only propose; decision 05.11.2026, card 12870): [key, label, hint]
const SRV_ST = [['briefing', N_('Morning briefing at 07:30'), N_('Daily in its chat, read-only: due, overdue, untouched, waiting on someone.')],
  ['tidy', N_('Tidy up the basket'), N_('Project, due date, priority and tags as a proposal.')],
  ['docs', N_('Sort receipts and documents'), N_('Sender, type and tags suggested from the recognised text.')],
  ['meetings', N_('Meeting notes into task proposals'), N_('Notes become a proposal “Tasks from notes”, never tasks directly.')],
  ['followup', N_('Follow up on “Waiting on someone”'), N_('A drafted follow-up as a comment, posted only after your Yes.')],
  // 2.568.0 (#4673): off by default; it grants no office rights itself (skipped with the reason until the agent has them)
  ['office', N_('Due billing on Mondays at 08:00'), N_('Open time and due invoices as a reminder; invoice drafts only after your Yes, never finalised or sent. Needs the agent’s office rights (“Office drafts”, “May draft office documents”).')]];
// 2.565.0 D (#4674): the routines that may run with a model of their own (srvstarter.py SRV_FLOWS; '' = the agent's model)
const SRV_FLOW_KEYS = ['briefing', 'tidy', 'meetings', 'followup'];
const srv_flowName = k => tr((SRV_ST.find(x => x[0] === k) || [])[1] || k);
function srv_flowsHtml(j) {
  const fm = j.flow_models || {};
  return `<fieldset class="srvflows"><legend>${tr('Model per routine')}</legend>
    <div class="shint keep">${esc(tr('A routine of the starter pack can use a model of its own, e.g. a cheaper one for the briefing. Empty = the agent’s model.'))}</div>
    ${SRV_FLOW_KEYS.map(k => `<div class="row"><label for="srv-fm-${k}">${esc(srv_flowName(k))}</label><select id="srv-fm-${k}" data-srv-fm="${k}" data-was="${esc(fm[k] || '')}"><option value="">${esc(tr('Like the agent'))}</option>${fm[k] ? `<option value="${esc(fm[k])}" selected>${esc(fm[k])}</option>` : ''}</select></div>`).join('')}</fieldset>`;
}
// the routine choices from the same live model list as the agent's model (srv_modelsFill)
function srv_flowsFill(md, j) {
  const ms = j?.models || []; if (!ms.length) return;
  for (const sel of $$('[data-srv-fm]', md)) {
    const cur = sel.dataset.was || '';
    sel.innerHTML = `<option value="">${esc(tr('Like the agent'))}</option>` + (cur && !ms.some(m => m.id === cur) ? `<option value="${esc(cur)}">${esc(cur)}</option>` : '')
      + ms.map(m => `<option value="${esc(m.id)}" ${m.id === cur ? 'selected' : ''}>${esc(m.name || m.id)}</option>`).join('');
  }
}
// only the routines whose choice changed (an unchanged one is not checked against the list again); null = none changed
function srv_flowsBody(md) {
  /** @type {Record<string, string>} */ const out = {};
  for (const sel of $$('[data-srv-fm]', md)) if (sel.value !== (sel.dataset.was || '')) out[sel.dataset.srvFm] = sel.value;
  return Object.keys(out).length ? out : null;
}
// 2.571.0 D (#4676): read-only web research per routine (srvweb.py SRV_WEB_KEYS: the routines + "other"), default off
const SRV_WEB_KEYS = [...SRV_FLOW_KEYS, 'other'];
const srv_webName = k => k === 'other' ? tr('Everything else (chat, mentions, tasks)') : srv_flowName(k);
function srv_webHtml(j) {
  const fw = j.flow_web || {};
  return `<fieldset class="srvweb"><legend>${tr('Web research per routine')}</legend>
    <div class="shint keep">${esc(tr('Read-only: search the web, read a page, check a VAT number with the EU service VIES. Off by default. A run with the web never sends forms; every change and every message to someone else then waits for your approval, and each web find names its source.'))}</div>
    ${SRV_WEB_KEYS.map(k => `<label class="chkl"><input type="checkbox" data-srv-web="${k}" data-was="${fw[k] ? 1 : 0}" ${fw[k] ? 'checked' : ''}><span>${esc(srv_webName(k))}</span></label>`).join('')}</fieldset>`;
}
// only the switches that changed; null = none
function srv_webBody(md) {
  /** @type {Record<string, boolean>} */ const out = {};
  for (const x of $$('[data-srv-web]', md)) if (x.checked !== (x.dataset.was === '1')) out[x.dataset.srvWeb] = x.checked;
  return Object.keys(out).length ? out : null;
}
let srv_def = null;
async function srv_defaults(fresh) {
  if (!srv_def || fresh) srv_def = await api('GET', '/api/agents/server/defaults');
  return srv_def;
}
const srv_is = a => !!a && a.provider === SRV_PROV;
const srv_offHtml = () => `<div class="shint keep srvoff" role="note">${ic('alert', 's')} ${esc(tr('Agents on the Kalmido server are switched off on this server (an admin can allow them: Settings > Organisation > Agents).'))}</div>`;
// the fields both dialogs share: provider, key, model, instructions (j = GET …/server or the defaults)
function srv_fieldsHtml(j, isNew) {
  const keyRow = !isNew && j.has_key
    ? `<div class="row"><label>${tr('API key')}</label><code class="srvkey" id="srv-keyhint">${esc(j.key_hint || '')}</code><button type="button" class="btn sm" data-srv="rep">${tr('Replace')}</button><button type="button" class="btn sm danger" data-srv="delkey">${tr('Delete')}</button></div>
      <div class="row" id="srv-keyrow" hidden><label for="srv-key">${tr('New API key')}</label><input id="srv-key" type="password" autocomplete="off" spellcheck="false" autocapitalize="off" maxlength="300"></div>`
    : `<div class="row"><label for="srv-key">${tr('API key')}</label><input id="srv-key" type="password" autocomplete="off" spellcheck="false" autocapitalize="off" maxlength="300" placeholder="sk-ant-…"></div>`;
  const model = j.model || j.default_model || '';
  // 2.638.0 (#4714): without limits a day limit is proposed with the first key (kept = the agent's hard day limit); a key that is there: a hint
  const limRow = j.limits ? '' : isNew || !j.has_key
    ? `<div class="row"><label for="srv-daylim">${tr('Daily limit')}</label><input id="srv-daylim" type="number" inputmode="numeric" class="numin" min="1" step="1" value="${+j.day_limit_default || 2000000}"><span class="muted">${tr('tokens')}</span></div>
      <div class="shint keep">${esc(tr('Proposed with the first key: the agent pauses for the day once its runs used this many tokens, also the runs other people start through chat, mentions or assignments. Empty = no limit.'))}</div>`
    : `<div class="shint keep srvnolim" role="note">${ic('alert', 's')} ${esc(tr('No usage limit: every run, also those other people start through chat, mentions or assignments, is billed to this key without a cap. Set one under “Usage limit” in the agent’s settings.'))}</div>`;
  return `<div class="row"><label for="srv-prov">${tr('Provider')}</label><select id="srv-prov"><option value="anthropic" selected>Anthropic (Claude)</option></select></div>
    ${keyRow}
    <div class="shint keep">${esc(tr('Your own key of the provider; its usage is billed to you by the provider. Kalmido stores it encrypted and never shows it again, only its last four characters.'))}</div>
    ${limRow}
    <div class="row"><label for="srv-model">${tr('Model')}</label><select id="srv-model"><option value="${esc(model)}" selected>${esc(model)}</option></select></div>
    <div class="shint keep" id="srv-modelhint">${esc(isNew ? tr('The list of models comes from the provider once the key is saved; you can change the model later in the agent’s settings.') : tr('Loading…'))}</div>
    <div class="row"><label for="srv-ins">${tr('Instructions')}</label><textarea id="srv-ins" rows="7" maxlength="20000">${esc(j.instructions || j.default_instructions || '')}</textarea></div>
    <div class="shint keep">${esc(tr('Like a CLAUDE.md: how it works for you. It only uses the Kalmido tools within its permissions; no web, no terminal, no other services.'))}</div>`;
}
// 2.638.0 (#4714): the proposed day limit of the dialog ({} = none shown or emptied; the server takes it only with a first key)
function srv_limBody(md) {
  const v = $('#srv-daylim', md)?.value.trim() || '';
  return v ? {day_limit: Math.round(+v)} : {};
}
// fills the model choice live from the provider (409 no_key: only the current one stays)
async function srv_modelsFill(md, aid, cur) {
  const sel = $('#srv-model', md), h = $('#srv-modelhint', md); if (!sel) return;
  let j; try { j = await rawFetch('GET', `/api/agents/${aid}/server/models`); } catch (x) {
    if (h) h.textContent = x?.data?.error === 'no_key' ? tr('Save an API key first; then the provider’s models are listed here.') : x instanceof Offline ? tr('Only available online.') : (x?.message || '');
    return null;
  }
  if (!md.isConnected) return j;
  const want = cur || j.default, ms = j.models || [];
  sel.innerHTML = (ms.some(m => m.id === want) ? '' : `<option value="${esc(want)}">${esc(want)}</option>`) + ms.map(m => `<option value="${esc(m.id)}" ${m.id === want ? 'selected' : ''}>${esc(m.name || m.id)}</option>`).join('');
  if (h) h.textContent = j.fallback_note || tr('Default: {0}. A cheaper model for simple work, a larger one for difficult cases.', j.default || '');
  return j;
}
function srv_starterHtml(d) {
  return `<fieldset class="srvst"><legend>${tr('Starter pack')}</legend>
    <div class="shint keep">${esc(tr('Each one only proposes; you decide. Later you change or remove each on its own (planned jobs, standing rules, documents).'))}</div>
    ${SRV_ST.map(([k, n, h]) => `<label class="chkl srvsti"><input type="checkbox" data-srv-st="${k}" ${k === 'office' ? '' : 'checked'}><span>${esc(tr(n))}<small class="muted">${esc(tr(h))}</small></span></label>${k === 'followup'
      ? `<div class="row srvfd"><label for="srv-fdays">${tr('after|days')}</label><input id="srv-fdays" type="number" inputmode="numeric" class="numin" min="1" max="${d.followup_max || 60}" value="${d.followup_days || 5}"><span class="muted">${tr('days')}</span></div>` : k === 'docs' ? '<div class="shint keep" id="srv-docsws" hidden></div>' : ''}`).join('')}</fieldset>`;
}
// 2.777.0 C (#5378): the projects I may share with an agent: managed by me, no basket / archive / lock / private kind (health,
// budget, an organisation's trip), no agent in it yet (one agent per project). ws: 'org:<id>' = only that organisation's (a team
// agent of it; also an agent that works there), 'private' = only private ones, '' = all of mine (a new personal agent: its
// workspace follows the chosen projects)
const srv_hasAgent = l => listPeople(l).some(p => p.agent || !!agentById(p.user_id));
function srv_projs(ws) {
  const org = String(ws || '').startsWith('org:') ? +String(ws).slice(4) : 0;
  return (S.lists || []).filter(l => !l.archived && !l.is_inbox && !l.e2e && canManage(l) && !['health', 'budget'].includes(l.life) && !(l.life === 'travel' && l.org_id)
    && !srv_hasAgent(l) && (org ? l.org_id === org : ws === 'private' ? !l.org_id : true)).sort((a, b) => lname(a).localeCompare(lname(b), LOCALE()));
}
function srv_projHtml(ws) {
  const ls = srv_projs(ws);
  return `<legend>${tr('Projects for the agent')}</legend>
    <div class="shint keep">${esc(tr('Shared with the agent first: it works only in projects shared with it. Without one its routines wait and start on their own once you share a project.'))}</div>
    ${ls.length ? `<div class="srvpj" role="group" aria-label="${esc(tr('Projects for the agent'))}">${ls.map(l => `<label class="chkl"><input type="checkbox" data-srv-pj="${l.id}"><span>${esc(lname(l))}${wsOn() && !String(ws).startsWith('org:') ? ` <small class="muted">${esc(wsLabel(l.org_id))}</small>` : ''}</span></label>`).join('')}</div>`
      : `<div class="muted mhint">${esc(tr('No project of yours to share yet; you can share one later.'))}</div>`}`;
}
// shares the projects lids with agent aid (role edit; a bridge between different people asks first) -> the failures as texts
async function srv_share(aid, lids) {
  const out = [];
  for (const lid of lids) {
    try { await bridgeTry(ok => rawFetch('PUT', `/api/lists/${lid}/members`, {user_id: aid, role: 'edit', ...(ok ? {bridge_ok: true} : {})})); }
    catch (x) { if (!x?.declined) out.push(`${lname(listById(lid) || {name: ''})}: ${x instanceof Offline ? tr('Only available online.') : x?.message || ''}`); }
  }
  return out;
}
// "Share project" in the agent's window: the projects of its workspace, then back to the window (its routines start)
async function srv_shareModal(a, ws, done) {
  const md = /** @type {any} */ (modal(`<h3>${esc(tr('Share a project with {0}', a.name || ''))}</h3>
    <fieldset class="srvpjs">${srv_projHtml(ws)}</fieldset>
    <div class="foot"><div class="calerr" role="alert" id="srv-pjerr" hidden></div><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="srv-pjok">${tr('Share')}</button></div>`));
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'srv-pjok') return;
    const lids = $$('[data-srv-pj]:checked', md).map(x => +x.dataset.srvPj), er = $('#srv-pjerr', md);
    if (!lids.length) { er.textContent = tr('Choose a project'); er.hidden = false; return; }
    b.disabled = true;
    const f = await srv_share(a.id, lids);
    b.disabled = false;
    if (f.length) { er.textContent = f.join(' · '); er.hidden = false; }
    if (f.length < lids.length) { toast(tr('Shared')); if (!f.length) md.remove(); load().then(render).catch(() => {}); done && done(); }
  });
  return md;
}
// "New agent" > "Runs on the Kalmido server". o.admin: from the administration (team agent or my own), else my personal agent
async function srv_newModal(o = {}) {
  let d; try { d = await srv_defaults(true); } catch { toast(tr('Only available online.')); return; }
  const md = /** @type {any} */ (modal(`<h3>${tr('New agent on the Kalmido server')}</h3>
    <div class="shint keep">${esc(tr('Kalmido calls the model itself with your own API key whenever something comes for the agent (assigned, @mention, chat, listening in, a planned job). No computer of your own is needed.'))}</div>
    ${d.enabled_instance ? `${o.admin ? `<div class="row"><label for="srv-own">${tr('Belongs to')}</label><select id="srv-own"><option value="me">${esc(tr('Personal agent of {0}', S.me?.display_name || ''))}</option><option value="team">${tr('Team agent')}</option></select></div>` : srv_teamOwnHtml()}
    <div class="row"><label for="srv-name">${tr('Display name')}</label><input id="srv-name" value="${esc(d.default_name || '')}" maxlength="60"></div>
    <div class="row"><label for="srv-user">${tr('Username')}</label><input id="srv-user" class="unin" autocapitalize="off" autocomplete="off" spellcheck="false" maxlength="32"></div>
    <div class="shint keep" id="srv-userhint" hidden></div>
    ${srv_fieldsHtml(d, true)}
    <fieldset class="srvpjs" id="srv-pjs"></fieldset>
    ${srv_starterHtml(d)}` : srv_offHtml()}
    <div class="foot"><div class="calerr" role="alert" id="srv-err" hidden></div><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${d.enabled_instance ? `<button class="btn pri" data-m="srv-ok">${tr('Create')}</button>` : ''}</div>`));
  userNameFollow(md, 'srv-name', 'srv-user', 'srv-userhint');
  // 2.621.0 (#4715): which workspace "Sort receipts and documents" meets: private or the organisation of the chosen team agent
  // 2.621.0 (#4715): an owner without a listed workspace (instance team agent) shows no hint
  const dw = $('#srv-docsws', md), docsWs = () => { if (!dw) return; const v = $('#srv-own', md)?.value || 'me', w = (d.docs_scopes || []).find(x => x.key === v); dw.textContent = w ? tr('Applies to: {0}', w.name) : ''; dw.hidden = !w; };
  docsWs(); $('#srv-own', md)?.addEventListener('change', docsWs);
  // 2.777.0 C (#5378): "Projects for the agent" follow the owner choice (a team agent of an organisation: only its projects)
  const pjWs = () => { const v = $('#srv-own', md)?.value || 'me'; return v.startsWith('org:') ? v : ''; };
  const pjDraw = () => { const f = $('#srv-pjs', md); if (f) f.innerHTML = srv_projHtml(pjWs()); };
  pjDraw(); $('#srv-own', md)?.addEventListener('change', pjDraw);
  const un0 = $('#srv-user', md); if (un0) un0.value = slugUser(d.default_name || '');
  const err = $('#srv-err', md), show = m => { err.textContent = m || ''; err.hidden = !m; };
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'srv-ok') return;
    const name = $('#srv-name', md).value.trim(), un = $('#srv-user', md).value.trim().toLowerCase(), key = $('#srv-key', md).value.trim();
    if (!name) { need($('#srv-name', md)); return; }
    if (!un || userNameBad(un)) { show(un ? userNameBad(un) : ''); need($('#srv-user', md)); return; }
    if (!key) { need($('#srv-key', md), tr('The API key is missing')); return; }
    const items = $$('[data-srv-st]:checked', md).map(x => x.dataset.srvSt), days = Math.max(1, Math.min(d.followup_max || 60, +$('#srv-fdays', md)?.value || d.followup_days || 5));
    const team = o.admin && $('#srv-own', md)?.value === 'team';
    // 2.777.0 C (#5378): the chosen projects; an agent works in ONE workspace, so they decide the workspace of an agent of mine
    const pj = $$('[data-srv-pj]:checked', md).map(x => +x.dataset.srvPj), pws = [...new Set(pj.map(id => listById(id)?.org_id || null))];
    if (pws.length > 1) { show(tr('Choose projects of one workspace: an agent works in one workspace.')); return; }
    b.disabled = true; show('');
    let r;
    try {
      const nb = {username: un, display_name: name, provider: SRV_PROV, ...(pws.length ? {org_id: pws[0]} : {})};
      const torg = o.admin ? 0 : +String($('#srv-own', md)?.value || '').replace('org:', '') || 0;  // 2.569.0 B (#4675): a team agent of my organisation
      r = torg ? await calReq('POST', `/api/orgs/${torg}/server-agents`, {username: un, display_name: name}) : o.admin ? await calReq('POST', '/api/admin/agents', team ? nb : {...nb, owner_id: S.me?.id}) : await calReq('POST', '/api/my/agents', nb);
    } catch (x) { show(x.message); b.disabled = false; return; }
    // the agent exists from here on: a later step that fails is said, the agent stays (its settings open again from its row)
    const fails = [];
    try { await calReq('PUT', `/api/agents/${r.id}/server`, {provider: $('#srv-prov', md).value, model: $('#srv-model', md).value, instructions: $('#srv-ins', md).value, api_key: key, ...srv_limBody(md)}); }
    catch (x) { fails.push(tr('Server settings: {0}', x.message)); }
    if (!fails.length && pj.length) fails.push(...await srv_share(r.id, pj));  // 2.777.0 C (#5378): shared BEFORE the starter pack
    const calm = [];  // a routine that waits for a project or an item that needs a right first: a calm hint, no error
    if (!fails.length && items.length) {
      try {
        const st = await calReq('POST', `/api/agents/${r.id}/server/starter`, {items, followup_days: days});
        for (const x of st.items || []) if (x.state === 'skipped') calm.push(`${tr((SRV_ST.find(y => y[0] === x.item) || [])[1] || x.item)}: ${x.reason || ''}`);
      } catch (x) { fails.push(tr('Starter pack: {0}', x.message)); }
    }
    md.remove(); o.done && o.done(); load().then(render).catch(() => {});
    // 2.777.0 C (#5378): the agent's window opens after creating it: its starter pack, what waits, "Share project"
    srv_editModal({...r, name: r.name || name}, fails, calm);
    if (fails.length) return;
    toast(tr('{0} is ready', r.name || name));
    try { const m = await api('GET', `/api/agents/${r.id}/server/models`); if (m.fallback_note) toast(m.fallback_note); } catch { /* the settings say it */ }
  });
  setTimeout(() => $('#srv-name', md)?.focus(), 50);
  return md;
}
// 2.777.0 C (#5378): the starter pack in the agent's window: each item with its state; a missing one is added later here (the same
// POST as the dialog, e.g. "Due billing" once the agent has the office rights); without a shared project a calm hint + "Share project"
const SRV_ST_STATE = {active: N_('On|starter'), waiting: N_('Waits for a project'), paused: N_('Paused|starter')};
async function srv_stDraw(md, a) {
  const box = $('#srv-st', md); if (!box) return;
  let j; try { j = await api('GET', `/api/agents/${a.id}/server/starter`); } catch { box.innerHTML = ''; return; }
  if (!md.isConnected) return;
  const waits = Object.values(j.items || {}).includes('waiting');
  box.innerHTML = `${j.shared ? '' : `<div class="shint keep srvwait" role="note"><span>${esc(waits ? tr('No project is shared with {0} yet: its routines wait and start on their own once you share one.', a.name || '') : tr('No project is shared with {0} yet: it sees nothing and can only work once you share a project.', a.name || ''))}</span>
      <button type="button" class="btn sm" data-srv="share">${ic('users', 's')} ${tr('Share project')}</button></div>`}
    <h4 id="srv-st-h">${tr('Starter pack')}</h4><div class="srvruns" role="list" aria-labelledby="srv-st-h">${SRV_ST.map(([k, n]) => { const st = (j.items || {})[k] || 'missing';
      return `<div class="mrow srvsti" role="listitem" data-srv-sti="${k}" data-state="${st}"><span class="n">${esc(tr(n))} <small class="muted">${st === 'missing' ? '' : esc(tr(SRV_ST_STATE[st] || st))}</small></span>${st === 'missing' ? `<button type="button" class="btn sm" data-srv-add="${k}">${ic('plus', 's')} ${tr('Add')}</button>` : ''}</div>`; }).join('')}</div>
    <div class="shint keep" id="srv-sthint" role="status" hidden></div>`;
  box.dataset.ws = j.org_id ? 'org:' + j.org_id : 'private';
  md._srvSt = j;
}
// after "Share project": the waiting routines asked again start at once (else the server's watchdog starts them within a minute)
async function srv_stWake(md, a) {
  const w = Object.entries(md._srvSt?.items || {}).filter(([, v]) => v === 'waiting').map(([k]) => k);
  if (w.length) { try { await calReq('POST', `/api/agents/${a.id}/server/starter`, {items: w}); } catch { /* the watchdog starts them */ } }
  if (md.isConnected) await srv_stDraw(md, a);
}
// the server settings of an agent (the same fields) + its starter pack + its latest runs; notes = what failed while creating it,
// calm = what the starter pack left out for now (a right missing): a hint, no error (2.777.0 C #5378)
async function srv_editModal(a, notes, calm) {
  const md = /** @type {any} */ (modal(`<h3>${esc(tr('{0} on the Kalmido server', a.name))}</h3>
    ${notes?.length ? `<div class="calerr" role="alert">${notes.map(esc).join('<br>')}</div>` : ''}
    ${calm?.length ? `<div class="shint keep srvcalm" role="note">${calm.map(esc).join('<br>')}</div>` : ''}
    <div id="srv-st"></div>
    <div id="srv-ed"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div id="srv-team"></div>
    <h4 id="srv-runs-h">${tr('Latest runs')}</h4><div class="srvruns" id="srv-runs" role="list" aria-labelledby="srv-runs-h"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><div class="calerr" role="alert" id="srv-err" hidden></div><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button><button class="btn pri" data-m="srv-save" hidden>${tr('Save')}</button></div>`));
  const err = $('#srv-err', md), show = m => { err.textContent = m || ''; err.hidden = !m; };
  let j = null;
  const draw = async () => {
    try { j = await api('GET', `/api/agents/${a.id}/server`); } catch (x) { $('#srv-ed', md).innerHTML = `<div class="muted mhint">${esc(x instanceof Offline ? tr('Only available online.') : x.message)}</div>`; return; }
    if (!md.isConnected) return;
    $('#srv-ed', md).innerHTML = (j.enabled_instance === false ? srv_offHtml() : '') + srv_fieldsHtml(j, false) + srv_flowsHtml(j) + srv_webHtml(j);
    $('[data-m="srv-save"]', md).hidden = false;
    srv_modelsFill(md, a.id, j.model).then(m => srv_flowsFill(md, m));
  };
  const runs = async () => {
    const box = $('#srv-runs', md);
    let r; try { r = await api('GET', `/api/agents/${a.id}/server/runs?limit=10`); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
    if (!md.isConnected) return;
    box.innerHTML = (r.runs || []).map(x => `<div class="mrow srvrun" role="listitem"><span class="n"><b>${esc(srv_stateTxt(x.state))}</b> <span class="muted">${esc(x.trigger || '')}</span>
      <small class="muted">${esc([x.started ? fmtStamp(new Date(x.started)) : '', x.flow ? srv_flowName(x.flow) : '', x.model || '', trn('{0} step', '{0} steps', x.steps || 0), tr('{0} tokens', fmtTok((x.tokens_in || 0) + (x.tokens_out || 0))), x.web ? tr('Web: {0} searches, {1} pages, {2} VAT checks', x.web_searches || 0, x.web_fetches || 0, x.vat_checks || 0) : ''].filter(Boolean).join(' · '))}</small>
      ${x.error ? `<small class="srverr">${esc(x.error)}</small>` : ''}</span></div>`).join('') || `<div class="muted mhint">${tr('No runs yet.')}</div>`;
  };
  md.addEventListener('click', async e => {
    const t = /** @type {any} */ (e.target), b = t.closest('button[data-m], button[data-srv], button[data-srv-add]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.srv === 'rep') { const row = $('#srv-keyrow', md); if (row) { row.hidden = false; $('#srv-key', md)?.focus(); } return; }
    try {
      if (b.dataset.srv === 'delkey') {
        if (!await askConfirm(tr('Delete the API key?'), tr('The agent stops working on the server until you save a new key.'), {ok: tr('Delete'), danger: true})) return;
        await calReq('PUT', `/api/agents/${a.id}/server`, {delete_key: true}); toast(tr('Deleted')); await draw(); return;
      }
      if (b.dataset.srvAdd) {  // 2.568.0 (#4673) office, 2.777.0 C (#5378) every item: added later, e.g. once the agent has the rights
        b.disabled = true; show('');
        const x = ((await calReq('POST', `/api/agents/${a.id}/server/starter`, {items: [b.dataset.srvAdd]})).items || [])[0] || {};
        const h = $('#srv-sthint', md);
        if (x.state === 'skipped' || x.state === 'waiting') { if (h) { h.textContent = x.reason || ''; h.hidden = !x.reason; } }
        else toast(x.state === 'exists' ? tr('Already set up') : tr('Saved'));
        if (x.state !== 'skipped') await srv_stDraw(md, a);
        return;
      }
      if (b.dataset.srv === 'share') { srv_shareModal(a, $('#srv-st', md)?.dataset.ws || '', () => srv_stWake(md, a)); return; }
      if (b.dataset.m === 'srv-save') {
        const key = $('#srv-key', md)?.value.trim() || '';
        b.disabled = true; show('');
        const fm = srv_flowsBody(md), fw = srv_webBody(md);  // 2.565.0 D (#4674); 2.571.0 D (#4676)
        await calReq('PUT', `/api/agents/${a.id}/server`, {provider: $('#srv-prov', md).value, model: $('#srv-model', md).value, instructions: $('#srv-ins', md).value, ...(key ? {api_key: key, ...srv_limBody(md)} : {}), ...(fm ? {flow_models: fm} : {}), ...(fw ? {flow_web: fw} : {})});
        toast(tr('Saved')); await draw();
      }
    } catch (x) { show(x.message); } finally { b.disabled = false; }
  });
  draw(); runs(); srv_teamFill(md, a); srv_stDraw(md, a);
  return md;
}
const srv_stateTxt = s => tr(({queued: N_('queued|run'), run: N_('running|run'), running: N_('running|run'), done: N_('done|run'), failed: N_('failed|run'), error: N_('failed|run'), aborted: N_('stopped|run'), paused: N_('paused|run')})[s] || s || '');  // agent_runs.state (srvagent_run.py)
// Settings > Agents > Set up: the third way next to "For me" / "For the team" (the in-app guide)
function srv_guideHtml() {
  return `<div class="shint keep srvguide">${ic('cloud', 's')} <span>${esc(tr('Without a computer: an agent on the Kalmido server (“Kalmido AI”) works with your own API key of a model provider. Kalmido calls the model itself; the agent only uses the Kalmido tools within its permissions.'))}</span>
    <button type="button" class="btn sm" data-myag-act="srvnew">${ic('plus', 's')} ${tr('Set up on the Kalmido server')}</button></div>`;
}
// Administration > Agents: the instance switch (server_agents_off, "1" = off)
function srv_adminHtml(hint) {
  return `<h4 id="s-srvag-h">${tr('Agents on the Kalmido server')}</h4>
    <div class="row"><label class="chkl swl"><span class="swc"><input type="checkbox" id="s-srvag" ${S.about?.server_agents_off ? '' : 'checked'}><span class="swt" aria-hidden="true"></span></span><span>${tr('Allow server agents')}</span></label></div>
    ${hint(tr('On: people may set up an agent that runs on this server with their own API key of a model provider. Off: the kind is not offered and no server agent runs.'))}`;
}
async function srv_adminSwitch(el) {
  const on = el.checked;
  if (!on && !await askConfirm(tr('Switch server agents off?'), tr('No server agent runs any more until you switch them on again; nothing is deleted.'), {ok: tr('Switch off'), danger: true})) { el.checked = true; return; }
  try {  // allowing them again opens the server: the account password like the other opening switches (core/instance.py)
    let j; try { j = await rawFetch('PATCH', '/api/admin/settings', {server_agents_off: !on}); } catch (x) {
      if (x.data?.reauth_needed) { if (!await reauthFresh(x.data)) throw x; j = await api('PATCH', '/api/admin/settings', {server_agents_off: !on}); } else {  // 2.611.0 (#4019)
      if (!x.data?.password_needed) { toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); throw x; }
      const p = await pwPrompt(tr('Confirm with your password')); if (!p) throw x;
      j = await api('PATCH', '/api/admin/settings', {server_agents_off: !on, password: p.password}); }
    }
    if (j && j.version) S.about = j;
    srv_def = null; toast(tr('Saved'));
  } catch { el.checked = !on; }
}
// 2.569.0 B (#4675): a team agent of an organisation on the server - its admins create it (POST /api/orgs/<id>/server-agents) and
// set a limit per member (GET / PUT /api/agents/<id>/server/team); members give it orders where a project opens it to them
const srv_teamOrgs = () => (S.me?.workspaces || []).filter(w => w.role === 'admin');
function srv_teamOwnHtml() {
  const os = srv_teamOrgs(); if (!os.length) return '';
  return `<div class="row"><label for="srv-own">${tr('Belongs to')}</label><select id="srv-own"><option value="me">${esc(tr('Personal agent of {0}', S.me?.display_name || ''))}</option>${os.map(w => `<option value="org:${w.id}">${esc(tr('Team agent of {0}', w.name || ''))}</option>`).join('')}</select></div>
    <div class="shint keep">${esc(tr('A team agent works with the key you store here; members give it orders where a project opens it to them (“Members may see and use the agent”). Your personal agent takes orders only from you, also in shared projects.'))}</div>`;
}
async function srv_teamFill(md, a) {
  const box = $('#srv-team', md); if (!box) return;
  let j; try { j = await rawFetch('GET', `/api/agents/${a.id}/server/team`); } catch { return; }  // a personal agent (400) or no admin: nothing
  if (!md.isConnected || !j?.team) return;
  const lim = j.member_limit, per = lim?.period || j.period || 'month';
  box.innerHTML = `<h4 id="srv-team-h">${tr('Limit per member')}</h4>
    <div class="shint keep">${esc(tr('Its usage goes on the key stored here. A member over the limit gets an answer that says so; the requests of the others still run.'))}</div>
    <div class="row"><label for="srv-mlim">${tr('Tokens')}</label><input id="srv-mlim" type="number" inputmode="numeric" class="numin" min="1" value="${lim?.hard ?? ''}" placeholder="${esc(tr('none'))}">
      <select id="srv-mper" aria-label="${esc(tr('Period'))}"><option value="day" ${per === 'day' ? 'selected' : ''}>${tr('per day')}</option><option value="month" ${per === 'month' ? 'selected' : ''}>${tr('per month')}</option></select>
      <button type="button" class="btn sm" id="srv-mlim-save">${tr('Save')}</button></div>
    <div class="srvruns" role="list" aria-labelledby="srv-team-h">${(j.members || []).map(m => `<div class="mrow" role="listitem"><span class="n">${esc(m.name || '')} <small class="muted">${esc(tr('{0} tokens', fmtTok(m.used || 0)))}${m.reached ? ' · ' + esc(tr('limit reached')) : ''}</small></span></div>`).join('')}</div>`;
  $('#srv-mlim-save', md).addEventListener('click', async ev => {
    const b = /** @type {any} */ (ev.currentTarget), v = +$('#srv-mlim', md).value || 0;
    b.disabled = true;
    try { await calReq('PUT', `/api/agents/${a.id}/server/team`, {member_limit: v > 0 ? {period: $('#srv-mper', md).value, hard: Math.round(v)} : null}); toast(tr('Saved')); srv_teamFill(md, a); }
    catch (x) { toast(x.message); } finally { b.disabled = false; }
  });
}
