// 2.554.0 UI tests, part B (#4658): custom fields of a list are added, changed and deleted at once (optimistic), jsdom:
// kalmido-suite: fresh
// - a new field: the dialog closes and the column shows while the server's answer is still held (a stand-in id below 0); a
//   value typed into its cell waits for the real id (the stand-in never reaches the server); the answer brings the real id
// - a refused new field is taken back (the column goes) with the server's message
// - offline: the dialog stays open with "only with a connection" (fields are not queued)
// - a rename shows at once, the server follows
// - a delete (after the question with the count) is gone at once, Undo brings the field back with the value
// - a person without an organisation (freelancer parity): the new field's column shows at once, too
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const FEAT = 'comments,collab,fields';
// requests matching re ("METHOD /url") wait in w.__held until the test calls go() (the real request) or fail(text) (a refusal)
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => re.test(`${o.method || 'GET'} ${u}`)
    ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: msg => res(new Response(JSON.stringify({error: msg}), {status: 400, headers: {'content-type': 'application/json'}}))}))
    : f1(u, o);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Receipts'})).id;
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: ['due']});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Pharmacy', list_id: L})).id;
  const fieldsOnServer = async (ck, lid) => ((await call(ck, 'GET', '/api/state')).fields || []).filter(f => f.list_id === lid);

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  check(await until(() => d.querySelector(`#tc-${T}`)), 'the list shows its row with columns');

  // ================= a new field shows at once, the answer held
  hold(w, /^POST \/api\/lists\/\d+\/fields$/);
  w.eval(`fieldModal(${L}, null, () => {})`);
  await until(() => d.querySelector('#fd-name'));
  d.querySelector('#fd-name').value = 'Budget';
  lastModal(d).querySelector('[data-m="save"]').click();
  check(await until(() => w.__held.length === 1), 'the request is on its way (held)');
  check(!d.querySelector('#fd-name'), 'the dialog closed at once');
  const tmp = w.eval(`(S.fields.find(f => f.name === 'Budget') || {}).id`);
  check(tmp < 0, 'the new field carries a stand-in id: ' + tmp);
  check(await until(() => d.querySelector(`#tc-${T} .lc[data-k="f:${tmp}"]`)), 'its column shows before the server answered');
  check(!(await fieldsOnServer(CA, L)).length, 'the server has no field yet');
  // a value typed into the new column waits for the real id
  w.eval(`window.__tc = tcSave(${T}, ${tmp}, 'B-17')`);
  await sleep(0);
  check(w.__held.length === 1 && !w.eval(`[...window.__net.open.values()].some(u => u.includes('/api/tasks/${T}'))`), 'the value waits: no task request with the stand-in id');
  w.__held[0].go();
  check(await until(() => w.eval(`!S.fields.some(f => f.id < 0) && S.fields.some(f => f.name === 'Budget' && f.id > 0)`)), 'the answer replaced the stand-in id');
  const FB = w.eval(`S.fields.find(f => f.name === 'Budget').id`);
  check(await until(() => d.querySelector(`#tc-${T} .lc[data-k="f:${FB}"]`) && !d.querySelector(`#tc-${T} .lc[data-k="f:${tmp}"]`)), 'the column carries the real id');
  check(await until(async () => (await call(CA, 'GET', `/api/tasks/${T}`)).fields?.[FB] === 'B-17'), 'the value typed meanwhile is saved under the real id');
  check((await fieldsOnServer(CA, L)).length === 1, 'one field on the server (no stand-in, no double)');

  // ================= a refused new field is taken back with the message
  hold(w, /^POST \/api\/lists\/\d+\/fields$/);
  w.eval(`fieldModal(${L}, null, () => {})`);
  await until(() => d.querySelector('#fd-name'));
  d.querySelector('#fd-name').value = 'Refused';
  lastModal(d).querySelector('[data-m="save"]').click();
  check(await until(() => w.__held.length === 1), 'the second request is held');
  const tmp2 = w.eval(`(S.fields.find(f => f.name === 'Refused') || {}).id`);
  check(tmp2 < 0 && await until(() => d.querySelector(`#tc-${T} .lc[data-k="f:${tmp2}"]`)), 'the second column shows at once');
  w.__held[0].fail('Refused for the test');
  check(await until(() => !w.eval(`S.fields.some(f => f.name === 'Refused')`) && !d.querySelector(`#tc-${T} .lc[data-k="f:${tmp2}"]`)), 'the refusal takes the column back');
  check(await until(() => /Refused for the test/.test(d.querySelector('#toast')?.textContent || '')), 'with the server\'s message');
  check(w.eval(`!(listById(${L}).columns || []).some(k => k === 'f:${tmp2}')`), 'and out of the list\'s columns');
  unhold(w);

  // ================= offline: the dialog stays, nothing half made
  w.eval(`setOnline(false)`);
  w.eval(`fieldModal(${L}, null, () => {})`);
  await until(() => d.querySelector('#fd-name'));
  d.querySelector('#fd-name').value = 'Offline field';
  lastModal(d).querySelector('[data-m="save"]').click();
  check(await until(() => /Offline: only works again with a connection/.test(d.querySelector('#toast')?.textContent || '')), 'offline: "only with a connection"');
  check(!!d.querySelector('#fd-name') && !w.eval(`S.fields.some(f => f.name === 'Offline field')`), 'offline: the dialog stays, no field made');
  lastModal(d).remove();
  w.eval(`setOnline(true)`);

  // ================= a rename shows at once
  hold(w, /^PATCH \/api\/fields\/\d+$/);
  w.eval(`fieldModal(${L}, fieldById(${FB}), () => {})`);
  await until(() => d.querySelector('#fd-name'));
  d.querySelector('#fd-name').value = 'Budget 2026';
  lastModal(d).querySelector('[data-m="save"]').click();
  check(await until(() => w.__held.length === 1), 'the rename is on its way (held)');
  check(!d.querySelector('#fd-name') && w.eval(`fieldById(${FB}).name`) === 'Budget 2026', 'the new name shows at once, the dialog closed');
  check((await fieldsOnServer(CA, L))[0]?.name === 'Budget', 'the server has the old name still');
  w.__held[0].go(); unhold(w);
  check(await until(async () => (await fieldsOnServer(CA, L))[0]?.name === 'Budget 2026'), 'the server follows');

  // ================= a delete is gone at once, Undo brings it back
  hold(w, /^DELETE \/api\/fields\/\d+$/);
  w.eval(`fieldModal(${L}, fieldById(${FB}), () => {})`);
  await until(() => d.querySelector('#fd-name'));
  lastModal(d).querySelector('[data-m="del"]').click();
  const okBtn = await until(() => { const m = lastModal(d); return m && /Delete the field/.test(m.textContent) && /1 task with a value/.test(m.textContent) && [...m.querySelectorAll('button')].find(b => b.textContent.trim() === 'Delete' && b.dataset.m !== 'del'); });
  check(!!okBtn, 'delete asks first, with the count of the server');
  okBtn?.click();
  check(await until(() => w.__held.length === 1), 'the delete is on its way (held)');
  check(!w.eval(`!!fieldById(${FB})`) && !d.querySelector(`#tc-${T} .lc[data-k="f:${FB}"]`) && !d.querySelector('#fd-name'), 'the field and its column are gone at once');
  check((await fieldsOnServer(CA, L)).length === 1, 'the server has it still');
  w.__held[0].go(); unhold(w);
  check(await until(async () => !(await fieldsOnServer(CA, L)).length), 'the server deleted it');
  check(await undoToast(w, /“Budget 2026” deleted/), 'the toast offers Undo');
  check(await until(async () => (await fieldsOnServer(CA, L)).some(f => f.name === 'Budget 2026' && f.type === 'text')), 'Undo makes the field again');
  const FB2 = (await fieldsOnServer(CA, L)).find(f => f.name === 'Budget 2026')?.id;
  check(await until(async () => (await call(CA, 'GET', `/api/tasks/${T}`)).fields?.[FB2] === 'B-17'), 'with the value of the task');
  check(await until(() => d.querySelector(`#tc-${T} .lc[data-k="f:${FB2}"]`)), 'and its column again');
  w.close();

  // ================= a person without an organisation: the same at once
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Jobs'})).id;
  await call(CF, 'PATCH', `/api/lists/${LF}`, {columns: ['due']});
  const TF = (await call(CF, 'POST', '/api/tasks', {title: 'Logo draft', list_id: LF})).id;
  w = await boot({user: 'frida', hash: 'l/' + LF}); d = w.document;
  check(await until(() => d.querySelector(`#tc-${TF}`)), 'freelancer: the list shows');
  hold(w, /^POST \/api\/lists\/\d+\/fields$/);
  w.eval(`fieldModal(${LF}, null, () => {})`);
  await until(() => d.querySelector('#fd-name'));
  d.querySelector('#fd-name').value = 'Hours';
  lastModal(d).querySelector('[data-m="save"]').click();
  check(await until(() => w.__held.length === 1), 'freelancer: the request is held');
  check(await until(() => d.querySelector(`#tc-${TF} .lc[data-k^="f:-"]`)), 'freelancer: the column shows before the answer');
  w.__held[0].go(); unhold(w);
  check(await until(async () => (await fieldsOnServer(CF, LF)).some(f => f.name === 'Hours')), 'freelancer: the server made it');
  check(await until(() => !d.querySelector(`#tc-${TF} .lc[data-k^="f:-"]`) && d.querySelector(`#tc-${TF} .lc[data-k^="f:"]`)), 'freelancer: the column carries the real id');
  w.close();

  console.log(`p2554_b_fieldopt_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
