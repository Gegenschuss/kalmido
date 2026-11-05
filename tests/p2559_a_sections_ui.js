// 2.559.0 UI tests, part A (#4659): sections are added and deleted at once (optimistic like #1501), jsdom, invented data:
// kalmido-suite: fresh
// - a new section shows its header while the answer is still held (a stand-in id below 0); a task moved into it meanwhile
//   waits for the real id (no request with the stand-in id), then lands in the real section; no GET /api/state follows
// - a refused new section is taken back with the server's message
// - a deleted section is gone at once (its task stays without a section); a refusal (500) brings it back with its task
// - a person without an organisation (freelancer parity): the new section shows at once, too
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
// requests matching re ("METHOD /url") wait in w.__held until go() / fail(text, status); every request lands in w.__log
// the live update's poll (GET /api/version every 4 s) waits while a test holds requests, so a GET /api/state it would start
// (its retry after a crossing write has no auto=1) is never mistaken for a consequence of the action; what is still on its
// way (a timeline the poll asked for) arrives before the action
const hold = async (w, re) => {
  if (w.__f1) w.fetch = w.__f1;  // the parked polls of a hold before go on first
  for (const v of w.__vers || []) v();
  await until(() => !w.eval('td_polling'));
  w.__held = []; w.__log = []; w.__resp = []; w.__vers = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => { const k = `${o.method || 'GET'} ${u}`; w.__log.push(k);
    if (/^GET \/api\/version\b/.test(k)) return new Promise(res => w.__vers.push(() => res(f1(u, o))));
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: (msg, st = 409) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))})) : f1(u, o); };
  await idle(w);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; for (const v of w.__vers || []) v(); w.__vers = []; };
const noState = w => !w.__log.some(k => /^GET \/api\/state\b/.test(k) && !/[?&]auto=1/.test(k));  // auto=1 = the live update's poll, no consequence of the action

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: []});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Kitchen'})).id;
  const S1 = (await call(CA, 'POST', '/api/sections', {list_id: L, name: 'Now'})).id;
  const T1 = (await call(CA, 'POST', '/api/tasks', {title: 'Clean the oven', list_id: L})).id;
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'New shelf', list_id: L, section_id: S1})).id;
  const secs = async (ck = CA) => ((await call(ck, 'GET', '/api/state')).sections || []).filter(s => s.list_id === L);

  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  const head = name => [...d.querySelectorAll('#view .ghead[data-section]')].find(h => h.textContent.includes(name));
  const secOf = id => row(id)?.closest('.group')?.querySelector('.ghead')?.dataset.section;
  check(await until(() => row(T1) && head('Now')), 'the list shows its section and rows');

  // ================= a new section shows at once
  await hold(w, /^POST \/api\/sections$/);
  w.eval(`window.__p = sectionCreate(${L}, 'Soon')`);
  check(await until(() => w.__held.length === 1), 'new section: the request is held');
  const tmp = +(head('Soon')?.dataset.section || 0);
  check(tmp < 0, 'new section: its header shows before the answer, with a stand-in id: ' + tmp);
  check(!(await secs()).some(s => s.name === 'Soon'), 'new section: the server has none yet');
  // a task moved into it meanwhile waits for the real id
  w.eval(`window.__m = taskToSection(${T1}, ${tmp})`);
  await sleep(0);
  check(!w.__log.some(k => /\/api\/tasks\/reorder/.test(k)), 'the move waits: no request while the section has no real id');
  w.__held[0].go();
  await w.eval('window.__p'); await w.eval('window.__m');
  const real = (await secs()).find(s => s.name === 'Soon')?.id;
  check(real > 0 && !w.eval('S.sections.some(s => s.id < 0)'), 'the answer swapped the stand-in for the real section ' + real);
  check(await until(() => secOf(T1) === String(real)), 'the task moved meanwhile stands in the real section');
  check(await until(async () => (await call(CA, 'GET', `/api/tasks/${T1}`)).section_id === real), 'the server has the task in it');
  check((await secs()).filter(s => s.name === 'Soon').length === 1, 'one new section on the server');
  check(!w.__log.some(k => /\/api\/(sections|tasks)\/-/.test(k)), 'no request carried the stand-in id: ' + w.__log.join(' | '));

  // ================= a refused new section is taken back
  await hold(w, /^POST \/api\/sections$/);
  w.eval(`window.__p = sectionCreate(${L}, 'Refused')`);
  check(await until(() => w.__held.length === 1 && head('Refused')), 'refused section: shown at once');
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => !head('Refused') && !w.eval(`S.sections.some(s => s.name === 'Refused')`)), 'refused section: the header goes again');
  check(await until(() => /Refused for the test/.test(d.querySelector('#toast')?.textContent || '')), 'refused section: with the server\'s message');
  await w.eval('window.__p');
  check(noState(w), 'refused section: no GET /api/state');

  // ================= a deleted section is gone at once; a refusal brings it back
  await hold(w, /^DELETE \/api\/sections\/\d+$/);
  w.eval(`window.__p = sectionDelete(${S1})`);
  check(await until(() => w.__held.length === 1 && !head('Now')), 'delete: the header is gone before the answer');
  check(secOf(T2) !== String(S1) && row(T2), 'delete: its task stays, without the section');
  w.__held[0].fail('Server trouble', 500);
  check(await until(() => head('Now') && secOf(T2) === String(S1)), 'delete refused (500): the section is back with its task');
  await w.eval('window.__p');
  check(noState(w), 'delete refused: no GET /api/state (put back, not reloaded)');
  await hold(w, /^DELETE \/api\/sections\/\d+$/);
  w.eval(`window.__p = sectionDelete(${S1})`);
  check(await until(() => w.__held.length === 1 && !head('Now')), 'delete again: gone at once');
  w.__held[0].go(); await w.eval('window.__p');
  check(!(await secs()).some(s => s.id === S1) && (await call(CA, 'GET', `/api/tasks/${T2}`)).section_id === null, 'delete: the server follows, the task stays');
  check(noState(w), 'delete: no GET /api/state');
  unhold(w);
  w.close();

  // ================= a person without an organisation: the new section at once
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Jobs'})).id;
  await call(CF, 'POST', '/api/sections', {list_id: LF, name: 'Inbox work'});
  await call(CF, 'POST', '/api/tasks', {title: 'Logo draft', list_id: LF});
  const wf = await boot({user: 'frida', hash: 'l/' + LF}), df = wf.document;
  const headF = name => [...df.querySelectorAll('#view .ghead[data-section]')].find(h => h.textContent.includes(name));
  check(await until(() => headF('Inbox work')), 'freelancer: the list shows');
  await hold(wf, /^POST \/api\/sections$/);
  wf.eval(`window.__p = sectionCreate(${LF}, 'Invoices')`);
  check(await until(() => wf.__held.length === 1 && +(headF('Invoices')?.dataset.section || 0) < 0), 'freelancer: the new section shows before the answer');
  wf.__held[0].go(); await wf.eval('window.__p');
  check(await until(() => +(headF('Invoices')?.dataset.section || 0) > 0), 'freelancer: it carries the real id');
  unhold(wf);
  wf.close();

  console.log(`p2559_a_sections_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
