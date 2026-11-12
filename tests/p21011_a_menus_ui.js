// 2.1011.0 UI test, part A (#5688 the document view's "Actions", #5689 the plus of the chat box): both are the shared menu()
// kalmido-suite: fresh
// Own container (start.sh; P2998A_NOSTART=1 / KMT_NOSTART=1: it runs already), Firefox. Invented names only.
// freelancer-matrix: docs (a person without organisation owns the document)
// #5688 (1440 px, a mouse; then a phone 390 px):
// - "Actions" opens the shared menu (#pop, role=menu, the focus on its first entry) with "New task", "Link with a task…" and
//   "Add to favourites" above the rarer actions; Escape closes it and the focus is back on "Actions"
// - "New task" creates the task and links it (the server says so); then "Actions" offers "Open task" instead, and that one opens it
// - "Add to favourites": the document is a favourite (also after a reload), the menu then offers "Remove from favourites"
// - a second document: "Link with a task…" opens the picker; a task chosen there is linked (server), "Open task" follows
// - a reader (view share): "Actions" without "New task" / "Link with a task…", but with the star
// - phone 390 px: "Actions" is the sheet from below with the title "Actions" and its X; the X closes it
// #5689 (the team chat):
// - phone 390 px: the plus opens the sheet "More" with the tools as entries; "Attach images or files" opens the file picker,
//   the sheet closes and the focus is back in the box; Escape closes the sheet
// - computer 1280 px: no plus, the tools stand in the row
// P21011A_SHOTS=1: pictures.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const firefox = require('./ff')({tag: 'p21011_a_menus_ui', check, shots: 'P21011A_SHOTS'});
const {realClick} = require('./ff');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2998A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const up = async (ck, name, text) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).ids?.[0];
};
// in the page: the open menu (#pop) - its entries by their label
const MENU = `window.__mi = lab => [...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.querySelector('.ml')?.firstChild?.textContent === lab);
window.__menu = () => { const p = document.querySelector('#pop'); if (!p || p.classList.contains('hidden') || !p.querySelector('[role="menu"]')) return {open: false};
  const r = p.getBoundingClientRect();
  return {open: true, labels: [...p.querySelectorAll('[role="menuitem"]')].map(b => b.querySelector('.ml')?.firstChild?.textContent || ''), sheet: p.classList.contains('sheet'),
    title: p.querySelector('.tch-sht')?.textContent || '', x: !!p.querySelector('.tch-shx'), inside: r.left >= -1 && r.right <= innerWidth + 1 && r.top >= -1 && r.bottom <= innerHeight + 1,
    rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom), innerWidth, innerHeight],
    focus: !!document.activeElement?.closest?.('#pop [role="menuitem"]')}; };
window.__mark = lab => { document.querySelectorAll('[data-t998]').forEach(x => x.removeAttribute('data-t998')); const b = __mi(lab); if (b) b.setAttribute('data-t998', '1'); return !!b; };
1`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const bu = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: []});
  check(fu.http < 300 && bu.http < 300, 'a person without organisation (frida) and a reader (bob) ' + [fu.http, bu.http]);
  const CF = await login('frida'), CB = await login('bob');
  const FEAT = 'cal,comments,docs,files,team,collab';
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida has no organisation');
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Wohnung'})).id;
  const T = (await call(CF, 'POST', '/api/tasks', {title: 'Nebenkosten prüfen', list_id: L})).id;
  // the team chat: a list of alice's shared with bob has its channel (as tests/p2213_ui.js)
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const LA = (await call(CA, 'POST', '/api/lists', {name: 'Dreh'})).id;
  await call(CA, 'PUT', `/api/lists/${LA}/members`, {user_id: bu.id, role: 'edit'});
  const D1 = await up(CF, 'vertrag.txt', 'Mietvertrag Beispiel Nummer 12');
  const D2 = await up(CF, 'abrechnung.txt', 'Nebenkostenabrechnung Beispiel 2026');
  for (const id of [D1, D2]) for (let i = 0; i < 200 && !['done', 'failed'].includes((await call(CF, 'GET', `/api/docs/${id}`)).state); i++) await sleep(300);
  check(L && T && D1 && D2, 'setup: list, task, two documents ' + [L, T, D1, D2]);
  const sh = await call(CF, 'POST', `/api/files/nodes/${D1}/shares`, {user_id: bu.id, role: 'view'});
  check(sh.http < 300, 'the first document shared with bob to read ' + sh.http);
  const RID = ((await call(CA, 'GET', '/api/team')).rooms || []).find(x => x.list_id === LA)?.id;
  check(RID, 'the list channel ' + RID);

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
    const press = async (sel, what) => { const c = await realClick(o, sel); check(c.ok, `${what}: pressed with the mouse (${c.on})`); return c.ok; };
    const pick = async (lab, what) => (await ev(`__mark(${JSON.stringify(lab)})`)) ? press('#pop [data-t998]', what) : check(false, `${what}: the entry "${lab}" ` + JSON.stringify(await ev(`__menu()`)));
    const signIn = async u => { await nav(B + 'static/icon.svg'); await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`); };
    const openDoc = async id => { await nav(B + `#docs/${id}`); await wait(`typeof S !== 'undefined' && !!S.booted && DC.doc?.id === ${id} && !!document.querySelector('.dv-view [data-dc="actsmore"]')`, 100); await ev(MENU); };
    const acts = async () => { await press('.dv-view [data-dc="actsmore"]', 'Actions'); return wait(`__menu().open`, 20); };

    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    check(await signIn('frida') === 200, 'Firefox: frida signs in');

    // ================= #5688: the document view's "Actions"
    await openDoc(D1);
    check(await acts(), '#5688: "Actions" opens the shared menu');
    let m = await ev(`__menu()`);
    check(m.labels[0] === 'New task' && m.labels[1] === 'Link with a task…' && m.labels[2] === 'Add to favourites', '#5688: task and star on top ' + JSON.stringify(m.labels));
    check(['Share…', 'Upload a new version…', 'Move to…'].every(x => m.labels.includes(x)), '#5688: the rarer actions stay in it ' + JSON.stringify(m.labels));
    check(m.focus && !m.sheet && m.inside, '#5688: the focus on its first entry, a popover inside the window ' + JSON.stringify(m));
    await shot('p21011-a-actions-1440.png');
    await ev(`(() => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    check(await wait(`!__menu().open`, 20), '#5688: Escape closes it');
    check(await wait(`document.activeElement?.dataset?.dc === 'actsmore'`, 20), '#5688: the focus is back on "Actions" ' + await ev(`document.activeElement?.className || '-'`));
    check(await ev(`!!document.querySelector('.dv-view') && DC.doc?.id === ${D1}`), '#5688: Escape closed only the menu, the view stays');

    // New task: created and linked; then "Open task"
    await acts();
    await pick('New task', '#5688: New task');
    let d1 = {};
    for (let i = 0; i < 40 && !d1.task_id; i++) { d1 = await call(CF, 'GET', `/api/docs/${D1}`); if (!d1.task_id) await sleep(250); }
    check(d1.task_id > 0, '#5688: "New task" created the task, linked with the document (server) ' + d1.task_id);
    check(await wait(`DC.doc?.task_id === ${d1.task_id || 0} || DC.doc?.task?.id === ${d1.task_id || 0}`, 30), '#5688: the view knows the task');
    await acts();
    m = await ev(`__menu()`);
    check(m.labels.includes('Open task') && !m.labels.includes('New task') && !m.labels.includes('Link with a task…'), '#5688: a linked task: "Open task" instead ' + JSON.stringify(m.labels));
    await pick('Open task', '#5688: Open task');
    check(await wait(`S.sel === ${d1.task_id || 0} && !document.querySelector('#detail').classList.contains('hidden') && !!document.querySelector('#detail #d-title')`, 30), '#5688: "Open task" opens the task in its panel ' + await ev(`JSON.stringify([location.hash, S.sel, document.querySelector('#detail')?.className])`));

    // the star
    await openDoc(D1);
    await acts();
    await pick('Add to favourites', '#5688: Add to favourites');
    check(await wait(`fv2_is('doc:${D1}')`, 30), '#5688: the document is a favourite');
    await openDoc(D1);
    await acts();
    check(await ev(`!!__mi('Remove from favourites') && !__mi('Add to favourites')`), '#5688: the menu then offers "Remove from favourites" ' + JSON.stringify((await ev(`__menu()`)).labels));
    await ev(`(closePop(), 1)`);
    await nav(B + 'static/icon.svg');
    await openDoc(D1);
    check(await ev(`fv2_is('doc:${D1}')`), '#5688: still a favourite after a reload');

    // the second document: "Link with a task…" through the picker
    await openDoc(D2);
    await acts();
    await pick('Link with a task…', '#5688: Link with a task…');
    check(await wait(`!!document.querySelector('.dsp-pick [data-pick="${T}"]')`, 30), '#5688: the picker lists the open task');
    await press(`.dsp-pick [data-pick="${T}"]`, '#5688: the task in the picker');
    let d2 = {};
    for (let i = 0; i < 40 && d2.task_id !== T; i++) { d2 = await call(CF, 'GET', `/api/docs/${D2}`); if (d2.task_id !== T) await sleep(250); }
    check(d2.task_id === T, '#5688: the chosen task is linked (server) ' + d2.task_id);
    check(await wait(`!document.querySelector('.dsp-pick')`, 20) && await acts() && await ev(`!!__mi('Open task')`), '#5688: then "Actions" offers "Open task"');
    await ev(`(closePop(), 1)`);

    // phone: the sheet with its title and X
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await openDoc(D2);
    await ev(`(() => { document.querySelector('.dv-view [data-dc="actsmore"]').click(); return 1; })()`);
    check(await wait(`__menu().open && __menu().inside`, 20), '#5688 phone: "Actions" opens inside the window ' + JSON.stringify(await ev(`__menu().rect`)));
    m = await ev(`__menu()`);
    check(m.sheet && m.title === 'Actions' && m.x && m.inside && m.labels.includes('Open task'), '#5688 phone: the sheet from below with the title "Actions" and X ' + JSON.stringify(m));
    await shot('p21011-a-actions-390.png');
    await ev(`(() => { document.querySelector('#pop .tch-shx').click(); return 1; })()`);
    check(await wait(`!__menu().open`, 20), '#5688 phone: the X closes the sheet');

    // ================= #5689: the plus of the team chat box (alice's list channel)
    check(await signIn('alice') === 200, 'Firefox: alice signs in');
    await nav(B + '#team/' + RID);
    check(await wait(`typeof S !== 'undefined' && !!S.booted && !!document.querySelector('#tc-in')`, 100), '#5689: the team chat box');
    await ev(MENU);
    const plus = '.tccomp:not(.tthcomp) [data-chmore]';
    check(await wait(`(() => { const p = document.querySelector(${JSON.stringify(plus)}); return !!p && getComputedStyle(p).display !== 'none' && getComputedStyle(p.parentElement.querySelector('.chtools')).display === 'none'; })()`, 30), '#5689 phone: one plus, the tools not in the row ' + await ev(`document.querySelector('.tccomp')?.innerHTML?.replace(/<svg.*?<\\/svg>/g, '').slice(0, 400) || '-'`));
    await ev(`(() => { document.querySelector(${JSON.stringify(plus)}).click(); return 1; })()`);
    check(await wait(`__menu().open && __menu().focus && __menu().inside`, 20), '#5689 phone: the plus opens the menu (the sheet slid in)');
    m = await ev(`__menu()`);
    check(m.sheet && m.title === 'More' && m.x && m.inside && m.labels.includes('Attach images or files'), '#5689 phone: the sheet "More" with the tools ' + JSON.stringify(m));
    await shot('p21011-a-plus-390.png');
    await ev(`(() => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    check(await wait(`!__menu().open`, 20), '#5689 phone: Escape closes the sheet');
    await ev(`(() => { document.querySelector(${JSON.stringify(plus)}).click(); return 1; })()`);
    await wait(`__menu().open`, 20);
    await ev(`(() => { window.__picked = 0; const f = document.querySelector('#tc-file'); f.click = () => { window.__picked++; }; __mi('Attach images or files').click(); return 1; })()`);
    check(await wait(`window.__picked === 1 && !__menu().open`, 20), '#5689 phone: "Attach images or files" opens the file picker, the sheet closes');
    check(await wait(`document.activeElement?.id === 'tc-in'`, 20), '#5689 phone: the focus is back in the box ' + await ev(`document.activeElement?.id || document.activeElement?.className || '-'`));

    // the computer: the tools in the row, no plus
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await nav(B + '#team/' + RID);
    check(await wait(`typeof S !== 'undefined' && !!S.booted && !!document.querySelector('#tc-in')`, 100), '#5689 computer: the team chat box');
    const ROW = `(() => { const c = document.querySelector('.tccomp:not(.tthcomp)'), p = c?.querySelector('[data-chmore]'), clip = c?.querySelector('.chclip'); return {plus: !!p && getComputedStyle(p).display !== 'none', clip: clip ? Math.round(clip.getBoundingClientRect().width) : -1, pop: !document.querySelector('#pop').classList.contains('hidden'), achat: !!c?.closest('#achat')}; })()`;
    check(await wait(`(() => { const r = ${ROW}; return !r.plus && r.clip >= 40; })()`, 30), '#5689 computer: no plus, the paperclip in the row ' + JSON.stringify(await ev(ROW)));

    // ================= the reader: no task entries, the star stays
    check(await signIn('bob') === 200, 'Firefox: bob signs in');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await openDoc(D1);
    check(await ev(`DC.doc?.role === 'view'`), 'bob reads the shared document ' + await ev(`DC.doc?.role || '-'`));
    check(await acts(), 'bob: "Actions" opens');
    m = await ev(`__menu()`);
    check(!m.labels.includes('New task') && !m.labels.includes('Link with a task…') && !m.labels.includes('Move to…'), 'bob (reader): no task to create or link, nothing that writes ' + JSON.stringify(m.labels));
    check(m.labels.includes('Add to favourites') || m.labels.includes('Remove from favourites'), 'bob (reader): the star ' + JSON.stringify(m.labels));
  }, false);

  console.log(`p21011_a_menus_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
