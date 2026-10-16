// 2.56.0 part C UI test, own container (start.sh), Firefox (the real layout).
// #1797: the sidebar's share symbols sit in two fixed columns at the right edge (agent | person) on every row: lists with
//        agent + person, only a person, only an agent, a list inside a folder, a list with a count, the folder rows themselves.
// Screenshots with P256C_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p256_c_ui', check, shots: 'P256C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const FEAT = 'cal,collab,agents,comments,progress';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: 'claude', display_name: 'Claude'})).id;
  const mk = async (name, folder) => { const id = (await call('POST', '/api/lists', {name})).id; if (folder) await call('PATCH', `/api/lists/${id}`, {folder}); return id; };
  const L = {both: await mk('Both'), person: await mk('Person only'), agent: await mk('Agent only'), plain: await mk('Plain'),
    kid: await mk('Kid list', 'Team'), kidPlain: await mk('Kid plain', 'Team'), count: await mk('Counted')};
  await call('PATCH', '/api/settings', {folders: JSON.stringify(['Team'])});
  for (const [id, u] of [[L.both, BOB], [L.both, AG], [L.person, BOB], [L.agent, AG], [L.kid, BOB], [L.count, BOB], [L.count, AG]]) await call('PUT', `/api/lists/${id}/members`, {user_id: u, role: 'edit'});
  for (let i = 0; i < 12; i++) await call('POST', '/api/tasks', {title: 'Task ' + i, list_id: L.count});
  await call('PUT', '/api/folders/people', {folder: 'Team', user_id: BOB, role: 'edit'});

  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  // right edges / left edges of the two columns of every row that has them, per row kind
  const COLS = `(() => { const R = el => el.getBoundingClientRect(), out = {};
    const rows = [...document.querySelectorAll('#side .srow[data-list], #side .fhead')];
    for (const r of rows) { const sl = r.querySelector('.sbc-sl'); if (!sl) continue;
      const k = r.dataset.list ? 'l' + r.dataset.list : 'f' + r.dataset.folder, pe = sl.querySelector('.sbc-pe'), ag = sl.querySelector('.sbc-ag');
      out[k] = {peR: R(pe).right, agR: R(ag).right, pe: !!pe.querySelector('svg'), ag: !!ag.querySelector('svg'), name: R(r.querySelector('.n')).right, vis: getComputedStyle(sl).visibility, w: R(sl).width}; }
    return out; })()`;
  const run = async (o, w, theme, touch) => {
    const {cmd, ev, shot} = o, tag = `${w} ${theme}`;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: w, height: 900}});
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await o.nav(B + '#inbox'); await ready(ev, '#side .srow[data-list]');
    if (touch || w < 900) { await ev(`(() => { document.querySelector('[data-act="side"]')?.click(); return 1; })()`); await sleep(600); }
    const c = await ev(COLS), k = Object.keys(c), j = JSON.stringify(c);
    check(k.length >= 7, `${tag}: #1797: every row has the two columns (also the unshared ones) ` + k.length);
    const pe = k.map(x => c[x].peR), ag = k.map(x => c[x].agR);
    check(Math.max(...pe) - Math.min(...pe) <= 1, `${tag}: #1797: the person column is at the same place on every row ` + j);
    check(Math.max(...ag) - Math.min(...ag) <= 1, `${tag}: #1797: the agent column is at the same place on every row ` + j);
    check(c['l' + L.both].pe && c['l' + L.both].ag && c['l' + L.person].pe && !c['l' + L.person].ag && !c['l' + L.agent].pe && c['l' + L.agent].ag, `${tag}: #1797: symbols in their own columns ` + j);
    check(!c['l' + L.plain].pe && !c['l' + L.plain].ag && c['l' + L.plain].vis === 'hidden', `${tag}: #1797: an unshared list keeps empty columns ` + j);
    check(c['fTeam'] && c['fTeam'].pe && Math.abs(c['fTeam'].peR - c['l' + L.both].peR) <= 1, `${tag}: #1797: the folder row in the same column ` + j);
    check(k.every(x => c[x].name <= c[x].agR - c[x].w / 2), `${tag}: #1797: the names end left of the symbols ` + j);
    await shot(`p256c-${w}-${theme}.png`);
  };
  await firefox(async o => { await run(o, 1440, 'light', false); await run(o, 1440, 'dark', false); }, false);
  await firefox(async o => { await run(o, 390, 'light', true); await run(o, 390, 'dark', true); await run(o, 344, 'light', true); await run(o, 680, 'dark', true); }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
