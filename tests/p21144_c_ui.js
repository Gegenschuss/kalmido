// 2.114.4 UI test, part C (#2278 #2280 #2281, office: documents), own container (start.sh, mode workspaces), Firefox in a
// phone viewport. Invented companies only. freelancer-matrix: office
// - a person without organisation opens a draft: the preview pane has the prominent "Preview (PDF)" button; a click
//   opens the PDF page view (lightbox), closing it returns to the draft
// - the variable buttons insert at the cursor with spaces around them; the address variable gets its own line;
//   the cursor stands behind the inserted variable
// - "Finish" with an empty variable names the empty fields first (Back keeps the draft); without empty fields no
//   extra question comes
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21144_c_ui', check, shots: 'P21144C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21144C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const cl = await call(CF, 'POST', '/api/clients', {name: 'Beispiel Medien GmbH', street: 'Musterweg 5', zip: '20000', city: 'Hamburg', country: 'DE'});
  const mk = (title, body) => call(CF, 'POST', '/api/office/gen-docs', {client_id: cl.id, title, body, kind: 'other'});
  const d1 = await mk('Mit Lücke', 'Vertrag mit {{client.name}} über {{project.title}}.');
  const d2 = await mk('Vollständig', 'Vertrag mit {{client.name}}.');
  check(d1.id && d2.id, 'two drafts');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const click = (ev, sel) => ev(`(() => { document.querySelector('${sel}').click(); return 1; })()`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await nav(B + `#office/gendocs/${d1.id}`);
    check(await ready(ev, `!!document.querySelector('#dt-body') && !!document.querySelector('.dtp-pv .dtp-pvbtn')`, 80), 'the draft has the PDF preview button');
    await shot('p21144-c-draft.png');
    // ---- the PDF page view
    await click(ev, '.dtp-pv [data-dt="pvpdf"]');
    check(await ready(ev, `!!document.querySelector('.lightbox.pview')`, 60), 'the button opens the PDF page view');
    await click(ev, '.pview [data-pv="x"]');
    check(await ready(ev, `!document.querySelector('.lightbox')`), 'closed again');
    // ---- variables at the cursor
    await ev(`(() => { const t = document.querySelector('#dt-body'); t.value = 'AnWort'; t.focus(); t.setSelectionRange(2, 2); document.querySelector('[data-dt="var"][data-k="client.name"]').click(); return 1; })()`);
    check(await ev(`document.querySelector('#dt-body').value === 'An {{client.name}} Wort'`), 'spaces around the variable ' + await ev(`JSON.stringify(document.querySelector('#dt-body').value)`));
    check(await ev(`document.querySelector('#dt-body').selectionStart === 18`), 'the cursor stands behind the variable');
    await ev(`(() => { const t = document.querySelector('#dt-body'); t.value = 'Adresse: Ende'; t.setSelectionRange(9, 9); document.querySelector('[data-dt="var"][data-k="client.address"]').click(); return 1; })()`);
    check(await ev(`document.querySelector('#dt-body').value === 'Adresse: \\n{{client.address}}\\nEnde'`), 'the address on its own line ' + await ev(`JSON.stringify(document.querySelector('#dt-body').value)`));
    // ---- finish with an empty variable
    await ev(`(() => { const t = document.querySelector('#dt-body'); t.value = 'Vertrag mit {{client.name}} über {{project.title}}.'; t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await click(ev, '[data-dt="final"]');
    check(await ready(ev, `/project\\.title/.test(document.querySelector('.modal')?.textContent || '')`, 60), 'finish names the empty field');
    await click(ev, '.modal [data-cd="no"]');
    await sleep(400);
    check(await ev(`!document.querySelector('.modal') && !!document.querySelector('#dt-body')`), 'Back keeps the draft');
    // ---- no empty fields: only the usual question
    await nav(B + `#office/gendocs/${d2.id}`);
    check(await ready(ev, `!!document.querySelector('#dt-body') && /Vollständig/.test(document.querySelector('#dt-title')?.value || '')`, 80), 'the second draft');
    await click(ev, '[data-dt="final"]');
    check(await ready(ev, `/Finish this document/.test(document.querySelector('.modal')?.textContent || '')`, 60), 'no empty fields: the usual question comes first');
    await click(ev, '.modal [data-cd="no"]');
  }, true);
  console.log(`p21144_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
