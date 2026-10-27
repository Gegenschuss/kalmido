// 2.224.0 A (#2817) one navigation, own container (start.sh), jsdom.
// - a computer: the calendar has no panel any more, its views are only the tabs on top (they still switch); Habits, Time and
//   Review have no panel either (the bar stays, the page takes the width), their parts are the tabs on top (Time 2, Review 2,
//   Habits none); a part hidden in Settings > Appearance > Sidebar is no tab; Home keeps its panel
// - no button to show a panel there, a click on the lit icon does not unfold a folded panel elsewhere
// - a phone: unchanged (the drawer keeps the calendar views and the parts, the tabs stay)
// - the same for a person without an organisation
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,events,timeline,habits,pomo,collab,stats,time,review,family,home,agents,comments';

async function desktop(user, tag) {
  let w = await boot({user, hash: 'cal'}), d = w.document;
  const app = () => d.querySelector('#app'), tabs = () => [...d.querySelectorAll('#view .mgtabs [data-go]')].map(b => b.dataset.go + (b.getAttribute('aria-selected') === 'true' ? '*' : '')).join();
  // ================= the calendar
  await until(() => d.querySelector('.calbar .seg [data-k="week"]'));
  check(app().classList.contains('sb-b') && app().classList.contains('sbb-nopan') && d.querySelector('#srail [data-sbb="cal"].on'), `${tag}: the calendar: the bar, no panel`);
  check(!d.querySelector('#side [data-sbbcal], #side [data-act="cal-mode"]') && w.eval(`sbb_panelHtml('cal')`) === '', `${tag}: no view rows in the panel`);
  check(!d.querySelector('#srail .srpanel'), `${tag}: no button to show a panel`);
  click(w, d.querySelector('.calbar .seg [data-k="week"]'));
  check(await until(() => w.eval('S.calMode') === 'week' && d.querySelector('.calbar .seg button.on[data-k="week"]')), `${tag}: a view tab on top switches the view`);
  click(w, d.querySelector('.calbar .seg [data-k="month"]'));
  await until(() => w.eval('S.calMode') === 'month');
  check(!!d.querySelector('.calbar [data-act="ev-cals"]'), `${tag}: the Calendars window stays reachable in the head`);
  // ================= Time: two tabs, no panel
  w.eval(`go('time')`); await until(() => w.eval('S.route.mod') === 'time' && d.querySelector('#view .mgtabs'));
  check(tabs() === 'time*,pomo' && app().classList.contains('sbb-nopan') && !d.querySelector('#side [data-sbbpart]'), `${tag}: Time: tabs Time tracking + Focus timer, no panel ` + tabs());
  check(d.querySelector('#top h1')?.textContent === 'Time tracking', `${tag}: the header names the page ` + d.querySelector('#top h1')?.textContent);
  click(w, d.querySelector('#view .mgtabs [data-go="pomo"]'));
  check(await until(() => w.eval('S.route.mod') === 'pomo' && tabs() === 'time,pomo*') && d.querySelector('#srail [data-sbb="time"].on'), `${tag}: the tab opens the focus timer, the icon stays lit ` + tabs());
  // ================= Review: two tabs
  w.eval(`go('review')`); await until(() => w.eval('S.route.mod') === 'review' && d.querySelector('#view .mgtabs'));
  check(tabs() === 'review*,stats' && app().classList.contains('sbb-nopan'), `${tag}: Review: tabs Review & journal + Statistics ` + tabs());
  // ================= Habits: one entry, no tabs, no panel
  w.eval(`go('habits')`); await until(() => w.eval('S.route.mod') === 'habits');
  await sleep(200);
  check(!d.querySelector('#view .mgtabs') && app().classList.contains('sbb-nopan') && !d.querySelector('#side .sbbi'), `${tag}: Habits: no tabs, no panel`);
  // ================= Home keeps its panel
  w.eval(`go('life')`); await until(() => w.eval('S.route.mod') === 'life' && d.querySelector('#side [data-sbbpart]'));
  check(!app().classList.contains('sbb-nopan') && d.querySelector('#side [data-sbbpart="life"][aria-current="page"]') && !d.querySelector('#view .mgtabs'), `${tag}: Home keeps its panel, no tabs`);
  // ================= a folded panel: the lit icon of an area without a panel does not unfold it, the layout has no rail
  w.eval(`LS.set('sideFold', true); fitLayout(); go('time')`); await until(() => w.eval('S.route.mod') === 'time');
  await sleep(200);
  check(!app().classList.contains('side-rail') && !d.querySelector('#srail .srpanel'), `${tag}: folded elsewhere: Time has no rail and no show button`);
  click(w, d.querySelector('#srail [data-sbb="time"].on')); await sleep(200);
  check(w.eval(`LS.get('sideFold', false)`) === true, `${tag}: the lit icon leaves the fold as it is`);
  w.eval(`LS.set('sideFold', false); fitLayout(); render()`);
  check(!errs.length, `${tag}: no script errors ` + errs.join(' | ')); errs.splice(0);
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

  await desktop('alice', 'computer');
  await desktop('frida', 'without organisation');

  // ================= a part hidden in Settings > Appearance > Sidebar is no tab (the open one stays)
  await call(CA, 'PATCH', '/api/settings', {sidebar: JSON.stringify({hidden: ['e:stats']})});
  let w = await boot({user: 'alice', hash: 'review'}), d = w.document;
  await until(() => w.eval('S.route.mod') === 'review'); await sleep(300);
  check(!d.querySelector('#view .mgtabs [data-go="stats"]') && !d.querySelector('#view .mgtabs'), 'Statistics hidden: no tab row on Review');
  w.eval(`go('stats')`); await until(() => w.eval('S.route.mod') === 'stats'); await sleep(200);
  check(!!d.querySelector('#view .mgtabs [data-go="stats"][aria-selected="true"]'), 'an old link to the hidden part still shows its tab');
  w.close();
  await call(CA, 'PATCH', '/api/settings', {sidebar: JSON.stringify({hidden: []})});

  // ================= a phone: unchanged
  w = await boot({user: 'alice', hash: 'time', mobile: true}); d = w.document;
  await until(() => d.querySelector('#view .mgtabs'));
  check(!d.querySelector('#app.sb-b') && !d.querySelector('#app.sbb-nopan') && d.querySelectorAll('#view .mgtabs [data-go]').length === 2, 'phone: no bar, the tabs of Time stay');
  check(/data-sbbcal="week"/.test(w.eval(`sbb_panelHtml('cal')`)) && /data-sbbpart="pomo"/.test(w.eval(`sbb_panelHtml('time')`)), 'phone: the drawer keeps the calendar views and the parts');
  check(!errs.length, 'phone: no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  console.log(`p2224_a_nav_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
