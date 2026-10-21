// 2.152.2 UI tests, part C (#2627 chat header: only search + menu, #2660 the line under the brand is not cut), own container
// (start.sh), Firefox (desktop 1280 px + phone 412 px touch, light + dark). Invented data only. P21522C_NOSTART=1 = the container runs.
// - #2627: the agent chat's header shows exactly two icons (search, menu); filter, "Fold long messages" and "Always show steps"
//   are entries of the menu with their state; the menu icon carries the dot while the filter is not "All"
// - #2660: phone, workspace "All workspaces": the line under the brand in the drawer is whole (scrollWidth <= clientWidth)
// P4: the agent chat belongs to the server's agents (no organisation needed for the menu); the brand line is checked for a person
// without an organisation too (freelancer-matrix: Chat)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21522_c_ui', check, shots: 'P21522C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21522C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let TOK;
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const st = await call(CA, 'GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: [...feats].join(',')});
  const me = (await call(CA, 'GET', '/api/state')).me;
  await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  const J = (await v1('POST', '/agent/jobs', {title: 'Knox: Release 2.152.2', user_id: me.id, state: 'running'})).id;
  await call(CA, 'POST', `/api/agents/${CL}/chat`, {body: 'Please build the release'});
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  await say('Hello, a plain answer');
  await say('Knox: started the build', {job_id: J, job_msg: 'say'});
  check(J, 'setup: a job in the chat');
  // frida: no organisation (P4)
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'all'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u, theme) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  // the header's buttons without avatar, back / close / window buttons and the mode chip
  const HEAD = `[...document.querySelectorAll('.chath button')].filter(b => !b.matches('.avb, .ib, .chmode, .chback, [data-act="chat-close"], [data-act="chat-dock"], [data-act^="cw-"], .cwbtn') && b.offsetParent).map(b => b.getAttribute('data-act') || b.className)`;
  const items = `[...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')].map(b => b.textContent.trim().replace(/\\s+/g, ' ') + (b.classList.contains('on') ? ' [on]' : ''))`;
  const pickItem = (ev, re) => ev(`(() => { const b = [...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')].find(x => ${re}.test(x.textContent)); if (!b) return 0; b.click(); return 1; })()`);
  const openMenu = async ev => { await ev(`document.querySelector('.chath [data-act="chat-head-menu"]').click()`); return ready(ev, `!!document.querySelector('#pop:not(.hidden) [role=menuitem]')`); };

  const chatRun = async (o, label) => {
    const {ev, nav, shot} = o;
    await nav(B + '#agents/' + CL);
    check(await ready(ev, `!!document.querySelector('.chath [data-act="ms-toggle"]') && !!document.querySelector('#jcd-fbtn')`, 80), label + ': the chat is up');
    const head = await ev(HEAD);
    check(head.length === 2 && head.includes('ms-toggle') && head.includes('chat-head-menu'), label + ': the header shows exactly search + menu ' + JSON.stringify(head));
    check(await ev(`!document.querySelector('.chath .jcfbtn, .chath .chstog')`), label + ': no fold / steps icon in the header');
    check(await ev(`!document.querySelector('#jcd-fbtn .jcdfdot')`), label + ': filter All: no dot');
    await shot(`p21522c-head-${label.replace(/\W+/g, '-')}.png`);
    await openMenu(ev);
    let it = await ev(items);
    check(it.some(x => /^Filter: All/.test(x)) && it.some(x => /^Fold long messages/.test(x)) && it.some(x => /^Always show steps/.test(x)) && it.some(x => /^Delete history/.test(x)), label + ': the menu has Filter / Fold / Steps / Delete ' + JSON.stringify(it));
    check(!it.some(x => /\[on\]/.test(x)), label + ': nothing is switched on yet ' + JSON.stringify(it));
    // the filter: submenu with the three choices
    await pickItem(ev, '/^Filter/');
    check(await ready(ev, `[...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')].some(x => x.textContent.trim() === 'Jobs')`), label + ': the filter entry opens the three choices');
    await pickItem(ev, '/^Jobs$/');
    check(await ready(ev, `!!document.querySelector('#jcd-fbtn .jcdfdot')`), label + ': filter Jobs: the menu icon carries the dot');
    check(await ev(`(() => { const d = document.querySelector('#jcd-fbtn .jcdfdot'), r = d.getBoundingClientRect(); return r.width > 0 && getComputedStyle(d).backgroundColor !== 'rgba(0, 0, 0, 0)'; })()`), label + ': ... and the dot is visible');
    await shot(`p21522c-dot-${label.replace(/\W+/g, '-')}.png`);
    await openMenu(ev); it = await ev(items);
    check(it.some(x => /^Filter: Jobs/.test(x)), label + ': the entry shows which filter holds ' + JSON.stringify(it));
    // steps: the entry switches, with its state
    await pickItem(ev, '/^Always show steps/');
    check(await ready(ev, `S.settings && S.settings.agent_steps_always === '1'`), label + ': "Always show steps" switches on');
    await openMenu(ev); it = await ev(items);
    check(it.some(x => /^Always show steps.*\[on\]/.test(x)), label + ': ... and the entry is marked ' + JSON.stringify(it));
    await pickItem(ev, '/^Always show steps/');
    check(await ready(ev, `S.settings.agent_steps_always !== '1'`), label + ': switches off again');
    // back to All
    await openMenu(ev); await pickItem(ev, '/^Filter/');
    await ready(ev, `[...document.querySelectorAll('#pop:not(.hidden) [role=menuitem]')].some(x => x.textContent.trim() === 'All')`);
    await pickItem(ev, '/^All$/');
    check(await ready(ev, `!document.querySelector('#jcd-fbtn .jcdfdot')`), label + ': filter All: the dot is gone');
  };

  for (const theme of ['light', 'dark']) {
    await firefox(async o => {
      await o.cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1280, height: 860}});
      check(await signIn(o, 'alice', theme) === 200, 'alice: login ' + theme);
      await chatRun(o, 'desktop ' + theme);
    }, false);
    await firefox(async o => {
      await o.cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 412, height: 860}});
      check(await signIn(o, 'alice', theme) === 200, 'alice: login phone ' + theme);
      await chatRun(o, 'phone ' + theme);
    }, true);
  }

  // ================= #2660 the line under the brand, phone 412 px, "All workspaces"
  for (const [u, label] of [['alice', 'organisation'], ['frida', 'no organisation (P4)']]) {
    await firefox(async o => {
      const {cmd, ev, ctx, nav, shot} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 860}});
      check(await signIn(o, u, 'light') === 200, u + ': login');
      await nav(B + '#inbox');
      await ready(ev, `!!document.querySelector('#top .menu')`, 60);
      await ev(`document.querySelector('#top .menu').click()`); await sleep(700);
      const m = await ev(`(() => { const w = document.querySelector('#side .sbbrand .sbbsub .wsn'); return w ? {t: w.textContent, sw: w.scrollWidth, cw: w.clientWidth} : null; })()`);
      check(m && (u !== 'alice' || /^All workspaces$/i.test(m.t)) && m.sw <= m.cw, '#2660: ' + label + ': "All workspaces" is whole under the brand ' + JSON.stringify(m));
      await shot('p21522c-brand-' + u + '.png');
    }, true);
  }

  console.log(`p21522_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
