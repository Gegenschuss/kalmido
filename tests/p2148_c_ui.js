// 2.148.0 UI tests, part C (#2472, office: the procedure documentation (GoBD)), own container (start.sh, mode workspaces),
// Firefox. Invented companies and people only. freelancer-matrix: office
// - a person without organisation (personal office, its admin): Bookkeeping has the entry "Procedure documentation"; the
//   view shows five sections as cards, the prefilled texts grey with "from the settings" (the company name of the company
//   data), the gaps marked and counted; typing an own text and "Save new version" makes version 1 (toast, the server has it);
//   a second save = version 2; the version picker opens version 1 read only (no text fields, no save button) with the
//   text of then; Markdown / PDF links carry the version
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2148_c_ui', check, shots: 'P2148C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2148C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CE = await login('erin');
  await call(CE, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CE, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'erin is in no organisation');
  const st = await call(CE, 'PUT', '/api/office/settings', {company_fields: {name: 'Erin Example Media', city: 'Sampletown', zip: '12345', street: 'Example Road 2'}});
  check(st.http === 200, 'company data ' + st.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone first
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'erin');
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('a[href="#office/books/procdoc"]')`, 80), 'Bookkeeping has the entry');
    await ev(`(() => { document.querySelector('a[href="#office/books/procdoc"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.pd-sec').length === 5`, 80), 'five sections as cards');
    check(await ev(`document.querySelector('.pd-field[data-pdk="company"] .pd-auto').textContent.includes('Erin Example Media')`), 'company prefilled from the company data');
    check(await ev(`!!document.querySelector('.pd-field[data-pdk="company"] .pd-src') && !!document.querySelector('.pd-gap')`), 'prefilled marked, gaps marked');
    check(await ev(`document.querySelectorAll('.pd-open').length >= 5 && /\\d+ gaps to fill in/.test(document.querySelector('.pd-gaps')?.textContent || '')`), 'gaps highlighted and counted');
    check(await ev(`!!document.querySelector('[data-pd="save"]') && !!document.querySelector('a[href="/api/office/procdoc.md"]') && !!document.querySelector('a[href="/api/office/procdoc.pdf"]')`), 'save button and exports');
    check(await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1`), 'no horizontal scrolling on the phone');
    await shot('p2148-c-view.png');
    // own text -> version 1
    await ev(`(() => { const t = document.querySelector('textarea[data-pdf="company"]'); t.value = 'Sole trader, video production (v1)'; t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ev(`!document.querySelector('.pd-field[data-pdk="company"]').classList.contains('pd-open')`), 'typing closes the gap mark');
    await ev(`(() => { document.querySelector('[data-pd="save"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/procdoc', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.version === 1)`, 60), 'version 1 saved');
    check(await ready(ev, `/Version 1 saved/.test(document.querySelector('#toast')?.textContent || '')`, 20), 'toast names the version');
    check(await ready(ev, `/Last saved: version 1/.test(document.querySelector('.pd-state')?.textContent || '')`, 40), 'the state line names version 1');
    await ev(`(() => { const t = document.querySelector('textarea[data-pdf="company"]'); t.value = 'Sole trader, video production (v2)'; t.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('[data-pd="save"]').click(); return 1; })()`);
    check(await ready(ev, `/Last saved: version 2/.test(document.querySelector('.pd-state')?.textContent || '')`, 60), 'version 2 saved');
    // version 1 read only
    await ev(`(() => { const s = document.querySelector('#pd-ver'); s.value = '1'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/read only/.test(document.querySelector('.pd-state')?.textContent || '') && !document.querySelector('textarea[data-pdf]') && !document.querySelector('[data-pd="save"]')`, 60), 'version 1 read only');
    check(await ev(`document.querySelector('.pd-field[data-pdk="company"] .pd-owntxt')?.textContent === 'Sole trader, video production (v1)'`), 'the text of version 1');
    check(await ev(`!!document.querySelector('a[href="/api/office/procdoc.pdf?version=1"]')`), 'export of version 1');
    await shot('p2148-c-version1.png');
    await ev(`(() => { const s = document.querySelector('#pd-ver'); s.value = '0'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `document.querySelector('textarea[data-pdf="company"]')?.value === 'Sole trader, video production (v2)'`, 60), 'back to the current state with version 2');
  }, false);

  console.log(`p2148_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
