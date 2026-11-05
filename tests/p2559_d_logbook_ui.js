// 2.559.0 UI tests, part D (#4660): drives of the logbook are added, changed and deleted at once (optimistic), own
// kalmido-suite: fresh
// container (start.sh, mode workspaces), jsdom. Invented places, people and figures only. Run for a member of an
// organisation and for a person without an organisation (freelancer parity, the own office).
// - New drive: the dialog closes and the row (provisional id) shows while the answer is still held; a refusal (500) takes it
//   away with the server's message; let through, the row carries the real id and the server's warning (a gap of the
//   odometer) comes as the toast after the answer
// - Change: the dialog closes, the row shows the new destination before the answer; a refusal (400) puts the old one back
// - Delete: the row goes at once; a refusal (409) brings it back; let through, "Deleted" with undo
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
const stateFetches = w => { let rep = 0; return w.__sent.filter(s => { if (!/^GET \/api\/state(\?|$)/.test(s)) return false; if (/auto=1/.test(s)) { rep = 2; return false; } if (rep) { rep--; return false; } return true; }); };  // the live poll (auto=1) and load()'s up to two repeats when a write crossed it are no reload of the action

async function round(who, ck) {
  const veh = await call(ck, 'POST', '/api/office/vehicles', {name: 'Kombi', kind: 'private', odo_start: '1000'});
  check(veh.http === 201, `${who}: a vehicle ${veh.http}`);
  const kiel = await call(ck, 'POST', '/api/office/drives', {vehicle_id: veh.id, day: DAY, start_place: 'Hamburg', dest: 'Kiel', purpose: 'Dreh', odo_start: 1000, odo_end: 1100, km: 100, kind: 'business'});
  check(kiel.http === 201, `${who}: a drive ${kiel.http}`);
  const onServer = async () => (await call(ck, 'GET', `/api/office/drives?year=${DAY.slice(0, 4)}&vehicle_id=${veh.id}`)).drives || [];

  const w = await boot({user: who, hash: 'office/travel'}), d = w.document;
  const dlg = () => d.querySelector('.modal.ofcdlg');
  const rowOf = re => [...d.querySelectorAll('.lgb-list [data-lgb="open"]')].find(b => re.test(b.textContent));
  const toastHas = re => re.test(d.querySelector('#toast')?.textContent || '');
  const loading = () => /Loading…/.test(d.querySelector('.ofcbody')?.textContent || '');
  check(await until(() => d.querySelector('[data-rk="view"][data-v="logbook"]')), `${who}: the travel tab has the logbook`);
  click(w, d.querySelector('[data-rk="view"][data-v="logbook"]'));
  check(await until(() => rowOf(/Kiel/) && d.querySelector('[data-lgb="new"]')), `${who}: the logbook shows the drive`);
  watch(w);

  // ================= new drive: at once, a refusal takes the row away; the warning after the answer
  const add = async () => {
    click(w, d.querySelector('[data-lgb="new"]')); await until(() => dlg()?.querySelector('#lgb-o1'));
    const m = dlg(); m.querySelector('#lgb-start').value = 'Kiel'; m.querySelector('#lgb-dest').value = 'Lübeck';
    m.querySelector('#lgb-o0').value = '1200'; m.querySelector('#lgb-o1').value = '1250'; m.querySelector('#lgb-km').value = '50';
    click(w, m.querySelector('[data-m="save"]'));
  };
  hold(w, /^POST \/api\/office\/drives$/);
  await add();
  check(await until(() => w.__held.length === 1), `${who}: New drive: the request is held`);
  check(!dlg() && rowOf(/Lübeck/) && +rowOf(/Lübeck/).dataset.id < 0 && /50 km/.test(rowOf(/Lübeck/).textContent), `${who}: the dialog closed and the row (provisional id, 50 km) shows before the answer`);
  check(!loading() && rowOf(/Kiel.*Dreh|Hamburg/), `${who}: the other drive stays, no "Loading…"`);
  check(!(await onServer()).some(x => x.dest === 'Lübeck'), `${who}: the server has no drive yet`);
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => !rowOf(/Lübeck/)), `${who}: the refusal takes the row away`);
  check(await until(() => toastHas(/Refused for the test/)), `${who}: with the server's message`);
  await add();
  check(await until(() => w.__held.length === 2), `${who}: the second New drive is held`);
  check(!dlg() && rowOf(/Lübeck/) && !toastHas(/Gap of/), `${who}: shown at once again, no warning before the answer`);
  w.__held[1].go();
  check(await until(async () => (await onServer()).some(x => x.dest === 'Lübeck')), `${who}: the server stores the drive`);
  check(await until(() => +rowOf(/Lübeck/)?.dataset.id > 0), `${who}: the row carries the real id`);
  check(await until(() => toastHas(/Gap of 100 km to the previous drive/)), `${who}: the server's warning comes as the toast after the answer`);
  check(await until(() => /Gap of 100 km/.test(rowOf(/Lübeck/)?.textContent || '')), `${who}: the row shows the warning`);
  unhold(w);

  // ================= change: at once, a refusal puts the old destination back
  const edit = async () => {
    click(w, rowOf(/Hamburg/)); await until(() => dlg()?.querySelector('#lgb-dest')?.value === 'Kiel');
    dlg().querySelector('#lgb-dest').value = 'Kiel Hafen'; click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^PATCH \/api\/office\/drives\/\d+$/);
  await edit();
  check(await until(() => w.__held.length === 1), `${who}: Save: the request is held`);
  check(!dlg() && /Kiel Hafen/.test(rowOf(/Hamburg/)?.textContent || '') && !loading(), `${who}: the dialog closed, the row shows the new destination before the answer`);
  w.__held[0].fail('Refused for the test');
  check(await until(() => rowOf(/Hamburg/) && !/Kiel Hafen/.test(rowOf(/Hamburg/).textContent)), `${who}: the refusal puts the old destination back`);
  check(await until(() => toastHas(/Refused for the test/)), `${who}: with the server's message`);
  await edit();
  check(await until(() => w.__held.length === 2), `${who}: the second Save is held`);
  w.__held[1].go();
  check(await until(async () => (await onServer()).find(x => x.id === kiel.id)?.dest === 'Kiel Hafen'), `${who}: the server stores the destination`);
  check(await until(() => toastHas(/Saved/)), `${who}: "Saved" after the answer`);
  unhold(w);

  // ================= saved elsewhere meanwhile (#4700 on the at-once path): the row goes back, the dialog opens again with the input and "Reload"
  check(await until(() => (LBrow => LBrow && LBrow.updated_at)(w.eval(`LB.drives.find(x => x.id === ${kiel.id})`))), `${who}: the row knows its version`);
  const was = w.eval(`LB.drives.find(x => x.id === ${kiel.id}).updated_at`);
  let o = null;
  check(await until(async () => { o = await call(ck, 'PATCH', `/api/office/drives/${kiel.id}`, {purpose: 'Other tab'}); return o.http === 200 && o.updated_at && o.updated_at !== was; }), `${who}: another tab saved the drive`);
  click(w, rowOf(/Hamburg/)); await until(() => dlg()?.querySelector('#lgb-dest')?.value === 'Kiel Hafen');
  dlg().querySelector('#lgb-dest').value = 'Kiel Nord'; click(w, dlg().querySelector('[data-m="save"]'));
  check(await until(() => dlg()?.querySelector('[data-ofc-reload]')), `${who}: conflict: the dialog is open again with "Reload"`);
  check(dlg()?.querySelector('#lgb-dest')?.value === 'Kiel Nord' && /Changed in the meantime/.test(dlg()?.querySelector('.aerr')?.textContent || ''), `${who}: conflict: with the input of the person and the bar`);
  check(await until(async () => (await onServer()).find(x => x.id === kiel.id)?.dest === 'Kiel Hafen'), `${who}: conflict: nothing was overwritten`);
  check(await until(() => rowOf(/Hamburg/) && !/Kiel Nord/.test(rowOf(/Hamburg/).textContent)), `${who}: conflict: the row is back`);
  click(w, dlg().querySelector('[data-ofc-reload]'));
  check(await until(() => dlg()?.querySelector('#lgb-dest')?.value === 'Kiel Hafen'), `${who}: Reload opens the saved drive`);
  click(w, dlg()?.querySelector('[data-m="cancel"], .xclose, [data-m="close"]')); dlg()?.remove();

  // ================= delete: at once, a refusal brings the row back
  const del = async () => {
    click(w, rowOf(/Hamburg/)); await until(() => dlg()?.querySelector('[data-m="del"]'));
    click(w, dlg().querySelector('[data-m="del"]'));
  };
  hold(w, /^DELETE \/api\/office\/drives\/\d+$/);
  await del();
  check(await until(() => w.__held.length === 1), `${who}: Delete: the request is held`);
  check(!dlg() && !rowOf(/Hamburg/) && rowOf(/Lübeck/), `${who}: the dialog closed and the row is gone before the answer`);
  w.__held[0].fail('This drive is closed', 409);
  check(await until(() => rowOf(/Hamburg/)), `${who}: the refusal brings the row back`);
  check(await until(() => toastHas(/This drive is closed/)), `${who}: with the server's message`);
  await del();
  check(await until(() => w.__held.length === 2), `${who}: the second Delete is held`);
  check(!rowOf(/Hamburg/), `${who}: gone at once again`);
  w.__held[1].go();
  check(await until(async () => !(await onServer()).some(x => x.id === kiel.id)), `${who}: the server deleted it`);
  check(await until(() => toastHas(/Deleted/)), `${who}: "Deleted" with undo after the answer`);
  unhold(w);
  await sleep(300);  // a reload the actions might start would be on its way by now
  check(!stateFetches(w).length, `${who}: no action fetched the whole state again: ` + stateFetches(w).join(' | '));
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

  console.log(`p2559_d_logbook_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
