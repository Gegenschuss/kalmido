// 2.55.0 UI tests, part A (jsdom): saved arrangements per view (#1069), an arrangement as a template (#1068). Invented data only.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const DATA = process.argv[2] || path.join(__dirname, '.data');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
if (!process.env.P255A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const click = (w, el) => el?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const WAIT = +process.env.P255A_WAIT || 2500;  // a slow machine: more time for the client to load
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ca = await login('alice');
  const req = async (ck, m, u, b) => (await fetch(B + u.replace(/^\//, ''), {method: m, headers: {...H, Cookie: ck}, body: b ? JSON.stringify(b) : undefined})).json().catch(() => ({}));
  await req(ca, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const bob = await req(ca, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const cb = await login('bob');
  for (const ck of [ca, cb]) await req(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(bob.id, 'bob created');

  // ---- no saved arrangement: no switch, only "Save as arrangement…" in a block's menu
  let w = await boot({user: 'alice', hash: 'home', wait: WAIT}), d = w.document;
  await sleep(600);
  check(!d.querySelector('#view .lyvsw'), '#1069: no switch while nothing is saved');
  check(w.eval(`lyv_menuItems('home').some(x => x.label === 'Save as arrangement…')`), '#1069: "Save as arrangement…" in a block menu');
  w.close();

  // ---- two saved arrangements: the switch shows "Standard", switching changes the blocks, undo goes back
  const L1 = JSON.stringify({order: ['notes', 'today', 'wait', 'news'], hidden: ['news']});
  const f = await req(ca, 'POST', '/api/layouts/saved', {key: 'dashboard', name: 'Focus', layout: L1});
  await req(ca, 'POST', '/api/layouts/saved', {key: 'dashboard', name: 'Overview', layout: JSON.stringify({order: ['wait', 'today'], hidden: ['notes']})});
  check(f.saved?.id, '#1069: saved through the API');
  w = await boot({user: 'alice', hash: 'home', wait: WAIT}); d = w.document;
  check(await until(() => d.querySelector('#view .lyvsw')), '#1069: the switch appears in the header');
  const sw = d.querySelector('#view .lyvsw');
  check(sw && /Standard/.test(sw.textContent), '#1069: it says Standard: ' + sw?.textContent);
  const before = w.eval(`lyPref('home').order.filter(k => !lyPref('home').hidden.has(k)).join(',')`);
  click(w, sw); await sleep(200);
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(items.some(x => /Focus/.test(x.textContent)) && items.some(x => /Overview/.test(x.textContent)) && items.some(x => /Manage arrangements/.test(x.textContent)),
    '#1069: the menu lists Standard, the saved ones and Manage: ' + items.map(x => x.textContent.trim()).join(' | '));
  click(w, items.find(x => /Focus/.test(x.textContent)));
  check(await until(() => w.eval(`(S.settings.dashboard || '').includes('notes')`)), '#1069: switching sets the view value');
  await sleep(300);
  const after = w.eval(`lyPref('home').order.filter(k => !lyPref('home').hidden.has(k)).join(',')`);
  check(after !== before && !after.split(',').includes('news') && after.indexOf('notes') < after.indexOf('today'), '#1069: the blocks changed: ' + before + ' -> ' + after);
  check(/Focus/.test(d.querySelector('#view .lyvsw')?.textContent || ''), '#1069: the header names the active one');
  check(await until(() => !d.querySelector('#view .lyb[data-lyk="news"]') && !!d.querySelector('#view .lyb[data-lyk="search"]')), '#1069: News is hidden now: ' + [...d.querySelectorAll('#view .lyb')].map(x => x.dataset.lyk).join(','));
  w.eval(`histStep('undo')`);
  check(await until(() => !w.eval(`S.settings.dashboard`)), '#1069: undo goes back to the standard');
  check(await until(() => /Standard/.test(d.querySelector('#view .lyvsw')?.textContent || '')), '#1069: ... and the header says so');
  // save as (a prompt), then manage: rename, delete with undo
  let asked = '';
  w.prompt = t => { asked = t; return 'Evening'; };  // boot.js answers the app's own prompt dialog with this
  w.eval(`lyv_saveAs('home')`);
  check(await until(() => asked === 'Save arrangement as'), '#1069: "Save as" asks for a name');
  check(await until(() => w.eval(`lyv_rows('dashboard').some(r => r.name === 'Evening' && r.active)`)), '#1069: saved and active');
  w.eval(`lyv_manage('home')`); await sleep(200);
  const rows = [...d.querySelectorAll('.lyvm .lyvrow')];
  check(rows.length === 3, '#1069: manage lists three: ' + rows.length);
  click(w, rows.find(r => /Overview/.test(r.textContent))?.querySelector('[data-lyvm="del"]'));
  check(await until(() => d.querySelectorAll('.lyvm .lyvrow').length === 2 && w.eval(`HIST.undo.at(-1)?.label === 'Arrangement deleted' && !HIST.busy`)), '#1069: deleted, one undo step');
  w.eval(`histStep('undo')`);
  check(await until(() => d.querySelectorAll('.lyvm .lyvrow').length === 3 && /Overview/.test(d.querySelector('.lyvm .lyvlist').textContent)), '#1069: undo brings it back: ' + w.eval(`lyv_rows('dashboard').map(r => r.name).join() + ' / ' + HIST.undo.map(e => e.label).join('|')`));
  w.close();

  // ---- the phone: the switch opens a sheet with large targets
  w = await boot({user: 'alice', hash: 'home', mobile: true, wait: WAIT}); d = w.document;
  check(await until(() => d.querySelector('#view .lyvsw')), '#1069: phone: the switch is there');
  click(w, d.querySelector('#view .lyvsw')); await sleep(250);
  check(!!d.querySelector('#pop .tch-sh') && d.querySelectorAll('#pop [role="menuitem"]').length >= 4, '#1069: phone: a sheet with a head');
  w.close();

  // ---- Today: the switch in the view's "…" menu
  w = await boot({user: 'alice', hash: 'today', wait: WAIT}); d = w.document;
  await req(ca, 'POST', '/api/layouts/saved', {key: 'view_today', name: 'Morning', layout: JSON.stringify({order: ['tasks', 'brief']})});
  w.eval(`S.lyv = null; lyv_load()`); await until(() => w.eval(`lyv_rows('view_today').length === 1`));
  check(w.eval(`topMoreItems().some(x => /^Arrangement: Standard/.test(x.label) && x.more?.length >= 2)`), '#1069: Today: "Arrangement" in its menu');
  w.close();

  // ---- #1068 a template: bob gets a News item, sees the preview, takes it over
  const L2 = JSON.stringify({order: ['next', 'done'], hidden: ['journal']});
  const s = await req(ca, 'POST', '/api/layouts/offers', {key: 'view_review', name: 'Weekly', layout: L2, to: [bob.id]});
  check(s.sent === 1, '#1068: sent ' + JSON.stringify(s));
  w = await boot({user: 'bob', hash: 'news', wait: WAIT}); d = w.document;
  check(await until(() => /sent you the arrangement/.test(d.querySelector('#view')?.textContent || '')), '#1068: bob sees the News item');
  const it = w.eval(`(S.nf.items || []).findIndex(x => x.kind === 'lytpl')`);
  w.eval(`newsOpen(${it})`);
  check(await until(() => d.querySelector('.lyvo')), '#1068: the template opens');
  const dlg = d.querySelector('.lyvo');
  check(dlg && /Alice sent you this arrangement/.test(dlg.textContent) && dlg.querySelectorAll('.lyvprev li').length === 4, '#1068: sender and preview of the blocks: ' + dlg?.textContent.replace(/\s+/g, ' ').slice(0, 200));
  check(dlg && /Hidden: Journal/.test(dlg.textContent), '#1068: the preview names hidden blocks');
  click(w, dlg?.querySelector('[data-lyvo="yes"]'));
  check(await until(() => w.eval(`lyv_rows('view_review').some(r => r.name === 'Alice: Weekly' && r.active)`)), '#1068: taken over as bob\'s own, active');
  check(w.eval(`JSON.parse(S.settings.view_review || '{}').order?.[0]`) === 'next', '#1068: bob\'s review shows it');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
