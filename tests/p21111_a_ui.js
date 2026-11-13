// 2.1111.0 Part A (#5963): the start page without clutter, own container (start.sh).
// kalmido-suite: fresh
// jsdom: the sentence under the greeting names only today ("overdue" stands once, in the box "Waiting for you"); the integration failure in the news says how to fix it; the quote is one line
// that a tap opens. Firefox 412x900 (phone, touch): the first task of the card Today is in the first screen without scrolling,
// the active tab and the page title have one name, nothing moves while it loads. Screenshots into $P21111A_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21111_a_ui', check, shots: 'P21111A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const TC = require('./testclock');
const T0 = TC.today();
const txt = (d, s) => (d.querySelector(s)?.textContent || '').replace(/\s+/g, ' ').trim();

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,time'});
  for (let i = 1; i <= 5; i++) await call('POST', '/api/tasks', {title: 'Late task ' + i, due: TC.day(-i)});
  await call('POST', '/api/tasks', {title: 'Today task', due: T0});

  // ================= jsdom
  const w = await boot({user: 'alice', hash: 'home'}), d = w.document;
  await until(() => d.querySelector('#view .hpsum') && d.querySelector('.dc-today .dtl li'));
  const sum = txt(d, '.hpsum');
  check(/^6 tasks for today/.test(sum) && !/overdue/i.test(sum), '#5963: the sentence names only today: ' + sum);
  const dash = txt(d, '.dash');
  const n = (dash.match(/\d+ tasks? overdue|\d+ overdue/gi) || []).length;
  check(n === 1 && /5 tasks overdue/.test(txt(d, '.dtome')), '#5963: "overdue" stands once, in the box Waiting for you (' + n + ') ' + txt(d, '.dtome'));
  const fig = d.querySelector('figure.qd.dashq');
  check(!fig || (fig.getAttribute('aria-expanded') === 'false' && !fig.classList.contains('open')), '#5963: the quote starts closed');
  if (fig) { fig.click(); check(fig.classList.contains('open') && fig.getAttribute('aria-expanded') === 'true', '#5963: a tap opens the quote'); fig.click(); check(!fig.classList.contains('open'), '#5963: a second tap closes it'); }
  // the Today tab is on, the title says the same
  const on = txt(d, '#tabs button.on'), title = txt(d, '#top h1 .ht');
  check(on && on === title, `#5963: active tab and title have one name: "${on}" / "${title}"`);
  // integration failure: a sentence that says how to fix it
  const ft = w.eval(`newsText({kind: 'integfail', data: {what: 'git', text: 'Git connection Docs cannot fetch, failing since 3 Nov.'}}, [])`);
  check(/Git connection Docs cannot fetch/.test(ft) && /Check the connection in the settings, or remove it\./.test(ft), '#5963: integfail with a way to the solution: ' + ft);
  const f2 = w.eval(`newsText({kind: 'integfail', data: {what: 'backup', text: 'Backup failed: x'}}, [])`);
  check(!/Check the connection/.test(f2), '#5963: other integration texts stay as they are');
  w.close();

  // ================= Firefox, phone
  if (process.env.NOFF) { console.log(`${ok} ok, ${F.length} failed`); process.exit(F.length ? 1 : 0); }
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 900}});
    await nav(B + '#home');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.dc-today .dtl li')`).catch(() => false)); i++) await sleep(300);
    await sleep(900);
    const M = `(() => { const q = s => document.querySelector(s), top = e => e ? Math.round(e.getBoundingClientRect().top) : null;
      const li = q('.dc-today .dtl li'), qd = q('figure.qd.dashq .qdo');
      return {bottom: li ? Math.round(li.getBoundingClientRect().bottom) : null, vh: window.innerHeight, sw: document.documentElement.scrollWidth,
        qh: qd ? Math.round(qd.getBoundingClientRect().height) : null, lh: qd ? parseFloat(getComputedStyle(qd).lineHeight) || 24 : null,
        on: (q('#tabs button.on') || {}).textContent, title: (q('#top h1 .ht') || {}).textContent, ht: top(q('.dtome h3')), box: top(q('.dtome')),
        mono: li ? getComputedStyle(q('.dc-today .dt') || li).fontFamily : ''}; })()`;
    const m = await ev(M);
    check(m.bottom !== null && m.bottom <= m.vh, '#5963: the first task of Today is in the first screen without scrolling ' + JSON.stringify(m));
    check(m.qh === null || m.qh <= m.lh * 1.5, '#5963: the quote is one line ' + m.qh + ' / ' + m.lh);
    check(m.sw <= 412, '#5963: nothing sideways ' + m.sw);
    check(m.on && m.on.trim() === (m.title || '').trim(), `#5963: active tab and title: "${m.on}" / "${m.title}"`);
    // nothing moves after loading: the first task stays where it is
    await sleep(1200);
    const m2 = await ev(M);
    check(m2.bottom === m.bottom, `#5963: the first task did not move (${m.bottom} -> ${m2.bottom})`);
    await shot('p21111a-412.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
