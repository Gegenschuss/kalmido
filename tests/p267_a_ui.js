// 2.67.0 UI tests, part A (#1838: fixed costs from a spreadsheet in the cash flow), own container (start.sh, mode workspaces),
// Firefox (desktop + phone width). Invented names and figures only.
// - the switch Net | Gross (gross by default, the choice kept on the device) changes the sums of the months
// - the fixed costs grouped by category (without one last), each row net and gross; the dialog has category + VAT rate
// - the import: the template (downloaded from the app) as the file -> the preview dialog with ticks and a VAT choice per row,
//   "Take over N rows" -> the rows in the list; on a phone the rows stay inside the screen with large tap targets
// - the monthly check task: the tick switches it on for the admin
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p267_a_ui', check, shots: 'P267A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const ym = TC.today().slice(0, 7);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const f1 = await call(CA, 'POST', '/api/office/fixed-costs', {label: 'Server', amount: 100, start: ym + '-01', repeat: 'monthly', category: 'IT', vat_rate: 19});
  const f2 = await call(CA, 'POST', '/api/office/fixed-costs', {label: 'Miete', amount: 900, start: ym + '-01', repeat: 'monthly'});
  check(f1.http === 201 && f1.gross === '119.00' && f2.http === 201 && f2.vat_rate === 0, 'two fixed costs ' + f1.http + ' ' + f2.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel}')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const cur = `document.querySelector('.rkcfm.cur')?.textContent || ''`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/cashflow');
    check(await ready(ev, `!!document.querySelector('.rkcfm.cur')`, 80), 'the cash flow');
    // ---- net | gross
    check(await ev(`document.querySelector('[data-rkf="basis"][data-v="gross"]')?.getAttribute('aria-pressed') === 'true'`), 'gross by default');
    check(await ev(`/1,019\\.00/.test(${cur})`), 'gross: 119 + 900 out this month ' + await ev(cur));
    await ev(`(() => { document.querySelector('[data-rkf="basis"][data-v="net"]').click(); return 1; })()`);
    check(await ready(ev, `/1,000\\.00/.test(${cur}) && localStorage.getItem('tasks.cfBasis') === '"net"'`), 'net: 100 + 900, the choice kept on the device');
    await ev(`(() => { document.querySelector('[data-rkf="basis"][data-v="gross"]').click(); return 1; })()`);
    check(await ready(ev, `/1,019\\.00/.test(${cur})`), 'back to gross');
    // ---- the list: grouped, net + gross
    check(await ev(`(() => { const h = [...document.querySelectorAll('.fcicat')].map(x => x.textContent); return h.length === 2 && h[0] === 'IT' && h[1] === 'Without category'; })()`),
      'grouped by category, without one last ' + await ev(`[...document.querySelectorAll('.fcicat')].map(x => x.textContent).join('|')`));
    check(await ev(`(() => { const b = document.querySelector('[data-rkf="fixed"][data-id="${f1.id}"]'); return !!b && /100\\.00/.test(b.textContent) && /119\\.00/.test(b.textContent) && /VAT 19 %/.test(b.textContent); })()`), 'a row shows net, gross and the rate');
    await ev(`(() => { document.querySelector('[data-rkf="fixed"][data-id="${f1.id}"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('.modal #cf-category')?.value === 'IT' && document.querySelector('.modal #cf-vat')?.value === '19' && !!document.querySelector('.modal datalist#cf-cats option[value="IT"]')`),
      'the dialog: category with suggestions, VAT rate');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#cf-vat').value = '7'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && /107\\.00/.test(document.querySelector('[data-rkf="fixed"][data-id="${f1.id}"]')?.textContent || '')`), 'the rate saved (7 %: 107.00 gross)');
    // ---- the import: the template as the file
    // 2.122.3 (#2335): template + import moved to Settings > Import legacy data; the cash flow only links there
    check(await ev(`!document.querySelector('.fcibar [data-rkf="fimp"]') && !document.querySelector('.fcibar a[href$="/import/template"]') && !!document.querySelector('.oimlink a[href="#office/import/fixed"]')`), 'import link to the import page');
    await ev(`(async () => { const b = await (await fetch('/api/office/fixed-costs/import/template', {credentials: 'same-origin'})).blob(); fci_preview(new File([b], 'template.xlsx')); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.fcidlg .fcirow').length === 2`), 'the preview dialog with the two example rows');
    check(await ev(`/Take over 2 rows/.test(document.querySelector('.fcidlg [data-fci="go"]').textContent) && document.querySelector('.fcidlg [data-fci="vat"][data-i="1"]').value === '0'`),
      'both ticked, the insurance with 0 %');
    await shot('p267-a-import.png');
    await ev(`(() => { const s = document.querySelector('.fcidlg [data-fci="vat"][data-i="0"]'); s.value = '7'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await ev(`(() => { const c = document.querySelector('.fcidlg [data-fci="sel"][data-i="1"]'); c.checked = false; c.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/Take over 1 row/.test(document.querySelector('.fcidlg [data-fci="go"]')?.textContent || '')`), 'unticking counts down');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide('.fcidlg .fcirow *')), 'on a phone the preview rows stay inside the screen');
    check(await ev(`[...document.querySelectorAll('.fcidlg .fcick')].every(x => x.getBoundingClientRect().height >= 43 && x.getBoundingClientRect().width >= 43)`), 'large tap targets for the ticks');
    // 2.122.2 (#2323): on a phone amount + VAT rate sit on a second line below the name, inside the row
    check(await ev(`[...document.querySelectorAll('.fcidlg .fcirow:not(.err)')].every(r => { const n = r.querySelector('.ofcn').getBoundingClientRect(), a = r.querySelector('.fciamt').getBoundingClientRect(), o = r.getBoundingClientRect(); return a.top >= n.bottom - 1 && a.bottom <= o.bottom + 1 && a.right <= o.right + 1; })`),
      'on a phone amount and VAT below the name, inside the row');
    await shot('p267-a-import-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { document.querySelector('.fcidlg [data-fci="go"]').click(); return 1; })()`);
    // 2.87.9 (#1940): the import first names the office it goes into
    check(await ready(ev, `!!document.querySelector('.itc-dlg [data-cd="yes"]')`), 'the import names its target first');
    await ev(`(() => { document.querySelector('.itc-dlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.fcidlg') && [...document.querySelectorAll('[data-rkf="fixed"]')].some(b => /Software subscription/.test(b.textContent) && /VAT 7 %/.test(b.textContent))`),
      'taken over with the changed rate');
    check(await ev(`fetch('/api/office/fixed-costs', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.items.length === 3 && !j.items.some(i => /Liability/.test(i.label)))`), 'the unticked row is not taken over');
    // ---- the monthly check
    check(await ready(ev, `!!document.querySelector('[data-fcc="on"]') && !document.querySelector('[data-fcc="on"]').checked`), 'the monthly check, off');
    await ev(`(() => { const c = document.querySelector('[data-fcc="on"]'); c.checked = true; c.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/cashflow/check', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.on && j.user_id === ${me.id} && !!j.task_id)`), 'switched on for the admin');
    await shot('p267-a-cashflow.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide('.office .ofcbody *')), 'on a phone the cash flow stays inside the screen');
    await shot('p267-a-cashflow-phone.png');
    // 2.122.2 (#2327): a reload after saving keeps the old content (no "Loading…" page) and the scroll position
    await ev(`(() => { const v = document.getElementById('view'); v.scrollTop = v.scrollHeight; window.__st = v.scrollTop; rk_cfReload(); return 1; })()`);
    check(await ev(`!!document.querySelector('.office .rkcfms') && ![...document.querySelectorAll('.office p.lempty')].some(p => p.textContent === tr('Loading…'))`), 'the reload keeps the old content until the new data is there');
    check(await ready(ev, `!!RKF.data && document.getElementById('view').scrollTop === window.__st`), 'the scroll position stays after the reload ' + await ev(`document.getElementById('view').scrollTop + '/' + window.__st`));
  }, false);

  console.log(`p267_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
