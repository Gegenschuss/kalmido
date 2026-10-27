// 2.46.6 part C UI tests (#1710), own container (start.sh). jsdom, invented data only:
// - an admin finds everything that applies to the whole server under Settings > Administration ("Admin" in German):
//   the sub-tab Agents holds the agent rules (personal agents, permission limit), the admins' alert on usage limits and
//   the API log; Server holds the update check result (no longer in Help) and the switches "for everyone"
// - the other areas show only the own settings: no Log / Administration sub-tab under Agents, no usage row among the own
//   notifications, no update line in Help
// - Modules keeps the two "for everyone" switches with the mark "Admin · applies to everyone" and "Open in Administration",
//   which opens Administration > Server on the same switch; a switch there re-draws on Administration > Server
// - old entries land right: settingsModal('activity' / 'agentpolicy' / 'usage' / 'users'), a remembered sub-tab "log",
//   the settings search
// - a member sees no Administration, no mark, no admin parts; German texts
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,time,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'});
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);

  let w = await boot({user: 'alice'}), d = w.document;
  await until(() => d.querySelector('#side'));
  check(w.eval('!!S.api.enabled'), 'the API is on (agents possible)');
  // as if the daily check had found a new version (client side: the server's own check could overwrite a row set here)
  const fakeUpd = () => w.eval(`S.about = {...S.about, update_env: true, update_check: true, available: true, latest: '99.0.0', url: 'https://github.com/example/kalmido/releases/tag/v99.0.0'}`);
  fakeUpd();
  const closeAll = () => d.querySelectorAll('.modal').forEach(m => m.remove());
  const secOn = md => md.querySelector('.snav .on')?.dataset.sec;
  const admOn = md => md.querySelector('[data-admsub][aria-selected="true"]')?.dataset.admsub;

  // ================= Administration > Agents
  w.eval(`settingsModal('agentpolicy')`);
  let md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'users' && admOn(md) === 'agents' && !md.querySelector('#admp-agents').hidden, "settingsModal('agentpolicy') opens Administration > Agents: " + secOn(md) + '/' + admOn(md));
  check([...md.querySelectorAll('[data-admsub]')].map(b => b.dataset.admsub).join() === 'users,signin,org,agents,server,log', 'the sub-tabs of Administration: ' + [...md.querySelectorAll('[data-admsub]')].map(b => b.dataset.admsub).join());
  const ap = md.querySelector('#admp-agents');
  await until(() => ap.querySelector('#s-sclim .sclim') && ap.querySelector('#s-aud'));
  check(ap.querySelector('#s-uag') && ap.querySelector('#s-uagmax') && ap.querySelectorAll('#s-sclim .sclim').length === 2, 'Agents: personal agents for everyone + the permission limit (loaded)');
  check(ap.querySelector('[data-nm="usage"][data-ch="push"]') && /What notifies you as an admin/.test(ap.textContent), 'Agents: the admins’ alert on usage limits');
  check(ap.querySelector('#s-adlog-h') && ap.querySelector('#s-aud') && ap.querySelector('#aud-poll'), 'Agents: the API log');
  // the policy switch still saves from here
  const uag = ap.querySelector('#s-uag'); uag.checked = true; uag.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/admin/agent-policy')).user_agents);
  check((await call('GET', '/api/admin/agent-policy')).user_agents === true, 'the switch "Users may create their own agents" saves from Administration > Agents');
  // the other areas: only the own settings
  const ai = md.querySelector('[data-pane="ai"]');
  check(ai && ![...ai.querySelectorAll('[data-aisub]')].some(b => ['log', 'admin'].includes(b.dataset.aisub)) && !ai.querySelector('#s-uag, #s-sclim, #s-aud'), 'Agents area: no Log / Administration sub-tab, no admin parts: ' + [...(ai?.querySelectorAll('[data-aisub]') || [])].map(b => b.dataset.aisub).join());
  check(!md.querySelector('#sp-notify [data-nm="usage"]') && md.querySelector('#sp-notify [data-nm="comment"]'), 'Notifications: the own rows, no admins’ row');
  const help = md.querySelector('[data-pane="help"]').textContent;
  check(!/v99/.test(help) && !/update check/i.test(help) && /Kalmido v\d/.test(help), 'Help: the version, no update result');
  const srv = md.querySelector('#admp-server');
  check(/installed — v99\.0\.0 available/.test(srv.textContent) && srv.querySelector('a[href$="/v99.0.0"]') && srv.querySelector('#s-upd-h') && srv.querySelector('#s-updcheck'), 'Administration > Server: the update result next to its switch');
  check(srv.querySelector('#s-collaball-a')?.checked && srv.querySelector('#s-timeall-a')?.checked, 'Administration > Server: collaboration and time tracking for everyone');
  closeAll();

  // ================= Modules: the mark + "Open in Administration"
  w.eval(`settingsModal('modules')`);
  md = await until(() => d.querySelector('.smodal'));
  const marks = [...md.querySelectorAll('[data-pane="modules"] .ad-mark')];
  check(marks.length === 2 && marks.every(m => m.querySelector('.ad-tag')?.textContent === 'Admin · applies to everyone' && m.querySelector('.ad-open')?.textContent === 'Open in Administration'), 'Modules: two marks "Admin · applies to everyone" + "Open in Administration"');
  check(md.querySelector('[data-modrow="collab"] .ad-mark') && md.querySelector('[data-modrow="time"] .ad-mark') && md.querySelector('[data-modrow="collab"] #s-collaball'), 'the marks sit at collaboration and time tracking, next to the switch');
  click(w, md.querySelector('[data-modrow="time"] .ad-open'));
  await sleep(100);
  check(secOn(md) === 'users' && admOn(md) === 'server' && !md.querySelector('#admp-server').hidden, 'Open in Administration: Administration > Server: ' + secOn(md) + '/' + admOn(md));
  check(md.querySelector('#s-timeall-a').closest('label').classList.contains('flash'), 'the same switch is marked');
  closeAll();
  // a switch under Administration: one way, the dialog comes back on Administration > Server
  await call('PATCH', '/api/admin/settings', {time_all: false});
  w.close(); w = await boot({user: 'alice'}); d = w.document; await until(() => d.querySelector('#side'));
  w.eval(`settingsModal('server')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'users' && admOn(md) === 'server' && md.querySelector('#s-timeall-a')?.checked === false, "settingsModal('server'): Administration > Server, time tracking for everyone off");
  const ta = md.querySelector('#s-timeall-a'); ta.checked = true; ta.dispatchEvent(new w.Event('change', {bubbles: true}));
  // 2.47.2: wait for both switches (the own one follows after the redraw; CI is slower than the Mac)
  await until(() => w.eval('S.timeAll') === true && d.querySelector('.smodal #s-timeall-a')?.checked && d.querySelector('.smodal #s-timeall')?.checked);
  md = d.querySelector('.smodal');
  check(w.eval('S.timeAll') === true && md.querySelector('#s-timeall')?.checked && md.querySelector('#s-timeall-a')?.checked, 'switched on under Administration: both switches on');
  check(secOn(md) === 'users' && admOn(md) === 'server', 'the re-drawn dialog stays on Administration > Server: ' + secOn(md) + '/' + admOn(md));
  check(d.querySelectorAll('.smodal').length === 1, 'one settings dialog');
  closeAll();

  // ================= old entries
  w.eval(`settingsModal('activity')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'users' && admOn(md) === 'agents', "settingsModal('activity'): Administration > Agents (the log)");
  closeAll();
  w.eval(`settingsModal('usage')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'ai' && !md.querySelector('#aisp-usage').hidden, "settingsModal('usage'): Agents > Usage");
  closeAll();
  w.eval(`settingsModal('users')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'users' && admOn(md) === 'users', "settingsModal('users'): Administration > People");
  closeAll();
  w.eval(`LS.set('aiSub', 'log'); settingsModal('ai')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'ai' && md.querySelector('[data-aisub][aria-selected="true"]')?.dataset.aisub === 'agents', 'a remembered sub-tab "log" falls back to Status');
  // the settings search finds the moved parts and opens their sub-tab
  await sleep(400);
  const sq = md.querySelector('#s-search'); sq.dispatchEvent(new w.Event('focus')); sq.value = 'permission limit'; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
  const hit = await until(() => [...md.querySelectorAll('#s-sres [data-hit]')].find(b => /Administration/.test(b.textContent)));
  check(hit && /Administration/.test(hit.textContent), 'search: the hit is in Administration: ' + hit?.textContent);
  if (hit) { click(w, hit); await sleep(100); }
  check(secOn(md) === 'users' && admOn(md) === 'agents', 'search: the hit opens Administration > Agents: ' + secOn(md) + '/' + admOn(md));
  closeAll();
  w.close();

  // ================= a member
  w = await boot({user: 'bob'}); d = w.document; await until(() => d.querySelector('#side'));
  w.eval(`S.about = {...S.about, available: true, latest: '99.0.0'}`);
  w.eval(`settingsModal('activity')`);
  md = await until(() => d.querySelector('.smodal'));
  check(!md.querySelector('.snav [data-sec="users"]') && !md.querySelector('[data-admsub]'), 'member: no Administration');
  check(!md.querySelector('.ad-mark, #s-collaball, #s-collaball-a, #s-uag, #s-sclim, #s-aud, [data-nm="usage"]'), 'member: no mark, no admin switch, no rules, no log, no admins’ row');
  check(!/v99/.test(md.querySelector('[data-pane="help"]').textContent), 'member: no update result');
  closeAll(); w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice'}); d = w.document; await until(() => d.querySelector('#side'));
  w.eval(`settingsModal('modules')`);
  md = await until(() => d.querySelector('.smodal'));
  check(md.querySelector('.snav [data-sec="users"] span')?.textContent === 'Verwaltung', 'German: the area is called Verwaltung (2.152.4, #2655): ' + md.querySelector('.snav [data-sec="users"] span')?.textContent);
  check(md.querySelector('.ad-mark .ad-tag')?.textContent === 'Verwaltung · gilt für alle' && md.querySelector('.ad-mark .ad-open')?.textContent === 'In der Verwaltung öffnen', 'German: the mark and the link');
  check(md.querySelector('[data-admsub="agents"]')?.textContent.trim() === 'Agenten', 'German: the sub-tab Agenten');
  closeAll(); w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2466_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
