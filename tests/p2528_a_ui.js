// 2.528.0 UI test, part A (#4305 A3): office settings changed in another session while the page is open. Own container, Firefox.
// kalmido-suite: fresh
// - a field left (autosave) after another session saved ANOTHER field: saved on top, the other change stays and is drawn
// - the SAME field saved elsewhere meanwhile: not overwritten, the error at the field, the typed value stays in it
// - Save of the page (Enter / the bar) after another session set the payment terms: the terms stay (only changed fields go,
//   a newer version = the hint, the current state drawn, the typed values kept), the second save stores them
// the person without an organisation: p2528_a_test.py (freelancer-matrix: office)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2528_a_ui', check, shots: 'P2528A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2528A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');  // the other session (another admin's tab)
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'en', payment_days: 21, reminder_fee: 5, reminder_deadline_days: 10});
  const cur = async () => (await call(CA, 'GET', '/api/office/settings')).settings;
  const srv = async (f, n = 40) => { for (let i = 0; i < n; i++) { const s = await cur(); if (f(s)) return s; await sleep(250); } return null; };
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const typ = (id, v) => `(() => { const el = document.getElementById('${id}'); el.focus(); el.value = ${JSON.stringify(v)}; el.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`;
  const leave = id => `(() => { const el = document.getElementById('${id}'); el.dispatchEvent(new Event('change', {bubbles: true})); el.dispatchEvent(new FocusEvent('focusout', {bubbles: true})); return 1; })()`;
  const val = id => `document.getElementById('${id}')?.value`;
  const mark = id => `document.getElementById('${id}')?.closest('.row')?.querySelector('.ostok')`;

  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
    check(await ready(ev, `!!document.getElementById('os-paydays') && !!OFC.info?.settings?.updated_at`, 80), 'the settings page with its version');

    // 1. another field saved elsewhere, then this page saves its field: both stay, the page shows the other change
    check((await call(CA, 'PUT', '/api/office/settings', {payment_days: 30})).http === 200, 'the other session sets 30 days');
    await ev(typ('os-rmfee', '6')); await ev(leave('os-rmfee'));
    let s = await srv(x => Number(x.reminder_fee) === 6);
    check(s && s.payment_days === 30, `another field: saved on top, the other change stays (${s?.payment_days} ${s?.reminder_fee})`);
    check(await ready(ev, `${val('os-paydays')} === '30' && !${mark('os-rmfee')}?.classList.contains('err')`), 'another field: the page draws the other change, no error');

    // 2. the same field saved elsewhere: not overwritten, the error at the field, the typed value stays
    check((await call(CA, 'PUT', '/api/office/settings', {reminder_fee: 9})).http === 200, 'the other session sets the fee to 9');
    await ev(typ('os-rmfee', '11')); await ev(leave('os-rmfee'));
    check(await ready(ev, `!!${mark('os-rmfee')}?.classList.contains('err')`), 'the same field: the error at the field');
    const fee = Number((await cur()).reminder_fee), shown = await ev(val('os-rmfee'));
    check(fee === 9 && shown === '11', `the same field: the other value stays saved, the typed one stays in the field (${fee} ${shown})`);

    // 3. Save of the page after the other session set the payment terms: the terms stay
    check((await call(CA, 'PUT', '/api/office/settings', {payment_days: 45})).http === 200, 'the other session sets 45 days');
    await ev(typ('os-rmdays', '12'));  // typed, not left yet
    await ev(`(() => { const f = document.getElementById('ofc-set'); f.requestSubmit ? f.requestSubmit() : f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); return 1; })()`);
    check(await ready(ev, `${val('os-paydays')} === '45' && ${val('os-rmdays')} === '12' && ${val('os-rmfee')} === '11'`), 'Save: the current terms drawn, the typed values kept');
    s = await cur();
    check(s.payment_days === 45 && s.reminder_deadline_days === 10, `Save: nothing of the stale page stored (${s.payment_days} ${s.reminder_deadline_days})`);
    await ev(`(() => { const f = document.getElementById('ofc-set'); f.requestSubmit ? f.requestSubmit() : f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); return 1; })()`);
    s = await srv(x => x.reminder_deadline_days === 12);
    check(s && s.payment_days === 45 && Number(s.reminder_fee) === 11, `Save again: the typed values stored, the other session's terms stay (${s?.payment_days} ${s?.reminder_fee})`);
  }, false);

  console.log(`p2528_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
