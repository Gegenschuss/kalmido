// 2.559.0 UI tests, part C (#4660): the project status shows at once (optimistic as #1501), jsdom:
// kalmido-suite: fresh
// - the status dialog: Save closes it and the status (pill, list) shows while the server's answer is still held; no GET /api/state
// - the status select of the list dialog: the same; a refusal (500) puts the old status back with the server's message
// - a person without an organisation (freelancer parity): the status shows at once, too
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
const FEAT = 'comments,progress';
const stOf = async (ck, lid) => ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.id === lid)?.status || '';

(async () => {
  const CA = await setupAlice(FEAT);
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Garden'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Dig', list_id: L});

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  check(await until(() => d.querySelector('#view')), 'the list shows');
  await holdPoll(w);

  // ================= the status dialog: shown at once, the answer held
  hold(w, /^POST \/api\/lists\/\d+\/status$/);
  w.eval(`statusModal(${L})`);
  const opt = await until(() => d.querySelector('.stmodal .stopt[data-st="at_risk"]'));
  opt.click();
  d.querySelector('#st-note').value = 'Rain all week';
  d.querySelector('.stmodal [data-m="save"]').click();
  check(await until(() => w.__held.length === 1), 'status: the request is on its way (held)');
  const st0 = w.__st;
  check(!d.querySelector('.stmodal'), 'status: the dialog closed at once');
  check(w.eval(`listById(${L}).status`) === 'at_risk' && w.eval(`listById(${L}).status_note`) === 'Rain all week', 'status: the list carries it before the answer');
  check(await until(() => d.querySelector('.stpill.st-at_risk')), 'status: the pill shows it before the answer');
  check(await stOf(CA, L) === '', 'status: the server has none yet');
  w.__held[0].go();
  check(await until(async () => await stOf(CA, L) === 'at_risk'), 'status: the server follows');
  await idle(w);
  check(w.__st === st0, 'status: no GET /api/state for it (' + (w.__st - st0) + ')');
  check(w.eval(`listById(${L}).status`) === 'at_risk', 'status: stays after the answer');

  // ================= the list dialog's select: a refusal puts the old status back
  hold(w, /^POST \/api\/lists\/\d+\/status$/);
  w.eval(`window.__sel = {value: 'off_track'}; lmStatusSet(${L}, window.__sel)`);
  check(await until(() => w.__held.length === 1), 'select: the request is held');
  check(w.eval(`listById(${L}).status`) === 'off_track' && !!d.querySelector('.stpill.st-off_track'), 'select: off track shows at once');
  w.__held[0].fail('Refused for the test');
  check(await until(() => w.eval(`listById(${L}).status`) === 'at_risk' && d.querySelector('.stpill.st-at_risk') && !d.querySelector('.stpill.st-off_track')), 'select: the refusal puts at risk back');
  check(await toastHas(d, /Refused for the test/), 'select: with the server\'s message');
  check(w.eval(`window.__sel.value`) === 'at_risk', 'select: the field shows the old status again');
  check(await stOf(CA, L) === 'at_risk', 'select: the server kept at risk');
  unhold(w); freePoll(w);
  w.close();

  // ================= a person without an organisation: the same at once
  const CF = await setupFrida(CA, FEAT);
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Jobs'})).id;
  w = await boot({user: 'frida', hash: 'l/' + LF}); d = w.document;
  check(await until(() => d.querySelector('#view')), 'freelancer: the list shows');
  await holdPoll(w);
  hold(w, /^POST \/api\/lists\/\d+\/status$/);
  w.eval(`statusModal(${LF})`);
  (await until(() => d.querySelector('.stmodal .stopt[data-st="on_track"]'))).click();
  d.querySelector('.stmodal [data-m="save"]').click();
  check(await until(() => w.__held.length === 1), 'freelancer: the request is held');
  check(w.eval(`listById(${LF}).status`) === 'on_track' && !d.querySelector('.stmodal'), 'freelancer: shown at once, the dialog closed');
  w.__held[0].go(); unhold(w); freePoll(w);
  check(await until(async () => await stOf(CF, LF) === 'on_track'), 'freelancer: the server follows');
  w.close();

  console.log(`p2559_c_status_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
