// 2.147.1 UI tests of part B2 (#2230, #2231) (own container, start.sh; P21443B_NOSTART=1: the container runs already). jsdom:
// - #2230: moving 25 files into an organisation: the dialog shows "Moving…" (aria-busy) and the bar "x of 25 moved"
//   (role progressbar), all 25 arrive, ONE undo step brings all 25 back (batches of 20)
// - a few items: only the busy button, no bar
// - #2231: an agent of an organisation carries data-wsc (the workspace stripe) on its entries (sidebar, window bar, Agents
//   view); a private agent is neutral unless I chose a colour for Private; the chat head keeps the agent colour (#2411)
//   and never the workspace one; a person without an organisation sees no colour and nothing breaks
// - #2502: a hidden reply bar no longer takes away the agent colour line on top of the chat input
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21443B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const upload = async (ck, name, text) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name); fd.append('space', 'private');
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items[0].id;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const me = (await call('GET', '/api/state')).me;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id;
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs', 'agents'])].filter(Boolean).join(',')});
  const ids = [];
  for (let i = 0; i < 25; i++) ids.push(await upload(CK, `datei${i}.txt`, `inhalt ${i}`));

  // ================= 25 files: busy button + progress bar + one undo
  const w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}), d = w.document;
  await until(() => d.querySelector(`.abrow[data-abid="${ids[0]}"]`));
  w.eval(`AB.selOn = true; AB.sel = new Set(${JSON.stringify(ids)}); ab_smvSpace(AB.data.items.filter(x => AB.sel.has(x.id)))`);
  const md = await until(() => d.querySelector('.smv-dlg'));
  const yes = md && await until(() => !md.querySelector('[data-smv="yes"]').disabled && md.querySelector('.smv-notes li') && md, 60);
  check(md?.querySelector('.smv-bar[role="progressbar"]') && md.querySelector('.smv-prog')?.hidden, 'the bar exists for 25 items, hidden before the move');
  // slow every batch a little so the busy state is observable
  w.eval(`(() => { const o = window.api; window.api = async (...a) => { await new Promise(r => setTimeout(r, 400)); return o(...a); }; })()`);
  let busy = false, seen = '';
  yes?.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true, bubbles: true}));
  for (let i = 0; i < 40 && d.querySelector('.smv-dlg'); i++) {
    const b = d.querySelector('[data-smv="yes"]');
    if (b && b.getAttribute('aria-busy') === 'true' && b.disabled && /Moving/.test(b.textContent)) busy = true;
    const t = d.querySelector('.smv-pt')?.textContent || ''; if (/of 25 moved/.test(t)) seen += t + '|';
    await sleep(100);
  }
  check(busy, 'the button says "Moving…", is disabled and aria-busy');
  check(/20 of 25 moved/.test(seen) || /25 of 25 moved/.test(seen), 'the progress text counts batches ' + seen);
  check(await until(async () => { for (const id of ids) if ((await call('GET', `/api/files/nodes/${id}`)).org_id !== ORG) return false; return true; }, 80), 'all 25 files are in Alpha');
  const n0 = w.eval('HIST.undo.length');
  await w.eval(`histStep('undo')`);
  check(await until(async () => { for (const id of ids) if ((await call('GET', `/api/files/nodes/${id}`)).org_id !== null) return false; return true; }, 120) && w.eval('HIST.undo.length') === n0 - 1,
    'one undo step brings all 25 back');
  w.close();

  // ================= few items: busy button only, no bar
  const w2 = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}), d2 = w2.document;
  await until(() => d2.querySelector(`.abrow[data-abid="${ids[0]}"]`));
  w2.eval(`ab_smvSpace(AB.data.items.filter(x => x.id === ${ids[0]}))`);
  const md2 = await until(() => d2.querySelector('.smv-dlg'));
  check(md2 && !md2.querySelector('.smv-bar'), 'one item: no progress bar');
  w2.close();

  // ================= #2231: agent colours
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'orgbot', display_name: 'Orgbot', org_id: ORG});
  const ag2 = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'privbot', display_name: 'Privbot', org_id: null});
  await call('PATCH', `/api/admin/agents/${ag.id}`, {enabled: true}); await call('PATCH', `/api/admin/agents/${ag2.id}`, {enabled: true});
  const LO = (await call('POST', '/api/lists', {name: 'Team', org_id: ORG})).id, LP = (await call('POST', '/api/lists', {name: 'Mine'})).id;
  await call('PUT', `/api/lists/${LO}/members`, {user_id: ag.id, role: 'edit'}); await call('PUT', `/api/lists/${LP}/members`, {user_id: ag2.id, role: 'edit'});
  const v = await boot({user: 'alice', hash: 'home'}), vd = v.document;
  await v.eval(`api('GET', '/api/agents').then(j => { S.agents = j.agents || []; })`);
  v.eval(`S.agents.push({id: ${ag2.id}, name: 'Privbot', org_id: null, enabled: true, status: 'idle'})`);  // a private agent as the list shows it
  check(await until(() => v.eval(`!!agentById(${ag.id}) && !!agentById(${ag2.id})`)), 'both agents are in my list ' + v.eval(`JSON.stringify((S.agents || []).map(a => [a.id, a.org_id]))`) + ' ' + ag.id + ',' + ag2.id + ' ' + JSON.stringify(ag).slice(0, 120));
  check(v.eval(`agentById(${ag.id}).org_id`) === ORG, 'the agent list carries org_id');
  // 2.147.1 B (#2231 with #2411): the workspace shows as a stripe on the agent's entries, the chat head keeps the agent colour
  check(v.eval(`/data-wsc="1"/.test(acw_attr(${ORG}))`), 'an organisation agent gets the workspace stripe attributes');
  check(v.eval(`!/class="chath[^>]*data-wsc/.test(chatInner(${ag.id})) && !/class="chath[^>]*data-wsc/.test(chatInner(${ag2.id}))`), 'the chat head itself never carries the workspace colour (2.174.0 #2681: only the dot of the name does)');
  const srow = await until(() => vd.querySelector(`#side .srow.steam[data-aid="${ag.id}"]`), 30);
  if (srow) check(srow.hasAttribute('data-wsc'), 'sidebar entry of an organisation agent carries the stripe');
  const prow = vd.querySelector(`#side .srow.steam[data-aid="${ag2.id}"]`);
  if (prow) check(!prow.hasAttribute('data-wsc'), 'sidebar entry of a private agent is neutral');
  check(v.eval(`/data-wsc/.test(acw_of({agent_org_id: ${ORG}})) && acw_of({agent_org_id: null}) === ''`), 'acw_of takes agent_org_id');
  v.eval(`S.settings.ws_colors = JSON.stringify({private: LP_TONES[2][0]})`);
  check(v.eval(`/data-wsc="1"/.test(acw_attr(null))`), 'a private agent takes my own colour of Private');
  v.eval(`S.settings.ws_colors = '{}'`);

  // ================= #2502: the agent colour line on top of the input stays while the reply bar is hidden
  const css = await (await fetch(B + 'static/app.css')).text();
  const zero = [...css.matchAll(/([^{}]*\.rbar[^{}]*\+\s*\.chcomp[^{}]*)\{([^}]*)\}/g)].filter(m => /border-top\s*:\s*0/.test(m[2])).map(m => m[1].replace(/\/\*[\s\S]*?\*\//g, '').trim());
  check(zero.length > 0, 'the reply bar rule is there ' + zero.join(' | '));
  const box = vd.createElement('div'); vd.body.appendChild(box);
  box.innerHTML = v.eval(`chatInner(${ag.id})`);
  const cp = box.querySelector('.chcomp'), rb = cp?.previousElementSibling;
  check(cp && rb?.classList.contains('rbar') && rb.classList.contains('hidden'), 'the input follows a hidden reply bar');
  check(cp && !zero.some(sel => cp.matches(sel)), 'a hidden reply bar does not remove the top line of the input');
  if (rb) { rb.classList.remove('hidden'); check(zero.some(sel => cp.matches(sel)), 'a visible reply bar still takes the top line'); }
  box.remove();
  v.close();

  // ================= a person without an organisation: no colour, nothing breaks
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, FCK);
  const f = await boot({user: 'frida', hash: 'ablage'});
  check(f.eval(`acw_attr(null) === '' && acw_attr(1) === ''`), 'freelancer: no agent colour');
  f.close();

  console.log(`p21443_b2_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
