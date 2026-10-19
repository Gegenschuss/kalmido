// 2.103.0 UI tests, part C (#2169): the closed logbook, own container (start.sh, mode workspaces), Firefox (desktop + phone
// width). Invented companies, people and figures only.
// - the drives bar has "Close month"; its dialog offers the months of the year that are still open
// - a drive of a closed month opens read-only: the closing note, its change log right in the dialog, no delete, "Correct"
// - "Correct" opens a new entry prefilled with the old values and a reason field; saved, the list marks both drives
// - on a phone nothing sticks out to the side (list and dialog)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2103_c_ui', check, shots: 'P2103C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2103C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const today = new Date().toISOString().slice(0, 10);
  const veh = await call(CA, 'POST', '/api/office/vehicles', {name: 'Kombi', kind: 'private', odo_start: '1000'});
  const drv = await call(CA, 'POST', '/api/office/drives', {vehicle_id: veh.id, day: today, start_place: 'Hamburg', dest: 'Lübeck', purpose: 'Dreh', km: 70, kind: 'business'});
  await call(CA, 'PATCH', `/api/office/drives/${drv.id}`, {purpose: 'Dreh Imagefilm'});
  const cl = await call(CA, 'POST', '/api/office/logbook/close', {month: today.slice(0, 7), vehicle_id: veh.id});
  check(cl.http === 200, 'the month closed through the API ' + cl.http);
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *, .modal *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/travel');
    check(await ready(ev, `!!document.querySelector('[data-rk="view"][data-v="logbook"]')`, 80), 'the travel tab has the logbook');
    await ev(`(() => { document.querySelector('[data-rk="view"][data-v="logbook"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.lgb-list .lgb-row').length === 1`), 'the drive is in the list');
    check(await ev(`!!document.querySelector('.lgb-bar [data-lgb="close"]')`), '#2169: the bar has "Close month"');
    // the close dialog: the closed month is not offered again
    await ev(`(() => { document.querySelector('[data-lgb="close"]').click(); return 1; })()`);
    if (await ready(ev, `!!document.querySelector('.modal #lgb-cm')`, 12)) {
      check(await ev(`![...document.querySelectorAll('.modal #lgb-cm option')].some(o => o.value === '${today.slice(0, 7)}')`), '#2169: the closed month is not offered again');
      check(await ev(`!!document.querySelector('.modal #lgb-cv option[value="all"]')`), '#2169: one vehicle or all vehicles');
      await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    } else check(/closed already/.test(await ev(`document.body.textContent`)), '#2169: every month closed: a note instead of the dialog');
    await ready(ev, `!document.querySelector('.modal')`, 8);
    // the closed drive
    await ev(`(() => { document.querySelector('.lgb-list .lgb-row').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .lgb-lock')`), '#2169: a drive of a closed month opens with the closing note');
    check(await ready(ev, `document.querySelectorAll('.modal .lgb-hist .lgb-hlist li').length === 2 && /Changed/.test(document.querySelector('.modal .lgb-hist').textContent) && /Created/.test(document.querySelector('.modal .lgb-hist').textContent)`),
      '#2169: the change log is shown right in the dialog (created, changed) ' + await ev(`document.querySelector('.modal .lgb-hist')?.textContent`));
    check(await ev(`/Before/.test(document.querySelector('.modal .lgb-hist').textContent) && /Dreh/.test(document.querySelector('.modal .lgb-hist').textContent)`), '#2169: ... with the values before');
    check(await ev(`!document.querySelector('.modal [data-m="del"]') && !document.querySelector('.modal [data-m="save"]') && document.querySelector('.modal #lgb-dest').disabled`), '#2169: read-only: no delete, no save, fields locked');
    check(await ev(`!!document.querySelector('.modal [data-m="fix"]')`), '#2169: the button "Correct"');
    await shot('p2103-c-closed-drive.png');
    await ev(`(() => { document.querySelector('.modal [data-m="fix"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #lgb-fixnote') && document.querySelector('.modal #lgb-dest').value === 'Lübeck' && !document.querySelector('.modal #lgb-dest').disabled`),
      '#2169: the correction: a new entry with the old values and a reason field');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#lgb-dest').value = 'Lübeck Nord'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `/reason/.test(document.querySelector('.modal .aerr')?.textContent || '')`, 12), '#2169: without a reason the correction is not saved');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#lgb-fixnote').value = 'Falsches Ziel'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.lgb-list .lgb-row').length === 2`), '#2169: the correction is saved, the old drive stays');
    const txt = await ev(`document.querySelector('.lgb-list').textContent`);
    check(/Corrected/.test(txt) && /Correction/.test(txt), '#2169: the list marks the corrected drive and the correction ' + txt.slice(0, 200));
    await shot('p2103-c-logbook.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the drives stay inside the screen');
    await ev(`(() => { [...document.querySelectorAll('.lgb-list .lgb-row')].find(b => /Corrected/.test(b.textContent)).click(); return 1; })()`);
    check(await ready(ev, `/Corrected by entry/.test(document.querySelector('.modal .lgb-lock')?.textContent || '')`), '#2169: the corrected drive names its correction');
    check(await ev(noSide), 'on a phone the dialog stays inside the screen');
    await shot('p2103-c-closed-phone.png');
  }, false);

  console.log(`p2103_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
