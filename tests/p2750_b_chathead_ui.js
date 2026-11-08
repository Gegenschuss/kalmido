// kalmido-suite: fresh
// 2.750.0 (#5243) UI test: the header of the agent chat on a phone (touch, 320 / 412 / 460 px): even, tight gaps like the team chat
// and the same height in every state (ready, working on #..., working with text, waiting, paused, error), so nothing jumps.
// Own container (start.sh), Firefox. Invented data only.
// freelancer-matrix: none (layout only)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2750_b_chathead_ui', check, shots: 'P2750BH_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Kalmido Dev'});
  const CL = ag.id, TOK = ag.token;
  await call(CA, 'PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W0 = (await call(CA, 'POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call(CA, 'PUT', `/api/lists/${W0}/members`, {user_id: CL, role: 'edit'});
  const tk = await call(CA, 'POST', `/api/lists/${W0}/tasks`, {title: 'Header gaps'});
  await call(CA, 'POST', `/api/agents/${CL}/chat`, {body: 'Please look at the header'});
  await v1(TOK, 'POST', `/agent/chats/${me.id}`, {body: 'On it'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const STATES = [['idle', {status: 'idle'}], ['working-task', {status: 'working', task_id: tk.id, text: 'Fixing it'}], ['working-text', {status: 'working', text: 'Reading the code'}],
    ['waiting', {status: 'waiting', text: 'Waiting for an answer'}], ['paused', {status: 'paused', text: 'Weekly limit'}], ['error', {status: 'error', text: 'Something broke'}]];
  // geometry of the header: its height, gap back arrow -> picture, picture -> name, name line -> state line
  const GEO = `(() => { const h = document.querySelector('#view .chath.chh2'); if (!h) return null; const R = s => { const e = h.querySelector(s); return e && e.offsetParent ? e.getBoundingClientRect() : null; };
    const back = R('.chback'), av = R('.avb, .avatar'), nm = R('.chnm b'), l2 = R('.chl2'), hr = h.getBoundingClientRect(), chn = R('.chn');
    const r = x => x == null ? null : Math.round(x * 10) / 10;
    return {h: r(hr.height), backAv: back && av ? r(av.left - back.right) : null, avNm: av && nm ? r(nm.left - av.right) : null, nmL2: nm && l2 ? r(l2.top - nm.bottom) : null, chnH: chn ? r(chn.height) : null, l2h: l2 ? r(l2.height) : null, nmh: nm ? r(h.querySelector('.chnm').getBoundingClientRect().height) : null, kids: [...h.children].map(k => k.className.split(' ')[0] + ':' + r(k.getBoundingClientRect().height)).join(','), sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth}; })()`;

  for (const W of [320, 412, 460]) {
    await firefox(async o => {
      const {cmd, ev, ctx, nav, shot} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 780}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, W + ': login');
      await nav(B + '#agents/' + CL);
      check(await ready(o.ev, `!!document.querySelector('#view .chath.chh2 .chstx, #view .chath.chh2 .chst')`, 80), W + ': the chat is up');
      const seen = {};
      for (const [nm, body] of STATES) {
        await v1(TOK, 'PUT', '/agent/status', body);
        await ev('agentPoll()').catch(() => 0);
        const cls = nm === 'working-task' || nm === 'working-text' ? 'working' : nm;
        await ready(ev, `!!document.querySelector('#view .chath .chst.st-${cls}') && ${nm === 'working-task' ? `!!document.querySelector('#view .chath .chtask')` : nm === 'working-text' ? `!document.querySelector('#view .chath .chtask')` : 'true'}`, 40);
        const g = await ev(GEO); seen[nm] = g;
        console.log('GEO', W, nm, JSON.stringify(g));
        await shot(`p2750b-head-${W}-${nm}.png`);
      }
      const all = Object.values(seen).filter(Boolean);
      check(all.length === STATES.length, W + ': all states measured');
      check(all.every(g => g.h === all[0].h), W + ': the header has the same height in every state ' + JSON.stringify(all.map(g => g.h)));
      check(all.every(g => g.backAv != null && g.backAv <= 8), W + ': back arrow and picture close together ' + JSON.stringify(all.map(g => g.backAv)));
      check(all.every(g => g.avNm != null && g.avNm <= 12), W + ': picture and name close together ' + JSON.stringify(all.map(g => g.avNm)));
      check(all.every(g => g.nmL2 != null && g.nmL2 <= 4), W + ': name line and state line close ' + JSON.stringify(all.map(g => g.nmL2)));
      check(all.every(g => g.sw <= g.cw), W + ': no sideways scrolling');
    }, true);
  }
  console.log(`p2750_b_chathead_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
