// 2.144.3 C UI tests (#2405): News with an unread agent approval -- the bell number (S.news.unread_me) equals the count of
// the section "For you" (one approval = 1), the divider of the read items reads "Read" (own key "Read|section", no suffix).
// freelancer-matrix: news (the same page without an organisation is covered by p21443_c_api_test.py).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
if (!process.env.P21443C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const py = code => execFileSync('docker', ['exec', CT, 'python', '-c', code], {encoding: 'utf8'}).trim();
const sql = (q, rows) => py(`import json
from kalmido.core.db import connect
c = connect()
for r in json.loads(${JSON.stringify(JSON.stringify(rows))}):
    c.execute(${JSON.stringify(q)}, r)
c.commit(); c.close()`);
const FEAT = 'comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Work'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Prepare the offer', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Old thing', list_id: L})).id;
  sql('INSERT INTO notifications (user_id, kind, task_id, actor_id, data, created_at, read_at) VALUES (?,?,?,?,CAST(? AS jsonb),?,?)', [
    [ME.id, 'approval', T, ag.id, '{"title": "Prepare the offer"}', '2026-04-01T10:00:00Z', null],
    [ME.id, 'approval', T2, ag.id, '{"title": "Old thing"}', '2026-03-01T10:00:00Z', '2026-03-02T10:00:00Z']]);
  const w = await boot({user: 'alice', hash: 'news'}), d = w.document;
  await until(() => d.querySelector('.nlist .nitem')); await sleep(300);
  const bell = +(d.querySelector('.bell .nbadge')?.textContent || 0);
  check(bell === 1, '#2405: the bell number counts the agent approval ' + bell);
  const sec = d.querySelector('.nsec.me .c.nunread');
  check(sec && +sec.textContent === bell, `#2405: section "For you" equals the bell number (${bell}) ` + sec?.textContent);
  const rd = d.querySelector('.nsec.read span');
  check(rd && rd.textContent.trim() === 'Read', '#2405: the divider reads "Read": ' + (rd && rd.textContent));
  w.close();
  console.log(`p21443_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
