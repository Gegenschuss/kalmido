// 2.55.0 part C UI test, own container (start.sh). jsdom:
// #1065 settings per block of a view built from blocks: the gear only in Customize and only at blocks that have
//       settings, "Settings…" in the block's "…" menu, the popover / phone sheet built from the registry (lyo_reg),
//       time tracking: one block shows one client only (the others keep everything), the line chart, the number of
//       tasks on the start page, a list that is no longer visible is ignored ("No longer available"), one undo step.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const opts = async key => { const s = (await call('GET', '/api/state')).settings?.[key]; try { return JSON.parse(s || '{}').opts || {}; } catch { return {}; } };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,time,progress,agents,clients'});
  const A = (await call('POST', '/api/lists', {name: 'Alpha site', kind: 'project', time_tracking: true})).id;
  const BL = (await call('POST', '/api/lists', {name: 'Beta shop', kind: 'project', time_tracking: true})).id;
  const C = (await call('POST', '/api/clients', {name: 'Acme Example'})).id;
  check(C, 'a client');
  await call('PATCH', `/api/lists/${A}`, {client_id: C});
  const TA = (await call('POST', '/api/tasks', {title: 'Alpha work', list_id: A})).id;
  const TB = (await call('POST', '/api/tasks', {title: 'Beta work', list_id: BL})).id;
  await call('POST', '/api/time/entries', {task_id: TA, start: new Date(Date.now() - 3 * 36e5).toISOString(), minutes: 30});
  await call('POST', '/api/time/entries', {task_id: TB, start: new Date(Date.now() - 2 * 36e5).toISOString(), minutes: 50});
  const today = new Date().toISOString().slice(0, 10);
  for (let i = 0; i < 7; i++) await call('POST', '/api/tasks', {title: 'Today ' + i, list_id: BL, due: today});

  // ---- time tracking: the gear only in Customize, a block with one client only
  let w = await boot({user: 'alice', hash: 'time'}), d = w.document;
  const tvl = () => d.querySelectorAll('#view .ttable tr.tvl').length;
  await until(() => tvl() === 2);
  check(tvl() === 2, '#1065: the report shows both lists');
  check(!d.querySelector('#view .lyo-gear'), '#1065: no gear outside Customize');
  check(w.eval(`lyo_defs('time', 'lists').map(x => x.name).join()`) === 'client,list', '#1065: the registry: the lists block has client + list');
  w.eval(`lyOpen('time', true)`); await until(() => d.querySelector('#view .lycanvas'));
  const gear = d.querySelector('#view .lycanvas [data-lyk="lists"] .lyo-gear');
  check(gear, '#1065: Customize: the gear at the block');
  click(w, gear); await until(() => d.querySelector('#pop:not(.hidden) .lyo select[data-lyo="client"]'));
  let sel = d.querySelector('#pop .lyo select[data-lyo="client"]');
  check(sel && [...sel.options].some(o => o.value === String(C)), '#1065: the popover offers the visible client');
  check(!d.querySelector('#pop').classList.contains('sheet'), '#1065: a popover on a computer');
  sel.value = String(C); sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await opts('view_time')).lists?.client === C), '#1065: stored in opts.lists.client');
  check(w.eval('HIST.undo.length') >= 1 && /client/i.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), '#1065: one undo step');
  w.eval('closePop()'); w.eval(`lyOpen('time', false)`);
  await until(() => tvl() === 1);
  check(tvl() === 1 && d.querySelector('#view .ttable tr.tvl')?.textContent.includes('Alpha'), '#1065: the lists block shows only the client\'s list');
  check(/Acme Example/.test(d.querySelector('#view .ttable')?.closest('.stcard')?.querySelector('.sthead')?.textContent || ''), '#1065: the block says "Only: Acme Example"');
  check(/1:20|80/.test(d.querySelector('#view .sttiles b')?.textContent || ''), '#1065: the totals keep everything (own settings per block) ' + d.querySelector('#view .sttiles b')?.textContent);
  // undo
  await w.eval(`histStep('undo')`);
  check(await until(() => tvl() === 2), '#1065: undo brings both lists back');
  check(await until(async () => !(await opts('view_time')).lists), '#1065: undo removes the stored setting');
  // the chart kind
  w.eval(`lyo_put('time', 'chart', {kind: 'line'})`);
  w.eval(`S.tv.period = 'week'; S.tv.key = ''; renderView()`);
  check(await until(() => d.querySelector('#view .ch-line') || !d.querySelector('#view .ch-bar')), '#1065: chart kind line draws a line (or no chart for one day)');
  check(w.eval(`[...document.querySelectorAll('#view .ch-bar')].length`) === 0, '#1065: no bars with kind line');
  w.close();

  // ---- the start page: gear only at blocks with settings, the number of tasks, a list no longer visible
  w = await boot({user: 'alice', hash: 'home'}), d = w.document;
  const rows = () => d.querySelectorAll('#view .dc-today .dtl li').length;
  const total = () => +(d.querySelector('#view .dc-today .dcn')?.textContent || 0);  // the welcome tasks are due today too
  await until(() => total() > 8 && rows() === 8);
  check(total() > 8 && rows() === 8, '#1065: Today on the start page shows 8 by default ' + rows() + '/' + total());
  // "Settings…" in the "…" menu
  const more = d.querySelector('#view .lyb[data-lyk="today"] [data-act="wg-more"]');
  click(w, more); await until(() => d.querySelector('#pop:not(.hidden) [role="menuitem"]'));
  const it = [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Settings/.test(b.textContent));
  check(it, '#1065: "Settings…" in the block\'s menu');
  click(w, it); await until(() => d.querySelector('#pop:not(.hidden) .lyo'));
  const five = [...d.querySelectorAll('#pop .lyo button[data-lyo="n"]')].find(b => b.textContent.trim() === '5');
  check(five, '#1065: the number as buttons');
  click(w, five);
  await until(() => rows() === 5);
  check(rows() === 5, '#1065: the number 5 limits the block');
  check(d.querySelector('#pop .lyo button[data-lyo="n"].on')?.textContent.trim() === '5', '#1065: the popover shows the new value');
  // only one list
  sel = d.querySelector('#pop .lyo select[data-lyo="list"]');
  check(sel && [...sel.options].some(o => o.value === 'f:' || o.value === String(BL)), '#1065: the lists to pick');
  sel.value = String(BL); sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => rows() === 5 && [...d.querySelectorAll('#view .dc-today .dtl li')].every(li => /Today \d/.test(li.textContent))), '#1065: only the tasks of the chosen list');
  w.eval('closePop()');
  w.eval(`lyOpen('home', true)`); await until(() => d.querySelector('#view .lycanvas'));
  check(d.querySelector('#view .lycanvas [data-lyk="today"] .lyo-gear') && !d.querySelector('#view .lycanvas [data-lyk="stats"] .lyo-gear'), '#1065: the gear only at blocks with settings (Today yes, Figures no)');
  w.eval(`lyOpen('home', false)`);
  // a list that is gone: ignored, the sheet says so
  const own = JSON.parse((await call('GET', '/api/state')).settings.dashboard || '{}');
  own.opts = {...(own.opts || {}), today: {n: 20, list: 987654}};
  await call('PATCH', '/api/settings', {dashboard: JSON.stringify(own)});
  w.close();
  w = await boot({user: 'alice', hash: 'home', mobile: true}), d = w.document;
  await until(() => total() > 8 && rows() === total());
  check(total() > 8 && rows() === total(), '#1065: a list that is not visible is ignored (all shown, number 20)');
  w.eval(`lyo_open('home', 'today', document.querySelector('#view .lyb[data-lyk="today"]'))`);
  await until(() => d.querySelector('#pop:not(.hidden) .lyo'));
  check(d.querySelector('#pop').classList.contains('sheet') && d.querySelector('#pop .tch-sh'), '#1065: a sheet on the phone');
  check(d.querySelector('#pop .lyo select[data-lyo="list"] option[value="__gone"]') && d.querySelector('#pop .lyo-gone'), '#1065: the sheet says "No longer available"');
  check(![...d.querySelectorAll('#pop .lyo select[data-lyo="list"] option')].some(o => o.value === '987654'), '#1065: no foreign id as an option');
  // back to the default
  click(w, d.querySelector('#pop .lyo [data-lyo-reset]'));
  check(await until(async () => !(await opts('dashboard')).today), '#1065: "Back to the default" clears the block\'s settings');
  w.close();

  console.log(`p255_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
