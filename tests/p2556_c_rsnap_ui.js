// 2.556.0 C (#4583) UI test (jsdom), fresh DB: the completed copy of a recurring task shows, read only, which of its subtasks
// were done when it was ticked ("3 of 5 subtasks done" + the titles with a tick / open); the original shows none of it.
// kalmido-suite: fresh
const {boot, errs, B, login, until, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Routine'})).id;
  const due = new Date().toISOString().slice(0, 10);
  const R = (await call('POST', '/api/tasks', {title: 'Weekly review', list_id: L, due, repeat: 'FREQ=WEEKLY'})).id;
  const subs = [];
  for (let i = 1; i <= 5; i++) subs.push((await call('POST', '/api/tasks', {title: `Step ${i}`, list_id: L, parent_id: R})).id);
  for (const k of subs.slice(0, 3)) await call('POST', `/api/tasks/${k}/complete`, {});
  const j = await call('POST', `/api/tasks/${R}/complete`, {});
  check(j.next_due && j.next_due > due, 'setup: ticked, moved on ' + j.next_due);  // (status: the task's own, it is open again)

  const w = await boot({user: 'alice', hash: `l/${L}`}), d = w.document;
  const cp = await until(() => w.eval(`[...S.tasks.values()].find(t => t.list_id === ${L} && t.id !== ${R} && !t.parent_id && t.status === 2)?.id`));
  check(cp, 'the completed copy is in the page');
  w.eval(`openDetail(${cp})`); await idle(w);
  const box = await until(() => d.querySelector('#detail .subsec .rsnap'));
  check(box && /3 of 5 subtasks done/.test(box.textContent), 'the copy: "3 of 5 subtasks done" ' + (box?.textContent || '').trim().slice(0, 80));
  const li = box ? [...box.querySelectorAll('li')] : [];
  check(li.map(x => x.textContent.trim()).join('|') === 'Step 1|Step 2|Step 3|Step 4|Step 5', 'the titles in their order ' + li.map(x => x.textContent.trim()).join('|'));
  check(li.map(x => x.className).join() === 'done,done,done,open,open', 'three with a tick, two open ' + li.map(x => x.className).join());
  check(!box?.querySelector('input, button, [data-act]'), 'read only: nothing to click');
  w.eval(`openDetail(${R})`); await idle(w);
  check(await until(() => w.eval(`S.sel === ${R}`)) && !d.querySelector('#detail .rsnap'), 'the original shows no snapshot');
  // 2.556.0 C review (#4583, finding 3): a copy that is open again (or a series again) shows no old round, even with the field
  w.eval(`Object.assign(S.tasks.get(${cp}), {status: 0}); openDetail(${cp})`); await idle(w);
  check(await until(() => w.eval(`S.sel === ${cp}`)) && !d.querySelector('#detail .rsnap'), 'reopened copy: no snapshot');
  w.eval(`Object.assign(S.tasks.get(${cp}), {status: 2, repeat: 'FREQ=WEEKLY'}); openDetail(${R}); openDetail(${cp})`); await idle(w);
  check(await until(() => w.eval(`S.sel === ${cp}`)) && !d.querySelector('#detail .rsnap'), 'copy with a repeat: no snapshot');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2556_c_rsnap_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
