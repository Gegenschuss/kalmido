// 2.198.0 B (#2764): the panel's fold-all button stays in Knowledge / File store when nothing is open (Unfold all brings the state back).
// Own container (start.sh), jsdom, a person WITHOUT an organisation (as tests/freelancer_fixture.py; freelancer-matrix: sheets,
// wiki, files).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2198B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const dnd = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: '', types: [], files: [], setDragImage() {}}; el.dispatchEvent(e); return e; };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);  // a server with organisations
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files', 'sheets'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const P = (await call('POST', '/api/lists', {name: 'Launch'})).id;
  const S1 = (await call('POST', '/api/sheets', {title: 'Budget', space: 'private'})).id;
  const S2 = (await call('POST', '/api/sheets', {title: 'Crew', space: 'private', list_id: P})).id;
  check(S1 && S2, 'two tables, one of them on the project ' + S1 + ' ' + S2);
  for (const p of ['Docs/Guide', 'Docs/Deep/Inner', 'Top page']) await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p});
  const INV = (await call('POST', '/api/files/folders', {name: 'Invoices', space: 'private'})).id;
  const Q1 = (await call('POST', '/api/files/folders', {name: 'Q1', parent_id: INV})).id;
  const ARC = (await call('POST', '/api/files/folders', {name: 'Archive', space: 'private'})).id;
  const fd = new FormData(); fd.append('space', 'private'); fd.append('file', new Blob(['hello']), 'note.txt');
  const up = await (await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json();
  const NOTE = (up.items || [])[0]?.id;
  check(INV && Q1 && ARC && NOTE, 'folders Invoices/Q1, Archive and a file at the top');

  const fa = d => d.querySelector('#side .sbbfa');
  const arrows = d => [...d.querySelectorAll('#side [data-act="sbb-tree"]')];
  const openKeys = d => arrows(d).filter(a => a.dataset.open).map(a => a.dataset.k).sort().join('|');
  // ---- Knowledge
  let w = await boot({user: 'frida', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}); let d = w.document;
  check(await until(() => rowOf(d, 'Docs')), 'wiki: the panel shows Docs');
  check(fa(d) && fa(d).getAttribute('aria-pressed') === 'true', 'wiki: nothing open - the button is there, as "Unfold all"');
  rowOf(d, 'Docs').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Deep')), 'wiki: Docs opened');
  rowOf(d, 'Deep').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Inner')), 'wiki: Deep opened');
  check(fa(d).getAttribute('aria-pressed') === 'false', 'wiki: something open - "Fold all"');
  const before = openKeys(d);
  fa(d).click();
  check(await until(() => !rowOf(d, 'Deep')), 'wiki: fold all closes the tree');
  check(fa(d) && fa(d).getAttribute('aria-pressed') === 'true' && d.activeElement === fa(d), 'wiki: the button stays, now "Unfold all", focus on it');
  fa(d).click();
  check(await until(() => rowOf(d, 'Inner')) && openKeys(d) === before, 'wiki: unfold all restores exactly the earlier state');
  fa(d).click(); await until(() => !rowOf(d, 'Deep'));
  w.eval(`LS.set('sbbMem', {})`);
  fa(d).click();
  check(await until(() => rowOf(d, 'Deep')) && !rowOf(d, 'Inner'), 'wiki: without a remembered state the first level opens');
  w.close();
  // ---- File store
  w = await boot({user: 'frida', hash: 'ablage'}); d = w.document;
  check(await until(() => rowOf(d, 'Invoices')) && fa(d) && fa(d).getAttribute('aria-pressed') === 'true', 'files: the button is there with nothing open');
  rowOf(d, 'Invoices').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Q1')), 'files: Invoices opened');
  fa(d).click();
  check(await until(() => !rowOf(d, 'Q1')) && fa(d) && d.activeElement === fa(d), 'files: fold all, the button stays and has the focus');
  fa(d).click();
  check(await until(() => rowOf(d, 'Q1')), 'files: unfold all restores Invoices open');
  w.close();
  // ---- Tasks unchanged, narrow window does not break
  w = await boot({user: 'frida', hash: ''}); d = w.document;
  check(await until(() => fa(d)), 'tasks: the fold button is there as before');
  w.close();
  w = await boot({user: 'frida', hash: 'wiki', mobile: true}); d = w.document;
  check(await until(() => d.querySelector('#view')), 'narrow window: the app still draws');
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
