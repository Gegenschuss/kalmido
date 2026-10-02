// 2.0.5 UI tests (jsdom + the service worker in a Node vm), fresh DB:
// #313 Settings > "AI colleague" (German "KI-Kollege", icon bot): admins manage the agents there (moved from
// Administration, settingsModal('agents') lands there), the agents module switch mirrors Settings > Modules, the
// explanation + "which lists it sees" + share button; non-admins: switch, explanation and their agents' status only.
// #310 the trash marks what stays (shared lists of other owners), "Empty" says how many stayed (toast).
// #311 the service worker closes notifications by tag (dismiss push, piggybacked dismiss), the app closes its own
// notification when a task is opened and tells the server (POST /api/push/handled with X-Kalmido-Device).
const fs = require('fs'), path = require('path'), vm = require('vm');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const CK = {};
const call = async (who, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK[who]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

// ------------------------------------------------------------------ service worker: closing by tag
const SW = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
function swEnv(tags) {
  const L = {}, shown = [], closed = [];
  const notes = tags.map(tag => ({tag, close: () => closed.push(tag)}));
  const self = {location: {origin: 'https://kalmido.example'}, addEventListener: (t, f) => { L[t] = f; }, skipWaiting() {},
    registration: {showNotification: async (t, o) => { shown.push([t, o]); }, getNotifications: async () => notes, pushManager: {}},
    clients: {matchAll: async () => [], openWindow: async () => ({}), claim() {}}};
  const ctx = {self, caches: {open: async () => ({addAll: async () => {}, put() {}}), keys: async () => [], match: async () => null},
    fetch: async () => new Response('{}'), URL, Response, atob, Uint8Array, JSON, Promise, console, setTimeout};
  vm.createContext(ctx); vm.runInContext(SW, ctx);
  return {L, shown, closed};
}
const pushEv = d => ({data: {json: () => d, text: () => JSON.stringify(d)}, waitUntil(p) { this.p = p; }});
async function swTests() {
  check(/const CACHE = 'tasks-shell-v((5[789]|6[0-9])|7[0-9])'/.test(SW), 'service worker cache v57 (2.0.6: v58, 2.0.8: v59, 2.1.0: v60, 2.1.1: v61, 2.1.2: v62, 2.2.0: v63, 2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79)');
  let S = swEnv(['t-1', 't-2', 'digest']);
  let e = pushEv({type: 'dismiss', tags: ['t-1', 't-9']}); S.L.push(e); await e.p;
  check(JSON.stringify(S.closed) === '["t-1"]' && !S.shown.length, 'dismiss push: closes t-1 only, shows nothing');
  S = swEnv(['t-1', 't-2']);
  e = pushEv({title: 'Task Y', body: 'Bob commented', tag: 't-3', url: '/#t/3', dismiss: ['t-2']}); S.L.push(e); await e.p;
  check(JSON.stringify(S.closed) === '["t-2"]' && S.shown.length === 1 && S.shown[0][1].tag === 't-3', 'piggyback: closes t-2, then shows the new one');
  S = swEnv(['t-1']);
  e = pushEv({title: 'x', body: 'y', tag: 't-1'}); S.L.push(e); await e.p;
  check(!S.closed.length && S.shown.length === 1, 'normal push without dismiss: nothing closed');
  S = swEnv([]);
  e = pushEv({type: 'dismiss', tags: 'not-a-list'}); S.L.push(e); await e.p;
  check(!S.closed.length && !S.shown.length, 'malformed dismiss: ignored');
}

(async () => {
  await swTests();
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK.alice = await login('alice');
  const ids = {};
  for (const u of ['bob', 'carl']) ids[u] = (await call('alice', 'POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123'})).id;
  CK.bob = await login('bob'); CK.carl = await login('carl');
  for (const u of ['alice', 'bob', 'carl']) await call(u, 'PATCH', '/api/settings', {lang: 'en'});
  // carl's list, shared with alice + bob (edit), then carl becomes an agent (lists owned by an agent user)
  const DEV = (await call('carl', 'POST', '/api/lists', {name: 'Dev', kind: 'project'})).id;
  for (const u of [1, ids.bob]) await call('carl', 'PUT', `/api/lists/${DEV}/members`, {user_id: u, role: 'edit'});
  const t1 = (await call('bob', 'POST', '/api/tasks', {title: 'Old idea', list_id: DEV})).id;
  const t2 = (await call('alice', 'POST', '/api/tasks', {title: 'Dup', list_id: DEV})).id;
  const BL = (await call('bob', 'POST', '/api/lists', {name: 'Bobs'})).id;
  const t3 = (await call('bob', 'POST', '/api/tasks', {title: 'Bob own', list_id: BL})).id;
  for (const [u, t] of [['bob', t1], ['alice', t2], ['bob', t3]]) await call(u, 'DELETE', `/api/tasks/${t}`);
  check((await call('alice', 'PATCH', `/api/users/${ids.carl}`, {kind: 'agent'})).status < 300, 'setup: carl is an agent');
  for (const u of ['alice', 'bob']) await call(u, 'PATCH', '/api/settings', {features: 'kanban,collab,agents'});
  const ALST = (await call('alice', 'POST', '/api/lists', {name: 'Alice project', kind: 'project'})).id;

  // ================= #313 admin: AI colleague tab
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval('settingsModal()'); await sleep(400);
  let md = d.querySelector('.modal.smodal');
  const secs = [...md.querySelectorAll('.snav [data-sec]')].map(b => b.dataset.sec);
  check(JSON.stringify(secs) === JSON.stringify(['account', 'general', 'look', 'modules', 'notify', 'integr', 'ai', 'data', 'users', 'help']), 'admin tabs incl. ai: ' + secs);
  const tab = md.querySelector('.snav [data-sec="ai"]');
  check(/Agents/.test(tab.textContent) && tab.querySelector('svg, use, .ic, i') !== null, 'tab "Agents" with an icon (2.6.0, K09: was "AI colleague")');
  check(!md.querySelector('[data-pane="users"] #s-ags'), 'Administration no longer holds the agents block');
  md.remove();
  w.eval(`settingsModal('agents')`);
  let row;
  for (let i = 0; i < 40 && !row; i++) { await sleep(150); row = [...d.querySelectorAll('#s-ags [data-agid]')].find(r => /Carl/.test(r.textContent)); }
  md = d.querySelector('.modal.smodal');
  check(md.querySelector('.snav .on')?.dataset.sec === 'ai' && !md.querySelector('[data-pane="ai"]').classList.contains('hidden'), "settingsModal('agents') opens the AI colleague tab");
  check(row && !md.querySelector('#aisp-agents').hidden && md.querySelector('#aisp-agents [data-ag="new"]'), 'admin: agent list + "Add agent" in the sub-tab Agents (2.5.1)');
  const pane = md.querySelector('[data-pane="ai"]');
  check(/team member for an AI assistant/.test(pane.textContent) && pane.querySelector('a[href$="AGENTS.md"]'), 'explanation + link to AGENTS.md');
  check(/sees exactly the lists shared with it/.test(pane.textContent) && !pane.querySelector('[data-m="ai-share"]') && pane.querySelector('#s-ai-share'), 'hint: list access = sharing; 2.4.2 (#391): no "Share a list with an agent…" button, the per-agent share block instead');
  // 2.5.1 (#393): the module switch shows in AI colleague only while the module is off (Settings > Modules has it always)
  const modSw = md.querySelector('[data-pane="modules"] [data-feat="agents"]');
  check(!pane.querySelector('[data-feat="agents"]') && modSw && modSw.checked, 'agents on: the switch only in Modules');
  modSw.checked = false; modSw.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  check(!(await call('alice', 'GET', '/api/state')).settings.features.split(',').includes('agents'), 'saved: agents off');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.eval(`settingsModal('agents')`); await sleep(600);
  md = d.querySelector('.modal.smodal');
  // 2.6.0 (K09): the switch only lives in Modules; the Agents tab shows a hint with "Open Modules"
  const modSw2 = md.querySelector('[data-pane="modules"] [data-feat="agents"]');
  check(!md.querySelector('[data-pane="ai"] [data-feat="agents"]') && md.querySelector('[data-pane="ai"] .aimodoff [data-m="go-modules"]') && !modSw2.checked, 'agents off: a hint in Agents, the switch only in Modules');
  modSw2.checked = true; modSw2.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  check((await call('alice', 'GET', '/api/state')).settings.features.split(',').includes('agents'), 'switched on in Modules, saved');
  // 2.4.2 (#391): the "Share a list with an agent…" button is gone (the table below covers it)
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // palette: the tab is searchable
  const pal = w.eval(`JSON.stringify(palAll().filter(x => x.id === 's:ai').map(x => x.label))`);
  check(pal === '["Settings: Agents"]', 'command palette: Settings: Agents ' + pal);
  // German
  await call('alice', 'PATCH', '/api/settings', {lang: 'de'});
  w.close();
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(600);
  md = d.querySelector('.modal.smodal');
  check(/Agenten/.test(md.querySelector('.snav [data-sec="ai"]').textContent) && /Welche Listen er sieht/.test(md.textContent), 'German: Agenten');
  w.close();
  await call('alice', 'PATCH', '/api/settings', {lang: 'en'});

  // ================= #313 non-admin: switch + explanation + status, no management
  w = await boot({user: 'bob', mobile: true}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(600);
  md = d.querySelector('.modal.smodal');
  const bp = md.querySelector('[data-pane="ai"]');
  check(bp && !bp.classList.contains('hidden'), 'bob: Agents tab');
  check(!bp.querySelector('[data-feat="agents"]') && /team member for an AI assistant/.test(bp.textContent), 'bob: explanation, no switch while the module is on (2.5.1)');
  check(!bp.querySelector('#s-ags') && !bp.querySelector('[data-ag]'), 'bob: no management');
  const my = bp.querySelector('#s-myags [data-agid]');
  check(my && /Carl/.test(my.textContent) && /not connected/.test(my.textContent), 'bob: his agent with its status (2.6.0, K08: never in touch = not connected): ' + (my?.textContent || '').trim());
  check(!md.querySelector('.snav [data-sec="users"]'), 'bob: still no Administration');
  w.close();

  // ================= #310 trash: marks + toast
  w = await boot({user: 'bob', hash: 'trash'}); d = w.document; await sleep(600);
  const rows = () => [...d.querySelectorAll('#view .trow')];
  check(rows().length === 3, 'bob: three items in the trash: ' + rows().length);
  const kept = rows().filter(r => r.querySelector('.tkeep'));
  check(kept.length === 2 && kept.every(r => [t1, t2].includes(+r.dataset.id)), 'rows of the agent\'s list marked "stays"');
  check(/2 items stay when you empty the trash/.test(d.querySelector('#view .trkeep')?.textContent || ''), 'banner: 2 items stay');
  let asked = '';
  w.confirm = m => { asked = m; return true; };
  click(w, d.querySelector('[data-act="trash-empty"]')); await sleep(1500);
  check(/1 task is deleted for good/.test(asked), 'confirm counts only what is deleted: ' + asked);
  const toast = d.querySelector('#toast');
  check(toast && !toast.classList.contains('hidden') && /2 items stay: they are in lists of other owners/.test(toast.textContent), 'toast: 2 items stay');
  check(rows().length === 2 && !d.querySelector('[data-act="trash-empty"]'), 'only the kept ones remain, no "Empty" when nothing can be deleted');
  w.close();
  w = await boot({user: 'alice', hash: 'trash'}); d = w.document; await sleep(600);
  check(rows().length === 2 && !d.querySelector('#view .tkeep') && !d.querySelector('#view .trkeep'), 'admin: nothing marked');
  click(w, d.querySelector('[data-act="trash-empty"]')); await sleep(1500);
  check(!rows().length && /Trash is empty/.test(d.querySelector('#view').textContent), 'admin empties the shared trash');
  w.close();

  // ================= #311 opening a task: own notification closed, server told with the device header
  const T = (await call('alice', 'POST', '/api/tasks', {title: 'Notified', list_id: ALST})).id;
  const closed = [], sent = [];
  w = await boot({user: 'alice', hash: 'l/' + ALST, ls: {'tasks.wpUser': '1', 'tasks.wpEp': '"https://fcm.googleapis.com/fcm/send/me"'}, setup(win) {
    const reg = {getNotifications: async () => [{tag: 't-' + T, close: () => closed.push('t-' + T)}, {tag: 't-0', close: () => closed.push('t-0')}]};
    Object.defineProperty(win.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null, getRegistration: async () => reg}});
    const f = win.fetch; win.fetch = (u, o = {}) => { sent.push([String(u), o]); return f(u, o); };
  }}); d = w.document;
  w.eval('S.webpush.enabled = true; S.webpush.devices = 2');
  w.eval(`openDetail(${T})`); await sleep(500);
  check(JSON.stringify(closed) === `["t-${T}"]`, 'open: this device closes its notification of the task: ' + closed);
  const h = sent.find(([u]) => /\/api\/push\/handled$/.test(u));
  check(h && JSON.parse(h[1].body).tasks[0] === T && h[1].headers['X-Kalmido-Device'] === 'https://fcm.googleapis.com/fcm/send/me', 'open: POST /api/push/handled with the device header');
  const n0 = sent.filter(([u]) => /push\/handled/.test(u)).length;
  w.eval('closeDetail()'); w.eval(`openDetail(${T})`); await sleep(300);
  check(sent.filter(([u]) => /push\/handled/.test(u)).length === n0, 'reopened within a minute: not sent again');
  const other = sent.find(([u]) => /\/api\/state/.test(u));
  check(other && !(other[1].headers || {})['X-Kalmido-Device'], 'other requests carry no device header');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
