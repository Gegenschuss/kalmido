// 2.559.0 UI tests, part C (#4660): tasks moved into a sprint / the backlog show at once (optimistic as #1501), jsdom:
// kalmido-suite: fresh
// - spr_assign (task menu, multi-selection, drop on the header): the tasks carry the sprint and the sprint header counts them
//   while the server's answer is still held; no GET /api/state for it; one undo step as before
// - back to the backlog: a refusal (500) puts the tasks back into the sprint with the server's message
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
const FEAT = 'comments,kanban,progress';
const sprOf = async (ck, id) => (await call(ck, 'GET', `/api/tasks/${id}`)).sprint_id || null;
const head = d => d.querySelector('#view .sprh .sprp')?.textContent || '';

const run = async (ck, user, who) => {
  const L = (await call(ck, 'POST', '/api/lists', {name: 'Product ' + who, kind: 'project'})).id;
  const S1 = (await call(ck, 'PUT', `/api/lists/${L}/sprint-settings`, {on: true})).started_id;
  const A = (await call(ck, 'POST', '/api/tasks', {title: 'Login page', list_id: L})).id, Bt = (await call(ck, 'POST', '/api/tasks', {title: 'Signup mail', list_id: L})).id;
  check(S1 > 0, who + ': a running sprint');
  const w = await boot({user, hash: 'l/' + L}), d = w.document;
  check(await until(() => d.querySelector(`#view [data-id="${A}"]`) && d.querySelector('#view .sprh')), who + ': the list shows its sprint header');
  await w.eval(`loadModule('sprints')`);
  await holdPoll(w);

  // ================= into the sprint: shown at once, the answer held
  hold(w, /^POST \/api\/tasks\/batch$/);
  const h0 = w.eval('HIST.undo.length');
  w.eval(`spr_assign([${A}, ${Bt}], ${S1})`);
  check(await until(() => w.__held.length === 1), who + ': the request is on its way (held)');
  const st0 = w.__st;
  check(w.eval(`S.tasks.get(${A}).sprint_id === ${S1} && S.tasks.get(${Bt}).sprint_id === ${S1}`), who + ': the tasks carry the sprint before the answer');
  check(await until(() => /0 of 2/.test(head(d))), who + ': the sprint header counts them before the answer: ' + head(d));
  check(await sprOf(ck, A) === null, who + ': the server has them in the backlog still');
  w.__held[0].go();
  check(await until(async () => await sprOf(ck, A) === S1 && await sprOf(ck, Bt) === S1), who + ': the server follows');
  check(await until(() => w.eval('HIST.undo.length') === h0 + 1), who + ': one undo step');
  check(await until(() => w.eval(`SPR.j[${S1}]?.j?.progress?.total`) === 2 && /0 of 2/.test(head(d))), who + ': the header asks the server again after the answer (not its figures of before): ' + head(d));
  await idle(w);
  check(w.__st === st0, who + ': no GET /api/state for it (' + (w.__st - st0) + ')');

  // ================= back to the backlog: a refusal puts them back
  hold(w, /^POST \/api\/tasks\/batch$/);
  w.eval(`spr_assign([${A}], null)`);
  check(await until(() => w.__held.length === 1), who + ': backlog: the request is held');
  check(w.eval(`S.tasks.get(${A}).sprint_id`) === null && await until(() => /0 of 1/.test(head(d))), who + ': backlog: out of the sprint at once');
  w.__held[0].fail('Refused for the test');
  check(await until(() => w.eval(`S.tasks.get(${A}).sprint_id`) === S1 && /0 of 2/.test(head(d))), who + ': backlog: the refusal puts it back');
  check(await toastHas(d, /Refused for the test/), who + ': backlog: with the server\'s message');
  check(await sprOf(ck, A) === S1, who + ': backlog: the server kept it');
  unhold(w); freePoll(w);
  w.close();
};

(async () => {
  const CA = await setupAlice(FEAT);
  await run(CA, 'alice', 'alice');
  const CF = await setupFrida(CA, FEAT);
  await run(CF, 'frida', 'freelancer');
  console.log(`p2559_c_sprints_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
