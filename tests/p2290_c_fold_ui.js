// 2.290.0 C (#3163) an unfolded Fold 8 landscape / small tablets (900-1199 px): never bar | panel | list | task side by side,
// own container (start.sh, isolated test database). freelancer-matrix: tasks
// - jsdom: below 1200 px a task open folds the panel into the drawer (side-rail, not remembered), the bar stays; closing the
//   task brings the panel back; 1400 px keeps the panel; a click on the open area's icon opens the drawer; the same for a
//   person without an organisation; a phone is unchanged
// - Firefox 940 x 700 and 1024 x 768 (also with the font at 130 %), mouse and touch: the project names in the panel are
//   readable (not bare symbols), with a task open the panel is folded, the bar stays, the list's titles get the width (the
//   date under the title, no column next to it), the task header's close button sits in the first row; 1400 x 900 keeps
//   panel | list | task and the cells as columns. Screenshots with P2290C_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2290_c_fold_ui', check, shots: 'P2290C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const width = (w, px) => Object.defineProperty(w, 'innerWidth', {configurable: true, value: px});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const NAME = 'Website relaunch';
const LONG = 'Decide about the new landing page copy and the pricing table for the spring campaign';

async function seed(ck) {
  const L = (await call(ck, 'POST', '/api/lists', {name: NAME, kind: 'project'})).id;
  await call(ck, 'PATCH', `/api/lists/${L}`, {columns: ['id', 'due', 'created']});  // own columns: number, date, created (like the Fold screenshot)
  const T = (await call(ck, 'POST', '/api/tasks', {title: LONG, list_id: L, due: '2027-01-14'})).id;
  for (const t of ['Renew the CI token before it runs out', 'Trademark: deadlines after the filing', 'Short one']) await call(ck, 'POST', '/api/tasks', {title: t, list_id: L, due: '2027-03-31'});
  return {L, T};
}

async function jsd(user, {L, T}, tag) {
  let w = await boot({user, hash: 'l/' + L, setup: x => width(x, 940)}), d = w.document;
  const app = () => d.querySelector('#app');
  await until(() => d.querySelector(`#view .trow[data-id="${T}"]`));
  check(app().classList.contains('sb-b') && !app().classList.contains('side-rail'), `${tag} 940: no task open: bar + panel`);
  w.eval(`openDetail(${T})`); await until(() => app().classList.contains('detail-open'));
  w.eval('fitLayout()');
  check(app().classList.contains('side-rail') && !w.__store['tasks.sideFold'], `${tag} 940 + task: the panel folds into the drawer (not remembered as hidden)`);
  click(w, d.querySelector('#srail .srb.on[data-sbb]'));
  check(await until(() => d.querySelector('#side.open')), `${tag} 940 + task: a click on the open area's icon opens the drawer`);
  w.eval('closeSide()');
  w.eval('closeDetail()'); w.eval('fitLayout()');
  check(await until(() => !app().classList.contains('side-rail')), `${tag} 940: closing the task brings the panel back`);
  width(w, 1024); w.eval(`openDetail(${T})`); w.eval('fitLayout()');
  check(app().classList.contains('side-rail'), `${tag} 1024 + task: folded too`);
  width(w, 1400); w.eval('fitLayout()');
  check(!app().classList.contains('side-rail'), `${tag} 1400 + task: panel | list | task as before`);
  check(!errs.length, `${tag}: no script errors ` + errs.join(' | ')); errs.splice(0);
  w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.status < 300, 'a person without organisation ' + fu.status);
  const CF = await login('frida');
  for (const ck of [CA, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const A = await seed(CA), FR = await seed(CF);

  // ================= jsdom
  await jsd('alice', A, 'computer');
  await jsd('frida', FR, 'without organisation');
  let w = await boot({user: 'alice', hash: 'l/' + A.L, mobile: true}), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${A.T}"]`));
  w.eval(`openDetail(${A.T})`); await sleep(300);
  check(!d.querySelector('#app.sb-b') && !d.querySelector('#app.side-rail'), 'phone: unchanged (no bar, no drawer class)');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, user, fs) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); ${fs ? `localStorage.setItem('tasks.fsize', '${fs}'); localStorage.setItem('tasks.lookLocal', 'true');` : ''} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const M = T => `(() => { const R = e => { if (!e || !e.getClientRects().length || getComputedStyle(e).display === 'none' || getComputedStyle(e).visibility === 'hidden') return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), t: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height), cy: Math.round(b.top + b.height / 2)}; };
    const app = document.querySelector('#app'), row = document.querySelector('#view .trow[data-id="${T}"]'), sr = [...document.querySelectorAll('#side .srow')].find(r => r.querySelector('.n')?.textContent.trim() === ${JSON.stringify(NAME)});
    const lh = parseFloat(getComputedStyle(row?.querySelector('.ttl') || document.body).lineHeight) || 20;
    return {rail: app.classList.contains('side-rail'), srail: R(document.querySelector('#srail')), side: R(document.querySelector('#side')), sideOpen: document.querySelector('#side').classList.contains('open'),
      name: R(sr?.querySelector('.n')), sbbpt: R(document.querySelector('#side .sbhead .sbbpt')), ttl: R(row?.querySelector('.ttl')), lines: row ? Math.round(R(row.querySelector('.ttl'))?.h / lh) : 0, lcols: R(row?.querySelector('.lcols')), due: R(row?.querySelector('.meta .mlc.o0[data-lc="due"]')),
      det: R(document.querySelector('#detail')), x: R(document.querySelector('#detail .dtop > .dclose')), chk: R(document.querySelector('#detail .dtop > .chk')), more: R(document.querySelector('#detail .dtop [data-act="task-menu"]')),
      tools: [...document.querySelectorAll('#side .sbhead .sbtools .iconbtn')].filter(e => e.offsetWidth).map(e => { const sd = document.querySelector('#side'); return [e.getBoundingClientRect(), sd.getBoundingClientRect().left + sd.clientLeft + sd.clientWidth]; }).filter(([b, r]) => b.right > r + 1 || b.width < 24).map(([b]) => Math.round(b.left)),
      over: document.documentElement.scrollWidth - innerWidth}; })()`;
  const run = async ({cmd, ev, nav, ctx, shot}, {L, T}, tag, sizes, fs) => {
    for (const [vw, vh] of sizes) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await ev(`(() => { localStorage.removeItem('tasks.sideFold'); return 1; })()`);  // each size starts with the panel shown
      await nav(B + '?v=' + vw + (fs || '') + '#l/' + L);
      await until(() => ev(`!!document.querySelector('#view .trow[data-id="${T}"]')`).catch(() => false)); await sleep(500);
      const k = `${tag} ${vw}x${vh}${fs ? ' font ' + fs + ' %' : ''}`;
      if (fs) check(await ev(`Math.round(parseFloat(getComputedStyle(document.documentElement).fontSize))`) === Math.round(16 * fs / 100), `${k}: the larger font is on`);
      const a = await ev(M(T));
      check(!a.rail && a.side && a.name && a.name.w >= 60, `${k}: no task open: the project names are readable in the panel ` + JSON.stringify({side: a.side, name: a.name}));
      if (vw < 1200) check(!a.sbbpt || a.sbbpt.w >= 60, `${k}: the panel's title is readable ` + JSON.stringify(a.sbbpt));
      if (vw < 1200) check(!a.tools.length, `${k}: the panel head's buttons are not cut ` + JSON.stringify(a.tools));
      await shot(`p2290c-${tag.replace(/\W+/g, '')}-${vw}${fs ? '-fs' + fs : ''}-list.png`);
      await ev(`(() => { openDetail(${T}); return 1; })()`);
      await until(() => ev(`!!document.querySelector('#app.detail-open #detail .dtop')`)); await sleep(700);
      const b = await ev(M(T));
      if (vw < 1200) {
        check(b.rail && b.srail && b.srail.w > 0 && !b.sideOpen && b.det && b.over <= 0, `${k} + task: the panel folded into the drawer, the bar stays, nothing scrolls sideways ` + JSON.stringify({rail: b.rail, srail: b.srail, det: b.det, over: b.over}));
        check(b.ttl && b.ttl.w >= (fs ? 180 : 200) && b.lines <= (fs ? 4 : 3), `${k} + task: the title gets the width (>= 200 px / 180 px with the larger font, at most 3 / 4 lines; before: 0-174 px, up to 70 lines) ` + JSON.stringify({ttl: b.ttl, lines: b.lines}));
        check(!b.lcols && b.due && b.due.t >= b.ttl.t + b.ttl.h - 2, `${k} + task: the date under the title, no column next to it ` + JSON.stringify({lcols: b.lcols, due: b.due, ttl: b.ttl}));
      } else {
        check(!b.rail && b.side && b.lcols && !b.due && b.over <= 0, `${k} + task: panel | list | task and the cells as columns, as before ` + JSON.stringify({rail: b.rail, side: b.side, lcols: b.lcols, due: b.due}));
      }
      check(b.x && b.chk && Math.abs(b.x.cy - b.chk.cy) <= 4 && b.x.l + b.x.w >= b.det.l + b.det.w - 32, `${k} + task: the close button in the header's first row at the right ` + JSON.stringify({x: b.x, chk: b.chk, more: b.more}));
      check(!b.more || !b.x || b.more.l + b.more.w <= b.x.l + 1 || b.more.t >= b.x.t + b.x.h - 1, `${k} + task: nothing in the header covers the close button ` + JSON.stringify({x: b.x, more: b.more}));
      await shot(`p2290c-${tag.replace(/\W+/g, '')}-${vw}${fs ? '-fs' + fs : ''}-task.png`);
      if (vw < 1200) {
        await ev(`(() => { document.querySelector('#srail .srpanel')?.click(); return 1; })()`);
        check(await until(() => ev(`document.querySelector('#side').classList.contains('open')`)), `${k} + task: the bar's panel button opens the drawer`);
        await ev(`(() => { closeSide(); return 1; })()`); await sleep(300);
      }
      await ev(`(() => { closeDetail(); return 1; })()`); await sleep(400);
    }
  };
  for (const [touch, fs] of [[false, 0], [false, 130], [true, 0], [true, 130]]) {
    await firefox(async x => {
      check(await ffLogin(x, 'alice', fs) === 200, 'Firefox: login');
      await run(x, A, touch ? 'touch' : 'mouse', fs ? [[940, 700], [1024, 768]] : [[940, 700], [1024, 768], [1400, 900]], fs);
      if (!touch && !fs) {  // the same for a person without an organisation
        check(await ffLogin(x, 'frida') === 200, 'Firefox: login frida');
        await run(x, FR, 'without organisation', [[940, 700]]);
      }
    }, touch);
  }

  console.log(`p2290_c_fold_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
