// 2.280.0 A (#3109) UI test, own container (start.sh), Firefox (1440 x 900): a change of someone else no longer loads the
// whole state in the open app (S.lpN.state stays). freelancer-matrix: tasks (alice has no organisation)
// - bob books time on his own task, writes a knowledge page, changes his settings: the app takes a lean delta, no state load
// - bob comments his own task (light area): the bundled follow-up (lpFollow) takes the delta + the sidebar's parts, no state
//   load; a comment on the shared task: its row count follows through that delta (the same result as the full reload)
// - alice's own setting from this window: no state load; from another device of hers: the full way (and the new value)
// - 2.280.0 F (#3109): a change seen while typing / held back by the brake is taken later (never dropped); a braked follow-up again
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2280_a_ui', check, shots: 'P2280A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['comments', 'time', 'wiki']});
  const FEAT = 'comments,collab,time,wiki';
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: []});
  check(bob.id > 0, 'setup: bob ' + JSON.stringify(bob).slice(0, 200));
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Shared plan'})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: bob.id, role: 'edit'});
  const TS = (await call(CA, 'POST', '/api/tasks', {title: 'Shared task', list_id: L})).id;
  const LB = (await call(CB, 'POST', '/api/lists', {name: 'Bob alone'})).id;
  await call(CB, 'PATCH', `/api/lists/${LB}`, {time_tracking: 1});
  const TB = (await call(CB, 'POST', '/api/tasks', {title: 'Bob task', list_id: LB})).id;
  check(L > 0 && TS > 0 && LB > 0 && TB > 0, 'setup: lists and tasks');

  await firefox(async o => {
    const {ev, nav, cmd, ctx} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    // the page has taken the server's last change (its poll saw the version and is done)
    const caught = () => ready(`fetch('/api/version', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.v === S.v && !td_polling)`, 120);
    // the bundled follow-up of a light change, at once instead of after LP_DEFER_MS
    const follow = () => ev(`(async () => { if (lpT) { clearTimeout(lpT); await lpFollow(); } return lpT === 0; })()`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`typeof lpFollow === 'function' && !!document.querySelector('#view [data-id="${TS}"]') && !!S.lpA`, 60), 'the list and the poll areas');
    await caught();
    const st0 = await ev('S.lpN.state'), dl0 = await ev('S.lpN.delta');
    const st = () => ev('S.lpN.state');

    const te = await call(CB, 'POST', '/api/time/entries', {task_id: TB, start: '2026-01-05T09:00', minutes: 30});
    check(te.http === 200 || te.http === 201, 'bob books time ' + te.http);
    check(await caught(), 'the poll saw bob\'s time entry');
    check(await st() === st0 && await ev('S.lpN.delta') > dl0, `#3109 bob's time entry: a delta, no state load (was the whole state) ${await st()} vs ${st0}`);

    const wp = await call(CB, 'POST', '/api/wiki/pages', {space: 'private', path: 'Invented note', body: 'Invented text'});
    check(wp.http === 200 || wp.http === 201, 'bob writes a knowledge page ' + wp.http);
    check(await caught(), 'the poll saw bob\'s page');
    check(await follow(), 'the follow-up of the page ran');
    check(await st() === st0, `#3109 bob's knowledge page: no state load ${await st()} vs ${st0}`);

    await call(CB, 'PATCH', '/api/settings', {allday_time: '08:00'});
    check(await caught(), 'the poll saw bob\'s setting');
    check(await st() === st0, `#3109 bob's own setting: no state load ${await st()} vs ${st0}`);

    await call(CB, 'POST', `/api/tasks/${TB}/comments`, {body: 'Note on my own task'});
    check(await caught(), 'the poll saw bob\'s comment');
    check(await ev('lpT !== 0'), '#3109 a comment: the bundled follow-up is planned');
    check(await follow(), 'the follow-up ran');
    check(await st() === st0, `#3109 bob's comment on his own task: the follow-up takes a delta, no state load ${await st()} vs ${st0}`);

    await call(CB, 'POST', `/api/tasks/${TS}/comments`, {body: 'Note on the shared task'});
    check(await caught(), 'the poll saw the comment on the shared task');
    check(await follow(), 'the follow-up ran');
    check(await ready(`(S.tasks.get(${TS})?.comment_count || 0) === 1`, 20), `#3109 the shared task's comment count follows through the delta ${await ev(`S.tasks.get(${TS})?.comment_count`)}`);
    check(await st() === st0, `#3109 ... still no state load ${await st()} vs ${st0}`);

    await ev(`api('PATCH', '/api/settings', {allday_time: '09:30'}).then(() => 1)`);
    check(await caught(), 'the poll saw alice\'s own setting');
    check(await st() === st0, `#3109 alice's setting from this window: no state load ${await st()} vs ${st0}`);
    await call(CA, 'PATCH', '/api/settings', {allday_time: '10:00'});
    check(await caught(), 'the poll saw the setting of alice\'s other device');
    check(await ready(`S.lpN.state === ${st0} + 1 && S.settings.allday_time === '10:00'`, 40),
      `#3109 alice's setting from another device: the full way as before ${JSON.stringify(await ev(`({st: S.lpN.state, t: S.settings.allday_time})`))}`);
    console.log(`PERF #3109 one window, 6 changes of others / another device: ${await st() - st0} state loads, ${await ev('S.lpN.delta') - dl0} deltas`);

    // 2.280.0 F (#3109): a change the poll saw while typing is taken once the field is left (it was dropped: lean delta only)
    await ev('(imeOn = true, 1)');
    await call(CA, 'PATCH', '/api/settings', {allday_time: '11:00'});
    check(await ready(`fetch('/api/version', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => JSON.stringify(j.a) === JSON.stringify(S.lpA) && !td_polling)`, 120), 'the poll saw the other device\'s setting while typing');
    check(await ev(`S.settings.allday_time !== '11:00'`), 'while typing: not taken yet');
    await ev('(imeOn = false, 1)');
    check(await ready(`S.settings.allday_time === '11:00'`, 60), `#3109 F a change seen while typing is taken afterwards ${await ev('S.settings.allday_time')}`);
    // 2.280.0 F (#3109): the brake holds a reload back - the change stays pending and comes with a later poll
    check(await ready(`load(true).then(r => r !== 'brake')`, 60), 'an automatic reload of this window (the next one within seconds is braked)');
    await call(CA, 'PATCH', '/api/settings', {allday_time: '12:00'});
    check(await ready(`S.settings.allday_time === '12:00'`, 80), `#3109 F a braked reload: the change comes later ${await ev('S.settings.allday_time')}`);
    // the bundled follow-up whose full load is braked plans itself again
    check(await ready(`load(true).then(r => r !== 'brake')`, 60), 'an automatic reload of this window again');
    await call(CB, 'POST', `/api/tasks/${TS}/comments`, {body: 'Second note on the shared task'});
    check(await caught(), 'the poll saw the second comment');
    check(await ev(`(S.lpBase = 1e9, lpT !== 0 && (S.tasks.get(${TS})?.comment_count || 0) === 1)`), 'the follow-up is planned, the count not there yet (its delta answers full: since too new)');
    check(!(await follow()), '#3109 F the braked follow-up plans itself again');
    check(await ready(`(S.tasks.get(${TS})?.comment_count || 0) === 2`, 80), `#3109 F ... and brings the comment count later ${await ev(`S.tasks.get(${TS})?.comment_count`)}`);
  }, false);

  console.log(`p2280_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
