// 2.1.0 UI tests (jsdom), own container (start.sh) with KALMIDO_SECRET_KEY, the legacy Paperless connection from the
// environment and the fake Paperless (fake_services.py) inside:
// #317 Settings > Notifications: the matrix (events x News / Push, reminder without News, saved per checkbox, undo),
//      German, phone; the list bell (list menu > Notifications, the list dialog, the muted icon in the sidebar)
// #180 Settings > Integrations: my connections (server ones with "no token yet" / "•••• set", enter a token, my own
//      connection), never a token in the page; the admin's server connections without anyone's personal one; the link
//      dialog picks the connection
// #335 waiting on external: task menu > dialog (note + follow-up day), the chip on the row, the bar in the task panel,
//      the smart view "Waiting on external", clearing with one click (+ undo), the News / history texts; SW v60
const {execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const KEY = require('crypto').randomBytes(32).toString('base64');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
  EXTRA: `-e KALMIDO_SECRET_KEY=${KEY} -e PAPERLESS_TOKEN=pl-legacy-env-token -e PAPERLESS_API=http://127.0.0.1:8082 -e PAPERLESS_PUBLIC_URL=https://paperless.example.test`}});
fs.copyFileSync(path.join(__dirname, 'fake_services.py'), path.join(DATA, 'fake_services.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_services.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,agents';
const TOKEN = 'bob-ui-server-token-4c2e', PTOKEN = 'bob-ui-personal-token-9d1f';

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(6[0-9]|7[0-2])'/.test(SW), 'service worker cache v60 (2.1.1: v61, 2.1.2: v62, 2.2.0: v63, 2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, CKB);
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: BOB, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Quote from the carpenter', list_id: TEAM})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Invoice', list_id: TEAM})).id;

  // ================= #317 the matrix
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    const w = await boot({user: 'bob', mobile, hash: 'today'}), d = w.document;
    w.eval(`settingsModal('notify')`); await sleep(700);
    const mx = d.querySelector('#sp-notify .nmx');
    const rows = [...(mx?.querySelectorAll('.nmr') || [])];
    check(mx && rows.length === 13 && /Event.*News.*Push/.test(mx.querySelector('.nmh').textContent), `${lab}: matrix with every event (${rows.length})`);
    const rem = rows.find(r => /Reminders/.test(r.textContent));
    check(rem && !rem.querySelector('[data-ch="news"]') && rem.querySelector('.nmna') && rem.querySelector('[data-nm="reminder"][data-ch="push"]').checked, `${lab}: reminders push only`);
    check(d.querySelector('[data-nm="reply"][data-ch="push"]').checked && d.querySelector('[data-nm="newtask"][data-ch="push"]').checked === mobile  // the desktop run switched it on
      && !d.querySelector('[data-nm="status"][data-ch="push"]').checked && d.querySelector('[data-nm="status"][data-ch="news"]').checked, `${lab}: defaults`);
    check(!d.querySelector('#sp-notify [data-nk]'), `${lab}: the old News checkboxes are gone`);
    if (!mobile) {
      const cb = d.querySelector('[data-nm="newtask"][data-ch="push"]'); cb.checked = true; change(w, cb); await sleep(700);
      let st = await call('GET', '/api/state', null, CKB);
      check(st.notify.newtask.push === true && JSON.parse(st.settings.notify).newtask.push === 1, 'toggle: saved (notify)');
      const cm = d.querySelector('[data-nm="complete"][data-ch="news"]'); cm.checked = true; change(w, cm); await sleep(700);
      st = await call('GET', '/api/state', null, CKB);
      check(st.notify.complete.news === true && st.settings.news_kinds.split(',').includes('complete'), 'toggle a News of an old event: news_kinds');
      click(w, d.querySelector('.smodal .ssaved [data-m="s-undo"]')); await sleep(900);
      st = await call('GET', '/api/state', null, CKB);
      check(st.notify.complete.news === false && st.notify.newtask.push === true, 'undo takes back the last change');
    }
    w.close();
  }
  await call('PATCH', '/api/settings', {lang: 'de'}, CKB);
  let w = await boot({user: 'bob', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('notify')`); await sleep(700);
  check(/Was dich benachrichtigt/.test(d.querySelector('#s-news-h')?.textContent || '') && /Antworten auf meinen Kommentar/.test(d.querySelector('#sp-notify .nmx').textContent), 'German');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'}, CKB);

  // ================= #317 the list bell
  w = await boot({user: 'bob', hash: 'l/' + TEAM}); d = w.document;
  let items = w.eval(`listMenuItems(${TEAM}, document.querySelector('#top h1')).filter(x => x !== '-').map(x => x.label)`);
  check(items.includes('Notifications: Default'), 'list menu: Notifications: Default ' + items);
  w.eval(`bellMenu(document.querySelector('#top h1'), ${TEAM})`); await sleep(200);
  const bells = [...d.querySelectorAll('#pop .menu-list button')];
  check(bells.map(b => b.textContent.trim()).join('|') === 'All activity|Default|Mute' && bells[1].classList.contains('on'), 'bell menu: All / Default (on) / Mute');
  click(w, bells[2]); await sleep(700);
  check((await call('GET', '/api/state', null, CKB)).lists.find(l => l.id === TEAM).bell === 'mute', 'muted (server)');
  check(d.querySelector(`#side .srow[data-list="${TEAM}"] .bellm`), 'sidebar: the muted icon');
  check(/Notifications for Team: Mute/.test(d.querySelector('#toast').textContent), 'toast names it');
  check((await call('GET', '/api/state')).lists.find(l => l.id === TEAM).bell === 'default', 'only for bob');
  w.eval(`listModal(${TEAM})`); await sleep(500);
  const sel = d.querySelector('.lmodal #l-bell');
  check(sel && sel.value === 'mute' && /only mentions/.test(d.querySelector('#l-bellhint').textContent), 'list dialog: the bell');
  sel.value = 'all'; change(w, sel); await sleep(700);
  check((await call('GET', '/api/state', null, CKB)).lists.find(l => l.id === TEAM).bell === 'all' && /every comment/.test(d.querySelector('#l-bellhint').textContent), 'list dialog: All');
  w.close();
  await call('PUT', `/api/lists/${TEAM}/bell`, {mode: 'default'}, CKB);

  // ================= #180 connections
  const SRV = (await call('POST', '/api/admin/paperless', {name: 'Office', url: 'http://127.0.0.1:8082', users: [BOB]})).id;
  await call('PATCH', '/api/admin/settings', {cal_allow_hosts: '127.0.0.1:8082'});
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('integr')`); await sleep(900);
  let box = d.querySelector('#s-plc');
  let row = box?.querySelector(`[data-plc="${SRV}"]`);
  check(row && /Office/.test(row.textContent) && /no token yet/.test(row.textContent) && /set up by an admin/.test(row.textContent), 'my connections: the server one, no token yet');
  check(box.querySelector('.plnew') && box.querySelector('#plc-tok').type === 'password', 'add my own: a password field');
  w.prompt = () => TOKEN;
  click(w, row.querySelector('[data-plc-act="token"]')); await sleep(1200);
  row = d.querySelector(`#s-plc [data-plc="${SRV}"]`);
  check(row && /•••• set/.test(row.textContent) && row.querySelector('[data-plc-act="untoken"]'), 'token set: "•••• set" + remove');
  d.querySelector('#plc-name').value = 'Private'; d.querySelector('#plc-url').value = 'http://127.0.0.1:8082'; d.querySelector('#plc-tok').value = PTOKEN;
  click(w, d.querySelector('[data-plc-act="add"]')); await sleep(1200);
  const per = [...d.querySelectorAll('#s-plc [data-plc]')].find(r => /Private/.test(r.textContent));
  check(per && /personal · only you/.test(per.textContent) && per.querySelector('[data-plc-act="del"]'), 'my own connection listed');
  check(!d.documentElement.outerHTML.includes(TOKEN) && !d.documentElement.outerHTML.includes(PTOKEN), 'no token anywhere in the page');
  check(w.eval('plConns().length') === 2, 'two usable connections');
  w.close();
  // the link dialog picks the connection
  w = await boot({user: 'bob', hash: 't/' + T2}); d = w.document; await sleep(500);
  w.eval(`plSearchModal(${T2})`); await sleep(900);
  const cs = d.querySelector('.plmodal #pl-conn');
  check(cs && cs.options.length === 2, 'link dialog: connection select');
  check(d.querySelector('.plmodal .plitem img')?.getAttribute('src').includes('conn='), 'thumbnails carry the connection');
  click(w, d.querySelector('.plmodal .plitem')); await sleep(900);
  const lk = (await call('GET', '/api/state', null, CKB)).tasks.find(t => t.id === T2).paperless[0];
  check(lk && lk.conn === +cs.value && lk.title, 'linked with that connection');
  w.eval('renderDetail()'); await sleep(200);
  check(d.querySelector('.plsec .plink a')?.getAttribute('href') === 'http://127.0.0.1:8082/documents/7/details', 'the document opens on its connection: ' + d.querySelector('.plsec .plink a')?.getAttribute('href'));
  w.close();
  // alice (admin): server connections only, bob's link hidden
  w = await boot({user: 'alice', hash: 't/' + T2}); d = w.document; await sleep(500);
  check(/Linked through a Paperless connection you cannot use/.test(d.querySelector('.plsec')?.textContent || ''), "alice: bob's document only as 'a document'");
  w.eval(`settingsModal('users')`); await sleep(1200);
  const pla = d.querySelector('#s-pla');
  check(pla && pla.querySelector(`[data-pla="${SRV}"]`) && /1 token set/.test(pla.textContent) && !/Private/.test(pla.textContent), 'admin: the server connection, not the personal one');
  check(!d.documentElement.outerHTML.includes(TOKEN) && !d.documentElement.outerHTML.includes(PTOKEN) && !d.documentElement.outerHTML.includes('pl-legacy-env-token'), 'admin page: no token');
  w.close();

  // ================= #335 waiting on external
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    if (mobile) await call('DELETE', `/api/tasks/${T1}/waiting`, null, CKB);
    w = await boot({user: 'bob', mobile, hash: 'l/' + TEAM}); d = w.document;
    w.eval(`taskMenu(document.querySelector('#top h1'), ${T1})`); await sleep(200);
    const it = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Waiting on external…');
    check(it, `${lab}: task menu entry`);
    click(w, it); await sleep(300);
    const md = d.querySelector('.modal.waitmodal');
    check(md && md.querySelector('#w-note') && md.querySelector('#w-until'), `${lab}: dialog with note + follow-up day`);
    md.querySelector('#w-note').value = 'carpenter Meier';
    click(w, md.querySelector('[data-m="ok"]')); await sleep(800);
    const t = (await call('GET', '/api/state', null, CKB)).tasks.find(x => x.id === T1);
    check(t.waiting_at && t.wait_note === 'carpenter Meier' && t.wait_until, `${lab}: saved (default follow-up in a week): ${t.wait_until}`);
    const chip = d.querySelector(`#view .trow[data-id="${T1}"] .waitm`);
    check(chip && /Waiting on external: carpenter Meier/.test(chip.title), `${lab}: chip on the row`);
    check(d.querySelector('#side .srow[data-go="waiting"]'), `${lab}: sidebar row "Waiting on external"`);
    w.close();
  }
  w = await boot({user: 'bob', hash: 'waiting'}); d = w.document;
  check([...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).join() === String(T1) && /Waiting on external/.test(d.querySelector('#top h1').textContent), 'the smart view');
  w.eval(`openDetail(${T1})`); await sleep(500);
  const bar = d.querySelector('#detail .waitbar');
  check(bar && /carpenter Meier/.test(bar.textContent) && /follow up/.test(bar.textContent), 'the bar in the task panel');
  click(w, bar.querySelector('[data-act="wait-clear"]')); await sleep(800);
  check(!(await call('GET', '/api/state', null, CKB)).tasks.find(x => x.id === T1).waiting_at && !d.querySelector('#detail .waitbar'), 'one click clears it');
  click(w, d.querySelector('#toast button')); await sleep(800);
  check((await call('GET', '/api/state', null, CKB)).tasks.find(x => x.id === T1).wait_note === 'carpenter Meier', 'undo puts it back');
  check(/Follow up today: waiting on/.test(w.eval(`newsText({kind: 'followup', data: {note: 'x'}}, {})`)) && /added a task/.test(w.eval(`newsText({kind: 'newtask', actor_id: 1, data: {}}, {})`)),
    'News texts: follow-up, new task');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'}, CKB);
  w = await boot({user: 'bob', hash: 'l/' + TEAM}); d = w.document;
  check(/Warten auf Extern/.test(d.querySelector(`#view .trow[data-id="${T1}"] .waitm`)?.title || '') && /Warten auf Extern/.test(d.querySelector('#side').textContent), 'German: Warten auf Extern');
  w.close();

  const e = errs.filter(x => !/Could not load|ECONNREFUSED|fetch failed|NetworkError/.test(x));
  check(!e.length, 'no page errors: ' + e.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
