// kalmido-suite: fresh
// 2.437.0 A UI tests (Firefox): #3626 the inline title field on a double click (list with the people column + sections: the
// field sits flush right of the circle, the columns stay right of it, Enter / Esc as before); #3737 the agent chat's typing row
// (always there, fixed height, the message list keeps its height); #3318 delivery ticks without the word.
// Screenshots into $P2437A_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2437_a_ui', check, shots: 'P2437A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents', show_done_default: '1', show_done_new: '0'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const L = (await call('POST', '/api/lists', {name: 'Team', org_id: (await call('GET', '/api/state')).me.workspaces[0].id})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const S1 = (await call('POST', '/api/sections', {name: 'Light', list_id: L})).id;
  const T = [];
  for (const [t, s] of [['Fix the bath light', S1], ['Move the kitchen light', S1], ['Unassigned loose task', null]]) T.push((await call('POST', '/api/tasks', {title: t, list_id: L, ...(s ? {section_id: s} : {})})).id);
  await call('PATCH', `/api/tasks/${T[1]}`, {assignee_id: BOB, due: '2030-05-02'});
  await call('PATCH', `/api/lists/${L}`, {columns: ['who', 'due']});

  const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PATCH', '/api/settings', {workspace: 'all'});
  // an own agent per run: once an agent fetched a message the chat shows "writing" for a while by itself
  const mkAgent = async name => {
    const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: name, display_name: name});
    await call('PATCH', `/api/admin/agents/${ag.id}`, {org_id: ORG});
    const AL = (await call('POST', '/api/lists', {name: 'For ' + name, org_id: ORG})).id;
    await call('PUT', `/api/lists/${AL}/members`, {user_id: ag.id, role: 'edit'});  // it shares a project with me: its chat is open to me
    await call('POST', `/api/agents/${ag.id}/chat`, {body: 'Please write the release notes'});
    await v1(ag.token, 'PUT', '/agent/status', {status: 'idle'});
    return {AG: ag.id, TOK: ag.token};
  };

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const rect = `const R = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), t: Math.round(b.top), r: Math.round(b.right), b: Math.round(b.bottom), h: Math.round(b.height)}; };`;

  // ---- #3626
  const dbl = async (o, id, what, shotName, withDetail) => {
    // the detail pane narrows the list (the columns move under the title); open another task first
    if (withDetail) { await o.ev(`openDetail(${T[0] === id ? T[1] : T[0]})`); await sleep(700); }
    // a real double click with the mouse (BiDi), on the title text
    const pt = await o.ev(`(() => { const t = document.querySelector('#view .trow[data-id="${id}"] .ttl'); if (!t) return null; t.scrollIntoView({block: 'center'}); const b = t.getBoundingClientRect(); return {x: Math.round(b.left + 20), y: Math.round(b.top + b.height / 2)}; })()`);
    if (pt) {
      const click = [{type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}];
      await o.cmd('input.performActions', {context: o.ctx, actions: [{type: 'pointer', id: 'm1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: pt.x, y: pt.y}, ...click, ...click]}]});
      await o.cmd('input.releaseActions', {context: o.ctx});
      await o.until(`!!document.querySelector('#view .ttlin')`, {timeout: 3000});
      await sleep(1200);  // the detail pane and the list settle (redraws keep the field)
    }
    const g = await o.ev(`(() => { ${rect} const row = document.querySelector('#view .trow[data-id="${id}"]'); if (!row) return null;
      const i = row.querySelector('.ttlin'), c = row.querySelector('.chk');
      const cols = [...row.querySelectorAll('.lcols, .lcols .lc, .meta, .wcell, .whob')].map(R).filter(x => x && x.r > x.l);
      return {row: R(row), i: R(i), c: R(c), cols, ttl: R(row.querySelector('.ttl'))}; })()`);
    if (shotName) await o.shot(shotName);
    check(!!g && !!g.i, `#3626: ${what}: the field is there ` + JSON.stringify(g));
    if (!g || !g.i) return;
    check(g.i.l >= g.c.r && g.i.l - g.c.r <= 24, `#3626: ${what}: the field starts right next to the circle ` + JSON.stringify([g.i, g.c]));
    check(g.i.r - g.i.l >= 120, `#3626: ${what}: the field has room (${g.i.r - g.i.l}px)`);
    check(g.i.t >= g.row.t && g.i.b <= g.row.b, `#3626: ${what}: the field lies inside the row`);
    check(g.cols.every(x => x.l >= g.i.r - 1 || x.r <= g.i.l || x.t >= g.i.b || x.b <= g.i.t), `#3626: ${what}: no column overlaps the field ` + JSON.stringify(g));
    // Enter saves, Esc cancels
    const e = await o.ev(`(() => { const i = document.querySelector('#view .ttlin'); i.value = 'zzz'; i.dispatchEvent(new Event('input', {bubbles: true}));
      i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); return !document.querySelector('#view .ttlin') && !/zzz/.test(document.querySelector('#view .trow[data-id="${id}"]').textContent); })()`);
    check(e === true, `#3626: ${what}: Esc cancels`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx} = o;
    check(await ffLogin(o) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1345, height: 800}});
    await o.nav(B + '#l/' + L); await until(() => ev(`!!document.querySelector('#view .trow')`), 60); await sleep(800);
    const cases = async tag => {
      await dbl(o, T[0], `${tag} section row, detail open`, `p2437a-3626-${tag}.png`, true);
      await o.nav(B + '#l/' + L); await sleep(1000);
      await dbl(o, T[1], `${tag} row with person + date, detail open`, null, true);
      await o.nav(B + '#l/' + L); await sleep(1000);
      await dbl(o, T[2], `${tag} unassigned row, detail open`, null, true);
    };
    for (const [cols, tag] of [[['who', 'due'], 'cols'], [null, 'plain'], [['who'], 'who']]) {
      await call('PATCH', `/api/lists/${L}`, {columns: cols});
      await o.nav(B + '#l/' + L); await sleep(1200);
      await cases(`1345-${tag}`);
    }
    await call('PATCH', `/api/lists/${L}`, {columns: null});
    await call('PATCH', `/api/lists/${L}`, {columns: null});
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 900, height: 800}}); await sleep(600);
    await o.nav(B + '#l/' + L); await sleep(1200);
    await dbl(o, T[2], '900 unassigned row, detail open', 'p2437a-3626-900.png', true);
  }, false);

  // ---- #3737 typing row + #3318 ticks, agent chat (computer, phone, the side window #achat)
  for (const [wd, tag] of [[1345, '1345'], [390, '390']]) {
    const {AG, TOK} = await mkAgent('devbot' + wd);
    await firefox(async o => {
      const {cmd, ev, ctx} = o;
      check(await ffLogin(o) === 200, `${tag}: login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: 800}});
      await o.nav(B + '#agents/' + AG);
      check(await o.until(`!!document.querySelector('#chat-msgs .cmsg.me') && !!document.querySelector('#chat-typing')`, {timeout: 20000}), `${tag}: the agent chat is up ` + await ev(`JSON.stringify({h: location.hash, ag: (window.S?.agents || []).map(a => a.id + ':' + a.name), v: (document.querySelector('#view')?.innerText || '').slice(0, 200), me: document.querySelectorAll('#chat-msgs .cmsg').length})`));
      await sleep(600);
      const geo = `(() => { ${rect} const q = s => document.querySelector(s), t = q('#chat-typing'), m = q('#chat-msgs'), c = q('.chcomp'); return {t: R(t), m: R(m), c: R(c), bt: t && getComputedStyle(t).borderTopWidth, hid: t && getComputedStyle(t).display, kids: t ? t.childElementCount : -1, bot: !!q('#chat-typing svg.bot')}; })()`;
      const g0 = await ev(geo);
      check(g0.t && g0.hid !== 'none' && g0.kids === 0, `${tag} #3737: the typing row is there while nobody writes ` + JSON.stringify(g0));
      check(g0.t && g0.t.h >= 32 && g0.bt === '1px', `${tag} #3737: fixed height and a rule on top ` + JSON.stringify(g0));
      check(g0.t && g0.m && g0.t.t >= g0.m.b - 1 && g0.c && g0.t.b <= g0.c.t + 1, `${tag} #3737: the row sits between the messages and the input ` + JSON.stringify(g0));
      await ev(`(() => { const a = agentById(${AG}); a.enabled = true; a.online = true; a.typing = 600; S.agentsAt = Date.now(); agentLive(); return 1; })()`);
      check(await o.until(`!!document.querySelector('#chat-typing svg.bot')`, {timeout: 5000}), `${tag} #3737: the writing figure appears`);
      const g1 = await ev(geo);
      check(g1.m.h === g0.m.h && g1.t.h === g0.t.h && g1.t.t === g0.t.t, `${tag} #3737: the message list and the row keep their size with the figure ` + JSON.stringify([g0, g1]));
      await o.shot(`p2437a-3737-${tag}.png`);
      await ev(`(() => { const a = agentById(${AG}); a.typing = 0; agentLive(); return 1; })()`);
      check(await o.until(`!document.querySelector('#chat-typing svg.bot')`, {timeout: 5000}), `${tag} #3737: the figure goes away`);
      const g2 = await ev(geo);
      check(g2.m.h === g0.m.h && g2.t.h === g0.t.h && g2.kids === 0, `${tag} #3737: back to the empty row, same sizes ` + JSON.stringify(g2));
      // #3318
      const tk = `(() => { const r = [...document.querySelectorAll('#chat-msgs .cmsg.me')].pop(), d = r && r.querySelector('.cdlv'); return d && {n: d.querySelectorAll('svg').length, txt: d.textContent.trim(), al: d.getAttribute('aria-label'), ti: d.title, on: d.classList.contains('on'), vis: r.textContent.replace(/\\s+/g, ' ')}; })()`;
      const k0 = await ev(tk);
      check(k0 && k0.n === 1 && k0.txt === '' && k0.al === 'Sent' && k0.ti === 'Sent' && !/Sent|Delivered/.test(k0.vis), `${tag} #3318: sent = one tick, no word ` + JSON.stringify(k0));
      await v1(TOK, 'GET', '/agent/events?since=0');  // the agent fetches the message
      await ev(`chatLoad().then(() => 1)`); await sleep(400);
      const k1 = await ev(tk);
      check(k1 && k1.n === 2 && k1.txt === '' && /^Delivered/.test(k1.al || '') && k1.on && !/Delivered/.test(k1.vis), `${tag} #3318: delivered = two ticks, no word ` + JSON.stringify(k1));
    }, undefined);
  }

  console.log(`p2437_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
