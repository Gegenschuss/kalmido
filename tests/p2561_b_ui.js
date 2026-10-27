// 2.56.1 UI tests, part B (#1799: fewer symbols in the task row and the sidebar; own container, start.sh). jsdom:
// - a new account without the setting = level "Important": due date, reminder, person show; note, tags, list do not
// - "All" = every symbol as before; "Calm" = only the title, the status circle and the due date
// - "Custom" with one box (Settings > Appearance > Task rows), the boxes start from what the row showed
// - overdue (red) and "an agent waits for your yes" stay in "Calm"; the task view still shows the hidden note / tags
// - the sidebar: task counts, status dots, share marks each off; no empty share columns are kept
// - the level comes back from the server after a reload; the server refuses unknown levels / symbol keys
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._st = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const day = n => TC.day(n);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice', undefined, {rowIcons: null});  // the real default, not the legacy "all"
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  check(st0.settings.row_icons === 'key' && st0.settings.side_count === '1' && st0.settings.side_dots === '1' && st0.settings.side_share === '1',
    'defaults: row_icons key, the sidebar switches on ' + JSON.stringify([st0.settings.row_icons, st0.settings.side_count, st0.settings.side_dots, st0.settings.side_share]));
  // the server: levels and symbol keys
  check((await call('PATCH', '/api/settings', {row_icons: 'loud'}))._st === 400, 'an unknown level is refused');
  check((await call('PATCH', '/api/settings', {row_icons_custom: 'due,nope'}))._st === 400, 'an unknown symbol key is refused');
  check((await call('PATCH', '/api/settings', {side_share: 'maybe'}))._st === 400, 'side_share takes 0 / 1 only');
  check((await call('PATCH', '/api/settings', {row_icons_custom: 'tags,due'}))._st === 200 && (await call('GET', '/api/state')).settings.row_icons_custom === 'due,tags', 'custom keys are stored in the table order');
  await call('PATCH', '/api/settings', {row_icons_custom: ''});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...new Set([...feats, 'progress', 'collab'])].join(',')});
  const L = (await call('POST', '/api/lists', {name: 'Household', kind: 'project'})).id;
  await call('POST', `/api/lists/${L}/status`, {status: 'on_track'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Alpha', list_id: L, due: day(3), reminders: '60', content: 'a quiet note', tags: ['garden'], assignee_id: BOB})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Beta', list_id: L, due: day(-2), content: 'late note'})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Gamma', list_id: L, due: day(1)})).id;
  await call('POST', '/api/tasks', {title: 'Gamma one', list_id: L, parent_id: T3});

  let w = await boot({user: 'alice', hash: 'week', rowIcons: null}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  const meta = id => row(id)?.querySelector('.meta');
  const has = (id, html) => !!meta(id)?.innerHTML.includes(html);
  const norm = h => { const x = d.createElement('div'); x.innerHTML = h; return x.innerHTML; };  // the icon as the page serialises it
  const BELL = norm(w.eval(`ic('bell', 's')`)), NOTE = norm(w.eval(`ic('edit', 's')`));
  const look = id => ({due: !!meta(id)?.querySelector('.dt'), bell: has(id, BELL), note: has(id, NOTE), tag: !!meta(id)?.querySelector('.tag'),
    list: !!row(id)?.querySelector('.lst, .c-list'), who: !!row(id)?.querySelector('.meta .who, .c-who .who, .meta .av, .c-who .av'), sub: !!meta(id)?.querySelector('.subc')});
  await until(() => row(T1));

  // (a) the default "Important"
  let a = look(T1);
  check(a.due && a.bell && a.who && !a.note && !a.tag && !a.list, '(a) Important: due, reminder, person; no note, tag, list ' + JSON.stringify(a));
  check(!look(T3).sub, '(a) Important: no subtask counter');

  // (h) Settings > Appearance > Task rows shows the level; "Custom" opens the boxes, seeded from "Important"
  w.eval(`settingsModal('look')`);
  let md = await until(() => d.querySelector('.smodal #rsy-set') && d.querySelector('.smodal'));
  check(md?.querySelector('#rsy-set [data-rsy-lv="key"]')?.getAttribute('aria-pressed') === 'true', 'the settings show "Important" as chosen');
  check(!md?.querySelector('#rsy-set [data-rsy]'), 'no boxes before "Custom"');
  click(w, md.querySelector('#rsy-set [data-rsy-lv="custom"]'));
  await until(() => md.querySelector('#rsy-set [data-rsy="note"]'));
  await until(async () => (await call('GET', '/api/state')).settings.row_icons === 'custom');
  const boxes = Object.fromEntries([...md.querySelectorAll('#rsy-set [data-rsy]')].map(b => [b.dataset.rsy, b.checked]));
  check(boxes.due && boxes.remind && boxes.person && !boxes.note && !boxes.tags, '(d) Custom starts from Important ' + JSON.stringify(boxes));
  check(md.querySelectorAll('#rsy-set .rsy-g legend').length === 6, '(d) six groups (dates, content, time, status, placement, people)');
  // (d) one box: the note on
  const nb = md.querySelector('#rsy-set [data-rsy="note"]'); nb.checked = true; nb.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).settings.row_icons_custom?.includes('note'));
  const st1 = (await call('GET', '/api/state')).settings;
  check(st1.row_icons === 'custom' && st1.row_icons_custom.split(',').includes('note') && st1.row_icons_custom.split(',').includes('due'), '(d) saved on the server: custom + note ' + st1.row_icons_custom);
  await until(() => look(T1).note);
  a = look(T1);
  check(a.note && a.due && !a.tag, '(d) the row follows at once: the note shows, the tag not ' + JSON.stringify(a));
  // the preview in the same pane follows the level
  check(d.querySelector('.smodal .lookpv .trow .meta')?.innerHTML.includes(NOTE), 'the preview shows the note in "Custom"');
  md.remove();

  // (b) "All" = as before
  await call('PATCH', '/api/settings', {row_icons: 'all'});
  w.close(); w = await boot({user: 'alice', hash: 'week', rowIcons: null}); d = w.document;
  await until(() => row(T1));
  a = look(T1);
  check(a.due && a.bell && a.who && a.note && a.tag && a.list && look(T3).sub, '(b) All: every symbol ' + JSON.stringify(a));

  // (c) + (e) "Calm": only the title, the status circle and the due date; overdue and "agent waits" stay
  await call('PATCH', '/api/settings', {row_icons: 'calm'});
  w.close(); w = await boot({user: 'alice', hash: 'week', rowIcons: null}); d = w.document;
  await until(() => row(T1));
  check(w.eval('S.settings.row_icons') === 'calm', '(h) the level comes back from the server after a reload');
  a = look(T1);
  check(a.due && !a.bell && !a.who && !a.note && !a.tag && !a.list && !look(T3).sub, '(c) Calm: only the due date ' + JSON.stringify(a));
  check(!!row(T1).querySelector('.chk') && row(T1).querySelector('.ttl')?.textContent.includes('Alpha'), '(c) Calm: status circle + title');
  check(!!meta(T2)?.querySelector('.dt.over'), '(e) Calm: overdue (red) still shows');
  await call('PATCH', '/api/settings', {row_icons: 'custom', row_icons_custom: 'none'});
  w.eval(`Object.assign(S.settings, {row_icons: 'custom', row_icons_custom: 'none'}); S.tasks.get(${T3}).approval = 'pending'; render()`);
  await until(() => meta(T3)?.querySelector('.apchip'));
  check(!!meta(T3)?.querySelector('.apchip'), '(e) Custom with nothing on: "an agent waits for your yes" still shows');
  check(!!meta(T2)?.querySelector('.dt.over') && !meta(T1)?.querySelector('.dt'), '(e) nothing on: overdue stays, a future date goes');

  // (f) the task view shows what the row hides
  w.eval(`openDetail(${T1})`);
  const det = await until(() => d.querySelector('#d-content') && d.querySelector('#detail'));
  check(det && det.innerHTML.includes('a quiet note') && /garden/.test(det.textContent), '(f) the task view still shows the note and the tag');

  // (g) the sidebar: counts, status dots, share marks one by one
  const lrow = () => d.querySelector(`#side .srow[data-list="${L}"]`);
  check(lrow()?.querySelector('.c')?.textContent.trim() !== '' && !!lrow()?.querySelector('.stdot') && !!lrow()?.querySelector('.shk'), '(g) default: count, status dot, share mark');
  w.eval(`Object.assign(S.settings, {side_count: '0'}); render()`);
  await until(() => lrow()?.querySelector('.c')?.textContent.trim() === '');
  check(lrow()?.querySelector('.c')?.textContent.trim() === '' && !!lrow()?.querySelector('.stdot'), '(g) counts off: no number, the dot stays');
  const today = d.querySelector('#side .srow[data-go="#today"], #side .srow[data-drop="today"]');
  check(!today || today.querySelector('.c')?.textContent.trim() === '' || today.querySelector('.c.over'), '(g) counts off: Today keeps only a red number');
  w.eval(`Object.assign(S.settings, {side_count: '1', side_dots: '0'}); render()`);
  await until(() => !lrow()?.querySelector('.stdot'));
  check(!lrow()?.querySelector('.stdot') && lrow()?.querySelector('.c')?.textContent.trim() !== '', '(g) status dots off');
  w.eval(`Object.assign(S.settings, {side_dots: '1', side_share: '0'}); render()`);
  await until(() => !lrow()?.querySelector('.shk'));
  check(!d.querySelector('#side .shk') && !d.querySelector('#side .sbc-sl'), '(g) share marks off: no marks and no empty columns kept');
  // the switches in Settings > Appearance > Sidebar
  w.eval(`settingsModal('look')`);
  md = await until(() => d.querySelector('.smodal #s-sideshr') && d.querySelector('.smodal'));
  check(md && md.querySelector('#s-sidecnt')?.checked && md.querySelector('#s-sidedot')?.checked && !md.querySelector('#s-sideshr')?.checked, '(g) the three sidebar switches show the state');
  const sc = md.querySelector('#s-sidecnt'); sc.checked = false; sc.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state')).settings.side_count === '0'), '(g) the counts switch saves on the server');
  md.remove(); w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
