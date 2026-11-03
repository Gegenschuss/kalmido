// 2.498.0 A UI tests (Firefox, touch, 320 x 640, own container via start.sh):
// #3854 at 320 px title and bell win the header, the sidebar keeps the names, the view tab shows its whole name or only the symbol
// freelancer-matrix: n/a (no new route; the same header and sidebar for a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2498_a_phone320_ui', check, shots: 'P2498A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2498A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Studio Nordlicht', lang: 'en', collab_all: true, modules: ['comments', 'cal', 'office']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'kanban,timeline,collab,agents,comments,mindmap'});
  const bob = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const ORG = ((await call(CA, 'GET', '/api/state')).me.workspaces || [])[0]?.id;
  check(!!ORG, 'the fixture organisation ' + ORG);
  await call(CA, 'PATCH', '/api/settings', {workspace: 'org:' + ORG});
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const NAMES = ['Kundenportal Relaunch', 'Elbkai Sanierung Nord', 'Fischmarkt Kampagne', 'Elbe'], IDS = [];
  for (const name of NAMES) {
    const id = (await call(CA, 'POST', '/api/lists', {name, org_id: ORG, kind: 'project'})).id; IDS.push(id);
    await call(CA, 'PUT', `/api/lists/${id}/members`, {user_id: bob, role: 'edit'});
    if (ag.id) await call(CA, 'PUT', `/api/lists/${id}/members`, {user_id: ag.id, role: 'edit'});
    const t = await call(CA, 'POST', '/api/tasks', {list_id: id, title: 'One'}); await call(CA, 'POST', '/api/tasks', {list_id: id, title: 'Two'});
    await call(CA, 'PATCH', `/api/tasks/${t.id}`, {status: 1});
  }
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // what the header gives each item
  const top = `(() => { const R = e => e && e.offsetWidth ? e.getBoundingClientRect() : null, q = s => R(document.querySelector('#top ' + s)), w = r => r ? Math.round(r.width) : 0, ht = document.querySelector('#top h1 .ht'), t = ht.firstChild, g = document.createRange();
    g.setStart(t, 0); g.setEnd(t, Math.min(t.length, 12)); const twelve = g.getBoundingClientRect().width; g.setEnd(t, t.length);
    return {cls: document.querySelector('#top').className, tw: Math.round(ht.getBoundingClientRect().width), twelve: Math.floor(twelve), full: Math.floor(g.getBoundingClientRect().width), bell: Math.round(q('.bell')?.right || 0), bw: w(q('.bell')), more: w(q('.tmore')), ag: w(q('.achip') || q('.stchip')), ws: w(q('.wschip')), badge: w(q('.wsbadge')), nw: w(q('[data-act="list-new"]')), nlab: !!document.querySelector('#top [data-act="list-new"] span')?.offsetWidth, sw: document.documentElement.scrollWidth}; })()`;
  const inView = m => m.bell > 0 && m.bell <= 320 && m.bw >= 40 && m.sw <= 321;
  const noSliver = m => (!m.ag || m.ag >= 40) && (!m.ws || m.ws >= 40) && (!m.badge || m.badge >= 40);
  const page = async (ev, nav, h, cond) => { await nav(B + h); check(await ready(ev, `!!S.booted && !!document.querySelector('#top h1 .ht') && ${cond}`, 80), 'the page ' + h); await sleep(400); };

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});

    // Projects: the whole title, the bell on screen, New project = its symbol with a whole target
    await page(ev, nav, '#projects', `S.route.key === 'projects'`);
    let m = await ev(top);
    check(m.tw >= m.full && inView(m) && noSliver(m), 'Projects at 320: title whole, bell on screen, no sliver ' + JSON.stringify(m));
    check(m.nw >= 44 && !m.nlab, 'Projects at 320: New project is a symbol of 44 px ' + JSON.stringify(m));
    await shot('projects');

    // a project: at least 12 characters of the title, the same bell, nothing squeezed; both signs stay reachable in "…"
    await page(ev, nav, '#l/' + IDS[1], `S.route.key === 'l:${IDS[1]}'`);
    m = await ev(top);
    check(m.tw >= m.twelve && inView(m) && noSliver(m), 'project at 320: title keeps 12 characters, bell on screen ' + JSON.stringify(m));
    check(m.cls.includes('tl5') && !m.badge, 'project at 320: the workspace sign left the header ' + JSON.stringify(m));
    await shot('list');
    const items = `[...document.querySelectorAll('#pop [role="menuitem"]')].map(b => ({t: b.textContent, i: +b.dataset.i}))`;
    const more = async () => { await ev(`(() => { document.querySelector('#top [data-act="top-more"]').click(); return 1; })()`); await ready(ev, `!document.querySelector('#pop').classList.contains('hidden')`, 20); return ev(items); };
    const take = async (it, what) => { check(!!it, what); if (it) await ev(`(() => { document.querySelector('#pop [role="menuitem"][data-i="${it.i}"]').click(); return 1; })()`); };
    let its = await more();
    await take(its.find(x => /Workspace/.test(x.t)), '"…" offers the workspace ' + JSON.stringify(its.map(x => x.t)));
    check(await ready(ev, `[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /Private/.test(b.textContent))`, 20), 'the same workspace switch opens from "…"');
    await ev(`(() => { closePop(); return 1; })()`); await sleep(300);
    // even narrower: the agents' sign goes too, its menu stays
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 280, height: 640}});
    await ready(ev, `document.querySelector('#top').classList.contains('tl6')`, 20);
    m = await ev(top);
    check(m.cls.includes('tl6') && !m.ag && m.bell > 0 && m.bell <= 280 && m.tw >= m.twelve * .3, 'project at 280: the agents left the header too ' + JSON.stringify(m));
    its = await more();
    await take(its.find(x => /Agent|Claude/.test(x.t)), '"…" offers the agents ' + JSON.stringify(its.map(x => x.t)));
    check(await ready(ev, `!document.querySelector('#pop').classList.contains('hidden') && !document.querySelector('#pop [data-act="top-more"]') && ![...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /Select multiple/.test(b.textContent))`, 20), 'the same agent menu opens from "…"');
    await ev(`(() => { closePop(); return 1; })()`); await sleep(300);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}}); await sleep(300);

    // the view tab: the whole name or only the symbol
    const tab = `(() => { const b = document.querySelector('.vsegm button.on'), s = b.querySelector('span'), i = b.querySelector('svg'), B = b.getBoundingClientRect(), S = s.getBoundingClientRect(), I = i.getBoundingClientRect(); return {bw: Math.round(B.width), whole: S.top < B.bottom - 2 && S.left >= B.left - 1 && S.right <= B.right + 1, out: S.top >= B.bottom - 1, sym: I.width > 8 && I.left >= B.left && I.right <= B.right && I.top >= B.top - 1 && I.bottom <= B.bottom + 1, rows: document.querySelectorAll('.vsegm button').length, h: Math.round(B.height)}; })()`;
    const views = await ev(`[...document.querySelectorAll('.vsegm button')].map(b => b.dataset.act)`);
    check(views.length > 3, 'the project has many views ' + views);
    for (const v of views) {
      await ev(`(() => { document.querySelector('.vsegm [data-act="${v}"]').click(); return 1; })()`);
      await ready(ev, `!!document.querySelector('.vsegm [data-act="${v}"].on')`, 20);
      await sleep(150);
      const t = await ev(tab); check(t.whole !== t.out && t.sym && t.bw >= 44, 'the tab ' + v + ': whole name or only the symbol ' + JSON.stringify(t));
    }
    await ev(`(() => { document.querySelector('.vsegm [data-act="view-list"]').click(); return 1; })()`); await ready(ev, `!!document.querySelector('.vsegm [data-act="view-list"].on')`, 20); await sleep(300);
    check((await ev(tab)).whole, 'the short name of the list view is shown whole');
    await ev(`(() => { document.querySelector('.vsegm button.on span').textContent = 'Carte mentale du projet'; return 1; })()`); await sleep(100);
    const t = await ev(tab); check(t.out && t.sym && t.bw >= 44, 'a name too long: only the symbol, never cut ' + JSON.stringify(t));
    await shot('tab');
    await ev(`(() => { document.querySelector('.vsegm [data-act="${views[0]}"]').click(); render(); return 1; })()`); await sleep(300);

    // the sidebar: the names keep the row
    await ev(`(() => { document.querySelector('#top .menu').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#side.open')`, 20); await sleep(700);
    await ev(`(() => { const s = document.querySelector('#side'); document.querySelector('#side [data-list="${IDS[0]}"]')?.scrollIntoView({block: 'center'}); return 1; })()`); await sleep(200);
    const rows = await ev(`[...document.querySelectorAll('#side [data-list]')].filter(e => e.offsetWidth).map(r => { const n = r.querySelector('.n'); return {name: n.textContent, w: n.clientWidth, need: n.scrollWidth, shr: [...r.querySelectorAll('.shr')].filter(e => e.offsetWidth).length}; })`);
    check(rows.length >= 3, 'the projects are in the sidebar ' + JSON.stringify(rows));
    for (const r of rows) check(r.w >= r.need, 'sidebar at 320: the name has the row ' + JSON.stringify(r));
    check(rows.every(r => !r.shr), 'sidebar at 320: the share symbol gave way ' + JSON.stringify(rows));
    await shot('side');
    await ev(`(() => { closeSide(); return 1; })()`); await sleep(300);

    // a usual phone: the workspace sign stays where there is room, as a whole 44 px target
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 800}});
    await page(ev, nav, '#l/' + IDS[3], `S.route.key === 'l:${IDS[3]}'`);
    m = await ev(top);
    check(m.badge >= 44, 'phone at 412: the workspace sign is there and wide enough ' + JSON.stringify(m));
    const hit = await ev(`(() => { const b = document.querySelector('#top .wsbadge'), r = b.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2, on = yy => !!document.elementFromPoint(x, yy)?.closest('.wsbadge'); return {h: Math.round(r.height), up: on(y - 20), down: on(y + 20)}; })()`);
    check(hit.up && hit.down, 'the workspace sign takes taps over 44 px height ' + JSON.stringify(hit));
    const side412 = await ev(`[...document.querySelectorAll('#side .shr')].length`);
    check(side412 >= 3, 'a usual phone keeps the share symbols in the sidebar ' + side412);

    // the computer: nothing moved
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await page(ev, nav, '#projects', `S.route.key === 'projects'`);
    m = await ev(top);
    check(!m.cls.includes('tl5') && m.nlab, 'computer: New project keeps its words, no phone level ' + JSON.stringify(m));
  }, true);

  console.log(`p2498_a_phone320_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
