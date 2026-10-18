// 2.95.0 B UI tests (#1932: a per diem spreadsheet into the travel expenses), own container (start.sh, mode workspaces),
// Firefox (desktop + phone width). The spreadsheet: tests/p295_b_xlsx.py (invented people, places and figures).
// - the empty trip list offers "Take over from Excel"; the file -> the preview: a section per sheet with the person
//   (a person of the office or "As a free name"), the rows with status, amount and the spreadsheet's amount, the sum
// - unticking counts down; on a phone the rows stay inside the screen with large tap targets
// - "Take over N trips" (after naming the target) -> the list shows the trips of that year -> the toast's undo removes them
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p295_b_ui', check, shots: 'P295B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P295B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const XLSX = execFileSync('python3', ['-I', path.join(__dirname, 'p295_b_xlsx.py')]).toString().trim();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Admin', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel}')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const go = `document.querySelector('.rki-dlg [data-rki="go"]')?.textContent || ''`;
  const trips = `fetch('/api/office/trips?year=2025', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.trips.length)`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/travel');
    check(await ready(ev, `!!document.querySelector('.office [data-rki="pick"]')`, 80), 'the empty trip list offers the import');
    check(await ev(`/Take over from Excel/.test(document.querySelector('[data-rki="pick"]').textContent)`), 'the button text');
    // ---- the preview (the file handed to the same function the file picker calls)
    await ev(`(() => { const b = Uint8Array.from(atob('${XLSX}'), c => c.charCodeAt(0)); rk_impPreview(new File([b], 'reisen.xlsx')); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rki-dlg .rki-sheet').length === 2 && document.querySelectorAll('.rki-dlg .fcirow').length === 6`), 'the preview: two sheets, six rows');
    check(await ev(`(() => { const s = document.querySelectorAll('.rki-dlg select[data-rki="person"]'); return s[0].value === 'u${me.id}' && s[1].value === 'n' && /As a free name: Tom Beispiel/.test(s[1].selectedOptions[0].textContent); })()`),
      'the person of a sheet: the office person, else a free name');
    check(await ev(`/Take over 5 trips/.test(${go})`), 'five rows ticked (the error row has no tick) ' + await ev(go));
    check(await ev(`(() => { const t = document.querySelector('.rki-dlg').textContent; return /Sum: Excel \\D*173\\.00/.test(t) && /calculated \\D*173\\.00/.test(t) && /Start and end time missing/.test(t) && /Date missing or not readable/.test(t) && /Excel: \\D*131\\.00/.test(t); })()`),
      'the sums, the hints and the spreadsheet amount');
    await ev(`(() => { const c = document.querySelector('.rki-dlg [data-rki="sel"][data-s="0"][data-i="2"]'); c.checked = false; c.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/Take over 4 trips/.test(${go})`), 'unticking counts down');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide('.rki-dlg .fcirow *, .rki-dlg .rki-head *')), 'on a phone the preview stays inside the screen');
    check(await ev(`[...document.querySelectorAll('.rki-dlg .fcick')].every(x => x.getBoundingClientRect().height >= 43 && x.getBoundingClientRect().width >= 43)`), 'large tap targets for the ticks');
    await shot('p295-b-import-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ---- take over -> the list -> undo
    await ev(`(() => { document.querySelector('.rki-dlg [data-rki="go"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.itc-dlg [data-cd="yes"]')`), 'the import names its target first');
    await ev(`(() => { document.querySelector('.itc-dlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.rki-dlg') && document.querySelectorAll('.rklist .ofcrow').length === 4 && document.getElementById('rk-year')?.value === '2025'`, 60),
      'taken over: the list shows the year of the trips with four trips');
    check(await ev(trips) === 4 && await ev(`/Beispielort/.test(document.querySelector('.rklist').textContent) && !/Beispielstadt/.test(document.querySelector('.rklist').textContent)`), 'the unticked row is not taken over');
    await shot('p295-b-imported.png');
    check(await ready(ev, `/4 trips imported/.test(document.querySelector('#toast')?.textContent || '')`), 'a toast with undo');
    await ev(`(() => { const b = [...document.querySelectorAll('#toast button')].find(x => /undo/i.test(x.textContent)); b?.click(); return !!b; })()`);
    check(await ready(ev, `${trips}.then(n => n === 0)`, 40), 'the undo removes the imported trips');
    check(await ready(ev, `!document.querySelector('.rklist') && !!document.querySelector('.office [data-rki="pick"]')`), 'the list is empty again');
  }, false);

  console.log(`p295_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
