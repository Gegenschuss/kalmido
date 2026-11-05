// @ts-check
// 2.557.0 C (#4670): the setup of a server agent ("Kalmido AI"): it runs on the Kalmido server with the person's own API key of
// a model provider, no computer of one's own. A normal agent (provider "kalmido-server") + its server settings
// (GET / PUT /api/agents/<id>/server, the models live from the provider, the latest runs) + the starter pack
// (POST /api/agents/<id>/server/starter, kalmido/agents/srvstarter.py). The dialog "New agent" asks for the defaults first
// (GET /api/agents/server/defaults: the agent has no id yet). The key is a password field and comes back only as its last
// four characters ("…abcd"): replace or delete it. Lazy module "agentchat" (lazyload.js).
const SRV_PROV = 'kalmido-server';
// the five items of the starter pack (all only propose; decision 05.11.2026, card 12870): [key, label, hint]
const SRV_ST = [['briefing', N_('Morning briefing at 07:30'), N_('Daily in its chat, read only: due, overdue, untouched, waiting on someone.')],
  ['tidy', N_('Tidy up the basket'), N_('Project, due date, priority and tags as a proposal.')],
  ['docs', N_('Sort receipts and documents'), N_('Sender, type and tags suggested from the recognised text.')],
  ['meetings', N_('Meeting notes into task proposals'), N_('Notes become a proposal “Tasks from notes”, never tasks directly.')],
  ['followup', N_('Follow up on “Waiting on someone”'), N_('A drafted follow-up as a comment, posted only after your Yes.')]];
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
  return `<div class="row"><label for="srv-prov">${tr('Provider')}</label><select id="srv-prov"><option value="anthropic" selected>Anthropic (Claude)</option></select></div>
    ${keyRow}
    <div class="shint keep">${esc(tr('Your own key of the provider; its usage is billed to you by the provider. Kalmido stores it encrypted and never shows it again, only its last four characters.'))}</div>
    <div class="row"><label for="srv-model">${tr('Model')}</label><select id="srv-model"><option value="${esc(model)}" selected>${esc(model)}</option></select></div>
    <div class="shint keep" id="srv-modelhint">${esc(isNew ? tr('The list of models comes from the provider once the key is saved; you can change the model later in the agent’s settings.') : tr('Loading…'))}</div>
    <div class="row"><label for="srv-ins">${tr('Instructions')}</label><textarea id="srv-ins" rows="7" maxlength="20000">${esc(j.instructions || j.default_instructions || '')}</textarea></div>
    <div class="shint keep">${esc(tr('Like a CLAUDE.md: how it works for you. It only uses the Kalmido tools within its permissions; no web, no terminal, no other services.'))}</div>`;
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
    ${SRV_ST.map(([k, n, h]) => `<label class="chkl srvsti"><input type="checkbox" data-srv-st="${k}" checked><span>${esc(tr(n))}<small class="muted">${esc(tr(h))}</small></span></label>${k === 'followup'
      ? `<div class="row srvfd"><label for="srv-fdays">${tr('after|days')}</label><input id="srv-fdays" type="number" inputmode="numeric" class="numin" min="1" max="${d.followup_max || 60}" value="${d.followup_days || 5}"><span class="muted">${tr('days')}</span></div>` : ''}`).join('')}</fieldset>`;
}
// "New agent" > "Runs on the Kalmido server". o.admin: from the administration (team agent or my own), else my personal agent
async function srv_newModal(o = {}) {
  let d; try { d = await srv_defaults(true); } catch { toast(tr('Only available online.')); return; }
  const md = modal(`<h3>${tr('New agent on the Kalmido server')}</h3>
    <div class="shint keep">${esc(tr('Kalmido calls the model itself with your own API key whenever something comes for the agent (assigned, @mention, chat, listening in, a planned job). No computer of your own is needed.'))}</div>
    ${d.enabled_instance ? `${o.admin ? `<div class="row"><label for="srv-own">${tr('Belongs to')}</label><select id="srv-own"><option value="me">${esc(tr('Personal agent of {0}', S.me?.display_name || ''))}</option><option value="team">${tr('Team agent')}</option></select></div>` : ''}
    <div class="row"><label for="srv-name">${tr('Display name')}</label><input id="srv-name" value="${esc(d.default_name || '')}" maxlength="60"></div>
    <div class="row"><label for="srv-user">${tr('Username')}</label><input id="srv-user" class="unin" autocapitalize="off" autocomplete="off" spellcheck="false" maxlength="32"></div>
    <div class="shint keep" id="srv-userhint" hidden></div>
    ${srv_fieldsHtml(d, true)}
    ${srv_starterHtml(d)}` : srv_offHtml()}
    <div class="foot"><div class="calerr" role="alert" id="srv-err" hidden></div><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${d.enabled_instance ? `<button class="btn pri" data-m="srv-ok">${tr('Create')}</button>` : ''}</div>`);
  userNameFollow(md, 'srv-name', 'srv-user', 'srv-userhint');
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
    b.disabled = true; show('');
    let r;
    try {
      const nb = {username: un, display_name: name, provider: SRV_PROV};
      r = o.admin ? await calReq('POST', '/api/admin/agents', team ? nb : {...nb, owner_id: S.me?.id}) : await calReq('POST', '/api/my/agents', nb);
    } catch (x) { show(x.message); b.disabled = false; return; }
    // the agent exists from here on: a later step that fails is said, the agent stays (its settings open again from its row)
    const fails = [];
    try { await calReq('PUT', `/api/agents/${r.id}/server`, {provider: $('#srv-prov', md).value, model: $('#srv-model', md).value, instructions: $('#srv-ins', md).value, api_key: key}); }
    catch (x) { fails.push(tr('Server settings: {0}', x.message)); }
    if (!fails.length && items.length) {
      try {
        const st = await calReq('POST', `/api/agents/${r.id}/server/starter`, {items, followup_days: days});
        for (const x of st.items || []) if (x.state === 'skipped') fails.push(`${tr((SRV_ST.find(y => y[0] === x.item) || [])[1] || x.item)}: ${x.reason || ''}`);
      } catch (x) { fails.push(tr('Starter pack: {0}', x.message)); }
    }
    md.remove(); o.done && o.done(); load().then(render).catch(() => {});
    if (fails.length) { srv_editModal(r, fails); return; }
    toast(tr('{0} is ready', r.name || name));
    try { const m = await api('GET', `/api/agents/${r.id}/server/models`); if (m.fallback_note) toast(m.fallback_note); } catch { /* the settings say it */ }
  });
  setTimeout(() => $('#srv-name', md)?.focus(), 50);
  return md;
}
// the server settings of an agent (the same fields, no starter pack) + its latest runs; notes = what failed while creating it
async function srv_editModal(a, notes) {
  const md = modal(`<h3>${esc(tr('{0} on the Kalmido server', a.name))}</h3>
    ${notes?.length ? `<div class="calerr" role="alert">${notes.map(esc).join('<br>')}</div>` : ''}
    <div id="srv-ed"><div class="muted mhint">${tr('Loading…')}</div></div>
    <h4 id="srv-runs-h">${tr('Latest runs')}</h4><div class="srvruns" id="srv-runs" role="list" aria-labelledby="srv-runs-h"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><div class="calerr" role="alert" id="srv-err" hidden></div><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button><button class="btn pri" data-m="srv-save" hidden>${tr('Save')}</button></div>`);
  const err = $('#srv-err', md), show = m => { err.textContent = m || ''; err.hidden = !m; };
  let j = null;
  const draw = async () => {
    try { j = await api('GET', `/api/agents/${a.id}/server`); } catch (x) { $('#srv-ed', md).innerHTML = `<div class="muted mhint">${esc(x instanceof Offline ? tr('Only available online.') : x.message)}</div>`; return; }
    if (!md.isConnected) return;
    $('#srv-ed', md).innerHTML = (j.enabled_instance === false ? srv_offHtml() : '') + srv_fieldsHtml(j, false);
    $('[data-m="srv-save"]', md).hidden = false;
    srv_modelsFill(md, a.id, j.model);
  };
  const runs = async () => {
    const box = $('#srv-runs', md);
    let r; try { r = await api('GET', `/api/agents/${a.id}/server/runs?limit=10`); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
    if (!md.isConnected) return;
    box.innerHTML = (r.runs || []).map(x => `<div class="mrow srvrun" role="listitem"><span class="n"><b>${esc(srv_stateTxt(x.state))}</b> <span class="muted">${esc(x.trigger || '')}</span>
      <small class="muted">${esc([x.started ? fmtStamp(new Date(x.started)) : '', trn('{0} step', '{0} steps', x.steps || 0), tr('{0} tokens', fmtTok((x.tokens_in || 0) + (x.tokens_out || 0)))].filter(Boolean).join(' · '))}</small>
      ${x.error ? `<small class="srverr">${esc(x.error)}</small>` : ''}</span></div>`).join('') || `<div class="muted mhint">${tr('No runs yet.')}</div>`;
  };
  md.addEventListener('click', async e => {
    const t = /** @type {any} */ (e.target), b = t.closest('button[data-m], button[data-srv]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.srv === 'rep') { const row = $('#srv-keyrow', md); if (row) { row.hidden = false; $('#srv-key', md)?.focus(); } return; }
    try {
      if (b.dataset.srv === 'delkey') {
        if (!await askConfirm(tr('Delete the API key?'), tr('The agent stops working on the server until you save a new key.'), {ok: tr('Delete'), danger: true})) return;
        await calReq('PUT', `/api/agents/${a.id}/server`, {delete_key: true}); toast(tr('Deleted')); await draw(); return;
      }
      if (b.dataset.m === 'srv-save') {
        const key = $('#srv-key', md)?.value.trim() || '';
        b.disabled = true; show('');
        await calReq('PUT', `/api/agents/${a.id}/server`, {provider: $('#srv-prov', md).value, model: $('#srv-model', md).value, instructions: $('#srv-ins', md).value, ...(key ? {api_key: key} : {})});
        toast(tr('Saved')); await draw();
      }
    } catch (x) { show(x.message); } finally { b.disabled = false; }
  });
  draw(); runs();
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
  if (!on && !await askConfirm(tr('Switch server agents off?'), tr('No server agent runs any more until you switch them on again; nothing is deleted.'), {ok: tr('Turn off'), danger: true})) { el.checked = true; return; }
  try {  // allowing them again opens the server: the account password like the other opening switches (core/instance.py)
    let j; try { j = await rawFetch('PATCH', '/api/admin/settings', {server_agents_off: !on}); } catch (x) {
      if (!x.data?.password_needed) { toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); throw x; }
      const p = await pwPrompt(tr('Confirm with your password')); if (!p) throw x;
      j = await api('PATCH', '/api/admin/settings', {server_agents_off: !on, password: p.password});
    }
    if (j && j.version) S.about = j;
    srv_def = null; toast(tr('Saved'));
  } catch { el.checked = !on; }
}
