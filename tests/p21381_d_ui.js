// 2.138.2 D (#2405): the News bell as an inbox: "For you" (unread + to me, the bell's number) / "Also new" (other unread) /
// "Read" (below, muted). jsdom: bell number = "For you" number = header number, read bundles never above unread ones, read =
// muted class, unread = stripe class and no dot; the same in the plain list. Firefox 390 / 1280, light + dark (P21381D_SHOTS=<dir>).
// freelancer-matrix: n/a - nur Oberfläche
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21381_d_ui', check, shots: 'P21381D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21381D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done'}, CB);
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T = [];
  for (const t of ['Write the homepage text', 'Call the printer']) T.push((await call('POST', '/api/tasks', {title: t, list_id: L})).id);
  await call('POST', `/api/tasks/${T[0]}/comments`, {body: 'First draft is in'}, CB);
  await call('POST', `/api/tasks/${T[0]}/comments`, {body: 'And the second part'}, CB);
  // the first two comments are read, then fresh ones arrive: an unread "for you" mention and an unread comment
  const first = (await call('GET', '/api/news')).items.filter(it => it.task_id === T[0]);
  await call('POST', '/api/news/read', {ids: first.flatMap(it => it.ids || [it.id])});
  await call('POST', `/api/tasks/${T[1]}/comments`, {body: '<@1> can you call them?'}, CB);
  await call('POST', `/api/tasks/${T[0]}/comments`, {body: 'Third part is in'}, CB);

  // ================= jsdom: bundled
  let w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsBundle': null}}), d = w.document;
  await until(() => d.querySelector('.nbund .ngroup'));
  const bell = +(d.querySelector('.bell .nbadge')?.textContent || 0);
  const meSec = d.querySelector('#ns-need')?.closest('.nsect');
  check(bell > 0 && meSec && +meSec.querySelector('.nsh .c')?.textContent === bell, `#2405: "For you" number = bell number (${bell}) ` + meSec?.querySelector('.nsh')?.textContent);
  check(meSec && !/Needs you/.test(d.body.textContent) && /For you/.test(meSec.textContent) && meSec.querySelector('.ngroup.unread.needs'), '#2405: the section is "For you", its bundles unread + needs');
  const readSec = d.querySelector('#ns-read')?.closest('.nsect'), gs = [...d.querySelectorAll('.nbund .ngroup')];
  check(readSec && readSec.querySelectorAll('.ngroup.read').length >= 1 && !readSec.querySelector('.ngroup.unread, .ngroup.needs'), '#2405: "Read" holds only read bundles, none "needs"');
  const lastUnread = gs.map(g => g.classList.contains('unread')).lastIndexOf(true), firstRead = gs.findIndex(g => g.classList.contains('read'));
  check(firstRead > lastUnread, '#2405: read bundles never above unread ones');
  check(!d.querySelector('.ngroup.read .ngn') && d.querySelector('.ngroup.unread') && !d.querySelector('.ngroup.read [data-act="news-gread"]'), '#2405: read bundle has no tick / count');
  check(d.querySelector('#ns-info') && d.querySelector('#ns-info').closest('.nsect').textContent.includes('Also new'), '#2405: "Also new" section for the other unread');
  w.close();
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsBundle': false}}); d = w.document; await sleep(500);
  await until(() => d.querySelector('.nlist .nitem'));
  const sec = d.querySelector('.nsec.me .c.nunread');
  check(sec && +sec.textContent === bell, '#2405: plain list: "For you" number = bell number');
  const items = [...d.querySelectorAll('.nlist .nitem, .nlist .nsec')];
  const iRead = items.findIndex(x => x.matches('.nsec.read')), lastU = items.map(x => x.classList.contains('unread')).lastIndexOf(true);
  check(iRead > lastU && items.filter((x, i) => i > iRead && x.classList.contains('unread')).length === 0, '#2405: plain list: Read section at the bottom, no unread below it');
  w.close();

  // ================= Firefox: layout + shots
  const OVER = `(() => ({o: document.documentElement.scrollWidth - innerWidth}))()`;
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  for (const [th, wd, ht, touch] of [['light', 390, 844, true], ['dark', 390, 844, true], ['light', 1280, 900, false], ['dark', 1280, 900, false]]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${wd} ${th}`;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${th}"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
    await o.nav(B + '#news'); await ready(ev);
    const x = await ev(OVER);
    check(x.o <= 0, `${tag}: nothing sideways ` + JSON.stringify(x));
    const st = await ev(`(() => { const u = document.querySelector('.ngroup.unread'), r = document.querySelector('.ngroup.read'); const cs = (e, p, pe) => e && getComputedStyle(e, pe)[p];
      return {uShadow: cs(u, 'boxShadow'), uDot: cs(u.querySelector('.ngt'), 'content', '::before'), rOp: cs(r.querySelector('.ngav .avatar'), 'opacity'), rW: cs(r.querySelector('.ngt'), 'fontWeight'), uW: cs(u.querySelector('.ngt'), 'fontWeight')}; })()`);
    check(st.uShadow !== 'none' && st.uDot !== '""' && +st.rOp < 1 && +st.rW < +st.uW, `${tag}: unread stripe without dot, read muted ` + JSON.stringify(st));
    await shot(`p21381-d-${th}-${wd}-news.png`);
    await ev(`document.querySelector('[data-act="bell-pop"]').click()`); await sleep(700);
    const bp = await ev(`(() => ({n: document.querySelectorAll('.bpop .nsect, .bpop .nsec').length, head: document.querySelector('.bpnew')?.textContent || ''}))()`);
    check(bp.n >= 2 && /for you/.test(bp.head), `${tag}: bell panel has sections + "N for you" ` + JSON.stringify(bp));
    await shot(`p21381-d-${th}-${wd}-bell.png`);
  }, touch);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
