// 2.98.0 UI tests (part A, #1953), own container (start.sh): scheduling polls. jsdom:
//   the calendar bar's "Find a date" opens the list (empty), "New poll" the form (three proposed times, + a time, a time
//   removed), Create makes the poll (ONE undo step: undo = trash, redo = back), the poll window shows the link + copy + QR;
//   two visitors vote on the public page (fetch, with its stamp), the window shows the counts, the names and the best time,
//   "Choose this time" opens the calendar dialog and makes ONE event (undo = reopen, the event goes to the trash);
//   the task's "Find a date" and the client menu's "Find a date…" exist; a person without an organisation sees no workspace field.
// Firefox 402 x 844 touch: the public page (open and closed) and the app's poll window without horizontal scrolling, the
// answers >= 44 px high; screenshots with P298A_SHOTS. P298A_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p298_a_ui', check, shots: 'P298A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P298A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const vpath = url => '/vote/' + url.split('/vote/')[1];
async function vote(p, name, answers, email = '') {  // a visitor: the page (its stamp), 3 s, the form
  const pg = await (await fetch(B + p.replace(/^\//, ''), {headers: {'Accept-Language': 'en'}})).text();
  const stamp = (pg.match(/name="stamp" value="([^"]+)"/) || [])[1] || '';
  await sleep(3300);
  const fd = new URLSearchParams({name, email, stamp, ...Object.fromEntries(Object.entries(answers).map(([k, v]) => ['a' + k, v]))});
  return (await fetch(B + p.replace(/^\//, ''), {method: 'POST', body: fd, headers: {'Accept-Language': 'en'}})).status;
}
const FEAT = 'collab,comments,events,cal,clients,office';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('POST', '/api/users', {username: 'dave', display_name: 'Dave', password: 'password123', email: 'dave@example.com', orgs: []});
  const DK = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, DK);

  // ================= the calendar bar -> list -> new poll -> create (undo / redo)
  let w = await boot({user: 'alice', hash: 'cal'}), d = w.document;
  const fb = await until(() => d.querySelector('#view [data-act="tpo-list"]'));
  check(fb && /Find a date/.test(fb.textContent), 'the calendar bar has "Find a date"');
  fb?.click();
  const ld = await until(() => d.querySelector('.tpo-dlg'));
  check(ld && /No polls yet/.test(ld.textContent), 'the list: empty');
  d.querySelector('.tpo-dlg [data-tpo="new"]')?.click();
  const fm = await until(() => d.querySelector('.tpo-dlg #tpo-title'));
  check(fm && d.querySelectorAll('.tpo-dlg .tpo-row').length === 3, 'the form: three proposed times');
  check(d.querySelector('.tpo-dlg #tpo-sp'), 'with an organisation: the workspace field');
  d.querySelector('.tpo-dlg [data-tpo="add"]')?.click();
  check(d.querySelectorAll('.tpo-dlg .tpo-row').length === 4, '+ a time');
  d.querySelectorAll('.tpo-dlg .tpo-row [data-tpo="rm"]')[3]?.click();
  check(d.querySelectorAll('.tpo-dlg .tpo-row').length === 3, 'a time removed');
  fm.value = 'Planning day';
  const rows = [...d.querySelectorAll('.tpo-dlg .tpo-row')];
  ['2031-05-05', '2031-05-06', '2031-05-07'].forEach((x, i) => { rows[i].querySelector('.tpo-d').value = x; rows[i].querySelector('.tpo-t').value = '09:30'; });
  d.querySelector('.tpo-dlg #tpo-loc').value = 'Studio';
  d.querySelector('.tpo-dlg #tpo-sp').value = 'private';
  d.querySelector('.tpo-dlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const made = await until(async () => { const l = await call('GET', '/api/polls'); return l.items?.length === 1 && l.items[0]; });
  check(made && made.title === 'Planning day' && made.space === 'private', 'created through the form ' + JSON.stringify(made).slice(0, 200));
  const PID = made && made.id;
  const sw = await until(() => d.querySelector('.tpo-dlg .tpo-link input'));
  check(sw && /\/vote\//.test(sw.value) && d.querySelector('.tpo-dlg [data-tpo="copy"]') && d.querySelector('.tpo-dlg [data-tpo="qr"]'), 'the poll window: link, copy, QR');
  check(d.querySelectorAll('.tpo-dlg .tpo-o').length === 3 && /No votes yet/.test(d.querySelector('.tpo-dlg').textContent), 'three times, no votes yet');
  d.querySelector('.tpo-dlg [data-tpo="qr"]')?.click();
  check(await until(() => d.querySelector('.tpo-dlg .tpo-qr img')), 'the QR code');
  d.querySelector('.tpo-dlg [data-tpo="close"]')?.click();
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/polls/' + PID)).status === 404), 'undo: the poll is in the trash');
  await w.eval(`histStep('redo')`);
  check(await until(async () => (await call('GET', '/api/polls/' + PID)).status === 200), 'redo: it is back');

  // ================= votes -> the counts, the best time -> choose (undo = reopen)
  const P = (await call('GET', '/api/polls/' + PID)).poll, VP = vpath(P.url);
  const [o1, o2, o3] = P.options.map(o => o.id);
  check(await vote(VP, 'Anna', {[o1]: 'm', [o2]: 'y', [o3]: 'n'}, 'anna@example.com') === 200, 'Anna voted');
  check(await vote(VP, 'Ben', {[o1]: 'y', [o2]: 'y'}) === 200, 'Ben voted');
  await w.eval(`tpo_show(${PID})`);
  const best = await until(() => d.querySelector('.tpo-dlg .tpo-o.tpo-best'));
  check(best && /2 yes · 0 maybe/.test(best.textContent) && /Anna/.test(best.textContent) && /Ben/.test(best.textContent), 'the best time: 2 yes, the names ' + (best?.textContent || '').slice(0, 200));
  check(/2 votes/.test(d.querySelector('.tpo-dlg .tpo-sub')?.textContent || ''), 'the status: 2 votes');
  best?.querySelector('[data-tpo-pick]')?.click();
  const dc = await until(() => d.querySelector('#tpo-cal'));
  check(dc && dc.options.length >= 1 && d.querySelector('#tpo-mail') && !d.querySelector('#tpo-mail').checked, 'the choose dialog: a calendar, the invitation off by default');
  d.querySelector('#tpo-cal')?.closest('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const closed = await until(async () => { const g = await call('GET', '/api/polls/' + PID); return g.poll?.closed_at && g.poll; });
  check(closed && closed.chosen_id === o2 && closed.event_id, 'chosen: closed, an event ' + JSON.stringify(closed).slice(0, 200));
  const ev = closed ? await call('GET', '/api/events/' + closed.event_id) : {};
  check(ev.title === 'Planning day' && ev.location === 'Studio', 'the event: title and place');
  check(await until(() => /Open event/.test(d.querySelector('.tpo-dlg')?.textContent || '')), 'the window: Open event, Reopen');
  await w.eval(`histStep('undo')`);
  check(await until(async () => { const g = await call('GET', '/api/polls/' + PID); return g.poll && !g.poll.closed_at; }), 'undo: the poll is open again');
  check(closed && (await call('GET', '/api/events/' + closed.event_id)).status === 404, 'undo: the event went to the trash');
  await w.eval(`histStep('redo')`);
  check(await until(async () => (await call('GET', '/api/polls/' + PID)).poll?.closed_at), 'redo: the time is chosen again');

  // ================= the task and the client offer it
  const L = await call('POST', '/api/lists', {name: 'Work', org_id: null});
  const T = await call('POST', '/api/tasks', {list_id: L.id, title: 'Board meeting'});
  check(w.eval(`evTaskHtml(taskById(${T.id}) || {id: ${T.id}, list_id: ${L.id}}, false).includes('data-act="tpo-task"')`), 'a task offers "Find a date"');
  check(w.eval(`evTaskHtml({id: ${T.id}, list_id: ${L.id}}, true).includes('tpo-task') === false`), 'read-only: no entry');
  const cpj = await (await fetch(B + 'static/js/clientpage.js')).text();
  check(w.eval(`typeof tpo_forClient === 'function'`) && cpj.includes("tr('Find a date…'), icon: 'users', fn: () => tpo_forClient(c)"), 'the client menu has its entry');
  w.close();

  // ================= without an organisation: no workspace field
  w = await boot({user: 'dave', hash: 'cal'}); d = w.document;
  await until(() => d.querySelector('#view [data-act="tpo-list"]'));
  await w.eval(`tpo_edit()`);
  check(await until(() => d.querySelector('.tpo-dlg #tpo-title')) && !d.querySelector('.tpo-dlg #tpo-sp'), 'a person without an organisation: no workspace field');
  w.close();
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));

  // ================= Firefox 402 touch: the public page and the poll window
  const Q = (await call('POST', '/api/polls', {title: 'Coffee with the whole team and a rather long title to wrap', location: 'https://video.example.com/room/123456789',
    tz: 'Europe/Berlin', duration: 30, space: 'private', options: [{start: '2031-06-02T08:00'}, {start: '2031-06-03T16:30'}, {start: '2031-06-04T12:00'}]})).poll;
  const QP = vpath(Q.url);
  await vote(QP, 'Carla with a long double name', {[Q.options[0].id]: 'y', [Q.options[1].id]: 'm'});
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 844}});
    await nav(B + QP.replace(/^\//, ''));
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('.tpo-form')`).catch(() => false)); i++) await sleep(250);
    const g = await ev(`(() => { const a = [...document.querySelectorAll('.tpo-a span')].map(x => x.getBoundingClientRect());
      return {wide: document.documentElement.scrollWidth <= innerWidth + 1, n: a.length, min: Math.min(...a.map(r => r.height)), tz: document.querySelector('.tpo-tz')?.textContent || ''}; })()`);
    check(g && g.wide, '402: the public page has no horizontal scrolling ' + JSON.stringify(g));
    check(g && g.n === 9 && g.min >= 43.5, '402: three answers per time, >= 44 px ' + JSON.stringify(g));
    await shot('p298a-402-vote.png');
    await nav(B + '#cal');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('[data-act="tpo-list"]')`).catch(() => false)); i++) await sleep(300);
    await ev(`(tpo_show(${Q.id}), 1)`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('.tpo-dlg .tpo-o')`).catch(() => false)); i++) await sleep(250);
    await sleep(500);
    const a = await ev(`(() => { const c = document.querySelector('.tpo-dlg .card'); const b = [...document.querySelectorAll('.tpo-dlg .tpo-o .btn')].map(x => x.getBoundingClientRect().height);
      return {wide: c.scrollWidth <= c.clientWidth + 1 && document.documentElement.scrollWidth <= innerWidth + 1, min: Math.min(...b)}; })()`);
    check(a && a.wide && a.min >= 39.5, '402: the poll window has no horizontal scrolling, the buttons >= 40 px ' + JSON.stringify(a));
    await shot('p298a-402-results.png');
    await call('POST', `/api/polls/${Q.id}/decide`, {option_id: Q.options[0].id});
    await nav(B + QP.replace(/^\//, ''));
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('.tpo-chosen')`).catch(() => false)); i++) await sleep(250);
    const c2 = await ev(`(() => ({wide: document.documentElement.scrollWidth <= innerWidth + 1, form: !!document.querySelector('.tpo-form')}))()`);
    check(c2 && c2.wide && !c2.form, '402: the closed poll shows only the result ' + JSON.stringify(c2));
    await shot('p298a-402-closed.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
