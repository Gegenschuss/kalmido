// 2.359.2 B (#3049) UI tests (jsdom), fresh DB: a form or dialog keeps what was typed when the save fails
// - quick entry (docked composer), board "+ Task", matrix "+ Task", the tag field, the shopping mode: a 500 / 409 leaves the text
//   (and pasted images) in the field; a second Enter while the first still saves sends nothing twice; emptied once saved
// - a task's detail drawn again while the tag field is typed in (the video section arrives late) keeps the text
// - the list dialog: "Close" with a failed save keeps the dialog and the typed name ("Discard changes?" first); Esc too
// kalmido-suite: fresh
const {boot, errs, B, login, until, sleep} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});
// every write that leaves the window {m, p, body}; fake(m, p, go) may answer instead (go() = the real request)
const stub = (w, fake) => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname;
  if (m !== 'GET') calls.push({m, p, body: typeof o.body === 'string' ? o.body : ''});
  const r = fake && fake(m, p, () => of(u, o)); return r ? Promise.resolve(r) : of(u, o); }; return calls; };
const enter = (w, el) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
const titles = async () => (await call('GET', '/api/state')).tasks.map(t => t.title);

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'kanban,matrix,family'});
  const P = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const SH = (await call('POST', '/api/lists', {name: 'Groceries', family: 'shopping'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Plant tulips', list_id: P})).id;
  const w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  let fake = null;
  const calls = stub(w, (m, p, go) => fake && fake(m, p, go));
  const fail = (st = 500) => (m, p) => m === 'POST' && p === '/api/tasks' ? jres(st, {error: 'Server error'}) : null;
  check(await until(() => !!d.querySelector('#qinput')), 'setup: the composer is there');

  // ================= quick entry: a failed save keeps the text and the pasted image
  fake = fail(500);
  w.eval(`S.qfiles = S.qfiles || {}; S.qfiles.qinput = [new File(['x'], 'seed.png', {type: 'image/png'})]`);
  let q = d.querySelector('#qinput'); q.focus(); q.value = 'Buy seeds'; enter(w, q);
  check(await until(() => calls.some(c => c.p === '/api/tasks') && !d.querySelector('#qinput').dataset.qbusy), 'quick: the create went out');
  check(d.querySelector('#qinput').value === 'Buy seeds', 'quick 500: the text stays (' + d.querySelector('#qinput').value + ')');
  check(w.eval('S.qfiles.qinput.length') === 1, 'quick 500: the pasted image stays');
  w.eval('S.qfiles.qinput = []');
  fake = fail(409); calls.length = 0;
  q = d.querySelector('#qinput'); enter(w, q);
  check(await until(() => calls.some(c => c.p === '/api/tasks') && !d.querySelector('#qinput').dataset.qbusy), 'quick 409: sent');
  check(d.querySelector('#qinput').value === 'Buy seeds', 'quick 409: the text stays');
  check(!(await titles()).includes('Buy seeds'), 'quick: nothing created by the failed tries');

  // ================= quick entry: a second Enter while it saves sends nothing twice; emptied once saved
  let open; const gate = new Promise(r => { open = r; });
  fake = (m, p, go) => m === 'POST' && p === '/api/tasks' ? gate.then(go) : null; calls.length = 0;
  q = d.querySelector('#qinput'); enter(w, q); enter(w, q);
  check(await until(() => calls.some(c => c.p === '/api/tasks')), 'quick: the create is on its way');
  await sleep(150);
  check(calls.filter(c => c.p === '/api/tasks').length === 1, 'quick: a second Enter while saving sends nothing twice (' + calls.filter(c => c.p === '/api/tasks').length + ')');
  check(d.querySelector('#qinput').value === 'Buy seeds', 'quick: the text stays while it saves');
  open(); fake = null;
  check(await until(() => d.querySelector('#qinput').value === ''), 'quick: emptied once saved');
  check((await titles()).filter(t => t === 'Buy seeds').length === 1, 'quick: saved once');

  // ================= board "+ Task"
  await call('PATCH', `/api/lists/${P}`, {view: 'kanban'});
  w.eval('load().then(render)');
  check(await until(() => !!d.querySelector('#view [data-kadd]')), 'board: the "+ Task" field');
  fake = fail(500); calls.length = 0;
  let k = d.querySelector('#view [data-kadd]'); k.focus(); k.value = 'Rake leaves'; enter(w, k);
  check(await until(() => calls.some(c => c.p === '/api/tasks') && !d.querySelector('#view [data-kadd]')?.dataset.qbusy), 'board: sent');
  check(d.querySelector('#view [data-kadd]').value === 'Rake leaves', 'board 500: the text stays');
  fake = null;
  enter(w, d.querySelector('#view [data-kadd]'));
  check(await until(async () => (await titles()).includes('Rake leaves')), 'board: saved on the next Enter');
  check(await until(() => d.querySelector('#view [data-kadd]')?.value === ''), 'board: emptied once saved');

  // ================= matrix "+ Task"
  w.eval(`go('matrix')`);
  check(await until(() => !!d.querySelector('#view [data-qadd]')), 'matrix: the "+ Task" field');
  fake = fail(500); calls.length = 0;
  let mq = d.querySelector('#view [data-qadd]'); const qa = mq.dataset.qadd; mq.focus(); mq.value = 'Prune roses'; enter(w, mq);
  check(await until(() => calls.some(c => c.p === '/api/tasks') && !d.querySelector(`[data-qadd="${qa}"]`)?.dataset.qbusy), 'matrix: sent');
  check(d.querySelector(`[data-qadd="${qa}"]`).value === 'Prune roses', 'matrix 500: the text stays');
  fake = null;

  // ================= the tag field of a task
  w.eval(`go('l/${P}'); openDetail(${T1})`);
  check(await until(() => !!d.querySelector('#d-tag')), 'tag: the field is there');
  fake = (m, p) => m === 'PATCH' && p === '/api/tasks/' + T1 ? jres(500, {error: 'Server error'}) : null; calls.length = 0;
  let tg = d.querySelector('#d-tag'); tg.focus(); tg.value = 'spring'; enter(w, tg);
  check(await until(() => calls.some(c => c.p === '/api/tasks/' + T1) && !tg.dataset.qbusy, {step: 5}), 'tag: sent');
  check(d.querySelector('#d-tag').value === 'spring', 'tag 500: the text stays (' + d.querySelector('#d-tag').value + ' | ' + d.querySelector('#toast')?.textContent + ' | ' + JSON.stringify(calls.map(c => c.m + c.p)) + ')');
  fake = null;
  enter(w, d.querySelector('#d-tag'));
  check(await until(async () => ((await call('GET', '/api/tasks/' + T1)).tags || []).includes('spring')), 'tag: saved on the next Enter');

  // ================= shopping mode
  w.eval(`if (typeof closeDetail === 'function') closeDetail(); shopModeOpen(${SH})`);
  check(await until(() => !!d.querySelector('#shop-in')), 'shop: the add field');
  fake = fail(500); calls.length = 0;
  d.querySelector('#shop-in').value = 'Milk';
  d.querySelector('[data-shopadd]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  check(await until(() => calls.some(c => c.p === '/api/tasks') && !d.querySelector('#shop-in')?.dataset.qbusy), 'shop: sent');
  check(d.querySelector('#shop-in').value === 'Milk', 'shop 500: the text stays (' + d.querySelector('#shop-in').value + ')');
  fake = null;
  d.querySelector('[data-shopadd]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  check(await until(async () => (await titles()).includes('Milk')), 'shop: saved on the next try');
  check(await until(() => d.querySelector('#shop-in')?.value === ''), 'shop: emptied once saved');
  d.querySelector('[data-act="shop-close"]')?.click();
  await until(() => !d.querySelector('.shopmode'));

  // ================= the list dialog: "Close" keeps it while the save fails
  w.__dialogs = 'manual';
  w.eval(`listModal(${P})`);
  check(await until(() => !!d.querySelector('#l-name')), 'list dialog: open');
  const lmd = d.querySelector('#l-name').closest('.modal');
  fake = (m, p) => m === 'PATCH' && p === '/api/lists/' + P ? jres(500, {error: 'Server error'}) : null; calls.length = 0;
  const nm = d.querySelector('#l-name'); nm.focus(); nm.value = 'Garden and yard'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
  lmd.querySelector('[data-m="close"]').click();
  const ask = () => [...d.querySelectorAll('.modal.cdlg')].find(x => /Discard changes/.test(x.textContent));
  check(await until(() => !!ask()), 'list dialog: a failed save asks "Discard changes?"');
  check(calls.some(c => c.m === 'PATCH' && c.p === '/api/lists/' + P), 'list dialog: the save was tried');
  ask().querySelector('[data-cd="no"]').click();  // Keep editing
  await until(() => !ask());
  check(lmd.isConnected, 'list dialog: still open after "Keep editing"');
  check(d.querySelector('#l-name')?.value === 'Garden and yard', 'list dialog: the typed name stays (' + d.querySelector('#l-name')?.value + ')');
  // Esc (backdrop) goes the same way
  w.eval('modalClose(document.querySelector("#l-name").closest(".modal"))');
  check(await until(() => !!ask()), 'list dialog: Esc asks too');
  ask().querySelector('[data-cd="no"]').click(); await until(() => !ask());
  check(lmd.isConnected && d.querySelector('#l-name')?.value === 'Garden and yard', 'list dialog: Esc keeps it open with the name');
  fake = null;
  lmd.querySelector('[data-m="close"]').click();
  check(await until(() => !lmd.isConnected), 'list dialog: closes once saved');
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === P)?.name === 'Garden and yard'), 'list dialog: the name is saved');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2359_2_b_forms_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
