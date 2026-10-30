// 2.173.0 UI tests (part A), own container (start.sh). jsdom:
// #2680 Home in an organisation's view: shown as "Travel & contacts" while travel or staying in touch is on (contracts,
//       budget and family stay hidden there), its view shows only the organisation's trips; Private keeps "Home" with
//       everything; the trip's bar offers "Travel expenses" (admins), which opens the office trip made from it.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,contacts,care,travel,contracts,budget,family,office';
const iso = n => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal']});
  CK = await login('alice');
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id, SP = 'org:' + ORG;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: SP});
  const ot = await call('POST', '/api/life/trips', {name: 'Trade fair', from: iso(20), to: iso(22), where: 'Hamburg', packing: '', space: SP});
  check(ot.status === 201, '#2680: a trip of the organisation');
  const pt = await call('POST', '/api/life/trips', {name: 'Beach holiday', from: iso(30), to: iso(37), packing: '', space: 'private'});
  check(pt.status === 201, '#2680: a private trip');

  // ================= the organisation's view
  let w = await boot({user: 'alice', hash: 'life'}), d = w.document;
  check(w.eval(`wsCur()`) === SP && w.eval(`S.route.mod`) === 'life', '#2680: Home opens in the organisation view (no jump to Private)');
  check(w.eval(`!o3a_privOnly('life') && o3a_privOnly('family') && o3a_privOnly('budget')`), '#2680: Home not private-only, family and budget still are');
  await until(() => d.querySelector('.lc-travel'));
  const tv = d.querySelector('.lc-travel')?.textContent || '';
  check(/Trade fair/.test(tv) && !/Beach holiday/.test(tv), '#2680: only the organisation\'s trip ' + tv.slice(0, 120));
  check(!d.querySelector('.lc-contracts') && !d.querySelector('.lc-budget') && d.querySelector('.lc-care'), '#2680: no contracts / budget card, staying in touch is there');
  const rail = d.querySelector('#srail [data-sbb="life"]');
  check(rail && /Travel & contacts/.test(rail.textContent), '#2680: the area is called "Travel & contacts" there ' + (rail && rail.textContent));
  check(!d.querySelector('#side [data-sbbpart="family"]') && !d.querySelector('#side [data-sbbpart="budget"]'), '#2680: family and budget not in the panel');
  w.eval(`S.settings.features = 'cal,comments,contacts,contracts,family'`);
  check(w.eval(`o3a_privOnly('life')`), '#2680: without travel and staying in touch Home stays private-only');
  w.close();

  // ================= the trip's bar: travel expenses
  w = await boot({user: 'alice', hash: 'l/' + ot.list_id}); d = w.document;
  await until(() => d.querySelector('.lifebar [data-act="life-tripcost"]'));
  check(d.querySelector('.lifebar [data-act="life-tripcost"]'), '#2680: "Travel expenses" on the trip (an admin, office on)');
  click(w, d.querySelector('.lifebar [data-act="life-tripcost"]'));
  await until(() => w.eval(`S.route.mod === 'office' && typeof RK === 'object' && !!RK.open`), 60);
  check(w.eval(`S.route.mod`) === 'office' && w.eval(`typeof RK === 'object' && RK.open`) > 0, '#2680: the office trip opens');
  const tr = await call('GET', '/api/office/trips');
  check((tr.trips || []).length === 1 && tr.trips[0].dest === 'Hamburg', '#2680: one office trip, filled from the trip');
  w.close();
  // 2.173.1 A (#2714): back on the trip the button says the expenses are linked
  w = await boot({user: 'alice', hash: 'l/' + ot.list_id}); d = w.document;
  await until(() => /Open travel expenses/.test(d.querySelector('.lifebar [data-act="life-tripcost"]')?.textContent || ''));
  check(/Open travel expenses/.test(d.querySelector('.lifebar [data-act="life-tripcost"]')?.textContent || ''), '#2714: "Open travel expenses" once linked');
  w.close();

  // ================= Private: Home with everything, its own trips
  await call('PATCH', '/api/settings', {workspace: 'private'});
  w = await boot({user: 'alice', hash: 'life'}); d = w.document;
  await until(() => d.querySelector('.lc-travel'));
  const pv = d.querySelector('.lc-travel')?.textContent || '';
  check(/Beach holiday/.test(pv) && !/Trade fair/.test(pv), '#2680: Private shows only the private trip');
  check(d.querySelector('.lc-contracts'), '#2680: Private keeps contracts');
  const rp = d.querySelector('#srail [data-sbb="life"]');
  check(rp && rp.textContent.trim() === 'Home', '#2680: Private: the area stays "Home" ' + (rp && rp.textContent));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
