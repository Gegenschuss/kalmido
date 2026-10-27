// 2.281.0 C UI test (#3113), own container (start.sh): the main search asks the server from 2 characters on.
//  - jsdom: "zebra" in the main search asks /api/tasks?scope=search and lists the hits; one letter afterwards asks no server
//    (no task, message or other-server search) and empties the hits; 2 letters ask again; "#<id>" / a one-digit id still
//    finds the loaded task locally (also with 1 character) and Enter opens it
//  - the waits are on states (the hits shown / emptied, the request counter), never on a fixed time
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2281C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(100); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const L = (await call('POST', '/api/lists', {name: 'Zoo'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Zebra feeding', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Clean the zebra stable', list_id: L})).id;
  check(T1 > 0 && T2 > 0, 'setup: two tasks');

  const w = await boot({user: 'alice', hash: `l/${L}`}), d = w.document;
  const urls = [];
  { const f1 = w.fetch; w.fetch = (u, o) => { urls.push(String(u)); return f1(u, o); }; }
  const asked = from => urls.slice(from).filter(u => /search/i.test(u));  // tasks, full text, messages, other servers
  w.eval(`go('search')`); await until(() => d.querySelector('#searchq'));
  const rows = () => [...d.querySelectorAll('#sresults .trow[data-id]')].map(e => +e.dataset.id);

  let n0 = urls.length;
  w.eval(`doSearch('zebra')`);
  check(await until(() => rows().includes(T1) && rows().includes(T2)), 'zebra: both tasks listed ' + rows());
  check(urls.slice(n0).some(u => /scope=search&q=zebra/.test(u)), 'zebra: the server was asked');

  // one letter: no server search, the hits go (state: #sresults empty)
  n0 = urls.length;
  w.eval(`doSearch('z')`);
  check(await until(() => !rows().length && w.eval(`S.searchRes === null`)), 'one letter: the hits are emptied ' + rows());
  check(!asked(n0).length, 'one letter: no server search at all ' + asked(n0).join(' '));

  // two letters: the server again
  n0 = urls.length;
  w.eval(`doSearch('ze')`);
  check(await until(() => rows().includes(T1)), 'two letters: hits again ' + rows());
  check(urls.slice(n0).some(u => /scope=search&q=ze\b/.test(u)), 'two letters: the server was asked');

  // "#<id>" finds the loaded task; a one-digit id even with one character, locally, and Enter opens it
  n0 = urls.length;
  w.eval(`doSearch('#${T2}')`);
  check(await until(() => rows()[0] === T2), `"#${T2}" puts the task first ` + rows());
  const one = w.eval(`[...S.tasks.keys()].find(id => id < 10)`);
  if (one) {
    w.eval(`doSearch('${one}')`);
    check(await until(() => rows()[0] === one), `one digit "${one}": the task found locally ` + rows());
    const inp = d.querySelector('#searchq'); inp.value = String(one);
    inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    check(await until(() => w.eval(`S.sel === ${one}`)), 'Enter opens the task of the one-digit id');
  } else console.log('note: no loaded task with a one-digit id, that case is skipped');

  console.log(`p2281_c_search_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
