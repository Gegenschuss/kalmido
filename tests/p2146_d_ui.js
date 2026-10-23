// 2.146.0 UI tests, part D (#2468, the retention export before deleting an account / an organisation), own container
// (start.sh, mode workspaces), Firefox. Invented companies, clients and figures only. freelancer-matrix: office
// - a person without organisation (personal office, a finalised invoice): Settings > Data of the office shows the box
//   "Retention export" with its 8 / 10 years note and the download link of the own records
// - the instance admin deletes that account: the retention step comes first (records counted for nobody but the person,
//   no download for the admin), "Continue" only after a choice; with the waiver and the confirmation the account goes;
//   Cancel in the step leaves it
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2146_d_ui', check, shots: 'P2146D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2146D_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const mk = async name => {
    const u = await call(CA, 'POST', '/api/users', {username: name, display_name: name[0].toUpperCase() + name.slice(1), password: 'password123', email: `${name}@example.com`, orgs: []});
    check(u.http < 300, 'a person without organisation ' + u.http);
    const ck = await login(name);
    await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
    await call(ck, 'PUT', '/api/office/settings', {company_fields: {name: 'Studio ' + name, street: 'Teststrasse 1', zip: '20000', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001'}});
    const cl = await call(ck, 'POST', '/api/clients', {name: 'Client Ltd', street: 'Marktstrasse 5', zip: '50000', city: 'Koeln', country: 'DE'});
    const d = await call(ck, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: '2026-03-01', service_to: '2026-03-02', items: [{title: 'Schnitt', qty: 1, rate: 120}]});
    check((await call(ck, 'POST', `/api/office/docs/${d.id}/finalize`)).http < 300, 'setup: a finalised invoice of ' + name);
    // 2.186.0 A (#2599): a running period retires the office without the retention step: the records into 2014 (period over)
    for (const t of ['office_docs', 'office_archive']) execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, `UPDATE ${t} SET date='2014-03-02' WHERE org_id IN (SELECT id FROM orgs WHERE personal_of=${+u.id})`]);
    return u.id;
  };
  const FID = await mk('frida');
  check(((await call(await login('frida'), 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone first
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.ofcSetSub', '"data"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('.rxbox a[data-rxdl]')`, 80), 'office settings > data: the retention export box');
    check(await ev(`document.querySelector('.rxbox a[data-rxdl]').getAttribute('href') === '/api/retention/me/export.zip' && document.querySelector('.rxbox a[data-rxdl]').hasAttribute('download')`), 'the download link of the own records');
    check(await ev(`/8 years/.test(document.querySelector('.rxbox').textContent) && /10 years/.test(document.querySelector('.rxbox').textContent)`), 'the 8 / 10 years note');
    await ev(`document.querySelector('.rxbox').scrollIntoView({block: 'center'})`);
    await shot('p2146-d-settings.png');

    // the instance admin deletes frida
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#inbox');
    check(await ready(ev, `typeof ua8_delete === 'function' && typeof rxAsk === 'function'`, 80), 'the app is loaded');
    await ev(`(() => { window.__del = 'pending'; ua8_delete({id: ${FID}, display_name: 'Frida'}).then(v => { window.__del = v; }); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [name="rxhow"]')`, 60), 'the retention step comes first');
    check(await ev(`document.querySelector('.modal [data-m="go"]').disabled`), '"Continue" waits for a choice');
    check(await ev(`!document.querySelector('.modal [data-rxdl]') && !document.querySelector('.modal .rxcounts')`), 'the admin gets no download and no counts');
    check(await ev(`/8 years/.test(document.querySelector('.modal').textContent)`), 'the step names the years');
    await shot('p2146-d-step.png');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    check(await ready(ev, `window.__del === false`, 40), 'cancel: nothing deleted');
    check((await call(CA, 'GET', `/api/users/${FID}/delete-info`)).http === 200, 'frida is still there');

    await ev(`(() => { window.__del = 'pending'; ua8_delete({id: ${FID}, display_name: 'Frida'}).then(v => { window.__del = v; }); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [name="rxhow"]')`, 60), 'the step again');
    await ev(`(() => { const i = document.querySelector('.modal [name="rxhow"][value="waived"]'); i.checked = true; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ev(`!document.querySelector('.modal [data-m="go"]').disabled`), 'a choice enables "Continue"');
    await ev(`(() => { document.querySelector('.modal [data-m="go"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-cd="yes"]') && !document.querySelector('.modal [name="rxhow"]')`, 60), 'then the usual question');
    await ev(`(() => { document.querySelector('.modal [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `window.__del === true`, 60), 'deleted with the waiver ' + await ev('String(window.__del)'));
    check((await call(CA, 'GET', `/api/users/${FID}/delete-info`)).http === 404, 'frida is gone');
  }, false);

  console.log(`p2146_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
