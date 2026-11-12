// kalmido-suite: fresh
// 2.1011.0 (#5691): the menus of the time tracking (Export, the running indicator) are the shared menu(): role="menu", an anchor
// button with aria-haspopup, an entry focused, Escape closes, the phone shows a sheet with a title. Used like a person: open,
// see the entries, pick one -> the effect (a download is started / the timesheet opens / a pause arrives on the server).
// freelancer-matrix: time (alice signs up alone, without an organisation)
const {boot, sleep, errs, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'time,pomo';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const P = (await call('POST', '/api/lists', {name: 'Client work', kind: 'project', time_tracking: true})).id;
  const t = (await call('POST', '/api/tasks', {title: 'Write the offer', list_id: P})).id;

  const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];
  const labels = d => items(d).map(b => b.textContent.trim());
  const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
  // opens the menu of an anchor and checks the shared form: role=menu, anchor says haspopup, an entry has the focus
  const open = async (w, sel, what) => {
    const d = w.document, a = await until(() => d.querySelector(sel));
    check(a && a.getAttribute('aria-haspopup') === 'menu', `${what}: the anchor button says aria-haspopup=menu`);
    click(w, a); await until(() => d.querySelector('#pop:not(.hidden) [role="menu"] [role="menuitem"]'));
    check(items(d).length > 0 && d.querySelector('#pop [role="menu"]'), `${what}: the menu opens as role=menu`);
    await until(() => d.activeElement && d.activeElement.closest('#pop'));
    check(d.activeElement.closest('#pop'), `${what}: an entry has the focus`);
    return a;
  };
  const escCloses = async (w, what) => { const d = w.document; key(w, d.activeElement, 'Escape'); check(await until(() => d.querySelector('#pop.hidden') || !d.querySelector('#pop [role="menu"]')), `${what}: Escape closes the menu`); };

  // ================= time tracking: Export
  let w = await boot({user: 'alice', hash: 'time'}); let d = w.document;
  await until(() => d.querySelector('.timev [data-act="tv-export"]'));
  const ex = d.querySelector('.timev [data-act="tv-export"]'); click(w, ex);
  await until(() => d.querySelector('#pop [role="menu"] [role="menuitem"]'));
  check(labels(d).length === 3 && labels(d)[0] === 'CSV' && !d.querySelector('#pop a'), 'time export: three entries (buttons) ' + labels(d).join('|'));
  check(items(d)[0].querySelector('svg, .i'), 'time export: the entries have an icon');
  await until(() => d.activeElement && d.activeElement.closest('#pop'));
  await escCloses(w, 'time export');
  click(w, ex); await until(() => d.querySelector('#pop [role="menu"] [role="menuitem"]'));
  let href = ''; const ac2 = w.HTMLAnchorElement.prototype.click; w.HTMLAnchorElement.prototype.click = function () { href = this.getAttribute('href'); };
  click(w, items(d).find(b => /Excel/.test(b.textContent)));
  check(await until(() => /^\/api\/time\/export\.xlsx\?/.test(href)), 'time export: "Excel" starts the download ' + href);
  w.HTMLAnchorElement.prototype.click = ac2;
  w.close();

  // ================= running: one group per running thing, the time ticks in the group head, Pause arrives on the server
  await call('POST', '/api/time/start', {task_id: t});
  await call('POST', '/api/pomo/start', {kind: 'focus', minutes: 25, task_id: t});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  const chip = await until(() => d.querySelector('#top .tmini.run'));
  click(w, chip); await until(() => d.querySelector('#pop [role="menu"] [role="group"]'));
  const gr = [...d.querySelectorAll('#pop [role="group"]')];
  check(gr.length === 2 && /Time tracking/.test(gr[0].textContent) && /Focus session/.test(gr[1].textContent), 'running: a group per running thing, with its kind in the head');
  check(d.querySelector('#pop .mgh [data-timer-mini]') && d.querySelector('#pop .mgh [data-pomo-mini]'), 'running: the time sits in the group head (data-timer-mini / data-pomo-mini)');
  check(/Write the offer/.test(gr[0].textContent) && labels(d).includes('Stop timer') && labels(d).includes('Pause') && labels(d).includes('Stop focus session'), 'running: task, Stop timer, Pause, Stop focus session ' + labels(d).join('|'));
  await escCloses(w, 'running');
  click(w, chip); await until(() => d.querySelector('#pop [role="menu"] [role="menuitem"]'));
  click(w, items(d).find(b => b.textContent.trim() === 'Pause'));
  check(await until(async () => !!(await call('GET', '/api/state')).pomo?.paused_at), 'running: "Pause" pauses the focus session on the server');
  w.close();

  // ================= phone: a sheet with a title, the timesheet opens from it
  w = await boot({user: 'alice', mobile: true, hash: 'time'}); d = w.document;
  await until(() => w.eval('!!(S.tv && S.tv.data)'));  // the timesheet entry needs the loaded period
  await open(w, '.timev [data-act="tv-export"]', 'time export on the phone');
  check(d.querySelector('#pop .tch-sh .tch-sht') && /Export/.test(d.querySelector('#pop .tch-sht').textContent) && d.querySelector('#pop .tch-shx'), 'phone: the menu is a sheet with the title Export and an X');
  await until(() => d.querySelector('#pop [data-act="tvx-sheet"]:not([disabled])'));
  click(w, d.querySelector('#pop [data-act="tvx-sheet"]'));
  check(await until(() => d.querySelector('.tsheet h1')), 'phone: "Timesheet" opens the timesheet');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
