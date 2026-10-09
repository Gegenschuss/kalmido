// 2.1.0 UI tests (jsdom), own container (start.sh) with KALMIDO_SECRET_KEY (2.36.0: the Paperless part is gone):
// #317 Settings > Notifications: the matrix (events x News / Push, reminder without News, saved per checkbox, undo),
//      German, phone; the list bell (list menu > Notifications, the list dialog, the muted icon in the sidebar)
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
  EXTRA: `-e KALMIDO_SECRET_KEY=${KEY}`}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,comments,agents';

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:(6[0-9]|7[0-9])|8[0-9]|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v60 (2.1.1: v61, 2.1.2: v62, 2.2.0: v63, 2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
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
    check(mx && rows.length === 16 &&  /* 2.18.0: + errreport */  /Event.*News.*Push/.test(mx.querySelector('.nmh').textContent), `${lab}: matrix with every event (${rows.length}: ${rows.map(r => r.querySelector('[data-nm]')?.dataset.nm || '-').join(',')})`);
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
      // 2.9.0: on a slow CI runner the second save could still be settling in the undo history when Undo was clicked
      // (Undo then took back the first change): wait until the saved note names the second change
      // 2.12.2: wait for the note to hold the newest undo entry, then click at once (the note drops its Undo after 6 s; the
      // old wait for "News" in the note never matched, it says "Saved · Undo", so the click came after ~6 s on slow runners)
      const top = () => w.eval(`(() => { const el = [...document.querySelectorAll('.smodal .ssaved')].pop(); return !!(el && el._e && HIST.undo[HIST.undo.length - 1] === el._e); })()`);
      // 2.14.0: the real cause of the CI flake is fixed in the app (a state answer that the save overtook put the old
      // setting back locally, so Undo saw "changed elsewhere"); the note holds the entry once the save is through
      for (let i = 0; i < 50 && !top(); i++) await sleep(100);
      check(top(), 'the note holds the newest undo step');
      click(w, d.querySelector('.smodal .ssaved [data-m="s-undo"]')); await sleep(900);
      for (let i = 0; i < 40 && (await call('GET', '/api/state', null, CKB)).notify.complete.news !== false; i++) await sleep(300);  // 2.7.2: slow CI runner
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
  let items = w.eval(`listMenuItems(${TEAM}, document.querySelector('#top h1')).flatMap(x => x.more || [x]).filter(x => x !== '-').map(x => x.label)`);
  check(items.includes('Notifications: Default'), 'list menu: Notifications: Default ' + items);
  w.eval(`bellMenu(document.querySelector('#top h1'), ${TEAM})`); await sleep(200);
  const bells = [...d.querySelectorAll('#pop .menu-list button')];
  check(bells.map(b => b.textContent.trim()).join('|') === 'All activity|Default|Mute|Custom selection…' && bells[1].classList.contains('on'), 'bell menu: All / Default (on) / Mute (2.6.1: + Custom selection…)');
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

  // ================= #335 waiting on external
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    if (mobile) await call('DELETE', `/api/tasks/${T1}/waiting`, null, CKB);
    w = await boot({user: 'bob', mobile, hash: 'l/' + TEAM}); d = w.document;
    w.eval(`taskMenu(document.querySelector('#top h1'), ${T1})`); await sleep(200);
    const it = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Waiting on someone…');
    check(it, `${lab}: task menu entry`);
    click(w, it); await sleep(300);
    const md = d.querySelector('.modal.waitmodal');
    check(md && md.querySelector('#w-note') && md.querySelector('#w-until'), `${lab}: dialog with note + follow-up day`);
    md.querySelector('#w-note').value = 'carpenter Meier';
    click(w, md.querySelector('[data-m="ok"]')); await sleep(800);
    const t = (await call('GET', '/api/state', null, CKB)).tasks.find(x => x.id === T1);
    check(t.waiting_at && t.wait_note === 'carpenter Meier' && t.wait_until, `${lab}: saved (default follow-up in a week): ${t.wait_until}`);
    const chip = d.querySelector(`#view .trow[data-id="${T1}"] .waitm`);
    check(chip && /Waiting on someone: carpenter Meier/.test(chip.title), `${lab}: chip on the row`);
    check(d.querySelector('#side .srow[data-go="waiting"]'), `${lab}: sidebar row "Waiting on someone"`);
    w.close();
  }
  w = await boot({user: 'bob', hash: 'waiting'}); d = w.document;
  check([...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).join() === String(T1) && /Waiting on someone/.test(d.querySelector('#top h1').textContent), 'the smart view');
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
  check(/Wartet auf jemanden/.test(d.querySelector(`#view .trow[data-id="${T1}"] .waitm`)?.title || '') && /Wartet auf jemanden/.test(d.querySelector('#side').textContent), 'German: Wartet auf jemanden (2.25.0)');
  w.close();

  const e = errs.filter(x => !/Could not load|ECONNREFUSED|fetch failed|NetworkError/.test(x));
  check(!e.length, 'no page errors: ' + e.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
