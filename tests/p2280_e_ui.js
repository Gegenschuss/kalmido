// 2.280.0 A (#3108) UI test (jsdom), fresh DB: a long note is not in the start state; the detail loads it. freelancer-matrix: tasks
// (alice has no organisation)
// - the start state: the long note's task has no content (content_n), the short one keeps it
// - opening the task: the note arrives (GET /api/tasks/<id>) and is shown; then editing it saves as before
// - offline: a task whose long note is not loaded shows "Only available online." and no note field; nothing is queued, and
//   back online the server still has the note unchanged (an empty note is never saved); the note then loads
// - a full reload keeps a note already loaded while the task is unchanged
// - 2.280.0 F (#3108): undoing a change of a task whose long note was not loaded (menu / table cell) keeps the note; a local
//   copy of a note that is not the server's (a save that failed) is loaded again; a reference card comes from the local task;
//   a refused note load says so (not "online only"), back online the open task loads at once; notes for printing load at
//   most 6 at a time; a note emptied here drops the note mark of the row
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Briefs'})).id;
  const LONG = 'Invented brief, first line.\n' + 'Lots of words about the shoot. '.repeat(20) + '\nEND-OF-NOTE';
  const LONG2 = 'Second invented brief.\n' + 'Other words about the edit. '.repeat(20) + '\nEND-TWO';
  const TL = (await call('POST', '/api/tasks', {title: 'Long note', list_id: P, content: LONG})).id;
  const TL2 = (await call('POST', '/api/tasks', {title: 'Long note two', list_id: P, content: LONG2})).id;
  const TS = (await call('POST', '/api/tasks', {title: 'Short note', list_id: P, content: 'Short invented note'})).id;
  const LONG3 = 'Third invented brief.\n' + 'Words about the grade. '.repeat(20) + '\nEND-THREE';
  const TL3 = (await call('POST', '/api/tasks', {title: 'Long note three', list_id: P, content: LONG3})).id;
  const MANY = [];
  for (let i = 0; i < 8; i++) MANY.push((await call('POST', '/api/tasks', {title: 'Print note ' + i, list_id: P, content: LONG + ' no ' + i})).id);
  check(TL > 0 && TL2 > 0 && TS > 0 && TL3 > 0 && MANY.every(x => x > 0) && LONG.length > 200, 'setup');

  const w = await boot({user: 'alice', hash: 'l/' + P});
  check(await until(() => w.eval(`S.tasks.has(${TL}) && !!document.querySelector('#view [data-id="${TL}"]')`)), 'the list is drawn');
  check(w.eval(`!('content' in S.tasks.get(${TL})) && S.tasks.get(${TL}).content_n === ${LONG.length}`), '#3108 the start state: the long note is not in it (content_n)');
  check(w.eval(`S.tasks.get(${TS}).content`) === 'Short invented note', '#3108 a short note stays in the start state');

  // 2.280.0 F (#3108): undo of a change made while the long note was not loaded must not empty the note
  check(w.eval(`!('content' in S.tasks.get(${TL3}))`), 'the third long note is not loaded');
  await w.eval(`patchUndoable(${TL3}, {priority: 3}, 'x')`);
  await w.eval(`histStep('undo')`);
  let s3 = await call('GET', `/api/tasks/${TL3}`);
  check(s3.priority === 0 && s3.content === LONG3, '#3108 F undo of a menu change (patchUndoable) keeps the long note: ' + JSON.stringify([s3.priority, (s3.content || '').length]));
  await w.eval(`load()`);
  check(w.eval(`!('content' in S.tasks.get(${TL3})) || S.tasks.get(${TL3}).content === ${JSON.stringify(LONG3)}`), 'the note is unloaded again or whole');
  w.eval(`S.tasks.get(${TL3}) && delete S.tasks.get(${TL3}).content`);
  await w.eval(`patchTask(${TL3}, {due: '2031-02-03'})`);
  await w.eval(`histStep('undo')`);
  s3 = await call('GET', `/api/tasks/${TL3}`);
  check(!s3.due && s3.content === LONG3, '#3108 F undo of a direct change (patchTask history) keeps the long note: ' + JSON.stringify([s3.due, (s3.content || '').length]));
  await w.eval(`histStep('redo')`);
  s3 = await call('GET', `/api/tasks/${TL3}`);
  check(s3.due === '2031-02-03' && s3.content === LONG3, '#3108 F redo keeps the long note too');

  // 2.280.0 F (#3108): the reference card of a task whose long note is not loaded: from the local task (no fetch, offline the title)
  check(w.eval(`rf_get('t:${TL2}')?.name`) === 'Long note two', '#3108 F a reference card takes the local task (was: fetched, "…" offline)');
  // 2.280.0 F (#3108): the print view loads the notes at most 6 at a time
  w.eval(`window.__rf0 = rawFetch; window.__cur = 0; window.__max = 0; rawFetch = async (...a) => { if (!${JSON.stringify(MANY)}.some(id => a[1].includes('/tasks/' + id))) return __rf0(...a); __cur++; __max = Math.max(__max, __cur); try { return await __rf0(...a); } finally { __cur--; } }`);  // #3506: only the notes - the 4 s poll made it 7 in a full run
  const pr = await w.eval(`tkNotesLoad(${JSON.stringify(MANY)}).then(r => r.map(x => x.status))`);
  w.eval(`rawFetch = __rf0`);
  check(pr.length === 8 && pr.every(x => x === 'fulfilled') && w.eval(`__max`) <= 6, `#3108 F notes for printing: all loaded, at most 6 at once ${JSON.stringify(pr)} max ${w.eval('__max')}`);
  // 2.280.0 F (#3108): a note emptied here: the row's note mark goes (content_n stays from the start state)
  check(w.eval(`(() => { const t = S.tasks.get(${MANY[0]}), a = taskRow({...t, content: '', content_n: 500}), c = taskRow({...t, content: ''}), b = taskRow((({content, ...x}) => ({...x, content_n: 500}))(t)); return a === c && b !== c; })()`),
    '#3108 F a note emptied here drops the note mark (content_n of the start state does not count any more)');

  // the detail loads the note
  w.eval(`openDetail(${TL})`);
  check(await until(() => w.eval(`(document.querySelector('#d-md')?.textContent || '').includes('END-OF-NOTE')`)), '#3108 opening the task shows its note (loaded)');
  check(w.eval(`S.tasks.get(${TL}).content`) === LONG, '#3108 the note is in S.tasks now');
  // a full reload keeps the loaded note (the task did not change)
  await w.eval('load()');
  check(w.eval(`S.tasks.get(${TL}).content`) === LONG, '#3108 a full reload keeps the loaded note');
  // 2.280.0 F (#3108): a local copy that is not the server's (a save that failed, same updated_at) is not kept by a full reload
  w.eval(`S.tasks.get(${TL}).content = 'Unsaved invented text'`);
  w.eval(`saveTimers['${TL}:content'] = {id: ${TL}, field: 'content', value: 'Unsaved invented text', t: 0}`);
  await w.eval('load()');
  check(w.eval(`S.tasks.get(${TL}).content`) === 'Unsaved invented text', '#3108 F a note waiting to be saved stays over a full reload');
  w.eval(`delete saveTimers['${TL}:content']`);
  await w.eval('load()');
  check(w.eval(`S.tasks.get(${TL}).content`) !== 'Unsaved invented text', '#3108 F a local note that is not the server\'s is dropped by a full reload (loaded again)');
  w.eval('render()');  // as after the poll's reload (td_renderSoon)
  check(await until(() => w.eval(`S.tasks.get(${TL}).content === ${JSON.stringify(LONG)}`)), '#3108 F ... and the server\'s note comes back (the open detail loads it)');
  w.eval('closeDetail()');

  // offline: the other long note was never loaded
  w.__offline = true;
  w.eval(`openDetail(${TL2})`);
  check(await until(() => w.eval(`(document.querySelector('#d-note-wait')?.textContent || '').trim() === tr('Only available online.')`)),
    '#3108 offline: "Only available online." instead of the note');
  check(w.eval(`!document.querySelector('#d-content')`), '#3108 offline: no note field to type into');
  check(w.eval('OUT.q.length') === 0, '#3108 offline: nothing queued');
  w.__offline = false;
  w.dispatchEvent(new w.Event('online'));
  check(await until(() => w.eval('OUT.q.length') === 0), 'the queue is empty');
  const srv = await call('GET', `/api/tasks/${TL2}`);
  check(srv.content === LONG2, '#3108 back online: the server still has the whole note (no empty note saved)');
  // 2.280.0 F (#3108): the online event loads the open task's note at once (was: "Only available online." until reopened)
  check(await until(() => w.eval(`(document.querySelector('#d-md')?.textContent || '').includes('END-TWO')`)), '#3108 F online again: the note loads by itself');
  // 2.280.0 F (#3108): a refused load (gone / no access) is not "Only available online."
  w.eval(`(() => { const t = {...S.tasks.get(${TL3}), id: 987654, title: 'Gone task'}; delete t.content; t.content_n = 300; S.tasks.set(987654, t); openDetail(987654); })()`);
  check(await until(() => w.eval(`(() => { const x = (document.querySelector('#d-note-wait')?.textContent || '').trim(); return !!x && x !== tr('Loading…') && !TKN_WAIT.has(987654); })()`)), 'the refused load finished');
  check(w.eval(`(document.querySelector('#d-note-wait')?.textContent || '').trim() !== tr('Only available online.')`), '#3108 F a refused note load is not "Only available online.": ' + w.eval(`document.querySelector('#d-note-wait')?.textContent`));
  w.eval(`closeDetail(); S.tasks.delete(987654)`);
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2280_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
