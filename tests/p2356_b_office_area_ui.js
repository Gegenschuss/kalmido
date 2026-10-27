// kalmido-suite: fresh
// 2.356.0 B (#2932) UI test, jsdom: the office header always names its workspace.
// - a person without an organisation: "Private" as plain text in the office header (no switch to offer)
// - the same person with an own office joins an organisation: the office stays "Private", the header now carries the
//   workspace switch itself (data-act ws-menu); switching to the organisation shows its name there and ONE hint
//   ("This office belongs to the workspace …", setting office_ws_hint), switching back shows no second hint
// freelancer-matrix: office
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const FEATURES = 'cal,collab,comments,contacts,files,docs,clients,office';
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEATURES}, FK);
  const cl = await call('POST', '/api/clients', {name: 'Kunde Beispiel', email: 'kunde@example.com'}, FK);
  check(cl.id, 'setup: the freelancer has a private client');

  // ================= no organisation: the area as text
  let w = await boot({user: 'frida', hash: 'office/offers'}), d = w.document;
  const a0 = await until(() => d.querySelector('.office .ofchead .ofcws'));
  check(a0 && a0.tagName === 'SPAN' && /Private/.test(a0.textContent), 'without an organisation: "Private" in the office header ' + (a0 && a0.outerHTML));
  w.close();

  // ================= joins an organisation (made with her as its admin): the office stays private, the header is the switch
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha Studio', admin_id: fr.id});
  check(org.id, 'setup: an organisation with frida as its admin');
  check((await call('GET', '/api/state', null, FK)).settings.workspace === 'private', '#2932: the workspace stays private');
  w = await boot({user: 'frida', hash: 'office/offers'}); d = w.document;
  const a1 = await until(() => d.querySelector('.office .ofchead button.ofcws'));
  check(a1 && a1.dataset.act === 'ws-menu' && /Private/.test(a1.textContent), '#2932: the office header: "Private" with the workspace switch ' + (a1 && a1.outerHTML));
  const toastHas = () => /This office belongs to the workspace/.test(d.querySelector('#toast')?.textContent || '');
  check(!toastHas(), 'no hint while the area did not change');
  w.wsSet('org:' + org.id);
  check(await until(() => /Alpha Studio/.test(d.querySelector('.office .ofchead .ofcws')?.textContent || '')), '#2932: after the switch the header names the organisation');
  check(await until(toastHas), '#2932: the first change shows the hint once: ' + (d.querySelector('#toast')?.textContent || ''));
  check(await until(async () => (await call('GET', '/api/state', null, FK)).settings.office_ws_hint === '1'), '#2932: the hint is remembered (office_ws_hint)');
  d.querySelector('#toast')?.classList.add('hidden');
  if (d.querySelector('#toast')) d.querySelector('#toast').textContent = '';
  w.wsSet('private');
  check(await until(() => /Private/.test(d.querySelector('.office .ofchead .ofcws')?.textContent || '')), 'back in the private office');
  check(!toastHas(), '#2932: no second hint');
  w.close();

  console.log(`p2356_b_office_area_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
