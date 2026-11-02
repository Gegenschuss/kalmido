// 2.365.2 part C UI tests (#2789): settings moved out of small modules, own container (start.sh). jsdom:
// - Time tracking and the Focus panel have a "Settings…" button that opens Settings
// - Settings > Agents: "Always show steps" is the setting agent_steps_always; the agent card names the permission mode
// - Settings > Account: "Signature for letters" opens the Office signature dialog
// - Settings > Organisation: vacation approval + public holidays of the organisation (admins write, members read);
//   the Absences tab holds a link instead; a person without an organisation has the own state in General > Working week
// freelancer-matrix: none (no new routes)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2365C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const change = (w, el, v) => { if (typeof v === 'boolean') el.checked = v; else el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'cal', 'collab', 'comments', 'time', 'events', 'workload', 'office', 'pomo', 'agents'])].join(',');
  const prep = ck => call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, ck);
  await prep(CK);
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'})).id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: 1})).id;
  sql('INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?) ON CONFLICT DO NOTHING', [ORG, BOB, 'member']);
  const CB = await login('bob'); await prep(CB);
  const CC = await login('carol'); await prep(CC);

  // ================= time + focus: a way to Settings
  let w = await boot({user: 'alice', hash: 'time'}), d = w.document;
  const tb = await until(() => d.querySelector('#view .tvbar [data-act="mod-settings"][data-sec="time"]'), 60);
  check(!!tb, '#2789: Time tracking has a Settings button');
  click(w, tb);
  check(!!(await until(() => d.querySelector('.smodal'))), '#2789: it opens the Settings dialog');
  w.close();
  w = await boot({user: 'alice', hash: 'pomo'}); d = w.document;
  const pb = await until(() => d.querySelector('#view .pomo [data-act="mod-settings"][data-sec="focus"]'), 60);
  check(!!pb, '#2789: the Focus panel has a Settings button');
  click(w, pb);
  check(!!(await until(() => d.querySelector('.smodal'))), '#2789: it opens the Settings dialog (focus)');
  w.close();

  // ================= agents: steps switch + permission mode on the card
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('ai')`);
  const as = await until(() => d.querySelector('.smodal #s-agsteps'), 80);
  check(!!as && !as.checked, '#2789: Settings > Agents has "Always show steps", off by default');
  if (as) change(w, as, true);
  check(await until(async () => (await call('GET', '/api/state')).settings.agent_steps_always === '1'), '#2789: the switch saves agent_steps_always');
  check(w.eval(`stepsAlwaysOn()`) === true, '#2789: the chat reads the same setting');
  const card = w.eval(`agCardHtml({id: 9, name: 'Robo', enabled: true, lists: [], permission_mode: 'ask', usage: null}, true)`);
  check(/Permissions: Ask first/.test(card || ''), '#2789: the agent card names the permission mode');
  const card2 = w.eval(`agCardHtml({id: 9, name: 'Robo', enabled: true, lists: [], permission_mode: '', usage: null}, true)`);
  check(!/Permissions:/.test(card2 || ''), '#2789: no mode on the card when it is the host default');
  check(/id="ag-pm"/.test(w.eval(`agRtFields(null)`) || ''), '#2789: the agent dialog has the Approvals (permission mode) choice');
  w.close();

  // ================= signature for letters
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('account')`);
  const sg = await until(() => d.querySelector('.smodal [data-act="lt-sigset"]'), 80);
  check(!!sg, '#2789: Settings > Account has "Signature for letters"');
  click(w, sg);
  check(!!(await until(() => d.querySelector('#lt-pgreet'), 80)), '#2789: the button opens the signature dialog');
  w.close();

  // ================= organisation: vacation approval + public holidays
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('org')`);
  const ap = await until(() => d.querySelector('.smodal #s-wsr-appr'), 80);
  const hs = await until(() => d.querySelector('.smodal #s-wsr-state'), 80);
  check(!!ap && !!hs && !ap.disabled && !hs.disabled, '#2789: the admin sees both fields, editable');
  // 2.461.0 (#3773): first the country, then the region; a country without regions shows no second field
  const hc = d.querySelector('.smodal #s-wsr-state-cc');
  check(!!hc && !!hs && hs.hidden, '#3773: without a choice only the country shows');
  if (hc) change(w, hc, 'FR');
  check(await until(async () => (await call('GET', `/api/team/absences?org=${ORG}`)).state === 'FR'), '#3773: a country without regions is saved at once');
  check(hs.hidden, '#3773: France has no region field');
  if (hc) change(w, hc, 'DE');
  check(await until(async () => (await call('GET', `/api/team/absences?org=${ORG}`)).state === 'DE'), '#3773: Germany starts on the nationwide holidays');
  check(!hs.hidden && [...hs.options].some(o => o.value === 'BY'), '#3773: Germany offers its states');
  if (hs) change(w, hs, 'BY');
  check(await until(async () => (await call('GET', `/api/team/absences?org=${ORG}`)).state === 'BY'), '#2789: the state of the organisation saved');
  if (ap) change(w, ap, true);
  check(await until(async () => (await call('GET', `/api/team/leave?org=${ORG}`)).approval === true), '#2789: the approval saved');
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  w.close(); w = await boot({user: 'alice', hash: 'workload'}); d = w.document;
  await until(() => d.querySelector('#view .ab2tabs'), 60);
  w.eval(`WLV.tab = 'abs'; AB2.data = null; render()`);
  check(await until(() => /Bavaria|Bayern/.test(d.querySelector('#view .ab2st[data-act="mod-settings"]')?.textContent || '')), '#2789: the Absences tab shows the state and a link to Settings');
  check(!d.querySelector('#ab2-state') && !d.querySelector('#lv-approval'), '#2789: no state picker / approval switch left in the module');
  w.close();
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('org')`);
  const bs = await until(() => d.querySelector('.smodal #s-wsr-state'), 80);
  check(!!bs && bs.disabled, '#2789: a member sees the state but cannot change it');
  w.close();

  // ================= own holiday state: General > Working week; without an organisation too
  w = await boot({user: 'carol'}); d = w.document;
  w.eval(`settingsModal('general')`);
  const ps = await until(() => d.querySelector('.smodal #s-holst'), 80);
  check(!!ps, '#2789: General > Working week has the own state of the public holidays (person without an organisation)');
  const pc = d.querySelector('.smodal #s-holst-cc');  // 2.461.0 (#3773): first the country
  if (pc) change(w, pc, 'DE');
  check(await until(async () => (await call('GET', '/api/state', null, CC)).settings.holiday_state === 'DE'), '#3773: Germany saved first');
  // saving may draw the section anew: always the field that is there now
  check(await until(async () => { const r = d.querySelector('.smodal #s-holst'); if (r && !r.hidden) change(w, r, 'BY'); return (await call('GET', '/api/state', null, CC)).settings.holiday_state === 'BY'; }), '#2789: the own state saved');
  check((await call('GET', '/api/team/absences/feed', null, CC)).state === 'BY', '#2789: it applies to the person without an organisation');
  w.close();

  console.log(`p2365_2_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
