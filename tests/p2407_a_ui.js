// kalmido-suite: fresh
// 2.407.0 A (#3513): "agent is working" at a task. An agent marks a task over the API (POST /api/v1/tasks/<id>/working): an
// open window shows a pulsing dot with "Claude · HH:MM · line" in the list row, in the task detail and on the board card,
// without reloading the page (the delta, no whole state); a new line replaces the text; DELETE removes it again; a mark whose
// last update is older than its ttl fades in the client too. Own container.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, AT;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const agent = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + AT}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const until = async (fn, n = 140) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['agents', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,kanban'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0]?.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  AT = ag.token;
  await call('PATCH', `/api/admin/agents/${ag.id}`, {org_id: ORG});
  execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, 'INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,\'member\') ON CONFLICT DO NOTHING', JSON.stringify([ORG, ag.id])]);  // as p2407_a_api_test.py
  const W = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const K = (await call('POST', '/api/lists', {name: 'Board', org_id: ORG, view: 'kanban'})).id;
  for (const l of [W, K]) await call('PUT', `/api/lists/${l}/members`, {user_id: ag.id, role: 'edit'});
  const TL = (await call('POST', '/api/tasks', {title: 'Logo is blurry', list_id: W})).id;
  const TK = (await call('POST', '/api/tasks', {title: 'Columns for the board', list_id: K})).id;
  check(ORG && AT && W && K && TL && TK, 'setup');
  const w = await boot({user: 'alice', hash: 'l/' + W}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  await until(() => row(TL));
  await until(() => w.eval('!!S.lpA && !S.lpUnk && S.lpPend.size === 0'));  // the first poll (it loads the whole state once) is over
  w.__noReload = 1;
  const n0 = w.eval('S.lpN.state');

  // the list row: the dot appears live with name, time and line
  let r = await agent('POST', `/tasks/${TL}/working`, {text: 'Column added'});
  check(r.status === 201, `#3513: the agent marks the task (${r.status})`);
  const hm = w.eval(`fmtTimeLoc(fmtHM(new Date(${JSON.stringify(r.j.working?.at || '')})))`);
  let m = await until(() => row(TL)?.querySelector('.agw'));
  check(!!m, '#3513: the list row shows the mark without a reload');
  check(m && m.querySelector('.agwd') && m.querySelector('.agwt')?.textContent === `Claude · ${hm} · Column added`, `#3513: dot + "Claude · ${hm} · Column added": ${m?.textContent}`);
  check(m && m.getAttribute('title') === `Claude · ${hm} · Column added`, '#3513: the full text in the title');
  check(m && /Agent working/.test(m.querySelector('.sr')?.textContent || ''), '#3513: screen readers hear "Agent working"');
  check(row(TL)?.querySelector('.chk.work'), '#3513: the status circle shows the agent at work');
  check(w.__noReload === 1 && w.eval('S.lpN.state') === n0, `#3513: taken with the delta (no whole state, no reload) ${n0} -> ${w.eval('S.lpN.state')}`);

  // the detail: the same line, live; a new line replaces it
  w.eval(`openDetail(${TL})`);
  m = await until(() => d.querySelector('#detail .dagw .agw'));
  check(m && /Column added/.test(m.textContent), '#3513: the detail shows the mark under the title ' + (m?.textContent || ''));
  await agent('POST', `/tasks/${TL}/working`, {text: 'Cards moved'});
  check(await until(() => /Cards moved/.test(d.querySelector('#detail .dagw')?.textContent || '') && /Cards moved/.test(row(TL)?.querySelector('.agw')?.textContent || '')),
    '#3513: a new progress line replaces the text in the detail and the row');
  // the end: gone at once in both places
  r = await agent('DELETE', `/tasks/${TL}/working`);
  check(r.status === 200, `#3513: the agent ends it (${r.status})`);
  check(await until(() => !d.querySelector('#detail .dagw') && row(TL) && !row(TL).querySelector('.agw')), '#3513: after the end the mark disappears (row and detail)');
  check(row(TL) && !row(TL).querySelector('.chk.work'), '#3513: ... the status circle too');
  w.eval('closeDetail()');

  // the board card
  w.location.hash = 'l/' + K;
  await until(() => d.querySelector(`#view .kcards .trow[data-id="${TK}"]`));
  await agent('POST', `/tasks/${TK}/working`, {text: 'Lane drafted', name: 'Holston'});
  m = await until(() => d.querySelector(`#view .kcards .trow[data-id="${TK}"] .agw`));
  check(m && /^Holston · \d/.test(m.textContent.replace(/^Agent working: /, '')) && /Lane drafted/.test(m.textContent), '#3513: the board card shows the mark (the job name first) ' + (m?.textContent || ''));
  // fading in the client: a mark older than its ttl is not drawn (the server leaves it out on its next read anyway)
  w.eval(`(() => { const t = S.tasks.get(${TK}); t.working = {...t.working, at: new Date(Date.now() - 16 * 60000).toISOString()}; viewSafeRender(); })()`);
  check(await until(() => d.querySelector(`#view .kcards .trow[data-id="${TK}"]`) && !d.querySelector(`#view .kcards .trow[data-id="${TK}"] .agw`)), '#3513: an outdated mark fades in the client');
  const css = [...d.styleSheets].flatMap(s => { try { return [...s.cssRules].map(x => x.cssText); } catch { return []; } }).join('\n');
  check(/prefers-reduced-motion:\s*reduce[^}]*\.agwd/.test(css.replace(/\n/g, ' ')) || /\.agwd\s*\{[^}]*animation:\s*none/.test(css), '#3513: no pulse with reduced motion');
  check(w.__noReload === 1, '#3513: the page was never reloaded');
  console.log(`p2407_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: exception', e && e.stack); process.exit(1); });
