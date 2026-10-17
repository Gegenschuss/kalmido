// 2.66.0 UI tests (part A, #1835), own container (start.sh). jsdom, invented data only:
// - #1835 merging contacts: the selection bar has Merge, waiting for two ticks; the dialog step 1 lists the contacts to
//   keep and the differing fields (a choice per field), the joined phones; step 2 shows the server's overview (what moves)
//   and the note that the others are gone; Merge sends one request, ends the selection and opens the target's card; the
//   toast's Undo puts the contact back (one step); the card's history line has Undo; on the phone the bar and the dialog work
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p266_a_ui', check, shots: 'P266A_SHOTS'});  // 2.80.0 (#1897): the real phone layout
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});  // KMT_NOSTART=1: a running app
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,contacts'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,contacts'}, CB);
  const BK = (await call('POST', '/api/books', {name: 'Mine'}, CB)).id;
  const mk = b => call('POST', '/api/contacts', {book_id: BK, ...b}, CB);
  const C1 = (await mk({given: 'Erika', family: 'Muster', phones: [{value: '+49 30 111'}]})).id;
  const C2 = (await mk({given: 'Erika', family: 'Mustermann', phones: [{value: '+49 170 222'}], emails: [{value: 'erika@example.com'}]})).id;
  await mk({given: 'Third', family: 'Person'});
  const T = (await call('POST', '/api/tasks', {title: 'Call Erika'}, CB)).id;
  check((await call('POST', `/api/tasks/${T}/contacts`, {contact_id: C2, kind: 'about'}, CB)).http === 200, 'a task linked to the second contact');

  let w = await boot({user: 'bob', hash: 'contacts'}); let d = w.document;
  const row = n => [...d.querySelectorAll('#view .ctrow')].find(x => x.textContent.includes(n));
  await until(() => d.querySelectorAll('#view .ctrow').length === 3, 60);
  d.querySelector('[data-ct="pick"]').click(); await sleep(50);
  const mb = () => d.querySelector('#ct-sbar [data-ctb="merge"]');
  check(!!mb() && mb().disabled, '#1835: Merge in the bar, waiting for ticks');
  row('Erika Muster').click(); await sleep(50);
  check(mb().disabled, '#1835: one tick: Merge still waits');
  row('Erika Mustermann').click(); await sleep(50);
  check(!mb().disabled, '#1835: two ticks: Merge is ready');
  mb().click();
  await until(() => d.querySelector('.modal.mgdlg .mgset'), 40);
  const md = d.querySelector('.modal.mgdlg');
  check(!!md && /Merge 2 contacts/.test(md.querySelector('h3').textContent), '#1835: the merge dialog opens');
  const keep = [...md.querySelectorAll('input[name="mg-t"]')];
  check(keep.length === 2 && keep[0].checked, '#1835: step 1 offers both to keep, the first is chosen');
  const fam = [...md.querySelectorAll('input[name="mg-f-family"]')];
  check(fam.length === 2 && fam[0].checked, '#1835: the differing last name offers both values');
  check(!md.querySelector('input[name="mg-f-given"]') && /First name/.test(md.querySelector('.mgsame')?.textContent || ''), '#1835: the same first name is no choice');
  check(/\+49 30 111/.test(md.querySelector('.mgjoin')?.textContent || '') && /\+49 170 222/.test(md.querySelector('.mgjoin').textContent), '#1835: the phones are joined');
  fam[1].checked = true; fam[1].dispatchEvent(new w.Event('change', {bubbles: true}));
  const fn = [...md.querySelectorAll('input[name="mg-f-fn"]')];  // the display name is its own choice
  check(fn.length === 2, '#1835: the differing name offers both values');
  fn[1].checked = true; fn[1].dispatchEvent(new w.Event('change', {bubbles: true}));
  md.querySelector('[data-m="next"]').click();
  await until(() => md.querySelector('.mglines li'), 40);
  const lines = [...md.querySelectorAll('.mglines li')].map(x => x.textContent);
  check(lines.includes('Task links: 1') && lines.includes('E-mail addresses added: 1'), '#1835: step 2 shows the server overview ' + lines.join('|'));
  check(/gone afterwards/.test(md.querySelector('.mgwarn')?.textContent || ''), '#1835: ... and that the other is gone afterwards');
  check((await call('GET', `/api/contacts/${C2}`, null, CB)).http === 200, '#1835: the overview changed nothing');
  md.querySelector('[data-m="run"]').click();
  await until(() => !d.querySelector('.modal.mgdlg') && d.querySelector('#ct-h'), 60);
  check(!d.querySelector('.modal.mgdlg'), '#1835: the dialog closes');
  check(w.eval('CT.pick') === null, '#1835: the selection ended');
  await until(() => d.querySelectorAll('#view .ctrow').length === 2 && /Mustermann/.test(d.querySelector('#ct-h')?.textContent || ''), 60);
  check(d.querySelectorAll('#view .ctrow').length === 2, '#1835: one contact fewer in the list');
  check(/Erika Mustermann/.test(d.querySelector('#ct-h')?.textContent || '') && w.eval('CT.sel') === C1, '#1835: the target card opens with the picked name');
  check((await call('GET', `/api/contacts/${C2}`, null, CB)).http === 404, '#1835: the other contact is gone');
  check(/1 contact merged|2 contacts merged/.test(d.querySelector('#toast')?.textContent || ''), '#1835: a toast with Undo ' + (d.querySelector('#toast')?.textContent || ''));
  check(/Merged with Erika Mustermann/.test(d.querySelector('.ctmsec')?.textContent || '') && !!d.querySelector('.ctmsec [data-ctmundo]'), '#1835: the card shows the history line with Undo');
  // the toast's Undo
  d.querySelector('#toast button').click();
  await until(async () => (await call('GET', `/api/contacts/${C2}`, null, CB)).http === 200, 40);
  check((await call('GET', `/api/contacts/${C2}`, null, CB)).http === 200, '#1835: Undo in the toast brings the contact back');
  await until(() => d.querySelectorAll('#view .ctrow').length === 3, 60);
  check(d.querySelectorAll('#view .ctrow').length === 3, '#1835: ... and the list shows it again');
  check((await call('GET', `/api/contacts/${C1}`, null, CB)).family === 'Muster', '#1835: ... the target has its old last name');
  w.close();

  // the history's Undo (merge by API, then the card); the phone: bar + dialog
  const j = await call('POST', '/api/contacts/merge', {target: C1, ids: [C2]}, CB);
  check(j.http === 200 && j.run_id, 'merged again by the API');
  w = await boot({user: 'bob', hash: 'contacts/' + C1, mobile: true}); d = w.document;
  await until(() => d.querySelector('.ctmsec [data-ctmundo]'), 60);
  const ub = d.querySelector('.ctmsec [data-ctmundo]');
  check(!!ub && ub.getBoundingClientRect, '#1835 phone: the card has the history with Undo');
  ub.click();
  await until(async () => (await call('GET', `/api/contacts/${C2}`, null, CB)).http === 200, 40);
  check((await call('GET', `/api/contacts/${C2}`, null, CB)).http === 200, '#1835 phone: Undo on the card brings the contact back');
  await until(() => /Merge undone/.test(d.querySelector('#toast')?.textContent || ''), 30);
  check(/Merge undone/.test(d.querySelector('#toast')?.textContent || ''), '#1835 phone: a short confirmation');
  w.close();
  w = await boot({user: 'bob', hash: 'contacts', mobile: true}); d = w.document;
  await until(() => d.querySelectorAll('#view .ctrow').length === 3, 60);
  w.eval(`bk_start(${C1}); CT.pick.add(${C2}); ctDraw();`); await sleep(50);
  check(!!d.querySelector('#ct-sbar [data-ctb="merge"]') && !d.querySelector('#ct-sbar [data-ctb="merge"]').disabled, '#1835 phone: Merge in the bar');
  d.querySelector('#ct-sbar [data-ctb="merge"]').click();
  await until(() => d.querySelector('.modal.mgdlg .mgset'), 40);
  check(!!d.querySelector('.modal.mgdlg [data-m="next"]'), '#1835 phone: the dialog opens');
  d.querySelector('.modal.mgdlg [data-m="close"]').click();
  await until(() => !d.querySelector('.modal.mgdlg'), 20);
  check(!d.querySelector('.modal.mgdlg') && (await call('GET', `/api/contacts/${C2}`, null, CB)).http === 200, '#1835 phone: Cancel changes nothing');
  w.close();

  // 2.80.0 (#1897) Firefox at 402 px with touch, German (the longest labels): the selection bar never scrolls sideways,
  // "Clear selection" lies on the screen, the toast's Undo button is at least 44 px high
  await call('PATCH', '/api/settings', {lang: 'de'}, CB);
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'bob', password: 'password123'})}).then(r => r.status)`) === 200, '#1897 Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await nav(B + '?v=1897#contacts');
    for (let i = 0; i < 30 && !(await ev(`document.querySelectorAll('#view .ctrow').length >= 2`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { const ids = [...document.querySelectorAll('#view .ctrow[data-ctopen]')].map(x => +x.dataset.ctopen); bk_start(ids[0]); CT.pick.add(ids[1]); ctDraw(); return 1; })()`); await sleep(400);
    const bar = await ev(`(() => { const b = document.querySelector('#ct-sbar'), x = b && b.querySelector('.mbx'), r = x && x.getBoundingClientRect();
      return b ? {sw: b.scrollWidth, cw: b.clientWidth, xr: r ? Math.round(r.right) : -1, xh: r ? Math.round(r.height) : 0, vw: innerWidth, doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1} : null; })()`);
    check(bar && bar.sw <= bar.cw + 1 && bar.xr > 0 && bar.xr <= bar.vw && bar.doc, '#1897: the selection bar fits, no sideways scrolling, Clear selection on screen ' + JSON.stringify(bar));
    await shot('p266a-1897-bar-402.png');
    const th = await ev(`(() => { toast('Kontakte zusammengeführt', () => {}); const b = document.querySelector('#toast button:not(.tx)'); return b ? Math.round(b.getBoundingClientRect().height) : 0; })()`);
    check(th >= 44, '#1897: the toast\'s Undo button at least 44 px high: ' + th);
  }, true);
  await call('PATCH', '/api/settings', {lang: 'en'}, CB);

  console.log(`p266_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
