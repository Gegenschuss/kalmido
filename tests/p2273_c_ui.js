// 2.273.0 part C UI test (jsdom), fresh DB, English (#3051 point 11):
//  - one date of a repeating event saved from a stale editor copy: the server answers 409 (expect is sent like for the
//    series), the editor stays open with the hint, the date is not changed
//  - the automatic reload sees every typed but unsaved text field (here the task description), not only a fixed list
//  - "checklist lines -> subtasks" waits for the pending save of the typed description (flushSaves) before it cuts the
//    lines out: afterwards the server has the typed text and no open checklist line
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const W = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const t1 = day(1);
  const ev = await call('POST', '/api/events', {title: 'Weekly', cal_id: W.id, start: `${t1}T09:00`, end: `${t1}T09:30`, rrule: 'FREQ=WEEKLY;COUNT=4'});
  check(ev.id || ev.eid, 'a weekly event');
  const eid = ev.id || ev.eid;
  const occ = `${t1}T09:00`;

  // ---- one date from a stale copy: 409 + hint, nothing changed
  let w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
  await until(() => d.querySelector('#view [data-act="ev-new"]'));
  const full = await call('GET', `/api/events/${eid}`);
  w.eval(`evEditor({ev: ${JSON.stringify(full)}, occ: ${JSON.stringify(occ)}})`);
  let md = await until(() => d.querySelector('.modal.evmodal'));
  await call('PATCH', `/api/events/${eid}`, {title: 'Weekly (renamed elsewhere)'});  // someone else changes the event meanwhile
  click(w, md.querySelector('[data-evsc="one"]'));
  md.querySelector('#ev-title').value = 'Only this date';
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(() => /changed meanwhile/i.test(d.querySelector('#toast')?.textContent || '')), 'the 409 hint of the stale copy shows: ' + (d.querySelector('#toast')?.textContent || ''));
  check(d.querySelector('.modal.evmodal'), 'the editor stays open (nothing lost)');
  const after = await call('GET', `/api/events/${eid}`);
  check(after.title === 'Weekly (renamed elsewhere)' && !(after.overrides || []).some(o => o.rid === occ), 'the date was not changed from the stale copy ' + JSON.stringify(after.overrides || []));
  // a fresh copy saves the date
  click(w, d.querySelector('.modal.evmodal [data-evm="close"]'));
  w.eval(`evEditor({ev: ${JSON.stringify(after)}, occ: ${JSON.stringify(occ)}})`);
  md = await until(() => d.querySelector('.modal.evmodal'));
  click(w, md.querySelector('[data-evsc="one"]'));
  md.querySelector('#ev-title').value = 'Only this date';
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(async () => ((await call('GET', `/api/events/${eid}`)).overrides || []).some(o => o.rid === occ && o.title === 'Only this date')), 'a fresh copy saves only this date');
  w.close();

  // ---- the automatic reload sees an unsaved description; mdToSubtasks waits for its save
  const L = (await call('GET', '/api/state')).lists.find(l => l.is_inbox) || (await call('GET', '/api/state')).lists[0];
  const t = await call('POST', '/api/tasks', {title: 'Packing', list_id: L.id, content: 'Notes\n- [ ] Passport\n- [ ] Tickets'});
  w = await boot({user: 'alice'}); d = w.document;
  await until(() => w.eval('typeof openDetail') === 'function' && w.eval(`!!taskById(${t.id})`));
  w.eval(`openDetail(${t.id})`);
  await until(() => d.querySelector('#d-content') || d.querySelector('[data-act="content-edit"]'));
  if (!d.querySelector('#d-content')) { w.eval('S.editContent = true; renderDetail()'); await until(() => d.querySelector('#d-content')); }
  const ta = d.querySelector('#d-content');
  check(ta && !w.eval('verDraft()'), 'nothing typed: no draft');
  ta.value = ta.value + '\nCall the hotel';
  ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(w.eval('verDraft()'), 'typed but not saved: the automatic reload waits (a draft)');
  await w.eval('mdToSubtasks()');
  const st = await call('GET', `/api/tasks/${t.id}`);
  const subs = (await call('GET', '/api/state')).tasks.filter(x => x.parent_id === t.id).map(x => x.title).sort();
  check(/Call the hotel/.test(st.content || '') && !/- \[ \]/.test(st.content || ''), 'after the step the server has the typed text and no open checklist line: ' + JSON.stringify(st.content));
  check(subs.join() === 'Passport,Tickets', 'the two subtasks were made ' + subs.join());
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
