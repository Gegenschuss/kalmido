// 2.55.0 UI tests, part D (#1067 more views on the view builder), own container (start.sh). jsdom:
// - statistics, the client card and family are built from blocks: "Customize" opens the editor, hiding a block and the
//   order are stored (view_stats / view_clients / view_family) and survive a reload
// - without an own arrangement every view shows its blocks in the order it had before (the default)
// - the roadmap, the calendar and the habits stay as they are (one surface): no Customize button
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const t = await r.text(); try { return JSON.parse(t); } catch { return t; } };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,time,progress,agents,clients,family,habits,pomo,timeline';
const keys = d => [...d.querySelectorAll('#view .lyb[data-lyk]')].map(x => x.dataset.lyk);
const saved = async k => { const s = await call('GET', '/api/settings'); const v = s[k] || s.settings?.[k] || ''; return v ? JSON.parse(v) : {}; };

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call('POST', '/api/lists', {name: 'Chores'})).id;
  const t1 = await call('POST', `/api/lists/${L}/tasks`, {title: 'Sweep'});
  if (t1.id) await call('PATCH', `/api/tasks/${t1.id}`, {status: 2});
  const cl = await call('POST', '/api/clients', {name: 'Acme Ltd', note: 'Pays late'});
  check(cl.id, '#1067: a client to look at ' + JSON.stringify(cl).slice(0, 120));

  // ================= statistics
  let w = await boot({user: 'alice', hash: 'stats'}), d = w.document;
  await until(() => d.querySelector('#view .stats .lyb[data-lyk="tiles"]'));
  let ks = keys(d);
  check(ks.slice(0, 3).join() === 'tiles,done,bylist' && ks.includes('overdue'), '#1067: statistics: the blocks in the old order ' + ks);
  check(d.querySelector('#view [data-act="ly-custom"][data-lyv="stats"]'), '#1067: statistics: a Customize button');
  click(w, d.querySelector('#view [data-act="ly-custom"][data-lyv="stats"]'));
  await until(() => d.querySelector('.lyed[data-lyed="stats"]'));
  check(d.querySelector('.lyed[data-lyed="stats"] .lycanvas'), '#1067: statistics: the editor opens');
  click(w, d.querySelector('.lyed[data-lyed="stats"] [data-act="ly-cvhide"][data-k="bylist"]'));
  let v = await until(async () => { const x = await saved('view_stats'); return (x.hidden || []).includes('bylist') ? x : null; });
  check(v, '#1067: statistics: hiding a block is stored');
  click(w, d.querySelector('.lyed[data-lyed="stats"] [data-act="ly-done"]'));
  await sleep(300);
  w = await boot({user: 'alice', hash: 'stats'}); d = w.document;
  await until(() => d.querySelector('#view .stats .lyb[data-lyk="tiles"]'));
  check(!keys(d).includes('bylist') && keys(d).includes('done'), '#1067: statistics: still hidden after a reload');

  // ================= family
  w = await boot({user: 'alice', hash: 'family'}); d = w.document;
  await until(() => d.querySelector('#view .fam .lyb[data-lyk]'));
  ks = keys(d);
  check(ks.join() === 'occ,rot,meals,shop,dl,pack', '#1067: family: the cards in the old order ' + ks);
  click(w, d.querySelector('#view [data-act="ly-custom"][data-lyv="family"]'));
  await until(() => d.querySelector('.lyed[data-lyed="family"]'));
  click(w, d.querySelector('.lyed[data-lyed="family"] [data-act="ly-mv"][data-k="pack"][data-d="-1"]'));
  v = await until(async () => { const x = await saved('view_family'); return (x.order || []).indexOf('pack') === (x.order || []).indexOf('dl') - 1 && x.order ? x : null; });
  check(v, '#1067: family: a moved card is stored ' + JSON.stringify(v));
  click(w, d.querySelector('.lyed[data-lyed="family"] [data-act="ly-done"]'));
  await sleep(300);
  w = await boot({user: 'alice', hash: 'family'}); d = w.document;
  await until(() => d.querySelector('#view .fam .lyb[data-lyk]'));
  ks = keys(d);
  check(ks.indexOf('pack') < ks.indexOf('dl'), '#1067: family: the new order after a reload ' + ks);

  // ================= the client card
  w = await boot({user: 'alice', hash: 'client/' + cl.id}); d = w.document;
  await until(() => d.querySelector('#view .msclcard .lyb[data-lyk]'));
  ks = keys(d);
  check(ks.join() === 'details,month,lists,note', '#1067: client card: the sections in the old order ' + ks);
  check(d.querySelector('#view .msclcard .cldetail .cltable, #view .msclcard .cldetail .stcard'), '#1067: client card: lists and the month are still there');
  click(w, d.querySelector('#view .msclcard [data-act="ly-custom"][data-lyv="clients"]'));
  await until(() => d.querySelector('.lyed[data-lyed="clients"]'));
  click(w, d.querySelector('.lyed[data-lyed="clients"] [data-act="ly-cvhide"][data-k="note"]'));
  v = await until(async () => { const x = await saved('view_clients'); return (x.hidden || []).includes('note') ? x : null; });
  check(v, '#1067: client card: hiding the note is stored');
  click(w, d.querySelector('.lyed[data-lyed="clients"] [data-act="ly-done"]'));
  await sleep(300);
  check(!keys(d).includes('note') && keys(d).includes('lists'), '#1067: client card: the note is gone, the rest stays');

  // ================= untouched: roadmap, calendar, habits (one surface each)
  for (const h of ['roadmap', 'calendar', 'habits']) {
    w = await boot({user: 'alice', hash: h}); d = w.document; await sleep(500);
    check(!d.querySelector('#view [data-act="ly-custom"]'), '#1067: ' + h + ' has no Customize (one surface)');
  }
  console.log(`p255_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
