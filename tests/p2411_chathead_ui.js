// kalmido-suite:
// 2.411.0 UI tests (#3529 a long state line in the agent chat header, #3446 Stop in the header's ⋯ menu), own container
// (start.sh), Firefox (desktop 1280 px side panel, phone 390 px touch). Invented data only. P2411C_NOSTART=1 = the container runs.
// - #3529: a 200-character "working: …" stays one line and ends in "…" before the header buttons (it never runs under
//   them); the full text is the hint (title) of the line
// - #3446: while the agent answers me the ⋯ button has a red dot; its menu starts with "Stop the answer" in red; no Stop
//   button in the box any more
// P4: a person without an organisation with her own agent (private area) gets the same header (freelancer-matrix: Chat)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2411_chathead_ui', check, shots: 'P2411C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2411C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const LONG = 'Walker: fill in the briefs (10 tasks) - findings: ' + 'static/js/agentchat.js and static/css/agentchat.css, the header line, '.repeat(3);
const TXT = LONG.slice(0, 200);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const st = await call(CA, 'GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: [...feats].join(',')});
  const me = (await call(CA, 'GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id, TOK = ag.token;
  await call(CA, 'PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W0 = (await call(CA, 'POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call(CA, 'PUT', `/api/lists/${W0}/members`, {user_id: CL, role: 'edit'});
  await call(CA, 'POST', `/api/agents/${CL}/chat`, {body: 'Please write the release notes'});
  await v1(TOK, 'POST', `/agent/chats/${me.id}`, {body: 'On it'});
  await v1(TOK, 'PUT', '/agent/status', {status: 'working', text: TXT});
  // frida: no organisation, her own agent (P4)
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'all', features: [...feats].join(',')});
  const FU = (await call(CF, 'GET', '/api/state')).me;
  check(!(FU.workspaces || []).length, 'frida: no organisation');
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const fa = await call(CF, 'POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida Bot', scopes: ['read', 'tasks:write', 'comments']});
  const ft = fa.token ? fa : await call(CF, 'POST', `/api/my/agents/${fa.id}/token`, {});
  check(fa.id && ft.token, 'frida: her own agent with a token ' + fa.http);
  await v1(ft.token, 'POST', `/agent/chats/${FU.id}`, {body: 'Hello Frida'});
  await v1(ft.token, 'PUT', '/agent/status', {status: 'working', text: TXT});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  // the state line: cut (scrollWidth > clientWidth), its right edge left of the first visible header button, the title = full text
  const GEO = sel => `(() => { const h = document.querySelector('${sel} .chath.chh2'); if (!h) return null; const x = h.querySelector('.chstx'); if (!x) return null;
    const btn = [...h.querySelectorAll('.chhb button, :scope > button')].filter(b => b.offsetParent && !b.matches('.avb, .chback'))[0], xr = x.getBoundingClientRect(), l2 = h.querySelector('.chl2').getBoundingClientRect();
    return {sw: x.scrollWidth, cw: x.clientWidth, right: Math.round(Math.max(xr.right, l2.right)), btn: btn ? Math.round(btn.getBoundingClientRect().left) : null, title: x.title, one: Math.round(xr.height) <= 24, ov: getComputedStyle(x).textOverflow}; })()`;
  const headCase = async (o, sel, L, aname) => {
    const up = await ready(o.ev, `!!document.querySelector('${sel} .chath.chh2 .chstx')`, 80);
    check(up, L + ': the chat is up');
    const g = await o.ev(GEO(sel));
    check(g && g.sw > g.cw && g.ov === 'ellipsis' && g.one, L + ': the long state is one line and cut with … ' + JSON.stringify(g));
    check(g && g.btn != null && g.right <= g.btn + 1, L + ': the state ends before the header buttons ' + JSON.stringify(g));
    check(g && g.title === 'working: ' + TXT, L + ': the full text is the hint ' + JSON.stringify(g && g.title));
    check(!(await o.ev(`!!document.querySelector('${sel} .chcomp .chstop, #chat-stop')`)), L + ': no Stop button in the box (#3446)');
    await o.shot(`p2411-${aname}.png`);
  };

  // ---- desktop 1280: the side panel; the answer runs for alice: the red dot and Stop first in ⋯
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o, L = 'desktop 1280 panel';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    check(await signIn(o, 'alice') === 200, L + ': login');
    await nav(B + '#agents/' + CL);
    await headCase(o, '#achat', L, 'panel-1280');
    await v1(TOK, 'POST', '/agent/typing', {chat_user_id: me.id});
    await ev('agentPoll()').catch(() => 0);
    const dot = await ready(ev, `(() => { const b = document.querySelector('#achat #jcd-fbtn.chbusy'); return !!b && getComputedStyle(b, '::before').backgroundColor !== 'rgba(0, 0, 0, 0)'; })()`, 60);
    check(dot, L + ': the answer runs: a red dot on ⋯ (#3446)');
    await ev(`document.querySelector('#achat #jcd-fbtn').click()`);
    check(await ready(ev, `!!document.querySelector('#pop:not(.hidden) [role=menuitem]')`), L + ': ⋯ opens');
    const it = await ev(`(() => { const a = [...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')], s = document.querySelector('#pop:not(.hidden) .chmi-stop'); if (!s) return null;
      const c = getComputedStyle(s.querySelector('.ml') || s).color, d = getComputedStyle(document.documentElement).getPropertyValue('--danger').trim(); return {first: a[0] === s, text: s.textContent.trim(), c, d, keys: !!s.querySelector('kbd')}; })()`);
    check(it && it.first && /^Stop the answer/.test(it.text) && it.keys, L + ': "Stop the answer" is the first entry, with its key ' + JSON.stringify(it));
    check(it && it.c !== 'rgb(0, 0, 0)' && /^rgb\((\d+)/.test(it.c) && +it.c.match(/^rgb\((\d+), (\d+)/)[1] > +it.c.match(/^rgb\((\d+), (\d+)/)[2] + 60, L + ': the entry is red ' + JSON.stringify(it));
    await o.shot('p2411-panel-1280-menu.png');
  }, false);

  // ---- phone 390: alice (the organisation's agent) and frida (P4, her own agent)
  for (const [u, aid, nm] of [['alice', CL, 'phone-390'], ['frida', fa.id, 'phone-390-frida']]) {
    await firefox(async o => {
      const {cmd, ctx, nav} = o, L = `phone 390 ${u}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 780}});
      check(await signIn(o, u) === 200, L + ': login');
      await nav(B + '#agents/' + aid);
      await headCase(o, '#view', L, nm);
    }, true);
  }

  console.log(`p2411_chathead_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
