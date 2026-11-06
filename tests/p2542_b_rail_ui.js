// 2.542.0 UI test, part B (#4610): the bar of the areas has no button "Show the panel" any more, a change of the area opens the
// kalmido-suite: fresh
// panel again. Own container (start.sh), jsdom, a computer (1280 px).
// - hidden or shown, with or without a panel: the bar's first icon is the first area, Start (no button above it), nothing to skip
//   for the arrow keys
// - hidden in Tasks: a click on another area's icon opens the panel (LS sideFold false, no rail); go() to another area too
// - a tap on the open area's icon brings a hidden panel back (as before); a click on the open area does not unfold by itself
// - a reload keeps the hidden panel (per device); an area without a panel (Time) stays without one
// - the same for a person without an organisation
// freelancer-matrix: tasks
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,events,timeline,habits,pomo,collab,stats,time,review,family,home,agents,comments';

async function desktop(user, L, tag) {
  let w = await boot({user, hash: 'l/' + L}), d = w.document;
  const app = () => d.querySelector('#app'), fold = () => w.eval(`LS.get('sideFold', false)`);
  const first = () => d.querySelector('#srail .srbs')?.firstElementChild;
  const shown = () => !app().classList.contains('side-rail') && fold() === false;
  Object.defineProperty(w, 'innerWidth', {configurable: true, value: 1280}); w.eval('fitLayout()');
  await until(() => d.querySelector('#side .sbbhide') && d.querySelector('#srail [data-sbb="tasks"].on'));
  check(!d.querySelector('#srail .srpanel') && first()?.dataset.sbb === 'home', `${tag}: shown: no panel button, the first icon is Start`);
  // hide in Tasks
  click(w, d.querySelector('#side .sbbhide'));
  check(await until(() => fold() === true && app().classList.contains('side-rail')), `${tag}: Hide the panel hides it`);
  check(!d.querySelector('#srail .srpanel') && first()?.dataset.sbb === 'home', `${tag}: hidden: still no button above the icons, Start stays first`);
  check(w.eval(`sbb_railItems().length`) === d.querySelectorAll('#srail .srb').length && w.eval(`sbb_railItems()[0].dataset.sbb`) === 'home', `${tag}: the arrow keys walk the area icons only`);
  // the open area's icon brings it back
  click(w, d.querySelector('#srail .srb.on[data-sbb]'));
  check(await until(() => shown()), `${tag}: a tap on the open area's icon brings the panel back`);
  // hidden again, then another area: open again
  click(w, d.querySelector('#side .sbbhide')); await until(() => fold() === true);
  click(w, d.querySelector('#srail [data-sbb="life"]'));
  check(await until(() => w.eval('sbb_area()') === 'life' && shown() && d.querySelector('#side [data-sbbpart]')), `${tag}: #4610: a click on another area opens the panel there`);
  // hidden in Home, go() to Tasks (a link, a key): open again
  click(w, d.querySelector('#side .sbbhide')); await until(() => fold() === true);
  w.eval(`go('today')`);
  check(await until(() => w.eval('sbb_area()') === 'tasks' && shown() && d.querySelector('#side .sbbhide')), `${tag}: #4610: any way into another area opens the panel`);
  // a redraw in the same area leaves a hidden panel hidden
  click(w, d.querySelector('#side .sbbhide')); await until(() => fold() === true);
  w.eval('render()'); await sleep(200);
  check(fold() === true && app().classList.contains('side-rail'), `${tag}: a redraw of the same area keeps it hidden`);
  // an area without a panel: the bar, no panel, nothing to show
  w.eval(`go('time')`); await until(() => w.eval('S.route.mod') === 'time');
  check(app().classList.contains('sbb-nopan') && !app().classList.contains('side-rail') && !d.querySelector('#srail .srpanel') && first()?.dataset.sbb === 'home', `${tag}: Time: no panel, the icons where they were`);
  check(!errs.length, `${tag}: no script errors ` + errs.join(' | ')); errs.splice(0);
  w.close();
  // a reload keeps a hidden panel (the first drawing is no change of the area)
  w = await boot({user, hash: 'l/' + L, ls: {'tasks.sideFold': 'true'}}); d = w.document;
  Object.defineProperty(w, 'innerWidth', {configurable: true, value: 1280}); w.eval('fitLayout()');
  await until(() => d.querySelector('#srail [data-sbb="tasks"].on'));
  await sleep(300);
  check(w.eval(`LS.get('sideFold', false)`) === true && d.querySelector('#app').classList.contains('side-rail'), `${tag}: a reload keeps the hidden panel`);
  check(!errs.length, `${tag}: no script errors after the reload ` + errs.join(' | ')); errs.splice(0);
  w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.status < 300, 'a person without organisation ' + fu.status);
  const CF = await login('frida');
  for (const ck of [CA, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const LA = (await call(CA, 'POST', '/api/lists', {name: 'Alpha', kind: 'project'})).id, LF = (await call(CF, 'POST', '/api/lists', {name: 'Beta', kind: 'project'})).id;
  await desktop('alice', LA, 'computer');
  await desktop('frida', LF, 'without organisation');
  console.log(`p2542_b_rail_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
