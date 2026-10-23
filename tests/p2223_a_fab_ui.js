// 2.223.0 A (#2815) the round agent button bottom right (#chatfab) covers nothing: on the main desktop pages (team chat,
// a project list, office cash book, text blocks, figures, cash flow), scrolled to the end, no visible button / link button /
// field / select lies under the button's box. Own container (start.sh), Firefox (jsdom has no layout), 1280 x 800 and
// 1440 x 900, light and dark; the office pages also for a person without an organisation (freelancer-matrix: office).
// Invented people and figures only. Screenshots with P2223A_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2223_a_fab_ui', check, shots: 'P2223A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,agents,team,office,clients,docs,time';

// scroll every scroll box to its end, then list the visible controls whose box (clipped by their scroll boxes) meets the
// agent button's box
const FABCHK = `(async () => {
  const f = document.querySelector('#chatfab');
  if (!f || !f.getClientRects().length || getComputedStyle(f).visibility === 'hidden') return {fab: false, hits: []};
  const scr = e => e.scrollHeight > e.clientHeight + 2 && /auto|scroll/.test(getComputedStyle(e).overflowY);
  for (let k = 0; k < 3; k++) {  // a late re-render (data arriving) may put the scroll back
    for (const s of [document.scrollingElement, ...document.querySelectorAll('#app *')]) if (s && scr(s)) s.scrollTop = s.scrollHeight;
    await new Promise(r => requestAnimationFrame(() => setTimeout(r, 400)));
  }
  const fb = f.getBoundingClientRect(), hits = [];
  const clip = e => { let b = e.getBoundingClientRect(), l = b.left, t = b.top, r = b.right, bo = b.bottom;
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p); if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      const q = p.getBoundingClientRect(); l = Math.max(l, q.left); t = Math.max(t, q.top); r = Math.min(r, q.right); bo = Math.min(bo, q.bottom);
    }
    return {l, t, r: Math.min(r, innerWidth), b: Math.min(bo, innerHeight)}; };
  for (const e of document.querySelectorAll('button, a.btn, input:not([type=hidden]), select, textarea')) {
    if (f.contains(e) || !e.getClientRects().length || e.closest('.hidden, [hidden], #toast')) continue;
    const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const b = clip(e); if (b.r - b.l < 2 || b.b - b.t < 2) continue;
    if (b.r > fb.left + 1 && b.l < fb.right - 1 && b.b > fb.top + 1 && b.t < fb.bottom - 1)
      hits.push((e.id ? '#' + e.id : e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).join('.') : '')) + ' "' + (e.textContent || e.placeholder || e.getAttribute('aria-label') || '').trim().slice(0, 30) + '"');
  }
  return {fab: true, hits, box: [Math.round(fb.left), Math.round(fb.top)]};
})()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments', 'agents']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CA, CB, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const me = (await call(CA, 'GET', '/api/state')).me;
  const BOB = (await call(CB, 'GET', '/api/state')).me.id;
  // an agent alice and frida share a list with (in alice's private space, frida is admin there): the round button shows for both
  const AG = (await call(CA, 'POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'})).id;
  const LS = (await call(CA, 'POST', '/api/lists', {name: 'Shared with Frida'})).id;
  await call(CA, 'PUT', `/api/lists/${LS}/members`, {user_id: AG, role: 'edit'});
  await call(CA, 'PUT', `/api/lists/${LS}/members`, {user_id: fu.id, role: 'admin'});
  check(((await call(CF, 'GET', '/api/agents')).agents || []).length === 1, 'frida reaches the agent');
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Frida Film'})).id;
  let T = 0;
  for (let i = 0; i < 30; i++) { const id = (await call(CA, 'POST', '/api/tasks', {title: `Website task ${i}`, list_id: L, content: i ? '' : Array.from({length: 40}, (_, k) => `- line ${k} of a long note`).join('\n')})).id; T = T || id; }
  for (let i = 0; i < 6; i++) await call(CB, 'POST', `/api/tasks/${T}/comments`, {body: `Comment ${i} on the task`});
  for (let i = 0; i < 30; i++) await call(CF, 'POST', '/api/tasks', {title: `Film task ${i}`, list_id: LF});
  const RID = ((await call(CA, 'GET', '/api/team')).rooms || []).find(x => x.list_id === L)?.id;
  check(RID, 'the channel of the shared list');
  for (let i = 0; i < 25; i++) await call(i % 2 ? CB : CA, 'POST', `/api/team/rooms/${RID}/messages`, {body: `Message ${i} about the shoot`});
  for (const ck of [CA, CF]) for (let i = 0; i < 12; i++) await call(ck, 'POST', `/api/office/cashbooks/${(await call(ck, 'GET', '/api/office/cashbooks')).books[0]?.id}/entries`, {day: new Date().toISOString().slice(0, 10), dir: 'in', amount: String(10 + i), vat_pct: '19', text: `Sale ${i}`});

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const PAGES = [
    ['team chat', '#team/' + RID, `!!document.querySelector('#tc-in')`, 'alice'],
    ['project list', '#l/' + L, `document.querySelectorAll('#view .trow').length > 5`, 'alice'],
    ['project list', '#l/' + LF, `document.querySelectorAll('#view .trow').length > 5`, 'frida'],
    ['open task', '#l/' + L, `document.querySelectorAll('#view .trow').length > 5`, 'alice', `openDetail(${T})`],
    ['cash book', '#office/cashbook', `!!document.querySelector('#cb-quick')`, 'alice', 'frida'],
    ['text blocks', '#office/texts', `!!document.querySelector('.office .ofcbody')`, 'alice', 'frida'],
    ['figures', '#office/kpi', `!!document.querySelector('.office .ofcbody')`, 'alice', 'frida'],
    ['cash flow', '#office/cashflow', `!!document.querySelector('.office .ofcbody')`, 'alice', 'frida'],
  ];
  for (const user of ['alice', 'frida']) {
    await firefox(async ({cmd, ev, ctx, nav, shot}) => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      check(await signIn(ev, user) === 200, `${user}: login`);
      for (const [vw, vh, theme] of [[1280, 800, 'light'], [1440, 900, 'dark']]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
        for (const [name, hash, rdy, ...rest] of PAGES) {
          const act = rest.find(x => x.includes('(')), who = rest.filter(x => x !== act);
          if (!who.includes(user)) continue;
          await nav(B + hash);
          const okp = await ready(ev, rdy);
          check(okp, `${user} ${vw}: ${name} loads ` + (okp ? '' : await ev(`location.hash + ' ' + (document.querySelector('#view')?.textContent || '').slice(0, 200)`)));
          if (!okp) continue;
          if (act) { await ev(`(() => { ${act}; return 1; })()`); await ready(ev, `!document.querySelector('#detail').classList.contains('hidden')`, 20); }
          await ready(ev, `!!document.querySelector('#chatfab')`, 20); await sleep(800);
          const res = await ev(FABCHK);
          check(res.fab, `${user} ${vw}: ${name}: the agent button shows ` + (res.fab ? '' : await ev(`JSON.stringify({ag: (S.agents || []).map(a => [a.id, a.enabled, a.chat]), f: feat('agents'), full: chatFull()})`)));
          check(!res.hits.length, `${user} ${vw} ${theme}: ${name}: nothing under the agent button ${JSON.stringify(res)}`);
          await shot(`p2223a-${user}-${vw}-${name.replace(/ /g, '-')}.png`);
        }
      }
    }, false);
  }
  console.log(`p2223_a_fab_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
