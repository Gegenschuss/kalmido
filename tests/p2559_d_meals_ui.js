// 2.559.0 UI tests, part D (#4660): entertainment receipts are saved as a draft, duplicated and deleted at once
// kalmido-suite: fresh
// (optimistic), own container (start.sh, mode workspaces), jsdom. Invented places, people and figures only.
// - New receipt, "Save draft": the dialog closes and the row (provisional id, its sum) shows while the answer is held; a
//   refusal (500) takes it away with the server's message; let through, the row carries the real id
// - Edit, "Save draft": the row shows the new occasion before the answer; a refusal (400) puts the old one back
// - Duplicate (row menu): the copy shows at once; let through, the dialog opens with the stored copy
// - Delete (row menu): the row goes at once; a refusal (409) brings it back; let through, "Deleted" with undo
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

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const ck = await login('alice');
  await call(ck, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(ck, 'GET', '/api/state')).me;
  const org = await call(ck, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const y = DAY.slice(0, 4);
  const osteria = await call(ck, 'POST', '/api/office/meals', {date: DAY, place_name: 'Osteria Beispiel', occasion: 'Kick-off of the film', amounts: [{kind: 'food', rate: '7', gross: 50}]});
  check(osteria.http === 201, 'a draft receipt ' + osteria.http);
  const meals = async () => (await call(ck, 'GET', `/api/office/meals?year=${y}`)).meals || [];

  const w = await boot({user: 'alice', hash: 'office/meals'}), d = w.document;
  const dlg = () => d.querySelector('.modal.bwdlg');
  const rowOf = re => [...d.querySelectorAll('.bwlist [data-bw="open"]')].find(b => re.test(b.textContent));
  const toastHas = re => re.test(d.querySelector('#toast')?.textContent || '');
  const loading = () => /Loading…/.test(d.querySelector('.ofcbody')?.textContent || '');
  const nTr0 = () => [...d.querySelectorAll('.bwlist [data-bw="open"]')].filter(b => /Trattoria Neu/.test(b.textContent)).length;  // 2.651.0 (#5076)
  const menuPick = async (re, label) => {
    click(w, rowOf(re).closest('li').querySelector('[data-bw="rowmore"]'));
    const b = await until(() => [...d.querySelectorAll('#pop .menu-list button')].find(x => x.textContent.trim() === label));
    click(w, b);
  };
  check(await until(() => rowOf(/Osteria Beispiel/) && d.querySelector('[data-bw="new"]')), 'the tab lists the draft');
  watch(w);

  // ================= new receipt: at once, a refusal takes the row away
  const add = async () => {
    click(w, d.querySelector('[data-bw="new"]')); await until(() => dlg()?.querySelector('#bw-pname'));
    const m = dlg(); m.querySelector('#bw-pname').value = 'Trattoria Neu'; m.querySelector('#bw-occ').value = 'Planning of the shoot';
    m.querySelector('[data-bwl="gross"]').value = '30'; click(w, m.querySelector('[data-bwm="save"]'));
  };
  hold(w, /^POST \/api\/office\/meals$/);
  await add();
  check(await until(() => w.__held.length === 1), 'New receipt: the request is held');
  check(!dlg() && rowOf(/Trattoria Neu/) && +rowOf(/Trattoria Neu/).dataset.id < 0 && /30[.,]00/.test(rowOf(/Trattoria Neu/).textContent) && !loading(),
    'the dialog closed and the row (provisional id, 30.00) shows before the answer: ' + (rowOf(/Trattoria Neu/)?.textContent || ''));
  check(rowOf(/Osteria Beispiel/), 'the other receipt stays');
  check(!(await meals()).some(m => m.place_name === 'Trattoria Neu'), 'the server has no receipt yet');
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => !rowOf(/Trattoria Neu/)), 'the refusal takes the row away');
  check(await until(() => toastHas(/Refused for the test/)), 'with the server\'s message');
  await add();
  check(await until(() => w.__held.length === 2), 'the second New receipt is held');
  check(!dlg() && rowOf(/Trattoria Neu/), 'shown at once again');
  w.__held[1].go();
  check(await until(async () => (await meals()).some(m => m.place_name === 'Trattoria Neu' && m.calc.gross === '30.00')), 'the server stores the receipt');
  check(await until(() => +rowOf(/Trattoria Neu/)?.dataset.id > 0), 'the row carries the real id');
  check(await until(() => toastHas(/Added/)), '"Added" with undo after the answer');
  unhold(w);

  // ================= edit: at once, a refusal puts the old occasion back
  const edit = async () => {
    click(w, rowOf(/Osteria Beispiel/)); await until(() => dlg()?.querySelector('#bw-occ')?.value === 'Kick-off of the film');
    dlg().querySelector('#bw-occ').value = 'Follow-up order'; click(w, dlg().querySelector('[data-bwm="save"]'));
  };
  hold(w, /^PATCH \/api\/office\/meals\/\d+$/);
  await edit();
  check(await until(() => w.__held.length === 1), 'Save draft: the request is held');
  check(!dlg() && /Follow-up order/.test(rowOf(/Osteria Beispiel/)?.textContent || '') && !loading(), 'the dialog closed, the row shows the new occasion before the answer');
  w.__held[0].fail('Refused for the test');
  check(await until(() => /Kick-off of the film/.test(rowOf(/Osteria Beispiel/)?.textContent || '')), 'the refusal puts the old occasion back');
  await edit();
  check(await until(() => w.__held.length === 2), 'the second Save draft is held');
  w.__held[1].go();
  check(await until(async () => (await meals()).find(m => m.id === osteria.id)?.occasion === 'Follow-up order'), 'the server stores the occasion');
  check(await until(() => toastHas(/Saved/) && /Follow-up order/.test(rowOf(/Osteria Beispiel/)?.textContent || '')), '"Saved" after the answer, the row keeps it');
  unhold(w);

  // ================= duplicate: the copy at once, the dialog with the stored copy after the answer
  // 2.651.0 (#5076, CI red "the row is gone before the answer"): a state of the app fetched before the copy and arriving after
  // it (the live update the write itself set off) put the copy's provisional row in once more (OPT_DONE, 2.607.0); fetched
  // here from outside the page (no request of the page, see stateFetches)
  const old = JSON.stringify(await call(ck, 'GET', '/api/state'));
  hold(w, /^POST \/api\/office\/meals$/);
  await menuPick(/Trattoria Neu/, 'Duplicate');
  check(await until(() => w.__held.length === 1), 'Duplicate: the request is held');
  check([...d.querySelectorAll('.bwlist [data-bw="open"]')].filter(b => /Trattoria Neu/.test(b.textContent)).length === 2 && !dlg(), 'the copy shows before the answer, no dialog yet');
  w.__held[0].go();
  check(await until(async () => (await meals()).filter(m => m.place_name === 'Trattoria Neu').length === 2), 'the server stores the copy');
  check(await until(() => dlg()?.querySelector('[data-bwm="del"]') && dlg()?.querySelector('#bw-pname')?.value === 'Trattoria Neu'), 'the dialog opens with the stored copy');
  click(w, dlg()?.querySelector('[data-bwm="close"]'));
  check(await until(() => !dlg() && [...d.querySelectorAll('.bwlist [data-bw="open"]')].every(b => +b.dataset.id > 0)), 'every row carries its real id');
  w.__old = old;
  w.eval('applyState(JSON.parse(window.__old)); render()');  // ... arrives now (applyState and render are synchronous)
  check([...d.querySelectorAll('.bwlist [data-bw="open"]')].every(b => +b.dataset.id > 0) && nTr0() === 2, '#5076: an older state of the app does not bring the copy\'s provisional row back ' + nTr0());
  unhold(w);

  // ================= delete: at once, a refusal brings the row back
  const nTr = () => [...d.querySelectorAll('.bwlist [data-bw="open"]')].filter(b => /Trattoria Neu/.test(b.textContent)).length;
  const del = async () => { await menuPick(/Trattoria Neu/, 'Delete'); await until(() => d.querySelector('[data-cd="yes"]')); click(w, d.querySelector('[data-cd="yes"]')); };
  hold(w, /^DELETE \/api\/office\/meals\/\d+$/);
  await del();
  check(await until(() => w.__held.length === 1), 'Delete: the request is held');
  check(nTr() === 1 && !loading(), 'the row is gone before the answer');
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => nTr() === 2), 'the refusal brings the row back');
  await del();
  check(await until(() => w.__held.length === 2), 'the second Delete is held');
  w.__held[1].go();
  check(await until(async () => (await meals()).filter(m => m.place_name === 'Trattoria Neu').length === 1), 'the server deleted it');
  check(await until(() => toastHas(/Deleted/) && nTr() === 1), '"Deleted" with undo after the answer');
  unhold(w);
  await sleep(300);  // a reload the actions might start would be on its way by now
  check(!stateFetches(w).length, 'no action fetched the whole state again: ' + stateFetches(w).join(' | ') + ' (all: ' + w.__sent.join(' ; ') + ')');
  w.close();
  console.log(`p2559_d_meals_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
