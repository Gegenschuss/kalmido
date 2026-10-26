// 2.218.0 A (#2803) UI tests: Today on a phone. Own container (start.sh), jsdom.
// - the briefing counts "due today" / "overdue" from the groups Today shows: a tick on an overdue task (and a change that
//   comes in like a live event) lowers the number at once, card == the section "Overdue"
// - on a phone the briefing is one slim line (the numbers + "Read"), a tap opens the full card, its fold button closes it;
//   a computer keeps the full card
// - the blocks' "…" in Today has no grey square (CSS)
// - Today / Tomorrow show the project in the row (line of the date) with the standard level; "Calm" switches it off
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
const line = d => d.querySelector('#view .bfcard .rvfn')?.textContent || '';
const secOver = d => d.querySelector('#view .ghead[data-key="d:over"] .c')?.textContent || '0';
const lstOf = (d, id) => d.querySelector(`#view .trow[data-id="${id}"] .meta .lst`)?.textContent || '';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice', undefined, {rowIcons: null});
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', sidebar: JSON.stringify({hidden: ['e:home']})});  // 2.364.0 (#3031): Today's briefing only while Start is hidden in the bar
  const P = (await call('POST', '/api/lists', {name: 'Postproduction'})).id;
  const mk = async b => (await call('POST', '/api/tasks', {list_id: P, ...b})).id;
  const O1 = await mk({title: 'Acceptance with the client', due: day(-1)});
  const O2 = await mk({title: 'Insurance for the equipment', due: day(-2)});
  const O3 = await mk({title: 'Permit from the city', due: day(-3)});
  const D1 = await mk({title: 'Callsheet day 1', due: day(0)});
  await mk({title: 'Call the printer', due: day(0)});
  const M1 = await mk({title: 'Send the shooting plan', due: day(1)});

  const css = require('fs').readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(css.includes('[data-ly="today"] > .lyb > .lymore{background:none}'), 'CSS: the "…" of the Today blocks without the grey square');

  // ================= phone
  let w = await boot({user: 'alice', mobile: true, hash: 'today', rowIcons: null}), d = w.document;
  check(await until(() => d.querySelector('#view .bfcard')), 'the briefing is there');
  const c = d.querySelector('#view .bfcard');
  check(c && c.classList.contains('fold') && c.classList.contains('bfline') && c.querySelector('[data-brief="read"]') && !c.querySelector('.rvnums'), 'phone: one line with "Read" (no full card)');
  check(/2 due today/.test(line(d)) && /3 overdue/.test(line(d)) && secOver(d) === '3', 'phone: the numbers: ' + line(d) + ' / section ' + secOver(d));
  // a tick on an overdue task: the card follows at once
  w.eval(`toggleTask(${O1})`);
  check(await until(() => /2 overdue/.test(line(d)) && secOver(d) === '2'), 'a tick: "2 overdue" at once, the same as the section: ' + line(d) + ' / ' + secOver(d));
  // a change from elsewhere (as a live event brings it): counted again with the next render
  w.eval(`putTask({...S.tasks.get(${O2}), status: 2}); render()`);
  check(await until(() => /1 overdue/.test(line(d)) && secOver(d) === '1'), 'a change from elsewhere: "1 overdue": ' + line(d) + ' / ' + secOver(d));
  w.eval(`putTask({...S.tasks.get(${D1}), due: '${day(5)}'}); render()`);
  check(await until(() => /1 due today/.test(line(d))), 'a task moved away: "1 due today": ' + line(d));
  // open + close
  d.querySelector('#view .bfcard [data-brief="open"]').click();
  check(await until(() => d.querySelector('#view .bfcard:not(.fold) .rvnums') && d.querySelector('#view .bfcard [data-brief="close"]')), 'a tap opens the full card, with its fold button');
  d.querySelector('#view .bfcard [data-brief="close"]').click();
  check(await until(() => d.querySelector('#view .bfcard.bfline')), 'the fold button makes it one line again');
  // the project in the row (standard level)
  check(lstOf(d, O3) === 'Postproduction', 'Today: the project in the row: ' + lstOf(d, O3));
  w.close();
  w = await boot({user: 'alice', mobile: true, hash: 'tomorrow', rowIcons: null}); d = w.document;
  check(await until(() => lstOf(d, M1) === 'Postproduction'), 'Tomorrow: the project in the row');
  w.close();
  await call('PATCH', '/api/settings', {row_icons: 'calm'});
  w = await boot({user: 'alice', mobile: true, hash: 'today', rowIcons: null}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${O3}"]`));
  check(d.querySelector(`#view .trow[data-id="${O3}"]`) && !lstOf(d, O3), '"Calm": no project in the row');
  w.close();
  await call('PATCH', '/api/settings', {row_icons: 'key'});

  // ================= computer: the full card as before
  w = await boot({user: 'alice', hash: 'today', rowIcons: null}); d = w.document;
  check(await until(() => d.querySelector('#view .bfcard:not(.fold) .rvnums') && !d.querySelector('#view .bfcard.bfline')), 'computer: the full card (unread)');
  // (the changes above were local only: on the server O1 is done, O2 still overdue)
  check(/2 overdue/.test(d.querySelector('#view .bfcard .rvnums')?.textContent || '') && secOver(d) === '2', 'computer: card == section: ' + d.querySelector('#view .bfcard .rvnums')?.textContent + ' / ' + secOver(d));
  w.close();

  // ================= a person without an organisation
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  const FK = await login('frida', undefined, {rowIcons: null});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', sidebar: JSON.stringify({hidden: ['e:home']})}, FK);  // 2.364.0 (#3031)
  const FL = (await call('POST', '/api/lists', {name: 'Clients'}, FK)).id;
  const FO = (await call('POST', '/api/tasks', {list_id: FL, title: 'Invoice', due: day(-1)}, FK)).id;
  w = await boot({user: 'frida', mobile: true, hash: 'today', rowIcons: null}); d = w.document;
  check(await until(() => d.querySelector('#view .bfcard.bfline')) && /1 overdue/.test(line(d)), 'without an organisation: one line, 1 overdue: ' + line(d));
  check(lstOf(d, FO) === 'Clients', 'without an organisation: the project in the row');
  w.eval(`toggleTask(${FO})`);
  check(await until(() => !/overdue/.test(line(d))), 'without an organisation: a tick counts again: ' + line(d));
  w.close();

  console.log(`p2218_a_today_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
