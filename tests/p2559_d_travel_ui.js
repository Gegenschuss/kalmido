// 2.559.0 UI tests, part D (#4660): trips, their receipts and the tick "in DATEV" show at once (optimistic), own container
// kalmido-suite: fresh
// (start.sh, mode workspaces), jsdom. Invented places, people and figures only. Run for a member of an organisation and
// for a person without an organisation (freelancer parity, the own office).
// - New trip: the dialog closes and the trip (provisional id) opens while the answer is held; a refusal (500) takes it away
//   with the server's message; let through, the trip carries the real id
// - Edit trip: the head shows the new destination before the answer; a refusal (400) puts the old one back
// - Add receipt: the receipt and the new sum show before the answer; a refusal takes it away
// - the tick "in DATEV": checked before the answer; a refusal (409) unticks it
// - Delete (row menu): the row goes at once; a refusal brings it back; let through, "Deleted" with undo
// - none of these actions fetches the whole state again (no GET /api/state), no "Loading…" in between
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients';
const DAY = TC.today();
// requests matching re ("METHOD /url") wait in w.__held until the test calls go() (the real request) or fail(text, status)
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => re.test(`${o.method || 'GET'} ${u}`)
    ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: (msg, st = 400) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))}))
    : f1(u, o);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
// every request of the page in w.__sent (to see that no action fetches the whole state again)
const watch = w => { w.__sent = []; const f0 = w.fetch; w.fetch = (u, o = {}) => { w.__sent.push(`${o.method || 'GET'} ${u}`); return f0(u, o); }; };
// (the live update's poll is no action: GET /api/state?auto=1 and the up to two repeats load() makes when a write crossed it)
const stateFetches = w => { let rep = 0; return w.__sent.filter(s => { if (!/^GET \/api\/state(\?|$)/.test(s)) return false; if (/auto=1/.test(s)) { rep = 2; return false; } if (rep) { rep--; return false; } return true; }); };

async function round(who, ck) {
  const kiel = await call(ck, 'POST', '/api/office/trips', {date_from: DAY, dest: 'Kiel', people: [], items: [{date: DAY, category: 'train', amount: 40}]});
  check(kiel.http === 201 && kiel.items?.length === 1, `${who}: a trip with one receipt ${kiel.http}`);
  const trips = async () => (await call(ck, 'GET', `/api/office/trips?year=${DAY.slice(0, 4)}`)).trips || [];
  const tripOf = async id => (await trips()).find(t => t.id === id);

  const w = await boot({user: who, hash: 'office/travel'}), d = w.document;
  const dlg = () => d.querySelector('.modal.ofcdlg');
  const rowOf = re => [...d.querySelectorAll('.rklist [data-rk="open"]')].find(b => re.test(b.textContent));
  const head = () => d.querySelector('.rkhead h3')?.textContent || '';
  const toastHas = re => re.test(d.querySelector('#toast')?.textContent || '');
  const loading = () => /Loading…/.test(d.querySelector('.ofcbody')?.textContent || '');
  const back = async () => { click(w, d.querySelector('[data-rk="back"]')); return until(() => d.querySelector('.rklist')); };
  check(await until(() => rowOf(/Kiel/) && d.querySelector('[data-rk="new"]')), `${who}: the travel tab lists the trip`);
  watch(w);

  // ================= new trip: at once (opened), a refusal takes it away
  const add = async () => {
    click(w, d.querySelector('[data-rk="new"]')); await until(() => dlg()?.querySelector('#rk-dest'));
    dlg().querySelector('#rk-dest').value = 'Bremen'; click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^POST \/api\/office\/trips$/);
  await add();
  check(await until(() => w.__held.length === 1), `${who}: New trip: the request is held`);
  check(!dlg() && head() === 'Bremen' && w.eval('RK.open') < 0 && !loading(), `${who}: the dialog closed and the trip (provisional id) is open before the answer`);
  check(!(await trips()).some(t => t.dest === 'Bremen'), `${who}: the server has no trip yet`);
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => !d.querySelector('.rkhead') && d.querySelector('.rklist') && !rowOf(/Bremen/) && rowOf(/Kiel/)), `${who}: the refusal takes it away, the list is back`);
  check(await until(() => toastHas(/Refused for the test/)), `${who}: with the server's message`);
  await add();
  check(await until(() => w.__held.length === 2), `${who}: the second New trip is held`);
  check(!dlg() && head() === 'Bremen', `${who}: shown at once again`);
  w.__held[1].go();
  check(await until(async () => (await trips()).some(t => t.dest === 'Bremen')), `${who}: the server stores the trip`);
  check(await until(() => w.eval('RK.open') > 0 && head() === 'Bremen'), `${who}: the open trip carries the real id`);
  check(await until(() => toastHas(/Added/)), `${who}: "Added" with undo after the answer`);
  unhold(w);
  await back();

  // ================= edit trip: at once, a refusal puts the old destination back
  click(w, rowOf(/Kiel/));
  check(await until(() => head() === 'Kiel' && d.querySelectorAll('.rkits .rkit').length === 1), `${who}: the trip Kiel opens with its receipt`);
  const edit = async () => {
    click(w, d.querySelector('[data-rk="edit"]')); await until(() => dlg()?.querySelector('#rk-dest')?.value === 'Kiel');
    dlg().querySelector('#rk-dest').value = 'Kiel Nord'; click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^PATCH \/api\/office\/trips\/\d+$/);
  await edit();
  check(await until(() => w.__held.length === 1), `${who}: Edit trip: the request is held`);
  check(!dlg() && head() === 'Kiel Nord' && !loading(), `${who}: the head shows the new destination before the answer`);
  w.__held[0].fail('Refused for the test');
  check(await until(() => head() === 'Kiel'), `${who}: the refusal puts the old destination back`);
  check(await until(() => toastHas(/Refused for the test/)), `${who}: with the server's message`);
  await edit();
  check(await until(() => w.__held.length === 2), `${who}: the second Save is held`);
  w.__held[1].go();
  check(await until(async () => (await tripOf(kiel.id))?.dest === 'Kiel Nord'), `${who}: the server stores the destination`);
  check(await until(() => toastHas(/Saved/) && head() === 'Kiel Nord'), `${who}: "Saved" after the answer, the head keeps it`);
  unhold(w);

  // ================= add receipt: the receipt and the sum at once, a refusal takes it away
  const sum = () => [...d.querySelectorAll('.ofcbar')].find(x => x.querySelector('b')?.textContent === 'Receipts')?.querySelector('.muted')?.textContent || '';
  const addIt = async () => {
    click(w, d.querySelector('[data-rk="add"]')); await until(() => dlg()?.querySelector('#rk-amt'));
    dlg().querySelector('#rk-amt').value = '20'; dlg().querySelector('#rk-text').value = 'Taxi'; click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^POST \/api\/office\/trips\/\d+\/items$/);
  await addIt();
  check(await until(() => w.__held.length === 1), `${who}: Add receipt: the request is held`);
  check(!dlg() && d.querySelectorAll('.rkits .rkit').length === 2 && /Taxi/.test(d.querySelector('.rkits').textContent) && /60[.,]00/.test(sum()),
    `${who}: the receipt and the sum 60.00 show before the answer: ` + sum());
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => d.querySelectorAll('.rkits .rkit').length === 1 && /40[.,]00/.test(sum())), `${who}: the refusal takes it away, the sum is back`);
  await addIt();
  check(await until(() => w.__held.length === 2), `${who}: the second Add receipt is held`);
  w.__held[1].go();
  check(await until(async () => (await tripOf(kiel.id))?.items.length === 2), `${who}: the server stores the receipt`);
  check(await until(() => [...d.querySelectorAll('.rkits [data-rk="item"]')].every(b => +b.dataset.id > 0) && /60[.,]00/.test(sum())), `${who}: the receipt carries the real id, the sum stays`);
  unhold(w);

  // ================= the tick "in DATEV": at once, a refusal unticks it
  const box = () => d.querySelector('.rkits [data-rk="datev"]');
  check(await until(() => box() && !box().checked), `${who}: the tick "in DATEV" is there, not ticked`);
  hold(w, /^PATCH \/api\/office\/trips\/\d+\/items\/\d+$/);
  click(w, box());
  check(await until(() => w.__held.length === 1), `${who}: the tick: the request is held`);
  check(box()?.checked && !loading(), `${who}: ticked before the answer`);
  w.__held[0].fail('The month is locked', 409);
  check(await until(() => box() && !box().checked), `${who}: the refusal unticks it`);
  check(await until(() => toastHas(/The month is locked/)), `${who}: with the server's message`);
  click(w, box());
  check(await until(() => w.__held.length === 2), `${who}: the second tick is held`);
  w.__held[1].go();
  check(await until(async () => (await tripOf(kiel.id))?.items.filter(i => i.datev).length === 1), `${who}: the server stores the tick`);
  check(await until(() => toastHas(/Ticked as in DATEV/) && box()?.checked), `${who}: the toast after the answer, the box stays ticked`);
  unhold(w);
  await back();

  // ================= delete from the row menu: at once, a refusal brings the row back
  const del = async () => {
    click(w, rowOf(/Bremen/).closest('li').querySelector('[data-rk="rowmore"]'));
    await until(() => [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Delete'));
    click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Delete'));
    await until(() => d.querySelector('[data-cd="yes"]')); click(w, d.querySelector('[data-cd="yes"]'));
  };
  hold(w, /^DELETE \/api\/office\/trips\/\d+$/);
  await del();
  check(await until(() => w.__held.length === 1), `${who}: Delete: the request is held`);
  check(!rowOf(/Bremen/) && rowOf(/Kiel/) && !loading(), `${who}: the row is gone before the answer`);
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => rowOf(/Bremen/)), `${who}: the refusal brings the row back`);
  await del();
  check(await until(() => w.__held.length === 2), `${who}: the second Delete is held`);
  w.__held[1].go();
  check(await until(async () => !(await trips()).some(t => t.dest === 'Bremen')), `${who}: the server deleted it`);
  check(await until(() => toastHas(/Deleted|Moved to the trash/) && !rowOf(/Bremen/)), `${who}: "Deleted" with undo after the answer`);  // 2.925.0 (#5454): the trash says so
  unhold(w);
  await sleep(300);  // a reload the actions might start would be on its way by now
  check(!stateFetches(w).length, `${who}: no action fetched the whole state again: ` + stateFetches(w).join(' | ') + ' (all: ' + w.__sent.join(' ; ') + ')');
  w.close();
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await round('alice', CA);

  // ================= a person without an organisation (the own office): the same at once
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  await round('frida', CF);

  console.log(`p2559_d_travel_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
