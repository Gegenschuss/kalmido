// 2.431.0 C (#3598, #3602): Office > Clients and the contacts (Firefox, a real layout), frida WITHOUT an organisation
// (freelancer-matrix: clients, contacts: her private clients, her own address book):
// - #3598 computer 1280x800: the page does not scroll as a whole; the list on the left scrolls for itself, the search bar
//   stays on top and the card on the right stays where it is (it scrolls for itself when it is long); the phone keeps its
//   one column as before
// - #3602 a change elsewhere (a list renamed, a setting of another device: the whole state) leaves the open page alone: the
//   same list node, its scroll and the card stay, nothing drawn, no invoices / documents fetched again; the return to the
//   tab the same; a change of the shown client / contact still appears (and the scroll stays)
// Invented data only (@example.com). Screenshots: P2431C_SHOTS.
// kalmido-suite: fresh
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2431C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2431_c_ui', check, shots: 'P2431C_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const N = 40;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['contacts']});
  const FEAT = 'contacts,office,clients,time';
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEAT});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEAT});
  check(fu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const CL = [], CT = [];
  for (let i = 0; i < N; i++) CL.push((await call(CF, 'POST', '/api/clients', {name: `Client ${String(i).padStart(2, '0')} Studio`, org_id: null, email: `c${i}@example.com`, phone: '+49 30 1000' + i, address: 'Example street 1, 10115 Example town'})).id);
  const BK = (await call(CF, 'POST', '/api/books', {name: 'Mine', org_id: null})).id;
  for (let i = 0; i < N; i++) CT.push((await call(CF, 'POST', '/api/contacts', {book_id: BK, fn: `Person ${String(i).padStart(2, '0')} Example`, emails: [{value: `p${i}@example.com`, type: ['work']}], phones: [{value: '+49 40 2000' + i, type: ['cell']}]})).id);
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Elsewhere'})).id;
  check(CL.every(Boolean) && CL.length === N && CT.every(Boolean) && BK && L, `setup: ${N} clients, ${N} contacts, a list (${CL.filter(Boolean).length}, ${CT.filter(Boolean).length})`);
  let ln = 0;
  // a change elsewhere that brings the whole state: the list renamed + a setting of another device (the full way)
  const elsewhere = async () => { ln++; await call(CF, 'PATCH', `/api/lists/${L}`, {name: `Elsewhere ${ln}`}); await call(CF, 'PATCH', '/api/settings', {allday_time: ln % 2 ? '10:00' : '11:00'}); };

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const until = async (expr, n = 40) => { for (let i = 0; i < n; i++) { const x = await ev(expr).catch(() => null); if (x) return x; await sleep(250); } return ev(expr).catch(() => null); };
    // the page has taken the server's last change (its poll saw the version, the full state is in and drawn)
    const caught = () => until(`fetch('/api/version', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.v === S.v && !td_polling && !td_rsT)`, 120);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, 'login frida');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    check(await ev(`matchMedia('(hover:hover) and (pointer:fine)').matches`), 'a computer with a mouse (not the touch tablet layout)');
    // what the columns do: the view's own scroll, the list's, where the bar and the card stand
    const geo = `(() => { const v = document.querySelector('#view'), l = v.querySelector('.ctlistw'), b = v.querySelector('.ctbar'), c = v.querySelector('.ctcard'); if (!l || !b || !c) return null;
      const vr = v.getBoundingClientRect(), r = e => Math.round(e.getBoundingClientRect().top);
      return {vs: v.scrollHeight - v.clientHeight, ls: l.scrollHeight - l.clientHeight, lt: l.scrollTop, bar: r(b) - Math.round(vr.top), card: r(c), cb: Math.round(c.getBoundingClientRect().bottom), vb: Math.round(vr.bottom), cy: getComputedStyle(c).overflowY}; })()`;
    for (const pg of [{name: 'clients', hash: `client/${CL[0]}`, row: '.msclients .ctrow', card: '.msclcard', n: 'cl'}, {name: 'contacts', hash: `contacts/${CT[0]}`, row: '.ctrow[data-ctopen]', card: '.ctcard[data-ck]', n: 'ct'}]) {
      const tag = `${pg.name} 1280`;
      await nav(B + '#' + pg.hash);
      check(await until(`document.querySelectorAll('#view ${pg.row}').length >= ${N} && !!document.querySelector('#view ${pg.card}') && typeof S !== 'undefined' && !!S.lpA`, 80), `${tag}: the list (${N}) and the open card`);
      await caught();
      // ---- #3598
      const g0 = await ev(geo);
      check(g0 && g0.vs <= 1 && g0.ls > 300, `${tag} #3598: the page does not scroll, the list does (${JSON.stringify(g0)})`);
      check(g0 && g0.cy === 'auto' && g0.cb <= g0.vb + 1, `${tag} #3598: the card ends inside the window and scrolls for itself (${JSON.stringify(g0)})`);
      await ev(`(() => { document.querySelector('#view').scrollTop = 400; document.querySelector('#view .ctlistw').scrollTop = 600; return 1; })()`);
      await sleep(100);
      const g1 = await ev(geo);
      check(g1 && g1.lt === 600 && g1.bar === g0.bar && g1.card === g0.card && g1.bar >= 0, `${tag} #3598: after scrolling the list the search bar and the card stand where they were (${JSON.stringify([g0, g1])})`);
      if (pg.n === 'cl') await shot('p2431_c_clients_scrolled.png');
      // ---- #3602: a change elsewhere leaves the page alone
      await ev(`(() => { document.querySelector('#view .ctlistw').__p2431 = 1; window.__p2431f = []; if (!window.__p2431w) { window.__p2431w = 1; const f0 = window.fetch; window.fetch = (u, ...a) => { window.__p2431f.push(String(u)); return f0(u, ...a); }; } return 1; })()`);
      const st0 = await ev('S.lpN.state'), dr0 = await ev(`S.lpN.${pg.n}Draw || 0`), lv0 = await ev(`S.lpN.${pg.n}Live || 0`);
      await elsewhere();
      check(await until(`S.lpN.state > ${st0}`, 80), `${tag} #3602: the change elsewhere came with the whole state (${await ev('S.lpN.state')} vs ${st0})`);
      await caught();
      check(await until(`(S.lpN.${pg.n}Live || 0) > ${lv0}`, 40), `${tag} #3602: the page looked quietly whether it changed`);
      await sleep(300);
      const g2 = await ev(`(() => { const l = document.querySelector('#view .ctlistw'); return {same: l?.__p2431 === 1, lt: l?.scrollTop, card: !!document.querySelector('#view ${pg.card}'), loading: !!document.querySelector('#view .ctempty')}; })()`);
      check(g2.same && g2.lt === 600 && g2.card && !g2.loading, `${tag} #3602: the same list (node, scroll 600) and the card, no "Loading" (${JSON.stringify(g2)})`);
      check(await ev(`S.lpN.${pg.n}Draw || 0`) === dr0, `${tag} #3602: nothing drawn (the page did not change)`);
      const off = await ev(`window.__p2431f.filter(u => /\\/api\\/office\\//.test(u))`);
      check(off.length === 0, `${tag} #3602: invoices / documents / letters not fetched again (${JSON.stringify(off)})`);
      // the return to the tab: the same
      await ev(`(() => { document.dispatchEvent(new Event('visibilitychange')); return 1; })()`);
      await sleep(400); await caught(); await sleep(300);
      const g3 = await ev(`(() => { const l = document.querySelector('#view .ctlistw'); return {same: l?.__p2431 === 1, lt: l?.scrollTop, card: !!document.querySelector('#view ${pg.card}')}; })()`);
      check(g3.same && g3.lt === 600 && g3.card, `${tag} #3602: back in the tab the list and its scroll stay (${JSON.stringify(g3)})`);
      // a change of the shown entry appears, the list keeps its scroll
      if (pg.n === 'cl') await call(CF, 'PATCH', `/api/clients/${CL[0]}`, {phone: '+49 30 7777777'});
      else await call(CF, 'PATCH', `/api/contacts/${CT[0]}`, {phones: [{value: '+49 40 7777777', type: ['cell']}]});
      check(await until(`/7777777/.test(document.querySelector('#view ${pg.card}')?.textContent || '')`, 80), `${tag} #3602: the change of the shown ${pg.n === 'cl' ? 'client' : 'contact'} appears on the card`);
      const g4 = await ev(`(() => { const l = document.querySelector('#view .ctlistw'); return {lt: l?.scrollTop, n: document.querySelectorAll('#view ${pg.row}').length}; })()`);
      check(g4.lt === 600 && g4.n >= N, `${tag} #3602: the list keeps its scroll after that change (${JSON.stringify(g4)})`);
      // a row's change elsewhere shows in the list (the list really follows)
      if (pg.n === 'cl') await call(CF, 'PATCH', `/api/clients/${CL[N - 1]}`, {name: 'Client 39 Renamed'});
      else await call(CF, 'PATCH', `/api/contacts/${CT[N - 1]}`, {fn: 'Person 39 Renamed'});
      check(await until(`[...document.querySelectorAll('#view ${pg.row}')].some(x => /39 Renamed/.test(x.textContent))`, 80), `${tag} #3602: a renamed ${pg.n === 'cl' ? 'client' : 'contact'} shows in the list`);
      if (pg.n === 'ct') await shot('p2431_c_contacts_after.png');
    }
    // the phone: one column, the page scrolls as before
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#clients');
    check(await until(`document.querySelectorAll('#view .msclients .ctrow').length >= ${N}`, 80), 'phone: the clients list');
    const ph = await ev(`(() => { const v = document.querySelector('#view'), c = v.querySelector('.ctcols'); return {vy: getComputedStyle(v).overflowY, cols: getComputedStyle(c).gridTemplateColumns.split(' ').length, card: !!v.querySelector('.ctcard')}; })()`);
    check(ph.vy === 'auto' && ph.cols === 1 && !ph.card, `phone #3598: one column as before (the computer's rules do not apply) (${JSON.stringify(ph)})`);
  }, false);  // a mouse: Firefox's default matched the touch tablets' office rule (#2445), which hid the bug
  console.log(`p2431_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
