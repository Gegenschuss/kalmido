// 2.236.0 A (#2904-#2911): the dialog "Work style and notifications" at phone width (360 and 412 px), Firefox with screenshots
// (P2236A_SHOTS): nothing runs off the side, the fields and the weekday boxes are at least 44 px high, the sections are all there.
// freelancer-matrix: agents  (a person without an organisation with an own agent)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2236_a_workstyle_ff_ui', check, shots: 'P2236A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2236A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const SH = !!process.env.P2236A_SHOTS;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 3});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'});
  const ag = await call(CF, 'POST', '/api/my/agents', {username: 'fridabot', display_name: 'Fridabot'});
  check(ag.id, 'an own agent without an organisation');
  await call(CF, 'PATCH', `/api/agents/${ag.id}/work-style`, {budget_period: 'day', budget_limit: 5000, work_mode: 'office', quiet_mode: 'on'});
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    for (const W of [360, 412]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 844}});
      await nav(B + 'static/icon.svg'); await nav(B + '#agents');
      check(await ready(ev, `typeof settingsModal === 'function' && typeof S === 'object' && !!S.me && !!document.querySelector('.agcard')`, 80), `the app is up (${W})`);
      await sleep(500);
      await ev(`(() => { settingsModal('ai'); return 1; })()`);
      await sleep(600);
      await ev(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`).catch(() => 0);
      check(await ready(ev, `!!document.querySelector('#s-myown [data-myag-act="work"]')`, 60), `the cog button in the agent row (${W})`);
      await ev(`(() => { document.querySelector('#s-myown [data-myag-act="work"]').click(); return 1; })()`);
      const open = await ready(ev, `!!document.querySelector('.awdlg #aw-push')`, 60);
      check(open, `the dialog opens (${W})`);
      if (!open) break;
      await sleep(400);
      check(await ev(`(() => { const c = document.querySelector('.awdlg .card'); const R = c.getBoundingClientRect().right; return [...c.querySelectorAll('*')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= document.documentElement.clientWidth + 1); })()`), `nothing runs off the side (${W})`);
      check(await ev(`['aw-h-budget', 'aw-h-time', 'aw-h-par', 'aw-h-prio', 'aw-h-rep', 'aw-h-msg'].every(i => !!document.getElementById(i))`), `all six sections (${W})`);
      check(await ev(`[...document.querySelectorAll('.awdlg select, .awdlg input:not([type=checkbox]):not([type=hidden]), .awdlg .awday')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().height >= 43.5)`), `fields and weekday boxes at least 44 px (${W})`);
      check(await ev(`(() => { const d = [...document.querySelectorAll('.awdlg .awday')]; document.querySelector('.awdlg #aw-office').scrollIntoView(); return d.length === 7 && d[0].getBoundingClientRect().top === d[3].getBoundingClientRect().top; })()`), `the weekday boxes sit side by side (${W})`);
      if (SH) await shot(`p2236a-workstyle-${W}.png`);
      await ev(`(() => { document.querySelector('.awdlg [data-m="close"]').click(); document.querySelector('.smodal [data-m="close"], .smodal .mclose')?.click(); return 1; })()`);
    }
  });
  console.log(`p2236_a_workstyle_ff_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
