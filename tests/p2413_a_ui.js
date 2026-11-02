// kalmido-suite: fresh
// 2.413.0 A (#3439) UI tests: every view keeps its place (static/js/viewmem.js). In Firefox (real layout):
//  - a list scrolled -> another list -> back: the same row at the top; the left sidebar keeps its own place per area
//  - an office document (offer) scrolled far down -> a list -> back over the office icon: the document is open, same place
//  - after a reload the list and the sidebar stand where they were
//  - phone width (390 px): list -> other list -> back = same row
//  - the task open in the panel opens again with its view (after a reload), a task completed in between does not
//  - counter-check: without the hooks (vm_after / vm_leave off) the same way back does NOT show the same row
// Own container (start.sh). freelancer-matrix: everything runs as frida (no organisation, her own office)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2413_a_ui', check, shots: 'P2413A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const MODS = 'cal,comments,office,contacts,wiki';
const svc = (title, qty, rate) => ({kind: 'service', title, qty, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing: 0, in_handling: 0, in_markup: 0, intext: 'intern', cost: 0, discountable: 1});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: MODS.split(',')});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.http < 300, 'P4: frida (no organisation) ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS});
  const L = {}, T = {};
  for (const n of ['Alpha', 'Beta']) {
    L[n] = (await call(CF, 'POST', '/api/lists', {name: n})).id; T[n] = [];
    for (let i = 0; i < 60; i++) T[n].push((await call(CF, 'POST', '/api/tasks', {title: `${n} task ${String(i).padStart(2, '0')}`, list_id: L[n]})).id);
  }
  for (let i = 0; i < 30; i++) await call(CF, 'POST', '/api/lists', {name: `Extra ${String(i).padStart(2, '0')}`});  // the sidebar scrolls
  const items = []; for (let i = 0; i < 40; i++) items.push(svc(`Item ${String(i).padStart(2, '0')}`, 1, 100 + i));
  const doc = await call(CF, 'POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Long offer', items});
  check(doc.id, 'setup: an offer with 40 items ' + JSON.stringify(doc).slice(0, 200));
  const D = doc.id;

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(200); } return false; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 720}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.ofmAll', 'true'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'frida logs in');
    const up = () => ready(`!!S.booted && !!document.querySelector('#view')`, 100);
    // the id of the first task row whose top is inside the view; the scroll box of the open office document
    const TOP = `(() => { const v = document.querySelector('#view'), vt = v.getBoundingClientRect().top; const r = [...v.querySelectorAll('.trow[data-id]')].find(x => x.getBoundingClientRect().top >= vt - 1 && x.getBoundingClientRect().height); return r ? +r.dataset.id : 0; })()`;
    const BOX = `(() => { const all = [document.querySelector('#view'), ...document.querySelectorAll('#view *')].filter(e => /auto|scroll/.test(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 40); all.sort((a, b) => b.scrollHeight - a.scrollHeight); return all[0] || null; })()`;
    const listShown = id => ready(`S.route.key === 'l:${id}' && document.querySelectorAll('#view .trow[data-id]').length >= 20`);
    const kept = key => ready(`(() => { const o = JSON.parse(localStorage.getItem('tasks.viewMem') || '{}'); return Object.keys(o).some(k => k.endsWith('|${key}') && o[k].y > 0); })()`, 30);
    // scrolls the list so that row i of the view stands at the top
    const scrollTo = i => ev(`(() => { const v = document.querySelector('#view'), r = v.querySelectorAll('.trow[data-id]')[${i}]; v.scrollTop += r.getBoundingClientRect().top - v.getBoundingClientRect().top; return 1; })()`);
    const go = h => ev(`(go(${JSON.stringify(h)}), 1)`);
    // a real reload (a navigate that only changes the address' hash stays in the same page)
    const reload = async h => { await ev(`(window.__p2413 = 1, 1)`); await nav(B + 'static/icon.svg'); await nav(B + '#' + h); return ev(`!window.__p2413`); };
    const OPEN = `!!document.querySelector('#view input[data-k="title"][data-i="39"]')`;

    await nav(B + `#l/${L.Alpha}`);
    check(await up() && await listShown(L.Alpha), 'desktop: list Alpha is shown');
    // ================= a list -> another list -> back
    await scrollTo(30);
    const topA = await ev(TOP);
    check(topA && topA !== T.Alpha[0], 'desktop: Alpha scrolled down ' + topA);
    check(await kept(`t:l:${L.Alpha}`), 'desktop: the place of Alpha is written to the browser');
    await go(`l/${L.Beta}`);
    check(await listShown(L.Beta), 'desktop: list Beta');
    await scrollTo(10);
    const topB = await ev(TOP);
    await go(`l/${L.Alpha}`);
    check(await listShown(L.Alpha) && await ready(`${TOP} === ${topA}`, 30), 'desktop: back in Alpha the same row is on top ' + topA + ' / ' + await ev(TOP));
    await go(`l/${L.Beta}`);
    check(await listShown(L.Beta) && await ready(`${TOP} === ${topB}`, 30), 'desktop: back in Beta its own row is on top ' + topB + ' / ' + await ev(TOP));
    await go(`l/${L.Alpha}`); await listShown(L.Alpha); await ready(`${TOP} === ${topA}`, 30);

    // ================= the sidebar keeps its own place per area
    const sideMax = await ev(`(() => { const s = document.querySelector('#side'); return s ? s.scrollHeight - s.clientHeight : 0; })()`);
    check(sideMax > 100, 'desktop: the sidebar scrolls (30 more lists) ' + sideMax);
    await ev(`(document.querySelector('#side').scrollTop = ${Math.round(sideMax * .6)}, 1)`);
    const sideTop = await ev(`document.querySelector('#side').scrollTop`);
    check(await ready(`(() => { const o = JSON.parse(localStorage.getItem('tasks.viewMem') || '{}'); return Object.keys(o).some(k => k.startsWith('side|') && k.endsWith('|tasks') && o[k].y > 0); })()`, 30), 'desktop: the sidebar\'s place is written');

    // ================= an office document scrolled far down -> a list -> back over the office icon
    await go(`office/offers/${D}`);
    check(await ready(`S.route.mod === 'office' && ${OPEN} && !!${BOX}`, 100), 'desktop: the offer is open ' + await ev(`location.hash + ' ' + document.querySelector('#view').textContent.slice(0, 200)`));
    const oy = await ev(`(() => { const b = ${BOX}; b.scrollTop = Math.round((b.scrollHeight - b.clientHeight) * .8); return b.scrollTop; })()`);
    check(oy > 100, 'desktop: the offer scrolled far down ' + oy);
    await shot('p2413a-offer-before.png');
    check(await ready(`(() => { const o = JSON.parse(localStorage.getItem('tasks.viewMem') || '{}'); return Object.keys(o).some(k => k.includes('office/offers/${D}')); })()`, 30), 'desktop: the place in the offer is written');
    const sbbTasks = await ev(`(() => { const b = document.querySelector('#srail [data-sbb="tasks"]'); if (b) b.click(); return !!b; })()`);
    if (!sbbTasks) await go(`l/${L.Alpha}`);
    check(await listShown(L.Alpha) && await ready(`${TOP} === ${topA}`, 30), 'desktop: the projects icon leads back to Alpha at its row ' + await ev(TOP));
    check(await ready(`Math.abs(document.querySelector('#side').scrollTop - ${sideTop}) <= 2`, 30), 'desktop: the sidebar of the projects stands where it was ' + sideTop + ' / ' + await ev(`document.querySelector('#side').scrollTop`));
    const sbbOffice = await ev(`(() => { const b = document.querySelector('#srail [data-sbb="office"]'); if (b) b.click(); return !!b; })()`);
    if (!sbbOffice) await go(`office/offers/${D}`);
    check(await ready(`location.hash === '#office/offers/${D}' && ${OPEN}`, 100), 'desktop: the office icon opens the same offer again ' + await ev('location.hash'));
    check(await ready(`(() => { const b = ${BOX}; return !!b && Math.abs(b.scrollTop - ${oy}) <= 2; })()`, 50), 'desktop: the offer at the same place ' + oy + ' / ' + await ev(`(${BOX} || {}).scrollTop`));
    await shot('p2413a-offer-after.png');

    // ================= after a reload
    await go(`l/${L.Alpha}`); await listShown(L.Alpha); await ready(`${TOP} === ${topA}`, 30);
    await reload(`l/${L.Alpha}`);
    check(await up() && await listShown(L.Alpha), 'reload: Alpha is shown');
    check(await ready(`${TOP} === ${topA}`, 50), 'reload: the same row of Alpha on top ' + topA + ' / ' + await ev(TOP));
    check(await ready(`Math.abs(document.querySelector('#side').scrollTop - ${sideTop}) <= 2`, 30), 'reload: the sidebar where it was ' + await ev(`document.querySelector('#side').scrollTop`));
    check(await ev(`Object.keys(JSON.parse(localStorage.getItem('tasks.viewMem') || '{}')).length <= VM_MAX`), 'at most VM_MAX views are kept');

    // ================= phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await reload(`l/${L.Beta}`), 'phone: a new page');
    check(await up() && await ev('isMobile()') && await listShown(L.Beta), 'phone: list Beta');
    await scrollTo(25);
    const topP = await ev(TOP);
    check(await kept(`t:l:${L.Beta}`), 'phone: the place is written');
    await go(`l/${L.Alpha}`);
    check(await listShown(L.Alpha), 'phone: list Alpha');
    await go(`l/${L.Beta}`);
    check(await listShown(L.Beta) && await ready(`${TOP} === ${topP}`, 30), 'phone: back in Beta the same row on top ' + topP + ' / ' + await ev(TOP));
    await shot('p2413a-phone.png');

    // ================= the task open in the panel: the view keeps it (after a reload it opens again), a completed one not
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 720}});
    const open = T.Beta[27], gone = T.Beta[28];
    await reload(`l/${L.Beta}`); await up(); await listShown(L.Beta);
    await ev(`(openDetail(${open}), 1)`);
    check(await ready(`S.sel === ${open}`), 'desktop: a task of Beta open in the panel');
    await go(`l/${L.Alpha}`); await listShown(L.Alpha);
    await ev(`(closeDetail(), 1)`); await ready(`!S.sel`);
    check(await reload(`l/${L.Beta}`), 'reload: a new page');
    check(await up() && await listShown(L.Beta), 'reload: Beta');
    check(await ready(`S.sel === ${open}`, 30), 'reload: the task open in Beta is open again ' + await ev(`JSON.stringify([S.sel, VM.key, VM.want, Object.entries(JSON.parse(localStorage.getItem('tasks.viewMem') || '{}')).map(([k, o]) => k + ':' + o.sel + ':' + o.y)])`));
    await ev(`(openDetail(${gone}), 1)`); await ready(`S.sel === ${gone}`);
    await go(`l/${L.Alpha}`); await listShown(L.Alpha);
    await ev(`(closeDetail(), 1)`); await ready(`!S.sel`);
    check((await call(CF, 'POST', `/api/tasks/${gone}/complete`)).http < 300, 'the task is completed elsewhere');
    await reload(`l/${L.Beta}`);
    check(await up() && await listShown(L.Beta) && await ready(`!VM.want`, 30), 'reload: Beta, its place is back');
    check(await ev(`S.sel`) !== gone, 'reload: the completed task is not opened again ' + await ev('S.sel'));

    // ================= counter-check: the same way without the hooks does not keep the place
    await reload(`l/${L.Alpha}`); await up(); await listShown(L.Alpha);
    await ev(`(window.vm_after = () => 0, window.vm_leave = () => 0, 1)`);
    await scrollTo(35);
    const topC = await ev(TOP);
    await go(`l/${L.Beta}`); await listShown(L.Beta);
    await scrollTo(5);
    await go(`l/${L.Alpha}`); await listShown(L.Alpha);
    check(await ev(TOP) !== topC, 'counter-check: without viewmem the row is lost ' + topC + ' / ' + await ev(TOP));
  });

  console.log(`p2413_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
