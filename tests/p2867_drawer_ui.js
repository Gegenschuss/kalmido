// kalmido-suite: fresh
// 2.867.0 UI test (#5540): the phone's drawer is calm and even (Firefox, touch, 412 x 915 like the report's Android Chrome).
// freelancer-matrix: n/a (no new route; alice runs the instance without an organisation, the drawer is the same for her)
// - the area icons are ONE fixed grid of equal columns (4 per row once there are more than 5 areas, was up to 7 x 2 with
//   columns as wide as their names), every name in ONE type size (the smallest one any name needs), nothing cut
// - the dot drawn into an icon (the icon set's accent dot) is in the tile's own colour in the drawer: no accent dot reads as
//   "something new" at Projects / Calendar / Time / Files; a real "something waits" mark stays (team chat, agents, a timer)
// - one count per thing: the agents' tile carries only a dot (the numbers stand in the agents' rows), the header's agent pill
//   leaves its number out while the drawer is open
// - the agents' rows are as high as the lists' rows; their status dot is the status colour only (no ring in the agent's
//   colour), a tap on the dot explains the state (it does not open the chat)
// - the computer's bar (sidebar B) keeps the accent dots and the numbers
// Screenshots into $P2867D_SHOTS. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2867_drawer_ui', check, shots: 'P2867D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const MODS = 'cal,comments,office,contacts,wiki,sheets,habits,time,pomo,review,stats,agents,reading,collab';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'de', collab_all: true, time_all: true, modules: MODS.split(',')});
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: MODS});
  const me = (await call(CA, 'GET', '/api/state')).me.id;
  const L = [];
  for (const n of ['Garten', 'Steuer', 'Umzug']) { const l = (await call(CA, 'POST', '/api/lists', {name: n})).id; L.push(l); await call(CA, 'POST', '/api/tasks', {title: n + ' anfangen', list_id: l}); }
  // two agents: Wolke is in touch and has written to alice (an unread message), Nebel never connected
  const wolke = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'wolke', display_name: 'Wolke'});
  const nebel = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read'], username: 'nebel', display_name: 'Nebel'});
  check(wolke.token && nebel.id, 'two agents ' + wolke.http + ' ' + nebel.http);
  for (const a of [wolke, nebel]) await call(CA, 'PUT', `/api/lists/${L[0]}/members`, {user_id: a.id, role: 'edit'});
  check((await v1(wolke.token, 'GET', '/agent/chats')).http === 200, 'Wolke reads its chats (in touch)');
  check((await v1(wolke.token, 'POST', `/agent/chats/${me}`, {body: 'Die Beete sind geplant.'})).http === 201, 'Wolke writes to alice');
  await call(CA, 'PATCH', '/api/settings', {side_agents: `${wolke.id},${nebel.id}`});  // both pinned in the drawer's People

  await firefox(async ({cmd, ev, nav, ctx, shot, until}) => {
    const wait = s => until(() => ev(s));
    const size = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    await size(412, 915);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); localStorage.setItem('tasks.lookLocal', 'true'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await nav(B + '#today'); await wait(`!!S.booted`);
    const open = async () => { await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`); return wait(`!!document.querySelector('#side.open .sbmr .srb[data-sbb]')`); };
    check(await open(), 'the drawer opens');
    await sleep(400);
    await shot('p2867-drawer-412.png');
    const G = `(() => { const r = document.querySelector('#side .sbmr'), bs = [...r.querySelectorAll('.srb[data-sbb]')], R = e => e.getBoundingClientRect();
      const ws = bs.map(b => Math.round(R(b).width * 2) / 2), fs = [...new Set(bs.map(b => getComputedStyle(b.querySelector('.srbn')).fontSize))];
      const cols = new Set(bs.map(b => Math.round(R(b).left))).size, rows = new Set(bs.map(b => Math.round(R(b).top))).size;
      return {n: bs.length, cols, rows, wmin: Math.min(...ws), wmax: Math.max(...ws), fs, inside: bs.every(b => R(b).right <= R(r).right + 1 && R(b).left >= R(r).left - 1),
        cut: bs.map(b => b.querySelector('.srbn')).filter(n => n.classList.contains('srcut') || n.scrollWidth > n.clientWidth + 1 || n.scrollHeight > n.clientHeight + 1).map(n => n.textContent)}; })()`;
    for (const w of [412, 360, 320]) {
      await size(w, 915); await sleep(300); await ev('sbb_fit(), 1');
      const g = await ev(G);
      check(g.n >= 12 && g.cols === 4 && g.rows === Math.ceil(g.n / 4), `#5540 ${w} px: a fixed grid of 4 columns ` + JSON.stringify(g));
      check(g.wmax - g.wmin <= 1 && g.inside, `#5540 ${w} px: every column equally wide, nothing sideways ` + JSON.stringify(g));
      check(g.fs.length === 1 && !g.cut.length, `#5540 ${w} px: one type size for every name, nothing cut ` + JSON.stringify(g));
    }
    await size(412, 915); await sleep(300);
    // the icons' own dot: the tile's colour, not the accent (the computer keeps the accent: app.css svg.i .d)
    const DOTS = `(() => [...document.querySelectorAll('#side .sbmr .srb[data-sbb]:not(.on)')].map(b => { const d = b.querySelector('svg.i .d'); return d ? [b.dataset.sbb, getComputedStyle(d).fill === getComputedStyle(b).color] : null; }).filter(Boolean))()`;
    const dots = await ev(DOTS);
    check(dots.length >= 3 && dots.every(x => x[1]), '#5540: the icons\' own dots in the tile\'s colour (no accent dot without meaning) ' + JSON.stringify(dots));
    // the agents: the tile a dot without a number, the row the number; the header pill without its number while open
    const ag = await ev(`(() => { const t = document.querySelector('#side .sbmr .srb[data-sbb="agents"] .srbd'), row = document.querySelector('#side .steam[data-aid="${wolke.id}"] .c.nunread'), n = document.querySelector('#top .achip .acn');
      return {tile: t ? t.className + '|' + t.textContent.trim() : null, tileLab: t?.getAttribute('aria-label') || t?.title || '', row: row?.textContent || '', pill: n ? getComputedStyle(n).display !== 'none' && getComputedStyle(n).visibility !== 'hidden' : false}; })()`);
    check(ag.tile && /srdot/.test(ag.tile) && ag.tile.split('|')[1] === '' && ag.tileLab, '#5540: the agents\' tile a dot without a number (named for screen readers) ' + JSON.stringify(ag));
    check(ag.row === '1', '#5540: the number stands in the agent\'s row ' + JSON.stringify(ag));
    check(!ag.pill, '#5540: the header pill leaves its number out while the drawer is open ' + JSON.stringify(ag));
    // rows as high as the lists' rows
    const hs = await ev(`(() => { const h = s => [...document.querySelectorAll(s)].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().height));
      return {list: h('#side .srow[data-list]'), agent: h('#side .srow.steam[data-aid]')}; })()`);
    check(hs.list.length && hs.agent.length === 2 && hs.agent.every(x => Math.abs(x - hs.list[0]) <= 1), '#5540: the agents\' rows as high as the lists\' rows ' + JSON.stringify(hs));
    // the status dot: the status colour only, a tap explains it and keeps the drawer (no chat)
    const ring = await ev(`(() => [...document.querySelectorAll('#side .steam[data-aid] .hdot')].map(d => getComputedStyle(d).boxShadow))()`);
    check(ring.length === 2 && ring.every(x => x === 'none'), '#5540: the status dot without the agent\'s colour ring ' + JSON.stringify(ring));
    await ev(`(() => { document.querySelector('#side .steam[data-aid="${nebel.id}"] .sdot').click(); return 1; })()`);
    check(await wait(`/Nebel/.test(document.querySelector('#toast')?.textContent || '') && /nicht verbunden|grau/i.test(document.querySelector('#toast')?.textContent || '')`), '#5540: a tap on the dot explains the state ' + await ev(`document.querySelector('#toast')?.textContent`));
    check(await ev(`!!document.querySelector('#side.open') && !document.querySelector('#achat:not(.hidden), .chview')`), '#5540: the tap on the dot opens no chat, the drawer stays');
    await shot('p2867-drawer-agents.png');
    // the area Agents in the drawer: its rows as high as the rows of an area's parts
    await ev(`(() => { document.querySelector('#side .sbmr .srb[data-sbb="agents"]').click(); return 1; })()`);
    check(await wait(`!!document.querySelector('#side.open .sbbp .steam[data-go^="agents/"]')`), 'the area Agents in the drawer');
    await sleep(300); await shot('p2867-drawer-agentsarea.png');
    const ha = await ev(`(() => { const h = s => [...document.querySelectorAll(s)].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().height)); return {part: h('#side .sbbp .srow:not(.steam)'), agent: h('#side .sbbp .steam')}; })()`);
    check(ha.part.length && ha.agent.length === 2 && ha.agent.every(x => Math.abs(x - ha.part[0]) <= 1), '#5540: the area Agents: its agents\' rows as high as its other rows ' + JSON.stringify(ha));
    await ev(`(() => { document.querySelector('#side .sbmr .srb[data-sbb="tasks"]').click(); return 1; })()`);
    await wait(`!!document.querySelector('#side.open .steam[data-aid]')`);
    // a tap on the row itself still opens the chat
    await ev(`(() => { document.querySelector('#side .steam[data-aid="${nebel.id}"] .n').click(); return 1; })()`);
    check(await wait(`S.chat?.aid === ${nebel.id}`), '#5540: a tap on the row opens the agent\'s chat as before');
  }, true);
  console.log(F.length ? `p2867_drawer_ui: ${F.length} FAILED, ${ok} passed` : `p2867_drawer_ui: all ${ok} passed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
