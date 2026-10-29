// kalmido-suite:
// 2.350.0 A UI tests (#2790 chat header on the phone, #3317 agent chat header: one state, at most 3 icons, #2793 desktop
// composer), own container (start.sh), Firefox (phone 360 / 412 px touch, desktop 1280 / 1440 px, light + dark). Invented
// data only. P2350A_NOSTART=1 = the container runs.
// - phone: the header is one row group of at most 56 px; right only the ⋯ menu; name whole; the state once ("working: …"),
//   while working its dot is a small spinning circle; no mode badge, model, workspace, search or usage ring in the header
// - ⋯ names what moved there with its value (Permissions, Model, Workspace, Usage) and works: Permissions opens the mode
//   menu and switches the mode, Search opens the search bar
// - desktop: right exactly side panel switch, ⋯ and close (the panel); nothing is cut off, also at about 700 px chat width (the chat as a page, 960 px)
//   (scrollWidth <= clientWidth); the composer: tools, box and Send in one line with one height, the box >= 60 % of the
//   row, no own line for "Ctrl+Enter sends" (the Send button's title keeps it)
// P4: a person without an organisation with her own agent (private area) gets the same header (freelancer-matrix: Chat)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2350_a_chathead_ui', check, shots: 'P2350A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2350A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

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
  await v1(TOK, 'POST', `/agent/chats/${me.id}`, {body: 'On it, a plain answer'});
  await v1(TOK, 'PUT', '/agent/status', {status: 'working', text: 'Billing: notes', model: 'Opus 5.5', host_permission_mode: 'auto'});
  const wk = new Date(Date.now() + 3 * 864e5).toISOString();
  await v1(TOK, 'PUT', '/agent/quota', {windows: [{label: 'Week', percent: 41, resets_at: wk}]});
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
  await v1(ft.token, 'PUT', '/agent/status', {status: 'idle', model: 'Sonnet 5.5'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u, theme) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  // the header's visible buttons right of the name (avatar, back and the usage ring are not counted)
  const HEAD = sel => `[...document.querySelectorAll('${sel} .chath.chh2 button')].filter(b => !b.matches('.avb, .chback, .chring') && b.offsetParent).map(b => b.getAttribute('data-act') || b.className)`;
  const GEO = sel => `(() => { const h = document.querySelector('${sel} .chath.chh2'); if (!h) return null; const r = h.getBoundingClientRect(), b = h.querySelector('.chnm b'), x = h.querySelector('.chstx'), d = h.querySelector('.chst .adot');
    const cut = [...h.querySelectorAll('.chnm b, .chstx, .chl2, .chn')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.className || e.tagName);
    return {h: Math.round(r.height), right: Math.round(r.right), vw: innerWidth, name: b?.textContent, st: x?.textContent, cut, spin: d ? getComputedStyle(d).animationName : '', rm: matchMedia('(prefers-reduced-motion: reduce)').matches, dot: d?.className,
      gone: ['.chmode', '.chmodel', '.chws'].filter(s => h.querySelector(s)), ring: [...h.querySelectorAll('.chring')].filter(e => e.offsetParent).length}; })()`;
  const diag = ev => ev(`JSON.stringify({h: location.hash, w: innerWidth, ach: !!document.querySelector('#achat .chath'), cls: document.querySelector('.chath')?.className, ag: (window.S?.agents || []).map(a => a.id + ':' + a.name), v: (document.querySelector('#view')?.textContent || '').slice(0, 200)})`).catch(e => String(e));
  const items = `[...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')].map(b => b.textContent.trim().replace(/\\s+/g, ' '))`;
  const pickItem = (ev, re) => ev(`(() => { const b = [...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')].find(x => ${re}.test(x.textContent.trim())); if (!b) return 0; b.click(); return 1; })()`);
  const openMenu = async (ev, sel) => { await ev(`document.querySelector('${sel} .chath [data-act="chat-head-menu"]').click()`); return ready(ev, `!!document.querySelector('#pop:not(.hidden) [role=menuitem]')`); };
  const COMP = sel => `(() => { const c = document.querySelector('${sel} .chcomp'), t = c?.querySelector('textarea'), s = c?.querySelector('[data-act="chat-send"]'); if (!t || !s) return null;
    const vis = [...c.children].filter(e => e.offsetParent && e.getBoundingClientRect().width > 0 && !e.matches('input, .chtools, .mpick')), hs = vis.map(e => Math.round(e.getBoundingClientRect().height));
    const k = c.querySelector('.chkh'); return {box: t.getBoundingClientRect().width / c.clientWidth, hs, top: new Set(vis.map(e => Math.round(e.getBoundingClientRect().bottom))).size, hint: !!k && k.offsetParent !== null, title: s.title}; })()`;

  // ---- phone, alice's agent in the organisation: 360 px light (with the menu round), 412 px dark
  for (const [W, theme, full] of [[360, 'light', true], [412, 'dark', false]]) {
    await firefox(async o => {
      const {cmd, ev, ctx, nav, shot} = o, L = `phone ${W} ${theme}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 780}});
      check(await signIn(o, 'alice', theme) === 200, L + ': login');
      await nav(B + '#agents/' + CL);
      const up = await ready(ev, `!!document.querySelector('#view .chath.chh2 .chstx')`, 80);
      check(up, L + ': the chat is up' + (up ? '' : ' ' + await diag(ev)));
      const g = await ev(GEO('#view'));
      check(g && g.h <= 56, L + ': the header is at most 56 px high ' + JSON.stringify(g));
      check(g && g.name === 'Dev Bot' && !g.cut.length && g.right <= g.vw, L + ': nothing cut off ' + JSON.stringify(g));
      check(g && /^working: Billing: notes/.test(g.st || '') && /st-working/.test(g.dot) && (g.spin === 'aspin' || g.rm), L + ': the state once, "working: <job>", the spinning circle (a still dot with reduced motion) ' + JSON.stringify(g));
      // 2.407.0 B (#3493): the usage ring is always shown (41 % = accent), no longer only near its limit
      check(g && !g.gone.length && g.ring === 1, L + ': no mode, model or workspace in the header, the usage ring always ' + JSON.stringify(g));
      const head = await ev(HEAD('#view'));
      check(head.length === 1 && head[0] === 'chat-head-menu', L + ': right only the ⋯ menu ' + JSON.stringify(head));
      await shot(`p2350a-phone-${W}-${theme}.png`);
      if (!full) return;
      await openMenu(ev, '#view');
      const it = await ev(items);
      check(it.some(x => x === 'Permissions: Host default (Auto)') && it.some(x => x === 'Model: Opus 5.5') && it.some(x => x === 'Team agent · Alpha') /* 2.407.0 B (#3493): the kind of agent instead of the workspace */
        && it.some(x => /^Usage: 41 %/.test(x)) && it.some(x => x === 'Search in this chat') && it.some(x => /^Filter|^Fold long messages/.test(x)), L + ': ⋯ names what moved there with its value ' + JSON.stringify(it));
      // Permissions opens the mode menu; "Ask first" switches the agent
      await pickItem(ev, '/^Permissions/');
      check(await ready(ev, `[...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')].some(x => /^Ask first/.test(x.textContent.trim()))`), L + ': Permissions opens the mode menu');
      await pickItem(ev, '/^Ask first/');
      check(await ready(ev, `fetch('/api/agents').then(r => r.json()).then(j => (j.agents || []).find(a => a.id === ${CL})?.permission_mode === 'ask')`), L + ': the mode is switched to Ask first');
      await openMenu(ev, '#view');
      check((await ev(items)).some(x => x === 'Permissions: Ask first'), L + ': ⋯ shows the new mode');
      await pickItem(ev, '/^Search in this chat$/');
      check(await ready(ev, `!!document.querySelector('#ms-q')`), L + ': Search in ⋯ opens the search bar');
      await call(CA, 'PUT', `/api/agents/${CL}/permission-mode`, {mode: ''});
    }, true);
  }

  // ---- desktop: the side panel at 1280 light / 1440 dark; the chat as a page (about 700 px chat width) at 960 px
  for (const [W, theme] of [[1280, 'light'], [1440, 'dark'], [960, 'light']]) {
    await firefox(async o => {
      const {cmd, ev, ctx, nav, shot} = o, page = W < 1000, sel = page ? '#view' : '#achat', L = `desktop ${W} ${theme} ${page ? 'page' : 'panel'}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 860}});
      check(await signIn(o, 'alice', theme) === 200, L + ': login');
      await nav(B + '#agents/' + CL);
      const up = await ready(ev, `!!document.querySelector('${sel} .chath.chh2 .chstx')`, 80);
      check(up, L + ': the chat is up' + (up ? '' : ' ' + await diag(ev)));
      const g = await ev(GEO(sel));
      check(g && !g.cut.length && g.name === 'Dev Bot' && /^working: Billing: notes/.test(g.st || '') && g.right <= g.vw, L + ': nothing cut off ' + JSON.stringify(g));
      // 2.407.0 B (#3493): the usage ring is always shown (41 % = accent), no longer only near its limit
      check(g && !g.gone.length && g.ring === 1, L + ': no mode, model or workspace in the header, the usage ring always ' + JSON.stringify(g));
      const head = (await ev(HEAD(sel))).sort();
      check(JSON.stringify(head) === JSON.stringify(page ? ['chat-head-menu'] : ['chat-close', 'chat-dock', 'chat-head-menu']), L + ': right exactly ' + (page ? '⋯ (the page has its back button)' : 'side panel, ⋯ and close') + ' ' + JSON.stringify(head));
      const c = await ev(COMP(sel));
      check(c && c.box >= 0.6 && !c.hint && /Enter sends/.test(c.title), L + ': the box takes >= 60 %, no hint line, the hint is the title ' + JSON.stringify(c));
      check(c && Math.max(...c.hs) - Math.min(...c.hs) <= 1 && c.top === 1, L + ': tools, box and Send on one line, one height ' + JSON.stringify(c));
      await openMenu(ev, sel);
      check((await ev(items)).some(x => x === 'Search in this chat'), L + ': Search is in ⋯');
      await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
      await shot(`p2350a-${page ? 'page' : 'panel'}-${W}-${theme}.png`);
    }, false);
  }

  // ---- P4: frida without an organisation, her own agent, phone 412 px
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o, L = 'frida (no organisation) phone 412';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 780}});
    check(await signIn(o, 'frida', 'light') === 200, L + ': login');
    await nav(B + '#agents/' + fa.id);
    const up = await ready(ev, `!!document.querySelector('#view .chath.chh2 .chstx')`, 80);
      check(up, L + ': the chat is up' + (up ? '' : ' ' + await diag(ev)));
    const g = await ev(GEO('#view'));
    check(g && g.h <= 56 && g.name === 'Frida Bot' && !g.cut.length && !g.gone.length, L + ': the same header, at most 56 px, nothing cut off ' + JSON.stringify(g));
    const head = await ev(HEAD('#view'));
    check(head.length === 1 && head[0] === 'chat-head-menu', L + ': right only the ⋯ menu ' + JSON.stringify(head));
    await openMenu(ev, '#view');
    const it = await ev(items);
    check(it.some(x => x === 'Model: Sonnet 5.5') && it.some(x => x === 'Search in this chat'), L + ': ⋯ with model and search ' + JSON.stringify(it));
    await pickItem(ev, '/^Search in this chat$/');
    check(await ready(ev, `!!document.querySelector('#ms-q')`), L + ': Search opens the search bar');
    await shot('p2350a-phone-frida.png');
  }, true);

  console.log(`p2350_a_chathead_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
