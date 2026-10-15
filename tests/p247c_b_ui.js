// 2.47c UI tests of part B (#1721, own container, start.sh). jsdom:
// - the assignee avatar in a task row carries the account colour (class acol + --acol): a fill without a photo, a ring with one
// - "me" keeps the accent mark (the colour rules skip .me)
// - "Show colours for people" off: only agents stay coloured (the robot badge stays)
// - the assign menu shows the person's colour, the profile offers the palette and saves the own colour
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Example', password: 'password123'})).id;
  const CAR = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol Example', password: 'password123'})).id;
  const AG = (await call('POST', '/api/admin/agents', {username: 'helperbot', display_name: 'Helper bot'})).id;
  const CKB = await login('bob');
  await call('PUT', '/api/me/avatar', {preset: 'coffee'}, CKB);  // bob has a picture, carol and the agent do not
  const L = (await call('POST', '/api/lists', {name: 'Team list'})).id;
  for (const u of [BOB, CAR, AG]) await call('PUT', `/api/lists/${L}/members`, {user_id: u, role: 'edit'});
  const T = {};
  for (const [k, uid] of [['bob', BOB], ['carol', CAR], ['agent', AG], ['me', 1]]) {
    T[k] = (await call('POST', '/api/tasks', {title: 'Task ' + k, list_id: L})).id;
    await call('PATCH', `/api/tasks/${T[k]}`, {assignee_id: uid});
  }
  const st = await call('GET', '/api/state');
  check([BOB, CAR, AG, 1].every(u => /^#[0-9a-f]{6}$/.test((st.colors || {})[u] || '')), 'setup: every account of the list has a colour ' + JSON.stringify(st.colors));
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T.me}"]`));
  const who = k => d.querySelector(`#view .trow[data-id="${T[k]}"] .who`);

  // ================= colour in the task row
  const wc = who('carol');
  check(wc && wc.classList.contains('acol') && !wc.classList.contains('pic') && wc.style.getPropertyValue('--acol') === st.colors[CAR],
    'no photo: the initials on the account colour (class acol, --acol = carol\'s colour)');
  const wb = who('bob');
  check(wb && wb.classList.contains('acol') && wb.classList.contains('pic') && wb.style.getPropertyValue('--acol') === st.colors[BOB],
    'with a photo: the same colour as a ring (acol + pic)');
  const wa = who('agent');
  check(wa && wa.classList.contains('acol') && wa.classList.contains('agent') && wa.querySelector('.abot-b'), 'the agent: its colour + the robot badge');
  const wm = who('me');
  check(wm && wm.classList.contains('me'), '"me" keeps the accent class');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/\.acol:not\(\.pic\):not\(\.me\)\{background:var\(--acol\)/.test(css) && /\.acol\.pic:not\(\.me\)\{box-shadow:0 0 0 1\.5px var\(--acol\)/.test(css),
    'CSS: fill without a photo, thin ring with one, never on "me" (the accent goes first)');
  check(w.eval(`AC_COLORS.every(c => { const x = ac_darkInk(c); const l = [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16) / 255).map(v => v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4); const L = .2126 * l[0] + .7152 * l[1] + .0722 * l[2]; return (x ? (L + .05) / (.0098 + .05) : 1.05 / (L + .05)) >= 4.5; })`),
    'every palette colour: initials with a contrast of at least 4.5');
  check(/Carol/.test(wc.closest('[title]')?.getAttribute('title') || ''), 'the name stays in the tooltip');

  // ================= "Show colours for people" off: only agents
  w.eval(`S.settings.person_colors = '0'; render()`);
  await sleep(200);
  check(!who('carol').classList.contains('acol') && !who('bob').classList.contains('acol'), 'off: people without colour');
  check(who('agent').classList.contains('acol') && who('agent').querySelector('.abot-b'), 'off: the agent keeps its colour and the robot');
  w.eval(`S.settings.person_colors = '1'; render()`);
  await sleep(200);
  check(who('carol').classList.contains('acol'), 'on again: people coloured');

  // ================= assign menu: the colour as a swatch
  w.eval(`assignMenu(document.querySelector('#view .trow[data-id="${T.carol}"] .whob'), ${T.carol})`);
  await sleep(150);
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
  const it = items.find(b => /Carol/.test(b.textContent) && !b.classList.contains('mshow'));
  check(it && it.querySelector('.mswc'), 'assign menu: carol\'s entry shows her colour ' + (it ? it.outerHTML : items.map(b => b.textContent).join('|')).slice(0, 300));
  w.eval(`closePop()`);

  // ================= profile: the palette, saving the own colour
  check(w.eval(`ac_pickHtml('${st.colors[1]}', 'me')`).split('data-accol').length - 1 === 12, 'the profile offers the 12 colours');
  const box = d.createElement('div'); box.className = 'pfcol'; box.innerHTML = w.eval(`ac_pickHtml('${st.colors[1]}', 'me')`); d.body.appendChild(box);
  const pick = w.eval('AC_COLORS[7]');
  box.querySelector(`[data-accol="${pick}"]`).click();
  check(await until(async () => (await call('GET', '/api/state')).colors[1] === pick), 'a click on a colour saves the own colour');
  check(box.querySelector(`[data-accol="${pick}"]`).getAttribute('aria-pressed') === 'true', 'the chosen colour is marked');
  check(await until(() => w.eval(`S.colors[1]`) === pick), 'the app uses the new colour at once');

  console.log(`p247c_b_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
