// 2.102.0 B UI tests (own container, start.sh; P2102B_NOSTART=1: the container runs already). jsdom:
// - #2197 News: bundled per task only, read and unread never share a line, unread lines first, one number per line
//   (unread), the tabs show their unread numbers (the "All" tab = the bell's number)
// - #2204 the key hint next to the send buttons (team chat, agent chat, comments), empty on touch devices
// - #2206 choosing in the file store / documents: room below the list as high as the sticky bar (class + CSS rule),
//   the choosing mark in documents has a 2.75rem touch target
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2102B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team,files,docs';
const css = f => { for (const base of [path.join(__dirname, '..', 'static'), path.join(__dirname, '..', 'app', 'static')]) { try { return fs.readFileSync(path.join(base, f), 'utf8'); } catch (e) { /* next */ } } return ''; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: FEAT, tour: 'done'}, CB);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/agent`, {agent_id: ag.id});
  const TA = (await call('POST', '/api/tasks', {title: 'Alpha task', list_id: L})).id;
  const TB = (await call('POST', '/api/tasks', {title: 'Beta task', list_id: L})).id;
  // alternating tasks: the server cannot merge them (only neighbours of one task bundle)
  for (const t of [TA, TB, TA, TB, TA]) await call('POST', `/api/tasks/${t}/comments`, {body: 'note on ' + t}, CB);

  // ================= #2197 News
  const items = (await call('GET', '/api/news')).items.filter(it => it.kind === 'comment');
  const firstA = items.filter(it => it.task_id === TA).sort((a, b) => a.id - b.id)[0];
  await call('POST', '/api/news/read', {ids: firstA.ids || [firstA.id]});
  let w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsBundle': null, newsTab: '"all"'}}), d = w.document;
  await until(() => d.querySelector('.nbund .ngroup'));
  const gs = [...d.querySelectorAll('.nbund .ngroup')];
  const ga = gs.filter(g => g.querySelector('.ngt')?.textContent.includes('Alpha task')), gb = gs.filter(g => g.querySelector('.ngt')?.textContent.includes('Beta task'));
  check(ga.length === 2 && gb.length === 1, '#2197: per task, read and unread apart: Alpha twice, Beta once ' + gs.map(g => g.querySelector('.ngt')?.textContent).join('|'));
  const gau = ga.find(g => g.classList.contains('unread')), gar = ga.find(g => !g.classList.contains('unread'));
  check(gau && gar && gs.indexOf(gau) < gs.indexOf(gar), '#2197: the unread line stands above the read one');
  check(gau && gau.querySelector('.ngn')?.textContent === '2' && gb[0].querySelector('.ngn')?.textContent === '2', '#2197: the number of a line = its unread entries');
  check(gar && !gar.querySelector('.ngn') && !gar.querySelector('[data-act="news-gread"]'), '#2197: a read line has no number and no "Mark read"');
  check(!/^\d+$/.test((gau?.querySelector('.ngs')?.textContent || '').trim()) && /2 comments/.test(gau?.querySelector('.ngs')?.textContent || ''), '#2197: the total only as text "2 comments"');
  const bell = w.eval('S.news.unread'), tabsum = +(d.querySelector('.ntabs [data-tab="all"] .nunread')?.textContent || 0);
  const me = +(d.querySelector('.ntabs [data-tab="me"] .nunread')?.textContent || 0), act = +(d.querySelector('.ntabs [data-tab="act"] .nunread')?.textContent || 0);
  check(bell > 0 && me + act === bell && tabsum === bell, `#2197: bell ${bell} = the unread numbers of the tabs ${me} + ${act} (All: ${tabsum})`);
  w.close();

  // ================= #2204 key hint
  const dm = await call('POST', '/api/team/dm', {user_id: BOB}), rid = dm.id || dm.room?.id;
  w = await boot({user: 'alice', hash: 'team/' + rid}); d = w.document;
  await until(() => d.querySelector('#tc-in') && d.querySelector('.chkh'));
  check(/^(Ctrl|Cmd)\+Enter sends$/.test(d.querySelector('.tccomp .chkh')?.textContent || ''), 'team chat: the visible hint ' + d.querySelector('.tccomp .chkh')?.textContent);
  w.eval(`chatOpen(${ag.id})`);
  check(await until(() => /Enter sends/.test(d.querySelector('#chat-in')?.closest('.chcomp')?.querySelector('.chkh')?.textContent || '')), 'agent chat: the visible hint');
  w.eval(`openDetail(${TA})`); await sleep(1200);
  check(/Enter sends/.test(d.querySelector('.chint')?.textContent || ''), 'comments: the hint ' + d.querySelector('.chint')?.textContent);
  w.close();
  w = await boot({user: 'alice', hash: 'team/' + rid, media: {'(hover:none)': true}}); d = w.document;
  await until(() => d.querySelector('#tc-in'));
  check(d.querySelector('.tccomp .chkh') && d.querySelector('.tccomp .chkh').textContent === '', 'touch device: the hint is empty');
  w.close();

  // ================= #2206 choosing
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob(['Rechnung Beispiel 12,50 EUR']), 'beleg.txt');
  await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const fu = new FormData(); fu.append('file', new Blob(['erste Datei']), 'eins.txt'); fu.append('space', 'private');
  await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fu});
  w = await boot({user: 'alice', hash: 'docs', mobile: true}); d = w.document;
  await until(() => d.querySelector('[data-dcsel="mode"]'));
  check(!d.querySelector('.dc-grid.dc-selon'), 'documents: no extra room outside choosing');
  d.querySelector('[data-dcsel="mode"]').click();
  check(await until(() => d.querySelector('.dc-grid.dc-selon .dc-selmark')), 'documents: choosing -> the grid has room for the bar, the cards a mark');
  w.close();
  w = await boot({user: 'alice', hash: 'ablage', mobile: true, ls: {abSpace: '"private"'}}); d = w.document;
  await until(() => d.querySelector('[data-absel="mode"]'));
  check(!d.querySelector('.ablist.abselon'), 'file store: no extra room outside choosing');
  d.querySelector('[data-absel="mode"]').click();
  check(await until(() => d.querySelector('.ablist.abselon') && d.querySelector('.abselbar')), 'file store: choosing -> the list has room for the bar');
  w.close();
  const dcss = css('css/docs.css'), acss = css('app.css');
  check(/\.dc-grid\.dc-selon\{padding-bottom:7\.5rem\}/.test(dcss) && /\.ablist\.abselon\{padding-bottom:7\.5rem\}/.test(acss), 'the CSS rules for the room in rem');
  // 2.119.1 (#2206): -.625rem (the pseudo box starts inside the .125rem border; -.5rem made only 2.5rem), measured in p21191_d_ui
  check(/\.dc-selmark::after\{[^}]*inset:-\.625rem/.test(dcss) && /\.dc-selmark\{[^}]*width:1\.75rem/.test(dcss), 'the choosing mark: 1.75rem circle + 2.75rem touch target');

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
