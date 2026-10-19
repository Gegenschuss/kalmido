// 2.114.4 UI test, part B (#2270, office: the order confirmation block of a quotation optional), own container (start.sh,
// mode workspaces), Firefox in a phone viewport. Invented companies and figures only. freelancer-matrix: office
// - the office settings show the switch "Print the order confirmation with signature line", on by default
// - the quotation editor shows the choice "Order confirmation with signature line" (like the settings (on) / on / off) in
//   the texts section; choosing "off" saves it (API accept_on 0) and the choice stays after a reload
// - a finalised quotation shows its frozen value and the choice is locked
// - an organisation's admin and a person without organisation alike; no horizontal scrolling on the phone
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21144_b_ui', check, shots: 'P21144B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21144B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  const prep = async (ck, who) => {
    const cl = await call(ck, 'POST', '/api/clients', {name: 'Example Media Ltd', street: 'Harbour Road 1', zip: '20457', city: 'Hamburg', country: 'DE'});
    const q = await call(ck, 'POST', '/api/office/docs', {kind: 'offer', project_title: 'Image film', client_id: cl.id, items: [{title: 'Concept', qty: 1, rate: 800}]});
    const f = await call(ck, 'POST', '/api/office/docs', {kind: 'offer', project_title: 'Frozen film', client_id: cl.id, items: [{title: 'Edit', qty: 1, rate: 500}]});
    check(q.http === 201 && f.http === 201, `${who}: two quotations`);
    check((await call(ck, 'PATCH', `/api/office/docs/${f.id}`, {accept_on: 0})).accept_on === 0, `${who}: the second quotation off`);
    const fin = await call(ck, 'POST', `/api/office/docs/${f.id}/finalize`);
    check(fin.locked === true, `${who}: the second quotation finalised ${fin.http}`);
    return {q: q.id, f: f.id};
  };
  const docs = {alice: await prep(CA, 'org'), frida: await prep(CF, 'freelancer')};

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noScroll = `document.documentElement.scrollWidth <= window.innerWidth + 1`;
  const sel = `document.getElementById('ofd-accept_on')`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    for (const [u, who, ck] of [['alice', 'org', CA], ['frida', 'freelancer', CF]]) {
      const {q, f} = docs[u];
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await signIn(ev, u);
      // the settings page
      await nav(B + '#office/settings');
      check(await ready(ev, `!!document.getElementById('os-accept-on')`, 80), `${who}: the switch on the settings page`);
      check(await ev(`document.getElementById('os-accept-on').checked === true && /Print the order confirmation with signature line/.test(document.getElementById('os-accept-on').closest('label').textContent)`), `${who}: the switch is on by default`);
      // the editor
      await nav(B + `#office/offers/${q}`);
      check(await ready(ev, `!!${sel}`, 80), `${who}: the choice in the editor`);
      check(await ev(`${sel}.value === '' && /Like the settings \\(on\\)/.test(${sel}.options[0].textContent) && ${sel}.options.length === 3 && !${sel}.disabled`), `${who}: "like the settings (on)", three options, editable -- ` + await ev(`${sel}.outerHTML.slice(0, 300)`));
      check(await ev(`/Order confirmation with signature line/.test(document.querySelector('label[for="ofd-accept_on"]')?.textContent || '')`), `${who}: the label of the choice`);
      await ev(`(() => { const s = ${sel}; s.closest('details') && (s.closest('details').open = true); s.value = '0'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
      let saved = false;
      for (let i = 0; i < 20 && !saved; i++) { await sleep(250); saved = (await call(ck, 'GET', `/api/office/docs/${q}`)).accept_on === 0; }
      check(saved, `${who}: "off" is saved (accept_on 0)`);
      check(await ev(noScroll), `${who}: editor without horizontal scrolling on the phone`);
      if (u === 'alice') { await ev(`(() => { ${sel}.scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300); await shot('p21144-b-editor.png'); }
      await nav(B + 'static/icon.svg');
      await nav(B + `#office/offers/${q}`);
      check(await ready(ev, `!!${sel} && ${sel}.value === '0'`, 80), `${who}: "off" stays after a reload -- ` + await ev(`${sel}?.value`));
      // the finalised quotation: frozen value, locked
      await nav(B + `#office/offers/${f}`);
      check(await ready(ev, `!!${sel} && ${sel}.value === '0'`, 80), `${who}: the finalised quotation shows its frozen "off"`);
      check(await ev(`${sel}.disabled || ${sel}.matches(':disabled')`), `${who}: the choice is locked on a finalised quotation`);
    }
  }, true);
  console.log(`p21144_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
