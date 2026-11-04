// kalmido-suite: fresh
// 2.505.0 (#4325): two agent cards side by side (Firefox, real layout, two columns as on a tablet): opening "Projects" on one
// makes only that card longer; the neighbour keeps its height and its inner layout. With P2505_SHOTS: a picture before and after.
// freelancer-matrix: agents  (a person without an organisation with own agents)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2505_agcard_ff_ui', check, shots: 'P2505_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const SH = !!process.env.P2505_SHOTS;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 3});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'});
  for (const n of ['one', 'two']) check((await call(CF, 'POST', '/api/my/agents', {username: 'bot' + n, display_name: 'Bot ' + n})).id, 'an own agent without an organisation: ' + n);
  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1000, height: 800}});
    await nav(B + 'static/icon.svg'); await nav(B + '#agents');
    check(await ready(ev, `document.querySelectorAll('.agcard .aglists').length >= 2`), 'two cards with their projects');
    await sleep(300);
    // the neighbour: its height and where its projects row sits inside the card
    const measure = `(() => { const [a, b] = document.querySelectorAll('.agcard'), ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(), s = b.querySelector('.aglists').getBoundingClientRect();
      return JSON.stringify({same: Math.abs(ra.top - rb.top) < 2 && ra.left !== rb.left, a: ra.height, b: rb.height, row: s.top - rb.top}); })()`;
    const before = JSON.parse(await ev(measure));
    check(before.same, 'the two cards stand side by side ' + JSON.stringify(before));
    if (SH) await shot('p2505-agcard-closed.png');
    await ev(`(() => { const a = document.querySelector('.agcard .aglists'); a.open = true; return 1; })()`);
    check(await ready(ev, `document.querySelector('.agcard').getBoundingClientRect().height > ${before.a + 10}`), 'the opened card gets longer');
    const after = JSON.parse(await ev(measure));
    check(Math.abs(after.b - before.b) < 1, `the neighbour keeps its height (${before.b} -> ${after.b})`);
    check(Math.abs(after.row - before.row) < 1, `the neighbour's projects row stays in its place (${before.row} -> ${after.row})`);
    if (SH) await shot('p2505-agcard-open.png');
  });
  console.log(`p2505_agcard_ff_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
