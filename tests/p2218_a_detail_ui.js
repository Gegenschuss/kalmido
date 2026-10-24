// 2.218.0 A (#2799) UI tests: the task panel on a phone. Own container (start.sh), jsdom.
// - the quick button that equals the current date is left out (due today: only Tomorrow; else both - Tomorrow stays, a further click adds a day, #2768)
// - the section button next to the project shows the section icon (not "+"), its name stays "Move to section…"
// - the task number is no longer in the panel's path (phone and computer): the "…" menu has "Copy link · #id"
// - the "…" menu of the panel has Pin and Lock with their state (a check when on), a tap on Lock locks the task
// - the CSS: on touch screens below 28rem the header hides Pin and an unset Lock (a set lock stays as an icon)
// - a person WITHOUT an organisation: the same
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2218A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const dq = d => [...d.querySelectorAll('#detail .dtop [data-act="due-q"]')].map(b => b.dataset.d).join();
const menuItems = (w, d, id) => { w.eval(`taskMenu(document.querySelector('#detail [data-act="task-menu"]'), ${id})`); return [...d.querySelectorAll('#pop [role="menuitem"]')]; };
const item = (its, re) => its.find(b => re.test(b.querySelector('.ml')?.textContent || ''));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const L = (await call('POST', '/api/lists', {name: 'Postproduction'})).id;
  await call('POST', `/api/lists/${L}/share`, {username: 'bob', role: 'edit'});
  const mk = async b => (await call('POST', '/api/tasks', {list_id: L, ...b})).id;
  const T0 = await mk({title: 'Callsheet day 1', due: day(0), priority: 5});
  const T1 = await mk({title: 'Send the shooting plan', due: day(1)});
  const T9 = await mk({title: 'Colour grading', due: day(9)});

  // CSS: Pin and an unset Lock leave the narrow header
  const css = require('fs').readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/@media \(pointer:coarse\)\{ @container dtop \(max-width:27\.99rem\)\{ \.dtop \.iconbtn\[data-act="pin"\],\.dtop \.tlkb:not\(\.on\)\{display:none\}/.test(css), 'CSS: touch screens below 28rem hide Pin and an unset Lock in the header (a computer keeps them)');

  // ================= phone
  let w = await boot({user: 'alice', mobile: true, hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${T0})`); await until(() => d.querySelector('#detail .dtop'));
  check(dq(d) === '1', 'due today: only Tomorrow next to the date: ' + dq(d));
  check(!d.querySelector('#detail .dcid') && !/#\d+/.test(d.querySelector('#detail .dcrumbs')?.textContent || ''), 'no task number in the path');
  const sb = d.querySelector('#detail .dcrumbs .dcadd');
  const icCols = w.eval(`(() => { const t = document.createElement('span'); t.innerHTML = ic('columns', 's'); return t.innerHTML; })()`);
  const icPlus = w.eval(`(() => { const t = document.createElement('span'); t.innerHTML = ic('plus', 's'); return t.innerHTML; })()`);
  check(sb && sb.innerHTML.includes(icCols) && !sb.innerHTML.includes(icPlus) && sb.title === 'Move to section…', 'the section button: the section icon, named "Move to section…"');
  check(d.querySelector('#detail .dtop [data-act="pin"]') && d.querySelector('#detail .dtop .tlkb'), 'Pin + Lock still rendered (CSS hides them on a phone)');
  let its = menuItems(w, d, T0);
  check(item(its, new RegExp('^Copy link · #' + T0 + '$')), '"…": Copy link · #' + T0);
  check(item(its, /^Pin$/) && !item(its, /^Pin$/).classList.contains('on'), '"…": Pin (not on)');
  const lk = item(its, /^Lock$/);
  check(lk && !lk.classList.contains('on'), '"…": Lock (not on)');
  lk?.click();
  check(await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.id === T0)?.locked), 'a tap on Lock locks the task');
  await until(() => d.querySelector('#detail .dtop .tlkb.on'));
  its = menuItems(w, d, T0);
  check(item(its, /^Locked$/)?.classList.contains('on'), '"…": Locked with its check');
  item(its, /^Pin$/)?.click();
  check(await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.id === T0)?.pinned), 'a tap on Pin pins');
  await sleep(300);
  its = menuItems(w, d, T0);
  check(item(its, /^Pinned$/)?.classList.contains('on'), '"…": Pinned with its check');
  w.eval('closePop()');
  w.eval(`openDetail(${T1})`); await sleep(400);
  check(dq(d) === '0,1', 'due tomorrow: Today and Tomorrow (a further day, #2768): ' + dq(d));
  w.eval(`openDetail(${T9})`); await sleep(400);
  check(dq(d) === '0,1', 'due in 9 days: Today and Tomorrow: ' + dq(d));
  d.querySelector('#detail .dtop [data-act="due-q"][data-d="1"]').click();
  check(await until(() => dq(d) === '0,1'), 'a tap on Tomorrow (one more day, #2768): both stay');  // 2.218.0: merged with #2768, Tomorrow is never left out
  w.close();

  // ================= computer: no number in the path either
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`openDetail(${T9})`); await until(() => d.querySelector('#detail .dtop'));
  check(d.querySelector('#detail .dcrumbs') && !d.querySelector('#detail .dcid'), 'computer: no task number in the path');
  check(item(menuItems(w, d, T9), new RegExp('Copy link · #' + T9)), 'computer: "…" has Copy link · #' + T9);
  w.close();

  // ================= a person without an organisation
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, FK);
  const FL = (await call('POST', '/api/lists', {name: 'Mine'}, FK)).id;
  const FT = (await call('POST', '/api/tasks', {list_id: FL, title: 'Invoice', due: day(0)}, FK)).id;
  w = await boot({user: 'frida', mobile: true, hash: 'l/' + FL}); d = w.document;
  w.eval(`openDetail(${FT})`); await until(() => d.querySelector('#detail .dtop'));
  check(dq(d) === '1' && !d.querySelector('#detail .dcid'), 'without an organisation: only Tomorrow, no number in the path');
  its = menuItems(w, d, FT);
  check(item(its, new RegExp('Copy link · #' + FT)) && item(its, /^Lock$/), 'without an organisation: Copy link + Lock in "…"');
  w.close();

  console.log(`p2218_a_detail_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
