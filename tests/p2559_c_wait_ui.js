// 2.559.0 UI tests, part C (#4660): "Waiting on someone" set / ended shows at once (optimistic as #1501), jsdom:
// kalmido-suite: fresh
// - the waiting dialog: Save closes it and the task panel shows the waiting bar while the server's answer is still held;
//   no GET /api/state for it
// - "No longer waiting": the bar goes at once; a refusal (500) brings it back with the server's message
// - a person without an organisation (freelancer parity): the same at once
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
// the page's requests: those matching re ("METHOD /url") wait in w.__held until go() (the real request) or fail() (a 500 with
// the text); every GET /api/state is counted (w.__st). The change poll is held meanwhile (holdPoll): a poll of its own that saw
// the new server version would count as a GET /api/state of the action
const hold = (w, re) => {
  w.__held = []; w.__st = w.__st || 0; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => {
    const k = `${(o.method || 'GET').toUpperCase()} ${u}`;
    if (/^GET \/api\/state/.test(k)) w.__st++;
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: msg => res(new Response(JSON.stringify({error: msg}), {status: 500, headers: {'content-type': 'application/json'}}))})) : f1(u, o);
  };
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
const holdPoll = w => until(() => w.eval('td_polling ? false : (td_polling = true)'));
const freePoll = w => w.eval('td_polling = false');
const toastHas = (d, re) => until(() => re.test(d.querySelector('#toast')?.textContent || ''));
const setupAlice = async features => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features});
  return CA;
};
// a person without an organisation (freelancer parity)
const setupFrida = async (CA, features) => {
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  return CF;
};
const FEAT = 'comments,deps';
const waitOf = async (ck, id) => (await call(ck, 'GET', `/api/tasks/${id}`)).wait_note || '';

(async () => {
  const CA = await setupAlice(FEAT);
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Kitchen', kind: 'project'})).id;
  const A = (await call(CA, 'POST', '/api/tasks', {title: 'Order the worktop', list_id: L})).id;

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${A})`);
  check(await until(() => d.querySelector('#detail [data-act="wait-edit"], #detail [data-act="wait-on"]')), 'the task panel shows');
  await holdPoll(w);

  // ================= set: shown at once, the answer held
  hold(w, /^PUT \/api\/tasks\/\d+\/waiting$/);
  w.eval(`waitDialog(${A})`);
  const md = await until(() => d.querySelector('.waitmodal'));
  md.querySelector('#w-note').value = 'Quote from the carpenter';
  md.querySelector('[data-m="ok"]').click();
  check(await until(() => w.__held.length === 1), 'set: the request is on its way (held)');
  const st0 = w.__st;
  check(!d.querySelector('.waitmodal'), 'set: the dialog closed at once');
  check(w.eval(`!!S.tasks.get(${A}).waiting_at && S.tasks.get(${A}).wait_note`) === 'Quote from the carpenter', 'set: the task carries it before the answer');
  check(await until(() => /Quote from the carpenter/.test(d.querySelector('#detail .waitbar')?.textContent || '')), 'set: the waiting bar shows before the answer');
  check(await waitOf(CA, A) === '', 'set: the server has nothing yet');
  w.__held[0].go();
  check(await until(async () => await waitOf(CA, A) === 'Quote from the carpenter'), 'set: the server follows');
  await idle(w);
  check(w.__st === st0, 'set: no GET /api/state for it (' + (w.__st - st0) + ')');
  check(!!d.querySelector('#detail .waitbar'), 'set: the bar stays after the answer');

  // ================= end: gone at once, a refusal brings it back
  hold(w, /^DELETE \/api\/tasks\/\d+\/waiting$/);
  d.querySelector('#detail .waitbar [data-act="wait-clear"]').click();
  check(await until(() => w.__held.length === 1), 'end: the request is held');
  check(await until(() => !d.querySelector('#detail .waitbar')) && w.eval(`!S.tasks.get(${A}).waiting_at`), 'end: the bar is gone at once');
  w.__held[0].fail('Refused for the test');
  check(await until(() => /Quote from the carpenter/.test(d.querySelector('#detail .waitbar')?.textContent || '')), 'end: the refusal brings the bar back');
  check(await toastHas(d, /Refused for the test/), 'end: with the server\'s message');
  check(await waitOf(CA, A) === 'Quote from the carpenter', 'end: the server kept it');
  // and ended for real
  hold(w, /^DELETE \/api\/tasks\/\d+\/waiting$/);
  d.querySelector('#detail .waitbar [data-act="wait-clear"]').click();
  check(await until(() => w.__held.length === 1 && !d.querySelector('#detail .waitbar')), 'end again: gone at once');
  const st1 = w.__st;
  w.__held[0].go();
  check(await until(async () => await waitOf(CA, A) === ''), 'end: the server follows');
  await idle(w);
  check(w.__st === st1, 'end: no GET /api/state for it');
  unhold(w); freePoll(w);
  w.close();

  // ================= a person without an organisation: the same at once
  const CF = await setupFrida(CA, FEAT);
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Jobs', kind: 'project'})).id;
  const FA = (await call(CF, 'POST', '/api/tasks', {title: 'Logo', list_id: LF})).id;
  w = await boot({user: 'frida', hash: 'l/' + LF}); d = w.document;
  w.eval(`openDetail(${FA})`);
  check(await until(() => d.querySelector('#detail [data-act="wait-edit"], #detail [data-act="wait-on"]')), 'freelancer: the task panel shows');
  await holdPoll(w);
  hold(w, /^PUT \/api\/tasks\/\d+\/waiting$/);
  w.eval(`waitDialog(${FA})`);
  const mf = await until(() => d.querySelector('.waitmodal'));
  mf.querySelector('#w-note').value = 'Client approval';
  mf.querySelector('[data-m="ok"]').click();
  check(await until(() => w.__held.length === 1), 'freelancer: the request is held');
  check(await until(() => /Client approval/.test(d.querySelector('#detail .waitbar')?.textContent || '')) && !d.querySelector('.waitmodal'), 'freelancer: shown at once');
  w.__held[0].go(); unhold(w); freePoll(w);
  check(await until(async () => await waitOf(CF, FA) === 'Client approval'), 'freelancer: the server follows');
  w.close();

  console.log(`p2559_c_wait_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
