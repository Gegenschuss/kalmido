// 2.576.0 part D (#3371) UI tests (jsdom), fresh DB: the block "Relations" in a task (related.js)
// kalmido-suite: fresh
// - shows both kinds with the other task's title; "Close as duplicate" on a duplicate closes the task (won't do), Undo opens it again
//   and keeps the relation that was there before
// - "Relation…" picks a task (search) and adds it; the x removes it again
// Without an organisation (P4): all of it in a private list of a person without any organisation
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const stOf = async id => (await (await fetch(B + `api/tasks/${id}`, {headers: {...H, Cookie: CK}})).json()).status;  // call() puts the HTTP status into .status
const relsOf = async id => ((await call('GET', `/api/tasks/${id}/relations`)).relations || []).map(x => `${x.id}:${x.kind}`).sort();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;
  const A = (await call('POST', '/api/tasks', {title: 'Fix the gate', list_id: P})).id;
  const Bt = (await call('POST', '/api/tasks', {title: 'Oil the hinges', list_id: P})).id;
  const C = (await call('POST', '/api/tasks', {title: 'Gate is broken', list_id: P})).id;
  const D = (await call('POST', '/api/tasks', {title: 'Drain the pond', list_id: P})).id;
  check((await call('POST', `/api/tasks/${A}/relations`, {other_id: Bt})).status === 200, 'relates via the API');
  check((await call('POST', `/api/tasks/${C}/relations`, {other_id: A, kind: 'duplicate'})).status === 200, 'duplicate via the API');

  const w = await boot({user: 'alice', hash: 'l/' + P});
  await until(() => w.eval('S.route.key') === 'l:' + P);
  const box = () => w.eval(`document.querySelector('#d-rels')?.textContent || ''`);

  // the duplicate: its block names the original and offers to close it
  w.eval(`openDetail(${C})`);
  await until(() => box().includes('Fix the gate'));
  check(box().includes('Duplicate of') && box().includes('Fix the gate'), 'the block shows "Duplicate of" + the title: ' + box());
  check(w.eval(`!!document.querySelector('#d-rels [data-rel="close"][data-o="${A}"]')`), 'it offers "Close as duplicate"');
  w.eval(`document.querySelector('#d-rels [data-rel="close"]').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))`);
  await until(async () => (await stOf(C)) === -1);
  check((await stOf(C)) === -1, 'closed as won\'t do');
  await until(() => w.eval(`HIST.undo.length`) > 0);
  await w.eval(`histStep('undo')`);
  await until(async () => (await stOf(C)) === 0);
  check((await stOf(C)) === 0, 'Undo opens it again');
  check(JSON.stringify(await relsOf(C)) === JSON.stringify([`${A}:duplicate_of`]), 'the relation from before stays');

  // the original: both kinds, adding through the picker, removing with the x
  w.eval(`openDetail(${A})`);
  await until(() => box().includes('Oil the hinges') && box().includes('Gate is broken'));
  check(box().includes('Related to') && box().includes('Has duplicate'), 'both kinds named: ' + box());
  w.eval(`document.querySelector('#d-rels [data-rel="add"]').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))`);
  await until(() => w.eval(`!!document.querySelector('#rel-q')`));
  w.eval(`(() => { const q = document.querySelector('#rel-q'); q.value = 'pond'; q.dispatchEvent(new Event('input', {bubbles: true})); })()`);
  await until(() => w.eval(`!!document.querySelector('#rel-list [data-pick="${D}"]')`));
  check(!w.eval(`!!document.querySelector('#rel-list [data-pick="${Bt}"]')`), 'the search leaves the others out (and what is related already)');
  w.eval(`document.querySelector('#rel-list [data-pick="${D}"]').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))`);
  await until(async () => (await relsOf(A)).includes(`${D}:relates`));
  check((await relsOf(A)).includes(`${D}:relates`), 'picked: related');
  await until(() => box().includes('Drain the pond'));
  check(box().includes('Drain the pond'), 'the block shows the new one');
  w.eval(`document.querySelector('#d-rels [data-rel="rm"][data-o="${D}"]').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))`);
  await until(async () => !(await relsOf(A)).includes(`${D}:relates`));
  check(!(await relsOf(A)).includes(`${D}:relates`), 'the x removes it');
  await until(() => !box().includes('Drain the pond'));
  check(!box().includes('Drain the pond'), 'and the block drops it');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
