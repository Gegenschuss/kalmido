// 2.490.0 (#4032) swipe to the left closes the sidebar (tablet panel beside the content, the drawer, the phone's drawer)
// own container (start.sh, isolated test database). freelancer-matrix: tasks
// - jsdom: swipe left > 1/3 of the width closes (panel: folded and remembered like the button; drawer: closeSide), a short
//   swipe keeps it open and the panel snaps back, a vertical move / a swipe to the right / a second finger do nothing,
//   the same for a person without an organisation
// - app.css: the rail's show / hide button is position: sticky (stays while the rail scrolls); 2.542.0 (#4610): the button is gone, no rule for it left
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const width = (w, px) => Object.defineProperty(w, 'innerWidth', {configurable: true, value: px});

// touch events with a touch list (jsdom has no TouchEvent)
const tev = (w, el, type, pts) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = pts.map(([x, y]) => ({clientX: x, clientY: y, target: el})); el.dispatchEvent(e); return e; };
const swipe = (w, el, dx, dy = 0, extra = false) => {
  tev(w, el, 'touchstart', [[200, 300]].concat(extra ? [[250, 300]] : []));
  tev(w, el, 'touchmove', [[200 + dx, 300 + dy]].concat(extra ? [[250, 300]] : []));
  tev(w, el, 'touchend', []);
};

async function jsd(user, L, tag, mobile) {
  const w = await boot({user, hash: 'l/' + L, mobile, setup: x => width(x, mobile ? 390 : 940)}), d = w.document;
  await until(() => d.querySelector('#side .srow'));
  const side = d.querySelector('#side'), pick = () => d.querySelector('#side .srow') || side; let item = pick();
  side.getBoundingClientRect = () => ({left: 0, top: 0, width: 270, height: 600, right: 270, bottom: 600});
  const open = () => side.classList.contains('open'), folded = () => !!w.__store['tasks.sideFold'];
  check(!errs.length, `${tag}: boots without errors ` + errs.join(' | ')); errs.splice(0);

  if (!mobile) {
    check(d.querySelector('#app.sb-b') && !d.querySelector('#app.side-rail') && !folded(), `${tag}: panel beside the content`);
    swipe(w, item, -30); check(!folded(), `${tag}: a short swipe (< 1/3) keeps the panel`);
    check(side.style.transform === '', `${tag}: ... and it snapped back`);
    swipe(w, item, -5, -80); swipe(w, item, -60, 100); swipe(w, item, 120); swipe(w, item, -150, 0, true);
    check(!folded(), `${tag}: vertical, right and two-finger moves do nothing`);
    tev(w, item, 'touchstart', [[200, 300]]); const m = tev(w, item, 'touchmove', [[150, 302]]);
    check(side.style.transform.includes('-50') && m.defaultPrevented, `${tag}: the panel follows the finger`);
    tev(w, item, 'touchend', []);
    swipe(w, item, -120);
    check(await until(() => folded()), `${tag}: a swipe > 1/3 hides the panel (remembered as the button does)`);
    w.eval('sideFold(false)');
    // the drawer (task open = side-rail)
    width(w, 940); w.eval(`openDetail(${d.querySelector('#view .trow')?.dataset.id || 0})`); await sleep(300);
  }
  w.eval('fitLayout()');
  if (mobile || d.querySelector('#app.side-rail')) {
    item = pick(); w.eval('sideDrawerOpen()'); item = pick(); check(open(), `${tag}: drawer open`);
    swipe(w, item, -30); check(open(), `${tag}: drawer: a short swipe keeps it open`);
    swipe(w, item, 0, 90); check(open(), `${tag}: drawer: vertical scrolling keeps it open`);
    swipe(w, item, -120); check(!open(), `${tag}: drawer: a swipe > 1/3 closes it`);
  }
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
  const LA = (await call(CA, 'POST', '/api/lists', {name: 'Alpha', kind: 'project'})).id, LF = (await call(CF, 'POST', '/api/lists', {name: 'Beta', kind: 'project'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'One', list_id: LA}); await call(CF, 'POST', '/api/tasks', {title: 'One', list_id: LF});
  await jsd('alice', LA, 'tablet', false);
  await jsd('frida', LF, 'tablet without organisation', false);
  await jsd('alice', LA, 'phone', true);
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(!/srpanel/.test(css), '#4610: app.css: no rule for the removed panel button of the rail');  // 2.542.0 (#4610): was "the rail button is sticky"
  console.log(`p4032_swipe_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
