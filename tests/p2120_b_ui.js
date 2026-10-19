// 2.120.0 UI tests, part B (#2088 the customer portal with quotations, invoices and their payment status), own container
// (start.sh, mode workspaces, no mail server), Firefox (desktop + phone width). Invented companies, people and figures only.
// - the office settings show the switch "Show documents in the customer portal" (off by default, on after saving it)
// - the client's menu "More" offers "Send portal link"; it asks first (the address in the question) and says plainly
//   when mail is not set up on the server
// - the portal /portal (signed in by a sign-in link): heading "Customer portal", the documents with their payment state,
//   the open amount and the due date; on a phone the list stays inside the screen, the rows are big targets
// - a person without organisation: the switch in the personal office and "Send portal link" on a private client
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2120_b_ui', check, shots: 'P2120B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
if (process.env.P2120B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const COMPANY = {street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', email: 'hallo@studio.example', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'};
// a sign-in link of the portal as "Send portal link" makes it (team/portal.py portal_logins), made inside the container
// because the address hash needs the server key -> the one-time token
const signinLink = (mail, org) => execFileSync('docker', ['exec', CT, 'python', '-c',
  "import sys, secrets, app\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.core.db import iso, now_utc\nfrom datetime import timedelta\n" +
  "from kalmido.team.portal import pt_email_hash\nfrom kalmido.accounts.session import _token_hash\nc = app.connect()\ntok = secrets.token_urlsafe(32)\n" +
  "with system_ctx(c):\n    c.execute('INSERT INTO portal_logins(email_hash,org_id,owner_id,token_hash,created_at,expires_at) VALUES(?,?,NULL,?,?,?)', " +
  "(pt_email_hash(c, sys.argv[1]), int(sys.argv[2]), _token_hash(tok), iso(now_utc()), iso(now_utc() + timedelta(minutes=30))))\nc.commit()\nprint(tok)",
  mail, String(org)]).toString().trim().split('\n').pop();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Frei', password: 'password123', email: 'frida@example.com'});
  const CF = await login('frida');
  for (const ck of [CA, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  for (const [ck, name] of [[CA, 'Studio Nordlicht GmbH'], [CF, 'Frida Frei Design']]) {
    const s = await call(ck, 'PUT', '/api/office/settings', {company: {name}, lang: 'en', company_fields: {name, ...COMPANY}});
    check(s.http === 200, 'office settings ' + s.http);
  }
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Xaver GmbH', email: 'kontakt@xaver.example.com', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'});
  const fcl = await call(CF, 'POST', '/api/clients', {name: 'Privatkunde Quer', email: 'quer@example.com', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: '2026-05-01', items: [{title: 'Beratung', qty: 1, rate: 1000}]});
  check((await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`)).http === 200, 'finalised');
  await call(CA, 'POST', `/api/office/docs/${inv.id}/status`, {status: 'sent'});
  await call(CA, 'POST', `/api/office/docs/${inv.id}/payments`, {date: '2026-06-01', amount: '100.00', method: 'transfer'});
  const off = await call(CA, 'POST', '/api/office/docs', {client_id: cl.id, project_title: 'Imagefilm Hafen mit einem sehr langen Projekttitel für das schmale Telefon', items: [{title: 'Dreh', qty: 1, rate: 900}]});
  await call(CA, 'POST', `/api/office/docs/${off.id}/status`, {status: 'sent'});
  await call(CA, 'POST', `/api/office/docs/${off.id}/signoff`, {});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const menuItem = `[...document.querySelectorAll('#pop [role=menuitem]')].find(b => /Send portal link/.test(b.textContent))`;
  // the client's menu: "Send portal link" -> the question (with the address) -> without mail on the server a plain toast
  const portalLink = async (ev, nav, cid, mail, tag) => {
    await nav(B + '?p=' + tag + '#client/' + cid);
    await ready(ev, `!!document.querySelector('[data-mscl="cmenu"]')`, 80);
    await ev(`(() => { document.querySelector('[data-mscl="cmenu"]').click(); return 1; })()`);
    check(await ready(ev, `!!${menuItem}`), `${tag}: #2088 the client's menu offers "Send portal link"`);
    await ev(`(() => { ${menuItem}.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.cdlg') && document.querySelector('.modal.cdlg').textContent.includes('${mail}')`), `${tag}: #2088 it asks first, with the address`);
    await ev(`(() => { document.querySelector('.modal.cdlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `/switched off|not set up/i.test((document.querySelector('#toast') || {}).textContent || '')`), `${tag}: #2088 a plain answer when it cannot be sent`);
  };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ---- the setting
    await nav(B + '?p=1#office/settings');
    check(await ready(ev, `!!document.querySelector('#os-portal-docs')`, 80), '#2088: the office settings show the portal switch');
    check(await ev(`!document.querySelector('#os-portal-docs').checked`), '#2088: off by default');
    await call(CA, 'PUT', '/api/office/settings', {portal_docs: 1});
    await nav(B + '?p=2#office/settings');
    check(await ready(ev, `!!document.querySelector('#os-portal-docs') && document.querySelector('#os-portal-docs').checked`, 80), '#2088: on after saving');
    await ev(`(() => { document.querySelector('#os-portal-docs').scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
    await shot('p2120-b-setting.png');
    // ---- "Send portal link" (no mail server in this container)
    await portalLink(ev, nav, cl.id, 'kontakt@xaver.example.com', 'desk');
    await shot('p2120-b-client-toast.png');
    // ---- the portal on a phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'portal/login/' + signinLink('kontakt@xaver.example.com', org.id));
    await ready(ev, `!!document.querySelector('form button')`);
    await ev(`(() => { document.querySelector('form button').click(); return 1; })()`);
    check(await ready(ev, `location.pathname === '/portal' && !!document.querySelector('ul.kpdocs li')`), '#2088: signed in, the documents are listed');
    const p = await ev(`(() => { const li = [...document.querySelectorAll('ul.kpdocs li')]; const W = document.documentElement.clientWidth;
      return {h1: (document.querySelector('h1') || {}).textContent || '', n: li.length, text: document.querySelector('ul.kpdocs').textContent,
        wide: document.documentElement.scrollWidth <= 390, inside: li.every(x => x.getBoundingClientRect().right <= W + 1),
        rows: Math.min(...li.map(x => x.querySelector('a').getBoundingClientRect().height)),
        go: Math.min(...[...document.querySelectorAll('a.kpgo')].map(x => x.getBoundingClientRect().height))}; })()`);
    check(p && p.h1 === 'Customer portal' && p.n === 2, '#2088: the heading and both documents ' + JSON.stringify(p && {h1: p.h1, n: p.n}));
    check(p && /Partly paid/.test(p.text) && /open/.test(p.text) && /due/.test(p.text), '#2088: the payment state, the open amount and the due date ' + (p && p.text));
    check(p && /Review and approve/.test(p.text), '#2088: the open quotation offers its approval page');
    check(p && p.wide && p.inside, '#2088: the list fits the phone ' + JSON.stringify(p));
    check(p && p.rows >= 44 && p.go >= 44, '#2088: big targets on the phone ' + JSON.stringify(p && {rows: p.rows, go: p.go}));
    await shot('p2120-b-portal-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ---- a person without organisation: the personal office
    await nav(B + 'static/icon.svg');
    await signIn(ev, 'frida');
    await nav(B + '?p=3#office/settings');
    check(await ready(ev, `!!document.querySelector('#os-portal-docs')`, 80), 'freelancer: #2088 the switch in the personal office');
    await portalLink(ev, nav, fcl.id, 'quer@example.com', 'frida');
  });

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
