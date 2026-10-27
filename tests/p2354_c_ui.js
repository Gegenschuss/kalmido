// 2.354.0 C (#3326 #3009 #3013) UI tests. Own container (start.sh). jsdom + Firefox (layout).
// freelancer-matrix: tasks / quick dates -- alice has no organisation: everything below runs in her private space
// - #3326: a task due tomorrow or later: "+1 day" (tooltip: the target day) and "-1 day" (never before today); due today / no date: "Tomorrow", no "-1 day"
// - #3009: Today > Overdue: "All to today" / "Another day…" never overlap the block's "…" at 690 / 820 / 1100 / 1440 px
// - #3013: "Name missing" for a new project without a name, "under 1 minute", no hyphenation in the icon bar, "Ctrl K" only with a mouse
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2354_c_ui', check, shots: 'P2354C_SHOTS'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const task = async id => (await call('GET', '/api/state')).tasks.find(t => t.id === id);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const T = (await call('POST', '/api/tasks', {list_id: L, title: 'Pay the rent', due: day(2)})).id;
  for (let i = 1; i <= 3; i++) await call('POST', '/api/tasks', {list_id: L, title: 'Late ' + i, due: day(-i)});

  // ================= #3326
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${T})`); await sleep(400);
  const qs = () => [...d.querySelectorAll('#detail .dtop [data-act="due-q"]')].map(b => b.dataset.d + ':' + b.querySelector('.dql').textContent.trim()).join(',');
  const set = async (due) => { await call('PATCH', `/api/tasks/${T}`, {due}); w.eval(`putTask(${JSON.stringify(await task(T))})`); w.eval('render()'); w.eval(`openDetail(${T})`); await sleep(150); };
  check(qs() === '0:Today,1:+1 day,-1:-1 day', 'due in 2 days: Today, +1 day, -1 day: ' + qs());
  const plus = d.querySelector('#detail [data-act="due-q"][data-d="1"]');
  check(plus.title.includes(w.eval(`dayLabel('${day(3)}')`)), 'tooltip of +1 day names the target day: ' + plus.title);
  click(w, d.querySelector('#detail [data-act="due-q"][data-d="-1"]'));
  check(await until(async () => (await task(T)).due === day(1)), '-1 day: due tomorrow');
  check(await until(() => /-1 day/.test(qs())), 'due tomorrow: -1 day is still there (tomorrow > today): ' + qs());
  click(w, d.querySelector('#detail [data-act="due-q"][data-d="-1"]'));
  check(await until(async () => (await task(T)).due === day(0)), 'a further -1 day: due today');
  check(await until(() => !/-1 day/.test(qs())), 'due today: -1 day is gone: ' + qs());
  check(/1:Tomorrow/.test(qs()), 'due today: the button reads Tomorrow: ' + qs());
  w.eval(`quickDue(${T}, -1)`); await sleep(300);
  check((await task(T)).due === day(0), 'quickDue(-1) never goes before today');
  await set(null);
  check(/1:Tomorrow/.test(qs()) && !/-1 day/.test(qs()), 'no date: Tomorrow, no -1 day: ' + qs());
  await set(day(-2));
  check(/1:Tomorrow/.test(qs()) && !/-1 day/.test(qs()), 'overdue: Tomorrow, no -1 day: ' + qs());
  // the menu row follows the same rule
  await set(day(4));
  const row = w.eval(`quickDueRow(${T}).row.map(x => x.label).join('|')`);
  check(row === 'Today|+1 day|-1 day', 'menu row: ' + row);
  w.eval(`quickDueRow(${T}).row[2].fn()`);
  check(await until(async () => (await task(T)).due === day(3)), 'menu -1 day moves one day back');
  await set(day(0));
  check(w.eval(`quickDueRow(${T}).row.map(x => x.label).join('|')`) === 'Today|Tomorrow', 'menu row due today: Today|Tomorrow');

  // ================= #3013 (small texts)
  check(w.eval('fmtDur(30)') === 'under 1 minute', 'time: under a minute reads "under 1 minute": ' + w.eval('fmtDur(30)'));
  check(w.eval('fmtDur(120)') !== 'under 1 minute', 'time: two minutes stay a time');
  w.eval('listModal()'); await sleep(300);
  const nm = d.querySelector('#l-name');
  check(!!nm, 'the New project dialog opens');
  nm.value = '';
  d.querySelector('.modal [data-m="save"]').click();
  check(await until(() => nm.getAttribute('aria-invalid') === 'true'), 'New project without a name: the field is marked');
  check(await until(() => /Name missing/.test(d.body.textContent)), 'New project without a name: "Name missing"');
  const css = require('fs').readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/@media not all and \(hover:hover\) and \(pointer:fine\)\{ #top \.cmdbar \.kbs\{display:none\} \}/.test(css), 'CSS: the Ctrl K hint only with a mouse');
  check(/\.srb \.srbn\{[^}]*hyphens:none/.test(css) && !/\.srb \.srbn\{[^}]*hyphens:auto/.test(css), 'CSS: the icon bar does not hyphenate');
  const org = require('fs').readFileSync(path.join(__dirname, '..', 'static', 'js', 'areas.js'), 'utf8');
  check(/tr\('Add an organisation'\)/.test(org) && !/tr\('Add a company'\)/.test(org), 'the workspace switch says "Add an organisation"');
  w.close();

  // ================= #3009 + hyphens + Ctrl K in a real browser
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(300); await sleep(500); };
  if (!process.env.NOFF) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'ff: login');
    for (const wd of [690, 820, 1100, 1440]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: 900}});
      await o.nav(B + '#today'); await ready(ev, '#view .ghead .odact');
      const m = await ev(`(() => {
        const act = document.querySelector('#view .ghead .odact'), more = document.querySelector('[data-ly="today"] > .lyb[data-lyk="tasks"] > .lymore') || document.querySelector('#view .lymore');
        if (!act || !more) return {err: 'missing ' + !act + ' ' + !more};
        const a = [...act.querySelectorAll('button')].map(b => b.getBoundingClientRect()), r = more.getBoundingClientRect();
        const hit = a.some(x => x.width && x.left < r.right && x.right > r.left && x.top < r.bottom && x.bottom > r.top);
        const gap = Math.min(...a.map(x => r.left - x.right)); return {hit, gap: Math.round(gap), n: a.length, sw: document.documentElement.scrollWidth, more: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)], a: a.map(x => [Math.round(x.left), Math.round(x.top), Math.round(x.right), Math.round(x.bottom)])};
      })()`);
      check(m && !m.err && m.n === 2 && m.hit === false && m.gap >= 8, `${wd} px: the Overdue buttons do not overlap the "…" ${JSON.stringify(m)}`);
      if (wd === 690 || wd === 1440) await shot(`p2354c-${wd}-today.png`);
    }
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#today'); await ready(ev, '#view');
    const hy = await ev(`(() => { const e = document.querySelector('.srb .srbn'); return e ? getComputedStyle(e).hyphens : 'none'; })()`);
    check(hy === 'none', 'ff: the icon bar does not hyphenate: ' + hy);
    const kb = await ev(`(() => { const e = document.querySelector('#top .cmdbar .kbs'); return e ? getComputedStyle(e).display : 'absent'; })()`);
    check(kb !== 'none', 'ff: with a mouse the Ctrl K hint shows (' + kb + ')');
  }, false);
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'ff touch: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 820, height: 900}});
    await o.nav(B + '#today'); await ready(ev, '#view .ghead .odact');
    const m = await ev(`(() => {
      const act = document.querySelector('#view .ghead .odact'), more = document.querySelector('#view .lymore');
      if (!act || !more) return {err: 'missing'};
      const r = more.getBoundingClientRect();
      const bs = [...act.querySelectorAll('button')].map(b => b.getBoundingClientRect());
      return {gap: Math.round(Math.min(...bs.map(x => r.left - x.right))), hit: bs.some(x => x.left < r.right && x.right > r.left && x.top < r.bottom && x.bottom > r.top),
        kbs: [...document.querySelectorAll('#top .cmdbar .kbs')].map(e => getComputedStyle(e).display)};
    })()`);
    check(m && !m.err && m.hit === false && m.gap >= 8, 'touch 820 px: no overlap, a gap of 8 px ' + JSON.stringify(m));
    check(m && (m.kbs || []).every(x => x === 'none'), 'touch: no Ctrl K hint ' + JSON.stringify(m));
    await shot('p2354c-touch-today.png');
  }, true);

  console.log(`p2354_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
