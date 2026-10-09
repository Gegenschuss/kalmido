// 2.36.1 UI tests (agent B): Office & finance (#1021) -- the module skeleton + master data; own container (start.sh).
// jsdom: the module is off by default (no sidebar entry, no view); Settings > Modules has the group "Office & finance"; on =
//      sidebar entry + the view with its six tabs; a member sees the lists without "New"; the admin opens "New service",
//      types a comma decimal and saves -> the row appears grouped under its category; the search filters; the settings
//      tab shows the number preview and the DE tax rates; the purpose "Office & finance" exists in the purpose cards
// Firefox 390 x 844 touch: the Services tab with rows >= 44 px tall, the service dialog, the settings tab (screenshots)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2361_b_ui', check, shots: 'P2361B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT + ',office'}, BCK);
  check(!!BOB, 'setup: bob');

  // ================= jsdom: off by default
  let w = await boot({hash: 'office'}); let d = w.document;
  await sleep(800);
  check(!d.querySelector('#side [data-go="office"]') && !d.querySelector('.office'), 'off: no sidebar entry, no view');
  check(w.eval('officeOn()') === false, 'off: officeOn() false');
  // Settings > Modules: the group with the switch
  w.eval(`settingsModal('modules')`); await until(() => d.querySelector('.smodal'));
  const grp = [...d.querySelectorAll('.smodal .modgrp')].find(g => /Office & finance/.test(g.querySelector('.mgn')?.textContent || ''));
  const sw = grp && grp.querySelector('[data-feat="office"]');
  check(!!grp && !!sw, 'Settings > Modules: group "Office & finance" with the switch');
  check(w.eval(`PURPOSES.some(p => p[0] === 'office' && /Office & finance/.test(p[2])) && PURPOSE_EXTRA.office.includes('office')`), 'the purpose "Office & finance" exists and switches the module on');
  if (sw) { sw.click(); await until(() => w.eval(`feat('office')`)); }
  check(w.eval(`feat('office')`), 'the switch turns the module on');
  d.querySelector('.smodal')?.remove(); w.eval('render()'); await sleep(400);
  check(!!d.querySelector('#side [data-go="office"]'), 'on: sidebar entry');

  // ================= the view (admin)
  w.eval(`go('office/services')`); await until(() => d.querySelector('.office[data-ofctab="services"] .ofcbar'), 60);
  check(d.querySelectorAll('.office .ofctabs [role=tab]').length === 6, 'the view has six tabs');
  check(d.querySelector('.office .ofctabs [role=tab][aria-selected="true"]')?.dataset.go === 'office/services', 'tab Services selected');
  check(!!d.querySelector('.office [data-ofc="new"][data-kind="services"]'), 'admin: "New service"');
  check(/Nothing here yet/.test(d.querySelector('.office .ofcbody')?.textContent || ''), 'empty hint');
  d.querySelector('.office [data-ofc="new"][data-kind="services"]').click(); await until(() => d.querySelector('.ofcdlg'));
  let md = d.querySelector('.ofcdlg');
  check(!!md && /New service/.test(md.querySelector('h3')?.textContent || ''), 'dialog "New service"');
  check(md.querySelector('#of-daily_rate')?.getAttribute('inputmode') === 'decimal' && !md.querySelector('input[type=date]'), 'money inputs: inputmode decimal, no native date');
  md.querySelector('#of-name_de').value = 'Kamera'; md.querySelector('#of-name_en').value = 'Camera'; md.querySelector('#of-category').value = 'Video';
  md.querySelector('#of-daily_rate').value = '980,50'; md.querySelector('#of-raw_fee').checked = true; md.querySelector('#of-producing').checked = true;
  md.querySelector('[data-m="save"]').click();
  await until(() => !d.querySelector('.ofcdlg') && d.querySelector('.office .ofcrow'), 60);
  const row = d.querySelector('.office .ofcrow');
  check(!!row && /Kamera/.test(row.textContent) && /980[.,]50?/.test(row.textContent) && /raw data/.test(row.textContent) && /producing/.test(row.textContent), 'the row shows name, rate and flags ' + (row?.textContent || '').slice(0, 120));
  check(/Video/.test(d.querySelector('.office .ofcgrp')?.textContent || ''), 'grouped under its category');
  const srv = await call('GET', '/api/office/services');
  check(srv.items?.length === 1 && srv.items[0].daily_rate === 980.5 && srv.items[0].raw_fee === 1, 'stored with the comma decimal ' + JSON.stringify(srv.items?.[0] || {}).slice(0, 160));
  await call('POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', category: 'Video', unit: 'hour', hourly_rate: 120});
  w.eval(`ofcReload('services')`); await until(() => d.querySelectorAll('.office .ofcrow').length === 2, 60);
  const q = d.querySelector('#ofc-q'); q.value = 'edit'; q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(300);
  check(d.querySelectorAll('.office .ofcrow').length === 1 && /Schnitt/.test(d.querySelector('.office .ofcrow').textContent), 'search filters by the English name too');
  const q2 = d.querySelector('#ofc-q'); q2.value = ''; q2.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(300);  // the list was drawn again: a new input
  // open a row = edit dialog
  await until(() => d.querySelectorAll('.office .ofcrow').length === 2);
  const kr = [...d.querySelectorAll('.office .ofcrow')].find(x => /Kamera/.test(x.textContent));
  kr?.click(); await until(() => d.querySelector('.ofcdlg'));
  md = d.querySelector('.ofcdlg');
  if (!md) {  // diagnostics: what the row is and what opening it directly says
    let why = ''; try { w.eval(`ofcModal('services', ofcRow('services', ${+kr?.dataset.id}))`); } catch (x) { why = String(x && x.stack || x).split('\n').slice(0, 3).join(' | '); }
    console.log('row:', kr ? kr.outerHTML.slice(0, 200) : 'none', 'rows:', d.querySelectorAll('.office .ofcrow').length, 'direct:', why || 'ok', !!d.querySelector('.ofcdlg'));
    md = d.querySelector('.ofcdlg');
  }
  check(/Edit service/.test(md?.querySelector('h3')?.textContent || '') && md.querySelector('#of-name_de').value === 'Kamera', 'tapping a row opens the edit dialog ' + (md?.querySelector('h3')?.textContent || 'no dialog') + ' ' + (md?.querySelector('#of-name_de')?.value || ''));
  check(!!md.querySelector('[data-m="del"]') && !!md.querySelector('#of-archived'), 'admin: delete + archive in the dialog');
  md.querySelector('[data-m="close"]').click(); await sleep(200);
  // settings tab
  w.eval(`go('office/settings')`); await until(() => d.querySelector('.office .ofcset'), 60);
  check(/next: KVA-\d{4}-001/.test(d.querySelector('#os-preview')?.textContent || ''), 'settings: the number preview ' + d.querySelector('#os-preview')?.textContent);
  check(/19/.test(d.querySelector('.office .ofcset')?.textContent || '') && /7/.test(d.querySelector('.office .ofcset')?.textContent || '') && d.querySelector('#os-pack')?.value === 'DE', 'settings: pack DE with its tax rates');
  check(!!d.querySelector('.office [data-ofc="save-settings"]') && !!d.querySelector('.office [data-ofc="import"]') && !!d.querySelector('.office a[href="/api/office/export"]'), 'settings: save, import, export');
  d.querySelector('#os-name').value = 'Studio Nordlicht GmbH'; d.querySelector('#os-lines').value = 'Hafenstraße 12\n20457 Hamburg';
  d.querySelector('#ofc-set').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(async () => (await call('GET', '/api/office/settings')).settings?.company?.name === 'Studio Nordlicht GmbH', 40);
  check((await call('GET', '/api/office/settings')).settings.company.lines.length === 2, 'settings: saved company + address lines');
  // texts tab: the seeded catalogue
  w.eval(`go('office/texts')`); await until(() => d.querySelector('.office[data-ofctab="texts"] .ofcrow'), 60);
  await until(() => d.querySelectorAll('.office .ofcrow').length > 8, 40);
  check([...d.querySelectorAll('.office .ofcgrp')].some(h => /Rights: territory/.test(h.textContent)) && [...d.querySelectorAll('.office .ofcrow')].some(r => /weltweit außer Musik/.test(r.textContent)), 'text blocks: the seeded rights catalogue, grouped by kind ' + [...d.querySelectorAll('.office .ofcgrp')].map(h => h.textContent).join('|') + ' rows ' + d.querySelectorAll('.office .ofcrow').length + ' ' + (d.querySelector('.office .ofcrow')?.textContent || '').slice(0, 80));
  w.close();

  // ================= a member: reads, no "New"
  w = await boot({user: 'bob', hash: 'office/services'}); d = w.document;
  await until(() => d.querySelector('.office .ofcrow'), 60);
  check(d.querySelectorAll('.office .ofcrow').length === 2 && !d.querySelector('.office [data-ofc="new"]'), 'member: sees the services, no "New"');
  d.querySelector('.office .ofcrow').click(); await until(() => d.querySelector('.ofcdlg'));
  md = d.querySelector('.ofcdlg');
  check(md && md.querySelector('#of-name_de').disabled && !md.querySelector('[data-m="save"]') && !md.querySelector('[data-m="del"]'), 'member: the dialog is read-only');
  md.querySelector('[data-m="close"]').click();
  w.eval(`go('office/settings')`); await until(() => d.querySelector('.office .ofcset'), 60);
  check(!d.querySelector('.office [data-ofc="save-settings"]') && d.querySelector('#os-name')?.disabled, 'member: settings read-only');
  w.close();

  // ================= Firefox 390 x 844 touch
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('.office .ofcbody')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#office/services'); await ready(ev); await sleep(1200);
    const g = await ev(`(() => { const r = document.querySelector('.office .ofcrow'); if (!r) return null; const b = r.getBoundingClientRect(); const t = document.querySelector('.office .ofctabs [role=tab]').getBoundingClientRect(); return {h: Math.round(b.height), w: Math.round(b.width), th: Math.round(t.height), over: document.documentElement.scrollWidth > window.innerWidth + 1}; })()`);
    check(g && g.h >= 44 && g.w >= 300 && g.th >= 24 && !g.over, '390: rows >= 44 px, tabs >= 24 px, no horizontal overflow ' + JSON.stringify(g));
    await shot('p2361b-390-services.png');
    await ev(`(() => { document.querySelector('.office [data-ofc="new"][data-kind="services"]').click(); return 1; })()`); await sleep(800);
    const dg = await ev(`(() => { const m = document.querySelector('.ofcdlg .card'); if (!m) return null; const b = m.getBoundingClientRect(); const s = m.querySelector('[data-m="save"]').getBoundingClientRect(); return {w: Math.round(b.width), sh: Math.round(s.height), fits: b.right <= window.innerWidth + 1}; })()`);
    check(dg && dg.fits && dg.sh >= 24, '390: the dialog fits, save button >= 24 px ' + JSON.stringify(dg));
    await shot('p2361b-390-service-dialog.png');
    await ev(`(() => { document.querySelector('.ofcdlg [data-m="close"]').click(); return 1; })()`); await sleep(400);
    await o.nav(B + '#office/settings'); await ready(ev); await sleep(1000);
    const st = await ev(`(() => { const f = document.querySelector('.office .ofcset'); return f ? {over: document.documentElement.scrollWidth > window.innerWidth + 1, pv: document.querySelector('#os-preview')?.textContent || ''} : null; })()`);
    check(st && !st.over && /KVA-/.test(st.pv), '390: settings fit, preview shows ' + JSON.stringify(st));
    await shot('p2361b-390-settings.png');
  }, true);

  console.log(`p2361_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
