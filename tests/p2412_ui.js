// 2.41.2 UI tests (#1501, the UI answers at once), own container (start.sh). jsdom:
// - a list's colour / name from the sidebar menu shows before any GET /api/state answer (the state is held back 4 s)
// - a server error puts the old colour back; a state fetched while the write runs does not flicker it back
// - a second window of the same user gets it with the live update; Undo puts it back (locally and on the server)
// - sections (rename / order), list tags (colour / rename) and the list view switch locally as well
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
// the window's requests: GET /api/state held back by S_DELAY ms (counted), a PATCH matching w.__fail answers 500 after a moment
function shim(w) {
  const of = w.fetch;
  w.__st = 0; w.__sDelay = 4000; w.__fail = null; w.__pDelay = 0;
  w.fetch = async (u, o = {}) => {
    const url = String(u), m = (o.method || 'GET').toUpperCase();
    if (m === 'GET' && /\/api\/state/.test(url)) { w.__st++; w.__stk = (new Error().stack || '').split('\n').slice(2, 6).join(' < '); await sleep(w.__sDelay); }
    if (m !== 'GET' && w.__pDelay) await sleep(w.__pDelay);
    if (m !== 'GET' && w.__fail && w.__fail.test(url)) return new Response(JSON.stringify({error: 'Test error'}), {status: 500, headers: {'Content-Type': 'application/json'}});
    return of(u, o);
  };
}
const lc = (w, id) => w.eval(`listById(${id})?.color || ''`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  check(L > 0, 'list created');
  const C1 = '#6d8cff', C2 = '#f87171';

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const w2 = await boot({user: 'alice', hash: 'today'});
  shim(w);
  // ================= colour from the sidebar menu: visible before /api/state answers
  const st0 = w.__st;
  w.eval(`licColor(${L}, '${C1}')`);
  await sleep(250);
  check(lc(w, L) === C1, '#1501: the colour is in the local state at once: ' + lc(w, L));
  check(d.querySelector('#side').innerHTML.includes(C1), '#1501: the sidebar shows the colour at once');
  check(w.__st === st0, '#1501: no GET /api/state was needed for it (' + (w.__st - st0) + ')');
  check((await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === L)?.color === C1)), '#1501: the server has the colour');

  // ================= the second window gets it with the live update
  check(await until(() => w2.eval(`listById(${L})?.color`) === C1, 70), '#1501: a second window gets the colour by the live update');

  // ================= Undo puts it back
  await w.eval(`histStep('undo')`);
  await until(() => lc(w, L) === '', 40);
  check(lc(w, L) === '', '#1501: Undo puts the colour back locally: ' + lc(w, L));
  check((await call('GET', '/api/state')).lists.find(l => l.id === L)?.color === '', '#1501: Undo puts it back on the server');

  // ================= a server error puts the old colour back
  w.__fail = new RegExp(`/api/lists/${L}$`); w.__pDelay = 600;
  const pe = w.eval(`licColor(${L}, '${C2}')`);
  await sleep(200);
  check(lc(w, L) === C2, '#1501: the colour shows while the failing request runs');
  await pe;
  check(lc(w, L) === '', '#1501: after the error the old colour is back: ' + lc(w, L));
  check(!d.querySelector('#side').innerHTML.includes(C2), '#1501: the sidebar shows the old colour again');
  check((await call('GET', '/api/state')).lists.find(l => l.id === L)?.color === '', '#1501: the server kept the old colour');
  w.__fail = null;

  // ================= a state fetched while the write runs does not take the change back (no flicker)
  w.__sDelay = 0; w.__pDelay = 1500;
  const pn = w.eval(`listPatch(${L}, {name: 'Garden plan'}, null)`);
  await sleep(200);
  check(w.eval(`listById(${L}).name`) === 'Garden plan', '#1501: the new name shows at once');
  await w.eval(`load()`);  // what the poll does: the server still has the old name
  check(w.eval(`listById(${L}).name`) === 'Garden plan', '#1501: a state loaded meanwhile keeps the new name (no flicker)');
  check([...d.querySelectorAll('#side *')].some(x => x.textContent.trim() === 'Garden plan'), '#1501: the sidebar keeps the new name');
  await pn;
  check((await call('GET', '/api/state')).lists.find(l => l.id === L)?.name === 'Garden plan', '#1501: the server has the new name');
  w.__pDelay = 0; w.__sDelay = 4000;

  // ================= sections: rename and order locally
  const SA = (await call('POST', '/api/sections', {list_id: L, name: 'Beds'})).id, SB = (await call('POST', '/api/sections', {list_id: L, name: 'Pots'})).id;
  w.__sDelay = 0; await w.eval(`load()`); w.__sDelay = 4000;
  // CI of 2.168.3 / 2.168.4 (red twice): the change poll is held here too, like for the list tags below (2.93.1 / 2.98.1)
  await until(() => w.eval('td_polling ? false : (td_polling = true)'), 80);
  let st1 = w.__st;
  w.eval(`sectionRename(${SA}, 'Raised beds')`);
  await sleep(250);
  check(w.eval(`S.sections.find(s => s.id === ${SA})?.name`) === 'Raised beds', '#1501: a section rename shows at once');
  w.eval(`saveSectionOrder(${L}, [${SB}, ${SA}])`);
  await sleep(250);
  check(w.eval(`secIds(${L}).join()`) === `${SB},${SA}`, '#1501: the section order changes at once: ' + w.eval(`secIds(${L}).join()`));
  check(w.__st === st1, '#1501: sections without GET /api/state' + (w.__st === st1 ? '' : ' (from ' + w.__stk + ')'));
  w.eval('td_polling = false');
  check(await until(async () => (await call('GET', '/api/state')).sections.filter(s => s.list_id === L).sort((a, b) => a.sort - b.sort).map(s => s.name).join() === 'Pots,Raised beds'), '#1501: the server has name and order');

  // ================= list tags: colour and rename locally (the tasks' tags follow the name)
  const TG = (await call('POST', `/api/lists/${L}/tags`, {name: 'urgent'})).id;
  const T = (await call('POST', '/api/tasks', {list_id: L, title: 'Water the roses'})).id;
  await call('PATCH', '/api/tasks/' + T, {ltags: ['urgent']});
  w.__sDelay = 0; await w.eval(`load()`); w.__sDelay = 4000;
  // 2.93.1: the 4 s change poll (core.js) may load the state on its own when it sees the server version of the calls above;
  // it is held for this check (CI red twice), the write itself must not fetch the state
  // 2.98.1 (CI red again): a poll already on the way could still load the state - hold it only once none is running
  await until(() => w.eval('td_polling ? false : (td_polling = true)'), 80);
  st1 = w.__st;
  w.eval(`optWrite(ltagPut(${L}, 'urgent', 'soon'), () => api('PATCH', '/api/list-tags/${TG}', {name: 'soon'}))`);
  await sleep(250);
  check(w.eval(`listTags(${L}).map(t => t.name).join()`) === 'soon', '#1501: a list tag rename shows at once');
  check(w.eval(`(S.tasks.get(${T})?.ltags || []).join()`) === 'soon', '#1501: the task carries the new tag name at once: ' + w.eval(`(S.tasks.get(${T})?.ltags || []).join()`));
  check(w.__st === st1, '#1501: list tags without GET /api/state' + (w.__st === st1 ? '' : ' (from ' + w.__stk + ')'));
  w.eval('td_polling = false');

  // ================= the list view switches locally
  await sleep(1500);  // 2.80.3: late answers of the steps above settle first (slow CI)
  await until(() => w.eval('td_polling ? false : (td_polling = true)'), 80);  // CI of 2.168.4: the change poll held (as above)
  st1 = w.__st;
  w.eval(`setListView(listById(${L}), 'kanban')`);
  await sleep(250);
  check(w.eval(`listById(${L}).view`) === 'kanban', '#1501: the list view switches at once');
  check(w.__st === st1, '#1501: the view switch without GET /api/state' + (w.__st === st1 ? '' : ' (from ' + w.__stk + ')'));
  w.eval('td_polling = false');

  w.close(); w2.close();
  console.log(`p2412_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
