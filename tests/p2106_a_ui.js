// 2.153.0 UI tests, part A (#2028, office: correspondence -- letters), own container (start.sh, mode workspaces),
// Firefox (desktop + phone width). Invented companies, people and addresses only.
// - the admin has the tab "Correspondence"; a new letter opens its editor; the recipient search offers the client and
//   picking it fills name / address; typing saves the draft by itself; the list shows the letter
// - "Mark as sent" asks for the channel, then the letter is fixed (no editor) and filed
// - the signature dialog saves greeting and name; #office/letters/new opens a new draft
// - the client page lists the client's letters; on a phone nothing sticks out to the side
// - a member does not get the tab (the hint instead)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2106_a_ui', check, shots: 'P2106A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2106A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,contacts';

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
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('#view *')].filter(e => e.getClientRects().length && !e.closest('.seg') && !e.closest('.ofctabs') && !e.closest('.ofmenu')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const click = sel => `(() => { const b = document.querySelector('${sel}'); if (!b) return 0; b.click(); return 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= the tab, a new letter
    await nav(B + '#office/letters');
    check(await ready(ev, `!!document.querySelector('[data-lt="new"]')`, 80), 'the tab "Correspondence" for the admin');
    check(await ev(`/No letters yet/.test(document.querySelector('#view').textContent)`), 'the empty list explains itself');
    await ev(click('[data-lt="new"]'));
    check(await ready(ev, `!!document.querySelector('#lt-body') && !!document.querySelector('#lt-rcpt_name') && !!document.querySelector('#lt-ref_line[name="ref_line"]')`, 60), 'a new letter opens its editor (fields lt-<column>)');
    await ev(`(() => { const s = document.querySelector('#lt-rsearch'); s.focus(); s.value = 'Kunde'; s.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#lt-sug [data-lt="rc"]')].some(b => /Kunde Eins GmbH/.test(b.textContent))`), 'the recipient search offers the client');
    await ev(`(() => { [...document.querySelectorAll('#lt-sug [data-lt="rc"]')].find(b => /Kunde Eins GmbH/.test(b.textContent)).click(); return 1; })()`);
    check(await ev(`document.querySelector('#lt-rcpt_name').value === 'Kunde Eins GmbH' && document.querySelector('#lt-rcpt_address').value === 'Kundenweg 5\\n20000 Hamburg' && document.querySelector('#lt-client_id').value === '${cl.id}'`),
      'picking it fills name, address and the client ' + await ev(`JSON.stringify(document.querySelector('#lt-rcpt_address')?.value)`));
    await ev(`(() => { const s = document.querySelector('#lt-subject'); s.value = 'Kündigung Rahmenvertrag'; s.dispatchEvent(new Event('input', {bubbles: true})); const t = document.querySelector('#lt-body'); t.value = 'Sehr geehrte Damen und Herren,\\n\\nhiermit kündigen wir.'; t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await sleep(2200);  // the quiet save after typing
    const l1 = await ev(api('GET', '/api/office/letters?brief=1'));
    check(l1.letters?.length === 1 && l1.letters[0].subject === 'Kündigung Rahmenvertrag' && l1.letters[0].client_id === cl.id, 'the draft saved itself ' + JSON.stringify(l1.letters?.[0] || {}).slice(0, 160));
    await shot('p2106-a-editor.png');
    // ================= sent
    await ev(click('[data-lt="sent"]'));
    check(await ready(ev, `!!document.querySelector('.modal #lt-schan')`), '"Mark as sent" asks for the channel');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#lt-schan').value = 'registered'; m.querySelector('#lt-schan').dispatchEvent(new Event('change', {bubbles: true})); m.querySelector('#lt-strack').value = 'RR1DE'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && !document.querySelector('#lt-body') && !!document.querySelector('.lt-paper') && !!document.querySelector('[data-lt="delivered"]')`, 60), 'sent: the letter is fixed, "Delivered" offered');
    const s1 = await ev(api('GET', `/api/office/letters/${l1.letters[0].id}`));
    check(s1.status === 'sent' && s1.channel === 'registered' && s1.tracking_no === 'RR1DE' && s1.node_id, 'sent by registered mail and filed');
    check(await ev(`/RR1DE/.test(document.querySelector('.lt-facts').textContent) && !!document.querySelector('a[href="#docs/${s1.node_id}"]')`), 'the facts with the tracking number and the link to the document');
    await shot('p2106-a-sent.png');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the letter stays inside the screen');
    await shot('p2106-a-sent-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= the list, the signature, a new letter through the address
    await ev(click('[data-lt="back"]'));
    check(await ready(ev, `[...document.querySelectorAll('.lt-list .ofcrow')].some(b => /Kunde Eins GmbH/.test(b.textContent) && /Kündigung/.test(b.textContent))`, 60), 'the list shows the letter');
    await ev(click('[data-lt="profile"]'));
    check(await ready(ev, `!!document.querySelector('.modal #lt-pgreet')`), 'the signature dialog');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#lt-pgreet').value = 'Beste Grüße'; m.querySelector('#lt-pname').value = 'Alice Beispiel'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal')`), 'the signature saved');
    const pr = await ev(api('GET', '/api/office/letters/profile'));
    check(pr.greeting === 'Beste Grüße' && pr.name === 'Alice Beispiel', 'the profile has greeting and name');
    await nav(B + '#office/letters/new');
    check(await ready(ev, `/^#office\\/letters\\/\\d+$/.test(location.hash) && document.querySelector('#lt-greeting')?.value === 'Beste Grüße'`, 80), '#office/letters/new opens a new draft with the profile');
    // ================= the client page
    await nav(B + `#client/${cl.id}`);
    check(await ready(ev, `[...document.querySelectorAll('a[href^="#office/letters/"]')].some(a => /Kündigung/.test(a.textContent))`, 80), 'the client page lists the letter');
    // ================= member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/letters');
    check(await ready(ev, `/Only the admins of the office see the correspondence/.test(document.querySelector('#view')?.textContent || '')`, 80), 'a member gets the hint instead of the letters');
    check(await ev(`!document.querySelector('[data-lt="new"]')`), 'a member has no button to write a letter');
  }, false);

  console.log(`p2106_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
