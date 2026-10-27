// kalmido-suite:
// 2.357.0 C (#3158) UI: "With my signature" is always offered, without a picture it opens the setup. Own container (start.sh),
// Firefox. Invented companies, people and addresses only; the signature is drawn here.
// - a letter draft shows the box "With my signature" also without a signature picture (was hidden); ticking it opens the
//   signature dialog with the drawing field, the box stays off until a picture is saved
// - drawing on the field and saving stores the picture (profile has_image) and ticks the box; the letter saves sign_image = 1
// - a document from a template shows the same box
// freelancer-matrix: office (the API part: tests/p2357_c_signature_test.py runs the person without organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2357_c_signature_ui', check, shots: 'P2357C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2357C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,contacts';

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
  await call(CA, 'PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Kundenweg 5', zip: '20000', city: 'Hamburg', country: 'DE'});
  const lt = await call(CA, 'POST', '/api/office/letters', {rcpt_name: 'Amt fuer Beispiele', rcpt_address: 'Musterweg 1\n12345 Musterstadt', subject: 'Anfrage', body: 'Text.'});
  check(lt.http === 201 && lt.sign_image === 0, 'a letter without a signature picture ' + lt.http);
  const gd = await call(CA, 'POST', '/api/office/gen-docs', {client_id: cl.id, title: 'Vertrag', body: 'Text.', sign: 1});
  check(gd.http === 201, 'a document from a template ' + gd.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const api = (m, u) => `fetch('${u}', {method: '${m}', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + `#office/letters/${lt.id}`);
    check(await ready(ev, `!!document.querySelector('#lt-sign_image')`, 80), '#3158: the box "With my signature" shows without a picture');
    check(await ev(`!document.querySelector('#lt-sign_image').checked && /With my signature/.test(document.querySelector('#lt-sign_image').closest('label').textContent)`), '#3158: it is off and named "With my signature"');
    await ev(`(() => { document.querySelector('#lt-sign_image').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal canvas.lt-pad')`), '#3158: ticking it opens the setup with the drawing field');
    check(await ev(`!document.querySelector('#lt-sign_image').checked`), '#3158: the box stays off until a picture is saved');
    // draw a stroke with pointer events
    await ev(`(() => { const c = document.querySelector('.modal canvas.lt-pad'), r = c.getBoundingClientRect();
      const ev = (t, x, y) => c.dispatchEvent(new PointerEvent(t, {bubbles: true, pointerId: 1, clientX: r.left + x, clientY: r.top + y, isPrimary: true}));
      ev('pointerdown', 20, 40); for (let i = 1; i <= 30; i++) ev('pointermove', 20 + i * 8, 40 + (i % 2 ? 20 : -10)); ev('pointerup', 260, 40); return 1; })()`);
    await ev(`(() => { document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelector('#lt-sign_image')?.checked === true`, 60), '#3158: saving the drawing closes the dialog and ticks the box');
    const pr = await ev(api('GET', '/api/office/letters/profile'));
    check(pr.has_image === true && /^data:image\/png;base64,/.test(pr.image || ''), '#3158: the drawn signature is stored as PNG');
    check(await ready(ev, `${api('GET', `/api/office/letters/${lt.id}`)}.then(j => j.sign_image === 1)`, 40), '#3158: the letter saved sign_image = 1');
    await nav(B + `#office/gendocs/${gd.id}`);
    check(await ready(ev, `!!document.querySelector('#dt-sign_image')`, 80), '#3158: a document from a template offers "With my signature"');
  }, false);

  console.log(`p2357_c_signature_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
