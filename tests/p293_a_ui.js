// 2.93.0 UI tests, part A (#1927, office: document templates and documents), own container (start.sh, mode workspaces),
// Firefox (desktop + phone width). Invented companies, people and figures only.
// - the admin has the tab "Documents": "Use sample" takes over the contract sample as own template; the template dialog
//   inserts a variable at the cursor through its button bar
// - a new document for a client: the draft with its preview (variables filled, an unknown one marked), finish (the
//   document is final, the text frozen), create the signature link (the link is shown)
// - the client page lists the client's documents; on a phone nothing sticks out to the side
// - a member does not get the tab (the hint instead)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p293_a_ui', check, shots: 'P293A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P293A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Kundenweg 5', zip: '20000', city: 'Hamburg', country: 'DE'});
  check(cl.http < 300, 'a client ' + cl.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const api = (m, u, b) => `fetch('${u}', {method: '${m}', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}${b ? `, body: JSON.stringify(${JSON.stringify(b)})` : ''}}).then(r => r.json())`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('#view *')].filter(e => e.getClientRects().length && !e.closest('.seg') && !e.closest('.ofctabs') && !e.closest('.ofrail') && !e.closest('.ofpts')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;  // 2.98.0 (#2180): the office rail / a phone's tab row scroll on their own
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= templates
    await nav(B + '#office/gendocs');
    check(await ready(ev, `!!document.querySelector('[data-dt="new"]')`, 80), 'the tab "Documents" for the admin');
    await ev(`(() => { document.querySelector('[data-dt="view"][data-v="templates"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-dt="starters"]')`), 'the templates view');
    await ev(`(() => { document.querySelector('[data-dt="starters"]').click(); return 1; })()`);
    // 2.117.0 (#2283): three contract samples + seven letters
    check(await ready(ev, `document.querySelectorAll('.modal .dtp-starters li').length === 10`), 'the ten samples');
    check(await ev(`/legal advice|Rechtsberatung/.test(document.querySelector('.modal').textContent)`), 'the note: sample text, no legal advice');
    await ev(`(() => { document.querySelector('.modal [data-m="take"][data-k="contract"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.dtp-list .ofcrow').length === 1`), 'use sample: the contract is an own template');
    await ev(`(() => { document.querySelector('[data-dt="tnew"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #dt-tbody') && document.querySelectorAll('.modal .dtp-vars .btn').length === 10`), 'the template dialog with the variable bar');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#dt-tname').value = 'Kurzvertrag'; const t = m.querySelector('#dt-tbody'); t.value = '# Kurzvertrag\\n\\nFür  und {{unbekannt}}.'; t.focus(); t.setSelectionRange(19, 19); m.querySelector('[data-dt="var"][data-k="client.name"]').click(); return 1; })()`);
    check(await ev(`document.querySelector('.modal #dt-tbody').value === '# Kurzvertrag\\n\\nFür {{client.name}} und {{unbekannt}}.'`), 'a variable inserted at the cursor ' + await ev(`JSON.stringify(document.querySelector('.modal #dt-tbody')?.value)`));
    await shot('p293-a-template.png');
    await ev(`(() => { document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.dtp-list .ofcrow').length === 2`), 'the own template saved');
    // ================= a document
    await ev(`(() => { document.querySelector('[data-dt="view"][data-v="docs"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('[data-dt="new"]')`);
    await ev(`(() => { document.querySelector('[data-dt="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #dt-tpl')`), 'the new document dialog');
    await ev(`(() => { const m = document.querySelector('.modal'); const s = m.querySelector('#dt-tpl'); s.value = [...s.options].find(o => /Kurzvertrag/.test(o.textContent)).value; m.querySelector('#dt-client').value = '${cl.id}'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && !!document.querySelector('#dt-body') && !!document.querySelector('.dtp-pv .dtp-doc')`, 60), 'the draft opens with its preview');
    check(await ready(ev, `/Für Kunde Eins GmbH und/.test(document.querySelector('.dtp-pv .dtp-doc').textContent) && document.querySelector('.dtp-pv mark.dtp-miss')?.textContent === '{{unbekannt}}'`),
      'the preview fills the client and marks the unknown variable ' + await ev(`document.querySelector('.dtp-pv')?.textContent`));
    await shot('p293-a-draft.png');
    await ev(`(() => { document.querySelector('[data-dt="final"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-cd="yes"]')`), 'finish asks first');
    await ev(`(() => { document.querySelector('.modal [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.dtp-final') && !document.querySelector('#dt-body')`, 60), 'finished: the frozen text, no editor');
    check(await ev(`/Für Kunde Eins GmbH und \\./.test(document.querySelector('.dtp-final').textContent) && !!document.querySelector('a[href$="/pdf"]')`), 'finished: the unknown variable is empty, the PDF is there');
    const docs = await ev(api('GET', '/api/office/gen-docs?brief=1'));
    check(docs.docs?.length === 1 && docs.docs[0].status === 'final' && docs.docs[0].node_id, 'the document is final and filed');
    await ev(`(() => { document.querySelector('[data-dt="sgnew"]').click(); return 1; })()`);
    check(await ready(ev, `/\\/s\\/q\\//.test(document.querySelector('[data-dturl]')?.value || '')`, 60), 'the signature link is shown');
    await shot('p293-a-final.png');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the document stays inside the screen');
    await shot('p293-a-final-phone.png');
    // the client page lists the document
    await nav(B + `#client/${cl.id}`);
    check(await ready(ev, `[...document.querySelectorAll('a[href^="#office/gendocs/"]')].some(a => /Kurzvertrag/.test(a.textContent))`, 80), 'the client page lists the document');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/gendocs');  // (the tab row becomes a group menu in 2.92.1: no check on it, the route opens the tab)
    check(await ready(ev, `/Only the admins of the office see documents/.test(document.querySelector('#view')?.textContent || '')`, 80), 'a member gets the hint instead of the documents');
    check(await ev(`!document.querySelector('[data-dt="new"]') && !document.querySelector('[data-go="office/gendocs"], [data-ofm="gendocs"]')`), 'a member has neither the tab nor its buttons');
  }, false);

  console.log(`p293_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
