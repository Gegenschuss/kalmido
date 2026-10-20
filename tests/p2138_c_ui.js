// 2.138.0 UI tests, part C, own container (start.sh, with a server key). Invented names only.
// #1907: the calendar subscription link and the upload token are shown once. Settings > Integrations: "Create
// subscription link" shows the link with "Only visible now"; after a reload only "active since" + New link / Turn off (no
// link); New link (confirmed) shows a new one. Share from your phone: no token field before a token exists, "Create upload
// token" shows it once, after a reload only "Active since".
// #1972: Settings > Organisation > Encryption:
// - the box offers "Show recovery key" and "New recovery key" and says that the full renewal runs on the command line
// - "Show" asks for the password and shows the key once in a dialog ("R2-" + 13 groups, warning, copy button)
// - "New" asks first (the current key stops working), then the password, and shows a different key with the hint "new"
// - the News text for the other admins names who did what, never the value; the personal office box stays hidden
//   for a person without a personal office
// P2138C_NOSTART=1 = the server already runs (with a KALMIDO_SECRET_KEY).
const path = require('path');
const crypto = require('crypto');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const KEY = crypto.randomBytes(32).toString('base64');
if (process.env.P2138C_NOSTART !== '1') {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} -e KALMIDO_SECRET_KEY=${KEY} -e KALMIDO_ORGCRYPT_DELAY=0`}});
}
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const submit = (w, form) => form && form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients';
const RK_RE = /^R2(-[A-Z2-7]{4}){13}$/;

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});

  // ================= #1907 calendar subscription: the link once
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('ical')`);
  const cb = await until(() => d.querySelector('#sp-integr:not(.hidden) [data-m="ical-create"]'));
  check(cb, 'Integrations: create link button');
  cb?.click();
  const inp = await until(() => d.querySelector('#s-icalurl'));
  const url = inp?.value || '';
  check(/^https:\/\/kalmido\.example\/ical\/\d+\.[\w-]{40,}\.ics$/.test(url), 'link shown after creating: ' + url.slice(0, 40));
  check(/Only visible now/.test(d.querySelector('#s-ical')?.textContent || ''), 'hint: only visible now');
  check(d.querySelector('#s-ical [data-m="ical-copy"]') && d.querySelector('#s-ical a[href^="webcal://"]'), 'copy + open in calendar app');
  w.close();

  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('ical')`);
  const act = await until(() => d.querySelector('#s-icalact'));
  check(act && /Subscription link active since/.test(act.textContent), 'after a reload: active since ' + (act?.textContent || ''));
  check(!d.querySelector('#s-icalurl') && !(d.querySelector('#s-ical')?.innerHTML || '').includes('/ical/'), 'after a reload: no link on the page');
  check(d.querySelector('#s-ical [data-m="ical-rotate"]') && d.querySelector('#s-ical [data-m="ical-off"]'), 'New link + Turn off');
  d.querySelector('#s-ical [data-m="ical-rotate"]')?.click();
  (await until(() => d.querySelector('[data-cd="yes"]')))?.click();
  const inp2 = await until(() => d.querySelector('#s-icalurl'));
  check(inp2 && inp2.value !== url && /\/ical\//.test(inp2.value), 'New link: the new link is shown once');
  check((await fetch(B + url.replace('https://kalmido.example/', ''))).status === 404, 'the old link stopped');
  w.close();

  // ================= upload token: shown once
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('share')`);
  const nb = await until(() => d.querySelector('#s-dropw [data-m="drop-new-tok"]'));
  check(nb && !d.querySelector('#s-droptok'), 'no token field before a token exists');
  nb?.click();
  const ti = await until(() => d.querySelector('#s-droptok'));
  check(ti && ti.value.length >= 24 && /Only visible now/.test(d.querySelector('#s-dropw')?.textContent || ''), 'the new token once, with the hint');
  const tok = ti?.value || '';
  const r = await fetch(B + 'drop', {method: 'POST', headers: {Authorization: 'Bearer ' + tok}, body: new URLSearchParams({text: 'UI token works'})});
  check(r.ok, 'the shown token works for /drop');
  w.close();

  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('share')`);
  const dw = await until(() => d.querySelector('#s-dropw'));
  check(dw && /Active since/.test(dw.textContent) && !d.querySelector('#s-droptok') && !d.body.innerHTML.includes(tok), 'after a reload: only Active since, no token');
  check(/Each download contains a new upload token/.test(d.querySelector('#sp-integr')?.textContent || ''), 'the HTTP Shortcuts download says it makes a new token');
  w.close();

  check(errs.length === 0, 'no JS errors (#1907): ' + errs.slice(0, 3).join(' | '));

  // ================= #1972 recovery key
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  check((await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'admin'})).status === 200, 'bob is an admin of the organisation');

  // ================= the box
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('org')`);
  const box = await until(() => d.querySelector(`#s-ws .ocbox[data-ocorg="${ORG}"] [data-oc="show"]`) && d.querySelector(`#s-ws .ocbox[data-ocorg="${ORG}"]`));
  check(!!box, 'the encryption box of the organisation');
  check(box && /New recovery key/.test(box.querySelector('[data-oc="new"]')?.textContent || ''), 'button "New recovery key"');
  check(box && /command line/.test(box.textContent) && /SELF-HOSTING\.md/.test(box.textContent), 'hint: the full renewal on the command line');
  const pbox = d.querySelector('#s-ws .ocbox[data-ocorg="0"]');
  await until(() => pbox && pbox.hidden);
  check(!pbox || pbox.hidden, 'no personal office: its box stays hidden');

  // ================= show: password, then the key once
  click(w, box.querySelector('[data-oc="show"]'));
  let pw = await until(() => d.querySelector('.pwprompt #pp-pw'));
  check(!!pw && !d.querySelector('.pwprompt #pp-code'), 'show: asks for the password (no code without the app)');
  pw.value = 'password123'; submit(w, d.querySelector('.pwprompt form'));
  const rk = await until(() => d.querySelector('#oc-rk'));
  const RK1 = rk ? rk.textContent.trim() : '';
  check(RK_RE.test(RK1), 'show: the key "R2-" + 13 groups ' + RK1.slice(0, 8));
  const md = rk && rk.closest('.modal') || d.body;
  check(/never send it by e-mail or chat/.test(md.textContent) && !!md.querySelector('[data-m="copy"]'), 'show: warning and copy button');
  check(!/earlier ones no longer work/.test(md.textContent), 'show: the first recovery key has no "new" hint');
  click(w, md.querySelector('[data-m="close"]'));  // the dialog's own Done (the settings dialog has one too)
  check(await until(() => !d.querySelector('#oc-rk')), 'show: Done closes the dialog');

  // ================= new: confirm, password, a different key
  await until(() => d.querySelector(`#s-ws .ocbox[data-ocorg="${ORG}"] [data-oc="new"]`));
  click(w, d.querySelector(`#s-ws .ocbox[data-ocorg="${ORG}"] [data-oc="new"]`));
  const ask = await until(() => d.querySelector('.cdlg'));
  check(ask && /stops working at once/.test(ask.textContent), 'new: asks first (the current key stops working)');
  submit(w, ask && ask.querySelector('form'));
  pw = await until(() => d.querySelector('.pwprompt #pp-pw'));
  if (pw) { pw.value = 'password123'; submit(w, d.querySelector('.pwprompt form')); }
  const rk2 = await until(() => d.querySelector('#oc-rk'));
  const RK2 = rk2 ? rk2.textContent.trim() : '';
  check(RK_RE.test(RK2) && RK2 !== RK1, 'new: a different key');
  check(/earlier ones no longer work/.test(rk2 ? rk2.closest('.modal').textContent : ''), 'new: the hint that earlier keys no longer work');
  click(w, rk2 && rk2.closest('.modal').querySelector('[data-m="close"]'));
  w.close();

  // ================= the other admin's News: who and what, never the value
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CKB);
  const items = ((await call('GET', '/api/news', null, CKB)).items || []).filter(x => x.kind === 'orgkey');
  check(items.length >= 1 && !JSON.stringify(items).includes(RK2.slice(3, 12)), 'bob: News items "orgkey" without the value');
  w = await boot({user: 'bob'}); d = w.document;
  const txt = w.eval(`ocNewsText({org: 'Kalmido', action: 'new'}, '<b>Alice</b>', x => '<b>' + x + '</b>')`);
  check(/Alice<\/b> made a new recovery key for <b>Kalmido/.test(txt), 'News text: who made a new recovery key ' + txt);
  check(/renewed on the server/.test(w.eval(`ocNewsText({org: 'Kalmido', action: 'rotated'}, '', x => x)`)), 'News text: the key was renewed');
  w.close();

  console.log(`p2138_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
