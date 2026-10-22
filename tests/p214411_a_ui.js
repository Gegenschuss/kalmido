// 2.144.11 UI tests, part A (#2354, review N5): the cash book tab recovers from a failed load, own container (start.sh), Firefox.
// Invented names and figures only.
// - the first load of the cash book fails (500): the tab shows the error and a "Try again" button
// - "Try again" (the server back) loads the cash book with its quick entry; a later booking works as before
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p214411_a_ui', check, shots: 'P214411A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';

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
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#side [data-ofm="cashbook"]')`, 80), 'the office with the menu entry "Cash book"');  // 2.152.2 (#2617): the office points sit in the panel #side
    // the server answers 500 for the cash book (a short failure)
    await ev(`(() => { const f0 = window.fetch; window.__cbFail = true; window.fetch = (u, o) => (window.__cbFail && String(u).includes('/api/office/cashbooks')) ? Promise.resolve(new Response(JSON.stringify({error: 'Server error'}), {status: 500, headers: {'Content-Type': 'application/json'}})) : f0(u, o); return 1; })()`);
    await ev(`(() => { document.querySelector('#side [data-ofm="cashbook"]').click(); return 1; })()`);  // 2.152.2 (#2617): the office points sit in the panel #side
    check(await ready(ev, `!!document.querySelector('.ofcbody [data-cb="retry"]') && !document.querySelector('#cb-quick')`), 'a failed load: the error with "Try again"');
    await shot('p214411-a-error.png');
    await ev(`(() => { window.__cbFail = false; document.querySelector('[data-cb="retry"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#cb-quick') && !document.querySelector('[data-cb="retry"]')`), '"Try again": the cash book loads');
    await ev(`(() => { document.querySelector('[data-cb="dir"][data-v="in"]').click(); const f = document.querySelector('#cb-quick');
      f.querySelector('#cb-amount').value = '12'; f.querySelector('#cb-text').value = 'Verkauf'; f.querySelector('.cb-go').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.cb-list .cb-row').length === 1`), 'a booking afterwards works');
  });
  console.log(`p214411_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
