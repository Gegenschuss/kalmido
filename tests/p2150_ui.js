// 2.15.0 UI tests (#479 permissions of tokens and agents, approvals; #632 the inbox name), own container (start.sh).
// jsdom: Settings > Account > API tokens: the new token dialog (a grid of permissions, Read always on, the explanations
// behind (i) on the legend, the address field), the token row's summary + lock button -> the permissions dialog (save,
// an invalid address shows its error); Settings > Agents > Set up: the admin's permission limit (two grids, saved at
// once), a personal agent's lock button (its owner changes its permissions, the approval note) and the new token dialog with
// an expiry; the admin's agent dialog with the default permissions; an agent's request waiting for approval shows Approve /
// Reject in the Agents view and Approve runs it; the inbox in the viewer's language (#632); German labels.
// Firefox: 390 touch (real taps, pointerType touch) and 1440 mouse, light + dark: the token dialog, the permissions dialog
// and the limit grids fit (no horizontal overflow, 44 px rows), a tap toggles a permission, the (i) tooltip lists one
// permission per line inside the viewport. Screenshots with P2150_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2150_ui', check, shots: 'P2150_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _st: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:89|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v89');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const DORA = (await call('POST', '/api/users', {username: 'dora', display_name: 'Dora', password: 'password123', lang: 'de'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CB);
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done'}, await login('dora'));
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 2});
  const L = (await call('POST', '/api/lists', {name: 'Team'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});

  // ================= Settings > Account > API tokens: new token
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('account')`); await sleep(400);
  const dev = d.querySelector('.smodal details.sdev'); if (dev) dev.open = true;
  await until(() => d.querySelector('#s-toks .mhint, #s-toks .tokrow'));
  click(w, d.querySelector('[data-tok="new"]')); await sleep(300);
  let md = lastModal(d);
  const boxes = [...md.querySelectorAll('.scopes [data-scope]')];
  check(boxes.length === 14 && boxes.map(b => b.dataset.scope).includes('admin-read'), 'new token: 14 permissions for an admin (admin read included; 2.21.0: calendar, contacts; 2.22.0: private) ' + boxes.map(b => b.dataset.scope).join(','));
  const rd = md.querySelector('[data-scope="read"]');
  check(rd.checked && rd.disabled && boxes.filter(b => b.checked).length === 1, 'new token: only Read, always on');
  check(md.querySelector('.scopes legend .ib[data-ii]') && /Tasks: Create, change/.test(md.querySelector('.scopes .shint.pl')?.textContent || ''), 'the explanations behind (i) on the legend');
  check(!md.querySelector('.scopes .shint:not(.iisrc)'), 'no inline helper text under the permissions');
  check(md.querySelector('#tk-ips') && md.querySelector('label[for="tk-ips"] .ib'), 'address field with (i)');
  md.querySelector('#tk-name').value = 'Home Assistant';
  md.querySelector('[data-scope="tasks:write"]').checked = true;
  md.querySelector('#tk-ips').value = '192.168.0.0/16';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(async () => (await call('GET', '/api/me/tokens')).tokens.length || !md.querySelector('#tk-err').hidden);
  if (!md.querySelector('#tk-err').hidden) console.log('token error:', md.querySelector('#tk-err').textContent);
  await sleep(300);
  let toks = (await call('GET', '/api/me/tokens')).tokens;
  check(toks[0].name === 'Home Assistant' && JSON.stringify(toks[0].scopes) === '["read","tasks:write"]' && toks[0].allowed_ips[0] === '192.168.0.0/16', 'created with the ticked permissions + address ' + JSON.stringify(toks[0]));
  [...d.querySelectorAll('.modal:not(.smodal)')].forEach(m => m.remove());
  await w.eval(`tokDraw(document.querySelector('.smodal'))`); await sleep(300);
  const row = d.querySelector(`#s-toks [data-tokid="${toks[0].id}"]`);
  check(row && /Tasks/.test(row.textContent) && /only from 192\.168\.0\.0\/16/.test(row.textContent), 'token row: the permissions in words + address ' + (row?.textContent || '').trim().slice(0, 140));
  check(row.querySelector('[data-tok="edit"]')?.getAttribute('aria-label') === 'Permissions of Home Assistant', 'token row: the lock button');
  click(w, row.querySelector('[data-tok="edit"]')); await sleep(300);
  md = lastModal(d);
  check(md.querySelector('[data-scope="tasks:write"]').checked && !md.querySelector('[data-scope="comments"]').checked && md.querySelector('#pm-ips').value === '192.168.0.0/16', 'permissions dialog: the current state');
  md.querySelector('#pm-ips').value = 'not an address';
  click(w, md.querySelector('[data-m="ok"]')); await until(() => !md.querySelector('#pm-err').hidden);
  check(!md.querySelector('#pm-err').hidden && /Invalid address/.test(md.querySelector('#pm-err').textContent) && md.isConnected, 'an invalid address: the error in the dialog, it stays open');
  md.querySelector('#pm-ips').value = '';
  md.querySelector('[data-scope="comments"]').checked = true;
  click(w, md.querySelector('[data-m="ok"]')); await until(() => !md.isConnected);
  toks = (await call('GET', '/api/me/tokens')).tokens;
  check(JSON.stringify(toks[0].effective_scopes) === '["read","tasks:write","comments"]' && !toks[0].allowed_ips.length, 'saved: comments added, address cleared');
  // a legacy token shows "all permissions"
  await call('POST', '/api/me/tokens', {name: 'Old script', scopes: ['read', 'write']});
  await w.eval(`tokDraw(document.querySelector('.smodal'))`); await sleep(300);
  check(/all permissions/.test([...d.querySelectorAll('#s-toks .tokrow')].find(r => /Old script/.test(r.textContent))?.textContent || ''), 'an old read + write token: "all permissions"');
  w.close();

  // ================= Settings > Agents > Set up: the admin's limit, the admin's agent dialog
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  await until(() => d.querySelector('#s-sclim .sclim'));
  const lim = [...d.querySelectorAll('#s-sclim .sclim')];
  check(lim.length === 2 && !lim[0].querySelector('[data-scope="account"]') && lim[1].querySelector('[data-scope="account"]'), 'limit: agents (no account) + personal tokens');
  check(d.querySelector('#s-sclim-h .ib'), 'limit: the explanation behind (i)');
  const ex = d.querySelector('[data-sclim="agents"][data-scope="export"]');
  check(ex.checked, 'limit: everything allowed by default');
  ex.checked = false; ex.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => !(await call('GET', '/api/admin/agent-policy')).scope_limit.agents.includes('export')), 'limit: unticking saves at once');
  await until(() => w.eval(`(S.agOffer || []).some(o => o.scope === 'export' && !o.allowed)`));
  // admin: add an agent -> default permissions; export greyed out (over the limit)
  w.eval(`agModal(null, () => {})`); await sleep(300);
  md = lastModal(d);
  const on = [...md.querySelectorAll('.scopes [data-scope]:checked')].map(b => b.dataset.scope);
  check(JSON.stringify(on) === '["read","tasks:write","comments"]', 'new agent: Read, Tasks, Comments ' + on);
  check(md.querySelector('[data-scope="export"]').disabled && md.querySelector('[data-scope="export"]').closest('.chkl').classList.contains('off'), 'over the limit: greyed out');
  check(!md.querySelector('[data-scope="account"]') && !md.querySelector('[data-scope="admin-read"]'), 'agents: no account / admin read');
  check(/always wait for a person’s approval/.test(md.textContent), 'the approval note');
  md.querySelector('#ag-user').value = 'claude'; md.querySelector('#ag-name').value = 'Claude';
  md.querySelector('[data-scope="structure"]').checked = true;
  click(w, md.querySelector('[data-m="ok"]'));
  await until(async () => (await call('GET', '/api/admin/agents')).agents.length);
  await sleep(300);
  const ag = (await call('GET', '/api/admin/agents')).agents.find(a => a.username === 'claude');
  check(ag && JSON.stringify(ag.effective_scopes) === '["read","tasks:write","comments","structure"]', 'agent created with them ' + JSON.stringify(ag?.effective_scopes));
  [...d.querySelectorAll('.modal:not(.smodal)')].forEach(m => m.remove());
  await call('PUT', '/api/admin/agent-policy', {scope_limit: {agents: ['read', 'tasks:write', 'comments', 'structure', 'delete', 'attachments:read', 'attachments:write', 'time', 'export']}});
  w.close();

  // ================= bob: his personal agent's permissions + a new token with an expiry
  const PA = (await call('POST', '/api/my/agents', {username: 'bobbot', display_name: 'Bobbot'}, CB)).id;
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  await until(() => d.querySelector(`#s-myown [data-myag="${PA}"]`));
  const prow = d.querySelector(`#s-myown [data-myag="${PA}"]`);
  check(/Tasks, Comments/.test(prow.textContent), 'personal agent row: its permissions in words ' + prow.textContent.trim().slice(0, 120));
  check(!d.querySelector('#s-sclim'), 'bob: no limit section');
  click(w, prow.querySelector('[data-myag-act="perm"]')); await sleep(300);
  md = lastModal(d);
  check(/Permissions of Bobbot/.test(md.querySelector('h3').textContent) && /wait for your approval/.test(md.textContent), 'owner: the permissions dialog with the approval note');
  md.querySelector('[data-scope="time"]').checked = true;
  click(w, md.querySelector('[data-m="ok"]')); await until(() => !md.isConnected);
  check((await call('GET', '/api/my/agents', null, CB)).agents[0].effective_scopes.includes('time'), 'owner saved time tracking');
  click(w, d.querySelector(`#s-myown [data-myag="${PA}"] [data-myag-act="token"]`)); await sleep(300);
  md = lastModal(d);
  check(md.querySelector('#agt-exp')?.value === '' && /stops working/.test(md.textContent), 'new agent token: expiry (never by default) + the warning');
  md.querySelector('#agt-exp').value = '30';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(async () => (await call('GET', '/api/my/agents', null, CB)).agents[0].tokens[0]?.expires_at);
  const pa = (await call('GET', '/api/my/agents', null, CB)).agents[0];
  check(pa.tokens.length === 1 && pa.tokens[0].expires_at && pa.tokens[0].effective_scopes.includes('time'), 'the new token expires and keeps the permissions');
  w.close();

  // ================= an agent's request waits for approval; Approve in the Agents view runs it
  const TOK = (await call('POST', `/api/admin/agents/${ag.id}/token`, {})).token;
  await call('PATCH', `/api/admin/agents/${ag.id}`, {scopes: ['read', 'tasks:write', 'comments', 'structure', 'delete']});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const AL = (await tcall('POST', '/lists', TOK, {name: 'Scratch'})).id;
  await tcall('PATCH', `/lists/${AL}`, TOK, {archived: true});
  const pend = await tcall('DELETE', `/lists/${AL}`, TOK);
  check(pend._st === 202 && pend.job?.state === 'waiting', 'agent deletes a list: waits (202)');
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  const ap = await until(() => d.querySelector(`[data-act="job-do"][data-a="approve"][data-jid="${pend.job.id}"]`), 60);
  check(ap && d.querySelector(`[data-act="job-do"][data-a="reject"][data-jid="${pend.job.id}"]`), 'Agents view: Approve / Reject on the waiting request');
  check(/Delete the list “Scratch” for good/.test(d.querySelector('#view').textContent), 'the request in words');
  if (ap) click(w, ap);
  check(await until(async () => (await call('GET', '/api/agents/jobs')).jobs.find(j => j.id === pend.job.id)?.state === 'done', 60), 'Approve runs it: job done');
  check(!(await call('GET', '/api/state')).lists.some(l => l.id === AL) && (await tcall('GET', `/lists/${AL}`, TOK))._st === 404, 'the list is gone');
  w.close();

  // ================= #632 + German
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  check([...d.querySelectorAll('#side .srow .n')].some(n => n.textContent === 'Inbox'), "#632: bob's inbox (stored 'Inbox') shows 'Inbox'");
  w.close();
  w = await boot({user: 'dora', hash: 'today'}); d = w.document;
  check([...d.querySelectorAll('#side .srow .n')].some(n => n.textContent === 'Eingang'), "#632: dora (German) sees 'Eingang'");
  w.eval(`settingsModal('account')`); await sleep(400);
  const dv = d.querySelector('.smodal details.sdev'); if (dv) dv.open = true;
  await until(() => d.querySelector('#s-toks .mhint, #s-toks .tokrow'));
  click(w, d.querySelector('[data-tok="new"]')); await sleep(300);
  md = lastModal(d);
  check(/Berechtigungen/.test(md.querySelector('.scopes legend').textContent) && md.querySelector('[data-scope="tasks:write"]').closest('label').textContent.trim() === 'Aufgaben'
        && md.querySelector('label[for="tk-ips"]').textContent.trim().startsWith('Nur von'), 'German: Berechtigungen, Aufgaben, Nur von');
  check(!md.querySelector('[data-scope="admin-read"]'), 'not an admin: no admin read');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'}, CB);
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  check([...d.querySelectorAll('#side .srow .n')].some(n => n.textContent === 'Eingang'), "#632: bob in German: his 'Inbox' shows as 'Eingang'");
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'}, CB);

  // ================= Firefox: phone (touch) + desktop (mouse)
  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const FIT = `(() => { const m = [...document.querySelectorAll('.modal')].pop(), b = m.querySelector('.mbox') || m.firstElementChild || m, r = b.getBoundingClientRect();
    const rows = [...m.querySelectorAll('.scgrid .chkl')].map(x => x.getBoundingClientRect());
    return {over: document.documentElement.scrollWidth - innerWidth, left: Math.round(r.left), right: Math.round(innerWidth - r.right), n: rows.length,
      minH: Math.round(Math.min(...rows.map(x => x.height))), minW: Math.round(Math.min(...rows.map(x => x.width))), out: rows.filter(x => x.right > innerWidth + 1 || x.left < -1).length,
      save: (() => { const s = m.querySelector('[data-m="ok"]').getBoundingClientRect(); return s.height >= 40 && s.bottom <= innerHeight + 2 || !!m.querySelector('.foot'); })()}; })()`;
  const tap = async ({cmd, ctx}, x, y) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const center = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`;
  for (const [vw, vh, touch, th] of [[390, 844, true, 'dark'], [1440, 900, false, 'light']]) await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o, tag = String(vw);
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + '#today'); await ready(ev);
    await ev(`(() => { settingsModal('account'); return 1; })()`); await sleep(600);
    await ev(`(() => { const x = document.querySelector('.smodal details.sdev'); if (x) x.open = true; return 1; })()`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('#s-toks .tokrow')`)); i++) await sleep(300);
    // the permissions dialog of a token
    const p = await ev(center('#s-toks .tokrow [data-tok="edit"]'));
    if (touch) await tap(o, p.x, p.y); else await ev(`(() => { document.querySelector('#s-toks .tokrow [data-tok="edit"]').click(); return 1; })()`);
    await sleep(600);
    const f = await ev(FIT);
    check(f.n >= 10 && f.over <= 1 && f.out === 0 && f.left >= 0 && f.right >= 0, `${tag}: the permissions dialog fits ` + JSON.stringify(f));
    check(f.minH >= 44, `${tag}: permission rows at least 44 px high (${f.minH})`);
    await shot(`p2150-${tag}-perm.png`);
    // a tap / click toggles a permission
    const before = await ev(`document.querySelector('.modal:last-of-type [data-scope="export"]')?.checked ?? [...document.querySelectorAll('.modal')].pop().querySelector('[data-scope="export"]').checked`);
    const q = await ev(center('.modal [data-scope="export"]'));
    const q2 = await ev(`(() => { const m = [...document.querySelectorAll('.modal')].pop(), l = m.querySelector('[data-scope="export"]').closest('label'), r = l.getBoundingClientRect(); return {x: r.left + r.width * .7, y: r.top + r.height / 2}; })()`);
    if (touch) await tap(o, q2.x, q2.y); else await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(q2.x), y: Math.round(q2.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
    await sleep(300);
    const after = await ev(`[...document.querySelectorAll('.modal')].pop().querySelector('[data-scope="export"]').checked`);
    check(q && after === !before, `${tag}: ${touch ? 'a tap' : 'a click'} on the label toggles the permission`);
    // the (i) of the legend: one permission per line, inside the viewport
    const ib = await ev(`(() => { const b = [...document.querySelectorAll('.modal')].pop().querySelector('.scopes legend .ib'); b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(); const a = parseFloat(getComputedStyle(b, '::after').top) || 0; return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width - 2 * a, h: r.height - 2 * a}; })()`);
    if (touch) await tap(o, ib.x, ib.y); else await ev(`(() => { [...document.querySelectorAll('.modal')].pop().querySelector('.scopes legend .ib').click(); return 1; })()`);
    await sleep(400);
    const tip = await ev(`(() => { const t = document.querySelector('#iitip'); if (!t || t.classList.contains('hidden')) return null; const r = t.getBoundingClientRect(); return {ws: getComputedStyle(t).whiteSpace, l: r.left, r: innerWidth - r.right, top: r.top, b: innerHeight - r.bottom, lines: Math.round(r.height / parseFloat(getComputedStyle(t).lineHeight))}; })()`);
    check(tip && tip.ws === 'pre-line' && tip.l >= 0 && tip.r >= 0 && tip.lines >= 9, `${tag}: (i) shows one permission per line inside the viewport ` + JSON.stringify(tip));
    if (touch) check(ib.w >= 43 && ib.h >= 43, `${tag}: (i) touch target (with its invisible margin) ${Math.round(ib.w)} x ${Math.round(ib.h)}`);
    await shot(`p2150-${tag}-info.png`);
    await ev(`(() => { iiHide(true); [...document.querySelectorAll('.modal')].pop().querySelector('[data-m="close"]').click(); return 1; })()`); await sleep(300);
    // the new token dialog
    await ev(`(() => { document.querySelector('[data-tok="new"]').click(); return 1; })()`); await sleep(600);
    const g = await ev(FIT);
    check(g.n >= 10 && g.over <= 1 && g.out === 0 && g.minH >= 44, `${tag}: the new token dialog fits ` + JSON.stringify(g));
    await shot(`p2150-${tag}-newtoken.png`);
    await ev(`(() => { [...document.querySelectorAll('.modal')].pop().querySelector('[data-m="close"]').click(); document.querySelector('.smodal [data-m="close"], .smodal .mclose')?.click(); return 1; })()`); await sleep(300);
    // the admin's limit grids
    await nav(B + '#today'); await ready(ev);
    await ev(`(() => { settingsModal('ai'); return 1; })()`); await sleep(600);
    await ev(`(() => { aiSubShow(document.querySelector('.smodal'), 'setup', false); return 1; })()`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('#s-sclim .sclim')`)); i++) await sleep(300);
    const lm = await ev(`(() => { const rows = [...document.querySelectorAll('#s-sclim .chkl')].map(x => x.getBoundingClientRect()); return {n: rows.length, over: document.documentElement.scrollWidth - innerWidth, out: rows.filter(x => x.right > innerWidth + 1).length, minH: Math.round(Math.min(...rows.map(x => x.height)))}; })()`);
    check(lm.n === 25 && lm.over <= 1 && lm.out === 0 && lm.minH >= 44, `${tag}: the limit grids fit ` + JSON.stringify(lm));
    await ev(`(() => { document.querySelector('#s-sclim').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(200);
    await shot(`p2150-${tag}-limit.png`);
  }, touch);

  console.log(`p2150_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
