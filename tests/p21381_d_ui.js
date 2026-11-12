// 2.138.2 D (#2405): the News bell as an inbox (2.1037.0 #5807: Also new + Read = one folded history, see tests/p21037_b_bell_ui.js): "For you" (unread + to me, the bell's number) / "Also new" (other unread) /
// "Read" (below, muted). jsdom: bell number = "For you" number = header number, read bundles never above unread ones, read =
// muted class, unread = stripe class and no dot (2.1052.0 #5808: the plain list is gone, only bundled). Firefox 390 / 1280, light + dark (P21381D_SHOTS=<dir>).
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
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
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
  let w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsHist': null}}), d = w.document;  // 2.1037.0 (#5807): the folded default; 2.1052.0 (#5808): no tasks.newsBundle any more
  await until(() => d.querySelector('.nbund .ngroup'));
  const bell = +(d.querySelector('.bell .nbadge')?.textContent || 0);
  const meSec = d.querySelector('#ns-need')?.closest('.nsect');
  check(bell > 0 && meSec && +meSec.querySelector('.nsh .c')?.textContent === bell, `#2405: "For you" number = bell number (${bell}) ` + meSec?.querySelector('.nsh')?.textContent);
  check(meSec && !/Needs you/.test(d.body.textContent) && /For you/.test(meSec.textContent) && meSec.querySelector('.ngroup.unread.needs'), '#2405: the section is "For you", its bundles unread + needs');
  // 2.1037.0 (#5807): "Also new" and "Read" became ONE folded history without the unread look (no stripe, no tick, no count)
  const hist = d.querySelector('.nbund .nhist');
  check(hist && !hist.querySelector('.ngroup') && hist.querySelector('[data-act="news-hist"][aria-expanded="false"]') && !d.querySelector('#ns-info, #ns-read') && !/Also new/.test(d.body.textContent), '#5807: the history is folded (was: Also new / Read)');
  w.close();
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsHist': true}}); d = w.document;
  await until(() => d.querySelector('.nbund .nhist .ngroup'));
  const hg = [...d.querySelectorAll('.nbund .nhist .ngroup')];
  check(hg.length >= 1 && hg.every(g => !g.classList.contains('unread') && !g.querySelector('.ngn, [data-act="news-gread"]')), '#5807: history bundles: no unread look, no count, no tick');
  const gs = [...d.querySelectorAll('.nbund .ngroup')], lastNeed = gs.map(g => g.classList.contains('needs') && g.classList.contains('unread')).lastIndexOf(true), firstH = gs.findIndex(g => g.closest('.nhist'));
  check(firstH > lastNeed, '#2405/#5807: For you above the history');
  w.close();
  // ================= Firefox: layout + shots
  const OVER = `(() => ({o: document.documentElement.scrollWidth - innerWidth}))()`;
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  for (const [th, wd, ht, touch] of [['light', 390, 844, true], ['dark', 390, 844, true], ['light', 1280, 900, false], ['dark', 1280, 900, false]]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${wd} ${th}`;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${th}"'); localStorage.setItem('tasks.lookLocal', 'true'); localStorage.setItem('tasks.newsHist', 'true'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
    await o.nav(B + '#news'); await ready(ev);
    const x = await ev(OVER);
    check(x.o <= 0, `${tag}: nothing sideways ` + JSON.stringify(x));
    // 2.1037.0 (#5807): the history is open on this device (tasks.newsHist) so its calm rows can be measured
    const st = await ev(`(() => { const u = document.querySelector('.ngroup.unread'), r = document.querySelector('.ngroup.read'); const cs = (e, p, pe) => e && getComputedStyle(e, pe)[p];
      return {uShadow: cs(u, 'boxShadow'), uDot: cs(u.querySelector('.ngt'), 'content', '::before'), rOp: cs(r.querySelector('.ngav .avatar'), 'opacity'), rW: cs(r.querySelector('.ngt'), 'fontWeight'), uW: cs(u.querySelector('.ngt'), 'fontWeight')}; })()`);
    check(st.uShadow !== 'none' && st.uDot !== '""' && +st.rOp < 1 && +st.rW < +st.uW, `${tag}: unread stripe without dot, read muted ` + JSON.stringify(st));
    await shot(`p21381-d-${th}-${wd}-news.png`);
    await ev(`document.querySelector('[data-act="bell-pop"]').click()`); await sleep(700);
    const bp = await ev(`(() => ({n: document.querySelectorAll('.bpop .nsect').length /* 2.1052.0 (#5808): only the bundled sections */, head: document.querySelector('.bpnew')?.textContent || ''}))()`);
    check(bp.n >= 2 && /for you/.test(bp.head), `${tag}: bell panel has sections + "N for you" ` + JSON.stringify(bp));
    await shot(`p21381-d-${th}-${wd}-bell.png`);
  }, touch);

  // 2.1052.0 (#5808): the plain list (tasks.newsBundle false) is gone - its two checks ("For you" number = bell, the history
  // at the bottom without the unread look) are the bundled ones above; here (after Firefox, the click reads the mention): a click on the mention's bundle opens its task
  w = await boot({user: 'alice', hash: 'news'}); d = w.document;
  await until(() => d.querySelector('.nbund .nsect.me .ngroup.needs'));
  {
    const mg = [...d.querySelectorAll('.nbund .nsect.me .ngroup.needs')].find(g => /Call the printer/.test(g.querySelector('.ngt')?.textContent || ''));
    check(mg && /can you call them/.test(mg.querySelector('.ngex')?.textContent || ''), '#5808: the mention\'s bundle under "For you" shows what was written');
    // one entry: the head opens it; several: the head unfolds the bundle and a row opens
    if (mg) { const one = mg.querySelector('.ngmain').dataset.act === 'news-open'; mg.querySelector('.ngmain').click();
      if (!one) { await until(() => d.querySelector(`.ngroup[data-gk="${mg.dataset.gk}"] .ngitems .nitem`)); d.querySelector(`.ngroup[data-gk="${mg.dataset.gk}"] .ngitems .nitem`).click(); }
      await until(() => w.eval('S.sel') === T[1]); }
    check(w.eval('S.sel') === T[1], '#5808: a click on the bundle opens its task');
  }
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
