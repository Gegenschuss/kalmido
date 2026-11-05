// 2.559.0 UI tests, part D (#4660): deals of the pipeline are added, dragged into another stage, changed and deleted at
// kalmido-suite: fresh
// once (optimistic), own container (start.sh, mode workspaces), jsdom. Invented companies and figures only. Run for a
// member of an organisation and for a person without an organisation (freelancer parity, the own office).
// - New enquiry: the dialog closes and the card (provisional id) stands in its column while the answer is held; a refusal
//   (500) takes it away with the server's message; let through, the card carries the real id and the open sum on top
//   (the server's) follows in the background
// - Drag a card into "Order": it stands there before the answer; a refusal (409) puts it back into its column
// - Edit: the card shows the new name before the answer; a refusal (400) puts the old one back
// - Delete: the card goes at once; a refusal brings it back; let through, "Deleted" with undo
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
// a drag in jsdom: events with a small stand-in for the DataTransfer
const drag = (w, type, el) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'dataTransfer', {value: {effectAllowed: '', dropEffect: '', setData() {}, getData: () => ''}}); el.dispatchEvent(e); };

async function round(who, ck) {
  const img = await call(ck, 'POST', '/api/office/deals', {title: 'Imagefilm', value: 1000, stage: 'inquiry'});
  check(img.http === 201, `${who}: a deal ${img.http}`);
  const deals = async () => (await call(ck, 'GET', '/api/office/deals')).items || [];

  const w = await boot({user: who, hash: 'office/pipeline'}), d = w.document;
  const dlg = () => d.querySelector('.modal.ofcdlg');
  const cardOf = (re, col) => [...d.querySelectorAll(`${col ? `[data-pipcol="${col}"] ` : ''}.ppcard`)].find(c => re.test(c.textContent));
  const open = () => d.querySelector('.pptile b')?.textContent || '';
  const toastHas = re => re.test(d.querySelector('#toast')?.textContent || '');
  const loading = () => /Loading…/.test(d.querySelector('.ofcbody')?.textContent || '');
  check(await until(() => cardOf(/Imagefilm/, 'inquiry') && d.querySelector('[data-pp="new"]')), `${who}: the board shows the deal`);
  check(/1,000/.test(open()), `${who}: the open sum on top: ` + open());
  watch(w);

  // ================= new enquiry: at once, a refusal takes the card away
  const add = async () => {
    click(w, d.querySelector('.ofcbar [data-pp="new"]')); await until(() => dlg()?.querySelector('#pp-title'));
    dlg().querySelector('#pp-title').value = 'Messefilm'; dlg().querySelector('#pp-value').value = '2500'; click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^POST \/api\/office\/deals$/);
  await add();
  check(await until(() => w.__held.length === 1), `${who}: New enquiry: the request is held`);
  // the answer is held: waited on the drawn card (a redraw of the office between two looks once made a single look fail)
  check(await until(() => { const c = cardOf(/Messefilm/, 'inquiry'); return !dlg() && c && +c.dataset.id < 0 && /2,500/.test(c.textContent) && !loading(); }),
    `${who}: the dialog closed and the card (provisional id, 2,500) stands in "Enquiry" before the answer: ` + [!dlg(), cardOf(/Messefilm/)?.parentElement?.closest('[data-pipcol]')?.dataset.pipcol, cardOf(/Messefilm/)?.dataset.id, cardOf(/Messefilm/)?.textContent, loading()].join(' / '));
  check(!(await deals()).some(x => x.title === 'Messefilm'), `${who}: the server has no deal yet`);
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => !cardOf(/Messefilm/) && cardOf(/Imagefilm/)), `${who}: the refusal takes the card away`);
  check(await until(() => toastHas(/Refused for the test/)), `${who}: with the server's message`);
  await add();
  check(await until(() => w.__held.length === 2), `${who}: the second New enquiry is held`);
  w.__held[1].go();
  check(await until(async () => (await deals()).some(x => x.title === 'Messefilm' && x.stage === 'inquiry')), `${who}: the server stores the deal`);
  check(await until(() => +cardOf(/Messefilm/)?.dataset.id > 0), `${who}: the card carries the real id`);
  check(await until(() => /3,500/.test(open())), `${who}: the open sum follows in the background: ` + open());
  unhold(w);

  // ================= drag into "Order": at once, a refusal puts the card back
  const move = () => { const c = cardOf(/Imagefilm/), col = d.querySelector('[data-pipcol="won"]'); drag(w, 'dragstart', c); drag(w, 'dragover', col); drag(w, 'drop', col); };
  hold(w, /^PATCH \/api\/office\/deals\/\d+$/);
  move();
  check(await until(() => w.__held.length === 1), `${who}: the drag: the request is held`);
  check(cardOf(/Imagefilm/, 'won') && !cardOf(/Imagefilm/, 'inquiry') && !loading(), `${who}: the card stands in "Order" before the answer`);
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => cardOf(/Imagefilm/, 'inquiry') && !cardOf(/Imagefilm/, 'won')), `${who}: the refusal puts it back into "Enquiry"`);
  move();
  check(await until(() => w.__held.length === 2), `${who}: the second drag is held`);
  w.__held[1].go();
  check(await until(async () => (await deals()).find(x => x.id === img.id)?.stage === 'won'), `${who}: the server stores the stage`);
  check(await until(() => toastHas(/Moved to Order/) && cardOf(/Imagefilm/, 'won')), `${who}: the toast after the answer, the card stays in "Order"`);
  unhold(w);

  // ================= edit: at once, a refusal puts the old name back
  const edit = async () => {
    click(w, cardOf(/Imagefilm|Brand film/)); await until(() => dlg()?.querySelector('#pp-title')?.value === 'Imagefilm');
    dlg().querySelector('#pp-title').value = 'Brand film'; click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^PATCH \/api\/office\/deals\/\d+$/);
  await edit();
  check(await until(() => w.__held.length === 1), `${who}: Save: the request is held`);
  check(!dlg() && cardOf(/Brand film/, 'won') && !cardOf(/Imagefilm/), `${who}: the dialog closed, the card shows the new name before the answer`);
  w.__held[0].fail('Refused for the test');
  check(await until(() => cardOf(/Imagefilm/, 'won') && !cardOf(/Brand film/)), `${who}: the refusal puts the old name back`);
  await edit();
  check(await until(() => w.__held.length === 2), `${who}: the second Save is held`);
  w.__held[1].go();
  check(await until(async () => (await deals()).find(x => x.id === img.id)?.title === 'Brand film'), `${who}: the server stores the name`);
  unhold(w);

  // ================= delete: at once, a refusal brings the card back
  const del = async () => { click(w, cardOf(/Messefilm/)); await until(() => dlg()?.querySelector('[data-m="del"]')); click(w, dlg().querySelector('[data-m="del"]')); };
  hold(w, /^DELETE \/api\/office\/deals\/\d+$/);
  await del();
  check(await until(() => w.__held.length === 1), `${who}: Delete: the request is held`);
  check(!dlg() && !cardOf(/Messefilm/) && cardOf(/Brand film/), `${who}: the dialog closed and the card is gone before the answer`);
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => cardOf(/Messefilm/)), `${who}: the refusal brings the card back`);
  await del();
  check(await until(() => w.__held.length === 2), `${who}: the second Delete is held`);
  w.__held[1].go();
  check(await until(async () => !(await deals()).some(x => x.title === 'Messefilm')), `${who}: the server deleted it`);
  check(await until(() => toastHas(/Deleted/) && !cardOf(/Messefilm/)), `${who}: "Deleted" with undo after the answer`);
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

  console.log(`p2559_d_pipeline_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
