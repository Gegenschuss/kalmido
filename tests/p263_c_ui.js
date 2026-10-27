// 2.63.0 UI tests, part C (#1523), own container (start.sh), Firefox (desktop):
// - "Tracked time · name" of a project: an editor sees only their own entries and the note "Your time only"; the owner sees everyone
// - a project made from a template that was saved from a project page shows its notepad (new id) with the colour
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p263_c_ui', check, shots: 'P263C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const FEAT = 'comments,collab,time,progress';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments', 'time']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Harbour site', kind: 'project', time_tracking: true})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: bob.id, role: 'edit'});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Survey the quay', list_id: L})).id;
  await call(CA, 'POST', '/api/time/entries', {task_id: T, start: '2026-09-01T08:00:00Z', end: '2026-09-01T10:00:00Z'});
  await call(CB, 'POST', '/api/time/entries', {task_id: T, start: '2026-09-02T08:00:00Z', end: '2026-09-02T09:00:00Z'});
  // the project page: a notepad with a colour, saved as a template, a new project from it
  const pad = await call(CA, 'POST', `/api/lists/${L}/notepads`, {title: 'Gate codes', body: 'north gate'});
  await call(CA, 'PUT', `/api/lists/${L}/page-style`, {block: 'np' + pad.id, color: 'yellow'});
  const tp = await call(CA, 'POST', '/api/templates', {list_id: L, name: 'Site'});
  const L2 = (await call(CA, 'POST', `/api/templates/${tp.id}/apply`, {name: 'Harbour two'})).list_id;
  const pads2 = (await call(CA, 'GET', `/api/lists/${L2}/layout`)).pads || [];
  check(pads2.length === 1 && pads2[0].id !== pad.id, 'the new project has its own notepad ' + JSON.stringify(pads2));

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const until = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const ffLogin = async (user, pov) => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.pov', '${JSON.stringify(pov)}'); return 1; })()`);
      return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
    };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    const win = async () => {
      await nav(B + '#l/' + L);
      check(await until(`!!document.querySelector('#view .lhead .tsum[data-tsum]')`, 60), 'the header shows Tracked');
      await ev(`document.querySelector('#view .lhead .tsum').click()`);
      await until(`/ h/.test(document.querySelector('.tzmodal #tz-body')?.textContent || '')`, 60);
      return ev(`(document.querySelector('.tzmodal #tz-body')?.textContent || '').replace(/\\s+/g, ' ')`);
    };
    // the editor
    check(await ffLogin('bob', []) === 200, 'bob login');
    let txt = await win();
    check(/Your time only/.test(txt) && /^ ?1 h/.test(txt), 'editor: own hour and "Your time only" ' + txt.slice(0, 200));
    check(!/Alice/.test(txt), 'editor: no Alice in the window');
    await shot('p263c-editor-window.png');
    // the owner
    check(await ffLogin('alice', []) === 200, 'alice login');
    txt = await win();
    check(!/Your time only/.test(txt) && /^ ?3 h/.test(txt) && /Alice/.test(txt) && /Bob/.test(txt), 'owner: everyone, no note ' + txt.slice(0, 200));
    // the project page of the project made from the template
    check(await ffLogin('alice', [L2]) === 200, 'alice login (project page)');
    await nav(B + '#l/' + L2);
    const k = 'np' + (pads2[0] || {}).id;
    check(await until(`!!document.querySelector('.lyb[data-lyk="${k}"]')`, 60), 'project page shows the copied notepad');
    check(await ev(`/Gate codes/.test(document.querySelector('.lyb[data-lyk="${k}"]')?.textContent || '')`), 'notepad title on the page');
    await shot('p263c-template-page.png');
  });
  console.log(`p263_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
