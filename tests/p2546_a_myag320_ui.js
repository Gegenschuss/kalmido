// kalmido-suite: fresh
// 2.546.0 (#4491) Settings > Agents > Set up on a phone at 320 px: the three fields of a new personal agent (display name, username,
// where it runs) stand one below the other at full width, the "Create agent" button under them (before: side by side, a letter wide).
// Own container (start.sh), Firefox at 320 x 640 (touch); a second look at 1024 px keeps them on one row there. Invented data only.
// freelancer-matrix: agents - frida has no organisation: the place is checked as her.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2546_a_myag320_ui', check, shots: 'P2546A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

// the boxes of the three fields and the button
const BOX = `(() => { const r = document.querySelector('.row.myagnew'); if (!r) return null;
  const b = e => { const x = e.getBoundingClientRect(); return {l: Math.round(x.left), r: Math.round(x.right), t: Math.round(x.top), bt: Math.round(x.bottom), w: Math.round(x.width)}; };
  return {vw: innerWidth, row: b(r), f: ['#myag-name', '#myag-user', '#myag-prov'].map(s => b(r.querySelector(s))), btn: b(r.querySelector('[data-myag-act="new"]'))}; })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'de', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: 'cal,comments,agents'});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'P4: frida is in no organisation');

  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const open = async () => {
      await nav(B + '#today');
      check(await ready(`typeof settingsModal === 'function' && typeof S !== 'undefined' && !!S.me`), 'the app is up');
      await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('ai'); return 1; })()`);
      check(await ready(`!!document.querySelector('.smodal')`), 'settings open');
      await ev(`(async () => { await aiSubShow(document.querySelector('.smodal'), 'setup', false); return 1; })()`);
      check(await ready(`!!document.querySelector('.row.myagnew #myag-prov') && getComputedStyle(document.querySelector('.row.myagnew')).display !== 'none'`), 'Set up: the create form is there');
      return ev(BOX);
    };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'login frida');
    const a = await open();
    check(a && a.f.every(x => x.w >= a.row.w - 2 && x.w >= 200), '320 px: each field has the full width ' + JSON.stringify(a));
    check(a && a.f[0].bt <= a.f[1].t && a.f[1].bt <= a.f[2].t, '320 px: the three fields one below the other ' + JSON.stringify(a && a.f));
    check(a && a.btn.t >= a.f[2].bt && a.btn.r <= a.vw, '320 px: the button under them, inside the screen ' + JSON.stringify(a && a.btn));
    await o.shot('p2546a-320.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1024, height: 768}});
    const b = await open();
    check(b && b.f.every(x => x.t === b.f[0].t) && b.f.every(x => x.w >= 120), '1024 px: the fields stay on one row with a usable width ' + JSON.stringify(b && b.f));
  }, true);

  console.log(`p2546_a_myag320_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
