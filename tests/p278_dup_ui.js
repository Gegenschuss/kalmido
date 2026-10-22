// 2.78.0 UI test (#1881, "Duplicate list"), own container (start.sh), Firefox (desktop + phone):
// - the list menu offers "Duplicate list…": the dialog suggests "<list> (copy)", "Copy completed tasks too" is off, Duplicate
//   opens the copy (toast "List duplicated"); the copy has the open tasks only, with the box ticked the completed ones too
// - the list dialog has a "Duplicate" button next to "Save as template"; on a phone the dialog and its foot fit the screen
// - a participant gets no entry
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p278_dup_ui', check, shots: 'P278_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const FEAT = 'comments,collab,progress';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Harbour site'})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: bob.id, role: 'participant'});
  await call(CA, 'POST', '/api/sections', {list_id: L, name: 'Planning'});
  await call(CA, 'POST', '/api/tasks', {title: 'Survey the quay', list_id: L});
  const TD = (await call(CA, 'POST', '/api/tasks', {title: 'Site visit', list_id: L})).id;
  await call(CA, 'POST', `/api/tasks/${TD}/complete`, {});
  const titles = async lid => [...(await call(CA, 'GET', '/api/state')).tasks, ...((await call(CA, 'GET', '/api/tasks?scope=done')).tasks || [])]
    .filter(t => t.list_id === lid).map(t => t.title).filter((x, i, a) => a.indexOf(x) === i).sort();

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const until = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const ffLogin = async user => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
    };
    const openMenuEntry = async () => {
      await ev(`(() => { listMenu(document.querySelector('#top h1'), ${L}); return 1; })()`); await sleep(300);
      // 2.152.2 (#2624): project instead of list
      return ev(`(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => /Duplicate project…/.test(x.textContent)); if (b) b.click(); return !!b; })()`);
    };
    const dup = async (done, name) => {
      check(await until(`!!document.querySelector('.modal.ldmodal #ld-name')`), 'the duplicate dialog opens');
      if (name) await ev(`(() => { document.querySelector('#ld-name').value = ${JSON.stringify(name)}; return 1; })()`);
      if (done) await ev(`(() => { document.querySelector('#ld-done').click(); return 1; })()`);
      await ev(`(() => { document.querySelector('.modal.ldmodal [data-m="ok"]').click(); return 1; })()`);
      // 2.152.2 (#2624): project instead of list
      check(await until(`!document.querySelector('.modal.ldmodal') && /Project duplicated/.test(document.querySelector('#toast')?.textContent || '')`, 60), 'duplicated: dialog closed, toast');
      check(await until(`/^#l\\/\\d+$/.test(location.hash) && location.hash !== '#l/${L}'`, 40), 'the copy is open ' + await ev('location.hash'));
      return +(await ev('location.hash')).slice(3);
    };

    // ================= desktop: list menu, default copy
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    check(await ffLogin('alice') === 200, 'alice login');
    await nav(B + '#l/' + L);
    check(await until(`typeof listDuplicate === 'function' && !!document.querySelector('#view .trow')`, 60), 'list rendered');
    check(await openMenuEntry(), 'the list menu has "Duplicate list…"');
    check(await until(`!!document.querySelector('.modal.ldmodal #ld-name')`), 'dialog');
    const dlg = await ev(`(() => { const m = document.querySelector('.modal.ldmodal'); return {h: m.querySelector('h3').textContent, v: m.querySelector('#ld-name').value, done: m.querySelector('#ld-done').checked, hint: m.querySelector('.shint').textContent}; })()`);
    check(dlg.h === 'Duplicate “Harbour site”' && dlg.v === 'Harbour site (copy)' && dlg.done === false && /Members, shares and assignees do not/.test(dlg.hint), 'dialog: title, name, box off, hint ' + JSON.stringify(dlg));
    await sleep(600); await shot('p278-dialog-desktop.png');
    const C1 = await dup(false);
    check(JSON.stringify(await titles(C1)) === JSON.stringify(['Survey the quay']), 'default copy: open tasks only');
    check(await until(`/Harbour site \\(copy\\)/.test(document.querySelector('#top h1')?.textContent || '')`), 'the copy\'s header');

    // ================= phone: list dialog button, with the completed tasks
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + L);
    check(await until(`!!document.querySelector('#view .trow')`, 60), 'phone: list rendered');
    await ev(`(() => { listModal(${L}); return 1; })()`);
    check(await until(`!!document.querySelector('.modal [data-m="dup"]')`), 'list dialog: the Duplicate button');
    const foot = await ev(`(() => { const f = document.querySelector('.modal [data-m="dup"]').closest('.foot'); return {sw: f.scrollWidth, cw: f.clientWidth, tpl: !!f.querySelector('[data-m="tpl"]')}; })()`);
    check(foot.tpl && foot.sw <= foot.cw + 1, 'phone: the foot with "Save as template" and "Duplicate" fits ' + JSON.stringify(foot));
    await sleep(600); await shot('p278-listdialog-phone.png');
    await ev(`(() => { document.querySelector('.modal [data-m="dup"]').click(); return 1; })()`);
    check(await until(`!!document.querySelector('.modal.ldmodal')`), 'phone: the duplicate dialog');
    const w = await ev(`document.querySelector('.modal.ldmodal').getBoundingClientRect().width`);
    check(w <= 390, 'phone: the dialog fits ' + w);
    await sleep(600); await shot('p278-dialog-phone.png');
    const C2 = await dup(true, 'Harbour archive');
    check(JSON.stringify(await titles(C2)) === JSON.stringify(['Site visit', 'Survey the quay']), 'with the box: the completed task too ' + JSON.stringify(await titles(C2)));

    // ================= a participant: no entry
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    check(await ffLogin('bob') === 200, 'bob login');
    await nav(B + '#l/' + L);
    check(await until(`typeof listMenuItems === 'function' && !!document.querySelector('#top h1')`, 60), 'bob: list rendered');
    const lab = await ev(`listMenuItems(${L}, document.querySelector('#top h1')).flatMap(x => x === '-' ? [] : x.more ? [x, ...x.more] : [x]).map(x => x.label).join('|')`);
    // 2.152.2 (#2624): project instead of list
    check(!/Duplicate project…/.test(lab), 'participant: no "Duplicate list…" ' + lab);
  });
  console.log(`p278_dup_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
