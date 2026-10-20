// 2.116.0 UI tests (part C, #2064 #2068), own container (start.sh). jsdom:
//   the list menu has "Export as CSV" and "Print" (a list with the lock: CSV greyed out); "Print" opens the page with the tasks
//   by section, the checkbox, due / priority / tags, subtasks indented; "Show completed" and "Show notes" switch; Close removes it;
//   code snippets in an ordinary (not software) list: the task menu offers "Add code snippet", the form saves one, it shows in the detail.
// P2116C_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2116C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Kitchen plans'})).id;
  const sec = (await call('POST', '/api/sections', {list_id: L, name: 'Phase one'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Order tiles', list_id: L, section_id: sec, due: '2031-05-04', priority: 5, tags: ['urgent'], content: 'Ask for samples'})).id;
  await call('POST', '/api/tasks', {title: 'Measure floor', parent_id: T1});
  await call('POST', '/api/tasks', {title: 'Loose task', list_id: L});
  const T3 = (await call('POST', '/api/tasks', {title: 'Finished job', list_id: L})).id;
  await call('POST', `/api/tasks/${T3}/complete`, {});

  // ================= the list menu
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await until(() => w.eval(`!!taskById(${T1})`));
  const items = w.eval(`listMenuItems(${L}, document.querySelector('#top h1')).flatMap(x => x.more || [x]).filter(x => x !== '-').map(x => x.label)`);
  check(items.includes('Export as CSV') && items.includes('Print'), 'the list menu has "Export as CSV" and "Print" ' + items);

  // ================= the print page
  w.eval(`lexPrint(${L})`);
  const pg = await until(() => d.querySelector('.tsheet .lexpage .lxr'));
  check(pg && d.body.classList.contains('tsprint'), 'the print page opens');
  const txt = () => d.querySelector('.tsheet .lexpage').textContent;
  check(/Kitchen plans/.test(txt()) && /Phase one/.test(txt()) && /Order tiles/.test(txt()) && /#urgent/.test(txt()) && /High/.test(txt()), 'title, section, task with tags and priority ' + txt().slice(0, 200));
  const sub = [...d.querySelectorAll('.lexpage .lxr')].find(x => /Measure floor/.test(x.textContent));
  check(sub && parseFloat(sub.style.marginLeft) > 0, 'the subtask is indented');
  check(d.querySelector('.lexpage .lxr .lxbox') && /Finished job/.test(txt()), 'checkbox per task; completed shown by default');
  check(!/Ask for samples/.test(txt()), 'notes hidden by default');
  const cb = d.querySelector('#lex-notes'); cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(/Ask for samples/.test(txt()), '"Show notes" shows them');
  const cd = d.querySelector('#lex-done'); cd.checked = false; cd.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!/Finished job/.test(txt()) && /Loose task/.test(txt()), '"Show completed" off hides the completed');
  d.querySelector('.tsheet [data-ts="close"]').click();
  check(!d.querySelector('.tsheet') && !d.body.classList.contains('tsprint'), 'Close removes the page');

  // ================= a code snippet in an ordinary list (the task menu)
  w.eval(`openDetail(${T1})`); await until(() => d.querySelector('#detail [data-act="task-menu"]'));
  check(!d.querySelector('#d-snips'), 'an ordinary list: no snippet section yet');
  w.eval(`snipOpen(${T1}, 'new')`);
  const ta = await until(() => d.querySelector('#snip-code'));
  ta.value = 'echo hello'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  d.querySelector('[data-act="snip-save"]').click();
  const st = await until(async () => { const t = await call('GET', `/api/tasks/${T1}`); return t.snippets?.length ? t : null; });
  check(st && st.snippets[0].code === 'echo hello', 'the snippet is saved ' + JSON.stringify(st?.snippets));
  await until(() => d.querySelector('#d-snips .snip pre'));
  check(/echo hello/.test(d.querySelector('#d-snips .snip pre')?.textContent || ''), 'it shows in the detail');

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
