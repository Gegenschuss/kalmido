// kalmido-suite:
// 2.363.3 B UI test (#3134), own container (start.sh), Firefox:
// - "Duplicate" in the task menu: the copy comes from the server with its assignee, subtask and file, the toast offers Undo
// - the dialog "Duplicate project" says what comes along
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2363_3_b_ui', check, shots: 'P23633B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Harbour site'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Survey the quay', list_id: L, assignee_id: 1})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Measure', parent_id: T});
  const fd = new FormData(); fd.append('file', new Blob(['plan\n'], {type: 'text/plain'}), 'plan.txt');
  await fetch(B + `api/tasks/${T}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd});

  await firefox(async o => {
    const {ev, nav, shot} = o;
    const until = (expr, n) => require('./boot').until(() => ev(expr).catch(() => null), {timeout: n ? n * 250 : 15000, step: 250});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + `#l/${L}`);
    check(await until(`!!document.querySelector('#view .trow[data-id="${T}"]')`), 'the list shows the task');
    await ev(`(() => { taskDuplicate(S.tasks.get(${T}), () => { window.__plain = 1; }); return 1; })()`);
    check(await until(`[...S.tasks.values()].filter(t => t.title === 'Survey the quay').length === 2`), 'a copy in the list');
    check(await ev(`!window.__plain`), 'online: not the device copy');
    check(await until(`/Created/.test(document.querySelector('#toast')?.textContent || '')`), 'the toast with Undo');
    const c = (await call(CA, 'GET', '/api/state')).tasks.filter(t => t.title === 'Survey the quay' && t.id !== T)[0];
    check(c && c.assignee_id === 1, 'the copy: the assignee');
    check((await call(CA, 'GET', `/api/tasks/${c.id}`)).attachments?.length === 1, 'the copy: the file');
    await ev(`(() => { listDuplicate(${L}); return 1; })()`);
    check(await until(`/Everything except comments and times comes along/.test(document.querySelector('.modal.ldmodal')?.textContent || '')`), 'the dialog says what comes along');
    await shot('p2363-3-b-dup.png');
  });
  console.log(`p2363_3_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
