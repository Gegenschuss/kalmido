// 2.116.0 part B UI test (#2065), own container (start.sh): the command palette's group "Everywhere".
//  - jsdom: typing a word that is only in a comment of a completed task (not among the loaded tasks) shows the group
//    "Everywhere" (after the pause) with that task, the list name, "Completed", "Comment" and the snippet with its mark;
//    a click opens the task and shows the comment; a task the palette already lists locally comes once; one character
//    asks nothing; offline the group stays away and nothing breaks
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2116B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Old done task', list_id: L})).id;
  const C = (await call('POST', `/api/tasks/${T}/comments`, {body: 'The zitronenfalter came back in May'})).id;
  await call('POST', `/api/tasks/${T}/complete`);
  const TO = (await call('POST', '/api/tasks', {title: 'Zitronenfalter photo', list_id: L})).id;
  const api = await call('GET', '/api/search?q=zitronen');
  check((api.hits || []).length === 2, 'setup: the server finds both tasks ' + JSON.stringify(api).slice(0, 200));

  const w = await boot({user: 'alice', hash: `l/${L}`}), d = w.document;
  if (w.eval(`!!taskById(${T})`)) console.log('note: the completed task is loaded in this state; the group must show it anyway');
  w.eval('openPalette()'); await sleep(200);
  const inp = d.querySelector('.palette .pqin');
  input(w, inp, 'z'); await sleep(450);
  check(![...d.querySelectorAll('.palette .pgroup')].some(g => g.textContent === 'Everywhere'), 'one character: no server search');
  input(w, inp, 'zitronen');
  const grp = await until(() => [...d.querySelectorAll('.palette .pgroup')].find(g => g.textContent === 'Everywhere'));
  check(grp, 'the group "Everywhere" appears after the pause');
  const items = () => [...d.querySelectorAll('.palette .pitem')];
  const it = items().find(b => b.querySelector('.plt')?.textContent === 'Old done task');
  check(it, 'the completed task found by its comment is in the group');
  const sub = it?.querySelector('.pls');
  check(sub && /Garden/.test(sub.textContent) && /Completed/.test(sub.textContent) && /Comment/.test(sub.textContent), 'list, Completed and Comment under the title: ' + (sub?.textContent || ''));
  check(sub?.querySelector('mark')?.textContent.toLowerCase() === 'zitronen', 'the snippet marks what was typed (the word beginning): ' + sub?.innerHTML);
  check(items().filter(b => b.querySelector('.plt')?.textContent === 'Zitronenfalter photo').length === 1, 'a task the palette lists locally comes once');
  if (it) click(w, it);
  const opened = await until(() => w.eval(`S.sel === ${T}`) && d.querySelector(`#detail [data-mid="c:${C}"]`));
  check(opened, 'a click opens the task and shows the comment');
  check(TO > 0, 'setup: the open task');

  // offline: no group, no error
  w.eval('closePalette()'); w.eval('openPalette()'); await sleep(100);
  w.__offline = true;  // every request fails (the device is offline)
  input(w, d.querySelector('.palette .pqin'), 'zitronenf'); await sleep(600);
  check(![...d.querySelectorAll('.palette .pgroup')].some(g => g.textContent === 'Everywhere'), 'offline: no group "Everywhere"');
  w.__offline = false; w.eval('closePalette()');
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  w.close();
  console.log(`p2116_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
